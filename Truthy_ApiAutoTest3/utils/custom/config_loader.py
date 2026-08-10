"""YAML 与环境配置加载工具。"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """表示配置文件缺失、格式错误或必填配置不完整。"""


SESSION_ENV_MAPPING = {
    "access_token": "AUTH_TOKEN",
    "refresh_token": "REFRESH_TOKEN",
    "user_id": "USER_ID",
    "device_id": "DEVICE_ID",
    "expires_time": "EXPIRES_TIME",
    "refresh_expires_time": "REFRESH_EXPIRES_TIME",
}
ADMIN_ENV_MAPPING = {
    "admin_session_token": "ADMIN_SESSION_TOKEN",
    "admin_operator_id": "ADMIN_OPERATOR_ID",
    "admin_operator_name": "ADMIN_OPERATOR_NAME",
}


def load_dotenv_values(path: Path) -> dict[str, str]:
    """读取项目 .env 中的简单 KEY=VALUE 配置，不修改进程环境变量。

    参数说明:
        path: .env 文件路径；文件不存在时视为未配置。

    返回值:
        去除空行和注释后的环境变量字典；包裹值的单、双引号会被移除。
    """
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def persist_session_to_dotenv(path: Path, values: dict[str, Any]) -> None:
    """将已成功获取的会话字段更新到 .env，同时保留无关配置与注释。

    参数说明:
        path: 要写入的项目 .env 路径。
        values: RuntimeContext 中的会话字段；空值不会覆盖已有值。

    返回值:
        无。目录不存在或文件无法写入时由 Path.write_text 抛出 OSError。
    """
    updates = {
        env_key: str(values[runtime_key])
        for runtime_key, env_key in SESSION_ENV_MAPPING.items()
        if values.get(runtime_key) not in (None, "")
    }
    if not updates:
        return

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    result: list[str] = []
    for line in lines:
        key, separator, _ = line.partition("=")
        normalized_key = key.strip()
        if separator and normalized_key in remaining:
            result.append(f"{normalized_key}={remaining.pop(normalized_key)}")
        else:
            result.append(line)
    result.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(result) + "\n", encoding="utf-8")


def load_yaml(path: Path) -> dict[str, Any]:
    """读取一个 YAML 对象。

    参数说明:
        path: YAML 文件路径，文件根节点必须是对象。

    返回值:
        YAML 根对象对应的字典；空文件返回空字典。

    异常说明:
        ConfigError: 文件不存在、YAML 语法错误或根节点不是对象时抛出。
    """
    try:
        with path.open("r", encoding="utf-8") as file:
            content = yaml.safe_load(file) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 格式错误: {path}: {exc}") from exc

    if not isinstance(content, dict):
        raise ConfigError(f"YAML 根节点必须是对象: {path}")
    return content


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并字典，环境配置覆盖默认配置。"""
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_settings(
    env: str,
    project_root: Path | None = None,
    require_secrets: bool = True,
) -> dict[str, Any]:
    """加载指定环境的完整运行配置。

    功能说明:
        合并 ``config/settings.yaml`` 与 ``config/env/{env}.yaml``，再将
        读取项目 .env，并允许进程环境变量覆盖同名值。AUTH_TOKEN、USER_ID 和
        DEVICE_ID 写入 ``comm``；其余会话字段写入 ``runtime_session``。

    参数说明:
        env: 环境名称，例如 ``test``。
        project_root: 项目根目录；为空时自动定位当前项目。
        require_secrets: 是否要求最终配置中存在 device_id。

    返回值:
        可用于构造 Gateway 请求的配置字典。

    异常说明:
        ConfigError: 环境名称非法、配置缺失或必填敏感变量缺失时抛出。
    """
    if not env or Path(env).name != env:
        raise ConfigError(f"环境名称不合法: {env!r}")

    root = project_root or Path(__file__).resolve().parents[2]
    settings = _deep_merge(
        load_yaml(root / "config" / "settings.yaml"),
        load_yaml(root / "config" / "env" / f"{env}.yaml"),
    )
    if not settings.get("gateway_base_url"):
        raise ConfigError("环境配置缺少 gateway_base_url")

    comm = settings.setdefault("comm", {})
    if not isinstance(comm, dict):
        raise ConfigError("comm 配置必须是对象")

    env_values = load_dotenv_values(root / ".env")
    managed_env_keys = (*SESSION_ENV_MAPPING.values(), *ADMIN_ENV_MAPPING.values())
    env_values.update(
        {key: value for key in managed_env_keys if (value := os.getenv(key))}
    )
    comm_mapping = {
        "auth_token": "AUTH_TOKEN",
        "user_id": "USER_ID",
        "device_id": "DEVICE_ID",
    }
    for comm_key, env_key in comm_mapping.items():
        value = env_values.get(env_key)
        if value:
            comm[comm_key] = value

    settings["runtime_session"] = {
        runtime_key: env_values[env_key]
        for runtime_key, env_key in SESSION_ENV_MAPPING.items()
        if env_values.get(env_key)
    }
    settings["runtime_variables"] = {
        runtime_key: env_values[env_key]
        for runtime_key, env_key in ADMIN_ENV_MAPPING.items()
        if env_values.get(env_key)
    }

    if require_secrets and not comm.get("device_id"):
        raise ConfigError("缺少必填设备标识: 请配置 comm.device_id 或 DEVICE_ID")
    return settings
