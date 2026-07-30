# searchTool v1.3 MVP 报告优化开发设计与开发计划

## 1. 文档信息

| 项目 | 内容 |
|---|---|
| 文档名称 | searchTool v1.3 MVP 报告优化开发设计与开发计划 |
| 文档版本 | v1.0 |
| 编写日期 | 2026-07-29 |
| 需求依据 | `docs/searchTool_v1.3_MVP_报告优化PRD.md` v1.1 |
| 视觉参考 | `docs/searchTool_v1.3_单次评测报告_Mock.html`、`docs/searchTool_v1.3_两次结果对比报告_Mock.html` |
| 当前数据库 | SQLite Schema v4 |
| 目标数据库 | SQLite Schema v4，不新增表和列 |
| 当前 ReportModel | `report-model-v4` |
| 目标 ReportModel | `report-model-v5` |
| 指标规则 | 继续使用现有 `metrics-v4` |
| 数据处理规则 | 继续使用现有 `field-processing-v5` |
| 核心原则 | 复用现有报告流程，以完成功能为主，不引入新前端框架和分页服务 |

## 2. 开发目标

### 2.1 任务目标

在不修改检索接口、身份规则和指标公式的前提下完成：

1. 将报告首屏调整为核心结论和四项核心指标；
2. 将技术元数据、普通风险和未就绪原因移到页面底部；
3. 未配置参考线、建议、成本等可选数据时不渲染对应章节；
4. 在 ReportModel 快照中保存全部 Query 和全部候选人；
5. 支持单次报告查看候选人与基准人物的模块和字段比较；
6. 支持对比报告查看两次运行的配对结果和候选人变化；
7. Web 报告按前端分段方式渲染 Query，不使用分页；
8. 静态 HTML 保留全部 Query 和候选人核心数据，不嵌入完整 Raw；
9. Web 和静态 HTML 使用同一个不可变 ReportModel 快照；
10. 保持历史 `report-model-v2/v3/v4` 报告可继续打开。

### 2.2 成功标准

- 首屏无需滚动即可看到检索成功率、命中准确率、命中完整度和非命中完整度；
- 核心百分比同时显示分子和分母；
- Query 快照数量与 Process 的 Query 数一致；
- 每个 Query 的候选人快照数量与入库 Candidate 数一致；
- HIT、NON_HIT、SUSPECTED、UNCLASSIFIED 使用正确的指标展示规则；
- Candidate Detail 失败的候选人不会从报告消失；
- 单次报告不展示版本配对；
- 未选择参考线时不出现参考线章节和 `NOT_CONFIGURED`；
- 成本字段全部未接入时不出现空成本主表；
- Web 页面不出现分页器，搜索可以命中尚未渲染的 Query 或 Candidate；
- 静态 HTML 在关闭 JavaScript 后仍可阅读核心指标和全部候选人摘要；
- 报告生成不触发任何检索 HTTP 请求；
- 现有报告、Excel 和其他页面不发生回归。

### 2.3 本期不实现

1. 不修改 `search_tool.py` 的 HTTP 调用流程；
2. 不修改身份归类规则；
3. 不修改完整度和准确度公式；
4. 不升级 SQLite Schema；
5. 不新增前端框架、图表库、缓存服务或搜索服务；
6. 不提供历史报告升级为 v5 的入口；
7. 不把 Candidate Detail 完整 Raw 写入报告快照或静态 HTML；
8. 不重新设计 Excel 内容，只保证现有导出不受影响；
9. 不实现 LLM 报告总结；
10. 不实现服务端分页。

## 3. 简化设计原则

1. 继续使用 `analysis_service.py` 构建 ReportModel；
2. 继续使用 `reports.metrics_json` 保存完整不可变报告快照；
3. 继续由 `/reports/<report_id>` 读取快照，不在打开页面时重新计算；
4. 不新增 Query 明细 API，完整 Query 数据随报告页面一次加载；
5. Web 仅减少首次 DOM 渲染数量，不减少浏览器持有的数据；
6. 静态 HTML 直接输出核心摘要和全部候选人行，详情默认折叠；
7. 模块、字段和 Evidence 只消费现有 FieldSchema 和处理结果；
8. 报告展示层不重新实现指标算法；
9. 旧 ReportModel 使用旧模板分支，新报告使用 v5 分支；
10. 优先修改现有文件，不新增业务模块文件。

## 4. 现有架构与改动边界

### 4.1 现有报告流程

```text
Run / Candidate / Raw
          ↓
Process + FieldSchema 快照
          ↓
calculate_process_metrics()
          ↓
build_report_model()
          ↓
reports.metrics_json + report_model.json
          ↓
Web 报告 / 静态 HTML / Excel
```

现有架构已经满足“不可变报告快照”的基本要求。本次不改变报告创建入口，只扩充 `build_report_model()` 生成的内容并调整展示。

### 4.2 本次目标流程

```text
Process 数据与 metrics-v4
          ↓
一次性批量读取 Query、Candidate、Review、Field Scores
          ↓
构建 report-model-v5
├── metadata
├── overview
├── query_stage_metrics
├── comparison（可选）
├── query_explorer（全部 Query / Candidate）
├── module_and_field_quality
├── optional_sections
└── diagnostics
          ↓
reports.metrics_json 不可变保存
          ↓
Web：前端分段渲染
Static HTML：全部摘要预渲染，详情折叠
```

### 4.3 不改动的内容

- `search_tool.py`；
- Raw 保存方式；
- Run、Query、Candidate 表结构；
- Process 不可变策略；
- FieldSchema 发布与快照策略；
- `metrics-v4` 正式计算口径；
- Candidate 身份自动归类和人工修正规则；
- Docker 启动方式；
- 报告创建页面的基本操作流程。

## 5. 主要修改文件

| 文件 | 主要改动 |
|---|---|
| `analysis_service.py` | ReportModel v5、Query/Candidate 快照、结构化结论、可选章节判断、静态报告数据准备 |
| `web_app.py` | v5 报告展示上下文，不新增分页 API |
| `templates/_report_content.html` | v5 报告信息架构、核心指标、Query 工作台容器、条件章节、诊断附录 |
| `templates/report_detail.html` | v5 Query 数据安全嵌入、加载状态、旧报告兼容 |
| `templates/report_static.html` | v5 静态样式、全部候选人摘要、折叠详情、打印规则 |
| `static/app.js` | Query 分段加载、搜索、筛选、展开与加载状态 |
| `static/app.css` | 新报告布局、KPI、Query 卡片、候选人表格、移动端横向滚动 |
| `tests/test_analysis_service.py` | v5 快照结构、数量、指标口径、条件章节、对比数据测试 |
| `tests/test_web_app.py` | Web 渲染、旧报告兼容、静态 HTML、条件隐藏测试 |
| `tests/test_result_to_excel.py` | 只补充 v5 ReportModel 兼容回归测试 |
| `README.md` | 新版报告入口、单次/对比报告区别、静态 HTML 说明 |

本期不创建新数据库表，不新增独立前端工程，不新增报告 API 文件。

## 6. ReportModel v5 设计

### 6.1 版本策略

在 `analysis_service.py` 中将新报告版本定义为稳定常量：

```python
REPORT_MODEL_VERSION = "report-model-v5"
```

规则：

1. 新生成且满足 `metrics-v4` 的报告写入 `report-model-v5`；
2. 已存在的 v2/v3/v4 快照保持原值；
3. 模型结构或业务含义变化时再升级版本；
4. ReportModel 版本不作为报告创建表单字段；
5. `report_id` 继续作为报告实例标识，不代替模型版本。

### 6.2 顶层结构

建议保持现有键并新增展示所需结构，避免 Excel 和旧模板大范围失效：

```json
{
  "metadata": {},
  "summary": {},
  "overview": {},
  "execution_summary": {},
  "query_stage_metrics": {},
  "comparison": {},
  "query_explorer": {},
  "module_metrics": {},
  "field_metrics": {},
  "cost_metrics": {},
  "pdl_metrics": {},
  "threshold_assessment": null,
  "diagnostics": {},
  "warnings": []
}
```

设计要求：

- 保留 Excel 仍在读取的现有键；
- 新页面优先读取 `overview`、`query_explorer` 和 `diagnostics`；
- 未满足展示条件的可选结构保存为 `null`，不生成空对象；
- 不将 `NOT_CONFIGURED` 列表保存为可展示章节。

### 6.3 Overview

```json
{
  "conclusion": {
    "level": "INFO",
    "title": "检索能力基本可用，人物资料质量仍需提升",
    "description": "本次共执行 10 个 Query……"
  },
  "core_metrics": {
    "retrieval_success": {
      "value": 0.8,
      "numerator": 8,
      "denominator": 10,
      "status": "READY"
    },
    "matched_accuracy": {},
    "matched_completeness": {},
    "nonmatched_completeness": {}
  },
  "secondary_metrics": {
    "query_count": 10,
    "has_candidates_count": 10,
    "no_candidates_count": 0,
    "candidate_count": 45,
    "primary_hit_query_count": 8,
    "pending_query_count": 0,
    "execution_failed_count": 0,
    "detail_success_count": 45,
    "detail_failure_count": 0
  },
  "blocking_alert": null
}
```

实现规则：

1. 四项核心指标复用 `calculate_process_metrics()` 的结果；
2. 不在 Overview 中重新计算指标；
3. `conclusion` 使用固定模板拼接，不调用 LLM；
4. 缺失指标不进入结论文案；
5. `blocking_alert` 只覆盖 PRD 规定的阻断问题；
6. 普通字段未接入进入 `diagnostics`，不占据首屏。

### 6.4 Query Explorer

```json
{
  "total_query_count": 10,
  "total_candidate_count": 45,
  "default_chunk_size": 20,
  "items": [
    {
      "pair_key": "person-001|FULL_NAME",
      "person_id": "person-001",
      "display_name": "Stephanie McMahon",
      "query_stage": "FULL_NAME",
      "change_category": null,
      "candidate_run": {
        "query": {},
        "candidates": []
      },
      "baseline_run": null,
      "change": null
    }
  ]
}
```

单次报告：

- `candidate_run` 保存本次 Query 和全部候选人；
- `baseline_run = null`；
- 基准人物字段比较保存在候选人字段详情中；
- 不出现版本变化分类。

对比报告：

- 以 `person_id + query_stage` 作为正式配对键；
- `candidate_run` 保存本次运行；
- `baseline_run` 保存对比运行；
- `change_category` 使用持续命中、新增命中、退化未命中、持续未命中；
- 新增线索或不可比 Query 仍保存，并写明不可比原因；
- 两侧都保存各自实际返回的全部候选人。

### 6.5 Query 快照

每个运行侧的 Query 至少保存：

```json
{
  "query_id": "case-001",
  "input_id": "case-001",
  "person_id": "person-001",
  "display_name": "Stephanie McMahon",
  "query_stage": "FULL_NAME",
  "query_status": "SUCCEEDED",
  "result_status": "HAS_CANDIDATES",
  "candidate_count": 4,
  "retrieval_success": true,
  "identity_state": "HIT_CONFIRMED",
  "primary_hit_candidate_pk": "candidate_pk",
  "task_metrics": {
    "llm_cost": null,
    "third_party_cost": null,
    "total_cost": null,
    "search_duration_ms": null,
    "pdl_called": null
  }
}
```

要求：

1. Query 顺序与输入数据顺序一致；
2. Candidate 数量来自实际 Candidate 入库记录；
3. 执行失败和无候选人 Query 仍进入快照；
4. 任务公共字段未接入时保存 `null`，不写 0；
5. Query 快照不得包含完整 Task Raw。

### 6.6 Candidate 快照

每个候选人至少保存：

```json
{
  "candidate_pk": "candidate_pk",
  "candidate_id": "candidate_id",
  "candidate_rank": 1,
  "rank_score": 0.94,
  "display_name": "Stephanie McMahon",
  "detail_status": "SUCCESS",
  "detail_error": "",
  "confidence": "HIGH",
  "identity": {
    "judgement": "HIT",
    "classification_source": "RULE",
    "is_primary_hit": true,
    "reason": "Social URL 一致",
    "evidence_summary": "LinkedIn 与基准一致"
  },
  "metrics": {
    "matched_completeness": {},
    "matched_accuracy": {},
    "nonmatched_completeness": {}
  },
  "modules": {},
  "field_comparisons": [],
  "evidence": {},
  "references": {
    "candidate_pk": "candidate_pk",
    "raw_id": "raw_id"
  }
}
```

### 6.7 Candidate 指标规则

展示层不允许自行推导指标。Candidate 快照使用当前 metrics-v4 和 FieldSchema 规则生成：

| 身份结论 | 命中完整度 | 命中准确率 | 非命中完整度 |
|---|---|---|---|
| 主 HIT | 使用现有主命中字段评分聚合结果 | 使用现有主命中字段评分聚合结果 | `null` |
| 其他 HIT | 不进入 Query 正式命中指标；可显示身份结果 | 不进入 Query 正式命中指标 | `null` |
| NOT_HIT | `null` | `null` | 使用现有非命中完整度规则 |
| SUSPECTED | `null` | `null` | 使用现有非命中完整度规则 |
| UNCLASSIFIED | `null` | `null` | 无正式结果时为 `null` |
| Detail 失败 | `null` | `null` | `null` |

实现方式：

1. 抽取一个现有指标计算可复用的私有 helper；
2. metrics-v4 聚合和 Candidate 快照共同调用该 helper；
3. 不复制第二套完整度或准确度公式；
4. 增加测试确认 Candidate 值能够反向汇总到 Query/Process 指标；
5. 不适用统一保存为 `value = null` 和明确状态，不保存成 0。

### 6.8 模块、字段与 Evidence

模块与字段快照来源：

- `processed_candidates.fields_json`；
- `processed_candidates.empty_fields_json`；
- `processed_candidates.processing_errors_json`；
- `reviews.field_scores_json`；
- 当前 Process 冻结的 FieldSchema。

规则：

1. 只将 `display_enabled = true` 的字段写入默认展示结构；
2. 字段配置关闭的 Evidence 不进入快照；
3. 已启用但接口未返回的字段记录为空值；
4. 已启用但提取失败的字段记录处理错误；
5. Evidence 不在报告代码中维护固定路径；
6. Candidate Detail 完整 Raw 不进入快照；
7. Raw 只保留现有记录引用；
8. 长文本和 JSON 值保持原类型，模板负责格式化展示。

## 7. 数据读取与快照生成

### 7.1 避免 N+1 查询

报告生成时按 Process 批量读取：

1. Query 与 Baseline Person；
2. Candidate 与 Candidate Detail 状态；
3. Processed Candidate 字段；
4. Review、身份结论和 Field Scores；
5. 当前 FieldSchema；
6. Raw 引用 ID；
7. 已计算 Query 指标。

在 Python 内按 `query_id` 和 `candidate_pk` 组装，不允许在候选人循环中逐条查询数据库。

### 7.2 建议新增的私有方法

方法仍放在 `analysis_service.py`，不创建新模块：

```text
_build_report_overview()
_load_report_candidate_rows()
_build_report_candidate_snapshot()
_build_report_query_run_snapshot()
_build_report_query_explorer()
_build_report_diagnostics()
_build_structured_conclusion()
```

职责：

- `build_report_model()` 只负责组织顶层模型；
- SQL 批量读取集中在 `_load_report_candidate_rows()`；
- Candidate 数据转换集中在 `_build_report_candidate_snapshot()`；
- 单次与对比报告共同使用 `_build_report_query_explorer()`；
- 条件展示结果在模型生成阶段确定。

### 7.3 数据一致性检查

生成快照前检查：

1. `query_explorer.total_query_count` 等于 Process Query 数；
2. 每个 Query 的 `candidate_count` 等于候选人列表长度；
3. `total_candidate_count` 等于所有 Query 候选人数量总和；
4. `primary_hit_candidate_pk` 必须存在于对应候选人列表；
5. Candidate Rank 按升序排列，缺失排名放在末尾；
6. 对比报告配对键不重复；
7. 分子、分母与现有正式指标一致。

发现不一致时停止创建新报告并返回明确错误，不保存部分 ReportModel。

## 8. 条件展示设计

### 8.1 在模型阶段生成展示开关

`optional_sections` 建议包含：

```json
{
  "show_comparison": true,
  "show_cost": false,
  "show_pdl": false,
  "show_threshold": false,
  "show_recommendation": false,
  "show_evidence": true
}
```

模板只消费开关，不重复判断复杂业务条件。

### 8.2 参考线与建议

```text
show_threshold =
    threshold_profile_id 非空
    且 configured_count > 0
    且至少一个指标可判断
```

规则：

1. 不满足条件时 `threshold_assessment = null`；
2. 不生成 `NOT_CONFIGURED` 表；
3. 没有建议配置时 `show_recommendation = false`；
4. 模板不显示“未选择参考线方案”元数据行。

### 8.3 成本与 PDL

```text
show_cost = 至少一个成本或耗时字段存在有效值
show_pdl = pdl_called 至少存在一个明确 true/false
```

全部未接入时：

- 主报告不显示空表；
- `diagnostics` 保存一条“成本与 PDL 字段暂未接入”；
- 不将缺失值按 0 统计。

### 8.4 版本对比

```text
show_comparison =
    report_type == "COMPARE"
    且 baseline_process_id 非空
    且 comparison 数据存在
```

单次报告不保存空的配对展示数据。

### 8.5 顶部阻断提示

只有以下问题进入 `overview.blocking_alert`：

- 报告生成失败；
- 正式 Query 数为 0；
- 全部 Query 执行失败；
- 身份结果完全不可用；
- 核心指标因处理错误全部无法计算。

其他问题进入 `diagnostics.items`，页面底部默认折叠。

## 9. Web 报告实现

### 9.1 页面渲染

`/reports/<report_id>` 继续一次性读取 `reports.metrics_json`：

```text
SQLite metrics_json
        ↓
Jinja 渲染 Overview 与固定章节
        ↓
query_explorer.items 使用 tojson 安全写入页面
        ↓
app.js 按段创建 Query DOM
```

不新增：

- `/api/reports/<report_id>/queries`；
- page/page_size 参数；
- 服务端分页状态；
- 额外缓存。

### 9.2 前端分段加载

首版固定规则：

- 每段 20 个 Query；
- 首次渲染第一段；
- 页面接近 Query 列表底部时加载下一段；
- 同时提供“加载更多”兜底按钮；
- 显示“已展示 20 / 100 个 Query”；
- 全部加载完成后隐藏加载按钮。

使用原生 `IntersectionObserver`；浏览器不支持时退化为“加载更多”按钮。

### 9.3 搜索与筛选

搜索和筛选直接作用于内存中的全部 `query_explorer.items`：

1. 姓名；
2. person_id；
3. query_id/input_id；
4. candidate_id；
5. query_stage；
6. 检索成功/未成功；
7. 执行失败；
8. 无候选人；
9. 疑似；
10. 待身份归类；
11. Social 冲突。

筛选后：

- 清空当前 Query DOM；
- 对完整数组过滤；
- 从过滤结果第一段重新渲染；
- 更新展示数量和总数量；
- 不重新请求后端。

### 9.4 Query 展开

Query 默认收起，异常 Query 可以默认展开：

- 执行失败；
- 无候选人；
- 退化未命中；
- 存在 Candidate Detail 失败。

展开后显示全部候选人。候选人字段详情继续按需展开，避免一次生成大量字段 DOM。

### 9.5 Web 安全

1. Query 数据使用 Jinja `tojson` 输出；
2. 原生 JavaScript 创建节点时优先使用 `textContent`；
3. 不直接使用候选人字段拼接 `innerHTML`；
4. URL 只允许现有受控详情路由；
5. Raw ID、candidate_id 和 person_id 作为文本显示；
6. 长 JSON 交给现有 JSON 展示模板，不直接执行。

## 10. 静态 HTML 实现

### 10.1 核心数据直接输出

静态 HTML 使用 Jinja 直接输出：

- 报告标题；
- 一句话结论；
- 四项核心指标；
- Query 条件指标；
- 版本配对汇总；
- 全部 Query；
- 每个 Query 的全部候选人；
- 候选人的身份结论和适用指标；
- 数据质量附录。

因此关闭 JavaScript 后仍可以完成核心阅读。

### 10.2 详情体积控制

1. Query 和 Candidate 详情使用 `<details>`；
2. 默认只展开重点 Query；
3. 模块、字段和 Evidence 默认收起；
4. 不写入 Candidate Detail 完整 Raw；
5. 不重复写入相同字段值；
6. 未启用字段和空的可选章节不输出；
7. 样式和脚本全部内联，保持单文件可分发；
8. 不截断 Query 或 Candidate 数量。

### 10.3 Web 与静态一致性

Web 和静态 HTML 必须共用：

- ReportModel v5；
- 指标格式化 helper；
- 状态中文映射；
- 条件展示开关；
- Query/Candidate 数据字段；
- 章节顺序。

只允许交互方式不同，不允许指标值和分母不同。

## 11. 模板与视觉实现

### 11.1 页面顺序

`report-model-v5` 使用以下顺序：

1. 标题与轻量元数据；
2. 一句话结论；
3. 四项核心指标；
4. 执行辅助指标；
5. Query Stage；
6. 版本配对，仅对比报告；
7. Query 与候选人工作台；
8. 模块与字段质量；
9. 成本/耗时/PDL，仅有数据时；
10. 参考线与建议，仅已配置时；
11. 数据质量和技术附录。

### 11.2 状态中文映射

| 内部状态 | 页面显示 |
|---|---|
| READY | 正常状态不显示 |
| REVIEWED | 已确认 |
| NOT_CONNECTED | 字段暂未接入 |
| NOT_CONFIGURED | 不渲染对应项 |
| NOT_APPLICABLE | 不适用 |
| HIT | 命中 |
| NOT_HIT | 不命中 |
| SUSPECTED | 疑似 |
| UNCLASSIFIED | 待身份归类 |

旧报告仍保留原展示，不批量改写历史快照。

### 11.3 数值格式

增加或复用统一模板 helper：

- 比例：`80.00%`；
- 分子/分母：`8 / 10`；
- 变化：`+5.00 个百分点`；
- 无变化：`无变化`；
- 不适用：`—` 或“不适用”；
- 成本：按 `cost_currency` 和现有精度显示；
- 耗时：毫秒转换为更易读的秒，保留原始值用于审计。

不得把 `None`、缺失值和不适用显示成 `0%`。

### 11.4 响应式

1. 主要内容宽度保持与现有平台一致；
2. 核心 KPI 在桌面端四列、窄屏两列或单列；
3. 候选人宽表使用横向滚动；
4. 单元格设置合理最小宽度；
5. 禁止通过缩窄列宽造成单字纵向换行；
6. 固定表头不得遮挡导航栏；
7. 打印模式关闭粘性定位和交互按钮。

## 12. 旧报告兼容

### 12.1 兼容策略

`_report_content.html` 按 `report_model_version` 分支：

```text
report-model-v5       → 新报告布局
report-model-v2/v3/v4 → 保留现有布局
```

不对历史 `metrics_json` 做迁移或补算。

### 12.2 报告创建策略

1. 上线后新生成的 metrics-v4 报告使用 v5；
2. 历史报告继续读取旧快照；
3. 不提供重生成入口；
4. 不覆盖旧 HTML 文件；
5. 旧 Excel 仍使用旧模型数据；
6. 新 Excel 至少能够读取 v5 保留的兼容键。

## 13. 测试设计

### 13.1 ReportModel 单元测试

在 `tests/test_analysis_service.py` 增加：

1. 单次报告生成 v5；
2. 对比报告生成 v5；
3. 快照包含全部 Query；
4. 每个 Query 包含全部候选人；
5. 15 个候选人不会被截断为 5 个；
6. Candidate Detail 失败仍保留；
7. 主 HIT 指标正确；
8. NOT_HIT/SUSPECTED 只有非命中完整度；
9. 不适用保存为 `null`；
10. 对比报告两侧候选人完整保存；
11. 配对分类正确；
12. Query/Candidate 总数一致；
13. Evidence 与 FieldSchema 开关一致；
14. Raw 完整内容未进入快照；
15. 未配置参考线时 `threshold_assessment = null`；
16. 成本未接入时 `show_cost = false`；
17. 报告生成不修改 Process、Candidate 和 Raw；
18. 报告生成不调用检索客户端。

### 13.2 Web 测试

在 `tests/test_web_app.py` 增加：

1. v5 报告首屏先出现核心指标；
2. 技术信息位于折叠附录；
3. 正常指标后不显示 `READY`；
4. 未配置参考线时无参考线章节；
5. 单次报告无版本配对；
6. 对比报告有四类人物配对；
7. 页面包含完整 Query JSON；
8. 页面无分页器；
9. 静态 HTML 包含全部 Query 和候选人摘要；
10. 静态 HTML 不包含 Candidate Detail 完整 Raw；
11. v2/v3/v4 历史报告仍能打开；
12. XSS 字符串按文本转义。

### 13.3 前端交互验收

使用浏览器验证：

1. 首段自动加载；
2. 向下浏览后继续加载；
3. “加载更多”兜底可用；
4. 搜索未渲染 Candidate ID 可以命中；
5. 按未命中、疑似、退化筛选正确；
6. Query 展开后候选人数正确；
7. 长字段和 JSON 不出现单字纵向换行；
8. 桌面和窄屏均可阅读；
9. 静态 HTML 可独立打开；
10. 打印预览无导航按钮和粘性表头问题。

### 13.4 Excel 回归

只验证：

1. v5 保留 Excel 依赖的兼容键；
2. 原有报告 Excel 可以继续导出；
3. Excel 不因 `threshold_assessment = null` 报错；
4. 本期不要求 Excel 复刻 Web 新布局。

## 14. 开发计划

本次按 4 个阶段实施，先完成数据，再完成页面，最后统一导出与验收。

### 阶段 0：契约冻结与测试准备

#### 目标

冻结 ReportModel v5 的最小字段结构和验收样本，确保后续页面不反复修改数据结构。

#### 开发内容

1. 固定 `report-model-v5` 常量；
2. 确认 Overview、Query、Candidate、Comparison、Diagnostics 结构；
3. 选取现有测试 Fixture 覆盖：
   - 单次报告；
   - 对比报告；
   - 一个 Query 多候选人；
   - Candidate Detail 失败；
   - HIT、NOT_HIT、SUSPECTED；
   - 无参考线；
   - 成本未接入；
4. 在现有测试文件中先写失败测试；
5. 冻结 Mock HTML 作为视觉参考，不作为运行依赖。

#### 完成标准

- v5 JSON 契约明确；
- P0 验收场景均有测试入口；
- 测试能够证明当前 v4 缺少全部 Query/Candidate 快照；
- 不修改数据库。

### 阶段 1：ReportModel v5 与完整快照

#### 目标

生成包含全部 Query、全部候选人、候选人指标和字段详情的不可变 v5 快照。

#### 开发内容

1. 批量读取 Query、Candidate、Processed Candidate 和 Review；
2. 抽取 Candidate 指标复用 helper；
3. 构建单次报告 Query Explorer；
4. 构建对比报告双侧 Query Explorer；
5. 生成 Overview 和结构化结论；
6. 生成条件展示开关；
7. 生成 Diagnostics；
8. Evidence 按 FieldSchema 快照进入报告；
9. Raw 只保留引用 ID；
10. 增加总数和一致性校验；
11. 保存到现有 `reports.metrics_json` 和 `report_model.json`。

#### 完成标准

- 单次和对比报告均生成 `report-model-v5`；
- Query 和 Candidate 一个不少；
- 指标值与 metrics-v4 一致；
- 未配置章节保存为 `null` 或关闭状态；
- 报告生成不触发 HTTP；
- ReportModel 单元测试通过。

### 阶段 2：Web 报告页面

#### 目标

完成新版信息架构和 Query 工作台，达到日常查看要求。

#### 开发内容

1. 增加 v5 模板分支；
2. 将执行摘要和核心指标移动到首屏；
3. 增加一句话结论；
4. 增加 Query Stage 展示；
5. 对比报告增加人物配对；
6. 增加 Query 与候选人工作台；
7. 实现每段 20 个 Query 的前端分段加载；
8. 实现搜索、筛选和加载状态；
9. 增加 Candidate 模块、字段和 Evidence 下钻；
10. 参考线、建议、成本按开关渲染；
11. 将风险和技术信息移至底部；
12. 完成响应式和长表格处理；
13. 保留 v2/v3/v4 模板分支。

#### 完成标准

- 首屏核心指标突出；
- 页面无分页器；
- 未渲染数据仍可搜索；
- Query 展开后候选人数正确；
- 无空参考线、空成本表和多余 `READY`；
- 旧报告仍能打开；
- Web 测试和浏览器验收通过。

### 阶段 3：静态 HTML、集成验收与文档

#### 目标

保证静态报告、Web 报告和现有导出使用同一口径，并完成交付。

#### 开发内容

1. 更新静态 HTML v5 模板；
2. 预渲染核心指标、全部 Query 和全部候选人摘要；
3. 模块、字段和 Evidence 使用折叠详情；
4. 排除完整 Raw、空章节和重复字段数据；
5. 完成打印样式；
6. 验证单次和对比静态报告；
7. 验证 Excel v5 兼容；
8. 运行全量测试；
9. 使用真实 Process 新生成报告验收；
10. 更新 README 和指标说明。

#### 完成标准

- 静态 HTML 可独立打开；
- JavaScript 关闭后核心数据仍可阅读；
- 全部 Query/Candidate 摘要完整；
- Web 与 HTML 核心指标一致；
- Excel 不回归；
- 全量自动化测试通过；
- 文档与实际行为一致。

## 15. 实施顺序与依赖

```text
阶段 0：契约与失败测试
          ↓
阶段 1：ReportModel v5
          ↓
阶段 2：Web 页面
          ↓
阶段 3：Static HTML + 集成验收
```

依赖原则：

- 阶段 1 完成前不正式开发 Query 工作台；
- Web 和静态 HTML 都只能消费已冻结的 v5 快照；
- 阶段 2 不改变指标算法；
- 阶段 3 不再修改业务口径，只处理导出、兼容和问题修复。

## 16. 风险与缓解方案

### 16.1 ReportModel 体积增大

风险：全部 Query、Candidate 和字段比较进入快照后，`metrics_json` 变大。

缓解：

- 不写完整 Raw；
- 只写展示启用字段；
- Evidence 不重复保存；
- 使用一次批量查询；
- 静态 HTML 不重复嵌入快照和完整 DOM 详情。

### 16.2 指标重复计算产生偏差

风险：报告为了展示 Candidate 指标复制一套公式，与 metrics-v4 不一致。

缓解：

- 抽取共用私有 helper；
- ReportModel 只消费 helper 结果；
- 增加 Candidate → Query → Process 反向核对测试。

### 16.3 前端一次持有数据较多

风险：100 个 Query、较多 Candidate 时页面初始化变慢。

缓解：

- 数据一次加载但 DOM 分段创建；
- 每段 20 个 Query；
- 字段详情按展开创建；
- 搜索在内存数组中执行；
- 不引入分页接口和复杂状态同步。

### 16.4 旧报告模板回归

风险：修改共用 `_report_content.html` 影响 v2/v3/v4。

缓解：

- 明确按 ReportModel 版本分支；
- 保留旧分支；
- 增加历史报告 Web 与静态 HTML 回归测试；
- 不修改历史快照。

### 16.5 静态 HTML 过大

风险：候选人和字段较多时文件体积增加。

缓解：

- 全部候选人摘要直接输出；
- 字段详情折叠；
- Raw 不嵌入；
- 空字段和空章节不输出；
- 不以截断候选人作为优化手段。

## 17. 回滚方案

1. 旧 `report-model-v2/v3/v4` 模板分支始终保留；
2. 如果 v5 页面异常，可以暂时停止新报告生成，不影响历史报告；
3. 新报告写入独立 report_id 和目录，不覆盖旧报告；
4. 本期无数据库迁移，不需要执行数据库回滚；
5. Process、Candidate、Raw 未被修改，可在修复后重新生成新报告；
6. 回滚时仅恢复 ReportModel 版本选择和 v5 模板分支。

## 18. 最终验收清单

- [ ] ReportModel v5 结构与文档一致；
- [ ] 单次报告与基准人物字段比较可查看；
- [ ] 对比报告两次运行结果可查看；
- [ ] 全部 Query 和候选人进入快照；
- [ ] Candidate Detail 失败候选人仍保留；
- [ ] 四项核心指标首屏展示；
- [ ] 百分比、分子和分母格式正确；
- [ ] HIT 与非命中指标职责正确；
- [ ] 单次报告无版本变化空章节；
- [ ] 未配置参考线时完全隐藏；
- [ ] 成本未接入时主报告无空表；
- [ ] 风险和技术信息位于底部；
- [ ] Web 前端分段加载，无分页器；
- [ ] 搜索覆盖完整快照；
- [ ] 静态 HTML 包含全部候选人摘要；
- [ ] 静态 HTML 不嵌入完整 Raw；
- [ ] Evidence 与 FieldSchema 快照一致；
- [ ] Web 与静态 HTML 核心指标一致；
- [ ] 历史 v2/v3/v4 报告仍可打开；
- [ ] 报告生成不调用检索接口；
- [ ] 自动化测试和浏览器验收通过；
- [ ] README 与指标说明更新完成。
