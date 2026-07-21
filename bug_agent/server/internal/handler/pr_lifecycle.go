package handler

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"fmt"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type PRLifecycleHandler struct {
	db                *gorm.DB
	vcsWebhookService *service.VCSWebhookService
}

func NewPRLifecycleHandler(db *gorm.DB) *PRLifecycleHandler {
	return &PRLifecycleHandler{
		db:                db,
		vcsWebhookService: service.NewVCSWebhookService(db),
	}
}

type ManualRejectPRRequest struct {
	RejectedBy   string `json:"rejectedBy"`
	RejectReason string `json:"rejectReason" binding:"required"`
}

func (h *PRLifecycleHandler) ManualRejectPR(c *gin.Context) {
	defectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}
	taskID, err := strconv.ParseUint(c.Param("taskId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的任务ID")
		return
	}

	var req ManualRejectPRRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	var task model.FixTask
	if err := h.db.First(&task, taskID).Error; err != nil {
		response.NotFound(c, "修复任务不存在")
		return
	}
	if task.DefectID != uint(defectID) {
		response.BadRequest(c, "修复任务不属于该缺陷")
		return
	}

	validRejectStatuses := map[string]bool{
		model.FixTaskStatusPending:  true,
		model.FixTaskStatusPlanning: true,
		model.FixTaskStatusExecuting: true,
		model.FixTaskStatusTesting:  true,
	}
	if !validRejectStatuses[task.Status] {
		response.Conflict(c, fmt.Sprintf("当前任务状态 [%s] 不允许拒绝操作", task.Status))
		return
	}

	if err := h.vcsWebhookService.HandleManualPRRejected(task, req.RejectedBy, req.RejectReason); err != nil {
		response.ServerErrorWithLog(c, err, "标记PR拒绝失败")
		return
	}

	response.Success(c, gin.H{"message": "PR已标记为拒绝"})
}

func (h *PRLifecycleHandler) ManualMergePR(c *gin.Context) {
	defectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}
	taskID, err := strconv.ParseUint(c.Param("taskId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的任务ID")
		return
	}

	var task model.FixTask
	if err := h.db.First(&task, taskID).Error; err != nil {
		response.NotFound(c, "修复任务不存在")
		return
	}
	if task.DefectID != uint(defectID) {
		response.BadRequest(c, "修复任务不属于该缺陷")
		return
	}

	if err := h.vcsWebhookService.HandleManualPRMerged(task); err != nil {
		response.ServerErrorWithLog(c, err, "标记PR合并失败")
		return
	}

	response.Success(c, gin.H{"message": "PR已标记为合并"})
}

func (h *PRLifecycleHandler) ListPRRejections(c *gin.Context) {
	taskID, err := strconv.ParseUint(c.Param("taskId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的任务ID")
		return
	}

	var rejections []model.PRRejection
	if err := h.db.Where("fix_task_id = ?", taskID).Order("created_at DESC").Find(&rejections).Error; err != nil {
		response.ServerError(c, "查询PR拒绝记录失败")
		return
	}

	response.Success(c, gin.H{
		"items": rejections,
		"total": len(rejections),
	})
}
