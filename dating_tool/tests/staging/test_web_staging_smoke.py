"""显式 opt-in 的 Web -> staging smoke；默认永远不访问外部环境。"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aidating_eval.application import RunApplicationService
from aidating_eval.web.app import create_app
from aidating_eval.web.input_store import WebInputStore
from aidating_eval.web.run_manager import RunManager
from aidating_eval.web.run_repository import RunRepository
from dotenv import load_dotenv


RUN_STAGING = os.getenv("AIDATING_RUN_STAGING_TESTS") == "1"


@unittest.skipUnless(RUN_STAGING, "需要显式开启 staging 测试")
class WebStagingSmokeTests(unittest.TestCase):
    def test_internal_mixed_jsonl_can_run_from_web_and_cleanup(self):
        load_dotenv(override=False)
        source_lines = Path("datasets/eval-smoke.jsonl").read_text(encoding="utf-8").splitlines()
        content = ("\n".join(source_lines[:2]) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "AIDATING_ARTIFACTS_ROOT": str(Path(directory) / "artifacts"),
                "AIDATING_LOG_ROOT": str(Path(directory) / "logs"),
                "AIDATING_WEB_DRAFT_ROOT": str(Path(directory) / "drafts"),
            },
            clear=False,
        ):
            store = WebInputStore(Path(directory) / "drafts")
            service = RunApplicationService()
            manager = RunManager(service=service, input_store=store)
            repository = RunRepository(
                artifacts_root=Path(directory) / "artifacts",
                logs_root=Path(directory) / "logs",
                active_provider=manager.snapshot,
            )
            app = create_app(
                service=service,
                manager=manager,
                repository=repository,
                input_store=store,
                testing=True,
            )
            response = app.test_client().post(
                "/api/runs/validate",
                data={"mode": "eval", "dataset": (io.BytesIO(content), "mixed.jsonl")},
                content_type="multipart/form-data",
            )
            self.assertEqual(200, response.status_code, response.get_data(as_text=True))
            draft_id = response.get_json()["draft_id"]
            created = app.test_client().post("/api/runs", json={"draft_id": draft_id})
            self.assertEqual(202, created.status_code, created.get_data(as_text=True))
            result = manager.wait(created.get_json()["run_id"], timeout=300)
            self.assertEqual(0, result.exit_code)
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
