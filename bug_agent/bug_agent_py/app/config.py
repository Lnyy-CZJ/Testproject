"""
Pydantic Settings 配置管理

替代 Go 版 Viper 配置，使用 Pydantic Settings 实现类型安全的配置加载。
支持从 .env 文件和环境变量读取，环境变量前缀为 BUG_AGENT_。
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    """服务配置"""
    model_config = SettingsConfigDict(env_prefix="BUG_AGENT_SERVER_")

    port: str = Field(default="8765", description="HTTP 服务端口")
    mode: str = Field(default="debug", description="运行模式: debug / release")
    admin_password: str = Field(default="", description="默认管理员密码")
    upload_dir: str = Field(default="./uploads", description="文件上传目录")


class DatabaseSettings(BaseSettings):
    """数据库配置"""
    model_config = SettingsConfigDict(env_prefix="BUG_AGENT_DATABASE_")

    driver: str = Field(default="postgresql+asyncpg", description="数据库驱动")
    host: str = Field(default="localhost", description="数据库主机地址")
    port: str = Field(default="5432", description="数据库端口")
    user: str = Field(default="postgres", description="数据库用户名")
    password: SecretStr = Field(default=SecretStr(""), description="数据库密码")
    dbname: str = Field(default="bug_agent", description="数据库名称")
    db_schema: str = Field(default="public", description="数据库 Schema")
    sslmode: str = Field(default="disable", description="SSL 模式")

    max_open_conns: int = Field(default=20, description="最大连接数")
    max_idle_conns: int = Field(default=10, description="最大空闲连接数")
    conn_max_lifetime_seconds: int = Field(default=1800)
    conn_max_idle_time_seconds: int = Field(default=300)

    @property
    def url(self) -> str:
        """构建 SQLAlchemy 异步连接 URL"""
        return (
            f"{self.driver}://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.dbname}"
        )

    @property
    def sync_url(self) -> str:
        """
        构建 SQLAlchemy 同步连接 URL（用于 Alembic 迁移）。

        使用项目依赖中已安装的 psycopg v3 驱动，避免 `postgresql://`
        被 SQLAlchemy 解析为未安装的 psycopg2 驱动。
        """
        return (
            f"postgresql+psycopg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.dbname}"
        )


class JWTSettings(BaseSettings):
    """JWT 认证配置"""
    model_config = SettingsConfigDict(env_prefix="BUG_AGENT_JWT_")

    secret: str = Field(
        default="bug-agent-secret-key-change-in-production",
        min_length=16,
        description="JWT 签名密钥",
    )
    expire_hour: int = Field(default=72, description="Token 过期时间(小时)")


class RedisSettings(BaseSettings):
    """Redis 缓存配置"""
    model_config = SettingsConfigDict(env_prefix="BUG_AGENT_REDIS_")

    host: str = Field(default="localhost", description="Redis 主机地址")
    port: str = Field(default="6379", description="Redis 端口")
    password: str = Field(default="", description="Redis 密码")
    db: int = Field(default=0, description="Redis 数据库编号")

    @property
    def url(self) -> str:
        """构建 Redis 连接 URL"""
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class SecretsSettings(BaseSettings):
    """加密密钥配置"""
    model_config = SettingsConfigDict(env_prefix="BUG_AGENT_SECRETS_")

    credential_encrypt_key: str = Field(
        default="0123456789abcdef0123456789abcdef",
        min_length=16,
        description="凭证加密密钥(AES-256-GCM)",
    )
    ai_config_encryption_key: str = Field(
        default="0123456789abcdef0123456789abcdef",
        min_length=16,
        description="AI 配置加密密钥(AES-256-GCM)",
    )
    invite_code_sign_key: str = Field(
        default="0123456789abcdef0123456789abcdef",
        min_length=32,
        description="邀请码签名密钥(HMAC-SHA256)",
    )


class Settings(BaseSettings):
    """全局配置"""
    model_config = SettingsConfigDict(
        env_prefix="BUG_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    secrets: SecretsSettings = Field(default_factory=SecretsSettings)


# 全局配置单例
settings = Settings()
