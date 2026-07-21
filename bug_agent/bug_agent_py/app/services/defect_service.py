"""
缺陷服务

功能说明:
    实现第二阶段缺陷 CRUD、列表筛选、附件、评论和工作流入口。

设计约束:
    - 状态流转统一委托 WorkflowService。
    - 附件文件保存到配置的 upload_dir 下，数据库只保存相对路径。
    - Service 层不直接返回裸 ORM，统一转换为 Pydantic DTO。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.analysis_report import AnalysisReport
from app.models.defect import Attachment, Comment, Defect
from app.models.fix_task import FixTask
from app.models.project import Iteration, Project
from app.models.user import User
from app.models.workflow import StatusChange
from app.schemas.auth import UserProfile
from app.schemas.defect import (
    AttachmentDetail,
    BatchTransitionItem,
    CommentDetail,
    DefectConfirmCreateRequest,
    DefectCreate,
    DefectDetail,
    DefectDetailResponse,
    DefectDraftRequest,
    DefectDraftResponse,
    DefectListItem,
    DefectUpdate,
    StatusChangeDetail,
)
from app.services.auth_service import user_to_profile
from app.services.workflow_service import WorkflowService


def _split_tags(tags: str | None) -> list[str]:
    """将逗号分隔标签转换为列表"""
    if not tags:
        return []
    return [item.strip() for item in tags.split(",") if item.strip()]


def _join_tags(tags: list[str] | None) -> str:
    """将标签列表转换为数据库存储字符串"""
    return ",".join(tags or [])


class DefectService:
    """缺陷服务，封装缺陷相关数据库操作"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_defects(
        self,
        page: int,
        size: int,
        status_value: str | None = None,
        severity: str | None = None,
        keyword: str | None = None,
        iteration_id: int | None = None,
        project_ids: list[int] | None = None,
    ) -> tuple[list[DefectListItem], int]:
        """
        查询缺陷列表。

        参数说明:
            page/size: 分页参数。
            status_value/severity/keyword/iteration_id: 前端筛选条件。
            project_ids: 非管理员用户可见项目范围；None 表示不过滤。
        """
        stmt = select(Defect)
        count_stmt = select(func.count()).select_from(Defect)
        conditions = []
        if project_ids is not None:
            if not project_ids:
                return [], 0
            stmt = stmt.join(Iteration, Iteration.id == Defect.iteration_id)
            count_stmt = count_stmt.join(Iteration, Iteration.id == Defect.iteration_id)
            conditions.append(Iteration.project_id.in_(project_ids))
        if status_value:
            conditions.append(Defect.status == status_value)
        if severity:
            conditions.append(Defect.severity == severity)
        if iteration_id:
            conditions.append(Defect.iteration_id == iteration_id)
        if keyword:
            conditions.append(or_(Defect.title.ilike(f"%{keyword}%"), Defect.code.ilike(f"%{keyword}%")))
        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        total = int(await self.db.scalar(count_stmt) or 0)
        result = await self.db.execute(
            stmt.order_by(Defect.id.desc()).offset((page - 1) * size).limit(size)
        )
        defects = result.scalars().all()
        return [await self._to_list_item(defect) for defect in defects], total

    async def create_defect(self, body: DefectCreate, reporter: User) -> DefectDetail:
        """创建缺陷，初始状态为 new"""
        iteration = await self._get_iteration(body.iterationId)
        code = await self._next_defect_code(iteration.project_id)
        defect = Defect(
            code=code,
            iteration_id=body.iterationId,
            title=body.title,
            description=body.description,
            severity=body.severity,
            priority=body.priority,
            type=body.type,
            status="new",
            reporter_id=reporter.id,
            tags=_join_tags(body.tags),
        )
        self.db.add(defect)
        await self.db.flush()
        await self.db.refresh(defect)
        return await self._to_detail(defect)

    async def draft_from_chat(self, project_id: int, body: DefectDraftRequest) -> DefectDraftResponse:
        """
        根据自然语言生成缺陷草稿。

        第一阶段/第二阶段不调用 LLM，使用规则化草稿保证前端流程可用。
        """
        title = body.message.strip().splitlines()[0][:80]
        return DefectDraftResponse(
            title=title or "待补充缺陷标题",
            descriptionMarkdown=body.message,
            severity="一般",
            priority="P2",
            type="功能缺陷",
            tags=body.tags,
            suggestedIterationId=body.iterationId,
            missingInformation=[],
            confidence=0.6,
        )

    async def confirm_create_defect(
        self,
        body: DefectConfirmCreateRequest,
        reporter: User,
    ) -> DefectDetail:
        """确认草稿并创建正式缺陷"""
        create_body = DefectCreate(
            iteration_id=body.iterationId,
            title=body.title,
            description=body.descriptionMarkdown,
            severity=body.severity,
            priority=body.priority,
            type=body.type,
            tags=body.tags,
        )
        return await self.create_defect(create_body, reporter)

    async def get_defect_page(self, defect_id: int) -> DefectDetailResponse:
        """获取缺陷详情页聚合数据"""
        defect = await self._get_defect(defect_id)
        return DefectDetailResponse(
            defect=await self._to_detail(defect),
            comments=await self.list_comments(defect_id),
            fixTasks=await self._list_fix_tasks(defect_id),
            reports=await self._list_reports(defect_id),
            attachments=await self.list_attachments(defect_id),
        )

    async def update_defect(self, defect_id: int, body: DefectUpdate) -> DefectDetail:
        """更新缺陷基础信息"""
        defect = await self._get_defect(defect_id)
        if body.title is not None:
            defect.title = body.title
        if body.description is not None:
            defect.description = body.description
        if body.severity is not None:
            defect.severity = body.severity
        if body.priority is not None:
            defect.priority = body.priority
        if body.type is not None:
            defect.type = body.type
        if body.tags is not None:
            defect.tags = _join_tags(body.tags)
        await self.db.flush()
        await self.db.refresh(defect)
        return await self._to_detail(defect)

    async def assign_defect(
        self,
        defect_id: int,
        assignee_id: int,
        operator_id: int,
    ) -> DefectDetail:
        """分配缺陷，并在合法时从 pending_assign 推进到 pending_analysis"""
        defect = await self._get_defect(defect_id)
        assignee = await self.db.get(User, assignee_id)
        if assignee is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="被分配用户不存在")
        defect.assignee_id = assignee_id
        if defect.status == "pending_assign":
            await WorkflowService(self.db).transition(defect, "pending_analysis", operator_id, "分配缺陷")
        else:
            await self.db.flush()
            await self.db.refresh(defect)
        return await self._to_detail(defect)

    async def transition_defect(
        self,
        defect_id: int,
        to_status: str,
        operator_id: int,
        comment: str | None = None,
    ) -> DefectDetail:
        """按状态机流转缺陷"""
        defect = await self._get_defect(defect_id)
        await WorkflowService(self.db).transition(defect, to_status, operator_id, comment)
        return await self._to_detail(defect)

    async def verify_defect(self, defect_id: int, passed: bool, operator_id: int, comment: str | None) -> DefectDetail:
        """验证缺陷，通过进入 fixed，不通过回到 pending_fix"""
        target = "fixed" if passed else "pending_fix"
        return await self.transition_defect(defect_id, target, operator_id, comment)

    async def reject_defect(self, defect_id: int, operator_id: int, reason: str) -> str:
        """驳回缺陷"""
        await self.transition_defect(defect_id, "rejected", operator_id, reason)
        return "rejected"

    async def reopen_defect(
        self,
        defect_id: int,
        target_status: str,
        operator_id: int,
        comment: str | None,
    ) -> DefectDetail:
        """重新打开缺陷"""
        return await self.transition_defect(defect_id, target_status, operator_id, comment)

    async def get_transitions(self, defect_id: int) -> list[str]:
        """获取缺陷当前可用状态流转"""
        defect = await self._get_defect(defect_id)
        return WorkflowService.valid_transitions(defect.status)

    async def get_history(self, defect_id: int) -> list[StatusChangeDetail]:
        """获取缺陷状态历史"""
        await self._get_defect(defect_id)
        result = await self.db.execute(
            select(StatusChange)
            .where(StatusChange.defect_id == defect_id)
            .order_by(StatusChange.id.asc())
        )
        return [
            StatusChangeDetail(
                id=item.id,
                defect_id=item.defect_id,
                from_status=item.from_status,
                to_status=item.to_status,
                operator_id=item.operator_id,
                comment=item.comment,
                created_at=item.created_at,
            )
            for item in result.scalars().all()
        ]

    async def batch_transition(
        self,
        defect_ids: list[int],
        to_status: str,
        operator_id: int,
        comment: str | None,
    ) -> list[BatchTransitionItem]:
        """批量状态流转，单条失败不影响其他缺陷"""
        results: list[BatchTransitionItem] = []
        for defect_id in defect_ids:
            try:
                await self.transition_defect(defect_id, to_status, operator_id, comment)
                results.append(BatchTransitionItem(defectId=defect_id, success=True))
            except HTTPException as exc:
                results.append(BatchTransitionItem(defectId=defect_id, success=False, message=str(exc.detail)))
        return results

    async def create_comment(self, defect_id: int, user: User, content: str) -> CommentDetail:
        """创建缺陷评论"""
        await self._get_defect(defect_id)
        comment = Comment(defect_id=defect_id, user_id=user.id, content=content, is_agent_message=False)
        self.db.add(comment)
        await self.db.flush()
        await self.db.refresh(comment)
        return await self._to_comment_detail(comment)

    async def list_comments(self, defect_id: int) -> list[CommentDetail]:
        """查询缺陷评论列表"""
        result = await self.db.execute(
            select(Comment).where(Comment.defect_id == defect_id).order_by(Comment.id.asc())
        )
        return [await self._to_comment_detail(comment) for comment in result.scalars().all()]

    async def save_attachment(self, defect_id: int, user: User, file: UploadFile) -> AttachmentDetail:
        """保存附件文件并写入附件记录"""
        await self._get_defect(defect_id)
        upload_root = Path(settings.server.upload_dir).resolve()
        target_dir = upload_root / "defects" / str(defect_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(file.filename or "attachment").name
        stored_name = f"{uuid4().hex}_{safe_name}"
        file_path = target_dir / stored_name
        content = await file.read()
        file_path.write_bytes(content)

        relative_path = str(file_path.relative_to(upload_root))
        attachment = Attachment(
            defect_id=defect_id,
            file_name=safe_name,
            file_path=relative_path,
            file_size=len(content),
            mime_type=file.content_type,
            uploaded_by=user.id,
        )
        self.db.add(attachment)
        await self.db.flush()
        await self.db.refresh(attachment)
        return self._to_attachment_detail(attachment)

    async def list_attachments(self, defect_id: int) -> list[AttachmentDetail]:
        """查询缺陷附件列表"""
        result = await self.db.execute(
            select(Attachment).where(Attachment.defect_id == defect_id).order_by(Attachment.id.asc())
        )
        return [self._to_attachment_detail(attachment) for attachment in result.scalars().all()]

    async def delete_attachment(self, defect_id: int, attachment_id: int) -> None:
        """删除附件记录和本地文件"""
        attachment = await self.db.get(Attachment, attachment_id)
        if attachment is None or attachment.defect_id != defect_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")
        file_path = Path(settings.server.upload_dir).resolve() / attachment.file_path
        if file_path.exists():
            file_path.unlink()
        await self.db.delete(attachment)

    async def _get_iteration(self, iteration_id: int) -> Iteration:
        """获取迭代，不存在返回 404"""
        iteration = await self.db.get(Iteration, iteration_id)
        if iteration is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="迭代不存在")
        return iteration

    async def _get_defect(self, defect_id: int) -> Defect:
        """获取缺陷，不存在返回 404"""
        defect = await self.db.get(Defect, defect_id)
        if defect is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="缺陷不存在")
        return defect

    async def _next_defect_code(self, project_id: int) -> str:
        """生成项目内递增缺陷编号"""
        project = await self.db.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        year_month = datetime.now().strftime("%Y%m")
        if project.defect_seq_year_month != year_month:
            project.defect_seq = 0
            project.defect_seq_year_month = year_month
        project.defect_seq += 1
        return f"BUG-{project_id}-{year_month}-{project.defect_seq:04d}"

    async def _to_list_item(self, defect: Defect) -> DefectListItem:
        """转换缺陷列表项"""
        assignee = await self.db.get(User, defect.assignee_id) if defect.assignee_id else None
        reporter = await self.db.get(User, defect.reporter_id)
        return DefectListItem(
            id=defect.id,
            code=defect.code,
            title=defect.title,
            severity=defect.severity,
            priority=defect.priority,
            type=defect.type,
            status=defect.status,
            assignee_id=defect.assignee_id,
            assigneeName=assignee.nickname or assignee.username if assignee else None,
            reporter_id=defect.reporter_id,
            reporterName=reporter.nickname or reporter.username if reporter else None,
            created_at=defect.created_at,
            updated_at=defect.updated_at,
            iteration_id=defect.iteration_id,
            tags=_split_tags(defect.tags),
        )

    async def _to_detail(self, defect: Defect) -> DefectDetail:
        """转换缺陷详情对象"""
        assignee = await self.db.get(User, defect.assignee_id) if defect.assignee_id else None
        reporter = await self.db.get(User, defect.reporter_id)
        return DefectDetail(
            id=defect.id,
            code=defect.code,
            iteration_id=defect.iteration_id,
            title=defect.title,
            description=defect.description,
            severity=defect.severity,
            priority=defect.priority,
            type=defect.type,
            status=defect.status,
            assignee_id=defect.assignee_id,
            assignee=user_to_profile(assignee) if assignee else None,
            reporter_id=defect.reporter_id,
            reporter=user_to_profile(reporter) if reporter else None,
            tags=_split_tags(defect.tags),
            created_at=defect.created_at,
            updated_at=defect.updated_at,
        )

    async def _to_comment_detail(self, comment: Comment) -> CommentDetail:
        """转换评论详情"""
        user = await self.db.get(User, comment.user_id)
        return CommentDetail(
            id=comment.id,
            defect_id=comment.defect_id,
            user_id=comment.user_id,
            content=comment.content,
            agent_type=comment.agent_type,
            is_agent_message=comment.is_agent_message,
            created_at=comment.created_at,
            user=user_to_profile(user) if user else None,
        )

    def _to_attachment_detail(self, attachment: Attachment) -> AttachmentDetail:
        """转换附件详情"""
        return AttachmentDetail(
            id=attachment.id,
            defect_id=attachment.defect_id,
            file_name=attachment.file_name,
            fileUrl=f"/api/v1/uploads/{attachment.file_path}",
            file_size=attachment.file_size,
            mime_type=attachment.mime_type,
            created_at=attachment.created_at,
        )

    async def _list_fix_tasks(self, defect_id: int) -> list[dict]:
        """查询修复任务占位数据，第四阶段会替换为完整 DTO"""
        result = await self.db.execute(select(FixTask).where(FixTask.defect_id == defect_id))
        return [{"id": item.id, "status": item.status, "defectId": item.defect_id} for item in result.scalars().all()]

    async def _list_reports(self, defect_id: int) -> list[dict]:
        """查询分析报告占位数据，第三阶段会替换为完整 DTO"""
        result = await self.db.execute(select(AnalysisReport).where(AnalysisReport.defect_id == defect_id))
        return [{"id": item.id, "status": item.status, "defectId": item.defect_id} for item in result.scalars().all()]
