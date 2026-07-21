package handler

import (
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type RBACHandler struct {
	db       *gorm.DB
	rbacSvc  *service.RBACService
	auditSvc *service.AuditService
}

func NewRBACHandler(db *gorm.DB) *RBACHandler {
	return &RBACHandler{
		db:       db,
		rbacSvc:  service.NewRBACService(db),
		auditSvc: service.NewAuditService(db),
	}
}

func (h *RBACHandler) ListRoles(c *gin.Context) {
	var roles []model.Role
	query := h.db.Preload("Permissions", func(db *gorm.DB) *gorm.DB {
		return db.Order("module, code")
	})
	if tier := c.Query("tier"); tier != "" {
		query = query.Where("tier = ?", tier)
	}
	if err := query.Find(&roles).Error; err != nil {
		response.ServerError(c, "查询角色列表失败")
		return
	}
	response.Success(c, roles)
}

func (h *RBACHandler) CreateRole(c *gin.Context) {
	var req struct {
		Name        string `json:"name" binding:"required"`
		DisplayName string `json:"displayName" binding:"required"`
		Tier        string `json:"tier" binding:"required"`
		Description string `json:"description"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "无效的请求: "+err.Error())
		return
	}

	if req.Tier != "platform" && req.Tier != "project" {
		response.BadRequest(c, "tier 必须为 platform 或 project")
		return
	}

	var existing model.Role
	if err := h.db.Where("name = ?", req.Name).First(&existing).Error; err == nil {
		response.BadRequest(c, "角色标识已存在")
		return
	}

	role := model.Role{
		Name:        req.Name,
		DisplayName: req.DisplayName,
		Tier:        req.Tier,
		Description: req.Description,
		IsSystem:    false,
	}
	if err := h.db.Create(&role).Error; err != nil {
		response.ServerErrorWithLog(c, err, "创建角色失败")
		return
	}

	middleware.AuditAction(c, "create_role", "role", role.ID, nil, map[string]interface{}{
		"name":        req.Name,
		"displayName": req.DisplayName,
		"tier":        req.Tier,
	})

	response.Created(c, role)
}

func (h *RBACHandler) GetRole(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的角色ID")
		return
	}
	var role model.Role
	if err := h.db.Preload("Permissions", func(db *gorm.DB) *gorm.DB {
		return db.Order("module, code")
	}).First(&role, id).Error; err != nil {
		response.NotFound(c, "角色不存在")
		return
	}
	response.Success(c, role)
}

func (h *RBACHandler) UpdateRole(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的角色ID")
		return
	}
	var role model.Role
	if err := h.db.First(&role, id).Error; err != nil {
		response.NotFound(c, "角色不存在")
		return
	}
	if role.IsSystem {
		response.BadRequest(c, "系统角色不可修改")
		return
	}
	var req struct {
		DisplayName string `json:"displayName"`
		Tier        string `json:"tier"`
		Description string `json:"description"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "无效的请求: "+err.Error())
		return
	}
	if req.Tier != "" && req.Tier != "platform" && req.Tier != "project" {
		response.BadRequest(c, "tier 必须为 platform 或 project")
		return
	}
	updates := map[string]interface{}{}
	if req.DisplayName != "" {
		updates["display_name"] = req.DisplayName
	}
	if req.Tier != "" {
		updates["tier"] = req.Tier
	}
	if req.Description != "" {
		updates["description"] = req.Description
	}
	if len(updates) > 0 {
		if err := h.db.Model(&role).Updates(updates).Error; err != nil {
			logger.Errorf("update failed: %v", err)
			response.ServerError(c, "更新角色失败")
			return
		}
	}
	if err := h.db.Preload("Permissions", func(db *gorm.DB) *gorm.DB {
		return db.Order("module, code")
	}).First(&role, id).Error; err != nil {
		logger.Errorf("重新查询角色失败: %v", err)
	}

	middleware.AuditAction(c, "update_role", "role", role.ID, nil, map[string]interface{}{
		"displayName": req.DisplayName,
		"description": req.Description,
	})

	response.Success(c, role)
}

func (h *RBACHandler) UpdateRolePermissions(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的角色ID")
		return
	}
	var role model.Role
	if err := h.db.First(&role, id).Error; err != nil {
		response.NotFound(c, "角色不存在")
		return
	}
	if role.IsSystem {
		response.BadRequest(c, "系统角色权限不可修改")
		return
	}
	var req struct {
		PermissionIDs []uint `json:"permissionIds" binding:"required,max=100"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "无效的请求: "+err.Error())
		return
	}

	var perms []model.Permission
	if err := h.db.Where("id IN ?", req.PermissionIDs).Find(&perms).Error; err != nil {
		response.ServerError(c, "查询权限失败")
		return
	}

	if err := h.db.Model(&role).Association("Permissions").Replace(perms); err != nil {
		response.ServerErrorWithLog(c, err, "更新权限失败")
		return
	}

	if err := h.db.Preload("Permissions", func(db *gorm.DB) *gorm.DB {
		return db.Order("module, code")
	}).First(&role, id).Error; err != nil {
		logger.Errorf("重新查询角色失败: %v", err)
	}

	var affectedUserIDs []uint
	if err := h.db.Model(&model.UserRole{}).Where("role_id = ?", id).Pluck("user_id", &affectedUserIDs).Error; err != nil {
		logger.Errorf("查询受影响用户失败: %v", err)
	}
	for _, uid := range affectedUserIDs {
		middleware.InvalidateRBACCache(uid)
	}

	middleware.AuditAction(c, "update_role_permissions", "role", role.ID, nil, map[string]interface{}{
		"permissionIds": req.PermissionIDs,
	})

	response.Success(c, role)
}

func (h *RBACHandler) ListPermissions(c *gin.Context) {
	perms := h.rbacSvc.GetAllPermissions()
	response.Success(c, perms)
}

func (h *RBACHandler) GetUserPermissions(c *gin.Context) {
	userID := middleware.GetUserID(c)
	if userID == 0 {
		response.Unauthorized(c, "未登录")
		return
	}
	perms := h.rbacSvc.GetUserPermissions(userID)
	response.Success(c, perms)
}

func (h *RBACHandler) GetUserRoles(c *gin.Context) {
	userID := middleware.GetUserID(c)
	if userID == 0 {
		response.Unauthorized(c, "未登录")
		return
	}
	roles := h.rbacSvc.GetUserRoles(userID)
	response.Success(c, roles)
}

func (h *RBACHandler) AssignUserRole(c *gin.Context) {
	var req struct {
		UserID    uint   `json:"userId" binding:"required"`
		RoleID    uint   `json:"roleId" binding:"required"`
		ScopeType string `json:"scopeType"`
		ScopeID   uint   `json:"scopeId"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "无效的请求: "+err.Error())
		return
	}

	currentUserID := middleware.GetUserID(c)

	if req.ScopeType == "" {
		req.ScopeType = "global"
	}

	err := h.rbacSvc.AssignRole(req.UserID, req.RoleID, req.ScopeType, req.ScopeID, currentUserID)
	if err != nil {
		response.ServerErrorWithLog(c, err, "分配角色失败")
		return
	}

	middleware.AuditAction(c, "assign_role", "user", req.UserID, nil, map[string]interface{}{
		"roleId":    req.RoleID,
		"scopeType": req.ScopeType,
		"scopeId":   req.ScopeID,
	})

	response.Success(c, gin.H{"message": "角色分配成功"})
}

func (h *RBACHandler) RemoveUserRole(c *gin.Context) {
	userIDStr := c.Param("userId")
	roleIDStr := c.Param("roleId")

	userID, err := strconv.ParseUint(userIDStr, 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的用户ID")
		return
	}
	roleID, err := strconv.ParseUint(roleIDStr, 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的角色ID")
		return
	}

	var req struct {
		ScopeType string `json:"scopeType"`
		ScopeID   uint   `json:"scopeId"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	err = h.rbacSvc.RemoveRole(uint(userID), uint(roleID), req.ScopeType, req.ScopeID)
	if err != nil {
		response.ServerErrorWithLog(c, err, "移除角色失败")
		return
	}

	middleware.AuditAction(c, "remove_role", "user", uint(userID), nil, map[string]interface{}{
		"roleId": roleID,
	})

	response.Success(c, gin.H{"message": "角色移除成功"})
}

func (h *RBACHandler) CheckPermission(c *gin.Context) {
	permissionCode := c.Query("code")
	if permissionCode == "" {
		response.BadRequest(c, "权限代码不能为空")
		return
	}

	userID := middleware.GetUserID(c)
	projectIDStr := c.Query("projectId")
	projectID := uint64(0)
	if projectIDStr != "" {
		var err error
		projectID, err = strconv.ParseUint(projectIDStr, 10, 64)
		if err != nil {
			response.BadRequest(c, "无效的项目ID")
			return
		}
	}

	hasPerm := false
	if projectID > 0 {
		hasPerm = h.rbacSvc.HasProjectPermission(userID, uint(projectID), permissionCode)
	} else {
		hasPerm = h.rbacSvc.HasPermission(userID, permissionCode)
	}

	response.Success(c, gin.H{
		"hasPermission":  hasPerm,
		"permissionCode": permissionCode,
	})
}
