package handler

import (
	"bug-agent/internal/adk"
	"bug-agent/internal/model"
	"bug-agent/internal/retrieval"
	"bug-agent/pkg/response"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type RetrieverPluginHandler struct {
	db *gorm.DB
}

type retrieverPluginView struct {
	ID           uint                    `json:"id"`
	ProjectID    uint                    `json:"projectId"`
	Name         string                  `json:"name"`
	DisplayName  string                  `json:"displayName"`
	Description  string                  `json:"description"`
	Config       string                  `json:"config"`
	ConfigSchema *retrieval.ConfigSchema `json:"configSchema,omitempty"`
	Enabled      bool                    `json:"enabled"`
	SortOrder    int                     `json:"sortOrder"`
	IsBuiltIn    bool                    `json:"isBuiltIn"`
	CreatedBy    uint                    `json:"createdBy"`
	CreatedAt    time.Time               `json:"createdAt"`
	UpdatedAt    time.Time               `json:"updatedAt"`
}

func NewRetrieverPluginHandler(db *gorm.DB) *RetrieverPluginHandler {
	return &RetrieverPluginHandler{db: db}
}

func (h *RetrieverPluginHandler) List(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	if err := retrieval.NormalizePluginSortOrders(h.db, projectID); err != nil {
		response.ServerError(c, "归一化检索插件排序失败")
		return
	}

	var plugins []model.RetrieverPlugin
	if err := h.db.Where("project_id = ?", projectID).Order("sort_order ASC").Find(&plugins).Error; err != nil {
		response.ServerError(c, "查询检索插件列表失败")
		return
	}

	response.Success(c, h.toViews(plugins))
}

func (h *RetrieverPluginHandler) Update(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	pluginID, err := parsePathUintParam(c, "pluginId")
	if err != nil {
		response.BadRequest(c, "无效的插件 ID")
		return
	}

	var req struct {
		Config      *string `json:"config"`
		Enabled     *bool   `json:"enabled"`
		SortOrder   *int    `json:"sortOrder"`
		DisplayName *string `json:"displayName"`
		Description *string `json:"description"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	var plugin model.RetrieverPlugin
	if err := h.db.Where("id = ? AND project_id = ?", pluginID, projectID).First(&plugin).Error; err != nil {
		response.NotFound(c, "检索插件不存在")
		return
	}

	updates := map[string]interface{}{"updated_at": time.Now()}
	if req.Config != nil {
		updates["config"] = *req.Config
	}
	if req.Enabled != nil {
		updates["enabled"] = *req.Enabled
	}
	if req.SortOrder != nil {
		updates["sort_order"] = *req.SortOrder
	}
	if req.DisplayName != nil {
		updates["display_name"] = *req.DisplayName
	}
	if req.Description != nil {
		updates["description"] = *req.Description
	}

	if err := h.db.Model(&plugin).Updates(updates).Error; err != nil {
		response.ServerError(c, "更新检索插件失败")
		return
	}
	if req.SortOrder != nil {
		if err := retrieval.NormalizePluginSortOrders(h.db, projectID); err != nil {
			response.ServerError(c, "归一化检索插件排序失败")
			return
		}
	}
	if err := h.db.First(&plugin, pluginID).Error; err != nil {
		response.ServerError(c, "查询检索插件失败")
		return
	}

	response.Success(c, h.toView(plugin))
}

func (h *RetrieverPluginHandler) Toggle(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	pluginID, err := parsePathUintParam(c, "pluginId")
	if err != nil {
		response.BadRequest(c, "无效的插件 ID")
		return
	}

	var plugin model.RetrieverPlugin
	if err := h.db.Where("id = ? AND project_id = ?", pluginID, projectID).First(&plugin).Error; err != nil {
		response.NotFound(c, "检索插件不存在")
		return
	}

	newEnabled := !plugin.Enabled
	result := h.db.Model(&plugin).Where("id = ? AND enabled = ?", pluginID, plugin.Enabled).Updates(map[string]interface{}{
		"enabled":    newEnabled,
		"updated_at": time.Now(),
	})
	if result.Error != nil {
		response.ServerError(c, "切换检索插件状态失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "检索插件状态已被其他操作修改，请刷新重试")
		return
	}
	plugin.Enabled = newEnabled
	plugin.UpdatedAt = time.Now()

	response.Success(c, h.toView(plugin))
}

func (h *RetrieverPluginHandler) BatchSort(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req struct {
		Items []struct {
			ID        uint `json:"id" binding:"required"`
			SortOrder int  `json:"sortOrder"`
		} `json:"items" binding:"required"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	tx := h.db.Begin()
	for _, item := range req.Items {
		if err := tx.Model(&model.RetrieverPlugin{}).
			Where("id = ? AND project_id = ?", item.ID, projectID).
			Updates(map[string]interface{}{"sort_order": item.SortOrder, "updated_at": time.Now()}).Error; err != nil {
			tx.Rollback()
			response.ServerError(c, "批量排序失败")
			return
		}
	}
	if err := tx.Commit().Error; err != nil {
		response.ServerError(c, "批量排序失败")
		return
	}

	response.Success(c, gin.H{"message": "排序已更新"})
}

func (h *RetrieverPluginHandler) toViews(plugins []model.RetrieverPlugin) []retrieverPluginView {
	views := make([]retrieverPluginView, 0, len(plugins))
	for _, plugin := range plugins {
		views = append(views, h.toView(plugin))
	}
	return views
}

func (h *RetrieverPluginHandler) toView(plugin model.RetrieverPlugin) retrieverPluginView {
	return retrieverPluginView{
		ID:           plugin.ID,
		ProjectID:    plugin.ProjectID,
		Name:         plugin.Name,
		DisplayName:  plugin.DisplayName,
		Description:  plugin.Description,
		Config:       plugin.Config,
		ConfigSchema: retrieverConfigSchema(plugin.Name),
		Enabled:      plugin.Enabled,
		SortOrder:    plugin.SortOrder,
		IsBuiltIn:    plugin.IsBuiltIn,
		CreatedBy:    plugin.CreatedBy,
		CreatedAt:    plugin.CreatedAt,
		UpdatedAt:    plugin.UpdatedAt,
	}
}

func retrieverConfigSchema(name string) *retrieval.ConfigSchema {
	if adk.GlobalRegistry == nil {
		adk.InitRegistry()
	}
	if adk.GlobalRegistry == nil {
		return nil
	}
	return adk.GlobalRegistry.ConfigSchema(name)
}

func (h *RetrieverPluginHandler) Test(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	pluginID, err := parsePathUintParam(c, "pluginId")
	if err != nil {
		response.BadRequest(c, "无效的插件 ID")
		return
	}

	var plugin model.RetrieverPlugin
	if err := h.db.Where("id = ? AND project_id = ?", pluginID, projectID).First(&plugin).Error; err != nil {
		response.NotFound(c, "检索插件不存在")
		return
	}

	if plugin.Name == "keyword" {
		response.Success(c, gin.H{"connected": true})
		return
	}

	if adk.GlobalRegistry == nil || !adk.GlobalRegistry.Has(plugin.Name) {
		response.Success(c, gin.H{"connected": false, "error": "未注册的检索插件: " + plugin.Name})
		return
	}

	retriever, connErr := adk.GlobalRegistry.Create(plugin.Name, plugin.Config)
	if connErr != nil {
		response.Success(c, gin.H{"connected": false, "error": connErr.Error()})
		return
	}

	if retriever == nil {
		response.Success(c, gin.H{"connected": false, "error": "创建检索实例失败"})
		return
	}

	response.Success(c, gin.H{"connected": true})
}
