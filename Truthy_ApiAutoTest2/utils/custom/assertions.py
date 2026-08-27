"""Gateway 分层响应断言工具。"""

from __future__ import annotations

from typing import Any

from utils.custom.runtime_context import RuntimeContext, RuntimeContextError


def _matches_declared_type(value: Any, declared_type: str) -> bool:
    """按 YAML 稳定类型名判断 JSON 值，避免 Python ``bool`` 被当成整数。"""

    if declared_type == "object":
        return isinstance(value, dict)
    if declared_type == "array":
        return isinstance(value, list)
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "boolean":
        return isinstance(value, bool)
    if declared_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared_type == "null":
        return value is None
    raise AssertionError(f"不支持的业务数据类型声明: {declared_type}")


def _assert_fields(actual: dict[str, Any], expected: dict[str, Any], scope: str) -> None:
    """逐项比较配置的期望字段，并提供带层级的失败信息。"""
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        assert actual_value == expected_value, (
            f"{scope}字段 {key} 断言失败: "
            f"期望 {expected_value!r}，实际 {actual_value!r}"
        )


def assert_gateway_response(response: Any, expected: dict[str, Any]) -> dict[str, Any]:
    """校验 HTTP、Gateway 顶层、业务子响应和必填 data 字段。

    参数说明:
        response: 兼容 requests.Response 的对象，需提供 status_code 和 json()。
        expected: 用例 YAML 中的 ``assert`` 配置。

    返回值:
        目标业务子响应的 data 字典，方便未来用例继续使用。

    异常说明:
        AssertionError: 任一层级不符合期望、响应结构无效或字段不存在时抛出。
    """
    expected_status = expected.get("http_status", 200)
    assert response.status_code == expected_status, (
        f"HTTP 状态断言失败: 期望 {expected_status}，实际 {response.status_code}"
    )

    try:
        body = response.json()
    except (TypeError, ValueError) as exc:
        raise AssertionError("Gateway 响应不是有效 JSON") from exc
    assert isinstance(body, dict), "Gateway 响应 JSON 根节点必须是对象"

    _assert_fields(body, expected.get("gateway") or {}, "Gateway 顶层")
    responses = body.get("responses")
    assert isinstance(responses, list), "Gateway 响应缺少 responses 数组"

    expected_response = expected.get("response") or {}
    expected_id = expected_response.get("id", "req_0")
    target = next(
        (item for item in responses if isinstance(item, dict) and item.get("id") == expected_id),
        None,
    )
    assert target is not None, f"Gateway responses 中未找到 id={expected_id!r} 的子响应"
    _assert_fields(target, expected_response, "业务子响应")

    data = target.get("data") or {}
    assert isinstance(data, dict), "业务子响应 data 必须是对象"
    for field in expected.get("data_fields") or []:
        assert field in data, f"业务数据字段 {field} 不存在"
    for path, declared_type in (expected.get("data_types") or {}).items():
        normalized_path = path if str(path).startswith("$.") else f"$.{path}"
        try:
            actual_value = RuntimeContext.read_path(data, normalized_path)
        except RuntimeContextError as exc:
            # 类型契约属于响应断言的一部分，对调用方统一表现为 AssertionError，
            # 不把 RuntimeContext 的内部路径解析异常泄漏成不同失败语义。
            raise AssertionError(f"业务数据类型路径 {path} 不存在") from exc
        assert _matches_declared_type(actual_value, str(declared_type)), (
            f"业务数据路径 {path} 类型断言失败: "
            f"期望 {declared_type}，实际 {type(actual_value).__name__}"
        )
    return data


def assert_data_equals(data: dict[str, Any], expected: dict[str, Any]) -> None:
    """校验业务 data 中指定路径的值。

    参数说明:
        data: Gateway 目标子响应的 data 对象。
        expected: ``路径 -> 期望值`` 映射；路径可省略开头的 ``$.``。

    返回值:
        无。全部相等时正常返回。

    异常说明:
        AssertionError: 实际值与期望值不相等时抛出。
        RuntimeContextError: 路径不存在或格式错误时由路径读取器抛出。
    """
    for path, expected_value in expected.items():
        normalized_path = path if path.startswith("$.") else f"$.{path}"
        actual_value = RuntimeContext.read_path(data, normalized_path)
        assert actual_value == expected_value, (
            f"业务数据路径 {path} 断言失败: "
            f"期望 {expected_value!r}，实际 {actual_value!r}"
        )
