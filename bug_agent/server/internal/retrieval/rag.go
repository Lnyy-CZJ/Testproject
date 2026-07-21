package retrieval

import (
	"context"
	"encoding/json"
	"fmt"
)

type RAGRetriever struct {
	endpoint   string
	collection string
}

type ragConfig struct {
	Endpoint   string `json:"endpoint"`
	Collection string `json:"collection"`
}

func RAGConfigSchema() *ConfigSchema {
	return &ConfigSchema{
		Type:     "object",
		Title:    "RAG 检索配置",
		Required: []string{"endpoint"},
		Properties: map[string]ConfigSchemaProperty{
			"endpoint": {
				Type:        "string",
				Title:       "RAG 服务地址",
				Description: "RAG 检索服务基础地址。",
				Format:      "uri",
			},
			"collection": {
				Type:        "string",
				Title:       "Collection",
				Description: "向量库集合名，可选。",
			},
		},
	}
}

func NewRAGRetriever(config string) (*RAGRetriever, error) {
	var cfg ragConfig
	if config != "" {
		if err := json.Unmarshal([]byte(config), &cfg); err != nil {
			return nil, fmt.Errorf("parse rag config: %w", err)
		}
	}
	if cfg.Endpoint == "" {
		return nil, fmt.Errorf("rag config: endpoint is required")
	}
	return &RAGRetriever{
		endpoint:   cfg.Endpoint,
		collection: cfg.Collection,
	}, nil
}

func (r *RAGRetriever) Name() string {
	return "rag"
}

func (r *RAGRetriever) Retrieve(ctx context.Context, query Query) ([]Evidence, error) {
	return nil, fmt.Errorf("RAG retriever is not yet implemented")
}
