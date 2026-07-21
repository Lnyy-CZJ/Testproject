"""阶段4扩展 Service 的文档请求形状测试。"""

from typing import Any

from framework.models.envelope import GatewayResponse
from services.profile_feedback_service import ProfileFeedbackService
from services.report_service import ReportService
from services.search_service import SearchService


class _Gateway:
    """记录调用且返回离线成功响应的最小 Gateway 替身。"""

    def __init__(self) -> None:
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
        response = GatewayResponse.model_validate(
            {
                "code": 0,
                "message": "OK",
                "request_id": "offline",
                "trace_id": "offline",
                "responses": [{"id": "req_0", "code": 0, "success": True, "data": {}}],
            }
        )
        response.http_status = 200
        return response


def test_refine_task_uses_exact_documented_fields_and_preserves_ids() -> None:
    """RefineTask 不改写来源/幂等 ID，也不引入内部 report_id。"""
    gateway = _Gateway()
    details = [{"type": "EMPLOYER", "value": "Example Org"}]

    SearchService(gateway).refine_task(
        access_token="access",
        client_request_id="autotest-build-TC-REFINE-001",
        source_task_id="task-source",
        additional_details=details,
        feedback_type="too_broad",
        feedback_message="narrow it",
    )

    call = gateway.calls[0]
    assert call == {
        "service_name": "tool.people_insight.SearchService",
        "method_name": "RefineTask",
        "params": {
            "client_request_id": "autotest-build-TC-REFINE-001",
            "source_task_id": "task-source",
            "additional_details": details,
            "feedback_type": "too_broad",
            "feedback_message": "narrow it",
        },
        "auth_token": "access",
        "client_request_id": "autotest-build-TC-REFINE-001",
    }
    assert "report_id" not in call["params"]


def test_report_methods_use_exact_documented_optional_fields() -> None:
    """补图与报告反馈只发送调用方提供的文档字段。"""
    gateway = _Gateway()
    service = ReportService(gateway)
    service.add_report_photos(
        access_token="access",
        client_request_id="autotest-build-TC-PHOTO-001",
        task_id="task-source",
        media_asset_ids=["media-1"],
        client_context={"screen": "report_detail"},
    )
    service.submit_feedback(
        access_token="access",
        client_request_id="autotest-build-TC-FEEDBACK-001",
        task_id="task-source",
        feedback_type="wrong_person",
        feedback_message="unrelated",
        selected_evidence_ids=["ev-1"],
        additional_details=[{"type": "EMPLOYER", "value": "Example Org"}],
        screenshot_media_asset_id="media-screen",
        client_context={"screen": "report_detail", "app_version": "0.1.0"},
    )

    assert gateway.calls[0]["params"] == {
        "client_request_id": "autotest-build-TC-PHOTO-001",
        "task_id": "task-source",
        "media_asset_ids": ["media-1"],
        "client_context": {"screen": "report_detail"},
    }
    assert gateway.calls[1]["params"] == {
        "client_request_id": "autotest-build-TC-FEEDBACK-001",
        "task_id": "task-source",
        "feedback_type": "wrong_person",
        "feedback_message": "unrelated",
        "selected_evidence_ids": ["ev-1"],
        "additional_details": [{"type": "EMPLOYER", "value": "Example Org"}],
        "screenshot_media_asset_id": "media-screen",
        "client_context": {"screen": "report_detail", "app_version": "0.1.0"},
    }
    assert all("report_id" not in call["params"] for call in gateway.calls)
    assert gateway.calls[0]["client_request_id"] == "autotest-build-TC-PHOTO-001"
    assert gateway.calls[1]["client_request_id"] == "autotest-build-TC-FEEDBACK-001"


def test_feedback_services_omit_only_unprovided_optional_fields() -> None:
    """可选字段为 None 时省略，调用方显式提供的空容器或空字符串原样发送。"""
    gateway = _Gateway()
    ReportService(gateway).submit_feedback(
        access_token="access",
        client_request_id="autotest-build-TC-FEEDBACK-EMPTY",
        task_id="task-source",
        feedback_type="wrong_person",
        feedback_message="",
        selected_evidence_ids=[],
        additional_details=[],
        client_context={},
    )
    ProfileFeedbackService(gateway).submit_profile_feedback(
        access_token="access",
        client_request_id="autotest-build-TC-PROFILE-EMPTY",
        feedback_message="message",
        feedback_type="GENERAL",
        contact="",
        media_asset_ids=[],
        client_context={},
    )

    assert gateway.calls[0]["params"] == {
        "client_request_id": "autotest-build-TC-FEEDBACK-EMPTY",
        "task_id": "task-source",
        "feedback_type": "wrong_person",
        "feedback_message": "",
        "selected_evidence_ids": [],
        "additional_details": [],
        "client_context": {},
    }
    assert gateway.calls[1]["params"] == {
        "client_request_id": "autotest-build-TC-PROFILE-EMPTY",
        "feedback_message": "message",
        "feedback_type": "GENERAL",
        "contact": "",
        "media_asset_ids": [],
        "client_context": {},
    }


def test_profile_feedback_uses_exact_documented_shape_and_stable_id() -> None:
    """个人反馈的业务参数与 Gateway 幂等上下文使用同一个调用方 ID。"""
    gateway = _Gateway()
    ProfileFeedbackService(gateway).submit_profile_feedback(
        access_token="access",
        client_request_id="autotest-build-TC-PROFILE-001",
        feedback_message="layout confusing",
        feedback_type="APP_FEEDBACK",
        contact="user@example.test",
        media_asset_ids=["media-feedback"],
        client_context={"screen": "profile"},
    )

    call = gateway.calls[0]
    assert call["service_name"] == "tool.people_insight.ProfileFeedbackService"
    assert call["method_name"] == "SubmitProfileFeedback"
    assert call["params"] == {
        "client_request_id": "autotest-build-TC-PROFILE-001",
        "feedback_message": "layout confusing",
        "feedback_type": "APP_FEEDBACK",
        "contact": "user@example.test",
        "media_asset_ids": ["media-feedback"],
        "client_context": {"screen": "profile"},
    }
    assert call["client_request_id"] == "autotest-build-TC-PROFILE-001"
