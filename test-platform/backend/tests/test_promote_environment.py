from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.security import SecretCipher
from app.models.access import Project
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
    ToolProjectScope,
)
from app.models.identity import ToolClient
from app.models.tool import Tool
from app.promote_environment import promote_environment, promotion_summary
from app.services.secret_store import decrypt_secret_version, replace_secret


def _seed(database, cipher: SecretCipher) -> None:
    database.add_all([
        Environment(id="dev", name="开发环境"),
        Environment(id="prod", name="生产环境"),
        Tool(
            id="tool-a", name="Tool A", description="test", entry_url="/tool-a",
            health_url="http://tool-a/health", short_code="TA", icon_key="tool",
            category="test", features=[],
        ),
        ConfigDefinition(
            id="tool-a.NORMAL", key="NORMAL", display_name="普通配置", owner_type="tool",
            owner_id="tool-a", value_type="string", sensitivity="normal",
        ),
        ConfigDefinition(
            id="tool-a.SECRET", key="SECRET", display_name="敏感配置", owner_type="tool",
            owner_id="tool-a", value_type="string", sensitivity="secret",
        ),
    ])
    database.flush()
    secret = Secret(
        id="sec_dev", environment_id="dev", owner_type="tool",
        owner_id="tool-a", definition_id="tool-a.SECRET",
    )
    database.add(secret)
    database.flush()
    secret_version = replace_secret(database, cipher, secret, "same-value", "test")
    release = ConfigRelease(
        id="rel_dev", environment_id="dev", owner_type="tool", owner_id="tool-a",
        version=3, revision=1, status="active", created_by="test", published_by="test",
    )
    database.add(release)
    database.flush()
    database.add_all([
        ConfigReleaseItem(release_id=release.id, definition_id="tool-a.NORMAL", value_json="value"),
        ConfigReleaseItem(release_id=release.id, definition_id="tool-a.SECRET", secret_version_id=secret_version.id),
        ConfigActivation(environment_id="dev", owner_type="tool", owner_id="tool-a", active_release_id=release.id),
        Credential(id="cred_dev", tool_id="tool-a", environment_id="dev", provider_type="login", status="healthy", current_version=2),
        ToolClient(id="client_dev", tool_id="tool-a", environment_id="dev", token_hash="a" * 64, capabilities=[], status="active"),
    ])
    database.flush()
    database.add(CredentialItem(
        credential_id="cred_dev", credential_version=2, key="session", value_json="do-not-copy",
    ))


def _seed_project_scoped_runtime_material(database, cipher: SecretCipher) -> None:
    """补充一组只能留在 dev/test 的项目级运行材料。

    这组数据与普通 Tool 配置共用 Definition，但所有权锚定到 Runtime Scope；
    环境提升若复制它们，就会把 test Gateway、Secret 或登录凭证带入 prod。
    """

    database.add(Project(
        id="project-a", code="PROJECT_A", name="Project A", description="test",
    ))
    database.flush()
    scope = ToolProjectScope(
        id="scope_dating_dev_test",
        environment_id="dev",
        tool_id="tool-a",
        platform_project_id="project-a",
        project_id="dating",
        target_env="test",
        display_name="Dating AI Assistant",
        status="active",
        is_default=True,
        revision=1,
        created_by="test",
        updated_by="test",
    )
    database.add(scope)
    database.flush()
    secret = Secret(
        id="sec_scope_dev",
        environment_id="dev",
        owner_type="tool_project_scope",
        owner_id=scope.id,
        definition_id="tool-a.SECRET",
    )
    database.add(secret)
    database.flush()
    secret_version = replace_secret(
        database, cipher, secret, "test-only-secret", "test",
    )
    release = ConfigRelease(
        id="rel_scope_dev",
        environment_id="dev",
        owner_type="tool_project_scope",
        owner_id=scope.id,
        version=1,
        revision=1,
        status="active",
        created_by="test",
        published_by="test",
    )
    database.add(release)
    database.flush()
    database.add_all([
        ConfigReleaseItem(
            release_id=release.id,
            definition_id="tool-a.NORMAL",
            value_json="https://gateway.test.example.com",
        ),
        ConfigReleaseItem(
            release_id=release.id,
            definition_id="tool-a.SECRET",
            secret_version_id=secret_version.id,
        ),
        ConfigActivation(
            environment_id="dev",
            owner_type="tool_project_scope",
            owner_id=scope.id,
            active_release_id=release.id,
        ),
        Credential(
            id="cred_scope_dev",
            tool_id="tool-a",
            environment_id="dev",
            runtime_scope_id=scope.id,
            provider_type="scoped-login",
            status="healthy",
            current_version=1,
        ),
    ])
    database.flush()


def _seed_legacy_api_autotest_runtime_material(database, cipher: SecretCipher) -> None:
    """补充迁移前遗留的 API AutoTest Tool 级 test 配置和凭证。

    新版运行时只接受 Runtime Scope 快照，但旧 Release 仍保留作审计。首次生产提升
    不能因为它们是 Tool 级数据就复制到 prod，否则仍可能保存 test Gateway/Token。
    """

    database.add(Tool(
        id="api-autotest",
        name="API AutoTest",
        description="test",
        entry_url="/api-autotest",
        health_url="http://api-autotest/health",
        short_code="API",
        icon_key="api",
        category="test",
        features=[],
    ))
    database.add_all([
        ConfigDefinition(
            id="api-autotest.NORMAL",
            key="gateway.base_url",
            display_name="Gateway",
            owner_type="tool",
            owner_id="api-autotest",
            value_type="string",
            sensitivity="normal",
        ),
        ConfigDefinition(
            id="api-autotest.SECRET",
            key="ADMIN_TOKEN",
            display_name="Admin Token",
            owner_type="tool",
            owner_id="api-autotest",
            value_type="string",
            sensitivity="secret",
        ),
    ])
    database.flush()
    secret = Secret(
        id="sec_api_autotest_legacy_dev",
        environment_id="dev",
        owner_type="tool",
        owner_id="api-autotest",
        definition_id="api-autotest.SECRET",
    )
    database.add(secret)
    database.flush()
    secret_version = replace_secret(
        database, cipher, secret, "legacy-test-token", "test",
    )
    release = ConfigRelease(
        id="rel_api_autotest_legacy_dev",
        environment_id="dev",
        owner_type="tool",
        owner_id="api-autotest",
        version=1,
        revision=1,
        status="active",
        created_by="test",
        published_by="test",
    )
    database.add(release)
    database.flush()
    database.add_all([
        ConfigReleaseItem(
            release_id=release.id,
            definition_id="api-autotest.NORMAL",
            value_json="https://gateway.test.example.com",
        ),
        ConfigReleaseItem(
            release_id=release.id,
            definition_id="api-autotest.SECRET",
            secret_version_id=secret_version.id,
        ),
        ConfigActivation(
            environment_id="dev",
            owner_type="tool",
            owner_id="api-autotest",
            active_release_id=release.id,
        ),
        Credential(
            id="cred_api_autotest_legacy_dev",
            tool_id="api-autotest",
            environment_id="dev",
            provider_type="admin_session",
            status="healthy",
            current_version=1,
        ),
    ])
    database.flush()


def test_summary_is_read_only(database_factory) -> None:
    cipher = SecretCipher({"v1": b"a" * 32}, "v1")
    with database_factory() as database:
        _seed(database, cipher)
        database.commit()
        assert promotion_summary(database, "dev").__dict__ == {
            "activations": 1, "secrets": 1, "credentials": 1, "clients": 1,
        }
        assert database.scalar(select(func.count()).select_from(ConfigRelease).where(
            ConfigRelease.environment_id == "prod",
        )) == 0


def test_promotion_reencrypts_and_does_not_copy_sessions(database_factory) -> None:
    cipher = SecretCipher({"v1": b"a" * 32, "prod-v1": b"b" * 32}, "prod-v1")
    with database_factory() as database:
        _seed(database, SecretCipher({"v1": b"a" * 32}, "v1"))
        summary = promote_environment(
            database, cipher, "dev", "prod", copy_secrets=True,
            seed_credentials=True, require_empty_target=True,
        )
        database.commit()
        assert summary.activations == 1
        target_secret = database.scalar(select(Secret).where(Secret.environment_id == "prod"))
        target_version = database.get(SecretVersion, target_secret.current_version_id)
        source_version = database.scalar(select(SecretVersion).join(Secret).where(Secret.environment_id == "dev"))
        assert target_version.kek_version == "prod-v1"
        assert target_version.ciphertext != source_version.ciphertext
        assert decrypt_secret_version(database, cipher, target_secret, target_version.id) == "same-value"
        target_release = database.scalar(select(ConfigRelease).where(ConfigRelease.environment_id == "prod"))
        values = list(database.scalars(select(ConfigReleaseItem).where(
            ConfigReleaseItem.release_id == target_release.id,
        )).all())
        assert {item.definition_id for item in values} == {"tool-a.NORMAL", "tool-a.SECRET"}
        target_credential = database.scalar(select(Credential).where(Credential.environment_id == "prod"))
        assert (target_credential.status, target_credential.current_version) == ("pending_validation", 0)
        assert database.scalar(select(func.count()).select_from(CredentialItem).where(
            CredentialItem.credential_id == target_credential.id,
        )) == 0


def test_promotion_excludes_project_scoped_runtime_material(database_factory) -> None:
    """dev/test 项目配置必须由管理员在 prod/prod 重新填写，不能自动提升。"""

    source_cipher = SecretCipher({"v1": b"a" * 32}, "v1")
    target_cipher = SecretCipher({"v1": b"a" * 32, "prod-v1": b"b" * 32}, "prod-v1")
    with database_factory() as database:
        _seed(database, source_cipher)
        _seed_project_scoped_runtime_material(database, source_cipher)
        database.commit()

        summary = promote_environment(
            database,
            target_cipher,
            "dev",
            "prod",
            copy_secrets=True,
            seed_credentials=True,
            require_empty_target=True,
        )
        database.commit()

        # 普通 Tool 配置仍保持既有提升语义；Summary 只统计真正可提升的材料。
        assert summary.__dict__ == {
            "activations": 1,
            "secrets": 1,
            "credentials": 1,
            "clients": 1,
        }
        assert database.scalar(select(func.count()).select_from(ConfigActivation).where(
            ConfigActivation.environment_id == "prod",
            ConfigActivation.owner_type == "tool_project_scope",
        )) == 0
        assert database.scalar(select(func.count()).select_from(ConfigRelease).where(
            ConfigRelease.environment_id == "prod",
            ConfigRelease.owner_type == "tool_project_scope",
        )) == 0
        assert database.scalar(select(func.count()).select_from(Secret).where(
            Secret.environment_id == "prod",
            Secret.owner_type == "tool_project_scope",
        )) == 0
        assert database.scalar(select(func.count()).select_from(Credential).where(
            Credential.environment_id == "prod",
            Credential.provider_type == "scoped-login",
        )) == 0


def test_promotion_excludes_legacy_api_autotest_runtime_material(database_factory) -> None:
    """遗留 Tool 级 API AutoTest test 值也必须在生产提升中 fail-closed。"""

    source_cipher = SecretCipher({"v1": b"a" * 32}, "v1")
    target_cipher = SecretCipher({"v1": b"a" * 32, "prod-v1": b"b" * 32}, "prod-v1")
    with database_factory() as database:
        _seed(database, source_cipher)
        _seed_legacy_api_autotest_runtime_material(database, source_cipher)
        database.commit()

        summary = promote_environment(
            database,
            target_cipher,
            "dev",
            "prod",
            copy_secrets=True,
            seed_credentials=True,
            require_empty_target=True,
        )
        database.commit()

        assert summary.__dict__ == {
            "activations": 1,
            "secrets": 1,
            "credentials": 1,
            "clients": 1,
        }
        assert database.scalar(select(func.count()).select_from(ConfigActivation).where(
            ConfigActivation.environment_id == "prod",
            ConfigActivation.owner_type == "tool",
            ConfigActivation.owner_id == "api-autotest",
        )) == 0
        assert database.scalar(select(func.count()).select_from(ConfigRelease).where(
            ConfigRelease.environment_id == "prod",
            ConfigRelease.owner_type == "tool",
            ConfigRelease.owner_id == "api-autotest",
        )) == 0
        assert database.scalar(select(func.count()).select_from(Secret).where(
            Secret.environment_id == "prod",
            Secret.owner_type == "tool",
            Secret.owner_id == "api-autotest",
        )) == 0
        assert database.scalar(select(func.count()).select_from(Credential).where(
            Credential.environment_id == "prod",
            Credential.tool_id == "api-autotest",
        )) == 0


def test_non_empty_target_is_rejected_without_partial_writes(database_factory) -> None:
    cipher = SecretCipher({"v1": b"a" * 32}, "v1")
    with database_factory() as database:
        _seed(database, cipher)
        database.add(ToolClient(
            id="client_prod", tool_id="tool-a", environment_id="prod",
            token_hash="b" * 64, capabilities=[], status="active",
        ))
        database.commit()
        with pytest.raises(ValueError, match="不是空环境"):
            promote_environment(
                database, cipher, "dev", "prod", copy_secrets=True,
                seed_credentials=True, require_empty_target=True,
            )
        database.rollback()
        assert database.scalar(select(func.count()).select_from(ConfigRelease).where(
            ConfigRelease.environment_id == "prod",
        )) == 0


def test_failure_can_be_rolled_back_atomically(database_factory) -> None:
    cipher = SecretCipher({"v1": b"a" * 32}, "v1")
    with database_factory() as database:
        _seed(database, cipher)
        source_item = database.scalar(select(ConfigReleaseItem).where(
            ConfigReleaseItem.secret_version_id.is_not(None),
        ))
        source_item.secret_version_id = "missing-version"
        database.commit()
        with pytest.raises(ValueError, match="未复制"):
            promote_environment(
                database, cipher, "dev", "prod", copy_secrets=True,
                seed_credentials=True, require_empty_target=True,
            )
        database.rollback()
        assert database.scalar(select(func.count()).select_from(Secret).where(
            Secret.environment_id == "prod",
        )) == 0
