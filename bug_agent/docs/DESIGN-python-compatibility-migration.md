# Python 重构兼容性详细设计

> 版本: v1.0  
> 日期: 2026-06-20  
> 状态: 评审稿  
> 关联 PRD: `docs/PRD_缺陷管理平台_python.md` v1.1-python

---

## 1. 设计目标

本设计用于约束 BugAgent 后端从 Go 重构到 Python 的兼容性实现。目标不是逐行翻译 Go 代码，而是在 Python 原生技术栈中实现与 Go 版等价的用户可见行为。

### 1.1 成功标准

| 标准 | 验收方式 |
|------|---------|
| 前端零改动 | `web/` 不修改业务代码，仅切换后端 baseURL 即可通过核心 E2E |
| 数据库兼容 | Python ORM 可直接读取 Go 版 PostgreSQL 数据备份 |
| API 兼容 | 关键 API 的路径、参数、响应、错误格式通过契约快照 |
| 状态兼容 | 13 个状态、24 条合法流转及副作用完全一致 |
| SSE 兼容 | 前端现有 SSE 消费逻辑无需调整 |
| Agent 兼容 | 分析报告、思考过程、Token 统计、失败语义可被前端直接展示 |
| 上线可回滚 | Python 切流失败时可切回 Go 版，数据库无需回滚 |

---

## 2. 总体架构

Python 版采用分层架构，对应 Go 版的 router / handler / service / model / adk / retrieval 分层。

```text
FastAPI Router
  -> Dependencies: auth, rbac, db session
  -> Service Layer: business rules and side effects
  -> Infrastructure: SQLAlchemy, Redis, Celery, SSE, Git, LLM clients
  -> Database: existing PostgreSQL schema baseline
```

### 2.1 层职责

| 层 | Python 模块 | 职责 |
|----|-------------|------|
| API 层 | `app/api/v1/*` | 路由注册、参数解析、响应模型、错误映射 |
| 依赖层 | `app/api/deps.py` | 当前用户、权限校验、项目/缺陷作用域解析 |
| Service 层 | `app/services/*` | 业务规则、状态副作用、事务边界 |
| Model 层 | `app/models/*` | SQLAlchemy ORM，保持 Go schema 兼容 |
| Schema 层 | `app/schemas/*` | Pydantic DTO，保持前端 camelCase 契约 |
| Agent 层 | `app/agent/*` | LangGraph 分析流程、工具调用、报告归一化 |
| Infrastructure | `app/infrastructure/*` | DB、Redis、SSE、Celery、JWT、加密 |

### 2.2 事务边界

写接口默认以单个 API 请求为事务边界。需要同时写业务表、状态历史、通知、审计的接口必须满足：

1. 主业务状态写入必须在事务内完成。
2. `status_changes` 与业务状态更新保持同事务。
3. 通知、SSE、审计失败不得回滚主业务事务，但必须记录错误日志。
4. Celery 异步任务只接收已提交事务后的实体 ID，不接收未持久化对象。

---

## 3. API 兼容设计

### 3.1 契约来源

API 契约矩阵由三类来源合并生成：

| 来源 | 用途 |
|------|------|
| `server/internal/router/router.go` | 后端真实路由、认证分组、路径结构 |
| `web/src/api/*` | 前端真实请求参数和响应消费方式 |
| `web/e2e/*`、`tests/e2e_*` | 用户关键路径和断言 |

### 3.2 响应封装

所有业务接口统一返回：

```json
{
  "code": 0,
  "data": {},
  "message": "success"
}
```

错误响应要求：

| 场景 | HTTP 状态 | code | message 要求 |
|------|-----------|------|--------------|
| 未登录/过期 | 401 | 401 | 与 Go 版一致，例如 `登录已过期` |
| 无权限 | 403 | 403 | 稳定可展示文本 |
| 资源不存在 | 404 | 404 | 包含资源类型，不泄露敏感信息 |
| 状态冲突 | 409 | 409 | 说明当前状态和目标操作不匹配 |
| 参数错误 | 422 或 Go 版兼容状态 | 非 0 | 字段级错误需归一化 |
| 服务错误 | 500 | 500 | 不返回堆栈 |

### 3.3 字段命名

数据库和 ORM 使用 snake_case，API 响应使用 camelCase。Pydantic schema 必须显式配置 alias，禁止在接口层手工拼字典绕过 schema。

常见字段映射：

| DB/ORM | API |
|--------|-----|
| `created_at` | `createdAt` |
| `updated_at` | `updatedAt` |
| `project_id` | `projectId` |
| `iteration_id` | `iterationId` |
| `defect_id` | `defectId` |
| `agent_types` | `agentTypes` |
| `api_endpoint` | `apiEndpoint` |

### 3.4 路由实现规则

1. FastAPI router 的 prefix 不得导致路径多一层或少一层。
2. `:id` 风格路径在 FastAPI 中写为 `{id}`，但 OpenAPI 和测试必须覆盖实际 URL。
3. 文件上传下载、SSE、inbound connector、invite code 等特殊认证接口单独标注。
4. 所有新增或变更端点先更新契约矩阵，再开发实现。

---

## 4. 数据库兼容设计

### 4.1 Baseline 策略

Python Alembic 不重放 Go 版历史迁移，而是以 Go 版当前生产 schema 作为 baseline。

执行策略：

1. 从 Go 版数据库导出 schema。
2. Python ORM 定义对齐该 schema。
3. Alembic 创建 baseline revision，仅标记当前结构。
4. Python 后续版本只追加增量迁移。

### 4.2 Schema Diff

需要实现 schema diff 脚本，对比：

| 类型 | 检查内容 |
|------|----------|
| 表 | 表是否缺失、是否多出未评审表 |
| 字段 | 名称、类型、nullable、默认值 |
| 索引 | 单列索引、组合索引、唯一索引 |
| 外键 | 引用表、引用字段、删除行为 |
| JSON/Text | Go 版序列化结构和 Python 版反序列化结构 |

阻断级差异：

- 删除 Go 版已有字段
- 改变字段类型或 nullable 语义
- 丢失唯一约束
- 状态、角色、权限默认值不一致
- 历史数据无法反序列化

### 4.3 历史数据验证

使用脱敏生产备份或等价 fixture 执行只读验证：

1. 用户、项目、迭代、仓库可正常查询。
2. 缺陷列表和详情可正常序列化。
3. 旧分析报告、修复任务、通知、审计可展示。
4. JSON 字段缺失或旧格式时有兼容默认值。

---

## 5. 状态机与副作用设计

状态机实现集中在 `WorkflowService`，禁止在各 API handler 中分散判断。

### 5.1 状态流转

状态流转必须基于矩阵校验。每次流转输出：

| 输出 | 要求 |
|------|------|
| `defects.status` | 更新为目标状态 |
| `status_changes` | 写入 from/to/operator/reason |
| SSE | 推送 `defect:status_changed` |
| 通知 | 按项目通知策略触发 |
| 审计 | 记录操作人、接口、资源 ID |

### 5.2 并发控制

状态流转必须防止并发覆盖：

1. 更新时带当前状态条件：`WHERE id = ? AND status = ?`。
2. 影响行数为 0 时返回 409。
3. 批量流转逐条返回结果，不因单条失败回滚全部，除非接口契约另有要求。

---

## 6. RBAC 兼容设计

权限系统分三层：

| 层级 | 示例 | 实现 |
|------|------|------|
| 平台级 | 用户管理、平台凭证、AI 目录 | `RequirePermission` |
| 项目级 | 项目成员、迭代、仓库、项目配置 | `RequireProjectPermission` |
| 缺陷级 | 缺陷详情、分配、流转、修复 | `RequireDefectPermission` |

权限缓存：

1. Redis key 包含 user_id、project_id、权限版本。
2. 角色或成员变更后主动失效。
3. Redis 不可用时可降级数据库查询，但必须记录 warning。

---

## 7. SSE 兼容设计

SSE 连接端点保持：

```text
GET /api/v1/sse?token={jwt}&rooms=defect:1,project:5
```

### 7.1 事件格式

```text
event: defect:status_changed
data: {"defectId":1,"fromStatus":"pending_analysis","toStatus":"analyzing"}

```

要求：

1. event 名与 Go 版一致。
2. data 使用 camelCase。
3. room 映射保持 `defect:{id}`、`project:{id}`。
4. 慢客户端断开不影响业务写入。
5. Redis Pub/Sub 失败时记录日志，不回滚主事务。

---

## 8. Agent 兼容设计

Python 版使用 LangGraph，但必须保留 Go 版 Agent 的外部行为。

### 8.1 分析流程

```text
触发分析
  -> 校验权限和缺陷状态
  -> 创建 analysis_task
  -> 状态变更为 analyzing
  -> Celery 提交 LangGraph 任务
  -> Planner 生成探索计划
  -> Executor 调用安全工具
  -> Analyzer 生成结构化报告
  -> PostProcess 归一化字段和证据
  -> 写 analysis_reports / ai_token_usage
  -> 状态变更为 pending_fix 或失败回退
```

### 8.2 报告 Schema

分析报告至少包含：

| 字段 | 要求 |
|------|------|
| `agentType` | product / ui / frontend / client / backend / test |
| `rootCause` | 根因摘要，失败时为空字符串或失败说明 |
| `affectedFiles` | 文件路径数组，必须限定在目标仓库 |
| `solution.steps` | 修复步骤数组，供修复引擎消费 |
| `confidence` | 0 到 1 |
| `evidence` | 工具发现的文件、片段、行号 |
| `tokenUsage` | prompt/completion/total |
| `thinkingEvents` | 前端流式展示所需事件 |

### 8.3 工具安全

1. 工具白名单按 Agent 类型过滤。
2. 文件读取必须限制在仓库根目录内。
3. 禁止通过工具执行任意 shell，除非后续明确评审。
4. MCP 服务命令必须匹配白名单。
5. 所有工具调用记录入 analysis task metadata。

---

## 9. 修复链路兼容设计

修复链路必须保持 8 步流水线：

```text
克隆仓库 -> 创建分支 -> AI 生成补丁 -> 应用补丁 -> 提交 -> 构建验证 -> 推送 -> 创建 PR
```

### 9.1 补丁应用

1. `oldContent` 必须在文件中精确出现一次。
2. 出现 0 次或多次均视为补丁失败。
3. 每次失败记录到 fix task logs。
4. 最多重试 3 次，重试必须带失败原因。

### 9.2 语言验证

不能只做 Python `ast.parse`。验证策略按仓库语言或项目配置选择：

| 类型 | 验证方式 |
|------|----------|
| Python | `python -m py_compile` 或 `ast.parse` |
| Go | `go test ./...` 或 `go test` 指定包 |
| Node/TS | `npm test` / `npm run build` / `tsc --noEmit` |
| 未配置 | 只做 diff 和文件存在校验，标记为弱验证 |

### 9.3 PR 生命周期

PR 状态同步规则：

| PR 状态 | 缺陷状态 |
|---------|----------|
| open | `pending_verify` |
| rejected/closed without merge | `pending_fix` |
| merged | `fixed` |
| completed action | `completed` |

Webhook 必须校验签名并做幂等处理，同一事件重复投递不得重复写状态历史。

---

## 10. 双跑、切流与回滚

### 10.1 双跑模式

上线前执行 Go/Python 双跑验证：

1. 同一份 fixture 数据分别请求 Go 和 Python。
2. 对比响应 JSON，忽略允许差异字段，如 traceId、耗时。
3. 对比 SSE golden event。
4. 对比数据库副作用。

### 10.2 切流策略

推荐按模块切流：

1. 健康检查、认证、用户资料。
2. 项目、迭代、仓库。
3. 缺陷主流程。
4. Agent 分析。
5. 修复和信号接入。

### 10.3 回滚策略

回滚要求：

1. Python 首次上线不得引入 Go 版无法识别的破坏性 schema。
2. 新增字段必须允许为空或有默认值。
3. Python 写入的新枚举值必须先在 Go 版兼容。
4. 回滚只切换流量，不执行数据库逆向迁移。

---

## 11. 测试策略

| 测试类型 | 覆盖内容 |
|----------|----------|
| 单元测试 | 状态机、权限判断、字段序列化、加密、指纹 |
| 集成测试 | API、数据库事务、副作用、SSE、Celery |
| 契约测试 | OpenAPI、响应 JSON、错误响应、SSE event |
| E2E | 前端核心流程 |
| 双跑测试 | Go/Python 响应和副作用一致 |
| 安全测试 | JWT、RBAC、凭证脱敏、Webhook 签名、路径逃逸 |

阻断上线的失败：

- 前端 E2E 核心流程失败
- 状态机矩阵失败
- schema diff 存在阻断差异
- 凭证明文泄露
- Go/Python 双跑关键接口响应不兼容

---

## 12. 未决问题

| 问题 | 建议 |
|------|------|
| 是否保留 Go 版和 Python 版长期并存 | 建议仅在灰度期并存，避免双写复杂度 |
| 是否支持 SQLite 开发模式 | 建议仅用于单元测试，完整兼容测试必须使用 PostgreSQL |
| LangGraph checkpoint 使用 PostgreSQL 还是独立存储 | 建议使用 PostgreSQL，但表需命名隔离并纳入 baseline 评审 |
| LightRAG/Qdrant 是否首版必须上线 | 建议第四/五阶段再启用，首版保留关键词和 RepoWiki |

