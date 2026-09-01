import json
from pathlib import Path
import tempfile
import unittest

from aidating_eval.application import (
    RunApplicationService,
    RunRequest,
)
from aidating_eval.config import Settings
from aidating_eval.domain import RunMode
from aidating_eval.runner import RunControl
from tests.helpers import FakeAdapter


class _MemoryWireLogger:
    path = Path("logs/test-application.log")

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def write(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


class ApplicationServiceTests(unittest.TestCase):
    def test_validate_returns_eval_summary_without_loading_settings_or_network(self):
        request = RunRequest(
            mode=RunMode.EVAL,
            dataset_path=Path("tests/fixtures/cases/eval-mixed-valid.jsonl"),
            eval_concurrency=2,
        )

        service = RunApplicationService(
            settings_factory=lambda _: self.fail("validate 不应读取远端配置")
        )

        summary = service.validate(request)

        self.assertEqual("mixed", summary.task_kind)
        self.assertEqual(2, summary.case_count)
        self.assertEqual(8, summary.message_count)
        self.assertEqual(2, summary.eval_concurrency)
        self.assertEqual(2, summary.normal_create_requests)

    def test_execute_uses_existing_runner_and_returns_completed_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "analysis.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "schema_version": "aidating.eval.case.v1",
                        "case_id": "application-analysis",
                        "task_kind": "analysis",
                        "locale": "en-US",
                        "transcript": {
                            "schema_version": "dating.transcript.v1",
                            "messages": [
                                {"message_id": "m1", "speaker": "other", "message_type": "text", "text": "hello"},
                                {"message_id": "m2", "speaker": "self", "message_type": "text", "text": "hi"},
                                {"message_id": "m3", "speaker": "other", "message_type": "text", "text": "ready?"},
                                {"message_id": "m4", "speaker": "self", "message_type": "text", "text": "yes"},
                            ],
                        },
                        "expect": {
                            "task_status": "succeeded",
                            "result_schema": "dating.relationship_analysis.v1",
                        },
                    }
                ),
                encoding="utf-8",
            )
            adapter = FakeAdapter(
                tasks=[],
                result={"schema_version": "dating.relationship_analysis.v1"},
                diagnostics={"model_alias": "fixture"},
            )
            # FakeAdapter 的任务序列只需要初始 succeeded 快照；直接构造避免依赖测试实现细节。
            from aidating_eval.domain import TaskSnapshot

            adapter.tasks = [
                TaskSnapshot(
                    "application-task",
                    "relationship_analysis",
                    "succeeded",
                    "done",
                )
            ]
            settings = Settings(
                mode="eval",
                eval_base_url="https://lb-rg3phjei-vzmdn2i7ey8rq40l.clb.usw-tencentclb.com/admin/invoke",
                eval_api_key="fixture-key",
                artifacts_root=root / "artifacts",
                eval_concurrency=1,
            )
            logger = _MemoryWireLogger()
            service = RunApplicationService(
                settings_factory=lambda _: settings,
                adapter_factory=lambda _settings, **_: adapter,
            )
            prepared = service.prepare(
                RunRequest(RunMode.EVAL, dataset, eval_concurrency=1),
                run_id="run-application",
                wire_logger=logger,
            )

            result = service.execute(prepared, control=RunControl())

        self.assertEqual("completed", result.status)
        self.assertEqual(0, result.exit_code)
        self.assertEqual(["application-analysis"], [item.case_id for item in result.outcomes])
        self.assertEqual(["application-task"], adapter.deleted_task_ids)
        self.assertIn(("run_bound", {"mode": "eval", "run_id": "run-application"}), logger.events)


if __name__ == "__main__":
    unittest.main()
