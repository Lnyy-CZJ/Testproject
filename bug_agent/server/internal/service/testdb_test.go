package service_test

import (
	"os"
	"strings"
	"testing"

	"bug-agent/internal/model"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

func setupServiceTestDB(t *testing.T) *gorm.DB {
	t.Helper()

	_ = os.Setenv("CREDENTIAL_ENCRYPT_KEY", "0123456789abcdef0123456789abcdef")
	_ = os.Setenv("AI_CONFIG_ENCRYPTION_KEY", "abcdef0123456789abcdef0123456789")
	_ = os.Setenv("INVITE_CODE_SIGN_KEY", "0123456789abcdef0123456789abcdefSIGN")

	dsn := "file:" + strings.ReplaceAll(t.Name(), "/", "_") + "?mode=memory&cache=shared"
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		t.Fatalf("open sqlite db failed: %v", err)
	}

	if err := db.Exec("PRAGMA foreign_keys = ON").Error; err != nil {
		t.Fatalf("enable sqlite foreign keys failed: %v", err)
	}

	if err := db.AutoMigrate(
		&model.User{},
		&model.Project{},
		&model.ProjectMember{},
		&model.IntegrationConnector{},
		&model.IntegrationSyncRecord{},
		&model.ProjectModule{},
		&model.IssueRoutingRule{},
		&model.AppRelease{},
		&model.ExternalSyncRecord{},
		&model.RegressionItem{},
		&model.IssueCluster{},
		&model.IssueSignal{},
		&model.IssueTriageRecord{},
		&model.Iteration{},
		&model.Defect{},
		&model.Comment{},
	); err != nil {
		t.Fatalf("auto migrate sqlite db failed: %v", err)
	}

	model.DB = db
	return db
}
