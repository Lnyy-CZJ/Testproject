# searchTool v1.3 MVP 字段配置与数据处理优化 PRD

> 文档版本：v1.1  
> 状态：已确认字段来源与首版规则，待开发  
> 适用范围：searchTool 本地 Docker / 单用户 MVP  
> 术语说明：本文使用“基准人物字段”和“检索候选字段”作为内部工程术语；最终产品展示名称必须以 `GetTaskCandidateDetail.ui_sections` 的模块和字段定义为来源，待接口字段口径补全后统一配置，不在代码中硬编码。

## 1. 背景与问题

当前平台已经能够从已入库的 Task、Candidate 和 Candidate Detail Raw 中提取字段，并支持无成本重处理、基准关联、候选人身份判定与报告生成。但字段配置的业务语义尚不完整：

1. 当前字段配置以 `source_path` 提取为主，字段的展示、基准对比、版本对比和评分职责没有清晰分离；
2. 一份字段配置中已提取多个模块字段，但正式质量指标只由少数字段参与，用户难以理解“字段已返回”与“字段已计分”的差异；
3. 基准人物资料与检索候选资料的比较，以及不同检索批次之间的结果对比，混在同一字段口径中；
4. `Profile Data`、`Photos Data` 等完整 JSON 对象直接使用 `exact` 比较时，容易因返回结构不同得到无意义的 0 分；
5. 平台缺少以 Insights、Photos、Profile、Social、Summary 为核心的模块树和子字段开关，测试人员无法直观维护字段参与范围。

本需求的目标是将字段配置升级为“数据处理规则中心”：同一份字段定义同时控制提取、展示、两类对比和指标参与，且不改变既有 Raw 数据与历史 Process 快照。

## 2. 目标

### 2.1 业务目标

1. 清晰区分基准人物资料与检索候选资料；
2. 支持“基准人物字段 vs 检索候选字段”的人物资料评估；
3. 支持“本次检索字段 vs 上次检索字段”的版本回归评估；
4. 让模块、子字段、比较方式和评分参与范围都可配置、可追溯；
5. 让报告能够解释每一项指标的数据来源、分子、分母与不适用原因。

### 2.2 非目标

1. 本期不增加新的检索接口调用，不修改 HTTP 请求流程；
2. 本期不修改 Raw 原始响应，也不回写历史采集结果；
3. 本期不要求实现复杂语义模型、LLM 自动评判或图片视觉比对服务；
4. 本期不实现多人审批、字段配置审核流或角色权限体系。

## 3. 核心术语与数据边界

| 名称 | 定义 | 数据来源 |
|---|---|---|
| 基准人物字段 | 已知目标人物的参考资料，用于判断人物资料是否覆盖、是否正确 | Baseline JSONL / Excel 导入 |
| 检索候选字段 | 检索接口返回的单个候选人字段 | 已入库 Candidate Detail、Candidate List、Task Raw |
| 模块字段 | Insights、Photos、Profile、Social、Summary 五个业务资料模块 | Candidate Detail `ui_sections` |
| 执行字段 | Task、Candidate 等检索过程和排序字段 | Task / Candidate 接口结果 |
| 基准对比 | 基准人物字段与已判定主命中候选人的资料比较 | 人物资料评估 |
| 版本对比 | 两个可比 Process / Run 的字段和指标比较 | 回归测试评估 |
| 字段快照 | Process 创建时冻结的字段配置版本 | 不可变 Process 快照 |

### 3.2 已确认的字段来源

检索候选资料字段的唯一业务来源为 `GetTaskCandidateDetail` 响应中的 `ui_sections`。字段配置页的模块名称、展示名称和字段目录必须由该响应结构维护；Task、Candidate 仅作为执行与版本对比信息，不得混入人物资料模块。

本期以已提供的响应样例作为首版字段目录。接口新增子字段时，系统必须允许在相应模块下新增字段配置，不需要修改既有 Raw 或覆盖历史 Process。

### 3.1 两类对比必须分开

#### A. 基准对比：基准人物字段 vs 检索候选字段

仅适用于已确认 `HIT` 且被选为主命中的候选人。参与模块为：

- Insights
- Photos
- Profile
- Social
- Summary

Task 和 Candidate 字段不参与基准人物资料对比，因为它们不存在对应的基准人物值。

#### B. 版本对比：本次检索结果 vs 上次检索结果

适用于相同评测条件下的两个 Process / Run。可比较全部启用字段：

- Task：成本、耗时、第三方调用；
- Candidate：候选数量、排名、Rank Score；
- 五个业务资料模块：字段返回率、准确度、覆盖率、变化情况。

## 4. 用户角色与使用场景

### 4.1 测试人员

1. 在字段配置页查看所有模块与子字段；
2. 决定字段是否提取、展示、参与基准对比、参与版本对比；
3. 选择字段的比较方式与指标角色；
4. 以无成本重处理方式应用新配置；
5. 在报告中查看模块、字段和指标解释。

### 4.2 评测查看者

1. 查看某个主命中候选人与基准人物的字段对比；
2. 查看某次检索的资料覆盖率、准确度和身份命中情况；
3. 查看两个版本在 Task、Candidate 和资料模块上的变化；
4. 下钻到 Raw、字段值及评分原因。

## 5. 字段配置优化需求

### 5.1 字段树

字段配置页按以下树形结构展示：

```text
执行与候选信息
├── Task
│   ├── task_id
│   ├── llm_cost
│   ├── third_party_cost
│   ├── total_cost
│   ├── pdl_called
│   └── search_duration_ms
└── Candidate
    ├── candidate_id
    ├── candidate_rank
    └── rank_score

人物资料模块
├── Insights
├── Photos
├── Profile
├── Social
└── Summary
```

每个模块可展开查看子字段；模块级设置作为默认值，子字段可单独覆盖。模块关闭时，子字段配置不删除，只在当前字段配置版本中处于非生效状态。

### 5.1.1 `ui_sections` 首版原子字段目录

以下目录来自已确认的 `GetTaskCandidateDetail.ui_sections` 样例。所有字段首版均应可登记、提取和展示；是否纳入基准对比、完整度、准确度由字段开关决定。

| 模块 | 字段键 / 来源路径 | 类型或说明 |
|---|---|---|
| Insights | `ui_sections.insights.status` | 模块状态 |
| Insights | `ui_sections.insights.data.count` | Insights 数量 |
| Insights | `ui_sections.insights.data.items` | 完整 Items 数组，保留 Raw / 格式化展示 |
| Insights | `ui_sections.insights.data.items[*]` | 动态 Insight 对象；已知或后续新增子键可独立登记，例如 `description`、`links` |
| Photos | `ui_sections.photos.status` | 模块状态 |
| Photos | `ui_sections.photos.data.authenticity_photos` | 真实性照片列表 |
| Photos | `ui_sections.photos.data.baseline_photo_url` | 基准照片 URL |
| Photos | `ui_sections.photos.data.identity_match_rate` | 照片身份相似度；正式路径 |
| Photos | `ui_sections.photos.data.match_photos` | 匹配照片列表 |
| Profile | `ui_sections.profile.status` | 模块状态 |
| Profile | `ui_sections.profile.data.sections` | 完整 Profile 分组数组，保留 Raw / 格式化展示 |
| Profile | `ui_sections.profile.data.sections[*].title` | 分组标题，例如 Identity、Career、Background |
| Profile | `ui_sections.profile.data.sections[*].items[*].label` | 动态字段标签 |
| Profile | `ui_sections.profile.data.sections[*].items[*].value` | 动态字段值；由“分组标题 + 标签”映射为原子字段 |
| Social | `ui_sections.social.status` | 模块状态 |
| Social | `ui_sections.social.data.private_accounts` | 私有账号列表 |
| Social | `ui_sections.social.data.profiles[*].display_handle` | 展示账号 |
| Social | `ui_sections.social.data.profiles[*].platform` | 平台 |
| Social | `ui_sections.social.data.profiles[*].url` | Social URL |
| Social | `ui_sections.social.data.profiles[*].username` | 用户名 |
| Summary | `ui_sections.summary.status` | 模块状态 |
| Summary | `ui_sections.summary.data.age` | 年龄 |
| Summary | `ui_sections.summary.data.avatar_url` | 头像 URL |
| Summary | `ui_sections.summary.data.candidate_id` | 返回候选 ID |
| Summary | `ui_sections.summary.data.confidence_level` | 置信度等级 |
| Summary | `ui_sections.summary.data.disclaimers` | 免责声明列表 |
| Summary | `ui_sections.summary.data.display_name` | 显示姓名 |
| Summary | `ui_sections.summary.data.education` | 教育摘要 |
| Summary | `ui_sections.summary.data.generate_time` | 生成时间 |
| Summary | `ui_sections.summary.data.headline` | 职业 / 标题摘要 |
| Summary | `ui_sections.summary.data.is_best_match` | 是否最佳匹配 |
| Summary | `ui_sections.summary.data.is_top_result` | 是否首位结果 |
| Summary | `ui_sections.summary.data.jobs` | 职位列表 |
| Summary | `ui_sections.summary.data.location` | 地点 |
| Summary | `ui_sections.summary.data.match_reasons` | 匹配原因列表 |
| Summary | `ui_sections.summary.data.match_score` | 匹配分数 |
| Summary | `ui_sections.summary.data.more_social_count` | 更多社交账号数量 |
| Summary | `ui_sections.summary.data.person_id` | 人物 ID |
| Summary | `ui_sections.summary.data.primary_image` | 主图对象或空值 |
| Summary | `ui_sections.summary.data.profile_url` | 主资料 URL |
| Summary | `ui_sections.summary.data.report_expires_at` | 报告过期时间 |
| Summary | `ui_sections.summary.data.social_links[*].platform` | Summary Social 平台 |
| Summary | `ui_sections.summary.data.social_links[*].title` | Summary Social 标题 |
| Summary | `ui_sections.summary.data.social_links[*].url` | Summary Social URL |
| Summary | `ui_sections.summary.data.social_platforms` | Summary 平台列表 |
| Summary | `ui_sections.summary.data.web_links[*].platform` | Web Link 平台 |
| Summary | `ui_sections.summary.data.web_links[*].title` | Web Link 标题 |
| Summary | `ui_sections.summary.data.web_links[*].url` | Web Link URL |

Profile 的 `sections[*].items[*]` 属于动态标签结构。首版必须支持按 `title + label` 登记为原子字段，例如：

```text
Identity / Full Name
Identity / Location
Identity / Profile URL
Career / Current Role
Background / Education
```

如果接口返回新的 Profile 分组或标签，先保留在完整 `sections` 值中，并在字段配置页显示“待配置字段”；测试人员可通过开关将其发布为新的原子字段，无需改代码。

### 5.2 字段配置属性

每个字段至少应具备以下属性：

| 属性 | 说明 |
|---|---|
| `field_key` | 稳定字段标识，不因展示名称变化而变化 |
| `display_name` | 页面、Excel、报告显示名称 |
| `module` | Task、Candidate、Insights、Photos、Profile、Social、Summary |
| `parent_field_key` | 可选；用于模块下的原子子字段层级 |
| `value_scope` | `TASK` 或 `CANDIDATE` |
| `candidate_source_path` | 从检索候选响应提取字段的路径 |
| `baseline_field_key` | 对应的基准人物字段键；无对应关系时为空 |
| `normalizer` | 文本、URL、百分比、列表、Profile 分组等规范化方式 |
| `compare_mode` | 对应字段的比较方式 |
| `enabled` | 是否参与本版本数据处理 |
| `display_enabled` | 是否在页面、Excel、报告展示 |
| `baseline_compare_enabled` | 是否参与基准人物资料对比 |
| `run_compare_enabled` | 是否参与版本对比 |
| `identity_enabled` | 是否参与身份判定 |
| `completeness_enabled` | 是否参与资料完整度 |
| `accuracy_enabled` | 是否参与资料准确度 |
| `weight` | 可选；模块或字段加权时使用，默认 1 |
| `missing_policy` | `EMPTY` 或 `ERROR` |

### 5.3 开关规则

1. `enabled = false`：不提取、不展示、不计分，但历史字段快照保持可查看；
2. `display_enabled = false`：仍可提取和计算，但默认不在候选人详情、Excel 与报告展示；
3. `baseline_compare_enabled = true`：要求配置 `baseline_field_key`，才能进入基准对比；
4. `run_compare_enabled = true`：允许进入 Process / Run 版本变化比较；
5. `identity_enabled = true`：仅允许用于已定义的强绑定规则，首版仅支持 Social URL 与照片身份相似度；
6. `completeness_enabled = true`：字段进入资料覆盖计算；
7. `accuracy_enabled = true`：字段必须具备可解释的 `compare_mode`，不允许完整 JSON 直接用 `exact` 自动计入准确率。

首版默认策略：所有 `ui_sections` 字段均登记为“可提取、可展示”；除身份强绑定字段外，完整度和准确度开关默认关闭，由测试人员按模块或子字段显式开启。这样接口字段扩展不会在未确认口径前影响正式报告。

### 5.4 推荐默认配置

| 模块 | 提取/展示 | 基准对比 | 版本对比 | 身份判定 |
|---|---:|---:|---:|---:|
| Task | 是 | 否 | 是 | 否 |
| Candidate | 是 | 否 | 是 | 否 |
| Insights | 是 | 是 | 是 | 否 |
| Photos | 是 | 是 | 是 | `photos_identity_match_rate` 可启用 |
| Profile | 是 | 是 | 是 | 否 |
| Social | 是 | 是 | 是 | `social_urls` 可启用 |
| Summary | 是 | 是 | 是 | 否 |

已确认：首版不启用模块或字段权重。所有已启用且同属一个指标分母的字段默认等权，即每个字段权重均为 `1`；字段权重配置入口可预留，但不在首版 UI 中开放。

## 6. 数据处理规则

### 6.1 无成本重处理流程

```text
已入库 Raw / Candidate / Query
        ↓
冻结字段配置版本
        ↓
按 candidate_source_path 提取字段
        ↓
记录字段值、空值、提取错误
        ↓
执行身份规则并选出主命中
        ↓
执行基准对比与字段评分
        ↓
计算模块、字段、Query、Run 指标
        ↓
生成不可变 Process 与报告快照
```

此流程不得调用检索 HTTP 接口，不得覆盖 Raw、Candidate 或旧 Process。

### 6.2 身份判定规则

保持既有规则：

1. 同平台 Social Link 不一致 → `NOT_HIT`；
2. 至少一个 Social Link 一致 → `HIT`；
3. 否则照片身份相似度 `>= 80%` → `HIT`；
4. Social 与照片均无法判断 → `SUSPECTED`，统计时按不命中；
5. 其他情况 → `NOT_HIT`。

同一 Query 有多个 `HIT` 时，按 `rank_score` 最高者确定主命中；分数相同再按候选排名最小者确定。所有 `HIT` 均展示各自的命中资料完整度与准确度，但只有主命中进入该 Query 的基准人物资料完整度与准确度汇总。

### 6.3 字段比较方式

| 比较方式 | 适用场景 | 完整度 | 准确度 |
|---|---|---|---|
| `presence` | 图片、Profile 大对象、Insights 大对象 | 返回非空为 1，否则 0 | 不自动评分 |
| `exact` | 布尔、枚举、稳定 ID | 非空并相同为 1 | 相同为 1，否则 0 |
| `normalized_text` | 姓名、短文本、地点 | 返回非空为 1 | 大小写/空白规范化后相同为 1 |
| `set` | 平台、标签、普通链接 | 交集 ÷ 基准集合数 | 交集 ÷ 返回集合数 |
| `url_set` | Social URL | URL 规范化后按集合计算 | URL 规范化后按集合计算 |
| `semantic_text_lite` | 地点、职位、教育、短/中等文本描述 | 返回非空为 1，否则 0 | 返回 0–1 的轻量语义相似度 |
| `manual` | Profile 分组、长描述、复杂结构 | 可配置为 presence | 等待人工复核 |

完整 JSON 字段，例如 `profile_data`、`photos_data`、`summary_social_links`，首版不得以对象整体 `exact` 进入准确度；应使用 `presence`、拆分子字段或人工复核。

#### 6.3.1 轻量语义相似规则

已确认地点、职位、教育和长文本需要语义相似规则。首版采用本地、可解释、无需调用外部模型的 `semantic_text_lite`：

1. 统一大小写、空白、常见标点和 URL 尾部格式；
2. 规范化后完全一致，得分 `1.0`；
3. 一方文本包含另一方时，得分不低于 `0.8`；
4. 其他文本按词元集合重叠度计算；无空格文本按连续字符片段重叠度计算，结果范围 `0–1`；
5. 字段配置可设置“自动判定阈值”，首版默认 `0.6`；低于阈值的值仍保留相似度，但标记为“建议人工复核”；
6. 不使用 LLM，不访问网络，不改变原始文本。

该规则适用于 `summary_location`、`summary_headline`、`summary_education`、`summary_jobs` 及从 Profile 分组拆出的地点、职位、教育字段。人物姓名与 Social URL 仍使用强规则，不使用语义相似度代替身份判定。

### 6.4 模块与子字段处理

模块层指标由其启用子字段聚合：

```text
模块完整度 = Σ(子字段完整度 × 子字段权重) / Σ(已纳入完整度的子字段权重)
模块准确度 = Σ(可自动评分子字段准确度 × 子字段权重) / Σ(可评分子字段权重)
```

若一个模块的所有子字段均未配置为准确度，则模块准确度显示 `N/A`，不得显示为 0。

Photos 的 `ui_sections.photos.data.identity_match_rate` 为已确认的正式照片身份相似度来源路径。该字段可开启 `identity_enabled`，并沿用 `>= 80%` 命中、`< 80%` 不可通过照片判定命中的规则。

## 7. 报告与指标口径

### 7.1 报告分区

报告必须拆为以下三个分区，禁止混用口径：

1. **检索与身份结果**：有候选人率、主命中率、Social 冲突率、照片命中率、待判断率；
2. **基准人物资料质量**：Insights、Photos、Profile、Social、Summary 的覆盖率和准确度；
3. **版本回归结果**：Task、Candidate 与五个资料模块相对上一批 Process 的变化。

### 7.2 Query 级指标

| 指标 | 分子 | 分母 |
|---|---|---|
| 检索成功率 | `HIT_CONFIRMED` Query 数 | 已完成身份归类 Query 数 |
| 主命中资料完整度 | 主命中候选人的已配置完整度字段分数 | 该人物可用且启用完整度的字段权重 |
| 主命中资料准确度 | 主命中候选人的可自动评分字段准确度 | 返回非空且可评分字段权重 |
| 非命中资料完整度 | 已确认 `NOT_HIT/SUSPECTED` 候选人的非空完整度字段数 / 已启用完整度字段数，不比较 Baseline 值 | 已确认非命中候选人数 |
| 非命中基准字段重叠度 | 已确认 `NOT_HIT/SUSPECTED` 候选人与 Baseline 的可比较字段覆盖/交集，单独用于误召回与身份冲突分析 | 有可比较基准字段的非命中候选人数 |

### 7.3 Run 级指标

Run 级指标为 Query 级指标的加权或非加权平均，报告必须同时显示：

- 指标值；
- 分子；
- 分母；
- 适用状态：`READY`、`PARTIAL`、`NOT_READY`、`NOT_APPLICABLE`；
- 不适用或未就绪原因；
- 字段配置版本、Baseline 版本、Process ID。

### 7.4 字段返回率与模块返回率

字段返回率不等于准确率：

```text
字段返回率 = 返回非空的成功 Candidate 数 / 成功 Candidate 总数
模块返回率 = 模块至少有一个启用子字段非空的成功 Candidate 数 / 成功 Candidate 总数
```

它们用于观察接口数据覆盖，不用于证明候选人身份正确。

## 8. 页面需求

### 8.1 字段配置页

1. 提供模块树、展开/收起、模块级和子字段级开关；
2. 展示字段来源路径、基准映射、规范化方式、比较方式、评分角色；
3. 支持筛选：模块、启用状态、基准对比、版本对比、身份、完整度、准确度；
4. 展示字段配置预览：基准样本、候选样本、数据形状、潜在冲突；
5. 发布时创建不可变新版本，不覆盖旧版本。

### 8.2 基准对比页

对每个 Query 的主命中候选人展示：

| 模块 | 子字段 | 基准人物值 | 检索候选值 | 完整度 | 准确度 | 比较说明 |
|---|---|---|---|---:|---:|---|

复杂 JSON 默认展示摘要、数量与“查看格式化 JSON”入口；不得在表格中直接铺开超长对象。

### 8.3 版本对比页

1. 显示 Task、Candidate 与资料模块的变化；
2. 同时显示绝对值、变化值和变化方向；
3. 对无可比基准、字段配置不同、输入集不同的情况明确标记“不可比”并说明原因；
4. 允许按模块、字段、Query Stage、人物筛选。

### 8.4 报告页

1. 顶部明确展示“身份命中”“资料质量”“版本回归”三种口径；
2. 每项指标可展开查看公式、分子分母、涉及字段与 Query 列表；
3. 人物案例至少展示基准值、主命中值、字段判断和 Raw 下钻入口；
4. Excel 导出与 Web 报告使用同一 Process 快照，避免数字不一致。

## 9. 历史兼容与数据迁移

1. 旧 `field-schema` 与旧 Process 必须保持可读；
2. 历史报告保留原指标快照，不重新计算、不静默变化；
3. 新字段配置版本可兼容旧字段：缺少新属性时使用默认值；
4. 旧字段默认映射建议：
   - `enabled = true`；
   - `display_enabled = true`；
   - `run_compare_enabled = true`；
   - 仅 `social_urls` 保留现有身份、完整度、准确度角色；
   - 其他字段默认不进入正式质量总分，等待测试侧配置后启用；
5. 对已有 Run 重新处理时，必须新建 Process，不覆盖既有 Process。

## 10. 验收标准

1. 能在字段配置页按模块和子字段查看全部字段；
2. 模块级关闭后，其子字段在新 Process 中不生效，旧 Process 不受影响；
3. 子字段可独立开启基准对比、版本对比、完整度、准确度和展示；
4. Task / Candidate 字段不出现在“基准人物资料对比”表中；
5. Task / Candidate 字段能出现在“版本回归”表中；
6. 基准对比页能同时展示基准人物值、主命中候选值、比较方式、完整度、准确度与原因；
7. `profile_data`、`photos_data` 等复杂对象不会因整体结构不同被错误计入自动准确度；
8. 报告中每个正式指标均可查看分子、分母、状态、原因及字段配置版本；
9. 新配置无成本重处理不调用检索 HTTP 接口，不修改 Raw；
10. 历史报告、历史 Process 与旧字段配置仍可打开和导出。

## 11. 已确认与待确认事项

### 11.1 已确认

1. 最终产品展示名称以 `GetTaskCandidateDetail.ui_sections` 的模块与字段为来源；工程内部暂保留“基准人物字段”“检索候选字段”，待接口字段口径补全后统一配置展示名称；
2. 首版字段目录以第 5.1.1 节的 `ui_sections` 全量子字段为准；动态 Insights Item 与 Profile 标签结构必须支持后续在字段配置页新增原子字段；
3. 所有 `ui_sections` 字段首版均可提取和展示；是否进入完整度、准确度由模块/子字段开关决定，默认关闭，避免未确认字段影响正式报告；
4. 首版不开放模块或字段权重，所有启用字段默认等权；
5. 地点、职位、教育和长文本使用 `semantic_text_lite` 本地轻量语义规则，不调用 LLM 或外部服务；
6. 照片身份相似度正式路径为 `ui_sections.photos.data.identity_match_rate`，身份阈值为 `80%`；
7. `social_urls` 与照片身份相似度保留为首版身份强绑定字段。

### 11.2 待确认

`llm_cost`、`third_party_cost`、`total_cost`、`pdl_called`、`cost_currency` 的正式接口返回路径尚未提供。首版在字段配置中保留这些字段和展示位置，但不生成虚构数据、不进入成本正式指标；收到接口契约后通过新字段配置版本启用。
