from __future__ import annotations

import json
from pathlib import Path

import yaml

from requirement_decomposition import run_decomposition
from requirement_decomposition.chunker.section_chunker import chunk_markdown_sections
from requirement_decomposition.config.loader import load_config
from requirement_decomposition.llm.constraint_extractor import extract_constraints
from requirement_decomposition.llm.gwt_generator import generate_gwt_criteria
from requirement_decomposition.llm.llm_client import parse_json_response
from requirement_decomposition.llm.permission_extractor import extract_permissions
from requirement_decomposition.llm.prompt_loader import load_prompt
from requirement_decomposition.llm.requirement_splitter import split_requirements
from requirement_decomposition.llm.risk_tag_extractor import extract_risk_tags
from requirement_decomposition.llm.self_checker import run_llm_self_check
from requirement_decomposition.llm.state_model_extractor import extract_state_model
from requirement_decomposition.llm.test_object_extractor import extract_test_objects
from requirement_decomposition.models.schema import Requirement, RequirementFacts, SourceTrace
from requirement_decomposition.parser.document_parser import parse_markdown_document


class FakeLLMClient:
    """测试用可注入 LLM 客户端，按任务名返回固定 JSON。"""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[dict[str, str]] = []

    def complete(self, task_name: str, prompt: str, config) -> str:
        self.calls.append({"task_name": task_name, "prompt": prompt})
        payload = self.responses[task_name]
        return json.dumps(payload, ensure_ascii=False)


class RawFakeLLMClient:
    """按任务名返回原始字符串，用于测试 JSON 修复链。"""

    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.calls: list[str] = []

    def complete(self, task_name: str, prompt: str, config) -> str:
        self.calls.append(task_name)
        return self.responses[task_name]


def test_prompt_loader_reads_metadata_and_renders_variables(tmp_path):
    prompt_file = tmp_path / "sample.md"
    prompt_file.write_text(
        "---\nprompt_name: sample\nversion: v2.0\n---\n只输出 JSON。\n原文: {{ content }}\n",
        encoding="utf-8",
    )

    prompt = load_prompt("sample", prompt_dir=tmp_path)
    rendered = prompt.render({"content": "用户可以取消订单"})

    assert prompt.prompt_name == "sample"
    assert prompt.version == "v2.0"
    assert "用户可以取消订单" in rendered
    assert "{{ content }}" not in rendered


def test_default_prompt_dir_is_independent_from_current_working_directory(tmp_path, monkeypatch):
    """任务切换到独立 work 目录后，仍应从项目 prompts 目录加载模板。"""

    monkeypatch.chdir(tmp_path)
    prompt = load_prompt("requirement_split")

    assert prompt.prompt_name == "requirement_split"
    assert Path(prompt.path).name == "requirement_split.md"


def test_parse_json_response_accepts_fenced_json():
    data = parse_json_response(
        '```json\n{"items": [{"name": "订单状态", "type": "enum"}]}\n```'
    )

    assert data["items"][0]["name"] == "订单状态"


def test_requirement_splitter_normalizes_common_llm_type_drift(tmp_path):
    source_file = tmp_path / "order.md"
    source_file.write_text(
        "# 订单系统\n\n## 取消订单\n用户可以取消待支付订单。\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump({"sources": [{"path": str(source_file)}]}, allow_unicode=True),
        encoding="utf-8",
    )
    config = load_config(str(config_file), source_path=str(source_file))
    document = parse_markdown_document(str(source_file), source_id="SRC-001")
    section = chunk_markdown_sections(document)[0]
    client = FakeLLMClient(
        {
            "requirement_split": [
                {
                    "title": "订阅状态展示",
                    "description": "展示用户订阅状态。",
                    "confidence": "高",
                    "unresolved": "未明确订阅状态展示样式。",
                    "ambiguity_notes": "",
                    "conflict_items": "",
                }
            ]
        }
    )

    drafts = split_requirements(section, config.llm, client)

    assert drafts[0].confidence == 0.9
    assert drafts[0].unresolved == [
        {"field": "unknown", "reason": "未明确订阅状态展示样式。"}
    ]
    assert drafts[0].ambiguity_notes == []
    assert drafts[0].conflict_items == []


def test_requirement_splitter_repairs_invalid_json_once(tmp_path):
    source_file = tmp_path / "feedback.md"
    source_file.write_text("# 反馈\n\n## 输入框\n用户可以输入反馈内容。\n", encoding="utf-8")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump({"sources": [{"path": str(source_file)}]}, allow_unicode=True),
        encoding="utf-8",
    )
    config = load_config(str(config_file), source_path=str(source_file))
    document = parse_markdown_document(str(source_file), source_id="SRC-001")
    section = chunk_markdown_sections(document)[0]
    client = RawFakeLLMClient(
        {
            "requirement_split": '[{"title":"反馈内容输入" "description":"用户可以输入反馈内容。"}]',
            "json_repair": '[{"title":"反馈内容输入","description":"用户可以输入反馈内容。"}]',
        }
    )

    drafts = split_requirements(section, config.llm, client)

    assert client.calls == ["requirement_split", "json_repair"]
    assert drafts[0].title == "反馈内容输入"


def test_requirement_splitter_merges_ui_display_section(tmp_path):
    source_file = tmp_path / "account.md"
    source_file.write_text(
        "# 个人中心\n\n## 2.1 页面布局\n页面标题显示 My Account，右上角显示设置图标。\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump({"sources": [{"path": str(source_file)}]}, allow_unicode=True),
        encoding="utf-8",
    )
    config = load_config(str(config_file), source_path=str(source_file))
    document = parse_markdown_document(str(source_file), source_id="SRC-001")
    section = chunk_markdown_sections(document)[0]
    client = FakeLLMClient(
        {
            "requirement_split": [
                {"title": "页面标题显示 My Account", "description": "页面标题显示 My Account。"},
                {"title": "右上角显示设置图标", "description": "右上角显示设置图标。"},
            ]
        }
    )

    drafts = split_requirements(section, config.llm, client)

    assert len(drafts) == 1
    assert drafts[0].title == "2.1 页面布局页面展示与视觉校验"
    assert "页面标题显示 My Account" in drafts[0].description
    assert "右上角显示设置图标" in drafts[0].description


def test_test_object_extractor_normalizes_dict_values(tmp_path):
    source_file = tmp_path / "faq.md"
    source_file.write_text("# 个人中心\n\n## 问题列表\n展示常见问题。\n", encoding="utf-8")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump({"sources": [{"path": str(source_file)}]}, allow_unicode=True),
        encoding="utf-8",
    )
    config = load_config(str(config_file), source_path=str(source_file))
    document = parse_markdown_document(str(source_file), source_id="SRC-001")
    section = chunk_markdown_sections(document)[0]
    draft = split_requirements(
        section,
        config.llm,
        FakeLLMClient(
            {
                "requirement_split": [
                    {"title": "展示常见问题", "description": "页面展示常见问题。"}
                ]
            }
        ),
    )[0]
    client = FakeLLMClient(
        {
            "test_object_extract": {
                "items": [
                    {
                        "name": "问题列表",
                        "type": "list",
                        "values": [{"问题": "问题例子1", "说明": "问题说明"}],
                    }
                ]
            }
        }
    )

    objects = extract_test_objects(section, draft, config.llm, client)

    assert objects[0].values == ["问题: 问题例子1；说明: 问题说明"]


def test_splitter_and_extractors_map_llm_json_to_models(tmp_path):
    source_file = tmp_path / "order.md"
    source_file.write_text(
        "# 订单系统\n\n## 取消订单\n用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump({"sources": [{"path": str(source_file)}]}, allow_unicode=True),
        encoding="utf-8",
    )
    config = load_config(str(config_file), source_path=str(source_file))
    document = parse_markdown_document(str(source_file), source_id="SRC-001")
    section = chunk_markdown_sections(document)[0]
    client = FakeLLMClient(
        {
            "requirement_split": [
                {
                    "title": "待支付订单允许取消",
                    "description": "订单状态为待支付时，订单创建人可以取消订单。",
                    "confidence": 0.88,
                    "reasoning_summary": "原文包含状态和权限规则。",
                }
            ],
            "test_object_extract": {
                "items": [
                    {"name": "订单状态", "type": "enum", "values": ["待支付", "已支付"]},
                    {"name": "用户身份", "type": "role", "values": ["订单创建人", "非订单创建人"]},
                ]
            },
            "constraint_extract": {
                "items": [
                    {
                        "object": "订单状态",
                        "rule": "订单状态必须为待支付",
                        "constraint_type": "state",
                        "test_dimension": "状态校验",
                    }
                ]
            },
            "state_model_extract": {
                "entity": "订单",
                "states": ["待支付", "已支付", "已取消"],
                "transitions": [
                    {"from": "待支付", "to": "已取消", "trigger": "取消订单", "valid": True}
                ],
            },
            "permission_extract": {
                "items": [{"role": "订单创建人", "rule": "只有订单创建人可以取消订单"}]
            },
            "gwt_generate": {
                "items": [
                    {
                        "given": "订单状态为待支付且用户为订单创建人",
                        "when": "用户执行取消订单",
                        "then": "订单状态变为已取消",
                    }
                ]
            },
            "risk_tag_extract": {"risk_tags": ["状态流转", "权限"]},
            "self_check": {"passed": True, "issues": []},
        }
    )

    drafts = split_requirements(section, config.llm, client)
    draft = drafts[0]

    assert draft.title == "待支付订单允许取消"
    assert extract_test_objects(section, draft, config.llm, client)[0].name == "订单状态"
    assert extract_constraints(section, draft, config.llm, client)[0].rule == "订单状态必须为待支付"
    assert extract_state_model(section, draft, config.llm, client).states == ["待支付", "已支付", "已取消"]
    assert extract_permissions(section, draft, config.llm, client)[0].role == "订单创建人"
    assert generate_gwt_criteria(section, draft, config.llm, client)[0].then == "订单状态变为已取消"
    assert extract_risk_tags(section, draft, config.llm, client) == ["状态流转", "权限"]

    requirement = Requirement(
        requirement_id="REQ-001",
        title=draft.title,
        description=draft.description,
        source_trace=SourceTrace(
            source_id=section.source_id,
            section_id=section.section_id,
            quote=section.quote,
        ),
        requirement_facts=RequirementFacts(),
    )
    assert run_llm_self_check(section, requirement, config.llm, client).passed is True


def test_run_decomposition_uses_injected_llm_chain_and_outputs_fields(tmp_path):
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
                    "description": "订单状态为待支付时，订单创建人可以取消订单。",
                    "confidence": 0.91,
                    "reasoning_summary": "拆出状态和身份条件。",
                }
            ],
            "fact_bundle_batch_extract": {
                "items": [
                    {
                        "index": 0,
                        "test_objects": [
                            {"name": "订单状态", "type": "enum", "values": ["待支付", "已支付"]}
                        ],
                        "constraints": [
                            {
                                "object": "订单状态",
                                "rule": "订单状态必须为待支付",
                                "constraint_type": "state",
                                "test_dimension": "状态校验",
                            }
                        ],
                        "state_model": {
                            "entity": "订单",
                            "states": ["待支付", "已支付", "已取消"],
                            "transitions": [
                                {"from": "待支付", "to": "已取消", "trigger": "取消订单", "valid": True},
                                {"from": "已支付", "to": "已取消", "trigger": "取消订单", "valid": False},
                            ],
                        },
                        "permissions": [{"role": "订单创建人", "rule": "非订单创建人不可取消订单"}],
                        "acceptance_criteria": [
                            {
                                "given": "订单状态为待支付且用户为订单创建人",
                                "when": "用户执行取消订单",
                                "then": "订单状态变为已取消",
                            }
                        ],
                        "risk_tags": ["状态流转", "权限", "幂等"],
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

    assert result.success is True
    assert result.llm_trace["enabled"] is True
    assert [call["task_name"] for call in client.calls] == [
        "requirement_split",
        "fact_bundle_batch_extract",
    ]
    assert requirement.title == "待支付订单允许取消"
    assert requirement.status == "draft"
    assert requirement.requirement_facts.test_objects[0].name == "订单状态"
    assert requirement.requirement_facts.constraints[0].constraint_type == "state"
    assert requirement.requirement_facts.state_model.transitions[1].valid is False
    assert requirement.requirement_facts.permissions[0].role == "订单创建人"
    assert requirement.requirement_facts.acceptance_criteria[0].then == "订单状态变为已取消"
    assert requirement.test_design_suggestions.risk_tags == ["状态流转", "权限", "幂等"]
    assert requirement.llm_self_check.passed is True
    assert requirement.llm_metadata.llm_enabled is True
    assert requirements_json["requirements"][0]["requirement_facts"]["test_objects"][0]["name"] == "订单状态"
    assert requirements_json["requirements"][0]["test_design_suggestions"]["risk_tags"] == [
        "状态流转",
        "权限",
        "幂等",
    ]


def test_run_decomposition_accepts_output_dir_override(tmp_path):
    source_file = tmp_path / "history.md"
    configured_output_dir = tmp_path / "configured"
    override_output_dir = tmp_path / "requirements_docs" / "历史记录"
    source_file.write_text(
        "# 历史记录\n\n## 历史记录列表\n用户可以查看历史记录。\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "requirement_decomposition.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "project": {"project_id": "PROJECT-001", "project_name": "检索系统"},
                "sources": [{"source_id": "SRC-001", "path": str(source_file)}],
                "output": {
                    "requirement_json": {
                        "enabled": True,
                        "path": str(configured_output_dir / "requirements.json"),
                    },
                    "markdown": {"enabled": True, "path": str(configured_output_dir / "requirements_md")},
                    "test_seed": {"enabled": True, "path": str(configured_output_dir / "test_seed.json")},
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
                    "title": "历史记录列表展示",
                    "description": "用户可以查看历史记录。",
                    "confidence": 0.91,
                    "reasoning_summary": "拆出历史记录列表需求。",
                }
            ],
            "fact_bundle_batch_extract": {
                "items": [
                    {
                        "index": 0,
                        "test_objects": [{"name": "历史记录列表", "type": "ui", "values": []}],
                        "constraints": [],
                        "state_model": {"entity": "", "states": [], "transitions": []},
                        "permissions": [],
                        "acceptance_criteria": [
                            {
                                "given": "用户进入历史记录页面",
                                "when": "系统加载历史记录",
                                "then": "展示历史记录列表",
                            }
                        ],
                        "risk_tags": [],
                    }
                ]
            },
        }
    )

    result = run_decomposition(
        source_path=str(source_file),
        config_path=str(config_file),
        llm_client=client,
        output_dir=str(override_output_dir),
    )

    assert result.success is True
    assert (override_output_dir / "requirements.json").is_file()
    assert (override_output_dir / "requirements_md").is_dir()
    assert (override_output_dir / "test_seed.json").is_file()
    assert not (configured_output_dir / "requirements.json").exists()
