# BugAgent v5.5 设计文档

> Version: v5.5  
> Date: 2026-05-06  
> Baseline: v5.4  
> 对应 PRD: PRD-v5.5-status-chain-sse-token-isolation-agent.md

---

## 1. 总体架构变更

v5.5 涉及 5 个 FR，变更范围：

| FR | 变更层 | 影响模块 |
|---|---|---|
| FR-1 状态链路 | model + handler + service + frontend | workflow.go, defect.go, DefectDetail.tsx |
| FR-2 SSE | 删除 ws/，新增 sse/ | ws/*, router.go, wsManager.ts |
| FR-3 Token统计 | model + handler + service + migration | models.go, 新增 AITokenUsage, analysis.go, fix_engine.go |
| FR-4 仓库隔离 | git + service + model | repo.go, fix_engine.go, 新增 DefectRepo |
| FR-5 Agent能力 | model + handler + service + adk | 新增 ProjectMCPServer/ProjectAgentSkill, mcp_integration.go |

---

## 2. FR-1 状态链路优化

### 2.1 状态机变更

文件：`server/internal/model/workflow.go`

```go
var DefectTransitionMatrix = map[string]map[string]bool{
    // ... 保留现有 ...
    DefectStatusReopened: {
        DefectStatusPendingAnalysis: true,  // 新增
        DefectStatusAnalyzing:       true,
        DefectStatusPendingFix:      true,
        DefectStatusRejected:        true,
    },
    DefectStatusPendingFix: {
        DefectStatusPendingAnalysis: true,  // 新增
        DefectStatusFixing:          true,
        DefectStatusManualFixing:    true,
        DefectStatusRejected:        true,
        DefectStatusSuspended:       true,
    },
    DefectStatusRejected: {
        DefectStatusReopened:        true,
        DefectStatusPendingAnalysis: true,  // 新增
    },
}
```

### 2.2 新增 API

**ReopenDefect**：`POST /defects/:id/reopen`

```go
type ReopenRequest struct {
    TargetStatus string `json:"targetStatus" binding:"required"` // pending_analysis / analyzing / pending_fix
    Comment      string `json:"comment"`
}
```

Handler 逻辑：
1. 查找缺陷，校验当前状态为 `rejected` 或 `fixed` 或 `completed` 或 `suspended`。
2. 调用 `IsValidDefectTransition(current, req.TargetStatus)` 校验。
3. 乐观锁更新状态。
4. 写 `StatusChange`，comment 标注 `reopen_to:{targetStatus}`。
5. 如果 targetStatus 为 `pending_analysis`，将已有 `AnalysisReport` 标记为 `superseded`（新增状态值）。

**ReanalyzeDefect**：`POST /defects/:id/reanalyze`

快捷操作，等价于 `ChangeStatus(pending_fix → pending_analysis)`，但额外：
1. 校验当前状态必须为 `pending_fix`。
2. 将已有 `AnalysisReport` 标记为 `superseded`。
3. 写 `StatusChange`，comment 标注 `reanalyze`。

### 2.3 AnalysisReport 新增状态

文件：`server/internal/model/models.go`

`AnalysisReport.Status` 枚举新增 `superseded`：

```go
const (
    AnalysisStatusPending   = "pending"
    AnalysisStatusCompleted = "completed"
    AnalysisStatusFailed    = "failed"
    AnalysisStatusSuperseded = "superseded"  // 新增：被重新分析取代
)
```

### 2.4 路由注册

文件：`server/internal/router/router.go`

```go
defects.POST("/:id/reopen", middleware.RequirePermission("defect:edit"), defectHandler.ReopenDefect)
defects.POST("/:id/reanalyze", middleware.RequirePermission("defect:edit"), defectHandler.ReanalyzeDefect)
```

---

## 3. FR-2 SSE 替换 WebSocket

### 3.1 删除 ws/ 包

删除文件：
- `server/internal/ws/hub.go`
- `server/internal/ws/client.go`
- `server/internal/ws/notify.go`
- `server/internal/ws/hub_test.go`
- `server/internal/middleware/websocket.go`（WSAuthMiddleware）
- `web/src/hooks/wsManager.ts`
- `web/src/hooks/useWebSocket.ts`

### 3.2 新增 sse/ 包

```
server/internal/sse/
├── broker.go      # Broker: 管理订阅和事件分发
├── handler.go     # Gin handler: SSE 连接处理
└── notify.go      # NotifyService: 业务层桥接
```

#### 3.2.1 Broker

```go
type Broker struct {
    subscribers map[string]map[chan SSEEvent]bool  // room → set of channels
    mu          sync.RWMutex
}

type SSEEvent struct {
    Event string      `json:"event"`
    Data  interface{} `json:"data"`
}

func NewBroker() *Broker
func (b *Broker) Subscribe(rooms []string) chan SSEEvent
func (b *Broker) Unsubscribe(ch chan SSEEvent)
func (b *Broker) Publish(room string, event SSEEvent)
func (b *Broker) PublishGlobal(event SSEEvent)
```

- `Subscribe`：创建 buffered channel（256），注册到指定 rooms。
- `Unsubscribe`：从所有 rooms 移除 channel，关闭 channel。
- `Publish`：向 room 内所有 channel 非阻塞写入，满则踢出。
- `PublishGlobal`：向所有订阅者推送。

#### 3.2.2 Handler

```go
type SSEHandler struct {
    broker *Broker
    jwtKey string
}

func (h *SSEHandler) HandleSSE(c *gin.Context)
```

流程：
1. 从 query `token` 解析 JWT，验证有效性，提取 userID。
2. 从 query `rooms` 解析房间列表（逗号分隔）。
3. 调用 `broker.Subscribe(rooms)` 获取 event channel。
4. 设置 SSE headers：`Content-Type: text/event-stream`、`Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`。
5. 启动 keepalive goroutine（30s 间隔发送 `:keepalive\n\n`）。
6. 主循环：从 channel 读取事件，格式化为 SSE 写入 `c.Writer`，`Flusher.Flush()`。
7. `c.Request.Context().Done()` 时，取消订阅，停止 keepalive。

#### 3.2.3 NotifyService

```go
type NotifyService struct {
    broker *Broker
}

func (s *NotifyService) NotifyDefectStatusChanged(defectID uint, fromStatus, toStatus string)
func (s *NotifyService) NotifyAnalysisProgress(defectID uint, progress float64, message string)
func (s *NotifyService) NotifyAnalysisCompleted(defectID uint, reportCode string)
func (s *NotifyService) NotifyFixTaskProgress(defectID uint, taskCode string, progress float64)
func (s *NotifyService) NotifyFixTaskCompleted(defectID uint, taskCode string)
func (s *NotifyService) NotifyCommentAdded(defectID uint, commentID uint)
```

每个方法调用 `broker.Publish("defect:{defectID}", SSEEvent{...})`。

### 3.3 路由变更

```go
// 删除
authed.GET("/ws", wsHandler.HandleWebSocket)

// 新增（在 authed 组外，因为 token 通过 query 传递）
public.GET("/sse", sseHandler.HandleSSE)
```

### 3.4 前端 SSE Manager

文件：`web/src/hooks/sseManager.ts`

```typescript
class SSEManager {
    private es: EventSource | null = null;
    private handlers = new Map<string, Set<EventHandler>>();
    private connected = false;
    private connectionListeners = new Set<(connected: boolean) => void>();

    connect(token: string, rooms: string[]): void
    disconnect(): void
    on(event: string, handler: EventHandler): void
    off(event: string, handler: EventHandler): void
    onConnectionChange(listener: (connected: boolean) => void): void
}
export const sseManager = new SSEManager();
```

文件：`web/src/hooks/useSSE.ts`

```typescript
export function useSSE(rooms: string[]): { connected: boolean }
```

### 3.5 事件类型映射

| 原 WS EventType | SSE event 名 | 不变 |
|---|---|---|
| `defect:status_changed` | `defect:status_changed` | ✓ |
| `analysis:progress` | `analysis:progress` | ✓ |
| `analysis:completed` | `analysis:completed` | ✓ |
| `analysis:failed` | `analysis:failed` | ✓ |
| `fix_task:progress` | `fix_task:progress` | ✓ |
| `fix_task:completed` | `fix_task:completed` | ✓ |
| `comment:added` | `comment:added` | ✓ |
| `notification` | `notification` | ✓ |

事件格式不变，仅传输层从 WebSocket 改为 SSE。

---

## 4. FR-3 Token 统计

### 4.1 新增 AITokenUsage 模型

文件：`server/internal/model/models.go`

```go
type AITokenUsage struct {
    ID               uint    `gorm:"primaryKey" json:"id"`
    ProjectID        uint    `gorm:"index:idx_project_type;not null" json:"projectId"`
    IterationID      *uint   `gorm:"index:idx_iteration_type" json:"iterationId"`
    DefectID         uint    `gorm:"index:idx_defect_type;not null" json:"defectId"`
    ConsumptionType  string  `gorm:"size:20;not null;index:idx_project_type;index:idx_iteration_type;index:idx_defect_type" json:"consumptionType"`
    SourceID         uint    `gorm:"index;not null" json:"sourceId"`
    AttemptIndex     int     `gorm:"default:0" json:"attemptIndex"`
    IsFinalAttempt   bool    `gorm:"default:false" json:"isFinalAttempt"`
    Provider         string  `gorm:"size:50" json:"provider"`
    ModelName        string  `gorm:"size:100" json:"modelName"`
    PromptTokens     int     `json:"promptTokens"`
    CompletionTokens int     `json:"completionTokens"`
    TotalTokens      int     `json:"totalTokens"`
    EstimatedCostUSD float64 `json:"estimatedCostUsd"`
    DurationMs       int64   `json:"durationMs"`
    CreatedAt        int64   `gorm:"index" json:"createdAt"`
}

func (AITokenUsage) TableName() string { return "ai_token_usages" }
```

### 4.2 删除旧 Token 字段

**AnalysisReport 删除字段**：
`PromptTokens`、`CompletionTokens`、`TotalTokens`、`EstimatedCostUSD`、`DurationMs`、`Provider`、`ModelName`、`PromptVersion`、`FallbackUsed`

**FixTask 删除字段**：
`AIPromptTokens`、`AICompletionTokens`、`AITotalTokens`、`AIEstimatedCostUSD`、`AIDurationMs`、`AIProvider`、`AIModelName`、`AIPromptVersion`、`AIFallbackUsed`、`AILastError`

### 4.3 写入逻辑

#### 分析完成时

文件：`server/internal/adk/analysis_service.go`

在 `PerformAnalysis` 和 `PerformAnalysisStream` 完成后，写入 `AITokenUsage`：

```go
func (s *ADKAnalysisService) recordTokenUsage(ctx context.Context, defect model.Defect, report *model.AnalysisReport) {
    usage := model.AITokenUsage{
        ProjectID:        defect.ProjectID,
        IterationID:      &defect.IterationID,
        DefectID:         defect.ID,
        ConsumptionType:  "analysis",
        SourceID:         report.ID,
        Provider:         report.Provider,
        ModelName:        report.ModelName,
        PromptTokens:     report.PromptTokens,
        CompletionTokens: report.CompletionTokens,
        TotalTokens:      report.TotalTokens,
        EstimatedCostUSD: report.EstimatedCostUSD,
        DurationMs:       report.DurationMs,
        AttemptIndex:     0,
        IsFinalAttempt:   true,
        CreatedAt:        time.Now().Unix(),
    }
    s.db.Create(&usage)
}
```

注意：写入在旧字段删除前同时进行，迁移后旧字段删除，写入逻辑只写 `AITokenUsage`。

#### 修复完成时

文件：`server/internal/service/fix_engine.go`

在 `executeFixWorkflow` 完成后，写入 `AITokenUsage`：

```go
func (s *FixService) recordTokenUsage(defect model.Defect, fixTask *model.FixTask, attemptIndex int, isFinal bool) {
    usage := model.AITokenUsage{
        ProjectID:        defect.ProjectID,
        IterationID:      &defect.IterationID,
        DefectID:         defect.ID,
        ConsumptionType:  "fix",
        SourceID:         fixTask.ID,
        Provider:         fixTask.AIProvider,
        ModelName:        fixTask.AIModelName,
        PromptTokens:     fixTask.AIPromptTokens,
        CompletionTokens: fixTask.AICompletionTokens,
        TotalTokens:      fixTask.AITotalTokens,
        EstimatedCostUSD: fixTask.AIEstimatedCostUSD,
        DurationMs:       fixTask.AIDurationMs,
        AttemptIndex:     attemptIndex,
        IsFinalAttempt:   isFinal,
        CreatedAt:        time.Now().Unix(),
    }
    s.db.Create(&usage)
}
```

Fallback 场景：每次尝试都调用 `recordTokenUsage`，`attemptIndex` 递增。

### 4.4 汇总 API

文件：`server/internal/handler/token_usage.go`（新增）

```go
type TokenUsageHandler struct {
    db *gorm.DB
}

func (h *TokenUsageHandler) GetDefectTokenUsage(c *gin.Context)
func (h *TokenUsageHandler) GetDefectTokenUsageDetails(c *gin.Context)
func (h *TokenUsageHandler) GetIterationTokenUsage(c *gin.Context)
func (h *TokenUsageHandler) GetProjectTokenUsage(c *gin.Context)
func (h *TokenUsageHandler) GetProjectTokenUsageByIteration(c *gin.Context)
func (h *TokenUsageHandler) GetProjectTokenUsageByDefect(c *gin.Context)
```

### 4.5 数据库迁移

文件：`server/migrations/v55_token_usage.sql`

```sql
-- 1. 创建 ai_token_usages 表
CREATE TABLE ai_token_usages (...);

-- 2. 回填 AnalysisReport 数据
INSERT INTO ai_token_usages (project_id, iteration_id, defect_id, consumption_type, source_id, ...)
SELECT d.iteration_id -> project_id, d.iteration_id, ar.defect_id, 'analysis', ar.id, ...
FROM analysis_reports ar JOIN defects d ON d.id = ar.defect_id;

-- 3. 回填 FixTask 数据
INSERT INTO ai_token_usages (project_id, iteration_id, defect_id, consumption_type, source_id, ...)
SELECT d.iteration_id -> project_id, d.iteration_id, ft.defect_id, 'fix', ft.id, ...
FROM fix_tasks ft JOIN defects d ON d.id = ft.defect_id;

-- 4. 删除旧字段
ALTER TABLE analysis_reports DROP COLUMN prompt_tokens, ...;
ALTER TABLE fix_tasks DROP COLUMN ai_prompt_tokens, ...;
```

---

## 5. FR-4 仓库隔离

### 5.1 新增 DefectRepo 模型

文件：`server/internal/model/models.go`

```go
type DefectRepo struct {
    ID        uint       `gorm:"primaryKey" json:"id"`
    DefectID  uint       `gorm:"index;not null" json:"defectId"`
    ProjectID uint       `gorm:"index;not null" json:"projectId"`
    RepoURL   string     `gorm:"size:500;not null" json:"repoUrl"`
    Branch    string     `gorm:"size:100" json:"branch"`
    LocalPath string     `gorm:"size:500;not null" json:"localPath"`
    Status    string     `gorm:"size:20;not null;default:'active'" json:"status"`
    FixTaskID *uint      `gorm:"index" json:"fixTaskId"`
    CreatedAt time.Time  `json:"createdAt"`
    DeletedAt *time.Time `json:"deletedAt"`
}

func (DefectRepo) TableName() string { return "defect_repos" }
```

### 5.2 仓库目录结构

```
{baseDir}/defects/{defectID}/{repoHash}/
```

- `baseDir`：从配置读取，默认 `/data/bug-agent/repos`
- `repoHash`：`fmt.Sprintf("%x", sha256.Sum256([]byte(repoURL)))[:8]`

### 5.3 克隆逻辑变更

文件：`server/internal/service/fix_engine.go`

`cloneRepository` 方法改为：

```go
func (s *FixService) cloneRepository(ctx context.Context, defect model.Defect, ...) (*git.Repository, ...) {
    // ... 现有逻辑：解析仓库URL、认证、分支 ...

    // 新增：按缺陷隔离目录
    repoHash := fmt.Sprintf("%x", sha256.Sum256([]byte(projectRepo.RepoURL)))[:8]
    defectDir := filepath.Join(config.RepoBaseDir(), "defects", strconv.Itoa(int(defect.ID)), repoHash)
    os.MkdirAll(defectDir, 0755)

    // 使用缺陷隔离目录替代 MkdirTemp
    repo, err := git.CloneToDir(ctx, defectDir, git.CloneOptions{...})

    // 写入 DefectRepo 记录
    defectRepo := &model.DefectRepo{
        DefectID:  defect.ID,
        ProjectID: iteration.ProjectID,
        RepoURL:   projectRepo.RepoURL,
        Branch:    targetBranch,
        LocalPath: defectDir,
        Status:    "active",
    }
    s.db.Create(defectRepo)

    return repo, &projectRepo, repoAuth, iterationBranch, nil
}
```

### 5.4 修复完成后清理

在 `executeFixWorkflow` 的 defer 中：

```go
defer func() {
    if defectRepo != nil {
        os.RemoveAll(defectRepo.LocalPath)
        s.db.Model(defectRepo).Updates(map[string]interface{}{
            "status":     "deleted",
            "deleted_at": time.Now(),
        })
    }
}()
```

### 5.5 定时清理任务

文件：`server/internal/service/repo_cleanup.go`（新增）

```go
type RepoCleanupService struct {
    db *gorm.DB
}

func (s *RepoCleanupService) CleanOrphanedRepos(ctx context.Context) (int, error) {
    // 查找 status=active 且 created_at < now-24h 的 DefectRepo
    // 逐个 os.RemoveAll + 更新状态
}
```

通过 `asyncx.Go` 启动定时任务，每小时执行一次。

### 5.6 git 包变更

文件：`server/internal/git/repo.go`

新增 `CloneToDir` 函数：

```go
func CloneToDir(ctx context.Context, dir string, opts CloneOptions) (*Repository, error) {
    // 与 NewRepository 相同逻辑，但使用指定目录而非 MkdirTemp
}
```

### 5.7 API

文件：`server/internal/handler/repo.go`（新增）

```go
type RepoHandler struct {
    db *gorm.DB
}

func (h *RepoHandler) ListDefectRepos(c *gin.Context)
func (h *RepoHandler) DeleteDefectRepo(c *gin.Context)
func (h *RepoHandler) ListOrphanedRepos(c *gin.Context)
func (h *RepoHandler) TriggerCleanup(c *gin.Context)
```

---

## 6. FR-5 Agent 能力一体化

### 6.1 新增模型

文件：`server/internal/model/models.go`

```go
type ProjectMCPServer struct {
    ID          uint      `gorm:"primaryKey" json:"id"`
    ProjectID   uint      `gorm:"index;not null" json:"projectId"`
    Name        string    `gorm:"size:100;not null" json:"name"`
    Command     string    `gorm:"size:500;not null" json:"command"`
    Args        string    `gorm:"type:text" json:"args"`
    Description string    `gorm:"type:text" json:"description"`
    Enabled     bool      `gorm:"default:true" json:"enabled"`
    CreatedBy   uint      `json:"createdBy"`
    CreatedAt   time.Time `json:"createdAt"`
    UpdatedAt   time.Time `json:"updatedAt"`
}

func (ProjectMCPServer) TableName() string { return "project_mcp_servers" }

type ProjectAgentSkill struct {
    ID               uint      `gorm:"primaryKey" json:"id"`
    ProjectID        uint      `gorm:"index;not null" json:"projectId"`
    Name             string    `gorm:"size:100;not null" json:"name"`
    AgentType        string    `gorm:"size:20;not null" json:"agentType"`
    Instruction      string    `gorm:"type:text" json:"instruction"`
    Tools            string    `gorm:"type:text" json:"tools"`
    MCPServerIDs     string    `gorm:"type:text;column:mcp_server_ids" json:"mcpServerIds"`
    MemoryCategories string    `gorm:"type:text" json:"memoryCategories"`
    Enabled          bool      `gorm:"default:true" json:"enabled"`
    IsDefault        bool      `gorm:"default:false" json:"isDefault"`
    CreatedBy        uint      `json:"createdBy"`
    CreatedAt        time.Time `json:"createdAt"`
    UpdatedAt        time.Time `json:"updatedAt"`
}

func (ProjectAgentSkill) TableName() string { return "project_agent_skills" }
```

### 6.2 MCP 服务管理

文件：`server/internal/handler/mcp_server.go`（新增）

```go
type MCPServerHandler struct {
    db *gorm.DB
}

func (h *MCPServerHandler) List(c *gin.Context)
func (h *MCPServerHandler) Create(c *gin.Context)
func (h *MCPServerHandler) Update(c *gin.Context)
func (h *MCPServerHandler) Delete(c *gin.Context)
func (h *MCPServerHandler) Toggle(c *gin.Context)
func (h *MCPServerHandler) TestConnection(c *gin.Context)
```

### 6.3 技能管理

文件：`server/internal/handler/skill.go`（新增）

```go
type SkillHandler struct {
    db *gorm.DB
}

func (h *SkillHandler) List(c *gin.Context)
func (h *SkillHandler) Create(c *gin.Context)
func (h *SkillHandler) Update(c *gin.Context)
func (h *SkillHandler) Delete(c *gin.Context)
func (h *SkillHandler) Toggle(c *gin.Context)
```

### 6.4 Agent 调度改造

文件：`server/internal/adk/analysis_service.go`

`PerformAnalysis` 改造：

```go
func (s *ADKAnalysisService) PerformAnalysis(ctx context.Context, req ADKAnalysisRequest) (*ADKAnalysisResult, error) {
    // 1. 读取项目技能配置
    var skills []model.ProjectAgentSkill
    s.db.Where("project_id = ? AND enabled = ?", defect.ProjectID, true).Find(&skills)

    // 2. 选择匹配技能（按 agentType 匹配，无匹配则用默认技能）
    matchedSkills := filterSkillsByType(skills, req.AgentTypes)

    // 3. 从技能配置构建 Agent
    for _, skill := range matchedSkills {
        // 解析 MCP 服务
        mcpServers := resolveMCPServers(s.db, skill.MCPServerIDs)
        // 解析记忆类别
        memoryCategories := parseMemoryCategories(skill.MemoryCategories)
        // 构建 Agent
        agent := buildAgentFromSkill(skill, mcpServers, memoryCategories)
    }

    // 4. 执行（后续流程不变）
}
```

### 6.5 路由注册

```go
// MCP 服务
mcpServers := projects.Group("/:id/mcp-servers")
mcpServers.GET("", ..., mcpServerHandler.List)
mcpServers.POST("", ..., mcpServerHandler.Create)
mcpServers.PUT("/:serverId", ..., mcpServerHandler.Update)
mcpServers.DELETE("/:serverId", ..., mcpServerHandler.Delete)
mcpServers.PATCH("/:serverId/toggle", ..., mcpServerHandler.Toggle)
mcpServers.POST("/:serverId/test", ..., mcpServerHandler.TestConnection)

// 技能
skills := projects.Group("/:id/skills")
skills.GET("", ..., skillHandler.List)
skills.POST("", ..., skillHandler.Create)
skills.PUT("/:skillId", ..., skillHandler.Update)
skills.DELETE("/:skillId", ..., skillHandler.Delete)
skills.PATCH("/:skillId/toggle", ..., skillHandler.Toggle)
```

---

## 7. 配置变更

文件：`server/internal/config/config.go`

新增：

```go
type Config struct {
    // ... existing ...
    Repo struct {
        BaseDir string `mapstructure:"base_dir"`
    } `mapstructure:"repo"`
}
```

默认值：`/data/bug-agent/repos`

---

## 8. 数据库迁移清单

| 序号 | 迁移文件 | 内容 |
|------|----------|------|
| 1 | `v55_01_defect_repos.sql` | 创建 `defect_repos` 表 |
| 2 | `v55_02_ai_token_usages.sql` | 创建 `ai_token_usages` 表，回填旧数据 |
| 3 | `v55_03_drop_old_token_fields.sql` | 删除 `analysis_reports` 和 `fix_tasks` 的 Token 字段 |
| 4 | `v55_04_project_mcp_servers.sql` | 创建 `project_mcp_servers` 表 |
| 5 | `v55_05_project_agent_skills.sql` | 创建 `project_agent_skills` 表，插入默认技能 |
| 6 | `v55_06_analysis_report_superseded.sql` | 更新 `analysis_reports.status` 枚举支持 `superseded` |
