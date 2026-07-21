package handler

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type CredentialHandler struct {
	db          *gorm.DB
	credService *service.CredentialService
}

func NewCredentialHandler(db *gorm.DB) *CredentialHandler {
	return &CredentialHandler{
		db:          db,
		credService: service.NewCredentialService(db),
	}
}

func (h *CredentialHandler) ListCredentials(c *gin.Context) {
	userID := getUserID(c)
	projectIDStr := c.Query("projectId")
	var (
		creds []model.RepoCredential
		err   error
	)
	if projectIDStr != "" {
		projectID, convErr := strconv.ParseUint(projectIDStr, 10, 64)
		if convErr != nil || projectID == 0 {
			response.BadRequest(c, "无效的项目ID")
			return
		}
		creds, err = h.credService.ListForProject(userID, uint(projectID))
	} else {
		creds, err = h.credService.List(userID)
	}
	if err != nil {
		response.ServerError(c, "获取凭证列表失败")
		return
	}
	response.Success(c, creds)
}

func (h *CredentialHandler) CreateCredential(c *gin.Context) {
	userID := getUserID(c)
	var req struct {
		Name        string `json:"name" binding:"required"`
		Type        string `json:"type" binding:"required"`
		Provider    string `json:"provider" binding:"required"`
		Content     string `json:"content" binding:"required"`
		ExtraConfig string `json:"extraConfig"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	cred, err := h.credService.Create(userID, req.Name, req.Type, req.Provider, req.Content, req.ExtraConfig)
	if err != nil {
		response.ServerError(c, "创建凭证失败")
		return
	}
	response.Created(c, cred)
}

func (h *CredentialHandler) UpdateCredential(c *gin.Context) {
	userID := getUserID(c)
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的凭证ID")
		return
	}
	var req struct {
		Name        string  `json:"name"`
		Type        string  `json:"type"`
		Provider    string  `json:"provider"`
		Content     string  `json:"content"`
		ExtraConfig *string `json:"extraConfig"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	cred, err := h.credService.Update(uint(id), userID, req.Name, req.Type, req.Provider, req.Content, req.ExtraConfig)
	if err != nil {
		if err == service.ErrCredentialNotFound {
			response.NotFound(c, "凭证不存在")
			return
		}
		response.ServerError(c, "更新凭证失败")
		return
	}
	response.Success(c, cred)
}

func (h *CredentialHandler) DeleteCredential(c *gin.Context) {
	userID := getUserID(c)
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的凭证ID")
		return
	}
	if err := h.credService.Delete(uint(id), userID); err != nil {
		if err == service.ErrCredentialNotFound {
			response.NotFound(c, "凭证不存在")
			return
		}
		response.ServerError(c, "删除凭证失败")
		return
	}
	response.Success(c, gin.H{"message": "凭证已删除"})
}

func (h *CredentialHandler) ListPlatformCredentials(c *gin.Context) {
	creds, err := h.credService.ListPlatform()
	if err != nil {
		response.ServerError(c, "获取平台凭证列表失败")
		return
	}
	response.Success(c, creds)
}

func (h *CredentialHandler) CreatePlatformCredential(c *gin.Context) {
	userID := getUserID(c)
	var req struct {
		Name              string `json:"name" binding:"required"`
		Type              string `json:"type" binding:"required"`
		Provider          string `json:"provider" binding:"required"`
		Content           string `json:"content" binding:"required"`
		ExtraConfig       string `json:"extraConfig"`
		Status            string `json:"status"`
		AllowedProjectIDs []uint `json:"allowedProjectIds"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	cred, err := h.credService.CreatePlatform(userID, req.Name, req.Type, req.Provider, req.Content, req.ExtraConfig, req.Status, req.AllowedProjectIDs)
	if err != nil {
		response.ServerError(c, "创建平台凭证失败")
		return
	}
	response.Created(c, cred)
}

func (h *CredentialHandler) UpdatePlatformCredential(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的凭证ID")
		return
	}

	var req struct {
		Name              string  `json:"name"`
		Type              string  `json:"type"`
		Provider          string  `json:"provider"`
		Content           string  `json:"content"`
		ExtraConfig       *string `json:"extraConfig"`
		Status            string  `json:"status"`
		AllowedProjectIDs []uint  `json:"allowedProjectIds"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	cred, err := h.credService.UpdatePlatform(uint(id), req.Name, req.Type, req.Provider, req.Content, req.Status, req.ExtraConfig, req.AllowedProjectIDs)
	if err != nil {
		switch err {
		case service.ErrCredentialNotFound:
			response.NotFound(c, "平台凭证不存在")
		case service.ErrPlatformCredentialOnly:
			response.BadRequest(c, "仅支持更新平台凭证")
		default:
			response.ServerError(c, "更新平台凭证失败")
		}
		return
	}
	response.Success(c, cred)
}

func (h *CredentialHandler) DeletePlatformCredential(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的凭证ID")
		return
	}
	if err := h.credService.DeletePlatform(uint(id)); err != nil {
		if err == service.ErrCredentialNotFound {
			response.NotFound(c, "平台凭证不存在")
			return
		}
		response.ServerError(c, "删除平台凭证失败")
		return
	}
	response.Success(c, gin.H{"message": "平台凭证已删除"})
}

// TestConnection 测试仓库连接
// NOTE: 此接口支持两种调用格式：
// 1. JSON body: { provider, repoUrl, content } — 直接提供连接信息
// 2. URL param: /repos/:id — 使用已保存仓库的凭证测试连接
// 两种格式通过 JSON body 绑定是否成功来区分，这是一个历史兼容设计。
func (h *CredentialHandler) TestConnection(c *gin.Context) {
	var req struct {
		Provider string `json:"provider" binding:"required"`
		RepoURL  string `json:"repoUrl" binding:"required"`
		Content  string `json:"content"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		repoIDStr := c.Param("id")
		if repoIDStr == "" {
			response.BadRequest(c, "参数错误: "+err.Error())
			return
		}

		repoID, convErr := strconv.ParseUint(repoIDStr, 10, 64)
		if convErr != nil {
			response.BadRequest(c, "无效的仓库ID")
			return
		}

		var repo model.ProjectRepo
		if dbErr := h.db.First(&repo, uint(repoID)).Error; dbErr != nil {
			response.NotFound(c, "仓库不存在")
			return
		}

		req.Provider = repo.SourceType
		req.RepoURL = repo.RepoURL

		if repo.CredentialID != nil {
			if _, accessErr := h.credService.ResolveAccessibleCredential(*repo.CredentialID, getUserID(c), repo.ProjectID); accessErr != nil {
				writeCredentialAccessError(c, accessErr)
				return
			}
			if content, decErr := h.credService.GetDecryptedContentByID(*repo.CredentialID); decErr == nil {
				req.Content = content
			} else {
				response.ServerError(c, "读取仓库凭证失败")
				return
			}
		}
	}

	if req.Provider == "" || req.RepoURL == "" {
		response.BadRequest(c, "参数错误: provider/repoUrl 不能为空")
		return
	}
	result := h.credService.ValidateConnection(req.Provider, req.RepoURL, req.Content)
	response.Success(c, result)
}

func writeCredentialAccessError(c *gin.Context, err error) {
	switch err {
	case service.ErrCredentialForbidden:
		response.Forbidden(c, "当前项目无权使用该平台凭证")
	case service.ErrCredentialInactive:
		response.BadRequest(c, "平台凭证已停用")
	case service.ErrCredentialNotFound:
		response.BadRequest(c, "凭证不存在或无权使用")
	default:
		response.ServerError(c, "读取凭证失败")
	}
}
