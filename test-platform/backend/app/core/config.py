from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    管理平台后端运行配置。

    功能说明:
        从环境变量读取数据库、日志和工具健康探测配置。
    返回值:
        Settings: 已完成类型校验的配置对象。
    异常说明:
        配置值类型不合法时由 Pydantic 抛出校验异常，阻止服务以错误配置启动。
    """

    database_url: str = "postgresql+psycopg://platform:platform@platform-db:5432/test_platform"
    app_env: str = "development"
    log_level: str = "INFO"
    tool_health_timeout_seconds: float = 3.0

    model_config = SettingsConfigDict(case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    """
    获取进程级配置单例。

    返回值:
        Settings: 缓存后的平台配置，避免每次请求重复解析环境变量。
    """

    return Settings()
