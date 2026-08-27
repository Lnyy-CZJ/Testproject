from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """保存平台本地用户及其安全状态。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    username_normalized: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    permission_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 迁移窗口内允许为空；0019 回填并完成预检后由 0020 收紧为非空。
    platform_role: Mapped[str | None] = mapped_column(String(32))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Role(Base):
    """描述可复用的平台角色。"""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Permission(Base):
    """保存稳定权限代码和显示说明。"""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)


class UserRole(Base):
    """关联用户与角色。"""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RoleGrant(Base):
    """保存角色在平台或指定工具范围内的授权。"""

    __tablename__ = "role_grants"
    __table_args__ = (
        UniqueConstraint(
            "role_id", "permission_code", "resource_type", "resource_id",
            name="uq_role_grants_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code", ondelete="CASCADE"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False, default="*")
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PlatformSession(Base):
    """保存可撤销的浏览器服务端会话，仅落 Token 哈希。"""

    __tablename__ = "platform_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    user_agent_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LoginThrottle(Base):
    """持久化用户名/IP 登录失败窗口，避免重启绕过限速。"""

    __tablename__ = "login_throttles"
    __table_args__ = (UniqueConstraint("key_type", "key_hash", name="uq_login_throttle_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_type: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ToolClient(Base):
    """保存工具工作负载身份及其最小能力。"""

    __tablename__ = "tool_clients"
    __table_args__ = (
        UniqueConstraint("tool_id", "environment_id", name="uq_tool_clients_tool_env"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id", ondelete="CASCADE"), nullable=False)
    environment_id: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    capabilities: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RuntimeContext(Base):
    """保存工具后台任务可使用的短期、可撤销用户运行上下文。

    记录只包含身份和资源绑定元数据，不保存签名 Header、权限列表、业务输入或
    Secret。每次物化配置时仍需校验 Session、用户状态和权限版本，避免已撤销的
    浏览器身份继续读取个人配置。
    """

    __tablename__ = "runtime_contexts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name="ck_runtime_contexts_status",
        ),
        CheckConstraint(
            "resource_type IN ('task', 'run', 'request')",
            name="ck_runtime_contexts_resource_type",
        ),
        Index(
            "ix_runtime_contexts_tool_environment_status_expires",
            "tool_id", "environment_id", "status", "expires_at",
        ),
        Index(
            "ix_runtime_contexts_user_status_expires",
            "user_id", "status", "expires_at",
        ),
        Index(
            "ix_runtime_contexts_session_status", "session_id", "status"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("platform_sessions.id", ondelete="CASCADE"), nullable=False
    )
    tool_id: Mapped[str] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"), nullable=False
    )
    environment_id: Mapped[str] = mapped_column(
        ForeignKey("environments.id"), nullable=False
    )
    # Runtime Context 必须固化解析时的 Scope；后续快照与会话写回只能使用该值，
    # 不能再次按可变项目状态猜测，从而防止任务创建后漂移到其他项目。
    runtime_scope_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_project_scopes.id", ondelete="RESTRICT")
    )
    permission_version: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id_snapshot: Mapped[str | None] = mapped_column(String(64))
    authorization_source_snapshot: Mapped[str | None] = mapped_column(String(32))
    allowed_config_refs: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    allowed_credential_refs: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    emergency_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
