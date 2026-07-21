"""
Alembic 迁移环境配置

自动发现所有 SQLAlchemy ORM 模型并生成迁移脚本。
数据库连接 URL 从 app.config.settings 读取。
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 将项目根目录加入 sys.path，确保可以导入 app 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.models.base import Base

# 导入所有模型（触发 __init__.py 中的注册）
import app.models  # noqa: E402, F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从 Pydantic Settings 读取数据库 URL
config.set_main_option("sqlalchemy.url", settings.database.sync_url)

# 所有模型的元数据集合
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 脚本文件"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：直接连接数据库执行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()