# searchTool v1.3 MVP 优化需求

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | searchTool v1.3 MVP 优化需求 |
| 文档版本 | v1.0 |
| 基于版本 | searchTool v1.3 MVP |
| 编写日期 | 2026-07-24 |
| 需求状态 | 待开发 |
| 优化主线 | 补充数据字段 → 修正指标口径 → 升级报告 |

## 2. 背景

searchTool v1.3 MVP 已经支持：

- 通过 Web 启动 `FULL_NAME` 和 `FULL_NAME_SOCIAL` 检索；
- 导入历史 JSONL/Excel 结果；
- 保存 Query、Candidate 和完整 Raw 数据；
- 使用版本化字段配置处理 Candidate Detail；
- 导入 Baseline、人工复核候选人和字段；
- 生成单次运行报告、对比报告、静态 HTML 和 Excel。

最新版《检索功能常态化测试方案与方法》进一步明确了分阶段评估、结果状态、成本、
耗时、候选人置信度、基准可用字段和上线判断等要求。现有平台的采集主流程不需要重做，
本次重点补齐数据、修正指标并升级报告。

## 3. 当前问题

### 3.1 字段配置能力边界不清晰

当前字段配置属于处理层配置，主要从以下已构造的数据源中提取字段：

- Candidate Detail 的 `ui_sections`；
- Candidate 的 `candidate_id`、`candidate_rank`、`rank_score` 等固定字段；
- Task 的 `task_id`、`llm_cost`、`total_cost`、`pdl_called` 等固定字段。

字段配置当前不能直接完成以下工作：

- 从任意接口 Raw 响应中动态增加 Task 公共字段；
- 自动把新增字段写入 Query/Candidate 结构化存储；
- 自动让新增字段参与指标和报告计算。

因此，`llm_cost`、`total_cost`、`pdl_called` 虽然已经有配置项和数据库占位字段，
但当前采集结果仍保存为空。仅发布一份新的字段配置，不能让这些字段自动进入指标和报告。

### 3.2 可选业务字段缺失被误判为处理错误

当前处理器遇到以下情况会记录 `FIELD_PROCESSING_ERROR`：

- 数组为空，配置使用了 `items[0]`；
- 对象字段不存在；
- 父对象为 `null`；
- 可选模块没有返回。

例如：

```text
ui_sections.insights.data.items[0].description
ui_sections.insights.data.items[0].links
ui_sections.summary.data.primary_image.url
```

当 `insights.data.items` 为空，或 `summary.data.primary_image` 不存在/为 `null` 时，
这些字段本来就没有数据，应当记为空值，而不是配置错误。

### 3.3 指标仍使用旧口径

- 命中候选人完整度仍固定除以22；
- 未按每个人的 `baseline_available_fields` 计算有效分母；
- 未区分 `HAS_CANDIDATES`、`NO_CANDIDATES`、`EXECUTION_FAILED`；
- 成本字段任一缺失时，已存在的成本值也无法正常汇总；
- 尚未计算第三方成本、检索耗时和候选人置信度指标；
- 尚未按 `evaluation_phase + system_version + query_stage` 分组。

### 3.4 报告不能完整回答评估问题

当前报告主要展示检索成功率、完整度、准确率和基础成本占位信息，尚不能清楚回答：

- 本轮有多少任务有候选人、无候选人或执行失败；
- 本轮属于哪个评估阶段；
- 同条件版本升级是否真正改善；
- 新增 Social Link 是线索增益还是系统版本增益；
- 成本、耗时和 PDL 调用是否可接受；
- 候选人置信度如何分布和变化；
- 核心指标是否达到参考线；
- 本轮是否建议上线、继续优化或暂不能判断。

## 4. 优化目标

### 4.1 产品目标

1. 接口新增公共字段后，可以通过稳定映射进入结构化数据、指标和报告。
2. 可选业务字段没有返回时按正常空值处理，不再产生虚假配置错误。
3. 指标严格使用最新版测试方案口径，结果可复现、可解释。
4. 单次报告和对比报告可以完整展示结果状态、质量、成本、耗时和置信度。
5. 报告可以区分同条件版本对比和新增线索实验，避免错误归因。

### 4.2 成功标准

- 新字段进入平台时不需要重做检索主流程；
- 所有公共字段均保留原始值，缺失时保持 `null`，不能按0处理；
- 可选路径不存在不会进入“字段错误”列表；
- 命中完整度使用每个人实际确认的基准字段作为分母；
- 单次运行无需对比 Run 即可生成报告；
- 缺少 Baseline 或人工复核时，相关质量指标显示“未就绪”，不阻止原始数据和运行报告导出；
- 对比报告将同条件版本对比和新增线索结果分开展示；
- 旧处理结果和旧报告快照保持不变。

## 5. 范围

### 5.1 本次包含

1. 公共字段接入与配置边界优化；
2. 可选路径缺失处理；
3. `candidate_confidence` 统一映射；
4. `baseline_available_fields` 管理与完整度口径修正；
5. 结果状态及有结果率/无结果率/失败率；
6. 成本、耗时和 PDL 指标；
7. `evaluation_phase`；
8. 单次报告和对比报告升级；
9. 旧数据兼容与重新处理。

### 5.2 本次不包含

- `FULL_NAME_PHOTO` 输入和照片上传接口；
- 多用户、角色权限和字段配置审核；
- 通用脚本、表达式或用户自定义代码执行；
- 排名质量、重复运行一致性和错误类型等后续指标；
- Provider、Evidence、Social Accounts 的完整结构化归类；
- 自动获取外部 Baseline；
- 自动决定正式上线，平台只按已配置规则给出辅助判断。

## 6. 字段配置与公共字段接入

### 6.1 两类字段能力

平台需要明确区分两类配置。

#### A. 处理字段配置

用于从已经进入平台的 Candidate/Task 处理源中提取、展示和复核普通字段，例如：

- `insights_description`；
- `insights_links`；
- `summary_primary_image_url`；
- Profile、Social、Photos 和 Summary 业务字段。

处理字段配置继续支持：

- `source_stage`；
- `source_path`；
- `data_type`；
- `array_mode`；
- `empty_rule`；
- `normalizer`；
- `scoring_role`；
- `compare_mode`。

#### B. 系统公共字段映射

用于把接口返回的公共字段写入平台的结构化 Query/Candidate 数据，并提供给指标和报告。

本次需要支持以下公共字段：

| 字段 | 层级 | 类型 | 当前来源 | 缺失处理 |
| --- | --- | --- | --- | --- |
| `baseline_available_fields` | Baseline/Person | string array | 正式接口路径待确认，也支持 Baseline 导入/人工维护 | `null`，相关完整度未就绪 |
| `llm_cost` | Query/Task | number | 正式接口路径待确认 | `null`，不按0统计 |
| `third_party_cost` | Query/Task | number | 正式接口路径待确认 | `null`，不按0统计 |
| `total_cost` | Query/Task | number | 正式接口路径待确认 | `null`，不按0统计 |
| `pdl_called` | Query/Task | boolean | 正式接口路径待确认 | `null`，表示未知 |
| `search_duration_ms` | Query/Task | integer | 正式接口路径待确认 | `null`，不使用本地运行时长替代 |
| `candidate_confidence` | Candidate | enum/string | `ui_sections.summary.data.confidence_level` | `null`/`UNKNOWN` |

公共字段的类型和业务含义固定，接口路径允许配置。后端确认实际路径后，应通过映射配置
接入，不应再次修改指标公式或报告模板中的业务字段名称。

### 6.2 字段接入要求

1. Raw 响应始终完整保存。
2. 公共字段从对应接口响应中提取后，写入结构化数据。
3. 历史 Raw 数据可以使用新映射重新处理。
4. 映射路径变化时发布新版本，不覆盖旧处理快照。
5. 公共字段缺失时保存 `null`，并记录字段缺失数量。
6. 字段值类型错误时记录结构异常，不把错误值写成0、`false` 或空字符串。
7. `total_cost` 直接采用接口返回值，不使用
   `llm_cost + third_party_cost` 二次计算，避免重复统计。

## 7. Candidate Confidence 统一规则

### 7.1 字段定义

`candidate_confidence` 对应现有的 Summary Confidence Level：

```text
ui_sections.summary.data.confidence_level
```

### 7.2 兼容规则

- 指标和新版报告统一使用逻辑字段名 `candidate_confidence`；
- 现有 `summary_confidence_level` 作为历史展示字段继续兼容；
- 同一份处理结果中二者来源相同，不能作为两个不同指标重复统计；
- 旧报告保持原字段名和快照，不自动改变；
- 值缺失时记为 `UNKNOWN` 或空值，不产生字段处理错误。

### 7.3 首版统计

在未确认更多枚举前，报告至少支持：

- 各原始置信度值的候选人数和占比；
- 空值/`UNKNOWN` 数量；
- 命中候选人与非命中候选人的置信度分布；
- 同条件对比中同一人物置信度的前后变化。

平台不得自行把 HIGH/MEDIUM/LOW 转换为身份命中结论。

## 8. 可选路径缺失处理

### 8.1 路径结果分类

字段提取结果分为三类：

| 分类 | 示例 | 处理方式 |
| --- | --- | --- |
| 正常有值 | 路径存在且值符合类型 | 保存值 |
| 正常空值 | 键不存在、父对象为 `null`、数组为空、固定索引不存在 | 保存 `null` 或空数组，标记为空，不报错 |
| 结构/配置错误 | 路径语法非法、实际类型与配置类型冲突、需要数组但返回标量 | 记录字段处理错误 |

### 8.2 缺失策略

字段配置增加或明确 `missing_policy`：

| 值 | 含义 |
| --- | --- |
| `EMPTY` | 路径缺失按空值处理 |
| `ERROR` | 路径缺失记录处理错误 |

默认规则：

- `ui_sections` 下的业务字段默认使用 `EMPTY`；
- `task_id`、`candidate_id` 等系统必需标识使用 `ERROR`；
- 通配数组为空时返回空数组；
- `items[0]` 在数组为空时返回 `null`；
- 父对象为 `null` 时，其子字段返回 `null`。

### 8.3 本次必须修正的字段

| 字段 | 路径 | 无数据时结果 |
| --- | --- | --- |
| `insights_description` | `ui_sections.insights.data.items[0].description` | `null` |
| `insights_links` | `ui_sections.insights.data.items[0].links` | 空数组或 `null` |
| `summary_primary_image_url` | `ui_sections.summary.data.primary_image.url` | `null` |

这些路径由字段配置定义，不是写死在提取器中的业务逻辑。问题在于当前提取器没有区分
“可选字段不存在”和“配置结构错误”。

### 8.4 页面展示

- 正常空值计入字段空值率，不进入字段错误列表；
- 字段错误列表只展示真正的配置、类型或结构异常；
- Process 页面分别展示“空字段数”和“字段错误数”；
- 报告不得把正常空值描述为处理失败。

## 9. Baseline Available Fields 与完整度

### 9.1 字段定义

每个基准人物保存一组已确认可用于对比的字段：

```json
{
  "baseline_available_fields": [
    "profile_full_name",
    "profile_location",
    "summary_social_links"
  ]
}
```

来源优先级：

1. 正式接口返回；
2. Baseline JSONL/Excel 导入；
3. 测试人员在 Baseline/字段复核页面人工确认。

### 9.2 命中完整度口径

本优化版本明确取消“所有人物固定除以22”的正式计算方式。

单个命中候选人的完整度：

```text
命中完整度 =
该候选人在 baseline_available_fields 中正确找回的字段得分之和
/ 该人物 baseline_available_fields 字段数
* 100%
```

规则：

- 单值字段正确找回得1分，否则得0分；
- 多值字段得分为正确找回项数/已确认基准项数；
- 不在 `baseline_available_fields` 中的字段不进入分子和分母；
- 错误值不能提高完整度；
- `baseline_available_fields` 缺失或为空时，命中完整度显示“未就绪”，不能回退为除以22。

### 9.3 准确率口径

命中候选人字段准确率只统计：

- 位于 `baseline_available_fields` 中；
- 候选人实际返回了非空值；
- 已完成自动或人工正确性判定的字段。

未返回字段不进入准确率分母，但会影响完整度。

## 10. 结果状态与检索指标

### 10.1 Query 结果状态

统一使用：

| 状态 | 定义 |
| --- | --- |
| `HAS_CANDIDATES` | 检索正常完成，候选人数大于等于1 |
| `NO_CANDIDATES` | 检索正常完成，候选人数为0 |
| `EXECUTION_FAILED` | 接口失败、超时或无法取得候选人列表 |

Candidate Detail 部分失败继续使用明细状态
`PARTIAL_DETAIL_FAILED`，但 Query 结果状态仍为 `HAS_CANDIDATES`。

旧数据中的 `SUCCESS`、`NO_CANDIDATE` 和失败状态在新处理版本中映射到上述统一状态，
不修改旧 Raw。

### 10.2 指标公式

```text
有结果率 =
HAS_CANDIDATES 数
/ (HAS_CANDIDATES 数 + NO_CANDIDATES 数)
* 100%
```

```text
无结果率 =
NO_CANDIDATES 数
/ (HAS_CANDIDATES 数 + NO_CANDIDATES 数)
* 100%
```

```text
执行失败率 =
EXECUTION_FAILED 数
/ 本轮应执行的正式 Query 数
* 100%
```

```text
检索成功率 =
命中 Baseline 人物的 Query 数
/ 本轮应执行的正式 Query 数
* 100%
```

其中 `NO_CANDIDATES` 和 `EXECUTION_FAILED` 的检索成功均记为0，但必须在报告中分别
展示，不能把执行失败解释为正常无候选人。

## 11. 成本、耗时与 PDL

### 11.1 单 Query 字段

- `llm_cost`；
- `third_party_cost`；
- `total_cost`；
- `pdl_called`；
- `search_duration_ms`。

### 11.2 聚合规则

每个字段独立计算：

- 有效任务数；
- 缺失任务数；
- 总值；
- 平均值；
- 最小值和最大值（耗时至少提供平均值和最大值）。

字段部分缺失时：

- 对已有有效值继续汇总；
- 不使用0补齐；
- 报告标记“部分接入”并显示缺失任务数；
- 一个字段缺失不能阻止其他成本字段统计。

`pdl_called` 分别统计：

- `true` 次数；
- `false` 次数；
- 未知次数；
- 调用率，分母只使用明确为 `true/false` 的任务。

### 11.3 分组

成本、耗时和 PDL 按以下维度分组：

```text
evaluation_phase + system_version + query_stage
```

同时展示整个阶段的实际任务总计。

## 12. Evaluation Phase

Evaluation 或 Run 必须记录：

| 值 | 含义 |
| --- | --- |
| `PHASE_1_BASELINE` | 第一阶段基线 |
| `PHASE_2_POST_OPTIMIZATION` | 第二阶段优化后复测 |
| `PHASE_3_TARGETED_ITERATION` | 第三阶段专项迭代 |

`evaluation_phase` 与 `query_stage` 是两个独立字段：

- `evaluation_phase` 表示评估处于哪个阶段；
- `query_stage` 表示 `FULL_NAME`、`FULL_NAME_SOCIAL` 等检索条件。

历史 Run 未设置时显示 `UNSPECIFIED`，允许测试人员补充阶段，但不得根据
`system_version` 自动猜测。

## 13. 报告升级

### 13.1 单次运行报告

单次报告不依赖对比 Run，可以直接生成并导出。

至少包括：

1. Evaluation、Run、阶段、系统版本、Dataset、字段配置和规则版本；
2. 应执行、完成、有候选人、无候选人、执行失败和部分详情失败数量；
3. 有结果率、无结果率、执行失败率；
4. 检索成功率、命中完整度、命中准确率、非命中完整度；
5. Candidate Confidence 分布；
6. LLM、第三方、总成本、PDL 和检索耗时；
7. 模块返回率和字段返回率；
8. 缺失数据说明、字段错误和失败任务；
9. 人物、Query、Candidate 和 Raw 下钻入口；
10. 静态 HTML 和 Excel 导出。

没有 Baseline 或复核时：

- 仍可生成运行报告；
- 原始结果、候选人数、结果状态、成本、耗时和置信度正常展示；
- 依赖 Baseline/复核的指标显示“未就绪”及缺失原因。

### 13.2 对比报告

对比报告分为两个独立区域。

#### A. 同条件版本对比

要求：

- Person、Dataset 输入和 `query_stage` 可配对；
- 字段配置、Baseline 和判定规则版本兼容；
- 展示基线阶段与优化阶段的前后变化；
- 展示持续命中、新增命中、退化未命中和持续未命中；
- 展示完整度、准确率、成本、耗时和置信度变化；
- 列出改善最明显的3至5个人、全部退化人物和持续未命中典型案例。

#### B. 新增线索实验

当某个 `query_stage` 在上一阶段没有相同条件基线时：

- 标记为“本阶段新增线索”；
- 单独展示本阶段实际结果；
- 可以与同版本 `FULL_NAME` 做横向观察；
- 不展示虚构的优化前数值；
- 不将线索增益表述为系统版本提升。

### 13.3 参考线与建议

报告支持为以下核心指标配置可选参考线：

- 检索成功率；
- 命中完整度；
- 命中准确率；
- 可接受成本；
- 可接受检索耗时。

报告展示：

- 参考线；
- 实际值；
- 是否达到；
- 缺失数据；
- 建议结果：`建议上线`、`继续优化`、`暂不能判断`。

参考线未配置或关键数据缺失时，只能显示“暂不能判断”，不能自动给出上线建议。

### 13.4 详细数据表

报告增加：

- 命中/非命中候选人的模块返回情况；
- 字段返回率、命中完整度和命中准确率；
- Social Link 数量、平台和匹配/冲突情况；
- Photos 状态、图片数量和链接；
- Candidate Confidence 分布；
- 每个 Query 的成本、耗时和 PDL；
- 字段空值和真正的字段处理错误。

## 14. 兼容与重新处理

1. 不修改历史 Raw 数据。
2. 不覆盖历史字段配置和报告快照。
3. 发布新的字段配置/公共字段映射版本。
4. 历史数据包含所需 Raw 字段时，可以重新处理生成新 Process。
5. 历史数据没有对应接口字段时保持 `null`。
6. 旧 `summary_confidence_level` 可映射为新版 `candidate_confidence`。
7. 旧 Query 状态在新 Process/报告中做兼容映射，不回写旧结果文件。
8. 新旧 Process 和报告必须显示所使用的字段配置、映射和规则版本。

## 15. 异常与边界规则

| 场景 | 处理 |
| --- | --- |
| 可选业务路径不存在 | 正常空值，不报错 |
| `items` 为空但配置取 `[0]` | 正常空值 |
| `primary_image` 为 `null` | URL 为空，不报错 |
| 路径语法非法 | 配置发布失败 |
| 期望数组但接口返回字符串 | 记录结构/类型错误 |
| 成本字段缺失 | 保存 `null`，已有任务继续汇总 |
| `baseline_available_fields` 缺失 | 完整度未就绪 |
| Confidence 缺失或出现新枚举 | 保留原值，统计为未知/新增分类 |
| 无候选人 | `NO_CANDIDATES` |
| 接口执行失败 | `EXECUTION_FAILED` |
| 单个 Candidate Detail 失败 | 保留 List 信息，继续其他候选人 |
| 新增线索没有上一阶段基线 | 单独展示，不做版本提升归因 |

## 16. 验收标准

### 16.1 字段接入

- [ ] Raw 中出现公共字段后，可以按映射写入结构化数据。
- [ ] `llm_cost`、`third_party_cost`、`total_cost`、`pdl_called` 和
      `search_duration_ms` 缺失时保持 `null`。
- [ ] `candidate_confidence` 正确读取 Summary Confidence Level。
- [ ] `baseline_available_fields` 可以从接口、导入文件或人工维护。
- [ ] 新映射可以重新处理历史 Raw，旧快照不变。

### 16.2 可选路径

- [ ] `insights.data.items=[]` 时，description 和 links 不产生处理错误。
- [ ] `primary_image=null` 或不存在时，primary image URL 不产生处理错误。
- [ ] 通配数组为空时得到空数组。
- [ ] 非法路径语法在配置发布时被阻止。
- [ ] 确实存在的类型错误仍会进入字段错误列表。

### 16.3 指标

- [ ] 命中完整度按每个人的 `baseline_available_fields` 计算。
- [ ] 不再固定除以22。
- [ ] 有结果率、无结果率、执行失败率公式正确。
- [ ] `NO_CANDIDATES` 和 `EXECUTION_FAILED` 的检索成功均记为0并分开展示。
- [ ] 每个成本字段独立汇总，部分缺失不影响其他字段。
- [ ] 耗时可以计算平均值和最大值。
- [ ] PDL 可以统计调用、未调用和未知数量。
- [ ] Confidence 可以按原始枚举统计分布。

### 16.4 报告

- [ ] 单次 Run 无对比 Run 时可以生成 HTML/Excel 报告。
- [ ] 无 Baseline 时报告仍可生成，依赖 Baseline 的指标显示未就绪。
- [ ] 报告按 `evaluation_phase + system_version + query_stage` 展示。
- [ ] 同条件版本对比和新增线索实验分开。
- [ ] 报告显示参考线、实际值、是否达标和判断依据。
- [ ] 数据不足时上线建议为“暂不能判断”。
- [ ] 正常空字段不再显示为字段处理错误。

## 17. 开发前待后端确认

以下事项不阻塞需求定稿，但会影响字段映射配置：

1. `baseline_available_fields` 的正式接口、路径、数据类型和字段键命名；
2. `llm_cost`、`third_party_cost`、`total_cost`、`pdl_called`、
   `search_duration_ms` 的正式接口路径；
3. 成本单位，以及 `total_cost` 是否已经包含 LLM 和第三方成本；
4. `pdl_called` 是否为严格布尔值；
5. `search_duration_ms` 是否包含排队时间；
6. Summary Confidence Level 的完整枚举；
7. 正式参考线和可接受成本/耗时阈值。

路径确认后应通过公共字段映射接入；除非字段业务含义或类型发生变化，否则不应再次修改
指标公式。

## 18. 建议实施顺序

### 阶段A：字段与空值处理

1. 区分处理字段配置和系统公共字段映射；
2. 接入新增公共字段和 `candidate_confidence`；
3. 修正可选路径缺失策略；
4. 增加兼容迁移和重新处理能力。

### 阶段B：指标口径

1. 接入 `baseline_available_fields`；
2. 修正完整度和准确率；
3. 统一 Query 结果状态；
4. 增加成本、耗时、PDL 和 Confidence 指标；
5. 增加 `evaluation_phase` 分组。

### 阶段C：报告升级

1. 升级单次报告；
2. 升级同条件版本对比；
3. 增加新增线索实验区域；
4. 增加参考线和辅助建议；
5. 完善 HTML/Excel 明细与下钻。
