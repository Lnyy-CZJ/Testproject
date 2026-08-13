---
prompt_name: fact_bundle_extract
version: v1.0
---
请从 Requirement 中一次性抽取测试点生成所需信息，只输出 JSON。

输出格式：
{
  "test_objects":[{"name":"","type":"","values":[]}],
  "constraints":[{"object":"","rule":"","constraint_type":"","test_dimension":""}],
  "state_model":{"entity":"","states":[],"transitions":[{"from":"","to":"","trigger":"","valid":true}]},
  "permissions":[{"role":"","rule":""}],
  "acceptance_criteria":[{"given":"","when":"","then":""}],
  "risk_tags":[],
  "negative_suggestions":[],
  "boundary_suggestions":[],
  "test_generation_hints":[]
}

要求：
1. 只基于原文和当前 Requirement，不要编造需求事实。
2. test_objects 表示测试点生成时“测什么”。
3. constraints 表示输入、业务、权限、状态等约束。
4. state_model 只在原文涉及状态时填写，否则使用空对象结构。
5. acceptance_criteria 必须是可验证的 Given / When / Then。
6. risk_tags 只能从以下枚举中选择：输入校验, 权限, 状态流转, 金额, 数据一致性, 并发, 幂等, 异常流程, 接口, 兼容性, 性能, 安全。
7. risk_tags 和 suggestions 是测试设计建议，不作为需求事实。

section_id: {{ section_id }}
原文:
{{ source_content }}

Requirement:
{{ requirement_title }}
{{ requirement_description }}
