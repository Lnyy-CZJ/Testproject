import json
import re
from functools import lru_cache
from pathlib import Path

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
    session_idle_hours: int = 8
    session_absolute_hours: int = 24
    session_touch_interval_seconds: int = 300
    login_failure_limit: int = 5
    login_failure_window_minutes: int = 15
    login_lock_minutes: int = 15
    cookie_secure: bool = False
    bootstrap_token: str = ""
    bootstrap_token_file: str = ""
    secret_kek_file: str = ""
    audit_retention_days: int = 180
    credential_refresh_window_seconds: int = 3600
    credential_agent_interval_seconds: int = 60
    versions_manifest_file: str = str(Path(__file__).resolve().parents[3] / "versions.json")
    app_version: str = "unknown"
    app_revision: str = "unknown"
    app_build_dirty: bool = True
    version_peer_token: str = ""
    version_peer_token_file: str = ""
    prod_version_snapshot_url: str = ""
    prod_release_bom_file: str = ""

    model_config = SettingsConfigDict(case_sensitive=False)

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
