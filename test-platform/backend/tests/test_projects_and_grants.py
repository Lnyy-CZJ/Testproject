from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import AuthContext, current_auth_context, require_csrf
from app.main import app
from app.models.access import Project, ProjectMembership
from app.models.identity import PlatformSession, Role, User, UserRole
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


def _auth_override(database_factory: sessionmaker[Session], user_id: str = "test-user"):
    """返回指定固定角色用户的认证上下文，权限仍由真实授权内核判断。"""

    def override() -> AuthContext:
        with database_factory() as database:
            user = database.get(User, user_id)
            now = datetime.now(UTC)
            session = PlatformSession(
                id=f"test-session-{user_id}",
                token_hash="unused",
                csrf_hash="unused",
                user_id=user.id,
                idle_expires_at=now + timedelta(hours=1),
                absolute_expires_at=now + timedelta(hours=2),
                last_seen_at=now,
            )
            return AuthContext(session=session, user=user)

    return override


def _csrf_override(database_factory: sessionmaker[Session]):
    """兼容既有测试，默认以平台管理员通过 CSRF 校验。"""

    return _auth_override(database_factory)


def _user(*, user_id: str, username: str, role: str, status: str = "active") -> User:
    """构造成员链路测试用户，用户名规范化与生产写入规则保持一致。"""

    return User(
        id=user_id,
        username=username,
        username_normalized=username.lower(),
        display_name=username,
        password_hash="unused",
        status=status,
        platform_role=role,
    )


def test_create_user_sets_fixed_role_before_contract_insert(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """0020 收紧角色非空后，创建用户必须在第一次 flush 前写入固定角色。

    内存 SQLite 测试库由 ORM 元数据创建，无法自然复现已经执行过 0020 的
    PostgreSQL ``NOT NULL`` 约束。这里用 ``before_flush`` 监听器模拟合同约束，
    避免测试再次出现“SQLite 通过、真实数据库插入 503”的方言缺口。
    """

    with database_factory() as database:
        _platform_admin(database)

    def enforce_contract_role(session: Session, _flush_context, _instances) -> None:
        for pending in session.new:
            if (
                isinstance(pending, User)
                and pending.username_normalized == "contract-admin"
                and pending.platform_role is None
            ):
                raise AssertionError("固定角色必须在用户首次 flush 前写入")

    event.listen(Session, "before_flush", enforce_contract_role)
    app.dependency_overrides[require_csrf] = _csrf_override(database_factory)
    try:
        response = client.post(
            "/api/v1/admin/users",
            json={
                "username": "contract-admin",
                "display_name": "合同约束管理员",
                "password": "Strong-pass-123",
                "role": "admin",
            },
        )
        assert response.status_code == 201
        assert response.json()["role"] == "admin"
    finally:
        app.dependency_overrides.pop(require_csrf, None)
        event.remove(Session, "before_flush", enforce_contract_role)


def test_create_user_rejects_legacy_role_ids_without_fixed_role(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """新权限模型只接受一个固定角色，旧 ``role_ids`` 不能再创建空角色用户。"""

    with database_factory() as database:
        _platform_admin(database)
    app.dependency_overrides[require_csrf] = _csrf_override(database_factory)
    try:
        response = client.post(
            "/api/v1/admin/users",
            json={
                "username": "legacy-role-user",
                "display_name": "旧角色请求",
                "password": "Strong-pass-123",
                "role_ids": [],
            },
        )
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        with database_factory() as database:
            assert database.scalar(
                select(User).where(User.username_normalized == "legacy-role-user")
            ) is None
    finally:
        app.dependency_overrides.pop(require_csrf, None)


def test_create_user_rejects_legacy_role_ids_with_fixed_role(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """固定角色请求也不能夹带旧角色关系，避免审计记录与真实授权分叉。"""

    with database_factory() as database:
        _platform_admin(database)
    app.dependency_overrides[require_csrf] = _csrf_override(database_factory)
    try:
        response = client.post(
            "/api/v1/admin/users",
            json={
                "username": "mixed-role-user",
                "display_name": "混合角色请求",
                "password": "Strong-pass-123",
                "role": "tester",
                "role_ids": ["role_platform_admin"],
            },
        )
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        with database_factory() as database:
            assert database.scalar(
                select(User).where(User.username_normalized == "mixed-role-user")
            ) is None
    finally:
        app.dependency_overrides.pop(require_csrf, None)


def test_update_user_rejects_legacy_role_ids_and_preserves_relationships(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """旧 RBAC 只读兼容，PATCH 不能再改写 UserRole 形成第二授权源。"""

    with database_factory() as database:
        _platform_admin(database)
        database.add_all([
            Role(id="legacy-role-a", name="旧角色 A"),
            Role(id="legacy-role-b", name="旧角色 B"),
            _user(user_id="legacy-target", username="legacy.target", role="tester"),
        ])
        database.flush()
        database.add(UserRole(
            user_id="legacy-target",
            role_id="legacy-role-a",
            created_by="test-user",
        ))
        database.commit()
    app.dependency_overrides[require_csrf] = _csrf_override(database_factory)
    try:
        response = client.patch(
            "/api/v1/admin/users/legacy-target",
            json={"role_ids": ["legacy-role-b"]},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        with database_factory() as database:
            role_ids = set(database.scalars(
                select(UserRole.role_id).where(UserRole.user_id == "legacy-target")
            ).all())
            assert role_ids == {"legacy-role-a"}
            assert database.get(User, "legacy-target").platform_role == "tester"
    finally:
        app.dependency_overrides.pop(require_csrf, None)


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
                "password": "Strong-pass-123",
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


def test_platform_admin_can_add_active_admin_as_project_manager(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """平台管理员可通过完整用户名添加 active admin，并递增权限版本。"""

    with database_factory() as database:
        _platform_admin(database)
        database.add(Project(id="prj-manager", code="MANAGER", name="负责人项目"))
        database.add(_user(user_id="admin-one", username="Admin.One", role="admin"))
        database.commit()
    app.dependency_overrides[require_csrf] = _csrf_override(database_factory)
    try:
        response = client.post(
            "/api/v1/projects/prj-manager/managers",
            json={"username": "Admin.One", "reason": "负责项目"},
        )
        assert response.status_code == 201
        assert response.json()["relation"] == "manager"
        with database_factory() as database:
            assert database.get(ProjectMembership, ("prj-manager", "admin-one")).relation == "manager"
            assert database.get(User, "admin-one").permission_version == 2
    finally:
        app.dependency_overrides.pop(require_csrf, None)


def test_project_admin_can_add_active_tester_as_member(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """普通管理员只能在自己负责的项目中精确添加 active tester。"""

    with database_factory() as database:
        _platform_admin(database)
        database.add(Project(id="prj-member", code="MEMBER", name="成员项目"))
        database.add_all([
            _user(user_id="admin-owner", username="admin.owner", role="admin"),
            _user(user_id="tester-one", username="tester.one", role="tester"),
        ])
        database.flush()
        database.add(ProjectMembership(
            project_id="prj-member",
            user_id="admin-owner",
            relation="manager",
            created_by_user_id="test-user",
        ))
        database.commit()
    admin_auth = _auth_override(database_factory, "admin-owner")
    app.dependency_overrides[current_auth_context] = admin_auth
    app.dependency_overrides[require_csrf] = admin_auth
    try:
        response = client.post(
            "/api/v1/projects/prj-member/members",
            json={"username": "tester.one", "reason": "执行项目测试"},
        )
        assert response.status_code == 201
        assert response.json()["relation"] == "member"
        with database_factory() as database:
            assert database.get(ProjectMembership, ("prj-member", "tester-one")).relation == "member"
            assert database.get(User, "tester-one").permission_version == 2
    finally:
        app.dependency_overrides.pop(current_auth_context, None)
        app.dependency_overrides.pop(require_csrf, None)


def test_project_relations_reject_disabled_target_users(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """disabled admin/tester 不得通过负责人或成员入口重新获得项目关系。"""

    with database_factory() as database:
        _platform_admin(database)
        database.add(Project(id="prj-disabled", code="DISABLED", name="禁用账号项目"))
        database.add_all([
            _user(user_id="active-admin", username="active.admin", role="admin"),
            _user(user_id="disabled-admin", username="disabled.admin", role="admin", status="disabled"),
            _user(user_id="disabled-tester", username="disabled.tester", role="tester", status="disabled"),
        ])
        database.flush()
        database.add(ProjectMembership(
            project_id="prj-disabled",
            user_id="active-admin",
            relation="manager",
            created_by_user_id="test-user",
        ))
        database.commit()
    app.dependency_overrides[require_csrf] = _csrf_override(database_factory)
    try:
        manager = client.post(
            "/api/v1/projects/prj-disabled/managers",
            json={"username": "disabled.admin", "reason": "不应成功"},
        )
        # 成员入口改用真实普通管理员上下文，覆盖其项目范围内的拒绝路径。
        admin_auth = _auth_override(database_factory, "active-admin")
        app.dependency_overrides[current_auth_context] = admin_auth
        app.dependency_overrides[require_csrf] = admin_auth
        member = client.post(
            "/api/v1/projects/prj-disabled/members",
            json={"username": "disabled.tester", "reason": "不应成功"},
        )
        assert manager.status_code == 404
        assert manager.json()["code"] == "NOT_FOUND"
        assert member.status_code == 404
        assert member.json()["code"] == "NOT_FOUND"
        with database_factory() as database:
            assert database.get(ProjectMembership, ("prj-disabled", "disabled-admin")) is None
            assert database.get(ProjectMembership, ("prj-disabled", "disabled-tester")) is None
    finally:
        app.dependency_overrides.pop(current_auth_context, None)
        app.dependency_overrides.pop(require_csrf, None)


def test_role_change_rejects_existing_incompatible_project_relation(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """角色修改不能留下授权内核无法识别的 admin/member 或 tester/manager 关系。"""

    with database_factory() as database:
        _platform_admin(database)
        database.add_all([
            Project(id="prj-role-member", code="ROLE-MEMBER", name="成员角色项目"),
            Project(id="prj-role-manager", code="ROLE-MANAGER", name="负责人角色项目"),
            _user(user_id="member-user", username="member.user", role="tester"),
            _user(user_id="manager-user", username="manager.user", role="admin"),
        ])
        database.flush()
        database.add_all([
            ProjectMembership(
                project_id="prj-role-member",
                user_id="member-user",
                relation="member",
                created_by_user_id="test-user",
            ),
            ProjectMembership(
                project_id="prj-role-manager",
                user_id="manager-user",
                relation="manager",
                created_by_user_id="test-user",
            ),
        ])
        database.commit()
    app.dependency_overrides[require_csrf] = _csrf_override(database_factory)
    try:
        member_to_admin = client.patch(
            "/api/v1/admin/users/member-user",
            json={"role": "admin"},
        )
        manager_to_tester = client.patch(
            "/api/v1/admin/users/manager-user",
            json={"role": "tester"},
        )
        assert member_to_admin.status_code == 409
        assert member_to_admin.json()["code"] == "PROJECT_RELATION_ROLE_CONFLICT"
        assert manager_to_tester.status_code == 409
        assert manager_to_tester.json()["code"] == "PROJECT_RELATION_ROLE_CONFLICT"
        with database_factory() as database:
            assert database.get(User, "member-user").platform_role == "tester"
            assert database.get(User, "manager-user").platform_role == "admin"
    finally:
        app.dependency_overrides.pop(require_csrf, None)
