"""
工作流状态变更模型

对应 PRD 数据模型:
    - status_changes: 缺陷状态变更历史表
"""

from __future__ import annotations

from sqlalchemy import BigInteger, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StatusChange(Base):
    """
    状态变更历史表

    记录缺陷每次状态流转的详细信息。
    乐观锁: 使用 WHERE status = ? 条件防止并发冲突。
    """
    __tablename__ = "status_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    defect_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("defects.id"), nullable=False)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    operator_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())