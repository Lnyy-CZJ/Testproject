from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, ToolClientContext, current_auth_context, current_tool_client
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.core.permissions import required_tool_permission
from app.core.security import (
    UserContextTokenError,
    UserContextTokenExpired,
    load_user_context_signing_key,
    new_id,
    new_runtime_context_id,
    sign_user_context,
    token_hash,
    verify_user_context,
)
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.configuration import (
    ConfigActivation,
    ConfigDefinition,
    ConfigRelease,
    ConfigReleaseItem,
    Credential,
    CredentialItem,
    Secret,
    SecretVersion,
    ToolProjectScope,
    UserCredential,
    UserCredentialItem,
)
from app.models.identity import PlatformSession, RuntimeContext, User
from app.models.access import BusinessResourceSnapshot
from app.models.tool import Tool
from app.schemas.auth import MessageResponse
from app.schemas.internal import (
    ConfigAckRequest,
    BusinessResourceRegisterRequest,
    CredentialStatusRequest,
    RuntimeContextCreateRequest,
    RuntimeContextResponse,
    ResourceAccessCheckRequest,
    ResourceAccessCheckResponse,
    RuntimeConfigMaterializeRequest,
    RuntimeConfigResponse,
    RuntimeSnapshotSelector,
    InternalRuntimeScope,
    InternalRuntimeScopeItem,
    InternalRuntimeScopeListResponse,
    ActiveReleaseMetadata,
    SessionWriteRequest,
    ToolAuditEventRequest,
    UserCredentialSessionWriteRequest,
)
from app.services.audit import add_audit_event
from app.services.auth import as_utc, validate_runtime_context
from app.services.authorization import consume_public_tool_usage, decide_tool_access, has_tool_permission, tool_permissions
from app.services.resource_authorization import decide_resource_access
from app.services.secret_store import (
    decrypt_secret,
    decrypt_secret_version,
    load_secret_cipher,
    replace_secret,
)
from app.services.llm import (
    materialize_llm_snapshot,
    resolve_legacy_llm_snapshot,
    resolve_llm_snapshot,
)


router = APIRouter(prefix="/internal", tags=["internal"])

# 第一方工具只能使用这里显式登记的根资源动作。列表与下载同样属于
# 对象级授权的一部分，不能退化为仅依赖网关的工具可见性判断。
RESOURCE_ACTIONS = frozenset({"create", "list", "read", "cancel", "retry", "review", "export", "download"})


def public_request_is_locally_safe(tool_id: str, method: str, uri: str) -> bool:
    """公共来源仅允许只读请求和经过评审的本地文件导出。"""

    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return True
    return tool_id == "log-filter" and urlsplit(uri).path == "/log-filter/export"


@router.post("/resources", status_code=201)
def register_business_resource(
    payload: BusinessResourceRegisterRequest,
    request: Request,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    signed_context: Annotated[str | None, Header(alias="X-Platform-Resource-Context")] = None,
) -> dict[str, str | None]:
    """登记不可变根资源快照；重复同 owner 请求幂等，冲突 owner 失败关闭。"""

    _assert_client_scope(context, payload.tool_id)
    user, _session = _verify_resource_identity(database, settings, context, payload.tool_id, signed_context)
    tool = database.scalar(select(Tool).where(Tool.id == payload.tool_id).with_for_update())
    if tool is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    decision = decide_tool_access(database, user, tool)
    if not decision.allowed:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    snapshot = database.scalar(select(BusinessResourceSnapshot).where(
        BusinessResourceSnapshot.environment_id == context.client.environment_id,
        BusinessResourceSnapshot.tool_id == payload.tool_id,
        BusinessResourceSnapshot.resource_type == payload.resource_type,
        BusinessResourceSnapshot.resource_id == payload.resource_id,
    ))
    if snapshot is not None and snapshot.owner_user_id != user.id:
        raise PlatformError(409, "RESOURCE_ID_CONFLICT", "业务资源标识已被占用")
    if snapshot is None:
        snapshot = BusinessResourceSnapshot(
            id=new_id("brs"), resource_type=payload.resource_type,
            resource_id=payload.resource_id, root_resource_id=payload.resource_id,
            tool_id=payload.tool_id, environment_id=context.client.environment_id,
            owner_user_id=user.id,
            project_id_snapshot=tool.project_id,
            authorization_source_snapshot=decision.source or "unknown",
        )
        database.add(snapshot)
        tool.revision += 1
        tool.authorization_epoch += 1
        add_audit_event(database, action="resource.snapshot.create", resource_type=payload.resource_type, resource_id=payload.resource_id, tool_id=payload.tool_id, environment_id=context.client.environment_id, outcome="success", request=request, actor=user)
        try:
            database.commit()
        except IntegrityError:
            database.rollback()
            snapshot = database.scalar(select(BusinessResourceSnapshot).where(
                BusinessResourceSnapshot.environment_id == context.client.environment_id,
                BusinessResourceSnapshot.tool_id == payload.tool_id,
                BusinessResourceSnapshot.resource_type == payload.resource_type,
                BusinessResourceSnapshot.resource_id == payload.resource_id,
            ))
            if snapshot is None or snapshot.owner_user_id != user.id:
                raise PlatformError(409, "RESOURCE_ID_CONFLICT", "业务资源标识已被占用") from None
    return {
        "resource_id": snapshot.resource_id,
        "environment_id": snapshot.environment_id,
        "owner_user_id": snapshot.owner_user_id,
        "project_id_snapshot": snapshot.project_id_snapshot,
        "authorization_source_snapshot": snapshot.authorization_source_snapshot,
    }


def _parse_credential_expiry(value: Any) -> datetime:
    """解析 Gateway 毫秒时间戳或 Admin ISO 时间为 UTC。"""

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000, UTC)
        except (ValueError, OverflowError, OSError):
            raise PlatformError(422, "VALIDATION_ERROR", "凭证过期时间格式不正确") from None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(value) / 1000, UTC)
            except (ValueError, OverflowError):
                pass
    raise PlatformError(422, "VALIDATION_ERROR", "凭证过期时间格式不正确")


def _require_capability(context: ToolClientContext, capability: str) -> None:
    """限制工具 Client 只能调用启动时授予的最小内部能力。"""

    if capability not in set(context.client.capabilities or []):
        raise PlatformError(403, "TOOL_CLIENT_FORBIDDEN", "工具身份无权执行此操作")


@router.get("/authorize", status_code=204)
def authorize_tool_request(
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    tool_id: Annotated[str, Header(alias="X-Tool-ID")],
    original_uri: Annotated[str, Header(alias="X-Original-URI")],
    original_method: Annotated[str, Header(alias="X-Original-Method")],
) -> Response:
    """供 Nginx auth_request 校验会话与当前工具路径权限。"""

    tool = database.get(Tool, tool_id)
    if tool is None or not tool.is_enabled:
        raise PlatformError(404, "NOT_FOUND", "工具不存在")
    permissions = tool_permissions(database, context.user.id, tool_id)
    required = required_tool_permission(tool_id, original_method, original_uri)
    if required not in permissions:
        raise PlatformError(403, "PERMISSION_DENIED", "无权访问该工具资源")
    access_decision = decide_tool_access(database, context.user, tool)
    if access_decision.source == "public":
        if not public_request_is_locally_safe(tool_id, original_method, original_uri):
            # v1 没有统一真实目标出口代理；公共来源只允许只读与明确登记的本地
            # 导出操作，不能仅凭 policy JSON 启动可能访问真实目标的任务。
            raise PlatformError(403, "PUBLIC_REAL_EXECUTION_DISABLED", "公共工具暂未开放真实执行")
        # 首次创建用户配额桶时没有可锁行，短事务锁定工具作为稳定串行化键，
        # 避免两个并发首请求同时插入相同主键。
        tool = database.scalar(select(Tool).where(Tool.id == tool_id).with_for_update())
        consume_public_tool_usage(database, context.user, tool, kind="request")
        database.commit()
    # 身份 Header 仅由网关根据此响应注入；值移除换行，避免响应头注入。
    safe_username = quote(context.user.username.replace("\r", "").replace("\n", ""), safe="")
    safe_display_name = quote(context.user.display_name.replace("\r", "").replace("\n", ""), safe="")
    now_epoch = int(datetime.now(UTC).timestamp())
    try:
        signing_key = load_user_context_signing_key(
            settings.user_context_signing_key_file
        )
    except (OSError, ValueError):
        raise PlatformError(
            503, "RUNTIME_CONTEXT_UNAVAILABLE", "可信用户上下文服务暂时不可用"
        ) from None
    signed_context = sign_user_context({
        "v": 1,
        "sid": context.session.id,
        "uid": context.user.id,
        "pv": context.user.permission_version,
        "tid": tool_id,
        "env": settings.platform_runtime_env,
        "iat": now_epoch,
        "exp": now_epoch + min(settings.user_context_ttl_seconds, 300),
        "nonce": new_id("ctx"),
    }, signing_key)
    return Response(status_code=204, headers={
        "X-Platform-User-ID": context.user.id,
        "X-Platform-Username": safe_username,
        "X-Platform-Display-Name": safe_display_name,
        "X-Platform-Permissions": ",".join(sorted(permissions)),
        "X-Platform-User-Context": signed_context,
        # 两个 Header 当前使用同一短期签名载荷，但语义分离；工具不得自行解析。
        "X-Platform-Resource-Context": signed_context,
    })


def _assert_client_scope(context: ToolClientContext, tool_id: str) -> None:
    """拒绝工具 Client 跨工具读取或写入。"""

    if context.client.tool_id != tool_id:
        raise PlatformError(403, "TOOL_CLIENT_FORBIDDEN", "工具身份作用域不匹配")


def _verify_resource_identity(
    database: Session,
    settings: Settings,
    context: ToolClientContext,
    tool_id: str,
    signed_context: str | None,
) -> tuple[User, PlatformSession]:
    """验证网关注入的资源上下文，并返回仍处于有效状态的身份。

    该函数刻意不接受浏览器传入的 owner、project 或 scope；这些字段后续只从
    数据库中的工具关系和不可变资源快照计算。
    """

    if not signed_context:
        raise PlatformError(401, "RESOURCE_CONTEXT_REQUIRED", "当前请求缺少可信资源上下文")
    try:
        signing_key = load_user_context_signing_key(settings.user_context_signing_key_file)
        claims = verify_user_context(
            signed_context,
            signing_key,
            expected_tool_id=tool_id,
            expected_environment_id=context.client.environment_id,
            max_ttl_seconds=settings.user_context_ttl_seconds,
        )
    except UserContextTokenExpired:
        raise PlatformError(401, "RESOURCE_CONTEXT_EXPIRED", "资源上下文已过期") from None
    except UserContextTokenError:
        raise PlatformError(403, "RESOURCE_CONTEXT_INVALID", "资源上下文无效") from None
    except (OSError, ValueError):
        raise PlatformError(503, "RESOURCE_CONTEXT_UNAVAILABLE", "资源授权服务暂时不可用") from None

    now = datetime.now(UTC)
    session = database.get(PlatformSession, str(claims["sid"]))
    user = database.get(User, str(claims["uid"]))
    if (
        session is None
        or session.user_id != claims["uid"]
        or session.revoked_at is not None
        or as_utc(session.idle_expires_at) <= now
        or as_utc(session.absolute_expires_at) <= now
        or user is None
        or user.status != "active"
        or user.permission_version != claims["pv"]
    ):
        raise PlatformError(403, "RESOURCE_CONTEXT_INVALID", "资源上下文无效")
    return user, session


@router.post(
    "/tools/{tool_id}/resource-access/check",
    response_model=ResourceAccessCheckResponse,
)
def check_resource_access(
    tool_id: str,
    payload: ResourceAccessCheckRequest,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    signed_context: Annotated[
        str | None, Header(alias="X-Platform-Resource-Context")
    ] = None,
) -> ResourceAccessCheckResponse:
    """为列表与根资源操作返回同一 own/project/global 判定结果。"""

    _assert_client_scope(context, tool_id)
    if payload.action not in RESOURCE_ACTIONS:
        raise PlatformError(403, "RESOURCE_ACTION_DENIED", "未注册的资源操作不允许执行")
    user, _session = _verify_resource_identity(
        database, settings, context, tool_id, signed_context
    )
    tool = database.get(Tool, tool_id)
    if tool is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    tool_decision = decide_tool_access(database, user, tool)
    if not tool_decision.allowed:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")

    data_scope = "own"
    managed_project_ids: list[str] = []
    access_scope_snapshot = tool.access_scope
    project_id_snapshot = tool.project_id
    authorization_source_snapshot = tool_decision.source
    if user.platform_role == "platform_admin":
        data_scope = "global"
    elif tool_decision.source == "project_manager" and tool.project_id:
        data_scope = "project"
        managed_project_ids = [tool.project_id]

    if payload.root_resource_id is not None:
        snapshot = database.scalar(select(BusinessResourceSnapshot).where(
            BusinessResourceSnapshot.environment_id == context.client.environment_id,
            BusinessResourceSnapshot.tool_id == tool_id,
            BusinessResourceSnapshot.resource_type == payload.resource_type,
            BusinessResourceSnapshot.resource_id == payload.root_resource_id,
        ))
        if snapshot is None:
            raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
        resource_decision = decide_resource_access(database, user, snapshot)
        if not resource_decision.allowed:
            raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
        data_scope = resource_decision.scope or "own"
        project_id_snapshot = snapshot.project_id_snapshot
        access_scope_snapshot = "project" if snapshot.project_id_snapshot else "public"
        authorization_source_snapshot = snapshot.authorization_source_snapshot
        managed_project_ids = (
            [snapshot.project_id_snapshot]
            if data_scope == "project" and snapshot.project_id_snapshot
            else []
        )

    return ResourceAccessCheckResponse(
        allowed=True,
        action=payload.action,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        tool_id=tool_id,
        environment=context.client.environment_id,
        data_scope=data_scope,
        managed_project_ids=managed_project_ids,
        access_scope_snapshot=access_scope_snapshot,
        project_id_snapshot=project_id_snapshot,
        authorization_source_snapshot=authorization_source_snapshot,
    )


def _runtime_context_rejection(
    database: Session,
    request: Request,
    context: ToolClientContext,
    code: str,
    status_code: int,
    message: str,
) -> PlatformError:
    """记录不含签名 Header/Context ID 的兑换拒绝审计并构造安全异常。"""

    add_audit_event(
        database,
        action="runtime.context.reject",
        resource_type="runtime_context",
        outcome="denied",
        error_code=code,
        tool_id=context.client.tool_id,
        environment_id=context.client.environment_id,
        request=request,
        actor_type="service",
        actor_id=context.client.id,
    )
    database.commit()
    return PlatformError(status_code, code, message)


def _fixed_target_env(environment_id: str) -> str:
    """把平台部署环境映射为唯一目标环境，未知环境一律失败关闭。"""

    target_env = {"dev": "test", "prod": "prod"}.get(environment_id)
    if target_env is None:
        raise PlatformError(
            422, "RUNTIME_SCOPE_MAPPING_INVALID", "平台环境没有受支持的目标环境映射"
        )
    return target_env


def _resolve_runtime_scope(
    database: Session,
    *,
    tool_id: str,
    environment_id: str,
    platform_project_id: str | None,
    project_id: str | None,
    require_active: bool = True,
) -> ToolProjectScope:
    """按完整五元组解析唯一 Scope，并区分缺失与禁用状态。

    参数说明:
        platform_project_id: 只能来自服务端授权决策，不能来自请求体。
        project_id: 工具请求唯一允许选择的项目键。
        require_active: 执行链路为 True；管理型只读场景可放宽。
    异常说明:
        RUNTIME_SCOPE_NOT_FOUND: 任一受控维度无法解析。
        RUNTIME_SCOPE_DISABLED: Scope 存在但禁止创建新任务或物化。
    """

    if not platform_project_id or not project_id:
        raise PlatformError(422, "RUNTIME_SCOPE_REQUIRED", "必须选择工具项目")
    target_env = _fixed_target_env(environment_id)
    row = database.scalar(select(ToolProjectScope).where(
        ToolProjectScope.environment_id == environment_id,
        ToolProjectScope.tool_id == tool_id,
        ToolProjectScope.platform_project_id == platform_project_id,
        ToolProjectScope.project_id == project_id,
        ToolProjectScope.target_env == target_env,
    ))
    if row is None:
        raise PlatformError(404, "RUNTIME_SCOPE_NOT_FOUND", "当前项目没有可用 Runtime Scope")
    if require_active and row.status != "active":
        raise PlatformError(409, "RUNTIME_SCOPE_DISABLED", "当前 Runtime Scope 已禁用")
    return row


def _internal_scope(row: ToolProjectScope) -> InternalRuntimeScope:
    """构造不含运行配置值的内部 Scope 元数据。"""

    return InternalRuntimeScope(
        scope_id=row.id, platform_project_id=row.platform_project_id,
        project_id=row.project_id, display_name=row.display_name,
        platform_environment=row.environment_id, target_env=row.target_env,
        status=row.status, is_default=row.is_default,
    )


def _verify_internal_scope_identity(
    database: Session,
    settings: Settings,
    context: ToolClientContext,
    tool_id: str,
    signed_context: str | None,
) -> tuple[User, Tool, str]:
    """验证 Scope 列表的签名身份，并返回服务端派生的平台项目 ID。"""

    if not signed_context:
        raise PlatformError(403, "RUNTIME_CONTEXT_REQUIRED", "当前请求缺少可信用户上下文")
    try:
        claims = verify_user_context(
            signed_context,
            load_user_context_signing_key(settings.user_context_signing_key_file),
            expected_tool_id=tool_id,
            expected_environment_id=context.client.environment_id,
            max_ttl_seconds=settings.user_context_ttl_seconds,
        )
    except UserContextTokenExpired:
        raise PlatformError(401, "RUNTIME_CONTEXT_EXPIRED", "用户上下文已过期，请重新提交") from None
    except (UserContextTokenError, OSError, ValueError):
        raise PlatformError(403, "RUNTIME_CONTEXT_INVALID", "用户上下文无效或与工具不匹配") from None
    now = datetime.now(UTC)
    session = database.get(PlatformSession, str(claims["sid"]))
    user = database.get(User, str(claims["uid"]))
    if (
        session is None or user is None or session.user_id != user.id
        or session.revoked_at is not None or as_utc(session.idle_expires_at) <= now
        or as_utc(session.absolute_expires_at) <= now or user.status != "active"
        or user.permission_version != claims["pv"]
        or not has_tool_permission(database, user.id, "tool.execute", tool_id)
    ):
        raise PlatformError(403, "RUNTIME_CONTEXT_INVALID", "用户上下文无效或与工具不匹配")
    tool = database.get(Tool, tool_id)
    if tool is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    decision = decide_tool_access(database, user, tool) if user.platform_role is not None else None
    platform_project_id = decision.project_id if decision is not None else tool.project_id
    if not platform_project_id:
        raise PlatformError(403, "RUNTIME_SCOPE_FORBIDDEN", "当前身份没有平台项目运行权限")
    return user, tool, platform_project_id


@router.get(
    "/tools/{tool_id}/runtime-scopes",
    response_model=InternalRuntimeScopeListResponse,
)
def list_internal_runtime_scopes(
    tool_id: str,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    signed_context: Annotated[str | None, Header(alias="X-Platform-User-Context")] = None,
) -> InternalRuntimeScopeListResponse:
    """返回当前工具客户端、签名用户及平台项目共同授权的 Scope 列表。"""

    _assert_client_scope(context, tool_id)
    _require_capability(context, "runtime.context.create")
    _user, _tool, platform_project_id = _verify_internal_scope_identity(
        database, settings, context, tool_id, signed_context
    )
    rows = database.scalars(select(ToolProjectScope).where(
        ToolProjectScope.tool_id == tool_id,
        ToolProjectScope.environment_id == context.client.environment_id,
        ToolProjectScope.platform_project_id == platform_project_id,
        ToolProjectScope.status == "active",
    ).order_by(ToolProjectScope.is_default.desc(), ToolProjectScope.project_id)).all()
    items: list[InternalRuntimeScopeItem] = []
    for row in rows:
        activation = database.scalar(select(ConfigActivation).where(
            ConfigActivation.environment_id == row.environment_id,
            ConfigActivation.owner_type == "tool_project_scope",
            ConfigActivation.owner_id == row.id,
        ))
        release = database.get(ConfigRelease, activation.active_release_id) if activation else None
        if release is not None and (
            release.environment_id, release.owner_type, release.owner_id, release.status
        ) != (row.environment_id, "tool_project_scope", row.id, "active"):
            # 列表不能把损坏或跨 Scope 的 Activation 当作可运行状态展示。
            raise _runtime_snapshot_invalid()
        items.append(InternalRuntimeScopeItem(
            **_internal_scope(row).model_dump(),
            active_release=(ActiveReleaseMetadata(
                id=release.id, version=release.version, status=release.status
            ) if release is not None else None),
            management_url=f"/settings/config?scope_id={quote(row.id, safe='')}",
        ))
    return InternalRuntimeScopeListResponse(items=items)


@router.post(
    "/tools/{tool_id}/runtime-contexts",
    response_model=RuntimeContextResponse,
    status_code=201,
)
def create_runtime_context(
    tool_id: str,
    payload: RuntimeContextCreateRequest,
    request: Request,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    signed_context: Annotated[
        str | None, Header(alias="X-Platform-User-Context")
    ] = None,
) -> RuntimeContextResponse:
    """把 Nginx 注入的短期签名 Header 兑换为可撤销 Runtime Context。"""

    _assert_client_scope(context, tool_id)
    _require_capability(context, "runtime.context.create")
    if not signed_context:
        raise _runtime_context_rejection(
            database, request, context, "RUNTIME_CONTEXT_REQUIRED", 403,
            "当前请求缺少可信用户上下文",
        )
    try:
        signing_key = load_user_context_signing_key(
            settings.user_context_signing_key_file
        )
        claims = verify_user_context(
            signed_context,
            signing_key,
            expected_tool_id=tool_id,
            expected_environment_id=context.client.environment_id,
            max_ttl_seconds=settings.user_context_ttl_seconds,
        )
    except UserContextTokenExpired:
        raise _runtime_context_rejection(
            database, request, context, "RUNTIME_CONTEXT_EXPIRED", 401,
            "用户上下文已过期，请重新提交",
        ) from None
    except UserContextTokenError:
        raise _runtime_context_rejection(
            database, request, context, "RUNTIME_CONTEXT_INVALID", 403,
            "用户上下文无效或与工具不匹配",
        ) from None
    except (OSError, ValueError):
        raise PlatformError(
            503, "RUNTIME_CONTEXT_UNAVAILABLE", "可信用户上下文服务暂时不可用"
        ) from None

    now = datetime.now(UTC)
    session = database.get(PlatformSession, str(claims["sid"]))
    user = database.get(User, str(claims["uid"]))
    invalid_identity = (
        session is None
        or session.user_id != claims["uid"]
        or session.revoked_at is not None
        or as_utc(session.idle_expires_at) <= now
        or as_utc(session.absolute_expires_at) <= now
        or user is None
        or user.status != "active"
        or user.permission_version != claims["pv"]
        or not has_tool_permission(database, str(claims["uid"]), "tool.execute", tool_id)
    )
    if invalid_identity:
        raise _runtime_context_rejection(
            database, request, context, "RUNTIME_CONTEXT_INVALID", 403,
            "用户上下文无效或与工具不匹配",
        )
    # 任务规划会同时写入资源快照并递增工具授权版本，需与影响预览串行化。
    tool = database.scalar(select(Tool).where(Tool.id == tool_id).with_for_update())
    if tool is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    access_decision = (
        decide_tool_access(database, user, tool)
        if user.platform_role is not None
        else None
    )
    if access_decision is not None and access_decision.source == "public":
        # Execution Lease 会赋予后台任务继续执行的能力；公共来源在统一出口代理
        # 接入前一律不签发，避免 real_execution_enabled=false 沦为展示字段。
        raise PlatformError(403, "PUBLIC_REAL_EXECUTION_DISABLED", "公共工具暂未开放真实执行")
    runtime_scope = None
    if tool_id == "api-autotest":
        platform_project_id = (
            access_decision.project_id if access_decision is not None else tool.project_id
        )
        runtime_scope = _resolve_runtime_scope(
            database,
            tool_id=tool_id,
            environment_id=context.client.environment_id,
            platform_project_id=platform_project_id,
            project_id=payload.project_id,
        )
    ttl_seconds = min(settings.runtime_context_ttl_seconds, 86400)
    if ttl_seconds <= 0:
        raise PlatformError(
            503, "RUNTIME_CONTEXT_UNAVAILABLE", "可信用户上下文服务暂时不可用"
        )
    row = RuntimeContext(
        id=new_runtime_context_id(),
        user_id=user.id,
        session_id=session.id,
        tool_id=tool_id,
        environment_id=context.client.environment_id,
        runtime_scope_id=runtime_scope.id if runtime_scope is not None else None,
        permission_version=user.permission_version,
        project_id_snapshot=(
            runtime_scope.platform_project_id if runtime_scope is not None else tool.project_id
        ),
        authorization_source_snapshot=(
            access_decision.source if access_decision is not None else "legacy"
        ),
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        status="active",
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    database.add(row)
    # Runtime Context 的 resource_id 是工具在创建任务前生成的根 ID，因此在同一
    # 事务登记不可变资源快照，避免工具先落任务、平台后补 ACL 的竞态窗口。
    snapshot = database.scalar(select(BusinessResourceSnapshot).where(
        BusinessResourceSnapshot.environment_id == context.client.environment_id,
        BusinessResourceSnapshot.tool_id == tool_id,
        BusinessResourceSnapshot.resource_type == payload.resource_type,
        BusinessResourceSnapshot.resource_id == payload.resource_id,
    ))
    if snapshot is None:
        database.add(BusinessResourceSnapshot(
            id=new_id("brs"),
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            root_resource_id=payload.resource_id,
            tool_id=tool_id,
            environment_id=context.client.environment_id,
            owner_user_id=user.id,
            project_id_snapshot=(
                runtime_scope.platform_project_id if runtime_scope is not None else tool.project_id
            ),
            authorization_source_snapshot=(
                access_decision.source if access_decision is not None else "legacy"
            ),
        ))
        tool.revision += 1
        tool.authorization_epoch += 1
    elif snapshot.owner_user_id != user.id:
        # 同一根 ID 被其他身份抢先登记时统一按冲突拒绝，绝不覆盖所有者。
        raise PlatformError(409, "RESOURCE_ID_CONFLICT", "业务资源标识已被占用")
    add_audit_event(
        database,
        action="runtime.context.create",
        resource_type="runtime_context",
        resource_id="rtx_hash_" + token_hash(row.id)[:16],
        tool_id=row.tool_id,
        environment_id=row.environment_id,
        outcome="success",
        request=request,
        actor_type="service",
        actor_id=context.client.id,
        metadata={
            "subject_user_id": row.user_id,
            "resource_type": row.resource_type,
        },
    )
    selector = None
    if runtime_scope is not None:
        release = _current_tool_release(
            database, context.client.environment_id, tool_id, runtime_scope.id
        )
        if release is None:
            raise PlatformError(409, "CONFIG_RELEASE_NOT_ACTIVE", "Runtime Scope 没有激活的配置版本")
        _normal, _secrets, _configured, system_secret_versions = _system_runtime_snapshot(
            database, settings, tool_id, context.client.environment_id, release,
            include_secrets=False, runtime_scope_id=runtime_scope.id,
        )
        (
            _personal_values, _personal_configured, _metadata,
            credential_versions, credential_secret_versions,
        ) = _personal_credential_runtime_snapshot(
            database, settings, user.id, tool_id, context.client.environment_id,
            include_secrets=False, runtime_scope_id=runtime_scope.id,
            allow_incomplete_profiles=True,
        )
        selector = RuntimeSnapshotSelector(
            runtime_scope_id=runtime_scope.id, release_id=release.id,
            system_secret_versions=system_secret_versions,
            credential_versions=credential_versions,
            credential_secret_versions=credential_secret_versions,
        )
        # 选择器必须随 Context 一次固化；物化接口只接受逐字段完全一致的副本，
        # 防止调用方把同 Scope 的其他历史 Release 或 Credential 版本替换进来。
        row.allowed_config_refs = [selector.model_dump(mode="json")]
    database.commit()
    return RuntimeContextResponse(
        runtime_context_id=row.id,
        tool_id=row.tool_id,
        environment_id=row.environment_id,
        expires_at=row.expires_at,
        resource_snapshot={
            "owner_user_id": user.id,
            "environment_id": context.client.environment_id,
            "access_scope_snapshot": tool.access_scope,
            "project_id_snapshot": row.project_id_snapshot,
            "authorization_source_snapshot": row.authorization_source_snapshot,
        },
        runtime_scope=_internal_scope(runtime_scope) if runtime_scope is not None else None,
        snapshot_selector=selector,
    )


def _runtime_snapshot_invalid() -> PlatformError:
    """构造统一的快照选择器错误，避免泄露跨用户对象是否存在。"""

    return PlatformError(
        409, "RUNTIME_SNAPSHOT_INVALID", "任务配置快照无效，请重新提交任务"
    )


def _system_runtime_snapshot(
    database: Session,
    settings: Settings,
    tool_id: str,
    environment_id: str,
    release: ConfigRelease | None,
    *,
    include_secrets: bool,
    runtime_scope_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, str], set[str], dict[str, str]]:
    """展开全局 Release 中仅 ``value_scope=system`` 的配置。

    被迁移为用户级的 legacy Release Item 会在定义过滤阶段直接忽略，因此即使
    global Secret 仍保留作回滚材料，也不会进入 configured keys 或解密路径。
    """

    runtime_scope = (
        database.get(ToolProjectScope, runtime_scope_id)
        if runtime_scope_id is not None else None
    )

    def applies_to_runtime_project(definition: ConfigDefinition) -> bool:
        """按 Definition 的项目白名单过滤历史 Release 中已不适用的配置项。"""

        project_ids = (definition.validation_schema or {}).get("project_ids")
        if project_ids is None:
            return True
        return (
            runtime_scope is not None
            and isinstance(project_ids, list)
            and runtime_scope.project_id in project_ids
        )

    definitions = {
        row.id: row
        for row in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == "tool",
            ConfigDefinition.owner_id == tool_id,
            ConfigDefinition.value_scope == "system",
        )).all()
        if applies_to_runtime_project(row)
    }
    normal = {
        row.key: row.default_value
        for row in definitions.values()
        if row.sensitivity == "normal" and row.default_value is not None
    }
    secrets: dict[str, str] = {}
    configured: set[str] = set()
    secret_versions: dict[str, str] = {}
    cipher = None
    if release is None:
        return normal, secrets, configured, secret_versions
    for item in database.scalars(select(ConfigReleaseItem).where(
        ConfigReleaseItem.release_id == release.id,
    )).all():
        definition = definitions.get(item.definition_id)
        if definition is None:
            continue
        if definition.sensitivity == "normal":
            normal[definition.key] = item.value_json
            continue
        if not item.secret_version_id:
            continue
        version = database.get(SecretVersion, item.secret_version_id)
        secret = database.get(Secret, version.secret_id) if version else None
        expected_owner = (
            ("tool_project_scope", runtime_scope_id)
            if runtime_scope_id is not None else ("tool", tool_id)
        )
        if secret is None or (
            secret.environment_id,
            secret.owner_type,
            secret.owner_id,
            secret.definition_id,
        ) != (environment_id, *expected_owner, definition.id):
            raise _runtime_snapshot_invalid()
        configured.add(definition.key)
        secret_versions[definition.key] = version.id
        if include_secrets:
            if cipher is None:
                cipher = load_secret_cipher(settings)
            try:
                secrets[definition.key] = decrypt_secret_version(
                    database, cipher, secret, version.id
                )
            except (ValueError, KeyError):
                raise PlatformError(
                    503, "SECRET_UNAVAILABLE", "Secret 服务暂时不可用"
                ) from None
    return normal, secrets, configured, secret_versions


def _personal_credential_runtime_snapshot(
    database: Session,
    settings: Settings,
    user_id: str,
    tool_id: str,
    environment_id: str,
    *,
    include_secrets: bool,
    selected_versions: dict[str, int] | None = None,
    expected_secret_versions: dict[str, dict[str, str]] | None = None,
    runtime_scope_id: str | None = None,
    allow_incomplete_profiles: bool = False,
) -> tuple[
    dict[str, str],
    set[str],
    dict[str, Any],
    dict[str, int],
    dict[str, dict[str, str]],
]:
    """规划或物化当前用户的各 Provider Credential 版本。

    ``selected_versions=None`` 表示规划当前版本；传入版本字典表示物化历史版本。
    后一种模式下所有错误统一映射为 ``RUNTIME_SNAPSHOT_INVALID``，且查询始终先
    过滤 ``user_id``，不能借选择器探测他人 Credential。

    Scope 化的接口自动化允许 Profile 不完整：平台负责冻结当前已配置版本，
    工具再按选中 API/Flow 的声明检查实际所需 Profile。这样 Dating 匿名链路
    不会因为同一 Tool 下未配置 Truthy Admin Profile 而在创建 Context 时被
    全局拦截；legacy 工具仍维持原有“必需 Provider 全部就绪”的行为。
    """

    definitions = list(database.scalars(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == "tool",
        ConfigDefinition.owner_id == tool_id,
        ConfigDefinition.value_scope == "user",
        ConfigDefinition.credential_provider_type.is_not(None),
    ).order_by(ConfigDefinition.sort_order, ConfigDefinition.key)).all())
    by_provider: dict[str, dict[str, ConfigDefinition]] = {}
    for definition in definitions:
        by_provider.setdefault(str(definition.credential_provider_type), {})[
            definition.key
        ] = definition

    def participates_in_runtime(definition: ConfigDefinition) -> bool:
        """判断个人凭证字段是否仍属于运行时契约。

        已迁移到项目 Release 的静态字段会保留 Definition 与历史 Secret，便于
        审计和旧快照校验，但新快照不得再把这些值下发给工具，否则会重新覆盖
        ``gateway.comm`` 中按项目发布的静态参数。
        """

        return not bool(
            (definition.validation_schema or {}).get("runtime_config_excluded")
        )

    if not by_provider:
        if selected_versions or expected_secret_versions:
            raise _runtime_snapshot_invalid()
        return {}, set(), {}, {}, {}

    materializing = selected_versions is not None

    def credential_is_ready(credential: UserCredential) -> bool:
        """判断 Credential 是否允许进入本次运行快照。

        项目 Scope 已经具备完整的 Credential 生命周期，因此必须 fail-closed：
        只有 Agent 明确标记为 ``healthy`` 的版本才可被冻结和物化。验证中、
        刷新中或未来新增的未知状态都只能作为诊断信息返回，不能意外下发
        Secret。尚未迁移到 Runtime Scope 的旧工具继续沿用原有拒绝列表，避免
        本次接口自动化修复改变其它工具的兼容行为。
        """

        if runtime_scope_id is not None:
            return credential.status == "healthy"
        return credential.status not in {"missing", "expired", "action_required"}

    def fail() -> PlatformError:
        if materializing:
            return _runtime_snapshot_invalid()
        return PlatformError(
            409,
            "PERSONAL_CREDENTIAL_NOT_CONFIGURED",
            "请先配置当前工具的个人凭证",
        )

    credentials: list[tuple[UserCredential, int]] = []
    if selected_versions is None:
        rows = list(database.scalars(select(UserCredential).where(
            UserCredential.user_id == user_id,
            UserCredential.tool_id == tool_id,
            UserCredential.environment_id == environment_id,
            UserCredential.runtime_scope_id == runtime_scope_id,
            UserCredential.current_version > 0,
        ).order_by(UserCredential.provider_type)).all())
        credentials = [(row, row.current_version) for row in rows]
    else:
        for credential_id, version in sorted(selected_versions.items()):
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise fail()
            row = database.scalar(select(UserCredential).where(
                UserCredential.user_id == user_id,
                UserCredential.id == credential_id,
                UserCredential.tool_id == tool_id,
                UserCredential.environment_id == environment_id,
                UserCredential.runtime_scope_id == runtime_scope_id,
            ))
            if row is None:
                raise fail()
            credentials.append((row, version))

    # 规划态要同时保留未就绪 Credential 的非敏感诊断元数据。它们随后仍会从
    # selector 与 Secret 物化链路中过滤掉；否则工具只能看到“Profile 缺失”，
    # 无法区分真实未配置、已过期或自动刷新失败。
    planning_credentials = list(credentials)
    if allow_incomplete_profiles and not materializing:
        # Scope 规划阶段只冻结当前可用的 Profile。已失效的可选 Credential
        # 仍应在平台配置中心显示其真实状态，但不能污染一个与它无关的 API/Flow
        # 快照；工具会依据资产声明对真正需要的 Profile 做严格预检。
        # 物化阶段绝不执行此过滤：选择器若被替换为失效版本必须 fail-closed。
        credentials = [
            (row, version)
            for row, version in credentials
            if credential_is_ready(row)
        ]
    credential_by_provider = {row.provider_type: (row, version) for row, version in credentials}
    required_providers = set() if allow_incomplete_profiles else {
        provider
        for provider, provider_definitions in by_provider.items()
        if any(
            definition.required and participates_in_runtime(definition)
            for definition in provider_definitions.values()
        )
    }
    if not required_providers.issubset(credential_by_provider):
        raise fail()
    if set(credential_by_provider) - set(by_provider):
        raise fail()

    values: dict[str, str] = {}
    configured: set[str] = set()
    def provider_metadata(
        credential: UserCredential,
        version_number: int,
    ) -> dict[str, Any]:
        """返回可安全展示的 Profile 状态，不包含字段值或 Secret 指纹。"""

        def iso_timestamp(value: datetime | None) -> str | None:
            # SQLite 测试库会丢失 timezone 标记；对外契约始终补成 UTC，避免
            # dev/prod 因数据库方言不同而返回两种时间格式。
            if value is None:
                return None
            aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
            return aware.astimezone(UTC).isoformat()

        return {
            "credential_id": credential.id,
            "credential_version": version_number,
            "status": credential.status,
            "expires_at": iso_timestamp(credential.expires_at),
            "refresh_expires_at": iso_timestamp(credential.refresh_expires_at),
            "last_checked_at": iso_timestamp(credential.last_checked_at),
            "last_error_code": credential.last_error_code,
        }

    providers: dict[str, Any] = (
        {
            credential.provider_type: provider_metadata(
                credential, version_number
            )
            for credential, version_number in planning_credentials
        }
        if allow_incomplete_profiles and not materializing
        else {}
    )
    versions: dict[str, int] = {}
    secret_versions: dict[str, dict[str, str]] = {}
    primary_metadata: dict[str, Any] = {}
    cipher = None
    for provider, (credential, version_number) in sorted(credential_by_provider.items()):
        if not credential_is_ready(credential):
            raise fail()
        provider_definitions = by_provider[provider]
        items = list(database.scalars(select(UserCredentialItem).where(
            UserCredentialItem.credential_id == credential.id,
            UserCredentialItem.credential_version == version_number,
        )).all())
        items_by_key = {item.key: item for item in items}
        if any(
            definition.required
            and participates_in_runtime(definition)
            and definition.key not in items_by_key
            for definition in provider_definitions.values()
        ):
            raise fail()
        selected_secret_versions: dict[str, str] = {}
        for key, item in items_by_key.items():
            definition = provider_definitions.get(key)
            if definition is None:
                raise fail()
            if not participates_in_runtime(definition):
                # 新快照完全忽略已项目化字段。物化历史任务时，仅校验并保留旧
                # selector 中的版本引用，使既有任务可重放；明文仍不再下发。
                expected_version_id = (
                    (expected_secret_versions or {})
                    .get(credential.id, {})
                    .get(key)
                )
                if expected_version_id is not None:
                    if item.secret_version_id != expected_version_id:
                        raise fail()
                    selected_secret_versions[key] = expected_version_id
                continue
            if item.secret_version_id:
                version = database.get(SecretVersion, item.secret_version_id)
                secret = database.get(Secret, version.secret_id) if version else None
                if secret is None or (
                    secret.environment_id,
                    secret.owner_type,
                    secret.owner_id,
                    secret.definition_id,
                ) != (
                    environment_id,
                    "user_credential",
                    credential.id,
                    definition.id,
                ):
                    raise fail()
                configured.add(key)
                selected_secret_versions[key] = version.id
                if include_secrets:
                    if cipher is None:
                        cipher = load_secret_cipher(settings)
                    try:
                        values[key] = decrypt_secret_version(
                            database, cipher, secret, version.id
                        )
                    except (ValueError, KeyError):
                        raise PlatformError(
                            503, "SECRET_UNAVAILABLE", "Secret 服务暂时不可用"
                        ) from None
            elif item.value_json is not None and definition.sensitivity == "normal":
                configured.add(key)
                if include_secrets:
                    values[key] = str(item.value_json)
                    if provider == "gateway_session":
                        primary_metadata[key] = item.value_json
            else:
                raise fail()
        versions[credential.id] = version_number
        secret_versions[credential.id] = selected_secret_versions
        providers[provider] = provider_metadata(credential, version_number)
        if provider == "gateway_session":
            primary_metadata.update({
                "credential_id": credential.id,
                "credential_version": version_number,
                "provider_type": provider,
                "expires_at": providers[provider]["expires_at"],
                "refresh_expires_at": providers[provider]["refresh_expires_at"],
            })
    if expected_secret_versions is not None and secret_versions != expected_secret_versions:
        raise fail()
    metadata = dict(primary_metadata)
    if providers:
        metadata["providers"] = providers
    return values, configured, metadata, versions, secret_versions


def _current_tool_release(
    database: Session,
    environment_id: str,
    tool_id: str,
    runtime_scope_id: str | None = None,
) -> ConfigRelease | None:
    """返回工具当前全局 Release；该身份只承载 system 配置。"""

    owner_type = "tool_project_scope" if runtime_scope_id is not None else "tool"
    owner_id = runtime_scope_id or tool_id
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == environment_id,
        ConfigActivation.owner_type == owner_type,
        ConfigActivation.owner_id == owner_id,
    ))
    return database.get(ConfigRelease, activation.active_release_id) if activation else None


def _personal_runtime_config(
    tool_id: str,
    runtime_context_id: str | None,
    include_secrets: bool,
    llm_capability: str | None,
    request: Request,
    response: Response,
    context: ToolClientContext,
    database: Session,
    settings: Settings,
) -> RuntimeConfigResponse:
    """规划当前版本，或为同步调用物化当前用户的最新个人快照。"""

    requires_context = include_secrets or bool(llm_capability) or tool_id == "api-autotest"
    if requires_context and not runtime_context_id:
        raise PlatformError(403, "RUNTIME_CONTEXT_REQUIRED", "当前请求缺少可信用户上下文")
    runtime_context = None
    if runtime_context_id:
        runtime_context = validate_runtime_context(
            database, runtime_context_id, context.client, tool_id
        )
    runtime_scope = None
    if tool_id == "api-autotest":
        if runtime_context is None or not runtime_context.runtime_scope_id:
            raise PlatformError(403, "RUNTIME_CONTEXT_REQUIRED", "当前请求缺少可信 Runtime Scope")
        runtime_scope = database.get(ToolProjectScope, runtime_context.runtime_scope_id)
        if runtime_scope is None or (
            runtime_scope.tool_id, runtime_scope.environment_id,
            runtime_scope.platform_project_id,
        ) != (
            tool_id, context.client.environment_id, runtime_context.project_id_snapshot,
        ):
            raise _runtime_snapshot_invalid()
        if runtime_scope.status != "active":
            raise PlatformError(409, "RUNTIME_SCOPE_DISABLED", "当前 Runtime Scope 已禁用")
    release = _current_tool_release(
        database, context.client.environment_id, tool_id,
        runtime_scope.id if runtime_scope is not None else None,
    )
    if tool_id == "api-autotest" and release is None:
        raise PlatformError(409, "CONFIG_RELEASE_NOT_ACTIVE", "Runtime Scope 没有激活的配置版本")
    normal, system_secrets, configured, system_secret_versions = _system_runtime_snapshot(
        database,
        settings,
        tool_id,
        context.client.environment_id,
        release,
        include_secrets=include_secrets,
        runtime_scope_id=runtime_scope.id if runtime_scope is not None else None,
    )
    selector = RuntimeSnapshotSelector(
        runtime_scope_id=runtime_scope.id if runtime_scope is not None else None,
        release_id=release.id if release else None,
        system_secret_versions=system_secret_versions,
    )
    metadata: dict[str, Any] = {}
    personal_values: dict[str, str] = {}
    llm_snapshot = None
    if runtime_context is not None:
        (
            personal_values,
            personal_configured,
            metadata,
            selector.credential_versions,
            selector.credential_secret_versions,
        ) = _personal_credential_runtime_snapshot(
            database,
            settings,
            runtime_context.user_id,
            tool_id,
            context.client.environment_id,
            include_secrets=include_secrets,
            runtime_scope_id=runtime_scope.id if runtime_scope is not None else None,
            allow_incomplete_profiles=runtime_scope is not None,
        )
        configured.update(personal_configured)
        if llm_capability:
            llm_snapshot = resolve_llm_snapshot(
                database,
                settings,
                context.client.environment_id,
                tool_id,
                llm_capability,
                runtime_context.user_id,
                include_secrets=include_secrets,
            )
            selector.llm_capability = llm_capability
            selector.llm_binding_release_id = llm_snapshot["binding_release_id"]
            selector.llm_profile_release_id = llm_snapshot["profile_release_id"]
            selector.llm_secret_version_id = llm_snapshot["api_key_secret_version_id"]
            configured.add("LLM_API_KEY")
    context.client.last_used_at = datetime.now(UTC)
    if set(system_secrets) & set(personal_values):
        raise _runtime_snapshot_invalid()
    if (
        runtime_scope is not None
        and runtime_context is not None
        and runtime_context.allowed_config_refs != [selector.model_dump(mode="json")]
    ):
        raise _runtime_snapshot_invalid()
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return RuntimeConfigResponse(
        tool_id=tool_id,
        environment=context.client.environment_id,
        release_id=release.id if release else None,
        release_version=release.version if release else None,
        normal=normal,
        secrets={**system_secrets, **personal_values},
        credential_metadata=metadata,
        configured_secret_keys=sorted(configured),
        llm=llm_snapshot,
        subject_user_id=runtime_context.user_id if runtime_context else None,
        runtime_context_expires_at=(runtime_context.expires_at if runtime_context else None),
        snapshot_selector=selector,
        runtime_scope_id=runtime_scope.id if runtime_scope is not None else None,
        platform_environment=(runtime_scope.environment_id if runtime_scope is not None else None),
        platform_project_id=(runtime_scope.platform_project_id if runtime_scope is not None else None),
        project_id=(runtime_scope.project_id if runtime_scope is not None else None),
        target_env=(runtime_scope.target_env if runtime_scope is not None else None),
        config_source="platform" if runtime_scope is not None else None,
    )


@router.get("/tools/{tool_id}/runtime-config", response_model=RuntimeConfigResponse)
def runtime_config(
    tool_id: str,
    request: Request,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
    include_secrets: bool = True,
    llm_capability: str | None = None,
    runtime_context_id: str | None = None,
) -> RuntimeConfigResponse:
    """返回工具/环境绑定的配置快照。

    参数说明:
        include_secrets: false 时只返回普通配置和已配置 Secret 键名，供提交前安全读取容量限制。
    """

    _assert_client_scope(context, tool_id)
    _require_capability(context, "config.read")
    if settings.personal_credentials_enabled:
        return _personal_runtime_config(
            tool_id,
            runtime_context_id,
            include_secrets,
            llm_capability,
            request,
            response,
            context,
            database,
            settings,
        )
    environment_id = context.client.environment_id
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == environment_id,
        ConfigActivation.owner_type == "tool",
        ConfigActivation.owner_id == tool_id,
    ))
    normal: dict[str, Any] = {}
    secret_values: dict[str, str] = {}
    configured_secret_keys: set[str] = set()
    release = database.get(ConfigRelease, activation.active_release_id) if activation else None
    definitions = {
        row.id: row for row in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == "tool", ConfigDefinition.owner_id == tool_id,
        )).all()
    }
    if release is not None:
        for item in database.scalars(select(ConfigReleaseItem).where(ConfigReleaseItem.release_id == release.id)).all():
            definition = definitions.get(item.definition_id)
            if definition is None:
                continue
            if definition.sensitivity == "normal":
                normal[definition.key] = item.value_json
            elif item.secret_version_id:
                secret = database.scalar(select(Secret).where(
                    Secret.environment_id == environment_id,
                    Secret.owner_type == "tool",
                    Secret.owner_id == tool_id,
                    Secret.definition_id == definition.id,
                ))
                if secret is not None:
                    configured_secret_keys.add(definition.key)
                    if not include_secrets:
                        continue
                    try:
                        secret_values[definition.key] = decrypt_secret_version(
                            database, load_secret_cipher(settings), secret, item.secret_version_id,
                        )
                    except (ValueError, KeyError):
                        raise PlatformError(503, "SECRET_UNAVAILABLE", "Secret 服务暂时不可用") from None
    for definition in definitions.values():
        if definition.sensitivity == "normal" and definition.key not in normal and definition.default_value is not None:
            normal[definition.key] = definition.default_value
    credentials = list(database.scalars(select(Credential).where(
        Credential.tool_id == tool_id,
        Credential.environment_id == environment_id,
        Credential.current_version > 0,
    ).order_by(Credential.updated_at.desc())).all())
    metadata: dict[str, Any] = {}
    provider_metadata: dict[str, Any] = {}
    # 安全配置查询只返回 Secret 键名，不应加载 KEK 或触碰密文解密路径。
    cipher = load_secret_cipher(settings) if credentials and include_secrets else None
    for credential in credentials:
        credential_items = database.scalars(
            select(CredentialItem).where(
                CredentialItem.credential_id == credential.id,
                CredentialItem.credential_version == credential.current_version,
            )
        ).all()
        for item in credential_items:
            if item.secret_version_id:
                secret_version = database.get(SecretVersion, item.secret_version_id)
                secret = database.get(Secret, secret_version.secret_id) if secret_version else None
                if secret is not None and (secret.environment_id, secret.owner_type, secret.owner_id) == (environment_id, "tool", tool_id):
                    configured_secret_keys.add(item.key)
                    if not include_secrets:
                        continue
                    try:
                        assert cipher is not None
                        secret_values[item.key] = decrypt_secret_version(database, cipher, secret, item.secret_version_id)
                    except (ValueError, KeyError):
                        raise PlatformError(503, "SECRET_UNAVAILABLE", "Secret 服务暂时不可用") from None
            elif credential.provider_type == "gateway_session":
                # 普通会话是工具写回时的主 Credential；仅展开其非敏感元数据，
                # 避免 Admin 的 operator 字段覆盖普通会话上下文。
                metadata[item.key] = item.value_json
        provider_metadata[credential.provider_type] = {
            "credential_id": credential.id,
            "credential_version": credential.current_version,
            "status": credential.status,
            "expires_at": credential.expires_at.isoformat() if credential.expires_at else None,
            "refresh_expires_at": credential.refresh_expires_at.isoformat() if credential.refresh_expires_at else None,
        }
    # 工具现有写回协议必须始终指向普通 Gateway 会话；providers 提供其他
    # Credential 的只读状态，保持响应向后兼容。
    primary = next((row for row in credentials if row.provider_type == "gateway_session"), None)
    if primary is not None:
        metadata.update({
            "credential_id": primary.id,
            "credential_version": primary.current_version,
            "provider_type": primary.provider_type,
            "expires_at": primary.expires_at.isoformat() if primary.expires_at else None,
            "refresh_expires_at": primary.refresh_expires_at.isoformat() if primary.refresh_expires_at else None,
        })
    if provider_metadata:
        metadata["providers"] = provider_metadata
    context.client.last_used_at = datetime.now(UTC)
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    llm_snapshot = None
    if llm_capability:
        llm_snapshot = resolve_legacy_llm_snapshot(
            database, settings, environment_id, tool_id, llm_capability,
            include_secrets=include_secrets,
        )
        if include_secrets:
            configured_secret_keys.add("LLM_API_KEY")
    return RuntimeConfigResponse(
        tool_id=tool_id,
        environment=environment_id,
        release_id=release.id if release else None,
        release_version=release.version if release else None,
        normal=normal,
        secrets=secret_values,
        credential_metadata=metadata,
        configured_secret_keys=sorted(configured_secret_keys),
        llm=llm_snapshot,
    )


@router.post(
    "/tools/{tool_id}/runtime-config/materialize",
    response_model=RuntimeConfigResponse,
)
def materialize_runtime_config(
    tool_id: str,
    payload: RuntimeConfigMaterializeRequest,
    request: Request,
    response: Response,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RuntimeConfigResponse:
    """重新校验 Context 后，按规划选择器物化精确历史版本一次。"""

    _assert_client_scope(context, tool_id)
    _require_capability(context, "config.read")
    if not settings.personal_credentials_enabled:
        raise PlatformError(503, "PERSONAL_CONFIG_DISABLED", "个人运行配置尚未启用")
    runtime_context = validate_runtime_context(
        database, payload.runtime_context_id, context.client, tool_id
    )
    selector = payload.snapshot_selector
    runtime_scope = None
    if tool_id == "api-autotest":
        if (
            not runtime_context.runtime_scope_id
            or selector.runtime_scope_id != runtime_context.runtime_scope_id
        ):
            raise _runtime_snapshot_invalid()
        runtime_scope = database.get(ToolProjectScope, runtime_context.runtime_scope_id)
        if runtime_scope is None or (
            runtime_scope.tool_id, runtime_scope.environment_id,
            runtime_scope.platform_project_id,
        ) != (
            tool_id, context.client.environment_id, runtime_context.project_id_snapshot,
        ):
            raise _runtime_snapshot_invalid()
        if runtime_scope.status != "active":
            raise PlatformError(409, "RUNTIME_SCOPE_DISABLED", "当前 Runtime Scope 已禁用")
        if runtime_context.allowed_config_refs != [selector.model_dump(mode="json")]:
            raise _runtime_snapshot_invalid()
    release = None
    if selector.release_id is not None:
        release = database.get(ConfigRelease, selector.release_id)
        expected_owner = (
            ("tool_project_scope", runtime_scope.id)
            if runtime_scope is not None else ("tool", tool_id)
        )
        if release is None or release.status not in {"active", "superseded"} or (
            release.environment_id,
            release.owner_type,
            release.owner_id,
        ) != (context.client.environment_id, *expected_owner):
            raise _runtime_snapshot_invalid()
    normal, system_secrets, configured, system_secret_versions = _system_runtime_snapshot(
        database,
        settings,
        tool_id,
        context.client.environment_id,
        release,
        include_secrets=True,
        runtime_scope_id=runtime_scope.id if runtime_scope is not None else None,
    )
    if system_secret_versions != selector.system_secret_versions:
        raise _runtime_snapshot_invalid()
    (
        personal_values,
        personal_configured,
        metadata,
        credential_versions,
        credential_secret_versions,
    ) = _personal_credential_runtime_snapshot(
        database,
        settings,
        runtime_context.user_id,
        tool_id,
        context.client.environment_id,
        include_secrets=True,
        selected_versions=selector.credential_versions,
        expected_secret_versions=selector.credential_secret_versions,
        runtime_scope_id=runtime_scope.id if runtime_scope is not None else None,
        allow_incomplete_profiles=runtime_scope is not None,
    )
    if credential_versions != selector.credential_versions:
        raise _runtime_snapshot_invalid()
    configured.update(personal_configured)
    if set(system_secrets) & set(personal_values):
        raise _runtime_snapshot_invalid()

    llm_selector_values = (
        selector.llm_capability,
        selector.llm_binding_release_id,
        selector.llm_profile_release_id,
        selector.llm_secret_version_id,
    )
    llm_snapshot = None
    if any(value is not None for value in llm_selector_values):
        if not all(isinstance(value, str) and value for value in llm_selector_values):
            raise _runtime_snapshot_invalid()
        llm_snapshot = materialize_llm_snapshot(
            database,
            settings,
            context.client.environment_id,
            tool_id,
            selector.llm_capability,
            runtime_context.user_id,
            binding_release_id=selector.llm_binding_release_id,
            profile_release_id=selector.llm_profile_release_id,
            secret_version_id=selector.llm_secret_version_id,
        )
        configured.add("LLM_API_KEY")
    context.client.last_used_at = datetime.now(UTC)
    add_audit_event(
        database,
        action="runtime.config.loaded",
        resource_type="runtime_context",
        resource_id="rtx_hash_" + token_hash(runtime_context.id)[:16],
        tool_id=tool_id,
        environment_id=context.client.environment_id,
        outcome="success",
        request=request,
        actor_type="service",
        actor_id=context.client.id,
        metadata={
            "subject_user_id": runtime_context.user_id,
            "credential_count": len(credential_versions),
            "llm_capability": selector.llm_capability,
        },
    )
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return RuntimeConfigResponse(
        tool_id=tool_id,
        environment=context.client.environment_id,
        release_id=release.id if release else None,
        release_version=release.version if release else None,
        normal=normal,
        secrets={**system_secrets, **personal_values},
        credential_metadata=metadata,
        configured_secret_keys=sorted(configured),
        llm=llm_snapshot,
        subject_user_id=runtime_context.user_id,
        runtime_context_expires_at=runtime_context.expires_at,
        snapshot_selector=selector,
        runtime_scope_id=runtime_scope.id if runtime_scope is not None else None,
        platform_environment=(runtime_scope.environment_id if runtime_scope is not None else None),
        platform_project_id=(runtime_scope.platform_project_id if runtime_scope is not None else None),
        project_id=(runtime_scope.project_id if runtime_scope is not None else None),
        target_env=(runtime_scope.target_env if runtime_scope is not None else None),
        config_source="platform" if runtime_scope is not None else None,
    )


def _validate_dispatch_runtime_context(
    database: Session,
    runtime_context_id: str,
    context: ToolClientContext,
) -> RuntimeContext:
    """在任务真正入队前重新校验并锁定浏览器身份租约。

    普通物化允许已派发任务继续使用既有 Execution Lease；dispatch 则是能力
    真正交付给后台任务的最后边界，必须额外确认原 Session、用户权限版本和
    ``tool.execute`` 仍然有效。锁顺序固定为 RuntimeContext → Tool → User →
    Session，避免与授权变更及用户禁用事务形成循环等待；所有行在同一事务
    中锁定，避免校验通过后、快照提交前发生撤销竞态。

    参数说明:
        database: 当前请求的数据库事务。
        runtime_context_id: 创建任务时签发的不透明 Runtime Context ID。
        context: 已认证的 api-autotest Tool Client 上下文。
    返回值:
        已锁定且通过 dispatch 级身份校验的 RuntimeContext。
    异常说明:
        Context TTL 过期沿用 ``RUNTIME_CONTEXT_EXPIRED``；其余身份、会话或
        权限失效统一返回 ``RUNTIME_CONTEXT_INVALID``，避免暴露具体撤销来源。
    """

    runtime_context = validate_runtime_context(
        database,
        runtime_context_id,
        context.client,
        "api-autotest",
        for_update=True,
    )
    # 全平台授权写路径采用 Tool → User，用户禁用采用 User → Session。
    # dispatch 因此固定使用 Context → Tool → User → Session，既兼容两条既有
    # 写路径，也避免 PostgreSQL 在并发撤销时形成循环锁等待。
    tool = database.scalar(select(Tool).where(
        Tool.id == "api-autotest",
    ).with_for_update().execution_options(populate_existing=True))
    user = database.scalar(select(User).where(
        User.id == runtime_context.user_id,
    ).with_for_update().execution_options(populate_existing=True))
    session = database.scalar(select(PlatformSession).where(
        PlatformSession.id == runtime_context.session_id,
    ).with_for_update().execution_options(populate_existing=True))
    now = datetime.now(UTC)
    access_decision = (
        decide_tool_access(database, user, tool)
        if user is not None and tool is not None
        else None
    )
    invalid_identity = (
        session is None
        or session.user_id != runtime_context.user_id
        or session.revoked_at is not None
        or as_utc(session.idle_expires_at) <= now
        or as_utc(session.absolute_expires_at) <= now
        or user is None
        or user.status != "active"
        or user.permission_version != runtime_context.permission_version
        or tool is None
        or access_decision is None
        or not access_decision.allowed
        or access_decision.source == "public"
        or access_decision.project_id != runtime_context.project_id_snapshot
        or not has_tool_permission(
            database, runtime_context.user_id, "tool.execute", "api-autotest"
        )
    )
    if invalid_identity:
        raise PlatformError(
            403,
            "RUNTIME_CONTEXT_INVALID",
            "用户上下文无效或与工具不匹配",
        )
    return runtime_context


def _runtime_dispatch_credential_unavailable() -> PlatformError:
    """返回排队期间原 Credential 无法继续派发的稳定错误。"""

    return PlatformError(
        409,
        "RUNTIME_DISPATCH_CREDENTIAL_UNAVAILABLE",
        "任务排队期间凭证已失效或版本不可用，请重新提交任务",
    )


def _dispatch_selector_matches_allowed(
    selector: RuntimeSnapshotSelector,
    allowed_config_refs: list[dict[str, Any]] | None,
) -> bool:
    """判断 dispatch 重试是否仍属于 Context 当前冻结的配置身份。

    首次 dispatch 会把 ``allowed_config_refs`` 中的个人 Credential 版本提升到
    当前健康版本。如果响应在工具落盘前丢失，工具只能拿创建任务时的旧
    selector 重试。这里允许旧、当前 selector 的 Credential *版本*不同，但
    Credential ID 集合必须完全相同；Scope、Release、系统 Secret 与 LLM
    选择器仍逐字段等于 Context 当前值。

    参数说明:
        selector: 工具本次提交的旧或当前 selector。
        allowed_config_refs: Runtime Context 当前唯一允许的 selector 列表。
    返回值:
        ``True`` 表示只存在可安全忽略的个人 Credential 版本差异；存储结构
        异常、Credential ID 集合变化或任何非 Credential 字段漂移均返回
        ``False``，由调用方统一失败关闭。
    """

    if not isinstance(allowed_config_refs, list) or len(allowed_config_refs) != 1:
        return False
    try:
        allowed_selector = RuntimeSnapshotSelector.model_validate(
            allowed_config_refs[0]
        )
    except (TypeError, ValueError):
        return False

    submitted = selector.model_dump(mode="json")
    allowed = allowed_selector.model_dump(mode="json")
    submitted_credential_ids = set(submitted["credential_versions"])
    allowed_credential_ids = set(allowed["credential_versions"])
    if (
        set(submitted["credential_secret_versions"])
        != submitted_credential_ids
        or set(allowed["credential_secret_versions"])
        != allowed_credential_ids
        or submitted_credential_ids != allowed_credential_ids
    ):
        return False

    # 个人版本字段由 dispatch 根据数据库当前健康版本重新计算，因此不会信任
    # 调用方的旧值。除此之外的快照身份必须和 Context 当前值完全一致。
    for credential_field in (
        "credential_versions",
        "credential_secret_versions",
    ):
        submitted.pop(credential_field)
        allowed.pop(credential_field)
    return submitted == allowed


@router.post(
    "/tools/api-autotest/runtime-config/dispatch-materialize",
    response_model=RuntimeConfigResponse,
)
def dispatch_materialize_api_autotest_runtime_config(
    payload: RuntimeConfigMaterializeRequest,
    request: Request,
    response: Response,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RuntimeConfigResponse:
    """在任务派发边界刷新原 Credential 集合并原子物化运行快照。

    该入口只把原选择器中已有 Credential ID 提升到各自 ``current_version``；
    Scope、Release、系统 Secret 和 LLM 版本全部保持不变，同 Scope 后来新增的
    Profile 不会进入任务。新选择器仅在完整物化成功后随同审计记录一起提交，
    任一身份、Scope、凭据或 Secret 校验失败都会回滚，Context TTL 也不延长。
    """

    _assert_client_scope(context, "api-autotest")
    _require_capability(context, "config.read")
    if not settings.personal_credentials_enabled:
        raise PlatformError(
            503, "PERSONAL_CONFIG_DISABLED", "个人运行配置尚未启用"
        )
    runtime_context = _validate_dispatch_runtime_context(
        database, payload.runtime_context_id, context
    )
    original_selector = payload.snapshot_selector
    if not _dispatch_selector_matches_allowed(
        original_selector,
        runtime_context.allowed_config_refs,
    ):
        raise _runtime_snapshot_invalid()
    if (
        not runtime_context.runtime_scope_id
        or original_selector.runtime_scope_id != runtime_context.runtime_scope_id
    ):
        raise _runtime_snapshot_invalid()

    runtime_scope = database.scalar(select(ToolProjectScope).where(
        ToolProjectScope.id == runtime_context.runtime_scope_id,
    ).with_for_update())
    if runtime_scope is None or (
        runtime_scope.tool_id,
        runtime_scope.environment_id,
        runtime_scope.platform_project_id,
    ) != (
        "api-autotest",
        context.client.environment_id,
        runtime_context.project_id_snapshot,
    ):
        raise _runtime_snapshot_invalid()
    if runtime_scope.status != "active":
        raise PlatformError(
            409, "RUNTIME_SCOPE_DISABLED", "当前 Runtime Scope 已禁用"
        )

    selected_credential_ids = set(original_selector.credential_versions)
    if set(original_selector.credential_secret_versions) != selected_credential_ids:
        raise _runtime_snapshot_invalid()
    credentials = (
        list(database.scalars(select(UserCredential).where(
            UserCredential.id.in_(selected_credential_ids),
            UserCredential.user_id == runtime_context.user_id,
            UserCredential.tool_id == "api-autotest",
            UserCredential.environment_id == context.client.environment_id,
            UserCredential.runtime_scope_id == runtime_scope.id,
        ).with_for_update()).all())
        if selected_credential_ids
        else []
    )
    if (
        {credential.id for credential in credentials} != selected_credential_ids
        or any(
            credential.status != "healthy" or credential.current_version < 1
            for credential in credentials
        )
    ):
        raise _runtime_dispatch_credential_unavailable()
    refreshed_credential_versions = {
        credential.id: credential.current_version for credential in credentials
    }
    try:
        (
            _personal_values,
            _personal_configured,
            _metadata,
            resolved_credential_versions,
            refreshed_credential_secret_versions,
        ) = _personal_credential_runtime_snapshot(
            database,
            settings,
            runtime_context.user_id,
            "api-autotest",
            context.client.environment_id,
            include_secrets=False,
            selected_versions=refreshed_credential_versions,
            runtime_scope_id=runtime_scope.id,
            allow_incomplete_profiles=True,
        )
    except PlatformError as exc:
        if exc.code == "RUNTIME_SNAPSHOT_INVALID":
            raise _runtime_dispatch_credential_unavailable() from exc
        raise
    if resolved_credential_versions != refreshed_credential_versions:
        raise _runtime_dispatch_credential_unavailable()

    refreshed_selector = original_selector.model_copy(
        deep=True,
        update={
            "credential_versions": refreshed_credential_versions,
            "credential_secret_versions": refreshed_credential_secret_versions,
        },
    )
    runtime_context.allowed_config_refs = [
        refreshed_selector.model_dump(mode="json")
    ]
    # 复用普通精确物化路径完成 Release/System Secret/LLM 校验、Secret 解密、
    # 审计及单次 commit。若其中任一步抛错，本请求事务会整体回滚选择器更新。
    return materialize_runtime_config(
        "api-autotest",
        RuntimeConfigMaterializeRequest(
            runtime_context_id=runtime_context.id,
            snapshot_selector=refreshed_selector,
        ),
        request,
        response,
        context,
        database,
        settings,
    )


@router.post("/tools/{tool_id}/config-ack", response_model=MessageResponse)
def config_ack(
    tool_id: str,
    payload: ConfigAckRequest,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    """记录工具已成功加载的配置版本。"""

    _assert_client_scope(context, tool_id)
    _require_capability(context, "config.ack")
    owner_type = "tool"
    owner_id = tool_id
    if tool_id == "api-autotest":
        if not payload.runtime_context_id:
            raise PlatformError(403, "RUNTIME_CONTEXT_REQUIRED", "确认配置需要 Runtime Context")
        runtime_context = validate_runtime_context(
            database, payload.runtime_context_id, context.client, tool_id
        )
        scope = database.get(ToolProjectScope, runtime_context.runtime_scope_id)
        if scope is None or scope.status != "active":
            raise PlatformError(409, "RUNTIME_SCOPE_DISABLED", "当前 Runtime Scope 不可执行")
        owner_type, owner_id = "tool_project_scope", scope.id
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == context.client.environment_id,
        ConfigActivation.owner_type == owner_type,
        ConfigActivation.owner_id == owner_id,
        ConfigActivation.active_release_id == payload.release_id,
    ))
    if activation is None:
        raise PlatformError(409, "VERSION_CONFLICT", "确认的配置版本不是当前激活版本")
    activation.confirmed_release_id = payload.release_id
    activation.confirmed_at = datetime.now(UTC)
    database.commit()
    return MessageResponse(message="配置版本已确认")


@router.post("/tools/{tool_id}/audit-events", response_model=MessageResponse)
def ingest_audit_event(
    tool_id: str,
    payload: ToolAuditEventRequest,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    """幂等接收工具审计事件，重复 event_id 返回成功且不重复写入。"""

    _assert_client_scope(context, tool_id)
    _require_capability(context, "audit.write")
    if database.get(AuditLog, payload.event_id) is not None:
        return MessageResponse(message="审计事件已接收")
    add_audit_event(
        database, event_id=payload.event_id, action=payload.action,
        resource_type=payload.resource_type, resource_id=payload.resource_id,
        tool_id=tool_id, environment_id=context.client.environment_id,
        outcome=payload.outcome, error_code=payload.error_code,
        actor_type="user" if payload.actor_user_id else "tool",
        actor_id=payload.actor_user_id or context.client.id,
        metadata={**payload.metadata, "actor_username": payload.actor_username or ""},
    )
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
    return MessageResponse(message="审计事件已接收")


@router.post("/tools/{tool_id}/credential-status", response_model=MessageResponse)
def credential_status(
    tool_id: str,
    payload: CredentialStatusRequest,
    request: Request,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MessageResponse:
    """更新不含 Token 的工具凭证健康状态。

    个人模式下，状态只能写入 Runtime Context 所属用户的 Credential，禁止工具
    仅凭 Provider 名称更新全局对象。功能开关关闭时保留旧路径，供尚未升级的
    工具在发布过渡期继续运行。
    """

    _assert_client_scope(context, tool_id)
    _require_capability(context, "credential.status.write")
    if settings.personal_credentials_enabled:
        if not payload.runtime_context_id:
            raise PlatformError(403, "RUNTIME_CONTEXT_REQUIRED", "当前请求缺少可信用户上下文")
        runtime_context = validate_runtime_context(
            database, payload.runtime_context_id, context.client, tool_id
        )
        if tool_id == "api-autotest":
            scope = database.get(ToolProjectScope, runtime_context.runtime_scope_id)
            if scope is None or scope.status != "active":
                raise PlatformError(409, "RUNTIME_SCOPE_DISABLED", "当前 Runtime Scope 不可执行")
        # 所有权是查询的首要条件；跨用户 Provider 与本用户未配置采用同一错误，
        # 不把其他用户的凭证存在性泄露给工具调用方。
        personal_credential = database.scalar(select(UserCredential).where(
            UserCredential.user_id == runtime_context.user_id,
            UserCredential.tool_id == tool_id,
            UserCredential.environment_id == context.client.environment_id,
            UserCredential.runtime_scope_id == runtime_context.runtime_scope_id,
            UserCredential.provider_type == payload.provider_type,
        ).with_for_update())
        if personal_credential is None:
            raise PlatformError(
                409,
                "PERSONAL_CREDENTIAL_NOT_CONFIGURED",
                "请先配置当前工具的个人凭证",
            )
        personal_credential.status = payload.status
        personal_credential.last_error_code = payload.error_code
        personal_credential.last_checked_at = datetime.now(UTC)
        if payload.expires_at:
            personal_credential.expires_at = _parse_credential_expiry(payload.expires_at)
        add_audit_event(
            database,
            action="personal.credential.status",
            resource_type="user_credential",
            resource_id=personal_credential.id,
            tool_id=tool_id,
            environment_id=context.client.environment_id,
            outcome="success",
            request=request,
            actor_type="service",
            actor_id=context.client.id,
            after={
                "provider_type": payload.provider_type,
                "status": payload.status,
                "credential_version": personal_credential.current_version,
            },
            metadata={"subject_user_id": runtime_context.user_id},
        )
        database.commit()
        return MessageResponse(message="个人凭证状态已更新")

    runtime_scope_id = None
    if tool_id == "api-autotest":
        if not payload.runtime_context_id:
            raise PlatformError(403, "RUNTIME_CONTEXT_REQUIRED", "当前请求缺少可信用户上下文")
        scoped_context = validate_runtime_context(
            database, payload.runtime_context_id, context.client, tool_id
        )
        runtime_scope_id = scoped_context.runtime_scope_id
        scope = database.get(ToolProjectScope, runtime_scope_id)
        if scope is None or scope.status != "active":
            raise PlatformError(409, "RUNTIME_SCOPE_DISABLED", "当前 Runtime Scope 不可执行")
    row = database.scalar(select(Credential).where(
        Credential.tool_id == tool_id,
        Credential.environment_id == context.client.environment_id,
        Credential.provider_type == payload.provider_type,
        Credential.runtime_scope_id == runtime_scope_id,
    ))
    if row is None:
        row = Credential(
            id=new_id("cred"), tool_id=tool_id, environment_id=context.client.environment_id,
            runtime_scope_id=runtime_scope_id, provider_type=payload.provider_type,
        )
        database.add(row)
    row.status = payload.status
    row.last_error_code = payload.error_code
    row.last_checked_at = datetime.now(UTC)
    if payload.expires_at:
        row.expires_at = _parse_credential_expiry(payload.expires_at)
    add_audit_event(
        database, action="credential.status", resource_type="credential",
        resource_id=row.id, tool_id=tool_id,
        environment_id=context.client.environment_id,
        outcome="success", request=request,
        actor_type="service", actor_id=context.client.id,
        after={"provider_type": payload.provider_type, "status": payload.status},
    )
    database.commit()
    return MessageResponse(message="凭证状态已更新")


@router.put("/tools/{tool_id}/credentials/{credential_id}/session", response_model=MessageResponse)
def write_credential_session(
    tool_id: str,
    credential_id: str,
    payload: SessionWriteRequest,
    request: Request,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MessageResponse:
    """按 expected_version 原子写回工具会话，避免旧任务覆盖新凭证。"""

    _assert_client_scope(context, tool_id)
    _require_capability(context, "credential.session.write")
    if settings.personal_credentials_enabled:
        # 个人读取开启后绝不能再把动态会话写回 legacy 全局对象，否则一个用户
        # 的刷新结果会重新变成所有用户可见的共享凭证。
        raise PlatformError(
            410,
            "LEGACY_CREDENTIAL_WRITE_DISABLED",
            "旧凭证写入接口已停用，请升级工具",
        )
    credential = database.get(Credential, credential_id)
    runtime_scope_id = None
    if tool_id == "api-autotest":
        if not payload.runtime_context_id:
            raise PlatformError(403, "RUNTIME_CONTEXT_REQUIRED", "当前请求缺少可信用户上下文")
        scoped_context = validate_runtime_context(
            database, payload.runtime_context_id, context.client, tool_id
        )
        runtime_scope_id = scoped_context.runtime_scope_id
    if credential is None or (
        credential.tool_id, credential.environment_id, credential.runtime_scope_id
    ) != (
        tool_id, context.client.environment_id, runtime_scope_id,
    ):
        raise PlatformError(404, "NOT_FOUND", "凭证不存在")
    if credential.current_version != payload.expected_version:
        raise PlatformError(409, "VERSION_CONFLICT", "凭证已被其他任务更新")
    definitions = {
        row.key: row for row in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == "tool",
            ConfigDefinition.owner_id == tool_id,
            ConfigDefinition.sensitivity == "secret",
        )).all()
    }
    metadata_keys = {"expires_time", "refresh_expires_time", "user_id", "operator_id", "operator_name"}
    unknown = set(payload.values) - set(definitions) - metadata_keys
    if unknown:
        raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "凭证包含未登记字段")
    new_version = credential.current_version + 1
    cipher = load_secret_cipher(settings)
    for key, value in payload.values.items():
        if key in metadata_keys:
            database.add(CredentialItem(
                credential_id=credential.id, credential_version=new_version,
                key=key, value_json=value,
            ))
            continue
        if not isinstance(value, str) or not value:
            raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "凭证 Secret 必须是非空字符串")
        definition = definitions[key]
        secret_owner_type = "tool_project_scope" if runtime_scope_id else "tool"
        secret_owner_id = runtime_scope_id or tool_id
        secret = database.scalar(select(Secret).where(
            Secret.environment_id == credential.environment_id,
            Secret.owner_type == secret_owner_type,
            Secret.owner_id == secret_owner_id,
            Secret.definition_id == definition.id,
        ))
        if secret is None:
            secret = Secret(
                id=new_id("sec"), environment_id=credential.environment_id,
                owner_type=secret_owner_type, owner_id=secret_owner_id,
                definition_id=definition.id,
                status="missing",
            )
            database.add(secret)
            database.flush()
        version = replace_secret(database, cipher, secret, value, context.client.id)
        database.flush()
        database.add(CredentialItem(
            credential_id=credential.id, credential_version=new_version,
            key=key, secret_version_id=version.id,
        ))
    credential.current_version = new_version
    if payload.values.get("EXPIRES_TIME") not in (None, ""):
        credential.expires_at = _parse_credential_expiry(payload.values["EXPIRES_TIME"])
    elif payload.values.get("expires_time") not in (None, ""):
        credential.expires_at = _parse_credential_expiry(payload.values["expires_time"])
    if payload.values.get("REFRESH_EXPIRES_TIME") not in (None, ""):
        credential.refresh_expires_at = _parse_credential_expiry(payload.values["REFRESH_EXPIRES_TIME"])
    elif payload.values.get("refresh_expires_time") not in (None, ""):
        credential.refresh_expires_at = _parse_credential_expiry(payload.values["refresh_expires_time"])
    credential.status = "healthy"
    credential.last_error_code = None
    credential.last_checked_at = datetime.now(UTC)
    add_audit_event(
        database, action="credential.session.write", resource_type="credential",
        resource_id=credential.id, tool_id=tool_id,
        environment_id=credential.environment_id,
        outcome="success", request=request,
        actor_type="service", actor_id=context.client.id,
        after={"credential_version": new_version, "status": "healthy"},
    )
    database.commit()
    return MessageResponse(message="凭证会话已原子更新")


@router.put(
    "/tools/{tool_id}/user-credentials/{credential_id}/session",
    response_model=MessageResponse,
)
def write_user_credential_session(
    tool_id: str,
    credential_id: str,
    payload: UserCredentialSessionWriteRequest,
    request: Request,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MessageResponse:
    """按可信用户上下文原子写回个人动态会话。

    参数说明:
        credential_id: 任务快照中属于当前用户的个人 Credential ID。
        payload: Runtime Context、乐观锁版本和需要替换的字段。
    返回值:
        MessageResponse: 整版写入成功后的确认消息。
    异常说明:
        RUNTIME_CONTEXT_INVALID: Context 已失效或跨工具/环境。
        NOT_FOUND: ID 不属于 Context 用户，响应不暴露真实所有者。
        VERSION_CONFLICT: 任务基于的 Credential 已被更新。
    """

    _assert_client_scope(context, tool_id)
    _require_capability(context, "credential.session.write")
    if not settings.personal_credentials_enabled:
        raise PlatformError(404, "NOT_FOUND", "接口不存在")
    runtime_context = validate_runtime_context(
        database, payload.runtime_context_id, context.client, tool_id
    )
    if tool_id == "api-autotest":
        scope = database.get(ToolProjectScope, runtime_context.runtime_scope_id)
        if scope is None or scope.status != "active":
            raise PlatformError(409, "RUNTIME_SCOPE_DISABLED", "当前 Runtime Scope 不可执行")
    # 先限定 Context 用户，再匹配客户端传入 ID，形成统一的 IDOR 防线。
    credential = database.scalar(select(UserCredential).where(
        UserCredential.user_id == runtime_context.user_id,
        UserCredential.id == credential_id,
        UserCredential.tool_id == tool_id,
        UserCredential.environment_id == context.client.environment_id,
        UserCredential.runtime_scope_id == runtime_context.runtime_scope_id,
    ).with_for_update())
    if credential is None:
        raise PlatformError(404, "NOT_FOUND", "个人凭证不存在")
    if credential.current_version != payload.expected_version:
        raise PlatformError(409, "VERSION_CONFLICT", "配置已更新，请刷新后重试")

    definitions = {
        row.key: row
        for row in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == "tool",
            ConfigDefinition.owner_id == tool_id,
            ConfigDefinition.value_scope == "user",
            ConfigDefinition.credential_provider_type == credential.provider_type,
        )).all()
        if not bool(
            (row.validation_schema or {}).get("runtime_config_excluded")
        )
    }
    if not definitions or set(payload.values) - set(definitions):
        raise PlatformError(
            403,
            "CREDENTIAL_SCOPE_MISMATCH",
            "凭证不属于当前用户或工具",
        )

    old_version = credential.current_version
    previous_items = {
        item.key: item
        for item in database.scalars(select(UserCredentialItem).where(
            UserCredentialItem.credential_id == credential.id,
            UserCredentialItem.credential_version == old_version,
        )).all()
    }
    desired_keys = set(previous_items) | set(payload.values)
    if any(row.required and row.key not in desired_keys for row in definitions.values()):
        raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "个人凭证缺少必填字段")

    new_version = old_version + 1
    cipher = None
    for key, definition in definitions.items():
        if key not in desired_keys:
            continue
        if key not in payload.values:
            previous = previous_items[key]
            database.add(UserCredentialItem(
                credential_id=credential.id,
                credential_version=new_version,
                key=key,
                secret_version_id=previous.secret_version_id,
                value_json=previous.value_json,
            ))
            continue

        value = payload.values[key]
        if definition.sensitivity == "secret":
            # Gateway 的过期时间可能是毫秒整数；与旧写回契约保持兼容，但布尔、
            # 容器和空字符串都不是合法 Secret，且统一转成字符串后再加密。
            if (
                isinstance(value, bool)
                or not isinstance(value, (str, int, float))
                or not str(value)
                or len(str(value)) > 65536
            ):
                raise PlatformError(
                    422,
                    "CONFIG_VALIDATION_FAILED",
                    "个人凭证 Secret 必须是非空字符串或数字",
                )
            secret = database.scalar(select(Secret).where(
                Secret.environment_id == credential.environment_id,
                Secret.owner_type == "user_credential",
                Secret.owner_id == credential.id,
                Secret.definition_id == definition.id,
            ))
            if secret is None:
                secret = Secret(
                    id=new_id("sec"),
                    environment_id=credential.environment_id,
                    owner_type="user_credential",
                    owner_id=credential.id,
                    definition_id=definition.id,
                    status="missing",
                )
                database.add(secret)
                database.flush()
            if cipher is None:
                cipher = load_secret_cipher(settings)
            secret_version = replace_secret(
                database, cipher, secret, str(value), runtime_context.user_id
            )
            database.flush()
            database.add(UserCredentialItem(
                credential_id=credential.id,
                credential_version=new_version,
                key=key,
                secret_version_id=secret_version.id,
            ))
        else:
            # 会话写回的普通元数据仍遵循定义类型；避免工具借写回接口注入与定义
            # 不一致的 JSON。完整的长度/范围校验由用户保存 API 负责。
            valid = (
                (definition.value_type in {"string", "url", "logical_path", "enum"} and isinstance(value, str))
                or (definition.value_type == "int" and isinstance(value, int) and not isinstance(value, bool))
                or (definition.value_type == "float" and isinstance(value, (int, float)) and not isinstance(value, bool))
                or (definition.value_type == "bool" and isinstance(value, bool))
                or (definition.value_type == "json" and isinstance(value, (dict, list)))
            )
            if not valid:
                raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "个人凭证字段类型不正确")
            database.add(UserCredentialItem(
                credential_id=credential.id,
                credential_version=new_version,
                key=key,
                value_json=value,
            ))

    if payload.values.get("EXPIRES_TIME") not in (None, ""):
        credential.expires_at = _parse_credential_expiry(payload.values["EXPIRES_TIME"])
    if payload.values.get("REFRESH_EXPIRES_TIME") not in (None, ""):
        credential.refresh_expires_at = _parse_credential_expiry(
            payload.values["REFRESH_EXPIRES_TIME"]
        )
    credential.current_version = new_version
    credential.status = "healthy"
    credential.last_error_code = None
    credential.last_checked_at = datetime.now(UTC)
    add_audit_event(
        database,
        action="personal.credential.session.write",
        resource_type="user_credential",
        resource_id=credential.id,
        tool_id=tool_id,
        environment_id=credential.environment_id,
        outcome="success",
        request=request,
        actor_type="service",
        actor_id=context.client.id,
        before={"credential_version": old_version},
        after={"credential_version": new_version, "status": credential.status},
        metadata={
            "subject_user_id": runtime_context.user_id,
            "provider_type": credential.provider_type,
        },
    )
    database.commit()
    return MessageResponse(message="个人凭证会话已原子更新")
