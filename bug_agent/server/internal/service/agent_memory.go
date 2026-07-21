package service

import (
	"bug-agent/internal/ai"
	"bug-agent/internal/asyncx"
	"bug-agent/internal/model"
	"context"
	"encoding/json"
	"fmt"
	"bug-agent/pkg/logger"
	"strings"
	"time"

	"gorm.io/gorm"
)

const (
	defaultMemoryMaxTokens    = 2000
	defaultMemorySummaryTokens = 1024
)

type AgentMemoryService struct {
	db       *gorm.DB
	aiClient ai.AIClient
}

func NewAgentMemoryService(db *gorm.DB) *AgentMemoryService {
	return &AgentMemoryService{db: db}
}

func (s *AgentMemoryService) ListMemories(projectID uint, iterationID *uint, category string) ([]model.AgentMemory, error) {
	var memories []model.AgentMemory
	q := s.db.Where("project_id = ?", projectID)
	if iterationID != nil {
		q = q.Where("iteration_id = ?", *iterationID)
	} else {
		q = q.Where("iteration_id IS NULL")
	}
	if category != "" {
		q = q.Where("category = ?", category)
	}
	q = q.Order("relevance_score DESC, created_at DESC")
	if err := q.Find(&memories).Error; err != nil {
		return nil, err
	}
	return memories, nil
}

func (s *AgentMemoryService) CreateMemory(memory *model.AgentMemory) error {
	now := time.Now()
	if memory.CreatedAt.IsZero() {
		memory.CreatedAt = now
	}
	if memory.UpdatedAt.IsZero() {
		memory.UpdatedAt = now
	}

	var existing []model.AgentMemory
	q := s.db.Where("project_id = ? AND category = ?", memory.ProjectID, memory.Category)
	if memory.IterationID != nil {
		q = q.Where("iteration_id = ?", *memory.IterationID)
	} else {
		q = q.Where("iteration_id IS NULL")
	}
	if err := q.Order("updated_at DESC").Limit(100).Find(&existing).Error; err != nil {
		logger.Errorf("查询已有记忆失败: %v", err)
	}

	newTokens := tokenize(memory.Content)
	existingTokens := make([]map[string]bool, len(existing))
	for i, e := range existing {
		existingTokens[i] = tokenize(e.Content)
	}
	for i, e := range existing {
		if jaccardSimilarityWithTokens(newTokens, existingTokens[i]) > 0.8 {
			updates := map[string]interface{}{
				"content":         memory.Content,
				"relevance_score": maxFloat64(e.RelevanceScore, memory.RelevanceScore),
				"updated_at":      now,
			}
			return s.db.Model(&model.AgentMemory{}).Where("id = ?", e.ID).Updates(updates).Error
		}
	}

	return s.db.Create(memory).Error
}

func (s *AgentMemoryService) GetMemory(memoryID uint) (*model.AgentMemory, error) {
	var memory model.AgentMemory
	if err := s.db.First(&memory, memoryID).Error; err != nil {
		return nil, err
	}
	return &memory, nil
}

func (s *AgentMemoryService) UpdateMemory(memoryID uint, updates map[string]interface{}) error {
	return s.db.Model(&model.AgentMemory{}).Where("id = ?", memoryID).Updates(updates).Error
}

func (s *AgentMemoryService) DeleteMemory(memoryID uint) error {
	return s.db.Delete(&model.AgentMemory{}, memoryID).Error
}

func (s *AgentMemoryService) ToggleMemory(memoryID uint) error {
	var memory model.AgentMemory
	if err := s.db.First(&memory, memoryID).Error; err != nil {
		return err
	}
	return s.db.Model(&model.AgentMemory{}).Where("id = ?", memoryID).
		Updates(map[string]interface{}{
			"enabled":    !memory.Enabled,
			"updated_at": time.Now(),
		}).Error
}

func (s *AgentMemoryService) BuildMemoryContext(projectID uint, iterationID uint) string {
	var project model.Project
	if err := s.db.Select("memory_enabled").First(&project, projectID).Error; err != nil || !project.MemoryEnabled {
		return ""
	}

	var memories []model.AgentMemory

	if err := s.db.Where(
		"project_id = ? AND enabled = true AND (iteration_id IS NULL OR iteration_id = ?)",
		projectID, iterationID,
	).Order("relevance_score DESC, created_at DESC").Limit(50).Find(&memories).Error; err != nil {
		logger.Errorf("构建记忆上下文查询失败: %v", err)
	}

	var builder strings.Builder
	tokenEstimate := 0
	maxTokens := defaultMemoryMaxTokens

	for _, m := range memories {
		entry := fmt.Sprintf("- [%s] %s", m.Category, m.Content)
		entryTokens := len(entry) / 4
		if tokenEstimate+entryTokens > maxTokens {
			break
		}
		builder.WriteString(entry + "\n")
		tokenEstimate += entryTokens
	}

	return builder.String()
}

func (s *AgentMemoryService) ExtractMemoriesFromAnalysis(defectID uint, report model.AnalysisReport) error {
	var defect model.Defect
	if err := s.db.Preload("Iteration").First(&defect, defectID).Error; err != nil {
		return err
	}

	var project model.Project
	if err := s.db.Select("memory_enabled").First(&project, defect.Iteration.ProjectID).Error; err != nil || !project.MemoryEnabled {
		return nil
	}

	configs, err := listUsableProjectAIConfigs(s.db, defect.Iteration.ProjectID)
	if err != nil || len(configs) == 0 {
		logger.Infof("[AgentMemory] 无可用AI配置，跳过分析记忆提取: %v", err)
		return nil
	}

	aiClient, err := ai.NewAIClient(configs[0].Provider, configs[0].APIKey, configs[0].APIEndpoint, configs[0].ModelName)
	if err != nil {
		logger.Errorf("[AgentMemory] 创建AI客户端失败，跳过分析记忆提取: %v", err)
		return nil
	}

	prompt := ai.BuildAnalysisMemoryExtractionPrompt(defect.Title, defect.Type, report.Analysis)

	asyncx.Go(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()

		resp, err := aiClient.Chat(ctx, &ai.ChatRequest{
			Model:       configs[0].ModelName,
			Messages:    []ai.Message{{Role: "user", Content: prompt}},
			Temperature: 0.3,
			MaxTokens:   defaultMemorySummaryTokens,
		})
		if err != nil {
			logger.Errorf("[AgentMemory] 分析记忆提取AI调用失败: %v", err)
			return
		}
		if len(resp.Choices) == 0 {
			return
		}

		items := parseMemoryExtractionResponse(resp.Choices[0].Message.Content)
		for _, item := range items {
			memory := &model.AgentMemory{
				ProjectID:      defect.Iteration.ProjectID,
				IterationID:    &defect.IterationID,
				Category:       item.Category,
				Content:        item.Content,
				Source:         model.MemorySourceAutoExtract,
				RelevanceScore: item.RelevanceScore,
				Enabled:        true,
			}
			if err := s.CreateMemory(memory); err != nil {
				logger.Errorf("[AgentMemory] 保存分析记忆失败: %v", err)
			}
		}
	})

	return nil
}

func (s *AgentMemoryService) ExtractMemoriesFromFix(defectID uint, fixTask model.FixTask) error {
	var defect model.Defect
	if err := s.db.Preload("Iteration").First(&defect, defectID).Error; err != nil {
		return err
	}

	var project model.Project
	if err := s.db.Select("memory_enabled").First(&project, defect.Iteration.ProjectID).Error; err != nil || !project.MemoryEnabled {
		return nil
	}

	configs, err := listUsableProjectAIConfigs(s.db, defect.Iteration.ProjectID)
	if err != nil || len(configs) == 0 {
		logger.Infof("[AgentMemory] 无可用AI配置，跳过修复记忆提取: %v", err)
		return nil
	}

	aiClient, err := ai.NewAIClient(configs[0].Provider, configs[0].APIKey, configs[0].APIEndpoint, configs[0].ModelName)
	if err != nil {
		logger.Errorf("[AgentMemory] 创建AI客户端失败，跳过修复记忆提取: %v", err)
		return nil
	}

	prompt := ai.BuildFixMemoryExtractionPrompt(defect.Title, fixTask.Plan, fixTask.Result)

	asyncx.Go(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()

		resp, err := aiClient.Chat(ctx, &ai.ChatRequest{
			Model:       configs[0].ModelName,
			Messages:    []ai.Message{{Role: "user", Content: prompt}},
			Temperature: 0.3,
			MaxTokens:   defaultMemorySummaryTokens,
		})
		if err != nil {
			logger.Errorf("[AgentMemory] 修复记忆提取AI调用失败: %v", err)
			return
		}
		if len(resp.Choices) == 0 {
			return
		}

		items := parseMemoryExtractionResponse(resp.Choices[0].Message.Content)
		for _, item := range items {
			memory := &model.AgentMemory{
				ProjectID:      defect.Iteration.ProjectID,
				IterationID:    &defect.IterationID,
				Category:       item.Category,
				Content:        item.Content,
				Source:         model.MemorySourceAutoExtract,
				RelevanceScore: item.RelevanceScore,
				Enabled:        true,
			}
			if err := s.CreateMemory(memory); err != nil {
				logger.Errorf("[AgentMemory] 保存修复记忆失败: %v", err)
			}
		}
	})

	return nil
}

func (s *AgentMemoryService) ExtractMemoryFromPRRejection(rejection model.PRRejection, fixTask model.FixTask, projectID uint) error {
	var defect model.Defect
	if err := s.db.Preload("Iteration").First(&defect, fixTask.DefectID).Error; err != nil {
		return err
	}

	var project model.Project
	if err := s.db.Select("memory_enabled").First(&project, projectID).Error; err != nil || !project.MemoryEnabled {
		return nil
	}

	memory := &model.AgentMemory{
		ProjectID:      defect.Iteration.ProjectID,
		Category:       model.MemoryCategoryAvoidStrategy,
		Content:        fmt.Sprintf("修复策略在 %s 场景下被拒绝，原因：%s", defect.Title, rejection.RejectReason),
		Source:         model.MemorySourcePRRejection,
		SourceRefID:    &rejection.ID,
		RelevanceScore: 0.8,
		Enabled:        true,
	}
	return s.CreateMemory(memory)
}

type memoryExtractionItem struct {
	Category       string  `json:"category"`
	Content        string  `json:"content"`
	RelevanceScore float64 `json:"relevanceScore"`
}

func parseMemoryExtractionResponse(text string) []memoryExtractionItem {
	text = strings.TrimSpace(text)
	text = stripMarkdownCodeBlock(text)
	text = strings.TrimPrefix(text, "\xEF\xBB\xBF")
	text = strings.TrimSpace(text)

	start := strings.Index(text, "[")
	end := strings.LastIndex(text, "]")
	if start < 0 || end < 0 || end <= start {
		objStart := strings.Index(text, "{")
		objEnd := strings.LastIndex(text, "}")
		if objStart >= 0 && objEnd > 0 && objEnd > objStart {
			wrapped := "[" + text[objStart:objEnd+1] + "]"
			var items []memoryExtractionItem
			if err := json.Unmarshal([]byte(wrapped), &items); err == nil {
				return items
			}
		}
		return nil
	}

	var items []memoryExtractionItem
	if err := json.Unmarshal([]byte(text[start:end+1]), &items); err != nil {
		logger.Errorf("[AgentMemory] 解析记忆提取结果失败: %v", err)
		return nil
	}
	return items
}

func jaccardSimilarity(a, b string) float64 {
	return jaccardSimilarityWithTokens(tokenize(a), tokenize(b))
}

func jaccardSimilarityWithTokens(setA, setB map[string]bool) float64 {
	if len(setA) == 0 && len(setB) == 0 {
		return 0
	}

	intersection := 0
	for k := range setA {
		if setB[k] {
			intersection++
		}
	}
	union := len(setA) + len(setB) - intersection
	if union == 0 {
		return 0
	}
	return float64(intersection) / float64(union)
}

func tokenize(text string) map[string]bool {
	set := make(map[string]bool)
	lower := strings.ToLower(text)
	for _, word := range strings.Fields(lower) {
		word = strings.TrimSpace(word)
		if word != "" {
			set[word] = true
		}
	}
	runes := []rune(lower)
	if len(runes) > 1 {
		for i := 0; i < len(runes)-1; i++ {
			bigram := string(runes[i]) + string(runes[i+1])
			set[bigram] = true
		}
	}
	return set
}

func maxFloat64(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}
