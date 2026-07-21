"""
Agent 记忆服务

功能说明:
    管理项目级和迭代级 Agent 记忆，并为分析/修复流程构建可注入上下文。
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_memory import AgentMemory
from app.schemas.agent import AgentMemoryCreate, AgentMemoryDetail, AgentMemoryUpdate


class AgentMemoryService:
    """Agent 记忆服务，封装记忆 CRUD 与上下文构建"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_memories(
        self,
        project_id: int,
        iteration_id: int | None = None,
        category: str | None = None,
    ) -> list[AgentMemoryDetail]:
        """
        查询项目或迭代记忆。

        参数说明:
            project_id: 项目 ID。
            iteration_id: 迭代 ID；为空时只查询项目级记忆。
            category: 可选记忆分类筛选。
        """
        conditions = [AgentMemory.project_id == project_id]
        if iteration_id is None:
            conditions.append(AgentMemory.iteration_id.is_(None))
        else:
            conditions.append(AgentMemory.iteration_id == iteration_id)
        if category:
            conditions.append(AgentMemory.category == category)

        result = await self.db.execute(
            select(AgentMemory)
            .where(and_(*conditions))
            .order_by(AgentMemory.relevance_score.desc(), AgentMemory.id.desc())
        )
        return [self._to_detail(memory) for memory in result.scalars().all()]

    async def create_memory(
        self,
        project_id: int,
        iteration_id: int | None,
        body: AgentMemoryCreate,
        created_by: int,
        source_ref_id: int | None = None,
    ) -> AgentMemoryDetail:
        """创建 Agent 记忆"""
        memory = AgentMemory(
            project_id=project_id,
            iteration_id=iteration_id,
            category=body.category,
            content=body.content,
            source=body.source,
            source_ref_id=source_ref_id,
            relevance_score=body.relevanceScore,
            enabled=body.enabled,
            created_by=created_by,
        )
        self.db.add(memory)
        await self.db.flush()
        await self.db.refresh(memory)
        return self._to_detail(memory)

    async def update_memory(
        self,
        memory_id: int,
        body: AgentMemoryUpdate,
    ) -> AgentMemoryDetail:
        """更新 Agent 记忆"""
        memory = await self._get_memory(memory_id)
        if body.category is not None:
            memory.category = body.category
        if body.content is not None:
            memory.content = body.content
        if body.relevanceScore is not None:
            memory.relevance_score = body.relevanceScore
        if body.enabled is not None:
            memory.enabled = body.enabled
        await self.db.flush()
        await self.db.refresh(memory)
        return self._to_detail(memory)

    async def delete_memory(self, memory_id: int) -> None:
        """删除 Agent 记忆"""
        memory = await self._get_memory(memory_id)
        await self.db.delete(memory)

    async def toggle_memory(self, memory_id: int) -> AgentMemoryDetail:
        """切换 Agent 记忆启用状态"""
        memory = await self._get_memory(memory_id)
        memory.enabled = not memory.enabled
        await self.db.flush()
        await self.db.refresh(memory)
        return self._to_detail(memory)

    async def build_memory_context(self, project_id: int, iteration_id: int | None) -> str:
        """
        构建分析可注入的记忆上下文。

        返回值:
            str: 每行一条记忆，按相关度排序。
        """
        conditions = [
            AgentMemory.project_id == project_id,
            AgentMemory.enabled.is_(True),
        ]
        if iteration_id is None:
            conditions.append(AgentMemory.iteration_id.is_(None))
        else:
            conditions.append(
                (AgentMemory.iteration_id.is_(None)) | (AgentMemory.iteration_id == iteration_id)
            )
        result = await self.db.execute(
            select(AgentMemory)
            .where(and_(*conditions))
            .order_by(AgentMemory.relevance_score.desc(), AgentMemory.id.desc())
            .limit(10)
        )
        memories = result.scalars().all()
        return "\n".join(f"{item.category}: {item.content}" for item in memories)

    async def extract_from_analysis(
        self,
        project_id: int,
        iteration_id: int | None,
        report_id: int,
        content: str,
        created_by: int,
    ) -> AgentMemoryDetail:
        """
        从分析结果中沉淀一条规则化记忆。

        设计说明:
            第三阶段不调用 LLM 做记忆抽取，先把分析结论作为 fix_strategy
            记忆落库，后续可替换为更智能的去重/抽取流程。
        """
        body = AgentMemoryCreate(
            category="fix_strategy",
            content=content[:1000],
            source="auto_extract",
            relevance_score=0.6,
            enabled=True,
        )
        return await self.create_memory(project_id, iteration_id, body, created_by, report_id)

    async def _get_memory(self, memory_id: int) -> AgentMemory:
        """获取记忆，不存在返回 404"""
        memory = await self.db.get(AgentMemory, memory_id)
        if memory is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="记忆不存在")
        return memory

    @staticmethod
    def _to_detail(memory: AgentMemory) -> AgentMemoryDetail:
        """转换记忆 DTO"""
        return AgentMemoryDetail(
            id=memory.id,
            project_id=memory.project_id,
            iteration_id=memory.iteration_id,
            category=memory.category,
            content=memory.content,
            source=memory.source,
            source_ref_id=memory.source_ref_id,
            relevance_score=memory.relevance_score,
            enabled=memory.enabled,
            created_by=memory.created_by,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )
