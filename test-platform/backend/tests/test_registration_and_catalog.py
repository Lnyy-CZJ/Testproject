from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.identity import User
from app.models.tool import Tool


def test_registration_creates_active_tester_without_privilege_fields(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """自助注册固定创建 tester，并拒绝客户端夹带角色或项目。"""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "new.tester",
            "display_name": "新测试人员",
            "password": "Strong-password-123",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "tester"
    with database_factory() as database:
        user = database.scalar(select(User).where(User.username_normalized == "new.tester"))
        assert user is not None
        assert (user.platform_role, user.status) == ("tester", "active")

    rejected = client.post(
        "/api/v1/auth/register",
        json={
            "username": "attacker",
            "display_name": "攻击者",
            "password": "Strong-password-123",
            "platform_role": "platform_admin",
        },
    )
    assert rejected.status_code == 422


def test_catalog_returns_access_source_and_management_boundary(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """工具卡片必须展示访问来源，公共工具不能产生管理入口。"""

    with database_factory() as database:
        database.add(
            Tool(
                id="public-tool",
                name="公共工具",
                description="test",
                entry_url="/public-tool/",
                health_url="http://public-tool/health",
                short_code="PUBLIC",
                icon_key="test",
                category="test",
                features=[],
                access_scope="public",
                project_id=None,
                public_safety_policy_status="complete",
                public_safety_policy={
                    "request_quota_per_minute": 10,
                    "task_quota_per_day": 20,
                    "cost_quota_daily": 5,
                    "cost_reservation_per_task": 0.25,
                    "real_execution_enabled": False,
                    "target_allowlist": ["example.test"],
                },
            )
        )
        database.commit()

    # 测试客户端的兼容用户先切换到新 tester 模型，目录必须走新授权内核。
    client.get("/api/v1/auth/me")
    with database_factory() as database:
        user = database.get(User, "test-user")
        user.platform_role = "tester"
        database.commit()

    response = client.get("/api/v1/tools")
    assert response.status_code == 200
    item = next(row for row in response.json()["items"] if row["id"] == "public-tool")
    assert item["access_source"] == "public"
    assert item["can_manage"] is False
