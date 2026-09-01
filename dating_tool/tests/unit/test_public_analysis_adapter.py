import tempfile
import unittest
from pathlib import Path

from PIL import Image

from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from aidating_eval.domain import E2EAnalysisCase, PreparedCase, RunContext, RunMode, TaskKind
from aidating_eval.errors import BusinessError, ContractError
from aidating_eval.runner import CaseRunner
from tests.helpers import FakePublicGateway, FakeTransport, MemoryArtifactStore


SESSION = {
    "user_id": "user-1",
    "access_token": "access-1",
    "expires_time": 1787558400000,
    "refresh_token": "refresh-1",
    "refresh_expires_time": 1790064000000,
}


def _analysis_result():
    return {
        "task_id": "task-analysis",
        "task_type": "relationship_analysis",
        "schema_version": "dating.relationship_analysis.v1",
        "result": {
            "schema_version": "dating.relationship_analysis.v1",
            "overview": {
                "next_steps": [
                    {"type": "action", "text": "a"},
                    {"type": "communication", "text": "b"},
                    {"type": "observation", "text": "c"},
                ],
                "dashboard": {"match_degree": {"status": "unclear", "score": None}},
            },
            "chat_signals": {"positive": [], "watch": [], "risk": []},
            "key_events": {
                "turning_points": [],
                "hidden_meanings": [],
                "did_well": [],
                "could_improve": [],
            },
            "warnings": [],
        },
    }


class PublicAnalysisAdapterTests(unittest.TestCase):
    """公开 Analysis 只能使用 staging 已冻结的类型专属查询方法。"""

    def test_full_public_analysis_sequence_uses_current_method_names(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "chat.png"
            Image.new("RGB", (100, 100), "white").save(image_path)
            size = image_path.stat().st_size
            gateway = FakePublicGateway(
                [
                    ("CreateAnonymousSession", SESSION),
                    ("GetMe", {"user_id": "user-1"}),
                    ("GetMediaUploadConfig", {
                        "allowed_content_types": ["image/png"], "min_asset_count": 1,
                        "max_asset_count": 9, "max_size_bytes": 7_000_000,
                        "config_cache_ttl_seconds": 300,
                        "complete_retry": {"max_attempts": 1, "initial_delay_ms": 0, "max_delay_ms": 0},
                    }),
                    ("PrepareMediaUpload", {
                        "asset_id": "asset-1", "content_type": "image/png", "size_bytes": size,
                        "upload_url": "https://cos.test/a?signature=safe", "upload_method": "PUT",
                        "required_headers": {"Content-Type": "image/png"}, "max_size_bytes": 7_000_000,
                    }),
                    ("CompleteMediaUpload", {"asset_id": "asset-1", "status": "uploaded"}),
                    ("GetQuotaStatus", {"remaining": 1, "unlimited": False}),
                    ("CreateAnalysisTask", {"task_id": "task-analysis", "task_type": "relationship_analysis", "status": "queued", "phase": "queued"}),
                    ("GetAnalysisTask", {"task_id": "task-analysis", "task_type": "relationship_analysis", "status": "succeeded", "phase": "finalizing"}),
                    ("GetAnalysisResult", _analysis_result()),
                    ("DeleteTaskData", {"task_id": "task-analysis", "logical_deleted": True, "object_deletion_status": "pending"}),
                    ("GetAnalysisTask", BusinessError("NOT_FOUND")),
                    ("GetAnalysisResult", BusinessError("NOT_FOUND")),
                ]
            )
            adapter = PublicE2EAdapter.for_test(
                gateway=gateway, transport=FakeTransport([204])
            )
            context = RunContext.for_case(
                "run-public", "analysis-one", RunMode.E2E, TaskKind.ANALYSIS
            )
            case = E2EAnalysisCase(
                "analysis-one", "en-US", (image_path,), "Alex", "Synthetic"
            )
            adapter.prepare_run(context)
            outcome = CaseRunner(
                adapter, MemoryArtifactStore(), sleep_fn=lambda _: None
            ).execute(case, context)
        self.assertEqual("completed", outcome.status)
        methods = [call.method_name for call in gateway.calls]
        self.assertIn("GetAnalysisTask", methods)
        self.assertIn("GetAnalysisResult", methods)
        self.assertNotIn("GetTask", methods)
        self.assertNotIn("GetTaskResult", methods)
        self.assertLess(methods.index("GetQuotaStatus"), methods.index("CreateAnalysisTask"))

    def test_invalid_create_contract_preserves_observed_task_for_cleanup(self):
        gateway = FakePublicGateway(
            [
                (
                    "CreateAnalysisTask",
                    {
                        "task_id": "task-observed",
                        "task_type": "relationship_analysis",
                        "status": "succeeded",
                        "phase": "done",
                    },
                )
            ]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway, authenticated=True)
        case = E2EAnalysisCase("analysis-one", "en-US", (), None, None)
        context = RunContext.for_case(
            "run-public", "analysis-one", RunMode.E2E, TaskKind.ANALYSIS
        )
        with self.assertRaisesRegex(
            ContractError, "PUBLIC_CREATE_STATUS_NOT_QUEUED"
        ) as caught:
            adapter.create_task(
                case, PreparedCase({"asset_ids": ("asset-1",)}), context
            )
        self.assertEqual(("task-observed",), caught.exception.task_ids_to_cleanup)


if __name__ == "__main__":
    unittest.main()
