"""登记 Dating Evaluation 专属运行配置。

Revision ID: 20260831_0025
Revises: 20260831_0024

这些 Definition 仍归属于 ``api-autotest`` Tool，但通过 ``project_ids`` 只向
Dating Runtime Scope 暴露。它们保持可选是有意的：普通 Dating 图片 Flow 不应
被 Evaluation 专属连接阻断，真正选择 Evaluation 资产时由工具预检精确校验。
迁移只登记字段，不写入 endpoint 或 API Key，也不会复制 test 值到 prod。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260831_0025"
down_revision: str | None = "20260831_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFINITIONS = (
    {
        "id": "api-autotest.runtime.dating-evaluation.base-url",
        "key": "gateway.targets.dating_evaluation.base_url",
        "display_name": "Dating Evaluation Base URL",
        "description": "Dating 内部自动化评测接口的 HTTP(S) Base URL",
        "group_key": "connection",
        "value_type": "url",
        "sensitivity": "normal",
        "validation_schema": {
            "project_ids": ["dating"],
            "min_length": 1,
            "max_length": 2048,
        },
        "sort_order": 60,
    },
    {
        "id": "api-autotest.runtime.dating-evaluation.path",
        "key": "gateway.targets.dating_evaluation.path",
        "display_name": "Dating Evaluation 请求路径",
        "description": "Dating 内部自动化评测接口的请求路径，例如 /admin/invoke",
        "group_key": "connection",
        "value_type": "logical_path",
        "sensitivity": "normal",
        "validation_schema": {
            "project_ids": ["dating"],
            "min_length": 1,
            "max_length": 256,
        },
        "sort_order": 70,
    },
    {
        "id": "api-autotest.runtime.dating-evaluation.api-key",
        "key": "DATING_EVALUATION_API_KEY",
        "display_name": "Dating Evaluation API Key",
        "description": "Dating 内部自动化评测接口使用的 Bearer API Key",
        "group_key": "credentials",
        "value_type": "secret",
        "sensitivity": "secret",
        "validation_schema": {"project_ids": ["dating"]},
        "sort_order": 80,
    },
)


def _definition_table() -> sa.TableClause:
    """返回插入 Definition 所需的稳定轻量表映射。"""

    return sa.table(
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


def upgrade() -> None:
    """新增三个 Dating 专属 Definition，不创建任何实际配置值。"""

    definitions = _definition_table()
    op.bulk_insert(definitions, [
        {
            **item,
            "owner_type": "tool",
            "owner_id": "api-autotest",
            # Evaluation 不是所有 Dating 资产的公共依赖，必填性由资产预检决定。
            "required": False,
            "default_value": None,
            "apply_mode": "next_task",
            "editable": True,
            "value_scope": "system",
            "credential_provider_type": None,
        }
        for item in DEFINITIONS
    ])


def downgrade() -> None:
    """删除本迁移定义；已被 Release 引用时拒绝破坏历史配置。"""

    connection = op.get_bind()
    definition_ids = [item["id"] for item in DEFINITIONS]
    release_items = sa.table(
        "config_release_items",
        sa.column("definition_id", sa.String()),
    )
    reference_count = connection.execute(
        sa.select(sa.func.count()).select_from(release_items).where(
            release_items.c.definition_id.in_(definition_ids)
        )
    ).scalar_one()
    if int(reference_count) > 0:
        raise RuntimeError(
            "Dating Evaluation 配置已被 Release 引用；请先完成显式数据处置再降级"
        )

    definitions = _definition_table()
    connection.execute(definitions.delete().where(definitions.c.id.in_(definition_ids)))
