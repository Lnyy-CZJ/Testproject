package handler

import (
	"bug-agent/internal/git"
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/logger"
	"bug-agent/pkg/response"
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

const repoBranchTimeout = 15 * time.Second

type ProjectHandler struct {
	db *gorm.DB
}

func NewProjectHandler(db *gorm.DB) *ProjectHandler { return &ProjectHandler{db: db} }

// ListProjects 获取当前用户可访问的项目列表
func (h *ProjectHandler) ListProjects(c *gin.Context) {
	userID := middleware.GetUserID(c)
	if userID == 0 {
		response.Unauthorized(c, "未登录")
		return
	}

	page, pageSize := parsePagination(c, 200)

	keyword := strings.TrimSpace(c.Query("keyword"))

	allowAll := strings.EqualFold(c.Query("all"), "true") && isPlatformAdmin(h.db, userID)

	query := h.db.Model(&model.Project{})
	if !allowAll {
		query = query.
			Joins("JOIN project_members ON project_members.project_id = projects.id").
			Where("project_members.user_id = ?", userID)
	}

	if keyword != "" {
		query = query.Where("projects.name LIKE ? OR projects.code LIKE ?", "%"+EscapeLike(keyword)+"%", "%"+EscapeLike(keyword)+"%")
	}

	var total int64
	if err := query.Count(&total).Error; err != nil {
		response.ServerError(c, "查询失败")
		return
	}

	var items []model.Project
	if total > 0 {
		if err := query.
			Select("projects.*").
			Order("projects.created_at DESC").
			Offset((page - 1) * pageSize).
			Limit(pageSize).
			Find(&items).Error; err != nil {
			response.ServerError(c, "查询项目列表失败")
			return
		}
	}

	response.SuccessPage(c, items, total, page, pageSize)
}

func (h *ProjectHandler) CreateProject(c *gin.Context) {
	userID := middleware.GetUserID(c)

	var req struct {
		Name        string `json:"name" binding:"required,max=100"`
		Code        string `json:"code" binding:"required,max=20"`
		Description string `json:"description"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	req.Name = strings.TrimSpace(req.Name)
	req.Code = strings.ToUpper(strings.TrimSpace(req.Code))
	req.Description = strings.TrimSpace(req.Description)
	if req.Name == "" || req.Code == "" {
		response.BadRequest(c, "项目名称和编码不能为空")
		return
	}

	var duplicate int64
	if err := h.db.Model(&model.Project{}).
		Where("LOWER(code) = LOWER(?)", req.Code).
		Count(&duplicate).Error; err != nil {
		response.ServerError(c, "校验项目编码失败")
		return
	}
	if duplicate > 0 {
		response.BadRequest(c, "项目编码已存在")
		return
	}

	project := model.Project{
		Name:        req.Name,
		Code:        req.Code,
		Description: req.Description,
		Status:      "active",
	}

	err := h.db.Transaction(func(tx *gorm.DB) error {
		if result := tx.Create(&project); result.Error != nil {
			return result.Error
		}
		member := model.ProjectMember{
			ProjectID: project.ID,
			UserID:    userID,
			Role:      "project_admin",
		}
		if result := tx.Create(&member); result.Error != nil {
			return result.Error
		}
		for _, p := range []model.RetrieverPlugin{
			{ProjectID: project.ID, Name: "keyword", DisplayName: "仓库关键词检索", Description: "基于文件名和内容的关键词匹配", Config: "{}", Enabled: true, SortOrder: 0, IsBuiltIn: true},
			{ProjectID: project.ID, Name: "rag", DisplayName: "RAG 语义检索", Description: "基于向量数据库的语义检索", Config: "{}", Enabled: false, SortOrder: 1, IsBuiltIn: true},
			{ProjectID: project.ID, Name: "requirement", DisplayName: "需求文档检索", Description: "从需求文档中检索相关上下文", Config: "{}", Enabled: false, SortOrder: 2, IsBuiltIn: true},
		} {
			if result := tx.Create(&p); result.Error != nil {
				return result.Error
			}
		}
		return nil
	})
	if err != nil {
		response.BadRequest(c, "创建项目失败，项目代码可能已存在")
		return
	}

	middleware.InvalidateRBACCache(userID)

	response.Created(c, project)
}

func (h *ProjectHandler) GetProject(c *gin.Context) {
	id, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	var project model.Project
	if err := h.db.First(&project, id).Error; err != nil {
		response.NotFound(c, "项目不存在")
		return
	}

	var members []model.ProjectMember
	if err := h.db.Where("project_id = ?", id).Find(&members).Error; err != nil {
		response.ServerError(c, "查询项目成员失败")
		return
	}

	userIDs := make([]uint, 0, len(members))
	for _, m := range members {
		userIDs = append(userIDs, m.UserID)
	}

	var users []model.User
	if len(userIDs) > 0 {
		if err := h.db.Select("id, username, nickname, agent_types").Where("id IN ?", userIDs).Find(&users).Error; err != nil {
			logger.Errorf("[ProjectHandler] query users failed: %v", err)
		}
	}

	memberUsers := make([]map[string]interface{}, 0, len(members))
	for _, m := range members {
		var u *model.User
		for i := range users {
			if users[i].ID == m.UserID {
				u = &users[i]
				break
			}
		}
		if u == nil {
			continue
		}
		publicUser := u.PublicUser()
		publicUser["memberId"] = m.ID
		publicUser["userId"] = m.UserID
		publicUser["role"] = m.Role
		memberUsers = append(memberUsers, publicUser)
	}

	var iterations []model.Iteration
	if err := h.db.Where("project_id = ?", id).Order("start_date DESC").Find(&iterations).Error; err != nil {
		logger.Errorf("[ProjectHandler] query iterations failed: %v", err)
	}

	response.Success(c, gin.H{
		"project":    project,
		"members":    memberUsers,
		"iterations": iterations,
	})
}

func (h *ProjectHandler) UpdateProject(c *gin.Context) {
	id, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	var req struct {
		Name          string `json:"name"`
		Description   string `json:"description"`
		Status        string `json:"status"`
		MemoryEnabled *bool  `json:"memoryEnabled"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	updates := map[string]interface{}{}
	if req.Name != "" {
		updates["name"] = req.Name
	}
	if req.Description != "" {
		updates["description"] = req.Description
	}
	if req.Status != "" {
		validStatuses := map[string]bool{"active": true, "archived": true}
		if !validStatuses[req.Status] {
			response.BadRequest(c, "无效的项目状态，仅支持 active/archived")
			return
		}
		updates["status"] = req.Status
	}
	if req.MemoryEnabled != nil {
		updates["memory_enabled"] = *req.MemoryEnabled
	}

	if err := h.db.Model(&model.Project{}).Where("id = ?", id).Updates(updates).Error; err != nil {
		response.ServerError(c, "更新项目失败")
		return
	}
	var project model.Project
	if err := h.db.First(&project, id).Error; err != nil {
		response.ServerError(c, "查询失败")
		return
	}
	response.Success(c, project)
}

func (h *ProjectHandler) AddMember(c *gin.Context) {
	id, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	var req struct {
		UserID uint   `json:"userId" binding:"required"`
		Role   string `json:"role" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}
	role, ok := normalizeProjectRole(req.Role)
	if !ok {
		response.BadRequest(c, "无效的项目角色")
		return
	}

	member := model.ProjectMember{ProjectID: uint(id), UserID: req.UserID, Role: role}
	if result := h.db.Create(&member); result.Error != nil {
		response.BadRequest(c, "该用户已是项目成员")
		return
	}
	middleware.InvalidateRBACCache(req.UserID)
	response.Created(c, member)
}

func (h *ProjectHandler) RemoveMember(c *gin.Context) {
	id, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	memberID, ok := parseIDParam(c, "memberId")
	if !ok {
		return
	}

	var member model.ProjectMember
	if err := h.db.Where("id = ? AND project_id = ?", memberID, id).First(&member).Error; err != nil {
		response.NotFound(c, "成员不存在")
		return
	}

	if member.Role == "project_admin" {
		err := h.db.Transaction(func(tx *gorm.DB) error {
			var adminCount int64
			tx.Set("gorm:query_option", "FOR UPDATE").Model(&model.ProjectMember{}).Where("project_id = ? AND role = ? AND id != ?", id, "project_admin", memberID).Count(&adminCount)
			if adminCount == 0 {
				return fmt.Errorf("不能移除最后一个项目管理员，请先转移管理员角色")
			}
			return tx.Delete(&member).Error
		})
		if err != nil {
			if strings.Contains(err.Error(), "最后一个项目管理员") {
				response.BadRequest(c, err.Error())
			} else {
				response.ServerError(c, "删除项目成员失败")
			}
			return
		}
	} else {
		if err := h.db.Delete(&member).Error; err != nil {
			response.ServerError(c, "删除项目成员失败")
			return
		}
	}
	middleware.InvalidateRBACCache(member.UserID)

	response.Success(c, nil)
}

// --- Iteration ---

func (h *ProjectHandler) CreateIteration(c *gin.Context) {
	projectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	var req struct {
		Name      string `json:"name" binding:"required,max=100"`
		StartDate string `json:"startDate" binding:"required"`
		EndDate   string `json:"endDate" binding:"required"`
		Goal      string `json:"goal"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	startDate, err := time.ParseInLocation("2006-01-02", req.StartDate, time.Local)
	if err != nil {
		response.BadRequest(c, "无效的开始日期格式，应为 YYYY-MM-DD")
		return
	}
	endDate, err := time.ParseInLocation("2006-01-02", req.EndDate, time.Local)
	if err != nil {
		response.BadRequest(c, "无效的结束日期格式，应为 YYYY-MM-DD")
		return
	}
	if endDate.Before(startDate) {
		response.BadRequest(c, "结束日期不能早于开始日期")
		return
	}

	iteration := model.Iteration{
		ProjectID: uint(projectID),
		Name:      req.Name,
		StartDate: startDate,
		EndDate:   endDate,
		Goal:      req.Goal,
		Status:    "planning",
	}
	if err := h.db.Create(&iteration).Error; err != nil {
		response.ServerError(c, "创建迭代失败")
		return
	}
	response.Created(c, iteration)
}

func (h *ProjectHandler) GetIteration(c *gin.Context) {
	id, ok := parseIDParam(c, "iterationId")
	if !ok {
		return
	}
	var iteration model.Iteration
	if err := h.db.First(&iteration, id).Error; err != nil {
		response.NotFound(c, "迭代不存在")
		return
	}

	// 查询绑定的仓库
	var repos []model.IterationRepo
	if err := h.db.Preload("Repo").Where("iteration_id = ?", id).Find(&repos).Error; err != nil {
		logger.Errorf("[ProjectHandler] query iteration repos failed: %v", err)
	}

	// 构建返回数据（仅使用关联的项目仓库）
	repoList := make([]map[string]interface{}, 0)
	for _, r := range repos {
		item := map[string]interface{}{
			"id":          r.ID,
			"iterationId": r.IterationID,
			"repoId":      r.RepoID,
			"branch":      r.Branch,
			"createdAt":   r.CreatedAt,
		}
		if r.Repo != nil {
			item["repoName"] = r.Repo.Name
			item["repoUrl"] = r.Repo.RepoURL
		}
		repoList = append(repoList, item)
	}

	var total, pendingCount, fixingCount, completedCount int64
	type defectStatsRow struct {
		Total     int64
		Pending   int64
		Fixing    int64
		Completed int64
	}
	var stats defectStatsRow
	if err := h.db.Model(&model.Defect{}).
		Select(`COUNT(*) as total,
			SUM(CASE WHEN status IN ('new','pending_analysis','pending_assign') THEN 1 ELSE 0 END) as pending,
			SUM(CASE WHEN status IN ('analyzing','pending_fix','fixing') THEN 1 ELSE 0 END) as fixing,
			SUM(CASE WHEN status IN ('fixed','completed') THEN 1 ELSE 0 END) as completed`).
		Where("iteration_id = ?", id).
		Scan(&stats).Error; err != nil {
		logger.Errorf("查询迭代缺陷统计失败: %v", err)
	}
	total = stats.Total
	pendingCount = stats.Pending
	fixingCount = stats.Fixing
	completedCount = stats.Completed

	response.Success(c, gin.H{
		"iteration":   iteration,
		"repos":       repoList,
		"defectStats": gin.H{"total": total, "pending": pendingCount, "fixing": fixingCount, "completed": completedCount},
	})
}

func (h *ProjectHandler) UpdateIteration(c *gin.Context) {
	id, ok := parseIDParam(c, "iterationId")
	if !ok {
		return
	}
	var req struct {
		Name      string `json:"name"`
		StartDate string `json:"startDate"`
		EndDate   string `json:"endDate"`
		Goal      string `json:"goal"`
		Status    string `json:"status"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	updates := map[string]interface{}{}
	if req.Name != "" {
		updates["name"] = req.Name
	}
	if req.Goal != "" {
		updates["goal"] = req.Goal
	}
	if req.Status != "" {
		validIterStatuses := map[string]bool{"planning": true, "in_progress": true, "completed": true}
		if !validIterStatuses[req.Status] {
			response.BadRequest(c, "无效的迭代状态")
			return
		}
		updates["status"] = req.Status
	}
	if req.StartDate != "" {
		parsed, err := time.ParseInLocation("2006-01-02", req.StartDate, time.Local)
		if err != nil {
			response.BadRequest(c, "无效的开始日期格式")
			return
		}
		updates["start_date"] = parsed
	}
	if req.EndDate != "" {
		parsed, err := time.ParseInLocation("2006-01-02", req.EndDate, time.Local)
		if err != nil {
			response.BadRequest(c, "无效的结束日期格式")
			return
		}
		updates["end_date"] = parsed
	}

	if len(updates) > 0 {
		var current model.Iteration
		if err := h.db.Select("start_date", "end_date").First(&current, id).Error; err != nil {
			response.ServerError(c, "查询迭代失败")
			return
		}
		startDate := current.StartDate
		endDate := current.EndDate
		if sd, ok := updates["start_date"]; ok {
			startDate = sd.(time.Time)
		}
		if ed, ok := updates["end_date"]; ok {
			endDate = ed.(time.Time)
		}
		if endDate.Before(startDate) {
			response.BadRequest(c, "结束日期不能早于开始日期")
			return
		}
	}

	if err := h.db.Model(&model.Iteration{}).Where("id = ?", id).Updates(updates).Error; err != nil {
		response.ServerError(c, "更新迭代失败")
		return
	}
	var iteration model.Iteration
	if err := h.db.First(&iteration, id).Error; err != nil {
		response.ServerError(c, "查询失败")
		return
	}
	response.Success(c, iteration)
}

func (h *ProjectHandler) ListIterations(c *gin.Context) {
	projectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	var iterations []model.Iteration
	if err := h.db.Where("project_id = ?", projectID).Order("start_date DESC").Find(&iterations).Error; err != nil {
		response.ServerError(c, "查询迭代列表失败")
		return
	}
	response.Success(c, iterations)
}

func (h *ProjectHandler) BindRepo(c *gin.Context) {
	projectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	iterationID, ok := parseIDParam(c, "iterationId")
	if !ok {
		return
	}
	var req struct {
		RepoID uint   `json:"repoId" binding:"required"`
		Branch string `json:"branch"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	var projectRepo model.ProjectRepo
	if err := h.db.Where("id = ? AND project_id = ?", req.RepoID, projectID).First(&projectRepo).Error; err != nil {
		response.BadRequest(c, "仓库不存在或不属于当前项目")
		return
	}

	var iter model.Iteration
	if err := h.db.Where("id = ? AND project_id = ?", iterationID, projectID).First(&iter).Error; err != nil {
		response.BadRequest(c, "迭代不存在或不属于当前项目")
		return
	}

	var existing model.IterationRepo
	if err := h.db.Where("iteration_id = ? AND repo_id = ?", iterationID, req.RepoID).First(&existing).Error; err == nil {
		response.BadRequest(c, "该仓库已绑定到此迭代")
		return
	}

	branch := strings.TrimSpace(req.Branch)
	if branch == "" {
		branch = strings.TrimSpace(projectRepo.DefaultBranch)
	}
	branch = model.ResolveBranch(branch)

	repoID := req.RepoID
	repo := model.IterationRepo{
		IterationID: uint(iterationID),
		RepoID:      &repoID,
		Branch:      branch,
	}
	if err := h.db.Create(&repo).Error; err != nil {
		response.ServerError(c, "绑定仓库失败")
		return
	}

	var result model.IterationRepo
	if err := h.db.Preload("Repo").First(&result, repo.ID).Error; err != nil {
		logger.Errorf("查询迭代仓库绑定失败: %v", err)
	}
	response.Created(c, result)
}

func (h *ProjectHandler) UnbindRepo(c *gin.Context) {
	repoID, ok := parseIDParam(c, "repoId")
	if !ok {
		return
	}
	if repoID == 0 {
		response.BadRequest(c, "无效的仓库绑定ID")
		return
	}
	if err := h.db.Where("id = ?", repoID).Delete(&model.IterationRepo{}).Error; err != nil {
		response.ServerError(c, "解绑仓库失败")
		return
	}
	response.Success(c, gin.H{"message": "仓库已解绑"})
}

func (h *ProjectHandler) UpdateIterationRepoBranch(c *gin.Context) {
	projectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	iterationID, ok := parseIDParam(c, "iterationId")
	if !ok {
		return
	}
	iterRepoID, ok := parseIDParam(c, "iterRepoId")
	if !ok {
		return
	}

	var iterRepo model.IterationRepo
	if err := h.db.Preload("Repo").Where("id = ? AND iteration_id = ?", iterRepoID, iterationID).First(&iterRepo).Error; err != nil {
		response.BadRequest(c, "迭代仓库绑定不存在")
		return
	}

	var iter model.Iteration
	if err := h.db.Where("id = ? AND project_id = ?", iterationID, projectID).First(&iter).Error; err != nil {
		response.BadRequest(c, "迭代不存在或不属于当前项目")
		return
	}

	var req struct {
		Branch string `json:"branch"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	branch := strings.TrimSpace(req.Branch)
	if branch == "" {
		branch = strings.TrimSpace(iterRepo.Repo.DefaultBranch)
	}
	branch = model.ResolveBranch(branch)

	if err := h.db.Model(&model.IterationRepo{}).Where("id = ?", iterRepoID).Update("branch", branch).Error; err != nil {
		response.ServerError(c, "更新分支失败")
		return
	}

	response.Success(c, gin.H{"branch": branch, "projectId": projectID})
}

func (h *ProjectHandler) ListRepoBranches(c *gin.Context) {
	projectID, ok := parseIDParam(c, "id")
	if !ok {
		return
	}
	repoID, ok := parseIDParam(c, "repoId")
	if !ok {
		return
	}

	var projectRepo model.ProjectRepo
	if err := h.db.Where("id = ? AND project_id = ?", repoID, projectID).First(&projectRepo).Error; err != nil {
		response.BadRequest(c, "仓库不存在")
		return
	}

	repoAuth, _, err := service.ResolveRepositoryAuth(h.db, uint(projectID), projectRepo, "backend", 0)
	if err != nil {
		response.ServerError(c, "解析仓库凭证失败")
		return
	}

	var auth git.Auth
	if repoAuth != nil {
		auth = *repoAuth
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), repoBranchTimeout)
	defer cancel()

	branches, err := git.ListRemoteBranches(ctx, projectRepo.RepoURL, auth)
	if err != nil {
		response.ServerErrorWithLog(c, err, "获取分支列表失败")
		return
	}

	if len(branches) == 0 {
		branches = []string{}
	}
	response.Success(c, branches)
}

func (h *ProjectHandler) GetDefects(c *gin.Context) {
	userID := middleware.GetUserID(c)
	iterationID, ok := parseIDParam(c, "iterationId")
	if !ok {
		return
	}

	query := h.db.Model(&model.Defect{}).Preload("Assignee").Preload("Reporter").Where("iteration_id = ?", iterationID)

	if status := c.Query("status"); status != "" {
		query = query.Where("status = ?", status)
	}
	if severity := c.Query("severity"); severity != "" {
		query = query.Where("severity = ?", severity)
	}
	if priority := c.Query("priority"); priority != "" {
		query = query.Where("priority = ?", priority)
	}
	if keyword := c.Query("keyword"); keyword != "" {
		query = query.Where("title LIKE ? OR code LIKE ?", "%"+EscapeLike(keyword)+"%", "%"+EscapeLike(keyword)+"%")
	}
	if assignee := c.Query("assigneeId"); assignee != "" {
		if assignee == "me" {
			query = query.Where("assignee_id = ?", userID)
		} else {
			query = query.Where("assignee_id = ?", assignee)
		}
	}
	if reporter := c.Query("reporterId"); reporter != "" {
		if reporter == "me" {
			query = query.Where("reporter_id = ?", userID)
		} else {
			query = query.Where("reporter_id = ?", reporter)
		}
	}

	sortBy := c.DefaultQuery("sortBy", "created_at")
	orderBy := c.DefaultQuery("orderBy", "desc")
	if orderBy != "asc" && orderBy != "desc" {
		orderBy = "desc"
	}
	allowedSorts := map[string]string{
		"created_at": "defects.created_at",
		"updated_at": "defects.updated_at",
		"priority":   "defects.priority",
		"severity":   "defects.severity",
	}
	sortColumn, ok := allowedSorts[sortBy]
	if !ok {
		sortBy = "created_at"
		sortColumn = allowedSorts[sortBy]
	}
	query = query.Order(sortColumn + " " + orderBy)

	page, size := parsePagination(c, 100)

	var total int64
	if err := query.Count(&total).Error; err != nil {
		response.ServerError(c, "查询失败")
		return
	}
	var defects []model.Defect
	if err := query.Offset((page - 1) * size).Limit(size).Find(&defects).Error; err != nil {
		response.ServerError(c, "查询失败")
		return
	}

	response.SuccessPage(c, defects, total, page, size)
}
