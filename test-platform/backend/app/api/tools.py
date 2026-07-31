from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.tool import Tool
from app.schemas.tool import ToolHealthResponse, ToolListResponse
from app.services.tool_health import probe_tool_health


router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=ToolListResponse)
def list_tools(database: Session = Depends(get_db)) -> ToolListResponse:
    """
    获取已启用的工具目录。

    参数说明:
        database (Session): 当前请求的同步数据库会话。
    返回值:
        ToolListResponse: 按 sort_order、name 升序排列的工具列表。
    """

    statement = (
        select(Tool)
        .where(Tool.is_enabled.is_(True))
        .order_by(Tool.sort_order.asc(), Tool.name.asc())
    )
    return ToolListResponse(items=list(database.scalars(statement).all()))


@router.get("/{tool_id}/health", response_model=ToolHealthResponse)
def tool_health(
    tool_id: str,
    database: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ToolHealthResponse:
    """
    从平台后端探测指定工具的健康状态。

    参数说明:
        tool_id (str): 工具目录中的稳定主键。
        database (Session): 当前请求的同步数据库会话。
        settings (Settings): 包含健康探测超时的运行配置。
    返回值:
        ToolHealthResponse: 健康或不健康状态，上游失败仍返回正常响应。
    异常说明:
        工具不存在或被禁用时抛出 404，内部地址和上游异常不会返回前端。
    """

    tool = database.get(Tool, tool_id)
    if tool is None or not tool.is_enabled:
        raise HTTPException(status_code=404, detail="工具不存在")

    is_healthy = probe_tool_health(tool.health_url, settings.tool_health_timeout_seconds)
    return ToolHealthResponse(
        tool_id=tool.id,
        status="healthy" if is_healthy else "unhealthy",
        checked_at=datetime.now(UTC),
    )
