"""Dating 已部署客户端协议、Case 与 Flow 静态验收。"""

from __future__ import annotations

from pathlib import Path

from utils.custom.api_loader import load_api_definitions
from utils.custom.case_loader import load_single_cases
from utils.custom.config_loader import load_yaml
from utils.custom.flow_loader import load_flow_cases
from utils.custom.project_registry import ProjectRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_APIS = {
    "CreateAnonymousSession": ("tool.identity.IdentityService", "CreateAnonymousSession", "public"),
    "RefreshSession": ("tool.identity.IdentityService", "RefreshSession", "anonymous_session"),
    "GetMe": ("tool.identity.IdentityService", "GetMe", "anonymous_session"),
    "DeleteAccount": ("tool.identity.IdentityService", "DeleteAccount", "anonymous_session"),
    "GetUserPreferences": ("tool.dating.DatingAssistantService", "GetUserPreferences", "anonymous_session"),
    "UpdateUserPreferences": ("tool.dating.DatingAssistantService", "UpdateUserPreferences", "anonymous_session"),
    "GetMediaUploadConfig": ("tool.dating.DatingMediaService", "GetMediaUploadConfig", "anonymous_session"),
    "PrepareMediaUpload": ("tool.dating.DatingMediaService", "PrepareMediaUpload", "anonymous_session"),
    "CompleteMediaUpload": ("tool.dating.DatingMediaService", "CompleteMediaUpload", "anonymous_session"),
    "CreateReplyTask": ("tool.dating.DatingAssistantService", "CreateReplyTask", "anonymous_session"),
    "GetTask": ("tool.dating.DatingAssistantService", "GetTask", "anonymous_session"),
    "GetTaskResult": ("tool.dating.DatingAssistantService", "GetTaskResult", "anonymous_session"),
    "CreateAnalysisTask": ("tool.dating.DatingAssistantService", "CreateAnalysisTask", "anonymous_session"),
    "GetAnalysisTask": ("tool.dating.DatingAssistantService", "GetAnalysisTask", "anonymous_session"),
    "GetAnalysisResult": ("tool.dating.DatingAssistantService", "GetAnalysisResult", "anonymous_session"),
    "DeleteTaskData": ("tool.dating.DatingAssistantService", "DeleteTaskData", "anonymous_session"),
    "GetQuotaStatus": ("tool.subscription.SubscriptionService", "GetQuotaStatus", "anonymous_session"),
    "UpdateReplyAssociation": (
        "tool.dating.DatingAssistantService",
        "UpdateReplyAssociation",
        "anonymous_session",
    ),
    "SubmitFeedback": (
        "tool.dating.DatingFeedbackService",
        "SubmitFeedback",
        "anonymous_session",
    ),
    "DeleteUserData": (
        "tool.dating.DatingAssistantService",
        "DeleteUserData",
        "anonymous_session",
    ),
}

SUCCESS_ASSERTION = {
    "http_status": 200,
    "gateway": {"message": "ok"},
}


def test_dating_manifest_matches_deployed_public_api_contract() -> None:
    """目录应包含新版协议中已经由真实 Gateway 确认的 20 个公开 API。

    ``GetTask/GetTaskResult`` 只服务 Reply；Analysis 仍使用独立的
    ``GetAnalysisTask/GetAnalysisResult``，不能因新增 Reply 接口而回退旧名称。
    """
    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    definitions = load_api_definitions(package.root)

    assert set(definitions) == set(EXPECTED_APIS)
    assert package.manifest.config_contract.credential_profiles == (
        "anonymous_session",
    )
    for api_id, (service_name, method_name, credential_profile) in EXPECTED_APIS.items():
        assert definitions[api_id]["request"] == {
            "service_name": service_name,
            "method_name": method_name,
        }
        assert definitions[api_id]["credential_profile"] == credential_profile


def test_dating_gateway_transport_uses_dating_client_route() -> None:
    """Dating 本地协议默认入口必须与客户端能力文档一致。

    平台执行时该路径由 Runtime Scope 的 Release 快照唯一决定；这里锁定本地
    调试默认值，避免复制 Truthy 资产后误请求通用 ``/gateway/invoke``，继而
    得到 ``APPLICATION_DENIED``。
    """
    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    endpoint = load_yaml(package.api_dir / "gateway_invoke.yaml")

    assert endpoint["path"] == "/dating/gateway/invoke"


def test_dating_has_complete_standalone_case_matrix() -> None:
    """独立执行有价值的接口应覆盖成功、格式边界和输入失败。"""
    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    cases = load_single_cases(package.root)

    assert {item["api_id"] for item in cases} == {
        "CreateAnonymousSession",
        "RefreshSession",
        "GetMe",
        "GetMediaUploadConfig",
        "PrepareMediaUpload",
        "GetQuotaStatus",
        "GetUserPreferences",
        "SubmitFeedback",
    }
    case_ids = {item["id"] for item in cases}
    assert len(case_ids) == 21
    assert {
        "RefreshSession::refresh_session_success",
        "RefreshSession::refresh_session_invalid_token",
        "PrepareMediaUpload::prepare_jpeg_success",
        "PrepareMediaUpload::prepare_png_success",
        "PrepareMediaUpload::prepare_webp_success",
        "PrepareMediaUpload::prepare_size_at_limit_success",
        "PrepareMediaUpload::prepare_size_over_limit",
        "PrepareMediaUpload::prepare_unsupported_content_type",
        "SubmitFeedback::submit_feedback_text_success",
        "SubmitFeedback::submit_feedback_message_min_success",
        "SubmitFeedback::submit_feedback_message_max_success",
        "SubmitFeedback::submit_feedback_invalid_type",
        "SubmitFeedback::submit_feedback_blank_message",
        "SubmitFeedback::submit_feedback_message_too_long",
        "SubmitFeedback::submit_feedback_invalid_email",
    }.issubset(case_ids)

    cases_by_id = {item["id"]: item for item in cases}
    assert cases_by_id[
        "PrepareMediaUpload::prepare_size_at_limit_success"
    ]["execution_case"]["request"]["params"]["size_bytes"] == 7_000_000
    assert cases_by_id[
        "PrepareMediaUpload::prepare_size_over_limit"
    ]["execution_case"]["request"]["params"]["size_bytes"] == 7_000_001
    assert cases_by_id[
        "SubmitFeedback::submit_feedback_message_max_success"
    ]["execution_case"]["request"]["params"]["feedback_message"] == "测" * 500
    assert cases_by_id[
        "SubmitFeedback::submit_feedback_message_too_long"
    ]["execution_case"]["request"]["params"]["feedback_message"] == "测" * 501

    successful_case_ids = {
        "CreateAnonymousSession::create_anonymous_session_success",
        "GetMe::get_me_success",
        "GetMediaUploadConfig::get_media_upload_config_success",
        "GetQuotaStatus::get_analysis_quota_success",
        "GetQuotaStatus::get_reply_quota_success",
        "GetUserPreferences::get_user_preferences_success",
        "RefreshSession::refresh_session_success",
        "PrepareMediaUpload::prepare_jpeg_success",
        "PrepareMediaUpload::prepare_png_success",
        "PrepareMediaUpload::prepare_webp_success",
        "PrepareMediaUpload::prepare_size_at_limit_success",
        "SubmitFeedback::submit_feedback_text_success",
        "SubmitFeedback::submit_feedback_message_min_success",
        "SubmitFeedback::submit_feedback_message_max_success",
    }
    assert successful_case_ids.issubset(case_ids)
    for case_id in successful_case_ids:
        assert cases_by_id[case_id]["execution_case"]["assert"] == SUCCESS_ASSERTION

    assert {item["id"] for item in cases if item["api_id"] == "GetQuotaStatus"} == {
        "GetQuotaStatus::get_analysis_quota_success",
        "GetQuotaStatus::get_reply_quota_success",
    }
    quota_cases = [item for item in cases if item["api_id"] == "GetQuotaStatus"]
    for quota_case in quota_cases:
        assert set(quota_case["runtime_inputs"]) == {
            "product_code",
            "entitlement_code",
        }
        product_input = quota_case["runtime_inputs"]["product_code"]
        quota_input = quota_case["runtime_inputs"]["entitlement_code"]
        assert product_input["type"] == quota_input["type"] == "string"
        assert product_input["options"] == quota_input["options"] == []
        assert quota_input["target"] == {
            "scope": "case_request",
            "path": ["entitlement_code"],
        }
    create_session = next(
        item for item in cases if item["api_id"] == "CreateAnonymousSession"
    )
    assert create_session["runtime_inputs"] == {}


def test_dating_flow_catalog_covers_stateful_contracts() -> None:
    """动态 ID、版本与破坏性能力必须由自包含 Flow 覆盖。"""
    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    flows = {item["id"]: item for item in load_flow_cases(package.root)}

    assert set(flows) == {
        "anonymous_session_refresh",
        "analysis_idempotency",
        "analysis_not_ready_then_success",
        "analysis_rejected",
        "delete_account_contract",
        "delete_task_data_contract",
        "delete_user_data_contract",
        "feedback_with_attachments",
        "media_upload_contract",
        "multi_image_analysis",
        "multi_image_reply",
        "reply_association",
        "reply_idempotency_supersede_resume",
        "reply_preferences_lifecycle",
    }
    # Web 创建 Flow 任务的默认示例使用 regression 过滤；P0 Flow 必须带同名
    # pytest marker，否则平台会成功提交却在收集阶段把唯一用例全部 deselect。
    assert "regression" in flows["anonymous_session_refresh"]["tags"]
    assert flows["multi_image_analysis"]["tags"] == ["interactive"]
    refresh_api_ids = [step.get("api") for step in flows["anonymous_session_refresh"]["flow"]["steps"]]
    assert refresh_api_ids == [
        "CreateAnonymousSession",
        "GetMe",
        "RefreshSession",
        "GetMe",
    ]
    cleanup = flows["delete_task_data_contract"]
    assert {"cleanup", "destructive", "explicit"}.issubset(cleanup["tags"])
    assert "smoke" not in cleanup["tags"]
    analysis_steps = cleanup["flow"]["steps"]
    result_step = next(
        step for step in analysis_steps if step.get("api") == "GetAnalysisResult"
    )
    cleanup_step = next(step for step in analysis_steps if step.get("api") == "DeleteTaskData")
    poll_step = next(step for step in analysis_steps if step.get("api") == "GetAnalysisTask")
    assert result_step["skip_unless"] == {"variable": "analysis_status", "equals": "succeeded"}
    assert cleanup_step["run_on_termination"] is True
    assert poll_step["until"]["terminate_on"] == ["rejected", "failed"]
    assert poll_step["until"]["interval_seconds"] == "{{analysis_poll_interval_seconds}}"
    assert poll_step["until"]["timeout_seconds"] == "{{analysis_timeout_seconds}}"

    scenario = cleanup["scenario"]["step_data"]
    assert scenario["get_analysis_result"]["assert"] == SUCCESS_ASSERTION
    assert analysis_steps[-1] == {
        "id": "verify_deleted_result",
        "api": "GetAnalysisResult",
    }
    assert scenario["verify_deleted_result"]["assert"]["response"] == {
        "id": "req_0",
        "success": False,
        "business_error_code": "NOT_FOUND",
    }
    delete_steps = [
        step for step in analysis_steps if step.get("api") == "DeleteTaskData"
    ]
    assert len(delete_steps) == 2

    interactive = flows["multi_image_analysis"]
    analysis_locale = interactive["runtime_inputs"]["analysis_locale"]
    assert analysis_locale["default_value"] == "en-US"
    assert analysis_locale["options"] == ["en-US", "zh-CN"]
    assert analysis_locale["target"] == {
        "scope": "flow_step_request",
        "step_id": "create_analysis",
        "path": ["locale"],
    }
    assert list(interactive["runtime_inputs"]) == [
        "analysis_locale",
        "other_person_name",
        "analysis_background",
    ]
    assert interactive["flow"]["inputs"] == {
        "media_files": {
            "type": "files",
            "required": True,
            "min_items": 1,
            "max_items": 9,
            "allowed_content_types": ["image/jpeg", "image/png", "image/webp"],
            "max_size_bytes": 7000000,
            "label": "分析图片",
            "description": "按聊天顺序选择 1～9 张图片",
        }
    }
    interactive_steps = interactive["flow"]["steps"]
    foreach_step = next(step for step in interactive_steps if "foreach" in step)
    assert foreach_step["foreach"]["collect"] == {"asset_ids": "{{asset_id}}"}
    assert [
        step.get("api") or (step.get("action") or {}).get("type")
        for step in foreach_step["foreach"]["steps"]
    ] == [
        "PrepareMediaUpload",
        "signed_binary_upload",
        "CompleteMediaUpload",
    ]
    assert all(step.get("api") != "DeleteTaskData" for step in interactive_steps)
    interactive_poll = next(
        step for step in interactive_steps if step.get("api") == "GetAnalysisTask"
    )
    assert interactive_poll["until"]["fail_on_termination"] is True

    reply = flows["multi_image_reply"]
    reply_locale = reply["runtime_inputs"]["reply_locale"]
    assert reply_locale["default_value"] == "en-US"
    assert reply_locale["options"] == ["en-US", "zh-CN"]
    assert reply_locale["target"] == {
        "scope": "flow_step_request",
        "step_id": "create_reply",
        "path": ["locale"],
    }
    assert list(reply["runtime_inputs"]) == [
        "reply_locale",
        "requested_intent",
        "reply_background",
        "update_preferences__dating_goal",
        "update_preferences__your_voice",
    ]
    # Gateway 参数必须使用后端真实接受的稳定 code；Opener/Charming 等是
    # 产品展示文案，直接作为 requested_intent 发送会返回 INPUT_INVALID。
    assert reply["runtime_inputs"]["requested_intent"]["options"] == [
        "opener",
        "flirt",
        "tease",
        "advance",
    ]
    assert reply["runtime_inputs"]["update_preferences__dating_goal"][
        "default_value"
    ] == "serious_relationship"
    assert reply["runtime_inputs"]["update_preferences__your_voice"][
        "default_value"
    ] == "warm_direct"
    assert reply["tags"] == ["interactive"]
    assert reply["flow"]["inputs"] == {
        "media_files": {
            "type": "files",
            "required": True,
            "min_items": 1,
            "max_items": 9,
            "allowed_content_types": ["image/jpeg", "image/png", "image/webp"],
            "max_size_bytes": 7000000,
            "label": "Reply 图片",
            "description": "按聊天顺序选择 1～9 张图片",
        }
    }
    reply_steps = reply["flow"]["steps"]
    assert [step.get("api") for step in reply_steps if step.get("api")] == [
        "GetUserPreferences",
        "UpdateUserPreferences",
        "GetMediaUploadConfig",
        "CreateReplyTask",
        "GetTask",
        "GetTaskResult",
    ]
    update_preferences = next(
        step for step in reply_steps if step.get("api") == "UpdateUserPreferences"
    )
    assert update_preferences["skip_if"] == {
        "variable": "preferences_complete",
        "equals": True,
    }
    reply_foreach = next(step for step in reply_steps if "foreach" in step)
    assert reply_foreach["foreach"]["collect"] == {"asset_ids": "{{asset_id}}"}
    assert [
        step.get("api") or (step.get("action") or {}).get("type")
        for step in reply_foreach["foreach"]["steps"]
    ] == [
        "PrepareMediaUpload",
        "signed_binary_upload",
        "CompleteMediaUpload",
    ]
    assert all(step.get("api") != "DeleteTaskData" for step in reply_steps)
    reply_poll = next(step for step in reply_steps if step.get("api") == "GetTask")
    assert reply_poll["until"] == {
        "path": "$.status",
        "equals": "succeeded",
        "terminate_on": ["rejected", "failed"],
        "fail_on_termination": True,
        "interval_seconds": "{{analysis_poll_interval_seconds}}",
        "timeout_seconds": "{{analysis_timeout_seconds}}",
    }
    reply_scenario = reply["scenario"]["step_data"]
    assert reply_scenario["update_preferences"]["params"] == {
        "client_request_id": "{{client_request_id}}",
        "dating_goal": "serious_relationship",
        "your_voice": "warm_direct",
        "expected_version": "{{preferences_version}}",
    }
    assert reply_scenario["create_reply"]["params"]["requested_intent"] == "flirt"

    supported_intents = {"opener", "flirt", "tease", "advance"}
    for flow_id in (
        "multi_image_reply",
        "reply_association",
        "reply_idempotency_supersede_resume",
    ):
        for step_data in flows[flow_id]["scenario"]["step_data"].values():
            params = step_data.get("params") or {}
            if "requested_intent" in params:
                assert params["requested_intent"] in supported_intents
    # Analysis/Reply 后端仍在联调期。这两个交互 Flow 的每个 Gateway 步骤只
    # 固定传输成功和顶层 message；具体 data 字段、类型和值均不得成为阻塞项。
    relaxed_assertion = {
        "http_status": 200,
        "gateway": {"message": "ok"},
    }
    for flow_id in ("anonymous_session_refresh", "multi_image_analysis", "multi_image_reply"):
        step_data = flows[flow_id]["scenario"]["step_data"]
        assert step_data
        assert all(
            step["assert"] == relaxed_assertion
            for step in step_data.values()
        )

    for flow_id in (
        "analysis_idempotency",
        "analysis_not_ready_then_success",
        "analysis_rejected",
        "reply_association",
        "reply_idempotency_supersede_resume",
        "reply_preferences_lifecycle",
        "feedback_with_attachments",
        "delete_user_data_contract",
        "delete_account_contract",
    ):
        assert "explicit" in flows[flow_id]["tags"]

    for flow_id in ("delete_user_data_contract", "delete_account_contract"):
        assert {"destructive", "isolated", "explicit"}.issubset(
            flows[flow_id]["tags"]
        )

    for flow_id in ("multi_image_analysis", "multi_image_reply"):
        assert all(
            step.get("api") != "DeleteTaskData"
            for step in flows[flow_id]["flow"]["steps"]
        )


def test_third_fixture_project_validates_without_engine_branch() -> None:
    """第三项目只增加项目包即可通过公共注册表，不需要引擎项目分支。"""
    registry = ProjectRegistry(PROJECT_ROOT / "projects")
    package = registry.get("fixture-demo")

    assert package.project_id == "fixture-demo"
    assert package.manifest.capabilities == ("gateway",)
    assert registry.validate("fixture-demo") == []


def test_dating_upload_fixture_media_type_matches_declared_content_type() -> None:
    """签名上传的声明类型必须与真实文件魔数一致，避免真实 PUT 被对象存储拒绝。"""

    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    fixture = package.fixtures_dir / "chat-sample.png"
    scenario = load_yaml(
        package.scenarios_dir / "delete_task_data_contract.yaml"
    )

    assert fixture.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert scenario["step_data"]["prepare_upload"]["params"]["content_type"] == "image/png"
