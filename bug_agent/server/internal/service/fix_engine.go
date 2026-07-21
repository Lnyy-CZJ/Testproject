package service

import (
	"bug-agent/internal/ai"
	"bug-agent/internal/asyncx"
	"bug-agent/internal/git"
	"bug-agent/internal/model"
	"bug-agent/internal/sse"
	"bug-agent/internal/vcs"
	"bug-agent/pkg/logger"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"gorm.io/gorm"
)

// FixService 自动修复服务
type FixService struct {
	db *gorm.DB
}

// NewFixService 创建修复服务
func NewFixService(db *gorm.DB) *FixService {
	return &FixService{db: db}
}

// FixRequest 修复请求
type FixRequest struct {
	FixTaskID    uint
	DefectID     uint
	GroupID      uint
	ReportID     uint
	AgentType    string
	TargetBranch string
	UserID       uint
}

// FixResult 修复结果
type FixResult struct {
	GroupID    uint
	TaskID     uint
	TaskCode   string
	Status     string
	Units      []FixUnitResult
	PlanJSON   json.RawMessage
	ResultJSON json.RawMessage
	PRURL      string
	Duration   time.Duration
	Error      string
}

type FixUnitResult struct {
	ID               uint   `json:"id"`
	TaskCode         string `json:"taskCode"`
	AgentType        string `json:"agentType"`
	AnalysisReportID uint   `json:"analysisReportId"`
	ProjectRepoID    uint   `json:"projectRepoId"`
	Status           string `json:"status"`
}

type fixExecutionUnit struct {
	report      model.AnalysisReport
	projectRepo model.ProjectRepo
}

// PerformAutoFix 执行完整的自动修复流程
func (s *FixService) PerformAutoFix(ctx context.Context, req FixRequest) (*FixResult, error) {
	return s.CreateAutoFixGroup(ctx, req)
}

func (s *FixService) CreateAutoFixGroup(ctx context.Context, req FixRequest) (*FixResult, error) {
	startTime := time.Now()
	requestedAgentType := strings.TrimSpace(req.AgentType)
	logger.Infof("[FixService] 开始聚合自动修复: 缺陷 #%d, AGENT=%s", req.DefectID, requestedAgentType)

	defect, err := s.getDefect(req.DefectID)
	if err != nil {
		return nil, fmt.Errorf("get defect failed: %w", err)
	}

	reports, err := s.getLatestAutoFixableAnalysisReports(req.DefectID, requestedAgentType)
	if err != nil {
		return nil, fmt.Errorf("get analysis reports failed: %w", err)
	}
	if len(reports) == 0 {
		return nil, gorm.ErrRecordNotFound
	}
	executionUnits, err := s.buildFixExecutionUnits(defect, reports)
	if err != nil {
		return nil, err
	}

	group := model.FixTaskGroup{
		TaskCode:     GenerateTaskCode(defect.Code),
		DefectID:     defect.ID,
		Status:       model.FixTaskStatusPlanning,
		TargetBranch: resolveTargetBranch("", req.TargetBranch, "main"),
		CreatedBy:    req.UserID,
	}
	units := make([]FixUnitResult, 0, len(executionUnits))
	tasks := make([]model.FixTask, 0, len(executionUnits))
	if err := s.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&group).Error; err != nil {
			return fmt.Errorf("create fix task group failed: %w", err)
		}
		for index, unit := range executionUnits {
			task, err := s.createFixTaskRecordWithRepo(tx, defect, unit.report, req, group.ID, index+1, unit.projectRepo.ID)
			if err != nil {
				return err
			}
			tasks = append(tasks, task)
			reportID := uint(0)
			if task.AnalysisReportID != nil {
				reportID = *task.AnalysisReportID
			}
			units = append(units, FixUnitResult{
				ID:               task.ID,
				TaskCode:         task.TaskCode,
				AgentType:        task.AgentType,
				AnalysisReportID: reportID,
				ProjectRepoID:    unit.projectRepo.ID,
				Status:           task.Status,
			})
		}
		return nil
	}); err != nil {
		return nil, err
	}

	resultStatus := group.Status
	if os.Getenv("BUG_AGENT_DISABLE_BACKGROUND_WORKERS") != "1" {
		now := time.Now()
		UpdateTaskGroupFields(s.db, group.ID, map[string]interface{}{"Status": model.FixTaskStatusExecuting, "StartedAt": now})
		resultStatus = model.FixTaskStatusExecuting
		for index := range tasks {
			task := tasks[index]
			unit := executionUnits[index]
			s.startFixTaskWorker(defect, unit.report, &task, req.TargetBranch, req.UserID, startTime)
		}
	}

	return &FixResult{
		GroupID:  group.ID,
		TaskCode: group.TaskCode,
		Status:   resultStatus,
		Units:    units,
	}, nil
}

func (s *FixService) buildFixExecutionUnits(defect model.Defect, reports []model.AnalysisReport) ([]fixExecutionUnit, error) {
	units := make([]fixExecutionUnit, 0, len(reports))
	seen := map[string]bool{}
	for _, report := range reports {
		agentType := strings.TrimSpace(report.AgentType)
		repos, err := ResolveDefectProjectReposForReport(s.db, defect, agentType, report)
		if err != nil {
			return nil, fmt.Errorf("解析修复目标代码仓库失败: %w", err)
		}
		for _, repo := range repos {
			key := fmt.Sprintf("%d:%d", report.ID, repo.repo.ID)
			if seen[key] {
				continue
			}
			seen[key] = true
			units = append(units, fixExecutionUnit{
				report:      report,
				projectRepo: repo.repo,
			})
		}
	}
	if len(units) == 0 {
		return nil, gorm.ErrRecordNotFound
	}
	return units, nil
}

func (s *FixService) createFixTaskRecordWithRepo(db *gorm.DB, defect model.Defect, report model.AnalysisReport, req FixRequest, groupID uint, unitIndex int, projectRepoID uint) (model.FixTask, error) {
	effectiveAgentType := strings.TrimSpace(report.AgentType)
	if effectiveAgentType == "" {
		effectiveAgentType = strings.TrimSpace(req.AgentType)
	}
	task := model.FixTask{
		TaskCode:         GenerateTaskCode(defect.Code),
		DefectID:         defect.ID,
		AnalysisReportID: &report.ID,
		AgentType:        effectiveAgentType,
		Status:           "planning",
		TargetBranch:     resolveTargetBranch("", req.TargetBranch, "main"),
	}
	if groupID > 0 {
		task.GroupID = &groupID
		task.TaskCode = GenerateUnitTaskCode(defect.Code, effectiveAgentType, unitIndex)
	}
	task.ProjectRepoID = &projectRepoID
	steps := []map[string]interface{}{
		{"step": 1, "action": "克隆代码仓库", "status": "pending"},
		{"step": 2, "action": "创建修复分支", "status": "pending"},
		{"step": 3, "action": "AI生成修复代码", "status": "pending"},
		{"step": 4, "action": "应用代码修改", "status": "pending"},
		{"step": 5, "action": "提交代码变更", "status": "pending"},
		{"step": 6, "action": "构建验证", "status": "pending"},
		{"step": 7, "action": "推送到远程仓库", "status": "pending"},
		{"step": 8, "action": "创建Pull Request", "status": "pending"},
	}

	planBytes, err := json.Marshal(steps)
	if err != nil {
		logger.Errorf("[FixService] marshal plan steps failed: %v", err)
	}
	task.Plan = string(planBytes)
	if err := db.Create(&task).Error; err != nil {
		return model.FixTask{}, fmt.Errorf("创建修复任务失败: %w", err)
	}
	return task, nil
}

func (s *FixService) startFixTaskWorker(defect model.Defect, report model.AnalysisReport, task *model.FixTask, targetBranch string, userID uint, startTime time.Time) {
	asyncx.Go(func() {
		defer func() {
			if r := recover(); r != nil {
				logger.Errorf("[FixService] Panic recovered: %v", r)
				if task.GroupID != nil && *task.GroupID > 0 {
					_ = s.finalizeFixTaskFailure(task.ID, fmt.Sprintf("panic: %v", r))
					s.refreshFixTaskGroupStatus(task.GroupID, defect.ID)
				} else {
					_ = s.finalizeFixFailure(task.ID, defect.ID, fmt.Sprintf("panic: %v", r))
				}
			}
		}()

		fixCtx, fixCancel := context.WithTimeout(asyncx.ShutdownContext(), 30*time.Minute)
		defer fixCancel()

		result, fixErr := s.executeFixWorkflow(fixCtx, defect, report, task, targetBranch, userID)

		if fixErr != nil {
			logger.Errorf("[FixService] 修复失败: %v", fixErr)
			if task.GroupID != nil && *task.GroupID > 0 {
				if err := s.finalizeFixTaskFailure(task.ID, fixErr.Error()); err != nil {
					logger.Errorf("[FixService] 回写修复失败状态失败: %v", err)
				}
				s.refreshFixTaskGroupStatus(task.GroupID, defect.ID)
			} else {
				if err := s.finalizeFixFailure(task.ID, defect.ID, fixErr.Error()); err != nil {
					logger.Errorf("[FixService] 回写修复失败状态失败: %v", err)
				}
			}
			s.publishFixFailureComment(defect, task, fixErr)
			return
		}

		if task.GroupID != nil && *task.GroupID > 0 {
			if err := s.finalizeFixTaskSuccess(task.ID, result); err != nil {
				logger.Errorf("[FixService] 回写修复成功状态失败: %v", err)
			}
			s.refreshFixTaskGroupStatus(task.GroupID, defect.ID)
		} else {
			if err := s.finalizeFixSuccess(task.ID, defect.ID, result); err != nil {
				logger.Errorf("[FixService] 回写修复成功状态失败: %v", err)
			}
		}

		s.publishFixComment(defect, result)

		logger.Infof("[FixService] 修复完成: 任务=%s, PR=%s, 耗时=%v",
			task.TaskCode, task.PRURL, time.Since(startTime))
	})
}

// executeFixWorkflow 执行修复工作流
func (s *FixService) executeFixWorkflow(
	ctx context.Context,
	defect model.Defect,
	report model.AnalysisReport,
	task *model.FixTask,
	preferredBranch string,
	operatorID uint,
) (*FixResult, error) {

	startTime := time.Now() // 修复：添加startTime定义

	var steps []map[string]interface{}
	if err := json.Unmarshal([]byte(task.Plan), &steps); err != nil {
		logger.Errorf("[FixService] unmarshal plan failed for task %d: %v", task.ID, err)
		return nil, fmt.Errorf("parse fix plan failed: %w", err)
	}
	UpdateTaskFields(s.db, task.ID, map[string]interface{}{"Status": model.FixTaskStatusExecuting})

	// Step 1: 克隆代码仓库
	UpdateStepStatus(steps, 0, "executing")
	SavePlanToDB(s.db, task.ID, steps)
	repo, projectRepo, repoAuth, iterationBranch, defectRepoID, err := s.cloneRepository(ctx, defect, task.ID, task.ProjectRepoID, task.AgentType, preferredBranch, operatorID)
	if err != nil {
		UpdateStepStatus(steps, 0, "failed")
		SavePlanToDB(s.db, task.ID, steps)
		return nil, fmt.Errorf("clone repository failed: %w", err)
	}
	defer func() {
		asyncx.Go(func() {
			s.cleanupTaskRepository(repo, defectRepoID)
		})
	}()

	task.TargetBranch = resolveTargetBranch(iterationBranch, preferredBranch, projectRepo.DefaultBranch)
	UpdateTaskFields(s.db, task.ID, map[string]interface{}{
		"TargetBranch": task.TargetBranch,
	})

	UpdateStepStatus(steps, 0, "completed")
	SavePlanToDB(s.db, task.ID, steps)

	// Step 2: 创建修复分支
	UpdateStepStatus(steps, 1, "executing")
	SavePlanToDB(s.db, task.ID, steps)
	fixBranch, err := repo.CreateFixBranch(defect.Code, int(task.ID))
	if err != nil {
		UpdateStepStatus(steps, 1, "failed")
		SavePlanToDB(s.db, task.ID, steps)
		return nil, fmt.Errorf("create branch failed: %w", err)
	}
	task.FixBranch = fixBranch
	UpdateTaskFields(s.db, task.ID, map[string]interface{}{
		"FixBranch": task.FixBranch,
	})

	UpdateStepStatus(steps, 1, "completed")
	SavePlanToDB(s.db, task.ID, steps)

	// Step 3-4: AI生成并应用修复代码
	UpdateStepStatus(steps, 2, "executing")
	UpdateStepStatus(steps, 3, "executing")
	SavePlanToDB(s.db, task.ID, steps)

	configs, err := listUsableProjectAIConfigs(s.db, defect.Iteration.ProjectID)
	if err != nil {
		UpdateStepStatus(steps, 2, "failed")
		UpdateStepStatus(steps, 3, "failed")
		SavePlanToDB(s.db, task.ID, steps)
		return nil, fmt.Errorf("resolve AI configs failed: %w", err)
	}

	var (
		fixPlan     *ai.FixPlan
		codeGen     *ai.CodeGenerator
		generateErr error
		noChangeErr error
	)
	for index, cfg := range configs {
		attemptStart := time.Now()
		aiClient, clientErr := ai.NewAIClient(cfg.Provider, cfg.APIKey, cfg.APIEndpoint, cfg.ModelName)
		if clientErr != nil {
			// 客户端创建失败没有实际 AI token 消耗，不写入 AITokenUsage。
			RecordAITokenUsage(s.db, model.AITokenUsage{
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
		codeGen = ai.NewCodeGenerator(aiClient)

		analysisInput := buildRepoScopedAnalysisInput(report, *projectRepo)

		plan, metrics, planErr := codeGen.GenerateFixWithMetrics(ctx, analysisInput, repo)
		isFinal := index == len(configs)-1 || planErr == nil
		if planErr == nil && metrics.TotalTokens <= 0 {
			planBytes, _ := json.Marshal(plan)
			estimatedUsage := EstimateTokenUsageFromText(string(analysisInput), string(planBytes))
			metrics.PromptTokens = estimatedUsage.PromptTokens
			metrics.CompletionTokens = estimatedUsage.CompletionTokens
			metrics.TotalTokens = estimatedUsage.TotalTokens
		}
		estimatedCost := EstimateAICostUSD(cfg.Provider, cfg.ModelName, ai.Usage{
			PromptTokens:     metrics.PromptTokens,
			CompletionTokens: metrics.CompletionTokens,
			TotalTokens:      metrics.TotalTokens,
		})
		if planErr == nil {
			fixPlan = plan
			task.AIRiskSummary = report.RiskSummary
			task.AIValidationSuggestions = report.ValidationSuggestions
			UpdateTaskFields(s.db, task.ID, map[string]interface{}{
				"AIRiskSummary":           task.AIRiskSummary,
				"AIValidationSuggestions": task.AIValidationSuggestions,
			})
			// 记录成功的 AITokenUsage
			RecordAITokenUsage(s.db, model.AITokenUsage{
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
			break
		}
		generateErr = planErr
		// 记录失败的 AITokenUsage
		RecordAITokenUsage(s.db, model.AITokenUsage{
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
		if ai.IsNoApplicableCodeChanges(planErr) {
			noChangeErr = planErr
			break
		}
	}

	if fixPlan == nil {
		if noChangeErr != nil {
			reason := noChangeErr.Error()
			UpdateStepStatus(steps, 2, "warning")
			UpdateStepStatus(steps, 3, "warning")
			UpdateStepError(steps, 2, reason)
			UpdateStepError(steps, 3, reason)
			markRemainingFixStepsSkipped(steps, 4, "skipped: no applicable code changes")
			SavePlanToDB(s.db, task.ID, steps)
			result := buildNoChangeFixResult(task.TaskCode, steps, map[string]interface{}{
				"noChanges": true,
				"reason":    reason,
			}, time.Since(startTime))
			return result, nil
		}
		UpdateStepStatus(steps, 2, "failed")
		UpdateStepStatus(steps, 3, "failed")
		SavePlanToDB(s.db, task.ID, steps)
		if generateErr != nil {
			return nil, fmt.Errorf("generate fix failed: %w", generateErr)
		}
		return nil, fmt.Errorf("generate fix failed: no usable AI config")
	}

	changedFiles := collectFixPlanChangedFiles(fixPlan)
	baselineBuildResult, baselineBuildErr := repo.RunBuild(changedFiles)
	if baselineBuildErr != nil {
		logger.Warnf("[FixService] Baseline build verification error: %v", baselineBuildErr)
	} else if baselineBuildResult != nil && !baselineBuildResult.Skipped && !baselineBuildResult.Success {
		logger.Warnf("[FixService] Baseline build verification already failing: %s", baselineBuildResult.Output)
	}

	var applyErrors []string
	for i, step := range fixPlan.Steps {
		if step.CodeChange != nil {
			err := codeGen.ApplyChange(repo, step.CodeChange)
			if err != nil {
				step.Status = "failed"
				step.Error = err.Error()
				applyErrors = append(applyErrors, fmt.Sprintf("%s: %v", step.CodeChange.FilePath, err))
			} else {
				step.Status = "completed"
			}
			fixPlan.Steps[i] = step
		} else {
			fixPlan.Steps[i].Status = "completed"
		}
	}
	if len(applyErrors) > 0 {
		errorMessage := strings.Join(applyErrors, "\n")
		UpdateStepStatus(steps, 2, "completed")
		UpdateStepStatus(steps, 3, "failed")
		UpdateStepError(steps, 3, errorMessage)
		SavePlanToDB(s.db, task.ID, steps)
		return nil, fmt.Errorf("apply fix failed: %s", errorMessage)
	}

	UpdateStepStatus(steps, 2, "completed")
	UpdateStepStatus(steps, 3, "completed")
	SavePlanToDB(s.db, task.ID, steps)

	// Step 6: 构建验证
	UpdateTaskFields(s.db, task.ID, map[string]interface{}{"Status": model.FixTaskStatusTesting})
	UpdateStepStatus(steps, 5, "executing")
	SavePlanToDB(s.db, task.ID, steps)

	buildResult, buildErr := repo.RunBuild(changedFiles)
	if buildErr != nil {
		logger.Errorf("[FixService] Build verification error: %v", buildErr)
		UpdateStepStatus(steps, 5, "failed")
		UpdateStepError(steps, 5, buildErr.Error())
		SavePlanToDB(s.db, task.ID, steps)
		return nil, fmt.Errorf("build verification failed: %w", buildErr)
	} else if buildResult.Skipped {
		logger.Infof("[FixService] Build verification skipped: %s", buildResult.SkipReason)
		UpdateStepStatus(steps, 5, buildSkippedStepStatus(buildResult))
		UpdateStepError(steps, 5, buildSkippedMessage(buildResult))
		SavePlanToDB(s.db, task.ID, steps)
		if isBuildSkippedFatal(buildResult) {
			return nil, fmt.Errorf("build verification failed: %s", buildSkippedMessage(buildResult))
		}
	} else if buildResult.Success {
		logger.Infof("[FixService] Build verification passed: %s (%dms)", buildResult.Command, buildResult.Duration)
		UpdateStepStatus(steps, 5, "completed")
	} else {
		logger.Errorf("[FixService] Build verification failed: %s", buildResult.Output)
		errorMessage := buildResult.Output
		if baselineBuildResult != nil && !baselineBuildResult.Skipped && !baselineBuildResult.Success {
			errorMessage = fmt.Sprintf("target build was already failing before applying fix\n\nBaseline:\n%s\n\nAfter fix:\n%s", baselineBuildResult.Output, buildResult.Output)
			UpdateStepStatus(steps, 5, "failed")
			UpdateStepError(steps, 5, errorMessage)
			SavePlanToDB(s.db, task.ID, steps)
			return nil, fmt.Errorf("build verification failed: %s", errorMessage)
		}
		UpdateStepStatus(steps, 5, "failed")
		UpdateStepError(steps, 5, errorMessage)
		SavePlanToDB(s.db, task.ID, steps)
		return nil, fmt.Errorf("build verification failed: %s", errorMessage)
	}
	SavePlanToDB(s.db, task.ID, steps)

	// Step 5: 提交代码
	UpdateStepStatus(steps, 4, "executing")
	SavePlanToDB(s.db, task.ID, steps)

	commitMsg := fmt.Sprintf("fix(BUG-%s): Auto-fix by BugAgent\n\n%s",
		defect.Code,
		GenerateCommitDescription(fixPlan))

	commitHash, err := repo.Commit(commitMsg)
	if err != nil {
		UpdateStepStatus(steps, 4, "failed")
		UpdateStepError(steps, 4, err.Error())
		SavePlanToDB(s.db, task.ID, steps)
		return nil, fmt.Errorf("commit failed: %w", err)
	}

	UpdateStepStatus(steps, 4, "completed")
	SavePlanToDB(s.db, task.ID, steps)

	// Step 7: 推送到远程
	UpdateStepStatus(steps, 6, "executing")
	SavePlanToDB(s.db, task.ID, steps)

	err = repo.Push(repoAuth)
	if err != nil {
		UpdateStepStatus(steps, 6, "failed")
		SavePlanToDB(s.db, task.ID, steps)
		return nil, fmt.Errorf("push failed: %w", err)
	}

	UpdateStepStatus(steps, 6, "completed")
	SavePlanToDB(s.db, task.ID, steps)
	s.saveFixCheckpoint(task.ID, map[string]interface{}{
		"commitHash":        commitHash,
		"branch":            fixBranch,
		"pushed":            true,
		"codeChanges":       extractCodeChanges(fixPlan),
		"buildVerification": buildVerificationResult(buildResult),
	})

	// Step 8: 创建PR/MR
	UpdateStepStatus(steps, 7, "executing")
	SavePlanToDB(s.db, task.ID, steps)

	prURL, prNumber, err := s.createPullRequest(projectRepo.RepoURL, fixBranch, task.TargetBranch, defect)
	if err != nil {
		logger.Errorf("[FixService] Create PR failed: %v", err)
		prURL = ""
		prNumber = ""
		UpdateStepStatus(steps, 7, "failed")
		UpdateStepError(steps, 7, err.Error())
		SavePlanToDB(s.db, task.ID, steps)
		return nil, fmt.Errorf("create pull request failed: %w", err)
	} else {
		UpdateStepStatus(steps, 7, "completed")
		if prNumber != "" {
			if err := s.db.Model(&model.FixTask{}).Where("id = ?", task.ID).Update("PRNumber", prNumber).Error; err != nil {
				logger.Errorf("[FixEngine] update pr_number failed: taskID=%d err=%v", task.ID, err)
			}
		}
	}
	SavePlanToDB(s.db, task.ID, steps)

	resultJSON := map[string]interface{}{
		"commitHash":  commitHash,
		"branch":      fixBranch,
		"prURL":       prURL,
		"codeChanges": extractCodeChanges(fixPlan),
	}
	if buildResult != nil {
		resultJSON["buildVerification"] = buildVerificationResult(buildResult)
	}
	resultBytes, err := json.Marshal(resultJSON)
	if err != nil {
		logger.Errorf("[FixService] marshal result JSON failed: %v", err)
	}
	finalPlanBytes := MarshalFixPlanSteps(steps)
	finalStatus := resolveFinalFixStatus(steps)

	return &FixResult{
		TaskCode:   task.TaskCode,
		Status:     finalStatus,
		PlanJSON:   json.RawMessage(finalPlanBytes),
		ResultJSON: resultBytes,
		PRURL:      prURL,
		Duration:   time.Since(startTime),
	}, nil
}

// cloneRepository 克隆代码仓库
func (s *FixService) cloneRepository(ctx context.Context, defect model.Defect, taskID uint, projectRepoID *uint, agentType, preferredBranch string, operatorID uint) (*git.Repository, *model.ProjectRepo, *git.Auth, string, *uint, error) {
	var selection *DefectRepositorySelection
	var err error
	if projectRepoID != nil && *projectRepoID > 0 {
		selection, err = ResolveDefectRepositorySelectionByRepoID(s.db, defect, *projectRepoID, agentType, operatorID)
	} else {
		selection, err = ResolveDefectRepositorySelection(s.db, defect, agentType, operatorID)
	}
	if err != nil {
		return nil, nil, nil, "", nil, err
	}

	projectRepo := selection.ProjectRepo
	repoAuth := selection.Auth
	iterationBranch := selection.IterationBranch
	targetBranch := resolveTargetBranch(iterationBranch, preferredBranch, projectRepo.DefaultBranch)
	localPath := buildDefectRepoPath(defect.ID, taskID, projectRepo.RepoURL)
	if err := os.RemoveAll(localPath); err != nil {
		return nil, nil, nil, "", nil, fmt.Errorf("cleanup previous defect repo path failed: %w", err)
	}
	if err := os.MkdirAll(filepath.Dir(localPath), 0o755); err != nil {
		return nil, nil, nil, "", nil, fmt.Errorf("create defect repo parent failed: %w", err)
	}

	repo, err := git.CloneToDir(ctx, localPath, git.CloneOptions{
		URL:    projectRepo.RepoURL,
		Branch: targetBranch,
		Auth:   *repoAuth,
	})
	if err != nil {
		return nil, nil, nil, "", nil, err
	}

	defectRepo := model.DefectRepo{
		DefectID:  defect.ID,
		ProjectID: projectRepo.ProjectID,
		RepoURL:   projectRepo.RepoURL,
		Branch:    targetBranch,
		LocalPath: localPath,
		Status:    "active",
		FixTaskID: &taskID,
	}
	if err := s.db.Create(&defectRepo).Error; err != nil {
		repo.Cleanup()
		return nil, nil, nil, "", nil, fmt.Errorf("create defect repo record failed: %w", err)
	}
	if err := s.db.Model(&model.FixTask{}).Where("id = ?", taskID).Updates(map[string]interface{}{
		"defect_repo_id":  defectRepo.ID,
		"project_repo_id": projectRepo.ID,
	}).Error; err != nil {
		repo.Cleanup()
		return nil, nil, nil, "", nil, fmt.Errorf("link defect repo to fix task failed: %w", err)
	}
	defectRepoID := defectRepo.ID

	return repo, &projectRepo, repoAuth, iterationBranch, &defectRepoID, nil
}

func (s *FixService) cleanupTaskRepository(repo *git.Repository, defectRepoID *uint) {
	if repo == nil {
		return
	}
	if err := repo.Cleanup(); err != nil {
		logger.Errorf("[FixService] cleanup repository failed: %v", err)
		return
	}
	if defectRepoID == nil {
		return
	}
	now := time.Now()
	if err := s.db.Model(&model.DefectRepo{}).Where("id = ?", *defectRepoID).Updates(map[string]interface{}{
		"status":     "deleted",
		"deleted_at": now,
	}).Error; err != nil {
		logger.Errorf("[FixService] update defect repo cleanup status failed: %v", err)
	}
}

func buildDefectRepoPath(defectID, taskID uint, repoURL string) string {
	sum := sha256.Sum256([]byte(strings.TrimSpace(repoURL)))
	repoHash := hex.EncodeToString(sum[:])[:8]
	baseDir := strings.TrimSpace(os.Getenv("BUG_AGENT_REPO_BASE_DIR"))
	if baseDir == "" {
		baseDir = "/tmp/bug-agent/repos"
	}
	taskPart := "task-0"
	if taskID > 0 {
		taskPart = fmt.Sprintf("task-%d", taskID)
	}
	return filepath.Join(baseDir, "defects", fmt.Sprintf("%d", defectID), taskPart, repoHash)
}

// createPullRequest 创建Pull Request
func (s *FixService) createPullRequest(repoURL, fixBranch, baseBranch string, defect model.Defect) (string, string, error) {
	provider, ownerRepo, baseURL := vcs.DetectVCSProvider(repoURL)
	if strings.TrimSpace(baseBranch) == "" {
		baseBranch = "main"
	}

	prTitle := fmt.Sprintf("fix(BUG-%s): Auto-fix for \"%s\"", defect.Code, defect.Title)
	prDescription := fmt.Sprintf("## Auto-fix by BugAgent 🤖\n\n**缺陷编号**: BUG-%s\n**缺陷标题**: %s\n**AGENT类型**: %s\n\n### 修复内容：\n此PR由BugAgent AI自动生成。\n\n### 原始缺陷描述：\n%s\n---\n*由BugAgent自动创建于 %s*",
		defect.Code,
		defect.Title,
		defect.Type,
		defect.Description,
		time.Now().Format("2006-01-02 15:04:05"),
	)

	vcsToken := s.resolveVCSToken(defect)

	switch provider {
	case "github":
		client := vcs.NewGitHubClient(vcsToken)
		parts := strings.Split(ownerRepo, "/")
		if len(parts) != 2 {
			return "", "", fmt.Errorf("invalid owner/repo format: %s", ownerRepo)
		}
		pr, err := client.CreatePR(parts[0], parts[1], &vcs.PullRequest{
			Title:       prTitle,
			Description: prDescription,
			HeadBranch:  fixBranch,
			BaseBranch:  baseBranch,
		})
		if err != nil {
			return "", "", err
		}
		return pr.URL, fmt.Sprintf("%d", pr.Number), nil

	case "gitlab":
		client := vcs.NewGitLabClient(vcsToken, baseURL)
		pr, err := client.CreatePR(ownerRepo, &vcs.PullRequest{
			Title:       prTitle,
			Description: prDescription,
			HeadBranch:  fixBranch,
			BaseBranch:  baseBranch,
		})
		if err != nil {
			return "", "", err
		}
		return pr.WebURL, fmt.Sprintf("%d", pr.IID), nil

	default:
		return "", "", fmt.Errorf("unsupported VCS provider: %s", provider)
	}
}

func (s *FixService) resolveVCSToken(defect model.Defect) string {
	var iteration model.Iteration
	if err := s.db.Select("id, project_id").Where("id = ?", defect.IterationID).First(&iteration).Error; err != nil {
		return ""
	}

	var iterationRepos []model.IterationRepo
	if err := s.db.Where("iteration_id = ?", defect.IterationID).Find(&iterationRepos).Error; err != nil {
		logger.Errorf("[FixService] query iteration repos for VCS token failed: iterationID=%d err=%v", defect.IterationID, err)
	}
	if len(iterationRepos) == 0 || iterationRepos[0].RepoID == nil {
		return ""
	}

	var projectRepo model.ProjectRepo
	if err := s.db.First(&projectRepo, *iterationRepos[0].RepoID).Error; err != nil {
		return ""
	}

	if projectRepo.CredentialID != nil && *projectRepo.CredentialID > 0 {
		auth, _, err := LoadGitAuthFromCredential(s.db, *projectRepo.CredentialID)
		if err == nil && auth != nil {
			if strings.TrimSpace(auth.Token) != "" {
				return auth.Token
			}
			if strings.TrimSpace(auth.Password) != "" {
				return auth.Password
			}
		}
	}

	return ""
}

func parseUsernamePassword(content string) (string, string) {
	var payload struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if strings.HasPrefix(content, "{") {
		if err := json.Unmarshal([]byte(content), &payload); err == nil {
			return strings.TrimSpace(payload.Username), payload.Password
		}
	}

	parts := strings.SplitN(content, ":", 2)
	if len(parts) == 2 {
		return strings.TrimSpace(parts[0]), parts[1]
	}
	return "", ""
}

func resolveTargetBranch(iterationBranch, preferred, fallback string) string {
	branch := strings.TrimSpace(iterationBranch)
	if branch != "" {
		return branch
	}
	branch = strings.TrimSpace(preferred)
	if branch != "" {
		return branch
	}
	branch = strings.TrimSpace(fallback)
	if branch != "" {
		return branch
	}
	return "main"
}

func matchAgentType(agentTypesRaw, agentType string) bool {
	agentType = strings.TrimSpace(agentType)
	if agentType == "" || strings.TrimSpace(agentTypesRaw) == "" {
		return false
	}

	for _, item := range strings.Split(agentTypesRaw, ",") {
		if strings.TrimSpace(item) == agentType {
			return true
		}
	}
	return false
}

func sourceTypeProviders(sourceType string) []string {
	switch strings.TrimSpace(sourceType) {
	case "github":
		return []string{"github", "generic"}
	case "gitlab":
		return []string{"gitlab", "generic"}
	case "gitea":
		return []string{"gitea", "generic"}
	default:
		return []string{"generic", "custom", "github", "gitlab", "gitea"}
	}
}

// publishFixComment 发布修复完成评论
func (s *FixService) publishFixComment(defect model.Defect, result *FixResult) {
	var changes []map[string]string
	noChanges := result != nil && result.Status == model.FixTaskStatusNoChanges
	var noChangeReason string
	if len(result.ResultJSON) > 0 {
		var resultData map[string]interface{}
		if err := json.Unmarshal(result.ResultJSON, &resultData); err == nil {
			if value, ok := resultData["noChanges"].(bool); ok && value {
				noChanges = true
			}
			if value, ok := resultData["reason"].(string); ok {
				noChangeReason = strings.TrimSpace(value)
			}
			if cc, ok := resultData["codeChanges"].([]interface{}); ok {
				for _, c := range cc {
					if m, ok := c.(map[string]string); ok {
						changes = append(changes, m)
					}
				}
			}
		}
	}

	var body strings.Builder
	title := "🔧 **自动修复完成**"
	if noChanges {
		title = "🔧 **自动修复无需变更**"
	}
	body.WriteString(fmt.Sprintf("%s\n\n**任务编号**: %s\n**耗时**: %.1f 秒\n",
		title,
		result.TaskCode,
		result.Duration.Seconds()))

	if noChanges {
		body.WriteString("\n**结果**: 当前代码已满足修复要求，未生成代码变更，未推送分支，未创建 PR。\n")
		if noChangeReason != "" {
			body.WriteString(fmt.Sprintf("\n**原因**: %s\n", noChangeReason))
		}
	} else if len(changes) > 0 {
		body.WriteString("\n**修改文件**:\n")
		for _, c := range changes {
			fp := c["filePath"]
			desc := c["description"]
			if fp != "" {
				body.WriteString(fmt.Sprintf("- `%s`", fp))
				if desc != "" {
					body.WriteString(fmt.Sprintf(": %s", desc))
				}
				body.WriteString("\n")
			}
		}
	}

	if result.PRURL != "" {
		body.WriteString(fmt.Sprintf("\n**PR链接**: [%s](%s)\n", result.PRURL, result.PRURL))
	}

	if result.PRURL != "" {
		body.WriteString("\n> ⚠️ 请人工审核后合并此PR。")
	} else if !noChanges {
		body.WriteString("\n> ⚠️ 未创建 PR，请查看任务结果确认是否需要人工处理。")
	}

	comment := model.Comment{
		DefectID:       defect.ID,
		Content:        sanitizeCommentContent(body.String()),
		IsAgentMessage: true,
	}
	comment.UserID = resolveCommentUserID(defect)
	if !ensureCommentUserExists(s.db, comment.UserID) {
		logger.Errorf("[FixService] 跳过发布修复评论: actor user not found (defect=%d user=%d)", defect.ID, comment.UserID)
		return
	}

	if err := s.db.Create(&comment).Error; err != nil {
		logger.Errorf("[FixService] 发布修复评论失败: %v", err)
	}
}

// 辅助函数
func UpdateStepStatus(steps []map[string]interface{}, index int, status string) {
	if index < len(steps) {
		steps[index]["status"] = status
	}
}

func UpdateStepError(steps []map[string]interface{}, index int, errText string) {
	if index < len(steps) {
		steps[index]["error"] = errText
	}
}

func SavePlanToDB(db *gorm.DB, taskID uint, steps []map[string]interface{}) {
	planStr := string(MarshalFixPlanSteps(steps))
	if err := db.Model(&model.FixTask{}).Where("id = ?", taskID).Update("Plan", planStr).Error; err != nil {
		logger.Errorf("[FixEngine] SavePlanToDB failed: taskID=%d err=%v", taskID, err)
		return
	}
	notifyFixTaskPlanProgress(db, taskID, steps)
}

func UpdateTaskFields(db *gorm.DB, taskID uint, updates map[string]interface{}) {
	if len(updates) == 0 {
		return
	}
	if err := db.Model(&model.FixTask{}).Where("id = ?", taskID).Updates(updates).Error; err != nil {
		logger.Errorf("[FixEngine] UpdateTaskFields failed: taskID=%d err=%v", taskID, err)
	}
}

func UpdateTaskGroupFields(db *gorm.DB, groupID uint, updates map[string]interface{}) {
	if groupID == 0 || len(updates) == 0 {
		return
	}
	if err := db.Model(&model.FixTaskGroup{}).Where("id = ?", groupID).Updates(updates).Error; err != nil {
		logger.Errorf("[FixEngine] UpdateTaskGroupFields failed: groupID=%d err=%v", groupID, err)
	}
}

func notifyFixTaskPlanProgress(db *gorm.DB, taskID uint, steps []map[string]interface{}) {
	if sse.Notifier == nil {
		return
	}
	var task model.FixTask
	if err := db.Select("id, group_id, task_code, defect_id, agent_type, status").First(&task, taskID).Error; err != nil {
		logger.Errorf("[FixEngine] query fix task for progress SSE failed: taskID=%d err=%v", taskID, err)
		return
	}
	sse.Notifier.NotifyFixTaskPlanProgress(task.DefectID, task.GroupID, task.ID, task.TaskCode, task.AgentType, task.Status, steps)
}

func MarshalFixPlanSteps(steps []map[string]interface{}) json.RawMessage {
	bytes, err := json.Marshal(steps)
	if err != nil {
		logger.Errorf("[FixService] marshal fix plan steps failed: %v", err)
	}
	return bytes
}

func collectFixPlanChangedFiles(plan *ai.FixPlan) []string {
	if plan == nil {
		return nil
	}
	files := make([]string, 0, len(plan.Steps))
	seen := map[string]bool{}
	for _, step := range plan.Steps {
		if step.CodeChange == nil || step.CodeChange.FilePath == "" {
			continue
		}
		if seen[step.CodeChange.FilePath] {
			continue
		}
		seen[step.CodeChange.FilePath] = true
		files = append(files, step.CodeChange.FilePath)
	}
	return files
}

func buildWarningFixResult(taskCode string, steps []map[string]interface{}, payload map[string]interface{}, duration time.Duration) *FixResult {
	resultBytes, err := json.Marshal(payload)
	if err != nil {
		logger.Errorf("[FixService] marshal warning result JSON failed: %v", err)
	}
	return &FixResult{
		TaskCode:   taskCode,
		Status:     model.FixTaskStatusCompletedWithWarnings,
		PlanJSON:   MarshalFixPlanSteps(steps),
		ResultJSON: resultBytes,
		Duration:   duration,
	}
}

func buildNoChangeFixResult(taskCode string, steps []map[string]interface{}, payload map[string]interface{}, duration time.Duration) *FixResult {
	result := buildWarningFixResult(taskCode, steps, payload, duration)
	result.Status = model.FixTaskStatusNoChanges
	return result
}

func markRemainingFixStepsSkipped(steps []map[string]interface{}, startIndex int, reason string) {
	for index := startIndex; index < len(steps); index++ {
		status, _ := steps[index]["status"].(string)
		if status != "" && status != "pending" {
			continue
		}
		steps[index]["status"] = "warning"
		if reason != "" {
			steps[index]["error"] = reason
		}
	}
}

func buildSkippedStepStatus(result *git.BuildResult) string {
	if isBuildSkippedFatal(result) {
		return "failed"
	}
	return "warning"
}

func isBuildSkippedFatal(result *git.BuildResult) bool {
	return result != nil && result.SkipReason == "missing_tool"
}

func resolveFinalFixStatus(steps []map[string]interface{}) string {
	for _, step := range steps {
		if status, _ := step["status"].(string); status == "warning" {
			return model.FixTaskStatusCompletedWithWarnings
		}
	}
	return model.FixTaskStatusCompleted
}

func buildSkippedMessage(result *git.BuildResult) string {
	if result == nil {
		return "build verification skipped"
	}
	switch result.SkipReason {
	case "missing_tool":
		return strings.TrimSpace("build verification skipped: missing build tool\n" + result.Output)
	case "no_build_target":
		return "build verification skipped: no recognized build target"
	default:
		return strings.TrimSpace("build verification skipped: " + result.SkipReason + "\n" + result.Output)
	}
}

func extractCodeChanges(plan *ai.FixPlan) []map[string]string {
	if plan == nil {
		return nil
	}
	changes := []map[string]string{}
	for _, step := range plan.Steps {
		if step.CodeChange != nil {
			change := map[string]string{
				"filePath":    step.CodeChange.FilePath,
				"description": step.CodeChange.Description,
			}
			if step.CodeChange.Diff != "" {
				change["diff"] = step.CodeChange.Diff
			}
			if step.CodeChange.OldContent != "" {
				change["oldContent"] = step.CodeChange.OldContent
			}
			if step.CodeChange.NewContent != "" {
				change["newContent"] = step.CodeChange.NewContent
			}
			changes = append(changes, change)
		}
	}
	return changes
}

func buildVerificationResult(buildResult *git.BuildResult) map[string]interface{} {
	if buildResult == nil {
		return nil
	}
	return map[string]interface{}{
		"skipped":    buildResult.Skipped,
		"skipReason": buildResult.SkipReason,
		"success":    buildResult.Success,
		"command":    buildResult.Command,
		"durationMs": buildResult.Duration,
	}
}

func (s *FixService) saveFixCheckpoint(taskID uint, checkpoint map[string]interface{}) {
	if len(checkpoint) == 0 {
		return
	}
	bytes, err := json.Marshal(checkpoint)
	if err != nil {
		logger.Errorf("[FixService] marshal fix checkpoint failed: %v", err)
		return
	}
	UpdateTaskFields(s.db, taskID, map[string]interface{}{"Result": string(bytes)})
}

func (s *FixService) finalizeFixSuccess(taskID, defectID uint, result *FixResult) error {
	if err := s.finalizeFixTaskSuccess(taskID, result); err != nil {
		return err
	}
	if defectID > 0 {
		status := model.FixTaskStatusCompleted
		if result != nil && result.Status != "" {
			status = result.Status
		}
		s.finalizeDefectStatusFromFixGroup(defectID, status)
	}
	return nil
}

func (s *FixService) finalizeFixTaskSuccess(taskID uint, result *FixResult) error {
	now := time.Now()
	updates := map[string]interface{}{
		"Status":      result.Status,
		"Result":      string(result.ResultJSON),
		"PRURL":       result.PRURL,
		"CompletedAt": now,
	}
	if len(result.PlanJSON) > 0 {
		updates["Plan"] = string(result.PlanJSON)
	}
	if err := s.db.Model(&model.FixTask{}).Where("id = ?", taskID).UpdateColumns(updates).Error; err != nil {
		return err
	}
	s.notifyFixTaskFinished(taskID)
	return nil
}

func (s *FixService) finalizeFixFailure(taskID, defectID uint, reason string) error {
	if err := s.finalizeFixTaskFailure(taskID, reason); err != nil {
		return err
	}
	result := s.db.Model(&model.Defect{}).Where("id = ? AND status IN ?", defectID, []string{model.DefectStatusFixing, model.DefectStatusManualFixing}).Update("status", model.DefectStatusPendingFix)
	if result.Error != nil {
		logger.Errorf("[FixService] 回退缺陷状态失败: %v", result.Error)
		return result.Error
	}
	if result.RowsAffected == 0 {
		logger.Warnf("[FixService] 缺陷 %d 状态已变更，跳过回退（当前非fixing状态）", defectID)
	}
	return nil
}

func (s *FixService) finalizeFixTaskFailure(taskID uint, reason string) error {
	now := time.Now()
	resultPayload := map[string]interface{}{"error": reason}
	var existingTask model.FixTask
	if err := s.db.Select("result").First(&existingTask, taskID).Error; err == nil && strings.TrimSpace(existingTask.Result) != "" {
		var existing map[string]interface{}
		if err := json.Unmarshal([]byte(existingTask.Result), &existing); err == nil {
			for k, v := range existing {
				resultPayload[k] = v
			}
			resultPayload["error"] = reason
		}
	}
	resultBytes, err := json.Marshal(resultPayload)
	if err != nil {
		logger.Errorf("[FixService] marshal failure result failed: %v", err)
	}
	updates := map[string]interface{}{
		"Status":      "failed",
		"Result":      string(resultBytes),
		"CompletedAt": now,
	}
	if err := s.db.Model(&model.FixTask{}).Where("id = ?", taskID).UpdateColumns(updates).Error; err != nil {
		return err
	}
	s.notifyFixTaskFinished(taskID)
	return nil
}

func (s *FixService) notifyFixTaskFinished(taskID uint) {
	if sse.Notifier == nil {
		return
	}
	var task model.FixTask
	if err := s.db.Select("id, group_id, task_code, defect_id, agent_type, status, pr_url").First(&task, taskID).Error; err != nil {
		logger.Errorf("[FixService] query finished fix task for SSE failed: taskID=%d err=%v", taskID, err)
		return
	}
	sse.Notifier.NotifyFixTaskFinished(task.DefectID, task.GroupID, task.ID, task.TaskCode, task.AgentType, task.Status, task.PRURL)
}

func (s *FixService) refreshFixTaskGroupStatus(groupID *uint, defectID uint) {
	if groupID == nil || *groupID == 0 {
		return
	}

	var tasks []model.FixTask
	if err := s.db.Select("id, status").Where("group_id = ?", *groupID).Find(&tasks).Error; err != nil {
		logger.Errorf("[FixService] query group units failed: groupID=%d err=%v", *groupID, err)
		return
	}
	if len(tasks) == 0 {
		return
	}

	warnings := 0
	noChanges := 0
	failed := 0
	cancelled := 0
	running := 0
	for _, task := range tasks {
		switch task.Status {
		case model.FixTaskStatusCompleted:
		case model.FixTaskStatusNoChanges:
			noChanges++
		case model.FixTaskStatusCompletedWithWarnings:
			warnings++
		case model.FixTaskStatusFailed:
			failed++
		case model.FixTaskStatusCancelled:
			cancelled++
		default:
			running++
		}
	}

	status := model.FixTaskStatusExecuting
	updates := map[string]interface{}{}
	if running == 0 {
		now := time.Now()
		updates["CompletedAt"] = now
		switch {
		case failed == len(tasks) || cancelled == len(tasks):
			status = model.FixTaskStatusFailed
		case failed > 0 || cancelled > 0:
			status = model.FixTaskStatusPartiallyFailed
		case noChanges == len(tasks):
			status = model.FixTaskStatusNoChanges
		case noChanges > 0:
			status = model.FixTaskStatusCompletedWithWarnings
		case warnings > 0:
			status = model.FixTaskStatusCompletedWithWarnings
		default:
			status = model.FixTaskStatusCompleted
		}
	}
	updates["Status"] = status
	UpdateTaskGroupFields(s.db, *groupID, updates)
	if running == 0 {
		s.finalizeDefectStatusFromFixGroup(defectID, status)
	}
}

func (s *FixService) finalizeDefectStatusFromFixGroup(defectID uint, groupStatus string) {
	nextStatus := model.DefectStatusPendingVerify
	if groupStatus == model.FixTaskStatusFailed || groupStatus == model.FixTaskStatusPartiallyFailed || groupStatus == model.FixTaskStatusNoChanges {
		nextStatus = model.DefectStatusPendingFix
	}
	result := s.db.Model(&model.Defect{}).
		Where("id = ? AND status IN ?", defectID, []string{model.DefectStatusFixing, model.DefectStatusManualFixing}).
		Update("status", nextStatus)
	if result.Error != nil {
		logger.Errorf("[FixService] update defect status from fix group failed: %v", result.Error)
	}
}

func (s *FixService) getFirstFixTask(taskID uint) (*model.FixTask, error) {
	var task model.FixTask
	if err := s.db.First(&task, taskID).Error; err != nil {
		return nil, err
	}
	return &task, nil
}

func GenerateTaskCode(defectCode string) string {
	now := time.Now()
	defectCode = compactTaskCodePart(defectCode, 33)
	return fmt.Sprintf("FT-%s-%s-%s", defectCode, now.Format("200601"), now.Format("150405"))
}

func GenerateUnitTaskCode(defectCode, agentType string, unitIndex int) string {
	now := time.Now()
	agentType = strings.TrimSpace(agentType)
	if agentType == "" {
		agentType = "unit"
	}
	agentType = strings.NewReplacer("/", "-", "\\", "-", " ", "-").Replace(agentType)
	agentType = compactTaskCodePart(agentType, 10)
	defectCode = compactTaskCodePart(defectCode, 18)
	if unitIndex <= 0 {
		unitIndex = 1
	}
	return fmt.Sprintf("FT-%s-%s-%s-%02d-%s", defectCode, now.Format("200601"), now.Format("150405"), unitIndex, agentType)
}

func compactTaskCodePart(value string, maxLen int) string {
	value = strings.TrimSpace(value)
	if len(value) <= maxLen {
		return value
	}
	if maxLen <= 7 {
		return value[:maxLen]
	}
	sum := sha256.Sum256([]byte(value))
	hash := hex.EncodeToString(sum[:])[:6]
	return value[:maxLen-7] + "-" + hash
}

func GenerateCommitDescription(plan *ai.FixPlan) string {
	var desc strings.Builder
	desc.WriteString("Auto-generated fix by BugAgent AI:\n\n")
	for _, step := range plan.Steps {
		if step.CodeChange != nil && step.CodeChange.Description != "" {
			fmt.Fprintf(&desc, "- %s\n", step.CodeChange.Description)
		}
	}
	return desc.String()
}

// getDefect loads the defect data required by the fix workflow.
func (s *FixService) getDefect(defectID uint) (model.Defect, error) {
	var defect model.Defect
	err := s.db.Preload("Iteration").
		Preload("Assignee").
		First(&defect, defectID).Error
	return defect, err
}

func (s *FixService) getLatestAnalysisReport(defectID uint, agentType string) (model.AnalysisReport, error) {
	var reports []model.AnalysisReport
	if strings.TrimSpace(agentType) != "" {
		err := s.db.
			Where("defect_id = ? AND agent_type = ? AND status = ?", defectID, agentType, model.AnalysisStatusCompleted).
			Order("created_at DESC").
			Find(&reports).Error
		if err != nil {
			return model.AnalysisReport{}, err
		}
		for _, report := range reports {
			if isAutoFixableAnalysisReport(report) {
				return report, nil
			}
		}
		return model.AnalysisReport{}, gorm.ErrRecordNotFound
	}

	reports = nil
	err := s.db.Where("defect_id = ? AND status = ?", defectID, model.AnalysisStatusCompleted).
		Order("created_at DESC").
		Find(&reports).Error
	if err != nil {
		return model.AnalysisReport{}, err
	}
	for _, report := range reports {
		if isAutoFixableAnalysisReport(report) {
			return report, nil
		}
	}
	return model.AnalysisReport{}, gorm.ErrRecordNotFound
}

func (s *FixService) getLatestAutoFixableAnalysisReports(defectID uint, agentType string) ([]model.AnalysisReport, error) {
	agentType = strings.TrimSpace(agentType)
	if agentType != "" {
		report, err := s.getLatestAnalysisReport(defectID, agentType)
		if err != nil {
			return nil, err
		}
		return []model.AnalysisReport{report}, nil
	}

	var reports []model.AnalysisReport
	if err := s.db.Where("defect_id = ? AND status = ?", defectID, model.AnalysisStatusCompleted).
		Order("created_at DESC").
		Find(&reports).Error; err != nil {
		return nil, err
	}

	seenAgents := map[string]bool{}
	selected := make([]model.AnalysisReport, 0)
	for _, report := range reports {
		agent := strings.TrimSpace(report.AgentType)
		if agent == "" || seenAgents[agent] || !isAutoFixableAnalysisReport(report) {
			continue
		}
		seenAgents[agent] = true
		selected = append(selected, report)
	}
	if len(selected) == 0 {
		return nil, gorm.ErrRecordNotFound
	}
	return selected, nil
}

func isAutoFixableAnalysisReport(report model.AnalysisReport) bool {
	if report.Status != model.AnalysisStatusCompleted {
		return false
	}
	if analysisHasFixSteps(report.Analysis) {
		return true
	}
	return analysisHasFixSteps(report.Solution)
}

func analysisHasFixSteps(raw string) bool {
	if strings.TrimSpace(raw) == "" || strings.TrimSpace(raw) == "null" {
		return false
	}
	var payload map[string]interface{}
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		return false
	}
	if steps, ok := payload["steps"].([]interface{}); ok && analysisHasFileLevelFixStep(steps) {
		return true
	}
	solution, ok := payload["solution"].(map[string]interface{})
	if !ok {
		return false
	}
	steps, ok := solution["steps"].([]interface{})
	return ok && analysisHasFileLevelFixStep(steps)
}

func analysisHasFileLevelFixStep(steps []interface{}) bool {
	for _, stepData := range steps {
		stepMap, ok := stepData.(map[string]interface{})
		if !ok {
			continue
		}
		for _, key := range []string{"filePath", "path", "targetFile"} {
			if path, ok := stepMap[key].(string); ok && analysisLooksLikeRepoFilePath(path) {
				return true
			}
		}
	}
	return false
}

func analysisLooksLikeRepoFilePath(value string) bool {
	value = strings.TrimSpace(value)
	if value == "" || strings.Contains(value, "\n") || strings.Contains(value, "\r") {
		return false
	}
	if strings.ContainsAny(value, "\"'`{}()") || strings.Contains(value, " ") {
		return false
	}
	return filepath.Ext(value) != ""
}

func (s *FixService) publishFixFailureComment(defect model.Defect, task *model.FixTask, err error) {
	errMsg := err.Error()
	if len(errMsg) > 200 {
		errMsg = errMsg[:200] + "..."
	}

	content := fmt.Sprintf(
		"⚠️ 自动修复失败，状态已回退到待修复。\n失败原因：%s",
		errMsg,
	)

	comment := model.Comment{
		DefectID:       defect.ID,
		Content:        sanitizeCommentContent(content),
		AgentType:      task.AgentType,
		IsAgentMessage: true,
	}
	comment.UserID = resolveCommentUserID(defect)
	if !ensureCommentUserExists(s.db, comment.UserID) {
		return
	}
	if err := s.db.Create(&comment).Error; err != nil {
		logger.Errorf("[FixService] 发布修复失败评论失败: %v", err)
	}
}
