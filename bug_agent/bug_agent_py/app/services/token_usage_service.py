"""
Token 用量统计服务

功能说明:
    汇总和查询 AI 调用产生的 Token、费用和耗时记录。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_report import AITokenUsage
from app.schemas.agent import TokenUsageDetail, TokenUsageSummary


class TokenUsageService:
    """Token 用量服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def summarize(
        self,
        project_id: int | None = None,
        iteration_id: int | None = None,
        defect_id: int | None = None,
    ) -> TokenUsageSummary:
        """
        汇总 Token 用量。

        参数说明:
            project_id/iteration_id/defect_id: 可组合的统计维度。
        """
        stmt = select(
            func.coalesce(func.sum(AITokenUsage.prompt_tokens), 0),
            func.coalesce(func.sum(AITokenUsage.completion_tokens), 0),
            func.coalesce(func.sum(AITokenUsage.total_tokens), 0),
            func.coalesce(func.sum(AITokenUsage.estimated_cost_usd), 0),
            func.count(AITokenUsage.id),
        ).select_from(AITokenUsage)
        stmt = self._apply_filters(stmt, project_id, iteration_id, defect_id)
        row = (await self.db.execute(stmt)).one()
        return TokenUsageSummary(
            promptTokens=int(row[0] or 0),
            completionTokens=int(row[1] or 0),
            totalTokens=int(row[2] or 0),
            estimatedCostUsd=float(row[3] or 0),
            count=int(row[4] or 0),
        )

    async def list_details(
        self,
        project_id: int | None = None,
        iteration_id: int | None = None,
        defect_id: int | None = None,
    ) -> list[TokenUsageDetail]:
        """查询 Token 用量明细"""
        stmt = select(AITokenUsage).order_by(AITokenUsage.id.desc())
        stmt = self._apply_filters(stmt, project_id, iteration_id, defect_id)
        result = await self.db.execute(stmt)
        return [self._to_detail(item) for item in result.scalars().all()]

    async def group_by_iteration(self, project_id: int) -> list[dict]:
        """按迭代聚合项目 Token 用量"""
        result = await self.db.execute(
            select(
                AITokenUsage.iteration_id,
                func.coalesce(func.sum(AITokenUsage.total_tokens), 0),
                func.coalesce(func.sum(AITokenUsage.estimated_cost_usd), 0),
            )
            .where(AITokenUsage.project_id == project_id)
            .group_by(AITokenUsage.iteration_id)
            .order_by(AITokenUsage.iteration_id)
        )
        return [
            {
                "iterationId": row[0],
                "totalTokens": int(row[1] or 0),
                "estimatedCostUsd": float(row[2] or 0),
            }
            for row in result.all()
        ]

    async def group_by_defect(self, project_id: int) -> list[dict]:
        """按缺陷聚合项目 Token 用量"""
        result = await self.db.execute(
            select(
                AITokenUsage.defect_id,
                func.coalesce(func.sum(AITokenUsage.total_tokens), 0),
                func.coalesce(func.sum(AITokenUsage.estimated_cost_usd), 0),
            )
            .where(AITokenUsage.project_id == project_id)
            .group_by(AITokenUsage.defect_id)
            .order_by(AITokenUsage.defect_id)
        )
        return [
            {
                "defectId": row[0],
                "totalTokens": int(row[1] or 0),
                "estimatedCostUsd": float(row[2] or 0),
            }
            for row in result.all()
        ]

    @staticmethod
    def estimate_cost(total_tokens: int) -> Decimal:
        """
        估算成本。

        返回值:
            Decimal: 使用固定单价的美元估算值，后续可按模型定价替换。
        """
        return Decimal(total_tokens) * Decimal("0.000001")

    @staticmethod
    def _apply_filters(stmt, project_id: int | None, iteration_id: int | None, defect_id: int | None):
        """给查询追加维度过滤条件"""
        if project_id is not None:
            stmt = stmt.where(AITokenUsage.project_id == project_id)
        if iteration_id is not None:
            stmt = stmt.where(AITokenUsage.iteration_id == iteration_id)
        if defect_id is not None:
            stmt = stmt.where(AITokenUsage.defect_id == defect_id)
        return stmt

    @staticmethod
    def _to_detail(item: AITokenUsage) -> TokenUsageDetail:
        """转换 Token 明细 DTO"""
        return TokenUsageDetail(
            id=item.id,
            project_id=item.project_id,
            iteration_id=item.iteration_id,
            defect_id=item.defect_id,
            provider=item.provider,
            model=item.model,
            prompt_tokens=item.prompt_tokens,
            completion_tokens=item.completion_tokens,
            total_tokens=item.total_tokens,
            estimated_cost_usd=float(item.estimated_cost_usd or 0),
            is_fallback=item.is_fallback,
            duration_ms=item.duration_ms,
            source=item.source,
            created_at=item.created_at,
        )
