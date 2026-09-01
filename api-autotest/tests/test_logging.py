"""业务文件日志命名契约测试。"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from utils.custom.logger import configure_logging


def test_file_log_keeps_legacy_filename_without_platform_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未绑定平台任务时，文件日志必须继续使用历史命名格式。"""

    monkeypatch.delenv("API_AUTOTEST_TASK_ID", raising=False)

    log_path = configure_logging(
        log_directory=tmp_path,
        env="test",
        console=False,
        file=True,
        now=datetime(2026, 7, 27, 10, 30, 0),
    )

    assert log_path is not None
    assert log_path.parent == tmp_path / "2026-07-27"
    assert log_path.name == f"20260727_103000_000000_test_{os.getpid()}.log"


def test_file_log_includes_platform_task_id_without_extra_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """绑定平台任务时，文件名应携带任务 ID，且不增加额外目录层级。"""

    task_id = "20260830-101530-a1b2"
    monkeypatch.setenv("API_AUTOTEST_TASK_ID", task_id)

    log_path = configure_logging(
        log_directory=tmp_path,
        env="staging",
        console=False,
        file=True,
        now=datetime(2026, 8, 30, 10, 15, 30, 123456),
    )

    assert log_path is not None
    assert log_path.parent == tmp_path / "2026-08-30"
    assert log_path.name == (
        f"20260830_101530_123456_staging_{task_id}_{os.getpid()}.log"
    )
