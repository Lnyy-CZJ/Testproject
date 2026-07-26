# v1.3 阶段0基线夹具

本目录保存阶段0冻结的脱敏最小数据，用于验证当前 JSONL 结构和 Excel 导出兼容性。

- `tasks.jsonl`：包含 `FULL_NAME`、`FULL_NAME_SOCIAL` 和一条失败场景输入；
- `query_metadata.jsonl`：通过 `query_id = input_id` 提供 Person 和 Query 元数据；
- `results.jsonl`：当前成功结果结构，包含候选人数、排名、`rank_score` 和五个 `ui_sections`；
- `failures.jsonl`：当前失败记录结构。

夹具只使用 `example.test` 和虚构人物，不包含真实凭证或个人数据。
