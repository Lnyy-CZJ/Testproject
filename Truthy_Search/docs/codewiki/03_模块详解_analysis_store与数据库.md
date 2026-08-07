# 03 · 模块详解：analysis_store.py 与数据库

文件：[analysis_store.py](../../analysis_store.py)（约 877 行）
配套文档：[docs/数据库说明.md](../数据库说明.md)

## 1. 模块定位

**纯存储层**。职责边界（类 docstring 明确声明）：

- 管理单个 SQLite 数据库文件（默认 `data/searchtool_v1_3.db`）；
- 统一连接设置：`foreign_keys=ON`、`journal_mode=WAL`、`busy_timeout=5000`（行 343–345）；
- 幂等的 Schema v4 初始化 + v1→v2→v3→v4 连续单事务迁移；
- 显式写事务与通用只读查询。

> **重要**：本文件不包含业务导入/写入逻辑（除唯一的 `create_evaluation` 外）。所有业务表的 INSERT/UPDATE 均在 [analysis_service.py](../../analysis_service.py) 中，通过 `transaction()` 直接执行 SQL。

## 2. 顶层结构

| 元素 | 行号 | 说明 |
|---|---|---|
| `DB_SCHEMA_VERSION = 4` | 14 | 当前支持的 Schema 版本 |
| `UnsupportedSchemaError` | 17–18 | 数据库版本超出支持范围时抛出 |
| `SCHEMA_SQL` | 21–304 | Schema v4 全量 DDL（18 表 + 9 索引） |
| `utc_now_text()` | 307–310 | 带时区 UTC ISO 8601 时间文本，全库 `*_at` 统一来源 |
| `AnalysisStore` | 313–877 | 存储层主类 |

## 3. AnalysisStore 方法清单

### 3.1 连接与事务

| 方法 | 行号 | 说明 |
|---|---|---|
| `connection()` | 327–348 | 上下文管理器；自动建目录，`sqlite3.connect(timeout=5.0)`，`row_factory=sqlite3.Row`，三条 PRAGMA，finally 关闭 |
| `transaction()` | 350–361 | 在 `connection()` 内显式 `BEGIN`，成功 commit，异常 rollback 后重抛 |

### 3.2 初始化与迁移

| 方法 | 行号 | 说明 |
|---|---|---|
| `initialize()` | 751–799 | 幂等入口；单事务内建 `schema_info` → 判版本 → 新库建全量 / 旧库链式迁移 |
| `_execute_schema_sql()` | 363–384 | 按分号拆分 DDL 逐条执行；**刻意不用 `executescript`**，避免隐式提交破坏迁移原子性 |
| `_column_names()` / `_add_column_if_missing()` | 386–424 | 幂等补列 |
| `_legacy_available_fields()` | 426–456 | 从 v1 时代 `baseline_people.fields_json` 派生可评测字段键 |
| `_migrate_v1_to_v2()` | 458–579 | 补 8 列（thresholds_json、evaluation_phase、result_status、third_party_cost、search_duration_ms、public_fields_json、available_fields_*）并回填 |
| `_migrate_v2_to_v3()` | 581–619 | 建 `threshold_profiles`，`evaluations` 加 `threshold_profile_id`；历史 thresholds 不解析不重写 |
| `_migrate_v3_to_v4()` | 621–749 | 加 `person_id_source`（dataset_queries/run_queries）、`classification_source`、`is_primary_hit`（reviews）；建 `run_query_person_history` 审计表；回填来源与主要命中（历史多 HIT 取 rank 最小并发 RuntimeWarning） |

### 3.3 查询与业务方法

| 方法 | 行号 | 说明 |
|---|---|---|
| `schema_version()` | 801–809 | 读当前版本；未初始化抛 `UnsupportedSchemaError` |
| `fetch_one(sql, params)` | 811–819 | 参数化只读查询，返回首行或 None |
| `fetch_all(sql, params)` | 821–829 | 参数化只读查询，返回全部行 |
| `create_evaluation(...)` | 831–877 | **唯一的公开业务写方法**；thresholds 以紧凑 JSON 写入 |

**无 `backup()` 方法**：备份方案为外部使用 SQLite backup API（见 [07 章](./07_依赖关系与运行方式.md#6-备份与恢复)；测试 `tests/test_analysis_store.py::test_sqlite_online_backup_can_be_restored` 演示了该用法）。

## 4. 数据库表结构（Schema v4，18 + 1 张表）

### 4.1 表清单

| # | 表 | 主键/唯一约束 | 用途 |
|---|---|---|---|
| 1 | `schema_info` | `key` | 元数据（`schema_version=4`） |
| 2 | `threshold_profiles` | `profile_id`；UNIQUE(name, version) | 版本化参考线方案；`based_on_profile_id` 记录派生 |
| 3 | `evaluations` | `evaluation_id` | 评测容器：名称、`thresholds_json` 快照、`threshold_profile_id` |
| 4 | `datasets` | `dataset_id`；checksum UNIQUE | Query 数据集元信息 |
| 5 | `dataset_queries` | `(dataset_id, query_id)` | 数据集每条查询输入：person_id 及来源、阶段、匹配策略、clues/补充/元数据 JSON |
| 6 | `runs` | `run_id`；source_checksum UNIQUE | 一次运行：所属评测/数据集、run_label（baseline/candidate）、系统版本、状态、结果文件路径、Query 统计、评测阶段 |
| 7 | `run_queries` | `(run_id, query_id)` | Query 执行结果：状态、当前阶段、候选计数、5 个成本/耗时字段、`result_status`、`public_fields_json`、person_id 及来源、起止时间 |
| 8 | `candidates` | `candidate_pk`；UNIQUE(run_id, query_id, candidate_rank) | 候选人详情：排名、rank_score、详情状态、`ui_sections_json`、`detail_data_json`、`list_item_json` |
| 9 | `raw_records` | `raw_id` | 原始接口响应快照：阶段、序号、payload JSON（append-only） |
| 10 | `failures` | `failure_id` | 失败记录：scope（INPUT/QUERY/CANDIDATE/IMPORT/PROCESS）、stage、error |
| 11 | `field_schemas` | `schema_version` | 字段配置：definitions JSON、`is_active` |
| 12 | `baseline_sets` | `baseline_version`；checksum UNIQUE | 基准数据集元信息 |
| 13 | `baseline_people` | `(baseline_version, person_id)` | 基准人物：fields/evidence/可评测字段及来源 |
| 14 | `run_query_person_history` | `history_id` | **v4 新增**：Query-人物关联变更审计（old/new person_id、来源、是否同步数据集） |
| 15 | `process_runs` | `process_id` | 字段处理任务：关联 run/schema/baseline、规则版本、状态、错误数 |
| 16 | `processed_candidates` | `(process_id, candidate_pk)` | 候选级结构化结果：fields/empty_fields/processing_errors |
| 17 | `processed_queries` | `(process_id, query_id)` | Query 级结构化结果 |
| 18 | `reviews` | `(process_id, candidate_pk)` | 人工复核：judgement/reason/evidence、字段评分、`classification_source`（SUGGESTED/MANUAL）、`is_primary_hit` |
| 19 | `reports` | `report_id` | 报告产物：baseline/candidate process_id、类型、状态、metrics_json、html/excel 路径 |

### 4.2 索引（9 个）

`idx_runs_evaluation_created`、`idx_run_queries_status_stage`、`idx_run_queries_person_stage`、`idx_candidates_run_query_rank`、`idx_failures_run_scope_stage`、`idx_process_runs_run_created`、`idx_processed_queries_process_status`、`idx_reviews_process_judgement`、`idx_person_history_run_query`（v4 新增）。

### 4.3 表关系概览

```text
评测主干：
evaluations ──< runs ──< run_queries ──< candidates ──< raw_records
    │              │           │                          
    │              │           └──< failures（scope 关联）
    │              └──< run_query_person_history（审计）
    └──< reports >── process_runs ──< processed_candidates ──< reviews
                         │      └──< processed_queries
                         ├── field_schemas（冻结 schema_version）
                         └── baseline_sets ──< baseline_people

数据源主干：
datasets ──< dataset_queries
datasets ──< runs（执行 Run 绑定数据集）

逻辑引用：
threshold_profiles ⇢ evaluations（快照复制，非外键）
```

**通用约定**：`*_id/*_pk/*_version` 为文本业务标识；`*_json` 一律 TEXT 存 JSON 原文；`*_at` 一律 UTC ISO 8601 文本；枚举取值由业务流程控制，Schema 层不做 CHECK 限制。

## 5. schema_info.schema_version 机制

- 存储：`schema_info(key TEXT PRIMARY KEY, value TEXT)`，唯一键 `schema_version`；
- **新库**：无记录 → 执行全量 `SCHEMA_SQL` → 写入 `'4'`；
- **旧库**：`int()` 解析失败或 `<1` / `>4` → `UnsupportedSchemaError`（防止新版本库被旧程序打开、非法版本被误启动）；按链式顺序 v1→v2→v3→v4 迁移，每步末尾 `UPDATE schema_info` 提升版本；
- **原子性**：`initialize()` 与全部迁移共用一个 `transaction()`，任一 DDL/回填失败整体回滚、版本不变；
- 业务侧约束：当前版本 ≠ 4 时应用拒绝启动；升级未来 Schema 必须先完整备份并使用对应迁移程序，禁止手改版本号。

## 6. 与 docs/数据库说明.md 的差异

`docs/数据库说明.md` 内容整体准确，但**停留在 Schema v3**，阅读时注意以下差异（以代码为准）：

| 差异项 | 说明 |
|---|---|
| 版本号 | 文档记载 v3，代码为 `DB_SCHEMA_VERSION = 4` |
| 缺表 | 文档未收录 v4 新增的 `run_query_person_history` |
| 缺列 | 文档缺 `dataset_queries.person_id_source`、`run_queries.person_id_source`、`reviews.classification_source`、`reviews.is_primary_hit` |
| 缺索引 | 文档 8 个索引，代码 9 个（缺 `idx_person_history_run_query`） |

其余（PRAGMA 设置、JSON/UTC 约定、字段语义、备份运维建议）与代码一致。
