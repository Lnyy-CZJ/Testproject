from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Project(Base):
    """项目是批量继承工具访问范围的稳定边界，code 创建后不可修改。"""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_projects_status"),
        Index("ix_projects_status_name", "status", "name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProjectMembership(Base):
    """保存用户在项目中的唯一关系；角色变化时必须同步校验关系类型。"""

    __tablename__ = "project_memberships"
    __table_args__ = (
        CheckConstraint("relation IN ('manager', 'member')", name="ck_project_memberships_relation"),
        Index("ix_project_memberships_user_relation", "user_id", "relation"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    relation: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserToolGrant(Base):
    """平台管理员签发的有期限单工具加权授权，不携带任何管理权限。"""

    __tablename__ = "user_tool_grants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'expired', 'revoked')", name="ck_user_tool_grants_status"),
        Index("ix_user_tool_grants_user_status_expires", "user_id", "status", "expires_at"),
        Index("ix_user_tool_grants_tool_status_expires", "tool_id", "status", "expires_at"),
        # 业务查询的“先查后插”无法保护不存在的行；部分唯一索引在数据库层
        # 保证同一用户和工具最多只有一条 active 授权。
        Index(
            "uq_user_tool_grants_active_user_tool",
            "user_id",
            "tool_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    granted_by_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_reason: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_by_user_id: Mapped[str | None] = mapped_column(String(64))
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    renewed_from_grant_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    idempotency_payload_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class BusinessResourceSnapshot(Base):
    """固化根业务资源创建时的所有者与项目范围，后续归属变化不得改写。"""

    __tablename__ = "business_resource_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "environment_id", "tool_id", "resource_type", "resource_id",
            name="uq_business_resources_env_tool_type_id",
        ),
        Index("ix_business_resources_owner_env_tool_created", "owner_user_id", "environment_id", "tool_id", "created_at"),
        Index("ix_business_resources_project_env_tool_created", "project_id_snapshot", "environment_id", "tool_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    root_resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    environment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    project_id_snapshot: Mapped[str | None] = mapped_column(String(64))
    authorization_source_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PublicToolUsage(Base):
    """公共工具按用户/工具/UTC 日期维护的事务内配额桶。"""

    __tablename__ = "public_tool_usage"

    usage_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True)
    request_window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ProjectAccessReadiness(Base):
    """Contract 迁移只能在完整 manifest/shadow apply 后读取的单行门禁。"""

    __tablename__ = "project_access_readiness"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    environment_id: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
