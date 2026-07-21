"""
第一阶段账号与项目域契约测试

测试目标:
    - 确认第一阶段 API 已注册到 OpenAPI
    - 确认未登录错误使用 ApiResult 兼容格式
    - 确认分页响应同时兼容 items 和 list 字段
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.schemas.common import PaginatedResponse


@pytest.fixture
async def client():
    """创建 FastAPI 测试客户端"""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.mark.anyio
async def test_phase1_routes_registered_in_openapi(client: AsyncClient):
    """
    验证第一阶段路由已进入 OpenAPI。

    功能说明:
        第零阶段只注册骨架；第一阶段必须至少暴露账号、项目、
        迭代、仓库、AI 配置相关路径。
    """
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    expected_paths = [
        "/api/v1/auth/login",
        "/api/v1/users/me",
        "/api/v1/users/{user_id}/reset-password",
        "/api/v1/projects",
        "/api/v1/user/projects",
        "/api/v1/projects/{id}/iterations",
        "/api/v1/projects/{id}/repos",
        "/api/v1/projects/{id}/ai-configs",
        "/api/v1/ai/providers",
    ]
    for path in expected_paths:
        assert path in paths


@pytest.mark.anyio
async def test_unauthorized_response_uses_api_result_format(client: AsyncClient):
    """验证未登录访问受保护接口时返回 Go 版兼容错误格式"""
    response = await client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.json() == {"code": 401, "data": None, "message": "登录已过期"}


def test_paginated_response_keeps_items_and_list_fields():
    """验证分页响应同时兼容前端 items 和 PRD list 字段"""
    page = PaginatedResponse.from_items(items=[{"id": 1}], total=1, page=1, size=20)
    data = page.model_dump(mode="json", by_alias=True)

    assert data["items"] == [{"id": 1}]
    assert data["list"] == [{"id": 1}]
    assert data["pageSize"] == 20
    assert data["size"] == 20
