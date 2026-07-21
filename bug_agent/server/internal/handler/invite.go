package handler

import (
	"bug-agent/internal/config"
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type InviteHandler struct {
	inviteService *service.InviteService
}

func NewInviteHandler(db *gorm.DB) *InviteHandler {
	return &InviteHandler{
		inviteService: service.NewInviteService(db),
	}
}

func (h *InviteHandler) CreateInvite(c *gin.Context) {
	userID := getUserID(c)
	var req struct {
		MaxUses   int        `json:"maxUses"`
		ExpiresAt *time.Time `json:"expiresAt"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	if req.MaxUses < 0 {
		req.MaxUses = 0
	}
	invite, err := h.inviteService.GenerateCode(userID, req.MaxUses, req.ExpiresAt)
	if err != nil {
		response.ServerError(c, "生成邀请码失败")
		return
	}
	response.Created(c, invite)
}

func (h *InviteHandler) ListInvites(c *gin.Context) {
	userID := getUserID(c)
	codes, err := h.inviteService.ListCodes(userID)
	if err != nil {
		response.ServerError(c, "获取邀请码列表失败")
		return
	}
	response.Success(c, codes)
}

func (h *InviteHandler) AcceptInvite(c *gin.Context) {
	code := c.Param("code")
	userID := getUserID(c)

	var req struct {
		Mode     string `json:"mode"`
		Username string `json:"username"`
		Email    string `json:"email"`
		Password string `json:"password"`
		Nickname string `json:"nickname"`
	}
	_ = c.ShouldBindJSON(&req)

	if userID > 0 && req.Mode != "register" {
		if err := h.inviteService.AcceptCode(code, userID); err != nil {
			switch err {
			case service.ErrInviteCodeNotFound:
				response.NotFound(c, "邀请码不存在")
			case service.ErrInviteCodeExpired:
				response.BadRequest(c, "邀请码已过期")
			case service.ErrInviteCodeExhausted:
				response.BadRequest(c, "邀请码使用次数已达上限")
			default:
				response.ServerError(c, "接受邀请失败")
			}
			return
		}
		response.Success(c, gin.H{"message": "邀请接受成功"})
		return
	}

	// 未登录/注册模式：邀请码 + 注册信息
	if req.Username == "" || req.Email == "" || req.Password == "" {
		response.BadRequest(c, "缺少注册信息，请提供 username/email/password")
		return
	}
	if len(req.Password) < 8 {
		response.BadRequest(c, "密码长度至少8位")
		return
	}

	user, err := h.inviteService.RegisterWithInvite(code, req.Username, req.Email, req.Password, req.Nickname)
	if err != nil {
		switch err {
		case service.ErrInviteCodeNotFound:
			response.NotFound(c, "邀请码不存在")
		case service.ErrInviteCodeExpired:
			response.BadRequest(c, "邀请码已过期")
		case service.ErrInviteCodeExhausted:
			response.BadRequest(c, "邀请码使用次数已达上限")
		default:
			logger.Errorf("[InviteHandler] 注册失败: %v", err)
			response.BadRequest(c, "邀请码注册失败，请稍后重试")
		}
		return
	}

	jwtToken, err := model.GenerateToken(user.ID, user.Username, config.C.JWT.Secret, config.C.JWT.ExpireHour)
	if err != nil {
		response.ServerError(c, "生成令牌失败")
		return
	}

	response.Created(c, gin.H{
		"message": "邀请码注册成功",
		"user":    user,
		"token":   jwtToken,
	})
}

func (h *InviteHandler) ValidateInvite(c *gin.Context) {
	code := c.Param("code")
	invite, err := h.inviteService.ValidateCode(code)
	if err != nil {
		switch err {
		case service.ErrInviteCodeNotFound:
			response.NotFound(c, "邀请码不存在")
		case service.ErrInviteCodeExpired:
			response.BadRequest(c, "邀请码已过期")
		case service.ErrInviteCodeExhausted:
			response.BadRequest(c, "邀请码使用次数已达上限")
		default:
			response.ServerError(c, "验证失败")
		}
		return
	}
	response.Success(c, invite)
}
