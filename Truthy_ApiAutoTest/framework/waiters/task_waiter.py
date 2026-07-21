"""搜索任务的限时、限频状态等待器。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
import inspect
import math
import re
from typing import Any, Protocol

from framework.models.envelope import GatewayResponse


def _finite_number(value: Any) -> float | None:
    """将原生 int/float 安全转换为有限浮点数，排除 bool 和溢出。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


class _SearchTaskReader(Protocol):
    """等待器依赖的最小 SearchService 协议。"""

    def get_task(
        self,
        *,
        access_token: str,
        task_id: str,
        read_timeout: float | None = None,
    ) -> GatewayResponse: ...


class TaskWaitError(RuntimeError):
    """任务等待安全异常。

    功能说明:
        表示状态机、业务失败或总预算异常，消息中仅包含安全轨迹。
    参数说明:
        继承 ``RuntimeError`` 的安全错误消息参数。
    返回值:
        无；该类型仅用于异常传播。
    异常说明:
        本类型自身不额外抛出异常。
    """


@dataclass(frozen=True)
class TaskWaitResult:
    """允许终态的最终业务快照和安全轮询轨迹。

    功能说明:
        保存允许终态的最终业务快照和安全轮询轨迹。
    参数说明:
        status: ``SUCCEEDED/NO_RESULT/FAILED`` 之一；data: 最终 GetTask 业务数据；
        trajectory: 每次仅含 status/progress/request_id/trace_id 的诊断条目。
    返回值:
        实例作为 ``TaskWaiter`` 的不可变等待结果。
    异常说明:
        数据类构造不主动校验，字段正确性由等待器状态机保证。
    """

    status: str
    data: dict[str, Any]
    trajectory: tuple[dict[str, Any], ...]


class TaskWaiter:
    """在固定总预算内等待搜索任务进入允许终态。

    功能说明:
        在固定总预算内轮询搜索任务，并校验合法状态流转。
    参数说明:
        search_service: 仅需提供 ``get_task``；timeout: 默认 20 秒总预算；clock
        与 sleep: 可注入的单调时钟和等待函数，供离线无等待测试使用。
    返回值:
        :meth:`wait_terminal` 返回包含最终快照与安全轨迹的
        :class:`TaskWaitResult`；``wait`` 是兼容入口。
    异常说明:
        非允许终态、未知状态、SEARCHING 回退、非限流业务错误及超时均抛出
        中文 :class:`TaskWaitError`，错误中包含不含业务敏感载荷的轨迹。
    """

    _ACTIVE = {"CREATED", "QUEUED", "SEARCHING"}
    _ACTIVE_ORDER = {"CREATED": 0, "QUEUED": 1, "SEARCHING": 2}
    _ALLOWED_TERMINAL = {"SUCCEEDED", "NO_RESULT", "FAILED"}
    _DISALLOWED_TERMINAL = {"EXPIRED", "CANCELED", "REJECTED"}
    _KNOWN_STATUSES = _ACTIVE | _ALLOWED_TERMINAL | _DISALLOWED_TERMINAL
    _SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    _SAFE_STAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

    def __init__(
        self,
        search_service: _SearchTaskReader,
        *,
        timeout: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        normalized_timeout = _finite_number(timeout)
        if normalized_timeout is None or normalized_timeout <= 0:
            raise ValueError("timeout 必须是有限的非 bool 正数")
        self._search_service = search_service
        self._timeout = normalized_timeout
        self._clock = clock
        self._sleep = sleep

    def wait_terminal(self, *, access_token: str, task_id: str) -> TaskWaitResult:
        """轮询指定任务直至允许终态，所有 HTTP 与等待均计入总预算。

        功能说明:
            持续读取任务直到允许终态，并将 HTTP 与退避纳入同一预算。
        参数说明:
            access_token: 最新会话 token，仅传给 SearchService；task_id: 待轮询任务。
        返回值:
            允许终态、最终业务快照和脱敏状态轨迹。
        异常说明:
            状态非法、业务失败、外部调用异常或 20 秒总预算耗尽时抛出
            :class:`TaskWaitError`。0–10 秒使用 2 秒间隔，之后使用 3 秒间隔。
        """
        trajectory: list[dict[str, Any]] = []
        previous_active_status: str | None = None
        last_clock: float | None = None

        def read_clock() -> float:
            """读取有限单调时钟，任何异常只暴露安全的异常类型。"""
            nonlocal last_clock
            clock_error_type: str | None = None
            raw_value: Any = None
            try:
                raw_value = self._clock()
            except Exception as exc:  # noqa: BLE001 - 必须安全包装注入时钟异常
                clock_error_type = self._safe_exception_type(exc)
            if clock_error_type is not None:
                raise self._error(
                    f"单调时钟读取失败: {clock_error_type}", trajectory
                ) from None
            current = _finite_number(raw_value)
            if current is None:
                raise self._error("单调时钟必须返回有限非 bool 数值", trajectory)
            if last_clock is not None and current < last_clock:
                raise self._error("单调时钟发生回退", trajectory)
            last_clock = current
            return current

        started_at = read_clock()
        deadline = started_at + float(self._timeout)
        if not math.isfinite(deadline):
            raise self._error("单调时钟与 timeout 无法形成有限截止时间", trajectory)

        while True:
            current = read_clock()
            if current >= deadline:
                raise self._error(f"等待任务 {self._timeout:g} 秒超时", trajectory)

            get_task_error_type: str | None = None
            response: GatewayResponse | None = None
            try:
                get_task = self._search_service.get_task
                call_kwargs: dict[str, Any] = {
                    "access_token": access_token,
                    "task_id": task_id,
                }
                if self._accepts_keyword(get_task, "read_timeout"):
                    call_kwargs["read_timeout"] = deadline - current
                response = get_task(**call_kwargs)
            except Exception as exc:  # noqa: BLE001 - 外部实现异常必须安全转换
                get_task_error_type = self._safe_exception_type(exc)
            if get_task_error_type is not None:
                raise self._error(
                    f"GetTask 调用异常: {get_task_error_type}", trajectory
                ) from None
            if response is None:
                raise self._error("GetTask 未返回响应", trajectory)

            response_time = read_clock()
            if response_time >= deadline:
                trajectory.append(
                    self._trace_entry(
                        status="TIME_BUDGET_EXCEEDED",
                        progress=None,
                        response=response,
                    )
                )
                raise self._error(f"等待任务 {self._timeout:g} 秒超时", trajectory)
            if not response.responses:
                raise self._error("GetTask 响应缺少业务子响应", trajectory)
            sub_response = next(
                (item for item in response.responses if item.id == "req_0"),
                response.responses[0],
            )

            if not sub_response.success or sub_response.code != 0:
                business_code = sub_response.business_error_code or "UNKNOWN_BUSINESS_ERROR"
                trajectory.append(
                    self._trace_entry(
                        status=self._safe_identifier(business_code),
                        progress=None,
                        response=response,
                    )
                )
                if business_code != "RATE_LIMITED":
                    raise self._error(
                        f"GetTask 业务失败: {self._safe_identifier(business_code)}",
                        trajectory,
                    )
                self._backoff(
                    now=response_time,
                    started_at=started_at,
                    deadline=deadline,
                    trajectory=trajectory,
                )
                continue

            data = sub_response.data
            if not isinstance(data, dict):
                raise self._error("GetTask 成功响应 data 不是对象", trajectory)
            status = data.get("status")
            progress = data.get("progress")
            if not isinstance(status, str):
                trajectory.append(
                    self._trace_entry(
                        status="<redacted>", progress=progress, response=response
                    )
                )
                raise self._error("GetTask status 必须是字符串", trajectory)
            if status not in self._KNOWN_STATUSES:
                safe_status = self._safe_identifier(status)
                trajectory.append(
                    self._trace_entry(
                        status=safe_status, progress=progress, response=response
                    )
                )
                raise self._error(f"任务返回未知状态: {safe_status}", trajectory)
            trajectory.append(
                self._trace_entry(status=status, progress=progress, response=response)
            )

            if status in self._ALLOWED_TERMINAL:
                return TaskWaitResult(status=status, data=data, trajectory=tuple(trajectory))
            if status in self._DISALLOWED_TERMINAL:
                raise self._error(f"任务进入非允许终态: {status}", trajectory)
            if (
                previous_active_status is not None
                and self._ACTIVE_ORDER[status]
                < self._ACTIVE_ORDER[previous_active_status]
            ):
                raise self._error(
                    f"任务状态从 {previous_active_status} 回退到 {status}", trajectory
                )
            previous_active_status = status
            self._backoff(
                now=response_time,
                started_at=started_at,
                deadline=deadline,
                trajectory=trajectory,
            )

    def wait(self, *, access_token: str, task_id: str) -> TaskWaitResult:
        """兼容旧调用方并委托 :meth:`wait_terminal`。

        功能说明:
            保留旧入口并完整委托 ``wait_terminal``。
        参数说明:
            access_token/task_id: 与 ``wait_terminal`` 相同。
        返回值:
            ``wait_terminal`` 返回的任务终态结果。
        异常说明:
            不改写 ``wait_terminal`` 的任何异常。
        """
        return self.wait_terminal(access_token=access_token, task_id=task_id)

    @staticmethod
    def _accepts_keyword(function: Callable[..., Any], name: str) -> bool:
        """判断真实 Service 或测试替身是否接受可选预算关键字。"""
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

    def _backoff(
        self,
        *,
        now: float,
        started_at: float,
        deadline: float,
        trajectory: list[dict[str, Any]],
    ) -> None:
        """使用绝对截止时间计算等待，确保单次 sleep 不越过总预算。"""
        elapsed = now - started_at
        remaining = deadline - now
        if remaining <= 0:
            raise self._error(f"等待任务 {self._timeout:g} 秒超时", trajectory)
        interval = 2.0 if elapsed < 10.0 else 3.0
        self._sleep(min(interval, remaining))

    @staticmethod
    def _trace_entry(
        *, status: Any, progress: Any, response: GatewayResponse
    ) -> dict[str, Any]:
        """只抽取协议允许的四个诊断字段，绝不复制其余业务数据。"""
        return {
            "status": TaskWaiter._safe_identifier(status),
            "progress": TaskWaiter._safe_progress(progress),
            "request_id": TaskWaiter._safe_identifier(response.request_id),
            "trace_id": TaskWaiter._safe_identifier(response.trace_id),
        }

    @staticmethod
    def _safe_progress(progress: Any) -> dict[str, Any] | None:
        """仅保留无个人内容的阶段与百分比，排除服务端扩展和展示文案。"""
        if not isinstance(progress, dict):
            return None
        safe: dict[str, Any] = {}
        stage = progress.get("stage")
        if isinstance(stage, str) and TaskWaiter._SAFE_STAGE.fullmatch(stage):
            safe["stage"] = stage
        percent = progress.get("display_percent")
        if type(percent) is int and 0 <= percent <= 100:
            safe["display_percent"] = percent
        return safe

    @staticmethod
    def _safe_identifier(value: Any) -> str:
        """仅允许有限长度的协议标识字符，其余值统一替换且不回显。"""
        if isinstance(value, str) and TaskWaiter._SAFE_IDENTIFIER.fullmatch(value):
            return value
        return "<redacted>"

    @staticmethod
    def _safe_exception_type(exc: Exception) -> str:
        """只返回安全的异常类名，绝不返回可能包含敏感数据的异常文本。"""
        type_name = type(exc).__name__
        safe_name = TaskWaiter._safe_identifier(type_name)
        return safe_name if safe_name != "<redacted>" else "Exception"

    @staticmethod
    def _error(message: str, trajectory: list[dict[str, Any]]) -> TaskWaitError:
        """构造带安全轨迹的中文异常。"""
        return TaskWaitError(f"{message}; 状态轨迹={trajectory!r}")


def wait_task_terminal(
    search_service: _SearchTaskReader,
    *,
    access_token: str,
    task_id: str,
    timeout: float = 20.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> TaskWaitResult:
    """使用函数式入口等待任务终态。

    功能说明:
        构造 ``TaskWaiter`` 并使用相同的预算和状态机执行等待。
    参数说明:
        search_service: 搜索读取 Service；access_token/task_id: 会话 token 与任务；
        timeout: 总预算秒数；clock/sleep: 可注入时钟与退避函数。
    返回值:
        允许终态的 ``TaskWaitResult``。
    异常说明:
        参数无效时抛 ``ValueError``；等待失败时抛 ``TaskWaitError``。
    """
    return TaskWaiter(
        search_service, timeout=timeout, clock=clock, sleep=sleep
    ).wait_terminal(access_token=access_token, task_id=task_id)
