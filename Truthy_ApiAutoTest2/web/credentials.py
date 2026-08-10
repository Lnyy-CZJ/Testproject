"""凭证与配置预检。

功能说明:
    任务提交前完成两级预检（均为本地检查，不发请求）：
    1. 配置合并级：只读调用框架 ``load_settings(env)``，复用其对
       ``config/settings.yaml``、``config/env/<env>.yaml``、``.env`` 与
       进程环境变量的真实合并逻辑；不额外要求 DEVICE_ID 必须来自 .env。
    2. 任务级：解析实际选择的 Flow，目标包含 Admin 审计步骤时校验
       ``ADMIN_SESSION_TOKEN``、``ADMIN_OPERATOR_ID``、``ADMIN_OPERATOR_NAME``，
       缺失时只返回字段名，不返回字段值。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.custom.config_loader import (
    ADMIN_ENV_MAPPING,
    ConfigError,
    load_settings,
    load_yaml,
)

# 稳定错误码：配置合并级缺失。
CREDENTIALS_MISSING = "CREDENTIALS_MISSING"
# 稳定错误码：.env 挂载位置被目录占据（Docker bind mount 误创建）。
CREDENTIAL_FILE_INVALID = "CREDENTIAL_FILE_INVALID"
# 稳定错误码：任务目标需要 Admin 凭证但缺失。
ADMIN_CREDENTIALS_MISSING = "ADMIN_CREDENTIALS_MISSING"

# Scenario 中引用 Admin 运行时变量的模板占位符前缀。
_ADMIN_PLACEHOLDER = "{{admin_"


def check_env_file(project_root: Path) -> str | None:
    """检查 .env 位置是否为可写普通文件语义。

    功能说明:
        平台模式下宿主 ``.env.platform`` 缺失时，Docker bind mount 可能在
        容器内创建同名目录；此时框架读写必然失败，应提前拒绝提交。

    返回值:
        正常返回 None；.env 位置被目录占据时返回 CREDENTIAL_FILE_INVALID。
    """
    env_path = Path(project_root) / ".env"
    if env_path.exists() and not env_path.is_file():
        return CREDENTIAL_FILE_INVALID
    return None


def check_base_config(
    env: str,
    project_root: Path,
) -> tuple[dict[str, Any] | None, str | None, str]:
    """执行配置合并级预检。

    参数说明:
        env: 环境名称，例如 ``test``。
        project_root: 项目根目录。

    返回值:
        ``(settings, error_code, message)``：预检通过时 settings 为合并后
        配置、error_code 为 None；失败时 settings 为 None，error_code 为
        CREDENTIAL_FILE_INVALID 或 CREDENTIALS_MISSING，message 为可读原因。
    """
    file_error = check_env_file(project_root)
    if file_error:
        return None, file_error, ".env 位置被目录占据，无法读写凭证文件"
    try:
        settings = load_settings(env, project_root=Path(project_root))
    except ConfigError as exc:
        return None, CREDENTIALS_MISSING, str(exc)
    return settings, None, ""


def missing_admin_keys(settings: dict[str, Any]) -> list[str]:
    """从合并后配置中找出缺失的 Admin 凭证字段名。

    参数说明:
        settings: ``load_settings`` 返回的合并配置。

    返回值:
        缺失的环境变量名列表（如 ADMIN_SESSION_TOKEN）；全部就绪返回空列表。
    """
    provided = settings.get("runtime_variables") or {}
    return [
        env_key
        for runtime_key, env_key in ADMIN_ENV_MAPPING.items()
        if not provided.get(runtime_key)
    ]


def _scenario_requires_admin(project_root: Path, flow_name: str) -> bool:
    """判断单个 Flow 的 Scenario 是否引用 Admin 运行时变量。

    功能说明:
        直接读取 ``data/scenarios/<flow>.yaml`` 原文检索 ``{{admin_``
        占位符；文件缺失或不可读按不需要处理，交由 Flow 加载校验暴露。
    """
    scenario_path = (
        Path(project_root) / "data" / "scenarios" / f"{flow_name}.yaml"
    )
    try:
        return _ADMIN_PLACEHOLDER in scenario_path.read_text(encoding="utf-8")
    except OSError:
        return False


def target_requires_admin(
    project_root: Path,
    run_type: str,
    flow: str | None,
    tag: str | None,
) -> bool:
    """判断本次任务目标是否包含 Admin 审计步骤。

    参数说明:
        project_root: 项目根目录。
        run_type: ``all|single|flow``。
        flow: run_type=flow 时必填的 Flow 名称。
        tag: 可选标签表达式；带标签时只检查标签命中的 Flow。

    返回值:
        目标包含 Admin 审计步骤返回 True。single 入口不含 Flow，恒为 False。
    """
    if run_type == "single":
        return False

    flows_directory = Path(project_root) / "data" / "flows"
    if run_type == "flow" and flow:
        return _scenario_requires_admin(project_root, Path(flow).stem)

    # all（可选 tag 过滤）：逐个读取 Flow 的 tags 判定是否命中。
    for flow_path in sorted(flows_directory.glob("*.yaml")):
        if tag:
            try:
                flow_tags = load_yaml(flow_path).get("tags") or []
            except ConfigError:
                flow_tags = []
            if tag not in [str(item) for item in flow_tags]:
                continue
        if _scenario_requires_admin(project_root, flow_path.stem):
            return True
    return False


def list_envs(project_root: Path) -> list[str]:
    """列出 ``config/env/`` 下可用环境名称（供页面下拉框）。"""
    env_directory = Path(project_root) / "config" / "env"
    if not env_directory.is_dir():
        return []
    return sorted(path.stem for path in env_directory.glob("*.yaml"))


def list_flows(project_root: Path) -> list[str]:
    """列出 ``data/flows/`` 下可用 Flow 名称（供页面下拉框）。"""
    flows_directory = Path(project_root) / "data" / "flows"
    if not flows_directory.is_dir():
        return []
    return sorted(path.stem for path in flows_directory.glob("*.yaml"))


def credential_status(
    env: str,
    run_type: str,
    flow: str | None,
    tag: str | None,
    project_root: Path,
) -> dict[str, Any]:
    """汇总页面展示的凭证就绪状态（只含状态与字段名，不含值）。

    返回值:
        ``{"base_config": {"ready": bool, "message": str},
           "admin": {"required": bool, "ready": bool, "missing_fields": [...]}}``
    """
    settings, error_code, message = check_base_config(env, project_root)
    base_ready = error_code is None
    admin_required = False
    missing_fields: list[str] = []
    if base_ready and settings is not None:
        admin_required = target_requires_admin(project_root, run_type, flow, tag)
        if admin_required:
            missing_fields = missing_admin_keys(settings)
    return {
        "base_config": {
            "ready": base_ready,
            "message": "" if base_ready else message,
        },
        "admin": {
            "required": admin_required,
            "ready": base_ready and (not admin_required or not missing_fields),
            "missing_fields": missing_fields,
        },
    }
