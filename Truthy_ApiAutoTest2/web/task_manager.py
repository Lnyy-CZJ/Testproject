"""单槽位任务执行引擎。

功能说明:
    以子进程 ``python -m pytest`` 驱动既有框架入口（对齐 Jenkinsfile
    语义），提供提交、等待、取消、超时与启动恢复能力。槽位检查、取消
    请求与终态提交使用同一状态锁；任务终态不可再次迁移。
"""

from __future__ import annotations

import inspect
import json
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
from web.task_store import TaskStore, is_valid_task_id, new_task_id
from utils.custom.config_loader import (
    ConfigError,
    create_runtime_snapshot_file,
    delete_runtime_snapshot_file,
    load_yaml,
)
from utils.custom.project_registry import (
    ProjectNotFoundError,
    ProjectPackage,
    ProjectRegistry,
    ProjectRegistryError,
)

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
PLATFORM_CONFIG_UNAVAILABLE = "PLATFORM_CONFIG_UNAVAILABLE"
PROJECT_PACKAGE_NOT_FOUND = "PROJECT_PACKAGE_NOT_FOUND"

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
        runtime_environment_provider: 平台模式的运行时配置快照提供器。
        runtime_plan_provider: 使用网关签名 Header 为新任务规划 Context/selector。
        platform_secret_keys_provider: 平台模式的 Secret 键名清单读取器，
            返回已配置键名集合，平台配置不可用时返回 None；仅供提交前
            Admin 凭证预检使用，Secret 值不进入壳服务内存。
    """

    def __init__(
        self,
        project_root: Path,
        store: TaskStore,
        timeout_seconds: int = 1800,
        retain: int = 50,
        python: str | None = None,
        cancel_grace_seconds: float = 10.0,
        runtime_plan_provider: Callable[[str, str], dict[str, Any]] | None = None,
        runtime_environment_provider: Callable[[dict[str, Any]], tuple[dict[str, str], dict[str, Any]]] | None = None,
        runtime_snapshot_provider: Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]] | None = None,
        platform_secret_keys_provider: Callable[[str], set[str] | None] | None = None,
        platform_environment: str = "dev",
    ) -> None:
        self._project_root = Path(project_root)
        self._store = store
        self._timeout_seconds = int(timeout_seconds)
        self._retain = int(retain)
        self._python = python or sys.executable
        self._cancel_grace_seconds = float(cancel_grace_seconds)
        self._runtime_plan_provider = runtime_plan_provider
        self._runtime_environment_provider = runtime_environment_provider
        self._runtime_snapshot_provider = runtime_snapshot_provider
        self._platform_secret_keys_provider = platform_secret_keys_provider
        if platform_environment not in {"dev", "prod"}:
            raise ValueError("platform_environment 必须为 dev 或 prod")
        self._platform_environment = platform_environment
        self._target_env = {"dev": "test", "prod": "prod"}[platform_environment]
        self._registry = ProjectRegistry(self._project_root / "projects")
        self._lock = threading.Lock()
        self._active_id: str | None = None
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancel_requested: set[str] = set()
        self._snapshot_files: dict[str, Path] = {}

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
        env: str | None,
        run_type: str,
        flow: str | None,
        tag: str | None,
        *,
        project_id: str | None = None,
        api_id: str | None = None,
        case_id: str | None = None,
        flow_id: str | None = None,
    ) -> dict[str, Any]:
        """校验并规范化旧版单项目或 V2 多项目提交参数。

        新页面必须传 ``project_id`` 及资源 ID，并且环境完全由当前平台实例
        派生；``env`` 仅保留给旧任务/CLI 兼容入口。两种模式不会同时扫描根
        ``data`` 和 ``projects``，从而避免同名资产串用。

        异常说明:
            SubmissionError: 400 + INVALID_PARAMS，消息指明具体字段问题。
        """
        run_type = (run_type or "").strip()
        if run_type not in RUN_TYPES:
            raise SubmissionError(
                400, INVALID_PARAMS, f"run_type 必须是 {'/'.join(RUN_TYPES)}"
            )

        tag = (tag or "").strip() or None
        if tag is not None:
            if len(tag) > TAG_MAX_LENGTH or not TAG_PATTERN.match(tag):
                raise SubmissionError(
                    400, INVALID_PARAMS, "tag 仅允许字母、数字、下划线、空格和括号"
                )

        legacy_mode = project_id is None and env is not None
        if legacy_mode:
            normalized_env = (env or "").strip()
            if not normalized_env or Path(normalized_env).name != normalized_env:
                raise SubmissionError(400, INVALID_PARAMS, f"env 不合法: {normalized_env!r}")
            env_file = self._project_root / "config" / "env" / f"{normalized_env}.yaml"
            if not env_file.is_file():
                raise SubmissionError(400, INVALID_PARAMS, f"env 不存在: {normalized_env}")
            normalized_flow = (flow or flow_id or "").strip() or None
            if normalized_flow is not None:
                if Path(normalized_flow).name != normalized_flow:
                    raise SubmissionError(400, INVALID_PARAMS, f"flow 不合法: {normalized_flow!r}")
                if run_type == "single":
                    raise SubmissionError(400, INVALID_PARAMS, "run_type=single 时不得指定 flow")
                flow_file = self._project_root / "data" / "flows" / f"{normalized_flow}.yaml"
                if not flow_file.is_file():
                    raise SubmissionError(400, INVALID_PARAMS, f"flow 不存在: {normalized_flow}")
            if run_type == "flow" and normalized_flow is None:
                raise SubmissionError(400, INVALID_PARAMS, "run_type=flow 时 flow 必填")
            return {
                "legacy_mode": True,
                "project_id": "truthy",
                "target_env": normalized_env,
                "config_source": "local",
                "env": normalized_env,
                "run_type": run_type,
                "api_id": None,
                "case_id": None,
                "flow_id": normalized_flow,
                "flow": normalized_flow,
                "tag": tag,
            }

        normalized_project_id = (project_id or "").strip()
        try:
            package = self._registry.get(normalized_project_id)
        except (ProjectNotFoundError, ProjectRegistryError) as exc:
            raise SubmissionError(
                400,
                PROJECT_PACKAGE_NOT_FOUND,
                f"项目包不可用: {normalized_project_id or '未选择项目'}",
            ) from exc

        normalized_api_id = self._safe_asset_id(api_id, "api_id")
        normalized_case_id = self._safe_asset_id(case_id, "case_id")
        normalized_flow = self._safe_asset_id(flow_id or flow, "flow_id")
        if run_type == "single":
            if normalized_flow is not None:
                raise SubmissionError(400, INVALID_PARAMS, "run_type=single 时不得指定 flow_id")
            if normalized_api_id is None or normalized_case_id is None:
                raise SubmissionError(400, INVALID_PARAMS, "run_type=single 时 api_id/case_id 必填")
            self._validate_single_selection(package, normalized_api_id, normalized_case_id)
        elif run_type == "flow":
            if normalized_api_id is not None or normalized_case_id is not None:
                raise SubmissionError(400, INVALID_PARAMS, "run_type=flow 时不得指定 api_id/case_id")
            if normalized_flow is None:
                raise SubmissionError(400, INVALID_PARAMS, "run_type=flow 时 flow_id 必填")
            if not (package.flows_dir / f"{normalized_flow}.yaml").is_file():
                raise SubmissionError(400, INVALID_PARAMS, f"flow_id 不存在: {normalized_flow}")
        elif any(value is not None for value in (normalized_api_id, normalized_case_id, normalized_flow)):
            raise SubmissionError(400, INVALID_PARAMS, "run_type=all 时不得指定单个资产")

        platform_mode = self._runtime_plan_provider is not None or self._runtime_snapshot_provider is not None
        return {
            "legacy_mode": False,
            "project_id": package.project_id,
            "target_env": self._target_env,
            "config_source": "platform" if platform_mode else "local",
            "env": None,
            "run_type": run_type,
            "api_id": normalized_api_id,
            "case_id": normalized_case_id,
            "flow_id": normalized_flow,
            # ``flow`` 暂时保留给旧测试和现有日志代码；V2 持久化以 flow_id 为准。
            "flow": normalized_flow,
            "tag": tag,
        }

    @staticmethod
    def _safe_asset_id(value: str | None, field: str) -> str | None:
        """校验资产 ID 为单一路径段，阻止提交参数参与目录穿越。"""

        normalized = (value or "").strip() or None
        if normalized is None:
            return None
        if Path(normalized).name != normalized or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]{0,127}", normalized
        ):
            raise SubmissionError(400, INVALID_PARAMS, f"{field} 不合法: {normalized!r}")
        return normalized

    @staticmethod
    def _validate_single_selection(
        package: ProjectPackage,
        api_id: str,
        case_id: str,
    ) -> None:
        """确认 Case 确实属于当前项目和 API，拒绝跨项目/跨 API 同名引用。"""

        api_path = package.apis_dir / f"{api_id}.yaml"
        case_path = package.cases_dir / f"{api_id}.yaml"
        if not api_path.is_file() or not case_path.is_file():
            raise SubmissionError(400, INVALID_PARAMS, f"API/Case 不存在: {api_id}::{case_id}")
        try:
            collection = load_yaml(case_path)
        except ConfigError as exc:
            raise SubmissionError(400, INVALID_PARAMS, f"Case 配置不可用: {api_id}") from exc
        if collection.get("api") != api_id:
            raise SubmissionError(400, INVALID_PARAMS, f"Case 不属于 API: {api_id}")
        cases = collection.get("cases")
        if not isinstance(cases, list) or not any(
            isinstance(item, dict) and item.get("id") == case_id for item in cases
        ):
            raise SubmissionError(400, INVALID_PARAMS, f"case_id 不存在: {case_id}")

    def _precheck_credentials(
        self,
        task_input: dict[str, Any],
        signed_user_context: str,
    ) -> None:
        """配置合并级与任务级凭证预检。

        功能说明:
            平台模式下本地 .env 不参与凭证合并，任务级 Admin 校验改以
            平台 Secret 管理已配置的键名清单为准（只读键名，不取值）。

        异常说明:
            SubmissionError: 400 + CREDENTIAL_FILE_INVALID/CREDENTIALS_MISSING/
            ADMIN_CREDENTIALS_MISSING；Admin 缺失时消息只列字段名不含值。
            平台清单不可读时抛 503 + PLATFORM_CONFIG_UNAVAILABLE。
        """
        # V2 平台任务的 Release/Profile 预检由 runtime-contexts 完成；这里
        # 再读根 .env 会把 Dating 错误绑定到 Truthy Admin 凭证，正是本次
        # 多项目改造要消除的串用。旧 local 兼容入口仍保留原检查。
        if task_input.get("config_source") == "platform":
            return

        settings, error_code, message = credentials.check_base_config(
            task_input["env"], self._project_root
        )
        if error_code is not None:
            raise SubmissionError(400, error_code, message)
        assert settings is not None

        if credentials.target_requires_admin(
            self._project_root,
            task_input["run_type"],
            task_input.get("flow_id") or task_input.get("flow"),
            task_input["tag"],
        ):
            if self._platform_secret_keys_provider is not None:
                secret_keys = self._platform_secret_keys_provider(signed_user_context)
                if secret_keys is None:
                    raise SubmissionError(
                        503,
                        PLATFORM_CONFIG_UNAVAILABLE,
                        "平台运行配置暂时不可用，无法校验 Secret 配置",
                    )
                missing = credentials.missing_admin_keys(
                    settings, platform_secret_keys=secret_keys
                )
            else:
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
        env: str | None = None,
        run_type: str = "",
        flow: str | None = None,
        tag: str | None = None,
        signed_user_context: str = "",
        *,
        project_id: str | None = None,
        api_id: str | None = None,
        case_id: str | None = None,
        flow_id: str | None = None,
        retry_of: str | None = None,
    ) -> dict[str, Any]:
        """提交一个新任务；校验失败或槽位被占用时抛出 SubmissionError。

        返回值:
            落盘后的任务记录（status 为 pending 或 running）。
        """
        task_input = self._validate_input(
            env,
            run_type,
            flow,
            tag,
            project_id=project_id,
            api_id=api_id,
            case_id=case_id,
            flow_id=flow_id,
        )
        self._precheck_credentials(task_input, signed_user_context)

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
            runtime_context = self._plan_runtime(
                task_id,
                signed_user_context,
                task_input,
            )
            # runtime_plan_provider 仅由平台 client 注入；这里不读取请求 payload
            # 中的 owner/project。root task 的快照一经落盘便不可被重试、报告或
            # 前端参数改写，派生产物一律通过 task_id 回溯到这一条记录。
            resource_snapshot = None
            if isinstance(runtime_context, dict):
                candidate_snapshot = runtime_context.get("resource_snapshot")
                if isinstance(candidate_snapshot, dict):
                    resource_snapshot = {
                        key: candidate_snapshot.get(key)
                        for key in (
                            "owner_user_id",
                            "access_scope_snapshot",
                            "project_id_snapshot",
                            "authorization_source_snapshot",
                        )
                    }
            try:
                package = self._registry.get(task_input["project_id"])
                display_name = package.display_name
            except ProjectRegistryError:
                # 只有旧 Truthy 兼容骨架允许没有 projects/；生产 V2 路径已在
                # _validate_input 中 fail-closed。
                display_name = "Truthy（历史兼容）"

            runtime = {
                "platform_environment": self._platform_environment,
                "target_env": task_input["target_env"],
                "runtime_scope_id": None,
                "config_source": task_input["config_source"],
                "release_id": None,
                "release_version": None,
                "credential_profiles": [],
            }
            platform_project_id = None
            if isinstance(runtime_context, dict):
                platform_project_id = runtime_context.get("platform_project_id")
                runtime.update(
                    {
                        "platform_environment": runtime_context.get("platform_environment")
                        or runtime["platform_environment"],
                        "target_env": runtime_context.get("target_env") or runtime["target_env"],
                        "runtime_scope_id": runtime_context.get("runtime_scope_id"),
                        "config_source": runtime_context.get("config_source") or "platform",
                        "release_id": runtime_context.get("release_id"),
                        "release_version": runtime_context.get("release_version"),
                        "credential_profiles": runtime_context.get("credential_profiles") or [],
                    }
                )
            selection = {
                "run_type": task_input["run_type"],
                "api_id": task_input.get("api_id"),
                "case_id": task_input.get("case_id"),
                "flow_id": task_input.get("flow_id"),
                "tag": task_input.get("tag"),
            }
            record = {
                "schema_version": 2,
                "id": task_id,
                "status": "pending",
                "project": {
                    "platform_project_id": platform_project_id,
                    "project_id": task_input["project_id"],
                    "display_name": display_name,
                },
                "runtime": runtime,
                "selection": selection,
                "retry_of": retry_of,
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
                "junit_file": (
                    f"reports/junit-task-{task_id}.xml"
                    if task_input.get("legacy_mode")
                    else f"reports/junit/{task_input['project_id']}/{task_id}.xml"
                ),
                "log_file": None,
                "summary": {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "errors": 0,
                    "skipped": 0,
                },
                # 只允许规划提供器返回不透明 Context ID 与非敏感 selector；
                # signed_user_context 从不加入 record，也不会传给子进程。
                "runtime_context": runtime_context,
                "resource_root_id": task_id,
                "resource_snapshot": resource_snapshot,
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

    def _plan_runtime(
        self,
        task_id: str,
        signed_user_context: str,
        task_input: dict[str, Any],
    ) -> dict[str, Any] | None:
        """调用平台规划提供器，并兼容一次旧版两参数回调。

        参数个数通过签名判断，不能用 ``except TypeError`` 掩盖提供器内部的
        真实缺陷。新版第三参数是已通过本地资产归属校验的只读选择快照。
        """

        provider = self._runtime_plan_provider
        if provider is None:
            return None
        parameter_count = len(inspect.signature(provider).parameters)
        if parameter_count >= 3:
            result = provider(task_id, signed_user_context, dict(task_input))
        else:
            result = provider(task_id, signed_user_context)
        if not isinstance(result, dict):
            raise SubmissionError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台运行规划响应无效")
        if not task_input.get("legacy_mode"):
            expected_mapping = {
                "platform_environment": self._platform_environment,
                "target_env": self._target_env,
            }
            for key, expected in expected_mapping.items():
                if result.get(key) not in (None, expected):
                    raise SubmissionError(
                        409,
                        "RUNTIME_SCOPE_MISMATCH",
                        "平台运行 Scope 与当前实例固定环境不匹配",
                    )
            if not result.get("runtime_scope_id"):
                raise SubmissionError(409, "RUNTIME_SCOPE_NOT_FOUND", "当前项目未配置可用 Runtime Scope")
        return result

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
        args = [self._python, "-m", "pytest", *entries]
        if task_input.get("legacy_mode") or (
            task_input.get("env") and not task_input.get("project_id")
        ):
            args.append(f"--env={task_input['env']}")
            if task_input.get("flow"):
                args.append(f"--flow={task_input['flow']}")
        elif "project_id" in task_input:
            args.extend(
                [
                    f"--project={task_input['project_id']}",
                    f"--target-env={task_input['target_env']}",
                    f"--config-source={task_input['config_source']}",
                ]
            )
            if task_input.get("api_id"):
                args.append(f"--api={task_input['api_id']}")
            if task_input.get("case_id"):
                # Web/API 契约把 api_id 与 case_id 分开保存，CaseLoader 的
                # pytest 选择器则使用 ``ApiId::case_id``。只在进程边界组合，
                # 任务 V2 仍保留两个独立字段，便于筛选和历史展示。
                args.append(
                    f"--case={task_input['api_id']}::{task_input['case_id']}"
                )
            if task_input.get("flow_id"):
                args.append(f"--flow={task_input['flow_id']}")
            if task_input.get("task_id"):
                args.append(f"--task-id={task_input['task_id']}")
            if task_input.get("runtime_scope_id"):
                args.append(f"--runtime-scope-id={task_input['runtime_scope_id']}")
        else:
            # 旧单元测试直接调用 _build_command 时只有 env 字段，继续保留
            # 原命令契约；生产提交均经 _validate_input 补全模式标识。
            args.append(f"--env={task_input['env']}")
            if task_input.get("flow"):
                args.append(f"--flow={task_input['flow']}")
        if task_input.get("tag"):
            args.extend(["-m", task_input["tag"]])
        args.append(f"--junitxml={junit_path}")
        return args

    @staticmethod
    def _safe_process_environment(extra: Any) -> dict[str, str]:
        """构造平台任务的最小宿主环境，拒绝把配置/Secret 继承给 pytest。

        ``extra`` 只允许平台会话写回所需的服务身份定位字段；任何业务配置
        都必须在受控快照中出现。这样即使机器上遗留 Truthy Admin 环境变量，
        Dating 任务也不会读取它们。
        """

        inherited_allowlist = {
            "PATH",
            "PYTHONPATH",
            "VIRTUAL_ENV",
            "HOME",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "TZ",
            "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
        }
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in inherited_allowlist
        }
        allowed_extra = {
            "API_AUTOTEST_SESSION_PROVIDER",
            "PLATFORM_API_URL",
            "PLATFORM_CLIENT_TOKEN_FILE",
            "PLATFORM_RUNTIME_CONTEXT_ID",
            "PLATFORM_CREDENTIAL_ID",
            "PLATFORM_CREDENTIAL_VERSION",
        }
        if isinstance(extra, dict):
            environment.update(
                {
                    str(key): str(value)
                    for key, value in extra.items()
                    if key in allowed_extra and value not in (None, "")
                }
            )
        return environment

    @staticmethod
    def _settings_from_platform_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """把平台 materialize 响应转换为执行器唯一理解的 ``settings``。

        新平台可直接返回 ``settings``；兼容旧 ConfigDefinition 的扁平
        ``normal``/``secrets`` 时，只映射已知逻辑键并把其余 Secret 保存在
        任务内存快照的 ``runtime_variables``，绝不转成子进程环境变量。
        """

        direct = payload.get("settings")
        if isinstance(direct, dict):
            return json.loads(json.dumps(direct, ensure_ascii=False))
        normal = payload.get("normal") if isinstance(payload.get("normal"), dict) else {}
        secrets = payload.get("secrets") if isinstance(payload.get("secrets"), dict) else {}
        settings = json.loads(json.dumps(normal, ensure_ascii=False))
        gateway_value = settings.pop("GATEWAY_API_URL", None) or settings.get(
            "gateway.base_url"
        )
        if gateway_value and not settings.get("gateway_base_url"):
            settings["gateway_base_url"] = gateway_value
        comm = settings.setdefault("comm", {})
        if not isinstance(comm, dict):
            raise SubmissionError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台快照 comm 配置无效")
        secret_comm_mapping = {
            "AUTH_TOKEN": "auth_token",
            "ACCESS_TOKEN": "auth_token",
            "USER_ID": "user_id",
            "DEVICE_ID": "device_id",
        }
        for source_key, target_key in secret_comm_mapping.items():
            if secrets.get(source_key) not in (None, ""):
                comm[target_key] = secrets[source_key]
        variables = settings.setdefault("runtime_variables", {})
        if not isinstance(variables, dict):
            raise SubmissionError(
                503, PLATFORM_CONFIG_UNAVAILABLE, "平台快照 runtime_variables 配置无效"
            )
        variables.update(secrets)
        return settings

    def _snapshot_document(
        self,
        record: dict[str, Any],
        payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """组装带任务/Scope 不可变身份的 schema_version=1 运行快照。"""

        runtime = record["runtime"]
        project = record["project"]
        release_id = payload.get("release_id") or metadata.get("release_id") or runtime.get(
            "release_id"
        )
        if not runtime.get("runtime_scope_id") or not project.get("platform_project_id") or not release_id:
            raise SubmissionError(409, "RUNTIME_SNAPSHOT_INVALID", "平台运行快照缺少 Scope/Release 身份")
        return {
            "schema_version": 1,
            "task_id": record["id"],
            "runtime_scope_id": runtime["runtime_scope_id"],
            "platform_environment": runtime["platform_environment"],
            "tool_id": "api-autotest",
            "platform_project_id": project["platform_project_id"],
            "project_id": project["project_id"],
            "target_env": runtime["target_env"],
            "config_release_id": str(release_id),
            "config_release_version": payload.get("release_version")
            or metadata.get("release_version")
            or runtime.get("release_version"),
            "credential_profiles": payload.get("credential_profiles")
            or metadata.get("credential_profiles")
            or runtime.get("credential_profiles")
            or [],
            "snapshot_time": _now_iso(),
            "settings": self._settings_from_platform_payload(payload),
        }

    @staticmethod
    def _apply_snapshot_metadata(
        record: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        """只把非敏感快照版本元数据写入 Task V2。"""

        runtime = record.setdefault("runtime", {})
        mapping = {
            "runtime_scope_id": "runtime_scope_id",
            "release_id": "release_id",
            "release_version": "release_version",
            "credential_profiles": "credential_profiles",
        }
        for source, target in mapping.items():
            if metadata.get(source) is not None:
                runtime[target] = metadata[source]

    def _start(self, task_id: str) -> None:
        """启动子进程并派生等待线程。"""
        record = self._store.load(task_id)
        assert record is not None

        project_id = str(record.get("project", {}).get("project_id") or "truthy")
        legacy_mode = bool(record.get("input", {}).get("legacy_mode"))
        console_directory = self._store.console_dir(
            task_id,
            None if legacy_mode else project_id,
        )
        console_directory.mkdir(parents=True, exist_ok=True)
        console_path = self._store.console_log_path(
            task_id,
            None if legacy_mode else project_id,
        )
        junit_path = self._project_root / record["junit_file"]
        junit_path.parent.mkdir(parents=True, exist_ok=True)

        execution_input = dict(record["input"])
        execution_input["task_id"] = task_id
        execution_input["runtime_scope_id"] = record.get("runtime", {}).get(
            "runtime_scope_id"
        )
        args = self._build_command(execution_input, junit_path)
        task_environment = os.environ.copy()
        if self._runtime_snapshot_provider is not None:
            payload, snapshot_metadata = self._runtime_snapshot_provider(record)
            if not isinstance(payload, dict) or not isinstance(snapshot_metadata, dict):
                raise SubmissionError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台运行快照响应无效")
            self._apply_snapshot_metadata(record, snapshot_metadata)
            snapshot = self._snapshot_document(record, payload, snapshot_metadata)
            snapshot_path = create_runtime_snapshot_file(
                self._project_root / "runtime",
                project_id,
                task_id,
                snapshot,
            )
            self._snapshot_files[task_id] = snapshot_path
            # 平台模式采用最小进程环境白名单；Release/Secret 只存在于 0600
            # 文件中，宿主机同名变量即使被配置也不会覆盖任务快照。
            task_environment = self._safe_process_environment(
                snapshot_metadata.get("process_environment")
            )
            task_environment.update(
                {
                    "API_AUTOTEST_RUNTIME_SNAPSHOT_FILE": str(snapshot_path),
                    "API_AUTOTEST_CONFIG_SOURCE": "platform",
                    "API_AUTOTEST_PROJECT_ID": project_id,
                    "API_AUTOTEST_TARGET_ENV": str(record["runtime"]["target_env"]),
                    "API_AUTOTEST_TASK_ID": task_id,
                    "API_AUTOTEST_RUNTIME_SCOPE_ID": str(
                        record["runtime"].get("runtime_scope_id") or ""
                    ),
                }
            )
            self._store.save(record)
        elif self._runtime_environment_provider is not None:
            # 旧接入测试仍可注入环境映射；生产平台模式不再走该分支。
            runtime_values, snapshot_metadata = self._runtime_environment_provider(record)
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
            self._delete_snapshot(task_id)

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

    def retry(
        self,
        task_id: str,
        *,
        signed_user_context: str = "",
    ) -> dict[str, Any]:
        """基于旧任务的资产选择创建一个全新任务和全新平台快照。

        旧记录仅作为不可变选择来源；Runtime Scope、Release 与 Profile 必须
        重新由平台规划，绝不复用旧任务的 ``runtime_context`` 或 Secret。
        """

        original = self._store.load(task_id)
        if original is None:
            raise SubmissionError(404, TASK_NOT_FOUND, f"任务不存在: {task_id}")
        if original.get("status") not in TERMINAL_STATUSES:
            raise SubmissionError(409, "TASK_NOT_TERMINATED", "仅终态任务可以重试")
        selection = original.get("selection")
        if not isinstance(selection, dict):
            old_input = original.get("input") if isinstance(original.get("input"), dict) else {}
            selection = {
                "run_type": old_input.get("run_type"),
                "api_id": old_input.get("api_id"),
                "case_id": old_input.get("case_id"),
                "flow_id": old_input.get("flow_id") or old_input.get("flow"),
                "tag": old_input.get("tag"),
            }
        project = original.get("project") if isinstance(original.get("project"), dict) else {}
        project_id = project.get("project_id") or "truthy"
        return self.submit(
            project_id=str(project_id),
            run_type=str(selection.get("run_type") or ""),
            api_id=selection.get("api_id"),
            case_id=selection.get("case_id"),
            flow_id=selection.get("flow_id"),
            tag=selection.get("tag"),
            signed_user_context=signed_user_context,
            retry_of=task_id,
        )

    def _associate_log_file(
        self,
        record: dict[str, Any],
        finished_at: str,
    ) -> str | None:
        """按子进程 PID 关联框架脱敏日志文件。

        功能说明:
            框架日志命名为 ``logs/YYYY-MM-DD/{时间戳}_{env}_{pid}.log``；
            在任务起止日期覆盖的日期目录中按 PID 后缀匹配。
        """
        project_id = str(record.get("project", {}).get("project_id") or "truthy")
        target_env = str(record.get("runtime", {}).get("target_env") or "test")
        task_id = str(record.get("id") or "")
        scoped_directory = self._project_root / "logs" / project_id / target_env / task_id
        if scoped_directory.is_dir():
            for path in sorted(scoped_directory.rglob("*.log")):
                return path.relative_to(self._project_root).as_posix()

        pid = record.get("pid")
        if not pid:
            return None
        logs_root = self._project_root / "logs"
        try:
            start_date = datetime.fromisoformat(record.get("started_at")).date()
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
        record = self._store.load(task_id) or {}
        project_id = str(record.get("project", {}).get("project_id") or "truthy")
        legacy_mode = bool(record.get("input", {}).get("legacy_mode"))
        console_path = self._store.console_log_path(
            task_id,
            None if legacy_mode else project_id,
        )
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
            record["log_file"] = self._associate_log_file(record, finished_at)

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
        self._delete_snapshot(task_id)

    def _delete_snapshot(self, task_id: str) -> None:
        """精准删除当前任务专属快照；不会递归清理项目运行目录。"""

        snapshot_path = self._snapshot_files.pop(task_id, None)
        if snapshot_path is not None:
            delete_runtime_snapshot_file(snapshot_path)

    def _delete_recovered_snapshot(self, record: dict[str, Any]) -> None:
        """删除服务重启前遗留的 V2 平台快照。

        重启后内存 ``_snapshot_files`` 已丢失，因此必须从已落盘的不可变任务
        身份重建唯一文件路径。任务 ID、项目 ID 和解析后的父目录均要校验；
        任何异常记录都选择保留而不是扩大删除范围。只删除 snapshot.json，
        同目录 console.log 等审计产物继续保留。
        """
        task_id = str(record.get("id") or "")
        project = record.get("project")
        project_id = (
            str(project.get("project_id") or "")
            if isinstance(project, dict)
            else ""
        )
        if not is_valid_task_id(task_id) or not re.fullmatch(
            r"[a-z][a-z0-9-]{1,31}", project_id
        ):
            return
        runtime_root = (self._project_root / "runtime").resolve()
        snapshot_path = self._project_root / "runtime" / project_id / task_id / "snapshot.json"
        try:
            snapshot_path.resolve(strict=False).relative_to(runtime_root)
        except (OSError, ValueError):
            return
        delete_runtime_snapshot_file(snapshot_path)

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
                    # 先删除包含 Secret 的受控快照，再持久化失败终态。即使后续
                    # 任务 JSON 写入失败，也不会让明文配置继续滞留在磁盘。
                    self._delete_recovered_snapshot(record)
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
