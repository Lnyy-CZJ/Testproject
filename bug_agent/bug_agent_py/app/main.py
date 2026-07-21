"""
FastAPI 应用工厂入口

替代 Go 版 main.go，负责:
1. 创建 FastAPI 应用实例
2. 注册生命周期事件（启动/关闭时初始化/清理资源）
3. 挂载全部 API 路由
4. 配置 CORS 中间件
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理

    启动时验证数据库和 Redis 连接可用性。
    关闭时清理连接池和客户端。
    """
    from app.infrastructure.database import engine
    from app.infrastructure.redis import redis_client

    # 验证数据库连接
    async with engine.begin() as conn:
        await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    # 验证 Redis 连接
    await redis_client.ping()

    yield

    await engine.dispose()
    await redis_client.close()


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例

    配置 CORS 白名单与 Go 版一致，确保前端无需修改即可对接。
    """
    app = FastAPI(
        title="BugAgent API",
        version="0.1.0",
        description="AI-powered defect management platform (Python重构版)",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """
        统一 HTTP 异常响应。

        功能说明:
            FastAPI 默认返回 {"detail": "..."}，前端请求封装期望 Go 版
            兼容格式 {"code": 状态码, "data": null, "message": "..."}。
        """
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.status_code, "data": None, "message": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """
        统一参数校验错误响应。

        返回值:
            JSONResponse: code=422 的 ApiResult 风格错误。
        """
        return JSONResponse(
            status_code=422,
            content={"code": 422, "data": None, "message": "请求参数错误"},
        )

    # CORS 中间件（与 Go 版一致的白名单）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000", "http://127.0.0.1:3000",
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:5678", "http://127.0.0.1:5678",
            "http://localhost:5679", "http://127.0.0.1:5679",
            "http://localhost:5680", "http://127.0.0.1:5680",
            "http://localhost:5688", "http://127.0.0.1:5688",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Origin", "Content-Type", "Authorization"],
        expose_headers=["Content-Length"],
    )

    # 健康检查端点
    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        """存活检查，无需数据库连接"""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> dict[str, str]:
        """就绪检查，验证数据库和 Redis 可用"""
        from app.infrastructure.redis import redis_client
        from app.infrastructure.database import engine

        async with engine.begin() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        await redis_client.ping()
        return {"status": "ready"}

    # 注册 API 路由
    from app.api.v1.router import api_router
    app.include_router(api_router)

    return app


# 应用实例
app = create_app()
