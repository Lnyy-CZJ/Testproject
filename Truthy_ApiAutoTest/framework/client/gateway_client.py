"""Gateway 唯一 HTTP 调用入口。"""

from __future__ import annotations

import time
from ipaddress import ip_address
from collections.abc import Callable
import math
from typing import Any
from urllib.parse import urlsplit

import requests
from pydantic import ValidationError

from framework.config import Settings
from framework.models.envelope import GatewayResponse, build_gateway_envelope
from framework.security.redactor import Redactor


_INHERIT_DEFAULT_AUTH = object()


def _is_local_http_url(url: str) -> bool:
    """判断 HTTP URL 是否指向 localhost 或回环地址。"""
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "http":
        return False
    hostname = parsed.hostname or ""
    if hostname.lower() == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_gateway_url(url: str) -> None:
    """验证 Gateway URL 只使用安全传输协议且不携带 userinfo。

    参数说明:
        url: 已拼接固定 ``/gateway/invoke`` 路径的完整请求 URL。
    返回值:
        无；URL 满足远程 HTTPS 或回环 HTTP 约束时正常返回。
    异常说明:
        URL 无主机、含用户名/密码、协议不受支持或远程使用 HTTP 时抛出
        ``ValueError``，并保证异常发生在网络请求之前。
    """
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        # 读取 port 可让 urllib 对非法端口在发起网络前完成校验。
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Gateway URL 格式无效") from exc
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Gateway URL 禁止包含用户名或密码")
    if not hostname:
        raise ValueError("Gateway URL 必须包含主机")
    scheme = parsed.scheme.lower()
    if scheme == "https":
        return
    if scheme == "http" and _is_local_http_url(url):
        return
    raise ValueError("Gateway 仅允许远程 HTTPS 或回环 HTTP")


def _normalize_timeout_override(value: float | None) -> float | None:
    """校验可选总请求预算，返回有限正浮点数或 None。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("read_timeout 必须是有限非 bool 正数")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("read_timeout 必须是有限非 bool 正数")
    return normalized


class GatewayClient:
    """封装 Gateway 信封、超时、有限重试与响应解析。

    功能说明:
        统一构造 Gateway 信封，执行安全 HTTP 调用、有限重试和脱敏诊断。
    参数说明:
        settings: 已合并并校验的运行配置。
        session: 可替换的 requests 会话，便于连接复用和离线测试。
        sleep: 重试等待函数，测试中可注入空实现。
        diagnostic_hook: 可选诊断接收函数，仅收到脱敏后的请求与响应。
        redactor: 可选自定义脱敏器。
    返回值:
        实例通过 ``invoke`` 返回标准 Gateway 响应模型。
    异常说明:
        非重试 HTTP 错误、JSON/模型解析错误以及耗尽重试的连接异常会向调用方抛出。
    """

    def __init__(
        self,
        settings: Settings,
        *,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        diagnostic_hook: Callable[[dict[str, Any]], None] | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self.settings = settings
        self._session = session or requests.Session()
        self._sleep = sleep
        self._diagnostic_hook = diagnostic_hook
        self._redactor = redactor or Redactor.from_config()

    def _emit_diagnostic(
        self,
        *,
        service_name: str,
        method_name: str,
        body: dict[str, Any],
        started_at: float,
        attempts: int,
        http_status: int | None = None,
        response: Any = None,
        error_type: str | None = None,
    ) -> None:
        """向钩子发送统一脱敏诊断，绝不传递原始载荷。"""
        if self._diagnostic_hook is None:
            return
        diagnostic = {
            "service_name": service_name,
            "method_name": method_name,
            "http_status": http_status,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "attempts": attempts,
            "request": body,
            "response": response,
        }
        if error_type is not None:
            diagnostic["error_type"] = error_type
        self._diagnostic_hook(self._redactor.redact(diagnostic))

    @staticmethod
    def _diagnostic_response(http_response: Any) -> Any:
        """尽力读取失败响应 JSON；读取失败时返回空值且不覆盖原始异常。"""
        try:
            return http_response.json()
        except ValueError:
            return None

    def invoke(
        self,
        service_name: str,
        method_name: str,
        params: dict[str, Any],
        *,
        auth_token: str | None | object = _INHERIT_DEFAULT_AUTH,
        client_request_id: str | None = None,
        trace_id: str | None = None,
        read_timeout: float | None = None,
    ) -> GatewayResponse:
        """调用单个 Gateway 业务方法。

        功能说明:
            在首次网络请求前一次性构造并序列化信封；后续连接异常或 502/503/504
            重试复用完全相同的请求体和 ``client_request_id``，最多重试配置中的两次。
        参数说明:
            service_name/method_name/params: 业务服务、方法与参数。
            auth_token: 未提供时继承配置 token；显式传 ``None`` 表示匿名请求。
            client_request_id: 调用方创建的稳定幂等 ID。
            trace_id: 可选稳定追踪 ID。
            read_timeout: 可选调用总预算；每次尝试的连接和读取超时都会裁剪到
                当前剩余预算，且不能放大配置中的超时。
        返回值:
            Pydantic v2 解析的 :class:`GatewayResponse`。
        异常说明:
            读取超时不重试；连接失败耗尽、HTTP 非成功或响应结构无效时抛出对应异常。
        """
        resolved_auth_token = (
            self.settings.auth_token
            if auth_token is _INHERIT_DEFAULT_AUTH
            else auth_token
        )
        envelope = build_gateway_envelope(
            service_name=service_name,
            method_name=method_name,
            params=params,
            device_id=self.settings.device_id,
            platform=self.settings.platform,
            app_version=self.settings.app_version,
            locale=self.settings.locale,
            timezone=self.settings.timezone,
            auth_token=resolved_auth_token,
            client_request_id=client_request_id,
            trace_id=trace_id,
        )
        body = envelope.model_dump(exclude_none=True)
        url = f"{self.settings.base_url.rstrip('/')}/gateway/invoke"
        _validate_gateway_url(url)
        timeout_budget = _normalize_timeout_override(read_timeout)
        retryable_statuses = {502, 503, 504}
        started_at = time.perf_counter()

        for attempt in range(self.settings.max_retries + 1):
            remaining = (
                timeout_budget - (time.perf_counter() - started_at)
                if timeout_budget is not None
                else None
            )
            if remaining is not None and remaining <= 0:
                self._emit_diagnostic(
                    service_name=service_name,
                    method_name=method_name,
                    body=body,
                    started_at=started_at,
                    attempts=attempt,
                    error_type="Timeout",
                )
                raise requests.Timeout("Gateway 调用总预算已耗尽")
            connect_timeout = self.settings.connect_timeout
            effective_read_timeout = self.settings.read_timeout
            if remaining is not None:
                connect_timeout = min(connect_timeout, remaining)
                effective_read_timeout = min(effective_read_timeout, remaining)
            try:
                http_response = self._session.post(
                    url,
                    json=body,
                    timeout=(connect_timeout, effective_read_timeout),
                    allow_redirects=False,
                )
            except requests.ReadTimeout as exc:
                self._emit_diagnostic(
                    service_name=service_name,
                    method_name=method_name,
                    body=body,
                    started_at=started_at,
                    attempts=attempt + 1,
                    error_type=type(exc).__name__,
                )
                raise
            except requests.ConnectionError as exc:
                if attempt >= self.settings.max_retries:
                    self._emit_diagnostic(
                        service_name=service_name,
                        method_name=method_name,
                        body=body,
                        started_at=started_at,
                        attempts=attempt + 1,
                        error_type=type(exc).__name__,
                    )
                    raise
                self._sleep(0.25 * (2**attempt))
                continue

            if http_response.status_code in retryable_statuses and attempt < self.settings.max_retries:
                self._sleep(0.25 * (2**attempt))
                continue
            if not 200 <= http_response.status_code < 300:
                exc = requests.HTTPError(
                    f"Gateway HTTP 状态异常: {http_response.status_code}"
                )
                self._emit_diagnostic(
                    service_name=service_name,
                    method_name=method_name,
                    body=body,
                    started_at=started_at,
                    attempts=attempt + 1,
                    http_status=http_response.status_code,
                    response=self._diagnostic_response(http_response),
                    error_type=type(exc).__name__,
                )
                raise exc
            try:
                response_payload = http_response.json()
            except ValueError as exc:
                self._emit_diagnostic(
                    service_name=service_name,
                    method_name=method_name,
                    body=body,
                    started_at=started_at,
                    attempts=attempt + 1,
                    http_status=http_response.status_code,
                    error_type=type(exc).__name__,
                )
                raise
            try:
                parsed = GatewayResponse.model_validate(response_payload)
            except ValidationError as exc:
                self._emit_diagnostic(
                    service_name=service_name,
                    method_name=method_name,
                    body=body,
                    started_at=started_at,
                    attempts=attempt + 1,
                    http_status=http_response.status_code,
                    response=response_payload,
                    error_type=type(exc).__name__,
                )
                raise
            parsed.http_status = http_response.status_code
            self._emit_diagnostic(
                service_name=service_name,
                method_name=method_name,
                body=body,
                started_at=started_at,
                attempts=attempt + 1,
                http_status=http_response.status_code,
                response=response_payload,
            )
            return parsed

        raise RuntimeError("Gateway 重试循环异常结束")
