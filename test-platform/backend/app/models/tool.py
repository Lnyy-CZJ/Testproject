from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tool(Base):
    """描述由测试开发平台统一展示和探测的独立工具。"""

    __tablename__ = "tools"
    __table_args__ = (
        CheckConstraint("access_scope IN ('public', 'project')", name="ck_tools_access_scope"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    entry_url: Mapped[str] = mapped_column(String(512), nullable=False)
    health_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    short_code: Mapped[str] = mapped_column(String(32), nullable=False)
    icon_key: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    features: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 存量数据由迁移工具显式归入 legacy 项目，因此应用模型使用 project 作为保守默认值。
    access_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="project")
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    public_safety_policy_status: Mapped[str] = mapped_column(String(16), nullable=False, default="missing")
    # 公共开放不能只依赖一个可手工切换的状态字符串；结构化策略由授权内核
    # 逐项校验，并由实际执行/出口层消费对应配额和目标白名单。
    public_safety_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
