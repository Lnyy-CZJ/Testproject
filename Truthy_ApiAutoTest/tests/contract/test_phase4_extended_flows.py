"""阶段4二次搜索、补图与反馈的完整离线流程契约。"""

from collections.abc import Iterable
from typing import Any

import pytest

from framework.assertions.gateway_assert import assert_business_success
from framework.models.envelope import GatewayResponse
from framework.flows.search_flow import SearchFlow
from framework.security.redactor import REDACTED, Redactor
from framework.waiters.task_waiter import TaskWaiter
from services.media_service import MediaService
from services.profile_feedback_service import ProfileFeedbackService
from services.report_service import ReportService
from services.search_service import SearchService


def _response(
    data: Any = None, *, error_code: str = "", numeric_code: int = 0
) -> GatewayResponse:
    """构造可成功或业务失败的单子响应离线信封。"""
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


class _Gateway:
    """按顺序返回离线响应并记录跨 Service 调用。"""

    def __init__(self, responses: Iterable[GatewayResponse]) -> None:
        self._responses = iter(responses)
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
        return next(self._responses)


class _Clock:
    """让 TaskWaiter 离线推进时间而不真实 sleep。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Cos:
    """可配置成功或失败的离线 COS PUT 替身。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def put(self, url: str, *, upload_headers: dict[str, str], content: bytes) -> None:
        self.calls += 1
        if self.fail:
            raise RuntimeError("offline cos failure")


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.search
@pytest.mark.feedback
@pytest.mark.async_task
def test_refine_task_returns_new_lineage_and_waits_only_new_task() -> None:
    """精炼流程保留来源快照，轮询新 task 成功后才读取新候选。"""
    source = {
        "task_id": "task-source",
        "status": "SUCCEEDED",
        "user_id": "user-offline",
        "create_time": 100,
    }
    gateway = _Gateway(
        [
            _response(source),
            _response(
                {
                    "task_id": "task-refined",
                    "source_task_id": "task-source",
                    "feedback_id": "feedback-refine",
                    "status": "QUEUED",
                }
            ),
            _response({"task_id": "task-refined", "status": "SEARCHING"}),
            _response({"task_id": "task-refined", "status": "SUCCEEDED"}),
            _response(source),
            _response(
                {
                    "task_id": "task-refined",
                    "items": [{"candidate_id": "candidate-refined"}],
                    "next_page_token": "",
                    "empty_reason": "",
                }
            ),
        ]
    )
    service = SearchService(gateway)
    clock = _Clock()
    result = SearchFlow(
        service,
        ReportService(gateway),
        task_waiter=TaskWaiter(service, clock=clock, sleep=clock.sleep),
    ).refine_and_collect(
            access_token="access",
            client_request_id="autotest-build-TC-REFINE-001",
            source_task_id="task-source",
            additional_details=[{"type": "EMPLOYER", "value": "Example Org"}],
            feedback_type="too_broad",
            feedback_message="narrow it",
    )

    assert result.task_id == "task-refined"
    assert result.source_task_id == "task-source"
    assert result.feedback_id == "feedback-refine"
    assert result.candidates[0]["candidate_id"] == "candidate-refined"
    assert [call["method_name"] for call in gateway.calls] == [
        "GetTask",
        "RefineTask",
        "GetTask",
        "GetTask",
        "GetTask",
        "ListTaskCandidates",
    ]


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.media
@pytest.mark.report
@pytest.mark.async_task
def test_add_report_photos_uploads_then_waits_refresh_task_before_candidates() -> None:
    """补图严格遵循上传三段式、Add、轮询刷新任务、候选列表顺序。"""
    content = b"offline-image"
    gateway = _Gateway(
        [
            _response({"allowed_content_types": ["image/jpeg"], "max_size_bytes": 100}),
            _response(
                {
                    "media_asset_id": "media-photo",
                    "status": "pending",
                    "content_type": "image/jpeg",
                    "size_bytes": len(content),
                    "upload_url": "https://cos.example.test/object",
                    "upload_method": "PUT",
                    "upload_headers": {"Content-Type": "image/jpeg"},
                    "max_size_bytes": 100,
                }
            ),
            _response(
                {
                    "media_asset_id": "media-photo",
                    "status": "uploaded",
                    "content_type": "image/jpeg",
                    "size_bytes": len(content),
                }
            ),
            _response(
                {
                    "refresh_task_id": "task-refresh",
                    "source_task_id": "task-source",
                    "media_asset_ids": ["media-photo"],
                    "status": "QUEUED",
                }
            ),
            _response({"task_id": "task-refresh", "status": "SUCCEEDED"}),
            _response(
                {
                    "task_id": "task-refresh",
                    "items": [{"candidate_id": "candidate-refresh"}],
                    "next_page_token": "",
                    "empty_reason": "",
                }
            ),
        ]
    )
    cos = _Cos()
    uploaded = assert_business_success(
        MediaService(gateway, cos_client=cos).upload_media(
            access_token="access",
            client_request_id="autotest-build-TC-PHOTO-UPLOAD",
            content_type="image/jpeg",
            content=content,
        )
    )
    search = SearchService(gateway)
    result = SearchFlow(
        search,
        ReportService(gateway),
        task_waiter=TaskWaiter(search, clock=lambda: 0),
    ).add_photos_and_collect(
            access_token="access",
            client_request_id="autotest-build-TC-PHOTO-ADD",
            source_task_id="task-source",
            media_asset_ids=[uploaded["media_asset_id"]],
            client_context={"screen": "report_detail"},
    )

    assert cos.calls == 1
    assert result.source_task_id == "task-source"
    assert result.media_asset_ids == ("media-photo",)
    assert result.task_id == "task-refresh"
    assert [call["method_name"] for call in gateway.calls] == [
        "GetMediaUploadConfig",
        "PrepareMediaUpload",
        "CompleteMediaUpload",
        "AddReportPhotos",
        "GetTask",
        "ListTaskCandidates",
    ]


@pytest.mark.contract
@pytest.mark.media
@pytest.mark.report
def test_cos_failure_never_completes_or_adds_report_photos() -> None:
    """COS PUT 失败后不能错误执行 Complete 或 AddReportPhotos。"""
    content = b"offline-image"
    gateway = _Gateway(
        [
            _response({"allowed_content_types": ["image/jpeg"], "max_size_bytes": 100}),
            _response(
                {
                    "media_asset_id": "media-photo",
                    "status": "pending",
                    "content_type": "image/jpeg",
                    "size_bytes": len(content),
                    "upload_url": "https://cos.example.test/object",
                    "upload_method": "PUT",
                    "upload_headers": {},
                    "max_size_bytes": 100,
                }
            ),
        ]
    )

    with pytest.raises(RuntimeError, match="offline cos failure"):
        MediaService(gateway, cos_client=_Cos(fail=True)).upload_media(
            access_token="access",
            client_request_id="autotest-build-TC-PHOTO-COS-FAIL",
            content_type="image/jpeg",
            content=content,
        )

    assert [call["method_name"] for call in gateway.calls] == [
        "GetMediaUploadConfig",
        "PrepareMediaUpload",
    ]


@pytest.mark.contract
@pytest.mark.report
@pytest.mark.async_task
def test_refresh_task_failure_never_reads_candidates() -> None:
    """刷新任务进入 FAILED 终态时，编排层不得继续候选查询。"""
    gateway = _Gateway(
        [
            _response(
                {
                    "refresh_task_id": "task-refresh",
                    "source_task_id": "task-source",
                    "media_asset_ids": ["media-photo"],
                    "status": "QUEUED",
                }
            ),
            _response(
                {
                    "task_id": "task-refresh",
                    "status": "FAILED",
                    "error_code": "non-empty",
                }
            ),
        ]
    )
    search = SearchService(gateway)
    terminal = SearchFlow(
        search,
        ReportService(gateway),
        task_waiter=TaskWaiter(search, clock=lambda: 0),
    ).add_photos_and_collect(
            access_token="access",
            client_request_id="autotest-build-TC-PHOTO-TASK-FAIL",
            source_task_id="task-source",
            media_asset_ids=["media-photo"],
    )

    assert terminal.status == "FAILED"
    assert terminal.candidates == ()
    assert [call["method_name"] for call in gateway.calls] == [
        "AddReportPhotos",
        "GetTask",
    ]


@pytest.mark.contract
@pytest.mark.feedback
@pytest.mark.idempotency
def test_report_and_profile_feedback_reuse_ids_and_redact_diagnostics() -> None:
    """重复提交复用调用方 ID，离线回显同一 feedback_id 且诊断脱敏。"""
    gateway = _Gateway(
        [
            _response({"feedback_id": "feedback-report", "status": "submitted"}),
            _response({"feedback_id": "feedback-report", "status": "submitted"}),
            _response({"feedback_id": "feedback-profile", "status": "submitted"}),
            _response({"feedback_id": "feedback-profile", "status": "submitted"}),
        ]
    )
    report = ReportService(gateway)
    profile = ProfileFeedbackService(gateway)
    report_results = [
        assert_business_success(
            report.submit_feedback(
                access_token="access-secret",
                client_request_id="autotest-build-TC-REPORT-FEEDBACK",
                task_id="task-source",
                feedback_type="wrong_person",
                feedback_message="private report feedback",
            )
        )
        for _ in range(2)
    ]
    profile_results = [
        assert_business_success(
            profile.submit_profile_feedback(
                access_token="access-secret",
                client_request_id="autotest-build-TC-PROFILE-FEEDBACK",
                feedback_message="private profile feedback",
                contact="private@example.test",
            )
        )
        for _ in range(2)
    ]
    diagnostic = Redactor().redact(gateway.calls)

    assert {item["feedback_id"] for item in report_results} == {"feedback-report"}
    assert {item["feedback_id"] for item in profile_results} == {"feedback-profile"}
    assert [call["params"]["client_request_id"] for call in gateway.calls] == [
        "autotest-build-TC-REPORT-FEEDBACK",
        "autotest-build-TC-REPORT-FEEDBACK",
        "autotest-build-TC-PROFILE-FEEDBACK",
        "autotest-build-TC-PROFILE-FEEDBACK",
    ]
    assert all(call["auth_token"] == REDACTED for call in diagnostic)
    assert all(
        call["params"].get("feedback_message") == REDACTED for call in diagnostic
    )
    assert diagnostic[-1]["params"]["contact"] == REDACTED
