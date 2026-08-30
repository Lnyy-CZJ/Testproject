"""Truthy 根资产一次性迁移后的规范化清单与唯一真源测试。"""

from __future__ import annotations

from pathlib import Path

from utils.custom.api_loader import load_api_definitions
from utils.custom.case_loader import load_single_cases
from utils.custom.flow_loader import load_flow_cases
from utils.custom.project_registry import ProjectRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_truthy_assets_have_single_project_source_and_preserved_inventory() -> None:
    """迁移后根 data 必须消失，API/Case/Flow ID 与迁移前基线保持一致。"""
    assert not (PROJECT_ROOT / "data").exists()
    package = ProjectRegistry(PROJECT_ROOT / "projects").get("truthy")

    assert set(load_api_definitions(package.root)) == {
        "CompleteMediaUpload",
        "CreateAnonymousSession",
        "CreateIntentTask",
        "GetEntitlement",
        "GetMe",
        "GetMediaUploadConfig",
        "GetProviderCostSummary",
        "GetSearchTaskDebug",
        "GetSubscriptionStatus",
        "GetTask",
        "GetTaskCandidateDetail",
        "ListTaskCandidates",
        "PrepareMediaUpload",
        "RefreshSession",
    }
    assert {item["id"] for item in load_single_cases(package.root)} == {
        "CreateAnonymousSession::create_anonymous_session_success",
        "GetEntitlement::get_entitlement_success",
        "GetMe::get_me_success",
        "GetMediaUploadConfig::get_media_upload_config_success",
        "GetSubscriptionStatus::get_subscription_status_success",
    }
    assert {item["id"] for item in load_flow_cases(package.root)} == {
        "AnonymousSessionMediaSearch",
        "NameWithConditionsAndPhotoSearch",
        "NameWithConditionsSearch",
    }
    assert {path.name for path in package.fixtures_dir.iterdir() if path.is_file()} == {
        "asynccode.jpeg",
        "IMG_0031.jpeg",
        "JayShetty.jpeg",
        "media_aa75ca2a75b2ef4b1f5f8d29 (1).jpg",
        "media_c22496643ebabcc7cb32ca64.jpg",
        "RohitSingh.png",
    }
