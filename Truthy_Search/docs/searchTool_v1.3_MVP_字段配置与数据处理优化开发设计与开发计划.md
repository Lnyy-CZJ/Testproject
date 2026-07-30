# searchTool v1.3 MVP 字段配置与数据处理优化开发设计与开发计划

## 1. 文档信息

| 项目 | 内容 |
|---|---|
| 文档名称 | searchTool v1.3 MVP 字段配置与数据处理优化开发设计与开发计划 |
| 文档版本 | v1.0 |
| 编写日期 | 2026-07-29 |
| 需求依据 | `docs/searchTool_v1.3_MVP_字段配置与数据处理优化PRD.md` v1.1 |
| 当前数据库 | SQLite Schema v4 |
| 目标数据库 | SQLite Schema v4，不新增业务表 |
| 当前处理规则 | `field-processing-v4` |
| 目标处理规则 | `field-processing-v5` |
| 当前指标规则 | `metrics-v3` |
| 目标指标规则 | `metrics-v4` |
| 当前报告模型 | `report-model-v3` |
| 目标报告模型 | `report-model-v4` |
| 核心原则 | 复用现有架构、Raw 不变、旧快照不变、无成本重处理不请求接口 |

## 2. 开发目标

### 2.1 任务目标

在不修改顺序检索流程的前提下完成：

1. 将字段配置从“字段提取配置”扩展为“提取、展示、基准对比、版本对比和指标参与”的统一配置；
2. 按 Task、Candidate、Insights、Photos、Profile、Social、Summary 展示字段树；
3. 登记 PRD 中已确认的 `ui_sections` 首版字段目录；
4. 支持 Profile `section.title + item.label` 动态字段提取；
5. 支持模块与子字段开关；
6. 支持基准人物字段与主命中候选字段逐项对比；
7. 支持 `presence` 和 `semantic_text_lite` 比较；
8. 按启用字段等权计算模块及整体完整度、准确度；
9. 将身份结果、基准资料质量、版本回归拆分展示；
10. 将字段对比结果同步到 Web 报告、静态 HTML 和 Excel。

### 2.2 成功标准

- 字段配置页能按模块查看全部已登记字段；
- 每个子字段可独立控制提取、展示、基准对比、版本对比、身份、完整度和准确度；
- Task、Candidate 不进入基准人物资料对比；
- `ui_sections` 业务模块可进入基准资料对比；
- Profile 动态标签可配置为稳定原子字段；
- 主命中候选人与 Baseline 的每个启用字段都有可解释对比结果；
- 复杂 JSON 不再因对象结构不同被错误计入准确率；
- 地点、职位、教育和文本描述可使用本地轻量语义相似度；
- 报告显示模块分数、字段分数、分子、分母和原因；
- 旧 FieldSchema、Process、Report 可继续打开；
- 无成本重处理期间检索 HTTP 调用次数为 0；
- 自动化测试和真实历史 Run 验收通过。

### 2.3 本次不实现

- 新的检索接口或请求流程；
- LLM、Embedding 或外部语义服务；
- 图片视觉相似算法；
- 字段权重编辑；
- 多用户审核；
- 通用表达式、JSONPath 引擎或用户脚本；
- 成本字段正式计算，直至接口路径确认；
- 自动覆盖旧字段配置、Process 或报告。

## 3. 简化设计原则

1. 不新增第二套字段定义表，继续使用 `field_schemas.definitions_json`；
2. 不新增字段评分表，继续使用 `reviews.field_scores_json`；
3. 不新增模块配置表，模块开关发布时展开为每个子字段的最终开关；
4. 不改 Raw、Run、Candidate 表；
5. 不引入前端框架，继续使用 Flask、Jinja、原生 JavaScript；
6. 动态 Profile 只实现确定的 `section + label` 选择器，不建设通用查询语言；
7. 版本对比复用现有 `compare_processes()`，不建设第二套报告流程；
8. 新规则使用新版本号，旧规则保持原样。

## 4. 现有架构与改动边界

### 4.1 复用现有流程

```text
Raw / Run / Candidate
        ↓
FieldSchema Version
        ↓
process_run()
        ↓
processed_queries / processed_candidates
        ↓
reviews + field_scores_json
        ↓
calculate_process_metrics()
        ↓
ReportModel
        ↓
Web / Static HTML / Excel
```

本次只增强 FieldSchema 到 ReportModel 之间的数据处理，不改：

- `search_tool.py` 的接口调用顺序；
- Raw 保存方式；
- Run 和 Candidate 入库方式；
- Process 不可变策略；
- Report 快照不可变策略；
- Docker 启动方式。

### 4.2 主要修改文件

| 文件 | 主要改动 |
|---|---|
| `analysis_service.py` | 字段配置兼容、字段提取、Profile 选择器、语义比较、字段评分、模块指标、版本对比 |
| `web_app.py` | 字段树上下文、配置发布校验、基准对比与报告下钻数据 |
| `templates/field_schemas.html` | 模块树、字段开关、筛选和配置预览 |
| `templates/field_comparison_matrix.html` | 双侧字段映射、启用状态和问题提示 |
| `templates/process_detail.html` | 基准资料质量摘要与下钻入口 |
| `templates/candidate_detail.html` | 基准值与候选值逐字段展示 |
| `templates/_report_content.html` | 身份、资料质量、版本回归三个报告分区 |
| `static/app.js` | 模块批量开关、字段筛选和配置状态提示 |
| `static/app.css` | 字段树与对比表样式 |
| `result_to_excel_builder.mjs` | 新增字段对比、模块质量和规则说明 Sheet |
| `tests/test_analysis_service.py` | 提取、比较、指标和兼容测试 |
| `tests/test_web_app.py` | 字段配置、对比页和报告测试 |
| `tests/test_result_to_excel.py` | Excel 快照与字段对比测试 |
| `README.md` | 新字段配置和无成本重处理说明 |

不新建业务模块文件，优先在现有文件中精准修改。

## 5. FieldSchema v3 设计

### 5.1 不升级数据库 Schema

`field_schemas` 已使用 `definitions_json` 保存不可变字段定义，因此本次只升级 JSON 内容和校验规则：

```text
SQLite Schema：继续使用 v4
FieldSchema 内容版本：v3
```

数据库不增加列、不迁移历史行。旧定义在读取时补默认值，新发布定义保存完整 v3 属性。

### 5.2 字段定义结构

```json
{
  "field_key": "summary_location",
  "display_name": "Location",
  "module": "Summary",
  "value_scope": "CANDIDATE",
  "source_path": "ui_sections.summary.data.location",
  "source_type": "PATH",
  "source_options": {},
  "baseline_field_key": "summary_location",
  "normalizer": "trim_text",
  "compare_mode": "semantic_text_lite",
  "enabled": true,
  "display_enabled": true,
  "baseline_compare_enabled": true,
  "run_compare_enabled": true,
  "identity_enabled": false,
  "completeness_enabled": true,
  "accuracy_enabled": true,
  "similarity_threshold": 0.6,
  "missing_policy": "EMPTY"
}
```

首版不保存可编辑 `weight`；计算时所有启用字段固定权重为 `1`。

### 5.3 Profile 动态字段

Profile 不引入通用 JSONPath 过滤，使用一个受控选择器：

```json
{
  "field_key": "profile_identity_full_name",
  "display_name": "Identity / Full Name",
  "module": "Profile",
  "source_path": "ui_sections.profile.data.sections",
  "source_type": "PROFILE_ITEM",
  "source_options": {
    "section": "Identity",
    "label": "Full Name"
  }
}
```

处理规则：

1. 在 `sections` 中查找 `title` 规范化后相同的分组；
2. 在分组 `items` 中查找 `label` 规范化后相同的项目；
3. 返回项目的 `value`；
4. 找不到时按 `missing_policy` 记录 EMPTY 或 ERROR；
5. 多个相同标签时保留数组，并记录 `DUPLICATE_PROFILE_ITEM` 提示；
6. 未登记的新标签仍保留在完整 `profile_sections` 和 Raw 中。

### 5.4 开关落地

每个字段保存最终生效开关：

| 开关 | 处理行为 |
|---|---|
| `enabled` | 决定是否提取 |
| `display_enabled` | 决定详情、报告、Excel是否默认展示 |
| `baseline_compare_enabled` | 决定是否执行 Baseline 对比 |
| `run_compare_enabled` | 决定是否进入版本对比 |
| `identity_enabled` | 决定是否作为身份规则证据 |
| `completeness_enabled` | 决定是否进入完整度分母 |
| `accuracy_enabled` | 决定是否进入准确度分母 |

模块级开关只用于页面批量操作。发布 FieldSchema 时，将模块选择展开写入每个字段，不额外保存模块状态。

### 5.5 旧配置兼容

旧定义读取时按以下规则补齐：

| 新属性 | 旧配置默认值 |
|---|---|
| `source_type` | `PATH` |
| `source_options` | `{}` |
| `display_enabled` | `enabled` |
| `baseline_compare_enabled` | 原 `scoring_role` 含 completeness、accuracy 或 identity 时为 true |
| `run_compare_enabled` | `enabled` |
| `identity_enabled` | 原 `scoring_role` 含 identity |
| `completeness_enabled` | 原 `scoring_role` 含 completeness |
| `accuracy_enabled` | 原 `scoring_role` 含 accuracy |
| `similarity_threshold` | `0.6` |

兼容逻辑只在内存中补齐，不回写旧 FieldSchema。

### 5.6 发布校验

发布新配置时必须校验：

- `field_key` 唯一；
- module、scope、compare_mode、source_type 为允许枚举；
- PATH 字段必须有合法 `source_path`；
- PROFILE_ITEM 必须有 section 和 label；
- 开启基准对比必须填写 `baseline_field_key`；
- 开启准确度不能使用 `presence`；
- 完整复杂对象不能使用 `exact + accuracy_enabled`；
- `identity_enabled` 首版仅允许 Social URL 和照片相似度；
- `similarity_threshold` 范围为 0 到 1；
- 成本预留字段没有正式路径时保持禁用。

校验失败时不创建新 FieldSchema。

## 6. 首版字段目录

### 6.1 目录来源

字段目录以 PRD 第 5.1.1 节为准，来源为：

```text
GetTaskCandidateDetail.ui_sections
```

首版将字段定义合并进现有默认配置的新版本，不创建额外目录服务。

### 6.2 默认状态

| 字段类型 | 提取 | 展示 | 基准对比 | 版本对比 | 完整度/准确度 |
|---|---:|---:|---:|---:|---:|
| Task / Candidate | 开 | 开 | 关 | 开 | 关 |
| `ui_sections` 状态和原始容器 | 开 | 开 | 关 | 开 | 关 |
| `ui_sections` 原子子字段 | 开 | 开 | 可配置 | 开 | 默认关 |
| Social URL | 开 | 开 | 开 | 开 | 开 |
| Photos Identity Match Rate | 开 | 开 | 开 | 开 | 身份开，质量默认关 |
| 成本预留字段 | 关 | 显示为待接入 | 关 | 关 | 关 |

发布后由测试人员通过字段配置开关选择正式参与完整度和准确度的字段。

### 6.3 动态字段发现

首版不自动发布未知字段，只做发现：

1. 从选定 Baseline 和最新 Process 收集未登记的 `ui_sections` 子键；
2. Profile 以 `section.title + item.label` 形成建议字段；
3. Insights Item 以实际子键形成建议字段；
4. 字段配置页显示“待配置字段”；
5. 用户复制现有配置并选择启用后，发布为新版本。

发现结果即时聚合，不新增数据库表。

## 7. 字段提取与比较设计

### 7.1 提取结果

继续写入：

- `processed_queries.fields_json`；
- `processed_candidates.fields_json`；
- `empty_fields_json`；
- `processing_errors_json`。

仅 `enabled=true` 的字段执行提取。`display_enabled=false` 不影响保存和计算。

### 7.2 基准字段映射

基准对比按定义中的映射执行：

```text
Baseline.fields_json[baseline_field_key]
              ↕
ProcessedCandidate.fields_json[field_key]
```

适用条件：

1. Query 已关联 Baseline Person；
2. 候选人 Detail 成功；
3. 候选人已由 RULE 或 MANUAL 终判；
4. 只有 `is_primary_hit=1` 的候选人进入 Query 正式基准质量；
5. 其他候选人的字段返回率仍正常统计。

### 7.3 字段评分结构

继续保存在 `reviews.field_scores_json`：

```json
{
  "summary_location": {
    "baseline_field_key": "summary_location",
    "baseline_available": true,
    "baseline_value": "Redmond, Washington, USA",
    "returned_nonempty": true,
    "returned_value": "Redmond, Washington, United States",
    "compare_mode": "semantic_text_lite",
    "completeness_score": 1.0,
    "accuracy_score": 0.82,
    "comparison_status": "READY",
    "reason_code": "SEMANTIC_SIMILARITY",
    "review_note": ""
  }
}
```

大对象只保存原值引用所需摘要；完整值继续从 Baseline 和 Process 字段读取，避免重复放大数据库。

### 7.4 比较模式

| 模式 | 完整度 | 准确度 |
|---|---|---|
| `presence` | 候选值非空为 1，否则 0 | 不计算 |
| `exact` | 非空为 1，否则 0 | 完全相同为 1，否则 0 |
| `normalized_text` | 非空为 1，否则 0 | 规范化后相同为 1，否则 0 |
| `set` | 交集数 / 基准集合数 | 交集数 / 候选集合数 |
| `url_set` | URL 规范化后计算集合覆盖 | URL 规范化后计算集合精确度 |
| `semantic_text_lite` | 非空为 1，否则 0 | 返回 0 到 1 相似度 |
| `manual` | 可按 presence 计算 | 不自动计算 |

基准为空或该人物未将字段标记为 available 时，不进入该人物正式分母。

### 7.5 `semantic_text_lite`

仅使用 Python 标准库：

1. Unicode NFKC；
2. `casefold()`；
3. 标点转空格、合并空白；
4. 完全一致返回 `1.0`；
5. 一方包含另一方且较短文本长度达到 4，返回至少 `0.8`；
6. 英文和有空格文本使用词元集合 Jaccard；
7. 无空格文本使用连续双字符集合 Jaccard；
8. 最终分数取包含分与 Jaccard 的较大值；
9. 分数低于字段阈值时保存 `BELOW_SIMILARITY_THRESHOLD`，但不丢弃原分数。

不使用相似度替代 Social 冲突或照片身份规则。

### 7.6 身份规则

沿用 v4 优先级：

1. 同平台 Social URL 冲突 → NOT_HIT；
2. Social URL 一致 → HIT；
3. Photos Identity Match Rate >= 80% → HIT；
4. Social 和照片都无证据 → SUSPECTED；
5. 其他 → NOT_HIT。

字段开关只决定证据是否启用，不改变上述优先级。

## 8. 指标规则 metrics-v4

### 8.1 指标分区

metrics-v4 返回三个独立分区：

```json
{
  "identity_metrics": {},
  "baseline_quality_metrics": {},
  "regression_metrics": {}
}
```

兼容保留现有顶层指标键，供旧模板和 Excel 读取。

### 8.2 身份指标

沿用现有：

- 有候选人率；
- 检索成功率；
- 主命中 Query 数；
- 无命中 Query 数；
- 待身份判断 Query / Candidate 数；
- Social Match、Social Conflict、Photo Match、Suspected 数。

### 8.3 基准资料质量

仅统计主命中候选人。

单 Query：

```text
字段完整度 = 字段 completeness_score
字段准确度 = 字段 accuracy_score

模块完整度 = 启用完整度且 Baseline 可用字段分数平均值
模块准确度 = 启用准确度且可评分字段分数平均值

人物总完整度 = 五个模块所有有效完整度字段等权平均
人物总准确度 = 五个模块所有有效准确度字段等权平均
```

Run：

```text
Run 模块完整度 = 有正式模块完整度的主命中 Query 平均
Run 模块准确度 = 有正式模块准确度的主命中 Query 平均
Run 总完整度 = 有正式人物完整度的主命中 Query 平均
Run 总准确度 = 有正式人物准确度的主命中 Query 平均
```

每个指标必须返回：

- `numerator`；
- `denominator`；
- `value`；
- `status`；
- `reason_codes`；
- `reasons`。

### 8.4 非命中候选人

非命中候选人不与 Baseline 计算“准确度”，只统计：

- 字段返回率；
- 模块返回率；
- 非命中资料完整度；
- Social 冲突等身份原因。

避免把已确认不是目标人物的资料差异误解为准确度错误。

### 8.5 版本回归

复用 `compare_processes()`：

1. 相同 Evaluation、输入人物、Query Stage、Baseline、FieldSchema 时为正式可比；
2. FieldSchema 不同时只展示共同 `field_key` 的预览变化，并标记 `NOT_COMPARABLE_SCHEMA`；
3. Task 字段按 Query 聚合；
4. Candidate 和模块字段按成功 Candidate 聚合；
5. 输出基准值、候选值、Delta、变化方向；
6. 仅 `run_compare_enabled=true` 的字段参与。

首版版本回归以字段返回率、模块返回率和已有质量指标变化为主，不做逐个候选人的跨 Run 身份配对。

## 9. ReportModel v4

### 9.1 报告结构

```text
执行摘要
├── 检索执行
├── 身份命中
└── 配置与数据状态

基准人物资料质量
├── 五模块完整度/准确度
├── 字段级分子分母
└── 人物案例下钻

版本回归
├── Task
├── Candidate
└── 五模块变化
```

### 9.2 人物案例

每个主命中 Query 展示：

| 模块 | 字段 | 基准值 | 检索候选值 | 完整度 | 准确度 | 状态/原因 |
|---|---|---|---|---:|---:|---|

复杂值默认显示：

- 对象：键数量和“查看 JSON”；
- 数组：元素数量和前几个样本；
- URL：可点击链接；
- 长文本：摘要和展开入口。

### 9.3 历史报告

- report-model-v1/v2/v3 按原模板兼容展示；
- report-model-v4 只由 metrics-v4 生成；
- 打开历史报告不重新计算；
- 新 Process 不将旧报告自动变为新模型；
- 字段配置变化后，相关旧报告只按现有规则标记 STALE。

## 10. Web 设计

### 10.1 字段配置页

页面保持服务端渲染，布局为：

```text
配置版本与操作
字段搜索 / 模块筛选 / 角色筛选

执行与候选信息
  Task
  Candidate

人物资料模块
  Insights
  Photos
  Profile
  Social
  Summary
```

每个字段行显示：

- 展示名称和 field_key；
- 候选来源路径；
- Baseline 映射；
- normalizer / compare_mode；
- 提取、展示、基准对比、版本对比、身份、完整度、准确度开关；
- 配置问题状态。

模块开关用于批量勾选当前模块，不保存额外模块对象。

### 10.2 字段矩阵

在现有字段矩阵上增加：

- Baseline 字段样本；
- Candidate 字段样本；
- 两侧数据形状；
- Baseline 映射；
- 各开关状态；
- `READY`、`WARNING`、`ERROR`；
- 未登记动态字段建议。

ERROR 阻止正式发布；WARNING 允许发布但要求确认。

### 10.3 Process 详情

新增：

- 身份指标卡；
- 五个模块质量卡；
- 字段生效数量；
- “查看基准字段对比”入口；
- “查看版本回归”入口。

### 10.4 Candidate 详情

在主命中候选人详情中新增“基准资料对比”：

- 只显示 `baseline_compare_enabled=true` 的字段；
- 默认按模块折叠；
- 基准值与候选值并列；
- 显示完整度、准确度、相似度和原因；
- 保留人工覆写字段评分能力；
- 非主命中候选人提示“不进入正式基准资料指标”。

## 11. Excel 设计

在现有导出中增加或调整：

| Sheet | 内容 |
|---|---|
| `Core Metrics` | 身份、资料质量、版本回归核心指标 |
| `Module Quality` | 五个模块的完整度、准确度、分子分母 |
| `Field Comparison` | Query、人物、主命中、字段、基准值、候选值、评分和原因 |
| `Field Returns` | 全部成功候选人的字段返回率 |
| `Rule Snapshot` | FieldSchema、处理、指标、报告规则版本 |
| `Raw` | 继续保存超长 JSON 分块引用 |

旧 ReportModel 继续按旧格式导出。

## 12. 异常与状态规则

| 场景 | 状态/处理 |
|---|---|
| Query 未关联 Person | `BASELINE_NOT_LINKED` |
| Person 不在 Baseline | `BASELINE_PERSON_NOT_FOUND` |
| Baseline 字段未标记可用 | `BASELINE_FIELD_UNAVAILABLE`，不进分母 |
| Candidate 字段为空 | 完整度 0；准确度不进分母 |
| 字段提取失败 | `FIELD_EXTRACTION_ERROR` |
| Profile 标签重复 | `DUPLICATE_PROFILE_ITEM` |
| 复杂对象误设 exact accuracy | 发布 ERROR |
| 语义分低于阈值 | 保存分数并标记 `BELOW_SIMILARITY_THRESHOLD` |
| 没有启用完整度字段 | `NOT_APPLICABLE / NO_COMPLETENESS_FIELDS` |
| 没有可评分准确度字段 | `NOT_APPLICABLE / NO_ACCURACY_FIELDS` |
| 身份未完成 | 正式基准质量 `NOT_READY / IDENTITY_PENDING` |
| 成本路径未接入 | `NOT_CONNECTED` |

空值不是处理错误，也不需要人工补字段。

## 13. 测试设计

### 13.1 单元测试

- FieldSchema v1/v2 读取兼容；
- FieldSchema v3 发布校验；
- PATH 和 PROFILE_ITEM 提取；
- Profile 缺失、重复标签；
- `presence`、`exact`、`normalized_text`、`set`、`url_set`；
- `semantic_text_lite` 的一致、包含、相似、不相似和空值；
- Social / Photos 身份优先级；
- 模块和整体等权聚合；
- 非命中候选人不计算准确度；
- Task/Candidate 不进入基准资料质量；
- 动态字段发现不修改 Raw。

### 13.2 集成测试

- 发布新字段配置；
- 使用历史 Run 无成本重处理；
- 生成主命中字段对比；
- 生成 metrics-v4；
- 生成 report-model-v4；
- Web 下钻基准值和候选值；
- Excel 字段对比；
- 版本对比；
- 旧配置、旧 Process、旧报告兼容。

### 13.3 真实数据验收

使用 `candidatetest2` 数据副本：

1. Raw、Run、Candidate 数量处理前后不变；
2. 外部检索调用次数为 0；
3. 10 个人物均能找到对应 Baseline；
4. Social 与照片规则身份结论可解释；
5. 主命中能生成五模块字段对比；
6. 关闭某子字段后，新 Process 指标分母同步变化；
7. 旧报告数值不变化；
8. 新报告能下钻到字段级基准值和候选值。

## 14. 开发阶段与计划

### 阶段 0：基线冻结与兼容准备

目标：固定当前行为，防止优化时破坏旧数据。

开发内容：

1. 冻结 `field-processing-v4`、`metrics-v3`、`report-model-v3` 回归夹具；
2. 补充当前 FieldSchema 兼容测试；
3. 固定 `candidatetest2` 脱敏验收快照；
4. 记录当前字段数、Candidate 数、指标与报告结果；
5. 明确新版本常量与路由兼容策略。

验收：

- 当前全量测试通过；
- 旧报告可打开和导出；
- 基线快照可重复验证。

### 阶段 1：FieldSchema v3 与字段目录

目标：让配置完整表达字段职责。

开发内容：

1. 扩展字段定义属性和默认值；
2. 增加发布校验；
3. 加入 PRD 的 `ui_sections` 字段目录；
4. 实现 PROFILE_ITEM 受控选择器；
5. 实现动态字段发现；
6. 保持旧配置只读兼容。

验收：

- 新配置可发布；
- 旧配置可读取；
- Profile 原子字段可正确提取；
- 未登记字段可显示为建议。

### 阶段 2：字段比较与无成本重处理

目标：生成可解释的 Baseline 与 Candidate 字段评分。

开发内容：

1. 增加 `presence`；
2. 实现 `semantic_text_lite`；
3. 按 `baseline_field_key` 对比两侧值；
4. 扩展 `field_scores_json`；
5. 应用完整度、准确度和身份开关；
6. 升级为 `field-processing-v5`；
7. 验证无成本重处理不调用接口。

验收：

- 每个启用字段有基准值、候选值、分数、状态和原因；
- 复杂对象不会误计准确度；
- 旧 Process 不变化；
- 新 Process 可重复生成。

### 阶段 3：字段配置 Web 与对比工作台

目标：测试人员能在 Web 完成字段选择和结果核对。

开发内容：

1. 字段树、搜索和筛选；
2. 模块批量开关与子字段开关；
3. 双侧字段矩阵；
4. 发布前 ERROR/WARNING；
5. Candidate 主命中基准对比；
6. Process 对比入口。

验收：

- 页面可配置并发布新版本；
- 开关在新 Process 中生效；
- 能查看基准值和候选值；
- 页面不直接铺开超长 JSON。

### 阶段 4：metrics-v4 与 report-model-v4

目标：报告清晰区分身份、资料质量和版本回归。

开发内容：

1. 五模块等权完整度与准确度；
2. 人物、Query、Run 聚合；
3. 非命中资料返回率；
4. 版本字段变化；
5. ReportModel v4；
6. Web、静态 HTML 报告更新。

验收：

- 每个指标有分子、分母、状态和原因；
- Task/Candidate 不进入基准质量；
- 无评分字段显示 N/A 而非 0；
- 历史报告继续按旧模型展示。

### 阶段 5：Excel、集成验收与文档

目标：完成导出与端到端交付。

开发内容：

1. Excel 新 Sheet；
2. 真实历史数据副本重处理；
3. 全量自动化测试；
4. Docker 构建与健康检查；
5. README、字段配置和报告使用说明；
6. 记录验收数据和已知限制。

验收：

- Web、HTML、Excel 数字一致；
- Docker `5002` 健康；
- 全量测试通过；
- 不产生检索接口费用；
- 文档可指导测试人员独立操作。

## 15. 依赖关系

```text
阶段 0
  ↓
阶段 1 FieldSchema
  ↓
阶段 2 提取与比较
  ↓
阶段 3 Web 配置 ──┐
                  ├→ 阶段 4 指标与报告
                  ↓
              阶段 5 集成与文档
```

阶段 3 和阶段 4 在阶段 2 完成后可局部并行，但首版建议按顺序验收，减少指标与页面同时变化造成的排查成本。

## 16. 风险与控制

| 风险 | 控制措施 |
|---|---|
| 字段开关过多导致页面复杂 | 模块折叠、批量开关、默认只显示常用列 |
| 动态 Profile 标签不稳定 | 使用 section + label 选择器，未登记字段只提示不自动发布 |
| 语义规则误判 | 保留原值、相似度、阈值和原因，允许人工覆写 |
| 指标分母再次混乱 | Task、Candidate、主命中、非命中分别固定分母 |
| 配置变化影响历史报告 | 新版本、新 Process、新报告；旧快照不重算 |
| 复杂 JSON 体积过大 | 字段评分保存摘要，完整值从 Process / Baseline 读取 |
| 成本字段没有接口路径 | 保持 NOT_CONNECTED，不填 0、不进入正式指标 |
| 版本对比配置不同 | 仅共同字段预览，正式结果标记不可比 |

## 17. 完成定义

本需求完成必须同时满足：

1. PRD 验收标准全部通过；
2. 新字段配置可由 Web 发布；
3. 历史 Run 可无成本生成 field-processing-v5；
4. 主命中可生成 Baseline 与 Candidate 字段对比；
5. metrics-v4 和 report-model-v4 可生成并解释；
6. Web、静态 HTML、Excel 使用同一快照；
7. 旧数据兼容；
8. 自动化测试通过；
9. Docker 服务健康；
10. 使用文档与验收记录完成。

