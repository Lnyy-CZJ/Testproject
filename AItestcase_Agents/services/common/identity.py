"""可信平台身份、权限、所有权和 CSRF 校验。"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from urllib.parse import unquote

from flask import Request

from services.common.errors import ServiceError


@dataclass(frozen=True, slots=True)
class Identity:
    """由 Nginx 鉴权响应注入的用户身份。"""

    user_id: str
    username: str
    display_name: str
    permissions: frozenset[str]


def identity_from_request(request: Request) -> Identity:
    """解析可信身份；业务请求缺少用户 ID 时失败关闭。"""

    user_id = request.headers.get("X-Platform-User-ID", "").strip()
    if not user_id:
        raise ServiceError(401, "AUTH_REQUIRED", "请先登录")
    return Identity(
        user_id=user_id,
        username=unquote(request.headers.get("X-Platform-Username", "")),
        display_name=unquote(request.headers.get("X-Platform-Display-Name", "")),
        permissions=frozenset(filter(None, (item.strip() for item in request.headers.get("X-Platform-Permissions", "").split(",")))),
    )


def require_permission(identity: Identity, permission: str) -> None:
    """校验工具服务的第二层权限。"""

    if permission not in identity.permissions:
        raise ServiceError(403, "PERMISSION_DENIED", "无权执行此操作")


def require_task_access(identity: Identity, record: dict, *, permission: str = "tool.result.view") -> None:
    """同时校验查看权限和任务所有权。"""

    require_permission(identity, permission)
    if record.get("created_by_user_id") != identity.user_id and "task.view.all" not in identity.permissions:
        raise ServiceError(404, "TASK_NOT_FOUND", "任务不存在")


def require_csrf(request: Request) -> None:
    """对写请求执行 Cookie/Header 或 Cookie/表单双提交校验。"""

    cookie = request.cookies.get("tp_csrf", "")
    submitted = request.headers.get("X-CSRF-Token", "") or request.form.get("_csrf", "")
    if not cookie or not submitted or not hmac.compare_digest(cookie, submitted):
        raise ServiceError(403, "CSRF_INVALID", "CSRF 校验失败，请刷新页面后重试")

