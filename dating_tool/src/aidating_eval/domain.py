"""Runner 与 Adapter 之间共享的稳定领域类型。

领域模型刻意不包含任何 Gateway 信封字段；公开接口和内部 Evaluation 的 Wire Schema
分别留在各自 Adapter 中，避免未来一个协议变化时污染另一条链路。
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


class RunMode(StrEnum):
    """工具支持的两种互斥运行模式。"""

    E2E = "e2e"
    EVAL = "eval"


class TaskKind(StrEnum):
    """Dating 后端当前支持的两类 AI 任务。"""

    REPLY = "reply"
    ANALYSIS = "analysis"


class TaskStatus(StrEnum):
    """服务端稳定任务状态。"""

    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class NegativeVariant(StrEnum):
    """允许工具由合法 Case 派生的受控负向请求。"""

    MESSAGE_COUNT_BELOW_MIN = "message_count_below_min"
    INSUFFICIENT_PARTY_MESSAGES = "insufficient_party_messages"
    DUPLICATE_MESSAGE_ID = "duplicate_message_id"
    UNSUPPORTED_FIELD = "unsupported_field"
    IDEMPOTENCY_SAME = "idempotency_same"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


@dataclass(frozen=True)
class TranscriptMessage:
    """已规范化的消息；输入中的 ``self`` 在这里已经变为 ``user``。"""

    message_id: str
    message_type: str
    speaker: str
    text: str


@dataclass(frozen=True)
class CaseExpectation:
    """只描述可确定验证的状态、Schema 和稳定 code。"""

    task_status: str | None = "succeeded"
    result_schema: str | None = None
    business_error_code: str | None = None
    warning_codes: tuple[str, ...] = ()
    policy_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplyPreferences:
    """公开 Reply 在创建任务之前写入的用户偏好。"""

    dating_goal: str
    your_voice: str


@dataclass(frozen=True)
class E2EReplyCase:
    """通过截图、OCR 和公开 Reply Pipeline 执行的案例。"""

    case_id: str
    locale: str
    media_paths: tuple[Path, ...]
    preferences: ReplyPreferences
    requested_intent: str | None
    background: str | None
    expect: CaseExpectation = field(
        default_factory=lambda: CaseExpectation(
            result_schema="dating.reply_generation.v1"
        )
    )

    @property
    def task_kind(self) -> TaskKind:
        return TaskKind.REPLY


@dataclass(frozen=True)
class E2EAnalysisCase:
    """通过截图、OCR 和公开 Analysis Pipeline 执行的案例。"""

    case_id: str
    locale: str
    media_paths: tuple[Path, ...]
    other_person_name: str | None
    background: str | None
    expect: CaseExpectation = field(
        default_factory=lambda: CaseExpectation(
            result_schema="dating.relationship_analysis.v1"
        )
    )

    @property
    def task_kind(self) -> TaskKind:
        return TaskKind.ANALYSIS


@dataclass(frozen=True)
class EvaluationReplyCase:
    """直接提交结构化 Transcript 的内部 Reply 案例。"""

    case_id: str
    locale: str
    messages: tuple[TranscriptMessage, ...]
    dating_goal: str
    your_voice: str
    requested_intent: str | None = None
    background: str | None = None
    negative_variant: NegativeVariant | None = None
    expect: CaseExpectation = field(
        default_factory=lambda: CaseExpectation(
            result_schema="dating.reply_generation.v1"
        )
    )

    @property
    def task_kind(self) -> TaskKind:
        return TaskKind.REPLY

    @property
    def text_bytes(self) -> int:
        return sum(len(message.text.encode("utf-8")) for message in self.messages)


@dataclass(frozen=True)
class EvaluationAnalysisCase:
    """直接提交结构化 Transcript 的内部 Analysis 案例。"""

    case_id: str
    locale: str
    messages: tuple[TranscriptMessage, ...]
    negative_variant: NegativeVariant | None = None
    expect: CaseExpectation = field(
        default_factory=lambda: CaseExpectation(
            result_schema="dating.relationship_analysis.v1"
        )
    )

    @property
    def task_kind(self) -> TaskKind:
        return TaskKind.ANALYSIS

    @property
    def text_bytes(self) -> int:
        return sum(len(message.text.encode("utf-8")) for message in self.messages)


CaseDefinition = (
    E2EReplyCase
    | E2EAnalysisCase
    | EvaluationReplyCase
    | EvaluationAnalysisCase
)


@dataclass(frozen=True)
class PollPolicy:
    """轮询时限与分阶段间隔；时间由 Runner 注入以便确定性测试。"""

    timeout_seconds: float
    initial_interval_seconds: float
    steady_interval_seconds: float
    switch_after_seconds: float = 0

    def interval_for(self, elapsed_seconds: float) -> float:
        if elapsed_seconds < self.switch_after_seconds:
            return self.initial_interval_seconds
        return self.steady_interval_seconds


@dataclass(frozen=True)
class TaskSnapshot:
    """Adapter 将不同后端任务响应规范化后的只读快照。"""

    task_id: str
    task_type: str
    status: TaskStatus
    phase: str
    retryable: bool = False
    error_code: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, TaskStatus):
            object.__setattr__(self, "status", TaskStatus(self.status))


class CaseOutcomeStatus(StrEnum):
    """单案例最终状态；清理失败独立于业务结果。"""

    COMPLETED = "completed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    CLEANUP_PENDING = "cleanup_pending"


@dataclass(frozen=True)
class RunContext:
    """把 Run、Attempt、模式和任务类型绑定，避免并发 Adapter 共享可变状态。"""

    run_id: str
    attempt_id: str
    mode: RunMode
    task_kind: TaskKind

    @classmethod
    def for_case(
        cls,
        run_id: str,
        case_id: str,
        mode: RunMode,
        task_kind: TaskKind,
    ) -> "RunContext":
        return cls(
            run_id=run_id,
            attempt_id=f"{case_id}-{uuid4().hex[:12]}",
            mode=mode,
            task_kind=task_kind,
        )

    def next_attempt(self, case_id: str) -> "RunContext":
        return RunContext.for_case(self.run_id, case_id, self.mode, self.task_kind)


def new_run_id() -> str:
    """生成可用于目录和后端追踪的 UTC Run ID。"""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid4().hex[:8]}"


@dataclass(frozen=True)
class PreparedCase:
    """Adapter 的完整内存 Payload 与可落盘安全元数据。"""

    payload: Mapping[str, Any] = field(repr=False)
    safe_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CleanupResult:
    """删除结果；``already_absent`` 也视为成功。"""

    success: bool
    status: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class CaseOutcome:
    """Runner 返回给批量调度和 CLI 的最小确定性结果。"""

    case_id: str
    status: CaseOutcomeStatus
    task_id: str | None
    business_error_code: str | None
    schema_version: str | None
    cleanup: CleanupResult | None
    retryable: bool = False

    @classmethod
    def not_started(cls, case_id: str, code: str) -> "CaseOutcome":
        return cls(
            case_id=case_id,
            status=CaseOutcomeStatus.INCOMPLETE,
            task_id=None,
            business_error_code=code,
            schema_version=None,
            cleanup=None,
        )


class DoctorStatus(StrEnum):
    """doctor 检查既能失败，也能把只可在真实链路验证的项目延期。"""

    PASS = "PASS"
    FAIL = "FAIL"
    DEFERRED = "DEFERRED"


@dataclass(frozen=True)
class DoctorCheck:
    """doctor 命令的单项机器可读结果。"""

    name: str
    status: DoctorStatus
    safe_message: str


@dataclass(frozen=True)
class SessionTokens:
    """只驻留内存的完整 Public Token 对。"""

    user_id: str = field(repr=False)
    access_token: str = field(repr=False)
    access_expires_time: int
    refresh_token: str = field(repr=False)
    refresh_expires_time: int
