"""
修复任务与 PR 生命周期 API

功能说明:
    提供第四阶段自动修复任务、人工修复和 PR 生命周期管理入口。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireDefectPermission, get_current_user, is_platform_admin
from app.infrastructure.database import get_db
from app.models.defect import Defect
from app.models.fix_task import FixTask
from app.models.project import Iteration, Project, ProjectMember
from app.models.user import User
from app.schemas.common import ApiResult
from app.schemas.fix_task import (
    CreateFixTaskRequest,
    CreateFixTaskResponse,
    FixTaskDetail,
    FixTaskGroupDetail,
    ManualFixRequest,
    PRRejectionDetail,
    RejectPRRequest,
    UpdateFixTaskRequest,
    UpdatePRRequest,
)
from app.services.fix_task_service import FixTaskService

router = APIRouter(tags=["fix_tasks"])


async def _ensure_defect_access(db: AsyncSession, user: User, defect_id: int) -> None:
    """
    校验用户是否可访问缺陷所属项目。

    异常说明:
        HTTPException(403): 当前用户不是项目 Owner 或成员。
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


async def _ensure_task_access(db: AsyncSession, user: User, task_id: int) -> int:
    """
    校验用户是否可访问修复任务。

    返回值:
        int: 任务所属缺陷 ID。
    """
    defect_id = await db.scalar(select(FixTask.defect_id).where(FixTask.id == task_id))
    if defect_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="修复任务不存在")
    await _ensure_defect_access(db, user, defect_id)
    return defect_id


@router.post("/defects/{id}/fix-tasks", response_model=ApiResult[CreateFixTaskResponse])
async def create_fix_tasks(
    id: int,
    body: CreateFixTaskRequest,
    _: bool = Depends(RequireDefectPermission("fix_tasks:create", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[CreateFixTaskResponse]:
    """创建自动修复任务组和任务"""
    result = await FixTaskService(db).create_fix_tasks(id, body, current_user)
    return ApiResult.success(result)


@router.get("/defects/{id}/fix-task-groups", response_model=ApiResult[list[FixTaskGroupDetail]])
async def list_fix_task_groups(
    id: int,
    _: bool = Depends(RequireDefectPermission("defects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[FixTaskGroupDetail]]:
    """查询缺陷修复任务组"""
    groups = await FixTaskService(db).list_groups(id)
    return ApiResult.success(groups)


@router.get("/defects/{id}/fix-tasks", response_model=ApiResult[list[FixTaskDetail]])
async def list_fix_tasks(
    id: int,
    _: bool = Depends(RequireDefectPermission("defects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[FixTaskDetail]]:
    """查询缺陷修复任务"""
    tasks = await FixTaskService(db).list_tasks(id)
    return ApiResult.success(tasks)


@router.get("/fix-tasks/{task_id}", response_model=ApiResult[FixTaskDetail])
async def get_fix_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[FixTaskDetail]:
    """获取修复任务详情"""
    await _ensure_task_access(db, current_user, task_id)
    task = await FixTaskService(db).get_task(task_id)
    return ApiResult.success(task)


@router.put("/fix-tasks/{task_id}", response_model=ApiResult[FixTaskDetail])
async def update_fix_task(
    task_id: int,
    body: UpdateFixTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[FixTaskDetail]:
    """更新修复任务状态、结果或 PR 信息"""
    await _ensure_task_access(db, current_user, task_id)
    task = await FixTaskService(db).update_task(task_id, body)
    return ApiResult.success(task)


@router.post("/defects/{id}/manual-fix/start", response_model=ApiResult[FixTaskDetail])
async def start_manual_fix(
    id: int,
    body: ManualFixRequest,
    _: bool = Depends(RequireDefectPermission("fix_tasks:create", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[FixTaskDetail]:
    """开始人工修复"""
    task = await FixTaskService(db).start_manual_fix(id, body, current_user)
    return ApiResult.success(task)


@router.post("/defects/{id}/manual-fix/complete", response_model=ApiResult[FixTaskDetail])
async def complete_manual_fix(
    id: int,
    body: ManualFixRequest,
    _: bool = Depends(RequireDefectPermission("fix_tasks:update", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[FixTaskDetail]:
    """完成人工修复"""
    task = await FixTaskService(db).complete_manual_fix(id, body, current_user)
    return ApiResult.success(task)


@router.post("/defects/{id}/manual-fix/abandon", response_model=ApiResult[FixTaskDetail])
async def abandon_manual_fix(
    id: int,
    _: bool = Depends(RequireDefectPermission("fix_tasks:update", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[FixTaskDetail]:
    """放弃人工修复"""
    task = await FixTaskService(db).abandon_manual_fix(id, current_user)
    return ApiResult.success(task)


@router.patch("/defects/{id}/fix-tasks/{task_id}/pr", response_model=ApiResult[FixTaskDetail])
async def update_fix_task_pr(
    id: int,
    task_id: int,
    body: UpdatePRRequest,
    _: bool = Depends(RequireDefectPermission("fix_tasks:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[FixTaskDetail]:
    """更新修复任务 PR 信息"""
    task = await FixTaskService(db).update_pr(id, task_id, body)
    return ApiResult.success(task)


@router.get("/defects/{id}/fix-tasks/{task_id}/rejections", response_model=ApiResult[list[PRRejectionDetail]])
async def list_pr_rejections(
    id: int,
    task_id: int,
    _: bool = Depends(RequireDefectPermission("defects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[PRRejectionDetail]]:
    """查询 PR 拒绝记录"""
    rejections = await FixTaskService(db).list_rejections(id, task_id)
    return ApiResult.success(rejections)


@router.post("/defects/{id}/fix-tasks/{task_id}/reject", response_model=ApiResult[PRRejectionDetail])
async def reject_pr(
    id: int,
    task_id: int,
    body: RejectPRRequest,
    _: bool = Depends(RequireDefectPermission("fix_tasks:update", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[PRRejectionDetail]:
    """手动标记 PR 被拒绝"""
    rejection = await FixTaskService(db).reject_pr(id, task_id, body, current_user)
    return ApiResult.success(rejection)


@router.post("/defects/{id}/fix-tasks/{task_id}/merge", response_model=ApiResult[FixTaskDetail])
async def merge_pr(
    id: int,
    task_id: int,
    _: bool = Depends(RequireDefectPermission("fix_tasks:update", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[FixTaskDetail]:
    """手动标记 PR 已合并"""
    task = await FixTaskService(db).merge_pr(id, task_id, current_user)
    return ApiResult.success(task)
