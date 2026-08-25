from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import AuthContext, require_csrf
from app.main import app
from app.models.access import Project
from app.models.identity import PlatformSession, User
from app.models.tool import Tool


def _platform_admin(database: Session) -> User:
    """预置测试客户端会复用的固定角色平台管理员。"""

    user = User(
        id="test-user",
        username="root",
        username_normalized="root",
        display_name="平台管理员",
        password_hash="unused",
        status="active",
        platform_role="platform_admin",
    )
    database.add(user)
    database.commit()
    return user


def _csrf_override(database_factory: sessionmaker[Session]):
    """仅测试写接口授权边界，不绕过角色权限检查。"""

    def override() -> AuthContext:
        with database_factory() as database:
            user = database.get(User, "test-user")
            now = datetime.now(UTC)
            session = PlatformSession(
                id="test-session",
                token_hash="unused",
                csrf_hash="unused",
                user_id=user.id,
                idle_expires_at=now + timedelta(hours=1),
                absolute_expires_at=now + timedelta(hours=2),
                last_seen_at=now,
            )
            return AuthContext(session=session, user=user)

    return override


def test_platform_admin_can_create_and_list_project(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """项目 code 创建后稳定，并在管理列表中返回 revision。"""

    with database_factory() as database:
        _platform_admin(database)
    app.dependency_overrides[require_csrf] = _csrf_override(database_factory)
    try:
        response = client.post(
            "/api/v1/projects",
            json={"code": "PAY-QA", "name": "支付测试", "description": "支付链路", "reason": "创建测试项目"},
        )
        assert response.status_code == 201
        assert response.json()["code"] == "PAY-QA"
        assert response.json()["revision"] == 1

        listing = client.get("/api/v1/projects")
        assert listing.status_code == 200
        assert [row["code"] for row in listing.json()] == ["PAY-QA"]
    finally:
        app.dependency_overrides.pop(require_csrf, None)


def test_extra_grant_is_time_bounded_and_rejects_redundant_membership(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """项目继承已经存在时不能再创建冗余单工具授权。"""

    with database_factory() as database:
        _platform_admin(database)
    app.dependency_overrides[require_csrf] = _csrf_override(database_factory)
    try:
        project = client.post(
            "/api/v1/projects",
            json={"code": "TRUST", "name": "内容安全", "description": "", "reason": "创建测试项目"},
        ).json()
        # API 使用精确用户名添加 tester，不能返回全平台候选列表。
        create_user = client.post(
            "/api/v1/admin/users",
            json={
                "username": "tester.one",
                "display_name": "测试一",
                "password": "Strong-password-123",
                "role": "tester",
            },
        )
        assert create_user.status_code == 201
        user_id = create_user.json()["id"]
        added = client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"username": "tester.one", "reason": "加入项目测试"},
        )
        assert added.status_code == 201

        with database_factory() as database:
            database.add(
                Tool(
                    id="test-tool",
                    name="测试工具",
                    description="test",
                    entry_url="/test-tool/",
                    health_url="http://test-tool/health",
                    short_code="TEST",
                    icon_key="test",
                    category="test",
                    features=[],
                    access_scope="project",
                    project_id=project["id"],
                )
            )
            database.commit()
        grant = client.post(
            "/api/v1/admin/tool-grants",
            json={"user_id": user_id, "tool_id": "test-tool", "days": 7, "reason": "临时排障", "idempotency_key": "grant-test-001"},
        )
        assert grant.status_code == 409
        assert grant.json()["code"] == "REDUNDANT_GRANT"
    finally:
        app.dependency_overrides.pop(require_csrf, None)


def test_tool_scope_change_requires_fresh_impact_and_unknown_acknowledgement(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """工具范围变更必须绑定预览 revision，未知运行态需显式确认。"""

    with database_factory() as database:
        _platform_admin(database)
        project = Project(id="prj-impact", code="IMPACT", name="影响预览")
        database.add(project)
        database.add(Tool(
            id="log-filter",
            name="影响工具",
            description="test",
            entry_url="/log-filter/",
            health_url="http://log-filter/health",
            short_code="IMPACT",
            icon_key="test",
            category="test",
            features=[],
            access_scope="project",
            project_id=project.id,
            public_safety_policy_status="complete",
            public_safety_policy={
                "request_quota_per_minute": 10,
                "task_quota_per_day": 20,
                "cost_quota_daily": 5,
                "cost_reservation_per_task": 0.25,
                "real_execution_enabled": False,
                "target_allowlist": ["example.test"],
            },
        ))
        database.add(Tool(
            id="external-agent",
            name="外部执行工具",
            description="test",
            entry_url="/external-agent/",
            health_url="http://external-agent/health",
            short_code="EXT",
            icon_key="test",
            category="test",
            features=[],
            access_scope="project",
            project_id=project.id,
            public_safety_policy_status="complete",
            public_safety_policy={
                "request_quota_per_minute": 10,
                "task_quota_per_day": 20,
                "cost_quota_daily": 5,
                "cost_reservation_per_task": 0.25,
                "real_execution_enabled": False,
                "target_allowlist": ["example.test"],
            },
        ))
        database.commit()
    app.dependency_overrides[require_csrf] = _csrf_override(database_factory)
    try:
        unsupported = client.post(
            "/api/v1/admin/tool-access/external-agent/impact",
            json={"access_scope": "public", "project_id": None},
        )
        assert unsupported.status_code == 409
        assert unsupported.json()["code"] == "PUBLIC_SANDBOX_UNAVAILABLE"
        preview = client.post(
            "/api/v1/admin/tool-access/log-filter/impact",
            json={"access_scope": "public", "project_id": None},
        )
        assert preview.status_code == 200
        payload = {
            "access_scope": "public",
            "project_id": None,
            "revision": preview.json()["expected_revision"],
            "impact_token": preview.json()["impact_token"],
            "reason": "开放公共工具",
        }
        blocked = client.patch("/api/v1/admin/tool-access/log-filter", json=payload)
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "RUNNING_TASK_IMPACT_UNKNOWN"
        changed = client.patch(
            "/api/v1/admin/tool-access/log-filter",
            json={**payload, "force_unknown_impact": True},
        )
        assert changed.status_code == 200
        assert changed.json()["access_scope"] == "public"
    finally:
        app.dependency_overrides.pop(require_csrf, None)
