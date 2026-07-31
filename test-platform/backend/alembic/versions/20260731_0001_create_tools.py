"""创建工具目录并写入首批工具。

Revision ID: 20260731_0001
Revises:
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260731_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 tools 表并确定性写入两个基础工具。"""

    tools_table = op.create_table(
        "tools",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("entry_url", sa.String(length=512), nullable=False),
        sa.Column("health_url", sa.String(length=1024), nullable=False),
        sa.Column("short_code", sa.String(length=32), nullable=False),
        sa.Column("icon_key", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        tools_table,
        [
            {
                "id": "trackevents",
                "name": "埋点测试",
                "description": "解析 TrackEvents 日志并校验事件字段",
                "entry_url": "/trackevents/",
                "health_url": "http://trackevents-web:8000/trackevents/health",
                "short_code": "EVENT",
                "icon_key": "event",
                "category": "analysis",
                "features": ["事件统计", "字段校验", "结果报告"],
                "sort_order": 10,
                "is_enabled": True,
            },
            {
                "id": "log-filter",
                "name": "日志筛选工具",
                "description": "上传、筛选并导出测试日志",
                "entry_url": "/log-filter/",
                "health_url": "http://log-filter-tool:5001/log-filter/health",
                "short_code": "LOG",
                "icon_key": "log",
                "category": "analysis",
                "features": ["日志上传", "条件筛选", "结果导出"],
                "sort_order": 20,
                "is_enabled": True,
            },
        ],
    )


def downgrade() -> None:
    """删除首轮工具目录表，供明确回滚数据库结构时使用。"""

    op.drop_table("tools")
