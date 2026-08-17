---
prompt_name: self_check
version: v1.0
---
请对 Requirement 拆解结果做自检，只输出 JSON。

输出格式：
{"passed":true,"issues":[]}

自检问题：
1. 是否存在多个业务规则被错误合并？
2. 是否存在不可测试的 Requirement？
3. 是否遗漏权限、状态、边界、异常？
4. 是否存在原文没有依据的推断被放入 requirement_facts？
5. 是否所有关键字段都能追溯到 source_trace？

section_id: {{ section_id }}
原文:
{{ source_content }}

Requirement JSON:
{{ requirement_json }}
