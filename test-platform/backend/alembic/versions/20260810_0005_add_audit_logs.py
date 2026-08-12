"""新增只追加审计日志。

Revision ID: 20260810_0005
Revises: 20260810_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0005"
down_revision: str | None = "20260810_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建审计表和常用筛选索引。"""

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(64)),
        sa.Column("actor_snapshot", sa.JSON(), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("tool_id", sa.String(64)),
        sa.Column("environment_id", sa.String(32)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("ip_address", sa.String(128)),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("before_json", sa.JSON()),
        sa.Column("after_json", sa.JSON()),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
    )
    for column in ("occurred_at", "actor_id", "action", "tool_id", "environment_id", "outcome", "request_id"):
        op.create_index(f"ix_audit_logs_{column}", "audit_logs", [column])
    if op.get_bind().dialect.name == "postgresql":
        # 普通应用连接只能追加审计记录；数据库层拒绝篡改或删除。
        op.execute(
            """
            CREATE FUNCTION reject_audit_log_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_logs are append-only';
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER audit_logs_append_only
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();
            """
        )


def downgrade() -> None:
    """删除审计表；生产执行前必须先保留数据库备份。"""

    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS reject_audit_log_mutation()")
    op.drop_table("audit_logs")
