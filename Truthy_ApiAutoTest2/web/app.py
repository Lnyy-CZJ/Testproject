"""Flask 应用工厂、路由与页面。

功能说明:
    壳服务全部路由挂载在单个 Blueprint 上，通过 ``url_prefix`` 适配
    根路径与平台子路径两种运行模式；页面为服务端渲染 + 原生 JS，
    JS 接口基址由模板注入 ``window.__BASE_PATH__``，不硬编码根路径。
"""

from __future__ import annotations

import json
import hmac
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from flask import (
    Blueprint,
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from web import catalog as catalog_module
from web import credentials
from web.junit_report import parse_junit_file
from web.task_manager import SubmissionError, TaskManager
from web.task_store import TaskStore, is_valid_task_id

# 壳服务默认定位的框架项目根目录（web/ 的上一级）。
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 列表分页默认与上限（沿用平台约定）。
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 日志 tail 默认行数与上限。
DEFAULT_LOG_TAIL = 500
MAX_LOG_TAIL = 2000


def _platform_json_response(response: Any) -> dict[str, Any]:
    """解析平台 JSON 响应，并保留已经脱敏的稳定业务错误。

    平台 API 的 ``code``/``message`` 是面向工具的安全契约。若响应体不是该
    契约，则仍调用 ``raise_for_status`` 并由上层统一降级为 503，避免把原始
    HTML、代理报错或内部异常文本透传给浏览器。
    """

    status_code = getattr(response, "status_code", 200)
    if isinstance(status_code, int) and status_code >= 400:
        try:
            error = response.json()
            code = error.get("code") if isinstance(error, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
        except ValueError:
            code = message = None
        if isinstance(code, str) and code and isinstance(message, str) and message:
            raise SubmissionError(status_code, code, message)
        response.raise_for_status()
        raise ValueError("invalid platform error response")

    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("invalid platform response")
    return payload


def validate_base_path(value: str) -> str:
    """校验并规范化 URL 基础路径。

    功能说明:
        空值合法（根路径模式）；非空必须以 ``/`` 开头并去除末尾 ``/``，
        禁止查询参数、锚点、协议、``..`` 与重复斜杠。

    异常说明:
        ValueError: 非法基础路径，应由启动入口直接报错退出。
    """
    value = (value or "").strip()
    if value == "":
        return ""
    if not value.startswith("/"):
        raise ValueError(f"基础路径必须以 / 开头: {value!r}")
    if any(char in value for char in ("?", "#")) or "://" in value:
        raise ValueError(f"基础路径不得包含查询参数、锚点或协议: {value!r}")
    if "//" in value or ".." in value.split("/"):
        raise ValueError(f"基础路径不得包含重复斜杠或 ..: {value!r}")
    return value.rstrip("/")


def load_web_settings(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """从环境变量读取壳服务运行配置（含默认值）。

    参数说明:
        env: 环境变量映射；None 表示当前进程环境变量，测试可注入。

    异常说明:
        ValueError: 基础路径或数值型变量非法时抛出（启动即失败）。
    """
    env = env if env is not None else os.environ
    return {
        "host": env.get("API_AUTOTEST_HOST", "127.0.0.1"),
        "port": int(env.get("API_AUTOTEST_PORT", "5003")),
        "base_path": validate_base_path(env.get("API_AUTOTEST_BASE_PATH", "")),
        "platform_home_url": env.get("PLATFORM_HOME_URL", "/"),
        "timeout_seconds": int(env.get("API_AUTOTEST_TASK_TIMEOUT_SECONDS", "1800")),
        "tasks_retain": int(env.get("API_AUTOTEST_TASKS_RETAIN", "50")),
        "report_dir": env.get("API_AUTOTEST_REPORT_DIR", "reports/allure-current"),
        "config_source": env.get("API_AUTOTEST_CONFIG_SOURCE", "env"),
        "platform_api_url": env.get("PLATFORM_API_URL", "").rstrip("/"),
        "platform_client_token_file": env.get("PLATFORM_CLIENT_TOKEN_FILE", ""),
    }


def create_app(
    project_root: Path | None = None,
    settings: dict[str, Any] | None = None,
    task_manager: TaskManager | None = None,
) -> Flask:
    """创建壳服务 Flask 应用。

    参数说明:
        project_root: 框架项目根目录；None 使用默认定位。
        settings: 运行配置；None 时从当前进程环境变量读取。
        task_manager: 注入的执行引擎；None 时按配置创建并执行启动恢复。

    返回值:
        注册好全部路由的 Flask 应用。
    """
    root = Path(project_root) if project_root else DEFAULT_PROJECT_ROOT
    settings = settings or load_web_settings()
    store = TaskStore(root / "tasks", root / "reports")

    def platform_identity() -> tuple[str, Path, str]:
        """按调用读取平台地址和工具 Client Token。"""

        token_path = Path(settings.get("platform_client_token_file", ""))
        platform_api_url = str(settings.get("platform_api_url", "")).rstrip("/")
        if not platform_api_url or not token_path.is_file():
            raise SubmissionError(503, "PLATFORM_CONFIG_UNAVAILABLE", "平台运行配置客户端未正确部署")
        token = token_path.read_text(encoding="utf-8").strip()
        return platform_api_url, token_path, token

    def exchange_and_plan(
        signed_user_context: str,
        *,
        resource_type: str,
        resource_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """把网关签名兑换成 Context，并读取不含 Secret 的版本规划。"""

        if not signed_user_context:
            raise SubmissionError(403, "RUNTIME_CONTEXT_REQUIRED", "当前请求缺少可信用户上下文")
        platform_api_url, _token_path, token = platform_identity()
        try:
            context_headers = {
                "Authorization": f"Bearer {token}",
                "X-Platform-User-Context": signed_user_context,
            }
            opaque_resource_context = request.headers.get("X-Platform-Resource-Context", "")
            if opaque_resource_context:
                context_headers["X-Platform-Resource-Context"] = opaque_resource_context
            context_response = requests.post(
                f"{platform_api_url}/internal/tools/api-autotest/runtime-contexts",
                headers=context_headers,
                json={"resource_type": resource_type, "resource_id": resource_id},
                timeout=5,
            )
            context_payload = _platform_json_response(context_response)
            runtime_context_id = context_payload.get("runtime_context_id")
            if not isinstance(runtime_context_id, str) or not runtime_context_id:
                raise ValueError("invalid runtime context")
            response = requests.get(
                f"{platform_api_url}/internal/tools/api-autotest/runtime-config",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "include_secrets": "false",
                    "runtime_context_id": runtime_context_id,
                },
                timeout=5,
            )
            payload = _platform_json_response(response)
        except SubmissionError:
            # PERSONAL_*/RUNTIME_* 等业务错误必须到达任务 API，不能被折叠成
            # 通用 503，否则用户无法判断应配置凭证还是重新登录。
            raise
        except (requests.RequestException, ValueError) as exc:
            raise SubmissionError(503, "PLATFORM_CONFIG_UNAVAILABLE", "平台运行配置暂时不可用") from exc
        if not isinstance(payload, dict) or payload.get("tool_id") != "api-autotest" or not payload.get("release_id"):
            raise SubmissionError(503, "PLATFORM_CONFIG_UNAVAILABLE", "平台未发布可用的接口自动化配置")
        return context_payload, payload

    def platform_runtime_plan(task_id: str, signed_user_context: str) -> dict[str, Any]:
        """为新任务返回可安全持久化的 Context 与 selector。"""

        context_payload, payload = exchange_and_plan(
            signed_user_context,
            resource_type="task",
            resource_id=task_id,
        )
        selector = payload.get("snapshot_selector")
        if selector is not None and not isinstance(selector, dict):
            raise SubmissionError(503, "PLATFORM_CONFIG_UNAVAILABLE", "平台配置选择器无效")
        return {
            "runtime_context_id": context_payload["runtime_context_id"],
            "runtime_context_expires_at": context_payload.get("expires_at"),
            "snapshot_selector": selector,
            # 仅保存平台 runtime-contexts 已确认的快照，不接受创建 API 的任何
            # owner/project 字段。缺失时平台模式的读取过滤会保持失败关闭。
            "resource_snapshot": context_payload.get("resource_snapshot"),
        }

    def platform_runtime_environment(record: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
        """在 pytest 子进程启动前按任务 selector 物化精确历史版本。"""

        runtime = record.get("runtime_context")
        if not isinstance(runtime, dict) or not runtime.get("runtime_context_id"):
            raise SubmissionError(403, "RUNTIME_CONTEXT_REQUIRED", "当前任务缺少可信用户上下文")
        runtime_context_id = str(runtime["runtime_context_id"])
        selector = runtime.get("snapshot_selector")
        platform_api_url, token_path, token = platform_identity()
        try:
            if selector is None:
                # 个人读取开关关闭期间保留旧单请求读取，开启后 selector 必定存在。
                response = requests.get(
                    f"{platform_api_url}/internal/tools/api-autotest/runtime-config",
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "include_secrets": "true",
                        "runtime_context_id": runtime_context_id,
                    },
                    timeout=5,
                )
            elif isinstance(selector, dict):
                response = requests.post(
                    f"{platform_api_url}/internal/tools/api-autotest/runtime-config/materialize",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "runtime_context_id": runtime_context_id,
                        "snapshot_selector": selector,
                    },
                    timeout=5,
                )
            else:
                raise SubmissionError(409, "RUNTIME_SNAPSHOT_INVALID", "任务配置快照无效，请重新提交任务")
            payload = _platform_json_response(response)
        except SubmissionError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise SubmissionError(503, "PLATFORM_CONFIG_UNAVAILABLE", "平台运行配置暂时不可用") from exc
        if not isinstance(payload, dict) or payload.get("tool_id") != "api-autotest":
            raise SubmissionError(503, "PLATFORM_CONFIG_UNAVAILABLE", "平台运行配置作用域不匹配")
        normal = payload.get("normal") if isinstance(payload.get("normal"), dict) else {}
        secrets = payload.get("secrets") if isinstance(payload.get("secrets"), dict) else {}
        credential = payload.get("credential_metadata") if isinstance(payload.get("credential_metadata"), dict) else {}
        providers = credential.get("providers") if isinstance(credential.get("providers"), dict) else {}
        gateway = providers.get("gateway_session") if isinstance(providers.get("gateway_session"), dict) else credential
        admin = providers.get("admin_login") if isinstance(providers.get("admin_login"), dict) else {}
        environment = {
            str(key): str(value) for key, value in {**normal, **secrets}.items()
            if value is not None
        }
        environment.update({
            "API_AUTOTEST_SESSION_PROVIDER": "platform",
            "PLATFORM_API_URL": platform_api_url,
            "PLATFORM_CLIENT_TOKEN_FILE": str(token_path),
            "PLATFORM_RUNTIME_CONTEXT_ID": runtime_context_id,
            "PLATFORM_CREDENTIAL_ID": str(gateway.get("credential_id") or ""),
            "PLATFORM_CREDENTIAL_VERSION": str(gateway.get("credential_version") or 0),
            "PLATFORM_ADMIN_CREDENTIAL_ID": str(admin.get("credential_id") or ""),
            "PLATFORM_ADMIN_CREDENTIAL_VERSION": str(admin.get("credential_version") or 0),
        })
        return environment, {
            "release_id": payload.get("release_id"),
            "release_version": payload.get("release_version"),
            "credential_version": gateway.get("credential_version"),
        }

    def platform_configured_secret_keys(signed_user_context: str) -> set[str] | None:
        """读取平台 Secret 管理已配置的 Secret 键名清单（只读键名不取值）。

        功能说明:
            以 ``include_secrets=false`` 调用平台运行配置接口，供提交前
            Admin 凭证预检与页面凭证状态判定；Secret 值不进入壳服务内存。

        返回值:
            已配置 Secret 键名集合；客户端未部署、请求失败或响应非法时
            返回 None，由调用方决定降级策略。
        """
        try:
            _context, payload = exchange_and_plan(
                signed_user_context,
                resource_type="request",
                resource_id=f"credential-status-{uuid.uuid4().hex}",
            )
        except OSError:
            return None
        if not isinstance(payload, dict) or payload.get("tool_id") != "api-autotest":
            return None
        keys = payload.get("configured_secret_keys")
        if not isinstance(keys, list):
            return None
        return {str(key) for key in keys}

    platform_mode = settings.get("config_source") == "platform"
    manager = task_manager or TaskManager(
        root,
        store,
        timeout_seconds=settings["timeout_seconds"],
        retain=settings["tasks_retain"],
        runtime_environment_provider=(
            platform_runtime_environment if platform_mode else None
        ),
        runtime_plan_provider=(platform_runtime_plan if platform_mode else None),
        platform_secret_keys_provider=(
            platform_configured_secret_keys if platform_mode else None
        ),
    )
    if task_manager is None:
        manager.recover_on_startup()

    app = Flask(__name__)
    app.config["AUTOTEST_ROOT"] = root
    app.config["AUTOTEST_SETTINGS"] = settings
    app.config["AUTOTEST_MANAGER"] = manager
    app.config["AUTOTEST_SECRET_KEYS_PROVIDER"] = (
        platform_configured_secret_keys if platform_mode else None
    )
    app.config["JSON_AS_ASCII"] = False

    @app.before_request
    def validate_platform_csrf():
        """平台模式校验所有写请求的双提交 CSRF Token。"""

        if not settings.get("platform_api_url") or request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        cookie = request.cookies.get("tp_csrf", "")
        submitted = request.headers.get("X-CSRF-Token", "") or request.form.get("_csrf", "")
        if not cookie or not submitted or not hmac.compare_digest(cookie, submitted):
            return jsonify({"error": "请求安全校验失败", "error_code": "CSRF_INVALID"}), 403
        return None

    @app.after_request
    def platform_response_hooks(response):
        """为 HTML 注入 CSRF fetch 包装，并最大尽力上报写操作审计。"""

        platform_api_url = str(settings.get("platform_api_url", "")).rstrip("/")
        if platform_api_url and response.content_type and response.content_type.startswith("text/html"):
            script = """<script>
function platformCsrf(){const p='tp_csrf=';const v=document.cookie.split(';').map(x=>x.trim()).find(x=>x.startsWith(p));return v?decodeURIComponent(v.slice(p.length)):'';}
const platformFetch=window.fetch.bind(window);window.fetch=function(resource,options){const next=Object.assign({},options||{});const method=String(next.method||'GET').toUpperCase();if(!['GET','HEAD','OPTIONS'].includes(method)){next.headers=Object.assign({},next.headers||{}, {'X-CSRF-Token':platformCsrf()});}return platformFetch(resource,next);};
</script>"""
            response.set_data(response.get_data(as_text=True).replace("</head>", f"{script}</head>"))
        if request.method in {"GET", "HEAD", "OPTIONS"} or not platform_api_url:
            return response
        try:
            token_path = Path(settings.get("platform_client_token_file", ""))
            token = token_path.read_text(encoding="utf-8").strip()
            requests.post(
                f"{platform_api_url}/internal/tools/api-autotest/audit-events",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "event_id": f"evt_{uuid.uuid4().hex}",
                    "action": f"tool.{request.endpoint or 'write'}",
                    "resource_type": "api_autotest_task",
                    "outcome": "success" if response.status_code < 400 else ("denied" if response.status_code == 403 else "failed"),
                    "error_code": "CSRF_INVALID" if response.status_code == 403 else None,
                    "actor_user_id": request.headers.get("X-Platform-User-ID"),
                    "actor_username": request.headers.get("X-Platform-Username"),
                    "metadata": {},
                }, timeout=1,
            )
        except (OSError, requests.RequestException):
            pass
        return response

    blueprint = Blueprint(
        "apiautotest",
        __name__,
        template_folder="templates",
    )
    _register_routes(blueprint)
    app.register_blueprint(blueprint, url_prefix=settings["base_path"] or None)

    @app.errorhandler(SubmissionError)
    def _handle_submission_error(error: SubmissionError):
        """统一拒绝响应：可读信息 + 稳定错误码。"""
        return (
            jsonify({"error": error.message, "error_code": error.error_code}),
            error.status_code,
        )

    return app


def _get_manager() -> TaskManager:
    """从 Flask 全局上下文中取出执行引擎。"""
    from flask import current_app

    return current_app.config["AUTOTEST_MANAGER"]


def _get_root() -> Path:
    """从 Flask 全局上下文中取出项目根目录。"""
    from flask import current_app

    return current_app.config["AUTOTEST_ROOT"]


def _get_settings() -> dict[str, Any]:
    """从 Flask 全局上下文中取出运行配置。"""
    from flask import current_app

    return current_app.config["AUTOTEST_SETTINGS"]


def _resource_access(action: str, root_resource_id: str | None = None) -> dict[str, Any] | None:
    """将 opaque 资源上下文交给平台核验，返回平台确认的访问决策。

    独立运行没有平台地址时返回 ``None`` 以维持现有单用户使用方式。平台模式
    从不解码浏览器 Header；上下文、工具 Token、动作和根任务 ID 均由平台端
    校验，任何错误统一为 404，防止通过错误差异枚举任务或报告。
    """
    settings = _get_settings()
    platform_api_url = str(settings.get("platform_api_url") or "").rstrip("/")
    if not platform_api_url:
        return None
    opaque_context = request.headers.get("X-Platform-Resource-Context", "")
    token_path = Path(str(settings.get("platform_client_token_file") or ""))
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if not opaque_context or not token:
        abort(404)
    try:
        response = requests.post(
            f"{platform_api_url}/internal/tools/api-autotest/resource-access/check",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Platform-Resource-Context": opaque_context,
            },
            json={
                "action": action,
                "resource_type": "task",
                "root_resource_id": root_resource_id,
            },
            timeout=3,
        )
        decision = _platform_json_response(response)
    except (SubmissionError, ValueError, OSError, requests.RequestException):
        abort(404)
    if decision.get("allowed") is not True:
        abort(404)
    return decision


def _visible_task_records(records: list[dict[str, Any]], decision: dict[str, Any] | None) -> list[dict[str, Any]]:
    """按平台已验证的 own/project/global scope 在读取时过滤任务记录。

    ``resource_snapshot`` 只能由创建 root task 时的平台响应写入。旧记录在
    平台模式下没有快照时不对非 global 用户可见，避免迁移遗漏变成越权读取。
    """
    if decision is None or decision.get("data_scope") == "global":
        return records
    user_id = str(decision.get("user_id") or "")
    managed_project_ids = {str(item) for item in decision.get("managed_project_ids") or []}
    visible: list[dict[str, Any]] = []
    for record in records:
        snapshot = record.get("resource_snapshot")
        if not isinstance(snapshot, dict):
            continue
        if decision.get("data_scope") == "own":
            if snapshot.get("owner_user_id") == user_id:
                visible.append(record)
        elif decision.get("data_scope") == "project":
            if str(snapshot.get("project_id_snapshot") or "") in managed_project_ids:
                visible.append(record)
    return visible


def _get_secret_keys_provider() -> Callable[[], set[str] | None] | None:
    """取出平台 Secret 键名清单读取器；独立模式为 None。"""
    from flask import current_app

    return current_app.config.get("AUTOTEST_SECRET_KEYS_PROVIDER")


def _parse_page_args() -> tuple[int, int]:
    """解析分页参数并夹取到合法范围。"""
    try:
        page = max(int(request.args.get("page", 1)), 1)
        page_size = int(request.args.get("page_size", DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        abort(400, description="page/page_size 必须是整数")
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    return page, page_size


def _require_task(task_id: str, action: str = "read") -> dict[str, Any]:
    """取任务记录；ID 非法或不存在时 404。"""
    if not is_valid_task_id(task_id):
        abort(404, description=f"任务不存在: {task_id}")
    record = _get_manager().store.load(task_id)
    if record is None:
        abort(404, description=f"任务不存在: {task_id}")
    _resource_access(action, task_id)
    return record


def _resolve_report_dir(task_id: str) -> Path | None:
    """解析指定任务 current 指针指向的真实目录；不存在返回 None。

    异常说明:
        Docker Desktop for Mac 绑定挂载在宿主机原子切换 symlink 后，
        容器内残留句柄可能使 stat 抛 OSError(EINVAL) 而非 ENOENT；
        报告展示属只读端点，此类文件系统异常按“暂无报告”降级处理，
        避免 meta/报告页返回 500（重启容器可刷新挂载视图）。
    """
    # ``report_dir`` 的父目录继续作为可配置报告根，实际读取始终进入任务
    # 专属目录，不能退回历史的全局 allure-current 单槽。
    configured = _get_root() / _get_settings()["report_dir"]
    report_dir = configured.parent / "task-reports" / task_id / "current"
    try:
        if not report_dir.exists():
            return None
        return report_dir.resolve()
    except OSError:
        return None


def _resolve_task_report_dir(task_id: str) -> tuple[Path, dict[str, Any]] | None:
    """解析并校验与根任务绑定的 Allure 报告目录。

    报告发布目录通过 ``task-reports/<task_id>/current`` 独立切换，目录中的
    ``report-meta.json`` 必须显式记录同一个 ``task_id``。仅仅拥有某个任务
    的读取权，不能借此读取当前指针中属于另一任务的报告。元数据缺失、损坏
    或绑定不一致时统一视为报告不存在，避免旧的全局报告产生跨账号泄露。

    参数说明:
        task_id: 已由任务路由校验存在且可访问的根任务 ID。

    返回值:
        ``(报告真实目录, 元数据)``；无法证明任务绑定时返回 ``None``。
    """

    report_dir = _resolve_report_dir(task_id)
    if report_dir is None or not report_dir.is_dir():
        return None
    meta_path = report_dir / "report-meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict) or meta.get("task_id") != task_id:
        return None
    return report_dir, meta


def _register_routes(blueprint: Blueprint) -> None:
    """把全部路由注册到壳服务 Blueprint。"""

    # ---------------- 页面 ----------------

    @blueprint.get("/")
    def index_page():
        """首页：执行表单、凭证状态、报告入口与最近任务。"""
        root = _get_root()
        return render_template(
            "index.html",
            base_path=_get_settings()["base_path"],
            platform_home_url=_get_settings()["platform_home_url"],
            envs=credentials.list_envs(root),
            flows=credentials.list_flows(root),
        )

    @blueprint.get("/tasks/<task_id>")
    def task_detail_page(task_id: str):
        """任务详情页：参数、时间线、统计、失败清单与日志。"""
        _require_task(task_id)
        return render_template(
            "task_detail.html",
            base_path=_get_settings()["base_path"],
            platform_home_url=_get_settings()["platform_home_url"],
            task_id=task_id,
        )

    @blueprint.get("/catalog")
    def catalog_page():
        """用例库页：API / Case / Flow 清单与解析错误。"""
        return render_template(
            "catalog.html",
            base_path=_get_settings()["base_path"],
            platform_home_url=_get_settings()["platform_home_url"],
        )

    # ---------------- 任务接口 ----------------

    @blueprint.post("/api/tasks")
    def submit_task():
        """提交任务；校验失败 400，槽位占用 409。"""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise SubmissionError(400, "INVALID_PARAMS", "请求体必须是 JSON 对象")
        record = _get_manager().submit(
            env=str(payload.get("env") or ""),
            run_type=str(payload.get("run_type") or ""),
            flow=payload.get("flow"),
            tag=payload.get("tag"),
            signed_user_context=request.headers.get("X-Platform-User-Context", ""),
        )
        return (
            jsonify(
                {
                    "id": record["id"],
                    "status": record["status"],
                    "created_at": record["created_at"],
                }
            ),
            201,
        )

    @blueprint.get("/api/tasks")
    def list_tasks():
        """任务列表（分页，ID 倒序）。"""
        page, page_size = _parse_page_args()
        try:
            decision = _resource_access("list")
        except Exception as exc:  # pragma: no cover - abort 会中断请求，此处仅为类型兜底
            if getattr(exc, "code", None) == 404:
                return jsonify({"items": [], "page": page, "page_size": page_size, "total": 0})
            raise
        records = _visible_task_records(_get_manager().store.list(), decision)
        total = len(records)
        start = (page - 1) * page_size
        items = records[start : start + page_size]
        return jsonify(
            {"items": items, "page": page, "page_size": page_size, "total": total}
        )

    @blueprint.get("/api/tasks/<task_id>")
    def task_detail_api(task_id: str):
        """任务详情：记录全量字段。"""
        return jsonify(_require_task(task_id))

    @blueprint.post("/api/tasks/<task_id>/cancel")
    def cancel_task(task_id: str):
        """取消任务；不存在 404，已终态 409。"""
        _require_task(task_id, "cancel")
        record = _get_manager().cancel(task_id)
        return jsonify({"id": record["id"], "status": record["status"]})

    @blueprint.get("/api/tasks/<task_id>/result")
    def task_result(task_id: str):
        """任务结果摘要：统计 + 失败清单；无 JUnit 时给出原因码。"""
        record = _require_task(task_id)
        root = _get_root()
        parsed = parse_junit_file(root / record["junit_file"], root)
        if parsed is None:
            return jsonify(
                {
                    "status": record["status"],
                    "result_available": False,
                    "summary": None,
                    "failed_cases": [],
                    "reason_code": "JUNIT_NOT_GENERATED",
                }
            )
        return jsonify(
            {
                "status": record["status"],
                "result_available": True,
                "summary": parsed["summary"],
                "failed_cases": parsed["failed_cases"],
            }
        )

    @blueprint.get("/api/tasks/<task_id>/logs")
    def task_logs(task_id: str):
        """任务日志：优先框架脱敏日志，兜底二次脱敏后的 console 尾部。"""
        record = _require_task(task_id)
        try:
            tail = int(request.args.get("tail", DEFAULT_LOG_TAIL))
        except (TypeError, ValueError):
            abort(400, description="tail 必须是整数")
        tail = max(1, min(tail, MAX_LOG_TAIL))

        root = _get_root()
        log_file = record.get("log_file")
        if log_file:
            log_path = root / log_file
            if log_path.is_file():
                lines = log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                return jsonify(
                    {"log_file": log_file, "lines": lines[-tail:], "source": "framework_log"}
                )

        console_path = _get_manager().store.console_log_path(task_id)
        if console_path.is_file():
            from web.redaction import DEFAULT_MAX_LENGTH, redact_text

            content = console_path.read_text(encoding="utf-8", errors="replace")
            redacted = redact_text(
                content, project_root=root, max_length=DEFAULT_MAX_LENGTH * 5
            )
            return jsonify(
                {
                    "log_file": None,
                    "lines": redacted.splitlines()[-tail:],
                    "source": "console_redacted",
                }
            )
        return jsonify({"log_file": None, "lines": [], "source": "none"})

    # ---------------- 用例库、凭证状态、报告 ----------------

    @blueprint.get("/api/catalog")
    def catalog_api():
        """用例库清单；单文件解析失败进入 errors 数组。"""
        return jsonify(catalog_module.build_catalog(_get_root()))

    @blueprint.get("/api/credentials/status")
    def credentials_status():
        """凭证就绪状态（只返回状态与缺失字段名，不返回值）。"""
        root = _get_root()
        provider = _get_secret_keys_provider()
        # Provider 本身需要当前浏览器请求的可信签名；闭包生命周期仅限本次
        # 调用，签名不会进入返回值、应用配置或浏览器存储。
        def scoped_provider() -> set[str] | None:
            """状态页把平台拒绝显示为未就绪，任务提交仍严格透传错误。"""

            if provider is None:
                return None
            try:
                return provider(request.headers.get("X-Platform-User-Context", ""))
            except SubmissionError:
                return None

        return jsonify(
            credentials.credential_status(
                env=request.args.get("env", "test"),
                run_type=request.args.get("run_type", "all"),
                flow=request.args.get("flow") or None,
                tag=request.args.get("tag") or None,
                project_root=root,
                platform_secret_keys_provider=(
                    scoped_provider if provider is not None else None
                ),
            )
        )

    @blueprint.get("/api/report/meta")
    def report_meta():
        """返回与指定根任务强绑定的报告元信息。"""
        task_id = request.args.get("task_id", "").strip()
        if not task_id:
            return jsonify({"exists": False, "report_url": None})
        _require_task(task_id)
        resolved = _resolve_task_report_dir(task_id)
        if resolved is None:
            return jsonify({"exists": False, "report_url": None})
        _report_dir, meta = resolved
        report_url = url_for(
            "apiautotest.report_file", task_id=task_id, filename="index.html"
        )
        return jsonify({"exists": True, "report_url": report_url, **meta})

    @blueprint.get("/reports/<task_id>/<path:filename>")
    def report_file(task_id: str, filename: str):
        """读取根任务绑定的 Allure 静态资源，未知或错绑统一返回 404。"""
        _require_task(task_id)
        resolved = _resolve_task_report_dir(task_id)
        if resolved is None:
            abort(404, description="报告尚未发布")
        report_dir, _meta = resolved
        return send_from_directory(report_dir, filename)

    # ---------------- 健康检查 ----------------

    @blueprint.get("/health")
    def health():
        """健康检查：不触发执行、不读凭证、不依赖外部 Gateway。"""
        return jsonify({
            "status": "ok", "service": "api-autotest",
            "version": os.getenv("APP_VERSION", "unknown"),
            "revision": os.getenv("APP_REVISION", "unknown"),
            "dirty": os.getenv("APP_BUILD_DIRTY", "true").lower() == "true",
            "content_sha256": os.getenv("APP_CONTENT_SHA256", "unknown"),
            "runtime_environment": os.getenv("PLATFORM_RUNTIME_ENV", "unknown"),
        })


def main() -> None:
    """独立模式启动入口：python -m web.app。"""
    settings = load_web_settings()
    app = create_app(settings=settings)
    # 与既有工具一致：容器内使用 Flask 自带服务器，不引入 Gunicorn。
    app.run(host=settings["host"], port=settings["port"])


if __name__ == "__main__":
    main()
