---
prompt_name: constraint_extract
version: v1.0
---
请从 Requirement 中提取约束，只输出 JSON。

输出格式：
{"items":[{"object":"","rule":"","constraint_type":"","test_dimension":""}]}

约束类型只能从以下范围选择：
required, format, length, range, enum, state, permission, unique, business_rule, dependency

section_id: {{ section_id }}
原文:
{{ source_content }}

Requirement:
{{ requirement_title }}
{{ requirement_description }}
