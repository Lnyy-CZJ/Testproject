from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Callable

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.core.security import token_hash
from app.db.session import get_db
from app.models.identity import PlatformSession, ToolClient, User
from app.services.auth import resolve_session
from app.services.authorization import has_platform_permission, has_tool_permission


@dataclass(frozen=True)
class AuthContext:
    """封装当前已认证用户和服务端会话。"""

    session: PlatformSession
    user: User


@dataclass(frozen=True)
class ToolClientContext:
    """封装已认证工具 Client 及其固定工具/环境范围。"""

    client: ToolClient


def current_auth_context(
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    tp_session: Annotated[str | None, Cookie()] = None,
) -> AuthContext:
    """从 HttpOnly Cookie 解析有效会话，失败统一返回 401。"""

    resolved = resolve_session(database, tp_session or "", settings)
    if resolved is None:
        raise PlatformError(401, "AUTH_REQUIRED", "请先登录")
    session, user = resolved
    return AuthContext(session=session, user=user)


def require_csrf(
    context: Annotated[AuthContext, Depends(current_auth_context)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    tp_csrf: Annotated[str | None, Cookie()] = None,
) -> AuthContext:
    """验证双提交 CSRF Token 与服务端哈希。"""

    if not csrf_header or not tp_csrf or csrf_header != tp_csrf:
        raise PlatformError(403, "CSRF_INVALID", "请求安全校验失败")
    if token_hash(csrf_header) != context.session.csrf_hash:
        raise PlatformError(403, "CSRF_INVALID", "请求安全校验失败")
    return context


def require_platform(code: str, *, csrf: bool = False) -> Callable:
    """构造平台权限依赖，可选同时要求 CSRF。"""

    dependency = require_csrf if csrf else current_auth_context

    def checker(
        context: AuthContext = Depends(dependency),
        database: Session = Depends(get_db),
    ) -> AuthContext:
        """校验当前用户的平台权限。"""

        if not has_platform_permission(database, context.user.id, code):
            raise PlatformError(403, "PERMISSION_DENIED", "无权执行此操作")
        return context

    return checker


def require_tool(code: str, tool_id: str) -> Callable:
    """构造指定工具权限依赖。"""

    def checker(
        context: AuthContext = Depends(current_auth_context),
        database: Session = Depends(get_db),
    ) -> AuthContext:
        """校验当前用户在指定工具上的权限。"""

        if not has_tool_permission(database, context.user.id, code, tool_id):
            raise PlatformError(403, "PERMISSION_DENIED", "无权访问该工具")
        return context

    return checker


def current_tool_client(
    database: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> ToolClientContext:
    """使用 Bearer Token 哈希解析工具工作负载身份。"""

    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise PlatformError(401, "TOOL_CLIENT_UNAUTHORIZED", "工具身份无效")
    digest = token_hash(authorization[len(prefix):].strip())
    client = database.scalar(
        select(ToolClient).where(
            ToolClient.token_hash == digest,
            ToolClient.status == "active",
        )
    )
    if client is None:
        raise PlatformError(401, "TOOL_CLIENT_UNAUTHORIZED", "工具身份无效")
    return ToolClientContext(client=client)
