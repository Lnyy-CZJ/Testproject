"""为 API AutoTest 创建 Truthy、Dating 的生产 Runtime Scope。

Revision ID: 20260831_0024
Revises: 20260828_0023

迁移策略:
    项目包已经随 API AutoTest 镜像发布，但 Web 只展示项目包与 active Scope 的
    交集。此前迁移只创建 Truthy/dev/test 占位 Scope，导致生产即使包含项目包也
    无法展示 Catalog。本迁移只补 ``prod + prod`` Scope 元数据；不创建、复制或
    激活任何 Release、Secret、Credential，生产值仍必须由管理员独立填写。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260831_0024"
down_revision: str | None = "20260828_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MIGRATION_ACTOR = "system/migration-api-autotest-prod-scopes"
PROJECTS = (
    {
        "scope_id": "tps_truthy_prod_prod",
        "project_id": "truthy",
        "display_name": "Truthy People Insight",
        "preferred_default": True,
    },
    {
        "scope_id": "tps_dating_prod_prod",
        "project_id": "dating",
        "display_name": "Dating AI Assistant",
        "preferred_default": False,
    },
)


def _tables() -> tuple[sa.TableClause, sa.TableClause, sa.TableClause, sa.TableClause]:
    """返回迁移所需的最小表映射，避免依赖未来 ORM 模型。"""

    environments = sa.table(
        "environments",
        sa.column("id", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    tools = sa.table(
        "tools",
        sa.column("id", sa.String()),
        sa.column("project_id", sa.String()),
    )
    projects = sa.table(
        "projects",
        sa.column("id", sa.String()),
    )
    scopes = sa.table(
        "tool_project_scopes",
        sa.column("id", sa.String()),
        sa.column("environment_id", sa.String()),
        sa.column("tool_id", sa.String()),
        sa.column("platform_project_id", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("target_env", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("status", sa.String()),
        sa.column("is_default", sa.Boolean()),
        sa.column("revision", sa.Integer()),
        sa.column("created_by", sa.String()),
        sa.column("updated_by", sa.String()),
    )
    return environments, tools, projects, scopes


def _platform_project_id(
    connection: sa.Connection,
    environments: sa.TableClause,
    tools: sa.TableClause,
    projects: sa.TableClause,
) -> str:
    """校验生产环境及工具项目归属，返回 Scope 必须使用的平台项目 ID。

    缺少任一前置条件时阻断迁移。静默跳过会让发布显示成功、生产 Catalog 仍为空，
    因此这里必须 fail-closed。
    """

    prod_active = connection.execute(sa.select(environments.c.is_active).where(
        environments.c.id == "prod",
    )).scalar_one_or_none()
    if prod_active is not True:
        raise RuntimeError("API AutoTest prod Scope 迁移要求有效的 prod 环境")

    platform_project_id = connection.execute(sa.select(tools.c.project_id).where(
        tools.c.id == "api-autotest",
    )).scalar_one_or_none()
    if not platform_project_id:
        raise RuntimeError("API AutoTest 尚未归属平台项目，不能创建 prod Scope")
    project_exists = connection.execute(sa.select(sa.func.count()).select_from(projects).where(
        projects.c.id == platform_project_id,
    )).scalar_one()
    if int(project_exists) != 1:
        raise RuntimeError("API AutoTest 的平台项目不存在，不能创建 prod Scope")
    return str(platform_project_id)


def upgrade() -> None:
    """创建两个 active prod/prod Scope，不附带任何生产运行材料。"""

    connection = op.get_bind()
    environments, tools, projects, scopes = _tables()
    platform_project_id = _platform_project_id(
        connection, environments, tools, projects,
    )
    has_default = bool(connection.execute(sa.select(sa.func.count()).select_from(scopes).where(
        scopes.c.environment_id == "prod",
        scopes.c.tool_id == "api-autotest",
        scopes.c.platform_project_id == platform_project_id,
        scopes.c.is_default.is_(True),
    )).scalar_one())

    for item in PROJECTS:
        existing_id = connection.execute(sa.select(scopes.c.id).where(
            scopes.c.environment_id == "prod",
            scopes.c.tool_id == "api-autotest",
            scopes.c.platform_project_id == platform_project_id,
            scopes.c.project_id == item["project_id"],
            scopes.c.target_env == "prod",
        )).scalar_one_or_none()
        if existing_id is not None:
            # 人工 Scope 可能已经配置或停用；迁移只补缺失项，绝不覆盖其状态。
            continue

        id_collision = connection.execute(sa.select(scopes.c.id).where(
            scopes.c.id == item["scope_id"],
        )).scalar_one_or_none()
        if id_collision is not None:
            raise RuntimeError(
                f"Runtime Scope ID 已被其他边界占用: {item['scope_id']}"
            )

        is_default = bool(item["preferred_default"] and not has_default)
        connection.execute(scopes.insert().values(
            id=item["scope_id"],
            environment_id="prod",
            tool_id="api-autotest",
            platform_project_id=platform_project_id,
            project_id=item["project_id"],
            target_env="prod",
            display_name=item["display_name"],
            status="active",
            is_default=is_default,
            revision=1,
            created_by=MIGRATION_ACTOR,
            updated_by=MIGRATION_ACTOR,
        ))
        has_default = has_default or is_default


def downgrade() -> None:
    """仅删除本迁移创建且从未挂接运行材料的 Scope。

    一旦管理员为 Scope 创建 Release、Secret、Credential 或任务 Context，自动删除
    会破坏审计和历史任务，因此降级必须阻断并要求先走显式数据处置流程。
    """

    connection = op.get_bind()
    _environments, _tools, _projects, scopes = _tables()
    managed_ids = [
        row[0]
        for row in connection.execute(sa.select(scopes.c.id).where(
            scopes.c.created_by == MIGRATION_ACTOR,
            scopes.c.id.in_([item["scope_id"] for item in PROJECTS]),
        )).all()
    ]
    if not managed_ids:
        return

    dependency_queries = (
        ("ConfigActivation", "config_activations", "owner_id", True),
        ("ConfigRelease", "config_releases", "owner_id", True),
        ("Secret", "secrets", "owner_id", True),
        ("Credential", "credentials", "runtime_scope_id", False),
        ("UserCredential", "user_credentials", "runtime_scope_id", False),
        ("RuntimeContext", "runtime_contexts", "runtime_scope_id", False),
    )
    blockers: list[str] = []
    for label, table_name, column_name, has_owner_type in dependency_queries:
        table = sa.table(
            table_name,
            sa.column(column_name, sa.String()),
            *(
                [sa.column("owner_type", sa.String())]
                if has_owner_type
                else []
            ),
        )
        conditions = [getattr(table.c, column_name).in_(managed_ids)]
        if has_owner_type:
            conditions.append(table.c.owner_type == "tool_project_scope")
        count = connection.execute(sa.select(sa.func.count()).select_from(table).where(
            *conditions,
        )).scalar_one()
        if int(count):
            blockers.append(f"{label}={count}")
    if blockers:
        raise RuntimeError(
            "prod Scope 已有关联运行材料，拒绝自动降级: " + ", ".join(blockers)
        )

    connection.execute(scopes.delete().where(
        scopes.c.id.in_(managed_ids),
        scopes.c.created_by == MIGRATION_ACTOR,
    ))
