package handler

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/response"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type AgentMemoryHandler struct {
	db     *gorm.DB
	service *service.AgentMemoryService
}

func NewAgentMemoryHandler(db *gorm.DB) *AgentMemoryHandler {
	return &AgentMemoryHandler{
		db:      db,
		service: service.NewAgentMemoryService(db),
	}
}

func (h *AgentMemoryHandler) ListProjectMemories(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	var category string
	if v := c.Query("category"); v != "" {
		category = v
	}

	memories, err := h.service.ListMemories(uint(projectID), nil, category)
	if err != nil {
		response.ServerErrorWithLog(c, err, "查询记忆失败")
		return
	}

	response.Success(c, gin.H{
		"items": memories,
		"total": len(memories),
	})
}

func (h *AgentMemoryHandler) ListIterationMemories(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}
	iterID, err := strconv.ParseUint(c.Param("iterationId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的迭代ID")
		return
	}

	var category string
	if v := c.Query("category"); v != "" {
		category = v
	}

	iterIDUint := uint(iterID)
	memories, err := h.service.ListMemories(uint(projectID), &iterIDUint, category)
	if err != nil {
		response.ServerErrorWithLog(c, err, "查询记忆失败")
		return
	}

	response.Success(c, gin.H{
		"items": memories,
		"total": len(memories),
	})
}

func (h *AgentMemoryHandler) CreateProjectMemory(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}

	var req struct {
		Category       string  `json:"category" binding:"required"`
		Content        string  `json:"content" binding:"required"`
		RelevanceScore float64 `json:"relevanceScore"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	userID := getUserID(c)
	memory := &model.AgentMemory{
		ProjectID:      uint(projectID),
		Category:       req.Category,
		Content:        req.Content,
		Source:         model.MemorySourceManual,
		RelevanceScore: req.RelevanceScore,
		Enabled:        true,
		CreatedBy:      userID,
	}

	if err := h.service.CreateMemory(memory); err != nil {
		response.ServerErrorWithLog(c, err, "创建记忆失败")
		return
	}

	response.Created(c, memory)
}

func (h *AgentMemoryHandler) CreateIterationMemory(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}
	iterID, err := strconv.ParseUint(c.Param("iterationId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的迭代ID")
		return
	}

	var req struct {
		Category       string  `json:"category" binding:"required"`
		Content        string  `json:"content" binding:"required"`
		RelevanceScore float64 `json:"relevanceScore"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	iterIDUint := uint(iterID)
	userID := getUserID(c)
	memory := &model.AgentMemory{
		ProjectID:      uint(projectID),
		IterationID:    &iterIDUint,
		Category:       req.Category,
		Content:        req.Content,
		Source:         model.MemorySourceManual,
		RelevanceScore: req.RelevanceScore,
		Enabled:        true,
		CreatedBy:      userID,
	}

	if err := h.service.CreateMemory(memory); err != nil {
		response.ServerErrorWithLog(c, err, "创建记忆失败")
		return
	}

	response.Created(c, memory)
}

func (h *AgentMemoryHandler) UpdateMemory(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}
	memoryID, err := strconv.ParseUint(c.Param("memoryId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的记忆ID")
		return
	}

	existing, err := h.service.GetMemory(uint(memoryID))
	if err != nil || existing == nil {
		response.NotFound(c, "记忆不存在")
		return
	}
	if existing.ProjectID != uint(projectID) {
		response.Forbidden(c, "记忆不属于当前项目")
		return
	}

	var req struct {
		Category       *string  `json:"category"`
		Content        *string  `json:"content"`
		RelevanceScore *float64 `json:"relevanceScore"`
		Enabled        *bool    `json:"enabled"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, "参数错误: "+err.Error())
		return
	}

	updates := map[string]interface{}{}
	if req.Category != nil {
		updates["category"] = *req.Category
	}
	if req.Content != nil {
		updates["content"] = *req.Content
	}
	if req.RelevanceScore != nil {
		updates["relevance_score"] = *req.RelevanceScore
	}
	if req.Enabled != nil {
		updates["enabled"] = *req.Enabled
	}

	if err := h.service.UpdateMemory(uint(memoryID), updates); err != nil {
		response.ServerErrorWithLog(c, err, "更新记忆失败")
		return
	}

	updated, err := h.service.GetMemory(uint(memoryID))
	if err != nil {
		response.ServerErrorWithLog(c, err, "查询更新后的记忆失败")
		return
	}
	response.Success(c, updated)
}

func (h *AgentMemoryHandler) DeleteMemory(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}
	memoryID, err := strconv.ParseUint(c.Param("memoryId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的记忆ID")
		return
	}

	existing, err := h.service.GetMemory(uint(memoryID))
	if err != nil || existing == nil {
		response.NotFound(c, "记忆不存在")
		return
	}
	if existing.ProjectID != uint(projectID) {
		response.Forbidden(c, "记忆不属于当前项目")
		return
	}

	if err := h.service.DeleteMemory(uint(memoryID)); err != nil {
		response.ServerErrorWithLog(c, err, "删除记忆失败")
		return
	}

	response.Success(c, gin.H{"message": "记忆已删除"})
}

func (h *AgentMemoryHandler) ToggleMemory(c *gin.Context) {
	projectID, err := strconv.ParseUint(c.Param("id"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的项目ID")
		return
	}
	memoryID, err := strconv.ParseUint(c.Param("memoryId"), 10, 64)
	if err != nil {
		response.BadRequest(c, "无效的记忆ID")
		return
	}

	existing, err := h.service.GetMemory(uint(memoryID))
	if err != nil || existing == nil {
		response.NotFound(c, "记忆不存在")
		return
	}
	if existing.ProjectID != uint(projectID) {
		response.Forbidden(c, "记忆不属于当前项目")
		return
	}

	if err := h.service.ToggleMemory(uint(memoryID)); err != nil {
		response.ServerErrorWithLog(c, err, "切换记忆状态失败")
		return
	}

	updated, err := h.service.GetMemory(uint(memoryID))
	if err != nil {
		response.ServerErrorWithLog(c, err, "查询切换后的记忆失败")
		return
	}
	response.Success(c, updated)
}
