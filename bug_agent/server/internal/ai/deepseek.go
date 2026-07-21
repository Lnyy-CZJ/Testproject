package ai

import "strings"

type DeepSeekClient struct {
	*OpenAICompatibleClient
}

func NewDeepSeekClient(apiKey, baseURL, model string) *DeepSeekClient {
	if baseURL == "" {
		baseURL = "https://api.deepseek.com/v1"
	}
	return &DeepSeekClient{
		OpenAICompatibleClient: NewOpenAICompatibleClient(apiKey, strings.TrimRight(baseURL, "/"), model),
	}
}
