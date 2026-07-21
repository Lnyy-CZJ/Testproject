"""
缺陷、附件、评论模型

对应 PRD 数据模型:
    - defects: 缺陷表
    - attachments: 附件表
    - comments: 评论表
    - defect_repos: 缺陷仓库关联表
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Defect(Base):
    """
    缺陷表

    code 格式: BUG-{项目缩写}-{YYYYMM}-{序号}
    status 流转见 WorkflowService 状态机
    """
    __tablename__ = "defects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    iteration_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("iterations.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="一般")
    priority: Mapped[str] = mapped_column(String(10), default="P2")
    type: Mapped[str] = mapped_column(String(30), default="功能缺陷")
    status: Mapped[str] = mapped_column(String(20), default="new")
    assignee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    reporter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    tags: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    defect_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("defects.id"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    uploaded_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    defect_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("defects.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    agent_type: Mapped[str | None] = mapped_column(String(20))
    is_agent_message: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class DefectRepo(Base):
    __tablename__ = "defect_repos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    defect_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("defects.id"), nullable=False)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("project_repos.id"), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())