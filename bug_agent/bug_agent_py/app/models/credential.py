"""
凭证与平台设置模型

对应 PRD 数据模型:
    - repo_credentials: 仓库凭证表
    - platform_credential_projects: 平台凭证-项目关联表
    - platform_settings: 平台设置表
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RepoCredential(Base):
    """
    仓库凭证表

    scope:
        - personal: 个人凭证（仅创建者可用）
        - platform: 平台凭证（可绑定项目，全局共享）

    AES-256-GCM 加密存储私钥和密码。
    """
    __tablename__ = "repo_credentials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), default="personal")
    auth_type: Mapped[str] = mapped_column(String(20), default="token")
    token: Mapped[str | None] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(100))
    password: Mapped[str | None] = mapped_column(Text)
    ssh_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlatformCredentialProject(Base):
    """平台凭证与项目的关联表"""
    __tablename__ = "platform_credential_projects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    credential_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repo_credentials.id"), nullable=False)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id"), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class PlatformSetting(Base):
    """平台设置表（SMTP 等全局配置）"""
    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    setting_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())