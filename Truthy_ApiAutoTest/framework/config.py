"""运行环境配置加载。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    """框架运行配置。

    功能说明:
        保存非敏感环境参数与仅由环境变量注入的凭据。
    参数说明:
        字段可由默认值、环境 YAML、环境变量和命令行参数按优先级合并。
    返回值:
        配置模型实例；未知配置字段会被忽略以兼容服务端配置扩展。
    异常说明:
        字段类型或约束不合法时由 Pydantic 抛出校验异常。
    """

    model_config = ConfigDict(extra="ignore")

    env_name: str = "test"
    base_url: str = "http://127.0.0.1:8000"
    device_id: str = "autotest-device"
    platform: str = "ios"
    app_version: str = "1.0.0"
    locale: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    connect_timeout: float = Field(default=5.0, gt=0)
    read_timeout: float = Field(default=15.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=2)
    auth_token: str | None = Field(default=None, repr=False)
    refresh_token: str | None = Field(default=None, repr=False)


_ENVIRONMENT_FIELDS = {
    "TRUTHY_BASE_URL": "base_url",
    "TRUTHY_DEVICE_ID": "device_id",
    "TRUTHY_PLATFORM": "platform",
    "TRUTHY_APP_VERSION": "app_version",
    "TRUTHY_LOCALE": "locale",
    "TRUTHY_TIMEZONE": "timezone",
    "TRUTHY_CONNECT_TIMEOUT": "connect_timeout",
    "TRUTHY_READ_TIMEOUT": "read_timeout",
    "TRUTHY_MAX_RETRIES": "max_retries",
    "TRUTHY_AUTH_TOKEN": "auth_token",
    "TRUTHY_REFRESH_TOKEN": "refresh_token",
}
_SENSITIVE_FIELDS = {"auth_token", "refresh_token"}


def load_config(
    env_name: str = "test",
    *,
    cli_overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    config_dir: str | Path | None = None,
) -> Settings:
    """按优先级加载运行配置。

    功能说明:
        依次合并默认值、环境 YAML、环境变量与命令行覆盖项；敏感字段仅接受环境变量。
    参数说明:
        env_name: 环境名，对应 ``env.<name>.yaml``。
        cli_overrides: 命令行提供的非空覆盖值。
        environ: 环境变量映射，默认读取当前进程环境。
        config_dir: 配置目录，默认使用项目根目录下的 ``config``。
    返回值:
        校验后的 :class:`Settings`。
    异常说明:
        YAML 不是对象、文件无法读取或配置值校验失败时抛出对应异常。
    """

    directory = Path(config_dir) if config_dir is not None else Path(__file__).resolve().parent.parent / "config"
    path = directory / f"env.{env_name}.yaml"
    yaml_values: dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"环境配置必须是对象: {path}")
        yaml_values = {key: value for key, value in loaded.items() if key not in _SENSITIVE_FIELDS}

    source_environ = os.environ if environ is None else environ
    environment_values = {
        field: source_environ[name]
        for name, field in _ENVIRONMENT_FIELDS.items()
        if name in source_environ and source_environ[name] != ""
    }
    safe_cli_values = {
        key: value
        for key, value in (cli_overrides or {}).items()
        if value is not None and key not in _SENSITIVE_FIELDS
    }

    values: dict[str, Any] = {"env_name": env_name}
    values.update(yaml_values)
    values.update(environment_values)
    values.update(safe_cli_values)
    return Settings.model_validate(values)
