"""在回填完成后收紧项目权限模型核心约束。

Revision ID: 20260824_0020
Revises: 20260824_0019
"""

from collections.abc import Sequence
import hashlib
import json

import sqlalchemy as sa
from alembic import op


revision: str = "20260824_0020"
down_revision: str | None = "20260824_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AUTHORIZATION_STATE_QUERIES = (
    "SELECT id, status, platform_role, permission_version FROM users ORDER BY id",
    "SELECT id, status, revision, authorization_epoch FROM projects ORDER BY id",
    "SELECT id, is_enabled, access_scope, project_id, revision, authorization_epoch FROM tools ORDER BY id",
    "SELECT project_id, user_id, relation FROM project_memberships ORDER BY project_id, user_id",
    "SELECT id, user_id, tool_id, project_id, status, expires_at, revoked_at FROM user_tool_grants ORDER BY id",
    "SELECT environment_id, tool_id, resource_type, resource_id, root_resource_id, owner_user_id, project_id_snapshot, authorization_source_snapshot FROM business_resource_snapshots ORDER BY environment_id, tool_id, resource_type, resource_id",
)


def _authorization_state_digest(connection: sa.Connection) -> str:
    """重算 apply 后授权状态，防止 readiness 与 contract 之间发生在线漂移。"""

    state = [
        [[None if value is None else str(value) for value in row] for row in connection.execute(sa.text(query)).all()]
        for query in AUTHORIZATION_STATE_QUERIES
    ]
    return hashlib.sha256(
        json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def upgrade() -> None:
    """阻断未知角色/工具范围后再建立非空和范围一致性约束。"""

    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        # 先一次性冻结全部会影响授权或历史归属的表，再读取 readiness 与重算摘要。
        # SHARE 与普通读取兼容，但会等待并阻止 RowExclusive 写事务；锁一直持有到
        # 本次 Alembic 事务提交，因此不存在“摘要已验证、约束尚未提交”的 TOCTOU。
        # 固定表顺序与 API 的 user/project/tool/grant 锁序无关，避免迁移互锁。
        connection.execute(sa.text("SET LOCAL lock_timeout = '30s'"))
        connection.execute(sa.text(
            "LOCK TABLE users, projects, tools, project_memberships, "
            "user_tool_grants, business_resource_snapshots IN SHARE MODE"
        ))
    readiness = connection.execute(sa.text(
        "SELECT environment_id, manifest_digest, source_digest, state_digest "
        "FROM project_access_readiness WHERE id='contract-v1'"
    )).mappings().one_or_none()
    if (
        readiness is None
        or readiness["environment_id"] != "prod"
        or not readiness["manifest_digest"]
        or not readiness["source_digest"]
        or readiness["state_digest"] != _authorization_state_digest(connection)
    ):
        raise RuntimeError("完整 manifest、源端对账与 shadow 校验尚未成功应用，禁止执行权限模型 contract")
    unknown_users = connection.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE platform_role IS NULL OR platform_role NOT IN ('platform_admin','admin','tester')")
    ).scalar_one()
    if unknown_users:
        raise RuntimeError("存在未知或未映射用户角色，禁止执行权限模型 contract")
    invalid_tools = connection.execute(
        sa.text("SELECT COUNT(*) FROM tools WHERE access_scope IS NULL OR access_scope NOT IN ('public','project') OR (access_scope='project' AND project_id IS NULL)")
    ).scalar_one()
    if invalid_tools:
        raise RuntimeError("存在未分类或项目缺失的工具，禁止执行权限模型 contract")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("platform_role", existing_type=sa.String(32), nullable=False)
        batch.create_check_constraint("ck_users_platform_role", "platform_role IN ('platform_admin','admin','tester')")
    with op.batch_alter_table("tools") as batch:
        batch.alter_column("access_scope", existing_type=sa.String(16), nullable=False)
        batch.create_check_constraint("ck_tools_access_scope", "access_scope IN ('public','project')")
        batch.create_check_constraint("ck_tools_project_scope", "(access_scope='public' AND project_id IS NULL) OR (access_scope='project' AND project_id IS NOT NULL)")


def downgrade() -> None:
    """回退约束但保留全部新模型写入，供兼容版本继续读取。"""

    with op.batch_alter_table("tools") as batch:
        batch.drop_constraint("ck_tools_project_scope", type_="check")
        batch.drop_constraint("ck_tools_access_scope", type_="check")
        batch.alter_column("access_scope", existing_type=sa.String(16), nullable=True)
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_platform_role", type_="check")
        batch.alter_column("platform_role", existing_type=sa.String(32), nullable=True)
