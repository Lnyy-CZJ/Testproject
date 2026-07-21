package model

import (
	"time"
)

// Role 角色模型
type Role struct {
	ID          uint      `gorm:"primaryKey" json:"id"`
	Name        string    `gorm:"uniqueIndex;size:50" json:"name"`
	DisplayName string    `gorm:"size:50" json:"displayName"`
	Description string    `gorm:"type:text" json:"description,omitempty"`
	Tier        string    `gorm:"size:20;default:project" json:"tier"`
	IsSystem    bool      `gorm:"default:false" json:"isSystem"`
	CreatedAt   time.Time `json:"createdAt"`
	UpdatedAt   time.Time `json:"updatedAt"`

	Permissions []Permission `gorm:"many2many:role_permissions;" json:"permissions,omitempty"`
}

// Permission 权限模型
type Permission struct {
	ID          uint      `gorm:"primaryKey" json:"id"`
	Code        string    `gorm:"uniqueIndex;size:100" json:"code"`
	Name        string    `gorm:"size:100" json:"name"`
	Module      string    `gorm:"size:50" json:"module"`
	Description string    `gorm:"type:text" json:"description,omitempty"`
	CreatedAt   time.Time `json:"createdAt"`
}

// RolePermission 角色-权限关联
type RolePermission struct {
	RoleID       uint      `gorm:"primaryKey" json:"roleId"`
	PermissionID uint      `gorm:"primaryKey" json:"permissionId"`
	CreatedAt    time.Time `json:"createdAt"`
}

// UserRole 用户-角色关联（支持多角色、多范围）
type UserRole struct {
	UserID     uint      `gorm:"primaryKey" json:"userId"`
	RoleID     uint      `gorm:"primaryKey" json:"roleId"`
	ScopeType  string    `gorm:"size:20;default:global" json:"scopeType"` // global, project
	ScopeID    uint      `gorm:"default:0" json:"scopeId"`                // project_id
	AssignedBy *uint     `json:"assignedBy,omitempty"`
	AssignedAt time.Time `json:"assignedAt"`

	Role Role `gorm:"foreignKey:RoleID" json:"role"`
}

// AuditLog 审计日志
type AuditLog struct {
	ID            uint      `gorm:"primaryKey" json:"id"`
	UserID        uint      `json:"userId"`
	Username      string    `gorm:"size:50" json:"username"`
	Action        string    `gorm:"size:100;index" json:"action"`
	TargetType    string    `gorm:"size:50;index:idx_audit_target,priority:2" json:"targetType"`
	TargetID      *uint     `json:"targetId,omitempty"`
	OldValue      string    `gorm:"type:json" json:"oldValue,omitempty"`
	NewValue      string    `gorm:"type:json" json:"newValue,omitempty"`
	IPAddress     string    `gorm:"size:45" json:"ipAddress,omitempty"`
	UserAgent     string    `gorm:"type:text" json:"userAgent,omitempty"`
	RequestMethod string    `gorm:"size:10" json:"requestMethod,omitempty"`
	RequestPath   string    `gorm:"size:255" json:"requestPath,omitempty"`
	StatusCode    int       `json:"statusCode"`
	ErrorMessage  string    `gorm:"type:text" json:"errorMessage,omitempty"`
	DurationMs    int       `json:"durationMs"`
	CreatedAt     time.Time `gorm:"index:idx_audit_created_at,priority:3" json:"createdAt"`
}

func (Role) TableName() string           { return "roles" }
func (Permission) TableName() string     { return "permissions" }
func (RolePermission) TableName() string { return "role_permissions" }
func (UserRole) TableName() string       { return "user_roles" }
func (AuditLog) TableName() string       { return "audit_logs" }
