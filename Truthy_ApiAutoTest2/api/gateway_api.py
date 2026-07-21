"""Gateway 请求信封构造与接口调用。"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from utils.custom.assertions import assert_gateway_response
from utils.custom.http_client import HttpClient
from utils.custom.logger import get_logger
from utils.custom.config_loader import persist_session_to_dotenv
from utils.custom.runtime_context import RuntimeContext, RuntimeContextError


LOGGER = get_logger(__name__)
ONE_DAY_MS = 86_400_000
SESSION_METHODS = {"CreateAnonymousSession", "RefreshSession"}


def build_payload(
    settings: dict[str, Any],
    case: dict[str, Any],
    runtime_context: RuntimeContext | None = None,
) -> dict[str, Any]:
    """构造 MVP 规定的单子请求 Gateway 信封。

    参数说明:
        settings: 包含 ``comm`` 的完整环境配置。
        case: 包含 ``request.service_name/method_name/params`` 的用例数据。

    返回值:
        仅含 ``comm`` 和一个 ``req_0`` 子请求的字典。

    异常说明:
        ValueError: 用例缺少 service_name 或 method_name 时抛出。
    """
    request = case.get("request") or {}
    service_name = request.get("service_name")
    method_name = request.get("method_name")
    if not service_name or not method_name:
        raise ValueError("用例必须配置 request.service_name 和 request.method_name")

    client_request_id = f"crid_{time.time_ns()}"
    variables = RuntimeContext(runtime_context.as_dict() if runtime_context else {})
    variables.set("client_request_id", client_request_id)

    # 空字符串和 None 表示未配置字段，构造请求时不序列化。
    comm = {
        key: value
        for key, value in (settings.get("comm") or {}).items()
        if value is not None and value != ""
    }
    if runtime_context:
        access_token = runtime_context.get("access_token")
        user_id = runtime_context.get("user_id")
        if access_token:
            # Gateway 协议字段名为 auth_token，值来自会话响应的 access_token。
            comm["auth_token"] = access_token
        if user_id:
            comm["user_id"] = user_id
    comm["client_request_id"] = client_request_id
    return {
        "comm": comm,
        "requests": [
            {
                "id": "req_0",
                "service_name": service_name,
                "method_name": method_name,
                "params": variables.resolve(request.get("params") or {}),
            }
        ],
    }


class GatewayApi:
    """组合环境、接口配置和 HTTP 客户端完成一次 Gateway 调用。"""

    def __init__(
        self,
        settings: dict[str, Any],
        endpoint: dict[str, Any],
        http_client: HttpClient | None = None,
        runtime_context: RuntimeContext | None = None,
        session_cases: dict[str, dict[str, Any]] | None = None,
        now_ms: Callable[[], int] | None = None,
        session_env_path: Path | None = None,
    ) -> None:
        """保存调用所需配置；不在构造阶段发起网络请求。"""
        self.settings = settings
        self.endpoint = endpoint
        self.http_client = http_client or HttpClient()
        self.runtime_context = runtime_context
        self.session_cases = session_cases or {}
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.session_env_path = session_env_path

    def execute(self, case: dict[str, Any]):
        """执行请求、完成分层断言并将 YAML 声明的字段写入运行时上下文。

        参数说明:
            case: 包含 request、assert 及可选 extract 的完整用例对象。

        返回值:
            requests.Response，便于调用方继续检查原始响应。

        异常说明:
            AssertionError: 响应不符合用例断言时抛出。
            RuntimeContextError: 变量缺失或响应提取失败时抛出。
        """
        response = self.invoke(case)
        data = assert_gateway_response(response, case.get("assert") or {})
        if self.runtime_context and case.get("extract"):
            self.runtime_context.extract(data, case["extract"])
            if self._is_session_case(case):
                self._persist_session_state()
        return response

    def invoke(self, case: dict[str, Any]):
        """调用一个 YAML 用例。

        参数说明:
            case: 单接口用例数据。

        返回值:
            requests.Response，由测试层交给通用断言器处理。

        异常说明:
            ValueError: 接口配置不是 POST 时抛出；网络异常由 HttpClient 透传。
        """
        if str(self.endpoint.get("method", "")).upper() != "POST":
            raise ValueError("Gateway MVP 仅支持 POST 请求")
        request = case.get("request") or {}
        method_name = str(request.get("method_name") or "")
        if self.runtime_context and method_name not in SESSION_METHODS:
            self._ensure_session()
        return self._post(case)

    def _post(self, case: dict[str, Any]):
        """发送一次 Gateway POST，不执行会话检查，供会话接口避免递归调用。"""
        base_url = str(self.settings["gateway_base_url"]).rstrip("/")
        path = str(self.endpoint.get("path", "")).lstrip("/")
        url = f"{base_url}/{path}"
        return self.http_client.post_json(
            url=url,
            headers=self.endpoint.get("headers") or {},
            payload=build_payload(self.settings, case, self.runtime_context),
            timeout=float(self.settings.get("timeout", 15)),
        )

    def _ensure_session(self) -> None:
        """在普通请求前创建或刷新会话，刷新失败时仅回退重建一次。"""
        if not self.runtime_context:
            return
        now_ms = self.now_ms()
        refresh_before_ms = int(
            (self.settings.get("session") or {}).get(
                "refresh_before_ms",
                ONE_DAY_MS,
            )
        )
        if not self.runtime_context.access_token_needs_refresh(
            now_ms,
            refresh_before_ms,
        ):
            return

        if (
            self.runtime_context.refresh_token_is_valid(now_ms)
            and "RefreshSession" in self.session_cases
        ):
            try:
                self._execute_session_case("RefreshSession")
                return
            except (AssertionError, RuntimeContextError, requests.RequestException, ValueError) as exc:
                # 刷新失败只记录错误类型，不输出可能包含 token 的异常内容。
                LOGGER.warning("会话刷新失败，将重新创建匿名会话: %s", type(exc).__name__)

        self._execute_session_case("CreateAnonymousSession")

    def _execute_session_case(self, method_name: str) -> None:
        """执行创建或刷新会话用例并更新全部 session 字段。"""
        case = self.session_cases.get(method_name)
        if not case:
            raise RuntimeContextError(f"缺少会话用例配置: {method_name}")
        response = self._post(case)
        data = assert_gateway_response(response, case.get("assert") or {})
        extract_rules = case.get("extract") or {}
        if not extract_rules:
            raise RuntimeContextError(f"会话用例缺少 extract 配置: {method_name}")
        if not self.runtime_context:
            raise RuntimeContextError("会话运行时上下文未初始化")
        self.runtime_context.extract(data, extract_rules)
        self._persist_session_state()

    @staticmethod
    def _is_session_case(case: dict[str, Any]) -> bool:
        """判断用例是否为需要持久化会话状态的身份接口。"""
        request = case.get("request") or {}
        return str(request.get("method_name") or "") in SESSION_METHODS

    def _persist_session_state(self) -> None:
        """将本次成功提取的会话值写入 .env，避免下次运行重复创建会话。"""
        if self.runtime_context and self.session_env_path:
            persist_session_to_dotenv(self.session_env_path, self.runtime_context.as_dict())
