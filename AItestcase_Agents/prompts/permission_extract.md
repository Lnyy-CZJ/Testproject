---
prompt_name: permission_extract
version: v1.0
---
请从 Requirement 中提取权限规则，只输出 JSON。

输出格式：
{"items":[{"role":"","rule":""}]}

section_id: {{ section_id }}
原文:
{{ source_content }}

Requirement:
{{ requirement_title }}
{{ requirement_description }}
