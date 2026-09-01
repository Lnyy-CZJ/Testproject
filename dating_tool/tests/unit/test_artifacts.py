import json
import tempfile
import unittest
from pathlib import Path

from aidating_eval.artifacts import ArtifactStore


class ArtifactStoreTests(unittest.TestCase):
    """运行状态必须私密、可追加且在落盘前统一脱敏。"""

    def test_writes_private_files_and_append_only_events(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory), "run-1")
            store.append_event(
                "case-1",
                "task_created",
                {"task_id": "task-1", "authorization": "secret"},
            )
            store.append_event("case-1", "task_succeeded", {"task_id": "task-1"})
            store.write_case_payload("case-1", "task.json", {"status": "queued"})
            run_path = Path(directory) / "run-1"
            event_path = run_path / "run-state.jsonl"
            task_path = run_path / "cases" / "case-1" / "task.json"

            self.assertEqual(0o700, run_path.stat().st_mode & 0o777)
            self.assertEqual(0o600, event_path.stat().st_mode & 0o777)
            self.assertEqual(0o600, task_path.stat().st_mode & 0o777)
            events = [json.loads(line) for line in event_path.read_text().splitlines()]
            self.assertEqual(2, len(events))
            self.assertNotIn("authorization", events[0]["data"])

    def test_case_artifacts_use_filename_specific_allowlists(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory), "run-safe")
            path = store.write_case_payload(
                "case-safe",
                "task.json",
                {
                    "task_id": "task-safe",
                    "status": "failed",
                    "error_code": "MODEL_OUTPUT_INVALID",
                    "prompt": "private prompt",
                    "model_output": "private generated body",
                    "reasoning": "private reasoning",
                    "conversation": {"text": "private chat"},
                    "future_unknown_body": "private future field",
                },
            )
            stored = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            {
                "error_code": "MODEL_OUTPUT_INVALID",
                "status": "failed",
                "task_id": "task-safe",
            },
            stored,
        )

    def test_manifest_uses_only_supplied_redacted_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory), "run-2")
            path = store.start_run({"mode": "eval", "eval_api_key": "***"})
            manifest = json.loads((path / "manifest.json").read_text())
            self.assertEqual("***", manifest["config"]["eval_api_key"])

    def test_manifest_update_merges_run_metadata_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory), "run-manifest")
            path = store.start_run({"mode": "eval"})

            updated = store.update_manifest(
                {
                    "schema_version": "aidating.run.manifest.v1",
                    "status": "running",
                    "case_count": 2,
                    "wire_log_path": "2026-08-31/run.log",
                }
            )

            self.assertEqual("run-manifest", updated["run_id"])
            self.assertEqual("running", updated["status"])
            self.assertEqual(2, updated["case_count"])
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(updated, manifest)
            self.assertEqual(0o600, (path / "manifest.json").stat().st_mode & 0o777)

    def test_manifest_update_cannot_replace_identity_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory), "run-immutable")
            store.start_run({"mode": "eval"})

            with self.assertRaises(ValueError):
                store.update_manifest({"run_id": "other-run"})

    def test_rejects_case_id_and_payload_name_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory), "run-3")
            for case_id, filename in (("../escape", "task.json"), ("case", "../x")):
                with self.subTest(case_id=case_id, filename=filename), self.assertRaises(
                    ValueError
                ):
                    store.write_case_payload(case_id, filename, {})


if __name__ == "__main__":
    unittest.main()
