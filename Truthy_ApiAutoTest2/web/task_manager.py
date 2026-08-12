"""单槽位任务执行引擎。

功能说明:
    以子进程 ``python -m pytest`` 驱动既有框架入口（对齐 Jenkinsfile
    语义），提供提交、等待、取消、超时与启动恢复能力。槽位检查、取消
    请求与终态提交使用同一状态锁；任务终态不可再次迁移。
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from web import credentials
from web.junit_report import parse_junit_file
from web.redaction import FAILED_MESSAGE_LIMIT, redact_text
from web.task_store import TaskStore, new_task_id

# 支持的运行类型，与 Jenkinsfile RUN_TYPE 语义一致。
RUN_TYPES = ("all", "single", "flow")

# 入口文件：对齐 Jenkins（直接 pytest 指定入口，而非 runtest.py）。
ENTRY_SINGLE = "test_cases/test_single_api.py"
ENTRY_FLOW = "test_cases/test_gateway_flow.py"

# tag 白名单：字母/数字/下划线/空格/括号；壳服务不解释 -m 表达式。
TAG_PATTERN = re.compile(r"^[A-Za-z0-9_()\s]+$")
TAG_MAX_LENGTH = 200

# 稳定错误码。
SLOT_BUSY = "SLOT_BUSY"
INVALID_PARAMS = "INVALID_PARAMS"
TASK_NOT_FOUND = "TASK_NOT_FOUND"
TASK_TERMINATED = "TASK_TERMINATED"
TASK_TIMEOUT = "TASK_TIMEOUT"
ALL_TESTS_SKIPPED = "ALL_TESTS_SKIPPED"

# 终态集合：进入后不可再次迁移。
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")

# pytest 退出码语义。
EXIT_NO_TESTS_COLLECTED = 5


class SubmissionError(Exception):
    """任务提交/取消被拒绝时携带 HTTP 状态码与稳定错误码。"""

    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


def _now_iso() -> str:
    """返回带时区的本地当前时间 ISO 字符串。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TaskManager:
    """单槽位执行引擎：同一时刻至多一个 pending/running 任务。

    参数说明:
        project_root: 被驱动框架的项目根目录。
        store: 任务记录存储器。
        timeout_seconds: 单任务执行超时上限。
        retain: 任务记录保留条数。
        python: 子进程解释器，默认当前解释器；测试可注入。
        cancel_grace_seconds: SIGTERM 后等待退出的宽限秒数，超过则 SIGKILL。
    """

    def __init__(
        self,
        project_root: Path,
        store: TaskStore,
        timeout_seconds: int = 1800,
        retain: int = 50,
        python: str | None = None,
        cancel_grace_seconds: float = 10.0,
        runtime_environment_provider: Callable[[], tuple[dict[str, str], dict[str, Any]]] | None = None,
    ) -> None:
        self._project_root = Path(project_root)
        self._store = store
        self._timeout_seconds = int(timeout_seconds)
        self._retain = int(retain)
        self._python = python or sys.executable
        self._cancel_grace_seconds = float(cancel_grace_seconds)
        self._runtime_environment_provider = runtime_environment_provider
        self._lock = threading.Lock()
        self._active_id: str | None = None
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancel_requested: set[str] = set()

    @property
    def project_root(self) -> Path:
        """被驱动框架的项目根目录。"""
        return self._project_root

    @property
    def store(self) -> TaskStore:
        """任务记录存储器。"""
        return self._store

    # ------------------------------------------------------------------
    # 提交前校验（全部本地检查，不发请求）
    # ------------------------------------------------------------------

    def _validate_input(
        self,
        env: str,
        run_type: str,
        flow: str | None,
        tag: str | None,
    ) -> dict[str, Any]:
        """校验并规范化提交参数。

        异常说明:
            SubmissionError: 400 + INVALID_PARAMS，消息指明具体字段问题。
        """
        env = (env or "").strip()
        if not env or Path(env).name != env:
            raise SubmissionError(400, INVALID_PARAMS, f"env 不合法: {env!r}")
        env_file = self._project_root / "config" / "env" / f"{env}.yaml"
        if not env_file.is_file():
            raise SubmissionError(400, INVALID_PARAMS, f"env 不存在: {env}")

        run_type = (run_type or "").strip()
        if run_type not in RUN_TYPES:
            raise SubmissionError(
                400, INVALID_PARAMS, f"run_type 必须是 {'/'.join(RUN_TYPES)}"
            )

        flow = (flow or "").strip() or None
        if flow is not None:
            if Path(flow).name != flow:
                raise SubmissionError(400, INVALID_PARAMS, f"flow 不合法: {flow!r}")
            if run_type == "single":
                raise SubmissionError(
                    400, INVALID_PARAMS, "run_type=single 时不得指定 flow"
                )
            flow_file = self._project_root / "data" / "flows" / f"{flow}.yaml"
            if not flow_file.is_file():
                raise SubmissionError(400, INVALID_PARAMS, f"flow 不存在: {flow}")

        if run_type == "flow" and flow is None:
            raise SubmissionError(400, INVALID_PARAMS, "run_type=flow 时 flow 必填")

        tag = (tag or "").strip() or None
        if tag is not None:
            if len(tag) > TAG_MAX_LENGTH or not TAG_PATTERN.match(tag):
                raise SubmissionError(
                    400, INVALID_PARAMS, "tag 仅允许字母、数字、下划线、空格和括号"
                )

        return {"env": env, "run_type": run_type, "flow": flow, "tag": tag}

    def _precheck_credentials(self, task_input: dict[str, Any]) -> None:
        """配置合并级与任务级凭证预检。

        异常说明:
            SubmissionError: 400 + CREDENTIAL_FILE_INVALID/CREDENTIALS_MISSING/
            ADMIN_CREDENTIALS_MISSING；Admin 缺失时消息只列字段名不含值。
        """
        settings, error_code, message = credentials.check_base_config(
            task_input["env"], self._project_root
        )
        if error_code is not None:
            raise SubmissionError(400, error_code, message)
        assert settings is not None

        if credentials.target_requires_admin(
            self._project_root,
            task_input["run_type"],
            task_input["flow"],
            task_input["tag"],
        ):
            missing = credentials.missing_admin_keys(settings)
            if missing:
                raise SubmissionError(
                    400,
                    credentials.ADMIN_CREDENTIALS_MISSING,
                    f"目标包含 Admin 审计步骤，缺少凭证: {', '.join(missing)}",
                )

    # ------------------------------------------------------------------
    # 提交与启动
    # ------------------------------------------------------------------

    def submit(
        self,
        env: str,
        run_type: str,
        flow: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        """提交一个新任务；校验失败或槽位被占用时抛出 SubmissionError。

        返回值:
            落盘后的任务记录（status 为 pending 或 running）。
        """
        task_input = self._validate_input(env, run_type, flow, tag)
        self._precheck_credentials(task_input)

        with self._lock:
            if self._active_id is not None:
                active = self._store.load(self._active_id)
                if active is not None and active.get("status") in (
                    "pending",
                    "running",
                ):
                    raise SubmissionError(
                        409, SLOT_BUSY, f"已有任务在执行: {self._active_id}"
                    )
            task_id = new_task_id()
            record = {
                "id": task_id,
                "status": "pending",
                "input": task_input,
                "pid": None,
                "created_at": _now_iso(),
                "started_at": None,
                "finished_at": None,
                "cancel_requested_at": None,
                "exit_code": None,
                "timeout": False,
                "error_code": None,
                "error_message": None,
                "result_available": False,
                "junit_file": f"reports/junit-task-{task_id}.xml",
                "log_file": None,
                "summary": {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 0,
                },
            }
            self._store.save(record)
            self._active_id = task_id

        # Popen 可能失败（解释器缺失等），失败时把任务置为 failed 并释放槽位。
        try:
            self._start(task_id)
        except Exception:
            self._fail_start(task_id)
            raise
        return self._store.load(task_id) or record

    def _build_command(
        self,
        task_input: dict[str, Any],
        junit_path: Path,
    ) -> list[str]:
        """组装 pytest 参数数组（不经 shell，无注入面）。"""
        entries = {
            "single": [ENTRY_SINGLE],
            "flow": [ENTRY_FLOW],
            "all": [ENTRY_SINGLE, ENTRY_FLOW],
        }[task_input["run_type"]]
        args = [
            self._python,
            "-m",
            "pytest",
            *entries,
            f"--env={task_input['env']}",
        ]
        if task_input.get("flow"):
            args.append(f"--flow={task_input['flow']}")
        if task_input.get("tag"):
            args.extend(["-m", task_input["tag"]])
        args.append(f"--junitxml={junit_path}")
        return args

    def _start(self, task_id: str) -> None:
        """启动子进程并派生等待线程。"""
        record = self._store.load(task_id)
        assert record is not None

        console_directory = self._store.console_dir(task_id)
        console_directory.mkdir(parents=True, exist_ok=True)
        console_path = self._store.console_log_path(task_id)
        junit_path = self._project_root / record["junit_file"]
        junit_path.parent.mkdir(parents=True, exist_ok=True)

        args = self._build_command(record["input"], junit_path)
        task_environment = os.environ.copy()
        if self._runtime_environment_provider is not None:
            runtime_values, snapshot_metadata = self._runtime_environment_provider()
            task_environment.update(runtime_values)
            record["config_release_id"] = snapshot_metadata.get("release_id")
            record["config_release_version"] = snapshot_metadata.get("release_version")
            record["credential_version"] = snapshot_metadata.get("credential_version")
            self._store.save(record)
        with console_path.open("w", encoding="utf-8") as console_file:
            proc = subprocess.Popen(
                args,
                cwd=self._project_root,
                env=task_environment,
                stdout=console_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        record["pid"] = proc.pid
        record["status"] = "running"
        record["started_at"] = _now_iso()
        with self._lock:
            self._store.save(record)
            self._procs[task_id] = proc
            thread = threading.Thread(
                target=self._wait,
                args=(task_id, proc),
                name=f"task-wait-{task_id}",
                daemon=True,
            )
            self._threads[task_id] = thread
        thread.start()

    def _fail_start(self, task_id: str) -> None:
        """子进程启动失败时写入 failed 终态并释放槽位。"""
        with self._lock:
            record = self._store.load(task_id)
            if record is not None:
                record["status"] = "failed"
                record["finished_at"] = _now_iso()
                record["error_message"] = "子进程启动失败，任务未执行"
                self._store.save(record)
            if self._active_id == task_id:
                self._active_id = None

    # ------------------------------------------------------------------
    # 等待、取消、超时与终态提交
    # ------------------------------------------------------------------

    def _terminate_group(self, proc: subprocess.Popen[bytes]) -> None:
        """向子进程组发送 SIGTERM，宽限期后仍未退出则 SIGKILL。"""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            proc.wait(timeout=self._cancel_grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def _wait(self, task_id: str, proc: subprocess.Popen[bytes]) -> None:
        """等待子进程结束；超时走终止流程，然后提交终态。"""
        timed_out = False
        try:
            proc.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate_group(proc)
            proc.wait()
        self._finalize(task_id, proc.returncode, timed_out)

    def cancel(self, task_id: str) -> dict[str, Any]:
        """取消指定任务。

        异常说明:
            SubmissionError: 404 任务不存在；409 任务已处于终态。

        返回值:
            标记取消请求后的任务记录。
        """
        with self._lock:
            record = self._store.load(task_id)
            if record is None:
                raise SubmissionError(404, TASK_NOT_FOUND, f"任务不存在: {task_id}")
            if record["status"] in TERMINAL_STATUSES:
                raise SubmissionError(
                    409, TASK_TERMINATED, f"任务已处于终态: {record['status']}"
                )
            record["cancel_requested_at"] = _now_iso()
            self._store.save(record)
            self._cancel_requested.add(task_id)
            proc = self._procs.get(task_id)

        if proc is not None:
            # 宽限期可能较长，放后台执行；等待线程会在进程退出后写入终态。
            threading.Thread(
                target=self._terminate_group,
                args=(proc,),
                name=f"task-cancel-{task_id}",
                daemon=True,
            ).start()
        return self._store.load(task_id) or record

    def _associate_log_file(
        self,
        pid: int | None,
        started_at: str | None,
        finished_at: str,
    ) -> str | None:
        """按子进程 PID 关联框架脱敏日志文件。

        功能说明:
            框架日志命名为 ``logs/YYYY-MM-DD/{时间戳}_{env}_{pid}.log``；
            在任务起止日期覆盖的日期目录中按 PID 后缀匹配。
        """
        if not pid:
            return None
        logs_root = self._project_root / "logs"
        try:
            start_date = datetime.fromisoformat(started_at).date()
        except (TypeError, ValueError):
            start_date = datetime.fromisoformat(finished_at).date()
        end_date = datetime.fromisoformat(finished_at).date()
        current = start_date
        while current <= end_date:
            day_directory = logs_root / current.strftime("%Y-%m-%d")
            if day_directory.is_dir():
                for path in sorted(day_directory.glob(f"*_{pid}.log")):
                    return path.relative_to(self._project_root).as_posix()
            current += timedelta(days=1)
        return None

    def _console_tail(self, task_id: str) -> str:
        """读取 console.log 尾部并完成二次脱敏（内部兜底输入）。"""
        console_path = self._store.console_log_path(task_id)
        if not console_path.is_file():
            return ""
        try:
            lines = console_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            return ""
        tail = "\n".join(lines[-50:])
        return redact_text(
            tail, project_root=self._project_root, max_length=FAILED_MESSAGE_LIMIT
        )

    def _finalize(
        self,
        task_id: str,
        exit_code: int | None,
        timed_out: bool,
    ) -> None:
        """在状态锁内提交终态；已处于终态时只补充退出码与产物信息。"""
        with self._lock:
            record = self._store.load(task_id)
            if record is None:
                self._cleanup_refs(task_id)
                return

            finished_at = _now_iso()
            junit_path = self._project_root / record["junit_file"]
            parsed = parse_junit_file(junit_path, self._project_root)
            cancelled_requested = task_id in self._cancel_requested

            record["exit_code"] = exit_code
            record["log_file"] = self._associate_log_file(
                record.get("pid"), record.get("started_at"), finished_at
            )

            if record["status"] in TERMINAL_STATUSES:
                # 取消/恢复等路径已先行写入终态：不覆盖，仅补充产物信息。
                if parsed is not None and record["status"] != "cancelled":
                    record["summary"] = parsed["summary"]
                    record["result_available"] = True
                record.setdefault("finished_at", finished_at)
                self._store.save(record)
                self._cleanup_refs(task_id)
                return

            if cancelled_requested:
                record["status"] = "cancelled"
                record["result_available"] = parsed is not None
                record["summary"] = parsed["summary"] if parsed else None
            elif timed_out:
                record["status"] = "failed"
                record["timeout"] = True
                record["error_code"] = TASK_TIMEOUT
                record["error_message"] = (
                    f"任务执行超时（上限 {self._timeout_seconds} 秒），已强制终止"
                )
                record["result_available"] = parsed is not None
                record["summary"] = parsed["summary"] if parsed else None
            else:
                record["result_available"] = parsed is not None
                record["summary"] = parsed["summary"] if parsed else None
                if exit_code == 0:
                    record["status"] = "succeeded"
                    summary = parsed["summary"] if parsed else None
                    if summary and summary["total"] > 0 and (
                        summary["skipped"] == summary["total"]
                    ):
                        # 全量跳过不是成功：避免“0 执行假成功”。
                        record["status"] = "failed"
                        record["error_code"] = ALL_TESTS_SKIPPED
                        record["error_message"] = (
                            f"全部 {summary['total']} 个用例被跳过，"
                            "未发生真实执行；请检查凭证与运行配置"
                        )
                else:
                    record["status"] = "failed"
                    record["error_message"] = self._failure_message(
                        task_id, exit_code, parsed is not None
                    )

            record["finished_at"] = finished_at
            self._store.save(record)
            self._cleanup_refs(task_id)
            if self._active_id == task_id:
                self._active_id = None
            self._store.enforce_retention(self._retain)

    def _failure_message(
        self,
        task_id: str,
        exit_code: int | None,
        junit_available: bool,
    ) -> str:
        """生成 failed 状态的可读错误信息（退出码 1 有 JUnit 时不附 console）。"""
        if exit_code == EXIT_NO_TESTS_COLLECTED:
            base = "未收集到任何用例（pytest 退出码 5）"
        elif junit_available:
            base = f"存在失败或错误用例（pytest 退出码 {exit_code}）"
        else:
            base = f"执行失败（pytest 退出码 {exit_code}），未生成 JUnit 结果"
        if exit_code == 1 and junit_available:
            return base
        tail = self._console_tail(task_id)
        return f"{base}\n{tail}".strip() if tail else base

    def _cleanup_refs(self, task_id: str) -> None:
        """清理进程/线程/取消标记引用（需在状态锁内调用）。"""
        self._procs.pop(task_id, None)
        self._threads.pop(task_id, None)
        self._cancel_requested.discard(task_id)

    # ------------------------------------------------------------------
    # 启动恢复与测试辅助
    # ------------------------------------------------------------------

    def recover_on_startup(self) -> int:
        """将遗留 pending/running 任务置为 failed（服务重启后子进程必然不存在）。

        返回值:
            被恢复的任务数量。
        """
        recovered = 0
        with self._lock:
            for record in self._store.list():
                if record.get("status") in ("pending", "running"):
                    record["status"] = "failed"
                    record["finished_at"] = _now_iso()
                    record["error_message"] = "服务重启，任务中断"
                    self._store.save(record)
                    recovered += 1
            self._active_id = None
        return recovered

    def wait_idle(self, timeout: float = 30.0) -> None:
        """等待全部等待线程结束；仅供测试与停机使用。"""
        while True:
            with self._lock:
                threads = list(self._threads.values())
            if not threads:
                return
            for thread in threads:
                thread.join(timeout=timeout)
            if not any(thread.is_alive() for thread in threads):
                return
