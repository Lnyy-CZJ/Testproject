# searchTool v1.3 MVP 数据处理优化开发设计与开发计划

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | searchTool v1.3 MVP 数据处理优化开发设计与开发计划 |
| 文档版本 | v1.0 |
| 编写日期 | 2026-07-28 |
| 需求依据 | `docs/searchTool_v1.3_MVP_数据处理优化PRD.md` |
| 当前数据库 | SQLite Schema v3 |
| 目标数据库 | SQLite Schema v4 |
| 当前处理规则 | `field-processing-v2` |
| 目标处理规则 | `field-processing-v3` |
| 当前指标规则 | `metrics-v2` |
| 目标指标规则 | `metrics-v3` |
| 当前报告模型 | `report-model-v2` |
| 目标报告模型 | `report-model-v3` |
| 核心原则 | Raw 不变、旧快照不变、历史 Run 重处理不调用外部接口 |

## 2. 开发目标

### 2.1 任务目标

在不改变现有顺序检索主流程的前提下完成：

1. 已有 Run Query 的 `person_id` 修正；
2. Query 与 Baseline Person 的批量匹配建议；
3. 关联修改审计及可选 Dataset 同步；
4. 基于已有 Raw/SQLite 的无成本重新处理；
5. 将“候选人复核”重构为 Query 级候选人身份归类；
6. 将字段是否为空与身份归类解耦；
7. 增加 Baseline/Candidate 字段对比矩阵；
8. 校验 Baseline 可用字段与 FieldSchema 评分字段交集；
9. 修正空模块、复杂空对象和状态字段口径；
10. 分离 Query 与 Candidate 字段统计分母；
11. 升级指标未就绪原因与报告修复入口；
12. 保证旧 Run、旧 Process、旧报告可继续访问。

### 2.2 成功标准

- 修改历史 Query `person_id` 时外部接口请求次数为0；
- 原始 JSONL、Raw Record、Candidate 和旧 ProcessResult 不被覆盖；
- 每次人物关联修改均可追溯；
- 修正关联后可以生成新 Process；
- 旧 Process 和旧报告仍按原规则展示；
- `PENDING_REVIEW` 不再被误解为字段需要人工补齐；
- 未归类候选人仍展示全部候选人字段返回率；
- 字段矩阵可以同时看到 Baseline 和 Candidate 两侧配置；
- `status=empty` 的 Insights/Photos/Social 不计为模块有数据；
- Task 字段使用 Query 数作为分母；
- Candidate 字段使用详情成功候选人数作为分母；
- 报告明确展示 `NOT_READY`、`NOT_APPLICABLE`、`NOT_CONNECTED` 和具体原因；
- 全量自动化测试、数据库迁移测试和真实数据验收通过。

### 2.3 交付物

- SQLite Schema v4 迁移；
- 历史 Run 人物关联管理；
- 人物关联审计；
- 无外部请求重新处理；
- Query 级候选人身份归类；
- 字段对比矩阵；
- FieldSchema 评分配置预检；
- `field-processing-v3`；
- `metrics-v3`；
- `report-model-v3`；
- Web、静态 HTML、Excel 更新；
- 自动化测试与验收记录；
- README 和使用说明更新。

## 3. 实施边界

### 3.1 本次实现

- 本地/测试环境单用户；
- `FULL_NAME`、`FULL_NAME_SOCIAL`；
- EXECUTION 和 IMPORT 两类历史 Run；
- Run Query 人物关联修正；
- Dataset Query 可选同步；
- Baseline Version 内人物选择；
- 已有数据重新处理；
- 候选人身份归类；
- 字段矩阵和版本化 FieldSchema；
- 指标、报告和导出升级。

### 3.2 本次不实现

- 重新请求收费检索接口；
- 自动修改原始 JSONL；
- 自动修改旧 Process/Report 快照；
- 基于姓名自动确认 HIT；
- 多用户审批；
- 通用表达式或脚本执行；
- 大模型字段准确率判断；
- 外部网页事实核验；
- 照片身份识别算法；
- 对线上业务数据做自动回写。

## 4. 现有架构评估

### 4.1 当前可复用流程

```text
Dataset
  → Run / run_queries
  → 顺序接口采集
  → candidates + raw_records
  → process_run()
  → processed_queries + processed_candidates
  → reviews
  → calculate_process_metrics()
  → ReportModel
  → Web / HTML / Excel
```

本次不修改：

- `search_tool.py` 的接口顺序；
- CreateIntentTask/GetTask/ListTaskCandidates/GetTaskCandidateDetail 调用；
- Raw 保存策略；
- Process 不可变策略；
- Report 快照不可变策略。

### 4.2 当前问题对应代码边界

| 问题 | 当前责任位置 | 优化方向 |
| --- | --- | --- |
| Query person_id 为空 | `dataset_queries`、`run_queries` | 增加安全修正和审计 |
| Baseline 无法关联 | `process_run()` | 使用修正后的 `run_queries.person_id` |
| 全部候选人待复核 | `reviews`、`save_review()` | Query 级身份归类 |
| 字段评分角色不完整 | `field_schemas.definitions_json` | 字段矩阵和预检 |
| 空对象判有值 | `_is_empty_value()`、字段处理 | 模块语义判空 |
| Task 分母错误 | `_process_field_report_metrics()` | 按 value_scope 分流 |
| 报告统一“不适用” | Metrics/ReportModel/模板 | 结构化状态与原因 |

### 4.3 复用与新增原则

1. 继续使用 `run_queries.person_id` 作为 Run 内有效人物关联；
2. 继续使用 `dataset_queries.person_id` 作为未来 Run 的默认关联；
3. 不创建第二套字段定义表；
4. 字段矩阵只聚合 FieldSchema、Baseline 和 Process 数据；
5. 继续使用 `reviews` 保存候选人最终身份状态；
6. 新增最小审计表记录人物关联历史；
7. 新 Process 读取修正后的关联，旧 Process 不回写。

## 5. 总体设计

### 5.1 优化后流程

```text
已有 Run
  ↓
检查 Query.person_id
  ├─ 已关联 → 继续
  └─ 未关联/错误
       ↓
    选择 Baseline Version
       ↓
    生成名称匹配建议
       ↓
    人工确认 Person
       ↓
    更新 run_queries.person_id
    写入关联审计
    标记关联报告 STALE
       ↓
使用已有数据重新处理
  ├─ 不调用任何外部接口
  ├─ 读取 candidates/raw_records
  ├─ 读取新 person_id
  └─ 创建新 ProcessResult
       ↓
候选人身份归类
       ↓
metrics-v3
       ↓
report-model-v3
```

### 5.2 数据流

```text
Raw/Run/Candidate（不可变事实）
             │
             ├── run_queries.person_id（可修正元数据）
             │
             ├── Baseline Version
             │
             └── FieldSchema Version
                         ↓
                ProcessResult（新快照）
                         ↓
                 Identity Classification
                         ↓
                    Metrics v3
                         ↓
                  ReportModel v3
```

### 5.3 版本策略

| 对象 | 策略 |
| --- | --- |
| Raw | 永不覆盖 |
| Run/Candidate | 不因重新处理重复采集 |
| Query person_id | 允许修正，记录审计 |
| FieldSchema | 发布新版本，不原地修改 |
| ProcessResult | 每次重处理创建新 ID |
| Review | 绑定 Process，不跨 Process 静默复用 |
| Metrics | 按 `metrics_rule_version` 计算 |
| Report | 保存完整快照，不打开时重算 |

## 6. SQLite Schema v4

### 6.1 版本升级

```python
DB_SCHEMA_VERSION = 4
```

增加：

```text
v1 → v2 → v3 → v4
```

迁移必须：

- 事务执行；
- 幂等；
- 不删除任何现有列；
- 不重写旧 Process/Report JSON；
- 迁移失败时保留 v3 数据库；
- Docker 启动和本地启动使用同一迁移逻辑。

### 6.2 run_queries 新增字段

```sql
ALTER TABLE run_queries
ADD COLUMN person_id_source TEXT NOT NULL DEFAULT 'UNSPECIFIED';
```

枚举：

| 值 | 含义 |
| --- | --- |
| `UNSPECIFIED` | 没有关联来源 |
| `DATASET` | 创建 Run 时继承 Dataset |
| `IMPORT_METADATA` | 历史结果元数据补齐 |
| `MANUAL_RUN` | 在已有 Run 中人工修改 |

迁移规则：

- `person_id IS NULL/''` → `UNSPECIFIED`；
- `person_id` 有值 → `DATASET`；
- 不推断历史人工来源。

### 6.3 dataset_queries 新增字段

```sql
ALTER TABLE dataset_queries
ADD COLUMN person_id_source TEXT NOT NULL DEFAULT 'UNSPECIFIED';
```

枚举：

| 值 | 含义 |
| --- | --- |
| `UNSPECIFIED` | 未提供 |
| `INPUT` | Dataset 源文件提供 |
| `IMPORT_METADATA` | 元数据文件提供 |
| `MANUAL_DATASET` | 人工同步 |

### 6.4 人物关联审计表

```sql
CREATE TABLE run_query_person_history (
    history_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    old_person_id TEXT,
    new_person_id TEXT,
    change_source TEXT NOT NULL,
    sync_dataset INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL,
    FOREIGN KEY (run_id, query_id)
        REFERENCES run_queries(run_id, query_id) ON DELETE CASCADE,
    FOREIGN KEY (baseline_version)
        REFERENCES baseline_sets(baseline_version)
);
```

`change_source` 首版支持：

- `MANUAL_SINGLE`；
- `MANUAL_BULK`；
- `CLEAR_LINK`；
- `DATASET_SYNC`。

索引：

```sql
CREATE INDEX idx_person_history_run_query
ON run_query_person_history(run_id, query_id, changed_at);
```

### 6.5 reviews 新增字段

```sql
ALTER TABLE reviews
ADD COLUMN classification_source TEXT NOT NULL DEFAULT 'SUGGESTED';

ALTER TABLE reviews
ADD COLUMN is_primary_hit INTEGER NOT NULL DEFAULT 0;
```

`classification_source`：

| 值 | 含义 |
| --- | --- |
| `SUGGESTED` | Process 初始化建议，尚未最终确认 |
| `MANUAL` | 人工最终归类 |
| `RULE` | 未来版本化自动规则最终归类 |

兼容迁移：

- `reviewed_at IS NULL` → `SUGGESTED`；
- `reviewed_at IS NOT NULL` → `MANUAL`；
- 已复核 HIT 中，同一 Query 排名最小者迁移为 `is_primary_hit=1`；
- 如果历史同一 Query 存在多个最终 HIT，只选择 rank 最小者为主要命中，并记录迁移告警。

首版不创建跨表唯一索引，由 Service 事务校验同一
`process_id + query_id` 最多一个最终主要 HIT。

### 6.6 Schema v4 迁移测试

必须覆盖：

- 空数据库直接创建 v4；
- v1→v4；
- v2→v4；
- v3→v4；
- 重复启动幂等；
- 有历史 Review 的迁移；
- 有多个历史 HIT 的兼容；
- 外键开启状态下迁移成功；
- 迁移失败事务回滚。

## 7. 历史 Run 人物关联服务设计

### 7.1 服务方法

在 `AnalysisService` 增加：

```python
def get_run_person_link_context(
    run_id: str,
    baseline_version: str,
) -> dict[str, Any]:
    ...

def update_run_query_person_links(
    run_id: str,
    baseline_version: str,
    changes: list[dict[str, Any]],
    *,
    sync_dataset: bool = False,
    note: str = "",
) -> dict[str, Any]:
    ...
```

### 7.2 关联上下文

`get_run_person_link_context()` 一次性返回：

```json
{
  "run": {},
  "baseline": {},
  "summary": {
    "query_count": 10,
    "linked_count": 0,
    "unlinked_count": 10,
    "invalid_count": 0,
    "unique_suggestion_count": 10
  },
  "queries": [
    {
      "query_id": "case-007",
      "query_stage": "FULL_NAME",
      "query_name": "Stephanie McMahon",
      "current_person_id": null,
      "current_source": "UNSPECIFIED",
      "current_baseline_exists": false,
      "suggestions": [
        {
          "person_id": "diffbot-ex4k_q8zrpiapv8cjifwf-a",
          "display_name": "Stephanie McMahon",
          "match_reason": "NORMALIZED_NAME_EXACT"
        }
      ]
    }
  ]
}
```

### 7.3 名称提取

Query 姓名只从以下位置读取：

1. Dataset 的 `FULL_NAME` clue；
2. Dataset 不存在时，从已归档输入元数据读取；
3. 两者均不存在时显示“无法生成建议”。

不得从候选人第一名反推 Query 目标姓名。

### 7.4 名称规范化

首版只做轻量规范化：

- Unicode 文本转换为字符串；
- 去除首尾空格；
- 连续空白合并；
- `casefold()`；
- 不自动删除中间名；
- 不做别名推断；
- 不做模糊距离自动保存。

建议类型：

| 类型 | 行为 |
| --- | --- |
| 唯一精确名称匹配 | 可批量勾选，仍需保存确认 |
| 多个精确名称匹配 | 必须手动选择 |
| 无精确匹配 | 必须手动选择或保持为空 |

### 7.5 更新校验

每条 change 输入：

```json
{
  "query_id": "case-007",
  "expected_person_id": null,
  "person_id": "diffbot-ex4k_q8zrpiapv8cjifwf-a"
}
```

校验：

- Run 存在；
- Run 状态不是 `PENDING/RUNNING`；
- Query 属于 Run；
- Baseline Version 存在；
- 新 `person_id` 属于该 Baseline Version；
- `expected_person_id` 与数据库当前值一致；
- 空字符串统一为 `null`；
- changes 中 query_id 不重复。

### 7.6 事务行为

同一事务中：

1. 更新 `run_queries.person_id`；
2. 更新 `person_id_source='MANUAL_RUN'`；
3. 写 `run_query_person_history`；
4. 可选更新 `dataset_queries.person_id`；
5. 可选更新 `dataset_queries.person_id_source='MANUAL_DATASET'`；
6. 将关联 Process 的 READY Report 标记为 `STALE`。

不执行：

- 删除 Process；
- 修改 Process 中已保存字段；
- 修改 Review；
- 修改 Raw；
- 修改 `results.jsonl`。

### 7.7 并发控制

使用 `expected_person_id` 做轻量乐观锁。

如果当前值已经变化，返回：

```text
Query case-007 的人物关联已被其他页面修改，请刷新后重试
```

本地单用户也保留该校验，防止旧浏览器页面覆盖。

## 8. 无外部请求重新处理

### 8.1 复用现有 process_run

现有 `process_run()` 已经只读取：

- `run_queries`；
- `candidates`；
- `raw_records`；
- FieldSchema；
- Baseline。

本次不建立第二套处理器。

增加显式封装：

```python
def reprocess_existing_run(
    run_id: str,
    schema_version: str,
    baseline_version: str,
) -> ProcessResult:
    ...
```

该方法先执行安全检查，再调用现有 Process 创建逻辑。

### 8.2 安全检查

- Run 状态必须为终态；
- 不允许 `PENDING/RUNNING`；
- Run 至少存在 processed source：Candidate 或 Query；
- FieldSchema 必须存在；
- Baseline Version 必须存在；
- 所有关联 `person_id` 必须在该 Baseline 中存在；
- 未关联 Query 可以继续处理，但必须返回明确告警；
- 不能调用 SearchToolClient 或执行 Run worker。

### 8.3 请求隔离

代码结构上确保：

```text
reprocess_existing_run()
  └─ process_run()
       ├─ SQLite read
       ├─ Raw read
       └─ SQLite write
```

禁止依赖：

- `execute_run()`；
- `_run_execution_worker()`；
- `SearchToolClient`；
- HTTP Client；
- CreateIntentTask。

测试中注入一个“调用即失败”的 HTTP Client，证明重处理不会请求接口。

### 8.4 新 Process 初始化

新 Process：

- 新 `process_id`；
- 使用修正后的 Query `person_id`；
- 使用选定 FieldSchema Version；
- 使用选定 Baseline Version；
- `rule_version=field-processing-v3`；
- 重新生成建议字段得分；
- 重新生成候选人身份建议；
- Review 初始化为建议状态，`reviewed_at=null`。

不自动复制旧 Process 的人工 Review，避免在人物关联或字段规则改变后误用旧结论。

后续可提供显式“复制兼容 Review”能力，但不在本次范围。

## 9. 候选人身份归类设计

### 9.1 数据职责

继续复用 `reviews`：

| 字段 | 用途 |
| --- | --- |
| judgement | HIT/NOT_HIT/SUSPECTED/PENDING_REVIEW |
| reason | SOCIAL_MATCH/SOCIAL_CONFLICT/NO_STRONG_FIELD/MANUAL |
| evidence | 自动证据或人工说明 |
| reviewed_at | 是否最终确认 |
| classification_source | SUGGESTED/MANUAL/RULE |
| is_primary_hit | Query 的主要命中候选人 |
| field_scores_json | 自动/人工字段评分 |

### 9.2 Query 级上下文

新增：

```python
def get_query_classification_context(
    process_id: str,
    query_id: str,
) -> dict[str, Any]:
    ...
```

返回：

- Query；
- 关联 Baseline Person；
- Baseline 核心字段；
- 全部候选人；
- Candidate Rank/Rank Score/Confidence；
- Candidate 核心字段；
- Social/Web URL；
- 自动建议及证据；
- 当前最终状态；
- 上一个/下一个 Query。

### 9.3 Query 级保存

新增：

```python
def save_query_classification(
    process_id: str,
    query_id: str,
    classifications: list[dict[str, Any]],
    *,
    primary_hit_candidate_pk: str | None,
    confirm_no_hit: bool,
    reviewer: str = "",
    review_note: str = "",
    expected_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    ...
```

规则：

- `primary_hit_candidate_pk` 和 `confirm_no_hit` 互斥；
- 主要命中必须属于当前 Query；
- 最多一个主要命中；
- `confirm_no_hit=true` 时不能存在最终 HIT；
- 未提交的候选人保持 PENDING，不默认改成 NOT_HIT；
- 页面提供“将其余成功候选人标记为 NOT_HIT”的显式勾选项；
- Candidate Detail 失败不能标记为正式 HIT；
- 保存后更新 `reviewed_at` 和 `classification_source=MANUAL`；
- 关联 READY Report 标记 `STALE`。

### 9.4 为什么不默认把其余候选人设为 NOT_HIT

姓名检索可能返回：

- 同一人物的多个数据源记录；
- 重复候选人；
- 同名人物；
- 部分证据不足的候选人。

因此首版必须由用户显式选择：

- 主要 HIT；
- NOT_HIT；
- SUSPECTED；
- 保持 PENDING；
- 确认无 HIT。

可以提供批量按钮，但保存前显示影响数量。

### 9.5 字段空值自动评分

处理器已经生成 `empty_fields_json`。

身份归类后：

- 完整度字段为空 → `completeness_score=0`；
- 简单字段非空 → `completeness_score=1`；
- 集合字段 → 按 Baseline 覆盖率；
- manual 字段非空但无法自动比较 → 完整度仍可计算，准确率待人工；
- 不需要用户确认字段“确实为空”。

### 9.6 页面改造

优先复用：

- `process_detail.html`：增加按 Query 的身份归类进度；
- `candidate_detail.html`：保留单候选人详细复核；
- 新增 Query 级工作区路由，模板可复用现有卡片和 JSON 宏。

页面文案：

```text
候选人身份归类
确认候选人是否为目标人物。字段是否为空由系统自动统计，
这里不会修改接口返回数据。
```

## 10. 字段对比矩阵设计

### 10.1 单一真源

矩阵不新增业务配置表。

数据来源：

```text
FieldSchema.definitions_json
  + baseline_people.fields_json
  + baseline_people.available_fields_json
  + processed_candidates.fields_json
  + processed_candidates.empty_fields_json
```

### 10.2 服务方法

```python
def build_field_comparison_matrix(
    schema_version: str,
    baseline_version: str,
    *,
    process_id: str | None = None,
    person_id: str | None = None,
) -> dict[str, Any]:
    ...
```

### 10.3 聚合结果

每个字段返回：

```json
{
  "field_key": "summary_display_name",
  "display_name": "Summary Display Name",
  "module": "Summary",
  "value_scope": "CANDIDATE",
  "enabled": true,
  "baseline_nonempty_count": 10,
  "baseline_available_count": 10,
  "baseline_person_count": 10,
  "candidate_nonempty_count": 45,
  "candidate_count": 45,
  "candidate_return_rate": 1.0,
  "completeness_enabled": false,
  "accuracy_enabled": false,
  "identity_enabled": false,
  "compare_mode": "normalized_text",
  "normalizer": "trim_text",
  "baseline_sample": "Stephanie McMahon",
  "candidate_sample": "Stephanie McMahon",
  "status": "BASELINE_ENABLED_NOT_SCORED",
  "issues": [
    "Baseline 已启用，但字段未参与完整度"
  ]
}
```

### 10.4 状态枚举

| 状态 | 含义 |
| --- | --- |
| `COMPARABLE` | 可提取、可做完整度和准确率 |
| `COMPLETENESS_ONLY` | 仅适合完整度 |
| `MANUAL_ACCURACY` | 准确率需要人工 |
| `BASELINE_ENABLED_NOT_EXTRACTED` | Baseline 打开但 Candidate 未提取 |
| `BASELINE_ENABLED_NOT_SCORED` | Baseline 打开但未参与评分 |
| `STRUCTURE_MISMATCH` | Baseline/Candidate 结构不一致 |
| `NO_BASELINE_DATA` | Baseline 没有有效值 |
| `NO_CANDIDATE_DATA` | 当前 Process 没有返回 |
| `DISPLAY_ONLY` | 只展示 |

### 10.5 性能要求

禁止按字段、按人物执行 N+1 SQL。

一次读取：

- FieldSchema 定义；
- Baseline Person JSON；
- Process Candidate JSON。

在内存中按 `field_key` 聚合。

首版规模：

- Baseline ≤ 1000 人；
- Candidate ≤ 10000；
- 字段 ≤ 500。

如未来超过规模再增加结构化统计表，本次不提前设计。

### 10.6 开关保存

#### Baseline 人物级开关

继续复用：

```text
POST /baselines/<baseline_version>/people/<person_id>/available-fields
```

#### FieldSchema 开关

FieldSchema 不允许原地修改。

矩阵页修改：

- `enabled`；
- `scoring_role` 中 completeness/accuracy/identity；
- `compare_mode`；
- `normalizer`。

保存动作：

```text
复制当前 Schema
  → 应用矩阵修改
  → 校验
  → 发布新 Schema Version
```

页面必须显示：

```text
将发布新字段配置版本，不会修改已有 Process。
```

### 10.7 配置预检

新增：

```python
def validate_process_field_alignment(
    schema_version: str,
    baseline_version: str,
) -> list[dict[str, Any]]:
    ...
```

严重级别：

| 等级 | 行为 |
| --- | --- |
| `ERROR` | 禁止生成正式指标，但允许保存 Schema 草稿/预览 |
| `WARNING` | 允许处理，报告显示风险 |
| `INFO` | 说明性提示 |

必须检测：

- Baseline 可用但 Candidate 未提取；
- Baseline 可用但未参与 completeness；
- accuracy 字段 compare_mode 不可执行；
- manual 字段没有人工评分入口；
- Baseline 字符串数组与 Candidate 对象数组不一致；
- QUERY/CANDIDATE 作用域错误；
- 所有 Baseline 均为空；
- 所有 Candidate 均为空。

## 11. FieldSchema v3 推荐调整

### 11.1 版本原则

不修改 `field-schema-default-v2`。

通过矩阵复制发布：

```text
field-schema-default-v3
```

是否激活由测试人员确认，不自动替换已有 active schema。

### 11.2 推荐评分配置

| 字段 | completeness | accuracy | identity | compare_mode |
| --- | --- | --- | --- | --- |
| insights_description | 是 | 是 | 否 | normalized_text |
| insights_links | 是 | 是 | 否 | url_set |
| insights_data | 是 | 否 | 否 | manual |
| photos_data | 是 | 否 | 否 | manual |
| profile_data | 是 | 否 | 否 | manual |
| profile_sections | 是 | 否/人工 | 否 | manual |
| social_display_handles | 是 | 是 | 否 | set |
| social_platforms | 是 | 是 | 否 | set |
| social_urls | 是 | 是 | 是 | url_set |
| summary_avatar_url | 是 | 否 | 否 | manual |
| summary_primary_image_url | 是 | 否 | 否 | manual |
| summary_social_links | 是 | 是 | 否 | url_set |
| summary_web_links | 是 | 是 | 否 | url_set |
| summary_display_name | 是 | 是 | 否 | normalized_text |
| summary_location | 是 | 是 | 否 | normalized_text |

### 11.3 URL 数组路径

Candidate 的对象数组改为提取 URL：

```text
ui_sections.summary.data.social_links[*].url
ui_sections.summary.data.web_links[*].url
```

Baseline 对应字段继续保存字符串数组。

处理层输出统一为：

```json
[
  "https://twitter.com/example"
]
```

### 11.4 复杂对象准确率

首版不对以下字段执行对象全量 exact：

- `profile_data`；
- `profile_sections`；
- `photos_data`；
- `insights_data`。

这些字段：

- 可以参与完整度；
- 可以展示 Baseline/Candidate 双栏；
- 准确率使用 manual 或暂不启用；
- 不用 JSON 全对象相等代表人物准确率。

## 12. field-processing-v3

### 12.1 规则版本

```python
FIELD_PROCESSING_RULE_VERSION = "field-processing-v3"
```

旧 Process：

- `field-processing-v1/v2` 保持旧 `empty_fields_json`；
- 不自动重算；
- 只有创建新 Process 才使用 v3。

### 12.2 基础空值函数

保留通用 `_is_empty_value()`，只处理标量/数组/对象基础规则：

- `None` → 空；
- `""`/纯空白字符串 → 空；
- `[]` → 空；
- `{}` → 空；
- 数值0默认有效；
- `zero_is_empty` 时0为空；
- `False` 默认有效；
- `false_is_empty` 时 False 为空。

### 12.3 模块语义判空

新增：

```python
def _apply_module_empty_rules(
    fields: dict[str, Any],
    empty_fields: dict[str, bool],
    definitions: list[dict[str, Any]],
) -> dict[str, bool]:
    ...
```

规则由代码维护，不引入用户脚本。

#### Insights

```text
insights_status == "empty"
  → insights_description/links/data 为空
```

`status=data` 时再检查 `items`。

#### Photos

```text
photos_status == "empty"
  → photos_data 为空
```

`identity_match_rate=0`：

- 当 status=empty 时为空模块；
- 当 status=data 时0是有效业务值。

#### Profile

```text
profile_status == "data"
且至少一个 section item value 非空
  → Profile 有数据
否则为空
```

#### Social

```text
social_status == "data"
且至少一个 profile URL/platform/handle 有效
  → Social 有数据
否则为空
```

#### Summary

Summary 没有统一模块空状态时，按 FieldSchema 中启用的核心字段判定。

### 12.4 模块状态字段

状态字段用于解释模块结果，不作为模块“有业务内容”的充分条件。

例如：

```text
insights_status="empty"
```

状态字段本身有值，但 Insights 模块业务数据仍为空。

### 12.5 处理结果扩展

不修改 `processed_candidates` 表结构。

继续保存：

- `fields_json`；
- `empty_fields_json`；
- `processing_errors_json`。

模块级状态从字段快照可复算，不额外复制 JSON。

## 13. metrics-v3

### 13.1 规则版本

```python
METRICS_RULE_VERSION = "metrics-v3"
```

`calculate_process_metrics()` 按 Process rule/version 路由：

```text
旧 Process → metrics-v1/v2
新 v3 Process → metrics-v3
```

### 13.2 指标返回结构

每个指标统一：

```json
{
  "value": null,
  "preview_value": null,
  "numerator": 0,
  "denominator": 0,
  "status": "NOT_READY",
  "reason_codes": [
    "BASELINE_NOT_LINKED",
    "IDENTITY_PENDING"
  ],
  "reasons": [
    "case-007 未关联 Baseline Person",
    "case-007 有3个候选人待身份归类"
  ]
}
```

### 13.3 状态枚举

```text
READY
NOT_READY
NOT_APPLICABLE
NOT_CONNECTED
PARTIAL
```

原因码：

| 原因码 | 含义 |
| --- | --- |
| `BASELINE_NOT_LINKED` | Query 未关联 Baseline |
| `BASELINE_PERSON_NOT_FOUND` | person_id 不在所选 Baseline |
| `IDENTITY_PENDING` | 候选人待身份归类 |
| `NO_HIT_CONFIRMED` | 已确认无命中 |
| `NO_NONMATCHED_CONFIRMED` | 没有已确认非命中/疑似 |
| `NO_EFFECTIVE_FIELDS` | 没有有效评分字段交集 |
| `MANUAL_SCORE_PENDING` | 人工准确率未完成 |
| `FIELD_NOT_CONNECTED` | 公共字段未接入 |
| `NO_DENOMINATOR` | 业务上没有分母 |

### 13.4 Query/Candidate 字段返回率

拆分方法：

```python
def _query_field_report_metrics(...):
    ...

def _candidate_field_report_metrics(...):
    ...
```

#### Query 字段

数据源：

```text
processed_queries
```

分母：

```text
有效 Query 数
```

#### Candidate 字段

数据源：

```text
processed_candidates
JOIN candidates
WHERE detail_status = 'SUCCESS'
```

分母：

```text
Candidate Detail 成功数
```

返回结果必须带：

```json
{
  "value_scope": "QUERY",
  "entity_count": 10,
  "returned_count": 10,
  "return_rate": 1.0
}
```

### 13.5 全部候选人返回率

不依赖 Review：

```text
字段非空的成功候选人数
÷
Candidate Detail 成功候选人数
```

该指标在全部候选人 `PENDING_REVIEW` 时仍为 READY。

### 13.6 模块有数据率

不再采用“模块任一字段有值”。

使用 `field-processing-v3` 的模块语义状态：

```text
模块有数据候选人数
÷
Candidate Detail 成功候选人数
```

结果同时展示：

- `data_count`；
- `empty_count`；
- `unknown_count`；
- `candidate_count`；
- `data_rate`。

### 13.7 身份归类分母

```text
reviewed_at 非空
且 classification_source in {MANUAL, RULE}
```

主要 HIT：

```text
judgement=HIT
且 is_primary_hit=1
```

非命中：

```text
judgement in {NOT_HIT, SUSPECTED}
```

建议状态不进入正式身份分母。

### 13.8 检索成功率

单 Query：

- 存在最终主要 HIT → 1；
- 已确认无 HIT → 0；
- 仍有 PENDING 且没有确认无 HIT → NOT_READY。

整体：

```text
确认存在主要 HIT 的 Query 数
÷
已完成身份归类的正式 Query 数
```

如果仍有未归类 Query：

- 可展示 preview；
- 正式 value 为 null；
- status=NOT_READY；
- 返回未归类 Query 列表。

### 13.9 命中完整度

有效字段：

```text
Person baseline_available_fields
∩ FieldSchema enabled
∩ value_scope=CANDIDATE
∩ scoring_role 包含 completeness
```

单人物：

```text
主要 HIT 的字段完整度得分总和
÷
有效字段数
```

没有有效字段：

```text
status=NOT_READY
reason_code=NO_EFFECTIVE_FIELDS
```

### 13.10 命中准确率

有效返回字段：

```text
有效准确率字段
且 Candidate 返回非空
且自动比较成功或人工评分完成
```

空字段：

- 不进入准确率分母；
- 已在完整度中计0。

manual 字段没有人工评分：

- 指标 `PARTIAL` 或 `NOT_READY`；
- 返回字段列表；
- 不静默按0。

### 13.11 非命中完整度

字段集合：

```text
FieldSchema enabled
∩ value_scope=CANDIDATE
∩ scoring_role 包含 completeness
```

不依赖目标人物 Baseline 可用字段。

单候选人：

```text
非空完整度字段数/字段得分总和
÷
Candidate 完整度字段数
```

只有 PENDING：

- 非命中完整度 `NOT_READY`；
- 全部候选人字段返回率仍 READY。

已确认无 HIT 且候选人均归类：

- 命中指标 `NOT_APPLICABLE/NO_HIT_CONFIRMED`；
- 非命中完整度正常计算。

### 13.12 Confidence

继续使用：

```text
ui_sections.summary.data.confidence_level
```

分别统计：

- 全部候选人；
- 主要 HIT；
- NOT_HIT；
- SUSPECTED；
- PENDING。

不把 HIGH 直接转为 HIT。

## 14. report-model-v3

### 14.1 版本

```python
REPORT_MODEL_VERSION = "report-model-v3"
```

旧报告继续读取 v1/v2 快照。

### 14.2 执行摘要

执行摘要分为：

#### 执行状态

- Query 总数；
- 有候选人；
- 无候选人；
- 执行失败；
- Candidate Detail 成功/失败。

#### 数据返回

- Candidate 字段总体返回率；
- Insights/Photos/Profile/Social/Summary 模块有数据率；
- 公共字段接入状态。

#### 身份结果

- 已归类 Query；
- 待归类 Query；
- 有主要 HIT；
- 已确认无 HIT。

#### 字段质量

- 命中完整度；
- 命中准确率；
- 非命中完整度；
- 配置冲突数量。

### 14.3 未就绪展示

禁止只输出：

```text
不适用
```

改为：

```text
待关联 Baseline（10条 Query）
待身份归类（45个候选人）
无有效完整度字段（14个字段未启用）
已确认无命中，本指标不适用
尚无已确认非命中候选人
接口字段未接入
```

### 14.4 修复入口

Web 报告根据 reason_code 渲染：

| reason_code | 入口 |
| --- | --- |
| BASELINE_NOT_LINKED | 管理 Query 人物关联 |
| IDENTITY_PENDING | 候选人身份归类 |
| NO_EFFECTIVE_FIELDS | 字段对比矩阵 |
| FIELD_NOT_CONNECTED | 字段配置/接口说明 |
| STALE | 使用最新 Process 生成新报告 |

静态 HTML 不提供可操作按钮，但展示具体原因和对象 ID。

### 14.5 案例

人物级案例增加：

- Query person_id；
- Baseline Person；
- 关联来源；
- 主要 HIT；
- 身份归类来源；
- 全部候选人字段返回摘要；
- 命中字段对比；
- 非命中字段返回摘要；
- 未就绪原因。

## 15. Web 设计

### 15.1 Run 详情页

增加人物关联摘要：

```text
Query 人物关联
已关联 0 / 10
无效关联 0
唯一建议 10
```

按钮：

- 管理人物关联；
- 使用已有数据重新处理。

当 Run 为 PENDING/RUNNING 时禁用关联修改。

### 15.2 人物关联管理

优先作为 Run 详情页独立工作区，避免在列表中塞入复杂表单。

功能：

- 选择 Baseline Version；
- 搜索 Query/人物；
- 筛选未关联/无效/多匹配；
- 展示唯一建议；
- 批量采用唯一建议；
- 单条修改；
- 清除关联；
- 可选同步 Dataset；
- 填写修改说明；
- 保存前确认变更数量。

### 15.3 Process 创建/重处理

表单增加：

- 人物关联覆盖率；
- 字段对比预检；
- ERROR/WARNING 数量；
- 明确提示“不会调用接口”；
- 确认生成新 Process。

### 15.4 Process 详情

增加：

- 身份归类进度；
- Query 级归类入口；
- 全部候选人字段返回率；
- Query/Candidate 分 scope 表格；
- 模块 data/empty/unknown；
- 字段配置冲突；
- 指标状态原因。

### 15.5 Query 身份归类工作区

布局：

```text
顶部：Query + Baseline 摘要 + 进度
左侧/主体：候选人列表
右侧/卡片：Baseline 对照与身份证据
底部：保存并进入下一 Query
```

候选人卡片：

- Rank、Rank Score、Confidence；
- 姓名、位置、Social、Web；
- Profile 摘要；
- 建议状态；
- HIT/NOT_HIT/SUSPECTED/PENDING 控件；
- 主要 HIT 开关。

### 15.6 FieldSchema 页面

增加字段矩阵入口。

矩阵支持：

- Module 筛选；
- 字段搜索；
- 状态筛选；
- Baseline/Candidate 样例；
- completeness/accuracy/identity 开关；
- compare_mode；
- 冲突说明；
- 复制并发布新版本。

### 15.7 Baseline 页面

现有单人基准工作台继续维护 `baseline_available_fields`。

增加：

- 版本级字段覆盖统计；
- 打开字段矩阵；
- 当前 Schema 对齐状态；
- 可用但未评分字段数量。

### 15.8 Report 页面

增加：

- 未就绪原因卡片；
- 修复入口；
- 全部候选人返回率；
- 身份归类进度；
- Query/Candidate scope；
- 模块真实 data rate；
- 配置冲突摘要。

## 16. Web 路由设计

### 16.1 人物关联

```text
GET  /runs/<run_id>/person-links
POST /runs/<run_id>/person-links
```

GET 参数：

- `baseline_version`；
- `status`；
- `q`。

POST：

- `baseline_version`；
- `changes_json`；
- `sync_dataset`；
- `note`。

### 16.2 重新处理

继续复用：

```text
POST /runs/<run_id>/process
```

增加：

```text
processing_mode=REPROCESS_EXISTING
```

后端不能只相信表单值，必须根据 Run 状态走只读数据处理路径。

### 16.3 身份归类

```text
GET  /processes/<process_id>/queries/<query_id>/classification
POST /processes/<process_id>/queries/<query_id>/classification
```

保留原单候选人 Review 路由用于详细字段人工评分。

### 16.4 字段矩阵

```text
GET /field-schemas/<schema_version>/comparison-matrix
```

参数：

- `baseline_version`；
- `process_id`；
- `person_id`；
- `module`；
- `status`；
- `q`。

发布仍复用现有 FieldSchema 发布入口。

### 16.5 JSON API

用于页面异步预览：

```text
GET /api/runs/<run_id>/person-links
GET /api/processes/<process_id>/classification-progress
GET /api/field-schemas/<schema_version>/comparison-matrix
GET /api/processes/<process_id>/metrics
```

所有写操作首版继续使用普通 POST，保持当前 Flask 架构简单。

## 17. 服务层设计

### 17.1 新增方法清单

| 方法 | 职责 |
| --- | --- |
| `get_run_person_link_context` | 获取 Query/Baseline 关联上下文 |
| `update_run_query_person_links` | 事务更新关联和审计 |
| `reprocess_existing_run` | 明确的无外部请求重处理 |
| `get_query_classification_context` | Query 级身份归类数据 |
| `save_query_classification` | 批量保存身份结果 |
| `build_field_comparison_matrix` | 聚合两侧字段矩阵 |
| `validate_process_field_alignment` | Process 前字段对齐检查 |
| `_apply_module_empty_rules` | 模块语义判空 |
| `_query_field_report_metrics` | Query 字段指标 |
| `_candidate_field_report_metrics` | Candidate 字段指标 |
| `_metrics_v3_quality` | v3 质量指标 |

### 17.2 异常

复用现有异常，并补充：

```python
class PersonLinkValidationError(ValueError):
    """人物关联校验失败。"""

class ClassificationValidationError(ValueError):
    """Query 候选人身份归类失败。"""

class FieldAlignmentError(ValueError):
    """字段对齐存在阻断问题。"""
```

错误信息必须包含：

- run_id/process_id；
- query_id；
- field_key 或 person_id；
- 可执行的修正建议。

### 17.3 事务边界

| 操作 | 事务范围 |
| --- | --- |
| 批量人物关联 | 全部 changes 同一事务 |
| Dataset 同步 | 与 Run 关联同一事务 |
| 身份归类 | 单 Query 全部候选人同一事务 |
| Schema 发布 | 新版本写入和 active 切换同一事务 |
| Process | 沿用现有先 PROCESSING 后完成/失败策略 |
| Report | 沿用现有快照与产物策略 |

## 18. 前端交互设计

### 18.1 JavaScript 范围

继续使用 `static/app.js`，不引入前端框架。

增加：

- 人物关联批量勾选；
- 变更计数；
- 保存前摘要；
- Query 身份归类状态联动；
- 主要 HIT 互斥；
- “确认无 HIT”互斥；
- 字段矩阵筛选；
- 字段角色开关联动；
- 未保存提示。

### 18.2 无 JavaScript 兼容

核心保存必须使用标准 HTML Form。

JavaScript 只负责：

- 批量选择；
- 交互联动；
- 搜索过滤；
- JSON 序列化；
- 状态提示。

服务端必须重新校验所有规则。

### 18.3 可访问性

- 开关关联真实 checkbox；
- 状态不只用颜色；
- 批量操作有明确 aria-label；
- 错误与字段行关联；
- 键盘可操作；
- 表单保存后显示成功/失败反馈。

## 19. 静态 HTML 与 Excel

### 19.1 静态 HTML

使用 `report-model-v3` 渲染：

- 指标状态；
- 原因；
- 数据返回率；
- 人物关联覆盖；
- 身份归类覆盖；
- 字段配置冲突；
- Query/Candidate scope。

旧 ReportModel 继续兼容现有模板分支。

### 19.2 Excel

增加或调整 Sheet：

| Sheet | 内容 |
| --- | --- |
| `Report_Summary` | v3 执行/身份/质量摘要 |
| `Query_Person_Links` | Query 与 Baseline Person 关联 |
| `Identity_Classification` | 候选人身份归类 |
| `Field_Matrix` | 字段两侧配置和覆盖 |
| `Field_Metrics` | 带 value_scope 的字段指标 |
| `Module_Metrics` | data/empty/unknown |
| `Not_Ready_Reasons` | 指标未就绪原因 |

保留现有 Raw 和 Candidate 明细 Sheet。

### 19.3 Excel 单元格

- JSON 超限继续拆 Raw Sheet；
- URL 使用超链接；
- 状态使用文本；
- 不把 null 输出为0；
- 比例同时保存数值和百分比格式；
- `reason_codes` 使用逗号连接，详细原因单独 Sheet。

## 20. 代码修改范围

### 20.1 必须修改

| 文件 | 修改内容 |
| --- | --- |
| `analysis_store.py` | Schema v4、迁移、审计表和新列 |
| `analysis_service.py` | 人物关联、重处理、身份归类、矩阵、processing-v3、metrics-v3 |
| `web_app.py` | 新路由、上下文、错误和报告入口 |
| `templates/run_detail.html` | 人物关联摘要和重处理入口 |
| `templates/process_detail.html` | 身份进度、scope 指标和原因 |
| `templates/candidate_detail.html` | 文案和字段人工评分边界 |
| `templates/field_schemas.html` | 字段矩阵入口和配置状态 |
| `templates/baselines.html` | 字段覆盖/矩阵入口 |
| `templates/_report_content.html` | report-model-v3 |
| `templates/report_detail.html` | 修复入口 |
| `static/app.js` | 批量关联、身份归类、矩阵交互 |
| `static/app.css` | 新工作区样式 |
| `result_to_excel_builder.mjs` | v3 Excel |
| `tests/test_analysis_store.py` | Schema v4 |
| `tests/test_analysis_service.py` | 服务、处理和指标 |
| `tests/test_web_app.py` | Web 流程 |
| `tests/test_result_to_excel.py` | Excel v3 |
| `README.md` | 历史 Run 修复说明 |

### 20.2 新模板策略

优先扩展现有模板。

只有当人物关联和 Query 身份工作区导致现有模板职责明显混乱时，才新增：

```text
templates/run_person_links.html
templates/query_classification.html
```

实际开发前先评估现有 `run_detail.html`、`process_detail.html` 是否可以清晰承载。

不为字段矩阵新增第二套 Schema 页面，继续从现有 FieldSchema 页面进入。

## 21. 测试设计

### 21.1 测试原则

1. 错误修复先补复现测试；
2. 每阶段运行相关测试；
3. 阶段完成运行全量测试；
4. 使用临时 SQLite；
5. 不修改生产数据库做自动测试；
6. 外部 HTTP 使用假客户端；
7. 重处理测试必须证明 HTTP 调用为0；
8. 报告使用固定输入断言快照字段，不依赖当前时间。

### 21.2 Schema v4

- 新库表和列存在；
- person_id_source 默认值；
- 审计外键；
- Review 新列；
- v3 数据迁移；
- 历史 reviewed_at 来源推导；
- 旧 HIT 主要候选人推导；
- 重复启动不重复列。

### 21.3 人物关联

- 空 person_id → 有效 Baseline Person；
- 错误 person_id 修正；
- 清除关联；
- 批量唯一建议；
- 同名多个不自动选；
- Baseline 不存在；
- Person 不属于 Baseline；
- expected_person_id 冲突；
- 可选 Dataset 同步；
- 审计完整；
- Report 标记 STALE；
- Raw/Results 文件校验和不变。

### 21.4 无成本重处理

- 已完成 EXECUTION Run；
- 已导入 IMPORT Run；
- 修正关联后新 Process 读取 Baseline；
- HTTP Client 被调用即测试失败；
- 旧 Process 数量和数据不变；
- 新 Process ID 不同；
- PENDING/RUNNING Run 被拒绝；
- 缺少 Raw 但已有结构化数据时边界提示。

### 21.5 身份归类

- 设置主要 HIT；
- 同 Query 第二个主要 HIT 被拒绝；
- 确认无 HIT；
- 无 HIT 与主要 HIT 互斥；
- 批量 NOT_HIT；
- 保持 PENDING；
- Detail 失败不能 HIT；
- optimistic lock；
- 报告 STALE；
- 字段空值不要求人工输入完整度。

### 21.6 字段矩阵

- Baseline 15字段、Schema 1个 completeness → 14冲突；
- Baseline 有值人数；
- Baseline 可用人数；
- Candidate 非空率；
- Query/Candidate scope；
- 字符串数组/对象数组结构冲突；
- manual 状态；
- 发布新 Schema 不改旧版本；
- 500字段性能基础测试。

### 21.7 processing-v3

- `status=empty + data={count:0,items:[]}`；
- Photos empty container；
- Profile 有一个有效 Item；
- Profile Section 全空；
- Social profiles 空；
- Social 有一条 URL；
- Summary 部分字段；
- 数值0默认有效；
- `zero_is_empty`；
- 缺失可选路径不报错；
- 类型冲突仍报错；
- URL 对象数组提取。

### 21.8 metrics-v3

固定场景：

```text
10 Query
45 Candidate
10 task_id
45 Profile data
34 Social data
2 Insights data
0 Photos data
```

断言：

- task_id=10/10；
- Profile=45/45；
- Social=34/45；
- Insights=2/45；
- Photos=0/45；
- PENDING 时全部候选人返回率 READY；
- PENDING 时身份指标 NOT_READY；
- 全部 NOT_HIT 后非命中完整度有值；
- 无 HIT 时命中指标 NOT_APPLICABLE；
- 有主要 HIT 后命中完整度使用有效交集；
- manual 准确率缺失显示 PARTIAL/NOT_READY。

### 21.9 ReportModel v3

- reason_codes；
- 修复入口映射；
- NOT_READY 文案；
- NOT_APPLICABLE 文案；
- Query/Candidate scope；
- 字段冲突摘要；
- 旧 report-model-v2 兼容；
- 静态 HTML 不出现无解释的统一“不适用”。

### 21.10 Excel

- 新 Sheet；
- null 不变0；
- scope 列；
- reason_codes；
- URL；
- 大 JSON；
- v2/v3 ReportModel 兼容。

### 21.11 Web 集成

完整流程：

```text
打开历史 Run
  → 选择 Baseline
  → 批量采用10个唯一人物建议
  → 保存
  → 验证无 HTTP
  → 使用已有数据重处理
  → 查看15字段矩阵
  → 发布新 Schema
  → 再次重处理
  → Query 级身份归类
  → 生成报告
  → 验证指标和原因
  → 导出 Excel/HTML
```

## 22. 开发计划

### 阶段0：基线冻结与问题复现

#### 目标

固定真实问题和新规则输入输出，避免实现过程中改变口径。

#### 工作项

1. 备份当前 SQLite；
2. 固定问题报告和 Process ID；
3. 从现有 results.jsonl 提取脱敏测试夹具；
4. 增加失败测试：
   - Query person_id 为空；
   - Baseline 无法关联；
   - 45个 PENDING 导致0/0；
   - Task ID 0/45；
   - Insights/Photos 空容器被判有数据；
   - 15个 Baseline 字段仅1个参与 completeness；
5. 记录 v2 当前输出；
6. 冻结 v3 原因码、公式和验收数据。

#### 主要文件

- `tests/test_analysis_service.py`
- `tests/test_analysis_store.py`
- `tests/test_web_app.py`
- 阶段验收记录文档

#### 完成标准

- 所有问题都有稳定复现测试；
- v2 行为快照可用于兼容测试；
- v3 期望值已经明确；
- 没有修改生产数据。

### 阶段1：Schema v4 与历史人物关联

#### 目标

实现安全、可审计的历史 Run Query 人物关联修正。

#### 工作项

1. Schema v4；
2. person_id_source；
3. run_query_person_history；
4. Review 分类来源/主要 HIT 列；
5. v3→v4 迁移；
6. 人物关联上下文；
7. 唯一名称建议；
8. 单条/批量更新；
9. 可选 Dataset 同步；
10. 乐观锁；
11. Report STALE；
12. Run 页面入口。

#### 主要文件

- `analysis_store.py`
- `analysis_service.py`
- `web_app.py`
- `templates/run_detail.html`
- `static/app.js`
- `static/app.css`
- `tests/test_analysis_store.py`
- `tests/test_analysis_service.py`
- `tests/test_web_app.py`

#### 完成标准

- 现有10条 Query 可关联到10个 Baseline Person；
- 修改历史完整；
- 原始文件校验和不变；
- 报告正确过期；
- 迁移和相关测试通过。

### 阶段2：无成本重处理与身份归类

#### 目标

使用已有数据生成新 Process，并简化候选人身份确认。

#### 工作项

1. `reprocess_existing_run()`；
2. 外部请求隔离；
3. 重处理安全提示；
4. 新 Process 初始化；
5. Query 级身份上下文；
6. 主要 HIT；
7. 确认无 HIT；
8. NOT_HIT/SUSPECTED/PENDING；
9. 批量设置其余候选人；
10. optimistic lock；
11. 字段空值自动完整度；
12. Process 身份进度。

#### 主要文件

- `analysis_service.py`
- `web_app.py`
- `templates/process_detail.html`
- `templates/candidate_detail.html`
- 身份工作区模板（如确有必要）
- `static/app.js`
- `static/app.css`
- `tests/test_analysis_service.py`
- `tests/test_web_app.py`

#### 完成标准

- 重处理 HTTP 调用为0；
- 新旧 Process 并存；
- 可以为每条 Query 指定一个主要 HIT 或确认无 HIT；
- 空字段无需人工补充；
- Review 变更令报告过期；
- 相关测试通过。

### 阶段3：字段对比矩阵与 processing-v3

#### 目标

统一展示两侧字段并修正字段空值语义。

#### 工作项

1. 矩阵聚合服务；
2. Baseline/Candidate 覆盖统计；
3. 双开关与评分角色；
4. 配置冲突检测；
5. Schema 复制发布；
6. URL 对象数组提取；
7. processing-v3；
8. Insights/Photos/Profile/Social 模块语义；
9. Process 前预检；
10. Baseline/FieldSchema/Process 页面入口。

#### 主要文件

- `analysis_service.py`
- `web_app.py`
- `templates/field_schemas.html`
- `templates/baselines.html`
- `templates/process_detail.html`
- `static/app.js`
- `static/app.css`
- `tests/test_analysis_service.py`
- `tests/test_web_app.py`

#### 完成标准

- 当前15字段问题在矩阵中可见；
- 可以发布新 FieldSchema 而不改旧版；
- 空模块统计正确；
- 字符串/对象 URL 结构统一；
- Process 前能看到阻断问题；
- 相关测试通过。

### 阶段4：metrics-v3 与 report-model-v3

#### 目标

修正分母、身份指标和报告状态。

#### 工作项

1. Query 字段指标；
2. Candidate 字段指标；
3. 全部候选人字段返回率；
4. 模块 data/empty/unknown；
5. 身份分类指标；
6. 命中完整度有效交集；
7. 命中准确率有效返回字段；
8. 非命中完整度；
9. 状态和 reason_codes；
10. ReportModel v3；
11. Web 修复入口；
12. 静态 HTML。

#### 主要文件

- `analysis_service.py`
- `web_app.py`
- `templates/process_detail.html`
- `templates/_report_content.html`
- `templates/report_detail.html`
- `tests/test_analysis_service.py`
- `tests/test_web_app.py`

#### 完成标准

- task_id=10/10；
- Profile=45/45；
- Social=34/45；
- Insights=2/45；
- Photos=0/45；
- 未归类时返回率可用；
- 无 HIT 时非命中完整度可计算；
- 报告无无解释“不适用”；
- v2 报告兼容。

### 阶段5：Excel、集成验收与文档

#### 目标

完成全链路交付并验证真实历史 Run 无成本修复。

#### 工作项

1. Excel v3；
2. 静态 HTML 验收；
3. 真实历史 Run 人物关联；
4. 无成本重处理；
5. 字段矩阵和新 Schema；
6. 身份归类；
7. 新报告；
8. Docker 构建；
9. 全量测试；
10. README；
11. 操作说明；
12. 阶段验收记录。

#### 主要文件

- `result_to_excel_builder.mjs`
- `tests/test_result_to_excel.py`
- `README.md`
- Docker 相关现有文件
- 阶段验收记录文档

#### 完成标准

- 全量自动化测试通过；
- Docker 5002 healthy；
- 历史 Run 没有新增接口费用；
- 新报告指标可解释；
- HTML/Excel 可导出；
- 操作文档完整；
- 用户可以独立完成历史 Run 修复。

## 23. 阶段依赖

```text
阶段0 基线冻结
   ↓
阶段1 Schema v4 + 人物关联
   ↓
阶段2 无成本重处理 + 身份归类
   ↓
阶段3 字段矩阵 + processing-v3
   ↓
阶段4 metrics-v3 + report-model-v3
   ↓
阶段5 Excel + 集成验收
```

阶段2依赖阶段1，因为新 Process 必须读取修正后的人物关联。

阶段4依赖阶段3，因为指标必须读取新的空值和字段角色快照。

## 24. 每阶段验证命令

### 数据库

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_analysis_store.py'
```

### 服务与指标

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_analysis_service.py'
```

### Web

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_web_app.py'
```

### Excel

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_result_to_excel.py'
```

### 全量

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
```

### Docker

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:5002/
```

## 25. 真实数据验收

使用：

```text
Run: run_2be5fe30b86f49bcba447296205911bb
Process: process_9c490abfc00f47a1a2f06d594f8819a7
Baseline: test20260728
旧报告: report_5a680512bbbc4048ae860ca42330b162
```

验收步骤：

1. 记录 results.jsonl、Raw 和数据库备份；
2. 打开 Run 人物关联管理；
3. 为10条 Query 选择对应 `diffbot-...` Person；
4. 保存并确认没有外部请求；
5. 旧报告变为 STALE，但仍可打开；
6. 使用 `field-schema-default-v2` 重处理，确认 Baseline 已关联；
7. 打开字段矩阵，确认14个评分配置冲突；
8. 复制发布 v3 Schema；
9. 再次使用已有数据重处理；
10. 完成10条 Query 身份归类；
11. 生成 report-model-v3；
12. 验证：
    - 10 Query；
    - 45 Candidate；
    - Task ID 10/10；
    - Profile 45/45；
    - Social 34/45；
    - Insights 2/45；
    - Photos 0/45；
13. 导出 HTML/Excel；
14. 对比接口调用日志，新增请求数必须为0。

## 26. 风险与应对

| 风险 | 应对 |
| --- | --- |
| 人物关联错配 | 姓名仅建议，保存前确认，保留审计 |
| 历史报告被新元数据影响 | 报告快照不重算，只标记 STALE |
| 重处理误调用接口 | 独立服务入口、依赖隔离、调用即失败测试 |
| 多个 HIT | Service 事务限制一个主要 HIT |
| 其余候选人误批量非命中 | 默认保持 PENDING，显式批量操作 |
| 评分字段过多导致人工负担 | 完整度自动，manual 准确率按需 |
| 复杂对象 exact 误判 | 改为 manual 或拆原子字段 |
| 空模块返回率虚高 | status + 核心内容双判断 |
| Query/Candidate 分母混用 | 独立指标方法和 value_scope 断言 |
| Schema v4 迁移失败 | 事务、备份、幂等测试 |
| v3 报告破坏旧报告 | 按 report_model_version 分支 |

## 27. 回滚方案

### 27.1 数据库

- 迁移前创建数据库备份；
- v4 只新增表和列，不删除 v3 数据；
- 如果新版本不可用，停止 v4 写入并恢复迁移前备份；
- 不尝试用删除列方式原地降级 SQLite。

### 27.2 Process

- 新 Process 异常时标记 FAILED；
- 旧 Process 保持可用；
- 不删除旧 Review；
- 可重新选择旧 Process 生成旧规则报告。

### 27.3 FieldSchema

- v3 Schema 为新版本；
- 失败时重新激活 v2；
- 已生成 Process 继续引用其 Schema 快照。

### 27.4 Report

- v3 报告失败不影响 v2；
- 报告模型和 HTML 产物按 report_id 隔离；
- Excel 失败时 HTML 仍可用。

## 28. 开发前确认项

以下项已经按 PRD确定，不再阻塞开发：

1. 历史 Run 可以修改 Query person_id；
2. 修改后不重新调用接口；
3. Raw、原始 JSONL、旧 Process 和旧报告不覆盖；
4. 候选人操作命名为“身份归类”；
5. 字段为空不需要人工确认；
6. Baseline 和 Candidate 两侧字段统一展示；
7. FieldSchema 继续版本化；
8. 空模块使用语义判空；
9. Query/Candidate 分母分开；
10. 报告必须展示具体未就绪原因。

实施阶段需要验证但不阻塞阶段0：

1. 现有历史 Run 是否都保留 Dataset clue；
2. 同名人物实际数量；
3. 历史多个 HIT 数据是否存在；
4. Excel 新 Sheet 顺序是否需要与既有模板保持固定；
5. Profile/Photos manual 准确率是否在本轮真实评测中启用。

## 29. 最终验收清单

- [ ] Schema v4 迁移成功且幂等；
- [ ] Query person_id 可安全修正；
- [ ] 人物关联有完整审计；
- [ ] 可选同步 Dataset；
- [ ] 旧 Raw 和结果文件不变；
- [ ] 重处理外部接口请求为0；
- [ ] 新旧 Process 并存；
- [ ] 候选人身份归类文案清晰；
- [ ] 每 Query 最多一个主要 HIT；
- [ ] 可以确认无 HIT；
- [ ] 空字段自动进入完整度；
- [ ] 字段矩阵同时展示两侧配置；
- [ ] 评分配置冲突可见；
- [ ] FieldSchema 发布新版本；
- [ ] URL 对象数组正确提取；
- [ ] 空 Insights/Photos/Social 不计为有数据；
- [ ] Query 字段分母正确；
- [ ] Candidate 字段分母正确；
- [ ] PENDING 时全部候选人返回率可用；
- [ ] 非命中完整度在完成归类后可计算；
- [ ] 报告区分 NOT_READY/NOT_APPLICABLE；
- [ ] 报告提供修复入口；
- [ ] 静态 HTML 可生成；
- [ ] Excel v3 可生成；
- [ ] 旧 ReportModel 可继续展示；
- [ ] 全量测试通过；
- [ ] Docker 服务 healthy；
- [ ] 真实历史 Run 修复不产生新费用。
