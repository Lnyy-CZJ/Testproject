// @title BugAgent API
// @version 1.4.0
// @description AI-powered defect management platform with multi-agent collaboration
// @host localhost:8765
// @BasePath /api/v1
// @securityDefinitions.apikey BearerAuth
// @in header
// @name Authorization

package main

import (
	"bug-agent/internal/asyncx"
	cachepkg "bug-agent/internal/cache"
	"bug-agent/internal/config"
	"bug-agent/internal/database"
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/internal/retrieval"
	"bug-agent/internal/router"
	"bug-agent/internal/service"
	"bug-agent/internal/sse"
	"bug-agent/pkg/logger"
	"context"
	"crypto/rand"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	// 加载配置
	config.Init()
	validateRequiredSecrets()

	// 初始化数据库
	database.Init()

	// 初始化 Redis
	cachepkg.Init()

	// 设置全局DB（解决循环依赖）
	model.SetDB(database.DB)

	// 自动迁移（建表）
	database.AutoMigrate(migrationModels()...)
	applySchemaFixes()

	// 预置RBAC角色权限数据（必须在AutoMigrate之后）
	middleware.SeedRBACData(database.DB)

	// 预置 AI 目录数据（仅目录为空时初始化）
	if err := model.SeedDefaultAICatalog(database.DB); err != nil {
		logger.Errorf("seed default AI catalog failed: %v", err)
	}
	if err := retrieval.SeedDefaultPlugins(database.DB); err != nil {
		logger.Errorf("seed default retriever plugins failed: %v", err)
	}

	// 创建性能优化索引（幂等操作，已存在则跳过）
	createPerformanceIndexes()

	// 创建默认管理员（仅首次运行）
	createDefaultAdmin()

	// 初始化 SSE Broker
	sse.InitBroker()

	// 启动限流器清理
	middleware.StartRateLimitCleanup()
	service.StartRepoCleanupLoop(asyncx.ShutdownContext(), database.DB)

	// 启动服务
	r := router.Setup()

	srv := &http.Server{
		Addr:    ":" + config.C.Server.Port,
		Handler: r,
	}

	go func() {
		logger.Infof("Server starting on :%s", config.C.Server.Port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Errorf("Server failed: %v", err)
			os.Exit(1)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	logger.Info("Shutting down server...")

	asyncx.TriggerShutdown()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		logger.Errorf("Server forced shutdown: %v", err)
	}
	logger.Info("Server exited")
}

func migrationModels() []interface{} {
	return []interface{}{
		&model.User{},
		&model.Project{},
		&model.ProjectMember{},
		&model.IntegrationConnector{},      // v5.0 P5A: 连接器
		&model.IntegrationSyncRecord{},     // v5.0 P5A: 接入同步记录
		&model.ProjectModule{},             // v5.0 P5B预留: 项目模块
		&model.IssueRoutingRule{},          // v5.0 P5B预留: 路由规则
		&model.AppRelease{},                // v5.0 P5B预留: 发布版本
		&model.ExternalSyncRecord{},        // v5.0 P5C预留: 外部回写记录
		&model.RegressionItem{},            // v5.0 P5C: 回归预防项
		&model.IssueCluster{},              // v5.0 P5A: 问题簇
		&model.IssueSignal{},               // v5.0 P5A: 问题信号
		&model.IssueTriageRecord{},         // v5.0 P5A: 分诊记录
		&model.ProjectRepo{},               // v1.1新增
		&model.RepoCredential{},            // v2.0 P2-1新增
		&model.PlatformCredentialProject{}, // v4.0 P2新增
		&model.NotificationPreference{},    // v2.0 P3-2新增
		&model.UserWebhookSetting{},        // v4.0 P4新增
		&model.ProjectWebhook{},            // v4.0 P3新增
		&model.ProjectNotificationPolicy{}, // v4.0 P3新增
		&model.PlatformSetting{},           // v4.0 P4新增
		&model.InviteCode{},                // v2.0 P5新增
		&model.ProjectAIConfig{},           // v1.1新增
		&model.AIProviderCatalog{},         // v3.0 P1: AI目录
		&model.AIModelCatalog{},            // v3.0 P1: AI目录
		&model.Iteration{},
		&model.IterationRepo{},
		&model.Defect{},
		&model.Attachment{},
		&model.CollaborationTask{},   // 多AGENT协作任务
		&model.CollaborationReport{}, // 多AGENT协作报告
		&model.FixTaskGroup{},        // 多仓库修复聚合任务
		&model.FixTask{},
		&model.DefectRepo{}, // v5.5: 缺陷仓库隔离
		&model.AnalysisReport{},
		&model.Comment{},
		&model.Role{},                 // Sprint 3: RBAC
		&model.Permission{},           // Sprint 3: RBAC
		&model.RolePermission{},       // Sprint 3: RBAC
		&model.UserRole{},             // Sprint 3: RBAC
		&model.AuditLog{},             // Sprint 3: 审计日志
		&model.StatusChange{},         // Sprint 4: Workflow state machine
		&model.Notification{},         // Sprint 4: Notification system
		&model.NotificationTemplate{}, // Sprint 4: Notification templates
		&model.PRRejection{},          // v5.4: PR拒绝记录
		&model.AgentMemory{},          // v5.4: Agent记忆
		&model.ProjectMCPServer{},     // v5.5: MCP服务器
		&model.ProjectAgentSkill{},    // v5.5: Agent技能
		&model.AITokenUsage{},         // v5.5: Token统计
		&model.RetrieverPlugin{},      // v5.6: Retriever插件
	}
}

func validateRequiredSecrets() {
	s := config.C.Secrets
	if len(s.CredentialEncryptKey) != 32 {
		log.Fatal("secrets.credential_encrypt_key must be 32 characters")
	}
	if s.CredentialEncryptKey == "0123456789abcdef0123456789abcdef" {
		log.Fatal("secrets.credential_encrypt_key must not use the default value")
	}
	if len(s.AIConfigEncryptionKey) != 32 {
		log.Fatal("secrets.ai_config_encryption_key must be 32 characters")
	}
	if s.AIConfigEncryptionKey == "0123456789abcdef0123456789abcdef" {
		log.Fatal("secrets.ai_config_encryption_key must not use the default value")
	}
	if len(s.InviteCodeSignKey) < 32 {
		log.Fatal("secrets.invite_code_sign_key must be at least 32 characters")
	}
	if s.InviteCodeSignKey == "0123456789abcdef0123456789abcdef" {
		log.Fatal("secrets.invite_code_sign_key must not use the default value")
	}
	if len(config.C.JWT.Secret) < 16 {
		log.Fatal("jwt.secret must be at least 16 characters")
	}
}

func createDefaultAdmin() {
	var count int64
	model.DB.Model(&model.User{}).Count(&count)
	if count > 0 {
		return
	}

	password := config.C.Server.AdminPassword
	if password == "" {
		password = generateRandomPassword(16)
		logger.Infof("Generated admin password - check server logs or set ADMIN_PASSWORD env var")
	}

	hashed, err := model.HashPassword(password)
	if err != nil {
		log.Fatal("failed to hash admin password: ", err)
	}
	admin := model.User{
		Username:     "admin",
		Email:        "admin@bug-agent.com",
		Password:     hashed,
		Nickname:     "系统管理员",
		AgentTypes:   "product,ui,frontend,client,backend,test",
		PlatformRole: "super_admin",
	}
	if err := model.DB.Create(&admin).Error; err != nil {
		logger.Errorf("Create failed: %v", err)
	}
}

func generateRandomPassword(length int) string {
	const charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%"
	b := make([]byte, length)
	randBytes := make([]byte, length)
	_, err := rand.Read(randBytes)
	if err != nil {
		log.Fatal("failed to generate random password")
	}
	for i := range b {
		b[i] = charset[int(randBytes[i])%len(charset)]
	}
	return string(b)
}

func createPerformanceIndexes() {
	indexes := []string{
		"CREATE INDEX IF NOT EXISTS idx_defects_iteration_status ON defects(iteration_id, status)",
		"CREATE INDEX IF NOT EXISTS idx_defects_iteration_created ON defects(iteration_id, created_at)",
		"CREATE INDEX IF NOT EXISTS idx_defects_iteration_status_created ON defects(iteration_id, status, created_at DESC)",
		"CREATE INDEX IF NOT EXISTS idx_defects_assignee ON defects(assignee_id)",
		"CREATE INDEX IF NOT EXISTS idx_defects_reporter ON defects(reporter_id)",
		"CREATE INDEX IF NOT EXISTS idx_defects_severity ON defects(severity)",
		"CREATE INDEX IF NOT EXISTS idx_defects_status ON defects(status)",
		"CREATE INDEX IF NOT EXISTS idx_defects_created_at ON defects(created_at)",
		"CREATE INDEX IF NOT EXISTS idx_project_members_user_project ON project_members(user_id, project_id)",
		"CREATE INDEX IF NOT EXISTS idx_project_members_project_user ON project_members(project_id, user_id)",
		"CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, \"read\")",
		"CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_logs(user_id, created_at)",
		"CREATE INDEX IF NOT EXISTS idx_credential_user ON repo_credentials(user_id)",
		"CREATE INDEX IF NOT EXISTS idx_credential_scope_status ON repo_credentials(scope, status)",
		"CREATE INDEX IF NOT EXISTS idx_integration_connector_project_status ON integration_connectors(project_id, status)",
		"CREATE INDEX IF NOT EXISTS idx_integration_connector_type_status ON integration_connectors(type, status)",
		"CREATE INDEX IF NOT EXISTS idx_issue_signal_project_status_seen ON issue_signals(project_id, triage_status, last_seen_at DESC)",
		"CREATE INDEX IF NOT EXISTS idx_issue_signal_connector_event ON issue_signals(connector_id, source_event_id)",
		"CREATE INDEX IF NOT EXISTS idx_issue_signal_cluster_seen ON issue_signals(cluster_id, last_seen_at DESC)",
		"CREATE INDEX IF NOT EXISTS idx_issue_cluster_project_status_seen ON issue_clusters(project_id, status, last_seen_at DESC)",
		"CREATE INDEX IF NOT EXISTS idx_issue_cluster_project_defect ON issue_clusters(project_id, linked_defect_id)",
		"CREATE INDEX IF NOT EXISTS idx_integration_sync_connector_created ON integration_sync_records(connector_id, created_at DESC)",
		"CREATE INDEX IF NOT EXISTS idx_project_modules_project_code ON project_modules(project_id, code)",
		"CREATE INDEX IF NOT EXISTS idx_app_releases_project_version ON app_releases(project_id, platform, app_version, build_number)",
		"CREATE INDEX IF NOT EXISTS idx_external_sync_entity_target ON external_sync_records(entity_type, entity_id, target_type)",
		"CREATE INDEX IF NOT EXISTS idx_platform_credential_project_lookup ON platform_credential_projects(project_id, credential_id)",
		"CREATE INDEX IF NOT EXISTS idx_notif_pref_user ON notification_preferences(user_id, category)",
		"CREATE INDEX IF NOT EXISTS idx_project_webhooks_project_enabled ON project_webhooks(project_id, enabled)",
		"CREATE INDEX IF NOT EXISTS idx_project_notification_policies_project_category ON project_notification_policies(project_id, category)",
		"CREATE INDEX IF NOT EXISTS idx_platform_settings_key ON platform_settings(setting_key)",
		"CREATE INDEX IF NOT EXISTS idx_collab_tasks_status_updated ON collaboration_tasks(status, updated_at DESC)",
		"CREATE INDEX IF NOT EXISTS idx_collab_tasks_defect_created ON collaboration_tasks(defect_id, created_at DESC)",
		"CREATE INDEX IF NOT EXISTS idx_collab_reports_task_status ON collaboration_reports(task_id, status)",
		"CREATE INDEX IF NOT EXISTS idx_collab_reports_report_id ON collaboration_reports(report_id)",
		"CREATE INDEX IF NOT EXISTS idx_comments_defect_created ON comments(defect_id, created_at)",
		"CREATE INDEX IF NOT EXISTS idx_iterations_project_status ON iterations(project_id, status)",
		"CREATE INDEX IF NOT EXISTS idx_status_changes_defect_created ON status_changes(defect_id, created_at)",
		"CREATE INDEX IF NOT EXISTS idx_routing_rules_project_sort ON issue_routing_rules(project_id, sort_order)",
		"CREATE INDEX IF NOT EXISTS idx_ai_model_catalog_provider_name ON ai_model_catalog(provider_key, model_name)",
		"CREATE INDEX IF NOT EXISTS idx_agent_memories_created_by ON agent_memories(created_by)",
		"CREATE INDEX IF NOT EXISTS idx_analysis_reports_defect_agent_created ON analysis_reports(defect_id, agent_type, created_at DESC)",
		"CREATE INDEX IF NOT EXISTS idx_fix_tasks_defect_status ON fix_tasks(defect_id, status)",
	}
	for _, sql := range indexes {
		if err := model.DB.Exec(sql).Error; err != nil {
			logger.Errorf("createPerformanceIndexes: failed SQL=%q err=%v", sql, err)
		}
	}
}

func applySchemaFixes() {
	statements := []string{
		"ALTER TABLE issue_signals ALTER COLUMN connector_id DROP NOT NULL",
	}
	for _, sql := range statements {
		if err := model.DB.Exec(sql).Error; err != nil {
			logger.Errorf("applySchemaFixes: failed SQL=%q err=%v", sql, err)
		}
	}
}
