"""Gateway 双层响应断言。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from framework.models.envelope import GatewayResponse, GatewaySubResponse


def _response_context(response: GatewayResponse) -> str:
    """返回不含敏感载荷的 Gateway 追踪上下文。"""
    return f"request_id={response.request_id}, trace_id={response.trace_id}"


def assert_gateway_received(response: GatewayResponse) -> None:
    """断言 Gateway 已通过 HTTP 2xx 返回可追踪信封。

    功能说明:
        校验 HTTP 层已收到可追踪 Gateway 信封，不判断子响应业务结果。
    参数说明:
        response: 已完成 Pydantic 解析的 Gateway 顶层响应。
    返回值:
        断言通过时返回 ``None``，不判断业务子响应是否成功。
    异常说明:
        HTTP 状态非 2xx，或追踪字段、子响应列表缺失时抛出 ``AssertionError``。
    """
    context = _response_context(response)
    assert response.http_status is not None and 200 <= response.http_status < 300, (
        f"Gateway HTTP 状态异常: {response.http_status}; {context}"
    )
    assert response.request_id, f"Gateway 响应缺少 request_id; {context}"
    assert response.trace_id, f"Gateway 响应缺少 trace_id; {context}"
    assert response.responses, f"Gateway 响应缺少业务子响应; {context}"


def _find_sub_response(response: GatewayResponse, request_id: str) -> GatewaySubResponse:
    """按请求 ID 查找子响应，避免依赖响应数组位置。"""
    for item in response.responses:
        if item.id == request_id:
            return item
    actual_ids = [item.id for item in response.responses]
    raise AssertionError(
        f"Gateway 响应中不存在子请求: expected_id={request_id}, actual_ids={actual_ids}; "
        f"{_response_context(response)}"
    )


def assert_business_success(
    response: GatewayResponse,
    request_id: str = "req_0",
    *,
    required_data_fields: Iterable[str] = (),
) -> Any:
    """断言指定 Gateway 子请求业务成功。

    功能说明:
        完成 Gateway 顶层断言后校验指定子请求业务成功和最小字段。
    参数说明:
        response: Gateway 顶层响应。
        request_id: 子请求 ID，默认单请求信封的 ``req_0``。
        required_data_fields: ``data`` 对象必须包含的最小字段集合。
    返回值:
        目标子响应的 ``data``。
    异常说明:
        顶层、成功标志、数字码或必需数据字段不符合预期时抛出 ``AssertionError``。
    """
    assert_gateway_received(response)
    item = _find_sub_response(response, request_id)
    context = f"{_response_context(response)}, sub_request_id={item.id}, code={item.code}"
    assert item.success is True, (
        f"业务请求失败: {item.business_error_code or item.message}; {context}"
    )
    assert item.code == 0, f"业务成功响应 code 应为 0，实际为 {item.code}; {context}"
    required = set(required_data_fields)
    if required:
        assert isinstance(item.data, dict), f"业务成功响应 data 必须是对象; {context}"
        missing = required.difference(item.data)
        assert not missing, f"业务成功响应 data 缺少字段: {sorted(missing)}; {context}"
    return item.data


def assert_business_error(
    response: GatewayResponse,
    expected_business_error_code: str,
    *,
    expected_code: int,
    request_id: str = "req_0",
) -> GatewaySubResponse:
    """断言指定 Gateway 子请求返回预期业务错误。

    功能说明:
        完成 Gateway 顶层断言后校验指定子请求返回预期业务错误。
    参数说明:
        response: Gateway 顶层响应。
        expected_business_error_code: 稳定的字符串业务错误码。
        expected_code: 对应数字错误码。
        request_id: 子请求 ID。
    返回值:
        匹配的业务子响应，便于补充场景断言。
    异常说明:
        顶层未接收、业务意外成功或错误码不匹配时抛出 ``AssertionError``。
    """
    assert_gateway_received(response)
    item = _find_sub_response(response, request_id)
    context = f"{_response_context(response)}, sub_request_id={item.id}, code={item.code}"
    assert item.success is False, f"预期业务失败，实际 success=true; {context}"
    assert item.business_error_code == expected_business_error_code, (
        f"业务错误码不匹配: expected={expected_business_error_code}, "
        f"actual={item.business_error_code}; {context}"
    )
    assert item.code == expected_code, (
        f"数字错误码不匹配: expected={expected_code}, actual={item.code}; {context}"
    )
    return item
