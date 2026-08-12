from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.api.deps import AuthContext, current_auth_context
from app.main import app
from app.models.identity import Permission, PlatformSession, Role, RoleGrant, User, UserRole


@pytest.fixture
def database_factory() -> Generator[sessionmaker[Session], None, None]:
    """
    创建每个测试独享的内存数据库。

    返回值:
        sessionmaker[Session]: 可创建同步测试会话的工厂。
    """

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(database_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    """
    创建已替换数据库依赖的 FastAPI 测试客户端。

    参数说明:
        database_factory: 当前测试的会话工厂。
    返回值:
        TestClient: 只连接内存数据库的同步测试客户端。
    """

    def override_database() -> Generator[Session, None, None]:
        database = database_factory()
        try:
            yield database
        finally:
            database.close()

    def override_authentication() -> AuthContext:
        """为原有工具 API 测试提供已认证管理员上下文。"""

        with database_factory() as database:
            user = database.get(User, "test-user")
            if user is None:
                user = User(
                    id="test-user", username="tester", username_normalized="tester",
                    display_name="测试管理员", password_hash="unused", status="active",
                )
                database.add(user)
                database.add_all([
                    Permission(code="tool.view", name="查看工具", resource_type="tool"),
                    Role(id="test-role", name="测试角色"),
                ])
                database.flush()
                database.add_all([
                    UserRole(user_id=user.id, role_id="test-role"),
                    RoleGrant(
                        role_id="test-role", permission_code="tool.view",
                        resource_type="tool", resource_id="*",
                    ),
                ])
                database.commit()
            now = datetime.now(UTC)
            session = PlatformSession(
                id="test-session", token_hash="unused", csrf_hash="unused",
                user_id=user.id, idle_expires_at=now + timedelta(hours=8),
                absolute_expires_at=now + timedelta(hours=24), last_seen_at=now,
            )
            return AuthContext(session=session, user=user)

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[current_auth_context] = override_authentication
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
