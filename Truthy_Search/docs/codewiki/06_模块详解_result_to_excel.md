# 06 · 模块详解：result_to_excel（Excel 导出链）

文件：[result_to_excel.py](../../result_to_excel.py)（约 167 行）+ [result_to_excel_builder.mjs](../../result_to_excel_builder.mjs)（约 2770 行）

## 1. 架构：两段式 subprocess 链

```text
调用方（CLI 直接运行 或 AnalysisService.export_report_excel）
  → python3 result_to_excel.py <single|compare|processed> [--flags...]
      → 定位 Node（SEARCHTOOL_NODE > 内置 Codex runtime > 系统 node）
      → node result_to_excel_builder.mjs <同参数>
          → 读取 JSONL / ReportModel 快照 → 构建中间数据模型
          → @oai/artifact-tool 生成带格式 .xlsx（临时文件 → 原子 rename）
```

Python 侧与 Node 侧通过**命令行参数 + 环境变量 + 退出码**通信（无 stdin 管道）；Python 原样透传 Node 退出码。两侧都**不读取接口凭证、不访问网络、不修改原始结果**。

## 2. result_to_excel.py（Python 启动器）

### 2.1 常量与 Node 定位

- `BUILDER = PROJECT_ROOT / "result_to_excel_builder.mjs"`；
- `find_node()`（27–50）优先级：**`SEARCHTOOL_NODE` 环境变量 > 内置 `BUNDLED_NODE`（Codex 运行时硬编码路径）> `shutil.which("node")`**；均不可用抛 RuntimeError。

### 2.2 参数处理（`prepare_arguments`，53–129）

1. 消费 `--env-file`（默认 `.env`，`load_dotenv(override=False)` 只填空缺）；
2. 按模式把 `EXCEL_*` 环境变量映射为缺失的 CLI flag：
   - `single`：`EXCEL_RESULTS_FILE / EXCEL_FAILURES_FILE / EXCEL_OUTPUT_FILE / EXCEL_RUN_LABEL / EXCEL_SYSTEM_VERSION / EXCEL_EVALUATION_ID / EXCEL_METADATA_FILE`；
   - `compare`：`EXCEL_BASELINE_* / EXCEL_CANDIDATE_*` + 公共项；
   - `processed`：`EXCEL_PROCESSED_INPUT_FILE / EXCEL_REPORT_MODEL_FILE / EXCEL_OUTPUT_FILE`；
3. 冲突阻断：已显式给出 `--run-dir`（single）或 `--baseline-dir/--candidate-dir`（compare）时，禁止再从 .env 注入文件参数；
4. 显式 CLI 参数始终优先。

### 2.3 main（132–163）

校验 BUILDER 存在 → `find_node()` → 预处理参数 → `subprocess.run([node, builder, *args], cwd=PROJECT_ROOT)` → 返回 Node 退出码（启动错误返回 1）。

## 3. result_to_excel_builder.mjs（Node 构建器）

### 3.1 职责

读取一/两个 Run 的 JSONL 文件或 processed 导出 + ReportModel 快照，构建**与工作簿无关的中间数据模型**，再用 `@oai/artifact-tool` 生成带格式、公式、数据校验的 `.xlsx`。

关键常量：`RAW_TRIGGER_LENGTH=32000`（超长内容迁移 Raw Sheet 阈值）、`RAW_CHUNK_LENGTH=30000`（分块大小）、`DEFAULT_DISPLAY_TIMEZONE="Asia/Shanghai"`。

### 3.2 通信与环境变量（Node 侧）

| 变量 | 作用 |
|---|---|
| `SEARCH_DISPLAY_TIMEZONE` | Excel 时间列展示时区（非法回退 Asia/Shanghai） |
| `SEARCHTOOL_ARTIFACT_BOOTSTRAPPED` | 防止 artifact-tool 引导自举死循环 |
| `SEARCHTOOL_NODE_MODULES` | 手工指定 `@oai/artifact-tool` 所在 node_modules |
| `SEARCHTOOL_MODEL_OUTPUT` | 把中间模型 dump 为 JSON（调试/测试） |
| `SEARCHTOOL_SKIP_WORKBOOK=1` | 只生成模型不写工作簿（单测免启动成本） |
| `SEARCHTOOL_VERIFY_DIR` | 输出 inspect ndjson 与 PNG 预览做可视化验收 |

`loadArtifactTool()`（87–121）：直接 `import("@oai/artifact-tool")` 失败时，在临时目录建 node_modules 符号链接并以 `SEARCHTOOL_ARTIFACT_BOOTSTRAPPED=1` 重新执行自身；运行时只用其 `Workbook` 与 `SpreadsheetFile` 两个导出。

### 3.3 三种模式

| 模式 | 输入 | 用途 |
|---|---|---|
| `single` | 一个 Run 的 results/failures JSONL（或 `--run-dir` 固定文件名） | 单 Run 评测工作簿 |
| `compare` | baseline + candidate 两个 Run + 可选 metadata | 同条件对比工作簿 |
| `processed` | `processed_export.jsonl` + `report_model.json` | Web 报告配套 Excel（由 AnalysisService 调用） |

### 3.4 主要函数分组

**CLI 与读取**：`parseArgs`（124–170，模式判定与必填校验）、`readJsonl`（173–192，行级错误收集而非中断）、`readJsonObject`（195–213）。

**ReportModel → 行数据**：`appendMetricGroup`（600–696，核心指标审计行）、`buildV3AuditRows`（706–830，Report_Summary / Query_Person_Links / Identity_Classification / Field_Matrix / Field_Metrics / Module_Metrics / Not_Ready_Reasons）、`buildV4AuditRows`（833–917，五模块质量、**仅主命中进入字段对比**、字段返回率、规则快照）、`buildReportRows`（920–1043，汇总入口含参考线结论）。

**processed 模型**：`buildProcessedModel`（1046–1146）：按 `record_type` 分流 candidate/query/failure，动态字段列来自 `field_metrics` 与候选 fields 并集。

**single/compare 模型**：`loadRun`（1149–1215，重复 input_id 记冲突）、`loadMetadata`（1218–1243）、`flattenCandidate`（1305–1409，`ui_sections` 五模块展平为固定列 + 动态 `profile.<section>.<label>` 列）、`runStatus`（1421–1436，DATA_CONFLICT/SUCCESS/NO_CANDIDATE/FAILED/MISSING）、`buildQueryRow`（1439–1483，含 hit1/3/5、mrr5 占位）、`collectFailureRows`（1486–1521）、`buildModel`（1805–1866 总装）、`buildFieldCatalog`（1683–1772，字段中文字典）、`extractRawRows`（1775–1802，超长内容分块并留 `RAW:run_label:query_id:candidate_id:field` 引用）。

**写入与样式引擎**：`safeExcelValue`（防公式注入，`=+-@` 开头前置单引号）、`excelDateTime`（ISO 时间转展示时区墙钟）、`writeDataSheet`（冻结首行、深蓝表头、TableStyleMedium2）、`applySemanticNumberFormats`（比率 0.0%、成本 #,##0.0000）、`applyManualValidations`（人工复核下拉 + 黄色可编辑底纹）、`applyQueryFormulas`（`*_target_rank` 驱动的 Hit@1/3/5、MRR5 公式）。

**自检**：写完后校验 Sheet 清单、正则扫描公式错误（`#REF!/#DIV/0!/#VALUE!/#NAME?/#N/A`）、抽查关键表；`SEARCHTOOL_VERIFY_DIR` 时每 12 列渲染 PNG 预览；最后临时文件 → 原子 rename 导出。

### 3.5 Sheet 结构

**single / compare 模式**（`writeWorkbook`，2144–2304）：

| Sheet | 内容 |
|---|---|
| 候选结果 | 展平候选行 + 人工复核下拉 |
| Query对比 | Query 汇总 + Hit/MRR 公式 |
| 失败记录 | 管线失败与输入异常 |
| 说明 | 运行版本/数据量/评测口径 + 字段整理字典（是否保留下拉） |
| Raw数据（条件） | 超长内容分块 |

**processed 模式**（`writeProcessedWorkbook`，2307–2673）：

- 基础 9 Sheet：说明 / 核心指标 / Query明细 / 候选结果 / 同条件对比 / 新增线索 / 模块字段统计 / 失败记录 / 人工复核；
- report-model-v3/v4/v5 追加 7 Sheet：Report_Summary / Query_Person_Links / Identity_Classification / Field_Matrix / Field_Metrics / Module_Metrics / Not_Ready_Reasons；
- 仅 v4/v5 追加英文稳定 Sheet（供测试平台自动化读取）：Core Metrics / Module Quality / Field Comparison / Field Returns / Rule Snapshot / Raw；
- Raw数据 Sheet（条件）。

**导出只消费冻结的报告快照，不重新计算任何指标**；缺失值保持空单元格，不补 0、不写 `"null"`。

## 4. 使用示例

```bash
# 单 Run 导出
python3 result_to_excel.py single \
  --results-file output/20260722_tasks_v01_results.jsonl \
  --failures-file output/20260722_tasks_v01_failures.jsonl \
  --run-label candidate --system-version v1.2.0 \
  --evaluation-id eval_20260721 --output output/results_comparison.xlsx

# baseline/candidate 对比
python3 result_to_excel.py compare \
  --baseline-results-file ... --candidate-results-file ... \
  --baseline-version <commit> --candidate-version <commit> \
  --evaluation-id eval_20260721 --output output/results_comparison.xlsx

# processed 模式（通常由 Web 报告流程自动调用）
python3 result_to_excel.py processed \
  --input-file processed_export.jsonl \
  --report-model report_model.json --output report.xlsx
```

也可在 `.env` 中配置 `EXCEL_*` 后直接 `python3 result_to_excel.py single --env-file .env`。
