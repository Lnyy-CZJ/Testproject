import json
from pathlib import Path
import tempfile
import unittest

from aidating_eval.web.run_repository import RunQuery, RunRepository


class RunRepositoryTests(unittest.TestCase):
    def _write_run(
        self,
        artifacts_root: Path,
        logs_root: Path,
        run_id: str,
        created_at: str,
        *,
        status: str = "completed",
    ) -> None:
        run_path = artifacts_root / run_id
        case_path = run_path / "cases" / "case-1"
        case_path.mkdir(parents=True)
        (run_path / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "aidating.run.manifest.v1",
                    "run_id": run_id,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "status": status,
                    "mode": "eval",
                    "task_kind": "analysis",
                    "case_ids": ["case-1"],
                    "case_count": 1,
                    "wire_log_path": "2026-08-31/run.log",
                    "cleanup_status": "deleted",
                }
            ),
            encoding="utf-8",
        )
        (case_path / "metadata.json").write_text(
            json.dumps({"case_id": "case-1", "task_kind": "analysis"}),
            encoding="utf-8",
        )
        (case_path / "result.json").write_text(
            json.dumps({"schema_version": "dating.relationship_analysis.v1"}),
            encoding="utf-8",
        )
        log_path = logs_root / "2026-08-31" / "run.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")

    def test_lists_runs_by_newest_and_reads_case_and_log_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            logs = root / "logs"
            self._write_run(artifacts, logs, "run-old", "2026-08-31T09:00:00Z")
            self._write_run(artifacts, logs, "run-new", "2026-08-31T10:00:00Z")
            repository = RunRepository(artifacts_root=artifacts, logs_root=logs)

            page = repository.list_runs(RunQuery(page=1, page_size=50))
            detail = repository.get_run("run-new")
            case = repository.get_case("run-new", "case-1")
            tail = repository.tail_log("run-new", line_count=100)

        self.assertEqual(["run-new", "run-old"], [item["run_id"] for item in page.items])
        self.assertEqual("run-new", detail["manifest"]["run_id"])
        self.assertEqual("dating.relationship_analysis.v1", case["result"]["schema_version"])
        self.assertEqual(("line-1", "line-2", "line-3"), tail.lines)
        self.assertFalse(tail.truncated)

    def test_filters_status_and_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            logs = root / "logs"
            self._write_run(artifacts, logs, "run-ok", "2026-08-31T10:00:00Z")
            self._write_run(
                artifacts,
                logs,
                "run-failed",
                "2026-08-31T11:00:00Z",
                status="failed",
            )
            repository = RunRepository(artifacts_root=artifacts, logs_root=logs)

            page = repository.list_runs(RunQuery(status="failed"))
            with self.assertRaises(ValueError):
                repository.get_run("../run-ok")
            with self.assertRaises(ValueError):
                repository.get_case("run-ok", "../case-1")
            with self.assertRaises(ValueError):
                repository.tail_log("run-ok", line_count=99)

        self.assertEqual(["run-failed"], [item["run_id"] for item in page.items])

    def test_rejects_symlinked_run_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            logs = root / "logs"
            artifacts.mkdir()
            logs.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / "manifest.json").write_text(
                json.dumps({"run_id": "run-link"}), encoding="utf-8"
            )
            (artifacts / "run-link").symlink_to(outside, target_is_directory=True)
            repository = RunRepository(artifacts_root=artifacts, logs_root=logs)

            with self.assertRaises(ValueError):
                repository.get_run("run-link")

    def test_legacy_manifest_gets_non_persistent_summary_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            logs = root / "logs"
            run_path = artifacts / "legacy-run"
            case_path = run_path / "cases" / "case-legacy"
            case_path.mkdir(parents=True)
            (run_path / "manifest.json").write_text(
                json.dumps({"run_id": "legacy-run", "config": {"mode": "eval"}}),
                encoding="utf-8",
            )
            (run_path / "run-state.jsonl").write_text(
                json.dumps({"case_id": "case-legacy", "event": "case_finished", "data": {"task_kind": "analysis", "status": "completed"}}) + "\n",
                encoding="utf-8",
            )
            repository = RunRepository(artifacts_root=artifacts, logs_root=logs)
            detail = repository.get_run("legacy-run")
            self.assertEqual("eval", detail["manifest"]["mode"])
            self.assertEqual("analysis", detail["manifest"]["task_kind"])
            self.assertEqual("completed", detail["manifest"]["status"])
            self.assertEqual(1, detail["manifest"]["case_count"])


if __name__ == "__main__":
    unittest.main()
