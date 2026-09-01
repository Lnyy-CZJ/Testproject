"""按模式加载并验证运行配置。

这里集中执行 URL allowlist 和明文 HTTP 例外检查，确保任何业务 Adapter 在构造网络
请求之前就拒绝错误环境。Secret 字段禁止出现在 ``repr`` 和脱敏字典中。
"""

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import os

from aidating_eval.errors import ConfigurationError


EVAL_STAGING_HOST = "lb-rg3phjei-vzmdn2i7ey8rq40l.clb.usw-tencentclb.com"
PUBLIC_GATEWAY_URL = "https://gateway.spark-jam.top/dating/gateway/invoke"
PUBLIC_HEALTH_URL = "https://gateway.spark-jam.top/healthz"


def _bool_env(name: str, default: bool = False) -> bool:
    """读取严格布尔环境变量，防止拼写错误静默改变安全行为。"""

    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized not in {"true", "false", "1", "0"}:
        raise ConfigurationError(f"{name} 必须为 true/false/1/0")
    return normalized in {"true", "1"}


def _int_env(name: str, default: int) -> int:
    """读取整数环境变量并转换为工具可归类的配置错误。"""

    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须为整数") from exc


@dataclass(frozen=True)
class Settings:
    """一次运行的冻结配置；不同模式只验证自身必需字段。"""

    mode: str
    public_gateway_url: str = ""
    public_health_url: str = ""
    device_id: str = field(default="", repr=False)
    platform: str = "ios"
    app_version: str = "1.0.0"
    locale: str = "en-US"
    timezone: str = "UTC+08:00"
    country: str = "CN"
    app_package: str = "com.example.dating"
    consent_policy_version: str = "2026-08-25"
    e2e_fixture_root: Path = Path("datasets")
    eval_base_url: str = ""
    eval_api_key: str = field(default="", repr=False)
    allow_insecure_eval_http: bool = False
    artifacts_root: Path = Path("artifacts")
    eval_concurrency: int = 3

    @classmethod
    def from_env(cls, mode: str) -> "Settings":
        """从进程环境构造配置并立即执行模式专属安全校验。"""

        settings = cls(
            mode=mode,
            public_gateway_url=os.getenv("AIDATING_PUBLIC_GATEWAY_URL", ""),
            public_health_url=os.getenv("AIDATING_PUBLIC_HEALTH_URL", ""),
            device_id=os.getenv("AIDATING_E2E_DEVICE_ID", ""),
            platform=os.getenv("AIDATING_E2E_PLATFORM", "ios"),
            app_version=os.getenv("AIDATING_E2E_APP_VERSION", "1.0.0"),
            locale=os.getenv("AIDATING_E2E_LOCALE", "en-US"),
            timezone=os.getenv("AIDATING_E2E_TIMEZONE", "UTC+08:00"),
            country=os.getenv("AIDATING_E2E_COUNTRY", "CN"),
            app_package=os.getenv("AIDATING_E2E_APP_PACKAGE", "com.example.dating"),
            consent_policy_version=os.getenv(
                "AIDATING_E2E_CONSENT_POLICY_VERSION", "2026-08-25"
            ),
            e2e_fixture_root=Path(
                os.getenv("AIDATING_E2E_FIXTURE_ROOT", "datasets")
            ),
            eval_base_url=os.getenv("AIDATING_EVAL_BASE_URL", ""),
            eval_api_key=os.getenv("AIDATING_EVAL_API_KEY", ""),
            allow_insecure_eval_http=_bool_env(
                "AIDATING_EVAL_ALLOW_INSECURE_HTTP"
            ),
            artifacts_root=Path(os.getenv("AIDATING_ARTIFACTS_ROOT", "artifacts")),
            eval_concurrency=_int_env("AIDATING_EVAL_CONCURRENCY", 3),
        )
        settings.validate_for_mode(mode)
        return settings

    def validate_for_mode(self, mode: str) -> None:
        """验证当前模式所需字段；拒绝宽松 URL 匹配和隐式 HTTP。"""

        if mode == "e2e":
            if self.public_gateway_url != PUBLIC_GATEWAY_URL:
                raise ConfigurationError("公开 E2E Gateway 必须是已确认的 staging 地址")
            if self.public_health_url != PUBLIC_HEALTH_URL:
                raise ConfigurationError("公开 Health URL 必须是已确认的 staging 地址")
            if not self.device_id:
                raise ConfigurationError("AIDATING_E2E_DEVICE_ID 不能为空")
            if not self.e2e_fixture_root.is_dir():
                raise ConfigurationError("AIDATING_E2E_FIXTURE_ROOT 必须是现有目录")
            return

        if mode != "eval":
            raise ConfigurationError("mode 必须为 e2e 或 eval")

        parsed = urlparse(self.eval_base_url)
        if not self.eval_api_key:
            raise ConfigurationError("AIDATING_EVAL_API_KEY 不能为空")
        if (
            parsed.netloc != EVAL_STAGING_HOST
            or parsed.path != "/admin/invoke"
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError("Eval URL 必须命中精确 staging 主机和路径")
        if parsed.scheme == "http":
            if not self.allow_insecure_eval_http:
                raise ConfigurationError("内部 HTTP 只允许精确 staging 主机并显式开启")
        elif parsed.scheme != "https":
            raise ConfigurationError("Eval URL 必须使用 http 或 https")
        if not 1 <= self.eval_concurrency <= 5:
            raise ConfigurationError("AIDATING_EVAL_CONCURRENCY 必须在 1 到 5 之间")

    def redacted(self) -> dict[str, object]:
        """返回可记录配置视图，绝不暴露凭据或稳定设备标识。"""

        values = dict(self.__dict__)
        values["eval_api_key"] = "***" if self.eval_api_key else ""
        values["device_id"] = "***" if self.device_id else ""
        values["artifacts_root"] = str(self.artifacts_root)
        values["e2e_fixture_root"] = str(self.e2e_fixture_root)
        return values
