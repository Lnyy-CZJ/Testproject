#!/usr/bin/env python3
"""Run People Insight search tasks sequentially and save ui_sections results."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parent
SERVICE_NAME = "tool.people_insight.SearchService"
MEDIA_SERVICE_NAME = "tool.people_insight.MediaService"
ADMIN_SERVICE_NAME = "tool.admin.AdminService"
RESULT_SCHEMA_VERSION = "1.3.2"
SUPPORTED_QUERY_STAGES = {
    "FULL_NAME",
    "FULL_NAME_SOCIAL",
    "FULL_NAME_PHOTO",
    "FULL_NAME_SOCIAL_PHOTO",
}
PHOTO_QUERY_STAGES = {"FULL_NAME_PHOTO", "FULL_NAME_SOCIAL_PHOTO"}
SOCIAL_QUERY_STAGES = {"FULL_NAME_SOCIAL", "FULL_NAME_SOCIAL_PHOTO"}
GET_TASK_RUNNING_STATUSES = frozenset({"QUEUED", "SEARCHING"})
GET_TASK_SUCCESS_STATUS = "SUCCEEDED"
GET_TASK_NO_RESULT_STATUS = "NO_RESULT"
# 当前正式通用失败终态为 FAILED；后端扩充枚举时只修改此集合与契约测试。
GET_TASK_FAILURE_TERMINAL_STATUSES = frozenset({"FAILED"})
ADMIN_REFRESH_WINDOW = timedelta(hours=1)
PUBLIC_INFO_TERMINAL_DELAY_SECONDS = 1.0
ProgressCallback = Callable[[dict[str, Any]], None]
RawCallback = Callable[[dict[str, Any]], None]
FailureCallback = Callable[[dict[str, Any]], None]

# Admin Debug 的 Provider 名称会继续扩展，但报告需要稳定的产品分类。
# 这里保留固定 key 和显示名称；无法识别的新 Provider 仍完整保存在 Raw 和
# cost_by_provider，不会被错误归入某个已知工具。
ADMIN_TOOL_DEFINITIONS = (
    ("pdl_person_identify", "PDL Person Identify"),
    ("pdl_person_search", "PDL Person Search"),
    ("llm_search", "LLM Search"),
    ("wiki", "Wiki / Public Figure"),
    ("google_lens", "Google Lens"),
    ("google_vision", "Google Vision"),
    ("social_profile_extraction", "Social Profile Extraction"),
)
ADMIN_TOOL_SUCCESS_STATUSES = frozenset({"success", "cache_hit"})
ADMIN_TOOL_NO_RESULT_STATUSES = frozenset({"no_result"})
ADMIN_TOOL_FAILURE_STATUSES = frozenset({
    "failed", "failure", "error", "timeout", "timed_out", "cancelled",
})


def classify_admin_tool(provider: Any, operation: Any) -> str | None:
    """把 Admin Provider/Operation 映射为稳定的报告工具分类。"""

    provider_text = str(provider or "").strip().lower()
    operation_text = str(operation or "").strip().lower()
    token = f"{provider_text} {operation_text}"
    if "google_lens" in token or "google lens" in token:
        return "google_lens"
    if "google_vision" in token or "google vision" in token:
        return "google_vision"
    if provider_text.startswith("llm_search"):
        return "llm_search"
    if provider_text == "social_profile":
        return "social_profile_extraction"
    if provider_text in {"public_figure", "wikidata", "wikipedia", "wiki"}:
        return "wiki"
    if provider_text == "people_data_labs":
        return (
            "pdl_person_identify"
            if "identify" in operation_text
            else "pdl_person_search"
        )
    return None


def classify_admin_call_outcome(call: Any) -> str:
    """把 Admin 工具调用状态归一为成功、无结果、失败或未知。

    功能说明:
        ``cache_hit`` 表示调用成功复用缓存，``no_result`` 表示调用正常完成
        但没有找到数据；两者都不能误记为接口失败。明确错误码、错误消息或
        失败终态才归为 ``FAILED``。

    参数说明:
        call: Admin Debug ``agent_tool_calls`` 中的单条调用记录。

    返回值:
        str: ``SUCCESS``、``NO_RESULT``、``FAILED`` 或 ``UNKNOWN``。

    异常说明:
        非字典或未知状态不抛出异常，统一返回 ``UNKNOWN`` 供报告显式展示。
    """

    if not isinstance(call, dict):
        return "UNKNOWN"
    status = str(call.get("status") or "").strip().lower()
    if str(call.get("error_code") or "").strip() or str(
        call.get("error_message") or ""
    ).strip():
        return "FAILED"
    if status in ADMIN_TOOL_SUCCESS_STATUSES:
        return "SUCCESS"
    if status in ADMIN_TOOL_NO_RESULT_STATUSES:
        return "NO_RESULT"
    if status in ADMIN_TOOL_FAILURE_STATUSES:
        return "FAILED"
    return "UNKNOWN"


def extract_admin_tool_usage(
    debug_body: dict[str, Any] | None,
    cost_body: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """联合 Debug 与 Cost 响应，提取工具调用及可审计的成本归属。

    返回值：
        第一项为七类工具的调用、成功/失败、成本和计价状态；第二项为全部
        Provider 的标准化成本汇总。PDL Identify 与 Search 同时出现时，
        people_data_labs 成本不会被擅自分摊到两个工具，但仍会完整保留在
        Provider 汇总中。
    """

    def envelope_data(body: dict[str, Any] | None) -> dict[str, Any]:
        """安全读取 Admin ``responses[0].data``。"""

        if not isinstance(body, dict):
            return {}
        responses = body.get("responses")
        if not isinstance(responses, list) or not responses:
            return {}
        response = responses[0]
        data = response.get("data") if isinstance(response, dict) else None
        return data if isinstance(data, dict) else {}

    tools = {
        key: {
            "key": key,
            "label": label,
            "call_count": 0,
            "success_count": 0,
            "no_result_count": 0,
            "failed_count": 0,
            "unknown_count": 0,
            "provider_call_count": 0,
            "priced_call_count": 0,
            "non_billable_call_count": 0,
            "unpriced_call_count": 0,
            "cost_microunit": None,
            "cost": None,
            "currency": None,
            "cost_status": "NOT_COLLECTED",
            "providers": [],
        }
        for key, label in ADMIN_TOOL_DEFINITIONS
    }
    debug_data = envelope_data(debug_body)
    debug = debug_data.get("debug")
    if isinstance(debug, dict):
        calls = debug.get("agent_tool_calls")
        for call in calls if isinstance(calls, list) else []:
            if not isinstance(call, dict):
                continue
            provider = str(call.get("provider") or "").strip()
            key = classify_admin_tool(provider, call.get("provider_operation"))
            if key is None:
                continue
            item = tools[key]
            item["call_count"] += 1
            outcome = classify_admin_call_outcome(call)
            outcome_counter = {
                "SUCCESS": "success_count",
                "NO_RESULT": "no_result_count",
                "FAILED": "failed_count",
                "UNKNOWN": "unknown_count",
            }[outcome]
            item[outcome_counter] += 1
            if provider and provider not in item["providers"]:
                item["providers"].append(provider)

    cost_data = envelope_data(cost_body)
    cost_summary = cost_data.get("cost_summary")
    cost_container = cost_summary if isinstance(cost_summary, dict) else cost_data
    provider_rows = cost_container.get("by_provider")
    provider_rows = provider_rows if isinstance(provider_rows, list) else []
    pdl_keys_used = {
        key for key in ("pdl_person_identify", "pdl_person_search")
        if tools[key]["call_count"] > 0
    }
    provider_level: dict[str, Any] = {}

    def integer(value: Any) -> int:
        """把接口的整数字符串转换为非负整数，非法值按 0 处理。"""

        try:
            return max(0, int(Decimal(str(value or 0))))
        except (InvalidOperation, ValueError, TypeError):
            return 0

    def merge_cost_status(current: str, incoming: str) -> str:
        """合并同一 Provider 的多条计费状态，优先保留最可审计的状态。"""

        priority = {
            "NOT_COLLECTED": 0,
            "UNKNOWN": 1,
            "NON_BILLABLE": 2,
            "UNPRICED": 3,
            "PRICED": 4,
        }
        return (
            incoming
            if priority.get(incoming, 1) >= priority.get(current, 1)
            else current
        )

    for row in provider_rows:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider") or "").strip()
        key = classify_admin_tool(provider, "")
        if provider.lower() == "people_data_labs":
            if len(pdl_keys_used) == 1:
                key = next(iter(pdl_keys_used))
            else:
                key = None
        currency = str(row.get("currency") or "").strip().upper()
        cost_microunit = integer(row.get("total_cost_microunit"))
        call_count = integer(row.get("call_count"))
        priced_count = integer(row.get("priced_call_count"))
        non_billable_count = integer(row.get("non_billable_call_count"))
        unpriced_count = integer(row.get("unpriced_call_count"))
        row_cost_status = (
            "PRICED" if currency == "USD" else
            "UNPRICED" if unpriced_count else
            "NON_BILLABLE" if non_billable_count else "UNKNOWN"
        )
        # Provider 汇总独立于工具分类：即使 Provider 已精确映射到某个工具，
        # 也必须保留其总额，供 Excel、报告和未来未知 Provider 一致使用。
        if provider:
            provider_key = provider.casefold()
            provider_item = provider_level.setdefault(provider_key, {
                "provider": provider,
                "currency": None,
                "cost_microunit": None,
                "cost": None,
                "call_count": 0,
                "priced_call_count": 0,
                "non_billable_call_count": 0,
                "unpriced_call_count": 0,
                "cost_status": "NOT_COLLECTED",
            })
            provider_item["call_count"] += call_count
            provider_item["priced_call_count"] += priced_count
            provider_item["non_billable_call_count"] += non_billable_count
            provider_item["unpriced_call_count"] += unpriced_count
            provider_item["cost_status"] = merge_cost_status(
                provider_item["cost_status"], row_cost_status
            )
            if currency == "USD":
                provider_item["currency"] = "USD"
                provider_item["cost_microunit"] = (
                    (provider_item["cost_microunit"] or 0) + cost_microunit
                )

        if key is None:
            continue
        item = tools[key]
        item["provider_call_count"] += call_count
        item["priced_call_count"] += priced_count
        item["non_billable_call_count"] += non_billable_count
        item["unpriced_call_count"] += unpriced_count
        if provider and provider not in item["providers"]:
            item["providers"].append(provider)
        if currency == "USD":
            current = item["cost_microunit"] or 0
            item["cost_microunit"] = current + cost_microunit
            item["currency"] = "USD"
            item["cost_status"] = "PRICED"
        elif unpriced_count:
            if item["cost_status"] != "PRICED":
                item["cost_status"] = "UNPRICED"
        elif non_billable_count and item["cost_status"] not in {"PRICED", "UNPRICED"}:
            item["cost_status"] = "NON_BILLABLE"
        elif item["cost_status"] == "NOT_COLLECTED":
            item["cost_status"] = "UNKNOWN"

    for item in tools.values():
        if item["cost_microunit"] is not None:
            item["cost"] = float(
                Decimal(item["cost_microunit"]) / Decimal(1_000_000)
            )
        if item["call_count"] == 0 and item["provider_call_count"]:
            item["call_count"] = item["provider_call_count"]
    for item in provider_level.values():
        if item["cost_microunit"] is not None:
            item["cost"] = float(
                Decimal(item["cost_microunit"]) / Decimal(1_000_000)
            )
    return list(tools.values()), provider_level


def normalize_result_status(
    query_status: str,
    candidate_count_listed: int | None,
) -> str:
    """把采集流程状态转换为稳定的评估结果状态。

    参数说明:
        query_status: Query 的采集明细状态。
        candidate_count_listed: ListTaskCandidates 实际返回数量。

    返回值:
        ``HAS_CANDIDATES``、``NO_CANDIDATES`` 或
        ``EXECUTION_FAILED``。候选人数优先，避免部分详情失败影响结果分类。
    """

    try:
        count = int(candidate_count_listed or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        return "HAS_CANDIDATES"
    if query_status in {"FAILED", "EXECUTION_FAILED"}:
        return "EXECUTION_FAILED"
    return "NO_CANDIDATES"


class ConfigError(ValueError):
    """Raised when local configuration is invalid."""


class FlowError(RuntimeError):
    """表示采集流程中的可记录业务失败。

    除失败阶段、消息和 task_id 外，还可携带接口已返回的业务响应以及本
    Query 已收集的脱敏 Raw，供上层写入 failures.jsonl。
    """

    def __init__(
        self,
        stage: str,
        message: str,
        task_id: str = "",
        response_body: Any = None,
    ) -> None:
        """初始化流程错误。

        参数说明:
            stage: 失败的输入或接口阶段。
            message: 面向测试人员的可读错误。
            task_id: 已创建的任务标识，创建前失败时为空。
            response_body: 失败时已获得的业务响应，HTTP 无响应时为 None。
        """

        super().__init__(message)
        self.stage = stage
        self.task_id = task_id
        self.response_body = response_body
        self.raw_records: list[dict[str, Any]] = []
        self.task_fields: dict[str, Any] = {}
        self.public_fields: dict[str, Any] = {}
        self.http_status: int | None = None
        self.duration_ms: int | None = None
        # 仅标记 HTTP 传输层错误类型；业务失败保持空字符串，避免误重试。
        self.network_error_kind: str = ""


TRANSIENT_HTTP_STATUSES = frozenset({408, 429, *range(500, 600)})
READ_ONLY_RETRY_STAGES = frozenset(
    {"GetTask", "ListTaskCandidates", "GetTaskCandidateDetail"}
)


def classify_transport_error(
    error: BaseException,
    http_status: int | None = None,
) -> str:
    """将 requests 异常归类为安全重试所需的传输层类型。

    参数说明:
        error: requests 抛出的原始异常。
        http_status: 已取得的 HTTP 状态；无响应时为 ``None``。

    返回值:
        ``DNS``、``READ_TIMEOUT``、``CONNECT_TIMEOUT``、``CONNECTION``、
        ``HTTP_TRANSIENT`` 或空字符串。空字符串表示不得自动重试。
    """

    if http_status in TRANSIENT_HTTP_STATUSES:
        return "HTTP_TRANSIENT"
    if isinstance(error, requests.ReadTimeout):
        return "READ_TIMEOUT"
    if isinstance(error, requests.ConnectTimeout):
        return "CONNECT_TIMEOUT"
    # urllib3 的 NameResolutionError 通常被 requests.ConnectionError 包裹，
    # 因此联合检查异常链和文本，且只匹配明确的域名解析失败信号。
    chain: list[str] = []
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        chain.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    error_text = " ".join(chain).casefold()
    dns_markers = (
        "nameresolutionerror",
        "failed to resolve",
        "name or service not known",
        "no address associated with hostname",
        "temporary failure in name resolution",
    )
    if any(marker in error_text for marker in dns_markers):
        return "DNS"
    if isinstance(error, requests.ConnectionError):
        return "CONNECTION"
    if isinstance(error, requests.Timeout):
        return "READ_TIMEOUT"
    return ""


def is_network_flow_error(error: FlowError) -> bool:
    """判断 Query 失败是否来自可恢复网络传输层，而非接口业务响应。"""

    return error.network_error_kind in {
        "DNS",
        "READ_TIMEOUT",
        "CONNECT_TIMEOUT",
        "CONNECTION",
        "HTTP_TRANSIENT",
    }


@dataclass(frozen=True)
class Config:
    api_url: str
    headers: dict[str, str]
    auth_token: str
    device_id: str
    user_id: str
    poll_interval_seconds: float = 5.0
    max_poll_count: int = 60
    http_timeout_seconds: float = 30.0
    search_retry_max_attempts: int = 3
    search_retry_initial_delay_seconds: float = 2.0
    network_failure_threshold: int = 3
    network_recovery_pause_seconds: float = 30.0
    platform: str = "ios"
    app_version: str = "1.0.0"
    locale: str = "zh-Hans-CN"
    timezone: str = "UTC+08:00"
    input_file: str = "input/tasks.jsonl"
    output_dir: str = "output"
    allow_duplicate_run: bool = False
    admin_enabled: bool = False
    admin_login_api_url: str = ""
    admin_api_url: str = ""
    admin_headers: dict[str, str] | None = None
    admin_username: str = ""
    admin_password: str = ""
    admin_reason: str = "searchTool 测试数据采集"
    admin_debug_service: str = "worker"
    admin_cost_limit: int = 100
    admin_config_error: str = ""
    query_log_enabled: bool = False
    query_log_dir: str = "log"
    query_log_timezone: str = "Asia/Shanghai"
    photo_enabled: bool = False
    photo_input_dir: str = "input/input_photos"
    photo_upload_host_suffixes: tuple[str, ...] = (".myqcloud.com",)

    @classmethod
    def from_env(
        cls,
        env_file: Path | None = None,
        overrides: Mapping[str, Any] | None = None,
    ) -> "Config":
        """从最新 Secret 文件与平台环境构造一次性运行配置。

        功能说明:
            每次调用都重新读取 ``env_file``，不再把文件内容写入全局
            ``os.environ``。平台显式环境变量覆盖 Secret 文件同名值，因此既能
            热更新 Token，也不会破坏 Compose 注入的路径和运行参数。

        参数说明:
            env_file: 平台只读 Secret 或本地 ``.env`` 路径；文件不存在时仅使用
                当前进程初始环境。

        返回值:
            当前调用独立使用的不可变 ``Config``。

        异常说明:
            ConfigError: 原 Search 必填项、类型或布尔配置不合法时抛出；Admin
                配置错误仍只关闭公共信息采集。
        """

        file_values = (
            dotenv_values(env_file)
            if env_file is not None and Path(env_file).is_file()
            else {}
        )
        config_values = {
            str(key): "" if value is None else str(value)
            for key, value in file_values.items()
        }
        # 平台环境变量优先，但不修改进程环境，避免一次 Run 污染后续重跑。
        config_values.update(os.environ)
        # 平台运行快照最后覆盖进程启动值，但不修改全局环境。
        if overrides:
            config_values.update({
                str(key): "" if value is None else str(value)
                for key, value in overrides.items()
            })

        def setting(name: str, default: str = "") -> str:
            """读取合并后的单项配置，并统一返回字符串。"""

            value = config_values.get(name, default)
            return "" if value is None else str(value)

        required_names = [
            "SEARCH_API_URL",
            "AUTH_TOKEN",
            "DEVICE_ID",
            "USER_ID",
        ]
        missing = [name for name in required_names if not setting(name).strip()]
        if missing:
            raise ConfigError(f"缺少必要配置: {', '.join(missing)}")

        raw_headers = setting("SEARCH_HTTP_HEADERS_JSON", "{}")
        try:
            headers = json.loads(raw_headers)
        except json.JSONDecodeError as exc:
            raise ConfigError("SEARCH_HTTP_HEADERS_JSON 必须是合法 JSON 对象") from exc
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in headers.items()
        ):
            raise ConfigError("SEARCH_HTTP_HEADERS_JSON 的键和值都必须是字符串")

        poll_interval = _positive_float("POLL_INTERVAL_SECONDS", 5.0, setting)
        max_poll_count = _positive_int("MAX_POLL_COUNT", 60, setting)
        http_timeout = _positive_float("HTTP_TIMEOUT_SECONDS", 30.0, setting)
        search_retry_max_attempts = _positive_int(
            "SEARCH_RETRY_MAX_ATTEMPTS", 3, setting
        )
        search_retry_initial_delay_seconds = _positive_float(
            "SEARCH_RETRY_INITIAL_DELAY_SECONDS", 2.0, setting
        )
        network_failure_threshold = _positive_int(
            "SEARCH_NETWORK_FAILURE_THRESHOLD", 3, setting
        )
        network_recovery_pause_seconds = _positive_float(
            "SEARCH_NETWORK_RECOVERY_PAUSE_SECONDS", 30.0, setting
        )

        # Admin 配置错误只能关闭公共信息采集，不能阻断原 Search 主链路。
        admin_enabled = _env_bool("SEARCH_ADMIN_ENABLED", False, setting)
        admin_config_error = ""
        admin_headers: dict[str, str] = {}
        admin_login_api_url = setting("SEARCH_ADMIN_LOGIN_API_URL").strip()
        admin_api_url = setting("SEARCH_ADMIN_API_URL").strip()
        admin_username = setting("SEARCH_ADMIN_USERNAME").strip()
        admin_password = setting("SEARCH_ADMIN_PASSWORD").strip()
        if admin_enabled:
            try:
                parsed_admin_headers = json.loads(
                    setting("SEARCH_ADMIN_HTTP_HEADERS_JSON", "{}")
                )
                if not isinstance(parsed_admin_headers, dict) or not all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in parsed_admin_headers.items()
                ):
                    raise ValueError("键和值都必须是字符串")
                admin_headers = parsed_admin_headers
            except (json.JSONDecodeError, ValueError):
                admin_config_error = (
                    "SEARCH_ADMIN_HTTP_HEADERS_JSON 必须是合法 JSON 字符串对象"
                )
            missing_admin = [
                name
                for name, value in (
                    ("SEARCH_ADMIN_LOGIN_API_URL", admin_login_api_url),
                    ("SEARCH_ADMIN_API_URL", admin_api_url),
                    ("SEARCH_ADMIN_USERNAME", admin_username),
                    ("SEARCH_ADMIN_PASSWORD", admin_password),
                )
                if not value
            ]
            if missing_admin and not admin_config_error:
                admin_config_error = "缺少 Admin 配置: " + ", ".join(missing_admin)
        try:
            admin_cost_limit = _positive_int(
                "SEARCH_ADMIN_COST_LIMIT", 100, setting
            )
        except ConfigError as exc:
            admin_cost_limit = 100
            if admin_enabled and not admin_config_error:
                admin_config_error = str(exc)

        photo_enabled = _env_bool("SEARCH_PHOTO_ENABLED", False, setting)
        photo_input_dir = (
            setting("SEARCH_PHOTO_INPUT_DIR", "input/input_photos").strip()
            or "input/input_photos"
        )
        photo_host_values = [
            value.strip().lower()
            for value in setting(
                "SEARCH_PHOTO_UPLOAD_HOST_SUFFIXES", ".myqcloud.com"
            ).split(",")
            if value.strip()
        ]
        if photo_enabled and not photo_host_values:
            raise ConfigError(
                "SEARCH_PHOTO_UPLOAD_HOST_SUFFIXES 至少需要一个允许的 COS 域名"
            )
        if photo_enabled and any(
            not value.startswith(".")
            or not re.fullmatch(r"\.[a-z0-9.-]+", value)
            for value in photo_host_values
        ):
            raise ConfigError(
                "SEARCH_PHOTO_UPLOAD_HOST_SUFFIXES 必须是以 . 开头的域名后缀"
            )

        return cls(
            api_url=setting("SEARCH_API_URL").strip(),
            headers=headers,
            auth_token=setting("AUTH_TOKEN").strip(),
            device_id=setting("DEVICE_ID").strip(),
            user_id=setting("USER_ID").strip(),
            poll_interval_seconds=poll_interval,
            max_poll_count=max_poll_count,
            http_timeout_seconds=http_timeout,
            search_retry_max_attempts=search_retry_max_attempts,
            search_retry_initial_delay_seconds=search_retry_initial_delay_seconds,
            network_failure_threshold=network_failure_threshold,
            network_recovery_pause_seconds=network_recovery_pause_seconds,
            platform=setting("PLATFORM", "ios").strip() or "ios",
            app_version=setting("APP_VERSION", "1.0.0").strip() or "1.0.0",
            locale=setting("LOCALE", "zh-Hans-CN").strip() or "zh-Hans-CN",
            timezone=setting("TIMEZONE", "UTC+08:00").strip() or "UTC+08:00",
            input_file=setting("SEARCH_INPUT_FILE", "input/tasks.jsonl").strip()
            or "input/tasks.jsonl",
            output_dir=setting("SEARCH_OUTPUT_DIR", "output").strip() or "output",
            allow_duplicate_run=_env_bool("ALLOW_DUPLICATE_RUN", False, setting),
            admin_enabled=admin_enabled,
            admin_login_api_url=admin_login_api_url,
            admin_api_url=admin_api_url,
            admin_headers=admin_headers,
            admin_username=admin_username,
            admin_password=admin_password,
            admin_reason=setting(
                "SEARCH_ADMIN_REASON", "searchTool 测试数据采集"
            ).strip()
            or "searchTool 测试数据采集",
            admin_debug_service=setting(
                "SEARCH_ADMIN_DEBUG_SERVICE", "worker"
            ).strip()
            or "worker",
            admin_cost_limit=admin_cost_limit,
            admin_config_error=admin_config_error,
            query_log_enabled=_env_bool("SEARCH_QUERY_LOG_ENABLED", True, setting),
            query_log_dir=setting("SEARCH_QUERY_LOG_DIR", "log").strip() or "log",
            query_log_timezone=setting(
                "SEARCH_DISPLAY_TIMEZONE", "Asia/Shanghai"
            ).strip()
            or "Asia/Shanghai",
            photo_enabled=photo_enabled,
            photo_input_dir=photo_input_dir,
            photo_upload_host_suffixes=(
                tuple(photo_host_values)
                if photo_enabled
                else (".myqcloud.com",)
            ),
        )


def _positive_float(
    name: str,
    default: float,
    value_getter: Callable[[str, str], str] = os.getenv,
) -> float:
    raw = value_getter(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是数字") from exc
    if value <= 0:
        raise ConfigError(f"{name} 必须大于 0")
    return value


def _positive_int(
    name: str,
    default: int,
    value_getter: Callable[[str, str], str] = os.getenv,
) -> int:
    raw = value_getter(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数") from exc
    if value <= 0:
        raise ConfigError(f"{name} 必须大于 0")
    return value


def _env_bool(
    name: str,
    default: bool,
    value_getter: Callable[[str, str], str] = os.getenv,
) -> bool:
    """Parse a strict boolean environment setting.

    Args:
        name: Environment variable name.
        default: Value returned when the variable is absent or blank.

    Returns:
        ``True`` for ``true/1/yes/on`` and ``False`` for
        ``false/0/no/off`` (case-insensitive).

    Raises:
        ConfigError: If a non-empty value is not a recognized boolean.
    """

    raw = value_getter(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"true", "1", "yes", "on"}:
        return True
    if raw in {"false", "0", "no", "off"}:
        return False
    raise ConfigError(f"{name} 必须是 true 或 false")


def select_output_paths(
    input_path: Path,
    output_dir: Path,
    allow_duplicate: bool,
    run_date: date | None = None,
) -> tuple[Path, Path]:
    """Choose protected result/failure paths for one search run.

    Args:
        input_path: Selected JSONL input. Only its filename stem is used.
        output_dir: Directory receiving result files.
        allow_duplicate: Whether an existing same-day run may create a new,
            incremented ``runNN`` pair.
        run_date: Date used in filenames. Defaults to the local current date;
            tests inject a fixed date.

    Returns:
        ``(results_path, failures_path)`` using ``YYYYMMDD_input`` naming.

    Raises:
        FileExistsError: If the first pair already exists and duplicate runs are
        disabled. Existing files are never overwritten by this selector.
    """

    date_text = (run_date or date.today()).strftime("%Y%m%d")
    base_prefix = f"{date_text}_{input_path.stem}"

    def paths_for(prefix: str) -> tuple[Path, Path]:
        return (
            output_dir / f"{prefix}_results.jsonl",
            output_dir / f"{prefix}_failures.jsonl",
        )

    first = paths_for(base_prefix)
    if not any(path.exists() for path in first):
        return first
    if not allow_duplicate:
        raise FileExistsError(
            f"同日同输入的结果已存在: {first[0]}。如需新增一次运行，请在 .env 设置 "
            "ALLOW_DUPLICATE_RUN=true"
        )

    run_number = 2
    while True:
        candidate = paths_for(f"{base_prefix}_run{run_number:02d}")
        if not any(path.exists() for path in candidate):
            return candidate
        run_number += 1


class SearchClient:
    def __init__(
        self,
        config: Config,
        session: Any | None = None,
        admin_session: Any | None = None,
        media_session: Any | None = None,
    ) -> None:
        """初始化原 Search Client，并为同一个 Run 持有一个 Admin Session。"""

        self.config = config
        self.session = session or requests.Session()
        self.last_http_status: int | None = None
        self.last_duration_ms: int | None = None
        self.admin_client = AdminClient(config, admin_session)
        # COS 使用独立 Session，避免把 Gateway Cookie 或认证 Header 带到签名 URL。
        self.media_session = media_session or requests.Session()
        self.last_media_http_status: int | None = None
        self.last_media_duration_ms: int | None = None

    def call(
        self,
        method_name: str,
        params: dict[str, Any],
        *,
        service_name: str = SERVICE_NAME,
    ) -> dict[str, Any]:
        """调用统一 HTTP RPC 接口并校验公共业务响应。

        参数说明:
            method_name: Create/Get/List/Detail 的接口方法名。
            params: 当前接口的业务参数。

        返回值:
            已通过 HTTP、顶层 code 和 responses[0] 校验的完整响应对象。

        异常说明:
            FlowError: HTTP、JSON 格式或业务 code 异常时抛出；如果已经取得
            业务响应，会放入异常的 response_body 供 Raw 记录使用。
        """

        payload = {
            "comm": {
                "auth_token": self.config.auth_token,
                "device_id": self.config.device_id,
                "user_id": self.config.user_id,
                "client_request_id": f"crid-{int(time.time() * 1000)}-{uuid.uuid4().hex[:10]}",
                "platform": self.config.platform,
                "app_version": self.config.app_version,
                "locale": self.config.locale,
                "timezone": self.config.timezone,
            },
            "requests": [
                {
                    "id": "req_0",
                    "service_name": service_name,
                    "method_name": method_name,
                    "params": params,
                }
            ],
        }
        headers = {"Content-Type": "application/json", **self.config.headers}

        started_at = time.monotonic()
        self.last_http_status = None
        try:
            response = self.session.post(
                self.config.api_url,
                headers=headers,
                json=payload,
                timeout=self.config.http_timeout_seconds,
            )
            self.last_http_status = getattr(response, "status_code", None)
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            response_body = None
            error_response = getattr(exc, "response", None)
            if error_response is not None:
                try:
                    response_body = error_response.json()
                except (ValueError, TypeError):
                    response_body = None
            flow_error = FlowError(
                method_name,
                f"HTTP 请求失败: {exc}",
                response_body=response_body,
            )
            flow_error.http_status = self.last_http_status
            flow_error.network_error_kind = classify_transport_error(
                exc,
                self.last_http_status,
            )
            raise flow_error from exc
        except (ValueError, TypeError) as exc:
            raise FlowError(method_name, "接口响应不是合法 JSON") from exc
        finally:
            self.last_duration_ms = int((time.monotonic() - started_at) * 1000)

        try:
            return self._validate_response(method_name, body)
        except FlowError as exc:
            # 业务失败响应仍属于可追溯 Raw；只挂到异常，不在客户端保存鉴权请求。
            exc.response_body = body
            exc.http_status = self.last_http_status
            exc.duration_ms = self.last_duration_ms
            raise

    def put_media_binary(
        self,
        upload_url: str,
        upload_headers: dict[str, str],
        content: bytes,
    ) -> int:
        """使用隔离 Session 将 JPEG 原始字节上传到受信任 COS Host。

        功能说明:
            保持 Prepare 返回的签名 URL 原样，不重编码查询参数；请求只携带
            Content-Length 与 Content-Type，且禁止重定向和自动重试。

        参数说明:
            upload_url: Prepare 返回的动态 HTTPS 签名 URL。
            upload_headers: 已与本地字节数核对的两个上传 Header。
            content: 本地 JPEG 原始字节。

        返回值:
            COS 返回的 HTTP 状态码；仅 200、201、204 会正常返回。

        异常说明:
            FlowError: URL 越界、网络失败或 HTTP 状态不受支持时抛出。错误
            文本不会包含完整签名 URL。
        """

        parsed = urlsplit(upload_url)
        hostname = (parsed.hostname or "").lower()
        allowed_suffixes = self.config.photo_upload_host_suffixes
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise FlowError(
                "PutMediaBinary", "COS 上传地址包含非法端口"
            ) from exc
        if (
            parsed.scheme.lower() != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or (parsed_port is not None and parsed_port != 443)
        ):
            raise FlowError("PutMediaBinary", "COS 上传地址必须是合法 HTTPS URL")
        if not any(
            hostname == suffix.lstrip(".") or hostname.endswith(suffix)
            for suffix in allowed_suffixes
        ):
            raise FlowError("PutMediaBinary", "COS 上传地址不属于允许的域名")

        started_at = time.monotonic()
        self.last_media_http_status = None
        cookies = getattr(self.media_session, "cookies", None)
        if cookies is not None and hasattr(cookies, "clear"):
            cookies.clear()
        try:
            response = self.media_session.put(
                upload_url,
                headers={
                    "Content-Length": upload_headers["Content-Length"],
                    "Content-Type": upload_headers["Content-Type"],
                },
                data=content,
                timeout=self.config.http_timeout_seconds,
                allow_redirects=False,
            )
            self.last_media_http_status = getattr(response, "status_code", None)
        except requests.RequestException as exc:
            error = FlowError("PutMediaBinary", "COS PUT 请求失败")
            error.http_status = self.last_media_http_status
            raise error from exc
        finally:
            self.last_media_duration_ms = int(
                (time.monotonic() - started_at) * 1000
            )
        if self.last_media_http_status not in {200, 201, 204}:
            error = FlowError(
                "PutMediaBinary",
                f"COS PUT 返回不受支持的 HTTP 状态: {self.last_media_http_status}",
            )
            error.http_status = self.last_media_http_status
            error.duration_ms = self.last_media_duration_ms
            raise error
        return int(self.last_media_http_status)

    @staticmethod
    def _validate_response(method_name: str, body: Any) -> dict[str, Any]:
        """校验 RPC 公共响应结构并返回原始对象。

        参数说明:
            method_name: 用于错误定位的接口方法名。
            body: HTTP JSON 响应。

        返回值:
            结构及业务状态均合法的原始响应字典。

        异常说明:
            FlowError: 响应不是对象、缺少 data 或任一级业务状态失败。
        """

        if not isinstance(body, dict):
            raise FlowError(method_name, "接口响应必须是 JSON 对象")
        if body.get("code") != 0:
            raise FlowError(
                method_name,
                f"接口返回失败: code={body.get('code')}, message={body.get('message', '')}",
            )
        responses = body.get("responses")
        if not isinstance(responses, list) or not responses or not isinstance(responses[0], dict):
            raise FlowError(method_name, "接口响应缺少 responses[0]")
        item = responses[0]
        if item.get("success") is not True or item.get("code", 0) != 0:
            raise FlowError(
                method_name,
                f"方法返回失败: code={item.get('code')}, message={item.get('message', '')}",
            )
        data = item.get("data")
        if not isinstance(data, dict):
            raise FlowError(method_name, "接口响应缺少 responses[0].data")
        return body


class AdminClient:
    """管理一个 Run 内复用的 Admin 登录会话和公共信息请求。"""

    def __init__(self, config: Config, session: Any | None = None) -> None:
        """保存 Admin 配置和内存 Token；不会持久化任何认证信息。"""

        self.config = config
        self.session = session or requests.Session()
        self.session_token = ""
        self.expire_time: datetime | None = None
        self.operator_id = ""
        self.operator_name = ""
        self.last_http_status: int | None = None
        self.last_duration_ms: int | None = None
        self._audit_events: list[dict[str, Any]] = []
        self._call_attempts: list[dict[str, Any]] = []

    @property
    def available(self) -> bool:
        """返回 Admin 公共信息采集是否已正确配置。"""

        return self.config.admin_enabled and not self.config.admin_config_error

    def drain_audit_events(self) -> list[dict[str, Any]]:
        """返回并清空 Login 脱敏审计事件，供当前 Query 写入 Raw。"""

        events = self._audit_events
        self._audit_events = []
        return events

    def drain_call_attempts(self) -> list[dict[str, Any]]:
        """返回并清空最近一次 Debug/Cost 的请求尝试记录。"""

        attempts = self._call_attempts
        self._call_attempts = []
        return attempts

    def _session_is_fresh(self, now: datetime | None = None) -> bool:
        """判断 Token 是否存在且距离接口失效时间至少还有一小时。"""

        if not self.session_token or self.expire_time is None:
            return False
        current = now or datetime.now(timezone.utc)
        return self.expire_time - current >= ADMIN_REFRESH_WINDOW

    @staticmethod
    def _parse_expire_time(value: Any) -> datetime:
        """解析 Login 的 ISO 时间，并统一转换为 UTC 带时区时间。"""

        if not isinstance(value, str) or not value.strip():
            raise FlowError("AdminLogin", "Login 响应缺少 expire_time")
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise FlowError("AdminLogin", "Login expire_time 格式无效") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _validate_envelope(stage: str, body: Any) -> dict[str, Any]:
        """校验 Admin 公共响应信封并返回 responses[0].data。"""

        if not isinstance(body, dict):
            raise FlowError(stage, "Admin 接口响应必须是 JSON 对象")
        responses = body.get("responses")
        item = responses[0] if isinstance(responses, list) and responses else None
        if body.get("code") != 0 or not isinstance(item, dict):
            raise FlowError(
                stage,
                f"Admin 接口失败: code={body.get('code')}, "
                f"message={body.get('message', '')}",
                response_body=body,
            )
        if item.get("success") is not True or item.get("code", 0) != 0:
            raise FlowError(
                stage,
                f"Admin 方法失败: code={item.get('code')}, "
                f"message={item.get('message', '')}",
                response_body=body,
            )
        data = item.get("data")
        if not isinstance(data, dict):
            raise FlowError(stage, "Admin 响应缺少 responses[0].data", response_body=body)
        return data

    def _post(self, url: str, payload: dict[str, Any], stage: str) -> dict[str, Any]:
        """执行一次 Admin HTTP 请求并记录安全的 HTTP 元数据。"""

        started_at = time.monotonic()
        self.last_http_status = None
        try:
            response = self.session.post(
                url,
                headers={"Content-Type": "application/json", **(self.config.admin_headers or {})},
                json=payload,
                timeout=self.config.http_timeout_seconds,
            )
            self.last_http_status = getattr(response, "status_code", None)
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            response_body = None
            error_response = getattr(exc, "response", None)
            if error_response is not None:
                try:
                    response_body = error_response.json()
                except (ValueError, TypeError):
                    response_body = None
            flow_error = FlowError(
                stage,
                f"Admin HTTP 请求失败: {exc}",
                response_body=response_body,
            )
            flow_error.http_status = self.last_http_status
            raise flow_error from exc
        except (ValueError, TypeError) as exc:
            raise FlowError(stage, "Admin 接口响应不是合法 JSON") from exc
        finally:
            self.last_duration_ms = int((time.monotonic() - started_at) * 1000)
        return body

    def login(self) -> None:
        """使用平台 Secret 中的账号登录，并原子更新进程内 Session。"""

        if not self.available:
            raise FlowError(
                "AdminLogin",
                self.config.admin_config_error or "Admin 公共信息采集未启用",
            )
        payload = {
            "client_request_id": f"admin_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}",
            "method_name": "Login",
            "reason": "",
            "params": {
                "username": self.config.admin_username,
                "password": self.config.admin_password,
            },
        }
        body: Any = None
        try:
            body = self._post(self.config.admin_login_api_url, payload, "AdminLogin")
            data = self._validate_envelope("AdminLogin", body)
            token = data.get("session_token")
            operator = data.get("operator")
            if not isinstance(token, str) or not token:
                raise FlowError("AdminLogin", "Login 响应缺少 session_token")
            if not isinstance(operator, dict):
                raise FlowError("AdminLogin", "Login 响应缺少 operator")
            operator_id = operator.get("operator_id")
            operator_name = operator.get("operator_name")
            if not isinstance(operator_id, str) or not operator_id:
                raise FlowError("AdminLogin", "Login 响应缺少 operator_id")
            if not isinstance(operator_name, str) or not operator_name:
                raise FlowError("AdminLogin", "Login 响应缺少 operator_name")
            expire_time = self._parse_expire_time(data.get("expire_time"))
            self.session_token = token
            self.expire_time = expire_time
            self.operator_id = operator_id
            self.operator_name = operator_name
            self._audit_events.append(
                {
                    "status": "SUCCESS",
                    "expire_time": expire_time.isoformat(),
                    "operator_id": "***",
                    "token_saved": False,
                    "response_summary": {"code": body.get("code"), "message": body.get("message")},
                    "http_status": self.last_http_status,
                    "duration_ms": self.last_duration_ms,
                    "error": "",
                }
            )
        except FlowError as exc:
            self.session_token = ""
            self.expire_time = None
            self.operator_id = ""
            self.operator_name = ""
            self._audit_events.append(
                {
                    "status": "FAILED",
                    "expire_time": None,
                    "operator_id": "***",
                    "token_saved": False,
                    "response_summary": None,
                    "http_status": exc.http_status or self.last_http_status,
                    "duration_ms": exc.duration_ms or self.last_duration_ms,
                    "error": str(exc),
                }
            )
            raise

    def ensure_session(self) -> None:
        """Token 缺失或不足一小时有效期时重新登录。"""

        if not self._session_is_fresh():
            self.login()

    @staticmethod
    def _is_auth_failure(error: FlowError) -> bool:
        """识别 HTTP 401/403 或响应中明确的 Session 认证失败。"""

        if error.http_status in {401, 403}:
            return True
        if isinstance(error.response_body, dict):
            codes = {error.response_body.get("code")}
            responses = error.response_body.get("responses")
            if isinstance(responses, list):
                codes.update(
                    item.get("code")
                    for item in responses
                    if isinstance(item, dict)
                )
            if codes & {401, 403}:
                return True
        body_text = json.dumps(error.response_body, ensure_ascii=False).lower()
        message = f"{error} {body_text}".lower()
        keywords = ("session_token", "session token", "token expired", "未登录", "认证失败")
        return any(keyword in message for keyword in keywords)

    def call(self, method_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """调用 Debug/Cost；认证失效时重新登录并仅重放一次。"""

        self._call_attempts = []
        self.ensure_session()
        last_error: FlowError | None = None
        for attempt in (1, 2):
            payload = {
                "comm": {
                    "device_id": "admin-web",
                    "platform": "web",
                    "app_version": "1.0.0",
                    "trace_id": f"trace_{uuid.uuid4().hex}",
                },
                "requests": [
                    {
                        "id": "req_0",
                        "service_name": ADMIN_SERVICE_NAME,
                        "method_name": method_name,
                        "params": {
                            "session_token": self.session_token,
                            "operator_id": self.operator_id,
                            "operator_name": self.operator_name,
                            "reason": self.config.admin_reason,
                            **params,
                        },
                    }
                ],
            }
            try:
                body = self._post(self.config.admin_api_url, payload, method_name)
                self._validate_envelope(method_name, body)
                self._call_attempts.append(
                    {
                        "attempt": attempt,
                        "response_body": body,
                        "error": "",
                        "http_status": self.last_http_status,
                        "duration_ms": self.last_duration_ms,
                    }
                )
                return body
            except FlowError as exc:
                exc.http_status = exc.http_status or self.last_http_status
                exc.duration_ms = exc.duration_ms or self.last_duration_ms
                last_error = exc
                self._call_attempts.append(
                    {
                        "attempt": attempt,
                        "response_body": exc.response_body,
                        "error": str(exc),
                        "http_status": exc.http_status,
                        "duration_ms": exc.duration_ms,
                    }
                )
                if attempt == 1 and self._is_auth_failure(exc):
                    self.session_token = ""
                    self.expire_time = None
                    self.login()
                    continue
                raise
        assert last_error is not None
        raise last_error


def response_data(body: dict[str, Any], stage: str, task_id: str = "") -> dict[str, Any]:
    try:
        data = body["responses"][0]["data"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FlowError(stage, "接口响应缺少 responses[0].data", task_id) from exc
    if not isinstance(data, dict):
        raise FlowError(stage, "responses[0].data 必须是对象", task_id)
    return data


def extract_admin_task_fields(
    *,
    task_id: str,
    debug_body: dict[str, Any] | None,
    cost_body: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """从两个 Admin 响应提取五个已确认的任务公共字段。

    功能说明:
        依据正式接口口径汇总 LLM、第三方和任务总成本，读取 PDL 调用状态，
        并使用任务开始、结束时间计算检索耗时。成本以接口 microunit 原值
        除以 1,000,000 后保存为 USD，原始微单位同步返回供审计。

    参数说明:
        task_id: 当前检索任务 ID，用于精确匹配 ``by_search``。
        debug_body: ``GetSearchTaskDebug`` 完整响应；缺失时只处理成本。
        cost_body: ``GetProviderCostSummary`` 完整响应；缺失时只处理诊断。

    返回值:
        二元组。第一项是五个标准 ``task_fields``；无法提取的字段为 None，
        Admin 明确确认没有计费调用时成本为 0。第二项是币种、微单位原值、
        字段来源、映射状态和非敏感警告。

    异常说明:
        本函数不因单字段缺失或格式错误中断主链路；错误会写入映射警告。
        只有 Debug 明确 ``cost_complete`` 且成本汇总没有 USD、未计价或部分
        计价记录时，才把无计费结果映射为 0，普通缺失不会伪造成零成本。
    """

    fields: dict[str, Any] = {
        "llm_cost": None,
        "third_party_cost": None,
        "total_cost": None,
        "pdl_called": None,
        "search_duration_ms": None,
    }
    metadata: dict[str, Any] = {
        "cost_currency": None,
        "llm_cost_microunit": None,
        "third_party_cost_microunit": None,
        "total_cost_microunit": None,
        "field_mapping_sources": {},
        "field_mapping_warnings": [],
        "field_mapping_status": "NOT_MAPPED",
    }
    warnings: list[str] = metadata["field_mapping_warnings"]
    sources: dict[str, str] = metadata["field_mapping_sources"]

    def envelope_data(body: dict[str, Any] | None) -> dict[str, Any]:
        """安全取得 Admin ``responses[0].data``，无效响应按缺失处理。"""

        if not isinstance(body, dict):
            return {}
        responses = body.get("responses")
        if not isinstance(responses, list) or not responses:
            return {}
        item = responses[0]
        if not isinstance(item, dict) or item.get("success") is False:
            return {}
        data = item.get("data")
        return data if isinstance(data, dict) else {}

    def microunit(value: Any, field_name: str) -> int | None:
        """把非负整数形式的微单位安全转换为 int。"""

        if isinstance(value, bool) or value is None or value == "":
            return None
        try:
            parsed = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            warnings.append(f"{field_name} 不是合法 microunit")
            return None
        if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
            warnings.append(f"{field_name} 必须是非负整数 microunit")
            return None
        return int(parsed)

    def usd_value(value: int | None) -> float | None:
        """将接口微单位换算成现有报告使用的 USD 数值。"""

        return float(Decimal(value) / Decimal(1_000_000)) if value is not None else None

    def count_value(value: Any) -> int:
        """把计数类接口值转换为非负整数，非法值按 0 处理。"""

        try:
            return max(0, int(Decimal(str(value or 0))))
        except (InvalidOperation, TypeError, ValueError):
            return 0

    diagnosis_cost_complete = False
    debug_data = envelope_data(debug_body)
    debug = debug_data.get("debug")
    if isinstance(debug, dict):
        diagnosis = debug.get("diagnosis")
        if isinstance(diagnosis, dict):
            diagnosis_cost_complete = diagnosis.get("cost_complete") is True
            if isinstance(diagnosis.get("pdl_called"), bool):
                fields["pdl_called"] = diagnosis["pdl_called"]
                sources["pdl_called"] = "debug.diagnosis.pdl_called"

        debug_task = debug.get("task")
        if isinstance(debug_task, dict):
            start_time = debug_task.get("start_time")
            finish_time = debug_task.get("finish_time")
            if isinstance(start_time, str) and isinstance(finish_time, str):
                try:
                    start = datetime.fromisoformat(
                        start_time.strip().replace("Z", "+00:00")
                    )
                    finish = datetime.fromisoformat(
                        finish_time.strip().replace("Z", "+00:00")
                    )
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=timezone.utc)
                    if finish.tzinfo is None:
                        finish = finish.replace(tzinfo=timezone.utc)
                    duration_ms = int(round((finish - start).total_seconds() * 1000))
                    if duration_ms < 0:
                        warnings.append("task.finish_time 早于 task.start_time")
                    else:
                        fields["search_duration_ms"] = duration_ms
                        sources["search_duration_ms"] = (
                            "debug.task.finish_time - debug.task.start_time"
                        )
                except ValueError:
                    warnings.append("task.start_time 或 task.finish_time 格式无效")

    cost_data = envelope_data(cost_body)
    cost_summary = cost_data.get("cost_summary")
    # 兼容接口文档把汇总数组直接放在 data 下的写法；实际响应优先使用
    # data.cost_summary，避免历史 Raw 因包装层差异无法无成本重处理。
    cost_container = cost_summary if isinstance(cost_summary, dict) else cost_data
    by_provider = cost_container.get("by_provider")
    by_search = cost_container.get("by_search")
    totals = cost_container.get("totals")
    provider_rows = by_provider if isinstance(by_provider, list) else []
    search_rows = by_search if isinstance(by_search, list) else []
    total_rows = totals if isinstance(totals, list) else []
    summary_rows = provider_rows + search_rows + total_rows

    llm_values: list[int] = []
    third_party_values: list[int] = []
    excluded_third_party = {
        "llm_search",
        "public_figure",
        "agent_people",
        "search_agent",
    }
    for index, row in enumerate(provider_rows):
        if not isinstance(row, dict) or str(row.get("currency") or "").upper() != "USD":
            continue
        provider = str(row.get("provider") or "").strip().lower()
        if not provider:
            continue
        value = microunit(
            row.get("total_cost_microunit"),
            f"by_provider[{index}].total_cost_microunit",
        )
        if value is None:
            continue
        if provider.startswith("llm_search"):
            llm_values.append(value)
        elif provider not in excluded_third_party:
            third_party_values.append(value)

    if llm_values:
        llm_total = sum(llm_values)
        metadata["llm_cost_microunit"] = llm_total
        fields["llm_cost"] = usd_value(llm_total)
        sources["llm_cost"] = "cost_summary.by_provider[provider^=llm_search]"
    if third_party_values:
        third_party_total = sum(third_party_values)
        metadata["third_party_cost_microunit"] = third_party_total
        fields["third_party_cost"] = usd_value(third_party_total)
        sources["third_party_cost"] = "cost_summary.by_provider[third_party]"

    total_microunit: int | None = None
    for index, row in enumerate(search_rows):
        if not isinstance(row, dict):
            continue
        if str(row.get("task_id") or "") != task_id:
            continue
        if str(row.get("currency") or "").upper() != "USD":
            continue
        total_microunit = microunit(
            row.get("total_cost_microunit"),
            f"by_search[{index}].total_cost_microunit",
        )
        if total_microunit is not None:
            sources["total_cost"] = "cost_summary.by_search[task_id,currency=USD]"
            break
    if total_microunit is None:
        for index, row in enumerate(total_rows):
            if not isinstance(row, dict):
                continue
            if str(row.get("currency") or "").upper() != "USD":
                continue
            total_microunit = microunit(
                row.get("total_cost_microunit"),
                f"totals[{index}].total_cost_microunit",
            )
            if total_microunit is not None:
                sources["total_cost"] = "cost_summary.totals[currency=USD]"
                break
    # 缓存命中或全部非计费时，Admin 会返回完整但没有 USD 行的成本汇总。
    # 该场景是已确认零成本，不是字段缺失；未计价、部分计价或异常 USD 行
    # 仍保持 None，避免把未知成本误写成 0。
    has_usd_row = any(
        isinstance(row, dict)
        and str(row.get("currency") or "").strip().upper() == "USD"
        for row in summary_rows
    )
    has_incomplete_cost_row = any(
        isinstance(row, dict)
        and (
            count_value(row.get("unpriced_call_count")) > 0
            or count_value(row.get("partial_cost_call_count")) > 0
            or row.get("cost_complete") in {False, 0, "0", "false", "False"}
        )
        for row in summary_rows
    )
    confirmed_no_charge = (
        total_microunit is None
        and diagnosis_cost_complete
        and isinstance(cost_summary, dict)
        and not has_usd_row
        and not has_incomplete_cost_row
    )
    if confirmed_no_charge:
        total_microunit = 0
        sources["total_cost"] = (
            "debug.diagnosis.cost_complete + cost_summary[no_usd_charge]"
        )
    if total_microunit is not None:
        metadata["total_cost_microunit"] = total_microunit
        metadata["cost_currency"] = "USD"
        fields["total_cost"] = usd_value(total_microunit)
    elif llm_values or third_party_values:
        metadata["cost_currency"] = "USD"

    # Provider 明细非空时，未出现某一类别表示该类别没有产生费用；任务总成本
    # 明确为 0 时也可确定各类别为真实 0。明细整体缺失且总成本非零时仍保留
    # None，避免把无法分类误写成零成本。
    provider_breakdown_complete = bool(provider_rows) or total_microunit == 0
    if provider_breakdown_complete and total_microunit is not None:
        if fields["llm_cost"] is None:
            fields["llm_cost"] = 0.0
            metadata["llm_cost_microunit"] = 0
            sources["llm_cost"] = "cost_summary.by_provider[no_llm_provider]"
        if fields["third_party_cost"] is None:
            fields["third_party_cost"] = 0.0
            metadata["third_party_cost_microunit"] = 0
            sources["third_party_cost"] = (
                "cost_summary.by_provider[no_third_party_provider]"
            )

    mapped_count = sum(value is not None for value in fields.values())
    if mapped_count == len(fields):
        metadata["field_mapping_status"] = "COMPLETE"
    elif mapped_count:
        metadata["field_mapping_status"] = "PARTIAL"
    tool_usage, provider_level_costs = extract_admin_tool_usage(
        debug_body,
        cost_body,
    )
    metadata["tool_usage_summary"] = tool_usage
    metadata["provider_level_costs"] = provider_level_costs
    # 标准化 Provider 汇总可直接被 FieldSchema、Excel 和报告使用；它涵盖
    # 已知工具、未知 Provider、已计价、未计价和非计费调用，避免仅靠 LLM
    # 或固定工具列导致第三方成本漏记。
    metadata["provider_cost_details"] = sorted(
        provider_level_costs.values(),
        key=lambda item: str(item.get("provider") or "").casefold(),
    )
    # 扁平字段供 FieldSchema 开关与 Excel 使用；完整结构仍保留在
    # tool_usage_summary，避免报告依赖固定 Provider 数量。
    for item in tool_usage:
        key = item["key"]
        metadata[f"{key}_call_count"] = item["call_count"]
        metadata[f"{key}_cost"] = item["cost"]
        metadata[f"{key}_cost_status"] = item["cost_status"]
    pdl_provider = provider_level_costs.get("people_data_labs", {})
    metadata["pdl_provider_cost"] = pdl_provider.get("cost")
    metadata["pdl_provider_cost_status"] = pdl_provider.get("cost_status")
    return fields, metadata


def sanitize_raw(value: Any) -> Any:
    """递归移除 Raw 数据中的鉴权字段并保留其他未知业务字段。

    功能说明:
        Raw 只允许保存接口业务参数和业务响应。该函数会从任意层级移除
        Token、Cookie、Header、Device ID 和 User ID 等敏感键，数组顺序和
        其他未识别字段保持不变。

    参数说明:
        value: 待保存的 JSON 兼容值，可以是对象、数组或标量。

    返回值:
        可安全写入 Raw 的新值；不会原地修改接口返回对象。

    异常说明:
        本函数不主动抛出业务异常；非容器值按原值返回。
    """

    sensitive_keys = {
        "password",
        "session_token",
        "auth_token",
        "authorization",
        "cookie",
        "set_cookie",
        "headers",
        "http_headers",
        "device_id",
        "user_id",
    }
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if normalized_key in sensitive_keys:
                continue
            if normalized_key == "upload_url":
                sanitized[str(key)] = "***SIGNED_UPLOAD_URL***"
                continue
            sanitized[str(key)] = sanitize_raw(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_raw(item) for item in value]
    if isinstance(value, str):
        # 异常文本也可能由 requests 带出签名 URL。只保留可定位的 Host，
        # 不让 COS 路径和签名查询参数进入 Raw、SQLite 或人物日志。
        return re.sub(
            r"https://[^\s?'\"<>]*\.myqcloud\.com/[^\s'\"<>]*",
            "https://***.myqcloud.com/***SIGNED_UPLOAD_URL***",
            value,
            flags=re.IGNORECASE,
        )
    return value


def utc_now_text() -> str:
    """返回带时区的 UTC ISO 8601 时间，用于采集和失败记录。"""

    return datetime.now(timezone.utc).isoformat()


def emit_callback(
    callback: Callable[[dict[str, Any]], None] | None,
    record: dict[str, Any],
) -> None:
    """在配置回调时同步发送记录，未配置时保持旧 CLI 行为。"""

    if callback is not None:
        callback(record)


def resolve_query_stage(item: dict[str, Any]) -> str:
    """解析 v1.3 Query 类型，并兼容未显式配置类型的旧输入。

    参数说明:
        item: 当前 Query 输入对象。

    返回值:
        返回当前支持的 Query Stage。旧输入只按 SOCIAL_LINK 推断，照片类型
        必须显式声明，避免误触发上传。

    异常说明:
        FlowError: 显式 query_stage 不属于 v1.3 MVP 支持范围时抛出。
    """

    query_stage = item.get("query_stage")
    if query_stage is None:
        clues = item.get("clues")
        clue_list = clues if isinstance(clues, list) else []
        clue_types = {
            clue.get("type")
            for clue in clue_list
            if isinstance(clue, dict)
        }
        return "FULL_NAME_SOCIAL" if "SOCIAL_LINK" in clue_types else "FULL_NAME"
    if query_stage not in SUPPORTED_QUERY_STAGES:
        raise FlowError(
            "Input",
            "query_stage 只支持 FULL_NAME、FULL_NAME_SOCIAL、"
            "FULL_NAME_PHOTO 或 FULL_NAME_SOCIAL_PHOTO",
        )
    return query_stage


def build_raw_record(
    *,
    run_id: str,
    input_id: str,
    task_id: str,
    candidate_id: str,
    stage: str,
    sequence_no: int,
    request_params: dict[str, Any],
    response_body: Any,
    error: str = "",
    attempt: int = 1,
    http_status: int | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """构造一条不含鉴权信息的 v1.3 Raw 回调记录。

    参数说明:
        run_id: 当前批次标识。
        input_id: Query 唯一标识。
        task_id: 已取得的接口任务标识，Create 阶段允许为空。
        candidate_id: Candidate Detail 阶段的候选人标识，其他阶段为空。
        stage: 实际接口方法名。
        sequence_no: 同阶段调用顺序，GetTask 从 1 开始。
        request_params: 请求中的业务参数，不包含 comm 和 HTTP Header。
        response_body: 接口完整业务响应；HTTP 无响应时为 None。
        error: 失败时的可读错误，成功时为空字符串。

    返回值:
        可直接交给 RawCallback 或写入 JSONL 的脱敏字典。
    """

    return {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "input_id": input_id,
        "task_id": task_id,
        "candidate_id": candidate_id,
        "stage": stage,
        "sequence_no": sequence_no,
        "request_params": sanitize_raw(request_params),
        "response_body": sanitize_raw(response_body),
        "error": sanitize_raw(error),
        "attempt": attempt,
        "http_status": http_status,
        "duration_ms": duration_ms,
        "business_success": not bool(error),
        "collected_at": utc_now_text(),
    }


def extract_person_name(item: dict[str, Any]) -> str:
    """从 FULL_NAME 线索提取输入人物姓名，缺失时回退 input_id。"""

    for clue in item.get("clues", []):
        if not isinstance(clue, dict) or clue.get("type") != "FULL_NAME":
            continue
        full_name_query = clue.get("full_name_query")
        if isinstance(full_name_query, dict):
            full_name = full_name_query.get("full_name")
            if isinstance(full_name, str) and full_name.strip():
                return full_name.strip()
        value = clue.get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(item.get("input_id") or "unknown")


def safe_log_name(value: str) -> str:
    """清理人物姓名中的路径、控制字符和不安全文件名字符。"""

    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.replace("..", "_").strip("._")
    return cleaned[:120] or "unknown"


class QueryChainLogger:
    """按日期、Run 和输入人物分层保存脱敏请求与响应日志。"""

    def __init__(
        self,
        *,
        enabled: bool,
        directory: Path,
        run_id: str,
        run_name: str,
        input_id: str,
        person_name: str,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        """安全创建日期/Run 分层目录和不覆盖的日志文件。"""

        self.enabled = enabled
        self.run_id = run_id
        self.run_name = run_name or run_id
        self.input_id = input_id
        self.person_name = person_name
        try:
            self.timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            self.timezone = ZoneInfo("Asia/Shanghai")
        self.path: Path | None = None
        self.handle: Any = None
        self.error = ""
        self._sequence = 0
        if not enabled:
            return
        try:
            created_at = datetime.now(self.timezone)
            date_text = created_at.strftime("%Y-%m-%d")
            time_text = created_at.strftime("%H%M%S")
            microsecond_text = created_at.strftime("%f")
            # Run 名称与人物名称共用同一套路径清理规则，避免用户输入的
            # 分隔符、控制字符或 ``..`` 逃逸日志根目录。
            run_directory = directory / date_text / safe_log_name(self.run_name)
            run_directory.mkdir(parents=True, exist_ok=True)
            safe_person = safe_log_name(person_name)
            safe_input = safe_log_name(input_id)
            filename_prefix = f"{date_text}_{time_text}_{safe_person}"
            candidates = [
                run_directory / f"{filename_prefix}.log",
                run_directory / f"{filename_prefix}_{safe_input}.log",
            ]
            candidates.append(
                run_directory
                / f"{filename_prefix}_{safe_input}_{microsecond_text}.log"
            )
            for candidate in candidates:
                try:
                    self.handle = candidate.open("x", encoding="utf-8")
                    self.path = candidate
                    break
                except FileExistsError:
                    continue
            if self.handle is None:
                for number in range(2, 10000):
                    candidate = run_directory / (
                        f"{filename_prefix}_{safe_input}_{microsecond_text}_{number:02d}.log"
                    )
                    try:
                        self.handle = candidate.open("x", encoding="utf-8")
                        self.path = candidate
                        break
                    except FileExistsError:
                        continue
            if self.handle is None:
                raise OSError("无法分配不重复的人物日志文件名")
        except OSError as exc:
            self.error = f"人物日志创建失败: {exc}"
            self.enabled = False

    def write_event(self, stage: str, **values: Any) -> None:
        """按事件标题、格式化请求 JSON 和响应 JSON 追加并立即 flush。

        功能说明:
            人物日志面向人工排障，不再把整个事件压缩为单行 JSONL。请求与
            响应分别展示，HTTP 状态、耗时和重试次数放在标题中；所有内容仍
            经过 ``sanitize_raw`` 脱敏。

        参数说明:
            stage: 当前 Query 或接口阶段。
            values: task/candidate、HTTP 元数据、请求、响应和错误信息。

        返回值:
            无。写入成功后立即刷新文件缓冲区。

        异常说明:
            文件写入失败不会中断检索，只会在 ``error`` 中记录原因并停止继续写。
        """

        if not self.enabled or self.handle is None:
            return
        self._sequence += 1
        now = datetime.now(self.timezone)
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        api_sequence_no = values.pop("api_sequence_no", None)
        task_id = values.pop("task_id", "")
        candidate_id = values.pop("candidate_id", "")
        attempt = values.pop("attempt", 1)
        http_status = values.pop("http_status", None)
        business_success = values.pop("business_success", True)
        duration_ms = values.pop("duration_ms", None)
        request_data = sanitize_raw(values.pop("request", {}))
        response_data_value = sanitize_raw(values.pop("response", {}))
        error = str(values.pop("error", ""))
        event_data = {
            "sequence_no": self._sequence,
            "api_sequence_no": api_sequence_no,
            "run_id": self.run_id,
            "run_name": self.run_name,
            "input_id": self.input_id,
            "person_name": self.person_name,
            "task_id": task_id,
            "candidate_id": candidate_id,
            "stage": stage,
            "attempt": attempt,
            "business_success": business_success,
            **sanitize_raw(values),
        }
        try:
            self.handle.write(
                f"{timestamp} | INFO | search_tool.QueryChainLogger | "
                f"{stage} 事件:\n"
            )
            json.dump(event_data, self.handle, ensure_ascii=False, indent=2)
            self.handle.write("\n")
            if request_data not in (None, {}, []):
                self.handle.write(
                    f"{timestamp} | INFO | search_tool.QueryChainLogger | "
                    f"{stage} 脱敏请求数据: attempt={attempt}\n"
                )
                json.dump(request_data, self.handle, ensure_ascii=False, indent=2)
                self.handle.write("\n")
            if response_data_value not in (None, {}, []):
                status_text = http_status if http_status is not None else "-"
                duration_text = duration_ms if duration_ms is not None else "-"
                self.handle.write(
                    f"{timestamp} | INFO | search_tool.QueryChainLogger | "
                    f"{stage} 响应数据: HTTP {status_text} "
                    f"elapsed_ms={duration_text}\n"
                )
                json.dump(
                    response_data_value,
                    self.handle,
                    ensure_ascii=False,
                    indent=2,
                )
                self.handle.write("\n")
            if error:
                self.handle.write(
                    f"{timestamp} | ERROR | search_tool.QueryChainLogger | "
                    f"{stage} 失败: {error}\n"
                )
            self.handle.write("\n")
            self.handle.flush()
        except OSError as exc:
            self.error = f"人物日志写入失败: {exc}"
            self.enabled = False

    def write_raw(self, record: dict[str, Any]) -> None:
        """把统一 Raw 事件转换成人物日志格式，避免第二套脱敏口径。"""

        self.write_event(
            str(record.get("stage") or "Unknown"),
            api_sequence_no=record.get("sequence_no", 1),
            task_id=record.get("task_id", ""),
            candidate_id=record.get("candidate_id", ""),
            attempt=record.get("attempt", 1),
            http_status=record.get("http_status"),
            business_success=record.get("business_success", not bool(record.get("error"))),
            duration_ms=record.get("duration_ms"),
            request=record.get("request_params", {}),
            response=record.get("response_body"),
            error=record.get("error", ""),
        )

    def close(self) -> None:
        """关闭日志句柄；关闭失败仅保存错误文本。"""

        if self.handle is not None:
            try:
                self.handle.close()
            except OSError as exc:
                self.error = f"人物日志关闭失败: {exc}"
            finally:
                self.handle = None


def validate_input(item: Any, line_number: int, seen_ids: set[str]) -> dict[str, Any]:
    """校验单条 CLI 输入，并保留照片执行所需的白名单字段。

    功能说明:
        保持旧 Query 输入兼容，同时确保照片执行线显式提供 photo_path，且
        输入无法绕过上传流程预置 PHOTO clue。

    参数说明:
        item: JSONL 当前行解析结果。
        line_number: 用于错误定位的行号。
        seen_ids: 当前文件已经出现的 input_id 集合。

    返回值:
        可直接交给 process_one 的规范化 Query 对象。

    异常说明:
        FlowError: 字段结构、Stage 组合或照片字段不符合契约时抛出。
    """

    if not isinstance(item, dict):
        raise FlowError("Input", f"第 {line_number} 行必须是 JSON 对象")
    input_id = item.get("input_id")
    if not isinstance(input_id, str) or not input_id.strip():
        raise FlowError("Input", f"第 {line_number} 行缺少非空 input_id")
    if input_id in seen_ids:
        raise FlowError("Input", f"第 {line_number} 行 input_id 重复: {input_id}")
    seen_ids.add(input_id)

    clues = item.get("clues")
    if not isinstance(clues, list) or not clues:
        raise FlowError("Input", f"第 {line_number} 行 clues 必须是非空数组")
    clue_types = {
        clue.get("type") for clue in clues if isinstance(clue, dict)
    }
    if "PHOTO" in clue_types:
        raise FlowError(
            "Input",
            f"第 {line_number} 行不得预置 PHOTO clue，media_asset_id 必须运行时生成",
        )
    additional_details = item.get("additional_details", [])
    if not isinstance(additional_details, list):
        raise FlowError("Input", f"第 {line_number} 行 additional_details 必须是数组")
    match_strategy = item.get("match_strategy", "UNION")
    if not isinstance(match_strategy, str) or not match_strategy:
        raise FlowError("Input", f"第 {line_number} 行 match_strategy 必须是非空字符串")
    query_stage = resolve_query_stage(item)
    photo_path = item.get("photo_path")
    if query_stage in PHOTO_QUERY_STAGES:
        if not isinstance(photo_path, str) or not photo_path.strip():
            raise FlowError(
                "Input",
                f"第 {line_number} 行 {query_stage} 必须提供非空 photo_path",
            )
        if "FULL_NAME" not in clue_types:
            raise FlowError(
                "Input",
                f"第 {line_number} 行 {query_stage} 缺少 FULL_NAME 线索",
            )
        if query_stage in SOCIAL_QUERY_STAGES and "SOCIAL_LINK" not in clue_types:
            raise FlowError(
                "Input",
                f"第 {line_number} 行 {query_stage} 缺少 SOCIAL_LINK 线索",
            )
        if query_stage == "FULL_NAME_PHOTO" and "SOCIAL_LINK" in clue_types:
            raise FlowError(
                "Input",
                f"第 {line_number} 行姓名、Social 与照片组合请使用 "
                "FULL_NAME_SOCIAL_PHOTO",
            )
    elif photo_path not in (None, ""):
        raise FlowError(
            "Input",
            f"第 {line_number} 行只有 FULL_NAME_PHOTO 或 "
            "FULL_NAME_SOCIAL_PHOTO 可以提供 photo_path",
        )
    elif query_stage in SOCIAL_QUERY_STAGES and "SOCIAL_LINK" not in clue_types:
        raise FlowError(
            "Input",
            f"第 {line_number} 行 {query_stage} 缺少 SOCIAL_LINK 线索",
        )

    normalized = {
        "input_id": input_id,
        "query_stage": query_stage,
        "clues": clues,
        "additional_details": additional_details,
        "match_strategy": match_strategy,
    }
    if query_stage in PHOTO_QUERY_STAGES:
        normalized["photo_path"] = photo_path.strip()
    return normalized


def read_jsonl(path: Path) -> Iterable[tuple[int, Any, str | None]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                yield line_number, json.loads(line), None
            except json.JSONDecodeError as exc:
                yield line_number, None, f"第 {line_number} 行 JSON 格式错误: {exc.msg}"


def load_photo_input(
    item: dict[str, Any],
    config: Config,
) -> tuple[bytes, dict[str, Any]]:
    """安全读取照片 Query 的本地 JPEG，并生成不含绝对路径的摘要。

    功能说明:
        将 photo_path 限制在配置目录内，拒绝绝对路径、路径穿越和符号链接，
        并通过 JPEG SOI/EOI 签名做首版基础格式校验。EXIF 不解析、不清理。

    参数说明:
        item: 已通过结构校验的照片 Query。
        config: 当前 Run 最新配置，提供照片开关和根目录。

    返回值:
        ``(原始 JPEG 字节, 安全照片摘要)``。

    异常说明:
        FlowError: 功能未启用、路径越界、文件不可读或格式不合法时抛出。
    """

    if not config.photo_enabled:
        raise FlowError("PhotoValidation", "照片检索功能未启用")
    raw_path = str(item.get("photo_path") or "").strip()
    relative_path = Path(raw_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise FlowError("PhotoValidation", "photo_path 必须是照片目录内的相对路径")
    if relative_path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise FlowError("PhotoValidation", "首版照片只支持 .jpg 或 .jpeg")

    configured_root = Path(config.photo_input_dir)
    if not configured_root.is_absolute():
        configured_root = PROJECT_ROOT / configured_root
    try:
        root = configured_root.resolve(strict=True)
    except OSError as exc:
        raise FlowError("PhotoValidation", "配置的照片目录不存在或不可访问") from exc

    # PRD 示例使用 input_photos/name.jpg；配置本身也可能已经指向该目录。
    # 两种写法统一到同一个根目录，兼容 CLI 与 Dataset 历史约定。
    effective_parts = relative_path.parts
    if effective_parts and effective_parts[0] == root.name:
        effective_parts = effective_parts[1:]
    if not effective_parts:
        raise FlowError("PhotoValidation", "photo_path 未指向具体 JPEG 文件")
    unresolved = root.joinpath(*effective_parts)
    cursor = root
    for part in effective_parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise FlowError("PhotoValidation", "photo_path 不允许经过符号链接")
    try:
        resolved = unresolved.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise FlowError("PhotoValidation", "photo_path 不存在或超出照片目录") from exc
    if not resolved.is_file():
        raise FlowError("PhotoValidation", "photo_path 必须指向普通文件")
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise FlowError("PhotoValidation", "照片文件不可读") from exc
    if len(content) < 4 or not content.startswith(b"\xff\xd8") or not content.endswith(b"\xff\xd9"):
        raise FlowError("PhotoValidation", "照片内容不是有效的 JPEG 基础格式")

    return content, {
        "photo_path": raw_path,
        "content_type": "image/jpeg",
        "content_length": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "config_version": None,
        "media_asset_id": None,
        "upload_status": "validated",
    }


def validate_media_config(data: dict[str, Any]) -> dict[str, Any]:
    """校验 GetMediaUploadConfig 中首版执行依赖的字段。"""

    allowed = data.get("allowed_content_types")
    max_size = data.get("max_size_bytes")
    retry = data.get("complete_retry")
    if not isinstance(allowed, list) or "image/jpeg" not in allowed:
        raise FlowError("GetMediaUploadConfig", "媒体配置不允许 image/jpeg")
    if not isinstance(max_size, int) or isinstance(max_size, bool) or max_size <= 0:
        raise FlowError("GetMediaUploadConfig", "媒体配置 max_size_bytes 非法")
    if not isinstance(retry, dict):
        raise FlowError("GetMediaUploadConfig", "媒体配置缺少 complete_retry")
    values: dict[str, int] = {}
    for key in ("initial_delay_ms", "max_attempts", "max_delay_ms"):
        value = retry.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise FlowError("GetMediaUploadConfig", f"complete_retry.{key} 非法")
        values[key] = value
    return {
        "max_size_bytes": max_size,
        "config_version": str(data.get("config_version") or ""),
        "strip_exif": data.get("strip_exif"),
        "complete_retry": values,
    }


def validate_prepare_data(
    data: dict[str, Any],
    *,
    content_length: int,
    config_max_size: int,
) -> dict[str, Any]:
    """交叉校验 Prepare 响应，防止大小、MIME 或上传目标错配。"""

    media_asset_id = data.get("media_asset_id")
    upload_url = data.get("upload_url")
    headers = data.get("upload_headers")
    if not isinstance(media_asset_id, str) or not media_asset_id:
        raise FlowError("PrepareMediaUpload", "响应缺少 media_asset_id")
    if not isinstance(upload_url, str) or not upload_url:
        raise FlowError("PrepareMediaUpload", "响应缺少 upload_url")
    if data.get("upload_method") != "PUT":
        raise FlowError("PrepareMediaUpload", "upload_method 必须为 PUT")
    if data.get("status") != "pending":
        raise FlowError("PrepareMediaUpload", "Prepare 状态必须为 pending")
    if not isinstance(headers, dict):
        raise FlowError("PrepareMediaUpload", "响应缺少 upload_headers")
    content_type = headers.get("Content-Type")
    try:
        header_length = int(headers.get("Content-Length"))
        response_size = int(data.get("size_bytes"))
        prepare_max_size = int(data.get("max_size_bytes"))
        expires_time = int(data.get("expires_time"))
    except (TypeError, ValueError) as exc:
        raise FlowError("PrepareMediaUpload", "响应中的大小或过期时间非法") from exc
    if content_type != "image/jpeg" or data.get("content_type") != "image/jpeg":
        raise FlowError("PrepareMediaUpload", "Prepare 返回的 Content-Type 不一致")
    if len({header_length, response_size, content_length}) != 1:
        raise FlowError("PrepareMediaUpload", "Prepare 返回的 Content-Length 与文件不一致")
    if content_length > config_max_size or content_length > prepare_max_size:
        raise FlowError("PrepareMediaUpload", "照片大小超过媒体配置限制")
    if expires_time <= int(time.time() * 1000):
        raise FlowError("PrepareMediaUpload", "COS 上传签名已经过期")
    return {
        "media_asset_id": media_asset_id,
        "upload_url": upload_url,
        "upload_headers": {
            "Content-Length": str(header_length),
            "Content-Type": "image/jpeg",
        },
        "size_bytes": response_size,
    }


def build_create_clues(
    item: dict[str, Any],
    media_asset_id: str | None = None,
) -> list[dict[str, Any]]:
    """深拷贝输入 clues，并为照片 Query 追加当前上传生成的 PHOTO clue。"""

    clues = copy.deepcopy(item["clues"])
    if any(
        isinstance(clue, dict) and clue.get("type") == "PHOTO"
        for clue in clues
    ):
        raise FlowError(
            "Input",
            "输入不得预置 PHOTO clue，media_asset_id 必须由当前 Query 上传生成",
        )
    if item.get("query_stage") in PHOTO_QUERY_STAGES:
        if not media_asset_id:
            raise FlowError("CreateIntentTask", "照片 Query 缺少 media_asset_id")
        clues.append(
            {
                "type": "PHOTO",
                "photo_query": {
                    "media_asset_id": media_asset_id,
                    "photo_type_hint": "face",
                },
            }
        )
    return clues


def process_one(
    item: dict[str, Any],
    client: SearchClient,
    sleep_fn: Callable[[float], None] = time.sleep,
    progress_callback: ProgressCallback | None = None,
    raw_callback: RawCallback | None = None,
    failure_callback: FailureCallback | None = None,
    run_id: str = "",
    run_name: str = "",
) -> dict[str, Any]:
    """顺序执行单条检索流程并生成向后兼容的 v1.3 结果记录。

    参数说明:
        item: 已校验的 CreateIntentTask 参数，包含唯一 ``input_id``。
        client: 按顺序调用四个接口的同步客户端。
        sleep_fn: GetTask 轮询等待函数，测试时可注入无等待实现。
        progress_callback: 可选进度回调，只发送业务标识、阶段和状态。
        raw_callback: 可选 Raw 回调，每次接口调用后发送脱敏业务请求与响应。
        failure_callback: 可选候选级失败回调，用于写入 failures.jsonl。
        run_id: 当前运行标识；未提供时为直接调用自动生成。
        run_name: 日志目录使用的 Run 显示名称；未提供时回退 ``run_id``。

    返回值:
        v1.3 结果字典。保留旧的 input/task/count/results 字段，并新增
        Query 状态、详情成功/失败数、完整 Raw、List 原项和详情状态。

    异常说明:
        FlowError: Create/Get/List 的 Query 级错误仍向上抛出；单个 Candidate
        Detail 错误在循环内隔离、记录后继续处理下一候选人。
    """

    input_id = item["input_id"]
    effective_run_id = run_id or f"run_{uuid.uuid4().hex}"
    task_id = ""
    candidate_count_total: int | None = None
    raw_records: list[dict[str, Any]] = []
    admin_login_sequence = 0
    final_log_status = "FAILED"
    final_log_error = ""
    final_log_candidate_count = 0
    log_directory = Path(getattr(client.config, "query_log_dir", "log"))
    if not log_directory.is_absolute():
        # 相对路径固定从项目根目录解析，避免从父目录用绝对脚本路径启动时
        # 把人物日志误写到其他项目的同名目录。
        log_directory = PROJECT_ROOT / log_directory
    chain_logger = QueryChainLogger(
        enabled=bool(getattr(client.config, "query_log_enabled", False)),
        directory=log_directory,
        run_id=effective_run_id,
        run_name=run_name or effective_run_id,
        input_id=input_id,
        person_name=extract_person_name(item),
        timezone_name=str(
            getattr(client.config, "query_log_timezone", "Asia/Shanghai")
        ),
    )
    chain_logger.write_event(
        "QueryStart",
        request=sanitize_raw(item),
        business_success=True,
    )

    def emit_progress(event: str, **values: Any) -> None:
        """补齐通用标识后发送单条进度事件。"""

        emit_callback(
            progress_callback,
            {
                "event": event,
                "run_id": effective_run_id,
                "input_id": input_id,
                "task_id": task_id,
                **values,
            },
        )

    def call_and_record(
        stage: str,
        params: dict[str, Any],
        *,
        sequence_no: int = 1,
        candidate_id: str = "",
        service_name: str = SERVICE_NAME,
        attempt: int = 1,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """调用 Search RPC，并按接口幂等性执行有限网络重试。

        只读接口允许重试全部临时传输错误；Create 只允许重试明确 DNS
        解析失败。每次失败和最终成功都会分别写入 Raw 与人物日志。
        """

        configured_attempts = int(
            getattr(client.config, "search_retry_max_attempts", 3)
        )
        max_attempts = (
            configured_attempts
            if stage in READ_ONLY_RETRY_STAGES or stage == "CreateIntentTask"
            else 1
        )
        initial_delay = float(
            getattr(client.config, "search_retry_initial_delay_seconds", 2.0)
        )
        current_attempt = attempt
        final_attempt = attempt + max_attempts - 1
        while current_attempt <= final_attempt:
            try:
                if service_name == SERVICE_NAME:
                    # 保持旧测试 Client 和普通检索调用签名完全兼容。
                    body = client.call(stage, params)
                else:
                    body = client.call(stage, params, service_name=service_name)
            except FlowError as exc:
                record = build_raw_record(
                    run_id=effective_run_id,
                    input_id=input_id,
                    task_id=task_id or exc.task_id,
                    candidate_id=candidate_id,
                    stage=stage,
                    sequence_no=sequence_no,
                    request_params=params,
                    response_body=exc.response_body,
                    error=str(exc),
                    attempt=current_attempt,
                    http_status=exc.http_status
                    or getattr(client, "last_http_status", None),
                    duration_ms=exc.duration_ms
                    or getattr(client, "last_duration_ms", None),
                )
                raw_records.append(record)
                emit_callback(raw_callback, record)
                chain_logger.write_raw(record)
                retryable = (
                    stage in READ_ONLY_RETRY_STAGES
                    and is_network_flow_error(exc)
                ) or (
                    stage == "CreateIntentTask"
                    and exc.network_error_kind == "DNS"
                )
                if not retryable or current_attempt >= final_attempt:
                    raise
                delay_seconds = initial_delay * (2 ** (current_attempt - attempt))
                emit_progress(
                    "request_retry",
                    stage=stage,
                    status="RETRYING",
                    attempt=current_attempt + 1,
                    message=(
                        f"{stage} 网络异常，{delay_seconds:g} 秒后重试 "
                        f"({current_attempt + 1}/{final_attempt})"
                    ),
                )
                sleep_fn(delay_seconds)
                current_attempt += 1
                continue

            record_task_id = task_id
            if stage == "CreateIntentTask" and not record_task_id:
                create_task_id = body.get("responses", [{}])[0].get("data", {}).get(
                    "task_id"
                )
                if isinstance(create_task_id, str):
                    record_task_id = create_task_id
            record = build_raw_record(
                run_id=effective_run_id,
                input_id=input_id,
                task_id=record_task_id,
                candidate_id=candidate_id,
                stage=stage,
                sequence_no=sequence_no,
                request_params=params,
                response_body=body,
                attempt=current_attempt,
                http_status=getattr(client, "last_http_status", None),
                duration_ms=getattr(client, "last_duration_ms", None),
            )
            raw_records.append(record)
            emit_callback(raw_callback, record)
            chain_logger.write_raw(record)
            return body, record

        raise AssertionError("Search RPC 重试循环未返回结果")

    def emit_admin_login_records() -> list[dict[str, Any]]:
        """把 AdminClient 产生的脱敏 Login 摘要接入统一 Raw 与人物日志。"""

        nonlocal admin_login_sequence
        records: list[dict[str, Any]] = []
        for event in client.admin_client.drain_audit_events():
            admin_login_sequence += 1
            record = build_raw_record(
                run_id=effective_run_id,
                input_id=input_id,
                task_id=task_id,
                candidate_id="",
                stage="AdminLogin",
                sequence_no=admin_login_sequence,
                request_params={
                    "method_name": "Login",
                    "username": "***",
                    "password": "***",
                },
                response_body={
                    "status": event.get("status"),
                    "expire_time": event.get("expire_time"),
                    "operator_id": "***",
                    "token_saved": False,
                    "response_summary": event.get("response_summary"),
                },
                error=str(event.get("error") or ""),
                http_status=event.get("http_status"),
                duration_ms=event.get("duration_ms"),
            )
            raw_records.append(record)
            emit_callback(raw_callback, record)
            chain_logger.write_raw(record)
            emit_progress(
                "query_stage",
                stage="AdminLogin",
                status=str(event.get("status") or "FAILED"),
                message=(
                    "Admin Session 已更新"
                    if event.get("status") == "SUCCESS"
                    else "Admin Session 获取失败"
                ),
            )
            records.append(record)
        return records

    def call_admin_and_record(
        stage: str,
        params: dict[str, Any],
        *,
        sequence_no: int = 1,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """调用 Admin 接口并独立记录 Login、请求、响应和错误。"""

        def emit_attempt_records() -> list[dict[str, Any]]:
            """把 AdminClient 内部认证重放的每次尝试都落为独立 Raw。"""

            records: list[dict[str, Any]] = []
            for attempt_event in client.admin_client.drain_call_attempts():
                attempt = int(attempt_event.get("attempt") or 1)
                record = build_raw_record(
                    run_id=effective_run_id,
                    input_id=input_id,
                    task_id=task_id,
                    candidate_id="",
                    stage=stage,
                    sequence_no=sequence_no,
                    request_params=params,
                    response_body=attempt_event.get("response_body"),
                    error=str(attempt_event.get("error") or ""),
                    attempt=attempt,
                    http_status=attempt_event.get("http_status"),
                    duration_ms=attempt_event.get("duration_ms"),
                )
                raw_records.append(record)
                emit_callback(raw_callback, record)
                chain_logger.write_raw(record)
                records.append(record)
            return records

        try:
            body = client.admin_client.call(stage, params)
        except FlowError as exc:
            emit_admin_login_records()
            records = emit_attempt_records()
            if not records:
                record = build_raw_record(
                    run_id=effective_run_id,
                    input_id=input_id,
                    task_id=task_id,
                    candidate_id="",
                    stage=stage,
                    sequence_no=sequence_no,
                    request_params=params,
                    response_body=exc.response_body,
                    error=str(exc),
                    http_status=exc.http_status or client.admin_client.last_http_status,
                    duration_ms=exc.duration_ms or client.admin_client.last_duration_ms,
                )
                raw_records.append(record)
                emit_callback(raw_callback, record)
                chain_logger.write_raw(record)
            raise
        emit_admin_login_records()
        records = emit_attempt_records()
        if not records:
            raise FlowError(stage, "Admin 请求未产生调用记录", task_id)
        return body, records[-1]

    def raw_payload(record: dict[str, Any]) -> dict[str, Any]:
        """提取适合嵌入 results.jsonl 的请求、响应和顺序字段。"""

        return {
            "sequence_no": record["sequence_no"],
            "request_params": record["request_params"],
            "response_body": record["response_body"],
            "error": record["error"],
            "attempt": record.get("attempt", 1),
            "http_status": record.get("http_status"),
            "duration_ms": record.get("duration_ms"),
            "business_success": record.get("business_success"),
            "collected_at": record["collected_at"],
        }

    def collect_public_info() -> dict[str, Any]:
        """顺序采集 Debug 和 Cost；任何辅助失败都转换为状态而不抛出。"""

        public_fields: dict[str, Any] = {
            "public_info_status": "NOT_CONFIGURED",
            "debug_collection_status": "NOT_CONFIGURED",
            "cost_collection_status": "NOT_CONFIGURED",
            "cache_hit": None,
            "public_info_warnings": [],
            "field_mapping_status": "NOT_MAPPED",
        }
        result: dict[str, Any] = {
            "public_fields": public_fields,
            "debug_record": None,
            "cost_record": None,
            "debug_body": None,
            "cost_body": None,
            "login_records": [],
        }
        admin_enabled = bool(getattr(client.config, "admin_enabled", False))
        admin_config_error = str(
            getattr(client.config, "admin_config_error", "") or ""
        )
        if not admin_enabled or admin_config_error:
            unavailable_reason = (
                admin_config_error or "Admin 公共信息采集未启用或未配置"
            )
            if admin_config_error:
                public_fields["public_info_warnings"].append(
                    admin_config_error
                )
            for skipped_stage in (
                "AdminLogin",
                "GetSearchTaskDebug",
                "GetProviderCostSummary",
            ):
                chain_logger.write_event(
                    skipped_stage,
                    task_id=task_id,
                    business_success=False,
                    response={
                        "status": "NOT_CONFIGURED",
                        "executed": False,
                        "reason": unavailable_reason,
                    },
                    error=f"未执行: {unavailable_reason}",
                )
                emit_progress(
                    "query_stage",
                    stage=skipped_stage,
                    status="NOT_CONFIGURED",
                    message=f"{skipped_stage} 未执行：{unavailable_reason}",
                )
            return result

        debug_body: dict[str, Any] | None = None
        cost_body: dict[str, Any] | None = None
        debug_error: FlowError | None = None
        cost_error: FlowError | None = None
        emit_progress(
            "query_stage",
            stage="GetSearchTaskDebug",
            status="RUNNING",
            message="正在采集任务诊断信息",
        )
        try:
            debug_body, debug_record = call_admin_and_record(
                "GetSearchTaskDebug",
                {
                    "task_id": task_id,
                    "service": getattr(client.config, "admin_debug_service", "worker"),
                },
            )
            result["debug_record"] = debug_record
            result["debug_body"] = debug_body
            public_fields["debug_collection_status"] = "SUCCESS"
            emit_progress(
                "query_stage",
                stage="GetSearchTaskDebug",
                status="SUCCEEDED",
                message="任务诊断信息采集完成",
            )
        except FlowError as exc:
            debug_error = exc
            public_fields["debug_collection_status"] = (
                "AUTH_FAILED" if exc.stage == "AdminLogin" else "FAILED"
            )
            public_fields["public_info_warnings"].append(
                f"GetSearchTaskDebug: {exc}"
            )
            emit_progress(
                "query_stage",
                stage="GetSearchTaskDebug",
                status="FAILED",
                message="任务诊断信息采集失败，继续主检索链路",
            )

        # Login 本身失败时，立即再次登录只会重复同一认证错误；Cost 记录为 AUTH_FAILED。
        if debug_error is not None and debug_error.stage == "AdminLogin":
            public_fields["cost_collection_status"] = "AUTH_FAILED"
            chain_logger.write_event(
                "GetProviderCostSummary",
                task_id=task_id,
                business_success=False,
                response={
                    "status": "AUTH_FAILED",
                    "executed": False,
                    "reason": "Admin 登录失败",
                },
                error="未执行: Admin 登录失败",
            )
            emit_progress(
                "query_stage",
                stage="GetProviderCostSummary",
                status="AUTH_FAILED",
                message="Admin 登录失败，成本接口未执行",
            )
        else:
            emit_progress(
                "query_stage",
                stage="GetProviderCostSummary",
                status="RUNNING",
                message="正在采集 Provider 成本信息",
            )
            try:
                cost_body, cost_record = call_admin_and_record(
                    "GetProviderCostSummary",
                    {
                        "task_id": task_id,
                        "limit": int(getattr(client.config, "admin_cost_limit", 100)),
                    },
                )
                cost_data = response_data(
                    cost_body,
                    "GetProviderCostSummary",
                    task_id,
                )
                if not isinstance(cost_data.get("cost_summary"), dict):
                    # 首次空响应允许一次短重试；不重复终态后的固定 1 秒等待。
                    sleep_fn(PUBLIC_INFO_TERMINAL_DELAY_SECONDS)
                    cost_body, cost_record = call_admin_and_record(
                        "GetProviderCostSummary",
                        {
                            "task_id": task_id,
                            "limit": int(getattr(client.config, "admin_cost_limit", 100)),
                        },
                        sequence_no=2,
                    )
                result["cost_record"] = cost_record
                result["cost_body"] = cost_body
                public_fields["cost_collection_status"] = "SUCCESS"
                emit_progress(
                    "query_stage",
                    stage="GetProviderCostSummary",
                    status="SUCCEEDED",
                    message="Provider 成本信息采集完成",
                )
            except FlowError as exc:
                cost_error = exc
                public_fields["cost_collection_status"] = (
                    "AUTH_FAILED" if exc.stage == "AdminLogin" else "FAILED"
                )
                public_fields["public_info_warnings"].append(
                    f"GetProviderCostSummary: {exc}"
                )
                emit_progress(
                    "query_stage",
                    stage="GetProviderCostSummary",
                    status="FAILED",
                    message="Provider 成本信息采集失败，继续主检索链路",
                )

        login_records = [
            record for record in raw_records if record.get("stage") == "AdminLogin"
        ]
        result["login_records"] = login_records

        if debug_body is not None:
            try:
                debug_data = response_data(debug_body, "GetSearchTaskDebug", task_id)
                debug = debug_data.get("debug")
                if isinstance(debug, dict):
                    debug_task = debug.get("task")
                    diagnosis = debug.get("diagnosis")
                    if isinstance(debug_task, dict):
                        public_fields.update(
                            {
                                "cache_hit": sanitize_raw(debug_task.get("cache_hit")),
                                "debug_task_status": sanitize_raw(debug_task.get("status")),
                                "task_create_time": sanitize_raw(debug_task.get("create_time")),
                                "task_start_time": sanitize_raw(debug_task.get("start_time")),
                                "task_finish_time": sanitize_raw(debug_task.get("finish_time")),
                            }
                        )
                    if isinstance(diagnosis, dict):
                        for key in (
                            "provider_request_count",
                            "agent_tool_call_count",
                            "successful_call_count",
                            "failed_call_count",
                            "unpriced_call_count",
                            "fallback_used",
                            "fallback_reason",
                            "stop_reason",
                            "final_status",
                            "warnings",
                        ):
                            public_fields[f"debug_{key}"] = sanitize_raw(
                                diagnosis.get(key)
                            )
            except FlowError as exc:
                public_fields["public_info_warnings"].append(str(exc))

        if cost_body is not None:
            try:
                cost_data = response_data(
                    cost_body, "GetProviderCostSummary", task_id
                )
                cost_summary = cost_data.get("cost_summary")
                if isinstance(cost_summary, dict):
                    public_fields.update(
                        {
                            "cost_from_time": sanitize_raw(cost_summary.get("from_time")),
                            "cost_to_time": sanitize_raw(cost_summary.get("to_time")),
                            "cost_totals_by_currency": sanitize_raw(
                                cost_summary.get("totals")
                            ),
                            "cost_by_provider": sanitize_raw(
                                cost_summary.get("by_provider")
                            ),
                            "cost_by_worker": sanitize_raw(cost_summary.get("by_worker")),
                            "cost_by_search": sanitize_raw(cost_summary.get("by_search")),
                        }
                    )
            except FlowError as exc:
                public_fields["public_info_warnings"].append(str(exc))

        statuses = {
            public_fields["debug_collection_status"],
            public_fields["cost_collection_status"],
        }
        if statuses == {"SUCCESS"}:
            public_fields["public_info_status"] = "COMPLETE"
        elif "AUTH_FAILED" in statuses:
            public_fields["public_info_status"] = "AUTH_FAILED"
        elif "SUCCESS" in statuses:
            public_fields["public_info_status"] = "PARTIAL"
        else:
            public_fields["public_info_status"] = "FAILED"
        return result

    emit_progress("query_started", stage="Input", status="RUNNING")
    photo_input: dict[str, Any] | None = None
    try:
        query_stage = resolve_query_stage(item)
        media_asset_id: str | None = None
        if query_stage in PHOTO_QUERY_STAGES:
            emit_progress(
                "query_stage",
                stage="PhotoValidation",
                status="RUNNING",
                message="正在校验本地 JPEG 照片",
            )
            try:
                photo_content, photo_input = load_photo_input(item, client.config)
            except FlowError as exc:
                validation_record = build_raw_record(
                    run_id=effective_run_id,
                    input_id=input_id,
                    task_id="",
                    candidate_id="",
                    stage="PhotoValidation",
                    sequence_no=1,
                    request_params={"photo_path": item.get("photo_path")},
                    response_body=None,
                    error=str(exc),
                )
                raw_records.append(validation_record)
                emit_callback(raw_callback, validation_record)
                chain_logger.write_raw(validation_record)
                raise
            validation_record = build_raw_record(
                run_id=effective_run_id,
                input_id=input_id,
                task_id="",
                candidate_id="",
                stage="PhotoValidation",
                sequence_no=1,
                request_params={"photo_path": item.get("photo_path")},
                response_body=photo_input,
            )
            raw_records.append(validation_record)
            emit_callback(raw_callback, validation_record)
            chain_logger.write_raw(validation_record)
            emit_progress(
                "query_stage",
                stage="PhotoValidation",
                status="SUCCEEDED",
                message="本地 JPEG 校验完成",
            )

            emit_progress(
                "query_stage",
                stage="GetMediaUploadConfig",
                status="RUNNING",
                message="正在获取媒体上传配置",
            )
            config_body, _ = call_and_record(
                "GetMediaUploadConfig",
                {},
                service_name=MEDIA_SERVICE_NAME,
            )
            media_config = validate_media_config(
                response_data(config_body, "GetMediaUploadConfig")
            )
            if photo_input["content_length"] > media_config["max_size_bytes"]:
                raise FlowError(
                    "GetMediaUploadConfig",
                    "照片大小超过媒体配置 max_size_bytes",
                )
            photo_input["config_version"] = media_config["config_version"]
            emit_progress(
                "query_stage",
                stage="GetMediaUploadConfig",
                status="SUCCEEDED",
                message="媒体上传配置获取完成",
            )

            prepare_params = {
                "client_request_id": (
                    f"media-{int(time.time() * 1000)}-{uuid.uuid4().hex[:10]}"
                ),
                "content_type": "image/jpeg",
                "size_bytes": photo_input["content_length"],
            }
            emit_progress(
                "query_stage",
                stage="PrepareMediaUpload",
                status="RUNNING",
                message="正在准备媒体上传",
            )
            prepare_body, _ = call_and_record(
                "PrepareMediaUpload",
                prepare_params,
                service_name=MEDIA_SERVICE_NAME,
            )
            prepared = validate_prepare_data(
                response_data(prepare_body, "PrepareMediaUpload"),
                content_length=photo_input["content_length"],
                config_max_size=media_config["max_size_bytes"],
            )
            media_asset_id = prepared["media_asset_id"]
            photo_input["media_asset_id"] = media_asset_id
            photo_input["upload_status"] = "prepared"
            emit_progress(
                "query_stage",
                stage="PrepareMediaUpload",
                status="SUCCEEDED",
                message="媒体上传准备完成",
            )

            emit_progress(
                "query_stage",
                stage="PutMediaBinary",
                status="RUNNING",
                message="正在上传 JPEG 原始字节",
            )
            put_request_summary = {
                "upload_url": "***SIGNED_UPLOAD_URL***",
                "content_length": photo_input["content_length"],
                "content_type": "image/jpeg",
                "binary_logged": False,
            }
            try:
                put_status = client.put_media_binary(
                    prepared["upload_url"],
                    prepared["upload_headers"],
                    photo_content,
                )
            except FlowError as exc:
                put_record = build_raw_record(
                    run_id=effective_run_id,
                    input_id=input_id,
                    task_id="",
                    candidate_id="",
                    stage="PutMediaBinary",
                    sequence_no=1,
                    request_params=put_request_summary,
                    response_body={"response_body_logged": False},
                    error=str(exc),
                    http_status=exc.http_status,
                    duration_ms=exc.duration_ms
                    or getattr(client, "last_media_duration_ms", None),
                )
                raw_records.append(put_record)
                emit_callback(raw_callback, put_record)
                chain_logger.write_raw(put_record)
                raise
            put_record = build_raw_record(
                run_id=effective_run_id,
                input_id=input_id,
                task_id="",
                candidate_id="",
                stage="PutMediaBinary",
                sequence_no=1,
                request_params=put_request_summary,
                response_body={
                    "status": "UPLOADED_TO_COS",
                    "response_body_logged": False,
                },
                http_status=put_status,
                duration_ms=getattr(client, "last_media_duration_ms", None),
            )
            raw_records.append(put_record)
            emit_callback(raw_callback, put_record)
            chain_logger.write_raw(put_record)
            # 二进制上传完成后立即释放当前引用，后续 Complete/Create 只需要
            # media_asset_id，避免候选人采集期间继续占用整张照片的内存。
            del photo_content
            photo_input["upload_status"] = "uploaded_to_cos"
            emit_progress(
                "query_stage",
                stage="PutMediaBinary",
                status="SUCCEEDED",
                message="JPEG 已上传至 COS",
            )

            retry = media_config["complete_retry"]
            complete_data: dict[str, Any] | None = None
            for attempt in range(1, retry["max_attempts"] + 1):
                if attempt > 1:
                    delay_ms = min(
                        retry["initial_delay_ms"] * (2 ** (attempt - 2)),
                        retry["max_delay_ms"],
                    )
                    sleep_fn(delay_ms / 1000)
                emit_progress(
                    "query_stage",
                    stage="CompleteMediaUpload",
                    status="RUNNING",
                    message=f"正在确认媒体上传（第 {attempt} 次）",
                )
                try:
                    complete_body, _ = call_and_record(
                        "CompleteMediaUpload",
                        {"media_asset_id": media_asset_id},
                        sequence_no=attempt,
                        service_name=MEDIA_SERVICE_NAME,
                        attempt=attempt,
                    )
                except FlowError as exc:
                    status_code = exc.http_status
                    retryable = (
                        status_code is None
                        or status_code in {408, 429}
                        or (isinstance(status_code, int) and 500 <= status_code <= 599)
                    )
                    if retryable and attempt < retry["max_attempts"]:
                        continue
                    raise
                complete_data = response_data(
                    complete_body,
                    "CompleteMediaUpload",
                )
                complete_status = complete_data.get("status")
                if complete_status == "pending" and attempt < retry["max_attempts"]:
                    continue
                if complete_status == "pending":
                    raise FlowError(
                        "CompleteMediaUpload",
                        "媒体上传在最大重试次数后仍为 pending",
                        response_body=complete_body,
                    )
                if complete_status != "uploaded":
                    raise FlowError(
                        "CompleteMediaUpload",
                        f"未知或失败的媒体状态: {complete_status!r}",
                        response_body=complete_body,
                    )
                if complete_data.get("media_asset_id") != media_asset_id:
                    raise FlowError(
                        "CompleteMediaUpload",
                        "Complete 返回的 media_asset_id 与 Prepare 不一致",
                        response_body=complete_body,
                    )
                if complete_data.get("content_type") not in (None, "image/jpeg"):
                    raise FlowError(
                        "CompleteMediaUpload",
                        "Complete 返回的 content_type 与 Prepare 不一致",
                        response_body=complete_body,
                    )
                if complete_data.get("size_bytes") not in (
                    None,
                    photo_input["content_length"],
                ):
                    raise FlowError(
                        "CompleteMediaUpload",
                        "Complete 返回的 size_bytes 与 Prepare 不一致",
                        response_body=complete_body,
                    )
                break
            if complete_data is None:
                raise FlowError("CompleteMediaUpload", "媒体上传确认未取得响应")
            photo_input["upload_status"] = "uploaded"
            emit_progress(
                "query_stage",
                stage="CompleteMediaUpload",
                status="SUCCEEDED",
                message="媒体上传确认完成",
            )

        create_params = {
            "match_strategy": item["match_strategy"],
            "clues": build_create_clues(item, media_asset_id),
            "additional_details": item["additional_details"],
        }
        create_body, create_raw = call_and_record(
            "CreateIntentTask",
            create_params,
        )
        create_data = response_data(create_body, "CreateIntentTask")
        task_id_value = create_data.get("task_id")
        if not isinstance(task_id_value, str) or not task_id_value:
            raise FlowError("CreateIntentTask", "响应缺少 task_id")
        task_id = task_id_value
        emit_progress(
            "query_stage",
            stage="CreateIntentTask",
            status="SUCCEEDED",
            message="任务创建成功",
        )

        get_task_history: list[dict[str, Any]] = []
        task_data: dict[str, Any] = {}
        no_result = False
        terminal_failure_status = ""
        for poll_sequence in range(1, client.config.max_poll_count + 1):
            sleep_fn(client.config.poll_interval_seconds)
            task_body, task_raw = call_and_record(
                "GetTask",
                {"task_id": task_id},
                sequence_no=poll_sequence,
            )
            get_task_history.append(raw_payload(task_raw))
            task_data = response_data(task_body, "GetTask", task_id)
            status = task_data.get("status")
            emit_progress(
                "query_stage",
                stage="GetTask",
                status=status,
                message=(
                    "任务完成"
                    if status == "SUCCEEDED"
                    else "任务未完成，继续轮询"
                ),
            )
            if status in {GET_TASK_SUCCESS_STATUS, GET_TASK_NO_RESULT_STATUS}:
                total_value = task_data.get("candidate_count")
                if (
                    isinstance(total_value, int)
                    and not isinstance(total_value, bool)
                    and total_value >= 0
                ):
                    candidate_count_total = total_value
                if status == GET_TASK_NO_RESULT_STATUS:
                    # NO_RESULT 是接口定义的终态：无需再请求候选列表或详情。
                    no_result = True
                    candidate_count_total = 0
                break
            if status in GET_TASK_FAILURE_TERMINAL_STATUSES:
                terminal_failure_status = str(status)
                break
            # QUEUED 和 SEARCHING 都表示任务尚未完成，继续下一轮 GetTask 轮询。
            if status not in GET_TASK_RUNNING_STATUSES:
                raise FlowError("GetTask", f"未知任务状态: {status!r}", task_id)
        else:
            raise FlowError("GetTask", "任务轮询超时", task_id)

        emit_progress(
            "query_stage",
            stage="PublicInfoDelay",
            status="RUNNING",
            message="任务已终态，等待 1 秒采集公共信息",
        )
        sleep_fn(PUBLIC_INFO_TERMINAL_DELAY_SECONDS)
        public_info = collect_public_info()
        public_fields = public_info["public_fields"]
        if chain_logger.error:
            public_fields.setdefault("public_info_warnings", []).append(
                chain_logger.error
            )
            public_fields["query_log_status"] = "LOG_INCOMPLETE"
        else:
            public_fields["query_log_status"] = "COMPLETE"
        public_fields["get_task_terminal_status"] = str(task_data.get("status") or "")
        if photo_input is not None:
            public_fields["photo_input"] = sanitize_raw(photo_input)
        # 使用已冻结的 Admin 契约生成正式任务字段；缺失或非法字段保持 None，
        # 原始 microunit、币种和来源继续放在 public_fields 供审计。
        task_fields, mapping_metadata = extract_admin_task_fields(
            task_id=task_id,
            debug_body=public_info.get("debug_body"),
            cost_body=public_info.get("cost_body"),
        )
        public_fields.update(mapping_metadata)
        admin_raw = {
            "admin_login": [
                raw_payload(record) for record in public_info["login_records"]
            ],
            "get_search_task_debug_history": [
                raw_payload(record)
                for record in raw_records
                if record.get("stage") == "GetSearchTaskDebug"
            ],
            "get_search_task_debug": (
                raw_payload(public_info["debug_record"])
                if public_info["debug_record"] is not None
                else None
            ),
            "get_provider_cost_summary_history": [
                raw_payload(record)
                for record in raw_records
                if record.get("stage") == "GetProviderCostSummary"
            ],
            "get_provider_cost_summary": (
                raw_payload(public_info["cost_record"])
                if public_info["cost_record"] is not None
                else None
            ),
        }
        photo_raw = {
            stage: [
                raw_payload(record)
                for record in raw_records
                if record.get("stage") == stage
            ]
            for stage in (
                "PhotoValidation",
                "GetMediaUploadConfig",
                "PrepareMediaUpload",
                "PutMediaBinary",
                "CompleteMediaUpload",
            )
            if any(record.get("stage") == stage for record in raw_records)
        }

        if terminal_failure_status:
            failure = FlowError(
                "GetTask",
                f"任务进入失败终态: {terminal_failure_status}",
                task_id,
                response_body=task_data,
            )
            failure.task_fields = task_fields
            failure.public_fields = public_fields
            raise failure

        # 仅 GetTask 的 NO_RESULT 终态明确表示没有候选人；SUCCEEDED 即使
        # candidate_count 为 0，仍需通过 ListTaskCandidates 取得实际结果。
        # NO_RESULT 时 List 与详情请求不会产生新信息，
        # 因此直接结束本 Query，避免为批量运行产生无意义的接口成本。
        if no_result:
            result = {
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "run_id": effective_run_id,
                "input_id": input_id,
                "task_id": task_id,
                "query_stage": query_stage,
                "query_status": "NO_CANDIDATE",
                "result_status": "NO_CANDIDATES",
                "candidate_count_total": 0,
                "candidate_count_listed": 0,
                "detail_success_count": 0,
                "detail_failure_count": 0,
                "task_fields": task_fields,
                "public_fields": public_fields,
                **(
                    {"photo_input": sanitize_raw(photo_input)}
                    if photo_input is not None
                    else {}
                ),
                "raw": {
                    **({"photo_upload": photo_raw} if photo_raw else {}),
                    "create_intent_task": raw_payload(create_raw),
                    "get_task_history": get_task_history,
                    **admin_raw,
                },
                "results": [],
            }
            emit_progress(
                "query_succeeded",
                stage="Completed",
                status="NO_CANDIDATE",
                candidate_count=0,
                detail_success_count=0,
                detail_failure_count=0,
                message="GetTask 确认无候选人，未请求候选列表和详情",
            )
            final_log_status = "NO_CANDIDATE"
            return result

        # 分页字段当前仅为接口预留；固定放大 page_size，接收全部候选人。
        list_params = {
            "task_id": task_id,
            "page": {"page_size": 100, "page_token": ""},
        }
        list_body, list_raw = call_and_record("ListTaskCandidates", list_params)
        items = response_data(list_body, "ListTaskCandidates", task_id).get("items")
        if not isinstance(items, list):
            raise FlowError("ListTaskCandidates", "响应中的 items 必须是数组", task_id)
        emit_progress(
            "query_stage",
            stage="ListTaskCandidates",
            status="SUCCEEDED",
            candidate_count=len(items),
            message=f"返回候选人 {len(items)} 个",
        )

        results: list[dict[str, Any]] = []
        detail_success_count = 0
        detail_failure_count = 0

        def record_candidate_failure(
            *,
            candidate_rank: int,
            candidate_id: str,
            rank_score: int | float | None,
            stage: str,
            error: str,
            list_item: Any,
            detail_response: Any = None,
        ) -> None:
            """同时构造失败候选人结果、失败记录和进度事件。"""

            nonlocal detail_failure_count
            detail_failure_count += 1
            sanitized_list_item = sanitize_raw(list_item)
            sanitized_detail_response = sanitize_raw(detail_response)
            results.append(
                {
                    "candidate_rank": candidate_rank,
                    "candidate_id": candidate_id,
                    "rank_score": rank_score,
                    "detail_status": "FAILED",
                    "detail_error": error,
                    "list_item_raw": sanitized_list_item,
                    "detail_data_raw": None,
                    "detail_response_raw": sanitized_detail_response,
                    "ui_sections": None,
                }
            )
            failure_record = {
                "failure_schema_version": RESULT_SCHEMA_VERSION,
                "run_id": effective_run_id,
                "input_id": input_id,
                "task_id": task_id,
                "candidate_id": candidate_id,
                "candidate_rank": candidate_rank,
                "scope": "CANDIDATE",
                "stage": stage,
                "query_status": "PARTIAL_DETAIL_FAILED",
                "result_status": "HAS_CANDIDATES",
                "error": error,
                "raw": {
                    "list_item_raw": sanitized_list_item,
                    "detail_response_raw": sanitized_detail_response,
                },
                "created_at": utc_now_text(),
            }
            emit_callback(failure_callback, failure_record)
            emit_progress(
                "candidate_failed",
                stage=stage,
                status="FAILED",
                candidate_id=candidate_id,
                candidate_rank=candidate_rank,
                message=error,
            )

        for candidate_rank, candidate in enumerate(items, start=1):
            candidate_id = ""
            rank_score: int | float | None = None
            if isinstance(candidate, dict):
                candidate_id_value = candidate.get("candidate_id")
                if isinstance(candidate_id_value, str):
                    candidate_id = candidate_id_value
                rank_score_value = candidate.get("rank_score")
                if (
                    isinstance(rank_score_value, (int, float))
                    and not isinstance(rank_score_value, bool)
                ):
                    rank_score = rank_score_value
            emit_progress(
                "candidate_started",
                stage="GetTaskCandidateDetail",
                status="RUNNING",
                candidate_id=candidate_id,
                candidate_rank=candidate_rank,
            )

            if not isinstance(candidate, dict):
                record_candidate_failure(
                    candidate_rank=candidate_rank,
                    candidate_id="",
                    rank_score=None,
                    stage="ListTaskCandidates",
                    error="候选人数据必须是对象",
                    list_item=candidate,
                )
                continue
            if not candidate_id:
                record_candidate_failure(
                    candidate_rank=candidate_rank,
                    candidate_id="",
                    rank_score=rank_score,
                    stage="ListTaskCandidates",
                    error="候选人缺少 candidate_id",
                    list_item=candidate,
                )
                continue

            detail_body: dict[str, Any] | None = None
            try:
                detail_body, _ = call_and_record(
                    "GetTaskCandidateDetail",
                    {"task_id": task_id, "candidate_id": candidate_id},
                    sequence_no=candidate_rank,
                    candidate_id=candidate_id,
                )
                detail_data = response_data(
                    detail_body,
                    "GetTaskCandidateDetail",
                    task_id,
                )
                ui_sections = detail_data.get("ui_sections", {})
                if not isinstance(ui_sections, dict):
                    raise FlowError(
                        "GetTaskCandidateDetail",
                        f"候选人 {candidate_id} 的 ui_sections 必须是对象",
                        task_id,
                    )
            except FlowError as exc:
                detail_response = (
                    exc.response_body
                    if exc.response_body is not None
                    else detail_body
                )
                record_candidate_failure(
                    candidate_rank=candidate_rank,
                    candidate_id=candidate_id,
                    rank_score=rank_score,
                    stage=exc.stage,
                    error=str(exc),
                    list_item=candidate,
                    detail_response=detail_response,
                )
                continue

            detail_success_count += 1
            results.append(
                {
                    "candidate_rank": candidate_rank,
                    "candidate_id": candidate_id,
                    "rank_score": rank_score,
                    "detail_status": "SUCCESS",
                    "detail_error": "",
                    "list_item_raw": sanitize_raw(candidate),
                    "detail_data_raw": sanitize_raw(detail_data),
                    "detail_response_raw": sanitize_raw(detail_body),
                    "ui_sections": sanitize_raw(ui_sections),
                }
            )
            emit_progress(
                "candidate_succeeded",
                stage="GetTaskCandidateDetail",
                status="SUCCESS",
                candidate_id=candidate_id,
                candidate_rank=candidate_rank,
            )

        if not items:
            query_status = "NO_CANDIDATE"
        elif detail_failure_count:
            query_status = "PARTIAL_DETAIL_FAILED"
        else:
            query_status = "SUCCESS"

        result = {
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "run_id": effective_run_id,
            "input_id": input_id,
            "task_id": task_id,
            "query_stage": query_stage,
            "query_status": query_status,
            "result_status": normalize_result_status(
                query_status,
                len(items),
            ),
            "candidate_count_total": candidate_count_total,
            "candidate_count_listed": len(items),
            "detail_success_count": detail_success_count,
            "detail_failure_count": detail_failure_count,
            "task_fields": task_fields,
            "public_fields": public_fields,
            **(
                {"photo_input": sanitize_raw(photo_input)}
                if photo_input is not None
                else {}
            ),
            "raw": {
                **({"photo_upload": photo_raw} if photo_raw else {}),
                "create_intent_task": raw_payload(create_raw),
                "get_task_history": get_task_history,
                **admin_raw,
                "list_task_candidates": raw_payload(list_raw),
            },
            "results": results,
        }
        emit_progress(
            "query_succeeded",
            stage="Completed",
            status=query_status,
            candidate_count=len(items),
            detail_success_count=detail_success_count,
            detail_failure_count=detail_failure_count,
        )
        final_log_status = query_status
        final_log_candidate_count = len(items)
        return result
    except FlowError as exc:
        if not exc.task_id and task_id:
            exc.task_id = task_id
        exc.raw_records = raw_records
        if not exc.task_fields and "task_fields" in locals():
            exc.task_fields = task_fields
        if not exc.public_fields and "public_fields" in locals():
            exc.public_fields = public_fields
        if photo_input is not None:
            exc.public_fields = dict(exc.public_fields or {})
            exc.public_fields["photo_input"] = sanitize_raw(photo_input)
        final_log_status = "FAILED"
        final_log_error = str(exc)
        emit_progress(
            "query_failed",
            stage=exc.stage,
            status="FAILED",
            message=str(exc),
        )
        raise
    finally:
        chain_logger.write_event(
            "QueryEnd",
            task_id=task_id,
            business_success=final_log_status not in {"FAILED", "EXECUTION_FAILED"},
            response={
                "status": final_log_status,
                "candidate_count": final_log_candidate_count,
            },
            error=final_log_error,
        )
        chain_logger.close()


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")


def run_batch(
    input_path: Path,
    output_dir: Path,
    client: SearchClient,
    sleep_fn: Callable[[float], None] = time.sleep,
    results_path: Path | None = None,
    failures_path: Path | None = None,
    progress_callback: ProgressCallback | None = None,
    raw_callback: RawCallback | None = None,
    run_id: str = "",
    run_name: str = "",
) -> tuple[int, int]:
    """顺序执行一个 JSONL 批次并写入 v1.3 结果与失败文件。

    功能说明:
        保持现有 CLI 的文件选择和顺序执行方式。Query 级失败继续下一输入；
        Candidate 级失败由 ``process_one`` 隔离并立即写入 failures.jsonl。

    参数说明:
        input_path: 输入任务 JSONL。
        output_dir: 未显式传入结果路径时使用的输出目录。
        client: 同步搜索接口客户端。
        sleep_fn: 轮询等待函数。
        results_path: 可选结果文件；为空时使用 output/results.jsonl。
        failures_path: 可选失败文件；为空时使用 output/failures.jsonl。
        progress_callback: 可选进度事件回调。
        raw_callback: 可选脱敏 Raw 回调。
        run_id: 可选运行标识；为空时为整个批次生成一个标识。
        run_name: 可选日志目录名称；CLI 默认使用输入文件名（不含扩展名）。

    返回值:
        ``(完整成功或无候选人 Query 数, 失败或部分失败 Query 数)``。

    异常说明:
        单条业务 FlowError 会写失败文件并继续；文件系统错误和回调自身错误
        不会被吞掉，交由调用方处理。
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_path or output_dir / "results.jsonl"
    failures_path = failures_path or output_dir / "failures.jsonl"
    results_path.write_text("", encoding="utf-8")
    failures_path.write_text("", encoding="utf-8")
    effective_run_id = run_id or f"run_{uuid.uuid4().hex}"
    effective_run_name = run_name or input_path.stem or effective_run_id

    def write_candidate_failure(record: dict[str, Any]) -> None:
        """把候选级失败写入本批次 failures.jsonl。"""

        append_jsonl(failures_path, record)

    success_count = 0
    failure_count = 0
    seen_ids: set[str] = set()

    for line_number, raw_item, parse_error in read_jsonl(input_path):
        fallback_input_id = f"line-{line_number}"
        if isinstance(raw_item, dict) and isinstance(raw_item.get("input_id"), str):
            fallback_input_id = raw_item["input_id"]
        try:
            if parse_error:
                raise FlowError("Input", parse_error)
            item = validate_input(raw_item, line_number, seen_ids)
            print(f"[{item['input_id']}] 开始处理", flush=True)
            result = process_one(
                item,
                client,
                sleep_fn,
                progress_callback=progress_callback,
                raw_callback=raw_callback,
                failure_callback=write_candidate_failure,
                run_id=effective_run_id,
                run_name=effective_run_name,
            )
            append_jsonl(results_path, result)
            if result["query_status"] == "PARTIAL_DETAIL_FAILED":
                failure_count += 1
                print(
                    f"[{item['input_id']}] 部分完成，候选人详情成功 "
                    f"{result['detail_success_count']} 个、失败 "
                    f"{result['detail_failure_count']} 个",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                success_count += 1
                print(
                    f"[{item['input_id']}] 完成，候选人 {len(result['results'])} 个",
                    flush=True,
                )
        except FlowError as exc:
            failure_record = {
                "failure_schema_version": RESULT_SCHEMA_VERSION,
                "run_id": effective_run_id,
                "input_id": fallback_input_id,
                "task_id": exc.task_id,
                "candidate_id": "",
                "scope": "INPUT" if exc.stage == "Input" else "QUERY",
                "stage": exc.stage,
                "query_status": "FAILED",
                "result_status": "EXECUTION_FAILED",
                "error": str(exc),
                "task_fields": exc.task_fields,
                "public_fields": exc.public_fields,
                "raw": exc.raw_records,
                "created_at": utc_now_text(),
            }
            append_jsonl(failures_path, failure_record)
            if exc.stage == "Input":
                emit_callback(
                    progress_callback,
                    {
                        "event": "query_failed",
                        "run_id": effective_run_id,
                        "input_id": fallback_input_id,
                        "task_id": exc.task_id,
                        "stage": exc.stage,
                        "status": "FAILED",
                        "message": str(exc),
                    },
                )
            failure_count += 1
            print(f"[{fallback_input_id}] 失败（{exc.stage}）: {exc}", file=sys.stderr, flush=True)

    return success_count, failure_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="顺序执行 People Insight 搜索任务并提取 ui_sections"
    )
    parser.add_argument(
        "--input",
        default=None,
        help="输入 JSONL 文件；未提供时读取 .env 的 SEARCH_INPUT_FILE",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="结果输出目录；未提供时读取 .env 的 SEARCH_OUTPUT_DIR",
    )
    parser.add_argument("--env-file", default=".env", help="环境变量文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = Config.from_env(Path(args.env_file))
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1

    input_path = Path(args.input or config.input_file)
    if not input_path.is_file():
        print(f"输入文件不存在: {input_path}", file=sys.stderr)
        return 1
    output_dir = Path(args.output or config.output_dir)
    try:
        results_path, failures_path = select_output_paths(
            input_path,
            output_dir,
            config.allow_duplicate_run,
        )
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"输入文件: {input_path}")
    print(f"结果文件: {results_path}")
    print(f"失败文件: {failures_path}")

    success_count, failure_count = run_batch(
        input_path=input_path,
        output_dir=output_dir,
        client=SearchClient(config),
        results_path=results_path,
        failures_path=failures_path,
    )
    print(f"处理结束：成功 {success_count} 条，失败 {failure_count} 条")
    return 2 if failure_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
