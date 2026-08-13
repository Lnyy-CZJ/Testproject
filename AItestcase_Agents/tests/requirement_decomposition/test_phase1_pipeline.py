from __future__ import annotations

import json

import yaml

from requirement_decomposition import run_decomposition
from requirement_decomposition.chunker.section_chunker import chunk_markdown_sections
from requirement_decomposition.config.loader import load_config
from requirement_decomposition.generator.test_seed_generator import generate_test_seeds
from requirement_decomposition.models.schema import (
    AcceptanceCriterion,
    Constraint,
    Requirement,
    RequirementFacts,
    SourceTrace,
    TestObject as RequirementTestObject,
)
from requirement_decomposition.parser.document_parser import parse_markdown_document


def test_config_loader_merges_source_path_and_output_defaults(tmp_path):
    config_file = tmp_path / "requirement_decomposition.yaml"
    source_file = tmp_path / "order.md"
    source_file.write_text("# 取消订单\n用户可以取消待支付订单。", encoding="utf-8")
    config_file.write_text(
        yaml.safe_dump(
            {
                "project": {"project_id": "PROJECT-001", "project_name": "订单系统"},
                "sources": [],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_file), source_path=str(source_file))

    assert config.project.project_id == "PROJECT-001"
    assert config.sources[0].path == str(source_file)
    assert config.output.requirement_json.path == "output/requirements.json"
    assert config.llm.enabled is True


def test_config_loader_accepts_single_source_object(tmp_path):
    config_file = tmp_path / "requirement_decomposition.yaml"
    source_file = tmp_path / "order.md"
    source_file.write_text("# 取消订单\n用户可以取消待支付订单。", encoding="utf-8")
    config_file.write_text(
        yaml.safe_dump(
            {
                "project": {"project_id": "PROJECT-001", "project_name": "订单系统"},
                "sources": {
                    "source_id": "SRC-001",
                    "source_type": "markdown",
                    "path": "old.md",
                    "trust_level": "high",
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_file), source_path=str(source_file))

    assert len(config.sources) == 1
    assert config.sources[0].source_id == "SRC-001"
    assert config.sources[0].path == str(source_file)


def test_markdown_parser_and_chunker_preserve_heading_path_and_quote(tmp_path):
    source_file = tmp_path / "order.md"
    source_file.write_text(
        "# 订单\n\n## 取消订单\n用户可以取消待支付订单。\n\n## 支付订单\n用户可以支付订单。\n",
        encoding="utf-8",
    )

    document = parse_markdown_document(str(source_file), source_id="SRC-ORDER")
    sections = chunk_markdown_sections(document)

    assert document.source_id == "SRC-ORDER"
    assert [section.title for section in sections] == ["取消订单", "支付订单"]
    assert sections[0].section_id == "SEC-001"
    assert sections[0].heading_path == ["订单", "取消订单"]
    assert sections[0].content == "用户可以取消待支付订单。"
    assert sections[0].quote == "用户可以取消待支付订单。"


def test_requirement_model_defaults_keep_facts_and_suggestions_separate():
    requirement = Requirement(
        requirement_id="REQ-001",
        title="待支付订单允许取消",
        domain="订单",
        module="订单状态管理",
        feature="取消订单",
        description="订单状态为待支付时，订单创建人可以取消订单。",
        source_trace=SourceTrace(
            source_id="SRC-001",
            section_id="SEC-001",
            quote="用户可以取消待支付订单。",
        ),
    )

    assert requirement.status == "draft"
    assert requirement.requirement_facts.test_objects == []
    assert requirement.test_design_suggestions.risk_tags == []
    assert requirement.field_evidence == []
    assert requirement.llm_metadata.llm_enabled is False


def test_test_seed_generator_groups_requirements_by_feature_and_marks_uncertain():
    confirmed = Requirement(
        requirement_id="REQ-001",
        title="待支付订单允许取消",
        domain="订单",
        module="订单状态管理",
        feature="取消订单",
        description="订单状态为待支付时，订单创建人可以取消订单。",
        source_trace=SourceTrace(
            source_id="SRC-001",
            section_id="SEC-001",
            quote="用户可以取消待支付订单。",
        ),
        status="confirmed",
        requirement_facts=RequirementFacts(
            test_objects=[
                RequirementTestObject(name="订单状态", type="enum", values=["待支付"])
            ],
            constraints=[
                Constraint(
                    object="订单状态",
                    rule="订单状态必须为待支付",
                    constraint_type="state",
                    test_dimension="状态校验",
                )
            ],
            acceptance_criteria=[
                AcceptanceCriterion(
                    given="订单状态为待支付",
                    when="用户取消订单",
                    then="订单状态变为已取消",
                )
            ],
        ),
    )
    draft = confirmed.model_copy(update={"requirement_id": "REQ-002", "status": "draft"})

    seeds = generate_test_seeds([confirmed, draft])

    assert len(seeds) == 1
    assert seeds[0].requirement_id == "SEED-001"
    assert seeds[0].requirement_ids == ["REQ-001", "REQ-002"]
    assert "未确定" in seeds[0].status_tags
    assert seeds[0].test_seed.objects == ["订单状态"]
    assert seeds[0].test_seed.constraints == ["订单状态必须为待支付"]
    assert seeds[0].test_seed.expected_results == ["订单状态变为已取消"]
    assert "REQ-002: 状态为 draft" in seeds[0].test_seed.uncertain_items


def test_run_decomposition_requires_llm_enabled(tmp_path):
    source_file = tmp_path / "order.md"
    source_file.write_text(
        "# 订单系统\n\n## 取消订单\n用户可以取消待支付订单，已支付订单不可取消。\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "requirement_decomposition.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "project": {"project_id": "PROJECT-001", "project_name": "订单系统"},
                "llm": {"enabled": False},
                "sources": [
                    {
                        "source_id": "SRC-001",
                        "source_type": "markdown",
                        "path": str(source_file),
                        "trust_level": "high",
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    result = run_decomposition(source_path=str(source_file), config_path=str(config_file))

    assert result.success is False
    assert result.requirements == []
    assert "LLM 已关闭" in result.errors[0]
