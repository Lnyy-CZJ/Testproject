"""
阶段零冒烟测试

验证:
    - FastAPI 应用可正常导入
    - /healthz 返回 200
    - /docs 可访问
    - Pydantic Schema camelCase 序列化正确
    - 所有 ORM 模型注册成功（50 张表）
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client():
    """创建测试客户端"""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_healthz_returns_ok(client: AsyncClient):
    """验证 /healthz 存活检查端点"""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_docs_accessible(client: AsyncClient):
    """验证 /docs Swagger 文档页可访问"""
    response = await client.get("/docs")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_openapi_schema_accessible(client: AsyncClient):
    """验证 OpenAPI Schema 端点可访问"""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "BugAgent API"


def test_all_models_registered():
    """验证 50 张 ORM 表全部注册"""
    from app.models.base import Base
    tables = set(Base.metadata.tables.keys())
    assert "users" in tables
    assert "defects" in tables
    assert "projects" in tables
    assert "fix_tasks" in tables
    assert "analysis_reports" in tables
    assert "issue_clusters" in tables
    assert "agent_memories" in tables
    assert len(tables) == 50, f"期望50张表，实际{len(tables)}张: {sorted(tables)}"


def test_camelcase_serialization():
    """验证 DefectListItem 序列化为 camelCase"""
    from datetime import datetime
    from app.schemas.defect import DefectListItem

    d = DefectListItem(
        id=1, code="BUG-001", title="测试",
        severity="严重", priority="P1", type="功能缺陷",
        status="new", reporter_id=1, iteration_id=1,
        created_at=datetime(2026, 6, 6, 12, 0, 0),
        updated_at=datetime(2026, 6, 6, 12, 0, 0),
    )
    data = d.model_dump(mode="json")
    assert "createdAt" in data
    assert "iterationId" in data
    assert "reporterId" in data
    assert "updatedAt" in data


def test_api_result_format():
    """验证 ApiResult 统一响应格式"""
    from app.schemas.common import ApiResult
    r = ApiResult(code=0, data={"id": 1})
    data = r.model_dump(mode="json")
    assert data["code"] == 0
    assert data["data"] == {"id": 1}


def test_jwt_token_roundtrip():
    """验证 JWT Token 生成与解析"""
    from app.infrastructure.security import create_access_token, decode_access_token

    token = create_access_token(user_id=1, username="admin")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "1"
    assert payload["username"] == "admin"


def test_password_hash():
    """验证 bcrypt 密码哈希"""
    from app.infrastructure.security import hash_password, verify_password

    hashed = hash_password("test123")
    assert verify_password("test123", hashed)
    assert not verify_password("wrong", hashed)


def test_aes_encrypt_decrypt():
    """验证 AES-256-GCM 加解密"""
    from app.infrastructure.security import aes_encrypt, aes_decrypt

    key = "0123456789abcdef0123456789abcdef"
    original = "sk-test-api-key-12345"
    encrypted = aes_encrypt(original, key)
    decrypted = aes_decrypt(encrypted, key)
    assert decrypted == original
    assert encrypted != original


def test_mask_key():
    """验证 API Key 脱敏"""
    from app.infrastructure.security import mask_key

    assert mask_key("sk-1234567890abcdef") == "sk-1****cdef"
    assert mask_key("short") == "shor****"