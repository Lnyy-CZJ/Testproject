package handler

import (
	"bug-agent/internal/integration/yunxiao"
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

const (
	yunxiaoDefaultTimeout = 15 * time.Second
	yunxiaoLongTimeout    = 20 * time.Second
)

type YunxiaoIntegrationHandler struct {
	db          *gorm.DB
	credService *service.CredentialService
}

func NewYunxiaoIntegrationHandler(db *gorm.DB) *YunxiaoIntegrationHandler {
	return &YunxiaoIntegrationHandler{
		db:          db,
		credService: service.NewCredentialService(db),
	}
}

func (h *YunxiaoIntegrationHandler) TestConnection(c *gin.Context) {
	userID := getUserID(c)
	var req struct {
		CredentialID   uint   `json:"credentialId" binding:"required"`
		ProjectID      uint   `json:"projectId"`
		Endpoint       string `json:"endpoint"`
		OrganizationID string `json:"organizationId"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	client, cred, orgID, err := h.buildClientFromCredential(userID, req.ProjectID, req.CredentialID, req.Endpoint, req.OrganizationID)
	if err != nil {
		h.writeYunxiaoCredentialError(c, err)
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), yunxiaoDefaultTimeout)
	defer cancel()
	if err := client.TestConnection(ctx, orgID); err != nil {
		h.respondYunxiaoAPIError(c, err, "云效连接测试失败")
		return
	}

	_ = h.credService.TouchLastUsed(cred.ID)
	middleware.AuditAction(c, "yunxiao_test_connection", "credential", cred.ID, nil, gin.H{
		"credentialId":   cred.ID,
		"provider":       cred.Provider,
		"endpoint":       client.Endpoint(),
		"organizationId": orgID,
		"success":        true,
	})
	response.Success(c, gin.H{
		"success":        true,
		"message":        "云效连接成功",
		"endpoint":       client.Endpoint(),
		"organizationId": orgID,
		"provider":       cred.Provider,
		"timestamp":      time.Now().Format(time.RFC3339),
	})
}

func (h *YunxiaoIntegrationHandler) ListRepositories(c *gin.Context) {
	userID := getUserID(c)
	projectID, err := parseOptionalProjectID(c.Query("projectId"))
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}
	credentialID, err := strconv.ParseUint(c.Query("credentialId"), 10, 64)
	if err != nil || credentialID == 0 {
		response.BadRequest(c, "credentialId 不能为空")
		return
	}

	page, size := parsePagination(c, 0)
	search := c.Query("search")
	endpoint := c.Query("endpoint")
	orgID := c.Query("organizationId")

	client, cred, resolvedOrgID, err := h.buildClientFromCredential(userID, projectID, uint(credentialID), endpoint, orgID)
	if err != nil {
		h.writeYunxiaoCredentialError(c, err)
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), yunxiaoLongTimeout)
	defer cancel()
	repos, err := client.ListRepositories(ctx, resolvedOrgID, page, size, search)
	if err != nil {
		h.respondYunxiaoAPIError(c, err, "拉取云效仓库失败")
		return
	}

	_ = h.credService.TouchLastUsed(cred.ID)
	response.Success(c, gin.H{
		"items":           repos,
		"page":           page,
		"pageSize":           size,
		"total":          len(repos),
		"organizationId": resolvedOrgID,
	})
}

func (h *YunxiaoIntegrationHandler) ImportRepositories(c *gin.Context) {
	userID := getUserID(c)
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil || projectID == 0 {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	var req struct {
		CredentialID uint `json:"credentialId" binding:"required"`
		Items        []struct {
			ExternalID    string `json:"externalId"`
			Name          string `json:"name"`
			RepoURL       string `json:"repoUrl"`
			DefaultBranch string `json:"defaultBranch"`
			Description   string `json:"description"`
		} `json:"items" binding:"required"`
		AgentTypes string `json:"agentTypes"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	if len(req.Items) == 0 {
		response.BadRequest(c, "items 不能为空")
		return
	}

	cred, err := h.requireAccessibleYunxiaoCredential(userID, uint(projectID), req.CredentialID)
	if err != nil {
		h.writeYunxiaoCredentialError(c, err)
		return
	}

	var project model.Project
	if err := h.db.First(&project, uint(projectID)).Error; err != nil {
		response.NotFound(c, "项目不存在")
		return
	}

	agentTypes := strings.TrimSpace(req.AgentTypes)
	if agentTypes == "" {
		agentTypes = "backend,test"
	}
	normalizedAgentTypes, err := normalizeRepoAgentTypes(agentTypes)
	if err != nil {
		response.BadRequest(c, "agentTypes 无效")
		return
	}

	type itemResult struct {
		Name    string `json:"name"`
		RepoURL string `json:"repoUrl"`
		Reason  string `json:"reason,omitempty"`
	}
	imported := make([]itemResult, 0, len(req.Items))
	skipped := make([]itemResult, 0)
	failed := make([]itemResult, 0)
	existingRepoURLSet := map[string]struct{}{}
	type repoRow struct {
		RepoURL string `gorm:"column:repo_url"`
	}
	var existingRows []repoRow
	if err := h.db.Table("project_repos").Select("repo_url").Where("project_id = ?", projectID).Find(&existingRows).Error; err != nil {
		response.ServerError(c, "读取项目仓库失败")
		return
	}
	for _, row := range existingRows {
		if normalized := normalizeRepoURL(row.RepoURL); normalized != "" {
			existingRepoURLSet[normalized] = struct{}{}
		}
	}

	for _, item := range req.Items {
		name := strings.TrimSpace(item.Name)
		repoURL := strings.TrimSpace(item.RepoURL)
		normalizedURL := normalizeRepoURL(repoURL)
		branch := strings.TrimSpace(item.DefaultBranch)
		if branch == "" {
			branch = "main"
		}
		if name == "" || repoURL == "" {
			failed = append(failed, itemResult{Name: name, RepoURL: repoURL, Reason: "仓库名称或地址为空"})
			continue
		}
		if normalizedURL == "" {
			failed = append(failed, itemResult{Name: name, RepoURL: repoURL, Reason: "仓库地址格式无效"})
			continue
		}

		if _, exists := existingRepoURLSet[normalizedURL]; exists {
			skipped = append(skipped, itemResult{Name: name, RepoURL: repoURL, Reason: "仓库已存在"})
			continue
		}

		repo := model.ProjectRepo{
			ProjectID:      uint(projectID),
			Name:           name,
			RepoURL:        repoURL,
			ExternalRepoID: strings.TrimSpace(item.ExternalID),
			SourceType:     "yunxiao",
			CredentialID:   &cred.ID,
			AgentTypes:     normalizedAgentTypes,
			DefaultBranch:  branch,
			Description:    strings.TrimSpace(item.Description),
		}
		if err := h.db.Create(&repo).Error; err != nil {
			if strings.Contains(strings.ToLower(err.Error()), "duplicate") || strings.Contains(strings.ToLower(err.Error()), "unique") {
				skipped = append(skipped, itemResult{Name: name, RepoURL: repoURL, Reason: "仓库已存在(并发写入)"})
			} else {
				failed = append(failed, itemResult{Name: name, RepoURL: repoURL, Reason: "导入失败"})
			}
			continue
		}
		imported = append(imported, itemResult{Name: name, RepoURL: repoURL})
		existingRepoURLSet[normalizedURL] = struct{}{}
	}

	_ = h.credService.TouchLastUsed(cred.ID)
	summary := gin.H{
		"total":    len(req.Items),
		"imported": len(imported),
		"skipped":  len(skipped),
		"failed":   len(failed),
	}
	middleware.AuditAction(c, "yunxiao_import_repositories", "project", uint(projectID), nil, gin.H{
		"credentialId": req.CredentialID,
		"summary":      summary,
	})
	response.Success(c, gin.H{
		"projectId": projectID,
		"summary":   summary,
		"imported":  imported,
		"skipped":   skipped,
		"failed":    failed,
	})
}

func (h *YunxiaoIntegrationHandler) ListMembers(c *gin.Context) {
	userID := getUserID(c)
	projectID, err := parseOptionalProjectID(c.Query("projectId"))
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}
	credentialID, err := strconv.ParseUint(c.Query("credentialId"), 10, 64)
	if err != nil || credentialID == 0 {
		response.BadRequest(c, "credentialId 不能为空")
		return
	}
	page, size := parsePagination(c, 0)
	search := c.Query("search")
	endpoint := c.Query("endpoint")
	orgID := c.Query("organizationId")

	client, cred, resolvedOrgID, err := h.buildClientFromCredential(userID, projectID, uint(credentialID), endpoint, orgID)
	if err != nil {
		h.writeYunxiaoCredentialError(c, err)
		return
	}
	if strings.TrimSpace(resolvedOrgID) == "" {
		response.BadRequest(c, "organizationId 不能为空（可放在凭证内容JSON中）")
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), yunxiaoLongTimeout)
	defer cancel()
	members, err := client.ListMembers(ctx, resolvedOrgID, page, size, search)
	if err != nil {
		h.respondYunxiaoAPIError(c, err, "拉取云效成员失败")
		return
	}
	_ = h.credService.TouchLastUsed(cred.ID)
	response.Success(c, gin.H{
		"items":           members,
		"page":           page,
		"pageSize":           size,
		"total":          len(members),
		"organizationId": resolvedOrgID,
	})
}

func (h *YunxiaoIntegrationHandler) ImportMembers(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil || projectID == 0 {
		response.BadRequest(c, "无效的项目ID")
		return
	}
	userID := getUserID(c)

	var req struct {
		CredentialID   uint `json:"credentialId" binding:"required"`
		UpdateExisting bool `json:"updateExisting"`
		Items          []struct {
			ExternalID string `json:"externalId"`
			Name       string `json:"name"`
			Username   string `json:"username"`
			Email      string `json:"email"`
			Role       string `json:"role"`
		} `json:"items" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}
	if len(req.Items) == 0 {
		response.BadRequest(c, "items 不能为空")
		return
	}

	cred, err := h.requireAccessibleYunxiaoCredential(userID, uint(projectID), req.CredentialID)
	if err != nil {
		h.writeYunxiaoCredentialError(c, err)
		return
	}

	var project model.Project
	if err := h.db.First(&project, uint(projectID)).Error; err != nil {
		response.NotFound(c, "项目不存在")
		return
	}

	type memberResult struct {
		ExternalID string `json:"externalId,omitempty"`
		Name       string `json:"name"`
		Email      string `json:"email,omitempty"`
		Username   string `json:"username,omitempty"`
		Role       string `json:"role,omitempty"`
		Reason     string `json:"reason,omitempty"`
	}
	added := make([]memberResult, 0)
	updated := make([]memberResult, 0)
	skipped := make([]memberResult, 0)
	unmatched := make([]memberResult, 0)
	failed := make([]memberResult, 0)

	for _, item := range req.Items {
		role := mapYunxiaoRoleToProjectRole(item.Role)
		if _, ok := normalizeProjectRole(role); !ok {
			role = "viewer"
		}

		user, findErr := h.findLocalUserForImportedMember(item.Email, item.Username)
		if findErr != nil {
			unmatched = append(unmatched, memberResult{
				ExternalID: item.ExternalID,
				Name:       item.Name,
				Email:      item.Email,
				Username:   item.Username,
				Role:       role,
				Reason:     "未匹配到本地用户",
			})
			continue
		}

		var pm model.ProjectMember
		err := h.db.Where("project_id = ? AND user_id = ?", projectID, user.ID).First(&pm).Error
		if err == nil {
			if req.UpdateExisting && pm.Role != role {
				pm.Role = role
				if saveErr := h.db.Save(&pm).Error; saveErr != nil {
					failed = append(failed, memberResult{
						ExternalID: item.ExternalID, Name: item.Name, Email: item.Email, Username: item.Username, Role: role, Reason: "更新角色失败",
					})
					continue
				}
				middleware.InvalidateRBACCache(pm.UserID)
				updated = append(updated, memberResult{
					ExternalID: item.ExternalID, Name: item.Name, Email: item.Email, Username: item.Username, Role: role,
				})
			} else {
				skipped = append(skipped, memberResult{
					ExternalID: item.ExternalID, Name: item.Name, Email: item.Email, Username: item.Username, Role: pm.Role, Reason: "成员已存在",
				})
			}
			continue
		}
		if !errors.Is(err, gorm.ErrRecordNotFound) {
			failed = append(failed, memberResult{
				ExternalID: item.ExternalID, Name: item.Name, Email: item.Email, Username: item.Username, Role: role, Reason: "查询项目成员失败",
			})
			continue
		}

		pm = model.ProjectMember{
			ProjectID: uint(projectID),
			UserID:    user.ID,
			Role:      role,
		}
		if createErr := h.db.Create(&pm).Error; createErr != nil {
			failed = append(failed, memberResult{
				ExternalID: item.ExternalID, Name: item.Name, Email: item.Email, Username: item.Username, Role: role, Reason: "新增成员失败",
			})
			continue
		}
		middleware.InvalidateRBACCache(pm.UserID)
		added = append(added, memberResult{
			ExternalID: item.ExternalID, Name: item.Name, Email: item.Email, Username: item.Username, Role: role,
		})
	}

	_ = h.credService.TouchLastUsed(cred.ID)
	summary := gin.H{
		"total":     len(req.Items),
		"added":     len(added),
		"updated":   len(updated),
		"skipped":   len(skipped),
		"unmatched": len(unmatched),
		"failed":    len(failed),
	}
	middleware.AuditAction(c, "yunxiao_import_members", "project", uint(projectID), nil, gin.H{
		"credentialId": req.CredentialID,
		"summary":      summary,
	})
	response.Success(c, gin.H{
		"projectId": projectID,
		"summary":   summary,
		"added":     added,
		"updated":   updated,
		"skipped":   skipped,
		"unmatched": unmatched,
		"failed":    failed,
	})
}

func (h *YunxiaoIntegrationHandler) respondYunxiaoAPIError(c *gin.Context, err error, fallbackMessage string) {
	var apiErr *yunxiao.APIError
	if errors.As(err, &apiErr) {
		switch apiErr.StatusCode {
		case http.StatusUnauthorized, http.StatusForbidden:
			response.BadRequest(c, "凭证无效或已过期")
		case http.StatusTooManyRequests:
			response.Error(c, http.StatusTooManyRequests, 429, "云效API触发限流，请稍后重试")
		default:
			msg := strings.TrimSpace(apiErr.Message)
			if msg == "" {
				msg = fallbackMessage
			}
			response.Error(c, http.StatusBadGateway, 502, msg)
		}
		return
	}
	response.ServerErrorWithLog(c, err, "操作失败")
}

func (h *YunxiaoIntegrationHandler) buildClientFromCredential(userID, projectID, credentialID uint, endpoint, organizationID string) (*yunxiao.Client, *model.RepoCredential, string, error) {
	cred, err := h.credService.ResolveAccessibleCredential(credentialID, userID, projectID)
	if err != nil {
		return nil, nil, "", err
	}
	provider := strings.ToLower(strings.TrimSpace(cred.Provider))
	if provider != "yunxiao" && provider != "generic" {
		return nil, nil, "", errors.New("凭证提供商不是云效")
	}

	content, err := h.credService.GetDecryptedContentByID(cred.ID)
	if err != nil {
		return nil, nil, "", errors.New("读取凭证失败")
	}
	token, orgFromContent := extractYunxiaoTokenAndOrg(content)
	if token == "" {
		return nil, nil, "", errors.New("云效凭证内容缺少 token")
	}
	endpointFromConfig, orgFromConfig := extractYunxiaoEndpointAndOrg(cred.ExtraConfig)

	orgID := strings.TrimSpace(organizationID)
	if orgID == "" {
		orgID = firstNonEmptyString(orgFromContent, orgFromConfig)
	}
	resolvedEndpoint := strings.TrimSpace(endpoint)
	if resolvedEndpoint == "" {
		resolvedEndpoint = endpointFromConfig
	}
	client := yunxiao.NewClient(resolvedEndpoint, token)
	return client, cred, orgID, nil
}

func (h *YunxiaoIntegrationHandler) requireAccessibleYunxiaoCredential(userID, projectID, credentialID uint) (*model.RepoCredential, error) {
	cred, err := h.credService.ResolveAccessibleCredential(credentialID, userID, projectID)
	if err != nil {
		return nil, err
	}
	provider := strings.ToLower(strings.TrimSpace(cred.Provider))
	if provider != "yunxiao" && provider != "generic" {
		return nil, errors.New("凭证提供商不是云效")
	}
	return cred, nil
}

func (h *YunxiaoIntegrationHandler) writeYunxiaoCredentialError(c *gin.Context, err error) {
	switch err {
	case service.ErrCredentialNotFound, service.ErrCredentialInactive:
		response.BadRequest(c, mapYunxiaoCredentialErrorMessage(err))
	case service.ErrCredentialForbidden:
		response.Forbidden(c, "当前项目无权使用该平台凭证")
	default:
		response.BadRequest(c, err.Error())
	}
}

func mapYunxiaoCredentialErrorMessage(err error) string {
	switch err {
	case service.ErrCredentialInactive:
		return "平台凭证已停用"
	default:
		return "凭证不存在或无权使用"
	}
}

func parseOptionalProjectID(raw string) (uint, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return 0, nil
	}
	projectID, err := strconv.ParseUint(raw, 10, 64)
	if err != nil || projectID == 0 {
		return 0, errors.New("invalid project id")
	}
	return uint(projectID), nil
}

func extractYunxiaoTokenAndOrg(content string) (string, string) {
	raw := strings.TrimSpace(content)
	if raw == "" {
		return "", ""
	}
	if strings.HasPrefix(raw, "{") {
		var payload map[string]interface{}
		if err := json.Unmarshal([]byte(raw), &payload); err == nil {
			token := strings.TrimSpace(firstNonEmptyString(
				payload["token"],
				payload["accessToken"],
				payload["personalAccessToken"],
				payload["password"],
			))
			org := strings.TrimSpace(firstNonEmptyString(
				payload["organizationId"],
				payload["organization"],
				payload["organizationIdentifier"],
				payload["spaceId"],
				payload["workspaceId"],
			))
			return token, org
		}
	}
	return raw, ""
}

func extractYunxiaoEndpointAndOrg(extraConfig string) (string, string) {
	raw := strings.TrimSpace(extraConfig)
	if raw == "" || !strings.HasPrefix(raw, "{") {
		return "", ""
	}

	var payload map[string]interface{}
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		return "", ""
	}

	endpoint := strings.TrimSpace(firstNonEmptyString(
		payload["endpoint"],
		payload["apiEndpoint"],
		payload["baseUrl"],
		payload["baseURL"],
	))
	org := strings.TrimSpace(firstNonEmptyString(
		payload["organizationId"],
		payload["organization"],
		payload["organizationIdentifier"],
		payload["workspaceId"],
		payload["spaceId"],
	))

	return endpoint, org
}

func firstNonEmptyString(values ...interface{}) string {
	for _, v := range values {
		if v == nil {
			continue
		}
		switch val := v.(type) {
		case string:
			if strings.TrimSpace(val) != "" {
				return val
			}
		case *string:
			if val != nil && strings.TrimSpace(*val) != "" {
				return *val
			}
		default:
			s := strings.TrimSpace(fmt.Sprintf("%v", v))
			if s != "" && s != "<nil>" {
				return s
			}
		}
	}
	return ""
}

func mapYunxiaoRoleToProjectRole(raw string) string {
	role := strings.ToLower(strings.TrimSpace(raw))
	switch {
	case strings.Contains(role, "admin"), strings.Contains(role, "owner"), strings.Contains(role, "负责人"), strings.Contains(role, "管理员"):
		return "project_admin"
	case strings.Contains(role, "test"), strings.Contains(role, "qa"), strings.Contains(role, "测试"):
		return "tester"
	case strings.Contains(role, "dev"), strings.Contains(role, "rd"), strings.Contains(role, "开发"), strings.Contains(role, "engineer"):
		return "developer"
	default:
		return "viewer"
	}
}

func (h *YunxiaoIntegrationHandler) findLocalUserForImportedMember(email, username string) (*model.User, error) {
	email = strings.TrimSpace(email)
	username = strings.TrimSpace(username)

	var user model.User
	if email != "" {
		if err := h.db.Where("LOWER(email) = LOWER(?)", email).First(&user).Error; err == nil {
			return &user, nil
		} else if !errors.Is(err, gorm.ErrRecordNotFound) {
			logger.Errorf("查询用户失败: %v", err)
		}
	}
	if username != "" {
		if err := h.db.Where("username = ?", username).First(&user).Error; err == nil {
			return &user, nil
		} else if !errors.Is(err, gorm.ErrRecordNotFound) {
			logger.Errorf("查询用户失败: %v", err)
		}
	}
	return nil, gorm.ErrRecordNotFound
}
