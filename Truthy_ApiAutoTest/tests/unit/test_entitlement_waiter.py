"""权益最终一致性等待器的离线预算与安全测试。"""

import math
from typing import Any

import pytest

from framework.models.envelope import GatewayResponse
from framework.waiters.entitlement_waiter import (
    EntitlementWaitError,
    wait_entitlement_allow,
)


def _response(*, decision: str, can_start_search: bool) -> GatewayResponse:
    """构造权益读取成功响应。"""
    response = GatewayResponse.model_validate(
        {
            "code": 0,
            "message": "OK",
            "request_id": "request-safe",
            "trace_id": "trace-safe",
            "responses": [
                {
                    "id": "req_0",
                    "code": 0,
                    "success": True,
                    "data": {
                        "decision": decision,
                        "can_start_search": can_start_search,
                    },
                }
            ],
        }
    )
    response.http_status = 200
    return response


class _Service:
    """按序返回权益快照或抛出注入异常。"""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, str]] = []

    def get_entitlement(
        self, *, access_token: str, product_code: str
    ) -> GatewayResponse:
        self.calls.append({"access_token": access_token, "product_code": product_code})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _Clock:
    """记录退避并离线推进单调时间。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_wait_entitlement_allow_reaches_final_consistent_state() -> None:
    """DENY 快照有界轮询，且同时满足两个 ALLOW 条件才返回。"""
    service = _Service(
        [
            _response(decision="DENY", can_start_search=False),
            _response(decision="ALLOW", can_start_search=False),
            _response(decision="ALLOW", can_start_search=True),
        ]
    )
    clock = _Clock()

    result = wait_entitlement_allow(
        service,
        access_token="token-ultra-secret",
        product_code="people_insight",
        clock=clock,
        sleep=clock.sleep,
    )

    assert result.data["decision"] == "ALLOW"
    assert result.data["can_start_search"] is True
    assert [entry["decision"] for entry in result.trajectory] == [
        "DENY",
        "ALLOW",
        "ALLOW",
    ]
    assert clock.sleeps == [2.0, 2.0]
    assert "token-ultra-secret" not in repr(result)


def test_wait_entitlement_timeout_clips_sleep_to_budget_and_hides_token() -> None:
    """总预算不足时裁剪最后退避，并在下一轮读取前安全超时。"""
    service = _Service([_response(decision="DENY", can_start_search=False)] * 10)
    clock = _Clock()

    with pytest.raises(EntitlementWaitError, match="5 秒超时") as caught:
        wait_entitlement_allow(
            service,
            access_token="token-ultra-secret",
            product_code="people_insight",
            timeout=5,
            clock=clock,
            sleep=clock.sleep,
        )

    assert clock.sleeps == [2.0, 2.0, 1.0]
    assert len(service.calls) == 3
    assert "token-ultra-secret" not in str(caught.value)


def test_wait_entitlement_switches_to_three_second_backoff_after_ten_seconds() -> None:
    """到第10秒后使用3秒间隔，并继续裁剪最后一次等待。"""
    service = _Service([_response(decision="DENY", can_start_search=False)] * 20)
    clock = _Clock()

    with pytest.raises(EntitlementWaitError, match="14 秒超时"):
        wait_entitlement_allow(
            service,
            access_token="secret",
            product_code="people_insight",
            timeout=14,
            clock=clock,
            sleep=clock.sleep,
        )

    assert clock.sleeps == [2.0, 2.0, 2.0, 2.0, 2.0, 3.0, 1.0]


def test_wait_entitlement_unknown_values_and_ids_are_safe_in_timeout_trace() -> None:
    """未知 decision 与不安全追踪 ID 不得原样进入异常轨迹。"""
    response = _response(
        decision="token-ultra-secret", can_start_search=False
    )
    response.request_id = "req-token-ultra-secret"
    response.trace_id = "trace-token-ultra-secret-suffix"
    clock = _Clock()

    with pytest.raises(EntitlementWaitError) as caught:
        wait_entitlement_allow(
            _Service([response]),
            access_token="token-ultra-secret",
            product_code="people_insight",
            timeout=2,
            clock=clock,
            sleep=clock.sleep,
        )

    assert "token-ultra-secret" not in str(caught.value)


def test_wait_entitlement_empty_secret_does_not_redact_safe_identifiers() -> None:
    """空 secret 不参与子串匹配，合法追踪 ID 保持可诊断。"""
    result = wait_entitlement_allow(
        _Service([_response(decision="ALLOW", can_start_search=True)]),
        access_token="",
        product_code="people_insight",
        clock=lambda: 0.0,
    )

    assert result.trajectory[0]["request_id"] == "request-safe"
    assert result.trajectory[0]["trace_id"] == "trace-safe"


@pytest.mark.parametrize("timeout", [True, 0, -1, math.inf, math.nan, "20"])
def test_wait_entitlement_rejects_invalid_timeout(timeout: object) -> None:
    """timeout 必须是有限非 bool 正数。"""
    with pytest.raises(ValueError, match="timeout"):
        wait_entitlement_allow(
            _Service([]),
            access_token="secret",
            product_code="people_insight",
            timeout=timeout,
        )


def test_wait_entitlement_rejects_clock_rollback_and_non_finite_value() -> None:
    """时钟回退或非有限值必须产生安全异常。"""
    values = iter([0.0, 0.0, -1.0])
    with pytest.raises(EntitlementWaitError, match="回退"):
        wait_entitlement_allow(
            _Service([_response(decision="DENY", can_start_search=False)]),
            access_token="secret",
            product_code="people_insight",
            clock=lambda: next(values),
            sleep=lambda _: None,
        )

    with pytest.raises(EntitlementWaitError, match="有限"):
        wait_entitlement_allow(
            _Service([]),
            access_token="secret",
            product_code="people_insight",
            clock=lambda: math.nan,
        )


def test_wait_entitlement_rejects_clock_that_does_not_advance_after_sleep() -> None:
    """冻结时钟与空 sleep 不能形成无限轮询。"""
    with pytest.raises(EntitlementWaitError, match="未前进"):
        wait_entitlement_allow(
            _Service([_response(decision="DENY", can_start_search=False)]),
            access_token="secret",
            product_code="people_insight",
            clock=lambda: 0.0,
            sleep=lambda _: None,
        )

def test_wait_entitlement_wraps_network_exception_without_secret_payload() -> None:
    """外部异常只暴露安全类型，不拼接可能包含 token 的原消息。"""
    with pytest.raises(EntitlementWaitError, match="RuntimeError") as caught:
        wait_entitlement_allow(
            _Service([RuntimeError("token-ultra-secret")]),
            access_token="token-ultra-secret",
            product_code="people_insight",
            clock=lambda: 0.0,
        )

    assert "token-ultra-secret" not in str(caught.value)


def test_wait_entitlement_passes_remaining_budget_to_supported_service() -> None:
    """权益等待器将剩余总预算作为 read timeout 传给真实订阅 Service。"""
    clock = _Clock()

    class _BudgetAwareService:
        """记录 read timeout，并模拟本次 HTTP 已消耗三秒。"""

        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def get_entitlement(
            self,
            *,
            access_token: str,
            product_code: str,
            read_timeout: float | None = None,
        ) -> GatewayResponse:
            assert read_timeout is not None
            self.timeouts.append(read_timeout)
            clock.now += 3.0
            return _response(decision="ALLOW", can_start_search=True)

    service = _BudgetAwareService()
    result = wait_entitlement_allow(
        service,
        access_token="secret",
        product_code="people_insight",
        timeout=5,
        clock=clock,
        sleep=clock.sleep,
    )

    assert result.data["decision"] == "ALLOW"
    assert service.timeouts == [5.0]


def test_wait_entitlement_reduces_second_http_timeout_after_backoff() -> None:
    """权益第二轮 read timeout 必须扣除首轮调用与退避耗时。"""
    clock = _Clock()

    class _TwoRoundService:
        """首轮 DENY、次轮 ALLOW，并记录等待器预算。"""

        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def get_entitlement(
            self,
            *,
            access_token: str,
            product_code: str,
            read_timeout: float | None = None,
        ) -> GatewayResponse:
            assert read_timeout is not None
            self.timeouts.append(read_timeout)
            clock.now += 1.0
            if len(self.timeouts) == 1:
                return _response(decision="DENY", can_start_search=False)
            return _response(decision="ALLOW", can_start_search=True)

    service = _TwoRoundService()
    result = wait_entitlement_allow(
        service,
        access_token="secret",
        product_code="people_insight",
        timeout=6,
        clock=clock,
        sleep=clock.sleep,
    )

    assert result.data["decision"] == "ALLOW"
    assert service.timeouts == [6.0, 3.0]
