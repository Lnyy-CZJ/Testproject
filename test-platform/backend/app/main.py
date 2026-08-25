import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api import access_admin, admin, audit, auth, configuration, health, internal, llm, projects, system, tools
from app.core.config import get_settings
from app.core.errors import PlatformError
from app.core.security import load_user_context_signing_key


settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


_SENSITIVE_ACCESS_QUERY_KEYS = frozenset({
    "access_token",
    "api_key",
    "auth_token",
    "password",
    "refresh_token",
    "runtime_context_id",
    "session_token",
    "token",
})


def _redact_access_log_target(value: str) -> str:
    """只脱敏访问日志中的敏感查询参数，保留路径与非敏感诊断字段。"""

    parsed = urlsplit(value)
    if not parsed.query:
        return value
    changed = False
    redacted_pairs: list[tuple[str, str]] = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.casefold() in _SENSITIVE_ACCESS_QUERY_KEYS:
            item_value = "[REDACTED]"
            changed = True
        redacted_pairs.append((key, item_value))
    if not changed:
        return value
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(redacted_pairs, doseq=True),
        parsed.fragment,
    ))


class SensitiveAccessLogFilter(logging.Filter):
    """在 Uvicorn 格式化前清除 URL 中的运行上下文和凭证类参数。

    Uvicorn 把请求目标作为 ``LogRecord.args`` 的一个字符串元素传给访问日志
    Formatter。这里同时处理 tuple、dict 与已预格式化消息，避免不同 Uvicorn
    版本或测试日志配置绕过脱敏。过滤器不记录被替换值，也不修改业务请求。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """原地脱敏日志参数并始终允许该条安全日志继续输出。"""

        if isinstance(record.msg, str):
            record.msg = _redact_access_log_target(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                _redact_access_log_target(value) if isinstance(value, str) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: (
                    _redact_access_log_target(value)
                    if isinstance(value, str)
                    else value
                )
                for key, value in record.args.items()
            }
        return True


# Uvicorn 在导入 ASGI 应用前已经完成日志器配置，因此模块加载时安装过滤器
# 即可覆盖容器启动与测试环境，无需改写全局日志格式或关闭其余访问诊断。
logging.getLogger("uvicorn.access").addFilter(SensitiveAccessLogFilter())


class RequestIdMiddleware(BaseHTTPMiddleware):
    """为每个请求生成或沿用安全的请求标识，并写入响应头。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        注入当前请求的 request_id。

        参数说明:
            request (Request): 当前 HTTP 请求。
            call_next: Starlette 下游处理函数。
        返回值:
            Response: 包含 X-Request-ID 响应头的下游响应。
        异常说明:
            下游未处理异常继续抛出，由 FastAPI 统一异常处理器接管。
        """

        incoming_id = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            incoming_id if incoming_id.startswith("req_") else f"req_{uuid.uuid4().hex}"
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response


def error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    """
    构造统一且不泄露内部细节的错误响应。

    参数说明:
        request (Request): 当前请求，用于读取 request_id。
        status_code (int): HTTP 状态码。
        code (str): 供调用方稳定判断的错误码。
        message (str): 可直接展示的中文错误信息。
    返回值:
        JSONResponse: 包含 code、message、request_id 的 JSON 响应。
    """

    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex}")
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


def validate_runtime_security_configuration() -> None:
    """个人配置功能启用时，在接收流量前验证独立签名密钥与 TTL。"""

    current = get_settings()
    if not (
        current.personal_credentials_write_enabled
        or current.personal_credentials_enabled
    ):
        return
    if not 1 <= current.user_context_ttl_seconds <= 300:
        raise RuntimeError("用户上下文 TTL 配置无效")
    if not 1 <= current.runtime_context_ttl_seconds <= 86400:
        raise RuntimeError("Runtime Context TTL 配置无效")
    try:
        load_user_context_signing_key(current.user_context_signing_key_file)
    except (OSError, ValueError):
        # 启动日志只指出安全配置不可用，不输出密钥路径、权限或文件内容。
        raise RuntimeError("用户上下文签名安全配置不可用") from None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时执行安全门禁，关闭阶段当前没有额外资源需要释放。"""

    validate_runtime_security_configuration()
    yield


app = FastAPI(
    title="测试开发平台 API",
    version=settings.read_platform_version(),
    lifespan=lifespan,
)
app.add_middleware(RequestIdMiddleware)
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(access_admin.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(configuration.router, prefix="/api/v1")
app.include_router(llm.router, prefix="/api/v1")
app.include_router(llm.personal_router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(internal.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")


@app.exception_handler(PlatformError)
async def platform_exception_handler(request: Request, exc: PlatformError) -> JSONResponse:
    """将稳定业务错误码转换为统一响应，不暴露内部异常。"""

    return error_response(request, exc.status_code, exc.code, exc.message)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """将业务 HTTP 异常转换为统一错误结构。"""

    code_by_status = {404: "NOT_FOUND", 503: "SERVICE_UNAVAILABLE"}
    message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
    if exc.status_code == 404 and message == "Not Found":
        message = "请求的资源不存在"
    return error_response(
        request,
        exc.status_code,
        code_by_status.get(exc.status_code, "HTTP_ERROR"),
        message,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """隐藏具体校验栈，仅向调用方返回稳定的参数错误信息。"""

    return error_response(request, 422, "VALIDATION_ERROR", "请求参数不正确")


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """记录数据库异常并返回不包含内部连接信息的服务错误。"""

    logger.exception("数据库请求执行失败", exc_info=exc)
    return error_response(request, 503, "DATABASE_UNAVAILABLE", "平台数据库暂时不可用")


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """记录未知异常并返回通用错误，防止内部实现细节泄露。"""

    logger.exception("未处理的平台请求异常", exc_info=exc)
    return error_response(request, 500, "INTERNAL_ERROR", "平台服务内部错误")
