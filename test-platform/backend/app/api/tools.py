from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, current_auth_context
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.db.session import get_db
from app.models.access import Project
from app.models.tool import Tool
from app.schemas.tool import ToolHealthResponse, ToolListResponse, ToolResponse
from app.services.tool_health import probe_tool_health
from app.services.authorization import decide_tool_access_batch, has_tool_permission


router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=ToolListResponse)
def list_tools(
    context: AuthContext = Depends(current_auth_context),
    database: Session = Depends(get_db),
) -> ToolListResponse:
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
    tools = list(database.scalars(statement).all())
    decisions = (
        decide_tool_access_batch(database, context.user, tools)
        if context.user.platform_role
        else {}
    )
    project_ids = {tool.project_id for tool in tools if tool.project_id}
    projects = {
        project.id: project
        for project in database.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    } if project_ids else {}
    rows: list[ToolResponse] = []
    for tool in tools:
        decision = decisions.get(tool.id) if context.user.platform_role else None
        if decision is not None and not decision.allowed:
            continue
        if decision is None and not has_tool_permission(database, context.user.id, "tool.view", tool.id):
            continue
        project = projects.get(tool.project_id or "")
        rows.append(
            ToolResponse.model_validate(tool).model_copy(
                update={
                    "project_name": project.name if project else None,
                    "access_source": decision.source if decision else "legacy_rbac",
                    "can_manage": decision.can_manage if decision else False,
                }
            )
        )
    return ToolListResponse(items=rows)


@router.get("/{tool_id}/health", response_model=ToolHealthResponse)
def tool_health(
    tool_id: str,
    context: AuthContext = Depends(current_auth_context),
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
        raise PlatformError(404, "NOT_FOUND", "工具不存在")
    if not has_tool_permission(database, context.user.id, "tool.view", tool_id):
        raise PlatformError(404, "NOT_FOUND", "工具不存在")

    health = probe_tool_health(tool.health_url, settings.tool_health_timeout_seconds)
    return ToolHealthResponse(
        tool_id=tool.id,
        status="healthy" if health["healthy"] else "unhealthy",
        checked_at=datetime.now(UTC),
        version=health.get("version"),
        revision=health.get("revision"),
        dirty=health.get("dirty"),
        runtime_environment=health.get("runtime_environment"),
    )
