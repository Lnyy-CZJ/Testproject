package handler

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"encoding/json"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type ProjectRepoHandler struct {
	db          *gorm.DB
	credService *service.CredentialService
}

var allowedRepoSourceTypes = map[string]struct{}{
	"github":  {},
	"gitlab":  {},
	"gitea":   {},
	"yunxiao": {},
	"custom":  {},
}

func NewProjectRepoHandler(db *gorm.DB) *ProjectRepoHandler {
	return &ProjectRepoHandler{
		db:          db,
		credService: service.NewCredentialService(db),
	}
}

// ListRepos 获取项目仓库列表
func (h *ProjectRepoHandler) ListRepos(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	var repos []model.ProjectRepo
	if err := h.db.Where("project_id = ?", projectID).Order("created_at desc").Find(&repos).Error; err != nil {
		response.ServerError(c, "获取仓库列表失败")
		return
	}

	response.Success(c, repos)
}

// CreateRepo 添加项目仓库
func (h *ProjectRepoHandler) CreateRepo(c *gin.Context) {
	userID := getUserID(c)
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	var req struct {
		Name          string `json:"name" binding:"required"`
		RepoURL       string `json:"repoUrl" binding:"required"`
		SourceType    string `json:"sourceType" binding:"required"`
		CredentialID  *uint  `json:"credentialId"`
		AgentTypes    string `json:"agentTypes"`
		DefaultBranch string `json:"defaultBranch"`
		Description   string `json:"description"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	req.Name = strings.TrimSpace(req.Name)
	req.RepoURL = strings.TrimSpace(req.RepoURL)
	req.SourceType = strings.TrimSpace(req.SourceType)
	req.DefaultBranch = strings.TrimSpace(req.DefaultBranch)
	req.Description = strings.TrimSpace(req.Description)

	if req.Name == "" || req.RepoURL == "" {
		response.BadRequest(c, "仓库名称和地址不能为空")
		return
	}

	if req.SourceType == "" {
		req.SourceType = "custom"
	}
	req.SourceType = strings.ToLower(req.SourceType)
	if !isValidRepoSourceType(req.SourceType) {
		response.BadRequest(c, "无效的来源类型")
		return
	}

	if req.DefaultBranch == "" {
		req.DefaultBranch = "main"
	}
	if req.AgentTypes == "" {
		req.AgentTypes = "backend,test"
	}
	normalizedAgentTypes, err := normalizeRepoAgentTypes(req.AgentTypes)
	if err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	req.AgentTypes = normalizedAgentTypes

	if req.CredentialID != nil {
		if *req.CredentialID == 0 {
			response.BadRequest(c, "无效的凭证ID")
			return
		}
		cred, err := h.credService.ResolveAccessibleCredential(*req.CredentialID, userID, uint(projectID))
		if err != nil {
			writeCredentialAccessError(c, err)
			return
		}
		if !isCredentialProviderCompatible(cred.Provider, req.SourceType) {
			response.BadRequest(c, "凭证提供商与仓库来源不匹配")
			return
		}
	}

	exists, err := h.repoURLExists(uint(projectID), req.RepoURL, nil)
	if err != nil {
		response.ServerError(c, "检查仓库地址失败")
		return
	}
	if exists {
		response.BadRequest(c, "该仓库地址已存在")
		return
	}

	repo := model.ProjectRepo{
		ProjectID:     uint(projectID),
		Name:          req.Name,
		RepoURL:       req.RepoURL,
		SourceType:    req.SourceType,
		CredentialID:  req.CredentialID,
		AgentTypes:    req.AgentTypes,
		DefaultBranch: req.DefaultBranch,
		Description:   req.Description,
	}
	if err := h.db.Create(&repo).Error; err != nil {
		response.ServerError(c, "创建仓库失败")
		return
	}

	response.Created(c, repo)
}

// UpdateRepo 更新项目仓库
func (h *ProjectRepoHandler) UpdateRepo(c *gin.Context) {
	userID := getUserID(c)
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	repoID, err := strconv.ParseUint(c.Param("repoId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的仓库ID")
		return
	}

	var raw map[string]json.RawMessage
	if err := c.ShouldBindJSON(&raw); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	var req struct {
		Name          *string `json:"name"`
		RepoURL       *string `json:"repoUrl"`
		SourceType    *string `json:"sourceType"`
		CredentialID  *uint   `json:"credentialId"`
		AgentTypes    *string `json:"agentTypes"`
		DefaultBranch *string `json:"defaultBranch"`
		Description   *string `json:"description"`
	}
	payload, _ := json.Marshal(raw)
	if err := json.Unmarshal(payload, &req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	_, hasCredentialID := raw["credentialId"]

	var repo model.ProjectRepo
	if err := h.db.Where("id = ? AND project_id = ?", repoID, projectID).First(&repo).Error; err != nil {
		response.NotFound(c, "仓库不存在")
		return
	}

	if req.RepoURL != nil {
		repoURL := strings.TrimSpace(*req.RepoURL)
		if repoURL == "" {
			response.BadRequest(c, "仓库地址不能为空")
			return
		}

		if repoURL != repo.RepoURL {
			excludeID := uint(repoID)
			exists, dupErr := h.repoURLExists(uint(projectID), repoURL, &excludeID)
			if dupErr != nil {
				response.ServerError(c, "检查仓库地址失败")
				return
			}
			if exists {
				response.BadRequest(c, "该仓库地址已存在")
				return
			}
		}
		repo.RepoURL = repoURL
	}
	if req.Name != nil {
		name := strings.TrimSpace(*req.Name)
		if name == "" {
			response.BadRequest(c, "仓库名称不能为空")
			return
		}
		repo.Name = name
	}
	if req.SourceType != nil {
		sourceType := strings.ToLower(strings.TrimSpace(*req.SourceType))
		if !isValidRepoSourceType(sourceType) {
			response.BadRequest(c, "无效的来源类型")
			return
		}
		repo.SourceType = sourceType
	}
	if hasCredentialID {
		if strings.TrimSpace(string(raw["credentialId"])) == "null" {
			repo.CredentialID = nil
		} else {
			if req.CredentialID == nil || *req.CredentialID == 0 {
				response.BadRequest(c, "无效的凭证ID")
				return
			}
			if _, err := h.credService.ResolveAccessibleCredential(*req.CredentialID, userID, uint(projectID)); err != nil {
				writeCredentialAccessError(c, err)
				return
			}
			repo.CredentialID = req.CredentialID
		}
	}
	if req.AgentTypes != nil {
		normalizedAgentTypes, err := normalizeRepoAgentTypes(*req.AgentTypes)
		if err != nil {
			response.BadRequest(c, err.Error())
			return
		}
		repo.AgentTypes = normalizedAgentTypes
	}
	if req.DefaultBranch != nil {
		branch := strings.TrimSpace(*req.DefaultBranch)
		if branch == "" {
			branch = "main"
		}
		repo.DefaultBranch = branch
	}
	if req.Description != nil {
		repo.Description = strings.TrimSpace(*req.Description)
	}
	if repo.CredentialID != nil {
		cred, err := h.credService.ResolveAccessibleCredential(*repo.CredentialID, userID, uint(projectID))
		if err != nil {
			writeCredentialAccessError(c, err)
			return
		}
		if !isCredentialProviderCompatible(cred.Provider, repo.SourceType) {
			response.BadRequest(c, "凭证提供商与仓库来源不匹配")
			return
		}
	}

	if err := h.db.Save(&repo).Error; err != nil {
		response.ServerError(c, "更新仓库失败")
		return
	}

	response.Success(c, repo)
}

// DeleteRepo 删除项目仓库
func (h *ProjectRepoHandler) DeleteRepo(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	repoID, err := strconv.ParseUint(c.Param("repoId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的仓库ID")
		return
	}

	var boundCount int64
	if err := h.db.Model(&model.IterationRepo{}).Where("repo_id = ?", repoID).Count(&boundCount).Error; err != nil {
		response.ServerError(c, "查询仓库绑定状态失败")
		return
	}
	if boundCount > 0 {
		response.BadRequest(c, "该仓库已被迭代绑定，请先解绑")
		return
	}

	if err := h.db.Where("id = ? AND project_id = ?", repoID, projectID).Delete(&model.ProjectRepo{}).Error; err != nil {
		response.ServerError(c, "删除仓库失败")
		return
	}

	response.Success(c, gin.H{"message": "仓库已删除"})
}

func (h *ProjectRepoHandler) repoURLExists(projectID uint, repoURL string, excludeID *uint) (bool, error) {
	target := normalizeRepoURL(repoURL)
	if target == "" {
		return false, nil
	}

	type repoRow struct {
		ID      uint
		RepoURL string `gorm:"column:repo_url"`
	}
	var rows []repoRow
	query := h.db.Table("project_repos").Select("id, repo_url").Where("project_id = ?", projectID)
	if excludeID != nil {
		query = query.Where("id <> ?", *excludeID)
	}
	if err := query.Find(&rows).Error; err != nil {
		return false, err
	}

	for _, row := range rows {
		if normalizeRepoURL(row.RepoURL) == target {
			return true, nil
		}
	}
	return false, nil
}

func isValidRepoSourceType(sourceType string) bool {
	_, ok := allowedRepoSourceTypes[sourceType]
	return ok
}

func isCredentialProviderCompatible(provider string, sourceType string) bool {
	p := strings.ToLower(strings.TrimSpace(provider))
	s := strings.ToLower(strings.TrimSpace(sourceType))
	if p == "generic" {
		return true
	}
	if s == "custom" {
		return true
	}
	return p == s
}

func normalizeRepoAgentTypes(raw string) (string, error) {
	parts := strings.Split(raw, ",")
	seen := make(map[string]struct{}, len(parts))
	normalized := make([]string, 0, len(parts))

	for _, part := range parts {
		value := strings.ToLower(strings.TrimSpace(part))
		if value == "" {
			continue
		}
		if !allowedAgentTypeSet[value] {
			return "", errInvalidAgentType
		}
		if _, exists := seen[value]; exists {
			continue
		}
		seen[value] = struct{}{}
		normalized = append(normalized, value)
	}

	if len(normalized) == 0 {
		return "", errInvalidAgentType
	}
	return strings.Join(normalized, ","), nil
}
