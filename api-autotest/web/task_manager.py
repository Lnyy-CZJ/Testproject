"""持久任务队列与隔离执行引擎。

功能说明:
    以子进程 ``python -m pytest`` 驱动既有框架入口（对齐 Jenkinsfile
    语义），提供提交、FIFO 排队、等待、取消、超时与启动恢复能力。默认
    并发数仍为 1；启用更高并发时，相同 Credential 隔离键的任务仍串行。
    调度、取消请求与终态提交使用同一状态锁；任务终态不可再次迁移。
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
from typing import Any, Callable, Iterable

from web import credentials
from web.junit_report import parse_junit_file
from web.redaction import FAILED_MESSAGE_LIMIT, truncate_tail
from web.task_store import (
    TaskInputError,
    TaskStore,
    is_valid_task_id,
    new_task_id,
)
from utils.custom.config_loader import (
    ConfigError,
    create_runtime_snapshot_file,
    delete_runtime_snapshot_file,
    load_yaml,
)
from utils.custom.api_loader import ApiConfigError, load_api_definitions
from utils.custom.case_loader import CaseConfigError, load_single_cases
from utils.custom.flow_loader import FlowConfigError, load_flow_cases
from utils.custom.project_registry import (
    ProjectNotFoundError,
    ProjectPackage,
    ProjectRegistry,
    ProjectRegistryError,
)
from utils.custom.runtime_overrides import (
    RuntimeOverrideError,
    apply_runtime_overrides,
    build_case_asset_snapshot,
    build_flow_asset_snapshot,
    canonical_sha256,
    public_asset_contract,
    validate_retry_runtime_input_schema,
)

# 支持的运行类型；``batch`` 是一个 pytest 进程内执行多个同类资产。
RUN_TYPES = ("all", "single", "flow", "batch")

# 入口文件：对齐 Jenkins（直接 pytest 指定入口，而非 runtest.py）。
ENTRY_SINGLE = "test_cases/test_single_api.py"
ENTRY_FLOW = "test_cases/test_gateway_flow.py"

# tag 白名单：字母/数字/下划线/空格/括号；壳服务不解释 -m 表达式。
TAG_PATTERN = re.compile(r"^[A-Za-z0-9_()\s]+$")
TAG_MAX_LENGTH = 200

# 稳定错误码。
SLOT_BUSY = "SLOT_BUSY"
QUEUE_FULL = "QUEUE_FULL"
BATCH_SELECTION_REQUIRED = "BATCH_SELECTION_REQUIRED"
BATCH_SELECTION_INVALID = "BATCH_SELECTION_INVALID"
BATCH_MIXED_TYPE = "BATCH_MIXED_TYPE"
BATCH_TOO_LARGE = "BATCH_TOO_LARGE"
BATCH_UNSAFE_CONFIRMATION_REQUIRED = "BATCH_UNSAFE_CONFIRMATION_REQUIRED"
BATCH_INPUT_CONTRACT_CONFLICT = "BATCH_INPUT_CONTRACT_CONFLICT"
BATCH_RESULT_INCOMPLETE = "BATCH_RESULT_INCOMPLETE"
TAG_FILTER_NOT_ALLOWED = "TAG_FILTER_NOT_ALLOWED"
INVALID_PARAMS = "INVALID_PARAMS"
TASK_NOT_FOUND = "TASK_NOT_FOUND"
TASK_TERMINATED = "TASK_TERMINATED"
TASK_TIMEOUT = "TASK_TIMEOUT"
ALL_TESTS_SKIPPED = "ALL_TESTS_SKIPPED"
PLATFORM_CONFIG_UNAVAILABLE = "PLATFORM_CONFIG_UNAVAILABLE"
PROJECT_PACKAGE_NOT_FOUND = "PROJECT_PACKAGE_NOT_FOUND"
TASK_INPUTS_MISSING = "TASK_INPUTS_MISSING"

# 终态集合：进入后不可再次迁移。
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")

# pytest 退出码语义。
EXIT_NO_TESTS_COLLECTED = 5


class SubmissionError(Exception):
    """任务提交/取消被拒绝时携带 HTTP 状态码与稳定错误码。"""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        *,
        details: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        # 字段级错误只包含逻辑键和用户可读消息；内部 target 永不进入 Web。
        self.details = list(details or [])


class _TaskCancelledBeforeStart(RuntimeError):
    """内部控制流：任务在物化期间被取消，不应再改写为启动失败。"""


def _now_iso() -> str:
    """返回带时区的本地当前时间 ISO 字符串。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class TaskManager:
    """持久 FIFO 执行引擎：默认串行，可按 Credential 隔离安全并发。

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
        max_pending_tasks: int = 20,
        max_concurrency: int = 1,
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
        self._max_pending_tasks = int(max_pending_tasks)
        self._max_concurrency = int(max_concurrency)
        if self._max_pending_tasks < 1:
            raise ValueError("max_pending_tasks 必须为正整数")
        if self._max_concurrency < 1:
            raise ValueError("max_concurrency 必须为正整数")
        self._registry = ProjectRegistry(self._project_root / "projects")
        # 调度器会在终态提交后继续选择下一任务，RLock 允许内部辅助函数复用
        # 同一把状态锁而不会因嵌套调用自锁。
        self._lock = threading.RLock()
        self._active_id: str | None = None
        self._active_ids: set[str] = set()
        self._active_isolation_keys: dict[str, frozenset[str]] = {}
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancel_requested: set[str] = set()
        self._snapshot_files: dict[str, Path] = {}
        existing_sequences = [
            int(record["queue"].get("sequence") or 0)
            for record in self._store.list()
            if isinstance(record.get("queue"), dict)
        ]
        self._next_queue_sequence = max(existing_sequences, default=0) + 1

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
            if run_type == "batch":
                raise SubmissionError(
                    400,
                    BATCH_SELECTION_INVALID,
                    "历史 env 兼容入口不支持批次任务",
                )
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
        if tag is not None and run_type in {"single", "flow"}:
            # 精确资产选择已经唯一定位 pytest 参数；再应用 marker 会造成
            # “提交成功但 0 条收集”的假执行，因此 V3 契约直接拒绝。
            raise SubmissionError(
                400,
                TAG_FILTER_NOT_ALLOWED,
                "单接口或单 Flow 任务不能再使用 tag 过滤",
            )
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
        elif run_type == "batch":
            if any(
                value is not None
                for value in (normalized_api_id, normalized_case_id, normalized_flow)
            ):
                raise SubmissionError(
                    400,
                    BATCH_SELECTION_INVALID,
                    "批次任务必须通过 items 选择资产",
                )
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

    def _build_selected_asset_snapshot(
        self,
        task_input: dict[str, Any],
    ) -> dict[str, Any] | None:
        """根据已验证的项目与逻辑 ID 加载唯一 Case/Flow 基础快照。

        ``run_type=all`` 和历史单项目兼容入口没有唯一资产，因此返回 None。
        路径和 YAML 均由现有 Registry/Loader 解析，浏览器无法提供目标路径。
        """

        if task_input.get("legacy_mode") or task_input.get("run_type") == "all":
            return None
        try:
            package = self._registry.get(str(task_input["project_id"]))
            definitions = load_api_definitions(package.root)
            if task_input.get("run_type") == "single":
                full_case_id = (
                    f"{task_input['api_id']}::{task_input['case_id']}"
                )
                single_case = load_single_cases(
                    package.root,
                    (full_case_id,),
                )[0]
                return build_case_asset_snapshot(
                    package.project_id,
                    single_case,
                    definitions,
                )
            flow_case = load_flow_cases(
                package.root,
                str(task_input["flow_id"]),
            )[0]
            return build_flow_asset_snapshot(
                package.project_id,
                flow_case,
                definitions,
            )
        except (
            ApiConfigError,
            CaseConfigError,
            FlowConfigError,
            ProjectRegistryError,
            IndexError,
            KeyError,
            RuntimeOverrideError,
        ) as exc:
            message = exc.message if isinstance(exc, RuntimeOverrideError) else str(exc)
            raise SubmissionError(
                400,
                INVALID_PARAMS,
                f"所选测试资产不可用: {message}",
            ) from exc

    @staticmethod
    def _raise_runtime_override_error(error: RuntimeOverrideError) -> None:
        """把共享领域异常映射为现有 TaskManager HTTP 异常。"""

        raise SubmissionError(
            error.status_code,
            error.error_code,
            error.message,
            details=error.field_errors,
        ) from error

    def _resolve_asset_snapshot(
        self,
        task_input: dict[str, Any],
        *,
        runtime_overrides: Any,
        asset_revision: str | None,
        require_revision: bool,
        schema_change_error: bool = False,
        previous_definitions: Any = None,
    ) -> dict[str, Any] | None:
        """构建基础资产并在深拷贝上应用本次覆盖。"""

        has_overrides = runtime_overrides not in (None, {})
        if task_input.get("run_type") == "all" or task_input.get("legacy_mode"):
            if has_overrides:
                raise SubmissionError(
                    400,
                    "RUNTIME_OVERRIDE_NOT_SUPPORTED",
                    "批量任务或历史兼容入口不支持本次运行参数修改",
                )
            return None
        snapshot = self._build_selected_asset_snapshot(task_input)
        assert snapshot is not None
        try:
            if schema_change_error:
                validate_retry_runtime_input_schema(
                    previous_definitions,
                    snapshot.get("runtime_input_definitions"),
                    runtime_overrides,
                )
            return apply_runtime_overrides(
                snapshot,
                runtime_overrides,
                expected_revision=asset_revision,
                require_revision=require_revision,
                schema_change_error=schema_change_error,
            )
        except RuntimeOverrideError as exc:
            self._raise_runtime_override_error(exc)

    @staticmethod
    def _batch_snapshot_tags(snapshot: dict[str, Any]) -> list[str]:
        """读取已经过 Loader 校验的 Case/Flow 标签，保持 YAML 声明顺序。"""

        resolved = snapshot.get("resolved_execution_asset")
        resolved = resolved if isinstance(resolved, dict) else {}
        asset_key = "single_case" if snapshot.get("asset_type") == "case" else "flow_case"
        asset = resolved.get(asset_key)
        asset = asset if isinstance(asset, dict) else {}
        tags = asset.get("tags")
        return [str(item) for item in tags] if isinstance(tags, list) else []

    @staticmethod
    def _batch_file_contract(snapshot: dict[str, Any]) -> dict[str, Any] | None:
        """返回 Flow 的文件输入契约；Case 与无文件 Flow 返回 None。"""

        if snapshot.get("asset_type") != "flow":
            return None
        resolved = snapshot.get("resolved_execution_asset")
        resolved = resolved if isinstance(resolved, dict) else {}
        flow_case = resolved.get("flow_case")
        flow_case = flow_case if isinstance(flow_case, dict) else {}
        flow = flow_case.get("flow")
        flow = flow if isinstance(flow, dict) else {}
        inputs = flow.get("inputs")
        inputs = inputs if isinstance(inputs, dict) else {}
        media_files = inputs.get("media_files")
        return dict(media_files) if isinstance(media_files, dict) else None

    @staticmethod
    def _batch_file_execution_contract(contract: dict[str, Any]) -> dict[str, Any]:
        """提取决定附件能否共享的文件执行约束。

        ``label`` 与 ``description`` 只用于当前 Flow 的页面展示；Analysis 与
        Reply 可以使用不同文案，但只要数量、MIME 和大小等执行约束一致，
        就应允许同一组有序图片分别提供给两个 Flow。MIME 列表顺序同样不
        改变约束语义，因此排序后再参与稳定摘要。
        """

        execution_contract = {
            key: contract.get(key)
            for key in (
                "type",
                "required",
                "min_items",
                "max_items",
                "allowed_content_types",
                "max_size_bytes",
            )
        }
        content_types = execution_contract.get("allowed_content_types")
        if isinstance(content_types, list):
            execution_contract["allowed_content_types"] = sorted(
                str(item) for item in content_types
            )
        return execution_contract

    def _batch_candidate_snapshots(
        self,
        project_id: str,
        batch_type: str,
    ) -> list[dict[str, Any]]:
        """按 Catalog/Loader 的稳定顺序加载某项目全部同类资产快照。"""

        package = self._registry.get(project_id)
        definitions = load_api_definitions(package.root)
        if batch_type == "cases":
            return [
                build_case_asset_snapshot(project_id, case, definitions)
                for case in load_single_cases(package.root)
            ]
        return [
            build_flow_asset_snapshot(project_id, flow, definitions)
            for flow in load_flow_cases(package.root)
        ]

    def _resolve_batch_snapshot(
        self,
        task_input: dict[str, Any],
        *,
        batch_type: str | None,
        selection_mode: str | None,
        batch_items: Any,
        tag_filters: Any,
        risk_acknowledgements: Any,
        has_uploads: bool,
        runtime_overrides: Any,
        enforce_upload_presence: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """解析批次选择并固化一个任务级不可变执行清单。

        浏览器只提交逻辑 ``asset_id + asset_revision``；所有执行对象重新从
        当前项目 Loader 构建。这样批次开始后即使 YAML 被修改，pytest 也
        只能读取该任务的 0600 快照，不能回退扫描当前目录。
        """

        if runtime_overrides not in (None, {}):
            raise SubmissionError(
                400,
                "RUNTIME_OVERRIDE_NOT_SUPPORTED",
                "批量回归使用 YAML 默认参数，不支持本次运行参数修改",
            )
        normalized_type = str(batch_type or "").strip()
        if normalized_type not in {"cases", "flows"}:
            raise SubmissionError(
                400,
                BATCH_MIXED_TYPE,
                "batch_type 只能是 cases 或 flows",
            )
        normalized_mode = str(selection_mode or "selected").strip()
        if normalized_mode not in {"selected", "all_safe"}:
            raise SubmissionError(
                400,
                BATCH_SELECTION_INVALID,
                "selection_mode 只能是 selected 或 all_safe",
            )

        if tag_filters is not None and not isinstance(tag_filters, list):
            raise SubmissionError(
                400, BATCH_SELECTION_INVALID, "tag_filters 必须是数组"
            )
        if risk_acknowledgements is not None and not isinstance(
            risk_acknowledgements, list
        ):
            raise SubmissionError(
                400,
                BATCH_SELECTION_INVALID,
                "risk_acknowledgements 必须是数组",
            )
        raw_filters = tag_filters if isinstance(tag_filters, list) else []
        filters = [str(item).strip() for item in raw_filters if str(item).strip()]
        if len(filters) != len(set(filters)):
            filters = list(dict.fromkeys(filters))
        acknowledgements = {
            str(item).strip()
            for item in (
                risk_acknowledgements
                if isinstance(risk_acknowledgements, list)
                else []
            )
            if str(item).strip()
        }

        try:
            candidates = self._batch_candidate_snapshots(
                str(task_input["project_id"]), normalized_type
            )
        except (
            ApiConfigError,
            CaseConfigError,
            FlowConfigError,
            ProjectRegistryError,
            RuntimeOverrideError,
        ) as exc:
            raise SubmissionError(
                400,
                BATCH_SELECTION_INVALID,
                f"批次资产不可用: {exc}",
            ) from exc
        by_id = {str(item.get("asset_id")): item for item in candidates}

        excluded: list[dict[str, Any]] = []
        if normalized_mode == "selected":
            if not isinstance(batch_items, list) or not batch_items:
                raise SubmissionError(
                    400,
                    BATCH_SELECTION_REQUIRED,
                    "请至少选择一条 Case 或 Flow",
                )
            if len(batch_items) > 200:
                raise SubmissionError(
                    400, BATCH_TOO_LARGE, "单批次最多选择 200 条"
                )
            selected: list[dict[str, Any]] = []
            seen: set[str] = set()
            for raw_item in batch_items:
                if not isinstance(raw_item, dict):
                    raise SubmissionError(
                        400, BATCH_SELECTION_INVALID, "批次条目格式无效"
                    )
                unexpected_fields = set(raw_item) - {
                    "asset_id",
                    "asset_revision",
                }
                if unexpected_fields:
                    raise SubmissionError(
                        400,
                        BATCH_SELECTION_INVALID,
                        "批次条目包含未知字段: "
                        + ", ".join(sorted(unexpected_fields)),
                    )
                asset_id = str(raw_item.get("asset_id") or "").strip()
                expected_revision = str(raw_item.get("asset_revision") or "").strip()
                if not asset_id or asset_id in seen or asset_id not in by_id:
                    raise SubmissionError(
                        400,
                        BATCH_SELECTION_INVALID,
                        f"批次资产不存在或重复: {asset_id or '未提供'}",
                    )
                snapshot = by_id[asset_id]
                if expected_revision != snapshot.get("asset_revision"):
                    raise SubmissionError(
                        409,
                        "RUNTIME_OVERRIDE_SCHEMA_CHANGED",
                        f"资产已更新，请刷新后重新选择: {asset_id}",
                    )
                selected.append(snapshot)
                seen.add(asset_id)
        else:
            if batch_items not in (None, []):
                raise SubmissionError(
                    400,
                    BATCH_SELECTION_INVALID,
                    "all_safe 由服务端解析，items 必须为空",
                )
            selected = []
            for snapshot in candidates:
                tags = set(self._batch_snapshot_tags(snapshot))
                contract = self._batch_file_contract(snapshot)
                if tags & {"explicit", "destructive", "interactive"}:
                    excluded.append(
                        {
                            "asset_id": snapshot.get("asset_id"),
                            "reason": "风险标签不属于自动安全范围",
                        }
                    )
                    continue
                if contract and bool(contract.get("required")):
                    excluded.append(
                        {
                            "asset_id": snapshot.get("asset_id"),
                            "reason": "需要文件输入",
                        }
                    )
                    continue
                selected.append(snapshot)

        # 多标签筛选使用 AND；顺序仍取 Loader 的稳定 Catalog 顺序。
        if filters:
            filtered: list[dict[str, Any]] = []
            for snapshot in selected:
                if set(filters).issubset(
                    set(self._batch_snapshot_tags(snapshot))
                ):
                    filtered.append(snapshot)
                else:
                    excluded.append(
                        {
                            "asset_id": snapshot.get("asset_id"),
                            "reason": "不满足全部标签筛选条件",
                        }
                    )
            selected = filtered
        candidate_order = {
            str(snapshot.get("asset_id")): index
            for index, snapshot in enumerate(candidates)
        }
        selected.sort(
            key=lambda snapshot: candidate_order[str(snapshot.get("asset_id"))]
        )
        if not selected:
            raise SubmissionError(
                400,
                BATCH_SELECTION_REQUIRED,
                "当前选择与筛选条件下没有可执行资产",
            )
        if len(selected) > 200:
            raise SubmissionError(400, BATCH_TOO_LARGE, "单批次最多选择 200 条")

        required_ack: set[str] = set()
        file_contracts: list[dict[str, Any]] = []
        for snapshot in selected:
            tags = set(self._batch_snapshot_tags(snapshot))
            required_ack.update(tags & {"explicit", "destructive"})
            contract = self._batch_file_contract(snapshot)
            if contract and bool(contract.get("required")):
                file_contracts.append(contract)
        missing_ack = sorted(required_ack - acknowledgements)
        if missing_ack:
            raise SubmissionError(
                400,
                BATCH_UNSAFE_CONFIRMATION_REQUIRED,
                "以下风险标签需要确认: " + ", ".join(missing_ack),
            )
        input_contract: dict[str, Any] | None = None
        if file_contracts:
            normalized_contracts = {
                canonical_sha256(self._batch_file_execution_contract(contract))
                for contract in file_contracts
            }
            if len(normalized_contracts) > 1:
                raise SubmissionError(
                    400,
                    BATCH_INPUT_CONTRACT_CONFLICT,
                    "所选 Flow 的图片输入契约不兼容",
                )
            # Catalog 顺序已经固化；兼容契约的执行约束相同，返回第一条的
            # 公开展示文案即可。复制列表，避免调用方意外修改 Loader 结果。
            input_contract = dict(file_contracts[0])
            allowed_types = input_contract.get("allowed_content_types")
            if isinstance(allowed_types, list):
                input_contract["allowed_content_types"] = list(allowed_types)
        # 先确认多 Flow 的执行契约彼此兼容，再检查是否已上传文件。否则 Web
        # 会因契约冲突隐藏上传区，却只能收到“缺少图片”，用户无法修正选择。
        if file_contracts and not has_uploads and enforce_upload_presence:
            raise SubmissionError(
                400,
                "TASK_INPUT_COUNT_INVALID",
                "所选 Flow 需要上传符合契约的图片",
            )

        project_id = str(task_input["project_id"])
        resolved_items: list[dict[str, Any]] = []
        public_items: list[dict[str, Any]] = []
        for snapshot in selected:
            asset_id = str(snapshot["asset_id"])
            tags = self._batch_snapshot_tags(snapshot)
            risk_tags = [
                item
                for item in tags
                if item in {"explicit", "destructive", "interactive"}
            ]
            resolved_items.append(
                {
                    "asset_type": snapshot["asset_type"],
                    "asset_id": asset_id,
                    "asset_revision": snapshot["asset_revision"],
                    "resolved_asset_revision": snapshot["resolved_asset_revision"],
                    "resolved_execution_asset": snapshot["resolved_execution_asset"],
                }
            )
            public_items.append(
                {
                    "asset_type": snapshot["asset_type"],
                    "asset_id": asset_id,
                    "asset_revision": snapshot["asset_revision"],
                    "pytest_id": f"{project_id}::{asset_id}",
                    "risk_tags": risk_tags,
                    "status": "pending",
                    "duration_ms": None,
                    "error_summary": None,
                }
            )

        revision_basis = {
            "project_id": project_id,
            "batch_type": normalized_type,
            "items": [
                {
                    "asset_id": item["asset_id"],
                    "asset_revision": item["asset_revision"],
                }
                for item in resolved_items
            ],
        }
        api_definitions: dict[str, Any] = {}
        for item in resolved_items:
            item_definitions = item["resolved_execution_asset"].get(
                "api_definitions", {}
            )
            for api_id, definition in item_definitions.items():
                previous = api_definitions.get(api_id)
                if previous is not None and canonical_sha256(
                    previous
                ) != canonical_sha256(definition):
                    # 每个资产只冻结自己引用的 API 子集，因此集合本来可以
                    # 不同；只有同一个 API ID 在两个条目里内容冲突才说明构建
                    # 期间发生 YAML 竞态，必须失败关闭。
                    raise SubmissionError(
                        409,
                        BATCH_SELECTION_INVALID,
                        f"批次 API {api_id} 在快照构建期间发生变化，请重新提交",
                    )
                api_definitions[api_id] = definition
        resolved_execution_asset = {
            "batch_type": normalized_type,
            "items": resolved_items,
            "api_definitions": api_definitions,
        }
        snapshot = {
            "schema_version": 1,
            "project_id": project_id,
            "asset_type": "batch",
            "asset_id": f"{normalized_type}:{len(resolved_items)}",
            "asset_revision": canonical_sha256(revision_basis),
            "runtime_input_schema_revision": canonical_sha256([]),
            "runtime_input_definitions": [],
            "runtime_inputs": {},
            "applied_overrides": [],
            "resolved_asset_revision": canonical_sha256(resolved_execution_asset),
            "resolved_execution_asset": resolved_execution_asset,
        }
        batch = {
            "type": normalized_type,
            "selection_mode": normalized_mode,
            "item_count": len(public_items),
            "resolved_count": len(public_items),
            "excluded": excluded,
            "tag_filters": filters,
            "risk_acknowledgements": sorted(acknowledgements),
            "input_contract": input_contract,
            "items": public_items,
        }
        return snapshot, batch

    def preview_asset(
        self,
        task_input: dict[str, Any],
        *,
        asset_revision: str | None = None,
        runtime_overrides: Any = None,
    ) -> dict[str, Any] | None:
        """返回 Preflight/Catalog 可公开的当前资产与覆盖差异。

        预览允许首次在尚未知版本时传入覆盖值；真正提交仍要求非空覆盖携带
        ``asset_revision``，从而锁定预览到提交之间的 YAML 竞态。
        """

        snapshot = self._resolve_asset_snapshot(
            task_input,
            runtime_overrides=runtime_overrides,
            asset_revision=asset_revision,
            require_revision=False,
        )
        return public_asset_contract(snapshot) if snapshot is not None else None

    def preview_batch(
        self,
        task_input: dict[str, Any],
        *,
        batch_type: str | None,
        selection_mode: str | None,
        batch_items: Any,
        tag_filters: Any,
        risk_acknowledgements: Any,
        has_uploads: bool,
    ) -> dict[str, Any]:
        """解析批次预检并仅返回可公开字段，不创建任务或 Runtime Context。"""

        snapshot, batch = self._resolve_batch_snapshot(
            task_input,
            batch_type=batch_type,
            selection_mode=selection_mode,
            batch_items=batch_items,
            tag_filters=tag_filters,
            risk_acknowledgements=risk_acknowledgements,
            has_uploads=has_uploads,
            runtime_overrides=None,
            # Preflight 需要在缺文件时仍返回解析后的条目与权威契约；真正提交
            # 继续走默认严格门禁，不能绕过必填附件。
            enforce_upload_presence=False,
        )
        return {
            "asset": public_asset_contract(snapshot),
            "batch": batch,
        }

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
        # 项目化任务的 Release/Profile 预检由 Runtime Context（生产）或
        # 项目自身执行链路（测试注入）完成；这里再读根 .env 会把 Dating
        # 错误绑定到 Truthy Admin 凭证。只有旧 env 兼容入口保留原检查。
        if not task_input.get("legacy_mode"):
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
        asset_revision: str | None = None,
        runtime_overrides: Any = None,
        retry_of: str | None = None,
        uploads: Iterable[Any] | None = None,
        batch_type: str | None = None,
        selection_mode: str | None = None,
        batch_items: Any = None,
        tag_filters: Any = None,
        risk_acknowledgements: Any = None,
        _retry_input_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """提交一个新任务；校验失败或持久队列已满时抛出 SubmissionError。

        参数说明:
            uploads: Web multipart 传入的有序图片流；普通 JSON 任务为 None。
            asset_revision/runtime_overrides: 浏览器提交的基础资产版本与逻辑
                字段值。目标路径由服务端 Loader 解析，不能从请求传入。
            _retry_input_record: 仅供 ``retry`` 内部复制旧任务输入，不接受
                HTTP 请求直接设置。它与 uploads 互斥。

        返回值:
            落盘后的任务记录（status 为 pending 或 running）。
        """
        if uploads is not None and _retry_input_record is not None:
            raise SubmissionError(
                400,
                INVALID_PARAMS,
                "新上传图片与重试任务输入不能同时提供",
            )
        upload_items = list(uploads) if uploads is not None else None
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
        previous_definitions = None
        if _retry_input_record is not None:
            previous_snapshot = _retry_input_record.get("asset_snapshot")
            if isinstance(previous_snapshot, dict):
                previous_definitions = previous_snapshot.get(
                    "runtime_input_definitions"
                )
        batch: dict[str, Any] | None = None
        if task_input["run_type"] == "batch":
            retry_attachments = (
                _retry_input_record.get("attachments")
                if isinstance(_retry_input_record, dict)
                else None
            )
            asset_snapshot, batch = self._resolve_batch_snapshot(
                task_input,
                batch_type=batch_type,
                selection_mode=selection_mode,
                batch_items=batch_items,
                tag_filters=tag_filters,
                risk_acknowledgements=risk_acknowledgements,
                # Retry 的附件稍后才由 clone_inputs 复制。这里把待克隆的
                # 元数据计入“已提供文件”，避免必填图片契约在完整性校验前
                # 被误判为空；源文件缺失/篡改仍由 clone_inputs fail-closed。
                has_uploads=bool(upload_items)
                or (isinstance(retry_attachments, list) and bool(retry_attachments)),
                runtime_overrides=runtime_overrides,
            )
            task_input.update(
                {
                    "batch_type": batch["type"],
                    "selection_mode": batch["selection_mode"],
                    # 平台规划只接收已由服务端解析过的逻辑资产，不接收浏览器
                    # 的内部路径或运行参数。
                    "batch_items": [
                        {
                            "asset_type": item["asset_type"],
                            "asset_id": item["asset_id"],
                        }
                        for item in batch["items"]
                    ],
                }
            )
        else:
            asset_snapshot = self._resolve_asset_snapshot(
                task_input,
                runtime_overrides=runtime_overrides,
                asset_revision=asset_revision,
                require_revision=(
                    runtime_overrides not in (None, {})
                    and _retry_input_record is None
                ),
                # Retry 不复用旧摘要；旧逻辑键与当前 YAML 不兼容时统一返回
                # schema changed，提示用户进入“修改参数后重试”。
                schema_change_error=_retry_input_record is not None,
                previous_definitions=previous_definitions,
            )
        self._precheck_credentials(task_input, signed_user_context)

        with self._lock:
            pending_count = sum(
                1
                for existing in self._store.list()
                if existing.get("status") == "pending"
            )
            if pending_count >= self._max_pending_tasks:
                raise SubmissionError(
                    429,
                    QUEUE_FULL,
                    f"执行队列已满（上限 {self._max_pending_tasks}）",
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

            attachments: list[dict[str, Any]] = []
            input_manifest_file: str | None = None
            try:
                staged = None
                if upload_items is not None:
                    staged = self._store.save_inputs(
                        task_id,
                        task_input["project_id"],
                        upload_items,
                    )
                elif _retry_input_record is not None:
                    staged = self._store.clone_inputs(
                        _retry_input_record,
                        task_id,
                        task_input["project_id"],
                    )
                if staged is not None:
                    attachments, input_manifest_file = staged
            except TaskInputError as exc:
                # 新上传属于 400 参数错误；重试源已损坏属于旧任务状态冲突。
                status_code = 409 if _retry_input_record is not None else 400
                raise SubmissionError(status_code, exc.error_code, exc.message) from exc

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
            if batch is not None:
                selection.update(
                    {
                        "batch_type": batch["type"],
                        "selection_mode": batch["selection_mode"],
                    }
                )
            record_input = dict(task_input)
            if asset_snapshot is not None:
                record_input["asset_revision"] = asset_snapshot["asset_revision"]
                record_input["runtime_overrides"] = {
                    str(item["key"]): item.get("override_value")
                    for item in asset_snapshot.get("applied_overrides", [])
                }
            record = {
                "schema_version": 3,
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
                "input": record_input,
                # Task JSON 是历史审计真相，保留内部定义和完整最终执行资产；
                # Web 公开响应会在 app 层移除这两个内部字段。
                "asset_snapshot": asset_snapshot,
                "queue": {
                    "sequence": self._next_queue_sequence,
                    "queued_at": _now_iso(),
                    "dispatched_at": None,
                },
                "batch": batch,
                "attachments": attachments,
                "input_manifest_file": input_manifest_file,
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
            try:
                self._store.save(record)
            except Exception:
                # 任务 JSON 未成功成为事实时，附件目录也不能留下无主数据。
                if input_manifest_file is not None:
                    self._store.cleanup_inputs(task_id, task_input["project_id"])
                raise
            self._next_queue_sequence += 1

        # 空闲时立即调度，繁忙时记录保持 pending 并由前一任务终态触发。
        # 当前任务若属于立即启动且 Popen 失败，保留原接口的同步异常语义。
        self._dispatch_pending(preferred_task_id=task_id, propagate_start_error=True)
        return self._store.load(task_id) or record

    @staticmethod
    def _task_isolation_keys(record: dict[str, Any]) -> frozenset[str]:
        """从冻结 selector 生成并发隔离键。

        相同 Scope 下引用同一 Credential ID 的任务必须串行。没有个人凭证的
        Scope 以 ``public`` 作为共享键；历史任务缺少 Scope 时使用全局键，
        以失败关闭方式避免错误并行。
        """

        runtime = record.get("runtime")
        runtime = runtime if isinstance(runtime, dict) else {}
        context = record.get("runtime_context")
        context = context if isinstance(context, dict) else {}
        selector = context.get("snapshot_selector")
        selector = selector if isinstance(selector, dict) else {}
        scope_id = str(
            runtime.get("runtime_scope_id")
            or selector.get("runtime_scope_id")
            or "legacy-global"
        )
        credential_versions = selector.get("credential_versions")
        credential_ids = (
            sorted(str(item) for item in credential_versions)
            if isinstance(credential_versions, dict) and credential_versions
            else ["public"]
        )
        return frozenset(f"{scope_id}:{credential_id}" for credential_id in credential_ids)

    def _refresh_compat_active_id(self) -> None:
        """维护历史测试/调用方读取的单值 ``_active_id`` 兼容视图。"""

        self._active_id = sorted(self._active_ids)[0] if self._active_ids else None

    def _pending_records(self) -> list[dict[str, Any]]:
        """按持久 sequence 返回待调度任务；旧记录以任务 ID 兜底排序。"""

        records = [
            record
            for record in self._store.list()
            if record.get("status") == "pending"
            and str(record.get("id") or "") not in self._active_ids
        ]
        def queue_key(item: dict[str, Any]) -> tuple[int, str]:
            queue = item.get("queue")
            sequence = queue.get("sequence") if isinstance(queue, dict) else 0
            return int(sequence or 0), str(item.get("id") or "")

        records.sort(
            key=queue_key
        )
        return records

    def _can_dispatch(self, isolation_keys: frozenset[str]) -> bool:
        """判断并发槽位与 Credential 隔离键是否同时可用。"""

        if len(self._active_ids) >= self._max_concurrency:
            return False
        occupied = set().union(*self._active_isolation_keys.values()) if self._active_isolation_keys else set()
        return not bool(occupied.intersection(isolation_keys))

    def _reserve_pending(self) -> tuple[str, dict[str, Any]] | None:
        """选择全局最早的可执行任务并原子预占槽位。"""

        with self._lock:
            for record in self._pending_records():
                isolation_keys = self._task_isolation_keys(record)
                if not self._can_dispatch(isolation_keys):
                    continue
                task_id = str(record["id"])
                queue = record.setdefault("queue", {})
                queue["dispatched_at"] = _now_iso()
                self._store.save(record)
                self._active_ids.add(task_id)
                self._active_isolation_keys[task_id] = isolation_keys
                self._refresh_compat_active_id()
                return task_id, record
        return None

    def _release_active(self, task_id: str) -> None:
        """释放任务占用的进程槽位与 Credential 隔离键。"""

        self._active_ids.discard(task_id)
        self._active_isolation_keys.pop(task_id, None)
        self._refresh_compat_active_id()

    def _dispatch_pending(
        self,
        *,
        preferred_task_id: str | None = None,
        propagate_start_error: bool = False,
    ) -> None:
        """尽可能填满并发槽位；默认部署只会启动一个任务。

        ``preferred_task_id`` 仅用于保留空闲提交时启动失败同步返回的旧契约；
        已经排队的任务后续启动失败只写入该任务终态，不影响前一请求。
        """

        while True:
            reserved = self._reserve_pending()
            if reserved is None:
                return
            task_id, _record = reserved
            try:
                self._start(task_id)
            except _TaskCancelledBeforeStart:
                with self._lock:
                    self._release_active(task_id)
                    # 包含 Popen 后、进程登记前的取消窗口。此时槽位必须等
                    # _start 已终止孤儿进程后才能释放；统一清理内存引用及两份
                    # 临时文件，避免留下 cancel 标记或 Secret 快照。
                    self._cleanup_refs(task_id)
                    self._store.enforce_retention(self._retain)
                continue
            except Exception as exc:
                self._fail_start(task_id, exc)
                if propagate_start_error and task_id == preferred_task_id:
                    raise
                # 一个任务启动失败不能阻塞队列；继续寻找下一条可执行任务。
                continue

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
            "batch": [
                ENTRY_SINGLE
                if task_input.get("batch_type") == "cases"
                else ENTRY_FLOW
            ],
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
        if task_input.get("tag") and (
            task_input.get("legacy_mode")
            or (
                task_input.get("env")
                and not task_input.get("project_id")
            )
            or task_input.get("run_type") == "all"
        ):
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

        # 平台 Release 以 ConfigDefinition 的逻辑键 ``gateway.comm`` 返回项目
        # 静态通讯参数。Credential 只允许补充 token/user_id 等动态会话字段；
        # 历史凭证中的 DEVICE_ID 不得覆盖已项目化的 comm.device_id。
        logical_comm = settings.pop("gateway.comm", None)
        if logical_comm is not None:
            if not isinstance(logical_comm, dict):
                raise SubmissionError(
                    503, PLATFORM_CONFIG_UNAVAILABLE, "平台快照 gateway.comm 配置无效"
                )
            existing_comm = settings.get("comm")
            if existing_comm is not None and not isinstance(existing_comm, dict):
                raise SubmissionError(
                    503, PLATFORM_CONFIG_UNAVAILABLE, "平台快照 comm 配置无效"
                )
            normalized_comm = json.loads(json.dumps(logical_comm, ensure_ascii=False))
            if isinstance(existing_comm, dict):
                normalized_comm.update(existing_comm)
            settings["comm"] = normalized_comm
        comm = settings.setdefault("comm", {})
        if not isinstance(comm, dict):
            raise SubmissionError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台快照 comm 配置无效")
        secret_comm_mapping = {
            "AUTH_TOKEN": "auth_token",
            "ACCESS_TOKEN": "auth_token",
            "USER_ID": "user_id",
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

    def _persist_dispatch_materialization(
        self,
        record: dict[str, Any],
        payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """在生成含 Secret 的临时文件前持久化调度版本。

        dispatch-materialize 可能把同一 Credential ID 刷新到较新版本。该
        selector 不含 Secret，必须在平台响应成功后立即写回 Task JSON；若
        随后的快照写盘或 Popen 失败，重启恢复仍能以已经确认的版本继续。
        保存时重新读取当前状态，避免物化期间发生的取消被旧 ``record``
        覆盖回 pending。

        异常说明:
            _TaskCancelledBeforeStart: 任务已被取消或不再处于 pending。
            SubmissionError: 平台返回了非法 selector。
        """

        refreshed_selector = payload.get("snapshot_selector")
        if refreshed_selector is not None and not isinstance(
            refreshed_selector, dict
        ):
            raise SubmissionError(
                409,
                "RUNTIME_SNAPSHOT_INVALID",
                "平台调度快照选择器无效，请重新提交任务",
            )
        with self._lock:
            latest = self._store.load(str(record.get("id") or ""))
            if latest is None or latest.get("status") != "pending":
                raise _TaskCancelledBeforeStart(str(record.get("id") or ""))
            if isinstance(refreshed_selector, dict):
                runtime_context = latest.get("runtime_context")
                if not isinstance(runtime_context, dict):
                    raise SubmissionError(
                        409,
                        "RUNTIME_SNAPSHOT_INVALID",
                        "任务运行上下文无效，请重新提交任务",
                    )
                # JSON 往返生成独立副本，防止 provider 后续复用并修改响应对象。
                runtime_context["snapshot_selector"] = json.loads(
                    json.dumps(refreshed_selector, ensure_ascii=False)
                )
            self._apply_snapshot_metadata(latest, metadata)
            self._store.save(latest)
            return latest

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
        # TaskManager 只信任自己刚写入的固定执行文件，绝不继承宿主机同名
        # 环境变量；否则本地服务可能被指向其他任务或项目的资产。
        task_environment.pop("API_AUTOTEST_EXECUTION_ASSET_FILE", None)
        if self._runtime_snapshot_provider is not None:
            payload, snapshot_metadata = self._runtime_snapshot_provider(record)
            if not isinstance(payload, dict) or not isinstance(snapshot_metadata, dict):
                raise SubmissionError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台运行快照响应无效")
            # 先持久化刷新后的 selector，再创建含 Secret 的临时快照。后续任一
            # 本机步骤失败或服务重启，都不会退回提交时的旧 Credential 版本。
            record = self._persist_dispatch_materialization(
                record,
                payload,
                snapshot_metadata,
            )
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
        elif self._runtime_environment_provider is not None:
            # 旧接入测试仍可注入环境映射；生产平台模式不再走该分支。
            runtime_values, snapshot_metadata = self._runtime_environment_provider(record)
            task_environment.update(runtime_values)
            with self._lock:
                latest = self._store.load(task_id)
                if latest is None or latest.get("status") != "pending":
                    raise _TaskCancelledBeforeStart(task_id)
                latest["config_release_id"] = snapshot_metadata.get("release_id")
                latest["config_release_version"] = snapshot_metadata.get(
                    "release_version"
                )
                latest["credential_version"] = snapshot_metadata.get(
                    "credential_version"
                )
                self._store.save(latest)
                record = latest
        input_manifest_file = record.get("input_manifest_file")
        if input_manifest_file:
            # manifest 路径由 TaskStore 生成并保存在任务记录中，浏览器不能覆盖。
            manifest_path = self._project_root / str(input_manifest_file)
            if not manifest_path.is_file():
                raise SubmissionError(
                    409,
                    TASK_INPUTS_MISSING,
                    "任务输入清单不存在，无法启动执行",
                )
            task_environment["API_AUTOTEST_TASK_INPUT_MANIFEST_FILE"] = str(
                manifest_path
            )
        asset_snapshot = record.get("asset_snapshot")
        if isinstance(asset_snapshot, dict):
            execution_document = {
                "schema_version": 1,
                "task_id": task_id,
                "project_id": project_id,
                "asset_type": asset_snapshot.get("asset_type"),
                "asset_id": asset_snapshot.get("asset_id"),
                "asset_revision": asset_snapshot.get("asset_revision"),
                "resolved_asset_revision": asset_snapshot.get(
                    "resolved_asset_revision"
                ),
                "resolved_execution_asset": asset_snapshot.get(
                    "resolved_execution_asset"
                ),
            }
            execution_asset_path = self._store.save_execution_asset(
                task_id,
                project_id,
                execution_document,
            )
            task_environment["API_AUTOTEST_EXECUTION_ASSET_FILE"] = str(
                execution_asset_path
            )
        # Runtime materialize 可能包含网络请求；期间用户仍可取消 pending
        # 任务。真正 Popen 前必须重新读取终态，避免“页面已取消但请求仍发出”。
        with self._lock:
            latest = self._store.load(task_id)
            if latest is None or latest.get("status") != "pending":
                raise _TaskCancelledBeforeStart(task_id)
        with console_path.open("w", encoding="utf-8") as console_file:
            proc = subprocess.Popen(
                args,
                cwd=self._project_root,
                env=task_environment,
                stdout=console_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        terminate_unregistered = False
        with self._lock:
            # Popen 本身不受状态锁保护；cancel 可能恰好在系统进程创建后、
            # 进程登记前把 pending 写成 cancelled。必须重新读取持久状态，
            # 终态时只终止刚创建的孤儿进程，绝不能用旧 record 复活任务。
            latest = self._store.load(task_id)
            if latest is None or latest.get("status") != "pending":
                terminate_unregistered = True
                thread = None
            else:
                latest["pid"] = proc.pid
                latest["status"] = "running"
                latest["started_at"] = _now_iso()
                self._store.save(latest)
                self._procs[task_id] = proc
                thread = threading.Thread(
                    target=self._wait,
                    args=(task_id, proc),
                    name=f"task-wait-{task_id}",
                    daemon=True,
                )
                self._threads[task_id] = thread
        if terminate_unregistered:
            self._terminate_group(proc)
            raise _TaskCancelledBeforeStart(task_id)
        assert thread is not None
        thread.start()

    def _fail_start(self, task_id: str, error: Exception | None = None) -> None:
        """启动/dispatch 失败时写入可诊断终态并释放槽位。"""
        with self._lock:
            record = self._store.load(task_id)
            if record is not None and record.get("status") not in TERMINAL_STATUSES:
                record["status"] = "failed"
                record["finished_at"] = _now_iso()
                if isinstance(error, SubmissionError):
                    # 排队任务由后台调度，调用方已无法同步收到平台错误；稳定
                    # 错误码必须进入任务记录，才能区分凭证失效、Context 过期
                    # 与本机 Popen 故障。
                    record["error_code"] = error.error_code
                    record["error_message"] = error.message
                else:
                    record["error_code"] = "TASK_START_FAILED"
                    record["error_message"] = "子进程启动失败，任务未执行"
                self._mark_pending_batch_items_not_run(
                    record, reason=record.get("error_message")
                )
                self._store.save(record)
            self._release_active(task_id)
            self._delete_snapshot(task_id)
            if record is not None:
                self._delete_execution_asset(record)

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
        dispatch_next = False
        with self._lock:
            record = self._store.load(task_id)
            if record is None:
                raise SubmissionError(404, TASK_NOT_FOUND, f"任务不存在: {task_id}")
            if record["status"] in TERMINAL_STATUSES:
                raise SubmissionError(
                    409, TASK_TERMINATED, f"任务已处于终态: {record['status']}"
                )
            record["cancel_requested_at"] = _now_iso()
            self._cancel_requested.add(task_id)
            proc = self._procs.get(task_id)
            if record.get("status") == "pending" and proc is None:
                # 排队任务没有子进程可等待，取消应立即进入终态；否则它仍会
                # 被调度器选中。输入、console 和历史 JSON 均继续保留审计。
                # 若任务已被调度器预占，则可能正处于 materialize/Popen 窗口；
                # 该槽位和 Credential 隔离锁必须由启动线程在停止潜在进程后
                # 释放，不能提前调度下一条同凭证任务。
                starting = task_id in self._active_ids
                record["status"] = "cancelled"
                record["finished_at"] = _now_iso()
                batch = record.get("batch")
                if isinstance(batch, dict):
                    for item in batch.get("items") or []:
                        if isinstance(item, dict) and item.get("status") == "pending":
                            item["status"] = "cancelled"
                self._store.save(record)
                if not starting:
                    self._release_active(task_id)
                    self._cleanup_refs(task_id)
                    self._store.enforce_retention(self._retain)
                    dispatch_next = True
            else:
                self._store.save(record)

        if proc is not None:
            # 宽限期可能较长，放后台执行；等待线程会在进程退出后写入终态。
            threading.Thread(
                target=self._terminate_group,
                args=(proc,),
                name=f"task-cancel-{task_id}",
                daemon=True,
            ).start()
        elif dispatch_next:
            self._dispatch_pending()
        return self._store.load(task_id) or record

    def retry(
        self,
        task_id: str,
        *,
        signed_user_context: str = "",
        mode: str = "all",
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
        normalized_mode = str(mode or "all").strip()
        if normalized_mode not in {"all", "failed"}:
            raise SubmissionError(400, INVALID_PARAMS, "重试 mode 只能是 all 或 failed")
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
        original_input = (
            original.get("input")
            if isinstance(original.get("input"), dict)
            else {}
        )
        original_overrides = original_input.get("runtime_overrides") or {}
        if selection.get("run_type") == "batch":
            batch = original.get("batch")
            if not isinstance(batch, dict):
                raise SubmissionError(409, BATCH_SELECTION_INVALID, "原批次记录不完整")
            source_items = [
                item
                for item in batch.get("items") or []
                if isinstance(item, dict)
                and (
                    normalized_mode == "all"
                    or item.get("status") in {"failed", "error"}
                )
            ]
            if not source_items:
                raise SubmissionError(
                    400,
                    BATCH_SELECTION_REQUIRED,
                    "原批次没有可重试的失败项",
                )
            batch_type = str(batch.get("type") or "")
            try:
                current = {
                    str(snapshot["asset_id"]): snapshot
                    for snapshot in self._batch_candidate_snapshots(
                        str(project_id), batch_type
                    )
                }
            except (
                ApiConfigError,
                CaseConfigError,
                FlowConfigError,
                ProjectRegistryError,
                RuntimeOverrideError,
            ) as exc:
                raise SubmissionError(
                    409,
                    BATCH_SELECTION_INVALID,
                    f"当前批次资产不可用: {exc}",
                ) from exc
            retry_items: list[dict[str, str]] = []
            for item in source_items:
                asset_id = str(item.get("asset_id") or "")
                snapshot = current.get(asset_id)
                if snapshot is None:
                    raise SubmissionError(
                        409,
                        BATCH_SELECTION_INVALID,
                        f"当前 YAML 已不存在批次资产: {asset_id}",
                    )
                retry_items.append(
                    {
                        "asset_id": asset_id,
                        "asset_revision": str(snapshot["asset_revision"]),
                    }
                )
            return self.submit(
                project_id=str(project_id),
                run_type="batch",
                batch_type=batch_type,
                selection_mode="selected",
                batch_items=retry_items,
                risk_acknowledgements=batch.get("risk_acknowledgements") or [],
                signed_user_context=signed_user_context,
                retry_of=task_id,
                _retry_input_record=original,
            )
        return self.submit(
            project_id=str(project_id),
            run_type=str(selection.get("run_type") or ""),
            api_id=selection.get("api_id"),
            case_id=selection.get("case_id"),
            flow_id=selection.get("flow_id"),
            tag=(
                selection.get("tag")
                if original_input.get("legacy_mode")
                or selection.get("run_type") == "all"
                else None
            ),
            # 使用当前 YAML 重新解析目标和版本，只复制旧任务的逻辑键和值。
            # 若字段被删除或约束变化，submit 会统一映射为 409 schema changed。
            asset_revision=None,
            runtime_overrides=original_overrides,
            signed_user_context=signed_user_context,
            retry_of=task_id,
            _retry_input_record=original,
        )

    def _associate_log_file(
        self,
        record: dict[str, Any],
        finished_at: str,
    ) -> str | None:
        """按子进程 PID 关联框架原始日志文件。

        功能说明:
            V2 框架日志命名为
            ``logs/<project>/<env>/YYYY-MM-DD/{时间戳}_{env}_{pid}.log``；
            在任务起止日期覆盖的项目目录中按 PID 后缀匹配，并只接受任务时间窗
            前后 5 秒容差内的候选。若 PID 因容器重启被复用，时间窗外的旧日志
            不得关联；多个候选时选择时间最新者。历史任务继续从
            ``logs/YYYY-MM-DD`` 查找，已有任务记录中的 ``log_file`` 不受影响。
        """
        project_id = str(record.get("project", {}).get("project_id") or "truthy")
        target_env = str(record.get("runtime", {}).get("target_env") or "test")
        try:
            pid = int(record.get("pid"))
        except (TypeError, ValueError):
            return None
        if pid <= 0:
            return None
        logs_root = self._project_root / "logs"
        is_v2_project_task = (
            record.get("schema_version") in {2, 3}
            and not bool(record.get("input", {}).get("legacy_mode"))
        )
        if is_v2_project_task:
            logs_root = logs_root / project_id / target_env
        try:
            # 文件名使用本机无时区时间；任务时间同样由本机生成但包含偏移量。
            # 去掉 tzinfo 而不换算时区，才能与文件名中的墙上时间逐字对齐。
            started = datetime.fromisoformat(str(record.get("started_at"))).replace(
                tzinfo=None
            )
            finished = datetime.fromisoformat(finished_at).replace(tzinfo=None)
        except (TypeError, ValueError):
            # 缺少可靠时间窗时 fail closed，避免只凭复用 PID 读取其他任务原文。
            return None
        if finished < started:
            return None
        association_grace = timedelta(seconds=5)
        window_start = started - association_grace
        window_end = finished + association_grace
        candidates: list[tuple[datetime, Path]] = []
        task_id = str(record.get("id") or "")
        patterns = (
            [f"*_{task_id}_{pid}.log", f"*_{pid}.log"]
            if record.get("schema_version") == 3 and is_valid_task_id(task_id)
            else [f"*_{pid}.log"]
        )
        for pattern in patterns:
            current = window_start.date()
            while current <= window_end.date():
                day_directory = logs_root / current.strftime("%Y-%m-%d")
                if day_directory.is_dir():
                    for path in sorted(day_directory.glob(pattern)):
                        try:
                            log_time = datetime.strptime(
                                path.name[:22],
                                "%Y%m%d_%H%M%S_%f",
                            )
                        except ValueError:
                            # 旧日志命名不含可解析时间戳时使用文件修改时间；仍
                            # 必须通过任务时间窗，不能退化为纯 PID 匹配。
                            try:
                                log_time = datetime.fromtimestamp(path.stat().st_mtime)
                            except OSError:
                                continue
                        if window_start <= log_time <= window_end:
                            candidates.append((log_time, path))
                current += timedelta(days=1)
            # V3 精确命中 task ID 后不再允许一个同 PID 的其他任务覆盖结果；
            # 只有历史日志没有 task ID 时才进入第二个兼容模式。
            if candidates:
                break
        if not candidates:
            return None
        _, selected = max(candidates, key=lambda item: item[0])
        return selected.relative_to(self._project_root).as_posix()

    def _console_tail(self, task_id: str) -> str:
        """读取 console.log 原始尾部并按失败摘要长度截断。"""
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
        return truncate_tail(tail, max_length=FAILED_MESSAGE_LIMIT)

    @staticmethod
    def _mark_pending_batch_items_not_run(
        record: dict[str, Any], *, reason: Any = None
    ) -> None:
        """把尚未开始的批次子项关闭为 ``not_run``。

        启动失败或服务重启会让根任务直接进入 failed，且不会产生可供
        ``_apply_batch_results`` 映射的 JUnit。若保留 pending，详情页会在
        终态任务中继续显示“排队中”。这里只修改 pending，避免覆盖未来
        已经落盘的通过/失败子项。
        """

        batch = record.get("batch")
        if not isinstance(batch, dict):
            return
        summary = str(reason or "").strip() or None
        for item in batch.get("items") or []:
            if not isinstance(item, dict) or item.get("status") != "pending":
                continue
            item["status"] = "not_run"
            if summary and not item.get("error_summary"):
                item["error_summary"] = summary

    @staticmethod
    def _apply_batch_results(
        record: dict[str, Any],
        parsed: dict[str, Any] | None,
        *,
        cancelled: bool,
    ) -> bool:
        """把聚合 JUnit 的 testcase 映射回任务内逻辑子项。

        返回值:
            正常执行时是否存在缺失结果。取消任务的未完成条目标记为
            ``cancelled``，不视为报告不完整；其他缺失条目标记 ``not_run``。
        """

        batch = record.get("batch")
        if not isinstance(batch, dict):
            return False
        junit_cases = parsed.get("cases") if isinstance(parsed, dict) else []
        junit_cases = junit_cases if isinstance(junit_cases, list) else []
        incomplete = False
        for item in batch.get("items") or []:
            if not isinstance(item, dict):
                continue
            pytest_id = str(item.get("pytest_id") or "")
            asset_id = str(item.get("asset_id") or "")
            def matches(case: dict[str, Any]) -> bool:
                """按 pytest 参数 ID 精确匹配，避免 case1 命中 case10。"""

                name = str(case.get("name") or "")
                parameter_id = (
                    name.rsplit("[", 1)[1][:-1]
                    if name.endswith("]") and "[" in name
                    else name
                )
                return parameter_id == pytest_id or (
                    not pytest_id and parameter_id == asset_id
                )

            matched = next(
                (
                    case
                    for case in junit_cases
                    if isinstance(case, dict) and matches(case)
                ),
                None,
            )
            if matched is None:
                item["status"] = "cancelled" if cancelled else "not_run"
                if not cancelled:
                    incomplete = True
                continue
            item["status"] = str(matched.get("status") or "error")
            try:
                item["duration_ms"] = round(float(matched.get("duration")) * 1000)
            except (TypeError, ValueError):
                item["duration_ms"] = None
            item["error_summary"] = str(matched.get("message") or "") or None
        return incomplete

    def _finalize(
        self,
        task_id: str,
        exit_code: int | None,
        timed_out: bool,
    ) -> None:
        """在状态锁内提交终态；已处于终态时只补充退出码与产物信息。"""
        should_dispatch = False
        with self._lock:
            record = self._store.load(task_id)
            if record is None:
                self._cleanup_refs(task_id)
                return

            finished_at = _now_iso()
            junit_path = self._project_root / record["junit_file"]
            parsed = parse_junit_file(junit_path, self._project_root)
            cancelled_requested = task_id in self._cancel_requested
            batch_incomplete = self._apply_batch_results(
                record,
                parsed,
                cancelled=cancelled_requested,
            )

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
                self._release_active(task_id)
                should_dispatch = True
            elif cancelled_requested:
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
                if batch_incomplete:
                    record["status"] = "failed"
                    record["error_code"] = BATCH_RESULT_INCOMPLETE
                    record["error_message"] = "批次存在未生成 JUnit 结果的子项"
                elif exit_code == 0:
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

            if not should_dispatch:
                record["finished_at"] = finished_at
                self._store.save(record)
                self._cleanup_refs(task_id)
                self._release_active(task_id)
                self._store.enforce_retention(self._retain)
                should_dispatch = True
        if should_dispatch:
            self._dispatch_pending()

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
        record = self._store.load(task_id)
        self._procs.pop(task_id, None)
        self._threads.pop(task_id, None)
        self._cancel_requested.discard(task_id)
        self._delete_snapshot(task_id)
        if record is not None:
            self._delete_execution_asset(record)

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

    def _delete_execution_asset(self, record: dict[str, Any]) -> None:
        """按任务记录中的不可变身份精准删除 execution-asset.json。

        恢复或异常记录若缺少合法项目/任务 ID，选择保留文件而不扩大删除
        范围；正常终态只删除这一份临时 JSON，console、图片和报告不受影响。
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
        self._store.cleanup_execution_asset(task_id, project_id)

    # ------------------------------------------------------------------
    # 启动恢复与测试辅助
    # ------------------------------------------------------------------

    def recover_on_startup(self) -> int:
        """恢复持久队列：running 失败，pending 保持 FIFO 并重新调度。

        返回值:
            被恢复的任务数量。
        """
        recovered = 0
        with self._lock:
            for record in self._store.list():
                if record.get("status") == "running":
                    # 先删除包含 Secret 的受控快照，再持久化失败终态。即使后续
                    # 任务 JSON 写入失败，也不会让明文配置继续滞留在磁盘。
                    self._delete_recovered_snapshot(record)
                    self._delete_execution_asset(record)
                    record["status"] = "failed"
                    record["finished_at"] = _now_iso()
                    record["error_message"] = "服务重启，任务中断"
                    self._mark_pending_batch_items_not_run(
                        record, reason=record["error_message"]
                    )
                    self._store.save(record)
                    recovered += 1
                elif record.get("status") == "pending":
                    queue = record.get("queue")
                    if not isinstance(queue, dict):
                        queue = {
                            "sequence": self._next_queue_sequence,
                            "queued_at": record.get("created_at") or _now_iso(),
                            "dispatched_at": None,
                        }
                        self._next_queue_sequence += 1
                        record["queue"] = queue
                    else:
                        if queue.get("dispatched_at"):
                            # 已写 dispatched_at 说明任务至少进入过 _start；服务
                            # 可能遗留含 Secret 的 snapshot 或不可变执行清单。
                            # 重新派发前只清理这两份受控临时文件，console/图片
                            # 等审计输入继续保留。
                            self._delete_recovered_snapshot(record)
                            self._delete_execution_asset(record)
                        # 进程可能在预占后、Popen 前退出；恢复时重新进入排队态。
                        queue["dispatched_at"] = None
                    self._store.save(record)
            self._active_ids.clear()
            self._active_isolation_keys.clear()
            self._refresh_compat_active_id()
        self._dispatch_pending()
        return recovered

    def queue_position(self, task_id: str) -> int | None:
        """实时计算 pending 任务的一基队列位置；运行/终态返回 None。"""

        with self._lock:
            pending = self._pending_records()
            for index, record in enumerate(pending, start=1):
                if record.get("id") == task_id:
                    return index
        return None

    def queue_status(self) -> dict[str, int]:
        """返回不含任务内容的队列容量摘要，供 Preflight 展示。"""

        with self._lock:
            pending = sum(
                1
                for record in self._store.list()
                if record.get("status") == "pending"
            )
        return {
            "pending": pending,
            "pending_count": pending,
            "capacity": self._max_pending_tasks,
            "available": max(self._max_pending_tasks - pending, 0),
            "max_concurrency": self._max_concurrency,
            "position": None,
            "estimated_position": None,
        }

    def wait_idle(self, timeout: float = 30.0) -> None:
        """等待全部等待线程结束；仅供测试与停机使用。"""
        while True:
            self._dispatch_pending()
            with self._lock:
                threads = list(self._threads.values())
                has_pending = any(
                    record.get("status") == "pending"
                    for record in self._store.list()
                )
            if not threads and not has_pending:
                return
            for thread in threads:
                thread.join(timeout=timeout)
            if not any(thread.is_alive() for thread in threads):
                return
