package ai

import "strings"

type OpenAIClient struct {
	*OpenAICompatibleClient
}

func NewOpenAIClient(apiKey, baseURL, model string) *OpenAIClient {
	if baseURL == "" {
		baseURL = "https://api.openai.com/v1"
	}
	return &OpenAIClient{
		OpenAICompatibleClient: NewOpenAICompatibleClient(apiKey, strings.TrimRight(baseURL, "/"), model),
	}
}
