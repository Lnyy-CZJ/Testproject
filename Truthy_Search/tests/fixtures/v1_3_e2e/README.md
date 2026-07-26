# v1.3 阶段7端到端验收夹具

本目录保存阶段7使用的固定脱敏夹具，用于贯通“历史结果导入 → 字段处理
→ 人工复核 → 指标 → 对比报告 → HTML/Excel”流程。

- `baseline.jsonl`：2名虚构人物的字段基准；
- `baseline_results.jsonl`：baseline Run，每人包含 `FULL_NAME` 和
  `FULL_NAME_SOCIAL`；
- `baseline_failures.jsonl`：一名 Candidate Detail 失败，验证候选人失败隔离；
- `candidate_results.jsonl`：candidate Run，包含可配置提取的未知
  `future_module` 字段；
- `candidate_failures.jsonl`：一条 Query 失败，验证失败可追溯且不伪造结果；
- `candidate_metadata.jsonl`：为失败 Query 保留 Person 和 Query 条件，确保版本
  对比仍按同人同条件配对。

测试会给成功候选人写入 `HIT`、`NOT_HIT` 和 `SUSPECTED` 复核结果。两个
Run 的成本字段均为空，用于验证“未接入”状态。

所有姓名、标识和链接均为虚构数据，只使用 `example.test` 域名；夹具不包含
Token、Cookie、HTTP Header、Device ID、User ID 或真实个人数据。
