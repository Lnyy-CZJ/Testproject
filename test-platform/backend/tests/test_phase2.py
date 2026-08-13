from __future__ import annotations

import base64
import json
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.permissions import required_tool_permission
from app.core.security import SecretCipher, hash_password, token_hash, verify_password
from app.api.internal import _parse_credential_expiry
from app.jobs import credential_agent
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.configuration import ConfigDefinition, Credential, CredentialItem, Environment, SecretVersion
from app.models.identity import Permission, Role, RoleGrant, ToolClient
from app.models.tool import Tool


@pytest.fixture
def phase2_client(tmp_path: Path) -> Generator[tuple[TestClient, sessionmaker[Session], Settings], None, None]:
    """创建包含第二阶段种子的隔离 API 客户端。"""

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    kek_path = tmp_path / "kek.json"
    kek_path.write_text(json.dumps({
        "active": "v1",
        "keys": {"v1": base64.b64encode(b"k" * 32).decode("ascii")},
    }), encoding="utf-8")
    settings = Settings(
        database_url="sqlite://", bootstrap_token="bootstrap-token-for-tests",
        secret_kek_file=str(kek_path), session_touch_interval_seconds=9999,
    )
    with factory() as database:
        database.add_all([
            Environment(id="dev", name="开发环境", is_active=True, sort_order=10),
            Tool(
                id="truthy-search", name="检索评测", description="", entry_url="/truthy-search/",
                health_url="http://truthy/health", short_code="SEARCH", icon_key="search",
                category="evaluation", features=[], sort_order=10, is_enabled=True,
            ),
            Tool(
                id="log-filter", name="日志分析", description="", entry_url="/log-filter/",
                health_url="http://log/health", short_code="LOG", icon_key="log",
                category="analysis", features=[], sort_order=20, is_enabled=True,
            ),
            Role(id="role_platform_admin", name="平台管理员", is_builtin=True),
        ])
        permissions = [
            ("platform.secret.manage", "platform"),
            ("platform.audit.view", "platform"),
            ("platform.user.manage", "platform"),
            ("platform.role.manage", "platform"),
            ("tool.view", "tool"),
            ("tool.secret.manage", "tool"),
        ]
        for code, resource_type in permissions:
            database.add(Permission(code=code, name=code, resource_type=resource_type))
            database.add(RoleGrant(
                role_id="role_platform_admin", permission_code=code,
                resource_type=resource_type, resource_id="*", created_by="test",
            ))
        database.add(ConfigDefinition(
            id="truthy-search.AUTH_TOKEN", key="AUTH_TOKEN", display_name="Access Token",
            description="", owner_type="tool", owner_id="truthy-search", group_key="credentials",
            value_type="secret", sensitivity="secret", required=True,
            validation_schema={}, apply_mode="next_task", editable=True, sort_order=10,
        ))
        database.commit()

    def override_database() -> Generator[Session, None, None]:
        database = factory()
        try:
            yield database
        finally:
            database.close()

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, factory, settings
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _setup(client: TestClient) -> dict:
    """使用一次性 Token 初始化管理员并返回当前用户。"""

    response = client.post("/api/v1/setup", json={
        "bootstrap_token": "bootstrap-token-for-tests",
        "username": "admin", "display_name": "管理员",
        "password": "correct-password-123",
    })
    assert response.status_code == 200
    return response.json()


def test_password_hash_uses_argon2id_and_rejects_wrong_password() -> None:
    """密码只保存 Argon2id 哈希，错误密码不能通过。"""

    encoded = hash_password("correct-password-123")
    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, "correct-password-123")
    assert not verify_password(encoded, "wrong-password")


def test_secret_cipher_detects_tampering() -> None:
    """AES-GCM 密文篡改必须解密失败。"""

    cipher = SecretCipher({"v1": b"k" * 32}, "v1")
    encrypted = cipher.encrypt("sentinel-secret", b"scope")
    tampered = type(encrypted)(
        encrypted.ciphertext[:-1] + bytes([encrypted.ciphertext[-1] ^ 1]),
        encrypted.cipher_nonce, encrypted.wrapped_dek, encrypted.wrap_nonce,
        encrypted.kek_version,
    )
    with pytest.raises(Exception):
        cipher.decrypt(tampered, b"scope")


def test_kek_rotation_keeps_old_versions_decryptable() -> None:
    """切换 active KEK 后旧密文可读，新密文只使用新版本包装。"""

    old_cipher = SecretCipher({"v1": b"a" * 32}, "v1")
    old_value = old_cipher.encrypt("old-secret", b"scope")
    rotated = SecretCipher({"v1": b"a" * 32, "v2": b"b" * 32}, "v2")
    new_value = rotated.encrypt("new-secret", b"scope")
    assert rotated.decrypt(old_value, b"scope") == "old-secret"
    assert new_value.kek_version == "v2"
    assert rotated.decrypt(new_value, b"scope") == "new-secret"


def test_setup_session_csrf_and_secret_never_echo_plaintext(phase2_client) -> None:
    """验证初始化、服务端会话、CSRF 与 Secret 不回显闭环。"""

    client, factory, _settings = phase2_client
    me = _setup(client)
    assert me["user"]["username"] == "admin"
    assert client.get("/api/v1/tools").status_code == 200
    denied = client.put("/api/v1/secrets/sec_test", json={
        "environment_id": "dev", "owner_type": "tool", "owner_id": "truthy-search",
        "definition_id": "truthy-search.AUTH_TOKEN", "value": "sentinel-secret",
    })
    assert denied.status_code == 403
    csrf = client.cookies.get("tp_csrf")
    response = client.put(
        "/api/v1/secrets/sec_test",
        headers={"X-CSRF-Token": csrf},
        json={
            "environment_id": "dev", "owner_type": "tool", "owner_id": "truthy-search",
            "definition_id": "truthy-search.AUTH_TOKEN", "value": "sentinel-secret",
        },
    )
    assert response.status_code == 200
    assert "sentinel-secret" not in response.text
    with factory() as database:
        version = database.scalar(select(SecretVersion))
        assert version is not None
        assert b"sentinel-secret" not in version.ciphertext


def test_permission_dependency_factory_does_not_create_query_parameters(phase2_client) -> None:
    """权限依赖工厂必须解析会话，不能误把 context/database 暴露为查询参数。"""

    client, _factory, _settings = phase2_client
    _setup(client)
    assert client.get("/api/v1/admin/users").status_code == 200
    assert client.get("/api/v1/admin/roles").status_code == 200


def test_tool_client_cannot_cross_tool_scope(phase2_client) -> None:
    """工具 Client 不能读取其他工具的运行配置。"""

    client, factory, _settings = phase2_client
    with factory() as database:
        database.add(ToolClient(
            id="client_truthy", tool_id="truthy-search", environment_id="dev",
            token_hash=token_hash("tool-client-token-for-tests"),
            capabilities=["config.read"], status="active",
        ))
        database.commit()
    response = client.get(
        "/api/v1/internal/tools/log-filter/runtime-config",
        headers={"Authorization": "Bearer tool-client-token-for-tests"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "TOOL_CLIENT_FORBIDDEN"


def test_runtime_config_uses_gateway_as_primary_when_admin_is_newer(phase2_client) -> None:
    """多 Credential 快照必须聚合状态，并固定用 Gateway 版本供工具 CAS 写回。"""

    client, factory, _settings = phase2_client
    with factory() as database:
        database.add(ToolClient(
            id="client_truthy_runtime", tool_id="truthy-search", environment_id="dev",
            token_hash=token_hash("tool-runtime-token-for-tests"),
            capabilities=["config.read"], status="active",
        ))
        database.add_all([
            Credential(
                id="cred_gateway", tool_id="truthy-search", environment_id="dev",
                provider_type="gateway_session", status="healthy", current_version=2,
            ),
            Credential(
                id="cred_admin", tool_id="truthy-search", environment_id="dev",
                provider_type="admin_login", status="healthy", current_version=5,
            ),
            CredentialItem(
                credential_id="cred_admin", credential_version=5,
                key="operator_name", value_json="测试服务账号",
            ),
        ])
        database.commit()

    response = client.get(
        "/api/v1/internal/tools/truthy-search/runtime-config",
        headers={"Authorization": "Bearer tool-runtime-token-for-tests"},
    )

    assert response.status_code == 200
    metadata = response.json()["credential_metadata"]
    assert metadata["credential_id"] == "cred_gateway"
    assert metadata["credential_version"] == 2
    assert metadata["providers"]["gateway_session"]["credential_version"] == 2
    assert metadata["providers"]["admin_login"]["credential_version"] == 5
    assert "operator_name" not in metadata


def test_tool_path_policy_separates_view_result_and_execute() -> None:
    """网关路径策略必须区分页面查看、结果读取和写操作。"""

    assert required_tool_permission("truthy-search", "GET", "/truthy-search/") == "tool.view"
    assert required_tool_permission("truthy-search", "GET", "/truthy-search/runs/run_1") == "tool.result.view"
    assert required_tool_permission("api-autotest", "GET", "/api-autotest/api/tasks") == "tool.result.view"
    assert required_tool_permission("trackevents", "POST", "/trackevents/api/analyze") == "tool.execute"
    assert required_tool_permission("functional-test-agent", "GET", "/functional-test-agent/api/v1/tasks") == "tool.result.view"
    assert required_tool_permission("functional-test-agent", "POST", "/functional-test-agent/api/v1/tasks/task_1/cancel") == "task.cancel"
    assert required_tool_permission("functional-test-agent", "POST", "/functional-test-agent/api/v1/tasks/task_1/review-ai/cancel") == "task.cancel"
    assert required_tool_permission("functional-test-agent", "POST", "/functional-test-agent/api/v1/tasks/task_1/case-review-ai/cancel") == "task.cancel"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/execute") == "api-test-agent.execute"
    assert required_tool_permission("api-test-agent", "PUT", "/api-test-agent/api/v1/tasks/task_1/contracts/review") == "api-test-agent.contract.review"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/cases/generate") == "api-test-agent.case.review"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/defect-drafts") == "api-test-agent.defect.create"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/runs/run_1/retry") == "api-test-agent.execute"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/runs/run_1/cancel") == "api-test-agent.execute"


def test_credential_expiry_accepts_gateway_milliseconds_and_admin_iso() -> None:
    """普通 Gateway 和 Admin 两类稳定过期时间都应写入同一 UTC 字段。"""

    gateway = _parse_credential_expiry(1786524829758)
    admin = _parse_credential_expiry("2026-08-10T12:00:00Z")
    assert gateway.tzinfo is not None
    assert admin.isoformat() == "2026-08-10T12:00:00+00:00"


def test_agent_expiry_accepts_dotenv_millisecond_string() -> None:
    """dotenv 读取的毫秒时间戳字符串必须按 Gateway 时间解析。"""

    parsed = credential_agent._as_datetime("1801472029758")
    assert parsed.year == 2027
    assert parsed.tzinfo is not None


def test_gateway_refresh_failure_falls_back_to_new_session(monkeypatch) -> None:
    """Refresh 失效时只回退一次正式建会话，并原子返回五个会话字段。"""

    methods: list[str] = []

    def fake_post(_url: str, payload: dict) -> dict:
        method = payload["requests"][0]["method_name"]
        request_id = payload["requests"][0]["id"]
        methods.append(method)
        if method == "RefreshSession":
            return {"code": 0, "responses": [{"id": request_id, "success": False, "code": 401}]}
        return {"code": 0, "responses": [{
            "id": request_id, "success": True, "code": 0,
            "data": {
                "access_token": "new-access", "refresh_token": "new-refresh",
                "expires_time": 1786524829758, "refresh_expires_time": 1801472029758,
                "user_id": "service-user",
            },
        }]}

    monkeypatch.setattr(credential_agent, "_post_json", fake_post)
    result = credential_agent._gateway_session(
        {"GATEWAY_API_URL": "https://gateway.example.test"},
        {"AUTH_TOKEN": "old", "REFRESH_TOKEN": "old-refresh", "DEVICE_ID": "device"},
    )
    assert methods == ["RefreshSession", "CreateAnonymousSession"]
    assert result["AUTH_TOKEN"] == "new-access"
    assert result["REFRESH_TOKEN"] == "new-refresh"
