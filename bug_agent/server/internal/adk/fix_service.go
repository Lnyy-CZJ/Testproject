package adk

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"bug-agent/internal/ai"
	bugmodel "bug-agent/internal/model"
	"bug-agent/internal/service"

	"google.golang.org/adk/agent"
	adkmodel "google.golang.org/adk/model"
	"google.golang.org/adk/session"
	"google.golang.org/genai"
	"gorm.io/gorm"
)

type ADKFixService struct {
	db         *gorm.DB
	sessionSvc session.Service
	fixSvc     *service.FixService
}

func NewADKFixService(db *gorm.DB) (*ADKFixService, error) {
	sessionSvc, err := InitSessionService(db)
	if err != nil {
		return nil, fmt.Errorf("InitSessionService: %w", err)
	}
	return &ADKFixService{
		db:         db,
		sessionSvc: sessionSvc,
		fixSvc:     service.NewFixService(db),
	}, nil
}

func (s *ADKFixService) PerformAutoFix(ctx context.Context, req service.FixRequest) (*service.FixResult, error) {
	return s.fixSvc.PerformAutoFix(ctx, req)
}

func (s *ADKFixService) CreateAutoFixGroup(ctx context.Context, req service.FixRequest) (*service.FixResult, error) {
	return s.fixSvc.CreateAutoFixGroup(ctx, req)
}

func (s *ADKFixService) GenerateFixWithADK(
	ctx context.Context,
	defect bugmodel.Defect,
	report bugmodel.AnalysisReport,
	task *bugmodel.FixTask,
) (*ai.FixPlan, ai.FixGenerationMetrics, error) {
	configs, err := listUsableAIConfigs(s.db, defect.Iteration.ProjectID)
	if err != nil {
		return nil, ai.FixGenerationMetrics{}, fmt.Errorf("resolve AI configs: %w", err)
	}

	var attemptErrors []string
	for index, cfg := range configs {
		attemptStart := time.Now()
		if err := service.HydrateProjectAIConfig(&cfg); err != nil {
			attemptErrors = append(attemptErrors, fmt.Sprintf("%s/%s: %v", cfg.Provider, cfg.ModelName, err))
			// 配置不可用，记录失败的 AITokenUsage
			service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
				ProjectID:       defect.Iteration.ProjectID,
				IterationID:     &defect.IterationID,
				DefectID:        defect.ID,
				ConsumptionType: "fix",
				SourceID:        task.ID,
				AttemptIndex:    index,
				IsFinalAttempt:  index == len(configs)-1,
				Provider:        cfg.Provider,
				ModelName:       cfg.ModelName,
				DurationMs:      time.Since(attemptStart).Milliseconds(),
			})
			continue
		}

		llm, err := NewLLM(ctx, &cfg)
		if err != nil {
			attemptErrors = append(attemptErrors, fmt.Sprintf("%s/%s: %v", cfg.Provider, cfg.ModelName, err))
			// LLM 创建失败，记录失败的 AITokenUsage
			service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
				ProjectID:       defect.Iteration.ProjectID,
				IterationID:     &defect.IterationID,
				DefectID:        defect.ID,
				ConsumptionType: "fix",
				SourceID:        task.ID,
				AttemptIndex:    index,
				IsFinalAttempt:  index == len(configs)-1,
				Provider:        cfg.Provider,
				ModelName:       cfg.ModelName,
				DurationMs:      time.Since(attemptStart).Milliseconds(),
			})
			continue
		}

		plan, metrics, planErr := s.generateFixWithLLM(ctx, llm, report, cfg)
		isFinal := index == len(configs)-1 || planErr == nil
		estimatedCost := service.EstimateAICostUSD(cfg.Provider, cfg.ModelName, ai.Usage{
			PromptTokens:     metrics.PromptTokens,
			CompletionTokens: metrics.CompletionTokens,
			TotalTokens:      metrics.TotalTokens,
		})
		if planErr == nil {
			// 记录成功的 AITokenUsage
			service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
				ProjectID:        defect.Iteration.ProjectID,
				IterationID:      &defect.IterationID,
				DefectID:         defect.ID,
				ConsumptionType:  "fix",
				SourceID:         task.ID,
				AttemptIndex:     index,
				IsFinalAttempt:   isFinal,
				Provider:         cfg.Provider,
				ModelName:        cfg.ModelName,
				PromptTokens:     metrics.PromptTokens,
				CompletionTokens: metrics.CompletionTokens,
				TotalTokens:      metrics.TotalTokens,
				EstimatedCostUSD: estimatedCost,
				DurationMs:       time.Since(attemptStart).Milliseconds(),
			})
			return plan, metrics, nil
		}
		attemptErrors = append(attemptErrors, fmt.Sprintf("%s/%s: %v", cfg.Provider, cfg.ModelName, planErr))
		// 记录失败的 AITokenUsage
		service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
			ProjectID:        defect.Iteration.ProjectID,
			IterationID:      &defect.IterationID,
			DefectID:         defect.ID,
			ConsumptionType:  "fix",
			SourceID:         task.ID,
			AttemptIndex:     index,
			IsFinalAttempt:   isFinal,
			Provider:         cfg.Provider,
			ModelName:        cfg.ModelName,
			PromptTokens:     metrics.PromptTokens,
			CompletionTokens: metrics.CompletionTokens,
			TotalTokens:      metrics.TotalTokens,
			EstimatedCostUSD: estimatedCost,
			DurationMs:       time.Since(attemptStart).Milliseconds(),
		})
	}

	return nil, ai.FixGenerationMetrics{}, fmt.Errorf("all models failed: %s", strings.Join(attemptErrors, "; "))
}

func (s *ADKFixService) generateFixWithLLM(
	ctx context.Context,
	llm adkmodel.LLM,
	report bugmodel.AnalysisReport,
	cfg bugmodel.ProjectAIConfig,
) (*ai.FixPlan, ai.FixGenerationMetrics, error) {
	userID := fmt.Sprintf("fix_user_%d", report.DefectID)
	sessionID := fmt.Sprintf("fix_%d_%d", report.DefectID, time.Now().UnixMilli())

	_, err := s.sessionSvc.Create(ctx, &session.CreateRequest{
		AppName:   "bug-agent",
		UserID:    userID,
		SessionID: sessionID,
	})
	if err != nil {
		return nil, ai.FixGenerationMetrics{}, fmt.Errorf("session create: %w", err)
	}
	defer s.sessionSvc.Delete(ctx, &session.DeleteRequest{
		AppName: "bug-agent", UserID: userID, SessionID: sessionID,
	})

	pipeline, err := NewFixPipeline(FixPipelineConfig{
		LLM:        llm,
		SessionSvc: s.sessionSvc,
		AppName:    "bug-agent",
	})
	if err != nil {
		return nil, ai.FixGenerationMetrics{}, fmt.Errorf("NewFixPipeline: %w", err)
	}

	prompt := fmt.Sprintf("根据以下分析报告生成修复方案：\n\n%s", report.Analysis)
	userMsg := &genai.Content{
		Role:  genai.RoleUser,
		Parts: []*genai.Part{{Text: prompt}},
	}

	startTime := time.Now()
	events := pipeline.Run(ctx, userID, sessionID, userMsg, agent.RunConfig{})

	collected, err := CollectEvents(events)
	if err != nil {
		return nil, ai.FixGenerationMetrics{}, fmt.Errorf("collect events: %w", err)
	}

	var fullText string
	var totalTokens, promptTokens, completionTokens int
	for _, evt := range collected {
		if evt.Content != nil {
			for _, part := range evt.Content.Parts {
				if part.Text != "" {
					fullText += part.Text
				}
			}
		}
		if evt.UsageMetadata != nil {
			totalTokens = maxInt(totalTokens, int(evt.UsageMetadata.TotalTokenCount))
			promptTokens = maxInt(promptTokens, int(evt.UsageMetadata.PromptTokenCount))
			completionTokens = maxInt(completionTokens, int(evt.UsageMetadata.CandidatesTokenCount))
		}
	}

	fixPlan := parseFixPlanFromText(fullText)
	if fixPlan == nil {
		return nil, ai.FixGenerationMetrics{}, fmt.Errorf("failed to parse fix plan from ADK response")
	}

	metrics := ai.FixGenerationMetrics{
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		TotalTokens:      totalTokens,
		DurationMs:       time.Since(startTime).Milliseconds(),
	}

	return fixPlan, metrics, nil
}

func parseFixPlanFromText(text string) *ai.FixPlan {
	if idx := strings.Index(text, "{"); idx >= 0 {
		end := strings.LastIndex(text, "}") + 1
		if end > idx {
			rawJSON := text[idx:end]
			var parsed map[string]interface{}
			if err := json.Unmarshal([]byte(rawJSON), &parsed); err == nil {
				stepsRaw, ok := parsed["codeChanges"]
				if !ok {
					stepsRaw, ok = parsed["steps"]
				}
				if !ok {
					return nil
				}
				stepsSlice, ok := stepsRaw.([]interface{})
				if !ok {
					return nil
				}
				fixPlan := &ai.FixPlan{Steps: make([]ai.FixStep, 0, len(stepsSlice))}
				for i, s := range stepsSlice {
					sm, ok := s.(map[string]interface{})
					if !ok {
						continue
					}
					step := ai.FixStep{
						Step:   i + 1,
						Status: "pending",
					}
					if action, ok := sm["action"].(string); ok {
						step.Action = action
					} else if desc, ok := sm["change"].(string); ok {
						step.Action = desc
					}
					if fp, ok := sm["path"].(string); ok {
						step.FilePath = fp
					} else if fp, ok := sm["filePath"].(string); ok {
						step.FilePath = fp
					}
					if orig, ok := sm["original"].(string); ok {
						if fixed, ok := sm["fixed"].(string); ok {
							step.CodeChange = &ai.CodeChange{
								FilePath:    step.FilePath,
								OldContent:  orig,
								NewContent:  fixed,
								Description: step.Action,
							}
						}
					}
					fixPlan.Steps = append(fixPlan.Steps, step)
				}
				if len(fixPlan.Steps) > 0 {
					return fixPlan
				}
			}
		}
	}
	return nil
}

func listUsableAIConfigs(db *gorm.DB, projectID uint) ([]bugmodel.ProjectAIConfig, error) {
	var configs []bugmodel.ProjectAIConfig
	if err := db.Where("project_id = ?", projectID).Order("is_default DESC").Find(&configs).Error; err != nil {
		return nil, err
	}
	return configs, nil
}
