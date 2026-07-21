package service

import (
	"bug-agent/internal/git"
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestFixService_getDefect_LoadsIterationWithoutUnsupportedRelation(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_reporter")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-defect", reporter.ID)

	loaded, err := svc.getDefect(defect.ID)
	if err != nil {
		t.Fatalf("getDefect failed: %v", err)
	}
	if loaded.Iteration.ID == 0 {
		t.Fatalf("expected iteration to be preloaded")
	}
	if loaded.Iteration.ProjectID == 0 {
		t.Fatalf("expected iteration project id to be available")
	}
}

func TestFixService_getLatestAnalysisReport_PrefersMatchingAgentType(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_reporter_pref")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-report-pref", reporter.ID)

	backend := model.AnalysisReport{
		ReportCode: "AR-BACKEND",
		DefectID:   defect.ID,
		AgentType:  "backend",
		Status:     "completed",
		Analysis:   `{"affectedFiles":["server/app.go"],"solution":{"steps":[{"step":1,"action":"修复后端","filePath":"server/app.go"}]}}`,
		CreatedAt:  time.Now().Add(-time.Minute),
	}
	if err := db.Create(&backend).Error; err != nil {
		t.Fatalf("create backend report failed: %v", err)
	}

	fallback := model.AnalysisReport{
		ReportCode: "AR-TEST",
		DefectID:   defect.ID,
		AgentType:  "test",
		Status:     "completed_fallback",
		Analysis:   `{"affectedFiles":[],"solution":{"steps":[{"step":1,"action":"测试建议"}]}}`,
		CreatedAt:  time.Now(),
	}
	if err := db.Create(&fallback).Error; err != nil {
		t.Fatalf("create fallback report failed: %v", err)
	}

	report, err := svc.getLatestAnalysisReport(defect.ID, "backend")
	if err != nil {
		t.Fatalf("getLatestAnalysisReport failed: %v", err)
	}
	if report.ID != backend.ID {
		t.Fatalf("expected backend report %d, got %d", backend.ID, report.ID)
	}
}

func TestFixService_getLatestAnalysisReport_AutoSelectsLatestFixableReport(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_report_auto_select")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-report-auto-select", reporter.ID)

	frontendFallback := model.AnalysisReport{
		ReportCode: "AR-FRONTEND-FALLBACK",
		DefectID:   defect.ID,
		AgentType:  "frontend",
		Status:     "completed_fallback",
		Analysis:   `{"affectedFiles":[],"solution":{"description":"manual only"}}`,
		CreatedAt:  time.Now(),
	}
	if err := db.Create(&frontendFallback).Error; err != nil {
		t.Fatalf("create frontend fallback report failed: %v", err)
	}

	backend := model.AnalysisReport{
		ReportCode: "AR-BACKEND-FIXABLE",
		DefectID:   defect.ID,
		AgentType:  "backend",
		Status:     model.AnalysisStatusCompleted,
		Analysis:   `{"affectedFiles":["server/app.go"],"solution":{"steps":[{"step":1,"action":"修复后端","filePath":"server/app.go"}]}}`,
		CreatedAt:  time.Now().Add(-time.Minute),
	}
	if err := db.Create(&backend).Error; err != nil {
		t.Fatalf("create backend report failed: %v", err)
	}

	report, err := svc.getLatestAnalysisReport(defect.ID, "")
	if err != nil {
		t.Fatalf("getLatestAnalysisReport failed: %v", err)
	}
	if report.ID != backend.ID {
		t.Fatalf("expected backend report %d, got %d", backend.ID, report.ID)
	}
}

func TestFixService_CreateAutoFixGroup_CreatesUnitForEachLatestFixableAgentReport(t *testing.T) {
	t.Setenv("BUG_AGENT_DISABLE_BACKGROUND_WORKERS", "1")
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_group_reporter")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-group", reporter.ID)
	var iteration model.Iteration
	if err := db.First(&iteration, defect.IterationID).Error; err != nil {
		t.Fatalf("query iteration failed: %v", err)
	}
	backendRepo := model.ProjectRepo{
		ProjectID:     iteration.ProjectID,
		Name:          "backend",
		RepoURL:       "https://example.com/backend.git",
		AgentTypes:    "backend",
		DefaultBranch: "main",
	}
	if err := db.Create(&backendRepo).Error; err != nil {
		t.Fatalf("create backend repo failed: %v", err)
	}
	frontendRepo := model.ProjectRepo{
		ProjectID:     iteration.ProjectID,
		Name:          "frontend",
		RepoURL:       "https://example.com/frontend.git",
		AgentTypes:    "frontend",
		DefaultBranch: "main",
	}
	if err := db.Create(&frontendRepo).Error; err != nil {
		t.Fatalf("create frontend repo failed: %v", err)
	}
	if err := db.Create(&model.IterationRepo{IterationID: iteration.ID, RepoID: &backendRepo.ID, Branch: "main"}).Error; err != nil {
		t.Fatalf("bind backend repo failed: %v", err)
	}
	if err := db.Create(&model.IterationRepo{IterationID: iteration.ID, RepoID: &frontendRepo.ID, Branch: "main"}).Error; err != nil {
		t.Fatalf("bind frontend repo failed: %v", err)
	}

	reports := []model.AnalysisReport{
		{
			ReportCode: "AR-GROUP-FRONTEND",
			DefectID:   defect.ID,
			AgentType:  "frontend",
			Status:     model.AnalysisStatusCompleted,
			Analysis:   `{"affectedFiles":["web/src/App.tsx"],"solution":{"steps":[{"step":1,"action":"修复前端","filePath":"web/src/App.tsx"}]}}`,
			CreatedAt:  time.Now().Add(-2 * time.Minute),
		},
		{
			ReportCode: "AR-GROUP-BACKEND",
			DefectID:   defect.ID,
			AgentType:  "backend",
			Status:     model.AnalysisStatusCompleted,
			Analysis:   `{"affectedFiles":["server/internal/router/router.go"],"solution":{"steps":[{"step":1,"action":"修复后端","filePath":"server/internal/router/router.go"}]}}`,
			CreatedAt:  time.Now().Add(-time.Minute),
		},
		{
			ReportCode: "AR-GROUP-BACKEND-OLD",
			DefectID:   defect.ID,
			AgentType:  "backend",
			Status:     model.AnalysisStatusCompleted,
			Analysis:   `{"affectedFiles":["server/old.go"],"solution":{"steps":[{"step":1,"action":"旧报告","filePath":"server/old.go"}]}}`,
			CreatedAt:  time.Now().Add(-3 * time.Minute),
		},
		{
			ReportCode: "AR-GROUP-TEST-FALLBACK",
			DefectID:   defect.ID,
			AgentType:  "test",
			Status:     "completed_fallback",
			Analysis:   `{"affectedFiles":[],"solution":{"description":"manual only"}}`,
			CreatedAt:  time.Now(),
		},
	}
	for _, report := range reports {
		if err := db.Create(&report).Error; err != nil {
			t.Fatalf("create report %s failed: %v", report.ReportCode, err)
		}
	}
	var frontendReport model.AnalysisReport
	if err := db.Where("report_code = ?", "AR-GROUP-FRONTEND").First(&frontendReport).Error; err != nil {
		t.Fatalf("query frontend report failed: %v", err)
	}
	var backendReport model.AnalysisReport
	if err := db.Where("report_code = ?", "AR-GROUP-BACKEND").First(&backendReport).Error; err != nil {
		t.Fatalf("query backend report failed: %v", err)
	}

	result, err := svc.CreateAutoFixGroup(context.Background(), FixRequest{
		DefectID:     defect.ID,
		TargetBranch: "main",
		UserID:       reporter.ID,
	})
	if err != nil {
		t.Fatalf("CreateAutoFixGroup failed: %v", err)
	}
	if result.GroupID == 0 {
		t.Fatal("expected group id")
	}
	if len(result.Units) != 2 {
		t.Fatalf("expected 2 units, got %d", len(result.Units))
	}

	var group model.FixTaskGroup
	if err := db.First(&group, result.GroupID).Error; err != nil {
		t.Fatalf("query group failed: %v", err)
	}
	if group.Status != model.FixTaskStatusPlanning {
		t.Fatalf("expected planning group, got %s", group.Status)
	}

	var tasks []model.FixTask
	if err := db.Where("group_id = ?", result.GroupID).Order("agent_type").Find(&tasks).Error; err != nil {
		t.Fatalf("query unit tasks failed: %v", err)
	}
	if len(tasks) != 2 {
		t.Fatalf("expected 2 unit tasks, got %d", len(tasks))
	}
	if tasks[0].AgentType != "backend" || tasks[1].AgentType != "frontend" {
		t.Fatalf("expected backend/frontend units, got %s/%s", tasks[0].AgentType, tasks[1].AgentType)
	}
	if tasks[0].AnalysisReportID == nil || *tasks[0].AnalysisReportID != backendReport.ID {
		t.Fatalf("backend unit should use latest backend report")
	}
	if tasks[0].ProjectRepoID == nil || *tasks[0].ProjectRepoID != backendRepo.ID {
		t.Fatalf("backend unit should bind backend repo")
	}
	if tasks[1].AnalysisReportID == nil || *tasks[1].AnalysisReportID != frontendReport.ID {
		t.Fatalf("frontend unit should use frontend report")
	}
	if tasks[1].ProjectRepoID == nil || *tasks[1].ProjectRepoID != frontendRepo.ID {
		t.Fatalf("frontend unit should bind frontend repo")
	}
}

func TestFixService_CreateAutoFixGroup_SplitsSingleAgentReportAcrossMatchedRepos(t *testing.T) {
	t.Setenv("BUG_AGENT_DISABLE_BACKGROUND_WORKERS", "1")
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_multi_repo_reporter")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-multi-repo", reporter.ID)
	var iteration model.Iteration
	if err := db.First(&iteration, defect.IterationID).Error; err != nil {
		t.Fatalf("query iteration failed: %v", err)
	}
	apiRepo := model.ProjectRepo{ProjectID: iteration.ProjectID, Name: "api", RepoURL: "https://example.com/api.git", AgentTypes: "backend", DefaultBranch: "main"}
	adminRepo := model.ProjectRepo{ProjectID: iteration.ProjectID, Name: "admin", RepoURL: "https://example.com/admin.git", AgentTypes: "backend", DefaultBranch: "main"}
	if err := db.Create(&apiRepo).Error; err != nil {
		t.Fatalf("create api repo failed: %v", err)
	}
	if err := db.Create(&adminRepo).Error; err != nil {
		t.Fatalf("create admin repo failed: %v", err)
	}

	report := model.AnalysisReport{
		ReportCode: "AR-GROUP-BACKEND-MULTI-REPO",
		DefectID:   defect.ID,
		AgentType:  "backend",
		Status:     model.AnalysisStatusCompleted,
		Analysis:   `{"affectedFiles":["api/internal/server.go","admin/internal/router.go"],"solution":{"steps":[{"step":1,"action":"修复 API","filePath":"api/internal/server.go"},{"step":2,"action":"修复 Admin","filePath":"admin/internal/router.go"}]}}`,
		CreatedAt:  time.Now(),
	}
	if err := db.Create(&report).Error; err != nil {
		t.Fatalf("create report failed: %v", err)
	}

	result, err := svc.CreateAutoFixGroup(context.Background(), FixRequest{DefectID: defect.ID, UserID: reporter.ID})
	if err != nil {
		t.Fatalf("CreateAutoFixGroup failed: %v", err)
	}
	if result.GroupID == 0 {
		t.Fatal("expected group id")
	}
	if len(result.Units) != 2 {
		t.Fatalf("expected 2 repo units, got %d", len(result.Units))
	}

	var tasks []model.FixTask
	if err := db.Where("group_id = ?", result.GroupID).Order("project_repo_id").Find(&tasks).Error; err != nil {
		t.Fatalf("query unit tasks failed: %v", err)
	}
	if len(tasks) != 2 {
		t.Fatalf("expected 2 unit tasks, got %d", len(tasks))
	}
	if tasks[0].AnalysisReportID == nil || *tasks[0].AnalysisReportID != report.ID || tasks[1].AnalysisReportID == nil || *tasks[1].AnalysisReportID != report.ID {
		t.Fatalf("both units should reference the same source report")
	}
	if tasks[0].ProjectRepoID == nil || tasks[1].ProjectRepoID == nil {
		t.Fatalf("units should bind project repos")
	}
	gotRepos := map[uint]bool{*tasks[0].ProjectRepoID: true, *tasks[1].ProjectRepoID: true}
	if !gotRepos[apiRepo.ID] || !gotRepos[adminRepo.ID] {
		t.Fatalf("expected units for api/admin repos, got %#v", gotRepos)
	}
}

func TestFixService_CreateAutoFixGroup_AlwaysCreatesGroupForSingleUnit(t *testing.T) {
	t.Setenv("BUG_AGENT_DISABLE_BACKGROUND_WORKERS", "1")
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_single_group_reporter")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-single-group", reporter.ID)
	var iteration model.Iteration
	if err := db.First(&iteration, defect.IterationID).Error; err != nil {
		t.Fatalf("query iteration failed: %v", err)
	}
	repo := model.ProjectRepo{ProjectID: iteration.ProjectID, Name: "backend", RepoURL: "https://example.com/backend.git", AgentTypes: "backend", DefaultBranch: "main"}
	if err := db.Create(&repo).Error; err != nil {
		t.Fatalf("create repo failed: %v", err)
	}
	report := model.AnalysisReport{
		ReportCode: "AR-GROUP-BACKEND-SINGLE",
		DefectID:   defect.ID,
		AgentType:  "backend",
		Status:     model.AnalysisStatusCompleted,
		Analysis:   `{"affectedFiles":["internal/router.go"],"solution":{"steps":[{"step":1,"action":"修复后端","filePath":"internal/router.go"}]}}`,
		CreatedAt:  time.Now(),
	}
	if err := db.Create(&report).Error; err != nil {
		t.Fatalf("create report failed: %v", err)
	}

	result, err := svc.CreateAutoFixGroup(context.Background(), FixRequest{DefectID: defect.ID, UserID: reporter.ID})
	if err != nil {
		t.Fatalf("CreateAutoFixGroup failed: %v", err)
	}
	if result.GroupID == 0 {
		t.Fatal("expected group id for single unit")
	}
	if len(result.Units) != 1 {
		t.Fatalf("expected one unit, got %d", len(result.Units))
	}
}

func TestFixService_getLatestAnalysisReport_RequiresCompletedAutoFixableReport(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_report_autofixable")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-report-autofixable", reporter.ID)

	reports := []model.AnalysisReport{
		{
			ReportCode: "AR-FAILED",
			DefectID:   defect.ID,
			AgentType:  "backend",
			Status:     model.AnalysisStatusFailed,
			Analysis:   `{"affectedFiles":["server/app.go"],"solution":{"steps":[{"action":"bad","filePath":"server/app.go"}]}}`,
			CreatedAt:  time.Now().Add(-3 * time.Minute),
		},
		{
			ReportCode: "AR-FALLBACK",
			DefectID:   defect.ID,
			AgentType:  "backend",
			Status:     "completed_fallback",
			Analysis:   `{"affectedFiles":[],"solution":{"description":"manual only"}}`,
			CreatedAt:  time.Now().Add(-2 * time.Minute),
		},
		{
			ReportCode: "AR-NOSTEPS",
			DefectID:   defect.ID,
			AgentType:  "backend",
			Status:     model.AnalysisStatusCompleted,
			Analysis:   `{"affectedFiles":["server/app.go"],"solution":{"description":"missing steps"}}`,
			CreatedAt:  time.Now().Add(-1 * time.Minute),
		},
		{
			ReportCode: "AR-GOOD",
			DefectID:   defect.ID,
			AgentType:  "backend",
			Status:     model.AnalysisStatusCompleted,
			Analysis:   `{"affectedFiles":["server/app.go"],"solution":{"steps":[{"action":"fix","filePath":"server/app.go"}]}}`,
			CreatedAt:  time.Now(),
		},
	}
	for _, report := range reports {
		if err := db.Create(&report).Error; err != nil {
			t.Fatalf("create report %s failed: %v", report.ReportCode, err)
		}
	}

	report, err := svc.getLatestAnalysisReport(defect.ID, "backend")
	if err != nil {
		t.Fatalf("getLatestAnalysisReport failed: %v", err)
	}
	if report.ReportCode != "AR-GOOD" {
		t.Fatalf("expected AR-GOOD, got %s", report.ReportCode)
	}
}

func TestFixService_getLatestAnalysisReport_ReturnsErrorWithoutAutoFixableReport(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_report_no_autofixable")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-report-no-autofixable", reporter.ID)

	report := model.AnalysisReport{
		ReportCode: "AR-FALLBACK-ONLY",
		DefectID:   defect.ID,
		AgentType:  "backend",
		Status:     "completed_fallback",
		Analysis:   `{"affectedFiles":[],"solution":{"description":"manual only"}}`,
		CreatedAt:  time.Now(),
	}
	if err := db.Create(&report).Error; err != nil {
		t.Fatalf("create fallback report failed: %v", err)
	}

	if _, err := svc.getLatestAnalysisReport(defect.ID, "backend"); err == nil {
		t.Fatal("expected no auto-fixable analysis report error")
	}
}

func TestBuildDefectRepoPath_DefaultsToWritableTempRoot(t *testing.T) {
	t.Setenv("BUG_AGENT_REPO_BASE_DIR", "")

	path := buildDefectRepoPath(102, 201, "https://example.com/org/repo.git")

	if !strings.HasPrefix(path, "/tmp/bug-agent/repos/defects/102/task-201/") {
		t.Fatalf("expected temp repo path, got %s", path)
	}
	if strings.HasPrefix(path, "/data/") {
		t.Fatalf("repo path should not default to read-only /data, got %s", path)
	}
}

func TestBuildDefectRepoPath_UsesConfiguredBaseDir(t *testing.T) {
	t.Setenv("BUG_AGENT_REPO_BASE_DIR", "/private/tmp/custom-bug-agent-repos")

	path := buildDefectRepoPath(103, 301, "https://example.com/org/repo.git")

	if !strings.HasPrefix(path, "/private/tmp/custom-bug-agent-repos/defects/103/task-301/") {
		t.Fatalf("expected configured repo path, got %s", path)
	}
}

func TestBuildDefectRepoPath_IsolatesTasksForSameDefectAndRepo(t *testing.T) {
	t.Setenv("BUG_AGENT_REPO_BASE_DIR", "/private/tmp/custom-bug-agent-repos")

	first := buildDefectRepoPath(103, 71, "https://example.com/org/repo.git")
	second := buildDefectRepoPath(103, 72, "https://example.com/org/repo.git")

	if first == second {
		t.Fatalf("expected task-isolated repo paths, both got %s", first)
	}
	if !strings.Contains(first, "/task-71/") || !strings.Contains(second, "/task-72/") {
		t.Fatalf("expected task ids in repo paths, got %s and %s", first, second)
	}
}

func TestFixService_finalizeFixSuccess_UpdatesDefectAndPlan(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_finalize_success")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-finalize-success", reporter.ID)
	if err := db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusFixing).Error; err != nil {
		t.Fatalf("update defect status failed: %v", err)
	}

	task := model.FixTask{
		TaskCode:  "FT-SUCCESS",
		DefectID:  defect.ID,
		AgentType: "backend",
		Status:    "planning",
		Plan:      `[{"step":1,"action":"old","status":"pending"}]`,
	}
	if err := db.Create(&task).Error; err != nil {
		t.Fatalf("create task failed: %v", err)
	}

	finalPlan := json.RawMessage(`[{"step":1,"action":"new","status":"completed"}]`)
	result := &FixResult{
		TaskCode:   task.TaskCode,
		Status:     "completed",
		PlanJSON:   finalPlan,
		ResultJSON: json.RawMessage(`{"commitHash":"abc123"}`),
		PRURL:      "https://example.com/pr/1",
	}

	if err := svc.finalizeFixSuccess(task.ID, defect.ID, result); err != nil {
		t.Fatalf("finalizeFixSuccess failed: %v", err)
	}

	var storedTask model.FixTask
	if err := db.First(&storedTask, task.ID).Error; err != nil {
		t.Fatalf("load task failed: %v", err)
	}
	if storedTask.Status != "completed" {
		t.Fatalf("task status = %s", storedTask.Status)
	}
	if storedTask.Plan != string(finalPlan) {
		t.Fatalf("task plan = %s", storedTask.Plan)
	}
	if storedTask.Result != `{"commitHash":"abc123"}` {
		t.Fatalf("task result = %s", storedTask.Result)
	}
	if storedTask.PRURL != "https://example.com/pr/1" {
		t.Fatalf("task pr url = %s", storedTask.PRURL)
	}
	if storedTask.CompletedAt == nil {
		t.Fatal("expected completed_at to be set")
	}

	var storedDefect model.Defect
	if err := db.First(&storedDefect, defect.ID).Error; err != nil {
		t.Fatalf("load defect failed: %v", err)
	}
	if storedDefect.Status != model.DefectStatusPendingVerify {
		t.Fatalf("defect status = %s", storedDefect.Status)
	}
}

func TestFixService_finalizeFixSuccess_AllowsCompletedWithWarnings(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_finalize_warning")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-finalize-warning", reporter.ID)
	if err := db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusFixing).Error; err != nil {
		t.Fatalf("update defect status failed: %v", err)
	}

	task := model.FixTask{
		TaskCode:  "FT-WARNING",
		DefectID:  defect.ID,
		AgentType: "backend",
		Status:    model.FixTaskStatusTesting,
	}
	if err := db.Create(&task).Error; err != nil {
		t.Fatalf("create task failed: %v", err)
	}

	result := &FixResult{
		TaskCode:   task.TaskCode,
		Status:     model.FixTaskStatusCompletedWithWarnings,
		ResultJSON: json.RawMessage(`{"buildVerification":{"skipped":true,"skipReason":"no_build_target"}}`),
	}

	if err := svc.finalizeFixSuccess(task.ID, defect.ID, result); err != nil {
		t.Fatalf("finalizeFixSuccess failed: %v", err)
	}

	var storedTask model.FixTask
	if err := db.First(&storedTask, task.ID).Error; err != nil {
		t.Fatalf("load task failed: %v", err)
	}
	if storedTask.Status != model.FixTaskStatusCompletedWithWarnings {
		t.Fatalf("task status = %s", storedTask.Status)
	}
	if storedTask.CompletedAt == nil {
		t.Fatal("expected completed_at to be set")
	}

	var storedDefect model.Defect
	if err := db.First(&storedDefect, defect.ID).Error; err != nil {
		t.Fatalf("load defect failed: %v", err)
	}
	if storedDefect.Status != model.DefectStatusPendingVerify {
		t.Fatalf("defect status = %s", storedDefect.Status)
	}
}

func TestFixService_finalizeFixFailure_PreservesPlanAndRollsBackDefect(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewFixService(db)

	reporter := testutil.CreateTestUser(t, db, "fix_engine_finalize_failure")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-finalize-failure", reporter.ID)
	if err := db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusFixing).Error; err != nil {
		t.Fatalf("update defect status failed: %v", err)
	}

	task := model.FixTask{
		TaskCode:  "FT-FAIL",
		DefectID:  defect.ID,
		AgentType: "backend",
		Status:    "planning",
		Plan:      `[{"step":1,"action":"old","status":"pending"}]`,
	}
	if err := db.Create(&task).Error; err != nil {
		t.Fatalf("create task failed: %v", err)
	}

	finalPlan := `[{"step":1,"action":"clone","status":"completed"},{"step":2,"action":"generate","status":"failed"}]`
	if err := db.Model(&model.FixTask{}).Where("id = ?", task.ID).Update("Plan", finalPlan).Error; err != nil {
		t.Fatalf("seed final plan failed: %v", err)
	}
	if err := db.Model(&model.FixTask{}).Where("id = ?", task.ID).Update("Result", `{"branch":"fix/bug","pushed":true}`).Error; err != nil {
		t.Fatalf("seed checkpoint result failed: %v", err)
	}

	if err := svc.finalizeFixFailure(task.ID, defect.ID, "boom"); err != nil {
		t.Fatalf("finalizeFixFailure failed: %v", err)
	}

	var storedTask model.FixTask
	if err := db.First(&storedTask, task.ID).Error; err != nil {
		t.Fatalf("load task failed: %v", err)
	}
	if storedTask.Status != "failed" {
		t.Fatalf("task status = %s", storedTask.Status)
	}
	if storedTask.Plan != finalPlan {
		t.Fatalf("task plan overwritten: %s", storedTask.Plan)
	}
	if !json.Valid([]byte(storedTask.Result)) {
		t.Fatalf("task result is not valid json: %s", storedTask.Result)
	}
	var resultPayload map[string]interface{}
	if err := json.Unmarshal([]byte(storedTask.Result), &resultPayload); err != nil {
		t.Fatalf("unmarshal task result failed: %v", err)
	}
	if resultPayload["branch"] != "fix/bug" || resultPayload["pushed"] != true {
		t.Fatalf("failure result should preserve checkpoint, got %#v", resultPayload)
	}
	if resultPayload["error"] != "boom" {
		t.Fatalf("failure result error = %#v", resultPayload["error"])
	}
	if storedTask.CompletedAt == nil {
		t.Fatal("expected completed_at to be set")
	}

	var storedDefect model.Defect
	if err := db.First(&storedDefect, defect.ID).Error; err != nil {
		t.Fatalf("load defect failed: %v", err)
	}
	if storedDefect.Status != model.DefectStatusPendingFix {
		t.Fatalf("defect status = %s", storedDefect.Status)
	}
}

func TestUpdateTaskFields_DoesNotOverwritePlanOrCompletedAt(t *testing.T) {
	db := testutil.SetupTestDB(t)
	reporter := testutil.CreateTestUser(t, db, "fix_engine_runtime_fields")
	defect := testutil.CreateTestDefect(t, db, "fix-engine-runtime-fields", reporter.ID)

	now := time.Now().Add(-time.Minute).UTC().Round(time.Microsecond)
	task := model.FixTask{
		TaskCode:     "FT-RUNTIME-UPDATES",
		DefectID:     defect.ID,
		AgentType:    "backend",
		Status:       "planning",
		Plan:         `[{"step":1,"status":"executing"}]`,
		CompletedAt:  &now,
		TargetBranch: "main",
	}
	if err := db.Create(&task).Error; err != nil {
		t.Fatalf("create task failed: %v", err)
	}

	UpdateTaskFields(db, task.ID, map[string]interface{}{
		"fix_branch":    "fix/test-branch",
		"target_branch": "develop",
	})

	var storedTask model.FixTask
	if err := db.First(&storedTask, task.ID).Error; err != nil {
		t.Fatalf("load task failed: %v", err)
	}
	if storedTask.Plan != `[{"step":1,"status":"executing"}]` {
		t.Fatalf("plan overwritten: %s", storedTask.Plan)
	}
	if storedTask.CompletedAt == nil || !storedTask.CompletedAt.Equal(now) {
		t.Fatalf("completed_at overwritten: %#v", storedTask.CompletedAt)
	}
	if storedTask.FixBranch != "fix/test-branch" {
		t.Fatalf("fix branch = %s", storedTask.FixBranch)
	}
	if storedTask.TargetBranch != "develop" {
		t.Fatalf("target branch = %s", storedTask.TargetBranch)
	}
}

func TestMarshalFixPlanSteps_UsesCurrentStatuses(t *testing.T) {
	steps := []map[string]interface{}{
		{"step": 1, "action": "clone", "status": "completed"},
		{"step": 2, "action": "generate", "status": "warning"},
	}

	planJSON := MarshalFixPlanSteps(steps)
	if !json.Valid(planJSON) {
		t.Fatalf("plan json invalid: %s", string(planJSON))
	}

	var decoded []map[string]interface{}
	if err := json.Unmarshal(planJSON, &decoded); err != nil {
		t.Fatalf("unmarshal plan json failed: %v", err)
	}
	if got := decoded[1]["status"]; got != "warning" {
		t.Fatalf("expected latest status warning, got %v", got)
	}
}

func TestBuildSkippedMessageDistinguishesMissingTool(t *testing.T) {
	message := buildSkippedMessage(&git.BuildResult{
		Skipped:    true,
		Success:    false,
		SkipReason: "missing_tool",
		Output:     `[.] build tool "npm" not found, skipped`,
	})

	if !strings.Contains(message, "missing build tool") {
		t.Fatalf("message = %q, want missing build tool", message)
	}
}

func TestBuildSkippedStepStatusFailsMissingTool(t *testing.T) {
	status := buildSkippedStepStatus(&git.BuildResult{
		Skipped:    true,
		Success:    false,
		SkipReason: "missing_tool",
	})

	if status != "failed" {
		t.Fatalf("status = %q, want failed", status)
	}
}

func TestResolveFinalFixStatusUsesWarnings(t *testing.T) {
	status := resolveFinalFixStatus([]map[string]interface{}{
		{"step": 1, "status": "completed"},
		{"step": 2, "status": "warning"},
	})

	if status != model.FixTaskStatusCompletedWithWarnings {
		t.Fatalf("status = %q, want %q", status, model.FixTaskStatusCompletedWithWarnings)
	}
}

func TestResolveTargetBranch(t *testing.T) {
	tests := []struct {
		name   string
		branch string
		want   string
	}{
		{name: "returns branch when provided", branch: "feat/x", want: "feat/x"},
		{name: "returns default when empty", branch: "", want: model.DefaultBranch},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := model.ResolveBranch(tt.branch)
			if got != tt.want {
				t.Fatalf("ResolveBranch(%q) = %q, want %q", tt.branch, got, tt.want)
			}
		})
	}
}
