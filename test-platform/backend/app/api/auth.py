from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, current_auth_context, require_csrf
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.core.security import hash_password, new_id, normalize_username, secure_equals, verify_password
from app.db.session import get_db
from app.models.identity import PlatformSession, RoleGrant, User, UserRole
from app.models.tool import Tool
from app.schemas.auth import ChangePasswordRequest, LoginRequest, MeResponse, MessageResponse, SessionResponse, SetupRequest, UserSummary
from app.services.audit import add_audit_event
from app.services.auth import (
    authenticate,
    clear_login_failures,
    create_session,
    is_login_blocked,
    record_login_failure,
    revoke_user_sessions,
    utc_now,
)
from app.services.authorization import user_grants


router = APIRouter(tags=["auth"])


def _client_ip(request: Request) -> str:
    """读取经过网关传递的客户端地址，缺失时使用连接地址。"""

    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "")


def _set_auth_cookies(response: Response, settings: Settings, session_token: str, csrf_token: str) -> None:
    """使用统一安全属性写入 Session 与 CSRF Cookie。"""

    max_age = settings.session_absolute_hours * 3600
    response.set_cookie(
        "tp_session", session_token, max_age=max_age, httponly=True,
        secure=settings.cookie_secure, samesite="lax", path="/",
    )
    response.set_cookie(
        "tp_csrf", csrf_token, max_age=max_age, httponly=False,
        secure=settings.cookie_secure, samesite="lax", path="/",
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    """删除两枚平台认证 Cookie。"""

    response.delete_cookie("tp_session", path="/", secure=settings.cookie_secure, samesite="lax")
    response.delete_cookie("tp_csrf", path="/", secure=settings.cookie_secure, samesite="lax")


def _me_response(database: Session, context: AuthContext) -> MeResponse:
    """构造当前用户角色、平台权限和按工具展开的有效权限。"""

    grants = user_grants(database, context.user.id)
    roles = list(database.scalars(select(UserRole.role_id).where(UserRole.user_id == context.user.id)).all())
    platform_permissions = sorted({grant.permission_code for grant in grants if grant.resource_type == "platform"})
    tools = list(database.scalars(select(Tool).where(Tool.is_enabled.is_(True))).all())
    tool_map: dict[str, list[str]] = {}
    for tool in tools:
        permissions = sorted({
            grant.permission_code
            for grant in grants
            if grant.resource_type == "tool" and grant.resource_id in {tool.id, "*"}
        })
        if permissions:
            tool_map[tool.id] = permissions
    return MeResponse(
        user=UserSummary(
            id=context.user.id,
            username=context.user.username,
            display_name=context.user.display_name,
            status=context.user.status,
            must_change_password=context.user.must_change_password,
        ),
        roles=sorted(roles),
        platform_permissions=platform_permissions,
        tool_permissions=tool_map,
        session_expires_at=context.session.absolute_expires_at,
    )


@router.post("/setup", response_model=MeResponse)
def setup(
    payload: SetupRequest,
    response: Response,
    request: Request,
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeResponse:
    """使用一次性引导 Token 创建首个平台管理员和登录会话。"""

    if database.scalar(select(func.count()).select_from(User)):
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    expected = settings.read_bootstrap_token()
    if not expected or not secure_equals(expected, payload.bootstrap_token):
        raise PlatformError(403, "BOOTSTRAP_DENIED", "初始化凭据无效")
    if database.scalar(select(User).where(User.username_normalized == normalize_username(payload.username))):
        raise PlatformError(409, "USERNAME_EXISTS", "用户名已存在")
    user = User(
        id=new_id("usr"),
        username=payload.username.strip(),
        username_normalized=normalize_username(payload.username),
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        status="active",
    )
    database.add(user)
    database.flush()
    database.add(UserRole(user_id=user.id, role_id="role_platform_admin", created_by="system/bootstrap"))
    session, session_token, csrf_token = create_session(
        database, user, settings, _client_ip(request), request.headers.get("user-agent", "")
    )
    add_audit_event(
        database, action="platform.setup", resource_type="user", resource_id=user.id,
        outcome="success", request=request, actor_type="system", actor_id="system/bootstrap",
        after={"username": user.username, "role": "role_platform_admin"},
    )
    database.commit()
    _set_auth_cookies(response, settings, session_token, csrf_token)
    return _me_response(database, AuthContext(session, user))


@router.post("/auth/login", response_model=MeResponse)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeResponse:
    """验证用户名密码、执行持久限速并创建统一会话。"""

    ip_address = _client_ip(request)
    if is_login_blocked(database, payload.username, ip_address):
        add_audit_event(
            database, action="auth.login", resource_type="session", outcome="denied",
            request=request, actor_type="anonymous", error_code="ACCOUNT_LOCKED",
            metadata={"username": normalize_username(payload.username)},
        )
        database.commit()
        raise PlatformError(423, "ACCOUNT_LOCKED", "登录尝试过多，请稍后再试")
    user = authenticate(database, payload.username, payload.password)
    if user is None:
        record_login_failure(database, payload.username, ip_address, settings)
        add_audit_event(
            database, action="auth.login", resource_type="session", outcome="failed",
            request=request, actor_type="anonymous", error_code="INVALID_CREDENTIALS",
            metadata={"username": normalize_username(payload.username)},
        )
        database.commit()
        raise PlatformError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
    clear_login_failures(database, user.username, ip_address)
    session, session_token, csrf_token = create_session(
        database, user, settings, ip_address, request.headers.get("user-agent", "")
    )
    user.last_login_at = utc_now()
    add_audit_event(
        database, action="auth.login", resource_type="session", resource_id=session.id,
        outcome="success", request=request, actor=user,
    )
    database.commit()
    _set_auth_cookies(response, settings, session_token, csrf_token)
    return _me_response(database, AuthContext(session, user))


@router.get("/auth/me", response_model=MeResponse)
def me(
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> MeResponse:
    """返回当前用户和有效权限，不返回任何认证 Token。"""

    database.commit()
    return _me_response(database, context)


@router.post("/auth/logout", response_model=MessageResponse)
def logout(
    response: Response,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MessageResponse:
    """撤销当前会话并清理浏览器 Cookie。"""

    context.session.revoked_at = utc_now()
    add_audit_event(
        database, action="auth.logout", resource_type="session", resource_id=context.session.id,
        outcome="success", request=request, actor=context.user,
    )
    database.commit()
    _clear_auth_cookies(response, settings)
    return MessageResponse(message="已退出登录")


@router.post("/auth/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    """校验当前密码、更新哈希并撤销其他全部会话。"""

    if not verify_password(context.user.password_hash, payload.current_password):
        raise PlatformError(400, "CURRENT_PASSWORD_INVALID", "当前密码不正确")
    context.user.password_hash = hash_password(payload.new_password)
    context.user.must_change_password = False
    revoke_user_sessions(database, context.user.id)
    context.session.revoked_at = None
    add_audit_event(
        database, action="auth.password.change", resource_type="user", resource_id=context.user.id,
        outcome="success", request=request, actor=context.user,
    )
    database.commit()
    return MessageResponse(message="密码已更新")


@router.get("/auth/sessions", response_model=list[SessionResponse])
def list_sessions(
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> list[SessionResponse]:
    """列出当前用户未撤销且未超过绝对有效期的会话。"""

    now = datetime.now(UTC)
    rows = list(database.scalars(select(PlatformSession).where(
        PlatformSession.user_id == context.user.id,
        PlatformSession.revoked_at.is_(None),
        PlatformSession.absolute_expires_at > now,
    ).order_by(PlatformSession.created_at.desc())).all())
    return [SessionResponse(
        id=row.id, created_at=row.created_at, last_seen_at=row.last_seen_at,
        absolute_expires_at=row.absolute_expires_at, ip_address=row.ip_address,
        current=row.id == context.session.id,
    ) for row in rows]


@router.delete("/auth/sessions/{session_id}", response_model=MessageResponse)
def revoke_session(
    session_id: str,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    """撤销当前用户指定会话，禁止撤销他人的会话。"""

    row = database.get(PlatformSession, session_id)
    if row is None or row.user_id != context.user.id:
        raise PlatformError(404, "NOT_FOUND", "会话不存在")
    row.revoked_at = utc_now()
    add_audit_event(
        database, action="auth.session.revoke", resource_type="session", resource_id=row.id,
        outcome="success", request=request, actor=context.user,
    )
    database.commit()
    return MessageResponse(message="会话已撤销")
