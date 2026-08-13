from __future__ import annotations

import json

import yaml

from requirement_decomposition import run_decomposition
from requirement_decomposition.llm.evidence_binder import bind_field_evidence
from requirement_decomposition.llm.grounding_checker import run_grounding_check
from requirement_decomposition.models.schema import (
    Constraint,
    Requirement,
    RequirementFacts,
    RequirementSection,
    SourceTrace,
)
from requirement_decomposition.validator.anti_hallucination import apply_anti_hallucination


class FakeLLMClient:
    """第三阶段 pipeline 测试使用的固定响应客户端。"""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses

    def complete(self, task_name: str, prompt: str, config) -> str:
        return json.dumps(self.responses[task_name], ensure_ascii=False)


def _section() -> RequirementSection:
    return RequirementSection(
        source_id="SRC-001",
        section_id="SEC-001",
        title="取消订单",
        heading_path=["订单系统", "取消订单"],
        content="用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。",
        quote="用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。",
    )


def test_bind_field_evidence_marks_explicit_and_inferred_values():
    section = _section()
    requirement = Requirement(
        requirement_id="REQ-001",
        title="待支付订单允许取消",
        domain="订单系统",
        module="订单系统",
        feature="取消订单",
        description="用户可以取消待支付订单。",
        source_trace=SourceTrace(
            source_id=section.source_id,
            section_id=section.section_id,
            quote=section.quote,
        ),
        requirement_facts=RequirementFacts(
            constraints=[
                Constraint(
                    object="订单状态",
                    rule="已支付订单不可取消",
                    constraint_type="state",
                    test_dimension="状态校验",
                ),
                Constraint(
                    object="库存",
                    rule="订单取消后库存自动回滚",
                    constraint_type="business_rule",
                    test_dimension="数据一致性",
                ),
            ]
        ),
    )

    evidence = bind_field_evidence(requirement)
    explicit = [item for item in evidence if item.value == "已支付订单不可取消"][0]
    inferred = [item for item in evidence if item.value == "订单取消后库存自动回滚"][0]

    assert explicit.evidence_type == "explicit"
    assert explicit.evidence.quote == section.quote
    assert inferred.evidence_type == "inferred"


def test_grounding_check_reports_unsupported_items_from_field_evidence():
    section = _section()
    requirement = Requirement(
        requirement_id="REQ-001",
        title="待支付订单允许取消",
        description="用户可以取消待支付订单。",
        source_trace=SourceTrace(
            source_id=section.source_id,
            section_id=section.section_id,
            quote=section.quote,
        ),
        requirement_facts=RequirementFacts(
            constraints=[
                Constraint(
                    object="库存",
                    rule="订单取消后库存自动回滚",
                    constraint_type="business_rule",
                    test_dimension="数据一致性",
                )
            ]
        ),
    )

    evidence = bind_field_evidence(requirement)
    grounding = run_grounding_check(evidence)

    assert grounding.passed is False
    assert grounding.unsupported_items[0]["field"] == "constraints"
    assert grounding.unsupported_items[0]["value"] == "订单取消后库存自动回滚"


def test_apply_anti_hallucination_downgrades_unsupported_constraints_to_suggestions():
    section = _section()
    requirement = Requirement(
        requirement_id="REQ-001",
        title="待支付订单允许取消",
        description="用户可以取消待支付订单。",
        source_trace=SourceTrace(
            source_id=section.source_id,
            section_id=section.section_id,
            quote=section.quote,
        ),
        requirement_facts=RequirementFacts(
            constraints=[
                Constraint(
                    object="订单状态",
                    rule="已支付订单不可取消",
                    constraint_type="state",
                    test_dimension="状态校验",
                ),
                Constraint(
                    object="库存",
                    rule="订单取消后库存自动回滚",
                    constraint_type="business_rule",
                    test_dimension="数据一致性",
                ),
            ]
        ),
    )

    processed = apply_anti_hallucination(requirement)

    assert [item.rule for item in processed.requirement_facts.constraints] == ["已支付订单不可取消"]
    assert processed.grounding_check.passed is False
    assert processed.grounding_check.unsupported_items[0]["action"] == "move_to_test_design_suggestions"
    assert processed.test_design_suggestions.test_generation_hints == [
        "constraints: 订单取消后库存自动回滚"
    ]


def test_pipeline_applies_grounding_and_downgrades_unsupported_llm_facts(tmp_path):
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
                "sources": [{"source_id": "SRC-001", "path": str(source_file)}],
                "output": {
                    "requirement_json": {
                        "enabled": True,
                        "path": str(output_dir / "requirements.json"),
                    },
                    "markdown": {"enabled": True, "path": str(output_dir / "requirements_md")},
                    "test_seed": {"enabled": True, "path": str(output_dir / "test_seed.json")},
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
                        "test_objects": [{"name": "订单状态", "type": "enum"}],
                        "constraints": [
                            {
                                "object": "订单状态",
                                "rule": "已支付订单不可取消",
                                "constraint_type": "state",
                                "test_dimension": "状态校验",
                            },
                            {
                                "object": "库存",
                                "rule": "订单取消后库存自动回滚",
                                "constraint_type": "business_rule",
                                "test_dimension": "数据一致性",
                            },
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
                                "then": "订单取消成功",
                            }
                        ],
                        "risk_tags": ["状态流转"],
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

    requirement = result.requirements[0]
    requirements_json = json.loads((output_dir / "requirements.json").read_text(encoding="utf-8"))

    assert [item.rule for item in requirement.requirement_facts.constraints] == ["已支付订单不可取消"]
    assert requirement.test_design_suggestions.test_generation_hints == [
        "constraints: 订单取消后库存自动回滚",
        "acceptance_criteria: 订单取消成功",
    ]
    assert result.grounding_summary == {
        "checked": True,
        "unsupported_facts": 2,
        "moved_to_suggestions": 2,
    }
    assert requirements_json["grounding_summary"]["unsupported_facts"] == 2
