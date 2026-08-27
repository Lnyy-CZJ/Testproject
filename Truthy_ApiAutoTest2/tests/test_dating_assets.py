"""Dating P0 项目包协议、Case 与 Flow 静态验收。"""

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
    "GetMediaUploadConfig": ("tool.dating.DatingMediaService", "GetMediaUploadConfig", "anonymous_session"),
    "PrepareMediaUpload": ("tool.dating.DatingMediaService", "PrepareMediaUpload", "anonymous_session"),
    "CompleteMediaUpload": ("tool.dating.DatingMediaService", "CompleteMediaUpload", "anonymous_session"),
    "CreateAnalysisTask": ("tool.dating.DatingAssistantService", "CreateAnalysisTask", "anonymous_session"),
    "GetAnalysisTask": ("tool.dating.DatingAssistantService", "GetAnalysisTask", "anonymous_session"),
    "GetAnalysisResult": ("tool.dating.DatingAssistantService", "GetAnalysisResult", "anonymous_session"),
    "DeleteTaskData": ("tool.dating.DatingAssistantService", "DeleteTaskData", "anonymous_session"),
    "GetQuotaStatus": ("tool.subscription.SubscriptionService", "GetQuotaStatus", "anonymous_session"),
}


def test_dating_manifest_and_exact_eleven_api_contract() -> None:
    """Dating 首期必须只暴露裁决后的 11 个 API，旧任务方法名不得残留。"""
    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    definitions = load_api_definitions(package.root)

    assert set(definitions) == set(EXPECTED_APIS)
    assert "GetTask" not in definitions
    assert "GetTaskResult" not in definitions
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


def test_dating_has_cases_and_two_p0_flows_with_success_gated_result_cleanup() -> None:
    """P0 Flow 只在成功后读取结果，并在失败或超时路径声明清理。"""
    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    cases = load_single_cases(package.root)
    flows = {item["id"]: item for item in load_flow_cases(package.root)}

    assert {item["api_id"] for item in cases} == {
        "CreateAnonymousSession",
        "GetMe",
        "GetMediaUploadConfig",
        "GetQuotaStatus",
    }
    assert set(flows) == {
        "anonymous_session_refresh",
        "single_image_analysis_happy_path",
    }
    refresh_api_ids = [step.get("api") for step in flows["anonymous_session_refresh"]["flow"]["steps"]]
    assert refresh_api_ids == [
        "CreateAnonymousSession",
        "GetMe",
        "RefreshSession",
        "GetMe",
    ]
    analysis_steps = flows["single_image_analysis_happy_path"]["flow"]["steps"]
    result_step = next(step for step in analysis_steps if step.get("api") == "GetAnalysisResult")
    cleanup_step = next(step for step in analysis_steps if step.get("api") == "DeleteTaskData")
    poll_step = next(step for step in analysis_steps if step.get("api") == "GetAnalysisTask")
    assert result_step["skip_unless"] == {"variable": "analysis_status", "equals": "succeeded"}
    assert cleanup_step["run_on_termination"] is True
    assert poll_step["until"]["terminate_on"] == ["rejected", "failed"]
    assert poll_step["until"]["interval_seconds"] == "{{analysis_poll_interval_seconds}}"
    assert poll_step["until"]["timeout_seconds"] == "{{analysis_timeout_seconds}}"


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
        package.scenarios_dir / "single_image_analysis_happy_path.yaml"
    )

    assert fixture.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert scenario["step_data"]["prepare_upload"]["params"]["content_type"] == "image/png"
