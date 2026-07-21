"""
第三阶段 Agent 分析、SSE、Token、记忆契约测试

测试目标:
    - 确认第三阶段 API 已注册到 OpenAPI。
    - 确认受保护 Agent 接口延续 ApiResult 错误格式。
    - 确认确定性分析器输出稳定结构，便于后续替换真实 LLM 后保留契约。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.analysis_engine import DeterministicAnalysisEngine
from app.main import create_app


@pytest.fixture
async def client():
    """创建 FastAPI 测试客户端"""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.mark.anyio
async def test_phase3_routes_registered_in_openapi(client: AsyncClient):
    """
    验证第三阶段路由已进入 OpenAPI。

    功能说明:
        第三阶段必须暴露 Agent 分析、SSE、Token 统计和 Agent 记忆入口。
    """
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    expected_paths = [
        "/api/v1/agents/analyze",
        "/api/v1/agents/analyze/stream",
        "/api/v1/agents/reports/{report_id}",
        "/api/v1/agents/analyze/{id}/cancel",
        "/api/v1/agents/analyze/queue",
        "/api/v1/agents/analyze/{id}/history",
        "/api/v1/defects/{id}/reports",
        "/api/v1/sse",
        "/api/v1/defects/{id}/token-usage",
        "/api/v1/defects/{id}/token-usage/details",
        "/api/v1/projects/{id}/token-usage",
        "/api/v1/projects/{id}/token-usage/by-iteration",
        "/api/v1/projects/{id}/token-usage/by-defect",
        "/api/v1/projects/{id}/memories",
        "/api/v1/projects/{id}/iterations/{iteration_id}/memories",
        "/api/v1/projects/{id}/memories/{memory_id}",
        "/api/v1/projects/{id}/memories/{memory_id}/toggle",
    ]
    for path in expected_paths:
        assert path in paths


@pytest.mark.anyio
async def test_agent_analyze_requires_login_with_api_result_format(client: AsyncClient):
    """验证未登录触发分析时返回统一 ApiResult 错误格式"""
    response = await client.post("/api/v1/agents/analyze", json={"defectId": 1})

    assert response.status_code == 401
    assert response.json() == {"code": 401, "data": None, "message": "登录已过期"}


def test_deterministic_analysis_engine_outputs_stable_report():
    """
    验证确定性分析器输出稳定。

    功能说明:
        第三阶段先用规则化分析器冻结报告 schema，后续真实 LLM 接入时
        仍需保持 analysis/solution/token_usage 三段结构。
    """
    report = DeterministicAnalysisEngine().analyze(
        title="登录按钮点击后无响应",
        description="用户在 Chrome 中点击登录按钮，没有任何请求发出。",
        agent_type="analysis_frontend",
        memory_context="项目约定: 表单提交必须带 loading 状态。",
    )

    assert report.analysis["rootCause"] == "需要结合日志、复现步骤和相关代码进一步定位"
    assert report.analysis["riskLevel"] == "medium"
    assert report.solution["description"] == "建议先补充复现信息，再按影响范围分层排查"
    assert report.token_usage.total_tokens > 0
    assert report.memory_items_used == 1
