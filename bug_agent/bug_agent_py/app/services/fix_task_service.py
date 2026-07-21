"""
修复任务与 PR 生命周期服务

功能说明:
    实现第四阶段修复任务创建、人工修复、PR 状态更新、拒绝记录和合并推进。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.sse import sse_broker
from app.models.defect import Defect
from app.models.fix_task import FixTask, FixTaskGroup, PRRejection
from app.models.project import Iteration
from app.models.user import User
from app.schemas.agent import AgentMemoryCreate
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
from app.services.memory_service import AgentMemoryService
from app.services.workflow_service import WorkflowService


class FixTaskService:
    """修复任务服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_fix_tasks(
        self,
        defect_id: int,
        body: CreateFixTaskRequest,
        operator: User,
    ) -> CreateFixTaskResponse:
        """
        创建自动修复任务组和任务。

        参数说明:
            defect_id: 缺陷 ID。
            body: 任务创建请求。
            operator: 当前操作人。
        """
        defect = await self._get_defect(defect_id)
        if defect.status == "pending_fix":
            await WorkflowService(self.db).transition(defect, "fixing", operator.id, "创建自动修复任务")
        elif defect.status != "fixing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="缺陷当前状态不能创建修复任务",
            )

        group = FixTaskGroup(
            defect_id=defect_id,
            target_branch=body.targetBranch,
            summary=body.summary,
            status="running",
        )
        self.db.add(group)
        await self.db.flush()
        await self.db.refresh(group)

        repo_ids = body.repoIds or [None]
        agent_types = body.agentTypes or ["fix_general"]
        tasks: list[FixTask] = []
        for repo_id in repo_ids:
            for agent_type in agent_types:
                task = FixTask(
                    fix_task_group_id=group.id,
                    defect_id=defect_id,
                    repo_id=repo_id,
                    agent_type=agent_type,
                    source="auto",
                    status="pending",
                    plan={"summary": body.summary, "targetBranch": body.targetBranch},
                    pr_status="open",
                )
                self.db.add(task)
                tasks.append(task)
        await self.db.flush()
        for task in tasks:
            await self.db.refresh(task)

        await sse_broker.publish(
            f"defect:{defect_id}",
            "fix_task:created",
            {"defectId": defect_id, "groupId": group.id, "taskIds": [task.id for task in tasks]},
        )
        return CreateFixTaskResponse(
            group=self._to_group_detail(group),
            tasks=[self._to_task_detail(task) for task in tasks],
        )

    async def list_groups(self, defect_id: int) -> list[FixTaskGroupDetail]:
        """查询缺陷修复任务组"""
        result = await self.db.execute(
            select(FixTaskGroup).where(FixTaskGroup.defect_id == defect_id).order_by(FixTaskGroup.id.desc())
        )
        return [self._to_group_detail(group) for group in result.scalars().all()]

    async def list_tasks(self, defect_id: int) -> list[FixTaskDetail]:
        """查询缺陷修复任务"""
        result = await self.db.execute(
            select(FixTask).where(FixTask.defect_id == defect_id).order_by(FixTask.id.desc())
        )
        return [self._to_task_detail(task) for task in result.scalars().all()]

    async def get_task(self, task_id: int) -> FixTaskDetail:
        """获取修复任务详情"""
        task = await self._get_task(task_id)
        return self._to_task_detail(task)

    async def update_task(self, task_id: int, body: UpdateFixTaskRequest) -> FixTaskDetail:
        """更新修复任务状态、结果或 PR 信息"""
        task = await self._get_task(task_id)
        if body.status is not None:
            task.status = body.status
            if body.status in {"completed", "failed", "cancelled"}:
                task.completed_at = datetime.now()
        if body.result is not None:
            task.result = body.result
        if body.prUrl is not None:
            task.pr_url = body.prUrl
        if body.prStatus is not None:
            task.pr_status = body.prStatus
        await self.db.flush()
        await self.db.refresh(task)
        return self._to_task_detail(task)

    async def start_manual_fix(
        self,
        defect_id: int,
        body: ManualFixRequest,
        operator: User,
    ) -> FixTaskDetail:
        """开始人工修复，并推进缺陷到 manual_fixing"""
        defect = await self._get_defect(defect_id)
        if defect.status == "pending_fix":
            await WorkflowService(self.db).transition(defect, "manual_fixing", operator.id, "开始人工修复")
        elif defect.status != "manual_fixing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="缺陷当前状态不能开始人工修复",
            )

        task = FixTask(
            defect_id=defect_id,
            repo_id=body.repoId,
            source="manual",
            status="running",
            pr_url=body.prUrl,
            pr_status="open" if body.prUrl else None,
            manual_description=body.description,
        )
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)
        await sse_broker.publish(
            f"defect:{defect_id}",
            "fix_task:progress",
            {"defectId": defect_id, "taskId": task.id, "step": "manual_fixing", "message": "人工修复已开始"},
        )
        return self._to_task_detail(task)

    async def complete_manual_fix(self, defect_id: int, body: ManualFixRequest, operator: User) -> FixTaskDetail:
        """完成人工修复，并推进缺陷到 pending_verify"""
        task = await self._latest_manual_task(defect_id)
        if body.prUrl is not None:
            task.pr_url = body.prUrl
            task.pr_status = "open"
        if body.description is not None:
            task.result = {"description": body.description}
        task.status = "completed"
        task.completed_at = datetime.now()
        defect = await self._get_defect(defect_id)
        await WorkflowService(self.db).transition(defect, "pending_verify", operator.id, "人工修复完成")
        await self.db.flush()
        await self.db.refresh(task)
        await sse_broker.publish(
            f"defect:{defect_id}",
            "fix_task:completed",
            {"defectId": defect_id, "taskId": task.id, "prUrl": task.pr_url, "status": task.status},
        )
        return self._to_task_detail(task)

    async def abandon_manual_fix(self, defect_id: int, operator: User) -> FixTaskDetail:
        """放弃人工修复，并回退缺陷到 pending_fix"""
        task = await self._latest_manual_task(defect_id)
        task.status = "cancelled"
        task.completed_at = datetime.now()
        defect = await self._get_defect(defect_id)
        await WorkflowService(self.db).transition(defect, "pending_fix", operator.id, "放弃人工修复")
        await self.db.flush()
        await self.db.refresh(task)
        return self._to_task_detail(task)

    async def update_pr(self, defect_id: int, task_id: int, body: UpdatePRRequest) -> FixTaskDetail:
        """更新修复任务 PR URL 和状态"""
        task = await self._get_task_for_defect(defect_id, task_id)
        task.pr_url = body.prUrl
        task.pr_status = body.prStatus
        await self.db.flush()
        await self.db.refresh(task)
        return self._to_task_detail(task)

    async def reject_pr(self, defect_id: int, task_id: int, body: RejectPRRequest, operator: User) -> PRRejectionDetail:
        """标记 PR 被拒绝，缺陷回退 pending_fix，并沉淀避免策略记忆"""
        task = await self._get_task_for_defect(defect_id, task_id)
        task.pr_status = "rejected"
        task.status = "failed"
        task.completed_at = datetime.now()
        rejection = PRRejection(
            fix_task_id=task.id,
            pr_number=body.prNumber,
            pr_url=task.pr_url,
            rejected_by=body.rejectedBy,
            reject_reason=body.rejectReason,
            vcs_provider=body.vcsProvider,
        )
        self.db.add(rejection)

        defect = await self._get_defect(defect_id)
        if defect.status != "pending_fix":
            await WorkflowService(self.db).transition(
                defect,
                "pending_fix",
                operator.id,
                f"PR 被拒绝，原因：{body.rejectReason}",
            )
        iteration = await self.db.get(Iteration, defect.iteration_id)
        if iteration is not None:
            await AgentMemoryService(self.db).create_memory(
                iteration.project_id,
                iteration.id,
                AgentMemoryCreate(
                    category="avoid_strategy",
                    content=f"避免重复提交被拒绝的 PR：{body.rejectReason}",
                    source="pr_rejection",
                    relevance_score=0.9,
                    enabled=True,
                ),
                operator.id,
                task.id,
            )
        await self.db.flush()
        await self.db.refresh(rejection)
        await sse_broker.publish(
            f"defect:{defect_id}",
            "fix_task:failed",
            {"defectId": defect_id, "taskId": task.id, "prStatus": task.pr_status},
        )
        return self._to_rejection_detail(rejection)

    async def merge_pr(self, defect_id: int, task_id: int, operator: User) -> FixTaskDetail:
        """标记 PR 已合并，并推进缺陷到 fixed"""
        task = await self._get_task_for_defect(defect_id, task_id)
        task.pr_status = "merged"
        task.status = "completed"
        task.completed_at = datetime.now()
        defect = await self._get_defect(defect_id)
        if defect.status != "fixed":
            await WorkflowService(self.db).transition(defect, "fixed", operator.id, "PR 已合并")
        await self.db.flush()
        await self.db.refresh(task)
        await sse_broker.publish(
            f"defect:{defect_id}",
            "fix_task:completed",
            {"defectId": defect_id, "taskId": task.id, "prUrl": task.pr_url, "status": task.status},
        )
        return self._to_task_detail(task)

    async def list_rejections(self, defect_id: int, task_id: int) -> list[PRRejectionDetail]:
        """查询 PR 拒绝记录"""
        await self._get_task_for_defect(defect_id, task_id)
        result = await self.db.execute(
            select(PRRejection).where(PRRejection.fix_task_id == task_id).order_by(PRRejection.id.desc())
        )
        return [self._to_rejection_detail(item) for item in result.scalars().all()]

    async def _get_defect(self, defect_id: int) -> Defect:
        """获取缺陷，不存在返回 404"""
        defect = await self.db.get(Defect, defect_id)
        if defect is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="缺陷不存在")
        return defect

    async def _get_task(self, task_id: int) -> FixTask:
        """获取修复任务，不存在返回 404"""
        task = await self.db.get(FixTask, task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="修复任务不存在")
        return task

    async def _get_task_for_defect(self, defect_id: int, task_id: int) -> FixTask:
        """获取指定缺陷下的修复任务"""
        task = await self._get_task(task_id)
        if task.defect_id != defect_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="修复任务不存在")
        return task

    async def _latest_manual_task(self, defect_id: int) -> FixTask:
        """获取缺陷最近一条人工修复任务"""
        result = await self.db.execute(
            select(FixTask)
            .where(FixTask.defect_id == defect_id, FixTask.source == "manual")
            .order_by(FixTask.id.desc())
            .limit(1)
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="人工修复任务不存在")
        return task

    @staticmethod
    def _to_group_detail(group: FixTaskGroup) -> FixTaskGroupDetail:
        """转换修复任务组 DTO"""
        return FixTaskGroupDetail(
            id=group.id,
            defect_id=group.defect_id,
            target_branch=group.target_branch,
            summary=group.summary,
            ai_provider=group.ai_provider,
            ai_model=group.ai_model,
            status=group.status,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )

    @staticmethod
    def _to_task_detail(task: FixTask) -> FixTaskDetail:
        """转换修复任务 DTO"""
        return FixTaskDetail(
            id=task.id,
            fix_task_group_id=task.fix_task_group_id,
            defect_id=task.defect_id,
            repo_id=task.repo_id,
            agent_type=task.agent_type,
            source=task.source,
            status=task.status,
            plan=task.plan,
            result=task.result,
            pr_url=task.pr_url,
            pr_status=task.pr_status,
            manual_description=task.manual_description,
            created_at=task.created_at,
            completed_at=task.completed_at,
        )

    @staticmethod
    def _to_rejection_detail(rejection: PRRejection) -> PRRejectionDetail:
        """转换 PR 拒绝记录 DTO"""
        return PRRejectionDetail(
            id=rejection.id,
            fix_task_id=rejection.fix_task_id,
            pr_number=rejection.pr_number,
            pr_url=rejection.pr_url,
            rejected_by=rejection.rejected_by,
            reject_reason=rejection.reject_reason,
            vcs_provider=rejection.vcs_provider,
            created_at=rejection.created_at,
        )
