package handler

import (
	"bug-agent/internal/aiconfig"
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type ProjectAIConfigHandler struct {
	db *gorm.DB
}

func NewProjectAIConfigHandler(db *gorm.DB) *ProjectAIConfigHandler {
	return &ProjectAIConfigHandler{
		db: db,
	}
}

// ListAIConfigs 获取项目AI配置列表
func (h *ProjectAIConfigHandler) ListAIConfigs(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	var configs []model.ProjectAIConfig
	if err := h.db.Where("project_id = ?", projectID).Order("is_default desc, created_at desc").Find(&configs).Error; err != nil {
		response.ServerError(c, "获取AI配置列表失败")
		return
	}

	// 脱敏处理API Key
	for i := range configs {
		if configs[i].APIKey != "" {
			decrypted, err := aiconfig.DecryptAPIKey(configs[i].APIKey)
			if err == nil {
				configs[i].MaskedAPIKey = aiconfig.MaskAPIKey(decrypted)
			}
			configs[i].APIKey = ""
		}
	}

	response.Success(c, configs)
}

// CreateAIConfig 添加AI配置
func (h *ProjectAIConfigHandler) CreateAIConfig(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	var req struct {
		Provider            string `json:"provider" binding:"required"`
		ModelName           string `json:"modelName" binding:"required"`
		APIKey              string `json:"apiKey" binding:"required"`
		APIEndpoint         string `json:"apiEndpoint"`
		FunctionCallingMode string `json:"functionCallingMode"`
		IsDefault           bool   `json:"isDefault"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	if req.FunctionCallingMode != "" && req.FunctionCallingMode != "auto" && req.FunctionCallingMode != "enabled" && req.FunctionCallingMode != "disabled" {
		response.BadRequest(c, "functionCallingMode 必须为 auto/enabled/disabled")
		return
	}
	encryptedKey, err := aiconfig.EncryptAPIKey(req.APIKey)
	if err != nil {
		response.ServerError(c, "加密密钥失败")
		return
	}

	var config model.ProjectAIConfig
	err = h.db.Transaction(func(tx *gorm.DB) error {
		var existingCount int64
		if err := tx.Model(&model.ProjectAIConfig{}).Where("project_id = ?", projectID).Count(&existingCount).Error; err != nil {
			return err
		}

		shouldDefault := req.IsDefault || existingCount == 0

		if shouldDefault {
			if err := tx.Model(&model.ProjectAIConfig{}).Where("project_id = ?", projectID).Update("is_default", false).Error; err != nil {
				return err
			}
		}

		config = model.ProjectAIConfig{
			ProjectID:           uint(projectID),
			Provider:            req.Provider,
			ModelName:           req.ModelName,
			APIKey:              encryptedKey,
			APIEndpoint:         req.APIEndpoint,
			FunctionCallingMode: req.FunctionCallingMode,
			IsDefault:           shouldDefault,
		}
		if err := tx.Create(&config).Error; err != nil {
			return err
		}
		return nil
	})
	if err != nil {
		response.ServerError(c, "创建AI配置失败")
		return
	}

	// 返回时脱敏
	config.MaskedAPIKey = aiconfig.MaskAPIKey(req.APIKey)
	response.Created(c, config)
}

// UpdateAIConfig 更新AI配置
func (h *ProjectAIConfigHandler) UpdateAIConfig(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	configID, err := strconv.ParseUint(c.Param("configId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的配置ID")
		return
	}

	var req struct {
		Provider            *string `json:"provider"`
		ModelName           *string `json:"modelName"`
		APIKey              string  `json:"apiKey"`
		APIEndpoint         *string `json:"apiEndpoint"`
		FunctionCallingMode *string `json:"functionCallingMode"`
		IsDefault           *bool   `json:"isDefault"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	if req.FunctionCallingMode != nil && *req.FunctionCallingMode != "" && *req.FunctionCallingMode != "auto" && *req.FunctionCallingMode != "enabled" && *req.FunctionCallingMode != "disabled" {
		response.BadRequest(c, "functionCallingMode 必须为 auto/enabled/disabled")
		return
	}

	var config model.ProjectAIConfig
	if err := h.db.Where("id = ? AND project_id = ?", configID, projectID).First(&config).Error; err != nil {
		response.NotFound(c, "AI配置不存在")
		return
	}

	previousDefault := config.IsDefault
	nextDefault := config.IsDefault
	if req.IsDefault != nil {
		nextDefault = *req.IsDefault
	}

	if req.Provider != nil {
		config.Provider = *req.Provider
	}
	if req.ModelName != nil {
		config.ModelName = *req.ModelName
	}
	if req.APIKey != "" {
		encryptedKey, err := aiconfig.EncryptAPIKey(req.APIKey)
		if err != nil {
			response.ServerError(c, "加密密钥失败")
			return
		}
		config.APIKey = encryptedKey
	}
	if req.APIEndpoint != nil && strings.TrimSpace(*req.APIEndpoint) != "" {
		config.APIEndpoint = strings.TrimSpace(*req.APIEndpoint)
	}
	if req.FunctionCallingMode != nil {
		config.FunctionCallingMode = *req.FunctionCallingMode
	}
	config.IsDefault = nextDefault

	if nextDefault {
		err := h.db.Transaction(func(tx *gorm.DB) error {
			if err := tx.Model(&model.ProjectAIConfig{}).Where("project_id = ? AND id != ?", projectID, configID).Update("is_default", false).Error; err != nil {
				return err
			}
			if err := tx.Save(&config).Error; err != nil {
				return err
			}
			return nil
		})
		if err != nil {
			response.ServerError(c, "更新AI配置失败")
			return
		}
	} else {
		if err := h.db.Save(&config).Error; err != nil {
			response.ServerError(c, "更新AI配置失败")
			return
		}
	}

	if previousDefault && !config.IsDefault {
		h.ensureDefaultAIConfig(uint(projectID), config.ID)
	}

	// 返回时脱敏
	if req.APIKey != "" {
		config.MaskedAPIKey = aiconfig.MaskAPIKey(req.APIKey)
	} else {
		// 如果未更新密钥，尝试解密后脱敏
		decrypted, err := aiconfig.DecryptAPIKey(config.APIKey)
		if err == nil {
			config.MaskedAPIKey = aiconfig.MaskAPIKey(decrypted)
		}
	}

	response.Success(c, config)
}

// DeleteAIConfig 删除AI配置
func (h *ProjectAIConfigHandler) DeleteAIConfig(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	configID, err := strconv.ParseUint(c.Param("configId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的配置ID")
		return
	}

	var deleting model.ProjectAIConfig
	if err := h.db.Where("id = ? AND project_id = ?", configID, projectID).First(&deleting).Error; err != nil {
		response.NotFound(c, "AI配置不存在")
		return
	}

	// 检查是否为项目下最后一个AI配置
	var count int64
	if err := h.db.Model(&model.ProjectAIConfig{}).Where("project_id = ?", projectID).Count(&count).Error; err != nil {
		response.ServerError(c, "查询AI配置数量失败")
		return
	}
	if count <= 1 {
		response.Error(c, http.StatusBadRequest, 400, "不允许删除项目下最后一个AI配置")
		return
	}

	if err := h.db.Where("id = ? AND project_id = ?", configID, projectID).Delete(&model.ProjectAIConfig{}).Error; err != nil {
		response.ServerError(c, "删除AI配置失败")
		return
	}

	if deleting.IsDefault {
		h.ensureDefaultAIConfig(uint(projectID), 0)
	}

	response.Success(c, gin.H{"message": "AI配置已删除"})
}

func (h *ProjectAIConfigHandler) ensureDefaultAIConfig(projectID uint, excludeID uint) {
	var currentDefaultCount int64
	query := h.db.Model(&model.ProjectAIConfig{}).Where("project_id = ? AND is_default = ?", projectID, true)
	if excludeID > 0 {
		query = query.Where("id <> ?", excludeID)
	}
	if err := query.Count(&currentDefaultCount).Error; err != nil || currentDefaultCount > 0 {
		return
	}

	var candidate model.ProjectAIConfig
	candidateQuery := h.db.Where("project_id = ?", projectID)
	if excludeID > 0 {
		candidateQuery = candidateQuery.Where("id <> ?", excludeID)
	}
	if err := candidateQuery.Order("updated_at DESC, created_at DESC, id DESC").First(&candidate).Error; err != nil {
		return
	}

	if err := h.db.Model(&model.ProjectAIConfig{}).
		Where("id = ?", candidate.ID).
		Update("is_default", true).Error; err != nil {
		logger.Errorf("[ProjectAIConfig] ensureDefaultAIConfig failed for project %d: %v", projectID, err)
	}
}

// GetAIProviders 获取支持的AI厂商和模型列表
func (h *ProjectAIConfigHandler) GetAIProviders(c *gin.Context) {
	providers, err := h.loadAIProvidersFromCatalog()
	if err != nil {
		response.ServerError(c, "获取AI厂商目录失败")
		return
	}
	response.Success(c, providers)
}

func (h *ProjectAIConfigHandler) loadAIProvidersFromCatalog() ([]map[string]interface{}, error) {
	var providerRows []model.AIProviderCatalog
	if err := h.db.
		Where("status = ?", "active").
		Order("sort_order ASC, id ASC").
		Find(&providerRows).Error; err != nil {
		return nil, err
	}
	if len(providerRows) == 0 {
		return []map[string]interface{}{customAIProviderOption()}, nil
	}

	providerKeys := make([]string, 0, len(providerRows))
	for _, p := range providerRows {
		providerKeys = append(providerKeys, p.ProviderKey)
	}

	var modelRows []model.AIModelCatalog
	if err := h.db.
		Where("provider_key IN ? AND status <> ?", providerKeys, "inactive").
		Order("provider_key ASC, is_default DESC, sort_order ASC, id ASC").
		Find(&modelRows).Error; err != nil {
		return nil, err
	}

	modelMap := make(map[string][]map[string]string, len(providerRows))
	for _, m := range modelRows {
		modelMap[m.ProviderKey] = append(modelMap[m.ProviderKey], map[string]string{
			"name":            m.ModelName,
			"endpoint":        m.Endpoint,
			"capabilityTags":  m.CapabilityTags,
		})
	}

	providers := make([]map[string]interface{}, 0, len(providerRows))
	for _, p := range providerRows {
		models := modelMap[p.ProviderKey]
		for i := range models {
			if strings.TrimSpace(models[i]["endpoint"]) == "" {
				models[i]["endpoint"] = p.DefaultEndpoint
			}
		}
		providers = append(providers, map[string]interface{}{
			"name":   p.DisplayName,
			"value":  p.ProviderKey,
			"models": models,
		})
	}

	// 永远保留“自定义”选项
	providers = append(providers, customAIProviderOption())

	return providers, nil
}

func customAIProviderOption() map[string]interface{} {
	return map[string]interface{}{
		"name":   "自定义",
		"value":  "custom",
		"models": []map[string]string{},
	}
}
