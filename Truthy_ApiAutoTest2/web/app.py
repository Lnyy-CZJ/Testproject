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
from datetime import datetime
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
from utils.custom.project_registry import ProjectRegistry, ProjectRegistryError

# 壳服务默认定位的框架项目根目录（web/ 的上一级）。
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 列表分页默认与上限（沿用平台约定）。
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 日志 tail 默认行数与上限。
DEFAULT_LOG_TAIL = 500
MAX_LOG_TAIL = 2000

# 浏览器永远不能覆盖由平台实例、Runtime Scope 或 Release 决定的字段。
FORBIDDEN_TASK_OVERRIDE_KEYS = {
    "target_env",
    "gateway",
    "gateway_url",
    "gateway_base_url",
    "release",
    "release_id",
    "release_version",
    "timeout",
    "timeout_seconds",
    "poll_interval",
    "poll_interval_seconds",
    "secret",
    "secrets",
    "credential_profiles",
    "runtime_scope_id",
    "platform_environment",
    "platform_project_id",
}

# 项目资产使用稳定的“逻辑 Profile”，平台凭证中心继续使用现有 provider_type。
# 映射只发生在工具边界，避免把平台实现名写进 API/Flow 资产，后续平台迁移也不
# 需要批量修改项目 YAML。
_PROFILE_PROVIDER_ALIASES = {
    "anonymous_session": "gateway_session",
    "admin_session": "admin_login",
}
_READY_PROFILE_STATUSES = {"ready", "active", "healthy"}


def _credential_profiles(
    payload: Mapping[str, Any],
    required_profile_ids: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """从平台 Credential 元数据提取并规范化逻辑 Profile 摘要。

    ``required_profile_ids`` 由当前选中的 API/Flow 资产推导。传入后只返回这些
    Profile，并把平台 ``gateway_session``/``admin_login`` provider 映射为项目
    Manifest 中的逻辑名。这样 Dating 的匿名会话任务不会被未使用的 Truthy
    Admin Profile 阻断，同时缺失的实际依赖仍会显式返回 ``missing``。
    """

    metadata = payload.get("credential_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    raw_profiles: list[dict[str, Any]] = []
    profiles = metadata.get("profiles")
    if isinstance(profiles, list):
        raw_profiles.extend(dict(item) for item in profiles if isinstance(item, dict))
    else:
        providers = metadata.get("providers")
        if isinstance(providers, dict):
            for profile_id, item in sorted(providers.items()):
                if not isinstance(item, dict):
                    continue
                raw_profiles.append(
                    {
                        "id": profile_id,
                        "status": item.get("status", "ready"),
                        "version": item.get("credential_version"),
                    }
                )

    if required_profile_ids is None:
        return raw_profiles

    by_id = {
        str(item.get("id")): item
        for item in raw_profiles
        if isinstance(item.get("id"), str) and item.get("id")
    }
    result: list[dict[str, Any]] = []
    for logical_profile_id in dict.fromkeys(required_profile_ids):
        if logical_profile_id == "public":
            continue
        provider_id = _PROFILE_PROVIDER_ALIASES.get(
            logical_profile_id, logical_profile_id
        )
        item = by_id.get(logical_profile_id) or by_id.get(provider_id)
        if item is None:
            result.append(
                {"id": logical_profile_id, "status": "missing", "version": None}
            )
            continue
        raw_status = str(item.get("status") or "missing").lower()
        result.append(
            {
                "id": logical_profile_id,
                "status": (
                    "ready" if raw_status in _READY_PROFILE_STATUSES else raw_status
                ),
                "version": item.get("version")
                or item.get("credential_version"),
            }
        )
    return result


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
    settings = {
        "host": env.get("API_AUTOTEST_HOST", "127.0.0.1"),
        "port": int(env.get("API_AUTOTEST_PORT", "5003")),
        "base_path": validate_base_path(env.get("API_AUTOTEST_BASE_PATH", "")),
        "platform_home_url": env.get("PLATFORM_HOME_URL", "/"),
        "timeout_seconds": int(env.get("API_AUTOTEST_TASK_TIMEOUT_SECONDS", "1800")),
        "tasks_retain": int(env.get("API_AUTOTEST_TASKS_RETAIN", "50")),
        "report_dir": env.get("API_AUTOTEST_REPORT_DIR", "reports/allure-current"),
        "config_source": env.get("API_AUTOTEST_CONFIG_SOURCE", "local"),
        "platform_environment": env.get("PLATFORM_RUNTIME_ENV", "dev"),
        "platform_api_url": env.get("PLATFORM_API_URL", "").rstrip("/"),
        "platform_client_token_file": env.get("PLATFORM_CLIENT_TOKEN_FILE", ""),
    }
    if settings["platform_environment"] not in {"dev", "prod"}:
        raise ValueError("PLATFORM_RUNTIME_ENV 必须为 dev 或 prod")
    if settings["config_source"] not in {"local", "platform"}:
        raise ValueError("API_AUTOTEST_CONFIG_SOURCE 必须为 local 或 platform")
    return settings


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
    registry = ProjectRegistry(root / "projects")

    def platform_identity() -> tuple[str, Path, str]:
        """按调用读取平台地址和工具 Client Token。"""

        token_path = Path(settings.get("platform_client_token_file", ""))
        platform_api_url = str(settings.get("platform_api_url", "")).rstrip("/")
        if not platform_api_url or not token_path.is_file():
            raise SubmissionError(503, "PLATFORM_CONFIG_UNAVAILABLE", "平台运行配置客户端未正确部署")
        token = token_path.read_text(encoding="utf-8").strip()
        return platform_api_url, token_path, token

    def platform_runtime_scopes(signed_user_context: str) -> list[dict[str, Any]]:
        """读取当前签名用户可使用的 Scope 元数据，不读取配置值或 Secret。"""

        if not signed_user_context:
            raise SubmissionError(403, "RUNTIME_CONTEXT_REQUIRED", "当前请求缺少可信用户上下文")
        platform_api_url, _token_path, token = platform_identity()
        try:
            response = requests.get(
                f"{platform_api_url}/internal/tools/api-autotest/runtime-scopes",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Platform-User-Context": signed_user_context,
                },
                timeout=5,
            )
            payload = _platform_json_response(response)
        except SubmissionError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise SubmissionError(
                503, "PLATFORM_CONFIG_UNAVAILABLE", "平台 Runtime Scope 暂时不可用"
            ) from exc
        items = payload.get("items")
        if not isinstance(items, list):
            raise SubmissionError(503, "PLATFORM_CONFIG_UNAVAILABLE", "平台 Scope 响应无效")
        return [dict(item) for item in items if isinstance(item, dict)]

    def exchange_and_plan(
        signed_user_context: str,
        *,
        project_id: str,
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
                json={
                    "project_id": project_id,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                },
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

    def platform_runtime_plan(
        task_id: str,
        signed_user_context: str,
        selection: dict[str, Any],
    ) -> dict[str, Any]:
        """为新任务返回可安全持久化的 Context 与 selector。"""

        project_id = str(selection.get("project_id") or "")
        context_payload, payload = exchange_and_plan(
            signed_user_context,
            project_id=project_id,
            resource_type="task",
            resource_id=task_id,
        )
        selector = context_payload.get("snapshot_selector") or payload.get(
            "snapshot_selector"
        )
        if selector is not None and not isinstance(selector, dict):
            raise SubmissionError(503, "PLATFORM_CONFIG_UNAVAILABLE", "平台配置选择器无效")
        scope = context_payload.get("runtime_scope")
        scope = scope if isinstance(scope, dict) else {}
        runtime_scope_id = (
            scope.get("scope_id")
            or context_payload.get("runtime_scope_id")
            or payload.get("runtime_scope_id")
        )
        platform_environment = (
            scope.get("platform_environment")
            or context_payload.get("platform_environment")
            or payload.get("platform_environment")
            or payload.get("environment")
        )
        target_env = (
            scope.get("target_env")
            or context_payload.get("target_env")
            or payload.get("target_env")
        )
        required_profiles = _required_credential_profiles(project_id, selection)
        credential_profiles = _credential_profiles(payload, required_profiles)
        missing_profiles = [
            item
            for item in credential_profiles
            if str(item.get("status") or "").lower()
            not in _READY_PROFILE_STATUSES
        ]
        if missing_profiles:
            raise SubmissionError(
                409,
                "PROJECT_CREDENTIAL_MISSING",
                "当前资产所需凭证未就绪: "
                + ", ".join(str(item.get("id")) for item in missing_profiles),
            )
        package = _get_registry().get(project_id)
        missing_config_keys = _missing_project_config_keys(
            payload,
            package.manifest.config_contract.required_keys,
        )
        if missing_config_keys:
            raise SubmissionError(
                409,
                "PROJECT_CONFIG_MISSING",
                "当前 Release 缺少项目运行所需配置: "
                + ", ".join(missing_config_keys),
            )
        return {
            "runtime_context_id": context_payload["runtime_context_id"],
            "runtime_context_expires_at": context_payload.get("expires_at"),
            "runtime_scope_id": runtime_scope_id,
            "platform_project_id": (
                scope.get("platform_project_id")
                or context_payload.get("platform_project_id")
                or payload.get("platform_project_id")
            ),
            "platform_environment": platform_environment,
            "target_env": target_env,
            "config_source": "platform",
            "release_id": payload.get("release_id"),
            "release_version": payload.get("release_version"),
            "credential_profiles": credential_profiles,
            "snapshot_selector": selector,
            # 仅保存平台 runtime-contexts 已确认的快照，不接受创建 API 的任何
            # owner/project 字段。缺失时平台模式的读取过滤会保持失败关闭。
            "resource_snapshot": context_payload.get("resource_snapshot"),
        }

    def platform_preflight(
        project_id: str,
        signed_user_context: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """为页面预检创建短期 request Context，并读取不含 Secret 的配置摘要。"""

        return exchange_and_plan(
            signed_user_context,
            project_id=project_id,
            resource_type="request",
            resource_id=f"preflight-{uuid.uuid4().hex}",
        )

    def platform_runtime_snapshot(
        record: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
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
        project = record.get("project")
        project = project if isinstance(project, dict) else {}
        selection = record.get("selection")
        selection = selection if isinstance(selection, dict) else {}
        project_id = str(project.get("project_id") or selection.get("project_id") or "")
        required_profiles = _required_credential_profiles(project_id, selection)
        credential_profiles = _credential_profiles(payload, required_profiles)
        missing_profiles = [
            item
            for item in credential_profiles
            if str(item.get("status") or "").lower()
            not in _READY_PROFILE_STATUSES
        ]
        if missing_profiles:
            raise SubmissionError(
                409,
                "PROJECT_CREDENTIAL_MISSING",
                "任务快照所需凭证不可用，请重新提交任务",
            )
        process_environment = {
            "PLATFORM_API_URL": platform_api_url,
            "PLATFORM_CLIENT_TOKEN_FILE": str(token_path),
            "PLATFORM_RUNTIME_CONTEXT_ID": runtime_context_id,
        }
        metadata = payload.get("credential_metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        providers = metadata.get("providers")
        providers = providers if isinstance(providers, dict) else {}
        gateway_provider = providers.get("gateway_session")
        if isinstance(gateway_provider, dict):
            credential_id = gateway_provider.get("credential_id")
            credential_version = gateway_provider.get("credential_version")
            if credential_id and isinstance(credential_version, int):
                process_environment.update(
                    {
                        "API_AUTOTEST_SESSION_PROVIDER": "platform",
                        "PLATFORM_CREDENTIAL_ID": str(credential_id),
                        "PLATFORM_CREDENTIAL_VERSION": str(credential_version),
                    }
                )
        if "anonymous_session" in required_profiles and (
            "PLATFORM_CREDENTIAL_ID" not in process_environment
        ):
            raise SubmissionError(
                409,
                "RUNTIME_SNAPSHOT_INVALID",
                "任务快照缺少可写回的匿名会话 Credential",
            )
        return payload, {
            "runtime_scope_id": payload.get("runtime_scope_id")
            or record.get("runtime", {}).get("runtime_scope_id"),
            "release_id": payload.get("release_id"),
            "release_version": payload.get("release_version"),
            "credential_profiles": credential_profiles,
            "process_environment": process_environment,
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
                project_id="truthy",
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
        runtime_snapshot_provider=(platform_runtime_snapshot if platform_mode else None),
        runtime_plan_provider=(platform_runtime_plan if platform_mode else None),
        platform_secret_keys_provider=(
            platform_configured_secret_keys if platform_mode else None
        ),
        platform_environment=str(settings.get("platform_environment") or "dev"),
    )
    if task_manager is None:
        manager.recover_on_startup()

    app = Flask(__name__)
    app.config["AUTOTEST_ROOT"] = root
    app.config["AUTOTEST_SETTINGS"] = settings
    app.config["AUTOTEST_MANAGER"] = manager
    app.config["AUTOTEST_REGISTRY"] = registry
    app.config["AUTOTEST_SECRET_KEYS_PROVIDER"] = (
        platform_configured_secret_keys if platform_mode else None
    )
    app.config["AUTOTEST_SCOPE_PROVIDER"] = (
        platform_runtime_scopes if platform_mode else None
    )
    app.config["AUTOTEST_PREFLIGHT_PROVIDER"] = (
        platform_preflight if platform_mode else None
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
        static_folder="static",
        static_url_path="/static",
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


def _get_registry() -> ProjectRegistry:
    """取当前部署版本的项目包注册表。"""

    from flask import current_app

    return current_app.config["AUTOTEST_REGISTRY"]


def _get_scope_provider() -> Callable[[str], list[dict[str, Any]]] | None:
    """取平台授权 Scope 提供器；local 兼容模式为 None。"""

    from flask import current_app

    return current_app.config.get("AUTOTEST_SCOPE_PROVIDER")


def _get_preflight_provider() -> (
    Callable[[str, str], tuple[dict[str, Any], dict[str, Any]]] | None
):
    """取平台预检提供器。"""

    from flask import current_app

    return current_app.config.get("AUTOTEST_PREFLIGHT_PROVIDER")


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
    record = _get_manager().store.load(task_id) or {}
    normalized = _normalize_task_record(record)
    report_dir = configured.parent / "task-reports"
    if record.get("schema_version") == 2:
        report_dir = report_dir / normalized["project"]["project_id"]
    report_dir = report_dir / task_id / "current"
    try:
        if not report_dir.exists():
            return None
        return report_dir.resolve()
    except OSError:
        return None


def _resolve_task_report_dir(task_id: str) -> tuple[Path, dict[str, Any]] | None:
    """解析并校验与根任务绑定的 Allure 报告目录。

    报告发布目录通过 ``task-reports/<project_id>/<task_id>/current`` 独立切换，目录中的
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
    record = _normalize_task_record(_get_manager().store.load(task_id) or {})
    project_id = record.get("project", {}).get("project_id")
    if (
        not isinstance(meta, dict)
        or meta.get("task_id") != task_id
        or (
            record.get("schema_version") == 2
            and meta.get("project_id") != project_id
        )
    ):
        return None
    return report_dir, meta


def _project_items() -> list[dict[str, Any]]:
    """返回平台授权 Scope 与当前部署项目包的交集。"""

    try:
        packages = {item.project_id: item for item in _get_registry().list_projects()}
    except ProjectRegistryError as exc:
        raise SubmissionError(503, "PROJECT_PACKAGE_INVALID", "当前工具项目包无效") from exc
    provider = _get_scope_provider()
    if provider is None:
        target_env = {"dev": "test", "prod": "prod"}[
            str(_get_settings().get("platform_environment") or "dev")
        ]
        scopes = [
            {
                "project_id": package.project_id,
                "display_name": package.display_name,
                "platform_environment": _get_settings().get("platform_environment", "dev"),
                "target_env": target_env,
                "status": "local",
                "scope_id": None,
                "active_release": None,
                "management_url": None,
            }
            for package in packages.values()
        ]
    else:
        scopes = provider(request.headers.get("X-Platform-User-Context", ""))

    items: list[dict[str, Any]] = []
    for scope in scopes:
        project_id = str(scope.get("project_id") or "")
        package = packages.get(project_id)
        if package is None:
            # 平台有 Scope 但部署版本没有项目包时不能作为可执行项目暴露；
            # 平台配置中心仍可看到 Scope，本页只展示交集。
            continue
        catalog = catalog_module.build_catalog(_get_root(), project_id)
        release = scope.get("active_release") or scope.get("release")
        items.append(
            {
                "project_id": project_id,
                "display_name": package.display_name,
                "platform_project_id": scope.get("platform_project_id"),
                "platform_environment": scope.get("platform_environment")
                or _get_settings().get("platform_environment"),
                "target_env": scope.get("target_env"),
                "scope_id": scope.get("scope_id") or scope.get("runtime_scope_id") or scope.get("id"),
                "scope_status": scope.get("status"),
                "release": release if isinstance(release, dict) else None,
                "credential_profiles": scope.get("credential_profiles") or [],
                "management_url": scope.get("management_url"),
                "package_status": "valid" if not catalog["errors"] else "invalid",
                "counts": {
                    "apis": len(catalog["apis"]),
                    "cases": len(catalog["cases"]),
                    "flows": len(catalog["flows"]),
                },
            }
        )
    return sorted(items, key=lambda item: item["project_id"])


def _validate_selection_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """复用 TaskManager 的资产归属校验，但不创建任务或启动子进程。"""

    return _get_manager()._validate_input(  # noqa: SLF001 - 同一服务内的预检入口
        None,
        str(payload.get("run_type") or ""),
        None,
        payload.get("tag"),
        project_id=str(payload.get("project_id") or ""),
        api_id=payload.get("api_id"),
        case_id=payload.get("case_id"),
        flow_id=payload.get("flow_id"),
    )


def _required_credential_profiles(
    project_id: str,
    selection: Mapping[str, Any],
) -> list[str]:
    """根据当前选中的真实资产计算需要校验的逻辑 Profile。

    单接口只检查该 API；Flow 检查其步骤引用 API 的并集；``all`` 用于概览，
    表示执行项目全部资产，因此检查项目中所有非 public Profile。返回顺序优先
    遵循 Manifest 声明，确保页面、任务快照与日志稳定可比较。
    """

    catalog = catalog_module.build_catalog(_get_root(), project_id)
    run_type = str(selection.get("run_type") or "")
    required: set[str] = set()
    if run_type == "single":
        api_id = str(selection.get("api_id") or "")
        api = next(
            (item for item in catalog["apis"] if item.get("id") == api_id),
            None,
        )
        if api and api.get("credential_profile") not in {None, "public"}:
            required.add(str(api["credential_profile"]))
    elif run_type == "flow":
        flow_id = str(selection.get("flow_id") or "")
        flow = next(
            (item for item in catalog["flows"] if item.get("id") == flow_id),
            None,
        )
        if flow:
            required.update(
                str(item)
                for item in flow.get("credential_profiles", [])
                if item not in {None, "public"}
            )
    elif run_type == "all":
        required.update(
            str(item.get("credential_profile"))
            for item in catalog["apis"]
            if item.get("credential_profile") not in {None, "public"}
        )

    package = _get_registry().get(project_id)
    declared = list(package.manifest.config_contract.credential_profiles)
    return [profile_id for profile_id in declared if profile_id in required]


def _missing_project_config_keys(
    config: Mapping[str, Any],
    required_keys: tuple[str, ...],
) -> list[str]:
    """返回平台 Release 未提供的项目 Manifest 逻辑配置键。

    平台可返回新版 ``settings`` 或旧兼容形态 ``normal``。这里只读取普通配置，
    不展开 Secret；旧 ``GATEWAY_API_URL`` 仅用于平滑读取迁移前已冻结的历史
    Release，新建 Scope 的 Definition 已统一为 ``gateway.base_url``。
    """

    direct = config.get("settings")
    values = direct if isinstance(direct, dict) else config.get("normal")
    values = values if isinstance(values, dict) else {}
    missing: list[str] = []
    for logical_key in required_keys:
        if logical_key in values:
            value: Any = values[logical_key]
        elif logical_key == "gateway.base_url" and "GATEWAY_API_URL" in values:
            value = values["GATEWAY_API_URL"]
        else:
            value = values
            for token in logical_key.split("."):
                if not isinstance(value, dict) or token not in value:
                    value = None
                    break
                value = value[token]
        if value is None or value == "":
            missing.append(logical_key)
    return missing


def _preflight_response(
    payload: dict[str, Any],
    *,
    enforce_profiles: bool = True,
) -> dict[str, Any]:
    """生成概览、项目上下文和提交区共用的唯一预检状态模型。

    项目切换没有选中执行资产，因此只展示 Profile 总体状态而不作为切换门禁；
    概览“全部资产”、单接口和 Flow 预检均保持严格校验。
    """

    selection = _validate_selection_payload(payload)
    project_id = selection["project_id"]
    package = _get_registry().get(project_id)
    catalog = catalog_module.build_catalog(_get_root(), project_id)
    project = {
        "project_id": project_id,
        "display_name": package.display_name,
        "package_status": "valid" if not catalog["errors"] else "invalid",
    }
    provider = _get_preflight_provider()
    if provider is None:
        runtime = {
            "platform_environment": _get_settings().get("platform_environment", "dev"),
            "target_env": selection["target_env"],
            "scope_id": None,
            "scope_status": "missing",
            "config_source": "local",
            "release": None,
        }
        return {
            "ready": False,
            "project": project,
            "runtime": runtime,
            "profiles": [],
            "errors": [
                {
                    "code": "PLATFORM_CONFIG_REQUIRED",
                    "message": "Web 任务只能使用平台 Runtime Scope 与配置快照",
                    "scope_id": None,
                    "release_id": None,
                    "logical_keys": [],
                    "management_url": None,
                }
            ],
        }

    context, config = provider(
        project_id,
        request.headers.get("X-Platform-User-Context", ""),
    )
    context_scope = context.get("runtime_scope")
    context_scope = context_scope if isinstance(context_scope, dict) else {}
    scope_id = (
        context_scope.get("scope_id")
        or context.get("runtime_scope_id")
        or config.get("runtime_scope_id")
    )
    release_id = config.get("release_id")
    release = (
        {
            "id": release_id,
            "version": config.get("release_version"),
            "status": "active",
        }
        if release_id
        else None
    )
    profiles = _credential_profiles(
        config,
        _required_credential_profiles(project_id, selection),
    )
    errors: list[dict[str, Any]] = []
    management_url = config.get("management_url") or context_scope.get("management_url")
    if project["package_status"] != "valid":
        errors.append(
            {
                "code": "PROJECT_ASSET_INVALID",
                "message": "当前项目测试资产校验未通过",
                "scope_id": scope_id,
                "release_id": release_id,
                "logical_keys": [],
                "management_url": management_url,
            }
        )
    if not scope_id:
        errors.append(
            {
                "code": "RUNTIME_SCOPE_NOT_FOUND",
                "message": "当前项目未配置可用 Runtime Scope",
                "scope_id": None,
                "release_id": None,
                "logical_keys": [],
                "management_url": management_url,
            }
        )
    if not release_id:
        errors.append(
            {
                "code": "CONFIG_RELEASE_NOT_ACTIVE",
                "message": "当前 Scope 未发布可用 Release",
                "scope_id": scope_id,
                "release_id": None,
                "logical_keys": [],
                "management_url": management_url,
            }
        )
    missing_config_keys = _missing_project_config_keys(
        config,
        package.manifest.config_contract.required_keys,
    )
    if missing_config_keys:
        errors.append(
            {
                "code": "PROJECT_CONFIG_MISSING",
                "message": "当前 Release 缺少项目运行所需配置",
                "scope_id": scope_id,
                "release_id": release_id,
                "logical_keys": missing_config_keys,
                "management_url": management_url,
            }
        )
    missing_profiles = [
        profile
        for profile in profiles
        if str(profile.get("status") or "").lower()
        not in _READY_PROFILE_STATUSES
    ]
    if enforce_profiles and missing_profiles:
        errors.append(
            {
                "code": "PROJECT_CREDENTIAL_MISSING",
                "message": "当前资产所需凭证未就绪",
                "scope_id": scope_id,
                "release_id": release_id,
                "logical_keys": [str(item.get("id")) for item in missing_profiles],
                "management_url": management_url,
            }
        )
    platform_environment = (
        context_scope.get("platform_environment")
        or context.get("platform_environment")
        or config.get("platform_environment")
        or config.get("environment")
    )
    target_env = (
        context_scope.get("target_env")
        or context.get("target_env")
        or config.get("target_env")
    )
    runtime = {
        "platform_environment": platform_environment,
        "target_env": target_env,
        "scope_id": scope_id,
        "scope_status": context_scope.get("status") or "active",
        "config_source": "platform",
        "release": release,
        "management_url": management_url,
    }
    expected_target = {"dev": "test", "prod": "prod"}.get(str(platform_environment))
    if expected_target != target_env:
        errors.append(
            {
                "code": "RUNTIME_SCOPE_MISMATCH",
                "message": "平台环境与接口环境固定映射不匹配",
                "scope_id": scope_id,
                "release_id": release_id,
                "logical_keys": [],
                "management_url": management_url,
            }
        )
    return {
        "ready": not errors,
        "project": project,
        "runtime": runtime,
        "profiles": profiles,
        "errors": errors,
    }


def _normalize_task_record(record: dict[str, Any]) -> dict[str, Any]:
    """读取时把 V1 Truthy 历史任务映射为 V2 展示结构，不改写旧文件。"""

    if record.get("schema_version") == 2:
        return record
    legacy_input = record.get("input") if isinstance(record.get("input"), dict) else {}
    normalized = dict(record)
    normalized["schema_version"] = 1
    normalized.setdefault(
        "project",
        {
            "platform_project_id": None,
            "project_id": "truthy",
            "display_name": "Truthy（历史任务）",
        },
    )
    normalized.setdefault(
        "runtime",
        {
            "platform_environment": None,
            "target_env": legacy_input.get("env", "test"),
            "runtime_scope_id": None,
            "config_source": "legacy",
            "release_id": record.get("config_release_id"),
            "release_version": record.get("config_release_version"),
            "credential_profiles": [],
        },
    )
    normalized.setdefault(
        "selection",
        {
            "run_type": legacy_input.get("run_type"),
            "api_id": legacy_input.get("api_id"),
            "case_id": legacy_input.get("case_id"),
            "flow_id": legacy_input.get("flow") or legacy_input.get("flow_id"),
            "tag": legacy_input.get("tag"),
        },
    )
    normalized.setdefault("retry_of", None)
    return normalized


def _register_routes(blueprint: Blueprint) -> None:
    """把全部路由注册到壳服务 Blueprint。"""

    # ---------------- 页面 ----------------

    @blueprint.get("/")
    def index_page():
        """概览页：运行上下文、快捷入口、统计与最近任务。"""
        return render_template(
            "index.html",
            base_path=_get_settings()["base_path"],
            platform_home_url=_get_settings()["platform_home_url"],
            platform_environment=_get_settings().get("platform_environment", "dev"),
        )

    @blueprint.get("/projects")
    def projects_page():
        """项目切换页；仅展示授权 Scope 与有效项目包的交集。"""

        return render_template(
            "projects.html",
            base_path=_get_settings()["base_path"],
            platform_home_url=_get_settings()["platform_home_url"],
            platform_environment=_get_settings().get("platform_environment", "dev"),
        )

    @blueprint.get("/tasks/new/single")
    def new_single_task_page():
        """创建单接口任务页。"""

        return render_template(
            "task_form.html",
            base_path=_get_settings()["base_path"],
            platform_home_url=_get_settings()["platform_home_url"],
            platform_environment=_get_settings().get("platform_environment", "dev"),
            task_mode="single",
        )

    @blueprint.get("/tasks/new/flow")
    def new_flow_task_page():
        """创建 Flow 任务页。"""

        return render_template(
            "task_form.html",
            base_path=_get_settings()["base_path"],
            platform_home_url=_get_settings()["platform_home_url"],
            platform_environment=_get_settings().get("platform_environment", "dev"),
            task_mode="flow",
        )

    @blueprint.get("/tasks")
    def tasks_page():
        """任务记录页。"""

        return render_template(
            "tasks.html",
            base_path=_get_settings()["base_path"],
            platform_home_url=_get_settings()["platform_home_url"],
            platform_environment=_get_settings().get("platform_environment", "dev"),
        )

    @blueprint.get("/tasks/<task_id>")
    def task_detail_page(task_id: str):
        """任务详情页：参数、时间线、统计、失败清单与日志。"""
        _require_task(task_id)
        return render_template(
            "task_detail.html",
            base_path=_get_settings()["base_path"],
            platform_home_url=_get_settings()["platform_home_url"],
            platform_environment=_get_settings().get("platform_environment", "dev"),
            task_id=task_id,
        )

    @blueprint.get("/catalog")
    def catalog_page():
        """用例库页：API / Case / Flow 清单与解析错误。"""
        return render_template(
            "catalog.html",
            base_path=_get_settings()["base_path"],
            platform_home_url=_get_settings()["platform_home_url"],
            platform_environment=_get_settings().get("platform_environment", "dev"),
        )

    # ---------------- 任务接口 ----------------

    @blueprint.get("/api/projects")
    def projects_api():
        """返回授权 Scope 与本地项目包的可执行交集。"""

        items = _project_items()
        return jsonify({"items": items, "total": len(items)})

    @blueprint.get("/api/projects/<project_id>/context")
    def project_context_api(project_id: str):
        """返回项目只读运行上下文；不包含配置值或 Secret。"""

        items = {item["project_id"]: item for item in _project_items()}
        item = items.get(project_id)
        if item is None:
            abort(404, description=f"项目不可用: {project_id}")
        preflight = _preflight_response(
            {"project_id": project_id, "run_type": "all"},
            enforce_profiles=False,
        )
        return jsonify({**item, "preflight": preflight})

    @blueprint.post("/api/preflight")
    def preflight_api():
        """执行服务端资产 + Scope/Release/Profile 预检，不创建任务。"""

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise SubmissionError(400, "INVALID_PARAMS", "请求体必须是 JSON 对象")
        forbidden = sorted(FORBIDDEN_TASK_OVERRIDE_KEYS & set(payload))
        if forbidden:
            raise SubmissionError(
                400,
                "INVALID_PARAMS",
                f"不得覆盖平台运行字段: {', '.join(forbidden)}",
            )
        return jsonify(_preflight_response(payload))

    @blueprint.post("/api/tasks")
    def submit_task():
        """提交任务；校验失败 400，槽位占用 409。"""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise SubmissionError(400, "INVALID_PARAMS", "请求体必须是 JSON 对象")
        forbidden = sorted(FORBIDDEN_TASK_OVERRIDE_KEYS & set(payload))
        if forbidden:
            raise SubmissionError(
                400,
                "INVALID_PARAMS",
                f"不得覆盖平台运行字段: {', '.join(forbidden)}",
            )
        signed_context = request.headers.get("X-Platform-User-Context", "")
        if payload.get("project_id"):
            preflight = _preflight_response(payload)
            if not preflight["ready"]:
                first = preflight["errors"][0]
                raise SubmissionError(409, first["code"], first["message"])
            record = _get_manager().submit(
                project_id=str(payload.get("project_id") or ""),
                run_type=str(payload.get("run_type") or ""),
                api_id=payload.get("api_id"),
                case_id=payload.get("case_id"),
                flow_id=payload.get("flow_id"),
                tag=payload.get("tag"),
                signed_user_context=signed_context,
            )
        else:
            # 兼容旧调用方：env 只能映射 Truthy，不接受任何新运行覆盖字段。
            record = _get_manager().submit(
                env=str(payload.get("env") or ""),
                run_type=str(payload.get("run_type") or ""),
                flow=payload.get("flow"),
                tag=payload.get("tag"),
                signed_user_context=signed_context,
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
        records = [
            _normalize_task_record(item)
            for item in _visible_task_records(_get_manager().store.list(), decision)
        ]
        project_filter = request.args.get("project_id", "all").strip()
        status_filter = request.args.get("status", "").strip()
        run_type_filter = request.args.get("run_type", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()

        def matches(record: dict[str, Any]) -> bool:
            """应用 P0 列表筛选；非法日期由请求边界直接返回 400。"""

            if project_filter not in {"", "all"} and record["project"]["project_id"] != project_filter:
                return False
            if status_filter and record.get("status") != status_filter:
                return False
            if run_type_filter and record["selection"].get("run_type") != run_type_filter:
                return False
            created = str(record.get("created_at") or "")[:10]
            if date_from and created < date_from:
                return False
            if date_to and created > date_to:
                return False
            return True

        if date_from:
            try:
                datetime.fromisoformat(date_from)
            except ValueError:
                abort(400, description="date_from 必须为 ISO 日期")
        if date_to:
            try:
                datetime.fromisoformat(date_to)
            except ValueError:
                abort(400, description="date_to 必须为 ISO 日期")
        records = [record for record in records if matches(record)]
        total = len(records)
        start = (page - 1) * page_size
        items = records[start : start + page_size]
        return jsonify(
            {"items": items, "page": page, "page_size": page_size, "total": total}
        )

    @blueprint.get("/api/tasks/<task_id>")
    def task_detail_api(task_id: str):
        """任务详情：记录全量字段。"""
        return jsonify(_normalize_task_record(_require_task(task_id)))

    @blueprint.post("/api/tasks/<task_id>/cancel")
    def cancel_task(task_id: str):
        """取消任务；不存在 404，已终态 409。"""
        _require_task(task_id, "cancel")
        record = _get_manager().cancel(task_id)
        return jsonify({"id": record["id"], "status": record["status"]})

    @blueprint.post("/api/tasks/<task_id>/retry")
    def retry_task(task_id: str):
        """重试创建新任务，旧任务与旧快照保持不变。"""

        _require_task(task_id, "retry")
        record = _get_manager().retry(
            task_id,
            signed_user_context=request.headers.get("X-Platform-User-Context", ""),
        )
        return (
            jsonify(
                {
                    "id": record["id"],
                    "status": record["status"],
                    "retry_of": task_id,
                    "created_at": record["created_at"],
                }
            ),
            201,
        )

    @blueprint.get("/api/tasks/<task_id>/result")
    def task_result(task_id: str):
        """任务结果摘要：统计 + 全量用例 + 失败清单；无 JUnit 时给出原因码。"""
        record = _require_task(task_id)
        root = _get_root()
        parsed = parse_junit_file(root / record["junit_file"], root)
        if parsed is None:
            return jsonify(
                {
                    "status": record["status"],
                    "result_available": False,
                    "summary": None,
                    "cases": [],
                    "failed_cases": [],
                    "reason_code": "JUNIT_NOT_GENERATED",
                }
            )
        return jsonify(
            {
                "status": record["status"],
                "result_available": True,
                "summary": parsed["summary"],
                "cases": parsed["cases"],
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

        normalized = _normalize_task_record(record)
        project_id = normalized["project"]["project_id"]
        legacy_mode = bool(record.get("input", {}).get("legacy_mode")) or record.get(
            "schema_version"
        ) != 2
        console_path = _get_manager().store.console_log_path(
            task_id,
            None if legacy_mode else project_id,
        )
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
        project_id = request.args.get("project_id", "").strip() or None
        if project_id is not None and _get_scope_provider() is not None:
            allowed = {item["project_id"] for item in _project_items()}
            if project_id not in allowed:
                abort(404, description=f"项目不可用: {project_id}")
        snapshot = catalog_module.build_catalog(_get_root(), project_id)
        if project_id is None:
            # 兼容旧版无项目参数的只读调用方；新版页面始终显式传 project_id，
            # 因此仍可获得并核对项目归属字段，不会影响多项目隔离。
            snapshot.pop("project_id", None)
        query = request.args.get("query", "").strip().lower()
        selected_type = request.args.get("type", "").strip()
        if query and selected_type in {"apis", "cases", "flows"}:
            snapshot[selected_type] = [
                item
                for item in snapshot[selected_type]
                if query in json.dumps(item, ensure_ascii=False).lower()
            ]
        return jsonify(snapshot)

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
