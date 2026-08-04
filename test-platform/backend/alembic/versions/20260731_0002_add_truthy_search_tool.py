"""把 Truthy_Search 作为第三个独立工具写入平台目录。

Revision ID: 20260731_0002
Revises: 20260731_0001
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260731_0002"
down_revision: str | None = "20260731_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """确定性插入 Truthy_Search 工具元数据，不修改现有表结构。"""

    tools_table = sa.table(
        "tools",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("entry_url", sa.String()),
        sa.column("health_url", sa.String()),
        sa.column("short_code", sa.String()),
        sa.column("icon_key", sa.String()),
        sa.column("category", sa.String()),
        sa.column("features", sa.JSON()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_enabled", sa.Boolean()),
    )
    op.bulk_insert(
        tools_table,
        [
            {
                "id": "truthy-search",
                "name": "检索评测",
                "description": "运行检索任务，对比基准结果并生成评测报告",
                "entry_url": "/truthy-search/",
                "health_url": "http://truthy-search:5002/truthy-search/health",
                "short_code": "SEARCH",
                "icon_key": "search",
                "category": "evaluation",
                "features": ["检索执行", "字段对比", "评测报告"],
                "sort_order": 30,
                "is_enabled": True,
            }
        ],
    )


def downgrade() -> None:
    """只删除 Truthy_Search 目录记录，保留另外两个基础工具。"""

    op.execute(
        sa.text("DELETE FROM tools WHERE id = :tool_id").bindparams(
            tool_id="truthy-search"
        )
    )
