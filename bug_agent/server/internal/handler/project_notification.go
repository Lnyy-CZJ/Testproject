package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"errors"
	"io"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type ProjectNotificationHandler struct {
	svc *service.ProjectNotificationService
}

func NewProjectNotificationHandler(db *gorm.DB) *ProjectNotificationHandler {
	return &ProjectNotificationHandler{
		svc: service.NewProjectNotificationService(db),
	}
}

func (h *ProjectNotificationHandler) GetPolicies(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil || projectID == 0 {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	policies, err := h.svc.GetPolicies(uint(projectID))
	if err != nil {
		response.ServerError(c, "获取项目通知策略失败")
		return
	}
	response.Success(c, policies)
}

func (h *ProjectNotificationHandler) BatchUpdatePolicies(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil || projectID == 0 {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req struct {
		Policies []struct {
			Category     string `json:"category" binding:"required"`
			InAppEnabled bool   `json:"inAppEnabled"`
			EmailEnabled bool   `json:"emailEnabled"`
			WebhookID    *uint  `json:"webhookId"`
		} `json:"policies" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	inputs := make([]service.ProjectNotificationPolicyInput, 0, len(req.Policies))
	for _, item := range req.Policies {
		inputs = append(inputs, service.ProjectNotificationPolicyInput{
			Category:     strings.TrimSpace(item.Category),
			InAppEnabled: item.InAppEnabled,
			EmailEnabled: item.EmailEnabled,
			WebhookID:    item.WebhookID,
		})
	}

	policies, err := h.svc.BatchUpdatePolicies(uint(projectID), inputs)
	if err != nil {
		switch {
		case errors.Is(err, service.ErrInvalidNotificationCategory):
			response.BadRequest(c, "无效的通知类别")
		case errors.Is(err, service.ErrProjectNotificationWebhookNotFound):
			response.BadRequest(c, "所选项目 Webhook 不存在")
		default:
			response.ServerError(c, "更新项目通知策略失败")
		}
		return
	}
	response.Success(c, policies)
}

func (h *ProjectNotificationHandler) ListWebhooks(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil || projectID == 0 {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	webhooks, err := h.svc.ListWebhooks(uint(projectID))
	if err != nil {
		response.ServerError(c, "获取项目 Webhook 失败")
		return
	}
	response.Success(c, webhooks)
}

func (h *ProjectNotificationHandler) CreateWebhook(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil || projectID == 0 {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req struct {
		Name    string `json:"name" binding:"required"`
		URL     string `json:"url" binding:"required"`
		Secret  string `json:"secret"`
		Enabled *bool  `json:"enabled"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	enabled := true
	if req.Enabled != nil {
		enabled = *req.Enabled
	}

	webhook, err := h.svc.CreateWebhook(uint(projectID), service.ProjectWebhookInput{
		Name:    req.Name,
		URL:     req.URL,
		Secret:  req.Secret,
		Enabled: enabled,
	})
	if err != nil {
		if errors.Is(err, service.ErrInvalidProjectNotificationParams) {
			response.BadRequest(c, "Webhook 参数不完整")
			return
		}
		response.ServerError(c, "创建项目 Webhook 失败")
		return
	}
	response.Created(c, webhook)
}

func (h *ProjectNotificationHandler) UpdateWebhook(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil || projectID == 0 {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	webhookID, err := strconv.ParseUint(c.Param("webhookId"), 10, 64)
	if err != nil || webhookID == 0 {
		response.BadRequest(c, "无效的 Webhook ID")
		return
	}

	var req struct {
		Name    string `json:"name" binding:"required"`
		URL     string `json:"url" binding:"required"`
		Secret  string `json:"secret"`
		Enabled *bool  `json:"enabled"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	enabled := true
	if req.Enabled != nil {
		enabled = *req.Enabled
	}

	webhook, err := h.svc.UpdateWebhook(uint(projectID), uint(webhookID), service.ProjectWebhookInput{
		Name:    req.Name,
		URL:     req.URL,
		Secret:  req.Secret,
		Enabled: enabled,
	})
	if err != nil {
		switch {
		case errors.Is(err, service.ErrProjectNotificationWebhookNotFound):
			response.NotFound(c, "项目 Webhook 不存在")
		case errors.Is(err, service.ErrInvalidProjectNotificationParams):
			response.BadRequest(c, "Webhook 参数不完整")
		default:
			response.ServerError(c, "更新项目 Webhook 失败")
		}
		return
	}
	response.Success(c, webhook)
}

func (h *ProjectNotificationHandler) DeleteWebhook(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil || projectID == 0 {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	webhookID, err := strconv.ParseUint(c.Param("webhookId"), 10, 64)
	if err != nil || webhookID == 0 {
		response.BadRequest(c, "无效的 Webhook ID")
		return
	}

	if err := h.svc.DeleteWebhook(uint(projectID), uint(webhookID)); err != nil {
		if errors.Is(err, service.ErrProjectNotificationWebhookNotFound) {
			response.NotFound(c, "项目 Webhook 不存在")
			return
		}
		response.ServerError(c, "删除项目 Webhook 失败")
		return
	}
	response.Success(c, gin.H{"message": "项目 Webhook 已删除"})
}

func (h *ProjectNotificationHandler) TestWebhook(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil || projectID == 0 {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	webhookID, err := strconv.ParseUint(c.Param("webhookId"), 10, 64)
	if err != nil || webhookID == 0 {
		response.BadRequest(c, "无效的 Webhook ID")
		return
	}

	var req struct {
		Event string `json:"event"`
	}
	if err := c.ShouldBindJSON(&req); err != nil && !errors.Is(err, io.EOF) {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	if err := h.svc.TestWebhook(uint(projectID), uint(webhookID), req.Event); err != nil {
		switch {
		case errors.Is(err, service.ErrProjectNotificationWebhookNotFound):
			response.NotFound(c, "项目 Webhook 不存在")
		default:
			response.ServerError(c, "测试项目 Webhook 失败")
		}
		return
	}
	response.Success(c, gin.H{"message": "项目 Webhook 测试成功"})
}
