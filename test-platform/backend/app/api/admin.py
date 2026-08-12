from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_platform
from app.core.errors import PlatformError
from app.core.security import hash_password, new_id, normalize_username
from app.db.session import get_db
from app.models.identity import Permission, Role, RoleGrant, User, UserRole
from app.models.tool import Tool
from app.schemas.admin import (
    ResetPasswordRequest,
    RoleCreateRequest,
    RoleGrantRequest,
    RoleResponse,
    RoleUpdateRequest,
    UserAdminResponse,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.schemas.auth import MessageResponse
from app.services.audit import add_audit_event
from app.services.auth import revoke_user_sessions


router = APIRouter(prefix="/admin", tags=["admin"])


def _role_ids(database: Session, user_id: str) -> list[str]:
    """读取用户角色 ID 并稳定排序。"""

    return sorted(database.scalars(select(UserRole.role_id).where(UserRole.user_id == user_id)).all())


def _user_response(database: Session, user: User) -> UserAdminResponse:
    """将用户模型转换为不含密码哈希的管理响应。"""

    return UserAdminResponse(
        id=user.id, username=user.username, display_name=user.display_name,
        status=user.status, must_change_password=user.must_change_password,
        role_ids=_role_ids(database, user.id), last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _validate_roles(database: Session, role_ids: list[str]) -> None:
    """确保请求中的全部角色存在。"""

    existing = set(database.scalars(select(Role.id).where(Role.id.in_(role_ids))).all()) if role_ids else set()
    if existing != set(role_ids):
        raise PlatformError(422, "VALIDATION_ERROR", "包含不存在的角色")


def _replace_user_roles(database: Session, user: User, role_ids: list[str], actor_id: str) -> None:
    """原子替换用户角色并递增权限版本。"""

    _validate_roles(database, role_ids)
    database.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for role_id in sorted(set(role_ids)):
        database.add(UserRole(user_id=user.id, role_id=role_id, created_by=actor_id))
    user.permission_version += 1


@router.get("/users", response_model=list[UserAdminResponse])
def list_users(
    _: Annotated[AuthContext, Depends(require_platform("platform.user.manage"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[UserAdminResponse]:
    """按用户名返回平台用户列表。"""

    rows = list(database.scalars(select(User).order_by(User.username_normalized)).all())
    return [_user_response(database, user) for user in rows]


@router.post("/users", response_model=UserAdminResponse, status_code=201)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.user.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> UserAdminResponse:
    """创建本地用户、分配角色并写入同事务审计。"""

    normalized = normalize_username(payload.username)
    if database.scalar(select(User).where(User.username_normalized == normalized)):
        raise PlatformError(409, "USERNAME_EXISTS", "用户名已存在")
    _validate_roles(database, payload.role_ids)
    user = User(
        id=new_id("usr"), username=payload.username.strip(), username_normalized=normalized,
        display_name=payload.display_name.strip(), password_hash=hash_password(payload.password),
        status="active", must_change_password=payload.must_change_password,
    )
    database.add(user)
    database.flush()
    _replace_user_roles(database, user, payload.role_ids, context.user.id)
    add_audit_event(
        database, action="user.create", resource_type="user", resource_id=user.id,
        outcome="success", request=request, actor=context.user,
        after={"username": user.username, "display_name": user.display_name, "role_ids": payload.role_ids},
    )
    database.commit()
    database.refresh(user)
    return _user_response(database, user)


@router.get("/users/{user_id}", response_model=UserAdminResponse)
def get_user(
    user_id: str,
    _: Annotated[AuthContext, Depends(require_platform("platform.user.manage"))],
    database: Annotated[Session, Depends(get_db)],
) -> UserAdminResponse:
    """获取单个用户管理详情。"""

    user = database.get(User, user_id)
    if user is None:
        raise PlatformError(404, "NOT_FOUND", "用户不存在")
    return _user_response(database, user)


@router.patch("/users/{user_id}", response_model=UserAdminResponse)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.user.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> UserAdminResponse:
    """修改用户显示信息、状态和角色，并在禁用时撤销会话。"""

    user = database.get(User, user_id)
    if user is None:
        raise PlatformError(404, "NOT_FOUND", "用户不存在")
    before = {"display_name": user.display_name, "status": user.status, "role_ids": _role_ids(database, user.id)}
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.status is not None:
        if user.id == context.user.id and payload.status == "disabled":
            raise PlatformError(422, "VALIDATION_ERROR", "不能禁用当前登录用户")
        user.status = payload.status
        if payload.status == "disabled":
            revoke_user_sessions(database, user.id)
    if payload.role_ids is not None:
        _replace_user_roles(database, user, payload.role_ids, context.user.id)
    after = {"display_name": user.display_name, "status": user.status, "role_ids": payload.role_ids if payload.role_ids is not None else before["role_ids"]}
    add_audit_event(
        database, action="user.update", resource_type="user", resource_id=user.id,
        outcome="success", request=request, actor=context.user, before=before, after=after,
    )
    database.commit()
    database.refresh(user)
    return _user_response(database, user)


@router.post("/users/{user_id}/reset-password", response_model=MessageResponse)
def reset_password(
    user_id: str,
    payload: ResetPasswordRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.user.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    """重置密码、要求下次修改并撤销目标用户全部会话。"""

    user = database.get(User, user_id)
    if user is None:
        raise PlatformError(404, "NOT_FOUND", "用户不存在")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = True
    revoked = revoke_user_sessions(database, user.id)
    add_audit_event(
        database, action="user.password.reset", resource_type="user", resource_id=user.id,
        outcome="success", request=request, actor=context.user, metadata={"revoked_sessions": revoked},
    )
    database.commit()
    return MessageResponse(message="密码已重置")


@router.delete("/users/{user_id}/sessions", response_model=MessageResponse)
def revoke_sessions(
    user_id: str,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.user.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    """强制撤销指定用户全部会话。"""

    if database.get(User, user_id) is None:
        raise PlatformError(404, "NOT_FOUND", "用户不存在")
    count = revoke_user_sessions(database, user_id)
    add_audit_event(
        database, action="user.sessions.revoke", resource_type="user", resource_id=user_id,
        outcome="success", request=request, actor=context.user, metadata={"count": count},
    )
    database.commit()
    return MessageResponse(message="用户会话已撤销")


def _role_response(database: Session, role: Role) -> RoleResponse:
    """构造带稳定授权顺序的角色响应。"""

    grants = list(database.scalars(select(RoleGrant).where(RoleGrant.role_id == role.id).order_by(RoleGrant.permission_code, RoleGrant.resource_id)).all())
    return RoleResponse(
        id=role.id, name=role.name, description=role.description, is_builtin=role.is_builtin,
        grants=[RoleGrantRequest(permission_code=item.permission_code, resource_type=item.resource_type, resource_id=item.resource_id) for item in grants],
    )


def _replace_grants(database: Session, role: Role, grants: list[RoleGrantRequest], actor_id: str) -> None:
    """校验并原子替换角色授权项。"""

    codes = {grant.permission_code for grant in grants}
    permissions = {
        permission.code: permission
        for permission in database.scalars(select(Permission).where(Permission.code.in_(codes))).all()
    } if codes else {}
    if codes != set(permissions):
        raise PlatformError(422, "VALIDATION_ERROR", "包含不存在的权限")
    tool_ids = set(database.scalars(select(Tool.id)).all())
    for grant in grants:
        permission = permissions[grant.permission_code]
        if permission.resource_type != grant.resource_type:
            raise PlatformError(422, "VALIDATION_ERROR", "权限与资源类型不匹配")
        if grant.resource_type == "platform" and grant.resource_id != "*":
            raise PlatformError(422, "VALIDATION_ERROR", "平台权限的资源范围必须为 *")
        if grant.resource_type == "tool" and grant.resource_id != "*" and grant.resource_id not in tool_ids:
            raise PlatformError(422, "VALIDATION_ERROR", "工具权限包含不存在的工具")
    database.execute(delete(RoleGrant).where(RoleGrant.role_id == role.id))
    unique = {(item.permission_code, item.resource_type, item.resource_id) for item in grants}
    for code, resource_type, resource_id in sorted(unique):
        database.add(RoleGrant(
            role_id=role.id, permission_code=code, resource_type=resource_type,
            resource_id=resource_id, created_by=actor_id,
        ))
    affected = set(database.scalars(select(UserRole.user_id).where(UserRole.role_id == role.id)).all())
    for user_id in affected:
        user = database.get(User, user_id)
        if user:
            user.permission_version += 1


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(
    _: Annotated[AuthContext, Depends(require_platform("platform.role.manage"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[RoleResponse]:
    """返回全部内置和自定义角色。"""

    roles = list(database.scalars(select(Role).order_by(Role.name)).all())
    return [_role_response(database, role) for role in roles]


@router.post("/roles", response_model=RoleResponse, status_code=201)
def create_role(
    payload: RoleCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.role.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> RoleResponse:
    """创建自定义角色及其授权项。"""

    if database.scalar(select(Role).where(Role.name == payload.name.strip())):
        raise PlatformError(409, "ROLE_EXISTS", "角色名称已存在")
    role = Role(id=new_id("role"), name=payload.name.strip(), description=payload.description, is_builtin=False)
    database.add(role)
    database.flush()
    _replace_grants(database, role, payload.grants, context.user.id)
    add_audit_event(
        database, action="role.create", resource_type="role", resource_id=role.id,
        outcome="success", request=request, actor=context.user,
        after={"name": role.name, "grants": [item.model_dump() for item in payload.grants]},
    )
    database.commit()
    return _role_response(database, role)


@router.get("/roles/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: str,
    _: Annotated[AuthContext, Depends(require_platform("platform.role.manage"))],
    database: Annotated[Session, Depends(get_db)],
) -> RoleResponse:
    """获取角色详情。"""

    role = database.get(Role, role_id)
    if role is None:
        raise PlatformError(404, "NOT_FOUND", "角色不存在")
    return _role_response(database, role)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
def update_role(
    role_id: str,
    payload: RoleUpdateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.role.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> RoleResponse:
    """修改角色显示信息和授权项；内置角色允许调整授权但不允许改名。"""

    role = database.get(Role, role_id)
    if role is None:
        raise PlatformError(404, "NOT_FOUND", "角色不存在")
    before = _role_response(database, role).model_dump()
    if payload.name is not None:
        if role.is_builtin:
            raise PlatformError(422, "VALIDATION_ERROR", "内置角色不能改名")
        role.name = payload.name.strip()
    if payload.description is not None:
        role.description = payload.description
    if payload.grants is not None:
        _replace_grants(database, role, payload.grants, context.user.id)
    add_audit_event(
        database, action="role.update", resource_type="role", resource_id=role.id,
        outcome="success", request=request, actor=context.user,
        before=before, after={"name": role.name, "description": role.description, "grants": [item.model_dump() for item in payload.grants] if payload.grants is not None else before["grants"]},
    )
    database.commit()
    return _role_response(database, role)


@router.delete("/roles/{role_id}", response_model=MessageResponse)
def delete_role(
    role_id: str,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.role.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    """删除未被用户使用的自定义角色。"""

    role = database.get(Role, role_id)
    if role is None:
        raise PlatformError(404, "NOT_FOUND", "角色不存在")
    if role.is_builtin:
        raise PlatformError(422, "VALIDATION_ERROR", "内置角色不能删除")
    if database.scalar(select(UserRole).where(UserRole.role_id == role.id)):
        raise PlatformError(409, "ROLE_IN_USE", "角色仍被用户使用")
    add_audit_event(
        database, action="role.delete", resource_type="role", resource_id=role.id,
        outcome="success", request=request, actor=context.user, before={"name": role.name},
    )
    database.delete(role)
    database.commit()
    return MessageResponse(message="角色已删除")


@router.get("/permissions")
def list_permissions(
    _: Annotated[AuthContext, Depends(require_platform("platform.role.manage"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[dict[str, str]]:
    """返回角色编辑器可选择的稳定权限目录。"""

    rows = list(database.scalars(select(Permission).order_by(Permission.resource_type, Permission.code)).all())
    return [{"code": row.code, "name": row.name, "description": row.description, "resource_type": row.resource_type} for row in rows]
