package router

import (
	"bug-agent/internal/adk"
	"bug-agent/internal/asyncx"
	"bug-agent/internal/config"
	"bug-agent/internal/handler"
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/internal/retrieval"
	"bug-agent/internal/service"
	"bug-agent/internal/sse"
	"context"
	"fmt"
	"strings"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	swaggerFiles "github.com/swaggo/files"
	ginSwagger "github.com/swaggo/gin-swagger"
)

func Setup() *gin.Engine {
	r := gin.Default()

	db := model.DB

	var retrievers []retrieval.Retriever
	retrievers = append(retrievers, retrieval.NewKeywordRetriever())
	signalIngestService := service.NewSignalIngestService(db)

	adkAnalysisService, err := adk.NewADKAnalysisService(db)
	if err != nil {
		panic(fmt.Sprintf("Failed to init ADK analysis service: %v", err))
	}
	adk.InitRegistry()
	adkAnalysisService.SetRegistry(adk.GlobalRegistry)
	if len(config.C.MCP.Servers) > 0 {
		var mcpServers []adk.MCPServerConfig
		for _, srv := range config.C.MCP.Servers {
			var args []string
			if srv.Args != "" {
				args = strings.Split(srv.Args, " ")
			}
			mcpServers = append(mcpServers, adk.MCPServerConfig{
				Command: srv.Command,
				Args:    args,
			})
		}
		adkAnalysisService.SetMCPServers(mcpServers)
	}
	adkFixService, err := adk.NewADKFixService(db)
	if err != nil {
		panic(fmt.Sprintf("Failed to init ADK fix service: %v", err))
	}
	adkCollabService, err := adk.NewADKCollaborationService(db, adkAnalysisService)
	if err != nil {
		panic(fmt.Sprintf("Failed to init ADK collaboration service: %v", err))
	}

	scheduler := adk.NewAgentScheduler(3)
	scheduler.Start(asyncx.ShutdownContext(), func(ctx context.Context, task *adk.AnalysisTask) *adk.AnalysisResult {
		analysisReq := adk.ADKAnalysisRequest{
			DefectID:   task.DefectID,
			AgentTypes: task.AgentTypes,
		}
		_, err := adkAnalysisService.PerformAnalysis(ctx, analysisReq)
		return &adk.AnalysisResult{
			TaskID:   task.ID,
			DefectID: task.DefectID,
			Status:   analysisTaskStatusFromError(err),
			Error:    err,
		}
	})
	adkAnalysisService.SetScheduler(scheduler)

	agentHandler := handler.NewAgentHandler(db, adkAnalysisService, scheduler)
	fixHandler := handler.NewFixTaskHandler(db, adkFixService)
	collabHandler := handler.NewCollaborationHandler(db, adkCollabService)

	// Global middleware
	r.Use(middleware.RateLimitMiddleware())

	// Static file service removed — use authenticated /uploads/*filename endpoint below

	// CORS
	corsOrigins := config.C.Server.CorsOrigins
	if len(corsOrigins) == 0 {
		corsOrigins = []string{
			"http://localhost:3000",
			"http://127.0.0.1:3000",
			"http://localhost:5678",
			"http://127.0.0.1:5678",
			"http://localhost:5679",
			"http://127.0.0.1:5679",
			"http://localhost:5680",
			"http://127.0.0.1:5680",
			"http://localhost:5688",
			"http://127.0.0.1:5688",
		}
	}
	r.Use(cors.New(cors.Config{
		AllowOrigins:     corsOrigins,
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Authorization"},
		ExposeHeaders:    []string{"Content-Length"},
		AllowCredentials: true,
	}))

	// Health check endpoints (no auth required, before rate limit bypass)
	healthHandler := handler.NewHealthHandler()
	r.GET("/healthz", healthHandler.Healthz)
	r.GET("/readyz", healthHandler.Readiness)

	// Swagger API documentation (dev only)
	r.GET("/swagger/*any", ginSwagger.WrapHandler(swaggerFiles.Handler))

	api := r.Group("/api/v1")

	authHandler := handler.NewAuthHandler(db)

	// 公开路由
	auth := api.Group("/auth")
	{
		auth.POST("/register", authHandler.Register)
		auth.POST("/login", authHandler.Login)
	}

	inboundConnectorHandler := handler.NewInboundConnectorHandler(db, signalIngestService)
	api.POST("/inbound/connectors/:token", inboundConnectorHandler.Receive)

	// 邀请码公开接口（注册页使用）
	publicInviteHandler := handler.NewInviteHandler(db)
	publicInvites := api.Group("/invites")
	{
		publicInvites.POST("/:code/accept", publicInviteHandler.AcceptInvite)
		publicInvites.GET("/:code/validate", publicInviteHandler.ValidateInvite)
	}

	// SSE 实时通知（注册在authed组之外，token 通过 query 传递）
	sse.InitBroker()
	sse.InitNotifyService(sse.GlobalBroker)
	sseHandler := sse.NewSSEHandler(sse.GlobalBroker)
	api.GET("/sse", sseHandler.HandleSSE)

	// Authenticated routes
	authed := api.Group("")
	authed.Use(middleware.JWTAuth())
	authed.Use(middleware.PasswordChangeGuard(db))
	authed.Use(middleware.APILimitMiddleware())
	authed.Use(middleware.AuditMiddleware())
	{
		// 用户管理
		// Authenticated file download (replaces unauthenticated /uploads static route)
		attachmentDownloadHandler := handler.NewAttachmentHandler(db)
		authed.GET("/uploads/*filename", attachmentDownloadHandler.DownloadFile)

		authed.POST("/auth/logout", authHandler.Logout)
		authed.GET("/users/me", authHandler.GetProfile)
		authed.PUT("/users/me", authHandler.UpdateProfile)
		authed.PUT("/users/me/password", authHandler.ChangeMyPassword)
		authed.POST("/users/me/avatar", authHandler.UploadAvatar)
		authed.PUT("/users/me/agent-types", authHandler.UpdateMyAgentTypes)
		authed.GET("/users", middleware.RequirePermission("users:read"), authHandler.ListUsers)
		authed.GET("/users/:id", middleware.RequirePermission("users:read"), authHandler.GetUser)
		authed.PUT("/users/:id/agent-types", middleware.RequirePermission("users:manage"), authHandler.UpdateUserAgentTypes)
		authed.POST("/users", middleware.RequirePermission("users:manage"), authHandler.CreateUser)
		authed.POST("/users/:id/reset-password", middleware.RequirePermission("users:manage"), authHandler.ResetUserPassword)

		// 用户项目列表（新增）
		userProjectsHandler := handler.NewUserProjectsHandler(db)
		authed.GET("/user/projects", userProjectsHandler.ListUserProjects)

		tokenUsageHandler := handler.NewTokenUsageHandler(db)
		repoHandler := handler.NewRepoHandler(db)
		authed.GET("/iterations/:id/token-usage", middleware.RequirePermission("projects:read"), tokenUsageHandler.GetIterationTokenUsage)

		// 项目
		projHandler := handler.NewProjectHandler(db)
		defectHandler := handler.NewDefectHandlerWithAnalysisService(db, adkAnalysisService)
		projects := authed.Group("/projects")
		{
			projects.GET("", projHandler.ListProjects)
			projects.POST("", middleware.RequirePermission("projects:create"), projHandler.CreateProject)
			projects.GET("/:id", middleware.RequireProjectPermission("projects:read", "id"), projHandler.GetProject)
			projects.PUT("/:id", middleware.RequireProjectPermission("projects:update", "id"), projHandler.UpdateProject)
			projects.POST("/:id/members", middleware.RequireProjectPermission("projects:update", "id"), projHandler.AddMember)
			projects.DELETE("/:id/members/:memberId", middleware.RequireProjectPermission("projects:update", "id"), projHandler.RemoveMember)

			// 项目统计（新增）
			projects.GET("/:id/stats", middleware.RequireProjectPermission("projects:read", "id"), userProjectsHandler.GetProjectStats)
			projects.POST("/:id/defects/draft-from-chat", middleware.RequireProjectPermission("projects:update", "id"), defectHandler.CreateDraftFromChat)
			projects.POST("/:id/defects/confirm-create", middleware.RequireProjectPermission("projects:update", "id"), defectHandler.ConfirmCreateDefect)

			// 项目仓库管理（v1.1新增）
			repoHandler := handler.NewProjectRepoHandler(db)
			projects.GET("/:id/repos", middleware.RequireProjectPermission("projects:read", "id"), repoHandler.ListRepos)
			projects.POST("/:id/repos", middleware.RequireProjectPermission("projects:update", "id"), repoHandler.CreateRepo)
			projects.PUT("/:id/repos/:repoId", middleware.RequireProjectPermission("projects:update", "id"), repoHandler.UpdateRepo)
			projects.DELETE("/:id/repos/:repoId", middleware.RequireProjectPermission("projects:update", "id"), repoHandler.DeleteRepo)
			issuePoolHandler := handler.NewIssuePoolHandler(db)
			projects.GET("/:id/issue-clusters", middleware.RequireProjectPermission("projects:read", "id"), issuePoolHandler.ListClusters)
			projects.GET("/:id/issue-clusters/release-summary", middleware.RequireProjectPermission("projects:read", "id"), issuePoolHandler.ListReleaseSummaries)
			projects.GET("/:id/issue-clusters/:clusterId", middleware.RequireProjectPermission("projects:read", "id"), issuePoolHandler.GetCluster)
			projects.GET("/:id/issue-clusters/:clusterId/signals", middleware.RequireProjectPermission("projects:read", "id"), issuePoolHandler.ListSignals)
			projects.GET("/:id/issue-clusters/:clusterId/releases", middleware.RequireProjectPermission("projects:read", "id"), issuePoolHandler.ListClusterReleases)
			projects.POST("/:id/issue-clusters/:clusterId/assign", middleware.RequireProjectPermission("projects:update", "id"), issuePoolHandler.AssignCluster)
			projects.POST("/:id/issue-clusters/batch-assign", middleware.RequireProjectPermission("projects:update", "id"), issuePoolHandler.BatchAssignClusters)
			projects.POST("/:id/issue-clusters/:clusterId/ignore", middleware.RequireProjectPermission("projects:update", "id"), issuePoolHandler.IgnoreCluster)
			projects.POST("/:id/issue-clusters/batch-ignore", middleware.RequireProjectPermission("projects:update", "id"), issuePoolHandler.BatchIgnoreClusters)
			projects.POST("/:id/issue-clusters/:clusterId/merge", middleware.RequireProjectPermission("projects:update", "id"), issuePoolHandler.MergeCluster)
			projects.POST("/:id/issue-clusters/:clusterId/convert", middleware.RequireProjectPermission("projects:update", "id"), issuePoolHandler.ConvertCluster)
			projects.POST("/:id/issue-clusters/batch-convert", middleware.RequireProjectPermission("projects:update", "id"), issuePoolHandler.BatchConvertClusters)
			projects.POST("/:id/issue-clusters/auto-triage", middleware.RequireProjectPermission("projects:update", "id"), issuePoolHandler.AutoTriageClusters)
			projects.GET("/:id/issue-clusters/suggestion-stats", middleware.RequireProjectPermission("projects:read", "id"), issuePoolHandler.GetRoutingSuggestionStats)
			projectRoutingHandler := handler.NewProjectRoutingHandler(db)
			projects.GET("/:id/modules", middleware.RequireProjectPermission("projects:read", "id"), projectRoutingHandler.ListModules)
			projects.POST("/:id/modules", middleware.RequireProjectPermission("projects:update", "id"), projectRoutingHandler.CreateModule)
			projects.PUT("/:id/modules/:moduleId", middleware.RequireProjectPermission("projects:update", "id"), projectRoutingHandler.UpdateModule)
			projects.DELETE("/:id/modules/:moduleId", middleware.RequireProjectPermission("projects:update", "id"), projectRoutingHandler.DeleteModule)
			projects.GET("/:id/routing-rules", middleware.RequireProjectPermission("projects:read", "id"), projectRoutingHandler.ListRules)
			projects.POST("/:id/routing-rules", middleware.RequireProjectPermission("projects:update", "id"), projectRoutingHandler.CreateRule)
			projects.PUT("/:id/routing-rules/:ruleId", middleware.RequireProjectPermission("projects:update", "id"), projectRoutingHandler.UpdateRule)
			projects.DELETE("/:id/routing-rules/:ruleId", middleware.RequireProjectPermission("projects:update", "id"), projectRoutingHandler.DeleteRule)
			projects.GET("/:id/releases", middleware.RequireProjectPermission("projects:read", "id"), projectRoutingHandler.ListReleases)
			projects.GET("/:id/releases/trends", middleware.RequireProjectPermission("projects:read", "id"), projectRoutingHandler.ListReleaseTrends)
			projects.POST("/:id/releases", middleware.RequireProjectPermission("projects:update", "id"), projectRoutingHandler.CreateRelease)
			projects.PUT("/:id/releases/:releaseId", middleware.RequireProjectPermission("projects:update", "id"), projectRoutingHandler.UpdateRelease)
			projects.DELETE("/:id/releases/:releaseId", middleware.RequireProjectPermission("projects:update", "id"), projectRoutingHandler.DeleteRelease)
			regressionHandler := handler.NewRegressionPreventionHandler(db)
			projects.GET("/:id/regression-items", middleware.RequireProjectPermission("projects:read", "id"), regressionHandler.ListItems)
			projects.POST("/:id/issue-clusters/:clusterId/regression-items", middleware.RequireProjectPermission("projects:update", "id"), regressionHandler.CreateFromCluster)
			projects.PUT("/:id/regression-items/:itemId", middleware.RequireProjectPermission("projects:update", "id"), regressionHandler.UpdateItem)
			qualityInsightsHandler := handler.NewQualityInsightsHandler(db)
			projects.GET("/:id/quality-insights/overview", middleware.RequireProjectPermission("projects:read", "id"), qualityInsightsHandler.GetOverview)
			integrationConnectorHandler := handler.NewIntegrationConnectorHandler(db, signalIngestService)
			projects.GET("/:id/integrations", middleware.RequireProjectPermission("projects:read", "id"), integrationConnectorHandler.List)
			projects.POST("/:id/integrations", middleware.RequireProjectPermission("projects:update", "id"), integrationConnectorHandler.Create)
			projects.PUT("/:id/integrations/:connectorId", middleware.RequireProjectPermission("projects:update", "id"), integrationConnectorHandler.Update)
			projects.DELETE("/:id/integrations/:connectorId", middleware.RequireProjectPermission("projects:update", "id"), integrationConnectorHandler.Delete)
			projects.POST("/:id/integrations/:connectorId/test", middleware.RequireProjectPermission("projects:update", "id"), integrationConnectorHandler.Test)
			projects.POST("/:id/integrations/:connectorId/sync", middleware.RequireProjectPermission("projects:update", "id"), integrationConnectorHandler.Sync)
			projects.GET("/:id/integrations/:connectorId/sync-records", middleware.RequireProjectPermission("projects:read", "id"), integrationConnectorHandler.ListSyncRecords)

			// 仓库凭证管理（v2.0 P2-1新增）
			credHandler := handler.NewCredentialHandler(db)
			authed.GET("/credentials", credHandler.ListCredentials)
			authed.POST("/credentials", credHandler.CreateCredential)
			authed.PUT("/credentials/:id", credHandler.UpdateCredential)
			authed.DELETE("/credentials/:id", credHandler.DeleteCredential)
			authed.POST("/credentials/test-connection", credHandler.TestConnection)
			authed.GET("/admin/platform-credentials", middleware.RequirePermission("users:manage"), credHandler.ListPlatformCredentials)
			authed.POST("/admin/platform-credentials", middleware.RequirePermission("users:manage"), credHandler.CreatePlatformCredential)
			authed.PUT("/admin/platform-credentials/:id", middleware.RequirePermission("users:manage"), credHandler.UpdatePlatformCredential)
			authed.DELETE("/admin/platform-credentials/:id", middleware.RequirePermission("users:manage"), credHandler.DeletePlatformCredential)
			platformSettingsHandler := handler.NewPlatformSettingsHandler(db)
			authed.GET("/admin/platform-settings/email", middleware.RequirePermission("system:settings"), platformSettingsHandler.GetEmailSettings)
			authed.PUT("/admin/platform-settings/email", middleware.RequirePermission("system:settings"), platformSettingsHandler.UpdateEmailSettings)
			authed.POST("/admin/platform-settings/email/test", middleware.RequirePermission("system:settings"), platformSettingsHandler.TestEmailSettings)
			authed.POST("/repos/:id/test-connection", middleware.RequireRepoPermission("projects:read", "id"), credHandler.TestConnection)

			// 邀请码管理（v2.0 P5新增）
			inviteHandler := handler.NewInviteHandler(db)
			authed.POST("/invites", middleware.RequirePermission("users:manage"), inviteHandler.CreateInvite)
			authed.GET("/invites", middleware.RequirePermission("users:manage"), inviteHandler.ListInvites)

			// 平台角色管理（v2.0 P5新增）
			authed.PUT("/users/:id/platform-role", middleware.RequirePermission("users:manage"), authHandler.UpdateUserPlatformRole)

			// 通知偏好管理（v2.0 P3-2新增）
			prefHandler := handler.NewNotificationPrefHandler(db)
			authed.GET("/notification-preferences", prefHandler.GetPreferences)
			authed.PUT("/notification-preferences", prefHandler.BatchUpdate)
			authed.GET("/notification-preferences/webhook", prefHandler.GetWebhookSettings)
			authed.PUT("/notification-preferences/webhook", prefHandler.UpdateWebhookSettings)
			authed.POST("/notification-preferences/webhook/test", prefHandler.TestWebhookSettings)

			// 项目AI配置管理（v1.1新增）
			aiConfigHandler := handler.NewProjectAIConfigHandler(db)
			projects.GET("/:id/ai-configs", middleware.RequireProjectPermission("projects:read", "id"), aiConfigHandler.ListAIConfigs)
			projects.POST("/:id/ai-configs", middleware.RequireProjectPermission("projects:update", "id"), aiConfigHandler.CreateAIConfig)
			projects.PUT("/:id/ai-configs/:configId", middleware.RequireProjectPermission("projects:update", "id"), aiConfigHandler.UpdateAIConfig)
			projects.DELETE("/:id/ai-configs/:configId", middleware.RequireProjectPermission("projects:update", "id"), aiConfigHandler.DeleteAIConfig)

			// 项目通知管理（v4.0 P3新增）
			projectNotificationHandler := handler.NewProjectNotificationHandler(db)
			projects.GET("/:id/notification-policies", middleware.RequireProjectPermission("projects:read", "id"), projectNotificationHandler.GetPolicies)
			projects.PUT("/:id/notification-policies", middleware.RequireProjectPermission("projects:update", "id"), projectNotificationHandler.BatchUpdatePolicies)
			projects.GET("/:id/notification-webhooks", middleware.RequireProjectPermission("projects:read", "id"), projectNotificationHandler.ListWebhooks)
			projects.POST("/:id/notification-webhooks", middleware.RequireProjectPermission("projects:update", "id"), projectNotificationHandler.CreateWebhook)
			projects.PUT("/:id/notification-webhooks/:webhookId", middleware.RequireProjectPermission("projects:update", "id"), projectNotificationHandler.UpdateWebhook)
			projects.DELETE("/:id/notification-webhooks/:webhookId", middleware.RequireProjectPermission("projects:update", "id"), projectNotificationHandler.DeleteWebhook)
			projects.POST("/:id/notification-webhooks/:webhookId/test", middleware.RequireProjectPermission("projects:update", "id"), projectNotificationHandler.TestWebhook)

			// AI 厂商模型列表（全局，无需项目ID）
			aiConfigHandler2 := handler.NewProjectAIConfigHandler(db)
			authed.GET("/ai/providers", aiConfigHandler2.GetAIProviders)

			// 云效集成（v3.0 P2/P3）
			yunxiaoHandler := handler.NewYunxiaoIntegrationHandler(db)
			authed.POST("/integrations/yunxiao/test-connection", yunxiaoHandler.TestConnection)
			authed.GET("/integrations/yunxiao/repos", yunxiaoHandler.ListRepositories)
			authed.GET("/integrations/yunxiao/members", yunxiaoHandler.ListMembers)
			projects.POST("/:id/repos/import/yunxiao", middleware.RequireProjectPermission("projects:update", "id"), yunxiaoHandler.ImportRepositories)
			projects.POST("/:id/members/import/yunxiao", middleware.RequireProjectPermission("projects:update", "id"), yunxiaoHandler.ImportMembers)

			// AI 目录管理（v3.0 P1：平台管理员）
			aiCatalogHandler := handler.NewAICatalogHandler(db)
			authed.GET("/admin/ai/providers", middleware.RequirePermission("users:manage"), aiCatalogHandler.ListProviders)
			authed.POST("/admin/ai/providers", middleware.RequirePermission("users:manage"), aiCatalogHandler.CreateProvider)
			authed.PUT("/admin/ai/providers/:id", middleware.RequirePermission("users:manage"), aiCatalogHandler.UpdateProvider)
			authed.DELETE("/admin/ai/providers/:id", middleware.RequirePermission("users:manage"), aiCatalogHandler.DeleteProvider)
			authed.GET("/admin/ai/models", middleware.RequirePermission("users:manage"), aiCatalogHandler.ListModels)
			authed.POST("/admin/ai/models", middleware.RequirePermission("users:manage"), aiCatalogHandler.CreateModel)
			authed.PUT("/admin/ai/models/:id", middleware.RequirePermission("users:manage"), aiCatalogHandler.UpdateModel)
			authed.DELETE("/admin/ai/models/:id", middleware.RequirePermission("users:manage"), aiCatalogHandler.DeleteModel)
			authed.POST("/admin/ai/models/:id/test", middleware.RequirePermission("users:manage"), aiCatalogHandler.TestModelAvailability)

			// 迭代
			projects.POST("/:id/iterations", middleware.RequireProjectPermission("projects:update", "id"), projHandler.CreateIteration)
			projects.GET("/:id/iterations", middleware.RequireProjectPermission("projects:read", "id"), projHandler.ListIterations)
			projects.GET("/:id/iterations/:iterationId", middleware.RequireProjectPermission("projects:read", "id"), projHandler.GetIteration)
			projects.PUT("/:id/iterations/:iterationId", middleware.RequireProjectPermission("projects:update", "id"), projHandler.UpdateIteration)
			projects.POST("/:id/iterations/:iterationId/repos", middleware.RequireProjectPermission("projects:update", "id"), projHandler.BindRepo)
			projects.DELETE("/:id/iterations/:iterationId/repos/:repoId", middleware.RequireProjectPermission("projects:update", "id"), projHandler.UnbindRepo)
			projects.PUT("/:id/iterations/:iterationId/repos/:iterRepoId/branch", middleware.RequireProjectPermission("projects:update", "id"), projHandler.UpdateIterationRepoBranch)
			projects.GET("/:id/repos/:repoId/branches", middleware.RequireProjectPermission("projects:read", "id"), projHandler.ListRepoBranches)
			projects.GET("/:id/iterations/:iterationId/defects", middleware.RequireProjectPermission("projects:read", "id"), projHandler.GetDefects)

			// Agent Memory (v5.4)
			memoryHandler := handler.NewAgentMemoryHandler(db)
			projects.GET("/:id/memories", middleware.RequireProjectPermission("projects:read", "id"), memoryHandler.ListProjectMemories)
			projects.POST("/:id/memories", middleware.RequireProjectPermission("projects:update", "id"), memoryHandler.CreateProjectMemory)
			projects.GET("/:id/iterations/:iterationId/memories", middleware.RequireProjectPermission("projects:read", "id"), memoryHandler.ListIterationMemories)
			projects.POST("/:id/iterations/:iterationId/memories", middleware.RequireProjectPermission("projects:update", "id"), memoryHandler.CreateIterationMemory)
			projects.PUT("/:id/memories/:memoryId", middleware.RequireProjectPermission("projects:update", "id"), memoryHandler.UpdateMemory)
			projects.DELETE("/:id/memories/:memoryId", middleware.RequireProjectPermission("projects:update", "id"), memoryHandler.DeleteMemory)
			projects.PATCH("/:id/memories/:memoryId/toggle", middleware.RequireProjectPermission("projects:update", "id"), memoryHandler.ToggleMemory)

			projects.GET("/:id/token-usage", middleware.RequireProjectPermission("projects:read", "id"), tokenUsageHandler.GetProjectTokenUsage)
			projects.GET("/:id/token-usage/by-iteration", middleware.RequireProjectPermission("projects:read", "id"), tokenUsageHandler.GetProjectTokenUsageByIteration)
			projects.GET("/:id/token-usage/by-defect", middleware.RequireProjectPermission("projects:read", "id"), tokenUsageHandler.GetProjectTokenUsageByDefect)
			projects.GET("/:id/iterations/:iterationId/token-usage", middleware.RequireProjectPermission("projects:read", "id"), tokenUsageHandler.GetIterationTokenUsage)

			// MCP 服务 (v5.5)
			mcpServerHandler := handler.NewMCPServerHandler(db)
			projects.GET("/:id/mcp-servers", middleware.RequireProjectPermission("projects:read", "id"), mcpServerHandler.List)
			projects.POST("/:id/mcp-servers", middleware.RequireProjectPermission("projects:update", "id"), mcpServerHandler.Create)
			projects.PUT("/:id/mcp-servers/:serverId", middleware.RequireProjectPermission("projects:update", "id"), mcpServerHandler.Update)
			projects.DELETE("/:id/mcp-servers/:serverId", middleware.RequireProjectPermission("projects:update", "id"), mcpServerHandler.Delete)
			projects.PATCH("/:id/mcp-servers/:serverId/toggle", middleware.RequireProjectPermission("projects:update", "id"), mcpServerHandler.Toggle)
			projects.POST("/:id/mcp-servers/:serverId/test", middleware.RequireProjectPermission("projects:update", "id"), mcpServerHandler.TestConnection)

			// 技能 (v5.5)
			skillHandler := handler.NewSkillHandler(db)
			projects.GET("/:id/skills", middleware.RequireProjectPermission("projects:read", "id"), skillHandler.List)
			projects.POST("/:id/skills", middleware.RequireProjectPermission("projects:update", "id"), skillHandler.Create)
			projects.PUT("/:id/skills/:skillId", middleware.RequireProjectPermission("projects:update", "id"), skillHandler.Update)
			projects.DELETE("/:id/skills/:skillId", middleware.RequireProjectPermission("projects:update", "id"), skillHandler.Delete)
			projects.PATCH("/:id/skills/:skillId/toggle", middleware.RequireProjectPermission("projects:update", "id"), skillHandler.Toggle)

			retrieverPluginHandler := handler.NewRetrieverPluginHandler(db)
			projects.GET("/:id/retriever-plugins", middleware.RequireProjectPermission("projects:read", "id"), retrieverPluginHandler.List)
			projects.PUT("/:id/retriever-plugins/:pluginId", middleware.RequireProjectPermission("projects:update", "id"), retrieverPluginHandler.Update)
			projects.PATCH("/:id/retriever-plugins/:pluginId/toggle", middleware.RequireProjectPermission("projects:update", "id"), retrieverPluginHandler.Toggle)
			projects.PUT("/:id/retriever-plugins/sort", middleware.RequireProjectPermission("projects:update", "id"), retrieverPluginHandler.BatchSort)
			projects.POST("/:id/retriever-plugins/:pluginId/test", middleware.RequireProjectPermission("projects:update", "id"), retrieverPluginHandler.Test)
		}

		// 缺陷
		defects := authed.Group("/defects")
		{
			defects.GET("", middleware.RequireDefectListPermission("defects:read"), defectHandler.ListDefects)
			defects.POST("", middleware.RequireDefectCreatePermission("defects:create"), defectHandler.CreateDefect)
			defects.GET("/:id", middleware.RequireDefectPermission("defects:read", "id"), defectHandler.GetDefect)
			defects.GET("/:id/recommend-assignees", middleware.RequireDefectPermission("defects:read", "id"), defectHandler.RecommendAssignees)
			defects.GET("/:id/recommend-agents", middleware.RequireDefectPermission("defects:read", "id"), defectHandler.RecommendAgents)
			defects.PUT("/:id", middleware.RequireDefectPermission("defects:update", "id"), defectHandler.UpdateDefect)
			defects.PUT("/:id/assign", middleware.RequireDefectPermission("defects:update", "id"), defectHandler.AssignDefect)
			defects.PUT("/:id/status", middleware.RequireDefectPermission("defects:update", "id"), defectHandler.ChangeStatus)
			defects.PUT("/:id/verify", middleware.RequireDefectPermission("defects:update", "id"), defectHandler.VerifyDefect)
			defects.PUT("/:id/merge", middleware.RequireDefectPermission("defects:update", "id"), defectHandler.MergeDefect)
			defects.PUT("/:id/reject", middleware.RequireDefectPermission("defects:update", "id"), defectHandler.RejectDefect)
			defects.POST("/:id/reopen", middleware.RequireDefectPermission("defects:update", "id"), defectHandler.ReopenDefect)
			defects.POST("/:id/reanalyze", middleware.RequireDefectPermission("defects:update", "id"), defectHandler.ReanalyzeDefect)

			// 附件
			attachmentHandler := handler.NewAttachmentHandler(db)
			defects.POST("/:id/attachments", middleware.RequireDefectPermission("defects:update", "id"), attachmentHandler.UploadAttachment)
			defects.GET("/:id/attachments", middleware.RequireDefectPermission("defects:read", "id"), attachmentHandler.ListAttachments)
			defects.DELETE("/:id/attachments/:attachmentId", middleware.RequireDefectPermission("defects:update", "id"), attachmentHandler.DeleteAttachment)

			// 评论
			commentHandler := handler.NewCommentHandlerWithAnalysisService(db, adkAnalysisService)
			defects.POST("/:id/comments", middleware.RequireDefectPermission("defects:update", "id"), commentHandler.CreateComment)
			defects.GET("/:id/comments", middleware.RequireDefectPermission("defects:read", "id"), commentHandler.ListComments)

			defects.GET("/:id/reports", middleware.RequireDefectPermission("agents:read_report", "id"), agentHandler.GetDefectAnalysisReports)

			defects.POST("/:id/fix-tasks", middleware.RequireDefectPermission("fix_tasks:create", "id"), fixHandler.CreateFixTask)
			defects.GET("/:id/fix-task-groups", middleware.RequireDefectPermission("defects:read", "id"), fixHandler.ListFixTaskGroups)
			defects.GET("/:id/fix-tasks", middleware.RequireDefectPermission("defects:read", "id"), fixHandler.ListFixTasks)

			// Manual Fix (v5.4)
			manualFixHandler := handler.NewManualFixHandler(db)
			defects.POST("/:id/manual-fix/start", middleware.RequireDefectPermission("fix_tasks:create", "id"), manualFixHandler.StartManualFix)
			defects.POST("/:id/manual-fix/complete", middleware.RequireDefectPermission("fix_tasks:update", "id"), manualFixHandler.CompleteManualFix)
			defects.POST("/:id/manual-fix/abandon", middleware.RequireDefectPermission("fix_tasks:update", "id"), manualFixHandler.AbandonManualFix)

			// PR Lifecycle (v5.4)
			prLifecycleHandler := handler.NewPRLifecycleHandler(db)
			defects.PATCH("/:id/fix-tasks/:taskId/pr", middleware.RequireDefectPermission("fix_tasks:update", "id"), manualFixHandler.UpdateFixTaskPR)
			defects.GET("/:id/fix-tasks/:taskId/rejections", middleware.RequireDefectPermission("defects:read", "id"), prLifecycleHandler.ListPRRejections)
			defects.POST("/:id/fix-tasks/:taskId/reject", middleware.RequireDefectPermission("fix_tasks:update", "id"), prLifecycleHandler.ManualRejectPR)
			defects.POST("/:id/fix-tasks/:taskId/merge", middleware.RequireDefectPermission("fix_tasks:update", "id"), prLifecycleHandler.ManualMergePR)

			// Workflow (Sprint 4: State Machine)
			workflowHandler := handler.NewWorkflowHandler(db)
			defects.PUT("/:id/transition", middleware.RequireDefectPermission("defects:update", "id"), workflowHandler.TransitionStatus)
			defects.GET("/:id/transitions", middleware.RequireDefectPermission("defects:read", "id"), workflowHandler.GetTransitions)
			defects.GET("/:id/history", middleware.RequireDefectPermission("defects:read", "id"), workflowHandler.GetHistory)
			authed.POST("/workflow/batch", middleware.RequirePermission("defects:update"), workflowHandler.BatchTransition)

			defects.GET("/:id/repos", middleware.RequireDefectPermission("defects:read", "id"), repoHandler.ListDefectRepos)
			defects.DELETE("/:id/repos/:repoId", middleware.RequireDefectPermission("defects:update", "id"), repoHandler.DeleteDefectRepo)
		}

		adminRepos := authed.Group("/admin/repos")
		{
			adminRepos.GET("/orphaned", middleware.RequirePermission("users:manage"), repoHandler.ListOrphanedRepos)
			adminRepos.POST("/cleanup", middleware.RequirePermission("users:manage"), repoHandler.TriggerCleanup)
		}

		authed.POST("/agents/analyze", middleware.RequireAnalysisPermission("agents:analyze"), agentHandler.TriggerAnalysis)
		authed.POST("/agents/analyze/stream", middleware.RequireAnalysisPermission("agents:analyze"), agentHandler.TriggerAnalysisStream)
		authed.GET("/agents/reports/:reportId", middleware.RequireReportPermission("agents:read_report", "reportId"), agentHandler.GetAnalysisReport)
		authed.POST("/agents/analyze/:id/cancel", middleware.RequireAnalysisPermission("agents:analyze"), agentHandler.CancelAnalysis)
		authed.GET("/agents/analyze/queue", middleware.RequireAnalysisPermission("agents:analyze"), agentHandler.QueueStatus)
		authed.GET("/agents/analyze/:id/history", middleware.RequireAnalysisPermission("agents:analyze"), agentHandler.AnalysisHistory)

		authed.GET("/fix-tasks/:taskId", middleware.RequireFixTaskPermission("defects:read", "taskId"), fixHandler.GetFixTask)
		authed.PUT("/fix-tasks/:taskId", middleware.RequireFixTaskPermission("fix_tasks:update", "taskId"), fixHandler.UpdateFixTaskStatus)

		defects.GET("/:id/token-usage", middleware.RequireDefectPermission("defects:read", "id"), tokenUsageHandler.GetDefectTokenUsage)
		defects.GET("/:id/token-usage/details", middleware.RequireDefectPermission("defects:read", "id"), tokenUsageHandler.GetDefectTokenUsageDetails)

		collaborations := authed.Group("/collaborations")
		{
			collaborations.POST("", middleware.RequireAnalysisPermission("agents:analyze"), collabHandler.StartCollaboration)
			collaborations.GET("", middleware.RequireDefectListPermission("defects:read"), collabHandler.ListCollaborationTasks)
			collaborations.GET("/:taskId", middleware.RequireCollaborationTaskPermission("defects:read", "taskId"), collabHandler.GetCollaborationTask)
			collaborations.GET("/:taskId/report", middleware.RequireCollaborationTaskPermission("defects:read", "taskId"), collabHandler.GetAggregatedReport)
		}
		defects.POST("/:id/collaborations", middleware.RequireDefectPermission("defects:update", "id"), collabHandler.StartCollaboration)
		defects.GET("/:id/collaborations", middleware.RequireDefectPermission("defects:read", "id"), collabHandler.GetDefectCollaborations)

		// RBAC权限管理（Sprint 3新增）
		rbacHandler := handler.NewRBACHandler(db)
		rbac := authed.Group("/rbac")
		{
			rbac.GET("/roles", middleware.RequirePermission("rbac:manage"), rbacHandler.ListRoles)
			rbac.GET("/permissions", middleware.RequirePermission("rbac:manage"), rbacHandler.ListPermissions)
			rbac.GET("/my-permissions", rbacHandler.GetUserPermissions)
			rbac.GET("/my-roles", rbacHandler.GetUserRoles)
			rbac.POST("/assign", middleware.RequirePermission("rbac:manage"), rbacHandler.AssignUserRole)
			rbac.DELETE("/users/:userId/roles/:roleId", middleware.RequirePermission("rbac:manage"), rbacHandler.RemoveUserRole)
			rbac.GET("/check", rbacHandler.CheckPermission)
			rbac.GET("/roles/:id", middleware.RequireRole("super_admin"), rbacHandler.GetRole)
			rbac.POST("/roles", middleware.RequireRole("super_admin"), rbacHandler.CreateRole)
			rbac.PUT("/roles/:id", middleware.RequireRole("super_admin"), rbacHandler.UpdateRole)
			rbac.PUT("/roles/:id/permissions", middleware.RequireRole("super_admin"), rbacHandler.UpdateRolePermissions)
		}

		// 审计日志（Sprint 3新增）
		auditHandler := handler.NewAuditHandler(db)
		authed.GET("/audit-logs", middleware.RequirePermission("audit:read"), auditHandler.ListAuditLogs)
		authed.GET("/audit-logs/recent", middleware.RequirePermission("audit:read"), auditHandler.GetRecentAuditLogs)
		authed.GET("/audit-logs/stats", middleware.RequirePermission("audit:read"), auditHandler.GetAuditStats)

		// 通知系统（Sprint 4新增）
		notifyCfg := &model.NotificationConfig{
			SMTPHost:      config.C.Notification.SMTPHost,
			SMTPPort:      config.C.Notification.SMTPPort,
			SMTPUser:      config.C.Notification.SMTPUser,
			SMTPPassword:  config.C.Notification.SMTPPassword,
			SMTPFrom:      config.C.Notification.SMTPFrom,
			WebhookURL:    config.C.Notification.WebhookURL,
			WebhookSecret: config.C.Notification.WebhookSecret,
		}
		notifySvc := service.NewNotificationService(db, notifyCfg)
		notifyHandler := handler.NewNotificationHandler(db, notifySvc)
		notifications := authed.Group("/notifications")
		{
			notifications.GET("", notifyHandler.List)
			notifications.GET("/unread-count", notifyHandler.UnreadCount)
			notifications.PUT("/read", notifyHandler.MarkRead)
			notifications.PUT("/read-all", notifyHandler.MarkAllRead)
			notifications.POST("/send", middleware.RequirePermission("notifications:send"), notifyHandler.Send)
		}

		// 报表看板（Sprint 4新增）
		reportSvc := service.NewReportService(db)
		reportHandler := handler.NewReportHandler(reportSvc)
		reports := authed.Group("/reports")
		{
			reports.GET("/dashboard", reportHandler.Dashboard)
			reports.GET("/trend", reportHandler.Trend)
			reports.GET("/status-distribution", reportHandler.StatusDistribution)
			reports.GET("/severity-distribution", reportHandler.SeverityDistribution)
			reports.GET("/team-metrics", reportHandler.TeamMetrics)
			reports.GET("/export/csv", middleware.RequirePermission("reports:export"), reportHandler.ExportCSV)
			reports.GET("/export/json", middleware.RequirePermission("reports:export"), reportHandler.ExportJSON)
		}

		// Initialize middleware services
		middleware.InitRBAC(db)
		middleware.InitAudit(db)
	}

	return r
}

func analysisTaskStatusFromError(err error) adk.TaskStatus {
	if err != nil {
		return adk.TaskStatusFailed
	}
	return adk.TaskStatusCompleted
}
