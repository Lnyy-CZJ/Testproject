#!/usr/bin/env python3
"""searchTool v1.3 阶段6本地 Web、报告与导出入口。"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from dotenv import dotenv_values
from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from analysis_service import (
    ActiveRunError,
    AnalysisService,
    DuplicateImportError,
    EVALUATION_PHASES,
    EVALUATION_THRESHOLD_FIELDS,
    FieldSchemaValidationError,
    ImportValidationError,
    PersonLinkValidationError,
    RESULT_STATUSES,
    ReviewValidationError,
    SUPPORTED_QUERY_STAGES,
    normalize_evaluation_thresholds,
    validate_field_definitions,
    validate_storage_id,
)
from analysis_store import AnalysisStore
from search_tool import Config, SearchClient


PROJECT_ROOT = Path(__file__).resolve().parent
TERMINAL_RUN_STATUSES = {
    "COMPLETED",
    "PARTIAL_FAILED",
    "FAILED",
    "INTERRUPTED",
}
QUERY_STATUSES = {
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "NO_CANDIDATE",
    "PARTIAL_DETAIL_FAILED",
    "FAILED",
}
QUERY_STAGES = {
    "FULL_NAME",
    "FULL_NAME_SOCIAL",
    "FULL_NAME_PHOTO",
    "FULL_NAME_SOCIAL_PHOTO",
}
ALLOWED_UPLOAD_SUFFIXES = {".jsonl", ".json", ".xlsx"}
REPORT_TYPES = {"SINGLE", "COMPARE"}
REPORT_STATUSES = {"READY", "STALE", "FAILED"}
DEFAULT_DISPLAY_TIMEZONE = "Asia/Shanghai"
DISPLAY_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def normalize_base_path(value: Any) -> str:
    """规范化平台挂载前缀并拒绝可能改变 URL 语义的输入。

    功能说明:
        把空值和根路径转换为空前缀；合法非空前缀统一为单个前导斜杠、
        不带尾部斜杠的形式。

    参数说明:
        value: 环境变量或测试覆盖传入的基础路径。

    返回值:
        str: 空字符串或形如 ``/truthy-search`` 的安全前缀。

    异常说明:
        ValueError: 路径包含父目录、协议、查询参数、Fragment、反斜杠或
        重复斜杠时抛出，避免平台路由被绕过。
    """

    raw = str(value or "").strip()
    if raw in {"", "/"}:
        return ""
    if not raw.startswith("/"):
        raw = f"/{raw}"
    if any(token in raw for token in ("..", "://", "?", "#", "\\", "//")):
        raise ValueError("SEARCH_WEB_BASE_PATH 必须是安全的单层或多层 URL 路径")
    normalized = raw.rstrip("/")
    if not normalized or any(not segment for segment in normalized.split("/")[1:]):
        raise ValueError("SEARCH_WEB_BASE_PATH 格式无效")
    return normalized


class BasePathMiddleware:
    """在平台模式下剥离固定前缀，并把前缀写入 WSGI ``SCRIPT_NAME``。"""

    def __init__(self, app: Callable, base_path: str) -> None:
        """绑定原始 WSGI 应用和已经过校验的平台路径前缀。"""

        self.app = app
        self.base_path = base_path

    def __call__(self, environ: dict[str, Any], start_response: Callable) -> Any:
        """转换匹配路径；不匹配请求直接返回不含内部信息的 404。"""

        path_info = str(environ.get("PATH_INFO") or "/")
        if path_info == self.base_path:
            internal_path = "/"
        elif path_info.startswith(f"{self.base_path}/"):
            internal_path = path_info[len(self.base_path) :]
        else:
            start_response(
                "404 Not Found",
                [("Content-Type", "text/plain; charset=utf-8")],
            )
            return ["Not Found".encode("utf-8")]
        environ["SCRIPT_NAME"] = self.base_path
        environ["PATH_INFO"] = internal_path
        return self.app(environ, start_response)


def _project_path(value: str | Path) -> Path:
    """把相对配置路径稳定解析到项目目录。"""

    path = Path(value)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _positive_int(value: Any, default: int) -> int:
    """把配置值转换为正整数，无效值回退到安全默认值。"""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _threshold_form_payload(form: Any) -> dict[str, dict[str, Any]]:
    """把结构化 Evaluation 表单转换为服务层参考线对象。"""

    return {
        query_stage: {
            field_key: form.get(
                f"threshold__{query_stage}__{field_key}",
                "",
            )
            for field_key in EVALUATION_THRESHOLD_FIELDS
        }
        for query_stage in sorted(SUPPORTED_QUERY_STAGES)
    }


def _boolean_value(value: Any, default: bool = False) -> bool:
    """解析 .env/测试覆盖中的布尔开关。"""

    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _format_datetime(
    value: Any,
    display_timezone: ZoneInfo,
    empty_text: str = "—",
) -> str:
    """把存储时间转换为统一的用户可见时间。

    功能说明:
        支持 ISO 8601、结尾 ``Z`` 和历史无时区值；无时区值按 UTC 解释，
        再转换到配置的展示时区并移除微秒。

    参数说明:
        value: 数据库或报告快照中的时间；空值使用 ``empty_text``。
        display_timezone: 已校验的 IANA 展示时区。
        empty_text: 页面针对空时间使用的提示文案。

    返回值:
        格式为 ``YYYY-MM-DD HH:mm:ss`` 的字符串。非法历史值保留原文，
        避免单条脏数据导致整个页面返回 500。
    """

    if value in (None, ""):
        return empty_text
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        try:
            parsed = datetime.fromisoformat(
                text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
            )
        except ValueError:
            return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(display_timezone).strftime(DISPLAY_TIME_FORMAT)


class RunCoordinator:
    """使用单线程后台执行器串行运行 searchTool。

    功能说明:
        Web 请求只提交 Run ID，真实接口流程在线程池中执行。每个任务由
        AnalysisService 独立打开 SQLite 连接，不跨线程复用连接对象。
    """

    def __init__(
        self,
        service: AnalysisService,
        env_file: Path,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        """绑定执行服务、环境文件和可测试的 HTTP 客户端工厂。"""

        self.service = service
        self.env_file = env_file
        self.client_factory = client_factory or self._default_client
        self.executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="searchtool-run",
        )
        self._lock = threading.Lock()
        self._futures: dict[str, Future[None]] = {}

    def prepare_run_client(self) -> tuple[SearchClient | None, str | None, int | None]:
        """在创建新 Run 前获取一次平台快照；独立模式保持后台延迟构造。"""

        source = os.getenv("SEARCH_CONFIG_SOURCE", "env").strip().lower()
        if source != "platform":
            return None, None, None
        platform_api_url = os.getenv("PLATFORM_API_URL", "").rstrip("/")
        token_file = Path(os.getenv("PLATFORM_CLIENT_TOKEN_FILE", ""))
        if not platform_api_url or not token_file.is_file():
            raise RuntimeError("平台运行配置客户端未正确部署")
        token = token_file.read_text(encoding="utf-8").strip()
        try:
            response = requests.get(
                f"{platform_api_url}/internal/tools/truthy-search/runtime-config",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError("平台运行配置暂时不可用") from exc
        if not isinstance(payload, dict) or payload.get("tool_id") != "truthy-search" or not payload.get("release_id"):
            raise RuntimeError("平台未发布可用的 Truthy Search 配置")
        normal = payload.get("normal") if isinstance(payload.get("normal"), dict) else {}
        secrets = payload.get("secrets") if isinstance(payload.get("secrets"), dict) else {}
        snapshot = {**normal, **secrets}
        # 平台模式不读取旧 .env，新 Run 仅使用本次不可变快照。
        credential_metadata = payload.get("credential_metadata") if isinstance(payload.get("credential_metadata"), dict) else {}
        credential_version = credential_metadata.get("credential_version")
        return (
            SearchClient(Config.from_env(None, overrides=snapshot)),
            str(payload["release_id"]),
            int(credential_version) if isinstance(credential_version, int) else None,
        )

    def _default_client(self) -> SearchClient:
        """构造独立模式客户端；平台模式的客户端必须在 Run 创建前锁定。"""

        prepared, _release_id, _credential_version = self.prepare_run_client()
        if prepared is None:
            return SearchClient(Config.from_env(self.env_file))
        return prepared

    @staticmethod
    def _report_admin_status(client: SearchClient) -> None:
        """平台模式只上报 Admin 状态和过期时间，绝不发送 Session Token。"""

        if os.getenv("SEARCH_CONFIG_SOURCE", "env").strip().lower() != "platform":
            return
        admin = client.admin_client
        if not admin.available or (admin.expire_time is None and admin.last_duration_ms is None):
            return
        platform_api_url = os.getenv("PLATFORM_API_URL", "").rstrip("/")
        token_file = Path(os.getenv("PLATFORM_CLIENT_TOKEN_FILE", ""))
        if not platform_api_url or not token_file.is_file():
            return
        payload = {
            "provider_type": "admin_login",
            "status": "healthy" if admin.expire_time is not None else "action_required",
            "expires_at": admin.expire_time.isoformat() if admin.expire_time else None,
            "error_code": None if admin.expire_time is not None else "ADMIN_LOGIN_FAILED",
        }
        try:
            requests.post(
                f"{platform_api_url}/internal/tools/truthy-search/credential-status",
                headers={"Authorization": f"Bearer {token_file.read_text(encoding='utf-8').strip()}"},
                json=payload,
                timeout=3,
            ).raise_for_status()
        except (OSError, requests.RequestException):
            # 状态上报是旁路能力，不得改变 Run 的业务终态。
            return

    def _execute(self, run_id: str, prepared_client: SearchClient | None = None) -> None:
        """执行一个 Run，意外错误转换为可见终态且不暴露堆栈。"""

        client: SearchClient | None = None
        try:
            client = prepared_client or self.client_factory()
            self.service.execute_run(
                run_id,
                client,
                sleep_fn=time.sleep,
            )
        except Exception as exc:
            self.service.mark_run_failed(
                run_id,
                f"后台执行失败（{type(exc).__name__}）: {exc}",
            )
        finally:
            if client is not None:
                self._report_admin_status(client)
            with self._lock:
                self._futures.pop(run_id, None)

    def _execute_query_retry(self, run_id: str, query_id: str) -> None:
        """后台重跑单条 Query；异常只标记该 Query，不波及同一 Run 的其他结果。"""

        future_id = f"{run_id}:{query_id}"
        try:
            self.service.execute_query_retry(
                run_id,
                query_id,
                self.client_factory(),
                sleep_fn=time.sleep,
            )
        except Exception as exc:
            self.service.mark_query_retry_failed(
                run_id,
                query_id,
                f"单条重跑失败（{type(exc).__name__}）: {exc}",
            )
        finally:
            with self._lock:
                self._futures.pop(future_id, None)

    def submit(self, run_id: str, prepared_client: SearchClient | None = None) -> None:
        """提交一个已创建的 PENDING Run，重复提交同一 ID 时拒绝。"""

        with self._lock:
            if run_id in self._futures:
                raise ActiveRunError(f"Run {run_id} 已提交")
            self._futures[run_id] = self.executor.submit(
                self._execute, run_id, prepared_client,
            )

    def submit_query_retry(self, run_id: str, query_id: str) -> None:
        """把已校验的单条重跑加入既有单线程执行队列。"""

        future_id = f"{run_id}:{query_id}"
        with self._lock:
            if future_id in self._futures:
                raise ActiveRunError(f"Query {query_id} 已提交重跑")
            self._futures[future_id] = self.executor.submit(
                self._execute_query_retry,
                run_id,
                query_id,
            )

    def shutdown(self, *, wait: bool = True) -> None:
        """关闭后台执行器；命令行退出和测试清理时调用。"""

        self.executor.shutdown(wait=wait, cancel_futures=False)


def create_app(config_overrides: dict[str, Any] | None = None) -> Flask:
    """创建阶段3 Flask 应用并初始化 Store、Service 与后台执行器。

    参数说明:
        config_overrides: 测试或嵌入平台提供的 Flask/路径覆盖配置。

    返回值:
        已注册页面、状态 API、历史导入和受控下载路由的 Flask 应用。

    异常说明:
        数据库无法初始化或路径不可写时直接抛出，避免启动半可用服务。
        接口 Token 等配置延迟到真正执行 Run 时校验，不阻塞历史数据浏览。
    """

    overrides = dict(config_overrides or {})
    env_file = _project_path(
        overrides.get(
            "SEARCH_ENV_FILE",
            os.getenv("SEARCH_ENV_FILE", ".env"),
        )
    )
    file_values = dotenv_values(env_file) if env_file.is_file() else {}

    def setting(name: str, default: Any) -> Any:
        """按显式覆盖、进程环境、env 文件、默认值顺序读取配置。"""

        if name in overrides:
            return overrides[name]
        if name in os.environ:
            return os.environ[name]
        return file_values.get(name, default)

    data_dir = _project_path(setting("SEARCH_DATA_DIR", "data"))
    db_path = _project_path(
        setting("SEARCH_DB_FILE", data_dir / "searchtool_v1_3.db")
    )
    import_dir = _project_path(
        setting("SEARCH_IMPORT_DIR", data_dir / "imports")
    )
    raw_dir = _project_path(setting("SEARCH_RAW_DIR", data_dir / "raw"))
    report_dir = _project_path(
        setting("SEARCH_REPORT_DIR", "output/reports")
    )
    app = Flask(__name__)
    configured_timezone = str(
        setting("SEARCH_DISPLAY_TIMEZONE", DEFAULT_DISPLAY_TIMEZONE)
    ).strip()
    try:
        display_timezone = ZoneInfo(configured_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        app.logger.warning(
            "SEARCH_DISPLAY_TIMEZONE=%r 无效，已回退为 %s",
            configured_timezone,
            DEFAULT_DISPLAY_TIMEZONE,
        )
        configured_timezone = DEFAULT_DISPLAY_TIMEZONE
        display_timezone = ZoneInfo(DEFAULT_DISPLAY_TIMEZONE)
    app.config.update(
        SECRET_KEY=str(setting("SEARCH_WEB_SECRET_KEY", "local-searchtool-v1.3")),
        SEARCH_DATA_DIR=str(data_dir),
        SEARCH_DB_FILE=str(db_path),
        SEARCH_IMPORT_DIR=str(import_dir),
        SEARCH_RAW_DIR=str(raw_dir),
        SEARCH_REPORT_DIR=str(report_dir),
        SEARCH_REPORT_EXCEL_ENABLED=_boolean_value(
            setting("SEARCH_REPORT_EXCEL_ENABLED", True),
            True,
        ),
        SEARCH_DISPLAY_TIMEZONE=configured_timezone,
        SEARCH_ENV_FILE=str(env_file),
        SEARCH_WEB_HOST=str(setting("SEARCH_WEB_HOST", "127.0.0.1")),
        SEARCH_WEB_PORT=_positive_int(setting("SEARCH_WEB_PORT", 5002), 5002),
        SEARCH_WEB_BASE_PATH=normalize_base_path(
            setting("SEARCH_WEB_BASE_PATH", "")
        ),
        PLATFORM_HOME_URL=str(setting("PLATFORM_HOME_URL", "")).strip(),
        PLATFORM_API_URL=str(setting("PLATFORM_API_URL", "")).rstrip("/"),
        PLATFORM_CLIENT_TOKEN_FILE=str(setting("PLATFORM_CLIENT_TOKEN_FILE", "")),
        MAX_CONTENT_LENGTH=_positive_int(
            setting("SEARCH_WEB_MAX_UPLOAD_BYTES", 50 * 1024 * 1024),
            50 * 1024 * 1024,
        ),
        RECOVER_INTERRUPTED_RUNS=True,
    )
    app.config.update(overrides)
    # 测试/嵌入覆盖同样必须经过 IANA 时区校验，不能把非法原值写回配置。
    app.config["SEARCH_DISPLAY_TIMEZONE"] = configured_timezone
    app.config["SEARCH_WEB_BASE_PATH"] = normalize_base_path(
        app.config.get("SEARCH_WEB_BASE_PATH", "")
    )
    if app.config["SEARCH_WEB_BASE_PATH"]:
        app.wsgi_app = BasePathMiddleware(
            app.wsgi_app,
            app.config["SEARCH_WEB_BASE_PATH"],
        )

    store = AnalysisStore(app.config["SEARCH_DB_FILE"])
    store.initialize()
    service = AnalysisService(
        store,
        app.config["SEARCH_DATA_DIR"],
        import_dir=app.config["SEARCH_IMPORT_DIR"],
        raw_dir=app.config["SEARCH_RAW_DIR"],
        report_dir=app.config["SEARCH_REPORT_DIR"],
    )
    # 先保留历史 v2 默认快照，再按兼容规则创建新的 v3 字段目录。
    service.ensure_default_field_schema()
    service.ensure_default_field_schema_v3()
    if app.config.get("RECOVER_INTERRUPTED_RUNS", True):
        service.recover_interrupted_runs()
    coordinator = RunCoordinator(service, Path(app.config["SEARCH_ENV_FILE"]))
    app.extensions["analysis_store"] = store
    app.extensions["analysis_service"] = service
    app.extensions["run_coordinator"] = coordinator
    app.extensions["default_run_coordinator"] = coordinator

    def platform_client_token() -> str:
        """读取只读工具身份 Token，不将内容写入日志或响应。"""

        try:
            return Path(app.config["PLATFORM_CLIENT_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
        except (OSError, TypeError):
            return ""

    @app.before_request
    def validate_platform_csrf() -> Response | None:
        """平台模式下为所有写路由校验双提交 CSRF Token。"""

        if not app.config["PLATFORM_API_URL"] or request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        cookie = request.cookies.get("tp_csrf", "")
        submitted = request.headers.get("X-CSRF-Token", "") or request.form.get("_csrf", "")
        if not cookie or not submitted or not hmac.compare_digest(cookie, submitted):
            return jsonify(code="CSRF_INVALID", message="请求安全校验失败"), 403
        return None

    @app.after_request
    def report_platform_audit(response: Response) -> Response:
        """上报工具写操作的结构化审计，上报失败不改写业务响应。"""

        token = platform_client_token()
        if request.method in {"GET", "HEAD", "OPTIONS"} or not app.config["PLATFORM_API_URL"] or not token:
            return response
        payload = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "action": f"tool.{request.endpoint or 'write'}",
            "resource_type": "truthy_search_operation",
            "outcome": "success" if response.status_code < 400 else ("denied" if response.status_code == 403 else "failed"),
            "error_code": "CSRF_INVALID" if response.status_code == 403 else None,
            "actor_user_id": request.headers.get("X-Platform-User-ID"),
            "actor_username": request.headers.get("X-Platform-Username"),
            "metadata": {},
        }
        try:
            requests.post(
                f"{app.config['PLATFORM_API_URL']}/internal/tools/truthy-search/audit-events",
                headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=1,
            )
        except requests.RequestException:
            pass
        return response

    @app.get("/health")
    def health() -> tuple[Response, int] | Response:
        """检查 Flask 进程与 SQLite 可查询性，不向调用方暴露异常详情。"""

        try:
            store.fetch_one("SELECT 1 AS ok")
        except sqlite3.Error:
            return jsonify(service="truthy-search", status="unavailable"), 503
        return jsonify(service="truthy-search", status="ok")

    def page_number(name: str = "page") -> int:
        """读取最小为1的分页页码。"""

        return max(_positive_int(request.args.get(name, 1), 1), 1)

    def parse_json(value: Any, default: Any) -> Any:
        """解析数据库 JSON TEXT；异常历史值回退而不破坏详情页。"""

        if value in (None, ""):
            return default
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    def report_artifact_available(
        report_id: str,
        artifact: str,
        status: str,
    ) -> bool:
        """检查报告产物是否真实存在，FAILED 报告不提供下载入口。"""

        if status == "FAILED":
            return False
        try:
            service.resolve_report_artifact(report_id, artifact)
        except ReviewValidationError:
            return False
        return True

    def report_summary_rows(
        where: list[str] | None = None,
        parameters: list[Any] | None = None,
        *,
        limit: int,
        offset: int = 0,
        with_artifacts: bool = False,
    ) -> list[dict[str, Any]]:
        """读取报告列表摘要，不加载 metrics_json 或重新计算指标。"""

        where_sql = (
            f"WHERE {' AND '.join(where)}"
            if where
            else ""
        )
        rows = store.fetch_all(
            f"""
            SELECT rp.report_id, rp.evaluation_id, rp.report_type,
                   rp.status, rp.html_file, rp.excel_file, rp.created_at,
                   CASE WHEN json_valid(rp.metrics_json)
                        THEN json_extract(
                            rp.metrics_json, '$.metadata.report_name'
                        )
                        ELSE NULL END AS report_name,
                   e.name AS evaluation_name,
                   candidate_run.system_version,
                   candidate_run.evaluation_phase
            FROM reports AS rp
            JOIN evaluations AS e
              ON e.evaluation_id = rp.evaluation_id
            JOIN process_runs AS candidate_process
              ON candidate_process.process_id = rp.candidate_process_id
            JOIN runs AS candidate_run
              ON candidate_run.run_id = candidate_process.run_id
            {where_sql}
            ORDER BY rp.created_at DESC, rp.report_id DESC
            LIMIT ? OFFSET ?
            """,
            [*(parameters or []), limit, offset],
        )
        summaries = [dict(row) for row in rows]
        if with_artifacts:
            for item in summaries:
                item["html_available"] = report_artifact_available(
                    item["report_id"],
                    "html",
                    item["status"],
                )
                item["excel_available"] = report_artifact_available(
                    item["report_id"],
                    "excel",
                    item["status"],
                )
        return summaries

    def threshold_profile_view(row: Any) -> dict[str, Any]:
        """解析参考线方案快照并计算两个 Query Stage 的配置项数量。"""

        item = dict(row)
        try:
            thresholds = normalize_evaluation_thresholds(
                parse_json(row["thresholds_json"], {})
            )
        except ReviewValidationError:
            thresholds = normalize_evaluation_thresholds({})
        item["thresholds"] = thresholds
        item["configured_counts"] = {
            query_stage: sum(
                value is not None
                for value in thresholds[query_stage].values()
            )
            for query_stage in sorted(SUPPORTED_QUERY_STAGES)
        }
        return item

    def active_threshold_profiles() -> list[dict[str, Any]]:
        """返回 Evaluation 创建和更换表单可选择的 ACTIVE 方案。"""

        return [
            threshold_profile_view(row)
            for row in store.fetch_all(
                """
                SELECT * FROM threshold_profiles
                WHERE status = 'ACTIVE'
                ORDER BY name, version DESC
                """
            )
        ]

    def render_imports(
        *,
        status: int = 200,
        errors: list[str] | None = None,
    ) -> tuple[str, int]:
        """渲染导入页所需的 Evaluation 和 Dataset 选项。"""

        evaluations = store.fetch_all(
            "SELECT * FROM evaluations ORDER BY created_at DESC"
        )
        datasets = store.fetch_all(
            "SELECT * FROM datasets ORDER BY created_at DESC"
        )
        return (
            render_template(
                "imports.html",
                evaluations=evaluations,
                datasets=datasets,
                evaluation_phases=sorted(EVALUATION_PHASES),
                errors=errors or [],
            ),
            status,
        )

    def save_upload(upload: Any, directory: Path, role: str) -> Path | None:
        """把上传保存到受控临时目录并校验扩展名。

        返回值:
            未选择文件时返回 ``None``；其他情况返回临时文件绝对路径。

        异常说明:
            ImportValidationError: 文件后缀不受支持或安全文件名为空。
        """

        if upload is None or not upload.filename:
            return None
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            raise ImportValidationError(
                ["上传只支持 .jsonl、.json 或 .xlsx 文件"]
            )
        filename = secure_filename(upload.filename)
        if not filename:
            filename = f"{role}{suffix}"
        target = directory / f"{role}__{filename}"
        upload.save(target)
        return target

    @app.template_filter("status_class")
    def status_class(value: Any) -> str:
        """将状态映射为少量稳定的视觉等级。"""

        text = str(value or "").upper()
        if text in {
            "SUCCESS",
            "COMPLETED",
            "SUCCEEDED",
            "NO_CANDIDATE",
            "HIT",
            "REVIEWED",
            "READY",
            "HAS_CANDIDATES",
            "VALID",
        }:
            return "success"
        if text in {
            "FAILED",
            "PARTIAL_FAILED",
            "PARTIAL_DETAIL_FAILED",
            "INTERRUPTED",
            "NOT_HIT",
            "STALE",
            "EXECUTION_FAILED",
            "ERROR",
        }:
            return "danger"
        if text in {
            "RUNNING",
            "SEARCHING",
            "QUEUED",
            "PENDING",
            "PENDING_REVIEW",
            "SUSPECTED",
        }:
            return "active"
        return "neutral"

    @app.template_filter("format_datetime")
    def format_datetime(value: Any, empty_text: str = "—") -> str:
        """使用服务端统一时区格式化页面和静态报告中的可见时间。"""

        return _format_datetime(value, display_timezone, empty_text)

    @app.template_filter("is_http_url")
    def is_http_url(value: Any) -> bool:
        """仅允许 http/https 字符串显示为可点击 URL。"""

        if not isinstance(value, str):
            return False
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @app.template_filter("is_image_url")
    def is_image_url(value: Any) -> bool:
        """按常见扩展名判断是否展示受控缩略图。"""

        if not is_http_url(value):
            return False
        return Path(urlparse(value).path).suffix.lower() in {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
        }

    @app.get("/")
    def index() -> str:
        """展示 Evaluation 汇总和最近10份报告快捷入口。"""

        evaluations = store.fetch_all(
            """
            SELECT e.*,
                   COUNT(r.run_id) AS run_count,
                   SUM(CASE WHEN r.status = 'RUNNING' THEN 1 ELSE 0 END)
                       AS running_count,
                   MAX(r.created_at) AS latest_run_at
            FROM evaluations AS e
            LEFT JOIN runs AS r ON r.evaluation_id = e.evaluation_id
            GROUP BY e.evaluation_id
            ORDER BY e.updated_at DESC
            """
        )
        recent_reports = report_summary_rows(limit=10)
        return render_template(
            "index.html",
            evaluations=evaluations,
            recent_reports=recent_reports,
        )

    @app.get("/reports")
    def reports() -> str:
        """按固定条件筛选报告摘要，并提供每页50条服务端分页。"""

        page = page_number()
        per_page = 50
        filters = {
            "evaluation_id": request.args.get(
                "evaluation_id",
                "",
            ).strip(),
            "system_version": request.args.get(
                "system_version",
                "",
            ).strip(),
            "report_type": request.args.get(
                "report_type",
                "",
            ).strip().upper(),
            "status": request.args.get("status", "").strip().upper(),
        }
        if filters["report_type"] not in REPORT_TYPES:
            filters["report_type"] = ""
        if filters["status"] not in REPORT_STATUSES:
            filters["status"] = ""

        where: list[str] = []
        parameters: list[Any] = []
        if filters["evaluation_id"]:
            where.append("rp.evaluation_id = ?")
            parameters.append(filters["evaluation_id"])
        if filters["system_version"]:
            escaped_keyword = (
                filters["system_version"]
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            where.append(
                "candidate_run.system_version LIKE ? ESCAPE '\\'"
            )
            parameters.append(f"%{escaped_keyword}%")
        if filters["report_type"]:
            where.append("rp.report_type = ?")
            parameters.append(filters["report_type"])
        if filters["status"]:
            where.append("rp.status = ?")
            parameters.append(filters["status"])

        where_sql = (
            f"WHERE {' AND '.join(where)}"
            if where
            else ""
        )
        total = store.fetch_one(
            f"""
            SELECT COUNT(*) AS count
            FROM reports AS rp
            JOIN process_runs AS candidate_process
              ON candidate_process.process_id = rp.candidate_process_id
            JOIN runs AS candidate_run
              ON candidate_run.run_id = candidate_process.run_id
            {where_sql}
            """,
            parameters,
        )["count"]
        rows = report_summary_rows(
            where,
            parameters,
            limit=per_page,
            offset=(page - 1) * per_page,
            with_artifacts=True,
        )
        evaluations = store.fetch_all(
            """
            SELECT evaluation_id, name
            FROM evaluations
            ORDER BY updated_at DESC
            """
        )
        return render_template(
            "reports.html",
            reports=rows,
            evaluations=evaluations,
            filters=filters,
            report_types=sorted(REPORT_TYPES),
            report_statuses=sorted(REPORT_STATUSES),
            page=page,
            per_page=per_page,
            total=total,
        )

    @app.get("/threshold-profiles")
    def threshold_profiles() -> str:
        """展示全部参考线方案版本，包括已归档的历史版本。"""

        profiles = [
            threshold_profile_view(row)
            for row in store.fetch_all(
                """
                SELECT tp.*,
                       COUNT(e.evaluation_id) AS evaluation_count
                FROM threshold_profiles AS tp
                LEFT JOIN evaluations AS e
                  ON e.threshold_profile_id = tp.profile_id
                GROUP BY tp.profile_id
                ORDER BY tp.created_at DESC
                """
            )
        ]
        return render_template(
            "threshold_profiles.html",
            profiles=profiles,
        )

    @app.get("/threshold-profiles/new")
    def threshold_profile_new() -> str:
        """显示独立参考线方案创建表单。"""

        return render_template(
            "threshold_profile_new.html",
            thresholds=normalize_evaluation_thresholds({}),
            threshold_fields=EVALUATION_THRESHOLD_FIELDS,
            form=None,
            based_on_profile_id="",
        )

    @app.post("/threshold-profiles")
    def threshold_profile_create() -> Response | tuple[str, int]:
        """校验并创建一个不可变参考线方案版本。"""

        try:
            version = int(request.form.get("version", ""))
            profile = service.create_threshold_profile(
                profile_id=request.form.get("profile_id", "").strip(),
                name=request.form.get("name", "").strip(),
                description=request.form.get("description", "").strip(),
                version=version,
                thresholds=_threshold_form_payload(request.form),
                based_on_profile_id=request.form.get(
                    "based_on_profile_id",
                    "",
                ).strip()
                or None,
            )
        except (ValueError, ReviewValidationError) as exc:
            return (
                render_template(
                    "threshold_profile_new.html",
                    errors=[f"创建参考线方案失败: {exc}"],
                    form=request.form,
                    thresholds=_threshold_form_payload(request.form),
                    threshold_fields=EVALUATION_THRESHOLD_FIELDS,
                    based_on_profile_id=request.form.get(
                        "based_on_profile_id",
                        "",
                    ),
                ),
                400,
            )
        flash(
            f"参考线方案 {profile['name']} v{profile['version']} 已创建",
            "success",
        )
        return redirect(
            url_for(
                "threshold_profile_detail",
                profile_id=profile["profile_id"],
            )
        )

    @app.get("/threshold-profiles/<profile_id>")
    def threshold_profile_detail(profile_id: str) -> str:
        """展示不可变方案内容、来源版本和当前 Evaluation 引用。"""

        row = store.fetch_one(
            """
            SELECT tp.*, source.name AS source_name,
                   source.version AS source_version
            FROM threshold_profiles AS tp
            LEFT JOIN threshold_profiles AS source
              ON source.profile_id = tp.based_on_profile_id
            WHERE tp.profile_id = ?
            """,
            (profile_id,),
        )
        if row is None:
            abort(404)
        evaluations = store.fetch_all(
            """
            SELECT evaluation_id, name
            FROM evaluations WHERE threshold_profile_id = ?
            ORDER BY updated_at DESC
            """,
            (profile_id,),
        )
        return render_template(
            "threshold_profile_detail.html",
            profile=threshold_profile_view(row),
            evaluations=evaluations,
            threshold_fields=EVALUATION_THRESHOLD_FIELDS,
        )

    @app.get("/threshold-profiles/<profile_id>/copy")
    def threshold_profile_copy(profile_id: str) -> str:
        """基于任一历史版本预填新版本表单，不修改来源记录。"""

        row = store.fetch_one(
            "SELECT * FROM threshold_profiles WHERE profile_id = ?",
            (profile_id,),
        )
        if row is None:
            abort(404)
        source = threshold_profile_view(row)
        next_version = store.fetch_one(
            """
            SELECT COALESCE(MAX(version), 0) + 1 AS version
            FROM threshold_profiles WHERE name = ?
            """,
            (row["name"],),
        )["version"]
        form = {
            "profile_id": "",
            "name": row["name"],
            "description": row["description"],
            "version": next_version,
        }
        return render_template(
            "threshold_profile_new.html",
            form=form,
            thresholds=source["thresholds"],
            threshold_fields=EVALUATION_THRESHOLD_FIELDS,
            based_on_profile_id=profile_id,
        )

    @app.post("/threshold-profiles/<profile_id>/archive")
    def threshold_profile_archive(profile_id: str) -> Response:
        """归档方案但保留所有历史引用和详情。"""

        try:
            service.archive_threshold_profile(profile_id)
        except ReviewValidationError as exc:
            abort(404, str(exc))
        flash("参考线方案已归档，历史 Evaluation 仍可查看", "success")
        return redirect(
            url_for(
                "threshold_profile_detail",
                profile_id=profile_id,
            )
        )

    @app.route("/evaluations/new", methods=["GET", "POST"])
    def evaluation_new() -> Response | str | tuple[str, int]:
        """创建评测；重复或非法标识返回可行动错误。"""

        profiles = active_threshold_profiles()
        if request.method == "GET":
            return render_template(
                "evaluation_new.html",
                threshold_profiles=profiles,
            )
        try:
            evaluation_id = request.form.get("evaluation_id", "").strip()
            service.create_evaluation(
                evaluation_id=evaluation_id,
                name=request.form.get("name", "").strip(),
                notes=request.form.get("notes", "").strip(),
                threshold_profile_id=request.form.get(
                    "threshold_profile_id",
                    "",
                ).strip()
                or None,
            )
        except Exception as exc:
            return (
                render_template(
                    "evaluation_new.html",
                    errors=[f"创建评测失败: {exc}"],
                    form=request.form,
                    threshold_profiles=profiles,
                ),
                400,
            )
        flash("评测创建成功", "success")
        return redirect(
            url_for(
                "evaluation_detail",
                evaluation_id=evaluation_id,
            )
        )

    @app.get("/evaluations/<evaluation_id>")
    def evaluation_detail(evaluation_id: str) -> str:
        """展示一个 Evaluation 下的 Run 和可执行 Dataset。"""

        evaluation = store.fetch_one(
            """
            SELECT e.*, tp.name AS threshold_profile_name,
                   tp.version AS threshold_profile_version,
                   tp.status AS threshold_profile_status
            FROM evaluations AS e
            LEFT JOIN threshold_profiles AS tp
              ON tp.profile_id = e.threshold_profile_id
            WHERE e.evaluation_id = ?
            """,
            (evaluation_id,),
        )
        if evaluation is None:
            abort(404)
        try:
            thresholds = normalize_evaluation_thresholds(
                parse_json(evaluation["thresholds_json"], {})
            )
        except ReviewValidationError:
            thresholds = normalize_evaluation_thresholds({})
        runs = store.fetch_all(
            """
            SELECT * FROM runs
            WHERE evaluation_id = ?
            ORDER BY created_at DESC
            """,
            (evaluation_id,),
        )
        datasets = store.fetch_all(
            "SELECT * FROM datasets ORDER BY created_at DESC"
        )
        reports = store.fetch_all(
            """
            SELECT rp.*, pr.run_id, r.run_label, r.system_version,
                   CASE WHEN json_valid(rp.metrics_json)
                        THEN json_extract(
                            rp.metrics_json, '$.metadata.report_name'
                        )
                        ELSE NULL END AS report_name
            FROM reports AS rp
            JOIN process_runs AS pr
              ON pr.process_id = rp.candidate_process_id
            JOIN runs AS r ON r.run_id = pr.run_id
            WHERE rp.evaluation_id = ?
            ORDER BY rp.created_at DESC
            """,
            (evaluation_id,),
        )
        return render_template(
            "evaluation_detail.html",
            evaluation=evaluation,
            runs=runs,
            datasets=datasets,
            reports=reports,
            thresholds=thresholds,
            configured_counts={
                query_stage: sum(
                    value is not None
                    for value in thresholds[query_stage].values()
                )
                for query_stage in sorted(SUPPORTED_QUERY_STAGES)
            },
            threshold_profiles=active_threshold_profiles(),
            evaluation_phases=sorted(
                phase
                for phase in EVALUATION_PHASES
                if phase != "UNSPECIFIED"
            ),
        )

    @app.post("/evaluations/<evaluation_id>/threshold-profile")
    def evaluation_threshold_profile_update(
        evaluation_id: str,
    ) -> Response | tuple[str, int]:
        """更换 Evaluation 方案快照，只影响以后生成的新报告。"""

        try:
            service.assign_evaluation_threshold_profile(
                evaluation_id,
                request.form.get("threshold_profile_id", "").strip()
                or None,
            )
        except ReviewValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="无法更换参考线方案",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash("参考线方案已更新；既有报告保持原快照和建议", "success")
        return redirect(
            url_for(
                "evaluation_detail",
                evaluation_id=evaluation_id,
            )
        )

    @app.post("/evaluations/<evaluation_id>/thresholds")
    def evaluation_thresholds_update(
        evaluation_id: str,
    ) -> Response | tuple[str, int]:
        """校验并保存 Evaluation 参考线，非法提交不覆盖旧值。"""

        try:
            service.update_evaluation_thresholds(
                evaluation_id,
                _threshold_form_payload(request.form),
            )
        except ReviewValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="无法保存参考线",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash("参考线已保存；既有报告仍保留生成时快照", "success")
        return redirect(
            url_for(
                "evaluation_detail",
                evaluation_id=evaluation_id,
            )
        )

    @app.post("/evaluations/<evaluation_id>/runs")
    def run_create(evaluation_id: str) -> Response | tuple[str, int]:
        """创建执行 Run 并立即提交给单线程后台协调器。"""

        try:
            coordinator = app.extensions["run_coordinator"]
            prepare = getattr(coordinator, "prepare_run_client", None)
            prepared_client, release_id, credential_version = (
                prepare() if callable(prepare) else (None, None, None)
            )
            run_id = service.create_execution_run(
                evaluation_id=evaluation_id,
                dataset_id=request.form.get("dataset_id", "").strip(),
                run_label=request.form.get("run_label", "").strip(),
                system_version=request.form.get("system_version", "").strip(),
                evaluation_phase=request.form.get(
                    "evaluation_phase",
                    "",
                ).strip(),
                platform_release_id=release_id,
                platform_credential_version=credential_version,
            )
            if prepared_client is None:
                coordinator.submit(run_id)
            else:
                coordinator.submit(run_id, prepared_client)
        except ActiveRunError as exc:
            return (
                render_template(
                    "error.html",
                    title="无法启动新的执行",
                    message=str(exc),
                    status_code=409,
                ),
                409,
            )
        except RuntimeError as exc:
            return (
                render_template(
                    "error.html",
                    title="平台配置暂时不可用",
                    message=str(exc),
                    status_code=503,
                ),
                503,
            )
        except (ImportValidationError, ValueError) as exc:
            return (
                render_template(
                    "error.html",
                    title="执行参数错误",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash("Run 已进入后台执行队列", "success")
        return redirect(url_for("run_detail", run_id=run_id))

    @app.get("/runs/<run_id>")
    def run_detail(run_id: str) -> str:
        """服务端分页展示 Run 的 Query、失败和最新进度。"""

        run = store.fetch_one(
            """
            SELECT r.*, e.name AS evaluation_name
            FROM runs AS r
            JOIN evaluations AS e ON e.evaluation_id = r.evaluation_id
            WHERE r.run_id = ?
            """,
            (run_id,),
        )
        if run is None:
            abort(404)
        page = page_number()
        per_page = 50
        keyword = request.args.get("q", "").strip()
        status = request.args.get("status", "").strip()
        result_status = request.args.get("result_status", "").strip()
        query_stage = request.args.get("query_stage", "").strip()
        sort = request.args.get("sort", "query_id")
        direction = request.args.get("direction", "asc").lower()
        sort_columns = {
            "query_id": "query_id",
            "person_id": "person_id",
            "query_stage": "query_stage",
            "status": "status",
            "result_status": "result_status",
            "candidate_count_listed": "candidate_count_listed",
            "detail_failure_count": "detail_failure_count",
        }
        sort_column = sort_columns.get(sort, "query_id")
        sort_direction = "DESC" if direction == "desc" else "ASC"
        where = ["run_id = ?"]
        parameters: list[Any] = [run_id]
        if keyword:
            where.append(
                "(query_id LIKE ? OR COALESCE(person_id, '') LIKE ? "
                "OR COALESCE(task_id, '') LIKE ?)"
            )
            wildcard = f"%{keyword}%"
            parameters.extend([wildcard, wildcard, wildcard])
        if status in QUERY_STATUSES:
            where.append("status = ?")
            parameters.append(status)
        if result_status in RESULT_STATUSES:
            where.append("result_status = ?")
            parameters.append(result_status)
        if query_stage in QUERY_STAGES:
            where.append("query_stage = ?")
            parameters.append(query_stage)
        where_sql = " AND ".join(where)
        total = store.fetch_one(
            f"SELECT COUNT(*) AS count FROM run_queries WHERE {where_sql}",
            parameters,
        )["count"]
        queries = store.fetch_all(
            f"""
            SELECT * FROM run_queries
            WHERE {where_sql}
            ORDER BY {sort_column} {sort_direction}, query_id ASC
            LIMIT ? OFFSET ?
            """,
            [*parameters, per_page, (page - 1) * per_page],
        )
        failures = store.fetch_all(
            """
            SELECT * FROM failures
            WHERE run_id = ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (run_id,),
        )
        field_schemas = store.fetch_all(
            """
            SELECT schema_version, name, is_active
            FROM field_schemas
            ORDER BY is_active DESC, created_at DESC
            """
        )
        process_runs = store.fetch_all(
            """
            SELECT pr.*, fs.name AS schema_name
            FROM process_runs AS pr
            JOIN field_schemas AS fs
              ON fs.schema_version = pr.schema_version
            WHERE pr.run_id = ?
            ORDER BY pr.created_at DESC
            """,
            (run_id,),
        )
        baseline_sets = store.fetch_all(
            """
            SELECT bs.baseline_version, bs.name, COUNT(bp.person_id) AS person_count
            FROM baseline_sets AS bs
            LEFT JOIN baseline_people AS bp
              ON bp.baseline_version = bs.baseline_version
            GROUP BY bs.baseline_version
            ORDER BY bs.created_at DESC
            """
        )
        if baseline_sets:
            person_link_context = service.get_run_person_link_context(
                run_id,
                baseline_sets[0]["baseline_version"],
            )
            person_link_summary = person_link_context["summary"]
            person_link_baseline_version = baseline_sets[0][
                "baseline_version"
            ]
        else:
            person_link_summary = {
                "query_count": run["total_queries"],
                "linked_count": 0,
                "unlinked_count": run["total_queries"],
                "invalid_count": 0,
                "unique_suggestion_count": 0,
            }
            person_link_baseline_version = ""
        alignment_issues: list[dict[str, Any]] = []
        if field_schemas and baseline_sets:
            try:
                alignment_issues = service.validate_process_field_alignment(
                    field_schemas[0]["schema_version"],
                    baseline_sets[0]["baseline_version"],
                )
            except FieldSchemaValidationError:
                alignment_issues = []
        result_status_counts = {
            row["result_status"]: row["count"]
            for row in store.fetch_all(
                """
                SELECT COALESCE(result_status, 'UNSPECIFIED') AS result_status,
                       COUNT(*) AS count
                FROM run_queries WHERE run_id = ?
                GROUP BY COALESCE(result_status, 'UNSPECIFIED')
                """,
                (run_id,),
            )
        }
        return render_template(
            "run_detail.html",
            run=run,
            queries=queries,
            failures=failures,
            field_schemas=field_schemas,
            baseline_sets=baseline_sets,
            process_runs=process_runs,
            page=page,
            per_page=per_page,
            total=total,
            filters={
                "q": keyword,
                "status": status,
                "result_status": result_status,
                "query_stage": query_stage,
                "sort": sort,
                "direction": direction,
            },
            terminal_statuses=TERMINAL_RUN_STATUSES,
            result_status_counts=result_status_counts,
            evaluation_phases=sorted(EVALUATION_PHASES),
            person_link_summary=person_link_summary,
            person_link_baseline_version=person_link_baseline_version,
            alignment_issues=alignment_issues,
        )

    @app.post("/runs/<run_id>/evaluation-phase")
    def run_evaluation_phase_update(run_id: str) -> Response | tuple[str, int]:
        """人工补录或修正 Run 评估阶段，不根据名称自动猜测。"""

        try:
            service.update_run_evaluation_phase(
                run_id,
                request.form.get("evaluation_phase", "").strip(),
            )
        except ImportValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="评估阶段更新失败",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash("Evaluation Phase 已更新", "success")
        return redirect(url_for("run_detail", run_id=run_id))

    @app.route("/runs/<run_id>/person-links", methods=["GET", "POST"])
    def run_person_links(run_id: str) -> Response | str | tuple[str, int]:
        """查看并原子保存历史 Run Query 的人物关联。

        GET 只生成精确姓名建议，不自动写入；POST 支持 JSON 批量提交和
        无 JavaScript 的逐行表单提交。乐观锁冲突返回409，其余校验错误
        返回400。
        """

        baseline_sets = store.fetch_all(
            """
            SELECT bs.baseline_version, bs.name,
                   COUNT(bp.person_id) AS person_count
            FROM baseline_sets AS bs
            LEFT JOIN baseline_people AS bp
              ON bp.baseline_version = bs.baseline_version
            GROUP BY bs.baseline_version
            ORDER BY bs.created_at DESC
            """
        )
        baseline_version = (
            request.values.get("baseline_version", "").strip()
        )
        if not baseline_version and baseline_sets:
            baseline_version = baseline_sets[0]["baseline_version"]
        if request.method == "POST":
            raw_changes = request.form.get("changes_json", "").strip()
            if raw_changes:
                try:
                    changes = json.loads(raw_changes)
                except json.JSONDecodeError:
                    return (
                        render_template(
                            "error.html",
                            title="人物关联保存失败",
                            message="changes_json 必须是合法 JSON 数组",
                            status_code=400,
                        ),
                        400,
                    )
            else:
                changes = []
                for key, value in request.form.items():
                    if not key.startswith("person_id__"):
                        continue
                    query_id = key.removeprefix("person_id__")
                    changes.append(
                        {
                            "query_id": query_id,
                            "expected_person_id": request.form.get(
                                f"expected_person_id__{query_id}",
                                "",
                            )
                            or None,
                            "person_id": value or None,
                        }
                    )
            try:
                result = service.update_run_query_person_links(
                    run_id,
                    baseline_version,
                    changes,
                    sync_dataset=_boolean_value(
                        request.form.get("sync_dataset"),
                    ),
                    note=request.form.get("note", ""),
                )
            except PersonLinkValidationError as exc:
                status_code = (
                    409 if "已被其他页面修改" in str(exc) else 400
                )
                return (
                    render_template(
                        "error.html",
                        title="人物关联保存失败",
                        message=str(exc),
                        status_code=status_code,
                    ),
                    status_code,
                )
            flash(
                "人物关联已保存："
                f"Run 更新 {result['updated_count']} 条，"
                f"Dataset 同步 {result['dataset_synced_count']} 条，"
                f"过期报告 {result['stale_report_count']} 份",
                "success",
            )
            return redirect(
                url_for(
                    "run_person_links",
                    run_id=run_id,
                    baseline_version=baseline_version,
                )
            )

        if not baseline_version:
            run = store.fetch_one(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            )
            if run is None:
                abort(404)
            return render_template(
                "run_person_links.html",
                run=run,
                baseline_sets=baseline_sets,
                context=None,
                filters={"q": "", "status": ""},
            )
        try:
            context = service.get_run_person_link_context(
                run_id,
                baseline_version,
            )
        except PersonLinkValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="人物关联加载失败",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        keyword = request.args.get("q", "").strip()
        link_status = request.args.get("status", "").strip()
        filtered_queries = []
        normalized_keyword = keyword.casefold()
        for item in context["queries"]:
            if normalized_keyword and normalized_keyword not in " ".join(
                [
                    item["query_id"],
                    item["query_name"],
                    item["current_person_id"] or "",
                ]
            ).casefold():
                continue
            if link_status == "linked" and not (
                item["current_person_id"] and item["current_baseline_exists"]
            ):
                continue
            if link_status == "unlinked" and item["current_person_id"]:
                continue
            if link_status == "invalid" and not (
                item["current_person_id"]
                and not item["current_baseline_exists"]
            ):
                continue
            if link_status == "unique" and not item["has_unique_suggestion"]:
                continue
            if link_status == "multiple" and len(item["suggestions"]) <= 1:
                continue
            filtered_queries.append(item)
        context["queries"] = filtered_queries
        return render_template(
            "run_person_links.html",
            run=context["run"],
            baseline_sets=baseline_sets,
            context=context,
            filters={"q": keyword, "status": link_status},
        )

    @app.get("/runs/<run_id>/queries/<query_id>")
    def query_detail(run_id: str, query_id: str) -> str:
        """展示 Query 输入、Task、候选人、失败和 Raw 索引。"""

        query = store.fetch_one(
            """
            SELECT rq.*, r.evaluation_id, r.dataset_id, r.run_label,
                   r.system_version, r.evaluation_phase, r.source_type,
                   r.status AS run_status, dq.clues_json,
                   dq.additional_details_json, dq.metadata_json,
                   dq.match_strategy
            FROM run_queries AS rq
            JOIN runs AS r ON r.run_id = rq.run_id
            LEFT JOIN dataset_queries AS dq
              ON dq.dataset_id = r.dataset_id AND dq.query_id = rq.query_id
            WHERE rq.run_id = ? AND rq.query_id = ?
            """,
            (run_id, query_id),
        )
        if query is None:
            abort(404)
        page = page_number()
        per_page = 50
        candidate_total = store.fetch_one(
            """
            SELECT COUNT(*) AS count FROM candidates
            WHERE run_id = ? AND query_id = ?
            """,
            (run_id, query_id),
        )["count"]
        candidates = store.fetch_all(
            """
            SELECT * FROM candidates
            WHERE run_id = ? AND query_id = ?
            ORDER BY candidate_rank
            LIMIT ? OFFSET ?
            """,
            (run_id, query_id, per_page, (page - 1) * per_page),
        )
        raw_records = store.fetch_all(
            """
            SELECT raw_id, stage, sequence_no, candidate_pk, collected_at
            FROM raw_records
            WHERE run_id = ? AND query_id = ?
            ORDER BY collected_at, sequence_no
            """,
            (run_id, query_id),
        )
        failures = store.fetch_all(
            """
            SELECT * FROM failures
            WHERE run_id = ? AND query_id = ?
            ORDER BY created_at
            """,
            (run_id, query_id),
        )
        input_payload = {
            "match_strategy": query["match_strategy"],
            "clues": parse_json(query["clues_json"], []),
            "additional_details": parse_json(
                query["additional_details_json"],
                [],
            ),
            "metadata": parse_json(query["metadata_json"], {}),
        }
        task_field_states = []
        for field_key, expected_type in [
            ("llm_cost", "number"),
            ("third_party_cost", "number"),
            ("total_cost", "number"),
            ("pdl_called", "boolean"),
            ("search_duration_ms", "integer"),
        ]:
            value = query[field_key]
            if value is None:
                data_status = "MISSING"
            elif expected_type == "number" and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
            ):
                data_status = "ERROR"
            elif expected_type == "boolean" and value not in {0, 1, False, True}:
                data_status = "ERROR"
            elif expected_type == "integer" and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                data_status = "ERROR"
            else:
                data_status = "VALID"
            task_field_states.append(
                {
                    "field_key": field_key,
                    "value": value,
                    "data_status": data_status,
                }
            )
        return render_template(
            "query_detail.html",
            query=query,
            candidates=candidates,
            candidate_total=candidate_total,
            raw_records=raw_records,
            failures=failures,
            input_payload=input_payload,
            task_field_states=task_field_states,
            public_fields=parse_json(query["public_fields_json"], {}),
            retry_allowed=(
                query["status"] in {"FAILED", "PENDING"}
                and query["source_type"] == "EXECUTION"
                and query["run_status"] not in {"PENDING", "RUNNING"}
            ),
            page=page,
            per_page=per_page,
        )

    @app.post("/runs/<run_id>/queries/<query_id>/retry")
    def query_retry(run_id: str, query_id: str) -> Response | tuple[str, int]:
        """校验后在原 Run 中排队重跑单条失败或中断 Query。"""

        try:
            service.validate_query_retry(run_id, query_id)
            app.extensions["run_coordinator"].submit_query_retry(run_id, query_id)
        except ActiveRunError as exc:
            return render_template("error.html", message=str(exc)), 409
        except (ImportValidationError, ValueError) as exc:
            return render_template("error.html", message=str(exc)), 400
        flash("该 Query 已进入重跑队列；会产生新的检索成本，结果仍归入当前 Run", "success")
        return redirect(url_for("query_detail", run_id=run_id, query_id=query_id))

    @app.get("/candidates/<candidate_pk>")
    def candidate_detail(candidate_pk: str) -> str:
        """展示 Candidate 五个业务模块和按需加载的 Detail Raw。"""

        candidate = store.fetch_one(
            """
            SELECT c.*, r.evaluation_id, r.run_label, r.system_version
            FROM candidates AS c
            JOIN runs AS r ON r.run_id = c.run_id
            WHERE c.candidate_pk = ?
            """,
            (candidate_pk,),
        )
        if candidate is None:
            abort(404)
        raw_records = store.fetch_all(
            """
            SELECT raw_id, stage, sequence_no, collected_at
            FROM raw_records
            WHERE candidate_pk = ?
            ORDER BY collected_at, sequence_no
            """,
            (candidate_pk,),
        )
        ui_sections = parse_json(candidate["ui_sections_json"], {})
        # 候选人详情优先展示 Summary 的稳定识别信息；模块原始字段仍完整保留在页面中。
        summary_section = ui_sections.get("summary", {})
        summary_data = (
            summary_section.get("data", {})
            if isinstance(summary_section, dict)
            else {}
        )
        if not isinstance(summary_data, dict):
            summary_data = {}
        candidate_view = {
            "display_name": summary_data.get("display_name") or candidate["candidate_id"],
            "headline": summary_data.get("headline") or "未返回职业或简介",
            "location": summary_data.get("location") or "未返回地点",
            "confidence": summary_data.get("confidence_level") or "未返回",
            "match_score": summary_data.get("match_score"),
            "avatar_url": summary_data.get("avatar_url") or "",
            "profile_url": summary_data.get("profile_url") or "",
            "match_reasons": summary_data.get("match_reasons") or [],
        }
        requested_process_id = request.args.get("process_id", "").strip()
        if requested_process_id:
            processed = store.fetch_one(
                """
                SELECT pc.*, pr.schema_version, pr.status AS process_status,
                       fs.name AS schema_name, fs.definitions_json
                FROM processed_candidates AS pc
                JOIN process_runs AS pr ON pr.process_id = pc.process_id
                JOIN field_schemas AS fs
                  ON fs.schema_version = pr.schema_version
                WHERE pc.candidate_pk = ? AND pc.process_id = ?
                """,
                (candidate_pk, requested_process_id),
            )
        else:
            processed = store.fetch_one(
                """
                SELECT pc.*, pr.schema_version, pr.status AS process_status,
                       fs.name AS schema_name, fs.definitions_json
                FROM processed_candidates AS pc
                JOIN process_runs AS pr ON pr.process_id = pc.process_id
                JOIN field_schemas AS fs
                  ON fs.schema_version = pr.schema_version
                WHERE pc.candidate_pk = ? AND pr.status = 'COMPLETED'
                ORDER BY pr.created_at DESC LIMIT 1
                """,
                (candidate_pk,),
            )
        processed_view = None
        review_context = None
        if processed is not None:
            definitions = parse_json(processed["definitions_json"], [])
            definitions_by_key = {
                item.get("field_key"): item
                for item in definitions
                if isinstance(item, dict) and item.get("field_key")
            }
            all_processed_fields = parse_json(processed["fields_json"], {})
            # 字段配置中的“展示”开关仅影响候选人详情的阅读视图，不影响
            # 已入库的处理结果、指标或报告快照。这样像 Profile Data 这类
            # 容器字段可保留在历史数据中，却不会和其原子化内容重复出现。
            visible_processed_fields = {
                field_key: value
                for field_key, value in all_processed_fields.items()
                if definitions_by_key.get(field_key, {}).get(
                    "display_enabled", True
                )
                # Profile Data 只是 Profile Sections 的原始容器；两者同时
                # 存在时仅展示已归一化的 Sections，避免旧 Process 页面重复。
                and not (
                    field_key == "profile_data"
                    and "profile_sections" in all_processed_fields
                )
            }
            processed_view = {
                "process_id": processed["process_id"],
                "schema_version": processed["schema_version"],
                "schema_name": processed["schema_name"],
                "fields": visible_processed_fields,
                "empty_fields": parse_json(
                    processed["empty_fields_json"],
                    {},
                ),
                "errors": parse_json(
                    processed["processing_errors_json"],
                    [],
                ),
                "definitions": definitions_by_key,
            }
            try:
                review_context = service.get_review_context(
                    processed["process_id"],
                    candidate_pk,
                )
            except ReviewValidationError:
                # 历史损坏数据仍允许查看 Raw，复核区显示为不可用。
                review_context = None
        return render_template(
            "candidate_detail.html",
            candidate=candidate,
            candidate_view=candidate_view,
            ui_sections=ui_sections,
            detail_data=parse_json(candidate["detail_data_json"], {}),
            list_item=parse_json(candidate["list_item_json"], {}),
            raw_records=raw_records,
            processed=processed_view,
            review=review_context,
        )

    @app.route("/imports", methods=["GET", "POST"])
    def imports() -> Response | tuple[str, int]:
        """通过受控上传导入 Dataset 或历史 JSONL/Excel 结果。"""

        if request.method == "GET":
            return render_imports()
        upload_root = data_dir / ".uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(
                prefix="web-import-",
                dir=upload_root,
            ) as temp_dir:
                temp_path = Path(temp_dir)
                source = save_upload(
                    request.files.get("source_file"),
                    temp_path,
                    "source",
                )
                if source is None:
                    raise ImportValidationError(["请选择需要导入的文件"])
                import_type = request.form.get("import_type", "")
                if import_type == "dataset":
                    name = request.form.get("name", "").strip()
                    if not name:
                        raise ImportValidationError(["数据集名称不能为空"])
                    dataset_id = request.form.get("dataset_id", "").strip() or None
                    if source.suffix.lower() == ".xlsx":
                        result = service.import_dataset_excel(
                            source,
                            name=name,
                            dataset_id=dataset_id,
                        )
                    elif source.suffix.lower() == ".jsonl":
                        result = service.import_dataset_jsonl(
                            source,
                            name=name,
                            dataset_id=dataset_id,
                        )
                    else:
                        raise ImportValidationError(
                            ["Dataset 只支持 .jsonl 或 .xlsx"]
                        )
                    flash(
                        f"Dataset 导入成功，共 {result.imported_count} 条 Query",
                        "success",
                    )
                    return redirect(url_for("imports"))
                if import_type == "results_jsonl":
                    evaluation_id = request.form.get(
                        "evaluation_id",
                        "",
                    ).strip()
                    run_label = request.form.get("run_label", "").strip()
                    system_version = request.form.get(
                        "system_version",
                        "",
                    ).strip()
                    evaluation_phase = request.form.get(
                        "evaluation_phase",
                        "UNSPECIFIED",
                    ).strip()
                    if not evaluation_id or not run_label or not system_version:
                        raise ImportValidationError(
                            ["Evaluation、run_label 和 system_version 不能为空"]
                        )
                    if source.suffix.lower() != ".jsonl":
                        raise ImportValidationError(
                            ["历史 JSONL 结果必须使用 .jsonl 文件"]
                        )
                    failures = save_upload(
                        request.files.get("failures_file"),
                        temp_path,
                        "failures",
                    )
                    metadata = save_upload(
                        request.files.get("metadata_file"),
                        temp_path,
                        "metadata",
                    )
                    result = service.import_results_jsonl(
                        source,
                        evaluation_id=evaluation_id,
                        run_label=run_label,
                        system_version=system_version,
                        evaluation_phase=evaluation_phase,
                        failures_path=failures,
                        metadata_path=metadata,
                    )
                elif import_type == "results_excel":
                    evaluation_id = request.form.get(
                        "evaluation_id",
                        "",
                    ).strip()
                    run_label = request.form.get("run_label", "").strip()
                    system_version = request.form.get(
                        "system_version",
                        "",
                    ).strip()
                    evaluation_phase = request.form.get(
                        "evaluation_phase",
                        "UNSPECIFIED",
                    ).strip()
                    if not evaluation_id or not run_label or not system_version:
                        raise ImportValidationError(
                            ["Evaluation、run_label 和 system_version 不能为空"]
                        )
                    if source.suffix.lower() != ".xlsx":
                        raise ImportValidationError(
                            ["历史 Excel 结果必须使用 .xlsx 文件"]
                        )
                    result = service.import_results_excel(
                        source,
                        evaluation_id=evaluation_id,
                        run_label=run_label,
                        system_version=system_version,
                        evaluation_phase=evaluation_phase,
                    )
                else:
                    raise ImportValidationError(["请选择有效的导入类型"])
            flash(
                f"历史结果导入成功，共 {result.imported_count} 条 Query",
                "success",
            )
            return redirect(url_for("run_detail", run_id=result.object_id))
        except (
            ImportValidationError,
            DuplicateImportError,
            ValueError,
        ) as exc:
            errors = getattr(exc, "errors", None) or [str(exc)]
            return render_imports(status=400, errors=errors)

    @app.route("/baselines", methods=["GET", "POST"])
    def baselines() -> Response | str | tuple[str, int]:
        """导入版本化 Person 基准并分页查看人物记录。"""

        errors: list[str] = []
        if request.method == "POST":
            upload_root = data_dir / ".uploads"
            upload_root.mkdir(parents=True, exist_ok=True)
            try:
                with tempfile.TemporaryDirectory(
                    prefix="web-baseline-",
                    dir=upload_root,
                ) as temp_dir:
                    source = save_upload(
                        request.files.get("source_file"),
                        Path(temp_dir),
                        "baseline",
                    )
                    if source is None:
                        raise ImportValidationError(["请选择基准数据文件"])
                    name = request.form.get("name", "").strip()
                    baseline_version = request.form.get(
                        "baseline_version",
                        "",
                    ).strip()
                    if not name or not baseline_version:
                        raise ImportValidationError(
                            ["基准名称和 baseline_version 不能为空"]
                        )
                    if source.suffix.lower() == ".jsonl":
                        result = service.import_baseline_jsonl(
                            source,
                            name=name,
                            baseline_version=baseline_version,
                        )
                    elif source.suffix.lower() == ".xlsx":
                        result = service.import_baseline_excel(
                            source,
                            name=name,
                            baseline_version=baseline_version,
                        )
                    else:
                        raise ImportValidationError(
                            ["基准数据只支持 .jsonl 或 .xlsx"]
                        )
                flash(
                    f"基准导入成功，共 {result.imported_count} 人",
                    "success",
                )
                return redirect(
                    url_for(
                        "baselines",
                        baseline_version=result.object_id,
                    )
                )
            except (
                ImportValidationError,
                DuplicateImportError,
                ValueError,
            ) as exc:
                errors = getattr(exc, "errors", None) or [str(exc)]

        baseline_sets = store.fetch_all(
            """
            SELECT bs.*, COUNT(bp.person_id) AS person_count
            FROM baseline_sets AS bs
            LEFT JOIN baseline_people AS bp
              ON bp.baseline_version = bs.baseline_version
            GROUP BY bs.baseline_version
            ORDER BY bs.created_at DESC
            """
        )
        selected_version = request.args.get(
            "baseline_version",
            "",
        ).strip()
        if not selected_version and baseline_sets:
            selected_version = baseline_sets[0]["baseline_version"]
        page = page_number()
        per_page = 50
        people = []
        total = 0
        active_schema = store.fetch_one(
            """
            SELECT schema_version, definitions_json FROM field_schemas
            WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1
            """
        )
        active_definitions = []
        if active_schema is not None:
            try:
                active_definitions = validate_field_definitions(
                    parse_json(active_schema["definitions_json"], [])
                )
            except FieldSchemaValidationError:
                active_definitions = []
        candidate_definitions = {
            definition["field_key"]: definition
            for definition in active_definitions
            if definition["value_scope"] == "CANDIDATE"
            and definition["enabled"]
        }
        if selected_version:
            total_row = store.fetch_one(
                """
                SELECT COUNT(*) AS count FROM baseline_people
                WHERE baseline_version = ?
                """,
                (selected_version,),
            )
            total = total_row["count"] if total_row else 0
            rows = store.fetch_all(
                """
                SELECT * FROM baseline_people
                WHERE baseline_version = ?
                ORDER BY person_id LIMIT ? OFFSET ?
                """,
                (
                    selected_version,
                    per_page,
                    (page - 1) * per_page,
                ),
            )
            for row in rows:
                item = dict(row)
                item["fields"] = parse_json(row["fields_json"], {})
                item["evidence"] = parse_json(row["evidence_json"], {})
                item["available_fields"] = parse_json(
                    row["available_fields_json"],
                    [],
                )
                item["unknown_available_fields"] = [
                    field_key
                    for field_key in item["available_fields"]
                    if field_key not in candidate_definitions
                ]
                field_keys = list(candidate_definitions)
                for field_key in [
                    *item["fields"],
                    *item["available_fields"],
                ]:
                    if field_key not in field_keys:
                        field_keys.append(field_key)
                field_options = []
                for field_key in field_keys:
                    definition = candidate_definitions.get(field_key, {})
                    value = item["fields"].get(field_key)
                    field_options.append(
                        {
                            "field_key": field_key,
                            "display_name": definition.get(
                                "display_name",
                                field_key,
                            ),
                            "module": definition.get(
                                "module",
                                "未配置字段",
                            ),
                            "sort_order": definition.get(
                                "sort_order",
                                9999,
                            ),
                            "data_type": definition.get(
                                "data_type",
                                "unknown",
                            ),
                            "value": value,
                            "has_value": value not in (None, "", [], {}),
                            "unknown": field_key not in candidate_definitions,
                        }
                    )
                # 按用户阅读路径组织字段；未知字段保留在独立分组中，
                # 避免字段配置扩展时丢失已导入的基准数据。
                module_order = (
                    "Candidate",
                    "Summary",
                    "Insights",
                    "Photos",
                    "Profile",
                    "Social",
                    "未配置字段",
                )
                item["field_groups"] = [
                    {
                        "module": module,
                        "fields": sorted(
                            (
                                field
                                for field in field_options
                                if field["module"] == module
                            ),
                            key=lambda field: (
                                field["sort_order"],
                                field["field_key"],
                            ),
                        ),
                    }
                    for module in module_order
                    if any(
                        field["module"] == module
                        for field in field_options
                    )
                ]
                item["valued_field_count"] = sum(
                    field["has_value"] for field in field_options
                )
                # 头像只用于人物识别，优先复用已导入的 Summary 图片。
                item["avatar_url"] = next(
                    (
                        item["fields"].get(field_key)
                        for field_key in (
                            "summary_avatar_url",
                            "summary_primary_image_url",
                        )
                        if item["fields"].get(field_key)
                    ),
                    None,
                )
                people.append(item)
        status = 400 if errors else 200
        return (
            render_template(
                "baselines.html",
                baseline_sets=baseline_sets,
                selected_version=selected_version,
                people=people,
                page=page,
                per_page=per_page,
                total=total,
                active_schema=active_schema,
                errors=errors,
            ),
            status,
        )

    @app.post(
        "/baselines/<baseline_version>/people/<person_id>/available-fields"
    )
    def baseline_available_fields_update(
        baseline_version: str,
        person_id: str,
    ) -> Response | tuple[str, int]:
        """保存人物级可评估字段，来源标记为人工维护。"""

        try:
            service.update_baseline_available_fields(
                baseline_version,
                person_id,
                request.form.getlist("available_fields"),
            )
        except ImportValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="Baseline 可用字段更新失败",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash("Baseline 可用字段已更新", "success")
        return redirect(
            url_for(
                "baselines",
                baseline_version=baseline_version,
            )
        )

    @app.get("/field-schemas")
    def field_schemas() -> str:
        """展示不可变字段配置版本、活跃状态和处理引用次数。"""

        keyword = request.args.get("q", "").strip().casefold()
        module_filter = request.args.get("module", "").strip()
        role_filter = request.args.get("role", "").strip()

        rows = store.fetch_all(
            """
            SELECT fs.*, COUNT(pr.process_id) AS process_count
            FROM field_schemas AS fs
            LEFT JOIN process_runs AS pr
              ON pr.schema_version = fs.schema_version
            GROUP BY fs.schema_version
            ORDER BY fs.is_active DESC, fs.created_at DESC
            """
        )
        schemas = []
        for row in rows:
            item = dict(row)
            try:
                display_definitions = validate_field_definitions(
                    parse_json(row["definitions_json"], [])
                )
            except FieldSchemaValidationError:
                # 历史损坏快照仍可在版本列表中看到，由后续处理页给出错误。
                display_definitions = []
            item["definitions"] = display_definitions
            item["filtered_definitions"] = [
                field
                for field in display_definitions
                if (
                    not module_filter or field["module"] == module_filter
                )
                and (
                    not role_filter
                    or (
                        role_filter == "enabled"
                        and field["enabled"]
                    )
                    or (
                        role_filter == "baseline"
                        and field["baseline_compare_enabled"]
                    )
                    or (
                        role_filter == "identity"
                        and field["identity_enabled"]
                    )
                    or (
                        role_filter == "completeness"
                        and field["completeness_enabled"]
                    )
                    or (
                        role_filter == "accuracy"
                        and field["accuracy_enabled"]
                    )
                )
                and (
                    not keyword
                    or keyword in (
                        field["field_key"] + " " + field["display_name"]
                    ).casefold()
                )
            ]
            item["query_field_count"] = sum(
                field["value_scope"] == "QUERY"
                for field in display_definitions
            )
            item["candidate_field_count"] = sum(
                field["value_scope"] == "CANDIDATE"
                for field in display_definitions
            )
            schemas.append(item)
        return render_template(
            "field_schemas.html",
            schemas=schemas,
            filters={
                "q": request.args.get("q", "").strip(),
                "module": module_filter,
                "role": role_filter,
            },
        )

    @app.route("/field-schemas/new", methods=["GET", "POST"])
    def field_schema_new() -> Response | str | tuple[str, int]:
        """复制已有版本或提交完整 JSON，发布一个新的字段配置版本。"""

        base_version = (
            request.args.get("base", "").strip()
            if request.method == "GET"
            else request.form.get("base_version", "").strip()
        )
        base = None
        if base_version:
            base = store.fetch_one(
                "SELECT * FROM field_schemas WHERE schema_version = ?",
                (base_version,),
            )
            if base is None:
                abort(404)
        if request.method == "GET":
            if base is None:
                base = store.fetch_one(
                    """
                    SELECT * FROM field_schemas
                    WHERE is_active = 1
                    ORDER BY created_at DESC LIMIT 1
                    """
                )
            definitions = parse_json(
                base["definitions_json"] if base is not None else "[]",
                [],
            )
            return render_template(
                "field_schema_new.html",
                base=base,
                form={},
                definitions_json=json.dumps(
                    definitions,
                    ensure_ascii=False,
                    indent=2,
                ),
                errors=[],
            )
        raw_definitions = request.form.get("definitions_json", "")
        try:
            definitions = json.loads(raw_definitions)
            schema_version = service.publish_field_schema(
                name=request.form.get("name", "").strip(),
                definitions=definitions,
                created_by=request.form.get("created_by", "").strip(),
            )
        except (json.JSONDecodeError, FieldSchemaValidationError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                errors = [f"字段配置 JSON 格式错误: {exc.msg}"]
            else:
                errors = exc.errors
            return (
                render_template(
                    "field_schema_new.html",
                    base=base,
                    form=request.form,
                    definitions_json=raw_definitions,
                    errors=errors,
                ),
                400,
            )
        flash(f"字段配置已发布为新版本 {schema_version}", "success")
        return redirect(url_for("field_schemas"))

    @app.route(
        "/field-schemas/<schema_version>/comparison-matrix",
        methods=["GET", "POST"],
    )
    def field_comparison_matrix(
        schema_version: str,
    ) -> str | Response | tuple[str, int]:
        """展示字段矩阵，并从当前不可变 Schema 复制发布新版本。"""

        schema = store.fetch_one(
            "SELECT * FROM field_schemas WHERE schema_version = ?",
            (schema_version,),
        )
        if schema is None:
            abort(404)
        baseline_version = (
            request.values.get("baseline_version", "").strip()
        )
        if not baseline_version:
            latest_baseline = store.fetch_one(
                """
                SELECT baseline_version FROM baseline_sets
                ORDER BY created_at DESC LIMIT 1
                """
            )
            baseline_version = (
                latest_baseline["baseline_version"]
                if latest_baseline is not None
                else ""
            )
        if request.method == "POST":
            try:
                definitions = validate_field_definitions(
                    parse_json(schema["definitions_json"], [])
                )
                enabled_fields = set(
                    request.form.getlist("enabled_fields")
                )
                completeness_fields = set(
                    request.form.getlist("completeness_fields")
                )
                accuracy_fields = set(
                    request.form.getlist("accuracy_fields")
                )
                identity_fields = set(
                    request.form.getlist("identity_fields")
                )
                visible_fields = set(
                    request.form.getlist("visible_fields")
                )
                display_fields = set(request.form.getlist("display_fields"))
                baseline_compare_fields = set(
                    request.form.getlist("baseline_compare_fields")
                )
                run_compare_fields = set(
                    request.form.getlist("run_compare_fields")
                )
                selected_discovered_fields = set(
                    request.form.getlist("discovered_field_keys")
                )
                if not visible_fields:
                    visible_fields = {
                        definition["field_key"] for definition in definitions
                    }
                updated_definitions = []
                for definition in definitions:
                    item = dict(definition)
                    field_key = item["field_key"]
                    if field_key not in visible_fields:
                        updated_definitions.append(item)
                        continue
                    item["enabled"] = field_key in enabled_fields
                    if "display_fields" in request.form:
                        item["display_enabled"] = field_key in display_fields
                    if "baseline_compare_fields" in request.form:
                        item["baseline_compare_enabled"] = (
                            field_key in baseline_compare_fields
                        )
                    if "run_compare_fields" in request.form:
                        item["run_compare_enabled"] = (
                            field_key in run_compare_fields
                        )
                    roles = []
                    if field_key in completeness_fields:
                        roles.append("completeness")
                    if field_key in accuracy_fields:
                        roles.append("accuracy")
                    if field_key in identity_fields:
                        roles.append("identity")
                    item["scoring_role"] = roles or ["display"]
                    item["identity_enabled"] = field_key in identity_fields
                    item["completeness_enabled"] = (
                        field_key in completeness_fields
                    )
                    item["accuracy_enabled"] = field_key in accuracy_fields
                    compare_mode = request.form.get(
                        f"compare_mode__{field_key}",
                        "",
                    ).strip()
                    normalizer = request.form.get(
                        f"normalizer__{field_key}",
                        "",
                    ).strip()
                    if compare_mode:
                        item["compare_mode"] = compare_mode
                    if normalizer:
                        item["normalizer"] = normalizer
                    baseline_field_key = request.form.get(
                        f"baseline_field_key__{field_key}",
                        "",
                    ).strip()
                    if baseline_field_key:
                        item["baseline_field_key"] = baseline_field_key
                    similarity_threshold = request.form.get(
                        f"similarity_threshold__{field_key}",
                        "",
                    ).strip()
                    if similarity_threshold:
                        try:
                            item["similarity_threshold"] = float(
                                similarity_threshold
                            )
                        except ValueError as exc:
                            raise FieldSchemaValidationError(
                                f"{field_key} 的相似度阈值必须是数值"
                            ) from exc
                    updated_definitions.append(item)
                raw_discovered = request.form.get(
                    "discovered_definitions_json", "[]"
                )
                try:
                    discovered = json.loads(raw_discovered)
                except json.JSONDecodeError as exc:
                    raise FieldSchemaValidationError(
                        "待配置字段数据已失效，请刷新页面后重试"
                    ) from exc
                known_keys = {
                    item["field_key"] for item in updated_definitions
                }
                for suggestion in discovered:
                    if not isinstance(suggestion, dict):
                        continue
                    definition = suggestion.get("definition")
                    field_key = suggestion.get("field_key")
                    if (
                        field_key not in selected_discovered_fields
                        or not isinstance(definition, dict)
                    ):
                        continue
                    if definition.get("field_key") in known_keys:
                        raise FieldSchemaValidationError(
                            f"待配置字段已存在: {definition.get('field_key')}"
                        )
                    updated_definitions.append(definition)
                    known_keys.add(definition["field_key"])
                new_version = service.publish_field_schema(
                    name=request.form.get("name", "").strip(),
                    definitions=updated_definitions,
                    created_by=request.form.get("created_by", "").strip(),
                )
            except FieldSchemaValidationError as exc:
                return (
                    render_template(
                        "error.html",
                        title="无法发布字段配置",
                        message=str(exc),
                        status_code=400,
                    ),
                    400,
                )
            flash(
                f"已从 {schema_version} 复制发布新版本 {new_version}，"
                "已有 Process 未被修改",
                "success",
            )
            return redirect(
                url_for(
                    "field_comparison_matrix",
                    schema_version=new_version,
                    baseline_version=baseline_version,
                )
            )
        if not baseline_version:
            return render_template(
                "field_comparison_matrix.html",
                schema=schema,
                matrix=None,
                baseline_sets=[],
                filters={},
                definitions={},
            )
        try:
            matrix = service.build_field_comparison_matrix(
                schema_version,
                baseline_version,
                process_id=request.args.get("process_id", "").strip() or None,
                person_id=request.args.get("person_id", "").strip() or None,
            )
        except FieldSchemaValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="无法生成字段矩阵",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        module_filter = request.args.get("module", "").strip()
        status_filter = request.args.get("status", "").strip()
        keyword = request.args.get("q", "").strip().casefold()
        if module_filter:
            matrix["fields"] = [
                item for item in matrix["fields"]
                if item["module"] == module_filter
            ]
        if status_filter:
            matrix["fields"] = [
                item for item in matrix["fields"]
                if item["status"] == status_filter
            ]
        if keyword:
            matrix["fields"] = [
                item for item in matrix["fields"]
                if keyword in (
                    item["field_key"] + " " + item["display_name"]
                ).casefold()
            ]
        baseline_sets = store.fetch_all(
            """
            SELECT baseline_version, name FROM baseline_sets
            ORDER BY created_at DESC
            """
        )
        definitions = {
            item["field_key"]: item
            for item in validate_field_definitions(
                parse_json(schema["definitions_json"], [])
            )
        }
        discovery = service.discover_field_candidates(
            schema_version=schema_version,
            process_id=request.args.get("process_id", "").strip() or None,
            baseline_version=baseline_version,
        )
        return render_template(
            "field_comparison_matrix.html",
            schema=schema,
            matrix=matrix,
            baseline_sets=baseline_sets,
            definitions=definitions,
            discovery=discovery,
            discovery_json=json.dumps(
                discovery["suggestions"], ensure_ascii=False
            ),
            filters={
                "baseline_version": baseline_version,
                "process_id": request.args.get("process_id", "").strip(),
                "person_id": request.args.get("person_id", "").strip(),
                "module": module_filter,
                "status": status_filter,
                "q": request.args.get("q", "").strip(),
            },
        )

    @app.post("/runs/<run_id>/process")
    def process_run(run_id: str) -> Response | tuple[str, int]:
        """同步启动字段处理；历史重处理只读取已入库数据。"""

        try:
            processing_mode = request.form.get(
                "processing_mode",
                "PROCESS_EXISTING",
            ).strip()
            arguments = {
                "run_id": run_id,
                "schema_version": request.form.get(
                    "schema_version",
                    "",
                ).strip(),
                "baseline_version": request.form.get(
                    "baseline_version",
                    "",
                ).strip() or None,
            }
            if processing_mode == "REPROCESS_EXISTING":
                if request.form.get("confirm_existing_data") != "true":
                    raise FieldSchemaValidationError(
                        "请确认本次仅重处理已入库数据，不会重新请求检索接口"
                    )
                if arguments["baseline_version"]:
                    alignment_issues = (
                        service.validate_process_field_alignment(
                            arguments["schema_version"],
                            arguments["baseline_version"],
                        )
                    )
                    blocking = [
                        issue for issue in alignment_issues
                        if issue["severity"] == "ERROR"
                    ]
                    if (
                        blocking
                        and request.form.get(
                            "acknowledge_alignment_errors"
                        ) != "true"
                    ):
                        field_keys = ", ".join(
                            issue["field_key"] for issue in blocking[:10]
                        )
                        raise FieldSchemaValidationError(
                            "字段对齐预检发现阻断问题，请先查看矩阵或明确"
                            f"确认风险。字段: {field_keys}"
                        )
                result = service.reprocess_existing_run(**arguments)
            else:
                result = service.process_run(**arguments)
        except FieldSchemaValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="无法启动字段处理",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash(
            f"字段处理完成：候选人 {result.candidate_count}，"
            f"字段错误 {result.error_count}",
            "success",
        )
        for warning in result.warnings:
            flash(warning, "warning")
        return redirect(
            url_for("process_detail", process_id=result.process_id)
        )

    @app.get("/processes/<process_id>")
    def process_detail(process_id: str) -> str:
        """分页展示一次不可变处理结果及字段级错误。"""

        process = store.fetch_one(
            """
            SELECT pr.*, r.run_label, r.system_version, r.evaluation_id,
                   e.name AS evaluation_name,
                   fs.name AS schema_name, fs.definitions_json
            FROM process_runs AS pr
            JOIN runs AS r ON r.run_id = pr.run_id
            JOIN evaluations AS e ON e.evaluation_id = r.evaluation_id
            JOIN field_schemas AS fs
              ON fs.schema_version = pr.schema_version
            WHERE pr.process_id = ?
            """,
            (process_id,),
        )
        if process is None:
            abort(404)
        definitions = parse_json(process["definitions_json"], [])
        definitions_by_key = {
            item.get("field_key"): item
            for item in definitions
            if isinstance(item, dict) and item.get("field_key")
        }
        try:
            metrics = service.calculate_process_metrics(process_id)
        except ReviewValidationError:
            metrics = None
        comparison = None
        comparison_error = ""
        compare_process_id = request.args.get(
            "compare_process_id",
            "",
        ).strip()
        if compare_process_id:
            try:
                comparison = service.compare_processes(
                    compare_process_id,
                    process_id,
                )
            except ReviewValidationError as exc:
                comparison_error = str(exc)
        compatible_processes = store.fetch_all(
            """
            SELECT other.process_id, other.run_id, other.schema_version,
                   other.baseline_version, other.rule_version,
                   other.created_at, r.run_label, r.system_version,
                   r.evaluation_id, r.evaluation_phase,
                   e.name AS evaluation_name
            FROM process_runs AS other
            JOIN runs AS r ON r.run_id = other.run_id
            JOIN evaluations AS e ON e.evaluation_id = r.evaluation_id
            WHERE other.process_id <> ?
              AND other.status = 'COMPLETED'
            ORDER BY e.name, r.evaluation_id, other.created_at DESC
            """,
            (process_id,),
        )
        reports = store.fetch_all(
            """
            SELECT * FROM reports
            WHERE candidate_process_id = ? OR baseline_process_id = ?
            ORDER BY created_at DESC
            """,
            (process_id, process_id),
        )
        page = page_number()
        per_page = 50
        keyword = request.args.get("q", "").strip()
        where = ["pc.process_id = ?"]
        parameters: list[Any] = [process_id]
        if keyword:
            where.append(
                "(c.candidate_id LIKE ? OR c.query_id LIKE ?)"
            )
            wildcard = f"%{keyword}%"
            parameters.extend([wildcard, wildcard])
        where_sql = " AND ".join(where)
        total = store.fetch_one(
            f"""
            SELECT COUNT(*) AS count
            FROM processed_candidates AS pc
            JOIN candidates AS c ON c.candidate_pk = pc.candidate_pk
            WHERE {where_sql}
            """,
            parameters,
        )["count"]
        rows = store.fetch_all(
            f"""
            SELECT pc.*, c.run_id, c.query_id, c.candidate_id,
                   c.candidate_rank, c.detail_status,
                   rv.judgement, rv.reviewed_at
            FROM processed_candidates AS pc
            JOIN candidates AS c ON c.candidate_pk = pc.candidate_pk
            LEFT JOIN reviews AS rv
              ON rv.process_id = pc.process_id
             AND rv.candidate_pk = pc.candidate_pk
            WHERE {where_sql}
            ORDER BY c.query_id, c.candidate_rank
            LIMIT ? OFFSET ?
            """,
            [*parameters, per_page, (page - 1) * per_page],
        )
        candidates = []
        for row in rows:
            item = dict(row)
            item["fields"] = parse_json(row["fields_json"], {})
            item["empty_fields"] = parse_json(
                row["empty_fields_json"],
                {},
            )
            item["errors"] = parse_json(
                row["processing_errors_json"],
                [],
            )
            candidates.append(item)
        query_rows = store.fetch_all(
            """
            SELECT * FROM processed_queries
            WHERE process_id = ?
            ORDER BY query_id
            """,
            (process_id,),
        )
        processed_queries = []
        query_empty_count = 0
        query_error_count = 0
        for row in query_rows:
            item = dict(row)
            item["fields"] = parse_json(row["fields_json"], {})
            item["empty_fields"] = parse_json(
                row["empty_fields_json"],
                {},
            )
            item["errors"] = parse_json(
                row["processing_errors_json"],
                [],
            )
            query_empty_count += sum(
                bool(value) for value in item["empty_fields"].values()
            )
            query_error_count += len(item["errors"])
            processed_queries.append(item)
        candidate_empty_count = 0
        candidate_error_count = 0
        detail_failure_count = 0
        for row in store.fetch_all(
            """
            SELECT empty_fields_json, processing_errors_json
            FROM processed_candidates
            WHERE process_id = ?
            """,
            (process_id,),
        ):
            empty_fields = parse_json(row["empty_fields_json"], {})
            errors = parse_json(row["processing_errors_json"], [])
            candidate_empty_count += sum(
                bool(value) for value in empty_fields.values()
            )
            detail_failures = sum(
                error.get("code") == "DETAIL_FAILED"
                for error in errors
                if isinstance(error, dict)
            )
            detail_failure_count += detail_failures
            candidate_error_count += len(errors) - detail_failures
        classification_progress = (
            service.get_process_classification_progress(process_id)
        )
        field_matrix = None
        if process["baseline_version"]:
            try:
                field_matrix = service.build_field_comparison_matrix(
                    process["schema_version"],
                    process["baseline_version"],
                    process_id=process_id,
                )
            except FieldSchemaValidationError:
                field_matrix = None
        return render_template(
            "process_detail.html",
            process=process,
            candidates=candidates,
            definitions=definitions_by_key,
            page=page,
            per_page=per_page,
            total=total,
            keyword=keyword,
            metrics=metrics,
            comparison=comparison,
            comparison_error=comparison_error,
            compare_process_id=compare_process_id,
            compatible_processes=compatible_processes,
            reports=reports,
            processed_queries=processed_queries,
            query_empty_count=query_empty_count,
            candidate_empty_count=candidate_empty_count,
            query_error_count=query_error_count,
            candidate_error_count=candidate_error_count,
            detail_failure_count=detail_failure_count,
            classification_progress=classification_progress,
            field_matrix=field_matrix,
        )

    @app.route(
        "/processes/<process_id>/queries/<query_id>/classification",
        methods=["GET", "POST"],
    )
    def query_classification(
        process_id: str,
        query_id: str,
    ) -> str | Response | tuple[str, int]:
        """展示并保存一个 Query 的候选人身份归类。"""

        try:
            context = service.get_query_classification_context(
                process_id,
                query_id,
            )
            if request.method == "POST":
                classifications: list[dict[str, str]] = []
                expected_versions: dict[str, str] = {}
                bulk_remaining = (
                    request.form.get("bulk_remaining_not_hit") == "true"
                )
                for candidate in context["candidates"]:
                    candidate_pk = candidate["candidate_pk"]
                    judgement = request.form.get(
                        f"judgement__{candidate_pk}",
                        "PENDING_REVIEW",
                    ).strip()
                    if (
                        bulk_remaining
                        and judgement == "PENDING_REVIEW"
                        and candidate["detail_status"] == "SUCCESS"
                    ):
                        judgement = "NOT_HIT"
                    if judgement != "PENDING_REVIEW":
                        classifications.append({
                            "candidate_pk": candidate_pk,
                            "judgement": judgement,
                            "reason": request.form.get(
                                f"reason__{candidate_pk}",
                                "MANUAL",
                            ).strip(),
                            "evidence": request.form.get(
                                f"evidence__{candidate_pk}",
                                "",
                            ),
                        })
                    expected_versions[candidate_pk] = request.form.get(
                        f"expected_reviewed_at__{candidate_pk}",
                        "",
                    )
                service.save_query_classification(
                    process_id,
                    query_id,
                    classifications,
                    primary_hit_candidate_pk=request.form.get(
                        "primary_hit_candidate_pk",
                        "",
                    ).strip() or None,
                    confirm_no_hit=(
                        request.form.get("confirm_no_hit") == "true"
                    ),
                    reviewer=request.form.get("reviewer", ""),
                    review_note=request.form.get("review_note", ""),
                    expected_versions=expected_versions,
                )
                flash(
                    "候选人身份归类已保存，关联 READY 报告已标记过期",
                    "success",
                )
                return redirect(
                    url_for(
                        "query_classification",
                        process_id=process_id,
                        query_id=query_id,
                    )
                )
        except ReviewValidationError as exc:
            if request.method == "POST":
                return (
                    render_template(
                        "error.html",
                        title="无法保存身份归类",
                        message=str(exc),
                        status_code=(
                            409 if "其他页面" in str(exc) else 400
                        ),
                    ),
                    409 if "其他页面" in str(exc) else 400,
                )
            abort(404)
        return render_template(
            "query_classification.html",
            context=context,
        )

    @app.post(
        "/processes/<process_id>/candidates/<candidate_pk>/review"
    )
    def candidate_review(
        process_id: str,
        candidate_pk: str,
    ) -> Response | tuple[str, int]:
        """保存候选人最终判定及字段得分，拒绝旧页面覆盖新记录。"""

        try:
            raw_scores = request.form.get("field_scores_json", "").strip()
            if raw_scores:
                field_scores = json.loads(raw_scores)
            else:
                context = service.get_review_context(
                    process_id,
                    candidate_pk,
                )
                field_scores = context["field_scores"]
                for field_key, score in field_scores.items():
                    score["completeness_score"] = request.form.get(
                        f"completeness__{field_key}",
                        "",
                    )
                    score["accuracy_score"] = request.form.get(
                        f"accuracy__{field_key}",
                        "",
                    )
                    score["review_note"] = request.form.get(
                        f"field_note__{field_key}",
                        "",
                    )
            service.save_review(
                process_id=process_id,
                candidate_pk=candidate_pk,
                judgement=request.form.get("judgement", "").strip(),
                reason=request.form.get("reason", "").strip(),
                evidence=request.form.get("evidence", ""),
                reviewer=request.form.get("reviewer", ""),
                review_note=request.form.get("review_note", ""),
                field_scores=field_scores,
                expected_reviewed_at=request.form.get(
                    "expected_reviewed_at",
                    "",
                ),
            )
        except json.JSONDecodeError as exc:
            error = ReviewValidationError(
                f"字段得分 JSON 格式错误: {exc.msg}"
            )
            return (
                render_template(
                    "error.html",
                    title="无法保存复核",
                    message=str(error),
                    status_code=400,
                ),
                400,
            )
        except ReviewValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="无法保存复核",
                    message=str(exc),
                    status_code=409 if "其他页面" in str(exc) else 400,
                ),
                409 if "其他页面" in str(exc) else 400,
            )
        flash("候选人复核已保存，关联 READY 报告已标记过期", "success")
        return redirect(
            url_for(
                "candidate_detail",
                candidate_pk=candidate_pk,
                process_id=process_id,
            )
        )

    @app.post("/reports")
    def report_create() -> Response | tuple[str, int]:
        """创建报告模型快照、静态 HTML，并尽力生成 processed Excel。"""

        report = None
        try:
            report = service.create_report(
                candidate_process_id=request.form.get(
                    "candidate_process_id",
                    "",
                ).strip(),
                baseline_process_id=request.form.get(
                    "baseline_process_id",
                    "",
                ).strip()
                or None,
                data_marker=request.form.get(
                    "data_marker",
                    "REAL_TEST_DATA",
                ).strip(),
            )
            static_html = render_template(
                "report_static.html",
                report=report.model,
                static_export=True,
            )
            service.save_report_html(report.report_id, static_html)
        except (ReviewValidationError, ValueError) as exc:
            if report is not None:
                service.mark_report_failed(report.report_id)
            return (
                render_template(
                    "error.html",
                    title="无法生成报告",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        except Exception as exc:
            if report is not None:
                service.mark_report_failed(report.report_id)
            return (
                render_template(
                    "error.html",
                    title="报告文件生成失败",
                    message=f"{type(exc).__name__}: {str(exc)[:500]}",
                    status_code=500,
                ),
                500,
            )
        excel_message = ""
        if app.config.get("SEARCH_REPORT_EXCEL_ENABLED", True):
            try:
                service.export_report_excel(report.report_id)
            except (RuntimeError, subprocess.SubprocessError) as exc:
                excel_message = f"；Excel 暂不可用：{str(exc)[:300]}"
        flash(
            f"报告 {report.report_id} 已生成{excel_message}",
            "success" if not excel_message else "warning",
        )
        return redirect(
            url_for("report_detail", report_id=report.report_id)
        )

    @app.get("/reports/<report_id>")
    def report_detail(report_id: str) -> str:
        """只读取 metrics_json 快照展示报告，不重新计算历史数字。"""

        row = store.fetch_one(
            """
            SELECT rp.*, candidate.run_id AS candidate_run_id,
                   baseline.run_id AS baseline_run_id
            FROM reports AS rp
            JOIN process_runs AS candidate
              ON candidate.process_id = rp.candidate_process_id
            LEFT JOIN process_runs AS baseline
              ON baseline.process_id = rp.baseline_process_id
            WHERE rp.report_id = ?
            """,
            (report_id,),
        )
        if row is None:
            abort(404)
        model = parse_json(row["metrics_json"], {})
        html_available = report_artifact_available(
            report_id,
            "html",
            row["status"],
        )
        excel_available = report_artifact_available(
            report_id,
            "excel",
            row["status"],
        )
        return render_template(
            "report_detail.html",
            report=model,
            report_row=row,
            html_available=html_available,
            excel_available=excel_available,
            static_export=False,
        )

    @app.post("/reports/<report_id>/name")
    def report_rename(report_id: str) -> Response | tuple[str, int]:
        """保存报告显示名称，并同步重新生成已有静态 HTML。"""

        try:
            model = service.rename_report(
                report_id,
                request.form.get("report_name", ""),
            )
        except ReviewValidationError as exc:
            status_code = 404 if "报告不存在" in str(exc) else 400
            return (
                render_template(
                    "error.html",
                    title="无法修改报告名称",
                    message=str(exc),
                    status_code=status_code,
                ),
                status_code,
            )

        static_warning = ""
        try:
            static_html = render_template(
                "report_static.html",
                report=model,
                static_export=True,
            )
            service.save_report_html(report_id, static_html)
        except (OSError, ReviewValidationError) as exc:
            # Web 报告名称已经保存；静态文件失败不能撤销用户刚完成的编辑。
            static_warning = f"；静态 HTML 同步失败：{str(exc)[:200]}"
        flash(
            f"报告名称已保存{static_warning}",
            "success" if not static_warning else "warning",
        )
        return redirect(url_for("report_detail", report_id=report_id))

    @app.get("/api/runs/<run_id>/status")
    def run_status(run_id: str) -> Response:
        """返回页面定时刷新需要的 Run 和当前 Query 进度。"""

        run = store.fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if run is None:
            abort(404)
        current = store.fetch_one(
            """
            SELECT query_id, current_stage
            FROM run_queries
            WHERE run_id = ? AND status = 'RUNNING'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,),
        )
        return jsonify(
            {
                "run_id": run_id,
                "status": run["status"],
                "total_queries": run["total_queries"],
                "completed_queries": (
                    run["success_queries"] + run["failed_queries"]
                ),
                "success_queries": run["success_queries"],
                "failed_queries": run["failed_queries"],
                "current_query_id": current["query_id"] if current else "",
                "current_stage": current["current_stage"] if current else "",
                "message": run["message"],
            }
        )

    @app.get("/api/field-schemas/<schema_version>")
    def field_schema_api(schema_version: str) -> Response:
        """返回字段配置快照，供页面预览和平台后续集成。"""

        schema = store.fetch_one(
            "SELECT * FROM field_schemas WHERE schema_version = ?",
            (schema_version,),
        )
        if schema is None:
            abort(404)
        definitions = validate_field_definitions(
            parse_json(schema["definitions_json"], [])
        )
        return jsonify(
            {
                "schema_version": schema["schema_version"],
                "name": schema["name"],
                "created_by": schema["created_by"],
                "created_at": schema["created_at"],
                "is_active": bool(schema["is_active"]),
                "definitions": definitions,
            }
        )

    @app.get("/api/field-schemas/<schema_version>/comparison-matrix")
    def field_comparison_matrix_api(schema_version: str) -> Response:
        """返回字段矩阵 JSON，供 Process 预检和后续平台集成。"""

        baseline_version = request.args.get(
            "baseline_version",
            "",
        ).strip()
        if not baseline_version:
            return jsonify({"error": "baseline_version 不能为空"}), 400
        try:
            matrix = service.build_field_comparison_matrix(
                schema_version,
                baseline_version,
                process_id=request.args.get("process_id", "").strip() or None,
                person_id=request.args.get("person_id", "").strip() or None,
            )
        except FieldSchemaValidationError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(matrix)

    @app.get("/api/processes/<process_id>/status")
    def process_status(process_id: str) -> Response:
        """返回同步处理的终态摘要，保留未来后台化兼容入口。"""

        process = store.fetch_one(
            """
            SELECT process_id, run_id, schema_version, status,
                   error_count, created_at, finished_at
            FROM process_runs WHERE process_id = ?
            """,
            (process_id,),
        )
        if process is None:
            abort(404)
        return jsonify(dict(process))

    @app.get("/api/processes/<process_id>/metrics")
    def process_metrics(process_id: str) -> Response:
        """返回与 Process 页面相同的可追溯指标模型。"""

        try:
            return jsonify(service.calculate_process_metrics(process_id))
        except ReviewValidationError:
            abort(404)

    @app.get("/api/raw/<raw_id>")
    def raw_record(raw_id: str) -> Response:
        """按 Raw ID 返回一条脱敏业务 JSON，不在列表页嵌入大对象。"""

        raw = store.fetch_one(
            """
            SELECT raw_id, run_id, query_id, candidate_pk, stage,
                   sequence_no, payload_json, collected_at
            FROM raw_records WHERE raw_id = ?
            """,
            (raw_id,),
        )
        if raw is None:
            abort(404)
        return jsonify(
            {
                "raw_id": raw["raw_id"],
                "run_id": raw["run_id"],
                "query_id": raw["query_id"],
                "candidate_pk": raw["candidate_pk"],
                "stage": raw["stage"],
                "sequence_no": raw["sequence_no"],
                "collected_at": raw["collected_at"],
                "payload": parse_json(raw["payload_json"], {}),
            }
        )

    @app.get("/downloads/<file_type>/<run_id>")
    def download_run_file(file_type: str, run_id: str) -> Response:
        """通过数据库 ID 下载 Run JSONL 或报告 HTML/Excel。"""

        if file_type in {"report-html", "report-excel"}:
            try:
                target = service.resolve_report_artifact(
                    run_id,
                    "html" if file_type == "report-html" else "excel",
                )
            except ReviewValidationError:
                abort(404)
            return send_file(
                target,
                as_attachment=True,
                download_name=target.name,
            )

        columns = {"results": "results_file", "failures": "failures_file"}
        column = columns.get(file_type)
        if column is None:
            abort(404)
        row = store.fetch_one(
            f"SELECT {column} AS relative_path FROM runs WHERE run_id = ?",
            (run_id,),
        )
        if row is None or not row["relative_path"]:
            abort(404)
        target = (data_dir / row["relative_path"]).resolve()
        try:
            target.relative_to(data_dir.resolve())
        except ValueError:
            abort(404)
        if not target.is_file():
            abort(404)
        return send_file(target, as_attachment=True, download_name=target.name)

    @app.errorhandler(413)
    def upload_too_large(_: HTTPException) -> tuple[str, int]:
        """上传超过限制时返回可读页面，不暴露 Flask 堆栈。"""

        return (
            render_template(
                "error.html",
                title="上传文件过大",
                message="请拆分文件，或调整 SEARCH_WEB_MAX_UPLOAD_BYTES。",
                status_code=413,
            ),
            413,
        )

    @app.errorhandler(404)
    def not_found(_: HTTPException) -> tuple[str, int]:
        """统一返回不包含内部路径的404页面。"""

        return (
            render_template(
                "error.html",
                title="没有找到该记录",
                message="请返回列表确认对象是否存在。",
                status_code=404,
            ),
            404,
        )

    @app.errorhandler(500)
    def internal_error(_: HTTPException) -> tuple[str, int]:
        """隐藏内部堆栈和配置，只提供下一步建议。"""

        return (
            render_template(
                "error.html",
                title="页面处理失败",
                message="请查看终端日志并刷新页面；已落库数据不会被覆盖。",
                status_code=500,
            ),
            500,
        )

    return app


def build_parser() -> argparse.ArgumentParser:
    """构造本地 Web 启动参数。"""

    parser = argparse.ArgumentParser(description="启动 searchTool v1.3 本地 Web")
    parser.add_argument("--env-file", default=".env", help="环境变量文件")
    parser.add_argument("--host", default=None, help="监听地址，默认读取 .env")
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    return parser


def main(argv: list[str] | None = None) -> int:
    """启动无自动重载的本地服务，退出时等待当前 Query 安全收尾。"""

    args = build_parser().parse_args(argv)
    overrides: dict[str, Any] = {"SEARCH_ENV_FILE": args.env_file}
    if args.host:
        overrides["SEARCH_WEB_HOST"] = args.host
    if args.port:
        overrides["SEARCH_WEB_PORT"] = args.port
    app = create_app(overrides)
    coordinator: RunCoordinator = app.extensions["default_run_coordinator"]
    try:
        app.run(
            host=app.config["SEARCH_WEB_HOST"],
            port=app.config["SEARCH_WEB_PORT"],
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    finally:
        coordinator.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
