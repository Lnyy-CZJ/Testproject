"""
测试基础设施

提供 pytest fixtures:
    - async_client: FastAPI 异步测试客户端
    - test_db: 测试数据库会话
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def async_client() -> AsyncClient:
    """创建 FastAPI 异步测试客户端"""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await transport.aclose()


@pytest.fixture
async def app():
    """返回 FastAPI 应用实例"""
    return create_app()