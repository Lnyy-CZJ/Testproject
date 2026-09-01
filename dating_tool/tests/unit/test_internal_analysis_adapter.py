import unittest

from aidating_eval.adapters.internal_evaluation import InternalEvaluationAdapter
from aidating_eval.domain import (
    EvaluationAnalysisCase,
    RunContext,
    RunMode,
    TaskKind,
    TranscriptMessage,
)
from aidating_eval.errors import BusinessError, ContractError
from aidating_eval.runner import CaseRunner
from tests.helpers import FakeEvaluationGateway, MemoryArtifactStore


def _messages(count: int = 4) -> tuple[TranscriptMessage, ...]:
    return tuple(
        TranscriptMessage(
            f"m{i + 1}",
            "text",
            "other" if i % 2 == 0 else "self",
            f"synthetic message {i + 1}",
        )
        for i in range(count)
    )


def _case(count: int = 4) -> EvaluationAnalysisCase:
    return EvaluationAnalysisCase("analysis-case-001", "en-US", _messages(count))


def _context() -> RunContext:
    return RunContext(
        "run-001",
        "analysis-case-001-attempt-001",
        RunMode.EVAL,
        TaskKind.ANALYSIS,
    )


def _analysis_result(
    *,
    warnings: list[object] | None = None,
    scope: dict | None = None,
    evidence_id: str | None = None,
) -> dict:
    result = {
        "schema_version": "dating.relationship_analysis.v1",
        "overview": {"summary": "Synthetic"},
        "chat_signals": {"positive": [], "watch": [], "risk": []},
        "key_events": {
            "turning_points": (
                [{"evidence_message_ids": [evidence_id]}] if evidence_id else []
            ),
            "hidden_meanings": [],
            "did_well": [],
            "could_improve": [],
        },
        "warnings": warnings or [],
    }
    if scope is not None:
        result["analysis_scope"] = scope
    return {
        "task_id": "task-analysis",
        "task_type": "relationship_analysis",
        "schema_version": "dating.relationship_analysis.v1",
        "result": result,
    }


class InternalAnalysisAdapterTests(unittest.TestCase):
    def test_analysis_evaluation_runs_result_diagnostics_and_delete(self):
        gateway = FakeEvaluationGateway(
            [
                ("CreateAnalysisEvaluationTask", {"task_id": "task-analysis", "task_type": "relationship_analysis", "status": "queued", "phase": "queued"}),
                ("GetAnalysisEvaluationTask", {"task_id": "task-analysis", "task_type": "relationship_analysis", "status": "processing", "phase": "analyzing"}),
                ("GetAnalysisEvaluationTask", {"task_id": "task-analysis", "task_type": "relationship_analysis", "status": "succeeded", "phase": "done"}),
                ("GetAnalysisEvaluationResult", _analysis_result()),
                ("GetEvaluationDiagnostics", {"case_id": "analysis-case-001", "run_id": "run-001", "policy_codes": []}),
                ("DeleteAnalysisEvaluationTaskData", {"task_id": "task-analysis", "deleted": True}),
            ]
        )
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        outcome = CaseRunner(
            adapter, MemoryArtifactStore(), sleep_fn=lambda _: None
        ).execute(_case(), _context())
        self.assertEqual("completed", outcome.status)
        self.assertEqual(
            [
                "CreateAnalysisEvaluationTask",
                "GetAnalysisEvaluationTask",
                "GetAnalysisEvaluationTask",
                "GetAnalysisEvaluationResult",
                "GetEvaluationDiagnostics",
                "DeleteAnalysisEvaluationTaskData",
            ],
            [call.method_name for call in gateway.calls],
        )

    def test_analysis_request_omits_all_reply_only_fields(self):
        gateway = FakeEvaluationGateway(
            [("CreateAnalysisEvaluationTask", {"task_id": "task-analysis", "task_type": "relationship_analysis", "status": "queued", "phase": "queued"})]
        )
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        case = _case()
        adapter.create_task(case, adapter.prepare_case(case, _context()), _context())
        params = gateway.calls[0].params
        self.assertEqual("user", params["transcript"]["messages"][1]["speaker"])
        for field in ("background", "dating_goal", "your_voice", "requested_intent"):
            self.assertNotIn(field, params)

    def test_301_messages_require_recent_300_scope_warning_and_evidence(self):
        case = _case(301)
        result = _analysis_result(
            warnings=["TRUNCATED_TO_RECENT_300"],
            scope={"truncated_to_recent_300": True, "analyzed_message_count": 300},
            evidence_id="m2",
        )
        gateway = FakeEvaluationGateway([("GetAnalysisEvaluationResult", result)])
        validated = InternalEvaluationAdapter.for_test(gateway=gateway).get_result(
            "task-analysis", case, _context()
        )
        self.assertEqual("dating.relationship_analysis.v1", validated["schema_version"])

    def test_301_messages_reject_evidence_from_truncated_prefix(self):
        case = _case(301)
        result = _analysis_result(
            warnings=["TRUNCATED_TO_RECENT_300"],
            scope={"truncated_to_recent_300": True, "analyzed_message_count": 300},
            evidence_id="m1",
        )
        gateway = FakeEvaluationGateway([("GetAnalysisEvaluationResult", result)])
        with self.assertRaisesRegex(ContractError, "ANALYSIS_EVIDENCE_OUT_OF_SCOPE"):
            InternalEvaluationAdapter.for_test(gateway=gateway).get_result(
                "task-analysis", case, _context()
            )

    def test_301_messages_reject_missing_truncation_contract(self):
        gateway = FakeEvaluationGateway(
            [("GetAnalysisEvaluationResult", _analysis_result())]
        )
        with self.assertRaisesRegex(ContractError, "ANALYSIS_TRUNCATION_SCOPE_INVALID"):
            InternalEvaluationAdapter.for_test(gateway=gateway).get_result(
                "task-analysis", _case(301), _context()
            )

    def test_analysis_accepts_documented_schema_body_without_public_outer_wrapper(self):
        direct = _analysis_result()["result"]
        gateway = FakeEvaluationGateway(
            [("GetAnalysisEvaluationResult", direct)]
        )
        result = InternalEvaluationAdapter.for_test(gateway=gateway).get_result(
            "task-analysis", _case(), _context()
        )
        self.assertEqual(
            "dating.relationship_analysis.v1", result["schema_version"]
        )
        self.assertIn("result", result)

    def test_delete_not_found_is_idempotent_cleanup_success(self):
        gateway = FakeEvaluationGateway(
            [("DeleteAnalysisEvaluationTaskData", BusinessError("NOT_FOUND"))]
        )
        result = InternalEvaluationAdapter.for_test(gateway=gateway).delete_task(
            "task-analysis", _context()
        )
        self.assertTrue(result.success)
        self.assertEqual("already_absent", result.status)

    def test_verify_deleted_requires_task_result_and_diagnostics_not_found(self):
        gateway = FakeEvaluationGateway(
            [
                ("GetAnalysisEvaluationTask", BusinessError("NOT_FOUND")),
                ("GetAnalysisEvaluationResult", BusinessError("NOT_FOUND")),
                ("GetEvaluationDiagnostics", BusinessError("NOT_FOUND")),
            ]
        )
        InternalEvaluationAdapter.for_test(gateway=gateway).verify_deleted(
            "task-analysis", _context()
        )
        self.assertEqual(
            [
                "GetAnalysisEvaluationTask",
                "GetAnalysisEvaluationResult",
                "GetEvaluationDiagnostics",
            ],
            [call.method_name for call in gateway.calls],
        )

    def test_doctor_uses_read_only_reply_and_analysis_probes(self):
        gateway = FakeEvaluationGateway(
            [
                ("GetReplyEvaluationTask", BusinessError("NOT_FOUND")),
                ("GetAnalysisEvaluationTask", BusinessError("NOT_FOUND")),
            ]
        )
        checks = InternalEvaluationAdapter.for_test(gateway=gateway).doctor()
        self.assertEqual(["PASS", "PASS"], [check.status for check in checks])
        self.assertFalse(any(call.method_name.startswith("Create") for call in gateway.calls))


if __name__ == "__main__":
    unittest.main()
