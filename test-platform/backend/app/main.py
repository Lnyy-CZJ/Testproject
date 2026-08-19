import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api import admin, audit, auth, configuration, health, internal, llm, system, tools
from app.core.config import get_settings
from app.core.errors import PlatformError


settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


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


app = FastAPI(title="测试开发平台 API", version=settings.read_platform_version())
app.add_middleware(RequestIdMiddleware)
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(configuration.router, prefix="/api/v1")
app.include_router(llm.router, prefix="/api/v1")
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
