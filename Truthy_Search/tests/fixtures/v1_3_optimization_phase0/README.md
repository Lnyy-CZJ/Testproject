# v1.3 MVP 优化阶段0接口契约夹具

本目录保存阶段0冻结的脱敏 Mock，不代表生产接口已经正式提供这些字段。

## 文件

- `get_task_public_fields_full.json`：GetTask 成功终态，新增公共字段全部有值。
- `get_task_public_fields_partial.json`：GetTask 成功终态，仅部分公共字段有值。
- `candidate_detail_optional_fields_missing.json`：Candidate Detail 中可选数组为空、
  可选对象为 `null`。
- `baseline_available_fields.jsonl`：Baseline 导入的目标结构样例。

## 已确认

- GetTask 使用 `responses[0].data`。
- `candidate_confidence` 对应
  `ui_sections.summary.data.confidence_level`。
- 可选业务路径不存在、数组为空或父对象为 `null` 时，应处理为空值。
- 成本、耗时和 PDL 字段缺失时保持 `null`，不能按0补齐。

## 待后端确认

- `llm_cost`、`third_party_cost`、`total_cost`、`pdl_called` 和
  `search_duration_ms` 的正式接口路径。
- 成本单位。
- `total_cost` 是否已经包含 LLM 和第三方成本。
- `pdl_called` 是否为严格布尔值。
- `search_duration_ms` 是否包含排队时间。
- `baseline_available_fields` 的正式来源接口和字段键命名。
- Summary Confidence Level 的完整枚举。

Mock 中的数值仅用于验证类型、缺失和聚合边界，不用于业务结论。
