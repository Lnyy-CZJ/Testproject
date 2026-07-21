# BugAgent v5.6 PRD

> Version: v5.6  
> Date: 2026-05-08  
> Status: Draft  
> Owner: Product + Engineering  
> Baseline: v5.5 已交付

---

## 1. 背景与现状

截至 `v5.5`，BugAgent 的 AI 分析流程为 `Explorer → Analysis` 的 SequentialAgent 模式。运行中暴露出四个结构性问题：

1. **Agent 无法主动探索代码**：Explorer 的 ExplorerContext 只绑了 HandlerFn（且永远报错），SearchFn/ReadFn/TraceFn 全为 nil，导致 explorer agent 无工具可用，analysis agent 工具列表为空，AI 只能依赖预检索的有限代码片段做分析，无法深入探索仓库代码。
2. **无任务调度机制**：所有分析请求直接 goroutine 启动，无并发控制、无优先级、无去重。多个分析同时跑会争抢 LLM 配额和 Git 克隆资源。
3. **会话不可恢复**：Session 一次性使用，用完即删。分析中断后只能重头开始，浪费已消耗的 Token。
4. **工具系统静态固化**：工具在编译时固定注册，无法按项目类型动态加载，无法运行时扩展（MCP/插件）。

参考 OpenAI Codex 的 Agent 架构（SQ/EQ 异步协议、多级沙箱、动态工具、会话持久化、CancellationToken），v5.6 核心目标是：**Agent 能自主探索代码、任务有序调度、工具动态注册、会话可恢复、取消可精细控制。**

---

## 2. v5.6 目标与非目标

### 2.1 目标（Goals）

1. 用 Planner Agent 替代 Explorer，一次性输出结构化探索计划，Executor 按计划调用工具，消除噪音输出。
2. 实现 SubmissionQueue + AgentScheduler，支持优先级调度、并发控制、任务去重。
3. 实现 ToolRegistry 动态工具注册，支持内置工具 + Retriever Plugin + MCP 工具的运行时组装。
4. 实现 CancellationToken 全链路传播，支持取消整个分析、取消当前步骤。
5. 实现 RolloutRecorder 会话持久化，支持中断恢复和历史查询。
6. 实现 SafetyGate 安全评估，按操作风险级别自动审批或拒绝。

### 2.2 非目标（Non-Goals）

1. 不在 v5.6 实现 bwrap/landlock 级别的操作系统沙箱（服务端部署场景不需要）。
2. 不在 v5.6 实现项目级记忆的独立管理界面（复用 v5.5 的 Agent 能力管理）。
3. 不在 v5.6 实现 apply_patch 原子性文件变更（修复场景的代码写入能力留给 v5.7）。
4. 不在 v5.6 实现前端 UI 交互变更（取消按钮、进度展示等），仅提供 API 能力。

---

## 3. 核心问题定义（按优先级）

### P0（必须做）

1. **Agent 无法主动探索代码**
   - 现状：Explorer 无可用工具，产出噪音；Analysis 无工具，只能基于预检索片段。
   - 影响：AI 分析不基于仓库代码，分析结论浅薄、文件路径编造。
   - 目标：Planner 输出结构化计划 → Executor 按计划调用 search_code/read_file/find_api_handler/list_directory → 收集证据 → Analysis 基于证据分析。

2. **工具系统静态固化**
   - 现状：5 个工具编译时固定注册，无法按项目类型动态组装。
   - 影响：不同项目类型（前端/后端/全栈）无法获得差异化的工具集。
   - 目标：ToolRegistry 按项目类型 + Agent 类型动态组装工具集，支持 Retriever Plugin 和 MCP 工具运行时注册。

### P1（应该做）

3. **无任务调度机制**
   - 现状：goroutine 直接启动，无并发控制、无优先级。
   - 影响：并发分析争抢资源；用户触发的分析和自动触发的分析无优先级区分。
   - 目标：SubmissionQueue 优先级堆 + AgentScheduler 并发信号量 + 任务去重。

4. **取消不可精细控制**
   - 现状：只有 context 超时，无法在分析过程中取消特定步骤。
   - 影响：用户点击"取消分析"只能等超时，无法立即停止。
   - 目标：CancellationToken 贯穿全链路，支持取消整个分析或取消当前步骤。

### P2（可以做）

5. **会话不可恢复**
   - 现状：Session 用完即删，中断后重头开始。
   - 影响：浪费已消耗的 Token；长时间分析中断后用户体验差。
   - 目标：RolloutRecorder 持久化完整对话，支持中断恢复。

6. **无安全评估**
   - 现状：工具权限是静态白名单，无法区分读写风险。
   - 影响：未来引入 apply_patch 等写操作工具时无审批机制。
   - 目标：SafetyGate 按操作风险级别自动审批或拒绝。

---

## 4. 功能需求（FR）

### FR-1 Planner Agent + Executor

| 项目 | 说明 |
|------|------|
| FR ID | FR-1 |
| 优先级 | P0 |
| 描述 | 用 Planner Agent 替代 Explorer Agent。Planner 一次性输出结构化探索计划（步骤列表），Executor 按计划依次调用工具，收集代码证据后传给 Analysis Agent。 |
| 验收标准 | 1. Planner 输出 JSON 格式的步骤列表，每步含 goal/tool/args<br>2. Executor 按步骤调用工具，收集结果<br>3. Analysis Agent 的输入包含 Executor 收集的代码证据<br>4. 分析报告中 affectedFiles 与仓库实际文件一致率 ≥ 80% |

### FR-2 ToolRegistry 动态工具注册

| 项目 | 说明 |
|------|------|
| FR ID | FR-2 |
| 优先级 | P0 |
| 描述 | 实现 ToolRegistry，按项目类型 + Agent 类型动态组装工具集。支持内置工具、Retriever Plugin、MCP 工具的运行时注册和解析。 |
| 验收标准 | 1. ToolRegistry.Resolve(agentType, projectType) 返回正确的工具集<br>2. Retriever Plugin 可通过 DB 配置启用/禁用<br>3. MCP 工具可运行时注册<br>4. 工具列表变化不需要重启服务 |

### FR-3 SubmissionQueue + AgentScheduler

| 项目 | 说明 |
|------|------|
| FR ID | FR-3 |
| 优先级 | P1 |
| 描述 | 实现任务提交队列和调度器。支持优先级调度（用户触发 > 自动触发）、并发控制（可配置最大并发数）、任务去重（同一缺陷不重复排队）。 |
| 验收标准 | 1. 用户触发的分析优先于自动触发的分析<br>2. 并发数不超过配置上限<br>3. 同一缺陷同时只有一个分析在执行<br>4. 队列状态可通过 API 查询 |

### FR-4 CancellationToken 全链路

| 项目 | 说明 |
|------|------|
| FR ID | FR-4 |
| 优先级 | P1 |
| 描述 | CancellationToken 贯穿从 API 到工具调用的全链路。支持取消整个分析、取消当前步骤。取消后已消耗的 Token 仍记录，已产出的部分结果仍保存。 |
| 验收标准 | 1. 调用取消 API 后，分析在 2 秒内停止<br>2. 取消后已产出的部分结果保存为 status=cancelled 的报告<br>3. Token 用量正常记录<br>4. SSE 推送 analysis:cancelled 事件 |

### FR-5 RolloutRecorder 会话持久化

| 项目 | 说明 |
|------|------|
| FR ID | FR-5 |
| 优先级 | P2 |
| 描述 | 持久化完整的 Agent 对话到数据库，支持中断恢复和历史查询。 |
| 验收标准 | 1. 分析中断后可通过 API 恢复<br>2. 可查询缺陷的分析历史<br>3. 恢复后从断点继续，不重复已完成的步骤 |

### FR-6 SafetyGate 安全评估

| 项目 | 说明 |
|------|------|
| FR ID | FR-6 |
| 优先级 | P2 |
| 描述 | 按操作风险级别自动审批或拒绝工具调用。只读操作自动批准，写操作需评估。 |
| 验收标准 | 1. search_code/read_file/list_directory 自动批准<br>2. apply_patch 在项目范围内自动批准，范围外需审批<br>3. 未注册工具默认拒绝 |

---

## 5. 非功能需求（NFR）

| NFR ID | 类别 | 要求 |
|--------|------|------|
| NFR-1 | 性能 | ToolRegistry.Resolve 响应时间 < 1ms（内存缓存） |
| NFR-2 | 可靠性 | 调度器崩溃后重启，队列中的任务不丢失 |
| NFR-3 | 可观测性 | 调度器指标（队列长度、并发数、等待时间）暴露为 Prometheus 指标 |
| NFR-4 | 兼容性 | 旧版 API（直接触发分析）继续可用，自动走 SubmissionQueue |

---

## 6. 影响范围

| 层 | 变更 |
|----|------|
| Model | 新增 AnalysisTask、ToolRegistryConfig |
| Migration | v5.6_analysis_tasks.sql, v5.6_tool_registry.sql |
| Service | 重构 ADKAnalysisService，新增 AgentScheduler、ToolRegistry、PlannerAgent |
| ADK | 新增 planner_agent.go, executor.go, tool_registry.go, scheduler.go, safety_gate.go, rollout_recorder.go |
| Handler | 新增 CancelAnalysis API，修改 TriggerAnalysis 走 SubmissionQueue |
| API | POST /defects/:id/analysis/cancel, GET /defects/:id/analysis/queue |

---

## 7. v5.7 待实现功能

以下功能在 v5.6 中未完成实现，顺延至 v5.7：

| FR ID | 功能 | 当前状态 | v5.7 目标 |
|-------|------|---------|----------|
| FR-5.1 | RolloutRecorder 断点恢复执行 | `ResumeLastIncomplete` 仅查询记录，无恢复执行逻辑 | 实现断点续传：记录已完成步骤索引，恢复时跳过已执行步骤，从断点继续执行 Planner/Executor/Analysis 流程 |
| FR-5.3 | 恢复后不重复已完成步骤 | 无步骤级进度记录 | 在 RolloutRecord 中增加 `completedStepIndex` 字段，Executor 每完成一步更新，恢复时从 `completedStepIndex + 1` 开始 |
