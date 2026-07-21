package service

import (
	"bug-agent/internal/model"
	"testing"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestSelectIterationProjectRepoRejectsMismatchedAgentType(t *testing.T) {
	db := newRepoResolverTestDB(t)

	project := model.Project{Name: "Repo Resolver", Code: "RR", Status: "active"}
	if err := db.Create(&project).Error; err != nil {
		t.Fatalf("create project failed: %v", err)
	}
	iteration := model.Iteration{ProjectID: project.ID, Name: "v1", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}
	repo := model.ProjectRepo{
		ProjectID:     project.ID,
		Name:          "frontend",
		RepoURL:       "https://example.com/frontend.git",
		SourceType:    "custom",
		AgentTypes:    "frontend",
		DefaultBranch: "main",
	}
	if err := db.Create(&repo).Error; err != nil {
		t.Fatalf("create repo failed: %v", err)
	}
	if err := db.Create(&model.IterationRepo{IterationID: iteration.ID, RepoID: &repo.ID, Branch: "main"}).Error; err != nil {
		t.Fatalf("create iteration repo failed: %v", err)
	}

	_, _, ok := selectIterationProjectRepo(db, iteration.ID, "backend")
	if ok {
		t.Fatal("expected no repository when the iteration repo does not match agent type")
	}
}

func TestResolveDefectProjectRepoForReportPrefersAffectedFileRepoPrefix(t *testing.T) {
	db := newRepoResolverTestDB(t)

	project := model.Project{Name: "Repo Resolver", Code: "RR", Status: "active"}
	if err := db.Create(&project).Error; err != nil {
		t.Fatalf("create project failed: %v", err)
	}
	iteration := model.Iteration{ProjectID: project.ID, Name: "v1", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}
	defect := model.Defect{
		Code:        "BUG-RR-001",
		Title:       "multi backend repos",
		ReporterID:  1,
		IterationID: iteration.ID,
	}

	apiRepo := model.ProjectRepo{ProjectID: project.ID, Name: "api", RepoURL: "https://example.com/api.git", SourceType: "custom", AgentTypes: "backend", DefaultBranch: "main"}
	adminRepo := model.ProjectRepo{ProjectID: project.ID, Name: "admin", RepoURL: "https://example.com/admin.git", SourceType: "custom", AgentTypes: "backend", DefaultBranch: "main"}
	if err := db.Create(&apiRepo).Error; err != nil {
		t.Fatalf("create api repo failed: %v", err)
	}
	if err := db.Create(&adminRepo).Error; err != nil {
		t.Fatalf("create admin repo failed: %v", err)
	}
	if err := db.Create(&model.IterationRepo{IterationID: iteration.ID, RepoID: &apiRepo.ID, Branch: "main"}).Error; err != nil {
		t.Fatalf("bind api repo failed: %v", err)
	}
	if err := db.Create(&model.IterationRepo{IterationID: iteration.ID, RepoID: &adminRepo.ID, Branch: "release/admin"}).Error; err != nil {
		t.Fatalf("bind admin repo failed: %v", err)
	}

	report := model.AnalysisReport{
		AgentType: "backend",
		Status:    model.AnalysisStatusCompleted,
		Analysis:  `{"affectedFiles":["admin/internal/router.go"],"solution":{"steps":[{"filePath":"admin/internal/router.go","action":"fix"}]}}`,
	}

	selected, branch, err := ResolveDefectProjectRepoForReport(db, defect, "backend", report)
	if err != nil {
		t.Fatalf("ResolveDefectProjectRepoForReport failed: %v", err)
	}
	if selected.ID != adminRepo.ID {
		t.Fatalf("expected admin repo %d, got %d", adminRepo.ID, selected.ID)
	}
	if branch != "release/admin" {
		t.Fatalf("expected iteration branch release/admin, got %s", branch)
	}
}

func TestResolveDefectProjectRepoForReportPrefersExplicitRepoHint(t *testing.T) {
	db := newRepoResolverTestDB(t)

	project := model.Project{Name: "Repo Resolver", Code: "RR", Status: "active"}
	if err := db.Create(&project).Error; err != nil {
		t.Fatalf("create project failed: %v", err)
	}
	iteration := model.Iteration{ProjectID: project.ID, Name: "v1", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}
	defect := model.Defect{Code: "BUG-RR-002", Title: "repo hint", ReporterID: 1, IterationID: iteration.ID}

	apiRepo := model.ProjectRepo{ProjectID: project.ID, Name: "api", RepoURL: "https://example.com/api.git", SourceType: "custom", AgentTypes: "backend", DefaultBranch: "main"}
	adminRepo := model.ProjectRepo{ProjectID: project.ID, Name: "admin", RepoURL: "https://example.com/admin.git", SourceType: "custom", AgentTypes: "backend", DefaultBranch: "main"}
	if err := db.Create(&apiRepo).Error; err != nil {
		t.Fatalf("create api repo failed: %v", err)
	}
	if err := db.Create(&adminRepo).Error; err != nil {
		t.Fatalf("create admin repo failed: %v", err)
	}

	report := model.AnalysisReport{
		AgentType: "backend",
		Status:    model.AnalysisStatusCompleted,
		Analysis:  `{"affectedFiles":[{"repoHint":"admin","path":"internal/router.go"}],"solution":{"steps":[{"repoHint":"admin","filePath":"internal/router.go","action":"fix"}]}}`,
	}

	selected, _, err := ResolveDefectProjectRepoForReport(db, defect, "backend", report)
	if err != nil {
		t.Fatalf("ResolveDefectProjectRepoForReport failed: %v", err)
	}
	if selected.ID != adminRepo.ID {
		t.Fatalf("expected admin repo %d, got %d", adminRepo.ID, selected.ID)
	}
}

func TestResolveDefectProjectReposForReportReturnsEveryMatchedRepo(t *testing.T) {
	db := newRepoResolverTestDB(t)

	project := model.Project{Name: "Repo Resolver", Code: "RR-MULTI", Status: "active"}
	if err := db.Create(&project).Error; err != nil {
		t.Fatalf("create project failed: %v", err)
	}
	iteration := model.Iteration{ProjectID: project.ID, Name: "v1", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}
	defect := model.Defect{Code: "BUG-RR-003", Title: "multi repo report", ReporterID: 1, IterationID: iteration.ID}

	apiRepo := model.ProjectRepo{ProjectID: project.ID, Name: "api", RepoURL: "https://example.com/api.git", SourceType: "custom", AgentTypes: "backend", DefaultBranch: "main"}
	adminRepo := model.ProjectRepo{ProjectID: project.ID, Name: "admin", RepoURL: "https://example.com/admin.git", SourceType: "custom", AgentTypes: "backend", DefaultBranch: "main"}
	if err := db.Create(&apiRepo).Error; err != nil {
		t.Fatalf("create api repo failed: %v", err)
	}
	if err := db.Create(&adminRepo).Error; err != nil {
		t.Fatalf("create admin repo failed: %v", err)
	}

	report := model.AnalysisReport{
		AgentType: "backend",
		Status:    model.AnalysisStatusCompleted,
		Analysis:  `{"affectedFiles":["api/internal/server.go","admin/internal/router.go"],"solution":{"steps":[{"filePath":"api/internal/server.go"},{"filePath":"admin/internal/router.go"}]}}`,
	}

	repos, err := ResolveDefectProjectReposForReport(db, defect, "backend", report)
	if err != nil {
		t.Fatalf("ResolveDefectProjectReposForReport failed: %v", err)
	}
	if len(repos) != 2 {
		t.Fatalf("expected 2 repos, got %d", len(repos))
	}
	if repos[0].repo.ID != apiRepo.ID || repos[1].repo.ID != adminRepo.ID {
		t.Fatalf("expected api/admin repos, got %d/%d", repos[0].repo.ID, repos[1].repo.ID)
	}
}

func TestResolveDefectProjectReposForReportKeepsOnlyBestScoredRepo(t *testing.T) {
	db := newRepoResolverTestDB(t)

	project := model.Project{Name: "Repo Resolver", Code: "RR-BEST", Status: "active"}
	if err := db.Create(&project).Error; err != nil {
		t.Fatalf("create project failed: %v", err)
	}
	iteration := model.Iteration{ProjectID: project.ID, Name: "v1", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}
	defect := model.Defect{Code: "BUG-RR-004", Title: "best repo match", ReporterID: 1, IterationID: iteration.ID}

	apiRepo := model.ProjectRepo{ProjectID: project.ID, Name: "api", RepoURL: "https://example.com/api.git", SourceType: "custom", AgentTypes: "backend", DefaultBranch: "main"}
	apiAdminRepo := model.ProjectRepo{ProjectID: project.ID, Name: "api-admin", RepoURL: "https://example.com/api-admin.git", SourceType: "custom", AgentTypes: "backend", DefaultBranch: "main"}
	if err := db.Create(&apiRepo).Error; err != nil {
		t.Fatalf("create api repo failed: %v", err)
	}
	if err := db.Create(&apiAdminRepo).Error; err != nil {
		t.Fatalf("create api-admin repo failed: %v", err)
	}

	report := model.AnalysisReport{
		AgentType: "backend",
		Status:    model.AnalysisStatusCompleted,
		Analysis:  `{"affectedFiles":[{"repoHint":"api","path":"internal/server.go"}],"solution":{"steps":[{"repoHint":"api","filePath":"internal/server.go"}]}}`,
	}

	repos, err := ResolveDefectProjectReposForReport(db, defect, "backend", report)
	if err != nil {
		t.Fatalf("ResolveDefectProjectReposForReport failed: %v", err)
	}
	if len(repos) != 1 {
		t.Fatalf("expected one best repo, got %d", len(repos))
	}
	if repos[0].repo.ID != apiRepo.ID {
		t.Fatalf("expected api repo %d, got %d", apiRepo.ID, repos[0].repo.ID)
	}
}

func TestResolveDefectProjectReposForReportRejectsAmbiguousUnmatchedFiles(t *testing.T) {
	db := newRepoResolverTestDB(t)

	project := model.Project{Name: "Repo Resolver", Code: "RR-AMBIG", Status: "active"}
	if err := db.Create(&project).Error; err != nil {
		t.Fatalf("create project failed: %v", err)
	}
	iteration := model.Iteration{ProjectID: project.ID, Name: "v1", Status: "active"}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}
	defect := model.Defect{Code: "BUG-RR-005", Title: "ambiguous repo", ReporterID: 1, IterationID: iteration.ID}

	apiRepo := model.ProjectRepo{ProjectID: project.ID, Name: "api", RepoURL: "https://example.com/api.git", SourceType: "custom", AgentTypes: "backend", DefaultBranch: "main"}
	adminRepo := model.ProjectRepo{ProjectID: project.ID, Name: "admin", RepoURL: "https://example.com/admin.git", SourceType: "custom", AgentTypes: "backend", DefaultBranch: "main"}
	if err := db.Create(&apiRepo).Error; err != nil {
		t.Fatalf("create api repo failed: %v", err)
	}
	if err := db.Create(&adminRepo).Error; err != nil {
		t.Fatalf("create admin repo failed: %v", err)
	}

	report := model.AnalysisReport{
		AgentType: "backend",
		Status:    model.AnalysisStatusCompleted,
		Analysis:  `{"affectedFiles":["internal/server.go"],"solution":{"steps":[{"filePath":"internal/server.go"}]}}`,
	}

	_, err := ResolveDefectProjectReposForReport(db, defect, "backend", report)
	if err == nil {
		t.Fatal("expected ambiguous unmatched file paths to be rejected")
	}
}

func newRepoResolverTestDB(t *testing.T) *gorm.DB {
	t.Helper()

	db, err := gorm.Open(sqlite.Open("file:"+t.Name()+"?mode=memory&cache=shared"), &gorm.Config{})
	if err != nil {
		t.Fatalf("open sqlite failed: %v", err)
	}
	if err := db.AutoMigrate(&model.Project{}, &model.Iteration{}, &model.ProjectRepo{}, &model.IterationRepo{}); err != nil {
		t.Fatalf("migrate failed: %v", err)
	}
	return db
}
