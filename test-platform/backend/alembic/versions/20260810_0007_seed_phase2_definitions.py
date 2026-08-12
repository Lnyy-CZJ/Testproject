"""写入第二阶段内置权限、角色、环境和配置定义。

Revision ID: 20260810_0007
Revises: 20260810_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0007"
down_revision: str | None = "20260810_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = [
    ("platform.user.manage", "用户管理", "platform"),
    ("platform.role.manage", "角色管理", "platform"),
    ("platform.audit.view", "查看审计", "platform"),
    ("platform.audit.export", "导出审计", "platform"),
    ("platform.config.manage", "平台配置管理", "platform"),
    ("platform.secret.manage", "平台 Secret 管理", "platform"),
    ("tool.view", "查看工具", "tool"),
    ("tool.execute", "执行工具", "tool"),
    ("tool.result.view", "查看工具结果", "tool"),
    ("tool.config.manage", "管理工具配置", "tool"),
    ("tool.secret.manage", "管理工具 Secret", "tool"),
]

ROLES = [
    ("role_platform_admin", "平台管理员", "管理平台、配置和全部工具"),
    ("role_test_developer", "测试开发", "执行工具并维护普通配置"),
    ("role_test_executor", "测试执行者", "执行已授权工具并查看结果"),
    ("role_readonly", "只读查看者", "查看已授权工具和结果"),
    ("role_auditor", "审计查看者", "只读查看和导出审计"),
]

DEFINITIONS = [
    ("truthy-search.SEARCH_API_URL", "SEARCH_API_URL", "检索接口地址", "url", "normal", True, "next_task"),
    ("truthy-search.AUTH_TOKEN", "AUTH_TOKEN", "检索 Access Token", "secret", "secret", True, "next_task"),
    ("truthy-search.REFRESH_TOKEN", "REFRESH_TOKEN", "检索 Refresh Token", "secret", "secret", True, "next_task"),
    ("truthy-search.EXPIRES_TIME", "EXPIRES_TIME", "Access Token 过期时间", "secret", "secret", False, "next_task"),
    ("truthy-search.REFRESH_EXPIRES_TIME", "REFRESH_EXPIRES_TIME", "Refresh Token 过期时间", "secret", "secret", False, "next_task"),
    ("truthy-search.DEVICE_ID", "DEVICE_ID", "检索设备标识", "secret", "secret", True, "next_task"),
    ("truthy-search.USER_ID", "USER_ID", "检索用户标识", "secret", "secret", True, "next_task"),
    ("truthy-search.SEARCH_ADMIN_LOGIN_API_URL", "SEARCH_ADMIN_LOGIN_API_URL", "Admin 登录接口", "url", "normal", False, "next_task"),
    ("truthy-search.SEARCH_ADMIN_API_URL", "SEARCH_ADMIN_API_URL", "Admin 查询接口", "url", "normal", False, "next_task"),
    ("truthy-search.SEARCH_ADMIN_USERNAME", "SEARCH_ADMIN_USERNAME", "Admin 服务账号", "secret", "secret", True, "next_task"),
    ("truthy-search.SEARCH_ADMIN_PASSWORD", "SEARCH_ADMIN_PASSWORD", "Admin 服务密码", "secret", "secret", True, "next_task"),
    ("api-autotest.GATEWAY_API_URL", "GATEWAY_API_URL", "Gateway 会话接口", "url", "normal", True, "next_task"),
    ("api-autotest.AUTH_TOKEN", "AUTH_TOKEN", "接口自动化 Access Token", "secret", "secret", True, "next_task"),
    ("api-autotest.REFRESH_TOKEN", "REFRESH_TOKEN", "接口自动化 Refresh Token", "secret", "secret", True, "next_task"),
    ("api-autotest.EXPIRES_TIME", "EXPIRES_TIME", "Access Token 过期时间", "secret", "secret", False, "next_task"),
    ("api-autotest.REFRESH_EXPIRES_TIME", "REFRESH_EXPIRES_TIME", "Refresh Token 过期时间", "secret", "secret", False, "next_task"),
    ("api-autotest.USER_ID", "USER_ID", "接口自动化用户标识", "secret", "secret", True, "next_task"),
    ("api-autotest.DEVICE_ID", "DEVICE_ID", "接口自动化设备标识", "secret", "secret", True, "next_task"),
    ("api-autotest.ADMIN_LOGIN_API_URL", "ADMIN_LOGIN_API_URL", "Admin 登录接口", "url", "normal", False, "next_task"),
    ("api-autotest.ADMIN_USERNAME", "ADMIN_USERNAME", "Admin 服务账号", "secret", "secret", True, "next_task"),
    ("api-autotest.ADMIN_PASSWORD", "ADMIN_PASSWORD", "Admin 服务密码", "secret", "secret", True, "next_task"),
    ("api-autotest.ADMIN_SESSION_TOKEN", "ADMIN_SESSION_TOKEN", "Admin Session Token", "secret", "secret", False, "next_task"),
]


def upgrade() -> None:
    """确定性写入第二阶段基础数据。"""

    permissions = sa.table("permissions", sa.column("code", sa.String()), sa.column("name", sa.String()), sa.column("description", sa.Text()), sa.column("resource_type", sa.String()))
    op.bulk_insert(permissions, [{"code": code, "name": name, "description": name, "resource_type": resource} for code, name, resource in PERMISSIONS])
    roles = sa.table("roles", sa.column("id", sa.String()), sa.column("name", sa.String()), sa.column("description", sa.Text()), sa.column("is_builtin", sa.Boolean()))
    op.bulk_insert(roles, [{"id": role_id, "name": name, "description": description, "is_builtin": True} for role_id, name, description in ROLES])
    environments = sa.table("environments", sa.column("id", sa.String()), sa.column("name", sa.String()), sa.column("is_active", sa.Boolean()), sa.column("sort_order", sa.Integer()))
    op.bulk_insert(environments, [{"id": "dev", "name": "开发环境", "is_active": True, "sort_order": 10}, {"id": "prod", "name": "生产环境", "is_active": True, "sort_order": 20}])
    definitions = sa.table(
        "config_definitions", sa.column("id", sa.String()), sa.column("key", sa.String()), sa.column("display_name", sa.String()),
        sa.column("description", sa.Text()), sa.column("owner_type", sa.String()), sa.column("owner_id", sa.String()),
        sa.column("group_key", sa.String()), sa.column("value_type", sa.String()), sa.column("sensitivity", sa.String()),
        sa.column("required", sa.Boolean()), sa.column("default_value", sa.JSON()), sa.column("validation_schema", sa.JSON()),
        sa.column("apply_mode", sa.String()), sa.column("editable", sa.Boolean()), sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(definitions, [
        {
            "id": definition_id, "key": key, "display_name": display, "description": display,
            "owner_type": "tool", "owner_id": definition_id.split(".", 1)[0], "group_key": "credentials" if sensitivity == "secret" else "connection",
            "value_type": value_type, "sensitivity": sensitivity, "required": required,
            "default_value": None, "validation_schema": {}, "apply_mode": apply_mode,
            "editable": True, "sort_order": index * 10,
        }
        for index, (definition_id, key, display, value_type, sensitivity, required, apply_mode) in enumerate(DEFINITIONS, start=1)
    ])
    grants = sa.table("role_grants", sa.column("role_id", sa.String()), sa.column("permission_code", sa.String()), sa.column("resource_type", sa.String()), sa.column("resource_id", sa.String()), sa.column("created_by", sa.String()))
    admin_grants = [
        {"role_id": "role_platform_admin", "permission_code": code, "resource_type": resource, "resource_id": "*", "created_by": "system/migration"}
        for code, _, resource in PERMISSIONS
    ]
    auditor_grants = [
        {"role_id": "role_auditor", "permission_code": code, "resource_type": "platform", "resource_id": "*", "created_by": "system/migration"}
        for code in ("platform.audit.view", "platform.audit.export")
    ]
    tool_role_grants = [
        {"role_id": role_id, "permission_code": code, "resource_type": "tool", "resource_id": "*", "created_by": "system/migration"}
        for role_id, codes in (
            ("role_test_developer", ("tool.view", "tool.execute", "tool.result.view", "tool.config.manage")),
            ("role_test_executor", ("tool.view", "tool.execute", "tool.result.view")),
            ("role_readonly", ("tool.view", "tool.result.view")),
        )
        for code in codes
    ]
    op.bulk_insert(grants, admin_grants + auditor_grants + tool_role_grants)


def downgrade() -> None:
    """只删除本迁移写入的确定性种子。"""

    op.execute(sa.text("DELETE FROM role_grants WHERE created_by = 'system/migration'"))
    op.execute(sa.text("DELETE FROM config_definitions WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True, value=[item[0] for item in DEFINITIONS])))
    op.execute(sa.text("DELETE FROM environments WHERE id IN ('dev', 'prod')"))
    op.execute(sa.text("DELETE FROM roles WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True, value=[item[0] for item in ROLES])))
    op.execute(sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(sa.bindparam("codes", expanding=True, value=[item[0] for item in PERMISSIONS])))
