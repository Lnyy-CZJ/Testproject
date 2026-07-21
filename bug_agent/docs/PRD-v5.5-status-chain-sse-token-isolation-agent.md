# BugAgent v5.5 PRD

> Version: v5.5  
> Date: 2026-05-06  
> Status: Draft  
> Owner: Product + Engineering  
> Baseline: v5.4 已交付

---

## 1. 背景与现状

截至 `v5.4`，BugAgent 已具备完整的"信号接入 → 分诊 → AI分析 → AI/人工修复 → PR生命周期 → Agent记忆"闭环。但运行中暴露出五个结构性问题：

1. **状态链路断裂**：缺陷被驳回后只能走 `reopened → analyzing/pending_fix`，无法回到"待分析"重新来过；`pending_fix` 状态下没有"重新分析"入口，只能直接修复或人工修复，分析结论有误时无法纠正。
2. **实时推送架构重**：当前使用 WebSocket（gorilla/websocket + Hub/Client/Room），需要维护连接池、心跳、重连、认证等复杂逻辑。但实际场景中推送是单向的（服务端→客户端），客户端不需要向服务端发消息，WebSocket 的双向能力是浪费的。
3. **Token 统计失真**：缺陷维度的 Token/费用统计依赖 `AnalysisReport` 和 `FixTask` 的字段累加，但多轮修复、Fallback 重试等场景下存在漏计和重复计算，导致数据不可信。且缺少"单个缺陷"维度的汇总视图，也无法按项目、迭代维度聚合。
4. **仓库隔离缺失**：当前所有缺陷修复共享同一个临时目录（`os.MkdirTemp("bug-agent-repo-*")`），不同缺陷的修复过程可能互相干扰（文件冲突、分支污染）。修复完成后未及时清理，磁盘空间持续占用。
5. **Agent 能力碎片化**：项目级记忆、MCP 服务、Agent 技能三者的管理分散且不完整——记忆只有迭代级+项目级但无项目级管理入口；MCP 服务硬编码在配置文件中无法动态管理；技能（Agent Type + Tool 权限）无管理界面，且三者未统一接入 Agent 调度体系。

`v5.5` 的核心目标是：**修复链路闭环、推送架构轻量化、成本统计可信化、仓库隔离安全化、Agent 能力一体化。**

---

## 2. v5.5 目标与非目标

### 2.1 目标（Goals）

1. 驳回后允许重新打开回到"待分析"，`pending_fix` 状态新增"重新分析"功能。
2. 将 WebSocket 推送替换为 SSE，降低架构复杂度。
3. 修复 Token/费用统计异常，新增单个缺陷维度的 Token/费用汇总。
4. 按缺陷隔离仓库目录，修复完成后自动删除，定时清理残留目录。
5. 新增项目级记忆管理、MCP 服务管理、技能管理，统一接入 Agent 体系。

### 2.2 非目标（Non-Goals）

1. 不在 v5.5 实现客户端到服务端的实时通信需求（SSE 是单向的，如有双向需求另行评估）。
2. 不在 v5.5 实现仓库加密（仓库按缺陷隔离 + 修复后删除 + 定时清理已满足安全需求）。
3. 不在 v5.5 实现跨项目的 MCP 服务共享或技能共享。
4. 不在 v5.5 做 Agent 技能的自动编排或动态组合（仅做静态配置+管理界面）。

---

## 3. 核心问题定义（按优先级）

### P0（必须做）

1. **状态链路断裂，驳回后无法回到待分析**
   - 现状：`rejected → reopened → analyzing/pending_fix`，但 `reopened` 只能跳到 `analyzing` 或 `pending_fix`，无法回到 `pending_analysis`。
   - 影响：分析结论有误时，用户无法让缺陷回到"待分析"重新触发完整分析流程。

2. **Token 统计不可信，缺少缺陷维度汇总**
   - 现状：`AnalysisReport` 和 `FixTask` 各自记录 Token 数，但多轮修复、Fallback、记忆提取的 Token 未完整归集；无"单个缺陷总共消耗多少"的汇总视图。
   - 影响：成本数据不可信，无法按缺陷维度做成本管控。

3. **仓库无隔离，修复过程互相干扰**
   - 现状：所有缺陷修复共享临时目录，无隔离、无及时清理。
   - 影响：并发修复时文件冲突；磁盘空间持续占用。

### P1（应该做）

1. **WebSocket 架构过重**
   - 现状：WS Hub/Client/Room + 心跳 + 重连 + 认证，代码量大且维护成本高，但实际只有服务端→客户端的单向推送。
   - 影响：架构复杂度与实际需求不匹配，SSE 可大幅简化。

2. **Agent 能力管理碎片化**
   - 现状：记忆/MCP/技能三套管理各自为政，无统一入口，MCP 硬编码在配置文件。
   - 影响：用户无法自助管理 Agent 能力，运维依赖配置文件修改+重启。

---

## 4. 功能需求（FR）

### FR-1 优化状态链路（P0）

#### 4.1.1 问题本质

当前状态机存在两个断点：

1. **驳回后回不到待分析**：`rejected → reopened` 后只能跳到 `analyzing` 或 `pending_fix`，跳过了 `pending_analysis` 状态。用户希望驳回后能"重新打开"让缺陷回到"待分析"，重新走完整分析流程。
2. **待修复时无法重新分析**：`pending_fix` 状态下只能选择 AI 修复或人工修复，没有"重新分析"入口。当分析结论有误时，用户只能驳回再重新打开，操作路径长。

#### 4.1.2 方案

**变更 1：`reopened` 状态新增到 `pending_analysis` 的转换**

```
reopened ──→ pending_analysis  (新增：回到待分析，重新走完整分析流程)
reopened ──→ analyzing         (保留：直接重新分析)
reopened ──→ pending_fix       (保留：跳过分析直接修复)
```

**变更 2：`pending_fix` 状态新增"重新分析"转换**

```
pending_fix ──→ pending_analysis  (新增：重新分析，分析结论有误时使用)
pending_fix ──→ fixing            (保留)
pending_fix ──→ manual_fixing     (保留)
pending_fix ──→ rejected          (保留)
pending_fix ──→ suspended         (保留)
```

**变更 3：`rejected` 状态新增"重新打开"操作，目标状态为 `pending_analysis`**

当前 `rejected → reopened` 是唯一出口，用户需要再从 `reopened` 选择去向。优化为"重新打开"操作直接指定目标状态：

```
rejected ──→ reopened            (保留：通用重新打开)
rejected ──→ pending_analysis    (新增：驳回后直接回到待分析，最常用路径)
```

#### 4.1.3 数据模型变更

**状态机变更**（[workflow.go](file:///Users/jame/Workspace/bug_agent/server/internal/model/workflow.go)）：

```go
DefectStatusReopened: {
    DefectStatusPendingAnalysis: true,  // 新增
    DefectStatusAnalyzing:       true,  // 保留
    DefectStatusPendingFix:      true,  // 保留
    DefectStatusRejected:        true,  // 保留
},
DefectStatusPendingFix: {
    DefectStatusPendingAnalysis: true,  // 新增：重新分析
    DefectStatusFixing:          true,  // 保留
    DefectStatusManualFixing:    true,  // 保留
    DefectStatusRejected:        true,  // 保留
    DefectStatusSuspended:       true,  // 保留
},
DefectStatusRejected: {
    DefectStatusReopened:        true,  // 保留
    DefectStatusPendingAnalysis: true,  // 新增：直接回到待分析
},
```

#### 4.1.4 API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/defects/:id/reopen` | 重新打开缺陷，Body 指定 `targetStatus`（`pending_analysis` / `analyzing` / `pending_fix`） |
| POST | `/defects/:id/reanalyze` | 从 `pending_fix` 重新回到 `pending_analysis`（快捷操作，等价于 `ChangeStatus(pending_fix → pending_analysis)`） |

#### 4.1.5 前端交互

1. **驳回状态**：新增"重新打开"按钮，点击后弹出目标状态选择（默认 `pending_analysis`）。
2. **待修复状态**：新增"重新分析"按钮，点击后状态回到 `pending_analysis`，已有分析报告保留但标记为"已失效"。
3. **重新打开状态**：新增"回到待分析"选项。

#### 4.1.6 验收标准

1. `rejected` 状态下可"重新打开"到 `pending_analysis`。
2. `reopened` 状态下可跳转到 `pending_analysis`。
3. `pending_fix` 状态下可"重新分析"，状态回到 `pending_analysis`。
4. 重新分析时，旧分析报告标记为"已失效"但不删除。
5. 状态变更记录写入 `status_changes` 表，`comment` 字段标注操作类型（`reopen_to_analysis` / `reanalyze`）。

---

### FR-2 WebSocket 替换为 SSE（P1）

#### 4.2.1 问题本质

当前 WebSocket 实现包含 Hub/Client/Room 三层架构，双 goroutine（ReadPump/WritePump），ping/pong 心跳，认证超时，前端重连逻辑等，代码量约 500+ 行。但实际使用场景：

- **服务端→客户端**：推送缺陷状态变更、分析进度、修复进度等事件。
- **客户端→服务端**：仅有 `auth`（认证）和 `join/leave`（加入/离开房间）两种消息。

客户端到服务端的通信完全可以用 HTTP API 替代（认证由 JWT 中间件处理，房间订阅由 SSE 的 URL 路径参数表达）。WebSocket 的双向能力是过度设计。

#### 4.2.2 方案

**用 SSE（Server-Sent Events）替换 WebSocket**：

| 维度 | WebSocket（当前） | SSE（目标） |
|------|-------------------|-------------|
| 协议 | ws:// 全双工 | HTTP/1.1 半双工（服务端→客户端） |
| 连接管理 | Hub + Client + Room | 无状态，每个 SSE 连接独立 |
| 认证 | 连接后首条消息认证 | URL query token 或 Header Bearer |
| 房间订阅 | `join/leave` 消息 | URL 路径参数 `/sse?rooms=defect:1,defect:2` |
| 心跳 | ping/pong 60s | SSE 注释行 `:keepalive` 30s |
| 重连 | 前端指数退避 | 浏览器原生 `EventSource` 自动重连 |
| 代理兼容 | 需要 WebSocket 代理支持 | 纯 HTTP，任何代理都支持 |

**SSE 事件格式**（复用现有 `WSEvent` 结构，仅改传输层）：

```
event: defect:status_changed
data: {"defectId":123,"fromStatus":"analyzing","toStatus":"pending_fix"}

event: analysis:progress
data: {"defectId":123,"progress":0.6,"message":"正在分析代码上下文..."}

:keepalive
```

#### 4.2.3 后端架构变更

**删除**：`ws/` 包（hub.go、client.go、notify.go）

**新增**：`sse/` 包

```
sse/
├── broker.go      # SSE Broker，管理连接和事件分发
├── handler.go     # Gin handler，处理 SSE 连接请求
└── notify.go      # 业务层桥接（复用现有 NotifyService 接口）
```

**Broker 设计**：

```go
type Broker struct {
    subscribers map[string]map[chan SSEEvent]bool  // room → channels
    mu          sync.RWMutex
}

type SSEEvent struct {
    Event string      // 事件类型（如 "defect:status_changed"）
    Data  interface{} // 事件数据
}
```

- `Subscribe(rooms []string) chan SSEEvent`：订阅指定房间，返回事件 channel。
- `Unsubscribe(rooms []string, ch chan SSEEvent)`：取消订阅。
- `Publish(room string, event SSEEvent)`：向房间内所有订阅者推送事件。

**SSE Handler**：

```go
func (h *SSEHandler) HandleSSE(c *gin.Context) {
    // 1. JWT 认证（复用现有中间件）
    // 2. 解析 rooms 参数
    // 3. 订阅
    // 4. 设置 SSE headers
    // 5. 循环读取 channel，写入 SSE 格式
    // 6. 连接断开时取消订阅
}
```

#### 4.2.4 前端变更

**删除**：`wsManager.ts`、`useWebSocket.ts`

**新增**：`sseManager.ts`、`useSSE.ts`

```typescript
class SSEManager {
    private es: EventSource | null = null;
    private handlers = new Map<string, Set<EventHandler>>();

    connect(token: string, rooms: string[]) {
        const url = `/api/v1/sse?token=${token}&rooms=${rooms.join(',')}`;
        this.es = new EventSource(url);
        // 注册事件监听...
    }

    disconnect() { this.es?.close(); }
}
```

**关键差异**：
- 浏览器原生 `EventSource` 自动重连，无需手动实现指数退避。
- 房间订阅通过 URL 参数传递，无需 `join/leave` 消息。
- 认证通过 URL query token（SSE 不支持自定义 Header），服务端需验证 token 有效性。

#### 4.2.5 API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/sse` | SSE 连接入口，query 参数 `token` + `rooms` |
| DELETE | `/api/v1/ws` 相关路由 | 移除 WebSocket 路由 |

#### 4.2.6 验收标准

1. SSE 连接可正常建立，JWT 认证生效。
2. 缺陷状态变更、分析进度、修复进度等事件通过 SSE 正确推送。
3. 房间订阅机制生效（只收到订阅房间的事件）。
4. 连接断开后浏览器自动重连。
5. 前端所有原 WebSocket 功能在 SSE 下等价可用。
6. 删除 `ws/` 包和前端 `wsManager.ts`，无残留代码。

---

### FR-3 Token 统计修复与缺陷维度汇总（P0）

#### 4.3.1 问题本质

当前 Token 统计存在三类问题：

1. **漏计**：Fallback 重试的中间失败调用 Token 丢失，只记录了最终成功的调用。
2. **重复计算**：`AnalysisReport` 和 `FixTask` 各自记录 Token 数，但同一缺陷可能有多轮分析+多个修复任务，缺少统一汇总。
3. **无多维度汇总**：无法按项目、迭代、缺陷维度聚合 Token/费用，无法回答"这个项目/迭代/缺陷总共花了多少"。

#### 4.3.2 方案

**变更 1：新增 `AITokenUsage` 模型，统一记录所有 AI 调用的 Token 消耗**

删除 `AnalysisReport` 和 `FixTask` 上的 Token 相关字段，统一由 `AITokenUsage` 表记录。消耗类型仅区分"分析"和"修复"两类。

```go
type AITokenUsage struct {
    ID               uint    `gorm:"primaryKey" json:"id"`
    ProjectID        uint    `gorm:"index;not null" json:"projectId"`
    IterationID      *uint   `gorm:"index" json:"iterationId"`               // 所属迭代，可为空
    DefectID         uint    `gorm:"index;not null" json:"defectId"`
    ConsumptionType  string  `gorm:"size:20;not null" json:"consumptionType"` // "analysis" / "fix"
    SourceID         uint    `gorm:"index;not null" json:"sourceId"`          // AnalysisReport.ID 或 FixTask.ID
    AttemptIndex     int     `gorm:"default:0" json:"attemptIndex"`           // 第几次尝试（Fallback 场景）
    IsFinalAttempt   bool    `gorm:"default:false" json:"isFinalAttempt"`     // 是否最终成功的尝试
    Provider         string  `gorm:"size:50" json:"provider"`
    ModelName        string  `gorm:"size:100" json:"modelName"`
    PromptTokens     int     `json:"promptTokens"`
    CompletionTokens int     `json:"completionTokens"`
    TotalTokens      int     `json:"totalTokens"`
    EstimatedCostUSD float64 `json:"estimatedCostUsd"`
    DurationMs       int64   `json:"durationMs"`
    CreatedAt        int64   `json:"createdAt"`
}
```

**索引设计**：

| 索引 | 字段 | 用途 |
|------|------|------|
| `idx_project_type` | `(project_id, consumption_type)` | 项目级按类型汇总 |
| `idx_iteration_type` | `(iteration_id, consumption_type)` | 迭代级按类型汇总 |
| `idx_defect_type` | `(defect_id, consumption_type)` | 缺陷级按类型汇总 |
| `idx_source` | `(source_id)` | 关联溯源 |
| `idx_created_at` | `(created_at)` | 时间范围过滤 |

**变更 2：删除 `AnalysisReport` 和 `FixTask` 上的 Token 字段**

`AnalysisReport` 删除字段：

| 删除字段 | 类型 | 原用途 |
|----------|------|--------|
| `PromptTokens` | int | 分析 Prompt Token 数 |
| `CompletionTokens` | int | 分析 Completion Token 数 |
| `TotalTokens` | int | 分析总 Token 数 |
| `EstimatedCostUSD` | float64 | 分析预估费用 |
| `DurationMs` | int64 | 分析耗时 |
| `Provider` | string | AI 厂商 |
| `ModelName` | string | AI 模型名 |
| `PromptVersion` | string | Prompt 版本 |
| `FallbackUsed` | bool | 是否使用 Fallback |

`FixTask` 删除字段：

| 删除字段 | 类型 | 原用途 |
|----------|------|--------|
| `AIPromptTokens` | int | 修复 Prompt Token 数 |
| `AICompletionTokens` | int | 修复 Completion Token 数 |
| `AITotalTokens` | int | 修复总 Token 数 |
| `AIEstimatedCostUSD` | float64 | 修复预估费用 |
| `AIDurationMs` | int64 | 修复耗时 |
| `AIProvider` | string | AI 厂商 |
| `AIModelName` | string | AI 模型名 |
| `AIPromptVersion` | string | Prompt 版本 |
| `AIFallbackUsed` | bool | 是否使用 Fallback |
| `AILastError` | string | 最后一次错误 |

**变更 3：Fallback 场景下每次尝试都写入一条 `AITokenUsage`**

当前 `FixTask` 的 Token 字段只记录最后一次尝试。改为每次 Fallback 尝试都写入一条 `AITokenUsage`，`attempt_index` 递增，`is_final_attempt` 标记最终成功的尝试。

**变更 4：多维度汇总 API**

按项目、迭代、缺陷三个维度提供汇总查询，每个维度均区分分析/修复消耗：

```sql
-- 缺陷维度
SELECT 
    defect_id,
    consumption_type,
    SUM(prompt_tokens)     AS total_prompt_tokens,
    SUM(completion_tokens) AS total_completion_tokens,
    SUM(total_tokens)      AS total_tokens,
    SUM(estimated_cost_usd) AS total_cost_usd,
    COUNT(*)               AS call_count
FROM ai_token_usages
WHERE defect_id = ?
GROUP BY defect_id, consumption_type;

-- 迭代维度
SELECT 
    iteration_id,
    consumption_type,
    SUM(total_tokens)      AS total_tokens,
    SUM(estimated_cost_usd) AS total_cost_usd,
    COUNT(*)               AS call_count
FROM ai_token_usages
WHERE iteration_id = ?
GROUP BY iteration_id, consumption_type;

-- 项目维度
SELECT 
    consumption_type,
    SUM(total_tokens)      AS total_tokens,
    SUM(estimated_cost_usd) AS total_cost_usd,
    COUNT(*)               AS call_count
FROM ai_token_usages
WHERE project_id = ?
GROUP BY consumption_type;
```

#### 4.3.3 数据模型变更

**新增 `AITokenUsage` 模型**（如上）

**删除 `AnalysisReport` Token 字段**：`PromptTokens`、`CompletionTokens`、`TotalTokens`、`EstimatedCostUSD`、`DurationMs`、`Provider`、`ModelName`、`PromptVersion`、`FallbackUsed`

**删除 `FixTask` Token 字段**：`AIPromptTokens`、`AICompletionTokens`、`AITotalTokens`、`AIEstimatedCostUSD`、`AIDurationMs`、`AIProvider`、`AIModelName`、`AIPromptVersion`、`AIFallbackUsed`、`AILastError`

**数据库迁移**：迁移脚本需先将现有 `AnalysisReport` 和 `FixTask` 的 Token 数据回填到 `AITokenUsage`，再删除旧字段。

#### 4.3.4 API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/defects/:id/token-usage` | 获取单个缺陷的 Token/费用汇总（按 analysis/fix 分组） |
| GET | `/defects/:id/token-usage/details` | 获取单个缺陷的 Token/费用明细（每次调用记录） |
| GET | `/iterations/:id/token-usage` | 获取迭代级 Token/费用汇总（按 analysis/fix 分组） |
| GET | `/projects/:id/token-usage` | 获取项目级 Token/费用汇总（按 analysis/fix 分组） |
| GET | `/projects/:id/token-usage/by-iteration` | 获取项目下按迭代维度的 Token/费用排名 |
| GET | `/projects/:id/token-usage/by-defect` | 获取项目下按缺陷维度的 Token/费用排名 |

所有汇总 API 支持 `startDate` / `endDate` 时间范围过滤。

#### 4.3.5 前端交互

1. **缺陷详情页**：新增"Token 消耗"Tab，展示该缺陷的分析/修复 Token/费用汇总和明细。
2. **迭代概览页**：新增"AI 消耗"面板，展示迭代级分析/修复 Token/费用。
3. **项目概览页**：新增"AI 消耗"面板，展示项目级 Token/费用趋势、按迭代排名、按缺陷排名。
4. **消耗类型**：所有展示均区分"分析"和"修复"两类，分别展示调用次数、Token 数、费用。

#### 4.3.6 验收标准

1. 每次 AI 调用（分析、修复）都写入 `AITokenUsage`，`consumption_type` 正确标记。
2. Fallback 场景下每次尝试都有独立记录，`attempt_index` 正确递增。
3. `AnalysisReport` 和 `FixTask` 的 Token 字段已删除，所有 Token 数据从 `AITokenUsage` 查询。
4. 缺陷维度汇总 API 返回的数据与 `AITokenUsage` 明细一致。
5. 迭代维度汇总 API 返回的数据与 `AITokenUsage` 明细一致。
6. 项目级汇总 API 可按时间范围过滤。
7. 数据库迁移成功，旧数据已回填到 `AITokenUsage`。

---

### FR-4 按缺陷隔离仓库目录（P0）

#### 4.4.1 问题本质

当前仓库克隆使用 `os.MkdirTemp("bug-agent-repo-*")`，所有缺陷共享同一临时目录池，存在两个问题：

1. **无隔离**：不同缺陷的修复任务可能同时操作同一个仓库目录，文件冲突和分支污染。
2. **无清理**：修复完成后仓库目录未及时删除，磁盘空间持续占用。

#### 4.4.2 方案

**变更 1：按缺陷创建独立仓库目录**

目录结构：`{baseDir}/defects/{defectID}/{repoHash}/`

```
/data/bug-agent/repos/
├── defects/
│   ├── 123/                          # 缺陷 123
│   │   └── a1b2c3d4/                 # 仓库 hash（URL 的 SHA256 前8位）
│   │       ├── .git/
│   │       └── src/
│   └── 456/                          # 缺陷 456
│       └── e5f6g7h8/
│           ├── .git/
│           └── src/
```

- `baseDir`：可配置，默认 `/data/bug-agent/repos`。
- `defectID`：缺陷 ID，保证不同缺陷的目录完全隔离。
- `repoHash`：仓库 URL 的 SHA256 前8位，同一缺陷可能关联多个仓库。

**变更 2：修复完成后立即删除仓库目录**

- 修复任务完成（无论成功或失败）后，立即 `os.RemoveAll` 删除仓库目录。
- 更新 `DefectRepo` 状态为 `deleted`，记录删除时间。

**变更 3：定时清理残留目录**

- 定时任务（每小时）：扫描 `status=active` 且 `createdAt` 超过 24h 的 `DefectRepo` 记录，强制删除目录并更新状态。
- 防止异常中断导致的仓库目录残留。

#### 4.4.3 数据模型变更

**新增 `DefectRepo` 模型**：

```go
type DefectRepo struct {
    ID          uint       `gorm:"primaryKey" json:"id"`
    DefectID    uint       `gorm:"index;not null" json:"defectId"`
    ProjectID   uint       `gorm:"index;not null" json:"projectId"`
    RepoURL     string     `gorm:"size:500;not null" json:"repoUrl"`
    Branch      string     `gorm:"size:100" json:"branch"`
    LocalPath   string     `gorm:"size:500;not null" json:"localPath"`
    Status      string     `gorm:"size:20;not null;default:'active'" json:"status"` // "active" / "deleted"
    FixTaskID   *uint      `gorm:"index" json:"fixTaskId"`
    CreatedAt   time.Time  `json:"createdAt"`
    DeletedAt   *time.Time `json:"deletedAt"`
}
```

**`FixTask` 新增字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `DefectRepoID` | *uint | 关联的 DefectRepo 记录 |

#### 4.4.4 仓库生命周期管理

```
1. 触发修复 → 克隆仓库到 /data/bug-agent/repos/defects/{defectID}/{repoHash}/
2. 写入 DefectRepo 记录（status=active）
3. 执行修复任务
4. 修复完成 → os.RemoveAll 删除目录
5. 更新 DefectRepo（status=deleted, deletedAt=now）
6. 定时任务：扫描 status=active 且 createdAt 超过 24h 的记录，强制清理
```

#### 4.4.5 API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/defects/:id/repos` | 获取缺陷关联的仓库列表及状态 |
| DELETE | `/defects/:id/repos/:repoId` | 手动清理缺陷的仓库目录 |
| GET | `/admin/repos/orphaned` | 管理员查看所有孤立仓库（无活跃修复任务的 active 仓库） |
| POST | `/admin/repos/cleanup` | 管理员触发全局仓库清理 |

#### 4.4.6 验收标准

1. 不同缺陷的仓库目录完全隔离，路径包含缺陷 ID。
2. 修复完成后仓库目录自动删除，`DefectRepo` 状态更新为 `deleted`。
3. 超过 24h 未删除的活跃仓库被定时任务清理。
4. 并发修复不同缺陷时互不干扰。
5. 管理员可查看和清理孤立仓库。

---

### FR-5 项目级记忆/MCP/技能管理接入 Agent 体系（P1）

#### 4.5.1 问题本质

当前 Agent 能力管理存在三个碎片化问题：

1. **记忆管理**：后端已有 `AgentMemory` 模型和 `AgentMemoryService`，前端有 `MemoryManager` 组件，但 MCP 和技能没有对应的管理入口。
2. **MCP 服务管理**：MCP 服务器配置硬编码在 `config.yaml` 中（`mcp.servers`），无法动态增删，修改后需重启服务。
3. **技能管理**：Agent 的"技能"通过 Agent Type + Tool 权限矩阵隐式定义，无管理界面，用户无法自助配置。

三者未统一接入 Agent 调度体系，导致：
- 分析/修复时无法根据项目配置动态选择 MCP 工具。
- 技能组合固定，无法按项目定制 Agent 行为。
- 管理分散，运维成本高。

#### 4.5.2 方案

**核心思路**：将记忆、MCP 服务、技能统一为"项目级 Agent 配置"，在项目设置中集中管理，Agent 调度时从项目配置读取。

##### 4.5.2.1 项目级 MCP 服务管理

**数据模型**：

```go
type ProjectMCPServer struct {
    ID          uint      `gorm:"primaryKey" json:"id"`
    ProjectID   uint      `gorm:"index;not null" json:"projectId"`
    Name        string    `gorm:"size:100;not null" json:"name"`
    Command     string    `gorm:"size:500;not null" json:"command"`
    Args        string    `gorm:"type:text" json:"args"`          // JSON array
    Description string    `gorm:"type:text" json:"description"`
    Enabled     bool      `gorm:"default:true" json:"enabled"`
    CreatedBy   uint      `json:"createdBy"`
    CreatedAt   time.Time `json:"createdAt"`
    UpdatedAt   time.Time `json:"updatedAt"`
}
```

**管理能力**：
- 项目设置中新增"MCP 服务"Tab，支持 CRUD 和启禁用。
- Agent 调度时，从 `ProjectMCPServer` 读取启用的 MCP 服务，动态创建 Toolset 注入 Agent。
- 替换当前从 `config.yaml` 读取 MCP 配置的逻辑。

**安全**：
- `allowedMCPCommands` 白名单保留，项目级配置的 Command 也需通过白名单校验。
- MCP 服务进程以受限用户运行，沙箱隔离。

##### 4.5.2.2 项目级技能管理

**数据模型**：

```go
type ProjectAgentSkill struct {
    ID          uint      `gorm:"primaryKey" json:"id"`
    ProjectID   uint      `gorm:"index;not null" json:"projectId"`
    Name        string    `gorm:"size:100;not null" json:"name"`
    AgentType   string    `gorm:"size:20;not null" json:"agentType"`  // frontend/backend/ui/test/client/custom
    Instruction string    `gorm:"type:text" json:"instruction"`       // 自定义 Prompt 指令
    Tools       string    `gorm:"type:text" json:"tools"`             // JSON array: 允许的工具列表
    MCPServerIDs string   `gorm:"type:text" json:"mcpServerIds"`      // JSON array: 关联的 MCP 服务 ID
    MemoryCategories string `gorm:"type:text" json:"memoryCategories"` // JSON array: 注入的记忆类别
    Enabled     bool      `gorm:"default:true" json:"enabled"`
    IsDefault   bool      `gorm:"default:false" json:"isDefault"`     // 是否为系统默认技能
    CreatedBy   uint      `json:"createdBy"`
    CreatedAt   time.Time `json:"createdAt"`
    UpdatedAt   time.Time `json:"updatedAt"`
}
```

**技能定义**：一个"技能"是 Agent Type + 自定义 Prompt + 工具集 + MCP 服务 + 记忆类别的组合。

**管理能力**：
- 项目设置中新增"技能"Tab，支持 CRUD 和启禁用。
- 系统预置 5 个默认技能（frontend/backend/ui/test/client），`is_default=true`，用户可修改但不可删除。
- 用户可创建自定义技能，指定 Agent Type、自定义 Prompt、工具集、关联 MCP 服务、注入记忆类别。
- 分析/修复时，根据缺陷类型和项目配置选择技能。

##### 4.5.2.3 统一接入 Agent 调度

**当前 Agent 调度流程**：

```
ADKAnalysisService.PerformAnalysis
  → 读取项目 AI 配置
  → 创建 Agent（硬编码的 Agent Type + Prompt + Tool 权限）
  → 从 config.yaml 读取 MCP 服务器
  → 注入记忆
  → 执行
```

**优化后**：

```
ADKAnalysisService.PerformAnalysis
  → 读取项目 AI 配置
  → 读取项目技能配置（ProjectAgentSkill）
  → 选择匹配的技能（根据缺陷类型 + 技能 AgentType）
  → 从技能配置构建 Agent：
      - Instruction = 技能的自定义 Prompt
      - Tools = 技能的工具白名单
      - MCP = 技能关联的 MCP 服务（从 ProjectMCPServer 读取）
      - Memory = 技能指定的记忆类别（从 AgentMemory 读取）
  → 执行
```

#### 4.5.3 API 变更

**MCP 服务管理**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/projects/:id/mcp-servers` | 获取项目 MCP 服务列表 |
| POST | `/projects/:id/mcp-servers` | 新增 MCP 服务 |
| PUT | `/projects/:id/mcp-servers/:serverId` | 编辑 MCP 服务 |
| DELETE | `/projects/:id/mcp-servers/:serverId` | 删除 MCP 服务 |
| PATCH | `/projects/:id/mcp-servers/:serverId/toggle` | 启禁用 MCP 服务 |
| POST | `/projects/:id/mcp-servers/:serverId/test` | 测试 MCP 服务连通性 |

**技能管理**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/projects/:id/skills` | 获取项目技能列表 |
| POST | `/projects/:id/skills` | 新增自定义技能 |
| PUT | `/projects/:id/skills/:skillId` | 编辑技能 |
| DELETE | `/projects/:id/skills/:skillId` | 删除技能（默认技能不可删） |
| PATCH | `/projects/:id/skills/:skillId/toggle` | 启禁用技能 |

#### 4.5.4 前端交互

1. **项目设置页**：新增三个 Tab——"记忆管理"、"MCP 服务"、"技能管理"。
2. **记忆管理**：复用现有 `MemoryManager` 组件，从迭代设置移到项目设置。
3. **MCP 服务**：表格展示，支持新增/编辑/删除/启禁用/测试连通性。
4. **技能管理**：卡片式展示，每个技能显示 Agent Type + 工具集 + MCP + 记忆类别，支持编辑和启禁用。

#### 4.5.5 验收标准

1. 项目设置中可管理 MCP 服务（CRUD + 启禁用 + 测试连通性）。
2. 项目设置中可管理技能（CRUD + 启禁用，默认技能不可删）。
3. Agent 调度时从项目配置读取技能和 MCP 服务，动态构建 Agent。
4. 修改项目 MCP 服务或技能后，后续分析/修复任务立即生效，无需重启服务。
5. `config.yaml` 中的 `mcp.servers` 配置标记为 deprecated，迁移到数据库后移除。

---

## 5. 迭代计划

> 节奏建议：每迭代 2 周，总计 3 个迭代（6 周）。  
> 优先顺序：状态链路 + Token 统计 + 仓库隔离 > SSE 替换 > Agent 能力管理。

### Iteration 5.5.1（P0）- 状态链路 + Token 统计 + 仓库隔离

目标：修复三个结构性缺陷，确保核心链路正确、成本可信、仓库安全。

必须完成：
1. 状态机变更（`reopened → pending_analysis`、`pending_fix → pending_analysis`、`rejected → pending_analysis`）。
2. "重新打开"和"重新分析"API 及前端交互。
3. `AITokenUsage` 模型及写入逻辑（分析、修复），删除 `AnalysisReport` 和 `FixTask` 的 Token 字段，旧数据回填。
4. 缺陷维度、迭代维度、项目维度 Token/费用汇总 API。
5. 缺陷维度 Token/费用前端展示。
6. `DefectRepo` 模型及按缺陷隔离仓库目录。
7. 修复完成后自动清理仓库目录。
8. 孤立仓库定时清理任务。

交付物：
1. 驳回后可重新打开回到待分析，待修复时可重新分析。
2. 每次 AI 调用的 Token 消耗完整记录（分析/修复），缺陷/迭代/项目维度汇总可查。
3. 不同缺陷的仓库目录完全隔离，修复后自动清理。

### Iteration 5.5.2（P1）- SSE 替换 WebSocket

目标：将实时推送从 WebSocket 替换为 SSE，降低架构复杂度。

必须完成：
1. `sse/` 包实现（Broker + Handler + NotifyService 桥接）。
2. SSE 连接认证（JWT via query token）。
3. SSE 房间订阅机制。
4. SSE 心跳（`:keepalive`）。
5. 前端 `sseManager.ts` + `useSSE.ts` 实现。
6. 前端所有 WebSocket 使用点迁移到 SSE。
7. 删除 `ws/` 包和前端 `wsManager.ts` / `useWebSocket.ts`。
8. 删除 WebSocket 路由和中间件。

交付物：
1. SSE 推送完整替代 WebSocket，功能等价。
2. 架构简化，代码量减少。

### Iteration 5.5.3（P1）- Agent 能力一体化

目标：项目级记忆/MCP/技能统一管理，接入 Agent 调度体系。

必须完成：
1. `ProjectMCPServer` 模型及 CRUD API。
2. `ProjectAgentSkill` 模型及 CRUD API。
3. MCP 服务测试连通性 API。
4. Agent 调度改造：从项目配置读取技能和 MCP 服务，动态构建 Agent。
5. 前端项目设置页新增"记忆管理"、"MCP 服务"、"技能管理"Tab。
6. `config.yaml` 中 `mcp.servers` 迁移到数据库。

交付物：
1. 项目设置中可管理记忆、MCP 服务、技能。
2. Agent 调度从项目配置动态构建，修改即时生效。

---

## 6. 里程碑与成功指标

### 里程碑

1. M1（第 2 周）：状态链路闭环，Token 统计可信，仓库隔离安全。
2. M2（第 4 周）：SSE 替换 WebSocket 完成，架构简化。
3. M3（第 6 周）：Agent 能力一体化，项目级管理可用。

### 成功指标

1. 驳回后重新打开到待分析的操作成功率：100%。
2. Token 统计完整率：≥ 99% 的 AI 调用有 `AITokenUsage` 记录（对比 AI 厂商侧的调用量）。
3. 缺陷/迭代/项目维度 Token/费用汇总与明细一致率：100%。
4. 仓库隔离率：100%（不同缺陷的仓库目录无交叉）。
5. 仓库清理率：≥ 95% 的修复完成后仓库在 1h 内删除。
6. SSE 推送延迟：P99 < 500ms（与当前 WebSocket 对比无退化）。
7. MCP 服务管理可用率：项目级 MCP 配置修改后即时生效，无需重启。

---

## 7. 风险与对策

1. **风险：SSE 不支持自定义 Header，认证只能走 URL query token**
   - 对策：token 通过 URL query 传递，服务端在 SSE handler 中验证；token 仅用于 SSE 连接建立，不记录到访问日志；连接建立后 token 不再需要。
   - 降级：如安全团队不允许 URL 传 token，可改用短期 ticket 机制（先 HTTP API 申请 ticket，SSE 连接用 ticket）。

2. **风险：SSE 连接数受浏览器同域限制（HTTP/1.1 下 6 个）**
   - 对策：全局只维护一个 SSE 连接，通过房间机制过滤事件；HTTP/2 下无此限制。
   - 当前场景：每个用户只需一个 SSE 连接，不会触发限制。

3. **风险：Token 字段删除后旧数据丢失**
   - 对策：迁移脚本先回填旧数据到 `AITokenUsage`，再删除旧字段；迁移过程支持回滚。
   - 验证：迁移后对比 `AITokenUsage` 汇总与旧字段累加结果一致。

4. **风险：项目级 MCP 服务动态加载可能导致 Agent 启动变慢**
   - 对策：MCP Toolset 缓存机制，相同配置复用；MCP 服务测试连通性 API 提前验证。
   - 超时保护：MCP Toolset 初始化超时 30s，超时后跳过该 MCP 服务。

5. **风险：技能组合爆炸，用户配置不当导致 Agent 行为异常**
   - 对策：默认技能不可删除，保证基础能力可用；自定义技能启用前需测试；Agent 执行异常时自动降级到默认技能。

---

## 8. v5.5 最终优先级结论

如果资源不足，按以下顺序确保收益最大化：

1. **必须先做**：`FR-1 状态链路` + `FR-3 Token 统计` + `FR-4 仓库隔离` — 这是核心链路正确性、成本可信度、安全性的硬需求，不做则平台基础不可靠。
2. **第二优先**：`FR-2 SSE 替换` — 架构简化，降低维护成本，但不影响功能正确性。
3. **第三优先**：`FR-5 Agent 能力一体化` — 提升可配置性和自助管理能力，有则加分，无则不影响基本功能。

这条顺序保证：先把基础打牢（链路正确 + 成本可信 + 仓库安全），再简化架构，最后提升可配置性。
