package handler

import (
	"bug-agent/internal/middleware"
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"fmt"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type WorkflowHandler struct {
	svc *service.WorkflowService
}

func NewWorkflowHandler(db *gorm.DB) *WorkflowHandler {
	return &WorkflowHandler{svc: service.NewWorkflowService(db)}
}

func (h *WorkflowHandler) TransitionStatus(c *gin.Context) {
	userID := middleware.GetUserID(c)
	defectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}

	var req struct {
		ToStatus string `json:"toStatus" binding:"required"`
		Comment  string `json:"comment"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: toStatus 为必填项")
		return
	}

	transitionReq := &service.TransitionRequest{
		DefectID: uint(defectID),
		ToStatus: req.ToStatus,
		Comment:  req.Comment,
		UserID:   userID,
	}

	change, err := h.svc.Transition(transitionReq)
	if err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	response.Success(c, gin.H{
		"message": "状态已变更",
		"data":    change,
	})
}

func (h *WorkflowHandler) GetHistory(c *gin.Context) {
	defectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}

	history, err := h.svc.GetHistory(uint(defectID))
	if err != nil {
		response.ServerError(c, "获取历史记录失败")
		return
	}

	response.Success(c, history)
}

func (h *WorkflowHandler) GetTransitions(c *gin.Context) {
	defectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}

	transitions, err := h.svc.GetAvailableTransitions(uint(defectID))
	if err != nil {
		response.NotFound(c, "缺陷不存在")
		return
	}

	response.Success(c, transitions)
}

func (h *WorkflowHandler) BatchTransition(c *gin.Context) {
	userID := middleware.GetUserID(c)

	var req struct {
		DefectIDs []uint `json:"defectIds" binding:"required,min=1,max=100"`
		ToStatus  string `json:"toStatus" binding:"required"`
		Comment   string `json:"comment"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误")
		return
	}

	if len(req.DefectIDs) > 100 {
		response.BadRequest(c, "单次批量操作不能超过 100 个缺陷")
		return
	}

	successes, errs := h.svc.BatchTransition(req.DefectIDs, req.ToStatus, userID, req.Comment)
	response.Success(c, gin.H{
		"message":   fmt.Sprintf("已转换 %d/%d 个缺陷", successes, len(req.DefectIDs)),
		"successes": successes,
		"errors":    errs,
	})
}
