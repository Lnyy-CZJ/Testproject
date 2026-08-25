"""API 测试智能体 V2 阶段式 Runner；本模块绝不发送目标 API 请求。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import time
import traceback
import sys
from pathlib import Path
from typing import Any

from agents.api_test.cases.coverage import build_coverage
from agents.api_test.cases.business_supplement import create_business_supplementer
from agents.api_test.cases.executable import build_executable_cases, executable_prompt_sha256
from agents.api_test.cases.fused_kernel import GenerationContext, generate_fused_cases
from agents.api_test.contracts.format_detector import DocumentFormat, detect_document_format
from agents.api_test.contracts.openapi_parser import parse_openapi_document
from agents.api_test.contracts.unstructured_parser import parse_unstructured_document, split_sections
from agents.api_test.workflows.contract_analysis_workflow import ContractAnalysisWorkflow
from agents.api_test.workflows.api_basecase_workflow import ApiBaseCaseGeneratorWorkFlow
from agents.api_test.workflows.api_run_case_wrokflow import ApiRunCaseGeneratorWorkFlow
from services.api_agent.document_service import DocumentRevisionService
from services.api_agent.models import (
    AnalysisScopeVersion, ApiContract, BaseTestCase, DocumentRevision, ExecutableCase,
    CoverageMatrix, GenerationProvenance, StageEvent, WorkflowRuntimeContext,
)
from services.api_agent.stage_events import StageEventStore
from services.api_agent.v2_store import ApiV2Store
from services.common.artifacts import merge_registry, publish_artifact
from services.common.errors import ServiceError, classify_runner_exception, structured_log
from services.common.task_store import TaskStore


def _publish_json(store: TaskStore, task_id: str, name: str, payload: Any, stage: str) -> None:
    """原子保存并立即登记单个阶段产物，后续失败不会令其消失。"""

    output = store.task_dir(task_id) / "work" / "output"
    output.mkdir(parents=True, exist_ok=True)
    path = output / name
    TaskStore.atomic_write_json(path, payload)
    artifact = publish_artifact(
        store, task_id, path, artifact_type=f"api_v2_{path.stem}",
        stage=stage, destination_group="stages",
    )
    merge_registry(store, task_id, [artifact])


def _append_event_safely(store: TaskStore, event: StageEvent) -> None:
    """尽力保存阶段记录；可观察性故障不能破坏阶段主产物。"""

    try:
        StageEventStore(store).append(event)
    except (OSError, TypeError, ValueError):
        return


def _finish_attempt(store: TaskStore, task_id: str, attempt_id: str, *, status: str, stage: str, error_code: str | None = None) -> None:
    """更新当前 Attempt 的结果，不删除过去 Attempt。"""

    path = store.task_dir(task_id) / "attempts" / attempt_id / "attempt.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    payload.update({"status": status, "completed_stage": stage, "error_code": error_code})
    TaskStore.atomic_write_json(path, payload)


def _initial_stage(store: TaskStore, task_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
    """执行格式预检、确定性或 LLM 契约解析，并进入契约 Review。"""

    task_dir = store.task_dir(task_id)
    versions = ApiV2Store(store)
    document_version = int(request_payload.get("document_version", 0) or 0)
    scope_version = int(request_payload.get("scope_version", 0) or 0)
    if document_version and scope_version:
        document_envelope = versions.load_version(task_id, "documents", document_version)
        scope_envelope = versions.load_version(task_id, "analysis-scopes", scope_version)
        document = DocumentRevision.model_validate(document_envelope["items"])
        scope = AnalysisScopeVersion.model_validate(scope_envelope["items"])
        if scope.document_version != document.version:
            raise ServiceError(422, "ANALYSIS_SCOPE_INVALID", "分析范围未绑定所选文档版本")
        text = document.content
        source_name = document.source_filename
        source_id = document.content_sha256
    else:
        source = task_dir / request_payload["input_relative_path"]
        text = source.read_text(encoding="utf-8")
        source_name = request_payload.get("input_original_name", source.name)
        source_id = request_payload["input_sha256"]
        scope = None
    document_format, structured, profile = detect_document_format(text, source_name)
    _publish_json(store, task_id, "document-profile.json", profile.as_dict(), "document_preflight")
    _append_event_safely(store, StageEvent(
        event_id=f"event_{secrets.token_hex(10)}", task_id=task_id,
        attempt_id=str(request_payload.get("attempt_id", "")), stage="document_preflight",
        node="format_detector", event_type="artifact", status="succeeded",
        message=f"文档预检完成：{document_format.value}",
    ))
    minimum_score = float(os.getenv("CONTRACT_QUALITY_MIN_SCORE", "0.8"))
    generation_kernel = str(request_payload.get("generation_kernel", "v2_minimal"))
    if generation_kernel == "v2_core_workflow":
        # V2.4 主路径由旧核心节点重新编排后的 ContractAnalysisWorkflow 负责。
        # Runner 仅注入模型/事件端口并持久化结果，不能在图外重复拼装契约。
        attempt_id = str(request_payload.get("attempt_id", ""))
        events = StageEventStore(store)
        legacy_parser = None
        if document_format not in {DocumentFormat.OPENAPI_3, DocumentFormat.SWAGGER_2} and os.getenv("DASHSCOPE_API_KEY"):
            from agents.api_test.parsers.ai_parser_api_document import AIAPIDocumentParser
            from agents.common.config.settings import llm

            legacy_parser = lambda document: AIAPIDocumentParser().parser(
                document,
                model_invoker=lambda prompt: events.invoke_model(
                    task_id, attempt_id=attempt_id, stage="document_parsing",
                    node="legacy_ai_parse", prompt_id="api_document_parser.prompt",
                    prompt=prompt, model=llm,
                ),
            )
        runtime = WorkflowRuntimeContext(
            task_id=task_id,
            attempt_id=attempt_id,
            workflow_id="contract_analysis_workflow",
            workflow_version="2.4.0",
            input_versions={
                key: int(value) for key, value in request_payload.get("source_versions", {}).items()
                if isinstance(value, int)
            },
            event_sink=lambda event: _append_event_safely(store, event),
        )
        workflow_result = ContractAnalysisWorkflow(legacy_parser=legacy_parser).run(
            document_text=text, filename=source_name, runtime=runtime,
        )
        contracts = [ApiContract.model_validate(item) for item in workflow_result.items]
        if workflow_result.status == "failed" and not contracts:
            raise ServiceError(422, "CONTRACT_WORKFLOW_FAILED", "核心契约解析工作流未生成有效候选")
        events.save_provenance(task_id, GenerationProvenance(
            attempt_id=attempt_id,
            generation_kernel="v2_core_workflow",
            contract_ids=[item.contract_id for item in contracts],
            input_versions=runtime.input_versions,
            prompt_ids=sorted(workflow_result.workflow_provenance.prompt_sha256),
            prompt_sha256=workflow_result.workflow_provenance.prompt_sha256,
            rejected_case_count=len(workflow_result.rejections),
            ai_supplement_status="partial" if workflow_result.rejections and contracts else (
                "failed" if workflow_result.rejections else "succeeded"
            ),
            rejections=workflow_result.rejections,
        ))
        sections = split_sections(text) if document_format not in {DocumentFormat.OPENAPI_3, DocumentFormat.SWAGGER_2} else []
        if sections:
            _publish_json(store, task_id, "document-sections.json", sections, "document_sectioning")
    elif document_format in {DocumentFormat.OPENAPI_3, DocumentFormat.SWAGGER_2}:
        contracts = parse_openapi_document(structured, source_id=source_id, minimum_score=minimum_score)
        sections = []
    else:
        # 切片先落盘；即使模型失败，用户仍可下载预检和原文结构产物。
        _publish_json(store, task_id, "document-sections.json", split_sections(text), "document_sectioning")
        parser = None
        if os.getenv("DASHSCOPE_API_KEY"):
            from agents.api_test.parsers.ai_parser_api_document import AIAPIDocumentParser
            from agents.common.config.settings import llm

            events = StageEventStore(store)
            attempt_id = str(request_payload.get("attempt_id", ""))
            parser = lambda document: AIAPIDocumentParser().parser(
                document,
                model_invoker=lambda prompt: events.invoke_model(
                    task_id, attempt_id=attempt_id, stage="document_parsing",
                    node="unstructured_contract_parser", prompt_id="api_document_parser.prompt",
                    prompt=prompt, model=llm,
                ),
            )
        contracts, sections = parse_unstructured_document(
            text, parser=parser, source_id=source_id, minimum_score=minimum_score,
        )
    if scope is not None:
        contracts = DocumentRevisionService(store).filter_contracts(
            contracts, scope, minimum_score=minimum_score,
        )
    contract_payload = [item.model_dump(mode="json", by_alias=True) for item in contracts]
    source_versions = {}
    if document_version and scope_version:
        source_versions = {"documents": document_version, "analysis-scopes": scope_version}
    previous_contract = int((store.load(task_id) or {}).get("current_versions", {}).get("contracts", {}).get("version", 0) or 0)
    version = versions.save_version(task_id, kind="contracts", items=contract_payload, source_versions=source_versions)
    blocker_count = sum(len(item.quality_report.blockers) for item in contracts)
    _append_event_safely(store, StageEvent(
        event_id=f"event_{secrets.token_hex(10)}", task_id=task_id,
        attempt_id=str(request_payload.get("attempt_id", "")), stage="document_preflight",
        node="contract_quality_gate", event_type="artifact", status="succeeded",
        message=f"已保存契约 v{version['version']}：{len(contracts)} 个接口，{blocker_count} 个阻断项",
        output_versions={"contracts": version["version"]},
    ))
    if previous_contract:
        versions.mark_downstream_stale(
            task_id, contract_version=version["version"],
            reason=f"重新分析已切换契约 v{previous_contract} → v{version['version']}",
        )
    return {
        "next_status": "waiting_contract_review", "stage": "contract_review",
        "interface_count": len(contracts), "contract_version": version["version"],
    }


def _base_case_stage(store: TaskStore, task_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
    """从指定的已确认契约版本生成结构化覆盖和基础用例。"""

    versions = ApiV2Store(store)
    requested = request_payload.get("source_versions", {})
    contract_version = int(requested.get("contracts") or 0)
    envelope = versions.load_version(task_id, "contracts", contract_version)
    contracts = [ApiContract.model_validate(item) for item in envelope["items"]]
    if not any(item.status == "confirmed" for item in contracts):
        raise ServiceError(409, "CONTRACT_NOT_CONFIRMED", "至少确认一个接口契约后才能生成用例")
    generation_kernel = str(request_payload.get("generation_kernel", "v2_minimal"))
    if generation_kernel not in {"v2_minimal", "v2_fused", "v2_core_workflow"}:
        raise ServiceError(422, "GENERATION_KERNEL_UNSUPPORTED", "API 生成内核配置不受支持")
    attempt_id = str(request_payload.get("attempt_id", ""))
    supplement_only = bool(request_payload.get("supplement_only"))
    if generation_kernel == "v2_core_workflow":
        events = StageEventStore(store)
        model = None
        if os.getenv("DASHSCOPE_API_KEY"):
            from agents.common.config.settings import llm

            model = lambda prompt: events.invoke_model(
                task_id, attempt_id=attempt_id, stage="base_case_generation",
                node="legacy_generate_base_cases", prompt_id="base_case_generator.v2_prompt",
                prompt=prompt, model=llm,
            )
        cases = []
        rejected_count = 0
        workflow_nodes: list[str] = []
        for contract in contracts:
            if contract.status != "confirmed":
                continue
            state = ApiBaseCaseGeneratorWorkFlow().create_workflow().invoke({
                "generation_kernel": "v2_core_workflow",
                "v2_contract": contract.model_dump(mode="json", by_alias=True),
                "contract_version": contract_version,
                "persist_to_database": False,
                "preconditions": [item.model_dump(mode="json") for item in contract.dependencies],
                "api_doc": json.dumps(contract.model_dump(mode="json", by_alias=True), ensure_ascii=False),
                "base_case_model": model,
                "attempt_id": attempt_id,
            })
            for item in state.get("out_put_cases", []):
                try:
                    cases.append(BaseTestCase.model_validate(item))
                except (TypeError, ValueError):
                    rejected_count += 1
            rejected_count += len(state.get("candidate_rejections", []))
            workflow_nodes.extend(str(item) for item in state.get("workflow_nodes", []))
        _unused, matrix = build_coverage(contracts, contract_version=contract_version)
        for item in matrix.items:
            matched = [
                case.case_id for case in cases
                if case.contract_id == item.contract_id and case.dimension == item.dimension
                and case.quality_report.hard_gate_passed
            ]
            if matched:
                item.case_ids = matched
                item.covered = True
        matrix.partial_success = any(item.required and not item.covered for item in matrix.items)
        prompt_hashes = {
            "base_case_generator.v2_prompt": next(
                (item.prompt_sha256 for item in cases if item.prompt_sha256), "",
            ),
        } if model else {}
        events.save_provenance(task_id, GenerationProvenance(
            attempt_id=attempt_id,
            generation_kernel="v2_core_workflow",
            contract_ids=[item.contract_id for item in contracts if item.status == "confirmed"],
            input_versions={"contracts": contract_version},
            prompt_ids=sorted(prompt_hashes), prompt_sha256=prompt_hashes,
            deterministic_case_count=sum(item.source == "deterministic" for item in cases),
            llm_case_count=sum(item.source == "llm" for item in cases),
            rejected_case_count=rejected_count,
            ai_supplement_status=("partial" if rejected_count and cases else "succeeded" if cases else "failed"),
        ))
        for index, node in enumerate(workflow_nodes):
            _append_event_safely(store, StageEvent(
                event_id=f"event_{secrets.token_hex(10)}", task_id=task_id,
                attempt_id=attempt_id, stage="base_case_generation", node=node,
                event_type="completed", status="completed",
                message=f"核心基础用例 Workflow 节点完成：{node}",
                workflow_id="api_base_case_workflow", workflow_version="2.4.0",
            ))
    elif generation_kernel == "v2_fused":
        events = StageEventStore(store)
        model = None
        if os.getenv("DASHSCOPE_API_KEY"):
            from agents.common.config.settings import llm

            model = lambda prompt: events.invoke_model(
                task_id, attempt_id=attempt_id, stage="base_case_generation",
                node="llm_business_cases", prompt_id="base_case_generator.v2_prompt",
                prompt=prompt, model=llm,
            )
        cases: list[BaseTestCase] = []
        matrix: CoverageMatrix | None = None
        if supplement_only:
            base_version = int(requested.get("base-cases") or 0)
            coverage_version = int(requested.get("coverage") or 0)
            cases = [
                BaseTestCase.model_validate(item)
                for item in versions.load_version(task_id, "base-cases", base_version)["items"]
            ]
            matrix = CoverageMatrix.model_validate(
                versions.load_version(task_id, "coverage", coverage_version)["items"]
            )
        prompt_ids: set[str] = set()
        prompt_hashes: dict[str, str] = {}
        deterministic_count = sum(item.source == "deterministic" for item in cases)
        llm_count = 0
        rejections = []
        supplement_statuses: list[str] = []
        for contract in contracts:
            if contract.status != "confirmed":
                continue
            generated, provenance = generate_fused_cases(
                GenerationContext.from_contract(contract, contract_version=contract_version),
                model=model, attempt_id=attempt_id,
            )
            candidates = [item for item in generated if item.source == "llm"] if supplement_only else generated
            known = {
                json.dumps({"contract": item.contract_id, "dimension": item.dimension, "steps": item.steps, "expected": item.expected_results}, ensure_ascii=False, sort_keys=True, default=str)
                for item in cases
            }
            added_llm = 0
            for candidate in candidates:
                signature = json.dumps({"contract": candidate.contract_id, "dimension": candidate.dimension, "steps": candidate.steps, "expected": candidate.expected_results}, ensure_ascii=False, sort_keys=True, default=str)
                if signature not in known:
                    cases.append(candidate)
                    known.add(signature)
                    added_llm += candidate.source == "llm"
            prompt_ids.update(provenance.prompt_ids)
            prompt_hashes.update(provenance.prompt_sha256)
            deterministic_count += 0 if supplement_only else provenance.deterministic_case_count
            llm_count += added_llm
            rejections.extend(provenance.rejections)
            supplement_statuses.append(provenance.ai_supplement_status)
        if matrix is None:
            _unused, matrix = build_coverage(contracts, contract_version=contract_version)
        for item in matrix.items:
            matched = [
                case.case_id for case in cases
                if case.contract_id == item.contract_id and case.dimension == item.dimension
                and case.quality_report.hard_gate_passed
            ]
            if matched:
                item.case_ids = matched
                item.covered = True
        matrix.partial_success = any(item.required and not item.covered for item in matrix.items)
        events.save_provenance(task_id, GenerationProvenance(
            attempt_id=attempt_id, generation_kernel="v2_fused",
            contract_ids=[item.contract_id for item in contracts if item.status == "confirmed"],
            input_versions={"contracts": contract_version},
            prompt_ids=sorted(prompt_ids), prompt_sha256=prompt_hashes,
            deterministic_case_count=deterministic_count,
            llm_case_count=llm_count, rejected_case_count=len(rejections),
            ai_supplement_status=(
                "partial" if rejections and llm_count else
                "failed" if rejections or "failed" in supplement_statuses else
                "succeeded" if supplement_statuses else "not_called"
            ),
            rejections=rejections,
        ))
        if rejections:
            _append_event_safely(store, StageEvent(
                event_id=f"event_{secrets.token_hex(10)}", task_id=task_id,
                attempt_id=attempt_id, stage="base_case_generation", node="candidate_validation",
                event_type="progress", status="partial_success", level="warning",
                message=f"基础用例已生成 {len(cases)} 条，拒绝模型候选 {len(rejections)} 条",
                error_code="CASE_GENERATION_PARTIAL",
            ))
    else:
        supplementer = create_business_supplementer() if os.getenv("DASHSCOPE_API_KEY") else None
        cases, matrix = build_coverage(
            contracts, contract_version=contract_version,
            supplementer=supplementer,
            max_rounds=int(os.getenv("COVERAGE_MAX_ROUNDS", "3")),
        )
    case_envelope = versions.save_version(
        task_id, kind="base-cases",
        items=[item.model_dump(mode="json", by_alias=True) for item in cases],
        source_versions={"contracts": contract_version},
    )
    versions.save_version(
        task_id, kind="coverage", items=matrix.model_dump(mode="json", by_alias=True),
        source_versions={"contracts": contract_version, "base-cases": case_envelope["version"]},
    )
    _append_event_safely(store, StageEvent(
        event_id=f"event_{secrets.token_hex(10)}", task_id=task_id,
        attempt_id=attempt_id, stage="base_case_generation", node="coverage_and_case_store",
        event_type="artifact", status="succeeded",
        message=f"已保存基础用例 v{case_envelope['version']}：{len(cases)} 条，覆盖缺口 {sum(1 for item in matrix.items if item.required and not item.covered)} 个",
        output_versions={"base-cases": case_envelope["version"]},
    ))
    return {
        "next_status": "waiting_case_review", "stage": "case_review",
        "base_case_count": len(cases), "base_case_version": case_envelope["version"],
        "coverage_gap_count": sum(1 for item in matrix.items if item.required and not item.covered),
        "generation_warning": "CASE_GENERATION_PARTIAL" if generation_kernel == "v2_fused" and rejections else None,
    }


def _executable_stage(store: TaskStore, task_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
    """从已确认用例生成无 Host 的可执行定义，并执行静态安全校验。"""

    versions = ApiV2Store(store)
    requested = request_payload.get("source_versions", {})
    contract_version = int(requested.get("contracts") or 0)
    case_version = int(requested.get("base-cases") or 0)
    contracts = [ApiContract.model_validate(item) for item in versions.load_version(task_id, "contracts", contract_version)["items"]]
    base_cases = [BaseTestCase.model_validate(item) for item in versions.load_version(task_id, "base-cases", case_version)["items"]]
    generation_kernel = str(request_payload.get("generation_kernel", "v2_minimal"))
    attempt_id = str(request_payload.get("attempt_id", ""))
    if generation_kernel == "v2_core_workflow":
        events = StageEventStore(store)

        def legacy_case_generator(base_case: BaseTestCase, contract: ApiContract, manifest: dict[str, Any]) -> dict[str, Any]:
            """在旧完整请求节点中使用统一模型端口，并提供确定性离线回退。"""

            if os.getenv("DASHSCOPE_API_KEY"):
                from agents.api_test.prompts import api_case_generator
                from agents.common.config.settings import llm

                prompt = api_case_generator.prompt.format(
                    api_case_output_format=json.dumps(api_case_generator.api_case_output_format, ensure_ascii=False),
                    case_info=json.dumps(base_case.model_dump(mode="json"), ensure_ascii=False),
                    case_api=json.dumps(contract.model_dump(mode="json", by_alias=True), ensure_ascii=False),
                    other_api=json.dumps([
                        item.model_dump(mode="json", by_alias=True)
                        for item in contracts if item.contract_id in {dep.contract_id for dep in base_case.dependencies}
                    ], ensure_ascii=False),
                    test_data=json.dumps({"data_refs": manifest.get("data_refs", [])}, ensure_ascii=False),
                    files_list="[]", function_list="[]", additional_info="禁止生成 Host、Credential 或任意环境变量",
                )
                raw = events.invoke_model(
                    task_id, attempt_id=attempt_id, stage="executable_generation",
                    node="legacy_generate_api_cases", prompt_id="api_case_generator.prompt",
                    prompt=prompt, model=llm,
                )
                raw = getattr(raw, "content", raw)
                if isinstance(raw, str):
                    raw = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
                if isinstance(raw, list):
                    raw = raw[0] if raw else {}
                if not isinstance(raw, dict):
                    raise ValueError("旧完整请求生成节点未返回对象")
                request_data = raw.get("request") if isinstance(raw.get("request"), dict) else {}
                request_data = {
                    "method": request_data.get("method", contract.method),
                    "path": request_data.get("path") or request_data.get("url") or contract.path,
                    "headers": request_data.get("headers") if isinstance(request_data.get("headers"), dict) else {},
                    "query": request_data.get("query") or request_data.get("params") or {},
                    "cookies": request_data.get("cookies") if isinstance(request_data.get("cookies"), dict) else {},
                    "body": request_data.get("body", request_data.get("requestbody")),
                }
                return {**raw, "request": request_data}
            # 模型不可用时仍通过旧 Workflow 节点输出确定性完整请求；控制平面会在
            # Review 中明确显示未调用模型，避免把离线回退伪装成 LLM 结果。
            generated = build_executable_cases([base_case], [contract])
            if not generated:
                raise ValueError("确定性执行定义生成失败")
            item = generated[0]
            return {
                "request": item.request.model_dump(mode="json"),
                "precondition_case_ids": item.precondition_case_ids,
                "assertions": [value.model_dump(mode="json") for value in item.assertions],
                "observation_targets": item.observation_targets,
                "variable_producers": [value.model_dump(mode="json") for value in item.variable_producers],
                "variable_consumers": [value.model_dump(mode="json") for value in item.variable_consumers],
                "data_refs": item.data_refs,
            }

        runtime = WorkflowRuntimeContext(
            task_id=task_id,
            attempt_id=attempt_id,
            workflow_id="api_run_case_workflow",
            workflow_version="2.4.0",
            input_versions={"contracts": contract_version, "base-cases": case_version},
            event_sink=lambda event: _append_event_safely(store, event),
        )
        controlled_manifest = {
            "data_refs": sorted({
                source for case in base_cases for source in case.generation_sources
                if str(source).startswith("data_ref:")
            }),
            "capabilities": [],
            "precondition_case_ids": [
                f"exec_{case.case_id.removeprefix('case_')}" for case in base_cases if case.status == "confirmed"
            ],
        }
        workflow_result = ApiRunCaseGeneratorWorkFlow(
            legacy_case_generator=legacy_case_generator,
        ).run(
            base_cases=base_cases, contracts=contracts,
            controlled_manifest=controlled_manifest, runtime=runtime,
        )
        executable = [
            # Workflow 已逐条隔离失败；Runner 仍进行最终严格 Schema 校验，防止
            # 任意节点绕过控制平面声明的执行定义边界。
            ExecutableCase.model_validate(item)
            for item in workflow_result.items
        ]
        events.save_provenance(task_id, GenerationProvenance(
            attempt_id=attempt_id, generation_kernel="v2_core_workflow",
            contract_ids=sorted({item.contract_id for item in base_cases if item.status == "confirmed"}),
            input_versions=runtime.input_versions,
            prompt_ids=sorted(workflow_result.workflow_provenance.prompt_sha256),
            prompt_sha256=workflow_result.workflow_provenance.prompt_sha256,
            rejected_case_count=len(workflow_result.rejections),
            ai_supplement_status=(
                "partial" if workflow_result.status == "partial_ready" else
                "failed" if workflow_result.status == "failed" else "succeeded"
            ),
            rejections=workflow_result.rejections,
        ))
    else:
        executable = []
    request_generator = None
    if generation_kernel == "v2_fused" and os.getenv("DASHSCOPE_API_KEY"):
        from agents.common.config.settings import llm

        events = StageEventStore(store)
        request_generator = lambda prompt: events.invoke_model(
            task_id, attempt_id=attempt_id, stage="executable_generation",
            node="llm_executable_case", prompt_id="api_case_generator.v2_prompt",
            prompt=prompt, model=llm,
        )
    if generation_kernel != "v2_core_workflow":
        executable = build_executable_cases(
            base_cases, contracts, request_generator=request_generator,
        )
    if generation_kernel == "v2_fused":
        StageEventStore(store).save_provenance(task_id, GenerationProvenance(
            attempt_id=attempt_id, generation_kernel="v2_fused",
            contract_ids=sorted({item.contract_id for item in base_cases if item.status == "confirmed"}),
            input_versions={"contracts": contract_version, "base-cases": case_version},
            prompt_ids=["api_case_generator.v2_prompt"] if request_generator else [],
            prompt_sha256={"api_case_generator.v2_prompt": executable_prompt_sha256()} if request_generator else {},
        ))
    envelope = versions.save_version(
        task_id, kind="executable-cases",
        items=[item.model_dump(mode="json", by_alias=True) for item in executable],
        source_versions={"contracts": contract_version, "base-cases": case_version},
    )
    ready = sum(1 for item in executable if item.validation_status == "ready")
    disabled = len(executable) - ready
    _publish_json(store, task_id, "static-validation.json", {
        "ready": ready, "disabled": disabled,
        "issues": [issue.model_dump(mode="json") for case in executable for issue in case.validation_issues],
    }, "static_validation")
    _append_event_safely(store, StageEvent(
        event_id=f"event_{secrets.token_hex(10)}", task_id=task_id,
        attempt_id=attempt_id, stage="executable_generation", node="static_validation",
        event_type="artifact", status="succeeded" if ready else "failed",
        level="info" if ready else "warning",
        message=f"静态校验完成：{ready} 条就绪，{disabled} 条禁用",
        output_versions={"executable-cases": envelope["version"]},
    ))
    return {
        "next_status": "waiting_executable_review" if generation_kernel == "v2_core_workflow" else (
            "partial_success" if disabled else "succeeded"
        ),
        "stage": "executable_review" if generation_kernel == "v2_core_workflow" else (
            "execution_ready" if ready else "static_validation_failed"
        ),
        "executable_case_count": len(executable), "ready_case_count": ready,
        "executable_case_version": envelope["version"],
    }


def _run(task_id: str) -> dict[str, Any]:
    """按 request.json 的显式阶段执行，并带回执行序号防止迟到写回。"""

    store = TaskStore(Path(os.environ["AGENT_DATA_DIR"]))
    task_dir = store.task_dir(task_id)
    request_payload = json.loads((task_dir / "request.json").read_text(encoding="utf-8"))
    execution = json.loads((task_dir / "execution.json").read_text(encoding="utf-8"))
    stage = request_payload.get("from_stage", "document_preflight")
    handlers = {
        "document_preflight": _initial_stage,
        "base_case_generation": _base_case_stage,
        "executable_generation": _executable_stage,
    }
    if stage not in handlers:
        raise ServiceError(422, "RETRY_STAGE_UNSUPPORTED", "执行阶段不受支持")
    events = StageEventStore(store)
    attempt_id = str(request_payload.get("attempt_id", ""))
    started = time.monotonic()
    _append_event_safely(store, StageEvent(
        event_id=f"event_{secrets.token_hex(10)}", task_id=task_id, attempt_id=attempt_id,
        stage=stage, node="runner", event_type="started", status="running",
        message=f"阶段开始：{stage}", input_versions={
            key: int(value) for key, value in request_payload.get("source_versions", {}).items()
            if isinstance(value, int)
        },
    ))
    structured_log(
        logging.getLogger("api_test_agent.runner"), task_id=task_id,
        attempt_id=attempt_id, stage=stage, node="runner", event="stage_started", status="running",
    )
    result = handlers[stage](store, task_id, request_payload)
    _append_event_safely(store, StageEvent(
        event_id=f"event_{secrets.token_hex(10)}", task_id=task_id, attempt_id=attempt_id,
        stage=stage, node="runner", event_type="completed", status="succeeded",
        message=f"阶段完成：{result['stage']}", duration_ms=int((time.monotonic() - started) * 1000),
    ))
    _finish_attempt(store, task_id, request_payload["attempt_id"], status="succeeded", stage=result["stage"])
    structured_log(
        logging.getLogger("api_test_agent.runner"), task_id=task_id,
        attempt_id=attempt_id, stage=stage, node="runner", event="stage_completed",
        status="succeeded", duration_ms=int((time.monotonic() - started) * 1000),
    )
    return {**result, "execution_sequence": execution["sequence"], "execution_kind": execution["kind"]}


def main() -> int:
    """运行阶段并将稳定错误写入 Runner 结果。"""

    logger = logging.getLogger("api_test_agent.runner")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    store = TaskStore(Path(os.environ["AGENT_DATA_DIR"]))
    result_path = store.task_dir(args.task_id) / "runner-result.json"
    try:
        TaskStore.atomic_write_json(result_path, _run(args.task_id))
        return 0
    except Exception as exc:
        traceback.print_exc()
        error_code, error_message = classify_runner_exception(
            exc, default_code="WORKFLOW_FAILED", default_message="API V2 阶段执行失败",
        )
        failed_stage = "api_v2"
        try:
            request_payload = json.loads((store.task_dir(args.task_id) / "request.json").read_text(encoding="utf-8"))
            failed_stage = request_payload.get("from_stage", "unknown")
            _finish_attempt(store, args.task_id, request_payload.get("attempt_id", ""), status="failed", stage=failed_stage, error_code=error_code)
            _append_event_safely(store, StageEvent(
                event_id=f"event_{secrets.token_hex(10)}", task_id=args.task_id,
                attempt_id=request_payload.get("attempt_id"),
                stage=failed_stage, node="runner",
                event_type="failed", status="failed", message=error_message, error_code=error_code,
            ))
        except (OSError, json.JSONDecodeError):
            pass
        structured_log(
            logging.getLogger("api_test_agent.runner"), "error", task_id=args.task_id,
            stage=failed_stage, node="runner", event="stage_failed", status="failed",
            error_code=error_code,
        )
        try:
            execution = json.loads((store.task_dir(args.task_id) / "execution.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            execution = {"kind": "initial", "sequence": 0}
        TaskStore.atomic_write_json(result_path, {"execution_kind": execution["kind"], "execution_sequence": execution["sequence"], "error_code": error_code, "error_message": error_message, "stage": failed_stage})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
