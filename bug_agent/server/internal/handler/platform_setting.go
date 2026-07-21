package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type PlatformSettingsHandler struct {
	svc *service.PlatformSettingsService
}

func NewPlatformSettingsHandler(db *gorm.DB) *PlatformSettingsHandler {
	return &PlatformSettingsHandler{
		svc: service.NewPlatformSettingsService(db),
	}
}

func (h *PlatformSettingsHandler) GetEmailSettings(c *gin.Context) {
	settings, err := h.svc.GetEmailSettings()
	if err != nil {
		response.ServerError(c, "获取邮件配置失败")
		return
	}
	response.Success(c, settings)
}

func (h *PlatformSettingsHandler) UpdateEmailSettings(c *gin.Context) {
	var req struct {
		SMTPHost     string `json:"smtpHost" binding:"required"`
		SMTPPort     int    `json:"smtpPort"`
		SMTPUser     string `json:"smtpUser"`
		SMTPPassword string `json:"smtpPassword"`
		SMTPFrom     string `json:"smtpFrom" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	settings, err := h.svc.SaveEmailSettings(getUserID(c), service.PlatformEmailSettingsInput{
		SMTPHost:     req.SMTPHost,
		SMTPPort:     req.SMTPPort,
		SMTPUser:     req.SMTPUser,
		SMTPPassword: req.SMTPPassword,
		SMTPFrom:     req.SMTPFrom,
	})
	if err != nil {
		response.ServerError(c, "保存邮件配置失败")
		return
	}
	response.Success(c, settings)
}

func (h *PlatformSettingsHandler) TestEmailSettings(c *gin.Context) {
	var req struct {
		SMTPHost     string `json:"smtpHost" binding:"required"`
		SMTPPort     int    `json:"smtpPort"`
		SMTPUser     string `json:"smtpUser"`
		SMTPPassword string `json:"smtpPassword"`
		SMTPFrom     string `json:"smtpFrom" binding:"required"`
		To           string `json:"to" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	if err := h.svc.TestEmailSettings(service.PlatformEmailSettingsInput{
		SMTPHost:     req.SMTPHost,
		SMTPPort:     req.SMTPPort,
		SMTPUser:     req.SMTPUser,
		SMTPPassword: req.SMTPPassword,
		SMTPFrom:     req.SMTPFrom,
	}, req.To); err != nil {
		response.ServerErrorWithLog(c, err, "测试邮件发送失败")
		return
	}
	response.Success(c, gin.H{"message": "测试邮件发送成功"})
}
