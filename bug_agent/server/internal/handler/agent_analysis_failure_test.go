package handler

import (
	"bug-agent/internal/adk"
	"bug-agent/internal/config"
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestAgentHandler_TriggerAnalysis_FallsBackWhenAllModelsFail(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	analysisSvc, err := adk.NewADKAnalysisService(db)
	if err != nil {
		t.Fatalf("create ADK analysis service: %v", err)
	}
	h := NewAgentHandler(db, analysisSvc, nil)

	prevMode := config.C.Server.Mode
	config.C.Server.Mode = "debug"
	defer func() {
		config.C.Server.Mode = prevMode
	}()

	reporter := testutil.CreateTestUser(t, db, "agent_failure_reporter")
	defect := testutil.CreateTestDefect(t, db, "agent-analysis-failure", reporter.ID)
	db.Model(&defect).Update("status", model.DefectStatusPendingAnalysis)

	var iteration model.Iteration
	if err := db.First(&iteration, defect.IterationID).Error; err != nil {
		t.Fatalf("load iteration failed: %v", err)
	}

	aiConfig := model.ProjectAIConfig{
		ProjectID:   iteration.ProjectID,
		Provider:    "mock-fail",
		ModelName:   "forced-failure",
		APIKey:      "",
		APIEndpoint: "",
		IsDefault:   true,
	}
	if err := db.Create(&aiConfig).Error; err != nil {
		t.Fatalf("create ai config failed: %v", err)
	}

	router.POST("/agents/analyze", h.TriggerAnalysis)

	body, _ := json.Marshal(map[string]any{
		"defectId":   defect.ID,
		"agentTypes": []string{"frontend"},
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/agents/analyze", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code, w.Body.String())

	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		var updated model.Defect
		if err := db.First(&updated, defect.ID).Error; err != nil {
			t.Fatalf("reload defect failed: %v", err)
		}

		var comments []model.Comment
		if err := db.Where("defect_id = ?", defect.ID).Order("id desc").Find(&comments).Error; err != nil {
			t.Fatalf("load comments failed: %v", err)
		}

		if updated.Status == model.DefectStatusPendingFix {
			var reports []model.AnalysisReport
			if err := db.Where("defect_id = ?", defect.ID).Order("id desc").Find(&reports).Error; err != nil {
				t.Fatalf("load reports failed: %v", err)
			}
			for _, report := range reports {
				if report.Status == "completed_fallback" {
					assert.Equal(t, "rule-based", report.Provider)
					assert.True(t, report.FallbackUsed)
					assert.Contains(t, report.ErrorMessage, "mock AI analysis failure triggered")
					return
				}
			}
			for _, comment := range comments {
				if strings.Contains(comment.Content, "已触发fallback") {
					assert.Contains(t, comment.Content, "mock AI analysis failure triggered")
					return
				}
			}
		}

		time.Sleep(50 * time.Millisecond)
	}

	var finalDefect model.Defect
	_ = db.First(&finalDefect, defect.ID).Error

	var finalComments []model.Comment
	_ = db.Where("defect_id = ?", defect.ID).Order("id desc").Find(&finalComments).Error

	t.Fatalf("analysis fallback not observed, final status=%s comments=%d defect=%s", finalDefect.Status, len(finalComments), strconv.FormatUint(uint64(defect.ID), 10))
}
