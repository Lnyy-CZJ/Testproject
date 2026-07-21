package model

import "time"

// AIProviderCatalog 平台级AI厂商目录
type AIProviderCatalog struct {
	ID              uint      `json:"id" gorm:"primaryKey"`
	ProviderKey     string    `json:"providerKey" gorm:"size:50;uniqueIndex;not null"` // openai/zhipu/deepseek...
	DisplayName     string    `json:"displayName" gorm:"size:100;not null"`
	DefaultEndpoint string    `json:"defaultEndpoint" gorm:"size:500"`
	Status          string    `json:"status" gorm:"size:20;not null;default:'active'"` // active/inactive
	SortOrder       int       `json:"sortOrder" gorm:"default:0"`
	CreatedAt       time.Time `json:"createdAt"`
	UpdatedAt       time.Time `json:"updatedAt"`
}

func (AIProviderCatalog) TableName() string { return "ai_provider_catalog" }

// AIModelCatalog 平台级AI模型目录
type AIModelCatalog struct {
	ID             uint      `json:"id" gorm:"primaryKey"`
	ProviderKey    string    `json:"providerKey" gorm:"size:50;index;not null"`
	ModelName      string    `json:"modelName" gorm:"size:100;not null"`
	Endpoint       string    `json:"endpoint" gorm:"size:500"`
	CapabilityTags string    `json:"capabilityTags" gorm:"size:200"`                  // chat,reasoning,code
	Status         string    `json:"status" gorm:"size:20;not null;default:'active'"` // active/deprecated/inactive
	IsDefault      bool      `json:"isDefault" gorm:"default:false"`
	SortOrder      int       `json:"sortOrder" gorm:"default:0"`
	CreatedAt      time.Time `json:"createdAt"`
	UpdatedAt      time.Time `json:"updatedAt"`
}

func (AIModelCatalog) TableName() string { return "ai_model_catalog" }
