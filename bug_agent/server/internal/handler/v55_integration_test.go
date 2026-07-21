package handler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"bug-agent/internal/model"
	"bug-agent/internal/sse"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func setupV55TestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	assert.NoError(t, err)

	err = db.AutoMigrate(
		&model.Defect{},
		&model.StatusChange{},
		&model.AnalysisReport{},
		&model.FixTask{},
		&model.AITokenUsage{},
		&model.DefectRepo{},
		&model.ProjectMCPServer{},
		&model.ProjectAgentSkill{},
		&model.Project{},
		&model.Iteration{},
		&model.User{},
	)
	assert.NoError(t, err)
	return db
}

func setupV55Router(db *gorm.DB) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(gin.Recovery())
	return r
}

func createTestDefectForV55(db *gorm.DB, status string) *model.Defect {
	project := &model.Project{Name: "test-project", Code: "TP"}
	db.Create(project)
	iteration := &model.Iteration{ProjectID: project.ID, Name: "Sprint 1"}
	db.Create(iteration)
	user := &model.User{Username: "testuser", Email: "test@test.com", Password: "hash"}
	db.Create(user)
	defect := &model.Defect{
		IterationID: iteration.ID,
		Title:       "Test Defect",
		Description: "desc",
		Severity:    "normal",
		Priority:    "P2",
		Type:        "functional",
		Status:      status,
		ReporterID:  user.ID,
	}
	db.Create(defect)
	return defect
}

// ============ FR-1: Status Chain ============

func TestV55_ReopenDefect_ToPendingAnalysis(t *testing.T) {
	db := setupV55TestDB(t)
	defect := createTestDefectForV55(db, model.DefectStatusRejected)
	handler := NewDefectHandler(db)
	router := setupV55Router(db)

	router.POST("/defects/:id/reopen", func(c *gin.Context) {
		c.Set("userID", uint(1))
		handler.ReopenDefect(c)
	})

	body, _ := json.Marshal(map[string]string{"targetStatus": model.DefectStatusPendingAnalysis})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/defects/"+uintToStr(defect.ID)+"/reopen", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var updated model.Defect
	db.First(&updated, defect.ID)
	assert.Equal(t, model.DefectStatusPendingAnalysis, updated.Status)

	var sc model.StatusChange
	db.Where("defect_id = ?", defect.ID).First(&sc)
	assert.Equal(t, model.DefectStatusRejected, sc.FromStatus)
	assert.Equal(t, model.DefectStatusPendingAnalysis, sc.ToStatus)
	assert.Contains(t, sc.Comment, "reopen_to:pending_analysis")
}

func TestV55_ReopenDefect_ToAnalyzing(t *testing.T) {
	db := setupV55TestDB(t)
	defect := createTestDefectForV55(db, model.DefectStatusRejected)
	handler := NewDefectHandler(db)
	router := setupV55Router(db)

	router.POST("/defects/:id/reopen", func(c *gin.Context) {
		c.Set("userID", uint(1))
		handler.ReopenDefect(c)
	})

	body, _ := json.Marshal(map[string]string{"targetStatus": model.DefectStatusAnalyzing})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/defects/"+uintToStr(defect.ID)+"/reopen", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var updated model.Defect
	db.First(&updated, defect.ID)
	assert.Equal(t, model.DefectStatusAnalyzing, updated.Status)
}

func TestV55_ReopenDefect_InvalidTarget(t *testing.T) {
	db := setupV55TestDB(t)
	defect := createTestDefectForV55(db, model.DefectStatusRejected)
	handler := NewDefectHandler(db)
	router := setupV55Router(db)

	router.POST("/defects/:id/reopen", func(c *gin.Context) {
		c.Set("userID", uint(1))
		handler.ReopenDefect(c)
	})

	body, _ := json.Marshal(map[string]string{"targetStatus": model.DefectStatusCompleted})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/defects/"+uintToStr(defect.ID)+"/reopen", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, 400, w.Code)
}

func TestV55_ReanalyzeDefect(t *testing.T) {
	db := setupV55TestDB(t)
	defect := createTestDefectForV55(db, model.DefectStatusPendingFix)

	report := &model.AnalysisReport{
		DefectID:   defect.ID,
		ReportCode: "AR-001",
		AgentType:  "frontend",
		Status:     model.AnalysisStatusCompleted,
	}
	db.Create(report)

	handler := NewDefectHandler(db)
	router := setupV55Router(db)

	router.POST("/defects/:id/reanalyze", func(c *gin.Context) {
		c.Set("userID", uint(1))
		handler.ReanalyzeDefect(c)
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/defects/"+uintToStr(defect.ID)+"/reanalyze", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var updated model.Defect
	db.First(&updated, defect.ID)
	assert.Equal(t, model.DefectStatusPendingAnalysis, updated.Status)

	var superseded model.AnalysisReport
	db.First(&superseded, report.ID)
	assert.Equal(t, model.AnalysisStatusSuperseded, superseded.Status)
}

func TestV55_ReanalyzeDefect_WrongStatus(t *testing.T) {
	db := setupV55TestDB(t)
	defect := createTestDefectForV55(db, model.DefectStatusAnalyzing)
	handler := NewDefectHandler(db)
	router := setupV55Router(db)

	router.POST("/defects/:id/reanalyze", func(c *gin.Context) {
		c.Set("userID", uint(1))
		handler.ReanalyzeDefect(c)
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/defects/"+uintToStr(defect.ID)+"/reanalyze", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 400, w.Code)
}

func TestV55_RejectedToPendingAnalysis_DirectTransition(t *testing.T) {
	assert.True(t, model.IsValidDefectTransition(model.DefectStatusRejected, model.DefectStatusPendingAnalysis))
}

func TestV55_ReopenedToPendingAnalysis_Transition(t *testing.T) {
	assert.True(t, model.IsValidDefectTransition(model.DefectStatusReopened, model.DefectStatusPendingAnalysis))
}

func TestV55_PendingFixToPendingAnalysis_Transition(t *testing.T) {
	assert.True(t, model.IsValidDefectTransition(model.DefectStatusPendingFix, model.DefectStatusPendingAnalysis))
}

// ============ FR-3: Token Usage ============

func TestV55_TokenUsage_DefectSummary(t *testing.T) {
	db := setupV55TestDB(t)
	defect := createTestDefectForV55(db, model.DefectStatusPendingFix)

	now := time.Now()
	db.Create(&model.AITokenUsage{
		ProjectID: 1, DefectID: defect.ID, ConsumptionType: "analysis", SourceID: 1,
		PromptTokens: 1000, CompletionTokens: 500, TotalTokens: 1500,
		EstimatedCostUSD: 0.05, DurationMs: 2000, CreatedAt: now,
	})
	db.Create(&model.AITokenUsage{
		ProjectID: 1, DefectID: defect.ID, ConsumptionType: "fix", SourceID: 2,
		PromptTokens: 2000, CompletionTokens: 1000, TotalTokens: 3000,
		EstimatedCostUSD: 0.10, DurationMs: 3000, CreatedAt: now,
	})
	db.Create(&model.AITokenUsage{
		ProjectID: 1, DefectID: defect.ID, ConsumptionType: "fix", SourceID: 3,
		PromptTokens: 500, CompletionTokens: 250, TotalTokens: 750,
		EstimatedCostUSD: 0.025, DurationMs: 1000, CreatedAt: now,
	})

	handler := NewTokenUsageHandler(db)
	router := setupV55Router(db)

	router.GET("/defects/:id/token-usage", handler.GetDefectTokenUsage)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/defects/"+uintToStr(defect.ID)+"/token-usage", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var resp struct {
		Data []struct {
			ConsumptionType  string `json:"consumptionType"`
			TotalTokens      int    `json:"totalTokens"`
			EstimatedCostUSD float64 `json:"estimatedCostUsd"`
			CallCount        int    `json:"callCount"`
		} `json:"data"`
	}
	json.Unmarshal(w.Body.Bytes(), &resp)

	analysisSummary := findSummary(resp.Data, "analysis")
	assert.NotNil(t, analysisSummary)
	assert.Equal(t, 1500, analysisSummary.TotalTokens)
	assert.InDelta(t, 0.05, analysisSummary.EstimatedCostUSD, 0.001)
	assert.Equal(t, 1, analysisSummary.CallCount)

	fixSummary := findSummary(resp.Data, "fix")
	assert.NotNil(t, fixSummary)
	assert.Equal(t, 3750, fixSummary.TotalTokens)
	assert.InDelta(t, 0.125, fixSummary.EstimatedCostUSD, 0.001)
	assert.Equal(t, 2, fixSummary.CallCount)
}

func TestV55_TokenUsage_FallbackAttempts(t *testing.T) {
	db := setupV55TestDB(t)
	defect := createTestDefectForV55(db, model.DefectStatusPendingFix)
	now := time.Now()

	db.Create(&model.AITokenUsage{
		ProjectID: 1, DefectID: defect.ID, ConsumptionType: "fix", SourceID: 1,
		AttemptIndex: 0, IsFinalAttempt: false,
		PromptTokens: 1000, CompletionTokens: 500, TotalTokens: 1500,
		EstimatedCostUSD: 0.05, CreatedAt: now,
	})
	db.Create(&model.AITokenUsage{
		ProjectID: 1, DefectID: defect.ID, ConsumptionType: "fix", SourceID: 1,
		AttemptIndex: 1, IsFinalAttempt: true,
		PromptTokens: 2000, CompletionTokens: 1000, TotalTokens: 3000,
		EstimatedCostUSD: 0.10, CreatedAt: now,
	})

	handler := NewTokenUsageHandler(db)
	router := setupV55Router(db)

	router.GET("/defects/:id/token-usage/details", handler.GetDefectTokenUsageDetails)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/defects/"+uintToStr(defect.ID)+"/token-usage/details", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var resp struct {
		Data []model.AITokenUsage `json:"data"`
	}
	json.Unmarshal(w.Body.Bytes(), &resp)
	assert.Len(t, resp.Data, 2)
	assert.Equal(t, 0, resp.Data[0].AttemptIndex)
	assert.False(t, resp.Data[0].IsFinalAttempt)
	assert.Equal(t, 1, resp.Data[1].AttemptIndex)
	assert.True(t, resp.Data[1].IsFinalAttempt)
}

// ============ FR-4: Defect Repo ============

func TestV55_DefectRepo_CreateAndList(t *testing.T) {
	db := setupV55TestDB(t)
	defect := createTestDefectForV55(db, model.DefectStatusFixing)

	repo := &model.DefectRepo{
		DefectID:  defect.ID,
		ProjectID: 1,
		RepoURL:   "https://github.com/test/repo.git",
		Branch:    "main",
		LocalPath: "/tmp/bug-agent/repos/defects/" + uintToStr(defect.ID) + "/a1b2c3d4",
		Status:    "active",
	}
	db.Create(repo)

	handler := NewRepoHandler(db)
	router := setupV55Router(db)
	router.GET("/defects/:id/repos", handler.ListDefectRepos)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/defects/"+uintToStr(defect.ID)+"/repos", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var resp struct {
		Data []model.DefectRepo `json:"data"`
	}
	json.Unmarshal(w.Body.Bytes(), &resp)
	assert.Len(t, resp.Data, 1)
	assert.Equal(t, "active", resp.Data[0].Status)
	assert.Equal(t, "https://github.com/test/repo.git", resp.Data[0].RepoURL)
}

func TestV55_DefectRepo_Delete(t *testing.T) {
	db := setupV55TestDB(t)
	defect := createTestDefectForV55(db, model.DefectStatusFixing)

	repo := &model.DefectRepo{
		DefectID:  defect.ID,
		ProjectID: 1,
		RepoURL:   "https://github.com/test/repo.git",
		Branch:    "main",
		LocalPath: "/tmp/bug-agent-v55-test-nonexistent",
		Status:    "active",
	}
	db.Create(repo)

	handler := NewRepoHandler(db)
	router := setupV55Router(db)
	router.DELETE("/defects/:id/repos/:repoId", handler.DeleteDefectRepo)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("DELETE", "/defects/"+uintToStr(defect.ID)+"/repos/"+uintToStr(repo.ID), nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var updated model.DefectRepo
	db.First(&updated, repo.ID)
	assert.Equal(t, "deleted", updated.Status)
	assert.NotNil(t, updated.DeletedAt)
}

func TestV55_DefectRepo_CleanupOrphaned(t *testing.T) {
	db := setupV55TestDB(t)

	oldTime := time.Now().Add(-48 * time.Hour)
	repo := &model.DefectRepo{
		DefectID:  999,
		ProjectID: 1,
		RepoURL:   "https://github.com/test/old.git",
		LocalPath: "/tmp/bug-agent-v55-test-nonexistent-old",
		Status:    "active",
		CreatedAt: oldTime,
	}
	db.Create(repo)

	var orphaned []model.DefectRepo
	cutoff := time.Now().Add(-24 * time.Hour)
	db.Where("status = ? AND created_at < ?", "active", cutoff).Find(&orphaned)
	assert.Len(t, orphaned, 1)

	now := time.Now()
	db.Model(&model.DefectRepo{}).Where("id = ?", repo.ID).Updates(map[string]interface{}{
		"status":     "deleted",
		"deleted_at": now,
	})

	var updated model.DefectRepo
	db.First(&updated, repo.ID)
	assert.Equal(t, "deleted", updated.Status)
}

// ============ FR-2: SSE Broker ============

func TestV55_SSE_Broker_PublishSubscribe(t *testing.T) {
	broker := sse.NewBroker()
	ch := broker.Subscribe([]string{"defect:1"})

	broker.Publish("defect:1", sse.SSEEvent{
		Event: "defect:status_changed",
		Data:  map[string]interface{}{"defectId": 1, "newStatus": "analyzing"},
	})

	select {
	case event := <-ch:
		assert.Equal(t, "defect:status_changed", event.Event)
	case <-time.After(1 * time.Second):
		t.Fatal("timeout waiting for event")
	}

	broker.Unsubscribe(ch)
}

func TestV55_SSE_Broker_RoomFiltering(t *testing.T) {
	broker := sse.NewBroker()
	ch1 := broker.Subscribe([]string{"defect:1"})
	ch2 := broker.Subscribe([]string{"defect:2"})

	broker.Publish("defect:1", sse.SSEEvent{Event: "test", Data: "for-1"})

	select {
	case <-ch1:
	default:
		t.Fatal("ch1 should receive event")
	}

	select {
	case <-ch2:
		t.Fatal("ch2 should NOT receive event for defect:1")
	default:
	}

	broker.Unsubscribe(ch1)
	broker.Unsubscribe(ch2)
}

func TestV55_SSE_Broker_MultipleRooms(t *testing.T) {
	broker := sse.NewBroker()
	ch := broker.Subscribe([]string{"defect:1", "defect:2"})

	broker.Publish("defect:1", sse.SSEEvent{Event: "e1", Data: "d1"})
	broker.Publish("defect:2", sse.SSEEvent{Event: "e2", Data: "d2"})

	count := 0
	timeout := time.After(1 * time.Second)
	for count < 2 {
		select {
		case <-ch:
			count++
		case <-timeout:
			t.Fatalf("only received %d events, expected 2", count)
		}
	}

	broker.Unsubscribe(ch)
}

func TestV55_SSE_NotifyService_NilSafe(t *testing.T) {
	var ns *sse.NotifyService
	assert.NotPanics(t, func() { ns.NotifyAnalysisStarted(1, []string{"frontend"}) })
	assert.NotPanics(t, func() { ns.NotifyDefectStatusChanged(1, "new", "analyzing") })
	assert.NotPanics(t, func() { ns.NotifyFixTaskCompleted(1, "http://pr") })
}

// ============ FR-5: MCP Server & Skills ============

func TestV55_MCPServer_CRUD(t *testing.T) {
	db := setupV55TestDB(t)
	handler := NewMCPServerHandler(db)
	router := setupV55Router(db)

	router.POST("/projects/:id/mcp-servers", func(c *gin.Context) {
		c.Set("userID", uint(1))
		handler.Create(c)
	})
	router.GET("/projects/:id/mcp-servers", handler.List)
	router.PATCH("/projects/:id/mcp-servers/:serverId/toggle", handler.Toggle)
	router.DELETE("/projects/:id/mcp-servers/:serverId", handler.Delete)

	createBody, _ := json.Marshal(map[string]string{
		"name":    "test-mcp",
		"command": "mcp-server",
		"args":    `["--port", "8080"]`,
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/projects/1/mcp-servers", bytes.NewBuffer(createBody))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)
	assert.Equal(t, 200, w.Code)

	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", "/projects/1/mcp-servers", nil)
	router.ServeHTTP(w, req)
	assert.Equal(t, 200, w.Code)

	var listResp struct {
		Data []model.ProjectMCPServer `json:"data"`
	}
	json.Unmarshal(w.Body.Bytes(), &listResp)
	assert.Len(t, listResp.Data, 1)
	assert.Equal(t, "test-mcp", listResp.Data[0].Name)
	assert.True(t, listResp.Data[0].Enabled)

	serverID := listResp.Data[0].ID

	w = httptest.NewRecorder()
	req, _ = http.NewRequest("PATCH", "/projects/1/mcp-servers/"+uintToStr(serverID)+"/toggle", nil)
	router.ServeHTTP(w, req)
	assert.Equal(t, 200, w.Code)

	w = httptest.NewRecorder()
	req, _ = http.NewRequest("DELETE", "/projects/1/mcp-servers/"+uintToStr(serverID), nil)
	router.ServeHTTP(w, req)
	assert.Equal(t, 200, w.Code)
}

func TestV55_Skill_CRUD(t *testing.T) {
	db := setupV55TestDB(t)
	handler := NewSkillHandler(db)
	router := setupV55Router(db)

	router.POST("/projects/:id/skills", func(c *gin.Context) {
		c.Set("userID", uint(1))
		handler.Create(c)
	})
	router.GET("/projects/:id/skills", handler.List)
	router.DELETE("/projects/:id/skills/:skillId", handler.Delete)

	createBody, _ := json.Marshal(map[string]string{
		"name":             "custom-frontend",
		"agentType":        "frontend",
		"instruction":      "Focus on React components",
		"tools":            `["search_code","read_file"]`,
		"mcpServerIds":     "[]",
		"memoryCategories": `["architecture","convention"]`,
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/projects/1/skills", bytes.NewBuffer(createBody))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)
	assert.Equal(t, 200, w.Code)

	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", "/projects/1/skills", nil)
	router.ServeHTTP(w, req)
	assert.Equal(t, 200, w.Code)

	var listResp struct {
		Data []model.ProjectAgentSkill `json:"data"`
	}
	json.Unmarshal(w.Body.Bytes(), &listResp)
	assert.Len(t, listResp.Data, 1)
	assert.Equal(t, "custom-frontend", listResp.Data[0].Name)
	assert.Equal(t, "frontend", listResp.Data[0].AgentType)
	assert.False(t, listResp.Data[0].IsDefault)

	skillID := listResp.Data[0].ID

	w = httptest.NewRecorder()
	req, _ = http.NewRequest("DELETE", "/projects/1/skills/"+uintToStr(skillID), nil)
	router.ServeHTTP(w, req)
	assert.Equal(t, 200, w.Code)
}

func TestV55_Skill_DefaultCannotDelete(t *testing.T) {
	db := setupV55TestDB(t)

	skill := &model.ProjectAgentSkill{
		ProjectID: 1, Name: "default-frontend", AgentType: "frontend",
		IsDefault: true, Enabled: true,
	}
	db.Create(skill)

	handler := NewSkillHandler(db)
	router := setupV55Router(db)
	router.DELETE("/projects/:id/skills/:skillId", handler.Delete)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("DELETE", "/projects/1/skills/"+uintToStr(skill.ID), nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 400, w.Code)
}

// ============ Helpers ============

func uintToStr(n uint) string {
	return fmt.Sprintf("%d", n)
}

func findSummary(data []struct {
	ConsumptionType  string `json:"consumptionType"`
	TotalTokens      int    `json:"totalTokens"`
	EstimatedCostUSD float64 `json:"estimatedCostUsd"`
	CallCount        int    `json:"callCount"`
}, consumptionType string) *struct {
	ConsumptionType  string `json:"consumptionType"`
	TotalTokens      int    `json:"totalTokens"`
	EstimatedCostUSD float64 `json:"estimatedCostUsd"`
	CallCount        int    `json:"callCount"`
} {
	for i := range data {
		if data[i].ConsumptionType == consumptionType {
			return &data[i]
		}
	}
	return nil
}
