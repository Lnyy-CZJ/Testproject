# Tasks

## Iteration 5.6.1 — SSE 流式推送 + 思考过程可视化

- [x] Task 1: 扩展 StreamEvent 结构并改造 convertEvent
  - [x] 1.1: 在 `server/internal/adk/stream_adapter.go` 中扩展 `StreamEvent` 结构，增加 `thinking`/`tool_call`/`tool_result` 事件类型及 `ToolName`/`ToolInput`/`ToolOutput`/`StepIndex`/`Phase` 字段
  - [x] 1.2: 改造 `convertEvent` 函数，识别 ADK `session.Event` 中的 `FunctionCall` 和 `FunctionResponse` Part，转换为 `tool_call`/`tool_result` 事件
  - [x] 1.3: 为 `thinking` 事件添加阶段推断逻辑（根据工具调用类型推断 `retrieval`/`analysis`/`validation` 阶段）
  - [x] 1.4: 编写 `convertEvent` 的单元测试，覆盖 `partial`/`final`/`tool_call`/`tool_result`/`thinking` 场景

- [x] Task 2: 改造 StreamToSSE 输出格式
  - [x] 2.1: 改造 `StreamToSSE` 函数，同时输出 `event:` 行和 `data:` 行（当前只输出 `data:` 行）
  - [x] 2.2: 添加 SSE `id:` 字段（递增序号），支持客户端断连后从上次位置恢复
  - [x] 2.3: 编写 `StreamToSSE` 的单元测试，验证输出格式正确

- [x] Task 3: 改造 PerformAnalysisStream 完成后置处理
  - [x] 3.1: 在 `PerformAnalysisStream` 的流结束后，保存 `AnalysisReport` 到数据库
  - [x] 3.2: 在流结束后，更新缺陷状态为 `pending_fix`
  - [x] 3.3: 在流结束后，记录 `AITokenUsage`
  - [x] 3.4: 在流结束后，发布 Agent 评论
  - [x] 3.5: 在流结束后，提取记忆（异步）
  - [x] 3.6: 处理流中断（客户端断连）场景：回退到异步模式继续分析

- [x] Task 4: 前端新增 useAnalysisStream Hook
  - [x] 4.1: 在 `web/src/hooks/` 下新建 `useAnalysisStream.ts`，实现 SSE 流式分析请求（fetch + ReadableStream）
  - [x] 4.2: 实现 SSE 事件解析（按 `event:` + `data:` 行解析）
  - [x] 4.3: 维护 `steps` 状态（思考步骤列表），每个步骤包含 type/content/toolName/phase/timestamp
  - [x] 4.4: 维护 `currentPhase` / `analyzing` / `error` 状态
  - [x] 4.5: 实现 `startStream(defectId, agentTypes)` 方法
  - [x] 4.6: 处理连接断开和错误重试逻辑

- [x] Task 5: 前端新增 ThinkingProcess 组件
  - [x] 5.1: 在 `web/src/pages/defects/components/` 下新建 `ThinkingProcess.tsx`
  - [x] 5.2: 实现步骤时间线布局（纵向时间线，每步显示阶段图标 + 描述 + 时间戳）
  - [x] 5.3: 实现工具调用卡片（折叠展示工具名、输入摘要、输出摘要）
  - [x] 5.4: 实现推理文本流（实时追加 partial 事件文本）
  - [x] 5.5: 实现顶部进度指示（当前阶段：检索 → 分析 → 验证）
  - [x] 5.6: 实现分析完成后的淡出动画

- [x] Task 6: 前端集成 ThinkingProcess 到 DefectAnalysisPanel
  - [x] 6.1: 修改 `DefectAnalysisPanel`，当 `analyzing=true` 时展示 `ThinkingProcess` 替代 Spinner
  - [x] 6.2: 修改 `useDefectActions`，删除 `startPolling`/`stopPolling`/`pollingTimerRef`/`pollingActiveRef` 轮询逻辑
  - [x] 6.3: 修改 `useDefectActions`，`handleTriggerAnalysis` 改为调用 `useAnalysisStream.startStream`
  - [x] 6.4: 修改 `DefectDetail.tsx`，将 `useAnalysisStream` 的状态传递给 `DefectTabs`/`DefectAnalysisPanel`
  - [x] 6.5: 删除 `analyzingProgress` 状态，由 `useAnalysisStream.steps` 替代
  - [x] 6.6: 保留 `triggerAnalysis`（异步触发）作为降级路径，在 SSE 不可用时回退

- [x] Task 7: 前端 API 层适配
  - [x] 7.1: 在 `web/src/api/defect.ts` 中新增 `triggerAnalysisStream` 函数（fetch + ReadableStream）
  - [x] 7.2: 更新 `web/src/api/types.ts`，新增 `StreamEvent`/`ThinkingStep` 类型定义

## Iteration 5.6.2 — 检索层插件化

- [x] Task 8: RetrieverPlugin 数据模型与迁移
  - [x] 8.1: 在 `server/internal/model/` 中新增 `RetrieverPlugin` 模型
  - [x] 8.2: 在 `server/migrations/` 中新增迁移脚本 `v5.6_retriever_plugins.sql`
  - [x] 8.3: 在 `server/internal/model/models.go` 中注册 `RetrieverPlugin` 到 AutoMigrate

- [x] Task 9: RetrieverPluginRegistry 实现
  - [x] 9.1: 在 `server/internal/retrieval/` 中新增 `registry.go`，实现 `RetrieverPluginRegistry`
  - [x] 9.2: 实现 `Register(name, factory)` 方法注册插件 Factory
  - [x] 9.3: 实现 `Create(name, config)` 方法根据配置创建 Retriever 实例
  - [x] 9.4: 实现 `ListRegistered()` 方法返回已注册的插件名称列表
  - [x] 9.5: 编写 Registry 的单元测试

- [x] Task 10: 内置检索插件实现
  - [x] 10.1: 确认 `KeywordRetriever` 作为内置插件，注册到 Registry
  - [x] 10.2: 新增 `RAGRetriever` 骨架实现（读取 config 中的 endpoint/collection，调用外部 RAG 服务）
  - [x] 10.3: 新增 `RequirementRetriever` 骨架实现（读取 config 中的 docPath，检索需求文档）
  - [x] 10.4: 在服务启动时（`init.go` 或 `main.go`）注册所有内置插件到全局 Registry

- [x] Task 11: ADKAnalysisService 改造为动态构建 Router
  - [x] 11.1: 在 `ADKAnalysisService` 中注入 `RetrieverPluginRegistry`
  - [x] 11.2: 新增 `buildRetrieverForProject(projectID)` 方法，从数据库读取项目插件配置，动态构建 Router
  - [x] 11.3: 添加 Retriever 实例缓存（按 projectID 缓存，TTL 5 分钟）
  - [x] 11.4: 修改 `PerformAnalysis` 和 `PerformAnalysisStream`，使用 `buildRetrieverForProject` 替代硬编码的 `s.retriever`
  - [x] 11.5: 所有插件失败时回退到 `KeywordRetriever`

- [x] Task 12: 检索插件管理 API
  - [x] 12.1: 在 `server/internal/handler/` 中新增 `retriever_plugin.go` Handler
  - [x] 12.2: 实现 `GET /projects/:id/retriever-plugins` 列表接口
  - [x] 12.3: 实现 `PUT /projects/:id/retriever-plugins/:pluginId` 编辑接口（config/enabled/sortOrder）
  - [x] 12.4: 实现 `PATCH /projects/:id/retriever-plugins/:pluginId/toggle` 开关接口
  - [x] 12.5: 实现 `PUT /projects/:id/retriever-plugins/sort` 批量排序接口
  - [x] 12.6: 实现 `POST /projects/:id/retriever-plugins/:pluginId/test` 连通性测试接口
  - [x] 12.7: 在 `server/internal/router/router.go` 中注册路由
  - [x] 12.8: 编写 API 集成测试

- [x] Task 13: 项目创建时自动插入内置插件种子数据
  - [x] 13.1: 在项目创建 Service 中，创建项目后自动插入 keyword/rag/requirement 三个内置插件记录
  - [x] 13.2: keyword 默认启用，rag/requirement 默认禁用
  - [x] 13.3: 为已有项目补充种子数据（一次性迁移脚本）

- [x] Task 14: 前端检索配置页面
  - [x] 14.1: 在 `web/src/api/agent.ts` 中新增检索插件 API 函数
  - [x] 14.2: 在 `web/src/api/types.ts` 中新增 `RetrieverPluginItem` 类型定义
  - [x] 14.3: 在 `web/src/pages/projects/` 下新建 `ProjectRetrieverPlugins.tsx` 页面
  - [x] 14.4: 实现插件列表表格（名称、描述、状态开关、排序、操作）
  - [x] 14.5: 实现开关切换（调用 toggle API）
  - [x] 14.6: 实现拖拽排序（调用 sort API）
  - [x] 14.7: 实现配置编辑模态框（JSON 编辑器）
  - [x] 14.8: 实现连通性测试按钮
  - [x] 14.9: 在项目设置页 `ProjectSettings.tsx` 中新增"检索配置"Tab

# Task Dependencies

- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 2]
- [Task 5] depends on [Task 4]
- [Task 6] depends on [Task 5]
- [Task 7] depends on [Task 4]
- [Task 11] depends on [Task 9, Task 10]
- [Task 12] depends on [Task 8]
- [Task 13] depends on [Task 8]
- [Task 14] depends on [Task 12]

# Parallelizable Work

- Task 1 + Task 8 可并行（后端不同模块）
- Task 5 + Task 9 可并行（前端组件 vs 后端 Registry）
- Task 10 + Task 12 可并行（插件实现 vs API Handler）
