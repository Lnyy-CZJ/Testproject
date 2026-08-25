from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.core.permissions import required_tool_permission
from app.core.security import SecretCipher, hash_password, token_hash, verify_password
from app.api.deps import AuthContext, current_auth_context, require_csrf
from app.api.internal import _parse_credential_expiry, public_request_is_locally_safe
from app.jobs import credential_agent
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.configuration import (
    ConfigActivation,
    ConfigDefinition,
    ConfigRelease,
    ConfigReleaseItem,
    Credential,
    CredentialItem,
    Environment,
    Secret,
    SecretVersion,
    UserCredential,
    UserCredentialItem,
)
from app.models.audit import AuditLog
from app.models.identity import (
    Permission,
    PlatformSession,
    RuntimeContext,
    Role,
    RoleGrant,
    ToolClient,
    User,
    UserRole,
)
from app.models.tool import Tool
from app.models.llm import LlmProfile, ToolLlmBinding, UserLlmBinding
from app.services.llm import materialize_llm_snapshot, resolve_llm_snapshot
from app.services.secret_store import decrypt_secret_version, load_secret_cipher, replace_secret
from app.services import auth as auth_services


@pytest.fixture
def phase2_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, sessionmaker[Session], Settings], None, None]:
    """创建包含第二阶段种子的隔离 API 客户端。"""

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    kek_path = tmp_path / "kek.json"
    kek_path.write_text(json.dumps({
        "active": "v1",
        "keys": {"v1": base64.b64encode(b"k" * 32).decode("ascii")},
    }), encoding="utf-8")
    # 自助接口测试显式开启写入能力；生产和 Compose 默认仍保持关闭。
    monkeypatch.setenv("PERSONAL_CREDENTIALS_WRITE_ENABLED", "true")
    monkeypatch.setenv("PERSONAL_CREDENTIALS_ENABLED", "true")
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

    client, factory, settings = phase2_client
    # 本用例验证的是开关关闭期间保留的 legacy Resolver 契约；个人读取开关
    # 在该测试内显式关闭，避免与其余用户隔离用例共享的默认开启状态混淆。
    settings.personal_credentials_enabled = False
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
    assert required_tool_permission("truthy-search", "POST", "/truthy-search/processes/process_1/candidates/candidate_1/review") == "tool.execute"
    assert required_tool_permission("truthy-search", "POST", "/truthy-search/baselines/v1/people/person_1/available-fields") == "tool.execute"
    assert required_tool_permission("api-autotest", "GET", "/api-autotest/api/tasks") == "tool.result.view"
    assert required_tool_permission("api-autotest", "GET", "/api-autotest/catalog") == "tool.view"
    assert required_tool_permission("log-filter", "POST", "/log-filter/people-search/analyze") == "tool.execute"
    assert required_tool_permission("log-filter", "POST", "/log-filter/export") == "tool.execute"
    assert required_tool_permission("trackevents", "POST", "/trackevents/api/analyze") == "tool.execute"
    assert required_tool_permission("functional-test-agent", "GET", "/functional-test-agent/api/v1/tasks") == "tool.result.view"
    assert required_tool_permission("functional-test-agent", "POST", "/functional-test-agent/api/v1/tasks/task_1/cancel") == "task.cancel"
    assert required_tool_permission("functional-test-agent", "POST", "/functional-test-agent/api/v1/tasks/task_1/review-ai/cancel") == "task.cancel"
    assert required_tool_permission("functional-test-agent", "POST", "/functional-test-agent/api/v1/tasks/task_1/case-review-ai/cancel") == "task.cancel"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/execute") == "api-test-agent.execute"
    assert required_tool_permission("api-test-agent", "PUT", "/api-test-agent/api/v1/tasks/task_1/contracts/review") == "api-test-agent.contract.review"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/cases/generate") == "api-test-agent.case.review"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/cases/confirm-all") == "api-test-agent.case.review"
    # 组合确认会在 API Agent 内继续校验 case.review；网关先保护阶段三生成能力。
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/cases/confirm-and-generate-executable") == "api-test-agent.executable.generate"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/executable-cases/generate") == "api-test-agent.executable.generate"
    assert required_tool_permission("api-test-agent", "PUT", "/api-test-agent/api/v1/tasks/task_1/executable-cases/review") == "api-test-agent.executable.review"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/execution-plans/preview") == "tool.result.view"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/execution-plans") == "api-test-agent.executable.review"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/execution-plans/plan_1/confirm") == "api-test-agent.execute"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/execution-plans/plan_1/runs") == "api-test-agent.execute"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/defect-drafts") == "api-test-agent.defect.create"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/runs/run_1/retry") == "api-test-agent.execute"
    assert required_tool_permission("api-test-agent", "POST", "/api-test-agent/api/v1/tasks/task_1/runs/run_1/cancel") == "api-test-agent.execute"
    # 未登记路径必须稳定拒绝，不能再根据 api/tasks 等字符串片段推断权限。
    assert required_tool_permission("truthy-search", "GET", "/truthy-search/admin/debug") == "tool.route.unregistered"
    assert required_tool_permission("log-filter", "DELETE", "/log-filter/anything") == "tool.route.unregistered"
    assert public_request_is_locally_safe("truthy-search", "GET", "/truthy-search/")
    assert public_request_is_locally_safe("log-filter", "POST", "/log-filter/export")
    assert not public_request_is_locally_safe("functional-test-agent", "POST", "/functional-test-agent/api/v1/tasks")


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


def test_credential_agent_refreshes_each_user_without_legacy_double_write(
    phase2_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """个人模式只轮换各用户自己的版本，legacy Credential 必须保持只读。"""

    client, factory, settings = phase2_client
    admin_payload = _setup(client)
    admin_id = admin_payload["user"]["id"]
    member_id = "user-agent-member"
    with factory() as database:
        database.add(User(
            id=member_id,
            username="agent-member",
            username_normalized="agent-member",
            display_name="刷新测试用户",
            password_hash="unused",
            status="active",
        ))
        auth_definition = database.get(ConfigDefinition, "truthy-search.AUTH_TOKEN")
        auth_definition.value_scope = "user"
        auth_definition.credential_provider_type = "gateway_session"
        refresh_definition = ConfigDefinition(
            id="truthy-search.REFRESH_TOKEN",
            key="REFRESH_TOKEN",
            display_name="Refresh Token",
            description="",
            owner_type="tool",
            owner_id="truthy-search",
            group_key="credentials",
            value_type="secret",
            sensitivity="secret",
            required=True,
            validation_schema={},
            apply_mode="next_task",
            editable=True,
            sort_order=20,
            value_scope="user",
            credential_provider_type="gateway_session",
        )
        database.add(refresh_definition)
        cipher = load_secret_cipher(settings)
        for suffix, user_id in (("admin", admin_id), ("member", member_id)):
            credential = UserCredential(
                id=f"ucred_agent_{suffix}",
                user_id=user_id,
                tool_id="truthy-search",
                environment_id="dev",
                provider_type="gateway_session",
                status="pending_validation",
                current_version=1,
            )
            database.add(credential)
            database.flush()
            for definition, value in (
                (auth_definition, f"{suffix}-access-v1"),
                (refresh_definition, f"{suffix}-refresh-v1"),
            ):
                secret = Secret(
                    id=f"sec_agent_{suffix}_{definition.key.lower()}",
                    environment_id="dev",
                    owner_type="user_credential",
                    owner_id=credential.id,
                    definition_id=definition.id,
                    status="missing",
                )
                database.add(secret)
                database.flush()
                secret_version = replace_secret(database, cipher, secret, value, user_id)
                database.flush()
                database.add(UserCredentialItem(
                    credential_id=credential.id,
                    credential_version=1,
                    key=definition.key,
                    secret_version_id=secret_version.id,
                ))
        database.add(Credential(
            id="cred_agent_legacy_sentinel",
            tool_id="truthy-search",
            environment_id="dev",
            provider_type="gateway_session",
            status="pending_validation",
            current_version=7,
        ))
        database.commit()

    seen_access_tokens: list[str] = []

    def fake_gateway_session(_normal: dict, secrets: dict[str, str]) -> dict:
        """用输入 Token 标识所属用户，避免测试依赖数据库扫描顺序。"""

        access_token = secrets["AUTH_TOKEN"]
        seen_access_tokens.append(access_token)
        return {
            "AUTH_TOKEN": access_token.replace("-v1", "-v2"),
            "REFRESH_TOKEN": secrets["REFRESH_TOKEN"].replace("-v1", "-v2"),
            "expires_at": datetime.now(UTC) + timedelta(hours=2),
            "refresh_expires_at": datetime.now(UTC) + timedelta(days=2),
        }

    monkeypatch.setattr(credential_agent, "SessionLocal", factory)
    monkeypatch.setattr(credential_agent, "get_settings", lambda: settings)
    monkeypatch.setattr(credential_agent, "_gateway_session", fake_gateway_session)

    assert credential_agent.process_one() is True
    assert credential_agent.process_one() is True
    assert credential_agent.process_one() is False
    assert set(seen_access_tokens) == {"admin-access-v1", "member-access-v1"}

    with factory() as database:
        cipher = load_secret_cipher(settings)
        for suffix in ("admin", "member"):
            credential = database.get(UserCredential, f"ucred_agent_{suffix}")
            assert credential.current_version == 2
            assert credential.status == "healthy"
            item = database.scalar(select(UserCredentialItem).where(
                UserCredentialItem.credential_id == credential.id,
                UserCredentialItem.credential_version == 2,
                UserCredentialItem.key == "AUTH_TOKEN",
            ))
            version = database.get(SecretVersion, item.secret_version_id)
            secret = database.get(Secret, version.secret_id)
            assert decrypt_secret_version(database, cipher, secret, version.id) == (
                f"{suffix}-access-v2"
            )
        legacy = database.get(Credential, "cred_agent_legacy_sentinel")
        assert (legacy.current_version, legacy.status) == (7, "pending_validation")


def test_truthy_admin_refresh_discards_unregistered_session_fields(
    phase2_client,
) -> None:
    """Truthy Admin 仅验证账号字段，不把 API AutoTest Session 字段跨 Provider 写入。"""

    client, factory, settings = phase2_client
    admin_id = _setup(client)["user"]["id"]
    with factory() as database:
        definitions = []
        for index, key in enumerate(("SEARCH_ADMIN_USERNAME", "SEARCH_ADMIN_PASSWORD")):
            definition = ConfigDefinition(
                id=f"truthy-search.{key}",
                key=key,
                display_name=key,
                description="",
                owner_type="tool",
                owner_id="truthy-search",
                group_key="credentials",
                value_type="secret",
                sensitivity="secret",
                required=True,
                validation_schema={},
                apply_mode="next_task",
                editable=True,
                sort_order=100 + index,
                value_scope="user",
                credential_provider_type="admin_login",
            )
            database.add(definition)
            definitions.append(definition)
        credential = UserCredential(
            id="ucred_truthy_admin_agent",
            user_id=admin_id,
            tool_id="truthy-search",
            environment_id="dev",
            provider_type="admin_login",
            status="refreshing",
            current_version=1,
            refresh_owner="agent-test",
        )
        database.add(credential)
        database.flush()
        cipher = load_secret_cipher(settings)
        for definition, value in zip(definitions, ("admin-user", "admin-password"), strict=True):
            secret = Secret(
                id=f"sec_truthy_admin_{definition.key.lower()}",
                environment_id="dev",
                owner_type="user_credential",
                owner_id=credential.id,
                definition_id=definition.id,
                status="missing",
            )
            database.add(secret)
            database.flush()
            version = replace_secret(database, cipher, secret, value, admin_id)
            database.flush()
            database.add(UserCredentialItem(
                credential_id=credential.id,
                credential_version=1,
                key=definition.key,
                secret_version_id=version.id,
            ))
        database.commit()

        credential_agent._activate_personal(
            database,
            credential,
            1,
            {
                "ADMIN_SESSION_TOKEN": "transient-session-token",
                "ADMIN_OPERATOR_ID": "operator-1",
                "ADMIN_OPERATOR_NAME": "测试账号",
                "expires_at": datetime.now(UTC) + timedelta(hours=2),
            },
        )
        database.commit()

        version_two = list(database.scalars(select(UserCredentialItem).where(
            UserCredentialItem.credential_id == credential.id,
            UserCredentialItem.credential_version == 2,
        )).all())
        assert {item.key for item in version_two} == {
            "SEARCH_ADMIN_USERNAME",
            "SEARCH_ADMIN_PASSWORD",
        }
        assert credential.status == "healthy"
        assert "transient-session-token" not in json.dumps([
            item.value_json for item in version_two
        ])


def test_user_credential_scope_is_unique_per_user_and_provider() -> None:
    """同一用户不能重复创建同环境 Provider，不同用户必须拥有独立记录。"""

    import app.models.configuration as configuration_models

    assert hasattr(configuration_models, "UserCredential"), "用户级凭证模型尚未实现"
    user_credential_model = configuration_models.UserCredential

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as database:
        database.add_all([
            Environment(id="dev", name="开发环境"),
            Tool(
                id="truthy-search", name="检索评测", description="",
                entry_url="/truthy-search/", health_url="http://truthy/health",
                short_code="SEARCH", icon_key="search", category="evaluation",
                features=[], sort_order=10, is_enabled=True,
            ),
            User(
                id="user-a", username="user-a", username_normalized="user-a",
                display_name="用户 A", password_hash="unused",
            ),
            User(
                id="user-b", username="user-b", username_normalized="user-b",
                display_name="用户 B", password_hash="unused",
            ),
        ])
        database.commit()
        database.add(user_credential_model(
            id="ucred-a", user_id="user-a", tool_id="truthy-search",
            environment_id="dev", provider_type="gateway_session",
        ))
        database.commit()

        database.add(user_credential_model(
            id="ucred-duplicate", user_id="user-a", tool_id="truthy-search",
            environment_id="dev", provider_type="gateway_session",
        ))
        with pytest.raises(IntegrityError):
            database.commit()
        database.rollback()

        database.add(user_credential_model(
            id="ucred-b", user_id="user-b", tool_id="truthy-search",
            environment_id="dev", provider_type="gateway_session",
        ))
        database.commit()
        assert {
            row.id for row in database.scalars(select(user_credential_model)).all()
        } == {"ucred-a", "ucred-b"}

    engine.dispose()


def _personal_test_context(user: User, suffix: str) -> AuthContext:
    """为 HTTP 所有权测试构造不含 Cookie 明文的服务端认证上下文。"""

    now = datetime.now(UTC)
    return AuthContext(
        user=user,
        session=PlatformSession(
            id=f"session-{suffix}", token_hash=f"token-{suffix}",
            csrf_hash=f"csrf-{suffix}", user_id=user.id,
            idle_expires_at=now + timedelta(hours=1),
            absolute_expires_at=now + timedelta(hours=2), last_seen_at=now,
        ),
    )


def test_personal_credential_api_isolates_two_users_and_never_echoes_values(
    phase2_client,
) -> None:
    """双用户写入、列表、IDOR、CAS 和字段作用域必须形成完整隔离闭环。"""

    client, factory, _settings = phase2_client
    _setup(client)
    with factory() as database:
        admin = database.scalar(select(User).where(User.username_normalized == "admin"))
        auth_token_definition = database.get(ConfigDefinition, "truthy-search.AUTH_TOKEN")
        auth_token_definition.value_scope = "user"
        auth_token_definition.credential_provider_type = "gateway_session"
        member = User(
            id="usr_member", username="member", username_normalized="member",
            display_name="成员", password_hash="unused", status="active",
        )
        member_role = Role(id="role_member", name="成员")
        database.add_all([
            member,
            member_role,
            Environment(id="prod", name="生产环境", sort_order=20),
            Permission(code="tool.execute", name="执行工具", resource_type="tool"),
            ConfigDefinition(
                id="truthy-search.REFRESH_TOKEN", key="REFRESH_TOKEN",
                display_name="Refresh Token", description="", owner_type="tool",
                owner_id="truthy-search", group_key="credentials", value_type="secret",
                sensitivity="secret", required=True, validation_schema={},
                apply_mode="next_task", editable=True, sort_order=20,
                value_scope="user", credential_provider_type="gateway_session",
            ),
            ConfigDefinition(
                id="truthy-search.DEVICE_ID", key="DEVICE_ID",
                display_name="设备 ID", description="", owner_type="tool",
                owner_id="truthy-search", group_key="credentials", value_type="string",
                sensitivity="normal", required=False, validation_schema={"min_length": 1},
                apply_mode="next_task", editable=True, sort_order=30,
                value_scope="user", credential_provider_type="gateway_session",
            ),
            ConfigDefinition(
                id="truthy-search.SYSTEM_SENTINEL", key="SYSTEM_SENTINEL",
                display_name="系统 Secret", description="", owner_type="tool",
                owner_id="truthy-search", group_key="system", value_type="secret",
                sensitivity="secret", required=False, validation_schema={},
                apply_mode="next_task", editable=True, sort_order=40,
                value_scope="system", credential_provider_type=None,
            ),
        ])
        database.flush()
        database.add_all([
            UserRole(user_id=member.id, role_id=member_role.id, created_by=admin.id),
            RoleGrant(
                role_id="role_platform_admin", permission_code="tool.execute",
                resource_type="tool", resource_id="truthy-search", created_by="test",
            ),
            RoleGrant(
                role_id=member_role.id, permission_code="tool.execute",
                resource_type="tool", resource_id="truthy-search", created_by="test",
            ),
        ])
        database.commit()
        admin_context = _personal_test_context(admin, "admin")
        member_context = _personal_test_context(member, "member")

    def use_context(context: AuthContext) -> None:
        app.dependency_overrides[current_auth_context] = lambda: context
        app.dependency_overrides[require_csrf] = lambda: context

    admin_values = {
        "AUTH_TOKEN": "admin-specific-access-token",
        "REFRESH_TOKEN": "admin-specific-refresh-token",
        "DEVICE_ID": "admin-device",
    }
    member_values = {
        "AUTH_TOKEN": "member-specific-access-token",
        "REFRESH_TOKEN": "member-specific-refresh-token",
        "DEVICE_ID": "member-device",
    }
    use_context(admin_context)
    admin_response = client.put(
        "/api/v1/me/credentials/truthy-search/gateway_session",
        json={"environment_id": "dev", "expected_version": 0, "values": admin_values},
    )
    assert admin_response.status_code == 200
    use_context(member_context)
    personal_catalog = client.get(
        "/api/v1/config/definitions?owner_type=tool&owner_id=truthy-search"
    )
    assert personal_catalog.status_code == 200
    assert {row["key"] for row in personal_catalog.json()} == {
        "AUTH_TOKEN", "REFRESH_TOKEN", "DEVICE_ID",
    }
    assert all(row["value_scope"] == "user" for row in personal_catalog.json())
    member_response = client.put(
        "/api/v1/me/credentials/truthy-search/gateway_session",
        json={"environment_id": "dev", "expected_version": 0, "values": member_values},
    )
    assert member_response.status_code == 200

    admin_payload = admin_response.json()
    member_payload = member_response.json()
    assert admin_payload["id"] != member_payload["id"]
    assert admin_payload["current_version"] == member_payload["current_version"] == 1
    serialized = json.dumps([admin_payload, member_payload], ensure_ascii=False)
    assert all(secret not in serialized for secret in [*admin_values.values(), *member_values.values()])
    assert {field["key"] for field in admin_payload["fields"] if field["configured"]} == {
        "AUTH_TOKEN", "REFRESH_TOKEN", "DEVICE_ID",
    }

    use_context(admin_context)
    admin_list = client.get("/api/v1/me/credentials?environment_id=dev")
    assert admin_list.status_code == 200
    assert [row["id"] for row in admin_list.json()] == [admin_payload["id"]]
    assert member_payload["id"] not in admin_list.text
    cross_validate = client.post(
        f"/api/v1/me/credentials/{member_payload['id']}/validate"
    )
    assert cross_validate.status_code == 404
    assert cross_validate.json()["code"] == "NOT_FOUND"

    scope_mismatch = client.put(
        "/api/v1/me/credentials/truthy-search/gateway_session",
        json={
            "environment_id": "dev", "expected_version": 1,
            "values": {"ADMIN_PASSWORD": "must-not-be-accepted"},
        },
    )
    assert scope_mismatch.status_code == 403
    assert scope_mismatch.json()["code"] == "CREDENTIAL_SCOPE_MISMATCH"
    assert "must-not-be-accepted" not in scope_mismatch.text

    conflict = client.put(
        "/api/v1/me/credentials/truthy-search/gateway_session",
        json={
            "environment_id": "dev", "expected_version": 0,
            "values": {"DEVICE_ID": "stale-write"},
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "VERSION_CONFLICT"

    partial_update = client.put(
        "/api/v1/me/credentials/truthy-search/gateway_session",
        json={
            "environment_id": "dev", "expected_version": 1,
            "values": {"DEVICE_ID": "admin-device-v2"},
        },
    )
    assert partial_update.status_code == 200
    assert partial_update.json()["current_version"] == 2
    assert all(field["configured"] for field in partial_update.json()["fields"])
    assert "admin-device-v2" not in partial_update.text

    missing_required = client.put(
        "/api/v1/me/credentials/truthy-search/gateway_session",
        json={
            "environment_id": "prod", "expected_version": 0,
            "values": {"AUTH_TOKEN": "only-one-required-field"},
        },
    )
    assert missing_required.status_code == 422
    assert "only-one-required-field" not in missing_required.text

    with factory() as database:
        version_two_items = list(database.scalars(select(UserCredentialItem).join(
            UserCredential, UserCredential.id == UserCredentialItem.credential_id
        ).where(
            UserCredential.id == admin_payload["id"],
            UserCredentialItem.credential_version == 2,
        )).all())
        assert {item.key for item in version_two_items} == {
            "AUTH_TOKEN", "REFRESH_TOKEN", "DEVICE_ID",
        }
        audit_text = json.dumps([
            {
                "before": row.before_json,
                "after": row.after_json,
                "metadata": row.metadata_json,
            }
            for row in database.scalars(select(AuditLog)).all()
        ], ensure_ascii=False)
        assert all(secret not in audit_text for secret in [*admin_values.values(), *member_values.values()])


def test_admin_credential_readiness_is_authorized_complete_and_redacted(
    phase2_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """管理员可见全员缺失状态，但聚合过程不得解密或返回个人 Secret。"""

    client, factory, settings = phase2_client
    _setup(client)
    sentinel = "readiness-must-never-decrypt-or-return"
    with factory() as database:
        admin = database.scalar(select(User).where(User.username_normalized == "admin"))
        member = User(
            id="usr_readiness_member",
            username="readiness-member",
            username_normalized="readiness-member",
            display_name="就绪度成员",
            password_hash="unused",
            status="active",
        )
        member_role = Role(id="role_readiness_member", name="就绪度成员")
        readiness_permission = Permission(
            code="platform.credential.readiness.view",
            name="查看凭证就绪度",
            resource_type="platform",
        )
        token_definition = database.get(ConfigDefinition, "truthy-search.AUTH_TOKEN")
        token_definition.value_scope = "user"
        token_definition.credential_provider_type = "gateway_session"
        refresh_definition = ConfigDefinition(
            id="truthy-search.READINESS_REFRESH_TOKEN",
            key="REFRESH_TOKEN",
            display_name="Refresh Token",
            description="",
            owner_type="tool",
            owner_id="truthy-search",
            group_key="credentials",
            value_type="secret",
            sensitivity="secret",
            required=True,
            validation_schema={},
            apply_mode="next_task",
            editable=True,
            sort_order=20,
            value_scope="user",
            credential_provider_type="gateway_session",
        )
        llm_binding = ToolLlmBinding(
            id="llmb_readiness_default",
            tool_id="truthy-search",
            capability_key="default",
            display_name="默认模型",
            description="",
            created_by="test",
        )
        database.add_all([
            member,
            member_role,
            readiness_permission,
            refresh_definition,
            llm_binding,
        ])
        database.flush()
        database.add_all([
            UserRole(user_id=member.id, role_id=member_role.id, created_by=admin.id),
            RoleGrant(
                role_id="role_platform_admin",
                permission_code=readiness_permission.code,
                resource_type="platform",
                resource_id="*",
                created_by="test",
            ),
        ])
        credential = UserCredential(
            id="ucred_readiness_admin",
            user_id=admin.id,
            tool_id="truthy-search",
            environment_id="dev",
            provider_type="gateway_session",
            status="healthy",
            current_version=1,
            last_checked_at=datetime.now(UTC),
        )
        database.add(credential)
        database.flush()
        secret = Secret(
            id="sec_readiness_admin",
            environment_id="dev",
            owner_type="user_credential",
            owner_id=credential.id,
            definition_id=token_definition.id,
            status="missing",
        )
        database.add(secret)
        database.flush()
        version = replace_secret(
            database,
            load_secret_cipher(settings),
            secret,
            sentinel,
            admin.id,
        )
        database.flush()
        database.add(UserCredentialItem(
            credential_id=credential.id,
            credential_version=1,
            key="AUTH_TOKEN",
            secret_version_id=version.id,
        ))
        database.commit()
        admin_context = _personal_test_context(admin, "readiness-admin")
        member_context = _personal_test_context(member, "readiness-member")

    # 如果实现错误地走到 Secret 解密路径，测试会立即失败；就绪度只能聚合元数据。
    monkeypatch.setattr(
        "app.services.secret_store.decrypt_secret_version",
        lambda *_args, **_kwargs: pytest.fail("就绪度接口禁止解密 Secret"),
    )
    app.dependency_overrides[current_auth_context] = lambda: member_context
    forbidden = client.get("/api/v1/admin/credential-readiness?environment_id=dev")
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "PERMISSION_DENIED"

    app.dependency_overrides[current_auth_context] = lambda: admin_context
    response = client.get(
        "/api/v1/admin/credential-readiness"
        "?environment_id=dev&tool_id=truthy-search&provider_type=gateway_session"
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert sentinel not in response.text
    credential_rows = [
        row for row in response.json() if row["resource_type"] == "credential"
    ]
    assert {(row["username"], row["readiness_status"]) for row in credential_rows} == {
        ("admin", "missing"),
        ("readiness-member", "missing"),
    }
    admin_row = next(row for row in credential_rows if row["username"] == "admin")
    assert admin_row["configured_field_count"] == 1
    assert admin_row["required_field_count"] == 2
    assert admin_row["current_version"] == 1
    assert "credential_id" not in admin_row

    missing_only = client.get(
        "/api/v1/admin/credential-readiness"
        "?environment_id=dev&tool_id=truthy-search&status=missing"
    )
    assert missing_only.status_code == 200
    assert all(row["readiness_status"] == "missing" for row in missing_only.json())
    assert {
        (row["username"], row["capability_key"])
        for row in missing_only.json()
        if row["resource_type"] == "llm_binding"
    } == {
        ("admin", "default"),
        ("readiness-member", "default"),
    }
    with factory() as database:
        audit = database.scalar(select(AuditLog).where(
            AuditLog.action == "admin.credential.readiness.view"
        ).order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()))
        assert audit is not None
        assert audit.metadata_json["filters"]["environment_id"] == "dev"
        assert sentinel not in json.dumps(audit.metadata_json, ensure_ascii=False)


def test_personal_llm_api_isolates_profiles_and_bindings_by_user(
    phase2_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """个人 Profile、API Key 与能力 Binding 必须按服务端用户上下文隔离。"""

    client, factory, settings = phase2_client
    _setup(client)
    monkeypatch.setattr(
        "app.api.llm.validate_provider_target",
        lambda base_url, _allowlist, *, production: base_url.rstrip("/") + "/chat/completions",
    )
    with factory() as database:
        admin = database.scalar(select(User).where(User.username_normalized == "admin"))
        member = User(
            id="usr_llm_member", username="llm-member",
            username_normalized="llm-member", display_name="LLM 成员",
            password_hash="unused", status="active",
        )
        member_role = Role(id="role_llm_member", name="LLM 成员")
        binding = ToolLlmBinding(
            id="llmb_truthy_default", tool_id="truthy-search",
            capability_key="default", display_name="默认总结模型",
            description="", created_by="test",
        )
        database.add_all([
            member,
            member_role,
            Permission(code="tool.execute", name="执行工具", resource_type="tool"),
            Permission(
                code="platform.llm.manage",
                name="管理公共 LLM 配置",
                resource_type="platform",
            ),
            Permission(
                code="platform.llm.secret.manage",
                name="管理公共 LLM Secret",
                resource_type="platform",
            ),
            binding,
        ])
        binding_specs = (
            ("PROFILE_ID", "string", "normal", True, None),
            ("MODEL_OVERRIDE", "string", "normal", False, None),
            ("TEMPERATURE_OVERRIDE", "float", "normal", False, None),
            ("MAX_TOKENS_OVERRIDE", "int", "normal", False, None),
            ("TIMEOUT_SECONDS_OVERRIDE", "int", "normal", False, None),
            ("ENABLED", "bool", "normal", True, True),
            ("API_KEY_OVERRIDE", "secret", "secret", False, None),
        )
        for sort_order, (key, value_type, sensitivity, required, default) in enumerate(
            binding_specs, start=1
        ):
            database.add(ConfigDefinition(
                id=f"{binding.id}.{key}", key=key, display_name=key,
                description="", owner_type="llm_binding", owner_id=binding.id,
                group_key="model", value_type=value_type, sensitivity=sensitivity,
                required=required, default_value=default, validation_schema={},
                apply_mode="next_task", editable=True, sort_order=sort_order * 10,
            ))
        database.flush()
        database.add_all([
            UserRole(user_id=member.id, role_id=member_role.id, created_by=admin.id),
            RoleGrant(
                role_id="role_platform_admin", permission_code="tool.execute",
                resource_type="tool", resource_id="truthy-search", created_by="test",
            ),
            RoleGrant(
                role_id=member_role.id, permission_code="tool.execute",
                resource_type="tool", resource_id="truthy-search", created_by="test",
            ),
            RoleGrant(
                role_id="role_platform_admin",
                permission_code="platform.llm.manage",
                resource_type="platform",
                resource_id="*",
                created_by="test",
            ),
            RoleGrant(
                role_id="role_platform_admin",
                permission_code="platform.llm.secret.manage",
                resource_type="platform",
                resource_id="*",
                created_by="test",
            ),
        ])
        database.commit()
        admin_context = _personal_test_context(admin, "llm-admin")
        member_context = _personal_test_context(member, "llm-member")

    def use_context(context: AuthContext) -> None:
        app.dependency_overrides[current_auth_context] = lambda: context
        app.dependency_overrides[require_csrf] = lambda: context

    def create_profile(context: AuthContext, *, model: str, api_key: str) -> dict:
        use_context(context)
        result = client.post("/api/v1/me/llm/profiles", json={
            "name": "  我的模型  ",
            "description": model,
            "environment_id": "dev",
            "provider": "openai_compatible",
            "base_url": f"https://dashscope.aliyuncs.com/{model}",
            "model": model,
            "api_key": api_key,
            "temperature": 0.2,
            "max_tokens": 1024,
            "timeout_seconds": 30,
            "enabled": True,
        })
        assert result.status_code == 201
        assert result.headers["cache-control"] == "no-store"
        assert api_key not in result.text
        assert result.json()["model"] == model
        assert result.json()["api_key_configured"] is True
        return result.json()

    admin_key = "admin-only-personal-llm-key"
    member_key = "member-only-personal-llm-key"
    admin_profile = create_profile(admin_context, model="admin-model", api_key=admin_key)
    member_profile = create_profile(member_context, model="member-model", api_key=member_key)
    assert admin_profile["id"] != member_profile["id"]

    use_context(admin_context)
    # 个人 Profile 必须只通过 /me/llm 管理。即使当前用户同时是平台 LLM
    # 管理员，legacy 公共接口和通用配置接口也不能枚举或改写个人对象。
    legacy_profiles = client.get("/api/v1/llm/profiles?environment_id=dev")
    assert legacy_profiles.status_code == 200
    assert admin_profile["id"] not in legacy_profiles.text
    assert member_profile["id"] not in legacy_profiles.text
    legacy_update = client.patch(
        f"/api/v1/llm/profiles/{admin_profile['id']}?environment_id=dev",
        json={"description": "legacy-cross-scope-write"},
    )
    assert legacy_update.status_code == 404
    generic_definitions = client.get(
        "/api/v1/config/definitions"
        f"?owner_type=llm_profile&owner_id={admin_profile['id']}"
    )
    assert generic_definitions.status_code == 200
    assert generic_definitions.json() == []
    generic_secrets = client.get(
        "/api/v1/secrets"
        f"?environment_id=dev&owner_type=llm_profile&owner_id={admin_profile['id']}"
    )
    assert generic_secrets.status_code == 403

    duplicate = client.post("/api/v1/me/llm/profiles", json={
        "name": "我的模型", "environment_id": "dev",
        "provider": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/duplicate",
        "model": "duplicate", "api_key": "duplicate-key",
    })
    assert duplicate.status_code == 409
    injected_owner = client.post("/api/v1/me/llm/profiles", json={
        "name": "非法所有者", "environment_id": "dev",
        "provider": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/injected",
        "model": "injected", "api_key": "injected-key",
        "owner_user_id": member_context.user.id,
    })
    assert injected_owner.status_code == 422
    own_profiles = client.get("/api/v1/me/llm/profiles?environment_id=dev")
    assert own_profiles.status_code == 200
    assert [row["id"] for row in own_profiles.json()] == [admin_profile["id"]]
    assert member_profile["id"] not in own_profiles.text
    cross_update = client.patch(
        f"/api/v1/me/llm/profiles/{member_profile['id']}",
        json={"environment_id": "dev", "description": "cross-user-write"},
    )
    assert cross_update.status_code == 404
    assert cross_update.json()["code"] == "NOT_FOUND"

    cross_binding = client.put(f"/api/v1/me/llm/bindings/{binding.id}", json={
        "environment_id": "dev", "expected_version": 0,
        "profile_id": member_profile["id"], "enabled": True,
    })
    assert cross_binding.status_code == 404
    assert member_profile["id"] not in cross_binding.text
    admin_binding = client.put(f"/api/v1/me/llm/bindings/{binding.id}", json={
        "environment_id": "dev", "expected_version": 0,
        "profile_id": admin_profile["id"], "enabled": True,
    })
    assert admin_binding.status_code == 200
    assert admin_binding.json()["profile_id"] == admin_profile["id"]

    use_context(member_context)
    member_binding = client.put(f"/api/v1/me/llm/bindings/{binding.id}", json={
        "environment_id": "dev", "expected_version": 0,
        "profile_id": member_profile["id"], "enabled": True,
    })
    assert member_binding.status_code == 200
    assert member_binding.json()["id"] != admin_binding.json()["id"]
    member_bindings = client.get("/api/v1/me/llm/bindings?environment_id=dev")
    assert member_bindings.status_code == 200
    assert member_bindings.json()[0]["profile_id"] == member_profile["id"]
    assert admin_profile["id"] not in member_bindings.text

    with factory() as database:
        admin_safe = resolve_llm_snapshot(
            database, settings, "dev", "truthy-search", "default",
            admin_context.user.id, include_secrets=False,
        )
        admin_full = resolve_llm_snapshot(
            database, settings, "dev", "truthy-search", "default",
            admin_context.user.id, include_secrets=True,
        )
        member_full = resolve_llm_snapshot(
            database, settings, "dev", "truthy-search", "default",
            member_context.user.id, include_secrets=True,
        )
        assert "api_key" not in admin_safe
        assert admin_full["profile_id"] == admin_profile["id"]
        assert member_full["profile_id"] == member_profile["id"]
        assert admin_full["model"] == "admin-model"
        assert member_full["model"] == "member-model"
        assert admin_full["api_key"] == admin_key
        assert member_full["api_key"] == member_key
        assert admin_full["snapshot_id"] != member_full["snapshot_id"]

    admin_key_v2 = "admin-only-personal-llm-key-v2"
    use_context(admin_context)
    updated_profile = client.patch(
        f"/api/v1/me/llm/profiles/{admin_profile['id']}",
        json={
            "environment_id": "dev", "model": "admin-model-v2",
            "api_key": admin_key_v2,
        },
    )
    assert updated_profile.status_code == 200
    with factory() as database:
        frozen = materialize_llm_snapshot(
            database, settings, "dev", "truthy-search", "default",
            admin_context.user.id,
            binding_release_id=admin_full["binding_release_id"],
            profile_release_id=admin_full["profile_release_id"],
            secret_version_id=admin_full["api_key_secret_version_id"],
        )
        latest_admin = resolve_llm_snapshot(
            database, settings, "dev", "truthy-search", "default",
            admin_context.user.id, include_secrets=True,
        )
        assert frozen["model"] == "admin-model"
        assert frozen["api_key"] == admin_key
        assert latest_admin["model"] == "admin-model-v2"
        assert latest_admin["api_key"] == admin_key_v2
        with pytest.raises(PlatformError) as cross_user_selector:
            materialize_llm_snapshot(
                database, settings, "dev", "truthy-search", "default",
                admin_context.user.id,
                binding_release_id=admin_full["binding_release_id"],
                profile_release_id=member_full["profile_release_id"],
                secret_version_id=member_full["api_key_secret_version_id"],
            )
        assert cross_user_selector.value.code == "RUNTIME_SNAPSHOT_INVALID"

    class _ConnectionResponse:
        """模拟只返回固定最小 OpenAI 兼容响应的流式 Provider。"""

        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_bytes(self):
            yield b'{"choices":[{"message":{"content":"OK"}}]}'

    class _ConnectionClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            return _ConnectionResponse()

    monkeypatch.setattr("app.api.llm.httpx.Client", _ConnectionClient)
    use_context(member_context)
    connection = client.post("/api/v1/me/llm/test-connection", json={
        "environment_id": "dev", "binding_id": binding.id,
    })
    assert connection.status_code == 200
    assert connection.json()["status"] == "ok"
    assert connection.json()["model"] == "member-model"
    assert member_key not in connection.text

    use_context(admin_context)
    in_use = client.post(
        f"/api/v1/me/llm/profiles/{admin_profile['id']}/archive?environment_id=dev"
    )
    assert in_use.status_code == 409
    assert in_use.json()["code"] == "LLM_PROFILE_IN_USE"
    unbound = client.put(f"/api/v1/me/llm/bindings/{binding.id}", json={
        "environment_id": "dev", "expected_version": 1,
        "profile_id": None, "enabled": False,
    })
    assert unbound.status_code == 200
    archived = client.post(
        f"/api/v1/me/llm/profiles/{admin_profile['id']}/archive?environment_id=dev"
    )
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True

    with factory() as database:
        profiles = list(database.scalars(select(LlmProfile).where(
            LlmProfile.id.in_([admin_profile["id"], member_profile["id"]])
        )).all())
        assert {row.owner_user_id for row in profiles} == {
            admin_context.user.id, member_context.user.id,
        }
        personal_bindings = list(database.scalars(select(UserLlmBinding)).all())
        assert {row.user_id for row in personal_bindings} == {
            admin_context.user.id, member_context.user.id,
        }
        cipher = load_secret_cipher(settings)
        decrypted_keys = set()
        for profile in profiles:
            secret = database.scalar(select(Secret).where(
                Secret.environment_id == "dev",
                Secret.owner_type == "llm_profile",
                Secret.owner_id == profile.id,
            ))
            decrypted_keys.add(decrypt_secret_version(
                database, cipher, secret, secret.current_version_id
            ))
        assert decrypted_keys == {admin_key_v2, member_key}
        audit_text = json.dumps([
            {"after": row.after_json, "metadata": row.metadata_json}
            for row in database.scalars(select(AuditLog)).all()
        ], ensure_ascii=False)
        assert all(key not in audit_text for key in (admin_key, admin_key_v2, member_key))


def test_signed_user_context_exchange_and_runtime_revocation(
    phase2_client,
    tmp_path: Path,
) -> None:
    """签名上下文必须绑定 Session、用户权限版本、工具、环境和任务资源。"""

    client, factory, settings = phase2_client
    _setup(client)
    signing_key = b"runtime-user-context-key-for-tests-32-bytes-minimum"
    signing_key_path = tmp_path / "user-context-signing-key"
    signing_key_path.write_bytes(signing_key)
    signing_key_path.chmod(0o600)
    settings.user_context_signing_key_file = str(signing_key_path)
    settings.user_context_ttl_seconds = 300
    settings.runtime_context_ttl_seconds = 86400
    with factory() as database:
        admin = database.scalar(select(User).where(User.username_normalized == "admin"))
        database.add(Permission(code="tool.execute", name="执行工具", resource_type="tool"))
        database.add_all([
            RoleGrant(
                role_id="role_platform_admin", permission_code="tool.execute",
                resource_type="tool", resource_id="truthy-search", created_by="test",
            ),
            RoleGrant(
                role_id="role_platform_admin", permission_code="tool.execute",
                resource_type="tool", resource_id="log-filter", created_by="test",
            ),
            ToolClient(
                id="client_runtime_truthy_dev", tool_id="truthy-search",
                environment_id="dev", token_hash=token_hash("runtime-truthy-dev-token"),
                capabilities=["runtime.context.create"], status="active",
            ),
            ToolClient(
                id="client_runtime_log_dev", tool_id="log-filter",
                environment_id="dev", token_hash=token_hash("runtime-log-dev-token"),
                capabilities=["runtime.context.create"], status="active",
            ),
            ToolClient(
                id="client_runtime_truthy_prod", tool_id="truthy-search",
                environment_id="prod", token_hash=token_hash("runtime-truthy-prod-token"),
                capabilities=["runtime.context.create"], status="active",
            ),
            Environment(id="prod", name="生产环境", sort_order=20),
        ])
        database.commit()
        admin_id = admin.id

    authorized = client.get("/api/v1/internal/authorize", headers={
        "X-Tool-ID": "truthy-search",
        "X-Original-URI": "/truthy-search/runs/run_1/process",
        "X-Original-Method": "POST",
        # 客户端伪造的旧身份 Header 不得影响服务端 Session 生成的签名主体。
        "X-Platform-User-ID": "usr_forged",
    })
    assert authorized.status_code == 204
    signed_context = authorized.headers["x-platform-user-context"]
    payload_segment, signature_segment = signed_context.split(".")
    claims = json.loads(base64.urlsafe_b64decode(
        payload_segment + "=" * (-len(payload_segment) % 4)
    ))
    assert set(claims) == {"v", "sid", "uid", "pv", "tid", "env", "iat", "exp", "nonce"}
    assert claims["uid"] == admin_id
    assert claims["tid"] == "truthy-search"
    assert claims["env"] == "dev"
    assert 0 < claims["exp"] - claims["iat"] <= 300

    exchanged = client.post(
        "/api/v1/internal/tools/truthy-search/runtime-contexts",
        headers={
            "Authorization": "Bearer runtime-truthy-dev-token",
            "X-Platform-User-Context": signed_context,
        },
        json={"resource_type": "task", "resource_id": "task_signed_context_1"},
    )
    assert exchanged.status_code == 201
    exchanged_payload = exchanged.json()
    runtime_context_id = exchanged_payload["runtime_context_id"]
    assert runtime_context_id.startswith("rtx_")
    assert exchanged_payload["tool_id"] == "truthy-search"
    assert exchanged_payload["environment_id"] == "dev"
    assert exchanged_payload["resource_snapshot"]["owner_user_id"] == admin_id
    assert signed_context not in exchanged.text

    resource_access = client.post(
        "/api/v1/internal/tools/truthy-search/resource-access/check",
        headers={
            "Authorization": "Bearer runtime-truthy-dev-token",
            "X-Platform-Resource-Context": authorized.headers[
                "x-platform-resource-context"
            ],
        },
        json={
            "action": "read",
            "resource_type": "task",
            "root_resource_id": "task_signed_context_1",
        },
    )
    assert resource_access.status_code == 200
    assert resource_access.json()["data_scope"] == "global"
    assert resource_access.json()["user_id"] == admin_id

    def canonical_token(token_claims: dict) -> str:
        payload = json.dumps(
            token_claims, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        signature = hmac.new(signing_key, payload, hashlib.sha256).digest()
        encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
        return f"{encode(payload)}.{encode(signature)}"

    tampered_claims = dict(claims, uid="usr_tampered")
    tampered_payload = json.dumps(
        tampered_claims, sort_keys=True, separators=(",", ":")
    ).encode()
    tampered = (
        base64.urlsafe_b64encode(tampered_payload).rstrip(b"=").decode()
        + "." + signature_segment
    )
    invalid = client.post(
        "/api/v1/internal/tools/truthy-search/runtime-contexts",
        headers={
            "Authorization": "Bearer runtime-truthy-dev-token",
            "X-Platform-User-Context": tampered,
        },
        json={"resource_type": "task", "resource_id": "task_tampered"},
    )
    assert invalid.status_code == 403
    assert invalid.json()["code"] == "RUNTIME_CONTEXT_INVALID"

    cross_tool = client.post(
        "/api/v1/internal/tools/log-filter/runtime-contexts",
        headers={
            "Authorization": "Bearer runtime-log-dev-token",
            "X-Platform-User-Context": signed_context,
        },
        json={"resource_type": "task", "resource_id": "task_cross_tool"},
    )
    assert cross_tool.status_code == 403
    assert cross_tool.json()["code"] == "RUNTIME_CONTEXT_INVALID"
    cross_environment = client.post(
        "/api/v1/internal/tools/truthy-search/runtime-contexts",
        headers={
            "Authorization": "Bearer runtime-truthy-prod-token",
            "X-Platform-User-Context": signed_context,
        },
        json={"resource_type": "task", "resource_id": "task_cross_environment"},
    )
    assert cross_environment.status_code == 403
    assert cross_environment.json()["code"] == "RUNTIME_CONTEXT_INVALID"

    now = int(time.time())
    expired_claims = dict(claims, iat=now - 601, exp=now - 301, nonce="expired")
    expired = client.post(
        "/api/v1/internal/tools/truthy-search/runtime-contexts",
        headers={
            "Authorization": "Bearer runtime-truthy-dev-token",
            "X-Platform-User-Context": canonical_token(expired_claims),
        },
        json={"resource_type": "task", "resource_id": "task_expired"},
    )
    assert expired.status_code == 401
    assert expired.json()["code"] == "RUNTIME_CONTEXT_EXPIRED"
    assert client.post(
        "/api/v1/internal/tools/truthy-search/runtime-contexts",
        headers={"X-Platform-User-Context": signed_context},
        json={"resource_type": "task", "resource_id": "task_no_client"},
    ).status_code == 401
    extra_identity = client.post(
        "/api/v1/internal/tools/truthy-search/runtime-contexts",
        headers={
            "Authorization": "Bearer runtime-truthy-dev-token",
            "X-Platform-User-Context": signed_context,
        },
        json={
            "resource_type": "task", "resource_id": "task_injected",
            "user_id": "usr_forged",
        },
    )
    assert extra_identity.status_code == 422

    with factory() as database:
        row = database.get(RuntimeContext, runtime_context_id)
        tool_client = database.get(ToolClient, "client_runtime_truthy_dev")
        assert row is not None
        assert (row.user_id, row.session_id, row.permission_version) == (
            claims["uid"], claims["sid"], claims["pv"],
        )
        assert auth_services.validate_runtime_context(
            database, runtime_context_id, tool_client, "truthy-search"
        ).id == runtime_context_id
        session = database.get(PlatformSession, claims["sid"])
        session.revoked_at = datetime.now(UTC)
        database.commit()
        # Execution Lease 已绑定原任务；普通会话退出不取消已派发任务。
        assert auth_services.validate_runtime_context(
            database, runtime_context_id, tool_client, "truthy-search"
        ).id == runtime_context_id

        session.revoked_at = None
        user = database.get(User, claims["uid"])
        user.permission_version += 1
        database.commit()
        # 权限版本变化只影响新请求，不能扩大或取消已有租约。
        assert auth_services.validate_runtime_context(
            database, runtime_context_id, tool_client, "truthy-search"
        ).id == runtime_context_id
        row.emergency_revoked_at = datetime.now(UTC)
        database.commit()
        with pytest.raises(PlatformError) as emergency_revoked:
            auth_services.validate_runtime_context(
                database, runtime_context_id, tool_client, "truthy-search"
            )
        assert emergency_revoked.value.code == "RUNTIME_CONTEXT_INVALID"


def test_personal_runtime_config_plans_and_materializes_fixed_user_versions(
    phase2_client,
) -> None:
    """规划阶段不得解密，物化必须按 Context 用户读取精确历史版本。"""

    client, factory, settings = phase2_client
    _setup(client)
    with factory() as database:
        admin = database.scalar(select(User).where(User.username_normalized == "admin"))
        member = User(
            id="usr_runtime_member", username="runtime-member",
            username_normalized="runtime-member", display_name="运行成员",
            password_hash="unused", status="active",
        )
        empty_user = User(
            id="usr_runtime_empty", username="runtime-empty",
            username_normalized="runtime-empty", display_name="未配置成员",
            password_hash="unused", status="active",
        )
        runtime_role = Role(id="role_runtime", name="运行角色")
        database.add_all([
            member, empty_user, runtime_role,
            Permission(code="tool.execute", name="执行工具", resource_type="tool"),
            ToolClient(
                id="client_runtime_config", tool_id="truthy-search",
                environment_id="dev", token_hash=token_hash("runtime-config-token"),
                capabilities=[
                    "config.read", "credential.status.write",
                    "credential.session.write",
                ],
                status="active",
            ),
        ])
        auth_definition = database.get(ConfigDefinition, "truthy-search.AUTH_TOKEN")
        auth_definition.value_scope = "user"
        auth_definition.credential_provider_type = "gateway_session"
        system_definition = ConfigDefinition(
            id="truthy-search.SEARCH_API_URL", key="SEARCH_API_URL",
            display_name="检索接口", description="", owner_type="tool",
            owner_id="truthy-search", group_key="general", value_type="url",
            sensitivity="normal", required=True, validation_schema={},
            apply_mode="next_task", editable=True, sort_order=1,
            value_scope="system",
        )
        database.add(system_definition)
        database.flush()
        system_release = ConfigRelease(
            id="rel_runtime_system", environment_id="dev", owner_type="tool",
            owner_id="truthy-search", version=1, revision=1, status="active",
            created_by="test", published_by="test", published_at=datetime.now(UTC),
        )
        database.add(system_release)
        database.flush()
        database.add(ConfigReleaseItem(
            release_id=system_release.id, definition_id=system_definition.id,
            value_json="https://system.example.test/search",
        ))
        legacy_secret = Secret(
            id="sec_runtime_legacy", environment_id="dev", owner_type="tool",
            owner_id="truthy-search", definition_id=auth_definition.id,
            status="missing",
        )
        database.add(legacy_secret)
        database.flush()
        cipher = load_secret_cipher(settings)
        legacy_version = replace_secret(
            database, cipher, legacy_secret,
            "legacy-global-secret-sentinel", "test",
        )
        database.flush()
        database.add_all([
            ConfigReleaseItem(
                release_id=system_release.id, definition_id=auth_definition.id,
                secret_version_id=legacy_version.id,
            ),
            ConfigActivation(
                environment_id="dev", owner_type="tool", owner_id="truthy-search",
                active_release_id=system_release.id,
            ),
            UserRole(user_id=member.id, role_id=runtime_role.id, created_by=admin.id),
            UserRole(user_id=empty_user.id, role_id=runtime_role.id, created_by=admin.id),
            RoleGrant(
                role_id="role_platform_admin", permission_code="tool.execute",
                resource_type="tool", resource_id="truthy-search", created_by="test",
            ),
            RoleGrant(
                role_id=runtime_role.id, permission_code="tool.execute",
                resource_type="tool", resource_id="truthy-search", created_by="test",
            ),
        ])
        now = datetime.now(UTC)
        sessions = {
            admin.id: database.scalar(select(PlatformSession).where(
                PlatformSession.user_id == admin.id,
            )),
            member.id: PlatformSession(
                id="session-runtime-member", token_hash="runtime-member-hash",
                csrf_hash="runtime-member-csrf", user_id=member.id,
                idle_expires_at=now + timedelta(hours=2),
                absolute_expires_at=now + timedelta(hours=4), last_seen_at=now,
            ),
            empty_user.id: PlatformSession(
                id="session-runtime-empty", token_hash="runtime-empty-hash",
                csrf_hash="runtime-empty-csrf", user_id=empty_user.id,
                idle_expires_at=now + timedelta(hours=2),
                absolute_expires_at=now + timedelta(hours=4), last_seen_at=now,
            ),
        }
        database.add_all([sessions[member.id], sessions[empty_user.id]])
        database.flush()

        credentials = {}
        personal_values = {
            admin.id: "admin-runtime-secret-v1",
            member.id: "member-runtime-secret-v1",
        }
        for suffix, user in (("admin", admin), ("member", member)):
            credential = UserCredential(
                id=f"ucred_runtime_{suffix}", user_id=user.id,
                tool_id="truthy-search", environment_id="dev",
                provider_type="gateway_session", status="healthy", current_version=1,
            )
            database.add(credential)
            database.flush()
            secret = Secret(
                id=f"sec_runtime_{suffix}", environment_id="dev",
                owner_type="user_credential", owner_id=credential.id,
                definition_id=auth_definition.id, status="missing",
            )
            database.add(secret)
            database.flush()
            secret_version = replace_secret(
                database, cipher, secret, personal_values[user.id], user.id
            )
            database.flush()
            database.add(UserCredentialItem(
                credential_id=credential.id, credential_version=1,
                key="AUTH_TOKEN", secret_version_id=secret_version.id,
            ))
            credentials[user.id] = (credential, secret)

        contexts = {}
        for suffix, user in (("admin", admin), ("member", member), ("empty", empty_user)):
            runtime_context = RuntimeContext(
                id=f"rtx_runtime_{suffix}", user_id=user.id,
                session_id=sessions[user.id].id, tool_id="truthy-search",
                environment_id="dev", permission_version=user.permission_version,
                resource_type="task", resource_id=f"task_{suffix}",
                status="active", expires_at=now + timedelta(hours=1),
            )
            database.add(runtime_context)
            contexts[user.id] = runtime_context.id
        database.commit()
        admin_id = admin.id
        member_id = member.id
        empty_id = empty_user.id

    headers = {"Authorization": "Bearer runtime-config-token"}
    public_plan = client.get(
        "/api/v1/internal/tools/truthy-search/runtime-config?include_secrets=false",
        headers=headers,
    )
    assert public_plan.status_code == 200
    assert public_plan.json()["normal"] == {
        "SEARCH_API_URL": "https://system.example.test/search"
    }
    assert public_plan.json()["secrets"] == {}
    assert "AUTH_TOKEN" not in public_plan.json()["configured_secret_keys"]
    assert "legacy-global-secret-sentinel" not in public_plan.text
    missing_context = client.get(
        "/api/v1/internal/tools/truthy-search/runtime-config?include_secrets=true",
        headers=headers,
    )
    assert missing_context.status_code == 403
    assert missing_context.json()["code"] == "RUNTIME_CONTEXT_REQUIRED"

    def plan(context_id: str):
        return client.get(
            "/api/v1/internal/tools/truthy-search/runtime-config",
            params={"include_secrets": "false", "runtime_context_id": context_id},
            headers=headers,
        )

    admin_plan = plan(contexts[admin_id])
    member_plan = plan(contexts[member_id])
    assert admin_plan.status_code == member_plan.status_code == 200
    assert admin_plan.json()["subject_user_id"] == admin_id
    assert member_plan.json()["subject_user_id"] == member_id
    assert admin_plan.json()["secrets"] == member_plan.json()["secrets"] == {}
    assert admin_plan.json()["snapshot_selector"]["credential_versions"] == {
        credentials[admin_id][0].id: 1
    }
    assert member_plan.json()["snapshot_selector"]["credential_versions"] == {
        credentials[member_id][0].id: 1
    }
    assert "legacy-global-secret-sentinel" not in admin_plan.text + member_plan.text

    empty_plan = plan(contexts[empty_id])
    assert empty_plan.status_code == 409
    assert empty_plan.json()["code"] == "PERSONAL_CREDENTIAL_NOT_CONFIGURED"

    with factory() as database:
        admin_credential = database.get(UserCredential, credentials[admin_id][0].id)
        admin_secret = database.get(Secret, credentials[admin_id][1].id)
        rotated = replace_secret(
            database, load_secret_cipher(settings), admin_secret,
            "admin-runtime-secret-v2", admin_id,
        )
        database.flush()
        admin_credential.current_version = 2
        database.add(UserCredentialItem(
            credential_id=admin_credential.id, credential_version=2,
            key="AUTH_TOKEN", secret_version_id=rotated.id,
        ))
        database.commit()

    materialized = client.post(
        "/api/v1/internal/tools/truthy-search/runtime-config/materialize",
        headers=headers,
        json={
            "runtime_context_id": contexts[admin_id],
            "snapshot_selector": admin_plan.json()["snapshot_selector"],
        },
    )
    assert materialized.status_code == 200
    assert materialized.json()["secrets"]["AUTH_TOKEN"] == "admin-runtime-secret-v1"
    assert "admin-runtime-secret-v2" not in materialized.text
    assert "legacy-global-secret-sentinel" not in materialized.text

    latest = client.get(
        "/api/v1/internal/tools/truthy-search/runtime-config",
        params={"include_secrets": "true", "runtime_context_id": contexts[admin_id]},
        headers=headers,
    )
    assert latest.status_code == 200
    assert latest.json()["secrets"]["AUTH_TOKEN"] == "admin-runtime-secret-v2"

    status_update = client.post(
        "/api/v1/internal/tools/truthy-search/credential-status",
        headers=headers,
        json={
            "runtime_context_id": contexts[admin_id],
            "provider_type": "gateway_session", "status": "expiring",
            "error_code": "REFRESH_REQUIRED",
        },
    )
    assert status_update.status_code == 200
    with factory() as database:
        assert database.get(UserCredential, credentials[admin_id][0].id).status == "expiring"
        assert database.get(UserCredential, credentials[member_id][0].id).status == "healthy"

    cross_write = client.put(
        f"/api/v1/internal/tools/truthy-search/user-credentials/{credentials[member_id][0].id}/session",
        headers=headers,
        json={
            "runtime_context_id": contexts[admin_id], "expected_version": 1,
            "values": {"AUTH_TOKEN": "cross-user-writeback-secret"},
        },
    )
    assert cross_write.status_code == 404
    assert "cross-user-writeback-secret" not in cross_write.text
    personal_write = client.put(
        f"/api/v1/internal/tools/truthy-search/user-credentials/{credentials[admin_id][0].id}/session",
        headers=headers,
        json={
            "runtime_context_id": contexts[admin_id], "expected_version": 2,
            "values": {"AUTH_TOKEN": "admin-runtime-secret-v3"},
        },
    )
    assert personal_write.status_code == 200
    with factory() as database:
        admin_credential = database.get(UserCredential, credentials[admin_id][0].id)
        member_credential = database.get(UserCredential, credentials[member_id][0].id)
        assert admin_credential.current_version == 3
        assert member_credential.current_version == 1
        item = database.scalar(select(UserCredentialItem).where(
            UserCredentialItem.credential_id == admin_credential.id,
            UserCredentialItem.credential_version == 3,
            UserCredentialItem.key == "AUTH_TOKEN",
        ))
        version = database.get(SecretVersion, item.secret_version_id)
        secret = database.get(Secret, version.secret_id)
        assert decrypt_secret_version(
            database, load_secret_cipher(settings), secret, version.id
        ) == "admin-runtime-secret-v3"
    legacy_write = client.put(
        f"/api/v1/internal/tools/truthy-search/credentials/{credentials[admin_id][0].id}/session",
        headers=headers,
        json={"expected_version": 3, "values": {"AUTH_TOKEN": "legacy-write-sentinel"}},
    )
    assert legacy_write.status_code == 410
    assert legacy_write.json()["code"] == "LEGACY_CREDENTIAL_WRITE_DISABLED"
    assert "legacy-write-sentinel" not in legacy_write.text

    tampered_selector = dict(admin_plan.json()["snapshot_selector"])
    tampered_selector["credential_versions"] = {credentials[member_id][0].id: 1}
    tampered = client.post(
        "/api/v1/internal/tools/truthy-search/runtime-config/materialize",
        headers=headers,
        json={
            "runtime_context_id": contexts[admin_id],
            "snapshot_selector": tampered_selector,
        },
    )
    assert tampered.status_code == 409
    assert tampered.json()["code"] == "RUNTIME_SNAPSHOT_INVALID"
    assert "member-runtime-secret-v1" not in tampered.text

    with factory() as database:
        runtime_context = database.get(RuntimeContext, contexts[admin_id])
        session = database.get(PlatformSession, runtime_context.session_id)
        session.revoked_at = datetime.now(UTC)
        database.commit()
    lease_survives_logout = client.post(
        "/api/v1/internal/tools/truthy-search/runtime-config/materialize",
        headers=headers,
        json={
            "runtime_context_id": contexts[admin_id],
            "snapshot_selector": admin_plan.json()["snapshot_selector"],
        },
    )
    assert lease_survives_logout.status_code == 200
    with factory() as database:
        runtime_context = database.get(RuntimeContext, contexts[admin_id])
        runtime_context.emergency_revoked_at = datetime.now(UTC)
        database.commit()
    emergency_revoked = client.post(
        "/api/v1/internal/tools/truthy-search/runtime-config/materialize",
        headers=headers,
        json={
            "runtime_context_id": contexts[admin_id],
            "snapshot_selector": admin_plan.json()["snapshot_selector"],
        },
    )
    assert emergency_revoked.status_code == 403
    assert emergency_revoked.json()["code"] == "RUNTIME_CONTEXT_INVALID"
