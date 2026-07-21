package handler

import (
	"bug-agent/internal/adk"
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"encoding/json"
	"fmt"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type FixTaskHandler struct {
	db         *gorm.DB
	fixService *adk.ADKFixService
}

func NewFixTaskHandler(db *gorm.DB, fixService *adk.ADKFixService) *FixTaskHandler {
	return &FixTaskHandler{db: db, fixService: fixService}
}

func (h *FixTaskHandler) CreateFixTask(c *gin.Context) {
	defectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}
	operatorID := getUserID(c)

	var req struct {
		AgentType    string `json:"agentType"`
		TargetBranch string `json:"targetBranch"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	var defect model.Defect
	if err := h.db.First(&defect, defectID).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			response.NotFound(c, "缺陷不存在")
			return
		}
		response.ServerError(c, "查询缺陷失败")
		return
	}

	statusResult := h.db.Model(&model.Defect{}).
		Where("id = ? AND status = ?", defect.ID, model.DefectStatusPendingFix).
		Update("status", model.DefectStatusFixing)
	if statusResult.Error != nil {
		response.ServerErrorWithLog(c, statusResult.Error, "更新缺陷状态失败")
		return
	}
	if statusResult.RowsAffected == 0 {
		response.Conflict(c, "当前缺陷状态不允许创建修复任务")
		return
	}

	result, err := h.fixService.CreateAutoFixGroup(c.Request.Context(), service.FixRequest{
		DefectID:     uint(defectID),
		AgentType:    req.AgentType,
		TargetBranch: req.TargetBranch,
		UserID:       operatorID,
	})
	if err != nil {
		rollbackResult := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", defectID, model.DefectStatusFixing).Update("status", model.DefectStatusPendingFix)
		if rollbackResult.Error != nil {
			logger.Errorf("[FixTaskHandler] 状态回滚失败: %v", rollbackResult.Error)
		}
		response.ServerErrorWithLog(c, err, "创建修复任务失败")
		return
	}

	response.Created(c, gin.H{
		"message":  "修复任务已提交，请通过轮询获取进度",
		"defectId": defectID,
		"groupId":  result.GroupID,
		"taskCode": result.TaskCode,
		"status":   result.Status,
		"units":    result.Units,
	})
}

func (h *FixTaskHandler) ListFixTasks(c *gin.Context) {
	defectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}

	var tasks []model.FixTask
	err := h.db.Where("defect_id = ?", defectID).
		Order("created_at DESC").
		Find(&tasks).Error

	if err != nil {
		response.ServerError(c, "查询失败")
		return
	}

	response.SuccessPage(c, tasks, int64(len(tasks)), 1, len(tasks))
}

func (h *FixTaskHandler) ListFixTaskGroups(c *gin.Context) {
	defectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}

	var groups []model.FixTaskGroup
	err := h.db.Preload("Units", func(db *gorm.DB) *gorm.DB {
		return db.Order("created_at ASC")
	}).
		Preload("Units.ProjectRepo").
		Where("defect_id = ?", defectID).
		Order("created_at DESC").
		Find(&groups).Error
	if err != nil {
		response.ServerError(c, "查询失败")
		return
	}

	response.SuccessPage(c, groups, int64(len(groups)), 1, len(groups))
}

func (h *FixTaskHandler) GetFixTask(c *gin.Context) {
	taskID, ok := parseIDParam(c, "taskId")
	if !ok {
		return
	}

	var task model.FixTask
	err := h.db.Preload("Defect").First(&task, taskID).Error
	if err != nil {
		response.NotFound(c, "修复任务不存在")
		return
	}

	response.Success(c, task)
}

func (h *FixTaskHandler) UpdateFixTaskStatus(c *gin.Context) {
	taskID, ok := parseIDParam(c, "taskId")
	if !ok {
		return
	}

	var req struct {
		Status string `json:"status" binding:"required"`
		Plan   string `json:"plan"`
		Result string `json:"result"`
		PRURL  string `json:"prUrl"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	validTaskStatuses := map[string]bool{
		model.FixTaskStatusPlanning:              true,
		model.FixTaskStatusExecuting:             true,
		model.FixTaskStatusTesting:               true,
		model.FixTaskStatusCompleted:             true,
		model.FixTaskStatusNoChanges:             true,
		model.FixTaskStatusCompletedWithWarnings: true,
		model.FixTaskStatusFailed:                true,
		model.FixTaskStatusCancelled:             true,
	}
	if !validTaskStatuses[req.Status] {
		response.BadRequest(c, "无效的任务状态")
		return
	}

	// 校验状态转换合法性
	var currentTask model.FixTask
	if err := h.db.Select("id, status").First(&currentTask, taskID).Error; err != nil {
		response.NotFound(c, "修复任务不存在")
		return
	}
	allowedFixTaskTransitions := map[string]map[string]bool{
		model.FixTaskStatusPending: {
			model.FixTaskStatusPlanning:  true,
			model.FixTaskStatusFailed:    true,
			model.FixTaskStatusCancelled: true,
		},
		model.FixTaskStatusPlanning: {
			model.FixTaskStatusExecuting: true,
			model.FixTaskStatusFailed:    true,
			model.FixTaskStatusCancelled: true,
		},
		model.FixTaskStatusExecuting: {
			model.FixTaskStatusTesting:   true,
			model.FixTaskStatusFailed:    true,
			model.FixTaskStatusCancelled: true,
		},
		model.FixTaskStatusTesting: {
			model.FixTaskStatusCompleted:             true,
			model.FixTaskStatusNoChanges:             true,
			model.FixTaskStatusCompletedWithWarnings: true,
			model.FixTaskStatusFailed:                true,
			model.FixTaskStatusCancelled:             true,
		},
	}
	if transitions, ok := allowedFixTaskTransitions[currentTask.Status]; ok {
		if !transitions[req.Status] {
			response.Conflict(c, fmt.Sprintf("不允许从 [%s] 转换到 [%s]", currentTask.Status, req.Status))
			return
		}
	} else if currentTask.Status != req.Status {
		// 已终态（completed/failed/cancelled）不允许再转换
		response.Conflict(c, fmt.Sprintf("当前状态 [%s] 不允许状态变更", currentTask.Status))
		return
	}

	updates := map[string]interface{}{"Status": req.Status}
	if req.Plan != "" {
		updates["Plan"] = req.Plan
	}
	if req.Result != "" {
		updates["Result"] = req.Result
	}
	if req.PRURL != "" {
		updates["PRURL"] = req.PRURL
	}

	if req.Status == model.FixTaskStatusCompleted || req.Status == model.FixTaskStatusNoChanges || req.Status == model.FixTaskStatusCompletedWithWarnings || req.Status == model.FixTaskStatusFailed {
		now := time.Now()
		updates["CompletedAt"] = now
	}

	result := h.db.Model(&model.FixTask{}).Where("id = ? AND status = ?", taskID, currentTask.Status).Updates(updates)
	if result.Error != nil {
		response.ServerError(c, "更新修复任务失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "任务状态已变更，请刷新后重试")
		return
	}

	if req.Status == model.FixTaskStatusCompleted || req.Status == model.FixTaskStatusCompletedWithWarnings {
		var ft model.FixTask
		if err := h.db.First(&ft, taskID).Error; err != nil {
			logger.Errorf("query fix task failed: %v", err)
		} else if ft.DefectID > 0 {
			var currentDefect model.Defect
			if err := h.db.Select("status").First(&currentDefect, ft.DefectID).Error; err != nil {
				logger.Errorf("query defect status failed: %v", err)
			} else if model.IsValidDefectTransition(currentDefect.Status, model.DefectStatusPendingVerify) {
				defectResult := h.db.Model(&model.Defect{}).Where("id = ? AND status = ?", ft.DefectID, currentDefect.Status).Update("status", model.DefectStatusPendingVerify)
				if defectResult.Error != nil {
					logger.Errorf("update defect status failed: %v", defectResult.Error)
				} else if defectResult.RowsAffected == 0 {
					logger.Infof("defect %d status already changed, skipping status update to pending_verify", ft.DefectID)
				}
			} else {
				logger.Infof("invalid defect transition %s -> %s for defect %d, skipping status update",
					currentDefect.Status, model.DefectStatusPendingVerify, ft.DefectID)
			}
		}
	}

	var updatedTask model.FixTask
	if err := h.db.Preload("Defect").First(&updatedTask, taskID).Error; err != nil {
		response.ServerError(c, "查询更新后的修复任务失败")
		return
	}

	response.Success(c, updatedTask)
}

func (h *FixTaskHandler) GetFixTaskProgress(c *gin.Context) {
	taskIDStr := c.Param("taskId")
	taskID, err := strconv.ParseUint(taskIDStr, 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的任务ID")
		return
	}

	var task model.FixTask
	err = h.db.First(&task, taskID).Error
	if err != nil {
		response.NotFound(c, "修复任务不存在")
		return
	}

	var steps []map[string]interface{}
	if task.Plan != "" {
		if err := json.Unmarshal([]byte(task.Plan), &steps); err != nil {
			logger.Errorf("[FixTaskHandler] unmarshal plan failed: %v", err)
			steps = nil
		}
	}

	completedCount := 0
	for _, step := range steps {
		if status, ok := step["status"].(string); ok && status == "completed" {
			completedCount++
		}
	}
	progress := 0
	if len(steps) > 0 {
		progress = int(float64(completedCount) / float64(len(steps)) * 100)
	}

	response.Success(c, gin.H{
		"taskCode":   task.TaskCode,
		"status":     task.Status,
		"progress":   progress,
		"totalSteps": len(steps),
		"completed":  completedCount,
		"steps":      steps,
		"prUrl":      task.PRURL,
	})
}
