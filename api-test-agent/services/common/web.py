"""API 测试智能体的 Flask HTTP 与页面协议。"""

from __future__ import annotations

import json
import re
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from flask import Flask, Response, g, jsonify, render_template, request, send_file
from jinja2 import ChoiceLoader, FileSystemLoader
from pydantic import ValidationError

from services.common.artifacts import load_registry, resolve_artifact
from services.common.audit import emit_audit
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
from services.common.task_manager import TaskManager
from services.common.task_models import public_task, utc_now
from services.common.task_store import TaskStore, new_task_id
from services.common.uploads import (
    API_EXTENSIONS,
    atomic_write_bytes,
    read_validated_text,
    sha256_bytes,
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

    def safe_slug(value: str, fallback: str) -> str:
        """把展示名称转换为不会形成目录越界的稳定 slug。"""

        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
        return slug[:64] or fallback

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
    """创建带任务、权限、上传、日志和产物协议的 API 智能体应用。"""

    if settings.agent_type != "api":
        raise RuntimeError("API 项目只允许启动 api 服务")

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
    app.extensions["task_store"] = store
    app.extensions["task_manager"] = manager
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
                "api_execution_enabled": False,
                "database_persist_enabled": bool(normal.get("DATABASE_PERSIST_ENABLED", False)),
            })
        except ServiceError:
            return jsonify({"status": "not_ready", "storage_writable": storage_writable, "configuration_available": False}), 503

    @app.get(f"{settings.base_path}/")
    def index():
        identity = current_identity()
        require_permission(identity, "tool.view")
        _snapshot, normal = safe_limits()
        source_records = [item for item in store.list() if item.get("created_by_user_id") == identity.user_id or "task.view.all" in identity.permissions]
        records = safe_public_tasks(source_records)
        return render_template(
            "index.html", title=title, description=description, settings=settings,
            tasks=records[:20], agent_type=settings.agent_type,
            csrf_token=request.cookies.get("tp_csrf", ""), platform_home_url=settings.platform_home_url,
        )

    @app.get(f"{settings.base_path}/tasks/<task_id>")
    def task_page(task_id: str):
        record, identity = get_task(task_id)
        _snapshot, normal = safe_limits()
        return render_template(
            "task_detail.html", title=title, settings=settings, task=public_task(record),
            artifacts=load_registry(store, task_id), csrf_token=request.cookies.get("tp_csrf", ""),
            platform_home_url=settings.platform_home_url,
            can_edit_review="tool.execute" in identity.permissions,
        )

    @app.post(f"{settings.base_path}/api/v1/tasks")
    def create_task():
        identity = current_identity()
        require_permission(identity, "tool.execute")
        require_csrf(request)
        snapshot, normal = safe_limits()
        operation = request.form.get("operation", "").strip()
        if operation in {"execute_api_cases", "full_pipeline"} and settings.agent_type == "api":
            raise ServiceError(403, "FEATURE_DISABLED", "API 真实执行在 MVP 中未启用")
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
            if has_test_points_upload:
                raise ServiceError(422, "INVALID_INPUT", "API 任务不接受功能测试点 JSON")
            upload = test_points_upload if has_test_points_upload else document_upload
            document_text = request.form.get("document_text", "")
            if bool(upload and upload.filename) == bool(document_text.strip()):
                raise ServiceError(422, "INVALID_INPUT", "上传文件和粘贴文本必须二选一")
            max_bytes = int(normal.get("UPLOAD_MAX_BYTES", 5 * 1024 * 1024))
            max_characters = int(normal.get("UPLOAD_MAX_CHARACTERS", 500_000))
            is_test_points = has_test_points_upload
            if upload and upload.filename:
                allowed = API_EXTENSIONS
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
        allowed_statuses = {"pending", "running", "waiting_review", "waiting_contract_review", "waiting_case_review", "waiting_execution_confirmation", "succeeded", "failed", "cancelled", "partial_success"}
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
        start = (page - 1) * page_size
        return jsonify({"items": safe_public_tasks(visible[start:start + page_size]), "total": len(visible), "page": page, "page_size": page_size})

    @app.get(f"{settings.base_path}/api/v1/tasks/<task_id>")
    def task_detail(task_id: str):
        record, _identity = get_task(task_id)
        payload = public_task(record)
        payload["artifacts"] = load_registry(store, task_id)
        payload["can_cancel"] = record.get("status") not in {"succeeded", "failed", "cancelled"}
        payload["can_resume"] = False
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

    return app
