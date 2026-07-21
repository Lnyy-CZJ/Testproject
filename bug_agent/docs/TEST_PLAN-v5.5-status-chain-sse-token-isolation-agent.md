# BugAgent v5.5 测试用例

> Version: v5.5  
> Date: 2026-05-06  
> 对应 PRD: PRD-v5.5  
> 对应设计: DESIGN-v5.5

---

## FR-1 状态链路优化

### TC-1.1 驳回后重新打开到待分析

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷状态为 `rejected` |
| 操作 | `POST /defects/:id/reopen`，body: `{"targetStatus":"pending_analysis","comment":"重新分析"}` |
| 预期 | 状态变为 `pending_analysis`；`status_changes` 表新增记录，comment 包含 `reopen_to:pending_analysis` |
| 清理 | 重置缺陷状态 |

### TC-1.2 驳回后重新打开到分析中

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷状态为 `rejected` |
| 操作 | `POST /defects/:id/reopen`，body: `{"targetStatus":"analyzing"}` |
| 预期 | 状态变为 `analyzing` |

### TC-1.3 驳回后重新打开到待修复

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷状态为 `rejected` |
| 操作 | `POST /defects/:id/reopen`，body: `{"targetStatus":"pending_fix"}` |
| 预期 | 状态变为 `pending_fix` |

### TC-1.4 驳回后直接跳到待分析（rejected → pending_analysis）

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷状态为 `rejected` |
| 操作 | `PUT /defects/:id/status`，body: `{"status":"pending_analysis"}` |
| 预期 | 状态变为 `pending_analysis`（状态机允许） |

### TC-1.5 reopened 状态跳到待分析

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷状态为 `reopened` |
| 操作 | `PUT /defects/:id/status`，body: `{"status":"pending_analysis"}` |
| 预期 | 状态变为 `pending_analysis` |

### TC-1.6 待修复状态重新分析

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷状态为 `pending_fix`，已有 1 条 `completed` 状态的 AnalysisReport |
| 操作 | `POST /defects/:id/reanalyze` |
| 预期 | 状态变为 `pending_analysis`；已有 AnalysisReport 状态变为 `superseded`；`status_changes` 记录 comment 为 `reanalyze` |

### TC-1.7 非法状态转换拒绝

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷状态为 `new` |
| 操作 | `POST /defects/:id/reopen` |
| 预期 | 返回 400，提示状态转换不合法 |

### TC-1.8 非法目标状态拒绝

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷状态为 `rejected` |
| 操作 | `POST /defects/:id/reopen`，body: `{"targetStatus":"completed"}` |
| 预期 | 返回 400，提示目标状态不合法 |

### TC-1.9 并发状态变更冲突

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷状态为 `rejected` |
| 操作 | 两个并发请求同时 `POST /defects/:id/reopen` |
| 预期 | 只有一个成功，另一个返回 409 或状态不匹配错误 |

---

## FR-2 SSE 替换 WebSocket

### TC-2.1 SSE 连接建立

| 项目 | 值 |
|------|---|
| 前置条件 | 用户已登录，有有效 JWT |
| 操作 | `GET /sse?token={jwt}&rooms=defect:1` |
| 预期 | 返回 200，Content-Type 为 `text/event-stream`；收到 `:keepalive` 心跳 |

### TC-2.2 SSE 认证失败

| 项目 | 值 |
|------|---|
| 前置条件 | 无有效 JWT |
| 操作 | `GET /sse?token=invalid` |
| 预期 | 返回 401 |

### TC-2.3 SSE 事件推送

| 项目 | 值 |
|------|---|
| 前置条件 | SSE 连接已建立，订阅 `defect:1` |
| 操作 | 修改缺陷 1 的状态 |
| 预期 | SSE 连接收到 `defect:status_changed` 事件，data 包含 fromStatus/toStatus |

### TC-2.4 SSE 房间过滤

| 项目 | 值 |
|------|---|
| 前置条件 | SSE 连接已建立，订阅 `defect:1` |
| 操作 | 修改缺陷 2 的状态 |
| 预期 | SSE 连接**不**收到缺陷 2 的事件 |

### TC-2.5 SSE 断线重连

| 项目 | 值 |
|------|---|
| 前置条件 | SSE 连接已建立 |
| 操作 | 网络中断后恢复 |
| 预期 | 浏览器 `EventSource` 自动重连；重连后继续收到事件 |

### TC-2.6 SSE 心跳

| 项目 | 值 |
|------|---|
| 前置条件 | SSE 连接已建立 |
| 操作 | 等待 30s 无业务事件 |
| 预期 | 收到 `:keepalive` 注释行 |

### TC-2.7 WebSocket 路由已删除

| 项目 | 值 |
|------|---|
| 前置条件 | SSE 替换完成 |
| 操作 | 尝试连接 `GET /api/v1/ws` |
| 预期 | 返回 404 |

---

## FR-3 Token 统计

### TC-3.1 分析完成写入 AITokenUsage

| 项目 | 值 |
|------|---|
| 前置条件 | 触发缺陷分析 |
| 操作 | 等待分析完成 |
| 预期 | `ai_token_usages` 表新增记录，`consumption_type=analysis`，`source_id` 为 AnalysisReport.ID，Token 数 > 0 |

### TC-3.2 修复完成写入 AITokenUsage

| 项目 | 值 |
|------|---|
| 前置条件 | 触发缺陷修复 |
| 操作 | 等待修复完成 |
| 预期 | `ai_token_usages` 表新增记录，`consumption_type=fix`，`source_id` 为 FixTask.ID，Token 数 > 0 |

### TC-3.3 Fallback 多次尝试记录

| 项目 | 值 |
|------|---|
| 前置条件 | 项目配置 2 个 AI 配置，第一个失败 |
| 操作 | 触发修复，Fallback 到第二个配置 |
| 预期 | `ai_token_usages` 表新增 2 条记录：第一条 `attempt_index=0, is_final_attempt=false`；第二条 `attempt_index=1, is_final_attempt=true` |

### TC-3.4 缺陷维度汇总

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷有 1 次分析 + 2 次修复（1次Fallback） |
| 操作 | `GET /defects/:id/token-usage` |
| 预期 | 返回按 `consumption_type` 分组的汇总：analysis 总 Token = 分析记录之和，fix 总 Token = 2 条修复记录之和 |

### TC-3.5 迭代维度汇总

| 项目 | 值 |
|------|---|
| 前置条件 | 迭代下有 3 个缺陷各有 Token 消耗 |
| 操作 | `GET /iterations/:id/token-usage` |
| 预期 | 返回迭代级 analysis/fix 分组汇总，总 Token = 3 个缺陷之和 |

### TC-3.6 项目维度汇总

| 项目 | 值 |
|------|---|
| 前置条件 | 项目下有多个迭代各有 Token 消耗 |
| 操作 | `GET /projects/:id/token-usage` |
| 预期 | 返回项目级 analysis/fix 分组汇总 |

### TC-3.7 项目按缺陷排名

| 项目 | 值 |
|------|---|
| 前置条件 | 项目下有多个缺陷各有 Token 消耗 |
| 操作 | `GET /projects/:id/token-usage/by-defect` |
| 预期 | 返回按 Token 消耗降序排列的缺陷列表 |

### TC-3.8 时间范围过滤

| 项目 | 值 |
|------|---|
| 前置条件 | 项目下有不同日期的 Token 消耗 |
| 操作 | `GET /projects/:id/token-usage?startDate=2026-05-01&endDate=2026-05-06` |
| 预期 | 只返回时间范围内的记录汇总 |

### TC-3.9 旧字段已删除

| 项目 | 值 |
|------|---|
| 前置条件 | 数据库迁移完成 |
| 操作 | 查询 `analysis_reports` 表结构 |
| 预期 | 不包含 `prompt_tokens`、`completion_tokens`、`total_tokens`、`estimated_cost_usd`、`duration_ms`、`provider`、`model_name`、`prompt_version`、`fallback_used` 字段 |

### TC-3.10 旧数据回填验证

| 项目 | 值 |
|------|---|
| 前置条件 | 迁移前 `analysis_reports` 有 Token 数据 |
| 操作 | 迁移后查询 `ai_token_usages` |
| 预期 | 回填数据与原始数据一致（Token 数、费用、Provider 等） |

---

## FR-4 仓库隔离

### TC-4.1 按缺陷隔离目录

| 项目 | 值 |
|------|---|
| 前置条件 | 触发缺陷 123 的修复 |
| 操作 | 修复开始后检查文件系统 |
| 预期 | 仓库克隆到 `{baseDir}/defects/123/{repoHash}/`，目录存在且包含 `.git/` |

### TC-4.2 不同缺陷目录隔离

| 项目 | 值 |
|------|---|
| 前置条件 | 同时触发缺陷 123 和缺陷 456 的修复 |
| 操作 | 检查两个仓库目录 |
| 预期 | 两个仓库在不同目录，互不影响 |

### TC-4.3 修复完成后目录删除

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷修复完成 |
| 操作 | 检查仓库目录 |
| 预期 | 目录已被 `os.RemoveAll`；`defect_repos` 表状态为 `deleted`，`deleted_at` 非空 |

### TC-4.4 DefectRepo 记录创建

| 项目 | 值 |
|------|---|
| 前置条件 | 触发修复 |
| 操作 | 修复开始后查询 `defect_repos` 表 |
| 预期 | 新增记录包含 defect_id、project_id、repo_url、branch、local_path、status=active |

### TC-4.5 定时清理残留目录

| 项目 | 值 |
|------|---|
| 前置条件 | 有一个 `status=active` 且 `created_at` 超过 24h 的 DefectRepo 记录 |
| 操作 | 触发定时清理任务 |
| 预期 | 目录被删除，记录状态更新为 `deleted` |

### TC-4.6 手动清理仓库

| 项目 | 值 |
|------|---|
| 前置条件 | 缺陷有 `status=active` 的 DefectRepo |
| 操作 | `DELETE /defects/:id/repos/:repoId` |
| 预期 | 目录删除，记录状态更新为 `deleted` |

### TC-4.7 查看孤立仓库

| 项目 | 值 |
|------|---|
| 前置条件 | 有无活跃修复任务的 active 仓库 |
| 操作 | `GET /admin/repos/orphaned` |
| 预期 | 返回孤立仓库列表 |

### TC-4.8 修复失败也清理目录

| 项目 | 值 |
|------|---|
| 前置条件 | 修复过程中 AI 调用失败 |
| 操作 | 等待修复流程结束 |
| 预期 | 目录仍被清理，DefectRepo 状态为 `deleted` |

---

## FR-5 Agent 能力一体化

### TC-5.1 MCP 服务 CRUD

| 项目 | 值 |
|------|---|
| 前置条件 | 项目存在 |
| 操作 | 创建/查询/更新/删除 MCP 服务 |
| 预期 | CRUD 操作正常，数据持久化 |

### TC-5.2 MCP 服务启禁用

| 项目 | 值 |
|------|---|
| 前置条件 | 项目有 MCP 服务 |
| 操作 | `PATCH /projects/:id/mcp-servers/:serverId/toggle` |
| 预期 | enabled 状态切换 |

### TC-5.3 MCP 服务连通性测试

| 项目 | 值 |
|------|---|
| 前置条件 | 项目有 MCP 服务 |
| 操作 | `POST /projects/:id/mcp-servers/:serverId/test` |
| 预期 | 返回连通性结果（成功/失败+原因） |

### TC-5.4 MCP 命令白名单

| 项目 | 值 |
|------|---|
| 前置条件 | 无 |
| 操作 | 创建 MCP 服务，command 为 `/usr/bin/rm` |
| 预期 | 返回 400，提示命令不在白名单中 |

### TC-5.5 技能 CRUD

| 项目 | 值 |
|------|---|
| 前置条件 | 项目存在 |
| 操作 | 创建/查询/更新/删除自定义技能 |
| 预期 | CRUD 操作正常 |

### TC-5.6 默认技能不可删除

| 项目 | 值 |
|------|---|
| 前置条件 | 项目有 `is_default=true` 的技能 |
| 操作 | `DELETE /projects/:id/skills/:skillId` |
| 预期 | 返回 400，提示默认技能不可删除 |

### TC-5.7 技能启禁用

| 项目 | 值 |
|------|---|
| 前置条件 | 项目有技能 |
| 操作 | `PATCH /projects/:id/skills/:skillId/toggle` |
| 预期 | enabled 状态切换 |

### TC-5.8 Agent 调度读取项目技能

| 项目 | 值 |
|------|---|
| 前置条件 | 项目配置了自定义技能（含 MCP 服务和记忆类别） |
| 操作 | 触发分析 |
| 预期 | Agent 使用项目技能配置构建，包含自定义 Prompt + MCP 工具 + 记忆注入 |

### TC-5.9 无自定义技能时降级到默认

| 项目 | 值 |
|------|---|
| 前置条件 | 项目无启用的自定义技能 |
| 操作 | 触发分析 |
| 预期 | Agent 使用默认技能（与 v5.4 行为一致） |

### TC-5.10 MCP 配置即时生效

| 项目 | 值 |
|------|---|
| 前置条件 | 项目新增 MCP 服务 |
| 操作 | 立即触发分析（不重启服务） |
| 预期 | Agent 包含新 MCP 服务的工具 |
