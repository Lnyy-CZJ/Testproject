"""任务记录的文件级存储。

功能说明:
    任务记录保存为 ``tasks/<task_id>.json``；子进程标准输出保存为
    ``tasks/<task_id>/console.log``。写入使用同目录临时文件 +
    flush/fsync + ``os.replace`` 原子替换，保证并发轮询读取时不会看到
    半份 JSON。任务 ID 采用 ``YYYYMMDD-HHMMSS-<4位十六进制>``，
    天然按时间排序。
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

# 任务 ID 格式：日期-时间-4 位十六进制随机后缀。
TASK_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


def new_task_id(now: datetime | None = None) -> str:
    """生成一个新的任务 ID。

    参数说明:
        now: 可选当前时间；未提供时使用系统时间，测试可注入固定时间。

    返回值:
        形如 ``20260807-163012-a1b2`` 的任务 ID。
    """
    moment = now or datetime.now()
    return f"{moment.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def is_valid_task_id(task_id: str) -> bool:
    """判断任务 ID 是否符合格式，防止路径穿越。"""
    return bool(TASK_ID_PATTERN.match(task_id or ""))


class TaskStore:
    """负责任务 JSON 的原子读写、列表、保留策略与关联产物清理。

    参数说明:
        tasks_dir: 任务记录目录 ``tasks/``。
        reports_dir: 报告目录 ``reports/``，删除任务时同步清理任务 JUnit。
    """

    def __init__(self, tasks_dir: Path, reports_dir: Path) -> None:
        self._tasks_dir = Path(tasks_dir)
        self._reports_dir = Path(reports_dir)
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    @property
    def tasks_dir(self) -> Path:
        """任务记录目录。"""
        return self._tasks_dir

    def record_path(self, task_id: str) -> Path:
        """返回任务 JSON 路径；ID 非法时抛出 ValueError。"""
        if not is_valid_task_id(task_id):
            raise ValueError(f"非法任务 ID: {task_id!r}")
        return self._tasks_dir / f"{task_id}.json"

    def console_dir(self, task_id: str) -> Path:
        """返回任务 console 输出目录 ``tasks/<task_id>/``。"""
        if not is_valid_task_id(task_id):
            raise ValueError(f"非法任务 ID: {task_id!r}")
        return self._tasks_dir / task_id

    def console_log_path(self, task_id: str) -> Path:
        """返回任务 console.log 路径。"""
        return self.console_dir(task_id) / "console.log"

    def save(self, record: dict[str, Any]) -> None:
        """原子写入一条任务记录。

        功能说明:
            先写同目录临时文件，flush/fsync 后用 ``os.replace`` 替换正式
            文件，确保任何时刻读取方看到的都是完整 JSON。

        参数说明:
            record: 任务记录字典，必须包含合法 ``id``。

        异常说明:
            ValueError: 记录缺少合法 ID 时抛出。
            OSError: 磁盘写入失败时由底层文件操作透传。
        """
        task_id = record.get("id", "")
        final_path = self.record_path(task_id)
        tmp_path = final_path.with_name(f".{task_id}.tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(record, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, final_path)

    def load(self, task_id: str) -> dict[str, Any] | None:
        """读取一条任务记录；不存在时返回 None。"""
        path = self.record_path(task_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, Any]]:
        """返回全部任务记录，按 ID 倒序（最新在前）。

        功能说明:
            ID 前缀为时间戳，字典序倒排即时间倒序。损坏或临时文件跳过。
        """
        records: list[dict[str, Any]] = []
        for path in self._tasks_dir.glob("*.json"):
            if path.name.startswith("."):
                continue
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                # 并发清理或异常残留不应阻断列表接口，跳过即可。
                continue
        records.sort(key=lambda item: item.get("id", ""), reverse=True)
        return records

    def delete(self, task_id: str) -> bool:
        """删除任务记录及其 console 目录与任务 JUnit。

        返回值:
            记录存在并完成删除返回 True；记录不存在返回 False。
        """
        path = self.record_path(task_id)
        record = self.load(task_id)
        if record is None and not path.exists():
            return False

        # 任务 JUnit 命名固定为 junit-task-<id>.xml，随记录同步清理。
        junit_path = self._reports_dir / f"junit-task-{task_id}.xml"
        if junit_path.is_file():
            junit_path.unlink()
        console_directory = self.console_dir(task_id)
        if console_directory.is_dir():
            shutil.rmtree(console_directory, ignore_errors=True)
        if path.is_file():
            path.unlink()
        return True

    def enforce_retention(self, retain: int) -> list[str]:
        """按保留条数清理最旧的任务记录。

        参数说明:
            retain: 保留条数上限，必须为正整数。

        返回值:
            被删除的任务 ID 列表（最新在前顺序中超出部分）。
        """
        if retain < 1:
            raise ValueError(f"保留条数必须为正整数，实际值: {retain}")
        records = self.list()
        removed: list[str] = []
        for record in records[retain:]:
            task_id = record.get("id", "")
            if is_valid_task_id(task_id) and self.delete(task_id):
                removed.append(task_id)
        return removed
