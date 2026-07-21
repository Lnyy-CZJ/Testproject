package adk

import (
	"fmt"
	"strings"

	"bug-agent/pkg/logger"

	"gorm.io/gorm"

	bugmodel "bug-agent/internal/model"

	"google.golang.org/adk/agent"
	"google.golang.org/adk/agent/llmagent"
	adkmodel "google.golang.org/adk/model"
	"google.golang.org/genai"
)

func MemoryInjectionCallback(db *gorm.DB, projectID uint) llmagent.BeforeModelCallback {
	return func(ctx agent.CallbackContext, llmRequest *adkmodel.LLMRequest) (*adkmodel.LLMResponse, error) {
		var project bugmodel.Project
		if err := db.Select("memory_enabled").First(&project, projectID).Error; err != nil || !project.MemoryEnabled {
			return nil, nil
		}

		var memories []bugmodel.AgentMemory
		if err := db.Where("project_id = ? AND enabled = ?", projectID, true).
			Order("relevance_score DESC").
			Limit(10).
			Find(&memories).Error; err != nil {
			return nil, nil
		}

		if len(memories) == 0 {
			return nil, nil
		}

		var sb strings.Builder
		sb.WriteString("## 历史记忆（来自过往分析和修复经验）\n")
		for _, mem := range memories {
			sb.WriteString(fmt.Sprintf("- [%s] %s\n", mem.Category, mem.Content))
		}

		memoryContent := &genai.Content{
			Role: genai.RoleUser,
			Parts: []*genai.Part{{
				Text: sb.String(),
			}},
		}
		llmRequest.Contents = append(llmRequest.Contents, memoryContent)

		return nil, nil
	}
}

func MemoryExtractionCallback(db *gorm.DB, projectID uint, createdBy uint) llmagent.AfterModelCallback {
	return func(ctx agent.CallbackContext, llmResponse *adkmodel.LLMResponse, llmResponseError error) (*adkmodel.LLMResponse, error) {
		if llmResponseError != nil || llmResponse == nil || llmResponse.Content == nil {
			return nil, nil
		}

		var project bugmodel.Project
		if err := db.Select("memory_enabled").First(&project, projectID).Error; err != nil || !project.MemoryEnabled {
			return nil, nil
		}

		var text string
		for _, part := range llmResponse.Content.Parts {
			if part.Text != "" {
				text += part.Text
			}
		}

		if text == "" {
			return nil, nil
		}

		categories := []string{
			bugmodel.MemoryCategoryArchitecture,
			bugmodel.MemoryCategoryConvention,
			bugmodel.MemoryCategoryCommonError,
			bugmodel.MemoryCategoryFixStrategy,
		}

		for _, category := range categories {
			if strings.Contains(strings.ToLower(text), strings.ToLower(category)) ||
				strings.Contains(text, "架构") ||
				strings.Contains(text, "规范") ||
				strings.Contains(text, "常见错误") ||
				strings.Contains(text, "修复策略") {
				memory := bugmodel.AgentMemory{
					ProjectID: projectID,
					Category:  category,
					Content:   extractMemoryContent(text, 500),
					Source:    bugmodel.MemorySourceAutoExtract,
					CreatedBy: createdBy,
				}
				if err := db.Create(&memory).Error; err != nil {
					logger.Errorf("[ADK] MemoryExtraction: create memory failed: %v", err)
				}
				break
			}
		}

		return nil, nil
	}
}

func extractMemoryContent(text string, maxLen int) string {
	text = strings.TrimSpace(text)
	runes := []rune(text)
	if len(runes) <= maxLen {
		return text
	}
	return string(runes[:maxLen]) + "..."
}
