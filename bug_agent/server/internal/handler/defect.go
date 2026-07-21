package handler

import (
	"bug-agent/internal/adk"
	"bug-agent/internal/asyncx"
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/internal/sse"
	"bug-agent/internal/vcs"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/gin-gonic/gin/binding"
	"gorm.io/gorm"
)

type DefectHandler struct {
	db              *gorm.DB
	analysisService *adk.ADKAnalysisService
}

func NewDefectHandler(db *gorm.DB) *DefectHandler { return &DefectHandler{db: db} }

func NewDefectHandlerWithAnalysisService(db *gorm.DB, analysisService *adk.ADKAnalysisService) *DefectHandler {
	return &DefectHandler{db: db, analysisService: analysisService}
}

type defectCreateInput struct {
	IterationID uint
	Title       string
	Description string
	Severity    string
	Priority    string
	DefectType  string
	Tags        []string
	SourceMode  string
}

type defectConfirmCreateRequest struct {
	IterationID         uint     `json:"iterationId" binding:"required"`
	Title               string   `json:"title" binding:"required,max=100"`
	DescriptionMarkdown string   `json:"descriptionMarkdown" binding:"required"`
	Severity            string   `json:"severity"`
	Priority            string   `json:"priority"`
	Type                string   `json:"type"`
	Tags                []string `json:"tags"`
	SourceMode          string   `json:"sourceMode"`
}

func (h *DefectHandler) CreateDraftFromChat(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req service.DefectDraftRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	draft, err := service.NewDefectDraftService(h.db).GenerateDraft(c.Request.Context(), projectID, req)
	if err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	response.Success(c, draft)
}

func (h *DefectHandler) ConfirmCreateDefect(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req defectConfirmCreateRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	defect, err := h.createManualDefect(projectID, getUserID(c), defectCreateInput{
		IterationID: req.IterationID,
		Title:       req.Title,
		Description: req.DescriptionMarkdown,
		Severity:    req.Severity,
		Priority:    req.Priority,
		DefectType:  req.Type,
		Tags:        req.Tags,
		SourceMode:  req.SourceMode,
	})
	if err != nil {
		if strings.Contains(err.Error(), "不存在") {
			response.NotFound(c, err.Error())
		} else {
			response.BadRequest(c, err.Error())
		}
		return
	}

	response.Created(c, defect)
}

// CreateDefect 创建缺陷
func (h *DefectHandler) CreateDefect(c *gin.Context) {
	userID := middleware.GetUserID(c)
	var req struct {
		IterationID uint     `json:"iterationId" binding:"required"`
		Title       string   `json:"title" binding:"required,max=100"`
		Description string   `json:"description" binding:"required"`
		Severity    string   `json:"severity"`
		Priority    string   `json:"priority"`
		Type        string   `json:"type"`
		Tags        []string `json:"tags"`
	}
	// Must use ShouldBindBodyWith because permission middleware reads body first.
	if err := c.ShouldBindBodyWith(&req, binding.JSON); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	projectID, err := h.projectIDForIteration(req.IterationID)
	if err != nil {
		response.NotFound(c, err.Error())
		return
	}

	defect, err := h.createManualDefect(projectID, userID, defectCreateInput{
		IterationID: req.IterationID,
		Title:       req.Title,
		Description: req.Description,
		Severity:    req.Severity,
		Priority:    req.Priority,
		DefectType:  req.Type,
		Tags:        req.Tags,
		SourceMode:  model.IssueSourceManualForm,
	})
	if err != nil {
		if strings.Contains(err.Error(), "不存在") {
			response.NotFound(c, err.Error())
		} else {
			response.BadRequest(c, err.Error())
		}
		return
	}
	response.Created(c, defect)
}

func (h *DefectHandler) createManualDefect(projectID, userID uint, input defectCreateInput) (*model.Defect, error) {
	var created model.Defect
	err := h.db.Transaction(func(tx *gorm.DB) error {
		var iteration model.Iteration
		if err := tx.Where("id = ? AND project_id = ?", input.IterationID, projectID).First(&iteration).Error; err != nil {
			return fmt.Errorf("迭代不存在或不属于当前项目")
		}

		var project model.Project
		if err := tx.First(&project, projectID).Error; err != nil {
			return fmt.Errorf("项目不存在")
		}

		defectCode, err := model.GenerateDefectCode(tx, &project)
		if err != nil {
			return fmt.Errorf("生成缺陷编号失败: %w", err)
		}
		defect := model.Defect{
			Code:        defectCode,
			IterationID: input.IterationID,
			Title:       strings.TrimSpace(input.Title),
			Description: strings.TrimSpace(input.Description),
			Severity:    normalizeDefectSeverity(input.Severity),
			Priority:    normalizeDefectPriority(input.Priority),
			Type:        normalizeDefectType(input.DefectType),
			Status:      model.DefectStatusPendingAssign,
			ReporterID:  userID,
			Tags:        strings.Join(sanitizeTags(input.Tags), ","),
		}
		if err := tx.Create(&defect).Error; err != nil {
			return fmt.Errorf("创建缺陷失败")
		}
		if _, _, err := service.NewManualDefectSignalService(tx).Ingest(tx, defect, projectID, input.SourceMode); err != nil {
			return fmt.Errorf("创建问题池信号失败: %w", err)
		}
		if err := tx.Preload("Reporter").Preload("Assignee").Preload("Iteration").First(&created, defect.ID).Error; err != nil {
			return err
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return &created, nil
}

func (h *DefectHandler) projectIDForIteration(iterationID uint) (uint, error) {
	var iteration model.Iteration
	if err := h.db.First(&iteration, iterationID).Error; err != nil {
		return 0, fmt.Errorf("迭代不存在")
	}
	return iteration.ProjectID, nil
}

func normalizeDefectSeverity(value string) string {
	switch strings.TrimSpace(strings.ToLower(value)) {
	case model.SeverityFatal:
		return model.SeverityFatal
	case model.SeverityMajor:
		return model.SeverityMajor
	case model.SeverityMinor:
		return model.SeverityMinor
	case model.SeveritySuggest:
		return model.SeveritySuggest
	default:
		return model.SeverityNormal
	}
}

func normalizeDefectPriority(value string) string {
	value = strings.ToUpper(strings.TrimSpace(value))
	switch value {
	case model.PriorityP0, model.PriorityP1, model.PriorityP2, model.PriorityP3, model.PriorityP4:
		return value
	default:
		return model.PriorityP2
	}
}

func normalizeDefectType(value string) string {
	switch strings.TrimSpace(strings.ToLower(value)) {
	case model.DefectTypeFunctional:
		return model.DefectTypeFunctional
	case model.DefectTypeUI:
		return model.DefectTypeUI
	case model.DefectTypePerformance:
		return model.DefectTypePerformance
	case model.DefectTypeSecurity:
		return model.DefectTypeSecurity
	case model.DefectTypeCompatibility:
		return model.DefectTypeCompatibility
	default:
		return model.DefectTypeFunctional
	}
}

func sanitizeTags(tags []string) []string {
	values := make([]string, 0, len(tags))
	seen := make(map[string]struct{}, len(tags))
	for _, tag := range tags {
		tag = strings.TrimSpace(tag)
		if tag == "" {
			continue
		}
		if _, ok := seen[tag]; ok {
			continue
		}
		seen[tag] = struct{}{}
		values = append(values, tag)
	}
	return values
}

// GetDefect 获取缺陷详情
func (h *DefectHandler) GetDefect(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	var defect model.Defect
	if err := h.db.Preload("Assignee").Preload("Reporter").Preload("Iteration").
		First(&defect, id).Error; err != nil {
		response.NotFound(c, "缺陷不存在")
		return
	}

	var comments []model.Comment
	if err := h.db.Preload("User").Where("defect_id = ?", id).Order("created_at ASC").Find(&comments).Error; err != nil {
		logger.Errorf("[DefectHandler] query comments failed: %v", err)
	}

	var fixTasks []model.FixTask
	if err := h.db.Where("defect_id = ?", id).Order("created_at DESC").Find(&fixTasks).Error; err != nil {
		logger.Errorf("[DefectHandler] query fixTasks failed: %v", err)
	}

	var reports []model.AnalysisReport
	if err := h.db.Where("defect_id = ?", id).Order("created_at DESC").Find(&reports).Error; err != nil {
		logger.Errorf("[DefectHandler] query reports failed: %v", err)
	}

	var attachments []model.Attachment
	if err := h.db.Where("defect_id = ?", id).Find(&attachments).Error; err != nil {
		logger.Errorf("[DefectHandler] query attachments failed: %v", err)
	}

	// 操作历史 (简化 - 用updated_at代替)
	// NOTE: 此接口返回格式与其他缺陷操作接口不一致：本接口将 defect 包裹在 "defect" key 中，
	// 而 ChangeStatus/UpdateDefect 等接口直接返回 defect 对象。保持现状以避免破坏前端兼容性。
	response.Success(c, gin.H{
		"defect":      defect,
		"comments":    comments,
		"fixTasks":    fixTasks,
		"reports":     reports,
		"attachments": attachments,
	})
}

// ListDefects 获取缺陷列表
func (h *DefectHandler) ListDefects(c *gin.Context) {
	userID := middleware.GetUserID(c)
	query := h.db.Model(&model.Defect{})

	// 筛选条件
	if projectID := c.Query("projectId"); projectID != "" {
		query = query.Joins("JOIN iterations ON iterations.id = defects.iteration_id").
			Where("iterations.project_id = ?", projectID)
	}
	if iterationID := c.Query("iterationId"); iterationID != "" {
		query = query.Where("iteration_id = ?", iterationID)
	}
	if status := c.Query("status"); status != "" {
		statuses := splitCSVValues(status)
		if len(statuses) == 1 {
			query = query.Where("status = ?", statuses[0])
		} else if len(statuses) > 1 {
			query = query.Where("status IN ?", statuses)
		}
	}
	if severity := c.Query("severity"); severity != "" {
		severities := splitCSVValues(severity)
		if len(severities) == 1 {
			query = query.Where("severity = ?", severities[0])
		} else if len(severities) > 1 {
			query = query.Where("severity IN ?", severities)
		}
	}
	if priority := c.Query("priority"); priority != "" {
		priorities := splitCSVValues(priority)
		if len(priorities) == 1 {
			query = query.Where("priority = ?", priorities[0])
		} else if len(priorities) > 1 {
			query = query.Where("priority IN ?", priorities)
		}
	}
	if defectType := c.Query("type"); defectType != "" {
		types := splitCSVValues(defectType)
		if len(types) == 1 {
			query = query.Where("type = ?", types[0])
		} else if len(types) > 1 {
			query = query.Where("type IN ?", types)
		}
	}
	if keyword := c.Query("keyword"); keyword != "" {
		likePattern := "%" + EscapeLike(keyword) + "%"
		query = query.Where("title LIKE ? OR code LIKE ?", likePattern, likePattern)
	}
	if assignee := c.Query("assigneeId"); assignee != "" {
		if assignee == "me" {
			query = query.Where("assignee_id = ?", userID)
		} else {
			query = query.Where("assignee_id = ?", assignee)
		}
	}
	if reporter := c.Query("reporterId"); reporter != "" {
		if reporter == "me" {
			query = query.Where("reporter_id = ?", userID)
		} else {
			query = query.Where("reporter_id = ?", reporter)
		}
	}
	// 标签筛选（支持多标签，逗号分隔）
	// NOTE: tags 字段以逗号分隔存储，当前使用 LIKE 匹配，无法精确匹配包含关系的标签
	// （如搜索 "bug" 会匹配到 "bugfix"）。若需精确匹配，应迁移为关联表或使用 FIND_IN_SET（MySQL）。
	if tags := c.Query("tags"); tags != "" {
		tagList := strings.Split(tags, ",")
		for _, tag := range tagList {
			tag = strings.TrimSpace(tag)
			if tag != "" {
				escaped := EscapeLike(tag)
				// 匹配: 标签在开头(tag,...)、中间(...,tag,...)、末尾(...,tag)、或唯一(tag)
				query = query.Where(
					"CONCAT(',', tags, ',') LIKE ?",
					"%,"+escaped+",%",
				)
			}
		}
	}

	page, size := parsePagination(c, 100)

	var total int64
	if err := query.Count(&total).Error; err != nil {
		response.ServerError(c, "查询缺陷总数失败")
		return
	}

	// 排序（在 count 后应用，避免 count 查询执行无意义排序）
	sortBy := c.DefaultQuery("sortBy", "created_at")
	orderBy := c.DefaultQuery("orderBy", "desc")
	if orderBy != "asc" {
		orderBy = "desc"
	}
	allowedSorts := map[string]string{
		"created_at": "defects.created_at",
		"updated_at": "defects.updated_at",
		"priority":   "defects.priority",
		"severity":   "defects.severity",
	}
	sortColumn, ok := allowedSorts[sortBy]
	if !ok {
		sortBy = "created_at"
		sortColumn = allowedSorts[sortBy]
	}

	var defects []model.Defect
	preloadUserLite := func(db *gorm.DB) *gorm.DB {
		return db.Select("id", "username", "nickname", "avatar")
	}
	if err := query.Order(sortColumn+" "+orderBy).
		Preload("Assignee", preloadUserLite).
		Preload("Reporter", preloadUserLite).
		Offset((page - 1) * size).
		Limit(size).
		Find(&defects).Error; err != nil {
		response.ServerError(c, "查询缺陷列表失败")
		return
	}

	response.SuccessPage(c, defects, total, page, size)
}

func splitCSVValues(raw string) []string {
	parts := strings.Split(raw, ",")
	values := make([]string, 0, len(parts))
	for _, p := range parts {
		v := strings.TrimSpace(p)
		if v != "" {
			values = append(values, v)
		}
	}
	return values
}

// RecommendAssignees 获取缺陷负责人推荐
func (h *DefectHandler) RecommendAssignees(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	limit := parseLimit(c.Query("limit"), 3)
	list, recErr := service.NewDefectRecommendationService(h.db).RecommendAssignees(id, limit)
	if recErr != nil {
		if errors.Is(recErr, service.ErrDefectRecommendationNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "获取负责人推荐失败")
		return
	}
	response.Success(c, gin.H{"list": list})
}

// RecommendAgents 获取缺陷 AGENT 推荐
func (h *DefectHandler) RecommendAgents(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	limit := parseLimit(c.Query("limit"), 3)
	list, recErr := service.NewDefectRecommendationService(h.db).RecommendAgents(id, limit)
	if recErr != nil {
		if errors.Is(recErr, service.ErrDefectRecommendationNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "获取 AGENT 推荐失败")
		return
	}
	response.Success(c, gin.H{"list": list})
}

// UpdateDefect 更新缺陷信息
func (h *DefectHandler) UpdateDefect(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	var req struct {
		Title             *string  `json:"title"`
		Description       *string  `json:"description"`
		Severity          *string  `json:"severity"`
		Priority          *string  `json:"priority"`
		Type              *string  `json:"type"`
		Tags              []string `json:"tags"`
		LinkedRequirement *string  `json:"linkedRequirement"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	updates := map[string]interface{}{}
	if req.Title != nil {
		updates["title"] = strings.TrimSpace(*req.Title)
	}
	if req.Description != nil {
		updates["description"] = strings.TrimSpace(*req.Description)
	}
	if req.Severity != nil {
		updates["severity"] = normalizeDefectSeverity(*req.Severity)
	}
	if req.Priority != nil {
		updates["priority"] = normalizeDefectPriority(*req.Priority)
	}
	if req.Type != nil {
		updates["type"] = normalizeDefectType(*req.Type)
	}
	if req.Tags != nil {
		updates["tags"] = strings.Join(sanitizeTags(req.Tags), ",")
	}

	if len(updates) == 0 {
		var defect model.Defect
		if err := h.db.Preload("Assignee").Preload("Reporter").First(&defect, id).Error; err != nil {
			response.ServerError(c, "查询缺陷失败")
			return
		}
		response.Success(c, defect)
		return
	}

	if err := h.db.Model(&model.Defect{}).Where("id = ?", id).Updates(updates).Error; err != nil {
		response.ServerError(c, "更新缺陷失败")
		return
	}

	var defect model.Defect
	if err := h.db.Preload("Assignee").Preload("Reporter").First(&defect, id).Error; err != nil {
		response.ServerError(c, "查询缺陷失败")
		return
	}
	response.Success(c, defect)
}

// AssignDefect 分配缺陷
func (h *DefectHandler) AssignDefect(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	var req struct {
		AssigneeID             uint     `json:"assigneeId" binding:"required"`
		AgentTypes             []string `json:"agentTypes"`
		RecommendationAdopted  bool     `json:"recommendationAdopted"`
		RecommendationStrategy string   `json:"recommendationStrategy"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	var currentDefect model.Defect
	if err := h.db.Select("id, status").First(&currentDefect, id).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}
	if !model.IsValidDefectTransition(currentDefect.Status, model.DefectStatusPendingAnalysis) {
		response.Conflict(c, fmt.Sprintf("当前状态 [%s] 不允许分配操作", currentDefect.Status))
		return
	}

	result := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", id, currentDefect.Status).Updates(map[string]interface{}{
		"assignee_id": req.AssigneeID,
		"status":      model.DefectStatusPendingAnalysis,
	})
	if result.Error != nil {
		response.ServerError(c, "分配缺陷失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "缺陷状态已变更，请刷新后重试")
		return
	}

	userID := middleware.GetUserID(c)
	if err := h.db.Create(&model.StatusChange{
		DefectID:   id,
		FromStatus: currentDefect.Status,
		ToStatus:   model.DefectStatusPendingAnalysis,
		ChangedBy:  userID,
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create assign status change record failed: %v", err)
	}

	var defect model.Defect
	if err := h.db.Preload("Assignee").Preload("Reporter").First(&defect, id).Error; err != nil {
		response.ServerError(c, "查询缺陷失败")
		return
	}

	if req.RecommendationAdopted {
		middleware.AuditAction(c, "defect_assign_recommendation_adopted", "defect", id, nil, gin.H{
			"assigneeId": req.AssigneeID,
			"strategy":   strings.TrimSpace(req.RecommendationStrategy),
		})
	}

	agentTypes := req.AgentTypes
	if len(agentTypes) == 0 {
		agentTypes = []string{"frontend"}
	}

	analysisReq := adk.ADKAnalysisRequest{
		DefectID:   id,
		AgentTypes: agentTypes,
		UserID:     req.AssigneeID,
	}

	asyncx.Go(func() {
		ctx := asyncx.ShutdownContext()
		analysisResult, err := h.performADKAnalysis(ctx, analysisReq)
		if err != nil {
			logger.Errorf("[AssignDefect] 自动分析失败: 缺陷 #%d, 错误: %v", id, err)
			rollbackResult := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", id, model.DefectStatusAnalyzing).Update("status", model.DefectStatusPendingAssign)
			if rollbackResult.RowsAffected == 0 {
				logger.Errorf("[AssignDefect] 回滚失败: 缺陷 #%d 状态已变更, 期望 analyzing", id)
			}
			sse.Notifier.NotifyAnalysisFailed(id, err.Error())
			if defect.ReporterID > 0 {
				_ = h.db.Create(&model.Comment{
					DefectID:       id,
					UserID:         defect.ReporterID,
					AgentType:      "system",
					IsAgentMessage: true,
					Content:        "⚠️ 分配后自动分析失败，状态已回退到待分配。失败原因：分析服务异常",
				}).Error
			}
			return
		}
		logger.Infof("[AssignDefect] 自动分析完成: 缺陷 #%d, 报告=%s, 耗时=%v", id, analysisResult.ReportCode, analysisResult.Duration)
	})

	response.Success(c, gin.H{
		"defect":                 defect,
		"status":                 defect.Status,
		"agentAnalysisTriggered": true,
	})
}

func (h *DefectHandler) performADKAnalysis(ctx context.Context, req adk.ADKAnalysisRequest) (*adk.ADKAnalysisResult, error) {
	analysisService := h.analysisService
	if analysisService == nil {
		var err error
		analysisService, err = adk.NewADKAnalysisService(h.db)
		if err != nil {
			return nil, err
		}
	}
	return analysisService.PerformAnalysis(ctx, req)
}

// ChangeStatus 变更缺陷状态
func (h *DefectHandler) ChangeStatus(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	var req struct {
		Status  string `json:"status" binding:"required"`
		Comment string `json:"comment"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	// 验证状态流转合法性
	var defect model.Defect
	if err := h.db.First(&defect, id).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}
	if !model.IsValidDefectTransition(defect.Status, req.Status) {
		validTransitions := model.GetValidTransitions(defect.Status)
		if len(validTransitions) == 0 {
			response.Conflict(c, fmt.Sprintf("当前状态 [%s] 不允许继续流转", defect.Status))
			return
		}
		response.Conflict(c, fmt.Sprintf("不允许从 [%s] 流转到 [%s]，允许的流转: %s", defect.Status, req.Status, strings.Join(validTransitions, ", ")))
		return
	}

	result := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", id, defect.Status).Update("status", req.Status)
	if result.Error != nil {
		response.ServerError(c, "更新缺陷状态失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "状态已变更，请刷新后重试")
		return
	}

	userID := middleware.GetUserID(c)
	if err := h.db.Create(&model.StatusChange{
		DefectID:   id,
		FromStatus: defect.Status,
		ToStatus:   req.Status,
		ChangedBy:  userID,
		Comment:    req.Comment,
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create status change record failed: %v", err)
	}

	if req.Comment != "" {
		if err := h.db.Create(&model.Comment{
			DefectID: id,
			UserID:   userID,
			Content:  fmt.Sprintf("🔄 状态变更为: %s\n%s", req.Status, req.Comment),
		}).Error; err != nil {
			logger.Errorf("[DefectHandler] create status change comment failed: %v", err)
		}
	}

	if err := h.db.Preload("Assignee").Preload("Reporter").First(&defect, id).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}
	response.Success(c, defect)
}

type reopenRequest struct {
	TargetStatus string `json:"targetStatus" binding:"required"`
	Comment      string `json:"comment"`
}

var allowedReopenTargets = map[string]bool{
	model.DefectStatusPendingAnalysis: true,
	model.DefectStatusAnalyzing:       true,
	model.DefectStatusPendingFix:      true,
}

func (h *DefectHandler) ReopenDefect(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	var req reopenRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	if !allowedReopenTargets[req.TargetStatus] {
		response.BadRequest(c, fmt.Sprintf("不支持的目标状态: %s，允许: pending_analysis, analyzing, pending_fix", req.TargetStatus))
		return
	}

	var defect model.Defect
	if err := h.db.First(&defect, id).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}

	userID := middleware.GetUserID(c)
	comment := fmt.Sprintf("reopen_to:%s", req.TargetStatus)
	if req.Comment != "" {
		comment += " " + req.Comment
	}

	steps := []struct{ from, to string }{}
	if model.IsValidDefectTransition(defect.Status, req.TargetStatus) {
		steps = append(steps, struct{ from, to string }{defect.Status, req.TargetStatus})
	} else if model.IsValidDefectTransition(defect.Status, model.DefectStatusReopened) &&
		model.IsValidDefectTransition(model.DefectStatusReopened, req.TargetStatus) {
		steps = append(steps,
			struct{ from, to string }{defect.Status, model.DefectStatusReopened},
			struct{ from, to string }{model.DefectStatusReopened, req.TargetStatus},
		)
	} else {
		validTransitions := model.GetValidTransitions(defect.Status)
		response.Conflict(c, fmt.Sprintf("不允许从 [%s] 流转到 [%s]，允许的流转: %s", defect.Status, req.TargetStatus, strings.Join(validTransitions, ", ")))
		return
	}

	err = h.db.Transaction(func(tx *gorm.DB) error {
		currentStatus := defect.Status
		for _, step := range steps {
			result := tx.Model(&model.Defect{}).Where("id = ? AND status = ?", id, currentStatus).Update("status", step.to)
			if result.Error != nil {
				return result.Error
			}
			if result.RowsAffected == 0 {
				return fmt.Errorf("conflict")
			}
			if err := tx.Create(&model.StatusChange{
				DefectID:   id,
				FromStatus: step.from,
				ToStatus:   step.to,
				ChangedBy:  userID,
				Comment:    comment,
			}).Error; err != nil {
				return err
			}
			currentStatus = step.to
		}
		return nil
	})
	if err != nil {
		if err.Error() == "conflict" {
			response.Conflict(c, "状态已变更，请刷新后重试")
			return
		}
		response.ServerError(c, "更新缺陷状态失败")
		return
	}

	if req.TargetStatus == model.DefectStatusPendingAnalysis {
		h.db.Model(&model.AnalysisReport{}).
			Where("defect_id = ? AND status = ?", id, model.AnalysisStatusCompleted).
			Update("status", model.AnalysisStatusSuperseded)
	}

	if err := h.db.Preload("Assignee").Preload("Reporter").First(&defect, id).Error; err != nil {
		response.ServerError(c, "查询缺陷失败")
		return
	}
	response.Success(c, defect)
}

func (h *DefectHandler) ReanalyzeDefect(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}

	var defect model.Defect
	if err := h.db.First(&defect, id).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}

	if defect.Status != model.DefectStatusPendingFix {
		response.Conflict(c, fmt.Sprintf("只有 [待修复] 状态可以重新分析，当前状态: [%s]", defect.Status))
		return
	}

	result := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", id, model.DefectStatusPendingFix).Update("status", model.DefectStatusPendingAnalysis)
	if result.Error != nil {
		response.ServerError(c, "更新缺陷状态失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "状态已变更，请刷新后重试")
		return
	}

	userID := middleware.GetUserID(c)
	if err := h.db.Create(&model.StatusChange{
		DefectID:   id,
		FromStatus: model.DefectStatusPendingFix,
		ToStatus:   model.DefectStatusPendingAnalysis,
		ChangedBy:  userID,
		Comment:    "reanalyze",
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create reanalyze status change record failed: %v", err)
	}

	h.db.Model(&model.AnalysisReport{}).
		Where("defect_id = ? AND status = ?", id, model.AnalysisStatusCompleted).
		Update("status", model.AnalysisStatusSuperseded)

	if err := h.db.Preload("Assignee").Preload("Reporter").First(&defect, id).Error; err != nil {
		response.ServerError(c, "查询缺陷失败")
		return
	}
	response.Success(c, defect)
}

// VerifyDefect 验证缺陷
func (h *DefectHandler) VerifyDefect(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	userID := middleware.GetUserID(c)
	var req struct {
		Passed  bool   `json:"passed"`
		Comment string `json:"comment"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	// 检查当前缺陷状态
	var defect model.Defect
	if err := h.db.First(&defect, id).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}
	if defect.Status != model.DefectStatusPendingVerify {
		response.Conflict(c, fmt.Sprintf("当前状态 [%s] 不允许验证操作，需要 [pending_verify]", defect.Status))
		return
	}

	var newStatus string
	if req.Passed {
		newStatus = model.DefectStatusFixed
	} else {
		newStatus = model.DefectStatusPendingFix
	}

	result := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", id, model.DefectStatusPendingVerify).Update("status", newStatus)
	if result.Error != nil {
		response.ServerError(c, "更新缺陷状态失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "缺陷状态已变更，请刷新后重试")
		return
	}

	if err := h.db.Create(&model.StatusChange{
		DefectID:   id,
		FromStatus: defect.Status,
		ToStatus:   newStatus,
		ChangedBy:  userID,
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create verify status change record failed: %v", err)
	}

	content := "✅ 验证通过"
	if !req.Passed {
		content = "❌ 验证失败"
	}
	if req.Comment != "" {
		content += "\n" + req.Comment
	}
	if err := h.db.Create(&model.Comment{
		DefectID: id,
		UserID:   userID,
		Content:  content,
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create verify comment failed: %v", err)
	}

	if err := h.db.Preload("Assignee").Preload("Reporter").First(&defect, id).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}
	response.Success(c, gin.H{"defect": defect, "status": newStatus})
}

// RejectDefect 驳回缺陷
func (h *DefectHandler) RejectDefect(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	userID := middleware.GetUserID(c)
	var req struct {
		Reason string `json:"reason" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	var defect model.Defect
	if err := h.db.Select("id, status").First(&defect, id).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}
	if !model.IsValidDefectTransition(defect.Status, model.DefectStatusRejected) {
		response.Conflict(c, fmt.Sprintf("当前状态 [%s] 不允许驳回", defect.Status))
		return
	}

	result := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", id, defect.Status).Update("status", model.DefectStatusRejected)
	if result.Error != nil {
		response.ServerError(c, "驳回缺陷失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "缺陷状态已变更，请刷新后重试")
		return
	}
	if err := h.db.Create(&model.StatusChange{
		DefectID:   id,
		FromStatus: defect.Status,
		ToStatus:   model.DefectStatusRejected,
		ChangedBy:  userID,
		Comment:    req.Reason,
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create reject status change failed: %v", err)
	}
	if err := h.db.Create(&model.Comment{
		DefectID: id,
		UserID:   userID,
		Content:  fmt.Sprintf("🚫 驳回原因: %s", req.Reason),
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create reject comment failed: %v", err)
	}

	response.Success(c, gin.H{"status": model.DefectStatusRejected})
}

type mergePRResult struct {
	mergedPRs []string
	failedPRs []string
}

func (h *DefectHandler) MergeDefect(c *gin.Context) {
	id, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的缺陷 ID")
		return
	}
	userID := middleware.GetUserID(c)

	var req struct {
		MergeMethod string `json:"mergeMethod"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		logger.Debugf("[DefectHandler] bind merge request params failed (using defaults): %v", err)
	}

	var defect model.Defect
	if err := h.db.First(&defect, id).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}
	if defect.Status != model.DefectStatusFixed {
		response.Conflict(c, fmt.Sprintf("当前状态 [%s] 不允许合并操作，需要 [fixed]", defect.Status))
		return
	}

	var fixTasks []model.FixTask
	if err := h.db.Where("defect_id = ? AND pr_url != ''", id).Order("created_at DESC").Find(&fixTasks).Error; err != nil {
		logger.Errorf("[DefectHandler] query fix tasks failed: %v", err)
	}

	if len(fixTasks) == 0 {
		h.completeDefectWithoutPR(c, id, defect.Status, userID)
		return
	}

	prResult := h.mergeFixTaskPRs(defect, fixTasks, req.MergeMethod)

	if len(prResult.failedPRs) > 0 && len(prResult.mergedPRs) == 0 {
		response.BadRequest(c, fmt.Sprintf("所有PR合并失败: %v", prResult.failedPRs))
		return
	}

	h.finalizeDefectMerge(c, id, userID, prResult)
}

func (h *DefectHandler) completeDefectWithoutPR(c *gin.Context, defectID uint, fromStatus string, userID uint) {
	result := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", defectID, model.DefectStatusFixed).Update("status", model.DefectStatusCompleted)
	if result.Error != nil {
		logger.Errorf("[DefectHandler] update defect status to completed failed: %v", result.Error)
		response.ServerError(c, "更新缺陷状态失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "缺陷状态已变更，请刷新后重试")
		return
	}
	if err := h.db.Create(&model.StatusChange{
		DefectID:   defectID,
		FromStatus: fromStatus,
		ToStatus:   model.DefectStatusCompleted,
		ChangedBy:  userID,
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create merge status change record failed: %v", err)
	}
	if err := h.db.Create(&model.Comment{
		DefectID: defectID,
		UserID:   userID,
		Content:  "✅ 缺陷已完成（无关联PR，直接关闭）",
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create complete comment failed: %v", err)
	}

	var defect model.Defect
	if err := h.db.Preload("Assignee").Preload("Reporter").First(&defect, defectID).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}
	response.Success(c, gin.H{"defect": defect, "status": model.DefectStatusCompleted, "merged": false})
}

func (h *DefectHandler) mergeFixTaskPRs(defect model.Defect, fixTasks []model.FixTask, mergeMethod string) mergePRResult {
	var result mergePRResult
	if mergeMethod == "" {
		mergeMethod = "merge"
	}

	for _, task := range fixTasks {
		if task.PRURL == "" {
			continue
		}

		projectRepo, ok := h.resolveProjectRepo(defect.IterationID)
		if !ok {
			result.failedPRs = append(result.failedPRs, task.PRURL)
			continue
		}

		provider, ownerRepo, baseURL := vcs.DetectVCSProvider(projectRepo.RepoURL)
		vcsToken := resolveVCSTokenFromDB(h.db, defect, projectRepo)

		var prNumber string
		if task.PRNumber != "" {
			prNumber = task.PRNumber
		} else {
			prNumber = extractPRNumberFromURL(task.PRURL)
		}
		if prNumber == "" {
			result.failedPRs = append(result.failedPRs, task.PRURL)
			continue
		}

		opts := &vcs.MergeOptions{
			CommitTitle:   fmt.Sprintf("fix(BUG-%s): %s", defect.Code, defect.Title),
			MergeMethod:   mergeMethod,
			CommitMessage: fmt.Sprintf("Merged by BugAgent for defect BUG-%s", defect.Code),
		}

		merged := h.mergeSinglePR(provider, ownerRepo, baseURL, vcsToken, prNumber, opts)
		if merged {
			result.mergedPRs = append(result.mergedPRs, task.PRURL)
		} else {
			result.failedPRs = append(result.failedPRs, task.PRURL)
		}
	}
	return result
}

func (h *DefectHandler) resolveProjectRepo(iterationID uint) (model.ProjectRepo, bool) {
	var iteration model.Iteration
	if err := h.db.Select("id, project_id").Where("id = ?", iterationID).First(&iteration).Error; err != nil {
		logger.Errorf("[DefectHandler] query iteration failed: %v", err)
		return model.ProjectRepo{}, false
	}

	var iterationRepos []model.IterationRepo
	if err := h.db.Where("iteration_id = ?", iterationID).Find(&iterationRepos).Error; err != nil {
		logger.Errorf("[DefectHandler] query iteration repos failed: %v", err)
		return model.ProjectRepo{}, false
	}
	if len(iterationRepos) == 0 || iterationRepos[0].RepoID == nil {
		return model.ProjectRepo{}, false
	}

	var projectRepo model.ProjectRepo
	if err := h.db.First(&projectRepo, *iterationRepos[0].RepoID).Error; err != nil {
		return model.ProjectRepo{}, false
	}
	return projectRepo, true
}

func (h *DefectHandler) mergeSinglePR(provider, ownerRepo, baseURL, vcsToken, prNumber string, opts *vcs.MergeOptions) bool {
	switch provider {
	case "github":
		client := vcs.NewGitHubClient(vcsToken)
		parts := strings.Split(ownerRepo, "/")
		if len(parts) != 2 {
			return false
		}
		if _, err := client.MergePR(parts[0], parts[1], prNumber, opts); err != nil {
			logger.Errorf("[MergeDefect] GitHub merge failed: %v", err)
			return false
		}
		return true
	case "gitlab":
		client := vcs.NewGitLabClient(vcsToken, baseURL)
		if _, err := client.MergePR(ownerRepo, prNumber, opts); err != nil {
			logger.Errorf("[MergeDefect] GitLab merge failed: %v", err)
			return false
		}
		return true
	default:
		return false
	}
}

func (h *DefectHandler) finalizeDefectMerge(c *gin.Context, defectID uint, userID uint, prResult mergePRResult) {
	result := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", defectID, model.DefectStatusFixed).Update("status", model.DefectStatusCompleted)
	if result.Error != nil {
		response.ServerError(c, "更新缺陷状态失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "状态已变更，请刷新后重试")
		return
	}

	if err := h.db.Create(&model.StatusChange{
		DefectID:   defectID,
		FromStatus: model.DefectStatusFixed,
		ToStatus:   model.DefectStatusCompleted,
		ChangedBy:  userID,
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create merge status change record failed: %v", err)
	}

	commentContent := "✅ 代码已合并，缺陷已完成"
	if len(prResult.mergedPRs) > 0 {
		commentContent += fmt.Sprintf("\n已合并PR: %s", strings.Join(prResult.mergedPRs, ", "))
	}
	if len(prResult.failedPRs) > 0 {
		commentContent += fmt.Sprintf("\n⚠️ 部分PR合并失败: %s", strings.Join(prResult.failedPRs, ", "))
	}

	if err := h.db.Create(&model.Comment{
		DefectID: defectID,
		UserID:   userID,
		Content:  commentContent,
	}).Error; err != nil {
		logger.Errorf("[DefectHandler] create merge comment failed: %v", err)
	}

	var defect model.Defect
	if err := h.db.Preload("Assignee").Preload("Reporter").First(&defect, defectID).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}
	response.Success(c, gin.H{
		"defect":    defect,
		"status":    model.DefectStatusCompleted,
		"merged":    len(prResult.mergedPRs) > 0,
		"mergedPRs": prResult.mergedPRs,
		"failedPRs": prResult.failedPRs,
	})
}

func extractPRNumberFromURL(prURL string) string {
	parts := strings.Split(prURL, "/")
	for i := len(parts) - 1; i >= 0; i-- {
		if _, err := strconv.Atoi(parts[i]); err == nil {
			return parts[i]
		}
	}
	return ""
}

func resolveVCSTokenFromDB(db *gorm.DB, defect model.Defect, projectRepo model.ProjectRepo) string {
	if projectRepo.CredentialID != nil && *projectRepo.CredentialID > 0 {
		auth, _, err := service.LoadGitAuthFromCredential(db, *projectRepo.CredentialID)
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
