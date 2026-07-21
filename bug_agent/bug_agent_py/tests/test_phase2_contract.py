"""
第二阶段缺陷域契约测试

测试目标:
    - 确认缺陷、评论、附件、工作流相关 API 已注册到 OpenAPI。
    - 确认受保护缺陷接口延续 ApiResult 错误格式。
    - 确认缺陷状态机核心流转规则与 PRD 保持一致。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.services.workflow_service import WorkflowService


@pytest.fixture
async def client():
    """创建 FastAPI 测试客户端"""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.mark.anyio
async def test_phase2_routes_registered_in_openapi(client: AsyncClient):
    """
    验证第二阶段路由已进入 OpenAPI。

    功能说明:
        第二阶段必须暴露缺陷 CRUD、状态机、评论、附件、
        项目内对话建单和批量工作流入口。
    """
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    expected_paths = [
        "/api/v1/defects",
        "/api/v1/defects/{id}",
        "/api/v1/defects/{id}/assign",
        "/api/v1/defects/{id}/status",
        "/api/v1/defects/{id}/transition",
        "/api/v1/defects/{id}/transitions",
        "/api/v1/defects/{id}/history",
        "/api/v1/defects/{id}/comments",
        "/api/v1/defects/{id}/attachments",
        "/api/v1/defects/{id}/attachments/{attachment_id}",
        "/api/v1/projects/{id}/defects/draft-from-chat",
        "/api/v1/projects/{id}/defects/confirm-create",
        "/api/v1/workflow/batch",
        "/api/v1/uploads/{filename}",
    ]
    for path in expected_paths:
        assert path in paths


@pytest.mark.anyio
async def test_defect_list_requires_login_with_api_result_format(client: AsyncClient):
    """验证未登录访问缺陷列表时返回统一 ApiResult 错误格式"""
    response = await client.get("/api/v1/defects")

    assert response.status_code == 401
    assert response.json() == {"code": 401, "data": None, "message": "登录已过期"}


def test_workflow_transition_matrix_keeps_prd_rules():
    """验证核心状态机规则：允许合法流转，拒绝跳跃式非法流转"""
    assert WorkflowService.is_valid_transition("new", "pending_assign") is True
    assert WorkflowService.is_valid_transition("pending_verify", "fixed") is True
    assert WorkflowService.is_valid_transition("fixed", "completed") is True
    assert WorkflowService.is_valid_transition("analyzing", "pending_analysis") is True
    assert WorkflowService.is_valid_transition("new", "fixed") is False
    assert WorkflowService.is_valid_transition("new", "unknown") is False

    assert WorkflowService.valid_transitions("pending_verify") == ["fixed", "pending_fix"]
