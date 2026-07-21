"""
Agent 分析 API

功能说明:
    提供第三阶段缺陷分析触发、流式分析、报告查询、任务取消和历史查询接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireDefectPermission, get_current_user, is_platform_admin
from app.infrastructure.database import get_db
from app.infrastructure.sse import format_sse_event
from app.models.analysis_report import AnalysisTask
from app.models.defect import Defect
from app.models.project import Iteration, Project, ProjectMember
from app.models.user import User
from app.schemas.agent import AnalysisReportDetail, AnalysisTaskDetail, AnalyzeRequest, AnalyzeResponse
from app.schemas.common import ApiResult
from app.services.analysis_service import AnalysisService

router = APIRouter(tags=["agents"])


async def _ensure_defect_access(db: AsyncSession, user: User, defect_id: int) -> None:
    """
    校验用户是否可访问指定缺陷。

    异常说明:
        HTTPException(403): 当前用户不是缺陷所属项目成员。
        HTTPException(404): 缺陷不存在。
    """
    if is_platform_admin(user):
        return

    project_id = await db.scalar(
        select(Iteration.project_id)
        .join(Defect, Defect.iteration_id == Iteration.id)
        .where(Defect.id == defect_id)
    )
    if project_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="缺陷不存在")

    owned = await db.scalar(select(Project.id).where(Project.id == project_id, Project.owner_id == user.id))
    if owned is not None:
        return

    member_id = await db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )
    if member_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")


@router.post("/agents/analyze", response_model=ApiResult[AnalyzeResponse])
async def trigger_analysis(
    body: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AnalyzeResponse]:
    """触发缺陷 Agent 分析"""
    await _ensure_defect_access(db, current_user, body.defectId)
    result = await AnalysisService(db).trigger_analysis(body, current_user)
    return ApiResult.success(result)


@router.post("/agents/analyze/stream", response_class=StreamingResponse)
async def trigger_analysis_stream(
    body: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    触发缺陷分析并返回 text/event-stream。

    说明:
        当前分析同步完成，因此返回 started/completed 两类兼容事件。
        后续接入异步 Agent 后可改为实时 yield 进度。
    """
    await _ensure_defect_access(db, current_user, body.defectId)
    result = await AnalysisService(db).trigger_analysis(body, current_user)

    async def event_stream():
        """输出本次分析结果事件"""
        yield format_sse_event(
            "analysis:completed",
            {
                "defectId": result.defectId,
                "taskId": result.taskId,
                "reportIds": result.reportIds,
                "status": result.status,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/agents/reports/{report_id}", response_model=ApiResult[AnalysisReportDetail])
async def get_report(
    report_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AnalysisReportDetail]:
    """获取分析报告详情"""
    report = await AnalysisService(db).get_report(report_id)
    await _ensure_defect_access(db, current_user, report.defectId)
    return ApiResult.success(report)


@router.post("/agents/analyze/{id}/cancel", response_model=ApiResult[AnalysisTaskDetail])
async def cancel_analysis(
    id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AnalysisTaskDetail]:
    """取消分析任务"""
    task = await db.get(AnalysisTask, id)
    if task is not None:
        await _ensure_defect_access(db, current_user, task.defect_id)
    task = await AnalysisService(db).cancel_analysis(id)
    return ApiResult.success(task)


@router.get("/agents/analyze/queue", response_model=ApiResult[list[AnalysisTaskDetail]])
async def list_analysis_queue(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[AnalysisTaskDetail]]:
    """查询分析队列"""
    tasks = await AnalysisService(db).list_queue()
    return ApiResult.success(tasks)


@router.get("/agents/analyze/{id}/history", response_model=ApiResult[list[AnalysisTaskDetail]])
async def list_analysis_history(
    id: int,
    _: bool = Depends(RequireDefectPermission("agents:analyze", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[AnalysisTaskDetail]]:
    """查询缺陷分析历史"""
    tasks = await AnalysisService(db).list_history(id)
    return ApiResult.success(tasks)


@router.get("/defects/{id}/reports", response_model=ApiResult[list[AnalysisReportDetail]])
async def list_defect_reports(
    id: int,
    _: bool = Depends(RequireDefectPermission("agents:read_report", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[AnalysisReportDetail]]:
    """查询缺陷分析报告"""
    reports = await AnalysisService(db).list_reports(id)
    return ApiResult.success(reports)
