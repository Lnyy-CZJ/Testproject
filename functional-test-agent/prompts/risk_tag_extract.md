---
prompt_name: risk_tag_extract
version: v1.0
---
请从 Requirement 中识别测试风险标签，只输出 JSON。

输出格式：
{"risk_tags":["状态流转","权限"]}

风险标签只能从以下枚举中选择：
输入校验, 权限, 状态流转, 金额, 数据一致性, 并发, 幂等, 异常流程, 接口, 兼容性, 性能, 安全

要求：
1. 风险标签用于提示测试点生成方向，不作为需求事实。
2. 不要生成枚举之外的标签。
3. 如果没有明显风险，输出 {"risk_tags":[]}。

section_id: {{ section_id }}
原文:
{{ source_content }}

Requirement:
{{ requirement_title }}
{{ requirement_description }}
