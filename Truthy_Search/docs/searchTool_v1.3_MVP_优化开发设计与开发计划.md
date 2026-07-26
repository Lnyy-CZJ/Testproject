# searchTool v1.3 MVP 优化开发设计与开发计划

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | searchTool v1.3 MVP 优化开发设计与开发计划 |
| 文档版本 | v1.0 |
| 编写日期 | 2026-07-24 |
| 需求依据 | `docs/searchTool_v1.3_MVP_优化需求.md` |
| 现有基线 | searchTool v1.3 MVP 阶段0～阶段7 |
| 实施原则 | 复用现有架构、最小增量、Raw 不丢失、处理与报告可复现 |
| 优化主线 | 补充数据字段 → 修正指标口径 → 升级报告 |

## 2. 开发目标

### 2.1 任务目标

在不重做现有顺序检索流程的前提下，完成以下优化：

1. 扩展现有字段配置，使其同时支持 Query 公共字段和 Candidate 业务字段；
2. 从完整 Raw 中提取新增 Task 公共字段，并保存不可变处理快照；
3. 将 `candidate_confidence` 统一映射到 Summary Confidence Level；
4. 将可选路径不存在改为正常空值；
5. 使用每个人的 `baseline_available_fields` 计算命中完整度；
6. 统一 Query 结果状态并增加结果率；
7. 增加成本、耗时、PDL 和置信度指标；
8. 增加 `evaluation_phase`；
9. 升级单次报告和对比报告；
10. 保证现有 SQLite、Raw、Process 和报告快照可继续使用。

### 2.2 成功标准

- 接口返回新字段后，通过字段配置即可提取到新 Process；
- 新字段路径变化不需要重写采集主流程；
- 空数组、缺失对象和 `null` 父节点不再产生虚假字段错误；
- 新指标不再固定除以22；
- 部分成本字段缺失时，其他有效成本仍可统计；
- 单 Run 无对比 Run 时仍可生成 HTML/Excel 报告；
- 同条件版本对比和新增线索实验在报告中分开展示；
- 数据库从 Schema v1 平滑升级到 v2；
- 旧 Process 使用旧规则，旧报告继续读取原快照；
- 全量自动化测试和人工验收通过。

### 2.3 交付物

- SQLite Schema v2 与 v1→v2 迁移；
- 字段配置 v2；
- Query/Candidate 字段处理 v2；
- 指标规则 v2；
- ReportModel v2；
- Web 页面和导出更新；
- 自动化测试、测试数据和验收记录；
- README/运行说明更新。

## 3. 需求边界

### 3.1 本次实现

- `FULL_NAME`、`FULL_NAME_SOCIAL`；
- 本地/测试环境单用户；
- Web 执行和历史结果导入；
- JSONL/Excel；
- Query/Candidate/Raw 下钻；
- Baseline、复核、指标和报告；
- 新增公共字段、空值策略、阶段、阈值和建议；
- 旧数据重新处理。

### 3.2 本次不实现

- `FULL_NAME_PHOTO` 输入和 PUT 上传；
- 多用户、角色权限、审批流；
- 通用表达式、脚本或 `eval`；
- Provider/Evidence/Social Accounts 完整结构化；
- 排名质量、重复运行一致性和错误类型指标；
- 自动采集第三方 Baseline；
- 平台自动代替业务负责人决定上线。

## 4. 现有架构评估

### 4.1 当前主流程

```text
Dataset
  → Run
  → CreateIntentTask
  → GetTask 轮询
  → ListTaskCandidates
  → 全部 GetTaskCandidateDetail
  → Raw + SQLite
  → 选择字段配置生成 Process
  → Baseline + 人工复核
  → 指标
  → ReportModel
  → Web / HTML / Excel
```

本次不改变接口调用顺序，也不引入并发任务系统。

### 4.2 当前可复用能力

| 能力 | 复用方式 |
| --- | --- |
| 顺序检索 | 保持 `search_tool.py` 主流程不变 |
| Raw 回调和存储 | 继续保存每个接口的完整请求/响应 |
| SQLite Repository | 在 `analysis_store.py` 增加 Schema v2 迁移 |
| 字段配置 | 扩展现有 `field_schemas.definitions_json` |
| Process 快照 | 增加 Query 级处理快照，保留 Candidate 快照 |
| Baseline | 扩展 `baseline_people` |
| 复核 | 继续使用 `reviews`，调整字段可用性口径 |
| 报告快照 | 继续保存完整 `metrics_json` |
| HTML/Excel | 升级共用 ReportModel，不建立第二套指标 |

### 4.3 当前主要技术限制

1. SQLite 只支持 Schema v1，遇到其他版本直接拒绝启动；
2. Task 字段配置实际只能读取构造出的固定 `task` 对象；
3. 采集结果将成本字段固定为 `null`；
4. Query 没有 Process 级不可变字段快照；
5. 路径缺失和路径结构错误共用一个异常；
6. 完整度使用常量22；
7. 成本聚合要求所有字段全部非空；
8. 报告只按 `query_stage` 聚合；
9. 对比逻辑没有区分同条件和新增线索。

## 5. 总体设计

### 5.1 设计原则

1. **Raw 是事实源**：任何配置或算法更新都不能修改 Raw。
2. **Process 是处理快照**：Query 和 Candidate 的结构化结果都绑定
   `schema_version + baseline_version + rule_version`。
3. **报告是不可变快照**：打开旧报告不得重新计算。
4. **配置负责路径，代码负责业务含义**：接口路径可配置，成本、状态和指标含义固定。
5. **空值不是错误**：业务字段可选，只有语法、结构或类型冲突才是错误。
6. **新旧规则并存**：旧 Process 按 v1 读取，新 Process 使用 v2。
7. **不重复建设**：字段配置仍使用现有页面和版本表，不新增通用规则引擎。

### 5.2 优化后流程

```text
接口执行/历史导入
  ├─ 保存结构化基础数据
  └─ 保存完整 Raw
         ↓
选择字段配置 v2 + Baseline
         ↓
Query 公共字段处理 ──→ processed_queries
Candidate 业务字段处理 → processed_candidates
         ↓
人工复核 + baseline_available_fields
         ↓
指标规则 v2
  ├─ 结果状态
  ├─ 成功/完整度/准确率
  ├─ 成本/耗时/PDL
  └─ Confidence
         ↓
ReportModel v2
  ├─ 单 Run
  ├─ 同条件版本对比
  └─ 新增线索实验
         ↓
Web / 静态 HTML / Excel
```

## 6. 字段配置 v2

### 6.1 配置复用方案

不创建独立的公共字段配置表。继续使用：

```text
field_schemas.schema_version
field_schemas.definitions_json
```

每个字段定义增加两个属性：

| 属性 | 可选值 | 说明 |
| --- | --- | --- |
| `value_scope` | `QUERY` / `CANDIDATE` | 字段属于 Query 还是 Candidate |
| `missing_policy` | `EMPTY` / `ERROR` | 路径缺失按空值还是错误处理 |

现有属性继续保留：

- `field_key`；
- `display_name`；
- `module`；
- `source_stage`；
- `source_path`；
- `data_type`；
- `array_mode`；
- `empty_rule`；
- `normalizer`；
- `scoring_role`；
- `compare_mode`；
- `enabled`；
- `sort_order`。

### 6.2 旧配置兼容

旧定义没有 `value_scope` 时：

- `module == "Task"` 推断为 `QUERY`；
- 其他模块推断为 `CANDIDATE`。

旧定义没有 `missing_policy` 时：

- `task_id`、`candidate_id` 等系统必需字段推断为 `ERROR`；
- `ui_sections` 下的业务字段推断为 `EMPTY`；
- 其他普通展示字段默认 `EMPTY`。

发布新配置时保存完整字段，不再依赖运行时推断。

### 6.3 Query 公共字段定义

默认字段配置 v2 增加或更新：

```json
[
  {
    "field_key": "llm_cost",
    "display_name": "LLM Cost",
    "module": "Task",
    "value_scope": "QUERY",
    "source_stage": "GetTask",
    "source_path": "task.llm_cost",
    "data_type": "number",
    "missing_policy": "EMPTY",
    "scoring_role": ["display"]
  },
  {
    "field_key": "third_party_cost",
    "display_name": "Third Party Cost",
    "module": "Task",
    "value_scope": "QUERY",
    "source_stage": "GetTask",
    "source_path": "task.third_party_cost",
    "data_type": "number",
    "missing_policy": "EMPTY",
    "scoring_role": ["display"]
  },
  {
    "field_key": "total_cost",
    "display_name": "Total Cost",
    "module": "Task",
    "value_scope": "QUERY",
    "source_stage": "GetTask",
    "source_path": "task.total_cost",
    "data_type": "number",
    "missing_policy": "EMPTY",
    "scoring_role": ["display"]
  },
  {
    "field_key": "pdl_called",
    "display_name": "PDL Called",
    "module": "Task",
    "value_scope": "QUERY",
    "source_stage": "GetTask",
    "source_path": "task.pdl_called",
    "data_type": "boolean",
    "missing_policy": "EMPTY",
    "scoring_role": ["display"]
  },
  {
    "field_key": "search_duration_ms",
    "display_name": "Search Duration (ms)",
    "module": "Task",
    "value_scope": "QUERY",
    "source_stage": "GetTask",
    "source_path": "task.search_duration_ms",
    "data_type": "number",
    "missing_policy": "EMPTY",
    "scoring_role": ["display"]
  }
]
```

实际 `source_path` 在后端提供正式响应后确认。字段键和类型先固定，路径允许通过新版本
配置更新。

### 6.4 Candidate Confidence

默认字段配置 v2 使用：

```json
{
  "field_key": "candidate_confidence",
  "display_name": "Candidate Confidence",
  "module": "Summary",
  "value_scope": "CANDIDATE",
  "source_stage": "GetTaskCandidateDetail",
  "source_path": "ui_sections.summary.data.confidence_level",
  "data_type": "string",
  "missing_policy": "EMPTY",
  "normalizer": "trim_text",
  "scoring_role": ["display"]
}
```

兼容规则：

- 新指标优先读取 `candidate_confidence`；
- 旧 Process 没有该键时回退读取 `summary_confidence_level`；
- 两者同时存在时只统计一次；
- 不把置信度直接转换为 HIT/NOT_HIT。

### 6.5 配置校验

`validate_field_definitions()` 增加：

- `value_scope` 枚举校验；
- `missing_policy` 枚举校验；
- Query 字段只能使用允许的 `source_stage`；
- `candidate_confidence` 类型必须为 string；
- 成本/耗时必须为 number；
- `pdl_called` 必须为 boolean；
- `field_key` 继续保持全配置唯一；
- 不允许条件表达式、函数或脚本。

## 7. Raw 与处理源设计

### 7.1 Raw 保持不变

执行模式继续保存：

```json
{
  "stage": "GetTask",
  "sequence_no": 3,
  "request_params": {},
  "response_body": {},
  "error": "",
  "collected_at": ""
}
```

历史结果导入继续拆分为相同的 `raw_records` 阶段记录。

### 7.2 Query 处理源

处理 Query 公共字段时，根据 `run_id + query_id + source_stage` 读取 Raw。

GetTask 选择规则：

1. 按 `sequence_no` 正序解析；
2. 优先选择最后一条状态为 `SUCCEEDED` 的响应；
3. 没有可识别终态时使用最后一条成功保存的响应；
4. 没有对应 Raw 时返回空处理源并标记公共字段缺失；
5. Raw JSON 损坏才记录结构错误。

将响应统一构造成：

```json
{
  "query": {
    "query_id": "",
    "person_id": "",
    "query_stage": "",
    "task_id": "",
    "result_status": ""
  },
  "task": {
    "status": "SUCCEEDED",
    "llm_cost": null,
    "third_party_cost": null,
    "total_cost": null,
    "pdl_called": null,
    "search_duration_ms": null
  },
  "raw": {}
}
```

其中 `task` 为 GetTask 的 `responses[0].data`。`raw` 保留完整响应，供后端实际路径
不是直接字段时配置使用。

### 7.3 Candidate 处理源

保持现有结构：

```json
{
  "candidate": {
    "candidate_id": "",
    "candidate_rank": 1,
    "rank_score": 0.0,
    "detail_status": ""
  },
  "ui_sections": {},
  "...detail_data": {}
}
```

Candidate Detail 缺失时仍保留 List 基础信息，详情字段不伪装成接口返回空值。

### 7.4 采集结果的兼容增强

`search_tool.py` 做最小增量：

- `result_schema_version` 从 `1.3` 更新为向后兼容的小版本，例如 `1.3.1`；
- Query 结果增加规范化 `result_status`；
- `task_fields` 增加
  `third_party_cost`、`search_duration_ms`；
- 最终 GetTask 数据中存在同名字段时直接保存；
- 不存在时保持 `null`；
- Raw 继续作为路径变化后的重新处理依据。

采集层的直接字段只用于 results.jsonl 和基础结构化展示；Process 内的字段配置快照是
指标和报告的正式来源。

## 8. 路径提取与空值设计

### 8.1 缺失值哨兵

内部增加只在处理器使用的 `MISSING` 哨兵，区分：

- JSON 明确返回 `null`；
- 路径不存在；
- 数组索引不存在；
- 真正结构错误。

最终输出中，`MISSING` 按字段类型转换为：

- 普通字段：`null`；
- 通配/collect 数组：`[]`。

### 8.2 提取规则

`extract_source_path()` 调整为：

| 场景 | `EMPTY` | `ERROR` |
| --- | --- | --- |
| 字典不存在 key | 返回缺失 | 抛出字段错误 |
| 当前父值为 `null` | 返回缺失 | 抛出字段错误 |
| 数组为空或索引越界 | 返回缺失 | 抛出字段错误 |
| 通配数组为空 | 返回 `[]` | 返回 `[]` |
| 应为字典但实际为字符串/数字 | 结构错误 | 结构错误 |
| 应为数组但实际不是数组 | 结构错误 | 结构错误 |
| 路径语法非法 | 配置校验失败 | 配置校验失败 |

### 8.3 三个已知问题

以下情况必须验证：

```text
ui_sections.insights.data.items[0].description
ui_sections.insights.data.items[0].links
ui_sections.summary.data.primary_image.url
```

预期：

- `items=[]` 时 description 为 `null`；
- `items=[]` 时 links 为 `[]` 或 `null`，由字段类型/array_mode 决定；
- `primary_image=null` 时 URL 为 `null`；
- 三者均进入 `empty_fields_json`；
- 三者均不进入 `processing_errors_json`。

### 8.4 Process 错误统计

Process 页面分开显示：

- Candidate 数；
- Query 公共字段空值数；
- Candidate 业务字段空值数；
- 真正字段错误数；
- Detail 失败数。

`process_runs.error_count` 只统计真正的结构、类型和配置错误。

## 9. 数据库 Schema v2

### 9.1 版本策略

将：

```python
DB_SCHEMA_VERSION = 1
```

升级为：

```python
DB_SCHEMA_VERSION = 2
```

初始化逻辑改为：

1. 新数据库直接创建 Schema v2；
2. Schema v1 在单个事务中执行 v1→v2；
3. 迁移成功后更新 `schema_info`；
4. 迁移失败完整回滚；
5. 大于当前版本继续拒绝启动；
6. 不删除表、不清空数据、不覆盖 Raw。

### 9.2 evaluations

增加：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `thresholds_json` | TEXT NOT NULL | `{}` | Evaluation 级参考线配置 |

评估阶段不放在 Evaluation 上，避免同一个 Evaluation 无法同时容纳多个阶段。

### 9.3 runs

增加：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `evaluation_phase` | TEXT NOT NULL | `UNSPECIFIED` | 本次 Run 所属评估阶段 |

允许值：

- `PHASE_1_BASELINE`；
- `PHASE_2_POST_OPTIMIZATION`；
- `PHASE_3_TARGETED_ITERATION`；
- `UNSPECIFIED`。

### 9.4 run_queries

增加：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `result_status` | TEXT | `NULL` | 规范化结果状态 |
| `third_party_cost` | REAL | `NULL` | 第三方成本 |
| `search_duration_ms` | INTEGER | `NULL` | 接口返回检索耗时 |
| `public_fields_json` | TEXT NOT NULL | `{}` | 未进入固定列的公共字段 |

保留已有：

- `status`：运行/采集明细状态；
- `llm_cost`；
- `total_cost`；
- `pdl_called`。

`status` 与 `result_status` 不合并：

- `status` 用于运行进度、部分 Detail 失败等运维信息；
- `result_status` 只用于评估结果分类。

### 9.5 baseline_people

增加：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `available_fields_json` | TEXT NOT NULL | `[]` | 已确认可评估字段 |
| `available_fields_source` | TEXT NOT NULL | `UNSPECIFIED` | API/IMPORT/MANUAL/DERIVED_LEGACY |

### 9.6 processed_queries

新增 Process 级 Query 快照表：

```sql
CREATE TABLE processed_queries (
    process_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    result_status TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    empty_fields_json TEXT NOT NULL,
    processing_errors_json TEXT NOT NULL,
    PRIMARY KEY (process_id, query_id),
    FOREIGN KEY (process_id)
        REFERENCES process_runs(process_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, query_id)
        REFERENCES run_queries(run_id, query_id)
);
```

设计原因：

- 同一 Run 可以使用不同字段配置重新处理；
- 不修改旧 Process 的 Task 字段结果；
- 指标与报告绑定同一次 Process；
- 新接口路径确认后可从旧 Raw 重新生成。

增加索引：

```sql
CREATE INDEX idx_processed_queries_process_status
ON processed_queries(process_id, result_status);
```

### 9.7 reports

不增加业务列。ReportModel v2、参考线和建议完整保存在现有 `metrics_json` 中。

### 9.8 迁移数据

v1→v2 迁移：

- 现有 Run 的 `evaluation_phase = UNSPECIFIED`；
- `SUCCESS` 且候选人数大于0 → `HAS_CANDIDATES`；
- `NO_CANDIDATE` → `NO_CANDIDATES`；
- `PARTIAL_DETAIL_FAILED` 且候选人数大于0 → `HAS_CANDIDATES`；
- `FAILED` → `EXECUTION_FAILED`；
- 现有 `fields_json` 中的非空字段可生成旧 Baseline 的
  `available_fields_json`，来源标记 `DERIVED_LEGACY`；
- 不为旧 Process 自动生成 v2 指标；
- 旧 Process 保持原 `rule_version`；
- 需要新口径时由用户重新处理生成 v2 Process。

## 10. Baseline Available Fields

### 10.1 数据归属

`baseline_available_fields` 属于 Baseline/Person，而不是候选人检索结果。

如果检索接口返回同名字段：

- Raw 和 Candidate 字段可以保存并展示；
- 不能直接用被测系统自己的返回值修改正式 Baseline 分母；
- 只有进入选定 Baseline 版本并经过确认后才参与正式指标。

这样避免被测系统用自己的字段声明决定自己的评估分母。

### 10.2 JSONL 导入

支持：

```json
{
  "person_id": "person-001",
  "display_name": "Example",
  "fields": {
    "profile_full_name": "Example",
    "profile_location": "Shanghai"
  },
  "baseline_available_fields": [
    "profile_full_name",
    "profile_location"
  ],
  "evidence": {}
}
```

校验：

- 必须是字符串数组；
- 自动去重并保持首次出现顺序；
- 空字符串非法；
- 未出现在当前字段配置中的键允许导入，但处理时显示未知字段警告；
- 显式空数组表示该人物完整度未就绪。

### 10.3 Excel 导入

“基准数据”Sheet 增加可选列：

```text
baseline_available_fields
```

支持：

- JSON 数组；
- 英文逗号分隔字段键。

JSON 数组优先；无法解析时整批预览报错，不静默丢弃。

### 10.4 人工维护

Baseline 页面增加人物字段可用性查看和编辑入口：

- 显示字段键、展示名和基准值；
- 勾选/取消 `baseline_available`；
- 保存时更新当前 Baseline 人物；
- 来源标记为 `MANUAL`；
- 已关联报告标记 `STALE`，不覆盖旧文件。

为了保持 MVP 简单，不做多人审批和修改历史版本树。

## 11. Query 结果状态

### 11.1 状态映射

新增纯函数：

```text
normalize_result_status(query_status, candidate_count_listed)
```

映射：

| 采集状态 | 候选人数 | result_status |
| --- | ---: | --- |
| `SUCCESS` | > 0 | `HAS_CANDIDATES` |
| `PARTIAL_DETAIL_FAILED` | > 0 | `HAS_CANDIDATES` |
| `NO_CANDIDATE` | 0 | `NO_CANDIDATES` |
| `FAILED` | 任意 | `EXECUTION_FAILED` |

非法组合记录警告，例如 `SUCCESS + 0`，并按候选人数优先规范化。

### 11.2 执行与历史导入

- 执行完成时写入 `run_queries.result_status`；
- results.jsonl 增加 `result_status`；
- 历史 JSONL 有值时校验并使用；
- 没有值时按旧 `query_status` 和候选人数推导；
- Excel 导入同样推导；
- Pending/Running 阶段保持 `NULL`。

## 12. Process v2

### 12.1 规则版本

新增：

```text
FIELD_PROCESSING_RULE_VERSION = field-processing-v2
```

旧 Process 继续保留：

```text
field-processing-v1
```

### 12.2 处理顺序

`process_run()` 调整为：

1. 校验 Run、字段配置和 Baseline；
2. 插入 `process_runs`；
3. 按 Query 处理 Query 公共字段；
4. 写入 `processed_queries`；
5. 按 Candidate 处理业务字段；
6. 写入 `processed_candidates`；
7. 生成候选人建议复核数据；
8. 汇总真正错误数；
9. Process 标记 `COMPLETED`；
10. 任一数据库事务失败时标记 `FAILED`。

Query 字段失败不能阻止 Candidate 字段处理；Candidate 单字段失败也不能阻止其他字段。

### 12.3 不可变性

- 每次重新处理创建新 `process_id`；
- 不更新旧 `processed_queries`；
- 不更新旧 `processed_candidates`；
- Process 保存完整 `schema_version`、`baseline_version` 和 `rule_version`；
- 报告仍保存完整 ReportModel 快照。

## 13. 指标规则 v2

### 13.1 指标模型版本

ReportModel 和 Process Metrics 增加：

```text
metrics_rule_version = metrics-v2
report_model_version = report-model-v2
```

`calculate_process_metrics()` 按 `process_runs.rule_version` 分派：

- v1 Process：继续使用旧计算路径；
- v2 Process：使用新计算路径；
- 未知版本拒绝计算，避免静默套用错误公式。

### 13.2 结果状态指标

输出：

```json
{
  "result_status_metrics": {
    "total_formal_queries": 100,
    "has_candidates_count": 80,
    "no_candidates_count": 15,
    "execution_failed_count": 5,
    "has_result_rate": 0.8421,
    "no_result_rate": 0.1579,
    "execution_failed_rate": 0.05
  }
}
```

公式：

```text
has_result_rate =
HAS_CANDIDATES / (HAS_CANDIDATES + NO_CANDIDATES)
```

```text
no_result_rate =
NO_CANDIDATES / (HAS_CANDIDATES + NO_CANDIDATES)
```

```text
execution_failed_rate =
EXECUTION_FAILED / total_formal_queries
```

分母为0时值为 `null`，不能显示0%。

### 13.3 检索成功率

```text
retrieval_success =
命中 Baseline 的 Query 数 / 正式 Query 总数
```

- `NO_CANDIDATES` 记0；
- `EXECUTION_FAILED` 记0；
- `HAS_CANDIDATES` 由最终人工复核结果判断；
- 缺少 Baseline 或复核时保留 preview，但正式 value 为 `null`。

### 13.4 命中完整度

单人：

```text
matched_completeness =
baseline_available_fields 中各字段完整度得分之和
/ baseline_available_fields 字段数
```

规则：

- 不再使用 `CONTENT_FIELD_COUNT = 22`；
- 不在可用字段列表中的字段不进入分子和分母；
- 单值字段正确找回为1，否则0；
- 多值字段使用正确找回项数/基准项数；
- 可用字段列表为空时为 `NOT_READY`；
- Query 有多个 HIT Candidate 时使用人工确认的命中 Candidate；
- 未完成字段分数时正式值为 `null`。

### 13.5 命中准确率

```text
matched_accuracy =
正确返回且已判定的字段数
/ 返回非空且可判定的 baseline_available_fields 字段数
```

- 未返回字段不进入准确率分母；
- 未返回字段仍影响完整度；
- 返回错误字段进入准确率分母并得0；
- 不在可用字段列表中的额外字段不进入命中准确率。

### 13.6 非命中完整度

保持“观察性指标”，但分母采用当前字段配置中：

- `scoring_role` 包含 completeness；
- enabled；
- 非系统标识字段。

报告必须注明它不是正确性指标，不单独决定上线。

### 13.7 成本与耗时

每个公共字段独立聚合，不再使用“所有字段全部完整才统计”的逻辑。

统一输出：

```json
{
  "llm_cost": {
    "status": "PARTIAL",
    "value_count": 90,
    "missing_count": 10,
    "total": 12.5,
    "average": 0.1389,
    "minimum": 0.05,
    "maximum": 0.4
  }
}
```

字段：

- `llm_cost`；
- `third_party_cost`；
- `total_cost`；
- `search_duration_ms`。

状态：

- 所有值缺失：`NOT_CONNECTED`；
- 部分缺失：`PARTIAL`；
- 全部有效：`COMPLETE`。

成本允许0；缺失必须为 `null`。负数和非数字记录类型错误，不参与汇总。

### 13.8 PDL

输出：

```json
{
  "pdl": {
    "true_count": 30,
    "false_count": 60,
    "unknown_count": 10,
    "known_count": 90,
    "call_rate": 0.3333
  }
}
```

`call_rate` 分母为 `true + false`。

### 13.9 Candidate Confidence

保留原始字符串，不假设只有 HIGH/MEDIUM/LOW。

输出：

```json
{
  "confidence": {
    "overall": {
      "HIGH": 20,
      "MEDIUM": 40,
      "LOW": 30,
      "UNKNOWN": 10
    },
    "matched": {},
    "nonmatched": {}
  }
}
```

规则：

- `null`、空字符串进入 `UNKNOWN`；
- 未知新枚举按原值独立统计；
- 大小写仅在后端确认枚举大小写无语义后统一；
- 不根据 Confidence 自动修改人工 HIT/NOT_HIT。

### 13.10 分组

所有核心指标至少按以下组合输出：

```text
evaluation_phase + system_version + query_stage
```

单 Process 的 `system_version` 和 `evaluation_phase` 固定，但模型仍保留完整维度，便于
阶段报告和平台后续集成。

## 14. 对比设计

### 14.1 同条件判定

正式同条件需要：

- 相同 `person_id`；
- 相同 `query_stage`；
- Dataset 输入签名相同；
- Baseline 版本相同；
- 字段配置兼容；
- 指标规则版本相同。

输入签名继续使用稳定 JSON 计算，至少包含：

- `match_strategy`；
- `clues`；
- `additional_details`。

### 14.2 对比结果拆分

`compare_processes()` 返回：

```json
{
  "same_condition": {
    "pairs": [],
    "coverage": {},
    "category_counts": {}
  },
  "new_clue": {
    "queries": [],
    "query_stage_metrics": {}
  },
  "not_comparable": {
    "queries": [],
    "reasons": []
  }
}
```

### 14.3 同条件四象限

- 持续命中；
- 新增命中；
- 退化未命中；
- 持续未命中。

每个人增加：

- 完整度前后值和变化；
- 准确率前后值和变化；
- Confidence 前后值；
- Query 成本前后值；
- Query 耗时前后值；
- PDL 前后状态。

### 14.4 新增线索

Candidate 阶段出现、Baseline 阶段没有相同条件的 `query_stage`：

- 进入 `new_clue`；
- 可以与 Candidate 同版本 FULL_NAME 横向展示；
- 不计算虚构的“优化前变化”；
- 报告文字使用“新增线索结果”，不使用“系统提升”。

### 14.5 配对覆盖

报告显示：

- Baseline 可配对 Query 数；
- Candidate 可配对 Query 数；
- 成功配对数；
- Candidate 新增条件数；
- Baseline 有但 Candidate 缺少的回归 Query 数；
- 输入签名不一致数。

存在缺失回归 Query 时报告给出警告，不静默忽略。

## 15. 参考线与建议

### 15.1 存储

在 `evaluations.thresholds_json` 保存，例如：

```json
{
  "FULL_NAME": {
    "min_retrieval_success": 0.7,
    "min_matched_completeness": 0.5,
    "min_matched_accuracy": 0.9,
    "max_average_total_cost": null,
    "max_average_search_duration_ms": null
  },
  "FULL_NAME_SOCIAL": {
    "min_retrieval_success": 0.85,
    "min_matched_completeness": 0.6,
    "min_matched_accuracy": 0.9
  }
}
```

所有阈值可空，取值范围在保存时校验。

### 15.2 页面

Evaluation 创建页允许留空；Evaluation 详情页提供编辑入口。

MVP 使用结构化表单维护常用阈值，不直接要求用户编辑整段 JSON。数据库仍保存 JSON，
避免为每个新阈值迁移表结构。

### 15.3 判断

单项状态：

- `PASS`；
- `FAIL`；
- `NOT_CONFIGURED`；
- `NOT_READY`。

总体建议：

| 条件 | 建议 |
| --- | --- |
| 所有已配置核心指标有值且全部 PASS | 建议上线 |
| 任一已配置核心指标 FAIL | 继续优化 |
| 未配置参考线或关键指标缺失 | 暂不能判断 |

报告必须显示判断依据，不能只显示结论。

阈值快照写入 ReportModel，后续修改 Evaluation 阈值不改变旧报告。

## 16. ReportModel v2

### 16.1 模型结构

```json
{
  "metadata": {
    "report_model_version": "report-model-v2",
    "metrics_rule_version": "metrics-v2",
    "evaluation_phase": "PHASE_2_POST_OPTIMIZATION"
  },
  "summary": {},
  "result_status_metrics": {},
  "quality_metrics": {},
  "cost_metrics": {},
  "pdl_metrics": {},
  "confidence_metrics": {},
  "grouped_metrics": {},
  "comparison": {
    "same_condition": {},
    "new_clue": {},
    "not_comparable": {}
  },
  "module_metrics": {},
  "field_metrics": {},
  "threshold_assessment": {},
  "case_groups": {},
  "warnings": []
}
```

### 16.2 单 Run 报告

无 `baseline_process_id` 时也生成：

- 元数据；
- 结果状态；
- 候选人数；
- 成本/耗时/PDL；
- Confidence；
- 模块/字段返回率；
- 失败、空值和字段错误；
- Query/Candidate 明细。

需要 Baseline/复核的指标显示：

```text
NOT_READY: 未关联 Baseline
```

不阻止报告保存和导出。

### 16.3 对比报告

有 `baseline_process_id` 时增加：

- 同条件对比；
- 新增线索；
- 配对覆盖；
- 四象限；
- 人物级质量、成本、耗时和置信度变化；
- 参考线与建议。

### 16.4 案例排序

- 改善最明显：优先按检索从0→1，再按完整度变化、准确率变化排序；
- 退化：所有退化必须列出，不只显示前几名；
- 持续未命中：按候选人数、最高 Confidence、非命中完整度排序；
- 默认展示前3～5个改善案例，支持查看全部明细。

### 16.5 模块和字段

模块/字段统计拆分：

- 全部候选人；
- 命中候选人；
- 非命中候选人。

字段表展示：

- 返回数；
- 空值数；
- 返回率；
- 命中完整度；
- 命中准确率；
- 非命中非空率；
- Baseline 对比变化。

## 17. Web 页面设计

### 17.1 Evaluation

创建/详情增加：

- 参考线配置；
- 参考线是否完整；
- 各 Query Stage 的阈值摘要。

### 17.2 Run 创建和历史导入

增加必选/明确字段：

```text
evaluation_phase
```

历史 Run 可选择 `UNSPECIFIED`，新执行默认不允许隐式猜测阶段。

### 17.3 Run 详情

增加：

- Evaluation Phase；
- HAS/NO/FAILED 计数；
- 第三方成本、耗时；
- 查询状态筛选使用规范化 `result_status`；
- 原 `status` 仍展示部分 Detail 失败等明细。

### 17.4 Query 详情

增加：

- `result_status`；
- 五个 Task 公共字段；
- 每个字段的数据状态：有效/缺失/错误；
- 对应 Raw 阶段入口。

### 17.5 字段配置

配置说明增加：

- `value_scope`；
- `missing_policy`；
- Query 公共字段示例；
- 可选路径缺失与结构错误的区别。

配置列表显示 Query/Candidate 字段数量。

### 17.6 Baseline

增加：

- `baseline_available_fields` 数量；
- 来源；
- 查看和人工编辑；
- 未知字段警告。

### 17.7 Process

增加：

- Query 公共字段处理摘要；
- 空值数和错误数分开展示；
- 新结果状态指标；
- 成本、耗时、PDL、Confidence；
- 指标规则版本；
- 按阶段和 Query Stage 过滤。

### 17.8 Candidate

增加：

- Candidate Confidence；
- 原始 Summary Confidence Level 路径；
- Confidence 仅供展示，不作为人工结论；
- 可选字段缺失显示 EMPTY，不显示 ERROR。

### 17.9 Report

按照 ReportModel v2 渲染：

1. 评估信息；
2. 核心结论和建议；
3. 结果状态；
4. 质量指标；
5. 同条件/新增线索；
6. 四象限和人物案例；
7. 成本、耗时、PDL；
8. Confidence；
9. 模块/字段；
10. 风险、缺失和失败明细。

## 18. Excel 与静态 HTML

### 18.1 静态 HTML

- 只读取 ReportModel 快照；
- 不调用数据库重新计算；
- 与 Web 报告使用同一个 `_report_content.html`；
- 缺失值展示为“未接入/无数据/未就绪”，不显示0。

### 18.2 Excel

现有 processed Excel 增加或调整 Sheet：

| Sheet | 内容 |
| --- | --- |
| `说明` | 阶段、版本、规则、缺失说明 |
| `核心指标` | 结果状态、质量指标、参考线和建议 |
| `Query明细` | result_status、成本、耗时、PDL |
| `候选结果` | Confidence、复核和结构化字段 |
| `同条件对比` | 人物级前后变化 |
| `新增线索` | 无上一阶段基线的条件 |
| `模块字段统计` | 命中/非命中拆分统计 |
| `失败记录` | 执行、Detail 和字段结构错误 |

空值保持空单元格，不写0、`False` 或字符串 `"null"`。

### 18.3 Docker

如果 Docker 环境仍未安装 Excel 构建依赖：

- HTML 报告必须可用；
- 页面明确显示 Excel 暂不可用原因；
- 不影响报告快照状态；
- 本次不改变现有 Docker 依赖策略，除非验收明确要求容器内 Excel。

## 19. API 兼容

现有 API 保持：

- `/api/field-schemas/<schema_version>`；
- `/api/processes/<process_id>/status`；
- `/api/processes/<process_id>/metrics`；
- `/api/raw/<raw_id>`。

响应做增量扩展：

- 字段配置返回 `value_scope`、`missing_policy`；
- Process Metrics 返回 v2 新模块；
- 旧客户端忽略新字段即可；
- 不删除或重命名现有字段。

可新增只读端点时，优先放入现有 `web_app.py`：

```text
GET /api/evaluations/<evaluation_id>/thresholds
```

如页面不需要独立请求，则不新增端点，直接使用现有表单提交。

## 20. 代码修改范围

遵循最小修改原则，优先修改现有文件。

| 文件 | 主要修改 |
| --- | --- |
| `analysis_store.py` | Schema v2、迁移、processed_queries |
| `search_tool.py` | result_status、Task 字段、结果小版本 |
| `analysis_service.py` | 配置v2、Raw处理源、空值、Baseline、指标、对比、报告 |
| `web_app.py` | 阶段、阈值、Baseline、Process、报告路由数据 |
| `result_to_excel.py` | 新 Query/Candidate/报告字段 |
| `result_to_excel_builder.mjs` | 新 Sheet/列、空值和格式 |
| `templates/evaluation_new.html` | 阈值输入 |
| `templates/evaluation_detail.html` | 阶段、阈值和 Run 展示 |
| `templates/run_detail.html` | 结果状态和公共字段 |
| `templates/query_detail.html` | Task 公共字段 |
| `templates/field_schemas.html` | scope/missing_policy 摘要 |
| `templates/field_schema_new.html` | 配置说明 |
| `templates/baselines.html` | available fields 查看/维护 |
| `templates/process_detail.html` | v2 指标和空值/错误 |
| `templates/candidate_detail.html` | Confidence |
| `templates/_report_content.html` | ReportModel v2 |
| `templates/report_detail.html` | 兼容 v1/v2 模型 |
| `templates/report_static.html` | 兼容 v1/v2 模型 |
| `static/app.css` | 仅补充必要布局 |
| `tests/test_analysis_store.py` | 数据库迁移 |
| `tests/test_search_tool.py` | 新字段/状态 |
| `tests/test_analysis_service.py` | 配置、处理、指标、对比、报告 |
| `tests/test_web_app.py` | Web 表单和展示 |
| `tests/test_result_to_excel.py` | Excel |
| `README.md` | 升级、字段配置和运行说明 |

除测试 Fixture 和用户已要求的文档外，不新建业务模块文件。

## 21. 测试设计

### 21.1 数据库

- 新数据库创建 v2；
- v1 数据库迁移到 v2；
- v1 数据、Raw、Process、Report 数量不变；
- 迁移重复执行幂等；
- 迁移中断回滚；
- 更高版本继续拒绝；
- 外键和索引有效。

### 21.2 字段配置

- v1 配置自动推断 scope/policy；
- v2 配置保存完整属性；
- 非法 scope/policy 拒绝发布；
- Query/Candidate 字段分别处理；
- 未知脚本语法继续拒绝。

### 21.3 可选路径

至少覆盖：

```json
{"items": []}
{"primary_image": null}
{}
{"items": "wrong-type"}
```

验证：

- 前三类按 `EMPTY` 得到正常空值；
- 错误类型仍进入错误；
- `ERROR` 策略仍能发现必需字段缺失；
- wildcard 空数组返回 `[]`。

### 21.4 Task 公共字段

Fixture 覆盖：

- 全部字段有值；
- 全部缺失；
- 单个字段缺失；
- 成本为0；
- 非法负数；
- PDL 为 true/false/null；
- 多次 GetTask，只有最后一次 SUCCEEDED 有值；
- 历史 Raw 路径不同但可通过配置读取。

### 21.5 Baseline

- JSONL 显式可用字段；
- Excel JSON 数组；
- Excel 逗号分隔；
- 重复字段去重；
- 空字段键报错；
- 未知字段警告；
- 旧 Baseline 派生 `DERIVED_LEGACY`；
- 空列表导致完整度 NOT_READY。

### 21.6 指标

构造可手算 Fixture：

- HAS/NO/FAILED 分布；
- 无失败和有失败；
- 每人不同可用字段数；
- 单值和多值完整度；
- 未返回字段影响完整度但不进入准确率；
- 成本部分缺失；
- PDL unknown；
- Confidence 新枚举；
- 分组公式；
- 分母为0。

测试必须断言分子、分母、value、preview 和状态，不只断言百分比。

### 21.7 对比

- 完全相同输入；
- 新增 Social 条件；
- Candidate 缺少回归 Query；
- 输入签名不一致；
- 四象限各至少1人；
- 完整度/准确率/成本/耗时/Confidence 变化；
- 不兼容规则版本拒绝正式比较。

### 21.8 报告

- 单 Run 无 Baseline；
- 单 Run 有 Baseline 未复核；
- 单 Run 完整复核；
- 正式同条件对比；
- 新增线索；
- 部分成本；
- 无阈值；
- 阈值 PASS/FAIL/NOT_READY；
- 旧 ReportModel v1 仍可打开；
- 静态 HTML 与 Web 核心数字一致。

### 21.9 Excel

- 新 Sheet 存在；
- 列名稳定；
- `null` 写空单元格；
- Query 和 Candidate 数量正确；
- 数字保持数字类型；
- URL 和长 JSON 仍按现有 Raw Sheet 策略处理；
- 旧导出用例不回归。

### 21.10 集成验收

端到端流程：

1. 启动 Schema v1 数据库并迁移；
2. 创建/选择 Evaluation；
3. 配置参考线；
4. 导入 Dataset；
5. 选择评估阶段启动 Run；
6. 验证 Raw；
7. 发布字段配置 v2；
8. 导入带 available fields 的 Baseline；
9. 生成 Process；
10. 复核；
11. 生成单次报告；
12. 再导入/执行另一版本；
13. 生成同条件对比；
14. 增加 Social 新线索并验证单独区域；
15. 导出 HTML/Excel；
16. 重启 Docker 后验证数据和报告仍存在。

## 22. 开发计划

### 阶段0：接口契约与基线冻结

#### 目标

冻结升级前数据库、自动化测试和接口样例。

#### 工作项

1. 备份当前测试 SQLite；
2. 记录 Schema v1 行数和报告文件；
3. 跑现有全量测试；
4. 准备 GetTask 新字段完整/部分缺失 Mock；
5. 确认实际字段路径、类型和单位；
6. 确认 `total_cost` 是否包含子成本；
7. 确认 Confidence 枚举；
8. 确认第一版参考线。

#### 涉及文件

- 只更新测试 Fixture、需求/设计记录；
- 不修改业务流程。

#### 完成标准

- 当前测试全绿；
- 新字段至少有一份真实或正式 Mock 响应；
- 未确认项有明确占位和负责人。

### 阶段1：数据库 Schema v2

#### 目标

安全支持新字段、阶段、Baseline 可用字段和 Query Process 快照。

#### 工作项

1. 实现 v1→v2 事务迁移；
2. 增加各表字段；
3. 创建 `processed_queries`；
4. 增加索引；
5. 实现旧状态迁移；
6. 实现旧 Baseline 可用字段迁移；
7. 增加迁移测试。

#### 主要文件

- `analysis_store.py`
- `tests/test_analysis_store.py`

#### 完成标准

- 新旧数据库均可启动；
- 数据量、Raw 和报告文件不丢失；
- 迁移失败可回滚；
- 数据库测试通过。

### 阶段2：字段配置 v2 与空值修正

#### 目标

用现有字段配置处理 Query/Candidate，并解决虚假字段错误。

#### 工作项

1. 增加 `value_scope`、`missing_policy`；
2. 增加旧配置默认推断；
3. 调整路径提取器；
4. 增加 Query Raw 处理源；
5. 增加默认公共字段；
6. 增加 `candidate_confidence`；
7. 实现 `processed_queries` 写入；
8. Process 页面分开显示空值/错误；
9. 补充单元测试。

#### 主要文件

- `analysis_service.py`
- `templates/field_schemas.html`
- `templates/field_schema_new.html`
- `templates/process_detail.html`
- `tests/test_analysis_service.py`
- `tests/test_web_app.py`

#### 完成标准

- 三个已知路径缺失均不报错；
- 真正类型错误仍能发现；
- Query 公共字段形成不可变 Process 快照；
- 历史 Raw 可用新配置重新处理。

### 阶段3：采集、导入与 Baseline

#### 目标

新执行和历史导入均能保存规范化状态与新增字段。

#### 工作项

1. results.jsonl 增加字段和结果状态；
2. 执行持久化写入新列；
3. JSONL/Excel 历史导入兼容新旧格式；
4. Baseline 导入支持 available fields；
5. Baseline Web 支持查看和维护；
6. 增加 `evaluation_phase` 表单和展示；
7. 补充采集、导入和 Web 测试。

#### 主要文件

- `search_tool.py`
- `analysis_service.py`
- `web_app.py`
- `templates/evaluation_detail.html`
- `templates/run_detail.html`
- `templates/query_detail.html`
- `templates/baselines.html`
- `tests/test_search_tool.py`
- `tests/test_analysis_service.py`
- `tests/test_web_app.py`

#### 完成标准

- 新执行和历史导入结果一致；
- 阶段不再依赖名称猜测；
- Baseline 可用字段可追溯；
- Query 详情能看到公共字段及缺失状态。

### 阶段4：指标规则 v2

#### 目标

完成结果、质量、成本、耗时、PDL 和置信度指标。

#### 工作项

1. 新旧规则版本分派；
2. 结果状态统计；
3. per-person 完整度；
4. 准确率口径；
5. 成本独立聚合；
6. 耗时统计；
7. PDL 统计；
8. Confidence 分布；
9. evaluation phase 分组；
10. 丰富人物级指标；
11. 编写可手算测试。

#### 主要文件

- `analysis_service.py`
- `templates/process_detail.html`
- `tests/test_analysis_service.py`

#### 完成标准

- 不再使用固定22分母；
- 各指标分子和分母可追溯；
- 部分成本仍可汇总；
- Process Metrics API 返回 v2 模型；
- 所有指标单元测试通过。

### 阶段5：对比、参考线与报告

#### 目标

完成同条件/新增线索拆分和 ReportModel v2。

#### 工作项

1. 扩展同条件配对；
2. 增加新线索和不可比数据；
3. 增加配对覆盖；
4. 实现 Evaluation 阈值维护；
5. 实现 PASS/FAIL/NOT_READY；
6. 构建 ReportModel v2；
7. 升级 Web/HTML；
8. 增加人物案例排序；
9. 保持 ReportModel v1 兼容。

#### 主要文件

- `analysis_service.py`
- `web_app.py`
- `templates/evaluation_new.html`
- `templates/evaluation_detail.html`
- `templates/_report_content.html`
- `templates/report_detail.html`
- `templates/report_static.html`
- `tests/test_analysis_service.py`
- `tests/test_web_app.py`

#### 完成标准

- 单 Run 报告可独立生成；
- 同条件和新增线索不混用；
- 阈值和建议有明确依据；
- 旧报告可打开；
- 静态 HTML 与 Web 一致。

### 阶段6：Excel、集成与文档

#### 目标

完成导出、回归、Docker 和交付说明。

#### 工作项

1. 更新 Excel 字段和 Sheet；
2. 校验空值、数字、URL；
3. 跑全量测试；
4. 执行完整端到端验收；
5. 验证数据库升级；
6. 验证 Docker 5002；
7. 更新 README；
8. 输出验收记录和已知限制。

#### 主要文件

- `result_to_excel.py`
- `result_to_excel_builder.mjs`
- `tests/test_result_to_excel.py`
- `README.md`
- 现有验收文档或用户明确要求的新验收文档

#### 完成标准

- 全量测试通过；
- HTML/Excel 内容一致；
- Docker 重启后数据保留；
- 需求验收项逐条有结果；
- 未确认接口字段明确显示未接入，不产生假数据。

## 23. 阶段依赖

```text
阶段0 契约/基线
  ↓
阶段1 数据库
  ↓
阶段2 配置/处理
  ↓
阶段3 采集/导入/Baseline
  ↓
阶段4 指标
  ↓
阶段5 报告
  ↓
阶段6 导出/验收
```

阶段2和阶段3可以在数据库结构完成后局部并行开发，但合并验收必须先完成
`processed_queries` 和 Raw 处理源。

## 24. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 新接口路径未确认 | 公共字段无法落值 | 先完成结构和空值，路径通过新配置接入 |
| total_cost 语义不清 | 成本重复计算 | 直接使用接口值，不自行相加 |
| Baseline 字段由被测系统返回 | 分母被系统自身影响 | 只将已确认 Baseline 版本用于正式指标 |
| 历史 Raw 不完整 | 无法重新提取新字段 | 显示未接入，不伪造数据 |
| v1 数据库无迁移机制 | 升级无法启动 | 先实现事务迁移和回滚测试 |
| 新规则改变旧 Process 数字 | 历史不可复现 | 按 rule_version 分派，旧报告只读快照 |
| 可选字段缺失被全部吞掉 | 真实结构错误不易发现 | 仅缺失/null为空，错误类型仍报错 |
| 新增线索被误认为版本提升 | 报告结论错误 | ReportModel 强制拆分两个区域 |
| Excel 容器依赖缺失 | Excel 导出不可用 | HTML 必须可用并明确提示 |

## 25. 回滚方案

### 25.1 代码回滚

- 保留支持 Schema v2 的数据库读取代码；
- 不允许代码回滚到只能读取 Schema v1 的版本后直接连接已升级数据库；
- 如需回滚功能，关闭新入口并继续只读旧数据。

### 25.2 数据回滚

- 迁移前保留 SQLite 文件备份；
- 迁移失败事务自动回滚；
- 不通过删除列恢复 v1；
- Raw、归档文件和报告目录不参与破坏性回滚。

### 25.3 配置回滚

- 字段配置不可变；
- 发布错误配置后重新激活上一版本或发布修正版；
- 已生成的错误 Process 可保留审计，不用于正式报告；
- 不覆盖旧 Report。

## 26. 开发前必须确认项

以下事项需要后端或测试负责人确认；不确认时可以开发框架，但对应字段只能保持空值：

1. `llm_cost` 正式路径和单位；
2. `third_party_cost` 正式路径和单位；
3. `total_cost` 正式路径、单位及包含关系；
4. `pdl_called` 正式路径和布尔语义；
5. `search_duration_ms` 正式路径，是否包含排队时间；
6. `baseline_available_fields` 的来源接口和数据类型；
7. Summary Confidence Level 完整枚举；
8. FULL_NAME/FULL_NAME_SOCIAL 正式参考线；
9. 可接受平均成本和平均/最长检索耗时。

## 27. 最终验收清单

- [ ] SQLite v1→v2 无数据丢失；
- [ ] 新字段配置支持 Query/Candidate scope；
- [ ] 可选路径缺失不报错；
- [ ] 真正结构错误仍可定位；
- [ ] Candidate Confidence 正确映射；
- [ ] Baseline Available Fields 可导入/维护；
- [ ] 完整度不再固定除以22；
- [ ] HAS/NO/FAILED 指标正确；
- [ ] 成本、耗时、PDL 支持部分数据；
- [ ] Evaluation Phase 可保存和展示；
- [ ] 单次报告无需对比 Run；
- [ ] 同条件和新增线索分开展示；
- [ ] 阈值、达标状态和建议可解释；
- [ ] Web、HTML、Excel 核心数字一致；
- [ ] 旧 Process 和旧报告仍可访问；
- [ ] Docker 5002 启动和重启验证通过；
- [ ] 全量自动化测试通过；
- [ ] README 和验收记录完成。
