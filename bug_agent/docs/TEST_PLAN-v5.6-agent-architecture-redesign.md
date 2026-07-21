# BugAgent v5.6 测试文档

> Version: v5.6  
> Date: 2026-05-08  
> 对应 PRD: PRD-v5.6-agent-architecture-redesign.md  
> 对应开发: DEV_PLAN-v5.6-agent-architecture-redesign.md

---

## 1. 测试策略

按 Phase 分层测试，每个 Phase 完成后做集成验证，全部完成后做端到端验收。

---

## 2. Phase 1 测试：ToolRegistry + PlannerAgent + Executor

### 2.1 ToolRegistry 单元测试

| 用例 | 输入 | 预期 |
|------|------|------|
| 注册内置工具并 Resolve | Register search_code + read_file, Resolve("planner", ctx) | 返回 2 个 tool.Tool |
| 缓存命中 | 连续两次 Resolve 相同参数 | 第二次不调用 factory |
| 缓存失效 | InvalidateCache 后 Resolve | 重新调用 factory |
| expCtx 字段为 nil | SearchFn=nil 的 ctx | search_code 不在结果中 |
| 空注册 | 无 Register, Resolve | 返回空列表 |

### 2.2 PlannerAgent 单元测试

| 用例 | 输入 | 预期 |
|------|------|------|
| 正常输出计划 | 前端缺陷描述 | 输出 JSON 含 steps 数组，每步有 goal/tool/args |
| 后端缺陷 | API 返回格式错误描述 | steps 包含 find_api_handler 步骤 |
| 输出格式异常 | Mock LLM 返回非 JSON | 解析失败，返回 fallback 标记 |
| 步骤数限制 | 复杂缺陷描述 | steps 不超过 5 个 |
| 工具名限制 | 任意 LLM 输出 | tool 字段只能是 search_code/read_file/find_api_handler/list_directory |

### 2.3 Executor 单元测试

| 用例 | 输入 | 预期 |
|------|------|------|
| 执行搜索步骤 | PlanStep{tool:"search_code", args:{query:"login"}} | 调用 SearchFn，结果写入 ExecResult |
| 执行读取步骤 | PlanStep{tool:"read_file", args:{filePath:"main.go"}} | 调用 ReadFn，结果写入 ExecResult |
| 步骤失败继续 | SearchFn 返回 error | 记录错误，继续执行后续步骤 |
| 全部失败 | 所有函数返回 error | ExecResult.Steps 全有 Error，Evidence 为空 |
| Context 取消 | ctx cancelled | 停止执行，返回已完成步骤 |

### 2.4 集成测试：Planner → Executor → Analysis

| 用例 | 操作 | 预期 |
|------|------|------|
| 完整分析流程 | 触发分析，等待完成 | 报告中 affectedFiles 与仓库文件一致 |
| Planner fallback | Mock Planner 返回非 JSON | 走预检索代码上下文，分析仍能完成 |
| 证据传递 | Executor 收集到代码证据 | Analysis Agent 的输入包含证据文本 |
| affectedFiles 一致率 | 10 个缺陷分析 | ≥ 80% 的 affectedFiles 在仓库中存在 |

---

## 3. Phase 2 测试：AgentScheduler + CancellationToken

### 3.1 AgentScheduler 单元测试

| 用例 | 操作 | 预期 |
|------|------|------|
| 优先级调度 | 提交 Priority=2 后提交 Priority=0 | Priority=0 先执行 |
| 并发控制 | maxConc=2, 提交 3 个任务 | 前 2 个并行执行，第 3 个等待 |
| 任务去重 | 同一 defectID 提交 2 次 | 第二次返回错误 |
| 取消任务 | 提交后 Cancel(defectID) | 任务停止，ResultCh 收到取消结果 |
| 队列状态 | 提交 3 个任务，1 个执行中 | QueueStatus 返回 1 running + 2 queued |

### 3.2 CancellationToken 集成测试

| 用例 | 操作 | 预期 |
|------|------|------|
| 取消整个分析 | 分析进行中调用 Cancel API | 2 秒内停止，SSE 推送 analysis:cancelled |
| 取消后保存部分结果 | 分析到一半取消 | 保存 status=cancelled 的报告 |
| Token 记录 | 取消后查询 Token 用量 | 已消耗的 Token 正常记录 |
| 无运行中分析 | 对未分析的缺陷调用 Cancel | 返回 404 |

---

## 4. Phase 3 测试：RolloutRecorder + SafetyGate

### 4.1 RolloutRecorder 单元测试

| 用例 | 操作 | 预期 |
|------|------|------|
| 记录事件 | Record(sessionID, event) | DB 中 events 字段包含该事件 |
| 中断恢复 | 分析中断后 Resume | 从断点继续执行 |
| 历史查询 | ListByDefect(defectID) | 返回该缺陷的所有分析记录 |

### 4.2 SafetyGate 单元测试

| 用例 | 输入 | 预期 |
|------|------|------|
| 只读自动批准 | tool=search_code | AutoApprove |
| 只读自动批准 | tool=read_file | AutoApprove |
| 项目内写入 | tool=apply_patch, path 在项目内 | AutoApprove |
| 项目外写入 | tool=apply_patch, path 在项目外 | AskUser |
| 未注册工具 | tool=shell | Reject |

---

## 5. 端到端验收测试

| 场景 | 操作 | 验收标准 |
|------|------|----------|
| 正常分析 | 创建缺陷 → 触发分析 → 等待完成 | 报告含代码证据，affectedFiles 真实 |
| 取消分析 | 触发分析 → 3秒后取消 | 2秒内停止，部分结果保存 |
| 并发分析 | 同时触发 3 个缺陷分析 | 并发数 ≤ 配置上限 |
| 优先级 | 自动分析运行中 → 用户手动触发 | 用户触发的先执行 |
| 中断恢复 | 分析到一半服务重启 → 恢复 | 从断点继续 |
| 工具动态加载 | DB 中启用 rag plugin → 触发分析 | 分析使用 RAG 检索工具 |

---

## 6. 回归测试

| 用例 | 验证点 |
|------|--------|
| 旧版 API 触发分析 | 直接调用 TriggerAnalysis 仍可正常工作 |
| SSE 流式推送 | 分析过程正常推送 thinking/tool_call/final 事件 |
| Fallback 机制 | AI 配置失败时走 fallbackAnalysis |
| 报告保存 | 分析完成后报告正常保存到 DB |
| Token 统计 | Token 用量正常记录到 ai_token_usage |
