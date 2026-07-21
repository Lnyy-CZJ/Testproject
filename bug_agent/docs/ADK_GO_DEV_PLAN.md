# BugAgent 基于 ADK-Go 开发计划

> 版本：v2.0（基于实际 SDK API 校准）  
> 日期：2026-05-04  
> SDK：`google.golang.org/adk` v0.3.0  
> Go：1.24.4+  
> 总工期：11 天（含并行压缩）

---

## 1. 架构总览

### 1.1 ADK-Go 核心包映射（v0.3.0 实际 API）

```
google.golang.org/adk/
├── agent/                    → Agent 生命周期
│   ├── agent.go              → Agent 接口 { Name/Description/Run/SubAgents }
│   │                         → agent.New(cfg) → Agent
│   │                         → agent.NewSingleLoader/NewMultiLoader
│   ├── llmagent/             → LLMAgent (ReAct 循环 + Tool-Use)
│   │                         → llmagent.New(cfg) → agent.Agent
│   │                         → BeforeModelCallback/AfterModelCallback
│   │                         → BeforeToolCallback/AfterToolCallback
│   │                         → InstructionProvider（动态指令）
│   └── workflowagents/
│       ├── sequentialagent/  → 顺序执行
│       ├── parallelagent/    → 并行执行
│       └── loopagent/        → 循环执行
├── tool/                     → 工具系统
│   ├── tool.go               → Tool 接口 { Name/Description/IsLongRunning/Run }
│   │                         → Toolset 接口 { Name/Tools }
│   ├── functiontool/         → 泛型函数工具
│   │                         → functiontool.New[TArgs, TResults](cfg, handler)
│   ├── mcptoolset/           → MCP Server → Toolset
│   │                         → mcptoolset.New(cfg) → tool.Toolset
│   ├── agenttool/            → Agent 作为 Tool
│   └── geminitool/           → 内置 GoogleSearch 等
├── model/                    → LLM 抽象
│   ├── llm.go                → LLM 接口 { GenerateContent/StreamGenerate }
│   │                         → LLMRequest/LLMResponse
│   └── gemini/               → Gemini 实现
│                             → gemini.NewModel(ctx, name, config)
├── session/                  → 会话管理
│   ├── service.go            → Service 接口 { Get/Create/Delete/List }
│   ├── session.go            → Session/Event/State
│   ├── inmemory.go           → InMemoryService()
│   └── database/             → ⭐ 内置 GORM 实现！
│                             → NewSessionService(dialector, opts...) → Service
│                             → AutoMigrate(service) → error
├── runner/                   → 执行器
│   └── runner.go             → Runner.Run(ctx, userID, sessionID, msg, ...) → iter.Seq2
├── artifact/                 → 附件管理
│   ├── service.go            → Service 接口
│   ├── inmemory.go           → 内存实现
│   └── gcs/                  → GCS 实现
└── memory/                   → 跨会话记忆
    ├── service.go            → Service 接口
    └── inmemory.go           → 内存实现
```

### 1.2 BugAgent → ADK-Go 组件映射

| BugAgent 现有组件 | ADK-Go 映射 | 新文件 | 备注 |
|---|---|---|---|
| `ai.AIClient` 接口 | `model.LLM` 接口 | `internal/adk/model_adapter.go` | 核心适配 |
| `ai.NewAIClient()` 工厂 | `NewLLM()` 工厂 | `internal/adk/model_factory.go` | 统一入口 |
| `ai.CodeExplorer` | `llmagent.New()` + Function Tools | `internal/adk/explorer_agent.go` | 消除手写循环 |
| `ai.BuildFrontendPrompt()` | `InstructionProvider` + Callback | `internal/adk/agents.go` | 动态指令 |
| `service.AnalysisService` | `runner.Runner` + `ParallelAgent` | `internal/adk/analysis_runner.go` | 并行分析 |
| `service.FixEngine` | `runner.Runner` + `SequentialAgent` | `internal/adk/fix_agent.go` | 修复流程 |
| `service.CollaborationService` | `ParallelAgent` | `internal/adk/collaboration_agent.go` | 协作 |
| `service.AgentMemoryService` | Callback + `memory.Service` | `internal/adk/memory_callbacks.go` | 记忆注入/提取 |
| 无 | `session/database.NewSessionService()` | 无需新文件 | ⭐ 内置 GORM |
| 无 | `mcptoolset.New()` | `internal/adk/mcp_integration.go` | MCP 集成 |

---

## 2. 任务分解

### Phase 1：基础设施（Day 1-2）

#### T1: model.LLM 适配器 [1.5d]

**目标**：将现有 `ai.AIClient` 包装为 ADK-Go 的 `model.LLM` 接口

**文件**：`server/internal/adk/model_adapter.go`

```go
package adk

import (
    "iter"
    "context"
    adkmodel "google.golang.org/adk/model"
)

type AIClientModel struct {
    client ai.AIClient
    model  string
}

func (m *AIClientModel) GenerateContent(ctx context.Context, req *adkmodel.LLMRequest) (*adkmodel.LLMResponse, error) {
    chatReq := m.convertRequest(req)
    resp, err := m.client.Chat(ctx, chatReq)
    if err != nil {
        return nil, err
    }
    return m.convertResponse(resp), nil
}

func (m *AIClientModel) StreamGenerate(ctx context.Context, req *adkmodel.LLMRequest) iter.Seq2[*adkmodel.LLMResponse, error] {
    return func(yield func(*adkmodel.LLMResponse, error) bool) {
        chatReq := m.convertRequest(req)
        ch := m.client.ChatStream(ctx, chatReq)
        for chunk := range ch {
            if chunk.Error != nil {
                if !yield(nil, chunk.Error) { return }
                break
            }
            resp := m.convertStreamChunk(chunk)
            if !yield(resp, nil) { return }
        }
    }
}
```

**关键转换**：
- `adkmodel.LLMRequest` → `ai.ChatRequest`（消息格式、温度、max_tokens）
- `ai.ChatResponse` → `adkmodel.LLMResponse`（内容、用量、function_call）
- `<-chan *ai.StreamChunk` → `iter.Seq2`（goroutine bridge，注意 context 取消传播）

**验收**：单元测试通过，`AIClientModel` 可被 `llmagent.New()` 使用

---

#### T2: model 工厂 + SessionService 初始化 [0.5d]

**目标**：统一创建 `model.LLM` 实例 + 初始化 SessionService

**文件**：`server/internal/adk/model_factory.go`、`server/internal/adk/init.go`

```go
// model_factory.go
func NewLLM(ctx context.Context, cfg *model.ProjectAIConfig) (adkmodel.LLM, error) {
    switch cfg.Provider {
    case "gemini":
        return gemini.NewModel(ctx, cfg.ModelName, &genai.ClientConfig{APIKey: cfg.APIKey})
    default:
        client, _ := ai.NewAIClient(cfg.Provider, cfg.APIKey, cfg.APIEndpoint, cfg.ModelName)
        return &AIClientModel{client: client, model: cfg.ModelName}, nil
    }
}

// init.go
func InitServices(db *gorm.DB) (session.Service, error) {
    sessionSvc, err := sessiondb.NewSessionService(db.Dialector, &gorm.Config{})
    if err != nil {
        return nil, err
    }
    if err := sessiondb.AutoMigrate(sessionSvc); err != nil {
        return nil, err
    }
    return sessionSvc, nil
}
```

**关键发现**：ADK-Go v0.3.0 已内置 `session/database.NewSessionService()`，直接复用，无需自写 GORM 实现。

**验收**：6 种 provider + Gemini 均可创建 model；SessionService CRUD 正常

---

### Phase 2：Agent 定义与工具（Day 3-5）

#### T3: 分析 Agent 定义 [1.5d]

**目标**：将 6 种 Agent 类型的 Prompt 和工具映射为 ADK-Go Agent

**文件**：`server/internal/adk/agents.go`

```go
func NewAnalysisAgent(agentType model.AgentType, llm adkmodel.LLM, tools []tool.Tool, memCtx string) (agent.Agent, error) {
    return llmagent.New(llmagent.Config{
        Name:        string(agentType) + "_analyzer",
        Model:       llm,
        Description: fmt.Sprintf("分析%s类型的缺陷", agentType),
        Instruction: buildInstruction(agentType, memCtx),
        Tools:       tools,
        BeforeModelCallbacks: []llmagent.BeforeModelCallback{
            MemoryInjectionCallback(memCtx),
        },
        AfterModelCallbacks: []llmagent.AfterModelCallback{
            StatusUpdateCallback(agentType),
        },
    })
}
```

**关键设计**：
- `Instruction` = 现有 `SystemPrompt` + 动态上下文
- 每个 agentType 创建独立 Agent 实例，各自配不同工具集
- 使用 `InstructionProvider` 替代静态 Instruction，支持动态注入 session state
- `client/product/test` 三种类型不再 fallback 到 frontend，各自有独立 Instruction

**验收**：6 种 Agent 类型均可创建并执行简单分析

---

#### T4: 内置 Function Tools [2d]

**目标**：将现有工具封装为 ADK-Go `functiontool`（泛型 API）

**文件**：`server/internal/adk/tools/`

| 文件 | 工具 | 映射来源 | 参数结构体 |
|------|------|----------|-----------|
| `code_search.go` | `search_code` | `explorer.go` search_code | `SearchCodeArgs` |
| `code_read.go` | `read_file` | `explorer.go` read_file | `ReadFileArgs` |
| `call_trace.go` | `trace_call` | `explorer.go` trace_call | `TraceCallArgs` |
| `api_mapper.go` | `find_api_handler` | `explorer.go` find_api_handler | `FindAPIArgs` |
| `git_ops.go` | `git_diff/log/blame` | 新增 | `GitOpsArgs` |
| `directory.go` | `list_directory` | 新增 | `ListDirArgs` |
| `symbol_search.go` | `search_symbols` | 新增 | `SymbolSearchArgs` |
| `test_run.go` | `run_test` | 新增（沙箱） | `RunTestArgs` |
| `db_query.go` | `db_query` | 新增（只读） | `DBQueryArgs` |

每个工具使用 ADK-Go 泛型 API：

```go
type SearchCodeArgs struct {
    Query string `json:"query" jsonschema:"description=语义搜索查询,required"`
}

type SearchCodeResult struct {
    Hits []retrieval.Hit `json:"hits"`
}

func NewSearchCodeTool(retriever retrieval.Retriever) (tool.Tool, error) {
    return functiontool.New(
        functiontool.Config[SearchCodeArgs, SearchCodeResult]{
            Name:        "search_code",
            Description: "语义搜索代码符号",
        },
        func(ctx tool.Context, args SearchCodeArgs) (SearchCodeResult, error) {
            hits, err := retriever.Retrieve(ctx, retrieval.Query{Text: args.Query})
            return SearchCodeResult{Hits: hits}, err
        },
    )
}
```

**验收**：每个工具可独立调用并返回正确结果

---

#### T5: Code Explorer Agent [1d]

**目标**：用 ADK-Go Agent + Tools 替代手写 tool-use 循环

**文件**：`server/internal/adk/explorer_agent.go`

```go
func NewExplorerAgent(llm adkmodel.LLM, expCtx ExplorerContext) (agent.Agent, error) {
    searchTool, _ := NewSearchCodeTool(expCtx.SearchFn)
    readTool, _ := NewCodeReadTool(expCtx.ReadFn)
    traceTool, _ := NewCallTraceTool(expCtx.TraceFn)
    apiTool, _ := NewAPIHandlerTool(expCtx.FindHandlerFn)

    return llmagent.New(llmagent.Config{
        Name:        "code_explorer",
        Model:       llm,
        Instruction: explorerSystemPrompt,
        Tools:       []tool.Tool{searchTool, readTool, traceTool, apiTool},
    })
}
```

**关键验证点**：
- ADK 内置 tool-use 循环行为与现有 8 轮循环一致
- Function Calling 格式在非 Gemini 模型上的兼容性
- 错误恢复行为（工具调用失败时 ADK 如何处理）

**验收**：Explorer Agent 可完成跨栈代码探索任务

---

### Phase 3：核心流程迁移（Day 6-8）

#### T6: 分析流程迁移 [2d]

**目标**：用 `ParallelAgent` + `SequentialAgent` 替代 `AnalysisService`

**文件**：`server/internal/adk/analysis_runner.go`

```go
func NewAnalysisPipeline(llm adkmodel.LLM, sessionSvc session.Service) (*runner.Runner, error) {
    explorer, _ := NewExplorerAgent(llm, expCtx)

    frontendAgent, _ := NewAnalysisAgent("frontend", llm, frontendTools, memCtx)
    backendAgent, _ := NewAnalysisAgent("backend", llm, backendTools, memCtx)
    testAgent, _ := NewAnalysisAgent("test", llm, testTools, memCtx)

    parallelAnalysis, _ := parallelagent.New(parallelagent.Config{
        Name:      "parallel_analysis",
        SubAgents: []agent.Agent{frontendAgent, backendAgent, testAgent},
    })

    pipeline, _ := sequentialagent.New(sequentialagent.Config{
        Name:      "analysis_pipeline",
        SubAgents: []agent.Agent{explorer, parallelAnalysis},
    })

    return runner.New(runner.Config{
        Agent:          pipeline,
        SessionService: sessionSvc,
    })
}
```

**关键适配**：
- `analyzeWithFallback` → 在 `model.LLM` 适配器中实现（尝试多个 provider）
- `normalizeAnalysisByRepoEvidence` → `LoopAgent`（分析→校验→修正）
- `publishAgentComment` → `AfterModelCallback`
- 缺陷状态机更新 → `AfterModelCallback` 中调用 `DefectService`

**验收**：创建缺陷 → 触发分析 → 并行多 Agent → 结果写入 DB + 评论

---

#### T7: 修复流程迁移 [1.5d]

**目标**：用 `SequentialAgent` + Git Tools 替代 `FixEngine`

**文件**：`server/internal/adk/fix_agent.go`

```go
func NewFixPipeline(llm adkmodel.LLM, sessionSvc session.Service) (*runner.Runner, error) {
    fixAgent, _ := llmagent.New(llmagent.Config{
        Name:        "fix_generator",
        Model:       llm,
        Instruction: fixSystemPrompt,
        Tools: []tool.Tool{
            gitCloneTool, gitBranchTool,
            fileReadTool, fileWriteTool,
            gitCommitTool, gitPushTool,
            createPRTool,
        },
    })

    return runner.New(runner.Config{
        Agent:          fixAgent,
        SessionService: sessionSvc,
    })
}
```

**关键适配**：
- 7 步工作流 → Agent 通过 Tool Calling 自主决定执行顺序（而非硬编码 7 步）
- `FixPlan` 进度 → `session.Event` 流式推送
- `CodeGenerator.ApplyChange` → `FileWriteTool`

**验收**：触发修复 → 克隆→生成→应用→提交→推送→创建 PR

---

#### T8: 协作流程迁移 [0.5d]

**目标**：用 `ParallelAgent` 替代 `CollaborationService`

**文件**：`server/internal/adk/collaboration_agent.go`

**验收**：多 Agent 并行分析 → 聚合结果 → 投票/共识

---

### Phase 4：集成与增强（Day 9-11）

#### T9: 记忆系统集成 [1d]

**目标**：用 Callback 机制替代 `AgentMemoryService` 的显式调用

**文件**：`server/internal/adk/memory_callbacks.go`

```go
func MemoryInjectionCallback(db *gorm.DB, projectID uint) llmagent.BeforeModelCallback {
    return func(ctx context.Context, ic *agent.CallbackContext, req *adkmodel.LLMRequest) (*adkmodel.LLMResponse, error) {
        memories := loadMemories(db, projectID)
        for _, mem := range memories {
            req.Contents = append(req.Contents, &genai.Content{
                Role: "user",
                Parts: []*genai.Part{{Text: fmt.Sprintf("[历史记忆] %s", mem.Content)}},
            })
        }
        return nil, nil
    }
}

func MemoryExtractionCallback(db *gorm.DB, projectID uint) llmagent.AfterModelCallback {
    return func(ctx context.Context, ic *agent.CallbackContext, resp *adkmodel.LLMResponse) (*adkmodel.LLMResponse, error) {
        extractAndSaveMemories(db, projectID, resp)
        return nil, nil
    }
}
```

**验收**：分析完成后自动提取记忆；下次分析自动注入记忆

---

#### T10: MCP 工具集成 [1d]

**目标**：集成 MCP Server，让 Agent 可调用外部工具

**文件**：`server/internal/adk/mcp_integration.go`

```go
func NewMCPToolset(serverCmd string, args ...string) (tool.Toolset, error) {
    return mcptoolset.New(mcptoolset.Config{
        Transport: &mcp.CommandTransport{
            Command: exec.Command(serverCmd, args...),
        },
    })
}

func NewExplorerAgentWithMCP(llm adkmodel.LLM, expCtx ExplorerContext, mcpServers []MCPServerConfig) (agent.Agent, error) {
    var toolsets []tool.Toolset
    for _, srv := range mcpServers {
        ts, _ := NewMCPToolset(srv.Command, srv.Args...)
        toolsets = append(toolsets, ts)
    }

    return llmagent.New(llmagent.Config{
        Name:        "code_explorer_mcp",
        Model:       llm,
        Instruction: explorerSystemPrompt,
        Tools:       builtinTools,
        Toolsets:    toolsets,
    })
}
```

**验收**：可连接至少 1 个 MCP Server 并调用其工具

---

#### T11: 流式输出 + WS 通知 [0.5d]

**目标**：将 ADK-Go 的 `iter.Seq2[Event, error]` 适配为 SSE + WS

**文件**：`server/internal/adk/stream_adapter.go`

```go
func StreamToSSE(events iter.Seq2[*session.Event, error], w http.ResponseWriter) {
    flusher := w.(http.Flusher)
    for event, err := range events {
        if err != nil { break }
        data, _ := json.Marshal(event)
        fmt.Fprintf(w, "data: %s\n\n", data)
        flusher.Flush()
    }
}

func StreamToWS(events iter.Seq2[*session.Event, error], hub *ws.Hub, userID string) {
    for event, err := range events {
        if err != nil { continue }
        hub.SendToUser(userID, ws.Message{Type: "agent_event", Data: event})
    }
}
```

**验收**：前端 SSE 连接后实时收到 Agent 推理 token；WS 通知正常

---

#### T12: Handler 层集成 + 端到端测试 [1.5d]

**目标**：将 ADK-Go Runner 集成到现有 Gin Handler

**文件**：修改 `server/internal/handler/agent.go`、`fix_task.go`

```go
func (h *AgentHandler) TriggerAnalysis(c *gin.Context) {
    llm, _ := adk.NewLLM(ctx, aiConfig)
    sessionSvc, _ := adk.InitServices(h.db)
    r, _ := adk.NewAnalysisPipeline(llm, sessionSvc)

    go func() {
        events := r.Run(ctx, userID, sessionID, userMsg)
        for event, err := range events {
            if err != nil { continue }
            processEvent(event)
        }
    }()

    c.JSON(200, gin.H{"status": "analyzing"})
}
```

**验收**：完整流程——创建缺陷 → 触发分析 → 流式推送 → 结果写入 → 修复 → 验证

---

## 3. 依赖关系与并行策略

```
Day 1-2:  T1(model adapter) ─── T2(model factory + session init)

Day 3-5:  T3(analysis agents) ─┬─ T4(function tools)
                                └─ T5(explorer agent)

Day 6-8:  T6(analysis runner) ──┬─ T7(fix agent)
                                 └─ T8(collaboration)

Day 9-11: T9(memory callbacks) ── T10(MCP integration) ── T11(stream + WS)
Day 11:   T12(handler integration + E2E test)
```

**并行机会**：
- T3/T4/T5 可部分并行（T3 依赖 T4 的工具定义接口，但可先 mock）
- T6/T7/T8 可并行
- T9/T10/T11 可并行

---

## 4. 与 v1.0 计划的关键差异

| 项 | v1.0 计划 | v2.0 计划（实际 API 校准） | 原因 |
|---|---|---|---|
| SDK 版本 | v0.2.0+ | v0.3.0 | pkg.go.dev 最新发布版 |
| GORM SessionService | 自写实现 [1.5d] | 直接用 `session/database.NewSessionService()` [0d] | SDK 内置 GORM 实现 |
| functiontool API | `map[string]any` 参数 | 泛型 `New[TArgs, TResults]` | SDK 实际 API |
| llmagent.New 返回值 | `*llmagent.LLMAgent` | `agent.Agent` | SDK 实际返回接口类型 |
| Callback 签名 | `func(ctx, InvocationContext) iter.Seq2` | `func(ctx, *CallbackContext, req/resp) (*Response, error)` | SDK 实际签名 |
| MCP 集成 | 仅提及 | 独立任务 T10 [1d] | 需要实际集成工作 |
| InstructionProvider | 未提及 | T3 中使用 | 支持动态指令注入 |
| 总工期 | 13 天 | 11 天 | T3 简化 + 并行优化 |

---

## 5. 风险与缓解

| # | 风险 | 缓解措施 |
|---|------|----------|
| R1 | ADK-Go v0.3.0 API 仍可能变更 | `go.mod` 锁定版本；封装 ADK 调用到 `internal/adk/` 包内，变更只影响适配层 |
| R2 | 非 Gemini 模型的 Function Calling 格式差异 | T1 适配器中处理 OpenAI/Anthropic 的 function_call 格式转换；优先用 Gemini 验证流程 |
| R3 | `iter.Seq2` 与现有 channel 模型不兼容 | T11 中用 goroutine bridge 适配；注意 context 取消传播和资源泄漏 |
| R4 | Explorer Agent tool-use 行为不一致 | T5 中先做原型验证，确认 ADK 内置循环与手写循环行为对齐 |
| R5 | functiontool 泛型约束与 JSON Schema 生成 | 验证 struct tag `jsonschema` 是否被 ADK 正确解析；必要时 fallback 到 `agent.New()` 自定义 |
| R6 | session/database 的 GORM 表结构与现有 DB 冲突 | AutoMigrate 前检查表是否存在；必要时用独立 schema |

---

## 6. 验收标准

| # | 验收项 | 标准 |
|---|--------|------|
| A1 | LLM 多厂商适配 | 6 种 provider + Gemini 均可通过 ADK-Go `model.LLM` 调用 |
| A2 | 并行分析 | 3 Agent 并行分析延迟 < 单 Agent × 1.3 |
| A3 | 流式输出 | SSE 首 token < 200ms；token 间隔 < 50ms |
| A4 | 修复流程 | 克隆→生成→应用→提交→PR 全流程可用 |
| A5 | 记忆系统 | 分析后自动提取记忆；下次分析自动注入 |
| A6 | MCP 工具 | 可连接至少 1 个 MCP Server 并调用其工具 |
| A7 | 回归测试 | 现有测试用例全部仍通过 |
| A8 | WS 通知 | 分析/修复全路径状态变更均通过 WS 推送 |
