"""功能测试智能体的 Flask HTTP 与页面协议。"""

from __future__ import annotations

import json
import io
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from flask import Flask, Response, g, jsonify, render_template, request, send_file
from jinja2 import ChoiceLoader, FileSystemLoader
from pydantic import ValidationError

from services.common.artifacts import load_registry, preview_artifact, resolve_artifact
from services.common.audit import emit_audit
from services.common.case_review import CaseReviewService, parse_cases
from services.common.config import ServiceSettings
from services.common.errors import ServiceError, error_payload
from services.common.identity import (
    identity_from_request,
    require_csrf,
    require_permission,
    require_task_access,
)
from services.common.platform_client import PlatformClient
from services.common.redaction import redact_text
from services.common.review import ReviewService, parse_points
from services.common.task_manager import TaskManager
from services.common.task_models import public_task, utc_now
from services.common.task_store import TaskStore, new_task_id
from services.common.uploads import (
    FUNCTIONAL_EXTENSIONS,
    atomic_write_bytes,
    read_validated_text,
    sha256_bytes,
    validate_review_json,
)


def safe_public_tasks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    将任务记录逐条转换为公开渲染载荷,跳过 schema 不兼容的记录。

    功能说明:
        正常任务照常经 public_task 转换;若某条记录因缺少必填字段
        (例如手工测试残留的最小 schema 数据)未通过 Pydantic 校验,
        仅跳过该条记录,避免单条坏数据导致整个任务列表返回 500。

    参数说明:
        items (list[dict]): TaskStore.list 返回的原始任务记录列表。

    返回值:
        list[dict]: 校验通过的公开任务载荷列表,保持原有顺序。

    异常说明:
        内部捕获 pydantic.ValidationError,不向调用方传播。
    """
    payloads: list[dict[str, Any]] = []
    for record in items:
        try:
            payloads.append(public_task(record))
        except ValidationError:
            # 跳过不兼容记录,防止单条坏数据打挂整个列表页。
            continue
    return payloads


def _new_record(task_id: str, settings: ServiceSettings, identity, form: dict[str, Any]) -> dict[str, Any]:
    """构造完整内部任务记录，路径与进程字段只保存在 internal。"""

    from services.functional_agent.adapter import safe_slug

    now = datetime.now(UTC)
    return {
        "schema_version": 1,
        "id": task_id,
        "agent_type": settings.agent_type,
        "operation": form["operation"],
        "status": "pending",
        "stage": "queued",
        "created_by_user_id": identity.user_id,
        "created_by_username": identity.username,
        "project_id": safe_slug(form["project_name"], "project"),
        "project_name": form["project_name"],
        "module_id": safe_slug(form["module_name"], "module"),
        "module_name": form["module_name"],
        "title": form.get("title") or f"{form['project_name']} / {form['module_name']}",
        "environment": settings.runtime_environment,
        "created_at": now.isoformat(),
        "started_at": None,
        "finished_at": None,
        "resume_requested_at": None,
        "cancel_requested_at": None,
        "config_release_id": None,
        "config_release_version": None,
        "model_name": None,
        "prompt_bundle_sha256": None,
        "app_revision": settings.app_revision,
        "result_summary": {},
        "error_code": None,
        "error_message": None,
        "artifacts_expire_at": (now + timedelta(days=90)).isoformat(),
        "artifacts_expired": False,
        "review": {},
        "config_history": [],
        "internal": {"pid": None, "exit_code": None, "timeout": False, "revision": 0},
    }


def create_agent_app(
    *,
    settings: ServiceSettings,
    manager_factory: Callable[[TaskStore, Callable[[], dict[str, Any]]], TaskManager],
    operations: set[str],
    title: str,
    description: str,
    platform_client: PlatformClient | None = None,
    safe_config_loader: Callable[[], dict[str, Any]] | None = None,
) -> Flask:
    """创建带任务、权限、上传、日志和产物协议的功能智能体应用。"""

    if settings.agent_type != "functional":
        raise RuntimeError("功能项目只允许启动 functional 服务")

    common_dir = Path(__file__).resolve().parent
    agent_template_dir = Path(__file__).resolve().parents[1] / f"{settings.agent_type}_agent" / "templates"
    app = Flask(__name__, static_folder=str(common_dir / "static"), static_url_path=f"{settings.base_path}/static")
    app.jinja_loader = ChoiceLoader([FileSystemLoader(agent_template_dir), FileSystemLoader(common_dir / "templates")])
    app.config.update(MAX_CONTENT_LENGTH=11 * 1024 * 1024, JSON_AS_ASCII=False)
    store = TaskStore(settings.data_dir)
    client = platform_client or PlatformClient(
        settings.platform_api_url, settings.tool_id, settings.runtime_environment,
        settings.platform_client_token_file,
    )
    load_safe = safe_config_loader or (lambda: client.runtime_config(include_secrets=False))
    manager = manager_factory(store, lambda: client.runtime_config(include_secrets=True))
    review_service = ReviewService(store)
    case_review_service = CaseReviewService(store)
    app.extensions["task_store"] = store
    app.extensions["task_manager"] = manager
    app.extensions["review_service"] = review_service
    app.extensions["case_review_service"] = case_review_service
    app.extensions["platform_client"] = client

    def current_identity():
        return identity_from_request(request)

    def get_task(task_id: str, permission: str = "tool.result.view") -> tuple[dict, Any]:
        identity = current_identity()
        record = store.load(task_id)
        if not record:
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        require_task_access(identity, record, permission=permission)
        return record, identity

    def safe_limits() -> tuple[dict[str, Any], dict[str, Any]]:
        snapshot = load_safe()
        normal = snapshot.get("normal", {}) or {}
        return snapshot, normal

    def case_limits(normal: dict[str, Any]) -> dict[str, int]:
        """从当前 Release 读取用例 Review 限制，避免各路由默认值漂移。"""

        return {
            "max_cases": int(normal.get("CASE_REVIEW_MAX_CASES", 2000)),
            "max_bytes": int(normal.get("CASE_REVIEW_MAX_BYTES", 10 * 1024 * 1024)),
            "max_characters": int(normal.get("CASE_REVIEW_MAX_CHARACTERS", 1_000_000)),
        }

    def case_point_summaries(task_id: str) -> list[dict[str, Any]]:
        """读取当前确认测试点的展示摘要，不向页面暴露文件路径。"""

        task_dir = store.task_dir(task_id)
        record = store.load(task_id) or {}
        request_payload = json.loads((task_dir / "request.json").read_text(encoding="utf-8"))
        relative = (record.get("review") or {}).get("relative_path") or request_payload.get("review_relative_path")
        if not relative:
            return []
        path = (task_dir / str(relative)).resolve()
        if task_dir not in path.parents or not path.is_file() or path.is_symlink():
            return []
        try:
            points = parse_points(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ServiceError):
            return []
        return [
            {key: item.get(key, "") for key in ("id", "module", "feature", "scenario", "test_point", "risk_level")}
            for item in points if isinstance(item, dict)
        ]

    @app.before_request
    def assign_request_id() -> None:
        """为每个请求生成不可信输入无法覆盖的关联 ID。"""

        g.request_id = f"req_{secrets.token_hex(10)}"

    @app.after_request
    def secure_headers(response: Response) -> Response:
        """添加下载和页面通用安全响应头。"""

        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.errorhandler(ServiceError)
    def handle_service_error(error: ServiceError):
        return jsonify(error_payload(error, g.get("request_id", "unknown"))), error.status_code

    @app.errorhandler(413)
    def handle_too_large(_error):
        error = ServiceError(413, "INVALID_INPUT", "上传内容超过网关或服务限制")
        return jsonify(error_payload(error, g.get("request_id", "unknown"))), 413

    @app.get("/health")
    @app.get(f"{settings.base_path}/health")
    def health():
        return jsonify({
            "status": "ok", "service": settings.tool_id,
            "version": settings.app_version, "revision": settings.app_revision,
            "dirty": settings.app_build_dirty,
            "content_sha256": settings.app_content_sha256,
            "runtime_environment": settings.runtime_environment,
        })

    @app.get(f"{settings.base_path}/api/v1/readiness")
    def readiness():
        identity = current_identity()
        require_permission(identity, "tool.view")
        storage_writable = settings.data_dir.exists() and settings.data_dir.is_dir()
        try:
            snapshot, normal = safe_limits()
            configured = set(snapshot.get("configured_secret_keys", []))
            return jsonify({
                "status": "ready" if storage_writable else "not_ready",
                "storage_writable": storage_writable,
                "release_id": snapshot.get("release_id"),
                "llm_secret_configured": "LLM_API_KEY" in configured,
                "environment": settings.runtime_environment,
                "online_review_enabled": bool(normal.get("ONLINE_REVIEW_ENABLED", False)),
                "review_ai_enabled": bool(normal.get("REVIEW_AI_ENABLED", False)),
                "online_case_review_enabled": bool(normal.get("ONLINE_CASE_REVIEW_ENABLED", False)),
                "case_review_ai_enabled": bool(normal.get("CASE_REVIEW_AI_ENABLED", False)),
                "functional_workbench_v2_enabled": bool(normal.get("FUNCTIONAL_WORKBENCH_V2_ENABLED", False)),
                "functional_workbench_v3_enabled": bool(normal.get("FUNCTIONAL_WORKBENCH_V3_ENABLED", False)),
            })
        except ServiceError:
            return jsonify({"status": "not_ready", "storage_writable": storage_writable, "configuration_available": False}), 503

    @app.get(f"{settings.base_path}/")
    def index():
        identity = current_identity()
        require_permission(identity, "tool.view")
        _snapshot, normal = safe_limits()
        workbench_v2 = bool(normal.get("FUNCTIONAL_WORKBENCH_V2_ENABLED", False))
        workbench_v3 = bool(normal.get("FUNCTIONAL_WORKBENCH_V3_ENABLED", False))
        mindmap_workbench = workbench_v2 or workbench_v3
        source_records = [item for item in store.list() if item.get("created_by_user_id") == identity.user_id or "task.view.all" in identity.permissions]
        for item in source_records:
            item["workbench_v2_enabled"] = workbench_v2
            item["workbench_v3_enabled"] = workbench_v3
        records = safe_public_tasks(source_records)
        return render_template(
            "index.html", title=title, description=description, settings=settings,
            tasks=records[:20], task_total=len(records), agent_type=settings.agent_type,
            csrf_token=request.cookies.get("tp_csrf", ""), platform_home_url=settings.platform_home_url,
            functional_workbench_v2=mindmap_workbench, functional_workbench_v3=workbench_v3,
        )

    @app.get(f"{settings.base_path}/tasks/<task_id>")
    def task_page(task_id: str):
        record, identity = get_task(task_id)
        _snapshot, normal = safe_limits()
        online_review_enabled = bool(normal.get("ONLINE_REVIEW_ENABLED", False))
        online_case_review_enabled = bool(normal.get("ONLINE_CASE_REVIEW_ENABLED", False))
        workbench_v2 = bool(normal.get("FUNCTIONAL_WORKBENCH_V2_ENABLED", False))
        workbench_v3 = bool(normal.get("FUNCTIONAL_WORKBENCH_V3_ENABLED", False))
        record["workbench_v2_enabled"] = workbench_v2
        record["workbench_v3_enabled"] = workbench_v3
        return render_template(
            "task_detail.html", title=title, settings=settings, task=public_task(record),
            artifacts=load_registry(store, task_id), csrf_token=request.cookies.get("tp_csrf", ""),
            platform_home_url=settings.platform_home_url,
            online_review_enabled=online_review_enabled,
            review_ai_enabled=online_review_enabled and bool(normal.get("REVIEW_AI_ENABLED", False)),
            can_edit_review="tool.execute" in identity.permissions,
            online_case_review_enabled=online_case_review_enabled,
            case_review_ai_enabled=online_case_review_enabled and bool(normal.get("CASE_REVIEW_AI_ENABLED", False)),
            functional_workbench_v2=workbench_v2 or workbench_v3,
            functional_workbench_v3=workbench_v3,
        )

    @app.post(f"{settings.base_path}/api/v1/tasks")
    def create_task():
        identity = current_identity()
        require_permission(identity, "tool.execute")
        require_csrf(request)
        snapshot, normal = safe_limits()
        operation = request.form.get("operation", "").strip()
        if operation not in operations:
            raise ServiceError(422, "INVALID_INPUT", "操作类型不受支持")
        environment = request.form.get("environment", settings.runtime_environment).strip()
        if environment != settings.runtime_environment:
            raise ServiceError(422, "INVALID_INPUT", "任务环境必须与当前部署环境一致")
        project_name = request.form.get("project_name", "").strip()
        module_name = request.form.get("module_name", "").strip()
        task_title = request.form.get("title", "").strip()
        if not 1 <= len(project_name) <= 128 or not 1 <= len(module_name) <= 128:
            raise ServiceError(422, "INVALID_INPUT", "项目和模块名称长度必须为 1～128 字符")
        if task_title and len(task_title) > 128:
            raise ServiceError(422, "INVALID_INPUT", "任务标题长度不能超过 128 字符")
        additional_context = request.form.get("additional_context", "").strip()
        if len(additional_context) > 4_000:
            raise ServiceError(422, "INVALID_INPUT", "补充说明超过长度上限")

        manager.assert_capacity(int(normal.get("QUEUE_MAX_WAITING", 5)))
        task_id = new_task_id()
        task_dir = store.task_dir(task_id, create=True)
        try:
            document_upload = request.files.get("document_file")
            test_points_upload = request.files.get("test_points_file")
            has_document_upload = bool(document_upload and document_upload.filename)
            has_test_points_upload = bool(test_points_upload and test_points_upload.filename)
            if has_document_upload and has_test_points_upload:
                raise ServiceError(422, "INVALID_INPUT", "主文档和测试点 JSON 只能选择一种")
            if has_test_points_upload and operation != "generate_test_cases":
                raise ServiceError(422, "INVALID_INPUT", "测试点 JSON 仅用于直接生成功能测试用例")
            upload = test_points_upload if has_test_points_upload else document_upload
            document_text = request.form.get("document_text", "")
            if bool(upload and upload.filename) == bool(document_text.strip()):
                raise ServiceError(422, "INVALID_INPUT", "上传文件和粘贴文本必须二选一")
            max_bytes = int(normal.get("UPLOAD_MAX_BYTES", 5 * 1024 * 1024))
            max_characters = int(normal.get("UPLOAD_MAX_CHARACTERS", 500_000))
            is_test_points = has_test_points_upload
            if upload and upload.filename:
                allowed = {".json"} if is_test_points else FUNCTIONAL_EXTENSIONS
                data, text, extension = read_validated_text(
                    upload.stream, filename=upload.filename, mimetype=upload.mimetype,
                    allowed_extensions=frozenset(allowed), max_bytes=max_bytes, max_characters=max_characters,
                )
            else:
                text = document_text
                data = text.encode("utf-8")
                extension = ".md"
                if not text.strip() or len(text) > max_characters or len(data) > max_bytes:
                    raise ServiceError(422, "INVALID_INPUT", "粘贴文档为空或超过限制")
            if is_test_points:
                validate_review_json(text)
            input_name = "source.json" if is_test_points else f"source{extension}"
            input_path = task_dir / "input" / input_name
            atomic_write_bytes(input_path, data)
            form = {"operation": operation, "project_name": project_name, "module_name": module_name, "title": task_title}
            record = _new_record(task_id, settings, identity, form)
            record["artifacts_expire_at"] = (
                datetime.now(UTC) + timedelta(days=int(normal.get("TASK_ARTIFACT_RETENTION_DAYS", 90)))
            ).isoformat()
            record["config_release_id"] = snapshot.get("release_id")
            record["config_release_version"] = snapshot.get("release_version")
            request_payload = {
                "operation": operation,
                "project_id": record["project_id"], "module_id": record["module_id"],
                "project_name": project_name, "module_name": module_name,
                "feature_name": request.form.get("feature_name", "")[:128],
                "feature_slug": record["module_id"],
                "additional_info": {"context": additional_context},
                "input_relative_path": input_path.relative_to(task_dir).as_posix(),
                "input_sha256": sha256_bytes(data),
                "input_original_name": upload.filename if upload and upload.filename else "pasted.md",
                "input_kind": "test_points" if is_test_points else "document",
            }
            manager.submit(record, request_payload, max_waiting=int(normal.get("QUEUE_MAX_WAITING", 5)))
        except Exception:
            shutil.rmtree(task_dir, ignore_errors=True)
            raise
        emit_audit(
            client, action="agent.task.create", resource_type="agent_task", resource_id=task_id,
            outcome="success", actor_user_id=identity.user_id, actor_username=identity.username,
            metadata={"operation": operation, "environment": settings.runtime_environment},
        )
        record["workbench_v2_enabled"] = bool(normal.get("FUNCTIONAL_WORKBENCH_V2_ENABLED", False))
        record["workbench_v3_enabled"] = bool(normal.get("FUNCTIONAL_WORKBENCH_V3_ENABLED", False))
        return jsonify(public_task(record)), 202

    @app.get(f"{settings.base_path}/api/v1/tasks")
    def list_tasks():
        identity = current_identity()
        require_permission(identity, "tool.result.view")
        page = max(1, request.args.get("page", 1, type=int))
        page_size = min(100, max(1, request.args.get("page_size", 20, type=int)))
        status = request.args.get("status")
        operation = request.args.get("operation")
        query = request.args.get("q", "").strip().casefold()[:128]
        created_date = request.args.get("date", "").strip()
        allowed_statuses = {"pending", "running", "waiting_review", "waiting_case_review", "succeeded", "partial_success", "failed", "cancelled"}
        if status and status not in allowed_statuses:
            raise ServiceError(422, "INVALID_INPUT", "任务状态筛选值不受支持")
        if operation and operation not in operations:
            raise ServiceError(422, "INVALID_INPUT", "操作类型筛选值不受支持")
        visible = [item for item in store.list() if item.get("created_by_user_id") == identity.user_id or "task.view.all" in identity.permissions]
        if status:
            visible = [item for item in visible if item.get("status") == status]
        if operation:
            visible = [item for item in visible if item.get("operation") == operation]
        if query:
            visible = [item for item in visible if any(query in str(item.get(key, "")).casefold() for key in ("id", "title", "project_name", "module_name"))]
        if created_date:
            try:
                datetime.strptime(created_date, "%Y-%m-%d")
            except ValueError as exc:
                raise ServiceError(422, "INVALID_INPUT", "日期必须使用 YYYY-MM-DD") from exc
            visible = [item for item in visible if str(item.get("created_at", ""))[:10] == created_date]
        visible.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("id", ""))), reverse=True)
        _snapshot, normal = safe_limits()
        workbench_v2 = bool(normal.get("FUNCTIONAL_WORKBENCH_V2_ENABLED", False))
        workbench_v3 = bool(normal.get("FUNCTIONAL_WORKBENCH_V3_ENABLED", False))
        for item in visible:
            item["workbench_v2_enabled"] = workbench_v2
            item["workbench_v3_enabled"] = workbench_v3
        start = (page - 1) * page_size
        return jsonify({"items": safe_public_tasks(visible[start:start + page_size]), "total": len(visible), "page": page, "page_size": page_size})

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>")
    def task_detail(task_id: str):
        record, _identity = get_task(task_id)
        _snapshot, normal = safe_limits()
        record["workbench_v2_enabled"] = bool(normal.get("FUNCTIONAL_WORKBENCH_V2_ENABLED", False))
        record["workbench_v3_enabled"] = bool(normal.get("FUNCTIONAL_WORKBENCH_V3_ENABLED", False))
        payload = public_task(record)
        payload["artifacts"] = load_registry(store, task_id)
        payload["can_cancel"] = record.get("status") not in {"succeeded", "failed", "cancelled"}
        payload["can_resume"] = record.get("status") == "waiting_review"
        return jsonify(payload)

    @app.post(f"{settings.base_path}/api/v1/tasks/<task_id>/cancel")
    def cancel_task(task_id: str):
        record, identity = get_task(task_id, permission="task.cancel")
        require_csrf(request)
        cancelled = manager.cancel(record["id"])
        emit_audit(
            client, action="agent.task.cancel", resource_type="agent_task", resource_id=task_id,
            outcome="success", actor_user_id=identity.user_id, actor_username=identity.username,
        )
        return jsonify(public_task(cancelled)), 202 if cancelled.get("status") == "running" else 200

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>/review")
    def get_review(task_id: str):
        """返回在线 Review 数据；功能开关关闭时失败关闭。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, identity = get_task(task_id)
        _snapshot, normal = safe_limits()
        if not bool(normal.get("ONLINE_REVIEW_ENABLED", False)):
            raise ServiceError(403, "FEATURE_DISABLED", "在线 Review 尚未启用")
        if record.get("artifacts_expired"):
            raise ServiceError(410, "ARTIFACT_EXPIRED", "Review 文件已过期")
        kind = request.args.get("kind", "draft")
        version = request.args.get("version", type=int)
        payload = review_service.load_version(task_id, kind=kind, version=version)
        payload.update({"editable": record.get("status") == "waiting_review" and "tool.execute" in identity.permissions, "task_status": record.get("status"), "stage": record.get("stage"), "review_ai": record.get("review_ai", {}), "review_ai_enabled": bool(normal.get("REVIEW_AI_ENABLED", False))})
        if kind != "draft":
            payload["editable"] = False
        return jsonify(payload)

    @app.put(f"{settings.base_path}/api/v1/tasks/<task_id>/review-draft")
    def save_review_draft(task_id: str):
        """显式保存草稿；业务校验错误随响应返回但不阻止落盘。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, identity = get_task(task_id, permission="tool.execute")
        require_csrf(request)
        if record.get("status") != "waiting_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许保存草稿")
        _snapshot, normal = safe_limits()
        if not bool(normal.get("ONLINE_REVIEW_ENABLED", False)):
            raise ServiceError(403, "FEATURE_DISABLED", "在线 Review 尚未启用")
        body = request.get_json(silent=True) or {}
        points = body.get("rows", body.get("points"))
        if not isinstance(points, list):
            raise ServiceError(422, "REVIEW_FILE_INVALID", "points 必须是数组")
        result = review_service.save_draft(
            task_id, points, revision=int(body.get("revision", -1)),
            sha256=str(body.get("sha256", "")), user_id=identity.user_id,
            username=identity.username, max_bytes=int(normal.get("UPLOAD_MAX_BYTES", 5 * 1024 * 1024)),
            max_characters=int(normal.get("UPLOAD_MAX_CHARACTERS", 500_000)),
            mindmap=body.get("mindmap") if "mindmap" in body else None,
        )
        emit_audit(client, action="agent.review.draft.save", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=identity.user_id, actor_username=identity.username, metadata={"revision": result["revision"], "sha256": result["sha256"], "count": len(result["points"]), "errors": len(result["validation"]["errors"]), "warnings": len(result["validation"]["warnings"])})
        return jsonify(result)

    @app.post(f"{settings.base_path}/api/v1/tasks/<task_id>/review-draft/import")
    def import_review_draft(task_id: str):
        """把上传 JSON 保存为草稿，不自动确认或入队。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, identity = get_task(task_id, permission="tool.execute")
        require_csrf(request)
        if record.get("status") != "waiting_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许导入草稿")
        _snapshot, normal = safe_limits()
        upload = request.files.get("review_file")
        if not upload or not upload.filename:
            raise ServiceError(422, "REVIEW_FILE_INVALID", "请选择 Review JSON 文件")
        _data, text, _extension = read_validated_text(upload.stream, filename=upload.filename, mimetype=upload.mimetype, allowed_extensions=frozenset({".json"}), max_bytes=int(normal.get("UPLOAD_MAX_BYTES", 5 * 1024 * 1024)), max_characters=int(normal.get("UPLOAD_MAX_CHARACTERS", 500_000)))
        try:
            points = parse_points(json.loads(text))
        except json.JSONDecodeError:
            raise ServiceError(422, "REVIEW_FILE_INVALID", "Review JSON 语法不正确") from None
        current = review_service.load(task_id)
        revision = int(request.form.get("revision", current["revision"]))
        digest = request.form.get("sha256", current["sha256"])
        result = review_service.save_draft(task_id, points, revision=revision, sha256=digest, user_id=identity.user_id, username=identity.username, max_bytes=int(normal.get("UPLOAD_MAX_BYTES", 5 * 1024 * 1024)), max_characters=int(normal.get("UPLOAD_MAX_CHARACTERS", 500_000)))
        emit_audit(client, action="agent.review.draft.import", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=identity.user_id, actor_username=identity.username, metadata={"revision": result["revision"], "sha256": result["sha256"], "count": len(result["points"])})
        return jsonify(result)

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>/review/download")
    def download_review(task_id: str):
        """按逻辑类型下载 Review JSON，禁止浏览器提交路径。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, _identity = get_task(task_id)
        if record.get("artifacts_expired"):
            raise ServiceError(410, "ARTIFACT_EXPIRED", "Review 文件已过期")
        kind = request.args.get("kind", "draft")
        if kind == "generated":
            data = review_service.original_points(task_id)[0]
            name = "generated-test-points.json"
        elif kind == "draft":
            data = review_service.load(task_id)["points"]
            name = "review-draft.json"
        elif kind == "confirmed":
            version = request.args.get("version", type=int)
            metadata = record.get("review", {})
            if not version or metadata.get("version") != version:
                raise ServiceError(404, "ARTIFACT_NOT_READY", "确认版本不存在")
            path = (store.task_dir(task_id) / metadata["relative_path"]).resolve()
            if store.task_dir(task_id) not in path.parents or not path.is_file() or path.is_symlink():
                raise ServiceError(404, "ARTIFACT_NOT_READY", "确认版本不存在")
            data = json.loads(path.read_text(encoding="utf-8"))
            name = f"review-test-points-v{version}.json"
        else:
            raise ServiceError(422, "INVALID_INPUT", "下载类型不受支持")
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return send_file(io.BytesIO(payload), mimetype="application/json", as_attachment=True, download_name=name, max_age=0)

    @app.post(f"{settings.base_path}/api/v1/tasks/<task_id>/review-ai")
    def request_review_ai(task_id: str):
        """持久化 AI 请求并进入共享 FIFO；HTTP 不同步等待模型。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, identity = get_task(task_id, permission="tool.execute")
        require_csrf(request)
        if record.get("status") != "waiting_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许发起 AI 辅助")
        _snapshot, normal = safe_limits()
        if not bool(normal.get("ONLINE_REVIEW_ENABLED", False)) or not bool(normal.get("REVIEW_AI_ENABLED", False)):
            raise ServiceError(403, "FEATURE_DISABLED", "AI 辅助 Review 尚未启用")
        from services.functional_agent.review_ai import ReviewAIRequest, request_sha

        body = request.get_json(silent=True) or {}
        current = review_service.load(task_id)
        revision, digest = int(body.get("revision", -1)), str(body.get("sha256", ""))
        if current["revision"] == 0:
            raise ServiceError(422, "REVIEW_DRAFT_REQUIRED", "请先保存草稿再发起 AI 辅助")
        if revision != current["revision"] or digest != current["sha256"]:
            raise ServiceError(409, "REVIEW_AI_BASE_CHANGED", "AI 建议基准草稿已变化")
        operation = str(body.get("operation", ""))
        selected_ids = body.get("selected_ids", [])
        scope = body.get("scope", {})
        instruction = str(body.get("instruction", ""))
        if operation not in {"supplement", "rewrite_selected", "generate_from_instruction"}:
            raise ServiceError(422, "INVALID_INPUT", "AI 操作类型不受支持")
        if not isinstance(selected_ids, list) or not isinstance(scope, dict):
            raise ServiceError(422, "INVALID_INPUT", "AI 作用域格式不正确")
        if operation == "rewrite_selected" and not 1 <= len(selected_ids) <= int(normal.get("REVIEW_AI_MAX_SELECTED_POINTS", 100)):
            raise ServiceError(422, "INVALID_INPUT", "改写操作必须选择有效数量的测试点")
        if operation == "generate_from_instruction" and not instruction.strip():
            raise ServiceError(422, "INVALID_INPUT", "请填写测试设计说明")
        if len(instruction) > int(normal.get("REVIEW_AI_MAX_INSTRUCTION_CHARACTERS", 2000)):
            raise ServiceError(422, "INVALID_INPUT", "测试设计说明超过长度上限")
        idempotency = request.headers.get("Idempotency-Key", "")
        if idempotency and not 8 <= len(idempotency) <= 128:
            raise ServiceError(422, "INVALID_INPUT", "Idempotency-Key 长度必须为 8～128")
        ai_dir = store.task_dir(task_id) / "input" / "review-ai"
        ai_dir.mkdir(mode=0o700, exist_ok=True)
        idempotency_sha = sha256_bytes(idempotency.encode())
        comparable = {"operation": operation, "base_revision": revision, "base_sha256": digest, "selected_ids": selected_ids, "scope": scope, "instruction": instruction}
        if idempotency:
            for existing_path in sorted(ai_dir.glob("request-v*.json")):
                try:
                    existing = json.loads(existing_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if existing.get("idempotency_key_sha256") != idempotency_sha:
                    continue
                if any(existing.get(key) != value for key, value in comparable.items()):
                    raise ServiceError(409, "INVALID_INPUT", "同一 Idempotency-Key 不能用于不同 AI 请求")
                current_ai = record.get("review_ai", {})
                existing_version = existing.get("request_version")
                if current_ai.get("request_version") == existing_version:
                    status = 202 if record.get("status") in {"pending", "running"} else 200
                    return jsonify(public_task(record)), status
                if current_ai:
                    raise ServiceError(409, "INVALID_INPUT", "Idempotency-Key 已用于历史 AI 请求")
                # 上一次请求只发布了文件但未成功入队，清除未引用文件后允许安全重试。
                existing_path.unlink(missing_ok=True)
                break
        versions = [int(path.stem.removeprefix("request-v")) for path in ai_dir.glob("request-v*.json") if path.stem.removeprefix("request-v").isdigit()]
        request_version = max(versions, default=0) + 1
        payload = {"schema_version": 1, "request_version": request_version, "operation": operation, "base_revision": revision, "base_sha256": digest, "selected_ids": selected_ids, "scope": scope, "instruction": instruction, "requested_by_user_id": identity.user_id, "requested_at": utc_now(), "idempotency_key_sha256": idempotency_sha, "request_sha256": ""}
        payload["request_sha256"] = request_sha(payload)
        validated = ReviewAIRequest.model_validate(payload).model_dump()
        ReviewService._atomic_create(ai_dir / f"request-v{request_version}.json", json.dumps(validated, ensure_ascii=False, indent=2).encode())
        metadata = {"status": "queued", "operation": operation, "request_version": request_version, "base_revision": revision, "base_sha256": digest, "requested_at": payload["requested_at"]}
        request_path = ai_dir / f"request-v{request_version}.json"
        try:
            queued = manager.enqueue_review_ai(task_id, metadata, max_waiting=int(normal.get("QUEUE_MAX_WAITING", 5)))
        except ServiceError:
            # 请求未进入持久队列时不能保留会被误判为幂等成功的孤立请求文件。
            request_path.unlink(missing_ok=True)
            raise
        emit_audit(client, action="agent.review.ai.request", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=identity.user_id, actor_username=identity.username, metadata={"operation": operation, "request_version": request_version, "base_revision": revision, "base_sha256": digest, "selected_count": len(selected_ids), "instruction_sha256": sha256_bytes(instruction.encode())})
        return jsonify(public_task(queued)), 202

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>/review-ai")
    def get_review_ai(task_id: str):
        """返回当前 AI 状态及通过 SHA 校验的建议正文。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, _identity = get_task(task_id)
        metadata = dict(record.get("review_ai", {}))
        relative = metadata.pop("relative_path", None)
        if metadata.get("status") == "ready" and relative:
            path = (store.task_dir(task_id) / relative).resolve()
            if store.task_dir(task_id) not in path.parents or not path.is_file() or path.is_symlink() or sha256_bytes(path.read_bytes()) != record.get("review_ai", {}).get("suggestion_sha256"):
                raise ServiceError(422, "REVIEW_AI_RESPONSE_INVALID", "AI 建议文件损坏或不完整")
            envelope = json.loads(path.read_text(encoding="utf-8"))
            metadata.update({key: envelope.get(key) for key in ("summary", "suggestions", "rejected_suggestions", "warnings", "model_name", "prompt_bundle_sha256", "finished_at")})
        return jsonify(metadata)

    @app.post(f"{settings.base_path}/api/v1/tasks/<task_id>/review-ai/cancel")
    def cancel_review_ai(task_id: str):
        """取消 AI 子阶段，保留主任务和草稿。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        _record, identity = get_task(task_id, permission="task.cancel")
        require_csrf(request)
        cancelled = manager.cancel_review_ai(task_id)
        emit_audit(client, action="agent.review.ai.cancel", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=identity.user_id, actor_username=identity.username, metadata={"request_version": cancelled.get("review_ai", {}).get("request_version")})
        return jsonify(public_task(cancelled)), 202 if cancelled.get("status") == "running" else 200

    @app.post(f"{settings.base_path}/api/v1/tasks/<task_id>/resume")
    def resume_task(task_id: str):
        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, identity = get_task(task_id, permission="tool.execute")
        require_csrf(request)
        if record.get("status") != "waiting_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许继续")
        _snapshot, normal = safe_limits()
        if request.is_json:
            if not bool(normal.get("ONLINE_REVIEW_ENABLED", False)):
                raise ServiceError(403, "FEATURE_DISABLED", "在线 Review 尚未启用")
            body = request.get_json(silent=True) or {}
            metadata = review_service.confirm(
                task_id, revision=int(body.get("revision", -1)), sha256=str(body.get("sha256", "")),
                accept_warnings=bool(body.get("accept_warnings", False)),
                acknowledge_quality_risks=bool(body.get("acknowledge_quality_risks", False)),
                expected_validation_sha256=str(body.get("validation_sha256", "")),
            )
            record["review"] = metadata
            store.save(record)
            request_path = store.task_dir(task_id) / "request.json"
            payload = json.loads(request_path.read_text(encoding="utf-8"))
            payload["review_relative_path"] = metadata["relative_path"]
            TaskStore.atomic_write_json(request_path, payload)
            resumed = manager.resume(task_id, metadata, max_waiting=int(normal.get("QUEUE_MAX_WAITING", 5)))
            emit_audit(client, action="agent.review.resume", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=identity.user_id, actor_username=identity.username, metadata={"review_sha256": metadata["sha256"], "review_version": metadata["version"]})
            return jsonify(public_task(resumed)), 202
        upload = request.files.get("review_file")
        if not upload or not upload.filename:
            raise ServiceError(422, "REVIEW_FILE_INVALID", "请选择 Review JSON 文件")
        data, text, _extension = read_validated_text(
            upload.stream, filename=upload.filename, mimetype=upload.mimetype,
            allowed_extensions=frozenset({".json"}),
            max_bytes=int(normal.get("UPLOAD_MAX_BYTES", 5 * 1024 * 1024)),
            max_characters=int(normal.get("UPLOAD_MAX_CHARACTERS", 500_000)),
        )
        points = validate_review_json(text)
        digest = sha256_bytes(data)
        existing = record.get("review_draft", {})
        if existing.get("sha256") == digest:
            relative_path = existing["relative_path"]
            version = existing["version"]
        else:
            version = int(existing.get("version", 0)) + 1
            path = store.task_dir(task_id) / "input" / f"review-test-points-v{version}.json"
            atomic_write_bytes(path, data)
            relative_path = path.relative_to(store.task_dir(task_id)).as_posix()
        metadata = {
            "version": version, "relative_path": relative_path, "sha256": digest,
            "reviewed_by_user_id": identity.user_id, "reviewed_by_username": identity.username,
            "reviewed_at": utc_now(), "test_point_count": len(points),
        }
        record["review_draft"] = metadata
        store.save(record)
        request_path = store.task_dir(task_id) / "request.json"
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        payload["review_relative_path"] = relative_path
        TaskStore.atomic_write_json(request_path, payload)
        resumed = manager.resume(task_id, metadata, max_waiting=int(normal.get("QUEUE_MAX_WAITING", 5)))
        emit_audit(
            client, action="agent.task.resume", resource_type="agent_task", resource_id=task_id,
            outcome="success", actor_user_id=identity.user_id, actor_username=identity.username,
            metadata={"review_sha256": digest, "review_version": version},
        )
        return jsonify(public_task(resumed)), 202

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>/case-review")
    def get_case_review(task_id: str):
        """返回测试用例在线 Review 工作区和服务端权威校验。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, identity = get_task(task_id)
        _snapshot, normal = safe_limits()
        if not bool(normal.get("ONLINE_CASE_REVIEW_ENABLED", False)):
            raise ServiceError(403, "FEATURE_DISABLED", "在线测试用例 Review 尚未启用")
        if record.get("artifacts_expired"):
            raise ServiceError(410, "ARTIFACT_EXPIRED", "测试用例 Review 文件已过期")
        kind = request.args.get("kind", "draft")
        version = request.args.get("version", type=int)
        payload = case_review_service.load_version(task_id, kind=kind, version=version, **case_limits(normal))
        payload.update({
            "editable": record.get("status") in {"waiting_case_review", "succeeded"} and "tool.execute" in identity.permissions,
            "task_status": record.get("status"), "stage": record.get("stage"),
            "test_points": case_point_summaries(task_id), "case_review_ai": record.get("case_review_ai", {}),
            "case_review_ai_enabled": bool(normal.get("CASE_REVIEW_AI_ENABLED", False)),
        })
        if kind != "draft":
            payload["editable"] = False
        return jsonify(payload)

    @app.put(f"{settings.base_path}/api/v1/tasks/<task_id>/case-review-draft")
    def save_case_review_draft(task_id: str):
        """使用 CAS 显式保存完整用例草稿，允许业务校验错误落盘。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, identity = get_task(task_id, permission="tool.execute")
        require_csrf(request)
        if record.get("status") not in {"waiting_case_review", "succeeded"}:
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许保存用例草稿")
        _snapshot, normal = safe_limits()
        if not bool(normal.get("ONLINE_CASE_REVIEW_ENABLED", False)):
            raise ServiceError(403, "FEATURE_DISABLED", "在线测试用例 Review 尚未启用")
        body = request.get_json(silent=True) or {}
        cases = body.get("rows", body.get("cases"))
        if not isinstance(cases, list):
            raise ServiceError(422, "CASE_REVIEW_FILE_INVALID", "cases 必须是数组")
        result = case_review_service.save_draft(
            task_id, cases, revision=int(body.get("revision", -1)), sha256=str(body.get("sha256", "")),
            user_id=identity.user_id, username=identity.username,
            mindmap=body.get("mindmap") if "mindmap" in body else None, **case_limits(normal),
        )
        emit_audit(client, action="agent.case_review.draft.save", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=identity.user_id, actor_username=identity.username, metadata={"revision": result["revision"], "sha256": result["sha256"], "count": len(result["cases"]), "errors": len(result["validation"]["errors"]), "warnings": len(result["validation"]["warnings"])})
        return jsonify(result)

    @app.post(f"{settings.base_path}/api/v1/tasks/<task_id>/case-review-draft/import")
    def import_case_review_draft(task_id: str):
        """导入 5 MiB 以内 JSON 为用例草稿，不自动确认或发布。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, identity = get_task(task_id, permission="tool.execute")
        require_csrf(request)
        if record.get("status") not in {"waiting_case_review", "succeeded"}:
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许导入用例草稿")
        _snapshot, normal = safe_limits()
        if not bool(normal.get("ONLINE_CASE_REVIEW_ENABLED", False)):
            raise ServiceError(403, "FEATURE_DISABLED", "在线测试用例 Review 尚未启用")
        upload = request.files.get("review_file")
        if not upload or not upload.filename:
            raise ServiceError(422, "CASE_REVIEW_FILE_INVALID", "请选择测试用例 JSON 文件")
        _data, text, _extension = read_validated_text(
            upload.stream, filename=upload.filename, mimetype=upload.mimetype,
            allowed_extensions=frozenset({".json"}),
            max_bytes=int(normal.get("UPLOAD_MAX_BYTES", 5 * 1024 * 1024)),
            max_characters=int(normal.get("UPLOAD_MAX_CHARACTERS", 500_000)),
        )
        try:
            cases = parse_cases(json.loads(text))
        except json.JSONDecodeError:
            raise ServiceError(422, "CASE_REVIEW_FILE_INVALID", "测试用例 JSON 语法不正确") from None
        current = case_review_service.load(task_id, **case_limits(normal))
        result = case_review_service.save_draft(
            task_id, cases,
            revision=int(request.form.get("revision", current["revision"])),
            sha256=str(request.form.get("sha256", current["sha256"])),
            user_id=identity.user_id, username=identity.username, **case_limits(normal),
        )
        emit_audit(client, action="agent.case_review.draft.import", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=identity.user_id, actor_username=identity.username, metadata={"revision": result["revision"], "sha256": result["sha256"], "count": len(result["cases"])})
        return jsonify(result)

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>/case-review/download")
    def download_case_review(task_id: str):
        """按固定类型和版本下载用例 JSON，拒绝客户端磁盘路径。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, _identity = get_task(task_id)
        if record.get("artifacts_expired"):
            raise ServiceError(410, "ARTIFACT_EXPIRED", "测试用例 Review 文件已过期")
        _snapshot, normal = safe_limits()
        kind = request.args.get("kind", "draft")
        if kind == "generated":
            data = case_review_service.original_cases(task_id)[0]
            name = "generated-test-cases.json"
        elif kind == "draft":
            data = case_review_service.load(task_id, **case_limits(normal))["cases"]
            name = "case-review-draft.json"
        elif kind == "confirmed":
            version = request.args.get("version", type=int)
            if not version:
                raise ServiceError(404, "ARTIFACT_NOT_READY", "确认用例版本不存在")
            try:
                data = case_review_service.load_version(task_id, kind="confirmed", version=version, **case_limits(normal))["cases"]
            except ServiceError as exc:
                if exc.code in {"STORAGE_READ_FAILED", "REVIEW_VERSION_NOT_FOUND"}:
                    raise ServiceError(404, "ARTIFACT_NOT_READY", "确认用例版本不存在") from None
                raise
            name = f"review-test-cases-v{version}.json"
        else:
            raise ServiceError(422, "INVALID_INPUT", "下载类型不受支持")
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        emit_audit(client, action="agent.case_review.download", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=_identity.user_id, actor_username=_identity.username, metadata={"kind": kind, "version": request.args.get("version", type=int)})
        return send_file(io.BytesIO(payload), mimetype="application/json", as_attachment=True, download_name=name, max_age=0)

    @app.post(f"{settings.base_path}/api/v1/tasks/<task_id>/case-review/confirm")
    def confirm_case_review(task_id: str):
        """确认不可变用例版本并同步发布同源 JSON/XLSX。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, identity = get_task(task_id, permission="tool.execute")
        require_csrf(request)
        _snapshot, normal = safe_limits()
        if not bool(normal.get("ONLINE_CASE_REVIEW_ENABLED", False)):
            raise ServiceError(403, "FEATURE_DISABLED", "在线测试用例 Review 尚未启用")
        idempotency = request.headers.get("Idempotency-Key", "")
        if not 8 <= len(idempotency) <= 128:
            raise ServiceError(422, "INVALID_INPUT", "确认必须提供 8～128 字符的 Idempotency-Key")
        body = request.get_json(silent=True) or {}
        revision, digest = int(body.get("revision", -1)), str(body.get("sha256", ""))
        idempotency_sha = sha256_bytes(idempotency.encode())
        body_sha = sha256_bytes(json.dumps({"revision": revision, "sha256": digest}, sort_keys=True).encode())
        previous = (record.get("internal", {}).get("case_review_confirm_keys", {}) or {}).get(idempotency_sha)
        if previous and previous != body_sha:
            raise ServiceError(409, "INVALID_INPUT", "同一 Idempotency-Key 不能确认不同草稿")
        if record.get("status") == "succeeded" and previous == body_sha and (
            record.get("case_review", {}).get("draft_sha256") == digest
            or record.get("case_review", {}).get("sha256") == digest
        ):
            # HTTP 重试发生在终态提交之后时，返回同一确认版本和已登记产物。
            metadata = record["case_review"]
            return jsonify({"task": public_task(record), "case_review": {key: metadata[key] for key in ("version", "sha256", "confirmed_at", "test_case_count")}, "artifacts": [item for item in load_registry(store, task_id) if item.get("stage") == "case_review_published"]})
        if record.get("status") not in {"waiting_case_review", "succeeded"}:
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许确认用例")
        metadata = case_review_service.confirm(task_id, revision=revision, sha256=digest, accept_warnings=bool(body.get("accept_warnings", False)), **case_limits(normal))
        from services.functional_agent.case_review_publisher import publish_confirmed_cases

        artifacts = publish_confirmed_cases(store, task_id, metadata)
        with store.locked():
            latest = store.load(task_id) or record
            if latest.get("status") not in {"waiting_case_review", "succeeded"}:
                raise ServiceError(409, "INVALID_TASK_STATE", "任务状态已变化，未提交确认结果")
            latest["case_review"] = metadata
            latest.setdefault("internal", {}).setdefault("case_review_confirm_keys", {})[idempotency_sha] = body_sha
            latest.update({"status": "succeeded", "stage": "case_review_published", "finished_at": latest.get("finished_at") or utc_now(), "error_code": None, "error_message": None})
            latest.setdefault("result_summary", {}).update({"test_cases": metadata["test_case_count"], "artifact_count": len(load_registry(store, task_id))})
            store.save(latest)
        emit_audit(client, action="agent.case_review.confirm", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=identity.user_id, actor_username=identity.username, metadata={"version": metadata["version"], "sha256": metadata["sha256"], "count": metadata["test_case_count"]})
        return jsonify({"task": public_task(latest), "case_review": {key: metadata[key] for key in ("version", "sha256", "confirmed_at", "test_case_count")}, "artifacts": artifacts})

    @app.post(f"{settings.base_path}/api/v1/tasks/<task_id>/case-review-ai")
    def request_case_review_ai(task_id: str):
        """持久化用例 AI 请求并进入与正式任务共享的 FIFO。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, identity = get_task(task_id, permission="tool.execute")
        require_csrf(request)
        if record.get("status") != "waiting_case_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许发起用例 AI")
        _snapshot, normal = safe_limits()
        if not bool(normal.get("ONLINE_CASE_REVIEW_ENABLED", False)) or not bool(normal.get("CASE_REVIEW_AI_ENABLED", False)):
            raise ServiceError(403, "FEATURE_DISABLED", "测试用例 AI Review 尚未启用")
        from services.functional_agent.case_review_ai import CaseReviewAIRequest, case_request_sha

        body = request.get_json(silent=True) or {}
        current = case_review_service.load(task_id, **case_limits(normal))
        revision, digest = int(body.get("revision", -1)), str(body.get("sha256", ""))
        if current["revision"] == 0:
            raise ServiceError(422, "CASE_REVIEW_DRAFT_REQUIRED", "请先保存用例草稿再发起 AI")
        if revision != current["revision"] or digest != current["sha256"]:
            raise ServiceError(409, "CASE_REVIEW_AI_BASE_CHANGED", "用例 AI 建议基准草稿已变化")
        operation = str(body.get("operation", ""))
        selected_ids, scope, instruction = body.get("selected_ids", []), body.get("scope", {}), str(body.get("instruction", ""))
        if operation not in {"supplement", "rewrite_selected", "generate_from_instruction"} or not isinstance(selected_ids, list) or not isinstance(scope, dict):
            raise ServiceError(422, "INVALID_INPUT", "用例 AI 请求格式不正确")
        if operation == "rewrite_selected" and not 1 <= len(selected_ids) <= int(normal.get("CASE_REVIEW_AI_MAX_SELECTED_CASES", 50)):
            raise ServiceError(422, "INVALID_INPUT", "改写操作必须选择有效数量的测试用例")
        if operation == "generate_from_instruction" and not instruction.strip():
            raise ServiceError(422, "INVALID_INPUT", "请填写测试设计说明")
        if len(instruction) > int(normal.get("CASE_REVIEW_AI_MAX_INSTRUCTION_CHARACTERS", 2000)):
            raise ServiceError(422, "INVALID_INPUT", "测试设计说明超过长度上限")
        idempotency = request.headers.get("Idempotency-Key", "")
        if not 8 <= len(idempotency) <= 128:
            raise ServiceError(422, "INVALID_INPUT", "AI 请求必须提供 8～128 字符的 Idempotency-Key")
        ai_dir = store.task_dir(task_id) / "input" / "case-review-ai"
        ai_dir.mkdir(mode=0o700, exist_ok=True)
        idempotency_sha = sha256_bytes(idempotency.encode())
        comparable = {"operation": operation, "base_revision": revision, "base_sha256": digest, "selected_ids": selected_ids, "scope": scope, "instruction": instruction}
        for existing_path in sorted(ai_dir.glob("request-v*.json")):
            try:
                existing = json.loads(existing_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if existing.get("idempotency_key_sha256") != idempotency_sha:
                continue
            if any(existing.get(key) != value for key, value in comparable.items()):
                raise ServiceError(409, "INVALID_INPUT", "同一 Idempotency-Key 不能用于不同 AI 请求")
            if record.get("case_review_ai", {}).get("request_version") == existing.get("request_version"):
                return jsonify(public_task(record)), 202 if record.get("status") in {"pending", "running"} else 200
            existing_path.unlink(missing_ok=True)
            break
        versions = [int(path.stem.removeprefix("request-v")) for path in ai_dir.glob("request-v*.json") if path.stem.removeprefix("request-v").isdigit()]
        request_version = max(versions, default=0) + 1
        payload = {"schema_version": 1, "request_version": request_version, **comparable, "requested_by_user_id": identity.user_id, "requested_at": utc_now(), "idempotency_key_sha256": idempotency_sha, "request_sha256": ""}
        payload["request_sha256"] = case_request_sha(payload)
        validated = CaseReviewAIRequest.model_validate(payload).model_dump()
        request_path = ai_dir / f"request-v{request_version}.json"
        ReviewService._atomic_create(request_path, json.dumps(validated, ensure_ascii=False, indent=2).encode())
        metadata = {"status": "queued", "operation": operation, "request_version": request_version, "base_revision": revision, "base_sha256": digest, "requested_at": payload["requested_at"]}
        try:
            queued = manager.enqueue_case_review_ai(task_id, metadata, max_waiting=int(normal.get("QUEUE_MAX_WAITING", 5)))
        except ServiceError:
            request_path.unlink(missing_ok=True)
            raise
        emit_audit(client, action="agent.case_review.ai.request", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=identity.user_id, actor_username=identity.username, metadata={"operation": operation, "request_version": request_version, "base_revision": revision, "base_sha256": digest, "selected_count": len(selected_ids), "instruction_sha256": sha256_bytes(instruction.encode())})
        return jsonify(public_task(queued)), 202

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>/case-review-ai")
    def get_case_review_ai(task_id: str):
        """返回用例 AI 状态及通过 SHA 校验的结构化建议。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        record, _identity = get_task(task_id)
        metadata = dict(record.get("case_review_ai", {}))
        relative = metadata.pop("relative_path", None)
        if metadata.get("status") == "ready" and relative:
            path = (store.task_dir(task_id) / relative).resolve()
            if store.task_dir(task_id) not in path.parents or not path.is_file() or path.is_symlink() or sha256_bytes(path.read_bytes()) != record.get("case_review_ai", {}).get("suggestion_sha256"):
                raise ServiceError(422, "CASE_REVIEW_AI_RESPONSE_INVALID", "用例 AI 建议文件损坏或不完整")
            envelope = json.loads(path.read_text(encoding="utf-8"))
            metadata.update({key: envelope.get(key) for key in ("summary", "suggestions", "rejected_suggestions", "warnings", "model_name", "prompt_bundle_sha256", "finished_at")})
        return jsonify(metadata)

    @app.post(f"{settings.base_path}/api/v1/tasks/<task_id>/case-review-ai/cancel")
    def cancel_case_review_ai(task_id: str):
        """取消用例 AI 子阶段，保留用例草稿和原始产物。"""

        if settings.agent_type != "functional":
            raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")
        _record, identity = get_task(task_id, permission="task.cancel")
        require_csrf(request)
        cancelled = manager.cancel_case_review_ai(task_id)
        emit_audit(client, action="agent.case_review.ai.cancel", resource_type="agent_task", resource_id=task_id, outcome="success", actor_user_id=identity.user_id, actor_username=identity.username, metadata={"request_version": cancelled.get("case_review_ai", {}).get("request_version")})
        return jsonify(public_task(cancelled)), 202 if cancelled.get("status") == "running" else 200

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>/logs")
    def task_logs(task_id: str):
        record, _identity = get_task(task_id)
        if record.get("artifacts_expired"):
            raise ServiceError(410, "ARTIFACT_EXPIRED", "任务日志已过期")
        cursor = max(0, request.args.get("cursor", 0, type=int))
        limit = min(256 * 1024, max(1, request.args.get("limit", 65_536, type=int)))
        path = store.task_dir(task_id) / "console.log"
        if not path.exists():
            return jsonify({"content": "", "next_cursor": cursor, "truncated": False, "complete": record.get("status") in {"succeeded", "failed", "cancelled", "waiting_review"}})
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(min(cursor, size))
            data = handle.read(limit)
            next_cursor = handle.tell()
        content = redact_text(data.decode("utf-8", errors="replace"))
        return jsonify({"content": content, "next_cursor": next_cursor, "truncated": next_cursor < size, "complete": record.get("status") in {"succeeded", "failed", "cancelled", "waiting_review"}})

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>/artifacts")
    def artifacts(task_id: str):
        record, _identity = get_task(task_id)
        if record.get("artifacts_expired"):
            raise ServiceError(410, "ARTIFACT_EXPIRED", "任务产物已过期")
        return jsonify({"items": load_registry(store, task_id)})

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>/artifacts/<artifact_id>")
    def download_artifact(task_id: str, artifact_id: str):
        record, identity = get_task(task_id)
        if record.get("artifacts_expired"):
            raise ServiceError(410, "ARTIFACT_EXPIRED", "任务产物已过期")
        try:
            path, item = resolve_artifact(store, task_id, artifact_id)
        except (FileNotFoundError, ValueError):
            raise ServiceError(404, "ARTIFACT_NOT_READY", "产物不存在") from None
        emit_audit(
            client, action="agent.artifact.download", resource_type="agent_artifact", resource_id=artifact_id,
            outcome="success", actor_user_id=identity.user_id, actor_username=identity.username,
            metadata={"task_id": task_id, "artifact_type": item.get("type")},
        )
        return send_file(path, as_attachment=True, download_name=item["name"], max_age=0)

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>/artifacts/<artifact_id>/preview")
    def artifact_preview(task_id: str, artifact_id: str):
        """按登记 ID 预览白名单文本或 XLSX 内容，绝不接受客户端路径。"""

        record, identity = get_task(task_id)
        if record.get("artifacts_expired"):
            raise ServiceError(410, "ARTIFACT_EXPIRED", "任务产物已过期")
        try:
            path, item = resolve_artifact(store, task_id, artifact_id)
            payload = preview_artifact(path)
        except FileNotFoundError:
            raise ServiceError(404, "ARTIFACT_NOT_READY", "产物不存在") from None
        except ValueError as exc:
            raise ServiceError(415, "ARTIFACT_PREVIEW_UNSUPPORTED", str(exc)) from None
        emit_audit(
            client, action="agent.artifact.preview", resource_type="agent_artifact", resource_id=artifact_id,
            outcome="success", actor_user_id=identity.user_id, actor_username=identity.username,
            metadata={"task_id": task_id, "artifact_type": item.get("type")},
        )
        return jsonify({"name": item["name"], **payload})

    return app
