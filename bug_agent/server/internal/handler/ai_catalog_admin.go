package handler

import (
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/pkg/response"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type AICatalogHandler struct {
	db *gorm.DB
}

func NewAICatalogHandler(db *gorm.DB) *AICatalogHandler {
	return &AICatalogHandler{db: db}
}

func (h *AICatalogHandler) ListProviders(c *gin.Context) {
	var providers []model.AIProviderCatalog
	query := h.db.Model(&model.AIProviderCatalog{})

	if status := strings.TrimSpace(c.Query("status")); status != "" {
		query = query.Where("status = ?", status)
	}
	if keyword := strings.TrimSpace(c.Query("keyword")); keyword != "" {
		like := "%" + EscapeLike(keyword) + "%"
		query = query.Where("provider_key ILIKE ? OR display_name ILIKE ?", like, like)
	}

	if err := query.Order("sort_order ASC, id ASC").Find(&providers).Error; err != nil {
		response.ServerError(c, "获取AI厂商目录失败")
		return
	}
	response.Success(c, providers)
}

func (h *AICatalogHandler) CreateProvider(c *gin.Context) {
	var req struct {
		ProviderKey     string `json:"providerKey" binding:"required"`
		DisplayName     string `json:"displayName" binding:"required"`
		DefaultEndpoint string `json:"defaultEndpoint"`
		Status          string `json:"status"`
		SortOrder       int    `json:"sortOrder"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	req.ProviderKey = strings.ToLower(strings.TrimSpace(req.ProviderKey))
	req.DisplayName = strings.TrimSpace(req.DisplayName)
	req.DefaultEndpoint = strings.TrimSpace(req.DefaultEndpoint)
	status := normalizeProviderStatus(req.Status)
	if status == "" {
		response.BadRequest(c, "无效的厂商状态，仅支持 active/inactive")
		return
	}
	if req.ProviderKey == "" || req.DisplayName == "" {
		response.BadRequest(c, "厂商标识和名称不能为空")
		return
	}

	var exists int64
	if err := h.db.Model(&model.AIProviderCatalog{}).Where("provider_key = ?", req.ProviderKey).Count(&exists).Error; err != nil {
		response.ServerError(c, "查询AI厂商目录失败")
		return
	}
	if exists > 0 {
		response.BadRequest(c, "厂商标识已存在")
		return
	}

	item := model.AIProviderCatalog{
		ProviderKey:     req.ProviderKey,
		DisplayName:     req.DisplayName,
		DefaultEndpoint: req.DefaultEndpoint,
		Status:          status,
		SortOrder:       req.SortOrder,
	}
	if err := h.db.Create(&item).Error; err != nil {
		response.ServerError(c, "创建AI厂商目录失败")
		return
	}
	middleware.AuditAction(c, "ai_provider_catalog_create", "ai_provider_catalog", item.ID, nil, item)
	response.Created(c, item)
}

func (h *AICatalogHandler) UpdateProvider(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的厂商ID")
		return
	}

	var req struct {
		DisplayName     *string `json:"displayName"`
		DefaultEndpoint *string `json:"defaultEndpoint"`
		Status          *string `json:"status"`
		SortOrder       *int    `json:"sortOrder"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	var item model.AIProviderCatalog
	if err := h.db.First(&item, id).Error; err != nil {
		response.NotFound(c, "AI厂商目录不存在")
		return
	}
	before := item

	if req.DisplayName != nil {
		name := strings.TrimSpace(*req.DisplayName)
		if name == "" {
			response.BadRequest(c, "厂商名称不能为空")
			return
		}
		item.DisplayName = name
	}
	if req.DefaultEndpoint != nil {
		item.DefaultEndpoint = strings.TrimSpace(*req.DefaultEndpoint)
	}
	if req.Status != nil {
		status := normalizeProviderStatus(*req.Status)
		if status == "" {
			response.BadRequest(c, "无效的厂商状态，仅支持 active/inactive")
			return
		}
		item.Status = status
	}
	if req.SortOrder != nil {
		item.SortOrder = *req.SortOrder
	}

	if err := h.db.Save(&item).Error; err != nil {
		response.ServerError(c, "更新AI厂商目录失败")
		return
	}
	middleware.AuditAction(c, "ai_provider_catalog_update", "ai_provider_catalog", item.ID, before, item)
	response.Success(c, item)
}

func (h *AICatalogHandler) DeleteProvider(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的厂商ID")
		return
	}

	var item model.AIProviderCatalog
	if err := h.db.First(&item, id).Error; err != nil {
		response.NotFound(c, "AI厂商目录不存在")
		return
	}

	var modelCount int64
	if err := h.db.Model(&model.AIModelCatalog{}).
		Where("provider_key = ?", item.ProviderKey).
		Count(&modelCount).Error; err != nil {
		response.ServerError(c, "查询关联模型目录失败")
		return
	}
	if modelCount > 0 {
		response.BadRequest(c, "请先删除该厂商下的模型目录")
		return
	}

	if err := h.db.Delete(&item).Error; err != nil {
		response.ServerError(c, "删除AI厂商目录失败")
		return
	}
	middleware.AuditAction(c, "ai_provider_catalog_delete", "ai_provider_catalog", item.ID, item, nil)
	response.Success(c, gin.H{"message": "AI厂商目录已删除"})
}

func (h *AICatalogHandler) ListModels(c *gin.Context) {
	var models []model.AIModelCatalog
	query := h.db.Model(&model.AIModelCatalog{})

	if providerKey := strings.TrimSpace(c.Query("providerKey")); providerKey != "" {
		query = query.Where("provider_key = ?", strings.ToLower(providerKey))
	}
	if status := strings.TrimSpace(c.Query("status")); status != "" {
		query = query.Where("status = ?", status)
	}
	if keyword := strings.TrimSpace(c.Query("keyword")); keyword != "" {
		like := "%" + EscapeLike(keyword) + "%"
		query = query.Where("model_name ILIKE ?", like)
	}

	if err := query.Order("provider_key ASC, is_default DESC, sort_order ASC, id ASC").Find(&models).Error; err != nil {
		response.ServerError(c, "获取AI模型目录失败")
		return
	}
	response.Success(c, models)
}

func (h *AICatalogHandler) CreateModel(c *gin.Context) {
	var req struct {
		ProviderKey    string `json:"providerKey" binding:"required"`
		ModelName      string `json:"modelName" binding:"required"`
		Endpoint       string `json:"endpoint"`
		CapabilityTags string `json:"capabilityTags"`
		Status         string `json:"status"`
		IsDefault      bool   `json:"isDefault"`
		SortOrder      int    `json:"sortOrder"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	req.ProviderKey = strings.ToLower(strings.TrimSpace(req.ProviderKey))
	req.ModelName = strings.TrimSpace(req.ModelName)
	req.Endpoint = strings.TrimSpace(req.Endpoint)
	req.CapabilityTags = strings.TrimSpace(req.CapabilityTags)
	status := normalizeModelStatus(req.Status)
	if status == "" {
		response.BadRequest(c, "无效的模型状态，仅支持 active/deprecated/inactive")
		return
	}
	if req.ProviderKey == "" || req.ModelName == "" {
		response.BadRequest(c, "厂商标识和模型名称不能为空")
		return
	}

	var providerCount int64
	if err := h.db.Model(&model.AIProviderCatalog{}).
		Where("provider_key = ?", req.ProviderKey).
		Count(&providerCount).Error; err != nil {
		response.ServerError(c, "查询AI厂商目录失败")
		return
	}
	if providerCount == 0 {
		response.BadRequest(c, "厂商目录不存在")
		return
	}

	if req.IsDefault {
		_ = h.db.Model(&model.AIModelCatalog{}).
			Where("provider_key = ?", req.ProviderKey).
			Update("is_default", false).Error
	}

	item := model.AIModelCatalog{
		ProviderKey:    req.ProviderKey,
		ModelName:      req.ModelName,
		Endpoint:       req.Endpoint,
		CapabilityTags: req.CapabilityTags,
		Status:         status,
		IsDefault:      req.IsDefault,
		SortOrder:      req.SortOrder,
	}
	if err := h.db.Create(&item).Error; err != nil {
		response.ServerError(c, "创建AI模型目录失败")
		return
	}
	middleware.AuditAction(c, "ai_model_catalog_create", "ai_model_catalog", item.ID, nil, item)
	response.Created(c, item)
}

func (h *AICatalogHandler) UpdateModel(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的模型ID")
		return
	}

	var req struct {
		ProviderKey    *string `json:"providerKey"`
		ModelName      *string `json:"modelName"`
		Endpoint       *string `json:"endpoint"`
		CapabilityTags *string `json:"capabilityTags"`
		Status         *string `json:"status"`
		IsDefault      *bool   `json:"isDefault"`
		SortOrder      *int    `json:"sortOrder"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	var item model.AIModelCatalog
	if err := h.db.First(&item, id).Error; err != nil {
		response.NotFound(c, "AI模型目录不存在")
		return
	}
	before := item

	if req.ProviderKey != nil {
		nextKey := strings.ToLower(strings.TrimSpace(*req.ProviderKey))
		if nextKey == "" {
			response.BadRequest(c, "厂商标识不能为空")
			return
		}
		var providerCount int64
		if err := h.db.Model(&model.AIProviderCatalog{}).
			Where("provider_key = ?", nextKey).
			Count(&providerCount).Error; err != nil {
			response.ServerError(c, "查询AI厂商目录失败")
			return
		}
		if providerCount == 0 {
			response.BadRequest(c, "厂商目录不存在")
			return
		}
		item.ProviderKey = nextKey
	}
	if req.ModelName != nil {
		name := strings.TrimSpace(*req.ModelName)
		if name == "" {
			response.BadRequest(c, "模型名称不能为空")
			return
		}
		item.ModelName = name
	}
	if req.Endpoint != nil {
		item.Endpoint = strings.TrimSpace(*req.Endpoint)
	}
	if req.CapabilityTags != nil {
		item.CapabilityTags = strings.TrimSpace(*req.CapabilityTags)
	}
	if req.Status != nil {
		status := normalizeModelStatus(*req.Status)
		if status == "" {
			response.BadRequest(c, "无效的模型状态，仅支持 active/deprecated/inactive")
			return
		}
		item.Status = status
	}
	if req.IsDefault != nil {
		item.IsDefault = *req.IsDefault
		if item.IsDefault {
			_ = h.db.Model(&model.AIModelCatalog{}).
				Where("provider_key = ? AND id != ?", item.ProviderKey, item.ID).
				Update("is_default", false).Error
		}
	}
	if req.SortOrder != nil {
		item.SortOrder = *req.SortOrder
	}

	if err := h.db.Save(&item).Error; err != nil {
		response.ServerError(c, "更新AI模型目录失败")
		return
	}
	middleware.AuditAction(c, "ai_model_catalog_update", "ai_model_catalog", item.ID, before, item)
	response.Success(c, item)
}

func (h *AICatalogHandler) DeleteModel(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的模型ID")
		return
	}

	var item model.AIModelCatalog
	if err := h.db.First(&item, id).Error; err != nil {
		response.NotFound(c, "AI模型目录不存在")
		return
	}

	if err := h.db.Delete(&item).Error; err != nil {
		response.ServerError(c, "删除AI模型目录失败")
		return
	}
	middleware.AuditAction(c, "ai_model_catalog_delete", "ai_model_catalog", item.ID, item, nil)
	response.Success(c, gin.H{"message": "AI模型目录已删除"})
}

func (h *AICatalogHandler) TestModelAvailability(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的模型ID")
		return
	}

	var req struct {
		APIKey      string `json:"apiKey" binding:"required"`
		APIEndpoint string `json:"apiEndpoint"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	var item model.AIModelCatalog
	if err := h.db.First(&item, id).Error; err != nil {
		response.NotFound(c, "AI模型目录不存在")
		return
	}

	var provider model.AIProviderCatalog
	if err := h.db.Where("provider_key = ?", item.ProviderKey).First(&provider).Error; err != nil {
		response.NotFound(c, "AI厂商目录不存在")
		return
	}

	endpoint := strings.TrimSpace(req.APIEndpoint)
	if endpoint == "" {
		endpoint = strings.TrimSpace(item.Endpoint)
	}
	if endpoint == "" {
		endpoint = strings.TrimSpace(provider.DefaultEndpoint)
	}
	if endpoint == "" {
		response.BadRequest(c, "模型端点未配置，无法测试")
		return
	}

	start := time.Now()
	err = probeModelAvailability(item.ProviderKey, endpoint, strings.TrimSpace(req.APIKey), item.ModelName)
	latencyMs := time.Since(start).Milliseconds()
	if err != nil {
		response.Success(c, gin.H{
			"success":   false,
			"latencyMs": latencyMs,
			"message":   "模型测试失败，请检查API配置",
		})
		return
	}

	response.Success(c, gin.H{
		"success":   true,
		"latencyMs": latencyMs,
		"message":   "模型可用性测试成功",
		"endpoint":  endpoint,
	})
}

func probeModelAvailability(providerKey, endpoint, apiKey, modelName string) error {
	switch strings.ToLower(strings.TrimSpace(providerKey)) {
	case "anthropic":
		return probeAnthropicModel(endpoint, apiKey, modelName)
	case "openai", "zhipu", "deepseek", "dashscope", "custom":
		return probeOpenAICompatibleModel(endpoint, apiKey, modelName)
	default:
		return fmt.Errorf("暂不支持该厂商的模型测试: %s", providerKey)
	}
}

func probeOpenAICompatibleModel(endpoint, apiKey, modelName string) error {
	payload := map[string]any{
		"model": modelName,
		"messages": []map[string]string{
			{"role": "user", "content": "ping"},
		},
		"max_tokens": 1,
	}
	return doModelProbe(joinOpenAICompatibleEndpoint(endpoint), map[string]string{
		"Authorization": "Bearer " + apiKey,
	}, payload)
}

func probeAnthropicModel(endpoint, apiKey, modelName string) error {
	payload := map[string]any{
		"model":      modelName,
		"max_tokens": 1,
		"messages": []map[string]string{
			{"role": "user", "content": "ping"},
		},
	}
	return doModelProbe(joinAnthropicEndpoint(endpoint), map[string]string{
		"x-api-key":         apiKey,
		"anthropic-version": "2023-06-01",
	}, payload)
}

func doModelProbe(url string, extraHeaders map[string]string, payload map[string]any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("序列化测试请求失败: %w", err)
	}

	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("创建测试请求失败: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	for key, value := range extraHeaders {
		req.Header.Set(key, value)
	}

	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("模型测试请求失败: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= http.StatusBadRequest {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("模型测试失败: HTTP %d %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}
	return nil
}

func joinOpenAICompatibleEndpoint(endpoint string) string {
	base := strings.TrimRight(strings.TrimSpace(endpoint), "/")
	if strings.HasSuffix(base, "/chat/completions") {
		return base
	}
	return base + "/chat/completions"
}

func joinAnthropicEndpoint(endpoint string) string {
	base := strings.TrimRight(strings.TrimSpace(endpoint), "/")
	switch {
	case strings.HasSuffix(base, "/v1/messages"):
		return base
	case strings.HasSuffix(base, "/v1"):
		return base + "/messages"
	default:
		return base + "/v1/messages"
	}
}

func normalizeProviderStatus(input string) string {
	status := strings.ToLower(strings.TrimSpace(input))
	if status == "" {
		return "active"
	}
	switch status {
	case "active", "inactive":
		return status
	default:
		return ""
	}
}

func normalizeModelStatus(input string) string {
	status := strings.ToLower(strings.TrimSpace(input))
	if status == "" {
		return "active"
	}
	switch status {
	case "active", "deprecated", "inactive":
		return status
	default:
		return ""
	}
}
