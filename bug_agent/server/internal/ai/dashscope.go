package ai

import "strings"

type DashScopeClient struct {
	*OpenAICompatibleClient
}

func NewDashScopeClient(apiKey, baseURL, model string) *DashScopeClient {
	if baseURL == "" {
		baseURL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
	}
	return &DashScopeClient{
		OpenAICompatibleClient: NewOpenAICompatibleClient(apiKey, strings.TrimRight(baseURL, "/"), model),
	}
}
