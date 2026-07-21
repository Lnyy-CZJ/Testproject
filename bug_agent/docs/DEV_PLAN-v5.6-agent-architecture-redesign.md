# BugAgent v5.6 开发文档

> Version: v5.6  
> Date: 2026-05-08  
> 对应 PRD: PRD-v5.6-agent-architecture-redesign.md  
> 对应设计: DESIGN-v5.6-agent-architecture-redesign.md

---

## 1. 开发顺序

按依赖关系排序：

```
Phase 1 (P0): ToolRegistry → PlannerAgent → Executor → 集成测试
Phase 2 (P1): AgentScheduler → CancellationToken → 集成测试
Phase 3 (P2): RolloutRecorder → SafetyGate → 集成测试
```

---

## 2. Phase 1: ToolRegistry + PlannerAgent + Executor

### 2.1 ToolRegistry

**文件**: `server/internal/adk/tool_registry.go`

```go
package adk

type ToolFactory func(ExplorerContext) (tool.Tool, error)

type ToolRegistry struct {
    mu       sync.RWMutex
    builtin  map[string]ToolFactory
    plugins  map[string]ToolFactory
    cache    map[string][]tool.Tool
}

func NewToolRegistry() *ToolRegistry

func (r *ToolRegistry) Register(name string, factory ToolFactory)

func (r *ToolRegistry) Resolve(agentType string, expCtx ExplorerContext) []tool.Tool

func (r *ToolRegistry) InvalidateCache()
```

**内置工具注册**：

| name | factory | 适用 agentType |
|------|---------|---------------|
| search_code | NewSearchCodeToolAdapted | explorer, planner |
| read_file | NewReadFileToolAdapted | explorer, planner, analysis |
| find_api_handler | NewFindAPIHandlerToolAdapted | explorer, planner |
| list_directory | NewListDirectoryToolAdapted | explorer, planner |
| trace_call | NewTraceCallToolAdapted | explorer, planner |

**Resolve 逻辑**：
1. 检查缓存 key = `{agentType}:{expCtx 非nil字段hash}`
2. 缓存命中 → 返回
3. 缓存未命中 → 按 agentType 筛选 builtin + plugins → 逐个 factory(expCtx) → 缓存结果

**与 Retriever Plugin 集成**：
- 从 DB 加载项目启用的 retriever_plugins
- keyword plugin → 已有 search_code（内置）
- rag plugin → 新增 RAGSearchTool（调用向量数据库）
- requirement plugin → 新增 RequirementSearchTool（调用需求文档检索）

### 2.2 PlannerAgent

**文件**: `server/internal/adk/planner_agent.go`

```go
type PlanStep struct {
    Goal     string                 `json:"goal"`
    Tool     string                 `json:"tool"`
    Args     map[string]interface{} `json:"args"`
}

type PlanOutput struct {
    Steps []PlanStep `json:"steps"`
}

func NewPlannerAgent(llm adkmodel.LLM, expCtx ExplorerContext) (*LlmAgent, error)
```

**System Prompt**：

```
分析缺陷描述，制定代码探索计划。只输出JSON。

工作流：
1. 从缺陷描述提取关键实体（API路径、组件名、错误信息）
2. 为每个实体制定搜索步骤
3. 规划阅读步骤（读取搜索结果中最相关的文件）

输出格式：
{"steps":[{"goal":"找到处理 /api/users 的后端handler","tool":"find_api_handler","args":{"apiPath":"/api/users","httpMethod":"GET"}},{"goal":"阅读handler代码","tool":"read_file","args":{"filePath":"server/internal/handler/user.go"}}]}

约束：
- 步骤不超过5步
- 每步只使用一个工具
- tool 只能是 search_code / read_file / find_api_handler / list_directory
- 优先搜索最可能出问题的模块
```

**与 Explorer 的区别**：
- Planner 不调用工具，只输出计划
- Executor 负责执行计划中的工具调用
- Planner 失败时 fallback 到预检索代码上下文

### 2.3 Executor

**文件**: `server/internal/adk/executor.go`

```go
type Executor struct {
    expCtx ExplorerContext
    tools  map[string]func(args map[string]interface{}) (string, error)
}

type ExecResult struct {
    Steps   []ExecStep
    Evidence string
    Files    []string
}

type ExecStep struct {
    Goal   string
    Tool   string
    Args   map[string]interface{}
    Result string
    Error  string
}

func NewExecutor(expCtx ExplorerContext) *Executor

func (e *Executor) Execute(ctx context.Context, plan PlanOutput) (*ExecResult, error)
```

**执行逻辑**：
1. 遍历 plan.Steps
2. 根据 step.Tool 调用对应的 ExplorerContext 函数
3. 收集结果到 ExecResult
4. 将所有步骤结果拼接为 Evidence 文本
5. 任何步骤失败 → 记录错误，继续执行后续步骤

**工具调用映射**：

| step.Tool | 调用函数 |
|-----------|---------|
| search_code | expCtx.SearchFn |
| read_file | expCtx.ReadFn |
| find_api_handler | expCtx.HandlerFn |
| list_directory | expCtx.ListFn |

### 2.4 集成到 AnalysisService

**修改文件**: `server/internal/adk/analysis_service.go`

**analyzeWithAgent 修改**：

```
当前流程:
  ExplorerContext → SequentialAgent(Explorer → Analysis)

新流程:
  ExplorerContext → PlannerAgent(输出计划)
                  → Executor(执行计划，收集证据)
                  → AnalysisAgent(基于证据分析)
```

**代码变更**：
1. 新增 `executePlannerPhase` 方法：创建 PlannerAgent，运行，解析 PlanOutput
2. 新增 `executePlanPhase` 方法：创建 Executor，执行计划，返回 ExecResult
3. 修改 `analyzeWithAgent`：替换 SequentialAgent 为 Planner → Executor → Analysis
4. 修改 `buildDefectSummary`：将 ExecResult.Evidence 追加到代码证据部分

---

## 3. Phase 2: AgentScheduler + CancellationToken

### 3.1 AgentScheduler

**文件**: `server/internal/adk/scheduler.go`

```go
type TaskPriority int

const (
    PriorityUser    TaskPriority = 0
    PriorityAuto    TaskPriority = 1
    PriorityBackground TaskPriority = 2
)

type AnalysisTask struct {
    ID         string
    DefectID   uint
    AgentTypes []string
    Priority   TaskPriority
    Ctx        context.Context
    Cancel     context.CancelFunc
    ResultCh   chan<- *AnalysisResult
    SubmittedAt time.Time
}

type AgentScheduler struct {
    queue    *PriorityQueue
    workers  semaphore.Weighted
    maxConc  int
    running  map[uint]string  // defectID → taskID (去重)
    mu       sync.Mutex
}

func NewAgentScheduler(maxConcurrency int) *AgentScheduler

func (s *AgentScheduler) Submit(task *AnalysisTask) error

func (s *AgentScheduler) Cancel(defectID uint) bool

func (s *AgentScheduler) QueueStatus() []TaskStatus

func (s *AgentScheduler) Start(ctx context.Context)

func (s *AgentScheduler) Stop()
```

**调度逻辑**：
1. `Submit` 将任务推入优先级堆，检查去重
2. `Start` 启动调度循环：从堆顶取任务 → 获取信号量 → 启动 goroutine 执行
3. 执行完成后释放信号量、从 running 中移除
4. `Cancel` 从 running 中找到任务，调用 Cancel()

**PriorityQueue**：

```go
type PriorityQueue struct {
    items []*AnalysisTask
}

func (pq *PriorityQueue) Len() int
func (pq *PriorityQueue) Less(i, j int) bool  // priority 升序，同优先级按提交时间升序
func (pq *PriorityQueue) Swap(i, j int)
func (pq *PriorityQueue) Push(x interface{})
func (pq *PriorityQueue) Pop() interface{}
```

### 3.2 CancellationToken 全链路

**修改文件**: `server/internal/adk/analysis_service.go`

**变更**：
1. `PerformAnalysisStream` 创建根 context.WithCancel
2. 传给 PlannerAgent、Executor、AnalysisAgent
3. Executor 每个步骤前检查 ctx.Done()
4. 新增 `CancelAnalysis` API：调用 scheduler.Cancel(defectID)

**Handler 变更**：

```go
// POST /defects/:id/analysis/cancel
func (h *AgentHandler) CancelAnalysis(c *gin.Context) {
    defectID := c.Param("id")
    if h.scheduler.Cancel(defectID) {
        c.JSON(200, gin.H{"message": "已取消"})
    } else {
        c.JSON(404, gin.H{"message": "未找到运行中的分析"})
    }
}
```

---

## 4. Phase 3: RolloutRecorder + SafetyGate

### 4.1 RolloutRecorder

**文件**: `server/internal/adk/rollout_recorder.go`

```go
type RolloutRecord struct {
    ID        uint      `gorm:"primaryKey"`
    SessionID string    `gorm:"uniqueIndex"`
    DefectID  uint      `gorm:"index"`
    Events    string    `gorm:"type:text"`  // JSON array of events
    Status    string    // running / completed / cancelled / failed
    CreatedAt time.Time
    UpdatedAt time.Time
}

type RolloutRecorder struct {
    db *gorm.DB
}

func (r *RolloutRecorder) Record(sessionID string, event *session.Event) error
func (r *RolloutRecorder) Resume(sessionID string) (*Runner, error)
func (r *RolloutRecorder) ListByDefect(defectID uint) ([]RolloutRecord, error)
```

**Migration**: `v5.6_rollout_records.sql`

### 4.2 SafetyGate

**文件**: `server/internal/adk/safety_gate.go`

```go
type SafetyDecision int

const (
    AutoApprove SafetyDecision = iota
    AskUser
    Reject
)

type SafetyGate struct {
    profile PermissionProfile
}

func (g *SafetyGate) Assess(toolCall ToolCall) SafetyDecision
```

---

## 5. 数据库迁移

### v5.6_analysis_tasks.sql

```sql
CREATE TABLE IF NOT EXISTS analysis_tasks (
    id BIGSERIAL PRIMARY KEY,
    defect_id BIGINT NOT NULL,
    task_id VARCHAR(100) NOT NULL,
    priority INT NOT NULL DEFAULT 1,
    agent_types TEXT[] NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_analysis_tasks_defect_id ON analysis_tasks (defect_id);
CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status ON analysis_tasks (status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_tasks_task_id ON analysis_tasks (task_id);
```

### v5.6_rollout_records.sql

```sql
CREATE TABLE IF NOT EXISTS rollout_records (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(200) NOT NULL,
    defect_id BIGINT NOT NULL,
    events TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rollout_records_session_id ON rollout_records (session_id);
CREATE INDEX IF NOT EXISTS idx_rollout_records_defect_id ON rollout_records (defect_id);
```

---

## 6. API 变更

| Method | Path | 说明 | 版本 |
|--------|------|------|------|
| POST | /defects/:id/analysis/cancel | 取消运行中的分析 | v5.6 |
| GET | /defects/:id/analysis/queue | 查询分析队列状态 | v5.6 |
| GET | /defects/:id/analysis/history | 查询分析历史 | v5.6 |

---

## 7. 文件清单

| 文件 | 操作 | Phase |
|------|------|-------|
| server/internal/adk/tool_registry.go | 新增 | 1 |
| server/internal/adk/planner_agent.go | 新增 | 1 |
| server/internal/adk/executor.go | 新增 | 1 |
| server/internal/adk/analysis_service.go | 修改 | 1 |
| server/internal/adk/agents.go | 修改 | 1 |
| server/internal/adk/scheduler.go | 新增 | 2 |
| server/internal/adk/safety_gate.go | 新增 | 3 |
| server/internal/adk/rollout_recorder.go | 新增 | 3 |
| server/internal/handler/agent.go | 修改 | 2 |
| server/internal/model/analysis_task.go | 新增 | 2 |
| server/internal/model/rollout_record.go | 新增 | 3 |
| server/migrations/v5.6_analysis_tasks.sql | 新增 | 2 |
| server/migrations/v5.6_rollout_records.sql | 新增 | 3 |
