"""TC-005/006/016～023 搜索主链路与边界的离线契约。"""

from collections.abc import Iterable
from typing import Any

import pytest

from framework.assertions.gateway_assert import (
    assert_business_error,
    assert_business_success,
    assert_gateway_received,
)
from framework.models.envelope import GatewayResponse, GatewaySubResponse
from framework.waiters.task_waiter import TaskWaiter
from services.search_service import SearchService


def _response(
    *,
    data: dict[str, Any] | None = None,
    error_code: str = "",
    numeric_code: int = 0,
) -> GatewayResponse:
    """构造顶层已接收、子响应可成功或失败的离线响应。"""
    response = GatewayResponse.model_validate(
        {
            "code": 0,
            "message": "OK",
            "request_id": "request-offline",
            "trace_id": "trace-offline",
            "responses": [
                {
                    "id": "req_0",
                    "code": numeric_code,
                    "message": "offline",
                    "success": not error_code,
                    "business_error_code": error_code,
                    "data": data,
                }
            ],
        }
    )
    response.http_status = 200
    return response


def _assert_unconfirmed_failure(response: GatewayResponse) -> GatewaySubResponse:
    """只断言文档未定义精确错误码场景确实业务失败且业务码非空。"""
    assert_gateway_received(response)
    item = response.responses[0]
    assert item.success is False
    assert item.code != 0
    assert item.business_error_code
    return item


class _Gateway:
    """按顺序返回响应并记录所有 Service 请求。"""

    def __init__(self, responses: Iterable[GatewayResponse]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def invoke(
        self, service_name: str, method_name: str, params: dict[str, Any], **kwargs: Any
    ) -> GatewayResponse:
        self.calls.append(
            {
                "service_name": service_name,
                "method_name": method_name,
                "params": params,
                **kwargs,
            }
        )
        return next(self.responses)


class _Clock:
    """无需真实等待的单调时钟。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _full_name_clues() -> list[dict[str, Any]]:
    """返回不含真人私密信息的公开演示线索。"""
    return [
        {"type": "FULL_NAME", "full_name_query": {"full_name": "Ada Lovelace"}}
    ]


@pytest.mark.contract
@pytest.mark.p0
@pytest.mark.search
@pytest.mark.async_task
def test_tc005_main_flow_waits_then_reads_owned_candidate_detail() -> None:
    gateway = _Gateway(
        [
            _response(data={"task_id": "task-5", "status": "QUEUED"}),
            _response(data={"task_id": "task-5", "status": "SEARCHING"}),
            _response(data={"task_id": "task-5", "status": "SUCCEEDED"}),
            _response(
                data={
                    "task_id": "task-5",
                    "items": [
                        {"candidate_id": "candidate-5", "display_name": "Ada Lovelace"}
                    ],
                    "next_page_token": "",
                    "empty_reason": "",
                }
            ),
            _response(
                data={
                    "task_id": "task-5",
                    "candidate_id": "candidate-5",
                    "candidate": {"candidate_id": "candidate-5"},
                }
            ),
        ]
    )
    service = SearchService(gateway)
    created = assert_business_success(
        service.create_intent_task(
            access_token="access",
            client_request_id="tc005-stable",
            match_strategy="UNION",
            clues=_full_name_clues(),
        ),
        required_data_fields={"task_id", "status"},
    )
    clock = _Clock()
    terminal = TaskWaiter(service, clock=clock, sleep=clock.sleep).wait(
        access_token="access", task_id=created["task_id"]
    )
    candidates = assert_business_success(
        service.list_task_candidates(
            access_token="access", task_id=terminal.data["task_id"]
        ),
        required_data_fields={"task_id", "items", "next_page_token", "empty_reason"},
    )
    candidate_id = candidates["items"][0]["candidate_id"]
    detail = assert_business_success(
        service.get_task_candidate_detail(
            access_token="access",
            task_id=terminal.data["task_id"],
            candidate_id=candidate_id,
        ),
        required_data_fields={"task_id", "candidate_id", "candidate"},
    )

    assert terminal.status == "SUCCEEDED"
    assert candidates["task_id"] == terminal.data["task_id"]
    assert detail["task_id"] == terminal.data["task_id"]
    assert detail["candidate_id"] == candidate_id


@pytest.mark.contract
@pytest.mark.p0
@pytest.mark.search
@pytest.mark.async_task
@pytest.mark.parametrize(
    "status,diagnostic_field",
    [("NO_RESULT", "no_result_reason"), ("FAILED", "error_code")],
)
def test_tc019_terminal_without_success_does_not_read_candidates_or_detail(
    status: str, diagnostic_field: str
) -> None:
    gateway = _Gateway(
        [
            _response(data={"task_id": "task-19", "status": "QUEUED"}),
            _response(
                data={
                    "task_id": "task-19",
                    "status": status,
                    diagnostic_field: "offline-diagnostic",
                }
            ),
        ]
    )
    service = SearchService(gateway)
    created = assert_business_success(
        service.create_intent_task(
            access_token="access",
            client_request_id=f"tc019-{status.lower()}",
            match_strategy="UNION",
            clues=_full_name_clues(),
        )
    )
    terminal = TaskWaiter(service, clock=lambda: 0).wait(
        access_token="access", task_id=created["task_id"]
    )

    assert terminal.status == status
    assert terminal.data[diagnostic_field] == "offline-diagnostic"
    assert [call["method_name"] for call in gateway.calls] == [
        "CreateIntentTask",
        "GetTask",
    ]


@pytest.mark.contract
@pytest.mark.p0
@pytest.mark.search
@pytest.mark.requires_entitlement
def test_tc016_unsubscribed_search_has_exact_documented_error() -> None:
    service = SearchService(
        _Gateway([_response(error_code="ENTITLEMENT_REQUIRED", numeric_code=301101)])
    )

    response = service.create_intent_task(
        access_token="unsubscribed-access",
        client_request_id="tc016-stable",
        match_strategy="UNION",
        clues=_full_name_clues(),
    )

    assert_business_error(
        response, "ENTITLEMENT_REQUIRED", expected_code=301101
    )


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.search
@pytest.mark.compatibility
def test_tc018_compatibility_create_start_and_duplicate_start() -> None:
    gateway = _Gateway(
        [
            _response(data={"task_id": "task-18", "status": "CREATED"}),
            _response(data={"task_id": "task-18", "status": "QUEUED"}),
            _response(error_code="OFFLINE_DUPLICATE_SENTINEL", numeric_code=399999),
        ]
    )
    service = SearchService(gateway)

    created = assert_business_success(
        service.create_intent(
            access_token="access",
            client_request_id="tc018-stable",
            match_strategy="UNION",
            clues=_full_name_clues(),
        )
    )
    started = assert_business_success(
        service.start_task(access_token="access", task_id=created["task_id"])
    )
    duplicate = service.start_task(access_token="access", task_id=created["task_id"])

    assert created["status"] == "CREATED"
    assert started["status"] == "QUEUED"
    _assert_unconfirmed_failure(duplicate)
    assert gateway.calls[1]["params"] == gateway.calls[2]["params"] == {
        "task_id": "task-18"
    }


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.search
def test_tc020_report_not_ready_returns_empty_candidate_list() -> None:
    service = SearchService(
        _Gateway(
            [
                _response(
                    data={
                        "task_id": "task-20",
                        "items": [],
                        "next_page_token": "",
                        "empty_reason": "REPORT_NOT_READY",
                    }
                )
            ]
        )
    )

    data = assert_business_success(
        service.list_task_candidates(access_token="access", task_id="task-20")
    )

    assert data["items"] == []
    assert data["empty_reason"] == "REPORT_NOT_READY"


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.search
def test_tc006_history_preserves_page_token_and_descending_sort_fields() -> None:
    gateway = _Gateway(
        [
            _response(
                data={
                    "items": [
                        {
                            "task_id": "task-new",
                            "query_type": "FULL_NAME",
                            "match_strategy": "UNION",
                            "clue_types": ["FULL_NAME"],
                            "display_query": "Ada Lovelace",
                            "status": "SUCCEEDED",
                            "entitlement_decision": "ALLOW",
                            "create_time": 200,
                            "update_time": 220,
                        },
                        {
                            "task_id": "task-old",
                            "query_type": "FULL_NAME",
                            "match_strategy": "UNION",
                            "clue_types": ["FULL_NAME"],
                            "display_query": "Grace Hopper",
                            "status": "SUCCEEDED",
                            "entitlement_decision": "ALLOW",
                            "create_time": 100,
                            "update_time": 120,
                        },
                    ],
                    "next_page_token": "page-2",
                }
            )
        ]
    )
    service = SearchService(gateway)

    history = assert_business_success(
        service.list_search_history(
            access_token="access",
            page_size=2,
            page_token="page-1",
            status_filter=["SUCCEEDED"],
        )
    )

    required = {
        "task_id",
        "query_type",
        "match_strategy",
        "clue_types",
        "display_query",
        "status",
        "entitlement_decision",
        "create_time",
        "update_time",
    }
    assert all(required <= item.keys() for item in history["items"])
    assert [item["create_time"] for item in history["items"]] == [200, 100]
    assert history["next_page_token"] == "page-2"
    assert gateway.calls[0]["params"] == {
        "page": {"page_size": 2, "page_token": "page-1"},
        "status_filter": ["SUCCEEDED"],
    }


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.search
@pytest.mark.idempotency
def test_tc021_same_client_request_id_keeps_shape_and_returns_same_task() -> None:
    gateway = _Gateway(
        [
            _response(data={"task_id": "same-task", "status": "QUEUED"}),
            _response(data={"task_id": "same-task", "status": "QUEUED"}),
        ]
    )
    service = SearchService(gateway)
    clues = _full_name_clues()

    first = assert_business_success(
        service.create_intent_task(
            access_token="access",
            client_request_id="tc021-stable",
            match_strategy="UNION",
            clues=clues,
        )
    )
    second = assert_business_success(
        service.create_intent_task(
            access_token="access",
            client_request_id="tc021-stable",
            match_strategy="UNION",
            clues=clues,
        )
    )

    assert first["task_id"] == second["task_id"]
    assert gateway.calls[0]["params"] == gateway.calls[1]["params"]
    assert gateway.calls[0]["client_request_id"] == "tc021-stable"
    assert gateway.calls[1]["client_request_id"] == "tc021-stable"


def _negative_cases() -> list[tuple[str, list[dict[str, Any]], str]]:
    """生成文档有明确边界、但无精确错误码的负向请求。"""
    full_name = _full_name_clues()[0]
    location = {"type": "LOCATION", "location_query": {"location": "London"}}
    photos = [
        {"type": "PHOTO", "photo_query": {"media_asset_id": f"media-{index}"}}
        for index in range(6)
    ]
    social_links = [
        {
            "type": "SOCIAL_LINK",
            "social_link_query": {"url": f"https://example.test/profile/{index}"},
        }
        for index in range(6)
    ]
    total = [full_name] + [
        {"type": "PHOTO", "photo_query": {"media_asset_id": f"media-total-{index}"}}
        for index in range(12)
    ]
    return [
        ("missing-full-name", [], "UNION"),
        ("duplicate-full-name", [full_name, full_name], "UNION"),
        ("duplicate-location", [full_name, location, location], "UNION"),
        ("too-many-photo", [full_name, *photos], "UNION"),
        ("too-many-social-link", [full_name, *social_links], "UNION"),
        ("too-many-total-clues", total, "UNION"),
        ("unsupported-match-strategy", [full_name], "INTERSECTION"),
    ]


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.search
@pytest.mark.parametrize("case_name,clues,match_strategy", _negative_cases())
def test_tc022_tc023_boundary_inputs_reach_api_without_local_rejection(
    case_name: str, clues: list[dict[str, Any]], match_strategy: str
) -> None:
    gateway = _Gateway(
        [_response(error_code=f"OFFLINE_{case_name.upper()}", numeric_code=399999)]
    )
    service = SearchService(gateway)

    response = service.create_intent_task(
        access_token="access",
        client_request_id=f"tc023-{case_name}",
        match_strategy=match_strategy,
        clues=clues,
    )

    _assert_unconfirmed_failure(response)
    assert gateway.calls[0]["params"]["clues"] is clues
    assert gateway.calls[0]["params"]["match_strategy"] == match_strategy
