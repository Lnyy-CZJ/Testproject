"""Gateway 接口自动化框架的核心行为测试。"""

from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

import pytest
import requests

from api.gateway_api import GatewayApi, build_payload
from runtest import build_pytest_args
from utils.custom.assertions import assert_gateway_response
from utils.custom.config_loader import (
    load_dotenv_values,
    load_settings,
    load_yaml,
    persist_session_to_dotenv,
)
from utils.custom.http_client import HttpClient
from utils.custom.runtime_context import RuntimeContext, RuntimeContextError


class FakeResponse:
    """提供断言器所需的最小 requests.Response 接口。"""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        """返回构造响应时传入的 JSON 数据。"""
        return self._body


def _session_api_definitions() -> dict[str, dict]:
    """构造自动会话测试所需的最小 API 路由注册表。

    返回值:
        仅包含创建、刷新匿名会话路由的 API 定义，不包含 params、断言或提取规则。
    """
    return {
        "CreateAnonymousSession": {
            "id": "CreateAnonymousSession",
            "name": "创建匿名会话",
            "request": {
                "service_name": "tool.identity.IdentityService",
                "method_name": "CreateAnonymousSession",
            },
        },
        "RefreshSession": {
            "id": "RefreshSession",
            "name": "刷新匿名会话 Token",
            "request": {
                "service_name": "tool.identity.IdentityService",
                "method_name": "RefreshSession",
            },
        },
    }


def test_load_settings_merges_environment_and_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配置加载器应合并默认项、环境项和敏感环境变量。"""
    config_dir = tmp_path / "config"
    env_dir = config_dir / "env"
    env_dir.mkdir(parents=True)
    (config_dir / "settings.yaml").write_text(
        "timeout: 10\ncomm:\n  platform: ios\n  locale: zh-CN\n",
        encoding="utf-8",
    )
    (env_dir / "test.yaml").write_text(
        "gateway_base_url: http://example.test\ntimeout: 20\ncomm:\n  locale: en-US\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_TOKEN", "secret-token")
    monkeypatch.setenv("USER_ID", "user_1")
    monkeypatch.setenv("DEVICE_ID", "device_1")

    settings = load_settings("test", project_root=tmp_path)

    assert settings["gateway_base_url"] == "http://example.test"
    assert settings["timeout"] == 20
    assert settings["comm"]["platform"] == "ios"
    assert settings["comm"]["locale"] == "en-US"
    assert settings["comm"]["auth_token"] == "secret-token"


def test_load_settings_allows_runtime_session_without_startup_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """环境 YAML 已配置 device_id 时，不应强制要求启动 token 和 user_id。"""
    config_dir = tmp_path / "config"
    env_dir = config_dir / "env"
    env_dir.mkdir(parents=True)
    (config_dir / "settings.yaml").write_text(
        "timeout: 15\ncomm:\n  platform: ios\n",
        encoding="utf-8",
    )
    (env_dir / "test.yaml").write_text(
        "gateway_base_url: http://example.test\ncomm:\n  device_id: device_yaml\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    monkeypatch.delenv("USER_ID", raising=False)
    monkeypatch.delenv("DEVICE_ID", raising=False)

    settings = load_settings("test", project_root=tmp_path)

    assert settings["comm"]["device_id"] == "device_yaml"
    assert "auth_token" not in settings["comm"]
    assert "user_id" not in settings["comm"]


def test_create_anonymous_session_resolves_current_consent_policy_date() -> None:
    """内部会话策略应把当天日期解析为 Gateway 所需的 YYYY-MM-DD 参数。"""
    runtime = RuntimeContext({"consent_policy_version": date.today().isoformat()})
    gateway = GatewayApi(
        {"gateway_base_url": "http://example.test", "comm": {}},
        {"method": "POST", "path": "/gateway/invoke"},
        runtime_context=runtime,
        api_definitions=_session_api_definitions(),
    )

    case = gateway._build_session_case("CreateAnonymousSession")
    resolved_params = runtime.resolve(case["request"]["params"])

    assert resolved_params == {"consent_policy_version": date.today().isoformat()}


def test_session_values_are_loaded_from_dotenv_and_process_env_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 会话值应可复用，且终端显式环境变量拥有更高优先级。"""
    config_dir = tmp_path / "config"
    env_dir = config_dir / "env"
    env_dir.mkdir(parents=True)
    (config_dir / "settings.yaml").write_text("comm: {}\n", encoding="utf-8")
    (env_dir / "test.yaml").write_text(
        "gateway_base_url: http://example.test\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(
        "AUTH_TOKEN=file-access\nREFRESH_TOKEN=file-refresh\nUSER_ID=file-user\n"
        "DEVICE_ID=file-device\nEXPIRES_TIME=1800000000000\n"
        "REFRESH_EXPIRES_TIME=1800100000000\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_TOKEN", "process-access")

    settings = load_settings("test", project_root=tmp_path)

    assert settings["comm"]["auth_token"] == "process-access"
    assert settings["comm"]["device_id"] == "file-device"
    assert settings["runtime_session"] == {
        "access_token": "process-access",
        "refresh_token": "file-refresh",
        "user_id": "file-user",
        "device_id": "file-device",
        "expires_time": "1800000000000",
        "refresh_expires_time": "1800100000000",
    }


def test_persist_session_to_dotenv_updates_only_session_values(tmp_path: Path) -> None:
    """刷新会话后应保留 .env 中无关项，并覆盖返回的新会话字段。"""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("DEVICE_ID=device-old\nKEEP_ME=yes\n", encoding="utf-8")

    persist_session_to_dotenv(
        dotenv_path,
        {
            "access_token": "access-new",
            "refresh_token": "refresh-new",
            "user_id": "user-new",
            "expires_time": 1800000000000,
            "refresh_expires_time": 1800100000000,
        },
    )

    assert load_dotenv_values(dotenv_path) == {
        "DEVICE_ID": "device-old",
        "KEEP_ME": "yes",
        "AUTH_TOKEN": "access-new",
        "REFRESH_TOKEN": "refresh-new",
        "USER_ID": "user-new",
        "EXPIRES_TIME": "1800000000000",
        "REFRESH_EXPIRES_TIME": "1800100000000",
    }


def test_build_payload_creates_single_gateway_request() -> None:
    """请求构造器应生成一个且仅一个 req_0 子请求。"""
    settings = {
        "comm": {
            "auth_token": "token",
            "user_id": "user_1",
            "device_id": "device_1",
            "platform": "ios",
            "optional_empty": "",
        }
    }
    case = {
        "request": {
            "service_name": "tool.identity.IdentityService",
            "method_name": "GetMe",
            "params": {},
        }
    }

    payload = build_payload(settings, case)

    assert payload["comm"]["client_request_id"].startswith("crid_")
    assert "optional_empty" not in payload["comm"]
    assert payload["requests"] == [
        {
            "id": "req_0",
            "service_name": "tool.identity.IdentityService",
            "method_name": "GetMe",
            "params": {},
        }
    ]


def test_assert_gateway_response_accepts_success() -> None:
    """HTTP、Gateway 和业务子响应均成功时应返回 data。"""
    response = FakeResponse(
        200,
        {
            "code": 0,
            "message": "ok",
            "responses": [
                {
                    "id": "req_0",
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "data": {"user_id": "user_1"},
                }
            ],
        },
    )
    expected = {
        "http_status": 200,
        "gateway": {"code": 0, "message": "ok"},
        "response": {"id": "req_0", "success": True, "code": 0, "message": "ok"},
        "data_fields": ["user_id"],
    }

    assert assert_gateway_response(response, expected) == {"user_id": "user_1"}


def test_assert_gateway_response_reports_business_failure() -> None:
    """业务子响应失败时，错误信息应明确指出失败字段。"""
    response = FakeResponse(
        200,
        {
            "code": 0,
            "message": "ok",
            "responses": [
                {
                    "id": "req_0",
                    "success": False,
                    "code": 300002,
                    "message": "unauthenticated",
                    "data": {},
                }
            ],
        },
    )
    expected = {
        "http_status": 200,
        "gateway": {"code": 0, "message": "ok"},
        "response": {"id": "req_0", "success": True, "code": 0, "message": "ok"},
    }

    with pytest.raises(AssertionError, match="业务子响应字段 success"):
        assert_gateway_response(response, expected)


def test_http_client_masks_auth_token_in_error_log(caplog: pytest.LogCaptureFixture) -> None:
    """HTTP 异常日志不得输出完整 auth_token。"""

    class FailingSession:
        """模拟 requests.Session 发起请求时失败。"""

        def post(self, *args: object, **kwargs: object) -> None:
            raise requests.RequestException("network down")

    client = HttpClient(session=FailingSession())
    payload = {"comm": {"auth_token": "very-secret-token"}, "requests": []}

    with caplog.at_level(logging.ERROR), pytest.raises(requests.RequestException):
        client.post_json("http://example.test", {}, payload, 10)

    assert "very-secret-token" not in caplog.text
    assert "***" in caplog.text


def test_http_client_logs_masked_request_and_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """HTTP 调用成功时应输出脱敏请求和响应数据，便于单接口调试。"""

    class SuccessfulSession:
        """模拟返回一个成功的 Gateway 响应。"""

        def post(self, *args: object, **kwargs: object) -> FakeResponse:
            return FakeResponse(
                200,
                {
                    "code": 0,
                    "message": "ok",
                    "access_token": "response-access-secret",
                    "refresh_token": "response-refresh-secret",
                },
            )

    client = HttpClient(session=SuccessfulSession())
    payload = {
        "comm": {"auth_token": "very-secret-token", "user_id": "user_1"},
        "requests": [],
    }

    with caplog.at_level(logging.INFO):
        client.post_json(
            "http://example.test/gateway/invoke",
            {"Authorization": "secret-header"},
            payload,
            10,
        )

    assert "请求数据" in caplog.text
    assert "响应数据" in caplog.text
    assert "user_1" in caplog.text
    assert '"code": 0' in caplog.text
    assert "very-secret-token" not in caplog.text
    assert "secret-header" not in caplog.text
    assert "response-access-secret" not in caplog.text
    assert "response-refresh-secret" not in caplog.text


def test_build_pytest_args_supports_filters() -> None:
    """统一入口应把环境、模块、标签及透传参数转换为 pytest 参数。"""
    args = build_pytest_args(
        env="test",
        module="single_api",
        tag="smoke",
        extra_args=["-x", "-vv"],
    )

    assert args == [
        "test_cases",
        "--env=test",
        "-k",
        "single_api",
        "-m",
        "smoke",
        "-x",
        "-vv",
    ]


def test_runtime_context_resolves_nested_variables_and_preserves_types() -> None:
    """完整变量占位符应保留字典和数字类型，并支持嵌套请求参数。"""
    context = RuntimeContext(
        {
            "task_id": "task_1",
            "page": {"page_size": 10},
            "suffix": 7,
        }
    )

    resolved = context.resolve(
        {
            "task_id": "{{task_id}}",
            "page": "{{page}}",
            "labels": ["task={{task_id}}", "{{suffix}}"],
        }
    )

    assert resolved == {
        "task_id": "task_1",
        "page": {"page_size": 10},
        "labels": ["task=task_1", 7],
    }


def test_runtime_context_reports_missing_variable() -> None:
    """未定义变量必须在发请求前给出明确错误。"""
    with pytest.raises(RuntimeContextError, match="candidate_id"):
        RuntimeContext().resolve({"candidate_id": "{{candidate_id}}"})


def test_runtime_context_extracts_first_candidate_id() -> None:
    """数组路径应能提取 ListTaskCandidates 返回的首个候选 ID。"""
    context = RuntimeContext()

    context.extract(
        {"items": [{"candidate_id": "candidate_1"}]},
        {"candidate_id": "$.items[0].candidate_id"},
    )

    assert context.get("candidate_id") == "candidate_1"


def test_access_token_refreshes_when_less_than_one_day_remains() -> None:
    """毫秒过期时间距当前不足一天时应判定 access token 需要刷新。"""
    now_ms = int(time.time() * 1000)
    context = RuntimeContext(
        {
            "access_token": "access-old",
            "expires_time": now_ms + 86_400_000 - 1,
            "refresh_token": "refresh-old",
            "refresh_expires_time": now_ms + 172_800_000,
        }
    )

    assert context.access_token_needs_refresh(now_ms, 86_400_000)
    assert context.refresh_token_is_valid(now_ms)


def test_access_token_does_not_refresh_at_one_day_boundary() -> None:
    """剩余时间恰好一天时仍可继续使用当前 access token。"""
    now_ms = int(time.time() * 1000)
    context = RuntimeContext(
        {
            "access_token": "access-current",
            "expires_time": now_ms + 86_400_000,
        }
    )

    assert not context.access_token_needs_refresh(now_ms, 86_400_000)


def test_gateway_api_refreshes_session_before_normal_request(tmp_path: Path) -> None:
    """临期 token 应按 API 定义刷新，并更新上下文及持久化会话数据。"""
    now_ms = 1_800_000_000_000
    context = RuntimeContext(
        {
            "access_token": "access-old",
            "expires_time": now_ms + 1,
            "refresh_token": "refresh-old",
            "refresh_expires_time": now_ms + 172_800_000,
            "user_id": "user_1",
        }
    )

    class QueueHttpClient:
        """依次返回刷新响应和目标接口响应，并记录发送请求。"""

        def __init__(self) -> None:
            self.payloads: list[dict] = []
            self.responses = [
                FakeResponse(
                    200,
                    {
                        "code": 0,
                        "message": "ok",
                        "responses": [
                            {
                                "id": "req_0",
                                "success": True,
                                "code": 0,
                                "message": "ok",
                                "data": {
                                    "access_token": "access-new",
                                    "expires_time": now_ms + 604_800_000,
                                    "refresh_token": "refresh-new",
                                    "refresh_expires_time": now_ms + 1_209_600_000,
                                    "user_id": "user_1",
                                },
                            }
                        ],
                    },
                ),
                FakeResponse(
                    200,
                    {
                        "code": 0,
                        "message": "ok",
                        "responses": [
                            {
                                "id": "req_0",
                                "success": True,
                                "code": 0,
                                "message": "ok",
                                "data": {"user_id": "user_1"},
                            }
                        ],
                    },
                ),
            ]

        def post_json(self, **kwargs: object) -> FakeResponse:
            self.payloads.append(kwargs["payload"])  # type: ignore[arg-type]
            return self.responses.pop(0)

    target_case = {
        "request": {
            "service_name": "tool.identity.IdentityService",
            "method_name": "GetMe",
            "params": {},
        },
        "assert": {
            "http_status": 200,
            "gateway": {"code": 0},
            "response": {"id": "req_0", "success": True, "code": 0},
        },
    }
    client = QueueHttpClient()
    gateway = GatewayApi(
        {"gateway_base_url": "http://example.test", "comm": {}},
        {"method": "POST", "path": "/gateway/invoke"},
        http_client=client,  # type: ignore[arg-type]
        runtime_context=context,
        api_definitions=_session_api_definitions(),
        now_ms=lambda: now_ms,
        session_env_path=tmp_path / ".env",
    )

    gateway.execute(target_case)

    assert client.payloads[0]["requests"][0]["method_name"] == "RefreshSession"
    assert client.payloads[0]["requests"][0]["params"] == {
        "refresh_token": "refresh-old"
    }
    assert client.payloads[1]["comm"]["auth_token"] == "access-new"
    assert context.get("refresh_token") == "refresh-new"
    assert "AUTH_TOKEN=access-new" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_gateway_api_recreates_session_when_refresh_fails() -> None:
    """刷新接口失败时应只回退一次 CreateAnonymousSession。"""
    now_ms = 1_800_000_000_000
    context = RuntimeContext(
        {
            "access_token": "access-old",
            "expires_time": now_ms + 1,
            "refresh_token": "refresh-old",
            "refresh_expires_time": now_ms + 172_800_000,
        }
    )

    class RecoveryGateway(GatewayApi):
        """记录会话分支并模拟刷新失败、重建成功。"""

        def __init__(self) -> None:
            super().__init__(
                {"gateway_base_url": "http://example.test", "comm": {}},
                {"method": "POST", "path": "/gateway/invoke"},
                runtime_context=context,
                api_definitions=_session_api_definitions(),
                now_ms=lambda: now_ms,
            )
            self.session_calls: list[str] = []

        def _execute_session_api(self, method_name: str) -> None:
            """记录会话 API ID，刷新失败时模拟框架的创建会话回退。"""
            self.session_calls.append(method_name)
            if method_name == "RefreshSession":
                raise AssertionError("refresh failed")
            context.update(
                {
                    "access_token": "access-created",
                    "expires_time": now_ms + 604_800_000,
                    "refresh_token": "refresh-created",
                    "refresh_expires_time": now_ms + 1_209_600_000,
                    "user_id": "user_1",
                }
            )

    gateway = RecoveryGateway()

    gateway._ensure_session()

    assert gateway.session_calls == ["RefreshSession", "CreateAnonymousSession"]
    assert context.get("access_token") == "access-created"


@pytest.mark.parametrize(
    "api_id",
    ["CreateAnonymousSession", "RefreshSession"],
)
def test_gateway_api_reports_missing_session_api_id(api_id: str) -> None:
    """内部会话缺少任一路由定义时，错误必须包含对应 API ID。"""
    gateway = GatewayApi(
        {"gateway_base_url": "http://example.test", "comm": {}},
        {"method": "POST", "path": "/gateway/invoke"},
        runtime_context=RuntimeContext(),
        api_definitions={},
    )

    with pytest.raises(RuntimeContextError, match=api_id):
        gateway._build_session_case(api_id)


def test_http_client_put_bytes_uses_extracted_upload_headers() -> None:
    """对象存储 PUT 应原样使用 PrepareMediaUpload 返回的上传请求头。"""

    class PutSession:
        """记录 PUT 参数的 requests.Session 替身。"""

        def __init__(self) -> None:
            self.call: dict | None = None

        def put(self, **kwargs: object) -> FakeResponse:
            self.call = kwargs
            return FakeResponse(200, {})

    session = PutSession()
    client = HttpClient(session=session)
    headers = {"Content-Length": "3", "Content-Type": "image/jpeg"}

    response = client.put_bytes(
        url="https://upload.example/file",
        headers=headers,
        content=b"abc",
        timeout=15,
    )

    assert response.status_code == 200
    assert session.call == {
        "url": "https://upload.example/file",
        "headers": headers,
        "data": b"abc",
        "timeout": 15,
    }
