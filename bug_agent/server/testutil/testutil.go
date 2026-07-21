package testutil

import (
	"bug-agent/internal/asyncx"
	"bug-agent/internal/model"
	"fmt"
	"log"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

var (
	baseDB      *gorm.DB
	migrateOnce sync.Once
	schemaOnce  sync.Once
	secretOnce  sync.Once
	testSchema  string
)

func getTestDSN() string {
	host := envOr("TEST_DB_HOST", "localhost")
	port := envOr("TEST_DB_PORT", "5432")
	user := envOr("TEST_DB_USER", "postgres")
	password := envOr("TEST_DB_PASSWORD", "changeme")
	dbname := envOr("TEST_DB_NAME", "hi_claw_test")
	schema := getTestSchema()

	return fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s search_path=%s sslmode=disable",
		host, port, user, password, dbname, schema)
}

func getTestSchema() string {
	schemaOnce.Do(func() {
		// Allow explicit override for CI/debug scenarios.
		if v := os.Getenv("TEST_DB_SCHEMA"); v != "" {
			testSchema = sanitizeSchemaName(v)
			return
		}

		// Use process-isolated schema by default so parallel package test runs
		// do not wipe each other's data via shared truncation.
		testSchema = fmt.Sprintf("bug_agent_test_%d", os.Getpid())
	})
	return testSchema
}

func sanitizeSchemaName(s string) string {
	if s == "" {
		return "public"
	}
	var b strings.Builder
	for _, ch := range strings.ToLower(s) {
		switch {
		case ch >= 'a' && ch <= 'z':
			b.WriteRune(ch)
		case ch >= '0' && ch <= '9':
			b.WriteRune(ch)
		case ch == '_':
			b.WriteRune(ch)
		default:
			b.WriteByte('_')
		}
	}
	out := b.String()
	if out == "" {
		return "public"
	}
	if out[0] >= '0' && out[0] <= '9' {
		out = "s_" + out
	}
	return out
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// SetupTestDB creates a PostgreSQL test environment.
// Uses TRUNCATE-based cleanup (no transactions) to avoid deadlocks
// with background goroutines (audit batch writer, RBAC cache cleanup).
func SetupTestDB(t testing.TB) *gorm.DB {
	t.Helper()
	secretOnce.Do(ensureTestSecrets)
	_ = asyncx.Wait(15 * time.Second)

	migrateOnce.Do(func() {
		var err error
		baseDB, err = gorm.Open(postgres.Open(getTestDSN()), &gorm.Config{
			Logger:                 logger.Default.LogMode(logger.Silent),
			SkipDefaultTransaction: true,
		})
		if err != nil {
			log.Fatalf("Failed to connect test database: %v", err)
		}

		if err := baseDB.Exec(fmt.Sprintf("DROP SCHEMA IF EXISTS %s CASCADE", getTestSchema())).Error; err != nil {
			log.Fatalf("Failed to reset test schema %q: %v", getTestSchema(), err)
		}
		if err := baseDB.Exec(fmt.Sprintf("CREATE SCHEMA %s", getTestSchema())).Error; err != nil {
			log.Fatalf("Failed to create test schema %q: %v", getTestSchema(), err)
		}

		err = baseDB.AutoMigrate(
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
			&model.IterationRepo{},
			&model.Defect{},
			&model.Attachment{},
			&model.Comment{},
			&model.AnalysisReport{},
			&model.FixTaskGroup{},
			&model.FixTask{},
			&model.ProjectRepo{},
			&model.RepoCredential{},
			&model.PlatformCredentialProject{},
			&model.NotificationPreference{},
			&model.UserWebhookSetting{},
			&model.ProjectWebhook{},
			&model.ProjectNotificationPolicy{},
			&model.PlatformSetting{},
			&model.InviteCode{},
			&model.ProjectAIConfig{},
			&model.AIProviderCatalog{},
			&model.AIModelCatalog{},
			&model.CollaborationTask{},
			&model.CollaborationReport{},
			&model.Role{},
			&model.Permission{},
			&model.RolePermission{},
			&model.UserRole{},
			&model.AuditLog{},
			&model.StatusChange{},
			&model.Notification{},
			&model.NotificationTemplate{},
			&model.PRRejection{},
			&model.AgentMemory{},
		)
		if err != nil {
			log.Fatalf("Failed to migrate test database: %v", err)
		}
	})

	truncateAllTables(baseDB)

	model.DB = baseDB

	return baseDB
}

func ensureTestSecrets() {
	if strings.TrimSpace(os.Getenv("CREDENTIAL_ENCRYPT_KEY")) == "" {
		_ = os.Setenv("CREDENTIAL_ENCRYPT_KEY", "0123456789abcdef0123456789abcdef")
	}
	if strings.TrimSpace(os.Getenv("AI_CONFIG_ENCRYPTION_KEY")) == "" {
		_ = os.Setenv("AI_CONFIG_ENCRYPTION_KEY", "abcdef0123456789abcdef0123456789")
	}
	if strings.TrimSpace(os.Getenv("INVITE_CODE_SIGN_KEY")) == "" {
		_ = os.Setenv("INVITE_CODE_SIGN_KEY", "0123456789abcdef0123456789abcdefSIGN")
	}
	if strings.TrimSpace(os.Getenv("BUG_AGENT_TEST_MODE")) == "" {
		_ = os.Setenv("BUG_AGENT_TEST_MODE", "1")
	}
	if strings.TrimSpace(os.Getenv("BUG_AGENT_DISABLE_BACKGROUND_WORKERS")) == "" {
		_ = os.Setenv("BUG_AGENT_DISABLE_BACKGROUND_WORKERS", "1")
	}
}

func truncateAllTables(db *gorm.DB) {
	tables := []string{
		"notification_templates", "notifications",
		"audit_logs", "user_roles", "role_permissions", "status_changes",
		"pr_rejections", "agent_memories",
		"collaboration_reports", "collaboration_tasks",
		"external_sync_records", "app_releases", "issue_routing_rules", "project_modules",
		"issue_triage_records", "issue_signals", "issue_clusters", "integration_sync_records", "integration_connectors",
		"attachments", "comments", "analysis_reports", "fix_tasks", "fix_task_groups",
		"project_ai_configs", "ai_model_catalog", "ai_provider_catalog", "platform_credential_projects", "repo_credentials", "notification_preferences", "user_webhook_settings", "project_notification_policies", "project_webhooks", "platform_settings", "invite_codes", "project_repos", "iteration_repos",
		"iterations", "defects",
		"project_members",
		"permissions", "roles",
		"users", "projects",
	}
	quoted := make([]string, 0, len(tables))
	for _, table := range tables {
		quoted = append(quoted, fmt.Sprintf(`"%s"`, table))
	}

	// Use one TRUNCATE in a short-timeout transaction to avoid long blocking
	// cleanup when other tests briefly hold row/table locks.
	tx := db.Begin()
	if tx.Error != nil {
		return
	}
	defer func() {
		if r := recover(); r != nil {
			tx.Rollback()
			panic(r)
		}
	}()

	_ = tx.Exec("SET LOCAL lock_timeout = '3s'").Error
	_ = tx.Exec("SET LOCAL statement_timeout = '15s'").Error

	sql := fmt.Sprintf("TRUNCATE TABLE %s RESTART IDENTITY CASCADE", strings.Join(quoted, ", "))
	if err := tx.Exec(sql).Error; err != nil {
		tx.Rollback()
		return
	}

	_ = tx.Commit().Error
}

// CreateTestUser creates a test user in the database
func CreateTestUser(t testing.TB, db *gorm.DB, username string) model.User {
	t.Helper()

	user := model.User{
		Username: username,
		Email:    username + "@test.com",
		Password: "hashed_password",
		Nickname: "Test " + username,
	}
	if err := db.Create(&user).Error; err != nil {
		t.Fatalf("Failed to create test user: %v", err)
	}
	return user
}

// CreateTestDefect creates a test defect with required FK dependencies
func CreateTestDefect(t testing.TB, db *gorm.DB, title string, reporterID uint) model.Defect {
	t.Helper()

	projectCode := "TP" + strings.ReplaceAll(title, "-", "_")
	if len(projectCode) > 20 {
		projectCode = projectCode[:20]
	}
	project := CreateTestProject(
		t,
		db,
		"proj_"+strings.ReplaceAll(title, "-", "_"),
		projectCode,
	)

	now := time.Now()
	iteration := model.Iteration{
		Name:      "iter_" + strings.ReplaceAll(title, "-", "_"),
		ProjectID: project.ID,
		Status:    "active",
		StartDate: now,
		EndDate:   now.Add(14 * 24 * time.Hour),
	}
	db.Create(&iteration)

	defectCode := "DEF-" + strings.ReplaceAll(title, "-", "_")
	if len(defectCode) > 50 {
		defectCode = defectCode[:50]
	}

	defect := model.Defect{
		Code:        defectCode,
		Title:       title,
		Severity:    "normal",
		Priority:    "P1",
		Type:        "functional",
		Status:      model.DefectStatusPendingAnalysis,
		ReporterID:  reporterID,
		IterationID: iteration.ID,
	}
	if err := db.Create(&defect).Error; err != nil {
		t.Fatalf("Failed to create test defect: %v", err)
	}
	return defect
}

// CreateTestProject creates a project for tests.
func CreateTestProject(t testing.TB, db *gorm.DB, name, code string) model.Project {
	t.Helper()

	project := model.Project{Name: name, Code: code, Status: "active"}
	if err := db.Create(&project).Error; err != nil {
		t.Fatalf("Failed to create test project: %v", err)
	}
	return project
}

// CreateTestRoles creates default roles and permissions for testing
func CreateTestRoles(t testing.TB, db *gorm.DB) map[string]model.Role {
	t.Helper()

	roles := []model.Role{
		{Name: "super_admin", DisplayName: "Super Admin", IsSystem: true},
		{Name: "developer", DisplayName: "Developer", IsSystem: true},
		{Name: "tester", DisplayName: "Tester", IsSystem: true},
		{Name: "viewer", DisplayName: "Viewer", IsSystem: true},
	}

	for i := range roles {
		if err := db.Create(&roles[i]).Error; err != nil {
			t.Fatalf("Failed to create role: %v", err)
		}
	}

	perms := []model.Permission{
		{Code: "defects:create", Name: "Create Defect", Module: "defects"},
		{Code: "defects:read", Name: "Read Defect", Module: "defects"},
		{Code: "defects:update", Name: "Update Defect", Module: "defects"},
		{Code: "agents:analyze", Name: "Trigger Analysis", Module: "agents"},
		{Code: "fix_tasks:create", Name: "Create Fix Task", Module: "fixes"},
		{Code: "users:read", Name: "Read Users", Module: "users"},
	}

	for i := range perms {
		if err := db.Create(&perms[i]).Error; err != nil {
			t.Fatalf("Failed to create permission: %v", err)
		}
	}

	rolePerms := []model.RolePermission{
		{RoleID: roles[0].ID, PermissionID: perms[0].ID},
		{RoleID: roles[0].ID, PermissionID: perms[1].ID},
		{RoleID: roles[0].ID, PermissionID: perms[2].ID},
		{RoleID: roles[0].ID, PermissionID: perms[3].ID},
		{RoleID: roles[0].ID, PermissionID: perms[4].ID},
		{RoleID: roles[0].ID, PermissionID: perms[5].ID},
		{RoleID: roles[1].ID, PermissionID: perms[0].ID},
		{RoleID: roles[1].ID, PermissionID: perms[1].ID},
		{RoleID: roles[1].ID, PermissionID: perms[3].ID},
		{RoleID: roles[2].ID, PermissionID: perms[1].ID},
		{RoleID: roles[3].ID, PermissionID: perms[1].ID},
	}
	for i := range rolePerms {
		if err := db.Create(&rolePerms[i]).Error; err != nil {
			t.Fatalf("Failed to create role-permission mapping: %v", err)
		}
	}

	roleMap := make(map[string]model.Role)
	for _, r := range roles {
		roleMap[r.Name] = r
	}

	return roleMap
}

// AssignRoleToUser assigns a role to a user
func AssignRoleToUser(t testing.TB, db *gorm.DB, userID uint, roleName string, roleMap map[string]model.Role) {
	t.Helper()

	role, ok := roleMap[roleName]
	if !ok {
		t.Fatalf("Role not found: %s", roleName)
	}

	userRole := model.UserRole{
		UserID:    userID,
		RoleID:    role.ID,
		ScopeType: "global",
	}
	if err := db.Create(&userRole).Error; err != nil {
		t.Fatalf("Failed to assign role: %v", err)
	}
}

func init() {
	log.SetOutput(os.Stderr)
}
