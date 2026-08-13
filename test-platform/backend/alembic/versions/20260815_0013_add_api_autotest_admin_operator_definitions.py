"""登记 api-autotest Admin operator 凭证定义。

Revision ID: 20260815_0013
Revises: 20260814_0012

功能说明:
    ADMIN_OPERATOR_ID / ADMIN_OPERATOR_NAME 供接口自动化 Admin 场景使用，
    由 Secret 管理手工维护，随 Release 快照注入任务子进程环境变量。
    两项均为可选（required=False），不阻塞既有 Release 发布校验。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260815_0013"
down_revision: str | None = "20260814_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFINITIONS = [
    ("api-autotest.ADMIN_OPERATOR_ID", "ADMIN_OPERATOR_ID", "Admin Operator ID"),
    ("api-autotest.ADMIN_OPERATOR_NAME", "ADMIN_OPERATOR_NAME", "Admin Operator 姓名"),
]


def upgrade() -> None:
    """新增 api-autotest 两个 Admin operator Secret 定义。"""

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
    op.bulk_insert(definitions, [
        {
            "id": definition_id, "key": key, "display_name": display, "description": display,
            "owner_type": "tool", "owner_id": "api-autotest", "group_key": "credentials",
            "value_type": "secret", "sensitivity": "secret", "required": False,
            "default_value": None, "validation_schema": {}, "apply_mode": "next_task",
            "editable": True, "sort_order": 230 + index * 10,
        }
        for index, (definition_id, key, display) in enumerate(DEFINITIONS)
    ])


def downgrade() -> None:
    """删除本迁移登记的两个定义。"""

    ids = [definition_id for definition_id, _key, _display in DEFINITIONS]
    op.execute(sa.text("DELETE FROM config_definitions WHERE id IN :ids").bindparams(
        sa.bindparam("ids", expanding=True, value=ids),
    ))
