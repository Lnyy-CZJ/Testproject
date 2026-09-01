"""CLI 与本地 Web 共用的 Dating 运行应用服务。

本模块只负责编排配置、Case Loader、Artifact、Adapter 和 Runner；它不包含 Flask 路由，也
不向调用方暴露任何公开接口的 Wire Schema。CLI 与 Web 通过同一服务执行，避免两套入口在
校验、轮询、限流、重试或 Cleanup 上出现行为漂移。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import Any, Protocol

from aidating_eval.adapters.internal_evaluation import InternalEvaluationAdapter
from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from aidating_eval.artifacts import ArtifactStore
from aidating_eval.cases import load_cases
from aidating_eval.config import Settings
from aidating_eval.domain import (
    CaseDefinition,
    CaseOutcome,
    CaseOutcomeStatus,
    DoctorCheck,
    RunContext,
    RunMode,
    TaskKind,
    new_run_id,
)
from aidating_eval.errors import CaseValidationError, ConfigurationError
from aidating_eval.evaluation_gateway import EvaluationGatewayClient
from aidating_eval.http import RequestsTransport
from aidating_eval.media_validation import inspect_media
from aidating_eval.public_gateway import PublicGatewayClient
from aidating_eval.runner import CaseRunner, RunControl
from aidating_eval.scheduling import (
    BatchRunner,
    CreatePacer,
    EvaluationRequestGate,
    calculate_eval_budget,
)
from aidating_eval.wire_logging import RawWireLogger


EXIT_OK = 0
EXIT_CASE_FAILURE = 1
EXIT_CONFIG_OR_INPUT = 2
EXIT_AUTH_OR_ENV = 3
EXIT_INCOMPLETE_OR_CLEANUP = 4

AUTH_OR_ENV_CODES = frozenset(
    {"UNAUTHENTICATED", "PERMISSION_DENIED", "FEATURE_NOT_READY"}
)


class AdapterFactory(Protocol):
    """为一次 Run 创建对应模式的 TaskFlowAdapter。"""

    def __call__(
        self,
        settings: Settings,
        *,
        create_pacer: CreatePacer | None = None,
        wire_logger: RawWireLogger | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class RunRequest:
    """Web/CLI 共享的运行请求；不包含凭证和 Gateway 地址。"""

    mode: RunMode | str
    dataset_path: Path
    fixture_root: Path | None = None
    case_id: str | None = None
    eval_concurrency: int | None = None
    source_name: str | None = None

    def normalized(self) -> "RunRequest":
        return replace(self, mode=RunMode(self.mode), dataset_path=Path(self.dataset_path))


@dataclass(frozen=True)
class ValidationSummary:
    """不含聊天正文、图片路径和凭证的本地校验摘要。"""

    mode: str
    task_kind: str
    case_ids: tuple[str, ...]
    case_count: int
    reply_count: int
    analysis_count: int
    message_count: int
    input_bytes: int
    media_count: int
    normal_create_requests: int
    worst_case_create_requests: int
    eval_concurrency: int | None
    media_items: tuple[Mapping[str, Any], ...] = ()


@dataclass
class PreparedRun:
    """已创建本地 Run 但尚未调用远端 Create Task 的执行上下文。"""

    run_id: str
    request: RunRequest
    cases: tuple[CaseDefinition, ...]
    settings: Settings
    artifact_store: ArtifactStore
    wire_logger: RawWireLogger
    summary: ValidationSummary


@dataclass(frozen=True)
class RunExecutionResult:
    """后台执行完成后的可序列化汇总。"""

    run_id: str
    status: str
    outcomes: tuple[CaseOutcome, ...]
    exit_code: int
    error_code: str | None = None


def build_adapter(
    settings: Settings,
    *,
    create_pacer: CreatePacer | None = None,
    wire_logger: RawWireLogger | None = None,
) -> PublicE2EAdapter | InternalEvaluationAdapter:
    """按模式装配真实 Adapter；Web 不得绕过该入口直接创建 Gateway Client。"""

    transport = RequestsTransport(wire_logger=wire_logger)
    if settings.mode == "e2e":
        gateway = PublicGatewayClient(
            transport,
            settings.public_gateway_url,
            device_id=settings.device_id,
            platform=settings.platform,
            app_version=settings.app_version,
            locale=settings.locale,
            timezone=settings.timezone,
            country=settings.country,
            app_package=settings.app_package,
        )
        return PublicE2EAdapter(
            gateway=gateway,
            transport=transport,
            settings=settings,
        )

    gateway = EvaluationGatewayClient(
        transport,
        settings.eval_base_url,
        settings.eval_api_key,
    )
    return InternalEvaluationAdapter(
        gateway=gateway,
        request_gate=EvaluationRequestGate.production(create_pacer=create_pacer),
    )


def load_and_validate(
    mode: RunMode | str,
    dataset: Path | str,
    *,
    fixture_root: Path | str | None = None,
) -> tuple[list[CaseDefinition], dict[str, Any]]:
    """读取并执行完整本地 Case 校验，同时返回安全统计。"""

    normalized_mode = RunMode(mode)
    if fixture_root is None:
        fixture_root = Path(os.getenv("AIDATING_E2E_FIXTURE_ROOT", "datasets"))
    cases = load_cases(
        dataset,
        normalized_mode.value,
        fixture_root=fixture_root if normalized_mode is RunMode.E2E else None,
    )
    media_items: list[dict[str, Any]] = []
    media_count = 0
    message_count = 0
    input_bytes = 0
    if normalized_mode is RunMode.E2E:
        for case in cases:
            for index, media_path in enumerate(case.media_paths, 1):
                inspected = inspect_media(media_path)
                media_count += 1
                input_bytes += inspected.size_bytes
                media_items.append(
                    {
                        "case_id": case.case_id,
                        "index": index,
                        "content_type": inspected.content_type,
                        "size_bytes": inspected.size_bytes,
                    }
                )
    else:
        for case in cases:
            message_count += len(case.messages)
            input_bytes += case.text_bytes
    return cases, {
        "case_count": len(cases),
        "media_count": media_count,
        "message_count": message_count,
        "input_bytes": input_bytes,
        "media_items": media_items,
    }


def select_case(
    cases: Sequence[CaseDefinition], case_id: str | None
) -> list[CaseDefinition]:
    """在完整数据集校验成功后选择单个 Case。"""

    if case_id is None:
        return list(cases)
    selected = [case for case in cases if case.case_id == case_id]
    if len(selected) != 1:
        raise CaseValidationError("--case 必须精确匹配数据集内唯一 case_id")
    return selected


def outcome_exit_code(outcomes: Sequence[CaseOutcome]) -> int:
    """使用 CLI 既有优先级汇总 Case 状态，供 Web 和 CLI 共用。"""

    if any(outcome.business_error_code in AUTH_OR_ENV_CODES for outcome in outcomes):
        return EXIT_AUTH_OR_ENV
    if any(
        outcome.status
        in {CaseOutcomeStatus.INCOMPLETE, CaseOutcomeStatus.CLEANUP_PENDING}
        for outcome in outcomes
    ):
        return EXIT_INCOMPLETE_OR_CLEANUP
    if any(outcome.status is CaseOutcomeStatus.FAILED for outcome in outcomes):
        return EXIT_CASE_FAILURE
    return EXIT_OK


def _create_wire_logger(
    command: str,
    *,
    mode: RunMode,
    run_id: str,
) -> RawWireLogger:
    """创建 Web Run 日志；完整日志保留给本地诊断，路径由 Manifest 绑定。"""

    root = Path(os.getenv("AIDATING_LOG_ROOT", "logs"))
    logger = RawWireLogger.create(root)
    logger.write(
        "log_started",
        command=command,
        mode=mode.value,
        run_id=run_id,
        warning="RAW_PRIVATE_DATA_NO_REDACTION",
    )
    return logger


class RunApplicationService:
    """编排本地校验、真实 Adapter 生命周期和 Artifact 汇总。"""

    def __init__(
        self,
        *,
        settings_factory: Callable[[str], Settings] | None = None,
        adapter_factory: AdapterFactory | None = None,
    ) -> None:
        # 在实例化时读取类方法，便于 CLI/测试通过依赖注入替换环境配置；不要把
        # ``Settings.from_env`` 作为默认参数绑定在模块导入时。
        self.settings_factory = settings_factory or Settings.from_env
        self.adapter_factory = adapter_factory or build_adapter

    def doctor(
        self,
        mode: RunMode | str,
        *,
        wire_logger: RawWireLogger | None = None,
    ) -> list[DoctorCheck]:
        """执行现有 Adapter 的只读环境检查，不返回配置值。"""

        normalized_mode = RunMode(mode)
        settings = self.settings_factory(normalized_mode.value)
        adapter = self.adapter_factory(settings, wire_logger=wire_logger)
        return adapter.doctor()

    def validate(self, request: RunRequest) -> ValidationSummary:
        """只执行 Loader、媒体格式和预算校验；该方法不得触发网络。"""

        normalized = request.normalized()
        cases, totals = load_and_validate(
            normalized.mode,
            normalized.dataset_path,
            fixture_root=normalized.fixture_root,
        )
        selected = select_case(cases, normalized.case_id)
        task_kinds = {str(case.task_kind) for case in selected}
        task_kind = next(iter(task_kinds)) if len(task_kinds) == 1 else "mixed"
        concurrency: int | None = None
        normal_create = 0
        worst_create = 0
        if normalized.mode is RunMode.EVAL:
            concurrency = normalized.eval_concurrency
            if concurrency is None:
                raw = os.getenv("AIDATING_EVAL_CONCURRENCY", "3")
                try:
                    concurrency = int(raw)
                except ValueError as exc:
                    raise ConfigurationError(
                        "AIDATING_EVAL_CONCURRENCY 必须为整数"
                    ) from exc
            budget = calculate_eval_budget(selected, max_workers=concurrency)
            normal_create = budget.normal_create_requests
            worst_create = budget.worst_create_requests
        return ValidationSummary(
            mode=normalized.mode.value,
            task_kind=task_kind,
            case_ids=tuple(case.case_id for case in selected),
            case_count=len(selected),
            reply_count=sum(case.task_kind is TaskKind.REPLY for case in selected),
            analysis_count=sum(
                case.task_kind is TaskKind.ANALYSIS for case in selected
            ),
            message_count=sum(len(getattr(case, "messages", ())) for case in selected),
            input_bytes=(
                sum(case.text_bytes for case in selected)
                if normalized.mode is RunMode.EVAL
                else sum(
                    item["size_bytes"]
                    for item in totals["media_items"]
                    if item["case_id"] in {case.case_id for case in selected}
                )
            ),
            media_count=sum(len(getattr(case, "media_paths", ())) for case in selected),
            normal_create_requests=normal_create,
            worst_case_create_requests=worst_create,
            eval_concurrency=concurrency,
            media_items=tuple(
                item
                for item in totals["media_items"]
                if item["case_id"] in {case.case_id for case in selected}
            ),
        )

    def prepare(
        self,
        request: RunRequest,
        *,
        run_id: str | None = None,
        wire_logger: RawWireLogger | None = None,
    ) -> PreparedRun:
        """创建本地 Run 上下文；在 execute 前不创建任何远端 Task。"""

        normalized = request.normalized()
        summary = self.validate(normalized)
        all_cases, _ = load_and_validate(
            normalized.mode,
            normalized.dataset_path,
            fixture_root=normalized.fixture_root,
        )
        selected = tuple(select_case(all_cases, normalized.case_id))
        settings = self.settings_factory(normalized.mode.value)
        if normalized.mode is RunMode.EVAL and normalized.eval_concurrency is not None:
            if not 1 <= normalized.eval_concurrency <= 5:
                raise ConfigurationError(
                    "AIDATING_EVAL_CONCURRENCY 必须在 1 到 5 之间"
                )
            settings = replace(settings, eval_concurrency=normalized.eval_concurrency)
        resolved_run_id = run_id or new_run_id()
        artifacts = ArtifactStore(settings.artifacts_root, resolved_run_id)
        artifacts.start_run(settings.redacted())
        logger = wire_logger or _create_wire_logger(
            "web-run",
            mode=normalized.mode,
            run_id=resolved_run_id,
        )
        logger.write(
            "run_bound",
            mode=normalized.mode.value,
            run_id=resolved_run_id,
        )
        artifacts.update_manifest(
            {
                "mode": normalized.mode.value,
                "task_kind": (
                    str(selected[0].task_kind)
                    if selected and len({str(item.task_kind) for item in selected}) == 1
                    else "mixed"
                ),
                "case_ids": [item.case_id for item in selected],
                "case_count": len(selected),
                "wire_log_path": self._wire_log_relative(logger),
                "summary": {
                    "case_count": summary.case_count,
                    "reply_count": summary.reply_count,
                    "analysis_count": summary.analysis_count,
                    "message_count": summary.message_count,
                    "input_bytes": summary.input_bytes,
                    "media_count": summary.media_count,
                    "normal_create_requests": summary.normal_create_requests,
                    "worst_case_create_requests": summary.worst_case_create_requests,
                    "eval_concurrency": summary.eval_concurrency,
                },
                "cancel_requested": False,
                "cleanup_status": "pending",
            }
        )
        return PreparedRun(
            run_id=resolved_run_id,
            request=normalized,
            cases=selected,
            settings=settings,
            artifact_store=artifacts,
            wire_logger=logger,
            summary=summary,
        )

    @staticmethod
    def _wire_log_relative(logger: RawWireLogger) -> str | None:
        """把日志路径绑定到 Manifest；绝不把请求正文复制到 Manifest。"""

        try:
            root = Path(os.getenv("AIDATING_LOG_ROOT", "logs")).resolve()
            return Path(logger.path).resolve().relative_to(root).as_posix()
        except (AttributeError, TypeError, ValueError):
            return str(getattr(logger, "path", "")) or None

    def execute(
        self,
        prepared: PreparedRun,
        *,
        control: RunControl,
    ) -> RunExecutionResult:
        """复用现有 Runner 执行一整个 Run，不打印业务正文。"""

        if not prepared.cases:
            raise ConfigurationError("Run 至少需要一个合法 Case")
        mode = RunMode(prepared.request.mode)
        first_case = prepared.cases[0]
        adapter: Any
        if mode is RunMode.E2E:
            adapter = self.adapter_factory(
                prepared.settings,
                wire_logger=prepared.wire_logger,
            )
            adapter.prepare_run(
                RunContext.for_case(
                    prepared.run_id,
                    first_case.case_id,
                    mode,
                    first_case.task_kind,
                )
            )
            outcomes: list[CaseOutcome] = []
            for case in prepared.cases:
                if not control.may_start_new_case():
                    outcomes.append(CaseOutcome.not_started(case.case_id, "RUN_STOP_REQUESTED"))
                    continue
                outcomes.append(
                    CaseRunner(
                        adapter,
                        prepared.artifact_store,
                        run_control=control,
                    ).execute(
                        case,
                        RunContext.for_case(
                            prepared.run_id,
                            case.case_id,
                            mode,
                            case.task_kind,
                        ),
                    )
                )
        else:
            create_pacer = CreatePacer(2)
            adapter = self.adapter_factory(
                prepared.settings,
                create_pacer=create_pacer,
                wire_logger=prepared.wire_logger,
            )
            adapter.prepare_run(
                RunContext.for_case(
                    prepared.run_id,
                    first_case.case_id,
                    mode,
                    first_case.task_kind,
                )
            )
            batch = BatchRunner(
                lambda _: CaseRunner(
                    adapter,
                    prepared.artifact_store,
                    run_control=control,
                ),
                max_workers=prepared.settings.eval_concurrency,
                create_pacer=create_pacer,
                run_control=control,
            )
            outcomes = batch.run(
                prepared.cases,
                lambda case: RunContext.for_case(
                    prepared.run_id,
                    case.case_id,
                    mode,
                    case.task_kind,
                ),
            )
        exit_code = outcome_exit_code(outcomes)
        status = _run_status(outcomes, control)
        return RunExecutionResult(
            run_id=prepared.run_id,
            status=status,
            outcomes=tuple(outcomes),
            exit_code=exit_code,
            error_code=control.reason if status in {"blocked", "cancelled"} else None,
        )


def _run_status(outcomes: Sequence[CaseOutcome], control: RunControl) -> str:
    """把既有 Case Outcome 汇总为 Web 可展示的 Run 状态。"""

    if any(item.status is CaseOutcomeStatus.CLEANUP_PENDING for item in outcomes):
        return "cleanup_pending"
    if control.reason == "RUN_CANCELLED":
        return "cancelled"
    if any(item.business_error_code in AUTH_OR_ENV_CODES for item in outcomes):
        return "blocked"
    if any(item.status is CaseOutcomeStatus.INCOMPLETE for item in outcomes):
        return "failed"
    if any(item.status is CaseOutcomeStatus.FAILED for item in outcomes):
        return "failed"
    return "completed"
