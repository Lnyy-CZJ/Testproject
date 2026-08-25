from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError
from app.models.configuration import ConfigActivation, ConfigDefinition, ConfigRelease, ConfigReleaseItem, Secret, SecretVersion
from app.models.llm import LlmProfile, ToolLlmBinding, UserLlmBinding
from app.services.secret_store import decrypt_secret_version, load_secret_cipher


def active_release(database: Session, environment_id: str, owner_type: str, owner_id: str) -> ConfigRelease | None:
    """读取指定环境与作用域的唯一激活 Release。"""

    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == environment_id,
        ConfigActivation.owner_type == owner_type,
        ConfigActivation.owner_id == owner_id,
    ))
    return database.get(ConfigRelease, activation.active_release_id) if activation else None


def release_values(database: Session, release: ConfigRelease | None) -> tuple[dict[str, Any], dict[str, tuple[Secret, SecretVersion]]]:
    """按定义 key 展开普通值和已冻结 Secret Version 元数据。"""

    if release is None:
        return {}, {}
    definitions = {
        row.id: row for row in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == release.owner_type,
            ConfigDefinition.owner_id == release.owner_id,
        )).all()
    }
    normal = {
        row.key: row.default_value for row in definitions.values()
        if row.sensitivity == "normal" and row.default_value is not None
    }
    secrets: dict[str, tuple[Secret, SecretVersion]] = {}
    for item in database.scalars(select(ConfigReleaseItem).where(ConfigReleaseItem.release_id == release.id)).all():
        definition = definitions.get(item.definition_id)
        if definition is None:
            continue
        if definition.sensitivity == "normal":
            normal[definition.key] = item.value_json
        elif item.secret_version_id:
            secret_version = database.get(SecretVersion, item.secret_version_id)
            secret = database.get(Secret, secret_version.secret_id) if secret_version else None
            if secret and (secret.environment_id, secret.owner_type, secret.owner_id) == (
                release.environment_id, release.owner_type, release.owner_id,
            ):
                secrets[definition.key] = (secret, secret_version)
    return normal, secrets


def validate_llm_release(database: Session, release: ConfigRelease) -> None:
    """补充 LLM 作用域发布约束，防止 Binding 指向草稿或归档 Profile。"""

    if release.owner_type == "llm_profile":
        profile = database.get(LlmProfile, release.owner_id)
        if profile is None or profile.is_archived:
            raise PlatformError(422, "LLM_PROFILE_NOT_FOUND", "LLM Profile 不存在或已归档")
        values, _ = release_values(database, release)
        base_url = values.get("BASE_URL")
        if isinstance(base_url, str):
            validate_provider_target(
                base_url, provider_allowlist(database, release.environment_id),
                production=release.environment_id == "prod",
            )
        return
    if release.owner_type != "llm_binding":
        return
    values, binding_secrets = release_values(database, release)
    profile_id = values.get("PROFILE_ID")
    profile = database.get(LlmProfile, profile_id) if isinstance(profile_id, str) else None
    if profile is None or profile.is_archived:
        raise PlatformError(422, "LLM_PROFILE_NOT_FOUND", "绑定的 LLM Profile 不存在或已归档")
    profile_release = active_release(database, release.environment_id, "llm_profile", profile.id)
    if profile_release is None:
        raise PlatformError(422, "LLM_CONFIG_NOT_READY", "绑定的 LLM Profile 尚未发布")
    profile_values, profile_secrets = release_values(database, profile_release)
    if not profile_values.get("ENABLED", True) or not values.get("ENABLED", True):
        raise PlatformError(422, "LLM_CONFIG_NOT_READY", "LLM Profile 或工具绑定未启用")
    override = database.scalar(select(Secret).where(
        Secret.environment_id == release.environment_id,
        Secret.owner_type == "llm_binding", Secret.owner_id == release.owner_id,
        Secret.current_version_id.is_not(None),
    ))
    if override is None and "API_KEY" not in profile_secrets:
        raise PlatformError(422, "LLM_SECRET_UNAVAILABLE", "LLM API Key 尚未配置")


def resolve_legacy_llm_snapshot(
    database: Session,
    settings: Settings,
    environment_id: str,
    tool_id: str,
    capability_key: str,
    *,
    include_secrets: bool,
) -> dict[str, Any]:
    """解析迁移期全局 LLM 快照，仅供旧管理接口兼容使用。

    新任务不得调用此函数。它被单独命名后，任何缺少用户上下文的调用都会在
    代码评审和搜索中显式可见，避免误把 global Binding 当成个人配置兜底。
    """

    binding = database.scalar(select(ToolLlmBinding).where(
        ToolLlmBinding.tool_id == tool_id,
        ToolLlmBinding.capability_key == capability_key,
    ))
    if binding is None:
        raise PlatformError(404, "LLM_BINDING_NOT_FOUND", "LLM 工具绑定不存在")
    binding_release = active_release(database, environment_id, "llm_binding", binding.id)
    binding_values, binding_secrets = release_values(database, binding_release)
    profile_id = binding_values.get("PROFILE_ID")
    profile = database.get(LlmProfile, profile_id) if isinstance(profile_id, str) else None
    if binding_release is None or profile is None or profile.is_archived:
        raise PlatformError(409, "LLM_CONFIG_NOT_READY", "LLM 配置尚未发布")
    profile_release = active_release(database, environment_id, "llm_profile", profile.id)
    profile_values, profile_secrets = release_values(database, profile_release)
    if profile_release is None or not profile_values.get("ENABLED", True) or not binding_values.get("ENABLED", True):
        raise PlatformError(409, "LLM_CONFIG_NOT_READY", "LLM 配置尚未启用")
    chosen_secret = binding_secrets.get("API_KEY_OVERRIDE") or profile_secrets.get("API_KEY")
    if chosen_secret is None:
        raise PlatformError(503, "LLM_SECRET_UNAVAILABLE", "LLM API Key 暂时不可用")
    secret, secret_version = chosen_secret
    effective = {
        "status": "ready", "binding_id": binding.id, "capability_key": binding.capability_key,
        "binding_release_id": binding_release.id, "binding_release_version": binding_release.version,
        "profile_id": profile.id, "profile_name": profile.name,
        "profile_release_id": profile_release.id, "profile_release_version": profile_release.version,
        "protocol": profile.protocol, "base_url": profile_values.get("BASE_URL"),
        "model": binding_values.get("MODEL_OVERRIDE") or profile_values.get("MODEL"),
        "temperature": binding_values.get("TEMPERATURE_OVERRIDE", profile_values.get("TEMPERATURE")),
        "max_tokens": binding_values.get("MAX_TOKENS_OVERRIDE", profile_values.get("MAX_TOKENS")),
        "timeout_seconds": binding_values.get("TIMEOUT_SECONDS_OVERRIDE", profile_values.get("TIMEOUT_SECONDS")),
        "api_key_configured": True, "api_key_version": secret_version.version,
    }
    if not effective["base_url"] or not effective["model"]:
        raise PlatformError(409, "LLM_CONFIG_NOT_READY", "LLM Base URL 或模型尚未配置")
    fingerprint = {
        "environment": environment_id, "tool": tool_id, "capability": capability_key,
        "binding_release": binding_release.id, "profile_release": profile_release.id,
        "secret_version": secret_version.id,
        **{key: effective[key] for key in ("base_url", "model", "temperature", "max_tokens", "timeout_seconds")},
    }
    effective["snapshot_id"] = "llms_" + hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if include_secrets:
        try:
            effective["api_key"] = decrypt_secret_version(
                database, load_secret_cipher(settings), secret, secret_version.id,
            )
        except (ValueError, KeyError):
            raise PlatformError(503, "LLM_SECRET_UNAVAILABLE", "LLM API Key 暂时不可用") from None
    return effective


def resolve_llm_snapshot(
    database: Session,
    settings: Settings,
    environment_id: str,
    tool_id: str,
    capability_key: str,
    user_id: str,
    *,
    include_secrets: bool,
) -> dict[str, Any]:
    """只从指定用户的 Profile 与 Binding 解析不可变 LLM 快照。

    参数说明:
        user_id: 已由可信 Runtime Context 解析出的登录用户 ID，不能来自业务请求体。
        include_secrets: false 时只计算版本元数据且完全不加载 KEK；true 时才解密
            已冻结的精确 SecretVersion。
    异常说明:
        PERSONAL_LLM_NOT_CONFIGURED: 任一用户级 Binding/Profile/Release/Key 缺失。
        LLM_SECRET_UNAVAILABLE: 已冻结 Secret 损坏或 KEK 不可用。

    解析路径从 ``UserLlmBinding.user_id`` 开始，绝不查询 global ``llm_binding``
    Activation，因此不存在 admin、legacy Profile 或环境变量回退。
    """

    catalog_binding = database.scalar(select(ToolLlmBinding).where(
        ToolLlmBinding.tool_id == tool_id,
        ToolLlmBinding.capability_key == capability_key,
    ))
    if catalog_binding is None:
        raise PlatformError(404, "LLM_BINDING_NOT_FOUND", "LLM 工具绑定不存在")
    user_binding = database.scalar(select(UserLlmBinding).where(
        UserLlmBinding.user_id == user_id,
        UserLlmBinding.binding_id == catalog_binding.id,
    ))
    if user_binding is None:
        raise PlatformError(
            409, "PERSONAL_LLM_NOT_CONFIGURED", "请先配置并发布个人 LLM 连接"
        )
    binding_release = active_release(
        database, environment_id, "user_llm_binding", user_binding.id
    )
    binding_values, binding_secrets = release_values(database, binding_release)
    profile_id = binding_values.get("PROFILE_ID")
    profile = database.scalar(select(LlmProfile).where(
        LlmProfile.owner_user_id == user_id,
        LlmProfile.id == profile_id,
        LlmProfile.is_archived.is_(False),
    )) if isinstance(profile_id, str) else None
    if binding_release is None or profile is None or not binding_values.get("ENABLED", True):
        raise PlatformError(
            409, "PERSONAL_LLM_NOT_CONFIGURED", "请先配置并发布个人 LLM 连接"
        )
    profile_release = active_release(
        database, environment_id, "llm_profile", profile.id
    )
    profile_values, profile_secrets = release_values(database, profile_release)
    if profile_release is None or not profile_values.get("ENABLED", True):
        raise PlatformError(
            409, "PERSONAL_LLM_NOT_CONFIGURED", "请先配置并发布个人 LLM 连接"
        )
    chosen_secret = binding_secrets.get("API_KEY_OVERRIDE") or profile_secrets.get("API_KEY")
    if chosen_secret is None:
        raise PlatformError(
            409, "PERSONAL_LLM_NOT_CONFIGURED", "请先配置并发布个人 LLM 连接"
        )
    secret, secret_version = chosen_secret
    effective = {
        "status": "ready",
        "binding_id": user_binding.id,
        "capability_key": catalog_binding.capability_key,
        "binding_release_id": binding_release.id,
        "binding_release_version": binding_release.version,
        "profile_id": profile.id,
        "profile_name": profile.name,
        "profile_release_id": profile_release.id,
        "profile_release_version": profile_release.version,
        "protocol": profile.protocol,
        "base_url": profile_values.get("BASE_URL"),
        "model": binding_values.get("MODEL_OVERRIDE") or profile_values.get("MODEL"),
        "temperature": binding_values.get(
            "TEMPERATURE_OVERRIDE", profile_values.get("TEMPERATURE")
        ),
        "max_tokens": binding_values.get(
            "MAX_TOKENS_OVERRIDE", profile_values.get("MAX_TOKENS")
        ),
        "timeout_seconds": binding_values.get(
            "TIMEOUT_SECONDS_OVERRIDE", profile_values.get("TIMEOUT_SECONDS")
        ),
        "api_key_configured": True,
        "api_key_version": secret_version.version,
        "api_key_secret_version_id": secret_version.id,
    }
    if not effective["base_url"] or not effective["model"]:
        raise PlatformError(
            409, "PERSONAL_LLM_NOT_CONFIGURED", "请先配置并发布个人 LLM 连接"
        )
    fingerprint = {
        "user": user_id,
        "environment": environment_id,
        "tool": tool_id,
        "capability": capability_key,
        "binding": user_binding.id,
        "binding_release": binding_release.id,
        "profile_release": profile_release.id,
        "secret_version": secret_version.id,
        **{
            key: effective[key]
            for key in (
                "base_url", "model", "temperature", "max_tokens", "timeout_seconds"
            )
        },
    }
    effective["snapshot_id"] = "llms_" + hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if include_secrets:
        try:
            effective["api_key"] = decrypt_secret_version(
                database, load_secret_cipher(settings), secret, secret_version.id
            )
        except (ValueError, KeyError):
            raise PlatformError(
                503, "LLM_SECRET_UNAVAILABLE", "LLM API Key 暂时不可用"
            ) from None
    return effective


def materialize_llm_snapshot(
    database: Session,
    settings: Settings,
    environment_id: str,
    tool_id: str,
    capability_key: str,
    user_id: str,
    *,
    binding_release_id: str,
    profile_release_id: str,
    secret_version_id: str,
) -> dict[str, Any]:
    """按规划阶段选择的个人 Release/SecretVersion 物化历史 LLM 快照。

    任一选择器对象必须重新从当前用户的 ``UserLlmBinding`` 开始验证。对象已被
    归档、跨用户/工具/环境、历史版本损坏或 Key 选择不一致时统一返回
    ``RUNTIME_SNAPSHOT_INVALID``，绝不切换到当前 active Release。
    """

    def invalid() -> PlatformError:
        return PlatformError(
            409, "RUNTIME_SNAPSHOT_INVALID", "任务配置快照无效，请重新提交任务"
        )

    catalog_binding = database.scalar(select(ToolLlmBinding).where(
        ToolLlmBinding.tool_id == tool_id,
        ToolLlmBinding.capability_key == capability_key,
    ))
    if catalog_binding is None:
        raise invalid()
    user_binding = database.scalar(select(UserLlmBinding).where(
        UserLlmBinding.user_id == user_id,
        UserLlmBinding.binding_id == catalog_binding.id,
    ))
    if user_binding is None:
        raise invalid()
    binding_release = database.get(ConfigRelease, binding_release_id)
    if binding_release is None or (
        binding_release.environment_id,
        binding_release.owner_type,
        binding_release.owner_id,
    ) != (environment_id, "user_llm_binding", user_binding.id):
        raise invalid()
    binding_values, binding_secrets = release_values(database, binding_release)
    profile_id = binding_values.get("PROFILE_ID")
    profile = database.scalar(select(LlmProfile).where(
        LlmProfile.owner_user_id == user_id,
        LlmProfile.id == profile_id,
        LlmProfile.is_archived.is_(False),
    )) if isinstance(profile_id, str) else None
    if profile is None or not binding_values.get("ENABLED", True):
        raise invalid()
    profile_release = database.get(ConfigRelease, profile_release_id)
    if profile_release is None or (
        profile_release.environment_id,
        profile_release.owner_type,
        profile_release.owner_id,
    ) != (environment_id, "llm_profile", profile.id):
        raise invalid()
    profile_values, profile_secrets = release_values(database, profile_release)
    if not profile_values.get("ENABLED", True):
        raise invalid()
    chosen_secret = binding_secrets.get("API_KEY_OVERRIDE") or profile_secrets.get("API_KEY")
    if chosen_secret is None or chosen_secret[1].id != secret_version_id:
        raise invalid()
    secret, secret_version = chosen_secret
    effective = {
        "status": "ready",
        "binding_id": user_binding.id,
        "capability_key": catalog_binding.capability_key,
        "binding_release_id": binding_release.id,
        "binding_release_version": binding_release.version,
        "profile_id": profile.id,
        "profile_name": profile.name,
        "profile_release_id": profile_release.id,
        "profile_release_version": profile_release.version,
        "protocol": profile.protocol,
        "base_url": profile_values.get("BASE_URL"),
        "model": binding_values.get("MODEL_OVERRIDE") or profile_values.get("MODEL"),
        "temperature": binding_values.get(
            "TEMPERATURE_OVERRIDE", profile_values.get("TEMPERATURE")
        ),
        "max_tokens": binding_values.get(
            "MAX_TOKENS_OVERRIDE", profile_values.get("MAX_TOKENS")
        ),
        "timeout_seconds": binding_values.get(
            "TIMEOUT_SECONDS_OVERRIDE", profile_values.get("TIMEOUT_SECONDS")
        ),
        "api_key_configured": True,
        "api_key_version": secret_version.version,
        "api_key_secret_version_id": secret_version.id,
    }
    if not effective["base_url"] or not effective["model"]:
        raise invalid()
    fingerprint = {
        "user": user_id,
        "environment": environment_id,
        "tool": tool_id,
        "capability": capability_key,
        "binding": user_binding.id,
        "binding_release": binding_release.id,
        "profile_release": profile_release.id,
        "secret_version": secret_version.id,
        **{
            key: effective[key]
            for key in (
                "base_url", "model", "temperature", "max_tokens", "timeout_seconds"
            )
        },
    }
    effective["snapshot_id"] = "llms_" + hashlib.sha256(
        json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    try:
        effective["api_key"] = decrypt_secret_version(
            database, load_secret_cipher(settings), secret, secret_version.id
        )
    except (ValueError, KeyError):
        raise PlatformError(
            503, "LLM_SECRET_UNAVAILABLE", "LLM API Key 暂时不可用"
        ) from None
    return effective


def provider_allowlist(database: Session, environment_id: str) -> set[str]:
    """读取版本化主机允许列表；无激活平台 Release 时使用安全默认值。"""

    release = active_release(database, environment_id, "platform", "platform")
    values, _ = release_values(database, release)
    raw = values.get("LLM_PROVIDER_HOST_ALLOWLIST", ["dashscope.aliyuncs.com"])
    return {str(item).lower().rstrip(".") for item in raw if isinstance(item, str)} if isinstance(raw, list) else set()


def validate_provider_target(base_url: str, allowlist: set[str], *, production: bool) -> str:
    """限制 Provider 目标，显式拒绝 SSRF 高风险 URL 与地址。"""

    parsed = urlsplit(base_url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in ({"https"} if production else {"http", "https"}) or not hostname:
        raise PlatformError(422, "LLM_TARGET_NOT_ALLOWED", "LLM Provider 地址不受允许")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or hostname not in allowlist:
        raise PlatformError(422, "LLM_TARGET_NOT_ALLOWED", "LLM Provider 地址不受允许")
    if hostname in {"localhost", "metadata.google.internal"}:
        raise PlatformError(422, "LLM_TARGET_NOT_ALLOWED", "LLM Provider 地址不受允许")
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except OSError:
        raise PlatformError(422, "LLM_TARGET_NOT_ALLOWED", "LLM Provider 地址无法解析") from None
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise PlatformError(422, "LLM_TARGET_NOT_ALLOWED", "LLM Provider 地址不受允许")
    return base_url.rstrip("/") + "/chat/completions"
