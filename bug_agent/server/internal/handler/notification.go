package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type NotificationHandler struct {
	svc *service.NotificationService
	db  *gorm.DB
}

func NewNotificationHandler(db *gorm.DB, svc *service.NotificationService) *NotificationHandler {
	return &NotificationHandler{svc: svc, db: db}
}

func (h *NotificationHandler) List(c *gin.Context) {
	userID, ok := getUserIDFromContext(c)
	if !ok {
		response.Unauthorized(c, "未登录")
		return
	}
	page, pageSize := parsePagination(c, 100)

	list, total, err := h.svc.GetByUser(userID, page, pageSize)
	if err != nil {
		response.ServerError(c, "获取通知列表失败")
		return
	}

	response.SuccessPage(c, list, total, page, pageSize)
}

func (h *NotificationHandler) UnreadCount(c *gin.Context) {
	userID, ok := getUserIDFromContext(c)
	if !ok {
		response.Unauthorized(c, "未登录")
		return
	}

	count, err := h.svc.GetUnreadCount(userID)
	if err != nil {
		response.ServerError(c, "获取未读数失败")
		return
	}

	response.Success(c, gin.H{"count": count})
}

func (h *NotificationHandler) MarkRead(c *gin.Context) {
	userID, ok := getUserIDFromContext(c)
	if !ok {
		response.Unauthorized(c, "未登录")
		return
	}

	var req struct {
		IDs []uint `json:"ids" binding:"required,max=100"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "ids 不能为空")
		return
	}
	// binding:"max=100" 对 slice 不生效，需手动校验长度
	if len(req.IDs) > 100 {
		response.BadRequest(c, "ids 数量不能超过 100")
		return
	}

	affected, err := h.svc.MarkRead(userID, req.IDs)
	if err != nil {
		response.ServerError(c, "标记已读失败")
		return
	}

	response.Success(c, gin.H{"affectedRows": affected})
}

func (h *NotificationHandler) MarkAllRead(c *gin.Context) {
	userID, ok := getUserIDFromContext(c)
	if !ok {
		response.Unauthorized(c, "未登录")
		return
	}

	affected, err := h.svc.MarkAllRead(userID)
	if err != nil {
		response.ServerError(c, "标记全部已读失败")
		return
	}

	response.Success(c, gin.H{"affectedRows": affected})
}

func (h *NotificationHandler) Send(c *gin.Context) {
	userID, ok := getUserIDFromContext(c)
	if !ok {
		response.Unauthorized(c, "未登录")
		return
	}
	if !isPlatformAdmin(h.db, userID) {
		response.Forbidden(c, "仅管理员可发送通知")
		return
	}

	var req service.NotifyRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误")
		return
	}

	if len(req.UserIDs) == 0 {
		response.BadRequest(c, "userIds 不能为空")
		return
	}
	if len(req.UserIDs) > 200 {
		response.BadRequest(c, "userIds 数量不能超过 200")
		return
	}

	notifications, err := h.svc.Send(&req)
	if err != nil {
		response.ServerErrorWithLog(c, err, "操作失败")
		return
	}

	response.Success(c, notifications)
}
