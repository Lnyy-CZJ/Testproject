# BugAgent v5.4 设计文档

> Date: 2026-04-25  
> Scope: `PRD-v5.4` 全部（P0 + P1）  
> 对应计划: `DEV_PLAN-v5.4.md`

---

## 1. 设计目标

1. 打通人工修复闭环：在 AI 修复失败或用户选择手动修复时，系统内可完成修复登记和 PR 关联。
2. 补齐 PR 生命周期：PR 创建后持续跟踪其状态，拒绝时自动回退缺陷并记录原因。
3. 建立 Agent 记忆体系：AI 分析和修复可利用项目/迭代级历史经验，随使用积累提升质量。

---

## 2. 总体架构改动

### 2.1 状态机扩展层（Backend）

在现有缺陷状态机中新增 `manual_fixing` 状态，与 `fixing` 并行，分别对应人工修复和 AI 自动修复两条路径。

```
pending_fix ──→ fixing           (AI 自动修复，已有)
pending_fix ──→ manual_fixing    (人工修复，新增)
manual_fixing ──→ pending_verify (人工提交修复完成)
manual_fixing ──→ pending_fix    (放弃人工修复)
```

### 2.2 PR 生命周期跟踪层（Backend + VCS Webhook）

1. FixTask 新增 `PRStatus` 字段跟踪 PR 状态。
2. 新增 VCS Webhook 入口接收 GitHub/GitLab 的 PR 事件。
3. 新增 `PRRejection` 模型记录拒绝历史。
4. 手动标记 API 作为 Webhook 降级方案。

### 2.3 Agent 记忆层（Backend + AI）

1. 新增 `AgentMemory` 模型，两级存储（项目级 + 迭代级）。
2. AI 分析/修复完成后自动提取记忆条目。
3. AI 调用前注入匹配记忆到 Prompt。
4. PR 拒绝时自动沉淀 `avoid_strategy` 记忆。

---

## 3. 详细设计

## 3.1 人工修复路径

### 3.1.1 状态机变更

**文件**: `server/internal/model/workflow.go`

新增常量：

```go
DefectStatusManualFixing = "manual_fixing"
```

在 `AllDefectStatuses` 中追加 `DefectStatusManualFixing`。

在 `DefectTransitionMatrix` 中新增：

```go
DefectStatusPendingFix: {
    ...existing,
    DefectStatusManualFixing: true,
},
DefectStatusManualFixing: {
    DefectStatusPendingVerify: true,
    DefectStatusPendingFix:    true,
},
```

### 3.1.2 FixTask 模型变更

**文件**: `server/internal/model/models.go`

FixTask 新增字段：

```go
Source            string `json:"source" gorm:"size:20;not null;default:auto"`
ManualDescription string `json:"manualDescription" gorm:"type:text"`
```

`Source` 取值：`"auto"`（AI 自动修复）/ `"manual"`（人工修复）。

### 3.1.3 Service 层设计

**文件**: `server/internal/service/manual_fix.go`（新建）

```go
type ManualFixService struct {
    db *gorm.DB
}

func NewManualFixService(db *gorm.DB) *ManualFixService

// StartManualFix 开始人工修复
// 1. 校验缺陷状态为 pending_fix
// 2. 更新状态为 manual_fixing
// 3. 记录 StatusChange
func (s *ManualFixService) StartManualFix(defectID uint, userID uint) error

// CompleteManualFix 提交人工修复完成
// 1. 校验缺陷状态为 manual_fixing
// 2. 创建 FixTask（source=manual, status=completed）
// 3. 更新缺陷状态为 pending_verify
// 4. 记录 StatusChange
// 5. 发布修复完成评论
func (s *ManualFixService) CompleteManualFix(defectID uint, req CompleteManualFixRequest, userID uint) error

// AbandonManualFix 放弃人工修复
// 1. 校验缺陷状态为 manual_fixing
// 2. 更新状态回退为 pending_fix
// 3. 记录 StatusChange
func (s *ManualFixService) AbandonManualFix(defectID uint, userID uint) error

// UpdateFixTaskPR 补填/修改关联 PR URL
// 1. 校验 FixTask 存在且属于该缺陷
// 2. 更新 PRURL 和 PRNumber
// 3. 如果 PRStatus 为 open 且 PRURL 非空，设置 PRStatus = "open"
func (s *ManualFixService) UpdateFixTaskPR(defectID uint, taskID uint, prURL string) error
```

请求结构：

```go
type CompleteManualFixRequest struct {
    Description string `json:"description" binding:"required"`
    PRURL       string `json:"prUrl"`
    FixBranch   string `json:"fixBranch"`
}
```

### 3.1.4 Handler 层设计

**文件**: `server/internal/handler/manual_fix.go`（新建）

| 方法 | 路径 | Handler | 说明 |
|------|------|---------|------|
| POST | `/api/v1/defects/:id/manual-fix/start` | `StartManualFix` | 开始人工修复 |
| POST | `/api/v1/defects/:id/manual-fix/complete` | `CompleteManualFix` | 提交修复完成 |
| POST | `/api/v1/defects/:id/manual-fix/abandon` | `AbandonManualFix` | 放弃人工修复 |
| PATCH | `/api/v1/defects/:id/fix-tasks/:taskId/pr` | `UpdateFixTaskPR` | 补填 PR URL |

### 3.1.5 前端交互设计

1. **缺陷详情页**：`pending_fix` 状态下，除"AI 修复"按钮外新增"人工修复"按钮。
2. **人工修复表单**：点击后弹出 Drawer/Modal，包含：
   - 修复描述（必填，TextArea）
   - 关联 PR URL（选填，Input）
   - 修复分支名（选填，Input）
3. **修复中状态**：`manual_fixing` 状态下显示"人工修复中"标签，提供"提交修复完成"和"放弃"两个操作。
4. **FixTask 列表**：统一展示 AI/人工 FixTask，通过 `source` 字段显示不同标签（AI=蓝色"自动"，Manual=绿色"手动"）。
5. **补关联 PR**：`pending_verify` 状态下，FixTask 的 PR URL 字段可编辑。

---

## 3.2 PR 生命周期管理

### 3.2.1 FixTask 模型变更

**文件**: `server/internal/model/models.go`

FixTask 新增字段：

```go
PRStatus string `json:"prStatus" gorm:"size:20;not null;default:open"`
```

取值：`"open"` / `"merged"` / `"closed"` / `"rejected"`。

### 3.2.2 PRRejection 模型

**文件**: `server/internal/model/models.go`（新增）

```go
type PRRejection struct {
    ID            uint   `gorm:"primaryKey" json:"id"`
    FixTaskID     uint   `gorm:"index;not null" json:"fixTaskId"`
    PRNumber      string `gorm:"size:50" json:"prNumber"`
    PRURL         string `gorm:"size:500" json:"prUrl"`
    RejectedBy    string `gorm:"size:100" json:"rejectedBy"`
    RejectReason  string `gorm:"type:text" json:"rejectReason"`
    VCSProvider   string `gorm:"size:20" json:"vcsProvider"`
    CreatedAt     int64  `json:"createdAt"`
}

func (PRRejection) TableName() string { return "pr_rejections" }
```

### 3.2.3 VCS Webhook 处理

**文件**: `server/internal/service/vcs_webhook.go`（新建）

```go
type VCSWebhookService struct {
    db           *gorm.DB
    fixService   *FixService
    memoryService *AgentMemoryService
}

func NewVCSWebhookService(db *gorm.DB) *VCSWebhookService

// HandleWebhook 处理 VCS Webhook 事件
func (s *VCSWebhookService) HandleWebhook(provider string, payload []byte, signature string) error

// handleGitHubPREvent 处理 GitHub PR 事件
// 1. 解析 payload，提取 action / pull_request
// 2. 如果 action=closed & merged=false → PR 被拒绝
// 3. 如果 action=closed & merged=true → PR 被合并
// 4. 通过 repo URL + PR number 查找关联 FixTask
// 5. 执行对应处理逻辑

// handleGitLabMREvent 处理 GitLab MR 事件
// 1. 解析 payload，提取 object_attributes.state
// 2. state=closed → MR 被拒绝（需检查 merged 字段）
// 3. state=merged → MR 被合并
// 4. 通过 repo URL + MR number 查找关联 FixTask
// 5. 执行对应处理逻辑
```

**PR 拒绝处理流程**：

```go
func (s *VCSWebhookService) handlePRRejected(fixTask model.FixTask, prNumber, rejectedBy, reason, provider string) error {
    // 1. 创建 PRRejection 记录
    rejection := model.PRRejection{
        FixTaskID:    fixTask.ID,
        PRNumber:     prNumber,
        PRURL:        fixTask.PRURL,
        RejectedBy:   rejectedBy,
        RejectReason: reason,
        VCSProvider:  provider,
        CreatedAt:    time.Now().Unix(),
    }
    s.db.Create(&rejection)

    // 2. 更新 FixTask PRStatus
    s.db.Model(&model.FixTask{}).Where("id = ?", fixTask.ID).Update("pr_status", "rejected")

    // 3. 缺陷状态回退
    s.db.Model(&model.Defect{}).Where("id = ?", fixTask.DefectID).Update("status", model.DefectStatusPendingFix)

    // 4. 记录 StatusChange
    statusChange := model.StatusChange{
        DefectID:   fixTask.DefectID,
        FromStatus: model.DefectStatusPendingVerify,
        ToStatus:   model.DefectStatusPendingFix,
        Comment:    fmt.Sprintf("PR #%s 被拒绝，原因：%s", prNumber, reason),
    }
    s.db.Create(&statusChange)

    // 5. 发布评论
    // 6. 自动沉淀 avoid_strategy 记忆（如果 memoryService 可用）
    return nil
}
```

**PR 合并处理流程**：

```go
func (s *VCSWebhookService) handlePRMerged(fixTask model.FixTask) error {
    // 1. 更新 FixTask PRStatus
    s.db.Model(&model.FixTask{}).Where("id = ?", fixTask.ID).Update("pr_status", "merged")

    // 2. 缺陷状态推进
    s.db.Model(&model.Defect{}).Where("id = ?", fixTask.DefectID).Update("status", model.DefectStatusFixed)

    // 3. 记录 StatusChange
    // 4. 发布合并评论
    return nil
}
```

### 3.2.4 FixTask 查找逻辑

通过 VCS Webhook 中的 repo URL + PR number 反查 FixTask：

```go
func (s *VCSWebhookService) findFixTaskByPR(repoURL, prNumber string) (*model.FixTask, error) {
    var fixTask model.FixTask
    err := s.db.Where("pr_number = ? AND pr_url LIKE ?", prNumber, "%"+extractRepoPath(repoURL)+"%").
        Order("created_at DESC").
        First(&fixTask).Error
    if err != nil {
        return nil, err
    }
    return &fixTask, nil
}
```

### 3.2.5 手动标记 API

**文件**: `server/internal/handler/pr_lifecycle.go`（新建）

| 方法 | 路径 | Handler | 说明 |
|------|------|---------|------|
| POST | `/api/v1/defects/:id/fix-tasks/:taskId/reject` | `ManualRejectPR` | 手动标记 PR 被拒绝 |
| POST | `/api/v1/defects/:id/fix-tasks/:taskId/merge` | `ManualMergePR` | 手动标记 PR 已合并 |
| GET | `/api/v1/defects/:id/fix-tasks/:taskId/rejections` | `ListPRRejections` | 获取 PR 拒绝记录 |

请求结构：

```go
type ManualRejectPRRequest struct {
    RejectedBy   string `json:"rejectedBy"`
    RejectReason string `json:"rejectReason" binding:"required"`
}
```

### 3.2.6 Webhook 路由

**文件**: `server/internal/router/router.go`

在公开路由组（无需认证）中新增：

```go
vcsGroup := public.Group("/inbound/vcs")
{
    vcsGroup.POST("/webhook", vcsWebhookHandler.HandleWebhook)
}
```

### 3.2.7 前端交互设计

1. **FixTask 卡片**：展示 PR 状态标签（open=黄色，merged=绿色，rejected=红色）。
2. **PR 拒绝历史**：FixTask 详情中展示 `PRRejection` 列表（拒绝人、原因、时间）。
3. **手动标记**：`pending_verify` 状态下提供"标记 PR 被拒绝"和"标记 PR 已合并"按钮。
4. **状态回退通知**：PR 被拒绝后，缺陷详情页显示回退提示。

---

## 3.3 Agent 记忆体系

### 3.3.1 AgentMemory 模型

**文件**: `server/internal/model/models.go`（新增）

```go
const (
    MemoryCategoryArchitecture      = "architecture"
    MemoryCategoryConvention        = "convention"
    MemoryCategoryCommonError       = "common_error"
    MemoryCategoryFixStrategy       = "fix_strategy"
    MemoryCategoryAvoidStrategy     = "avoid_strategy"
    MemoryCategoryIterationContext  = "iteration_context"

    MemorySourceAutoExtract  = "auto_extract"
    MemorySourceManual       = "manual"
    MemorySourcePRRejection  = "pr_rejection"
)

type AgentMemory struct {
    ID             uint    `gorm:"primaryKey" json:"id"`
    ProjectID      uint    `gorm:"index;not null" json:"projectId"`
    IterationID    *uint   `gorm:"index" json:"iterationId"`
    Category       string  `gorm:"size:30;not null" json:"category"`
    Content        string  `gorm:"type:text;not null" json:"content"`
    Source         string  `gorm:"size:20;not null" json:"source"`
    SourceRefID    *uint   `json:"sourceRefId"`
    RelevanceScore float64 `gorm:"default:0" json:"relevanceScore"`
    Enabled        bool    `gorm:"default:true" json:"enabled"`
    CreatedBy      uint    `json:"createdBy"`
    CreatedAt      int64   `json:"createdAt"`
    UpdatedAt      int64   `json:"updatedAt"`
}

func (AgentMemory) TableName() string { return "agent_memories" }
```

### 3.3.2 Service 层设计

**文件**: `server/internal/service/agent_memory.go`（新建）

```go
type AgentMemoryService struct {
    db       *gorm.DB
    aiClient ai.AIClient
}

func NewAgentMemoryService(db *gorm.DB) *AgentMemoryService

// CRUD
func (s *AgentMemoryService) ListMemories(projectID uint, iterationID *uint, category string) ([]model.AgentMemory, error)
func (s *AgentMemoryService) CreateMemory(memory *model.AgentMemory) error
func (s *AgentMemoryService) UpdateMemory(memoryID uint, updates map[string]interface{}) error
func (s *AgentMemoryService) DeleteMemory(memoryID uint) error
func (s *AgentMemoryService) ToggleMemory(memoryID uint) error

// 自动提取
func (s *AgentMemoryService) ExtractMemoriesFromAnalysis(defectID uint, report model.AnalysisReport) error
func (s *AgentMemoryService) ExtractMemoriesFromFix(defectID uint, fixTask model.FixTask) error
func (s *AgentMemoryService) ExtractMemoryFromPRRejection(rejection model.PRRejection, fixTask model.FixTask) error

// 记忆注入
func (s *AgentMemoryService) BuildMemoryContext(projectID uint, iterationID uint) string
```

### 3.3.3 自动提取 Prompt 设计

**文件**: `server/internal/ai/memory_prompts.go`（新建）

分析完成后的记忆提取 Prompt：

```
You are a knowledge extraction assistant. Given the following bug analysis report, extract reusable knowledge items that could help future analysis of similar bugs.

Bug: {title}
Type: {type}
Analysis: {analysis_json}

Output a JSON array of knowledge items, each with:
- category: one of [architecture, convention, common_error, fix_strategy]
- content: concise knowledge statement (max 200 chars)
- relevanceScore: 0.0-1.0

Rules:
1. Only extract project-specific or pattern-level knowledge, not bug-specific details.
2. Each item must be independently useful.
3. Max 5 items per extraction.
```

修复完成后的记忆提取 Prompt：

```
You are a knowledge extraction assistant. Given the following auto-fix result, extract reusable knowledge about effective fix strategies.

Bug: {title}
Fix steps: {fix_plan_json}
Result: {result_json}

Output a JSON array of knowledge items, each with:
- category: one of [fix_strategy, avoid_strategy, convention]
- content: concise knowledge statement (max 200 chars)
- relevanceScore: 0.0-1.0

Rules:
1. Focus on strategies that worked or patterns that were important.
2. Max 3 items per extraction.
```

### 3.3.4 记忆注入设计

**文件**: `server/internal/service/analysis.go`（修改）

在 `analyzeDefect` 方法中，构建 Prompt 前注入记忆：

```go
// 在现有 Prompt 构建逻辑前插入
memoryService := NewAgentMemoryService(s.db)
memoryContext := memoryService.BuildMemoryContext(defect.Iteration.ProjectID, defect.IterationID)
if memoryContext != "" {
    prompt = "## Project Knowledge\n" + memoryContext + "\n\n" + prompt
}
```

**文件**: `server/internal/service/fix_engine.go`（修改）

在 `GenerateFixWithMetricsAndContext` 调用前注入记忆：

```go
memoryService := NewAgentMemoryService(s.db)
memoryContext := memoryService.BuildMemoryContext(defect.Iteration.ProjectID, defect.IterationID)
if memoryContext != "" {
    fixContext.ProjectKnowledge = memoryContext
}
```

### 3.3.5 BuildMemoryContext 实现

```go
func (s *AgentMemoryService) BuildMemoryContext(projectID uint, iterationID uint) string {
    var memories []model.AgentMemory

    // 查询项目级记忆
    s.db.Where("project_id = ? AND iteration_id IS NULL AND enabled = true", projectID).
        Order("relevance_score DESC").
        Find(&memories)

    // 查询迭代级记忆
    s.db.Where("project_id = ? AND iteration_id = ? AND enabled = true", projectID, iterationID).
        Order("relevance_score DESC").
        Find(&memories)

    // 按 token 限制截断（2000 token ≈ 4000 中文字符 ≈ 8000 英文字符）
    var builder strings.Builder
    tokenEstimate := 0
    maxTokens := 2000

    for _, m := range memories {
        entry := fmt.Sprintf("- [%s] %s", m.Category, m.Content)
        entryTokens := len(entry) / 4 // 粗估
        if tokenEstimate+entryTokens > maxTokens {
            break
        }
        builder.WriteString(entry + "\n")
        tokenEstimate += entryTokens
    }

    return builder.String()
}
```

### 3.3.6 语义去重设计

首版采用简单去重策略：

1. 提取记忆时，对同一 `projectID + category` 下的现有记忆做关键词匹配。
2. 新记忆与现有记忆的 Jaccard 相似度 > 0.7 时，合并（更新 content，取更高 relevanceScore）。
3. Jaccard 计算：分词后取交集/并集比。

```go
func jaccardSimilarity(a, b string) float64 {
    setA := tokenize(a)
    setB := tokenize(b)
    intersection := 0
    for k := range setA {
        if setB[k] {
            intersection++
        }
    }
    union := len(setA) + len(setB) - intersection
    if union == 0 {
        return 0
    }
    return float64(intersection) / float64(union)
}
```

### 3.3.7 PR 拒绝自动沉淀记忆

在 `VCSWebhookService.handlePRRejected` 中追加：

```go
// 自动沉淀 avoid_strategy 记忆
memoryService := NewAgentMemoryService(s.db)
memory := model.AgentMemory{
    ProjectID:      projectID,
    IterationID:    nil, // 项目级
    Category:       model.MemoryCategoryAvoidStrategy,
    Content:        fmt.Sprintf("修复策略在 %s 场景下被拒绝，原因：%s", defect.Title, reason),
    Source:         model.MemorySourcePRRejection,
    SourceRefID:    &rejection.ID,
    RelevanceScore: 0.8,
    Enabled:        true,
    CreatedBy:      0,
}
memoryService.CreateMemory(&memory)
```

### 3.3.8 Handler 层设计

**文件**: `server/internal/handler/agent_memory.go`（新建）

| 方法 | 路径 | Handler | 说明 |
|------|------|---------|------|
| GET | `/api/v1/projects/:id/memories` | `ListProjectMemories` | 项目级记忆列表 |
| GET | `/api/v1/projects/:id/iterations/:iterId/memories` | `ListIterationMemories` | 迭代级记忆列表 |
| POST | `/api/v1/projects/:id/memories` | `CreateProjectMemory` | 新增项目级记忆 |
| POST | `/api/v1/projects/:id/iterations/:iterId/memories` | `CreateIterationMemory` | 新增迭代级记忆 |
| PUT | `/api/v1/projects/:id/memories/:memoryId` | `UpdateMemory` | 编辑记忆 |
| DELETE | `/api/v1/projects/:id/memories/:memoryId` | `DeleteMemory` | 删除记忆 |
| PATCH | `/api/v1/projects/:id/memories/:memoryId/toggle` | `ToggleMemory` | 启禁用记忆 |

### 3.3.9 前端交互设计

1. **项目设置页**：新增"Agent 记忆"Tab，展示项目级记忆列表。
2. **迭代设置页**：新增"Agent 记忆"Tab，展示迭代级记忆列表。
3. **记忆卡片**：每条记忆显示 category 标签、content、来源（自动/手动/PR拒绝）、启用状态。
4. **操作**：新增、编辑、删除、启禁用。
5. **AI 分析详情**：展示注入的记忆条目数量和总 token 估算。

---

## 4. 数据库迁移

### 4.1 新增表

```sql
CREATE TABLE pr_rejections (
    id BIGSERIAL PRIMARY KEY,
    fix_task_id BIGINT NOT NULL,
    pr_number VARCHAR(50),
    pr_url VARCHAR(500),
    rejected_by VARCHAR(100),
    reject_reason TEXT,
    vcs_provider VARCHAR(20),
    created_at BIGINT
);

CREATE INDEX idx_pr_rejections_fix_task_id ON pr_rejections(fix_task_id);

CREATE TABLE agent_memories (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    iteration_id BIGINT,
    category VARCHAR(30) NOT NULL,
    content TEXT NOT NULL,
    source VARCHAR(20) NOT NULL,
    source_ref_id BIGINT,
    relevance_score DOUBLE PRECISION DEFAULT 0,
    enabled BOOLEAN DEFAULT true,
    created_by BIGINT,
    created_at BIGINT,
    updated_at BIGINT
);

CREATE INDEX idx_agent_memories_project_id ON agent_memories(project_id);
CREATE INDEX idx_agent_memories_iteration_id ON agent_memories(iteration_id);
CREATE INDEX idx_agent_memories_project_category ON agent_memories(project_id, category);
```

### 4.2 修改表

```sql
ALTER TABLE fix_tasks ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'auto';
ALTER TABLE fix_tasks ADD COLUMN manual_description TEXT;
ALTER TABLE fix_tasks ADD COLUMN pr_status VARCHAR(20) NOT NULL DEFAULT 'open';
```

### 4.3 GORM AutoMigrate

在 `server/internal/model/models.go` 的迁移注册中追加 `PRRejection{}` 和 `AgentMemory{}`。

---

## 5. 兼容性与迁移

1. FixTask 新增字段均有默认值，老数据自动兼容。
2. `manual_fixing` 状态为新增，不影响现有状态流转。
3. `PRStatus` 默认 `open`，老 FixTask 自动标记为 `open`。
4. Agent 记忆为全新功能，无迁移问题。
5. VCS Webhook 为新增路由，不影响现有 API。

---

## 6. 验收要点

1. 人工修复：`pending_fix` → `manual_fixing` → `pending_verify` 流程完整可用。
2. PR 拒绝：Webhook 触发后缺陷状态自动回退，拒绝记录可查。
3. PR 合并：Webhook 触发后缺陷状态自动推进。
4. Agent 记忆：AI 分析/修复后自动提取，后续调用注入记忆。
5. PR 拒绝记忆：拒绝时自动沉淀 `avoid_strategy` 记忆。
6. 手动降级：Webhook 不可用时手动标记 API 可用。
