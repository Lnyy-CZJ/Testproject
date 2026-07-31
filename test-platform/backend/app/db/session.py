from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """
    为单次请求提供数据库会话。

    返回值:
        Generator[Session, None, None]: 供 FastAPI 依赖注入使用的同步会话。
    异常说明:
        数据库操作异常继续向上抛出，由统一异常处理器转换为安全响应。
    """

    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()
