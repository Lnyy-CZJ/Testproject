# V5.2 Chat-First Defect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a chat-first defect creation flow, automatically ingest manual defects into the issue pool, and redesign the defect detail page with proper Markdown rendering and readable structure.

**Architecture:** Extend the existing defect handler into a two-step draft-and-confirm flow, add a focused manual-defect ingest service that bridges formal defects into the `IssueSignal / IssueCluster` model, and split the current monolithic detail page into summary, timeline, and Markdown-driven content blocks. Keep the existing defect domain as the source of truth while issue-pool linkage becomes an automatic post-create side effect.

**Tech Stack:** Go + Gin + Gorm, React 19 + Ant Design 6 + React Router 7, Playwright, GFM Markdown via `react-markdown` + `remark-gfm`.

---

## File Map

### Backend

- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/model/signal.go`
  - Make `IssueSignal.ConnectorID` nullable for manual defects.
  - Add manual source constants.
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/model/models.go`
  - Add optional fields to `Defect` only if needed for linkage preload or summary payloads.
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/router/router.go`
  - Register draft-generation and confirm-create endpoints.
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/handler/defect.go`
  - Split create flow into draft generation + confirm create.
  - Return detail payload with summary/raw sections.
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/defect_draft.go`
  - Generate structured draft from chat input, with fallback path.
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/manual_defect_signal.go`
  - Create `manual_chat` / `manual_form` signals and clusters after defect creation.
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/quality_insights.go`
  - Ensure source breakdown counts include manual sources.
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/signal_triage.go`
  - Preserve manual-source clusters as `converted` and keep defect linkage visible.
- Test: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/handler/defect_chat_test.go`
- Test: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/defect_draft_test.go`
- Test: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/manual_defect_signal_test.go`
- Test: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/quality_insights_test.go`

### Frontend

- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/package.json`
  - Add Markdown rendering dependencies.
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/api/index.ts`
  - Add draft/confirm-create APIs.
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/types/index.ts`
  - Add draft, timeline, and manual-source types.
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/DefectCreate.tsx`
  - Replace form-first UI with chat-first shell and advanced-mode switch.
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectDraftChat.tsx`
  - Chat input and context capture.
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectDraftConfirm.tsx`
  - Editable confirmation view.
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/projects/ProjectIssuePool.tsx`
  - Show `manual_chat` / `manual_form` source labels and linked defect affordance.
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/components/MarkdownContent.tsx`
  - Shared GFM rendering wrapper.
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/DefectDetail.tsx`
  - Recompose layout and replace raw string rendering with structured cards.
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectDetailHeader.tsx`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectAnalysisSummary.tsx`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectTimeline.tsx`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectRawDataPanel.tsx`
- Test: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/e2e/browser-prd-flows.spec.ts`

---

### Task 1: Draft API and Chat-First Contract

**Files:**
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/defect_draft.go`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/defect_draft_test.go`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/handler/defect_chat_test.go`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/handler/defect.go`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/router/router.go`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/api/index.ts`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/types/index.ts`

- [ ] **Step 1: Write the failing backend draft-generation tests**

```go
func TestDefectDraftService_GenerateDraftFromChat(t *testing.T) {
    svc := NewDefectDraftService(nil)

    draft, err := svc.fallbackDraft(DefectDraftRequest{
        Message: "云效导入仓库页面搜索无效，应该本地过滤",
    })
    if err != nil {
        t.Fatalf("fallbackDraft returned error: %v", err)
    }
    if draft.Title == "" {
        t.Fatalf("expected title")
    }
    if draft.Type != model.DefectTypeOther {
        t.Fatalf("expected fallback type other, got %s", draft.Type)
    }
    if draft.Priority != model.PriorityP2 {
        t.Fatalf("expected fallback priority P2, got %s", draft.Priority)
    }
}

func TestDefectHandler_CreateDraftFromChat(t *testing.T) {
    db := testutil.SetupTestDB(t)
    model.SetDB(db)
    user := testutil.CreateTestUser(t, db)
    project, iteration := createProjectAndIteration(t, db, user.ID)

    h := NewDefectHandler()
    r := gin.New()
    r.POST("/projects/:id/defects/draft-from-chat", func(c *gin.Context) {
        c.Set("userID", user.ID)
        h.CreateDraftFromChat(c)
    })

    body := `{"iterationId":` + strconv.Itoa(int(iteration.ID)) + `,"message":"登录页按钮被键盘遮挡"}`
    req := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/projects/%d/defects/draft-from-chat", project.ID), strings.NewReader(body))
    req.Header.Set("Content-Type", "application/json")
    w := httptest.NewRecorder()

    r.ServeHTTP(w, req)
    if w.Code != http.StatusOK {
        t.Fatalf("expected 200, got %d body=%s", w.Code, w.Body.String())
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server && go test ./internal/service ./internal/handler -run 'TestDefect(DraftService_|Handler_CreateDraftFromChat)' -count=1
```

Expected: FAIL with missing `DefectDraftService`, `CreateDraftFromChat`, or unmatched response shape.

- [ ] **Step 3: Write minimal draft service and handler contract**

```go
type DefectDraftRequest struct {
    IterationID uint     `json:"iterationId"`
    Message     string   `json:"message"`
    Tags        []string `json:"tags,omitempty"`
}

type DefectDraft struct {
    Title                string   `json:"title"`
    DescriptionMarkdown  string   `json:"descriptionMarkdown"`
    Severity             string   `json:"severity"`
    Priority             string   `json:"priority"`
    Type                 string   `json:"type"`
    Tags                 []string `json:"tags"`
    SuggestedIterationID *uint    `json:"suggestedIterationId,omitempty"`
    MissingInformation   []string `json:"missingInformation,omitempty"`
    Confidence           float64  `json:"confidence"`
    SourceMode           string   `json:"sourceMode"`
}

func (s *DefectDraftService) fallbackDraft(req DefectDraftRequest) (*DefectDraft, error) {
    title := strings.TrimSpace(req.Message)
    if title == "" {
        title = "未命名缺陷"
    }
    return &DefectDraft{
        Title:               truncateText(title, 100),
        DescriptionMarkdown: strings.TrimSpace(req.Message),
        Severity:            model.SeverityNormal,
        Priority:            model.PriorityP2,
        Type:                model.DefectTypeOther,
        Tags:                req.Tags,
        MissingInformation:  []string{"AI 整理失败，请手动确认字段。"},
        Confidence:          0,
        SourceMode:          "chat",
    }, nil
}
```

- [ ] **Step 4: Run tests to verify the draft contract passes**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server && go test ./internal/service ./internal/handler -run 'TestDefect(DraftService_|Handler_CreateDraftFromChat)' -count=1
```

Expected: PASS

- [ ] **Step 5: Wire frontend API/types for draft generation**

```ts
export interface DefectDraft {
  title: string;
  descriptionMarkdown: string;
  severity: string;
  priority: string;
  type: string;
  tags: string[];
  suggestedIterationId?: number;
  missingInformation?: string[];
  confidence: number;
  sourceMode: 'chat' | 'form';
}

export const createDefectDraftFromChat = (projectId: number, data: {
  iterationId: number;
  message: string;
  tags?: string[];
}) => request.post(`/projects/${projectId}/defects/draft-from-chat`, data);
```

- [ ] **Step 6: Commit**

```bash
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first add \
  server/internal/service/defect_draft.go \
  server/internal/service/defect_draft_test.go \
  server/internal/handler/defect.go \
  server/internal/handler/defect_chat_test.go \
  server/internal/router/router.go \
  web/src/api/index.ts \
  web/src/types/index.ts
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first commit -m "feat: add defect chat draft api"
```

### Task 2: Chat-First Create UI and Confirm Flow

**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/DefectCreate.tsx`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectDraftChat.tsx`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectDraftConfirm.tsx`
- Test: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/e2e/browser-prd-flows.spec.ts`

- [ ] **Step 1: Write the failing browser regression**

```ts
test('chat-first defect creation generates draft then confirms create', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/projects/1/defects/create');
  await expect(page.getByText('对话创建缺陷')).toBeVisible();
  await page.getByPlaceholder('先描述问题').fill('云效导入搜索应该本地过滤');
  await page.getByRole('button', { name: '生成草稿' }).click();
  await expect(page.getByText('AI 整理后的缺陷内容')).toBeVisible();
  await page.getByRole('button', { name: '确认创建' }).click();
  await expect(page).toHaveURL(/\/projects\/1\/defects\/\d+$/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run test:e2e -- --grep "chat-first defect creation generates draft then confirms create"
```

Expected: FAIL because page is still form-first.

- [ ] **Step 3: Implement minimal chat-first UI with advanced-mode fallback**

```tsx
const [mode, setMode] = useState<'chat' | 'advanced'>('chat');
const [draft, setDraft] = useState<DefectDraft | null>(null);

if (mode === 'chat' && !draft) {
  return <DefectDraftChat onSubmit={handleGenerateDraft} onSwitchAdvanced={() => setMode('advanced')} />;
}
if (mode === 'chat' && draft) {
  return <DefectDraftConfirm draft={draft} onConfirm={handleConfirmCreate} onSwitchAdvanced={() => setMode('advanced')} />;
}
return <LegacyDefectForm />;
```

- [ ] **Step 4: Run build and targeted browser test**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run build
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run test:e2e -- --grep "chat-first defect creation generates draft then confirms create"
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first add \
  web/src/pages/defects/DefectCreate.tsx \
  web/src/pages/defects/components/DefectDraftChat.tsx \
  web/src/pages/defects/components/DefectDraftConfirm.tsx \
  web/e2e/browser-prd-flows.spec.ts
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first commit -m "feat: add chat first defect creation"
```

### Task 3: Manual Defects Into Issue Pool

**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/model/signal.go`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/manual_defect_signal.go`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/manual_defect_signal_test.go`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/handler/defect.go`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/quality_insights.go`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/projects/ProjectIssuePool.tsx`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/types/index.ts`
- Test: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/quality_insights_test.go`

- [ ] **Step 1: Write the failing ingest tests**

```go
func TestManualDefectSignalService_CreateFromDefect_ChatSource(t *testing.T) {
    db := testutil.SetupTestDB(t)
    model.SetDB(db)
    user := testutil.CreateTestUser(t, db)
    project, iteration := createProjectAndIteration(t, db, user.ID)
    defect := testutil.CreateDefect(t, db, iteration.ID, user.ID)

    svc := NewManualDefectSignalService(db)
    signal, cluster, err := svc.CreateFromDefect(defect, "manual_chat")
    if err != nil {
        t.Fatalf("CreateFromDefect returned error: %v", err)
    }
    if signal.SourceType != "manual_chat" {
        t.Fatalf("expected manual_chat, got %s", signal.SourceType)
    }
    if cluster.LinkedDefectID == nil || *cluster.LinkedDefectID != defect.ID {
        t.Fatalf("expected linked defect")
    }
    if signal.LinkedDefectID == nil || *signal.LinkedDefectID != defect.ID {
        t.Fatalf("expected signal linked defect")
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server && go test ./internal/service -run 'TestManualDefectSignalService_' -count=1
```

Expected: FAIL because service and nullable connector support do not exist.

- [ ] **Step 3: Implement manual defect ingest with nullable connector**

```go
const (
    SignalSourceManualChat = "manual_chat"
    SignalSourceManualForm = "manual_form"
)

type ManualDefectSignalService struct { db *gorm.DB }

func (s *ManualDefectSignalService) CreateFromDefect(defect model.Defect, sourceType string) (*model.IssueSignal, *model.IssueCluster, error) {
    cluster := model.IssueCluster{
        ProjectID:      defect.Iteration.ProjectID,
        ClusterKey:     fmt.Sprintf("manual-defect-%d", defect.ID),
        Title:          defect.Title,
        Summary:        defect.Description,
        Status:         model.IssueTriageStatusConverted,
        Severity:       defect.Severity,
        Priority:       defect.Priority,
        LinkedDefectID: &defect.ID,
        FirstSeenAt:    defect.CreatedAt,
        LastSeenAt:     defect.CreatedAt,
    }
    signal := model.IssueSignal{
        ProjectID:      defect.Iteration.ProjectID,
        ConnectorID:    nil,
        SourceType:     sourceType,
        SourceInstance: fmt.Sprintf("manual:defect:%d", defect.ID),
        SourceEventID:  fmt.Sprintf("defect:%d", defect.ID),
        Title:          defect.Title,
        Description:    defect.Description,
        RawSeverity:    defect.Severity,
        RawPriority:    defect.Priority,
        FirstSeenAt:    defect.CreatedAt,
        LastSeenAt:     defect.CreatedAt,
        RawPayloadJSON: fmt.Sprintf(`{"defectId":%d}`, defect.ID),
        TriageStatus:   model.IssueTriageStatusConverted,
        LinkedDefectID: &defect.ID,
    }
    // persist cluster then signal inside transaction
}
```

- [ ] **Step 4: Hook confirm-create and legacy form create into manual ingest**

```go
if err := model.DB.Transaction(func(tx *gorm.DB) error {
    if err := tx.Create(&defect).Error; err != nil {
        return err
    }
    return manualSignalSvc.WithDB(tx).CreateLinkedFromDefect(defect, sourceType)
}); err != nil {
    response.BadRequest(c, "创建缺陷失败")
    return
}
```

- [ ] **Step 5: Update issue pool / quality insights tests and UI source labels**

```tsx
const sourceLabelMap: Record<string, string> = {
  manual_chat: '手动创建 / 对话',
  manual_form: '手动创建 / 高级模式',
  bugly: 'Bugly',
  aliyun_log: '阿里云日志',
};
```

- [ ] **Step 6: Run focused backend and frontend verification**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server && go test ./internal/service ./internal/handler -run 'Test(ManualDefectSignalService_|DefectHandler_ConfirmCreate|QualityInsights)' -count=1
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run build
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first add \
  server/internal/model/signal.go \
  server/internal/service/manual_defect_signal.go \
  server/internal/service/manual_defect_signal_test.go \
  server/internal/handler/defect.go \
  server/internal/service/quality_insights.go \
  server/internal/service/quality_insights_test.go \
  web/src/pages/projects/ProjectIssuePool.tsx \
  web/src/types/index.ts
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first commit -m "feat: ingest manual defects into issue pool"
```

### Task 4: Markdown Rendering Infrastructure and Detail Data Shaping

**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/package.json`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/components/MarkdownContent.tsx`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/api/index.ts`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/types/index.ts`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/handler/defect.go`

- [ ] **Step 1: Write the failing rendering-focused browser test**

```ts
test('defect detail renders markdown summary and folds raw data', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/projects/1/defects/2');
  await expect(page.getByRole('heading', { name: 'AI 分析摘要' })).toBeVisible();
  await expect(page.getByText('查看原始数据')).toBeVisible();
  await expect(page.locator('pre code')).toHaveCountGreaterThan(0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run test:e2e -- --grep "defect detail renders markdown summary and folds raw data"
```

Expected: FAIL because current detail page renders raw text without structured markdown blocks.

- [ ] **Step 3: Add GFM dependencies and Markdown wrapper**

```tsx
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]}>
      {content}
    </ReactMarkdown>
  );
}
```

- [ ] **Step 4: Shape detail payload for summary and raw sections**

```go
type DefectDetailPayload struct {
    Defect      model.Defect   `json:"defect"`
    Comments    []model.Comment `json:"comments"`
    FixTasks    []model.FixTask `json:"fixTasks"`
    Reports     []model.AnalysisReport `json:"reports"`
    Summary     gin.H         `json:"summary"`
    RawSections []gin.H       `json:"rawSections"`
}
```

- [ ] **Step 5: Run build and focused test**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm install
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run build
```

Expected: PASS with new dependencies resolved.

- [ ] **Step 6: Commit**

```bash
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first add \
  web/package.json web/package-lock.json \
  web/src/components/MarkdownContent.tsx \
  web/src/api/index.ts web/src/types/index.ts \
  server/internal/handler/defect.go
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first commit -m "feat: add markdown detail rendering primitives"
```

### Task 5: Defect Detail Workbench Redesign

**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/DefectDetail.tsx`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectDetailHeader.tsx`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectAnalysisSummary.tsx`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectTimeline.tsx`
- Create: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/src/pages/defects/components/DefectRawDataPanel.tsx`
- Test: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/e2e/browser-prd-flows.spec.ts`

- [ ] **Step 1: Write the failing layout regression**

```ts
test('defect detail uses summary header, timeline, and raw-data drawer sections', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/projects/1/defects/2');
  await expect(page.getByText('问题描述')).toBeVisible();
  await expect(page.getByText('评论与系统动态')).toBeVisible();
  await expect(page.getByText('原始数据')).toBeVisible();
  await expect(page.getByText('修复任务')).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run test:e2e -- --grep "defect detail uses summary header, timeline, and raw-data drawer sections"
```

Expected: FAIL because the current page is monolithic and lacks these sections.

- [ ] **Step 3: Split the detail page into focused components**

```tsx
return (
  <div className="defect-detail-page">
    <DefectDetailHeader defect={defect} summary={summary} onEdit={() => setEditModalOpen(true)} onVerify={() => void handleVerify(true)} />
    <div className="defect-detail-grid">
      <div>
        <Card title="问题描述"><MarkdownContent content={defect.description} /></Card>
        <DefectAnalysisSummary reports={reports} />
        <DefectTimeline comments={comments} reports={reports} fixTasks={fixTasks} />
      </div>
      <div>
        <PropertyCard defect={defect} />
        <FixTaskCard tasks={fixTasks} />
        <CollaborationPanel defectId={defect.id} projectId={projectId} />
        <ActionCard defect={defect} />
      </div>
    </div>
    <DefectRawDataPanel sections={rawSections} />
  </div>
);
```

- [ ] **Step 4: Run build and targeted browser tests**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run build
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run test:e2e -- --grep "defect detail renders markdown summary and folds raw data|defect detail uses summary header, timeline, and raw-data drawer sections"
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first add \
  web/src/pages/defects/DefectDetail.tsx \
  web/src/pages/defects/components/DefectDetailHeader.tsx \
  web/src/pages/defects/components/DefectAnalysisSummary.tsx \
  web/src/pages/defects/components/DefectTimeline.tsx \
  web/src/pages/defects/components/DefectRawDataPanel.tsx \
  web/e2e/browser-prd-flows.spec.ts
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first commit -m "feat: redesign defect detail workbench"
```

### Task 6: Full Verification and Integration

**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web/e2e/browser-prd-flows.spec.ts`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/handler/defect_chat_test.go`
- Modify: `/Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server/internal/service/manual_defect_signal_test.go`

- [ ] **Step 1: Add end-to-end regressions for the full 5.2 flow**

```ts
test('manual chat defect enters issue pool and shows linked detail', async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto('/projects/1/defects/create');
  await page.getByPlaceholder('先描述问题').fill('支付页按钮文案错误且点击后报错');
  await page.getByRole('button', { name: '生成草稿' }).click();
  await page.getByRole('button', { name: '确认创建' }).click();
  await page.goto('/projects/1/issue-pool');
  await expect(page.getByText('手动创建 / 对话')).toBeVisible();
  await page.getByRole('link', { name: /BUG-/ }).first().click();
  await expect(page.getByText('AI 分析摘要')).toBeVisible();
});
```

- [ ] **Step 2: Run targeted backend suites**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server && go test ./internal/handler ./internal/service -run 'Test(Defect|ManualDefectSignal|QualityInsights)' -count=1
```

Expected: PASS

- [ ] **Step 3: Run frontend build and browser regression**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run build
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/web && npm run test:e2e -- --reporter=list
```

Expected: PASS

- [ ] **Step 4: Run server full test baseline again**

Run:
```bash
cd /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first/server && go test ./... -count=1 -timeout 180s
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first add \
  server/internal/handler/defect_chat_test.go \
  server/internal/service/manual_defect_signal_test.go \
  server/internal/service/quality_insights_test.go \
  web/e2e/browser-prd-flows.spec.ts
git -C /Users/jame/Workspace/bug_agent/.worktrees/v5-2-chat-first commit -m "test: cover v5.2 defect flow end to end"
```
