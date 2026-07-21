package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"errors"
	"io"
	"net/http"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type NotificationPrefHandler struct {
	prefService        *service.NotificationPrefService
	userWebhookService *service.UserWebhookService
}

func NewNotificationPrefHandler(db *gorm.DB) *NotificationPrefHandler {
	return &NotificationPrefHandler{
		prefService:        service.NewNotificationPrefService(db),
		userWebhookService: service.NewUserWebhookService(db),
	}
}

func (h *NotificationPrefHandler) GetPreferences(c *gin.Context) {
	userID := getUserID(c)
	prefs, err := h.prefService.GetPreferences(userID)
	if err != nil {
		response.ServerError(c, "获取通知偏好失败")
		return
	}
	response.Success(c, prefs)
}

func (h *NotificationPrefHandler) UpdatePreference(c *gin.Context) {
	userID := getUserID(c)
	var req struct {
		ID       uint   `json:"id" binding:"required"`
		Channels string `json:"channels" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	pref, err := h.prefService.UpdatePreference(userID, req.ID, req.Channels)
	if err != nil {
		if errors.Is(err, service.ErrInvalidNotificationCategory) || errors.Is(err, service.ErrInvalidNotificationChannels) {
			response.BadRequest(c, "无效的通知偏好参数")
			return
		}
		response.ServerError(c, "更新通知偏好失败")
		return
	}
	response.Success(c, pref)
}

func (h *NotificationPrefHandler) BatchUpdate(c *gin.Context) {
	userID := getUserID(c)
	var req struct {
		Updates map[string]string `json:"updates" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	if err := h.prefService.BatchUpdate(userID, req.Updates); err != nil {
		if errors.Is(err, service.ErrInvalidNotificationCategory) || errors.Is(err, service.ErrInvalidNotificationChannels) {
			response.BadRequest(c, "无效的通知偏好参数")
			return
		}
		response.ServerError(c, "批量更新通知偏好失败")
		return
	}
	response.Success(c, gin.H{"message": "通知偏好已更新"})
}

func (h *NotificationPrefHandler) GetWebhookSettings(c *gin.Context) {
	userID := getUserID(c)
	view, err := h.userWebhookService.Get(userID)
	if err != nil {
		response.ServerError(c, "获取个人Webhook配置失败")
		return
	}
	response.Success(c, view)
}

func (h *NotificationPrefHandler) UpdateWebhookSettings(c *gin.Context) {
	userID := getUserID(c)
	var req struct {
		URL     string  `json:"url"`
		Secret  *string `json:"secret"`
		Enabled bool    `json:"enabled"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	view, err := h.userWebhookService.Save(userID, service.UserWebhookSettingsInput{
		URL:     req.URL,
		Secret:  req.Secret,
		Enabled: req.Enabled,
	})
	if err != nil {
		response.ServerError(c, "保存个人Webhook配置失败")
		return
	}
	response.Success(c, view)
}

func (h *NotificationPrefHandler) TestWebhookSettings(c *gin.Context) {
	userID := getUserID(c)
	var req struct {
		URL     string  `json:"url"`
		Secret  *string `json:"secret"`
		Enabled bool    `json:"enabled"`
	}
	if err := c.ShouldBindJSON(&req); err != nil && !errors.Is(err, io.EOF) {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	if err := h.userWebhookService.Test(userID, service.UserWebhookSettingsInput{
		URL:     req.URL,
		Secret:  req.Secret,
		Enabled: req.Enabled,
	}); err != nil {
		switch {
		case errors.Is(err, service.ErrUserWebhookURLRequired):
			response.BadRequest(c, err.Error())
		case errors.Is(err, service.ErrUserWebhookDispatchFailed):
			response.Error(c, http.StatusBadGateway, http.StatusBadGateway, err.Error())
		default:
			response.ServerError(c, "个人Webhook测试失败")
		}
		return
	}
	response.Success(c, gin.H{"success": true, "message": "个人Webhook测试成功"})
}
