"""契约/用例 Review 的版本冲突、硬门禁和高风险权限测试。"""

import pytest

from agents.api_test.contracts.openapi_parser import parse_openapi_document
from services.api_agent.models import BaseTestCase
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
    added = review.review_cases(
        task_id, base_version=2,
        changes=[{"action": "add", "fields": {
            "contract_id": "contract_1", "name": "人工业务场景", "objective": "验证业务规则",
            "dimension": "business_scenario", "risk_level": "low",
        }}],
        actor={"user_id": "developer", "username": "developer"}, can_approve_high_risk=True,
    )
    assert len(added["items"]) == 2
