"""停止将 API AutoTest 的 DEVICE_ID 作为个人运行凭证。

Revision ID: 20260828_0023
Revises: 20260828_0022

``gateway.comm.device_id`` 已在 0022 成为项目 Release 的必填静态参数。旧的
个人 Credential Item 和 SecretVersion 继续保留作历史审计，但 Definition 会
标记为不参与运行快照，避免它再次覆盖 Runtime Scope Release。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260828_0023"
down_revision: str | None = "20260828_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFINITION_ID = "api-autotest.DEVICE_ID"
RETIRED_SCHEMA = {
    "runtime_config_excluded": True,
    "replacement_key": "gateway.comm.device_id",
}


def _definitions() -> sa.TableClause:
    """返回本迁移使用的最小 Definition 表映射。"""

    return sa.table(
        "config_definitions",
        sa.column("id", sa.String()),
        sa.column("required", sa.Boolean()),
        sa.column("validation_schema", sa.JSON()),
    )


def upgrade() -> None:
    """将旧 Device 字段从个人运行凭证契约中退休。"""

    definitions = _definitions()
    op.get_bind().execute(
        definitions.update()
        .where(definitions.c.id == DEFINITION_ID)
        .values(required=False, validation_schema=RETIRED_SCHEMA)
    )


def downgrade() -> None:
    """恢复 0022 之前的兼容凭证契约，不删除任何历史 Secret。"""

    definitions = _definitions()
    op.get_bind().execute(
        definitions.update()
        .where(definitions.c.id == DEFINITION_ID)
        .values(required=True, validation_schema={})
    )

