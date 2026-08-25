"""扩展固定角色、项目范围、临时工具授权与业务资源快照结构。

Revision ID: 20260824_0019
Revises: 20260823_0018

本迁移属于 expand 阶段：旧 RBAC 表完整保留，新字段先允许兼容读取。存量工具
保守归入 LEGACY 项目而不是公开，避免升级过程静默扩大权限。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260824_0019"
down_revision: str | None = "20260823_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加新模型并完成可确定的保守回填，不删除任何旧授权数据。"""

    op.create_table(
        "projects",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_user_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_projects_status"),
        sa.UniqueConstraint("code", name="uq_projects_code"),
    )
    op.create_index("ix_projects_status_name", "projects", ["status", "name"])
    op.execute(
        sa.text(
            "INSERT INTO projects (id, code, name, description, status, created_by_user_id) "
            "VALUES ('project_legacy', 'LEGACY', '存量工具', '迁移期间保守承接未分类工具', 'active', 'system/migration')"
        )
    )

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("platform_role", sa.String(32), nullable=True))
    op.execute(
        "UPDATE users SET platform_role='platform_admin' WHERE id IN "
        "(SELECT user_id FROM user_roles WHERE role_id='role_platform_admin')"
    )
    op.execute(
        "UPDATE users SET platform_role='tester' WHERE platform_role IS NULL AND id IN "
        "(SELECT user_id FROM user_roles WHERE role_id IN ('role_test_developer','role_test_executor'))"
    )

    with op.batch_alter_table("tools") as batch:
        batch.add_column(sa.Column("access_scope", sa.String(16), nullable=True))
        batch.add_column(sa.Column("project_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("authorization_epoch", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("public_safety_policy_status", sa.String(16), nullable=False, server_default="missing"))
        batch.add_column(sa.Column("public_safety_policy", sa.JSON(), nullable=False, server_default="{}"))
        batch.create_foreign_key("fk_tools_project_id_projects", "projects", ["project_id"], ["id"], ondelete="RESTRICT")
    op.execute("UPDATE tools SET access_scope='project', project_id='project_legacy' WHERE access_scope IS NULL")

    op.create_table(
        "project_memberships",
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("relation", sa.String(16), nullable=False),
        sa.Column("created_by_user_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("relation IN ('manager', 'member')", name="ck_project_memberships_relation"),
    )
    op.create_index("ix_project_memberships_user_relation", "project_memberships", ["user_id", "relation"])
    # Expand 阶段不自动把任何用户加入 LEGACY。旧角色可能只拥有部分工具，若把
    # tester 全量加入同一项目会静默扩权；项目关系必须经 manifest/shadow 校验写入。

    op.create_table(
        "user_tool_grants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_id", sa.String(64), sa.ForeignKey("tools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("granted_by_user_id", sa.String(64), nullable=False),
        sa.Column("grant_reason", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_by_user_id", sa.String(64)),
        sa.Column("revoke_reason", sa.Text()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("renewed_from_grant_id", sa.String(64)),
        sa.Column("idempotency_key", sa.String(128), unique=True),
        sa.Column("idempotency_payload_hash", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'expired', 'revoked')", name="ck_user_tool_grants_status"),
    )
    op.create_index("ix_user_tool_grants_user_status_expires", "user_tool_grants", ["user_id", "status", "expires_at"])
    op.create_index("ix_user_tool_grants_tool_status_expires", "user_tool_grants", ["tool_id", "status", "expires_at"])
    op.create_index(
        "uq_user_tool_grants_active_user_tool",
        "user_tool_grants",
        ["user_id", "tool_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "business_resource_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("root_resource_id", sa.String(128), nullable=False),
        sa.Column("tool_id", sa.String(64), nullable=False),
        sa.Column("environment_id", sa.String(64), nullable=False),
        sa.Column("owner_user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id_snapshot", sa.String(64)),
        sa.Column("authorization_source_snapshot", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "environment_id", "tool_id", "resource_type", "resource_id",
            name="uq_business_resources_env_tool_type_id",
        ),
    )
    op.create_index("ix_business_resources_owner_env_tool_created", "business_resource_snapshots", ["owner_user_id", "environment_id", "tool_id", "created_at"])
    op.create_index("ix_business_resources_project_env_tool_created", "business_resource_snapshots", ["project_id_snapshot", "environment_id", "tool_id", "created_at"])

    op.create_table(
        "public_tool_usage",
        sa.Column("usage_date", sa.String(10), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tool_id", sa.String(64), sa.ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("request_window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("task_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "project_access_readiness",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("environment_id", sa.String(32), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("state_digest", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    with op.batch_alter_table("runtime_contexts") as batch:
        batch.add_column(sa.Column("project_id_snapshot", sa.String(64), nullable=True))
        batch.add_column(sa.Column("authorization_source_snapshot", sa.String(32), nullable=True))
        batch.add_column(sa.Column("allowed_config_refs", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("allowed_credential_refs", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("emergency_revoked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """仅移除本迁移新增结构；旧 RBAC 数据从未改写或删除。"""

    with op.batch_alter_table("runtime_contexts") as batch:
        for name in ("emergency_revoked_at", "allowed_credential_refs", "allowed_config_refs", "authorization_source_snapshot", "project_id_snapshot"):
            batch.drop_column(name)
    op.drop_table("project_access_readiness")
    op.drop_table("public_tool_usage")
    op.drop_index("ix_business_resources_project_env_tool_created", table_name="business_resource_snapshots")
    op.drop_index("ix_business_resources_owner_env_tool_created", table_name="business_resource_snapshots")
    op.drop_table("business_resource_snapshots")
    op.drop_index("uq_user_tool_grants_active_user_tool", table_name="user_tool_grants")
    op.drop_index("ix_user_tool_grants_tool_status_expires", table_name="user_tool_grants")
    op.drop_index("ix_user_tool_grants_user_status_expires", table_name="user_tool_grants")
    op.drop_table("user_tool_grants")
    op.drop_index("ix_project_memberships_user_relation", table_name="project_memberships")
    op.drop_table("project_memberships")
    with op.batch_alter_table("tools") as batch:
        batch.drop_constraint("fk_tools_project_id_projects", type_="foreignkey")
        for name in ("public_safety_policy", "public_safety_policy_status", "authorization_epoch", "revision", "project_id", "access_scope"):
            batch.drop_column(name)
    with op.batch_alter_table("users") as batch:
        batch.drop_column("platform_role")
    op.drop_index("ix_projects_status_name", table_name="projects")
    op.drop_table("projects")
