package model

import "gorm.io/gorm"

var defaultAIProviderCatalog = []AIProviderCatalog{
	{ProviderKey: "openai", DisplayName: "OpenAI", DefaultEndpoint: "https://api.openai.com/v1", Status: "active", SortOrder: 10},
	{ProviderKey: "anthropic", DisplayName: "Anthropic", DefaultEndpoint: "https://api.anthropic.com", Status: "active", SortOrder: 20},
	{ProviderKey: "zhipu", DisplayName: "智谱AI", DefaultEndpoint: "https://open.bigmodel.cn/api/paas/v4", Status: "active", SortOrder: 30},
	{ProviderKey: "deepseek", DisplayName: "DeepSeek", DefaultEndpoint: "https://api.deepseek.com/v1", Status: "active", SortOrder: 40},
	{ProviderKey: "dashscope", DisplayName: "阿里云 DashScope", DefaultEndpoint: "https://dashscope.aliyuncs.com/compatible-mode/v1", Status: "active", SortOrder: 50},
}

var defaultAIModelCatalog = []AIModelCatalog{
	{ProviderKey: "openai", ModelName: "gpt-5.4", CapabilityTags: "chat,fc", Status: "active", IsDefault: true, SortOrder: 10},
	{ProviderKey: "openai", ModelName: "gpt-5.4-mini", CapabilityTags: "chat,fc", Status: "active", SortOrder: 20},
	{ProviderKey: "openai", ModelName: "gpt-5.4-nano", CapabilityTags: "chat,fc", Status: "active", SortOrder: 30},
	{ProviderKey: "openai", ModelName: "gpt-4.1", CapabilityTags: "chat,fc", Status: "active", SortOrder: 40},
	{ProviderKey: "openai", ModelName: "gpt-4.1-mini", CapabilityTags: "chat,fc", Status: "active", SortOrder: 50},
	{ProviderKey: "openai", ModelName: "o3", CapabilityTags: "chat,reasoning,fc", Status: "active", SortOrder: 60},

	{ProviderKey: "anthropic", ModelName: "claude-opus-4-1-20250805", CapabilityTags: "chat,fc", Status: "active", IsDefault: true, SortOrder: 10},
	{ProviderKey: "anthropic", ModelName: "claude-sonnet-4-20250514", CapabilityTags: "chat,fc", Status: "active", SortOrder: 20},
	{ProviderKey: "anthropic", ModelName: "claude-haiku-3-5-20241022", CapabilityTags: "chat,fc", Status: "active", SortOrder: 30},

	{ProviderKey: "zhipu", ModelName: "glm-5", CapabilityTags: "chat,fc", Status: "active", IsDefault: true, SortOrder: 10},
	{ProviderKey: "zhipu", ModelName: "glm-4.7", CapabilityTags: "chat,fc", Status: "active", SortOrder: 20},
	{ProviderKey: "zhipu", ModelName: "glm-4.6", CapabilityTags: "chat,fc", Status: "active", SortOrder: 30},
	{ProviderKey: "zhipu", ModelName: "glm-4.5", CapabilityTags: "chat", Status: "active", SortOrder: 40},
	{ProviderKey: "zhipu", ModelName: "glm-4.5-air", CapabilityTags: "chat", Status: "active", SortOrder: 50},

	{ProviderKey: "deepseek", ModelName: "deepseek-chat", CapabilityTags: "chat,fc", Status: "active", IsDefault: true, SortOrder: 10},
	{ProviderKey: "deepseek", ModelName: "deepseek-reasoner", CapabilityTags: "chat,reasoning", Status: "active", SortOrder: 20},

	{ProviderKey: "dashscope", ModelName: "qwen-max-latest", CapabilityTags: "chat,fc", Status: "active", IsDefault: true, SortOrder: 10},
	{ProviderKey: "dashscope", ModelName: "qwen-plus-latest", CapabilityTags: "chat,fc", Status: "active", SortOrder: 20},
	{ProviderKey: "dashscope", ModelName: "qwen-turbo-latest", CapabilityTags: "chat,fc", Status: "active", SortOrder: 30},
	{ProviderKey: "dashscope", ModelName: "qwen-flash", CapabilityTags: "chat,fc", Status: "active", SortOrder: 40},
	{ProviderKey: "dashscope", ModelName: "qwen3-max-preview", CapabilityTags: "chat,fc", Status: "active", SortOrder: 50},
}

func SeedDefaultAICatalog(db *gorm.DB) error {
	if db == nil {
		return nil
	}

	var count int64
	if err := db.Model(&AIProviderCatalog{}).Count(&count).Error; err != nil {
		return err
	}
	if count > 0 {
		return nil
	}

	return db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&defaultAIProviderCatalog).Error; err != nil {
			return err
		}
		if err := tx.Create(&defaultAIModelCatalog).Error; err != nil {
			return err
		}
		return nil
	})
}
