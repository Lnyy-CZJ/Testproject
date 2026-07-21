"""
AI 目录与协作模型

对应 PRD 数据模型:
    - ai_provider_catalog: AI 厂商目录表
    - ai_model_catalog: AI 模型目录表
    - collaboration_tasks: 多 Agent 协作任务表
    - collaboration_reports: 协作汇总报告表
"""

from __future__ import annotations

from sqlalchemy import BigInteger, String, Text, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AIProviderCatalog(Base):
    """AI 厂商目录表"""
    __tablename__ = "ai_provider_catalog"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    provider_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    default_endpoint: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class AIModelCatalog(Base):
    """AI 模型目录表"""
    __tablename__ = "ai_model_catalog"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider_key: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    supports_fc: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class CollaborationTask(Base):
    __tablename__ = "collaboration_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    defect_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("defects.id"), nullable=False)
    agent_types: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CollaborationReport(Base):
    __tablename__ = "collaboration_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("collaboration_tasks.id"), nullable=False)
    report_id: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class RetrieverPlugin(Base):
    """检索器插件配置表"""
    __tablename__ = "retriever_plugins"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    plugin_type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())