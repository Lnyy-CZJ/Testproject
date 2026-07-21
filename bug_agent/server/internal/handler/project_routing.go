package handler

import (
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"errors"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type ProjectRoutingHandler struct {
	svc *service.ProjectRoutingService
}

func NewProjectRoutingHandler(db *gorm.DB) *ProjectRoutingHandler {
	return &ProjectRoutingHandler{svc: service.NewProjectRoutingService(db)}
}

func (h *ProjectRoutingHandler) ListModules(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	items, err := h.svc.ListModules(projectID)
	if err != nil {
		response.ServerError(c, "获取项目模块失败")
		return
	}
	response.Success(c, items)
}

func (h *ProjectRoutingHandler) CreateModule(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	var req struct {
		Name        string `json:"name" binding:"required"`
		Code        string `json:"code" binding:"required"`
		Description string `json:"description"`
		OwnerUserID *uint  `json:"ownerUserId"`
		RepoID      *uint  `json:"repoId"`
		PathPattern string `json:"pathPattern"`
		Tags        string `json:"tags"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	item, err := h.svc.CreateModule(projectID, service.ProjectModuleInput(req))
	if err != nil {
		if errors.Is(err, service.ErrInvalidProjectRouting) {
			response.BadRequest(c, "模块参数不完整")
			return
		}
		response.ServerError(c, "创建项目模块失败")
		return
	}
	response.Created(c, item)
}

func (h *ProjectRoutingHandler) UpdateModule(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	moduleID, err := parsePathUintParam(c, "moduleId")
	if err != nil {
		response.BadRequest(c, "无效的模块 ID")
		return
	}
	var req struct {
		Name        string `json:"name" binding:"required"`
		Code        string `json:"code" binding:"required"`
		Description string `json:"description"`
		OwnerUserID *uint  `json:"ownerUserId"`
		RepoID      *uint  `json:"repoId"`
		PathPattern string `json:"pathPattern"`
		Tags        string `json:"tags"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	item, err := h.svc.UpdateModule(projectID, moduleID, service.ProjectModuleInput(req))
	if err != nil {
		switch {
		case errors.Is(err, service.ErrProjectModuleNotFound):
			response.NotFound(c, "项目模块不存在")
		case errors.Is(err, service.ErrInvalidProjectRouting):
			response.BadRequest(c, "模块参数不完整")
		default:
			response.ServerError(c, "更新项目模块失败")
		}
		return
	}
	response.Success(c, item)
}

func (h *ProjectRoutingHandler) DeleteModule(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	moduleID, err := parsePathUintParam(c, "moduleId")
	if err != nil {
		response.BadRequest(c, "无效的模块 ID")
		return
	}
	if err := h.svc.DeleteModule(projectID, moduleID); err != nil {
		if errors.Is(err, service.ErrProjectModuleNotFound) {
			response.NotFound(c, "项目模块不存在")
			return
		}
		response.ServerError(c, "删除项目模块失败")
		return
	}
	response.Success(c, gin.H{"message": "项目模块已删除"})
}

func (h *ProjectRoutingHandler) ListRules(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	items, err := h.svc.ListRules(projectID)
	if err != nil {
		response.ServerError(c, "获取路由规则失败")
		return
	}
	response.Success(c, items)
}

func (h *ProjectRoutingHandler) CreateRule(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	input, ok := bindRoutingRuleInput(c)
	if !ok {
		return
	}
	item, err := h.svc.CreateRule(projectID, input)
	if err != nil {
		switch {
		case errors.Is(err, service.ErrInvalidProjectRouting):
			response.BadRequest(c, "路由规则参数不完整")
		case errors.Is(err, service.ErrProjectModuleNotFound):
			response.BadRequest(c, "关联模块不存在")
		default:
			response.ServerError(c, "创建路由规则失败")
		}
		return
	}
	response.Created(c, item)
}

func (h *ProjectRoutingHandler) UpdateRule(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	ruleID, err := parsePathUintParam(c, "ruleId")
	if err != nil {
		response.BadRequest(c, "无效的规则 ID")
		return
	}
	input, ok := bindRoutingRuleInput(c)
	if !ok {
		return
	}
	item, err := h.svc.UpdateRule(projectID, ruleID, input)
	if err != nil {
		switch {
		case errors.Is(err, service.ErrIssueRoutingRuleNotFound):
			response.NotFound(c, "路由规则不存在")
		case errors.Is(err, service.ErrInvalidProjectRouting):
			response.BadRequest(c, "路由规则参数不完整")
		case errors.Is(err, service.ErrProjectModuleNotFound):
			response.BadRequest(c, "关联模块不存在")
		default:
			response.ServerError(c, "更新路由规则失败")
		}
		return
	}
	response.Success(c, item)
}

func (h *ProjectRoutingHandler) DeleteRule(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	ruleID, err := parsePathUintParam(c, "ruleId")
	if err != nil {
		response.BadRequest(c, "无效的规则 ID")
		return
	}
	if err := h.svc.DeleteRule(projectID, ruleID); err != nil {
		if errors.Is(err, service.ErrIssueRoutingRuleNotFound) {
			response.NotFound(c, "路由规则不存在")
			return
		}
		response.ServerError(c, "删除路由规则失败")
		return
	}
	response.Success(c, gin.H{"message": "路由规则已删除"})
}

func (h *ProjectRoutingHandler) ListReleases(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	items, err := h.svc.ListReleases(projectID)
	if err != nil {
		response.ServerError(c, "获取版本发布失败")
		return
	}
	response.Success(c, items)
}

func (h *ProjectRoutingHandler) ListReleaseTrends(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	items, err := h.svc.ListReleaseTrends(projectID)
	if err != nil {
		response.ServerError(c, "获取发布趋势失败")
		return
	}
	response.Success(c, items)
}

func (h *ProjectRoutingHandler) CreateRelease(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	input, ok := bindAppReleaseInput(c)
	if !ok {
		return
	}
	item, err := h.svc.CreateRelease(projectID, input)
	if err != nil {
		if errors.Is(err, service.ErrInvalidProjectRouting) {
			response.BadRequest(c, "版本发布参数不完整")
			return
		}
		response.ServerError(c, "创建版本发布失败")
		return
	}
	response.Created(c, item)
}

func (h *ProjectRoutingHandler) UpdateRelease(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	releaseID, err := parsePathUintParam(c, "releaseId")
	if err != nil {
		response.BadRequest(c, "无效的版本 ID")
		return
	}
	input, ok := bindAppReleaseInput(c)
	if !ok {
		return
	}
	item, err := h.svc.UpdateRelease(projectID, releaseID, input)
	if err != nil {
		switch {
		case errors.Is(err, service.ErrAppReleaseNotFound):
			response.NotFound(c, "版本发布不存在")
		case errors.Is(err, service.ErrInvalidProjectRouting):
			response.BadRequest(c, "版本发布参数不完整")
		default:
			response.ServerError(c, "更新版本发布失败")
		}
		return
	}
	response.Success(c, item)
}

func (h *ProjectRoutingHandler) DeleteRelease(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	releaseID, err := parsePathUintParam(c, "releaseId")
	if err != nil {
		response.BadRequest(c, "无效的版本 ID")
		return
	}
	if err := h.svc.DeleteRelease(projectID, releaseID); err != nil {
		if errors.Is(err, service.ErrAppReleaseNotFound) {
			response.NotFound(c, "版本发布不存在")
			return
		}
		response.ServerError(c, "删除版本发布失败")
		return
	}
	response.Success(c, gin.H{"message": "版本发布已删除"})
}

func bindRoutingRuleInput(c *gin.Context) (service.IssueRoutingRuleInput, bool) {
	var req struct {
		MatchType        string `json:"matchType" binding:"required"`
		MatchValue       string `json:"matchValue" binding:"required"`
		ModuleID         *uint  `json:"moduleId"`
		OwnerUserID      *uint  `json:"ownerUserId"`
		PriorityOverride string `json:"priorityOverride"`
		SeverityOverride string `json:"severityOverride"`
		Enabled          *bool  `json:"enabled"`
		SortOrder        int    `json:"sortOrder"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return service.IssueRoutingRuleInput{}, false
	}
	enabled := true
	if req.Enabled != nil {
		enabled = *req.Enabled
	}
	return service.IssueRoutingRuleInput{
		MatchType:        strings.TrimSpace(req.MatchType),
		MatchValue:       strings.TrimSpace(req.MatchValue),
		ModuleID:         req.ModuleID,
		OwnerUserID:      req.OwnerUserID,
		PriorityOverride: strings.TrimSpace(req.PriorityOverride),
		SeverityOverride: strings.TrimSpace(req.SeverityOverride),
		Enabled:          enabled,
		SortOrder:        req.SortOrder,
	}, true
}

func bindAppReleaseInput(c *gin.Context) (service.AppReleaseInput, bool) {
	var req struct {
		Platform    string                 `json:"platform" binding:"required"`
		AppVersion  string                 `json:"appVersion" binding:"required"`
		BuildNumber string                 `json:"buildNumber"`
		Channel     string                 `json:"channel"`
		ReleaseTime string                 `json:"releaseTime"`
		CommitSHA   string                 `json:"commitSha"`
		RepoID      *uint                  `json:"repoId"`
		Metadata    map[string]interface{} `json:"metadata"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return service.AppReleaseInput{}, false
	}
	releaseTime := time.Now()
	if strings.TrimSpace(req.ReleaseTime) != "" {
		parsed, err := time.Parse(time.RFC3339, req.ReleaseTime)
		if err != nil {
			response.BadRequest(c, "发布时间格式错误，需为 RFC3339")
			return service.AppReleaseInput{}, false
		}
		releaseTime = parsed
	}
	return service.AppReleaseInput{
		Platform:    strings.TrimSpace(req.Platform),
		AppVersion:  strings.TrimSpace(req.AppVersion),
		BuildNumber: strings.TrimSpace(req.BuildNumber),
		Channel:     strings.TrimSpace(req.Channel),
		ReleaseTime: releaseTime,
		CommitSHA:   strings.TrimSpace(req.CommitSHA),
		RepoID:      req.RepoID,
		Metadata:    req.Metadata,
	}, true
}
