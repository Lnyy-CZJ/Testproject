"""可信平台身份、权限、所有权和 CSRF 校验。"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from urllib.parse import unquote

from flask import Request

from services.common.errors import ServiceError


@dataclass(frozen=True, slots=True)
class Identity:
    """平台确认的身份和业务资源数据范围，不能由浏览器 Header 扩权。"""

    user_id: str
    username: str
    display_name: str
    permissions: frozenset[str]
    data_scope: str
    managed_project_ids: frozenset[str]
    access_scope_snapshot: str | None = None
    project_id_snapshot: str | None = None
    authorization_source_snapshot: str | None = None


def identity_from_request(request: Request, platform_client, *, action: str, root_resource_id: str | None = None) -> Identity:
    """把 opaque 资源上下文交回平台，换取不可伪造的数据范围。"""

    resource_context = request.headers.get("X-Platform-Resource-Context", "").strip()
    if not resource_context:
        raise ServiceError(401, "RESOURCE_CONTEXT_REQUIRED", "当前请求缺少可信资源上下文")
    decision = platform_client.resource_access_check(resource_context, action=action, root_resource_id=root_resource_id)
    user_id = str(decision.get("user_id") or "").strip()
    data_scope = str(decision.get("data_scope") or "").strip()
    managed_project_ids = decision.get("managed_project_ids") or []
    returned_action = decision.get("action")
    # 授权响应采用严格的 fail-closed 契约：allowed/action 任一缺失都不能
    # 被当成成功，避免平台异常响应意外扩大为 global 数据范围。
    if (
        decision.get("allowed") is not True
        or decision.get("tool_id") != getattr(platform_client, "tool_id", None)
        or decision.get("environment") != getattr(platform_client, "environment", None)
        or not user_id
        or data_scope not in {"own", "project", "global"}
        or not isinstance(managed_project_ids, list)
        or returned_action != action
    ):
        raise ServiceError(403, "RESOURCE_CONTEXT_INVALID", "可信资源上下文无效")
    return Identity(
        user_id=user_id,
        username=str(decision.get("username") or unquote(request.headers.get("X-Platform-Username", ""))),
        display_name=str(decision.get("display_name") or unquote(request.headers.get("X-Platform-Display-Name", ""))),
        permissions=frozenset(filter(None, (item.strip() for item in request.headers.get("X-Platform-Permissions", "").split(",")))),
        data_scope=data_scope,
        managed_project_ids=frozenset(str(item) for item in managed_project_ids if isinstance(item, str) and item),
        access_scope_snapshot=str(decision.get("access_scope_snapshot") or "") or None,
        project_id_snapshot=str(decision.get("project_id_snapshot") or decision.get("project_id_for_new_resource") or "") or None,
        authorization_source_snapshot=str(decision.get("authorization_source_snapshot") or "") or None,
    )


def require_permission(identity: Identity, permission: str) -> None:
    """校验工具服务的第二层权限。"""

    if permission not in identity.permissions:
        raise ServiceError(403, "PERMISSION_DENIED", "无权执行此操作")


def require_task_access(identity: Identity, record: dict, *, permission: str = "tool.result.view") -> None:
    """只校验动作权限；对象范围由 TaskStore 统一以平台 scope 过滤。"""

    require_permission(identity, permission)


def require_csrf(request: Request) -> None:
    """对写请求执行 Cookie/Header 或 Cookie/表单双提交校验。"""

    cookie = request.cookies.get("tp_csrf", "")
    submitted = request.headers.get("X-CSRF-Token", "") or request.form.get("_csrf", "")
    if not cookie or not submitted or not hmac.compare_digest(cookie, submitted):
        raise ServiceError(403, "CSRF_INVALID", "CSRF 校验失败，请刷新页面后重试")
