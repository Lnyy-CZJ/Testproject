import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
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
    app_public_url: str = "http://localhost:8080"
    platform_runtime_env: str = "dev"
    # 新签发的登录会话同时采用 7 天空闲期限和 7 天绝对期限；
    # 数据库中已存在的会话仍按各自持久化的到期时间判断，不会被此默认值追溯修改。
    session_idle_hours: int = 168
    session_absolute_hours: int = 168
    session_touch_interval_seconds: int = 300
    login_failure_limit: int = 5
    login_failure_window_minutes: int = 15
    login_lock_minutes: int = 15
    # 自助注册默认开放，但所有提交在进入业务校验前都受来源限流和全局熔断保护。
    # 这些边界只能保持或收紧，避免通过环境变量把防滥用能力意外关闭。
    registration_mode: Literal["open", "disabled", "invite"] = "open"
    registration_rate_limit: int = Field(default=5, ge=1, le=5)
    registration_rate_window_minutes: int = Field(default=15, ge=15)
    registration_lock_minutes: int = Field(default=15, ge=15)
    registration_global_limit: int = Field(default=100, ge=1, le=100)
    registration_global_window_minutes: int = Field(default=15, ge=15)
    registration_global_lock_minutes: int = Field(default=15, ge=15)
    cookie_secure: bool = False
    bootstrap_token: str = ""
    bootstrap_token_file: str = ""
    secret_kek_file: str = ""
    audit_retention_days: int = 180
    credential_refresh_window_seconds: int = 3600
    credential_agent_interval_seconds: int = 60
    # 两个开关故意相互独立：先开放个人配置写入，完成数据迁移与验收后，
    # 再让运行时 Resolver 切换到个人数据。默认关闭可避免升级过程中意外改写读取语义。
    personal_credentials_write_enabled: bool = False
    personal_credentials_enabled: bool = False
    user_context_signing_key_file: str = ""
    user_context_ttl_seconds: int = 300
    runtime_context_ttl_seconds: int = 86400
    versions_manifest_file: str = str(Path(__file__).resolve().parents[3] / "versions.json")
    app_version: str = "unknown"
    app_revision: str = "unknown"
    app_build_dirty: bool = True
    app_content_sha256: str = "unknown"
    version_peer_token: str = ""
    version_peer_token_file: str = ""
    prod_version_snapshot_url: str = ""
    prod_release_bom_file: str = ""

    model_config = SettingsConfigDict(case_sensitive=False)

    @model_validator(mode="after")
    def validate_registration_rate_windows(self) -> "Settings":
        """确保注册锁定至少覆盖完整计数窗口。

        返回值:
            Settings: 校验通过的当前配置实例。
        异常说明:
            ValueError: 来源或全局锁定短于对应窗口时阻止服务启动。
        """

        if self.registration_lock_minutes < self.registration_rate_window_minutes:
            raise ValueError("注册来源锁定时间不能短于计数窗口")
        if (
            self.registration_global_lock_minutes
            < self.registration_global_window_minutes
        ):
            raise ValueError("注册全局锁定时间不能短于计数窗口")
        return self

    def read_bootstrap_token(self) -> str:
        """
        读取一次性管理员引导 Token。

        返回值:
            str: 文件或环境变量中的 Token；未配置时返回空字符串。
        异常说明:
            OSError: 配置了文件但文件不可读取时继续抛出，阻止不安全初始化。
        """

        if self.bootstrap_token_file:
            return Path(self.bootstrap_token_file).read_text(encoding="utf-8").strip()
        return self.bootstrap_token.strip()

    def read_platform_version(self) -> str:
        """
        从唯一版本清单读取并校验当前产品版本。

        返回值:
            str: 标准 Semantic Versioning 版本号。
        异常说明:
            OSError: 版本文件不可读取时继续抛出，避免发布版本来源不明。
            ValueError: 版本格式不符合约定时阻止服务启动。
        """

        payload = json.loads(Path(self.versions_manifest_file).read_text(encoding="utf-8"))
        version = str(payload["product"]["version"])
        if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
            raise ValueError("平台产品版本必须使用无前导零的 Semantic Versioning")
        return version

    def read_versions_manifest(self) -> dict:
        """读取组件版本清单，供健康接口和版本矩阵使用。"""

        return json.loads(Path(self.versions_manifest_file).read_text(encoding="utf-8"))

    def read_version_peer_token(self) -> str:
        """优先从权限受限文件读取只读环境互查 Token。"""

        if self.version_peer_token_file:
            return Path(self.version_peer_token_file).read_text(encoding="utf-8").strip()
        return self.version_peer_token.strip()


@lru_cache
def get_settings() -> Settings:
    """
    获取进程级配置单例。

    返回值:
        Settings: 缓存后的平台配置，避免每次请求重复解析环境变量。
    """

    return Settings()
