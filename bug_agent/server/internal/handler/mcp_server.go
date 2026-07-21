package handler

import (
	"bug-agent/internal/adk"
	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/pkg/response"
	"encoding/json"
	"fmt"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type MCPServerHandler struct {
	db *gorm.DB
}

func NewMCPServerHandler(db *gorm.DB) *MCPServerHandler {
	return &MCPServerHandler{db: db}
}

func (h *MCPServerHandler) List(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var servers []model.ProjectMCPServer
	if err := h.db.Where("project_id = ?", projectID).Order("created_at DESC").Find(&servers).Error; err != nil {
		response.ServerError(c, "查询 MCP 服务失败")
		return
	}

	response.Success(c, servers)
}

func (h *MCPServerHandler) Create(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}

	var req struct {
		Name        string `json:"name" binding:"required"`
		Command     string `json:"command" binding:"required"`
		Args        string `json:"args"`
		Description string `json:"description"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	if !adk.IsAllowedMCPCommand(req.Command) {
		response.BadRequest(c, "MCP 命令不在白名单中")
		return
	}

	server := model.ProjectMCPServer{
		ProjectID:   projectID,
		Name:        req.Name,
		Command:     req.Command,
		Args:        req.Args,
		Description: req.Description,
		Enabled:     true,
		CreatedBy:   middleware.GetUserID(c),
		CreatedAt:   time.Now(),
		UpdatedAt:   time.Now(),
	}
	if err := h.db.Create(&server).Error; err != nil {
		response.ServerError(c, "创建 MCP 服务失败")
		return
	}

	response.Success(c, server)
}

func (h *MCPServerHandler) Update(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	serverID, err := parsePathUintParam(c, "serverId")
	if err != nil {
		response.BadRequest(c, "无效的服务 ID")
		return
	}

	var req struct {
		Name        *string `json:"name"`
		Command     *string `json:"command"`
		Args        *string `json:"args"`
		Description *string `json:"description"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		response.BadRequest(c, err.Error())
		return
	}

	var server model.ProjectMCPServer
	if err := h.db.Where("id = ? AND project_id = ?", serverID, projectID).First(&server).Error; err != nil {
		response.NotFound(c, "MCP 服务不存在")
		return
	}

	updates := map[string]interface{}{"updated_at": time.Now()}
	if req.Name != nil {
		updates["name"] = *req.Name
	}
	if req.Command != nil {
		if !adk.IsAllowedMCPCommand(*req.Command) {
			response.BadRequest(c, "MCP 命令不在白名单中")
			return
		}
		updates["command"] = *req.Command
	}
	if req.Args != nil {
		updates["args"] = *req.Args
	}
	if req.Description != nil {
		updates["description"] = *req.Description
	}

	if err := h.db.Model(&server).Updates(updates).Error; err != nil {
		response.ServerError(c, "更新 MCP 服务失败")
		return
	}
	if err := h.db.First(&server, serverID).Error; err != nil {
		response.ServerError(c, "查询 MCP 服务失败")
		return
	}

	response.Success(c, server)
}

func (h *MCPServerHandler) Delete(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	serverID, err := parsePathUintParam(c, "serverId")
	if err != nil {
		response.BadRequest(c, "无效的服务 ID")
		return
	}

	result := h.db.Where("id = ? AND project_id = ?", serverID, projectID).Delete(&model.ProjectMCPServer{})
	if result.RowsAffected == 0 {
		response.NotFound(c, "MCP 服务不存在")
		return
	}

	response.Success(c, gin.H{"message": "已删除"})
}

func (h *MCPServerHandler) Toggle(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	serverID, err := parsePathUintParam(c, "serverId")
	if err != nil {
		response.BadRequest(c, "无效的服务 ID")
		return
	}

	var server model.ProjectMCPServer
	if err := h.db.Where("id = ? AND project_id = ?", serverID, projectID).First(&server).Error; err != nil {
		response.NotFound(c, "MCP 服务不存在")
		return
	}

	newEnabled := !server.Enabled
	result := h.db.Model(&server).Where("id = ? AND enabled = ?", serverID, server.Enabled).Updates(map[string]interface{}{
		"enabled":    newEnabled,
		"updated_at": time.Now(),
	})
	if result.Error != nil {
		response.ServerError(c, "切换 MCP 服务状态失败")
		return
	}
	if result.RowsAffected == 0 {
		response.Conflict(c, "MCP 服务状态已被其他操作修改，请刷新重试")
		return
	}
	server.Enabled = newEnabled
	server.UpdatedAt = time.Now()

	response.Success(c, server)
}

func (h *MCPServerHandler) TestConnection(c *gin.Context) {
	projectID, err := parsePathUintParam(c, "id")
	if err != nil {
		response.BadRequest(c, "无效的项目 ID")
		return
	}
	serverID, err := parsePathUintParam(c, "serverId")
	if err != nil {
		response.BadRequest(c, "无效的服务 ID")
		return
	}

	var server model.ProjectMCPServer
	if err := h.db.Where("id = ? AND project_id = ?", serverID, projectID).First(&server).Error; err != nil {
		response.NotFound(c, "MCP 服务不存在")
		return
	}

	var args []string
	if server.Args != "" {
		parsedArgs, err := parseArgsFromString(server.Args)
		if err != nil {
			response.BadRequest(c, "args 参数格式错误")
			return
		}
		args = parsedArgs
	}

	_, connErr := adk.NewMCPToolset(server.Command, args...)
	if connErr != nil {
		response.Success(c, gin.H{"connected": false, "error": connErr.Error()})
		return
	}

	response.Success(c, gin.H{"connected": true})
}

func parseArgsFromString(argsStr string) ([]string, error) {
	if argsStr == "" {
		return nil, nil
	}
	var args []string
	if err := json.Unmarshal([]byte(argsStr), &args); err != nil {
		return nil, fmt.Errorf("invalid args JSON: %w", err)
	}
	return args, nil
}
