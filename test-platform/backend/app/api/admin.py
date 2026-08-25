from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, current_auth_context, require_csrf, require_platform
from app.core.errors import PlatformError
from app.core.security import hash_password, new_id, normalize_username
from app.db.session import get_db
from app.models.configuration import (
    ConfigDefinition,
    Environment,
    UserCredential,
    UserCredentialItem,
)
from app.models.identity import Permission, Role, RoleGrant, User, UserRole
from app.models.access import Project, ProjectMembership, UserToolGrant
from app.models.llm import LlmProfile, ToolLlmBinding, UserLlmBinding
from app.models.tool import Tool
from app.schemas.admin import (
    CredentialReadinessResponse,
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
from app.services.authorization import BUSINESS_TOOL_PERMISSIONS, platform_permissions_for_role
from app.services.llm import active_release, release_values


router = APIRouter(prefix="/admin", tags=["admin"])


def _role_ids(database: Session, user_id: str) -> list[str]:
    """读取用户角色 ID 并稳定排序。"""

    return sorted(database.scalars(select(UserRole.role_id).where(UserRole.user_id == user_id)).all())


def _user_response(database: Session, user: User) -> UserAdminResponse:
    """将用户模型转换为不含密码哈希的管理响应。"""

    memberships = database.scalars(select(ProjectMembership).where(
        ProjectMembership.user_id == user.id
    )).all()
    projects = []
    for membership in memberships:
        project = database.get(Project, membership.project_id)
        if project is not None:
            projects.append({
                "id": project.id,
                "code": project.code,
                "name": project.name,
                "status": project.status,
                "relation": membership.relation,
            })
    now = datetime.now(UTC)
    grants = []
    for grant in database.scalars(select(UserToolGrant).where(
        UserToolGrant.user_id == user.id,
        UserToolGrant.status == "active",
    )).all():
        expires_at = _as_utc(grant.expires_at)
        if expires_at is None or expires_at <= now:
            continue
        tool = database.get(Tool, grant.tool_id)
        project = database.get(Project, grant.project_id)
        if tool is not None and project is not None:
            grants.append({
                "id": grant.id,
                "tool_id": tool.id,
                "tool_name": tool.name,
                "project_id": project.id,
                "project_name": project.name,
                "status": grant.status,
                "grant_reason": grant.grant_reason,
                "expires_at": grant.expires_at,
            })

    return UserAdminResponse(
        id=user.id, username=user.username, display_name=user.display_name,
        status=user.status, must_change_password=user.must_change_password,
        role=user.platform_role,
        role_ids=_role_ids(database, user.id), last_login_at=user.last_login_at,
        projects=projects,
        extra_tool_grants=grants,
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


def _legacy_role_ids_for_platform_role(database: Session, platform_role: str) -> list[str]:
    """在兼容期为固定角色写入最窄的旧角色映射。

    新授权内核只读取 ``platform_role``。这里保留旧关系，是为了让仍未迁移的
    页面和工具在过渡期可读；普通管理员没有安全等价的旧内置角色，因此不做
    近似映射，避免意外获得配置或 Secret 权限。
    """

    mapping = {
        "platform_admin": "role_platform_admin",
        "tester": "role_test_executor",
    }
    role_id = mapping.get(platform_role)
    return [role_id] if role_id and database.get(Role, role_id) is not None else []


def _set_platform_role(database: Session, user: User, platform_role: str, actor_id: str) -> None:
    """原子设置唯一固定角色，并同步兼容期旧角色关系。"""

    user.platform_role = platform_role
    _replace_user_roles(
        database,
        user,
        _legacy_role_ids_for_platform_role(database, platform_role),
        actor_id,
    )


def _as_utc(value: datetime | None) -> datetime | None:
    """统一数据库时间的时区，兼容 SQLite 测试返回的 naive datetime。"""

    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _credential_readiness_status(
    credential: UserCredential | None,
    *,
    configured_count: int,
    required_count: int,
    now: datetime,
) -> str:
    """把内部 Credential 生命周期归一为管理员页面的四种稳定展示状态。"""

    if (
        credential is None
        or credential.current_version <= 0
        or configured_count < required_count
        or credential.status == "missing"
    ):
        return "missing"
    if credential.status in {"invalid", "action_required", "error", "failed", "revoked"}:
        return "invalid"
    expires_at = _as_utc(credential.expires_at)
    refresh_expires_at = _as_utc(credential.refresh_expires_at)
    if expires_at is not None and expires_at <= now:
        return "invalid"
    if any(
        value is not None and value <= now + timedelta(days=7)
        for value in (expires_at, refresh_expires_at)
    ):
        return "expiring"
    return "configured"


def _credential_readiness_rows(
    database: Session,
    users: list[User],
    environments: list[Environment],
    *,
    tool_id: str | None,
    provider_type: str | None,
    now: datetime,
) -> list[CredentialReadinessResponse]:
    """聚合个人 Credential 元数据，并为尚未创建记录的用户补出 missing 行。

    字段计数来自当前 Credential 版本的 Item 引用；本函数从不读取 Secret 或
    SecretVersion，因此管理员只能判断是否就绪，无法推断具体字段内容。
    """

    definitions = list(database.scalars(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == "tool",
        ConfigDefinition.value_scope == "user",
        ConfigDefinition.credential_provider_type.is_not(None),
    )).all())
    credentials = list(database.scalars(select(UserCredential)).all())
    catalog: dict[tuple[str, str], list[ConfigDefinition]] = {}
    for definition in definitions:
        if tool_id and definition.owner_id != tool_id:
            continue
        if provider_type and definition.credential_provider_type != provider_type:
            continue
        catalog.setdefault(
            (definition.owner_id, str(definition.credential_provider_type)), []
        ).append(definition)
    # 迁移数据若暂时缺少定义仍应出现在管理员视图，避免异常对象被静默隐藏。
    for credential in credentials:
        if tool_id and credential.tool_id != tool_id:
            continue
        if provider_type and credential.provider_type != provider_type:
            continue
        catalog.setdefault((credential.tool_id, credential.provider_type), [])

    credential_map = {
        (row.user_id, row.environment_id, row.tool_id, row.provider_type): row
        for row in credentials
    }
    current_versions = {row.id: row.current_version for row in credentials}
    configured_keys: dict[str, set[str]] = {}
    for item in database.scalars(select(UserCredentialItem)).all():
        if item.credential_version == current_versions.get(item.credential_id):
            configured_keys.setdefault(item.credential_id, set()).add(item.key)

    rows: list[CredentialReadinessResponse] = []
    for user in users:
        for environment in environments:
            for (catalog_tool_id, catalog_provider), provider_definitions in sorted(catalog.items()):
                credential = credential_map.get((
                    user.id,
                    environment.id,
                    catalog_tool_id,
                    catalog_provider,
                ))
                definition_keys = {row.key for row in provider_definitions}
                required_keys = {row.key for row in provider_definitions if row.required}
                item_keys = configured_keys.get(credential.id, set()) if credential else set()
                configured_count = len(item_keys & definition_keys) if definition_keys else len(item_keys)
                readiness_status = _credential_readiness_status(
                    credential,
                    configured_count=configured_count,
                    required_count=len(required_keys),
                    now=now,
                )
                rows.append(CredentialReadinessResponse(
                    resource_type="credential",
                    user_id=user.id,
                    username=user.username,
                    user_status=user.status,
                    environment_id=environment.id,
                    tool_id=catalog_tool_id,
                    provider_type=catalog_provider,
                    capability_key=None,
                    readiness_status=readiness_status,
                    credential_status=credential.status if credential else "missing",
                    current_version=credential.current_version if credential else 0,
                    configured_field_count=configured_count,
                    required_field_count=len(required_keys),
                    expires_at=credential.expires_at if credential else None,
                    refresh_expires_at=credential.refresh_expires_at if credential else None,
                    last_checked_at=credential.last_checked_at if credential else None,
                    last_error_code=credential.last_error_code if credential else None,
                ))
    return rows


def _llm_readiness_rows(
    database: Session,
    users: list[User],
    environments: list[Environment],
    *,
    tool_id: str | None,
    provider_type: str | None,
    now: datetime,
) -> list[CredentialReadinessResponse]:
    """汇总个人 LLM Binding/Profile 的发布状态，不物化 API Key 明文。"""

    if provider_type and provider_type != "llm":
        return []
    catalog = list(database.scalars(select(ToolLlmBinding).order_by(
        ToolLlmBinding.tool_id, ToolLlmBinding.capability_key
    )).all())
    if tool_id:
        catalog = [row for row in catalog if row.tool_id == tool_id]
    personal = {
        (row.user_id, row.binding_id): row
        for row in database.scalars(select(UserLlmBinding)).all()
    }
    rows: list[CredentialReadinessResponse] = []
    for user in users:
        for environment in environments:
            for binding in catalog:
                user_binding = personal.get((user.id, binding.id))
                release = active_release(
                    database,
                    environment.id,
                    "user_llm_binding",
                    user_binding.id,
                ) if user_binding else None
                values, binding_secrets = release_values(database, release)
                profile_id = values.get("PROFILE_ID")
                profile = database.get(LlmProfile, profile_id) if isinstance(profile_id, str) else None
                profile_release = active_release(
                    database,
                    environment.id,
                    "llm_profile",
                    profile.id,
                ) if profile and profile.owner_user_id == user.id else None
                profile_values, profile_secrets = release_values(database, profile_release)
                chosen_secret = (
                    binding_secrets.get("API_KEY_OVERRIDE")
                    or profile_secrets.get("API_KEY")
                )
                structurally_ready = bool(
                    release
                    and values.get("ENABLED", True)
                    and profile
                    and profile.owner_user_id == user.id
                    and not profile.is_archived
                    and profile_release
                    and profile_values.get("ENABLED", True)
                    and isinstance(profile_values.get("BASE_URL"), str)
                    and isinstance(profile_values.get("MODEL"), str)
                    and chosen_secret
                )
                secret_expires_at = _as_utc(chosen_secret[1].expires_at) if chosen_secret else None
                if not release:
                    readiness_status = "missing"
                elif not structurally_ready or (
                    secret_expires_at is not None and secret_expires_at <= now
                ):
                    readiness_status = "invalid"
                elif secret_expires_at is not None and secret_expires_at <= now + timedelta(days=7):
                    readiness_status = "expiring"
                else:
                    readiness_status = "configured"
                rows.append(CredentialReadinessResponse(
                    resource_type="llm_binding",
                    user_id=user.id,
                    username=user.username,
                    user_status=user.status,
                    environment_id=environment.id,
                    tool_id=binding.tool_id,
                    provider_type="llm",
                    capability_key=binding.capability_key,
                    readiness_status=readiness_status,
                    credential_status=None,
                    current_version=release.version if release else 0,
                    configured_field_count=1 if structurally_ready else 0,
                    required_field_count=1,
                    expires_at=secret_expires_at,
                    refresh_expires_at=None,
                    last_checked_at=None,
                    last_error_code=(
                        None if structurally_ready else "PERSONAL_LLM_NOT_CONFIGURED"
                    ),
                ))
    return rows


@router.get("/credential-readiness", response_model=list[CredentialReadinessResponse])
def credential_readiness(
    request: Request,
    response: Response,
    context: Annotated[
        AuthContext,
        Depends(require_platform("platform.credential.readiness.view")),
    ],
    database: Annotated[Session, Depends(get_db)],
    environment_id: str | None = None,
    user_id: str | None = None,
    tool_id: str | None = None,
    provider_type: str | None = None,
    status: str | None = None,
) -> list[CredentialReadinessResponse]:
    """返回全员个人 Credential 与 LLM 能力的脱敏只读就绪度。"""

    if status and status not in {"configured", "missing", "invalid", "expiring"}:
        raise PlatformError(422, "VALIDATION_ERROR", "就绪度状态筛选值无效")
    users_statement = select(User).order_by(User.username_normalized)
    if user_id:
        users_statement = users_statement.where(User.id == user_id)
    users = list(database.scalars(users_statement).all())
    environment_statement = select(Environment).where(
        Environment.is_active.is_(True)
    ).order_by(Environment.sort_order, Environment.id)
    if environment_id:
        environment_statement = environment_statement.where(Environment.id == environment_id)
    environments = list(database.scalars(environment_statement).all())
    now = datetime.now(UTC)
    rows = _credential_readiness_rows(
        database,
        users,
        environments,
        tool_id=tool_id,
        provider_type=provider_type,
        now=now,
    )
    rows.extend(_llm_readiness_rows(
        database,
        users,
        environments,
        tool_id=tool_id,
        provider_type=provider_type,
        now=now,
    ))
    if status:
        rows = [row for row in rows if row.readiness_status == status]
    rows.sort(key=lambda row: (
        row.username.casefold(),
        row.environment_id,
        row.tool_id,
        row.resource_type,
        row.provider_type or "",
        row.capability_key or "",
    ))
    filters = {
        "environment_id": environment_id,
        "user_id": user_id,
        "tool_id": tool_id,
        "provider_type": provider_type,
        "status": status,
    }
    add_audit_event(
        database,
        action="admin.credential.readiness.view",
        resource_type="credential_readiness",
        outcome="success",
        request=request,
        actor=context.user,
        metadata={"filters": filters, "result_count": len(rows)},
    )
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return rows


@router.get("/users", response_model=list[UserAdminResponse])
def list_users(
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> list[UserAdminResponse]:
    """平台管理员查看全员；普通管理员只看自己项目中的 tester。"""

    if context.user.platform_role == "platform_admin":
        rows = list(database.scalars(select(User).order_by(User.username_normalized)).all())
    elif context.user.platform_role == "admin":
        managed_ids = select(ProjectMembership.project_id).where(
            ProjectMembership.user_id == context.user.id,
            ProjectMembership.relation == "manager",
        )
        visible_user_ids = select(ProjectMembership.user_id).where(
            ProjectMembership.project_id.in_(managed_ids),
            ProjectMembership.relation == "member",
        )
        rows = list(database.scalars(select(User).where(
            User.id.in_(visible_user_ids),
            User.platform_role == "tester",
        ).order_by(User.username_normalized)).all())
    else:
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理平台用户")
    return [_user_response(database, user) for user in rows]


@router.post("/users", response_model=UserAdminResponse, status_code=201)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(current_auth_context)],
    _: Annotated[None, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> UserAdminResponse:
    """创建本地用户、分配角色并写入同事务审计。"""

    if context.user.platform_role == "admin" and payload.role != "tester":
        raise PlatformError(403, "PERMISSION_DENIED", "普通管理员只能创建测试人员")
    if context.user.platform_role not in {"platform_admin", "admin"}:
        raise PlatformError(403, "PERMISSION_DENIED", "无权创建用户")
    normalized = normalize_username(payload.username)
    if database.scalar(select(User).where(User.username_normalized == normalized)):
        raise PlatformError(409, "USERNAME_EXISTS", "用户名已存在")
    if payload.role is None:
        _validate_roles(database, payload.role_ids)
    user = User(
        id=new_id("usr"), username=payload.username.strip(), username_normalized=normalized,
        display_name=payload.display_name.strip(), password_hash=hash_password(payload.password),
        status="active", must_change_password=payload.must_change_password,
    )
    database.add(user)
    database.flush()
    if payload.role is not None:
        _set_platform_role(database, user, payload.role, context.user.id)
    else:
        _replace_user_roles(database, user, payload.role_ids, context.user.id)
    add_audit_event(
        database, action="user.create", resource_type="user", resource_id=user.id,
        outcome="success", request=request, actor=context.user,
        after={
            "username": user.username,
            "display_name": user.display_name,
            "role": payload.role,
            "role_ids": payload.role_ids,
        },
    )
    database.commit()
    database.refresh(user)
    return _user_response(database, user)


@router.get("/users/{user_id}", response_model=UserAdminResponse)
def get_user(
    user_id: str,
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> UserAdminResponse:
    """获取单个用户管理详情。"""

    user = database.get(User, user_id)
    if user is None:
        raise PlatformError(404, "NOT_FOUND", "用户不存在")
    if context.user.platform_role == "admin":
        managed_ids = set(database.scalars(select(ProjectMembership.project_id).where(
            ProjectMembership.user_id == context.user.id,
            ProjectMembership.relation == "manager",
        )).all())
        user_projects = set(database.scalars(select(ProjectMembership.project_id).where(
            ProjectMembership.user_id == user.id,
            ProjectMembership.relation == "member",
        )).all())
        if user.platform_role != "tester" or not managed_ids.intersection(user_projects):
            raise PlatformError(404, "NOT_FOUND", "用户不存在")
    elif context.user.platform_role != "platform_admin":
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理平台用户")
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
    removes_active_platform_admin = (
        user.platform_role == "platform_admin"
        and user.status == "active"
        and (
            payload.status == "disabled"
            or (payload.role is not None and payload.role != "platform_admin")
        )
    )
    if removes_active_platform_admin:
        # 所有降级/禁用请求都按稳定 ID 顺序锁定平台管理员集合。并发事务必须
        # 等待前一个事务提交后再重读状态，不能分别看到“还有两个管理员”。
        platform_admins = list(database.scalars(
            select(User)
            .where(User.platform_role == "platform_admin")
            .order_by(User.id)
            .with_for_update()
        ).all())
        active_platform_admins = sum(row.status == "active" for row in platform_admins)
        if active_platform_admins <= 1:
            raise PlatformError(
                409,
                "LAST_PLATFORM_ADMIN",
                "必须至少保留一个启用的平台管理员",
            )
    before = {
        "display_name": user.display_name,
        "status": user.status,
        "role": user.platform_role,
        "role_ids": _role_ids(database, user.id),
    }
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if payload.status is not None:
        if user.id == context.user.id and payload.status == "disabled":
            raise PlatformError(422, "VALIDATION_ERROR", "不能禁用当前登录用户")
        user.status = payload.status
        if payload.status == "disabled":
            revoke_user_sessions(database, user.id)
    if payload.role is not None:
        _set_platform_role(database, user, payload.role, context.user.id)
    elif payload.role_ids is not None:
        _replace_user_roles(database, user, payload.role_ids, context.user.id)
    after = {
        "display_name": user.display_name,
        "status": user.status,
        "role": user.platform_role,
        "role_ids": payload.role_ids if payload.role_ids is not None else before["role_ids"],
    }
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
    """返回三个只读固定角色矩阵，不再暴露 legacy 自定义角色。"""

    labels = {
        "platform_admin": ("平台管理员", "全平台管理与全局业务数据范围"),
        "admin": ("管理员", "负责项目的人员、工具管理与项目数据范围"),
        "tester": ("测试人员", "公共/项目/额外工具使用与本人数据范围"),
    }
    result = []
    for role_id in ("platform_admin", "admin", "tester"):
        name, description = labels[role_id]
        grants = [
            RoleGrantRequest(permission_code=code, resource_type="platform", resource_id="*")
            for code in sorted(platform_permissions_for_role(role_id))
        ]
        grants.extend(
            RoleGrantRequest(permission_code=code, resource_type="tool", resource_id="*")
            for code in sorted(BUSINESS_TOOL_PERMISSIONS)
        )
        result.append(RoleResponse(
            id=role_id,
            name=name,
            description=description,
            is_builtin=True,
            grants=grants,
        ))
    return result


@router.post("/roles", response_model=RoleResponse, status_code=201)
def create_role(
    payload: RoleCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.role.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> RoleResponse:
    """固定角色模型禁止创建自定义角色。"""

    raise PlatformError(409, "FIXED_ROLES_READ_ONLY", "固定角色不允许新增、删除或编辑")

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
    """固定角色矩阵只读。"""

    raise PlatformError(409, "FIXED_ROLES_READ_ONLY", "固定角色不允许新增、删除或编辑")

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
    """固定角色矩阵只读。"""

    raise PlatformError(409, "FIXED_ROLES_READ_ONLY", "固定角色不允许新增、删除或编辑")

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
