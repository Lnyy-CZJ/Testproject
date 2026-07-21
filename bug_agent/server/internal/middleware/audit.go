package middleware

import (
	"bug-agent/internal/asyncx"
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/pkg/logger"
	"encoding/json"
	"fmt"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

var auditSvc *service.AuditService

// InitAudit initializes audit service
func InitAudit(db *gorm.DB) {
	auditSvc = service.NewAuditService(db)
}

// AuditMiddleware creates middleware that logs all requests to audit table
func AuditMiddleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		if auditSvc == nil {
			c.Next()
			return
		}

		start := time.Now()

		c.Next()

		duration := time.Since(start)
		userID := GetUserID(c)
		username, _ := c.Get("username")

		entry := model.AuditLog{
			UserID:        userID,
			Action:        c.Request.Method + " " + c.FullPath(),
			RequestMethod: c.Request.Method,
			RequestPath:   c.Request.URL.Path,
			StatusCode:    c.Writer.Status(),
			DurationMs:    int(duration.Milliseconds()),
			IPAddress:     c.ClientIP(),
			UserAgent:     c.Request.UserAgent(),
			OldValue:      "null",
			NewValue:      "null",
			CreatedAt:     time.Now(),
		}

		if username != nil {
			if u, ok := username.(string); ok {
				entry.Username = u
			}
		}

		if c.Writer.Status() >= 400 {
			errMsg, _ := c.Get("error")
			if errMsg != nil {
				if s, ok := errMsg.(string); ok {
					entry.ErrorMessage = s
				} else {
					entry.ErrorMessage = fmt.Sprintf("%v", errMsg)
				}
			}
		}

		asyncx.Go(func() {
			if err := auditSvc.LogAction(entry); err != nil {
				logger.Errorf("[Audit] Failed to log action: %v", err)
			}
		})
	}
}

// AuditAction is a helper to manually log specific business actions
func AuditAction(c *gin.Context, action string, targetType string, targetID uint, oldValue interface{}, newValue interface{}) {
	if auditSvc == nil {
		return
	}

	userID := GetUserID(c)
	usernameVal, _ := c.Get("username")
	username := ""
	if usernameVal != nil {
		if u, ok := usernameVal.(string); ok {
			username = u
		}
	}

	entry := model.AuditLog{
		UserID:     userID,
		Username:   username,
		Action:     action,
		TargetType: targetType,
		TargetID:   &targetID,
		IPAddress:  c.ClientIP(),
		CreatedAt:  time.Now(),
	}

	if oldValue != nil {
		data, err := json.Marshal(oldValue)
		if err != nil {
			entry.OldValue = fmt.Sprintf("<marshal error: %v>", err)
		} else {
			entry.OldValue = string(data)
		}
	}
	if newValue != nil {
		data, err := json.Marshal(newValue)
		if err != nil {
			entry.NewValue = fmt.Sprintf("<marshal error: %v>", err)
		} else {
			entry.NewValue = string(data)
		}
	}

	asyncx.Go(func() {
		if err := auditSvc.LogAction(entry); err != nil {
			logger.Errorf("[Audit] Failed to log action: %v", err)
		}
	})
}
