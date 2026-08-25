"""文件级任务存储、恢复和保留策略。"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from services.common.task_models import TERMINAL_STATUSES, utc_now


TASK_ID_PATTERN = re.compile(r"^task_\d{8}_[0-9a-f]{20}$")


def new_task_id(now: datetime | None = None) -> str:
    """生成不可预测、可校验且大致可按日期识别的任务 ID。"""

    current = now or datetime.now(UTC)
    return f"task_{current:%Y%m%d}_{secrets.token_hex(10)}"


def is_valid_task_id(task_id: str) -> bool:
    """判断任务 ID 是否满足固定格式。"""

    return bool(TASK_ID_PATTERN.fullmatch(task_id or ""))


class TaskStore:
    """以任务目录为边界保存结构化状态。

    所有 JSON 采用同目录临时文件、fsync 和 os.replace，确保轮询读取不到半写内容。
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).resolve()
        self.tasks_dir = self.data_dir / "tasks"
        self.corrupt_dir = self.data_dir / "corrupt"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.corrupt_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def task_dir(self, task_id: str, *, create: bool = False) -> Path:
        """解析任务目录并阻止路径穿越。"""

        if not is_valid_task_id(task_id):
            raise ValueError("任务 ID 不合法")
        path = (self.tasks_dir / task_id).resolve()
        if path.parent != self.tasks_dir:
            raise ValueError("任务目录越界")
        if create:
            path.mkdir(mode=0o700, parents=False, exist_ok=False)
            for name in ("input", "work", "published"):
                (path / name).mkdir(mode=0o700)
        return path

    @staticmethod
    def atomic_write_json(path: Path, payload: Any) -> None:
        """原子保存 JSON，并尽力把文件内容同步到磁盘。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                # 某些文件系统不支持目录 fsync；文件本身仍已完成原子替换。
                pass
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        """保存任务记录并递增内部 revision。"""

        with self._lock:
            internal = record.setdefault("internal", {})
            internal["revision"] = int(internal.get("revision", 0)) + 1
            self.atomic_write_json(self.task_dir(record["id"]) / "task.json", record)
            return record

    @contextmanager
    def locked(self):
        """暴露单 worker 内的可重入事务锁，供跨文件 Review 操作复用。"""

        with self._lock:
            yield

    def load(self, task_id: str) -> dict[str, Any] | None:
        """读取任务；不存在或 JSON 损坏时返回 None。"""

        try:
            with (self.task_dir(task_id) / "task.json").open(encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else None
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return None

    @staticmethod
    def _is_visible_to(record: dict[str, Any], identity: Any) -> bool:
        """以根任务的不变快照执行 own/project/global 读取过滤。

        历史任务缺失平台快照时必须失败关闭。不能回退到浏览器 ``task.view.all``
        或任务表面的 project_id，避免旧 Header 和可编辑展示字段扩大数据范围。
        """

        internal = record.get("internal") or {}
        owner = internal.get("owner_user_id")
        project_id = internal.get("project_id_snapshot")
        access_scope = internal.get("access_scope_snapshot")
        if not isinstance(owner, str) or not isinstance(access_scope, str):
            return False
        if identity.data_scope == "global":
            return True
        if identity.data_scope == "own":
            return owner == identity.user_id
        return (
            identity.data_scope == "project"
            and access_scope == "project"
            and isinstance(project_id, str)
            and project_id in identity.managed_project_ids
        )

    def load_visible(self, task_id: str, identity: Any) -> dict[str, Any] | None:
        """读取单个根任务；不存在与越权均返回 None，供路由统一映射 404。"""

        record = self.load(task_id)
        return record if record and self._is_visible_to(record, identity) else None

    def list_visible(self, identity: Any) -> list[dict[str, Any]]:
        """在存储读取边界执行授权过滤，避免先返回全部任务再由页面隐藏。"""

        return [record for record in self.list() if self._is_visible_to(record, identity)]

    def list(self) -> list[dict[str, Any]]:
        """返回按创建时间倒序排列的有效任务，并隔离损坏记录。"""

        records = []
        for path in self.tasks_dir.iterdir():
            if not path.is_dir() or not is_valid_task_id(path.name):
                continue
            record = self.load(path.name)
            if record:
                records.append(record)
            elif (path / "task.json").exists():
                self._quarantine(path)
        return sorted(records, key=lambda item: (item.get("created_at", ""), item["id"]), reverse=True)

    def _quarantine(self, task_path: Path) -> None:
        """把含损坏 task.json 的完整任务目录移出活动队列，保留现场供运维排查。"""

        with self._lock:
            resolved = task_path.resolve()
            if resolved.parent != self.tasks_dir or not is_valid_task_id(resolved.name) or not resolved.exists():
                return
            suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            destination = self.corrupt_dir / f"{resolved.name}-{suffix}"
            os.replace(resolved, destination)

    def pending_fifo(self) -> list[dict[str, Any]]:
        """返回按最近入队时间和 ID 正序排列的 pending 任务。"""

        return sorted(
            (item for item in self.list() if item.get("status") == "pending"),
            key=lambda item: (item.get("queued_at") or item.get("created_at", ""), item["id"]),
        )

    def recover_interrupted(self) -> list[str]:
        """恢复服务重启状态，并清理任务目录中的临时文件。"""

        interrupted = []
        with self._lock:
            for record in self.list():
                task_path = self.task_dir(record["id"])
                for temporary in task_path.rglob("*.tmp"):
                    if temporary.is_file() and not temporary.is_symlink():
                        temporary.unlink(missing_ok=True)
                if record.get("status") == "running":
                    execution_kind = record.get("internal", {}).get("execution_kind")
                    if execution_kind in {"review_ai", "case_review_ai"}:
                        is_case = execution_kind == "case_review_ai"
                        prefix = "case_review_ai" if is_case else "review_ai"
                        record.update({"status": "waiting_case_review" if is_case else "waiting_review", "stage": f"{prefix}_failed", "error_code": None, "error_message": None})
                        record.setdefault(prefix, {}).update({"status": "failed", "error_code": "WORKER_INTERRUPTED", "error_message": "服务重启导致 AI 辅助中断，可继续人工 Review"})
                    else:
                        record.update({"status": "failed", "stage": "interrupted", "finished_at": utc_now(), "error_code": "WORKER_INTERRUPTED", "error_message": "服务重启导致任务中断，请创建重试任务"})
                    record.setdefault("internal", {})["pid"] = None
                    self.save(record)
                    interrupted.append(record["id"])
        return interrupted

    def retention_dry_run(
        self,
        *,
        summary_days: int = 180,
        artifact_days: int = 90,
        max_completed: int = 500,
        now: datetime | None = None,
    ) -> dict[str, list[str]]:
        """计算保留策略目标，不执行删除。"""

        current = now or datetime.now(UTC)
        terminal = [item for item in self.list() if item.get("status") in TERMINAL_STATUSES]
        terminal.sort(key=lambda item: (item.get("finished_at") or item.get("created_at", ""), item["id"]), reverse=True)
        remove_all: set[str] = set()
        expire_files: set[str] = set()
        for index, record in enumerate(terminal):
            raw_time = record.get("finished_at") or record.get("created_at")
            try:
                finished = datetime.fromisoformat(raw_time)
            except (TypeError, ValueError):
                continue
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=UTC)
            if finished <= current - timedelta(days=summary_days) or index >= max_completed:
                remove_all.add(record["id"])
            elif finished <= current - timedelta(days=artifact_days):
                expire_files.add(record["id"])
        expire_files.difference_update(remove_all)
        return {"remove_tasks": sorted(remove_all), "expire_artifacts": sorted(expire_files)}

    def enforce_retention(self, **kwargs: Any) -> dict[str, list[str]]:
        """逐任务执行已校验的保留计划。"""

        plan = self.retention_dry_run(**kwargs)
        with self._lock:
            for task_id in plan["expire_artifacts"]:
                record = self.load(task_id)
                if not record or record.get("status") not in TERMINAL_STATUSES:
                    continue
                task_path = self.task_dir(task_id)
                for name in ("input", "work", "published"):
                    target = task_path / name
                    if target.exists() and target.parent == task_path:
                        shutil.rmtree(target)
                for name in ("console.log", "runner-result.json"):
                    (task_path / name).unlink(missing_ok=True)
                record["artifacts_expired"] = True
                self.save(record)
            for task_id in plan["remove_tasks"]:
                record = self.load(task_id)
                if record and record.get("status") in TERMINAL_STATUSES:
                    shutil.rmtree(self.task_dir(task_id))
        return plan
