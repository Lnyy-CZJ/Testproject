"""
第五阶段信号接入、检索与质量洞察契约测试

测试目标:
    - 确认问题池、集成连接器、检索器、质量洞察 API 已注册。
    - 确认受保护接口延续 ApiResult 错误格式。
    - 确认入站连接器 token 无效时返回可识别错误。
    - 确认关键词检索器基础排序行为稳定。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.retrieval.keyword import KeywordRetriever


@pytest.fixture
async def client():
    """创建 FastAPI 测试客户端"""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.mark.anyio
async def test_phase5_routes_registered_in_openapi(client: AsyncClient):
    """
    验证第五阶段路由已进入 OpenAPI。

    功能说明:
        第五阶段必须暴露信号接入、问题池、连接器、检索器和质量洞察入口。
    """
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    expected_paths = [
        "/api/v1/inbound/connectors/{token}",
        "/api/v1/projects/{id}/issue-clusters",
        "/api/v1/projects/{id}/issue-clusters/{clusterId}",
        "/api/v1/projects/{id}/issue-clusters/{clusterId}/signals",
        "/api/v1/projects/{id}/issue-clusters/{clusterId}/assign",
        "/api/v1/projects/{id}/issue-clusters/{clusterId}/ignore",
        "/api/v1/projects/{id}/issue-clusters/{clusterId}/merge",
        "/api/v1/projects/{id}/issue-clusters/{clusterId}/convert",
        "/api/v1/projects/{id}/issue-clusters/auto-triage",
        "/api/v1/projects/{id}/integrations",
        "/api/v1/projects/{id}/integrations/{connectorId}",
        "/api/v1/projects/{id}/integrations/{connectorId}/test",
        "/api/v1/projects/{id}/integrations/{connectorId}/sync",
        "/api/v1/projects/{id}/retriever-plugins",
        "/api/v1/projects/{id}/retriever-plugins/{pluginId}",
        "/api/v1/projects/{id}/retriever-plugins/{pluginId}/toggle",
        "/api/v1/projects/{id}/retriever-plugins/sort",
        "/api/v1/projects/{id}/retriever-plugins/{pluginId}/test",
        "/api/v1/projects/{id}/quality-insights/overview",
    ]
    for path in expected_paths:
        assert path in paths


@pytest.mark.anyio
async def test_issue_clusters_requires_login_with_api_result_format(client: AsyncClient):
    """验证未登录访问问题池时返回统一 ApiResult 错误格式"""
    response = await client.get("/api/v1/projects/1/issue-clusters")

    assert response.status_code == 401
    assert response.json() == {"code": 401, "data": None, "message": "登录已过期"}


@pytest.mark.anyio
async def test_inbound_connector_invalid_token_uses_api_result_format(client: AsyncClient):
    """验证无效连接器 token 返回统一错误格式"""
    response = await client.post("/api/v1/inbound/connectors/not-found", json={"title": "crash"})

    assert response.status_code == 404
    assert response.json() == {"code": 404, "data": None, "message": "连接器不存在"}


def test_keyword_retriever_scores_path_and_content_matches():
    """验证关键词检索器按路径和内容命中排序"""
    docs = [
        {"filePath": "src/auth/login.py", "content": "def submit_form(): pass"},
        {"filePath": "src/ui/button.py", "content": "login button submit"},
        {"filePath": "README.md", "content": "project overview"},
    ]

    result = KeywordRetriever(docs).retrieve(text="login submit", keywords=["auth"], top_k=2)

    assert [item.filePath for item in result] == ["src/auth/login.py", "src/ui/button.py"]
    assert result[0].score > result[1].score
