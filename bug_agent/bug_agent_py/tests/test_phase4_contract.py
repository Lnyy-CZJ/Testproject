"""
第四阶段修复任务与 PR 生命周期契约测试

测试目标:
    - 确认修复任务、人工修复、PR 生命周期 API 已注册。
    - 确认受保护接口延续 ApiResult 错误格式。
    - 确认 PR 拒绝/合并依赖的缺陷状态流转合法。
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
async def test_phase4_routes_registered_in_openapi(client: AsyncClient):
    """
    验证第四阶段路由已进入 OpenAPI。

    功能说明:
        第四阶段必须暴露修复任务、人工修复和 PR 生命周期入口。
    """
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    expected_paths = [
        "/api/v1/defects/{id}/fix-tasks",
        "/api/v1/defects/{id}/fix-task-groups",
        "/api/v1/fix-tasks/{task_id}",
        "/api/v1/defects/{id}/manual-fix/start",
        "/api/v1/defects/{id}/manual-fix/complete",
        "/api/v1/defects/{id}/manual-fix/abandon",
        "/api/v1/defects/{id}/fix-tasks/{task_id}/pr",
        "/api/v1/defects/{id}/fix-tasks/{task_id}/rejections",
        "/api/v1/defects/{id}/fix-tasks/{task_id}/reject",
        "/api/v1/defects/{id}/fix-tasks/{task_id}/merge",
    ]
    for path in expected_paths:
        assert path in paths


@pytest.mark.anyio
async def test_fix_task_list_requires_login_with_api_result_format(client: AsyncClient):
    """验证未登录访问修复任务列表时返回统一 ApiResult 错误格式"""
    response = await client.get("/api/v1/defects/1/fix-tasks")

    assert response.status_code == 401
    assert response.json() == {"code": 401, "data": None, "message": "登录已过期"}


def test_pr_lifecycle_transition_rules_are_allowed():
    """验证 PR 生命周期需要的状态流转合法"""
    assert WorkflowService.is_valid_transition("pending_fix", "manual_fixing") is True
    assert WorkflowService.is_valid_transition("pending_fix", "fixing") is True
    assert WorkflowService.is_valid_transition("manual_fixing", "pending_verify") is True
    assert WorkflowService.is_valid_transition("pending_verify", "pending_fix") is True
    assert WorkflowService.is_valid_transition("pending_verify", "fixed") is True
