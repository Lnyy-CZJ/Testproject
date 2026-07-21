"""Gateway 顶层与业务子响应双层断言测试。"""

import pytest

from framework.assertions.gateway_assert import (
    assert_business_error,
    assert_business_success,
    assert_gateway_received,
)
from framework.models.envelope import GatewayResponse


def _response(*, success: bool = True, code: int = 0, error: str = "") -> GatewayResponse:
    return GatewayResponse.model_validate(
        {
            "code": 0,
            "message": "OK",
            "request_id": "gw-1",
            "trace_id": "trace-1",
            "responses": [
                {
                    "id": "req_0",
                    "code": code,
                    "success": success,
                    "business_error_code": error,
                    "data": {"content_version": "v1"},
                }
            ],
            "http_status": 200,
        }
    )


def test_gateway_received_checks_http_layer_only() -> None:
    response = _response(success=False, code=301002, error="UNAUTHENTICATED")

    assert_gateway_received(response)


def test_business_success_returns_data_and_checks_required_fields() -> None:
    data = assert_business_success(_response(), required_data_fields={"content_version"})

    assert data == {"content_version": "v1"}
    with pytest.raises(AssertionError, match="缺少字段"):
        assert_business_success(_response(), required_data_fields={"missing"})


def test_business_error_matches_string_and_numeric_codes() -> None:
    sub_response = assert_business_error(
        _response(success=False, code=301002, error="UNAUTHENTICATED"),
        "UNAUTHENTICATED",
        expected_code=301002,
    )

    assert sub_response.success is False


def test_gateway_received_rejects_non_2xx_status() -> None:
    response = _response()
    response.http_status = 503

    with pytest.raises(AssertionError, match="HTTP 状态"):
        assert_gateway_received(response)


def test_assertion_errors_include_traceable_context_and_actual_ids() -> None:
    response = _response(success=False, code=301002, error="UNAUTHENTICATED")

    with pytest.raises(AssertionError) as failure:
        assert_business_success(response)
    message = str(failure.value)
    assert "gw-1" in message
    assert "trace-1" in message
    assert "req_0" in message
    assert "301002" in message

    with pytest.raises(AssertionError, match=r"actual_ids=\['req_0'\]"):
        assert_business_success(response, "missing")
