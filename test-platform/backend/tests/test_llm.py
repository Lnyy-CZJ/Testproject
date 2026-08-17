from __future__ import annotations

import base64
import json

import pytest

from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.security import SecretCipher
from app.models.configuration import ConfigActivation, ConfigDefinition, ConfigRelease, ConfigReleaseItem, Environment, Secret
from app.models.llm import LlmProfile, ToolLlmBinding
from app.models.tool import Tool
from app.services.llm import resolve_llm_snapshot, validate_provider_target
from app.services.secret_store import replace_secret


def _definition(owner_type: str, owner_id: str, key: str, *, sensitivity: str = "normal", default=None):
    return ConfigDefinition(
        id=f"{owner_id}.{key}", key=key, display_name=key, description="",
        owner_type=owner_type, owner_id=owner_id, group_key="model",
        value_type="secret" if sensitivity == "secret" else "string",
        sensitivity=sensitivity, required=key in {"BASE_URL", "MODEL", "API_KEY", "PROFILE_ID"},
        default_value=default, validation_schema={}, apply_mode="next_task", editable=True,
    )


def test_llm_snapshot_merges_binding_and_never_hashes_plaintext(database_factory, tmp_path) -> None:
    """Binding 覆盖应形成固定快照；安全摘要不解密，快照指纹不包含 Key。"""

    kek = tmp_path / "kek.json"
    kek.write_text(json.dumps({
        "active": "v1", "keys": {"v1": base64.b64encode(b"k" * 32).decode()},
    }), encoding="utf-8")
    settings = Settings(secret_kek_file=str(kek))
    cipher = SecretCipher.from_file(kek)
    with database_factory() as database:
        database.add(Environment(id="dev", name="开发环境"))
        database.add(Tool(
            id="functional-test-agent", name="功能测试智能体", description="",
            entry_url="/functional-test-agent/", health_url="http://tool/health",
            short_code="AI", icon_key="ai", category="ai", features=[], sort_order=1,
        ))
        database.add(LlmProfile(
            id="llmp_test", name="测试 Profile", name_normalized="测试 profile",
            protocol="openai_compatible", created_by="test",
        ))
        database.add(ToolLlmBinding(
            id="llmb_test", tool_id="functional-test-agent", capability_key="default",
            display_name="默认模型", description="", created_by="test",
        ))
        profile_definitions = [
            _definition("llm_profile", "llmp_test", "BASE_URL"),
            _definition("llm_profile", "llmp_test", "MODEL"),
            _definition("llm_profile", "llmp_test", "API_KEY", sensitivity="secret"),
        ]
        binding_definitions = [
            _definition("llm_binding", "llmb_test", "PROFILE_ID"),
            _definition("llm_binding", "llmb_test", "MODEL_OVERRIDE"),
        ]
        database.add_all(profile_definitions + binding_definitions)
        profile_release = ConfigRelease(
            id="rel_profile", environment_id="dev", owner_type="llm_profile",
            owner_id="llmp_test", version=1, status="active", created_by="test",
        )
        binding_release = ConfigRelease(
            id="rel_binding", environment_id="dev", owner_type="llm_binding",
            owner_id="llmb_test", version=1, status="active", created_by="test",
        )
        database.add_all([profile_release, binding_release])
        database.flush()
        database.add_all([
            ConfigReleaseItem(release_id="rel_profile", definition_id="llmp_test.BASE_URL", value_json="https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ConfigReleaseItem(release_id="rel_profile", definition_id="llmp_test.MODEL", value_json="shared-model"),
            ConfigReleaseItem(release_id="rel_binding", definition_id="llmb_test.PROFILE_ID", value_json="llmp_test"),
            ConfigReleaseItem(release_id="rel_binding", definition_id="llmb_test.MODEL_OVERRIDE", value_json="tool-model"),
        ])
        secret = Secret(
            id="sec_test", environment_id="dev", owner_type="llm_profile",
            owner_id="llmp_test", definition_id="llmp_test.API_KEY", status="missing",
        )
        database.add(secret); database.flush()
        version = replace_secret(database, cipher, secret, "sentinel-api-key", "test")
        database.flush()
        database.add(ConfigReleaseItem(
            release_id="rel_profile", definition_id="llmp_test.API_KEY",
            secret_version_id=version.id,
        ))
        database.add_all([
            ConfigActivation(environment_id="dev", owner_type="llm_profile", owner_id="llmp_test", active_release_id="rel_profile"),
            ConfigActivation(environment_id="dev", owner_type="llm_binding", owner_id="llmb_test", active_release_id="rel_binding"),
        ])
        database.commit()

        safe = resolve_llm_snapshot(database, settings, "dev", "functional-test-agent", "default", include_secrets=False)
        full = resolve_llm_snapshot(database, settings, "dev", "functional-test-agent", "default", include_secrets=True)
        assert safe["model"] == "tool-model"
        assert "api_key" not in safe
        assert full["api_key"] == "sentinel-api-key"
        assert safe["snapshot_id"] == full["snapshot_id"]
        assert "sentinel" not in safe["snapshot_id"]


def test_provider_target_rejects_query_and_loopback() -> None:
    """即使管理员加入允许列表，高风险 URL 结构和非公网地址仍被代码拒绝。"""

    with pytest.raises(PlatformError) as query_error:
        validate_provider_target("https://example.com/v1?token=x", {"example.com"}, production=True)
    assert query_error.value.code == "LLM_TARGET_NOT_ALLOWED"
    with pytest.raises(PlatformError) as loopback_error:
        validate_provider_target("http://127.0.0.1/v1", {"127.0.0.1"}, production=False)
    assert loopback_error.value.code == "LLM_TARGET_NOT_ALLOWED"
