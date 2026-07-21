"""
第六阶段双跑验证与上线加固契约测试

测试目标:
    - 确认上线门禁 API 已注册。
    - 确认 Go/Python 双跑比较工具能识别兼容和不兼容响应。
    - 确认生产配置预检能阻断默认弱密钥。
    - 确认 Dockerfile 使用多阶段构建并启用非 root 用户。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from scripts.dual_run_compare import compare_response_pair
from scripts.preflight_check import run_preflight_checks


@pytest.fixture
async def client():
    """创建 FastAPI 测试客户端"""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.mark.anyio
async def test_phase6_ops_routes_registered_in_openapi(client: AsyncClient):
    """
    验证第六阶段运维门禁路由已进入 OpenAPI。

    功能说明:
        第六阶段需要提供上线预检、双跑比较和回滚计划查询入口，
        便于灰度上线前自动化检查。
    """
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]

    for path in [
        "/api/v1/ops/preflight",
        "/api/v1/ops/dual-run/compare",
        "/api/v1/ops/rollback-plan",
    ]:
        assert path in paths


@pytest.mark.anyio
async def test_ops_preflight_requires_login_with_api_result_format(client: AsyncClient):
    """验证未登录访问上线预检时返回统一 ApiResult 错误格式"""
    response = await client.get("/api/v1/ops/preflight")

    assert response.status_code == 401
    assert response.json() == {"code": 401, "data": None, "message": "登录已过期"}


def test_dual_run_compare_ignores_volatile_fields_and_detects_mismatch():
    """验证双跑比较忽略时间类易变字段，同时能发现真实响应差异"""
    go_response = {
        "code": 0,
        "data": {"id": 1, "name": "demo", "createdAt": "2026-01-01T00:00:00"},
        "message": "success",
    }
    py_response = {
        "code": 0,
        "data": {"id": 1, "name": "demo", "createdAt": "2026-01-02T00:00:00"},
        "message": "success",
    }
    compatible = compare_response_pair(go_response, py_response)
    assert compatible.compatible is True
    assert compatible.differences == []

    py_response["data"]["name"] = "changed"
    incompatible = compare_response_pair(go_response, py_response)
    assert incompatible.compatible is False
    assert "data.name" in incompatible.differences[0]


def test_preflight_rejects_default_production_secrets():
    """验证生产配置预检会阻断默认弱密钥"""
    report = run_preflight_checks(
        {
            "BUG_AGENT_SERVER_MODE": "production",
            "BUG_AGENT_JWT_SECRET": "bug-agent-secret-key-change-in-production",
            "BUG_AGENT_DATABASE_PASSWORD": "postgres",
            "BUG_AGENT_SECRETS_CREDENTIAL_ENCRYPT_KEY": "0123456789abcdef0123456789abcdef",
        }
    )

    assert report.passed is False
    failed_keys = {item.key for item in report.checks if not item.passed}
    assert "jwt_secret" in failed_keys
    assert "database_password" in failed_keys
    assert "credential_encrypt_key" in failed_keys


def test_dockerfile_is_multi_stage_and_non_root():
    """验证 Dockerfile 满足多阶段构建和非 root 运行要求"""
    dockerfile = Path("Dockerfile")
    assert dockerfile.exists()
    content = dockerfile.read_text(encoding="utf-8")

    assert " AS builder" in content
    assert " AS runtime" in content
    assert "USER bugagent" in content
