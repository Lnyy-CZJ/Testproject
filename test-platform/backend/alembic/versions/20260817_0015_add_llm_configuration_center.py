"""新增 LLM Profile、工具绑定、权限和配置定义。

Revision ID: 20260817_0015
Revises: 20260816_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260817_0015"
down_revision: str | None = "20260816_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILE_ID = "llmp_shared_default"
BINDINGS = (
    ("llmb_functional_default", "functional-test-agent", "default", "功能测试智能体默认模型"),
    ("llmb_api_default", "api-test-agent", "default", "API 测试智能体默认模型"),
    ("llmb_log_people_search", "log-filter", "people-search-summary", "People Search 日志 AI 总结"),
)
PERMISSIONS = (
    ("platform.llm.manage", "LLM 配置管理"),
    ("platform.llm.secret.manage", "LLM Secret 管理"),
)


def _definition(owner_type: str, owner_id: str, key: str, display_name: str,
                value_type: str, sensitivity: str = "normal", required: bool = False,
                default_value=None, validation_schema=None, sort_order: int = 0) -> dict:
    """构造确定性的配置定义种子。"""

    return {
        "id": f"{owner_id}.{key}", "key": key, "display_name": display_name,
        "description": display_name, "owner_type": owner_type, "owner_id": owner_id,
        "group_key": "secret" if sensitivity == "secret" else "model",
        "value_type": value_type, "sensitivity": sensitivity, "required": required,
        "default_value": default_value, "validation_schema": validation_schema or {},
        "apply_mode": "next_task", "editable": True, "sort_order": sort_order,
    }


def upgrade() -> None:
    """创建 LLM 配置中心身份表并写入最小确定性种子。"""

    op.create_table(
        "llm_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("name_normalized", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("protocol", sa.String(32), nullable=False, server_default="openai_compatible"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("protocol = 'openai_compatible'", name="ck_llm_profiles_protocol"),
    )
    op.create_table(
        "tool_llm_bindings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tool_id", sa.String(64), sa.ForeignKey("tools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability_key", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tool_id", "capability_key", name="uq_tool_llm_binding_capability"),
    )
    profiles = sa.table(
        "llm_profiles", sa.column("id", sa.String()), sa.column("name", sa.String()),
        sa.column("name_normalized", sa.String()), sa.column("description", sa.Text()),
        sa.column("protocol", sa.String()), sa.column("is_archived", sa.Boolean()),
        sa.column("created_by", sa.String()),
    )
    op.bulk_insert(profiles, [{
        "id": PROFILE_ID, "name": "共享默认模型", "name_normalized": "共享默认模型",
        "description": "功能与 API 测试智能体可复用的 OpenAI-compatible 配置",
        "protocol": "openai_compatible", "is_archived": False, "created_by": "system/migration-llm",
    }])
    bindings = sa.table(
        "tool_llm_bindings", sa.column("id", sa.String()), sa.column("tool_id", sa.String()),
        sa.column("capability_key", sa.String()), sa.column("display_name", sa.String()),
        sa.column("description", sa.Text()), sa.column("created_by", sa.String()),
    )
    op.bulk_insert(bindings, [{
        "id": binding_id, "tool_id": tool_id, "capability_key": capability,
        "display_name": display_name, "description": "由平台按任务提供不可变 LLM 配置快照",
        "created_by": "system/migration-llm",
    } for binding_id, tool_id, capability, display_name in BINDINGS])

    definitions = sa.table(
        "config_definitions", sa.column("id", sa.String()), sa.column("key", sa.String()),
        sa.column("display_name", sa.String()), sa.column("description", sa.Text()),
        sa.column("owner_type", sa.String()), sa.column("owner_id", sa.String()),
        sa.column("group_key", sa.String()), sa.column("value_type", sa.String()),
        sa.column("sensitivity", sa.String()), sa.column("required", sa.Boolean()),
        sa.column("default_value", sa.JSON()), sa.column("validation_schema", sa.JSON()),
        sa.column("apply_mode", sa.String()), sa.column("editable", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    rows = [
        _definition("platform", "platform", "LLM_PROVIDER_HOST_ALLOWLIST", "LLM Provider 主机允许列表", "json", default_value=["dashscope.aliyuncs.com"], sort_order=900),
        _definition("llm_profile", PROFILE_ID, "BASE_URL", "API Base URL", "url", required=True, sort_order=10),
        _definition("llm_profile", PROFILE_ID, "MODEL", "模型名称", "string", required=True, validation_schema={"min_length": 1, "max_length": 256}, sort_order=20),
        _definition("llm_profile", PROFILE_ID, "TEMPERATURE", "Temperature", "float", validation_schema={"minimum": 0, "maximum": 2}, sort_order=30),
        _definition("llm_profile", PROFILE_ID, "MAX_TOKENS", "Max Tokens", "int", validation_schema={"minimum": 1, "maximum": 131072}, sort_order=40),
        _definition("llm_profile", PROFILE_ID, "TIMEOUT_SECONDS", "请求超时（秒）", "int", validation_schema={"minimum": 1, "maximum": 600}, sort_order=50),
        _definition("llm_profile", PROFILE_ID, "ENABLED", "启用", "bool", required=True, default_value=True, sort_order=60),
        _definition("llm_profile", PROFILE_ID, "API_KEY", "API Key", "secret", "secret", True, sort_order=70),
    ]
    for binding_id, _, _, _ in BINDINGS:
        rows.extend([
            _definition("llm_binding", binding_id, "PROFILE_ID", "公共配置", "string", required=True, default_value=PROFILE_ID, sort_order=10),
            _definition("llm_binding", binding_id, "ENABLED", "启用", "bool", required=True, default_value=True, sort_order=20),
            _definition("llm_binding", binding_id, "MODEL_OVERRIDE", "模型覆盖", "string", validation_schema={"max_length": 256}, sort_order=30),
            _definition("llm_binding", binding_id, "TEMPERATURE_OVERRIDE", "Temperature 覆盖", "float", validation_schema={"minimum": 0, "maximum": 2}, sort_order=40),
            _definition("llm_binding", binding_id, "MAX_TOKENS_OVERRIDE", "Max Tokens 覆盖", "int", validation_schema={"minimum": 1, "maximum": 131072}, sort_order=50),
            _definition("llm_binding", binding_id, "TIMEOUT_SECONDS_OVERRIDE", "请求超时覆盖（秒）", "int", validation_schema={"minimum": 1, "maximum": 600}, sort_order=60),
            _definition("llm_binding", binding_id, "API_KEY_OVERRIDE", "独立 API Key", "secret", "secret", False, sort_order=70),
        ])
    op.bulk_insert(definitions, rows)

    permissions = sa.table(
        "permissions", sa.column("code", sa.String()), sa.column("name", sa.String()),
        sa.column("description", sa.Text()), sa.column("resource_type", sa.String()),
    )
    op.bulk_insert(permissions, [{"code": code, "name": name, "description": name, "resource_type": "platform"} for code, name in PERMISSIONS])
    grants = sa.table(
        "role_grants", sa.column("role_id", sa.String()), sa.column("permission_code", sa.String()),
        sa.column("resource_type", sa.String()), sa.column("resource_id", sa.String()),
        sa.column("created_by", sa.String()),
    )
    op.bulk_insert(grants, [{
        "role_id": "role_platform_admin", "permission_code": code,
        "resource_type": "platform", "resource_id": "*", "created_by": "system/migration-llm",
    } for code, _ in PERMISSIONS])


def downgrade() -> None:
    """仅在没有 LLM 业务版本数据时移除本迁移对象。"""

    connection = op.get_bind()
    owners = [PROFILE_ID, *(row[0] for row in BINDINGS)]
    referenced = connection.execute(sa.text(
        "SELECT COUNT(*) FROM config_releases WHERE owner_type IN ('llm_profile','llm_binding')"
    )).scalar_one()
    secret_count = connection.execute(sa.text(
        "SELECT COUNT(*) FROM secrets WHERE owner_type IN ('llm_profile','llm_binding')"
    )).scalar_one()
    if referenced or secret_count:
        raise RuntimeError("LLM 配置已有 Release 或 Secret，拒绝破坏性降级")
    connection.execute(sa.text("DELETE FROM role_grants WHERE created_by='system/migration-llm'"))
    connection.execute(sa.text("DELETE FROM permissions WHERE code IN ('platform.llm.manage','platform.llm.secret.manage')"))
    connection.execute(sa.text("DELETE FROM config_definitions WHERE owner_id IN :owners").bindparams(sa.bindparam("owners", expanding=True, value=owners)))
    connection.execute(sa.text("DELETE FROM config_definitions WHERE id='platform.LLM_PROVIDER_HOST_ALLOWLIST'"))
    op.drop_table("tool_llm_bindings")
    op.drop_table("llm_profiles")
