"""把当前环境的 legacy 业务凭证与 LLM 配置安全归属给唯一有效 admin。

命令默认只做 dry-run。只有显式传入 ``--apply`` 才会提交事务；任何冲突、分类
异常或 Secret 解密失败都会回滚整个环境。输出仅包含对象、键名、版本和动作，
不会输出明文、密文、长度、前后缀、哈希或 Secret ID。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import normalize_username
from app.db.session import SessionLocal
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
from app.services.audit import add_audit_event
from app.services.secret_store import (
    decrypt_secret_version,
    load_secret_cipher,
    replace_secret,
)


MIGRATION_ACTOR = "system/personal-credential-migration"


class PersonalMigrationError(RuntimeError):
    """个人配置迁移的脱敏基础错误。"""


class PersonalMigrationPreconditionError(PersonalMigrationError):
    """表示环境或唯一 active admin 前置条件不满足。"""


class PersonalMigrationConflict(PersonalMigrationError):
    """表示目标已被用户更新或来源结构不再满足确定性迁移规则。"""


@dataclass
class MigrationReport:
    """记录不含任何 Secret 特征的迁移计数与安全动作。"""

    environment: str
    mode: str
    credentials: dict[str, int] = field(
        default_factory=lambda: {"new": 0, "skipped": 0}
    )
    profiles: dict[str, int] = field(
        default_factory=lambda: {"new": 0, "skipped": 0}
    )
    bindings: dict[str, int] = field(
        default_factory=lambda: {"new": 0, "skipped": 0}
    )
    conflicts: int = 0
    actions: list[dict[str, Any]] = field(default_factory=list)

    def to_safe_dict(self) -> dict[str, Any]:
        """返回可安全打印的报告；动作中从不包含 Secret 标识或值。"""

        return {
            "environment": self.environment,
            "mode": self.mode,
            "credentials": dict(self.credentials),
            "profiles": dict(self.profiles),
            "bindings": dict(self.bindings),
            "conflicts": self.conflicts,
            "actions": list(self.actions),
        }


def _stable_id(prefix: str, *parts: str) -> str:
    """生成不暴露业务值的确定性内部 ID，保证重复迁移可识别同一目标。"""

    payload = "|".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:32]}"


def _active_admin(
    database: Session, admin_username: str, environment_id: str, settings: Settings
) -> User:
    """校验运行环境并返回唯一有效 admin，任何歧义都失败关闭。"""

    if environment_id != settings.platform_runtime_env:
        raise PersonalMigrationPreconditionError("迁移环境与平台运行环境不一致")
    if database.get(Environment, environment_id) is None:
        raise PersonalMigrationPreconditionError("迁移环境不存在")
    normalized = normalize_username(admin_username)
    admins = list(database.scalars(select(User).where(
        User.username_normalized == normalized,
        User.status == "active",
    )).all())
    if len(admins) != 1:
        raise PersonalMigrationPreconditionError("必须存在且只能存在一个有效 admin")
    return admins[0]


def _legacy_credential_values(
    database: Session, cipher, credential: Credential
) -> list[tuple[CredentialItem | None, ConfigDefinition, str | Any, bool]]:
    """合并 legacy 当前刷新项与同 Provider Secret，形成完整个人版本。

    legacy CredentialItem 只记录一次刷新返回的字段，账号、密码、设备 ID 等
    未轮换字段仍以工具作用域 Secret 的当前版本保存。因此迁移不能把 Item 当作
    完整快照：精确命中的 Item 优先固定其历史版本，其余已登记字段从同一工具、
    环境和定义的当前 Secret 补齐。明文只存在于本函数调用栈内。
    """

    items = list(database.scalars(select(CredentialItem).where(
        CredentialItem.credential_id == credential.id,
        CredentialItem.credential_version == credential.current_version,
    ).order_by(CredentialItem.key)).all())
    definitions = list(database.scalars(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == "tool",
        ConfigDefinition.owner_id == credential.tool_id,
        ConfigDefinition.value_scope == "user",
        ConfigDefinition.credential_provider_type == credential.provider_type,
    ).order_by(ConfigDefinition.sort_order, ConfigDefinition.key)).all())
    if not definitions:
        raise PersonalMigrationConflict("legacy Credential Provider 没有用户级字段定义")
    items_by_key = {item.key: item for item in items}
    if len(items_by_key) != len(items):
        raise PersonalMigrationConflict("legacy Credential 当前版本字段重复")
    unknown_keys = set(items_by_key) - {definition.key for definition in definitions}
    # 旧 Agent 会把统一 Admin Login 响应中的操作者元数据用小写临时键写入
    # CredentialItem。它们不是用户输入，也不能作为新个人字段；只允许丢弃这两个
    # 已知历史键，其他未知键仍失败关闭。
    allowed_transient_keys = {"operator_id", "operator_name"}
    if unknown_keys and (
        credential.provider_type != "admin_login"
        or bool(unknown_keys - allowed_transient_keys)
    ):
        raise PersonalMigrationConflict("legacy Credential 字段分类未知")

    resolved: list[
        tuple[CredentialItem | None, ConfigDefinition, str | Any, bool]
    ] = []
    for definition in definitions:
        item = items_by_key.get(definition.key)
        if item is None:
            # 未在本轮刷新中出现的 Secret 必须严格限定在同环境、同工具和同定义，
            # 禁止按键名跨 Provider 或跨环境猜测来源。
            secret = database.scalar(select(Secret).where(
                Secret.environment_id == credential.environment_id,
                Secret.owner_type == "tool",
                Secret.owner_id == credential.tool_id,
                Secret.definition_id == definition.id,
            ))
            version = (
                database.get(SecretVersion, secret.current_version_id)
                if secret is not None and secret.current_version_id
                else None
            )
            if definition.sensitivity == "secret" and secret is not None and version:
                try:
                    value = decrypt_secret_version(database, cipher, secret, version.id)
                except (ValueError, KeyError):
                    raise PersonalMigrationConflict(
                        "legacy Credential Secret 无法解密"
                    ) from None
                resolved.append((None, definition, value, True))
                continue
            if definition.required:
                raise PersonalMigrationConflict("legacy Credential 缺少必填字段")
            continue

        if item.secret_version_id:
            version = database.get(SecretVersion, item.secret_version_id)
            secret = database.get(Secret, version.secret_id) if version else None
            if secret is None or (
                secret.environment_id,
                secret.owner_type,
                secret.owner_id,
                secret.definition_id,
            ) != (
                credential.environment_id,
                "tool",
                credential.tool_id,
                definition.id,
            ):
                raise PersonalMigrationConflict("legacy Credential Secret 作用域损坏")
            try:
                value = decrypt_secret_version(database, cipher, secret, version.id)
            except (ValueError, KeyError):
                raise PersonalMigrationConflict("legacy Credential Secret 无法解密") from None
            resolved.append((item, definition, value, True))
        elif item.value_json is not None:
            resolved.append((item, definition, item.value_json, False))
        else:
            raise PersonalMigrationConflict("legacy Credential 字段没有有效值来源")
    if not resolved:
        raise PersonalMigrationConflict("legacy Credential 没有可迁移字段")
    return resolved


def _credential_matches(
    database: Session,
    cipher,
    source: Credential,
    target: UserCredential,
    values: list[tuple[CredentialItem | None, ConfigDefinition, Any, bool]],
    deterministic_id: str,
) -> bool:
    """在内存中比较来源与迁移目标，差异意味着用户已更新，禁止覆盖。"""

    if target.id != deterministic_id or target.current_version != source.current_version:
        return False
    target_items = list(database.scalars(select(UserCredentialItem).where(
        UserCredentialItem.credential_id == target.id,
        UserCredentialItem.credential_version == target.current_version,
    )).all())
    by_key = {item.key: item for item in target_items}
    if len(by_key) != len(values):
        return False
    for _source_item, definition, source_value, is_secret in values:
        target_item = by_key.get(definition.key)
        if target_item is None:
            return False
        if is_secret:
            version = database.get(SecretVersion, target_item.secret_version_id)
            secret = database.get(Secret, version.secret_id) if version else None
            if secret is None or (
                secret.environment_id, secret.owner_type, secret.owner_id,
                secret.definition_id,
            ) != (
                source.environment_id, "user_credential", target.id, definition.id,
            ):
                return False
            try:
                if decrypt_secret_version(database, cipher, secret, version.id) != source_value:
                    return False
            except (ValueError, KeyError):
                return False
        elif target_item.secret_version_id is not None or target_item.value_json != source_value:
            return False
    return True


def _migrate_credentials(
    database: Session,
    cipher,
    admin: User,
    environment_id: str,
    apply: bool,
    report: MigrationReport,
) -> None:
    """规划或导入当前环境所有 legacy Credential，不读取其他环境。"""

    sources = list(database.scalars(select(Credential).where(
        Credential.environment_id == environment_id,
        Credential.current_version > 0,
    ).order_by(Credential.tool_id, Credential.provider_type)).all())
    for source in sources:
        values = _legacy_credential_values(database, cipher, source)
        target_id = _stable_id(
            "ucred", admin.id, environment_id, source.tool_id, source.provider_type
        )
        target = database.scalar(select(UserCredential).where(
            UserCredential.user_id == admin.id,
            UserCredential.tool_id == source.tool_id,
            UserCredential.environment_id == environment_id,
            UserCredential.provider_type == source.provider_type,
        ))
        if target is not None:
            if not _credential_matches(
                database, cipher, source, target, values, target_id
            ):
                report.conflicts += 1
                raise PersonalMigrationConflict("个人 Credential 已被更新，拒绝覆盖")
            report.credentials["skipped"] += 1
            report.actions.append({
                "resource": "credential", "source": source.id,
                "target": target.id, "version": source.current_version,
                "action": "skipped",
            })
            continue

        report.credentials["new"] += 1
        report.actions.append({
            "resource": "credential", "source": source.id,
            "target": target_id, "version": source.current_version,
            "action": "create",
            "keys": [definition.key for _item, definition, _value, _secret in values],
        })
        if not apply:
            continue
        target = UserCredential(
            id=target_id,
            user_id=admin.id,
            tool_id=source.tool_id,
            environment_id=environment_id,
            provider_type=source.provider_type,
            status=source.status,
            current_version=source.current_version,
            expires_at=source.expires_at,
            refresh_expires_at=source.refresh_expires_at,
            last_error_code=source.last_error_code,
            last_checked_at=source.last_checked_at,
        )
        database.add(target)
        database.flush()
        for _source_item, definition, value, is_secret in values:
            if is_secret:
                secret_id = _stable_id(
                    "sec", "user_credential", target.id, definition.id, environment_id
                )
                if database.get(Secret, secret_id) is not None:
                    raise PersonalMigrationConflict("个人 Secret 目标已存在但 Credential 缺失")
                secret = Secret(
                    id=secret_id,
                    environment_id=environment_id,
                    owner_type="user_credential",
                    owner_id=target.id,
                    definition_id=definition.id,
                    status="missing",
                )
                database.add(secret)
                database.flush()
                version = replace_secret(
                    database, cipher, secret, str(value), MIGRATION_ACTOR
                )
                database.flush()
                database.add(UserCredentialItem(
                    credential_id=target.id,
                    credential_version=target.current_version,
                    key=definition.key,
                    secret_version_id=version.id,
                ))
            else:
                database.add(UserCredentialItem(
                    credential_id=target.id,
                    credential_version=target.current_version,
                    key=definition.key,
                    value_json=value,
                ))
        add_audit_event(
            database,
            action="personal_credential.migrate",
            resource_type="user_credential",
            resource_id=target.id,
            tool_id=target.tool_id,
            environment_id=environment_id,
            outcome="success",
            actor=admin,
            metadata={
                "provider_type": target.provider_type,
                "version": target.current_version,
                "keys": [definition.key for _item, definition, _value, _secret in values],
            },
        )


def _migrate_profiles(
    database: Session, admin: User, apply: bool, report: MigrationReport
) -> None:
    """把 legacy 空所有者 Profile 归 admin；已归 admin 时按幂等跳过。"""

    profiles = list(database.scalars(select(LlmProfile).where(
        (LlmProfile.owner_user_id.is_(None)) | (LlmProfile.owner_user_id == admin.id)
    ).order_by(LlmProfile.id)).all())
    for profile in profiles:
        if profile.owner_user_id == admin.id:
            report.profiles["skipped"] += 1
            action = "skipped"
        else:
            conflict = database.scalar(select(LlmProfile).where(
                LlmProfile.owner_user_id == admin.id,
                LlmProfile.name_normalized == profile.name_normalized,
                LlmProfile.id != profile.id,
            ))
            if conflict is not None:
                report.conflicts += 1
                raise PersonalMigrationConflict("admin 已存在同名个人 LLM Profile")
            report.profiles["new"] += 1
            action = "assign"
            if apply:
                profile.owner_user_id = admin.id
                add_audit_event(
                    database,
                    action="personal_llm_profile.migrate",
                    resource_type="llm_profile",
                    resource_id=profile.id,
                    outcome="success",
                    actor=admin,
                    metadata={"action": "assign_owner"},
                )
        report.actions.append({
            "resource": "llm_profile", "source": profile.id,
            "target": profile.id, "action": action,
        })


def _binding_source(
    database: Session, environment_id: str, binding: ToolLlmBinding
) -> tuple[ConfigRelease, ConfigActivation] | None:
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == environment_id,
        ConfigActivation.owner_type == "llm_binding",
        ConfigActivation.owner_id == binding.id,
    ))
    if activation is None:
        return None
    release = database.get(ConfigRelease, activation.active_release_id)
    if release is None or (
        release.environment_id, release.owner_type, release.owner_id
    ) != (environment_id, "llm_binding", binding.id):
        raise PersonalMigrationConflict("legacy LLM Binding Activation 损坏")
    return release, activation


def _binding_target_matches(
    database: Session,
    target: UserLlmBinding,
    target_id: str,
    target_release_id: str,
    source_release: ConfigRelease,
) -> bool:
    if target.id != target_id:
        return False
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == source_release.environment_id,
        ConfigActivation.owner_type == "user_llm_binding",
        ConfigActivation.owner_id == target.id,
    ))
    if activation is None or activation.active_release_id != target_release_id:
        return False
    target_release = database.get(ConfigRelease, target_release_id)
    if target_release is None or target_release.version != source_release.version:
        return False
    source_items = list(database.scalars(select(ConfigReleaseItem).where(
        ConfigReleaseItem.release_id == source_release.id
    )).all())
    target_items = list(database.scalars(select(ConfigReleaseItem).where(
        ConfigReleaseItem.release_id == target_release_id
    )).all())
    source_definitions = {
        row.id: row for row in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == "llm_binding",
            ConfigDefinition.owner_id == source_release.owner_id,
        )).all()
    }
    target_definitions = {
        row.key: row for row in database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == "user_llm_binding",
            ConfigDefinition.owner_id == target.id,
        )).all()
    }
    target_by_definition = {row.definition_id: row for row in target_items}
    if len(source_items) != len(target_items):
        return False
    for source_item in source_items:
        source_definition = source_definitions.get(source_item.definition_id)
        target_definition = (
            target_definitions.get(source_definition.key) if source_definition else None
        )
        target_item = (
            target_by_definition.get(target_definition.id) if target_definition else None
        )
        if target_item is None or target_item.value_json != source_item.value_json:
            return False
        # 当前首期 migration 测试和本机数据的 global Binding 没有独立 Key；
        # 若存在 Secret Override，创建路径支持重加密，但幂等比较必须交由后续
        # Secret 对照逻辑，不能把密文或 ID 当作相等依据。
        if bool(target_item.secret_version_id) != bool(source_item.secret_version_id):
            return False
    return True


def _clone_binding(
    database: Session,
    cipher,
    admin: User,
    binding: ToolLlmBinding,
    source_release: ConfigRelease,
    target: UserLlmBinding,
    target_release_id: str,
) -> None:
    """复制一个已激活 global Binding，并重加密可能存在的 Key Override。"""

    source_definitions = list(database.scalars(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == "llm_binding",
        ConfigDefinition.owner_id == binding.id,
    ).order_by(ConfigDefinition.sort_order, ConfigDefinition.key)).all())
    definition_map: dict[str, ConfigDefinition] = {}
    for source_definition in source_definitions:
        definition = ConfigDefinition(
            id=f"{target.id}.{source_definition.key}",
            key=source_definition.key,
            display_name=source_definition.display_name,
            description=source_definition.description,
            owner_type="user_llm_binding",
            owner_id=target.id,
            group_key=source_definition.group_key,
            value_type=source_definition.value_type,
            sensitivity=source_definition.sensitivity,
            required=source_definition.required,
            default_value=source_definition.default_value,
            validation_schema=source_definition.validation_schema,
            apply_mode=source_definition.apply_mode,
            editable=source_definition.editable,
            sort_order=source_definition.sort_order,
            value_scope="user",
        )
        database.add(definition)
        definition_map[source_definition.id] = definition
    database.flush()
    target_release = ConfigRelease(
        id=target_release_id,
        environment_id=source_release.environment_id,
        owner_type="user_llm_binding",
        owner_id=target.id,
        version=source_release.version,
        revision=source_release.revision,
        status="active",
        based_on_release_id=source_release.id,
        created_by=MIGRATION_ACTOR,
        published_by=MIGRATION_ACTOR,
        published_at=source_release.published_at,
    )
    database.add(target_release)
    database.flush()
    for source_item in database.scalars(select(ConfigReleaseItem).where(
        ConfigReleaseItem.release_id == source_release.id
    )).all():
        target_definition = definition_map.get(source_item.definition_id)
        if target_definition is None:
            raise PersonalMigrationConflict("legacy LLM Binding Item 定义缺失")
        if source_item.secret_version_id:
            version = database.get(SecretVersion, source_item.secret_version_id)
            secret = database.get(Secret, version.secret_id) if version else None
            if secret is None:
                raise PersonalMigrationConflict("legacy LLM Binding Secret 损坏")
            try:
                plaintext = decrypt_secret_version(database, cipher, secret, version.id)
            except (ValueError, KeyError):
                raise PersonalMigrationConflict("legacy LLM Binding Secret 无法解密") from None
            target_secret = Secret(
                id=_stable_id(
                    "sec", "user_llm_binding", target.id,
                    target_definition.id, source_release.environment_id,
                ),
                environment_id=source_release.environment_id,
                owner_type="user_llm_binding",
                owner_id=target.id,
                definition_id=target_definition.id,
                status="missing",
            )
            database.add(target_secret)
            database.flush()
            target_version = replace_secret(
                database, cipher, target_secret, plaintext, MIGRATION_ACTOR
            )
            database.flush()
            database.add(ConfigReleaseItem(
                release_id=target_release.id,
                definition_id=target_definition.id,
                secret_version_id=target_version.id,
            ))
        else:
            database.add(ConfigReleaseItem(
                release_id=target_release.id,
                definition_id=target_definition.id,
                value_json=source_item.value_json,
            ))
    database.add(ConfigActivation(
        environment_id=source_release.environment_id,
        owner_type="user_llm_binding",
        owner_id=target.id,
        active_release_id=target_release.id,
    ))
    add_audit_event(
        database,
        action="personal_llm_binding.migrate",
        resource_type="user_llm_binding",
        resource_id=target.id,
        tool_id=binding.tool_id,
        environment_id=source_release.environment_id,
        outcome="success",
        actor=admin,
        metadata={"binding_id": binding.id, "release_version": source_release.version},
    )


def _migrate_bindings(
    database: Session,
    cipher,
    admin: User,
    environment_id: str,
    apply: bool,
    report: MigrationReport,
) -> None:
    """为 admin 克隆当前环境所有已激活的 global LLM Binding。"""

    for binding in database.scalars(select(ToolLlmBinding).order_by(ToolLlmBinding.id)).all():
        source = _binding_source(database, environment_id, binding)
        if source is None:
            continue
        source_release, _source_activation = source
        target_id = _stable_id("ullmb", admin.id, binding.id)
        target_release_id = _stable_id(
            "rel", "user_llm_binding", target_id, environment_id, source_release.id
        )
        target = database.scalar(select(UserLlmBinding).where(
            UserLlmBinding.user_id == admin.id,
            UserLlmBinding.binding_id == binding.id,
        ))
        if target is not None:
            if not _binding_target_matches(
                database, target, target_id, target_release_id, source_release
            ):
                report.conflicts += 1
                raise PersonalMigrationConflict("个人 LLM Binding 已被更新，拒绝覆盖")
            report.bindings["skipped"] += 1
            action = "skipped"
        else:
            report.bindings["new"] += 1
            action = "create"
            if apply:
                target = UserLlmBinding(
                    id=target_id, user_id=admin.id, binding_id=binding.id
                )
                database.add(target)
                database.flush()
                _clone_binding(
                    database, cipher, admin, binding, source_release,
                    target, target_release_id,
                )
        report.actions.append({
            "resource": "llm_binding", "source": binding.id,
            "target": target_id, "version": source_release.version,
            "action": action,
        })


def migrate_personal_credentials(
    database: Session,
    settings: Settings,
    *,
    environment_id: str,
    admin_username: str = "admin",
    apply: bool = False,
) -> MigrationReport:
    """规划或执行单环境迁移，并在任意异常时回滚整个事务。

    参数说明:
        database: 当前数据库会话；调用方不得同时复用未提交业务事务。
        settings: 提供运行环境和 KEK 文件位置的平台配置。
        environment_id: 只能等于当前 ``platform_runtime_env``。
        admin_username: 要接收 legacy 配置的唯一 active 本地管理员。
        apply: ``False`` 时强制回滚并只返回报告；``True`` 时一次性提交。

    返回值:
        MigrationReport: 仅含对象计数和安全动作的报告。

    异常说明:
        PersonalMigrationPreconditionError: 环境或 admin 前置条件不满足。
        PersonalMigrationConflict: 来源损坏或个人目标已被更新。
    """

    report = MigrationReport(
        environment=environment_id,
        mode="apply" if apply else "dry-run",
    )
    try:
        admin = _active_admin(
            database, admin_username, environment_id, settings
        )
        cipher = load_secret_cipher(settings)
        _migrate_credentials(
            database, cipher, admin, environment_id, apply, report
        )
        _migrate_profiles(database, admin, apply, report)
        _migrate_bindings(
            database, cipher, admin, environment_id, apply, report
        )
        if apply:
            database.commit()
        else:
            database.rollback()
        return report
    except Exception:
        database.rollback()
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "把当前环境 legacy 业务凭证与 LLM 配置归属给唯一 active admin；"
            "默认 dry-run，绝不输出 Secret 值或指纹"
        )
    )
    parser.add_argument("--environment", required=True, choices=("dev", "prod"))
    parser.add_argument("--admin-username", default="admin")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只验证和预演（默认）")
    mode.add_argument("--apply", action="store_true", help="显式提交单环境迁移")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行命令行迁移；失败只输出稳定错误类型，不输出底层异常或敏感数据。"""

    args = _parser().parse_args(argv)
    settings = get_settings()
    try:
        with SessionLocal() as database:
            report = migrate_personal_credentials(
                database,
                settings,
                environment_id=args.environment,
                admin_username=args.admin_username,
                apply=bool(args.apply),
            )
        print(json.dumps(report.to_safe_dict(), ensure_ascii=False, sort_keys=True))
        return 0
    except PersonalMigrationError as error:
        print(
            json.dumps({
                "status": "failed",
                "error": type(error).__name__,
                "message": "迁移失败，数据库已回滚；未输出任何 Secret",
            }, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
