package adk

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"iter"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"bug-agent/internal/ai"
	"bug-agent/internal/asyncx"
	"bug-agent/internal/git"
	bugmodel "bug-agent/internal/model"
	"bug-agent/internal/retrieval"
	"bug-agent/internal/service"
	"bug-agent/internal/sse"
	"bug-agent/internal/util"
	"bug-agent/pkg/logger"

	"github.com/google/uuid"
	"google.golang.org/adk/agent"
	adkmodel "google.golang.org/adk/model"
	"google.golang.org/adk/runner"
	"google.golang.org/adk/session"
	"google.golang.org/adk/tool"
	"google.golang.org/genai"
	"gorm.io/gorm"
)

func generateADKReportCode() string {
	u := uuid.New()
	short := u.String()[:8]
	return fmt.Sprintf("ADK-%s-%s", time.Now().Format("20060102"), short)
}

const (
	maxContextChars          = 12000
	analysisTemperature      = 0.7
	analysisMaxTokens        = 4096
	defaultAnalysisMaxTokens = 2048
	cloneTimeout             = 30 * time.Second
)

type ADKAnalysisService struct {
	db         *gorm.DB
	sessionSvc session.Service
	retriever  retrieval.Retriever
	registry   *retrieval.RetrieverPluginRegistry
	rollout    *RolloutRecorder
	scheduler  *AgentScheduler

	configCache   map[uint][]bugmodel.ProjectAIConfig
	configCacheMu sync.RWMutex
	configCacheAt map[uint]time.Time

	retrieverCache   map[uint]retrieval.Retriever
	retrieverCacheMu sync.RWMutex
	retrieverCacheAt map[uint]time.Time

	mcpServers []MCPServerConfig

	runningMu   sync.Mutex
	runningCtxs map[uint]context.CancelFunc
}

func NewADKAnalysisService(db *gorm.DB) (*ADKAnalysisService, error) {
	sessionSvc, err := InitSessionService(db)
	if err != nil {
		return nil, fmt.Errorf("InitSessionService: %w", err)
	}
	return &ADKAnalysisService{
		db:          db,
		sessionSvc:  sessionSvc,
		retriever:   retrieval.NewRouter(retrieval.NewKeywordRetriever()),
		rollout:     InitRolloutRecorder(db),
		runningCtxs: make(map[uint]context.CancelFunc),
	}, nil
}

func NewADKAnalysisServiceWithRetriever(db *gorm.DB, retrieverImpl retrieval.Retriever) (*ADKAnalysisService, error) {
	svc, err := NewADKAnalysisService(db)
	if err != nil {
		return nil, err
	}
	if retrieverImpl != nil {
		svc.retriever = retrieverImpl
	}
	return svc, nil
}

func (s *ADKAnalysisService) SetMCPServers(servers []MCPServerConfig) {
	s.mcpServers = servers
}

func (s *ADKAnalysisService) SetRegistry(registry *retrieval.RetrieverPluginRegistry) {
	s.registry = registry
}

func (s *ADKAnalysisService) SetScheduler(scheduler *AgentScheduler) {
	s.scheduler = scheduler
}

const retrieverCacheTTL = 5 * time.Minute

func (s *ADKAnalysisService) buildRetrieverForProject(projectID uint) retrieval.Retriever {
	s.retrieverCacheMu.RLock()
	if cachedAt, ok := s.retrieverCacheAt[projectID]; ok && time.Since(cachedAt) < retrieverCacheTTL {
		if r, ok2 := s.retrieverCache[projectID]; ok2 && r != nil {
			s.retrieverCacheMu.RUnlock()
			return r
		}
	}
	s.retrieverCacheMu.RUnlock()

	var r retrieval.Retriever
	if s.registry == nil {
		r = retrieval.NewRouter(retrieval.NewKeywordRetriever())
	} else {
		var plugins []bugmodel.RetrieverPlugin
		if err := s.db.Where("project_id = ? AND enabled = ?", projectID, true).Order("sort_order ASC").Find(&plugins).Error; err != nil {
			logger.Errorf("[ADKAnalysis] query retriever plugins failed: %v", err)
			r = retrieval.NewRouter(retrieval.NewKeywordRetriever())
		} else if len(plugins) == 0 {
			r = retrieval.NewRouter(retrieval.NewKeywordRetriever())
		} else {
			var retrievers []retrieval.Retriever
			for _, plugin := range plugins {
				rr, err := s.registry.Create(plugin.Name, plugin.Config)
				if err != nil {
					logger.Errorf("[ADKAnalysis] create retriever plugin %s failed: %v", plugin.Name, err)
					continue
				}
				retrievers = append(retrievers, rr)
			}
			if len(retrievers) == 0 {
				r = retrieval.NewRouter(retrieval.NewKeywordRetriever())
			} else {
				r = retrieval.NewRouter(retrievers...)
			}
		}
	}

	s.retrieverCacheMu.Lock()
	if s.retrieverCache == nil {
		s.retrieverCache = make(map[uint]retrieval.Retriever)
	}
	if s.retrieverCacheAt == nil {
		s.retrieverCacheAt = make(map[uint]time.Time)
	}
	if len(s.retrieverCache) > 1000 {
		type cacheEntry struct {
			key uint
			at  time.Time
		}
		entries := make([]cacheEntry, 0, len(s.retrieverCacheAt))
		for k, v := range s.retrieverCacheAt {
			entries = append(entries, cacheEntry{k, v})
		}
		sort.Slice(entries, func(i, j int) bool {
			return entries[i].at.Before(entries[j].at)
		})
		evictCount := 500
		if len(entries) < evictCount {
			evictCount = len(entries)
		}
		for i := 0; i < evictCount; i++ {
			delete(s.retrieverCache, entries[i].key)
			delete(s.retrieverCacheAt, entries[i].key)
		}
	}
	s.retrieverCache[projectID] = r
	s.retrieverCacheAt[projectID] = time.Now()
	s.retrieverCacheMu.Unlock()

	return r
}

type ADKAnalysisRequest struct {
	DefectID         uint     `json:"defectId"`
	AgentTypes       []string `json:"agentTypes"`
	UserID           uint     `json:"userId,omitempty"`
	AppName          string   `json:"appName,omitempty"`
	SkipStatusUpdate bool     `json:"skipStatusUpdate,omitempty"`
}

type ADKAnalysisResult struct {
	ReportCode            string               `json:"reportCode"`
	DefectID              uint                 `json:"defectId"`
	AgentType             string               `json:"agentType"`
	Status                string               `json:"status"`
	Provider              string               `json:"provider,omitempty"`
	ModelName             string               `json:"modelName,omitempty"`
	PromptVersion         string               `json:"promptVersion,omitempty"`
	FallbackUsed          bool                 `json:"fallbackUsed,omitempty"`
	Analysis              json.RawMessage      `json:"analysis"`
	Solution              json.RawMessage      `json:"solution"`
	Duration              int64                `json:"durationMs"`
	PromptTokens          int                  `json:"promptTokens,omitempty"`
	CompletionTokens      int                  `json:"completionTokens,omitempty"`
	TotalTokens           int                  `json:"totalTokens,omitempty"`
	RiskSummary           string               `json:"riskSummary,omitempty"`
	ValidationSuggestions []string             `json:"validationSuggestions,omitempty"`
	RepairTriggered       bool                 `json:"repairTriggered,omitempty"`
	Repaired              bool                 `json:"repaired,omitempty"`
	RepairReason          string               `json:"repairReason,omitempty"`
	Error                 string               `json:"error,omitempty"`
	SubResults            []*ADKAnalysisResult `json:"subResults,omitempty"`
}

type streamEventItem struct {
	event *session.Event
	err   error
}

type streamPostProcessContext struct {
	defect           bugmodel.Defect
	config           bugmodel.ProjectAIConfig
	agentType        string
	skipStatusUpdate bool
	relatedFiles     []string
	codeContext      string
	promptText       string
	startTime        time.Time
	repo             *git.Repository
	pipelineCancel   context.CancelFunc
	sessionDeleteReq *session.DeleteRequest
	sessionID        string
}

func (s *ADKAnalysisService) PerformAnalysis(ctx context.Context, req ADKAnalysisRequest) (*ADKAnalysisResult, error) {
	startTime := time.Now()
	fmt.Printf("[ADK_DEBUG] PerformAnalysis called: defect=%d agentTypes=%v\n", req.DefectID, req.AgentTypes)

	if req.AppName == "" {
		req.AppName = "bug-agent"
	}

	var defect bugmodel.Defect
	if err := s.db.Preload("Iteration").Preload("Assignee").Preload("Reporter").First(&defect, req.DefectID).Error; err != nil {
		return nil, fmt.Errorf("defect not found: %w", err)
	}

	if len(req.AgentTypes) == 0 {
		req.AgentTypes = []string{"frontend"}
	}

	aiConfigs, err := s.listUsableAIConfigsCached(defect.Iteration.ProjectID)
	if err != nil || len(aiConfigs) == 0 {
		logger.Infof("[ADKAnalysis] fallback triggered in PerformAnalysis: project=%d err=%v configs=%d", defect.Iteration.ProjectID, err, len(aiConfigs))
		result, fallbackErr := s.fallbackAnalysis(defect, req.AgentTypes, startTime, fmt.Sprintf("no AI config: %v", err), req.SkipStatusUpdate)
		sse.Notifier.NotifyAnalysisFailed(defect.ID, "no usable AI config; fallback report created for manual confirmation")
		return result, fallbackErr
	}
	logger.Infof("[ADKAnalysis] AI configs found: project=%d configs=%d", defect.Iteration.ProjectID, len(aiConfigs))

	if !req.SkipStatusUpdate {
		var currentStatus string
		s.db.Model(&bugmodel.Defect{}).Select("status").Where("id = ?", defect.ID).Scan(&currentStatus)
		if currentStatus == bugmodel.DefectStatusPendingAssign {
			s.updateDefectStatus(defect.ID, bugmodel.DefectStatusPendingAnalysis)
		}
		s.updateDefectStatus(defect.ID, bugmodel.DefectStatusAnalyzing)
	}

	statusRolledBack := false
	defer func() {
		if !statusRolledBack && !req.SkipStatusUpdate {
			var currentStatus string
			s.db.Model(&bugmodel.Defect{}).Select("status").Where("id = ?", defect.ID).Scan(&currentStatus)
			if currentStatus == bugmodel.DefectStatusAnalyzing {
				s.updateDefectStatus(defect.ID, bugmodel.DefectStatusPendingAssign)
				logger.Warnf("[ADKAnalysis] safety rollback: defect %d stuck in analyzing", defect.ID)
			}
		}
	}()

	sse.Notifier.NotifyAnalysisStarted(defect.ID, req.AgentTypes)

	ctx, cancel := context.WithCancel(ctx)
	s.runningMu.Lock()
	s.runningCtxs[defect.ID] = cancel
	s.runningMu.Unlock()
	defer func() {
		s.runningMu.Lock()
		delete(s.runningCtxs, defect.ID)
		s.runningMu.Unlock()
		cancel()
	}()

	attachments := s.getAttachmentsInfo(defect.ID)
	memoryCtx := s.buildMemoryContext(defect.Iteration.ProjectID)

	var results []*ADKAnalysisResult
	for _, agentType := range req.AgentTypes {
		fmt.Printf("[ADK_DEBUG] Analyzing with agent=%s\n", agentType)
		result, err := func() (*ADKAnalysisResult, error) {
			codeContext, relatedFiles, repo, repoCtx := s.getCodeContext(ctx, defect, agentType)
			if repo != nil {
				defer repo.Cleanup()
			}
			fmt.Printf("[ADK_DEBUG] PerformAnalysis codeContext: agent=%s len=%d relatedFiles=%d\n", agentType, len(codeContext), len(relatedFiles))
			logger.Infof("[ADKAnalysis] codeContext result: agent=%s len=%d relatedFiles=%d", agentType, len(codeContext), len(relatedFiles))
			return s.analyzeWithFallback(ctx, defect, agentType, aiConfigs, codeContext, relatedFiles, attachments, memoryCtx, startTime, repo, repoCtx)
		}()
		if err != nil {
			if errors.Is(err, context.Canceled) {
				statusRolledBack = true
				if !req.SkipStatusUpdate {
					s.markAnalysisCancelled(defect.ID)
				}
				cfg := aiConfigs[0]
				sid := fmt.Sprintf("defect_%d_%d", defect.ID, startTime.UnixMilli())
				s.saveCancelledReportFromNonStream("", 0, 0, 0, defect, cfg, agentType, startTime, sid)
				sse.Notifier.NotifyAnalysisCancelled(defect.ID)
				return nil, err
			}
			logger.Errorf("[ADKAnalysis] agent %s failed: %v", agentType, err)
			fbResult, fbErr := s.fallbackAnalysis(defect, []string{agentType}, startTime, err.Error(), req.SkipStatusUpdate)
			if fbErr != nil {
				return nil, fbErr
			}
			results = append(results, fbResult)
		} else {
			results = append(results, result)
			s.publishAgentComment(defect, result)
		}
	}

	if len(results) == 0 {
		statusRolledBack = true
		if !req.SkipStatusUpdate {
			s.updateDefectStatus(defect.ID, bugmodel.DefectStatusPendingAssign)
		}
		sse.Notifier.NotifyAnalysisFailed(defect.ID, "all agent types failed")
		return nil, fmt.Errorf("all agent types failed")
	}

	if !hasActionableAnalysisResult(results) {
		statusRolledBack = true
		if !req.SkipStatusUpdate {
			s.db.Model(&bugmodel.Defect{}).
				Where("id = ? AND status = ?", defect.ID, bugmodel.DefectStatusAnalyzing).
				Update("status", bugmodel.DefectStatusPendingAnalysis)
		}
		sse.Notifier.NotifyAnalysisFailed(defect.ID, "analysis produced fallback report only; manual confirmation required")
		primary := results[0]
		if len(results) > 1 {
			primary.SubResults = results[1:]
		}
		return primary, nil
	}

	statusRolledBack = true
	if !req.SkipStatusUpdate {
		s.updateDefectStatus(defect.ID, bugmodel.DefectStatusPendingFix)
	}

	sse.Notifier.NotifyAnalysisCompleted(defect.ID, results[0].ReportCode)

	primary := results[0]
	if len(results) > 1 {
		primary.SubResults = results[1:]
	}

	asyncx.Go(func() {
		defer func() {
			if r := recover(); r != nil {
				logger.Infof("[ADKAnalysis] Memory extraction panic: %v", r)
			}
		}()
		s.extractMemoriesFromAnalysis(defect.ID, primary)
	})

	return primary, nil
}

func hasActionableAnalysisResult(results []*ADKAnalysisResult) bool {
	for _, result := range results {
		if result != nil && result.Status == bugmodel.AnalysisStatusCompleted {
			return true
		}
	}
	return false
}

func adkAnalysisHasFixSteps(raw json.RawMessage) bool {
	if len(raw) == 0 || strings.TrimSpace(string(raw)) == "null" {
		return false
	}
	var payload map[string]interface{}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return false
	}
	if steps, ok := payload["steps"].([]interface{}); ok && hasFileLevelFixStep(steps) {
		return true
	}
	solution, ok := payload["solution"].(map[string]interface{})
	if !ok {
		return false
	}
	steps, ok := solution["steps"].([]interface{})
	return ok && hasFileLevelFixStep(steps)
}

func hasFileLevelFixStep(steps []interface{}) bool {
	for _, step := range steps {
		stepMap, ok := step.(map[string]interface{})
		if !ok {
			continue
		}
		if looksLikeAnalysisRepoFilePath(util.GetStringField(stepMap, "filePath")) {
			return true
		}
		if looksLikeAnalysisRepoFilePath(util.GetStringField(stepMap, "path")) {
			return true
		}
		if looksLikeAnalysisRepoFilePath(util.GetStringField(stepMap, "targetFile")) {
			return true
		}
	}
	return false
}

func looksLikeAnalysisRepoFilePath(value string) bool {
	value = strings.TrimSpace(value)
	if value == "" || strings.Contains(value, "\n") || strings.Contains(value, "\r") {
		return false
	}
	if strings.ContainsAny(value, "\"'`{}()") || strings.Contains(value, " ") {
		return false
	}
	return filepath.Ext(value) != ""
}

func (s *ADKAnalysisService) analyzeWithFallback(
	ctx context.Context,
	defect bugmodel.Defect,
	agentType string,
	configs []bugmodel.ProjectAIConfig,
	codeContext string,
	relatedFiles []string,
	attachments []map[string]string,
	memoryCtx string,
	startTime time.Time,
	repo *git.Repository,
	repoCtx RepositoryContext,
) (*ADKAnalysisResult, error) {
	var attemptErrors []string
	for index, config := range configs {
		attemptStart := time.Now()
		if err := service.HydrateProjectAIConfig(&config); err != nil {
			attemptErrors = append(attemptErrors, fmt.Sprintf("%s/%s: %v", config.Provider, config.ModelName, err))
			logger.Infof("[ADKAnalysis] config hydration failed: provider=%s model=%s err=%v", config.Provider, config.ModelName, err)
			// 配置不可用，记录失败的 AITokenUsage
			service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
				ProjectID:       defect.Iteration.ProjectID,
				IterationID:     &defect.IterationID,
				DefectID:        defect.ID,
				ConsumptionType: "analysis",
				SourceID:        0,
				AttemptIndex:    index,
				IsFinalAttempt:  index == len(configs)-1,
				Provider:        config.Provider,
				ModelName:       config.ModelName,
				DurationMs:      time.Since(attemptStart).Milliseconds(),
			})
			continue
		}

		llm, err := NewLLM(ctx, &config)
		if err != nil {
			attemptErrors = append(attemptErrors, fmt.Sprintf("%s/%s: %v", config.Provider, config.ModelName, err))
			// LLM 创建失败，记录失败的 AITokenUsage
			service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
				ProjectID:       defect.Iteration.ProjectID,
				IterationID:     &defect.IterationID,
				DefectID:        defect.ID,
				ConsumptionType: "analysis",
				SourceID:        0,
				AttemptIndex:    index,
				IsFinalAttempt:  index == len(configs)-1,
				Provider:        config.Provider,
				ModelName:       config.ModelName,
				DurationMs:      time.Since(attemptStart).Milliseconds(),
			})
			continue
		}

		result, err := s.analyzeWithAgent(ctx, defect, agentType, llm, config, index, index > 0, codeContext, relatedFiles, attachments, memoryCtx, startTime, repo, repoCtx)
		if err == nil {
			fmt.Printf("[ADK_DEBUG] analyzeWithAgent SUCCEEDED: agent=%s provider=%s model=%s\n", agentType, config.Provider, config.ModelName)
			logger.Infof("[ADKAnalysis] analyzeWithAgent succeeded: agent=%s provider=%s model=%s", agentType, config.Provider, config.ModelName)
			// 成功时在 analyzeWithAgent 内部已写入 AITokenUsage
			return result, nil
		}
		attemptErrors = append(attemptErrors, fmt.Sprintf("%s/%s: %v", config.Provider, config.ModelName, err))
		fmt.Printf("[ADK_DEBUG] analyzeWithAgent FAILED: agent=%s provider=%s model=%s err=%v\n", agentType, config.Provider, config.ModelName, err)
		logger.Infof("[ADKAnalysis] analyzeWithAgent failed: agent=%s provider=%s model=%s err=%v", agentType, config.Provider, config.ModelName, err)
		// 失败时记录 AITokenUsage
		service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
			ProjectID:       defect.Iteration.ProjectID,
			IterationID:     &defect.IterationID,
			DefectID:        defect.ID,
			ConsumptionType: "analysis",
			SourceID:        0,
			AttemptIndex:    index,
			IsFinalAttempt:  index == len(configs)-1,
			Provider:        config.Provider,
			ModelName:       config.ModelName,
			DurationMs:      time.Since(attemptStart).Milliseconds(),
		})
	}

	joinedErr := fmt.Errorf("all models failed: %s", strings.Join(attemptErrors, "; "))
	if ctx.Err() != nil {
		return nil, fmt.Errorf("all models failed: %s: %w", strings.Join(attemptErrors, "; "), ctx.Err())
	}
	return nil, joinedErr
}

func (s *ADKAnalysisService) analyzeWithAgent(
	ctx context.Context,
	defect bugmodel.Defect,
	agentType string,
	llm adkmodel.LLM,
	config bugmodel.ProjectAIConfig,
	attemptIndex int,
	fallbackUsed bool,
	codeContext string,
	relatedFiles []string,
	attachments []map[string]string,
	memoryCtx string,
	startTime time.Time,
	repo *git.Repository,
	repoCtx RepositoryContext,
) (*ADKAnalysisResult, error) {
	attemptStart := time.Now()

	userID := fmt.Sprintf("user_%d", defect.ReporterID)
	sessionID := fmt.Sprintf("defect_%d_%d", defect.ID, time.Now().UnixMilli())

	_, err := s.sessionSvc.Create(ctx, &session.CreateRequest{
		AppName:   "bug-agent",
		UserID:    userID,
		SessionID: sessionID,
	})
	if err != nil {
		return nil, fmt.Errorf("session create: %w", err)
	}
	defer s.sessionSvc.Delete(ctx, &session.DeleteRequest{
		AppName: "bug-agent", UserID: userID, SessionID: sessionID,
	})

	explorerCtx := ExplorerContext{
		Repository: repoCtx,
		SearchFn: func(ctx interface{}, query string) ([]ai.SearchHit, error) {
			if repo == nil {
				return nil, fmt.Errorf("search_code: no repository available")
			}
			files, err := repo.SearchFiles(query, 20)
			if err != nil {
				return nil, err
			}
			var hits []ai.SearchHit
			for _, f := range files {
				hits = append(hits, ai.SearchHit{FilePath: f})
			}
			return hits, nil
		},
		ReadFn: func(ctx interface{}, filePath string) (string, error) {
			if repo == nil {
				return "", fmt.Errorf("read_file: no repository available")
			}
			return repo.ReadFile(filePath)
		},
		HandlerFn: s.buildHandlerFnWithRepo(repo),
		ListFn: func(ctx interface{}, path string) ([]ai.DirEntry, error) {
			if repo == nil {
				return nil, fmt.Errorf("list_directory: no repository available")
			}
			entries, err := repo.ListDir(path)
			if err != nil {
				return nil, err
			}
			result := make([]ai.DirEntry, len(entries))
			for i, e := range entries {
				result[i] = ai.DirEntry{Name: e.Name, Type: e.Type}
			}
			return result, nil
		},
	}

	agentTools := DefaultToolRegistry().ResolveWithPlugins(agentType, explorerCtx, defect.Iteration.ProjectID)

	plannerEvidence, plannerFiles := s.executePlannerPhase(ctx, llm, explorerCtx, defect, codeContext, relatedFiles, attachments)
	if plannerEvidence != "" {
		codeContext += "\n\n## Planner 探索证据\n" + plannerEvidence
		relatedFiles = mergeFileLists(relatedFiles, plannerFiles)
	}

	callbacks := []Callback{
		{BeforeModel: MemoryInjectionCallback(s.db, defect.Iteration.ProjectID)},
		{AfterModel: MemoryExtractionCallback(s.db, defect.Iteration.ProjectID, defect.ReporterID)},
		{BeforeTool: ToolPermissionBeforeToolCallback(DefaultToolPermissionMatrix(), agentType)},
	}

	pipelineCfg := AnalysisPipelineConfig{
		LLM:         llm,
		SessionSvc:  s.sessionSvc,
		ExplorerCtx: explorerCtx,
		MemoryCtx:   memoryCtx,
		AgentTypes:  []string{agentType},
		AgentTools:  agentTools,
		AppName:     "bug-agent",
		MCPServers:  s.mcpServers,
		Callbacks:   callbacks,
	}

	r, err := NewAnalysisPipeline(pipelineCfg)
	if err != nil {
		return nil, fmt.Errorf("NewAnalysisPipeline: %w", err)
	}

	defectSummary := s.buildDefectSummary(defect, codeContext, relatedFiles, attachments)
	userMsg := &genai.Content{
		Role:  genai.RoleUser,
		Parts: []*genai.Part{{Text: defectSummary}},
	}

	events := r.Run(ctx, userID, sessionID, userMsg, agent.RunConfig{})

	if s.rollout != nil {
		s.rollout.Record(sessionID, defect.ID, "analysis_started", map[string]interface{}{"agentTypes": agentType})
	}

	collected, err := CollectEvents(events)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			var partialText string
			var partialTokens, partialPrompt, partialCompletion int
			for _, evt := range collected {
				collectEventText(evt, &partialText, &partialTokens, &partialPrompt, &partialCompletion)
			}
			s.saveCancelledReportFromNonStream(partialText, partialTokens, partialPrompt, partialCompletion, defect, config, agentType, startTime, sessionID)
			sse.Notifier.NotifyAnalysisCancelled(defect.ID)
		} else {
			if s.rollout != nil {
				s.rollout.MarkFailed(sessionID)
			}
		}
		return nil, fmt.Errorf("collect events: %w", err)
	}

	var fullText string
	var totalTokens int
	var promptTokens int
	var completionTokens int
	for _, evt := range collected {
		if evt.Content != nil {
			for _, part := range evt.Content.Parts {
				if part.Text != "" {
					fullText += part.Text
				}
			}
		}
		if evt.UsageMetadata != nil {
			mergeUsageMetadata(evt, &totalTokens, &promptTokens, &completionTokens)
		}
	}
	analysisText := collectAnalysisEventText(collected, agentType)
	if strings.TrimSpace(analysisText) == "" {
		analysisText = fullText
	}

	var analysisJSON, solutionJSON json.RawMessage
	var rootCause, riskLevel string
	var riskSummary string
	var affectedFiles []string
	var validationSuggestions []string
	var repairTriggered, repaired bool
	var repairReason string

	if rawJSON, err := extractFinalAnalysisJSONObjectFromText(analysisText); err == nil {
		var parsed map[string]interface{}
		if err := json.Unmarshal([]byte(rawJSON), &parsed); err == nil {
			normalizeAnalysisFieldNames(parsed)
			normalized, telemetry := s.normalizeAnalysisByRepoEvidence(ctx, parsed, relatedFiles, codeContext, config)
			if telemetry.Repaired {
				logger.Infof("[ADKAnalysis] repaired by evidence: defect=%d agent=%s", defect.ID, agentType)
			}
			repairTriggered = telemetry.RepairTriggered
			repaired = telemetry.Repaired
			repairReason = telemetry.RepairReason

			rootCause = util.GetStringField(normalized, "rootCause")
			riskLevel = util.GetStringField(normalized, "riskLevel")
			affectedFiles = util.GetStringSliceField(normalized["affectedFiles"])
			validationSuggestions = util.GetStringSliceField(normalized["validationSuggestions"])

			riskSummary = util.GetStringField(normalized, "riskSummary")
			if riskSummary == "" {
				riskSummary = buildRiskSummary(rootCause, riskLevel)
			}
			normalized["riskSummary"] = riskSummary
			normalized["validationSuggestions"] = buildValidationSuggestions(affectedFiles, validationSuggestions)
			ensureSolution(normalized)

			aj, err := json.Marshal(normalized)
			if err == nil {
				analysisJSON = aj
			}
			if sol, ok := normalized["solution"]; ok {
				sj, err := json.Marshal(sol)
				if err == nil {
					solutionJSON = sj
				}
			}
		}
	}

	if analysisJSON == nil {
		logger.Warnf("[ADKAnalysis] failed to extract JSON from AI response, using fallback: defect=%d", defect.ID)
		validationSuggestions = buildValidationSuggestions(nil, nil)
		extractedFiles := extractFilePathsFromText(analysisText)
		fallbackPayload := map[string]interface{}{
			"rawResponse":           analysisText,
			"affectedFiles":         extractedFiles,
			"riskSummary":           buildRiskSummary("", ""),
			"validationSuggestions": validationSuggestions,
		}
		bytes, err := json.Marshal(fallbackPayload)
		if err == nil {
			analysisJSON = bytes
		}
	}

	if riskSummary == "" {
		riskSummary = buildRiskSummary(rootCause, riskLevel)
	}
	validationSuggestions = buildValidationSuggestions(affectedFiles, validationSuggestions)

	reportCode := generateADKReportCode()
	reportStatus := bugmodel.AnalysisStatusCompleted
	if !adkAnalysisHasFixSteps(analysisJSON) && !adkAnalysisHasFixSteps(solutionJSON) {
		reportStatus = "completed_fallback"
	}

	report := bugmodel.AnalysisReport{
		ReportCode:            reportCode,
		DefectID:              defect.ID,
		AgentType:             agentType,
		Status:                reportStatus,
		RiskSummary:           util.SanitizeUTF8(riskSummary),
		ValidationSuggestions: util.MarshalStringSlice(validationSuggestions),
		Analysis:              string(util.SanitizeJSONUTF8(analysisJSON)),
		Solution:              string(util.SanitizeJSONUTF8(solutionJSON)),
	}
	if err := s.db.Create(&report).Error; err != nil {
		logger.Errorf("[ADKAnalysis] save report: %v", err)
	}

	if totalTokens <= 0 {
		estimatedUsage := service.EstimateTokenUsageFromText(defectSummary, fullText)
		promptTokens = estimatedUsage.PromptTokens
		completionTokens = estimatedUsage.CompletionTokens
		totalTokens = estimatedUsage.TotalTokens
	}

	// 记录成功的 AITokenUsage
	estimatedCost := service.EstimateAICostUSD(config.Provider, config.ModelName, ai.Usage{
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		TotalTokens:      totalTokens,
	})
	service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
		ProjectID:        defect.Iteration.ProjectID,
		IterationID:      &defect.IterationID,
		DefectID:         defect.ID,
		ConsumptionType:  "analysis",
		SourceID:         report.ID,
		AttemptIndex:     attemptIndex,
		IsFinalAttempt:   true,
		Provider:         config.Provider,
		ModelName:        config.ModelName,
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		TotalTokens:      totalTokens,
		EstimatedCostUSD: estimatedCost,
		DurationMs:       time.Since(attemptStart).Milliseconds(),
	})

	if s.rollout != nil {
		s.rollout.MarkCompleted(sessionID)
	}

	return &ADKAnalysisResult{
		ReportCode:            reportCode,
		DefectID:              defect.ID,
		AgentType:             agentType,
		Status:                reportStatus,
		Provider:              config.Provider,
		ModelName:             config.ModelName,
		FallbackUsed:          fallbackUsed,
		Analysis:              analysisJSON,
		Solution:              solutionJSON,
		Duration:              time.Since(attemptStart).Milliseconds(),
		RiskSummary:           riskSummary,
		ValidationSuggestions: validationSuggestions,
		RepairTriggered:       repairTriggered,
		Repaired:              repaired,
		RepairReason:          repairReason,
	}, nil
}

func (s *ADKAnalysisService) PerformAnalysisStream(ctx context.Context, req ADKAnalysisRequest) (iter.Seq2[*session.Event, error], error) {
	if req.AppName == "" {
		req.AppName = "bug-agent"
	}
	fmt.Printf("[ADK_DEBUG] PerformAnalysisStream called: defect=%d agentTypes=%v\n", req.DefectID, req.AgentTypes)

	var defect bugmodel.Defect
	if err := s.db.Preload("Iteration").Preload("Reporter").First(&defect, req.DefectID).Error; err != nil {
		return nil, fmt.Errorf("defect not found: %w", err)
	}

	if len(req.AgentTypes) == 0 {
		req.AgentTypes = []string{"frontend"}
	}
	if len(req.AgentTypes) > 1 {
		return nil, fmt.Errorf("stream analysis supports exactly one agent type; use non-stream analysis for multi-agent requests")
	}

	aiConfigs, err := s.listUsableAIConfigsCached(defect.Iteration.ProjectID)
	if err != nil || len(aiConfigs) == 0 {
		logger.Infof("[ADKAnalysisStream] no AI configs, falling back: project=%d err=%v configs=%d", defect.Iteration.ProjectID, err, len(aiConfigs))
		startTime := time.Now()
		fbResult, fbErr := s.fallbackAnalysis(defect, req.AgentTypes, startTime, fmt.Sprintf("no AI config: %v", err), req.SkipStatusUpdate)
		if fbErr != nil {
			return nil, fbErr
		}
		sse.Notifier.NotifyAnalysisFailed(defect.ID, "no usable AI config; fallback report created for manual confirmation")
		fbJSON, _ := json.Marshal(fbResult)
		return func(yield func(*session.Event, error) bool) {
			evt := &session.Event{}
			evt.Content = &genai.Content{
				Role:  genai.RoleModel,
				Parts: []*genai.Part{{Text: string(fbJSON)}},
			}
			yield(evt, nil)
		}, nil
	}
	logger.Infof("[ADKAnalysisStream] AI configs found: project=%d configs=%d", defect.Iteration.ProjectID, len(aiConfigs))

	var usableConfig *bugmodel.ProjectAIConfig
	for i := range aiConfigs {
		if err := service.HydrateProjectAIConfig(&aiConfigs[i]); err != nil {
			continue
		}
		usableConfig = &aiConfigs[i]
		break
	}
	if usableConfig == nil {
		return nil, fmt.Errorf("no usable AI config after hydration")
	}

	llm, err := NewLLM(ctx, usableConfig)
	if err != nil {
		return nil, fmt.Errorf("LLM init: %w", err)
	}

	if !req.SkipStatusUpdate {
		var currentStatus string
		s.db.Model(&bugmodel.Defect{}).Select("status").Where("id = ?", defect.ID).Scan(&currentStatus)
		if currentStatus == bugmodel.DefectStatusPendingAssign {
			s.updateDefectStatus(defect.ID, bugmodel.DefectStatusPendingAnalysis)
		}
		s.updateDefectStatus(defect.ID, bugmodel.DefectStatusAnalyzing)
	}

	sse.Notifier.NotifyAnalysisStarted(defect.ID, req.AgentTypes)

	ctx, streamCancel := context.WithCancel(ctx)
	s.runningMu.Lock()
	s.runningCtxs[defect.ID] = streamCancel
	s.runningMu.Unlock()

	startTime := time.Now()

	codeContext, relatedFiles, repo, repoCtx := s.getCodeContext(ctx, defect, firstAgentType(req.AgentTypes))
	logger.Infof("[ADKAnalysisStream] codeContext result: len=%d relatedFiles=%d", len(codeContext), len(relatedFiles))
	attachments := s.getAttachmentsInfo(defect.ID)
	memoryCtx := s.buildMemoryContext(defect.Iteration.ProjectID)

	userID := fmt.Sprintf("user_%d", req.UserID)
	sessionID := fmt.Sprintf("defect_%d_%d", req.DefectID, time.Now().UnixMilli())

	_, err = s.sessionSvc.Create(ctx, &session.CreateRequest{
		AppName:   req.AppName,
		UserID:    userID,
		SessionID: sessionID,
	})
	if err != nil {
		s.cleanupStreamStartFailure(defect.ID, repo, streamCancel, nil)
		if !req.SkipStatusUpdate {
			s.updateDefectStatus(defect.ID, bugmodel.DefectStatusPendingAssign)
		}
		return nil, fmt.Errorf("session create: %w", err)
	}

	sessionDeleteReq := &session.DeleteRequest{
		AppName: req.AppName, UserID: userID, SessionID: sessionID,
	}

	explorerCtx := ExplorerContext{
		Repository: repoCtx,
		SearchFn: func(ctx interface{}, query string) ([]ai.SearchHit, error) {
			if repo == nil {
				return nil, fmt.Errorf("search_code: no repository available")
			}
			files, err := repo.SearchFiles(query, 20)
			if err != nil {
				return nil, err
			}
			var hits []ai.SearchHit
			for _, f := range files {
				hits = append(hits, ai.SearchHit{FilePath: f})
			}
			return hits, nil
		},
		ReadFn: func(ctx interface{}, filePath string) (string, error) {
			if repo == nil {
				return "", fmt.Errorf("read_file: no repository available")
			}
			return repo.ReadFile(filePath)
		},
		HandlerFn: s.buildHandlerFnWithRepo(repo),
		ListFn: func(ctx interface{}, path string) ([]ai.DirEntry, error) {
			if repo == nil {
				return nil, fmt.Errorf("list_directory: no repository available")
			}
			entries, err := repo.ListDir(path)
			if err != nil {
				return nil, err
			}
			result := make([]ai.DirEntry, len(entries))
			for i, e := range entries {
				result[i] = ai.DirEntry{Name: e.Name, Type: e.Type}
			}
			return result, nil
		},
	}

	pipelineCfg := AnalysisPipelineConfig{
		LLM:         llm,
		SessionSvc:  s.sessionSvc,
		ExplorerCtx: explorerCtx,
		MemoryCtx:   memoryCtx,
		AgentTypes:  req.AgentTypes,
		AgentTools:  DefaultToolRegistry().ResolveWithPlugins(req.AgentTypes[0], explorerCtx, defect.Iteration.ProjectID),
		AppName:     req.AppName,
		MCPServers:  s.mcpServers,
		Callbacks: []Callback{
			{BeforeModel: MemoryInjectionCallback(s.db, defect.Iteration.ProjectID)},
			{AfterModel: MemoryExtractionCallback(s.db, defect.Iteration.ProjectID, defect.ReporterID)},
			{BeforeTool: ToolPermissionBeforeToolCallback(DefaultToolPermissionMatrix(), req.AgentTypes[0])},
		},
	}

	sse.Notifier.NotifyDefectStatusChanged(defect.ID, "analyzing", "analyzing")

	plannerEvidence, plannerFiles := s.executePlannerPhase(ctx, llm, explorerCtx, defect, codeContext, relatedFiles, nil)
	if plannerEvidence != "" {
		codeContext += "\n\n## Planner 探索证据\n" + plannerEvidence
		relatedFiles = mergeFileLists(relatedFiles, plannerFiles)
	}

	r, err := NewAnalysisPipeline(pipelineCfg)
	if err != nil {
		s.cleanupStreamStartFailure(defect.ID, repo, streamCancel, sessionDeleteReq)
		if !req.SkipStatusUpdate {
			s.updateDefectStatus(defect.ID, bugmodel.DefectStatusPendingAssign)
		}
		return nil, fmt.Errorf("NewAnalysisPipeline: %w", err)
	}

	defectSummary := s.buildDefectSummary(defect, codeContext, relatedFiles, attachments)
	userMsg := &genai.Content{
		Role:  genai.RoleUser,
		Parts: []*genai.Part{{Text: defectSummary}},
	}

	pipelineCtx, pipelineCancel := context.WithTimeout(context.WithoutCancel(ctx), 10*time.Minute)
	rawEvents := r.Run(pipelineCtx, userID, sessionID, userMsg, agent.RunConfig{})

	ppCtx := streamPostProcessContext{
		defect:           defect,
		config:           *usableConfig,
		agentType:        req.AgentTypes[0],
		skipStatusUpdate: req.SkipStatusUpdate,
		relatedFiles:     relatedFiles,
		codeContext:      codeContext,
		promptText:       defectSummary,
		startTime:        startTime,
		repo:             repo,
		pipelineCancel:   pipelineCancel,
		sessionDeleteReq: sessionDeleteReq,
		sessionID:        sessionID,
	}

	return s.wrapStreamWithPostProcessing(rawEvents, ppCtx), nil
}

func (s *ADKAnalysisService) cleanupStreamStartFailure(
	defectID uint,
	repo *git.Repository,
	cancel context.CancelFunc,
	sessionDeleteReq *session.DeleteRequest,
) {
	s.runningMu.Lock()
	delete(s.runningCtxs, defectID)
	s.runningMu.Unlock()

	if cancel != nil {
		cancel()
	}
	if sessionDeleteReq != nil {
		s.sessionSvc.Delete(context.Background(), sessionDeleteReq)
	}
	if repo != nil {
		if err := repo.Cleanup(); err != nil {
			logger.Warnf("[ADKAnalysis] stream start repo cleanup failed: %v", err)
		}
	}
}

func collectEventText(event *session.Event, fullText *string, totalTokens, promptTokens, completionTokens *int) {
	if event == nil {
		return
	}
	if event.Content != nil {
		for _, part := range event.Content.Parts {
			if part.Text != "" {
				*fullText += part.Text
			}
		}
	}
	if event.UsageMetadata != nil {
		mergeUsageMetadata(event, totalTokens, promptTokens, completionTokens)
	}
}

func collectEventTextWithAnalysis(event *session.Event, fullText, analysisText *string, agentType string, totalTokens, promptTokens, completionTokens *int) {
	if event == nil {
		return
	}
	var eventText string
	if event.Content != nil {
		for _, part := range event.Content.Parts {
			if part.Text != "" {
				eventText += part.Text
			}
		}
	}
	*fullText += eventText
	if eventMatchesAnalysisAuthor(event.Author, agentType) {
		*analysisText += eventText
	}
	if event.UsageMetadata != nil {
		mergeUsageMetadata(event, totalTokens, promptTokens, completionTokens)
	}
}

func mergeUsageMetadata(event *session.Event, totalTokens, promptTokens, completionTokens *int) {
	if event == nil || event.UsageMetadata == nil {
		return
	}
	*totalTokens = maxInt(*totalTokens, int(event.UsageMetadata.TotalTokenCount))
	*promptTokens = maxInt(*promptTokens, int(event.UsageMetadata.PromptTokenCount))
	*completionTokens = maxInt(*completionTokens, int(event.UsageMetadata.CandidatesTokenCount))
}

func maxInt(a, b int) int {
	if b > a {
		return b
	}
	return a
}

func (s *ADKAnalysisService) wrapStreamWithPostProcessing(
	events iter.Seq2[*session.Event, error],
	ppCtx streamPostProcessContext,
) iter.Seq2[*session.Event, error] {
	ch := make(chan streamEventItem, 128)

	go func() {
		defer close(ch)
		for event, err := range events {
			ch <- streamEventItem{event: event, err: err}
			if err != nil {
				return
			}
		}
	}()

	return func(yield func(*session.Event, error) bool) {
		var fullText string
		var analysisText string
		var totalTokens, promptTokens, completionTokens int

		for item := range ch {
			if item.err != nil {
				if errors.Is(item.err, context.Canceled) {
					s.saveCancelledReport(fullText, totalTokens, promptTokens, completionTokens, ppCtx)
					sse.Notifier.NotifyAnalysisCancelled(ppCtx.defect.ID)
				} else {
					if !ppCtx.skipStatusUpdate {
						s.updateDefectStatus(ppCtx.defect.ID, bugmodel.DefectStatusPendingAssign)
					}
					sse.Notifier.NotifyAnalysisFailed(ppCtx.defect.ID, item.err.Error())
				}
				yield(item.event, item.err)
				s.cleanupStream(ppCtx)
				return
			}

			collectEventTextWithAnalysis(item.event, &fullText, &analysisText, ppCtx.agentType, &totalTokens, &promptTokens, &completionTokens)

			if !yield(item.event, nil) {
				go s.drainAndPostProcess(ch, fullText, analysisText, totalTokens, promptTokens, completionTokens, ppCtx)
				return
			}
		}

		s.doStreamPostProcessing(fullText, analysisText, totalTokens, promptTokens, completionTokens, ppCtx)
		s.cleanupStream(ppCtx)
	}
}

func (s *ADKAnalysisService) drainAndPostProcess(
	ch chan streamEventItem,
	fullText string,
	analysisText string,
	totalTokens, promptTokens, completionTokens int,
	ppCtx streamPostProcessContext,
) {
	defer s.cleanupStream(ppCtx)

	for item := range ch {
		if item.err != nil {
			if errors.Is(item.err, context.Canceled) {
				s.saveCancelledReport(fullText, totalTokens, promptTokens, completionTokens, ppCtx)
				sse.Notifier.NotifyAnalysisCancelled(ppCtx.defect.ID)
			} else {
				if !ppCtx.skipStatusUpdate {
					s.updateDefectStatus(ppCtx.defect.ID, bugmodel.DefectStatusPendingAssign)
				}
				sse.Notifier.NotifyAnalysisFailed(ppCtx.defect.ID, item.err.Error())
			}
			return
		}
		collectEventTextWithAnalysis(item.event, &fullText, &analysisText, ppCtx.agentType, &totalTokens, &promptTokens, &completionTokens)
	}

	s.doStreamPostProcessing(fullText, analysisText, totalTokens, promptTokens, completionTokens, ppCtx)
}

func (s *ADKAnalysisService) saveCancelledReport(
	fullText string,
	totalTokens, promptTokens, completionTokens int,
	ppCtx streamPostProcessContext,
) {
	reportCode := generateADKReportCode()

	var analysisJSON json.RawMessage
	if fullText != "" {
		fallbackPayload := map[string]interface{}{
			"rawResponse":           fullText,
			"riskSummary":           "分析已取消",
			"validationSuggestions": []string{"分析被用户取消，请重新触发分析"},
		}
		if bytes, err := json.Marshal(fallbackPayload); err == nil {
			analysisJSON = bytes
		}
	}
	if analysisJSON == nil {
		analysisJSON = []byte(`{"riskSummary":"分析已取消"}`)
	}

	report := bugmodel.AnalysisReport{
		ReportCode:            reportCode,
		DefectID:              ppCtx.defect.ID,
		AgentType:             ppCtx.agentType,
		Status:                "cancelled",
		RiskSummary:           "分析已取消",
		ValidationSuggestions: util.MarshalStringSlice([]string{"分析被用户取消，请重新触发分析"}),
		Analysis:              string(util.SanitizeJSONUTF8(analysisJSON)),
	}
	if err := s.db.Create(&report).Error; err != nil {
		logger.Errorf("[ADKAnalysis] save cancelled report: %v", err)
	}

	estimatedCost := service.EstimateAICostUSD(ppCtx.config.Provider, ppCtx.config.ModelName, ai.Usage{
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		TotalTokens:      totalTokens,
	})
	service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
		ProjectID:        ppCtx.defect.Iteration.ProjectID,
		IterationID:      &ppCtx.defect.IterationID,
		DefectID:         ppCtx.defect.ID,
		ConsumptionType:  "analysis",
		SourceID:         report.ID,
		IsFinalAttempt:   true,
		Provider:         ppCtx.config.Provider,
		ModelName:        ppCtx.config.ModelName,
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		TotalTokens:      totalTokens,
		EstimatedCostUSD: estimatedCost,
		DurationMs:       time.Since(ppCtx.startTime).Milliseconds(),
	})

	if !ppCtx.skipStatusUpdate {
		s.updateDefectStatus(ppCtx.defect.ID, bugmodel.DefectStatusPendingAssign)
	}

	if s.rollout != nil && ppCtx.sessionID != "" {
		s.rollout.MarkCancelled(ppCtx.sessionID)
	}
}

func (s *ADKAnalysisService) saveCancelledReportFromNonStream(
	fullText string,
	totalTokens, promptTokens, completionTokens int,
	defect bugmodel.Defect,
	config bugmodel.ProjectAIConfig,
	agentType string,
	startTime time.Time,
	sessionID string,
) {
	reportCode := generateADKReportCode()

	var analysisJSON json.RawMessage
	if fullText != "" {
		fallbackPayload := map[string]interface{}{
			"rawResponse":           fullText,
			"riskSummary":           "分析已取消",
			"validationSuggestions": []string{"分析被用户取消，请重新触发分析"},
		}
		if bytes, err := json.Marshal(fallbackPayload); err == nil {
			analysisJSON = bytes
		}
	}
	if analysisJSON == nil {
		analysisJSON = []byte(`{"riskSummary":"分析已取消"}`)
	}

	report := bugmodel.AnalysisReport{
		ReportCode:            reportCode,
		DefectID:              defect.ID,
		AgentType:             agentType,
		Status:                "cancelled",
		RiskSummary:           "分析已取消",
		ValidationSuggestions: util.MarshalStringSlice([]string{"分析被用户取消，请重新触发分析"}),
		Analysis:              string(util.SanitizeJSONUTF8(analysisJSON)),
	}
	if err := s.db.Create(&report).Error; err != nil {
		logger.Errorf("[ADKAnalysis] save cancelled report (non-stream): %v", err)
	}

	estimatedCost := service.EstimateAICostUSD(config.Provider, config.ModelName, ai.Usage{
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		TotalTokens:      totalTokens,
	})
	service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
		ProjectID:        defect.Iteration.ProjectID,
		IterationID:      &defect.IterationID,
		DefectID:         defect.ID,
		ConsumptionType:  "analysis",
		SourceID:         report.ID,
		IsFinalAttempt:   true,
		Provider:         config.Provider,
		ModelName:        config.ModelName,
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		TotalTokens:      totalTokens,
		EstimatedCostUSD: estimatedCost,
		DurationMs:       time.Since(startTime).Milliseconds(),
	})

	s.updateDefectStatus(defect.ID, bugmodel.DefectStatusPendingAssign)

	if s.rollout != nil && sessionID != "" {
		s.rollout.MarkCancelled(sessionID)
	}
}

func (s *ADKAnalysisService) cleanupStream(ppCtx streamPostProcessContext) {
	s.runningMu.Lock()
	delete(s.runningCtxs, ppCtx.defect.ID)
	s.runningMu.Unlock()

	if ppCtx.pipelineCancel != nil {
		ppCtx.pipelineCancel()
	}
	if ppCtx.sessionDeleteReq != nil {
		s.sessionSvc.Delete(context.Background(), ppCtx.sessionDeleteReq)
	}
	if ppCtx.repo != nil {
		if err := ppCtx.repo.Cleanup(); err != nil {
			logger.Warnf("[ADKAnalysis] stream repo cleanup failed: %v", err)
		}
	}
}

func (s *ADKAnalysisService) doStreamPostProcessing(
	fullText string,
	analysisText string,
	totalTokens, promptTokens, completionTokens int,
	ppCtx streamPostProcessContext,
) {
	responseText := analysisText
	if strings.TrimSpace(responseText) == "" {
		responseText = fullText
	}

	var analysisJSON, solutionJSON json.RawMessage
	var rootCause, riskLevel string
	var riskSummary string
	var affectedFiles []string
	var validationSuggestions []string
	var repairTriggered, repaired bool
	var repairReason string

	if rawJSON, err := extractFinalAnalysisJSONObjectFromText(responseText); err == nil {
		var parsed map[string]interface{}
		if err := json.Unmarshal([]byte(rawJSON), &parsed); err == nil {
			normalizeAnalysisFieldNames(parsed)
			normalized, telemetry := s.normalizeAnalysisByRepoEvidence(context.Background(), parsed, ppCtx.relatedFiles, ppCtx.codeContext, ppCtx.config)
			if telemetry.Repaired {
				logger.Infof("[ADKAnalysis] repaired by evidence: defect=%d agent=%s", ppCtx.defect.ID, ppCtx.agentType)
			}
			repairTriggered = telemetry.RepairTriggered
			repaired = telemetry.Repaired
			repairReason = telemetry.RepairReason

			rootCause = util.GetStringField(normalized, "rootCause")
			riskLevel = util.GetStringField(normalized, "riskLevel")
			affectedFiles = util.GetStringSliceField(normalized["affectedFiles"])
			validationSuggestions = util.GetStringSliceField(normalized["validationSuggestions"])

			riskSummary = util.GetStringField(normalized, "riskSummary")
			if riskSummary == "" {
				riskSummary = buildRiskSummary(rootCause, riskLevel)
			}
			normalized["riskSummary"] = riskSummary
			normalized["validationSuggestions"] = buildValidationSuggestions(affectedFiles, validationSuggestions)
			ensureSolution(normalized)

			aj, err := json.Marshal(normalized)
			if err == nil {
				analysisJSON = aj
			}
			if sol, ok := normalized["solution"]; ok {
				sj, err := json.Marshal(sol)
				if err == nil {
					solutionJSON = sj
				}
			}
		}
	}

	if analysisJSON == nil {
		logger.Warnf("[ADKAnalysis] stream: failed to extract JSON from AI response, using fallback: defect=%d", ppCtx.defect.ID)
		validationSuggestions = buildValidationSuggestions(nil, nil)
		fallbackPayload := map[string]interface{}{
			"rawResponse":           responseText,
			"riskSummary":           buildRiskSummary("", ""),
			"validationSuggestions": validationSuggestions,
		}
		bytes, err := json.Marshal(fallbackPayload)
		if err == nil {
			analysisJSON = bytes
		}
	}

	if riskSummary == "" {
		riskSummary = buildRiskSummary(rootCause, riskLevel)
	}
	validationSuggestions = buildValidationSuggestions(affectedFiles, validationSuggestions)

	reportCode := generateADKReportCode()
	reportStatus := bugmodel.AnalysisStatusCompleted
	if !adkAnalysisHasFixSteps(analysisJSON) && !adkAnalysisHasFixSteps(solutionJSON) {
		reportStatus = "completed_fallback"
	}

	report := bugmodel.AnalysisReport{
		ReportCode:            reportCode,
		DefectID:              ppCtx.defect.ID,
		AgentType:             ppCtx.agentType,
		Status:                reportStatus,
		RiskSummary:           util.SanitizeUTF8(riskSummary),
		ValidationSuggestions: util.MarshalStringSlice(validationSuggestions),
		Analysis:              string(util.SanitizeJSONUTF8(analysisJSON)),
		Solution:              string(util.SanitizeJSONUTF8(solutionJSON)),
	}
	if err := s.db.Create(&report).Error; err != nil {
		logger.Errorf("[ADKAnalysis] save report: %v", err)
	}

	if totalTokens <= 0 {
		estimatedUsage := service.EstimateTokenUsageFromText(ppCtx.promptText, fullText)
		promptTokens = estimatedUsage.PromptTokens
		completionTokens = estimatedUsage.CompletionTokens
		totalTokens = estimatedUsage.TotalTokens
	}

	estimatedCost := service.EstimateAICostUSD(ppCtx.config.Provider, ppCtx.config.ModelName, ai.Usage{
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		TotalTokens:      totalTokens,
	})
	service.RecordAITokenUsage(s.db, bugmodel.AITokenUsage{
		ProjectID:        ppCtx.defect.Iteration.ProjectID,
		IterationID:      &ppCtx.defect.IterationID,
		DefectID:         ppCtx.defect.ID,
		ConsumptionType:  "analysis",
		SourceID:         report.ID,
		AttemptIndex:     0,
		IsFinalAttempt:   true,
		Provider:         ppCtx.config.Provider,
		ModelName:        ppCtx.config.ModelName,
		PromptTokens:     promptTokens,
		CompletionTokens: completionTokens,
		TotalTokens:      totalTokens,
		EstimatedCostUSD: estimatedCost,
		DurationMs:       time.Since(ppCtx.startTime).Milliseconds(),
	})

	if !ppCtx.skipStatusUpdate && reportStatus == bugmodel.AnalysisStatusCompleted {
		s.updateDefectStatus(ppCtx.defect.ID, bugmodel.DefectStatusPendingFix)
	}

	if reportStatus == bugmodel.AnalysisStatusCompleted {
		sse.Notifier.NotifyAnalysisCompleted(ppCtx.defect.ID, reportCode)
	} else {
		s.db.Model(&bugmodel.Defect{}).
			Where("id = ? AND status = ?", ppCtx.defect.ID, bugmodel.DefectStatusAnalyzing).
			Update("status", bugmodel.DefectStatusPendingAnalysis)
		sse.Notifier.NotifyAnalysisFailed(ppCtx.defect.ID, "analysis produced fallback report only; manual confirmation required")
	}

	result := &ADKAnalysisResult{
		ReportCode:            reportCode,
		DefectID:              ppCtx.defect.ID,
		AgentType:             ppCtx.agentType,
		Status:                reportStatus,
		Provider:              ppCtx.config.Provider,
		ModelName:             ppCtx.config.ModelName,
		FallbackUsed:          false,
		Analysis:              analysisJSON,
		Solution:              solutionJSON,
		Duration:              time.Since(ppCtx.startTime).Milliseconds(),
		RiskSummary:           riskSummary,
		ValidationSuggestions: validationSuggestions,
		RepairTriggered:       repairTriggered,
		Repaired:              repaired,
		RepairReason:          repairReason,
	}
	s.publishAgentComment(ppCtx.defect, result)

	asyncx.Go(func() {
		defer func() {
			if r := recover(); r != nil {
				logger.Infof("[ADKAnalysis] Memory extraction panic: %v", r)
			}
		}()
		s.extractMemoriesFromAnalysis(ppCtx.defect.ID, result)
	})
}

func (s *ADKAnalysisService) buildDefectSummary(defect bugmodel.Defect, codeContext string, relatedFiles []string, attachments []map[string]string) string {
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("缺陷标题: %s\n描述: %s\n严重程度: %s\n优先级: %s\n类型: %s\n编号: %s",
		defect.Title, defect.Description, defect.Severity, defect.Priority, defect.Type, defect.Code))

	if len(attachments) > 0 {
		sb.WriteString("\n\n## 附件\n")
		for _, att := range attachments {
			sb.WriteString(fmt.Sprintf("- %s (%s): %s\n", att["FileName"], att["FileType"], att["FileURL"]))
		}
	}

	if len(relatedFiles) > 0 {
		sb.WriteString("\n\n## 相关文件\n")
		for _, f := range relatedFiles {
			sb.WriteString(fmt.Sprintf("- %s\n", f))
		}
	}

	if codeContext != "" {
		sb.WriteString("\n\n## 代码证据\n")
		if len(codeContext) > maxContextChars {
			runes := []rune(codeContext)
			if len(runes) > maxContextChars {
				codeContext = string(runes[:maxContextChars])
			}
			codeContext += "\n... (代码证据已截断)"
		}
		sb.WriteString(codeContext)
	}

	sb.WriteString("\n\n---\n")
	sb.WriteString("分析要求：请严格基于以上「代码证据」和「相关文件」进行分析。")
	if len(relatedFiles) > 0 {
		sb.WriteString(" affectedFiles 必须引用上面列出的文件路径，步骤中的 filePath 必须真实存在；涉及多仓库时，solution.steps[] 必须填写 repoHint 或使用 仓库名/文件路径。")
	} else {
		sb.WriteString(" 由于没有从仓库检索到相关文件，请仅基于缺陷描述做合理性分析，affectedFiles 返回空数组。")
	}

	return sb.String()
}

func (s *ADKAnalysisService) buildAgentTools(expCtx ExplorerContext) []tool.Tool {
	var agentTools []tool.Tool

	if expCtx.SearchFn != nil {
		t, err := NewSearchCodeToolAdapted(ExplorerContext{SearchFn: expCtx.SearchFn})
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}
	if expCtx.ReadFn != nil {
		t, err := NewReadFileToolAdapted(ExplorerContext{ReadFn: expCtx.ReadFn})
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}
	if expCtx.TraceFn != nil {
		t, err := NewTraceCallToolAdapted(ExplorerContext{TraceFn: expCtx.TraceFn})
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}
	if expCtx.HandlerFn != nil {
		t, err := NewFindAPIHandlerToolAdapted(ExplorerContext{HandlerFn: expCtx.HandlerFn})
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}
	if expCtx.ListFn != nil {
		t, err := NewListDirectoryToolAdapted(ExplorerContext{ListFn: expCtx.ListFn})
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}

	return agentTools
}

func firstAgentType(agentTypes []string) string {
	if len(agentTypes) == 0 {
		return ""
	}
	return strings.TrimSpace(agentTypes[0])
}

func (s *ADKAnalysisService) getCodeContext(ctx context.Context, defect bugmodel.Defect, agentType string) (string, []string, *git.Repository, RepositoryContext) {
	return s.getCodeContextFromGit(ctx, defect, agentType)
}

func (s *ADKAnalysisService) normalizeAnalysisByRepoEvidence(
	ctx context.Context,
	analysis map[string]interface{},
	relatedFiles []string,
	codeContext string,
	config bugmodel.ProjectAIConfig,
) (map[string]interface{}, evidenceRepairTelemetry) {
	telemetry := evidenceRepairTelemetry{CandidateFilesCount: len(relatedFiles)}
	telemetry.ReferencedFilesBefore = collectReferencedFiles(analysis)
	telemetry.OutOfScopeBefore = util.CollectOutOfScopeFiles(telemetry.ReferencedFilesBefore, relatedFiles)

	if len(analysis) == 0 {
		return analysis, telemetry
	}

	needsRepair, reason := analysisNeedsEvidenceRepair(analysis, relatedFiles)
	if !needsRepair {
		telemetry.RepairTriggered = false
		telemetry.RepairReason = reason
		telemetry.ReferencedFilesAfter = telemetry.ReferencedFilesBefore
		telemetry.OutOfScopeAfter = telemetry.OutOfScopeBefore
		return analysis, telemetry
	}

	telemetry.RepairTriggered = true
	telemetry.RepairReason = reason

	if reason == "no_related_files_clear_fabricated" {
		analysis["affectedFiles"] = []interface{}{}
		telemetry.Repaired = true
		telemetry.ReferencedFilesAfter = []string{}
		telemetry.OutOfScopeAfter = []string{}
		return analysis, telemetry
	}

	if reason == "missing_affected_files" {
		seedFiles := topRelatedFiles(relatedFiles, 3)
		analysis["affectedFiles"] = stringSliceToInterface(seedFiles)
		analysis["evidenceFiles"] = stringSliceToInterface(seedFiles)
		ensureFileLevelSolutionStep(analysis, seedFiles)
		telemetry.Repaired = true
		telemetry.ReferencedFilesAfter = seedFiles
		telemetry.OutOfScopeAfter = []string{}
		return analysis, telemetry
	}

	repaired, err := s.repairAnalysisByEvidence(ctx, analysis, relatedFiles, codeContext, config)
	if err != nil {
		logger.Errorf("[ADKAnalysis] evidence repair failed: %v", err)
		telemetry.ReferencedFilesAfter = telemetry.ReferencedFilesBefore
		telemetry.OutOfScopeAfter = telemetry.OutOfScopeBefore
		return analysis, telemetry
	}

	afterReferenced := collectReferencedFiles(repaired)
	afterOutOfScope := util.CollectOutOfScopeFiles(afterReferenced, relatedFiles)
	telemetry.ReferencedFilesAfter = afterReferenced
	telemetry.OutOfScopeAfter = afterOutOfScope
	if needsAgain, _ := analysisNeedsEvidenceRepair(repaired, relatedFiles); needsAgain {
		telemetry.Repaired = false
		telemetry.ReferencedFilesAfter = telemetry.ReferencedFilesBefore
		telemetry.OutOfScopeAfter = telemetry.OutOfScopeBefore
		return analysis, telemetry
	}
	telemetry.Repaired = true
	return repaired, telemetry
}

func (s *ADKAnalysisService) repairAnalysisByEvidence(
	ctx context.Context,
	analysis map[string]interface{},
	relatedFiles []string,
	codeContext string,
	config bugmodel.ProjectAIConfig,
) (map[string]interface{}, error) {
	analysisJSON, err := json.Marshal(analysis)
	if err != nil {
		return nil, fmt.Errorf("marshal for repair: %w", err)
	}

	prompt := buildAnalysisRepairPrompt(string(analysisJSON), relatedFiles, codeContext)
	client, err := ai.NewAIClient(config.Provider, config.APIKey, config.APIEndpoint, config.ModelName)
	if err != nil {
		return nil, err
	}

	resp, err := client.Chat(ctx, &ai.ChatRequest{
		Model:       config.ModelName,
		Messages:    []ai.Message{{Role: "user", Content: prompt}},
		Temperature: 0.1,
		MaxTokens:   defaultAnalysisMaxTokens,
	})
	if err != nil {
		return nil, err
	}
	if len(resp.Choices) == 0 {
		return nil, fmt.Errorf("empty repair response")
	}

	jsonText, err := util.ExtractJSONObjectFromText(resp.Choices[0].Message.Content)
	if err != nil {
		return nil, err
	}

	var repaired map[string]interface{}
	if err := json.Unmarshal([]byte(jsonText), &repaired); err != nil {
		return nil, err
	}
	return repaired, nil
}

func (s *ADKAnalysisService) publishAgentComment(defect bugmodel.Defect, result *ADKAnalysisResult) {
	var analysisData map[string]interface{}
	if err := json.Unmarshal(result.Analysis, &analysisData); err != nil {
		logger.Errorf("[ADKAnalysis] unmarshal for comment: %v", err)
	}

	rootCause := "已完成分析"
	if rc, ok := analysisData["rootCause"].(string); ok {
		rootCause = rc
	}
	riskLevel := "medium"
	if rl, ok := analysisData["riskLevel"].(string); ok {
		riskLevel = rl
	}

	riskEmoji := "🟡"
	switch riskLevel {
	case "high":
		riskEmoji = "🔴"
	case "low":
		riskEmoji = "🟢"
	}

	content := fmt.Sprintf(`🤖 **AGENT分析报告**（%s）

**根本原因**：%s
**风险等级**：%s %s
**执行模型**：%s / %s%s
**风险摘要**：%s

**修复前验证建议**：
%s

**详细分析**：
`+"```json"+`
%s
`+"```"+`

💡 是否需要我执行自动修复？`,
		util.GetAgentLabel(result.AgentType),
		rootCause,
		riskEmoji, strings.ToUpper(riskLevel),
		util.DefaultString(result.Provider, "fallback"), util.DefaultString(result.ModelName, "rule-based"),
		func() string {
			if result.FallbackUsed {
				return "（已触发fallback）"
			}
			return ""
		}(),
		util.DefaultString(result.RiskSummary, "待补充"),
		util.FormatValidationSuggestions(result.ValidationSuggestions),
		string(result.Analysis),
	)

	comment := bugmodel.Comment{
		DefectID:       defect.ID,
		Content:        html.EscapeString(content),
		AgentType:      result.AgentType,
		IsAgentMessage: true,
	}
	comment.UserID = resolveCommentUserID(defect)
	if !ensureCommentUserExists(s.db, comment.UserID) {
		return
	}
	if err := s.db.Create(&comment).Error; err != nil {
		logger.Errorf("[ADKAnalysis] publish comment failed: %v", err)
	}
}

func (s *ADKAnalysisService) extractMemoriesFromAnalysis(defectID uint, result *ADKAnalysisResult) {
	var defect bugmodel.Defect
	if err := s.db.Preload("Iteration").First(&defect, defectID).Error; err != nil {
		return
	}
	projectID := defect.Iteration.ProjectID

	var project bugmodel.Project
	if err := s.db.Select("memory_enabled").First(&project, projectID).Error; err != nil || !project.MemoryEnabled {
		return
	}

	var analysisData map[string]interface{}
	if err := json.Unmarshal(result.Analysis, &analysisData); err != nil {
		return
	}

	memories := make([]struct {
		category string
		content  string
	}, 0, 3)

	if rootCause, ok := analysisData["rootCause"].(string); ok && rootCause != "" {
		memories = append(memories, struct {
			category string
			content  string
		}{bugmodel.MemoryCategoryCommonError, rootCause})
	}
	if riskLevel, ok := analysisData["riskLevel"].(string); ok && riskLevel != "" {
		if rootCause, ok := analysisData["rootCause"].(string); ok && rootCause != "" {
			memories = append(memories, struct {
				category string
				content  string
			}{bugmodel.MemoryCategoryAvoidStrategy, fmt.Sprintf("缺陷[%s]风险等级%s: %s", defect.Title, riskLevel, rootCause)})
		}
	}
	if affectedFiles, ok := analysisData["affectedFiles"].([]interface{}); ok && len(affectedFiles) > 0 {
		var files []string
		for _, f := range affectedFiles {
			if s, ok := f.(string); ok {
				files = append(files, s)
			}
		}
		if len(files) > 0 {
			memories = append(memories, struct {
				category string
				content  string
			}{bugmodel.MemoryCategoryIterationContext, fmt.Sprintf("缺陷[%s]影响文件: %s", defect.Title, strings.Join(files, ", "))})
		}
	}

	for _, m := range memories {
		memory := bugmodel.AgentMemory{
			ProjectID: projectID,
			Category:  m.category,
			Content:   m.content,
			Source:    bugmodel.MemorySourceAutoExtract,
		}
		if err := s.db.Create(&memory).Error; err != nil {
			logger.Errorf("[ADK] create memory failed: %v", err)
		}
	}
}

func (s *ADKAnalysisService) getAttachmentsInfo(defectID uint) []map[string]string {
	var attachments []bugmodel.Attachment
	if err := s.db.Where("defect_id = ?", defectID).Find(&attachments).Error; err != nil {
		return nil
	}
	result := make([]map[string]string, 0, len(attachments))
	for _, att := range attachments {
		result = append(result, map[string]string{
			"FileName": att.FileName,
			"FileType": att.FileType,
			"FileURL":  att.FileURL,
		})
	}
	return result
}

func (s *ADKAnalysisService) listUsableAIConfigsCached(projectID uint) ([]bugmodel.ProjectAIConfig, error) {
	s.configCacheMu.RLock()
	if cachedAt, ok := s.configCacheAt[projectID]; ok && time.Since(cachedAt) < 5*time.Minute {
		if configs, ok2 := s.configCache[projectID]; ok2 && len(configs) > 0 {
			s.configCacheMu.RUnlock()
			return configs, nil
		}
	}
	s.configCacheMu.RUnlock()

	var configs []bugmodel.ProjectAIConfig
	if err := s.db.Where("project_id = ?", projectID).Order("is_default DESC").Find(&configs).Error; err != nil {
		return nil, err
	}

	s.configCacheMu.Lock()
	if s.configCache == nil {
		s.configCache = make(map[uint][]bugmodel.ProjectAIConfig)
	}
	if s.configCacheAt == nil {
		s.configCacheAt = make(map[uint]time.Time)
	}
	if len(s.configCache) > 1000 {
		type cacheEntry struct {
			key uint
			at  time.Time
		}
		entries := make([]cacheEntry, 0, len(s.configCacheAt))
		for k, v := range s.configCacheAt {
			entries = append(entries, cacheEntry{k, v})
		}
		sort.Slice(entries, func(i, j int) bool {
			return entries[i].at.Before(entries[j].at)
		})
		evictCount := 500
		if len(entries) < evictCount {
			evictCount = len(entries)
		}
		for i := 0; i < evictCount; i++ {
			delete(s.configCache, entries[i].key)
			delete(s.configCacheAt, entries[i].key)
		}
	}
	s.configCache[projectID] = configs
	s.configCacheAt[projectID] = time.Now()
	s.configCacheMu.Unlock()

	return configs, nil
}

func (s *ADKAnalysisService) buildMemoryContext(projectID uint) string {
	var project bugmodel.Project
	if err := s.db.Select("memory_enabled").First(&project, projectID).Error; err != nil || !project.MemoryEnabled {
		return ""
	}

	var memories []bugmodel.AgentMemory
	if err := s.db.Where("project_id = ? AND enabled = ?", projectID, true).
		Order("relevance_score DESC").Limit(10).Find(&memories).Error; err != nil {
		return ""
	}
	if len(memories) == 0 {
		return ""
	}
	var sb strings.Builder
	for _, mem := range memories {
		sb.WriteString(fmt.Sprintf("- [%s] %s\n", mem.Category, mem.Content))
	}
	return sb.String()
}

func (s *ADKAnalysisService) executePlannerPhase(
	ctx context.Context,
	llm adkmodel.LLM,
	expCtx ExplorerContext,
	defect bugmodel.Defect,
	codeContext string,
	relatedFiles []string,
	attachments []map[string]string,
) (string, []string) {
	plannerAgent, err := NewPlannerAgent(LLMWithoutResponseFormat(llm))
	if err != nil {
		logger.Warnf("[ADKAnalysis] create planner agent failed: %v, skipping planner phase", err)
		return "", nil
	}

	sessionID := fmt.Sprintf("planner_%d_%d", defect.ID, time.Now().UnixMilli())
	userID := fmt.Sprintf("user_%d", defect.ReporterID)

	_, cerr := s.sessionSvc.Create(ctx, &session.CreateRequest{
		AppName: "bug-agent", UserID: userID, SessionID: sessionID,
	})
	if cerr != nil {
		logger.Warnf("[ADKAnalysis] create planner session failed: %v", cerr)
		return "", nil
	}
	defer s.sessionSvc.Delete(ctx, &session.DeleteRequest{
		AppName: "bug-agent", UserID: userID, SessionID: sessionID,
	})

	summary := s.buildDefectSummary(defect, codeContext, relatedFiles, attachments)
	userMsg := &genai.Content{
		Role:  genai.RoleUser,
		Parts: []*genai.Part{{Text: summary}},
	}

	r, rerr := runner.New(runner.Config{
		AppName:        "bug-agent",
		Agent:          plannerAgent,
		SessionService: s.sessionSvc,
	})
	if rerr != nil {
		logger.Warnf("[ADKAnalysis] create planner runner failed: %v", rerr)
		return "", nil
	}

	events := r.Run(ctx, userID, sessionID, userMsg, agent.RunConfig{})
	collected, err := CollectEvents(events)
	if err != nil {
		logger.Warnf("[ADKAnalysis] planner collect events failed: %v", err)
		return "", nil
	}

	var fullText string
	for _, evt := range collected {
		if evt.Content != nil {
			for _, part := range evt.Content.Parts {
				if part.Text != "" {
					fullText += part.Text
				}
			}
		}
	}

	logger.Debugf("[ADKAnalysis] planner raw output for defect %d: %q", defect.ID, truncateString(fullText, 500))

	plan, perr := ParsePlanOutput(fullText)
	if perr != nil {
		logger.Warnf("[ADKAnalysis] planner parse failed: %v, skipping executor", perr)
		return "", nil
	}

	logger.Infof("[ADKAnalysis] planner produced %d steps for defect %d", len(plan.Steps), defect.ID)

	execResult, eerr := ExecutePlan(ctx, plan, expCtx)
	if eerr != nil {
		logger.Warnf("[ADKAnalysis] executor failed: %v", eerr)
	}
	if execResult != nil && execResult.Evidence != "" {
		logger.Infof("[ADKAnalysis] executor collected %d steps, %d files for defect %d", len(execResult.Steps), len(execResult.Files), defect.ID)
		return execResult.Evidence, execResult.Files
	}

	return "", nil
}

func mergeFileLists(a, b []string) []string {
	seen := make(map[string]bool, len(a))
	for _, f := range a {
		seen[f] = true
	}
	for _, f := range b {
		if !seen[f] {
			a = append(a, f)
			seen[f] = true
		}
	}
	return a
}

func (s *ADKAnalysisService) CancelAnalysis(defectID uint) bool {
	s.runningMu.Lock()
	cancel, ok := s.runningCtxs[defectID]
	if ok {
		delete(s.runningCtxs, defectID)
	}
	s.runningMu.Unlock()
	if ok && cancel != nil {
		cancel()
		s.markAnalysisCancelled(defectID)
		sse.Notifier.NotifyAnalysisCancelled(defectID)
		return true
	}
	return false
}

func (s *ADKAnalysisService) markAnalysisCancelled(defectID uint) {
	if s == nil || s.db == nil {
		return
	}
	if err := s.db.Model(&bugmodel.Defect{}).
		Where("id = ? AND status = ?", defectID, bugmodel.DefectStatusAnalyzing).
		Update("status", bugmodel.DefectStatusPendingAnalysis).Error; err != nil {
		logger.Errorf("[ADKAnalysis] cancel status update failed: defect=%d err=%v", defectID, err)
	}
}

func (s *ADKAnalysisService) buildHandlerFnWithRepo(repo *git.Repository) func(ctx interface{}, apiPath, httpMethod string) ([]ai.HandlerHit, error) {
	return func(ctx interface{}, apiPath, httpMethod string) ([]ai.HandlerHit, error) {
		if repo == nil {
			return nil, fmt.Errorf("find_api_handler: no repository available")
		}
		files, err := repo.SearchFiles(apiPath, 10)
		if err != nil {
			return nil, fmt.Errorf("find_api_handler: search failed: %w", err)
		}
		methodUpper := strings.ToUpper(httpMethod)
		var hits []ai.HandlerHit
		for _, file := range files {
			content, err := repo.ReadFile(file)
			if err != nil {
				continue
			}
			lines := strings.Split(content, "\n")
			for i, line := range lines {
				if !strings.Contains(line, apiPath) {
					continue
				}
				if methodUpper != "" && !strings.Contains(strings.ToUpper(line), methodUpper) {
					continue
				}
				hits = append(hits, ai.HandlerHit{
					FilePath:   file,
					LineNumber: i + 1,
				})
				if len(hits) >= 5 {
					return hits, nil
				}
			}
		}
		return hits, nil
	}
}

func (s *ADKAnalysisService) updateDefectStatus(defectID uint, status string) {
	var defect bugmodel.Defect
	if err := s.db.First(&defect, defectID).Error; err != nil {
		return
	}
	if !bugmodel.IsValidDefectTransition(defect.Status, status) {
		return
	}
	result := s.db.Model(&bugmodel.Defect{}).Where("id = ? AND status = ?", defectID, defect.Status).Update("status", status)
	if result.RowsAffected == 0 {
		logger.Warnf("[ADK] updateDefectStatus CAS failed: defect #%d expected=%s target=%s", defectID, defect.Status, status)
	}
}

func (s *ADKAnalysisService) fallbackAnalysis(defect bugmodel.Defect, agentTypes []string, startTime time.Time, reason string, skipStatusUpdate bool) (*ADKAnalysisResult, error) {
	agentType := "frontend"
	if len(agentTypes) > 0 {
		agentType = agentTypes[0]
	}

	analysis := map[string]interface{}{
		"rootCause":     fmt.Sprintf("缺陷「%s」可能由代码逻辑错误或边界条件处理不当导致", defect.Title),
		"affectedFiles": []string{},
		"affectedScope": "需进一步调查代码确定影响范围",
		"riskLevel":     util.MapSeverityToRisk(defect.Severity),
		"solution": map[string]interface{}{
			"description":     "建议修复步骤：1.复现问题 2.定位代码 3.实施修复 4.测试验证",
			"estimatedEffort": "中",
		},
		"riskSummary":           "已切换到降级分析，请人工确认",
		"failureReason":         reason,
		"validationSuggestions": []string{"优先复现并确认根因", "补回归验证用例", "验证修复后状态流转"},
	}
	analysisJSON, err := json.Marshal(analysis)
	if err != nil {
		analysisJSON = []byte("{}")
	}
	solutionVal := analysis["solution"]
	solutionJSON, err := json.Marshal(solutionVal)
	if err != nil {
		solutionJSON = []byte("null")
	}

	reportCode := generateADKReportCode()

	report := bugmodel.AnalysisReport{
		ReportCode:            reportCode,
		DefectID:              defect.ID,
		AgentType:             agentType,
		Status:                "completed_fallback",
		ErrorMessage:          reason,
		RiskSummary:           "已切换到降级分析，请人工确认",
		ValidationSuggestions: util.MarshalStringSlice([]string{"优先复现并确认根因", "补回归验证用例", "验证修复后状态流转"}),
		Analysis:              string(util.SanitizeJSONUTF8(analysisJSON)),
		Solution:              string(util.SanitizeJSONUTF8(solutionJSON)),
	}
	if err := s.db.Create(&report).Error; err != nil {
		logger.Errorf("[ADK] create fallback report failed: %v", err)
	}

	result := &ADKAnalysisResult{
		ReportCode:            reportCode,
		DefectID:              defect.ID,
		AgentType:             agentType,
		Status:                "completed_fallback",
		Provider:              "rule-based",
		ModelName:             "fallback",
		FallbackUsed:          true,
		Analysis:              analysisJSON,
		Solution:              solutionJSON,
		Duration:              time.Since(startTime).Milliseconds(),
		RiskSummary:           "已切换到降级分析，请人工确认",
		ValidationSuggestions: []string{"优先复现并确认根因", "补回归验证用例", "验证修复后状态流转"},
		Error:                 reason,
	}

	s.publishAgentComment(defect, result)

	if !skipStatusUpdate {
		s.updateDefectStatus(defect.ID, bugmodel.DefectStatusPendingAnalysis)
		s.updateDefectStatus(defect.ID, bugmodel.DefectStatusAnalyzing)
		s.updateDefectStatus(defect.ID, bugmodel.DefectStatusPendingFix)
	}

	return result, nil
}

func toContext(ctx interface{}) context.Context {
	if c, ok := ctx.(context.Context); ok {
		return c
	}
	return context.Background()
}

type evidenceRepairTelemetry struct {
	CandidateFilesCount   int
	RepairTriggered       bool
	Repaired              bool
	RepairReason          string
	ReferencedFilesBefore []string
	ReferencedFilesAfter  []string
	OutOfScopeBefore      []string
	OutOfScopeAfter       []string
}

func analysisNeedsEvidenceRepair(analysis map[string]interface{}, relatedFiles []string) (bool, string) {
	referenced := collectReferencedFiles(analysis)
	if len(referenced) == 0 {
		if len(relatedFiles) > 0 {
			return true, "missing_affected_files"
		}
		return false, "no_referenced_files"
	}
	if len(relatedFiles) == 0 {
		return true, "no_related_files_clear_fabricated"
	}
	allowed := make(map[string]struct{}, len(relatedFiles))
	for _, f := range relatedFiles {
		f = strings.TrimSpace(f)
		if f != "" {
			allowed[f] = struct{}{}
		}
	}
	for _, f := range referenced {
		if _, ok := allowed[f]; !ok {
			return true, "out_of_scope_files"
		}
	}
	return false, "consistent"
}

func collectAnalysisEventText(events []*session.Event, agentType string) string {
	if len(events) == 0 {
		return ""
	}
	for _, matcher := range []func(string, string) bool{
		isExactAnalyzerAuthor,
		isExactAgentAuthor,
		isAnyAnalyzerAuthor,
	} {
		var text strings.Builder
		for _, event := range events {
			if event == nil || !matcher(event.Author, agentType) || event.Content == nil {
				continue
			}
			for _, part := range event.Content.Parts {
				if part.Text != "" {
					text.WriteString(part.Text)
				}
			}
		}
		if strings.TrimSpace(text.String()) != "" {
			return text.String()
		}
	}
	return ""
}

func eventMatchesAnalysisAuthor(author, agentType string) bool {
	return isExactAnalyzerAuthor(author, agentType) ||
		isExactAgentAuthor(author, agentType) ||
		isAnyAnalyzerAuthor(author, agentType)
}

func isExactAnalyzerAuthor(author, agentType string) bool {
	author = strings.TrimSpace(author)
	agentType = strings.TrimSpace(agentType)
	return agentType != "" && author == agentType+"_analyzer"
}

func isExactAgentAuthor(author, agentType string) bool {
	author = strings.TrimSpace(author)
	agentType = strings.TrimSpace(agentType)
	return agentType != "" && author == agentType
}

func isAnyAnalyzerAuthor(author, _ string) bool {
	author = strings.TrimSpace(author)
	if author == "" {
		return false
	}
	switch author {
	case "code_explorer", "code_planner", "parallel_analysis", "analysis_pipeline":
		return false
	}
	return strings.HasSuffix(author, "_analyzer")
}

func extractFinalAnalysisJSONObjectFromText(text string) (string, error) {
	candidates := extractJSONObjectCandidates(text)
	if len(candidates) == 0 {
		return "", fmt.Errorf("json object not found")
	}

	for i := len(candidates) - 1; i >= 0; i-- {
		var payload map[string]interface{}
		if err := json.Unmarshal([]byte(candidates[i]), &payload); err != nil {
			continue
		}
		if isFinalAnalysisPayload(payload) {
			return candidates[i], nil
		}
	}

	return candidates[len(candidates)-1], nil
}

func extractJSONObjectCandidates(text string) []string {
	raw := strings.TrimSpace(text)
	if raw == "" {
		return nil
	}

	var candidates []string
	for start := strings.Index(raw, "{"); start >= 0 && start < len(raw); {
		depth := 0
		inStr := false
		escape := false
		foundEnd := -1
		for i := start; i < len(raw); i++ {
			ch := raw[i]
			if escape {
				escape = false
				continue
			}
			if ch == '\\' && inStr {
				escape = true
				continue
			}
			if ch == '"' {
				inStr = !inStr
				continue
			}
			if inStr {
				continue
			}
			switch ch {
			case '{':
				depth++
			case '}':
				depth--
				if depth == 0 {
					foundEnd = i + 1
				}
			}
			if foundEnd > 0 {
				break
			}
		}
		if foundEnd < 0 {
			break
		}
		candidate := strings.TrimSpace(raw[start:foundEnd])
		if json.Valid([]byte(candidate)) {
			candidates = append(candidates, candidate)
		}
		next := strings.Index(raw[foundEnd:], "{")
		if next < 0 {
			break
		}
		start = foundEnd + next
	}
	return candidates
}

func isFinalAnalysisPayload(payload map[string]interface{}) bool {
	if payload == nil {
		return false
	}
	if _, hasRootCause := payload["rootCause"]; hasRootCause {
		return true
	}
	if _, hasSolution := payload["solution"]; hasSolution {
		return true
	}
	if _, hasRisk := payload["riskLevel"]; hasRisk {
		return true
	}
	if _, hasAffected := payload["affectedFiles"]; hasAffected {
		return true
	}
	return false
}

func topRelatedFiles(files []string, limit int) []string {
	if limit <= 0 {
		return []string{}
	}
	seen := map[string]struct{}{}
	out := make([]string, 0, limit)
	for _, file := range files {
		file = strings.TrimSpace(file)
		if file == "" {
			continue
		}
		if _, ok := seen[file]; ok {
			continue
		}
		seen[file] = struct{}{}
		out = append(out, file)
		if len(out) >= limit {
			break
		}
	}
	return out
}

func stringSliceToInterface(values []string) []interface{} {
	out := make([]interface{}, 0, len(values))
	for _, value := range values {
		out = append(out, value)
	}
	return out
}

func ensureFileLevelSolutionStep(analysis map[string]interface{}, files []string) {
	if len(files) == 0 {
		return
	}
	solution, ok := analysis["solution"].(map[string]interface{})
	if !ok {
		solution = map[string]interface{}{}
		analysis["solution"] = solution
	}
	steps, ok := solution["steps"].([]interface{})
	if !ok || len(steps) == 0 {
		solution["steps"] = []interface{}{
			map[string]interface{}{
				"step":     1,
				"action":   fmt.Sprintf("基于代码证据定位并修复 %s", files[0]),
				"filePath": files[0],
			},
		}
		return
	}
	for _, step := range steps {
		stepMap, ok := step.(map[string]interface{})
		if !ok {
			continue
		}
		if looksLikeAnalysisRepoFilePath(util.GetStringField(stepMap, "filePath")) ||
			looksLikeAnalysisRepoFilePath(util.GetStringField(stepMap, "path")) ||
			looksLikeAnalysisRepoFilePath(util.GetStringField(stepMap, "targetFile")) {
			return
		}
	}
	if stepMap, ok := steps[0].(map[string]interface{}); ok {
		stepMap["filePath"] = files[0]
	}
}

func collectReferencedFiles(analysis map[string]interface{}) []string {
	seen := map[string]struct{}{}
	out := make([]string, 0)
	add := func(f string) {
		f = strings.TrimSpace(f)
		if f == "" {
			return
		}
		if _, ok := seen[f]; ok {
			return
		}
		seen[f] = struct{}{}
		out = append(out, f)
	}
	for _, f := range util.GetStringSliceField(analysis["affectedFiles"]) {
		add(f)
	}
	if sol, ok := analysis["solution"].(map[string]interface{}); ok {
		if steps, ok := sol["steps"].([]interface{}); ok {
			for _, s := range steps {
				if sm, ok := s.(map[string]interface{}); ok {
					add(util.GetStringField(sm, "filePath"))
					add(util.GetStringField(sm, "path"))
					add(util.GetStringField(sm, "targetFile"))
				}
			}
		}
	}
	return out
}

func buildAnalysisRepairPrompt(originalJSON string, relatedFiles []string, codeContext string) string {
	var b strings.Builder
	b.WriteString("修正分析JSON，使文件路径严格基于仓库证据。只输出JSON，不要解释。\n")
	b.WriteString("约束：\n1. affectedFiles 只能从允许文件列表选\n2. solution.steps[].filePath 只能从允许文件列表选\n3. 可修复步骤必须包含 filePath\n4. 多仓库时保留或补充 repoHint\n5. 保留原有语义\n\n")
	b.WriteString("## 允许文件列表\n")
	for _, f := range relatedFiles {
		b.WriteString("- " + f + "\n")
	}
	if strings.TrimSpace(codeContext) != "" {
		b.WriteString("\n## 代码证据\n" + codeContext + "\n")
	}
	b.WriteString("\n## 原始分析JSON\n" + originalJSON)
	return b.String()
}

var filePathPattern = regexp.MustCompile("`?((?:server|web|src|internal|cmd|pkg|packages|frontend|backend)/[a-zA-Z0-9_./-]+\\.(?:tsx|ts|jsx|js|vue|go|py|java|rs|rb|php|scss|css|html|yaml|yml|json|toml|xml|sql|sh))`?")

func extractFilePathsFromText(text string) []string {
	seen := make(map[string]bool)
	var result []string
	matches := filePathPattern.FindAllStringSubmatch(text, -1)
	for _, m := range matches {
		fp := m[1]
		if seen[fp] {
			continue
		}
		seen[fp] = true
		result = append(result, fp)
	}
	return result
}

func buildRiskSummary(rootCause, riskLevel string) string {
	if rootCause == "" {
		return "待补充"
	}
	summary := truncateAnalysisText(rootCause, 100)
	if riskLevel != "" {
		summary = fmt.Sprintf("[%s] %s", strings.ToUpper(riskLevel), summary)
	}
	return summary
}

func buildValidationSuggestions(affectedFiles []string, existing []string) []string {
	suggestions := make([]string, 0, len(existing)+3)
	suggestions = append(suggestions, existing...)
	if len(affectedFiles) > 0 {
		suggestions = append(suggestions, fmt.Sprintf("验证 %s 中修复是否生效", affectedFiles[0]))
	}
	suggestions = append(suggestions, "补一条覆盖当前缺陷场景的回归验证用例")
	suggestions = append(suggestions, "验证修复后状态从待修复流转到待验证")
	return suggestions
}

func normalizeAnalysisFieldNames(analysis map[string]interface{}) {
	nestedKeys := []string{"analysis", "analysisResult", "details", "result", "data", "output"}
	for _, key := range nestedKeys {
		if nested, ok := analysis[key]; ok {
			if m, ok := nested.(map[string]interface{}); ok {
				for k, v := range m {
					if _, exists := analysis[k]; !exists {
						analysis[k] = v
					}
				}
				delete(analysis, key)
			} else if s, ok := nested.(string); ok && len(s) > 10 {
				var parsed map[string]interface{}
				if err := json.Unmarshal([]byte(s), &parsed); err == nil {
					for k, v := range parsed {
						if _, exists := analysis[k]; !exists {
							analysis[k] = v
						}
					}
					delete(analysis, key)
				}
			}
		}
	}
	if sol, ok := analysis["fixStrategy"]; ok {
		if _, hasRC := analysis["rootCause"]; !hasRC {
			if m, ok := sol.(map[string]interface{}); ok {
				if approach, ok := m["approach"].(string); ok && approach != "" {
					analysis["rootCause"] = approach
				}
			}
		}
		if _, hasSol := analysis["solution"]; !hasSol {
			analysis["solution"] = sol
		}
		delete(analysis, "fixStrategy")
	}
	fieldAliases := map[string]string{
		"analysisSteps":          "steps",
		"bugCategory":            "bugType",
		"causeType":              "rootCauseType",
		"fixSteps":               "steps",
		"fixPlan":                "solution",
		"repairSteps":            "steps",
		"possibleRootCause":      "rootCause",
		"relatedFiles":           "affectedFiles",
		"suggestions":            "validationSuggestions",
		"stepsToReproduce":       "steps",
		"overview":               "summary",
		"root_cause":             "rootCause",
		"root_cause_type":        "rootCauseType",
		"bug_type":               "bugType",
		"risk_level":             "riskLevel",
		"risk_summary":           "riskSummary",
		"affected_files":         "affectedFiles",
		"validation_suggestions": "validationSuggestions",
		"data_path_summary":      "rootCause",
	}
	for alias, canonical := range fieldAliases {
		if val, ok := analysis[alias]; ok {
			if _, exists := analysis[canonical]; !exists {
				analysis[canonical] = val
			}
			delete(analysis, alias)
		}
	}
	if findings, ok := analysis["findings"]; ok {
		if arr, ok := findings.([]interface{}); ok {
			var files []string
			var evidences []string
			var maxSeverity string
			for _, item := range arr {
				if m, ok := item.(map[string]interface{}); ok {
					if fp, ok := m["file_path"].(string); ok && fp != "" {
						files = append(files, fp)
					}
					if ev, ok := m["evidence"].(string); ok && ev != "" {
						evidences = append(evidences, ev)
					}
					if sev, ok := m["severity"].(string); ok {
						if sev == "critical" || sev == "high" {
							if maxSeverity == "" || maxSeverity != "critical" {
								maxSeverity = sev
							}
						} else if maxSeverity == "" {
							maxSeverity = sev
						}
					}
				}
			}
			if len(files) > 0 {
				if _, exists := analysis["affectedFiles"]; !exists {
					analysis["affectedFiles"] = files
				}
			}
			if len(evidences) > 0 {
				if _, exists := analysis["rootCause"]; !exists {
					analysis["rootCause"] = strings.Join(evidences, "; ")
				}
			}
			if maxSeverity != "" {
				if _, exists := analysis["riskLevel"]; !exists {
					switch maxSeverity {
					case "critical":
						analysis["riskLevel"] = "high"
					case "high":
						analysis["riskLevel"] = "high"
					case "medium":
						analysis["riskLevel"] = "medium"
					default:
						analysis["riskLevel"] = "low"
					}
				}
			}
		}
		delete(analysis, "findings")
	}
	if rc, ok := analysis["rootCause"]; ok {
		if m, ok := rc.(map[string]interface{}); ok {
			if desc, ok := m["description"].(string); ok {
				analysis["rootCause"] = desc
			} else if summary, ok := m["summary"].(string); ok {
				analysis["rootCause"] = summary
			}
		}
	}
	enrichAnalysisFromReasoningText(analysis)
	if rs, ok := analysis["riskSummary"]; ok {
		if s, ok := rs.(string); ok && (s == "" || s == "待补充" || s == "待补充...") {
			delete(analysis, "riskSummary")
		}
	}
	if _, ok := analysis["riskSummary"]; !ok {
		if rootCause := strings.TrimSpace(util.GetStringField(analysis, "rootCause")); rootCause != "" {
			analysis["riskSummary"] = buildRiskSummary(rootCause, util.GetStringField(analysis, "riskLevel"))
		}
	}
}

func enrichAnalysisFromReasoningText(analysis map[string]interface{}) {
	text := collectReasoningText(analysis)
	if strings.TrimSpace(text) == "" {
		return
	}

	extractedFiles := extractFilePathsFromText(text)
	if len(extractedFiles) > 0 && len(util.GetStringSliceField(analysis["affectedFiles"])) == 0 {
		analysis["affectedFiles"] = extractedFiles
	}

	if strings.TrimSpace(util.GetStringField(analysis, "rootCause")) == "" {
		if len(extractedFiles) > 0 {
			analysis["rootCause"] = fmt.Sprintf("分析输出指向相关文件 %s，需要沿这些文件核对缺陷链路。", strings.Join(extractedFiles, "、"))
		} else {
			analysis["rootCause"] = truncateAnalysisText(text, 180)
		}
	}
}

func collectReasoningText(analysis map[string]interface{}) string {
	var parts []string
	appendField := func(key string) {
		value := strings.TrimSpace(util.GetStringField(analysis, key))
		if value != "" && value != "待补充" && value != "待补充..." {
			parts = append(parts, value)
		}
	}
	for _, key := range []string{"thinking", "summary", "rootCause", "riskSummary", "affectedScope"} {
		appendField(key)
	}

	if sol, ok := analysis["solution"].(map[string]interface{}); ok {
		if desc := strings.TrimSpace(util.GetStringField(sol, "description")); desc != "" {
			parts = append(parts, desc)
		}
		if steps, ok := sol["steps"].([]interface{}); ok {
			for _, step := range steps {
				stepMap, ok := step.(map[string]interface{})
				if !ok {
					continue
				}
				for _, key := range []string{"rawGuidance", "description", "action", "filePath", "path", "targetFile"} {
					value := strings.TrimSpace(util.GetStringField(stepMap, key))
					if value != "" {
						parts = append(parts, value)
					}
				}
			}
		}
	}

	return strings.Join(parts, "\n")
}

func truncateAnalysisText(text string, limit int) string {
	text = strings.Join(strings.Fields(strings.TrimSpace(text)), " ")
	if text == "" || limit <= 0 {
		return text
	}
	runes := []rune(text)
	if len(runes) <= limit {
		return text
	}
	return string(runes[:limit]) + "..."
}

func ensureSolution(normalized map[string]interface{}) {
	if sol, ok := normalized["solution"]; ok {
		if m, ok := sol.(map[string]interface{}); ok {
			if _, hasSteps := m["steps"]; !hasSteps || isEmptySlice(m["steps"]) {
				if topSteps, ok := normalized["steps"]; ok && !isEmptySlice(topSteps) {
					m["steps"] = topSteps
				} else {
					m["steps"] = buildFallbackSteps(normalized)
				}
			}
			if _, hasDesc := m["description"]; !hasDesc || isEmptyString(m["description"]) {
				if summary, ok := normalized["summary"].(string); ok && summary != "" {
					m["description"] = summary
				} else if rc, ok := normalized["rootCause"].(string); ok && rc != "" {
					m["description"] = rc
				}
			}
		}
		return
	}
	solution := map[string]interface{}{}
	if steps, ok := normalized["steps"]; ok && !isEmptySlice(steps) {
		solution["steps"] = steps
	} else {
		solution["steps"] = buildFallbackSteps(normalized)
	}
	if summary, ok := normalized["summary"]; ok {
		solution["description"] = summary
	}
	if desc, ok := solution["description"]; !ok || desc == nil {
		if rc, ok := normalized["rootCause"].(string); ok && rc != "" {
			solution["description"] = rc
		}
	}
	normalized["solution"] = solution
}

func buildFallbackSteps(normalized map[string]interface{}) []interface{} {
	var steps []interface{}

	if fixSugg, ok := normalized["fix suggestions"].(string); ok && fixSugg != "" {
		steps = append(steps, map[string]interface{}{
			"step":   1,
			"action": fixSugg,
		})
	} else if fixEx, ok := normalized["fix_example"].(string); ok && fixEx != "" {
		action := "根据分析结论修复缺陷"
		if conc, ok := normalized["conclusion"].(string); ok && conc != "" {
			action = conc
		}
		steps = append(steps, map[string]interface{}{
			"step":   1,
			"action": action,
			"code":   fixEx,
		})
	} else if conc, ok := normalized["conclusion"].(string); ok && conc != "" {
		steps = append(steps, map[string]interface{}{
			"step":   1,
			"action": conc,
		})
	} else if thinking, ok := normalized["thinking"].(string); ok && thinking != "" {
		steps = append(steps, map[string]interface{}{
			"step":        1,
			"action":      "根据分析思路修复缺陷",
			"rawGuidance": thinking,
		})
	}

	if len(steps) == 0 {
		if rc, ok := normalized["rootCause"].(string); ok && rc != "" {
			steps = append(steps, map[string]interface{}{
				"step":   1,
				"action": rc,
			})
		}
	}

	return steps
}

func isEmptySlice(v interface{}) bool {
	if s, ok := v.([]interface{}); ok {
		return len(s) == 0
	}
	return false
}

func isEmptyString(v interface{}) bool {
	if s, ok := v.(string); ok {
		return s == ""
	}
	return v == nil
}

func resolveCommentUserID(defect bugmodel.Defect) uint {
	if defect.ReporterID > 0 {
		return defect.ReporterID
	}
	return 1
}

func ensureCommentUserExists(db *gorm.DB, userID uint) bool {
	var count int64
	db.Model(&bugmodel.User{}).Where("id = ?", userID).Count(&count)
	return count > 0
}

const (
	adkMaxEvidenceFiles   = 8
	adkMaxEvidenceBlocks  = 3
	adkEvidenceLineRadius = 3
)

func (s *ADKAnalysisService) getCodeContextFromGit(ctx context.Context, defect bugmodel.Defect, agentType string) (string, []string, *git.Repository, RepositoryContext) {
	selection, err := service.ResolveDefectRepositorySelection(s.db, defect, agentType, defect.ReporterID)
	if err != nil {
		logger.Infof("[ADKAnalysis] 未能解析关联仓库，跳过代码上下文检索: defect=%d iteration=%d err=%v", defect.ID, defect.IterationID, err)
		return "", nil, nil, RepositoryContext{}
	}

	projectRepo := selection.ProjectRepo
	iterationBranch := selection.IterationBranch
	logger.Infof("[ADKAnalysis] 使用仓库: url=%s branch=%s iterationBranch=%s", projectRepo.RepoURL, projectRepo.DefaultBranch, iterationBranch)

	cloneCtx, cancel := context.WithTimeout(context.Background(), cloneTimeout)
	defer cancel()

	cloneBranch := strings.TrimSpace(iterationBranch)
	if cloneBranch == "" {
		cloneBranch = strings.TrimSpace(projectRepo.DefaultBranch)
	}
	repoCtx := RepositoryContext{
		RepoName:   resolveRepoWikiRepoName(projectRepo),
		RepoURL:    strings.TrimSpace(projectRepo.RepoURL),
		BranchName: strings.TrimSpace(cloneBranch),
	}
	cloneOpts := git.CloneOptions{
		URL:    projectRepo.RepoURL,
		Branch: bugmodel.ResolveBranch(cloneBranch),
		Auth:   *selection.Auth,
	}

	repo, err := git.NewRepository(cloneCtx, cloneOpts)
	if err != nil {
		logger.Errorf("[ADKAnalysis] 克隆仓库失败，尝试使用本地工作区: %v", err)
		localRepo, localErr := openMatchingLocalRepository(projectRepo.RepoURL, cloneBranch)
		if localErr != nil {
			logger.Errorf("[ADKAnalysis] 本地工作区回退失败: %v", localErr)
			return "", nil, nil, repoCtx
		}
		repo = localRepo
		logger.Infof("[ADKAnalysis] 使用本地工作区作为代码证据来源: url=%s branch=%s", projectRepo.RepoURL, cloneBranch)
	}

	defectText := defect.Title + " " + defect.Description
	retriever := s.buildRetrieverForProject(defect.Iteration.ProjectID)
	relatedFiles := s.findRelatedFiles(ctx, retriever, repo, defectText, 10)
	relatedFiles = prioritizeSourceFiles(relatedFiles)

	hasSourceFiles := false
	for _, f := range relatedFiles {
		ext := strings.ToLower(filepath.Ext(f))
		if ext == ".go" || ext == ".ts" || ext == ".tsx" || ext == ".js" || ext == ".jsx" || ext == ".vue" || ext == ".py" || ext == ".java" {
			hasSourceFiles = true
			break
		}
	}
	if !hasSourceFiles {
		sourceFiles := s.scanSourceFiles(repo)
		logger.Infof("[ADKAnalysis] 关键词检索未命中源码文件，已扫描仓库获取 %d 个源码文件", len(sourceFiles))
		relatedFiles = append(sourceFiles, relatedFiles...)
	}

	keywords := adkExtractKeywords(defectText)
	codeContext := adkBuildEvidenceContext(repo, relatedFiles, keywords)

	logger.Infof("[ADKAnalysis] git 代码检索完成: %d 个相关文件, codeContext=%d chars", len(relatedFiles), len(codeContext))
	for i, f := range relatedFiles {
		logger.Infof("[ADKAnalysis]   relatedFile[%d]: %s", i, f)
	}
	return codeContext, relatedFiles, repo, repoCtx
}

func resolveRepoWikiRepoName(projectRepo bugmodel.ProjectRepo) string {
	if name := strings.TrimSpace(projectRepo.Name); name != "" {
		return name
	}
	return normalizeRepoName(filepath.Base(strings.TrimSuffix(strings.TrimSpace(projectRepo.RepoURL), "/")))
}

func openMatchingLocalRepository(repoURL, branch string) (*git.Repository, error) {
	wd, err := os.Getwd()
	if err != nil {
		return nil, err
	}
	root, err := findGitRoot(wd)
	if err != nil {
		return nil, err
	}
	if !repoNamesMatch(root, repoURL) {
		return nil, fmt.Errorf("local git root %s does not match repo %s", root, repoURL)
	}
	return git.OpenLocalRepository(root, repoURL, branch)
}

func findGitRoot(start string) (string, error) {
	dir := start
	for {
		if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", fmt.Errorf("git root not found from %s", start)
		}
		dir = parent
	}
}

func repoNamesMatch(localRoot, repoURL string) bool {
	localName := normalizeRepoName(filepath.Base(localRoot))
	remoteName := normalizeRepoName(filepath.Base(strings.TrimSuffix(strings.TrimSpace(repoURL), "/")))
	return localName != "" && remoteName != "" && localName == remoteName
}

func normalizeRepoName(value string) string {
	value = strings.TrimSpace(strings.ToLower(value))
	value = strings.TrimSuffix(value, ".git")
	value = strings.ReplaceAll(value, "-", "_")
	return value
}

func prioritizeSourceFiles(files []string) []string {
	isSource := func(path string) bool {
		ext := strings.ToLower(filepath.Ext(path))
		switch ext {
		case ".go", ".ts", ".tsx", ".js", ".jsx", ".py", ".java", ".c", ".cpp", ".h", ".hpp", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".vue", ".svelte", ".css", ".scss", ".less":
			return true
		}
		return false
	}
	var sources, docs []string
	for _, f := range files {
		if isSource(f) {
			sources = append(sources, f)
		} else {
			docs = append(docs, f)
		}
	}
	return append(sources, docs...)
}

func (s *ADKAnalysisService) scanSourceFiles(repo *git.Repository) []string {
	const maxSourceFiles = 15
	allFiles, err := repo.ListFiles("")
	if err != nil {
		logger.Errorf("[ADKAnalysis] scanSourceFiles ListFiles 失败: %v", err)
		return nil
	}

	isSourceExt := func(ext string) bool {
		switch ext {
		case ".go", ".ts", ".tsx", ".js", ".jsx", ".py", ".java", ".c", ".cpp", ".h", ".hpp", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".vue", ".svelte":
			return true
		}
		return false
	}

	isPriorityDir := func(path string) bool {
		parts := strings.SplitN(path, "/", 2)
		if len(parts) < 2 {
			return false
		}
		top := parts[0]
		switch top {
		case "server", "web", "src", "internal", "app", "backend", "frontend", "packages":
			return true
		}
		return false
	}

	var prioritySources []string
	var otherSources []string

	for _, f := range allFiles {
		if isSourceExt(strings.ToLower(filepath.Ext(f))) {
			if isPriorityDir(f) {
				prioritySources = append(prioritySources, f)
			} else {
				otherSources = append(otherSources, f)
			}
		}
	}

	sort.Slice(prioritySources, func(i, j int) bool { return prioritySources[i] < prioritySources[j] })
	sort.Slice(otherSources, func(i, j int) bool { return otherSources[i] < otherSources[j] })

	result := prioritySources
	if len(result) < maxSourceFiles {
		remaining := maxSourceFiles - len(result)
		if remaining > len(otherSources) {
			remaining = len(otherSources)
		}
		result = append(result, otherSources[:remaining]...)
	} else {
		result = result[:maxSourceFiles]
	}

	return result
}

func (s *ADKAnalysisService) findRelatedFiles(ctx context.Context, r retrieval.Retriever, repo *git.Repository, text string, limit int) []string {
	if repo == nil || limit <= 0 || r == nil {
		return nil
	}
	evidences, err := r.Retrieve(ctx, retrieval.Query{
		Repo:     repo,
		Text:     text,
		Keywords: adkExtractKeywords(text),
		TopK:     limit,
	})
	if err != nil {
		logger.Errorf("[ADKAnalysis] 检索相关文件失败: %v", err)
		return nil
	}
	result := make([]string, 0, len(evidences))
	seen := make(map[string]struct{}, len(evidences))
	for _, evidence := range evidences {
		path := strings.TrimSpace(evidence.FilePath)
		if path == "" {
			continue
		}
		if _, ok := seen[path]; ok {
			continue
		}
		seen[path] = struct{}{}
		result = append(result, path)
		if len(result) >= limit {
			break
		}
	}
	return result
}

type adkEvidenceBlock struct {
	StartLine int
	EndLine   int
	Content   string
}

func adkBuildEvidenceContext(repo *git.Repository, relatedFiles, keywords []string) string {
	if repo == nil || len(relatedFiles) == 0 {
		return ""
	}
	limit := adkMaxEvidenceFiles
	if len(relatedFiles) < limit {
		limit = len(relatedFiles)
	}
	var b strings.Builder
	b.WriteString("以下是根据缺陷文本从仓库检索到的代码证据片段（含行号）：\n")
	sections := 0
	for i := 0; i < limit; i++ {
		path := relatedFiles[i]
		content, err := repo.ReadFile(path)
		if err != nil {
			logger.Errorf("读取文件失败: %v", err)
			continue
		}
		blocks, matchedKeywords := adkExtractEvidenceBlocks(content, keywords, adkMaxEvidenceBlocks, adkEvidenceLineRadius)
		if len(blocks) == 0 {
			continue
		}
		sections++
		b.WriteString(fmt.Sprintf("\n### 证据文件 %d: %s\n", sections, path))
		if len(matchedKeywords) > 0 {
			b.WriteString("- 命中关键词: " + strings.Join(matchedKeywords, ", ") + "\n")
		}
		for _, block := range blocks {
			b.WriteString(fmt.Sprintf("- 片段 L%d-L%d\n", block.StartLine, block.EndLine))
			b.WriteString("```text\n")
			b.WriteString(block.Content)
			b.WriteString("\n```\n")
		}
		if b.Len() >= maxContextChars {
			break
		}
	}
	context := strings.TrimSpace(b.String())
	if len(context) > maxContextChars {
		runes := []rune(context)
		if len(runes) > maxContextChars {
			context = string(runes[:maxContextChars])
		}
		context += "\n... (代码证据已截断)"
	}
	return context
}

func adkExtractEvidenceBlocks(content string, keywords []string, maxBlocks, radius int) ([]adkEvidenceBlock, []string) {
	lines := strings.Split(content, "\n")
	if len(lines) == 0 {
		return nil, nil
	}
	lowerKeywords := make([]string, 0, len(keywords))
	for _, keyword := range keywords {
		keyword = strings.TrimSpace(strings.ToLower(keyword))
		if keyword != "" {
			lowerKeywords = append(lowerKeywords, keyword)
		}
	}
	matchedLineIdx := make([]int, 0)
	for i, line := range lines {
		lower := strings.ToLower(line)
		for _, kw := range lowerKeywords {
			if strings.Contains(lower, kw) {
				matchedLineIdx = append(matchedLineIdx, i)
				break
			}
		}
	}
	if len(matchedLineIdx) == 0 {
		end := radius*2 + 1
		if end > len(lines) {
			end = len(lines)
		}
		blockLines := lines[:end]
		block := adkEvidenceBlock{
			StartLine: 1,
			EndLine:   end,
			Content:   strings.Join(blockLines, "\n"),
		}
		return []adkEvidenceBlock{block}, nil
	}
	covered := make(map[int]bool)
	matchedKeywords := make(map[string]bool)
	blocks := make([]adkEvidenceBlock, 0, maxBlocks)
	for _, lineIdx := range matchedLineIdx {
		if covered[lineIdx] {
			continue
		}
		start := lineIdx - radius
		if start < 0 {
			start = 0
		}
		end := lineIdx + radius + 1
		if end > len(lines) {
			end = len(lines)
		}
		for j := start; j < end; j++ {
			covered[j] = true
		}
		blockLines := lines[start:end]
		block := adkEvidenceBlock{
			StartLine: start + 1,
			EndLine:   end,
			Content:   strings.Join(blockLines, "\n"),
		}
		blocks = append(blocks, block)
		if len(blocks) >= maxBlocks {
			break
		}
	}
	for _, lineIdx := range matchedLineIdx {
		for _, kw := range lowerKeywords {
			if strings.Contains(strings.ToLower(lines[lineIdx]), kw) {
				matchedKeywords[kw] = true
				break
			}
		}
	}
	mk := make([]string, 0, len(matchedKeywords))
	for k := range matchedKeywords {
		mk = append(mk, k)
	}
	sort.Strings(mk)
	return blocks, mk
}

func adkExtractKeywords(text string) []string {
	replacer := strings.NewReplacer(
		"\n", " ", "\t", " ", "，", " ", "。", " ", "：", " ",
		":", " ", "；", " ", ";", " ", "（", " ", "）", " ",
		"(", " ", ")", " ", "[", " ", "]", " ", "{", " ", "}", " ",
		"-", " ", "－", " ", "—", " ", "_", " ",
	)
	originalText := strings.ToLower(strings.TrimSpace(text))
	text = replacer.Replace(text)
	stopWords := map[string]bool{"的": true, "是": true, "在": true, "和": true, "与": true, "或": true}
	seen := make(map[string]struct{})
	keywords := make([]string, 0)
	addKeyword := func(keyword string) {
		keyword = strings.TrimSpace(strings.ToLower(keyword))
		if keyword == "" || stopWords[keyword] {
			return
		}
		if len([]rune(keyword)) <= 1 && !strings.ContainsAny(keyword, "./_-") {
			return
		}
		if _, ok := seen[keyword]; ok {
			return
		}
		seen[keyword] = struct{}{}
		keywords = append(keywords, keyword)
	}
	for _, part := range strings.Fields(text) {
		addKeyword(part)
	}
	appendDomainKeywordAliases(originalText, addKeyword)
	return keywords
}

func appendDomainKeywordAliases(text string, add func(string)) {
	type aliasRule struct {
		contains []string
		aliases  []string
	}
	rules := []aliasRule{
		{
			contains: []string{"质量情报", "质量问题", "质量概览", "质量情报概览"},
			aliases:  []string{"quality", "insights", "quality_insights", "quality-insights", "qualityinsights"},
		},
		{
			contains: []string{"概览", "总览", "overview"},
			aliases:  []string{"overview", "getoverview"},
		},
		{
			contains: []string{"项目质量", "质量看板"},
			aliases:  []string{"projectqualityinsights", "qualityinsights"},
		},
	}
	for _, rule := range rules {
		for _, marker := range rule.contains {
			if strings.Contains(text, marker) {
				for _, alias := range rule.aliases {
					add(alias)
				}
				break
			}
		}
	}
}
