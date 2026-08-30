from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
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
    ToolProjectScope,
    UserCredential,
    UserCredentialItem,
)
from app.models.llm import LlmProfile, ToolLlmBinding
from app.schemas.auth import MessageResponse
from app.schemas.configuration import (
    ConfigDefinitionResponse,
    CredentialCreateRequest,
    CredentialResponse,
    PersonalCredentialFieldResponse,
    PersonalCredentialPutRequest,
    PersonalCredentialResponse,
    PersonalCredentialValidationResponse,
    ReleaseCreateRequest,
    ReleaseItemRequest,
    ReleaseResponse,
    ReleaseUpdateRequest,
    SecretReplaceRequest,
    SecretResponse,
    RuntimeScopeCreateRequest,
    RuntimeScopePatchRequest,
    RuntimeScopeResponse,
)
from app.models.access import Project, ProjectMembership
from app.models.tool import Tool
from app.services.audit import add_audit_event
from app.services.authorization import decide_tool_access, has_platform_permission, has_tool_permission
from app.services.secret_store import load_secret_cipher, replace_secret


router = APIRouter(tags=["configuration"])


def _scope_owner(database: Session, owner_type: str, owner_id: str) -> ToolProjectScope | None:
    """解析 scoped owner；非 Scope owner 返回 None，缺失 Scope 由调用方失败关闭。"""

    if owner_type != "tool_project_scope":
        return None
    return database.get(ToolProjectScope, owner_id)


def _owner_tool_id(database: Session, owner_type: str, owner_id: str) -> str | None:
    """返回配置 owner 对应的真实 Tool ID，供 Definition 和审计统一使用。"""

    if owner_type == "tool":
        return owner_id
    scope = _scope_owner(database, owner_type, owner_id)
    return scope.tool_id if scope is not None else None


def _owner_definitions(database: Session, owner_type: str, owner_id: str) -> list[ConfigDefinition]:
    """读取 owner 可用 Definition；Scope 始终复用其 Tool 级契约。"""

    tool_id = _owner_tool_id(database, owner_type, owner_id)
    if owner_type == "tool_project_scope":
        if tool_id is None:
            return []
        owner_type, owner_id = "tool", tool_id
    return list(database.scalars(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == owner_type,
        ConfigDefinition.owner_id == owner_id,
    )).all())


def _definition_applies_to_owner(
    database: Session,
    definition: ConfigDefinition,
    owner_type: str,
    owner_id: str,
) -> bool:
    """判断 Tool 级配置定义是否适用于当前项目 Scope。

    ``project_ids`` 是配置契约中的服务端白名单。没有声明该字段的旧定义继续
    对 Tool 下所有项目生效；声明后则只允许列出的 ``project_id`` 使用，避免
    Dating 草稿意外写入 Truthy Admin 地址等项目专属配置。
    """

    if owner_type != "tool_project_scope":
        return True
    scope = _scope_owner(database, owner_type, owner_id)
    if scope is None:
        return False
    project_ids = (definition.validation_schema or {}).get("project_ids")
    if project_ids is None:
        return True
    return isinstance(project_ids, list) and scope.project_id in project_ids


def _assert_scope_environment(
    database: Session, owner_type: str, owner_id: str, environment_id: str
) -> ToolProjectScope | None:
    """验证 scoped owner 与请求环境一致，阻断跨环境借用相同 Scope ID。"""

    scope = _scope_owner(database, owner_type, owner_id)
    if owner_type == "tool_project_scope" and (
        scope is None or scope.environment_id != environment_id
    ):
        raise PlatformError(422, "CONFIG_SCOPE_MISMATCH", "配置作用域与环境不匹配")
    return scope


def _runtime_scope_response(row: ToolProjectScope) -> RuntimeScopeResponse:
    """转换 Scope 元数据，同时显式暴露 platform_environment 外部契约。"""

    return RuntimeScopeResponse(
        id=row.id, environment_id=row.environment_id,
        platform_environment=row.environment_id, tool_id=row.tool_id,
        platform_project_id=row.platform_project_id, project_id=row.project_id,
        target_env=row.target_env, display_name=row.display_name, status=row.status,
        is_default=row.is_default, revision=row.revision,
        created_by=row.created_by, updated_by=row.updated_by,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def _can_manage_runtime_scope(
    database: Session,
    context: AuthContext,
    scope: ToolProjectScope,
    *,
    platform_permission: str,
    tool_permission: str,
) -> bool:
    """叠加 Tool 权限与平台项目 manager 关系，阻断跨平台项目管理同一 Tool。"""

    if has_platform_permission(database, context.user.id, platform_permission):
        return True
    if not has_tool_permission(database, context.user.id, tool_permission, scope.tool_id):
        return False
    membership = database.get(
        ProjectMembership, (scope.platform_project_id, context.user.id)
    )
    return membership is not None and membership.relation == "manager"


def _can_use_runtime_scope(
    database: Session, context: AuthContext, scope: ToolProjectScope
) -> bool:
    """确认个人 Credential 的 Scope 属于当前用户访问决策中的平台项目。"""

    tool = database.get(Tool, scope.tool_id)
    if tool is None or not has_tool_permission(
        database, context.user.id, "tool.execute", scope.tool_id
    ):
        return False
    if context.user.platform_role is None:
        return tool.project_id == scope.platform_project_id
    decision = decide_tool_access(database, context.user, tool)
    return decision.allowed and decision.project_id == scope.platform_project_id


def _can_manage_config(database: Session, context: AuthContext, owner_type: str, owner_id: str) -> bool:
    """判断用户是否可管理平台或指定工具普通配置。"""

    if owner_type == "platform":
        return has_platform_permission(database, context.user.id, "platform.config.manage")
    if owner_type == "tool_project_scope":
        scope = database.get(ToolProjectScope, owner_id)
        return scope is not None and _can_manage_runtime_scope(
            database, context, scope,
            platform_permission="platform.config.manage",
            tool_permission="tool.config.manage",
        )
    if owner_type == "llm_profile":
        # 通用配置 API 是 legacy 公共 LLM 管理面。个人 Profile 即使由平台
        # 管理员本人创建，也只能通过 /me/llm 修改，避免绕开所有者校验。
        profile = database.get(LlmProfile, owner_id)
        return (
            profile is not None
            and profile.owner_user_id is None
            and has_platform_permission(database, context.user.id, "platform.llm.manage")
        )
    if owner_type == "llm_binding":
        binding = database.get(ToolLlmBinding, owner_id)
        return binding is not None and (
            has_platform_permission(database, context.user.id, "platform.llm.manage")
            or has_tool_permission(database, context.user.id, "tool.config.manage", binding.tool_id)
        )
    return has_tool_permission(database, context.user.id, "tool.config.manage", owner_id)


def _can_manage_secret(database: Session, context: AuthContext, owner_type: str, owner_id: str) -> bool:
    """判断用户是否可管理平台或指定工具 Secret。"""

    if owner_type == "platform":
        return has_platform_permission(database, context.user.id, "platform.secret.manage")
    if owner_type == "tool_project_scope":
        scope = database.get(ToolProjectScope, owner_id)
        return scope is not None and _can_manage_runtime_scope(
            database, context, scope,
            platform_permission="platform.secret.manage",
            tool_permission="tool.secret.manage",
        )
    if owner_type == "llm_profile":
        # 个人 API Key 不进入公共 Secret 管理路径；该限制同时覆盖枚举、替换
        # 与 Release 操作，避免管理员权限意外扩大成跨用户 Secret 权限。
        profile = database.get(LlmProfile, owner_id)
        return (
            profile is not None
            and profile.owner_user_id is None
            and has_platform_permission(
                database, context.user.id, "platform.llm.secret.manage"
            )
        )
    if owner_type == "llm_binding":
        binding = database.get(ToolLlmBinding, owner_id)
        return binding is not None and (
            has_platform_permission(database, context.user.id, "platform.llm.secret.manage")
            or has_tool_permission(database, context.user.id, "tool.secret.manage", binding.tool_id)
        )
    return has_tool_permission(database, context.user.id, "tool.secret.manage", owner_id)


def _definition_response(row: ConfigDefinition) -> ConfigDefinitionResponse:
    """转换配置定义模型为响应。"""

    return ConfigDefinitionResponse(
        id=row.id, key=row.key, display_name=row.display_name, description=row.description,
        owner_type=row.owner_type, owner_id=row.owner_id, group_key=row.group_key,
        value_type=row.value_type, sensitivity=row.sensitivity, required=row.required,
        default_value=row.default_value if row.sensitivity == "normal" else None,
        validation_schema=row.validation_schema, apply_mode=row.apply_mode,
        editable=row.editable, sort_order=row.sort_order, value_scope=row.value_scope,
        credential_provider_type=row.credential_provider_type,
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
    """按配置定义校验普通值，并约束 JSON 中可持久化的静态字段。

    JSON 对象的动态字段黑名单由平台契约控制。校验错误只返回字段名，不回显
    用户提交的值，避免配置值意外进入接口错误日志。
    """

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
    if isinstance(value, dict):
        required_keys = schema.get("required_keys") or []
        missing_keys = [
            key for key in required_keys
            if key not in value or value[key] is None or value[key] == ""
        ]
        if missing_keys:
            raise PlatformError(
                422,
                "CONFIG_VALIDATION_FAILED",
                f"{definition.display_name} 缺少必填字段：{', '.join(missing_keys)}",
            )

        forbidden_keys = set(schema.get("forbidden_keys") or [])
        invalid_keys = sorted(forbidden_keys.intersection(value))
        if invalid_keys:
            raise PlatformError(
                422,
                "CONFIG_VALIDATION_FAILED",
                f"{definition.display_name} 包含运行时动态字段：{', '.join(invalid_keys)}",
            )

        max_properties = schema.get("max_properties")
        if max_properties is not None and len(value) > int(max_properties):
            raise PlatformError(
                422,
                "CONFIG_VALIDATION_FAILED",
                f"{definition.display_name} 字段数量超过限制",
            )

        property_pattern = schema.get("property_name_pattern")
        if property_pattern:
            invalid_names = sorted(
                str(key) for key in value if re.fullmatch(str(property_pattern), str(key)) is None
            )
            if invalid_names:
                raise PlatformError(
                    422,
                    "CONFIG_VALIDATION_FAILED",
                    f"{definition.display_name} 字段名不合法：{', '.join(invalid_names)}",
                )

        if schema.get("string_values"):
            non_string_keys = sorted(str(key) for key, item in value.items() if not isinstance(item, str))
            if non_string_keys:
                raise PlatformError(
                    422,
                    "CONFIG_VALIDATION_FAILED",
                    f"{definition.display_name} 字段必须使用字符串值：{', '.join(non_string_keys)}",
                )


def _personal_credential_definitions(
    database: Session,
    tool_id: str,
    provider_type: str,
) -> list[ConfigDefinition]:
    """返回某工具 Provider 明确声明为用户级的字段白名单。

    Provider 归属来自服务端配置定义，而不是请求体。这样即使客户端提交了
    legacy 系统 Secret 的键名，也不会被写入个人作用域或绕过字段分类。
    """

    definitions = list(database.scalars(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == "tool",
        ConfigDefinition.owner_id == tool_id,
        ConfigDefinition.value_scope == "user",
        ConfigDefinition.credential_provider_type == provider_type,
    ).order_by(ConfigDefinition.sort_order, ConfigDefinition.key)).all())
    return [
        definition
        for definition in definitions
        if not (definition.validation_schema or {}).get("runtime_config_excluded")
    ]


def _personal_credential_response(
    database: Session,
    row: UserCredential,
    definitions: list[ConfigDefinition] | None = None,
) -> PersonalCredentialResponse:
    """构造只含元数据的个人凭证响应，绝不计算可反推 Secret 的摘要。"""

    resolved_definitions = definitions or _personal_credential_definitions(
        database, row.tool_id, row.provider_type
    )
    configured_keys = {
        item.key
        for item in database.scalars(select(UserCredentialItem).where(
            UserCredentialItem.credential_id == row.id,
            UserCredentialItem.credential_version == row.current_version,
        )).all()
    }
    return PersonalCredentialResponse(
        id=row.id,
        tool_id=row.tool_id,
        environment_id=row.environment_id,
        runtime_scope_id=row.runtime_scope_id,
        provider_type=row.provider_type,
        status=row.status,
        current_version=row.current_version,
        expires_at=row.expires_at,
        refresh_expires_at=row.refresh_expires_at,
        last_checked_at=row.last_checked_at,
        last_error_code=row.last_error_code,
        fields=[
            PersonalCredentialFieldResponse(
                key=definition.key,
                display_name=definition.display_name,
                required=definition.required,
                configured=definition.key in configured_keys,
            )
            for definition in resolved_definitions
        ],
    )


def _parse_personal_credential_expiry(value: Any) -> datetime:
    """把用户提交的毫秒时间戳或 ISO 时间统一转换为 UTC。"""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value) / 1000, UTC)
        except (ValueError, OverflowError, OSError):
            pass
    if isinstance(value, str) and value.strip():
        normalized = value.strip()
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(normalized) / 1000, UTC)
            except (ValueError, OverflowError, OSError):
                pass
    raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "凭证过期时间格式不正确")


def _require_personal_credential_write(settings: Settings) -> None:
    """在分阶段发布期间关闭个人凭证的所有主动操作。"""

    if not settings.personal_credentials_write_enabled:
        raise PlatformError(
            503,
            "PERSONAL_CREDENTIAL_WRITE_DISABLED",
            "个人凭证写入功能暂未开放",
        )


@router.get("/me/credentials", response_model=list[PersonalCredentialResponse])
def list_personal_credentials(
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
    response: Response,
    environment_id: str | None = None,
    runtime_scope_id: str | None = None,
) -> list[PersonalCredentialResponse]:
    """列出当前登录用户有执行权限的个人凭证元数据。

    查询的第一个所有权条件固定为认证用户 ID；后续工具权限过滤用于处理角色
    被收回的情况。返回值不包含 Secret、长度、掩码或跨用户资源标识。
    """

    statement = select(UserCredential).where(
        UserCredential.user_id == context.user.id,
    )
    if environment_id:
        statement = statement.where(UserCredential.environment_id == environment_id)
    if runtime_scope_id:
        statement = statement.where(UserCredential.runtime_scope_id == runtime_scope_id)
    rows = list(database.scalars(statement.order_by(
        UserCredential.environment_id,
        UserCredential.tool_id,
        UserCredential.provider_type,
    )).all())
    response.headers["Cache-Control"] = "no-store"
    return [
        _personal_credential_response(database, row)
        for row in rows
        if has_tool_permission(database, context.user.id, "tool.execute", row.tool_id)
        and (
            row.runtime_scope_id is None
            or (
                (scope := database.get(ToolProjectScope, row.runtime_scope_id)) is not None
                and _can_use_runtime_scope(database, context, scope)
            )
        )
    ]


@router.put(
    "/me/credentials/{tool_id}/{provider_type}",
    response_model=PersonalCredentialResponse,
)
def put_personal_credential(
    tool_id: str,
    provider_type: str,
    payload: PersonalCredentialPutRequest,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PersonalCredentialResponse:
    """使用乐观锁原子保存当前用户的一版个人凭证。

    未提交字段只从同一 Credential 的当前版本复制；Secret 明文只在本次请求
    内存中进入信封加密函数。任一字段失败时整个事务回滚，不会激活半个版本。
    """

    _require_personal_credential_write(settings)
    if not has_tool_permission(database, context.user.id, "tool.execute", tool_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权配置该工具的个人凭证")
    environment = database.get(Environment, payload.environment_id)
    if environment is None or not environment.is_active:
        raise PlatformError(422, "VALIDATION_ERROR", "配置环境不存在或不可用")
    runtime_scope = (
        database.get(ToolProjectScope, payload.runtime_scope_id)
        if payload.runtime_scope_id else None
    )
    if tool_id == "api-autotest" and runtime_scope is None:
        raise PlatformError(422, "RUNTIME_SCOPE_REQUIRED", "api-autotest 凭证必须绑定 Runtime Scope")
    if runtime_scope is not None and (
        runtime_scope.tool_id, runtime_scope.environment_id
    ) != (tool_id, payload.environment_id):
        raise PlatformError(422, "CREDENTIAL_SCOPE_MISMATCH", "凭证与 Runtime Scope 不匹配")
    if runtime_scope is not None and not _can_use_runtime_scope(
        database, context, runtime_scope
    ):
        raise PlatformError(403, "PERMISSION_DENIED", "无权配置该 Runtime Scope 的个人凭证")

    definitions = _personal_credential_definitions(database, tool_id, provider_type)
    definitions_by_key = {definition.key: definition for definition in definitions}
    if not definitions or set(payload.values) - set(definitions_by_key):
        raise PlatformError(
            403,
            "CREDENTIAL_SCOPE_MISMATCH",
            "凭证字段不属于当前用户、工具或 Provider",
        )

    # 所有权条件放在查询首位；即使攻击者知道另一用户的同作用域对象，也只会
    # 在自己的范围内得到“尚未创建”，绝不会加载或复制对方的当前版本。
    row = database.scalar(select(UserCredential).where(
        UserCredential.user_id == context.user.id,
        UserCredential.tool_id == tool_id,
        UserCredential.environment_id == payload.environment_id,
        UserCredential.runtime_scope_id == payload.runtime_scope_id,
        UserCredential.provider_type == provider_type,
    ).with_for_update())
    old_version = row.current_version if row is not None else 0
    if payload.expected_version != old_version:
        raise PlatformError(409, "VERSION_CONFLICT", "配置已更新，请刷新后重试")

    previous_items = {
        item.key: item
        for item in database.scalars(select(UserCredentialItem).where(
            UserCredentialItem.credential_id == row.id,
            UserCredentialItem.credential_version == old_version,
        )).all()
    } if row is not None and old_version > 0 else {}
    desired_keys = set(previous_items) | set(payload.values)
    missing_required = [
        definition.key
        for definition in definitions
        if definition.required and definition.key not in desired_keys
    ]
    if missing_required:
        raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "个人凭证缺少必填字段")

    created = row is None
    if row is None:
        row = UserCredential(
            id=new_id("ucred"),
            user_id=context.user.id,
            tool_id=tool_id,
            environment_id=payload.environment_id,
            runtime_scope_id=payload.runtime_scope_id,
            provider_type=provider_type,
            status="missing",
            current_version=0,
        )
        database.add(row)
        try:
            # 尽早触发唯一约束，避免两个首次写入请求都继续创建 Secret。
            database.flush()
        except IntegrityError:
            database.rollback()
            raise PlatformError(409, "VERSION_CONFLICT", "配置已更新，请刷新后重试") from None

    new_version = old_version + 1
    cipher = None
    for definition in definitions:
        if definition.key not in desired_keys:
            continue
        if definition.key not in payload.values:
            previous = previous_items[definition.key]
            database.add(UserCredentialItem(
                credential_id=row.id,
                credential_version=new_version,
                key=definition.key,
                secret_version_id=previous.secret_version_id,
                value_json=previous.value_json,
            ))
            continue

        value = payload.values[definition.key]
        if definition.sensitivity == "secret":
            if not isinstance(value, str) or not value or len(value) > 65536:
                raise PlatformError(
                    422,
                    "CONFIG_VALIDATION_FAILED",
                    "个人凭证 Secret 必须是非空字符串",
                )
            secret = database.scalar(select(Secret).where(
                Secret.environment_id == row.environment_id,
                Secret.owner_type == "user_credential",
                Secret.owner_id == row.id,
                Secret.definition_id == definition.id,
            ))
            if secret is None:
                secret = Secret(
                    id=new_id("sec"),
                    environment_id=row.environment_id,
                    owner_type="user_credential",
                    owner_id=row.id,
                    definition_id=definition.id,
                    status="missing",
                )
                database.add(secret)
                database.flush()
            if cipher is None:
                cipher = load_secret_cipher(settings)
            secret_version = replace_secret(
                database, cipher, secret, value, context.user.id
            )
            database.flush()
            database.add(UserCredentialItem(
                credential_id=row.id,
                credential_version=new_version,
                key=definition.key,
                secret_version_id=secret_version.id,
            ))
        else:
            _validate_value(definition, value)
            database.add(UserCredentialItem(
                credential_id=row.id,
                credential_version=new_version,
                key=definition.key,
                value_json=value,
            ))

    if payload.values.get("EXPIRES_TIME") not in (None, ""):
        row.expires_at = _parse_personal_credential_expiry(payload.values["EXPIRES_TIME"])
    if payload.values.get("REFRESH_EXPIRES_TIME") not in (None, ""):
        row.refresh_expires_at = _parse_personal_credential_expiry(
            payload.values["REFRESH_EXPIRES_TIME"]
        )
    row.current_version = new_version
    row.status = "pending_validation"
    row.last_checked_at = None
    row.last_error_code = None
    add_audit_event(
        database,
        action="personal.credential.create" if created else "personal.credential.replace",
        resource_type="user_credential",
        resource_id=row.id,
        tool_id=row.tool_id,
        environment_id=row.environment_id,
        outcome="success",
        request=request,
        actor=context.user,
        after={
            "provider_type": row.provider_type,
            "credential_version": new_version,
            "status": row.status,
        },
    )
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _personal_credential_response(database, row, definitions)


@router.post(
    "/me/credentials/{credential_id}/validate",
    response_model=PersonalCredentialValidationResponse,
)
def validate_personal_credential(
    credential_id: str,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PersonalCredentialValidationResponse:
    """请求验证当前用户自己的 Credential。

    当前后端没有可复用且不轮换凭证的 Provider 校验器，因此明确返回
    ``unsupported``。这比把“已接收请求”误报为连接成功更安全；后续接入专用
    校验器时可保持响应契约不变。
    """

    _require_personal_credential_write(settings)
    row = database.scalar(select(UserCredential).where(
        UserCredential.user_id == context.user.id,
        UserCredential.id == credential_id,
    ))
    if row is None:
        raise PlatformError(404, "NOT_FOUND", "个人凭证不存在")
    if not has_tool_permission(database, context.user.id, "tool.execute", row.tool_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权验证该工具的个人凭证")
    if row.current_version < 1:
        raise PlatformError(
            409,
            "PERSONAL_CREDENTIAL_NOT_CONFIGURED",
            "请先配置当前工具的个人凭证",
        )
    add_audit_event(
        database,
        action="personal.credential.validate",
        resource_type="user_credential",
        resource_id=row.id,
        tool_id=row.tool_id,
        environment_id=row.environment_id,
        outcome="unknown",
        request=request,
        actor=context.user,
        metadata={"provider_type": row.provider_type, "validation_state": "unsupported"},
    )
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return PersonalCredentialValidationResponse(
        id=row.id,
        validation_state="unsupported",
        status=row.status,
        current_version=row.current_version,
    )


def _can_create_runtime_scope(
    database: Session,
    context: AuthContext,
    tool_id: str,
    platform_project_id: str,
) -> bool:
    """校验新 Scope 的管理边界，避免仅凭任意项目 ID 扩大工具管理权。"""

    if has_platform_permission(database, context.user.id, "platform.config.manage"):
        return True
    if not has_tool_permission(database, context.user.id, "tool.config.manage", tool_id):
        return False
    membership = database.get(ProjectMembership, (platform_project_id, context.user.id))
    return membership is not None and membership.relation == "manager"


@router.get("/runtime-scopes", response_model=list[RuntimeScopeResponse])
def list_runtime_scopes(
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
    tool_id: str | None = None,
    environment_id: str | None = None,
    platform_project_id: str | None = None,
    status: str | None = None,
) -> list[RuntimeScopeResponse]:
    """列出当前用户可管理的 Scope 元数据，所有过滤均在权限检查前后保持一致。"""

    statement = select(ToolProjectScope).order_by(
        ToolProjectScope.environment_id,
        ToolProjectScope.platform_project_id,
        ToolProjectScope.project_id,
    )
    if tool_id:
        statement = statement.where(ToolProjectScope.tool_id == tool_id)
    if environment_id:
        statement = statement.where(ToolProjectScope.environment_id == environment_id)
    if platform_project_id:
        statement = statement.where(
            ToolProjectScope.platform_project_id == platform_project_id
        )
    if status:
        statement = statement.where(ToolProjectScope.status == status)
    return [
        _runtime_scope_response(row)
        for row in database.scalars(statement).all()
        if _can_manage_config(database, context, "tool_project_scope", row.id)
    ]


@router.get("/runtime-scopes/{scope_id}", response_model=RuntimeScopeResponse)
def get_runtime_scope(
    scope_id: str,
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> RuntimeScopeResponse:
    """读取单一 Scope；不存在或不可管理时分别返回稳定 404/403。"""

    row = database.get(ToolProjectScope, scope_id)
    if row is None:
        raise PlatformError(404, "NOT_FOUND", "Runtime Scope 不存在")
    if not _can_manage_config(database, context, "tool_project_scope", row.id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该 Runtime Scope")
    return _runtime_scope_response(row)


@router.post("/runtime-scopes", response_model=RuntimeScopeResponse, status_code=201)
def create_runtime_scope(
    payload: RuntimeScopeCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> RuntimeScopeResponse:
    """创建 Scope，并在应用层提前返回可理解的固定环境映射错误。"""

    expected_target = {"dev": "test", "prod": "prod"}.get(payload.environment_id)
    if payload.target_env != expected_target:
        raise PlatformError(422, "RUNTIME_SCOPE_MAPPING_INVALID", "平台环境与目标环境映射无效")
    environment = database.get(Environment, payload.environment_id)
    tool = database.get(Tool, payload.tool_id)
    project = database.get(Project, payload.platform_project_id)
    if environment is None or not environment.is_active or tool is None or project is None:
        raise PlatformError(422, "VALIDATION_ERROR", "环境、工具或平台项目不存在")
    if not _can_create_runtime_scope(
        database, context, payload.tool_id, payload.platform_project_id
    ):
        raise PlatformError(403, "PERMISSION_DENIED", "无权创建该 Runtime Scope")
    row = ToolProjectScope(
        id=new_id("tps"), environment_id=payload.environment_id,
        tool_id=payload.tool_id, platform_project_id=payload.platform_project_id,
        project_id=payload.project_id, target_env=payload.target_env,
        display_name=payload.display_name, status="active",
        is_default=payload.is_default, revision=1,
        created_by=context.user.id, updated_by=context.user.id,
    )
    database.add(row)
    try:
        database.flush()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "RUNTIME_SCOPE_CONFLICT", "Runtime Scope 已存在或默认项冲突") from None
    add_audit_event(
        database, action="runtime.scope.create", resource_type="tool_project_scope",
        resource_id=row.id, tool_id=row.tool_id, environment_id=row.environment_id,
        outcome="success", request=request, actor=context.user,
        after={
            "platform_project_id": row.platform_project_id,
            "project_id": row.project_id, "target_env": row.target_env,
            "status": row.status, "is_default": row.is_default,
        },
    )
    database.commit()
    database.refresh(row)
    return _runtime_scope_response(row)


@router.patch("/runtime-scopes/{scope_id}", response_model=RuntimeScopeResponse)
def patch_runtime_scope(
    scope_id: str,
    payload: RuntimeScopePatchRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> RuntimeScopeResponse:
    """用乐观锁更新 Scope 可变元数据；五元组身份字段从契约中完全排除。"""

    row = database.scalar(select(ToolProjectScope).where(
        ToolProjectScope.id == scope_id
    ).with_for_update())
    if row is None:
        raise PlatformError(404, "NOT_FOUND", "Runtime Scope 不存在")
    if not _can_manage_config(database, context, "tool_project_scope", row.id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该 Runtime Scope")
    if row.revision != payload.revision:
        raise PlatformError(409, "VERSION_CONFLICT", "Runtime Scope 已被其他操作更新")
    before = {
        "display_name": row.display_name, "status": row.status,
        "is_default": row.is_default, "revision": row.revision,
    }
    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.status is not None:
        row.status = payload.status
    if payload.is_default is not None:
        row.is_default = payload.is_default
    row.revision += 1
    row.updated_by = context.user.id
    try:
        database.flush()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "RUNTIME_SCOPE_CONFLICT", "默认 Runtime Scope 已存在") from None
    add_audit_event(
        database, action="runtime.scope.update", resource_type="tool_project_scope",
        resource_id=row.id, tool_id=row.tool_id, environment_id=row.environment_id,
        outcome="success", request=request, actor=context.user, before=before,
        after={
            "display_name": row.display_name, "status": row.status,
            "is_default": row.is_default, "revision": row.revision,
        },
    )
    database.commit()
    database.refresh(row)
    return _runtime_scope_response(row)


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
        # 普通执行用户需要字段白名单来渲染首次个人凭证表单。这里只开放已明确
        # 标记为 user + Provider 的安全定义元数据，系统配置和系统 Secret 仍不可见。
        or (
            row.owner_type == "tool"
            and row.value_scope == "user"
            and row.credential_provider_type is not None
            and has_tool_permission(
                database, context.user.id, "tool.execute", row.owner_id
            )
        )
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

    _assert_scope_environment(database, owner_type, owner_id, environment_id)
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

    _assert_scope_environment(
        database, payload.owner_type, payload.owner_id, payload.environment_id
    )
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
        tool_id=_owner_tool_id(database, row.owner_type, row.owner_id),
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
    _assert_scope_environment(database, row.owner_type, row.owner_id, row.environment_id)
    if row.status != "draft":
        raise PlatformError(409, "VERSION_CONFLICT", "只有草稿可以修改")
    if row.revision != payload.revision:
        raise PlatformError(409, "VERSION_CONFLICT", "配置草稿已被其他操作更新")
    if not _can_manage_config(database, context, row.owner_type, row.owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该配置")
    definitions = {
        definition.id: definition
        for definition in _owner_definitions(database, row.owner_type, row.owner_id)
    }
    for item in payload.items:
        definition = definitions.get(item.definition_id)
        if (
            definition is None
            or not _definition_applies_to_owner(
                database, definition, row.owner_type, row.owner_id
            )
            or definition.sensitivity != "normal"
            or not definition.editable
        ):
            raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "包含不可编辑的配置项")
        _validate_value(definition, item.value)
    before = {item.definition_id: item.value_json for item in database.scalars(select(ConfigReleaseItem).where(ConfigReleaseItem.release_id == row.id)).all() if item.value_json is not None}
    database.execute(delete(ConfigReleaseItem).where(ConfigReleaseItem.release_id == row.id, ConfigReleaseItem.value_json.is_not(None)))
    for item in payload.items:
        database.add(ConfigReleaseItem(release_id=row.id, definition_id=item.definition_id, value_json=item.value))
    row.revision += 1
    add_audit_event(
        database, action="config.release.update", resource_type="config_release", resource_id=row.id,
        environment_id=row.environment_id,
        tool_id=_owner_tool_id(database, row.owner_type, row.owner_id),
        outcome="success", request=request, actor=context.user, before=before,
        after={item.definition_id: item.value for item in payload.items},
    )
    database.commit()
    return _release_response(database, row)


def _validate_release(database: Session, row: ConfigRelease) -> None:
    """验证 Release 普通必填项及作用域内 Secret 是否已配置。"""

    _assert_scope_environment(database, row.owner_type, row.owner_id, row.environment_id)
    # Release 是 Scope 下系统运行配置的唯一版本载体；``value_scope=user`` 的
    # 必填项由各用户 Credential 独立校验。若在这里混合校验，会迫使 Dating
    # Scope 为未使用的 Truthy Admin Profile 创建全局 Secret，既破坏项目隔离，
    # 也与“按实际资产校验凭证”的运行时契约冲突。
    definitions = [
        definition
        for definition in _owner_definitions(database, row.owner_type, row.owner_id)
        if definition.value_scope == "system"
        and _definition_applies_to_owner(database, definition, row.owner_type, row.owner_id)
    ]
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
    if row.owner_type in {"llm_profile", "llm_binding"}:
        from app.services.llm import validate_llm_release
        validate_llm_release(database, row)


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
    scope = _assert_scope_environment(
        database, row.owner_type, row.owner_id, row.environment_id
    )
    if scope is not None and (scope.environment_id, scope.target_env) not in {
        ("dev", "test"), ("prod", "prod")
    }:
        raise PlatformError(422, "RUNTIME_SCOPE_MAPPING_INVALID", "Runtime Scope 环境映射无效")
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
        environment_id=row.environment_id,
        tool_id=_owner_tool_id(database, row.owner_type, row.owner_id),
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
    _assert_scope_environment(
        database, source.owner_type, source.owner_id, source.environment_id
    )
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
        environment_id=row.environment_id,
        tool_id=_owner_tool_id(database, row.owner_type, row.owner_id),
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
    _assert_scope_environment(
        database, source.owner_type, source.owner_id, source.environment_id
    )
    if target_environment == source.environment_id:
        raise PlatformError(422, "VALIDATION_ERROR", "目标环境必须与来源环境不同")
    if database.get(Environment, target_environment) is None:
        raise PlatformError(422, "VALIDATION_ERROR", "目标环境不存在")
    if not _can_manage_config(database, context, source.owner_type, source.owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该配置")
    target_owner_id = source.owner_id
    source_scope = _scope_owner(database, source.owner_type, source.owner_id)
    if source_scope is not None:
        expected_target_env = {"dev": "test", "prod": "prod"}.get(target_environment)
        target_scope = database.scalar(select(ToolProjectScope).where(
            ToolProjectScope.environment_id == target_environment,
            ToolProjectScope.tool_id == source_scope.tool_id,
            ToolProjectScope.platform_project_id == source_scope.platform_project_id,
            ToolProjectScope.project_id == source_scope.project_id,
            ToolProjectScope.target_env == expected_target_env,
        ))
        if target_scope is None:
            raise PlatformError(422, "RUNTIME_SCOPE_NOT_FOUND", "目标环境 Runtime Scope 不存在")
        if not _can_manage_config(
            database, context, "tool_project_scope", target_scope.id
        ):
            raise PlatformError(403, "PERMISSION_DENIED", "无权管理目标 Runtime Scope")
        target_owner_id = target_scope.id
    version = (database.scalar(select(func.max(ConfigRelease.version)).where(
        ConfigRelease.environment_id == target_environment,
        ConfigRelease.owner_type == source.owner_type,
        ConfigRelease.owner_id == target_owner_id,
    )) or 0) + 1
    row = ConfigRelease(
        id=new_id("rel"), environment_id=target_environment,
        owner_type=source.owner_type, owner_id=target_owner_id,
        version=version, revision=1, status="draft",
        based_on_release_id=source.id, created_by=context.user.id,
    )
    database.add(row)
    database.flush()
    definitions = {
        definition.id: definition
        for definition in _owner_definitions(database, source.owner_type, source.owner_id)
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
        tool_id=_owner_tool_id(database, row.owner_type, row.owner_id),
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

    _assert_scope_environment(database, owner_type, owner_id, environment_id)
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

    scope = _assert_scope_environment(
        database, payload.owner_type, payload.owner_id, payload.environment_id
    )
    if not _can_manage_secret(database, context, payload.owner_type, payload.owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该 Secret")
    if database.get(Environment, payload.environment_id) is None:
        raise PlatformError(422, "VALIDATION_ERROR", "配置环境不存在")
    definition = database.get(ConfigDefinition, payload.definition_id)
    if definition is None or definition.sensitivity != "secret":
        raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "Secret 定义无效")
    expected_definition_owner = (
        ("tool", scope.tool_id) if scope is not None
        else (payload.owner_type, payload.owner_id)
    )
    if (definition.owner_type, definition.owner_id) != expected_definition_owner:
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
        environment_id=row.environment_id,
        tool_id=_owner_tool_id(database, row.owner_type, row.owner_id),
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
    runtime_scope_id: str | None = None,
) -> list[CredentialResponse]:
    """返回当前用户有 Secret 管理权限的凭证状态。"""

    statement = select(Credential).order_by(Credential.environment_id, Credential.tool_id)
    if environment_id:
        statement = statement.where(Credential.environment_id == environment_id)
    if runtime_scope_id:
        statement = statement.where(Credential.runtime_scope_id == runtime_scope_id)
    rows = [
        row for row in database.scalars(statement).all()
        if _can_manage_secret(
            database, context,
            "tool_project_scope" if row.runtime_scope_id else "tool",
            row.runtime_scope_id or row.tool_id,
        )
    ]
    return [CredentialResponse(
        id=row.id, tool_id=row.tool_id, environment_id=row.environment_id,
        runtime_scope_id=row.runtime_scope_id,
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

    scope = (
        database.get(ToolProjectScope, payload.runtime_scope_id)
        if payload.runtime_scope_id else None
    )
    if payload.tool_id == "api-autotest" and scope is None:
        raise PlatformError(422, "RUNTIME_SCOPE_REQUIRED", "api-autotest 凭证必须绑定 Runtime Scope")
    if scope is not None and (
        scope.tool_id, scope.environment_id
    ) != (payload.tool_id, payload.environment_id):
        raise PlatformError(422, "CREDENTIAL_SCOPE_MISMATCH", "凭证与 Runtime Scope 不匹配")
    owner_type = "tool_project_scope" if scope is not None else "tool"
    owner_id = scope.id if scope is not None else payload.tool_id
    if not _can_manage_secret(database, context, owner_type, owner_id):
        raise PlatformError(403, "PERMISSION_DENIED", "无权管理该凭证")
    if database.get(Environment, payload.environment_id) is None:
        raise PlatformError(422, "VALIDATION_ERROR", "配置环境不存在")
    existing = database.scalar(select(Credential).where(
        Credential.tool_id == payload.tool_id,
        Credential.environment_id == payload.environment_id,
        Credential.provider_type == payload.provider_type,
        Credential.runtime_scope_id == payload.runtime_scope_id,
    ))
    if existing is not None:
        raise PlatformError(409, "VERSION_CONFLICT", "该凭证已存在")
    row = Credential(
        id=new_id("cred"), tool_id=payload.tool_id,
        environment_id=payload.environment_id,
        runtime_scope_id=payload.runtime_scope_id,
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
        runtime_scope_id=row.runtime_scope_id,
        provider_type=row.provider_type, status=row.status,
        current_version=row.current_version, expires_at=row.expires_at,
        refresh_expires_at=row.refresh_expires_at, last_error_code=row.last_error_code,
        last_checked_at=row.last_checked_at,
    )
