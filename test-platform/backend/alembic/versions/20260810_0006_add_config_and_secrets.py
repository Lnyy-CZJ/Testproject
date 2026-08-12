"""新增配置版本、Secret 和 Credential 表。

Revision ID: 20260810_0006
Revises: 20260810_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0006"
down_revision: str | None = "20260810_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建环境、配置 Release、Secret 和 Credential 数据结构。"""

    op.create_table(
        "environments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "config_definitions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("owner_type", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("group_key", sa.String(64), nullable=False, server_default="general"),
        sa.Column("value_type", sa.String(32), nullable=False),
        sa.Column("sensitivity", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_value", sa.JSON()),
        sa.Column("validation_schema", sa.JSON(), nullable=False),
        sa.Column("apply_mode", sa.String(32), nullable=False, server_default="next_task"),
        sa.Column("editable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("owner_type", "owner_id", "key", name="uq_config_definition_owner_key"),
    )
    op.create_table(
        "config_releases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("environment_id", sa.String(32), sa.ForeignKey("environments.id"), nullable=False),
        sa.Column("owner_type", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("based_on_release_id", sa.String(64)),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("published_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("environment_id", "owner_type", "owner_id", "version", name="uq_config_release_version"),
    )
    op.create_table(
        "secrets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("environment_id", sa.String(32), sa.ForeignKey("environments.id"), nullable=False),
        sa.Column("owner_type", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("definition_id", sa.String(128), sa.ForeignKey("config_definitions.id"), nullable=False),
        sa.Column("current_version_id", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False, server_default="missing"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("environment_id", "owner_type", "owner_id", "definition_id", name="uq_secret_scope"),
    )
    op.create_table(
        "secret_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("secret_id", sa.String(64), sa.ForeignKey("secrets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("cipher_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("wrap_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("kek_version", sa.String(32), nullable=False),
        sa.Column("aad_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("secret_id", "version", name="uq_secret_version"),
    )
    op.create_table(
        "config_release_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("release_id", sa.String(64), sa.ForeignKey("config_releases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("definition_id", sa.String(128), sa.ForeignKey("config_definitions.id"), nullable=False),
        sa.Column("value_json", sa.JSON()),
        sa.Column("secret_version_id", sa.String(64), sa.ForeignKey("secret_versions.id")),
        sa.UniqueConstraint("release_id", "definition_id", name="uq_config_release_item"),
    )
    op.create_table(
        "config_activations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("environment_id", sa.String(32), sa.ForeignKey("environments.id"), nullable=False),
        sa.Column("owner_type", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("active_release_id", sa.String(64), sa.ForeignKey("config_releases.id"), nullable=False),
        sa.Column("confirmed_release_id", sa.String(64)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("environment_id", "owner_type", "owner_id", name="uq_config_activation_scope"),
    )
    op.create_table(
        "credentials",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tool_id", sa.String(64), sa.ForeignKey("tools.id"), nullable=False),
        sa.Column("environment_id", sa.String(32), sa.ForeignKey("environments.id"), nullable=False),
        sa.Column("provider_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="missing"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True)),
        sa.Column("refresh_lease_until", sa.DateTime(timezone=True)),
        sa.Column("refresh_owner", sa.String(64)),
        sa.Column("last_error_code", sa.String(128)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tool_id", "environment_id", "provider_type", name="uq_credential_scope"),
    )
    op.create_table(
        "credential_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("credential_id", sa.String(64), sa.ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("secret_version_id", sa.String(64), sa.ForeignKey("secret_versions.id")),
        sa.Column("value_json", sa.JSON()),
        sa.UniqueConstraint("credential_id", "credential_version", "key", name="uq_credential_item"),
    )


def downgrade() -> None:
    """按依赖反向顺序删除配置与 Secret 表。"""

    for table in (
        "credential_items", "credentials", "config_activations", "config_release_items",
        "secret_versions", "secrets", "config_releases", "config_definitions", "environments",
    ):
        op.drop_table(table)
