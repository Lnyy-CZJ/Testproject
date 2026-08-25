from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
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
    Environment,
    Secret,
)
from app.models.llm import LlmProfile, ToolLlmBinding, UserLlmBinding
from app.schemas.auth import MessageResponse
from app.schemas.llm import (
    LlmBindingResponse, LlmConnectionTestRequest, LlmConnectionTestResponse,
    LlmEffectiveConfigResponse, LlmProfileCreateRequest, LlmProfileResponse,
    LlmProfileUpdateRequest, PersonalLlmBindingPutRequest,
    PersonalLlmBindingResponse, PersonalLlmConnectionTestRequest,
    PersonalLlmProfileCreateRequest, PersonalLlmProfileResponse,
    PersonalLlmProfileUpdateRequest,
)
from app.services.audit import add_audit_event
from app.services.authorization import has_platform_permission, has_tool_permission
from app.services.llm import (
    active_release, provider_allowlist, release_values,
    resolve_legacy_llm_snapshot, resolve_llm_snapshot, validate_provider_target,
)
from app.services.secret_store import load_secret_cipher, replace_secret


router = APIRouter(prefix="/llm", tags=["llm"])
personal_router = APIRouter(prefix="/me/llm", tags=["personal-llm"])


def _platform_manager(database: Session, context: AuthContext) -> bool:
    return has_platform_permission(database, context.user.id, "platform.llm.manage")


def _can_view_binding(database: Session, context: AuthContext, binding: ToolLlmBinding) -> bool:
    return _platform_manager(database, context) or has_tool_permission(database, context.user.id, "tool.view", binding.tool_id)


def _can_manage_binding(database: Session, context: AuthContext, binding: ToolLlmBinding) -> bool:
    return _platform_manager(database, context) or has_tool_permission(database, context.user.id, "tool.config.manage", binding.tool_id)


def _profile_response(database: Session, profile: LlmProfile, environment_id: str) -> LlmProfileResponse:
    release = active_release(database, environment_id, "llm_profile", profile.id)
    secret = database.scalar(select(Secret).where(
        Secret.environment_id == environment_id, Secret.owner_type == "llm_profile",
        Secret.owner_id == profile.id, Secret.current_version_id.is_not(None),
    ))
    binding_count = 0
    for activation in database.scalars(select(ConfigActivation).where(
        ConfigActivation.environment_id == environment_id,
        ConfigActivation.owner_type == "llm_binding",
    )).all():
        values, _ = release_values(database, database.get(ConfigRelease, activation.active_release_id))
        if values.get("PROFILE_ID") == profile.id:
            binding_count += 1
    return LlmProfileResponse(
        id=profile.id, name=profile.name, description=profile.description,
        protocol=profile.protocol, is_archived=profile.is_archived,
        environment_id=environment_id, active_release_id=release.id if release else None,
        active_release_version=release.version if release else None,
        api_key_configured=secret is not None, binding_count=int(binding_count),
        created_at=profile.created_at, updated_at=profile.updated_at,
    )


def _binding_response(database: Session, binding: ToolLlmBinding, environment_id: str) -> LlmBindingResponse:
    release = active_release(database, environment_id, "llm_binding", binding.id)
    values, secrets = release_values(database, release)
    return LlmBindingResponse(
        id=binding.id, tool_id=binding.tool_id, capability_key=binding.capability_key,
        display_name=binding.display_name, description=binding.description,
        environment_id=environment_id, active_release_id=release.id if release else None,
        active_release_version=release.version if release else None,
        profile_id=values.get("PROFILE_ID"), enabled=values.get("ENABLED"),
        api_key_override_configured="API_KEY_OVERRIDE" in secrets,
    )


def _profile_definitions(profile_id: str) -> list[ConfigDefinition]:
    """生成新 Profile 的已登记配置定义，不引入额外模板表。"""

    specs = (
        ("BASE_URL", "API Base URL", "url", "normal", True, None, {}, 10),
        ("MODEL", "模型名称", "string", "normal", True, None, {"min_length": 1, "max_length": 256}, 20),
        ("TEMPERATURE", "Temperature", "float", "normal", False, None, {"minimum": 0, "maximum": 2}, 30),
        ("MAX_TOKENS", "Max Tokens", "int", "normal", False, None, {"minimum": 1, "maximum": 131072}, 40),
        ("TIMEOUT_SECONDS", "请求超时（秒）", "int", "normal", False, None, {"minimum": 1, "maximum": 600}, 50),
        ("ENABLED", "启用", "bool", "normal", True, True, {}, 60),
        ("API_KEY", "API Key", "secret", "secret", True, None, {}, 70),
    )
    return [ConfigDefinition(
        id=f"{profile_id}.{key}", key=key, display_name=display, description=display,
        owner_type="llm_profile", owner_id=profile_id,
        group_key="secret" if sensitivity == "secret" else "model",
        value_type=value_type, sensitivity=sensitivity, required=required,
        default_value=default, validation_schema=schema, apply_mode="next_task",
        editable=True, sort_order=sort_order, value_scope="user",
    ) for key, display, value_type, sensitivity, required, default, schema, sort_order in specs]


_PROFILE_REQUEST_TO_KEY = {
    "base_url": "BASE_URL",
    "model": "MODEL",
    "temperature": "TEMPERATURE",
    "max_tokens": "MAX_TOKENS",
    "timeout_seconds": "TIMEOUT_SECONDS",
    "enabled": "ENABLED",
}

_BINDING_REQUEST_TO_KEY = {
    "model_override": "MODEL_OVERRIDE",
    "temperature_override": "TEMPERATURE_OVERRIDE",
    "max_tokens_override": "MAX_TOKENS_OVERRIDE",
    "timeout_seconds_override": "TIMEOUT_SECONDS_OVERRIDE",
}


def _require_personal_llm_write(settings: Settings) -> None:
    """复用个人配置写入开关，保证 LLM 与凭证按同一发布阶段开放。"""

    if not settings.personal_credentials_write_enabled:
        raise PlatformError(
            503, "PERSONAL_CREDENTIAL_WRITE_DISABLED", "个人配置写入功能暂未开放"
        )


def _require_active_environment(database: Session, environment_id: str) -> Environment:
    """校验目标环境存在且启用，避免创建不可解析的孤立 Release。"""

    environment = database.get(Environment, environment_id)
    if environment is None or not environment.is_active:
        raise PlatformError(422, "VALIDATION_ERROR", "配置环境不存在或不可用")
    return environment


def _personal_profile_response(
    database: Session,
    profile: LlmProfile,
    environment_id: str,
) -> PersonalLlmProfileResponse:
    """展开当前环境 Profile 的非敏感参数和 Key 配置状态。"""

    release = active_release(database, environment_id, "llm_profile", profile.id)
    values, secrets = release_values(database, release)
    binding_count = 0
    personal_bindings = database.scalars(select(UserLlmBinding).where(
        UserLlmBinding.user_id == profile.owner_user_id,
    )).all()
    for binding in personal_bindings:
        binding_release = active_release(
            database, environment_id, "user_llm_binding", binding.id
        )
        binding_values, _ = release_values(database, binding_release)
        if (
            binding_values.get("PROFILE_ID") == profile.id
            and binding_values.get("ENABLED", True)
        ):
            binding_count += 1
    return PersonalLlmProfileResponse(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        provider=profile.protocol,
        is_archived=profile.is_archived,
        environment_id=environment_id,
        active_release_id=release.id if release else None,
        active_release_version=release.version if release else None,
        base_url=values.get("BASE_URL"),
        model=values.get("MODEL"),
        temperature=values.get("TEMPERATURE"),
        max_tokens=values.get("MAX_TOKENS"),
        timeout_seconds=values.get("TIMEOUT_SECONDS"),
        enabled=values.get("ENABLED") if release else None,
        api_key_configured="API_KEY" in secrets,
        binding_count=binding_count,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _publish_personal_profile_release(
    database: Session,
    settings: Settings,
    profile: LlmProfile,
    environment_id: str,
    actor_id: str,
    changes: dict[str, object],
    changed_fields: set[str],
    api_key: str | None,
) -> ConfigRelease:
    """发布 Profile 新版本并冻结本次使用的 API Key SecretVersion。

    更新时未提交的普通参数从同一 Profile/环境的 active Release 继承；API Key
    未提交时沿用已冻结版本。新环境没有 Key 时失败关闭，绝不查找其他环境或用户。
    """

    current = active_release(database, environment_id, "llm_profile", profile.id)
    current_values, current_secrets = release_values(database, current)
    values = dict(current_values)
    for request_key, definition_key in _PROFILE_REQUEST_TO_KEY.items():
        if request_key not in changed_fields:
            continue
        value = changes.get(request_key)
        if value is None:
            values.pop(definition_key, None)
        else:
            values[definition_key] = value
    values.setdefault("ENABLED", True)
    if not isinstance(values.get("BASE_URL"), str) or not isinstance(values.get("MODEL"), str):
        raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "LLM Base URL 和模型为必填项")
    validate_provider_target(
        values["BASE_URL"],
        provider_allowlist(database, environment_id),
        production=environment_id == "prod",
    )

    definitions = {
        row.key: row
        for row in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == "llm_profile",
            ConfigDefinition.owner_id == profile.id,
        )).all()
    }
    if (set(_PROFILE_REQUEST_TO_KEY.values()) | {"API_KEY"}) - set(definitions):
        raise PlatformError(503, "LLM_CONFIG_NOT_READY", "LLM Profile 定义不完整")
    version = int(database.scalar(select(func.max(ConfigRelease.version)).where(
        ConfigRelease.environment_id == environment_id,
        ConfigRelease.owner_type == "llm_profile",
        ConfigRelease.owner_id == profile.id,
    )) or 0) + 1
    release = ConfigRelease(
        id=new_id("rel"),
        environment_id=environment_id,
        owner_type="llm_profile",
        owner_id=profile.id,
        version=version,
        revision=1,
        status="active",
        based_on_release_id=current.id if current else None,
        created_by=actor_id,
        published_by=actor_id,
        published_at=datetime.now(UTC),
    )
    database.add(release)
    database.flush()
    for key, value in values.items():
        definition = definitions.get(key)
        if definition is not None and definition.sensitivity == "normal" and value is not None:
            database.add(ConfigReleaseItem(
                release_id=release.id, definition_id=definition.id, value_json=value
            ))

    chosen_secret = current_secrets.get("API_KEY")
    if api_key is not None:
        secret = database.scalar(select(Secret).where(
            Secret.environment_id == environment_id,
            Secret.owner_type == "llm_profile",
            Secret.owner_id == profile.id,
            Secret.definition_id == definitions["API_KEY"].id,
        ))
        if secret is None:
            secret = Secret(
                id=new_id("sec"),
                environment_id=environment_id,
                owner_type="llm_profile",
                owner_id=profile.id,
                definition_id=definitions["API_KEY"].id,
                status="missing",
            )
            database.add(secret)
            database.flush()
        key_version = replace_secret(
            database, load_secret_cipher(settings), secret, api_key, actor_id
        )
        database.flush()
        chosen_secret = (secret, key_version)
    if chosen_secret is None:
        raise PlatformError(422, "LLM_SECRET_UNAVAILABLE", "LLM API Key 尚未配置")
    database.add(ConfigReleaseItem(
        release_id=release.id,
        definition_id=definitions["API_KEY"].id,
        secret_version_id=chosen_secret[1].id,
    ))
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == environment_id,
        ConfigActivation.owner_type == "llm_profile",
        ConfigActivation.owner_id == profile.id,
    ))
    if activation is None:
        database.add(ConfigActivation(
            environment_id=environment_id,
            owner_type="llm_profile",
            owner_id=profile.id,
            active_release_id=release.id,
        ))
    else:
        activation.active_release_id = release.id
    if current is not None:
        current.status = "superseded"
    return release


@personal_router.get("/profiles", response_model=list[PersonalLlmProfileResponse])
def list_personal_llm_profiles(
    environment_id: str,
    response: Response,
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> list[PersonalLlmProfileResponse]:
    """只列出认证用户自己的非空所有者 Profile。"""

    rows = list(database.scalars(select(LlmProfile).where(
        LlmProfile.owner_user_id == context.user.id,
    ).order_by(LlmProfile.is_archived, LlmProfile.name_normalized)).all())
    response.headers["Cache-Control"] = "no-store"
    return [_personal_profile_response(database, row, environment_id) for row in rows]


@personal_router.post(
    "/profiles", response_model=PersonalLlmProfileResponse, status_code=201
)
def create_personal_llm_profile(
    payload: PersonalLlmProfileCreateRequest,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PersonalLlmProfileResponse:
    """原子创建个人 Profile、定义、首个 active Release 和加密 API Key。"""

    _require_personal_llm_write(settings)
    _require_active_environment(database, payload.environment_id)
    name = payload.name.strip()
    if not name:
        raise PlatformError(422, "VALIDATION_ERROR", "Profile 名称不能为空")
    profile = LlmProfile(
        id=new_id("llmp"),
        name=name,
        name_normalized=name.casefold(),
        owner_user_id=context.user.id,
        description=payload.description.strip(),
        protocol=payload.provider,
        created_by=context.user.id,
    )
    database.add(profile)
    try:
        database.flush()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "VERSION_CONFLICT", "个人 LLM Profile 名称已存在") from None
    database.add_all(_profile_definitions(profile.id))
    database.flush()
    changes = payload.model_dump(exclude={"name", "description", "environment_id", "provider", "api_key"})
    _publish_personal_profile_release(
        database,
        settings,
        profile,
        payload.environment_id,
        context.user.id,
        changes,
        set(_PROFILE_REQUEST_TO_KEY),
        payload.api_key,
    )
    add_audit_event(
        database,
        action="personal.llm.profile.create",
        resource_type="llm_profile",
        resource_id=profile.id,
        environment_id=payload.environment_id,
        outcome="success",
        request=request,
        actor=context.user,
        after={"provider": profile.protocol, "release_version": 1},
    )
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _personal_profile_response(database, profile, payload.environment_id)


@personal_router.patch(
    "/profiles/{profile_id}", response_model=PersonalLlmProfileResponse
)
def update_personal_llm_profile(
    profile_id: str,
    payload: PersonalLlmProfileUpdateRequest,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PersonalLlmProfileResponse:
    """修改自己的 Profile；他人或 legacy 空所有者 Profile 统一视为不存在。"""

    _require_personal_llm_write(settings)
    _require_active_environment(database, payload.environment_id)
    profile = database.scalar(select(LlmProfile).where(
        LlmProfile.owner_user_id == context.user.id,
        LlmProfile.id == profile_id,
    ))
    if profile is None:
        raise PlatformError(404, "NOT_FOUND", "个人 LLM Profile 不存在")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise PlatformError(422, "VALIDATION_ERROR", "Profile 名称不能为空")
        profile.name = name
        profile.name_normalized = name.casefold()
    if payload.description is not None:
        profile.description = payload.description.strip()
    if payload.provider is not None:
        profile.protocol = payload.provider
    try:
        database.flush()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "VERSION_CONFLICT", "个人 LLM Profile 名称已存在") from None
    changed_config_fields = set(payload.model_fields_set) & set(_PROFILE_REQUEST_TO_KEY)
    if changed_config_fields or "api_key" in payload.model_fields_set:
        _publish_personal_profile_release(
            database,
            settings,
            profile,
            payload.environment_id,
            context.user.id,
            payload.model_dump(),
            changed_config_fields,
            payload.api_key if "api_key" in payload.model_fields_set else None,
        )
    add_audit_event(
        database,
        action="personal.llm.profile.update",
        resource_type="llm_profile",
        resource_id=profile.id,
        environment_id=payload.environment_id,
        outcome="success",
        request=request,
        actor=context.user,
    )
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _personal_profile_response(database, profile, payload.environment_id)


def _personal_profile_in_use(database: Session, user_id: str, profile_id: str) -> bool:
    """检查该用户任意环境的当前 Binding 是否仍启用目标 Profile。"""

    binding_ids = list(database.scalars(select(UserLlmBinding.id).where(
        UserLlmBinding.user_id == user_id,
    )).all())
    if not binding_ids:
        return False
    activations = database.scalars(select(ConfigActivation).where(
        ConfigActivation.owner_type == "user_llm_binding",
        ConfigActivation.owner_id.in_(binding_ids),
    )).all()
    for activation in activations:
        release = database.get(ConfigRelease, activation.active_release_id)
        values, _ = release_values(database, release)
        if values.get("PROFILE_ID") == profile_id and values.get("ENABLED", True):
            return True
    return False


def _set_personal_profile_archive(
    profile_id: str,
    archived: bool,
    environment_id: str,
    request: Request,
    response: Response,
    context: AuthContext,
    database: Session,
    settings: Settings,
) -> PersonalLlmProfileResponse:
    """归档或恢复当前用户 Profile，并阻止破坏仍在使用的配置。"""

    _require_personal_llm_write(settings)
    profile = database.scalar(select(LlmProfile).where(
        LlmProfile.owner_user_id == context.user.id,
        LlmProfile.id == profile_id,
    ))
    if profile is None:
        raise PlatformError(404, "NOT_FOUND", "个人 LLM Profile 不存在")
    if archived and _personal_profile_in_use(database, context.user.id, profile.id):
        raise PlatformError(
            409, "LLM_PROFILE_IN_USE", "该连接仍被能力绑定，请先解绑"
        )
    profile.is_archived = archived
    add_audit_event(
        database,
        action="personal.llm.profile.archive" if archived else "personal.llm.profile.restore",
        resource_type="llm_profile",
        resource_id=profile.id,
        environment_id=environment_id,
        outcome="success",
        request=request,
        actor=context.user,
    )
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _personal_profile_response(database, profile, environment_id)


@personal_router.post(
    "/profiles/{profile_id}/archive", response_model=PersonalLlmProfileResponse
)
def archive_personal_llm_profile(
    profile_id: str,
    environment_id: str,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PersonalLlmProfileResponse:
    return _set_personal_profile_archive(
        profile_id, True, environment_id, request, response, context, database, settings
    )


@personal_router.post(
    "/profiles/{profile_id}/restore", response_model=PersonalLlmProfileResponse
)
def restore_personal_llm_profile(
    profile_id: str,
    environment_id: str,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PersonalLlmProfileResponse:
    return _set_personal_profile_archive(
        profile_id, False, environment_id, request, response, context, database, settings
    )


def _ensure_personal_binding_definitions(
    database: Session,
    user_binding: UserLlmBinding,
    catalog_binding: ToolLlmBinding,
) -> dict[str, ConfigDefinition]:
    """首次配置时从稳定目录 Binding 克隆一组个人作用域定义。"""

    existing = {
        row.key: row
        for row in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == "user_llm_binding",
            ConfigDefinition.owner_id == user_binding.id,
        )).all()
    }
    if existing:
        return existing
    sources = list(database.scalars(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == "llm_binding",
        ConfigDefinition.owner_id == catalog_binding.id,
    ).order_by(ConfigDefinition.sort_order, ConfigDefinition.key)).all())
    if not sources or "PROFILE_ID" not in {row.key for row in sources}:
        raise PlatformError(503, "LLM_CONFIG_NOT_READY", "LLM 能力目录定义不完整")
    for source in sources:
        database.add(ConfigDefinition(
            id=f"{user_binding.id}.{source.key}",
            key=source.key,
            display_name=source.display_name,
            description=source.description,
            owner_type="user_llm_binding",
            owner_id=user_binding.id,
            group_key=source.group_key,
            value_type=source.value_type,
            sensitivity=source.sensitivity,
            required=source.required,
            # 目录的默认 Profile 可能指向 legacy/admin；个人定义必须显式清除它。
            default_value=None if source.key == "PROFILE_ID" else source.default_value,
            validation_schema=source.validation_schema,
            apply_mode=source.apply_mode,
            editable=source.editable,
            sort_order=source.sort_order,
            value_scope="user",
        ))
    database.flush()
    return {
        row.key: row
        for row in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == "user_llm_binding",
            ConfigDefinition.owner_id == user_binding.id,
        )).all()
    }


def _personal_binding_response(
    database: Session,
    catalog_binding: ToolLlmBinding,
    user_binding: UserLlmBinding | None,
    environment_id: str,
) -> PersonalLlmBindingResponse:
    """合并公共能力目录与当前用户 active Binding Release 的安全摘要。"""

    release = active_release(
        database, environment_id, "user_llm_binding", user_binding.id
    ) if user_binding else None
    values, secrets = release_values(database, release)
    return PersonalLlmBindingResponse(
        id=user_binding.id if user_binding else None,
        binding_id=catalog_binding.id,
        tool_id=catalog_binding.tool_id,
        capability_key=catalog_binding.capability_key,
        display_name=catalog_binding.display_name,
        description=catalog_binding.description,
        environment_id=environment_id,
        active_release_id=release.id if release else None,
        current_version=release.version if release else 0,
        profile_id=values.get("PROFILE_ID"),
        enabled=values.get("ENABLED") if release else None,
        model_override=values.get("MODEL_OVERRIDE"),
        temperature_override=values.get("TEMPERATURE_OVERRIDE"),
        max_tokens_override=values.get("MAX_TOKENS_OVERRIDE"),
        timeout_seconds_override=values.get("TIMEOUT_SECONDS_OVERRIDE"),
        api_key_override_configured="API_KEY_OVERRIDE" in secrets,
    )


@personal_router.get("/bindings", response_model=list[PersonalLlmBindingResponse])
def list_personal_llm_bindings(
    environment_id: str,
    response: Response,
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> list[PersonalLlmBindingResponse]:
    """列出当前用户具有 tool.execute 的能力目录及其个人发布状态。"""

    catalog = [
        row
        for row in database.scalars(select(ToolLlmBinding).order_by(
            ToolLlmBinding.tool_id, ToolLlmBinding.capability_key
        )).all()
        if has_tool_permission(database, context.user.id, "tool.execute", row.tool_id)
    ]
    personal = {
        row.binding_id: row
        for row in database.scalars(select(UserLlmBinding).where(
            UserLlmBinding.user_id == context.user.id,
        )).all()
    }
    response.headers["Cache-Control"] = "no-store"
    return [
        _personal_binding_response(database, row, personal.get(row.id), environment_id)
        for row in catalog
    ]


@personal_router.put(
    "/bindings/{binding_id}", response_model=PersonalLlmBindingResponse
)
def put_personal_llm_binding(
    binding_id: str,
    payload: PersonalLlmBindingPutRequest,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PersonalLlmBindingResponse:
    """发布当前用户在指定能力目录上的个人 Binding 新版本。"""

    _require_personal_llm_write(settings)
    _require_active_environment(database, payload.environment_id)
    catalog_binding = database.get(ToolLlmBinding, binding_id)
    if catalog_binding is None or not has_tool_permission(
        database, context.user.id, "tool.execute", catalog_binding.tool_id
    ):
        raise PlatformError(404, "NOT_FOUND", "LLM 能力绑定不存在")
    if payload.profile_id is None and payload.enabled:
        raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "解绑时必须同时停用能力")
    profile = None
    if payload.profile_id is not None:
        profile = database.scalar(select(LlmProfile).where(
            LlmProfile.owner_user_id == context.user.id,
            LlmProfile.id == payload.profile_id,
            LlmProfile.is_archived.is_(False),
        ))
        if profile is None:
            raise PlatformError(404, "NOT_FOUND", "个人 LLM Profile 不存在")
        profile_release = active_release(
            database, payload.environment_id, "llm_profile", profile.id
        )
        _, profile_secrets = release_values(database, profile_release)
        if profile_release is None or "API_KEY" not in profile_secrets:
            raise PlatformError(
                409, "PERSONAL_LLM_NOT_CONFIGURED", "请先发布当前环境的个人 LLM Profile"
            )

    user_binding = database.scalar(select(UserLlmBinding).where(
        UserLlmBinding.user_id == context.user.id,
        UserLlmBinding.binding_id == catalog_binding.id,
    ).with_for_update())
    current = active_release(
        database, payload.environment_id, "user_llm_binding", user_binding.id
    ) if user_binding else None
    current_version = current.version if current else 0
    if payload.expected_version != current_version:
        raise PlatformError(409, "VERSION_CONFLICT", "配置已更新，请刷新后重试")
    if user_binding is None:
        user_binding = UserLlmBinding(
            id=new_id("ullmb"), user_id=context.user.id, binding_id=catalog_binding.id
        )
        database.add(user_binding)
        try:
            database.flush()
        except IntegrityError:
            database.rollback()
            raise PlatformError(409, "VERSION_CONFLICT", "配置已更新，请刷新后重试") from None
    definitions = _ensure_personal_binding_definitions(
        database, user_binding, catalog_binding
    )
    old_values, old_secrets = release_values(database, current)
    version = int(database.scalar(select(func.max(ConfigRelease.version)).where(
        ConfigRelease.environment_id == payload.environment_id,
        ConfigRelease.owner_type == "user_llm_binding",
        ConfigRelease.owner_id == user_binding.id,
    )) or 0) + 1
    release = ConfigRelease(
        id=new_id("rel"),
        environment_id=payload.environment_id,
        owner_type="user_llm_binding",
        owner_id=user_binding.id,
        version=version,
        revision=1,
        status="active",
        based_on_release_id=current.id if current else None,
        created_by=context.user.id,
        published_by=context.user.id,
        published_at=datetime.now(UTC),
    )
    database.add(release)
    database.flush()
    values: dict[str, object] = {"ENABLED": payload.enabled}
    if profile is not None:
        values["PROFILE_ID"] = profile.id
    for request_key, definition_key in _BINDING_REQUEST_TO_KEY.items():
        value = getattr(payload, request_key)
        if value is not None:
            values[definition_key] = value
    for key, value in values.items():
        definition = definitions.get(key)
        if definition is None or definition.sensitivity != "normal":
            if key == "ENABLED" and definition is None:
                # 早期目录可能没有 ENABLED；没有定义时不静默制造任意字段。
                raise PlatformError(503, "LLM_CONFIG_NOT_READY", "LLM 能力目录定义不完整")
            continue
        database.add(ConfigReleaseItem(
            release_id=release.id, definition_id=definition.id, value_json=value
        ))

    chosen_override = None if payload.clear_api_key_override else old_secrets.get("API_KEY_OVERRIDE")
    if payload.api_key_override is not None:
        definition = definitions.get("API_KEY_OVERRIDE")
        if definition is None:
            raise PlatformError(422, "CONFIG_VALIDATION_FAILED", "该能力不支持独立 API Key")
        secret = database.scalar(select(Secret).where(
            Secret.environment_id == payload.environment_id,
            Secret.owner_type == "user_llm_binding",
            Secret.owner_id == user_binding.id,
            Secret.definition_id == definition.id,
        ))
        if secret is None:
            secret = Secret(
                id=new_id("sec"), environment_id=payload.environment_id,
                owner_type="user_llm_binding", owner_id=user_binding.id,
                definition_id=definition.id, status="missing",
            )
            database.add(secret)
            database.flush()
        override_version = replace_secret(
            database, load_secret_cipher(settings), secret,
            payload.api_key_override, context.user.id,
        )
        database.flush()
        chosen_override = (secret, override_version)
    if chosen_override is not None and profile is not None:
        database.add(ConfigReleaseItem(
            release_id=release.id,
            definition_id=definitions["API_KEY_OVERRIDE"].id,
            secret_version_id=chosen_override[1].id,
        ))
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == payload.environment_id,
        ConfigActivation.owner_type == "user_llm_binding",
        ConfigActivation.owner_id == user_binding.id,
    ))
    if activation is None:
        database.add(ConfigActivation(
            environment_id=payload.environment_id,
            owner_type="user_llm_binding",
            owner_id=user_binding.id,
            active_release_id=release.id,
        ))
    else:
        activation.active_release_id = release.id
    if current is not None:
        current.status = "superseded"
    add_audit_event(
        database,
        action="personal.llm.binding.publish",
        resource_type="user_llm_binding",
        resource_id=user_binding.id,
        tool_id=catalog_binding.tool_id,
        environment_id=payload.environment_id,
        outcome="success",
        request=request,
        actor=context.user,
        after={
            "binding_id": catalog_binding.id,
            "release_version": version,
            "enabled": payload.enabled,
        },
    )
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return _personal_binding_response(
        database, catalog_binding, user_binding, payload.environment_id
    )


@personal_router.post(
    "/test-connection", response_model=LlmConnectionTestResponse
)
def test_personal_llm_connection(
    payload: PersonalLlmConnectionTestRequest,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LlmConnectionTestResponse:
    """使用当前用户已发布快照执行固定最小连接测试。"""

    _require_personal_llm_write(settings)
    catalog_binding = database.get(ToolLlmBinding, payload.binding_id)
    if catalog_binding is None or not has_tool_permission(
        database, context.user.id, "tool.execute", catalog_binding.tool_id
    ):
        raise PlatformError(404, "NOT_FOUND", "LLM 能力绑定不存在")
    snapshot = resolve_llm_snapshot(
        database,
        settings,
        payload.environment_id,
        catalog_binding.tool_id,
        catalog_binding.capability_key,
        context.user.id,
        include_secrets=True,
    )
    _probe_llm_snapshot(database, payload.environment_id, snapshot)
    add_audit_event(
        database,
        action="personal.llm.connection.test",
        resource_type="user_llm_binding",
        resource_id=snapshot["binding_id"],
        tool_id=catalog_binding.tool_id,
        environment_id=payload.environment_id,
        outcome="success",
        request=request,
        actor=context.user,
        metadata={"snapshot_id": snapshot["snapshot_id"]},
    )
    database.commit()
    response.headers["Cache-Control"] = "no-store"
    return LlmConnectionTestResponse(
        status="ok",
        checked_at=datetime.now(UTC),
        model=snapshot["model"],
        snapshot_id=snapshot["snapshot_id"],
    )


@router.get("/profiles", response_model=list[LlmProfileResponse])
def list_profiles(
    environment_id: str,
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> list[LlmProfileResponse]:
    """列出 Profile 安全摘要；只有 LLM 管理员可浏览公共配置身份。"""

    if not _platform_manager(database, context):
        raise PlatformError(403, "PERMISSION_DENIED", "无权查看 LLM 公共配置")
    return [_profile_response(database, row, environment_id) for row in database.scalars(
        # legacy 路由只保留迁移前的无所有者公共 Profile。个人对象的存在、名称
        # 和配置状态均不得通过管理员公共列表侧漏。
        select(LlmProfile).where(LlmProfile.owner_user_id.is_(None)).order_by(
            LlmProfile.is_archived, LlmProfile.name
        )
    ).all()]


@router.post("/profiles", response_model=LlmProfileResponse, status_code=201)
def create_profile(
    payload: LlmProfileCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> LlmProfileResponse:
    """在一个事务中创建 Profile、定义和指定环境首个草稿。"""

    if not _platform_manager(database, context):
        raise PlatformError(403, "PERMISSION_DENIED", "无权创建 LLM Profile")
    normalized = payload.name.strip().casefold()
    profile = LlmProfile(
        id=new_id("llmp"), name=payload.name.strip(), name_normalized=normalized,
        description=payload.description.strip(), protocol="openai_compatible",
        created_by=context.user.id,
    )
    database.add(profile)
    try:
        database.flush()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "VERSION_CONFLICT", "LLM Profile 名称已存在") from None
    definitions = _profile_definitions(profile.id)
    database.add_all(definitions)
    release = ConfigRelease(
        id=new_id("rel"), environment_id=payload.environment_id,
        owner_type="llm_profile", owner_id=profile.id, version=1, revision=1,
        status="draft", created_by=context.user.id,
    )
    database.add(release)
    database.flush()
    enabled = next(row for row in definitions if row.key == "ENABLED")
    database.add(ConfigReleaseItem(release_id=release.id, definition_id=enabled.id, value_json=True))
    add_audit_event(
        database, action="llm.profile.create", resource_type="llm_profile",
        resource_id=profile.id, environment_id=payload.environment_id,
        outcome="success", request=request, actor=context.user,
    )
    database.commit()
    database.refresh(profile)
    return _profile_response(database, profile, payload.environment_id)


@router.patch("/profiles/{profile_id}", response_model=LlmProfileResponse)
def update_profile(
    profile_id: str, payload: LlmProfileUpdateRequest, environment_id: str,
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
) -> LlmProfileResponse:
    if not _platform_manager(database, context):
        raise PlatformError(403, "PERMISSION_DENIED", "无权修改 LLM Profile")
    profile = database.get(LlmProfile, profile_id)
    if profile is None or profile.owner_user_id is not None:
        raise PlatformError(404, "LLM_PROFILE_NOT_FOUND", "LLM Profile 不存在")
    if payload.name is not None:
        profile.name = payload.name.strip()
        profile.name_normalized = profile.name.casefold()
    if payload.description is not None:
        profile.description = payload.description.strip()
    add_audit_event(database, action="llm.profile.update", resource_type="llm_profile", resource_id=profile.id,
                    environment_id=environment_id, outcome="success", request=request, actor=context.user)
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "VERSION_CONFLICT", "LLM Profile 名称已存在") from None
    database.refresh(profile)
    return _profile_response(database, profile, environment_id)


def _set_archive(profile_id: str, archived: bool, environment_id: str, request: Request,
                 context: AuthContext, database: Session) -> LlmProfileResponse:
    if not _platform_manager(database, context):
        raise PlatformError(403, "PERMISSION_DENIED", "无权归档 LLM Profile")
    profile = database.get(LlmProfile, profile_id)
    if profile is None or profile.owner_user_id is not None:
        raise PlatformError(404, "LLM_PROFILE_NOT_FOUND", "LLM Profile 不存在")
    if archived:
        for activation in database.scalars(select(ConfigActivation).where(ConfigActivation.owner_type == "llm_binding")).all():
            release = database.get(ConfigRelease, activation.active_release_id)
            values, _ = release_values(database, release)
            if values.get("PROFILE_ID") == profile.id and values.get("ENABLED", True):
                raise PlatformError(409, "VERSION_CONFLICT", "Profile 仍被已发布工具绑定使用")
    profile.is_archived = archived
    add_audit_event(database, action="llm.profile.archive" if archived else "llm.profile.restore",
                    resource_type="llm_profile", resource_id=profile.id, environment_id=environment_id,
                    outcome="success", request=request, actor=context.user)
    database.commit()
    database.refresh(profile)
    return _profile_response(database, profile, environment_id)


@router.post("/profiles/{profile_id}/archive", response_model=LlmProfileResponse)
def archive_profile(profile_id: str, environment_id: str, request: Request,
                    context: Annotated[AuthContext, Depends(require_csrf)],
                    database: Annotated[Session, Depends(get_db)]) -> LlmProfileResponse:
    return _set_archive(profile_id, True, environment_id, request, context, database)


@router.post("/profiles/{profile_id}/restore", response_model=LlmProfileResponse)
def restore_profile(profile_id: str, environment_id: str, request: Request,
                    context: Annotated[AuthContext, Depends(require_csrf)],
                    database: Annotated[Session, Depends(get_db)]) -> LlmProfileResponse:
    return _set_archive(profile_id, False, environment_id, request, context, database)


@router.get("/bindings", response_model=list[LlmBindingResponse])
def list_bindings(environment_id: str, context: Annotated[AuthContext, Depends(current_auth_context)],
                  database: Annotated[Session, Depends(get_db)]) -> list[LlmBindingResponse]:
    rows = [row for row in database.scalars(select(ToolLlmBinding).order_by(ToolLlmBinding.tool_id)).all()
            if _can_view_binding(database, context, row)]
    return [_binding_response(database, row, environment_id) for row in rows]


@router.get("/bindings/{binding_id}", response_model=LlmBindingResponse)
def get_binding(binding_id: str, environment_id: str,
                context: Annotated[AuthContext, Depends(current_auth_context)],
                database: Annotated[Session, Depends(get_db)]) -> LlmBindingResponse:
    binding = database.get(ToolLlmBinding, binding_id)
    if binding is None or not _can_view_binding(database, context, binding):
        raise PlatformError(404, "LLM_BINDING_NOT_FOUND", "LLM 工具绑定不存在")
    return _binding_response(database, binding, environment_id)


@router.get("/effective-config", response_model=LlmEffectiveConfigResponse)
def effective_config(environment_id: str, binding_id: str,
                     context: Annotated[AuthContext, Depends(current_auth_context)],
                     database: Annotated[Session, Depends(get_db)],
                     settings: Annotated[Settings, Depends(get_settings)]) -> LlmEffectiveConfigResponse:
    binding = database.get(ToolLlmBinding, binding_id)
    if binding is None or not _can_view_binding(database, context, binding):
        raise PlatformError(404, "LLM_BINDING_NOT_FOUND", "LLM 工具绑定不存在")
    return LlmEffectiveConfigResponse(**resolve_legacy_llm_snapshot(
        database, settings, environment_id, binding.tool_id, binding.capability_key,
        include_secrets=False,
    ))


@router.post("/test-connection", response_model=LlmConnectionTestResponse)
def test_connection(
    payload: LlmConnectionTestRequest, request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LlmConnectionTestResponse:
    """用固定最小请求验证当前已发布配置，不返回模型内容。"""

    binding = database.get(ToolLlmBinding, payload.binding_id)
    if binding is None:
        raise PlatformError(404, "LLM_BINDING_NOT_FOUND", "LLM 工具绑定不存在")
    if not _can_manage_binding(database, context, binding):
        raise PlatformError(403, "PERMISSION_DENIED", "无权测试该 LLM 配置")
    snapshot = resolve_legacy_llm_snapshot(
        database, settings, payload.environment_id, binding.tool_id,
        binding.capability_key, include_secrets=True,
    )
    _probe_llm_snapshot(database, payload.environment_id, snapshot)
    add_audit_event(database, action="llm.connection.test", resource_type="llm_binding",
                    resource_id=binding.id, tool_id=binding.tool_id,
                    environment_id=payload.environment_id, outcome="success",
                    request=request, actor=context.user, metadata={"snapshot_id": snapshot["snapshot_id"]})
    database.commit()
    return LlmConnectionTestResponse(status="ok", checked_at=datetime.now(UTC),
                                     model=snapshot["model"], snapshot_id=snapshot["snapshot_id"])


def _probe_llm_snapshot(
    database: Session,
    environment_id: str,
    snapshot: dict,
) -> None:
    """发送固定最小请求并只校验 OpenAI 兼容响应结构。

    调用方负责解析所有权正确的快照和写审计；本函数不记录 URL、API Key、
    Provider 正文或模型回复，异常也只暴露稳定错误码。
    """

    endpoint = validate_provider_target(
        snapshot["base_url"], provider_allowlist(database, environment_id),
        production=environment_id == "prod",
    )
    body = {"model": snapshot["model"], "messages": [{"role": "user", "content": "Reply OK."}], "max_tokens": 2}
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            with client.stream("POST", endpoint, headers={
                "Authorization": f"Bearer {snapshot['api_key']}", "Content-Type": "application/json",
            }, json=body) as response:
                if response.status_code >= 300:
                    raise PlatformError(502, "LLM_CONNECTION_FAILED", "LLM Provider 连接验证失败")
                payload_bytes = bytearray()
                for chunk in response.iter_bytes():
                    payload_bytes.extend(chunk)
                    if len(payload_bytes) > 65536:
                        raise PlatformError(502, "LLM_RESPONSE_INVALID", "LLM Provider 响应不符合预期")
        parsed = json.loads(payload_bytes)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("choices"), list):
            raise PlatformError(502, "LLM_RESPONSE_INVALID", "LLM Provider 响应不符合预期")
    except httpx.TimeoutException:
        raise PlatformError(504, "LLM_CONNECTION_TIMEOUT", "LLM Provider 连接超时") from None
    except (httpx.HTTPError, json.JSONDecodeError):
        raise PlatformError(502, "LLM_CONNECTION_FAILED", "LLM Provider 连接验证失败") from None
