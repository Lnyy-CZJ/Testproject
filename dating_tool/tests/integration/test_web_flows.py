import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aidating_eval.application import RunApplicationService
from aidating_eval.config import Settings
from aidating_eval.domain import PreparedCase, TaskSnapshot
from PIL import Image
from aidating_eval.web.app import create_app
from aidating_eval.web.input_store import WebInputStore
from aidating_eval.web.run_manager import RunManager
from aidating_eval.web.run_repository import RunRepository
from tests.helpers import FakeAdapter


class WebFlowIntegrationTests(unittest.TestCase):
    def test_eval_upload_validate_async_run_and_finally_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            logs = root / "logs"
            drafts = root / "drafts"
            dataset = {
                "schema_version": "aidating.eval.case.v1",
                "case_id": "web-case-1",
                "task_kind": "analysis",
                "locale": "en-US",
                "transcript": {
                    "schema_version": "dating.transcript.v1",
                    "messages": [
                        {"message_id": f"m{i}", "message_type": "text", "speaker": "user" if i % 2 else "other", "text": f"message {i}"}
                        for i in range(1, 5)
                    ],
                },
            }
            store = WebInputStore(drafts)
            adapter = FakeAdapter(
                tasks=[
                    # Create response, then one processing and one succeeded poll.
                    __import__("aidating_eval.domain", fromlist=["TaskSnapshot"]).TaskSnapshot("task-web", "relationship_analysis", "queued", "queued"),
                    __import__("aidating_eval.domain", fromlist=["TaskSnapshot"]).TaskSnapshot("task-web", "relationship_analysis", "processing", "working"),
                    __import__("aidating_eval.domain", fromlist=["TaskSnapshot"]).TaskSnapshot("task-web", "relationship_analysis", "succeeded", "done"),
                ],
                result={"schema_version": "dating.relationship_analysis.v1"},
                diagnostics={"model_alias": "fixture"},
            )
            settings = Settings(
                mode="eval",
                eval_base_url="https://lb-rg3phjei-vzmdn2i7ey8rq40l.clb.usw-tencentclb.com/admin/invoke",
                eval_api_key="fixture-key",
                artifacts_root=artifacts,
            )
            service = RunApplicationService(
                settings_factory=lambda _mode: settings,
                adapter_factory=lambda _settings, **_kwargs: adapter,
            )
            manager = RunManager(service=service, input_store=store)
            repository = RunRepository(artifacts_root=artifacts, logs_root=logs, active_provider=manager.snapshot)
            app = create_app(service=service, manager=manager, repository=repository, input_store=store, testing=True)
            client = app.test_client()
            with patch.dict(
                "os.environ",
                {"AIDATING_LOG_ROOT": str(logs), "AIDATING_ARTIFACTS_ROOT": str(artifacts)},
                clear=False,
            ):
                response = client.post(
                    "/api/runs/validate",
                    data={"mode": "eval", "dataset": (
                        __import__("io").BytesIO((json.dumps(dataset) + "\n").encode()),
                        "cases.jsonl",
                    )},
                    content_type="multipart/form-data",
                )
                self.assertEqual(200, response.status_code, response.get_data(as_text=True))
                draft_id = response.get_json()["draft_id"]
                created = client.post("/api/runs", json={"draft_id": draft_id})
                self.assertEqual(202, created.status_code, created.get_data(as_text=True))
                run_id = created.get_json()["run_id"]
                result = manager.wait(run_id, timeout=5)
            self.assertEqual("completed", result.status)
            self.assertFalse(store.root.joinpath(draft_id).exists())
            detail = repository.get_run(run_id)
            self.assertEqual("completed", detail["manifest"]["status"])
            self.assertEqual("deleted", detail["manifest"]["cleanup_status"])
            manager.shutdown()

    def test_e2e_upload_validate_async_run_and_finally_delete(self):
        class E2EFakeAdapter(FakeAdapter):
            def prepare_case(self, case, context):
                self.calls.append("prepare_case")
                return PreparedCase({}, {"asset_count": len(case.media_paths)})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts, logs, drafts = root / "artifacts", root / "logs", root / "drafts"
            image_bytes = BytesIO()
            Image.new("RGB", (80, 80), "white").save(image_bytes, format="PNG")
            adapter = E2EFakeAdapter(
                tasks=[
                    TaskSnapshot("task-web-e2e", "relationship_analysis", "queued", "queued"),
                    TaskSnapshot("task-web-e2e", "relationship_analysis", "succeeded", "done"),
                ],
                result={"schema_version": "dating.relationship_analysis.v1"},
                diagnostics={"model_alias": "fixture"},
            )
            settings = Settings(
                mode="e2e",
                public_gateway_url="https://gateway.test/invoke",
                public_health_url="https://gateway.test/healthz",
                device_id="fixture-device",
                e2e_fixture_root=root,
                artifacts_root=artifacts,
            )
            service = RunApplicationService(
                settings_factory=lambda _mode: settings,
                adapter_factory=lambda _settings, **_kwargs: adapter,
            )
            store = WebInputStore(drafts)
            manager = RunManager(service=service, input_store=store)
            repository = RunRepository(artifacts_root=artifacts, logs_root=logs, active_provider=manager.snapshot)
            app = create_app(service=service, manager=manager, repository=repository, input_store=store, testing=True)
            with patch.dict("os.environ", {"AIDATING_LOG_ROOT": str(logs), "AIDATING_ARTIFACTS_ROOT": str(artifacts)}, clear=False):
                client = app.test_client()
                response = client.post(
                    "/api/runs/validate",
                    data={"mode": "e2e", "task_kind": "analysis", "locale": "en-US", "media": (BytesIO(image_bytes.getvalue()), "chat.png")},
                    content_type="multipart/form-data",
                )
                self.assertEqual(200, response.status_code, response.get_data(as_text=True))
                draft_id = response.get_json()["draft_id"]
                created = client.post("/api/runs", json={"draft_id": draft_id})
                self.assertEqual(202, created.status_code, created.get_data(as_text=True))
                result = manager.wait(created.get_json()["run_id"], timeout=5)
            self.assertEqual(0, result.exit_code)
            self.assertFalse((drafts / draft_id).exists())
            self.assertEqual("completed", repository.get_run(result.run_id)["manifest"]["status"])
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
