"""新增工具项目 Runtime Scope 与 Credential/Context 作用域引用。

Revision ID: 20260827_0021
Revises: 20260824_0020

迁移策略:
    只创建可确定平台项目归属的 Truthy/dev/test 占位 Scope，且保持 disabled。
    legacy Release、Activation、Secret 与 Credential 不做猜测性迁移；需要运维确认后
    再通过控制面迁移和激活，避免把未知历史凭证暴露给错误项目。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260827_0021"
down_revision: str | None = "20260824_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MIGRATION_ACTOR = "system/migration-tool-project-scopes"

# ConfigDefinition 仍保持 Tool 级；具体 Scope 的 Release 只引用这些定义。
# 分析轮询键只被 Dating Manifest 要求，因此 Definition 层标记为可选，最终必填性
# 由工具按项目 Manifest 校验，避免 Truthy Release 被 Dating 专属字段误阻断。
RUNTIME_DEFINITIONS = [
    {
        "id": "api-autotest.runtime.gateway.path",
        "key": "gateway.path",
        "display_name": "Gateway 请求路径",
        "description": "当前 Scope 使用的 Gateway HTTP 请求路径",
        "group_key": "connection",
        "value_type": "logical_path",
        "required": True,
        "validation_schema": {"min_length": 1, "max_length": 256},
        "sort_order": 20,
    },
    {
        "id": "api-autotest.runtime.gateway.comm",
        "key": "gateway.comm",
        "display_name": "Gateway Comm 默认值",
        "description": "当前 Scope 的非敏感 Gateway comm JSON；会话字段由 Credential 覆盖",
        "group_key": "connection",
        "value_type": "json",
        "required": True,
        "validation_schema": {},
        "sort_order": 30,
    },
    {
        "id": "api-autotest.runtime.flow.analysis.poll_interval_seconds",
        "key": "flow.analysis.poll_interval_seconds",
        "display_name": "Analysis 轮询间隔（秒）",
        "description": "Dating Analysis Flow 的轮询间隔",
        "group_key": "flow",
        "value_type": "float",
        "required": False,
        "validation_schema": {"minimum": 0.1, "maximum": 60},
        "sort_order": 40,
    },
    {
        "id": "api-autotest.runtime.flow.analysis.timeout_seconds",
        "key": "flow.analysis.timeout_seconds",
        "display_name": "Analysis 总超时（秒）",
        "description": "Dating Analysis Flow 的总轮询超时",
        "group_key": "flow",
        "value_type": "float",
        "required": False,
        "validation_schema": {"minimum": 1, "maximum": 1800},
        "sort_order": 50,
    },
]


def upgrade() -> None:
    """建立 Scope 数据边界，并保留所有未确认 legacy 数据的原有读取关系。"""

    connection = op.get_bind()
    # 复用旧 Definition ID，保证历史 Release Item 的外键与值不丢失；运行快照从
    # 本迁移起输出 Manifest 使用的逻辑键 ``gateway.base_url``。
    connection.execute(sa.text(
        "UPDATE config_definitions SET key='gateway.base_url', "
        "display_name='Gateway Base URL', "
        "description='当前 Runtime Scope 使用的 Gateway Base URL', "
        "group_key='connection', sort_order=10 "
        "WHERE id='api-autotest.GATEWAY_API_URL'"
    ))
    definitions = sa.table(
        "config_definitions",
        sa.column("id", sa.String()),
        sa.column("key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("owner_type", sa.String()),
        sa.column("owner_id", sa.String()),
        sa.column("group_key", sa.String()),
        sa.column("value_type", sa.String()),
        sa.column("sensitivity", sa.String()),
        sa.column("required", sa.Boolean()),
        sa.column("default_value", sa.JSON()),
        sa.column("validation_schema", sa.JSON()),
        sa.column("apply_mode", sa.String()),
        sa.column("editable", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
        sa.column("value_scope", sa.String()),
        sa.column("credential_provider_type", sa.String()),
    )
    op.bulk_insert(
        definitions,
        [
            {
                **item,
                "owner_type": "tool",
                "owner_id": "api-autotest",
                "sensitivity": "normal",
                "default_value": None,
                "apply_mode": "next_task",
                "editable": True,
                "value_scope": "system",
                "credential_provider_type": None,
            }
            for item in RUNTIME_DEFINITIONS
        ],
    )

    op.create_table(
        "tool_project_scopes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "environment_id", sa.String(32),
            sa.ForeignKey("environments.id"), nullable=False,
        ),
        sa.Column(
            "tool_id", sa.String(64),
            sa.ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "platform_project_id", sa.String(64),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("project_id", sa.String(32), nullable=False),
        sa.Column("target_env", sa.String(16), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "environment_id", "tool_id", "platform_project_id", "project_id",
            "target_env", name="uq_tool_project_scope_identity",
        ),
        sa.CheckConstraint(
            "(environment_id = 'dev' AND target_env = 'test') OR "
            "(environment_id = 'prod' AND target_env = 'prod')",
            name="ck_tool_project_scopes_environment_mapping",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_tool_project_scopes_status",
        ),
        sa.CheckConstraint(
            "length(project_id) BETWEEN 2 AND 32 AND "
            "project_id = lower(project_id) AND "
            "substr(project_id, 1, 1) BETWEEN 'a' AND 'z'",
            name="ck_tool_project_scopes_project_id",
        ),
        sa.CheckConstraint(
            "project_id GLOB '[a-z][a-z0-9-]*' AND "
            "project_id NOT GLOB '*[^a-z0-9-]*'",
            name="ck_tool_project_scopes_project_id_sqlite",
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "project_id ~ '^[a-z][a-z0-9-]{1,31}$'",
            name="ck_tool_project_scopes_project_id_postgresql",
        ).ddl_if(dialect="postgresql"),
    )
    op.create_index(
        "uq_tool_project_scopes_default_context",
        "tool_project_scopes",
        ["environment_id", "tool_id", "platform_project_id"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
        postgresql_where=sa.text("is_default = true"),
    )
    op.create_index(
        "ix_tool_project_scopes_lookup",
        "tool_project_scopes",
        ["tool_id", "environment_id", "platform_project_id", "status"],
    )

    naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    with op.batch_alter_table("credentials", naming_convention=naming_convention) as batch:
        batch.add_column(sa.Column("runtime_scope_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_credentials_runtime_scope_id_tool_project_scopes",
            "tool_project_scopes", ["runtime_scope_id"], ["id"], ondelete="RESTRICT",
        )
        batch.drop_constraint("uq_credential_scope", type_="unique")
    op.create_index(
        "uq_credentials_legacy_scope", "credentials",
        ["tool_id", "environment_id", "provider_type"], unique=True,
        sqlite_where=sa.text("runtime_scope_id IS NULL"),
        postgresql_where=sa.text("runtime_scope_id IS NULL"),
    )
    op.create_index(
        "uq_credentials_runtime_scope", "credentials",
        ["runtime_scope_id", "provider_type"], unique=True,
        sqlite_where=sa.text("runtime_scope_id IS NOT NULL"),
        postgresql_where=sa.text("runtime_scope_id IS NOT NULL"),
    )

    with op.batch_alter_table("user_credentials", naming_convention=naming_convention) as batch:
        batch.add_column(sa.Column("runtime_scope_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_user_credentials_runtime_scope_id_tool_project_scopes",
            "tool_project_scopes", ["runtime_scope_id"], ["id"], ondelete="RESTRICT",
        )
        batch.drop_constraint("uq_user_credential_scope", type_="unique")
    op.create_index(
        "uq_user_credentials_legacy_scope", "user_credentials",
        ["user_id", "tool_id", "environment_id", "provider_type"], unique=True,
        sqlite_where=sa.text("runtime_scope_id IS NULL"),
        postgresql_where=sa.text("runtime_scope_id IS NULL"),
    )
    op.create_index(
        "uq_user_credentials_runtime_scope", "user_credentials",
        ["user_id", "runtime_scope_id", "provider_type"], unique=True,
        sqlite_where=sa.text("runtime_scope_id IS NOT NULL"),
        postgresql_where=sa.text("runtime_scope_id IS NOT NULL"),
    )

    with op.batch_alter_table("runtime_contexts") as batch:
        batch.add_column(sa.Column("runtime_scope_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_runtime_contexts_runtime_scope_id_tool_project_scopes",
            "tool_project_scopes", ["runtime_scope_id"], ["id"], ondelete="RESTRICT",
        )

    platform_project_id = connection.execute(sa.text(
        "SELECT project_id FROM tools WHERE id='api-autotest'"
    )).scalar_one_or_none()
    dev_exists = connection.execute(sa.text(
        "SELECT COUNT(*) FROM environments WHERE id='dev'"
    )).scalar_one()
    # 这里只能确认 Tool 自身的 RBAC 项目，不能确认旧 Release/Secret 的业务项目。
    # 因此创建 disabled 占位 Scope 供运维核对，绝不创建 scoped Activation。
    if platform_project_id and dev_exists:
        connection.execute(sa.text(
            "INSERT INTO tool_project_scopes "
            "(id, environment_id, tool_id, platform_project_id, project_id, target_env, "
            "display_name, status, is_default, revision, created_by, updated_by) "
            "VALUES (:id, 'dev', 'api-autotest', :platform_project_id, 'truthy', 'test', "
            ":display_name, 'disabled', true, 1, :actor, :actor)"
        ), {
            "id": "tps_truthy_dev_test",
            "platform_project_id": platform_project_id,
            "display_name": "Truthy",
            "actor": MIGRATION_ACTOR,
        })


def downgrade() -> None:
    """仅在没有 scoped 运行材料时撤销结构，保留全部 legacy 回滚材料。"""

    connection = op.get_bind()
    scoped_counts = {
        "Release": connection.execute(sa.text(
            "SELECT COUNT(*) FROM config_releases WHERE owner_type='tool_project_scope'"
        )).scalar_one(),
        "Secret": connection.execute(sa.text(
            "SELECT COUNT(*) FROM secrets WHERE owner_type='tool_project_scope'"
        )).scalar_one(),
        "Credential": connection.execute(sa.text(
            "SELECT COUNT(*) FROM credentials WHERE runtime_scope_id IS NOT NULL"
        )).scalar_one(),
        "UserCredential": connection.execute(sa.text(
            "SELECT COUNT(*) FROM user_credentials WHERE runtime_scope_id IS NOT NULL"
        )).scalar_one(),
    }
    if any(scoped_counts.values()):
        raise RuntimeError(
            "存在 scoped Release/Secret/Credential；请先由运维显式归档或迁移后再降级"
        )

    connection.execute(sa.text(
        "DELETE FROM config_definitions WHERE id IN "
        "('api-autotest.runtime.gateway.path', "
        "'api-autotest.runtime.gateway.comm', "
        "'api-autotest.runtime.flow.analysis.poll_interval_seconds', "
        "'api-autotest.runtime.flow.analysis.timeout_seconds')"
    ))
    connection.execute(sa.text(
        "UPDATE config_definitions SET key='GATEWAY_API_URL', "
        "display_name='Gateway 会话接口', description='Gateway 会话接口', "
        "group_key='connection', sort_order=120 "
        "WHERE id='api-autotest.GATEWAY_API_URL'"
    ))

    with op.batch_alter_table("runtime_contexts") as batch:
        batch.drop_constraint(
            "fk_runtime_contexts_runtime_scope_id_tool_project_scopes", type_="foreignkey"
        )
        batch.drop_column("runtime_scope_id")

    op.drop_index("uq_user_credentials_runtime_scope", table_name="user_credentials")
    op.drop_index("uq_user_credentials_legacy_scope", table_name="user_credentials")
    with op.batch_alter_table("user_credentials") as batch:
        batch.drop_constraint(
            "fk_user_credentials_runtime_scope_id_tool_project_scopes", type_="foreignkey"
        )
        batch.drop_column("runtime_scope_id")
        batch.create_unique_constraint(
            "uq_user_credential_scope",
            ["user_id", "tool_id", "environment_id", "provider_type"],
        )

    op.drop_index("uq_credentials_runtime_scope", table_name="credentials")
    op.drop_index("uq_credentials_legacy_scope", table_name="credentials")
    with op.batch_alter_table("credentials") as batch:
        batch.drop_constraint(
            "fk_credentials_runtime_scope_id_tool_project_scopes", type_="foreignkey"
        )
        batch.drop_column("runtime_scope_id")
        batch.create_unique_constraint(
            "uq_credential_scope", ["tool_id", "environment_id", "provider_type"]
        )

    op.drop_index("ix_tool_project_scopes_lookup", table_name="tool_project_scopes")
    op.drop_index("uq_tool_project_scopes_default_context", table_name="tool_project_scopes")
    op.drop_table("tool_project_scopes")
