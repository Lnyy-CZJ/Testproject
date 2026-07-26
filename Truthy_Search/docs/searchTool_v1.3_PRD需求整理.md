# searchTool v1.3 检索分析系统 MVP PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 产品名称 | searchTool 检索分析系统 |
| 文档版本 | v1.3 MVP |
| 文档状态 | 需求确认版 |
| 使用环境 | 本地或测试环境，单用户 |
| 核心目标 | 打通数据获取、原始数据查看、数据处理、人工复核和报告展示闭环 |
| 依据文档 | 《检索功能常态化测试方案与方法 V1.0》 |
| 报告参考 | 《检索系统评估报告 Mock 示例》 |
| 后续需求 | [《searchTool 后续需求池》](./searchTool_后续需求池.md) |

## 2. 背景

### 2.1 当前能力

当前 `searchTool` 可以顺序执行：

```text
CreateIntentTask
  → 每 5 秒轮询 GetTask
  → ListTaskCandidates
  → 对 List 实际返回的每名候选人请求 GetTaskCandidateDetail
  → 保存 results.jsonl / failures.jsonl
```

现有结果处理工具可以将 JSONL 中的固定字段提取到 Excel，用于查看和人工填写。

### 2.2 当前问题

1. 100 人、多个 Run 和多个版本的数据主要依赖 JSONL 与 Excel 管理，查看和追踪不方便。
2. 报告只有聚合结果，无法直接下钻到人物、Query、候选人和原始 JSON。
3. Excel 同时承担原始数据、结构化数据、人工复核和报告明细，数据增长后难以维护。
4. 字段提取仍较固定，接口新增或修改字段时需要调整代码。
5. 数据采集、处理、复核和报告之间缺少统一标识与可追溯关系。
6. 当前尚未形成“获取数据 → 处理数据 → 人工复核 → 生成报告”的可复用流程。

## 3. MVP 已确认决策

以下事项已经确认，不再作为待确认项。

| 编号  | 已确认事项                 | MVP 处理                                             |
| --- | --------------------- | -------------------------------------------------- |
| 1   | 首版运行环境                | 本地或测试环境，单用户                                        |
| 2   | 数据进入方式                | 同时支持 Web 启动 searchTool 和导入历史结果                     |
| 3   | 导入格式                  | 支持 JSONL 和 Excel，导入后转换为统一内部数据                      |
| 4   | 主要使用入口                | Web 为主，Excel 作为兼容导入和导出方式                           |
| 5   | 字段配置维护                | 由测试人员维护，新版本配置无需审核                                  |
| 6   | 成本与 PDL               | 预留 `llm_cost`、`total_cost`、`pdl_called`；正式路径未确认时为空 |
| 7   | `cost_currency`       | 是否存在尚未确认，MVP 不作为正式结构化字段要求                          |
| 8   | provider 与证据字段        | 完整保留原始响应，正式路径和模块映射后续确认                             |
| 9   | Social Link 回显        | 已确认不会回显；返回 Link 可以参与候选人判定和字段评分                     |
| 10  | Candidate Detail 单人失败 | 继续请求剩余候选人，单独记录失败                                   |
| 11  | 静态 HTML 人物案例          | MVP 允许包含人物级案例                                      |

## 4. 产品定位与职责边界

v1.3 MVP 是一个面向测试人员的本地 Web 检索分析工具。

系统分为三个职责层：

| 层级 | 职责 |
| --- | --- |
| 采集层 | 执行接口请求并完整保存原始业务数据 |
| 处理层 | 按字段配置提取数据，完成复核与指标计算 |
| 展示层 | 提供 Web 原始数据查看、分析和报告 |

职责边界：

- `searchTool` 继续只负责请求接口和采集数据；
- 候选人判定、字段评分和报告计算不进入接口请求流程；
- Web 负责组织采集任务、导入历史数据、处理、复核和展示；
- Excel 不再作为唯一数据载体。

## 5. MVP 目标与成功标准

### 5.1 产品目标

1. 可以通过 Web 启动一批 `FULL_NAME` 或 `FULL_NAME_SOCIAL` 检索。
2. 可以导入已有 JSONL 或 Excel 历史结果。
3. 可以查看某个 Run 下所有 Query 和全部已返回候选人。
4. 可以同时查看结构化业务字段和完整原始 JSON。
5. 新增普通返回字段时，可以通过字段配置提取和展示。
6. 可以导入基准数据并完成人工复核。
7. 可以自动计算测试方案中的核心指标。
8. 可以生成单版本或 baseline/candidate 对比报告。
9. 任一报告指标可以下钻到对应的 Query、候选人和原始数据。
10. 可以继续导出 JSONL、Excel 和静态 HTML。

### 5.2 MVP 成功标准

使用一批真实测试数据，能够完整走通：

```text
创建评测
  → 启动执行或导入历史结果
  → 查看原始数据
  → 选择字段配置并处理
  → 导入基准数据
  → 完成人工复核
  → 计算指标
  → 生成报告
  → 从报告下钻到原始记录
```

## 6. MVP 范围

### 6.1 支持的检索条件

| query_stage | 检索条件 | MVP 状态 |
| --- | --- | --- |
| `FULL_NAME` | 全名 | 支持 |
| `FULL_NAME_SOCIAL` | 全名 + Social Link | 支持 |
| `FULL_NAME_PHOTO` | 全名 + 照片 | 不支持，进入后续需求池 |

`FULL_NAME_PHOTO` 暂不实现的原因：

- 需要增加 PUT 等接口调用；
- 输入格式尚未与后端确认；
- 照片 URL 是否回显尚未确认；
- 当前实现会扩大首版接口和评估范围。

### 6.2 MVP 不包含

- 用户登录、角色和权限管理；
- 多用户协作和字段配置审核；
- 测试开发平台集成；
- `FULL_NAME_PHOTO`；
- 自动访问外部网页核验事实；
- 使用 AI 自动给出上线结论；
- 候选人分页；
- 长期趋势、通知、门禁和复杂任务编排；
- 自动识别 provider、evidence 和 social_accounts 的模块归属；
- 未确认接口路径的成本与 PDL 实际采集。

上述需求统一记录在后续需求池。

## 7. 使用者

MVP 只有一个逻辑使用者：测试人员。

测试人员可以：

- 创建评测；
- 启动检索；
- 导入历史结果；
- 查看和筛选数据；
- 维护字段配置；
- 导入基准数据；
- 完成人工复核；
- 生成和导出报告。

MVP 不开发登录、角色和权限。为便于追溯，人工复核仍保留可填写的 `reviewer`、`review_time` 和 `review_note`，但不校验用户身份。

## 8. 核心数据对象

| 对象 | 含义 |
| --- | --- |
| `Evaluation` | 一次评测，包含一个或多个 Run |
| `Dataset` | 本次使用的 Query 输入集 |
| `Person` | 拥有基准数据的目标人物 |
| `Query` | 某个人物的一种检索条件，`input_id = query_id` |
| `Run` | 某个系统版本对一组 Query 的一次执行 |
| `Task` | 一次真实接口检索，对应 `task_id` |
| `Candidate` | Task 返回的一名候选人 |
| `FieldSchema` | 一版字段提取与展示配置 |
| `ProcessResult` | 某个 Run 使用指定配置生成的处理结果 |
| `Review` | 候选人和字段的人工复核记录 |
| `Report` | 基于指定数据和配置版本生成的报告 |

同一个 `person_id + query_stage` 是版本配对的基础。

## 9. 数据分层

### 9.1 原始数据层

保存接口实际产生或历史导入的数据：

- 脱敏后的 CreateIntentTask 输入；
- CreateIntentTask 业务响应；
- GetTask 状态及最终业务响应；
- ListTaskCandidates 完整业务响应；
- 每名候选人的 GetTaskCandidateDetail 完整业务响应；
- `results.jsonl` 和 `failures.jsonl`；
- 采集时间、采集版本和失败信息。

原始数据要求：

- 不因当前字段配置缺失而丢弃新字段；
- 不被处理和复核流程覆盖；
- 不保存 token、Cookie 和完整鉴权 Header；
- 可以关联到 `run_id/query_id/task_id/candidate_id`；
- 历史 Excel 无法还原的原始字段需要明确标记为缺失。

### 9.2 结构化数据层

按照指定 `FieldSchema` 从原始数据提取：

- Task 字段；
- Candidate 字段；
- Insights、Photos、Profile、Social、Summary 字段；
- 模块状态；
- 规范化值；
- 字段非空状态；
- 处理错误。

### 9.3 基准与复核层

保存：

- Person 基准数据；
- 候选人判定；
- 字段完整度和准确率得分；
- Social Link 来源确认；
- 人工复核说明。

### 9.4 指标与报告层

保存：

- Query 指标；
- Run 汇总指标；
- baseline/candidate 配对指标；
- 报告参数、生成时间和配置版本。

## 10. 核心流程

### 10.1 新执行流程

```text
创建 Evaluation
  → 导入/选择 Query Dataset
  → 填写 system_version 和 run_label
  → 启动 searchTool
  → 查看 Run 进度
  → 采集结果进入原始数据层
  → 选择字段配置并处理
  → 复核
  → 生成报告
```

### 10.2 历史结果导入流程

```text
创建 Evaluation
  → 选择“导入历史结果”
  → 上传 JSONL 或 Excel
  → 校验并转换为统一内部数据
  → 标记数据来源和缺失范围
  → 选择字段配置并处理
  → 复核
  → 生成报告
```

### 10.3 重新处理流程

同一份原始数据可以选择新字段配置重新处理：

```text
选择 Run
  → 选择新 FieldSchema
  → 生成新的 ProcessResult
  → 原 ProcessResult 和旧报告保持不变
```

## 11. 功能需求

### 11.1 评测与 Run 管理

创建 Evaluation 时填写：

- `evaluation_id`；
- 评测名称；
- 数据来源：新执行或历史导入；
- `system_version`；
- `run_label`；
- Query 数据集；
- 字段配置版本；
- 基准数据版本；
- 备注。

Query 数据集继续沿用现有 `tasks.jsonl` 任务结构，并满足：

- `input_id = query_id`；
- `query_stage` 只允许 `FULL_NAME` 或 `FULL_NAME_SOCIAL`；
- `FULL_NAME` 只包含全名检索所需线索；
- `FULL_NAME_SOCIAL` 包含全名和 Social Link 线索；
- JSONL 或 Excel 导入后都转换为同一 Query 结构。

要求：

- 每次执行或导入生成唯一 `run_id`；
- 同一天重复执行不覆盖旧 Run；
- baseline 和 candidate 使用不同 Run；
- 可以查看 Evaluation 下所有 Run；
- 可以选择两个兼容 Run 生成版本对比。

### 11.2 Web 启动 searchTool

Web 调用现有顺序流程：

```text
CreateIntentTask
  → GetTask（QUEUED / SEARCHING 时继续轮询）
  → SUCCEEDED 后请求 ListTaskCandidates
  → 对 List 实际返回的每名候选人请求 Candidate Detail
```

执行页面展示：

- Query 总数；
- 待执行、执行中、成功和失败数量；
- 当前 `input_id`；
- 当前接口阶段；
- 已执行时间；
- 最新失败信息；
- 当前结果文件或归档状态。

MVP 使用定时刷新即可，不要求实时推送。

### 11.3 Candidate Detail 失败策略

某一名候选人的详情请求失败时：

1. 保存 List 中的候选人基本信息；
2. 记录 `candidate_id`、失败阶段和错误；
3. 继续请求剩余候选人；
4. Query 标记为“部分候选人详情失败”；
5. 报告和明细能够筛选此类记录；
6. 不将失败候选人伪装成字段为空的正常候选人。

### 11.4 历史数据导入

支持：

- `results.jsonl`；
- `failures.jsonl`；
- Query 元数据 JSONL；
- 现有结果 Excel；
- 基准数据 JSONL；
- 基准数据 Excel。

导入要求：

- 校验必需字段和文件格式；
- 显示成功、失败和跳过数量；
- 保留原文件名、导入时间和数据类型；
- 相同文件重复导入时提示，不静默覆盖；
- Excel 缺少原始 JSON 时标记“历史结构化数据”；
- JSONL 与 Excel 导入后使用统一的 Query、Task 和 Candidate 模型。

### 11.5 原始数据中心

#### 11.5.1 Run 列表

每个 Run 展示：

- Evaluation；
- 系统版本；
- Query 数；
- 成功、失败、无候选人和部分详情失败数量；
- 开始和结束时间；
- 数据来源；
- 处理状态；
- 复核状态；
- 报告状态。

#### 11.5.2 Query 列表

每个 Query 一行：

- `person_id`；
- `query_id/input_id`；
- `query_stage`；
- `task_id`；
- Task 状态；
- GetTask 候选人总数；
- List 实际返回人数；
- 详情成功数；
- 详情失败数；
- `llm_cost`、`total_cost` 和 `pdl_called` 占位状态；
- 处理和复核状态。

支持分页、排序、关键词搜索以及按状态、检索条件筛选。

#### 11.5.3 Query 详情

展示：

1. 输入线索和脱敏后的请求参数；
2. CreateIntentTask 结果；
3. GetTask 最终结果；
4. List 返回的全部候选人；
5. 候选人排名、`rank_score` 和详情状态；
6. Task 级预留字段；
7. 失败记录；
8. 原始 JSON 入口。

#### 11.5.4 Candidate 详情

业务视图展示：

- Summary；
- Profile；
- Social；
- Photos；
- Insights；
- 当前候选人判定；
- 字段复核结果。

原始视图支持：

- 展开和收起 JSON；
- 搜索字段名和值；
- 复制字段路径和值；
- 查看数据来源接口和采集时间；
- 查看未配置的新字段。

普通 URL 可点击打开；图片 URL 可显示缩略图和原始链接。加载失败时保留原始字符串。

### 11.6 字段配置

字段配置由测试人员维护，MVP 不需要审核流程。

每个配置项至少包含：

| 配置项 | 说明 |
| --- | --- |
| `schema_version` | 字段配置版本 |
| `field_key` | 稳定逻辑字段名 |
| `display_name` | 页面展示名称 |
| `module` | Task / Candidate / 五个业务模块 |
| `source_stage` | 来源接口 |
| `source_path` | 原始 JSON 路径 |
| `data_type` | string / number / boolean / object / array / url / image |
| `array_mode` | 保留、取首项、展开或合并 |
| `empty_rule` | 空值规则 |
| `normalizer` | URL、百分比或文本规范化 |
| `scoring_role` | 命中、完整度、准确率、展示或不评分 |
| `enabled` | 是否启用 |
| `sort_order` | 展示顺序 |

配置要求：

- 保存配置时生成新的 `schema_version`；
- 新增普通字段不需要修改采集流程；
- 可以使用新配置重新处理历史原始数据；
- 每个处理结果保存字段配置快照；
- 旧报告不因字段配置更新自动变化；
- 配置路径失败时记录错误，不影响原始数据；
- 复杂结构无法通过配置表达时进入后续开发，不在 MVP 构建通用脚本系统。

### 11.7 预留字段

Task 级预留以下可空字段：

- `llm_cost`；
- `total_cost`；
- `pdl_called`。

处理规则：

- 正式接口路径未确认前保持空值；
- 报告显示“数据未接入”或缺失任务数；
- 空值不能按0计算；
- `cost_currency` 暂不进入 MVP 正式字段；
- provider、evidence 和 social_accounts 完整保留在原始响应中，暂不做结构化模块映射。

### 11.8 基准数据

每个 Person 至少包含：

- `person_id`；
- 姓名；
- 已知 Social Links；
- 22个内容字段的基准值；
- 可选证据来源；
- 基准数据版本；
- 更新时间。

MVP 支持 JSONL 和 Excel 导入，并在 Web 查看。

### 11.9 候选人判定

MVP 不使用照片规则自动判定候选人。

Social 判定建议：

1. 同平台 Social Link 明确冲突：建议 `NOT_HIT`；
2. 至少一个规范化后的 Social Link 与基准数据一致：建议 `HIT`；
3. 没有可用于判断的 Social Link：建议 `SUSPECTED`；
4. 其他情况：建议 `NOT_HIT`。

人工复核可填写：

- 最终判定：`HIT`、`NOT_HIT`、`SUSPECTED`；
- 判定原因；
- 证据；
- `reviewer`；
- `review_time`；
- `review_note`。

规则要求：

- Social Link 比较前统一去除首尾空格、末尾 `/` 和不影响账号身份的跟踪参数；
- 同平台 Link 冲突的优先级高于普通字段一致；
- 已确认 Social Link 不会回显，返回 Link 可以参与命中、完整度和准确率；
- `SUSPECTED` 在当前正式统计中按未命中处理；
- 人工修改必须保留说明。

### 11.10 字段复核

命中候选人的字段复核展示：

- 基准值；
- 返回原始值；
- 规范化值；
- 完整度得分；
- 准确率得分；
- 证据；
- 复核说明。

非命中候选人不计算准确率，只计算22个内容字段的非空完整度。

### 11.11 数据处理

处理任务输入：

- `run_id`；
- `schema_version`；
- 基准数据版本；
- 处理规则版本。

处理任务输出：

- Task 结构化字段；
- Candidate 结构化字段；
- 字段非空状态；
- 规范化值；
- 待复核项；
- 处理异常。

处理与采集分开执行。处理失败不能修改原始数据。

### 11.12 报告

MVP 支持：

- 单 Run 报告；
- baseline/candidate 配对报告；
- `FULL_NAME` 与 `FULL_NAME_SOCIAL` 横向对比；
- Web 查看；
- Excel 和静态 HTML 导出。

报告包括：

1. 执行摘要；
2. 相同检索条件版本对比；
3. 同一个人前后配对；
4. `FULL_NAME` 与 `FULL_NAME_SOCIAL` 对比；
5. 成本与 PDL 占位区；
6. 模块和字段详情附录；
7. 改善、退化、疑似和失败案例。

报告下钻：

```text
报告指标
  → 对应人物列表
  → Query
  → Candidate
  → 字段复核
  → 原始 JSON
```

静态 HTML 允许包含人物级案例，但必须显示：

- 报告生成时间；
- 数据范围；
- 系统版本；
- 基准数据版本；
- 字段配置版本；
- Mock 或真实数据标识。

### 11.13 导出

JSONL：

- 原始结果；
- 失败记录；
- 结构化结果；
- 人工复核结果。

Excel：

- 候选人明细；
- Query 对比；
- 失败记录；
- 超长 Raw 数据；
- 人工复核字段。

HTML：

- 当前 Web 报告的静态版本；
- 允许包含受控的人物级案例。

## 12. 核心指标规则

### 12.1 检索成功率

```text
检索成功率 = 存在 HIT 候选人的 Query 数 / 参与统计的 Query 数
```

`SUSPECTED` 和 `PENDING_REVIEW` 不计为成功。

### 12.2 命中候选人完整度

```text
命中候选人完整度 = 22个内容字段正确找回得分之和 / 22
```

错误、空值和无关信息不得增加完整度。

### 12.3 命中候选人准确率

```text
命中候选人准确率 =
  所有非空返回字段的准确率得分之和 / 非空返回字段数
```

未返回字段由完整度体现，不进入准确率分母。

### 12.4 非命中候选人完整度

```text
非命中候选人完整度 = 非空内容字段数 / 22
```

该指标仅表示信息填充程度，不表示内容真实。

### 12.5 成本与 PDL

MVP 先展示预留状态：

- 有正式数据时按一个 `task_id` 统计一次；
- 缺失时显示缺失，不按0处理；
- 未接入时报告不能生成虚构金额或 PDL 次数；
- 正式统计待接口路径确认后启用。

## 13. 状态

### 13.1 Run 状态

- `PENDING`；
- `RUNNING`；
- `COMPLETED`；
- `PARTIAL_FAILED`；
- `FAILED`。

### 13.2 Query 状态

- `PENDING`；
- `RUNNING`；
- `SUCCESS`；
- `NO_CANDIDATE`；
- `PARTIAL_DETAIL_FAILED`；
- `FAILED`。

### 13.3 处理与报告状态

- `UNPROCESSED`；
- `PROCESSING`；
- `PENDING_REVIEW`；
- `REVIEWED`；
- `REPORT_READY`；
- `REPORT_STALE`。

## 14. 异常与边界处理

| 场景 | MVP 处理 |
| --- | --- |
| Query 输入错误 | 标记输入失败，不启动接口任务 |
| GetTask 轮询超时 | 记录失败和已有响应，继续下一 Query |
| List 返回0人 | 标记 `NO_CANDIDATE` |
| Candidate Detail 单人失败 | 记录失败并继续剩余候选人 |
| 未知接口字段 | 完整保存在原始数据中 |
| 字段配置路径错误 | 记录处理异常，不影响原始数据 |
| 历史 Excel 缺少 Raw 数据 | 标记“历史结构化数据” |
| 基准数据缺失 | 可查看数据，不生成正式准确率 |
| 人工复核未完成 | 报告显示待复核，不生成最终结论 |
| 成本/PDL 路径未接入 | 保持空值并显示“数据未接入” |
| 重复执行或导入 | 创建新 Run 或提示重复，不覆盖旧数据 |

## 15. 安全要求

1. 不保存和展示 `.env`、token、Cookie 与完整鉴权 Header。
2. 原始请求只保留完成追溯所需的脱敏业务参数。
3. 原始数据、邮箱、社交账号和人物案例仅用于授权测试。
4. 静态 HTML 可以包含人物案例，但仅作为受控文件使用。
5. 导出内容不得把系统返回直接描述为已核实事实。
6. MVP 无权限系统，因此仅部署在受控的本地或测试环境。

## 16. 非功能需求

| 项目 | MVP 要求 |
| --- | --- |
| 数据规模 | 至少支持100人 × 2种检索条件 × 2个版本及其全部已返回候选人 |
| 可追溯性 | 报告数字可下钻到 Query、Candidate 和原始 JSON |
| 可重复性 | 相同原始数据、配置、基准数据和规则生成相同指标 |
| 原始数据保护 | 处理、复核和重新生成报告不得覆盖原始数据 |
| 扩展性 | 普通新增字段可通过配置提取 |
| 页面性能 | 列表分页，单页不加载全部 Candidate Detail |
| 可恢复性 | 单 Query 或单 Candidate 失败不丢失其他已采集数据 |
| 兼容性 | 支持现有 JSONL 和 Excel |
| 可观测性 | 可查看采集、导入、处理和报告失败原因 |

## 17. 验收标准

### 17.1 执行与导入

1. Web 可以启动 `FULL_NAME` 和 `FULL_NAME_SOCIAL` 批量检索。
2. Web 可以导入 JSONL 和 Excel 历史结果。
3. 导入后统一展示为 Run、Query 和 Candidate。
4. 重复执行或导入不会覆盖旧数据。
5. Candidate Detail 单人失败后剩余候选人继续执行。

### 17.2 原始数据

1. 可以查看100人 Query 列表。
2. 可以查看每个 Query 的全部已返回候选人。
3. 可以查看 Candidate 业务字段和完整原始 JSON。
4. 未配置的新字段仍能在原始 JSON 中查看。
5. 可以下载原始结果和失败记录。

### 17.3 字段处理

1. 测试人员可以新增和修改字段配置。
2. 保存配置生成新版本，不需要审核。
3. 新字段配置可以重新处理历史原始数据。
4. Web 与 Excel 使用同一份处理结果。
5. 配置错误不修改原始数据。

### 17.4 复核与指标

1. 可以导入 JSONL 或 Excel 基准数据。
2. 可以填写候选人判定和字段复核。
3. Social Link 来源未确认时不会自动计为正式命中。
4. 核心指标符合测试方案公式。
5. 缺少基准或复核未完成时不生成虚假正式结论。
6. 成本与 PDL 未接入时显示缺失状态。

### 17.5 报告

1. 可以生成单 Run 报告。
2. 可以生成 baseline/candidate 配对报告。
3. 可以比较 `FULL_NAME` 和 `FULL_NAME_SOCIAL`。
4. 报告指标可以下钻到人物、Query、Candidate 和原始 JSON。
5. 可以导出 Excel 和静态 HTML。
6. 静态 HTML 可以包含人物级案例和必要风险说明。

## 18. 外部依赖与非阻塞项

以下信息尚未确定，但不阻塞 MVP 主流程开发：

| 事项 | MVP 处理 |
| --- | --- |
| `llm_cost` 正式路径 | 预留空字段，完整保留原始响应 |
| `total_cost` 正式路径 | 预留空字段，完整保留原始响应 |
| `pdl_called` 正式路径 | 预留空字段，完整保留原始响应 |
| `cost_currency` 是否存在 | 暂不纳入正式字段 |
| `provider_summary` 路径 | 保留原始数据，暂不结构化 |
| 顶层 `evidence` 映射 | 保留原始数据，暂不按模块归类 |
| `social_accounts` 映射 | 保留原始数据，暂不按模块归类 |

上述路径和规则确认后，以新增字段配置或小版本需求接入，不需要重做原始数据。

## 19. MVP 交付物

1. 本地/测试环境单用户 Web；
2. Evaluation、Run、Query 和 Candidate 数据管理；
3. Web 启动 searchTool；
4. JSONL/Excel 历史数据导入；
5. 原始数据中心；
6. 字段配置和重新处理；
7. 基准数据导入与人工复核；
8. 核心指标计算；
9. 单版本与版本对比报告；
10. JSONL、Excel 和静态 HTML 导出；
11. 对应测试、使用说明和数据迁移说明。
