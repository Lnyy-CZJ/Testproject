"""单槽位持久化 FIFO 调度器。"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from services.common.artifacts import merge_registry
from services.common.errors import ServiceError
from services.common.prompt_version import prompt_bundle_sha256
from services.common.task_models import TERMINAL_STATUSES, utc_now


def _running_stage(execution_kind: str) -> str:
    """把执行类型映射为可恢复的运行阶段；未知类型保留旧通用语义。"""

    return {
        "document_preflight": "document_preflight_running",
        "base_case_generation": "base_case_generation_running",
        "executable_generation": "executable_generation_running",
        "case_review_ai": "case_review_ai_running",
        "review_ai": "review_ai_running",
        "generate_cases": "generating_test_cases",
    }.get(execution_kind, "starting")
from services.common.task_store import TaskStore


ConfigLoader = Callable[[dict[str, Any]], dict[str, Any]]
ResultCollector = Callable[[str, Path, dict[str, Any]], dict[str, Any]]


class TaskManager:
    """管理一个智能体服务的持久化队列和 Runner 子进程。

    关键约束:
        TaskStore 是队列事实来源；内存只保存活动进程。生产配置必须只有一个 Web worker。
    """

    def __init__(
        self,
        *,
        store: TaskStore,
        runner_module: str,
        config_loader: ConfigLoader,
        result_collector: ResultCollector,
        project_root: Path,
        prompt_paths: list[str],
        app_revision: str,
        default_timeout: int = 3600,
        default_max_waiting: int = 5,
        autostart: bool = True,
        require_llm_config: bool = True,
    ):
        self.store = store
        self.runner_module = runner_module
        self.config_loader = config_loader
        self.result_collector = result_collector
        self.project_root = Path(project_root).resolve()
        self.prompt_paths = prompt_paths
        self.app_revision = app_revision
        self.default_timeout = default_timeout
        self.default_max_waiting = default_max_waiting
        self.require_llm_config = require_llm_config
        self._condition = threading.Condition(threading.RLock())
        self._active_task_id: str | None = None
        self._active_process: subprocess.Popen[bytes] | None = None
        self._stopping = False
        self._retention_limits = {
            "summary_days": 180,
            "artifact_days": 90,
            "max_completed": 500,
        }
        self.store.recover_interrupted()
        # 启动扫描只处理终态任务；异常不应阻止服务恢复 pending 队列。
        try:
            self.store.enforce_retention(**self._retention_limits)
        except OSError:
            pass
        self._thread = threading.Thread(target=self._dispatch_loop, name=f"dispatcher-{runner_module}", daemon=True)
        if autostart:
            self._thread.start()

    def queue_size(self) -> int:
        """返回当前等待任务数。"""

        return len(self.store.pending_fifo())

    def assert_capacity(self, max_waiting: int | None = None, *, error_code: str = "TASK_QUEUE_FULL") -> None:
        """在锁内校验等待队列容量，并允许 Review 保持兼容错误码。"""

        limit = self.default_max_waiting if max_waiting is None else int(max_waiting)
        if limit < 0 or self.queue_size() >= limit:
            raise ServiceError(409, error_code, "当前等待任务已达到上限，请稍后重试")

    def _write_execution(self, record: dict[str, Any], *, kind: str, queued_at: str, review_version: int | None = None, request_version: int | None = None) -> dict[str, Any]:
        """递增执行序号并原子保存当前执行信封，隔离迟到 Runner 结果。"""

        internal = record.setdefault("internal", {})
        sequence = int(internal.get("execution_sequence", 0)) + 1
        internal.update({"execution_sequence": sequence, "execution_kind": kind})
        execution = {"schema_version": 1, "sequence": sequence, "kind": kind, "queued_at": queued_at, "review_version": review_version}
        execution["case_review_ai_request_version" if kind == "case_review_ai" else "review_ai_request_version"] = request_version
        TaskStore.atomic_write_json(self.store.task_dir(record["id"]) / "execution.json", execution)
        return execution

    def submit(self, record: dict[str, Any], request_payload: dict[str, Any], *, max_waiting: int | None = None) -> dict[str, Any]:
        """原子提交已创建目录的任务并通知调度器。"""

        with self._condition:
            self.assert_capacity(max_waiting)
            task_dir = self.store.task_dir(record["id"])
            TaskStore.atomic_write_json(task_dir / "request.json", request_payload)
            record["queued_at"] = record.get("created_at") or utc_now()
            self._write_execution(record, kind="initial", queued_at=record["queued_at"])
            self.store.save(record)
            self._condition.notify_all()
            return record

    def resume(self, task_id: str, review_metadata: dict[str, Any], *, max_waiting: int | None = None) -> dict[str, Any]:
        """把 Review 任务重新放入 FIFO；队列满时保持 waiting_review。"""

        with self._condition:
            record = self.store.load(task_id)
            if not record or record.get("status") != "waiting_review":
                raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许继续")
            self.assert_capacity(max_waiting, error_code="QUEUE_FULL")
            record["review"] = review_metadata
            queued_at = utc_now()
            record.update({"status": "pending", "stage": "queued", "resume_requested_at": queued_at, "queued_at": queued_at})
            self._write_execution(record, kind="generate_cases", queued_at=queued_at, review_version=review_metadata.get("version"))
            self.store.save(record)
            self._condition.notify_all()
            return record

    def enqueue_review_ai(self, task_id: str, request_metadata: dict[str, Any], *, max_waiting: int | None = None) -> dict[str, Any]:
        """把 AI 辅助请求放入与正式生成共享的 FIFO。"""

        with self._condition:
            record = self.store.load(task_id)
            if not record or record.get("status") != "waiting_review":
                raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许发起 AI 辅助")
            self.assert_capacity(max_waiting, error_code="QUEUE_FULL")
            queued_at = utc_now()
            record.update({"status": "pending", "stage": "review_ai_queued", "queued_at": queued_at, "review_ai": request_metadata})
            self._write_execution(record, kind="review_ai", queued_at=queued_at, request_version=request_metadata.get("request_version"))
            self.store.save(record)
            self._condition.notify_all()
            return record

    def cancel_review_ai(self, task_id: str) -> dict[str, Any]:
        """取消 AI 子阶段并返回 Review，不把主任务标记为 cancelled。"""

        process: subprocess.Popen[bytes] | None = None
        with self._condition:
            record = self.store.load(task_id)
            if not record or record.get("internal", {}).get("execution_kind") != "review_ai" or record.get("status") not in {"pending", "running"}:
                raise ServiceError(409, "INVALID_TASK_STATE", "当前没有可取消的 AI 辅助")
            if record.get("status") == "pending":
                record.update({"status": "waiting_review", "stage": "review_ai_cancelled"})
                record.setdefault("review_ai", {}).update({"status": "cancelled", "error_code": None, "error_message": None})
                self.store.save(record)
                self._condition.notify_all()
                return record
            record.setdefault("internal", {})["review_ai_cancel_requested_at"] = utc_now()
            self.store.save(record)
            if self._active_task_id == task_id:
                process = self._active_process
        if process is not None:
            self._terminate_group(process)
        return self.store.load(task_id) or {}

    def enqueue_case_review_ai(self, task_id: str, request_metadata: dict[str, Any], *, max_waiting: int | None = None) -> dict[str, Any]:
        """把用例 AI 请求放入公共 FIFO，并保持用例 Review 独立状态。"""

        with self._condition:
            record = self.store.load(task_id)
            if not record or record.get("status") != "waiting_case_review":
                raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许发起用例 AI 辅助")
            self.assert_capacity(max_waiting, error_code="QUEUE_FULL")
            queued_at = utc_now()
            record.update({"status": "pending", "stage": "case_review_ai_queued", "queued_at": queued_at, "case_review_ai": request_metadata})
            self._write_execution(record, kind="case_review_ai", queued_at=queued_at, request_version=request_metadata.get("request_version"))
            self.store.save(record)
            self._condition.notify_all()
            return record

    def cancel_case_review_ai(self, task_id: str) -> dict[str, Any]:
        """取消用例 AI 子阶段，保留用例草稿和主任务。"""

        process: subprocess.Popen[bytes] | None = None
        with self._condition:
            record = self.store.load(task_id)
            if not record or record.get("internal", {}).get("execution_kind") != "case_review_ai" or record.get("status") not in {"pending", "running"}:
                raise ServiceError(409, "INVALID_TASK_STATE", "当前没有可取消的用例 AI 辅助")
            if record.get("status") == "pending":
                record.update({"status": "waiting_case_review", "stage": "case_review_ai_cancelled"})
                record.setdefault("case_review_ai", {}).update({"status": "cancelled", "error_code": None, "error_message": None})
                self.store.save(record)
                self._condition.notify_all()
                return record
            record.setdefault("internal", {})["case_review_ai_cancel_requested_at"] = utc_now()
            self.store.save(record)
            if self._active_task_id == task_id:
                process = self._active_process
        if process is not None:
            self._terminate_group(process)
        return self.store.load(task_id) or {}

    def cancel(self, task_id: str) -> dict[str, Any]:
        """取消等待、Review 或运行任务，并确保终止完整进程组。"""

        process: subprocess.Popen[bytes] | None = None
        with self._condition:
            record = self.store.load(task_id)
            if not record or record.get("status") in TERMINAL_STATUSES:
                raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许取消")
            record["cancel_requested_at"] = utc_now()
            if record.get("status") in {
                "pending", "waiting_review", "waiting_contract_review", "waiting_case_review",
                "waiting_executable_review", "waiting_execution_confirmation",
            }:
                record.update({"status": "cancelled", "stage": "cancelled", "finished_at": utc_now()})
                self.store.save(record)
                self._condition.notify_all()
                return record
            self.store.save(record)
            if self._active_task_id == task_id:
                process = self._active_process
        if process is not None:
            self._terminate_group(process)
        record = self.store.load(task_id)
        return record or {}

    def stop(self) -> None:
        """停止调度器；仅供测试或服务优雅退出使用。"""

        with self._condition:
            self._stopping = True
            process = self._active_process
            self._condition.notify_all()
        if process is not None:
            self._terminate_group(process)
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _dispatch_loop(self) -> None:
        """持续选择最早 pending 任务，单任务完成后释放槽位。"""

        while True:
            with self._condition:
                if self._stopping:
                    return
                pending = self.store.pending_fifo()
                if not pending:
                    self._condition.wait(timeout=1.0)
                    continue
                task_id = pending[0]["id"]
                self._active_task_id = task_id
            self._run_task(task_id)
            with self._condition:
                self._active_task_id = None
                self._active_process = None
                self._condition.notify_all()

    def _runner_environment(self, snapshot: dict[str, Any], task_id: str) -> dict[str, str]:
        """从允许列表构造子进程环境，禁止传递平台 Client Token。"""

        normal = snapshot.get("normal", {}) or {}
        secrets = snapshot.get("secrets", {}) or {}
        llm = snapshot.get("llm") or {}
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(self.project_root),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "TASK_ID": task_id,
            "AGENT_DATA_DIR": str(self.store.data_dir),
            "LLM_MODEL": str(llm.get("model") or normal.get("LLM_MODEL", "deepseek-v4-flash")),
            "base_url": str(llm.get("base_url") or normal.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")),
            "DASHSCOPE_API_KEY": str(llm.get("api_key") or secrets.get("LLM_API_KEY", "")),
            "DATABASE_PERSIST_ENABLED": str(normal.get("DATABASE_PERSIST_ENABLED", False)).lower(),
            "API_EXECUTION_ENABLED": "false",
            "ALLOWED_TARGETS": json.dumps(normal.get("ALLOWED_TARGETS", []), ensure_ascii=False),
            "CONTRACT_QUALITY_MIN_SCORE": str(normal.get("CONTRACT_QUALITY_MIN_SCORE", 0.8)),
            "COVERAGE_MAX_ROUNDS": str(normal.get("COVERAGE_MAX_ROUNDS", 3)),
            "DEFAULT_SLOW_THRESHOLD_MS": str(normal.get("DEFAULT_SLOW_THRESHOLD_MS", 3000)),
            "SLOW_CONFIRMATION_RUNS": str(normal.get("SLOW_CONFIRMATION_RUNS", 3)),
            "PROMPT_BUNDLE_SHA256": str(snapshot.get("prompt_bundle_sha256", "")),
        }
        for field, env_key in (("temperature", "LLM_TEMPERATURE"), ("max_tokens", "LLM_MAX_TOKENS"), ("timeout_seconds", "LLM_TIMEOUT_SECONDS")):
            if llm.get(field) is not None:
                environment[env_key] = str(llm[field])
        legacy_database_keys = {
            "DB_HOST": "db_name", "DB_PORT": "db_port", "DB_USER": "db_user",
            "DB_PASSWORD": "db_password", "DB_NAME": "db_database",
        }
        for source, destination in legacy_database_keys.items():
            if source in secrets:
                environment[destination] = str(secrets[source])
        return environment

    def _run_task(self, task_id: str) -> None:
        """读取一次完整配置、启动 Runner 并原子提交终态。"""

        record = self.store.load(task_id)
        if not record or record.get("status") != "pending":
            return
        try:
            # 必须把当前任务记录传给加载器，按创建时 selector 物化；禁止排队后
            # 静默读取其他用户或最新版本的配置。
            snapshot = self.config_loader(record)
            normal = snapshot.get("normal", {}) or {}
            self._retention_limits = {
                "summary_days": int(normal.get("TASK_SUMMARY_RETENTION_DAYS", 180)),
                "artifact_days": int(normal.get("TASK_ARTIFACT_RETENTION_DAYS", 90)),
                "max_completed": int(normal.get("TASK_MAX_COMPLETED", 500)),
            }
            llm_snapshot = snapshot.get("llm") or {}
            if self.require_llm_config and not (llm_snapshot.get("api_key") or (snapshot.get("secrets", {}) or {}).get("LLM_API_KEY")):
                raise ServiceError(503, "CONFIG_NOT_READY", "LLM API Key 尚未配置")
            model_name = str(llm_snapshot.get("model") or normal.get("LLM_MODEL", "deepseek-v4-flash"))
            bundle = prompt_bundle_sha256(self.project_root, self.prompt_paths)
            snapshot["prompt_bundle_sha256"] = bundle
            phase_config = {
                "release_id": snapshot.get("release_id"),
                "release_version": snapshot.get("release_version"),
                "llm_profile_release_id": llm_snapshot.get("profile_release_id"),
                "llm_binding_release_id": llm_snapshot.get("binding_release_id"),
                "llm_snapshot_id": llm_snapshot.get("snapshot_id"),
                "model_name": model_name,
                "prompt_bundle_sha256": bundle,
                "loaded_at": utc_now(),
            }
            record.setdefault("config_history", []).append(phase_config)
            kind = record.get("internal", {}).get("execution_kind", "initial")
            running_stage = _running_stage(kind)
            record.update({
                "status": "running", "stage": running_stage, "started_at": utc_now(),
                "config_release_id": snapshot.get("release_id"),
                "config_release_version": snapshot.get("release_version"),
                "llm_profile_release_id": llm_snapshot.get("profile_release_id"),
                "llm_binding_release_id": llm_snapshot.get("binding_release_id"),
                "llm_snapshot_id": llm_snapshot.get("snapshot_id"),
                "model_name": model_name, "prompt_bundle_sha256": bundle,
                "app_revision": self.app_revision,
            })
            self.store.save(record)
            task_dir = self.store.task_dir(task_id)
            log_handle = (task_dir / "console.log").open("ab", buffering=0)
            try:
                process = subprocess.Popen(
                    [sys.executable, "-m", self.runner_module, "--task-id", task_id],
                    cwd=self.project_root,
                    env=self._runner_environment(snapshot, task_id),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                with self._condition:
                    self._active_process = process
                    latest = self.store.load(task_id) or record
                    latest.setdefault("internal", {})["pid"] = process.pid
                    self.store.save(latest)
                timeout_key = "CASE_REVIEW_AI_TIMEOUT_SECONDS" if kind == "case_review_ai" else ("REVIEW_AI_TIMEOUT_SECONDS" if kind == "review_ai" else "TASK_TIMEOUT_SECONDS")
                timeout = int(normal.get(timeout_key, 600 if kind in {"review_ai", "case_review_ai"} else self.default_timeout))
                timed_out = False
                try:
                    exit_code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._terminate_group(process)
                    exit_code = process.returncode if process.returncode is not None else -9
            finally:
                log_handle.close()
            latest = self.store.load(task_id) or record
            if latest.get("status") in TERMINAL_STATUSES:
                return
            result = self._read_runner_result(task_id)
            if kind in {"review_ai", "case_review_ai"} and latest.get("internal", {}).get(f"{kind}_cancel_requested_at"):
                self._return_to_review(latest, stage=f"{kind}_cancelled", error_code=None, error_message=None)
            elif latest.get("cancel_requested_at"):
                self._finish(latest, status="cancelled", stage="cancelled")
            elif timed_out:
                if kind in {"review_ai", "case_review_ai"}:
                    self._return_to_review(latest, stage=f"{kind}_failed", error_code="LLM_TIMEOUT", error_message="AI 辅助执行超时，请稍后重试")
                else:
                    self._finish(latest, status="failed", stage="timeout", error_code="TASK_TIMEOUT", error_message="任务执行超时")
            elif not self._result_matches(latest, result):
                return
            elif exit_code != 0:
                if kind in {"review_ai", "case_review_ai"}:
                    self._return_to_review(latest, stage=f"{kind}_failed", error_code=result.get("error_code", "WORKER_FAILED"), error_message=result.get("error_message", "AI 辅助执行失败"), exit_code=exit_code)
                else:
                    self._finish(latest, status="failed", stage=result.get("stage", "runner_failed"), error_code=result.get("error_code", "WORKER_FAILED"), error_message=result.get("error_message", "智能体任务执行失败"), exit_code=exit_code)
            elif kind in {"review_ai", "case_review_ai"}:
                latest.setdefault(kind, {}).update(result.get(kind, {}))
                latest[kind]["status"] = "ready"
                self._return_to_review(latest, stage=f"{kind}_ready", error_code=None, error_message=None, exit_code=exit_code)
            else:
                collected = self.result_collector(task_id, task_dir, self._read_runner_result(task_id))
                artifacts = collected.pop("artifacts", [])
                # 阶段式 Runner 已可能登记上游产物；这里只合并，绝不覆盖成功阶段。
                merge_registry(self.store, task_id, artifacts)
                latest = self.store.load(task_id) or latest
                result_summary = collected.pop("result_summary", {})
                final_status = collected.pop("status", "succeeded")
                final_stage = collected.pop("stage", "completed")
                self._finish(
                    latest,
                    status=final_status,
                    stage=final_stage,
                    exit_code=exit_code,
                    updates={"result_summary": result_summary, **collected},
                )
        except ServiceError as exc:
            latest = self.store.load(task_id) or record
            if latest.get("status") not in TERMINAL_STATUSES:
                execution_kind = latest.get("internal", {}).get("execution_kind")
                if execution_kind in {"review_ai", "case_review_ai"}:
                    self._return_to_review(latest, stage=f"{execution_kind}_failed", error_code=exc.code, error_message=exc.message)
                else:
                    self._finish(latest, status="failed", stage="configuration", error_code=exc.code, error_message=exc.message)
        except Exception:
            latest = self.store.load(task_id) or record
            if latest.get("status") not in TERMINAL_STATUSES:
                execution_kind = latest.get("internal", {}).get("execution_kind")
                if execution_kind in {"review_ai", "case_review_ai"}:
                    self._return_to_review(latest, stage=f"{execution_kind}_failed", error_code="WORKER_START_FAILED", error_message="AI 辅助工作进程启动失败")
                else:
                    self._finish(latest, status="failed", stage="worker", error_code="WORKER_START_FAILED", error_message="任务工作进程启动或收集失败")

    @staticmethod
    def _result_matches(record: dict[str, Any], result: dict[str, Any]) -> bool:
        """拒绝旧执行阶段迟到写回的结果。"""

        internal = record.get("internal", {})
        if "execution_sequence" not in internal:
            return True
        return result.get("execution_sequence") == internal.get("execution_sequence") and result.get("execution_kind") == internal.get("execution_kind")

    def _return_to_review(self, record: dict[str, Any], *, stage: str, error_code: str | None, error_message: str | None, exit_code: int | None = None) -> None:
        """提交 AI 子阶段的可恢复结果，保留主任务产物和草稿。"""

        is_case = stage.startswith("case_review_ai_")
        metadata_key = "case_review_ai" if is_case else "review_ai"
        review_ai = dict(record.get(metadata_key, {}))
        review_ai.update({"status": "ready" if stage.endswith("_ready") else ("cancelled" if stage.endswith("_cancelled") else "failed"), "error_code": error_code, "error_message": error_message})
        internal = dict(record.get("internal", {}))
        internal.pop(f"{metadata_key}_cancel_requested_at", None)
        self._finish(record, status="waiting_case_review" if is_case else "waiting_review", stage=stage, error_code=None, error_message=None, exit_code=exit_code, updates={metadata_key: review_ai, "internal": internal})

    def _read_runner_result(self, task_id: str) -> dict[str, Any]:
        """读取 Runner 结构化结果，损坏时返回空字典。"""

        try:
            value = json.loads((self.store.task_dir(task_id) / "runner-result.json").read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _finish(
        self,
        record: dict[str, Any],
        *,
        status: str,
        stage: str,
        error_code: str | None = None,
        error_message: str | None = None,
        exit_code: int | None = None,
        updates: dict[str, Any] | None = None,
    ) -> None:
        """提交首次合法终态或 waiting_review，并原子合并结果摘要。

        参数说明:
            record: 调度阶段读取的任务记录。
            status: 本次合法转换的目标状态。
            stage: 对用户可见的执行阶段。
            error_code/error_message: 失败时的稳定错误信息。
            exit_code: Runner 进程退出码，仅写入内部字段。
            updates: 产物收集完成后需要随终态一起提交的公开结果字段。

        异常策略:
            锁内始终重新读取最新记录；若取消等终态已经先提交，本次迟到结果
            直接丢弃，避免覆盖取消状态或其他首次终态。
        """

        should_cleanup = False
        with self._condition:
            latest = self.store.load(record["id"]) or record
            if latest.get("status") in TERMINAL_STATUSES:
                return
            if updates:
                latest.update(updates)
            latest.update({"status": status, "stage": stage, "error_code": error_code, "error_message": error_message})
            latest.setdefault("internal", {}).update({"pid": None, "exit_code": exit_code})
            if status in TERMINAL_STATUSES:
                latest["finished_at"] = utc_now()
                should_cleanup = True
            self.store.save(latest)
        if should_cleanup:
            try:
                self.store.enforce_retention(**self._retention_limits)
            except OSError:
                # 清理失败不得回写或覆盖已提交的业务终态，后续启动扫描会重试。
                pass

    @staticmethod
    def _terminate_group(process: subprocess.Popen[bytes]) -> None:
        """先 SIGTERM，最多等待 10 秒，再 SIGKILL 完整进程组。"""

        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
