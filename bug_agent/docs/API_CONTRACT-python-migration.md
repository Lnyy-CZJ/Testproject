# Python 重构 API 契约冻结矩阵

> 版本: v0.1  
> 日期: 2026-06-20  
> 状态: 第零阶段冻结稿  
> 来源: `server/internal/router/router.go`、`web/src/api/*`、`web/e2e/*`

---

## 1. 契约目标

本文件用于冻结 Go 后端迁移到 Python 后端时必须保持兼容的 HTTP API、认证方式、权限、响应格式和副作用边界。Python 业务实现必须先更新本矩阵，再编写接口代码和测试。

第零阶段只冻结契约，不要求完成全部业务 API 实现。

---

## 2. 全局约定

| 项 | 约定 |
|----|------|
| API 前缀 | `/api/v1` |
| 成功响应 | `{"code":0,"data":...,"message":...}` |
| 分页响应 | `{"list":[],"total":0,"page":1,"size":20}` |
| 字段命名 | 请求兼容 camelCase，响应必须 camelCase |
| 认证头 | `Authorization: Bearer <token>` |
| 公开接口 | `/auth/register`、`/auth/login`、`/inbound/connectors/{token}`、`/invites/{code}/validate`、`/invites/{code}/accept`、`/sse` |
| 受保护中间件 | JWTAuth、PasswordChangeGuard、APILimit、Audit |
| 文件上传 | `multipart/form-data` |
| 文件下载 | `GET /api/v1/uploads/*filename`，必须 JWT |
| SSE | `GET /api/v1/sse?token={jwt}&rooms=defect:1,project:5` |

错误响应冻结:

| 场景 | HTTP | code | message |
|------|------|------|---------|
| 未登录/Token 过期 | 401 | 401 | `登录已过期` 或 Go 版等价文本 |
| 无权限 | 403 | 403 | 稳定可展示文本 |
| 资源不存在 | 404 | 404 | 稳定可展示文本 |
| 状态冲突 | 409 | 409 | 说明当前状态不可执行目标操作 |
| 参数错误 | 422 | 非 0 | 字段级错误需归一化后返回 |
| 服务错误 | 500 | 500 | 不暴露堆栈 |

---

## 3. 第零阶段优先级说明

| 优先级 | 含义 |
|--------|------|
| P0 | 第一、二阶段必须优先实现，前端基础和缺陷主流程依赖 |
| P1 | Agent、修复、通知、权限等核心闭环依赖 |
| P2 | 信号接入、质量洞察、治理能力依赖 |
| P3 | 管理增强或低频能力，可在主流程稳定后实现 |

---

## 4. 认证与用户

| Method | Path | 认证 | 权限 | 前端来源 | 优先级 | 备注 |
|--------|------|------|------|----------|--------|------|
| POST | `/auth/register` | public | - | `web/src/api/auth.ts` | P0 | 返回 LoginData |
| POST | `/auth/login` | public | - | `web/src/api/auth.ts` | P0 | 返回 token/user |
| POST | `/auth/logout` | JWT | - | auth/profile | P0 | Token 加入黑名单 |
| GET | `/users/me` | JWT | - | `getProfile` | P0 | 当前用户资料 |
| PUT | `/users/me` | JWT | - | `updateProfile` | P0 | 支持 nickname/avatar/agentTypes |
| PUT | `/users/me/password` | JWT | - | `changeMyPassword` | P0 | 强制改密依赖 |
| POST | `/users/me/avatar` | JWT | - | `uploadMyAvatar` | P1 | multipart |
| PUT | `/users/me/agent-types` | JWT | - | `updateMyAgentTypes` | P1 | agentTypes 数组 |
| GET | `/users` | JWT | `users:read` | `listUsers` | P1 | 分页 |
| GET | `/users/{id}` | JWT | `users:read` | `getUser` | P1 | 用户详情 |
| POST | `/users` | JWT | `users:manage` | `createUser` | P1 | 返回临时密码 |
| PUT | `/users/{id}/agent-types` | JWT | `users:manage` | `updateUserAgentTypes` | P1 | 管理员设置 |
| PUT | `/users/{id}/platform-role` | JWT | `users:manage` | `updateUserPlatformRole` | P1 | 平台角色 |
| POST | `/users/{id}/reset-password` | JWT | `users:manage` | `resetUserPassword` | P1 | 返回临时密码 |
| GET | `/user/projects` | JWT | - | 项目切换器 | P0 | 当前用户项目列表 |

---

## 5. 项目、迭代、仓库、AI 配置

| Method | Path | 认证 | 权限 | 前端来源 | 优先级 | 备注 |
|--------|------|------|------|----------|--------|------|
| GET | `/projects` | JWT | - | `web/src/api/project.ts` | P0 | 项目列表 |
| POST | `/projects` | JWT | `projects:create` | project | P0 | 创建项目 |
| GET | `/projects/{id}` | JWT | `projects:read` | project | P0 | 项目详情 |
| PUT | `/projects/{id}` | JWT | `projects:update` | project | P0 | 更新项目 |
| POST | `/projects/{id}/members` | JWT | `projects:update` | project members | P0 | 添加成员 |
| DELETE | `/projects/{id}/members/{memberId}` | JWT | `projects:update` | project members | P0 | 移除成员 |
| GET | `/projects/{id}/stats` | JWT | `projects:read` | dashboard | P1 | 项目统计 |
| GET | `/projects/{id}/repos` | JWT | `projects:read` | repos page | P0 | 仓库列表 |
| POST | `/projects/{id}/repos` | JWT | `projects:update` | repos page | P0 | 创建仓库 |
| PUT | `/projects/{id}/repos/{repoId}` | JWT | `projects:update` | repos page | P0 | 更新仓库 |
| DELETE | `/projects/{id}/repos/{repoId}` | JWT | `projects:update` | repos page | P0 | 删除仓库 |
| GET | `/projects/{id}/repos/{repoId}/branches` | JWT | `projects:read` | iteration repos | P1 | 分支列表 |
| GET | `/projects/{id}/ai-configs` | JWT | `projects:read` | AI config page | P0 | 项目 AI 配置 |
| POST | `/projects/{id}/ai-configs` | JWT | `projects:update` | AI config page | P0 | 创建配置 |
| PUT | `/projects/{id}/ai-configs/{configId}` | JWT | `projects:update` | AI config page | P0 | 更新配置 |
| DELETE | `/projects/{id}/ai-configs/{configId}` | JWT | `projects:update` | AI config page | P0 | 删除配置 |
| GET | `/ai/providers` | JWT | - | AI config page | P0 | 可用厂商模型 |
| POST | `/projects/{id}/iterations` | JWT | `projects:update` | iterations | P0 | 创建迭代 |
| GET | `/projects/{id}/iterations` | JWT | `projects:read` | iterations | P0 | 迭代列表 |
| GET | `/projects/{id}/iterations/{iterationId}` | JWT | `projects:read` | iterations | P0 | 迭代详情 |
| PUT | `/projects/{id}/iterations/{iterationId}` | JWT | `projects:update` | iterations | P0 | 更新迭代 |
| POST | `/projects/{id}/iterations/{iterationId}/repos` | JWT | `projects:update` | iterations | P0 | 绑定仓库 |
| DELETE | `/projects/{id}/iterations/{iterationId}/repos/{repoId}` | JWT | `projects:update` | iterations | P0 | 解绑仓库 |
| PUT | `/projects/{id}/iterations/{iterationId}/repos/{iterRepoId}/branch` | JWT | `projects:update` | iterations | P1 | 更新分支 |
| GET | `/projects/{id}/iterations/{iterationId}/defects` | JWT | `projects:read` | iteration detail | P1 | 迭代缺陷 |

---

## 6. 缺陷主流程

| Method | Path | 认证 | 权限 | 前端来源 | 优先级 | 副作用 |
|--------|------|------|------|----------|--------|--------|
| GET | `/defects` | JWT | `defects:read` | `listDefects` | P0 | - |
| POST | `/defects` | JWT | `defects:create` | `createDefect` | P0 | created event |
| GET | `/defects/{id}` | JWT | `defects:read` | `getDefect` | P0 | - |
| PUT | `/defects/{id}` | JWT | `defects:update` | `updateDefect` | P0 | updated event |
| PUT | `/defects/{id}/assign` | JWT | `defects:update` | `assignDefect` | P0 | 状态/通知/SSE |
| PUT | `/defects/{id}/status` | JWT | `defects:update` | `changeDefectStatus` | P0 | 状态历史/SSE |
| PUT | `/defects/{id}/verify` | JWT | `defects:update` | `verifyDefect` | P0 | 状态历史/SSE |
| PUT | `/defects/{id}/merge` | JWT | `defects:update` | `mergeDefect` | P1 | PR 状态同步 |
| PUT | `/defects/{id}/reject` | JWT | `defects:update` | `rejectDefect` | P0 | 状态历史/SSE |
| POST | `/defects/{id}/reopen` | JWT | `defects:update` | `reopenDefect` | P0 | 状态历史/SSE |
| POST | `/defects/{id}/reanalyze` | JWT | `defects:update` | `reanalyzeDefect` | P1 | 提交分析任务 |
| GET | `/defects/{id}/recommend-assignees` | JWT | `defects:read` | recommendation | P1 | - |
| GET | `/defects/{id}/recommend-agents` | JWT | `defects:read` | recommendation | P1 | - |
| POST | `/projects/{id}/defects/draft-from-chat` | JWT | `projects:update` | chat create | P0 | AI 草稿 |
| POST | `/projects/{id}/defects/confirm-create` | JWT | `projects:update` | chat create | P0 | 创建缺陷 |

---

## 7. 附件、评论、工作流

| Method | Path | 认证 | 权限 | 优先级 | 备注 |
|--------|------|------|------|--------|------|
| GET | `/uploads/*filename` | JWT | - | P0 | 认证下载 |
| POST | `/defects/{id}/attachments` | JWT | `defects:update` | P0 | multipart |
| GET | `/defects/{id}/attachments` | JWT | `defects:read` | P0 | 附件列表 |
| DELETE | `/defects/{id}/attachments/{attachmentId}` | JWT | `defects:update` | P1 | 删除附件 |
| POST | `/defects/{id}/comments` | JWT | `defects:update` | P0 | 添加评论 |
| GET | `/defects/{id}/comments` | JWT | `defects:read` | P0 | 评论列表 |
| PUT | `/defects/{id}/transition` | JWT | `defects:update` | P0 | 状态机入口 |
| GET | `/defects/{id}/transitions` | JWT | `defects:read` | P0 | 可用流转 |
| GET | `/defects/{id}/history` | JWT | `defects:read` | P0 | 状态历史 |
| POST | `/workflow/batch` | JWT | `defects:update` | P1 | 批量流转 |

---

## 8. Agent 分析与协作

| Method | Path | 认证 | 权限 | 前端来源 | 优先级 | 备注 |
|--------|------|------|------|----------|--------|------|
| POST | `/agents/analyze` | JWT | `agents:analyze` | `triggerAnalysis` | P1 | 异步分析 |
| POST | `/agents/analyze/stream` | JWT | `agents:analyze` | `triggerAnalysisStream` | P1 | text/event-stream |
| GET | `/agents/reports/{reportId}` | JWT | `agents:read_report` | `getReport` | P1 | 报告详情 |
| POST | `/agents/analyze/{id}/cancel` | JWT | `agents:analyze` | `cancelAnalysis` | P1 | 取消任务 |
| GET | `/agents/analyze/queue` | JWT | `agents:analyze` | queue | P1 | 队列状态 |
| GET | `/agents/analyze/{id}/history` | JWT | `agents:analyze` | history | P1 | 分析历史 |
| GET | `/defects/{id}/reports` | JWT | `agents:read_report` | `listReports` | P1 | 缺陷报告 |
| POST | `/collaborations` | JWT | `agents:analyze` | collaboration | P2 | 多 Agent |
| GET | `/collaborations` | JWT | `defects:read` | collaboration | P2 | 任务列表 |
| GET | `/collaborations/{taskId}` | JWT | `defects:read` | collaboration | P2 | 任务详情 |
| GET | `/collaborations/{taskId}/report` | JWT | `defects:read` | collaboration | P2 | 聚合报告 |
| POST | `/defects/{id}/collaborations` | JWT | `defects:update` | defect detail | P2 | 缺陷协作 |
| GET | `/defects/{id}/collaborations` | JWT | `defects:read` | defect detail | P2 | 缺陷协作列表 |

---

## 9. 修复任务与 PR 生命周期

| Method | Path | 认证 | 权限 | 前端来源 | 优先级 | 副作用 |
|--------|------|------|------|----------|--------|--------|
| POST | `/defects/{id}/fix-tasks` | JWT | `fix_tasks:create` | `createFixTask` | P1 | 创建任务组 |
| GET | `/defects/{id}/fix-task-groups` | JWT | `defects:read` | `listFixTaskGroups` | P1 | - |
| GET | `/defects/{id}/fix-tasks` | JWT | `defects:read` | `listFixTasks` | P1 | - |
| GET | `/fix-tasks/{taskId}` | JWT | `defects:read` | `getFixTask` | P1 | - |
| PUT | `/fix-tasks/{taskId}` | JWT | `fix_tasks:update` | `updateFixTask` | P1 | 状态更新 |
| POST | `/defects/{id}/manual-fix/start` | JWT | `fix_tasks:create` | manual fix | P1 | 状态流转 |
| POST | `/defects/{id}/manual-fix/complete` | JWT | `fix_tasks:update` | manual fix | P1 | 待验证 |
| POST | `/defects/{id}/manual-fix/abandon` | JWT | `fix_tasks:update` | manual fix | P1 | 回退 |
| PATCH | `/defects/{id}/fix-tasks/{taskId}/pr` | JWT | `fix_tasks:update` | PR lifecycle | P1 | 更新 PR |
| GET | `/defects/{id}/fix-tasks/{taskId}/rejections` | JWT | `defects:read` | PR lifecycle | P1 | 拒绝记录 |
| POST | `/defects/{id}/fix-tasks/{taskId}/reject` | JWT | `fix_tasks:update` | PR lifecycle | P1 | 回退 pending_fix |
| POST | `/defects/{id}/fix-tasks/{taskId}/merge` | JWT | `fix_tasks:update` | PR lifecycle | P1 | 推进 fixed |

---

## 10. 权限、通知、报表、治理

| Method | Path | 认证 | 权限 | 优先级 | 备注 |
|--------|------|------|------|--------|------|
| GET | `/rbac/roles` | JWT | `rbac:manage` | P1 | 角色列表 |
| GET | `/rbac/permissions` | JWT | `rbac:manage` | P1 | 权限列表 |
| GET | `/rbac/my-permissions` | JWT | - | P0 | 当前权限 |
| GET | `/rbac/my-roles` | JWT | - | P0 | 当前角色 |
| POST | `/rbac/assign` | JWT | `rbac:manage` | P1 | 分配角色 |
| DELETE | `/rbac/users/{userId}/roles/{roleId}` | JWT | `rbac:manage` | P1 | 移除角色 |
| GET | `/rbac/check` | JWT | - | P1 | 权限检查 |
| GET | `/audit-logs` | JWT | `audit:read` | P2 | 审计列表 |
| GET | `/audit-logs/recent` | JWT | `audit:read` | P2 | 最近审计 |
| GET | `/audit-logs/stats` | JWT | `audit:read` | P2 | 审计统计 |
| GET | `/notifications` | JWT | - | P1 | 通知列表 |
| GET | `/notifications/unread-count` | JWT | - | P1 | 未读数 |
| PUT | `/notifications/read` | JWT | - | P1 | 标记已读 |
| PUT | `/notifications/read-all` | JWT | - | P1 | 全部已读 |
| POST | `/notifications/send` | JWT | `notifications:send` | P2 | 手动发送 |
| GET | `/notification-preferences` | JWT | - | P2 | 通知偏好 |
| PUT | `/notification-preferences` | JWT | - | P2 | 批量更新 |
| GET | `/notification-preferences/webhook` | JWT | - | P2 | 个人 webhook |
| PUT | `/notification-preferences/webhook` | JWT | - | P2 | 更新 webhook |
| POST | `/notification-preferences/webhook/test` | JWT | - | P2 | 测试 webhook |
| GET | `/reports/dashboard` | JWT | - | P2 | 仪表盘 |
| GET | `/reports/trend` | JWT | - | P2 | 趋势 |
| GET | `/reports/status-distribution` | JWT | - | P2 | 状态分布 |
| GET | `/reports/severity-distribution` | JWT | - | P2 | 严重级别 |
| GET | `/reports/team-metrics` | JWT | - | P2 | 团队指标 |
| GET | `/reports/export/csv` | JWT | `reports:export` | P2 | CSV |
| GET | `/reports/export/json` | JWT | `reports:export` | P2 | JSON |

---

## 11. 凭证、平台设置、AI 目录

| Method | Path | 认证 | 权限 | 优先级 | 备注 |
|--------|------|------|------|--------|------|
| GET | `/credentials` | JWT | - | P1 | 个人/可用凭证 |
| POST | `/credentials` | JWT | - | P1 | 创建凭证 |
| PUT | `/credentials/{id}` | JWT | - | P1 | 更新凭证 |
| DELETE | `/credentials/{id}` | JWT | - | P1 | 删除凭证 |
| POST | `/credentials/test-connection` | JWT | - | P1 | 测试连接 |
| GET | `/admin/platform-credentials` | JWT | `users:manage` | P2 | 平台凭证 |
| POST | `/admin/platform-credentials` | JWT | `users:manage` | P2 | 创建平台凭证 |
| PUT | `/admin/platform-credentials/{id}` | JWT | `users:manage` | P2 | 更新平台凭证 |
| DELETE | `/admin/platform-credentials/{id}` | JWT | `users:manage` | P2 | 删除平台凭证 |
| GET | `/admin/platform-settings/email` | JWT | `system:settings` | P2 | 邮件配置 |
| PUT | `/admin/platform-settings/email` | JWT | `system:settings` | P2 | 更新邮件配置 |
| POST | `/admin/platform-settings/email/test` | JWT | `system:settings` | P2 | 测试邮件 |
| GET | `/admin/ai/providers` | JWT | `users:manage` | P2 | AI 厂商目录 |
| POST | `/admin/ai/providers` | JWT | `users:manage` | P2 | 创建厂商 |
| PUT | `/admin/ai/providers/{id}` | JWT | `users:manage` | P2 | 更新厂商 |
| DELETE | `/admin/ai/providers/{id}` | JWT | `users:manage` | P2 | 删除厂商 |
| GET | `/admin/ai/models` | JWT | `users:manage` | P2 | 模型目录 |
| POST | `/admin/ai/models` | JWT | `users:manage` | P2 | 创建模型 |
| PUT | `/admin/ai/models/{id}` | JWT | `users:manage` | P2 | 更新模型 |
| DELETE | `/admin/ai/models/{id}` | JWT | `users:manage` | P2 | 删除模型 |
| POST | `/admin/ai/models/{id}/test` | JWT | `users:manage` | P2 | 测试模型 |

---

## 12. 问题池、集成、检索、质量洞察

| Method | Path | 认证 | 权限 | 优先级 | 备注 |
|--------|------|------|------|--------|------|
| POST | `/inbound/connectors/{token}` | connector token | - | P2 | 外部信号接入 |
| GET | `/projects/{id}/issue-clusters` | JWT | `projects:read` | P2 | 问题簇列表 |
| GET | `/projects/{id}/issue-clusters/{clusterId}` | JWT | `projects:read` | P2 | 问题簇详情 |
| GET | `/projects/{id}/issue-clusters/{clusterId}/signals` | JWT | `projects:read` | P2 | 信号列表 |
| POST | `/projects/{id}/issue-clusters/{clusterId}/assign` | JWT | `projects:update` | P2 | 分配问题簇 |
| POST | `/projects/{id}/issue-clusters/{clusterId}/ignore` | JWT | `projects:update` | P2 | 忽略 |
| POST | `/projects/{id}/issue-clusters/{clusterId}/merge` | JWT | `projects:update` | P2 | 合并 |
| POST | `/projects/{id}/issue-clusters/{clusterId}/convert` | JWT | `projects:update` | P2 | 转缺陷 |
| POST | `/projects/{id}/issue-clusters/auto-triage` | JWT | `projects:update` | P2 | 自动分诊 |
| GET | `/projects/{id}/integrations` | JWT | `projects:read` | P2 | 连接器列表 |
| POST | `/projects/{id}/integrations` | JWT | `projects:update` | P2 | 创建连接器 |
| PUT | `/projects/{id}/integrations/{connectorId}` | JWT | `projects:update` | P2 | 更新连接器 |
| DELETE | `/projects/{id}/integrations/{connectorId}` | JWT | `projects:update` | P2 | 删除连接器 |
| POST | `/projects/{id}/integrations/{connectorId}/test` | JWT | `projects:update` | P2 | 测试 |
| POST | `/projects/{id}/integrations/{connectorId}/sync` | JWT | `projects:update` | P2 | 同步 |
| GET | `/projects/{id}/retriever-plugins` | JWT | `projects:read` | P2 | 检索器 |
| PUT | `/projects/{id}/retriever-plugins/{pluginId}` | JWT | `projects:update` | P2 | 更新 |
| PATCH | `/projects/{id}/retriever-plugins/{pluginId}/toggle` | JWT | `projects:update` | P2 | 开关 |
| PUT | `/projects/{id}/retriever-plugins/sort` | JWT | `projects:update` | P2 | 排序 |
| POST | `/projects/{id}/retriever-plugins/{pluginId}/test` | JWT | `projects:update` | P2 | 测试 |
| GET | `/projects/{id}/quality-insights/overview` | JWT | `projects:read` | P2 | 质量洞察 |

---

## 13. SSE 事件契约

| 事件名 | Room | data 字段 | 触发来源 |
|--------|------|-----------|----------|
| `defect:status_changed` | `defect:{id}`, `project:{id}` | `defectId`, `fromStatus`, `toStatus`, `operatorId` | 状态流转 |
| `defect:created` | `project:{id}` | `defectId`, `code`, `status` | 创建缺陷 |
| `defect:updated` | `defect:{id}`, `project:{id}` | `defectId`, changed fields | 更新缺陷 |
| `analysis:started` | `defect:{id}` | `defectId`, `taskId`, `agentTypes` | 触发分析 |
| `analysis:progress` | `defect:{id}` | `defectId`, `agentType`, `message`, `step` | 分析过程 |
| `analysis:completed` | `defect:{id}` | `defectId`, `reportIds`, `status` | 分析完成 |
| `analysis:failed` | `defect:{id}` | `defectId`, `error`, `status` | 分析失败 |
| `fix_task:created` | `defect:{id}` | `defectId`, `groupId`, `taskIds` | 创建修复 |
| `fix_task:progress` | `defect:{id}` | `taskId`, `step`, `message` | 修复过程 |
| `fix_task:completed` | `defect:{id}` | `taskId`, `prUrl`, `status` | 修复完成 |
| `comment:added` | `defect:{id}` | `defectId`, `commentId`, `userId` | 评论 |
| `notification` | `user:{id}` | `notificationId`, `category`, `title` | 通知 |

Golden event 样例:

```text
event: defect:status_changed
data: {"defectId":1,"fromStatus":"pending_analysis","toStatus":"analyzing","operatorId":99}

```

---

## 14. 第零阶段验收口径

| 验收项 | 当前要求 |
|--------|----------|
| 契约矩阵 | 本文档覆盖 Go 路由和前端核心调用 |
| OpenAPI | Python 服务可生成 `/openapi.json` |
| SSE golden | `bug_agent_py/tests/test_contract_baseline.py` 固化格式 |
| Schema diff | `bug_agent_py/scripts/schema_diff.py` 可对比 ORM 与 PostgreSQL |
| ORM baseline | `Base.metadata` 注册核心表 |
| 冒烟测试 | `python3 -m pytest -q` 通过 |

---

## 15. 后续维护规则

1. 新增或修改 API 前，必须先更新本契约矩阵。
2. 修改响应字段前，必须确认 `web/src/api/*` 和 `web/src/types/*` 是否兼容。
3. 修改状态流转前，必须更新状态机测试和 SSE 事件契约。
4. 修改数据库字段前，必须运行 schema diff 并说明是否影响 Go 版回滚。
5. 本文档中的 P0/P1/P2 优先级可在阶段评审时调整，但必须记录原因。

