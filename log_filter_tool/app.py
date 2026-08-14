import hmac
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib import request as urlrequest

try:
    from flask import Blueprint, Flask, jsonify, render_template, request
except ImportError:  # Allows core log parsing tests to run before Flask is installed.
    Blueprint = None
    Flask = None
    jsonify = None
    render_template = None
    request = None


ALL_METHOD = "__ALL__"
METHOD_PATTERNS = (
    re.compile(r"method=([A-Za-z0-9_]+)"),
    re.compile(r'"method_name"\s*:\s*"([A-Za-z0-9_]+)"'),
)
CONSOLE_PREFIX_PATTERN = re.compile(r"^.*?\bflutter:\s?")
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
}
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


def clean_log_line(line):
    line = CONSOLE_PREFIX_PATTERN.sub("", line, count=1)
    stripped_line = line.lstrip()
    if stripped_line.startswith(("┌", "└")):
        return ""
    if line.startswith("│ "):
        return line[2:]
    if line.startswith("│"):
        return line[1:]
    return line.replace("│", "")


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
    """将页面中的日志文本安全保存为不覆盖已有文件的 .log 文件。

    功能说明:
        根据导出来源生成带时间戳的文件名，并使用独占创建模式避免覆盖
        已存在的日志文件。

    参数说明:
        content (str): 需要导出的当前文本框内容，不能为空或仅包含空白。
        export_type (str): 导出来源，支持 log_content、filtered_result 和 analysis_report。
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
    app.config["PEOPLE_SEARCH_ANALYZER_ENABLED"] = os.environ.get(
        "PEOPLE_SEARCH_ANALYZER_ENABLED", "true"
    ).lower() in ("1", "true", "yes", "on")
    app.config["PEOPLE_SEARCH_ANALYZER_AI_ENABLED"] = os.environ.get(
        "PEOPLE_SEARCH_ANALYZER_AI_ENABLED", "false"
    ).lower() in ("1", "true", "yes", "on")
    tool = Blueprint("tool", __name__)

    def client_token():
        """读取只读 Client Token，缺失时仅跳过审计上报。"""

        try:
            return Path(app.config["PLATFORM_CLIENT_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
        except (OSError, TypeError):
            return ""

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
        )

    @tool.route("/sample", methods=["GET"])
    def sample_log():
        sample_path = Path(__file__).with_name("log_default.log")
        return sample_path.read_text(encoding="utf-8") if sample_path.exists() else ""

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
                ai_cfg = load_ai_config()
                ai_text, ai_status, _ = summarize_with_ai(result, ai_cfg)
                report_markdown = attach_ai_to_report(report_markdown, ai_text)

            data = {
                "analyzer_version": ANALYZER_VERSION,
                "ruleset_version": RULESET_VERSION,
                "verdict": verdict,
                "task": snapshot["task"],
                "coverage": snapshot["coverage"],
                "timeline": snapshot["timeline"],
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
        try:
            saved_path = save_exported_log(
                payload.get("content"),
                payload.get("export_type"),
                app.config["LOG_EXPORT_DIR"],
            )
        except ValueError as error:
            return jsonify({"message": str(error)}), 400
        except OSError as error:
            return jsonify({"message": f"导出失败：{error}"}), 500

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
        response = jsonify({"service": "log-filter", "status": "ok"})
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
