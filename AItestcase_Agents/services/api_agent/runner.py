"""API 测试智能体 V2 阶段式 Runner；本模块绝不发送目标 API 请求。"""

from __future__ import annotations

import argparse
import json
import os
import traceback
from pathlib import Path
from typing import Any

from agents.api_test.cases.coverage import build_coverage
from agents.api_test.cases.business_supplement import create_business_supplementer
from agents.api_test.cases.executable import build_executable_cases
from agents.api_test.contracts.format_detector import DocumentFormat, detect_document_format
from agents.api_test.contracts.openapi_parser import parse_openapi_document
from agents.api_test.contracts.unstructured_parser import parse_unstructured_document, split_sections
from services.api_agent.models import ApiContract, BaseTestCase
from services.api_agent.v2_store import ApiV2Store
from services.common.artifacts import merge_registry, publish_artifact
from services.common.errors import ServiceError, classify_runner_exception
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
    source = task_dir / request_payload["input_relative_path"]
    text = source.read_text(encoding="utf-8")
    document_format, structured, profile = detect_document_format(text, request_payload.get("input_original_name", source.name))
    _publish_json(store, task_id, "document-profile.json", profile.as_dict(), "document_preflight")
    minimum_score = float(os.getenv("CONTRACT_QUALITY_MIN_SCORE", "0.8"))
    if document_format in {DocumentFormat.OPENAPI_3, DocumentFormat.SWAGGER_2}:
        contracts = parse_openapi_document(structured, source_id=request_payload["input_sha256"], minimum_score=minimum_score)
        sections: list[dict[str, str]] = []
    else:
        # 切片先落盘；即使模型失败，用户仍可下载预检和原文结构产物。
        _publish_json(store, task_id, "document-sections.json", split_sections(text), "document_sectioning")
        contracts, sections = parse_unstructured_document(text, source_id=request_payload["input_sha256"], minimum_score=minimum_score)
    contract_payload = [item.model_dump(mode="json", by_alias=True) for item in contracts]
    version = ApiV2Store(store).save_version(task_id, kind="contracts", items=contract_payload)
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
    return {
        "next_status": "waiting_case_review", "stage": "case_review",
        "base_case_count": len(cases), "base_case_version": case_envelope["version"],
        "coverage_gap_count": sum(1 for item in matrix.items if item.required and not item.covered),
    }


def _executable_stage(store: TaskStore, task_id: str, request_payload: dict[str, Any]) -> dict[str, Any]:
    """从已确认用例生成无 Host 的可执行定义，并执行静态安全校验。"""

    versions = ApiV2Store(store)
    requested = request_payload.get("source_versions", {})
    contract_version = int(requested.get("contracts") or 0)
    case_version = int(requested.get("base-cases") or 0)
    contracts = [ApiContract.model_validate(item) for item in versions.load_version(task_id, "contracts", contract_version)["items"]]
    base_cases = [BaseTestCase.model_validate(item) for item in versions.load_version(task_id, "base-cases", case_version)["items"]]
    executable = build_executable_cases(base_cases, contracts)
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
    return {
        "next_status": "partial_success" if disabled else "succeeded",
        "stage": "execution_ready" if ready else "static_validation_failed",
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
    result = handlers[stage](store, task_id, request_payload)
    _finish_attempt(store, task_id, request_payload["attempt_id"], status="succeeded", stage=result["stage"])
    return {**result, "execution_sequence": execution["sequence"], "execution_kind": execution["kind"]}


def main() -> int:
    """运行阶段并将稳定错误写入 Runner 结果。"""

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
        try:
            request_payload = json.loads((store.task_dir(args.task_id) / "request.json").read_text(encoding="utf-8"))
            _finish_attempt(store, args.task_id, request_payload.get("attempt_id", ""), status="failed", stage=request_payload.get("from_stage", "unknown"), error_code=error_code)
        except (OSError, json.JSONDecodeError):
            pass
        try:
            execution = json.loads((store.task_dir(args.task_id) / "execution.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            execution = {"kind": "initial", "sequence": 0}
        TaskStore.atomic_write_json(result_path, {"execution_kind": execution["kind"], "execution_sequence": execution["sequence"], "error_code": error_code, "error_message": error_message, "stage": "api_v2"})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
