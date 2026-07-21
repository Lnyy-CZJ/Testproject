package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type ManualFixHandler struct {
	db     *gorm.DB
	service *service.ManualFixService
}

func NewManualFixHandler(db *gorm.DB) *ManualFixHandler {
	return &ManualFixHandler{
		db:      db,
		service: service.NewManualFixService(db),
	}
}

func (h *ManualFixHandler) StartManualFix(c *gin.Context) {
	defectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}

	userID := getUserID(c)
	if err := h.service.StartManualFix(uint(defectID), userID); err != nil {
		if strings.Contains(err.Error(), "不存在") {
			response.NotFound(c, err.Error())
		} else {
			response.Conflict(c, err.Error())
		}
		return
	}

	response.Success(c, gin.H{"message": "已开始人工修复"})
}

func (h *ManualFixHandler) CompleteManualFix(c *gin.Context) {
	defectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}

	var req service.CompleteManualFixRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	userID := getUserID(c)
	if err := h.service.CompleteManualFix(uint(defectID), req, userID); err != nil {
		if strings.Contains(err.Error(), "不存在") {
			response.NotFound(c, err.Error())
		} else {
			response.Conflict(c, err.Error())
		}
		return
	}

	response.Success(c, gin.H{"message": "人工修复已完成"})
}

func (h *ManualFixHandler) AbandonManualFix(c *gin.Context) {
	defectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的缺陷ID")
		return
	}

	userID := getUserID(c)
	if err := h.service.AbandonManualFix(uint(defectID), userID); err != nil {
		if strings.Contains(err.Error(), "不存在") {
			response.NotFound(c, err.Error())
		} else {
			response.Conflict(c, err.Error())
		}
		return
	}

	response.Success(c, gin.H{"message": "已放弃人工修复"})
}

func (h *ManualFixHandler) UpdateFixTaskPR(c *gin.Context) {
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

	var req struct {
		PRURL string `json:"prUrl"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	if err := h.service.UpdateFixTaskPR(uint(defectID), uint(taskID), req.PRURL); err != nil {
		response.ServerErrorWithLog(c, err, "操作失败")
		return
	}

	response.Success(c, gin.H{"message": "PR信息已更新"})
}
