package handler

import (
	"bytes"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/model"

	"github.com/gin-gonic/gin"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestProjectHandler_UpdateIterationRepoBranchUsesIterRepoIDParam(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	if err := db.AutoMigrate(&model.Project{}, &model.Iteration{}, &model.ProjectRepo{}, &model.IterationRepo{}); err != nil {
		t.Fatalf("migrate db: %v", err)
	}

	project := model.Project{Name: "BugAgent", Code: "BUG", Status: "active"}
	if err := db.Create(&project).Error; err != nil {
		t.Fatalf("create project: %v", err)
	}
	iteration := model.Iteration{ProjectID: project.ID, Name: "Sprint"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration: %v", err)
	}
	projectRepo := model.ProjectRepo{
		ProjectID:     project.ID,
		Name:          "bug_agent",
		RepoURL:       "https://example.com/bug_agent.git",
		SourceType:    "custom",
		AgentTypes:    "backend",
		DefaultBranch: "main",
	}
	if err := db.Create(&projectRepo).Error; err != nil {
		t.Fatalf("create project repo: %v", err)
	}
	repoID := projectRepo.ID
	iterRepo := model.IterationRepo{IterationID: iteration.ID, RepoID: &repoID, Branch: ""}
	if err := db.Create(&iterRepo).Error; err != nil {
		t.Fatalf("create iteration repo: %v", err)
	}

	r := gin.New()
	h := NewProjectHandler(db)
	r.PUT("/projects/:id/iterations/:iterationId/repos/:iterRepoId/branch", h.UpdateIterationRepoBranch)

	path := fmt.Sprintf("/projects/%d/iterations/%d/repos/%d/branch", project.ID, iteration.ID, iterRepo.ID)
	req, _ := http.NewRequest(http.MethodPut, path, bytes.NewBufferString(`{"branch":"codex/test"}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var updated model.IterationRepo
	if err := db.First(&updated, iterRepo.ID).Error; err != nil {
		t.Fatalf("load updated iteration repo: %v", err)
	}
	if updated.Branch != "codex/test" {
		t.Fatalf("branch = %q, want codex/test", updated.Branch)
	}
}
