"""Home GetHomeContent 离线与显式安全联调契约。"""

from pathlib import Path
from typing import Any

import pytest

from framework.assertions.gateway_assert import assert_business_success
from framework.data.loader import load_case_data
from framework.models.envelope import GatewayResponse
from services.home_service import HomeService


CASES = load_case_data(Path(__file__).parents[1] / "data/cases/home_content.yaml")


class _StubGatewayClient:
    """返回固定首页契约响应并记录 Service 层调用。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke(self, service_name: str, method_name: str, params: dict[str, Any], **kwargs: Any) -> GatewayResponse:
        self.calls.append(
            {
                "service_name": service_name,
                "method_name": method_name,
                "params": params,
                **kwargs,
            }
        )
        response = GatewayResponse.model_validate(
            {
                "code": 0,
                "message": "OK",
                "request_id": "gw-home-1",
                "trace_id": "trace-home-1",
                "responses": [
                    {
                        "id": "req_0",
                        "code": 0,
                        "message": "OK",
                        "success": True,
                        "data": {
                            "search_examples": [],
                            "user_stories": [],
                            "cache_ttl_seconds": 300,
                            "content_version": "offline-v1",
                        },
                    }
                ],
            }
        )
        response.http_status = 200
        return response


@pytest.mark.contract
@pytest.mark.smoke
@pytest.mark.p0
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_get_home_content_offline_contract(case: dict[str, Any]) -> None:
    client = _StubGatewayClient()
    service = HomeService(client)

    response = service.get_home_content(locale=case["params"]["locale"])
    data = assert_business_success(
        response,
        required_data_fields=case["expected"]["required_fields"],
    )

    assert client.calls[0]["service_name"] == "tool.people_insight.HomeService"
    assert client.calls[0]["method_name"] == "GetHomeContent"
    assert client.calls[0]["auth_token"] is None
    assert data["cache_ttl_seconds"] > 0


@pytest.mark.contract
@pytest.mark.live_safe
@pytest.mark.smoke
@pytest.mark.p0
def test_get_home_content_live_safe(home_service: HomeService) -> None:
    response = home_service.get_home_content(locale="en-US")

    assert_business_success(
        response,
        required_data_fields={
            "search_examples",
            "user_stories",
            "cache_ttl_seconds",
            "content_version",
        },
    )
