"""一次性把来源环境的当前有效配置复制到空目标环境。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import SecretCipher, new_id
from app.db.session import SessionLocal
from app.models.configuration import (
    ConfigActivation,
    ConfigRelease,
    ConfigReleaseItem,
    Credential,
    Environment,
    Secret,
    SecretVersion,
)
from app.models.identity import ToolClient
from app.services.secret_store import decrypt_secret_version, load_secret_cipher, replace_secret


@dataclass(frozen=True)
class PromotionSummary:
    """记录脱敏的复制数量，命令行不会输出任何配置值。"""

    activations: int
    secrets: int
    credentials: int
    clients: int


def _promotable_owner(
    owner_type: ColumnElement[str],
    owner_id: ColumnElement[str],
) -> ColumnElement[bool]:
    """返回允许跨环境提升的配置所有权条件。

    两类 API AutoTest 数据必须留在来源环境：

    - 任意 ``tool_project_scope`` 数据已经绑定项目和固定目标环境；
    - 迁移前遗留的 ``tool/api-autotest`` 数据可能仍保存 test Gateway/Admin 值。

    其他工具原有的 Tool/LLM 配置继续沿用首次生产提升语义。
    """

    return ~or_(
        owner_type == "tool_project_scope",
        and_(owner_type == "tool", owner_id == "api-autotest"),
    )


def _target_count(database: Session, target: str) -> int:
    """统计会使“一次性复制”不再安全的目标环境数据。"""

    models = (ConfigActivation, ConfigRelease, Secret, Credential, ToolClient)
    return sum(
        int(database.scalar(select(func.count()).select_from(model).where(model.environment_id == target)) or 0)
        for model in models
    )


def promotion_summary(database: Session, source: str) -> PromotionSummary:
    """返回来源环境中允许复制或重新生成的对象数量。

    ``tool_project_scope`` 的 Release/Secret、带 ``runtime_scope_id`` 的 Credential
    以及遗留 API AutoTest Tool 配置都可能保存 test 运行材料。它们不能沿用通用
    环境提升逻辑，否则 dev/test 值会进入 prod，或继续引用错误的 Scope ID。
    """

    return PromotionSummary(
        activations=int(database.scalar(select(func.count()).select_from(ConfigActivation).where(
            ConfigActivation.environment_id == source,
            _promotable_owner(ConfigActivation.owner_type, ConfigActivation.owner_id),
        )) or 0),
        secrets=int(database.scalar(select(func.count()).select_from(Secret).where(
            Secret.environment_id == source,
            _promotable_owner(Secret.owner_type, Secret.owner_id),
            Secret.current_version_id.is_not(None),
        )) or 0),
        credentials=int(database.scalar(select(func.count()).select_from(Credential).where(
            Credential.environment_id == source,
            Credential.runtime_scope_id.is_(None),
            Credential.tool_id != "api-autotest",
        )) or 0),
        clients=int(database.scalar(select(func.count()).select_from(ToolClient).where(
            ToolClient.environment_id == source, ToolClient.status == "active",
        )) or 0),
    )


def promote_environment(
    database: Session,
    cipher: SecretCipher,
    source: str,
    target: str,
    *,
    copy_secrets: bool,
    seed_credentials: bool,
    require_empty_target: bool,
) -> PromotionSummary:
    """原子创建目标非项目级 Secret、激活 Release 和待验证 Credential。

    项目级运行材料必须由目标环境管理员在对应 Runtime Scope 内独立创建；本函数
    只处理没有项目/目标环境归属的 legacy 或 Tool 级配置。这样既保留其他工具的
    首次生产初始化能力，也不会把 API AutoTest 的 test Gateway 或凭证带入 prod。
    """

    if source == target:
        raise ValueError("来源环境和目标环境不能相同")
    if database.get(Environment, source) is None or database.get(Environment, target) is None:
        raise ValueError("来源环境或目标环境不存在")
    if require_empty_target and _target_count(database, target):
        raise ValueError("目标环境不是空环境，拒绝覆盖")

    summary = promotion_summary(database, source)
    activations = list(database.scalars(select(ConfigActivation).where(
        ConfigActivation.environment_id == source,
        _promotable_owner(ConfigActivation.owner_type, ConfigActivation.owner_id),
    ).order_by(ConfigActivation.owner_type, ConfigActivation.owner_id)).all())

    version_map: dict[str, str] = {}
    if copy_secrets:
        source_secrets = list(database.scalars(select(Secret).where(
            Secret.environment_id == source,
            _promotable_owner(Secret.owner_type, Secret.owner_id),
            Secret.current_version_id.is_not(None),
        ).order_by(Secret.id)).all())
        referenced_versions = {
            item.secret_version_id
            for activation in activations
            for item in database.scalars(select(ConfigReleaseItem).where(
                ConfigReleaseItem.release_id == activation.active_release_id,
                ConfigReleaseItem.secret_version_id.is_not(None),
            )).all()
        }
        for source_secret in source_secrets:
            target_secret = Secret(
                id=new_id("sec"), environment_id=target,
                owner_type=source_secret.owner_type, owner_id=source_secret.owner_id,
                definition_id=source_secret.definition_id, status="missing",
            )
            database.add(target_secret)
            database.flush()
            versions = list(database.scalars(select(SecretVersion).where(
                SecretVersion.secret_id == source_secret.id,
                SecretVersion.id.in_(referenced_versions | {source_secret.current_version_id}),
            ).order_by(SecretVersion.version)).all())
            for source_version in versions:
                plaintext = decrypt_secret_version(database, cipher, source_secret, source_version.id)
                target_version = replace_secret(
                    database, cipher, target_secret, plaintext,
                    "system/environment-promotion", source_version.expires_at,
                )
                database.flush()
                version_map[source_version.id] = target_version.id

    now = datetime.now(UTC)
    for activation in activations:
        source_release = database.get(ConfigRelease, activation.active_release_id)
        if source_release is None:
            raise ValueError(f"激活配置不存在: {activation.active_release_id}")
        target_release = ConfigRelease(
            id=new_id("rel"), environment_id=target,
            owner_type=source_release.owner_type, owner_id=source_release.owner_id,
            version=1, revision=1, status="active",
            based_on_release_id=source_release.id,
            created_by="system/environment-promotion",
            published_by="system/environment-promotion", published_at=now,
        )
        database.add(target_release)
        database.flush()
        for item in database.scalars(select(ConfigReleaseItem).where(
            ConfigReleaseItem.release_id == source_release.id,
        )).all():
            if item.secret_version_id and not copy_secrets:
                continue
            target_secret_version = version_map.get(item.secret_version_id) if item.secret_version_id else None
            if item.secret_version_id and target_secret_version is None:
                raise ValueError(f"Secret Version 未复制: {item.secret_version_id}")
            database.add(ConfigReleaseItem(
                release_id=target_release.id, definition_id=item.definition_id,
                value_json=item.value_json, secret_version_id=target_secret_version,
            ))
        database.add(ConfigActivation(
            environment_id=target, owner_type=activation.owner_type,
            owner_id=activation.owner_id, active_release_id=target_release.id,
        ))

    if seed_credentials:
        for source_credential in database.scalars(select(Credential).where(
            Credential.environment_id == source,
            Credential.runtime_scope_id.is_(None),
            Credential.tool_id != "api-autotest",
        ).order_by(Credential.tool_id, Credential.provider_type)).all():
            database.add(Credential(
                id=new_id("cred"), tool_id=source_credential.tool_id,
                environment_id=target, provider_type=source_credential.provider_type,
                status="pending_validation",
            ))
    database.flush()
    return summary


def main() -> None:
    """解析安全的一次性复制参数，并在同一数据库事务中执行。"""

    parser = argparse.ArgumentParser(description="把当前有效配置复制到空目标环境")
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--require-empty-target", action="store_true", required=True)
    parser.add_argument("--copy-secrets", action="store_true")
    parser.add_argument("--seed-credentials", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as database:
        if database.get(Environment, args.source) is None or database.get(Environment, args.target) is None:
            raise SystemExit("来源环境或目标环境不存在")
        if _target_count(database, args.target):
            raise SystemExit("目标环境不是空环境，拒绝覆盖")
        summary = promotion_summary(database, args.source)
        if args.dry_run:
            print(f"dry-run: {asdict(summary)}；未写入数据库，未输出任何 Secret")
            return
        cipher = load_secret_cipher(get_settings())
        try:
            promote_environment(
                database, cipher, args.source, args.target,
                copy_secrets=args.copy_secrets,
                seed_credentials=args.seed_credentials,
                require_empty_target=True,
            )
            database.commit()
        except Exception:
            database.rollback()
            raise
        print(f"apply: {asdict(summary)}；未输出任何 Secret")


if __name__ == "__main__":
    main()
