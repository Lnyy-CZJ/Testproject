"""Gateway 信封模型、响应解析及有限重试测试。"""

from typing import Any

import pytest
import requests
from pydantic import ValidationError

from framework.client.gateway_client import GatewayClient
from framework.config import Settings
from framework.models.envelope import CommContext, GatewayResponse, build_gateway_envelope


class _FakeResponse:
    """提供 GatewayClient 所需最小 requests.Response 行为。"""

    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self) -> None:
        if not 200 <= self.status_code < 300:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _FakeSession:
    """按给定结果序列响应并记录请求参数。"""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _NoopRaiseResponse(_FakeResponse):
    """模拟 requests 对 3xx 不主动抛错的真实行为。"""

    def raise_for_status(self) -> None:
        return None


def _success_payload() -> dict[str, Any]:
    return {
        "code": 0,
        "message": "OK",
        "request_id": "gw-1",
        "trace_id": "trace-1",
        "new_top_field": "compatible",
        "responses": [
            {
                "id": "req_0",
                "code": 0,
                "message": "OK",
                "success": True,
                "business_error_code": "",
                "http_status": 200,
                "data": {"content_version": "v1"},
                "new_sub_field": 1,
            }
        ],
    }


def test_envelope_omits_user_id_and_optional_secrets() -> None:
    envelope = build_gateway_envelope(
        service_name="tool.people_insight.HomeService",
        method_name="GetHomeContent",
        params={"locale": "en-US"},
        device_id="device-1",
        platform="ios",
        app_version="1.0.0",
        locale="zh-CN",
        timezone="Asia/Shanghai",
        trace_id="trace-1",
    )
    dumped = envelope.model_dump(exclude_none=True)

    assert "user_id" not in dumped["comm"]
    assert "auth_token" not in dumped["comm"]
    assert dumped["requests"][0]["id"] == "req_0"


def test_response_parsing_allows_server_extensions() -> None:
    response = GatewayResponse.model_validate(_success_payload())

    assert response.new_top_field == "compatible"
    assert response.responses[0].new_sub_field == 1


def test_comm_context_allows_protocol_extension_fields() -> None:
    comm = CommContext(
        device_id="device-1",
        trace_id="trace-1",
        platform="ios",
        app_version="1.0.0",
        locale="zh-CN",
        timezone="Asia/Shanghai",
        install_id="install-1",
    )

    assert comm.install_id == "install-1"


def test_retry_reuses_exact_request_body_and_id() -> None:
    session = _FakeSession(
        [
            _FakeResponse(503, {"message": "temporary"}),
            requests.ConnectionError("connect failed"),
            _FakeResponse(200, _success_payload()),
        ]
    )
    client = GatewayClient(
        Settings(base_url="https://gateway.example.test"),
        session=session,
        sleep=lambda _: None,
    )

    response = client.invoke(
        "tool.people_insight.HomeService",
        "GetHomeContent",
        {"locale": "en-US"},
        client_request_id="stable-crid",
    )

    assert response.http_status == 200
    assert len(session.calls) == 3
    assert all(call["timeout"] == (5.0, 15.0) for call in session.calls)
    assert all(call["json"] == session.calls[0]["json"] for call in session.calls)
    assert all(call["json"]["comm"]["client_request_id"] == "stable-crid" for call in session.calls)


def test_read_timeout_is_not_retried() -> None:
    session = _FakeSession([requests.ReadTimeout("slow")])
    diagnostics: list[dict[str, Any]] = []
    client = GatewayClient(
        Settings(),
        session=session,
        sleep=lambda _: None,
        diagnostic_hook=diagnostics.append,
    )

    with pytest.raises(requests.ReadTimeout):
        client.invoke("svc", "Method", {"refresh_token": "read-secret"})
    assert len(session.calls) == 1
    assert len(diagnostics) == 1
    assert diagnostics[0]["error_type"] == "ReadTimeout"
    assert "read-secret" not in str(diagnostics)


def test_diagnostic_hook_receives_only_redacted_payload() -> None:
    payload = _success_payload()
    payload["responses"][0]["data"] = {"user_id": "u-secret"}
    diagnostics: list[dict[str, Any]] = []
    client = GatewayClient(
        Settings(auth_token="token-secret"),
        session=_FakeSession([_FakeResponse(200, payload)]),
        diagnostic_hook=diagnostics.append,
    )

    client.invoke("svc", "Method", {})

    serialized = str(diagnostics[0])
    assert "token-secret" not in serialized
    assert "u-secret" not in serialized
    assert diagnostics[0]["http_status"] == 200


def test_gateway_diagnostic_path_masks_feedback_media_identifiers() -> None:
    """真实 Gateway 诊断路径必须整体遮盖反馈截图和媒体 ID 数组。"""
    diagnostics: list[dict[str, Any]] = []
    client = GatewayClient(
        Settings(),
        session=_FakeSession([_FakeResponse(200, _success_payload())]),
        diagnostic_hook=diagnostics.append,
    )

    client.invoke(
        "tool.people_insight.ReportService",
        "SubmitFeedback",
        {
            "screenshot_media_asset_id": "media-screen-secret",
            "media_asset_ids": ["media-one-secret", "media-two-secret"],
        },
        auth_token="access-secret",
    )

    serialized = str(diagnostics)
    assert "access-secret" not in serialized
    assert "media-screen-secret" not in serialized
    assert "media-one-secret" not in serialized
    assert "media-two-secret" not in serialized
    params = diagnostics[0]["request"]["requests"][0]["params"]
    assert params["screenshot_media_asset_id"] == "***REDACTED***"
    assert params["media_asset_ids"] == "***REDACTED***"


def test_non_local_http_rejects_credentials_before_network() -> None:
    session = _FakeSession([_FakeResponse(200, _success_payload())])
    client = GatewayClient(
        Settings(base_url="http://gateway.example.test", auth_token="token-secret"),
        session=session,
    )

    with pytest.raises(ValueError, match="HTTPS"):
        client.invoke("svc", "Method", {})

    assert session.calls == []


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://gateway.example.test",
        "https://user:password@gateway.example.test",
        "http://user:password@127.0.0.1:8000",
    ],
)
def test_gateway_rejects_unsupported_scheme_and_userinfo_before_network(
    base_url: str,
) -> None:
    """Gateway 仅允许远程 HTTPS 或回环 HTTP，且 URL 不得携带 userinfo。"""
    session = _FakeSession([_FakeResponse(200, _success_payload())])
    client = GatewayClient(Settings(base_url=base_url), session=session)

    with pytest.raises(ValueError):
        client.invoke("svc", "Method", {})

    assert session.calls == []


@pytest.mark.parametrize("status_code", [300, 307, 308, 399])
def test_gateway_rejects_redirect_without_following_second_host(
    status_code: int,
) -> None:
    """重定向响应必须作为单次 HTTP 失败处理，不允许 requests 跟随到其他主机。"""
    session = _FakeSession(
        [
            _NoopRaiseResponse(status_code, {"location": "https://evil.example.test"}),
            _FakeResponse(200, _success_payload()),
        ]
    )
    client = GatewayClient(
        Settings(base_url="https://gateway.example.test"), session=session
    )

    with pytest.raises(requests.HTTPError):
        client.invoke("svc", "Method", {})

    assert len(session.calls) == 1
    assert session.calls[0]["allow_redirects"] is False


def test_gateway_read_timeout_override_is_bounded_by_configuration() -> None:
    """调用方剩余预算可缩短 read timeout，但不能放大配置超时。"""
    session = _FakeSession(
        [_FakeResponse(200, _success_payload()), _FakeResponse(200, _success_payload())]
    )
    client = GatewayClient(
        Settings(
            base_url="https://gateway.example.test",
            connect_timeout=5,
            read_timeout=15,
        ),
        session=session,
    )

    client.invoke("svc", "Method", {}, read_timeout=4.5)
    client.invoke("svc", "Method", {}, read_timeout=30)

    assert session.calls[0]["timeout"][0] == pytest.approx(4.5, abs=0.01)
    assert session.calls[0]["timeout"][1] == pytest.approx(4.5, abs=0.01)
    assert session.calls[1]["timeout"] == (5.0, 15.0)


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"refresh_token": "refresh-secret"},
        {"google_purchase_token": "purchase-secret"},
    ],
)
def test_non_local_http_is_rejected_even_for_anonymous_or_sensitive_params(
    params: dict[str, Any],
) -> None:
    session = _FakeSession([_FakeResponse(200, _success_payload())])
    client = GatewayClient(
        Settings(base_url="http://gateway.example.test"),
        session=session,
    )

    with pytest.raises(ValueError, match="HTTPS"):
        client.invoke("svc", "Method", params, auth_token=None)

    assert session.calls == []


def test_explicit_anonymous_does_not_inherit_default_token() -> None:
    session = _FakeSession([_FakeResponse(200, _success_payload())])
    client = GatewayClient(Settings(auth_token="token-secret"), session=session)

    client.invoke("svc", "Method", {}, auth_token=None)

    assert "auth_token" not in session.calls[0]["json"]["comm"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("code", "0"),
        ("sub_code", "0"),
        ("success", "false"),
        ("http_status", "200"),
    ],
)
def test_response_key_fields_reject_coerced_strings(field: str, value: str) -> None:
    payload = _success_payload()
    target = payload if field == "code" else payload["responses"][0]
    target["code" if field == "sub_code" else field] = value

    with pytest.raises(ValidationError):
        GatewayResponse.model_validate(payload)


def test_final_retryable_http_failure_emits_redacted_diagnostic() -> None:
    diagnostics: list[dict[str, Any]] = []
    session = _FakeSession(
        [_FakeResponse(503, {"auth_token": "response-secret"}) for _ in range(3)]
    )
    client = GatewayClient(
        Settings(base_url="https://gateway.example.test", auth_token="request-secret"),
        session=session,
        sleep=lambda _: None,
        diagnostic_hook=diagnostics.append,
    )

    with pytest.raises(requests.HTTPError):
        client.invoke("svc", "Method", {})

    assert len(diagnostics) == 1
    assert diagnostics[0]["http_status"] == 503
    assert "request-secret" not in str(diagnostics)
    assert "response-secret" not in str(diagnostics)


def test_connection_retry_exhaustion_emits_diagnostic() -> None:
    diagnostics: list[dict[str, Any]] = []
    client = GatewayClient(
        Settings(base_url="https://gateway.example.test"),
        session=_FakeSession([requests.ConnectionError("offline") for _ in range(3)]),
        sleep=lambda _: None,
        diagnostic_hook=diagnostics.append,
    )

    with pytest.raises(requests.ConnectionError):
        client.invoke("svc", "Method", {})

    assert len(diagnostics) == 1
    assert diagnostics[0]["error_type"] == "ConnectionError"


@pytest.mark.parametrize(
    "payload,error_type",
    [
        (ValueError("invalid json"), "ValueError"),
        ({"code": 0}, "ValidationError"),
    ],
)
def test_response_parse_failures_emit_diagnostic(payload: Any, error_type: str) -> None:
    diagnostics: list[dict[str, Any]] = []
    client = GatewayClient(
        Settings(base_url="https://gateway.example.test"),
        session=_FakeSession([_FakeResponse(200, payload)]),
        diagnostic_hook=diagnostics.append,
    )

    with pytest.raises((ValueError, ValidationError)):
        client.invoke("svc", "Method", {})

    assert len(diagnostics) == 1
    assert diagnostics[0]["error_type"] == error_type
