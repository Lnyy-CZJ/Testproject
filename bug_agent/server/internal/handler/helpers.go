package handler

import (
	"errors"
	"strconv"
	"strings"

	"bug-agent/pkg/response"

	"github.com/gin-gonic/gin"
)

// allowedAgentTypeSet 定义所有合法的 AGENT 类型，auth.go 和 project_repo.go 共享
var allowedAgentTypeSet = map[string]bool{
	"product":  true,
	"ui":       true,
	"frontend": true,
	"client":   true,
	"backend":  true,
	"test":     true,
}

var errInvalidAgentType = errors.New("无效的AGENT类型")

func parseIDParam(c *gin.Context, name string) (uint64, bool) {
	id, err := strconv.ParseUint(c.Param(name), 10, 64)
	if err != nil || id == 0 {
		response.BadRequest(c, "无效的"+name)
		return 0, false
	}
	return id, true
}

func parsePagination(c *gin.Context, maxPageSize int) (page, pageSize int) {
	page, _ = strconv.Atoi(c.DefaultQuery("page", "1"))
	pageSizeStr := c.Query("pageSize")
	if pageSizeStr == "" {
		pageSizeStr = c.Query("size")
	}
	if pageSizeStr == "" {
		pageSizeStr = "20"
	}
	pageSize, _ = strconv.Atoi(pageSizeStr)
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 20
	}
	if maxPageSize > 0 && pageSize > maxPageSize {
		pageSize = maxPageSize
	}
	return
}

func EscapeLike(s string) string {
	s = strings.ReplaceAll(s, "\\", "\\\\")
	s = strings.ReplaceAll(s, "%", "\\%")
	s = strings.ReplaceAll(s, "_", "\\_")
	return s
}

// getUserIDFromContext 安全地从 gin.Context 中获取 userId，
// 避免 userID.(uint) 类型断言 panic。
func getUserIDFromContext(c *gin.Context) (uint, bool) {
	val, exists := c.Get("userId")
	if !exists {
		return 0, false
	}
	switch v := val.(type) {
	case uint:
		return v, true
	case float64:
		return uint(v), true
	case int:
		return uint(v), true
	case int64:
		return uint(v), true
	case uint64:
		return uint(v), true
	default:
		return 0, false
	}
}

func getUserID(c *gin.Context) uint {
	id, _ := getUserIDFromContext(c)
	return id
}

func parseLimit(raw string, fallback int) int {
	if strings.TrimSpace(raw) == "" {
		return fallback
	}
	value, err := strconv.Atoi(raw)
	if err != nil {
		return fallback
	}
	if value < 1 {
		return fallback
	}
	if value > 50 {
		value = 50
	}
	return value
}
