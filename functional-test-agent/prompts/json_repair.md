---
prompt_name: json_repair
version: v1.0
---
请修复下面 LLM 输出中的 JSON 格式错误，只输出修复后的合法 JSON。

要求：
1. 不要新增业务内容。
2. 不要删除原有字段。
3. 不要输出解释。
4. 如果原始内容是 JSON 数组，修复后仍输出 JSON 数组。
5. 如果原始内容是 JSON 对象，修复后仍输出 JSON 对象。

task_name: {{ task_name }}

raw_response:
{{ raw_response }}
