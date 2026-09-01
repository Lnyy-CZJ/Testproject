"""Web Run 的单 Worker 生命周期管理。

Flask 请求线程只负责认领 Draft、创建本地 Run 和提交后台 Future；真实 Adapter、轮询、
限流、幂等和 finally Delete 仍全部由 ``RunApplicationService`` 与既有 Runner 执行。这里
唯一额外的状态是本地 Web 控制状态，所有状态变更同时写入 Manifest，供重启后的历史查询
使用。
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
import os
from pathlib import Path
from threading import Lock
from typing import Any

from aidating_eval.application import (
    RunApplicationService,
    RunExecutionResult,
    RunRequest,
)
from aidating_eval.domain import CaseOutcomeStatus
from aidating_eval.runner import RunControl
from aidating_eval.web.input_store import DraftRecord, WebInputStore


FINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "blocked", "cleanup_pending"})


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    draft_id: str


@dataclass
class _ManagedRun:
    handle: RunHandle
    control: RunControl
    prepared: Any
    status: str = "waiting"
    cancel_requested: bool = False
    error_code: str | None = None
    result: RunExecutionResult | None = None
    future: Future[RunExecutionResult] | None = None
    lock: Lock = field(default_factory=Lock, repr=False)


class RunManager:
    """保证单个 Web Run 执行、取消和 Draft finally 清理。"""

    def __init__(
        self,
        *,
        service: RunApplicationService,
        input_store: WebInputStore,
        max_workers: int = 1,
    ) -> None:
        if max_workers != 1:
            raise ValueError("Web Run 外层必须固定单 Worker")
        self.service = service
        self.input_store = input_store
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dating-web-run")
        self._runs: dict[str, _ManagedRun] = {}
        self._lock = Lock()

    def submit(self, draft_id: str) -> RunHandle:
        """认领 Draft、准备本地 Run，并异步执行；同一时刻只接受一个活动 Run。"""

        with self._lock:
            if any(item.status not in FINAL_STATUSES for item in self._runs.values()):
                raise ValueError("已有 Web Run 正在执行")
            draft = self.input_store.claim(draft_id)
            try:
                prepared = self.service.prepare(
                    RunRequest(**draft.to_request_kwargs())
                )
            except Exception:
                self.input_store.delete(draft_id)
                raise
            handle = RunHandle(prepared.run_id, draft_id)
            managed = _ManagedRun(handle, RunControl(), prepared)
            self._runs[handle.run_id] = managed
            self._manifest(
                prepared,
                {
                    "mode": draft.mode,
                    "task_kind": draft.task_kind,
                    "case_ids": list(prepared.summary.case_ids),
                    "case_count": prepared.summary.case_count,
                    "status": "waiting",
                    "cancel_requested": False,
                    "cleanup_status": "pending",
                    "wire_log_path": self._wire_log_relative(prepared),
                    "summary": self._summary(prepared.summary),
                },
            )
            try:
                managed.future = self.executor.submit(self._execute, managed, draft)
            except Exception:
                self._runs.pop(handle.run_id, None)
                self.input_store.delete(draft_id)
                raise
            return handle

    def cancel(self, run_id: str) -> bool:
        """请求停止；无论重复调用多少次都不会重新创建远端 Task。"""

        with self._lock:
            managed = self._runs.get(run_id)
        if managed is None:
            return False
        managed.cancel_requested = True
        managed.control.request_stop("RUN_CANCELLED")
        self._manifest(managed.prepared, {"cancel_requested": True, "status": "cancelling"})
        return True

    def snapshot(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            managed = self._runs.get(run_id)
        if managed is None:
            return None
        with managed.lock:
            return {
                "run_id": run_id,
                "draft_id": managed.handle.draft_id,
                "status": managed.status,
                "cancel_requested": managed.cancel_requested,
                "error_code": managed.error_code,
                "exit_code": managed.result.exit_code if managed.result else None,
            }

    def wait(self, run_id: str, *, timeout: float | None = None) -> RunExecutionResult:
        with self._lock:
            managed = self._runs.get(run_id)
        if managed is None or managed.future is None:
            raise ValueError("Run 不存在")
        try:
            return managed.future.result(timeout=timeout)
        except FutureTimeout:
            raise TimeoutError("Run 尚未完成") from None

    def recover_after_restart(self) -> None:
        """当前进程不恢复远端任务；调用方可在启动时把旧活动 Run 标为 interrupted。"""

        # 真实 Task 的跨进程清理继续使用 CLI 的 Internal cleanup；Public Token 不能从磁盘恢复。
        return None

    def shutdown(self, *, wait: bool = True) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=False)

    def _execute(self, managed: _ManagedRun, draft: DraftRecord) -> RunExecutionResult:
        with managed.lock:
            managed.status = "running"
        self._manifest(managed.prepared, {"status": "running"})
        try:
            result = self.service.execute(managed.prepared, control=managed.control)
            with managed.lock:
                managed.result = result
                managed.status = result.status
                managed.error_code = result.error_code
            counts = Counter(item.status.value for item in result.outcomes)
            cleanup_status = (
                "pending"
                if any(item.status is CaseOutcomeStatus.CLEANUP_PENDING for item in result.outcomes)
                else "deleted"
            )
            self._manifest(
                managed.prepared,
                {
                    "status": result.status,
                    "cleanup_status": cleanup_status,
                    "summary": {
                        "case_count": len(result.outcomes),
                        "completed": counts.get("completed", 0),
                        "failed": counts.get("failed", 0),
                        "incomplete": counts.get("incomplete", 0),
                        "cleanup_pending": counts.get("cleanup_pending", 0),
                        "exit_code": result.exit_code,
                        "error_code": result.error_code,
                    },
                },
            )
            return result
        except Exception as exc:
            with managed.lock:
                managed.status = "failed"
                managed.error_code = type(exc).__name__
            self._manifest(
                managed.prepared,
                {
                    "status": "failed",
                    "cleanup_status": "pending",
                    "summary": {"error_code": type(exc).__name__},
                },
            )
            raise
        finally:
            # Draft 只保存本地临时图片/JSONL；远端 Task 的删除已由 CaseRunner finally 完成。
            try:
                self.input_store.delete(draft.draft_id)
            except Exception as exc:
                with managed.lock:
                    managed.error_code = managed.error_code or "DRAFT_CLEANUP_FAILED"
                    if managed.status == "completed":
                        managed.status = "cleanup_pending"
                self._manifest(
                    managed.prepared,
                    {"status": managed.status, "cleanup_status": "pending", "error_code": "DRAFT_CLEANUP_FAILED"},
                )

    @staticmethod
    def _summary(summary: Any) -> dict[str, Any]:
        return {
            "case_count": getattr(summary, "case_count", 0),
            "reply_count": getattr(summary, "reply_count", 0),
            "analysis_count": getattr(summary, "analysis_count", 0),
            "message_count": getattr(summary, "message_count", 0),
            "input_bytes": getattr(summary, "input_bytes", 0),
            "media_count": getattr(summary, "media_count", 0),
            "normal_create_requests": getattr(summary, "normal_create_requests", 0),
            "worst_case_create_requests": getattr(summary, "worst_case_create_requests", 0),
            "eval_concurrency": getattr(summary, "eval_concurrency", None),
        }

    @staticmethod
    def _wire_log_relative(prepared: Any) -> str | None:
        logger = getattr(prepared, "wire_logger", None)
        path = getattr(logger, "path", None)
        if path is None:
            return None
        try:
            root = Path(os.getenv("AIDATING_LOG_ROOT", "logs")).resolve()
            return Path(path).resolve().relative_to(root).as_posix()
        except (ValueError, TypeError):
            return str(path)

    @staticmethod
    def _manifest(prepared: Any, changes: dict[str, Any]) -> None:
        try:
            prepared.artifact_store.update_manifest(changes)
        except Exception:
            # Manifest 是诊断增强，不允许掩盖 Runner 的远端 finally Delete；Case Artifact
            # 的自身写入失败仍由既有 CaseRunner 转为 ARTIFACT_WRITE_FAILED。
            return


__all__ = ["RunHandle", "RunManager"]
