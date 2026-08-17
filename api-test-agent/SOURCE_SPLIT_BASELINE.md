# 源码拆分基线

- 基线日期：2026-08-17
- 旧仓库：`AItestcase_Agents`
- Git commit：`f1a6260d44a9`
- 预留 tag（未创建）：`ai-agents-split-baseline-20260817`
- 权威清单：`../test-platform/docs/split-baseline-manifest.json`
- 逐文件归属：`../test-platform/docs/split-inventory.json`

拆分只复制 API 可信生成、Review、Controller、Egress 与 Executor 源码；未迁移或修改旧仓库的 `output/`、Secret 与运行数据。
