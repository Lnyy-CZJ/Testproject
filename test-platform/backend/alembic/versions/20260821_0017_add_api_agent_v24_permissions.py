"""登记 API 测试智能体 V2.4 的执行定义生成与 Review 权限。

Revision ID: 20260821_0017
Revises: 20260818_0016

功能说明:
    V2.4 将可执行用例的生成与人工 Review 从基础用例 Review 中拆分。
    本迁移只追加权限定义和内置角色授权；不会修改旧 0011 迁移、历史任务或
    既有 ``api-test-agent.execute`` 的真实执行权限。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260821_0017"
down_revision: str | None = "20260818_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = [
    ("api-test-agent.executable.generate", "生成 API 可执行用例"),
    ("api-test-agent.executable.review", "Review API 可执行用例"),
]


def upgrade() -> None:
    """新增 V2.4 能力权限，并仅授权可完成测试流程的内置角色。"""

    permissions = sa.table(
        "permissions",
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("resource_type", sa.String()),
    )
    op.bulk_insert(permissions, [
        {"code": code, "name": name, "description": name, "resource_type": "tool"}
        for code, name in PERMISSIONS
    ])

    grants = sa.table(
        "role_grants",
        sa.column("role_id", sa.String()),
        sa.column("permission_code", sa.String()),
        sa.column("resource_type", sa.String()),
        sa.column("resource_id", sa.String()),
        sa.column("created_by", sa.String()),
    )
    # 管理员使用全局工具资源；测试开发和测试执行者仅取得 API 测试智能体范围授权。
    op.bulk_insert(grants, [
        {
            "role_id": role_id,
            "permission_code": permission_code,
            "resource_type": "tool",
            "resource_id": resource_id,
            "created_by": "system/migration-api-agent-v24",
        }
        for role_id, resource_id in (
            ("role_platform_admin", "*"),
            ("role_test_developer", "api-test-agent"),
            ("role_test_executor", "api-test-agent"),
        )
        for permission_code, _name in PERMISSIONS
    ])


def downgrade() -> None:
    """仅撤销 V2.4 新增权限及其本迁移创建的授权，不触碰历史任务文件。"""

    connection = op.get_bind()
    codes = [code for code, _name in PERMISSIONS]
    connection.execute(
        sa.text(
            "DELETE FROM role_grants WHERE created_by='system/migration-api-agent-v24' "
            "AND permission_code IN :codes"
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": codes},
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(
            sa.bindparam("codes", expanding=True)
        ),
        {"codes": codes},
    )
