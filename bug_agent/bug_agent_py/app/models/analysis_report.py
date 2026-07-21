"""
分析报告、Token 用量、分析任务模型

对应 PRD 数据模型:
    - analysis_reports: 分析报告表
    - ai_token_usage: Token 用量表
    - analysis_tasks: 分析任务表
    - rollout_records: Agent 会话记录表
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, DateTime, ForeignKey, JSON, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AnalysisReport(Base):
    """
    分析报告表

    analysis: {rootCause, affectedFiles, riskLevel}
    solution: {description, steps}
    is_obsolete: 重新分析后标记旧报告为失效
    """
    __tablename__ = "analysis_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    defect_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("defects.id"), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False)
    analysis: Mapped[dict | None] = mapped_column(JSON)
    solution: Mapped[dict | None] = mapped_column(JSON)
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="completed")
    is_obsolete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class AITokenUsage(Base):
    """
    Token 用量表

    记录每次 AI 调用的 Token 消耗和费用估算。
    支持项目/迭代/缺陷三级维度聚合查询。
    """
    __tablename__ = "ai_token_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    defect_id: Mapped[int | None] = mapped_column(BigInteger)
    iteration_id: Mapped[int | None] = mapped_column(BigInteger)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), default="analysis")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class AnalysisTask(Base):
    """
    分析任务表

    记录分析任务的调度状态和结果。
    """
    __tablename__ = "analysis_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    defect_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("defects.id"), nullable=False)
    agent_types: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[DateTime | None] = mapped_column(DateTime)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class RolloutRecord(Base):
    """
    Agent 会话记录表

    持久化 Agent 对话历史和事件，支持中断恢复和审计追溯。
    """
    __tablename__ = "rollout_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False)
    defect_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    events: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="running")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())