"""契约/用例 Review 的版本冲突、硬门禁和高风险权限测试。"""

import pytest

from agents.api_test.contracts.openapi_parser import parse_openapi_document
from services.api_agent.models import BaseTestCase, ExecutableCase, ExecutableRequest
from services.api_agent.review_service import ApiReviewService
from services.api_agent.v2_store import ApiV2Store
from services.common.errors import ServiceError
from services.common.task_store import TaskStore, new_task_id


def _store(tmp_path):
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    store.save({"id": task_id, "schema_version": 2, "current_versions": {}, "completed_stages": []})
    return store, task_id


def test_contract_review_appends_version_and_detects_conflict(tmp_path):
    store, task_id = _store(tmp_path)
    contracts = parse_openapi_document({
        "openapi": "3.0.0", "paths": {"/health": {"get": {"responses": {"200": {"description": "ok"}}}}},
    })
    first = ApiV2Store(store).save_version(
        task_id, kind="contracts", items=[item.model_dump(mode="json", by_alias=True) for item in contracts],
    )
    review = ApiReviewService(store)
    saved = review.review_contracts(
        task_id, base_version=first["version"],
        changes=[{"contract_id": contracts[0].contract_id, "action": "confirm"}],
        actor={"user_id": "reviewer", "username": "reviewer"},
    )
    assert saved["version"] == 2
    assert saved["items"][0]["status"] == "confirmed"
    returned = review.review_contracts(
        task_id, base_version=2,
        changes=[{"contract_id": contracts[0].contract_id, "action": "return", "reason": "需要补充响应说明"}],
        actor={"user_id": "reviewer", "username": "reviewer"},
    )
    assert returned["items"][0]["status"] == "draft"
    with pytest.raises(ServiceError) as error:
        review.review_contracts(
            task_id, base_version=1, changes=[], actor={"user_id": "other", "username": "other"},
        )
    assert error.value.code == "REVIEW_VERSION_CONFLICT"


def test_high_risk_case_requires_execute_permission(tmp_path):
    store, task_id = _store(tmp_path)
    case = BaseTestCase(
        case_id="case_1", contract_id="contract_1", name="删除资源", objective="验证删除",
        dimension="destructive", risk_level="high", source="deterministic", status="draft",
    )
    ApiV2Store(store).save_version(task_id, kind="base-cases", items=[case.model_dump(mode="json")])
    review = ApiReviewService(store)
    with pytest.raises(ServiceError) as error:
        review.review_cases(
            task_id, base_version=1, changes=[{"case_id": "case_1", "action": "confirm"}],
            actor={"user_id": "executor", "username": "executor"}, can_approve_high_risk=False,
        )
    assert error.value.code == "HIGH_RISK_PERMISSION_REQUIRED"
    saved = review.review_cases(
        task_id, base_version=1, changes=[{"case_id": "case_1", "action": "confirm"}],
        actor={"user_id": "developer", "username": "developer"}, can_approve_high_risk=True,
    )
    assert saved["items"][0]["status"] == "confirmed"
    assert saved["items"][0]["high_risk_confirmed_by"]["user_id"] == "developer"
    assert saved["items"][0]["high_risk_confirmed_at"]
    added = review.review_cases(
        task_id, base_version=2,
        changes=[{"action": "add", "fields": {
            "contract_id": "contract_1", "name": "人工业务场景", "objective": "验证业务规则",
            "dimension": "business_scenario", "risk_level": "low",
        }}],
        actor={"user_id": "developer", "username": "developer"}, can_approve_high_risk=True,
    )
    assert len(added["items"]) == 2


def test_confirm_all_uses_stable_sha_and_reports_skipped_cases(tmp_path):
    """一键确认必须绑定当前版本，并明确返回不可确认项而非静默忽略。"""

    store, task_id = _store(tmp_path)
    ready = BaseTestCase(
        case_id="case_ready", contract_id="contract_1", name="正常登录", objective="验证登录",
        dimension="normal", risk_level="low", source="deterministic", status="confirmed_candidate",
    )
    disabled = BaseTestCase(
        case_id="case_disabled", contract_id="contract_1", name="已禁用", objective="不执行",
        dimension="negative", risk_level="low", source="deterministic", status="disabled",
    )
    ApiV2Store(store).save_version(
        task_id, kind="base-cases", items=[ready.model_dump(mode="json"), disabled.model_dump(mode="json")],
    )
    review = ApiReviewService(store)
    preview = review.case_confirmation_preview(task_id)

    with pytest.raises(ServiceError) as error:
        review.confirm_all_cases(
            task_id, base_version=1, confirmation_sha256="expired", reason="批量复核",
            actor={"user_id": "tester", "username": "tester"}, can_approve_high_risk=True,
        )
    assert error.value.code == "REVIEW_VERSION_CONFLICT"

    saved = review.confirm_all_cases(
        task_id, base_version=1, confirmation_sha256=preview["confirmation_sha256"],
        reason="批量复核", actor={"user_id": "tester", "username": "tester"},
        can_approve_high_risk=True,
    )
    assert saved["items"][0]["status"] == "confirmed"
    assert saved["confirmed_case_ids"] == ["case_ready"]
    assert saved["skipped"] == [{"case_id": "case_disabled", "code": "CASE_REVIEW_BLOCKED"}]


def test_executable_review_requires_current_ready_definition(tmp_path):
    """可执行定义必须独立 Review；静态禁用项不能被确认进入计划。"""

    store, task_id = _store(tmp_path)
    ready = ExecutableCase(
        executable_case_id="exec_ready", base_case_id="case_ready", contract_id="contract_1",
        name="健康检查", risk_level="low", request=ExecutableRequest(method="GET", path="/health"),
        validation_status="ready", enabled=True,
    )
    disabled = ExecutableCase(
        executable_case_id="exec_disabled", base_case_id="case_disabled", contract_id="contract_1",
        name="缺失请求", risk_level="low", request=ExecutableRequest(method="POST", path="/login"),
        validation_status="disabled", enabled=False,
    )
    ApiV2Store(store).save_version(
        task_id, kind="executable-cases",
        items=[ready.model_dump(mode="json"), disabled.model_dump(mode="json")],
    )
    review = ApiReviewService(store)
    saved = review.review_executable_cases(
        task_id, base_version=1,
        changes=[{"executable_case_id": "exec_ready", "action": "confirm", "reason": "已核对请求"}],
        actor={"user_id": "tester", "username": "tester"},
    )
    assert saved["items"][0]["review_status"] == "confirmed"
    with pytest.raises(ServiceError) as error:
        review.review_executable_cases(
            task_id, base_version=2,
            changes=[{"executable_case_id": "exec_disabled", "action": "confirm", "reason": "强制确认"}],
            actor={"user_id": "tester", "username": "tester"},
        )
    assert error.value.code == "EXECUTABLE_CASE_NOT_READY"


def test_base_case_review_marks_existing_executable_and_plan_stale(tmp_path):
    """基础用例产生新版本后，旧执行定义和计划只能保留为历史只读产物。"""

    store, task_id = _store(tmp_path)
    base_case = BaseTestCase(
        case_id="case_1", contract_id="contract_1", name="登录", objective="验证登录",
        dimension="normal", risk_level="low", source="deterministic", status="confirmed_candidate",
    )
    ApiV2Store(store).save_version(
        task_id, kind="base-cases", items=[base_case.model_dump(mode="json")],
    )
    executable = ExecutableCase(
        executable_case_id="exec_1", base_case_id="case_1", contract_id="contract_1",
        name="登录执行定义", risk_level="low",
        request=ExecutableRequest(method="POST", path="/login"),
        validation_status="ready", enabled=True, review_status="confirmed",
    )
    saved_executable = ApiV2Store(store).save_version(
        task_id, kind="executable-cases", items=[executable.model_dump(mode="json")],
        source_versions={"base-cases": 1},
    )
    saved_plan = ApiV2Store(store).save_version(
        task_id, kind="execution-plans", items={"plan_id": "plan_1", "status": "confirmed"},
        source_versions={"executable-cases": saved_executable["version"]},
    )

    ApiReviewService(store).review_cases(
        task_id, base_version=1,
        changes=[{"case_id": "case_1", "action": "confirm", "reason": "人工确认"}],
        actor={"user_id": "tester", "username": "tester"}, can_approve_high_risk=True,
    )

    record = store.load(task_id)
    stale = {(item["kind"], item["version"]) for item in record.get("stale_versions", [])}
    assert ("executable-cases", saved_executable["version"]) in stale
    assert ("execution-plans", saved_plan["version"]) in stale
    assert "execution_confirmation_sha256" not in record
