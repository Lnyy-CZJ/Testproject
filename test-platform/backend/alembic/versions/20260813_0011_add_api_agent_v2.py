"""登记 API 测试智能体 V2 Review 权限和安全默认配置。

Revision ID: 20260813_0011
Revises: 20260813_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260813_0011"
down_revision: str | None = "20260813_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = [
    ("api-test-agent.contract.review", "Review API 契约"),
    ("api-test-agent.case.review", "Review API 测试用例"),
    ("api-test-agent.defect.create", "创建本地 Bug 草稿"),
]

DEFINITIONS = [
    ("CONTRACT_QUALITY_MIN_SCORE", "契约质量最低分", "float", 0.8, {"minimum": 0, "maximum": 1}),
    ("COVERAGE_MAX_ROUNDS", "覆盖补齐最大轮数", "int", 3, {"minimum": 0, "maximum": 3}),
    ("CASE_GENERATION_CONCURRENCY", "用例生成并发数", "int", 1, {"minimum": 1, "maximum": 4}),
    ("DEFAULT_SLOW_THRESHOLD_MS", "默认慢响应阈值毫秒", "int", 3000, {"minimum": 100, "maximum": 60000}),
    ("SLOW_CONFIRMATION_RUNS", "慢响应连续确认次数", "int", 3, {"minimum": 3, "maximum": 3}),
]


def upgrade() -> None:
    """插入权限、配置定义及内置角色的精确授权。"""

    permissions = sa.table(
        "permissions", sa.column("code"), sa.column("name"),
        sa.column("description"), sa.column("resource_type"),
    )
    op.bulk_insert(permissions, [
        {"code": code, "name": name, "description": name, "resource_type": "tool"}
        for code, name in PERMISSIONS
    ])
    definitions = sa.table(
        "config_definitions",
        sa.column("id", sa.String()), sa.column("key", sa.String()), sa.column("display_name", sa.String()),
        sa.column("description", sa.Text()), sa.column("owner_type", sa.String()), sa.column("owner_id", sa.String()),
        sa.column("group_key", sa.String()), sa.column("value_type", sa.String()), sa.column("sensitivity", sa.String()),
        sa.column("required", sa.Boolean()), sa.column("default_value", sa.JSON()), sa.column("validation_schema", sa.JSON()),
        sa.column("apply_mode", sa.String()), sa.column("editable", sa.Boolean()), sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(definitions, [{
        "id": f"api-test-agent.{key}", "key": key, "display_name": display,
        "description": display, "owner_type": "tool", "owner_id": "api-test-agent",
        "group_key": "runtime", "value_type": value_type, "sensitivity": "normal",
        "required": True, "default_value": default, "validation_schema": schema,
        "apply_mode": "next_task", "editable": True, "sort_order": 400 + index * 10,
    } for index, (key, display, value_type, default, schema) in enumerate(DEFINITIONS)])
    grants = sa.table(
        "role_grants", sa.column("role_id"), sa.column("permission_code"),
        sa.column("resource_type"), sa.column("resource_id"), sa.column("created_by"),
    )
    review_codes = [code for code, _name in PERMISSIONS]
    developer_codes = [*review_codes, "api-test-agent.execute"]
    rows = [
        {"role_id": role_id, "permission_code": code, "resource_type": "tool", "resource_id": resource_id, "created_by": "system/migration-api-agent-v2"}
        for role_id, codes, resource_id in (
            # 0009 已给管理员 execute=*，本迁移只追加新 Review 权限，避免重复授权。
            ("role_platform_admin", review_codes, "*"),
            ("role_test_developer", developer_codes, "api-test-agent"),
            # 用户已确认管理员、测试开发和测试执行角色均可最终确认执行。
            ("role_test_executor", developer_codes, "api-test-agent"),
        )
        for code in codes
    ]
    op.bulk_insert(grants, rows)


def downgrade() -> None:
    """仅删除本迁移新增授权、配置和权限；不触碰任务文件。"""

    op.execute(sa.text("DELETE FROM role_grants WHERE created_by='system/migration-api-agent-v2'"))
    definition_ids = [f"api-test-agent.{key}" for key, *_rest in DEFINITIONS]
    op.execute(sa.text("DELETE FROM config_release_items WHERE definition_id IN :ids").bindparams(
        sa.bindparam("ids", expanding=True, value=definition_ids)
    ))
    op.execute(sa.text("DELETE FROM config_definitions WHERE id IN :ids").bindparams(
        sa.bindparam("ids", expanding=True, value=definition_ids)
    ))
    codes = [code for code, _name in PERMISSIONS]
    op.execute(sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(
        sa.bindparam("codes", expanding=True, value=codes)
    ))
