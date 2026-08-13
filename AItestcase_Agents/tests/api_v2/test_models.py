"""API V2 Schema 和状态机测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.api_agent.models import ApiContract, FieldEvidence, SourceTrace, assert_transition


def contract_payload() -> dict:
    """构造最小可验证契约。"""

    return {
        "contract_id": "contract_post_users_id",
        "name": "更新用户",
        "method": "post",
        "path": "/users/{id}",
        "parameters": [{
            "name": "id", "location": "path", "required": True, "schema": {"type": "string"},
        }],
        "source_trace": SourceTrace(source_id="doc", section_id="paths", quote="POST /users/{id}").model_dump(),
        "field_evidence": [FieldEvidence(
            field_path="method", value="POST", source_type="openapi_node",
            source_pointer="/paths/~1users~1{id}/post",
        ).model_dump()],
    }


def test_contract_is_strict_and_path_is_relative() -> None:
    contract = ApiContract.model_validate(contract_payload())
    assert contract.method == "POST"
    invalid = contract_payload() | {"path": "https://example.test/users", "unexpected": True}
    with pytest.raises(ValidationError):
        ApiContract.model_validate(invalid)


def test_path_parameter_must_match_template() -> None:
    payload = contract_payload()
    payload["parameters"][0]["required"] = False
    with pytest.raises(ValidationError):
        ApiContract.model_validate(payload)


def test_state_transitions_reject_illegal_shortcuts() -> None:
    assert_transition("pending", "running")
    assert_transition("running", "waiting_contract_review")
    with pytest.raises(ValueError):
        assert_transition("pending", "succeeded")
    with pytest.raises(ValueError):
        assert_transition("succeeded", "running")
