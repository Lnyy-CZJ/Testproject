"""与协议无关的单案例任务状态机。"""

from collections.abc import Callable, Mapping
from threading import Event, Lock
from time import monotonic, sleep
from typing import Any, Protocol

from aidating_eval.domain import (
    CaseDefinition,
    CaseOutcome,
    CaseOutcomeStatus,
    CleanupResult,
    RunContext,
    RunMode,
    TaskSnapshot,
    TaskStatus,
)
from aidating_eval.errors import (
    BusinessError,
    ContractError,
    DatingEvalError,
    RunInterrupted,
    TransportError,
)
from aidating_eval.ports import TaskFlowAdapter


RUN_STOP_BUSINESS_CODES = frozenset(
    {"UNAUTHENTICATED", "PERMISSION_DENIED", "FEATURE_NOT_READY"}
)

# 服务端 ``retryable`` 只是一个输入信号，不能推翻工具冻结的重建策略。MVP 只允许内部
# Evaluation 的瞬时 INTERNAL 失败在成功清理旧 Task 后使用新 Attempt 重建一次。
RECREATE_RETRYABLE_CODES = frozenset({"INTERNAL"})


class ArtifactWriter(Protocol):
    def append_event(
        self,
        case_id: str,
        event: str,
        data: Mapping[str, Any] | None = None,
    ) -> None: ...

    def write_case_payload(
        self,
        case_id: str,
        filename: str,
        payload: Mapping[str, Any],
    ) -> Any: ...


class RunControl:
    """协调用户中断和批次级致命错误，不保存服务端自由文本。"""

    def __init__(self) -> None:
        self._stopped = Event()
        self._lock = Lock()
        self._reason: str | None = None

    @property
    def reason(self) -> str | None:
        return self._reason

    def request_stop(self, stable_reason: str) -> None:
        with self._lock:
            self._reason = self._reason or stable_reason
            self._stopped.set()

    def may_start_new_case(self) -> bool:
        return not self._stopped.is_set()

    def raise_if_stopped(self) -> None:
        if self._stopped.is_set():
            raise RunInterrupted(self._reason or "RUN_STOP_REQUESTED")


class CaseRunner:
    """执行最多两次尝试，并对每个已取得的 Task ID 进行 finally 删除。"""

    def __init__(
        self,
        adapter: TaskFlowAdapter,
        artifacts: ArtifactWriter,
        *,
        sleep_fn: Callable[[float], None] = sleep,
        monotonic_fn: Callable[[], float] = monotonic,
        run_control: RunControl | None = None,
    ) -> None:
        self.adapter = adapter
        self.artifacts = artifacts
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn
        self.run_control = run_control or RunControl()

    def execute(self, case: CaseDefinition, context: RunContext) -> CaseOutcome:
        """执行案例；仅 retryable failed 且清理成功时创建第二次 Attempt。"""

        outcome = self._execute_once(case, context)
        if (
            not outcome.retryable
            or outcome.status is CaseOutcomeStatus.COMPLETED
            or outcome.status is CaseOutcomeStatus.CLEANUP_PENDING
            or self.run_control.may_start_new_case() is False
        ):
            return outcome
        return self._execute_once(case, context.next_attempt(case.case_id))

    def _event(
        self,
        case: CaseDefinition,
        context: RunContext,
        name: str,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        values = {
            "attempt_id": context.attempt_id,
            "mode": context.mode,
            "task_kind": case.task_kind,
            **dict(data or {}),
        }
        self.artifacts.append_event(case.case_id, name, values)

    def _safe_event(
        self,
        case: CaseDefinition,
        context: RunContext,
        name: str,
        data: Mapping[str, Any] | None = None,
    ) -> bool:
        """清理阶段 best-effort 写事件；本地磁盘异常不得阻断远端 Delete。"""

        try:
            self._event(case, context, name, data)
        except Exception:
            return False
        return True

    def _safe_write_case_payload(
        self,
        case: CaseDefinition,
        filename: str,
        payload: Mapping[str, Any],
    ) -> bool:
        """清理阶段 best-effort 写 JSON，并把失败转换为稳定生命周期错误。"""

        try:
            self.artifacts.write_case_payload(case.case_id, filename, payload)
        except Exception:
            return False
        return True

    @staticmethod
    def _retry_allowed(
        context: RunContext, business_code: str | None, server_retryable: bool
    ) -> bool:
        return (
            context.mode is RunMode.EVAL
            and server_retryable
            and business_code in RECREATE_RETRYABLE_CODES
        )

    @staticmethod
    def _observed_error_task_ids(exc: BaseException) -> tuple[str, ...]:
        values = getattr(exc, "task_ids_to_cleanup", ())
        if not isinstance(values, tuple):
            return ()
        return tuple(
            value for value in values if isinstance(value, str) and value
        )

    def _execute_once(
        self,
        case: CaseDefinition,
        context: RunContext,
    ) -> CaseOutcome:
        task_ids: list[str] = []
        task_ids_with_recovery_event: set[str] = set()
        cleanup: CleanupResult | None = None
        outcome_status = CaseOutcomeStatus.FAILED
        business_code: str | None = None
        schema_version: str | None = None
        retryable = False
        expected_error = case.expect.business_error_code

        def observe(*values: str) -> None:
            for value in values:
                if value and value not in task_ids:
                    task_ids.append(value)

        self._event(case, context, "case_started")
        try:
            self.run_control.raise_if_stopped()
            self.artifacts.write_case_payload(
                case.case_id,
                "metadata.json",
                {
                    "case_id": case.case_id,
                    "mode": context.mode,
                    "task_kind": case.task_kind,
                    "locale": case.locale,
                    "attempt_id": context.attempt_id,
                },
            )
            self._event(case, context, "prepare_started")
            prepared = self.adapter.prepare_case(case, context)
            self._event(case, context, "case_prepared", prepared.safe_metadata)

            self.run_control.raise_if_stopped()
            created = self.adapter.create_task(case, prepared, context)
            observe(created.task_id)
            self._event(
                case,
                context,
                "task_created",
                {"task_id": created.task_id, "task_type": created.task_type},
            )
            task_ids_with_recovery_event.add(created.task_id)
            terminal = self._poll_until_terminal(case, context, created)
            self.artifacts.write_case_payload(case.case_id, "task.json", terminal.raw)
            status_matches = (
                case.expect.task_status is None
                or terminal.status.value == case.expect.task_status
            )

            if terminal.status is TaskStatus.SUCCEEDED:
                result = self.adapter.get_result(created.task_id, case, context)
                schema_version = str(result.get("schema_version", ""))
                self.artifacts.write_case_payload(case.case_id, "result.json", result)
                self._event(
                    case,
                    context,
                    "result_fetched",
                    {"task_id": created.task_id},
                )
                if expected_error is not None:
                    business_code = "EXPECTED_BUSINESS_ERROR_NOT_OBSERVED"
                elif not status_matches:
                    business_code = "UNEXPECTED_TASK_STATUS"
                elif case.expect.result_schema and schema_version != case.expect.result_schema:
                    business_code = "RESULT_SCHEMA_MISMATCH"
                else:
                    outcome_status = CaseOutcomeStatus.COMPLETED
                if business_code:
                    outcome_status = CaseOutcomeStatus.FAILED
            else:
                business_code = terminal.error_code
                retryable = self._retry_allowed(
                    context,
                    business_code,
                    terminal.status is TaskStatus.FAILED and terminal.retryable,
                )
                outcome_status = (
                    CaseOutcomeStatus.COMPLETED
                    if status_matches
                    and (expected_error is None or business_code == expected_error)
                    else CaseOutcomeStatus.FAILED
                )
        except TimeoutError:
            business_code = "TASK_TIMEOUT"
            outcome_status = CaseOutcomeStatus.INCOMPLETE
            self._safe_event(
                case,
                context,
                "task_timeout",
                {"task_id": task_ids[0] if task_ids else None},
            )
        except RunInterrupted:
            business_code = "RUN_STOP_REQUESTED"
            outcome_status = CaseOutcomeStatus.INCOMPLETE
        except TransportError as exc:
            observe(*self._observed_error_task_ids(exc))
            business_code = "NETWORK_INCOMPLETE"
            outcome_status = CaseOutcomeStatus.INCOMPLETE
            retryable = False
            self._safe_write_case_payload(
                case,
                "error.json",
                {
                    "error_type": type(exc).__name__,
                    "business_error_code": business_code,
                },
            )
        except BusinessError as exc:
            observe(*self._observed_error_task_ids(exc))
            business_code = exc.code
            if business_code in RUN_STOP_BUSINESS_CODES:
                self.run_control.request_stop(business_code)
            retryable = self._retry_allowed(context, business_code, exc.retryable)
            outcome_status = (
                CaseOutcomeStatus.COMPLETED
                if business_code == expected_error and case.expect.task_status is None
                else CaseOutcomeStatus.FAILED
            )
            self._safe_write_case_payload(
                case,
                "error.json",
                {
                    "error_type": type(exc).__name__,
                    "business_error_code": business_code,
                },
            )
        except DatingEvalError as exc:
            observe(*self._observed_error_task_ids(exc))
            business_code = str(exc) or type(exc).__name__
            self._safe_write_case_payload(
                case,
                "error.json",
                {
                    "error_type": type(exc).__name__,
                    "business_error_code": business_code,
                },
            )
        except OSError as exc:
            # 运行产物不可写属于本地确定性失败；已观察到的 Task 仍由 finally 清理。
            business_code = "ARTIFACT_WRITE_FAILED"
            outcome_status = CaseOutcomeStatus.FAILED
            retryable = False
            self._safe_write_case_payload(
                case,
                "error.json",
                {
                    "error_type": type(exc).__name__,
                    "business_error_code": business_code,
                },
            )
        finally:
            cleanup_results: list[CleanupResult] = []
            for index, observed_task_id in enumerate(task_ids, 1):
                if observed_task_id not in task_ids_with_recovery_event:
                    # Create 已返回 Task ID、但完整契约校验失败时仍写恢复锚点。Internal
                    # cleanup 可据此在本次 Delete 失败后跨进程继续处理。
                    if self._safe_event(
                        case,
                        context,
                        "task_observed",
                        {"task_id": observed_task_id},
                    ):
                        task_ids_with_recovery_event.add(observed_task_id)
                task_cleanup, lifecycle_error_code = self._diagnose_and_delete(
                    case,
                    context,
                    observed_task_id,
                    artifact_index=index,
                )
                cleanup_results.append(task_cleanup)
                # Diagnostics 的网络失败不能抹掉已经通过的业务结果，但缺失预期安全
                # Policy code 属于确定性契约失败，必须反映到 Case Outcome。无论哪一种
                # 诊断失败，删除都已在 _diagnose_and_delete 的 finally 路径执行。
                if lifecycle_error_code is not None:
                    if lifecycle_error_code in RUN_STOP_BUSINESS_CODES:
                        business_code = lifecycle_error_code
                    elif lifecycle_error_code == "ARTIFACT_WRITE_FAILED":
                        business_code = lifecycle_error_code
                    elif business_code is None:
                        business_code = lifecycle_error_code
                    if outcome_status is CaseOutcomeStatus.COMPLETED:
                        outcome_status = CaseOutcomeStatus.FAILED
                if not task_cleanup.success:
                    outcome_status = CaseOutcomeStatus.CLEANUP_PENDING
            if len(cleanup_results) == 1:
                cleanup = cleanup_results[0]
            elif cleanup_results:
                all_clean = all(item.success for item in cleanup_results)
                cleanup = CleanupResult(
                    all_clean,
                    "deleted" if all_clean else "delete_failed",
                    {"task_ids": tuple(task_ids)},
                )
            if not self._safe_event(
                case,
                context,
                "case_finished",
                {"status": outcome_status, "business_error_code": business_code},
            ):
                if business_code not in RUN_STOP_BUSINESS_CODES:
                    business_code = "ARTIFACT_WRITE_FAILED"
                if outcome_status is CaseOutcomeStatus.COMPLETED:
                    outcome_status = CaseOutcomeStatus.FAILED

        return CaseOutcome(
            case_id=case.case_id,
            status=outcome_status,
            task_id=task_ids[0] if task_ids else None,
            business_error_code=business_code,
            schema_version=schema_version,
            cleanup=cleanup,
            retryable=retryable,
        )

    def _poll_until_terminal(
        self,
        case: CaseDefinition,
        context: RunContext,
        initial: TaskSnapshot,
    ) -> TaskSnapshot:
        start = self.monotonic_fn()
        snapshot = initial
        last_event_status: TaskStatus | None = None
        while True:
            self.run_control.raise_if_stopped()
            elapsed = self.monotonic_fn() - start
            if elapsed > self.adapter.poll_policy.timeout_seconds:
                raise TimeoutError
            if snapshot.status is not last_event_status:
                self._event(
                    case,
                    context,
                    f"task_{snapshot.status.value}",
                    {"task_id": snapshot.task_id, "phase": snapshot.phase},
                )
                last_event_status = snapshot.status
            if snapshot.status in {
                TaskStatus.SUCCEEDED,
                TaskStatus.REJECTED,
                TaskStatus.FAILED,
            }:
                return snapshot
            interval = self.adapter.poll_policy.interval_for(elapsed)
            self.sleep_fn(interval)
            self.run_control.raise_if_stopped()
            snapshot = self.adapter.get_task(snapshot.task_id, context)

    def _diagnose_and_delete(
        self,
        case: CaseDefinition,
        context: RunContext,
        task_id: str,
        *,
        artifact_index: int,
    ) -> tuple[CleanupResult, str | None]:
        lifecycle_error_code: str | None = None
        artifact_failed = False
        suffix = "" if artifact_index == 1 else f"-{artifact_index}"
        try:
            try:
                diagnostics = self.adapter.get_diagnostics(task_id, case, context)
                if diagnostics is not None:
                    artifact_failed |= not self._safe_write_case_payload(
                        case, f"diagnostics{suffix}.json", diagnostics
                    )
                    artifact_failed |= not self._safe_event(
                        case,
                        context,
                        "diagnostics_fetched",
                        {"task_id": task_id},
                    )
            except ContractError as exc:
                # ContractError 的内容由工具自身的稳定常量产生，可以作为机器可读失败码；
                # 服务端自由文本从未进入该异常。
                lifecycle_error_code = str(exc) or "DIAGNOSTICS_CONTRACT_ERROR"
                artifact_failed |= not self._safe_event(
                    case,
                    context,
                    "diagnostics_contract_failed",
                    {"business_error_code": lifecycle_error_code},
                )
            except BusinessError as exc:
                if exc.code in RUN_STOP_BUSINESS_CODES:
                    lifecycle_error_code = exc.code
                    self.run_control.request_stop(exc.code)
                elif case.expect.policy_codes:
                    # 安全 Case 明确依赖 Diagnostics 稳定策略码；查询不可用时不能把
                    # Result 误判为完成。普通 Case 的诊断业务错误只作为排障事件。
                    lifecycle_error_code = "DIAGNOSTICS_REQUIRED_UNAVAILABLE"
                artifact_failed |= not self._safe_event(
                    case,
                    context,
                    "diagnostics_failed",
                    {"business_error_code": exc.code},
                )
            except DatingEvalError as exc:
                artifact_failed |= not self._safe_event(
                    case,
                    context,
                    "diagnostics_failed",
                    {"error_type": type(exc).__name__},
                )
            except Exception as exc:
                # Adapter 或本地 Artifact 的未预期异常也不能越过远端 Delete。
                lifecycle_error_code = lifecycle_error_code or "DIAGNOSTICS_INTERNAL_ERROR"
                artifact_failed |= not self._safe_event(
                    case,
                    context,
                    "diagnostics_failed",
                    {"error_type": type(exc).__name__},
                )
        finally:
            artifact_failed |= not self._safe_event(
                case, context, "delete_started", {"task_id": task_id}
            )
            try:
                cleanup = self.adapter.delete_task(task_id, context)
                payload = dict(cleanup.raw) or {
                    "success": cleanup.success,
                    "status": cleanup.status,
                }
            except BusinessError as exc:
                if lifecycle_error_code is None:
                    lifecycle_error_code = exc.code
                if exc.code in RUN_STOP_BUSINESS_CODES:
                    self.run_control.request_stop(exc.code)
                cleanup = CleanupResult(False, "delete_failed")
                payload = {
                    "success": False,
                    "error_type": type(exc).__name__,
                    "business_error_code": exc.code,
                }
            except Exception as exc:
                cleanup = CleanupResult(False, "delete_failed")
                payload = {
                    "success": False,
                    "error_type": type(exc).__name__,
                    "business_error_code": getattr(exc, "code", None),
                }
            artifact_failed |= not self._safe_write_case_payload(
                case, f"cleanup{suffix}.json", payload
            )
        event = (
            "delete_already_absent"
            if cleanup.status == "already_absent"
            else "delete_succeeded"
            if cleanup.success
            else "delete_failed"
        )
        artifact_failed |= not self._safe_event(
            case, context, event, {"task_id": task_id}
        )
        if artifact_failed and lifecycle_error_code not in RUN_STOP_BUSINESS_CODES:
            lifecycle_error_code = "ARTIFACT_WRITE_FAILED"
        return cleanup, lifecycle_error_code
