package handler

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestFixTaskHandler_ListFixTaskGroups_ReturnsGroupsWithUnits(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	reporter := testutil.CreateTestUser(t, db, "fix_group_handler_reporter")
	defect := testutil.CreateTestDefect(t, db, "fix-group-handler", reporter.ID)

	group := model.FixTaskGroup{
		TaskCode: "FT-GROUP-001",
		DefectID: defect.ID,
		Status:   model.FixTaskStatusExecuting,
	}
	if err := db.Create(&group).Error; err != nil {
		t.Fatalf("create group failed: %v", err)
	}
	var iteration model.Iteration
	if err := db.First(&iteration, defect.IterationID).Error; err != nil {
		t.Fatalf("query iteration failed: %v", err)
	}
	projectRepo := model.ProjectRepo{
		ProjectID:     iteration.ProjectID,
		Name:          "backend",
		RepoURL:       "https://example.com/backend.git",
		AgentTypes:    "backend",
		DefaultBranch: "main",
	}
	if err := db.Create(&projectRepo).Error; err != nil {
		t.Fatalf("create project repo failed: %v", err)
	}

	unit := model.FixTask{
		GroupID:       &group.ID,
		TaskCode:      "FT-GROUP-001-BE",
		DefectID:      defect.ID,
		AgentType:     "backend",
		ProjectRepoID: &projectRepo.ID,
		Status:        model.FixTaskStatusPlanning,
	}
	if err := db.Create(&unit).Error; err != nil {
		t.Fatalf("create unit failed: %v", err)
	}

	h := NewFixTaskHandler(db, nil)
	router := gin.New()
	router.GET("/defects/:id/fix-task-groups", h.ListFixTaskGroups)

	req := httptest.NewRequest(http.MethodGet, "/defects/1/fix-task-groups", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var payload struct {
		Code int `json:"code"`
		Data struct {
			Items []model.FixTaskGroup `json:"items"`
			Total int64                `json:"total"`
		} `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &payload); err != nil {
		t.Fatalf("unmarshal response failed: %v", err)
	}
	if payload.Code != 0 {
		t.Fatalf("expected code 0, got %d", payload.Code)
	}
	if payload.Data.Total != 1 || len(payload.Data.Items) != 1 {
		t.Fatalf("expected one group, got total=%d len=%d", payload.Data.Total, len(payload.Data.Items))
	}
	if len(payload.Data.Items[0].Units) != 1 {
		t.Fatalf("expected one unit, got %d", len(payload.Data.Items[0].Units))
	}
	if payload.Data.Items[0].Units[0].AgentType != "backend" {
		t.Fatalf("expected backend unit, got %s", payload.Data.Items[0].Units[0].AgentType)
	}
	if payload.Data.Items[0].Units[0].ProjectRepo.ID != projectRepo.ID {
		t.Fatalf("expected project repo %d, got %d", projectRepo.ID, payload.Data.Items[0].Units[0].ProjectRepo.ID)
	}
}
