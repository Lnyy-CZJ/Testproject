from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, current_auth_context, require_csrf
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.core.security import new_id
from app.db.session import get_db
from app.models.configuration import ConfigActivation, ConfigDefinition, ConfigRelease, ConfigReleaseItem, Secret
from app.models.llm import LlmProfile, ToolLlmBinding
from app.schemas.auth import MessageResponse
from app.schemas.llm import (
    LlmBindingResponse, LlmConnectionTestRequest, LlmConnectionTestResponse,
    LlmEffectiveConfigResponse, LlmProfileCreateRequest, LlmProfileResponse,
    LlmProfileUpdateRequest,
)
from app.services.audit import add_audit_event
from app.services.authorization import has_platform_permission, has_tool_permission
from app.services.llm import (
    active_release, provider_allowlist, release_values, resolve_llm_snapshot,
    validate_provider_target,
)


router = APIRouter(prefix="/llm", tags=["llm"])


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
        editable=True, sort_order=sort_order,
    ) for key, display, value_type, sensitivity, required, default, schema, sort_order in specs]


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
        select(LlmProfile).order_by(LlmProfile.is_archived, LlmProfile.name)
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
    if profile is None:
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
    if profile is None:
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
    return LlmEffectiveConfigResponse(**resolve_llm_snapshot(
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
    snapshot = resolve_llm_snapshot(database, settings, payload.environment_id, binding.tool_id,
                                    binding.capability_key, include_secrets=True)
    endpoint = validate_provider_target(
        snapshot["base_url"], provider_allowlist(database, payload.environment_id),
        production=payload.environment_id == "prod",
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
    add_audit_event(database, action="llm.connection.test", resource_type="llm_binding",
                    resource_id=binding.id, tool_id=binding.tool_id,
                    environment_id=payload.environment_id, outcome="success",
                    request=request, actor=context.user, metadata={"snapshot_id": snapshot["snapshot_id"]})
    database.commit()
    return LlmConnectionTestResponse(status="ok", checked_at=datetime.now(UTC),
                                     model=snapshot["model"], snapshot_id=snapshot["snapshot_id"])
