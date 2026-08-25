from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.access import BusinessResourceSnapshot, Project, ProjectMembership, UserToolGrant
from app.models.configuration import Environment
from app.models.identity import User
from app.models.tool import Tool
from app.core.errors import PlatformError
from app.services.authorization import consume_public_tool_usage, decide_tool_access, decide_tool_access_batch, platform_permissions_for_role
from app.services.resource_authorization import decide_resource_access
from app import migrate_project_access


def _user(database: Session, user_id: str, role: str) -> User:
    """创建权限测试用户，密码字段仅满足数据库约束。"""

    row = User(
        id=user_id,
        username=user_id,
        username_normalized=user_id,
        display_name=user_id,
        password_hash="unused",
        status="active",
        platform_role=role,
    )
    database.add(row)
    return row


def _tool(database: Session, tool_id: str, scope: str, project_id: str | None = None) -> Tool:
    """创建最小工具目录记录。"""

    row = Tool(
        id=tool_id,
        name=tool_id,
        description="test",
        entry_url=f"/tools/{tool_id}/",
        health_url="http://tool/health",
        short_code=tool_id[:8],
        icon_key="test",
        category="test",
        features=[],
        access_scope=scope,
        project_id=project_id,
        public_safety_policy_status="complete" if scope == "public" else "missing",
        public_safety_policy={
            "request_quota_per_minute": 10,
            "task_quota_per_day": 20,
            "cost_quota_daily": 5,
            "cost_reservation_per_task": 0.25,
            "real_execution_enabled": False,
            "target_allowlist": ["example.test"],
        } if scope == "public" else {},
    )
    database.add(row)
    return row


def test_fixed_roles_have_explicit_management_permissions() -> None:
    """固定角色矩阵不得再依赖可编辑 RoleGrant。"""

    assert "platform.user.manage" in platform_permissions_for_role("platform_admin")
    assert "project.member.manage" in platform_permissions_for_role("admin")
    assert platform_permissions_for_role("tester") == frozenset()
    assert platform_permissions_for_role("unknown") == frozenset()


def test_tool_access_sources_are_public_project_and_extra_grant(
    database_factory: sessionmaker[Session],
) -> None:
    """公共、项目继承和临时授权必须产生可解释且互斥的主要来源。"""

    with database_factory() as database:
        tester = _user(database, "tester", "tester")
        project = Project(id="prj-a", code="A", name="项目 A", status="active")
        database.add(project)
        public_tool = _tool(database, "public-tool", "public")
        project_tool = _tool(database, "project-tool", "project", project.id)
        extra_tool = _tool(database, "extra-tool", "project", project.id)
        database.flush()

        assert decide_tool_access(database, tester, public_tool).source == "public"
        assert not decide_tool_access(database, tester, project_tool).allowed

        database.add(ProjectMembership(project_id=project.id, user_id=tester.id, relation="member"))
        database.flush()
        assert decide_tool_access(database, tester, project_tool).source == "project_member"

        database.delete(database.get(ProjectMembership, (project.id, tester.id)))
        database.add(
            UserToolGrant(
                id="grant-a",
                user_id=tester.id,
                tool_id=extra_tool.id,
                project_id=project.id,
                status="active",
                granted_by_user_id="platform-admin",
                grant_reason="临时排障",
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        database.flush()
        assert decide_tool_access(database, tester, extra_tool).source == "extra_grant"


def test_resource_access_does_not_follow_tool_access(
    database_factory: sessionmaker[Session],
) -> None:
    """同项目 tester 能使用工具，但只能读取本人业务资源。"""

    with database_factory() as database:
        owner = _user(database, "owner", "tester")
        peer = _user(database, "peer", "tester")
        manager = _user(database, "manager", "admin")
        platform_admin = _user(database, "root", "platform_admin")
        project = Project(id="prj-a", code="A", name="项目 A", status="active")
        database.add(project)
        database.flush()
        database.add_all(
            [
                ProjectMembership(project_id=project.id, user_id=owner.id, relation="member"),
                ProjectMembership(project_id=project.id, user_id=peer.id, relation="member"),
                ProjectMembership(project_id=project.id, user_id=manager.id, relation="manager"),
            ]
        )
        resource = BusinessResourceSnapshot(
            id="res-a",
            resource_type="task",
            resource_id="task-a",
            root_resource_id="task-a",
            tool_id="tool-a",
            environment_id="dev",
            owner_user_id=owner.id,
            project_id_snapshot=project.id,
            authorization_source_snapshot="project_member",
        )
        database.add(resource)
        database.flush()

        assert decide_resource_access(database, owner, resource).scope == "own"
        assert not decide_resource_access(database, peer, resource).allowed
        assert decide_resource_access(database, manager, resource).scope == "project"
        assert decide_resource_access(database, platform_admin, resource).scope == "global"


def test_resource_snapshot_identity_includes_environment(
    database_factory: sessionmaker[Session],
) -> None:
    """同一工具和根 ID 可在 dev/prod 独立存在，不能跨环境冲突或串线。"""

    with database_factory() as database:
        owner = _user(database, "env-owner", "tester")
        database.flush()
        for environment in ("dev", "prod"):
            database.add(BusinessResourceSnapshot(
                id=f"res-{environment}", environment_id=environment,
                resource_type="task", resource_id="same-task", root_resource_id="same-task",
                tool_id="env-tool", owner_user_id=owner.id,
                project_id_snapshot=None, authorization_source_snapshot="public",
            ))
        database.commit()
        rows = database.scalars(select(BusinessResourceSnapshot).where(BusinessResourceSnapshot.resource_id == "same-task")).all()
        assert {row.environment_id for row in rows} == {"dev", "prod"}


def test_public_tool_usage_enforces_request_task_and_cost_quota(
    database_factory: sessionmaker[Session],
) -> None:
    """公共策略必须被真实消费，不能只把合法 JSON 当作 complete。"""

    with database_factory() as database:
        user = _user(database, "quota-user", "tester")
        tool = _tool(database, "quota-tool", "public")
        tool.public_safety_policy.update({
            "request_quota_per_minute": 1,
            "task_quota_per_day": 2,
            "cost_quota_daily": 0.25,
            "cost_reservation_per_task": 0.25,
        })
        database.flush()
        consume_public_tool_usage(database, user, tool, kind="request")
        with pytest.raises(PlatformError) as request_error:
            consume_public_tool_usage(database, user, tool, kind="request")
        assert request_error.value.code == "PUBLIC_REQUEST_QUOTA_EXCEEDED"
        consume_public_tool_usage(database, user, tool, kind="task")
        with pytest.raises(PlatformError) as cost_error:
            consume_public_tool_usage(database, user, tool, kind="task")
        assert cost_error.value.code == "PUBLIC_COST_QUOTA_EXCEEDED"


def test_tool_catalog_batch_decision_has_constant_query_count(
    database_factory: sessionmaker[Session],
) -> None:
    """目录授权查询数不能随工具数量线性增长。"""

    with database_factory() as database:
        tester = _user(database, "catalog-tester", "tester")
        project = Project(id="prj-catalog", code="CATALOG", name="目录项目", status="active")
        database.add(project)
        database.flush()
        database.add(ProjectMembership(
            project_id=project.id,
            user_id=tester.id,
            relation="member",
        ))
        tools = [
            _tool(database, f"catalog-tool-{index}", "project", project.id)
            for index in range(20)
        ]
        database.flush()
        statements: list[str] = []

        def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        engine = database.get_bind()
        event.listen(engine, "before_cursor_execute", record_statement)
        try:
            decisions = decide_tool_access_batch(database, tester, tools)
        finally:
            event.remove(engine, "before_cursor_execute", record_statement)
        assert all(decision.source == "project_member" for decision in decisions.values())
        assert len(statements) <= 3


def test_migration_manifest_blocks_unknown_owner_and_applies_verified_snapshot(
    database_factory: sessionmaker[Session], monkeypatch,
) -> None:
    """历史资源只有 owner 可验证时才允许写入不可变快照。"""

    monkeypatch.setattr(migrate_project_access, "SessionLocal", database_factory)
    with database_factory() as database:
        _user(database, "legacy-owner", "tester")
        database.add(Environment(id="dev", name="开发环境", is_active=True))
        database.add(Project(id="legacy-project", code="LEGACY-TEST", name="存量测试", status="active"))
        _tool(database, "legacy-tool", "public")
        database.commit()
    invalid = migrate_project_access.inspect_and_apply({
        "user_roles": {}, "tool_projects": {"legacy-tool": "legacy-project"},
        "memberships": [], "required_environments": ["dev"],
        "source_counts": {"dev:legacy-tool": 1, "dev:truthy-search": 0, "dev:api-autotest": 0, "dev:functional-test-agent": 0, "dev:api-test-agent": 0, "dev:log-filter": 0},
        "resources": [{
            "environment_id": "dev", "tool_id": "legacy-tool", "resource_type": "task", "resource_id": "old-1",
            "root_resource_id": "old-1", "owner_user_id": "missing-owner",
            "project_id_snapshot": None, "authorization_source_snapshot": "public",
        }],
    }, apply=True, required_environment="dev")
    assert invalid["blocker_count"] == 1
    valid = migrate_project_access.inspect_and_apply({
        "user_roles": {}, "tool_projects": {"legacy-tool": "legacy-project"},
        "memberships": [], "required_environments": ["dev"],
        "source_counts": {"dev:legacy-tool": 1, "dev:truthy-search": 0, "dev:api-autotest": 0, "dev:functional-test-agent": 0, "dev:api-test-agent": 0, "dev:log-filter": 0},
        "resources": [{
            "environment_id": "dev", "tool_id": "legacy-tool", "resource_type": "task", "resource_id": "old-1",
            "root_resource_id": "old-1", "owner_user_id": "legacy-owner",
            "project_id_snapshot": None, "authorization_source_snapshot": "public",
        }],
    }, apply=True, required_environment="dev")
    assert valid["blocker_count"] == 0 and valid["applied"] is True
    with database_factory() as database:
        snapshot = database.scalar(select(BusinessResourceSnapshot).where(BusinessResourceSnapshot.resource_id == "old-1"))
        assert snapshot is not None and snapshot.owner_user_id == "legacy-owner"
