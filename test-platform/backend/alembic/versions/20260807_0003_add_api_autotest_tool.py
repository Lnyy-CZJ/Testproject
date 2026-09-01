"""把 api-autotest 作为第四个独立工具写入平台目录。

Revision ID: 20260807_0003
Revises: 20260731_0002
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260807_0003"
down_revision: str | None = "20260731_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """确定性插入接口自动化工具元数据，不修改现有表结构。"""

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
                "id": "api-autotest",
                "name": "接口自动化",
                "description": "触发 Gateway 接口自动化执行，查看回归结果与 Allure 报告",
                "entry_url": "/api-autotest/",
                "health_url": "http://api-autotest:5003/api-autotest/health",
                "short_code": "API",
                "icon_key": "api",
                "category": "automation",
                "features": ["执行触发", "结果统计", "报告查看"],
                "sort_order": 40,
                "is_enabled": True,
            }
        ],
    )


def downgrade() -> None:
    """只删除接口自动化目录记录，保留另外三个工具。"""

    op.execute(
        sa.text("DELETE FROM tools WHERE id = :tool_id").bindparams(
            tool_id="api-autotest"
        )
    )
