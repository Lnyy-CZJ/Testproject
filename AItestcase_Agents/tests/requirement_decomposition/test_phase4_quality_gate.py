from __future__ import annotations

import json

import pytest
import yaml

from requirement_decomposition import run_decomposition
from requirement_decomposition.models.schema import (
    AcceptanceCriterion,
    Constraint,
    FieldEvidence,
    GroundingCheck,
    Requirement,
    RequirementFacts,
    SourceTrace,
    StateModel,
    StateTransition,
    TestObject as RequirementTestObject,
    TestDesignSuggestions as RequirementTestDesignSuggestions,
)
from requirement_decomposition.validator.confirmed_gate_validator import apply_confirmed_gate
from requirement_decomposition.validator.quality_validator import build_quality_report
from requirement_decomposition.validator.risk_tag_validator import validate_risk_tags
from requirement_decomposition.validator.schema_validator import validate_requirement_schema
from requirement_decomposition.validator.state_model_validator import validate_state_model


class FakeLLMClient:
    """第四阶段 pipeline 测试使用的固定响应客户端。"""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses

    def complete(self, task_name: str, prompt: str, config) -> str:
        return json.dumps(self.responses[task_name], ensure_ascii=False)


def _field_evidence(field: str, value: str) -> FieldEvidence:
    return FieldEvidence(
        field=field,
        value=value,
        evidence={
            "source_id": "SRC-001",
            "section_id": "SEC-001",
            "quote": "用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。",
        },
        evidence_type="explicit",
        confidence=1.0,
    )


def _valid_requirement() -> Requirement:
    return Requirement(
        requirement_id="REQ-001",
        title="待支付订单允许取消",
        domain="订单系统",
        module="订单系统",
        feature="取消订单",
        description="用户可以取消待支付订单。",
        source_trace=SourceTrace(
            source_id="SRC-001",
            section_id="SEC-001",
            quote="用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。",
        ),
        requirement_facts=RequirementFacts(
            test_objects=[RequirementTestObject(name="订单状态", type="enum", values=["待支付"])],
            constraints=[
                Constraint(
                    object="订单状态",
                    rule="已支付订单不可取消",
                    constraint_type="state",
                    test_dimension="状态校验",
                )
            ],
            state_model=StateModel(
                entity="订单",
                states=["待支付", "已支付", "已取消"],
                transitions=[
                    StateTransition(
                        **{"from": "待支付", "to": "已取消", "trigger": "取消订单", "valid": True}
                    )
                ],
            ),
            permissions=[{"role": "非本人", "rule": "非本人订单不可操作"}],
            acceptance_criteria=[
                AcceptanceCriterion(
                    given="订单状态为待支付",
                    when="用户取消订单",
                    then="订单状态变为已取消",
                )
            ],
        ),
        test_design_suggestions=RequirementTestDesignSuggestions(risk_tags=["状态流转", "权限"]),
        field_evidence=[
            _field_evidence("title", "待支付订单允许取消"),
            _field_evidence("description", "用户可以取消待支付订单。"),
            _field_evidence("test_objects", "订单状态"),
            _field_evidence("constraints", "已支付订单不可取消"),
            _field_evidence("state_model", "待支付"),
            _field_evidence("permissions", "非本人订单不可操作"),
            _field_evidence("acceptance_criteria", "订单状态变为已取消"),
        ],
        grounding_check={"passed": True, "unsupported_items": []},
        unresolved=[],
        conflict_items=[],
    )


def test_schema_validator_accepts_valid_requirement_and_reports_invalid_dict():
    valid = _valid_requirement()
    invalid = valid.model_dump(mode="json")
    invalid["status"] = "approved"

    valid_result = validate_requirement_schema(valid)
    invalid_result = validate_requirement_schema(invalid)

    assert valid_result.passed is True
    assert invalid_result.passed is False
    assert invalid_result.issues[0]["issue_type"] == "schema_invalid"


def test_risk_tag_validator_keeps_only_allowed_enum_values():
    requirement = _valid_requirement()
    requirement.test_design_suggestions.risk_tags = ["权限", "库存回滚", "幂等"]

    result = validate_risk_tags(requirement)

    assert requirement.test_design_suggestions.risk_tags == ["权限", "幂等"]
    assert result.passed is False
    assert result.issues[0]["value"] == "库存回滚"


def test_state_model_validator_reports_invalid_transition_and_duplicate():
    state_model = StateModel(
        entity="订单",
        states=["待支付", "已支付"],
        transitions=[
            StateTransition(**{"from": "待支付", "to": "已取消", "trigger": "取消订单", "valid": True}),
            StateTransition(**{"from": "待支付", "to": "已取消", "trigger": "取消订单", "valid": True}),
            StateTransition(**{"from": "已支付", "to": "待支付", "trigger": "", "valid": False}),
        ],
    )

    result = validate_state_model(state_model, requirement_id="REQ-001")

    assert result.passed is False
    assert {issue["issue_type"] for issue in result.issues} == {
        "state_transition_unknown_state",
        "state_transition_duplicate",
        "state_transition_empty_trigger",
    }


def test_quality_report_and_confirmed_gate_mark_valid_requirement_as_candidate():
    requirement = _valid_requirement()

    quality = build_quality_report([requirement])
    gated = apply_confirmed_gate(requirement)

    assert quality["schema_valid_rate"] == 1.0
    assert quality["quality_score"] >= 0.9
    assert gated.status == "confirmed_candidate"


def test_confirmed_gate_keeps_requirement_with_issues_as_draft():
    requirement = _valid_requirement()
    requirement.grounding_check = GroundingCheck(
        passed=False,
        unsupported_items=[{"field": "constraints"}],
    )

    gated = apply_confirmed_gate(requirement)

    assert gated.status == "draft"


def test_pipeline_outputs_quality_report_and_confirmed_candidate(tmp_path):
    source_file = tmp_path / "order.md"
    output_dir = tmp_path / "output"
    source_file.write_text(
        "# 订单系统\n\n## 取消订单\n用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "requirement_decomposition.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "project": {"project_id": "PROJECT-001", "project_name": "订单系统"},
                "sources": [{"source_id": "SRC-001", "path": str(source_file), "trust_level": "high"}],
                "output": {
                    "requirement_json": {
                        "enabled": True,
                        "path": str(output_dir / "requirements.json"),
                    },
                    "markdown": {"enabled": True, "path": str(output_dir / "requirements_md")},
                    "test_seed": {
                        "enabled": True,
                        "path": str(output_dir / "test_seed.json"),
                        "include_confirmed_candidate": True,
                    },
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    client = FakeLLMClient(
        {
            "requirement_split": [
                {
                    "title": "待支付订单允许取消",
                    "description": "用户可以取消待支付订单。",
                    "confidence": 0.91,
                    "reasoning_summary": "拆出状态和权限规则。",
                }
            ],
            "fact_bundle_batch_extract": {
                "items": [
                    {
                        "index": 0,
                        "test_objects": [{"name": "订单状态", "type": "enum", "values": ["待支付"]}],
                        "constraints": [
                            {
                                "object": "订单状态",
                                "rule": "已支付订单不可取消",
                                "constraint_type": "state",
                                "test_dimension": "状态校验",
                            }
                        ],
                        "state_model": {
                            "entity": "订单",
                            "states": ["待支付", "已支付"],
                            "transitions": [],
                        },
                        "permissions": [{"role": "非本人", "rule": "非本人订单不可操作"}],
                        "acceptance_criteria": [
                            {
                                "given": "订单状态为待支付",
                                "when": "用户取消订单",
                                "then": "订单状态变为已取消",
                            }
                        ],
                        "risk_tags": ["状态流转", "权限"],
                    }
                ]
            },
        }
    )

    result = run_decomposition(
        source_path=str(source_file),
        config_path=str(config_file),
        llm_client=client,
    )
    output_json = json.loads((output_dir / "requirements.json").read_text(encoding="utf-8"))
    test_seed_json = json.loads((output_dir / "test_seed.json").read_text(encoding="utf-8"))

    assert result.requirements[0].status == "confirmed_candidate"
    assert result.test_seeds[0].test_seed.risk_tags == ["状态流转", "权限"]
    assert result.quality_report["schema_valid_rate"] == 1.0
    assert result.quality_report["llm_self_check_rate"] == 1.0
    assert result.quality_report["quality_score"] >= 0.9
    assert output_json["requirements"][0]["status"] == "confirmed_candidate"
    assert output_json["requirements"][0]["llm_self_check"]["passed"] is True
    assert output_json["requirements"][0]["test_design_suggestions"]["risk_tags"] == ["状态流转", "权限"]
    assert output_json["quality_report"]["confirmed_candidate_requirements"] == 1
    assert test_seed_json[0]["test_seed"]["risk_tags"] == ["状态流转", "权限"]
