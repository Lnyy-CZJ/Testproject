package adk

import (
	"context"
	"strings"
	"testing"
	"time"

	bugmodel "bug-agent/internal/model"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func TestCancelAnalysisMovesAnalyzingDefectBackToPendingAnalysis(t *testing.T) {
	db := setupAnalysisCancelTestDB(t)
	reporter := bugmodel.User{Username: "cancel_analysis_reporter", Email: "cancel_analysis_reporter@test.com", Password: "hashed_password"}
	if err := db.Create(&reporter).Error; err != nil {
		t.Fatalf("create reporter failed: %v", err)
	}
	project := bugmodel.Project{Name: "cancel_project", Code: "CANCEL", Status: "active"}
	if err := db.Create(&project).Error; err != nil {
		t.Fatalf("create project failed: %v", err)
	}
	now := time.Now()
	iteration := bugmodel.Iteration{Name: "cancel_iteration", ProjectID: project.ID, Status: "active", StartDate: now, EndDate: now.Add(24 * time.Hour)}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}
	defect := bugmodel.Defect{
		Code:        "DEF-CANCEL",
		Title:       "cancel-analysis-defect",
		Severity:    "normal",
		Priority:    "P1",
		Type:        "functional",
		Status:      bugmodel.DefectStatusAnalyzing,
		ReporterID:  reporter.ID,
		IterationID: iteration.ID,
	}
	if err := db.Create(&defect).Error; err != nil {
		t.Fatalf("create defect failed: %v", err)
	}

	svc := &ADKAnalysisService{db: db, runningCtxs: make(map[uint]context.CancelFunc)}
	ctx, cancel := context.WithCancel(context.Background())
	svc.runningCtxs[defect.ID] = cancel

	if !svc.CancelAnalysis(defect.ID) {
		t.Fatal("expected running analysis to be cancelled")
	}
	select {
	case <-ctx.Done():
	default:
		t.Fatal("expected running context to be cancelled")
	}

	var updated bugmodel.Defect
	if err := db.First(&updated, defect.ID).Error; err != nil {
		t.Fatalf("reload defect failed: %v", err)
	}
	if updated.Status != bugmodel.DefectStatusPendingAnalysis {
		t.Fatalf("cancelled analysis status = %q, want %q", updated.Status, bugmodel.DefectStatusPendingAnalysis)
	}
}

func setupAnalysisCancelTestDB(t *testing.T) *gorm.DB {
	t.Helper()

	dsn := "file:" + strings.ReplaceAll(t.Name(), "/", "_") + "?mode=memory&cache=shared"
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		t.Fatalf("open sqlite db failed: %v", err)
	}
	if err := db.AutoMigrate(&bugmodel.User{}, &bugmodel.Project{}, &bugmodel.Iteration{}, &bugmodel.Defect{}); err != nil {
		t.Fatalf("auto migrate sqlite db failed: %v", err)
	}
	return db
}
