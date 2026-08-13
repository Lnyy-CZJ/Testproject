---
prompt_name: state_model_extract
version: v1.0
---
请从 Requirement 中提取状态模型，只输出 JSON。

输出格式：
{"entity":"","states":[],"transitions":[{"from":"","to":"","trigger":"","valid":true}]}

section_id: {{ section_id }}
原文:
{{ source_content }}

Requirement:
{{ requirement_title }}
{{ requirement_description }}
