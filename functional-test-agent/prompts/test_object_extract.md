---
prompt_name: test_object_extract
version: v1.0
---
请从 Requirement 中提取测试对象，只输出 JSON。

输出格式：
{"items":[{"name":"","type":"","values":[]}]}

section_id: {{ section_id }}
原文:
{{ source_content }}

Requirement:
{{ requirement_title }}
{{ requirement_description }}
