"""登记功能测试智能体统一脑图工作台开关。

Revision ID: 20260816_0014
Revises: 20260815_0013

功能说明:
    仅增加普通布尔配置定义。迁移不自动创建或激活 dev/prod Release，
    避免数据库升级直接改变用户界面；dev 在验收后由发布流程显式开启。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260816_0014"
down_revision: str | None = "20260815_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFINITION_ID = "functional-test-agent.FUNCTIONAL_WORKBENCH_V2_ENABLED"


def upgrade() -> None:
    """新增默认关闭的功能工作台 V2 配置定义。"""

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
        "key": "FUNCTIONAL_WORKBENCH_V2_ENABLED",
        "display_name": "启用功能测试统一脑图工作台",
        "description": "启用任务列表 V2、统一任务工作台及脑图 Review 入口",
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
        "sort_order": 620,
    }])


def downgrade() -> None:
    """删除本期开关及其 Release 引用，不触碰 Release 和任务数据。"""

    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM config_release_items WHERE definition_id=:definition_id"),
        {"definition_id": DEFINITION_ID},
    )
    connection.execute(
        sa.text("DELETE FROM config_definitions WHERE id=:definition_id"),
        {"definition_id": DEFINITION_ID},
    )
