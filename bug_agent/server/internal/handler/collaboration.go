package handler

import (
	"bug-agent/internal/adk"
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/pkg/response"
	"errors"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type CollaborationHandler struct {
	db               *gorm.DB
	collaborationSvc *adk.ADKCollaborationService
}

func NewCollaborationHandler(db *gorm.DB, collaborationSvc *adk.ADKCollaborationService) *CollaborationHandler {
	return &CollaborationHandler{
		db:               db,
		collaborationSvc: collaborationSvc,
	}
}

func (h *CollaborationHandler) StartCollaboration(c *gin.Context) {
	var req adk.StartCollaborationRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	if req.DefectID == 0 {
		response.BadRequest(c, "缺陷ID不能为空")
		return
	}

	if h.collaborationSvc == nil {
		response.ServerError(c, "协作分析服务未初始化")
		return
	}

	req.TriggerUserID = middleware.GetUserID(c)

	task, err := h.collaborationSvc.StartCollaboration(c.Request.Context(), req)
	if err != nil {
		response.ServerErrorWithLog(c, err, "启动协作分析失败")
		return
	}

	response.Success(c, task)
}

func (h *CollaborationHandler) GetCollaborationTask(c *gin.Context) {
	taskIDStr := c.Param("taskId")
	taskID, err := strconv.ParseUint(taskIDStr, 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的任务ID")
		return
	}

	if h.collaborationSvc == nil {
		response.ServerError(c, "协作分析服务未初始化")
		return
	}

	task, err := h.collaborationSvc.GetCollaborationTask(uint(taskID))
	if err != nil {
		response.NotFound(c, "任务不存在")
		return
	}

	response.Success(c, task)
}

func (h *CollaborationHandler) GetDefectCollaborations(c *gin.Context) {
	defectIDStr := c.Param("id")
	defectID, err := strconv.ParseUint(defectIDStr, 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}

	if h.collaborationSvc == nil {
		response.ServerError(c, "协作分析服务未初始化")
		return
	}

	tasks, err := h.collaborationSvc.GetCollaborationTasksByDefect(uint(defectID))
	if err != nil {
		response.ServerError(c, "查询失败")
		return
	}

	response.Success(c, gin.H{
		"items": tasks,
		"total": len(tasks),
	})
}

func (h *CollaborationHandler) GetAggregatedReport(c *gin.Context) {
	taskIDStr := c.Param("taskId")
	taskID, err := strconv.ParseUint(taskIDStr, 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的任务ID")
		return
	}

	if h.collaborationSvc == nil {
		response.ServerError(c, "协作分析服务未初始化")
		return
	}

	report, err := h.collaborationSvc.GetAggregatedReport(uint(taskID))
	if err != nil {
		response.NotFound(c, "报告不存在")
		return
	}

	response.Success(c, report)
}

func (h *CollaborationHandler) ListCollaborationTasks(c *gin.Context) {
	projectIDStr := c.Query("projectId")
	defectIDStr := c.Query("defectId")

	var projectID uint64
	var err error

	if projectIDStr != "" {
		projectID, err = strconv.ParseUint(projectIDStr, 10, 64)
		if err != nil {
			response.BadRequest(c, "无效的 projectId")
			return
		}
	} else if defectIDStr != "" {
		// defectId 提供但 projectId 未提供时，自动查找缺陷所属项目
		defectID, err := strconv.ParseUint(defectIDStr, 10, 64)
		if err != nil {
			response.BadRequest(c, "无效的 defectId")
			return
		}
		var defect model.Defect
		if err := h.db.Select("id, iteration_id").Preload("Iteration").First(&defect, defectID).Error; err != nil {
			if errors.Is(err, gorm.ErrRecordNotFound) {
				response.NotFound(c, "缺陷不存在")
				return
			}
			response.ServerError(c, "查询缺陷失败")
			return
		}
		projectID = uint64(defect.Iteration.ProjectID)
	} else {
		response.BadRequest(c, "projectId 或 defectId 参数至少提供一个")
		return
	}

	page, pageSize := parsePagination(c, 100)

	var tasks []model.CollaborationTask
	var total int64

	query := h.db.Model(&model.CollaborationTask{}).
		Joins("JOIN defects ON defects.id = collaboration_tasks.defect_id").
		Joins("JOIN iterations ON iterations.id = defects.iteration_id").
		Where("iterations.project_id = ?", projectID)

	if status := c.Query("status"); status != "" {
		query = query.Where("collaboration_tasks.status = ?", status)
	}
	if defectIDStr != "" {
		if defectID, err := strconv.ParseUint(defectIDStr, 10, 64); err == nil {
			query = query.Where("collaboration_tasks.defect_id = ?", defectID)
		}
	}

	if err := query.Count(&total).Error; err != nil {
		response.ServerError(c, "查询总数失败")
		return
	}
	offset := (page - 1) * pageSize
	if err := query.Preload("Defect").
		Order("created_at DESC").
		Offset(offset).
		Limit(pageSize).
		Find(&tasks).Error; err != nil {
		response.ServerError(c, "查询失败")
		return
	}

	response.Success(c, gin.H{
		"items":    tasks,
		"total":    total,
		"page":     page,
		"pageSize": pageSize,
	})
}
