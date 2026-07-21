"""
缺陷域 API

功能说明:
    提供第二阶段缺陷、状态机、附件、评论和权限相关接口。

设计约束:
    - 业务写入统一通过 DefectService，路由层只做鉴权、参数适配和响应包装。
    - 项目/缺陷权限沿用 deps.py，避免在各接口重复散落权限判断。
    - AI 推荐与重新分析属于后续阶段，本阶段只保留兼容占位响应。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    RequireDefectPermission,
    RequireProjectPermission,
    get_current_user,
    is_platform_admin,
)
from app.config import settings
from app.infrastructure.database import get_db
from app.models.defect import Attachment, Defect
from app.models.project import Iteration, Project, ProjectMember
from app.models.user import User
from app.schemas.common import ApiResult, PaginatedResponse
from app.schemas.defect import (
    AssignDefectRequest,
    AssignDefectResponse,
    AttachmentDetail,
    BatchTransitionItem,
    BatchTransitionRequest,
    CommentCreate,
    CommentDetail,
    DefectConfirmCreateRequest,
    DefectCreate,
    DefectDetail,
    DefectDetailResponse,
    DefectDraftRequest,
    DefectDraftResponse,
    DefectListItem,
    DefectStatusChangeRequest,
    DefectUpdate,
    RejectDefectRequest,
    ReopenDefectRequest,
    ReopenDefectResponse,
    StatusChangeDetail,
    TransitionStatusRequest,
    VerifyDefectRequest,
    VerifyDefectResponse,
)
from app.services.defect_service import DefectService

router = APIRouter(tags=["defects"])


async def _visible_project_ids(db: AsyncSession, user: User) -> list[int] | None:
    """
    查询当前用户可见项目 ID。

    返回值:
        list[int] | None: 平台管理员返回 None 表示不限制；普通用户返回
        owner 项目和成员项目集合。
    """
    if is_platform_admin(user):
        return None

    owned = await db.scalars(select(Project.id).where(Project.owner_id == user.id))
    joined = await db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id))
    return sorted(set(owned.all()) | set(joined.all()))


async def _ensure_project_access(db: AsyncSession, user: User, project_id: int) -> None:
    """
    校验用户是否可访问指定项目。

    异常说明:
        HTTPException(403): 当前用户不是项目 Owner 或成员。
    """
    if is_platform_admin(user):
        return

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


async def _ensure_iteration_access(db: AsyncSession, user: User, iteration_id: int) -> int:
    """
    校验当前用户是否可访问迭代所属项目。

    返回值:
        int: 迭代所属项目 ID，供调用方继续做项目一致性校验。
    """
    project_id = await db.scalar(select(Iteration.project_id).where(Iteration.id == iteration_id))
    if project_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="迭代不存在")
    await _ensure_project_access(db, user, project_id)
    return project_id


async def _ensure_defect_access(db: AsyncSession, user: User, defect_id: int) -> None:
    """
    校验用户是否可访问指定缺陷。

    功能说明:
        缺陷本身不直接保存项目 ID，需要通过迭代回溯项目后复用项目权限。
    """
    project_id = await db.scalar(
        select(Iteration.project_id)
        .join(Defect, Defect.iteration_id == Iteration.id)
        .where(Defect.id == defect_id)
    )
    if project_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="缺陷不存在")
    await _ensure_project_access(db, user, project_id)


def _resolve_upload_path(filename: str) -> Path:
    """
    解析附件文件路径，并阻断目录穿越。

    异常说明:
        HTTPException(404): 路径不在上传根目录内，或文件不存在。
    """
    upload_root = Path(settings.server.upload_dir).resolve()
    file_path = (upload_root / filename).resolve()
    try:
        file_path.relative_to(upload_root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在") from exc
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")
    return file_path


@router.get("/defects", response_model=ApiResult[PaginatedResponse[DefectListItem]])
async def list_defects(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status_value: str | None = Query(default=None, alias="status"),
    severity: str | None = None,
    keyword: str | None = None,
    iteration_id: int | None = Query(default=None, alias="iterationId"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[PaginatedResponse[DefectListItem]]:
    """查询当前用户可见缺陷列表"""
    project_ids = await _visible_project_ids(db, current_user)
    items, total = await DefectService(db).list_defects(
        page=page,
        size=size,
        status_value=status_value,
        severity=severity,
        keyword=keyword,
        iteration_id=iteration_id,
        project_ids=project_ids,
    )
    return ApiResult.success(PaginatedResponse.from_items(items, total, page, size))


@router.post("/defects", response_model=ApiResult[DefectDetail])
async def create_defect(
    body: DefectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[DefectDetail]:
    """创建缺陷"""
    await _ensure_iteration_access(db, current_user, body.iterationId)
    defect = await DefectService(db).create_defect(body, current_user)
    return ApiResult.success(defect)


@router.get("/defects/{id}", response_model=ApiResult[DefectDetailResponse])
async def get_defect(
    id: int,
    _: bool = Depends(RequireDefectPermission("defects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[DefectDetailResponse]:
    """获取缺陷详情页聚合数据"""
    detail = await DefectService(db).get_defect_page(id)
    return ApiResult.success(detail)


@router.put("/defects/{id}", response_model=ApiResult[DefectDetail])
async def update_defect(
    id: int,
    body: DefectUpdate,
    _: bool = Depends(RequireDefectPermission("defects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[DefectDetail]:
    """更新缺陷基础信息"""
    defect = await DefectService(db).update_defect(id, body)
    return ApiResult.success(defect)


@router.put("/defects/{id}/assign", response_model=ApiResult[AssignDefectResponse])
async def assign_defect(
    id: int,
    body: AssignDefectRequest,
    _: bool = Depends(RequireDefectPermission("defects:assign", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AssignDefectResponse]:
    """分配缺陷处理人"""
    defect = await DefectService(db).assign_defect(id, body.assigneeId, current_user.id)
    return ApiResult.success(
        AssignDefectResponse(defect=defect, status=defect.status, agentAnalysisTriggered=False)
    )


@router.put("/defects/{id}/status", response_model=ApiResult[DefectDetail])
async def change_defect_status(
    id: int,
    body: DefectStatusChangeRequest,
    _: bool = Depends(RequireDefectPermission("defects:transition", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[DefectDetail]:
    """兼容旧前端的缺陷状态变更入口"""
    defect = await DefectService(db).transition_defect(id, body.status, current_user.id, body.comment)
    return ApiResult.success(defect)


@router.put("/defects/{id}/transition", response_model=ApiResult[DefectDetail])
async def transition_defect(
    id: int,
    body: TransitionStatusRequest,
    _: bool = Depends(RequireDefectPermission("defects:transition", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[DefectDetail]:
    """按状态机流转缺陷"""
    defect = await DefectService(db).transition_defect(id, body.status, current_user.id, body.comment)
    return ApiResult.success(defect)


@router.put("/defects/{id}/verify", response_model=ApiResult[VerifyDefectResponse])
async def verify_defect(
    id: int,
    body: VerifyDefectRequest,
    _: bool = Depends(RequireDefectPermission("defects:verify", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[VerifyDefectResponse]:
    """验证缺陷修复结果"""
    defect = await DefectService(db).verify_defect(id, body.passed, current_user.id, body.comment)
    return ApiResult.success(VerifyDefectResponse(defect=defect, status=defect.status))


@router.put("/defects/{id}/reject", response_model=ApiResult[dict])
async def reject_defect(
    id: int,
    body: RejectDefectRequest,
    _: bool = Depends(RequireDefectPermission("defects:transition", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[dict]:
    """驳回缺陷"""
    status_value = await DefectService(db).reject_defect(id, current_user.id, body.reason)
    return ApiResult.success({"status": status_value})


@router.post("/defects/{id}/reopen", response_model=ApiResult[ReopenDefectResponse])
async def reopen_defect(
    id: int,
    body: ReopenDefectRequest,
    _: bool = Depends(RequireDefectPermission("defects:transition", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[ReopenDefectResponse]:
    """重新打开缺陷"""
    defect = await DefectService(db).reopen_defect(id, body.targetStatus, current_user.id, body.comment)
    return ApiResult.success(ReopenDefectResponse(defect=defect, status=defect.status))


@router.post("/defects/{id}/reanalyze", response_model=ApiResult[dict])
async def reanalyze_defect(
    id: int,
    _: bool = Depends(RequireDefectPermission("defects:analyze", "id")),
) -> ApiResult[dict]:
    """重新分析缺陷占位入口，第三阶段接入真实 Agent 调度"""
    return ApiResult.success(
        {"defectId": id, "status": "pending_analysis", "message": "分析能力将在第三阶段实现"}
    )


@router.get("/defects/{id}/recommend-assignees", response_model=ApiResult[list[dict]])
async def recommend_assignees(
    id: int,
    _: bool = Depends(RequireDefectPermission("defects:read", "id")),
) -> ApiResult[list[dict]]:
    """推荐处理人占位入口，后续接入项目成员画像"""
    return ApiResult.success([])


@router.get("/defects/{id}/recommend-agents", response_model=ApiResult[list[dict]])
async def recommend_agents(
    id: int,
    _: bool = Depends(RequireDefectPermission("defects:read", "id")),
) -> ApiResult[list[dict]]:
    """推荐 Agent 占位入口，第三阶段接入 Agent 能力矩阵"""
    return ApiResult.success([])


@router.get("/defects/{id}/transitions", response_model=ApiResult[list[str]])
async def get_defect_transitions(
    id: int,
    _: bool = Depends(RequireDefectPermission("defects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[str]]:
    """获取缺陷当前可流转状态"""
    transitions = await DefectService(db).get_transitions(id)
    return ApiResult.success(transitions)


@router.get("/defects/{id}/history", response_model=ApiResult[list[StatusChangeDetail]])
async def get_defect_history(
    id: int,
    _: bool = Depends(RequireDefectPermission("defects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[StatusChangeDetail]]:
    """获取缺陷状态变更历史"""
    history = await DefectService(db).get_history(id)
    return ApiResult.success(history)


@router.post("/defects/{id}/comments", response_model=ApiResult[CommentDetail])
async def create_comment(
    id: int,
    body: CommentCreate,
    _: bool = Depends(RequireDefectPermission("defects:comment", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[CommentDetail]:
    """创建缺陷评论"""
    comment = await DefectService(db).create_comment(id, current_user, body.content)
    return ApiResult.success(comment)


@router.get("/defects/{id}/comments", response_model=ApiResult[list[CommentDetail]])
async def list_comments(
    id: int,
    _: bool = Depends(RequireDefectPermission("defects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[CommentDetail]]:
    """查询缺陷评论列表"""
    comments = await DefectService(db).list_comments(id)
    return ApiResult.success(comments)


@router.post("/defects/{id}/attachments", response_model=ApiResult[AttachmentDetail])
async def upload_attachment(
    id: int,
    file: UploadFile = File(...),
    _: bool = Depends(RequireDefectPermission("defects:attach", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AttachmentDetail]:
    """上传缺陷附件"""
    attachment = await DefectService(db).save_attachment(id, current_user, file)
    return ApiResult.success(attachment)


@router.get("/defects/{id}/attachments", response_model=ApiResult[list[AttachmentDetail]])
async def list_attachments(
    id: int,
    _: bool = Depends(RequireDefectPermission("defects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[AttachmentDetail]]:
    """查询缺陷附件列表"""
    attachments = await DefectService(db).list_attachments(id)
    return ApiResult.success(attachments)


@router.delete("/defects/{id}/attachments/{attachment_id}", response_model=ApiResult[None])
async def delete_attachment(
    id: int,
    attachment_id: int,
    _: bool = Depends(RequireDefectPermission("defects:attach", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[None]:
    """删除缺陷附件"""
    await DefectService(db).delete_attachment(id, attachment_id)
    return ApiResult.success(None)


@router.post("/projects/{id}/defects/draft-from-chat", response_model=ApiResult[DefectDraftResponse])
async def draft_defect_from_chat(
    id: int,
    body: DefectDraftRequest,
    _: bool = Depends(RequireProjectPermission("defects:create", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[DefectDraftResponse]:
    """根据项目内对话生成缺陷草稿"""
    if body.iterationId is not None:
        project_id = await db.scalar(select(Iteration.project_id).where(Iteration.id == body.iterationId))
        if project_id != id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="迭代不属于当前项目")
    draft = await DefectService(db).draft_from_chat(id, body)
    return ApiResult.success(draft)


@router.post("/projects/{id}/defects/confirm-create", response_model=ApiResult[DefectDetail])
async def confirm_create_defect(
    id: int,
    body: DefectConfirmCreateRequest,
    _: bool = Depends(RequireProjectPermission("defects:create", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[DefectDetail]:
    """确认缺陷草稿并创建正式缺陷"""
    project_id = await _ensure_iteration_access(db, current_user, body.iterationId)
    if project_id != id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="迭代不属于当前项目")
    defect = await DefectService(db).confirm_create_defect(body, current_user)
    return ApiResult.success(defect)


@router.post("/workflow/batch", response_model=ApiResult[list[BatchTransitionItem]])
async def batch_transition(
    body: BatchTransitionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[BatchTransitionItem]]:
    """批量流转缺陷状态，单个失败不影响其他项"""
    service = DefectService(db)
    results: list[BatchTransitionItem] = []
    for defect_id in body.defectIds:
        try:
            await _ensure_defect_access(db, current_user, defect_id)
            await service.transition_defect(defect_id, body.status, current_user.id, body.comment)
            results.append(BatchTransitionItem(defectId=defect_id, success=True))
        except HTTPException as exc:
            results.append(BatchTransitionItem(defectId=defect_id, success=False, message=str(exc.detail)))
    return ApiResult.success(results)


@router.get("/uploads/{filename:path}", response_class=FileResponse)
async def download_attachment(
    filename: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """
    下载缺陷附件。

    权限说明:
        通过附件记录回溯缺陷所属项目，只有平台管理员、项目 Owner 或项目成员可下载。
    """
    attachment = await db.scalar(select(Attachment).where(Attachment.file_path == filename))
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")
    await _ensure_defect_access(db, current_user, attachment.defect_id)
    return FileResponse(_resolve_upload_path(filename), filename=attachment.file_name)
