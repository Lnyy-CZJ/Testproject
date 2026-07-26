# searchTool v1.3 MVP 优化阶段0：接口契约与基线冻结记录

> 记录日期：2026-07-24  
> 对应需求：`docs/searchTool_v1.3_MVP_优化需求.md`  
> 对应开发设计：`docs/searchTool_v1.3_MVP_优化开发设计与开发计划.md`  
> 阶段范围：仅冻结升级前数据库、报告、测试和接口契约，不实现 Schema v2、字段处理
> v2、指标 v2 或 ReportModel v2。

## 1. 阶段结论

阶段0完成，可以进入阶段1“数据库 Schema v2”。

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| Schema v1 数据库已备份 | 通过 | SQLite 在线备份，`PRAGMA integrity_check=ok` |
| 源库与备份表行数一致 | 通过 | 15张业务表逐表一致 |
| 当前报告已记录 | 通过 | HTML、ReportModel、processed export 已记录 SHA-256 |
| 阶段开始前测试基线 | 通过 | 48/48，48.553秒 |
| 增加契约夹具后全量测试 | 通过 | 49/49，45.416秒 |
| GetTask 全量 Mock | 通过 | 新增脱敏标准响应 |
| GetTask 部分缺失 Mock | 通过 | 缺少第三方成本、总成本和耗时 |
| Candidate 可选空路径 Mock | 通过 | `items=[]`、`primary_image=null` |
| Baseline 可用字段样例 | 通过 | 新增 JSONL 目标结构 |
| 未确认接口项 | 已记录 | 路径、单位、包含关系、枚举和参考线均未猜测 |
| 业务流程代码 | 未修改 | 本阶段只新增夹具、契约测试、备份和记录 |

## 2. 冻结环境

| 项目 | 值 |
| --- | --- |
| 日期 | 2026-07-24 |
| Python | 3.12.10 |
| Git 分支 | `dev` |
| HEAD | `59780ef70a158127a2bc8205c34f6b540512dd88` |
| 数据库 | `data/searchtool_v1_3.db` |
| Schema | `1` |
| 报告目录 | `output/reports` |

工作区在阶段0开始前已经包含 v1.3 阶段0～阶段7及用户后续文档的未提交改动。本阶段没有
回退、覆盖或清理这些改动。

## 3. 数据库基线

### 3.1 在线备份

备份文件：

```text
outputs/v1_3_mvp_optimization_phase0/searchtool_v1_3_schema_v1_backup.db
```

使用 SQLite `.backup` 在线备份，避免数据库启用 WAL 或服务运行时直接复制主文件导致
快照不一致。

验证结果：

```text
PRAGMA integrity_check = ok
PRAGMA foreign_key_check = 无错误
```

### 3.2 校验值

| 文件 | SHA-256 |
| --- | --- |
| 源数据库 | `1630254faf9d211ecb99c16c5568c766b5cc28ee57c988a2df4181ed88280652` |
| 在线备份 | `bd3b50b1bfb34e505f10d344544cfa283ef7e1275d04ad8bba663ead51872546` |

源文件与在线备份的二进制校验值不同是正常现象：SQLite 在线备份会生成一致的独立数据库
文件，不保证与启用 WAL 的源文件逐字节一致。业务表行数和完整性检查必须一致。

### 3.3 表行数

| 表 | 源库 | 备份 | 结果 |
| --- | ---: | ---: | --- |
| `evaluations` | 1 | 1 | 一致 |
| `datasets` | 1 | 1 | 一致 |
| `dataset_queries` | 3 | 3 | 一致 |
| `runs` | 1 | 1 | 一致 |
| `run_queries` | 3 | 3 | 一致 |
| `candidates` | 14 | 14 | 一致 |
| `raw_records` | 24 | 24 | 一致 |
| `failures` | 0 | 0 | 一致 |
| `field_schemas` | 1 | 1 | 一致 |
| `baseline_sets` | 0 | 0 | 一致 |
| `baseline_people` | 0 | 0 | 一致 |
| `process_runs` | 1 | 1 | 一致 |
| `processed_candidates` | 14 | 14 | 一致 |
| `reviews` | 14 | 14 | 一致 |
| `reports` | 1 | 1 | 一致 |

阶段1迁移验收必须至少满足：

1. 上述已有记录不丢失；
2. Raw、Process、Review 和 Report 数量不减少；
3. 备份仍能由仅支持 Schema v1 的当前代码打开；
4. v1→v2 迁移失败时源数据库事务回滚；
5. 迁移测试使用备份副本或临时数据库，不直接修改本冻结文件。

## 4. 报告基线

当前报告目录包含：

```text
output/reports/
  eval_20260724/
    report_8ca02fd661a349a6aded268b21763e92/
      20260724_eval_20260724_test_version_report.html
      processed_export.jsonl
      report_model.json
```

| 文件 | SHA-256 |
| --- | --- |
| HTML | `d07930b14df1b4ec50f45b66bea0e9e675234f0fa364fc555f6f16e7cb12198d` |
| ReportModel | `ea93afc0681bb60cb69261e4dadfafd0f023bfc94704b19465634d727c6aac48` |
| processed export | `ef93bc74b9416230efe61c13cf0c774095bf8fb9fa9b94013ac9e9611e059518` |

后续升级要求：

- 旧报告继续读取自身 `metrics_json/report_model.json`；
- 旧 HTML 文件不覆盖；
- ReportModel v2 不得让旧 ReportModel v1 页面404或渲染异常；
- 新字段为空时不得把旧报告中的空值改成0。

## 5. 自动测试基线

### 5.1 阶段开始前

命令：

```bash
python3 -m unittest discover -s tests -v
```

结果：

```text
Ran 48 tests in 48.553s
OK
```

说明：

- 不调用真实搜索接口；
- 使用临时目录和 Fake Session；
- 覆盖执行、导入、字段处理、复核、指标、报告、Excel 和 Web。

### 5.2 增加契约夹具后

新增测试：

```text
test_phase0_optimization_contract_fixtures_are_frozen
```

全量结果：

```text
Ran 49 tests in 45.416s
OK
```

该测试只冻结标准响应信封、字段类型和缺失结构，不提前实现阶段1～阶段5业务逻辑。

### 5.3 启动冒烟

以下检查通过：

```bash
python3 search_tool.py --help
python3 result_to_excel.py --help
```

Flask `create_app()` 可成功初始化并注册现有路由。

### 5.4 静态检查

通过：

```bash
python3 -m py_compile ...
node --check result_to_excel_builder.mjs
```

Ruff 基线有1条现存问题：

```text
analysis_service.py:3421
F541 f-string without any placeholders
```

该问题只是 SQL 字符串前多余的 `f`，不影响运行或阶段0测试，与本次接口契约冻结无关。
为避免“顺便修改”业务文件，本阶段只记录，不修复。后续修改
`analysis_service.py` 的对应阶段可用独立最小改动处理。

## 6. 新增接口契约夹具

目录：

```text
tests/fixtures/v1_3_optimization_phase0/
  README.md
  get_task_public_fields_full.json
  get_task_public_fields_partial.json
  candidate_detail_optional_fields_missing.json
  baseline_available_fields.jsonl
```

全部使用虚构标识和 `example.test` 域名，不包含真实 URL、Token、Headers、Device ID、
User ID 或个人信息。

### 6.1 GetTask 全量公共字段

文件：

```text
get_task_public_fields_full.json
```

冻结目标结构：

```json
{
  "status": "SUCCEEDED",
  "candidate_count": 2,
  "llm_cost": 0.0125,
  "third_party_cost": 0.045,
  "total_cost": 0.0575,
  "pdl_called": true,
  "search_duration_ms": 18420
}
```

说明：

- 当前按 `responses[0].data` 构造正式 Mock；
- 数字仅用于类型和聚合边界测试；
- 不代表成本单位已经确认；
- 不代表 `total_cost` 的包含关系已经确认。

### 6.2 GetTask 部分缺失

文件：

```text
get_task_public_fields_partial.json
```

覆盖：

- `llm_cost = 0.0`，验证有效0不能被当成缺失；
- `pdl_called = false`，验证 false 不能被当成缺失；
- 缺少 `third_party_cost`；
- 缺少 `total_cost`；
- 缺少 `search_duration_ms`。

阶段2/阶段4实现后，缺少字段应保存为 `null` 并分别统计缺失数，不能阻止已有字段聚合。

### 6.3 Candidate 可选字段为空

文件：

```text
candidate_detail_optional_fields_missing.json
```

覆盖：

```text
ui_sections.insights.data.items = []
ui_sections.summary.data.primary_image = null
ui_sections.summary.data.confidence_level = MEDIUM
```

阶段2实现后的预期：

- `insights_description = null`；
- `insights_links = []` 或 `null`；
- `summary_primary_image_url = null`；
- 三者不产生 `FIELD_PROCESSING_ERROR`；
- `candidate_confidence = MEDIUM`。

`MEDIUM` 仅为现有样例观察值，不代表完整枚举已经确认。

### 6.4 Baseline Available Fields

文件：

```text
baseline_available_fields.jsonl
```

目标结构：

```json
{
  "person_id": "person-contract-001",
  "fields": {},
  "baseline_available_fields": [
    "profile_full_name",
    "profile_location",
    "summary_social_links"
  ],
  "evidence": {}
}
```

该文件冻结阶段3 Baseline 导入的目标结构。当前阶段的导入器尚未读取该数组，因此本阶段
只校验 JSONL 合法性，不提前改变 Baseline 业务逻辑。

### 6.5 夹具校验值

| 文件 | SHA-256 |
| --- | --- |
| `README.md` | `1bf04ae8c045b45d6827556dd74929e3b129bb435bc460ef4b8864e1b021ac2e` |
| `baseline_available_fields.jsonl` | `01b7c9a73601763e9c2337f817c487549eb8c73f52c18ce01d957fc0afd525f7` |
| `candidate_detail_optional_fields_missing.json` | `556da7b74eadb1782fba3b0df8085f662bd0e72736877bd62245123ae0bcc04c` |
| `get_task_public_fields_full.json` | `7e040b4852cab584e02473b899e4299aa7efd52e8c7a55d754781f496712149e` |
| `get_task_public_fields_partial.json` | `3dc880aa1629a59d1f582bd68f0ddc323fdb50f152d0d74111125000d465eb24` |

修改夹具时必须同步修改：

1. 契约测试；
2. 本记录的校验值；
3. 对应开发阶段的字段路径和类型说明；
4. 后端确认事项状态。

## 7. 当前核心代码校验值

由于当前工作区包含未提交的既有阶段成果，除 Git HEAD 外，额外记录主要实现文件
SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `analysis_store.py` | `caaeb4e3a15b172258fe0703f285a69aaf05a77f67ef55c51282734436937150` |
| `analysis_service.py` | `1df6adbbf5a0afaee2af242c14fbc322f6226c3d8a74301424694fbcbe6fb303` |
| `search_tool.py` | `2b44ec9ea34d1d51d71ac5ee88cb4189fb6558b2a2a77e8e7f0e6f0269a0f999` |
| `web_app.py` | `bd639c52e14fd3f7c12ae68bd26ff8c398adeae9ad17ea7abd1ba5d30214f0d5` |
| `result_to_excel.py` | `e137cb6d7a98f4d266f23edd05c8518f34a5983e50cc2be436950ab0b91e1c46` |
| `result_to_excel_builder.mjs` | `c68627809db371437ad524b5027c3968c6d1576eeadb40aa11ada7b975ce0347` |
| `templates/_report_content.html` | `4a9f27aa6471c252d4f229c72d2fd145cdf6b23c59b41c9036e85f69cbe3cefe` |

`tests/test_search_tool.py` 本阶段增加契约冻结测试，因此不使用阶段开始前校验值作为后续
业务代码回归依据。

## 8. 接口契约状态

### 8.1 已确认

| 事项 | 状态 | 依据 |
| --- | --- | --- |
| GetTask 终态 | `SUCCEEDED` | 现有接口流程 |
| GetTask 数据区 | `responses[0].data` | 现有解析逻辑 |
| Candidate Confidence | Summary Confidence Level | 用户明确确认 |
| Confidence 路径 | `ui_sections.summary.data.confidence_level` | 现有字段配置 |
| 可选空路径 | 应处理为空值 | 用户明确确认 |
| 缺失成本 | 不能按0 | 最新优化需求 |
| `total_cost` | 直接采用接口返回值 | 最新优化需求 |

### 8.2 待确认

| 事项 | 当前处理 | 责任方/输入 |
| --- | --- | --- |
| `llm_cost` 正式路径 | Mock 使用 GetTask data 同名字段 | 后端提供完整响应 |
| `third_party_cost` 正式路径 | Mock 使用 GetTask data 同名字段 | 后端提供完整响应 |
| `total_cost` 正式路径 | Mock 使用 GetTask data 同名字段 | 后端提供完整响应 |
| `pdl_called` 正式路径 | Mock 使用 GetTask data 同名字段 | 后端提供完整响应 |
| `search_duration_ms` 正式路径 | Mock 使用 GetTask data 同名字段 | 后端提供完整响应 |
| 成本单位 | 不展示推测单位 | 后端确认 |
| total 是否包含子成本 | 不自行相加 | 后端确认 |
| PDL 是否严格 boolean | v2 映射前校验 | 后端确认 |
| 耗时是否包含排队 | 原值展示，不改名解释 | 后端确认 |
| available fields 来源 | 先支持 Baseline 导入目标 | 后端/测试确认 |
| Confidence 完整枚举 | 原值保存，新值不拒绝 | 后端确认 |
| 正式参考线 | 留空并显示未配置 | 测试负责人确认 |

## 9. 阶段0修改范围

新增：

- `tests/fixtures/v1_3_optimization_phase0/README.md`
- `tests/fixtures/v1_3_optimization_phase0/get_task_public_fields_full.json`
- `tests/fixtures/v1_3_optimization_phase0/get_task_public_fields_partial.json`
- `tests/fixtures/v1_3_optimization_phase0/candidate_detail_optional_fields_missing.json`
- `tests/fixtures/v1_3_optimization_phase0/baseline_available_fields.jsonl`
- `outputs/v1_3_mvp_optimization_phase0/searchtool_v1_3_schema_v1_backup.db`
- 本阶段冻结记录

修改：

- `tests/test_search_tool.py`：只增加夹具契约冻结测试。

未修改：

- `search_tool.py`
- `analysis_store.py`
- `analysis_service.py`
- `web_app.py`
- Report 模板
- Excel 构建逻辑
- SQLite 源数据库业务记录

## 10. 回滚

本阶段没有业务代码或数据库结构改动。

如需回滚：

1. 删除优化阶段0夹具目录；
2. 删除对应契约测试；
3. 删除阶段0备份和本记录。

回滚不会修改：

- `data/searchtool_v1_3.db`；
- 现有 Raw；
- 现有报告；
- 现有 v1.3 功能。

冻结备份属于可恢复产物，正常情况下不应删除。

## 11. 进入阶段1条件

已满足：

- [x] 当前全量测试通过；
- [x] Schema v1 备份完整；
- [x] 表行数和报告校验值已记录；
- [x] GetTask 全量/部分缺失 Mock 已准备；
- [x] Candidate 可选空路径 Mock 已准备；
- [x] Baseline 可用字段目标样例已准备；
- [x] 未确认事项已明确记录；
- [x] 阶段0未修改业务流程。

阶段1可以先基于 Mock 完成 Schema v2 和迁移框架。接口真实路径未确认不会阻塞数据库
结构开发，但在路径确认前，新字段在真实运行中必须保持 `null`，不能使用 Mock 数值。
