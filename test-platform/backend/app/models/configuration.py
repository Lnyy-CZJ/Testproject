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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Environment(Base):
    """描述平台可管理的配置环境。"""

    __tablename__ = "environments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ToolProjectScope(Base):
    """定义工具项目在平台项目和固定目标环境中的唯一运行边界。

    Scope 是 Release、Secret 与 Credential 的共同所有权锚点。数据库同时约束
    固定环境映射和默认项唯一性，避免应用遗漏校验时跨项目读取运行材料。
    """

    __tablename__ = "tool_project_scopes"
    __table_args__ = (
        UniqueConstraint(
            "environment_id", "tool_id", "platform_project_id", "project_id",
            "target_env", name="uq_tool_project_scope_identity",
        ),
        CheckConstraint(
            "(environment_id = 'dev' AND target_env = 'test') OR "
            "(environment_id = 'prod' AND target_env = 'prod')",
            name="ck_tool_project_scopes_environment_mapping",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_tool_project_scopes_status",
        ),
        CheckConstraint(
            "length(project_id) BETWEEN 2 AND 32 AND "
            "project_id = lower(project_id) AND "
            "substr(project_id, 1, 1) BETWEEN 'a' AND 'z'",
            name="ck_tool_project_scopes_project_id",
        ),
        CheckConstraint(
            "project_id GLOB '[a-z][a-z0-9-]*' AND "
            "project_id NOT GLOB '*[^a-z0-9-]*'",
            name="ck_tool_project_scopes_project_id_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "project_id ~ '^[a-z][a-z0-9-]{1,31}$'",
            name="ck_tool_project_scopes_project_id_postgresql",
        ).ddl_if(dialect="postgresql"),
        Index(
            "uq_tool_project_scopes_default_context",
            "environment_id", "tool_id", "platform_project_id",
            unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default = true"),
        ),
        Index(
            "ix_tool_project_scopes_lookup",
            "tool_id", "environment_id", "platform_project_id", "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    environment_id: Mapped[str] = mapped_column(
        ForeignKey("environments.id"), nullable=False
    )
    tool_id: Mapped[str] = mapped_column(
        ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False
    )
    platform_project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(String(32), nullable=False)
    target_env: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )


class ConfigDefinition(Base):
    """登记允许通过 Web 管理的配置项及其约束。"""

    __tablename__ = "config_definitions"
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id", "key", name="uq_config_definition_owner_key"),
        CheckConstraint(
            "value_scope IN ('system', 'user')",
            name="ck_config_definitions_value_scope",
        ),
        CheckConstraint(
            "credential_provider_type IS NULL OR "
            "(owner_type = 'tool' AND value_scope = 'user')",
            name="ck_config_definitions_credential_provider_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    group_key: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    value_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_value: Mapped[Any | None] = mapped_column(JSON)
    validation_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    apply_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="next_task")
    editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    value_scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="system", server_default="system"
    )
    credential_provider_type: Mapped[str | None] = mapped_column(String(64))


class ConfigRelease(Base):
    """保存指定环境和工具的一组版本化配置。"""

    __tablename__ = "config_releases"
    __table_args__ = (
        UniqueConstraint("environment_id", "owner_type", "owner_id", "version", name="uq_config_release_version"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    based_on_release_id: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConfigReleaseItem(Base):
    """保存 Release 中的普通值或 Secret Version 引用。"""

    __tablename__ = "config_release_items"
    __table_args__ = (UniqueConstraint("release_id", "definition_id", name="uq_config_release_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    release_id: Mapped[str] = mapped_column(ForeignKey("config_releases.id", ondelete="CASCADE"), nullable=False)
    definition_id: Mapped[str] = mapped_column(ForeignKey("config_definitions.id"), nullable=False)
    value_json: Mapped[Any | None] = mapped_column(JSON)
    secret_version_id: Mapped[str | None] = mapped_column(String(64))


class ConfigActivation(Base):
    """保存一个配置作用域的当前发布和工具确认版本。"""

    __tablename__ = "config_activations"
    __table_args__ = (UniqueConstraint("environment_id", "owner_type", "owner_id", name="uq_config_activation_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    active_release_id: Mapped[str] = mapped_column(ForeignKey("config_releases.id"), nullable=False)
    confirmed_release_id: Mapped[str | None] = mapped_column(String(64))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Secret(Base):
    """保存 Secret 元数据和当前激活版本引用。"""

    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("environment_id", "owner_type", "owner_id", "definition_id", name="uq_secret_scope"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_id: Mapped[str] = mapped_column(ForeignKey("config_definitions.id"), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="missing")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class SecretVersion(Base):
    """保存使用信封加密后的不可变 Secret 版本。"""

    __tablename__ = "secret_versions"
    __table_args__ = (UniqueConstraint("secret_id", "version", name="uq_secret_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    secret_id: Mapped[str] = mapped_column(ForeignKey("secrets.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    cipher_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrap_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kek_version: Mapped[str] = mapped_column(String(32), nullable=False)
    aad_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Credential(Base):
    """聚合一组会话 Secret 的状态、版本和刷新租约。"""

    __tablename__ = "credentials"
    __table_args__ = (
        Index(
            "uq_credentials_legacy_scope", "tool_id", "environment_id", "provider_type",
            unique=True, sqlite_where=text("runtime_scope_id IS NULL"),
            postgresql_where=text("runtime_scope_id IS NULL"),
        ),
        Index(
            "uq_credentials_runtime_scope", "runtime_scope_id", "provider_type",
            unique=True, sqlite_where=text("runtime_scope_id IS NOT NULL"),
            postgresql_where=text("runtime_scope_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id"), nullable=False)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
    runtime_scope_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_project_scopes.id", ondelete="RESTRICT")
    )
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="missing")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_owner: Mapped[str | None] = mapped_column(String(64))
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CredentialItem(Base):
    """保存 Credential 版本内的 Secret 引用或非敏感元数据。"""

    __tablename__ = "credential_items"
    __table_args__ = (UniqueConstraint("credential_id", "credential_version", "key", name="uq_credential_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False)
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    secret_version_id: Mapped[str | None] = mapped_column(String(64))
    value_json: Mapped[Any | None] = mapped_column(JSON)


class UserCredential(Base):
    """保存某个登录用户在指定工具和环境下的个人 Credential 状态。

    个人 Credential 使用独立表，确保旧 Resolver 无法通过 legacy ``credentials``
    表误读普通用户数据。唯一范围包含 ``user_id``，因此相同 Provider 可以被不同
    用户分别配置和轮换，刷新租约也不会跨用户互相阻塞。
    """

    __tablename__ = "user_credentials"
    __table_args__ = (
        Index(
            "uq_user_credentials_legacy_scope",
            "user_id", "tool_id", "environment_id", "provider_type",
            unique=True,
            sqlite_where=text("runtime_scope_id IS NULL"),
            postgresql_where=text("runtime_scope_id IS NULL"),
        ),
        Index(
            "uq_user_credentials_runtime_scope",
            "user_id", "runtime_scope_id", "provider_type",
            unique=True,
            sqlite_where=text("runtime_scope_id IS NOT NULL"),
            postgresql_where=text("runtime_scope_id IS NOT NULL"),
        ),
        Index(
            "ix_user_credentials_environment_status_expires",
            "environment_id", "status", "expires_at",
        ),
        Index(
            "ix_user_credentials_user_environment_tool",
            "user_id", "environment_id", "tool_id",
        ),
        Index(
            "ix_user_credentials_refresh_lease_status",
            "refresh_lease_until", "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tool_id: Mapped[str] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"), nullable=False
    )
    environment_id: Mapped[str] = mapped_column(
        ForeignKey("environments.id"), nullable=False
    )
    runtime_scope_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_project_scopes.id", ondelete="RESTRICT")
    )
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="missing")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_owner: Mapped[str | None] = mapped_column(String(64))
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserCredentialItem(Base):
    """保存个人 Credential 某一版本的加密 Secret 引用或非敏感值。

    每个条目必须且只能选择一种值来源。Secret 明文始终保存在信封加密的
    ``secret_versions`` 中，本表仅保存版本引用；这样历史任务可以稳定解析精确
    版本，同时避免把敏感值复制进业务表。
    """

    __tablename__ = "user_credential_items"
    __table_args__ = (
        UniqueConstraint(
            "credential_id", "credential_version", "key",
            name="uq_user_credential_item",
        ),
        CheckConstraint(
            "(secret_version_id IS NOT NULL AND value_json IS NULL) OR "
            "(secret_version_id IS NULL AND value_json IS NOT NULL)",
            name="ck_user_credential_items_value_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    credential_id: Mapped[str] = mapped_column(
        ForeignKey("user_credentials.id", ondelete="CASCADE"), nullable=False
    )
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    secret_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("secret_versions.id"), nullable=True
    )
    value_json: Mapped[Any | None] = mapped_column(JSON(none_as_null=True), nullable=True)
