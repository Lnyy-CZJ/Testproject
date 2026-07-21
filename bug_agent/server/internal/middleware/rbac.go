package middleware

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"sync"

	"github.com/gin-gonic/gin"
	"github.com/gin-gonic/gin/binding"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

var rbacService *service.RBACService
var seedRBACMu sync.Mutex

func InitRBAC(db *gorm.DB) {
	rbacService = service.NewRBACService(db)
}

func SeedRBACData(db *gorm.DB) {
	seedRBACMu.Lock()
	defer seedRBACMu.Unlock()

	roles := []model.Role{
		{Name: "super_admin", DisplayName: "超级管理员", Tier: "platform", IsSystem: true, Description: "拥有平台全部权限"},
		{Name: "admin", DisplayName: "平台管理员", Tier: "platform", IsSystem: true, Description: "拥有平台管理权限"},
		{Name: "member", DisplayName: "平台成员", Tier: "platform", IsSystem: true, Description: "平台基础权限"},
		{Name: "project_admin", DisplayName: "项目管理员", Tier: "project", IsSystem: true, Description: "拥有项目管理权限"},
		{Name: "developer", DisplayName: "开发人员", Tier: "project", IsSystem: true, Description: "可处理缺陷和查看报告"},
		{Name: "tester", DisplayName: "测试人员", Tier: "project", IsSystem: true, Description: "可创建缺陷和执行测试"},
		{Name: "viewer", DisplayName: "只读成员", Tier: "project", IsSystem: true, Description: "只读访问"},
	}
	roleNames := make([]string, 0, len(roles))
	for _, role := range roles {
		roleNames = append(roleNames, role.Name)
	}
	if err := db.Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "name"}},
		DoUpdates: clause.AssignmentColumns([]string{"display_name", "description", "tier", "is_system", "updated_at"}),
	}).Create(&roles).Error; err != nil {
		logger.Errorf("SeedRBACData: create roles failed: %v", err)
	}

	var persistedRoles []model.Role
	if err := db.Where("name IN ?", roleNames).Find(&persistedRoles).Error; err != nil {
		logger.Errorf("SeedRBACData: query roles failed: %v", err)
		return
	}
	roleByName := make(map[string]model.Role, len(persistedRoles))
	for _, role := range persistedRoles {
		roleByName[role.Name] = role
	}

	// v2.0 去兼容化：将 legacy 角色迁移到标准角色并删除 legacy 角色定义。
	cleanupLegacyRoles(db, roleByName)

	perms := []model.Permission{
		{Code: "defects:create", Name: "创建缺陷", Module: "defects"},
		{Code: "defects:read", Name: "查看缺陷", Module: "defects"},
		{Code: "defects:update", Name: "编辑缺陷", Module: "defects"},
		{Code: "defects:delete", Name: "删除缺陷", Module: "defects"},
		{Code: "agents:analyze", Name: "触发AI分析", Module: "agents"},
		{Code: "agents:read_report", Name: "查看分析报告", Module: "agents"},
		{Code: "fix_tasks:create", Name: "创建修复任务", Module: "fixes"},
		{Code: "fix_tasks:update", Name: "更新修复任务", Module: "fixes"},
		{Code: "projects:create", Name: "创建项目", Module: "projects"},
		{Code: "projects:read", Name: "查看项目", Module: "projects"},
		{Code: "projects:update", Name: "编辑项目", Module: "projects"},
		{Code: "users:read", Name: "查看用户", Module: "users"},
		{Code: "users:manage", Name: "管理用户", Module: "users"},
		{Code: "system:settings", Name: "系统设置", Module: "system"},
		{Code: "rbac:manage", Name: "权限管理", Module: "system"},
		{Code: "audit:read", Name: "查看审计日志", Module: "system"},
		{Code: "notifications:send", Name: "发送通知", Module: "system"},
		{Code: "reports:export", Name: "导出报表", Module: "system"},
	}
	permCodes := make([]string, 0, len(perms))
	for _, perm := range perms {
		permCodes = append(permCodes, perm.Code)
	}
	if err := db.Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "code"}},
		DoUpdates: clause.AssignmentColumns([]string{"name", "module", "description"}),
	}).Create(&perms).Error; err != nil {
		logger.Errorf("SeedRBACData: create permissions failed: %v", err)
	}

	var persistedPerms []model.Permission
	if err := db.Where("code IN ?", permCodes).Find(&persistedPerms).Error; err != nil {
		logger.Errorf("SeedRBACData: query permissions failed: %v", err)
		return
	}
	permByCode := make(map[string]model.Permission, len(persistedPerms))
	for _, perm := range persistedPerms {
		permByCode[perm.Code] = perm
	}

	allCodes := make([]string, 0, len(permByCode))
	for code := range permByCode {
		allCodes = append(allCodes, code)
	}

	rolePermCodes := map[string][]string{
		"super_admin": allCodes,
		"admin": {
			"projects:create", "projects:read", "projects:update",
			"users:read", "users:manage",
			"rbac:manage", "audit:read", "reports:export",
			"system:settings", "notifications:send",
		},
		"member": {},
		"project_admin": {
			"projects:read", "projects:update",
			"defects:create", "defects:read", "defects:update", "defects:delete",
			"agents:analyze", "agents:read_report",
			"fix_tasks:create", "fix_tasks:update",
		},
		"developer": {
			"projects:read",
			"defects:create", "defects:read", "defects:update",
			"agents:analyze", "agents:read_report",
			"fix_tasks:create", "fix_tasks:update",
		},
		"tester": {
			"projects:read",
			"defects:create", "defects:read", "defects:update",
		},
		"viewer": {"projects:read", "defects:read", "agents:read_report"},
	}

	rolePermsToCreate := make([]model.RolePermission, 0, len(rolePermCodes)*4)
	for roleName, codes := range rolePermCodes {
		role, ok := roleByName[roleName]
		if !ok || role.ID == 0 {
			continue
		}
		for _, code := range codes {
			perm, ok := permByCode[code]
			if !ok || perm.ID == 0 {
				continue
			}
			rolePermsToCreate = append(rolePermsToCreate, model.RolePermission{
				RoleID:       role.ID,
				PermissionID: perm.ID,
			})
		}
	}
	if len(rolePermsToCreate) > 0 {
		if err := db.Clauses(clause.OnConflict{DoNothing: true}).Create(&rolePermsToCreate).Error; err != nil {
			logger.Errorf("db operation failed: %v", err)
		}
	}

	var adminUser model.User
	if err := db.Where("username = ?", "admin").First(&adminUser).Error; err != nil {
		logger.Errorf("查询管理员用户失败: %v", err)
	}
	if adminUser.ID > 0 {
		superAdminRole := roleByName["super_admin"]
		if superAdminRole.ID > 0 {
			if err := db.Clauses(clause.OnConflict{DoNothing: true}).Create(&model.UserRole{
				UserID:    adminUser.ID,
				RoleID:    superAdminRole.ID,
				ScopeType: "global",
			}).Error; err != nil {
				logger.Errorf("ensure super admin role failed: %v", err)
			}
		}
	}
}

func cleanupLegacyRoles(db *gorm.DB, roleByName map[string]model.Role) {
	legacyRoleMapping := map[string]string{
		"user":          "member",
		"project_owner": "project_admin",
		"guest":         "viewer",
		"org_admin":     "super_admin",
	}

	for legacyRoleName, targetRoleName := range legacyRoleMapping {
		var legacyRole model.Role
		if err := db.Where("name = ?", legacyRoleName).First(&legacyRole).Error; err != nil {
			continue
		}

		targetRole, ok := roleByName[targetRoleName]
		if ok && targetRole.ID > 0 {
			var duplicateRoles []model.UserRole
			if err := db.Where("role_id = ? AND user_id IN (?) AND COALESCE(scope_type, '') IN (?) AND COALESCE(scope_id, 0) IN (?)",
				legacyRole.ID,
				db.Model(&model.UserRole{}).Select("user_id").Where("role_id = ?", targetRole.ID),
				db.Model(&model.UserRole{}).Select("COALESCE(scope_type, '')").Where("role_id = ?", targetRole.ID),
				db.Model(&model.UserRole{}).Select("COALESCE(scope_id, 0)").Where("role_id = ?", targetRole.ID),
			).Find(&duplicateRoles).Error; err == nil {
				for _, dup := range duplicateRoles {
					db.Delete(&dup)
				}
			}

			if err := db.Model(&model.UserRole{}).
				Where("role_id = ?", legacyRole.ID).
				Update("role_id", targetRole.ID).Error; err != nil {
				logger.Errorf("[RBAC] migrate legacy role %s: %v", legacyRoleName, err)
			}
		} else {
			// 目标角色不存在时，直接清理遗留绑定，避免脏数据继续生效。
			if err := db.Where("role_id = ?", legacyRole.ID).Delete(&model.UserRole{}).Error; err != nil {
				logger.Errorf("db operation failed: %v", err)
			}
		}

		if err := db.Where("role_id = ?", legacyRole.ID).Delete(&model.RolePermission{}).Error; err != nil {
			logger.Errorf("db operation failed: %v", err)
		}
		if err := db.Delete(&legacyRole).Error; err != nil {
			logger.Errorf("Delete failed: %v", err)
		}
	}
}

func InvalidateRBACCache(userID uint) {
	if rbacService == nil || userID == 0 {
		return
	}
	rbacService.InvalidateCache(userID)
}

// RequirePermission creates a middleware that checks if user has required permission
func RequirePermission(permissionCode string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "请先登录")
			c.Abort()
			return
		}

		if rbacService == nil || !rbacService.HasPermission(userID, permissionCode) {
			response.Forbidden(c, "Permission denied: "+permissionCode)
			c.Abort()
			return
		}

		c.Next()
	}
}

// RequireAnyPermission creates a middleware that checks if user has ANY of the required permissions
func RequireAnyPermission(permissions ...string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "请先登录")
			c.Abort()
			return
		}

		for _, perm := range permissions {
			if rbacService != nil && rbacService.HasPermission(userID, perm) {
				c.Next()
				return
			}
		}

		response.Forbidden(c, "权限不足")
		c.Abort()
	}
}

// RequireProjectPermission checks permission in project scope (platform + project roles).
func RequireProjectPermission(permissionCode string, projectParam string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "请先登录")
			c.Abort()
			return
		}

		if rbacService == nil {
			response.ServerError(c, "RBAC service not initialized")
			c.Abort()
			return
		}

		projectIDStr := c.Param(projectParam)
		projectID := parseUint(projectIDStr)
		if projectID == 0 {
			response.BadRequest(c, "Invalid project ID")
			c.Abort()
			return
		}

		if !rbacService.HasProjectPermission(userID, projectID, permissionCode) {
			response.Forbidden(c, fmt.Sprintf("Permission denied: %s (project: %d)", permissionCode, projectID))
			c.Abort()
			return
		}

		c.Next()
	}
}

// RequireRepoPermission resolves repo -> project and checks permission in that project scope.
func RequireRepoPermission(permissionCode string, repoParam string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "请先登录")
			c.Abort()
			return
		}

		if rbacService == nil {
			response.ServerError(c, "RBAC service not initialized")
			c.Abort()
			return
		}

		repoIDStr := c.Param(repoParam)
		repoID := parseUint(repoIDStr)
		if repoID == 0 {
			response.BadRequest(c, "无效的仓库ID")
			c.Abort()
			return
		}

		var repo model.ProjectRepo
		if err := rbacService.DB().Select("id, project_id").Where("id = ?", repoID).First(&repo).Error; err != nil {
			response.NotFound(c, "仓库不存在")
			c.Abort()
			return
		}

		if !rbacService.HasProjectPermission(userID, repo.ProjectID, permissionCode) {
			response.Forbidden(c, fmt.Sprintf("Permission denied: %s (project: %d)", permissionCode, repo.ProjectID))
			c.Abort()
			return
		}

		c.Next()
	}
}

// RequireDefectPermission resolves defect -> iteration -> project and checks permission in that project scope.
func RequireDefectPermission(permissionCode string, defectParam string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "Authentication required")
			c.Abort()
			return
		}

		if rbacService == nil {
			response.ServerError(c, "RBAC service not initialized")
			c.Abort()
			return
		}

		defectIDStr := c.Param(defectParam)
		defectID := parseUint(defectIDStr)
		if defectID == 0 {
			response.BadRequest(c, "无效的缺陷ID")
			c.Abort()
			return
		}

		var result struct {
			ProjectID uint
		}
		if err := rbacService.DB().
			Table("defects").
			Select("iterations.project_id AS project_id").
			Joins("JOIN iterations ON iterations.id = defects.iteration_id").
			Where("defects.id = ?", defectID).
			Scan(&result).Error; err != nil || result.ProjectID == 0 {
			response.NotFound(c, "缺陷不存在")
			c.Abort()
			return
		}

		if !rbacService.HasProjectPermission(userID, result.ProjectID, permissionCode) {
			response.Forbidden(c, fmt.Sprintf("Permission denied: %s (project: %d)", permissionCode, result.ProjectID))
			c.Abort()
			return
		}

		c.Next()
	}
}

// RequireDefectListPermission resolves project from query(projectId/iterationId) and checks project scope permission.
func RequireDefectListPermission(permissionCode string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "Authentication required")
			c.Abort()
			return
		}

		projectID := parseUint(c.Query("projectId"))
		if projectID == 0 {
			iterationID := parseUint(c.Query("iterationId"))
			if iterationID > 0 {
				projectID = resolveProjectIDByIteration(iterationID)
				if projectID == 0 {
					response.BadRequest(c, "Invalid iteration ID")
					c.Abort()
					return
				}
			}
		}

		// Fallback for truly global list requests: only users with explicit platform-level permission can pass.
		if projectID == 0 {
			if rbacService == nil || !rbacService.HasPermission(userID, permissionCode) {
				response.Forbidden(c, "Permission denied: "+permissionCode)
				c.Abort()
				return
			}
			c.Next()
			return
		}

		if !rbacService.HasProjectPermission(userID, projectID, permissionCode) {
			response.Forbidden(c, fmt.Sprintf("Permission denied: %s (project: %d)", permissionCode, projectID))
			c.Abort()
			return
		}

		c.Next()
	}
}

// RequireDefectCreatePermission resolves project from body.iterationId and checks project scope permission.
func RequireDefectCreatePermission(permissionCode string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "Authentication required")
			c.Abort()
			return
		}

		var req struct {
			IterationID uint `json:"iterationId" binding:"required"`
		}
		if err := c.ShouldBindBodyWith(&req, binding.JSON); err != nil {
			response.BadRequest(c, "无效的请求体")
			c.Abort()
			return
		}

		projectID := resolveProjectIDByIteration(req.IterationID)
		if projectID == 0 {
			response.BadRequest(c, "Invalid iteration ID")
			c.Abort()
			return
		}

		if !rbacService.HasProjectPermission(userID, projectID, permissionCode) {
			response.Forbidden(c, fmt.Sprintf("Permission denied: %s (project: %d)", permissionCode, projectID))
			c.Abort()
			return
		}

		c.Next()
	}
}

// RequireRole creates a middleware that checks if user has a specific role
func RequireRole(roleName string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "Authentication required")
			c.Abort()
			return
		}

		if rbacService == nil {
			response.ServerError(c, "RBAC service not initialized")
			c.Abort()
			return
		}

		if !rbacService.HasRole(userID, roleName) {
			response.Forbidden(c, "未找到所需角色: "+roleName)
			c.Abort()
			return
		}

		c.Next()
	}
}

func resolveProjectIDByIteration(iterationID uint) uint {
	var iteration model.Iteration
	if err := rbacService.DB().Select("project_id").Where("id = ?", iterationID).First(&iteration).Error; err != nil {
		return 0
	}
	return iteration.ProjectID
}

// RequireProjectRole checks if user has specific role within a project
func RequireProjectRole(roleName string, projectParam string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "Authentication required")
			c.Abort()
			return
		}

		if rbacService == nil {
			response.ServerError(c, "RBAC service not initialized")
			c.Abort()
			return
		}

		projectIDStr := c.Param(projectParam)
		projectID := parseUint(projectIDStr)
		if projectID == 0 {
			response.BadRequest(c, "Invalid project ID")
			c.Abort()
			return
		}

		if !rbacService.HasScopedRole(userID, roleName, "project", projectID) {
			response.Forbidden(c, "需要项目角色: "+roleName)
			c.Abort()
			return
		}

		c.Next()
	}
}

// IsResourceOwner checks if current user owns the resource or has admin role
func IsResourceOwner(ownerIDField string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "Authentication required")
			c.Abort()
			return
		}

		resourceOwnerID := parseUint(c.Param(ownerIDField))
		if resourceOwnerID == 0 {
			response.Forbidden(c, "Access denied")
			c.Abort()
			return
		}
		if userID != resourceOwnerID {
			if rbacService == nil || !rbacService.IsAdmin(userID) {
				response.Forbidden(c, "Access denied")
				c.Abort()
				return
			}
		}

		c.Next()
	}
}

// LoadUserPermissions loads user permissions into context for frontend use
func LoadUserPermissions() gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			c.Next()
			return
		}

		if rbacService == nil {
			response.ServerError(c, "RBAC service not initialized")
			c.Abort()
			return
		}

		perms := rbacService.GetUserPermissions(userID)
		permCodes := make([]string, len(perms))
		for i, p := range perms {
			permCodes[i] = p.Code
		}
		c.Set("permissions", permCodes)

		roles := rbacService.GetUserRoles(userID)
		roleNames := make([]string, len(roles))
		for i, r := range roles {
			roleNames[i] = r.Name
		}
		c.Set("roles", roleNames)

		c.Next()
	}
}

// RequireReportPermission resolves report -> defect -> project and checks permission in that project scope.
func RequireReportPermission(permissionCode string, reportParam string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "Authentication required")
			c.Abort()
			return
		}

		if rbacService == nil {
			response.ServerError(c, "RBAC service not initialized")
			c.Abort()
			return
		}

		reportIDStr := c.Param(reportParam)
		reportID := parseUint(reportIDStr)
		if reportID == 0 {
			response.BadRequest(c, "无效的报告ID")
			c.Abort()
			return
		}

		var result struct {
			ProjectID uint
		}
		if err := rbacService.DB().
			Table("analysis_reports").
			Select("iterations.project_id AS project_id").
			Joins("JOIN defects ON defects.id = analysis_reports.defect_id").
			Joins("JOIN iterations ON iterations.id = defects.iteration_id").
			Where("analysis_reports.id = ?", reportID).
			Scan(&result).Error; err != nil || result.ProjectID == 0 {
			response.NotFound(c, "报告不存在")
			c.Abort()
			return
		}

		if !rbacService.HasProjectPermission(userID, result.ProjectID, permissionCode) {
			response.Forbidden(c, fmt.Sprintf("Permission denied: %s (project: %d)", permissionCode, result.ProjectID))
			c.Abort()
			return
		}

		c.Next()
	}
}

// RequireFixTaskPermission resolves fix_task -> defect -> project and checks permission in that project scope.
func RequireFixTaskPermission(permissionCode string, taskParam string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "Authentication required")
			c.Abort()
			return
		}

		if rbacService == nil {
			response.ServerError(c, "RBAC service not initialized")
			c.Abort()
			return
		}

		taskIDStr := c.Param(taskParam)
		taskID := parseUint(taskIDStr)
		if taskID == 0 {
			response.BadRequest(c, "无效的任务ID")
			c.Abort()
			return
		}

		var result struct {
			ProjectID uint
		}
		if err := rbacService.DB().
			Table("fix_tasks").
			Select("iterations.project_id AS project_id").
			Joins("JOIN defects ON defects.id = fix_tasks.defect_id").
			Joins("JOIN iterations ON iterations.id = defects.iteration_id").
			Where("fix_tasks.id = ?", taskID).
			Scan(&result).Error; err != nil || result.ProjectID == 0 {
			response.NotFound(c, "修复任务不存在")
			c.Abort()
			return
		}

		if !rbacService.HasProjectPermission(userID, result.ProjectID, permissionCode) {
			response.Forbidden(c, fmt.Sprintf("Permission denied: %s (project: %d)", permissionCode, result.ProjectID))
			c.Abort()
			return
		}

		c.Next()
	}
}

// RequireCollaborationTaskPermission resolves collaboration_task -> defect -> project and checks permission.
func RequireCollaborationTaskPermission(permissionCode string, taskParam string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "Authentication required")
			c.Abort()
			return
		}

		if rbacService == nil {
			response.ServerError(c, "RBAC service not initialized")
			c.Abort()
			return
		}

		taskIDStr := c.Param(taskParam)
		taskID := parseUint(taskIDStr)
		if taskID == 0 {
			response.BadRequest(c, "无效的任务ID")
			c.Abort()
			return
		}

		var result struct {
			ProjectID uint
		}
		if err := rbacService.DB().
			Table("collaboration_tasks").
			Select("iterations.project_id AS project_id").
			Joins("JOIN defects ON defects.id = collaboration_tasks.defect_id").
			Joins("JOIN iterations ON iterations.id = defects.iteration_id").
			Where("collaboration_tasks.id = ?", taskID).
			Scan(&result).Error; err != nil || result.ProjectID == 0 {
			response.NotFound(c, "协作任务不存在")
			c.Abort()
			return
		}

		if !rbacService.HasProjectPermission(userID, result.ProjectID, permissionCode) {
			response.Forbidden(c, fmt.Sprintf("Permission denied: %s (project: %d)", permissionCode, result.ProjectID))
			c.Abort()
			return
		}

		c.Next()
	}
}

// RequireAnalysisPermission resolves defectID from request body and checks project scope permission.
func RequireAnalysisPermission(permissionCode string) gin.HandlerFunc {
	return func(c *gin.Context) {
		userID := GetUserID(c)
		if userID == 0 {
			response.Unauthorized(c, "Authentication required")
			c.Abort()
			return
		}

		if rbacService == nil {
			response.ServerError(c, "RBAC service not initialized")
			c.Abort()
			return
		}

		var defectID uint

		var req struct {
			DefectID uint `json:"defectId"`
		}
		if err := c.ShouldBindBodyWith(&req, binding.JSON); err == nil && req.DefectID > 0 {
			defectID = req.DefectID
		}

		if defectID == 0 {
			if idStr := c.Param("id"); idStr != "" {
				if id, err := strconv.ParseUint(idStr, 10, 64); err == nil && id > 0 {
					defectID = uint(id)
				}
			}
		}

		if defectID == 0 && c.Request.Method == http.MethodGet && permissionCode == "agents:analyze" {
			c.Next()
			return
		}

		if defectID == 0 {
			response.BadRequest(c, "缺陷ID不能为空")
			c.Abort()
			return
		}

		var result struct {
			ProjectID uint
		}
		if err := rbacService.DB().
			Table("defects").
			Select("iterations.project_id AS project_id").
			Joins("JOIN iterations ON iterations.id = defects.iteration_id").
			Where("defects.id = ?", defectID).
			Scan(&result).Error; err != nil || result.ProjectID == 0 {
			response.NotFound(c, "缺陷不存在")
			c.Abort()
			return
		}

		if !rbacService.HasProjectPermission(userID, result.ProjectID, permissionCode) {
			response.Forbidden(c, fmt.Sprintf("Permission denied: %s (project: %d)", permissionCode, result.ProjectID))
			c.Abort()
			return
		}

		c.Next()
	}
}

func parseUint(s string) uint {
	val, err := strconv.ParseUint(s, 10, 64)
	if err != nil {
		return 0
	}
	return uint(val)
}

func getBearerToken(c *gin.Context) string {
	authHeader := c.GetHeader("Authorization")
	if authHeader == "" {
		return ""
	}
	parts := strings.SplitN(authHeader, " ", 2)
	if len(parts) != 2 || parts[0] != "Bearer" {
		return ""
	}
	return parts[1]
}
