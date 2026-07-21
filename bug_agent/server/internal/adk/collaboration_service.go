package adk

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"bug-agent/internal/asyncx"
	bugmodel "bug-agent/internal/model"
	"bug-agent/pkg/logger"

	"google.golang.org/adk/agent"
	"google.golang.org/adk/session"
	"google.golang.org/genai"

	"gorm.io/gorm"
)

type ADKCollaborationService struct {
	db          *gorm.DB
	analysisSvc *ADKAnalysisService
}

func NewADKCollaborationService(db *gorm.DB, analysisSvc *ADKAnalysisService) (*ADKCollaborationService, error) {
	return &ADKCollaborationService{
		db:          db,
		analysisSvc: analysisSvc,
	}, nil
}

type StartCollaborationRequest struct {
	DefectID      uint     `json:"defectId"`
	AgentTypes    []string `json:"agentTypes"`
	TriggerUserID uint     `json:"triggerUserId,omitempty"`
}

func (s *ADKCollaborationService) StartCollaboration(ctx context.Context, req StartCollaborationRequest) (*bugmodel.CollaborationTask, error) {
	if len(req.AgentTypes) == 0 {
		req.AgentTypes = []string{"frontend", "backend"}
	}

	var defect bugmodel.Defect
	if err := s.db.Preload("Iteration").Preload("Reporter").First(&defect, req.DefectID).Error; err != nil {
		return nil, fmt.Errorf("defect not found: %w", err)
	}

	task := &bugmodel.CollaborationTask{
		DefectID:      req.DefectID,
		AgentTypes:    func() string { b, _ := json.Marshal(req.AgentTypes); return string(b) }(),
		Status:        bugmodel.CollaborationStatusRunning,
		TriggerUserID: req.TriggerUserID,
	}

	if err := s.db.Create(task).Error; err != nil {
		return nil, fmt.Errorf("create collaboration task: %w", err)
	}

	asyncx.Go(func() {
		defer func() {
			if r := recover(); r != nil {
				logger.Errorf("[ADKCollaboration] panic: %v", r)
				s.db.Model(task).Update("status", bugmodel.CollaborationStatusFailed)
			}
		}()

		bgCtx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
		defer cancel()

		s.executeParallelAnalysis(bgCtx, defect, req.AgentTypes, task)
	})

	return task, nil
}

func (s *ADKCollaborationService) executeParallelAnalysis(
	ctx context.Context,
	defect bugmodel.Defect,
	agentTypes []string,
	task *bugmodel.CollaborationTask,
) {
	type agentResult struct {
		agentType string
		result    *ADKAnalysisResult
		err       error
	}

	resultsCh := make(chan agentResult, len(agentTypes))
	var wg sync.WaitGroup

	for _, agentType := range agentTypes {
		wg.Add(1)
		asyncx.Go(func() {
			defer wg.Done()
			result, err := s.analysisSvc.PerformAnalysis(ctx, ADKAnalysisRequest{
				DefectID:         defect.ID,
				AgentTypes:       []string{agentType},
				SkipStatusUpdate: true,
			})
			resultsCh <- agentResult{agentType: agentType, result: result, err: err}
		})
	}

	asyncx.Go(func() {
		wg.Wait()
		close(resultsCh)
	})

	var agentResults []bugmodel.AgentResult
	for ar := range resultsCh {
		if ar.err != nil {
			logger.Errorf("[ADKCollaboration] agent %s failed: %v", ar.agentType, ar.err)
			agentResults = append(agentResults, bugmodel.AgentResult{
				AgentType: ar.agentType,
				Status:    "failed",
				ErrorMsg:  ar.err.Error(),
			})
			continue
		}

		var analysisMap map[string]interface{}
		if ar.result.Analysis != nil {
			if err := json.Unmarshal(ar.result.Analysis, &analysisMap); err != nil {
				logger.Errorf("[Collaboration] unmarshal analysis for %s: %v", ar.agentType, err)
				analysisMap = map[string]interface{}{"raw": string(ar.result.Analysis)}
			}
		}
		var solutionMap map[string]interface{}
		if ar.result.Solution != nil {
			if err := json.Unmarshal(ar.result.Solution, &solutionMap); err != nil {
				logger.Errorf("[Collaboration] unmarshal solution for %s: %v", ar.agentType, err)
				solutionMap = map[string]interface{}{"raw": string(ar.result.Solution)}
			}
		}

		agentResults = append(agentResults, bugmodel.AgentResult{
			AgentType: ar.agentType,
			Status:    "completed",
			Analysis:  analysisMap,
			Solution:  solutionMap,
		})
	}

	aggregated := s.aggregateResults(task, agentResults)
	taskStatus := bugmodel.CollaborationStatusCompleted
	completedCount := countCompletedAgentResults(agentResults)
	if completedCount == 0 {
		taskStatus = bugmodel.CollaborationStatusFailed
	}

	aggregatedJSON, err := json.Marshal(aggregated)
	if err != nil {
		logger.Errorf("[ADKCollaboration] marshal aggregated result: %v", err)
	} else {
		now := time.Now()
		if err := s.db.Model(task).Updates(map[string]interface{}{
			"status":       taskStatus,
			"result":       string(aggregatedJSON),
			"completed_at": now,
			"updated_at":   now,
		}).Error; err != nil {
			logger.Errorf("[ADKCollaboration] update task status: %v", err)
		}

		for _, ar := range agentResults {
			report := bugmodel.CollaborationReport{
				TaskID:    task.ID,
				AgentType: ar.AgentType,
				Status:    ar.Status,
			}
			if ar.Status == "completed" {
				now2 := time.Now()
				report.StartedAt = &now2
				report.CompletedAt = &now2
			} else {
				report.Error = ar.ErrorMsg
			}
			if err := s.db.Create(&report).Error; err != nil {
				logger.Errorf("[ADKCollaboration] create report failed: %v", err)
			}
		}
	}

	s.publishCollaborationComment(defect, task, aggregated)
}

func countCompletedAgentResults(agentResults []bugmodel.AgentResult) int {
	completedCount := 0
	for _, result := range agentResults {
		if result.Status == "completed" {
			completedCount++
		}
	}
	return completedCount
}

func (s *ADKCollaborationService) StartCollaborationWithPipeline(
	ctx context.Context,
	req StartCollaborationRequest,
	pipelineCfg CollaborationConfig,
) (*bugmodel.CollaborationTask, error) {
	if len(req.AgentTypes) == 0 {
		req.AgentTypes = []string{"frontend", "backend"}
	}

	var defect bugmodel.Defect
	if err := s.db.Preload("Iteration").Preload("Reporter").First(&defect, req.DefectID).Error; err != nil {
		return nil, fmt.Errorf("defect not found: %w", err)
	}

	task := &bugmodel.CollaborationTask{
		DefectID:      req.DefectID,
		AgentTypes:    func() string { b, _ := json.Marshal(req.AgentTypes); return string(b) }(),
		Status:        bugmodel.CollaborationStatusRunning,
		TriggerUserID: req.TriggerUserID,
	}
	if err := s.db.Create(task).Error; err != nil {
		return nil, fmt.Errorf("create collaboration task: %w", err)
	}

	pipeline, err := NewCollaborationPipeline(pipelineCfg)
	if err != nil {
		return nil, fmt.Errorf("NewCollaborationPipeline: %w", err)
	}

	userID := fmt.Sprintf("collab_user_%d", req.DefectID)
	sessionID := fmt.Sprintf("collab_%d_%d", req.DefectID, time.Now().UnixMilli())

	_, err = pipelineCfg.SessionSvc.Create(ctx, &session.CreateRequest{
		AppName:   pipelineCfg.AppName,
		UserID:    userID,
		SessionID: sessionID,
	})
	if err != nil {
		return nil, fmt.Errorf("session create: %w", err)
	}
	defer pipelineCfg.SessionSvc.Delete(ctx, &session.DeleteRequest{
		AppName: pipelineCfg.AppName, UserID: userID, SessionID: sessionID,
	})

	userMsg := &genai.Content{
		Role:  genai.RoleUser,
		Parts: []*genai.Part{{Text: fmt.Sprintf("对缺陷 #%d 进行协作分析", req.DefectID)}},
	}

	events := pipeline.Run(ctx, userID, sessionID, userMsg, agent.RunConfig{})

	asyncx.Go(func() {
		_, err := CollectEvents(events)
		if err != nil {
			logger.Errorf("[ADKCollaboration] pipeline collect events failed: %v", err)
			errJSON, _ := json.Marshal(map[string]string{"error": err.Error()})
			s.db.Model(task).Updates(map[string]interface{}{
				"status": bugmodel.CollaborationStatusFailed,
				"result": string(errJSON),
			})
			return
		}

		now := time.Now()
		s.db.Model(task).Updates(map[string]interface{}{
			"status":       bugmodel.CollaborationStatusCompleted,
			"completed_at": now,
			"updated_at":   now,
		})
	})

	return task, nil
}

func (s *ADKCollaborationService) aggregateResults(task *bugmodel.CollaborationTask, agents []bugmodel.AgentResult) *bugmodel.AggregatedReport {
	report := &bugmodel.AggregatedReport{
		TaskID:    task.ID,
		TaskCode:  task.TaskCode,
		Agents:    agents,
		Consensus: map[string]float64{},
		Timestamp: time.Now(),
	}

	completedCount := countCompletedAgentResults(agents)

	if completedCount == len(agents) && len(agents) > 0 {
		report.Consensus["overall"] = 1.0
		report.RiskLevel = "medium"
		report.Summary = fmt.Sprintf("%d个Agent完成分析，共识度100%%", completedCount)
		report.Recommendation = "建议综合各Agent分析结果进行修复"
	} else if completedCount > 0 {
		report.Consensus["overall"] = float64(completedCount) / float64(len(agents))
		report.RiskLevel = "medium"
		report.Summary = fmt.Sprintf("%d/%d个Agent完成分析", completedCount, len(agents))
		report.Recommendation = "部分Agent分析失败，建议重试或人工确认"
	} else {
		report.Consensus["overall"] = 0
		report.RiskLevel = "high"
		report.Summary = "所有Agent分析均失败"
		report.Recommendation = "建议检查AI配置后重试"
	}

	return report
}

func (s *ADKCollaborationService) publishCollaborationComment(defect bugmodel.Defect, task *bugmodel.CollaborationTask, aggregated *bugmodel.AggregatedReport) {
	title := "协作分析完成"
	if aggregated.Consensus["overall"] == 0 {
		title = "协作分析失败"
	}
	content := fmt.Sprintf("🤖 **%s**（共识度：%.0f%%）\n综合风险：%s\n%s\n建议：%s",
		title,
		aggregated.Consensus["overall"]*100,
		aggregated.RiskLevel,
		aggregated.Summary,
		aggregated.Recommendation)

	comment := bugmodel.Comment{
		DefectID:       defect.ID,
		Content:        content,
		AgentType:      "collaboration",
		IsAgentMessage: true,
	}
	comment.UserID = resolveCommentUserID(defect)
	if ensureCommentUserExists(s.db, comment.UserID) {
		if err := s.db.Create(&comment).Error; err != nil {
			logger.Errorf("[ADKCollaboration] create comment failed: %v", err)
		}
	}
}

func (s *ADKCollaborationService) GetCollaborationTask(taskID uint) (*bugmodel.CollaborationTask, error) {
	var task bugmodel.CollaborationTask
	if err := s.db.Preload("Defect").First(&task, taskID).Error; err != nil {
		return nil, err
	}
	return &task, nil
}

func (s *ADKCollaborationService) GetCollaborationTasksByDefect(defectID uint) ([]bugmodel.CollaborationTask, error) {
	var tasks []bugmodel.CollaborationTask
	if err := s.db.Where("defect_id = ?", defectID).Order("created_at DESC").Find(&tasks).Error; err != nil {
		return nil, err
	}
	return tasks, nil
}

func (s *ADKCollaborationService) GetAggregatedReport(taskID uint) (*bugmodel.AggregatedReport, error) {
	var task bugmodel.CollaborationTask
	if err := s.db.Preload("Reports").First(&task, taskID).Error; err != nil {
		return nil, err
	}

	var agents []bugmodel.AgentResult
	for _, r := range task.Reports {
		ar := bugmodel.AgentResult{
			AgentType: r.AgentType,
			Status:    r.Status,
		}
		if r.ReportID != nil {
			ar.ReportID = *r.ReportID
			var analysisReport bugmodel.AnalysisReport
			if err := s.db.First(&analysisReport, *r.ReportID).Error; err == nil {
				var analysisMap map[string]interface{}
				if err := json.Unmarshal([]byte(analysisReport.Analysis), &analysisMap); err != nil {
					logger.Errorf("[Collaboration] unmarshal analysis report %d: %v", *r.ReportID, err)
					analysisMap = map[string]interface{}{"raw": analysisReport.Analysis}
				}
				ar.Analysis = analysisMap
			}
		}
		if r.Error != "" {
			ar.ErrorMsg = r.Error
		}
		agents = append(agents, ar)
	}

	return s.aggregateResults(&task, agents), nil
}
