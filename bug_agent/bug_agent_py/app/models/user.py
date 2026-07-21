"""
用户与认证模型

对应 PRD 数据模型:
    - users: 用户表
    - invite_codes: 邀请码表
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    """
    用户表

    存储平台用户信息，包含 Agent 身份和平台角色。
    agent_types 使用逗号分隔字符串存储多个 Agent 身份。
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50))
    avatar: Mapped[str | None] = mapped_column(String(255))
    agent_types: Mapped[str | None] = mapped_column(String(200), default="")
    platform_role: Mapped[str] = mapped_column(String(30), default="member")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class InviteCode(Base):
    """
    邀请码表

    管理员生成的注册邀请码，含签名防篡改。
    """
    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    max_uses: Mapped[int] = mapped_column(default=0)
    used_count: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())