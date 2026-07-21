"""
SQLAlchemy 异步数据库引擎与会话工厂

替代 Go 版 database.Init()，使用 SQLAlchemy 2.0 异步模式。
提供 AsyncEngine 和 async_session 工厂函数。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# 异步引擎（全局单例）
engine = create_async_engine(
    settings.database.url,
    pool_size=settings.database.max_open_conns,
    max_overflow=10,
    pool_pre_ping=True,
    echo=settings.server.mode == "debug",
)

# 异步会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """
    FastAPI Depends 依赖注入：获取数据库会话

    使用方式:
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise