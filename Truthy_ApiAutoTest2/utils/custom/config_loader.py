"""YAML 与环境配置加载工具。"""

from __future__ import annotations

import json
import os
import stat
from contextlib import contextmanager
from copy import deepcopy
from collections.abc import Iterator
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


def _validate_runtime_identity(
    snapshot: dict[str, Any],
    *,
    env: str,
    project_id: str | None,
    task_id: str | None,
    runtime_scope_id: str | None,
) -> None:
    """校验平台快照不可变身份，任一不一致都 fail-closed。

    这些字段由受控 Runtime Scope 和任务创建链路确定，不能由本地 YAML、环境
    变量或命令行覆盖。调用方未提供可选期望值时仍校验快照字段非空。
    """
    if snapshot.get("schema_version") != 1:
        raise ConfigError("平台运行快照 schema_version 仅支持 1")
    required_strings = (
        "task_id",
        "runtime_scope_id",
        "platform_environment",
        "tool_id",
        "platform_project_id",
        "project_id",
        "target_env",
        "config_release_id",
    )
    for field in required_strings:
        if not isinstance(snapshot.get(field), str) or not snapshot[field].strip():
            raise ConfigError(f"平台运行快照缺少 {field}")
    if snapshot["tool_id"] != "api-autotest":
        raise ConfigError(f"平台运行快照 tool_id 不匹配: {snapshot['tool_id']!r}")
    expected = {
        "project_id": project_id,
        "task_id": task_id,
        "runtime_scope_id": runtime_scope_id,
    }
    for field, expected_value in expected.items():
        if expected_value is not None and snapshot[field] != expected_value:
            raise ConfigError(
                f"平台运行快照 {field} 不匹配: 期望 {expected_value!r}"
            )
    if snapshot["target_env"] != env:
        raise ConfigError(
            f"平台运行快照 target_env 不匹配: 期望 {env!r}"
        )
    platform_environment = snapshot["platform_environment"]
    mapped_target = {"dev": "test", "prod": "prod"}.get(platform_environment)
    if mapped_target != snapshot["target_env"]:
        raise ConfigError(
            "平台运行快照 platform_environment 与 target_env 固定映射不匹配"
        )


def _read_runtime_snapshot(path: Path) -> dict[str, Any]:
    """从 0600 普通文件读取一次平台快照，拒绝符号链接和宽权限文件。"""
    try:
        file_stat = path.lstat()
    except FileNotFoundError as exc:
        raise ConfigError(f"平台运行快照文件不存在: {path}") from exc
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise ConfigError("平台运行快照必须是非符号链接的普通文件")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise ConfigError("平台运行快照文件权限必须为 0600")
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"平台运行快照 JSON 无法读取: {exc}") from exc
    if not isinstance(content, dict):
        raise ConfigError("平台运行快照 JSON 根节点必须是对象")
    return content


def _normalize_platform_settings(settings: dict[str, Any]) -> None:
    """把 Manifest/Release 逻辑键转换为现有 Gateway 与 Flow 执行结构。"""
    gateway = settings.get("gateway")
    gateway_values = gateway if isinstance(gateway, dict) else {}
    mappings = {
        "base_url": "gateway_base_url",
        "path": "gateway_path",
        "method": "gateway_method",
        "headers": "gateway_headers",
    }
    for logical_name, runtime_name in mappings.items():
        dotted_name = f"gateway.{logical_name}"
        value = settings.pop(dotted_name, None)
        if value is None:
            value = gateway_values.get(logical_name)
        if value is not None and runtime_name not in settings:
            settings[runtime_name] = deepcopy(value)
    comm_value = settings.pop("gateway.comm", None)
    if comm_value is None:
        comm_value = gateway_values.get("comm")
    if comm_value is not None and "comm" not in settings:
        settings["comm"] = deepcopy(comm_value)

    flow = settings.get("flow")
    if not isinstance(flow, dict):
        flow = {}
    analysis = flow.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
    for key in ("poll_interval_seconds", "timeout_seconds"):
        dotted_name = f"flow.analysis.{key}"
        if dotted_name in settings:
            analysis[key] = deepcopy(settings.pop(dotted_name))
    if analysis:
        flow["analysis"] = analysis
        settings["flow"] = flow


def validate_settings_contract(
    settings: dict[str, Any],
    required_keys: tuple[str, ...] | list[str],
) -> None:
    """按 Project Manifest 逻辑键校验已规范化的平台运行配置。

    Gateway 现有执行结构使用扁平键，因此先处理稳定别名；其他点分键按嵌套
    字典读取。仅报告逻辑键名，不在错误中输出任何配置值或 Secret。
    """
    aliases = {
        "gateway.base_url": "gateway_base_url",
        "gateway.path": "gateway_path",
        "gateway.method": "gateway_method",
        "gateway.headers": "gateway_headers",
        "gateway.comm": "comm",
    }
    missing: list[str] = []
    for logical_key in required_keys:
        if logical_key in aliases:
            value: Any = settings.get(aliases[logical_key])
        else:
            value = settings
            for token in logical_key.split("."):
                if not isinstance(value, dict) or token not in value:
                    value = None
                    break
                value = value[token]
        if value is None or value == "":
            missing.append(logical_key)
    if missing:
        raise ConfigError(
            "平台运行快照缺少 Manifest 必需配置键: " + ", ".join(sorted(missing))
        )


def create_runtime_snapshot_file(
    runtime_root: Path,
    project_id: str,
    task_id: str,
    snapshot: dict[str, Any],
) -> Path:
    """以独占 0600 文件物化任务快照，供 TaskManager/CLI 公共调用。

    文件固定写入 ``runtime/<project_id>/<task_id>/snapshot.json``。项目和任务
    标识只允许单一路径段，避免清理接口被路径输入扩大删除范围。
    """
    for field, value in (("project_id", project_id), ("task_id", task_id)):
        if not value or Path(value).name != value or value in {".", ".."}:
            raise ConfigError(f"创建平台快照时 {field} 不合法: {value!r}")
    directory = runtime_root / project_id / task_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "snapshot.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ConfigError(f"任务平台快照已存在: {project_id}/{task_id}") from exc
    try:
        payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        with os.fdopen(descriptor, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def delete_runtime_snapshot_file(path: Path) -> None:
    """删除单个任务快照；仅清理已知文件和其空任务目录。"""
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        # 任务目录还包含受控运行产物时保留，禁止递归宽删除。
        pass


@contextmanager
def runtime_snapshot_file(
    runtime_root: Path,
    project_id: str,
    task_id: str,
    snapshot: dict[str, Any],
) -> Iterator[Path]:
    """创建并在任意终态/异常退出时删除任务专属平台快照。"""
    path = create_runtime_snapshot_file(runtime_root, project_id, task_id, snapshot)
    try:
        yield path
    finally:
        delete_runtime_snapshot_file(path)


def load_settings(
    env: str,
    project_root: Path | None = None,
    require_secrets: bool = True,
    *,
    config_source: str = "local",
    snapshot_file: Path | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
    runtime_scope_id: str | None = None,
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

    if config_source not in {"local", "platform"}:
        raise ConfigError("config_source 必须为 platform 或 local")

    if config_source == "platform":
        controlled_path = snapshot_file
        if controlled_path is None:
            configured_path = os.getenv(
                "API_AUTOTEST_RUNTIME_SNAPSHOT_FILE",
                os.getenv("APIAUTOTEST_RUNTIME_SNAPSHOT_FILE", ""),
            )
            controlled_path = Path(configured_path) if configured_path else None
        if controlled_path is None:
            raise ConfigError("平台模式缺少任务专属运行快照文件")
        snapshot = _read_runtime_snapshot(controlled_path)
        _validate_runtime_identity(
            snapshot,
            env=env,
            project_id=project_id,
            task_id=task_id,
            runtime_scope_id=runtime_scope_id,
        )
        settings_value = snapshot.get("settings")
        if not isinstance(settings_value, dict):
            raise ConfigError("平台运行快照 settings 必须是对象")
        settings = deepcopy(settings_value)
        _normalize_platform_settings(settings)
        metadata_keys = (
            "task_id",
            "runtime_scope_id",
            "platform_environment",
            "platform_project_id",
            "project_id",
            "target_env",
            "config_release_id",
            "config_release_version",
            "credential_profiles",
            "snapshot_time",
        )
        settings["runtime_metadata"] = {
            key: deepcopy(snapshot.get(key)) for key in metadata_keys
        }
        comm = settings.setdefault("comm", {})
        if not isinstance(comm, dict):
            raise ConfigError("平台运行快照 settings.comm 必须是对象")
        # 平台值一次读入内存后仅在当前任务使用，绝不合并进程环境或本地 .env。
        raw_runtime_variables = settings.get("runtime_variables") or {}
        if not isinstance(raw_runtime_variables, dict):
            raise ConfigError("平台运行快照 settings.runtime_variables 必须是对象")
        runtime_session = {
            runtime_key: comm[comm_key]
            for runtime_key, comm_key in {
                "access_token": "auth_token",
                "user_id": "user_id",
                "device_id": "device_id",
            }.items()
            if comm.get(comm_key) not in (None, "")
        }
        # materialize 兼容层可能把 Secret 以平台逻辑键保存在 runtime_variables；
        # 此处只从快照内存规范化，绝不读取同名进程环境变量。
        for runtime_key, platform_key in SESSION_ENV_MAPPING.items():
            if raw_runtime_variables.get(platform_key) not in (None, ""):
                runtime_session[runtime_key] = deepcopy(
                    raw_runtime_variables[platform_key]
                )
        for runtime_key, comm_key in (
            ("access_token", "auth_token"),
            ("user_id", "user_id"),
            ("device_id", "device_id"),
        ):
            if comm.get(comm_key) in (None, "") and runtime_session.get(runtime_key) not in (
                None,
                "",
            ):
                comm[comm_key] = deepcopy(runtime_session[runtime_key])
        settings["runtime_session"] = runtime_session
        managed_platform_keys = {
            *SESSION_ENV_MAPPING.values(),
            *ADMIN_ENV_MAPPING.values(),
        }
        normalized_variables = {
            key: deepcopy(value)
            for key, value in raw_runtime_variables.items()
            if key not in managed_platform_keys
        }
        for runtime_key, platform_key in ADMIN_ENV_MAPPING.items():
            if raw_runtime_variables.get(platform_key) not in (None, ""):
                normalized_variables[runtime_key] = deepcopy(
                    raw_runtime_variables[platform_key]
                )
        settings["runtime_variables"] = normalized_variables
        if not settings.get("gateway_base_url"):
            raise ConfigError("平台运行快照缺少 gateway_base_url")
        if require_secrets and not comm.get("device_id"):
            raise ConfigError("平台运行快照缺少必填设备标识 comm.device_id")
        return settings

    if snapshot_file is not None:
        raise ConfigError("local 配置源不得同时传入平台快照文件")

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

    # 平台模式仅使用任务内存快照，不读取旧 .env.platform。
    # 旧根 .env 只属于 Truthy local 兼容窗口；Dating 和后续项目即使 local
    # 调试也不能继承 Truthy 会话或 Admin 凭证。
    env_values = (
        load_dotenv_values(root / ".env")
        if project_id in (None, "truthy")
        and os.getenv("API_AUTOTEST_SESSION_PROVIDER", "dotenv") != "platform"
        else {}
    )
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
