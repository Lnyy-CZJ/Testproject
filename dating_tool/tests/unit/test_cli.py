import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from aidating_eval.cli import (
    EXIT_CONFIG_OR_INPUT,
    EXIT_INCOMPLETE_OR_CLEANUP,
    EXIT_OK,
    build_parser,
    main,
)
from aidating_eval.config import Settings
from aidating_eval.domain import CleanupResult
from aidating_eval.domain import CaseOutcome, CaseOutcomeStatus
from aidating_eval.errors import ConfigurationError
from aidating_eval.cli import _outcome_exit_code, EXIT_AUTH_OR_ENV
from aidating_eval.cli import _pending_internal_tasks


class _MemoryWireLogger:
    path = Path("logs/2026-08-28/example.log")

    def __init__(self):
        self.events = []

    def write(self, event, **fields):
        self.events.append((event, fields))


class CliTests(unittest.TestCase):
    def setUp(self):
        """普通 CLI 单测使用内存日志，避免回归测试污染用户的真实 ``logs`` 目录。"""

        self._wire_log_patcher = patch(
            "aidating_eval.cli._start_wire_log",
            side_effect=lambda *args, **kwargs: _MemoryWireLogger(),
        )
        self.start_wire_log = self._wire_log_patcher.start()

    def tearDown(self):
        self._wire_log_patcher.stop()

    def test_command_surface_contains_only_four_mvp_commands(self):
        parser = build_parser()
        subparsers = next(
            action for action in parser._actions if action.dest == "command"
        )
        self.assertEqual(
            {"doctor", "validate", "run", "cleanup"},
            set(subparsers.choices),
        )

    def test_auth_exit_code_has_priority_when_cleanup_is_pending(self):
        outcome = CaseOutcome(
            "case",
            CaseOutcomeStatus.CLEANUP_PENDING,
            "task",
            "PERMISSION_DENIED",
            None,
            CleanupResult(False, "delete_failed"),
        )
        self.assertEqual(EXIT_AUTH_OR_ENV, _outcome_exit_code([outcome]))

    def test_validate_does_not_build_adapter_or_call_network(self):
        output = io.StringIO()
        with (
            patch("aidating_eval.cli.build_adapter") as build_adapter,
            redirect_stdout(output),
        ):
            code = main(
                [
                    "validate",
                    "--mode",
                    "eval",
                    "--dataset",
                    "tests/fixtures/cases/eval-mixed-valid.jsonl",
                ]
            )
        self.assertEqual(EXIT_OK, code)
        build_adapter.assert_not_called()
        self.assertNotIn("Please stop", output.getvalue())

    def test_validate_does_not_create_wire_log(self):
        with (
            patch("aidating_eval.cli._start_wire_log") as start_wire_log,
            redirect_stdout(io.StringIO()),
        ):
            code = main(
                [
                    "validate",
                    "--mode",
                    "eval",
                    "--dataset",
                    "tests/fixtures/cases/eval-mixed-valid.jsonl",
                ]
            )
        self.assertEqual(EXIT_OK, code)
        start_wire_log.assert_not_called()

    def test_doctor_uses_one_wire_log_for_adapter_and_prints_path(self):
        class DoctorAdapter:
            def doctor(self):
                return []

        logger = _MemoryWireLogger()
        settings = Settings(mode="eval")
        output = io.StringIO()
        with (
            patch("aidating_eval.cli.Settings.from_env", return_value=settings),
            patch("aidating_eval.cli._start_wire_log", return_value=logger),
            patch(
                "aidating_eval.cli.build_adapter", return_value=DoctorAdapter()
            ) as build_adapter,
            redirect_stdout(output),
        ):
            code = main(["doctor", "--mode", "eval"])

        self.assertEqual(EXIT_OK, code)
        build_adapter.assert_called_once_with(settings, wire_logger=logger)
        self.assertIn(f"LOG path={logger.path}", output.getvalue())

    def test_network_commands_create_log_before_configuration_or_input_failure(self):
        commands = [
            (["doctor", "--mode", "eval"], "raw config detail"),
            (
                ["run", "--mode", "eval", "--dataset", "missing.jsonl"],
                "Eval dataset 必须是 UTF-8 JSONL 文件",
            ),
        ]
        for command, expected_message in commands:
            with self.subTest(command=command):
                logger = _MemoryWireLogger()
                with (
                    patch(
                        "aidating_eval.cli._start_wire_log", return_value=logger
                    ) as start_wire_log,
                    patch(
                        "aidating_eval.cli.Settings.from_env",
                        side_effect=ConfigurationError("raw config detail"),
                    ),
                    redirect_stdout(io.StringIO()),
                ):
                    code = main(command)

                self.assertEqual(EXIT_CONFIG_OR_INPUT, code)
                start_wire_log.assert_called_once()
                error_events = [
                    fields
                    for event, fields in logger.events
                    if event == "cli_error"
                ]
                self.assertEqual(1, len(error_events))
                self.assertEqual(expected_message, error_events[0]["message"])

    def test_cli_reports_wire_log_degradation_without_changing_exit_code(self):
        class DegradedLogger(_MemoryWireLogger):
            failure_type = "OSError"

        class DoctorAdapter:
            def doctor(self):
                return []

        output = io.StringIO()
        with (
            patch(
                "aidating_eval.cli._start_wire_log", return_value=DegradedLogger()
            ),
            patch(
                "aidating_eval.cli.Settings.from_env",
                return_value=Settings(mode="eval"),
            ),
            patch(
                "aidating_eval.cli.build_adapter", return_value=DoctorAdapter()
            ),
            redirect_stdout(output),
        ):
            code = main(["doctor", "--mode", "eval"])

        self.assertEqual(EXIT_OK, code)
        self.assertIn("LOG status=degraded error=OSError", output.getvalue())

    def test_e2e_validate_prints_media_index_type_and_size_without_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "private-name.png"
            Image.new("RGB", (20, 20), "white").save(image_path)
            case = {
                "schema_version": "aidating.e2e.case.v1",
                "case_id": "safe-case",
                "task_kind": "analysis",
                "locale": "en-US",
                "media": [{"path": image_path.name}],
                "analysis": {},
                "expect": {
                    "task_status": "succeeded",
                    "result_schema": "dating.relationship_analysis.v1",
                },
            }
            dataset = root / "case.json"
            dataset.write_text(json.dumps(case), encoding="utf-8")
            output = io.StringIO()
            with (
                patch.dict(
                    "os.environ",
                    {"AIDATING_E2E_FIXTURE_ROOT": directory},
                    clear=False,
                ),
                redirect_stdout(output),
            ):
                code = main(
                    ["validate", "--mode", "e2e", "--dataset", str(dataset)]
                )
        rendered = output.getvalue()
        self.assertEqual(EXIT_OK, code)
        self.assertIn("MEDIA case=safe-case index=1 type=image/png bytes=", rendered)
        self.assertNotIn("private-name.png", rendered)
        self.assertNotIn(directory, rendered)

    def test_unknown_mode_returns_configuration_exit_code(self):
        with redirect_stderr(io.StringIO()):
            code = main(["doctor", "--mode", "unknown"])
        self.assertEqual(EXIT_CONFIG_OR_INPUT, code)

    def test_unexpected_exception_is_reduced_to_safe_exit_without_traceback(self):
        settings = Settings(mode="eval")
        output = io.StringIO()
        with (
            patch("aidating_eval.cli.Settings.from_env", return_value=settings),
            patch("aidating_eval.cli.build_adapter", side_effect=RuntimeError("private detail")),
            redirect_stdout(output),
        ):
            code = main(["doctor", "--mode", "eval"])
        self.assertEqual(1, code)
        self.assertIn("code=RuntimeError", output.getvalue())
        self.assertNotIn("private detail", output.getvalue())

    def test_cleanup_rejects_public_run_without_recoverable_token(self):
        with tempfile.TemporaryDirectory() as directory:
            run_path = Path(directory) / "run-e2e"
            run_path.mkdir()
            (run_path / "manifest.json").write_text(
                json.dumps({"run_id": "run-e2e", "config": {"mode": "e2e"}}),
                encoding="utf-8",
            )
            with (
                patch.dict(
                    "os.environ",
                    {"AIDATING_ARTIFACTS_ROOT": directory},
                    clear=False,
                ),
                redirect_stdout(io.StringIO()),
            ):
                code = main(["cleanup", "--run", "run-e2e"])
        self.assertEqual(EXIT_INCOMPLETE_OR_CLEANUP, code)
        self.start_wire_log.assert_not_called()

    def test_cleanup_without_pending_internal_task_does_not_create_wire_log(self):
        with tempfile.TemporaryDirectory() as directory:
            run_path = Path(directory) / "run-eval"
            run_path.mkdir()
            (run_path / "manifest.json").write_text(
                json.dumps({"run_id": "run-eval", "config": {"mode": "eval"}}),
                encoding="utf-8",
            )
            (run_path / "run-state.jsonl").write_text("", encoding="utf-8")
            with (
                patch.dict(
                    "os.environ",
                    {"AIDATING_ARTIFACTS_ROOT": directory},
                    clear=False,
                ),
                redirect_stdout(io.StringIO()),
            ):
                code = main(["cleanup", "--run", "run-eval"])

        self.assertEqual(EXIT_OK, code)
        self.start_wire_log.assert_not_called()

    def test_pending_internal_cleanup_starts_log_before_settings_failure(self):
        logger = _MemoryWireLogger()
        self.start_wire_log.side_effect = None
        self.start_wire_log.return_value = logger
        with tempfile.TemporaryDirectory() as directory:
            run_path = Path(directory) / "run-eval"
            run_path.mkdir()
            (run_path / "manifest.json").write_text(
                json.dumps({"run_id": "run-eval", "config": {"mode": "eval"}}),
                encoding="utf-8",
            )
            event = {
                "case_id": "analysis",
                "event": "task_created",
                "data": {
                    "attempt_id": "attempt-1",
                    "task_id": "task-1",
                    "task_kind": "analysis",
                    "mode": "eval",
                },
            }
            (run_path / "run-state.jsonl").write_text(
                json.dumps(event) + "\n", encoding="utf-8"
            )
            with (
                patch.dict(
                    "os.environ",
                    {"AIDATING_ARTIFACTS_ROOT": directory},
                    clear=False,
                ),
                patch(
                    "aidating_eval.cli.Settings.from_env",
                    side_effect=ConfigurationError("cleanup config detail"),
                ),
                redirect_stdout(io.StringIO()),
            ):
                code = main(["cleanup", "--run", "run-eval"])

        self.assertEqual(EXIT_CONFIG_OR_INPUT, code)
        self.start_wire_log.assert_called_once_with(
            "cleanup", mode="eval", run_id="run-eval"
        )
        self.assertIn(
            "cleanup config detail",
            [
                fields["message"]
                for event_name, fields in logger.events
                if event_name == "cli_error"
            ],
        )

    def test_validate_applies_case_filter_only_after_full_dataset_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            valid = Path("tests/fixtures/cases/eval-mixed-valid.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()[0]
            path.write_text(valid + "\n{bad json}\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "validate",
                        "--mode",
                        "eval",
                        "--dataset",
                        str(path),
                        "--case",
                        json.loads(valid)["case_id"],
                    ]
                )
        self.assertEqual(EXIT_CONFIG_OR_INPUT, code)

    def test_internal_cleanup_only_deletes_tasks_without_success_event(self):
        class CleanupAdapter:
            def __init__(self):
                self.deleted: list[tuple[str, str]] = []

            def delete_task(self, task_id, context):
                self.deleted.append((task_id, context.task_kind))
                return CleanupResult(True, "deleted", {"task_id": task_id})

        adapter = CleanupAdapter()
        with tempfile.TemporaryDirectory() as directory:
            run_path = Path(directory) / "run-eval"
            run_path.mkdir()
            (run_path / "manifest.json").write_text(
                json.dumps({"run_id": "run-eval", "config": {"mode": "eval"}}),
                encoding="utf-8",
            )
            events = [
                {"case_id": "reply", "event": "task_created", "data": {"attempt_id": "a1", "task_id": "t1", "task_kind": "reply", "mode": "eval"}},
                {"case_id": "reply", "event": "delete_succeeded", "data": {"attempt_id": "a1", "task_id": "t1", "task_kind": "reply", "mode": "eval"}},
                {"case_id": "analysis", "event": "task_created", "data": {"attempt_id": "a2", "task_id": "t2", "task_kind": "analysis", "mode": "eval"}},
            ]
            (run_path / "run-state.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            settings = Settings(
                mode="eval", artifacts_root=Path(directory), eval_concurrency=1
            )
            with (
                patch.dict("os.environ", {"AIDATING_ARTIFACTS_ROOT": directory}, clear=False),
                patch("aidating_eval.cli.Settings.from_env", return_value=settings),
                patch("aidating_eval.cli.build_adapter", return_value=adapter),
                redirect_stdout(io.StringIO()),
            ):
                code = main(["cleanup", "--run", "run-eval"])
            state = (run_path / "run-state.jsonl").read_text(encoding="utf-8")
        self.assertEqual(EXIT_OK, code)
        self.assertEqual([("t2", "analysis")], adapter.deleted)
        self.assertIn('"event":"delete_succeeded"', state)

    def test_cleanup_recovers_task_observed_before_create_contract_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            run_path = Path(directory)
            event = {
                "case_id": "analysis",
                "event": "task_observed",
                "data": {
                    "attempt_id": "attempt-1",
                    "task_id": "task-observed",
                    "task_kind": "analysis",
                    "mode": "eval",
                },
            }
            (run_path / "run-state.jsonl").write_text(
                json.dumps(event) + "\n", encoding="utf-8"
            )
            pending = _pending_internal_tasks(run_path)
        self.assertEqual("task-observed", pending[0]["task_id"])

    def test_cleanup_cross_checks_manifest_run_id_and_event_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            run_path = Path(directory) / "run-eval"
            run_path.mkdir()
            (run_path / "manifest.json").write_text(
                json.dumps({"run_id": "different-run", "config": {"mode": "eval"}}),
                encoding="utf-8",
            )
            (run_path / "run-state.jsonl").write_text("", encoding="utf-8")
            with (
                patch.dict("os.environ", {"AIDATING_ARTIFACTS_ROOT": directory}, clear=False),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    EXIT_CONFIG_OR_INPUT,
                    main(["cleanup", "--run", "run-eval"]),
                )

            (run_path / "manifest.json").write_text(
                json.dumps({"run_id": "run-eval", "config": {"mode": "eval"}}),
                encoding="utf-8",
            )
            event = {"case_id": "case", "event": "task_created", "data": {"attempt_id": "a1", "task_id": "t1", "task_kind": "analysis", "mode": "e2e"}}
            (run_path / "run-state.jsonl").write_text(
                json.dumps(event) + "\n", encoding="utf-8"
            )
            with (
                patch.dict("os.environ", {"AIDATING_ARTIFACTS_ROOT": directory}, clear=False),
                patch("aidating_eval.cli.build_adapter") as build_adapter,
                redirect_stdout(io.StringIO()),
            ):
                code = main(["cleanup", "--run", "run-eval"])
        self.assertEqual(EXIT_CONFIG_OR_INPUT, code)
        build_adapter.assert_not_called()


class CliRawWireLogFailureTests(unittest.TestCase):
    """使用真实日志工厂验证初始 I/O 故障不会改变业务退出结果。"""

    def test_unusable_log_root_is_fail_open_for_doctor(self):
        class DoctorAdapter:
            def doctor(self):
                return []

        with tempfile.TemporaryDirectory() as directory:
            unusable_root = Path(directory) / "logs-is-a-file"
            unusable_root.write_text("occupied", encoding="utf-8")
            output = io.StringIO()
            with (
                patch.dict(
                    "os.environ",
                    {"AIDATING_LOG_ROOT": str(unusable_root)},
                    clear=False,
                ),
                patch(
                    "aidating_eval.cli.Settings.from_env",
                    return_value=Settings(mode="eval"),
                ),
                patch(
                    "aidating_eval.cli.build_adapter",
                    return_value=DoctorAdapter(),
                ),
                redirect_stdout(output),
            ):
                code = main(["doctor", "--mode", "eval"])

        self.assertEqual(EXIT_OK, code)
        self.assertIn(
            "LOG status=degraded error=FileExistsError", output.getvalue()
        )


if __name__ == "__main__":
    unittest.main()
