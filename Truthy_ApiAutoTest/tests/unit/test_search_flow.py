"""阶段4精炼与补图生产流程协调器测试。"""

from collections.abc import Iterable
from typing import Any

import pytest

from framework.flows.search_flow import SearchFlow, SearchFlowError
from framework.models.envelope import GatewayResponse
from framework.waiters.task_waiter import TaskWaiter
from services.report_service import ReportService
from services.search_service import SearchService


def _response(
    data: Any = None, *, error_code: str = "", numeric_code: int = 0
) -> GatewayResponse:
    """构造流程测试的离线 Gateway 响应。"""
    response = GatewayResponse.model_validate(
        {
            "code": 0,
            "message": "OK",
            "request_id": "request-safe",
            "trace_id": "trace-safe",
            "responses": [
                {
                    "id": "req_0",
                    "code": numeric_code,
                    "message": "private payload must not leak",
                    "success": not error_code,
                    "business_error_code": error_code,
                    "data": data,
                }
            ],
        }
    )
    response.http_status = 200
    return response


class _Gateway:
    """按序响应并记录方法日志。"""

    def __init__(self, outcomes: Iterable[Any]) -> None:
        self.outcomes = iter(outcomes)
        self.calls: list[dict[str, Any]] = []

    def invoke(
        self, service_name: str, method_name: str, params: dict[str, Any], **kwargs: Any
    ) -> GatewayResponse:
        self.calls.append({"method_name": method_name, "params": params, **kwargs})
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _flow(gateway: _Gateway) -> SearchFlow:
    """构造无需真实等待的协调器。"""
    search = SearchService(gateway)
    return SearchFlow(
        search,
        ReportService(gateway),
        task_waiter=TaskWaiter(search, clock=lambda: 0.0),
    )


def _source() -> dict[str, Any]:
    """返回稳定来源任务快照。"""
    return {
        "task_id": "task-source",
        "status": "SUCCEEDED",
        "user_id": "user-safe",
        "create_time": 100,
        "update_time": 200,
        "error_code": "",
        "no_result_reason": "",
    }


def test_refine_and_collect_validates_source_and_returns_new_candidates() -> None:
    """协调器读取两次来源快照，只在新任务成功后读取候选。"""
    gateway = _Gateway(
        [
            _response(_source()),
            _response(
                {
                    "task_id": "task-new",
                    "source_task_id": "task-source",
                    "feedback_id": "feedback-safe",
                    "status": "QUEUED",
                }
            ),
            _response({"task_id": "task-new", "status": "SUCCEEDED"}),
            _response(_source()),
            _response(
                {
                    "task_id": "task-new",
                    "items": [{"candidate_id": "candidate-new"}],
                    "next_page_token": "",
                    "empty_reason": "",
                }
            ),
        ]
    )

    result = _flow(gateway).refine_and_collect(
        access_token="access-secret",
        client_request_id="autotest-build-TC-REFINE",
        source_task_id="task-source",
        additional_details=[{"type": "EMPLOYER", "value": "Example"}],
        feedback_type="too_broad",
        feedback_message="private details",
    )

    assert result.task_id == "task-new"
    assert result.source_task_id == "task-source"
    assert result.feedback_id == "feedback-safe"
    assert result.candidates == ({"candidate_id": "candidate-new"},)
    assert [call["method_name"] for call in gateway.calls] == [
        "GetTask",
        "RefineTask",
        "GetTask",
        "GetTask",
        "ListTaskCandidates",
    ]


def test_refine_business_failure_does_not_wait_or_read_candidates() -> None:
    """RefineTask 业务失败后日志中不能出现新任务轮询或候选查询。"""
    gateway = _Gateway(
        [
            _response(_source()),
            _response(error_code="INPUT_INVALID", numeric_code=301001),
        ]
    )

    with pytest.raises(SearchFlowError, match="RefineTask 业务失败"):
        _flow(gateway).refine_and_collect(
            access_token="access-secret",
            client_request_id="autotest-build-TC-REFINE-FAIL",
            source_task_id="task-source",
            additional_details=[],
            feedback_type="too_broad",
            feedback_message="private details",
        )

    assert [call["method_name"] for call in gateway.calls] == ["GetTask", "RefineTask"]


@pytest.mark.parametrize(
    "status,extra",
    [("NO_RESULT", {}), ("FAILED", {"error_code": "provider_failed"})],
)
def test_refine_non_success_terminal_returns_empty_without_candidates(
    status: str, extra: dict[str, Any]
) -> None:
    """NO_RESULT/合法 FAILED 返回空候选且仍复核来源快照。"""
    gateway = _Gateway(
        [
            _response(_source()),
            _response(
                {
                    "task_id": "task-new",
                    "source_task_id": "task-source",
                    "feedback_id": "feedback-safe",
                }
            ),
            _response({"task_id": "task-new", "status": status, **extra}),
            _response(_source()),
        ]
    )

    result = _flow(gateway).refine_and_collect(
        access_token="access",
        client_request_id="autotest-build-TC-REFINE-TERMINAL",
        source_task_id="task-source",
        additional_details=[],
        feedback_type="too_broad",
        feedback_message="details",
    )

    assert result.status == status
    assert result.candidates == ()
    assert "ListTaskCandidates" not in [call["method_name"] for call in gateway.calls]


def test_refine_rejects_missing_failed_error_and_source_mutation() -> None:
    """FAILED 必须有非空 error_code。"""
    missing_error = _Gateway(
        [
            _response(_source()),
            _response(
                {
                    "task_id": "task-new",
                    "source_task_id": "task-source",
                    "feedback_id": "feedback-safe",
                }
            ),
            _response({"task_id": "task-new", "status": "FAILED", "error_code": ""}),
            _response(_source()),
        ]
    )
    with pytest.raises(SearchFlowError, match="error_code"):
        _flow(missing_error).refine_and_collect(
            access_token="access",
            client_request_id="autotest-build-TC-REFINE-FAILED",
            source_task_id="task-source",
            additional_details=[],
            feedback_type="too_broad",
            feedback_message="details",
        )


@pytest.mark.parametrize(
    "field,changed_value",
    [
        ("update_time", 201),
        ("error_code", "changed"),
        ("no_result_reason", "changed"),
    ],
)
def test_refine_rejects_documented_source_field_mutation(
    field: str, changed_value: Any
) -> None:
    """来源 update/error/no-result 字段变化时必须在候选查询前失败。"""
    changed = dict(_source())
    changed[field] = changed_value
    gateway = _Gateway(
        [
            _response(_source()),
            _response(
                {
                    "task_id": "task-new",
                    "source_task_id": "task-source",
                    "feedback_id": "feedback-safe",
                }
            ),
            _response({"task_id": "task-new", "status": "NO_RESULT"}),
            _response(changed),
        ]
    )

    with pytest.raises(SearchFlowError, match="来源任务稳定字段发生变化"):
        _flow(gateway).refine_and_collect(
            access_token="access",
            client_request_id="autotest-build-TC-REFINE-MUTATED-FIELD",
            source_task_id="task-source",
            additional_details=[],
            feedback_type="too_broad",
            feedback_message="details",
        )

    assert "ListTaskCandidates" not in [call["method_name"] for call in gateway.calls]


def test_refine_rejects_source_status_mutation() -> None:
    """来源任务 status 变化时必须在候选查询前失败。"""
    changed = dict(_source(), status="FAILED")
    mutated = _Gateway(
        [
            _response(_source()),
            _response(
                {
                    "task_id": "task-new",
                    "source_task_id": "task-source",
                    "feedback_id": "feedback-safe",
                }
            ),
            _response({"task_id": "task-new", "status": "NO_RESULT"}),
            _response(changed),
        ]
    )
    with pytest.raises(SearchFlowError, match="来源任务稳定字段发生变化"):
        _flow(mutated).refine_and_collect(
            access_token="access",
            client_request_id="autotest-build-TC-REFINE-MUTATED",
            source_task_id="task-source",
            additional_details=[],
            feedback_type="too_broad",
            feedback_message="details",
        )


def test_add_photos_and_collect_success_and_lineage() -> None:
    """补图协调器只轮询 refresh_task_id，并在成功后查询候选。"""
    gateway = _Gateway(
        [
            _response(
                {
                    "refresh_task_id": "task-refresh",
                    "source_task_id": "task-source",
                    "media_asset_ids": ["media-safe"],
                }
            ),
            _response({"task_id": "task-refresh", "status": "SUCCEEDED"}),
            _response(
                {
                    "task_id": "task-refresh",
                    "items": [{"candidate_id": "candidate-refresh"}],
                }
            ),
        ]
    )

    result = _flow(gateway).add_photos_and_collect(
        access_token="access-secret",
        client_request_id="autotest-build-TC-PHOTO",
        source_task_id="task-source",
        media_asset_ids=["media-safe"],
        client_context={"screen": "report_detail"},
    )

    assert result.task_id == "task-refresh"
    assert result.media_asset_ids == ("media-safe",)
    assert result.candidates == ({"candidate_id": "candidate-refresh"},)
    assert [call["method_name"] for call in gateway.calls] == [
        "AddReportPhotos",
        "GetTask",
        "ListTaskCandidates",
    ]


@pytest.mark.parametrize(
    "add_response,terminal,error_match",
    [
        (_response(error_code="NOT_FOUND", numeric_code=301404), None, "业务失败"),
        (
            _response({"refresh_task_id": "task-source", "source_task_id": "task-source"}),
            None,
            "新任务",
        ),
        (
            _response(
                {
                    "refresh_task_id": "task-refresh",
                    "source_task_id": "task-source",
                    "media_asset_ids": ["media-safe"],
                }
            ),
            {"task_id": "task-refresh", "status": "FAILED", "error_code": ""},
            "error_code",
        ),
    ],
)
def test_add_photos_failures_short_circuit_without_candidates(
    add_response: GatewayResponse,
    terminal: dict[str, Any] | None,
    error_match: str,
) -> None:
    """Add 业务、血缘或 FAILED 契约异常均不能继续错误步骤。"""
    responses = [add_response]
    if terminal is not None:
        responses.append(_response(terminal))
    gateway = _Gateway(responses)

    with pytest.raises(SearchFlowError, match=error_match):
        _flow(gateway).add_photos_and_collect(
            access_token="access",
            client_request_id="autotest-build-TC-PHOTO-FAIL",
            source_task_id="task-source",
            media_asset_ids=["media-safe"],
        )

    assert "ListTaskCandidates" not in [call["method_name"] for call in gateway.calls]


@pytest.mark.parametrize(
    "echoed_media",
    [
        ["media-other", "media-safe"],
        ["media-cross-asset"],
    ],
    ids=["order-mismatch", "asset-set-mismatch"],
)
def test_add_photos_rejects_cross_asset_echo_before_wait(
    echoed_media: list[str],
) -> None:
    """服务端回显不同资产或顺序时必须在刷新任务轮询前失败。"""
    gateway = _Gateway(
        [
            _response(
                {
                    "refresh_task_id": "task-refresh",
                    "source_task_id": "task-source",
                    "media_asset_ids": echoed_media,
                }
            )
        ]
    )

    with pytest.raises(SearchFlowError, match="media_asset_ids"):
        _flow(gateway).add_photos_and_collect(
            access_token="access",
            client_request_id="autotest-build-TC-PHOTO-MISMATCH",
            source_task_id="task-source",
            media_asset_ids=["media-safe", "media-other"],
        )

    assert [call["method_name"] for call in gateway.calls] == ["AddReportPhotos"]


def test_flow_wraps_external_exception_without_secret_message() -> None:
    """外部异常消息即使含 token，也只暴露异常类型。"""
    gateway = _Gateway([RuntimeError("access-token-ultra-secret")])

    with pytest.raises(SearchFlowError) as caught:
        _flow(gateway).add_photos_and_collect(
            access_token="access-token-ultra-secret",
            client_request_id="autotest-build-TC-PHOTO-EXCEPTION",
            source_task_id="task-source",
            media_asset_ids=["media-safe"],
        )

    assert "access-token-ultra-secret" not in str(caught.value)
    assert "RuntimeError" in str(caught.value)
