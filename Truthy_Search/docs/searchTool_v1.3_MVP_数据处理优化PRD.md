# searchTool v1.3 MVP 数据处理优化 PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | searchTool v1.3 MVP 数据处理优化 PRD |
| 文档版本 | v1.0 |
| 编写日期 | 2026-07-28 |
| 需求状态 | 待开发 |
| 基于版本 | searchTool v1.3 MVP |
| 需求主线 | 历史 Query 人物关联修正 → 候选人身份归类简化 → 字段对比矩阵 → 指标口径修正 |
| 核心约束 | 复用已有 Run、Raw 和 Candidate Detail，不重新请求收费接口 |

## 2. 背景

searchTool v1.3 MVP 已经支持：

- 从 Web 启动 `FULL_NAME`、`FULL_NAME_SOCIAL` 检索；
- 导入 JSONL/Excel 历史结果；
- 保存 Run、Query、Candidate、Raw 和处理快照；
- 导入版本化 Baseline；
- 使用 FieldSchema 提取字段；
- 维护人物级 `baseline_available_fields`；
- 复核候选人并生成单次或对比报告。

在真实评测 `report_5a680512bbbc4048ae860ca42330b162` 中，系统已经采集到
10 个 Query、45 个候选人和大量 Profile、Social、Summary 数据，但报告中的命中完整度、
命中准确率和非命中完整度均显示“不适用”。

排查发现问题并非原始数据整体为空，而是以下因素叠加：

1. 已运行 Query 没有 `person_id`，无法关联已导入的 Baseline Person；
2. 候选人均处于 `PENDING_REVIEW`，没有正式的 HIT/NOT_HIT/SUSPECTED 分类；
3. Baseline 已确认的可用字段与 FieldSchema 中参与评分的字段没有形成完整交集；
4. 空对象、空模块和数值0的判空规则不够准确；
5. Query 字段和 Candidate 字段使用了错误的统计分母；
6. 报告用统一的“不适用”隐藏了“未关联、待归类、未配置、确实没有分母”等不同原因。

## 3. 本次需求结论

### 3.1 已有 Run 可以修正 person_id

已有 Run 的 Query 允许补充或修改 `person_id`。修正后使用已有数据库记录和 Raw
重新生成 ProcessResult、指标和报告，不重新调用 CreateIntentTask、GetTask、
ListTaskCandidates 或 GetTaskCandidateDetail。

### 3.2 候选人复核不负责补字段

候选人“复核”的目的只是确认候选人与目标人物的身份关系，不会修改接口返回字段，
也不会让空字段变成有值字段。

本次将页面和文案中的“候选人复核”优先调整为“候选人身份归类”，避免与字段完整度复核混淆。

### 3.3 身份归类与字段完整度解耦

- 字段有没有返回，由处理器根据 Raw 自动判断；
- 没有返回的字段完整度直接记为0，不要求人工逐字段确认；
- 候选人是否为目标人物，由自动规则或测试人员完成身份归类；
- 字段准确率只有在存在 Baseline 且字段支持自动比较或人工评分时才计算。

### 3.4 两类字段需要统一可视化

系统需要同时展示并管理：

1. Baseline Person 已准备、确认可用的字段；
2. Candidate 结果中已配置提取、参与完整度或参与准确率的字段。

两类字段在“字段对比矩阵”中统一展示，但仍保持不同职责和独立开关。

## 4. 产品目标

1. 已执行 Run 缺少或错误关联 `person_id` 时，可以在 Web 修正而不重新发起检索。
2. 修正关联后，可以基于已有 Raw 一键重新处理并生成新报告。
3. 测试人员不需要因为字段为空而逐字段复核。
4. 候选人身份归类流程可以按 Query 快速完成，并清楚说明其作用。
5. Baseline 字段和 Candidate 评分字段可以在同一页面检查、筛选和配置。
6. 指标能够区分“全部候选人返回情况”“命中候选人质量”和“非命中候选人数据冗余”。
7. 空模块、空对象、Query/Candidate 作用域使用正确口径计算。
8. 报告对不可计算的指标展示明确原因，而不是统一显示“不适用”。

## 5. 成功标准

- 已有 Run 修改 `person_id` 后，不产生任何外部接口请求；
- 原始 JSONL、Raw Record 和旧 ProcessResult 保持不变；
- 系统生成新的 ProcessResult，并把旧报告标记为过期；
- 每条 Query 都能看到当前人物关联和 Baseline 匹配状态；
- 支持逐条关联和批量关联；
- 完成身份归类后，HIT/NOT_HIT/SUSPECTED 分母正确；
- 字段为空时自动进入完整度计算，不要求人工补值；
- Baseline 可用字段与评分字段不一致时，处理前明确提示；
- Query 字段只使用 Query 数作为分母；
- Candidate 字段只使用成功 Candidate Detail 数作为分母；
- `status=empty` 的模块不会因为存在空对象而被统计为模块有数据；
- 报告可以区分 `NOT_READY` 和 `NOT_APPLICABLE`；
- 现有 Run 可以在不增加检索成本的前提下重新生成正确报告。

## 6. 范围

### 6.1 本次包含

1. 已有 Run Query 的 `person_id` 修正；
2. Baseline Person 匹配建议与批量关联；
3. 使用已有数据重新处理；
4. 候选人身份归类流程优化；
5. 字段对比矩阵；
6. Baseline 字段和 Candidate 评分字段开关；
7. 字段有效交集和配置冲突检查；
8. 空值、模块返回率和作用域指标修正；
9. 报告状态和原因展示优化；
10. 历史 Run 的重新处理与新报告生成。

### 6.2 本次不包含

- 修改或伪造接口原始返回字段；
- 重新调用收费检索接口；
- 使用姓名直接自动确认身份命中；
- 使用大模型自动判断复杂字段准确率；
- 自动修改旧报告快照；
- 多用户审批和权限；
- 自动访问外部网站验证人物事实；
- 修改 Baseline 原始导入文件；
- 通用表达式或用户自定义代码执行。

## 7. 核心概念调整

### 7.1 人物关联

人物关联表示：

```text
Run Query.person_id
  → Baseline Person.person_id
```

人物关联用于找到该 Query 对应的目标人物基准，不表示某个候选人已经命中。

### 7.2 候选人身份归类

候选人身份归类表示：

```text
该 Candidate 是否为 Query 目标人物
```

支持以下状态：

| 状态 | 含义 | 是否进入正式指标 |
| --- | --- | --- |
| `HIT` | 确认为目标人物 | 进入命中完整度和准确率 |
| `NOT_HIT` | 确认不是目标人物 | 进入非命中完整度 |
| `SUSPECTED` | 疑似但不能确认 | 进入非命中/疑似统计，并单独展示 |
| `PENDING_REVIEW` | 尚未归类 | 不进入 HIT/NOT_HIT 正式分母 |

### 7.3 字段完整度

字段完整度只回答：

```text
应该返回的字段是否返回了有效值
```

字段没有返回时，完整度记为0。人工复核不会改变字段是否为空。

### 7.4 字段准确率

字段准确率回答：

```text
返回的字段值与 Baseline 是否一致
```

只有以下情况参与准确率：

- Baseline 字段有值且已启用；
- Candidate 字段非空；
- 字段配置了可执行的自动比较方式，或已完成人工评分。

Candidate 字段为空时不进入准确率分母，但会影响完整度。

### 7.5 全部候选人字段返回率

该指标不依赖身份归类，回答：

```text
所有成功返回详情的候选人中，有多少候选人返回了该字段
```

该指标必须在候选人仍为 `PENDING_REVIEW` 时正常展示，用于快速判断接口实际数据覆盖情况。

## 8. 已有 Run Query 人物关联修正

### 8.1 使用入口

在以下页面增加入口：

- Run 详情页：`管理 Query 人物关联`；
- Process 详情页：当存在未关联 Query 时显示告警和快捷入口；
- 报告详情页：当指标因未关联 Baseline 未就绪时显示修正入口。

### 8.2 页面内容

人物关联页面按 Query 展示：

| 字段 | 说明 |
| --- | --- |
| Query ID | 例如 `case-007` |
| Query Stage | `FULL_NAME` / `FULL_NAME_SOCIAL` |
| 检索姓名 | 从 FULL_NAME clue 提取 |
| Social Link | 存在时展示，不能假设回显 |
| 当前 person_id | 允许为空 |
| 当前 Baseline | 当前关联的 Baseline Person |
| 建议 Baseline | 系统按名称生成的候选建议 |
| 匹配状态 | 已关联、未关联、关联对象不存在、存在多个同名人物 |
| 操作 | 选择、清除、保存 |

### 8.3 关联方式

支持：

1. 单条 Query 手动选择 Baseline Person；
2. 按显示姓名进行批量建议；
3. 对唯一名称匹配结果批量勾选；
4. 对同名、多义或无匹配结果逐条处理；
5. 从 Baseline Person 反向查看关联的 Query。

名称匹配只用于生成建议，系统不得仅凭姓名自动保存关联。

### 8.4 保存规则

保存前必须校验：

- Run 存在；
- Query 属于该 Run；
- Baseline Version 已选择；
- `person_id` 在该 Baseline Version 中存在；
- 同一个 Query 最多关联一个 Baseline Person；
- 允许多种 Query Stage 关联同一个 Person。

保存后：

1. 更新该 Run 的 Query 人物关联；
2. 保留修改前后值、修改时间和可选备注；
3. 不修改 Raw Record；
4. 不修改原始归档 JSONL；
5. 已存在 ProcessResult 保持不可变；
6. 关联该 Run 的 READY 报告标记为 `STALE`；
7. 页面提示需要“使用已有数据重新处理”。

### 8.5 重新处理

提供按钮：

```text
使用已有数据重新处理
```

重新处理只读取：

- 已保存的 Run/Query/Candidate；
- Raw Record；
- 修正后的 Query `person_id`；
- 指定 Baseline Version；
- 指定 FieldSchema Version。

重新处理输出：

- 新的 Process ID；
- 新的字段处理快照；
- 新的身份建议；
- 新的指标；
- 可重新生成的新报告。

不得调用任何外部检索接口。

### 8.6 是否同步到 Dataset

保存人物关联时提供可选项：

```text
同时同步到原 Dataset，供未来新 Run 使用
```

默认关闭。

- 关闭：只修正当前 Run；
- 开启：当前 Run 和 Dataset Query 同时更新；
- 原始归档文件仍不修改；
- Dataset 页面展示“数据库元数据已修正，原始文件未修改”。

## 9. 候选人身份归类优化

### 9.1 页面命名

将用户可见的“候选人复核”调整为：

```text
候选人身份归类
```

辅助说明：

```text
这里只确认候选人是不是目标人物，不会修改接口返回字段。
字段为空会由系统自动计入完整度，不需要人工补字段。
```

### 9.2 Query 级快速归类

每个 Query 按排名展示候选人卡片，至少包含：

- Candidate Rank；
- Rank Score；
- Confidence Level；
- Display Name；
- Location；
- Social URL；
- Web Link；
- Profile 摘要；
- Baseline 对照摘要；
- 自动建议及证据；
- 当前身份状态。

支持以下快捷操作：

- 设为主要命中候选人；
- 标记为非命中；
- 标记为疑似；
- 确认本 Query 没有命中候选人；
- 保存并进入下一个 Query。

### 9.3 主要命中候选人

一个 Query 首版只允许指定一个“主要命中候选人”，用于：

- 检索成功率；
- 命中完整度；
- 命中准确率；
- 报告人物案例。

如果实际存在重复记录或多个身份相同候选人，可以继续标记为疑似或非主要命中，
但不能重复进入 Query 级命中分母。

### 9.4 自动建议

系统允许根据稳定证据生成建议：

- Baseline Social URL 与 Candidate Social URL 规范化后一致；
- 同平台 Social URL 明确冲突；
- 已确认的稳定人物标识一致或冲突。

系统不得仅凭以下字段自动确认 HIT：

- 姓名一致；
- Confidence Level 为 HIGH；
- Rank Score 高；
- Candidate Rank 为1。

自动建议默认不等于人工确认。后续如果需要“高置信规则自动归类”，应单独配置规则版本，
并在报告中区分 `AUTO` 与 `MANUAL` 来源。

### 9.5 字段为空时的处理

候选人身份归类后：

- 应评估字段为空：完整度为0；
- 应评估字段有值：完整度为1或按集合覆盖率计算；
- 字段为空不要求用户复核；
- 字段值是否正确，按 compare_mode 自动比较或进入人工准确率复核。

### 9.6 没有命中候选人的 Query

测试人员确认“本 Query 没有命中候选人”后：

- 检索成功记为0；
- 命中完整度和命中准确率对该 Query 不适用；
- 已归类为 NOT_HIT/SUSPECTED 的候选人继续计算非命中完整度；
- 报告展示“已确认无命中”，不能继续显示“待复核”。

## 10. 字段对比矩阵

### 10.1 产品定位

新增“字段对比矩阵”，统一查看：

```text
Baseline 有什么
  × Candidate 提取什么
  × 哪些字段参与完整度
  × 哪些字段参与准确率
  × 使用什么方式比较
```

### 10.2 使用入口

提供以下入口：

- FieldSchema 详情页：`字段对比矩阵`；
- Baseline Version 详情页：`查看字段覆盖与评分配置`；
- Process 创建页：处理前配置检查；
- Process 详情页：查看本次实际使用的不可变配置快照。

### 10.3 矩阵字段

| 列 | 说明 |
| --- | --- |
| Module | Candidate/Insights/Photos/Profile/Social/Summary |
| Field Key | 系统稳定字段名 |
| Display Name | 页面名称 |
| Baseline 有值人数 | 当前 Baseline Version 中非空人数/总人数 |
| Baseline 可用人数 | 打开人物级可用开关的人数 |
| Baseline 可用开关 | 当前人物是否将该字段纳入基准 |
| Candidate 提取开关 | FieldSchema `enabled` |
| Candidate 有值率 | 当前 Process 实际非空率 |
| 完整度开关 | `scoring_role` 是否包含 `completeness` |
| 准确率开关 | `scoring_role` 是否包含 `accuracy` |
| 身份证据开关 | `scoring_role` 是否包含 `identity` |
| Compare Mode | exact/normalized_text/set/url_set/manual |
| Normalizer | 当前规范化规则 |
| Baseline 示例 | 脱敏/截断后的一个示例值 |
| Candidate 示例 | 当前 Process 的一个示例值 |
| 状态 | 可比较、仅完整度、需人工、配置冲突、无数据 |

### 10.4 开关职责

#### A. Baseline 可用开关

作用域：`Baseline Version + Person + Field`

表示：

```text
该人物的该字段已经准备好，可以作为基准
```

关闭时，该字段不进入该人物的命中完整度和准确率分母。

#### B. Candidate 提取开关

作用域：`FieldSchema Version + Field`

表示：

```text
是否从 Candidate/Query 数据源提取该字段
```

关闭时不提取、不展示、不评分。

#### C. 完整度开关

表示：

```text
该字段是否参与字段返回完整度
```

#### D. 准确率开关

表示：

```text
该字段是否参与与 Baseline 的值比较
```

### 10.5 有效字段交集

某人物的命中完整度有效字段集合为：

```text
Baseline 可用字段
∩ Candidate 已启用提取字段
∩ scoring_role 包含 completeness 的字段
```

某人物的命中准确率有效字段集合为：

```text
Baseline 可用字段
∩ Candidate 已启用提取字段
∩ scoring_role 包含 accuracy 的字段
∩ compare_mode 可执行或已完成人工评分的字段
```

### 10.6 配置冲突提示

处理前必须检查：

- Baseline 已打开，但 Candidate 未提取；
- Candidate 已提取，但未参与任何指标；
- 字段参与准确率，但 compare_mode 为 `manual` 且没有人工评分入口；
- Baseline 与 Candidate 数据结构不一致；
- URL 字符串数组与 URL 对象数组直接比较；
- 字段参与完整度，但所有 Baseline Person 都没有值；
- 字段参与准确率，但 Baseline 字段为空；
- Query 字段被配置为 Candidate 作用域，或反之。

存在冲突时允许保存草稿，但不能无提示创建正式 Process。

### 10.7 推荐字段策略

| 字段类型 | 完整度 | 准确率 | 推荐 compare_mode |
| --- | --- | --- | --- |
| 姓名、位置、描述 | 支持 | 支持 | `normalized_text` |
| Social URL、Web URL | 支持 | 支持 | `url_set` |
| 平台、Handle | 支持 | 支持 | `set` |
| 简单布尔/数值 | 支持 | 视业务含义 | `exact` |
| Profile 复杂对象 | 支持 | 首版人工 | `manual` |
| Photos 复杂对象 | 支持 | 首版人工或专用图片规则 | `manual` |
| Avatar/Primary Image URL | 支持返回率 | 不建议比较 URL 字符串 | `manual` 或仅完整度 |
| 状态字段 | 用于模块状态 | 通常不参与人物准确率 | `exact`/display |

### 10.8 URL 对象数组统一

对于以下 Candidate 返回结构：

```json
[
  {
    "platform": "x",
    "title": "X",
    "url": "https://twitter.com/example"
  }
]
```

参与 URL 对比前必须提取 `.url`，再执行 URL 规范化。

Baseline 字符串 URL 数组不能直接与 Candidate 对象数组执行集合比较。

## 11. 指标口径修正

### 11.1 指标分层

报告指标分为三层：

#### A. 执行与原始返回指标

不依赖 Baseline 和身份归类：

- Query 执行成功率；
- 有候选人率；
- 无候选人率；
- Candidate Detail 成功率；
- 全部候选人字段返回率；
- 模块有数据率；
- 成本、耗时和 PDL 字段接入状态。

#### B. 身份结果指标

依赖候选人身份归类：

- 检索成功率；
- HIT/NOT_HIT/SUSPECTED/PENDING 数量；
- Rank 命中情况；
- Confidence 分布。

#### C. 字段质量指标

依赖 Baseline 和字段配置：

- 命中完整度；
- 命中准确率；
- 非命中完整度；
- 模块级和字段级完整度/准确率。

### 11.2 空值分类

字段处理结果统一分为：

| 分类 | 示例 | 是否算有值 |
| --- | --- | --- |
| 有效值 | 非空字符串、有效数组、有效对象 | 是 |
| 正常空值 | `null`、空字符串、空数组 | 否 |
| 空模块容器 | `status=empty` 且内容数组为空 | 否 |
| 有效数值0 | 真实业务值0 | 按字段 empty_rule |
| 缺失路径 | 可选字段不存在 | 否，不报处理错误 |
| 结构错误 | 类型与字段配置冲突 | 否，记录处理错误 |

### 11.3 模块有数据率

模块有数据不能仅根据对象是否存在判断。

优先规则：

1. 模块存在标准 `status` 时：
   - `status=data`：进入内容有效性检查；
   - `status=empty`：模块无数据；
   - 其他状态：按明确映射处理或记为未知。
2. 没有标准状态时，按模块核心内容字段判断。
3. 状态字段本身不能让模块被判为“有业务数据”。

首版核心内容规则：

| 模块 | 有数据条件 |
| --- | --- |
| Insights | `status=data` 且至少一个有效 item |
| Photos | `status=data` 且至少一张有效照片，或业务确认0为有效结果 |
| Profile | `status=data` 且至少一个 Section Item 有值 |
| Social | `status=data` 且至少一个有效 Profile |
| Summary | 至少一个配置的核心 Summary 字段非空 |

### 11.4 Query/Candidate 作用域

| value_scope | 数据来源 | 分母 |
| --- | --- | --- |
| `QUERY` | processed_queries | 有效 Query 数 |
| `CANDIDATE` | processed_candidates | Candidate Detail 成功数 |

禁止：

- 使用45个 Candidate 作为 `task_id`、成本、耗时字段分母；
- 使用10个 Query 作为 Social、Profile、Summary 字段分母；
- 在同一个字段返回率中混用两种作用域。

### 11.5 非命中完整度

非命中完整度计算对象：

```text
身份状态为 NOT_HIT 或 SUSPECTED
且 Candidate Detail 成功
```

单候选人非命中完整度：

```text
非空的完整度字段数
÷
当前 FieldSchema 中启用的 Candidate 完整度字段数
```

非命中候选人不使用目标人物 Baseline 值判断准确率，但可以衡量返回了多少无关人物数据。

`PENDING_REVIEW` 不进入正式非命中完整度，但其“全部候选人字段返回率”必须正常展示。

### 11.6 命中完整度

命中完整度以人物为单位：

```text
有效字段交集中实际返回的字段得分之和
÷
有效字段交集数量
```

集合字段允许按覆盖率计算，不强制只有0或1。

### 11.7 命中准确率

命中准确率仅对 Candidate 非空字段计算：

```text
与 Baseline 匹配的返回字段得分之和
÷
实际返回且可比较的字段数
```

不允许把空字段作为准确率0重复处罚；空字段已经通过完整度体现。

## 12. 报告状态与文案

### 12.1 状态定义

| 状态 | 含义 | 展示文案 |
| --- | --- | --- |
| `READY` | 指标可以正式计算 | 展示正式值 |
| `NOT_READY` | 数据准备或身份归类未完成 | 展示原因和修正入口 |
| `NOT_APPLICABLE` | 业务上确实没有适用分母 | 展示不适用原因 |
| `NOT_CONNECTED` | 接口字段尚未接入 | 展示未接入 |
| `PARTIAL` | 部分数据可计算 | 展示已有值及缺失数量 |

### 12.2 不允许统一显示“不适用”

以下情况必须分别展示：

- Query 未关联 Baseline；
- 候选人待身份归类；
- 没有 HIT 候选人；
- 没有已确认的 NOT_HIT/SUSPECTED 候选人；
- Baseline 可用字段为空；
- Baseline 字段与评分字段没有有效交集；
- compare_mode 不可执行；
- Task 公共字段未接入；
- 业务上确实没有分母。

### 12.3 报告修正入口

报告详情页根据原因提供：

- 管理 Query 人物关联；
- 进入候选人身份归类；
- 查看字段对比矩阵；
- 使用已有数据重新处理；
- 生成新报告。

## 13. 数据与版本策略

### 13.1 不可变数据

以下数据不允许覆盖：

- Raw Record；
- 原始归档 JSONL/Excel；
- 旧 ProcessResult；
- 旧 FieldSchema Version；
- 旧报告快照。

### 13.2 可修正元数据

允许修正：

- 当前 Run Query 的 `person_id`；
- 可选的 Dataset Query `person_id`；
- 关联备注；
- 身份归类；
- 人工字段准确率评分。

### 13.3 新快照

以下操作必须生成新 ProcessResult：

- 修改 Query `person_id`；
- 更换 Baseline Version；
- 发布或更换 FieldSchema Version；
- 修改参与完整度/准确率的字段配置；
- 修改字段 normalizer 或 compare_mode。

仅修改身份归类时，可以令指标和报告过期并重新计算，不需要重新提取 Raw 字段。

## 14. 交互流程

### 14.1 历史 Run 修复流程

```text
打开已有 Run
  → 系统提示 10 条 Query 未关联 Baseline
  → 进入“管理 Query 人物关联”
  → 选择 Baseline Version
  → 按姓名生成匹配建议
  → 人工确认 person_id
  → 保存关联
  → 选择 FieldSchema
  → 查看字段对比矩阵与冲突提示
  → 使用已有数据重新处理
  → 完成候选人身份归类
  → 生成新报告
```

整个流程不调用检索接口。

### 14.2 新 Run 推荐流程

```text
导入 Dataset
  → 导入时校验 person_id
  → 选择 Baseline Version
  → 运行前预检人物关联
  → 执行检索
  → 处理字段
  → 身份归类
  → 生成报告
```

## 15. 验收场景

### 15.1 已有 Run 补 person_id

前置条件：

- Run 已执行完成；
- 已有 results.jsonl 和 Raw；
- Query `person_id` 为空；
- Baseline 已导入。

验收：

1. 页面可选择对应 Baseline Person；
2. 保存后 Query 显示已关联；
3. 外部接口请求次数为0；
4. 旧 Process 和旧报告仍可查看；
5. 旧报告标记为过期；
6. 可使用已有数据生成新 Process；
7. 新 Process 可以读取 Baseline 可用字段。

### 15.2 候选人字段为空

前置条件：

- Candidate 已归类为 HIT；
- Baseline 有15个有效字段；
- Candidate 只返回10个。

验收：

- 命中完整度按10/15或集合覆盖率计算；
- 5个空字段自动记为完整度0；
- 不要求用户逐字段确认“确实为空”；
- 准确率只使用返回且可比较的字段。

### 15.3 没有命中候选人

前置条件：

- Query 返回3个候选人；
- 测试人员确认全部不是目标人物。

验收：

- 检索成功率记为0；
- 命中完整度和准确率显示“无命中候选人，不适用”；
- 3个候选人进入非命中完整度；
- 报告不再显示“候选人待复核”。

### 15.4 PENDING_REVIEW 仍有数据

前置条件：

- 45个候选人尚未身份归类；
- Profile 45个有数据；
- Social 34个有数据。

验收：

- 全部候选人 Profile 返回率显示100%；
- Social 返回率显示34/45；
- HIT/NOT_HIT 指标显示待身份归类；
- 不把全部字段指标统一显示为不适用。

### 15.5 空模块

输入：

```json
{
  "status": "empty",
  "data": {
    "count": 0,
    "items": []
  }
}
```

验收：

- 模块有数据判定为否；
- 对象存在不等于有业务数据；
- 不产生字段处理错误。

### 15.6 Query/Candidate 分母

前置条件：

- 10个 Query；
- 45个 Candidate；
- 10个 `task_id` 有值；
- 34个 Candidate 的 Social 有值。

验收：

- `task_id` 返回率为10/10；
- Social 返回率为34/45；
- 不出现 `task_id=0/45`。

### 15.7 字段配置冲突

前置条件：

- Baseline 打开15个字段；
- FieldSchema 只有1个字段参与 completeness。

验收：

- 字段对比矩阵明确显示14个配置冲突；
- 创建 Process 前给出具体字段列表；
- 不允许报告只输出0/0而不说明原因。

## 16. 历史数据兼容

1. 旧 Run 不自动修改；
2. 旧 ProcessResult 不自动覆盖；
3. 旧报告保持原快照；
4. 历史 Run 可以选择补充 `person_id`；
5. 有 Raw 的 Run 支持完整重新处理；
6. 只有结构化结果、没有 Raw 的历史 Run，按现有字段重新计算并标记数据边界；
7. 新字段配置不会改变旧 ProcessResult；
8. 新报告必须记录使用的 Run、Baseline、FieldSchema、处理规则和指标规则版本。

## 17. 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| 姓名相同导致关联错误 | 姓名只生成建议，保存前人工确认 |
| 修改 Run 元数据影响旧报告 | 旧快照不变，关联报告标记过期 |
| 重新处理被误认为重新检索 | 按钮明确写“使用已有数据重新处理”，记录接口请求为0 |
| 一键把剩余候选人设为非命中造成误判 | 保存前展示影响人数并二次确认 |
| Baseline 与 Candidate 数据结构不同 | 字段对比矩阵提前提示 |
| 空对象造成虚高返回率 | 使用模块状态和核心内容规则 |
| 评分字段版本变化导致结果不可复现 | Process 固定 FieldSchema Version 和规则版本 |
| 人工准确率工作量过大 | 首版只对 `manual` 字段按需复核 |

## 18. 建议实施优先级

### P0：恢复已有评测可用性

1. 已有 Run Query 人物关联管理；
2. 使用已有数据重新处理；
3. 报告未就绪原因和修正入口；
4. Query/Candidate 作用域分母修正。

### P1：修正字段评分

1. 字段对比矩阵；
2. Baseline/Candidate 双开关；
3. 有效字段交集预检；
4. URL 对象数组规范化；
5. 空模块和复杂对象空值规则。

### P2：降低人工成本

1. Query 级身份归类工作台；
2. 主要命中候选人快捷选择；
3. 自动身份建议与证据展示；
4. 批量保存并进入下一 Query；
5. 报告完整展示自动/人工归类来源。

## 19. 最终交付结果

本需求完成后，测试人员可以：

1. 修正已经执行且已经产生费用的 Run；
2. 不重新请求接口即可关联 Baseline；
3. 清楚区分候选人身份、字段完整度和字段准确率；
4. 在同一矩阵查看 Baseline 字段和 Candidate 评分字段；
5. 快速发现字段配置冲突；
6. 使用正确的空值和作用域口径重新计算指标；
7. 生成可以解释“不适用/未就绪”原因的新报告。
