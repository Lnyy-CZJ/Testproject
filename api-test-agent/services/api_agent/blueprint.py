"""API 测试智能体 V2 的专属 Review、重试和执行准备 HTTP 协议。"""

from __future__ import annotations

import io
import json
import secrets
from datetime import UTC, datetime, timedelta

from flask import Blueprint, current_app, g, jsonify, request, send_file

from services.api_agent.defect_service import DefectDraftService
from services.api_agent.document_service import DocumentRevisionService
from services.api_agent.execution_plan import (
    compile_execution_plan,
    rehash_execution_plan,
    target_policy_sha256,
    validate_execution_plan_hashes,
)
from services.api_agent.review_service import ApiReviewService
from services.api_agent.stage_events import StageEventStore
from services.api_agent.v2_store import ApiV2Store, canonical_sha256
from agents.api_test.cases.grounding import assess_case_grounding, validate_legacy_executable
from services.api_agent.models import ApiContract, BaseTestCase, ExecutionPlan, StageEvent
from services.common.errors import ServiceError
from services.common.identity import identity_from_request, require_csrf, require_permission, require_task_access
from services.common.redaction import redact_structure
from services.common.task_models import public_task


def create_api_v2_blueprint(base_path: str) -> Blueprint:
    """创建 API 专属 Blueprint，避免继续扩展公共 web.py 的业务语义。"""

    blueprint = Blueprint("api_v2", __name__)
    api_prefix = f"{base_path}/api/v1"

    def context(task_id: str, permission: str, *, action: str | None = None):
        """解析派生 API 资源的根任务，并按实际动作核验平台上下文。"""

        store = current_app.extensions["task_store"]
        # Review 与重试不能借 read token 放行；缺省映射覆盖本 Blueprint 的
        # 所有任务级路由，个别取消 Run 的路由通过显式 action 覆盖。
        resolved_action = action or {
            "api-test-agent.contract.review": "review",
            "api-test-agent.case.review": "review",
            "api-test-agent.executable.review": "review",
            "api-test-agent.defect.create": "review",
            "api-test-agent.execute": "retry",
        }.get(permission, "read")
        identity = identity_from_request(
            request, current_app.extensions["platform_client"],
            action=resolved_action, root_resource_id=task_id,
        )
        record = store.load_visible(task_id, identity)
        if not record or record.get("schema_version") != 2:
            raise ServiceError(404, "TASK_NOT_FOUND", "V2 任务不存在")
        require_task_access(identity, record, permission=permission)
        return store, record, identity

    def documents(store):
        """创建遵循当前部署灰度开关的文档服务。"""

        return DocumentRevisionService(
            store, feature_enabled=bool(current_app.config.get("API_PRE_REVIEW_V21_ENABLED")),
        )

    def append_event(store, record: dict, *, stage: str, node: str, message: str, event_type: str = "review", run_id: str | None = None) -> None:
        """尽力记录产品级事件；事件失败不得破坏 Review 或执行终态。"""

        attempt_id = str(record.get("current_attempt_id") or "")
        if not attempt_id:
            return
        try:
            StageEventStore(store).append(StageEvent(
                event_id=f"event_{secrets.token_hex(10)}", task_id=record["id"],
                attempt_id=attempt_id, run_id=run_id, stage=stage, node=node,
                event_type=event_type, status="succeeded", message=message,
                request_id=g.get("request_id"),
            ))
        except (OSError, TypeError, ValueError):
            return

    def build_preview(store, task_id: str) -> dict:
        """构造稳定执行确认摘要；目标信息始终脱敏且不包含可执行 Host。"""

        try:
            executable = ApiV2Store(store).load_version(task_id, "executable-cases")
            ready = [item for item in executable["items"] if item.get("validation_status") == "ready" and item.get("enabled")]
        except FileNotFoundError:
            executable, ready = {"version": 0, "sha256": "", "items": []}, []
        legacy_blocked = []
        try:
            contracts = {
                item.contract_id: item for item in (
                    ApiContract.model_validate(value)
                    for value in ApiV2Store(store).load_version(task_id, "contracts")["items"]
                )
            }
        except FileNotFoundError:
            contracts = {}
        base_cases = {}
        source_case_version = int(executable.get("source_versions", {}).get("base-cases", 0) or 0)
        try:
            base_envelope = ApiV2Store(store).load_version(
                task_id, "base-cases", source_case_version or None,
            )
            base_cases = {
                item.case_id: item for item in (
                    BaseTestCase.model_validate(value) for value in base_envelope["items"]
                )
            }
        except FileNotFoundError:
            base_cases = {}
        safe_ready = []
        for item in ready:
            contract = contracts.get(str(item.get("contract_id", "")))
            kernel = str(item.get("generation_kernel") or "v2_minimal")
            issues = validate_legacy_executable(item, contract) if contract and kernel in {"legacy", "v2_minimal"} else []
            base_case = base_cases.get(str(item.get("base_case_id", "")))
            if contract and base_case and kernel in {"legacy", "v2_minimal"}:
                quality = assess_case_grounding(base_case, contract)
                issues.extend(quality.blockers)
            if issues or (kernel in {"legacy", "v2_minimal"} and not base_case):
                legacy_blocked.append(str(item.get("executable_case_id", "")))
            else:
                safe_ready.append(item)
        ready = safe_ready
        targets = current_app.extensions.get("api_execution_targets", {})
        target = next(iter(targets.values()), None)
        enabled = bool(current_app.extensions.get("api_execution_enabled") and target)
        blockers = []
        if not current_app.extensions.get("api_execution_enabled"):
            blockers.append("API_EXECUTION_ENABLED=false 或当前环境为生产环境")
        if target is None:
            blockers.append("未登记执行目标")
        if not ready:
            blockers.append("没有通过静态校验的可执行用例")
        if legacy_blocked:
            blockers.append("历史用例未通过 V2.2 兼容校验，请使用融合内核重新生成")
        if target and not target.allow_write_methods and any(item.get("request", {}).get("method") in {"POST", "PUT", "PATCH", "DELETE"} for item in ready):
            blockers.append("目标未授权写操作")
        summary = {
            "task_id": task_id, "executable_version": executable["version"],
            "executable_sha256": executable["sha256"], "ready_case_ids": [item["executable_case_id"] for item in ready],
            "write_case_count": sum(item.get("request", {}).get("method") in {"POST", "PUT", "PATCH", "DELETE"} for item in ready),
            "high_risk_count": sum(item.get("risk_level") == "high" for item in ready),
            "script_count": sum(bool(item.get("setup_script") or item.get("teardown_script")) for item in ready),
            "target_id": target.target_id if target else "",
            "target": target.masked_base_url if target else "未配置（已脱敏）", "execution_enabled": enabled,
            "blocking_reasons": blockers,
            "legacy_blocked_case_ids": legacy_blocked,
        }
        summary["confirmation_sha256"] = canonical_sha256(summary)
        return summary

    def build_case_view(store, record: dict) -> dict:
        """把文件化版本统一为页面稳定响应；正常门禁不抛 503。"""

        versions = ApiV2Store(store)
        empty_cases = {"version": 0, "sha256": "", "source_versions": {}, "lifecycle_status": "current", "items": []}
        empty_matrix = {
            "version": 0, "sha256": "", "contract_version": 0, "round_count": 0,
            "accepted_gap_ids": [], "partial_success": False,
            "lifecycle_status": "current", "items": [],
        }
        try:
            cases_envelope = versions.load_version(record["id"], "base-cases")
            coverage_envelope = versions.load_version(record["id"], "coverage")
        except FileNotFoundError:
            if record.get("status") in {"pending", "running"} and "case" in str(record.get("stage", "")):
                state = "generating"
            elif record.get("status") == "failed":
                state = "failed"
            elif record.get("status") == "waiting_contract_review":
                state = "blocked"
            else:
                state = "not_generated"
            return {"stage_state": state, "base_cases": empty_cases, "coverage_matrix": empty_matrix}
        except ValueError as exc:
            raise ServiceError(500, "CASE_RESPONSE_SCHEMA_INVALID", "覆盖矩阵或基础用例产物校验失败") from exc
        matrix = coverage_envelope.get("items") if isinstance(coverage_envelope.get("items"), dict) else {}
        matrix_items = matrix.get("items") if isinstance(matrix.get("items"), list) else None
        case_items = cases_envelope.get("items") if isinstance(cases_envelope.get("items"), list) else None
        if matrix_items is None or case_items is None:
            raise ServiceError(500, "CASE_RESPONSE_SCHEMA_INVALID", "覆盖矩阵或基础用例产物结构不合法")
        current_contract = int(record.get("current_versions", {}).get("contracts", {}).get("version", 0) or 0)
        source_contract = int(cases_envelope.get("source_versions", {}).get("contracts", 0) or 0)
        lifecycle = "stale" if current_contract and source_contract != current_contract else "current"
        stage_state = "stale" if lifecycle == "stale" else (
            "partial_success" if matrix.get("partial_success") else "ready"
        )
        return {
            "stage_state": stage_state,
            "base_cases": {
                "version": cases_envelope["version"], "sha256": cases_envelope["sha256"],
                "source_versions": cases_envelope.get("source_versions", {}),
                "lifecycle_status": lifecycle, "items": case_items,
            },
            "coverage_matrix": {
                "version": coverage_envelope["version"], "sha256": coverage_envelope["sha256"],
                "contract_version": int(matrix.get("contract_version", source_contract) or 0),
                "round_count": int(matrix.get("round_count", 0)),
                "rounds": matrix.get("rounds", []),
                "accepted_gap_ids": matrix.get("accepted_gap_ids", []),
                "partial_success": bool(matrix.get("partial_success")),
                "lifecycle_status": lifecycle, "items": matrix_items,
            },
        }

    def compile_plan_preview(store, record: dict, body: dict) -> dict:
        """从指定执行定义版本编译纯预览，不保存计划也不创建 Run。"""

        versions = ApiV2Store(store)
        requested_version = int(body.get("executable_version", 0) or 0)
        executable = versions.load_version(
            record["id"], "executable-cases", requested_version or None,
        )
        current_version = int(
            (store.load(record["id"]) or record).get("current_versions", {})
            .get("executable-cases", {}).get("version", 0) or 0
        )
        lifecycle = "current" if int(executable["version"]) == current_version else "stale"
        cases = [
            {**item, "lifecycle_status": lifecycle}
            for item in executable.get("items", []) if isinstance(item, dict)
        ]
        targets = current_app.extensions.get("api_execution_targets", {})
        target_payload = {
            target_id: {
                "target_id": target.target_id,
                "environment": target.environment,
                "allow_write_methods": target.allow_write_methods,
                "internal_base_url": target.internal_base_url,
            }
            for target_id, target in targets.items()
        }
        runtime = (
            current_app.extensions.get("api_fake_execution_service")
            if current_app.config.get("TESTING") else current_app.extensions.get("api_real_execution_service")
        )
        runtime_adapter = getattr(runtime, "runtime", None)
        default_resource_policy = "s1-fake-resource" if current_app.config.get("TESTING") else "local-restricted-v1"
        default_egress_policy = "s1-no-egress" if current_app.config.get("TESTING") else "local-platform-v1"
        resource_policy_id = str(
            body.get("resource_policy_id")
            or getattr(runtime_adapter, "resource_policy_id", default_resource_policy)
        )
        egress_policy_id = str(
            body.get("egress_policy_id")
            or getattr(runtime_adapter, "egress_policy_id", default_egress_policy)
        )
        target_id = str(body.get("target_id", ""))
        result = compile_execution_plan(
            cases,
            task_id=record["id"],
            source_executable_version=int(executable["version"]),
            source_executable_sha256=str(executable["sha256"]),
            target_id=target_id,
            environment=str(record.get("environment", "test")),
            registered_targets=target_payload,
            resource_policy_id=resource_policy_id,
            egress_policy_id=egress_policy_id,
            policy_version=str(record.get("config_release_id") or current_app.config.get("APP_REVISION", "local")),
            manual_edges=body.get("manual_edges") if isinstance(body.get("manual_edges"), list) else [],
        )
        blockers = [
            {"code": item.code, "field_path": item.field_path, "message": item.detail}
            for item in result.blockers
        ]
        return {
            "stage_state": "ready" if result.ready else "blocked",
            "plan": result.plan,
            "blockers": blockers,
            "source_executable_version": int(executable["version"]),
            "source_executable_sha256": str(executable["sha256"]),
        }

    def validate_plan_run_target(plan: dict, record: dict):
        """在每次新 Run（含重试）前复核不可变计划、策略与登记目标。

        计划确认后，部署人员仍可能撤销写权限、调整目标 URL 或升级策略。Run
        入口必须读取当前配置重新验证，不能只相信历史确认状态。该函数只返回
        已登记目标对象，不泄露内部 URL 到错误响应或审计正文。
        """

        if not validate_execution_plan_hashes(plan):
            raise ServiceError(409, "EXECUTION_PLAN_STALE", "执行计划内容校验失败，请重新生成并确认")
        current_policy_version = str(
            record.get("config_release_id") or current_app.config.get("APP_REVISION", "local")
        )
        if str(plan.get("policy_version", "")) != current_policy_version:
            raise ServiceError(409, "EXECUTION_PLAN_STALE", "执行安全策略版本已变化，请重新生成并确认")
        target = current_app.extensions.get("api_execution_targets", {}).get(str(plan.get("target_id", "")))
        if target is None:
            raise ServiceError(403, "EXECUTION_TARGET_DENIED", "计划目标未登记，未创建 Run")
        if target.environment != str(record.get("environment", "test")):
            raise ServiceError(403, "EXECUTION_TARGET_DENIED", "计划目标环境与任务不一致")
        nodes = plan.get("nodes") if isinstance(plan.get("nodes"), list) else []
        has_write = any(isinstance(node, dict) and bool(node.get("write_operation")) for node in nodes)
        if has_write and not target.allow_write_methods:
            raise ServiceError(403, "EXECUTION_TARGET_WRITE_DENIED", "目标的写操作授权已撤销，未创建 Run")
        if str(plan.get("target_policy_sha256", "")) != target_policy_sha256(target):
            raise ServiceError(409, "EXECUTION_PLAN_STALE", "执行目标配置已变化，请重新生成并确认")
        if target.internal_base_url.lower().startswith("https://"):
            raise ServiceError(409, "EGRESS_HTTPS_NOT_READY", "当前受控出口尚未启用 HTTPS 目标")
        if str(plan.get("credential_profile_ref", "")):
            raise ServiceError(409, "CREDENTIAL_INJECTION_NOT_READY", "当前版本尚未启用凭证注入")
        return target

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/contracts")
    def contracts(task_id: str):
        store, record, _identity = context(task_id, "tool.result.view")
        current = int(record.get("current_versions", {}).get("contracts", {}).get("version", 0) or 0)
        requested_text = str(request.args.get("version", "")).strip()
        try:
            requested = int(requested_text) if requested_text else current
        except ValueError as exc:
            raise ServiceError(422, "INVALID_INPUT", "契约版本必须为正整数") from exc
        if requested_text and requested < 1:
            raise ServiceError(422, "INVALID_INPUT", "契约版本必须为正整数")
        if not requested:
            state = "generating" if record.get("status") in {"pending", "running"} else (
                "failed" if record.get("status") == "failed" else "not_generated"
            )
            return jsonify({
                "stage_state": state, "version": 0, "sha256": "",
                "items": [], "task_status": record["status"],
            })
        try:
            payload = ApiV2Store(store).load_version(task_id, "contracts", requested)
        except FileNotFoundError as exc:
            if requested_text and requested != current:
                raise ServiceError(404, "CONTRACT_VERSION_NOT_FOUND", "指定契约版本不存在") from exc
            raise ServiceError(500, "CONTRACT_VERSION_CORRUPTED", "当前契约版本损坏，请从解析阶段重试") from exc
        return jsonify({
            **payload, "stage_state": "stale" if current and requested != current else "ready",
            "task_status": record["status"],
        })

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/documents")
    def list_documents(task_id: str):
        store, _record, _identity = context(task_id, "tool.result.view")
        return jsonify(documents(store).list_documents(task_id))

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/documents/<int:version>")
    def get_document(task_id: str, version: int):
        store, _record, _identity = context(task_id, "tool.result.view")
        return jsonify(documents(store).get_document(task_id, version))

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/documents/revisions")
    def create_document_revision(task_id: str):
        store, _record, identity = context(task_id, "api-test-agent.contract.review")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        saved = documents(store).create_revision(
            task_id, base_version=int(body.get("base_version", 0)),
            content=str(body.get("content", "")), change_reason=str(body.get("change_reason", "")),
            actor={"user_id": identity.user_id, "username": identity.username},
        )
        return jsonify(saved), 201

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/documents/compare")
    def compare_documents(task_id: str):
        store, _record, _identity = context(task_id, "tool.result.view")
        try:
            from_version = int(request.args.get("from", 0))
            to_version = int(request.args.get("to", 0))
        except (TypeError, ValueError) as exc:
            raise ServiceError(422, "INVALID_INPUT", "文档版本必须是正整数") from exc
        return jsonify(documents(store).compare(task_id, from_version, to_version))

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/analysis-scope")
    def analysis_scope(task_id: str):
        store, _record, _identity = context(task_id, "tool.result.view")
        return jsonify(documents(store).get_scope(task_id))

    @blueprint.put(f"{api_prefix}/tasks/<task_id>/analysis-scope")
    def update_analysis_scope(task_id: str):
        store, _record, identity = context(task_id, "api-test-agent.contract.review")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        saved = documents(store).save_scope(
            task_id, base_version=int(body.get("base_version", 0)),
            document_version=int(body.get("document_version", 0)),
            fields=body.get("fields") if isinstance(body.get("fields"), dict) else {},
            actor={"user_id": identity.user_id, "username": identity.username},
            reason=str(body.get("reason", "")),
        )
        return jsonify(saved)

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/reanalyze/preview")
    def preview_reanalysis(task_id: str):
        store, _record, _identity = context(task_id, "api-test-agent.contract.review")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        service = documents(store)
        if not service.feature_enabled():
            raise ServiceError(403, "FEATURE_DISABLED", "文档修订与重新分析当前未启用")
        return jsonify(service.preview_reanalysis(
            task_id, document_version=int(body.get("document_version", 0)),
            scope_version=int(body.get("scope_version", 0)),
        ))

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/reanalyze")
    def reanalyze(task_id: str):
        store, record, identity = context(task_id, "api-test-agent.contract.review")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        document_version = int(body.get("document_version", 0))
        scope_version = int(body.get("scope_version", 0))
        service = documents(store)
        if not service.feature_enabled():
            raise ServiceError(403, "FEATURE_DISABLED", "文档修订与重新分析当前未启用")
        service.ensure_initial_versions(
            task_id, register=True,
            created_by={"user_id": identity.user_id, "username": identity.username},
        )
        preview = service.preview_reanalysis(
            task_id, document_version=document_version, scope_version=scope_version,
        )
        if str(body.get("preview_sha256", "")) != preview["preview_sha256"]:
            raise ServiceError(409, "REANALYZE_PREVIEW_EXPIRED", "重新分析影响预览已失效")
        idempotency_key = str(body.get("idempotency_key", "")).strip()
        if not idempotency_key or len(idempotency_key) > 128:
            raise ServiceError(422, "INVALID_INPUT", "重新分析幂等键不能为空或超过限制")
        reason = str(body.get("reason", "")).strip()
        if not reason:
            raise ServiceError(422, "INVALID_INPUT", "重新分析必须填写确认原因")
        queued = current_app.extensions["task_manager"].enqueue_stage(
            task_id, from_stage="document_preflight",
            expected_status={"waiting_contract_review", "waiting_case_review", "waiting_execution_confirmation", "failed", "partial_success", "succeeded"},
            source_versions={"documents": document_version, "analysis-scopes": scope_version},
            request_updates={
                "document_version": document_version, "scope_version": scope_version,
                "document_sha256": preview["document_sha256"], "scope_sha256": preview["scope_sha256"],
            },
            idempotency_key=idempotency_key,
        )
        service.append_action_audit(
            task_id, action="analysis.reanalyze", version=scope_version,
            object_id=queued.get("current_attempt_id", ""),
            actor={"user_id": identity.user_id, "username": identity.username},
            field_paths=["document_version", "scope_version"],
        )
        return jsonify(public_task(queued)), 202

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/review-issues")
    def review_issues(task_id: str):
        store, _record, _identity = context(task_id, "tool.result.view")
        return jsonify(documents(store).list_issues(task_id, request.args.get("contract_id", "")))

    @blueprint.put(f"{api_prefix}/tasks/<task_id>/review-issues/<issue_id>")
    def resolve_review_issue(task_id: str, issue_id: str):
        store, record, identity = context(task_id, "api-test-agent.contract.review")
        require_csrf(request)
        allowed_statuses = {
            "waiting_contract_review", "waiting_case_review",
            "waiting_execution_confirmation", "partial_success", "succeeded",
        }
        if record.get("status") not in allowed_statuses:
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许处理契约问题")
        body = request.get_json(silent=True) or {}
        saved = documents(store).resolve_issue(
            task_id, issue_id, base_contract_version=int(body.get("base_contract_version", 0)),
            action=str(body.get("action", "")), reason=str(body.get("reason", "")),
            payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
            actor={"user_id": identity.user_id, "username": identity.username},
        )
        ApiV2Store(store).mark_downstream_stale(
            task_id, contract_version=int(saved["version"]), reason="契约问题人工处理产生新版本",
        )
        if record.get("status") != "waiting_contract_review":
            refreshed = store.load(task_id) or record
            refreshed.update({"status": "waiting_contract_review", "stage": "contract_review"})
            store.save(refreshed)
        append_event(store, store.load(task_id) or record, stage="contract_review", node="review_issue", message="契约问题已人工处理并重新运行质量门禁")
        return jsonify(saved)

    @blueprint.put(f"{api_prefix}/tasks/<task_id>/contracts/review")
    def review_contracts(task_id: str):
        store, record, identity = context(task_id, "api-test-agent.contract.review")
        require_csrf(request)
        if record.get("status") != "waiting_contract_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务不在契约 Review 阶段")
        body = request.get_json(silent=True) or {}
        result = ApiReviewService(store).review_contracts(
            task_id, base_version=int(body.get("base_version", 0)),
            changes=body.get("changes") if isinstance(body.get("changes"), list) else [],
            actor={"user_id": identity.user_id, "username": identity.username},
        )
        append_event(store, record, stage="contract_review", node="contract_review", message=f"契约 Review 已保存为 v{result['version']}")
        return jsonify(result)

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/cases/generate")
    def generate_cases(task_id: str):
        store, record, identity = context(task_id, "api-test-agent.case.review")
        require_csrf(request)
        current = ApiV2Store(store).load_version(task_id, "contracts")
        if not any(item.get("status") == "confirmed" for item in current["items"]):
            raise ServiceError(409, "CONTRACT_NOT_CONFIRMED", "至少确认一个契约后才能生成用例")
        queued = current_app.extensions["task_manager"].enqueue_stage(
            task_id, from_stage="base_case_generation", expected_status="waiting_contract_review",
            source_versions={"contracts": current["version"]},
        )
        return jsonify(public_task(queued)), 202

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/cases")
    def cases(task_id: str):
        store, record, _identity = context(task_id, "tool.result.view")
        return jsonify(build_case_view(store, record))

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/cases/confirmation-preview")
    def case_confirmation_preview(task_id: str):
        """返回一键确认摘要；该只读接口不会修改用例或创建 Attempt。"""

        store, _record, _identity = context(task_id, "tool.result.view")
        return jsonify(ApiReviewService(store).case_confirmation_preview(task_id))

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/cases/confirm-all")
    def confirm_all_cases(task_id: str):
        """确认当前版本全部可确认基础用例，并逐条保留高风险审计。"""

        store, record, identity = context(task_id, "api-test-agent.case.review")
        require_csrf(request)
        if record.get("status") != "waiting_case_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务不在用例 Review 阶段")
        body = request.get_json(silent=True) or {}
        saved = ApiReviewService(store).confirm_all_cases(
            task_id,
            base_version=int(body.get("base_version", 0)),
            confirmation_sha256=str(body.get("confirmation_sha256", "")),
            reason=str(body.get("reason", "")),
            actor={"user_id": identity.user_id, "username": identity.username},
            # V2.4 权限基线允许管理员、测试开发和测试人员确认高风险用例；
            # 只读角色无法通过本路由的 case.review 权限检查。
            can_approve_high_risk=True,
        )
        append_event(
            store, record, stage="case_review", node="confirm_all",
            message=f"已一键确认 {len(saved['confirmed_case_ids'])} 条基础用例",
        )
        return jsonify(saved)

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/cases/confirm-and-generate-executable")
    def confirm_and_generate_executable(task_id: str):
        """原子业务动作：确认基础用例并创建阶段三 Attempt，但绝不创建 Run。"""

        store, record, identity = context(task_id, "api-test-agent.case.review")
        require_permission(identity, "api-test-agent.executable.generate")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        idempotency_key = str(body.get("idempotency_key", "")).strip()
        if not idempotency_key or len(idempotency_key) > 128:
            raise ServiceError(422, "INVALID_INPUT", "幂等键不能为空或超过限制")
        slot = f"executable_generation:{idempotency_key}"
        if slot in record.get("stage_idempotency_keys", {}):
            return jsonify({**public_task(record), "stage_state": "generating"}), 202
        if record.get("status") != "waiting_case_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务不在用例 Review 阶段")

        # 确认版本与 Attempt 创建属于一个控制平面动作。不可变确认文件即使已写出，
        # 只有在入队成功后才切换 current 指针；入队异常会恢复原任务指针和状态，
        # 用户可安全重试而不会处于“已确认但没有阶段三 Attempt”的半完成状态。
        with store.locked():
            before_record = store.load(task_id) or record
            review = ApiReviewService(store)
            confirmed = review.confirm_all_cases(
                task_id,
                base_version=int(body.get("base_version", 0)),
                confirmation_sha256=str(body.get("confirmation_sha256", "")),
                reason=str(body.get("reason", "")),
                actor={"user_id": identity.user_id, "username": identity.username},
                can_approve_high_risk=True,
            )
            contract_version = int(
                (store.load(task_id) or {}).get("current_versions", {}).get("contracts", {}).get("version", 0) or 0
            )
            try:
                queued = current_app.extensions["task_manager"].enqueue_stage(
                    task_id,
                    from_stage="executable_generation",
                    expected_status="waiting_case_review",
                    source_versions={"contracts": contract_version, "base-cases": int(confirmed["version"])},
                    request_updates={
                        "base_case_sha256": confirmed["sha256"],
                        "case_confirmation_sha256": confirmed["confirmation_sha256"],
                    },
                    idempotency_key=idempotency_key,
                )
            except Exception:
                store.save(before_record)
                raise
        append_event(
            store, queued, stage="executable_generation", node="confirm_and_generate",
            message=f"已确认 {len(confirmed['confirmed_case_ids'])} 条用例并创建执行定义生成 Attempt",
        )
        return jsonify({
            **public_task(queued),
            "stage_state": "generating",
            "base_case_version": int(confirmed["version"]),
            "confirmed_count": len(confirmed["confirmed_case_ids"]),
            "skipped_count": len(confirmed["skipped"]),
        }), 202

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/cases/supplement/retry")
    def retry_case_supplement(task_id: str):
        """创建只重试 AI 补充的新 Attempt，保留已有确定性用例。"""

        store, record, _identity = context(task_id, "api-test-agent.case.review")
        require_csrf(request)
        if record.get("status") != "waiting_case_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "仅用例 Review 阶段允许重试 AI 补充")
        versions = ApiV2Store(store)
        contracts = versions.load_version(task_id, "contracts")
        base_cases = versions.load_version(task_id, "base-cases")
        coverage = versions.load_version(task_id, "coverage")
        queued = current_app.extensions["task_manager"].enqueue_stage(
            task_id, from_stage="base_case_generation", expected_status="waiting_case_review",
            source_versions={
                "contracts": contracts["version"], "base-cases": base_cases["version"],
                "coverage": coverage["version"],
            },
            request_updates={"supplement_only": True},
        )
        return jsonify(public_task(queued)), 202

    @blueprint.put(f"{api_prefix}/tasks/<task_id>/cases/review")
    def review_cases(task_id: str):
        store, record, identity = context(task_id, "api-test-agent.case.review")
        require_csrf(request)
        if record.get("status") != "waiting_case_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务不在用例 Review 阶段")
        body = request.get_json(silent=True) or {}
        service = ApiReviewService(store)
        actor = {"user_id": identity.user_id, "username": identity.username}
        changes = body.get("changes") if isinstance(body.get("changes"), list) else []
        if changes:
            service.review_cases(
                task_id, base_version=int(body.get("base_version", 0)), changes=changes,
                actor=actor, can_approve_high_risk=True,
            )
        gap_ids = body.get("accept_gap_ids") if isinstance(body.get("accept_gap_ids"), list) else []
        if gap_ids:
            service.accept_coverage_gaps(
                task_id, base_version=int(body.get("coverage_base_version", 0)),
                gap_ids=gap_ids, reason=str(body.get("reason", "")), actor=actor,
            )
        if not changes and not gap_ids:
            raise ServiceError(422, "REVIEW_PATCH_INVALID", "用例或覆盖 Review 变更不能为空")
        append_event(store, record, stage="case_review", node="case_review", message=f"用例 Review 已处理 {len(changes)} 项，接受缺口 {len(gap_ids)} 项")
        return jsonify(build_case_view(store, store.load(task_id) or record))

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/executable-cases/generate")
    def generate_executable(task_id: str):
        store, _record, _identity = context(task_id, "api-test-agent.executable.generate")
        require_csrf(request)
        contracts_version = ApiV2Store(store).load_version(task_id, "contracts")["version"]
        cases_version = ApiV2Store(store).load_version(task_id, "base-cases")
        current_contract = int((store.load(task_id) or {}).get("current_versions", {}).get("contracts", {}).get("version", 0))
        if int(cases_version.get("source_versions", {}).get("contracts", 0)) != current_contract:
            raise ServiceError(409, "CASE_VERSION_STALE", "基础用例基于旧契约版本，请重新生成")
        if not any(item.get("status") == "confirmed" for item in cases_version["items"]):
            raise ServiceError(409, "CASE_NOT_CONFIRMED", "至少确认一个基础用例后才能生成可执行用例")
        queued = current_app.extensions["task_manager"].enqueue_stage(
            task_id, from_stage="executable_generation", expected_status="waiting_case_review",
            source_versions={"contracts": contracts_version, "base-cases": cases_version["version"]},
        )
        return jsonify(public_task(queued)), 202

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/executable-cases")
    def get_executable_cases(task_id: str):
        """返回可执行定义详情、Review 和静态校验状态。"""

        store, record, _identity = context(task_id, "tool.result.view")
        try:
            envelope = ApiV2Store(store).load_version(task_id, "executable-cases")
        except FileNotFoundError:
            state = "generating" if (
                record.get("status") in {"pending", "running"}
                and "executable" in str(record.get("stage", ""))
            ) else "not_generated"
            return jsonify({
                "stage_state": state, "version": 0, "sha256": "", "source_versions": {},
                "lifecycle_status": "current", "items": [], "ready_count": 0, "disabled_count": 0,
            })
        current = int(record.get("current_versions", {}).get("executable-cases", {}).get("version", 0) or 0)
        lifecycle = "current" if int(envelope["version"]) == current else "stale"
        items = envelope.get("items") if isinstance(envelope.get("items"), list) else []
        ready = sum(item.get("validation_status") == "ready" for item in items if isinstance(item, dict))
        disabled = len(items) - ready
        public_envelope = redact_structure(envelope)
        return jsonify({
            **public_envelope,
            "stage_state": "stale" if lifecycle == "stale" else (
                "partial_ready" if ready and disabled else "ready" if ready else "failed"
            ),
            "lifecycle_status": lifecycle, "ready_count": ready, "disabled_count": disabled,
        })

    @blueprint.put(f"{api_prefix}/tasks/<task_id>/executable-cases/review")
    def review_executable_cases(task_id: str):
        """对执行定义进行独立 Review；静态禁用项不能被人工强制确认。"""

        store, record, identity = context(task_id, "api-test-agent.executable.review")
        require_csrf(request)
        if record.get("status") not in {"waiting_executable_review", "waiting_execution_confirmation"}:
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务不在执行定义 Review 阶段")
        body = request.get_json(silent=True) or {}
        changes = body.get("changes") if isinstance(body.get("changes"), list) else []
        if not changes:
            raise ServiceError(422, "REVIEW_PATCH_INVALID", "执行定义 Review 变更不能为空")
        saved = ApiReviewService(store).review_executable_cases(
            task_id, base_version=int(body.get("base_version", 0)), changes=changes,
            actor={"user_id": identity.user_id, "username": identity.username},
        )
        append_event(
            store, record, stage="executable_review", node="executable_review",
            message=f"执行定义 Review 已保存为 v{saved['version']}",
        )
        return jsonify(saved)

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/retry")
    def retry(task_id: str):
        store, record, _identity = context(task_id, "tool.execute")
        require_csrf(request)
        if record.get("status") != "failed":
            raise ServiceError(409, "INVALID_TASK_STATE", "仅失败任务允许阶段重试")
        body = request.get_json(silent=True) or {}
        retry_stage = str(body.get("stage", ""))
        source_versions = body.get("source_versions") if isinstance(body.get("source_versions"), dict) else {}
        attempt_id = str(record.get("current_attempt_id") or "")
        if attempt_id.startswith("attempt_") and attempt_id.replace("_", "").isalnum():
            try:
                attempt = json.loads(
                    (store.task_dir(task_id) / "attempts" / attempt_id / "attempt.json").read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                attempt = {}
            if attempt.get("task_id") == task_id and attempt.get("stage") in {
                "document_preflight", "base_case_generation", "executable_generation",
            }:
                retry_stage = str(attempt["stage"])
                if not source_versions:
                    source_versions = attempt.get("source_versions") or {}
        queued = current_app.extensions["task_manager"].enqueue_stage(
            task_id, from_stage=retry_stage, expected_status="failed",
            source_versions=source_versions,
        )
        return jsonify(public_task(queued)), 202

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/execution-plans/preview")
    def execution_plan_preview(task_id: str):
        """确定性编译执行计划；存在 blocker 也返回 200 供页面修复。"""

        store, record, _identity = context(task_id, "tool.result.view")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        return jsonify(redact_structure(compile_plan_preview(store, record, body)))

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/execution-plans")
    def create_execution_plan(task_id: str):
        """保存通过门禁的不可变 ExecutionPlan 版本，但不创建 Run。"""

        store, record, identity = context(task_id, "api-test-agent.executable.review")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        idempotency_key = str(body.get("idempotency_key", "")).strip()
        reason = str(body.get("reason", "")).strip()
        if not idempotency_key or len(idempotency_key) > 128 or not reason:
            raise ServiceError(422, "INVALID_INPUT", "创建执行计划必须提供幂等键和原因")
        existing_version = int(
            (record.get("execution_plan_idempotency") or {}).get(idempotency_key, 0) or 0
        )
        if existing_version:
            return jsonify(redact_structure(
                ApiV2Store(store).load_version(task_id, "execution-plans", existing_version)
            )), 200
        preview = compile_plan_preview(store, record, body)
        if preview["stage_state"] != "ready" or not preview["plan"]:
            raise ServiceError(409, "EXECUTION_PLAN_INVALID", "执行计划存在阻断项，不能保存")
        plan_id = f"plan_{secrets.token_hex(10)}"
        next_version = int(
            record.get("current_versions", {}).get("execution-plans", {}).get("version", 0) or 0
        ) + 1
        plan = rehash_execution_plan(ExecutionPlan.model_validate({
            **preview["plan"], "plan_id": plan_id, "version": next_version,
            "created_by": identity.user_id, "review_reason": reason,
        }).model_dump(mode="json"))
        saved = ApiV2Store(store).save_version(
            task_id, kind="execution-plans", items=plan,
            source_versions={"executable-cases": preview["source_executable_version"]},
            created_by=identity.user_id, artifact_schema_version=1,
        )
        refreshed = store.load(task_id) or record
        refreshed.setdefault("execution_plan_idempotency", {})[idempotency_key] = int(saved["version"])
        refreshed.update({"status": "waiting_execution_confirmation", "stage": "execution_plan_review"})
        store.save(refreshed)
        append_event(
            store, refreshed, stage="execution_plan", node="plan_create",
            message=f"已保存执行计划 {plan_id} v{saved['version']}",
        )
        return jsonify(redact_structure(saved)), 201

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/execution-plans/<plan_id>")
    def get_execution_plan(task_id: str, plan_id: str):
        """按受控计划 ID 读取任务内版本，不接受文件路径。"""

        store, _record, _identity = context(task_id, "tool.result.view")
        if not plan_id.startswith("plan_") or "/" in plan_id or ".." in plan_id:
            raise ServiceError(404, "EXECUTION_PLAN_NOT_FOUND", "执行计划不存在")
        match = next((
            item for item in ApiV2Store(store).list_versions(task_id, "execution-plans")
            if isinstance(item.get("items"), dict) and item["items"].get("plan_id") == plan_id
        ), None)
        if match is None:
            raise ServiceError(404, "EXECUTION_PLAN_NOT_FOUND", "执行计划不存在")
        return jsonify(redact_structure(match))

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/execution-plans/<plan_id>/confirm")
    def confirm_execution_plan(task_id: str, plan_id: str):
        """独立确认执行计划；确认动作本身不会创建 Run 或发送请求。"""

        store, record, identity = context(task_id, "api-test-agent.execute")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        reason = str(body.get("reason", "")).strip()
        if not reason:
            raise ServiceError(422, "INVALID_INPUT", "确认执行计划必须填写原因")
        current = ApiV2Store(store).load_version(task_id, "execution-plans")
        plan = current.get("items") if isinstance(current.get("items"), dict) else {}
        if plan.get("plan_id") != plan_id:
            raise ServiceError(409, "EXECUTION_PLAN_CONFIRMATION_EXPIRED", "执行计划已不是当前版本")
        if int(body.get("plan_version", 0)) != int(current["version"]):
            raise ServiceError(409, "REVIEW_VERSION_CONFLICT", "执行计划版本已变化")
        if str(body.get("confirmation_sha256", "")) != str(plan.get("confirmation_sha256", "")):
            raise ServiceError(409, "EXECUTION_PLAN_CONFIRMATION_EXPIRED", "执行确认摘要已失效")
        confirmed_plan = ExecutionPlan.model_validate({
            **plan, "status": "confirmed", "confirmed_by": identity.user_id,
            "confirmed_at": datetime.now(UTC).isoformat(), "confirmation_reason": reason,
        }).model_dump(mode="json")
        saved = ApiV2Store(store).save_version(
            task_id, kind="execution-plans", items=confirmed_plan,
            source_versions={
                **current.get("source_versions", {}), "execution-plans": int(current["version"]),
            }, created_by=identity.user_id, artifact_schema_version=1,
        )
        refreshed = store.load(task_id) or record
        refreshed.update({"status": "waiting_execution_confirmation", "stage": "execution_ready"})
        refreshed["execution_confirmation_sha256"] = confirmed_plan["confirmation_sha256"]
        store.save(refreshed)
        append_event(
            store, refreshed, stage="execution_plan", node="plan_confirm",
            message=f"执行计划 {plan_id} 已人工确认",
        )
        return jsonify(redact_structure(saved))

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/execution-plans/<plan_id>/runs")
    def create_plan_run(task_id: str, plan_id: str):
        """从已确认当前计划创建 Run；再次执行全部目标、权限和 SHA 门禁。"""

        store, record, identity = context(task_id, "api-test-agent.execute")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        current = ApiV2Store(store).load_version(task_id, "execution-plans")
        plan = current.get("items") if isinstance(current.get("items"), dict) else {}
        if plan.get("plan_id") != plan_id or plan.get("status") != "confirmed":
            raise ServiceError(409, "EXECUTION_PLAN_INVALID", "当前执行计划不存在、已过期或未确认")
        confirmation = str(body.get("confirmation_sha256", ""))
        if confirmation != str(plan.get("confirmation_sha256", "")):
            raise ServiceError(409, "EXECUTION_PLAN_CONFIRMATION_EXPIRED", "执行计划确认摘要已失效")
        source_version = int(plan.get("source_executable_version", 0) or 0)
        current_pointer = record.get("current_versions", {}).get("executable-cases", {})
        current_executable = int(current_pointer.get("version", 0) or 0)
        if source_version != current_executable:
            raise ServiceError(409, "EXECUTION_PLAN_INVALID", "执行计划引用的执行定义已过期")
        if str(plan.get("source_executable_sha256", "")) != str(current_pointer.get("sha256", "")):
            raise ServiceError(409, "EXECUTION_PLAN_INVALID", "执行计划引用的执行定义内容已变化")
        service = (
            current_app.extensions.get("api_fake_execution_service")
            if current_app.config.get("TESTING") else current_app.extensions.get("api_real_execution_service")
        )
        if service is None or (
            not current_app.config.get("TESTING") and not current_app.extensions.get("api_execution_enabled")
        ):
            raise ServiceError(403, "EXECUTION_NOT_READY", "执行运行时未启用，未创建 Run")
        target = validate_plan_run_target(plan, record)
        run = service.execute(
            task_id,
            confirmation_sha256=confirmation,
            expected_confirmation_sha256=str(plan.get("confirmation_sha256", "")),
            actor_id=identity.user_id,
            environment=str(record.get("environment", "test")),
            target_id=target.target_id,
            resolved_target_url=target.internal_base_url,
            execution_plan=plan,
        )
        append_event(
            store, record, stage="execution", node="execution_plan_run",
            message=f"已按计划 {plan_id} 创建受控 Run：{run.run_id}",
            event_type="started", run_id=run.run_id,
        )
        return jsonify(run.model_dump(mode="json")), 202

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/runs/<run_id>/steps")
    def get_run_steps(task_id: str, run_id: str):
        """返回脱敏逐节点结果；兼容历史 CaseResult 中的嵌套步骤。"""

        store, _record, _identity = context(task_id, "tool.result.view")
        if not run_id.startswith("run_") or "/" in run_id or ".." in run_id:
            raise ServiceError(404, "RUN_NOT_FOUND", "Run 不存在")
        run_dir = store.task_dir(task_id) / "runs" / run_id
        steps_path = run_dir / "step-results.json"
        try:
            if steps_path.is_file():
                items = json.loads(steps_path.read_text(encoding="utf-8"))
            else:
                case_results = json.loads((run_dir / "case-results.json").read_text(encoding="utf-8"))
                items = [
                    step for result in case_results if isinstance(result, dict)
                    for step in result.get("step_results", []) if isinstance(step, dict)
                ]
        except (OSError, json.JSONDecodeError):
            raise ServiceError(404, "RUN_RESULT_NOT_FOUND", "Run 步骤结果不存在") from None
        return jsonify({"items": redact_structure(items), "run_id": run_id})

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/execute/preview")
    def execution_preview(task_id: str):
        store, _record, identity = context(task_id, "tool.result.view")
        require_permission(identity, "tool.result.view")
        preview = build_preview(store, task_id)
        try:
            plan_envelope = ApiV2Store(store).load_version(task_id, "execution-plans")
            plan = plan_envelope.get("items") if isinstance(plan_envelope.get("items"), dict) else {}
        except FileNotFoundError:
            plan = {}
        if plan:
            preview.update({
                "plan_id": plan.get("plan_id"), "plan_version": plan_envelope["version"],
                "plan_status": plan.get("status", "ready"),
                "confirmation_sha256": plan.get("confirmation_sha256"),
                "ready_case_ids": plan.get("topological_order", []),
                "write_case_count": int(plan.get("write_operation_count", 0)),
                "high_risk_count": int(plan.get("high_risk_count", 0)),
            })
        if plan.get("status") != "confirmed":
            preview.setdefault("blocking_reasons", []).append("尚未创建并确认 V2.4 执行计划")
        return jsonify(preview)

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/execute")
    def execute(task_id: str):
        store, record, identity = context(task_id, "api-test-agent.execute")
        require_csrf(request)
        require_permission(identity, "api-test-agent.execute")
        fake_service = current_app.extensions.get("api_fake_execution_service") if current_app.config.get("TESTING") else None
        service = fake_service or current_app.extensions.get("api_real_execution_service")
        if service is None or (not current_app.config.get("TESTING") and not current_app.extensions.get("api_execution_enabled")):
            # 门禁拒绝必须发生在创建 Run 之前。
            raise ServiceError(403, "EXECUTION_NOT_READY", "执行运行时未启用，未创建 Run")
        body = request.get_json(silent=True) or {}
        preview = build_preview(store, task_id)
        if preview.get("legacy_blocked_case_ids"):
            raise ServiceError(409, "LEGACY_VALIDATION_REQUIRED", "历史执行定义未通过 V2.2 门禁")
        try:
            plan_envelope = ApiV2Store(store).load_version(task_id, "execution-plans")
            plan = plan_envelope.get("items") if isinstance(plan_envelope.get("items"), dict) else {}
        except FileNotFoundError:
            plan = {}
        if plan.get("status") != "confirmed":
            raise ServiceError(409, "LEGACY_VALIDATION_REQUIRED", "请先生成并确认 V2.4 执行计划")
        expected_confirmation = str(plan.get("confirmation_sha256", ""))
        if str(body.get("confirmation_sha256", "")) != expected_confirmation:
            raise ServiceError(409, "EXECUTION_PLAN_CONFIRMATION_EXPIRED", "执行计划确认摘要已失效")
        if not current_app.config.get("TESTING") and preview["blocking_reasons"]:
            raise ServiceError(403, "EXECUTION_NOT_READY", "执行预览存在阻断项，未创建 Run")
        targets = current_app.extensions.get("api_execution_targets", {})
        target = targets.get(str(plan.get("target_id", "")))
        if not current_app.config.get("TESTING") and target is None:
            raise ServiceError(403, "EXECUTION_TARGET_DENIED", "目标未登记，未创建 Run")
        run = service.execute(
            task_id, confirmation_sha256=expected_confirmation,
            expected_confirmation_sha256=expected_confirmation, actor_id=identity.user_id,
            environment=record.get("environment", "test"),
            target_id=target.target_id if target else "s1-mock-target",
            resolved_target_url=target.internal_base_url if target else "", execution_plan=plan,
        )
        append_event(store, record, stage="execution", node="execution_controller", message=f"已创建受控执行 Run：{run.run_id}", event_type="started", run_id=run.run_id)
        return jsonify(run.model_dump(mode="json")), 202

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/runs/<run_id>")
    def get_run(task_id: str, run_id: str):
        store, _record, _identity = context(task_id, "tool.result.view")
        if not run_id.startswith("run_") or "/" in run_id or ".." in run_id:
            raise ServiceError(404, "RUN_NOT_FOUND", "Run 不存在")
        path = store.task_dir(task_id) / "runs" / run_id / "run.json"
        try:
            run_payload = json.loads(path.read_text(encoding="utf-8"))
            report = json.loads((path.parent / "report.json").read_text(encoding="utf-8")) if (path.parent / "report.json").is_file() else None
        except (OSError, ValueError):
            raise ServiceError(404, "RUN_NOT_FOUND", "Run 不存在") from None
        return jsonify({"run": run_payload, "report": report})

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/stage-events")
    def list_stage_events(task_id: str):
        """返回当前任务的脱敏阶段事件，支持 Attempt 和游标筛选。"""

        store, record, _identity = context(task_id, "tool.result.view")
        attempt_id = str(request.args.get("attempt_id") or record.get("current_attempt_id") or "")
        try:
            payload = StageEventStore(store).list_events(
                task_id, attempt_id=attempt_id, run_id=str(request.args.get("run_id", "")),
                stage=str(request.args.get("stage", "")),
                level=str(request.args.get("level", "")),
                cursor=int(request.args.get("cursor", 0)), limit=int(request.args.get("limit", 100)),
            )
        except (TypeError, ValueError):
            raise ServiceError(422, "STAGE_EVENT_QUERY_INVALID", "阶段记录查询参数不合法") from None
        return jsonify(payload)

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/model-usage")
    def get_model_usage(task_id: str):
        """返回当前 Attempt 的供应商报告 Token 用量。"""

        store, record, _identity = context(task_id, "tool.result.view")
        attempt_id = str(request.args.get("attempt_id") or record.get("current_attempt_id") or "")
        try:
            return jsonify(StageEventStore(store).list_usage(task_id, attempt_id=attempt_id))
        except ValueError:
            raise ServiceError(422, "STAGE_EVENT_QUERY_INVALID", "Attempt ID 不合法") from None

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/generation-provenance")
    def get_generation_provenance(task_id: str):
        """返回生成内核、输入版本和 Prompt SHA，不返回 Prompt 正文。"""

        store, record, _identity = context(task_id, "tool.result.view")
        attempt_id = str(request.args.get("attempt_id") or record.get("current_attempt_id") or "")
        try:
            return jsonify(StageEventStore(store).load_provenance(task_id, attempt_id=attempt_id))
        except ValueError:
            raise ServiceError(422, "STAGE_EVENT_QUERY_INVALID", "Attempt ID 不合法") from None

    def usage_filters() -> dict[str, str]:
        """只接受统计接口声明的筛选字段。"""

        aliases = {"model": "model_name", "prompt": "prompt_id", "kernel": "generation_kernel"}
        allowed = {
            "project_id", "module_id", "attempt_id", "stage", "node",
            "model", "prompt", "kernel", "status", "from", "to",
        }
        return {aliases.get(key, key): str(request.args[key]) for key in allowed if request.args.get(key)}

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/usage/summary")
    def task_usage_summary(task_id: str):
        """聚合当前任务全部 Attempt 的调用质量。"""

        store, record, _identity = context(task_id, "tool.result.view")
        try:
            payload = StageEventStore(store).summarize_usage(
                [record], group_by=str(request.args.get("group_by", "attempt")),
                filters=usage_filters(),
            )
        except ValueError as exc:
            raise ServiceError(422, "STAGE_EVENT_QUERY_INVALID", str(exc)) from exc
        return jsonify(payload)

    @blueprint.get(f"{api_prefix}/usage/summary")
    def global_usage_summary():
        """为具备全局查看权限的角色提供最多90天的文件化聚合。"""

        store = current_app.extensions["task_store"]
        identity = identity_from_request(
            request, current_app.extensions["platform_client"], action="read",
        )
        require_permission(identity, "task.view.all")
        # 这是全局聚合而非可枚举的单个业务对象：先保持既有动作权限语义，
        # 再要求平台签发 global 范围，不能由旧 Header 单独扩大统计范围。
        if identity.data_scope != "global":
            raise ServiceError(403, "PERMISSION_DENIED", "无权执行此操作")
        filters = usage_filters()
        now = datetime.now(UTC)
        filters.setdefault("from", (now - timedelta(days=30)).isoformat())
        filters.setdefault("to", now.isoformat())
        try:
            start = datetime.fromisoformat(filters["from"].replace("Z", "+00:00")).astimezone(UTC)
            end = datetime.fromisoformat(filters["to"].replace("Z", "+00:00")).astimezone(UTC)
            if end < start or end - start > timedelta(days=90):
                raise ValueError("全局统计时间范围必须为0～90天")
            records = [item for item in store.list() if item.get("schema_version") == 2]
            payload = StageEventStore(store).summarize_usage(
                records, group_by=str(request.args.get("group_by", "project")), filters=filters,
            )
        except ValueError as exc:
            raise ServiceError(422, "STAGE_EVENT_QUERY_INVALID", str(exc)) from exc
        return jsonify(payload)

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/runs")
    def list_runs(task_id: str):
        """返回当前任务的 Run 安全摘要，供工作台在刷新后恢复执行上下文。

        返回值不包含请求、响应、日志或凭证；损坏的 Run 文件会被忽略，
        不影响其他已完成 Run 的可见性。
        """

        store, _record, _identity = context(task_id, "tool.result.view")
        runs_dir = store.task_dir(task_id) / "runs"
        items = []
        for path in runs_dir.glob("run_*/run.json") if runs_dir.is_dir() else []:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                run_id = str(payload.get("run_id", ""))
                if path.parent.name != run_id or not run_id.startswith("run_"):
                    continue
                summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
                items.append({
                    "run_id": run_id,
                    "status": str(payload.get("status", "failed")),
                    "created_at": str(payload.get("created_at", "")),
                    "finished_at": payload.get("finished_at"),
                    "total_cases": int(summary.get("total", 0)),
                    "passed_cases": int(summary.get("passed", 0)),
                    "failed_cases": int(summary.get("failed", 0)),
                })
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        items.sort(key=lambda item: (item["created_at"], item["run_id"]), reverse=True)
        return jsonify({"items": items, "latest_run_id": items[0]["run_id"] if items else None})

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/runs/<run_id>/cancel")
    def cancel_run(task_id: str, run_id: str):
        _store, _record, _identity = context(task_id, "api-test-agent.execute", action="cancel")
        require_csrf(request)
        service = (current_app.extensions.get("api_fake_execution_service") if current_app.config.get("TESTING") else None) or current_app.extensions.get("api_real_execution_service")
        if service is None or (
            not current_app.config.get("TESTING")
            and not current_app.extensions.get("api_execution_enabled")
        ):
            raise ServiceError(403, "EXECUTION_NOT_READY", "执行运行时未启用")
        return jsonify(service.cancel(task_id, run_id).model_dump(mode="json"))

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/runs/<run_id>/retry")
    def retry_run(task_id: str, run_id: str):
        """基于原 Run 的已确认执行计划创建独立重试 Run。

        重试不能重新读取并直接执行当前用例数组，否则历史 Run 在契约或执行定义
        更新后可能获得另一组业务输入。这里只允许复用仍为 current、confirmed 的
        V2.4 ExecutionPlan；历史无计划 Run 必须先重新生成并确认执行计划。
        """

        store, record, identity = context(task_id, "api-test-agent.execute")
        require_csrf(request)
        service = (current_app.extensions.get("api_fake_execution_service") if current_app.config.get("TESTING") else None) or current_app.extensions.get("api_real_execution_service")
        if service is None or (
            not current_app.config.get("TESTING")
            and not current_app.extensions.get("api_execution_enabled")
        ):
            raise ServiceError(403, "EXECUTION_NOT_READY", "执行运行时未启用")
        original_run = service.load_run(task_id, run_id)
        if not original_run.execution_plan_id:
            raise ServiceError(409, "LEGACY_VALIDATION_REQUIRED", "历史 Run 未绑定 V2.4 执行计划，不能直接重试")
        try:
            plan_envelope = ApiV2Store(store).load_version(task_id, "execution-plans")
        except FileNotFoundError:
            raise ServiceError(409, "LEGACY_VALIDATION_REQUIRED", "原执行计划已不可用，请重新生成并确认") from None
        plan = plan_envelope.get("items") if isinstance(plan_envelope.get("items"), dict) else {}
        if (
            plan.get("plan_id") != original_run.execution_plan_id
            or plan.get("status") != "confirmed"
            or str(plan.get("sha256", "")) != original_run.execution_plan_sha256
        ):
            raise ServiceError(409, "EXECUTION_PLAN_STALE", "原执行计划已失效，请重新预览并确认")
        target = validate_plan_run_target(plan, record)
        confirmation_sha256 = str(plan.get("confirmation_sha256", ""))
        run = service.execute(
            task_id, confirmation_sha256=confirmation_sha256,
            expected_confirmation_sha256=confirmation_sha256, actor_id=identity.user_id,
            environment=record.get("environment", "test"), target_id=target.target_id,
            resolved_target_url=target.internal_base_url,
            execution_plan=plan, retry_of_run_id=run_id,
        )
        return jsonify(run.model_dump(mode="json")), 202

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/defect-drafts")
    def create_defect(task_id: str):
        store, record, identity = context(task_id, "api-test-agent.defect.create")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        case_ids = body.get("case_ids") if isinstance(body.get("case_ids"), list) else []
        draft = DefectDraftService(store).create(
            task_id, str(body.get("run_id", "")), [str(item) for item in case_ids],
            actor_id=identity.user_id, manual_reason=str(body.get("manual_reason", "")),
        )
        append_event(store, record, stage="defect_draft", node="draft_create", message=f"已生成本地 Bug 草稿：{draft.draft_id}")
        return jsonify(draft.model_dump(mode="json")), 201

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/defect-drafts")
    def list_defects(task_id: str):
        store, _record, _identity = context(task_id, "tool.result.view")
        return jsonify({"items": [
            item.model_dump(mode="json") for item in DefectDraftService(store).list(task_id)
        ]})

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/defect-drafts/<draft_id>")
    def get_defect(task_id: str, draft_id: str):
        store, _record, _identity = context(task_id, "tool.result.view")
        return jsonify(DefectDraftService(store).load(task_id, draft_id).model_dump(mode="json"))

    @blueprint.put(f"{api_prefix}/tasks/<task_id>/defect-drafts/<draft_id>")
    def update_defect(task_id: str, draft_id: str):
        store, record, identity = context(task_id, "api-test-agent.defect.create")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        draft = DefectDraftService(store).update(
            task_id, draft_id, base_version=int(body.get("base_version", 0)),
            fields=body.get("fields") if isinstance(body.get("fields"), dict) else {}, actor_id=identity.user_id,
        )
        append_event(store, record, stage="defect_draft", node="draft_update", message=f"本地 Bug 草稿已保存为 v{draft.version}")
        return jsonify(draft.model_dump(mode="json"))

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/defect-drafts/<draft_id>/download")
    def download_defect(task_id: str, draft_id: str):
        store, record, _identity = context(task_id, "tool.result.view")
        payload, mimetype, name = DefectDraftService(store).download(
            task_id, draft_id, request.args.get("format", "json"),
        )
        append_event(store, record, stage="defect_draft", node="draft_download", message=f"已下载本地 Bug 草稿：{draft_id}")
        return send_file(io.BytesIO(payload), mimetype=mimetype, as_attachment=True, download_name=name, max_age=0)

    return blueprint
