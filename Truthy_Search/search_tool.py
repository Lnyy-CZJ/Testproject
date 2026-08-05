#!/usr/bin/env python3
"""Run People Insight search tasks sequentially and save ui_sections results."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parent
SERVICE_NAME = "tool.people_insight.SearchService"
ADMIN_SERVICE_NAME = "tool.admin.AdminService"
RESULT_SCHEMA_VERSION = "1.3.1"
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

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Config":
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

        return cls(
            api_url=setting("SEARCH_API_URL").strip(),
            headers=headers,
            auth_token=setting("AUTH_TOKEN").strip(),
            device_id=setting("DEVICE_ID").strip(),
            user_id=setting("USER_ID").strip(),
            poll_interval_seconds=poll_interval,
            max_poll_count=max_poll_count,
            http_timeout_seconds=http_timeout,
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
    ) -> None:
        """初始化原 Search Client，并为同一个 Run 持有一个 Admin Session。"""

        self.config = config
        self.session = session or requests.Session()
        self.last_http_status: int | None = None
        self.last_duration_ms: int | None = None
        self.admin_client = AdminClient(config, admin_session)

    def call(self, method_name: str, params: dict[str, Any]) -> dict[str, Any]:
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
                    "service_name": SERVICE_NAME,
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
            sanitized[str(key)] = sanitize_raw(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_raw(item) for item in value]
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
        ``FULL_NAME`` 或 ``FULL_NAME_SOCIAL``。旧输入存在 SOCIAL_LINK
        线索时推断为后者，否则推断为前者。

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
    if query_stage not in {"FULL_NAME", "FULL_NAME_SOCIAL"}:
        raise FlowError(
            "Input",
            "query_stage 只支持 FULL_NAME 或 FULL_NAME_SOCIAL",
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
        "error": error,
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
    """按输入人物追加便于人工阅读的脱敏请求与响应日志。"""

    def __init__(
        self,
        *,
        enabled: bool,
        directory: Path,
        run_id: str,
        input_id: str,
        person_name: str,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        """安全创建不覆盖的日志文件，目录错误不会中断检索。"""

        self.enabled = enabled
        self.run_id = run_id
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
            directory.mkdir(parents=True, exist_ok=True)
            created_at = datetime.now(self.timezone)
            date_text = created_at.strftime("%Y-%m-%d")
            time_text = created_at.strftime("%H%M%S")
            microsecond_text = created_at.strftime("%f")
            safe_person = safe_log_name(person_name)
            safe_input = safe_log_name(input_id)
            filename_prefix = f"{date_text}_{time_text}_{safe_person}"
            candidates = [
                directory / f"{filename_prefix}.log",
                directory / f"{filename_prefix}_{safe_input}.log",
            ]
            candidates.append(
                directory
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
                    candidate = directory / (
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
    additional_details = item.get("additional_details", [])
    if not isinstance(additional_details, list):
        raise FlowError("Input", f"第 {line_number} 行 additional_details 必须是数组")
    match_strategy = item.get("match_strategy", "UNION")
    if not isinstance(match_strategy, str) or not match_strategy:
        raise FlowError("Input", f"第 {line_number} 行 match_strategy 必须是非空字符串")
    query_stage = resolve_query_stage(item)

    return {
        "input_id": input_id,
        "query_stage": query_stage,
        "clues": clues,
        "additional_details": additional_details,
        "match_strategy": match_strategy,
    }


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


def process_one(
    item: dict[str, Any],
    client: SearchClient,
    sleep_fn: Callable[[float], None] = time.sleep,
    progress_callback: ProgressCallback | None = None,
    raw_callback: RawCallback | None = None,
    failure_callback: FailureCallback | None = None,
    run_id: str = "",
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
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """执行一次接口调用，并在成功或失败后立即生成脱敏 Raw。"""

        try:
            body = client.call(stage, params)
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
                http_status=exc.http_status
                or getattr(client, "last_http_status", None),
                duration_ms=exc.duration_ms
                or getattr(client, "last_duration_ms", None),
            )
            raw_records.append(record)
            emit_callback(raw_callback, record)
            chain_logger.write_raw(record)
            raise

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
            http_status=getattr(client, "last_http_status", None),
            duration_ms=getattr(client, "last_duration_ms", None),
        )
        raw_records.append(record)
        emit_callback(raw_callback, record)
        chain_logger.write_raw(record)
        return body, record

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
    try:
        query_stage = resolve_query_stage(item)
        create_params = {
            "match_strategy": item["match_strategy"],
            "clues": item["clues"],
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
        # 正式字段路径、单位和口径尚未确认。即使 Raw 中出现同名值，也不能
        # 据此猜测映射；后端冻结契约后只需修改这一处映射和对应测试。
        task_fields = {
            "llm_cost": None,
            "third_party_cost": None,
            "total_cost": None,
            "pdl_called": None,
            "search_duration_ms": None,
        }
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
                "raw": {
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
            "raw": {
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
