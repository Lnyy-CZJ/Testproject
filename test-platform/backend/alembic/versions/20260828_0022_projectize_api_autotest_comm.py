"""项目化接口自动化 Comm 静态配置，并拆分误复制的 Dating 值。

Revision ID: 20260828_0022
Revises: 20260827_0021

迁移策略:
    ConfigDefinition 继续保持 Tool 级，项目适用范围写入 validation_schema。
    仅当 dev/test 的 Dating 与同一平台项目下 Truthy 的当前 comm 完全相同时，
    才判定 Dating 值来自历史复制并创建一个新的已发布版本。已人工调整的 Dating
    值、prod Scope 以及 Truthy Release 均保持不变。
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "20260828_0022"
down_revision: str | None = "20260827_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MIGRATION_ACTOR = "system/migration-projectized-api-autotest-comm"
COMM_DEFINITION_ID = "api-autotest.runtime.gateway.comm"

COMM_SCHEMA = {
    "required_keys": ["device_id", "platform", "app_version"],
    "forbidden_keys": ["auth_token", "user_id", "client_request_id"],
    "property_name_pattern": "^[a-z][a-z0-9_]{0,63}$",
    "string_values": True,
    "max_properties": 32,
    "field_order": [
        "device_id",
        "platform",
        "app_version",
        "locale",
        "timezone",
        "country",
        "app_package",
    ],
    "field_labels": {
        "device_id": "Device ID",
        "platform": "客户端平台",
        "app_version": "客户端版本",
        "locale": "语言区域",
        "timezone": "时区",
        "country": "国家/地区",
        "app_package": "应用包名",
    },
}

DATING_COMM_DEFAULTS = {
    "platform": "ios",
    "app_version": "1.0.0",
    "locale": "en-US",
    "timezone": "UTC+08:00",
    "country": "CN",
    "app_package": "com.example.dating",
}


def _tables() -> tuple[sa.TableClause, sa.TableClause, sa.TableClause, sa.TableClause, sa.TableClause]:
    """返回迁移所需的轻量表定义，确保 JSON 在 SQLite/PostgreSQL 中正确绑定。"""

    definitions = sa.table(
        "config_definitions",
        sa.column("id", sa.String()),
        sa.column("validation_schema", sa.JSON()),
    )
    scopes = sa.table(
        "tool_project_scopes",
        sa.column("id", sa.String()),
        sa.column("environment_id", sa.String()),
        sa.column("tool_id", sa.String()),
        sa.column("platform_project_id", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("target_env", sa.String()),
    )
    releases = sa.table(
        "config_releases",
        sa.column("id", sa.String()),
        sa.column("environment_id", sa.String()),
        sa.column("owner_type", sa.String()),
        sa.column("owner_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("revision", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("based_on_release_id", sa.String()),
        sa.column("created_by", sa.String()),
        sa.column("published_by", sa.String()),
        sa.column("published_at", sa.DateTime(timezone=True)),
    )
    items = sa.table(
        "config_release_items",
        sa.column("release_id", sa.String()),
        sa.column("definition_id", sa.String()),
        sa.column("value_json", sa.JSON()),
        sa.column("secret_version_id", sa.String()),
    )
    activations = sa.table(
        "config_activations",
        sa.column("environment_id", sa.String()),
        sa.column("owner_type", sa.String()),
        sa.column("owner_id", sa.String()),
        sa.column("active_release_id", sa.String()),
        sa.column("confirmed_release_id", sa.String()),
        sa.column("confirmed_at", sa.DateTime(timezone=True)),
    )
    return definitions, scopes, releases, items, activations


def _active_release_id(
    connection: sa.Connection,
    activations: sa.TableClause,
    scope_id: str,
) -> str | None:
    """读取一个 Runtime Scope 当前激活的 Release ID。"""

    return connection.execute(sa.select(activations.c.active_release_id).where(
        activations.c.environment_id == "dev",
        activations.c.owner_type == "tool_project_scope",
        activations.c.owner_id == scope_id,
    )).scalar_one_or_none()


def _release_comm(
    connection: sa.Connection,
    items: sa.TableClause,
    release_id: str | None,
) -> dict[str, str] | None:
    """读取 Release 的 comm 对象；缺失或非对象时返回 None 并跳过数据拆分。"""

    if release_id is None:
        return None
    value = connection.execute(sa.select(items.c.value_json).where(
        items.c.release_id == release_id,
        items.c.definition_id == COMM_DEFINITION_ID,
    )).scalar_one_or_none()
    return value if isinstance(value, dict) else None


def _projectize_copied_dating_comm(
    connection: sa.Connection,
    scopes: sa.TableClause,
    releases: sa.TableClause,
    items: sa.TableClause,
    activations: sa.TableClause,
) -> None:
    """为确认复制自 Truthy 的 Dating/test comm 发布独立版本。

    相等比较是迁移的数据安全门：无法证明是复制值时绝不覆盖。新版本完整复制
    原 Release 的其他配置和 Secret 版本引用，仅替换 ``gateway.comm``。
    """

    dating_scopes = connection.execute(sa.select(
        scopes.c.id,
        scopes.c.tool_id,
        scopes.c.platform_project_id,
    ).where(
        scopes.c.tool_id == "api-autotest",
        scopes.c.project_id == "dating",
        scopes.c.environment_id == "dev",
        scopes.c.target_env == "test",
    )).mappings().all()

    for dating_scope in dating_scopes:
        truthy_scope_id = connection.execute(sa.select(scopes.c.id).where(
            scopes.c.tool_id == dating_scope["tool_id"],
            scopes.c.platform_project_id == dating_scope["platform_project_id"],
            scopes.c.project_id == "truthy",
            scopes.c.environment_id == "dev",
            scopes.c.target_env == "test",
        )).scalar_one_or_none()
        if truthy_scope_id is None:
            continue

        dating_release_id = _active_release_id(
            connection, activations, dating_scope["id"]
        )
        truthy_release_id = _active_release_id(connection, activations, truthy_scope_id)
        dating_comm = _release_comm(connection, items, dating_release_id)
        truthy_comm = _release_comm(connection, items, truthy_release_id)
        if dating_comm is None or dating_comm != truthy_comm:
            continue

        # 已存在草稿说明管理员正在调整该项目；迁移不得越过人工工作创建新激活版本。
        has_draft = connection.execute(sa.select(sa.func.count()).select_from(releases).where(
            releases.c.environment_id == "dev",
            releases.c.owner_type == "tool_project_scope",
            releases.c.owner_id == dating_scope["id"],
            releases.c.status == "draft",
        )).scalar_one()
        if has_draft:
            continue

        current_version = connection.execute(sa.select(sa.func.max(releases.c.version)).where(
            releases.c.environment_id == "dev",
            releases.c.owner_type == "tool_project_scope",
            releases.c.owner_id == dating_scope["id"],
        )).scalar_one()
        new_release_id = f"rel_0022_{uuid4().hex}"
        now = datetime.now(UTC)
        connection.execute(releases.insert().values(
            id=new_release_id,
            environment_id="dev",
            owner_type="tool_project_scope",
            owner_id=dating_scope["id"],
            version=int(current_version) + 1,
            revision=1,
            status="active",
            based_on_release_id=dating_release_id,
            created_by=MIGRATION_ACTOR,
            published_by=MIGRATION_ACTOR,
            published_at=now,
        ))

        new_comm = {"device_id": str(uuid4()), **DATING_COMM_DEFAULTS}
        old_items = connection.execute(sa.select(
            items.c.definition_id,
            items.c.value_json,
            items.c.secret_version_id,
        ).where(items.c.release_id == dating_release_id)).mappings().all()
        for old_item in old_items:
            # Admin 登录地址属于 Truthy；历史 Dating Release 保留作审计，但新的
            # Dating 激活版本不再携带这个静态配置。
            if old_item["definition_id"] == "api-autotest.ADMIN_LOGIN_API_URL":
                continue
            value = (
                new_comm
                if old_item["definition_id"] == COMM_DEFINITION_ID
                else old_item["value_json"]
            )
            connection.execute(items.insert().values(
                release_id=new_release_id,
                definition_id=old_item["definition_id"],
                value_json=value,
                secret_version_id=old_item["secret_version_id"],
            ))

        connection.execute(releases.update().where(
            releases.c.id == dating_release_id,
        ).values(status="superseded"))
        connection.execute(activations.update().where(
            activations.c.environment_id == "dev",
            activations.c.owner_type == "tool_project_scope",
            activations.c.owner_id == dating_scope["id"],
        ).values(active_release_id=new_release_id))


def upgrade() -> None:
    """发布项目化配置契约，并安全拆分 Dating 的历史复制值。"""

    connection = op.get_bind()
    definitions, scopes, releases, items, activations = _tables()
    schema_updates = {
        COMM_DEFINITION_ID: COMM_SCHEMA,
        "api-autotest.runtime.flow.analysis.poll_interval_seconds": {
            "minimum": 0.1,
            "maximum": 60,
            "project_ids": ["dating"],
        },
        "api-autotest.runtime.flow.analysis.timeout_seconds": {
            "minimum": 1,
            "maximum": 1800,
            "project_ids": ["dating"],
        },
        "api-autotest.ADMIN_LOGIN_API_URL": {"project_ids": ["truthy"]},
    }
    for definition_id, schema in schema_updates.items():
        connection.execute(definitions.update().where(
            definitions.c.id == definition_id,
        ).values(validation_schema=schema))

    _projectize_copied_dating_comm(
        connection, scopes, releases, items, activations
    )


def downgrade() -> None:
    """恢复迁移前激活版本和 Definition 契约，不触碰后续人工配置。"""

    connection = op.get_bind()
    definitions, _scopes, releases, items, activations = _tables()
    migration_releases = connection.execute(sa.select(
        releases.c.id,
        releases.c.environment_id,
        releases.c.owner_type,
        releases.c.owner_id,
        releases.c.based_on_release_id,
    ).where(releases.c.created_by == MIGRATION_ACTOR)).mappings().all()

    for migration_release in migration_releases:
        active_release_id = connection.execute(sa.select(
            activations.c.active_release_id
        ).where(
            activations.c.environment_id == migration_release["environment_id"],
            activations.c.owner_type == migration_release["owner_type"],
            activations.c.owner_id == migration_release["owner_id"],
        )).scalar_one_or_none()
        if active_release_id != migration_release["id"]:
            raise RuntimeError(
                "Dating 配置已在 0022 后继续发布；请先回滚至迁移版本再降级"
            )
        previous_release_id = migration_release["based_on_release_id"]
        connection.execute(activations.update().where(
            activations.c.environment_id == migration_release["environment_id"],
            activations.c.owner_type == migration_release["owner_type"],
            activations.c.owner_id == migration_release["owner_id"],
        ).values(active_release_id=previous_release_id))
        connection.execute(releases.update().where(
            releases.c.id == previous_release_id,
        ).values(status="active"))
        connection.execute(items.delete().where(
            items.c.release_id == migration_release["id"]
        ))
        connection.execute(releases.delete().where(
            releases.c.id == migration_release["id"]
        ))

    previous_schemas = {
        COMM_DEFINITION_ID: {},
        "api-autotest.runtime.flow.analysis.poll_interval_seconds": {
            "minimum": 0.1,
            "maximum": 60,
        },
        "api-autotest.runtime.flow.analysis.timeout_seconds": {
            "minimum": 1,
            "maximum": 1800,
        },
        "api-autotest.ADMIN_LOGIN_API_URL": {},
    }
    for definition_id, schema in previous_schemas.items():
        connection.execute(definitions.update().where(
            definitions.c.id == definition_id,
        ).values(validation_schema=schema))
