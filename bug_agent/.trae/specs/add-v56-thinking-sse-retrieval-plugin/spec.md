# BugAgent v5.6 PRD — 思考过程可视化 / SSE流式推送 / 检索层插件化

> Version: v5.6
> Date: 2026-05-08
> Status: Draft
> Baseline: v5.5 已交付

---

## 1. 背景与现状

截至 `v5.5`，BugAgent 已完成状态链路闭环、SSE 推送替换 WebSocket、Token 统计可信化、仓库隔离安全化、Agent 能力一体化。但运行中暴露出三个结构性问题：

1. **AI 思考过程不可见**：当前 AI 分析时，前端仅展示一个静态 Spinner + 轮播文案（"正在连接AI服务…""正在收集代码上下文…"），用户无法看到 Agent 真实的推理步骤和工具调用过程。后端 `StreamEvent` 已有 `partial`/`final` 两种事件类型，但前端 `TriggerAnalysis` 走的是异步触发+轮询模式（`useDefectActions` 中 `startPolling` 每 3s 轮询 `listReports` + `getDefect`），完全未消费流式事件。
2. **分析接口仍是轮询模式**：`TriggerAnalysis` 接口是异步触发，前端靠 `setTimeout` 轮询等待结果。后端已有 `TriggerAnalysisStream` + `StreamToSSE` 的流式实现，但前端未对接。轮询模式存在 3-5s 延迟、无实时进度、最多 40 轮超时等问题。
3. **检索层硬编码，不可配置**：当前 `retrieval.Router` 只注册了 `KeywordRetriever`，`ADKAnalysisService` 初始化时硬编码 `retrieval.NewRouter(retrieval.NewKeywordRetriever())`。无法动态增删检索插件（如 RAG 检索、需求文档检索），无法调整检索顺序和权重，无法按项目配置不同的检索策略。

`v5.6` 的核心目标是：**让 AI 思考过程透明可见、将分析接口从轮询改为 SSE 流式推送、将检索层插件化并支持项目级配置。**

---

## 2. v5.6 目标与非目标

### 2.1 目标（Goals）

1. 前端实时展示 AI Agent 的思考过程（推理步骤、工具调用、中间结论），替代当前的静态 Spinner。
2. 将 AI 分析接口从异步触发+轮询改为 SSE 流式推送，前端实时消费 `StreamEvent`。
3. 检索层抽象为可插拔插件架构，支持仓库检索、RAG 检索、需求检索等插件，插件可开关、可排序，按项目独立配置。

### 2.2 非目标（Non-Goals）

1. 不在 v5.6 实现思考过程的回放或持久化存储（仅实时展示，分析完成后从 `AnalysisReport` 查看）。
2. 不在 v5.6 实现检索插件的热加载/卸载（插件注册在服务启动时完成，运行时仅控制开关和顺序）。
3. 不在 v5.6 实现自定义检索插件的动态上传（插件由系统预置，用户只能开关和排序）。
4. 不在 v5.6 修改修复流程（FixTask）的推送方式，仅改造分析流程。

---

## 3. 核心问题定义（按优先级）

### P0（必须做）

1. **AI 思考过程不可见，用户无法判断分析是否在正常推进**
   - 现状：分析时前端展示 Spinner + 轮播文案，用户只能等待，无法感知进度。
   - 影响：长时间分析时用户焦虑，无法判断是否卡住；分析失败时无法定位卡在哪个步骤。

2. **分析接口轮询模式延迟高、无实时进度**
   - 现状：`TriggerAnalysis` 异步触发，前端 3s 轮询，最多 40 轮（2 分钟）超时。
   - 影响：进度感知延迟 3-5s；无法获取中间状态；轮询浪费请求。

### P1（应该做）

1. **检索层硬编码，无法按项目配置检索策略**
   - 现状：`retrieval.Router` 只注册了 `KeywordRetriever`，无法动态增删。
   - 影响：无法接入 RAG 检索、需求文档检索等新检索源；无法按项目调整检索策略。

---

## 4. 功能需求（FR）

### FR-1 前端展示 AI Agent 思考过程（P0）

#### 4.1.1 问题本质

当前 `StreamEvent` 结构已包含 `partial`（中间推理片段）和 `final`（最终结果）两种事件，但前端完全未消费。`convertEvent` 函数将 ADK 的 `session.Event` 转换为 `StreamEvent`，但只提取了文本内容和完成标记，未提取工具调用信息。

用户需要看到：
- Agent 当前在做什么（推理步骤描述）
- Agent 调用了哪些工具（工具名 + 参数摘要）
- Agent 的中间结论（部分推理文本）
- 整体进度（步骤编号 / 阶段标识）

#### 4.1.2 方案

**变更 1：扩展 `StreamEvent` 结构，增加思考过程事件类型**

```go
type StreamEvent struct {
    Type       string `json:"type"`                 // "thinking" / "tool_call" / "tool_result" / "partial" / "final" / "error"
    Agent      string `json:"agent,omitempty"`      // Agent 名称
    Content    string `json:"content,omitempty"`    // 文本内容
    ToolName   string `json:"toolName,omitempty"`   // 工具名称（tool_call/tool_result 时）
    ToolInput  string `json:"toolInput,omitempty"`  // 工具输入摘要（tool_call 时）
    ToolOutput string `json:"toolOutput,omitempty"` // 工具输出摘要（tool_result 时）
    StepIndex  int    `json:"stepIndex,omitempty"`  // 步骤序号
    Phase      string `json:"phase,omitempty"`      // 阶段标识："retrieval" / "analysis" / "validation"
    Partial    bool   `json:"partial,omitempty"`
    Done       bool   `json:"done,omitempty"`
    Error      string `json:"error,omitempty"`
}
```

**变更 2：改造 `convertEvent` 函数，识别并转换工具调用事件**

ADK 的 `session.Event` 中，工具调用通过 `Content.Parts` 中的 `FunctionCall` 和 `FunctionResponse` 体现。需要识别这些 Part 类型，转换为对应的 `StreamEvent`。

**变更 3：前端新增 `ThinkingProcess` 组件**

在 `DefectAnalysisPanel` 中，当 `analyzing=true` 时，替换当前的 Spinner 为 `ThinkingProcess` 组件，实时展示：

- **步骤时间线**：纵向时间线，每一步显示阶段图标 + 描述文本 + 时间戳
- **工具调用卡片**：折叠展示工具名、输入摘要、输出摘要
- **推理文本流**：实时追加 Agent 的中间推理文本（打字机效果）
- **进度指示**：顶部显示当前阶段（检索 → 分析 → 验证）

**变更 4：分析完成后，思考过程消失，展示分析报告**

当收到 `type=final` 事件后，思考过程组件淡出，展示分析报告面板。

#### 4.1.3 前端交互

1. **分析中状态**：展示 `ThinkingProcess` 组件，替代 Spinner + 轮播文案。
2. **步骤展示**：每个步骤包含阶段图标、描述文本、耗时。工具调用可展开查看详情。
3. **实时追加**：`partial` 事件实时追加到当前步骤的推理文本区域。
4. **完成切换**：收到 `final` 事件后，思考过程淡出，展示分析报告。

#### 4.1.4 验收标准

1. AI 分析过程中，前端实时展示思考步骤（推理、工具调用、中间结论）。
2. 工具调用事件正确展示工具名和输入/输出摘要。
3. `partial` 事件实时追加，无延迟（SSE 推送延迟 < 500ms）。
4. 分析完成后，思考过程消失，展示分析报告。
5. 分析失败时，展示错误步骤和错误信息。

---

### FR-2 分析接口从轮询改为 SSE 流式推送（P0）

#### 4.2.1 问题本质

当前分析流程：

```
前端 → POST /agents/analyze（异步触发）
前端 → setTimeout 3s 轮询 GET /defects/:id/reports + GET /defects/:id
```

后端已有流式接口：

```
前端 → POST /agents/analyze/stream → SSE 事件流
```

但前端未对接 `TriggerAnalysisStream`，仍在使用轮询模式。

#### 4.2.2 方案

**变更 1：前端 `handleTriggerAnalysis` 改为调用流式接口**

将 `triggerAnalysis`（异步触发）替换为 `triggerAnalysisStream`（SSE 流式），使用 `fetch` + `ReadableStream` 消费 SSE 事件流（因为需要 POST 请求体，`EventSource` 只支持 GET）。

**变更 2：前端新增 `useAnalysisStream` Hook**

```typescript
function useAnalysisStream(defectId: number) {
  // 调用 POST /agents/analyze/stream
  // 消费 SSE 事件流
  // 返回 { steps, currentPhase, analyzing, error, startStream }
}
```

- `startStream(agentTypes: string[])`：发起流式分析请求。
- `steps`：已收集的思考步骤列表。
- `currentPhase`：当前阶段。
- `analyzing`：是否分析中。
- `error`：错误信息。

**变更 3：删除轮询逻辑**

- 删除 `useDefectActions` 中的 `startPolling` / `stopPolling` / `pollingTimerRef` / `pollingActiveRef`。
- 删除 `analyzingProgress` 状态（由 `useAnalysisStream` 的 `steps` 替代）。
- `analyzing` 状态由 `useAnalysisStream` 提供。

**变更 4：后端 `TriggerAnalysisStream` 增加分析完成后的状态更新和报告保存**

当前 `PerformAnalysisStream` 只返回原始事件流，不保存 `AnalysisReport`。需要在流结束后：
- 保存 `AnalysisReport` 到数据库。
- 更新缺陷状态为 `pending_fix`。
- 记录 `AITokenUsage`。
- 发布 Agent 评论。

**变更 5：后端 `StreamToSSE` 改造，支持扩展后的 `StreamEvent` 格式**

当前 `StreamToSSE` 只输出 `data:` 行，不输出 `event:` 行。改造为同时输出 `event:` 和 `data:` 行，让前端可以按事件类型监听。

```
event: thinking
data: {"type":"thinking","content":"正在检索相关代码...","phase":"retrieval","stepIndex":1}

event: tool_call
data: {"type":"tool_call","toolName":"search_code","toolInput":"query=内存泄漏","stepIndex":2}

event: partial
data: {"type":"partial","content":"根据代码分析，该缺陷的根因是...","partial":true}

event: final
data: {"type":"final","content":"{...}","done":true}
```

#### 4.2.3 API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agents/analyze/stream` | 流式分析接口（已有，需增强） |
| POST | `/agents/analyze` | 保留作为异步触发接口（兼容） |

#### 4.2.4 验收标准

1. 前端调用 `POST /agents/analyze/stream` 后，SSE 事件流实时推送。
2. 前端不再轮询 `GET /defects/:id/reports`，分析进度完全由 SSE 事件驱动。
3. 分析完成后，`AnalysisReport` 已保存到数据库，缺陷状态已更新为 `pending_fix`。
4. 分析失败时，缺陷状态回退到 `pending_analysis`，前端展示错误信息。
5. SSE 推送延迟 P99 < 500ms。

---

### FR-3 检索层插件化与项目级配置（P1）

#### 4.3.1 问题本质

当前检索层架构：

```
retrieval.Retriever（接口）
  └── retrieval.Router（聚合多个 Retriever，RRF 融合排序）
        └── retrieval.KeywordRetriever（唯一实现）
```

问题：
1. `ADKAnalysisService` 初始化时硬编码 `retrieval.NewRouter(retrieval.NewKeywordRetriever())`，无法动态增删。
2. 没有项目级配置，所有项目使用相同的检索策略。
3. 无法接入新的检索源（RAG、需求文档等）。

#### 4.3.2 方案

**变更 1：新增 `RetrieverPlugin` 模型，项目级检索插件配置**

```go
type RetrieverPlugin struct {
    ID          uint      `gorm:"primaryKey" json:"id"`
    ProjectID   uint      `gorm:"index;not null" json:"projectId"`
    Name        string    `gorm:"size:100;not null" json:"name"`        // 插件标识："keyword" / "rag" / "requirement"
    DisplayName string    `gorm:"size:200;not null" json:"displayName"` // 显示名称
    Description string    `gorm:"type:text" json:"description"`         // 插件描述
    Config      string    `gorm:"type:text" json:"config"`              // JSON: 插件专属配置
    Enabled     bool      `gorm:"default:true" json:"enabled"`          // 是否启用
    SortOrder   int       `gorm:"default:0" json:"sortOrder"`           // 排序权重，越小越靠前
    IsBuiltIn   bool      `gorm:"default:false" json:"isBuiltIn"`       // 是否系统内置
    CreatedBy   uint      `json:"createdBy"`
    CreatedAt   time.Time `json:"createdAt"`
    UpdatedAt   time.Time `json:"updatedAt"`
}
```

**内置插件定义**：

| Name | DisplayName | 说明 | Config 示例 |
|------|-------------|------|-------------|
| `keyword` | 仓库关键词检索 | 基于文件名和内容的关键词匹配 | `{}` |
| `rag` | RAG 语义检索 | 基于向量数据库的语义检索 | `{"endpoint":"http://rag:8080","collection":"code"}` |
| `requirement` | 需求文档检索 | 从需求文档中检索相关上下文 | `{"docPath":"/docs/requirements"}` |

**变更 2：新增 `RetrieverPluginRegistry`，管理插件实例的生命周期**

```go
type RetrieverPluginRegistry struct {
    factories map[string]RetrieverFactory // name → factory
}

type RetrieverFactory func(config string) (Retriever, error)

func (r *RetrieverPluginRegistry) Register(name string, factory RetrieverFactory)
func (r *RetrieverPluginRegistry) Create(name string, config string) (Retriever, error)
```

- 服务启动时，注册所有内置插件的 Factory。
- 运行时根据项目配置动态创建 Retriever 实例。

**变更 3：`ADKAnalysisService` 改为从项目配置动态构建 `Router`**

```go
func (s *ADKAnalysisService) buildRetrieverForProject(projectID uint) retrieval.Retriever {
    // 1. 查询项目的 RetrieverPlugin 配置（enabled=true，按 sortOrder 排序）
    // 2. 用 Registry 创建每个插件的 Retriever 实例
    // 3. 构建 Router
    plugins := s.listProjectRetrieverPlugins(projectID)
    var retrievers []retrieval.Retriever
    for _, plugin := range plugins {
        r, err := s.registry.Create(plugin.Name, plugin.Config)
        if err != nil {
            logger.Errorf("创建检索插件 %s 失败: %v", plugin.Name, err)
            continue
        }
        retrievers = append(retrievers, r)
    }
    if len(retrievers) == 0 {
        return retrieval.NewRouter(retrieval.NewKeywordRetriever())
    }
    return retrieval.NewRouter(retrievers...)
}
```

**变更 4：前端新增"检索配置"页面**

在项目设置中新增"检索配置"Tab：
- 表格展示已注册的检索插件列表（名称、描述、状态、排序）。
- 支持开关插件（`enabled` 切换）。
- 支持拖拽排序调整插件执行顺序。
- 支持编辑插件配置（`config` JSON 编辑器）。
- 内置插件不可删除，仅可开关和配置。
- 显示每个插件的检索来源说明。

#### 4.3.3 API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/projects/:id/retriever-plugins` | 获取项目检索插件列表 |
| PUT | `/projects/:id/retriever-plugins/:pluginId` | 编辑插件配置（config、enabled、sortOrder） |
| PATCH | `/projects/:id/retriever-plugins/:pluginId/toggle` | 开关插件 |
| PUT | `/projects/:id/retriever-plugins/sort` | 批量调整插件排序 |
| POST | `/projects/:id/retriever-plugins/:pluginId/test` | 测试插件连通性 |

#### 4.3.4 前端交互

1. **项目设置页**：新增"检索配置"Tab。
2. **插件列表**：表格展示，列包含名称、描述、状态开关、排序、操作。
3. **排序调整**：拖拽行调整顺序，或输入 sortOrder 数值。
4. **配置编辑**：点击"配置"按钮，弹出 JSON 编辑器模态框。
5. **连通性测试**：点击"测试"按钮，验证插件配置是否正确。

#### 4.3.5 验收标准

1. 项目设置中可查看和管理检索插件（开关、排序、配置）。
2. AI 分析时，根据项目配置动态构建检索 Router，只使用已启用的插件。
3. 插件按 `sortOrder` 顺序执行，结果由 Router RRF 融合排序。
4. 修改项目检索配置后，后续分析任务立即生效，无需重启服务。
5. 内置插件不可删除，自定义插件可删除。
6. 插件连通性测试 API 可验证配置正确性。

---

## 5. 数据模型变更

### 新增 `RetrieverPlugin` 模型

如上 FR-3 变更 1 所述。

### 数据库迁移

```sql
CREATE TABLE retriever_plugins (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    project_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    description TEXT,
    config TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,
    is_built_in BOOLEAN DEFAULT FALSE,
    created_by BIGINT UNSIGNED,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_project_id (project_id),
    UNIQUE INDEX idx_project_name (project_id, name)
);
```

### 种子数据

每个项目创建时，自动插入三个内置插件记录（keyword、rag、requirement），其中 `keyword` 默认启用，`rag` 和 `requirement` 默认禁用（需要配置后才能启用）。

---

## 6. 迭代计划

> 节奏建议：每迭代 2 周，总计 2 个迭代（4 周）。
> 优先顺序：SSE 流式推送 + 思考过程可视化 > 检索层插件化。

### Iteration 5.6.1（P0）- SSE 流式推送 + 思考过程可视化

目标：将分析接口从轮询改为 SSE 流式推送，前端实时展示 AI 思考过程。

必须完成：
1. 扩展 `StreamEvent` 结构，增加 `thinking`/`tool_call`/`tool_result` 事件类型。
2. 改造 `convertEvent` 函数，识别 ADK 工具调用事件并转换。
3. 改造 `StreamToSSE`，输出 `event:` + `data:` 行。
4. 改造 `PerformAnalysisStream`，流结束后保存报告、更新状态、记录 Token。
5. 前端新增 `useAnalysisStream` Hook，消费 SSE 事件流。
6. 前端新增 `ThinkingProcess` 组件，实时展示思考步骤。
7. 前端 `DefectAnalysisPanel` 集成 `ThinkingProcess`，替换 Spinner。
8. 删除 `useDefectActions` 中的轮询逻辑。

交付物：
1. 分析过程实时展示思考步骤、工具调用、中间结论。
2. 分析接口完全由 SSE 驱动，无轮询。
3. 分析完成后报告自动保存，状态自动更新。

### Iteration 5.6.2（P1）- 检索层插件化

目标：检索层抽象为可插拔插件架构，支持项目级配置。

必须完成：
1. `RetrieverPlugin` 模型及数据库迁移。
2. `RetrieverPluginRegistry` 实现，注册内置插件 Factory。
3. `ADKAnalysisService` 改为从项目配置动态构建 Router。
4. 检索插件 CRUD API（列表、编辑、开关、排序、测试）。
5. 前端项目设置新增"检索配置"Tab。
6. 项目创建时自动插入内置插件种子数据。

交付物：
1. 项目设置中可管理检索插件（开关、排序、配置）。
2. AI 分析时根据项目配置动态构建检索策略。
3. 新增检索插件只需实现 `Retriever` 接口 + 注册 Factory，无需修改分析逻辑。

---

## 7. 里程碑与成功指标

### 里程碑

1. M1（第 2 周）：SSE 流式推送 + 思考过程可视化完成。
2. M2（第 4 周）：检索层插件化完成。

### 成功指标

1. 分析过程可视化率：100% 的分析任务在前端展示思考步骤。
2. SSE 推送延迟：P99 < 500ms（与 v5.5 的 SSE 通知推送一致）。
3. 轮询消除率：分析流程 0 次 HTTP 轮询请求。
4. 检索插件配置生效延迟：修改后 < 5s 生效（缓存 TTL 控制）。
5. 检索插件扩展性：新增一个检索插件只需实现 `Retriever` 接口 + 注册 Factory，无需修改 `ADKAnalysisService`。

---

## 8. 风险与对策

1. **风险：SSE 流式分析期间客户端断连**
   - 对策：后端检测连接断开，回退到异步模式（继续分析，保存报告，通过 SSE 通知推送结果）。
   - 降级：前端检测到断连后，回退到轮询模式（兼容旧逻辑保留）。

2. **风险：ADK session.Event 中工具调用事件的识别可能不完整**
   - 对策：先实现 `FunctionCall`/`FunctionResponse` 的识别，对于无法识别的 Part 类型，降级为 `thinking` 事件。
   - 兜底：如果 `convertEvent` 无法识别工具调用，至少保证文本推理步骤正确展示。

3. **风险：检索插件动态创建可能引入性能问题**
   - 对策：Retriever 实例按项目缓存，相同配置复用；缓存 TTL 5 分钟。
   - 超时保护：单个检索插件超时 30s，超时后跳过该插件。

4. **风险：RAG/需求检索插件依赖外部服务，可用性不确定**
   - 对策：插件测试连通性 API 提前验证；分析时插件失败不影响其他插件（Router 已有容错）。
   - 降级：所有插件失败时，回退到 `KeywordRetriever`。

5. **风险：前端 fetch + ReadableStream 消费 SSE 的兼容性**
   - 对策：使用 `fetch` API 的 `ReadableStream`，所有现代浏览器均支持；不使用 `EventSource`（因为需要 POST 请求体）。
   - 降级：如浏览器不支持 `ReadableStream`，回退到异步触发 + 轮询模式。

---

## 9. v5.6 最终优先级结论

如果资源不足，按以下顺序确保收益最大化：

1. **必须先做**：`FR-1 思考过程可视化` + `FR-2 SSE 流式推送` — 这是用户体验的核心提升，不做则 AI 分析过程始终是黑盒。
2. **第二优先**：`FR-3 检索层插件化` — 架构扩展性提升，有则加分，无则不影响基本功能。

这条顺序保证：先把用户体验打透（思考可见 + 实时推送），再提升架构扩展性（检索可配置）。
