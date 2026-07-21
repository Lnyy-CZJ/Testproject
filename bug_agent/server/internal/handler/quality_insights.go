package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type QualityInsightsHandler struct {
	svc *service.QualityInsightsService
}

func NewQualityInsightsHandler(db *gorm.DB) *QualityInsightsHandler {
	return &QualityInsightsHandler{svc: service.NewQualityInsightsService(db)}
}

func (h *QualityInsightsHandler) GetOverview(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	overview, err := h.svc.GetOverview(projectID)
	if err != nil {
		response.ServerError(c, "获取质量情报概览失败")
		return
	}
	response.Success(c, overview)
}
