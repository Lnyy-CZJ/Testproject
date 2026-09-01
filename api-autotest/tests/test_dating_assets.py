"""Dating 已部署客户端协议、Case 与 Flow 静态验收。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from api.gateway_api import build_payload
from utils.custom.api_loader import build_execution_case, load_api_definitions
from utils.custom.case_loader import load_single_cases
from utils.custom.config_loader import load_yaml
from utils.custom.flow_loader import load_flow_cases
from utils.custom.project_registry import ProjectRegistry
from utils.custom.runtime_context import RuntimeContext


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
    "GetReplyTask": ("tool.dating.DatingAssistantService", "GetReplyTask", "anonymous_session"),
    "GetReplyResult": ("tool.dating.DatingAssistantService", "GetReplyResult", "anonymous_session"),
    "CreateAnalysisTask": ("tool.dating.DatingAssistantService", "CreateAnalysisTask", "anonymous_session"),
    "GetAnalysisTask": ("tool.dating.DatingAssistantService", "GetAnalysisTask", "anonymous_session"),
    "GetAnalysisResult": ("tool.dating.DatingAssistantService", "GetAnalysisResult", "anonymous_session"),
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
    "CreateReplyEvaluationTask": (
        "tool.dating.internal.DatingEvaluationService",
        "CreateReplyEvaluationTask",
        "public",
    ),
    "GetReplyEvaluationTask": (
        "tool.dating.internal.DatingEvaluationService",
        "GetReplyEvaluationTask",
        "public",
    ),
    "GetReplyEvaluationResult": (
        "tool.dating.internal.DatingEvaluationService",
        "GetReplyEvaluationResult",
        "public",
    ),
    "CreateAnalysisEvaluationTask": (
        "tool.dating.internal.DatingEvaluationService",
        "CreateAnalysisEvaluationTask",
        "public",
    ),
    "GetAnalysisEvaluationTask": (
        "tool.dating.internal.DatingEvaluationService",
        "GetAnalysisEvaluationTask",
        "public",
    ),
    "GetAnalysisEvaluationResult": (
        "tool.dating.internal.DatingEvaluationService",
        "GetAnalysisEvaluationResult",
        "public",
    ),
    "GetTaskDebug": (
        "tool.dating.internal.DatingEvaluationService",
        "GetTaskDebug",
        "public",
    ),
    "GetProviderCostSummary": (
        "tool.dating.internal.DatingEvaluationService",
        "GetProviderCostSummary",
        "public",
    ),
}

SUCCESS_ASSERTION = {
    "http_status": 200,
    "gateway": {"message": "ok"},
}


def test_dating_manifest_matches_deployed_public_api_contract() -> None:
    """目录应包含当前客户端 19 个 API 与内部结构化评测 8 个 API。

    ``GetReplyTask/GetReplyResult`` 只服务 Reply；Analysis 仍使用独立的
    ``GetAnalysisTask/GetAnalysisResult``。V1 客户端不再调用 ``DeleteTaskData``。
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
        "delete_user_data_contract",
        "feedback_with_attachments",
        "media_upload_contract",
        "multi_image_analysis",
        "multi_image_reply",
        "reply_association",
        "reply_idempotency_supersede_resume",
        "reply_preferences_lifecycle",
        "structured_analysis_evaluation",
        "structured_reply_evaluation",
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
    assert [step.get("api") for step in interactive_steps if step.get("api")] == [
        "GetMediaUploadConfig",
        "CreateAnalysisTask",
        "GetAnalysisTask",
        "GetAnalysisResult",
        "GetTaskDebug",
        "GetProviderCostSummary",
    ]
    interactive_poll = next(
        step for step in interactive_steps if step.get("api") == "GetAnalysisTask"
    )
    assert interactive_poll["until"]["fail_on_termination"] is True
    assert interactive_poll["until"]["continue_flow_on"] == ["failed"]
    interactive_result = next(
        step for step in interactive_steps if step.get("api") == "GetAnalysisResult"
    )
    assert interactive_result["skip_unless"] == {
        "variable": "analysis_status",
        "equals": "succeeded",
    }

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
        "charming",
        "add_spark",
        "confident",
    ]
    assert reply["runtime_inputs"]["update_preferences__dating_goal"][
        "default_value"
    ] == "relationship"
    assert reply["runtime_inputs"]["update_preferences__your_voice"][
        "default_value"
    ] == "warm"
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
        "GetReplyTask",
        "GetReplyResult",
        "GetTaskDebug",
        "GetProviderCostSummary",
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
    reply_poll = next(
        step for step in reply_steps if step.get("api") == "GetReplyTask"
    )
    assert reply_poll["until"] == {
        "path": "$.status",
        "equals": "succeeded",
        "terminate_on": ["rejected", "failed"],
        "continue_flow_on": ["failed"],
        "fail_on_termination": True,
        "interval_seconds": "{{analysis_poll_interval_seconds}}",
        "timeout_seconds": "{{analysis_timeout_seconds}}",
    }
    reply_scenario = reply["scenario"]["step_data"]
    assert reply_scenario["update_preferences"]["params"] == {
        "dating_goal": "relationship",
        "your_voice": "warm",
        "expected_version": "{{preferences_version}}",
    }
    assert reply_scenario["create_reply"]["params"]["requested_intent"] == "charming"

    # 两个多图 Flow 都必须在正式 Result 后查询诊断与成本；这两个接口只消费
    # 动态 task_id，不应夹带 Evaluation 专属的 case/run 或其他静态参数。
    for flow_id, result_api in {
        "multi_image_analysis": "GetAnalysisResult",
        "multi_image_reply": "GetReplyResult",
    }.items():
        flow_case = flows[flow_id]
        steps = flow_case["flow"]["steps"]
        result_index = next(
            index for index, step in enumerate(steps) if step.get("api") == result_api
        )
        assert [step.get("api") for step in steps[result_index:]] == [
            result_api,
            "GetTaskDebug",
            "GetProviderCostSummary",
        ]
        step_data = flow_case["scenario"]["step_data"]
        assert step_data["get_task_debug"]["params"] == {
            "task_id": "{{task_id}}"
        }
        assert step_data["get_provider_cost"]["params"] == {
            "task_id": "{{task_id}}"
        }
        assert steps[result_index + 1]["until"][
            "retry_on_business_error_codes"
        ] == ["DEBUG_DATA_NOT_READY"]
        assert steps[result_index + 2]["until"][
            "retry_on_business_error_codes"
        ] == ["COST_DATA_PENDING"]

    supported_intents = {"opener", "charming", "add_spark", "confident"}
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

    evaluation_service = "tool.dating.internal.DatingEvaluationService"
    for flow_id, expected_methods in {
        "structured_reply_evaluation": [
            "CreateReplyEvaluationTask",
            "GetReplyEvaluationTask",
            "GetReplyEvaluationResult",
            "GetTaskDebug",
            "GetProviderCostSummary",
        ],
        "structured_analysis_evaluation": [
            "CreateAnalysisEvaluationTask",
            "GetAnalysisEvaluationTask",
            "GetAnalysisEvaluationResult",
            "GetTaskDebug",
            "GetProviderCostSummary",
        ],
    }.items():
        evaluation = flows[flow_id]
        assert evaluation["tags"] == ["interactive", "evaluation"]
        assert [step["api"] for step in evaluation["flow"]["steps"]] == expected_methods
        assert all(step.get("api") != "DeleteTaskData" for step in evaluation["flow"]["steps"])
        assert list(evaluation["runtime_inputs"]) == ["evaluation_request"]
        assert evaluation["runtime_inputs"]["evaluation_request"]["type"] == "json"
        for api_id in expected_methods:
            definition = evaluation["api_definitions"][api_id]
            assert definition["credential_profile"] == "public"
            assert definition["request"]["service_name"] == evaluation_service
            assert definition["transport"]["target"] == "dating_evaluation"
            assert definition["transport"]["envelope"] == "root_single"
            assert definition["transport"]["requires_session"] is False
            assert definition["transport"]["bearer_token_variable"] == (
                "DATING_EVALUATION_API_KEY"
            )
        assert all(
            step["assert"] == SUCCESS_ASSERTION
            for step in evaluation["scenario"]["step_data"].values()
        )
        debug_step = next(
            step for step in evaluation["flow"]["steps"] if step["api"] == "GetTaskDebug"
        )
        cost_step = next(
            step
            for step in evaluation["flow"]["steps"]
            if step["api"] == "GetProviderCostSummary"
        )
        assert debug_step["until"]["retry_on_business_error_codes"] == [
            "DEBUG_DATA_NOT_READY"
        ]
        assert cost_step["until"]["retry_on_business_error_codes"] == [
            "COST_DATA_PENDING"
        ]


def test_dating_client_request_ids_follow_latest_comm_contract() -> None:
    """客户端资产的幂等 ID 只能放在 comm，内部 Evaluation 协议保持原样。"""

    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    definitions = load_api_definitions(package.root)
    for single_case in load_single_cases(package.root):
        definition = definitions[single_case["api_id"]]
        if definition["request"]["service_name"].endswith(
            ".DatingEvaluationService"
        ):
            continue
        params = single_case["execution_case"]["request"]["params"]
        assert "client_request_id" not in params, single_case["id"]

    flows = {item["id"]: item for item in load_flow_cases(package.root)}
    for flow_id, flow_case in flows.items():
        if "evaluation" in flow_case["tags"]:
            continue
        for step_id, step_data in flow_case["scenario"]["step_data"].items():
            assert "client_request_id" not in step_data["params"], (
                flow_id,
                step_id,
            )

    analysis = flows["analysis_idempotency"]["scenario"]["step_data"]
    assert {
        analysis[step_id]["comm"]["client_request_id"]
        for step_id in (
            "create_analysis_first",
            "create_analysis_retry",
            "create_analysis_conflict",
        )
    } == {"{{flow_run_id}}-analysis"}

    deletion = flows["delete_user_data_contract"]["scenario"]["step_data"]
    assert deletion["delete_user_data"]["comm"] == deletion[
        "repeat_delete_user_data"
    ]["comm"]

    reply = flows["reply_idempotency_supersede_resume"]["scenario"]["step_data"]
    assert reply["create_reply_first"]["comm"] == reply[
        "create_reply_retry"
    ]["comm"]
    assert reply["create_reply_replacement"]["comm"] != reply[
        "create_reply_first"
    ]["comm"]


def test_third_fixture_project_validates_without_engine_branch() -> None:
    """第三项目只增加项目包即可通过公共注册表，不需要引擎项目分支。"""
    registry = ProjectRegistry(PROJECT_ROOT / "projects")
    package = registry.get("fixture-demo")

    assert package.project_id == "fixture-demo"
    assert package.manifest.capabilities == ("gateway",)
    assert registry.validate("fixture-demo") == []


def test_evaluation_create_flows_build_protocol_root_payloads() -> None:
    """Reply/Analysis 创建步骤必须生成评测协议规定的根级请求。

    这项测试直接加载真实 Flow、Scenario 和 API 定义，防止资产间组合后又退回
    客户端 Gateway 的 ``comm/requests`` 信封，或把交互输入错误地包在
    ``params.input`` 中。运行标识仍由引擎生成并覆盖交互 JSON，避免用户输入
    破坏任务幂等关系。
    """

    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    runtime = RuntimeContext({"flow_run_id": "run-20260831-001"})
    contracts = {
        "structured_reply_evaluation": {
            "step_id": "create_reply_evaluation",
            "method_name": "CreateReplyEvaluationTask",
            "reason": "automated Reply evaluation",
            "business_keys": {
                "locale",
                "dating_goal",
                "your_voice",
                "requested_intent",
                "background",
                "transcript",
            },
        },
        "structured_analysis_evaluation": {
            "step_id": "create_analysis_evaluation",
            "method_name": "CreateAnalysisEvaluationTask",
            "reason": "automated Analysis evaluation",
            "business_keys": {"locale", "transcript"},
        },
    }

    for flow_id, contract in contracts.items():
        flow_case = load_flow_cases(package.root, flow_id)[0]
        flow_step = next(
            step
            for step in flow_case["flow"]["steps"]
            if step["id"] == contract["step_id"]
        )
        step_data = flow_case["scenario"]["step_data"][contract["step_id"]]
        api_definition = flow_case["api_definitions"][flow_step["api"]]
        execution_case = build_execution_case(
            api_definition,
            deepcopy(step_data["params"]),
            deepcopy(step_data["assert"]),
            extract=deepcopy(flow_step.get("extract") or {}),
        )

        payload = build_payload({}, execution_case, runtime)

        assert set(payload) == {
            "service_name",
            "method_name",
            "client_request_id",
            "reason",
            "params",
        }
        assert payload["service_name"] == (
            "tool.dating.internal.DatingEvaluationService"
        )
        assert payload["method_name"] == contract["method_name"]
        assert payload["reason"] == contract["reason"]
        assert "comm" not in payload and "requests" not in payload

        params = payload["params"]
        assert "input" not in params
        assert contract["business_keys"].issubset(params)
        assert {"case_id", "run_id", "client_request_id"}.issubset(params)
        assert payload["client_request_id"] == params["client_request_id"]

        messages = params["transcript"]["messages"]
        assert len(messages) >= 4
        assert sum(item["speaker"] == "user" for item in messages) >= 2
        assert sum(item["speaker"] == "other" for item in messages) >= 2


def test_dating_upload_fixture_media_type_matches_declared_content_type() -> None:
    """签名上传的声明类型必须与真实文件魔数一致，避免真实 PUT 被对象存储拒绝。"""

    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    fixture = package.fixtures_dir / "chat-sample.png"
    scenario = load_yaml(
        package.scenarios_dir / "analysis_idempotency.yaml"
    )

    assert fixture.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert scenario["step_data"]["prepare_upload"]["params"]["content_type"] == "image/png"
