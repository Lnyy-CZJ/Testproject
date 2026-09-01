import tempfile
import unittest
from pathlib import Path

from PIL import Image

from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from aidating_eval.domain import E2EReplyCase, ReplyPreferences, RunContext, RunMode, TaskKind
from aidating_eval.errors import BusinessError
from aidating_eval.runner import CaseRunner
from tests.helpers import FakePublicGateway, FakeTransport, MemoryArtifactStore
from tests.unit.test_public_analysis_adapter import SESSION


def _reply_result():
    return {
        "task_id": "task-reply",
        "task_type": "reply_generation",
        "schema_version": "dating.reply_generation.v1",
        "result": {
            "schema_version": "dating.reply_generation.v1",
            "whats_happening": {"title": "Synthetic", "summary": "Synthetic"},
            "roles": [
                {
                    "role_id": "banter", "role_name": "Banter", "rank": 1,
                    "is_best_fit": True,
                    "top_pick": {"reply_id": "r1", "text": "Top"},
                    "alternatives": [
                        {"reply_id": "r2", "text": "A"},
                        {"reply_id": "r3", "text": "B"},
                        {"reply_id": "r4", "text": "C"},
                    ],
                }
            ],
            "warnings": [],
        },
    }


class PublicReplyAdapterTests(unittest.TestCase):
    """Reply 必须在上传前完成偏好和查询方法 readiness。"""

    def test_full_reply_sequence_places_preferences_before_media(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "chat.png"
            Image.new("RGB", (100, 100), "white").save(image_path)
            size = image_path.stat().st_size
            not_found = BusinessError("NOT_FOUND")
            gateway = FakePublicGateway(
                [
                    ("CreateAnonymousSession", SESSION),
                    ("GetMe", {"user_id": "user-1"}),
                    ("GetUserPreferences", {"preferences_complete": False, "dating_goal": "", "your_voice": "", "version": 0}),
                    ("UpdateUserPreferences", {"preferences_complete": True, "dating_goal": "serious_relationship", "your_voice": "warm_direct", "version": 1}),
                    ("GetUserPreferences", {"preferences_complete": True, "dating_goal": "serious_relationship", "your_voice": "warm_direct", "version": 1}),
                    ("GetTask", not_found),
                    ("GetTaskResult", not_found),
                    ("GetMediaUploadConfig", {
                        "allowed_content_types": ["image/png"], "min_asset_count": 1,
                        "max_asset_count": 9, "max_size_bytes": 7_000_000,
                        "config_cache_ttl_seconds": 300,
                        "complete_retry": {"max_attempts": 1, "initial_delay_ms": 0, "max_delay_ms": 0},
                    }),
                    ("PrepareMediaUpload", {
                        "asset_id": "asset-r", "content_type": "image/png", "size_bytes": size,
                        "upload_url": "https://cos.test/r?signature=safe", "upload_method": "PUT",
                        "required_headers": {"Content-Type": "image/png"}, "max_size_bytes": 7_000_000,
                    }),
                    ("CompleteMediaUpload", {"asset_id": "asset-r", "status": "uploaded"}),
                    ("CreateReplyTask", {"task_id": "task-reply", "task_type": "reply_generation", "status": "queued", "phase": "queued"}),
                    ("GetTask", {"task_id": "task-reply", "task_type": "reply_generation", "status": "succeeded", "phase": "finalizing"}),
                    ("GetTaskResult", _reply_result()),
                    ("DeleteTaskData", {"task_id": "task-reply", "logical_deleted": True, "object_deletion_status": "pending"}),
                    ("GetTask", BusinessError("NOT_FOUND")),
                    ("GetTaskResult", BusinessError("NOT_FOUND")),
                ]
            )
            adapter = PublicE2EAdapter.for_test(
                gateway=gateway, transport=FakeTransport([204])
            )
            context = RunContext.for_case(
                "run-public", "reply-one", RunMode.E2E, TaskKind.REPLY
            )
            case = E2EReplyCase(
                "reply-one", "en-US", (image_path,),
                ReplyPreferences("serious_relationship", "warm_direct"),
                "flirt", "Synthetic",
            )
            adapter.prepare_run(context)
            outcome = CaseRunner(
                adapter, MemoryArtifactStore(), sleep_fn=lambda _: None
            ).execute(case, context)
        self.assertEqual("completed", outcome.status)
        calls = gateway.calls
        media_index = next(i for i, call in enumerate(calls) if call.method_name == "GetMediaUploadConfig")
        self.assertLess(next(i for i, call in enumerate(calls) if call.method_name == "GetUserPreferences"), media_index)
        self.assertTrue(all(call.method_name in {"GetTask", "GetTaskResult"} for call in calls[5:7]))
        methods = [call.method_name for call in calls]
        self.assertLess(methods.index("CompleteMediaUpload"), methods.index("CreateReplyTask"))

    def test_readiness_failure_stops_before_media(self):
        gateway = FakePublicGateway(
            [
                ("CreateAnonymousSession", SESSION),
                ("GetMe", {"user_id": "user-1"}),
                ("GetUserPreferences", {"preferences_complete": True, "dating_goal": "serious_relationship", "your_voice": "warm_direct", "version": 1}),
                ("GetTask", BusinessError("FEATURE_NOT_READY")),
            ]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway)
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "chat.png"
            Image.new("RGB", (100, 100), "white").save(image_path)
            case = E2EReplyCase(
                "reply-blocked", "en-US", (image_path,),
                ReplyPreferences("serious_relationship", "warm_direct"), None, None,
            )
            context = RunContext.for_case(
                "run-public", case.case_id, RunMode.E2E, TaskKind.REPLY
            )
            adapter.prepare_run(context)
            outcome = CaseRunner(adapter, MemoryArtifactStore()).execute(case, context)
        self.assertEqual("failed", outcome.status)
        self.assertEqual("FEATURE_NOT_READY", outcome.business_error_code)
        self.assertFalse(any("Media" in call.method_name for call in gateway.calls))

    def test_readiness_only_check_never_enters_media_or_creates_task(self):
        gateway = FakePublicGateway(
            [
                ("GetUserPreferences", {"preferences_complete": True, "dating_goal": "serious_relationship", "your_voice": "warm_direct", "version": 1}),
                ("GetTask", BusinessError("NOT_FOUND")),
                ("GetTaskResult", BusinessError("NOT_FOUND")),
            ]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway, authenticated=True)
        case = E2EReplyCase(
            "reply-readiness", "en-US", (),
            ReplyPreferences("serious_relationship", "warm_direct"), None, None,
        )
        context = RunContext.for_case(
            "run-public", case.case_id, RunMode.E2E, TaskKind.REPLY
        )
        adapter.check_reply_readiness(case, context)
        methods = [call.method_name for call in gateway.calls]
        self.assertEqual(["GetUserPreferences", "GetTask", "GetTaskResult"], methods)
        self.assertFalse(any("Media" in method or method.startswith("CreateReply") for method in methods))


if __name__ == "__main__":
    unittest.main()
