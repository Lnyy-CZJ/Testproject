"""搜索权益最终一致性的限时、限频等待器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import inspect
import math
import re
import time
from typing import Any, Protocol

from framework.models.envelope import GatewayResponse


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class _EntitlementReader(Protocol):
    """等待器依赖的最小订阅读取协议。"""

    def get_entitlement(
        self,
        *,
        access_token: str,
        product_code: str,
        read_timeout: float | None = None,
    ) -> GatewayResponse: ...


class EntitlementWaitError(RuntimeError):
    """权益等待安全异常。

    功能说明:
        表示预算、协议或外部调用异常，消息与轨迹均不含 token 或业务载荷。
    参数说明:
        继承 ``RuntimeError`` 的安全错误消息参数。
    返回值:
        无；该类型仅用于异常传播。
    异常说明:
        本类型自身不额外抛出异常。
    """


@dataclass(frozen=True, slots=True)
class EntitlementWaitResult:
    """权益最终一致性等待结果。

    功能说明:
        保存最终允许快照及仅含安全决策字段的不可变轨迹。
    参数说明:
        data: 最终权益数据；trajectory: 脱敏轮询轨迹。
    返回值:
        实例作为权益等待函数的不可变结果。
    异常说明:
        数据类构造不主动校验，字段正确性由等待函数保证。
    """

    data: dict[str, Any]
    trajectory: tuple[dict[str, Any], ...]


def _finite_number(value: Any) -> float | None:
    """转换有限非 bool 数值，转换失败返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def wait_entitlement_allow(
    subscription_service: _EntitlementReader,
    *,
    access_token: str,
    product_code: str,
    timeout: float = 20.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> EntitlementWaitResult:
    """有界轮询权益，直到 decision=ALLOW 且 can_start_search=true。

    功能说明:
        在固定总预算内轮询，直到权益同时满足 ALLOW 和可开始搜索。
    参数说明:
        subscription_service: 提供 ``get_entitlement`` 的订阅 Service；token 与商品
        编码仅用于调用且不进入异常；timeout 默认 20 秒；clock/sleep 可离线注入。
    返回值:
        最终业务 data 及 decision/can_start_search/request_id/trace_id 安全轨迹。
    异常说明:
        timeout/时钟无效或回退、业务响应异常、网络异常均抛中文
        :class:`EntitlementWaitError`，不拼接外部异常消息或 token。
    """
    normalized_timeout = _finite_number(timeout)
    if normalized_timeout is None or normalized_timeout <= 0:
        raise ValueError("timeout 必须是有限非 bool 正数")
    trajectory: list[dict[str, Any]] = []
    last_clock: float | None = None

    def read_clock() -> float:
        """读取有限单调时钟并隐藏注入异常消息。"""
        nonlocal last_clock
        try:
            raw = clock()
        except Exception as exc:  # noqa: BLE001 - 外部消息可能含 token
            raise EntitlementWaitError(
                f"单调时钟读取失败: {type(exc).__name__}; 轨迹={trajectory}"
            ) from None
        value = _finite_number(raw)
        if value is None:
            raise EntitlementWaitError(f"单调时钟必须返回有限数值; 轨迹={trajectory}")
        if last_clock is not None and value < last_clock:
            raise EntitlementWaitError(f"单调时钟发生回退; 轨迹={trajectory}")
        last_clock = value
        return value

    started_at = read_clock()
    deadline = started_at + normalized_timeout
    if not math.isfinite(deadline):
        raise ValueError("timeout 无法形成有限截止时间")

    while True:
        now = read_clock()
        if now >= deadline:
            raise EntitlementWaitError(
                f"等待权益 {normalized_timeout:g} 秒超时; 轨迹={trajectory}"
            )
        try:
            get_entitlement = subscription_service.get_entitlement
            call_kwargs: dict[str, Any] = {
                "access_token": access_token,
                "product_code": product_code,
            }
            if _accepts_keyword(get_entitlement, "read_timeout"):
                call_kwargs["read_timeout"] = deadline - now
            response = get_entitlement(**call_kwargs)
        except Exception as exc:  # noqa: BLE001 - 外部消息可能含 token
            raise EntitlementWaitError(
                f"GetEntitlement 调用异常: {type(exc).__name__}; 轨迹={trajectory}"
            ) from None
        after_call = read_clock()
        if after_call >= deadline:
            raise EntitlementWaitError(
                f"等待权益 {normalized_timeout:g} 秒超时; 轨迹={trajectory}"
            )
        data = _require_success_data(response, trajectory)
        decision = data.get("decision")
        can_start_search = data.get("can_start_search")
        trajectory.append(
            {
                "decision": decision if decision in {"ALLOW", "DENY"} else "<invalid>",
                "can_start_search": (
                    can_start_search if isinstance(can_start_search, bool) else None
                ),
                "request_id": _safe_identifier(
                    response.request_id, forbidden=access_token
                ),
                "trace_id": _safe_identifier(response.trace_id, forbidden=access_token),
            }
        )
        if decision == "ALLOW" and can_start_search is True:
            return EntitlementWaitResult(data=dict(data), trajectory=tuple(trajectory))

        elapsed = after_call - started_at
        interval = 2.0 if elapsed < 10.0 else 3.0
        remaining = deadline - after_call
        duration = min(interval, remaining)
        try:
            sleep(duration)
        except Exception as exc:  # noqa: BLE001 - 注入 sleep 异常必须安全包装
            raise EntitlementWaitError(
                f"权益退避失败: {type(exc).__name__}; 轨迹={trajectory}"
            ) from None
        woke_at = read_clock()
        if woke_at <= after_call:
            raise EntitlementWaitError(f"退避后单调时钟未前进; 轨迹={trajectory}")


def _require_success_data(
    response: GatewayResponse, trajectory: list[dict[str, Any]]
) -> dict[str, Any]:
    """验证最小成功信封，不把消息或业务载荷写入异常。"""
    if response.http_status is None or not 200 <= response.http_status < 300:
        raise EntitlementWaitError(f"GetEntitlement HTTP 异常; 轨迹={trajectory}")
    item = next((item for item in response.responses if item.id == "req_0"), None)
    if item is None:
        raise EntitlementWaitError(f"GetEntitlement 缺少子响应; 轨迹={trajectory}")
    if item.success is not True or item.code != 0:
        raise EntitlementWaitError(f"GetEntitlement 业务失败; 轨迹={trajectory}")
    if not isinstance(item.data, dict):
        raise EntitlementWaitError(f"GetEntitlement data 必须是对象; 轨迹={trajectory}")
    return item.data


def _safe_identifier(value: Any, *, forbidden: str) -> str:
    """仅允许非 token 且符合有限字符集的追踪标识进入轨迹。"""
    if (
        isinstance(value, str)
        and (not forbidden or forbidden not in value)
        and _SAFE_IDENTIFIER.fullmatch(value)
    ):
        return value
    return "<redacted>"


def _accepts_keyword(function: Callable[..., Any], name: str) -> bool:
    """判断真实 Service 或旧测试替身是否接受可选预算关键字。"""
    try:
        parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or (
            parameter.name == name
            and parameter.kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        )
        for parameter in parameters
    )
