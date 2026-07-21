package handler

import (
	"bug-agent/internal/config"
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type InboundConnectorHandler struct {
	db  *gorm.DB
	svc *service.SignalIngestService
}

func NewInboundConnectorHandler(db *gorm.DB, svc *service.SignalIngestService) *InboundConnectorHandler {
	return &InboundConnectorHandler{
		db:  db,
		svc: svc,
	}
}

func (h *InboundConnectorHandler) Receive(c *gin.Context) {
	token := strings.TrimSpace(c.Param("token"))
	if token == "" {
		response.BadRequest(c, "入站 token 不能为空")
		return
	}

	var connector model.IntegrationConnector
	if err := h.db.Where("inbound_token = ?", token).First(&connector).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "连接器不存在")
			return
		}
		response.ServerError(c, "查询连接器失败")
		return
	}

	rawBody, err := io.ReadAll(io.LimitReader(c.Request.Body, 1<<20))
	if err != nil {
		response.BadRequest(c, "读取入站请求失败")
		return
	}

	if connector.Type == model.ConnectorTypeWebhook {
		securityConfig, err := service.NewIntegrationConnectorService(h.db, h.svc).ResolveConfig(connector)
		if err != nil {
			response.ServerError(c, "读取连接器配置失败")
			return
		}
		if enforceWebhookSignature(securityConfig) {
			secret := webhookSignatureSecret(securityConfig)
			if secret == "" {
				middleware.AuditAction(c, "inbound_webhook_signature_failed", "integration_connector", connector.ID, nil, gin.H{
					"reason": "secret_missing",
				})
				response.Forbidden(c, "连接器未配置签名密钥")
				return
			}
			signature := strings.TrimSpace(c.GetHeader("X-Hub-Signature-256"))
			if signature == "" {
				middleware.AuditAction(c, "inbound_webhook_signature_failed", "integration_connector", connector.ID, nil, gin.H{
					"reason": "header_missing",
				})
				response.Unauthorized(c, "签名缺失")
				return
			}
			if !verifyWebhookSignature(secret, rawBody, signature) {
				middleware.AuditAction(c, "inbound_webhook_signature_failed", "integration_connector", connector.ID, nil, gin.H{
					"reason": "signature_invalid",
				})
				response.Unauthorized(c, "签名校验失败")
				return
			}
		}
	}

	if connector.Type == model.ConnectorTypeFeishu {
		var payload map[string]interface{}
		if err := json.Unmarshal(rawBody, &payload); err == nil {
			if challenge, ok := payload["challenge"].(string); ok && strings.TrimSpace(challenge) != "" {
				c.JSON(http.StatusOK, gin.H{"challenge": strings.TrimSpace(challenge)})
				return
			}
		}
	}

	signal, cluster, syncRecord, err := h.svc.Ingest(connector, "inbound_webhook", rawBody)
	if err != nil {
		switch {
		case errors.Is(err, service.ErrIntegrationConnectorInactive):
			response.Forbidden(c, "连接器未启用")
		case errors.Is(err, service.ErrInvalidSignalPayload):
			response.BadRequest(c, "入站 payload 无效")
		default:
			response.ServerError(c, "接收入站信号失败")
		}
		return
	}

	response.Success(c, gin.H{
		"signalId":     signal.ID,
		"clusterId":    cluster.ID,
		"syncRecordId": syncRecord.ID,
	})
}

func webhookSignatureSecret(config map[string]interface{}) string {
	for _, key := range []string{"secret", "signingSecret", "webhookSecret"} {
		if value, ok := config[key].(string); ok && strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

func enforceWebhookSignature(config map[string]interface{}) bool {
	if skipSignatureVerification(config) {
		return false
	}
	if explicit, ok := parseBoolConfig(config["requireSignature"]); ok {
		return explicit
	}
	return webhookSignatureSecret(config) != ""
}

func skipSignatureVerification(config map[string]interface{}) bool {
	flag, ok := parseBoolConfig(config["skipSignatureVerification"])
	if !ok || !flag {
		return false
	}
	// 仅非生产模式允许跳过强校验
	mode := strings.ToLower(strings.TrimSpace(config2mode()))
	return mode != "release"
}

func config2mode() string {
	return config.C.Server.Mode
}

func parseBoolConfig(raw interface{}) (bool, bool) {
	switch value := raw.(type) {
	case bool:
		return value, true
	case string:
		text := strings.TrimSpace(strings.ToLower(value))
		switch text {
		case "true", "1", "yes", "y":
			return true, true
		case "false", "0", "no", "n":
			return false, true
		default:
			return false, false
		}
	default:
		return false, false
	}
}

func verifyWebhookSignature(secret string, body []byte, header string) bool {
	if secret == "" {
		return false
	}
	header = strings.TrimSpace(header)
	if !strings.HasPrefix(header, "sha256=") {
		return false
	}
	received := strings.TrimSpace(strings.TrimPrefix(header, "sha256="))
	if len(received) != 64 {
		return false
	}
	if _, err := hex.DecodeString(received); err != nil {
		return false
	}
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	expected := hex.EncodeToString(mac.Sum(nil))
	return hmac.Equal([]byte(strings.ToLower(received)), []byte(expected))
}
