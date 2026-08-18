from __future__ import annotations

import pytest
from sqlalchemy import func, select

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
