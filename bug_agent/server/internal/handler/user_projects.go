package handler

import (
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/pkg/response"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type UserProjectsHandler struct {
	db *gorm.DB
}

func NewUserProjectsHandler(db *gorm.DB) *UserProjectsHandler { return &UserProjectsHandler{db: db} }

// ListUserProjects 获取当前用户参与的所有项目
func (h *UserProjectsHandler) ListUserProjects(c *gin.Context) {
	userID := middleware.GetUserID(c)

	// 一次查询取到用户可见项目，避免 projectID pluck + 再次查询项目详情。
	var projects []model.Project
	if err := h.db.Model(&model.Project{}).
		Select("projects.*").
		Joins("JOIN project_members ON project_members.project_id = projects.id").
		Where("project_members.user_id = ?", userID).
		Order("projects.created_at DESC").
		Find(&projects).Error; err != nil {
		response.ServerError(c, "查询项目列表失败")
		return
	}
	if len(projects) == 0 {
		response.Success(c, gin.H{"items": []interface{}{}})
		return
	}

	projectIDs := make([]uint, 0, len(projects))
	for _, p := range projects {
		projectIDs = append(projectIDs, p.ID)
	}

	pendingStatuses := []string{"new", "pending_assign", "pending_analysis"}
	activeStatuses := []string{"analyzing", "pending_fix", "fixing", "pending_verify"}

	type defectStatRow struct {
		ProjectID      uint  `gorm:"column:project_id"`
		PendingDefects int64 `gorm:"column:pending_defects"`
		ActiveDefects  int64 `gorm:"column:active_defects"`
	}
	var defectRows []defectStatRow
	if err := h.db.Table("iterations AS i").
		Select(`
			i.project_id AS project_id,
			COALESCE(SUM(CASE WHEN d.status IN ? THEN 1 ELSE 0 END), 0) AS pending_defects,
			COALESCE(SUM(CASE WHEN d.status IN ? THEN 1 ELSE 0 END), 0) AS active_defects
		`, pendingStatuses, activeStatuses).
		Joins("LEFT JOIN defects AS d ON d.iteration_id = i.id").
		Where("i.project_id IN ?", projectIDs).
		Group("i.project_id").
		Scan(&defectRows).Error; err != nil {
		response.ServerError(c, "查询缺陷统计失败")
		return
	}
	defectStatsByProject := make(map[uint]defectStatRow, len(defectRows))
	for _, row := range defectRows {
		defectStatsByProject[row.ProjectID] = row
	}

	type memberCountRow struct {
		ProjectID   uint  `gorm:"column:project_id"`
		MemberCount int64 `gorm:"column:member_count"`
	}
	var memberCountRows []memberCountRow
	if err := h.db.Table("project_members").
		Select("project_id, COUNT(*) AS member_count").
		Where("project_id IN ?", projectIDs).
		Group("project_id").
		Scan(&memberCountRows).Error; err != nil {
		response.ServerError(c, "查询成员统计失败")
		return
	}
	memberCountByProject := make(map[uint]int64, len(memberCountRows))
	for _, row := range memberCountRows {
		memberCountByProject[row.ProjectID] = row.MemberCount
	}

	type memberPreviewRow struct {
		ProjectID uint   `gorm:"column:project_id"`
		ID        uint   `gorm:"column:id"`
		Nickname  string `gorm:"column:nickname"`
		Avatar    string `gorm:"column:avatar"`
	}
	var memberRows []memberPreviewRow
	if err := h.db.Raw(`
		SELECT pm_ranked.project_id, u.id, u.nickname, u.avatar
		FROM (
			SELECT pm.project_id, pm.user_id,
				ROW_NUMBER() OVER (PARTITION BY pm.project_id ORDER BY pm.id ASC) AS rn
			FROM project_members pm
			WHERE pm.project_id IN ?
		) pm_ranked
		JOIN users u ON u.id = pm_ranked.user_id
		WHERE pm_ranked.rn <= 5
		ORDER BY pm_ranked.project_id ASC, pm_ranked.rn ASC
	`, projectIDs).Scan(&memberRows).Error; err != nil {
		response.ServerError(c, "查询成员列表失败")
		return
	}
	membersByProject := make(map[uint][]map[string]interface{}, len(projects))
	for _, row := range memberRows {
		membersByProject[row.ProjectID] = append(membersByProject[row.ProjectID], map[string]interface{}{
			"id":       row.ID,
			"nickname": row.Nickname,
			"avatar":   row.Avatar,
		})
	}

	// 构建返回数据
	list := make([]map[string]interface{}, 0, len(projects))
	for _, p := range projects {
		stats := defectStatsByProject[p.ID]

		list = append(list, map[string]interface{}{
			"id":             p.ID,
			"name":           p.Name,
			"code":           p.Code,
			"description":    p.Description,
			"status":         p.Status,
			"pendingDefects": stats.PendingDefects,
			"activeDefects":  stats.ActiveDefects,
			"members":        membersByProject[p.ID],
			"memberCount":    memberCountByProject[p.ID],
			"createdAt":      p.CreatedAt,
		})
	}

	response.Success(c, gin.H{"items": list})
}

// GetProjectStats 获取项目统计汇总
func (h *UserProjectsHandler) GetProjectStats(c *gin.Context) {
	projectID := c.Param("id")

	type statsRow struct {
		Total     int64 `gorm:"column:total"`
		Pending   int64 `gorm:"column:pending"`
		Fixing    int64 `gorm:"column:fixing"`
		Completed int64 `gorm:"column:completed"`
		Urgent    int64 `gorm:"column:urgent"`
	}
	var stats statsRow

	pendingStatuses := []string{"new", "pending_assign", "pending_analysis"}
	fixingStatuses := []string{"analyzing", "pending_fix", "fixing", "pending_verify"}
	completedStatuses := []string{"fixed", "completed"}

	if err := h.db.Table("iterations AS i").
		Select(`
			COALESCE(COUNT(d.id), 0) AS total,
			COALESCE(SUM(CASE WHEN d.status IN ? THEN 1 ELSE 0 END), 0) AS pending,
			COALESCE(SUM(CASE WHEN d.status IN ? THEN 1 ELSE 0 END), 0) AS fixing,
			COALESCE(SUM(CASE WHEN d.status IN ? THEN 1 ELSE 0 END), 0) AS completed,
			COALESCE(SUM(CASE WHEN d.priority IN ? AND d.status NOT IN ? THEN 1 ELSE 0 END), 0) AS urgent
		`, pendingStatuses, fixingStatuses, completedStatuses, []string{"P0", "P1"}, completedStatuses).
		Joins("LEFT JOIN defects AS d ON d.iteration_id = i.id").
		Where("i.project_id = ?", projectID).
		Scan(&stats).Error; err != nil {
		response.ServerError(c, "查询项目统计失败")
		return
	}

	response.Success(c, gin.H{
		"total":     stats.Total,
		"pending":   stats.Pending,
		"fixing":    stats.Fixing,
		"completed": stats.Completed,
		"urgent":    stats.Urgent,
	})
}
