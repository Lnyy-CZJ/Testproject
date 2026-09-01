from dataclasses import dataclass
from pathlib import Path
import tempfile
import threading
import time
import unittest

from aidating_eval.application import RunExecutionResult
from aidating_eval.domain import CaseOutcome, CaseOutcomeStatus, CleanupResult
from aidating_eval.runner import RunControl
from aidating_eval.web.input_store import WebInputStore
from aidating_eval.web.run_manager import RunManager


@dataclass
class _FakeArtifacts:
    updates: list[dict]

    def update_manifest(self, changes):
        self.updates.append(dict(changes))
        return dict(changes)


@dataclass
class _FakePrepared:
    run_id: str
    artifact_store: _FakeArtifacts
    summary: object


class _FakeService:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.prepare_calls = []
        self.execute_calls = []

    def prepare(self, request, *, run_id=None):
        self.prepare_calls.append(request)
        return _FakePrepared(
            run_id=run_id or "run-test-manager",
            artifact_store=_FakeArtifacts([]),
            summary=type("Summary", (), {"case_ids": ("case-1",), "case_count": 1})(),
        )

    def execute(self, prepared, *, control):
        self.execute_calls.append((prepared, control))
        self.started.set()
        self.release.wait(2)
        status = "cancelled" if control.reason == "RUN_CANCELLED" else "completed"
        outcome = CaseOutcome(
            "case-1",
            CaseOutcomeStatus.INCOMPLETE if control.reason else CaseOutcomeStatus.COMPLETED,
            None,
            control.reason,
            None,
            CleanupResult(True, "deleted"),
        )
        return RunExecutionResult(
            prepared.run_id,
            status,
            (outcome,),
            4 if control.reason else 0,
            control.reason,
        )


class RunManagerTests(unittest.TestCase):
    def test_only_one_web_run_is_active_and_cancel_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WebInputStore(Path(directory) / "drafts")
            draft1 = store.create_eval_draft(b"{}\n", filename="one.jsonl")
            draft2 = store.create_eval_draft(b"{}\n", filename="two.jsonl")
            service = _FakeService()
            manager = RunManager(service=service, input_store=store)
            handle = manager.submit(draft1.draft_id)
            self.assertTrue(service.started.wait(1))
            with self.assertRaises(ValueError):
                manager.submit(draft2.draft_id)
            self.assertTrue(manager.cancel(handle.run_id))
            self.assertTrue(manager.cancel(handle.run_id))
            service.release.set()
            result = manager.wait(handle.run_id, timeout=2)
            self.assertEqual("cancelled", result.status)
            snapshot = manager.snapshot(handle.run_id)
            self.assertEqual("cancelled", snapshot["status"])
            self.assertTrue(snapshot["cancel_requested"])
            self.assertFalse(draft1.root.exists())
            manager.shutdown()

    def test_prepare_failure_releases_claimed_draft(self):
        class BrokenService(_FakeService):
            def prepare(self, request, *, run_id=None):
                raise ValueError("invalid")

        with tempfile.TemporaryDirectory() as directory:
            store = WebInputStore(Path(directory) / "drafts")
            draft = store.create_eval_draft(b"{}\n", filename="one.jsonl")
            manager = RunManager(service=BrokenService(), input_store=store)
            with self.assertRaises(ValueError):
                manager.submit(draft.draft_id)
            with self.assertRaises(ValueError):
                store.get(draft.draft_id)
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
