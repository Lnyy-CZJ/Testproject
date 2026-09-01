import unittest

from aidating_eval.adapters.internal_evaluation import InternalEvaluationAdapter
from aidating_eval.domain import (
    CaseExpectation,
    EvaluationReplyCase,
    NegativeVariant,
    RunContext,
    RunMode,
    TaskKind,
    TranscriptMessage,
)
from aidating_eval.errors import BusinessError, ContractError, TransportError
from aidating_eval.runner import CaseRunner
from aidating_eval.scheduling import (
    CreatePacer,
    EvaluationRequestGate,
    SharedCooldown,
    SlidingWindowRateLimiter,
)
from tests.helpers import FakeClock, FakeEvaluationGateway, MemoryArtifactStore


def _messages() -> tuple[TranscriptMessage, ...]:
    return (
        TranscriptMessage("m1", "text", "other", "I had a good time."),
        TranscriptMessage("m2", "text", "self", "Me too."),
        TranscriptMessage("m3", "text", "other", "Saturday?"),
        TranscriptMessage("m4", "text", "user", "Saturday works."),
    )


def _case(
    *,
    expect: CaseExpectation | None = None,
    negative_variant: NegativeVariant | None = None,
) -> EvaluationReplyCase:
    return EvaluationReplyCase(
        "reply-case-001",
        "en-US",
        _messages(),
        "serious_relationship",
        "warm_direct",
        "flirt",
        "Met twice.",
        negative_variant,
        expect or CaseExpectation(result_schema="dating.reply_generation.v1"),
    )


def _context() -> RunContext:
    return RunContext(
        "run-001",
        "reply-case-001-attempt-001",
        RunMode.EVAL,
        TaskKind.REPLY,
    )


def _reply_result(*, warnings: list[object] | None = None) -> dict:
    return {
        "task_id": "task-reply",
        "task_type": "reply_generation",
        "schema_version": "dating.reply_generation.v1",
        "result": {
            "schema_version": "dating.reply_generation.v1",
            "whats_happening": {"title": "Synthetic", "summary": "Synthetic"},
            "roles": [
                {
                    "role_id": "warm",
                    "rank": 1,
                    "is_best_fit": True,
                    "top_pick": {"reply_id": "r1", "text": "Top"},
                    "alternatives": [
                        {"reply_id": "r2", "text": "A"},
                        {"reply_id": "r3", "text": "B"},
                        {"reply_id": "r4", "text": "C"},
                    ],
                }
            ],
            "warnings": warnings or [],
        },
    }


class InternalReplyAdapterTests(unittest.TestCase):
    def test_reply_evaluation_runs_result_diagnostics_and_delete(self):
        gateway = FakeEvaluationGateway(
            [
                ("CreateReplyEvaluationTask", {"task_id": "task-reply", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
                ("GetReplyEvaluationTask", {"task_id": "task-reply", "task_type": "reply_generation", "status": "processing", "phase": "generating"}),
                ("GetReplyEvaluationTask", {"task_id": "task-reply", "task_type": "reply_generation", "status": "succeeded", "phase": "done"}),
                ("GetReplyEvaluationResult", _reply_result()),
                ("GetEvaluationDiagnostics", {"case_id": "reply-case-001", "run_id": "run-001", "model_alias": "staging", "policy_codes": []}),
                ("DeleteReplyEvaluationTaskData", {"task_id": "task-reply", "deleted": True}),
            ]
        )
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        outcome = CaseRunner(
            adapter, MemoryArtifactStore(), sleep_fn=lambda _: None
        ).execute(_case(), _context())
        self.assertEqual("completed", outcome.status)
        self.assertEqual(
            [
                "CreateReplyEvaluationTask",
                "GetReplyEvaluationTask",
                "GetReplyEvaluationTask",
                "GetReplyEvaluationResult",
                "GetEvaluationDiagnostics",
                "DeleteReplyEvaluationTaskData",
            ],
            [call.method_name for call in gateway.calls],
        )

    def test_reply_request_contains_only_confirmed_fields_and_normalizes_self(self):
        gateway = FakeEvaluationGateway(
            [("CreateReplyEvaluationTask", {"task_id": "task-reply", "task_type": "reply_generation", "status": "queued", "phase": "queued"})]
        )
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        case = _case()
        adapter.create_task(case, adapter.prepare_case(case, _context()), _context())
        call = gateway.calls[0]
        self.assertEqual(call.client_request_id, call.params["client_request_id"])
        self.assertEqual("automated Reply evaluation", call.reason)
        self.assertEqual("user", call.params["transcript"]["messages"][1]["speaker"])
        self.assertEqual("serious_relationship", call.params["dating_goal"])
        self.assertEqual("warm_direct", call.params["your_voice"])
        for field in ("app_id", "user_id", "model", "prompt"):
            self.assertNotIn(field, call.params)

    def test_reply_result_rejects_invalid_role_shape(self):
        invalid = _reply_result()
        invalid["result"]["roles"] = []
        gateway = FakeEvaluationGateway([("GetReplyEvaluationResult", invalid)])
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        with self.assertRaisesRegex(ContractError, "REPLY_ROLE_COUNT_INVALID"):
            adapter.get_result("task-reply", _case(), _context())

    def test_reply_accepts_documented_schema_body_without_public_outer_wrapper(self):
        direct = _reply_result()["result"]
        gateway = FakeEvaluationGateway(
            [("GetReplyEvaluationResult", direct)]
        )
        result = InternalEvaluationAdapter.for_test(gateway=gateway).get_result(
            "task-reply", _case(), _context()
        )
        self.assertEqual("dating.reply_generation.v1", result["schema_version"])
        self.assertIn("result", result)

    def test_expected_safety_warning_and_policy_code_are_deterministic_checks(self):
        expect = CaseExpectation(
            result_schema="dating.reply_generation.v1",
            warning_codes=("SAFETY_DEGRADED",),
            policy_codes=("EXPLICIT_BOUNDARY",),
        )
        gateway = FakeEvaluationGateway(
            [
                ("GetReplyEvaluationResult", _reply_result(warnings=["SAFETY_DEGRADED"])),
                ("GetEvaluationDiagnostics", {"case_id": "reply-case-001", "run_id": "run-001", "policy_codes": ["EXPLICIT_BOUNDARY"], "prompt_body": "must-not-be-saved"}),
            ]
        )
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        case = _case(expect=expect)
        adapter.get_result("task-reply", case, _context())
        diagnostics = adapter.get_diagnostics("task-reply", case, _context())
        self.assertNotIn("prompt_body", diagnostics)
        self.assertEqual(["EXPLICIT_BOUNDARY"], diagnostics["policy_codes"])

    def test_diagnostics_reject_mismatched_identity_and_nested_allowed_fields(self):
        for diagnostics in (
            {"case_id": "wrong-case", "run_id": "run-001", "policy_codes": []},
            {"case_id": "reply-case-001", "run_id": "run-001", "model_alias": {"prompt_body": "must-not-be-saved"}, "policy_codes": []},
        ):
            with self.subTest(diagnostics=diagnostics):
                gateway = FakeEvaluationGateway(
                    [("GetEvaluationDiagnostics", diagnostics)]
                )
                with self.assertRaises(ContractError):
                    InternalEvaluationAdapter.for_test(
                        gateway=gateway
                    ).get_diagnostics("task-reply", _case(), _context())

    def test_missing_expected_policy_code_marks_case_failed_and_still_deletes(self):
        expect = CaseExpectation(
            result_schema="dating.reply_generation.v1",
            policy_codes=("MINOR_PRESENT",),
        )
        gateway = FakeEvaluationGateway(
            [
                ("CreateReplyEvaluationTask", {"task_id": "task-reply", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
                ("GetReplyEvaluationTask", {"task_id": "task-reply", "task_type": "reply_generation", "status": "succeeded", "phase": "done"}),
                ("GetReplyEvaluationResult", _reply_result()),
                ("GetEvaluationDiagnostics", {"case_id": "reply-case-001", "run_id": "run-001", "policy_codes": []}),
                ("DeleteReplyEvaluationTaskData", {"task_id": "task-reply", "deleted": True}),
            ]
        )
        outcome = CaseRunner(
            InternalEvaluationAdapter.for_test(gateway=gateway),
            MemoryArtifactStore(),
            sleep_fn=lambda _: None,
        ).execute(_case(expect=expect), _context())
        self.assertEqual("failed", outcome.status)
        self.assertEqual("EXPECTED_POLICY_CODE_MISSING", outcome.business_error_code)
        self.assertEqual("DeleteReplyEvaluationTaskData", gateway.calls[-1].method_name)

    def test_idempotency_conflict_preserves_first_task_for_cleanup(self):
        expect = CaseExpectation(
            task_status=None,
            result_schema=None,
            business_error_code="IDEMPOTENCY_CONFLICT",
        )
        gateway = FakeEvaluationGateway(
            [
                ("CreateReplyEvaluationTask", {"task_id": "task-first", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
                ("CreateReplyEvaluationTask", BusinessError("IDEMPOTENCY_CONFLICT")),
                ("GetEvaluationDiagnostics", BusinessError("NOT_FOUND")),
                ("DeleteReplyEvaluationTaskData", {"task_id": "task-first", "deleted": True}),
            ]
        )
        case = _case(expect=expect, negative_variant=NegativeVariant.IDEMPOTENCY_CONFLICT)
        outcome = CaseRunner(
            InternalEvaluationAdapter.for_test(gateway=gateway),
            MemoryArtifactStore(),
        ).execute(case, _context())
        self.assertEqual("completed", outcome.status)
        self.assertEqual("task-first", outcome.task_id)
        first, second = gateway.calls[:2]
        self.assertEqual(first.client_request_id, second.client_request_id)
        self.assertNotEqual(first.params, second.params)

    def test_idempotency_same_mismatch_cleans_every_observed_task(self):
        gateway = FakeEvaluationGateway(
            [
                ("CreateReplyEvaluationTask", {"task_id": "task-first", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
                ("CreateReplyEvaluationTask", {"task_id": "task-second", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
                ("GetEvaluationDiagnostics", {"case_id": "reply-case-001", "run_id": "run-001", "policy_codes": []}),
                ("DeleteReplyEvaluationTaskData", {"task_id": "task-first", "deleted": True}),
                ("GetEvaluationDiagnostics", {"case_id": "reply-case-001", "run_id": "run-001", "policy_codes": []}),
                ("DeleteReplyEvaluationTaskData", {"task_id": "task-second", "deleted": True}),
            ]
        )
        case = _case(negative_variant=NegativeVariant.IDEMPOTENCY_SAME)
        outcome = CaseRunner(
            InternalEvaluationAdapter.for_test(gateway=gateway),
            MemoryArtifactStore(),
        ).execute(case, _context())
        self.assertEqual("failed", outcome.status)
        self.assertEqual("IDEMPOTENCY_SAME_TASK_MISMATCH", outcome.business_error_code)
        deleted = [
            call.params["task_id"]
            for call in gateway.calls
            if call.method_name == "DeleteReplyEvaluationTaskData"
        ]
        self.assertEqual(["task-first", "task-second"], deleted)

    def test_idempotency_conflict_unexpected_success_cleans_both_tasks(self):
        gateway = FakeEvaluationGateway(
            [
                ("CreateReplyEvaluationTask", {"task_id": "task-first", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
                ("CreateReplyEvaluationTask", {"task_id": "task-second", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
                ("GetEvaluationDiagnostics", {"case_id": "reply-case-001", "run_id": "run-001", "policy_codes": []}),
                ("DeleteReplyEvaluationTaskData", {"task_id": "task-first", "deleted": True}),
                ("GetEvaluationDiagnostics", {"case_id": "reply-case-001", "run_id": "run-001", "policy_codes": []}),
                ("DeleteReplyEvaluationTaskData", {"task_id": "task-second", "deleted": True}),
            ]
        )
        case = _case(negative_variant=NegativeVariant.IDEMPOTENCY_CONFLICT)
        outcome = CaseRunner(
            InternalEvaluationAdapter.for_test(gateway=gateway),
            MemoryArtifactStore(),
        ).execute(case, _context())
        self.assertEqual("failed", outcome.status)
        self.assertEqual(
            "IDEMPOTENCY_CONFLICT_NOT_OBSERVED", outcome.business_error_code
        )
        deleted = [
            call.params["task_id"]
            for call in gateway.calls
            if call.method_name == "DeleteReplyEvaluationTaskData"
        ]
        self.assertEqual(["task-first", "task-second"], deleted)

    def test_idempotency_second_create_transport_failure_cleans_first_task(self):
        gateway = FakeEvaluationGateway(
            [
                ("CreateReplyEvaluationTask", {"task_id": "task-first", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
                ("CreateReplyEvaluationTask", TransportError("ConnectionError")),
                ("CreateReplyEvaluationTask", TransportError("ConnectionError")),
                ("GetEvaluationDiagnostics", {"case_id": "reply-case-001", "run_id": "run-001", "policy_codes": []}),
                ("DeleteReplyEvaluationTaskData", {"task_id": "task-first", "deleted": True}),
            ]
        )
        case = _case(negative_variant=NegativeVariant.IDEMPOTENCY_SAME)
        outcome = CaseRunner(
            InternalEvaluationAdapter.for_test(gateway=gateway),
            MemoryArtifactStore(),
        ).execute(case, _context())
        self.assertEqual("incomplete", outcome.status)
        self.assertEqual("task-first", outcome.task_id)
        self.assertEqual(
            ["DeleteReplyEvaluationTaskData"],
            [
                call.method_name
                for call in gateway.calls
                if call.method_name == "DeleteReplyEvaluationTaskData"
            ],
        )

    def test_unknown_business_code_conversion_preserves_cleanup_ids(self):
        gateway = FakeEvaluationGateway(
            [
                (
                    "CreateReplyEvaluationTask",
                    BusinessError(
                        "FUTURE_CODE",
                        task_ids_to_cleanup=("task-observed",),
                    ),
                )
            ]
        )
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        case = _case()
        with self.assertRaisesRegex(
            ContractError, "UNKNOWN_BUSINESS_ERROR_CODE"
        ) as caught:
            adapter.create_task(
                case, adapter.prepare_case(case, _context()), _context()
            )
        self.assertEqual(
            ("task-observed",), caught.exception.task_ids_to_cleanup
        )

    def test_limit_retry_waits_on_shared_cooldown_and_reuses_create_request(self):
        clock = FakeClock()
        gate = EvaluationRequestGate(
            SlidingWindowRateLimiter(
                max_calls=120,
                period_seconds=60,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
            CreatePacer(
                2,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
            SharedCooldown(
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
        )
        gateway = FakeEvaluationGateway(
            [
                ("CreateReplyEvaluationTask", BusinessError("EVALUATION_LIMIT_EXCEEDED", retry_after_seconds=12)),
                ("CreateReplyEvaluationTask", {"task_id": "task-reply", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
            ]
        )
        adapter = InternalEvaluationAdapter(gateway=gateway, request_gate=gate)
        case = _case()
        adapter.create_task(case, adapter.prepare_case(case, _context()), _context())
        self.assertEqual([12], clock.sleeps)
        self.assertEqual(gateway.calls[0].params, gateway.calls[1].params)
        self.assertEqual(
            gateway.calls[0].client_request_id,
            gateway.calls[1].client_request_id,
        )

    def test_second_limit_response_still_defers_other_workers_without_looping(self):
        clock = FakeClock()
        gate = EvaluationRequestGate(
            SlidingWindowRateLimiter(
                max_calls=120,
                period_seconds=60,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
            CreatePacer(
                0,
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
            SharedCooldown(
                monotonic_fn=clock.monotonic,
                sleep_fn=clock.sleep,
            ),
        )
        gateway = FakeEvaluationGateway(
            [
                ("CreateReplyEvaluationTask", BusinessError("EVALUATION_LIMIT_EXCEEDED", retry_after_seconds=1)),
                ("CreateReplyEvaluationTask", BusinessError("EVALUATION_LIMIT_EXCEEDED", retry_after_seconds=30)),
            ]
        )
        adapter = InternalEvaluationAdapter(gateway=gateway, request_gate=gate)
        case = _case()
        with self.assertRaises(BusinessError):
            adapter.create_task(
                case, adapter.prepare_case(case, _context()), _context()
            )
        gate.cooldown.wait_if_needed()
        self.assertEqual([1, 30], clock.sleeps)
        self.assertEqual(2, len(gateway.calls))

    def test_unknown_create_network_result_retries_once_with_same_idempotency_key(self):
        gateway = FakeEvaluationGateway(
            [
                ("CreateReplyEvaluationTask", TransportError("ConnectionError")),
                ("CreateReplyEvaluationTask", {"task_id": "task-reply", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
            ]
        )
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        case = _case()
        adapter.create_task(case, adapter.prepare_case(case, _context()), _context())
        self.assertEqual(gateway.calls[0].params, gateway.calls[1].params)
        self.assertEqual(
            gateway.calls[0].client_request_id,
            gateway.calls[1].client_request_id,
        )


if __name__ == "__main__":
    unittest.main()
