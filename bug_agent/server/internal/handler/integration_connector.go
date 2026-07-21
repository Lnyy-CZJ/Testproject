package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"errors"
	"io"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type IntegrationConnectorHandler struct {
	svc *service.IntegrationConnectorService
}

func NewIntegrationConnectorHandler(db *gorm.DB, ingest *service.SignalIngestService) *IntegrationConnectorHandler {
	return &IntegrationConnectorHandler{
		svc: service.NewIntegrationConnectorService(db, ingest),
	}
}

func (h *IntegrationConnectorHandler) List(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	connectors, err := h.svc.List(projectID)
	if err != nil {
		response.ServerError(c, "获取连接器列表失败")
		return
	}
	response.Success(c, connectors)
}

func (h *IntegrationConnectorHandler) Create(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req struct {
		Name      string                 `json:"name" binding:"required"`
		Type      string                 `json:"type" binding:"required"`
		Status    string                 `json:"status"`
		Config    map[string]interface{} `json:"config"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	view, err := h.svc.Create(projectID, getUserID(c), service.IntegrationConnectorInput{
		Name:      req.Name,
		Type:      req.Type,
		Status:    req.Status,
		Config:    req.Config,
	})
	if err != nil {
		if errors.Is(err, service.ErrIntegrationConnectorConfigInvalid) {
			response.BadRequest(c, "连接器参数不完整")
			return
		}
		response.ServerError(c, "创建连接器失败")
		return
	}
	response.Created(c, view)
}

func (h *IntegrationConnectorHandler) Update(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	connectorID, err := strconv.ParseUint(c.Param("connectorId"), 10, 64)
	if err != nil || connectorID == 0 {
		response.BadRequest(c, "无效的连接器 ID")
		return
	}

	var req struct {
		Name      string                 `json:"name"`
		Type      string                 `json:"type"`
		Status    string                 `json:"status"`
		Config    map[string]interface{} `json:"config"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	view, updateErr := h.svc.Update(projectID, uint(connectorID), service.IntegrationConnectorInput{
		Name:      req.Name,
		Type:      req.Type,
		Status:    req.Status,
		Config:    req.Config,
	})
	if updateErr != nil {
		switch {
		case errors.Is(updateErr, service.ErrIntegrationConnectorNotFound):
			response.NotFound(c, "连接器不存在")
		case errors.Is(updateErr, service.ErrIntegrationConnectorConfigInvalid):
			response.BadRequest(c, "连接器参数不完整")
		default:
			response.ServerError(c, "更新连接器失败")
		}
		return
	}
	response.Success(c, view)
}

func (h *IntegrationConnectorHandler) Delete(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	connectorID, err := strconv.ParseUint(c.Param("connectorId"), 10, 64)
	if err != nil || connectorID == 0 {
		response.BadRequest(c, "无效的连接器 ID")
		return
	}
	if err := h.svc.Delete(projectID, uint(connectorID)); err != nil {
		switch {
		case errors.Is(err, service.ErrIntegrationConnectorNotFound):
			response.NotFound(c, "连接器不存在")
		case errors.Is(err, service.ErrIntegrationConnectorHasSignals):
			response.BadRequest(c, "连接器已有接入信号，不能删除")
		default:
			response.ServerError(c, "删除连接器失败")
		}
		return
	}
	response.Success(c, gin.H{"message": "连接器已删除"})
}

func (h *IntegrationConnectorHandler) Test(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	connectorID, err := strconv.ParseUint(c.Param("connectorId"), 10, 64)
	if err != nil || connectorID == 0 {
		response.BadRequest(c, "无效的连接器 ID")
		return
	}
	result, err := h.svc.Test(projectID, uint(connectorID))
	if err != nil {
		switch {
		case errors.Is(err, service.ErrIntegrationConnectorNotFound):
			response.NotFound(c, "连接器不存在")
		case errors.Is(err, service.ErrIntegrationConnectorConfigInvalid):
			response.BadRequest(c, "连接器配置不完整")
		default:
			respondConnectorOperationError(c, err, "测试连接器失败")
		}
		return
	}
	response.Success(c, result)
}

func (h *IntegrationConnectorHandler) Sync(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	connectorID, err := strconv.ParseUint(c.Param("connectorId"), 10, 64)
	if err != nil || connectorID == 0 {
		response.BadRequest(c, "无效的连接器 ID")
		return
	}

	var req struct {
		Items []map[string]interface{} `json:"items"`
	}
	if err := c.ShouldBindJSON(&req); err != nil && !errors.Is(err, io.EOF) {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	result, syncErr := h.svc.Sync(projectID, uint(connectorID), req.Items)
	if syncErr != nil {
		switch {
		case errors.Is(syncErr, service.ErrIntegrationConnectorNotFound):
			response.NotFound(c, "连接器不存在")
		case errors.Is(syncErr, service.ErrIntegrationConnectorInactive):
			response.BadRequest(c, "连接器未启用")
		case errors.Is(syncErr, service.ErrIntegrationConnectorConfigInvalid):
			response.BadRequest(c, "连接器配置不完整")
		default:
			respondConnectorOperationError(c, syncErr, "手动同步失败")
		}
		return
	}
	response.Success(c, result)
}

func (h *IntegrationConnectorHandler) ListSyncRecords(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	connectorID, err := strconv.ParseUint(c.Param("connectorId"), 10, 64)
	if err != nil || connectorID == 0 {
		response.BadRequest(c, "无效的连接器 ID")
		return
	}

	records, listErr := h.svc.ListSyncRecords(projectID, uint(connectorID))
	if listErr != nil {
		if errors.Is(listErr, service.ErrIntegrationConnectorNotFound) {
			response.NotFound(c, "连接器不存在")
			return
		}
		response.ServerError(c, "获取同步记录失败")
		return
	}
	response.Success(c, records)
}

func respondConnectorOperationError(c *gin.Context, err error, fallback string) {
	detail := service.ExplainConnectorError(err)
	messageText := detail.Message
	if messageText == "" {
		messageText = fallback
	}
	switch detail.Kind {
	case "auth_failed", "config_invalid", "inactive", "payload_invalid":
		response.Error(c, http.StatusBadRequest, http.StatusBadRequest, messageText)
	case "rate_limited":
		response.Error(c, http.StatusTooManyRequests, http.StatusTooManyRequests, messageText)
	case "network_timeout":
		response.Error(c, http.StatusGatewayTimeout, http.StatusGatewayTimeout, messageText)
	case "upstream_error":
		response.Error(c, http.StatusBadGateway, http.StatusBadGateway, messageText)
	default:
		response.ServerError(c, messageText)
	}
}
