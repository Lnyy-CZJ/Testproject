# BugAgent v5.5 开发计划

> Version: v5.5  
> Date: 2026-05-06  
> Baseline: v5.4  
> 对应 PRD: PRD-v5.5  
> 对应设计: DESIGN-v5.5

---

## 迭代总览

| 迭代 | 周期 | 内容 | 优先级 |
|------|------|------|--------|
| 5.5.1 | W1-W2 | FR-1 状态链路 + FR-3 Token统计 + FR-4 仓库隔离 | P0 |
| 5.5.2 | W3-W4 | FR-2 SSE替换WebSocket | P1 |
| 5.5.3 | W5-W6 | FR-5 Agent能力一体化 | P1 |

---

## Iteration 5.5.1（P0）

### Task 1: FR-1 状态链路优化

| # | 任务 | 文件 | 预估 |
|---|------|------|------|
| 1.1 | 状态机矩阵新增3条转换 | `model/workflow.go` | 0.5h |
| 1.2 | AnalysisReport 新增 superseded 状态 | `model/models.go` | 0.5h |
| 1.3 | ReopenDefect handler | `handler/defect.go` | 1h |
| 1.4 | ReanalyzeDefect handler | `handler/defect.go` | 1h |
| 1.5 | 路由注册 | `router/router.go` | 0.5h |
| 1.6 | 前端：驳回状态"重新打开"按钮+目标选择 | `DefectDetail.tsx` | 2h |
| 1.7 | 前端：待修复状态"重新分析"按钮 | `DefectDetail.tsx` | 1h |
| 1.8 | 前端：API 方法 | `api/index.ts` | 0.5h |
| 1.9 | 单元测试 | `handler/defect_test.go` | 2h |

### Task 2: FR-3 Token 统计

| # | 任务 | 文件 | 预估 |
|---|------|------|------|
| 2.1 | AITokenUsage 模型 | `model/models.go` | 0.5h |
| 2.2 | 数据库迁移：创建表+回填+删旧字段 | `migrations/v55_*.sql` | 2h |
| 2.3 | 分析完成时写入 AITokenUsage | `adk/analysis_service.go` | 1h |
| 2.4 | 修复完成时写入 AITokenUsage（含 Fallback） | `service/fix_engine.go` | 1.5h |
| 2.5 | 删除 AnalysisReport Token 字段引用 | `model/models.go` + 所有引用处 | 1h |
| 2.6 | 删除 FixTask Token 字段引用 | `model/models.go` + 所有引用处 | 1h |
| 2.7 | TokenUsageHandler（6个API） | `handler/token_usage.go` | 2h |
| 2.8 | 路由注册 | `router/router.go` | 0.5h |
| 2.9 | 前端：缺陷详情Token消耗Tab | `DefectDetail.tsx` | 2h |
| 2.10 | 前端：项目概览AI消耗面板 | `ProjectDashboard.tsx` | 2h |
| 2.11 | 前端：API 方法 | `api/index.ts` | 0.5h |
| 2.12 | 单元测试 | `handler/token_usage_test.go` | 2h |

### Task 3: FR-4 仓库隔离

| # | 任务 | 文件 | 预估 |
|---|------|------|------|
| 3.1 | DefectRepo 模型 | `model/models.go` | 0.5h |
| 3.2 | 数据库迁移 | `migrations/v55_01_defect_repos.sql` | 0.5h |
| 3.3 | 配置项：Repo.BaseDir | `config/config.go` | 0.5h |
| 3.4 | git.CloneToDir 函数 | `git/repo.go` | 1h |
| 3.5 | fix_engine 克隆逻辑改造 | `service/fix_engine.go` | 1.5h |
| 3.6 | 修复完成后清理逻辑 | `service/fix_engine.go` | 1h |
| 3.7 | RepoCleanupService 定时任务 | `service/repo_cleanup.go` | 1.5h |
| 3.8 | RepoHandler（4个API） | `handler/repo.go` | 1.5h |
| 3.9 | 路由注册 | `router/router.go` | 0.5h |
| 3.10 | 单元测试 | `service/repo_cleanup_test.go` | 1.5h |

---

## Iteration 5.5.2（P1）

### Task 4: FR-2 SSE 替换 WebSocket

| # | 任务 | 文件 | 预估 |
|---|------|------|------|
| 4.1 | SSE Broker 实现 | `sse/broker.go` | 2h |
| 4.2 | SSE Handler 实现 | `sse/handler.go` | 2h |
| 4.3 | SSE NotifyService 实现 | `sse/notify.go` | 1.5h |
| 4.4 | 替换所有 ws.NotifyService 调用点 | `service/*.go`, `handler/*.go` | 2h |
| 4.5 | 路由变更：删除 WS，注册 SSE | `router/router.go` | 0.5h |
| 4.6 | 删除 ws/ 包 | `ws/*` | 0.5h |
| 4.7 | 删除 WSAuthMiddleware | `middleware/websocket.go` | 0.5h |
| 4.8 | 前端 SSE Manager | `hooks/sseManager.ts` | 2h |
| 4.9 | 前端 useSSE hook | `hooks/useSSE.ts` | 1h |
| 4.10 | 前端替换所有 WebSocket 使用点 | 多个组件 | 2h |
| 4.11 | 删除 wsManager.ts / useWebSocket.ts | `hooks/wsManager.ts`, `hooks/useWebSocket.ts` | 0.5h |
| 4.12 | 集成测试 | `sse/broker_test.go` | 2h |

---

## Iteration 5.5.3（P1）

### Task 5: FR-5 Agent 能力一体化

| # | 任务 | 文件 | 预估 |
|---|------|------|------|
| 5.1 | ProjectMCPServer 模型 | `model/models.go` | 0.5h |
| 5.2 | ProjectAgentSkill 模型 | `model/models.go` | 0.5h |
| 5.3 | 数据库迁移 | `migrations/v55_04_05.sql` | 1h |
| 5.4 | MCPServerHandler（6个API） | `handler/mcp_server.go` | 2h |
| 5.5 | SkillHandler（5个API） | `handler/skill.go` | 1.5h |
| 5.6 | 路由注册 | `router/router.go` | 0.5h |
| 5.7 | ADK Agent 调度改造 | `adk/analysis_service.go` | 3h |
| 5.8 | config.yaml mcp.servers 迁移到数据库 | `adk/mcp_integration.go` | 1h |
| 5.9 | 前端：项目设置 MCP 服务 Tab | `ProjectSettings.tsx` | 2h |
| 5.10 | 前端：项目设置技能管理 Tab | `ProjectSettings.tsx` | 2h |
| 5.11 | 前端：API 方法 | `api/index.ts` | 0.5h |
| 5.12 | 单元测试 | `handler/mcp_server_test.go`, `handler/skill_test.go` | 2h |

---

## 依赖关系

```
Task 1 (FR-1) ── 无外部依赖，可独立开始
Task 2 (FR-3) ── 依赖数据库迁移脚本先完成
Task 3 (FR-4) ── 依赖 git.CloneToDir 先完成
Task 4 (FR-2) ── 依赖 Task 1/2/3 完成（避免合并冲突）
Task 5 (FR-5) ── 依赖 Task 4 完成（SSE 推送替代 WS 后再做 Agent 改造）
```

## 并行策略

- W1：Task 1 + Task 2 + Task 3 并行开发（后端三人或三线并行）
- W2：前端适配 + 集成测试
- W3-W4：Task 4
- W5-W6：Task 5
