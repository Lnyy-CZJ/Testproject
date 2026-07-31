from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app


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

    app.dependency_overrides[get_db] = override_database
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
