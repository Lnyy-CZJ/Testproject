from __future__ import annotations

import json

import yaml

from requirement_decomposition import run_decomposition
from requirement_decomposition.generator.markdown_generator import _render_requirement
from requirement_decomposition.llm.llm_client import DefaultLLMClient
from agents.functional_test.prompts.generator_test_point import prompt as test_point_prompt
from requirement_decomposition.models.schema import (
    AcceptanceCriterion,
    Constraint,
    Requirement,
    RequirementFacts,
    SourceTrace,
    TestDesignSuggestions as RequirementTestDesignSuggestions,
    TestObject as RequirementTestObject,
)


class FakeMessage:
    """模拟 LangChain invoke 返回的消息对象。"""

    def __init__(self, content: str):
        self.content = content


class FakeLangChainLLM:
    """模拟项目中 agents.common.config.settings.llm 的最小接口。"""

    def __init__(self, content: str):
        self.content = content
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return FakeMessage(self.content)


def test_default_llm_client_uses_langchain_invoke_content():
    fake_llm = FakeLangChainLLM('{"items": []}')
    client = DefaultLLMClient(llm_instance=fake_llm)

    response = client.complete("test_object_extract", "只输出 JSON", config=None)

    assert response == '{"items": []}'
    assert fake_llm.prompts == ["只输出 JSON"]


def test_pipeline_uses_default_project_llm_when_enabled_without_injected_client(tmp_path, monkeypatch):
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
                "sources": [{"source_id": "SRC-001", "path": str(source_file)}],
                "llm": {"enabled": True},
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

    class FakeDefaultClient:
        def complete(self, task_name: str, prompt: str, config):
            payloads = {
                "requirement_split": [
                    {
                        "title": "待支付订单允许取消",
                        "description": "用户可以取消待支付订单。",
                        "confidence": 0.9,
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
                                }
                            ],
                            "state_model": {"entity": "订单", "states": ["待支付", "已支付"], "transitions": []},
                            "permissions": [{"role": "非本人", "rule": "非本人订单不可操作"}],
                            "acceptance_criteria": [
                                {
                                    "given": "订单状态为待支付",
                                    "when": "用户取消订单",
                                    "then": "用户可以取消待支付订单",
                                }
                            ],
                            "risk_tags": ["状态流转", "权限"],
                        }
                    ]
                },
            }
            return json.dumps(payloads[task_name], ensure_ascii=False)

    monkeypatch.setattr("requirement_decomposition.pipeline.DefaultLLMClient", FakeDefaultClient)
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")

    result = run_decomposition(source_path=str(source_file), config_path=str(config_file))

    assert result.success is True
    assert result.llm_trace["enabled"] is True
    assert result.llm_trace["model"] == "deepseek-v4-flash"
    assert result.requirements[0].title == "待支付订单允许取消"


def test_test_point_prompt_keeps_additional_context_separate_from_requirement() -> None:
    """补充说明必须作为非需求事实的独立区块进入测试点 Prompt。"""

    rendered = test_point_prompt.format(
        document="# 登录需求\n用户可以使用密码登录。",
        point=[],
        additional_context="重点覆盖重复提交和并发场景",
        format_instructions="输出 JSON",
    )

    assert "测试设计补充要求（非需求事实）" in rendered
    assert "重点覆盖重复提交和并发场景" in rendered


def test_requirement_markdown_rendering_contains_readable_facts_and_suggestions():
    requirement = Requirement(
        requirement_id="REQ-001",
        title="待支付订单允许取消",
        domain="订单系统",
        module="订单系统",
        feature="取消订单",
        description="用户可以取消待支付订单。",
        source_trace=SourceTrace(
            source_id="SRC-001",
            section_id="SEC-001",
            quote="用户可以取消待支付订单，已支付订单不可取消。",
        ),
        status="confirmed_candidate",
        requirement_facts=RequirementFacts(
            test_objects=[RequirementTestObject(name="订单状态", type="enum", values=["待支付", "已支付"])],
            constraints=[
                Constraint(
                    object="订单状态",
                    rule="已支付订单不可取消",
                    constraint_type="state",
                    test_dimension="状态校验",
                )
            ],
            acceptance_criteria=[
                AcceptanceCriterion(
                    given="订单状态为待支付",
                    when="用户取消订单",
                    then="用户可以取消待支付订单",
                )
            ],
        ),
        test_design_suggestions=RequirementTestDesignSuggestions(
            risk_tags=["状态流转"],
            test_generation_hints=["constraints: 重复点击取消订单"],
        ),
        grounding_check={"passed": True, "unsupported_items": []},
    )

    markdown = _render_requirement(requirement)

    assert "## 需求事实" in markdown
    assert "### 测试对象" in markdown
    assert "订单状态" in markdown
    assert "### 约束" in markdown
    assert "已支付订单不可取消" in markdown
    assert "## 测试设计建议" in markdown
    assert "状态流转" in markdown
    assert "## Grounding Check" in markdown
