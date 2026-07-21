package retrieval

import (
	"context"
	"encoding/json"
	"fmt"
)

type RequirementRetriever struct {
	docPath string
}

type requirementConfig struct {
	DocPath string `json:"docPath"`
}

func RequirementConfigSchema() *ConfigSchema {
	return &ConfigSchema{
		Type:     "object",
		Title:    "需求检索配置",
		Required: []string{"docPath"},
		Properties: map[string]ConfigSchemaProperty{
			"docPath": {
				Type:        "string",
				Title:       "需求文档路径",
				Description: "本地需求文档路径。",
			},
		},
	}
}

func NewRequirementRetriever(config string) (*RequirementRetriever, error) {
	var cfg requirementConfig
	if config != "" {
		if err := json.Unmarshal([]byte(config), &cfg); err != nil {
			return nil, fmt.Errorf("parse requirement config: %w", err)
		}
	}
	if cfg.DocPath == "" {
		return nil, fmt.Errorf("requirement config: docPath is required")
	}
	return &RequirementRetriever{
		docPath: cfg.DocPath,
	}, nil
}

func (r *RequirementRetriever) Name() string {
	return "requirement"
}

func (r *RequirementRetriever) Retrieve(ctx context.Context, query Query) ([]Evidence, error) {
	return nil, fmt.Errorf("requirement retriever is not yet implemented")
}
