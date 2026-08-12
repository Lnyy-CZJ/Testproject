from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, ToolClientContext, current_auth_context, current_tool_client
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.core.permissions import required_tool_permission
from app.core.security import new_id
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
)
from app.models.tool import Tool
from app.schemas.auth import MessageResponse
from app.schemas.internal import (
    ConfigAckRequest,
    CredentialStatusRequest,
    RuntimeConfigResponse,
    SessionWriteRequest,
    ToolAuditEventRequest,
)
from app.services.audit import add_audit_event
from app.services.authorization import tool_permissions
from app.services.secret_store import (
    decrypt_secret,
    decrypt_secret_version,
    load_secret_cipher,
    replace_secret,
)


router = APIRouter(prefix="/internal", tags=["internal"])


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
    # 身份 Header 仅由网关根据此响应注入；值移除换行，避免响应头注入。
    safe_username = quote(context.user.username.replace("\r", "").replace("\n", ""), safe="")
    safe_display_name = quote(context.user.display_name.replace("\r", "").replace("\n", ""), safe="")
    return Response(status_code=204, headers={
        "X-Platform-User-ID": context.user.id,
        "X-Platform-Username": safe_username,
        "X-Platform-Display-Name": safe_display_name,
        "X-Platform-Permissions": ",".join(sorted(permissions)),
    })


def _assert_client_scope(context: ToolClientContext, tool_id: str) -> None:
    """拒绝工具 Client 跨工具读取或写入。"""

    if context.client.tool_id != tool_id:
        raise PlatformError(403, "TOOL_CLIENT_FORBIDDEN", "工具身份作用域不匹配")


@router.get("/tools/{tool_id}/runtime-config", response_model=RuntimeConfigResponse)
def runtime_config(
    tool_id: str,
    context: Annotated[ToolClientContext, Depends(current_tool_client)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> RuntimeConfigResponse:
    """返回工具/环境绑定的当前不可变配置与 Secret 快照，禁止缓存。"""

    _assert_client_scope(context, tool_id)
    _require_capability(context, "config.read")
    environment_id = context.client.environment_id
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == environment_id,
        ConfigActivation.owner_type == "tool",
        ConfigActivation.owner_id == tool_id,
    ))
    normal: dict[str, Any] = {}
    secret_values: dict[str, str] = {}
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
    cipher = load_secret_cipher(settings) if credentials else None
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
    return RuntimeConfigResponse(
        tool_id=tool_id,
        environment=environment_id,
        release_id=release.id if release else None,
        release_version=release.version if release else None,
        normal=normal,
        secrets=secret_values,
        credential_metadata=metadata,
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
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == context.client.environment_id,
        ConfigActivation.owner_type == "tool",
        ConfigActivation.owner_id == tool_id,
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
) -> MessageResponse:
    """更新不含 Token 的工具凭证健康状态。"""

    _assert_client_scope(context, tool_id)
    _require_capability(context, "credential.status.write")
    row = database.scalar(select(Credential).where(
        Credential.tool_id == tool_id,
        Credential.environment_id == context.client.environment_id,
        Credential.provider_type == payload.provider_type,
    ))
    if row is None:
        row = Credential(
            id=new_id("cred"), tool_id=tool_id, environment_id=context.client.environment_id,
            provider_type=payload.provider_type,
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
    credential = database.get(Credential, credential_id)
    if credential is None or (credential.tool_id, credential.environment_id) != (
        tool_id, context.client.environment_id,
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
        secret = database.scalar(select(Secret).where(
            Secret.environment_id == credential.environment_id,
            Secret.owner_type == "tool", Secret.owner_id == tool_id,
            Secret.definition_id == definition.id,
        ))
        if secret is None:
            secret = Secret(
                id=new_id("sec"), environment_id=credential.environment_id,
                owner_type="tool", owner_id=tool_id, definition_id=definition.id,
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
