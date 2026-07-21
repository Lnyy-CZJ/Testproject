package handler

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

const defaultAuditLogLimit = 20

// AuditHandler handles audit log queries
type AuditHandler struct {
	db       *gorm.DB
	auditSvc *service.AuditService
}

// NewAuditHandler creates a new audit handler
func NewAuditHandler(db *gorm.DB) *AuditHandler {
	return &AuditHandler{
		db:       db,
		auditSvc: service.NewAuditService(db),
	}
}

// ListAuditLogs retrieves audit logs with filtering and pagination
func (h *AuditHandler) ListAuditLogs(c *gin.Context) {
	var params service.AuditQueryParams

	params.Page = 1
	if page, err := parseIntParam(c, "page"); err == nil && page > 0 {
		params.Page = page
	}

	params.PageSize = 20
	if pageSize, err := parseIntParam(c, "pageSize"); err == nil && pageSize > 0 && pageSize <= 100 {
		params.PageSize = pageSize
	}

	if userID, err := parseUintParam(c, "userId"); err == nil && userID > 0 {
		params.UserID = userID
	}
	params.Action = c.DefaultQuery("action", "")
	params.TargetType = c.DefaultQuery("targetType", "")
	if targetID, err := parseUintParam(c, "targetId"); err == nil && targetID > 0 {
		params.TargetID = targetID
	}
	params.StartDate = c.DefaultQuery("startDate", "")
	params.EndDate = c.DefaultQuery("endDate", "")

	logs, total, err := h.auditSvc.QueryLogs(params)
	if err != nil {
		response.ServerErrorWithLog(c, err, "查询失败")
		return
	}

	response.Success(c, gin.H{
		"items":    logs,
		"total":    total,
		"page":     params.Page,
		"pageSize": params.PageSize,
	})
}

// GetRecentAuditLogs gets recent logs for a specific target
func (h *AuditHandler) GetRecentAuditLogs(c *gin.Context) {
	limit := defaultAuditLogLimit
	if l, err := parseIntParam(c, "limit"); err == nil && l > 0 && l <= 100 {
		limit = l
	}

	targetType := c.Query("targetType")
	targetID, _ := parseUintParam(c, "targetId")

	logs := h.auditSvc.GetRecentLogs(limit, targetType, targetID)

	response.Success(c, gin.H{
		"items": logs,
		"total": len(logs),
	})
}

// GetAuditStats returns aggregated statistics about audit logs
func (h *AuditHandler) GetAuditStats(c *gin.Context) {
	type ActionCount struct {
		Action string `json:"action"`
		Count  int64  `json:"count"`
	}

	var actionCounts []ActionCount
	if err := h.db.Model(&model.AuditLog{}).
		Select("action, COUNT(*) as count").
		Group("action").
		Order("count DESC").
		Limit(20).
		Scan(&actionCounts).Error; err != nil {
		response.ServerError(c, "查询操作统计失败")
		return
	}

	type UserCount struct {
		UserID   uint   `json:"userId"`
		Username string `json:"username"`
		Count    int64  `json:"count"`
	}

	var userCounts []UserCount
	if err := h.db.Model(&model.AuditLog{}).
		Select("user_id, username, COUNT(*) as count").
		Group("user_id, username").
		Order("count DESC").
		Limit(10).
		Scan(&userCounts).Error; err != nil {
		response.ServerError(c, "查询用户统计失败")
		return
	}

	var totalLogs int64
	if err := h.db.Model(&model.AuditLog{}).Count(&totalLogs).Error; err != nil {
		response.ServerError(c, "查询审计日志总数失败")
		return
	}

	response.Success(c, gin.H{
		"totalLogs":   totalLogs,
		"topActions":  actionCounts,
		"activeUsers": userCounts,
	})
}

func parseIntParam(c *gin.Context, key string) (int, error) {
	val := c.DefaultQuery(key, "0")
	return strconv.Atoi(val)
}

func parseUintParam(c *gin.Context, key string) (uint, error) {
	val := c.DefaultQuery(key, "0")
	v, err := strconv.ParseUint(val, 10, 64)
	if err != nil {
		return 0, err
	}
	return uint(v), nil
}
