"""V1.3 API 定义加载、校验与可执行 case 组装工具。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from utils.custom.config_loader import ConfigError, load_yaml


class ApiConfigError(ValueError):
    """表示 API 定义缺失、重复或格式不合法。"""


_ALLOWED_ROOT_FIELDS = {
    "id", "name", "credential_profile", "request", "transport"
}
_ALLOWED_REQUEST_FIELDS = {"service_name", "method_name"}
_ALLOWED_TRANSPORT_FIELDS = {
    "target",
    "comm",
    "requires_session",
    "envelope",
    "params_container",
    "reason",
    "bearer_token_variable",
}
_CREDENTIAL_PROFILE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def _require_non_empty_string(
    data: dict[str, Any],
    field: str,
    scope: str,
) -> str:
    """读取并校验必填非空字符串。

    功能说明:
        统一处理 API ID、名称和 Gateway 路由字段，确保错误消息包含来源范围。

    参数说明:
        data: 字段所属对象。
        field: 要读取的字段名。
        scope: 用于错误定位的 API 文件或 request 范围。

    返回值:
        去除首尾空白后的字符串。

    异常说明:
        ApiConfigError: 字段缺失、不是字符串或只包含空白时抛出。
    """
    if field not in data:
        raise ApiConfigError(f"{scope} 缺少 {field}")
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        raise ApiConfigError(f"{scope}.{field} 必须为非空字符串")
    return value.strip()


def _reject_unexpected_fields(
    data: dict[str, Any],
    allowed_fields: set[str],
    scope: str,
) -> None:
    """拒绝 API 定义中的测试数据或其他未声明字段。

    参数说明:
        data: 待校验对象。
        allowed_fields: 当前层级允许出现的字段集合。
        scope: 错误消息中的文件或对象范围。

    返回值:
        无。字段全部合法时正常返回。

    异常说明:
        ApiConfigError: 出现 V1.3 API 模型未允许的字段时抛出。
    """
    unexpected = sorted(set(data) - allowed_fields)
    if unexpected:
        fields = ", ".join(unexpected)
        raise ApiConfigError(f"{scope} 包含禁止字段: {fields}")


def _validate_api_content(
    content: dict[str, Any],
    file_name: str,
) -> dict[str, Any]:
    """校验单个 API YAML 的字段，不在此阶段校验文件名一致性。

    参数说明:
        content: ``load_yaml`` 返回的 API 根对象。
        file_name: 当前 API 文件名，用于错误定位。

    返回值:
        经过深拷贝和字符串规范化的 API 定义。

    异常说明:
        ApiConfigError: 必填字段、字段类型或允许字段不符合 V1.3 模型时抛出。
    """
    scope = f"API 定义文件 {file_name}"
    _reject_unexpected_fields(content, _ALLOWED_ROOT_FIELDS, scope)

    api_id = _require_non_empty_string(content, "id", scope)
    name = _require_non_empty_string(content, "name", scope)
    credential_profile = _require_non_empty_string(
        content, "credential_profile", scope
    )
    if not _CREDENTIAL_PROFILE_PATTERN.fullmatch(credential_profile):
        raise ApiConfigError(
            f"{scope}.credential_profile 必须是合法逻辑 Profile ID"
        )
    request = content.get("request")
    if not isinstance(request, dict):
        if "request" not in content:
            raise ApiConfigError(f"{scope} 缺少 request")
        raise ApiConfigError(f"{scope}.request 必须是对象")

    request_scope = f"API {api_id}.request"
    _reject_unexpected_fields(request, _ALLOWED_REQUEST_FIELDS, request_scope)
    service_name = _require_non_empty_string(
        request,
        "service_name",
        request_scope,
    )
    method_name = _require_non_empty_string(
        request,
        "method_name",
        request_scope,
    )
    definition = {
        "id": api_id,
        "name": name,
        "credential_profile": credential_profile,
        "request": {
            "service_name": service_name,
            "method_name": method_name,
        },
    }
    transport = content.get("transport")
    if transport is None:
        return definition
    transport_scope = f"API {api_id}.transport"
    if not isinstance(transport, dict):
        raise ApiConfigError(f"{transport_scope} 必须是对象")
    _reject_unexpected_fields(transport, _ALLOWED_TRANSPORT_FIELDS, transport_scope)
    target = _require_non_empty_string(transport, "target", transport_scope)
    normalized_transport: dict[str, Any] = {"target": target}
    if "comm" in transport:
        if not isinstance(transport["comm"], dict):
            raise ApiConfigError(f"{transport_scope}.comm 必须是对象")
        normalized_transport["comm"] = deepcopy(transport["comm"])
    if "requires_session" in transport:
        if not isinstance(transport["requires_session"], bool):
            raise ApiConfigError(f"{transport_scope}.requires_session 必须是布尔值")
        normalized_transport["requires_session"] = transport["requires_session"]
    envelope = transport.get("envelope")
    if envelope is not None:
        if envelope != "root_single":
            raise ApiConfigError(
                f"{transport_scope}.envelope 目前只支持 root_single"
            )
        normalized_transport["envelope"] = envelope
    for field in ("params_container", "reason", "bearer_token_variable"):
        if field not in transport:
            continue
        value = transport[field]
        if not isinstance(value, str) or not value.strip():
            raise ApiConfigError(f"{transport_scope}.{field} 必须为非空字符串")
        normalized_transport[field] = value.strip()
    if "params_container" in normalized_transport and envelope != "root_single":
        raise ApiConfigError(
            f"{transport_scope}.params_container 只能用于 root_single"
        )
    if "reason" in normalized_transport and envelope != "root_single":
        raise ApiConfigError(f"{transport_scope}.reason 只能用于 root_single")
    variable = normalized_transport.get("bearer_token_variable")
    if variable and not _VARIABLE_NAME_PATTERN.fullmatch(str(variable)):
        raise ApiConfigError(
            f"{transport_scope}.bearer_token_variable 必须是合法变量名"
        )
    definition["transport"] = normalized_transport
    return definition


def _relative_source(path: Path, project_root: Path) -> str:
    """生成稳定的项目相对来源路径，供配置错误和诊断信息使用。"""
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        # 测试或调用方传入项目外路径时保留原路径，不掩盖有效定义。
        return path.as_posix()


def _safe_api_paths(project_root: Path) -> list[Path]:
    """枚举当前项目 API YAML，拒绝符号链接和 resolve 后越界的文件。"""
    directory = project_root / "data" / "apis"
    boundary = project_root.resolve()
    paths = sorted(directory.glob("*.yaml"))
    for path in paths:
        if path.is_symlink():
            raise ApiConfigError(f"API 定义禁止使用符号链接: {path.name}")
        try:
            path.resolve().relative_to(boundary)
        except ValueError as exc:
            raise ApiConfigError(f"API 定义路径越界: {path.name}") from exc
    return paths


def load_api_definitions(project_root: Path) -> dict[str, dict[str, Any]]:
    """加载并校验项目中的全部 V1.3 API 定义。

    功能说明:
        扫描 ``data/apis/*.yaml``，校验最小 API 模型、重复 ID 以及 ID 与
        文件名的一致性，返回供 Cases、Flows 和会话管理共同使用的注册表。

    参数说明:
        project_root: 项目根目录，API 定义固定从其 ``data/apis`` 读取。

    返回值:
        以 API ID 为 key 的定义字典；每项额外包含只用于定位的 ``_source``。

    异常说明:
        ApiConfigError: API 目录为空、YAML 无效、字段非法、ID 重复或文件名
        与 ID 不一致时抛出。异常在任何网络请求发生前产生。
    """
    apis_directory = project_root / "data" / "apis"
    api_paths = _safe_api_paths(project_root)
    if not api_paths:
        raise ApiConfigError(f"未找到 API 定义: {apis_directory}")

    # 第一遍先校验内容和重复 ID，使重复定义不会被文件名错误提前遮挡。
    pending: list[tuple[Path, dict[str, Any]]] = []
    sources_by_id: dict[str, Path] = {}
    for api_path in api_paths:
        try:
            content = load_yaml(api_path)
        except ConfigError as exc:
            raise ApiConfigError(
                f"API 定义文件 {api_path.name} 加载失败: {exc}"
            ) from exc
        definition = _validate_api_content(content, api_path.name)
        api_id = definition["id"]
        if api_id in sources_by_id:
            first_source = sources_by_id[api_id].name
            raise ApiConfigError(
                f"存在重复 API id: {api_id}；"
                f"来源: {first_source}, {api_path.name}"
            )
        sources_by_id[api_id] = api_path
        pending.append((api_path, definition))

    definitions: dict[str, dict[str, Any]] = {}
    for api_path, definition in pending:
        api_id = definition["id"]
        if api_path.stem != api_id:
            raise ApiConfigError(
                f"API 定义文件 {api_path.name} 的 id 必须与文件名一致，"
                f"实际为 {api_id}"
            )
        item = deepcopy(definition)
        item["_source"] = _relative_source(api_path, project_root)
        definitions[api_id] = item
    return definitions


def build_execution_case(
    api_definition: dict[str, Any],
    params: dict[str, Any],
    assertions: dict[str, Any],
    extract: dict[str, str] | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """根据 API 路由和测试数据组装 GatewayApi 可执行 case。

    功能说明:
        保持现有 ``GatewayApi`` 的输入协议不变，使加载层完成 V1.3 数据拆分，
        执行层无需理解 API、Cases 或 Flow YAML。所有输入均深拷贝，避免一次
        运行中的变量解析或修改污染注册表和其他用例。

    参数说明:
        api_definition: ApiLoader 返回的单个 API 定义。
        params: 当前单接口 case 或 Flow step 的完整业务参数。
        assertions: 当前 case 或 Flow step 的完整断言。
        extract: 可选响应提取规则，以业务响应 data 为根。
        name: 可选执行名称；未提供时使用 API 中文名称。

    返回值:
        包含 name、request、assert 和 extract 的 GatewayApi 可执行字典。

    异常说明:
        ApiConfigError: API 路由无效，或 params、assertions、extract、name
        类型不符合可执行 case 约定时抛出。
    """
    if not isinstance(api_definition, dict):
        raise ApiConfigError("组装可执行 case 时 API 定义必须是对象")
    api_id = str(api_definition.get("id") or "unknown")
    request = api_definition.get("request")
    if not isinstance(request, dict):
        raise ApiConfigError(f"API {api_id}.request 必须是对象")
    service_name = _require_non_empty_string(
        request,
        "service_name",
        f"API {api_id}.request",
    )
    method_name = _require_non_empty_string(
        request,
        "method_name",
        f"API {api_id}.request",
    )
    if not isinstance(params, dict):
        raise ApiConfigError(f"API {api_id} 的 params 必须是对象")
    if not isinstance(assertions, dict):
        raise ApiConfigError(f"API {api_id} 的 assertions 必须是对象")
    if extract is not None and not isinstance(extract, dict):
        raise ApiConfigError(f"API {api_id} 的 extract 必须是对象")

    case_name = name if name is not None else api_definition.get("name")
    if not isinstance(case_name, str) or not case_name.strip():
        raise ApiConfigError(f"API {api_id} 的执行名称必须为非空字符串")
    execution_case = {
        "name": case_name.strip(),
        "request": {
            "service_name": service_name,
            "method_name": method_name,
            "params": deepcopy(params),
        },
        "assert": deepcopy(assertions),
        "extract": deepcopy(extract or {}),
    }
    # 旧 API 没有传输覆盖时不添加该字段，保持既有可执行 case 数据结构不变。
    if api_definition.get("transport"):
        execution_case["transport"] = deepcopy(api_definition["transport"])
    return execution_case
