from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, current_auth_context, require_csrf
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.core.security import new_id
from app.db.session import get_db
from app.models.configuration import (
    ConfigActivation,
    ConfigDefinition,
    ConfigRelease,
    ConfigReleaseItem,
    Credential,
    Environment,
    Secret,
    SecretVersion,
)
from app.schemas.auth import MessageResponse
from app.schemas.configuration import (
    ConfigDefinitionResponse,
    CredentialCreateRequest,
    CredentialResponse,
    ReleaseCreateRequest,
    ReleaseItemRequest,
    ReleaseResponse,
    ReleaseUpdateRequest,
    SecretReplaceRequest,
    SecretResponse,
)
from app.services.audit import add_audit_event
from app.services.authorization import has_platform_permission, has_tool_permission
from app.services.secret_store import load_secret_cipher, replace_secret


router = APIRouter(tags=["configuration"])


def _can_manage_config(database: Session, context: AuthContext, owner_type: str, owner_id: str) -> bool:
    """判断用户是否可管理平台或指定工具普通配置。"""

    if owner_type == "platform":
        return has_platform_permission(database, context.user.id, "platform.config.manage")
    return has_tool_permission(database, context.user.id, "tool.config.manage", owner_id)


def _can_manage_secret(database: Session, context: AuthContext, owner_type: str, owner_id: str) -> bool:
    """判断用户是否可管理平台或指定工具 Secret。"""

    if owner_type == "platform":
        return has_platform_permission(database, context.user.id, "platform.secret.manage")
    return has_tool_permission(database, context.user.id, "tool.secret.manage", owner_id)


def _definition_response(row: ConfigDefinition) -> ConfigDefinitionResponse:
    """转换配置定义模型为响应。"""

    return ConfigDefinitionResponse(
        id=row.id, key=row.key, display_name=row.display_name, description=row.description,
        owner_type=row.owner_type, owner_id=row.owner_id, group_key=row.group_key,
        value_type=row.value_type, sensitivity=row.sensitivity, required=row.required,
        default_value=row.default_value if row.sensitivity == "normal" else None,
        validation_schema=row.validation_schema, apply_mode=row.apply_mode,
        editable=row.editable, sort_order=row.sort_order,
    )


def _release_response(database: Session, row: ConfigRelease) -> ReleaseResponse:
    """构造不含 Secret 明文的 Release 响应。"""

    items = list(database.scalars(select(ConfigReleaseItem).where(ConfigReleaseItem.release_id == row.id)).all())
    definitions = {
        definition.id: definition
        for definition in database.scalars(select(ConfigDefinition).where(ConfigDefinition.id.in_([item.definition_id for item in items]))).all()
    } if items else {}
    safe_items = [
        ReleaseItemRequest(
            definition_id=item.definition_id,
            value=item.value_json if definitions[item.definition_id].sensitivity == "normal" else None,
        )
        for item in items
    ]
    return ReleaseResponse(
        id=row.id, environment_id=row.environment_id, owner_type=row.owner_type,
        owner_id=row.owner_id, version=row.version, revision=row.revision,
        status=row.status, created_by=row.created_by, published_by=row.published_by,
        created_at=row.created_at, published_at=row.published_at, items=safe_items,
    )


def _validate_value(definition: ConfigDefinition, value: Any) -> None:
    """按配置定义的基础类型校验普通值。"""

    expected = definition.value_type
    valid = (
        (expected in {"string", "url", "logical_path", "enum"} and isinstance(value, str))
        or (expected == "int" and isinstance(value, int) and not isinstance(value, bool))
        or (expected == "float" and isinstance(value, (int, float)) and not isinstance(value, bool))
        or (expected == "bool" and isinstance(value, bool))
        or (expected == "json" and isinstance(value, (dict, list)))
    )
    if not valid:
        raise PlatformError(422, "CONFIG_VALIDATION_FAILED", f"{definition.display_name} 类型不正确")
    schema = definition.validation_schema or {}
    if isinstance(value, str):
        if schema.get("min_length") is not None and len(value) < int(schema["min_length"]):
            raise PlatformError(422, "CONFIG_VALIDATION_FAILED", f"{definition.display_name} 长度不足")
        if schema.get("max_length") is not None and len(value) > int(schema["max_length"]):
            raise PlatformError(422, "CONFIG_VALIDATION_FAILED", f"{definition.display_name} 长度超限")
        if expected == "url" and not value.startswith(("http://", "https://")):
            raise PlatformError(422, "CONFIG_VALIDATION_FAILED", f"{definition.display_name} 必须是 HTTP(S) URL")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if schema.get("minimum") is not None and value < schema["minimum"]:
            raise PlatformError(422, "CONFIG_VALIDATION_FAILED", f"{definition.display_name} 小于允许值")
        if schema.get("maximum") is not None and value > schema["maximum"]:
            raise PlatformError(422, "CONFIG_VALIDATION_FAILED", f"{definition.display_name} 超过允许值")


@router.get("/config/definitions", response_model=list[ConfigDefinitionResponse])
def list_definitions(
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
    owner_type: str | None = None,
    owner_id: str | None = None,
) -> list[ConfigDefinitionResponse]:
    """返回当前用户有权管理的配置定义。"""

    statement = select(ConfigDefinition).order_by(ConfigDefinition.owner_id, ConfigDefinition.sort_order)
    if owner_type:
        statement = statement.where(ConfigDefinition.owner_type == owner_type)
    if owner_id:
        statement = statement.where(ConfigDefinition.owner_id == owner_id)
    rows = list(database.scalars(statement).all())
    return [
        _definition_response(row)
        for row in rows
        if _can_manage_config(database, context, row.owner_type, row.owner_id)
        or _can_manage_secret(database, context, row.owner_type, row.owner_id)
    ]


@router.get("/config/releases", response_model=list[ReleaseResponse])
def list_releases(
    environment_id: str,
    owner_type: str,
    owner_id: str,
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> list[ReleaseResponse]:
    """返回指定作用域的 Release 历史。"""

    if not _can_manage_config(database, context, owner_type, owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该配置")
    rows = list(database.scalars(select(ConfigRelease).where(
        ConfigRelease.environment_id == environment_id,
        ConfigRelease.owner_type == owner_type,
        ConfigRelease.owner_id == owner_id,
    ).order_by(ConfigRelease.version.desc())).all())
    return [_release_response(database, row) for row in rows]


@router.post("/config/releases", response_model=ReleaseResponse, status_code=201)
def create_release(
    payload: ReleaseCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> ReleaseResponse:
    """从当前激活版本创建新配置草稿。"""

    if not _can_manage_config(database, context, payload.owner_type, payload.owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该配置")
    if database.get(Environment, payload.environment_id) is None:
        raise PlatformError(422, "VALIDATION_ERROR", "配置环境不存在")
    current_version = database.scalar(select(func.max(ConfigRelease.version)).where(
        ConfigRelease.environment_id == payload.environment_id,
        ConfigRelease.owner_type == payload.owner_type,
        ConfigRelease.owner_id == payload.owner_id,
    )) or 0
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == payload.environment_id,
        ConfigActivation.owner_type == payload.owner_type,
        ConfigActivation.owner_id == payload.owner_id,
    ))
    row = ConfigRelease(
        id=new_id("rel"), environment_id=payload.environment_id,
        owner_type=payload.owner_type, owner_id=payload.owner_id,
        version=int(current_version) + 1, revision=1, status="draft",
        based_on_release_id=activation.active_release_id if activation else None,
        created_by=context.user.id,
    )
    database.add(row)
    database.flush()
    if activation:
        old_items = list(database.scalars(select(ConfigReleaseItem).where(ConfigReleaseItem.release_id == activation.active_release_id)).all())
        for item in old_items:
            database.add(ConfigReleaseItem(
                release_id=row.id, definition_id=item.definition_id,
                value_json=item.value_json, secret_version_id=item.secret_version_id,
            ))
    add_audit_event(
        database, action="config.release.create", resource_type="config_release",
        resource_id=row.id, environment_id=row.environment_id,
        tool_id=row.owner_id if row.owner_type == "tool" else None,
        outcome="success", request=request, actor=context.user,
    )
    database.commit()
    return _release_response(database, row)


@router.put("/config/releases/{release_id}/items", response_model=ReleaseResponse)
def update_release(
    release_id: str,
    payload: ReleaseUpdateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> ReleaseResponse:
    """使用 revision 乐观锁替换草稿普通配置项。"""

    row = database.get(ConfigRelease, release_id)
    if row is None:
        raise PlatformError(404, "NOT_FOUND", "配置版本不存在")
    if row.status != "draft":
        raise PlatformError(409, "VERSION_CONFLICT", "只有草稿可以修改")
    if row.revision != payload.revision:
        raise PlatformError(409, "VERSION_CONFLICT", "配置草稿已被其他操作更新")
    if not _can_manage_config(database, context, row.owner_type, row.owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该配置")
    definitions = {
        definition.id: definition
        for definition in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == row.owner_type,
            ConfigDefinition.owner_id == row.owner_id,
        )).all()
    }
    for item in payload.items:
        definition = definitions.get(item.definition_id)
        if definition is None or definition.sensitivity != "normal" or not definition.editable:
            raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "包含不可编辑的配置项")
        _validate_value(definition, item.value)
    before = {item.definition_id: item.value_json for item in database.scalars(select(ConfigReleaseItem).where(ConfigReleaseItem.release_id == row.id)).all() if item.value_json is not None}
    database.execute(delete(ConfigReleaseItem).where(ConfigReleaseItem.release_id == row.id, ConfigReleaseItem.value_json.is_not(None)))
    for item in payload.items:
        database.add(ConfigReleaseItem(release_id=row.id, definition_id=item.definition_id, value_json=item.value))
    row.revision += 1
    add_audit_event(
        database, action="config.release.update", resource_type="config_release", resource_id=row.id,
        environment_id=row.environment_id, tool_id=row.owner_id if row.owner_type == "tool" else None,
        outcome="success", request=request, actor=context.user, before=before,
        after={item.definition_id: item.value for item in payload.items},
    )
    database.commit()
    return _release_response(database, row)


def _validate_release(database: Session, row: ConfigRelease) -> None:
    """验证 Release 普通必填项及作用域内 Secret 是否已配置。"""

    definitions = list(database.scalars(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == row.owner_type,
        ConfigDefinition.owner_id == row.owner_id,
    )).all())
    items = {item.definition_id: item for item in database.scalars(select(ConfigReleaseItem).where(ConfigReleaseItem.release_id == row.id)).all()}
    secrets = {
        secret.definition_id: secret
        for secret in database.scalars(select(Secret).where(
            Secret.environment_id == row.environment_id,
            Secret.owner_type == row.owner_type,
            Secret.owner_id == row.owner_id,
        )).all()
    }
    for definition in definitions:
        if not definition.required:
            continue
        if definition.sensitivity == "secret":
            if definition.id not in secrets or not secrets[definition.id].current_version_id:
                raise PlatformError(422, "CONFIG_VALIDATION_FAILED", f"缺少 Secret：{definition.display_name}")
        elif definition.id not in items and definition.default_value is None:
            raise PlatformError(422, "CONFIG_VALIDATION_FAILED", f"缺少配置：{definition.display_name}")


def _freeze_secret_versions(database: Session, row: ConfigRelease) -> None:
    """将发布时的 Secret 版本引用写入 Release，保证后续运行快照不漂移。"""

    release_items = {
        item.definition_id: item
        for item in database.scalars(select(ConfigReleaseItem).where(
            ConfigReleaseItem.release_id == row.id,
        )).all()
    }
    secrets = database.scalars(select(Secret).where(
        Secret.environment_id == row.environment_id,
        Secret.owner_type == row.owner_type,
        Secret.owner_id == row.owner_id,
        Secret.current_version_id.is_not(None),
    )).all()
    for secret in secrets:
        item = release_items.get(secret.definition_id)
        if item is None:
            database.add(ConfigReleaseItem(
                release_id=row.id,
                definition_id=secret.definition_id,
                secret_version_id=secret.current_version_id,
            ))
        else:
            item.secret_version_id = secret.current_version_id


@router.post("/config/releases/{release_id}/validate", response_model=MessageResponse)
def validate_release(
    release_id: str,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    """验证配置草稿但不改变激活版本。"""

    row = database.get(ConfigRelease, release_id)
    if row is None:
        raise PlatformError(404, "NOT_FOUND", "配置版本不存在")
    if not _can_manage_config(database, context, row.owner_type, row.owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该配置")
    _validate_release(database, row)
    return MessageResponse(message="配置校验通过")


@router.post("/config/releases/{release_id}/publish", response_model=ReleaseResponse)
def publish_release(
    release_id: str,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> ReleaseResponse:
    """验证并原子激活配置 Release。"""

    row = database.get(ConfigRelease, release_id)
    if row is None:
        raise PlatformError(404, "NOT_FOUND", "配置版本不存在")
    if row.status != "draft":
        raise PlatformError(409, "VERSION_CONFLICT", "配置版本不是可发布草稿")
    if not _can_manage_config(database, context, row.owner_type, row.owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该配置")
    _validate_release(database, row)
    _freeze_secret_versions(database, row)
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == row.environment_id,
        ConfigActivation.owner_type == row.owner_type,
        ConfigActivation.owner_id == row.owner_id,
    ))
    old_release_id = activation.active_release_id if activation else None
    if activation is None:
        activation = ConfigActivation(
            environment_id=row.environment_id, owner_type=row.owner_type,
            owner_id=row.owner_id, active_release_id=row.id,
        )
        database.add(activation)
    else:
        activation.active_release_id = row.id
    if old_release_id:
        previous = database.get(ConfigRelease, old_release_id)
        if previous:
            previous.status = "superseded"
    row.status = "active"
    row.published_by = context.user.id
    row.published_at = datetime.now(UTC)
    add_audit_event(
        database, action="config.release.publish", resource_type="config_release", resource_id=row.id,
        environment_id=row.environment_id, tool_id=row.owner_id if row.owner_type == "tool" else None,
        outcome="success", request=request, actor=context.user,
        before={"active_release_id": old_release_id}, after={"active_release_id": row.id},
    )
    database.commit()
    return _release_response(database, row)


@router.post("/config/releases/{release_id}/rollback", response_model=ReleaseResponse)
def rollback_release(
    release_id: str,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> ReleaseResponse:
    """从历史版本复制值并立即创建、激活新的回滚 Release。"""

    source = database.get(ConfigRelease, release_id)
    if source is None:
        raise PlatformError(404, "NOT_FOUND", "配置版本不存在")
    if not _can_manage_config(database, context, source.owner_type, source.owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该配置")
    version = (database.scalar(select(func.max(ConfigRelease.version)).where(
        ConfigRelease.environment_id == source.environment_id,
        ConfigRelease.owner_type == source.owner_type,
        ConfigRelease.owner_id == source.owner_id,
    )) or 0) + 1
    row = ConfigRelease(
        id=new_id("rel"), environment_id=source.environment_id, owner_type=source.owner_type,
        owner_id=source.owner_id, version=version, revision=1, status="draft",
        based_on_release_id=source.id, created_by=context.user.id,
    )
    database.add(row)
    database.flush()
    for item in database.scalars(select(ConfigReleaseItem).where(ConfigReleaseItem.release_id == source.id)).all():
        database.add(ConfigReleaseItem(
            release_id=row.id, definition_id=item.definition_id,
            value_json=item.value_json, secret_version_id=item.secret_version_id,
        ))
    database.flush()
    _validate_release(database, row)
    _freeze_secret_versions(database, row)
    # 复用发布逻辑前先提交会丢失同事务语义，因此在当前事务内直接切换。
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == row.environment_id,
        ConfigActivation.owner_type == row.owner_type,
        ConfigActivation.owner_id == row.owner_id,
    ))
    old = activation.active_release_id if activation else None
    if activation is None:
        activation = ConfigActivation(environment_id=row.environment_id, owner_type=row.owner_type, owner_id=row.owner_id, active_release_id=row.id)
        database.add(activation)
    else:
        activation.active_release_id = row.id
    if old:
        previous = database.get(ConfigRelease, old)
        if previous:
            previous.status = "superseded"
    row.status = "active"
    row.published_by = context.user.id
    row.published_at = datetime.now(UTC)
    add_audit_event(
        database, action="config.release.rollback", resource_type="config_release", resource_id=row.id,
        environment_id=row.environment_id, tool_id=row.owner_id if row.owner_type == "tool" else None,
        outcome="success", request=request, actor=context.user,
        metadata={"source_release_id": source.id, "previous_active_release_id": old},
    )
    database.commit()
    return _release_response(database, row)


@router.post("/config/releases/{release_id}/promote", response_model=ReleaseResponse, status_code=201)
def promote_release(
    release_id: str,
    target_environment: str,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> ReleaseResponse:
    """把普通配置复制为目标环境草稿；Secret 明确不跨环境复制。"""

    source = database.get(ConfigRelease, release_id)
    if source is None:
        raise PlatformError(404, "NOT_FOUND", "配置版本不存在")
    if target_environment == source.environment_id:
        raise PlatformError(422, "VALIDATION_ERROR", "目标环境必须与来源环境不同")
    if database.get(Environment, target_environment) is None:
        raise PlatformError(422, "VALIDATION_ERROR", "目标环境不存在")
    if not _can_manage_config(database, context, source.owner_type, source.owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该配置")
    version = (database.scalar(select(func.max(ConfigRelease.version)).where(
        ConfigRelease.environment_id == target_environment,
        ConfigRelease.owner_type == source.owner_type,
        ConfigRelease.owner_id == source.owner_id,
    )) or 0) + 1
    row = ConfigRelease(
        id=new_id("rel"), environment_id=target_environment,
        owner_type=source.owner_type, owner_id=source.owner_id,
        version=version, revision=1, status="draft",
        based_on_release_id=source.id, created_by=context.user.id,
    )
    database.add(row)
    database.flush()
    definitions = {
        definition.id: definition
        for definition in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == source.owner_type,
            ConfigDefinition.owner_id == source.owner_id,
        )).all()
    }
    for item in database.scalars(select(ConfigReleaseItem).where(
        ConfigReleaseItem.release_id == source.id,
        ConfigReleaseItem.value_json.is_not(None),
    )).all():
        definition = definitions.get(item.definition_id)
        if definition is not None and definition.sensitivity == "normal":
            database.add(ConfigReleaseItem(
                release_id=row.id, definition_id=item.definition_id,
                value_json=item.value_json,
            ))
    add_audit_event(
        database, action="config.release.promote", resource_type="config_release",
        resource_id=row.id, environment_id=target_environment,
        tool_id=row.owner_id if row.owner_type == "tool" else None,
        outcome="success", request=request, actor=context.user,
        metadata={"source_release_id": source.id, "source_environment": source.environment_id},
    )
    database.commit()
    return _release_response(database, row)


def _secret_response(database: Session, row: Secret) -> SecretResponse:
    """构造不包含密文或明文的 Secret 元数据响应。"""

    version = database.get(SecretVersion, row.current_version_id) if row.current_version_id else None
    return SecretResponse(
        id=row.id, environment_id=row.environment_id, owner_type=row.owner_type,
        owner_id=row.owner_id, definition_id=row.definition_id,
        configured=version is not None, status=row.status,
        version=version.version if version else None,
        expires_at=version.expires_at if version else None, updated_at=row.updated_at,
    )


@router.get("/secrets", response_model=list[SecretResponse])
def list_secrets(
    environment_id: str,
    owner_type: str,
    owner_id: str,
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> list[SecretResponse]:
    """列出有权管理作用域的 Secret 元数据。"""

    if not _can_manage_secret(database, context, owner_type, owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该 Secret")
    rows = list(database.scalars(select(Secret).where(
        Secret.environment_id == environment_id,
        Secret.owner_type == owner_type,
        Secret.owner_id == owner_id,
    ).order_by(Secret.definition_id)).all())
    return [_secret_response(database, row) for row in rows]


@router.put("/secrets/{secret_id}", response_model=SecretResponse)
def put_secret(
    secret_id: str,
    payload: SecretReplaceRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SecretResponse:
    """加密保存并激活 Secret 新版本，响应永不回显明文。"""

    if not _can_manage_secret(database, context, payload.owner_type, payload.owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该 Secret")
    if database.get(Environment, payload.environment_id) is None:
        raise PlatformError(422, "VALIDATION_ERROR", "配置环境不存在")
    definition = database.get(ConfigDefinition, payload.definition_id)
    if definition is None or definition.sensitivity != "secret":
        raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "Secret 定义无效")
    if (definition.owner_type, definition.owner_id) != (payload.owner_type, payload.owner_id):
        raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "Secret 作用域不匹配")
    row = database.get(Secret, secret_id)
    if row is None:
        row = Secret(
            id=secret_id, environment_id=payload.environment_id, owner_type=payload.owner_type,
            owner_id=payload.owner_id, definition_id=payload.definition_id, status="missing",
        )
        database.add(row)
        database.flush()
    elif (row.environment_id, row.owner_type, row.owner_id, row.definition_id) != (
        payload.environment_id, payload.owner_type, payload.owner_id, payload.definition_id
    ):
        raise PlatformError(409, "VERSION_CONFLICT", "Secret 标识已用于其他作用域")
    version = replace_secret(database, load_secret_cipher(settings), row, payload.value, context.user.id, payload.expires_at)
    add_audit_event(
        database, action="secret.replace", resource_type="secret", resource_id=row.id,
        environment_id=row.environment_id, tool_id=row.owner_id if row.owner_type == "tool" else None,
        outcome="success", request=request, actor=context.user,
        after={"version": version.version, "status": row.status},
    )
    database.commit()
    database.refresh(row)
    return _secret_response(database, row)


@router.get("/credentials", response_model=list[CredentialResponse])
def list_credentials(
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
    environment_id: str | None = None,
) -> list[CredentialResponse]:
    """返回当前用户有 Secret 管理权限的凭证状态。"""

    statement = select(Credential).order_by(Credential.environment_id, Credential.tool_id)
    if environment_id:
        statement = statement.where(Credential.environment_id == environment_id)
    rows = [row for row in database.scalars(statement).all() if _can_manage_secret(database, context, "tool", row.tool_id)]
    return [CredentialResponse(
        id=row.id, tool_id=row.tool_id, environment_id=row.environment_id,
        provider_type=row.provider_type, status=row.status, current_version=row.current_version,
        expires_at=row.expires_at, refresh_expires_at=row.refresh_expires_at,
        last_error_code=row.last_error_code, last_checked_at=row.last_checked_at,
    ) for row in rows]


@router.post("/credentials", response_model=CredentialResponse, status_code=201)
def create_credential(
    payload: CredentialCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> CredentialResponse:
    """创建凭证生命周期记录，不复制或回显任何 Secret 明文。"""

    if not _can_manage_secret(database, context, "tool", payload.tool_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该凭证")
    if database.get(Environment, payload.environment_id) is None:
        raise PlatformError(422, "VALIDATION_ERROR", "配置环境不存在")
    existing = database.scalar(select(Credential).where(
        Credential.tool_id == payload.tool_id,
        Credential.environment_id == payload.environment_id,
        Credential.provider_type == payload.provider_type,
    ))
    if existing is not None:
        raise PlatformError(409, "VERSION_CONFLICT", "该凭证已存在")
    row = Credential(
        id=new_id("cred"), tool_id=payload.tool_id,
        environment_id=payload.environment_id,
        provider_type=payload.provider_type, status="pending_validation",
    )
    database.add(row)
    add_audit_event(
        database, action="credential.create", resource_type="credential", resource_id=row.id,
        tool_id=row.tool_id, environment_id=row.environment_id, outcome="success",
        request=request, actor=context.user, after={"provider_type": row.provider_type, "status": row.status},
    )
    database.commit()
    database.refresh(row)
    return CredentialResponse(
        id=row.id, tool_id=row.tool_id, environment_id=row.environment_id,
        provider_type=row.provider_type, status=row.status,
        current_version=row.current_version, expires_at=row.expires_at,
        refresh_expires_at=row.refresh_expires_at, last_error_code=row.last_error_code,
        last_checked_at=row.last_checked_at,
    )
