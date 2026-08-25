"""新增用户级 Credential、LLM Binding 和可信 Runtime Context 隔离层。

Revision ID: 20260823_0018
Revises: 20260821_0017

功能说明:
    本迁移只建立结构、配置字段分类和管理员就绪度权限。真实 Secret 仍由应用层
    使用现有 KEK 解密后重新加密；Alembic 不读取 KEK、不猜测 admin，也不复制
    legacy Credential，保证空库和已有 0017 数据库都能安全升级。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260823_0018"
down_revision: str | None = "20260821_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


READINESS_PERMISSION = "platform.credential.readiness.view"
MIGRATION_ACTOR = "system/migration-user-credential-scopes"

# 业务账号字段必须显式分类，运行时禁止通过 key 名称猜测用户作用域。
PERSONAL_CREDENTIAL_KEYS: dict[tuple[str, str], tuple[str, ...]] = {
    ("truthy-search", "gateway_session"): (
        "AUTH_TOKEN",
        "REFRESH_TOKEN",
        "EXPIRES_TIME",
        "REFRESH_EXPIRES_TIME",
        "DEVICE_ID",
        "USER_ID",
        "SEARCH_HTTP_HEADERS_JSON",
    ),
    ("truthy-search", "admin_login"): (
        "SEARCH_ADMIN_USERNAME",
        "SEARCH_ADMIN_PASSWORD",
        "SEARCH_ADMIN_HTTP_HEADERS_JSON",
    ),
    ("api-autotest", "gateway_session"): (
        "AUTH_TOKEN",
        "REFRESH_TOKEN",
        "EXPIRES_TIME",
        "REFRESH_EXPIRES_TIME",
        "USER_ID",
        "DEVICE_ID",
    ),
    ("api-autotest", "admin_login"): (
        "ADMIN_USERNAME",
        "ADMIN_PASSWORD",
        "ADMIN_SESSION_TOKEN",
        "ADMIN_OPERATOR_ID",
        "ADMIN_OPERATOR_NAME",
    ),
}


def _drop_legacy_llm_name_constraint() -> str | None:
    """返回旧全局 Profile 名称唯一约束名，兼容 SQLite 的匿名约束。"""

    constraints = sa.inspect(op.get_bind()).get_unique_constraints("llm_profiles")
    for constraint in constraints:
        if constraint.get("column_names") == ["name_normalized"]:
            return constraint.get("name") or "uq_llm_profiles_name_normalized"
    return None


def upgrade() -> None:
    """创建个人隔离结构并回填确定性的配置作用域元数据。"""

    naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    with op.batch_alter_table(
        "config_definitions", naming_convention=naming_convention
    ) as batch:
        batch.add_column(sa.Column(
            "value_scope", sa.String(16), nullable=False, server_default="system"
        ))
        batch.add_column(sa.Column(
            "credential_provider_type", sa.String(64), nullable=True
        ))
        batch.create_check_constraint(
            "ck_config_definitions_value_scope",
            "value_scope IN ('system', 'user')",
        )
        batch.create_check_constraint(
            "ck_config_definitions_credential_provider_scope",
            "credential_provider_type IS NULL OR "
            "(owner_type = 'tool' AND value_scope = 'user')",
        )

    connection = op.get_bind()
    definitions = sa.table(
        "config_definitions",
        sa.column("owner_type", sa.String()),
        sa.column("owner_id", sa.String()),
        sa.column("key", sa.String()),
        sa.column("value_scope", sa.String()),
        sa.column("credential_provider_type", sa.String()),
    )
    for (tool_id, provider_type), keys in PERSONAL_CREDENTIAL_KEYS.items():
        connection.execute(
            definitions.update().where(
                definitions.c.owner_type == "tool",
                definitions.c.owner_id == tool_id,
                definitions.c.key.in_(keys),
            ).values(
                value_scope="user",
                credential_provider_type=provider_type,
            )
        )
    # Agent 旧 Release 中的 LLM Key 和旧公共 LLM Profile/Binding 都属于用户配置；
    # 它们在新 Resolver 中只会经 admin 应用迁移后的个人所有权读取。
    connection.execute(
        definitions.update().where(
            definitions.c.owner_type == "tool",
            definitions.c.key == "LLM_API_KEY",
        ).values(value_scope="user")
    )
    connection.execute(
        definitions.update().where(
            definitions.c.owner_type.in_(("llm_profile", "llm_binding")),
        ).values(value_scope="user")
    )

    legacy_name_constraint = _drop_legacy_llm_name_constraint()
    with op.batch_alter_table(
        "llm_profiles", naming_convention=naming_convention
    ) as batch:
        batch.add_column(sa.Column("owner_user_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_llm_profiles_owner_user_id_users",
            "users", ["owner_user_id"], ["id"], ondelete="CASCADE",
        )
        if legacy_name_constraint is not None:
            batch.drop_constraint(legacy_name_constraint, type_="unique")
        batch.create_unique_constraint(
            "uq_llm_profiles_owner_name", ["owner_user_id", "name_normalized"]
        )

    op.create_table(
        "user_credentials",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "tool_id", sa.String(64),
            sa.ForeignKey("tools.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "environment_id", sa.String(32),
            sa.ForeignKey("environments.id"), nullable=False,
        ),
        sa.Column("provider_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="missing"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True)),
        sa.Column("refresh_lease_until", sa.DateTime(timezone=True)),
        sa.Column("refresh_owner", sa.String(64)),
        sa.Column("last_error_code", sa.String(128)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "tool_id", "environment_id", "provider_type",
            name="uq_user_credential_scope",
        ),
    )
    op.create_index(
        "ix_user_credentials_environment_status_expires", "user_credentials",
        ["environment_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_user_credentials_user_environment_tool", "user_credentials",
        ["user_id", "environment_id", "tool_id"],
    )
    op.create_index(
        "ix_user_credentials_refresh_lease_status", "user_credentials",
        ["refresh_lease_until", "status"],
    )

    op.create_table(
        "user_credential_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "credential_id", sa.String(64),
            sa.ForeignKey("user_credentials.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column(
            "secret_version_id", sa.String(64),
            sa.ForeignKey("secret_versions.id"), nullable=True,
        ),
        sa.Column("value_json", sa.JSON(none_as_null=True), nullable=True),
        sa.UniqueConstraint(
            "credential_id", "credential_version", "key",
            name="uq_user_credential_item",
        ),
        sa.CheckConstraint(
            "(secret_version_id IS NOT NULL AND value_json IS NULL) OR "
            "(secret_version_id IS NULL AND value_json IS NOT NULL)",
            name="ck_user_credential_items_value_source",
        ),
    )

    op.create_table(
        "user_llm_bindings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "binding_id", sa.String(64),
            sa.ForeignKey("tool_llm_bindings.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "binding_id", name="uq_user_llm_binding_scope"
        ),
    )

    op.create_table(
        "runtime_contexts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "session_id", sa.String(64),
            sa.ForeignKey("platform_sessions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "tool_id", sa.String(64),
            sa.ForeignKey("tools.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "environment_id", sa.String(32),
            sa.ForeignKey("environments.id"), nullable=False,
        ),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name="ck_runtime_contexts_status",
        ),
        sa.CheckConstraint(
            "resource_type IN ('task', 'run', 'request')",
            name="ck_runtime_contexts_resource_type",
        ),
    )
    op.create_index(
        "ix_runtime_contexts_tool_environment_status_expires", "runtime_contexts",
        ["tool_id", "environment_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_runtime_contexts_user_status_expires", "runtime_contexts",
        ["user_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_runtime_contexts_session_status", "runtime_contexts",
        ["session_id", "status"],
    )

    permissions = sa.table(
        "permissions",
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("resource_type", sa.String()),
    )
    op.bulk_insert(permissions, [{
        "code": READINESS_PERMISSION,
        "name": "查看用户凭证就绪度",
        "description": "只读查看用户凭证和个人 LLM 的脱敏就绪状态",
        "resource_type": "platform",
    }])
    grants = sa.table(
        "role_grants",
        sa.column("role_id", sa.String()),
        sa.column("permission_code", sa.String()),
        sa.column("resource_type", sa.String()),
        sa.column("resource_id", sa.String()),
        sa.column("created_by", sa.String()),
    )
    op.bulk_insert(grants, [{
        "role_id": "role_platform_admin",
        "permission_code": READINESS_PERMISSION,
        "resource_type": "platform",
        "resource_id": "*",
        "created_by": MIGRATION_ACTOR,
    }])


def downgrade() -> None:
    """只回退 0018 新增对象，完整保留 legacy Credential、Release 和 Secret。"""

    connection = op.get_bind()
    duplicate_profile_names = connection.execute(sa.text(
        "SELECT name_normalized FROM llm_profiles "
        "GROUP BY name_normalized HAVING COUNT(*) > 1 "
        "ORDER BY name_normalized LIMIT 5"
    )).scalars().all()
    if duplicate_profile_names:
        # 0018 将名称唯一范围从全局放宽到 owner。直接删除 owner_user_id 会让
        # 同名 Profile 在恢复旧全局唯一约束时发生部分降级，必须在任何删表前拒绝。
        names = ", ".join(str(name) for name in duplicate_profile_names)
        raise RuntimeError(
            "无法降级 20260823_0018：存在跨所有者同名 LLM Profile "
            f"({names})；请先重命名或合并同名 LLM Profile，再重新执行降级。"
        )
    connection.execute(sa.text(
        "DELETE FROM role_grants WHERE created_by=:actor "
        "AND permission_code=:permission"
    ), {"actor": MIGRATION_ACTOR, "permission": READINESS_PERMISSION})
    connection.execute(
        sa.text("DELETE FROM permissions WHERE code=:permission"),
        {"permission": READINESS_PERMISSION},
    )

    op.drop_index("ix_runtime_contexts_session_status", table_name="runtime_contexts")
    op.drop_index("ix_runtime_contexts_user_status_expires", table_name="runtime_contexts")
    op.drop_index(
        "ix_runtime_contexts_tool_environment_status_expires",
        table_name="runtime_contexts",
    )
    op.drop_table("runtime_contexts")
    op.drop_table("user_llm_bindings")
    op.drop_table("user_credential_items")
    op.drop_index(
        "ix_user_credentials_refresh_lease_status", table_name="user_credentials"
    )
    op.drop_index(
        "ix_user_credentials_user_environment_tool", table_name="user_credentials"
    )
    op.drop_index(
        "ix_user_credentials_environment_status_expires", table_name="user_credentials"
    )
    op.drop_table("user_credentials")

    naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    with op.batch_alter_table(
        "llm_profiles", naming_convention=naming_convention
    ) as batch:
        batch.drop_constraint("uq_llm_profiles_owner_name", type_="unique")
        batch.drop_constraint(
            "fk_llm_profiles_owner_user_id_users", type_="foreignkey"
        )
        batch.drop_column("owner_user_id")
        batch.create_unique_constraint(
            "uq_llm_profiles_name_normalized", ["name_normalized"]
        )

    with op.batch_alter_table(
        "config_definitions", naming_convention=naming_convention
    ) as batch:
        batch.drop_constraint(
            "ck_config_definitions_credential_provider_scope", type_="check"
        )
        batch.drop_constraint(
            "ck_config_definitions_value_scope", type_="check"
        )
        batch.drop_column("credential_provider_type")
        batch.drop_column("value_scope")
