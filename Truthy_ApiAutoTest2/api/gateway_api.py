"""Gateway 请求信封构造与接口调用。"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from utils.custom.assertions import assert_gateway_response
from utils.custom.api_loader import build_execution_case
from utils.custom.config_loader import persist_session_to_dotenv
from utils.custom.http_client import HttpClient
from utils.custom.logger import get_logger
from utils.custom.runtime_context import RuntimeContext, RuntimeContextError


LOGGER = get_logger(__name__)
SESSION_REFRESH_WINDOW_MS = 7_200_000
SESSION_METHODS = {"CreateAnonymousSession", "RefreshSession"}
# 这些字段的生命周期属于单次任务或当前会话，不能由 Release 静态配置决定。
# 即使旧版本或异常客户端曾把它们写入 comm，也要在请求边界再次剥离，再由
# RuntimeContext 和本次调用生成的 request id 覆盖，形成平台校验之外的防线。
RUNTIME_COMM_KEYS = frozenset({"auth_token", "user_id", "client_request_id"})
SESSION_EXTRACT_RULES = {
    "access_token": "$.access_token",
    "expires_time": "$.expires_time",
    "refresh_token": "$.refresh_token",
    "refresh_expires_time": "$.refresh_expires_time",
    "user_id": "$.user_id",
}
SESSION_PROTOCOLS = {
    "CreateAnonymousSession": {
        "params": {"consent_policy_version": "{{consent_policy_version}}"},
        "data_fields": [
            "access_token",
            "expires_time",
            "is_new_user",
            "refresh_expires_time",
            "refresh_token",
            "user_id",
        ],
    },
    "RefreshSession": {
        "params": {"refresh_token": "{{refresh_token}}"},
        "data_fields": [
            "access_token",
            "expires_time",
            "refresh_expires_time",
            "refresh_token",
            "user_id",
        ],
    },
}


def build_payload(
    settings: dict[str, Any],
    case: dict[str, Any],
    runtime_context: RuntimeContext | None = None,
    comm_overrides: dict[str, Any] | None = None,
    include_runtime_session: bool = True,
) -> dict[str, Any]:
    """构造 MVP 规定的单子请求 Gateway 信封。

    参数说明:
        settings: 包含 ``comm`` 的完整环境配置。
        case: 包含 ``request.service_name/method_name/params`` 的用例数据。
        runtime_context: 可选运行时变量，用于解析请求参数与 comm 占位符。
        comm_overrides: 可选完整 comm 覆盖，用于不同 Gateway 的客户端标识。
        include_runtime_session: 是否将普通用户会话字段写入 comm。

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
    comm_source = comm_overrides if comm_overrides is not None else settings.get("comm") or {}
    comm = {
        key: value
        for key, value in comm_source.items()
        if key not in RUNTIME_COMM_KEYS and value is not None and value != ""
    }
    comm = variables.resolve(comm)
    if runtime_context and include_runtime_session:
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
        api_definitions: dict[str, dict[str, Any]] | None = None,
        now_ms: Callable[[], int] | None = None,
        session_env_path: Path | None = None,
        session_state_writer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """保存 Gateway 调用及自动会话所需配置。

        参数说明:
            settings: 当前环境配置。
            endpoint: Gateway 固定 HTTP 端点配置。
            http_client: 可选 HTTP 客户端，未提供时创建默认客户端。
            runtime_context: 可选运行时变量上下文。
            api_definitions: 以 API ID 索引的路由定义；自动会话只从中读取路由。
            now_ms: 可选当前毫秒时间函数，主要用于稳定测试。
            session_env_path: 会话成功后需要更新的可选 ``.env`` 路径。

        返回值:
            无。构造阶段不会发起网络请求。
        """
        self.settings = settings
        self.endpoint = endpoint
        self.http_client = http_client or HttpClient()
        self.runtime_context = runtime_context
        self.api_definitions = api_definitions or {}
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.session_env_path = session_env_path
        self.session_state_writer = session_state_writer

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
            self.persist_session_state_for_case(case)
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
        request = case.get("request") or {}
        method_name = str(request.get("method_name") or "")
        transport = case.get("transport") or {}
        requires_session = bool(transport.get("requires_session", True))
        if self.runtime_context and requires_session and method_name not in SESSION_METHODS:
            self._ensure_session()
        return self._post(case)

    def _post(self, case: dict[str, Any]):
        """发送一次 Gateway POST，不执行会话检查，供会话接口避免递归调用。"""
        transport = case.get("transport") or {}
        endpoint = self._resolve_endpoint(str(transport.get("target") or "default"))
        base_url = str(endpoint["base_url"]).rstrip("/")
        path = str(endpoint.get("path", "")).lstrip("/")
        url = f"{base_url}/{path}"
        return self.http_client.post_json(
            url=url,
            headers=endpoint.get("headers") or {},
            payload=build_payload(
                self.settings,
                case,
                self.runtime_context,
                comm_overrides=transport.get("comm"),
                include_runtime_session=bool(transport.get("requires_session", True)),
            ),
            timeout=float(self.settings.get("timeout", 15)),
        )

    def _resolve_endpoint(self, target: str) -> dict[str, Any]:
        """解析默认或命名 Gateway 目标，并在请求前校验传输配置。"""
        if target == "default":
            endpoint = {**self.endpoint, "base_url": self.settings["gateway_base_url"]}
        else:
            endpoint = (self.settings.get("gateway_targets") or {}).get(target)
        if not isinstance(endpoint, dict):
            raise ValueError(f"未配置 Gateway 目标: {target}")
        if str(endpoint.get("method", "")).upper() != "POST":
            raise ValueError(f"Gateway 目标 {target} 仅支持 POST")
        if not endpoint.get("base_url") or not endpoint.get("path"):
            raise ValueError(f"Gateway 目标 {target} 缺少 base_url 或 path")
        return endpoint

    def _ensure_session(self) -> None:
        """按两小时临期边界复用、刷新或重建会话。

        未过期且剩余时间大于两小时直接复用；剩余时间不超过两小时才尝试
        RefreshSession；已经到期或缺少有效过期时间则直接执行
        CreateAnonymousSession。临期刷新失败时只回退重建一次。
        """
        if not self.runtime_context:
            return
        now_ms = self.now_ms()
        refresh_before_ms = int(
            (self.settings.get("session") or {}).get(
                "refresh_before_ms",
                SESSION_REFRESH_WINDOW_MS,
            )
        )
        access_token_status = self.runtime_context.access_token_status(
            now_ms,
            refresh_before_ms,
        )
        if access_token_status == "valid":
            return

        if (
            access_token_status == "refresh"
            and self.runtime_context.refresh_token_is_valid(now_ms)
            and "RefreshSession" in self.api_definitions
        ):
            try:
                self._execute_session_api("RefreshSession")
                return
            except (AssertionError, RuntimeContextError, requests.RequestException, ValueError) as exc:
                # 用户要求保留原始排障信息，异常类型与消息均写入执行日志。
                LOGGER.warning(
                    "会话刷新失败，将重新创建匿名会话: %s: %s",
                    type(exc).__name__,
                    exc,
                )

        self._execute_session_api("CreateAnonymousSession")

    def _build_session_case(self, api_id: str) -> dict[str, Any]:
        """用 API 路由和框架协议组装内部会话请求。

        参数说明:
            api_id: 会话 API ID，仅支持 ``CreateAnonymousSession`` 或
                ``RefreshSession``。

        返回值:
            可直接交给 Gateway 执行层的完整临时 case。

        异常说明:
            RuntimeContextError: 会话协议或对应 API 定义不存在时抛出，错误中包含
                API ID，便于定位迁移遗漏。
            ApiConfigError: API 路由格式不合法时由组装器抛出。
        """
        protocol = SESSION_PROTOCOLS.get(api_id)
        if not protocol:
            raise RuntimeContextError(f"不支持的会话 API: {api_id}")
        api_definition = self.api_definitions.get(api_id)
        if not api_definition:
            raise RuntimeContextError(f"缺少会话 API 定义: {api_id}")
        assertions = {
            "http_status": 200,
            "gateway": {"code": 0, "message": "ok"},
            "response": {
                "id": "req_0",
                "success": True,
                "code": 0,
                "message": "ok",
            },
            "data_fields": protocol["data_fields"],
        }
        return build_execution_case(
            api_definition,
            protocol["params"],
            assertions,
            extract=SESSION_EXTRACT_RULES,
            name=f"框架自动会话: {api_id}",
        )

    def _execute_session_api(self, api_id: str) -> None:
        """执行内部会话 API，并更新运行时上下文及持久化状态。

        参数说明:
            api_id: 需要执行的会话 API ID。

        返回值:
            无。成功后的 token、过期时间和 user_id 写入运行时上下文。

        异常说明:
            RuntimeContextError: API 定义缺失、上下文未初始化或提取失败时抛出。
            AssertionError: 会话响应不符合框架成功协议时抛出。
        """
        case = self._build_session_case(api_id)
        response = self._post(case)
        data = assert_gateway_response(response, case.get("assert") or {})
        if not self.runtime_context:
            raise RuntimeContextError("会话运行时上下文未初始化")
        self.runtime_context.extract(data, case["extract"])
        self._persist_session_state()

    @staticmethod
    def _is_session_case(case: dict[str, Any]) -> bool:
        """判断用例是否为需要持久化会话状态的身份接口。"""
        request = case.get("request") or {}
        return str(request.get("method_name") or "") in SESSION_METHODS

    def _persist_session_state(self) -> None:
        """将本次成功提取的会话值写入 .env，避免下次运行重复创建会话。"""
        if not self.runtime_context:
            return
        values = self.runtime_context.as_dict()
        if self.session_state_writer is not None:
            self.session_state_writer(values)
        elif self.session_env_path:
            persist_session_to_dotenv(self.session_env_path, values)

    def persist_session_state_for_case(self, case: dict[str, Any]) -> None:
        """在显式会话 Case 已完成响应提取后持久化当前完整会话。

        单接口执行由 :meth:`execute` 调用；FlowRunner 会先按 Flow 的 extract
        规则更新独立上下文，再调用本方法。这样两条执行路径共享同一判断，且
        平台 CAS writer 只在成功的 CreateAnonymousSession/RefreshSession 后
        触发，不会把半成品会话写回唯一真源。

        参数说明:
            case: 已成功完成协议断言和变量提取的执行 Case。

        返回值:
            无。非会话 Case 不执行任何写入。
        """

        if self._is_session_case(case):
            self._persist_session_state()
