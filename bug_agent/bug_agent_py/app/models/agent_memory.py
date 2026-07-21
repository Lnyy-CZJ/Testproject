"""
Agent 记忆模型

对应 PRD 数据模型:
    - agent_memories: Agent 记忆表
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Float, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentMemory(Base):
    """
    Agent 记忆表

    两级记忆架构:
        - iteration_id IS NULL: 项目级记忆（持久）
        - iteration_id IS NOT NULL: 迭代级记忆（随迭代归档）

    category:
        - architecture: 架构模式
        - convention: 编码规范
        - common_error: 常见错误模式
        - fix_strategy: 修复策略
        - avoid_strategy: 避免策略

    source:
        - auto_extract: AI 自动提取
        - manual: 人工录入
        - pr_rejection: PR 拒绝反馈
    """
    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id"), nullable=False, index=True)
    iteration_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("iterations.id"), index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref_id: Mapped[int | None] = mapped_column(BigInteger)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())