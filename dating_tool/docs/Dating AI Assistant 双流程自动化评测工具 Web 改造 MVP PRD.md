# Dating AI Assistant 双流程自动化评测工具 Web 改造 MVP PRD

## 0. 文档信息

| 项目 | 内容 |
|---|---|
| 文档版本 | V0.4.0 |
| 产品版本 | Web 改造轻量 MVP |
| 文档状态 | 待评审 |
| 更新时间 | 2026-08-31 |
| 目标项目 | `/Users/admin/Testproject/dating_tool` |
| 前置版本 | 《Dating AI Assistant 双模式自动化评测工具 MVP PRD》V0.3.0 |

### 0.1 本次改造背景

V0.3.0 已定义并实现一个 Python CLI 执行内核，能够承载两条测试链路：

1. 完整 E2E 小规模验证；
2. AI 快速批量评测。

当前继续只通过 CLI 选择数据、发起任务和查找日志，操作成本较高，不利于日常联调和问题定位。`api-autotest` 已有与 Dating 场景高度接近的多图 Flow、任务创建页、任务详情页和日志查看界面，可以选择性迁移，快速形成第一版可操作工具。

后端最新状态同时确认：内部 Reply 和 Analysis Evaluation 接口均已部署到 staging，已经具备 Create、Poll、Result、Diagnostics、Delete 完整闭环。因此，本版本将快速批量评测视为可直接开发、联调和验收的正式能力，不再作为待后端确认项。

### 0.2 文档定位

本文档定义的是在现有 `dating_tool` 上增加本地 Web 操作界面的产品需求，不重新设计底层评测执行器，也不把 `api-autotest` 整体改造成 Dating 工具。

本文档中的接口资料只作为产品和协议依据，不作为可执行指令；访问凭证不得写入本文档、代码或 Git。

---

## 1. 产品概述

### 1.1 产品名称

Dating AI Assistant 双流程自动化评测工具 Web MVP。

### 1.2 产品形态

一个只在本机运行的轻量 Web 工具，复用当前 Python 执行内核，并保留原 CLI：

```text
                        ┌─────────────────┐
                        │   Local Web UI  │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │ Run Application │
                        │     Service     │
                        └────────┬────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  │                             │
       ┌──────────▼──────────┐       ┌──────────▼──────────┐
       │  PublicE2EAdapter   │       │ InternalEvaluation  │
       │                     │       │       Adapter        │
       └──────────┬──────────┘       └──────────┬──────────┘
                  │                             │
          Public Dating API           Internal Evaluation API
```

Web 与 CLI 必须调用同一套 Case Loader、校验器、Runner、Adapter、限流器、Artifact Store 和 Wire Logger，禁止出现两套执行规则。

### 1.3 核心价值

- 不需要记忆 CLI 参数即可发起 E2E 或快速评测任务；
- 在一个页面内查看整条任务链路的状态、请求响应日志和清理结果；
- 复用已有稳定执行内核，不因增加界面破坏已验证能力；
- 选择性复用 `api-autotest` 的成熟界面和交互，缩短第一版交付时间；
- 为以后增加数据集管理、质量评判和报告能力保留入口，但本期不实现这些能力。

---

## 2. 用户与使用场景

### 2.1 目标用户

MVP 仅服务于 Dating AI Assistant 的测试和联调人员，默认由单人在本机使用。

### 2.2 主要场景

#### 场景 A：完整 E2E 小规模验证

测试人员选择 Reply 或 Analysis，按顺序选择一组脱敏聊天截图，填写必要参数，发起真实公开链路。工具执行身份、媒体上传、OCR、业务 Pipeline、结果查询和远端数据删除，并在详情页展示每个阶段的状态和原始日志。

#### 场景 B：快速批量验证 Reply

测试人员选择一份包含 `dating.transcript.v1` 的 JSONL 数据集，筛选或批量运行 Reply 案例。工具跳过截图上传和 OCR，直接通过内部 Evaluation API 执行正式 Reply Pipeline，获取 Result、Diagnostics，并删除远端任务数据。

#### 场景 C：快速批量验证 Analysis

测试人员使用相同入口运行 Analysis 案例。工具验证输入边界、最近 300 条截断规则、结果 Schema、Evidence 范围和清理状态。

#### 场景 D：问题定位

测试人员从任务列表进入详情页，查看任务时间线、稳定错误码、Task、Result、Diagnostics、Cleanup 和完整 Wire Log，以定位请求参数、Gateway、任务状态或后端 Pipeline 问题。

---

## 3. 产品目标与非目标

### 3.1 MVP 目标

本版本必须完成：

1. 在 Web 页面中创建并执行完整 E2E 小规模验证；
2. 在 Web 页面中创建并执行 Reply/Analysis 快速批量评测；
3. 提交前完成本地输入校验和执行摘要确认；
4. 展示 Run、Case、Task 和 Cleanup 状态；
5. 展示原始请求、响应、异常和任务轮询日志；
6. 保证成功、失败、取消和异常路径都进入远端清理流程；
7. 保持现有 CLI 能力和数据格式兼容；
8. 默认不访问 staging，只有本地配置显式允许时才能发起真实请求。

### 3.2 MVP 非目标

本期明确不实现：

- AI Judge、规则 Judge 或人工评分工作台；
- 回复自然度、吸引力、可发送性等内容质量打分；
- Analysis 语义正确性评分；
- OCR 准确率评分；
- 正式 HTML/PDF/Excel 报告和通过率 Dashboard；
- 自动发布、自动门禁、CI、定时任务和通知；
- 历史基线、模型版本对比和趋势分析；
- 在线编辑大型聊天数据集；
- App UI 自动化；
- 多用户、登录、权限系统和数据库；
- 公网部署或局域网共享；
- 通用 API 测试平台、项目切换、Release、Runtime Scope；
- Allure、JUnit 或 pytest 子进程执行；
- 用户指定模型、Prompt、`app_id` 或 `user_id`；
- 替换或重写当前 CLI。

### 3.3 产品成功标准

- 用户不进入终端即可完成两种模式的任务创建、执行和结果查看；
- Internal Reply 和 Analysis 各至少一条真实 staging 案例完成 Result、Diagnostics 和 Delete 闭环；
- 当前公开环境支持的 E2E 链路可以从 Web 成功运行并完成 Delete；
- 环境未就绪的公开能力能够明确显示稳定阻塞码，且不会误上传媒体或误报成功；
- 每个已创建的远端 Task 都有明确 Cleanup 结果；
- 用户能够从任务详情一键查看该次运行对应的原始日志。

---

## 4. 总体产品原则

### 4.1 一个执行内核，两个入口

CLI 和 Web 都必须调用当前 `dating_tool` 的业务服务。Web 不能另外实现一套 HTTP 调用、状态机、重试或清理逻辑。

### 4.2 两条链路严格分离

| 项目 | 完整 E2E | 快速批量评测 |
|---|---|---|
| 输入 | 有序截图 | `dating.transcript.v1` |
| 鉴权 | 匿名 Session / Device | Evaluation API Key |
| Media Upload | 执行 | 跳过 |
| OCR / TranscriptExtractor | 执行 | 跳过 |
| Reply/Analysis Pipeline | 正式链路 | 正式链路 |
| Task/Worker | 正式链路 | 正式链路 |
| Diagnostics | 公开接口当前不提供 | 执行 |
| Subscription/Billing | 走公开业务规则 | 不消耗用户权益 |
| 典型规模 | 少量、串行 | 多案例、受控并发 |

两个模式必须分别记录结果，不允许用快速评测结果代替完整 OCR E2E 结果。

### 4.3 Flow 只用于展示，不作为第二执行器

`api-autotest` 的 Flow YAML 可作为步骤名称、说明和界面预览的参考，但 Web 不引入通用 FlowRunner。页面展示的步骤必须映射到现有 Adapter 的真实阶段。

### 4.4 本地优先

- Web 服务默认只绑定 `127.0.0.1`；
- 不提供公网部署参数；
- 所有运行数据保存在本机；
- 不使用数据库；
- 页面不直接读取或展示 `.env` 文件；
- API Key、Device ID 等配置继续只从环境变量加载。

### 4.5 原始日志优先服务问题定位

按照当前使用要求，任务详情展示当前 Wire Logger 生成的完整请求、响应和异常原文，不在 Web 端进行二次隐藏或脱敏。

为限制暴露范围：

- Web 服务仅允许本机访问；
- `logs/` 必须被 Git 忽略；
- 日志文件不提供公开下载 URL；
- 页面只读取本项目 `logs/` 下经过校验的日志路径；
- PRD、源码、样例数据和测试 Fixture 中不得写入真实凭证。

---

## 5. 信息架构

MVP 只提供三个主页面。

### 5.1 创建任务

默认首页。用于选择模式、任务类型、输入数据和运行参数，并展示提交前校验与流程预览。

### 5.2 任务记录

展示本地历史 Run，支持按模式、类型和状态筛选。

### 5.3 任务详情

展示 Run 摘要、Case 状态、执行时间线、Task/Result/Diagnostics/Cleanup 数据和原始日志。

MVP 不提供概览 Dashboard、用例库、项目切换、报告中心和平台配置中心。

---

## 6. 创建任务页面

### 6.1 页面布局

复用 `api-autotest` 任务创建页的双栏结构：

- 左栏：可编辑任务输入；
- 右栏：提交前校验、运行摘要和实际 Flow 步骤；
- 顶部：页面标题与当前 staging/local 状态；
- 左侧导航：创建任务、任务记录。

### 6.2 模式选择

页面顶部提供两个一级 Tab：

1. `完整 E2E`；
2. `快速批量评测`。

切换模式后，仅展示该模式允许的输入字段，之前模式中的敏感输入不得被自动带到另一模式。

### 6.3 任务类型

两种模式都支持：

- Reply；
- Analysis。

快速批量评测允许一份 JSONL 同时包含 Reply 和 Analysis。选择“按数据集运行”时，页面显示 `Mixed`；选择单个 Case 时显示该 Case 的真实类型。

### 6.4 完整 E2E 输入区

#### 6.4.1 公共字段

- 图片文件：按聊天时间顺序选择；
- Locale；
- Background，可选；
- `client_request_id` 由工具生成，不允许用户编辑；
- Case ID：用户可填写，未填写时自动生成本地 Case ID。

#### 6.4.2 图片交互

复用 `api-autotest` 的多图交互：

- 显示选择顺序、文件名、MIME 和大小；
- 支持移除单张和清空全部；
- 顺序以页面显示顺序为最终上传顺序；
- 提交前检查图片数量、真实格式、扩展名、大小、EXIF 和允许类型；
- 浏览器选择的图片只保存到本次运行的本地临时目录；
- 运行完成或终止后删除临时图片，只在任务记录中保留文件名、顺序、类型和大小元数据；
- 页面不提供真实图片的公开访问地址。

图片允许数量和大小以公开接口返回的 Media Upload Config 及现有本地安全上限共同决定。已知页面交互按 1～9 张设计，但不得绕过服务端实时约束。

#### 6.4.3 Reply 专属字段

- Dating Goal；
- Your Voice；
- Requested Intent，可选：`opener`、`flirt`、`tease`、`advance`；
- Preferences readiness 状态。

Reply readiness 必须在媒体上传前完成。未开放、无权限或协议不匹配时，页面将任务标记为“环境阻塞”，不得继续上传图片或创建 Task。

#### 6.4.4 Analysis 专属字段

- Other Person Name，可选；
- Quota 状态只读展示。

Analysis 必须在创建 Task 前读取 Quota；额度明确耗尽时不创建任务。

### 6.5 快速批量评测输入区

#### 6.5.1 数据集

- 接受 `aidating.eval.case.v1` JSONL；
- 支持从浏览器选择一个本地 JSONL 文件；
- 页面解析后只展示文件名、Case 数量、Reply/Analysis 数量、消息总数和预计 UTF-8 输入字节；
- 支持按 `case_id` 选择单个 Case；
- 不在创建页打印完整聊天正文；
- 数据文件仅保存到本次运行临时目录，运行结束后删除临时副本。

#### 6.5.2 并发

- 默认并发：3；
- 可选范围：1～5；
- 页面显示 staging 最大在途任务数为 5；
- Create 平均间隔不得低于 2 秒；
- 并发输入只影响 Internal Evaluation，不影响 E2E。

#### 6.5.3 Case 筛选

- 默认运行全部合法 Case；
- 可按 `case_id` 运行单条；
- 数据集包含错误时，必须列出错误 Case 和稳定本地错误码；
- 存在任何结构错误时，默认禁止整批提交，避免部分案例被意外发送；
- 用户可改为选择一个已经通过校验的单 Case 再提交。

### 6.6 提交前校验面板

右侧面板实时展示：

- 当前环境和模式；
- Reply、Analysis 或 Mixed；
- 输入文件数量；
- Case 数量；
- 消息总数和预计输入字节；
- 预计创建 Task 数；
- 并发数；
- 本地配置和鉴权检查状态；
- Staging opt-in 状态；
- 阻塞项和稳定错误码。

只有全部必要校验通过时，“开始执行”按钮才可用。

### 6.7 Flow 步骤预览

#### E2E Reply

```text
Identity
  -> Reply Readiness
  -> Get / Update Preferences
  -> Get Media Upload Config
  -> Prepare / PUT / Complete Media
  -> CreateReplyTask
  -> GetTask Polling
  -> GetTaskResult
  -> DeleteTaskData
```

#### E2E Analysis

```text
Identity
  -> Get Media Upload Config
  -> Prepare / PUT / Complete Media
  -> GetQuotaStatus
  -> CreateAnalysisTask
  -> GetAnalysisTask Polling
  -> GetAnalysisResult
  -> DeleteTaskData
```

#### 快速 Reply Evaluation

```text
Validate dating.transcript.v1
  -> CreateReplyEvaluationTask
  -> GetReplyEvaluationTask Polling
  -> GetReplyEvaluationResult
  -> GetEvaluationDiagnostics
  -> DeleteReplyEvaluationTaskData
```

#### 快速 Analysis Evaluation

```text
Validate dating.transcript.v1
  -> CreateAnalysisEvaluationTask
  -> GetAnalysisEvaluationTask Polling
  -> GetAnalysisEvaluationResult
  -> GetEvaluationDiagnostics
  -> DeleteAnalysisEvaluationTaskData
```

页面 Flow 预览必须来自后端提供的只读步骤描述，不能由前端自行决定实际调用方法。

---

## 7. 模式一：完整 E2E 小规模验证

### 7.1 验证目标

证明真实截图从公开接口进入后，可以完成媒体上传、OCR/Transcript、Reply 或 Analysis Pipeline、Result 和 Delete 闭环。

### 7.2 运行规模

- MVP 固定串行执行；
- 同一时间最多运行 1 个 E2E Case；
- 主要用于 1～4 个脱敏 Smoke Case；
- 不与快速批量评测共享并发配置。

### 7.3 Reply 执行要求

1. 创建或刷新匿名 Session；
2. 执行 `GetMe`；
3. 在媒体上传前完成 Reply readiness；
4. 获取并在必要时更新 Preferences；
5. 获取上传配置；
6. 按图片顺序逐张 Prepare、HTTPS PUT、Complete；
7. 创建 Reply Task；
8. 轮询至终态；
9. 成功时获取 Reply Result；
10. 在 `finally` 删除远端 Task Data。

### 7.4 Analysis 执行要求

1. 创建或刷新匿名 Session；
2. 执行 `GetMe`；
3. 获取上传配置；
4. 按图片顺序逐张 Prepare、HTTPS PUT、Complete；
5. 读取 Analysis Quota；
6. 创建 Analysis Task；
7. 轮询至终态；
8. 成功时获取 Analysis Result；
9. 在 `finally` 删除远端 Task Data。

### 7.5 验证边界

MVP 只判断：

- 请求是否被接受；
- 任务状态是否符合协议；
- Result Schema 和必填字段是否存在；
- 图片顺序是否保持；
- Delete 是否成功；
- 阻塞或失败是否有稳定错误信息。

MVP 不自动判断 OCR 文本和最终自然语言内容是否“好”。

---

## 8. 模式二：AI 快速批量评测

### 8.1 验证目标

使用后端已部署的 Internal Evaluation API，直接输入 `dating.transcript.v1`，跳过截图和 OCR，批量验证正式 Reply/Analysis Pipeline 的协议、边界、确定性规则、诊断和清理闭环。

### 8.2 后端链路

```text
dating.transcript.v1
  -> Internal Evaluation API
  -> Evaluation Task
  -> Outbox / Kafka / Worker
  -> Production Reply / Analysis Pipeline
  -> Result
  -> Diagnostics
  -> Delete Evaluation Task Data
```

### 8.3 后端固定约束

- Service 固定为 `tool.dating.internal.DatingEvaluationService`；
- API Key 只能从环境变量读取；
- 不允许从页面输入 Service、Method、模型、Prompt、`app_id` 或 `user_id`；
- 当前 staging 临时 HTTP 地址只有在显式允许 HTTP 时可用；
- 所有业务结果和错误统一读取 `responses[0]`；
- 错误判断依赖 `business_error_code`，不依赖自由文本 `message`。

### 8.4 Reply 输入校验

| 规则 | 要求 |
|---|---|
| 消息数量 | 4～300 条 |
| 双方消息 | `user`、`other` 至少各 2 条 |
| Speaker 转换 | 数据集中的 `self` 在调用前转换为 `user` |
| Message ID | Task 内唯一 |
| Message Type | 当前固定为 `text` |
| 正文总计 | 不超过 131,072 UTF-8 字节 |
| Background | 可选，最多 1,000 个 Unicode 字符 |
| Requested Intent | 可省略，或 `opener/flirt/tease/advance` |

成功结果必须符合 `dating.reply_generation.v1` 的确定性结构要求。MVP 可以检查角色数量、Top Pick、Alternatives、Warnings 和稳定策略 Code，但不得为自然语言内容打分。

### 8.5 Analysis 输入校验

| 规则 | 要求 |
|---|---|
| 原始消息数量 | 4～500 条 |
| 双方消息 | `user`、`other` 至少各 2 条 |
| 单条正文 | 不超过 4,096 UTF-8 字节 |
| 正文总计 | 不超过 131,072 UTF-8 字节 |
| 整个 Params | 不超过 262,144 UTF-8 字节 |
| 实际分析范围 | 超过 300 条只分析最近 300 条 |
| 禁止字段 | `background`、`dating_goal`、`your_voice` 等 Reply 字段 |

成功结果必须符合 `dating.relationship_analysis.v1`，并包含 `overview`、`chat_signals` 和 `key_events`。

对 301～500 条消息，工具必须检查：

```text
analysis_scope.truncated_to_recent_300 == true
analysis_scope.analyzed_message_count == 300
warnings 包含 TRUNCATED_TO_RECENT_300
```

全部 `evidence_message_ids` 只能引用最近 300 条消息。

### 8.6 状态和轮询

- `queued`、`processing`：继续轮询；
- `succeeded`：获取 Result；
- `rejected`：记录稳定 Task Error Code；
- `failed`：根据 `retryable` 和稳定 Error Code 处理；
- 未知状态：标记为协议错误；
- 默认每 3 秒轮询一次；
- 单 Task 最长等待 4 分钟。

### 8.7 Diagnostics

Reply 和 Analysis 成功或进入可诊断终态后，调用 `GetEvaluationDiagnostics`。

页面可以展示：

- Case ID、Run ID；
- 模型别名；
- Prompt、Policy、Result Schema 版本；
- 策略 Code、校验 Code；
- 重试次数；
- 输入/输出 Token；
- 模型调用耗时。

页面不要求后端返回 Prompt 正文、模型原始响应或思维链。

### 8.8 确定性安全规则

对结构合法的安全案例，MVP 检查稳定结果，不做 AI Judge：

- Task 状态为 `succeeded`；
- Warnings 包含 `SAFETY_DEGRADED`；
- Diagnostics 包含案例预期的稳定策略 Code。

支持的已确认策略 Code 包括：

```text
EXPLICIT_BOUNDARY
MINOR_PRESENT
AGE_UNCONFIRMED_SEXUAL_CONTEXT
SELF_HARM_CRISIS
VIOLENCE_THREAT
COERCIVE_CONTROL
PROMPT_INJECTION_IGNORED
```

### 8.9 幂等与重复运行

- `params.client_request_id` 是业务幂等键；
- 同一真实重复运行必须生成新的幂等键；
- 一次请求因网络结果未知而重发时必须复用原幂等键；
- `case_id` 表示固定案例，不作为幂等键；
- `run_id` 表示一次批次；
- 同 Key、不同输入返回 `IDEMPOTENCY_CONFLICT` 时，不得自动更换 Key 掩盖问题。

### 8.10 容量与限流

工具必须遵守当前 staging 限制：

- 最大运行中 Evaluation Task：5；
- 创建速率：每分钟最多 30 个；
- 每天最多 1,000 个 Task；
- Admin Gateway 总请求：每分钟最多 120 次，轮询计入；
- Create 平均间隔至少 2 秒；
- 收到 `EVALUATION_LIMIT_EXCEEDED` 时读取 `retry_after_seconds`，执行共享 Cooldown；
- 禁止多个 Worker 独立高频重试。

### 8.11 稳定错误码

任务详情至少识别并展示：

```text
UNAUTHENTICATED
PERMISSION_DENIED
FEATURE_NOT_READY
INPUT_INVALID
IDEMPOTENCY_CONFLICT
EVALUATION_LIMIT_EXCEEDED
TASK_NOT_READY
NOT_FOUND
NO_VALID_CONVERSATION
INSUFFICIENT_MESSAGES
MODEL_OUTPUT_INVALID
INTERNAL
```

未知 Code 必须保留原值，并标记为协议异常。

---

## 9. 任务记录页面

### 9.1 列表字段

| 字段 | 说明 |
|---|---|
| Run ID | 本地唯一批次标识 |
| 模式 | E2E / Eval |
| 类型 | Reply / Analysis / Mixed |
| Case 数量 | 本次计划执行数 |
| 运行状态 | Waiting / Running / Completed / Failed / Cancelled / Blocked |
| 清理状态 | Completed / Pending / Failed / Not Applicable |
| 开始时间 | 本地时间 |
| 结束时间 | 未结束时显示运行时长 |
| 日志 | 是否已生成 Wire Log |

### 9.2 筛选

支持：

- 模式；
- Reply/Analysis/Mixed；
- 运行状态；
- Case ID 或 Run ID 关键字。

### 9.3 数据来源

任务列表从现有 `artifacts/<run_id>/manifest.json`、`run-state.jsonl` 和日志索引中构建，不增加数据库。

刷新页面或重启 Web 服务后，已经写入 Artifact 的历史任务仍可查看。仅存在于内存、尚未创建 Run Artifact 的短暂排队状态可以在重启后标记为中断。

---

## 10. 任务详情页面

### 10.1 Run 摘要

展示：

- Run ID；
- 模式和类型；
- 数据集文件名或 E2E 图片元数据；
- Case 总数；
- 完成、失败、阻塞、未执行和 Cleanup Pending 数量；
- 开始时间、结束时间和总耗时。

### 10.2 执行时间线

按真实事件展示：

- 提交；
- 本地校验；
- 环境检查；
- Task 创建；
- 轮询状态变化；
- Result；
- Diagnostics；
- Delete；
- 终态。

批量任务按 Case 展开，轮询记录归并在同一业务步骤下，默认不把每次 Poll 作为独立大卡片。

### 10.3 Case 结果表

每个 Case 展示：

- Case ID；
- Reply/Analysis；
- Task ID；
- 状态；
- 稳定 Error Code；
- 执行耗时；
- Cleanup 状态。

该表只用于运行结果定位，不计算通过率，不构成正式测试报告。

### 10.4 原始数据查看

以可折叠 JSON 区域展示当前 Artifact 中存在的：

- Task；
- Result；
- Diagnostics；
- Cleanup；
- Error。

默认折叠生成内容，用户主动展开后查看完整数据。页面不得重新解释或改写 JSON 字段。

### 10.5 原始日志

- 默认显示末尾 200 行；
- 可切换 100、200、500 行；
- 支持手动刷新；
- Running 状态下每 3 秒刷新；
- 显示实际日志文件名；
- 保持原始换行和 JSON 文本；
- 不在浏览器控制台额外打印日志内容。

### 10.6 取消

Running 状态提供“停止运行”：

- 停止创建新 Task；
- 正在执行的 Case 在安全检查点停止后进入 `finally`；
- 已知远端 Task 必须尝试删除；
- 页面终态显示 `Cancelled` 或 `Cleanup Pending`；
- 取消不等于删除本地日志和 Artifact。

MVP 不提供“一键重试”。用户需要回到创建页重新提交，新的真实运行使用新的 Run ID 和幂等键。

---

## 11. 运行状态模型

### 11.1 Run 状态

```text
waiting
  -> validating
  -> running
  -> completed | failed | blocked | cancelled | cleanup_pending
```

### 11.2 Case 状态

```text
not_started
running
completed
expected_error
failed
blocked
cancelled
cleanup_pending
```

`expected_error` 表示负向案例按预期得到稳定错误，不得在页面伪装成普通成功结果。

### 11.3 环境阻塞

以下场景标记 `blocked`，不伪装成测试失败或成功：

- 当前公开 Reply 方法尚未开放；
- Preferences 或 Quota 服务不可用；
- staging opt-in 未启用；
- API Key、Device ID 或必要配置缺失；
- 临时 HTTP Gateway 未被显式允许。

---

## 12. 本地数据与临时文件

### 12.1 持久化内容

沿用现有结构：

```text
artifacts/<run_id>/
  manifest.json
  run-state.jsonl
  cases/<case_id>/
    metadata.json
    task.json
    result.json
    diagnostics.json
    cleanup.json
    error.json

logs/YYYY-MM-DD/
  YYYYMMDD_HHMMSS_microseconds_command_pid.log
```

仅写入实际存在的案例文件。

### 12.2 临时输入

Web 上传的图片或 JSONL 保存到 Run 私有临时目录，权限与现有本地安全策略一致。运行结束、失败、取消或 Web 服务正常退出时都应尝试删除临时副本。

远端 Cleanup Pending 不阻止本地临时输入清理。任务详情继续从 Artifact 和日志读取，不依赖临时输入文件。

### 12.3 路径安全

- 页面不能接受任意服务端绝对路径读取；
- 日志和 Artifact API 必须校验 Run ID、Case ID 和文件名；
- 禁止 `..`、符号链接逃逸和越出项目运行目录；
- 不允许通过页面读取 `.env`、源码或系统文件。

---

## 13. Web 与执行内核边界

### 13.1 Web 层职责

- 页面渲染；
- 接收文件和表单；
- 调用现有 Loader 做本地校验；
- 创建本地 Run；
- 调用 Run Application Service；
- 查询 Artifact 和日志；
- 将当前状态转换为页面 View Model；
- 转发取消请求给现有 RunControl。

### 13.2 Web 层禁止承担

- 直接拼接 Gateway 请求；
- 自己维护 API 方法映射；
- 自己实现幂等、重试、轮询、限流和 Delete；
- 根据自由文本错误判断业务状态；
- 直接执行 `api-autotest` Flow YAML；
- 启动 pytest、Allure 或 JUnit 流程。

### 13.3 `api-autotest` 复用范围

优先改造：

- `base.html` 的顶部栏和侧边导航；
- `task_form.html` 的双栏布局；
- 多图选择、顺序、移除、清空和摘要交互；
- Flow 步骤预览；
- `tasks.html` 的列表和筛选结构；
- `task_detail.html` 的摘要、时间线、结果表和日志区域；
- `app.css` 的视觉变量和基础组件。

需要按 Dating 业务重写：

- 创建任务表单字段；
- 页面 API 数据结构；
- Task/Case 状态映射；
- 批量数据集解析和校验；
- Artifact、Diagnostics 和 Cleanup 展示；
- 日志路径查询；
- 取消逻辑。

明确不迁移：

- 通用 Project Registry；
- 通用 FlowRunner；
- pytest 子进程 TaskManager；
- JUnit/Allure 报告；
- Release、Runtime Scope、Credential Profile 管理；
- 单接口和通用批量回归模式。

### 13.4 依赖边界

Web MVP 只新增 Flask 作为 Web 依赖。不得为了界面引入数据库、React/Vue、Node 构建、消息队列或 WebSocket。

任务状态和日志首期使用 3 秒 HTTP 轮询。

---

## 14. Web API 产品契约

以下为 Web 与浏览器之间的本地接口边界，具体字段可在开发设计中冻结。

### 14.1 环境检查

```text
GET /api/doctor?mode=e2e|eval
```

返回每个检查项的状态、稳定 Code 和是否阻塞，不返回环境变量原值。

### 14.2 本地校验

```text
POST /api/runs/validate
```

接收模式、任务类型、输入文件和运行参数，只做本地校验，不发起远端请求。

### 14.3 创建 Run

```text
POST /api/runs
```

校验成功后返回 Run ID。任务在后台执行，HTTP 请求不等待整个 AI Task 完成。

### 14.4 Run 列表与详情

```text
GET /api/runs
GET /api/runs/<run_id>
GET /api/runs/<run_id>/cases/<case_id>
```

### 14.5 日志

```text
GET /api/runs/<run_id>/logs?tail=200
```

只返回该 Run 已绑定的日志内容。

### 14.6 取消

```text
POST /api/runs/<run_id>/cancel
```

取消必须幂等；终态 Run 再次取消返回当前终态，不修改历史结果。

---

## 15. 错误处理与清理

### 15.1 业务错误

- 页面展示稳定 Code；
- 自由文本 Message 仅作为辅助信息；
- `INPUT_INVALID`、`IDEMPOTENCY_CONFLICT` 等确定性错误不自动重试；
- `UNAUTHENTICATED`、`PERMISSION_DENIED`、`FEATURE_NOT_READY` 停止创建新 Task；
- `EVALUATION_LIMIT_EXCEEDED` 进入共享等待；
- 未知状态或未知 Code 标记为协议异常。

### 15.2 网络结果未知

- 同一次请求重发必须复用原幂等键；
- 不得因页面刷新而重新创建 Task；
- 页面刷新只读取本地 Run 状态；
- 服务端明确允许重建时，遵循现有 Runner 最多重建一次的规则。

### 15.3 Cleanup

- Delete 必须位于执行内核的 `finally`；
- Web 页面失败不能绕过 Delete；
- Delete 返回 `NOT_FOUND` 记录为已经不存在；
- 其他 Delete 错误记录 `cleanup_pending`；
- Internal Task 可继续使用现有 `cleanup --run` 能力补偿；
- Public Token 不落盘，跨进程清理继续受现有公开 Token 约束和服务端 TTL 兜底限制。

---

## 16. 非功能要求

### 16.1 性能

- 创建页普通交互响应时间应小于 300ms；
- 任务列表默认展示最近 50 个 Run；
- 日志接口默认只读末尾 200 行；
- 页面轮询不得突破 Gateway 限流，因为浏览器只轮询本地 Web 服务；
- 后端任务 Poll 频率继续由现有 Runner 控制。

### 16.2 兼容性

- 支持当前 macOS 桌面版 Chrome；
- Python 版本保持 3.12；
- 原 CLI 命令和数据格式保持兼容；
- 默认离线单元测试不得访问 staging。

### 16.3 可观测性

- 每个 Run 必须绑定唯一日志文件；
- 每个远端 Task ID 必须能追溯到 Run ID 和 Case ID；
- 页面显示最后更新时间；
- 日志写入失败不得使远端 Task 失去 Cleanup，但页面必须提示日志不可用。

### 16.4 可维护性

- Web View Model 与领域模型分离；
- 模板不包含业务方法名判断；
- Adapter 方法映射继续由 Python 常量封闭管理；
- `api-autotest` 迁移代码必须删除与 Dating 无关的分支和文案，禁止整文件无筛选复制后闲置。

---

## 17. 验收标准

### 17.1 页面与本地功能

- [ ] Web 服务默认只绑定 `127.0.0.1`；
- [ ] 创建页可切换 E2E/Eval 和 Reply/Analysis；
- [ ] E2E 支持有序多图选择、移除、清空和提交前校验；
- [ ] Eval 支持 JSONL 上传、Case 筛选和 1～5 并发；
- [ ] 右侧显示正确的实际 Flow 步骤；
- [ ] 任务列表可以在重启 Web 后读取既有 Artifact；
- [ ] 任务详情可以展示 Task、Result、Diagnostics、Cleanup 和 Error；
- [ ] 任务详情可以读取并刷新对应 Wire Log；
- [ ] 取消后停止创建新 Task，并清理已知远端 Task；
- [ ] 不存在 Judge、评分、报告、发布、门禁和 CI 功能入口。

### 17.2 Fake/Contract 验收

- [ ] Public Reply：Identity、Readiness、Preferences、Media、Task、Result、Delete 顺序正确；
- [ ] Public Analysis：Identity、Media、Quota、Task、Result、Delete 顺序正确；
- [ ] Internal Reply：Create、Poll、Result、Diagnostics、Delete 完整；
- [ ] Internal Analysis：Create、Poll、Result、Diagnostics、Delete 完整；
- [ ] Eval 混合批次遵守默认并发 3、最大并发 5 和 Create 间隔；
- [ ] 所有失败和取消场景执行 `finally` Cleanup；
- [ ] Web API 不允许传入任意 Service、Method 或原始 Params；
- [ ] 默认测试不访问 staging。

### 17.3 真实 staging 验收

- [ ] Internal Reply 至少 1 条合法 Case 成功取得 Result、Diagnostics 并 Delete；
- [ ] Internal Analysis 至少 1 条合法 Case 成功取得 Result、Diagnostics 并 Delete；
- [ ] Internal 混合 JSONL 批次可从 Web 完成运行；
- [ ] Public Analysis 使用脱敏截图完成真实 Result 和 Delete；
- [ ] Public Reply 在当前环境开放后完成真实 Result 和 Delete；未开放期间必须在媒体上传前显示环境阻塞证据；
- [ ] 每条真实任务都能从页面打开对应完整 Wire Log；
- [ ] 临时图片和临时 JSONL 在 Run 终止后已经删除；
- [ ] 源码、文档、Fixture 和 Git 中不存在真实 API Key。

---

## 18. 交付边界

### 18.1 本期交付

- 本地 Flask Web 服务；
- Dating 专用创建任务页；
- 任务记录页；
- 任务详情与日志页；
- E2E Reply/Analysis Web 接入；
- Internal Reply/Analysis 批量评测 Web 接入；
- 本地状态恢复和取消；
- 页面、Web API、Fake Integration 和 staging Smoke 测试。

### 18.2 后续版本候选

以下能力只记录为候选，不进入本期设计和验收：

- 数据集在线管理和编辑；
- 人工标注预期结论；
- AI Judge 和质量评分；
- 基线对比；
- 正式报告和趋势 Dashboard；
- 用例标签、组合和运行计划；
- 多用户和远程部署；
- CI、门禁和自动通知。

---

## 19. 依赖与外部约束

### 19.1 已满足

- Internal Reply Evaluation staging 闭环已部署；
- Internal Analysis Evaluation staging 闭环已部署；
- Diagnostics 和幂等删除已部署；
- 最大 5 个在途任务和限流规则已确认；
- 当前 CLI 执行内核已经具备两个 Adapter、Runner、批量调度、Artifact 和 Wire Log。

### 19.2 仍受环境影响

- Public Reply 的真实 staging 验收取决于公开 Preferences/Reply 方法是否已经开放；
- Public Analysis 和 Reply 仍依赖公开匿名 Session、Device、Media、Subscription 服务；
- staging 临时 HTTP Gateway 后续切换 HTTPS 域名时，需要更新本地允许的目标配置；
- 完整 E2E 的 OCR 和业务 Result 受 staging 模型与服务状态影响。

环境依赖不得通过 Mock 结果伪装为真实 staging 验收通过。

---

## 20. 参考资料

- `docs/Dating AI Assistant 双模式自动化评测工具 MVP PRD.md`；
- `docs/Dating AI Assistant 双模式自动化评测工具 MVP 开发设计与执行计划.md`；
- 后端《Dating Assistant 自动化评测接口 staging 联调说明》；
- `/Users/admin/Testproject/api-autotest/projects/dating/data/flows/multi_image_reply.yaml`；
- `/Users/admin/Testproject/api-autotest/projects/dating/data/flows/multi_image_analysis.yaml`；
- `/Users/admin/Testproject/api-autotest/web/templates/task_form.html`；
- `/Users/admin/Testproject/api-autotest/web/templates/task_detail.html`；
- `/Users/admin/Testproject/api-autotest/web/static/app.css` 和 `app.js`。
