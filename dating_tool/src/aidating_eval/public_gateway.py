"""公开 App Gateway 请求信封和响应解析。"""

from collections.abc import Mapping
from typing import Any, Protocol

from aidating_eval.errors import BusinessError, ContractError


class JsonTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
    ) -> dict[str, Any]: ...


class PublicGatewayClient:
    """构造单子请求公开信封；access token 仅进入 ``comm``。"""

    def __init__(
        self,
        transport: JsonTransport,
        url: str,
        *,
        device_id: str,
        platform: str,
        app_version: str,
        locale: str,
        timezone: str,
        country: str,
        app_package: str,
    ) -> None:
        self.transport = transport
        self.url = url
        self._comm = {
            "device_id": device_id,
            "platform": platform,
            "app_version": app_version,
            "locale": locale,
            "timezone": timezone,
            "country": country,
            "app_package": app_package,
        }

    @classmethod
    def example_for_test(cls, transport: JsonTransport) -> "PublicGatewayClient":
        """返回不含真实身份的完整测试客户端。"""

        return cls(
            transport,
            "https://gateway.test/invoke",
            device_id="test-device",
            platform="ios",
            app_version="1.0.0",
            locale="en-US",
            timezone="UTC+08:00",
            country="CN",
            app_package="com.example.dating",
        )

    def call(
        self,
        service_name: str,
        method_name: str,
        params: Mapping[str, Any],
        request_id: str,
        access_token: str | None,
    ) -> dict[str, Any]:
        """调用一个公开方法并返回 ``responses[0].data``。"""

        forbidden = {"app_id", "user_id"} & set(params)
        if forbidden:
            raise ContractError("PUBLIC_PARAMS_CONTAIN_RESERVED_IDENTITY")
        comm = dict(self._comm)
        if access_token:
            comm["auth_token"] = access_token
        body = {
            "comm": comm,
            "execution": {"mode": "sequential", "stop_on_error": True},
            "requests": [
                {
                    "id": request_id,
                    "service_name": service_name,
                    "method_name": method_name,
                    "params": dict(params),
                }
            ],
        }
        response = self.transport.request_json(
            "POST",
            self.url,
            headers={"Content-Type": "application/json"},
            json_body=body,
        )
        if response.get("code") != 0:
            raise ContractError("PUBLIC_TOP_LEVEL_CODE_NON_ZERO")
        sub = _single_response(response)
        if sub.get("id") != request_id:
            raise ContractError("PUBLIC_RESPONSE_ID_MISMATCH")
        return _parse_subresponse(sub)


def _single_response(response: Mapping[str, Any]) -> Mapping[str, Any]:
    values = response.get("responses")
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ContractError("RESPONSES_MUST_CONTAIN_EXACTLY_ONE_OBJECT")
    return values[0]


def _parse_subresponse(sub: Mapping[str, Any]) -> dict[str, Any]:
    success = sub.get("success")
    data = sub.get("data", {})
    if not isinstance(data, dict):
        raise ContractError("RESPONSE_DATA_MUST_BE_OBJECT")
    if success is True:
        if sub.get("code", 0) != 0:
            raise ContractError("SUCCESS_RESPONSE_CODE_NON_ZERO")
        return dict(data)
    if success is not False:
        raise ContractError("RESPONSE_SUCCESS_MUST_BE_BOOLEAN")
    code = sub.get("business_error_code") or data.get("error_code")
    if not isinstance(code, str) or not code:
        raise ContractError("BUSINESS_ERROR_CODE_MISSING")
    retry_after = data.get("retry_after_seconds")
    if retry_after is not None and not isinstance(retry_after, (int, float)):
        raise ContractError("RETRY_AFTER_SECONDS_INVALID")
    task_id = data.get("task_id")
    raise BusinessError(
        code,
        data=dict(data),
        retryable=data.get("retryable") is True,
        retry_after_seconds=float(retry_after) if retry_after is not None else None,
        task_id_to_cleanup=task_id if isinstance(task_id, str) else None,
    )
