from __future__ import annotations

import base64
import importlib
import json

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.security import SecretCipher
from app.models.configuration import (
    ConfigActivation,
    ConfigDefinition,
    ConfigRelease,
    ConfigReleaseItem,
    Credential,
    CredentialItem,
    Environment,
    Secret,
    SecretVersion,
    UserCredential,
    UserCredentialItem,
)
from app.models.identity import User
from app.models.llm import LlmProfile, ToolLlmBinding, UserLlmBinding
from app.models.tool import Tool
from app.services.llm import (
    resolve_legacy_llm_snapshot,
    resolve_llm_snapshot,
    validate_provider_target,
)
from app.services.secret_store import decrypt_secret_version, replace_secret


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

        safe = resolve_legacy_llm_snapshot(database, settings, "dev", "functional-test-agent", "default", include_secrets=False)
        full = resolve_legacy_llm_snapshot(database, settings, "dev", "functional-test-agent", "default", include_secrets=True)
        assert safe["model"] == "tool-model"
        assert "api_key" not in safe
        assert full["api_key"] == "sentinel-api-key"
        assert safe["snapshot_id"] == full["snapshot_id"]
        assert "sentinel" not in safe["snapshot_id"]
        with pytest.raises(PlatformError) as missing_personal:
            resolve_llm_snapshot(
                database, settings, "dev", "functional-test-agent", "default",
                "usr_without_personal_binding", include_secrets=True,
            )
        assert missing_personal.value.code == "PERSONAL_LLM_NOT_CONFIGURED"


def test_provider_target_rejects_query_and_loopback() -> None:
    """即使管理员加入允许列表，高风险 URL 结构和非公网地址仍被代码拒绝。"""

    with pytest.raises(PlatformError) as query_error:
        validate_provider_target("https://example.com/v1?token=x", {"example.com"}, production=True)
    assert query_error.value.code == "LLM_TARGET_NOT_ALLOWED"
    with pytest.raises(PlatformError) as loopback_error:
        validate_provider_target("http://127.0.0.1/v1", {"127.0.0.1"}, production=False)
    assert loopback_error.value.code == "LLM_TARGET_NOT_ALLOWED"


def _seed_legacy_personal_migration(database, tmp_path):
    """构造包含一个 legacy Credential 和一个全局 LLM Binding 的迁移基线。"""

    kek = tmp_path / "migration-kek.json"
    kek.write_text(json.dumps({
        "active": "v1", "keys": {"v1": base64.b64encode(b"m" * 32).decode()},
    }), encoding="utf-8")
    settings = Settings(secret_kek_file=str(kek), platform_runtime_env="dev")
    cipher = SecretCipher.from_file(kek)
    database.add_all([
        Environment(id="dev", name="开发环境"),
        Environment(id="prod", name="生产环境"),
        Tool(
            id="truthy-search", name="检索评测", description="",
            entry_url="/truthy-search/", health_url="http://truthy/health",
            short_code="SEARCH", icon_key="search", category="evaluation",
            features=[], sort_order=1,
        ),
        Tool(
            id="functional-test-agent", name="功能测试智能体", description="",
            entry_url="/functional-test-agent/", health_url="http://agent/health",
            short_code="AI", icon_key="ai", category="ai", features=[], sort_order=2,
        ),
        User(
            id="usr_admin", username="admin", username_normalized="admin",
            display_name="管理员", password_hash="unused", status="active",
        ),
        User(
            id="usr_other", username="other", username_normalized="other",
            display_name="其他用户", password_hash="unused", status="active",
        ),
    ])
    definition = ConfigDefinition(
        id="truthy-search.AUTH_TOKEN", key="AUTH_TOKEN", display_name="Access Token",
        description="", owner_type="tool", owner_id="truthy-search",
        group_key="credentials", value_type="secret", sensitivity="secret",
        required=True, validation_schema={}, apply_mode="next_task", editable=True,
        value_scope="user", credential_provider_type="gateway_session",
    )
    device_definition = ConfigDefinition(
        id="truthy-search.DEVICE_ID", key="DEVICE_ID", display_name="设备 ID",
        description="", owner_type="tool", owner_id="truthy-search",
        group_key="credentials", value_type="secret", sensitivity="secret",
        required=True, validation_schema={}, apply_mode="next_task", editable=True,
        value_scope="user", credential_provider_type="gateway_session",
    )
    database.add_all([definition, device_definition])
    legacy_secret = Secret(
        id="sec_legacy_token", environment_id="dev", owner_type="tool",
        owner_id="truthy-search", definition_id=definition.id, status="missing",
    )
    database.add(legacy_secret)
    database.flush()
    legacy_version = replace_secret(
        database, cipher, legacy_secret, "sentinel-legacy-token", "test"
    )
    # legacy Agent 的 CredentialItem 只记录本次刷新字段；未轮换的登录材料
    # 仍保存在同作用域 Secret 当前版本，迁移必须合并两者才能形成完整个人版本。
    legacy_device_secret = Secret(
        id="sec_legacy_device", environment_id="dev", owner_type="tool",
        owner_id="truthy-search", definition_id=device_definition.id,
        status="missing",
    )
    database.add(legacy_device_secret)
    database.flush()
    replace_secret(
        database, cipher, legacy_device_secret, "sentinel-legacy-device", "test"
    )
    legacy_credential = Credential(
        id="cred_legacy", tool_id="truthy-search", environment_id="dev",
        provider_type="gateway_session", status="healthy", current_version=1,
    )
    database.add(legacy_credential)
    database.flush()
    database.add(CredentialItem(
        credential_id=legacy_credential.id, credential_version=1,
        key="AUTH_TOKEN", secret_version_id=legacy_version.id,
    ))

    profile = LlmProfile(
        id="llmp_legacy", name="Legacy Model", name_normalized="legacy model",
        protocol="openai_compatible", created_by="test",
    )
    binding = ToolLlmBinding(
        id="llmb_functional", tool_id="functional-test-agent",
        capability_key="default", display_name="默认模型", created_by="test",
    )
    binding_definition = _definition(
        "llm_binding", binding.id, "PROFILE_ID", default=profile.id
    )
    binding_secret_definition = _definition(
        "llm_binding", binding.id, "API_KEY_OVERRIDE", sensitivity="secret"
    )
    database.add_all([profile, binding, binding_definition, binding_secret_definition])
    binding_release = ConfigRelease(
        id="rel_legacy_binding", environment_id="dev", owner_type="llm_binding",
        owner_id=binding.id, version=1, revision=1, status="active", created_by="test",
    )
    database.add(binding_release)
    database.flush()
    binding_secret = Secret(
        id="sec_legacy_binding_override", environment_id="dev",
        owner_type="llm_binding", owner_id=binding.id,
        definition_id=binding_secret_definition.id, status="missing",
    )
    database.add(binding_secret)
    database.flush()
    binding_secret_version = replace_secret(
        database, cipher, binding_secret, "sentinel-binding-override", "test"
    )
    database.add_all([
        ConfigReleaseItem(
            release_id=binding_release.id, definition_id=binding_definition.id,
            value_json=profile.id,
        ),
        ConfigReleaseItem(
            release_id=binding_release.id,
            definition_id=binding_secret_definition.id,
            secret_version_id=binding_secret_version.id,
        ),
        ConfigActivation(
            environment_id="dev", owner_type="llm_binding", owner_id=binding.id,
            active_release_id=binding_release.id,
        ),
    ])
    database.commit()
    return settings, cipher


def test_personal_migration_dry_run_apply_and_repeat_are_safe(
    database_factory, tmp_path
) -> None:
    """迁移必须默认可预演、只归 admin，并在第二次 apply 时完全幂等。"""

    migration = importlib.import_module("app.migrate_personal_credentials")
    with database_factory() as database:
        settings, cipher = _seed_legacy_personal_migration(database, tmp_path)
        before_versions = database.scalar(select(func.count(SecretVersion.id)))

        dry_run = migration.migrate_personal_credentials(
            database, settings, environment_id="dev", admin_username="admin",
            apply=False,
        )
        safe_dry_run = dry_run.to_safe_dict()
        assert safe_dry_run["mode"] == "dry-run"
        assert safe_dry_run["credentials"] == {"new": 1, "skipped": 0}
        assert safe_dry_run["profiles"] == {"new": 1, "skipped": 0}
        assert safe_dry_run["bindings"] == {"new": 1, "skipped": 0}
        assert safe_dry_run["conflicts"] == 0
        assert "sentinel-legacy-token" not in json.dumps(safe_dry_run)
        assert database.scalar(select(func.count(UserCredential.id))) == 0
        assert database.scalar(select(func.count(UserLlmBinding.id))) == 0
        assert database.get(LlmProfile, "llmp_legacy").owner_user_id is None
        assert database.scalar(select(func.count(SecretVersion.id))) == before_versions

        applied = migration.migrate_personal_credentials(
            database, settings, environment_id="dev", admin_username="admin",
            apply=True,
        )
        assert applied.to_safe_dict()["conflicts"] == 0
        target = database.scalar(select(UserCredential).where(
            UserCredential.user_id == "usr_admin",
            UserCredential.tool_id == "truthy-search",
            UserCredential.environment_id == "dev",
            UserCredential.provider_type == "gateway_session",
        ))
        assert target is not None and target.id.startswith("ucred_")
        assert database.scalar(select(UserCredential).where(
            UserCredential.user_id == "usr_other"
        )) is None
        target_item = database.scalar(select(UserCredentialItem).where(
            UserCredentialItem.credential_id == target.id,
            UserCredentialItem.key == "AUTH_TOKEN",
        ))
        target_version = database.get(SecretVersion, target_item.secret_version_id)
        target_secret = database.get(Secret, target_version.secret_id)
        assert (target_secret.owner_type, target_secret.owner_id) == (
            "user_credential", target.id,
        )
        assert decrypt_secret_version(
            database, cipher, target_secret, target_version.id
        ) == "sentinel-legacy-token"
        device_item = database.scalar(select(UserCredentialItem).where(
            UserCredentialItem.credential_id == target.id,
            UserCredentialItem.key == "DEVICE_ID",
        ))
        device_version = database.get(SecretVersion, device_item.secret_version_id)
        device_secret = database.get(Secret, device_version.secret_id)
        assert decrypt_secret_version(
            database, cipher, device_secret, device_version.id
        ) == "sentinel-legacy-device"
        assert database.get(LlmProfile, "llmp_legacy").owner_user_id == "usr_admin"
        personal_binding = database.scalar(select(UserLlmBinding).where(
            UserLlmBinding.user_id == "usr_admin",
            UserLlmBinding.binding_id == "llmb_functional",
        ))
        assert personal_binding is not None
        personal_activation = database.scalar(select(ConfigActivation).where(
            ConfigActivation.environment_id == "dev",
            ConfigActivation.owner_type == "user_llm_binding",
            ConfigActivation.owner_id == personal_binding.id,
        ))
        assert personal_activation is not None
        personal_release_items = list(database.scalars(select(ConfigReleaseItem).where(
            ConfigReleaseItem.release_id == personal_activation.active_release_id,
            ConfigReleaseItem.secret_version_id.is_not(None),
        )).all())
        assert len(personal_release_items) == 1
        binding_target_version = database.get(
            SecretVersion, personal_release_items[0].secret_version_id
        )
        binding_target_secret = database.get(
            Secret, binding_target_version.secret_id
        )
        assert binding_target_secret.owner_type == "user_llm_binding"
        assert decrypt_secret_version(
            database, cipher, binding_target_secret, binding_target_version.id
        ) == "sentinel-binding-override"
        after_apply_versions = database.scalar(select(func.count(SecretVersion.id)))

        repeated = migration.migrate_personal_credentials(
            database, settings, environment_id="dev", admin_username="admin",
            apply=True,
        )
        assert repeated.to_safe_dict()["credentials"] == {"new": 0, "skipped": 1}
        assert repeated.to_safe_dict()["profiles"] == {"new": 0, "skipped": 1}
        assert repeated.to_safe_dict()["bindings"] == {"new": 0, "skipped": 1}
        assert database.scalar(select(func.count(SecretVersion.id))) == after_apply_versions


def test_personal_migration_ignores_known_legacy_admin_login_transients(
    database_factory, tmp_path
) -> None:
    """legacy 登录响应中的小写操作者字段不能阻断完整 Secret 迁移。"""

    migration = importlib.import_module("app.migrate_personal_credentials")
    with database_factory() as database:
        settings, _cipher = _seed_legacy_personal_migration(database, tmp_path)
        credential = database.get(Credential, "cred_legacy")
        credential.provider_type = "admin_login"
        for definition in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == "tool",
            ConfigDefinition.owner_id == "truthy-search",
            ConfigDefinition.value_scope == "user",
        )).all():
            definition.credential_provider_type = "admin_login"
        database.add(CredentialItem(
            credential_id=credential.id,
            credential_version=credential.current_version,
            key="operator_id",
            value_json="legacy-operator",
        ))
        database.commit()

        report = migration.migrate_personal_credentials(
            database, settings, environment_id="dev", admin_username="admin",
            apply=False,
        )
        assert report.credentials == {"new": 1, "skipped": 0}
        assert report.conflicts == 0


def test_personal_migration_rejects_conflict_without_overwriting(
    database_factory, tmp_path
) -> None:
    """admin 自行更新个人值后，重复迁移必须整笔失败且保留用户的新值。"""

    migration = importlib.import_module("app.migrate_personal_credentials")
    with database_factory() as database:
        settings, cipher = _seed_legacy_personal_migration(database, tmp_path)
        migration.migrate_personal_credentials(
            database, settings, environment_id="dev", admin_username="admin", apply=True
        )
        target = database.scalar(select(UserCredential).where(
            UserCredential.user_id == "usr_admin"
        ))
        old_item = database.scalar(select(UserCredentialItem).where(
            UserCredentialItem.credential_id == target.id,
            UserCredentialItem.credential_version == target.current_version,
        ))
        old_version = database.get(SecretVersion, old_item.secret_version_id)
        target_secret = database.get(Secret, old_version.secret_id)
        new_version = replace_secret(
            database, cipher, target_secret, "admin-personal-token", "usr_admin"
        )
        target.current_version += 1
        database.add(UserCredentialItem(
            credential_id=target.id, credential_version=target.current_version,
            key="AUTH_TOKEN", secret_version_id=new_version.id,
        ))
        database.commit()

        with pytest.raises(migration.PersonalMigrationConflict):
            migration.migrate_personal_credentials(
                database, settings, environment_id="dev", admin_username="admin",
                apply=True,
            )
        database.refresh(target_secret)
        assert decrypt_secret_version(
            database, cipher, target_secret, target_secret.current_version_id
        ) == "admin-personal-token"


def test_personal_migration_requires_matching_environment_and_active_admin(
    database_factory, tmp_path
) -> None:
    """环境不匹配或没有唯一有效 admin 时必须在写入前失败关闭。"""

    migration = importlib.import_module("app.migrate_personal_credentials")
    with database_factory() as database:
        settings, _cipher = _seed_legacy_personal_migration(database, tmp_path)
        with pytest.raises(migration.PersonalMigrationPreconditionError):
            migration.migrate_personal_credentials(
                database, settings, environment_id="prod", admin_username="admin",
                apply=True,
            )
        database.get(User, "usr_admin").status = "disabled"
        database.commit()
        with pytest.raises(migration.PersonalMigrationPreconditionError):
            migration.migrate_personal_credentials(
                database, settings, environment_id="dev", admin_username="admin",
                apply=True,
            )
