import unittest

from aidating_eval.domain import (
    CaseOutcomeStatus,
    CleanupResult,
    RunContext,
    RunMode,
    TaskSnapshot,
    TaskStatus,
)
from aidating_eval.errors import BusinessError, ContractError, TransportError
from aidating_eval.runner import CaseRunner, RunControl
from tests.helpers import FakeAdapter, MemoryArtifactStore


def _task(status: TaskStatus | str, *, retryable: bool = False, code: str | None = None, task_id: str = "task-1"):
    return TaskSnapshot(
        task_id,
        "relationship_analysis",
        status,
        str(status),
        retryable,
        code,
        {"task_id": task_id, "status": str(status)},
    )


class RunnerTests(unittest.TestCase):
    """Runner 只决定状态时序，并对每个已知 Task 保证清理尝试。"""

    def test_succeeded_task_fetches_result_diagnostics_and_deletes(self):
        adapter = FakeAdapter(
            tasks=[_task(TaskStatus.QUEUED), _task(TaskStatus.SUCCEEDED)],
            result={"schema_version": "dating.relationship_analysis.v1"},
            diagnostics={"model_alias": "staging-model"},
            cleanup=CleanupResult(True, "deleted", {"success": True}),
        )
        runner = CaseRunner(adapter, MemoryArtifactStore(), sleep_fn=lambda _: None)
        outcome = runner.execute(FakeAdapter.case(), FakeAdapter.context())
        self.assertEqual(CaseOutcomeStatus.COMPLETED, outcome.status)
        self.assertEqual(["task-1"], adapter.deleted_task_ids)
        self.assertLess(adapter.calls.index("get_result"), adapter.calls.index("delete_task"))

    def test_result_failure_still_fetches_diagnostics_and_deletes(self):
        adapter = FakeAdapter.succeeded_but_result_fails()
        runner = CaseRunner(adapter, MemoryArtifactStore(), sleep_fn=lambda _: None)
        outcome = runner.execute(FakeAdapter.case(), FakeAdapter.context())
        self.assertEqual(CaseOutcomeStatus.FAILED, outcome.status)
        self.assertIn("get_diagnostics", adapter.calls)
        self.assertEqual(["task-1"], adapter.deleted_task_ids)

    def test_diagnostics_failure_does_not_prevent_delete(self):
        adapter = FakeAdapter(
            tasks=[_task(TaskStatus.SUCCEEDED)],
            result={"schema_version": "dating.relationship_analysis.v1"},
            diagnostics=TransportError("HTTP_500"),
        )
        outcome = CaseRunner(adapter, MemoryArtifactStore()).execute(
            FakeAdapter.case(), FakeAdapter.context()
        )
        self.assertEqual(CaseOutcomeStatus.COMPLETED, outcome.status)
        self.assertEqual(["task-1"], adapter.deleted_task_ids)

    def test_diagnostics_artifact_write_failure_still_deletes_remote_task(self):
        class FailingDiagnosticsArtifacts(MemoryArtifactStore):
            def write_case_payload(self, case_id, filename, payload):
                if filename == "diagnostics.json":
                    raise OSError("disk full")
                return super().write_case_payload(case_id, filename, payload)

        adapter = FakeAdapter(
            tasks=[_task(TaskStatus.SUCCEEDED)],
            result={"schema_version": "dating.relationship_analysis.v1"},
            diagnostics={"model_alias": "safe"},
        )
        outcome = CaseRunner(adapter, FailingDiagnosticsArtifacts()).execute(
            FakeAdapter.case(), FakeAdapter.context()
        )
        self.assertEqual(CaseOutcomeStatus.FAILED, outcome.status)
        self.assertEqual("ARTIFACT_WRITE_FAILED", outcome.business_error_code)
        self.assertEqual(["task-1"], adapter.deleted_task_ids)

    def test_diagnostics_auth_failure_stops_batch_marks_case_and_still_deletes(self):
        control = RunControl()
        adapter = FakeAdapter(
            tasks=[_task(TaskStatus.SUCCEEDED)],
            result={"schema_version": "dating.relationship_analysis.v1"},
            diagnostics=BusinessError("UNAUTHENTICATED"),
        )
        outcome = CaseRunner(
            adapter, MemoryArtifactStore(), run_control=control
        ).execute(FakeAdapter.case(), FakeAdapter.context())
        self.assertEqual(CaseOutcomeStatus.FAILED, outcome.status)
        self.assertEqual("UNAUTHENTICATED", outcome.business_error_code)
        self.assertFalse(control.may_start_new_case())
        self.assertEqual(["task-1"], adapter.deleted_task_ids)

    def test_delete_failure_overrides_status_to_cleanup_pending(self):
        adapter = FakeAdapter.succeeded_but_delete_fails()
        outcome = CaseRunner(adapter, MemoryArtifactStore()).execute(
            FakeAdapter.case(), FakeAdapter.context()
        )
        self.assertEqual(CaseOutcomeStatus.CLEANUP_PENDING, outcome.status)

    def test_delete_auth_failure_stops_batch_and_preserves_stable_code(self):
        control = RunControl()
        adapter = FakeAdapter(
            tasks=[_task(TaskStatus.SUCCEEDED)],
            result={"schema_version": "dating.relationship_analysis.v1"},
            cleanup=BusinessError("PERMISSION_DENIED"),
        )
        outcome = CaseRunner(
            adapter, MemoryArtifactStore(), run_control=control
        ).execute(FakeAdapter.case(), FakeAdapter.context())
        self.assertEqual(CaseOutcomeStatus.CLEANUP_PENDING, outcome.status)
        self.assertEqual("PERMISSION_DENIED", outcome.business_error_code)
        self.assertFalse(control.may_start_new_case())

    def test_expected_create_business_error_is_protocol_completed(self):
        case = FakeAdapter.case()
        object.__setattr__(
            case,
            "expect",
            type(case.expect)(
                task_status=None,
                result_schema=None,
                business_error_code="INPUT_INVALID",
            ),
        )
        adapter = FakeAdapter(
            tasks=[],
            result={},
            create_error=BusinessError("INPUT_INVALID"),
        )
        outcome = CaseRunner(adapter, MemoryArtifactStore()).execute(
            case, FakeAdapter.context()
        )
        self.assertEqual(CaseOutcomeStatus.COMPLETED, outcome.status)
        self.assertEqual("INPUT_INVALID", outcome.business_error_code)

    def test_idempotency_conflict_carries_first_task_to_cleanup(self):
        case = FakeAdapter.case()
        object.__setattr__(
            case,
            "expect",
            type(case.expect)(
                task_status=None,
                result_schema=None,
                business_error_code="IDEMPOTENCY_CONFLICT",
            ),
        )
        adapter = FakeAdapter(
            tasks=[],
            result={},
            create_error=BusinessError(
                "IDEMPOTENCY_CONFLICT", task_id_to_cleanup="task-first"
            ),
        )
        outcome = CaseRunner(adapter, MemoryArtifactStore()).execute(
            case, FakeAdapter.context()
        )
        self.assertEqual(CaseOutcomeStatus.COMPLETED, outcome.status)
        self.assertEqual(["task-first"], adapter.deleted_task_ids)

    def test_schema_mismatch_is_failed_but_task_is_deleted(self):
        adapter = FakeAdapter(
            tasks=[_task(TaskStatus.SUCCEEDED)],
            result={"schema_version": "wrong.schema"},
        )
        outcome = CaseRunner(adapter, MemoryArtifactStore()).execute(
            FakeAdapter.case(), FakeAdapter.context()
        )
        self.assertEqual(CaseOutcomeStatus.FAILED, outcome.status)
        self.assertEqual("RESULT_SCHEMA_MISMATCH", outcome.business_error_code)
        self.assertEqual(["task-1"], adapter.deleted_task_ids)

    def test_retryable_failed_task_retries_once_after_first_cleanup(self):
        adapter = FakeAdapter(
            tasks=[
                _task(TaskStatus.FAILED, retryable=True, code="INTERNAL", task_id="task-1"),
                _task(TaskStatus.SUCCEEDED, task_id="task-2"),
            ],
            result={"schema_version": "dating.relationship_analysis.v1"},
        )
        outcome = CaseRunner(adapter, MemoryArtifactStore()).execute(
            FakeAdapter.case(), FakeAdapter.context()
        )
        self.assertEqual(CaseOutcomeStatus.COMPLETED, outcome.status)
        self.assertEqual(["task-1", "task-2"], adapter.deleted_task_ids)
        self.assertEqual(2, len(set(adapter.context_attempts)))

    def test_deterministic_failure_never_recreates_even_if_server_marks_retryable(self):
        adapter = FakeAdapter(
            tasks=[
                _task(
                    TaskStatus.FAILED,
                    retryable=True,
                    code="INPUT_INVALID",
                )
            ],
            result={},
        )
        outcome = CaseRunner(adapter, MemoryArtifactStore()).execute(
            FakeAdapter.case(), FakeAdapter.context()
        )
        self.assertEqual(CaseOutcomeStatus.FAILED, outcome.status)
        self.assertFalse(outcome.retryable)
        self.assertEqual(1, adapter.calls.count("create_task"))

    def test_public_failed_task_is_not_recreated(self):
        adapter = FakeAdapter(
            tasks=[
                _task(
                    TaskStatus.FAILED,
                    retryable=True,
                    code="INTERNAL",
                )
            ],
            result={},
        )
        context = RunContext(
            "run-public",
            "attempt-public",
            RunMode.E2E,
            FakeAdapter.case().task_kind,
        )
        outcome = CaseRunner(adapter, MemoryArtifactStore()).execute(
            FakeAdapter.case(), context
        )
        self.assertEqual(CaseOutcomeStatus.FAILED, outcome.status)
        self.assertFalse(outcome.retryable)
        self.assertEqual(1, adapter.calls.count("create_task"))

    def test_transport_failure_is_incomplete_and_not_business_failed(self):
        adapter = FakeAdapter(
            tasks=[],
            result={},
            create_error=TransportError("ConnectionError"),
        )
        outcome = CaseRunner(adapter, MemoryArtifactStore()).execute(
            FakeAdapter.case(), FakeAdapter.context()
        )
        self.assertEqual(CaseOutcomeStatus.INCOMPLETE, outcome.status)
        self.assertEqual("NETWORK_INCOMPLETE", outcome.business_error_code)
        self.assertFalse(outcome.retryable)

    def test_stop_after_create_interrupts_poll_and_still_deletes(self):
        control = RunControl()
        adapter = FakeAdapter(
            tasks=[_task(TaskStatus.QUEUED)],
            result={},
            on_create=lambda: control.request_stop("TEST_STOP"),
        )
        outcome = CaseRunner(adapter, MemoryArtifactStore(), run_control=control).execute(
            FakeAdapter.case(), FakeAdapter.context()
        )
        self.assertEqual(CaseOutcomeStatus.INCOMPLETE, outcome.status)
        self.assertEqual(["task-1"], adapter.deleted_task_ids)

    def test_poll_timeout_is_incomplete_and_deletes(self):
        times = iter((0.0, 0.0, 11.0))
        # Create 返回 queued 后，允许一次真实 Poll 仍为 queued；下一轮时间检查才越过
        # 10 秒上限。这样测试验证的是 Runner 超时分支，而不是 Fake 队列耗尽。
        adapter = FakeAdapter(
            tasks=[_task(TaskStatus.QUEUED), _task(TaskStatus.QUEUED)],
            result={},
        )
        outcome = CaseRunner(
            adapter,
            MemoryArtifactStore(),
            sleep_fn=lambda _: None,
            monotonic_fn=lambda: next(times),
        ).execute(FakeAdapter.case(), FakeAdapter.context())
        self.assertEqual(CaseOutcomeStatus.INCOMPLETE, outcome.status)
        self.assertEqual(["task-1"], adapter.deleted_task_ids)


if __name__ == "__main__":
    unittest.main()
