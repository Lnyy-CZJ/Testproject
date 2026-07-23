# searchTool 结果处理与常态化对比 PRD v1.2

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 产品名称 | searchTool 结果处理与常态化对比工具 |
| 文档版本 | v1.2 |
| 需求阶段 | 第二阶段 |
| 上游数据 | searchTool 生成的 `results.jsonl`、`failures.jsonl` |
| 输出产物 | 可用于人工复核和版本对比的 Excel 工作簿 |
| 依据文档 | 《人际关系检索能力测试方案》《检索功能常态化测试方案与方法》 |
| 口径优先级 | 两份方案冲突时，以《检索功能常态化测试方案与方法》为准 |

## 2. 背景

第一阶段 searchTool 已能按照以下链路批量采集每条 Query 的前 5 名候选人，并将完整 `ui_sections` 保存到 JSONL：

```text
CreateIntentTask
  → GetTask（每 5 秒轮询）
  → ListTaskCandidates（Top 5）
  → GetTaskCandidateDetail（完整 ui_sections）
  → results.jsonl / failures.jsonl
```

JSONL 适合保留原始结构，但不便于测试人员直接查看、筛选和比较。尤其在检索能力优化前后，需要用相同 Query 对比基线版本和候选版本的候选排名、返回字段、链路失败及逐案例变化。

第二阶段需要增加一个独立的结果处理工具，将一个或两个 searchTool 输出目录转换为 Excel。该工具只负责数据提取、对齐和展示，不重新请求接口，也不修改原始 JSONL。

## 3. 产品目标

1. 将 `results.jsonl` 中每条 Query 的 Top 5 候选人展开为结构化 Excel 行。
2. 完整提取指定的 `insights`、`photos`、`profile`、`social` 和 `summary` 字段。
3. 使用稳定的 `input_id/query_id` 对齐基线版本与候选版本结果。
4. 同时纳入 `failures.jsonl`，区分接口链路失败、成功但无候选人和正常返回。
5. 为人工身份判定、字段复核、失败归因和前后版本差异分析提供统一表格。
6. 保留完整嵌套数据，避免 Excel 扁平化过程丢失未知或新增字段。

## 4. 核心原则

### 4.1 评测单位

- `Person`：金标中的目标人物，一个人物可对应多条 Query。
- `Query`：使用一组固定线索发起的一次检索，使用 `query_id` 标识。
- `Run`：某一系统版本对某条 Query 的一次实际执行。
- `Candidate`：某次 Run 返回的单个候选人，当前只处理 Top 5。

searchTool 当前使用 `input_id` 作为输入标识。常态化测试中要求：

```text
input_id = query_id
```

### 4.2 对比原则

- 基线版本和候选版本必须使用同一份输入文件和相同 Query。
- 两个版本必须分别保存到不同输出目录，不能互相覆盖。
- Excel 以 `query_id + run_label + candidate_rank` 唯一定位候选人。
- 当前只保存 Top 5，因此只支持 Top1、Hit@3、Hit@5 和 MRR@5 相关人工判定，不声称支持 Hit@10。
- 接口成功不等于身份命中；任务状态、候选人身份和字段质量必须分开记录。
- 只有候选人身份被确认正确后，才应对其字段准确性和完整性进行评分。

### 4.3 自动化边界

本期自动完成：

- JSONL 读取和字段提取；
- 基线/候选版本标识与 Query 对齐；
- Top 5 候选人展开；
- Profile 动态字段展开；
- 数组和对象的可读化展示；
- failures 归集；
- Excel 格式化和基础数量统计。

本期不自动完成：

- 判断候选人是否为目标人物；
- 判断照片是否属于同一人物；
- 判断 insights/AI 总结是否真实；
- 根据公开网页自动核验事实；
- 自动计算字段准确率、完整率或发布门禁结论；
- 自动生成竞品结论。

上述内容需要金标和人工复核，避免把模型输出或昵称相似直接当作身份结论。

## 5. 用户场景

### 5.1 单次结果查看

测试人员将一个输出目录转换为 Excel，用于查看本次 Run 的所有候选人和字段。

```text
output/eval_current/
  ├── results.jsonl
  └── failures.jsonl
        ↓
results_comparison.xlsx
```

### 5.2 优化前后版本对比

测试人员使用相同的 `tasks.jsonl` 分别运行基线版本和候选版本：

```text
output/eval_baseline_YYYYMMDD/
output/eval_candidate_YYYYMMDD/
        ↓ 按 input_id/query_id 对齐
results_comparison.xlsx
```

Excel 中同时保留 `baseline` 和 `candidate` 两组结果，测试人员可按 Query 查看候选人排名和字段变化。

## 6. 输入需求

### 6.1 必需输入

每个 Run 目录应包含：

| 文件 | 是否必需 | 说明 |
| --- | --- | --- |
| `results.jsonl` | 是 | 成功任务及其 Top 5 候选人的完整 `ui_sections` |
| `failures.jsonl` | 否 | 失败任务；文件不存在时按无失败处理 |

`results.jsonl` 每行结构：

```json
{
  "input_id": "query-001",
  "task_id": "task_xxx",
  "results": [
    {
      "candidate_id": "candidate_xxx",
      "ui_sections": {}
    }
  ]
}
```

### 6.2 Run 元数据

每个输入目录在导出时必须指定：

| 字段 | 说明 |
| --- | --- |
| `run_label` | `baseline`、`candidate` 或自定义名称 |
| `system_version` | Git commit、部署版本或人工填写的版本号 |
| `evaluation_id` | 本轮评测唯一编号 |

鉴权 token、Cookie 和真实凭证不得进入 Excel。

### 6.3 可选 Query 元数据

为支持常态化分组对比，可选提供 Query 元数据，至少包含：

| 字段 | 说明 |
| --- | --- |
| `query_id` | 与 searchTool 的 `input_id` 一致 |
| `person_id` | 金标人物稳定 ID |
| `query_type` | Q1–Q15 |
| `person_group` | A/B/C/D 人群层 |
| `difficulty` | low/medium/high |
| `tags` | 同名、少线索、多语言、有照片等标签 |

未提供 Query 元数据时仍可生成候选结果表，但无法按 Person、Query 类型或困难度分组。

## 7. 输出工作簿设计

默认输出：

```text
output/results_comparison.xlsx
```

工作簿包含四个 Sheet：

| Sheet | 一行的粒度 | 用途 |
| --- | --- | --- |
| `候选结果` | Run × Query × Candidate | 查看和比较 Top 5 详情，是主数据表 |
| `Query对比` | Query | 汇总基线/候选状态，填写人工身份判定和变化结论 |
| `失败记录` | 失败任务 | 汇总两个 Run 的接口、轮询和详情失败 |
| `说明` | 字段说明 | 记录生成时间、输入目录、版本和字段口径 |

### 7.1 `候选结果` Sheet

每名候选人占一行。排序顺序为：

```text
query_id → run_label → candidate_rank
```

#### A. 追溯与分组字段

| Excel 列 | 来源/规则 |
| --- | --- |
| `evaluation_id` | 导出参数 |
| `run_label` | 导出参数，如 baseline/candidate |
| `system_version` | 导出参数 |
| `query_id` | `results.jsonl.input_id` |
| `person_id` | Query 元数据；没有则留空 |
| `query_type` | Query 元数据；没有则留空 |
| `person_group` | Query 元数据；没有则留空 |
| `difficulty` | Query 元数据；没有则留空 |
| `tags` | Query 元数据；多值使用换行连接 |
| `task_id` | `results.jsonl.task_id` |
| `candidate_rank` | 候选人在 `results` 数组中的顺序，从 1 开始 |
| `candidate_id` | `results[].candidate_id` |

#### B. Insights 字段

| Excel 列 | JSON 路径 | 处理规则 |
| --- | --- | --- |
| `insights_status` | `ui_sections.insights.status` | 原样保存；缺失留空 |
| `insights_description` | `ui_sections.insights.data.items[0].description` | items 为空或不存在时留空 |
| `insights_links` | `ui_sections.insights.data.items[0].links` | 保存为紧凑 JSON 字符串，不丢失 platform/title/type/url |

本期只提取 `items[0]`，与当前需求保持一致。其他 insight item 仍保存在 `insights_data` 中：

| Excel 列 | JSON 路径 |
| --- | --- |
| `insights_data` | 完整 `ui_sections.insights.data` JSON |

#### C. Photos 字段

| Excel 列 | JSON 路径 | 处理规则 |
| --- | --- | --- |
| `photos_status` | `ui_sections.photos.status` | 原样保存 |
| `photos_baseline_photo_url` | `photos.data.baseline_photo_url` | 原样保存 URL |
| `photos_identity_match_rate` | `photos.data.identity_match_rate` | 保留数值类型 |
| `photos_authenticity_photos` | `photos.data.authenticity_photos` | JSON 字符串 |
| `photos_match_photos` | `photos.data.match_photos` | JSON 字符串 |
| `photos_data` | 完整 `ui_sections.photos.data` | JSON 字符串，保证未知字段不丢失 |

照片模块只做数据展示，不自动判断是否同一人物、是否可比或照片是否真实。

#### D. Profile 字段

当前结构：

```text
ui_sections.profile
  ├── status
  └── data.sections[]
      ├── title
      └── items[]
          ├── label
          └── value
```

固定列：

| Excel 列 | JSON 路径 |
| --- | --- |
| `profile_status` | `ui_sections.profile.status` |
| `profile_data` | 完整 `ui_sections.profile.data` JSON |

动态列按以下规则生成：

```text
profile.<section.title>.<item.label>
```

示例：

```text
profile.Identity.Full Name
profile.Identity.Location
profile.Career.Employer
profile.Background.School
```

生成 Excel 前，必须同时扫描基线和候选版本的所有 Profile 字段，取字段并集作为统一表头。相同 `title + label` 出现多个值时，按返回顺序使用换行连接；某候选人不存在该字段时留空。

#### E. Social 字段

从 `ui_sections.social.data.profiles[]` 提取：

| Excel 列 | JSON 路径 | 处理规则 |
| --- | --- | --- |
| `social_status` | `ui_sections.social.status` | 原样保存 |
| `social_display_handles` | `profiles[].display_handle` | 多个值按 profiles 顺序换行连接 |
| `social_platforms` | `profiles[].platform` | 多个值按相同顺序换行连接 |
| `social_urls` | `profiles[].url` | 多个值按相同顺序换行连接 |
| `social_profiles` | 完整 `profiles` | JSON 字符串，用于核对字段对应关系 |

三个多值展示列必须保持相同顺序，不得分别去重或重新排序。错误社交账号属于高风险字段，但是否错误由人工或后续金标比对判定。

#### F. Summary 字段

| Excel 列 | JSON 路径 | 处理规则 |
| --- | --- | --- |
| `summary_avatar_url` | `ui_sections.summary.data.avatar_url` | 原样保存 |
| `summary_confidence_level` | `summary.data.confidence_level` | 原样保存，不将其视为人工身份结论 |
| `summary_primary_image_url` | `summary.data.primary_image.url` | primary_image 不存在时留空 |
| `summary_social_links` | `summary.data.social_links` | JSON 字符串 |
| `summary_web_links` | `summary.data.web_links` | JSON 字符串 |

为便于人工确认候选人，可同时提取以下展示字段：

| Excel 列 | JSON 路径 |
| --- | --- |
| `summary_display_name` | `summary.data.display_name` |
| `summary_location` | `summary.data.location` |
| `summary_match_score` | `summary.data.match_score` |
| `summary_is_top_result` | `summary.data.is_top_result` |
| `summary_is_best_match` | `summary.data.is_best_match` |

#### G. 人工复核字段

以下为空白可编辑列，生成后由测试人员填写：

| Excel 列 | 可选值/说明 |
| --- | --- |
| `identity_judgement` | `correct` / `wrong` / `unverifiable` |
| `identity_evidence` | 支撑身份判断的公开来源或说明 |
| `field_review_status` | `correct` / `partial` / `wrong` / `unverifiable` / `not_returned` / `not_applicable` |
| `failure_type` | 常态化方案约定的失败类型 |
| `reviewer` | 标注人 |
| `review_comment` | 争议、数据变化或其他说明 |

### 7.2 `Query对比` Sheet

每个 `query_id` 一行，用于基线/候选版本配对检查和人工汇总结论。

| 字段组 | Excel 列 |
| --- | --- |
| Query 信息 | `query_id`、`person_id`、`query_type`、`person_group`、`difficulty`、`tags` |
| 基线执行 | `baseline_status`、`baseline_candidate_count`、`baseline_failure_stage` |
| 候选执行 | `candidate_status`、`candidate_candidate_count`、`candidate_failure_stage` |
| 人工排名 | `baseline_target_rank`、`candidate_target_rank` |
| 基础指标 | `baseline_hit1/3/5`、`candidate_hit1/3/5`、`baseline_mrr5`、`candidate_mrr5` |
| 变化 | `change_type`、`rank_change`、`regression_flag` |
| 归因 | `primary_failure_type`、`review_comment` |

人工填写目标人物排名后，Excel 可使用确定性公式生成 Hit@1、Hit@3、Hit@5 和 MRR@5：

```text
Hit@K = target_rank 非空且 target_rank <= K
MRR@5 = target_rank 在 1–5 时为 1 / target_rank，否则为 0
```

`change_type` 统一使用：

- `correct_to_correct`
- `wrong_to_correct`
- `correct_to_wrong`
- `wrong_to_wrong`
- `rank_improved`
- `rank_regressed`
- `pipeline_changed`
- `pending_review`

### 7.3 `失败记录` Sheet

合并各 Run 的 `failures.jsonl`：

| Excel 列 | 来源 |
| --- | --- |
| `evaluation_id`、`run_label`、`system_version` | 导出参数 |
| `query_id` | `failure.input_id` |
| `task_id` | `failure.task_id` |
| `stage` | `failure.stage` |
| `error` | `failure.error` |
| `failure_type` | 默认 `PIPELINE_FAILURE`，可人工修改 |

阶段至少保留：`Input`、`CreateIntentTask`、`GetTask`、`ListTaskCandidates`、`GetTaskCandidateDetail`。

### 7.4 `说明` Sheet

记录：

- Excel 生成时间；
- `evaluation_id`；
- 各 Run 的输入目录、`run_label` 和 `system_version`；
- results/failures 记录数；
- 是否提供 Query 元数据；
- Top 5 评测口径；
- 动态 Profile 列生成规则；
- 空值、多值和 JSON 字段展示规则；
- 不得把系统 confidence 当作人工身份判定的提示。

## 8. 数据处理流程

```text
读取 baseline results/failures（可选）
  + 读取 candidate/current results/failures
  + 读取 Query 元数据（可选）
            ↓
按 JSONL 行校验 input_id、task_id、results
            ↓
将每个 results[] 展开为候选人行，并生成 candidate_rank
            ↓
扫描两个 Run 的 Profile 字段并集，生成统一动态列
            ↓
提取 insights/photos/profile/social/summary 指定字段
            ↓
按 query_id 对齐两个 Run，汇总成功、空结果和失败状态
            ↓
生成四个 Excel Sheet 并应用筛选、冻结、换行和列宽
```

## 9. 异常与边界处理

| 场景 | 处理方式 |
| --- | --- |
| 输入目录或 `results.jsonl` 不存在 | 明确报错并终止，不生成不完整报告 |
| `failures.jsonl` 不存在 | 按无失败处理，并在说明 Sheet 标记 |
| JSONL 某行无法解析 | 记录文件名和行号；继续其他行，并在说明 Sheet 显示异常数 |
| `input_id` 缺失 | 该记录无法对齐，归入数据异常，不伪造 query_id |
| `results` 为空 | Query 状态记为 `NO_CANDIDATE`，候选结果不生成候选人行 |
| 某模块缺失或 status=empty | 对应字段留空，保留 status；不视为链路失败 |
| `insights.items` 为空 | description、links 留空 |
| Profile 出现新 section/label | 自动加入动态列 |
| Social 存在多个账号 | 按原顺序换行展示，同时保留完整 JSON |
| 基线有 Query、候选版本缺失 | Query 对比标记 `pipeline_changed` 或待复核 |
| Excel 单元格超过 32,767 字符 | 不静默截断；记录 query/candidate/字段，并将该单元格标记为超长待处理 |
| 外部文本以 `=`、`+`、`-`、`@` 开头 | 按纯文本写入，防止 Excel 公式注入 |

## 10. Excel 展示要求

- 第一行冻结；
- 开启自动筛选；
- 所有 URL、JSON、多值和人工备注列启用自动换行；
- 列宽设置合理上限，避免超长 URL 撑开表格；
- 数值字段保留数值类型，布尔字段保留布尔类型；
- 空值写空单元格，不写字符串 `null`、`None`；
- JSON 使用 UTF-8、紧凑格式并保留中文；
- Profile 动态列在两个 Run 中使用同一表头；
- 冻结原始提取列与人工填写列的列名，避免后续报告无法对齐。

## 11. 隐私与安全

- 不读取、导出或记录 `.env`、token、Cookie 和鉴权 headers；
- Excel 只包含完成评测所需的结果字段和运行元数据；
- 对外分享前应检查邮箱、私人账号、签名图片 URL 等敏感或短时信息；
- 社交、照片和 AI 总结仅用于已授权测试及公开信息质量评估；
- 报告不得把系统输出直接描述为已核实事实；
- 原始 JSONL 和 Excel 的访问权限应按测试数据敏感级别控制。

## 12. 非功能需求

| 项目 | 要求 |
| --- | --- |
| 执行方式 | 本地、离线、同步处理，不发起任何 HTTP 请求 |
| 数据规模 | 第一版至少支持 300 条 Query × 2 个 Run × 每条 Top 5 |
| 可重复性 | 同样输入和配置应生成相同的数据行、字段和值 |
| 原始数据保护 | 不修改、不覆盖输入 JSONL |
| 可追溯性 | 每行可回溯到 run_label、query_id、task_id、candidate_id 和 rank |
| 兼容性 | 输出 `.xlsx` 可由 Microsoft Excel 正常打开、筛选和编辑 |
| 简洁性 | 独立于 searchTool 请求流程，不引入数据库、Web 页面或异步任务 |

## 13. 验收标准

### 13.1 数据正确性

1. Excel 的候选人行数等于所有输入 Run 中 `results[]` 候选人数之和。
2. 每行的 `query_id`、`task_id`、`candidate_id` 和 `candidate_rank` 与原始 JSON 一致。
3. 指定的 insights、photos、profile、social、summary 字段全部按本 PRD 映射生成。
4. `ui_sections.insights.data.items[0]` 不存在时不会报错，相关列为空。
5. Profile 的全部 section/label 在基线和候选版本字段并集中均有对应列。
6. Social 多账号字段顺序一致，不发生 platform、handle 和 URL 错位。
7. Photos、Profile、Social 和 Insights 的完整 JSON 保留列不丢失未知字段。

### 13.2 对比与追溯

1. 相同 `query_id` 的 baseline/candidate 结果可在 Excel 中筛选并对照。
2. 成功、空候选人和 pipeline failure 三类状态能够区分。
3. `failures.jsonl` 中所有记录均出现在失败记录 Sheet。
4. 人工填写目标排名后，Hit@1、Hit@3、Hit@5 和 MRR@5 公式结果正确。
5. 可按 query_type、person_group、difficulty、tags、run_label 和 failure_type 筛选。

### 13.3 安全与兼容

1. Excel 不包含 auth token、Cookie 或完整鉴权配置。
2. 输入 JSONL 在导出前后内容和校验值不变。
3. Excel 可正常打开，无损坏提示；筛选、冻结、换行和中文显示正常。
4. 缺失模块、空数组、未知新增字段和单条坏 JSON 不导致全部导出失败。

## 14. 本期交付物建议

在用户确认本 PRD 后，第二阶段建议进行以下最小开发：

1. 新增一个独立的 JSONL → Excel 导出脚本，不修改现有 HTTP 请求链路；
2. 在现有依赖中增加一个 Excel 写入库；
3. 在现有 README 中补充单次导出和基线/候选对比命令；
4. 增加覆盖字段映射、Profile 动态列、空值、双 Run 对齐和失败记录的测试；
5. 使用当前 `output/results.jsonl` 做单 Run 验证，再使用两份相同结构目录做配对验证。

## 15. 后续阶段（不在 v1.2 实现范围）

- 接入 Person 金标库，自动规范化姓名、URL、邮箱和地区；
- 自动计算字段准确率、完整率、误报率和来源可追溯率；
- 自动汇总 Top1、Hit@3、Hit@5、MRR@5、多信息增益和分组指标；
- 自动生成逐 Query 退化清单、发布门禁和 Markdown 报告；
- 接入每日冒烟、每周基础集和发布前完整回归；
- 趋势看板、统计置信区间和配对 bootstrap；
- 竞品结果按相同 Query、金标和 Top 5 口径进行统一对比。

## 16. 待确认事项

1. 第一版是否需要同时支持“单 Run 导出”和“baseline/candidate 双 Run 对比”；建议两者都支持，共用同一字段处理逻辑。
2. Query 元数据首版采用 JSONL 还是 Excel；建议优先 JSONL，与 `tasks.jsonl` 的 `input_id` 对齐更稳定。
3. 人工复核字段是直接填写在导出 Excel 中，还是由独立标注表维护；第一版建议直接填写 Excel。
4. `profile_data`、`photos_data` 等完整 JSON 若超过 Excel 单元格限制，是否允许拆分到额外 Raw Sheet；首版需要在实现前确认。
