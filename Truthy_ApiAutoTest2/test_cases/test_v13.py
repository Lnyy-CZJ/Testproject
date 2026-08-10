"""V1.3 阶段 0：旧数据结构与 Flow 合并结果迁移基线。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from utils.custom.config_loader import load_yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _legacy_deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    """复刻 V1.2 FlowRunner 的递归合并规则，仅用于阶段 0 迁移快照。

    参数说明:
        base: 旧 case 中的默认参数或断言。
        override: 旧 Scenario 中的步骤覆盖数据。

    返回值:
        深拷贝后的合并结果，后者覆盖前者。

    说明:
        V1.3 FlowRunner 不再执行合并；该函数留在测试中用于验证迁移前基线。
    """
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _legacy_deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _success_assert(
    data_fields: list[str],
    data_equals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造当前成功 case 使用的完整断言快照。

    功能说明:
        复用旧 case 共同的 HTTP、Gateway 和业务子响应成功断言，减少测试
        快照中的无意义重复，同时保留每个接口独立的 data_fields。

    参数说明:
        data_fields: 业务响应 data 下必须存在的字段列表。
        data_equals: 可选的 Flow 场景值断言。

    返回值:
        可直接与 YAML ``assert`` 节点比较的独立字典。
    """
    assertions: dict[str, Any] = {
        "http_status": 200,
        "gateway": {"code": 0, "message": "ok"},
        "response": {
            "id": "req_0",
            "success": True,
            "code": 0,
            "message": "ok",
        },
        "data_fields": data_fields,
    }
    if data_equals is not None:
        assertions["data_equals"] = data_equals
    return assertions


# 阶段 0 固定当前 12 个旧 case 的完整核心数据。后续迁移测试应以该快照为准，
# 不再依赖已经被 V1.3 数据替换的旧 YAML 文件。
LEGACY_CASE_SNAPSHOT: dict[str, dict[str, Any]] = {
    "01_CreateAnonymousSession.yaml": {
        "name": "创建匿名会话",
        "tags": ["identity", "post"],
        "request": {
            "service_name": "tool.identity.IdentityService",
            "method_name": "CreateAnonymousSession",
            "params": {
                "consent_policy_version": "{{consent_policy_version}}",
            },
        },
        "assert": _success_assert(
            [
                "access_token",
                "expires_time",
                "is_new_user",
                "refresh_expires_time",
                "refresh_token",
                "user_id",
            ]
        ),
        "extract": {
            "access_token": "$.access_token",
            "expires_time": "$.expires_time",
            "refresh_token": "$.refresh_token",
            "refresh_expires_time": "$.refresh_expires_time",
            "user_id": "$.user_id",
        },
    },
    "02_RefreshSession.yaml": {
        "name": "刷新匿名会话 Token",
        "tags": ["identity", "post"],
        "flow_only": True,
        "request": {
            "service_name": "tool.identity.IdentityService",
            "method_name": "RefreshSession",
            "params": {
                "refresh_token": "{{refresh_token}}",
            },
        },
        "assert": _success_assert(
            [
                "access_token",
                "expires_time",
                "refresh_expires_time",
                "refresh_token",
                "user_id",
            ]
        ),
        "extract": {
            "access_token": "$.access_token",
            "expires_time": "$.expires_time",
            "refresh_token": "$.refresh_token",
            "refresh_expires_time": "$.refresh_expires_time",
            "user_id": "$.user_id",
        },
    },
    "03_GetMe.yaml": {
        "name": "获取当前用户",
        "tags": ["smoke", "identity"],
        "request": {
            "service_name": "tool.identity.IdentityService",
            "method_name": "GetMe",
            "params": {},
        },
        "assert": _success_assert(
            [
                "acquisition_summary",
                "consent_policy_version",
                "create_time",
                "device_id",
                "profile_summary",
                "subscription_summary",
                "user_id",
                "user_type",
            ]
        ),
    },
    "04_GetSubscriptionStatus.yaml": {
        "name": "查询订阅状态",
        "tags": ["subscription", "post"],
        "request": {
            "service_name": "tool.subscription.SubscriptionService",
            "method_name": "GetSubscriptionStatus",
            "params": {
                "product_code": "people_insight",
                "scenario": "search",
            },
        },
        "assert": _success_assert(
            [
                "entitlement",
                "expires_time",
                "has_active_subscription",
                "plan_code",
                "product_code",
                "subscription_status",
                "tier_code",
                "vip_level",
            ]
        ),
    },
    "05_GetEntitlement.yaml": {
        "name": "获取当前订阅权益",
        "tags": ["subscription", "post"],
        "request": {
            "service_name": "tool.subscription.SubscriptionService",
            "method_name": "GetEntitlement",
            "params": {
                "product_code": "people_insight",
            },
        },
        "assert": _success_assert(
            [
                "can_start_search",
                "concurrency_remaining",
                "decision",
                "expires_time",
                "plan_code",
                "product_code",
                "quota_remaining",
                "subscription_status",
                "vip_level",
            ]
        ),
    },
    "06_GetMediaUploadConfig.yaml": {
        "name": "获取媒体上传配置",
        "tags": ["media", "post"],
        "request": {
            "service_name": "tool.people_insight.MediaService",
            "method_name": "GetMediaUploadConfig",
            "params": {},
        },
        "assert": _success_assert(
            [
                "allowed_content_types",
                "asset_ttl_seconds",
                "cache_expires_time",
                "complete_retry",
                "config_cache_ttl_seconds",
                "config_version",
                "face_detection_required",
                "max_size_bytes",
                "recommended_jpeg_quality",
                "recommended_max_height",
                "recommended_max_width",
                "strip_exif",
                "upload_url_ttl_seconds",
            ]
        ),
    },
    "07_PrepareMediaUpload.yaml": {
        "name": "准备媒体上传",
        "tags": ["media", "post"],
        "flow_only": True,
        "request": {
            "service_name": "tool.people_insight.MediaService",
            "method_name": "PrepareMediaUpload",
            "params": {
                "client_request_id": "{{client_request_id}}",
                "content_type": "image/jpeg",
                "size_bytes": "{{media_size_bytes}}",
            },
        },
        "assert": _success_assert(
            [
                "content_type",
                "expires_time",
                "max_size_bytes",
                "media_asset_id",
                "size_bytes",
                "status",
                "upload_headers",
                "upload_method",
                "upload_url",
            ]
        ),
        "extract": {
            "upload_url": "$.upload_url",
            "upload_headers": "$.upload_headers",
            "media_asset_id": "$.media_asset_id",
        },
    },
    "08_CompleteMediaUpload.yaml": {
        "name": "完成媒体上传",
        "tags": ["media", "post"],
        "flow_only": True,
        "request": {
            "service_name": "tool.people_insight.MediaService",
            "method_name": "CompleteMediaUpload",
            "params": {
                "media_asset_id": "{{media_asset_id}}",
            },
        },
        "assert": _success_assert(
            [
                "content_type",
                "expires_time",
                "media_asset_id",
                "size_bytes",
                "status",
                "upload_expires_time",
                "uploaded_time",
            ]
        ),
    },
    "09_CreateIntentTask.yaml": {
        "name": "创建并启动线索搜索任务",
        "tags": ["search", "post"],
        "flow_only": True,
        "request": {
            "service_name": "tool.people_insight.SearchService",
            "method_name": "CreateIntentTask",
            "params": {
                "client_request_id": "{{client_request_id}}",
                "match_strategy": "UNION",
                "clues": [
                    {
                        "type": "FULL_NAME",
                        "full_name_query": {
                            "full_name": "JOJO CCQQ MOCK",
                        },
                    },
                    {
                        "type": "LOCATION",
                        "location_query": {
                            "location": "us",
                        },
                    },
                    {
                        "type": "SOCIAL_LINK",
                        "social_link_query": {
                            "url": (
                                "https://www.linkedin.com/search/results/people/"
                                "?keywords=John%20Smith%20photographer"
                            ),
                            "platform_hint": "linkedin",
                        },
                    },
                    {
                        "type": "SOCIAL_LINK",
                        "social_link_query": {
                            "url": "https://x.com",
                            "platform_hint": "twitter",
                        },
                    },
                    {
                        "type": "PHOTO",
                        "photo_query": {
                            "media_asset_id": "{{media_asset_id}}",
                            "photo_type_hint": "face",
                        },
                    },
                ],
                "additional_details": [
                    {"type": "PROFESSION", "value": "aa"},
                    {"type": "EMPLOYER", "value": "bb"},
                    {"type": "SCHOOL", "value": "cc"},
                    {"type": "OTHER", "value": "dd"},
                ],
            },
        },
        "assert": _success_assert(
            [
                "accepted_query_type",
                "additional_details",
                "cache_hit",
                "can_start_real_search",
                "clue_types",
                "entitlement_decision",
                "expires_time",
                "match_strategy",
                "status",
                "task_id",
            ]
        ),
        "extract": {
            "task_id": "$.task_id",
        },
    },
    "10_GetTask.yaml": {
        "name": "获取搜索任务状态",
        "tags": ["search", "post"],
        "flow_only": True,
        "request": {
            "service_name": "tool.people_insight.SearchService",
            "method_name": "GetTask",
            "params": {
                "task_id": "{{task_id}}",
            },
        },
        "assert": _success_assert(
            [
                "cache_hit",
                "candidate_confidence_scores",
                "candidate_count",
                "error_code",
                "failure_reason",
                "has_additional_clues",
                "is_initial_search",
                "no_result_reason",
                "progress",
                "provider_execution",
                "provider_summary",
                "result_type",
                "status",
                "task_id",
                "top_confidence_score",
                "update_time",
            ]
        ),
    },
    "11_ListTaskCandidates.yaml": {
        "name": "查询任务候选集列表",
        "tags": ["search", "post"],
        "flow_only": True,
        "request": {
            "service_name": "tool.people_insight.SearchService",
            "method_name": "ListTaskCandidates",
            "params": {
                "task_id": "{{task_id}}",
                "page": {
                    "page_size": 10,
                    "page_token": "",
                },
            },
        },
        "assert": _success_assert(
            [
                "empty_reason",
                "items",
                "next_page_token",
                "provider_summary",
                "task_id",
                "update_time",
            ]
        ),
        "extract": {
            "candidate_id": "$.items[0].candidate_id",
        },
    },
    "12_GetTaskCandidateDetail.yaml": {
        "name": "获取单个候选详情",
        "tags": ["search", "post"],
        "flow_only": True,
        "request": {
            "service_name": "tool.people_insight.SearchService",
            "method_name": "GetTaskCandidateDetail",
            "params": {
                "task_id": "{{task_id}}",
                "candidate_id": "{{candidate_id}}",
            },
        },
        "assert": _success_assert(
            [
                "candidate",
                "candidate_id",
                "disclaimers",
                "entitlement_decision",
                "evidence",
                "person_id",
                "social_accounts",
                "task_id",
                "ui_sections",
                "update_time",
            ]
        ),
    },
}


LEGACY_FLOW_SNAPSHOT: dict[str, Any] = {
    "name": "搜索流程",
    "tags": ["flow", "media", "search"],
    "steps": [
        {
            "id": "create_task",
            "call": "CreateIntentTask.yaml",
            "extract": {"task_id": "$.task_id"},
        },
        {
            "id": "poll_task",
            "call": "GetTask.yaml",
            "until": {
                # 这是迁移前实际配置；V1.3 数据迁移时再按 PRD 改为 $.status。
                "path": "$.data.status",
                "equals": "SUCCEEDED",
                "interval_seconds": 2,
                "timeout_seconds": 120,
            },
        },
        {
            "id": "list_candidates",
            "call": "ListTaskCandidates.yaml",
            "extract": {"candidate_id": "$.items[0].candidate_id"},
        },
        {
            "id": "candidate_detail",
            "call": "GetTaskCandidateDetail.yaml",
        },
    ],
}


LEGACY_SCENARIO_SNAPSHOT: dict[str, Any] = {
    "name": "姓名搜索成功场景",
    "step_data": {
        "create_task": {
            "params": {
                "match_strategy": "UNION",
                "clues": [
                    {
                        "type": "FULL_NAME",
                        "full_name_query": {
                            "full_name": "JOJO CCQQ MOCK",
                        },
                    }
                ],
                "additional_details": [],
            },
            "assert": {
                "data_equals": {
                    "status": "QUEUED",
                }
            },
        },
        "poll_task": {
            "assert": {
                "data_equals": {
                    "status": "SUCCEEDED",
                }
            },
        },
    },
}


# Flow 中 call 使用无前缀名称，当前真实文件带数字前缀。该映射只用于计算
# 迁移前原本希望执行的 case，不能用于修复现有 FlowLoader。
LEGACY_CALL_TO_FILE = {
    "CreateIntentTask.yaml": "09_CreateIntentTask.yaml",
    "GetTask.yaml": "10_GetTask.yaml",
    "ListTaskCandidates.yaml": "11_ListTaskCandidates.yaml",
    "GetTaskCandidateDetail.yaml": "12_GetTaskCandidateDetail.yaml",
}


LEGACY_FLOW_FINAL_SNAPSHOT: dict[str, dict[str, Any]] = {
    "create_task": {
        "call": "CreateIntentTask.yaml",
        "params": {
            "client_request_id": "{{client_request_id}}",
            "match_strategy": "UNION",
            "clues": [
                {
                    "type": "FULL_NAME",
                    "full_name_query": {
                        "full_name": "JOJO CCQQ MOCK",
                    },
                }
            ],
            "additional_details": [],
        },
        "assert": _success_assert(
            [
                "accepted_query_type",
                "additional_details",
                "cache_hit",
                "can_start_real_search",
                "clue_types",
                "entitlement_decision",
                "expires_time",
                "match_strategy",
                "status",
                "task_id",
            ],
            data_equals={"status": "QUEUED"},
        ),
        "extract": {"task_id": "$.task_id"},
    },
    "poll_task": {
        "call": "GetTask.yaml",
        "params": {
            "task_id": "{{task_id}}",
        },
        "assert": _success_assert(
            [
                "cache_hit",
                "candidate_confidence_scores",
                "candidate_count",
                "error_code",
                "failure_reason",
                "has_additional_clues",
                "is_initial_search",
                "no_result_reason",
                "progress",
                "provider_execution",
                "provider_summary",
                "result_type",
                "status",
                "task_id",
                "top_confidence_score",
                "update_time",
            ],
            data_equals={"status": "SUCCEEDED"},
        ),
        "extract": {},
    },
    "list_candidates": {
        "call": "ListTaskCandidates.yaml",
        "params": {
            "task_id": "{{task_id}}",
            "page": {
                "page_size": 10,
                "page_token": "",
            },
        },
        "assert": _success_assert(
            [
                "empty_reason",
                "items",
                "next_page_token",
                "provider_summary",
                "task_id",
                "update_time",
            ]
        ),
        "extract": {"candidate_id": "$.items[0].candidate_id"},
    },
    "candidate_detail": {
        "call": "GetTaskCandidateDetail.yaml",
        "params": {
            "task_id": "{{task_id}}",
            "candidate_id": "{{candidate_id}}",
        },
        "assert": _success_assert(
            [
                "candidate",
                "candidate_id",
                "disclaimers",
                "entitlement_decision",
                "evidence",
                "person_id",
                "social_accounts",
                "task_id",
                "ui_sections",
                "update_time",
            ]
        ),
        "extract": {},
    },
}


def _calculate_legacy_flow_final_data(
    flow: dict[str, Any],
    scenario: dict[str, Any],
    cases: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """按 V1.2 实际递归合并规则计算 Flow 每个调用步骤的最终数据。

    参数说明:
        flow: 迁移前 Flow YAML 根对象。
        scenario: 迁移前同名 Scenario YAML 根对象。
        cases: 迁移前全部 case，以真实文件名索引。

    返回值:
        以 step ID 为 key，包含 call、最终 params、最终 assert 和 extract
        的迁移基线。

    异常说明:
        KeyError: Flow 引用没有对应的旧 case 映射时抛出，提示迁移基线不完整。
    """
    final_data: dict[str, dict[str, Any]] = {}
    step_data = scenario.get("step_data") or {}

    for step in flow.get("steps") or []:
        if "call" not in step:
            continue
        step_id = str(step["id"])
        call_name = str(step["call"])
        case = cases[LEGACY_CALL_TO_FILE[call_name]]
        configured = step_data.get(step_id) or {}
        final_data[step_id] = {
            "call": call_name,
            "params": _legacy_deep_merge(
                deepcopy((case.get("request") or {}).get("params") or {}),
                deepcopy(configured.get("params") or {}),
            ),
            "assert": _legacy_deep_merge(
                deepcopy(case.get("assert") or {}),
                deepcopy(configured.get("assert") or {}),
            ),
            "extract": deepcopy(step.get("extract") or {}),
        }
    return final_data


def test_phase_zero_snapshot_covers_all_legacy_cases() -> None:
    """阶段 0 历史快照应完整覆盖迁移前 12 个旧 case。"""
    assert len(LEGACY_CASE_SNAPSHOT) == 12
    assert {
        case["request"]["method_name"]
        for case in LEGACY_CASE_SNAPSHOT.values()
    } == {
        "CreateAnonymousSession",
        "RefreshSession",
        "GetMe",
        "GetSubscriptionStatus",
        "GetEntitlement",
        "GetMediaUploadConfig",
        "PrepareMediaUpload",
        "CompleteMediaUpload",
        "CreateIntentTask",
        "GetTask",
        "ListTaskCandidates",
        "GetTaskCandidateDetail",
    }


def test_phase_zero_snapshot_records_flow_and_scenario() -> None:
    """阶段 0 历史快照应固定旧 Flow 顺序、引用、提取和场景覆盖。"""
    assert [step["id"] for step in LEGACY_FLOW_SNAPSHOT["steps"]] == [
        "create_task",
        "poll_task",
        "list_candidates",
        "candidate_detail",
    ]


def test_phase_zero_snapshot_records_final_flow_params_and_assertions() -> None:
    """V1.2 合并后的四个接口步骤应与显式迁移快照完全一致。"""
    actual_final_data = _calculate_legacy_flow_final_data(
        LEGACY_FLOW_SNAPSHOT,
        LEGACY_SCENARIO_SNAPSHOT,
        LEGACY_CASE_SNAPSHOT,
    )

    assert actual_final_data == LEGACY_FLOW_FINAL_SNAPSHOT
    assert set(actual_final_data) == {
        "create_task",
        "poll_task",
        "list_candidates",
        "candidate_detail",
    }


def test_phase_six_migration_preserves_all_legacy_api_routes() -> None:
    """新增 API 后，历史 case 提取出的全部业务路由仍必须保留。"""
    from utils.custom.api_loader import load_api_definitions

    definitions = load_api_definitions(PROJECT_ROOT)
    expected = {
        case["request"]["method_name"]: {
            "name": case["name"],
            "request": {
                "service_name": case["request"]["service_name"],
                "method_name": case["request"]["method_name"],
            },
        }
        for case in LEGACY_CASE_SNAPSHOT.values()
    }

    assert set(expected).issubset(definitions)
    for api_id, expected_definition in expected.items():
        assert definitions[api_id]["name"] == expected_definition["name"]
        assert definitions[api_id]["request"] == expected_definition["request"]


def test_phase_six_migration_preserves_five_independent_cases() -> None:
    """5 个可独立执行的旧 case 应完整保留参数、断言、标签和提取规则。"""
    from utils.custom.case_loader import load_single_cases

    independent_files = {
        "01_CreateAnonymousSession.yaml",
        "03_GetMe.yaml",
        "04_GetSubscriptionStatus.yaml",
        "05_GetEntitlement.yaml",
        "06_GetMediaUploadConfig.yaml",
    }
    expected_by_api = {
        LEGACY_CASE_SNAPSHOT[file_name]["request"]["method_name"]:
        LEGACY_CASE_SNAPSHOT[file_name]
        for file_name in independent_files
    }

    migrated_cases = load_single_cases(PROJECT_ROOT)

    assert len(migrated_cases) == 5
    assert {case["api_id"] for case in migrated_cases} == set(expected_by_api)
    for migrated in migrated_cases:
        expected = expected_by_api[migrated["api_id"]]
        assert migrated["name"] == expected["name"]
        assert migrated["tags"] == expected["tags"]
        assert migrated["execution_case"]["request"]["params"] == (
            expected["request"]["params"]
        )
        assert migrated["execution_case"]["assert"] == expected["assert"]
        assert migrated["execution_case"]["extract"] == expected.get("extract", {})


def test_phase_six_migration_removes_legacy_case_files_and_flow_only() -> None:
    """迁移后只保留 5 个无前缀 Case 集合，且不再出现 flow_only。"""
    case_paths = sorted((PROJECT_ROOT / "data" / "cases").glob("*.yaml"))

    assert {path.name for path in case_paths} == {
        "CreateAnonymousSession.yaml",
        "GetMe.yaml",
        "GetSubscriptionStatus.yaml",
        "GetEntitlement.yaml",
        "GetMediaUploadConfig.yaml",
    }
    assert all(not path.name[0].isdigit() for path in case_paths)
    assert all("flow_only" not in load_yaml(path) for path in case_paths)


def test_phase_six_migration_preserves_legacy_flow_routes_and_extracts() -> None:
    """扩展 Flow 后，历史业务步骤的 API 路由与提取规则仍必须保留。"""
    from utils.custom.flow_loader import load_flow_cases

    flow_case = load_flow_cases(
        PROJECT_ROOT,
        selected_flow="AnonymousSessionMediaSearch",
    )[0]
    flow = flow_case["flow"]
    scenario_step_data = flow_case["scenario"]["step_data"]
    actual: dict[str, dict[str, Any]] = {}
    for step in flow["steps"]:
        step_id = step["id"]
        configured = scenario_step_data[step_id]
        actual[step_id] = {
            "api": step["api"],
            "params": configured["params"],
            "assert": configured["assert"],
            "extract": step.get("extract") or {},
        }

    expected = {
        step_id: {
            "api": Path(snapshot["call"]).stem,
            "params": snapshot["params"],
            "assert": snapshot["assert"],
            "extract": snapshot["extract"],
        }
        for step_id, snapshot in LEGACY_FLOW_FINAL_SNAPSHOT.items()
    }
    # 无候选人是正常结果：list_candidates 的提取规则已由 extract 迁移为
    # optional_extract（见下方断言），此处基线跟随当前 Flow 结构放宽为空，
    # 不改动 LEGACY_FLOW_FINAL_SNAPSHOT 本身（它仍是 V1.2 迁移冻结基线）。
    expected["list_candidates"]["extract"] = {}

    for step_id, expected_step in expected.items():
        assert step_id in actual
        assert actual[step_id]["api"] == expected_step["api"]
        assert actual[step_id]["extract"] == expected_step["extract"]
    poll_step = next(step for step in flow["steps"] if step["id"] == "poll_task")
    assert poll_step["until"]["path"] == "$.status"

    # 空结果扩展行为必须固化：items[0] 不存在时不再强制提取，
    # 候选人详情步骤依据列表为空原因条件跳过。
    list_step = next(step for step in flow["steps"] if step["id"] == "list_candidates")
    assert list_step.get("optional_extract") == {
        "candidate_id": "$.items[0].candidate_id",
        "list_empty_reason": "$.empty_reason",
    }
    detail_step = next(step for step in flow["steps"] if step["id"] == "candidate_detail")
    assert detail_step.get("skip_if") == {
        "variable": "list_empty_reason",
        "equals": "NO_CANDIDATES",
    }


def test_name_with_conditions_flow_uses_non_photo_create_task_clues() -> None:
    """姓名附加条件 Flow 应复用链路，并只传递声明的非照片线索。"""
    from utils.custom.flow_loader import load_flow_cases

    flow_case = load_flow_cases(
        PROJECT_ROOT,
        selected_flow="NameWithConditionsSearch",
    )[0]
    steps = flow_case["flow"]["steps"]
    create_params = flow_case["scenario"]["step_data"]["create_task"]["params"]

    assert [step["api"] for step in steps] == [
        "CreateIntentTask",
        "GetTask",
        "ListTaskCandidates",
        "GetTaskCandidateDetail",
        "GetSearchTaskDebug",
        "GetProviderCostSummary",
    ]
    assert [clue["type"] for clue in create_params["clues"]] == [
        "FULL_NAME",
        "LOCATION",
        "SOCIAL_LINK",
    ]
    assert (
        create_params["clues"][0]["full_name_query"]["full_name"]
        == "JOJO CCQQ MOCK"
    )
    assert create_params["clues"][2]["social_link_query"]["url"] == (
        "https://www.linkedin.com/in/jojo-CCQQ-mock-1"
    )
    assert [item["type"] for item in create_params["additional_details"]] == [
        "PROFESSION",
        "EMPLOYER",
        "SCHOOL",
        "OTHER",
    ]


def test_name_with_conditions_and_photo_flow_has_media_upload_prerequisites() -> None:
    """照片搜索 Flow 应先完成上传，并将返回的媒体 ID 传给创建搜索任务。

    功能说明:
        校验 YAML 编排顺序、Prepare 响应提取和 PHOTO 线索引用，避免 PUT
        上传被放在签名 URL 生成之前，或 CreateIntentTask 使用错误的媒体变量。

    返回值:
        无；配置不满足约定时由断言抛出异常。
    """
    from utils.custom.flow_loader import load_flow_cases

    flow_case = load_flow_cases(
        PROJECT_ROOT,
        selected_flow="NameWithConditionsAndPhotoSearch",
    )[0]
    steps = flow_case["flow"]["steps"]
    scenario = flow_case["scenario"]
    create_params = scenario["step_data"]["create_task"]["params"]

    assert [
        (step["id"], step.get("api") or step.get("action")) for step in steps
    ] == [
        ("get_media_upload_config", "GetMediaUploadConfig"),
        ("prepare_media_upload", "PrepareMediaUpload"),
        ("upload_media", "prepared_media_upload"),
        ("complete_media_upload", "CompleteMediaUpload"),
        ("create_task", "CreateIntentTask"),
        ("poll_task", "GetTask"),
        ("list_candidates", "ListTaskCandidates"),
        ("candidate_detail", "GetTaskCandidateDetail"),
        ("search_task_debug", "GetSearchTaskDebug"),
        ("provider_cost_summary", "GetProviderCostSummary"),
    ]
    assert scenario["variables"]["media_file"].startswith("data/photo/")
    assert steps[1]["extract"] == {
        "upload_url": "$.upload_url",
        "upload_headers": "$.upload_headers",
        "media_asset_id": "$.media_asset_id",
    }
    assert scenario["step_data"]["prepare_media_upload"]["params"] == {
        "client_request_id": "{{client_request_id}}",
        "content_type": "image/jpeg",
        "size_bytes": "{{media_size_bytes}}",
    }
    assert [clue["type"] for clue in create_params["clues"]] == [
        "FULL_NAME",
        "SOCIAL_LINK",
        "PHOTO",
    ]
    assert create_params["clues"][-1]["photo_query"] == {
        "media_asset_id": "{{media_asset_id}}",
        "photo_type_hint": "face",
    }


def _write_api_definition(
    root: Path,
    file_name: str,
    content: Any,
) -> Path:
    """写入阶段 1 测试使用的临时 API YAML。

    功能说明:
        在 pytest 的临时目录中构造 API 定义，不修改项目真实数据目录。

    参数说明:
        root: pytest 提供的临时项目根目录。
        file_name: API YAML 文件名。
        content: 需要序列化的 YAML 数据，可用于构造合法或非法根节点。

    返回值:
        已写入的 API 文件路径。
    """
    apis_directory = root / "data" / "apis"
    apis_directory.mkdir(parents=True, exist_ok=True)
    api_path = apis_directory / file_name
    api_path.write_text(
        yaml.safe_dump(content, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return api_path


def _api_definition(
    api_id: str,
    service_name: str = "service.Demo",
    method_name: str = "Demo",
) -> dict[str, Any]:
    """构造阶段 1 测试使用的最小合法 API 定义。

    参数说明:
        api_id: API 唯一标识，同时应与文件名 stem 一致。
        service_name: Gateway 业务服务名称。
        method_name: Gateway 业务方法名称。

    返回值:
        包含 id、name 和 request 路由的独立字典。
    """
    return {
        "id": api_id,
        "name": f"{api_id} 接口",
        "request": {
            "service_name": service_name,
            "method_name": method_name,
        },
    }


def test_api_loader_loads_multiple_definitions(tmp_path: Path) -> None:
    """API Loader 应加载多个定义，并记录用于报错的相对来源路径。"""
    from utils.custom.api_loader import load_api_definitions

    _write_api_definition(
        tmp_path,
        "First.yaml",
        _api_definition("First", "service.First", "CallFirst"),
    )
    _write_api_definition(
        tmp_path,
        "Second.yaml",
        _api_definition("Second", "service.Second", "CallSecond"),
    )

    definitions = load_api_definitions(tmp_path)

    assert list(definitions) == ["First", "Second"]
    assert definitions["First"]["request"] == {
        "service_name": "service.First",
        "method_name": "CallFirst",
    }
    assert definitions["First"]["_source"] == "data/apis/First.yaml"
    assert definitions["Second"]["_source"] == "data/apis/Second.yaml"


def test_api_loader_rejects_file_name_mismatch(tmp_path: Path) -> None:
    """API ID 与文件名不一致时应在加载阶段失败。"""
    from utils.custom.api_loader import ApiConfigError, load_api_definitions

    _write_api_definition(tmp_path, "FileName.yaml", _api_definition("OtherId"))

    with pytest.raises(
        ApiConfigError,
        match=r"FileName\.yaml.*id.*OtherId",
    ):
        load_api_definitions(tmp_path)


def test_api_loader_reports_duplicate_id_before_file_name_mismatch(
    tmp_path: Path,
) -> None:
    """两个文件声明同一 API ID 时应优先报告重复定义。"""
    from utils.custom.api_loader import ApiConfigError, load_api_definitions

    _write_api_definition(tmp_path, "First.yaml", _api_definition("Duplicated"))
    _write_api_definition(tmp_path, "Second.yaml", _api_definition("Duplicated"))

    with pytest.raises(ApiConfigError, match=r"重复 API id.*Duplicated"):
        load_api_definitions(tmp_path)


@pytest.mark.parametrize(
    ("definition", "expected_message"),
    [
        (
            {
                "name": "缺少 ID",
                "request": {
                    "service_name": "service.Demo",
                    "method_name": "Demo",
                },
            },
            "缺少 id",
        ),
        (
            {
                "id": "Demo",
                "name": "缺少 service",
                "request": {
                    "method_name": "Demo",
                },
            },
            "缺少 service_name",
        ),
        (
            {
                "id": "Demo",
                "name": "错误 method 类型",
                "request": {
                    "service_name": "service.Demo",
                    "method_name": 123,
                },
            },
            "method_name.*非空字符串",
        ),
    ],
)
def test_api_loader_rejects_missing_or_invalid_required_fields(
    tmp_path: Path,
    definition: dict[str, Any],
    expected_message: str,
) -> None:
    """API 必填字段缺失或类型错误时应包含具体字段名。"""
    from utils.custom.api_loader import ApiConfigError, load_api_definitions

    _write_api_definition(tmp_path, "Demo.yaml", definition)

    with pytest.raises(ApiConfigError, match=expected_message):
        load_api_definitions(tmp_path)


@pytest.mark.parametrize(
    ("field", "in_request"),
    [
        ("params", False),
        ("assert", False),
        ("extract", False),
        ("tags", False),
        ("cases", False),
        ("params", True),
    ],
)
def test_api_loader_rejects_test_data_fields(
    tmp_path: Path,
    field: str,
    in_request: bool,
) -> None:
    """API 定义不得保存参数、断言、标签、提取或 case 数据。"""
    from utils.custom.api_loader import ApiConfigError, load_api_definitions

    definition = _api_definition("Demo")
    target = definition["request"] if in_request else definition
    target[field] = {}
    _write_api_definition(tmp_path, "Demo.yaml", definition)

    with pytest.raises(ApiConfigError, match=rf"禁止字段.*{field}"):
        load_api_definitions(tmp_path)


def test_api_loader_wraps_invalid_yaml_root(tmp_path: Path) -> None:
    """YAML 根节点不是对象时应统一转换为 ApiConfigError。"""
    from utils.custom.api_loader import ApiConfigError, load_api_definitions

    _write_api_definition(tmp_path, "Demo.yaml", ["not", "an", "object"])

    with pytest.raises(ApiConfigError, match=r"Demo\.yaml.*根节点"):
        load_api_definitions(tmp_path)


def test_api_loader_rejects_empty_api_directory(tmp_path: Path) -> None:
    """没有任何 API 定义时应在启动网络请求前明确失败。"""
    from utils.custom.api_loader import ApiConfigError, load_api_definitions

    (tmp_path / "data" / "apis").mkdir(parents=True)

    with pytest.raises(ApiConfigError, match="未找到 API 定义"):
        load_api_definitions(tmp_path)


def test_api_loader_builds_execution_case_without_mutating_inputs() -> None:
    """组装可执行 case 时应深拷贝 API、参数、断言和提取规则。"""
    from utils.custom.api_loader import build_execution_case

    api_definition = {
        **_api_definition("Demo"),
        "_source": "data/apis/Demo.yaml",
    }
    params = {"nested": {"value": 1}, "items": [{"id": "item_1"}]}
    assertions = {
        "http_status": 200,
        "response": {"id": "req_0", "success": True},
    }
    extract = {"result_id": "$.result.id"}
    originals = deepcopy((api_definition, params, assertions, extract))

    execution_case = build_execution_case(
        api_definition,
        params,
        assertions,
        extract=extract,
        name="Demo 成功用例",
    )

    assert execution_case == {
        "name": "Demo 成功用例",
        "request": {
            "service_name": "service.Demo",
            "method_name": "Demo",
            "params": params,
        },
        "assert": assertions,
        "extract": extract,
    }

    execution_case["request"]["params"]["nested"]["value"] = 2
    execution_case["assert"]["response"]["success"] = False
    execution_case["extract"]["result_id"] = "$.changed"

    assert (api_definition, params, assertions, extract) == originals


def _write_case_collection(
    root: Path,
    file_name: str,
    content: Any,
) -> Path:
    """写入阶段 2 测试使用的临时单接口 case 集合。

    功能说明:
        仅在 pytest 临时目录创建 ``data/cases`` 数据，不触碰项目真实 YAML。

    参数说明:
        root: pytest 提供的临时项目根目录。
        file_name: case 集合文件名。
        content: 需要写入的 YAML 根数据。

    返回值:
        已写入的 case 文件路径。
    """
    cases_directory = root / "data" / "cases"
    cases_directory.mkdir(parents=True, exist_ok=True)
    case_path = cases_directory / file_name
    case_path.write_text(
        yaml.safe_dump(content, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return case_path


def _single_case(
    case_id: str,
    params: dict[str, Any] | None = None,
    *,
    name: str | None = None,
    tags: list[str] | None = None,
    assertions: dict[str, Any] | None = None,
    extract: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构造阶段 2 测试使用的最小单接口 case。

    参数说明:
        case_id: 当前 API 文件内的 case 唯一标识。
        params: 本条 case 的完整请求参数。
        name: 可选中文名称。
        tags: 可选标签列表。
        assertions: 可选完整断言。
        extract: 可选响应提取规则。

    返回值:
        符合 V1.3 case 元素格式的独立字典。
    """
    case: dict[str, Any] = {
        "id": case_id,
        "name": name or f"{case_id} 用例",
        "tags": list(tags or []),
        "request": {
            "params": deepcopy(params or {}),
        },
        "assert": deepcopy(
            assertions
            if assertions is not None
            else {
                "http_status": 200,
                "response": {"id": "req_0", "success": True},
            }
        ),
    }
    if extract is not None:
        case["extract"] = deepcopy(extract)
    return case


def test_case_loader_expands_multiple_independent_cases(tmp_path: Path) -> None:
    """一个接口文件中的多条 case 应展开为独立、可执行的参数对象。"""
    from utils.custom.case_loader import load_single_cases

    _write_api_definition(
        tmp_path,
        "Demo.yaml",
        _api_definition("Demo", "service.Demo", "CallDemo"),
    )
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": [
                _single_case(
                    "success",
                    {"nested": {"value": 1}},
                    name="成功用例",
                    tags=["smoke", "positive"],
                    extract={"result_id": "$.result_id"},
                ),
                _single_case(
                    "missing_required",
                    {},
                    name="缺参用例",
                    tags=["negative"],
                    assertions={
                        "http_status": 200,
                        "response": {"id": "req_0", "success": False},
                    },
                ),
            ],
        },
    )

    cases = load_single_cases(tmp_path)

    assert [case["id"] for case in cases] == [
        "Demo::success",
        "Demo::missing_required",
    ]
    assert cases[0]["api_id"] == "Demo"
    assert cases[0]["case_id"] == "success"
    assert cases[0]["name"] == "成功用例"
    assert cases[0]["tags"] == ["smoke", "positive"]
    assert cases[0]["execution_case"] == {
        "name": "成功用例",
        "request": {
            "service_name": "service.Demo",
            "method_name": "CallDemo",
            "params": {"nested": {"value": 1}},
        },
        "assert": {
            "http_status": 200,
            "response": {"id": "req_0", "success": True},
        },
        "extract": {"result_id": "$.result_id"},
    }
    assert cases[1]["tags"] == ["negative"]
    assert cases[1]["execution_case"]["request"]["params"] == {}
    assert cases[1]["execution_case"]["assert"]["response"]["success"] is False

    # 修改一条加载结果不得污染同一集合中的其他 case。
    cases[0]["tags"].append("changed")
    cases[0]["execution_case"]["request"]["params"]["nested"]["value"] = 2
    assert cases[1]["tags"] == ["negative"]
    assert cases[1]["execution_case"]["request"]["params"] == {}


def test_case_loader_preserves_missing_and_extra_params_without_merge(
    tmp_path: Path,
) -> None:
    """缺参和多参 case 应完整保留自身 params，不补充任何默认参数。"""
    from utils.custom.case_loader import load_single_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": [
                _single_case("missing", {"required_a": 1}),
                _single_case(
                    "extra",
                    {
                        "required_a": 1,
                        "required_b": 2,
                        "unexpected": 3,
                    },
                ),
            ],
        },
    )

    cases = load_single_cases(tmp_path)

    assert cases[0]["execution_case"]["request"]["params"] == {
        "required_a": 1,
    }
    assert cases[1]["execution_case"]["request"]["params"] == {
        "required_a": 1,
        "required_b": 2,
        "unexpected": 3,
    }


def test_case_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    """同一接口文件内重复的 case ID 应在请求前失败。"""
    from utils.custom.case_loader import CaseConfigError, load_single_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": [
                _single_case("duplicated"),
                _single_case("duplicated"),
            ],
        },
    )

    with pytest.raises(CaseConfigError, match=r"Demo\.yaml.*重复 case id.*duplicated"):
        load_single_cases(tmp_path)


def test_case_loader_rejects_unknown_api_reference(tmp_path: Path) -> None:
    """case 引用不存在的 API 时应包含 API ID 和文件名。"""
    from utils.custom.case_loader import CaseConfigError, load_single_cases

    _write_api_definition(tmp_path, "Existing.yaml", _api_definition("Existing"))
    _write_case_collection(
        tmp_path,
        "Missing.yaml",
        {
            "api": "Missing",
            "cases": [_single_case("demo")],
        },
    )

    with pytest.raises(CaseConfigError, match=r"Missing\.yaml.*API 不存在.*Missing"):
        load_single_cases(tmp_path)


def test_case_loader_rejects_file_name_mismatch(tmp_path: Path) -> None:
    """case 文件名必须与其引用的 API ID 一致。"""
    from utils.custom.case_loader import CaseConfigError, load_single_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_case_collection(
        tmp_path,
        "Other.yaml",
        {
            "api": "Demo",
            "cases": [_single_case("demo")],
        },
    )

    with pytest.raises(
        CaseConfigError,
        match=r"Other\.yaml.*api.*Demo.*文件名",
    ):
        load_single_cases(tmp_path)


@pytest.mark.parametrize("cases_value", [[], {}, "invalid"])
def test_case_loader_rejects_empty_or_invalid_cases(
    tmp_path: Path,
    cases_value: Any,
) -> None:
    """cases 必须是非空列表。"""
    from utils.custom.case_loader import CaseConfigError, load_single_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": cases_value,
        },
    )

    with pytest.raises(CaseConfigError, match=r"Demo\.yaml.*cases.*非空列表"):
        load_single_cases(tmp_path)


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_message"),
    [
        ("tags", "smoke", "tags.*字符串数组"),
        ("request", {"params": []}, "params.*对象"),
        ("assert", [], "assert.*对象"),
        ("extract", [], "extract.*对象"),
    ],
)
def test_case_loader_rejects_invalid_case_fields(
    tmp_path: Path,
    field: str,
    invalid_value: Any,
    expected_message: str,
) -> None:
    """case 标签、参数、断言和提取规则类型错误时应明确失败。"""
    from utils.custom.case_loader import CaseConfigError, load_single_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    case = _single_case("invalid")
    case[field] = invalid_value
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": [case],
        },
    )

    with pytest.raises(CaseConfigError, match=expected_message):
        load_single_cases(tmp_path)


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_message"),
    [
        ("id", "", "缺少 id"),
        ("name", 123, "name.*非空字符串"),
    ],
)
def test_case_loader_rejects_invalid_case_identity(
    tmp_path: Path,
    field: str,
    invalid_value: Any,
    expected_message: str,
) -> None:
    """case ID 或名称无效时应提供当前元素位置。"""
    from utils.custom.case_loader import CaseConfigError, load_single_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    case = _single_case("invalid")
    case[field] = invalid_value
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": [case],
        },
    )

    with pytest.raises(CaseConfigError, match=expected_message):
        load_single_cases(tmp_path)


def test_case_loader_filters_exact_case_ids(tmp_path: Path) -> None:
    """selected_case_ids 应按完整 ID 精确筛选，并保持原始收集顺序。"""
    from utils.custom.case_loader import load_single_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": [
                _single_case("first"),
                _single_case("second"),
            ],
        },
    )

    selected = load_single_cases(
        tmp_path,
        selected_case_ids=("Demo::second",),
    )

    assert [case["id"] for case in selected] == ["Demo::second"]


def test_case_loader_rejects_unknown_selected_case_id(tmp_path: Path) -> None:
    """筛选 ID 不存在时应列出错误 ID和当前可用 ID。"""
    from utils.custom.case_loader import CaseConfigError, load_single_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": [
                _single_case("first"),
                _single_case("second"),
            ],
        },
    )

    with pytest.raises(
        CaseConfigError,
        match=r"Missing::case.*Demo::first.*Demo::second",
    ):
        load_single_cases(
            tmp_path,
            selected_case_ids=("Missing::case",),
        )


def test_single_api_entry_builds_one_pytest_param_per_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单接口入口应为每条 case 生成完整 ID 和当前 case 自己的 marks。"""
    from test_cases import test_single_api

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": [
                _single_case("success", tags=["smoke", "identity"]),
                _single_case("missing", tags=["post"]),
            ],
        },
    )
    monkeypatch.setattr(test_single_api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(test_single_api, "RUN_CASE_IDS", (), raising=False)

    params = test_single_api._load_case_params()

    assert [parameter.id for parameter in params] == [
        "Demo::success",
        "Demo::missing",
    ]
    assert [
        [mark.name for mark in parameter.marks]
        for parameter in params
    ] == [
        ["smoke", "identity"],
        ["post"],
    ]
    assert params[0].values[0]["id"] == "Demo::success"
    assert params[0].values[0]["execution_case"]["request"]["method_name"] == "Demo"


def test_single_api_entry_filters_exact_case_ids_and_rejects_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RUN_CASE_IDS 应精确筛选完整 ID，指定不存在 ID 时直接失败。"""
    from test_cases import test_single_api
    from utils.custom.case_loader import CaseConfigError

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": [
                _single_case("first"),
                _single_case("second"),
            ],
        },
    )
    monkeypatch.setattr(test_single_api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        test_single_api,
        "RUN_CASE_IDS",
        ("Demo::second",),
        raising=False,
    )

    selected = test_single_api._load_case_params()

    assert [parameter.id for parameter in selected] == ["Demo::second"]

    monkeypatch.setattr(
        test_single_api,
        "RUN_CASE_IDS",
        ("Demo::missing",),
    )
    with pytest.raises(CaseConfigError, match=r"Demo::missing.*Demo::first"):
        test_single_api._load_case_params()


def test_ci_entry_defaults_collect_all_cases_and_flows() -> None:
    """CI 默认入口不得固化本地调试筛选，确保定时任务收集全部用例。"""
    from test_cases import test_gateway_flow, test_single_api

    assert test_single_api.RUN_CASE_IDS == ()
    assert test_gateway_flow.RUN_FLOW_IDS == ()


def test_pytest_configure_registers_nested_case_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pytest 配置阶段应注册每条嵌套 case 的标签，而不是读取旧顶层 tags。"""
    from test_cases import conftest as project_conftest

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_case_collection(
        tmp_path,
        "Demo.yaml",
        {
            "api": "Demo",
            "cases": [
                _single_case("first", tags=["smoke", "positive"]),
                _single_case("second", tags=["negative", "smoke"]),
            ],
        },
    )
    config_directory = tmp_path / "config"
    config_directory.mkdir(parents=True)
    (config_directory / "settings.yaml").write_text(
        "logging:\n  console: false\n  file: false\n",
        encoding="utf-8",
    )
    (tmp_path / "data" / "flows").mkdir(parents=True)
    monkeypatch.setattr(project_conftest, "PROJECT_ROOT", tmp_path)

    class RecordingConfig:
        """记录 pytest_configure 动态注册的 marker。"""

        def __init__(self) -> None:
            self.markers: list[str] = []

        @staticmethod
        def getoption(name: str) -> str:
            """返回日志初始化使用的固定测试环境。"""
            assert name == "--env"
            return "test"

        def addinivalue_line(self, name: str, value: str) -> None:
            """保存 marker 配置，供测试检查去重后的标签集合。"""
            assert name == "markers"
            self.markers.append(value)

    config = RecordingConfig()

    project_conftest.pytest_configure(config)  # type: ignore[arg-type]

    assert config.markers == [
        "negative: YAML 用例标签",
        "positive: YAML 用例标签",
        "smoke: YAML 用例标签",
    ]


def test_gateway_flow_entry_supports_local_flow_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flow 测试文件应支持本地常量筛选多个 Flow，命令行筛选优先。"""
    from test_cases import test_gateway_flow
    from utils.custom.flow_loader import FlowConfigError

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    flows_directory = tmp_path / "data" / "flows"
    scenarios_directory = tmp_path / "data" / "scenarios"
    flows_directory.mkdir(parents=True)
    scenarios_directory.mkdir(parents=True)
    for flow_id in ("FirstFlow", "SecondFlow"):
        (flows_directory / f"{flow_id}.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": flow_id,
                    "steps": [{"id": "demo", "api": "Demo"}],
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (scenarios_directory / f"{flow_id}.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": f"{flow_id} 场景",
                    "step_data": {
                        "demo": _complete_step_data({}, {}),
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(test_gateway_flow, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        test_gateway_flow,
        "RUN_FLOW_IDS",
        ("SecondFlow",),
        raising=False,
    )

    local_cases = test_gateway_flow._load_selected_flow_cases(None)

    assert [flow_case["id"] for flow_case in local_cases] == ["SecondFlow"]
    command_case = test_gateway_flow._load_selected_flow_cases("FirstFlow")
    assert [flow_case["id"] for flow_case in command_case] == ["FirstFlow"]

    monkeypatch.setattr(test_gateway_flow, "RUN_FLOW_IDS", ("MissingFlow",))
    with pytest.raises(FlowConfigError, match=r"MissingFlow.*FirstFlow.*SecondFlow"):
        test_gateway_flow._load_selected_flow_cases(None)


def test_gateway_flow_copies_framework_session_without_business_leak() -> None:
    """Flow 应深拷贝会话状态和 consent 日期，不继承父上下文的业务变量。"""
    from test_cases import test_gateway_flow
    from utils.custom.runtime_context import RuntimeContext

    parent_context = RuntimeContext(
        {
            "access_token": "access-parent",
            "expires_time": 1_800_000_000_000,
            "refresh_token": "refresh-parent",
            "refresh_expires_time": 1_800_100_000_000,
            "user_id": "user_parent",
            "consent_policy_version": "2026-07-27",
            "parent_business_value": "do-not-copy",
        }
    )
    flow_context = RuntimeContext({"flow_business_value": "keep"})

    test_gateway_flow._copy_framework_session_context(
        flow_context,
        parent_context,
    )

    assert flow_context.as_dict() == {
        "flow_business_value": "keep",
        "access_token": "access-parent",
        "expires_time": 1_800_000_000_000,
        "refresh_token": "refresh-parent",
        "refresh_expires_time": 1_800_100_000_000,
        "user_id": "user_parent",
        "consent_policy_version": "2026-07-27",
    }
    flow_context.set("access_token", "access-flow")
    assert parent_context.get("access_token") == "access-parent"
    assert flow_context.get("parent_business_value") is None


def test_gateway_flow_direct_main_keeps_flow_debug_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """直接运行 Flow 文件应透传环境和 --flow，并保留终端日志选项。"""
    from test_cases import test_gateway_flow

    captured: list[str] = []

    def fake_main(arguments: list[str]) -> int:
        """记录 pytest 参数并模拟成功退出。"""
        captured.extend(arguments)
        return 0

    monkeypatch.setattr(test_gateway_flow.pytest, "main", fake_main)

    assert test_gateway_flow.main(["--env", "test", "--flow", "DemoFlow"]) == 0
    assert captured == [
        str(Path(test_gateway_flow.__file__).resolve()),
        "-s",
        "--log-cli-level=INFO",
        "--env",
        "test",
        "--flow",
        "DemoFlow",
    ]


def _write_v13_flow_fixture(
    root: Path,
    flow: dict[str, Any],
    scenario: dict[str, Any],
) -> None:
    """写入阶段 3 测试使用的 Flow 与同名 Scenario。

    功能说明:
        在 pytest 临时项目中创建固定名称的 Flow/Scenario 配对；API 定义由
        各测试按需要单独创建，以便覆盖存在、缺失和未引用场景。

    参数说明:
        root: pytest 临时项目根目录。
        flow: Flow YAML 根对象。
        scenario: Scenario YAML 根对象。

    返回值:
        无。文件写入失败时由 pathlib 透传 OSError。
    """
    flows_directory = root / "data" / "flows"
    scenarios_directory = root / "data" / "scenarios"
    flows_directory.mkdir(parents=True, exist_ok=True)
    scenarios_directory.mkdir(parents=True, exist_ok=True)
    (flows_directory / "DemoFlow.yaml").write_text(
        yaml.safe_dump(flow, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (scenarios_directory / "DemoFlow.yaml").write_text(
        yaml.safe_dump(scenario, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _complete_step_data(
    params: dict[str, Any] | None = None,
    assertions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 API step 必需的完整 Scenario 数据。"""
    return {
        "params": deepcopy(params or {}),
        "assert": deepcopy(assertions or {}),
    }


def test_flow_loader_uses_api_and_returns_only_referenced_definitions(
    tmp_path: Path,
) -> None:
    """FlowCase 应只携带当前 Flow 实际引用的 API 定义。"""
    from utils.custom.flow_loader import load_flow_cases

    _write_api_definition(
        tmp_path,
        "Demo.yaml",
        _api_definition("Demo", "service.Demo", "CallDemo"),
    )
    _write_api_definition(
        tmp_path,
        "Unused.yaml",
        _api_definition("Unused", "service.Unused", "CallUnused"),
    )
    _write_v13_flow_fixture(
        tmp_path,
        {
            "name": "API 引用流程",
            "tags": ["flow", "smoke"],
            "steps": [
                {
                    "id": "demo",
                    "api": "Demo",
                    "extract": {"result_id": "$.result_id"},
                }
            ],
        },
        {
            "name": "成功场景",
            "step_data": {
                "demo": _complete_step_data(
                    {"input": "value"},
                    {"data_equals": {"status": "DONE"}},
                )
            },
        },
    )

    flow_cases = load_flow_cases(tmp_path)

    assert len(flow_cases) == 1
    assert flow_cases[0]["flow"]["steps"][0]["api"] == "Demo"
    assert list(flow_cases[0]["api_definitions"]) == ["Demo"]
    assert flow_cases[0]["api_definitions"]["Demo"]["request"] == {
        "service_name": "service.Demo",
        "method_name": "CallDemo",
    }
    assert "Unused" not in flow_cases[0]["api_definitions"]


def test_flow_loader_rejects_unknown_api(tmp_path: Path) -> None:
    """Flow step 引用不存在 API 时应在请求前失败。"""
    from utils.custom.flow_loader import FlowConfigError, load_flow_cases

    _write_api_definition(
        tmp_path,
        "Existing.yaml",
        _api_definition("Existing"),
    )
    _write_v13_flow_fixture(
        tmp_path,
        {
            "name": "未知 API 流程",
            "steps": [{"id": "missing", "api": "Missing"}],
        },
        {
            "name": "场景",
            "step_data": {
                "missing": _complete_step_data(),
            },
        },
    )

    with pytest.raises(
        FlowConfigError,
        match=r"missing.*API 不存在.*Missing",
    ):
        load_flow_cases(tmp_path)


def test_flow_loader_rejects_legacy_call_field(tmp_path: Path) -> None:
    """V1.2 call 字段应被明确拒绝，不能静默当作无动作步骤。"""
    from utils.custom.flow_loader import FlowConfigError, load_flow_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_v13_flow_fixture(
        tmp_path,
        {
            "name": "旧格式流程",
            "steps": [{"id": "legacy", "call": "Demo.yaml"}],
        },
        {"name": "场景", "step_data": {}},
    )

    with pytest.raises(
        FlowConfigError,
        match=r"legacy.*不再支持 call.*api",
    ):
        load_flow_cases(tmp_path)


@pytest.mark.parametrize(
    ("step_data", "expected_message"),
    [
        ({}, "demo.*缺少 Scenario step_data"),
        ({"demo": {"assert": {}}}, "demo.*缺少 params"),
        ({"demo": {"params": {}}}, "demo.*缺少 assert"),
    ],
)
def test_flow_loader_requires_complete_scenario_data_for_api_step(
    tmp_path: Path,
    step_data: dict[str, Any],
    expected_message: str,
) -> None:
    """每个 API step 必须独立提供完整 params 和 assert。"""
    from utils.custom.flow_loader import FlowConfigError, load_flow_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_v13_flow_fixture(
        tmp_path,
        {
            "name": "数据不完整流程",
            "steps": [{"id": "demo", "api": "Demo"}],
        },
        {
            "name": "场景",
            "step_data": step_data,
        },
    )

    with pytest.raises(FlowConfigError, match=expected_message):
        load_flow_cases(tmp_path)


@pytest.mark.parametrize(
    "step",
    [
        {"id": "wait_step", "wait": {"seconds": 0}},
        {"id": "action_step", "action": "prepared_media_upload"},
    ],
)
def test_flow_loader_rejects_step_data_for_non_api_step(
    tmp_path: Path,
    step: dict[str, Any],
) -> None:
    """wait 和 action 步骤不得在 Scenario 中配置接口请求数据。"""
    from utils.custom.flow_loader import FlowConfigError, load_flow_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    step_id = str(step["id"])
    _write_v13_flow_fixture(
        tmp_path,
        {
            "name": "非 API 数据流程",
            "steps": [step],
        },
        {
            "name": "场景",
            "step_data": {
                step_id: _complete_step_data(),
            },
        },
    )

    with pytest.raises(
        FlowConfigError,
        match=rf"{step_id}.*仅 API 步骤",
    ):
        load_flow_cases(tmp_path)


@pytest.mark.parametrize(
    ("step_extra", "expected_message"),
    [
        (
            {"extract": {"value": "$.value"}},
            "wait_step.*extract.*只能用于 api",
        ),
        (
            {
                "until": {
                    "path": "$.status",
                    "equals": "DONE",
                    "interval_seconds": 1,
                    "timeout_seconds": 2,
                }
            },
            "wait_step.*until.*只能用于 api",
        ),
    ],
)
def test_flow_loader_limits_extract_and_until_to_api_steps(
    tmp_path: Path,
    step_extra: dict[str, Any],
    expected_message: str,
) -> None:
    """extract 和 until 只能附加在 API 调用步骤。"""
    from utils.custom.flow_loader import FlowConfigError, load_flow_cases

    _write_api_definition(tmp_path, "Demo.yaml", _api_definition("Demo"))
    _write_v13_flow_fixture(
        tmp_path,
        {
            "name": "动作边界流程",
            "steps": [
                {
                    "id": "wait_step",
                    "wait": {"seconds": 0},
                    **step_extra,
                }
            ],
        },
        {"name": "场景", "step_data": {}},
    )

    with pytest.raises(FlowConfigError, match=expected_message):
        load_flow_cases(tmp_path)
