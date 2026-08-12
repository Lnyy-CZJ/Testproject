from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Environment(Base):
    """描述平台可管理的配置环境。"""

    __tablename__ = "environments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ConfigDefinition(Base):
    """登记允许通过 Web 管理的配置项及其约束。"""

    __tablename__ = "config_definitions"
    __table_args__ = (UniqueConstraint("owner_type", "owner_id", "key", name="uq_config_definition_owner_key"),)

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
    __table_args__ = (UniqueConstraint("tool_id", "environment_id", "provider_type", name="uq_credential_scope"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tools.id"), nullable=False)
    environment_id: Mapped[str] = mapped_column(ForeignKey("environments.id"), nullable=False)
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
