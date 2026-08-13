"""登记两个 AI 测试智能体、配置和最小权限。

Revision ID: 20260812_0009
Revises: 20260811_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260812_0009"
down_revision: str | None = "20260811_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOOLS = [
    {
        "id": "functional-test-agent", "name": "功能测试智能体",
        "description": "需求拆解、测试点 Review 与功能测试用例生成",
        "entry_url": "/functional-test-agent/",
        "health_url": "http://functional-test-agent:5004/functional-test-agent/health",
        "short_code": "FT AI", "icon_key": "functional-ai", "category": "ai-testing",
        "features": ["需求拆解", "测试点 Review", "功能用例"], "sort_order": 50, "is_enabled": True,
    },
    {
        "id": "api-test-agent", "name": "API 测试智能体",
        "description": "API 文档解析与文件化测试用例生成",
        "entry_url": "/api-test-agent/",
        "health_url": "http://api-test-agent:5005/api-test-agent/health",
        "short_code": "API AI", "icon_key": "api-ai", "category": "ai-testing",
        "features": ["API 文档解析", "用例生成", "静态脚本检查"], "sort_order": 60, "is_enabled": True,
    },
]

PERMISSIONS = [
    ("task.cancel", "取消任务"),
    ("task.view.all", "查看全部任务"),
    ("api-test-agent.execute", "执行真实 API 测试"),
]

COMMON_DEFINITIONS = [
    ("LLM_MODEL", "模型名称", "string", "normal", True, "deepseek-v4-flash", {}),
    ("LLM_BASE_URL", "模型服务地址", "url", "normal", True, "https://dashscope.aliyuncs.com/compatible-mode/v1", {}),
    ("TASK_TIMEOUT_SECONDS", "任务超时秒数", "int", "normal", True, 3600, {"minimum": 60, "maximum": 14400}),
    ("QUEUE_MAX_WAITING", "等待队列上限", "int", "normal", True, 5, {"minimum": 1, "maximum": 50}),
    ("UPLOAD_MAX_BYTES", "上传字节上限", "int", "normal", True, 5242880, {"minimum": 1024, "maximum": 26214400}),
    ("UPLOAD_MAX_CHARACTERS", "上传字符上限", "int", "normal", True, 500000, {"minimum": 1000, "maximum": 2000000}),
    ("TASK_SUMMARY_RETENTION_DAYS", "任务摘要保留天数", "int", "normal", True, 180, {"minimum": 1, "maximum": 3650}),
    ("TASK_ARTIFACT_RETENTION_DAYS", "任务文件保留天数", "int", "normal", True, 90, {"minimum": 1, "maximum": 3650}),
    ("TASK_MAX_COMPLETED", "最多终态任务数", "int", "normal", True, 500, {"minimum": 1, "maximum": 10000}),
    ("ARTIFACT_EXPIRY_WARNING_DAYS", "产物到期预警天数", "int", "normal", True, 7, {"minimum": 0, "maximum": 90}),
    ("LLM_API_KEY", "模型 API Key", "secret", "secret", True, None, {}),
]

FUNCTIONAL_DEFINITIONS = [
    ("CASE_GENERATION_BATCH_SIZE", "用例生成批大小", "int", "normal", True, 5, {"minimum": 1, "maximum": 20}),
    ("COVERAGE_MATRIX_ENABLED", "启用覆盖矩阵", "bool", "normal", True, True, {}),
]

API_DEFINITIONS = [
    ("API_EXECUTION_ENABLED", "启用真实 API 执行", "bool", "normal", True, False, {}),
    ("DATABASE_PERSIST_ENABLED", "启用数据库写入", "bool", "normal", True, False, {}),
    ("ALLOWED_TARGETS", "允许访问目标", "json", "normal", True, [], {}),
    ("DB_HOST", "数据库主机", "secret", "secret", False, None, {}),
    ("DB_PORT", "数据库端口", "secret", "secret", False, None, {}),
    ("DB_USER", "数据库用户", "secret", "secret", False, None, {}),
    ("DB_PASSWORD", "数据库密码", "secret", "secret", False, None, {}),
    ("DB_NAME", "数据库名称", "secret", "secret", False, None, {}),
]


def upgrade() -> None:
    """确定性插入新工具、权限、配置定义和内置角色授权。"""

    tools = sa.table(
        "tools",
        sa.column("id", sa.String()), sa.column("name", sa.String()), sa.column("description", sa.Text()),
        sa.column("entry_url", sa.String()), sa.column("health_url", sa.String()), sa.column("short_code", sa.String()),
        sa.column("icon_key", sa.String()), sa.column("category", sa.String()), sa.column("features", sa.JSON()),
        sa.column("sort_order", sa.Integer()), sa.column("is_enabled", sa.Boolean()),
    )
    op.bulk_insert(tools, TOOLS)
    permissions = sa.table("permissions", sa.column("code"), sa.column("name"), sa.column("description"), sa.column("resource_type"))
    op.bulk_insert(permissions, [{"code": code, "name": name, "description": name, "resource_type": "tool"} for code, name in PERMISSIONS])
    definitions = sa.table(
        "config_definitions",
        sa.column("id", sa.String()), sa.column("key", sa.String()), sa.column("display_name", sa.String()),
        sa.column("description", sa.Text()), sa.column("owner_type", sa.String()), sa.column("owner_id", sa.String()),
        sa.column("group_key", sa.String()), sa.column("value_type", sa.String()), sa.column("sensitivity", sa.String()),
        sa.column("required", sa.Boolean()), sa.column("default_value", sa.JSON()),
        sa.column("validation_schema", sa.JSON()), sa.column("apply_mode", sa.String()),
        sa.column("editable", sa.Boolean()), sa.column("sort_order", sa.Integer()),
    )
    rows = []
    for tool_id, extras in (("functional-test-agent", FUNCTIONAL_DEFINITIONS), ("api-test-agent", API_DEFINITIONS)):
        for index, (key, display, value_type, sensitivity, required, default, schema) in enumerate(COMMON_DEFINITIONS + extras, start=1):
            rows.append({
                "id": f"{tool_id}.{key}", "key": key, "display_name": display, "description": display,
                "owner_type": "tool", "owner_id": tool_id,
                "group_key": "credentials" if sensitivity == "secret" else "runtime",
                "value_type": value_type, "sensitivity": sensitivity, "required": required,
                "default_value": default, "validation_schema": schema, "apply_mode": "next_task",
                "editable": True, "sort_order": index * 10,
            })
    op.bulk_insert(definitions, rows)
    grants = sa.table("role_grants", sa.column("role_id"), sa.column("permission_code"), sa.column("resource_type"), sa.column("resource_id"), sa.column("created_by"))
    op.bulk_insert(grants, [
        {"role_id": "role_platform_admin", "permission_code": code, "resource_type": "tool", "resource_id": "*", "created_by": "system/migration-ai-agents"}
        for code, _name in PERMISSIONS
    ] + [
        {"role_id": "role_test_developer", "permission_code": "task.cancel", "resource_type": "tool", "resource_id": tool["id"], "created_by": "system/migration-ai-agents"}
        for tool in TOOLS
    ])


def downgrade() -> None:
    """删除两个工具的配置关系后回滚登记数据；任务文件与审计记录不受影响。"""

    tool_ids = [item["id"] for item in TOOLS]
    definition_ids = [
        f"{tool_id}.{key}"
        for tool_id, extras in (("functional-test-agent", FUNCTIONAL_DEFINITIONS), ("api-test-agent", API_DEFINITIONS))
        for key, *_rest in COMMON_DEFINITIONS + extras
    ]
    op.execute(sa.text("DELETE FROM role_grants WHERE created_by = 'system/migration-ai-agents'"))
    # 先清除可能在部署后创建的引用关系，保证发布过 dev 配置后仍可回滚。
    tool_ids_param = sa.bindparam("tool_ids", expanding=True, value=tool_ids)
    op.execute(sa.text(
        "DELETE FROM credential_items WHERE credential_id IN "
        "(SELECT id FROM credentials WHERE tool_id IN :tool_ids)"
    ).bindparams(tool_ids_param))
    op.execute(sa.text("DELETE FROM credentials WHERE tool_id IN :tool_ids").bindparams(tool_ids_param))
    op.execute(sa.text(
        "DELETE FROM config_activations WHERE owner_type = 'tool' AND owner_id IN :tool_ids"
    ).bindparams(tool_ids_param))
    op.execute(sa.text(
        "DELETE FROM config_release_items WHERE release_id IN "
        "(SELECT id FROM config_releases WHERE owner_type = 'tool' AND owner_id IN :tool_ids)"
    ).bindparams(tool_ids_param))
    op.execute(sa.text(
        "DELETE FROM config_releases WHERE owner_type = 'tool' AND owner_id IN :tool_ids"
    ).bindparams(tool_ids_param))
    op.execute(sa.text(
        "DELETE FROM secret_versions WHERE secret_id IN "
        "(SELECT id FROM secrets WHERE owner_type = 'tool' AND owner_id IN :tool_ids)"
    ).bindparams(tool_ids_param))
    op.execute(sa.text(
        "DELETE FROM secrets WHERE owner_type = 'tool' AND owner_id IN :tool_ids"
    ).bindparams(tool_ids_param))
    op.execute(sa.text("DELETE FROM config_definitions WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True, value=definition_ids)))
    op.execute(sa.text("DELETE FROM tools WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True, value=tool_ids)))
    op.execute(sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(sa.bindparam("codes", expanding=True, value=[item[0] for item in PERMISSIONS])))
