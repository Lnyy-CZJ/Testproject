"""
修复任务模型

对应 PRD 数据模型:
    - fix_tasks: 修复任务表
    - fix_task_groups: 修复任务组表
    - pr_rejections: PR 拒绝记录表
"""

from __future__ import annotations

from sqlalchemy import BigInteger, String, Text, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FixTaskGroup(Base):
    """
    修复任务组表

    当缺陷涉及多个仓库时，聚合多个 FixTask 统一管理。
    """
    __tablename__ = "fix_task_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    defect_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("defects.id"), nullable=False)
    target_branch: Mapped[str | None] = mapped_column(String(100))
    summary: Mapped[str | None] = mapped_column(Text)
    ai_provider: Mapped[str | None] = mapped_column(String(50))
    ai_model: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FixTask(Base):
    """
    修复任务表

    source: auto(自动修复) / manual(人工修复)
    pr_status: open / merged / closed / rejected
    """
    __tablename__ = "fix_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fix_task_group_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fix_task_groups.id"))
    defect_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("defects.id"), nullable=False)
    repo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("project_repos.id"))
    agent_type: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20), default="auto")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    plan: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    pr_url: Mapped[str | None] = mapped_column(String(500))
    pr_status: Mapped[str | None] = mapped_column(String(20), default="open")
    manual_description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime)


class PRRejection(Base):
    """
    PR 拒绝记录表

    记录每次 PR 被拒绝的详细信息，沉淀为 Agent 记忆。
    """
    __tablename__ = "pr_rejections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fix_task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fix_tasks.id"), nullable=False)
    pr_number: Mapped[str | None] = mapped_column(String(50))
    pr_url: Mapped[str | None] = mapped_column(String(500))
    rejected_by: Mapped[str | None] = mapped_column(String(100))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    vcs_provider: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())