# Log 工具 V4 People Insight 检索日志分析 PRD

文档版本：v1.1  
产品版本：V4  
文档状态：评审已确认  
更新日期：2026-08-13  
目标用户：测试工程师、后端工程师  

## 一、产品定位

在现有 Log 过滤工具的 method 过滤和接口统计能力上，增加一项只面向 People Insight 检索任务的专项分析能力。

用户粘贴一份完整检索日志后，工具应自动还原任务输入、任务终态、LLM、Public Figure、PDL、Social Profile、图片反查、Face Comparison、候选结果和成本链路，并根据固定业务规则输出：

- 实际执行链路。
- 已确认正常项。
- 已确认异常项。
- 需要后端确认的问题。
- 因日志缺失而无法判断的项目。
- 每条结论对应的原始字段和日志证据。

该能力用于辅助测试排查，不替代原始日志、接口契约和人工最终判断。

## 二、背景与现状

### 2.1 当前工具能力

当前代码实际实现到 V1.5，支持：

- 粘贴日志。
- 提取和精确筛选 method。
- 清理 Flutter 控制台前缀。
- 提取 `request_id`、`trace_id` 和 HTTP 状态码。
- 统计接口请求、响应、成功、失败和未响应次数。
- 搜索、复制和导出过滤后的日志。

V2 的单次请求关联和 V3 的失败分析目前只有 PRD，尚未实现。

### 2.2 当前排查痛点

People Insight 检索不是一个接口成功就代表整体正确，而是多工作线、多 Provider 的组合流程。测试人员目前需要人工完成：

```text
查找任务输入和task_id
→ 对齐GetTask终态
→ 从Debug中还原Agent工具调用顺序
→ 判断LLM、Wiki、PDL fallback是否合理
→ 检查Social Profile是否调用、去重和合并
→ 检查图片反查和Face Comparison
→ 对齐候选列表、详情和Debug字段
→ 汇总每个Provider成本
→ 判断是业务无结果、技术失败还是诊断不一致
```

日志往往包含多次 GetTask 轮询、大段 JSON、倒序返回的 `agent_tool_calls` 和重复诊断字段，人工排查耗时且容易漏项。

### 2.3 历史问题表明需要专项分析

此前真实任务已出现过以下类型的问题：

- LLM 技术错误被归类为普通 `NO_RESULT/NO_MATCH`。
- LLM 达到 max_tokens 后无法判断是否存在可恢复候选。
- Public Figure 在免费 Wiki Remote 前调用高成本 PDL。
- Wiki 同名歧义、Wiki 候选和 PDL 候选处理不正确。
- 用户输入或 Provider 新发现的社交 URL 未执行 Social Profile。
- Social Profile 成功但未与人物候选合并。
- 图片公开出现、人脸相似和疑似盗图语义混用。
- Debug、Report、候选接口和停止原因不一致。
- Provider 已调用但成本缺失或被错误显示为 0。

这些问题可以沉淀为稳定规则，并通过可选 AI 说明提高报告可读性。

## 三、产品目标

### 3.1 核心目标

1. 将单个 People Insight 检索任务的日志解析为统一任务快照。
2. 按真实时间还原 Agent 和 Provider 调用链路。
3. 用固定规则检查路由、候选、社交、图片、状态和成本完整性。
4. 每条结论都提供可核对证据，不输出无证据的确定性根因。
5. 在不改变现有 Log 过滤功能的前提下接入专项分析。
6. 模型不可用时，确定性分析仍能正常完成。

### 3.2 成功标准

- 已标注的正常链路样本能还原正确调用顺序，不误报确定性 Bug。
- 已标注的历史 Bug 样本能命中对应异常规则。
- `agent_tool_calls` 无论接口返回顺序如何，都按 `start_time` 升序展示。
- 能区分 HTTP 成功、业务无结果、技术失败和证据不足。
- Provider 分项成本与任务总成本可以自动核对。
- 缺少 Debug、Cost 或候选详情时明确显示“无法判断”，而不是推断为未调用。
- AI 关闭、超时或返回非法内容时，规则报告仍可查看。
- 现有 Log 工具功能和测试全部保持通过。

## 四、用户与核心场景

### 4.1 用户角色

| 用户 | 主要诉求 |
| --- | --- |
| 测试工程师 | 快速判断一条检索链路是否按方案执行、是否需要提 Bug |
| 后端工程师 | 根据 task_id、工具时间线和证据字段定位异常阶段 |
| 产品或项目负责人 | 查看功能完整性和未实现能力，不阅读完整原始日志 |

### 4.2 核心场景

#### 场景一：姓名检索无结果

用户粘贴完整日志，工具回答：

- LLM 是正常无结果、截断还是技术失败。
- 是否调用 Wiki Remote。
- 是否调用 PDL，调用的是 Identify 还是 Search。
- 为什么停止，以及最终 `NO_RESULT` 是否合理。

#### 场景二：知名人物路由

工具检查：

```text
Public Figure Local
→ LLM
→ Wiki Remote
→ PDL fallback
```

是否符合当前策略，并发现 Wiki 唯一可靠命中后仍调用 PDL 等问题。

#### 场景三：姓名加社交链接

工具检查：

- 输入 Link 是否进入 Social Profile。
- LLM、Wiki、PDL 新发现 Link 是否进入队列。
- canonical URL 是否去重。
- Social Profile 成功结果是否绑定并合并到正确候选。
- 姓名与 Link 冲突是否被记录和处理。

#### 场景四：姓名加照片

工具检查：

- 图片工作线是否执行。
- Lens、Vision fallback 是否合理。
- `found_online` 是否只表示公开出现。
- Face Comparison 是否执行；未执行时是否明确返回 `not_performed`。
- 用户图片是否被错误用作未验证候选头像。

#### 场景五：成本排查

工具汇总每个真实 Provider 调用的操作、状态、缓存、用量和成本，并判断：

- `UNPRICED` 是否被错误解释为免费。
- 缓存命中是否仍产生计费。
- Report、Debug 和 Cost Summary 是否一致。
- 是否存在可避免的高成本 PDL 调用。

## 五、分析原则

### 5.1 证据优先

所有结论必须落入以下四类之一：

| 分类 | 定义 |
| --- | --- |
| 已确认正常 | 日志字段和规则能够直接证明链路符合预期 |
| 已确认异常 | 实际字段与明确规则直接冲突 |
| 需要确认 | 存在矛盾或可疑行为，但日志不足以确认根因 |
| 无法判断 | 缺少必要接口、字段或原始响应 |

### 5.2 禁止错误推断

- HTTP 200 不等于业务成功。
- 单个工具 `status=error` 不等于整个任务失败。
- 没有看到工具记录不等于工具一定未调用，需先判断日志覆盖度。
- Provider 返回候选不等于候选通过质量门。
- Wiki `hit` 不等于 Wiki 结果唯一且可用。
- `found_online` 不等于身份一致，也不等于盗图。
- `face_comparison_status=not_performed` 不等于相似度为 0。
- `estimated_cost_microunit=0` 在 `UNPRICED` 时不代表免费。

### 5.3 确定性规则优先于 AI

- 路由、状态、字段和成本判断由程序规则完成。
- AI 只负责整理、解释和生成易读报告。
- AI 不得修改结构化事实、规则结果和证据引用。
- AI 不得将“需要确认”改写为“已确认异常”。

## 六、V4 MVP 功能范围

### 6.1 分析入口

在现有页面增加“分析检索链路”入口：

- 直接使用“日志内容”文本框中的原始日志。
- 允许把同一 task 的主流程日志、GetSearchTaskDebug 和 GetProviderCostSummary 响应依次粘贴到同一个文本框；支持带接口标签或可由 `debug/cost_summary` 根字段识别的独立响应，不要求这些片段在文本中的物理顺序与真实调用时间一致。
- 不要求用户先选择 method。
- 日志为空时禁止提交并提示原因。
- 分析过程中显示加载状态，避免重复提交。

### 6.2 单任务识别

首版只分析一份日志中的一个 People Insight 任务。

系统应提取：

- 搜索姓名。
- 输入线索：`FULL_NAME`、`SOCIAL_LINK`、`PHOTO`。
- `task_id`、`query_id`、`request_id`、`trace_id`、`client_request_id`。
- 创建任务、轮询任务、候选列表和候选详情记录。

如果识别到多个不同 `task_id`：

- 不自动混合分析。
- 返回识别到的 task_id 列表。
- 提示用户先过滤为单一任务后重新分析。

### 6.3 日志覆盖度

分析开始时先显示本次日志包含哪些证据：

| 证据 | 作用 |
| --- | --- |
| CreateIntentTask / RefineTask | 识别原始输入 |
| GetTask | 判断任务状态、候选数和终态 |
| ListTaskCandidates | 判断最终候选、排序和概要字段 |
| GetTaskCandidateDetail | 判断候选详情和证据字段 |
| GetSearchTaskDebug | 还原路由、工具调用和诊断 |
| GetProviderCostSummary | 核对分项和任务成本 |

缺失项必须显示，不因缺失导致页面崩溃。

### 6.4 实际链路还原

从 Debug 中提取并按 `start_time` 升序展示：

- Provider。
- Provider operation。
- 开始和结束时间。
- 状态、HTTP 状态码和错误码。
- 是否缓存命中。
- 候选数或资料数。
- 单次估算成本。
- fallback 和停止原因。

支持识别的主要步骤：

```text
Search Agent
Public Figure Local
LLM Search
Public Figure Route Decision
Wiki Remote
PDL Person Identify / Person Search
Social Profile Extraction
Image Materializer
Google Lens / Google Vision
Face Comparison
Finalizer / Report
```

### 6.5 路由规则检查

首版至少检查：

| 规则 | 预期 |
| --- | --- |
| Local 可用命中 | 跳过 LLM、Wiki Remote 和 PDL，后续 Social/图片扩展不受影响 |
| LLM 强结果 | 不调用不必要的 PDL |
| Public Figure Local miss 且 LLM 弱、无结果或失败 | 先评估 Wiki Remote，再决定 PDL |
| Wiki 唯一可靠命中 | 直接返回并跳过 PDL |
| Wiki 无结果、失败或同名歧义 | 允许继续 PDL fallback |
| LLM/Provider 技术失败 | 不得错误归类为普通 `NO_MATCH` |
| 预算或 deadline 耗尽 | 停止原因和最终状态必须对应 |

如果任务命中 Local negative cache 等策略，但日志没有提供对应规则版本，应标记“需要确认”，不能直接判错。

当前正式生效的 Public Figure、PDL、Social Profile 和图片策略版本以《优化后检索功能测试报告》（https://kcnarqdur71j.feishu.cn/wiki/MAtnwS5ZdiK5TWk5ORUcZV6lnlg ，2026-08-11）为准（评审确认）。

### 6.6 候选一致性检查

检查 GetTask、候选列表、候选详情、Debug 和 Report 中：

- 候选数量和最高分。
- `candidate_id`、`person_id` 和 Provider 来源。
- `match_score`、`confidence_level`、`decision`、`selected`。
- `matched_clue_types` 和 `match_reasons`。
- `is_top_result` 和 `is_best_match`。
- 头像、社交链接和公开来源。
- 相同 canonical URL 是否被拆成重复候选。
- Wiki、LLM、PDL、Social Profile 同一人物是否正确合并。

首版不尝试仅凭自然语言资料自动判断现实世界中“究竟是不是同一个人”；只有存在明确 ID、canonical URL 或直接冲突时才给出确定结论。

### 6.7 Social Profile 检查

检查：

- 输入社交 URL 是否有队列记录。
- Provider 新发现的受支持 URL 是否被调用或记录明确跳过原因。
- 相同 canonical URL 是否最多真实调用一次。
- 账号不存在、私密、不可访问和 Provider 技术错误是否正确分类。
- 成功资料是否进入候选的姓名、简介、头像、地区、邮箱、社交账号和网站字段。
- `social_profile_merged_candidate_count` 等诊断值是否与最终候选一致。

### 6.8 图片和 Face Comparison 检查

检查：

- 有用户图片时是否规划 Reverse Image Search，或记录明确跳过原因。
- 主 Provider 无可用结果或失败后，fallback 是否符合策略。
- `found_online`、`no_public_match`、`unknown` 状态和来源是否一致。
- 用户上传图片是否被直接用作候选头像。
- 同时存在用户图片和候选头像时，Face Comparison 是否执行或明确为 `not_performed`。
- 未执行 Face Comparison 时，不输出人脸相似或不相似结论。
- Face Comparison 未接入期间作为“已知能力缺失”展示，不计为任务异常（评审确认）。

图片本身不作为 PDL 人物检索的身份线索；图片工作线和人物 fallback 需要分开解释。

### 6.9 成本检查

检查：

- LLM、PDL、Social Profile、Reverse Image 等外部调用的分项成本。
- `CALCULATED`、`NON_BILLABLE`、`PARTIAL` 和 `UNPRICED` 状态。
- 缓存命中是否正确为不计费。
- Debug、Report 和 GetProviderCostSummary 总成本是否一致。
- PDL Person Identify 和 Person Search 的调用类型、计费单位和返回数量。

多币种或缺少价卡时只显示现状并标记无法完整核对，不做汇率换算。

### 6.10 规则报告与 AI 说明

规则分析完成后输出固定报告：

```text
总体结论
日志覆盖度
实际执行链路
Provider与成本明细
已确认正常项
已确认异常项
需要后端确认
日志不足、无法判断
```

当服务端配置了允许使用的 LLM 时（评审确认：测试环境使用与功能测试智能体一致的 LLM 端点和模型）：

- 将脱敏后的结构化任务快照和规则结果交给模型。
- 使用仓库内版本化的 People Search Log Analyzer Skill 提示词生成简洁说明。
- 模型调用失败时回退到程序生成的固定报告。

### 6.11 复制和导出

- 支持复制分析报告。
- 支持将报告导出为 `.md` 文件。
- 导出仍使用服务端固定目录，客户端不能指定任意路径；评审确认 Report Markdown 默认导出目录继续复用现有配置。
- 原始日志只有用户主动使用现有导出按钮时才落盘。

## 七、页面要求

保持当前单页 Flask 结构，不引入 SPA 或新的前端框架。

在现有“过滤结果”和“接口分析”之外增加一个“检索链路分析”区域：

1. “分析检索链路”按钮。
2. 分析状态：未分析、分析中、完成、证据不足、失败。
3. 总体结论。
4. 日志覆盖度。
5. 实际调用时间线。
6. 问题与证据列表。
7. 成本摘要。
8. 复制报告、导出 Markdown。

首版使用文本、简单表格和折叠原始证据，不做复杂关系图和可拖拽编排。

## 八、结果状态

| 状态 | 含义 |
| --- | --- |
| `NORMAL` | 已执行的规则未发现异常，且关键证据完整 |
| `ISSUES_FOUND` | 至少存在一条已确认异常 |
| `NEEDS_CONFIRMATION` | 没有确认异常，但存在需要后端确认的问题 |
| `INCOMPLETE_EVIDENCE` | 缺少关键日志，无法完成主要判断 |
| `UNSUPPORTED_LOG` | 未识别到 People Insight 检索任务 |

“未发现异常”只表示在当前日志和规则范围内未发现，不代表现实身份一定正确。

## 九、异常与降级处理

| 场景 | 处理方式 |
| --- | --- |
| 日志为空 | 返回参数错误，不开始分析 |
| 未识别到 People Insight 接口 | 返回 `UNSUPPORTED_LOG` |
| 存在多个 task_id | 返回 task_id 列表，提示先过滤 |
| JSON 不完整 | 保留可解析内容，记录解析警告 |
| 缺少 Debug | 输出客户端可见链路，Provider 顺序标记无法判断 |
| 缺少 Cost Summary | 展示 Debug 内成本，标记未完成独立核对 |
| Evidence Packet 被截断 | 明确显示截断，不给出“链路完整”结论 |
| AI 未配置 | 返回规则报告，AI 状态为 `DISABLED` |
| AI 超时、限流或非法响应 | 返回规则报告，AI 状态为 `FAILED` |
| 单条规则解析异常 | 跳过该规则并记录 warning，不影响其他规则 |

## 十、安全与隐私

### 10.1 数据处理

- 默认只在当前请求内存中处理日志和分析结果。
- 不新增数据库和分析历史。
- 不自动上传、调用或重试 People Insight 接口。
- 只有用户主动导出报告时才写入文件。
- 页面分析结果和导出的 Markdown 报告只展示脱敏证据；现有原始日志导出仍由用户主动触发。

### 10.2 AI 调用前脱敏

发送给模型前必须清理：

- Authorization、Access Token、Refresh Token、Cookie、密码和密钥。
- 用户图片 Base64、二进制内容和签名参数。
- 与分析无关的长文本和原始响应。

评审确认允许把邮箱、手机号发送给模型，首版不对这两类字段脱敏。canonical 社交 URL、Provider、状态、分数和成本等分析必需字段可以保留。带签名的图片 URL 应去除 query 参数。

### 10.3 Prompt Injection 防护

- 日志内容一律视为不可信数据。
- 日志中的任何“忽略规则”“修改结论”等文本不得作为模型指令执行。
- 模型只能读取结构化 Evidence Packet，不能执行日志中的命令或 URL。
- 模型输出只能作为 Markdown 文本展示，不直接渲染任意 HTML。

## 十一、MVP 非目标

- 不实现通用任意业务日志的 AI 根因分析。
- 不实现 V2/V3 的全部通用请求关联和失败分析能力。
- 不支持多日志批量统计。
- 不支持修复前后两份日志自动对比。
- 不自动创建、提交或更新 Bug。
- 不自动修复或重试接口。
- 不接入实时日志流、CLS、OpenTelemetry 或分布式 Trace。
- 不新增数据库、Redis、Celery、消息队列或向量库。
- 不使用 Agent 自由规划、多模型编排或 RAG。
- 不承诺在日志缺失时判断唯一根因。
- 不自动判断现实世界人物身份正确率。

以下能力放入后续版本评估：

- 修复前后对比。
- 一键生成既有格式的 Bug Markdown。
- 多任务批量汇总和测试报告。
- 规则版本选择和管理页面。

## 十二、验收标准

### 12.1 功能验收

1. 可以从单任务日志中提取姓名、线索和主要 ID。
2. 可以识别六类核心接口及缺失情况。
3. 可以按 `start_time` 还原 Agent 工具调用顺序。
4. 可以区分 HTTP 成功、业务无结果和技术失败。
5. 可以检查 Local、LLM、Wiki Remote 和 PDL 的路由顺序。
6. 可以识别 PDL Identify 与 Person Search，并展示成本。
7. 可以检查输入和新发现社交 URL 的调用、去重和结果。
8. 可以发现 Social Profile 成功但候选合并或诊断不一致。
9. 可以检查 Reverse Image fallback 和图片状态语义。
10. Face Comparison 未执行时不会输出 0% 或不相似结论。
11. 可以检查候选 score、confidence、decision、selected 和 matched clues 一致性。
12. 可以核对 Provider 分项成本和任务总成本。
13. 每个异常和疑问都包含接口、JSON path 或日志片段证据。
14. 缺少关键日志时输出 `INCOMPLETE_EVIDENCE`，不会编造结论。
15. 规则报告可以复制并导出 Markdown。

### 12.2 稳定性验收

1. 不完整 JSON、未知字段和新增字段不会导致页面崩溃。
2. 多 task 日志不会被静默混合。
3. AI 未配置、超时或失败时规则分析仍可用。
4. 发送 AI 前能够完成敏感字段脱敏。
5. 现有日志过滤、统计、导出、平台前缀、CSRF 和健康检查不受影响。
6. 现有单元测试全部继续通过。

### 12.3 回归样本

首版至少准备以下脱敏测试夹具：

| 样本 | 预期 |
| --- | --- |
| Public Figure Local 命中 | 跳过 LLM、Wiki 和 PDL |
| LLM 弱结果、Wiki 唯一命中 | Wiki 在 PDL 前，PDL 跳过 |
| Wiki 同名歧义 | 继续 PDL，同时保留歧义信息 |
| LLM 截断 | 显示截断、可恢复候选和修复重试状态 |
| 姓名加输入 Link | Social Profile 必须有调用或明确跳过原因 |
| Provider 发现重复 Link | canonical URL 只真实调用一次 |
| Social 成功但未合并 | 输出候选合并异常 |
| Lens 无结果、Vision 成功 | 图片 fallback 和 `found_online` 正确 |
| Face 未接入 | 显示 `not_performed` 和“已知能力缺失”，不解释为 0%，不计为任务异常 |
| PDL 多个弱候选 | 不将 `UNRESOLVED/selected=false` 解释为可靠命中 |
| 成本完整 | 分项和总成本一致 |
| 成本缺价卡 | 明确 `UNPRICED`，不解释为免费 |

## 十三、发布边界与阶段

### 阶段一：规则分析 MVP

- 完成日志结构化、任务快照、时间线、规则审计和固定报告。
- 不依赖 AI 即可上线内部测试。

### 阶段二：可选 AI 说明

- 接入经批准的 OpenAI-compatible LLM 端点；评审确认测试环境使用与功能测试智能体一致的端点和模型。
- AI 功能默认关闭，配置完成后开启（评审确认）。
- 加载版本化 Skill 提示词。
- 验证脱敏、超时和失败降级。

### 阶段三：评估增强项

- 根据实际使用反馈决定是否增加日志对比、Bug 模板和批量报告。
- 不在 MVP 中预建扩展框架。

## 十四、评审结论（2026-08-13 确认）

1. 测试环境允许使用的 LLM 端点、模型与功能测试智能体使用的 LLM 一致。
2. AI 功能默认关闭，配置完成后开启。
3. 当前正式生效的 Public Figure、PDL、Social Profile 和图片策略版本以《优化后检索功能测试报告》（https://kcnarqdur71j.feishu.cn/wiki/MAtnwS5ZdiK5TWk5ORUcZV6lnlg ，2026-08-11）为准。
4. 允许把邮箱、手机号发送给模型，首版不对这两类字段脱敏。
5. Report Markdown 的默认导出目录继续复用现有配置。
6. Face Comparison 未接入期间作为“已知能力缺失”展示，不计为任务异常。
