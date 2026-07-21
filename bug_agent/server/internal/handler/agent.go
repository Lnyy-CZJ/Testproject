package handler

import (
	"bug-agent/internal/adk"
	"bug-agent/internal/asyncx"
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/internal/sse"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gin-gonic/gin/binding"
	"gorm.io/gorm"
)

type AgentHandler struct {
	db              *gorm.DB
	analysisService *adk.ADKAnalysisService
	scheduler       *adk.AgentScheduler
}

func NewAgentHandler(db *gorm.DB, analysisService *adk.ADKAnalysisService, scheduler *adk.AgentScheduler) *AgentHandler {
	return &AgentHandler{
		db:              db,
		analysisService: analysisService,
		scheduler:       scheduler,
	}
}

type TriggerAnalysisRequest struct {
	DefectID   uint     `json:"defectId" binding:"required"`
	AgentTypes []string `json:"agentTypes"`
}

func (h *AgentHandler) TriggerAnalysis(c *gin.Context) {
	var req TriggerAnalysisRequest
	if err := c.ShouldBindBodyWith(&req, binding.JSON); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	var defect model.Defect
	if err := h.db.First(&defect, req.DefectID).Error; err != nil {
		response.NotFound(c, "缺陷不存在")
		return
	}

	if defect.Status == model.DefectStatusAnalyzing {
		response.Conflict(c, "缺陷正在分析中，请勿重复触发")
		return
	}

	allowedStatuses := map[string]bool{
		model.DefectStatusPendingAssign:   true,
		model.DefectStatusPendingAnalysis: true,
		model.DefectStatusPendingFix:      true,
		model.DefectStatusReopened:        true,
		model.DefectStatusRejected:        true,
	}
	if !allowedStatuses[defect.Status] {
		response.Conflict(c, fmt.Sprintf("当前缺陷状态[%s]不允许触发分析", defect.Status))
		return
	}

	if len(req.AgentTypes) == 0 {
		req.AgentTypes = []string{"frontend"}
	}

	analysisReq := adk.ADKAnalysisRequest{
		DefectID:   req.DefectID,
		AgentTypes: req.AgentTypes,
		UserID:     middleware.GetUserID(c),
	}

	if h.scheduler != nil {
		taskID := fmt.Sprintf("task_%d_%d", req.DefectID, time.Now().UnixMilli())
		statusUpdate := h.db.Model(&model.Defect{}).
			Where("id = ? AND status IN ?", req.DefectID, []string{
				model.DefectStatusPendingAssign,
				model.DefectStatusPendingAnalysis,
				model.DefectStatusPendingFix,
				model.DefectStatusReopened,
				model.DefectStatusRejected,
			}).
			Update("status", model.DefectStatusPendingAnalysis)
		if statusUpdate.Error != nil {
			response.ServerError(c, "更新分析排队状态失败: "+statusUpdate.Error.Error())
			return
		}
		if statusUpdate.RowsAffected == 0 {
			response.Conflict(c, "缺陷状态已变更，请刷新后重试")
			return
		}

		ctx, cancel := context.WithTimeout(asyncx.ShutdownContext(), 10*time.Minute)
		task := &adk.AnalysisTask{
			ID:         taskID,
			DefectID:   req.DefectID,
			AgentTypes: req.AgentTypes,
			Priority:   adk.PriorityUser,
			Ctx:        ctx,
			Cancel:     cancel,
		}
		if err := h.scheduler.Submit(task); err != nil {
			cancel()
			if rollbackErr := h.db.Model(&model.Defect{}).
				Where("id = ? AND status = ?", req.DefectID, model.DefectStatusPendingAnalysis).
				Update("status", defect.Status).Error; rollbackErr != nil {
				logger.Errorf("[AgentHandler] rollback queued analysis status failed: defect=%d err=%v", req.DefectID, rollbackErr)
			}
			response.BadRequest(c, err.Error())
			return
		}
		response.Success(c, gin.H{
			"message":    "分析任务已排队",
			"defectId":   req.DefectID,
			"agentTypes": req.AgentTypes,
			"taskId":     taskID,
			"status":     "queued",
		})
		return
	} else {
		asyncx.Go(func() {
			ctx, cancel := context.WithTimeout(asyncx.ShutdownContext(), 10*time.Minute)
			defer cancel()
			result, err := h.analysisService.PerformAnalysis(ctx, analysisReq)
			if err != nil {
				logger.Errorf("[AgentHandler] 分析失败: 缺陷 #%d, 错误: %v", req.DefectID, err)
				rollbackResult := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", req.DefectID, model.DefectStatusAnalyzing).Update("status", model.DefectStatusPendingAssign)
				if rollbackResult.Error != nil {
					logger.Errorf("update failed: %v", rollbackResult.Error)
				}
				sse.Notifier.NotifyAnalysisFailed(req.DefectID, err.Error())
				if rollbackResult.RowsAffected > 0 && defect.ReporterID > 0 {
					if err := h.db.Create(&model.Comment{
						DefectID:       req.DefectID,
						UserID:         defect.ReporterID,
						AgentType:      "system",
						IsAgentMessage: true,
						Content:        "⚠️ AI分析失败，状态已回退到待分析。请稍后重试或联系管理员。",
					}).Error; err != nil {
						logger.Errorf("create comment failed: %v", err)
					}
				}
				return
			}
			logger.Infof("[AgentHandler] 分析完成: 报告=%s, 耗时=%v", result.ReportCode, result.Duration)
		})
	}

	response.Success(c, gin.H{
		"message":    "分析任务已启动",
		"defectId":   req.DefectID,
		"agentTypes": req.AgentTypes,
		"status":     "analyzing",
	})
}

func (h *AgentHandler) TriggerAnalysisStream(c *gin.Context) {
	var req TriggerAnalysisRequest
	if err := c.ShouldBindBodyWith(&req, binding.JSON); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	fmt.Printf("[AGENT_DEBUG] TriggerAnalysisStream called: defect=%d agentTypes=%v\n", req.DefectID, req.AgentTypes)

	var defect model.Defect
	if err := h.db.First(&defect, req.DefectID).Error; err != nil {
		response.NotFound(c, "缺陷不存在")
		return
	}

	if defect.Status == model.DefectStatusAnalyzing {
		response.Conflict(c, "缺陷正在分析中，请勿重复触发")
		return
	}

	allowedStatuses := map[string]bool{
		model.DefectStatusPendingAssign:   true,
		model.DefectStatusPendingAnalysis: true,
		model.DefectStatusPendingFix:      true,
		model.DefectStatusReopened:        true,
		model.DefectStatusRejected:        true,
	}
	if !allowedStatuses[defect.Status] {
		response.Conflict(c, fmt.Sprintf("当前缺陷状态[%s]不允许触发分析", defect.Status))
		return
	}

	if len(req.AgentTypes) == 0 {
		req.AgentTypes = []string{"frontend"}
	}
	if len(req.AgentTypes) > 1 {
		response.BadRequest(c, "流式分析一次只支持一个 Agent，请使用非流式分析触发多 Agent 分析")
		return
	}

	analysisReq := adk.ADKAnalysisRequest{
		DefectID:   req.DefectID,
		AgentTypes: req.AgentTypes,
		UserID:     middleware.GetUserID(c),
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 10*time.Minute)
	defer cancel()

	events, err := h.analysisService.PerformAnalysisStream(ctx, analysisReq)
	if err != nil {
		response.ServerError(c, "启动流式分析失败: "+err.Error())
		return
	}

	adk.StreamToSSE(events, c.Writer)
}

func (h *AgentHandler) GetAnalysisReport(c *gin.Context) {
	reportID := c.Param("reportId")

	var report model.AnalysisReport
	if err := h.db.Preload("Defect").First(&report, reportID).Error; err != nil {
		response.NotFound(c, "分析报告不存在")
		return
	}

	response.Success(c, report)
}

func (h *AgentHandler) GetDefectAnalysisReports(c *gin.Context) {
	defectIDStr := c.Param("id")
	defectID, err := strconv.ParseUint(defectIDStr, 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}

	var reports []model.AnalysisReport
	err = h.db.Where("defect_id = ?", defectID).
		Order("created_at DESC").
		Find(&reports).Error

	if err != nil {
		response.ServerError(c, "查询失败")
		return
	}

	response.SuccessPage(c, reports, int64(len(reports)), 1, len(reports))
}

func (h *AgentHandler) CancelAnalysis(c *gin.Context) {
	defectIDStr := c.Param("id")
	defectID, err := strconv.ParseUint(defectIDStr, 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}

	cancelled := h.analysisService.CancelAnalysis(uint(defectID))
	if h.scheduler != nil {
		if h.scheduler.Cancel(uint(defectID)) {
			cancelled = true
		}
	}

	if cancelled {
		response.Success(c, gin.H{"message": "已取消"})
	} else {
		response.NotFound(c, "未找到运行中的分析")
	}
}

func (h *AgentHandler) QueueStatus(c *gin.Context) {
	if h.scheduler == nil {
		response.Success(c, []interface{}{})
		return
	}
	status := h.scheduler.QueueStatus()
	response.Success(c, status)
}

func (h *AgentHandler) AnalysisHistory(c *gin.Context) {
	defectIDStr := c.Param("id")
	defectID, err := strconv.ParseUint(defectIDStr, 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}

	var reports []model.AnalysisReport
	if err := h.db.Where("defect_id = ?", defectID).
		Order("created_at DESC").
		Find(&reports).Error; err != nil {
		response.ServerError(c, "查询分析历史失败")
		return
	}

	response.Success(c, reports)
}
