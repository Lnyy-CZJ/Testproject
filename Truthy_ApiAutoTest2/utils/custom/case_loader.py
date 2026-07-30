"""V1.3 单接口多 case YAML 的加载、校验与展开工具。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from utils.custom.api_loader import build_execution_case, load_api_definitions
from utils.custom.config_loader import ConfigError, load_yaml


class CaseConfigError(ValueError):
    """表示单接口 case 集合或具体 case 配置不合法。"""


_ALLOWED_COLLECTION_FIELDS = {"api", "cases"}
_ALLOWED_CASE_FIELDS = {
    "id",
    "name",
    "tags",
    "request",
    "assert",
    "extract",
}
_ALLOWED_REQUEST_FIELDS = {"params"}


def _require_non_empty_string(
    data: dict[str, Any],
    field: str,
    scope: str,
) -> str:
    """读取 case 必填字符串，并生成包含文件和 case 范围的错误。

    参数说明:
        data: 字段所属对象。
        field: 需要读取的字段名。
        scope: 用于错误定位的文件或 case 描述。

    返回值:
        去除首尾空白后的字段值。

    异常说明:
        CaseConfigError: 字段缺失、为空或不是字符串时抛出。
    """
    value = data.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise CaseConfigError(f"{scope} 缺少 {field}")
    if not isinstance(value, str):
        raise CaseConfigError(f"{scope}.{field} 必须为非空字符串")
    return value.strip()


def _reject_unexpected_fields(
    data: dict[str, Any],
    allowed_fields: set[str],
    scope: str,
) -> None:
    """拒绝 V1.3 case 模型没有声明的字段。

    参数说明:
        data: 待校验字典。
        allowed_fields: 当前层级允许的字段。
        scope: 错误消息中的配置范围。

    返回值:
        无。字段合法时正常返回。

    异常说明:
        CaseConfigError: 出现旧格式或未支持字段时抛出。
    """
    unexpected = sorted(set(data) - allowed_fields)
    if unexpected:
        names = ", ".join(unexpected)
        raise CaseConfigError(f"{scope} 包含不支持字段: {names}")


def _validate_tags(value: Any, scope: str) -> list[str]:
    """校验并复制当前 case 的标签数组。"""
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(tag, str) or not tag.strip() for tag in value
    ):
        raise CaseConfigError(f"{scope}.tags 必须是非空字符串数组")
    return [tag.strip() for tag in value]


def _validate_extract(value: Any, scope: str) -> dict[str, str]:
    """校验可选提取映射的基本类型，具体路径由运行时读取器继续校验。"""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CaseConfigError(f"{scope}.extract 必须是对象")
    for variable_name, path in value.items():
        if (
            not isinstance(variable_name, str)
            or not variable_name.strip()
            or not isinstance(path, str)
            or not path.strip()
        ):
            raise CaseConfigError(
                f"{scope}.extract 的变量名和路径必须是非空字符串"
            )
    return deepcopy(value)


def _expand_collection(
    case_path: Path,
    collection: dict[str, Any],
    api_definitions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """校验并展开一个接口的 case 集合。

    参数说明:
        case_path: 当前 case YAML 路径。
        collection: YAML 根对象。
        api_definitions: ApiLoader 返回的完整注册表。

    返回值:
        当前文件内按声明顺序展开的单接口用例列表。

    异常说明:
        CaseConfigError: 文件、API 引用、case ID 或具体字段不符合设计时抛出。
    """
    file_scope = f"case 文件 {case_path.name}"
    _reject_unexpected_fields(
        collection,
        _ALLOWED_COLLECTION_FIELDS,
        file_scope,
    )
    api_id = _require_non_empty_string(collection, "api", file_scope)
    if api_id not in api_definitions:
        raise CaseConfigError(
            f"{file_scope} 引用的 API 不存在: {api_id}"
        )
    if case_path.stem != api_id:
        raise CaseConfigError(
            f"{file_scope} 的 api 为 {api_id}，必须与文件名一致"
        )

    configured_cases = collection.get("cases")
    if not isinstance(configured_cases, list) or not configured_cases:
        raise CaseConfigError(f"{file_scope}.cases 必须是非空列表")

    expanded: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    for position, case in enumerate(configured_cases, start=1):
        position_scope = f"{file_scope} 第 {position} 个 case"
        if not isinstance(case, dict):
            raise CaseConfigError(f"{position_scope} 必须是对象")
        _reject_unexpected_fields(case, _ALLOWED_CASE_FIELDS, position_scope)

        case_id = _require_non_empty_string(case, "id", position_scope)
        case_scope = f"{file_scope} case {case_id}"
        if case_id in case_ids:
            raise CaseConfigError(
                f"{file_scope} 存在重复 case id: {case_id}"
            )
        case_ids.add(case_id)
        name = _require_non_empty_string(case, "name", case_scope)
        tags = _validate_tags(case.get("tags"), case_scope)

        request = case.get("request")
        if not isinstance(request, dict):
            if "request" not in case:
                raise CaseConfigError(f"{case_scope} 缺少 request")
            raise CaseConfigError(f"{case_scope}.request 必须是对象")
        _reject_unexpected_fields(
            request,
            _ALLOWED_REQUEST_FIELDS,
            f"{case_scope}.request",
        )
        if "params" not in request:
            raise CaseConfigError(f"{case_scope}.request 缺少 params")
        params = request["params"]
        if not isinstance(params, dict):
            raise CaseConfigError(f"{case_scope}.request.params 必须是对象")

        assertions = case.get("assert")
        if not isinstance(assertions, dict):
            if "assert" not in case:
                raise CaseConfigError(f"{case_scope} 缺少 assert")
            raise CaseConfigError(f"{case_scope}.assert 必须是对象")
        extract = _validate_extract(case.get("extract"), case_scope)

        full_id = f"{api_id}::{case_id}"
        expanded.append(
            {
                "id": full_id,
                "api_id": api_id,
                "case_id": case_id,
                "name": name,
                "tags": tags,
                "execution_case": build_execution_case(
                    api_definitions[api_id],
                    params,
                    assertions,
                    extract=extract,
                    name=name,
                ),
            }
        )
    return expanded


def load_single_cases(
    project_root: Path,
    selected_case_ids: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """加载、校验并展开项目中的 V1.3 单接口用例。

    功能说明:
        扫描 ``data/cases/*.yaml``，通过 ApiLoader 解析接口路由，把每个
        ``cases`` 元素组装为独立的 GatewayApi 可执行对象。函数不生成 pytest
        marks，也不执行网络请求。

    参数说明:
        project_root: 项目根目录。
        selected_case_ids: 可选完整 ID 集合，格式为 ``ApiId::case_id``；
            空元组表示返回全部用例。

    返回值:
        按文件名和 YAML 声明顺序排列的单接口用例列表。

    异常说明:
        ApiConfigError: API 注册表不合法时由 ApiLoader 抛出。
        CaseConfigError: case YAML、API 引用、具体字段或筛选 ID 不合法时抛出。
    """
    api_definitions = load_api_definitions(project_root)
    cases_directory = project_root / "data" / "cases"
    case_paths = sorted(cases_directory.glob("*.yaml"))

    expanded: list[dict[str, Any]] = []
    for case_path in case_paths:
        try:
            collection = load_yaml(case_path)
        except ConfigError as exc:
            raise CaseConfigError(
                f"case 文件 {case_path.name} 加载失败: {exc}"
            ) from exc
        expanded.extend(
            _expand_collection(
                case_path,
                collection,
                api_definitions,
            )
        )

    if not selected_case_ids:
        return deepcopy(expanded)

    requested = set(selected_case_ids)
    available = [case["id"] for case in expanded]
    missing = sorted(requested - set(available))
    if missing:
        missing_text = ", ".join(missing)
        available_text = ", ".join(available) or "无"
        raise CaseConfigError(
            f"指定的 case ID 不存在: {missing_text}；"
            f"可用 case ID: {available_text}"
        )
    return deepcopy([case for case in expanded if case["id"] in requested])
