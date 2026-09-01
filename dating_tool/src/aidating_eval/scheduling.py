"""内部 Evaluation 的共享限流、预算预检和有界并发调度。

这里的三个时间控制器都允许注入单调时钟和 sleep，因此单元测试不会真实等待。生产运行
时，同一批次的所有 Worker 必须共享这些实例，才能让 Create、轮询、结果、诊断和删除
共同遵守 Admin Gateway 的总请求上限。
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import math
from threading import Condition, Lock
from time import monotonic, sleep
from typing import Protocol

from aidating_eval.domain import (
    CaseDefinition,
    CaseOutcome,
    NegativeVariant,
    RunContext,
    RunMode,
)
from aidating_eval.errors import ConfigurationError
from aidating_eval.runner import RunControl


class SlidingWindowRateLimiter:
    """线程安全的滑动窗口限流器。

    ``acquire`` 在真正发出 Gateway 请求前调用。窗口已满时只等待最早一条记录退出
    窗口，不做忙轮询；醒来后重新检查，因而能正确处理多个 Worker 同时竞争。
    """

    def __init__(
        self,
        *,
        max_calls: int,
        period_seconds: float,
        monotonic_fn: Callable[[], float] = monotonic,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        if max_calls < 1 or period_seconds <= 0:
            raise ValueError("滑动窗口参数必须为正数")
        self.max_calls = max_calls
        self.period_seconds = float(period_seconds)
        self.monotonic_fn = monotonic_fn
        self.sleep_fn = sleep_fn
        self._calls: deque[float] = deque()
        self._condition = Condition()

    def acquire(self) -> None:
        while True:
            with self._condition:
                now = self.monotonic_fn()
                while self._calls and now - self._calls[0] >= self.period_seconds:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    self._condition.notify_all()
                    return
                wait_seconds = max(
                    0.0, self.period_seconds - (now - self._calls[0])
                )
            # 释放锁后等待，避免一个睡眠 Worker 阻塞已经具备配额的其他线程。
            self.sleep_fn(wait_seconds)


class CreatePacer:
    """保证内部 Create 请求的开始时间至少相隔指定秒数。"""

    def __init__(
        self,
        spacing_seconds: float,
        *,
        monotonic_fn: Callable[[], float] = monotonic,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        if spacing_seconds < 0:
            raise ValueError("Create 间隔不得为负数")
        self.spacing_seconds = float(spacing_seconds)
        self.monotonic_fn = monotonic_fn
        self.sleep_fn = sleep_fn
        self._lock = Lock()
        self._last_started_at: float | None = None

    @classmethod
    def disabled(cls) -> "CreatePacer":
        """返回测试或单次纯内存调用使用的无等待 Pacer。"""

        return cls(0)

    def acquire(self) -> None:
        # 故意在锁内等待：Create 必须全局串行决定开始时间，否则多个 Worker 会取得同一
        # last_started_at 并一起越过服务端每分钟 30 次的限制。
        with self._lock:
            now = self.monotonic_fn()
            if self._last_started_at is not None:
                wait_seconds = self.spacing_seconds - (
                    now - self._last_started_at
                )
                if wait_seconds > 0:
                    self.sleep_fn(wait_seconds)
                    now = self.monotonic_fn()
            self._last_started_at = now

    def mark_admitted_now(self) -> None:
        """把最后一次 Create 时间校准到组合准入的真实放行时刻。

        ``acquire`` 之后总速率限制仍可能等待。若不校准，下一条 Create 会相对较早的
        预留时间计算间隔，多个 Worker 可能在总窗口释放时聚集。
        """

        with self._lock:
            self._last_started_at = self.monotonic_fn()


class SharedCooldown:
    """把任意 Worker 收到的服务端 ``retry_after`` 共享给整个批次。"""

    def __init__(
        self,
        *,
        monotonic_fn: Callable[[], float] = monotonic,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self.monotonic_fn = monotonic_fn
        self.sleep_fn = sleep_fn
        self._condition = Condition()
        self._blocked_until = 0.0
        self._version = 0

    def defer(self, retry_after_seconds: float | None) -> float:
        """登记 1～300 秒的安全等待；缺失或异常值按最保守的 300 秒处理。"""

        if (
            isinstance(retry_after_seconds, bool)
            or not isinstance(retry_after_seconds, (int, float))
            or not math.isfinite(float(retry_after_seconds))
        ):
            seconds = 300.0
        else:
            seconds = min(300.0, max(1.0, float(retry_after_seconds)))
        with self._condition:
            self._blocked_until = max(
                self._blocked_until, self.monotonic_fn() + seconds
            )
            # version 让已经通过第一次 cooldown 检查、但仍卡在 Create pacing 或总限流
            # 的 Worker 能发现新登记的服务端退避，而不是穿透共享 cooldown。
            self._version += 1
            self._condition.notify_all()
        return seconds

    def wait_if_needed(self) -> int:
        """等待当前 cooldown 结束，并返回用于最终放行复查的版本号。"""

        while True:
            with self._condition:
                remaining = self._blocked_until - self.monotonic_fn()
                if remaining <= 0:
                    return self._version
            self.sleep_fn(remaining)

    def is_current_and_clear(self, version: int) -> bool:
        """确认等待期间没有其他 Worker 登记新的 retry-after。"""

        with self._condition:
            return (
                version == self._version
                and self._blocked_until <= self.monotonic_fn()
            )


@dataclass(frozen=True)
class EvaluationRequestGate:
    """Adapter 在每次 Admin Gateway 调用前使用的共享时间控制集合。"""

    rate_limiter: SlidingWindowRateLimiter
    create_pacer: CreatePacer
    cooldown: SharedCooldown
    _create_admission_lock: Lock = field(
        default_factory=Lock, repr=False, compare=False
    )

    @classmethod
    def production(
        cls,
        *,
        create_pacer: CreatePacer | None = None,
    ) -> "EvaluationRequestGate":
        return cls(
            SlidingWindowRateLimiter(max_calls=120, period_seconds=60),
            create_pacer or CreatePacer(2),
            SharedCooldown(),
        )

    @classmethod
    def disabled(cls) -> "EvaluationRequestGate":
        """为协议单测关闭真实节奏，但仍经过相同调用入口。"""

        return cls(
            SlidingWindowRateLimiter(max_calls=1_000_000, period_seconds=1),
            CreatePacer.disabled(),
            SharedCooldown(),
        )

    def before_request(self, *, is_create: bool) -> None:
        if is_create:
            # Create 的 spacing、总窗口令牌和 cooldown 最终检查是一个组合准入事务。
            # 专用锁只串行 Create，不阻塞 Task/Result/Diagnostics/Delete 的正常并发。
            with self._create_admission_lock:
                self._before_create_request()
            return

        self._before_non_create_request()

    def _before_create_request(self) -> None:
        while True:
            cooldown_version = self.cooldown.wait_if_needed()
            self.create_pacer.acquire()
            self.rate_limiter.acquire()
            if self.cooldown.is_current_and_clear(cooldown_version):
                # 限流器令牌在此刻刚刚取得；将 Pacer 时间同步到真实放行点，使下一条
                # Create 同时满足“真实请求间隔”和“真实请求滑动窗口”两条约束。
                self.create_pacer.mark_admitted_now()
                return

    def _before_non_create_request(self) -> None:
        while True:
            cooldown_version = self.cooldown.wait_if_needed()
            self.rate_limiter.acquire()
            # 等待总窗口期间可能登记新 cooldown；令牌宁可保守消耗，也不能抢跑。
            if self.cooldown.is_current_and_clear(cooldown_version):
                return


@dataclass(frozen=True)
class EvalBatchBudget:
    """不含正文的批次预算摘要，可安全打印到控制台和 manifest。"""

    case_count: int
    normal_create_requests: int
    worst_create_requests: int
    message_count: int
    input_bytes: int
    worst_input_bytes: int
    max_workers: int


def calculate_eval_budget(
    cases: Sequence[CaseDefinition], *, max_workers: int
) -> EvalBatchBudget:
    """按一次明确 retryable 重建计算最坏 Create 和输入预算。

    幂等专项每次 Attempt 会发送两次 Create，因此其最坏请求倍数为四；普通 Case 的
    最坏倍数为二。该预检只保护本次 Run，服务账号当日已用额度仍以后端为准。
    """

    if not 1 <= max_workers <= 5:
        raise ConfigurationError("EVAL_MAX_WORKERS_MUST_BE_BETWEEN_1_AND_5")
    normal_create_requests = 0
    worst_create_requests = 0
    message_count = 0
    input_bytes = 0
    worst_input_bytes = 0
    for case in cases:
        messages = getattr(case, "messages", None)
        if messages is None:
            raise ConfigurationError("Eval 批次只能包含结构化 Transcript Case")
        count = len(messages)
        size = sum(len(item.text.encode("utf-8")) for item in messages)
        idempotency = getattr(case, "negative_variant", None) in {
            NegativeVariant.IDEMPOTENCY_SAME,
            NegativeVariant.IDEMPOTENCY_CONFLICT,
        }
        normal_multiplier = 2 if idempotency else 1
        worst_multiplier = normal_multiplier * 2
        normal_create_requests += normal_multiplier
        worst_create_requests += worst_multiplier
        message_count += count
        input_bytes += size * normal_multiplier
        worst_input_bytes += size * worst_multiplier

    if worst_create_requests > 1_000:
        raise ConfigurationError("EVAL_BATCH_DAILY_TASK_BUDGET_EXCEEDED")
    if worst_input_bytes > 268_435_456:
        raise ConfigurationError("EVAL_BATCH_INPUT_BUDGET_EXCEEDED")
    return EvalBatchBudget(
        len(cases),
        normal_create_requests,
        worst_create_requests,
        message_count,
        input_bytes,
        worst_input_bytes,
        max_workers,
    )


class _CaseRunnerLike(Protocol):
    def execute(self, case: CaseDefinition, context: RunContext) -> CaseOutcome: ...


class BatchRunner:
    """以最多五个 Worker 并发执行 Eval Case，并保持输入结果顺序。"""

    def __init__(
        self,
        case_runner_factory: Callable[[CreatePacer], _CaseRunnerLike],
        *,
        max_workers: int,
        create_pacer: CreatePacer,
        run_control: RunControl,
    ) -> None:
        if not 1 <= max_workers <= 5:
            raise ValueError("max_workers 必须在 1 到 5 之间")
        self.case_runner_factory = case_runner_factory
        self.max_workers = max_workers
        self.create_pacer = create_pacer
        self.run_control = run_control

    def run(
        self,
        cases: Iterable[CaseDefinition],
        context_factory: Callable[[CaseDefinition], RunContext],
    ) -> list[CaseOutcome]:
        case_list = list(cases)
        calculate_eval_budget(case_list, max_workers=self.max_workers)

        def execute(case: CaseDefinition) -> CaseOutcome:
            # ThreadPoolExecutor 可能已提交全部 Future；因此必须在线程真正开始时再检查，
            # 确保鉴权失败或信号停止后不会创建新的远端 Task。
            if not self.run_control.may_start_new_case():
                return CaseOutcome.not_started(case.case_id, "RUN_STOP_REQUESTED")
            runner = self.case_runner_factory(self.create_pacer)
            return runner.execute(case, context_factory(case))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            return list(executor.map(execute, case_list))
