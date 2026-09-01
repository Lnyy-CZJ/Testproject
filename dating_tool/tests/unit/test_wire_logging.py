import json
import stat
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aidating_eval.wire_logging import RawWireLogger


class RawWireLoggerTests(unittest.TestCase):
    """原始 Wire Log 必须保真，并且能安全地被并发评测线程追加。"""

    def test_creates_requested_daily_path_and_private_permissions(self):
        fixed_time = datetime(
            2026,
            8,
            28,
            2,
            58,
            0,
            346901,
            tzinfo=timezone(timedelta(hours=8)),
        )
        with tempfile.TemporaryDirectory() as directory:
            logger = RawWireLogger.create(
                Path(directory) / "logs",
                now_fn=lambda: fixed_time,
                pid=20019,
            )

            self.assertEqual(
                Path(directory)
                / "logs"
                / "2026-08-28"
                / "20260828_025800_346901_test_20019.log",
                logger.path,
            )
            self.assertEqual(
                0o700,
                stat.S_IMODE(logger.path.parent.stat().st_mode),
            )
            self.assertEqual(0o600, stat.S_IMODE(logger.path.stat().st_mode))

    def test_writes_api_key_tokens_and_private_content_without_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = RawWireLogger.create(Path(directory) / "logs")
            logger.write(
                "http_request",
                headers={"Authorization": "Bearer adm_key_private"},
                body={
                    "device_id": "device-private",
                    "auth_token": "token-private",
                    "transcript": {
                        "messages": [{"text": "Please keep this exact."}]
                    },
                },
            )

            event = json.loads(logger.path.read_text(encoding="utf-8"))

        self.assertEqual(
            "Bearer adm_key_private", event["headers"]["Authorization"]
        )
        self.assertEqual("device-private", event["body"]["device_id"])
        self.assertEqual("token-private", event["body"]["auth_token"])
        self.assertEqual(
            "Please keep this exact.",
            event["body"]["transcript"]["messages"][0]["text"],
        )

    def test_concurrent_writes_produce_complete_parseable_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = RawWireLogger.create(Path(directory) / "logs")

            def write_events(worker: int) -> None:
                for index in range(25):
                    logger.write("event", worker=worker, index=index)

            threads = [
                threading.Thread(target=write_events, args=(worker,))
                for worker in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            lines = logger.path.read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in lines]

        self.assertEqual(200, len(events))
        self.assertEqual(list(range(1, 201)), sorted(e["sequence"] for e in events))
        self.assertEqual(200, len({e["sequence"] for e in events}))

    def test_deleted_log_is_not_recreated_with_relaxed_permissions(self):
        """外部删除日志后必须进入降级状态，不能按 umask 创建含密钥的新文件。"""

        with tempfile.TemporaryDirectory() as directory:
            logger = RawWireLogger.create(Path(directory) / "logs")
            logger.path.unlink()

            logger.write("http_request", headers={"Authorization": "secret"})

            self.assertFalse(logger.path.exists())
            self.assertEqual("FileNotFoundError", logger.failure_type)

    def test_initial_log_creation_failure_returns_degraded_logger(self):
        """日志根路径不可用时仍返回可检查对象，不能阻断真实评测命令。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "logs-is-a-file"
            root.write_text("occupied", encoding="utf-8")

            logger = RawWireLogger.create(root)

        self.assertEqual("FileExistsError", logger.failure_type)

    def test_permission_change_and_same_path_replacement_are_never_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "logs"

            chmod_logger = RawWireLogger.create(root)
            chmod_logger.path.chmod(0o644)
            chmod_logger.write("http_request", secret="must-not-be-written")
            self.assertEqual("PermissionError", chmod_logger.failure_type)
            self.assertEqual("", chmod_logger.path.read_text(encoding="utf-8"))

            replacement_logger = RawWireLogger.create(root)
            path = replacement_logger.path
            path.unlink()
            path.write_text("replacement\n", encoding="utf-8")
            path.chmod(0o600)
            replacement_logger.write(
                "http_request", secret="must-not-reach-replacement"
            )
            self.assertEqual("PermissionError", replacement_logger.failure_type)
            self.assertEqual("replacement\n", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
