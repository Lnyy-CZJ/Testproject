package handler

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestDefectHandler_RecommendEndpoints(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	h := NewDefectHandler(model.DB)

	reporter := testutil.CreateTestUser(t, db, "recommend_reporter")
	assigneeA := testutil.CreateTestUser(t, db, "recommend_a")
	assigneeB := testutil.CreateTestUser(t, db, "recommend_b")

	project := testutil.CreateTestProject(t, db, "Recommend Project", "RECCMD")
	now := time.Now()
	iteration := model.Iteration{
		ProjectID: project.ID,
		Name:      "Sprint 1",
		Status:    "active",
		StartDate: now,
		EndDate:   now.AddDate(0, 0, 14),
	}
	assert.NoError(t, db.Create(&iteration).Error)
	assert.NoError(t, db.Create(&model.ProjectMember{ProjectID: project.ID, UserID: assigneeA.ID, Role: "developer"}).Error)
	assert.NoError(t, db.Create(&model.ProjectMember{ProjectID: project.ID, UserID: assigneeB.ID, Role: "tester"}).Error)

	defect := model.Defect{
		Code:        "BUG-RECCMD-202604-001",
		IterationID: iteration.ID,
		Title:       "推荐接口测试",
		Description: "验证推荐负责人与推荐 AGENT",
		Severity:    model.SeverityMajor,
		Priority:    model.PriorityP1,
		Type:        model.DefectTypeUI,
		Status:      model.DefectStatusPendingAssign,
		ReporterID:  reporter.ID,
	}
	assert.NoError(t, db.Create(&defect).Error)

	historyDefect := model.Defect{
		Code:        "BUG-RECCMD-202604-002",
		IterationID: iteration.ID,
		Title:       "历史样本",
		Description: "UI 历史处理",
		Severity:    model.SeverityNormal,
		Priority:    model.PriorityP2,
		Type:        model.DefectTypeUI,
		Status:      model.DefectStatusCompleted,
		ReporterID:  reporter.ID,
		AssigneeID:  &assigneeA.ID,
	}
	assert.NoError(t, db.Create(&historyDefect).Error)

	router.GET("/defects/:id/recommend-assignees", h.RecommendAssignees)
	router.GET("/defects/:id/recommend-agents", h.RecommendAgents)

	t.Run("recommend assignees returns candidates", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, "/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/recommend-assignees", nil)
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code, w.Body.String())
		var payload struct {
			Code int `json:"code"`
			Data struct {
				List []map[string]interface{} `json:"list"`
			} `json:"data"`
		}
		assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &payload))
		assert.GreaterOrEqual(t, len(payload.Data.List), 1)
	})

	t.Run("recommend agents returns candidates", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodGet, "/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/recommend-agents", nil)
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code, w.Body.String())
		var payload struct {
			Code int `json:"code"`
			Data struct {
				List []map[string]interface{} `json:"list"`
			} `json:"data"`
		}
		assert.NoError(t, json.Unmarshal(w.Body.Bytes(), &payload))
		assert.GreaterOrEqual(t, len(payload.Data.List), 1)
	})
}
