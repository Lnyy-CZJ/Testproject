---
prompt_name: gwt_generate
version: v1.0
---
请为 Requirement 生成 Given / When / Then 验收标准，只输出 JSON。

输出格式：
{"items":[{"given":"","when":"","then":""}]}

要求：
1. given 描述前置状态或条件。
2. when 描述触发动作。
3. then 描述可验证结果。

section_id: {{ section_id }}
原文:
{{ source_content }}

Requirement:
{{ requirement_title }}
{{ requirement_description }}
