from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LlmProfile(Base):
    """跨环境复用身份、由各环境 Release 提供参数的 LLM 配置。"""

    __tablename__ = "llm_profiles"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id", "name_normalized", name="uq_llm_profiles_owner_name"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    protocol: Mapped[str] = mapped_column(String(32), nullable=False, default="openai_compatible")
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ToolLlmBinding(Base):
    """登记工具内可读取 LLM 快照的稳定能力键。"""

    __tablename__ = "tool_llm_bindings"
    __table_args__ = (UniqueConstraint("tool_id", "capability_key", name="uq_tool_llm_binding_capability"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id", ondelete="CASCADE"), nullable=False)
    capability_key: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class UserLlmBinding(Base):
    """把稳定的工具 LLM 能力映射到某个用户的私有发布身份。"""

    __tablename__ = "user_llm_bindings"
    __table_args__ = (
        UniqueConstraint("user_id", "binding_id", name="uq_user_llm_binding_scope"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("tool_llm_bindings.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
