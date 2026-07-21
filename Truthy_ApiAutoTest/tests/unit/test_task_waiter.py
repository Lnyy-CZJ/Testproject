"""异步搜索任务等待器状态机和总预算测试。"""

from collections.abc import Iterable
import math
from typing import Any

import pytest

from framework.models.envelope import GatewayResponse
from framework.waiters.task_waiter import TaskWaiter, TaskWaitError


def _response(
    status: str | None = None,
    *,
    progress: dict[str, Any] | None = None,
    business_error_code: str = "",
    code: int = 0,
    data_extra: dict[str, Any] | None = None,
) -> GatewayResponse:
    """构造等待器所需的成功快照或业务失败响应。"""
    data = {"task_id": "task-1"}
    if status is not None:
        data["status"] = status
    if progress is not None:
        data["progress"] = progress
    data.update(data_extra or {})
    response = GatewayResponse.model_validate(
        {
            "code": 0,
            "message": "OK",
            "request_id": f"request-{status or business_error_code}",
            "trace_id": f"trace-{status or business_error_code}",
            "responses": [
                {
                    "id": "req_0",
                    "code": code,
                    "success": not business_error_code,
                    "business_error_code": business_error_code,
                    "data": data,
                }
            ],
        }
    )
    response.http_status = 200
    return response


class _Search:
    """按顺序返回 GetTask 快照。"""

    def __init__(self, responses: Iterable[GatewayResponse]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, str]] = []

    def get_task(self, *, access_token: str, task_id: str) -> GatewayResponse:
        self.calls.append({"access_token": access_token, "task_id": task_id})
        return next(self.responses)


class _Clock:
    """sleep 时推进的确定性单调时钟。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.mark.parametrize("terminal", ["SUCCEEDED", "NO_RESULT", "FAILED"])
def test_waiter_returns_all_allowed_terminals_with_sanitized_trajectory(
    terminal: str,
) -> None:
    clock = _Clock()
    service = _Search(
        [
            _response("CREATED", progress={"stage": "created"}),
            _response("QUEUED", progress={"display_percent": 10}),
            _response("SEARCHING", progress={"display_percent": 50}),
            _response(terminal, data_extra={"private_payload": "must-not-enter-trace"}),
        ]
    )

    result = TaskWaiter(service, clock=clock, sleep=clock.sleep).wait(
        access_token="access", task_id="task-1"
    )

    assert result.status == terminal
    assert [entry["status"] for entry in result.trajectory] == [
        "CREATED",
        "QUEUED",
        "SEARCHING",
        terminal,
    ]
    assert set(result.trajectory[0]) == {"status", "progress", "request_id", "trace_id"}
    assert "must-not-enter-trace" not in str(result.trajectory)
    assert clock.sleeps == [2.0, 2.0, 2.0]


def test_waiter_allows_skipping_intermediate_states() -> None:
    result = TaskWaiter(_Search([_response("SUCCEEDED")]), clock=lambda: 0).wait(
        access_token="access", task_id="task-1"
    )

    assert result.status == "SUCCEEDED"


@pytest.mark.parametrize("fallback", ["QUEUED", "CREATED"])
def test_waiter_rejects_searching_state_fallback(fallback: str) -> None:
    clock = _Clock()
    waiter = TaskWaiter(
        _Search([_response("SEARCHING"), _response(fallback)]),
        clock=clock,
        sleep=clock.sleep,
    )

    with pytest.raises(TaskWaitError, match="回退"):
        waiter.wait(access_token="access", task_id="task-1")


def test_waiter_rejects_queued_state_fallback_to_created() -> None:
    clock = _Clock()
    waiter = TaskWaiter(
        _Search([_response("QUEUED"), _response("CREATED")]),
        clock=clock,
        sleep=clock.sleep,
    )

    with pytest.raises(TaskWaitError, match="QUEUED.*回退.*CREATED") as error:
        waiter.wait(access_token="access", task_id="task-1")

    assert "request-CREATED" in str(error.value)


def test_waiter_rejects_unknown_state_with_diagnostic_trajectory() -> None:
    with pytest.raises(TaskWaitError, match="未知状态.*MYSTERY") as error:
        TaskWaiter(_Search([_response("MYSTERY")]), clock=lambda: 0).wait(
            access_token="access", task_id="task-1"
        )

    assert "request-MYSTERY" in str(error.value)


@pytest.mark.parametrize("terminal", ["EXPIRED", "CANCELED", "REJECTED"])
def test_waiter_rejects_disallowed_terminal(terminal: str) -> None:
    with pytest.raises(TaskWaitError, match=f"非允许终态.*{terminal}"):
        TaskWaiter(_Search([_response(terminal)]), clock=lambda: 0).wait(
            access_token="access", task_id="task-1"
        )


def test_waiter_times_out_at_twenty_second_budget_with_full_trace() -> None:
    clock = _Clock()
    waiter = TaskWaiter(
        _Search([_response("QUEUED") for _ in range(20)]),
        clock=clock,
        sleep=clock.sleep,
    )

    with pytest.raises(TaskWaitError, match="20.*超时") as error:
        waiter.wait(access_token="access", task_id="task-1")

    assert clock.now == 20.0
    assert clock.sleeps == [2.0] * 5 + [3.0] * 3 + [1.0]
    assert "request-QUEUED" in str(error.value)


def test_rate_limited_uses_interval_backoff_and_remains_in_budget() -> None:
    clock = _Clock()
    waiter = TaskWaiter(
        _Search(
            [
                _response(business_error_code="RATE_LIMITED", code=300002),
                _response("SEARCHING"),
                _response("SUCCEEDED"),
            ]
        ),
        clock=clock,
        sleep=clock.sleep,
    )

    result = waiter.wait(access_token="access", task_id="task-1")

    assert result.status == "SUCCEEDED"
    assert [entry["status"] for entry in result.trajectory] == [
        "RATE_LIMITED",
        "SEARCHING",
        "SUCCEEDED",
    ]
    assert clock.sleeps == [2.0, 2.0]
    assert clock.now <= 20.0


def test_non_rate_limited_business_error_is_diagnostic_failure() -> None:
    with pytest.raises(TaskWaitError, match="业务失败.*NOT_FOUND"):
        TaskWaiter(
            _Search([_response(business_error_code="NOT_FOUND", code=301404)]),
            clock=lambda: 0,
        ).wait(access_token="access", task_id="task-1")


def test_trajectory_progress_excludes_unrecognized_or_sensitive_fields() -> None:
    result = TaskWaiter(
        _Search(
            [
                _response(
                    "SUCCEEDED",
                    progress={
                        "stage": "complete",
                        "display_percent": 100,
                        "display_message": "found private person",
                        "full_name": "private-name",
                    },
                )
            ]
        ),
        clock=lambda: 0,
    ).wait(access_token="access", task_id="task-1")

    assert result.trajectory[0]["progress"] == {
        "stage": "complete",
        "display_percent": 100,
    }
    assert "private-name" not in str(result.trajectory)
    assert "private person" not in str(result.trajectory)


def test_network_time_is_included_in_total_budget() -> None:
    clock = _Clock()

    class _SlowSearch:
        """模拟单次 GetTask 已耗尽全部预算。"""

        def get_task(self, *, access_token: str, task_id: str) -> GatewayResponse:
            clock.now += 20.0
            return _response("SUCCEEDED")

    with pytest.raises(TaskWaitError, match="20.*超时"):
        TaskWaiter(_SlowSearch(), clock=clock, sleep=clock.sleep).wait(
            access_token="access", task_id="task-1"
        )


def test_wait_terminal_passes_remaining_budget_as_read_timeout() -> None:
    """计划锁定入口必须把每轮剩余预算传给支持该关键字的真实 Service。"""
    clock = _Clock()

    class _BudgetAwareSearch:
        """记录等待器传入的 read timeout，并模拟首轮 HTTP 消耗。"""

        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def get_task(
            self, *, access_token: str, task_id: str, read_timeout: float | None = None
        ) -> GatewayResponse:
            assert read_timeout is not None
            self.timeouts.append(read_timeout)
            clock.now += 3.0
            return _response("SUCCEEDED")

    service = _BudgetAwareSearch()
    result = TaskWaiter(
        service, timeout=5, clock=clock, sleep=clock.sleep
    ).wait_terminal(access_token="access", task_id="task-1")

    assert result.status == "SUCCEEDED"
    assert service.timeouts == [5.0]


def test_wait_terminal_reduces_second_http_timeout_after_call_and_backoff() -> None:
    """上一轮 HTTP 与退避耗时必须从下一轮 read timeout 中扣除。"""
    clock = _Clock()

    class _TwoRoundSearch:
        """首轮返回排队、次轮成功，并记录每轮剩余预算。"""

        def __init__(self) -> None:
            self.timeouts: list[float] = []

        def get_task(
            self, *, access_token: str, task_id: str, read_timeout: float | None = None
        ) -> GatewayResponse:
            assert read_timeout is not None
            self.timeouts.append(read_timeout)
            clock.now += 1.0
            return _response("QUEUED" if len(self.timeouts) == 1 else "SUCCEEDED")

    service = _TwoRoundSearch()
    result = TaskWaiter(
        service, timeout=6, clock=clock, sleep=clock.sleep
    ).wait_terminal(access_token="access", task_id="task-1")

    assert result.status == "SUCCEEDED"
    assert service.timeouts == [6.0, 3.0]


def test_wait_remains_compatible_alias_for_legacy_service_mock() -> None:
    """旧 mock 无 read_timeout 关键字时，兼容别名仍可完成轮询。"""
    result = TaskWaiter(_Search([_response("SUCCEEDED")]), clock=lambda: 0).wait(
        access_token="access", task_id="task-1"
    )

    assert result.status == "SUCCEEDED"


@pytest.mark.parametrize(
    "timeout",
    [True, False, 0, -1, math.nan, math.inf, -math.inf, "20", 10**1000],
)
def test_waiter_rejects_non_finite_non_numeric_or_bool_timeout(timeout: Any) -> None:
    with pytest.raises(ValueError, match="timeout"):
        TaskWaiter(_Search([]), timeout=timeout)


@pytest.mark.parametrize(
    "clock_value", [True, math.nan, math.inf, -math.inf, 10**1000]
)
def test_waiter_rejects_invalid_clock_values(clock_value: Any) -> None:
    with pytest.raises(TaskWaitError, match="时钟"):
        TaskWaiter(_Search([]), clock=lambda: clock_value).wait(
            access_token="access", task_id="task-1"
        )


def test_waiter_rejects_monotonic_clock_rollback() -> None:
    values = iter([1.0, 1.0, 0.5])

    with pytest.raises(TaskWaitError, match="时钟.*回退"):
        TaskWaiter(
            _Search([_response("SUCCEEDED")]), clock=lambda: next(values)
        ).wait(access_token="access", task_id="task-1")


def test_get_task_exception_is_wrapped_without_message_or_exception_chain() -> None:
    clock = _Clock()

    class _FailingSearch:
        """首轮返回安全快照，第二轮抛出含敏感文本的异常。"""

        def __init__(self) -> None:
            self.calls = 0

        def get_task(self, *, access_token: str, task_id: str) -> GatewayResponse:
            self.calls += 1
            if self.calls == 1:
                return _response("QUEUED")
            raise RuntimeError("TOPSECRET network URL?signature=TOPSECRET")

    with pytest.raises(TaskWaitError, match="RuntimeError") as captured:
        TaskWaiter(
            _FailingSearch(), clock=clock, sleep=clock.sleep
        ).wait(access_token="access", task_id="task-1")

    assert "TOPSECRET" not in str(captured.value)
    assert "request-QUEUED" in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_non_string_status_is_safe_diagnostic_error() -> None:
    response = _response("SUCCEEDED")
    response.responses[0].data["status"] = ["TOPSECRET"]

    with pytest.raises(TaskWaitError, match="status 必须是字符串") as captured:
        TaskWaiter(_Search([response]), clock=lambda: 0).wait(
            access_token="access", task_id="task-1"
        )

    assert "TOPSECRET" not in str(captured.value)


def test_progress_only_keeps_safe_stage_and_strict_percent() -> None:
    response = _response(
        "SUCCEEDED",
        progress={
            "stage": "TOPSECRET stage\n",
            "display_percent": True,
            "display_message": "TOPSECRET",
        },
    )

    result = TaskWaiter(_Search([response]), clock=lambda: 0).wait(
        access_token="access", task_id="task-1"
    )

    assert result.trajectory[0]["progress"] == {}
    assert "TOPSECRET" not in str(result.trajectory)


@pytest.mark.parametrize("percent", [-1, 101, 1.5, "50", True])
def test_progress_drops_invalid_percent(percent: Any) -> None:
    response = _response(
        "SUCCEEDED", progress={"stage": "searching", "display_percent": percent}
    )

    result = TaskWaiter(_Search([response]), clock=lambda: 0).wait(
        access_token="access", task_id="task-1"
    )

    assert result.trajectory[0]["progress"] == {"stage": "searching"}


def test_trajectory_redacts_dangerous_request_and_trace_ids() -> None:
    response = _response("SUCCEEDED")
    response.request_id = "TOPSECRET request?id=1"
    response.trace_id = "TOPSECRET/trace#fragment"

    result = TaskWaiter(_Search([response]), clock=lambda: 0).wait(
        access_token="access", task_id="task-1"
    )

    assert result.trajectory[0]["request_id"] == "<redacted>"
    assert result.trajectory[0]["trace_id"] == "<redacted>"
    assert "TOPSECRET" not in str(result.trajectory)


def test_business_error_code_is_redacted_when_not_a_safe_identifier() -> None:
    response = _response(business_error_code="TOPSECRET?signature=x", code=399999)

    with pytest.raises(TaskWaitError) as captured:
        TaskWaiter(_Search([response]), clock=lambda: 0).wait(
            access_token="access", task_id="task-1"
        )

    assert "TOPSECRET" not in str(captured.value)
    assert "<redacted>" in str(captured.value)
