package handler

import (
	"bug-agent/internal/model"
	"bug-agent/pkg/response"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type TokenUsageHandler struct {
	db *gorm.DB
}

func NewTokenUsageHandler(db *gorm.DB) *TokenUsageHandler {
	return &TokenUsageHandler{db: db}
}

type tokenUsageSummary struct {
	ConsumptionType  string  `json:"consumptionType"`
	PromptTokens     int     `json:"promptTokens"`
	CompletionTokens int     `json:"completionTokens"`
	TotalTokens      int     `json:"totalTokens"`
	EstimatedCostUSD float64 `json:"estimatedCostUsd"`
	CallCount        int     `json:"callCount"`
	DurationMs       int64   `json:"durationMs"`
}

func (h *TokenUsageHandler) GetDefectTokenUsage(c *gin.Context) {
	defectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}

	var summaries []tokenUsageSummary
	err = h.db.Model(&model.AITokenUsage{}).
		Select("consumption_type, SUM(prompt_tokens) as prompt_tokens, SUM(completion_tokens) as completion_tokens, SUM(total_tokens) as total_tokens, SUM(estimated_cost_usd) as estimated_cost_usd, COUNT(*) as call_count, SUM(duration_ms) as duration_ms").
		Where("defect_id = ?", defectID).
		Group("consumption_type").
		Find(&summaries).Error
	if err != nil {
		response.ServerError(c, "查询 Token 消耗失败")
		return
	}

	response.Success(c, summaries)
}

func (h *TokenUsageHandler) GetDefectTokenUsageDetails(c *gin.Context) {
	defectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}

	var usages []model.AITokenUsage
	if err := h.db.Where("defect_id = ?", defectID).Order("created_at DESC").Find(&usages).Error; err != nil {
		response.ServerError(c, "查询 Token 明细失败")
		return
	}

	response.Success(c, usages)
}

func (h *TokenUsageHandler) GetIterationTokenUsage(c *gin.Context) {
	iterationID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的迭代 ID")
		return
	}

	var summaries []tokenUsageSummary
	err = h.db.Model(&model.AITokenUsage{}).
		Select("consumption_type, SUM(prompt_tokens) as prompt_tokens, SUM(completion_tokens) as completion_tokens, SUM(total_tokens) as total_tokens, SUM(estimated_cost_usd) as estimated_cost_usd, COUNT(*) as call_count, SUM(duration_ms) as duration_ms").
		Where("iteration_id = ?", iterationID).
		Group("consumption_type").
		Find(&summaries).Error
	if err != nil {
		response.ServerError(c, "查询 Token 消耗失败")
		return
	}

	response.Success(c, summaries)
}

func (h *TokenUsageHandler) GetProjectTokenUsage(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	query := h.db.Model(&model.AITokenUsage{}).
		Select("consumption_type, SUM(prompt_tokens) as prompt_tokens, SUM(completion_tokens) as completion_tokens, SUM(total_tokens) as total_tokens, SUM(estimated_cost_usd) as estimated_cost_usd, COUNT(*) as call_count, SUM(duration_ms) as duration_ms").
		Where("project_id = ?", projectID)

	query = applyDateFilter(c, query)

	var summaries []tokenUsageSummary
	if err := query.Group("consumption_type").Find(&summaries).Error; err != nil {
		response.ServerError(c, "查询 Token 消耗失败")
		return
	}

	response.Success(c, summaries)
}

type tokenUsageByEntity struct {
	ID               uint    `json:"id"`
	ConsumptionType  string  `json:"consumptionType"`
	TotalTokens      int     `json:"totalTokens"`
	EstimatedCostUSD float64 `json:"estimatedCostUsd"`
	CallCount        int     `json:"callCount"`
}

func (h *TokenUsageHandler) GetProjectTokenUsageByIteration(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	query := h.db.Model(&model.AITokenUsage{}).
		Select("iteration_id as id, consumption_type, SUM(total_tokens) as total_tokens, SUM(estimated_cost_usd) as estimated_cost_usd, COUNT(*) as call_count").
		Where("project_id = ? AND iteration_id IS NOT NULL", projectID)

	query = applyDateFilter(c, query)

	var results []tokenUsageByEntity
	if err := query.Group("iteration_id, consumption_type").Order("total_tokens DESC").Find(&results).Error; err != nil {
		response.ServerError(c, "查询 Token 消耗失败")
		return
	}

	response.Success(c, results)
}

func (h *TokenUsageHandler) GetProjectTokenUsageByDefect(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	query := h.db.Model(&model.AITokenUsage{}).
		Select("defect_id as id, consumption_type, SUM(total_tokens) as total_tokens, SUM(estimated_cost_usd) as estimated_cost_usd, COUNT(*) as call_count").
		Where("project_id = ?", projectID)

	query = applyDateFilter(c, query)

	var results []tokenUsageByEntity
	if err := query.Group("defect_id, consumption_type").Order("total_tokens DESC").Find(&results).Error; err != nil {
		response.ServerError(c, "查询 Token 消耗失败")
		return
	}

	response.Success(c, results)
}

func applyDateFilter(c *gin.Context, query *gorm.DB) *gorm.DB {
	if startDate := c.Query("startDate"); startDate != "" {
		if t, err := time.Parse("2006-01-02", startDate); err == nil {
			query = query.Where("created_at >= ?", t)
		}
	}
	if endDate := c.Query("endDate"); endDate != "" {
		if t, err := time.Parse("2006-01-02", endDate); err == nil {
			query = query.Where("created_at < ?", t.Add(24*time.Hour))
		}
	}
	return query
}
