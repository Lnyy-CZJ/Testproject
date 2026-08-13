"""登记在线测试用例 Review 配置并创建 dev 开启 Release。

Revision ID: 20260814_0012
Revises: 20260813_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260814_0012"
down_revision: str | None = "20260813_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFINITIONS = [
    ("ONLINE_CASE_REVIEW_ENABLED", "启用在线测试用例 Review", "bool", False, {}),
    ("CASE_REVIEW_AI_ENABLED", "启用测试用例 AI Review", "bool", False, {}),
    ("CASE_REVIEW_AI_TIMEOUT_SECONDS", "测试用例 AI 超时秒数", "int", 600, {"minimum": 60, "maximum": 1800}),
    ("CASE_REVIEW_AI_MAX_SELECTED_CASES", "用例 AI 改写选中项上限", "int", 50, {"minimum": 1, "maximum": 200}),
    ("CASE_REVIEW_AI_MAX_SUGGESTIONS", "用例 AI 单次建议上限", "int", 100, {"minimum": 1, "maximum": 200}),
    ("CASE_REVIEW_AI_MAX_CONTEXT_CASES", "用例 AI 上下文用例上限", "int", 300, {"minimum": 1, "maximum": 1000}),
    ("CASE_REVIEW_AI_MAX_CONTEXT_POINTS", "用例 AI 上下文测试点上限", "int", 300, {"minimum": 1, "maximum": 1000}),
    ("CASE_REVIEW_AI_MAX_INSTRUCTION_CHARACTERS", "用例 AI 用户说明字符上限", "int", 2000, {"minimum": 1, "maximum": 10000}),
    ("CASE_REVIEW_MAX_CASES", "在线 Review 用例数量上限", "int", 2000, {"minimum": 1, "maximum": 5000}),
    ("CASE_REVIEW_MAX_BYTES", "在线 Review 正文字节上限", "int", 10485760, {"minimum": 1048576, "maximum": 10485760}),
    ("CASE_REVIEW_MAX_CHARACTERS", "在线 Review 字符上限", "int", 1000000, {"minimum": 10000, "maximum": 1000000}),
]


def upgrade() -> None:
    """插入安全默认定义，并克隆当前 dev Release 后开启两个开关。"""

    definitions = sa.table(
        "config_definitions",
        sa.column("id", sa.String()), sa.column("key", sa.String()), sa.column("display_name", sa.String()),
        sa.column("description", sa.Text()), sa.column("owner_type", sa.String()), sa.column("owner_id", sa.String()),
        sa.column("group_key", sa.String()), sa.column("value_type", sa.String()), sa.column("sensitivity", sa.String()),
        sa.column("required", sa.Boolean()), sa.column("default_value", sa.JSON()), sa.column("validation_schema", sa.JSON()),
        sa.column("apply_mode", sa.String()), sa.column("editable", sa.Boolean()), sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(definitions, [{
        "id": f"functional-test-agent.{key}", "key": key, "display_name": display,
        "description": display, "owner_type": "tool", "owner_id": "functional-test-agent",
        "group_key": "runtime", "value_type": value_type, "sensitivity": "normal", "required": True,
        "default_value": default, "validation_schema": schema, "apply_mode": "next_task", "editable": True,
        "sort_order": 500 + index * 10,
    } for index, (key, display, value_type, default, schema) in enumerate(DEFINITIONS)])

    connection = op.get_bind()
    active = connection.execute(sa.text(
        "SELECT active_release_id FROM config_activations WHERE environment_id='dev' AND owner_type='tool' AND owner_id='functional-test-agent'"
    )).scalar()
    version = int(connection.execute(sa.text(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM config_releases WHERE environment_id='dev' AND owner_type='tool' AND owner_id='functional-test-agent'"
    )).scalar_one())
    release_id = f"rel_functional_case_review_dev_{version}"
    connection.execute(sa.text(
        "INSERT INTO config_releases (id, environment_id, owner_type, owner_id, version, revision, status, based_on_release_id, created_by, published_by, published_at) "
        "VALUES (:id, 'dev', 'tool', 'functional-test-agent', :version, 1, 'active', :based, 'system/migration-case-review', 'system/migration-case-review', CURRENT_TIMESTAMP)"
    ), {"id": release_id, "version": version, "based": active})
    if active:
        connection.execute(sa.text(
            "INSERT INTO config_release_items (release_id, definition_id, value_json, secret_version_id) "
            "SELECT :new_id, definition_id, value_json, secret_version_id FROM config_release_items WHERE release_id=:old_id"
        ), {"new_id": release_id, "old_id": active})
    statement = sa.text(
        "INSERT INTO config_release_items (release_id, definition_id, value_json) VALUES (:release_id, :definition_id, :value)"
    ).bindparams(sa.bindparam("value", type_=sa.JSON()))
    for key in ("ONLINE_CASE_REVIEW_ENABLED", "CASE_REVIEW_AI_ENABLED"):
        connection.execute(statement, {"release_id": release_id, "definition_id": f"functional-test-agent.{key}", "value": True})
    if active:
        connection.execute(sa.text(
            "UPDATE config_activations SET active_release_id=:release_id, confirmed_release_id=NULL, confirmed_at=NULL "
            "WHERE environment_id='dev' AND owner_type='tool' AND owner_id='functional-test-agent'"
        ), {"release_id": release_id})
    else:
        connection.execute(sa.text(
            "INSERT INTO config_activations (environment_id, owner_type, owner_id, active_release_id) VALUES ('dev', 'tool', 'functional-test-agent', :release_id)"
        ), {"release_id": release_id})


def downgrade() -> None:
    """恢复迁移前 dev Release，仅删除本期定义和种子 Release。"""

    connection = op.get_bind()
    row = connection.execute(sa.text(
        "SELECT id, based_on_release_id FROM config_releases WHERE created_by='system/migration-case-review' "
        "AND environment_id='dev' AND owner_id='functional-test-agent' ORDER BY version DESC"
    )).mappings().first()
    if row:
        active = connection.execute(sa.text(
            "SELECT active_release_id FROM config_activations WHERE environment_id='dev' AND owner_type='tool' AND owner_id='functional-test-agent'"
        )).scalar()
        if active == row["id"] and row["based_on_release_id"]:
            connection.execute(sa.text(
                "UPDATE config_activations SET active_release_id=:previous WHERE environment_id='dev' AND owner_type='tool' AND owner_id='functional-test-agent'"
            ), {"previous": row["based_on_release_id"]})
        elif active == row["id"]:
            connection.execute(sa.text(
                "DELETE FROM config_activations WHERE environment_id='dev' AND owner_type='tool' AND owner_id='functional-test-agent'"
            ))
    ids = [f"functional-test-agent.{key}" for key, *_rest in DEFINITIONS]
    connection.execute(sa.text("DELETE FROM config_release_items WHERE definition_id IN :ids").bindparams(sa.bindparam("ids", expanding=True, value=ids)))
    scope = "created_by='system/migration-case-review' AND environment_id='dev' AND owner_type='tool' AND owner_id='functional-test-agent'"
    connection.execute(sa.text(f"DELETE FROM config_release_items WHERE release_id IN (SELECT id FROM config_releases WHERE {scope})"))
    connection.execute(sa.text(f"DELETE FROM config_releases WHERE {scope}"))
    connection.execute(sa.text("DELETE FROM config_definitions WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True, value=ids)))
