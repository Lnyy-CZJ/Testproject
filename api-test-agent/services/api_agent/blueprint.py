"""API 测试智能体 V2 的专属 Review、重试和执行准备 HTTP 协议。"""

from __future__ import annotations

import io

from flask import Blueprint, current_app, jsonify, request, send_file

from services.api_agent.defect_service import DefectDraftService
from services.api_agent.review_service import ApiReviewService
from services.api_agent.v2_store import ApiV2Store, canonical_sha256
from services.common.errors import ServiceError
from services.common.identity import identity_from_request, require_csrf, require_permission, require_task_access
from services.common.task_models import public_task


def create_api_v2_blueprint(base_path: str) -> Blueprint:
    """创建 API 专属 Blueprint，避免继续扩展公共 web.py 的业务语义。"""

    blueprint = Blueprint("api_v2", __name__)
    api_prefix = f"{base_path}/api/v1"

    def context(task_id: str, permission: str):
        store = current_app.extensions["task_store"]
        record = store.load(task_id)
        if not record or record.get("schema_version") != 2:
            raise ServiceError(404, "TASK_NOT_FOUND", "V2 任务不存在")
        identity = identity_from_request(request)
        require_task_access(identity, record, permission=permission)
        return store, record, identity

    def build_preview(store, task_id: str) -> dict:
        """构造稳定执行确认摘要；目标信息始终脱敏且不包含可执行 Host。"""

        try:
            executable = ApiV2Store(store).load_version(task_id, "executable-cases")
            ready = [item for item in executable["items"] if item.get("validation_status") == "ready" and item.get("enabled")]
        except FileNotFoundError:
            executable, ready = {"version": 0, "sha256": "", "items": []}, []
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
        }
        summary["confirmation_sha256"] = canonical_sha256(summary)
        return summary

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/contracts")
    def contracts(task_id: str):
        store, record, _identity = context(task_id, "tool.result.view")
        payload = ApiV2Store(store).load_version(task_id, "contracts")
        return jsonify({**payload, "task_status": record["status"]})

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
        payload = ApiV2Store(store).load_version(task_id, "base-cases")
        coverage = ApiV2Store(store).load_version(task_id, "coverage")
        return jsonify({**payload, "coverage": coverage, "task_status": record["status"]})

    @blueprint.put(f"{api_prefix}/tasks/<task_id>/cases/review")
    def review_cases(task_id: str):
        store, record, identity = context(task_id, "api-test-agent.case.review")
        require_csrf(request)
        if record.get("status") != "waiting_case_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务不在用例 Review 阶段")
        body = request.get_json(silent=True) or {}
        result = ApiReviewService(store).review_cases(
            task_id, base_version=int(body.get("base_version", 0)),
            changes=body.get("changes") if isinstance(body.get("changes"), list) else [],
            actor={"user_id": identity.user_id, "username": identity.username},
            can_approve_high_risk="api-test-agent.execute" in identity.permissions,
        )
        return jsonify(result)

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/executable-cases/generate")
    def generate_executable(task_id: str):
        store, _record, _identity = context(task_id, "api-test-agent.case.review")
        require_csrf(request)
        contracts_version = ApiV2Store(store).load_version(task_id, "contracts")["version"]
        cases_version = ApiV2Store(store).load_version(task_id, "base-cases")
        if not any(item.get("status") == "confirmed" for item in cases_version["items"]):
            raise ServiceError(409, "CASE_NOT_CONFIRMED", "至少确认一个基础用例后才能生成可执行用例")
        queued = current_app.extensions["task_manager"].enqueue_stage(
            task_id, from_stage="executable_generation", expected_status="waiting_case_review",
            source_versions={"contracts": contracts_version, "base-cases": cases_version["version"]},
        )
        return jsonify(public_task(queued)), 202

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/retry")
    def retry(task_id: str):
        _store, record, _identity = context(task_id, "tool.execute")
        require_csrf(request)
        if record.get("status") != "failed":
            raise ServiceError(409, "INVALID_TASK_STATE", "仅失败任务允许阶段重试")
        body = request.get_json(silent=True) or {}
        queued = current_app.extensions["task_manager"].enqueue_stage(
            task_id, from_stage=str(body.get("stage", "")), expected_status="failed",
            source_versions=body.get("source_versions") if isinstance(body.get("source_versions"), dict) else {},
        )
        return jsonify(public_task(queued)), 202

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/execute/preview")
    def execution_preview(task_id: str):
        store, _record, identity = context(task_id, "tool.result.view")
        require_permission(identity, "tool.result.view")
        return jsonify(build_preview(store, task_id))

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
        if not current_app.config.get("TESTING") and preview["blocking_reasons"]:
            raise ServiceError(403, "EXECUTION_NOT_READY", "执行预览存在阻断项，未创建 Run")
        targets = current_app.extensions.get("api_execution_targets", {})
        target = targets.get(str(body.get("target_id") or preview.get("target_id")))
        if not current_app.config.get("TESTING") and target is None:
            raise ServiceError(403, "EXECUTION_TARGET_DENIED", "目标未登记，未创建 Run")
        run = service.execute(
            task_id, confirmation_sha256=str(body.get("confirmation_sha256", "")),
            expected_confirmation_sha256=preview["confirmation_sha256"], actor_id=identity.user_id,
            environment=record.get("environment", "test"),
            target_id=target.target_id if target else "s1-mock-target",
            resolved_target_url=target.internal_base_url if target else "",
        )
        return jsonify(run.model_dump(mode="json")), 202

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/runs/<run_id>")
    def get_run(task_id: str, run_id: str):
        store, _record, _identity = context(task_id, "tool.result.view")
        if not run_id.startswith("run_") or "/" in run_id or ".." in run_id:
            raise ServiceError(404, "RUN_NOT_FOUND", "Run 不存在")
        path = store.task_dir(task_id) / "runs" / run_id / "run.json"
        try:
            import json
            run_payload = json.loads(path.read_text(encoding="utf-8"))
            report = json.loads((path.parent / "report.json").read_text(encoding="utf-8")) if (path.parent / "report.json").is_file() else None
        except (OSError, ValueError):
            raise ServiceError(404, "RUN_NOT_FOUND", "Run 不存在") from None
        return jsonify({"run": run_payload, "report": report})

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/runs/<run_id>/cancel")
    def cancel_run(task_id: str, run_id: str):
        _store, _record, _identity = context(task_id, "api-test-agent.execute")
        require_csrf(request)
        service = (current_app.extensions.get("api_fake_execution_service") if current_app.config.get("TESTING") else None) or current_app.extensions.get("api_real_execution_service")
        if service is None:
            raise ServiceError(403, "EXECUTION_NOT_READY", "执行运行时未启用")
        return jsonify(service.cancel(task_id, run_id).model_dump(mode="json"))

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/runs/<run_id>/retry")
    def retry_run(task_id: str, run_id: str):
        store, record, identity = context(task_id, "api-test-agent.execute")
        require_csrf(request)
        service = (current_app.extensions.get("api_fake_execution_service") if current_app.config.get("TESTING") else None) or current_app.extensions.get("api_real_execution_service")
        if service is None:
            raise ServiceError(403, "EXECUTION_NOT_READY", "执行运行时未启用")
        service.load_run(task_id, run_id)
        preview = build_preview(store, task_id)
        target = next(iter(current_app.extensions.get("api_execution_targets", {}).values()), None)
        run = service.execute(
            task_id, confirmation_sha256=preview["confirmation_sha256"],
            expected_confirmation_sha256=preview["confirmation_sha256"], actor_id=identity.user_id,
            environment=record.get("environment", "test"), target_id=target.target_id if target else "s1-mock-target",
            resolved_target_url=target.internal_base_url if target else "",
        )
        return jsonify(run.model_dump(mode="json")), 202

    @blueprint.post(f"{api_prefix}/tasks/<task_id>/defect-drafts")
    def create_defect(task_id: str):
        store, _record, identity = context(task_id, "api-test-agent.defect.create")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        case_ids = body.get("case_ids") if isinstance(body.get("case_ids"), list) else []
        draft = DefectDraftService(store).create(
            task_id, str(body.get("run_id", "")), [str(item) for item in case_ids],
            actor_id=identity.user_id, manual_reason=str(body.get("manual_reason", "")),
        )
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
        store, _record, identity = context(task_id, "api-test-agent.defect.create")
        require_csrf(request)
        body = request.get_json(silent=True) or {}
        draft = DefectDraftService(store).update(
            task_id, draft_id, base_version=int(body.get("base_version", 0)),
            fields=body.get("fields") if isinstance(body.get("fields"), dict) else {}, actor_id=identity.user_id,
        )
        return jsonify(draft.model_dump(mode="json"))

    @blueprint.get(f"{api_prefix}/tasks/<task_id>/defect-drafts/<draft_id>/download")
    def download_defect(task_id: str, draft_id: str):
        store, _record, _identity = context(task_id, "tool.result.view")
        payload, mimetype, name = DefectDraftService(store).download(
            task_id, draft_id, request.args.get("format", "json"),
        )
        return send_file(io.BytesIO(payload), mimetype=mimetype, as_attachment=True, download_name=name, max_age=0)

    return blueprint
