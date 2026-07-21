package handler

import (
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/pkg/response"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type SkillHandler struct {
	db *gorm.DB
}

func NewSkillHandler(db *gorm.DB) *SkillHandler {
	return &SkillHandler{db: db}
}

func (h *SkillHandler) List(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var skills []model.ProjectAgentSkill
	if err := h.db.Where("project_id = ?", projectID).Order("is_default DESC, created_at DESC").Find(&skills).Error; err != nil {
		response.ServerError(c, "查询技能列表失败")
		return
	}

	response.Success(c, skills)
}

func (h *SkillHandler) Create(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req struct {
		Name             string `json:"name" binding:"required"`
		AgentType        string `json:"agentType" binding:"required"`
		Instruction      string `json:"instruction"`
		Tools            string `json:"tools"`
		MCPServerIDs     string `json:"mcpServerIds"`
		MemoryCategories string `json:"memoryCategories"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	skill := model.ProjectAgentSkill{
		ProjectID:        projectID,
		Name:             req.Name,
		AgentType:        req.AgentType,
		Instruction:      req.Instruction,
		Tools:            req.Tools,
		MCPServerIDs:     req.MCPServerIDs,
		MemoryCategories: req.MemoryCategories,
		Enabled:          true,
		IsDefault:        false,
		CreatedBy:        middleware.GetUserID(c),
		CreatedAt:        time.Now(),
		UpdatedAt:        time.Now(),
	}
	if err := h.db.Create(&skill).Error; err != nil {
		response.ServerError(c, "创建技能失败")
		return
	}

	response.Success(c, skill)
}

func (h *SkillHandler) Update(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	skillID, err := parsePathUintParam(c, "skillId")
	if err != nil {
		response.BadRequest(c, "无效的技能 ID")
		return
	}

	var req struct {
		Name             *string `json:"name"`
		AgentType        *string `json:"agentType"`
		Instruction      *string `json:"instruction"`
		Tools            *string `json:"tools"`
		MCPServerIDs     *string `json:"mcpServerIds"`
		MemoryCategories *string `json:"memoryCategories"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	var skill model.ProjectAgentSkill
	if err := h.db.Where("id = ? AND project_id = ?", skillID, projectID).First(&skill).Error; err != nil {
		response.NotFound(c, "技能不存在")
		return
	}

	updates := map[string]interface{}{"updated_at": time.Now()}
	if req.Name != nil {
		updates["name"] = *req.Name
	}
	if req.AgentType != nil {
		updates["agent_type"] = *req.AgentType
	}
	if req.Instruction != nil {
		updates["instruction"] = *req.Instruction
	}
	if req.Tools != nil {
		updates["tools"] = *req.Tools
	}
	if req.MCPServerIDs != nil {
		updates["mcp_server_ids"] = *req.MCPServerIDs
	}
	if req.MemoryCategories != nil {
		updates["memory_categories"] = *req.MemoryCategories
	}

	if err := h.db.Model(&skill).Updates(updates).Error; err != nil {
		response.ServerError(c, "更新技能失败")
		return
	}
	if err := h.db.First(&skill, skillID).Error; err != nil {
		response.ServerError(c, "查询技能失败")
		return
	}

	response.Success(c, skill)
}

func (h *SkillHandler) Delete(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	skillID, err := parsePathUintParam(c, "skillId")
	if err != nil {
		response.BadRequest(c, "无效的技能 ID")
		return
	}

	var skill model.ProjectAgentSkill
	if err := h.db.Where("id = ? AND project_id = ?", skillID, projectID).First(&skill).Error; err != nil {
		response.NotFound(c, "技能不存在")
		return
	}

	if skill.IsDefault {
		response.BadRequest(c, "默认技能不可删除")
		return
	}

	if err := h.db.Delete(&skill).Error; err != nil {
		response.ServerError(c, "删除技能失败")
		return
	}
	response.Success(c, gin.H{"message": "已删除"})
}

func (h *SkillHandler) Toggle(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	skillID, err := parsePathUintParam(c, "skillId")
	if err != nil {
		response.BadRequest(c, "无效的技能 ID")
		return
	}

	var skill model.ProjectAgentSkill
	if err := h.db.Where("id = ? AND project_id = ?", skillID, projectID).First(&skill).Error; err != nil {
		response.NotFound(c, "技能不存在")
		return
	}

	newEnabled := !skill.Enabled
	result := h.db.Model(&skill).Where("id = ? AND enabled = ?", skillID, skill.Enabled).Updates(map[string]interface{}{
		"enabled":    newEnabled,
		"updated_at": time.Now(),
	})
	if result.Error != nil {
		response.ServerError(c, "切换技能状态失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "技能状态已被其他操作修改，请刷新重试")
		return
	}
	skill.Enabled = newEnabled
	skill.UpdatedAt = time.Now()

	response.Success(c, skill)
}
