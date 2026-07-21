"""
Agent 分析服务

功能说明:
    串联缺陷状态机、确定性分析引擎、分析报告、Token 统计、SSE 事件和
    Agent 记忆提取，形成第三阶段最小可运行分析闭环。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.analysis_engine import DeterministicAnalysisEngine
from app.infrastructure.sse import sse_broker
from app.models.analysis_report import AnalysisReport, AnalysisTask, AITokenUsage
from app.models.defect import Defect
from app.models.project import Iteration
from app.models.user import User
from app.schemas.agent import (
    AnalysisReportDetail,
    AnalysisTaskDetail,
    AnalyzeRequest,
    AnalyzeResponse,
)
from app.services.memory_service import AgentMemoryService
from app.services.token_usage_service import TokenUsageService
from app.services.workflow_service import WorkflowService


class AnalysisService:
    """Agent 分析服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.engine = DeterministicAnalysisEngine()

    async def trigger_analysis(self, body: AnalyzeRequest, operator: User) -> AnalyzeResponse:
        """
        触发缺陷分析。

        参数说明:
            body: 分析请求，包含 defectId 和 agentTypes。
            operator: 当前操作用户。

        返回值:
            AnalyzeResponse: 任务 ID、报告 ID 和任务状态。
        """
        defect = await self._get_defect(body.defectId)
        iteration = await self._get_iteration(defect.iteration_id)
        agent_types = body.agentTypes or ["analysis_general"]

        if defect.status == "pending_analysis":
            await WorkflowService(self.db).transition(defect, "analyzing", operator.id, "触发 Agent 分析")
        elif defect.status != "analyzing":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="缺陷当前状态不能触发分析")

        task = AnalysisTask(
            defect_id=defect.id,
            agent_types=",".join(agent_types),
            status="running",
            started_at=datetime.now(),
        )
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)

        await sse_broker.publish(
            f"defect:{defect.id}",
            "analysis:started",
            {"defectId": defect.id, "taskId": task.id, "agentTypes": agent_types},
        )

        report_ids: list[int] = []
        try:
            memory_context = await AgentMemoryService(self.db).build_memory_context(
                iteration.project_id,
                iteration.id,
            )
            for index, agent_type in enumerate(agent_types, start=1):
                await sse_broker.publish(
                    f"defect:{defect.id}",
                    "analysis:progress",
                    {
                        "defectId": defect.id,
                        "agentType": agent_type,
                        "step": index,
                        "message": "正在生成结构化分析报告",
                    },
                )
                report_id = await self._create_report_and_usage(
                    defect=defect,
                    iteration=iteration,
                    agent_type=agent_type,
                    memory_context=memory_context,
                    operator_id=operator.id,
                )
                report_ids.append(report_id)

            task.status = "completed"
            task.completed_at = datetime.now()
            if defect.status == "analyzing":
                await WorkflowService(self.db).transition(defect, "pending_fix", operator.id, "Agent 分析完成")
            await sse_broker.publish(
                f"defect:{defect.id}",
                "analysis:completed",
                {"defectId": defect.id, "taskId": task.id, "reportIds": report_ids, "status": task.status},
            )
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            task.completed_at = datetime.now()
            if defect.status == "analyzing":
                await WorkflowService(self.db).transition(defect, "pending_analysis", operator.id, "Agent 分析失败")
            await sse_broker.publish(
                f"defect:{defect.id}",
                "analysis:failed",
                {"defectId": defect.id, "taskId": task.id, "error": str(exc), "status": task.status},
            )
            raise

        await self.db.flush()
        return AnalyzeResponse(task_id=task.id, defect_id=defect.id, status=task.status, report_ids=report_ids)

    async def cancel_analysis(self, task_id: int) -> AnalysisTaskDetail:
        """
        取消分析任务。

        说明:
            当前分析为同步执行，只有 running/queued 任务会被标记为 cancelled。
        """
        task = await self._get_task(task_id)
        if task.status in {"queued", "running"}:
            task.status = "cancelled"
            task.completed_at = datetime.now()
            await self.db.flush()
            await self.db.refresh(task)
            await sse_broker.publish(
                f"defect:{task.defect_id}",
                "analysis:cancelled",
                {"defectId": task.defect_id, "taskId": task.id, "status": task.status},
            )
        return self._to_task_detail(task)

    async def list_queue(self) -> list[AnalysisTaskDetail]:
        """查询分析队列和最近任务"""
        result = await self.db.execute(select(AnalysisTask).order_by(AnalysisTask.id.desc()).limit(50))
        return [self._to_task_detail(task) for task in result.scalars().all()]

    async def list_history(self, defect_id: int) -> list[AnalysisTaskDetail]:
        """查询缺陷分析历史"""
        result = await self.db.execute(
            select(AnalysisTask).where(AnalysisTask.defect_id == defect_id).order_by(AnalysisTask.id.desc())
        )
        return [self._to_task_detail(task) for task in result.scalars().all()]

    async def list_reports(self, defect_id: int) -> list[AnalysisReportDetail]:
        """查询缺陷分析报告列表"""
        result = await self.db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.defect_id == defect_id)
            .order_by(AnalysisReport.id.desc())
        )
        return [self._to_report_detail(report) for report in result.scalars().all()]

    async def get_report(self, report_id: int) -> AnalysisReportDetail:
        """获取单个分析报告"""
        report = await self.db.get(AnalysisReport, report_id)
        if report is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分析报告不存在")
        return self._to_report_detail(report)

    async def _create_report_and_usage(
        self,
        defect: Defect,
        iteration: Iteration,
        agent_type: str,
        memory_context: str,
        operator_id: int,
    ) -> int:
        """创建分析报告、Token 记录和自动记忆"""
        result = self.engine.analyze(defect.title, defect.description or "", agent_type, memory_context)
        report = AnalysisReport(
            defect_id=defect.id,
            agent_type=agent_type,
            analysis=result.analysis,
            solution=result.solution,
            provider="deterministic",
            model="rule-based-v1",
            status="completed",
            is_obsolete=False,
        )
        self.db.add(report)
        await self.db.flush()
        await self.db.refresh(report)

        usage = AITokenUsage(
            project_id=iteration.project_id,
            defect_id=defect.id,
            iteration_id=iteration.id,
            provider="deterministic",
            model="rule-based-v1",
            prompt_tokens=result.token_usage.prompt_tokens,
            completion_tokens=result.token_usage.completion_tokens,
            total_tokens=result.token_usage.total_tokens,
            estimated_cost_usd=TokenUsageService.estimate_cost(result.token_usage.total_tokens),
            is_fallback=False,
            duration_ms=0,
            source="analysis",
        )
        self.db.add(usage)
        await AgentMemoryService(self.db).extract_from_analysis(
            iteration.project_id,
            iteration.id,
            report.id,
            result.solution["description"],
            operator_id,
        )
        return report.id

    async def _get_defect(self, defect_id: int) -> Defect:
        """获取缺陷，不存在返回 404"""
        defect = await self.db.get(Defect, defect_id)
        if defect is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="缺陷不存在")
        return defect

    async def _get_iteration(self, iteration_id: int) -> Iteration:
        """获取迭代，不存在返回 404"""
        iteration = await self.db.get(Iteration, iteration_id)
        if iteration is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="迭代不存在")
        return iteration

    async def _get_task(self, task_id: int) -> AnalysisTask:
        """获取分析任务，不存在返回 404"""
        task = await self.db.get(AnalysisTask, task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分析任务不存在")
        return task

    @staticmethod
    def _to_report_detail(report: AnalysisReport) -> AnalysisReportDetail:
        """转换分析报告 DTO"""
        return AnalysisReportDetail(
            id=report.id,
            defect_id=report.defect_id,
            agent_type=report.agent_type,
            analysis=report.analysis,
            solution=report.solution,
            provider=report.provider,
            model=report.model,
            status=report.status,
            is_obsolete=report.is_obsolete,
            created_at=report.created_at,
        )

    @staticmethod
    def _to_task_detail(task: AnalysisTask) -> AnalysisTaskDetail:
        """转换分析任务 DTO"""
        return AnalysisTaskDetail(
            id=task.id,
            defect_id=task.defect_id,
            agentTypes=[item for item in task.agent_types.split(",") if item],
            status=task.status,
            error=task.error,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
        )
