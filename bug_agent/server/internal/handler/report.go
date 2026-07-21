package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"fmt"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
)

type ReportHandler struct {
	svc *service.ReportService
}

func NewReportHandler(svc *service.ReportService) *ReportHandler {
	return &ReportHandler{svc: svc}
}

func parseProjectIDQuery(c *gin.Context) (uint, bool) {
	raw := c.Query("projectId")
	if raw == "" {
		raw = c.Query("project_id")
	}
	if raw == "" || raw == "0" {
		return 0, true
	}
	v, err := strconv.ParseUint(raw, 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的projectId")
		return 0, false
	}
	return uint(v), true
}

func (h *ReportHandler) Dashboard(c *gin.Context) {
	projectID, ok := parseProjectIDQuery(c)
	if !ok {
		return
	}

	summary, err := h.svc.GetDashboard(projectID)
	if err != nil {
		response.ServerError(c, "获取仪表盘失败")
		return
	}

	response.Success(c, summary)
}

func (h *ReportHandler) Trend(c *gin.Context) {
	days, _ := strconv.Atoi(c.DefaultQuery("days", "7"))
	interval := c.DefaultQuery("interval", "day")
	projectID, ok := parseProjectIDQuery(c)
	if !ok {
		return
	}

	if days > 365 {
		days = 365
	}
	if days < 1 {
		days = 7
	}

	trend, err := h.svc.GetTrend(days, interval, projectID)
	if err != nil {
		response.ServerError(c, "获取趋势失败")
		return
	}

	response.Success(c, trend)
}

func (h *ReportHandler) StatusDistribution(c *gin.Context) {
	projectID, ok := parseProjectIDQuery(c)
	if !ok {
		return
	}

	dist, err := h.svc.GetStatusDistribution(projectID)
	if err != nil {
		response.ServerError(c, "获取状态分布失败")
		return
	}

	response.Success(c, dist)
}

func (h *ReportHandler) SeverityDistribution(c *gin.Context) {
	projectID, ok := parseProjectIDQuery(c)
	if !ok {
		return
	}

	dist, err := h.svc.GetSeverityDistribution(projectID)
	if err != nil {
		response.ServerError(c, "获取严重度分布失败")
		return
	}

	response.Success(c, dist)
}

func (h *ReportHandler) TeamMetrics(c *gin.Context) {
	projectID, ok := parseProjectIDQuery(c)
	if !ok {
		return
	}

	metrics, err := h.svc.GetTeamMetrics(projectID)
	if err != nil {
		response.ServerError(c, "获取团队指标失败")
		return
	}

	response.Success(c, metrics)
}

func (h *ReportHandler) ExportCSV(c *gin.Context) {
	projectID, ok := parseProjectIDQuery(c)
	if !ok {
		return
	}
	status := c.DefaultQuery("status", "all")

	data, err := h.svc.ExportCSV(projectID, status)
	if err != nil {
		response.ServerError(c, "导出失败")
		return
	}

	c.Header("Content-Type", "text/csv; charset=utf-8")
	c.Header("Content-Disposition", fmt.Sprintf(`attachment; filename="defects_%s.csv"`, currentTimeStr()))
	c.String(200, data)
}

func (h *ReportHandler) ExportJSON(c *gin.Context) {
	projectID, ok := parseProjectIDQuery(c)
	if !ok {
		return
	}
	status := c.DefaultQuery("status", "all")

	data, err := h.svc.ExportJSON(projectID, status)
	if err != nil {
		response.ServerError(c, "导出失败")
		return
	}

	c.Header("Content-Type", "application/json; charset=utf-8")
	c.Header("Content-Disposition", fmt.Sprintf(`attachment; filename="defects_%s.json"`, currentTimeStr()))
	c.String(200, data)
}

func currentTimeStr() string {
	return time.Now().Format("20060102_150405")
}
