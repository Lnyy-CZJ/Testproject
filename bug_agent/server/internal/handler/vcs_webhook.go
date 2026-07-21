package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"io"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type VCSWebhookHandler struct {
	service *service.VCSWebhookService
}

func NewVCSWebhookHandler(db *gorm.DB) *VCSWebhookHandler {
	return &VCSWebhookHandler{
		service: service.NewVCSWebhookService(db),
	}
}

func (h *VCSWebhookHandler) HandleWebhook(c *gin.Context) {
	provider := c.Query("provider")
	if provider == "" {
		provider = c.GetHeader("X-VCS-Provider")
	}
	if provider == "" {
		response.BadRequest(c, "缺少 VCS provider 参数")
		return
	}

	payload, err := io.ReadAll(io.LimitReader(c.Request.Body, 1<<20))
	if err != nil {
		response.BadRequest(c, "读取请求体失败")
		return
	}

	var signature string
	var gitlabToken string
	switch strings.ToLower(provider) {
	case "github":
		signature = c.GetHeader("X-Hub-Signature-256")
		if signature == "" {
			response.BadRequest(c, "缺少 GitHub 签名 (X-Hub-Signature-256)")
			return
		}
	case "gitlab":
		gitlabToken = c.GetHeader("X-Gitlab-Token")
		if gitlabToken == "" {
			response.BadRequest(c, "缺少 GitLab Token (X-Gitlab-Token)")
			return
		}
	}

	if err := h.service.HandleWebhook(provider, payload, signature, gitlabToken); err != nil {
		response.ServerErrorWithLog(c, err, "处理Webhook失败")
		return
	}

	response.Success(c, gin.H{"message": "ok"})
}
