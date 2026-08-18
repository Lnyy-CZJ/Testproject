"""登记功能测试智能体 Figma 工作台 V3 开关。

Revision ID: 20260818_0016
Revises: 20260817_0015

功能说明:
    只增加默认关闭的普通布尔配置。迁移不会自动发布或激活 Release，
    本机 dev 验收通过后再由配置发布流程显式开启。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0016"
down_revision: str | None = "20260817_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFINITION_ID = "functional-test-agent.FUNCTIONAL_WORKBENCH_V3_ENABLED"


def upgrade() -> None:
    """新增默认关闭的功能测试 Figma 工作台开关。"""

    definitions = sa.table(
        "config_definitions",
        sa.column("id", sa.String()), sa.column("key", sa.String()),
        sa.column("display_name", sa.String()), sa.column("description", sa.Text()),
        sa.column("owner_type", sa.String()), sa.column("owner_id", sa.String()),
        sa.column("group_key", sa.String()), sa.column("value_type", sa.String()),
        sa.column("sensitivity", sa.String()), sa.column("required", sa.Boolean()),
        sa.column("default_value", sa.JSON()), sa.column("validation_schema", sa.JSON()),
        sa.column("apply_mode", sa.String()), sa.column("editable", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(definitions, [{
        "id": DEFINITION_ID,
        "key": "FUNCTIONAL_WORKBENCH_V3_ENABLED",
        "display_name": "启用功能测试 Figma 工作台 V3",
        "description": "启用固定阶段侧栏、紧凑任务中心和聚焦式 Review 工作台",
        "owner_type": "tool",
        "owner_id": "functional-test-agent",
        "group_key": "ui",
        "value_type": "bool",
        "sensitivity": "normal",
        "required": True,
        "default_value": False,
        "validation_schema": {},
        "apply_mode": "next_task",
        "editable": True,
        "sort_order": 621,
    }])


def downgrade() -> None:
    """删除 V3 开关及其 Release 引用，保留 Release 和任务数据。"""

    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM config_release_items WHERE definition_id=:definition_id"),
        {"definition_id": DEFINITION_ID},
    )
    connection.execute(
        sa.text("DELETE FROM config_definitions WHERE id=:definition_id"),
        {"definition_id": DEFINITION_ID},
    )
