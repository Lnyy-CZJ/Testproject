from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.health import ServiceHealthResponse


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=ServiceHealthResponse)
def live() -> ServiceHealthResponse:
    """
    返回平台进程存活状态。

    返回值:
        ServiceHealthResponse: 固定的进程存活响应，不访问数据库。
    """

    return ServiceHealthResponse(status="ok", version=get_settings().read_platform_version())


@router.get("/ready", response_model=ServiceHealthResponse)
def ready(database: Session = Depends(get_db)) -> ServiceHealthResponse:
    """
    检查平台数据库是否可访问。

    参数说明:
        database (Session): 当前请求的同步数据库会话。
    返回值:
        ServiceHealthResponse: 数据库可用时返回 ready。
    异常说明:
        数据库不可用时抛出 503，由统一处理器生成含 request_id 的错误响应。
    """

    try:
        database.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="平台数据库暂时不可用") from exc
    return ServiceHealthResponse(status="ready", version=get_settings().read_platform_version())
