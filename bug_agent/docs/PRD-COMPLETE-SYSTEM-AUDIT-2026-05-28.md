# BugAgent 上线前 PRD 功能核对与潜在问题排查报告

核对日期：2026-05-28  
参考文档：`docs/PRD-COMPLETE.md`  
核对范围：后端路由/handler/service/model，前端页面/API 调用，关键测试痕迹  
核对方式：静态代码审计 + PRD 功能点逐项映射

## 1. 总体结论

当前系统已经覆盖上线 PRD 的主体功能：项目/迭代/仓库/缺陷、问题池、连接器、AI 分析、人工修复、PR 手动处理、Agent 记忆、MCP/技能配置、通知、凭证、AI 模型、SSE、Token 统计、用户与审计均有代码实现。

上线前主要风险不在“完全缺功能”，而在“功能存在但没有接到主链路”：

1. VCS PR Webhook handler 已实现，但没有注册到正式 router，PR 自动拒绝/合并回调不会生效。
2. 项目级 MCP 服务和 Agent 技能只有 CRUD 页面/API，ADK 分析服务仍读取启动时全局配置，没有按项目动态构建 Agent 能力。
3. P1 分析取消链路已修复：前端取消会调用后端取消接口，后端取消会将 `analyzing` 回退到 `pending_analysis`。
4. P1 强制改密已修复：后端认证组增加 `must_change_password` 拦截，仅放行个人信息读取、修改密码、登出和 OPTIONS。

## 2. 功能覆盖概览

| PRD 功能 | 当前覆盖 | 证据 | 结论 |
|---|---|---|---|
| 项目与迭代管理 | 已覆盖 | `server/internal/router/router.go:181-190`, `318-327`; `web/src/layouts/ProjectLayout.tsx:152-241` | 可上线 |
| 仓库管理 | 已覆盖 | `server/internal/router/router.go:194-199`, `303`, `423-424`; `web/src/pages/projects/ProjectRepos.tsx` | 可上线，需继续关注凭证错误提示 |
| 缺陷管理 | 已覆盖 | `server/internal/router/router.go:369-385`; `web/src/pages/defects/*` | 可上线 |
| 对话式缺陷创建 | 已覆盖 | `server/internal/handler/defect.go:57-110`; `web/src/api/defect.ts:19-30` | 可上线 |
| 问题池与外部信号 | 已覆盖 | `server/internal/router/router.go:200-214`, `235-242`; `web/src/pages/projects/ProjectIssuePool.tsx`, `ProjectIntegrationsPage.tsx` | 可上线 |
| 连接器签名 | 已覆盖但策略需确认 | `server/internal/handler/inbound_connector.go:57-87`, `129-147` | 若上线要求所有 webhook 强制签名，需调整默认策略 |
| AI 分析 | 已覆盖 | `server/internal/handler/agent.go:40-162`, `164-219`; `server/internal/adk/analysis_service.go:238-363` | 可上线，取消链路已补齐 |
| AI/人工修复 | 已覆盖 | `server/internal/router/router.go:399-407`; `web/src/api/defect.ts:106-112` | 可上线 |
| PR 生命周期 | 部分覆盖 | 手动处理：`server/internal/router/router.go:409-414`; 自动 webhook handler：`server/internal/handler/vcs_webhook.go` | 自动 PR 回调未接入正式路由 |
| Agent 记忆 | 已覆盖 | `server/internal/router/router.go:329-337`; `server/internal/service/agent_memory.go` | 可上线 |
| Agent MCP/技能管理 | 页面/API 覆盖，运行时未闭环 | `server/internal/router/router.go:344-359`; `server/internal/adk/analysis_service.go:99`, `620`, `966` | 需修复主链路接入 |
| 凭证管理 | 已覆盖 | `server/internal/router/router.go:244-259`; `web/src/pages/system/PlatformCredentialsPage.tsx` | 可上线 |
| AI 模型配置 | 已覆盖 | `server/internal/router/router.go:277-316`; `web/src/pages/system/AICatalogPage.tsx` | 可上线 |
| 通知管理 | 已覆盖 | `server/internal/router/router.go:269-292`, `479-497`; `web/src/pages/projects/ProjectNotifications.tsx` | 可上线 |
| 用户与安全 | 已覆盖 | `server/internal/handler/auth.go:99-130`, `205-249`; `server/internal/middleware/auth.go`; `web/src/components/UserCenterModal.tsx:35-56` | 强制改密已有后端约束 |
| SSE 实时进度 | 已覆盖 | `server/internal/router/router.go:140-144`; `web/src/hooks/sseManager.ts`; `web/src/hooks/useAnalysisStream.ts` | 可上线 |
| Token 与成本统计 | 已覆盖 | `server/internal/router/router.go:339-342`, `443-444`; `server/internal/handler/token_usage.go` | 可上线 |
| 任务调度与取消 | 已覆盖 | `server/internal/adk/scheduler.go`; `server/internal/handler/agent.go:254-283`; `web/src/hooks/useAnalysisStream.ts` | 取消状态和前端入口已修复 |

## 3. 上线阻断问题

### P0-1：VCS Webhook 未注册到正式路由，PR 自动状态同步不会生效

影响：

1. PRD 要求 PR 打开、合并、关闭、拒绝状态能同步到缺陷。
2. 当前手动拒绝/合并接口可用，但 GitHub/GitLab Webhook 自动回调不会进入系统。
3. 对外宣称“PR 状态追踪”时，实际只能依赖人工操作或其他未暴露入口。

证据：

1. Handler 已实现：`server/internal/handler/vcs_webhook.go:13-56`。
2. Service 已实现 GitHub/GitLab 处理：`server/internal/service/vcs_webhook.go:30-50`, `163-241`, `271-361`。
3. Router 未注册该 handler：`server/internal/router/router.go` 中没有 `NewVCSWebhookHandler`、`HandleWebhook` 或 `/inbound/vcs/webhook`。
4. 测试里手动创建过测试路由：`server/internal/handler/v54_test.go:327-337`，说明生产 router 缺少同等挂载。

根因：

PR 生命周期 service 和 handler 已开发，但正式 `Setup()` 没有挂载公开 Webhook 路由。

建议处理：

1. 在 `/api/v1/inbound/vcs/webhook` 或类似公开路径注册 `VCSWebhookHandler.HandleWebhook`。
2. 明确 provider 来源方式：query、header 或 path。
3. 增加 router 层集成测试，覆盖真实 `router.Setup()`。

### P0-2：项目级 MCP/技能配置未进入 ADK 分析主链路

影响：

1. PRD 要求项目内管理 MCP 服务和 Agent 技能，修改后 Agent 能力即时生效。
2. 当前页面/API 可创建项目 MCP/技能，但 ADK 分析服务仍只读取启动配置。
3. 用户在项目设置里改 MCP/技能后，实际分析 Agent 不一定使用这些配置，属于“配置可见但不生效”。

证据：

1. 项目级 MCP/技能 CRUD 路由存在：`server/internal/router/router.go:344-359`。
2. 项目级模型/handler 存在：`server/internal/handler/mcp_server.go`, `server/internal/handler/skill.go`。
3. Router 启动时只从 `config.C.MCP.Servers` 注入全局 MCP：`server/internal/router/router.go:38-50`。
4. ADKAnalysisService 只有 `SetMCPServers` 全局 setter：`server/internal/adk/analysis_service.go:99`。
5. 分析 runner 使用 `s.mcpServers`：`server/internal/adk/analysis_service.go:620`, `966`，未按 `project_id` 查询 `ProjectMCPServer` 或 `ProjectAgentSkill`。

根因：

Agent 能力治理的数据模型和 UI 已上线，但调度/分析执行层还没有从项目配置动态构建能力。

建议处理：

1. 在分析请求中根据缺陷所属项目加载启用的 ProjectMCPServer 和 ProjectAgentSkill。
2. 将 `config.C.MCP.Servers` 降级为默认配置或迁移种子数据。
3. 增加端到端测试：项目配置 MCP 后触发分析，确认 runner 收到项目级 MCP。

## 4. 高优先级问题

### P1-1：取消分析可能让缺陷停在 `analyzing`

修复状态：已修复。后端新增取消状态落点，运行中分析取消后将 `analyzing` 回退为 `pending_analysis`，并增加回归测试。

影响：

1. PRD 要求用户可取消分析任务，任务状态可恢复。
2. 当前后端取消运行中分析时只 cancel context 和发 SSE，不回收缺陷状态。
3. `PerformAnalysis` 在 `context.Canceled` 分支设置 `statusRolledBack = true` 后直接返回，不触发 defer 的 `analyzing` 安全回滚。

证据：

1. CancelAnalysis 只调用 cancel，不更新缺陷状态：`server/internal/adk/analysis_service.go:2009-2021`。
2. `PerformAnalysis` 遇到 `context.Canceled` 时保存 cancelled report 并返回：`server/internal/adk/analysis_service.go:313-320`。
3. 该分支将 `statusRolledBack = true`，因此 defer 不会把 `analyzing` 回滚：`server/internal/adk/analysis_service.go:273-283`, `313-320`。
4. Scheduler 的 `Cancel` 也只删除队列/运行中任务并调用 cancel：`server/internal/adk/scheduler.go:103-123`。

根因：

取消语义只覆盖任务控制，没有定义缺陷状态落点。

建议处理：

1. 取消运行中分析时，将 `analyzing` 回到 `pending_analysis` 或 `pending_fix`，建议统一为 `pending_analysis`。
2. 取消排队任务时，如果缺陷已被置为 `pending_analysis`，保留或写入状态变更 comment。
3. 增加取消分析的 handler/service 测试，断言缺陷状态。

### P1-2：前端“取消分析”没有调用后端取消接口

修复状态：已修复。前端新增 `cancelAnalysis(defectId)` API，缺陷详情的“取消分析”按钮会调用后端取消接口并清理本地 stream/polling 状态。

影响：

1. 用户点击取消后，前端只停止当前流读取。
2. 后端已有 `/agents/analyze/:id/cancel`，但前端 API 未封装、页面未调用。
3. 如果后端分析仍在跑，用户会误以为已取消。

证据：

1. 后端取消接口存在：`server/internal/router/router.go:436`，`server/internal/handler/agent.go:254-273`。
2. 前端 `stopStream` 只 abort 当前请求和停止轮询：`web/src/hooks/useAnalysisStream.ts:28-42`。
3. 缺陷详情按钮调用的是 `analysisStream.stopStream()`：`web/src/pages/defects/DefectDetail.tsx:781-790`。
4. `web/src/api/defect.ts` 没有封装 `/agents/analyze/:id/cancel`。

根因：

前端取消交互只实现了 UI/网络层停止，没有接入后端任务取消。

建议处理：

1. 新增 `cancelAnalysis(defectId)` API。
2. “取消分析”按钮先调用后端取消，再停止本地 stream/polling。
3. 对 stream endpoint 的 AbortError 语义单独处理，避免用户取消被当成静默成功。

### P1-3：强制改密只靠前端弹窗，后端业务 API 没有强制拦截

修复状态：已修复。认证路由组新增 `PasswordChangeGuard`，`must_change_password=true` 用户只能访问个人资料读取、修改密码、登出和 OPTIONS。

影响：

1. PRD 要求 `must_change_password=true` 用户登录后必须改密。
2. 当前登录接口返回 `mustChangePassword`，前端布局会打开不可关闭的个人中心改密弹窗。
3. 但后端没有在 JWT middleware 或业务 API 层阻止该用户访问其他接口。
4. 如果用户绕过前端、复用 token 或本地存储被篡改，仍可访问业务接口。

证据：

1. 登录成功直接返回 token：`server/internal/handler/auth.go:123-129`。
2. 改密后清除标记：`server/internal/handler/auth.go:240-249`。
3. 前端登录直接存 token 并跳转：`web/src/pages/auth/Login.tsx:40-49`。
4. 前端强制改密依赖用户菜单状态和 Modal：`web/src/components/layout/UserMenuDropdown.tsx:32-38`, `web/src/components/UserCenterModal.tsx:35-56`。
5. `web/src/api/request.ts:36-42` 对所有请求只附加 token，没有 must-change-password 拦截。

根因：

强制改密被实现为前端体验约束，而不是后端安全策略。

建议处理：

1. 在认证中间件或业务中间件中检测 `must_change_password`。
2. 除 `/users/me/password`、登出、个人信息读取等白名单外，其他接口返回 403 和明确错误码。
3. 前端根据错误码打开强制改密弹窗。

## 5. 中优先级问题

### P2-1：Webhook 签名默认策略与“上线安全口径”可能不一致

影响：

PRD 对外验收写明“Webhook 签名：非法签名请求被拒绝并审计”。当前代码只有在配置了 secret 或显式 `requireSignature=true` 时才强制校验。若上线口径是“所有通用 Webhook 必须签名”，当前默认策略不足。

证据：

1. 只有 `enforceWebhookSignature` 返回 true 才校验：`server/internal/handler/inbound_connector.go:57-87`。
2. 默认逻辑为“配置了 secret 才强制”：`server/internal/handler/inbound_connector.go:129-137`。
3. 非生产可跳过签名：`server/internal/handler/inbound_connector.go:139-147`。

建议处理：

1. 明确上线策略：仅配置签名的连接器强校验，还是生产所有 webhook 强校验。
2. 若后者成立，生产环境默认 `requireSignature=true`，无 secret 时拒绝启用 webhook 连接器。

### P2-2：MCP/技能入口被放在“AI配置”页，和 PRD 的 Agent 能力治理口径不一致

影响：

PRD 对外描述为“Agent 能力管理”，包括 MCP 服务、技能、记忆。当前项目侧边栏显示为“AI配置”，页面内混放 AI 模型、记忆、MCP、技能、Retriever 插件，用户理解成本偏高。

证据：

1. 侧边栏 label 是“AI配置”：`web/src/layouts/ProjectLayout.tsx:235-239`。
2. 同一页面承载 AI config、MemoryManager、MCP、Skill、RetrieverPlugin：`web/src/pages/projects/ProjectSettings.tsx:8-33`, `48-68`。

建议处理：

1. 上线对外口径如果强调 Agent 能力管理，建议侧边栏改为“Agent 配置”或“智能配置”。
2. 页面内分组为“模型配置 / Agent 记忆 / MCP 服务 / 技能 / 检索插件”。

## 6. 可上线功能清单

以下功能从代码结构看已具备上线基础：

1. 项目、迭代、成员、仓库基础管理。
2. 缺陷创建、列表、详情、状态、评论、附件。
3. 对话式缺陷草稿生成和确认创建。
4. 问题池、问题簇、分诊、转缺陷。
5. 项目连接器、同步记录、连接器测试。
6. AI 分析、流式分析、SSE 通知、fallback 分析报告。
7. 人工修复、FixTask、PR 手动拒绝/合并。
8. 项目/迭代记忆 CRUD。
9. 平台凭证、个人凭证、仓库凭证绑定。
10. AI 厂商和模型目录。
11. 项目通知、个人通知偏好、站内消息。
12. Token 使用统计。
13. 用户管理、强制改密标记、审计日志。

## 7. 建议上线前必须完成

1. 注册 VCS Webhook 正式路由，并用 `router.Setup()` 做集成测试。
2. 将项目级 MCP/技能配置接入 ADK 分析执行链路。
3. 明确生产环境 Webhook 签名默认策略。

## 8. 本次未做事项

1. 未修改业务代码。
2. 未启动后端或前端服务做 UI 冒烟。
3. 未连接真实数据库执行全量测试。
4. 未调用产品需求知识库。
