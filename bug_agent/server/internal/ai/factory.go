package ai

import (
	"bug-agent/internal/config"
	"context"
	"fmt"
	"strings"
)

type mockFailClient struct {
	err error
}

func (c *mockFailClient) Chat(context.Context, *ChatRequest) (*ChatResponse, error) {
	return nil, c.err
}

func (c *mockFailClient) ChatStream(context.Context, *ChatRequest) (<-chan *StreamChunk, error) {
	return nil, c.err
}

// NewAIClient 根据厂商类型创建AI客户端
func NewAIClient(provider, apiKey, apiEndpoint, model string) (AIClient, error) {
	provider = strings.ToLower(strings.TrimSpace(provider))

	if provider == "mock-fail" {
		if strings.EqualFold(strings.TrimSpace(config.C.Server.Mode), "release") {
			return nil, fmt.Errorf("mock-fail provider is disabled in release mode")
		}
		return &mockFailClient{err: fmt.Errorf("mock AI analysis failure triggered")}, nil
	}

	if apiKey == "" {
		return nil, fmt.Errorf("API key is required")
	}

	if model == "" {
		return nil, fmt.Errorf("model name is required")
	}

	switch provider {
	case "openai":
		return NewOpenAIClient(apiKey, apiEndpoint, model), nil

	case "智谱ai", "zhipu", "zhipuai", "bigmodel":
		return NewZhipuClient(apiKey, apiEndpoint, model), nil

	case "deepseek":
		return NewDeepSeekClient(apiKey, apiEndpoint, model), nil

	case "anthropic":
		return NewAnthropicClient(apiKey, apiEndpoint, model), nil

	case "阿里云百炼", "alibaba", "dashscope":
		return NewDashScopeClient(apiKey, apiEndpoint, model), nil

	case "moonshot", "kimi":
		// Moonshot也兼容OpenAI API格式
		baseURL := apiEndpoint
		if baseURL == "" {
			baseURL = "https://api.moonshot.cn/v1"
		}
		return NewOpenAIClient(apiKey, baseURL, model), nil

	default:
		// 默认尝试使用OpenAI兼容格式
		return NewOpenAIClient(apiKey, apiEndpoint, model), nil
	}
}

// GetDefaultModel 根据厂商获取默认模型名称
func GetDefaultModel(provider string) string {
	switch strings.ToLower(strings.TrimSpace(provider)) {
	case "openai":
		return "gpt-5.4"
	case "智谱ai", "zhipu", "zhipuai":
		return "glm-5"
	case "deepseek":
		return "deepseek-chat"
	case "anthropic":
		return "claude-sonnet-4-20250514"
	case "moonshot", "kimi":
		return "moonshot-v1-8k"
	default:
		return "gpt-5.4"
	}
}
