package service

import (
	"bug-agent/internal/ai"
	"bug-agent/internal/aiconfig"
	"bug-agent/internal/model"
	"fmt"
	"strings"
	"time"

	"bug-agent/pkg/logger"
	"gorm.io/gorm"
)

const (
	analysisPromptVersion    = "v5.1-analysis-1"
	fixPromptVersion         = "v5.1-fix-1"
	defaultAnalysisMaxTokens = 2048
)

type AIExecutionMetadata struct {
	Provider              string
	ModelName             string
	PromptVersion         string
	FallbackUsed          bool
	ErrorMessage          string
	DurationMs            int64
	PromptTokens          int
	CompletionTokens      int
	TotalTokens           int
	EstimatedCostUSD      float64
	RiskSummary           string
	ValidationSuggestions []string
}

func listUsableProjectAIConfigs(db *gorm.DB, projectID uint) ([]model.ProjectAIConfig, error) {
	var configs []model.ProjectAIConfig
	if err := db.
		Where("project_id = ?", projectID).
		Order("is_default DESC, updated_at DESC, created_at DESC, id DESC").
		Find(&configs).Error; err != nil {
		return nil, fmt.Errorf("查询AI配置失败: %w", err)
	}
	if len(configs) == 0 {
		return nil, fmt.Errorf("未找到AI配置")
	}

	usable := make([]model.ProjectAIConfig, 0, len(configs))
	reasons := make([]string, 0, len(configs))
	for i := range configs {
		config := configs[i]
		if err := HydrateProjectAIConfig(&config); err != nil {
			reasons = append(reasons, fmt.Sprintf("配置#%d不可用: %v", config.ID, err))
			continue
		}
		usable = append(usable, config)
	}
	if len(usable) == 0 {
		return nil, fmt.Errorf("未找到可用AI配置: %s", strings.Join(reasons, "; "))
	}
	if !usable[0].IsDefault {
		promoteProjectAIConfigAsDefault(db, projectID, usable[0].ID)
		usable[0].IsDefault = true
	}
	return usable, nil
}

func HydrateProjectAIConfig(config *model.ProjectAIConfig) error {
	config.Provider = strings.TrimSpace(config.Provider)
	config.ModelName = strings.TrimSpace(config.ModelName)
	config.APIEndpoint = strings.TrimSpace(config.APIEndpoint)
	if config.Provider == "" {
		return fmt.Errorf("provider 不能为空")
	}
	if config.ModelName == "" {
		return fmt.Errorf("modelName 不能为空")
	}
	if aiconfig.IsPlaceholderEndpoint(config.APIEndpoint) {
		return fmt.Errorf("endpoint %q 是占位地址", config.APIEndpoint)
	}
	if strings.EqualFold(config.Provider, "mock-fail") {
		config.APIKey = ""
		return nil
	}

	decrypted, err := aiconfig.DecryptAPIKey(config.APIKey)
	if err != nil {
		config.APIKey = strings.TrimSpace(config.APIKey)
		if config.APIKey == "" {
			return fmt.Errorf("apiKey 解密失败且明文为空: %w", err)
		}
		if len(config.APIKey) >= 8 {
			logger.Infof("[HydrateProjectAIConfig] API key 解密失败(%v)，使用原始字符串作为API Key(长度=%d)", err, len(config.APIKey))
		} else {
			return fmt.Errorf("apiKey 解密失败: %w", err)
		}
	} else {
		config.APIKey = strings.TrimSpace(decrypted)
	}
	return nil
}

func promoteProjectAIConfigAsDefault(db *gorm.DB, projectID, configID uint) {
	err := db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Model(&model.ProjectAIConfig{}).
			Where("project_id = ?", projectID).
			Update("is_default", false).Error; err != nil {
			return err
		}
		if err := tx.Model(&model.ProjectAIConfig{}).
			Where("id = ?", configID).
			Update("is_default", true).Error; err != nil {
			return err
		}
		return nil
	})
	if err != nil {
		logger.Errorf("[AIConfig] promoteProjectAIConfigAsDefault: %v", err)
	}
}

func EstimateAICostUSD(provider, modelName string, usage ai.Usage) float64 {
	if usage.TotalTokens == 0 {
		return 0
	}

	promptPerMillion := 0.0
	completionPerMillion := 0.0
	switch strings.ToLower(strings.TrimSpace(provider)) {
	case "openai", "custom-openai", "moonshot", "kimi":
		promptPerMillion = 5.0
		completionPerMillion = 15.0
	case "anthropic":
		promptPerMillion = 3.0
		completionPerMillion = 15.0
	case "deepseek":
		promptPerMillion = 0.27
		completionPerMillion = 1.10
	case "zhipu", "zhipuai", "bigmodel", "智谱ai":
		promptPerMillion = 0.8
		completionPerMillion = 2.0
	case "dashscope", "alibaba", "阿里云百炼":
		promptPerMillion = 1.0
		completionPerMillion = 3.0
	default:
		if strings.Contains(strings.ToLower(modelName), "mini") {
			promptPerMillion = 0.8
			completionPerMillion = 2.4
		}
	}

	if promptPerMillion == 0 && completionPerMillion == 0 {
		return 0
	}
	return (float64(usage.PromptTokens)*promptPerMillion + float64(usage.CompletionTokens)*completionPerMillion) / 1_000_000
}

func EstimateTokenUsageFromText(promptText, completionText string) ai.Usage {
	promptTokens := estimateTokenCount(promptText)
	completionTokens := estimateTokenCount(completionText)
	return ai.Usage{
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		TotalTokens:      promptTokens + completionTokens,
	}
}

func estimateTokenCount(text string) int {
	text = strings.TrimSpace(text)
	if text == "" {
		return 0
	}
	count := len([]rune(text)) / 4
	if count < 1 {
		return 1
	}
	return count
}

func buildRiskSummary(rootCause, riskLevel string) string {
	rootCause = strings.TrimSpace(rootCause)
	riskLevel = strings.ToUpper(strings.TrimSpace(riskLevel))
	switch {
	case rootCause == "" && riskLevel == "":
		return ""
	case rootCause == "":
		return fmt.Sprintf("风险等级 %s，需要优先验证关键链路。", riskLevel)
	case riskLevel == "":
		return fmt.Sprintf("根因初判：%s", rootCause)
	default:
		return fmt.Sprintf("风险等级 %s；根因初判：%s", riskLevel, rootCause)
	}
}

func buildValidationSuggestions(affectedFiles []string, existing []string) []string {
	seen := make(map[string]struct{}, len(existing)+2)
	suggestions := make([]string, 0, len(existing)+3)
	appendSuggestion := func(value string) {
		value = strings.TrimSpace(value)
		if value == "" {
			return
		}
		if _, ok := seen[value]; ok {
			return
		}
		seen[value] = struct{}{}
		suggestions = append(suggestions, value)
	}

	for _, suggestion := range existing {
		appendSuggestion(suggestion)
	}
	appendSuggestion("补一条覆盖根因场景的回归验证用例")
	if len(affectedFiles) > 0 {
		appendSuggestion(fmt.Sprintf("重点验证变更文件涉及的关键路径：%s", affectedFiles[0]))
	}
	appendSuggestion("回归验证后确认问题池和正式缺陷状态保持一致")
	return suggestions
}

func classifyAIError(err error) string {
	if err == nil {
		return ""
	}
	lower := strings.ToLower(strings.TrimSpace(err.Error()))
	switch {
	case strings.Contains(lower, "api key"), strings.Contains(lower, "unauthorized"), strings.Contains(lower, "401"), strings.Contains(lower, "forbidden"):
		return "auth_failed"
	case strings.Contains(lower, "timeout"), strings.Contains(lower, "deadline exceeded"):
		return "timeout"
	case strings.Contains(lower, "rate"), strings.Contains(lower, "429"), strings.Contains(lower, "throttl"):
		return "rate_limited"
	case strings.Contains(lower, "model"), strings.Contains(lower, "provider"):
		return "config_invalid"
	default:
		return "unknown"
	}
}

// RecordAITokenUsage 写入 AI Token 使用记录，不影响主流程
func RecordAITokenUsage(db *gorm.DB, record model.AITokenUsage) {
	if !shouldRecordAITokenUsage(record) {
		return
	}
	record.CreatedAt = time.Now()
	if err := db.Create(&record).Error; err != nil {
		logger.Errorf("[AITokenUsage] write failed: %v", err)
	}
}

func shouldRecordAITokenUsage(record model.AITokenUsage) bool {
	return record.TotalTokens > 0
}
