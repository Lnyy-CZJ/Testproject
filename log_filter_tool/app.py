import hmac
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib import request as urlrequest

from gateway_log_parser import clean_log_line

try:
    from flask import Blueprint, Flask, jsonify, render_template, request
    from werkzeug.exceptions import RequestEntityTooLarge
except ImportError:  # Allows core log parsing tests to run before Flask is installed.
    Blueprint = None
    Flask = None
    jsonify = None
    render_template = None
    request = None
    RequestEntityTooLarge = None


ALL_METHOD = "__ALL__"
METHOD_PATTERNS = (
    re.compile(r"method=([A-Za-z0-9_]+)"),
    re.compile(r'"method_name"\s*:\s*"([A-Za-z0-9_]+)"'),
)
REQUEST_ID_PATTERN = re.compile(
    r'(?<![A-Za-z0-9_])"?request_id"?\s*[:=]\s*"?([^"\s,}]+)',
    re.IGNORECASE,
)
TRACE_ID_PATTERN = re.compile(
    r'(?<![A-Za-z0-9_])"?trace_id"?\s*[:=]\s*"?([^"\s,}]+)',
    re.IGNORECASE,
)
STATUS_CODE_PATTERNS = (
    re.compile(r"\[HTTP\]\s+<--\s+(\d{3})"),
    re.compile(r"HTTP/\d(?:\.\d)?\s+(\d{3})", re.IGNORECASE),
    re.compile(r'"?status_code"?\s*[:=]\s*"?(\d{3})', re.IGNORECASE),
)
EXPORT_FILE_TYPES = {
    "log_content": ("log_content", ".log"),
    "filtered_result": ("filtered_result", ".log"),
    "analysis_report": ("people_search_analysis", ".md"),
    "dating_analysis_report": ("dating_structured_analysis", ".md"),
    "dating_analysis_json": ("dating_structured_analysis", ".json"),
}
DATING_RULESET_VERSION = "2026-08-29"
DEFAULT_EXPORT_DIR = "/Users/admin/Documents/log"
# 导出文件名使用用户所在的上海时区，避免 Docker 默认 UTC 造成时间偏差。
EXPORT_TIMEZONE = timezone(timedelta(hours=8))


def normalize_base_path(value):
    """将部署基础路径转换为 Flask Blueprint 可使用的安全前缀。

    参数说明:
        value (str | None): 环境变量或调用方传入的路径，空值表示根路径。

    返回值:
        str: 不带末尾斜杠的标准路径；根路径模式返回空字符串。

    异常说明:
        ValueError: 路径包含查询参数、父目录或重复斜杠时抛出。
    """
    raw_path = (value or "").strip()
    if not raw_path or raw_path == "/":
        return ""
    if any(marker in raw_path for marker in ("?", "#", "..", "://")):
        raise ValueError(f"LOG_FILTER_BASE_PATH 不是有效路径: {raw_path}")
    normalized = raw_path if raw_path.startswith("/") else f"/{raw_path}"
    normalized = normalized.rstrip("/")
    if "//" in normalized:
        raise ValueError(f"LOG_FILTER_BASE_PATH 不能包含重复斜杠: {raw_path}")
    return normalized


def extract_methods(log_text):
    methods = set()
    for pattern in METHOD_PATTERNS:
        methods.update(pattern.findall(log_text or ""))
    return sorted(methods)


def extract_request_id(text):
    match = REQUEST_ID_PATTERN.search(text or "")
    return match.group(1) if match else None


def extract_trace_id(text):
    match = TRACE_ID_PATTERN.search(text or "")
    return match.group(1) if match else None


def extract_status_code(text):
    for pattern in STATUS_CODE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return int(match.group(1))
    return None


def detect_log_kind(text):
    text = text or ""
    if "[HTTP] <--" in text or "[HTTP] response:" in text:
        return "response"
    if "[HTTP] -->" in text or "[HTTP] request:" in text:
        return "request"
    return "other"


def parse_log_block(block, index):
    methods = extract_methods(block)
    return {
        "index": index,
        "raw_text": block,
        "display_text": format_result_text([block]),
        "method": methods[0] if methods else None,
        "request_id": extract_request_id(block),
        "trace_id": extract_trace_id(block),
        "kind": detect_log_kind(block),
        "status_code": extract_status_code(block),
    }


def parse_log_blocks(log_text):
    return [
        parse_log_block(block, index)
        for index, block in enumerate(split_log_blocks(log_text))
    ]


def _empty_interface_statistics(method):
    return {
        "method": method,
        "request_count": 0,
        "response_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "unresponded_count": 0,
        "success_rate": 0.0,
        "status_codes": {},
    }


def _finalize_statistics(statistics):
    for summary in statistics.values():
        summary["unresponded_count"] = max(
            summary["request_count"] - summary["response_count"], 0
        )
        response_count = summary["response_count"]
        summary["success_rate"] = round(
            summary["success_count"] / response_count * 100, 1
        ) if response_count else 0.0
    return statistics


def build_interface_statistics(parsed_blocks):
    statistics = {}
    for block in parsed_blocks:
        method = block.get("method")
        if not method:
            continue

        summary = statistics.setdefault(method, _empty_interface_statistics(method))
        is_request_header = "[HTTP] -->" in block.get("raw_text", "")
        is_response_header = (
            "[HTTP] <--" in block.get("raw_text", "")
            and block.get("status_code") is not None
        )
        if is_request_header:
            summary["request_count"] += 1
        elif is_response_header:
            summary["response_count"] += 1
            status_code = block.get("status_code")
            if status_code is None:
                continue
            summary["status_codes"][status_code] = (
                summary["status_codes"].get(status_code, 0) + 1
            )
            if 200 <= status_code <= 299:
                summary["success_count"] += 1
            elif status_code >= 400:
                summary["failure_count"] += 1

    return _finalize_statistics(dict(sorted(statistics.items())))


def summarize_interface_statistics(statistics):
    summary = _empty_interface_statistics("全部")
    for method_summary in statistics.values():
        for field in (
            "request_count",
            "response_count",
            "success_count",
            "failure_count",
            "unresponded_count",
        ):
            summary[field] += method_summary[field]
        for status_code, count in method_summary["status_codes"].items():
            summary["status_codes"][status_code] = (
                summary["status_codes"].get(status_code, 0) + count
            )

    return _finalize_statistics({"全部": summary})["全部"]


def split_log_blocks(log_text):
    if not log_text:
        return []

    lines = log_text.splitlines()
    if not any("┌" in line or "└" in line for line in lines):
        return [line for line in lines if line.strip()]

    blocks = []
    current = []
    loose_lines = []
    in_block = False

    for line in lines:
        if "┌" in line:
            if loose_lines:
                blocks.extend(line for line in loose_lines if line.strip())
                loose_lines = []
            current = [line]
            in_block = True
            continue

        if in_block:
            current.append(line)
            if "└" in line:
                blocks.append("\n".join(current))
                current = []
                in_block = False
            continue

        if line.strip():
            loose_lines.append(line)

    if current:
        blocks.append("\n".join(current))
    if loose_lines:
        blocks.extend(line for line in loose_lines if line.strip())

    return blocks


def block_matches_method(block, method):
    escaped_method = re.escape(method)
    return (
        re.search(rf"method={escaped_method}(?![A-Za-z0-9_])", block) is not None
        or re.search(rf'"method_name"\s*:\s*"{escaped_method}"', block) is not None
    )


def _should_include_next_block(block, next_block):
    if "[HTTP] -->" in block and "[HTTP] request:" in next_block:
        return True
    if "[HTTP] <--" in block and "[HTTP] response:" in next_block:
        return True
    return False


def _normalize_methods(methods):
    if isinstance(methods, str):
        return [methods] if methods else [ALL_METHOD]
    normalized = list(methods or [])
    return normalized or [ALL_METHOD]


def filter_log_blocks(blocks, methods):
    methods = _normalize_methods(methods)
    if ALL_METHOD in methods:
        return blocks

    selected_indexes = set()
    for index, block in enumerate(blocks):
        for method in methods:
            if block_matches_method(block, method):
                selected_indexes.add(index)
                if index + 1 < len(blocks) and _should_include_next_block(block, blocks[index + 1]):
                    selected_indexes.add(index + 1)
                break

    return [block for index, block in enumerate(blocks) if index in selected_indexes]


def filter_log_text(log_text, methods):
    methods = _normalize_methods(methods)
    blocks = split_log_blocks(log_text)
    if ALL_METHOD in methods:
        return format_result_text(blocks), len(blocks)

    filtered_blocks = filter_log_blocks(blocks, methods)
    return format_result_text(filtered_blocks), len(filtered_blocks)


def format_result_text(blocks):
    cleaned_blocks = []
    for block in blocks:
        cleaned_lines = []
        for line in block.splitlines():
            cleaned_line = clean_log_line(line)
            if cleaned_line:
                cleaned_lines.append(cleaned_line)
        cleaned_blocks.append("\n".join(cleaned_lines))
    return "\n".join(cleaned_blocks)


def save_exported_log(content, export_type, export_dir):
    """将页面文本安全保存为不覆盖已有文件的已批准导出类型。

    功能说明:
        根据导出来源生成带时间戳的文件名，并使用独占创建模式避免覆盖
        已存在的日志文件。

    参数说明:
        content (str): 需要导出的当前文本框内容，不能为空或仅包含空白。
        export_type (str): ``EXPORT_FILE_TYPES`` 中的固定导出类型。
        export_dir (str | Path): 服务端实际写入的目录。

    返回值:
        Path: 已成功创建的日志文件完整路径。

    异常说明:
        ValueError: 导出类型不受支持或导出内容为空时抛出。
        OSError: 目录创建或文件写入失败时由调用方统一转换为错误响应。
    """
    if export_type not in EXPORT_FILE_TYPES:
        raise ValueError("不支持的导出类型")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("当前内容为空，无法导出")

    target_dir = Path(export_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(EXPORT_TIMEZONE).strftime("%Y%m%d_%H%M%S")
    prefix, extension = EXPORT_FILE_TYPES[export_type]
    filename_base = f"{prefix}_{timestamp}"

    for sequence in range(10000):
        suffix = "" if sequence == 0 else f"_{sequence}"
        target_path = target_dir / f"{filename_base}{suffix}{extension}"
        try:
            with target_path.open("x", encoding="utf-8") as export_file:
                export_file.write(content)
            return target_path
        except FileExistsError:
            continue

    raise OSError("同名导出文件过多，请稍后重试")


def create_app(base_path=None):
    """创建日志工具 Flask 应用，并按配置注册可选的 URL 基础路径。

    参数说明:
        base_path (str | None): 显式部署前缀；未提供时读取
            LOG_FILTER_BASE_PATH，默认保持原根路径行为。

    返回值:
        Flask: 已注册业务、导出和健康检查路由的应用实例。

    异常说明:
        RuntimeError: Flask 未安装时抛出。
        ValueError: 基础路径不符合安全格式时抛出。
    """
    if Flask is None:
        raise RuntimeError("Flask is not installed. Run: pip install -r requirements.txt")

    configured_base_path = (
        os.environ.get("LOG_FILTER_BASE_PATH", "")
        if base_path is None
        else base_path
    )
    normalized_base_path = normalize_base_path(configured_base_path)
    app = Flask(__name__)
    app.config["MAX_FORM_MEMORY_SIZE"] = 20 * 1024 * 1024
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    app.config["LOG_EXPORT_DIR"] = os.environ.get(
        "LOG_EXPORT_DIR", DEFAULT_EXPORT_DIR
    )
    app.config["LOG_EXPORT_DISPLAY_DIR"] = os.environ.get(
        "LOG_EXPORT_DISPLAY_DIR", DEFAULT_EXPORT_DIR
    )
    app.config["LOG_FILTER_BASE_PATH"] = normalized_base_path
    app.config["PLATFORM_HOME_URL"] = os.environ.get("PLATFORM_HOME_URL", "").strip()
    app.config["PLATFORM_API_URL"] = os.environ.get("PLATFORM_API_URL", "").rstrip("/")
    app.config["PLATFORM_CLIENT_TOKEN_FILE"] = os.environ.get("PLATFORM_CLIENT_TOKEN_FILE", "")
    app.config["PLATFORM_ENVIRONMENT"] = os.environ.get("PLATFORM_RUNTIME_ENV", "dev").strip() or "dev"
    app.config["PEOPLE_SEARCH_ANALYZER_ENABLED"] = os.environ.get(
        "PEOPLE_SEARCH_ANALYZER_ENABLED", "true"
    ).lower() in ("1", "true", "yes", "on")
    app.config["PEOPLE_SEARCH_ANALYZER_AI_ENABLED"] = os.environ.get(
        "PEOPLE_SEARCH_ANALYZER_AI_ENABLED", "false"
    ).lower() in ("1", "true", "yes", "on")
    app.config["DATING_STRUCTURED_ANALYZER_ENABLED"] = os.environ.get(
        "DATING_STRUCTURED_ANALYZER_ENABLED", "true"
    ).lower() in ("1", "true", "yes", "on")
    # PRD canonical 名称优先；旧部署只配置 MAX_BYTES 时继续兼容。canonical
    # 一旦显式存在即不回落 alias，配置非法则统一使用安全默认值。
    dating_max_bytes_value = os.environ.get(
        "DATING_STRUCTURED_MAX_LOG_BYTES"
    )
    if dating_max_bytes_value is None:
        dating_max_bytes_value = os.environ.get(
            "DATING_STRUCTURED_MAX_BYTES", "10485760"
        )
    try:
        app.config["DATING_STRUCTURED_MAX_BYTES"] = max(
            1,
            int(dating_max_bytes_value),
        )
    except ValueError:
        # 环境变量配置错误时回落到 10 MiB，避免应用因可选分析器无法启动。
        app.config["DATING_STRUCTURED_MAX_BYTES"] = 10 * 1024 * 1024
    # 静态资源由同一 Blueprint 提供，使根路径部署与平台子路径部署共享
    # ``url_prefix``，避免模板硬编码路径后在 ``/log-tool`` 下产生 404。
    tool = Blueprint(
        "tool",
        __name__,
        static_folder="static",
        static_url_path="/static",
    )

    def client_token():
        """读取只读 Client Token，缺失时仅跳过审计上报。"""

        try:
            return Path(app.config["PLATFORM_CLIENT_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
        except (OSError, TypeError):
            return ""

    def verified_resource_access(action, resource_type, root_resource_id=None):
        """向平台核验 opaque 资源上下文，工具端绝不解析身份或角色。

        独立部署没有平台地址时返回 ``None`` 以保持原有单用户行为。启用平台
        后，缺失、失效或被拒绝的资源上下文都按不可见处理，调用方统一返回
        404，避免暴露资源是否存在。
        """
        platform_api_url = app.config["PLATFORM_API_URL"]
        if not platform_api_url:
            return None
        opaque_context = request.headers.get("X-Platform-Resource-Context", "")
        token = client_token()
        if not opaque_context or not token:
            return {"allowed": False}
        body = json.dumps(
            {
                "action": action,
                "resource_type": resource_type,
                "root_resource_id": root_resource_id,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        access_request = urlrequest.Request(
            f"{platform_api_url}/internal/tools/log-filter/resource-access/check",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Platform-Resource-Context": opaque_context,
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(access_request, timeout=3) as response:
                decision = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            # 无法得到平台的可验证决策时必须失败关闭，不能降级为公开导出。
            return {"allowed": False}
        return decision if isinstance(decision, dict) else {"allowed": False}

    def register_root_resource(resource_type, resource_id):
        """在写文件前登记平台不可变 owner/project 快照，字段缺失一律拒绝。"""

        platform_api_url = app.config["PLATFORM_API_URL"]
        if not platform_api_url:
            return True
        opaque_context = request.headers.get("X-Platform-Resource-Context", "")
        token = client_token()
        if not opaque_context or not token:
            return False
        register_request = urlrequest.Request(
            f"{platform_api_url}/internal/resources",
            data=json.dumps({
                "tool_id": "log-filter",
                "resource_type": resource_type,
                "resource_id": resource_id,
            }, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Platform-Resource-Context": opaque_context,
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(register_request, timeout=3) as response:
                registered = json.loads(response.read().decode("utf-8"))
                status = response.status
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        return (
            status == 201
            and isinstance(registered, dict)
            and registered.get("resource_id") == resource_id
            and registered.get("environment_id") == app.config.get("PLATFORM_ENVIRONMENT", "dev")
            and bool(registered.get("owner_user_id"))
        )

    @app.before_request
    def validate_platform_csrf():
        """平台模式下校验所有写操作的双提交 CSRF Token。"""

        if not app.config["PLATFORM_API_URL"] or request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        cookie = request.cookies.get("tp_csrf", "")
        submitted = request.headers.get("X-CSRF-Token", "") or request.form.get("_csrf", "")
        if not cookie or not submitted or not hmac.compare_digest(cookie, submitted):
            return jsonify({"message": "请求安全校验失败"}), 403
        return None

    @app.after_request
    def report_platform_audit(response):
        """最大尽力上报分析和导出事件，平台故障不覆盖业务响应。"""

        token = client_token()
        if request.method in {"GET", "HEAD", "OPTIONS"} or not app.config["PLATFORM_API_URL"] or not token:
            return response
        payload = json.dumps({
            "event_id": f"evt_{uuid.uuid4().hex}",
            "action": "tool.export" if request.endpoint == "tool.export_log" else "tool.analysis.submit",
            "resource_type": "log_filter_operation",
            "outcome": "success" if response.status_code < 400 else ("denied" if response.status_code == 403 else "failed"),
            "error_code": "CSRF_INVALID" if response.status_code == 403 else None,
            "actor_user_id": request.headers.get("X-Platform-User-ID"),
            "actor_username": request.headers.get("X-Platform-Username"),
            "metadata": {},
        }).encode("utf-8")
        audit_request = urlrequest.Request(
            f"{app.config['PLATFORM_API_URL']}/internal/tools/log-filter/audit-events",
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(audit_request, timeout=1):
                pass
        except Exception:
            pass
        return response

    @tool.route("/", methods=["GET", "POST"])
    def index():
        log_text = ""
        methods = []
        selected_methods = [ALL_METHOD]
        result_text = ""
        match_count = 0
        message = ""
        analysis = {}
        selected_analysis = None
        overall_analysis = None

        if request.method == "POST":
            log_text = request.form.get("log_text", "")
            selected_methods = request.form.getlist("method")
            if not selected_methods or ALL_METHOD in selected_methods:
                selected_methods = [ALL_METHOD]
            methods = extract_methods(log_text)

            if not log_text.strip():
                message = "请先粘贴日志内容"
            elif not methods:
                message = "未识别到 method，请检查日志格式"
            else:
                valid_methods = [m for m in selected_methods if m == ALL_METHOD or m in methods]
                if not valid_methods:
                    selected_methods = [ALL_METHOD]

                result_text, match_count = filter_log_text(log_text, selected_methods)
                parsed_blocks = parse_log_blocks(log_text)
                analysis = build_interface_statistics(parsed_blocks)
                overall_analysis = summarize_interface_statistics(analysis)
                if ALL_METHOD in selected_methods:
                    selected_analysis = overall_analysis
                else:
                    combined = _empty_interface_statistics("已选接口")
                    for m in selected_methods:
                        if m not in analysis:
                            continue
                        for field in ("request_count", "response_count", "success_count", "failure_count", "unresponded_count"):
                            combined[field] += analysis[m][field]
                        for sc, c in analysis[m]["status_codes"].items():
                            combined["status_codes"][sc] = combined["status_codes"].get(sc, 0) + c
                    selected_analysis = _finalize_statistics({"已选接口": combined})["已选接口"]
                if ALL_METHOD not in selected_methods and not result_text:
                    message = "没有匹配到相关日志"

        return render_template(
            "index.html",
            all_method=ALL_METHOD,
            log_text=log_text,
            methods=methods,
            selected_methods=selected_methods,
            result_text=result_text,
            match_count=match_count,
            method_count=len(methods),
            message=message,
            analysis=analysis,
            selected_analysis=selected_analysis,
            overall_analysis=overall_analysis,
            platform_home_url=app.config["PLATFORM_HOME_URL"],
            dating_analyzer_enabled=app.config[
                "DATING_STRUCTURED_ANALYZER_ENABLED"
            ],
        )

    @tool.route("/sample", methods=["GET"])
    def sample_log():
        sample_path = Path(__file__).with_name("log_default.log")
        return sample_path.read_text(encoding="utf-8") if sample_path.exists() else ""

    @tool.route("/dating/analyze", methods=["POST"])
    def analyze_dating():
        """编排本地 Dating 分析、规则、脱敏和固定报告。

        请求只接受 ``application/json`` 对象，其中 ``log_text`` 为必填
        字符串，``task_id`` 为可选字符串或 null。解析、规则和报告实现均
        保留在各自模块；本路由只负责校验、错误映射和响应结构组装。
        """

        def error_response(error_code, message, status_code, task_ids=None):
            """构造不含堆栈或原日志的稳定 Dating 错误响应。"""
            payload = {"error_code": error_code, "message": message}
            if task_ids is not None:
                payload["task_ids"] = task_ids
            return jsonify(payload), status_code

        if not app.config["DATING_STRUCTURED_ANALYZER_ENABLED"]:
            return error_response(
                "ANALYZER_DISABLED",
                "Dating 结构化分析功能未启用",
                503,
            )

        # Flask 的全局 body 上限可能在 JSON 解析时先抛异常；Dating 路由在
        # 读取 body 前做可判定的快速拒绝，并把解析期异常映射为同一 JSON。
        request_limit = app.config.get("MAX_CONTENT_LENGTH")
        if (
            isinstance(request_limit, int)
            and request.content_length is not None
            and request.content_length > request_limit
        ):
            return error_response(
                "LOG_TOO_LARGE", "日志内容超过允许的字节上限", 413
            )
        try:
            payload = request.get_json(silent=True)
        except RequestEntityTooLarge:
            return error_response(
                "LOG_TOO_LARGE", "日志内容超过允许的字节上限", 413
            )
        allowed_fields = {"log_text", "task_id"}
        if (
            request.mimetype != "application/json"
            or not isinstance(payload, dict)
            or "log_text" not in payload
            or not set(payload).issubset(allowed_fields)
            or not isinstance(payload.get("log_text"), str)
            or (
                payload.get("task_id") is not None
                and not isinstance(payload.get("task_id"), str)
            )
        ):
            return error_response(
                "INVALID_REQUEST",
                "请求必须是仅包含 log_text 和可选 task_id 的 JSON 对象",
                400,
            )

        log_text = payload["log_text"]
        task_id = payload.get("task_id")
        if not log_text.strip():
            return error_response("EMPTY_LOG", "日志内容为空", 400)
        try:
            log_size = len(log_text.encode("utf-8"))
        except UnicodeEncodeError:
            return error_response(
                "INVALID_REQUEST", "log_text 必须是有效 UTF-8 文本", 400
            )
        if log_size > app.config["DATING_STRUCTURED_MAX_BYTES"]:
            return error_response(
                "LOG_TOO_LARGE", "日志内容超过允许的字节上限", 413
            )

        try:
            # 延迟导入保持 app 核心过滤函数在 Flask/Dating 可选场景下可导入。
            from dating_log_analyzer import analyze_dating_log
            from dating_log_rules import (
                compute_dating_verdict,
                redact_dating_response,
                render_dating_report,
                run_dating_checks,
            )

            analysis = analyze_dating_log(
                log_text, requested_task_id=task_id
            )
            if not analysis["supported"]:
                return error_response(
                    "UNSUPPORTED_LOG",
                    "未识别到 Dating Gateway/PUT 日志",
                    422,
                )
            if analysis["selection_error"]:
                selection_error = analysis["selection_error"]
                selection_messages = {
                    "MULTIPLE_TASKS_FOUND": (
                        "日志包含多个 Dating 任务，请指定 task_id"
                    ),
                    "TASK_NOT_FOUND": "指定的 task_id 不存在",
                }
                if selection_error not in selection_messages:
                    raise ValueError("未知 Dating 任务选择错误")
                return error_response(
                    selection_error,
                    selection_messages[selection_error],
                    422,
                    task_ids=analysis["task_ids"],
                )

            checks = run_dating_checks(analysis)
            verdict = compute_dating_verdict(checks)
            summary = dict(analysis["summary"])
            summary.update(
                {
                    "check_fail_count": sum(
                        check["outcome"] == "FAIL" for check in checks
                    ),
                    "check_warn_count": sum(
                        check["outcome"] == "WARN" for check in checks
                    ),
                    "check_unknown_count": sum(
                        check["outcome"] == "UNKNOWN" for check in checks
                    ),
                }
            )
            # 明确重建顶层对象，既锁定 PRD 字段集合/顺序，也不修改 analyzer
            # 返回值，便于后续调用方复用同一分析结果。
            result = {
                "analyzer_version": analysis["analyzer_version"],
                "parser_version": analysis["parser_version"],
                "ruleset_version": DATING_RULESET_VERSION,
                "supported": analysis["supported"],
                "detected_domain": analysis["detected_domain"],
                "verdict": verdict,
                "selection_error": analysis["selection_error"],
                "task_ids": analysis["task_ids"],
                "summary": summary,
                "interface_statistics": analysis["interface_statistics"],
                "flow_steps": analysis["flow_steps"],
                "calls": analysis["calls"],
                "task_snapshot": analysis["task_snapshot"],
                "checks": checks,
                "parse_warnings": analysis["parse_warnings"],
            }
            safe_result = redact_dating_response(result)
            safe_result["report_markdown"] = render_dating_report(
                safe_result, safe_result["checks"]
            )
            # 仅 Dating 成功响应关闭键排序；People、export、health 等路由
            # 继续沿用 Flask 默认序列化，避免改变其既有响应字节合同。
            response_body = app.json.dumps(
                safe_result,
                sort_keys=False,
                separators=(",", ":"),
            )
            return app.response_class(
                response_body + "\n",
                status=200,
                mimetype="application/json",
            )
        except Exception:
            # 客户端只接收稳定错误码；完整堆栈仅写入服务端日志供排障。
            app.logger.exception("Dating 结构化分析发生未预期异常")
            return error_response(
                "ANALYSIS_INTERNAL_ERROR", "Dating 分析失败", 500
            )

    @tool.route("/people-search/analyze", methods=["POST"])
    def analyze_people_search():
        """People Insight 检索日志分析接口（设计 §13）。

        请求:
            JSON: {"log_text": "...", "task_id": "可选"}

        返回:
            成功 200：{code, message, data:{verdict, task, coverage, timeline,
                     checks, cost, ai, report_markdown}}。
            400 EMPTY_LOG、422 UNSUPPORTED_LOG/MULTIPLE_TASKS_FOUND、
            500 ANALYSIS_INTERNAL_ERROR。
            AI 默认关闭，data.ai.status 为 DISABLED；规则报告始终返回。
        """
        if not app.config["PEOPLE_SEARCH_ANALYZER_ENABLED"]:
            return jsonify({
                "code": 1,
                "message": "检索分析功能未启用",
                "error_code": "ANALYZER_DISABLED",
            }), 503

        payload = request.get_json(silent=True) or {}
        log_text = payload.get("log_text", "") or ""
        task_id = payload.get("task_id") or None
        if not log_text.strip():
            return jsonify({
                "code": 1,
                "message": "日志内容为空",
                "error_code": "EMPTY_LOG",
            }), 400

        try:
            # 延迟导入避免与 people_search_analyzer -> app 的循环导入。
            from people_search_analyzer import (
                ANALYZER_VERSION,
                RULESET_VERSION,
                analyze_people_search_log,
            )
            from people_search_ai import (
                attach_ai_to_report,
                load_ai_config,
                summarize_with_ai,
            )
            from people_search_rules import (
                redact_for_response,
                render_rule_report,
                run_all_checks,
            )

            result = analyze_people_search_log(log_text, task_id)
            if not result["supported"]:
                return jsonify({
                    "code": 1,
                    "message": "未识别到 People Insight 检索接口",
                    "error_code": "UNSUPPORTED_LOG",
                }), 422
            if result["selection_error"]:
                return jsonify({
                    "code": 1,
                    "message": result["selection_error"],
                    "error_code": result["selection_error"],
                    "detected_task_ids": result["task_ids"],
                }), 422

            snapshot = result["snapshot"]
            warnings = list(result["parse_warnings"])
            checks, verdict, _ = run_all_checks(snapshot, warnings)
            report_markdown = render_rule_report(result)

            # 可选 AI 总结（§11~§12）：默认关闭，配置齐全后开启；
            # 任何失败（超时、HTTP 错、非法响应）都只降级为规则报告。
            ai_status = {"status": "DISABLED"}
            if app.config["PEOPLE_SEARCH_ANALYZER_AI_ENABLED"]:
                ai_cfg = load_ai_config(
                    signed_user_context=request.headers.get("X-Platform-User-Context", ""),
                    resource_id=f"request-{uuid.uuid4().hex}",
                )
                ai_text, ai_status, _ = summarize_with_ai(result, ai_cfg)
                report_markdown = attach_ai_to_report(report_markdown, ai_text)

            data = {
                "analyzer_version": ANALYZER_VERSION,
                "ruleset_version": RULESET_VERSION,
                "policy_version": snapshot.get("policy_version"),
                "verdict": verdict,
                "task": snapshot["task"],
                "coverage": snapshot["coverage"],
                "timeline": snapshot["timeline"],
                "diagnosis": redact_for_response(snapshot["diagnosis"]),
                "checks": redact_for_response(checks),
                "cost": snapshot["cost"],
                "ai": ai_status,
                "report_markdown": report_markdown,
            }
            return jsonify({"code": 0, "message": "ok", "data": data}), 200
        except Exception:
            return jsonify({
                "code": 1,
                "message": "分析失败",
                "error_code": "ANALYSIS_INTERNAL_ERROR",
            }), 500

    @tool.route("/export", methods=["POST"])
    def export_log():
        """接收页面日志内容并保存到配置的固定导出目录。

        请求参数:
            JSON 中的 export_type 表示日志来源，content 表示待保存文本。

        返回值:
            成功时返回文件名和用户可见路径；参数错误返回 400，写入错误返回 500。

        异常处理:
            参数校验错误不会创建文件；文件系统异常只返回简洁错误信息，
            不允许客户端控制服务端保存目录。
        """
        payload = request.get_json(silent=True) or {}
        # 纯参数校验必须先于平台快照登记，避免 400 请求留下永久孤儿 ACL。
        export_type = payload.get("export_type")
        if export_type not in EXPORT_FILE_TYPES:
            return jsonify({"message": "不支持的导出类型"}), 400
        if not isinstance(payload.get("content"), str) or not payload["content"].strip():
            return jsonify({"message": "当前内容为空，无法导出"}), 400
        export_content = payload["content"]
        if export_type in {"dating_analysis_report", "dating_analysis_json"}:
            # Dating 导出在任何 ACL 登记或写盘之前执行同一后端脱敏入口；
            # JSON 必须先解析真实结构，不能把未验证字符串直接保存为 .json。
            from dating_log_rules import (
                redact_dating_document,
                redact_dating_response,
            )

            if export_type == "dating_analysis_json":
                try:
                    parsed_content = json.loads(export_content)
                except json.JSONDecodeError:
                    return jsonify({"message": "Dating JSON 内容格式无效"}), 400
                safe_content = redact_dating_response(parsed_content)
                # report_markdown 是完整文档而非普通字段：保留全部正文，仅
                # 执行文档级内嵌敏感信息扫描；其他 JSON 字段继续遵守 20k。
                if (
                    isinstance(parsed_content, dict)
                    and isinstance(parsed_content.get("report_markdown"), str)
                    and isinstance(safe_content, dict)
                ):
                    safe_content["report_markdown"] = redact_dating_document(
                        parsed_content["report_markdown"]
                    )
                export_content = json.dumps(
                    safe_content,
                    ensure_ascii=False,
                    indent=2,
                )
            else:
                export_content = redact_dating_document(export_content)
        # 平台模式下必须先得到对象级 create 决策；不能根据浏览器自报 owner、
        # project 或文件名决定导出路径。独立模式保持既有本地导出兼容行为。
        decision = verified_resource_access("export", "export")
        if decision is not None and decision.get("allowed") is not True:
            return jsonify({"message": "资源不存在"}), 404
        export_root_id = f"export_{uuid.uuid4().hex}"
        export_dir = app.config["LOG_EXPORT_DIR"]
        if decision is not None:
            owner_user_id = str(decision.get("user_id") or "")
            if not owner_user_id:
                return jsonify({"message": "资源不存在"}), 404
            if not register_root_resource("export", export_root_id):
                return jsonify({"message": "资源不存在"}), 404
            # 使用平台确认的 owner 和不可预测根资源 ID 物理隔离文件，阻断
            # 公共目录枚举与通过时间戳猜测其他用户导出物的可能。
            export_dir = Path(export_dir) / owner_user_id / export_root_id
        try:
            saved_path = save_exported_log(
                export_content,
                export_type,
                export_dir,
            )
        except ValueError as error:
            return jsonify({"message": str(error)}), 400
        except OSError as error:
            return jsonify({"message": f"导出失败：{error}"}), 500

        if decision is not None:
            return jsonify(
                {
                    "message": "导出成功",
                    # 外部只获得当前请求绑定的下载标识，不泄露服务端文件名或路径。
                    "download_id": export_root_id,
                }
            )
        display_path = Path(app.config["LOG_EXPORT_DISPLAY_DIR"]) / saved_path.name
        return jsonify(
            {
                "message": "导出成功",
                "filename": saved_path.name,
                "path": str(display_path),
            }
        )

    @tool.route("/health", methods=["GET"])
    def health():
        """返回不依赖日志文件和分析逻辑的轻量服务状态。"""
        response = jsonify({
            "service": "log-filter", "status": "ok",
            "version": os.getenv("APP_VERSION", "unknown"),
            "revision": os.getenv("APP_REVISION", "unknown"),
            "dirty": os.getenv("APP_BUILD_DIRTY", "true").lower() == "true",
            "content_sha256": os.getenv("APP_CONTENT_SHA256", "unknown"),
            "runtime_environment": os.getenv("PLATFORM_RUNTIME_ENV", "unknown"),
        })
        response.headers["Cache-Control"] = "no-store"
        return response

    app.register_blueprint(tool, url_prefix=normalized_base_path)
    return app


app = create_app() if Flask is not None else None


if __name__ == "__main__":
    create_app().run(
        debug=False,
        host=os.environ.get("LOG_FILTER_HOST", "127.0.0.1"),
        port=int(os.environ.get("LOG_FILTER_PORT", "5001")),
    )
