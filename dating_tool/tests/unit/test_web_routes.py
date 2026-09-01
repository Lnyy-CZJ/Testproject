import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aidating_eval.application import RunExecutionResult, ValidationSummary
from aidating_eval.domain import CaseOutcome, CaseOutcomeStatus, CleanupResult, DoctorCheck, DoctorStatus
from aidating_eval.web.app import create_app
from aidating_eval.web.input_store import WebInputStore
from aidating_eval.web.run_manager import RunHandle


class _FakeService:
    def __init__(self):
        self.validated = []

    def validate(self, request):
        self.validated.append(request)
        return ValidationSummary(
            mode=request.mode.value if hasattr(request.mode, "value") else str(request.mode),
            task_kind="analysis",
            case_ids=("case-1",),
            case_count=1,
            reply_count=0,
            analysis_count=1,
            message_count=0,
            input_bytes=4,
            media_count=1,
            normal_create_requests=0,
            worst_case_create_requests=0,
            eval_concurrency=None,
        )

    def doctor(self, mode):
        return [DoctorCheck("gateway", DoctorStatus.PASS, "ok")]


class _FakeManager:
    def __init__(self):
        self.submitted = []
        self.cancelled = []

    def submit(self, draft_id):
        self.submitted.append(draft_id)
        return RunHandle("run-web-1", draft_id)

    def snapshot(self, run_id):
        return {"run_id": run_id, "status": "running", "cancel_requested": False}

    def cancel(self, run_id):
        self.cancelled.append(run_id)
        return True


class _FakeRepository:
    def list_runs(self, query=None):
        return type("Page", (), {"items": ({"run_id": "run-web-1", "status": "running"},), "page": 1, "page_size": 50, "total": 1})()

    def get_run(self, run_id):
        return {"manifest": {"run_id": run_id, "status": "running"}, "cases": [], "events": [], "log_available": False}

    def get_case(self, run_id, case_id):
        return {"case_id": case_id, "result": {"ok": True}}

    def tail_log(self, run_id, line_count=200):
        return type("Tail", (), {"lines": ("wire",), "truncated": False, "tail": line_count})()


class WebRoutesTests(unittest.TestCase):
    def test_validate_uploads_draft_without_network_and_create_is_async(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = WebInputStore(root / "drafts")
            service = _FakeService()
            manager = _FakeManager()
            app = create_app(
                service=service,
                manager=manager,
                repository=_FakeRepository(),
                input_store=store,
                testing=True,
            )
            client = app.test_client()
            response = client.post(
                "/api/runs/validate",
                data={
                    "mode": "e2e",
                    "task_kind": "analysis",
                    "locale": "en-US",
                    "media": (io.BytesIO(b"fixture"), "chat.png"),
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(200, response.status_code)
            payload = response.get_json()
            self.assertEqual("e2e", payload["mode"])
            self.assertTrue(payload["draft_id"].startswith("draft-"))
            create = client.post("/api/runs", json={"draft_id": payload["draft_id"]})
            self.assertEqual(202, create.status_code)
            self.assertEqual([payload["draft_id"]], manager.submitted)

    def test_list_detail_case_log_cancel_and_health_routes(self):
        app = create_app(
            service=_FakeService(),
            manager=_FakeManager(),
            repository=_FakeRepository(),
            input_store=WebInputStore(Path(tempfile.mkdtemp()) / "drafts"),
            testing=True,
        )
        client = app.test_client()
        self.assertEqual(200, client.get("/health").status_code)
        self.assertEqual(200, client.get("/api/runs").status_code)
        self.assertEqual(200, client.get("/api/runs/run-web-1").status_code)
        self.assertEqual(200, client.get("/api/runs/run-web-1/cases/case-1").status_code)
        self.assertEqual(200, client.get("/api/runs/run-web-1/logs?tail=100").status_code)
        self.assertEqual(200, client.post("/api/runs/run-web-1/cancel").status_code)
        self.assertEqual(200, client.get("/runs/new").status_code)
        self.assertEqual(200, client.get("/runs").status_code)
        self.assertEqual(200, client.get("/runs/run-web-1").status_code)

    def test_default_port_is_5005_and_environment_can_override_only_port(self):
        with patch.dict("os.environ", {"AIDATING_WEB_PORT": "5011"}, clear=False):
            app = create_app(
                service=_FakeService(),
                manager=_FakeManager(),
                repository=_FakeRepository(),
                input_store=WebInputStore(Path(tempfile.mkdtemp()) / "drafts"),
                testing=True,
            )
        self.assertEqual(5011, app.config["WEB_PORT"])
        self.assertEqual("127.0.0.1", app.config["WEB_HOST"])


if __name__ == "__main__":
    unittest.main()
