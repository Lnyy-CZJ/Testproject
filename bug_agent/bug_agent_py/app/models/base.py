"""
SQLAlchemy ORM 基类

替代 Go 版 model/db.go，提供:
1. DeclarativeBase 基类
2. TimestampMixin（自动管理 created_at / updated_at）
3. 所有模型的 __init__.py 统一导出
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类，所有 ORM 模型继承自此"""
    pass


class TimestampMixin:
    """
    时间戳混入类

    自动管理 created_at 和 updated_at 字段。
    使用 server_default 确保数据库层面设置默认值。
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        default=datetime.utcnow,
    )