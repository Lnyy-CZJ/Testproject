package ai

import "strings"

type ZhipuClient struct {
	*OpenAICompatibleClient
}

func NewZhipuClient(apiKey, baseURL, model string) *ZhipuClient {
	if baseURL == "" {
		baseURL = "https://open.bigmodel.cn/api/paas/v4"
	}
	return &ZhipuClient{
		OpenAICompatibleClient: NewOpenAICompatibleClient(apiKey, strings.TrimRight(baseURL, "/"), model),
	}
}
