package model

import (
	"fmt"
	"strings"
	"time"

	"gorm.io/gorm"
)

// User 用户
type User struct {
	ID                 uint           `json:"id" gorm:"primaryKey"`
	Username           string         `json:"username" gorm:"uniqueIndex;size:50;not null"`
	Email              string         `json:"email" gorm:"uniqueIndex;size:100;not null"`
	Password           string         `json:"-" gorm:"size:255;not null"`
	Nickname           string         `json:"nickname" gorm:"size:50"`
	Avatar             string         `json:"avatar" gorm:"size:255"`
	AgentTypes         string         `json:"-" gorm:"size:200"`
	AgentTypesList     []string       `json:"agentTypes" gorm:"-"`
	PlatformRole       string         `json:"-" gorm:"size:20;default:'member'"`
	MustChangePassword bool           `json:"mustChangePassword"`
	LastLoginAt        *time.Time     `json:"lastLoginAt"`
	InvitedBy          *uint          `json:"-"`
	CreatedAt          time.Time      `json:"createdAt"`
	UpdatedAt          time.Time      `json:"updatedAt"`
	DeletedAt          gorm.DeletedAt `json:"-" gorm:"index"`
}

func (u *User) AfterFind(tx *gorm.DB) error {
	u.AgentTypesList = splitCommaField(u.AgentTypes)
	return nil
}

func (u User) PublicUser() map[string]interface{} {
	agentTypes := u.AgentTypesList
	if agentTypes == nil {
		agentTypes = []string{}
	}
	return map[string]interface{}{
		"id": u.ID, "username": u.Username, "email": u.Email,
		"nickname": u.Nickname, "avatar": u.Avatar, "agentTypes": agentTypes,
		"platformRole":       u.PlatformRole,
		"mustChangePassword": u.MustChangePassword, "lastLoginAt": u.LastLoginAt,
		"createdAt": u.CreatedAt,
	}
}

func (User) TableName() string { return "users" }

// Project 项目
type Project struct {
	ID                 uint           `json:"id" gorm:"primaryKey"`
	Name               string         `json:"name" gorm:"size:100;not null"`
	Code               string         `json:"code" gorm:"size:20;not null;uniqueIndex"`
	Description        string         `json:"description" gorm:"type:text"`
	Status             string         `json:"status" gorm:"size:20;not null;default:'active'"`
	MemoryEnabled      bool           `json:"memoryEnabled" gorm:"default:true"`
	DefectSeq          int            `json:"-" gorm:"default:0"`
	DefectSeqYearMonth string         `json:"-" gorm:"size:6"`
	CreatedAt          time.Time      `json:"createdAt"`
	UpdatedAt          time.Time      `json:"updatedAt"`
	DeletedAt          gorm.DeletedAt `json:"-" gorm:"index"`

	Members    []ProjectMember `json:"members,omitempty" gorm:"foreignKey:ProjectID;constraint:OnDelete:CASCADE"`
	Iterations []Iteration     `json:"iterations,omitempty" gorm:"foreignKey:ProjectID;constraint:OnDelete:CASCADE"`
	Repos      []ProjectRepo   `json:"repos,omitempty" gorm:"foreignKey:ProjectID;constraint:OnDelete:CASCADE"`
}

func (Project) TableName() string { return "projects" }

// ProjectMember 项目成员
type ProjectMember struct {
	ID        uint   `json:"id" gorm:"primaryKey"`
	ProjectID uint   `json:"projectId" gorm:"uniqueIndex:proj_user;index:idx_project_members_user_project,priority:2;not null"`
	UserID    uint   `json:"userId" gorm:"uniqueIndex:proj_user;index:idx_project_members_user_project,priority:1;not null"`
	Role      string `json:"role" gorm:"size:20;not null;default:'developer'"` // project_admin, developer, tester, viewer
}

func (ProjectMember) TableName() string { return "project_members" }

// Iteration 迭代
type Iteration struct {
	ID        uint      `json:"id" gorm:"primaryKey"`
	ProjectID uint      `json:"projectId" gorm:"index;not null"`
	Name      string    `json:"name" gorm:"size:100;not null"`
	StartDate time.Time `json:"startDate"`
	EndDate   time.Time `json:"endDate"`
	Goal      string    `json:"goal" gorm:"type:text"`
	Status    string    `json:"status" gorm:"size:20;not null;default:'planning'"` // planning, active, completed
	CreatedAt time.Time `json:"createdAt"`

	IterationRepos []IterationRepo `json:"iterationRepos,omitempty" gorm:"foreignKey:IterationID;constraint:OnDelete:CASCADE"`
}

func (Iteration) TableName() string { return "iterations" }

// ProjectRepo 项目仓库（v2.0 P2-1 升级）
type ProjectRepo struct {
	ID             uint      `json:"id" gorm:"primaryKey"`
	ProjectID      uint      `json:"projectId" gorm:"index;not null"`
	Name           string    `json:"name" gorm:"size:100;not null"`
	RepoURL        string    `json:"repoUrl" gorm:"size:500;not null"`
	ExternalRepoID string    `json:"externalRepoId,omitempty" gorm:"size:100"`
	SourceType     string    `json:"sourceType" gorm:"size:20;not null;default:'custom'"` // github / gitlab / gitea / custom
	CredentialID   *uint     `json:"credentialId" gorm:"index"`                           // 关联凭证 ID（外键）
	AgentTypes     string    `json:"-" gorm:"size:200;not null;default:'backend,test'"`
	AgentTypesList []string  `json:"agentTypes" gorm:"-"`
	DefaultBranch  string    `json:"defaultBranch" gorm:"size:50;not null;default:'main'"` // 默认分支
	WebhookSecret  string    `json:"-" gorm:"size:200"`
	Description    string    `json:"description" gorm:"type:text"`
	CreatedAt      time.Time `json:"createdAt"`
	UpdatedAt      time.Time `json:"updatedAt"`
}

func (ProjectRepo) TableName() string { return "project_repos" }

func (r *ProjectRepo) AfterFind(tx *gorm.DB) error {
	r.AgentTypesList = splitCommaField(r.AgentTypes)
	return nil
}

// RepoCredential 仓库凭证（v2.0 P2-1 新增）
type RepoCredential struct {
	ID                uint       `json:"id" gorm:"primaryKey"`
	UserID            uint       `json:"userId" gorm:"index;not null"`
	Name              string     `json:"name" gorm:"size:100;not null"`
	Type              string     `json:"type" gorm:"size:20;not null"`
	Provider          string     `json:"provider" gorm:"size:20;not null"`
	Scope             string     `json:"scope" gorm:"size:20;not null;default:'personal'"`
	Status            string     `json:"status" gorm:"size:20;not null;default:'active'"`
	Content           string     `json:"-" gorm:"type:text;not null"`
	ExtraConfig       string     `json:"extraConfig,omitempty" gorm:"type:text"`
	MaskedValue       string     `json:"maskedValue" gorm:"size:200"`
	LastUsedAt        *time.Time `json:"lastUsedAt"`
	CreatedAt         time.Time  `json:"createdAt"`
	UpdatedAt         time.Time  `json:"updatedAt"`
	AllowedProjectIDs []uint     `json:"allowedProjectIds,omitempty" gorm:"-"`
}

func (RepoCredential) TableName() string { return "repo_credentials" }

// PlatformCredentialProject 平台凭证-项目授权关系
type PlatformCredentialProject struct {
	ID           uint      `json:"id" gorm:"primaryKey"`
	CredentialID uint      `json:"credentialId" gorm:"uniqueIndex:uk_platform_credential_project;index;not null"`
	ProjectID    uint      `json:"projectId" gorm:"uniqueIndex:uk_platform_credential_project;index;not null"`
	CreatedAt    time.Time `json:"createdAt"`
}

func (PlatformCredentialProject) TableName() string { return "platform_credential_projects" }

// NotificationPreference 通知偏好（v2.0 P3-2 新增）
type NotificationPreference struct {
	ID           uint      `json:"id" gorm:"primaryKey"`
	UserID       uint      `json:"userId" gorm:"uniqueIndex:user_pref;not null"`
	Category     string    `json:"category" gorm:"size:50;uniqueIndex:user_pref;not null"` // defect_assigned / defect_status_change / defect_mention / ...
	Channels     string    `json:"-" gorm:"size:200;not null"`
	ChannelsList []string  `json:"channels" gorm:"-"` // in_app,email,webhook
	CreatedAt    time.Time `json:"createdAt"`
	UpdatedAt    time.Time `json:"updatedAt"`
}

func (NotificationPreference) TableName() string { return "notification_preferences" }

func (n *NotificationPreference) AfterFind(tx *gorm.DB) error {
	n.ChannelsList = splitCommaField(n.Channels)
	return nil
}

// UserWebhookSetting 个人通知 Webhook
type UserWebhookSetting struct {
	ID        uint      `json:"id" gorm:"primaryKey"`
	UserID    uint      `json:"userId" gorm:"uniqueIndex;not null"`
	URL       string    `json:"url" gorm:"size:500"`
	Secret    string    `json:"-" gorm:"size:500"`
	HasSecret bool      `json:"hasSecret" gorm:"-"`
	Enabled   bool      `json:"enabled"`
	CreatedAt time.Time `json:"createdAt"`
	UpdatedAt time.Time `json:"updatedAt"`
}

func (UserWebhookSetting) TableName() string { return "user_webhook_settings" }

// ProjectWebhook 项目通知 Webhook
type ProjectWebhook struct {
	ID        uint      `json:"id" gorm:"primaryKey"`
	ProjectID uint      `json:"projectId" gorm:"index;not null"`
	Name      string    `json:"name" gorm:"size:100;not null"`
	URL       string    `json:"url" gorm:"size:500;not null"`
	Secret    string    `json:"-" gorm:"size:255"`
	HasSecret bool      `json:"hasSecret" gorm:"-"`
	Enabled   bool      `json:"enabled"`
	CreatedAt time.Time `json:"createdAt"`
	UpdatedAt time.Time `json:"updatedAt"`
}

func (ProjectWebhook) TableName() string { return "project_webhooks" }

// ProjectNotificationPolicy 项目通知上限策略
type ProjectNotificationPolicy struct {
	ID           uint            `json:"id" gorm:"primaryKey"`
	ProjectID    uint            `json:"projectId" gorm:"uniqueIndex:uk_project_notification_policy;index;not null"`
	Category     string          `json:"category" gorm:"size:50;uniqueIndex:uk_project_notification_policy;not null"`
	InAppEnabled bool            `json:"inAppEnabled"`
	EmailEnabled bool            `json:"emailEnabled"`
	WebhookID    *uint           `json:"webhookId,omitempty" gorm:"index"`
	CreatedAt    time.Time       `json:"createdAt"`
	UpdatedAt    time.Time       `json:"updatedAt"`
	Webhook      *ProjectWebhook `json:"webhook,omitempty" gorm:"foreignKey:WebhookID"`
}

func (ProjectNotificationPolicy) TableName() string { return "project_notification_policies" }

// PlatformSetting 平台级配置
type PlatformSetting struct {
	ID         uint      `json:"id" gorm:"primaryKey"`
	SettingKey string    `json:"settingKey" gorm:"size:100;uniqueIndex;not null"`
	Value      string    `json:"value" gorm:"type:text;not null"`
	UpdatedBy  uint      `json:"updatedBy" gorm:"index"`
	CreatedAt  time.Time `json:"createdAt"`
	UpdatedAt  time.Time `json:"updatedAt"`
}

func (PlatformSetting) TableName() string { return "platform_settings" }

// InviteCode 邀请码（v2.0 P5 新增）
type InviteCode struct {
	ID        uint       `json:"id" gorm:"primaryKey"`
	Code      string     `json:"code" gorm:"uniqueIndex;size:64;not null"`
	InviterID uint       `json:"inviterId" gorm:"index;not null"`
	MaxUses   int        `json:"maxUses"` // 0=无限
	UsedCount int        `json:"usedCount" gorm:"default:0"`
	ExpiresAt *time.Time `json:"expiresAt"` // nil=永不过期
	CreatedAt time.Time  `json:"createdAt"`
}

func (InviteCode) TableName() string { return "invite_codes" }

// ProjectAIConfig 项目AI配置（v1.1新增）
type ProjectAIConfig struct {
	ID                  uint      `json:"id" gorm:"primaryKey"`
	ProjectID           uint      `json:"projectId" gorm:"index;not null"`
	Provider            string    `json:"provider" gorm:"size:50;not null"`
	ModelName           string    `json:"modelName" gorm:"size:100;not null"`
	APIKey              string    `json:"-" gorm:"type:text"`
	MaskedAPIKey        string    `json:"apiKey" gorm:"-"`
	APIEndpoint         string    `json:"apiEndpoint" gorm:"size:500"`
	FunctionCallingMode string    `json:"functionCallingMode" gorm:"size:20;default:'auto'"` // auto/enabled/disabled
	IsDefault           bool      `json:"isDefault" gorm:"default:false"`
	CreatedAt           time.Time `json:"createdAt"`
	UpdatedAt           time.Time `json:"updatedAt"`
}

func (ProjectAIConfig) TableName() string { return "project_ai_configs" }

// IterationRepo 迭代-仓库关联（v1.1改造：关联项目仓库ID）
type IterationRepo struct {
	ID          uint      `json:"id" gorm:"primaryKey"`
	IterationID uint      `json:"iterationId" gorm:"uniqueIndex:iter_repo;not null"`
	RepoID      *uint     `json:"repoId" gorm:"uniqueIndex:iter_repo"`
	Branch      string    `json:"branch" gorm:"size:200"`
	CreatedAt   time.Time `json:"createdAt"`

	Repo *ProjectRepo `json:"repo,omitempty" gorm:"foreignKey:RepoID"`
}

func (IterationRepo) TableName() string { return "iteration_repos" }

// Severity levels
const (
	SeverityFatal   = "fatal"
	SeverityMajor   = "major"
	SeverityNormal  = "normal"
	SeverityMinor   = "minor"
	SeveritySuggest = "suggest"
)

// Priority levels
const (
	PriorityP0 = "P0"
	PriorityP1 = "P1"
	PriorityP2 = "P2"
	PriorityP3 = "P3"
	PriorityP4 = "P4"
)

// Defect types
const (
	DefectTypeFunctional    = "functional"
	DefectTypeUI            = "ui"
	DefectTypePerformance   = "performance"
	DefectTypeSecurity      = "security"
	DefectTypeCompatibility = "compatibility"
	DefectTypeOther         = "other"
)

// Defect statuses
const (
	DefectStatusNew             = "new"
	DefectStatusPendingAssign   = "pending_assign"
	DefectStatusPendingAnalysis = "pending_analysis"
	DefectStatusAnalyzing       = "analyzing"
	DefectStatusPendingFix      = "pending_fix"
	DefectStatusFixing          = "fixing"
	DefectStatusPendingVerify   = "pending_verify"
	DefectStatusFixed           = "fixed"
	DefectStatusCompleted       = "completed"
	DefectStatusRejected        = "rejected"
	DefectStatusSuspended       = "suspended"
)

// Defect 缺陷
type Defect struct {
	ID          uint           `json:"id" gorm:"primaryKey"`
	Code        string         `json:"code" gorm:"uniqueIndex;size:50;not null"`
	IterationID uint           `json:"iterationId" gorm:"index;index:idx_defects_iteration_status_created,priority:1;index:idx_defects_iteration_created,priority:1;not null"`
	Title       string         `json:"title" gorm:"size:200;not null"`
	Description string         `json:"description" gorm:"type:text"`
	Severity    string         `json:"severity" gorm:"size:20;not null;default:'normal'"`
	Priority    string         `json:"priority" gorm:"size:10;not null;default:'P2'"`
	Type        string         `json:"type" gorm:"size:30;not null;default:'functional'"`
	Status      string         `json:"status" gorm:"size:20;not null;default:'new';index;index:idx_defects_iteration_status_created,priority:2"`
	AssigneeID  *uint          `json:"assigneeId" gorm:"index"`
	ReporterID  uint           `json:"reporterId" gorm:"index;not null"`
	Tags        string         `json:"-" gorm:"size:500"`
	TagsList    []string       `json:"tags" gorm:"-"`
	CreatedAt   time.Time      `json:"createdAt" gorm:"index:idx_defects_iteration_status_created,priority:3;index:idx_defects_iteration_created,priority:2"`
	UpdatedAt   time.Time      `json:"updatedAt"`
	DeletedAt   gorm.DeletedAt `json:"-" gorm:"index"`

	Iteration       Iteration        `json:"iteration,omitempty" gorm:"foreignKey:IterationID"`
	Assignee        *User            `json:"assignee,omitempty" gorm:"foreignKey:AssigneeID"`
	Reporter        User             `json:"reporter,omitempty" gorm:"foreignKey:ReporterID"`
	Comments        []Comment        `json:"comments,omitempty" gorm:"foreignKey:DefectID;constraint:OnDelete:CASCADE"`
	FixTasks        []FixTask        `json:"fixTasks,omitempty" gorm:"foreignKey:DefectID;constraint:OnDelete:CASCADE"`
	Attachments     []Attachment     `json:"attachments,omitempty" gorm:"foreignKey:DefectID;constraint:OnDelete:CASCADE"`
	AnalysisReports []AnalysisReport `json:"analysisReports,omitempty" gorm:"foreignKey:DefectID;constraint:OnDelete:CASCADE"`
	StatusChanges   []StatusChange   `json:"statusChanges,omitempty" gorm:"foreignKey:DefectID;constraint:OnDelete:CASCADE"`
}

func (d *Defect) AfterFind(tx *gorm.DB) error {
	d.TagsList = splitCommaField(d.Tags)
	return nil
}

func (Defect) TableName() string { return "defects" }

// Attachment 附件
type Attachment struct {
	ID        uint      `json:"id" gorm:"primaryKey"`
	DefectID  uint      `json:"defectId" gorm:"index;not null"`
	FileName  string    `json:"fileName" gorm:"size:255;not null"`
	FileURL   string    `json:"fileUrl" gorm:"size:500;not null"`
	FileSize  int64     `json:"fileSize"`
	FileType  string    `json:"fileType" gorm:"size:50"`
	CreatedAt time.Time `json:"createdAt"`
}

func (Attachment) TableName() string { return "attachments" }

// FixTask statuses
const (
	FixTaskStatusPending               = "pending"
	FixTaskStatusPlanning              = "planning"
	FixTaskStatusExecuting             = "executing"
	FixTaskStatusTesting               = "testing"
	FixTaskStatusCompleted             = "completed"
	FixTaskStatusNoChanges             = "no_changes"
	FixTaskStatusCompletedWithWarnings = "completed_warning"
	FixTaskStatusPartiallyFailed       = "partial_failed"
	FixTaskStatusFailed                = "failed"
	FixTaskStatusCancelled             = "cancelled"
)

// FixTaskGroup 一次缺陷修复的聚合任务，下面可以包含多个仓库/AGENT执行单元。
type FixTaskGroup struct {
	ID           uint       `json:"id" gorm:"primaryKey"`
	TaskCode     string     `json:"taskCode" gorm:"column:task_code;uniqueIndex;size:50;not null"`
	DefectID     uint       `json:"defectId" gorm:"column:defect_id;index;not null"`
	Status       string     `json:"status" gorm:"column:status;size:40;not null;default:'planning'"`
	TargetBranch string     `json:"targetBranch" gorm:"column:target_branch;size:100"`
	Summary      string     `json:"summary" gorm:"column:summary;type:text"`
	Result       string     `json:"result" gorm:"column:result;type:text"`
	CreatedBy    uint       `json:"createdBy" gorm:"column:created_by;index"`
	StartedAt    *time.Time `json:"startedAt" gorm:"column:started_at"`
	CompletedAt  *time.Time `json:"completedAt" gorm:"column:completed_at"`
	CreatedAt    time.Time  `json:"createdAt" gorm:"column:created_at"`

	Defect Defect    `json:"defect,omitempty" gorm:"foreignKey:DefectID"`
	Units  []FixTask `json:"units,omitempty" gorm:"foreignKey:GroupID"`
}

func (FixTaskGroup) TableName() string { return "fix_task_groups" }

// FixTask 修复任务
type FixTask struct {
	ID                      uint       `json:"id" gorm:"primaryKey"`
	GroupID                 *uint      `json:"groupId" gorm:"column:group_id;index"`
	TaskCode                string     `json:"taskCode" gorm:"column:task_code;uniqueIndex;size:50;not null"`
	DefectID                uint       `json:"defectId" gorm:"column:defect_id;index;not null"`
	AnalysisReportID        *uint      `json:"analysisReportId" gorm:"column:analysis_report_id;index"`
	AgentType               string     `json:"agentType" gorm:"column:agent_type;size:20;not null"`
	ProjectRepoID           *uint      `json:"projectRepoId" gorm:"column:project_repo_id;index"`
	Status                  string     `json:"status" gorm:"column:status;size:40;not null;default:'pending'"`
	TargetBranch            string     `json:"targetBranch" gorm:"column:target_branch;size:100"`
	FixBranch               string     `json:"fixBranch" gorm:"column:fix_branch;size:100"`
	AIRiskSummary           string     `json:"aiRiskSummary" gorm:"column:ai_risk_summary;type:text"`
	AIValidationSuggestions string     `json:"aiValidationSuggestions" gorm:"column:ai_validation_suggestions;type:text"`
	Plan                    string     `json:"plan" gorm:"column:plan;type:text"`
	Result                  string     `json:"result" gorm:"column:result;type:text"`
	PRURL                   string     `json:"prUrl" gorm:"column:pr_url;size:500"`
	PRNumber                string     `json:"prNumber" gorm:"column:pr_number;size:50"`
	Source                  string     `json:"source" gorm:"column:source;size:20;not null;default:'auto'"`
	ManualDescription       string     `json:"manualDescription" gorm:"column:manual_description;type:text"`
	PRStatus                string     `json:"prStatus" gorm:"column:pr_status;size:20;not null;default:'open'"`
	RepoPath                string     `json:"repoPath" gorm:"column:repo_path;size:200;index:idx_fix_tasks_pr_lookup"`
	DefectRepoID            *uint      `json:"defectRepoId" gorm:"column:defect_repo_id;index"`
	CreatedAt               time.Time  `json:"createdAt" gorm:"column:created_at"`
	CompletedAt             *time.Time `json:"completedAt" gorm:"column:completed_at"`

	Defect      Defect      `json:"defect,omitempty" gorm:"foreignKey:DefectID"`
	ProjectRepo ProjectRepo `json:"projectRepo,omitempty" gorm:"foreignKey:ProjectRepoID"`
}

func (FixTask) TableName() string { return "fix_tasks" }

// AnalysisReport statuses
const (
	AnalysisStatusPending    = "pending"
	AnalysisStatusCompleted  = "completed"
	AnalysisStatusFailed     = "failed"
	AnalysisStatusSuperseded = "superseded"
)

// AnalysisReport AGENT分析报告
type AnalysisReport struct {
	ID                    uint      `json:"id" gorm:"primaryKey"`
	ReportCode            string    `json:"reportCode" gorm:"uniqueIndex;size:50;not null"`
	DefectID              uint      `json:"defectId" gorm:"index;not null"`
	AgentType             string    `json:"agentType" gorm:"size:20;not null"`
	Status                string    `json:"status" gorm:"size:20;not null;default:'pending'"`
	ErrorMessage          string    `json:"errorMessage" gorm:"type:text"`
	RiskSummary           string    `json:"riskSummary" gorm:"type:text"`
	ValidationSuggestions string    `json:"validationSuggestions" gorm:"type:text"`
	Analysis              string    `json:"analysis" gorm:"type:text"`
	Solution              string    `json:"solution" gorm:"type:text"`
	CreatedAt             time.Time `json:"createdAt"`

	Defect Defect `json:"defect,omitempty" gorm:"foreignKey:DefectID"`
}

func (AnalysisReport) TableName() string { return "analysis_reports" }

type AITokenUsage struct {
	ID               uint      `gorm:"primaryKey" json:"id"`
	ProjectID        uint      `gorm:"index:idx_project_type;not null" json:"projectId"`
	IterationID      *uint     `gorm:"index:idx_iteration_type" json:"iterationId"`
	DefectID         uint      `gorm:"index:idx_defect_type;not null" json:"defectId"`
	ConsumptionType  string    `gorm:"size:20;not null;index:idx_project_type;index:idx_iteration_type;index:idx_defect_type" json:"consumptionType"`
	SourceID         uint      `gorm:"index;not null" json:"sourceId"`
	AttemptIndex     int       `gorm:"default:0" json:"attemptIndex"`
	IsFinalAttempt   bool      `gorm:"default:false" json:"isFinalAttempt"`
	Provider         string    `gorm:"size:50" json:"provider"`
	ModelName        string    `gorm:"size:100" json:"modelName"`
	PromptTokens     int       `json:"promptTokens"`
	CompletionTokens int       `json:"completionTokens"`
	TotalTokens      int       `json:"totalTokens"`
	EstimatedCostUSD float64   `json:"estimatedCostUsd"`
	DurationMs       int64     `json:"durationMs"`
	CreatedAt        time.Time `gorm:"index" json:"createdAt"`
}

func (a *AITokenUsage) AfterFind(tx *gorm.DB) error {
	return nil
}

func (AITokenUsage) TableName() string { return "ai_token_usages" }

type DefectRepo struct {
	ID        uint       `gorm:"primaryKey" json:"id"`
	DefectID  uint       `gorm:"index;not null" json:"defectId"`
	ProjectID uint       `gorm:"index;not null" json:"projectId"`
	RepoURL   string     `gorm:"size:500;not null" json:"repoUrl"`
	Branch    string     `gorm:"size:100" json:"branch"`
	LocalPath string     `gorm:"size:500;not null" json:"localPath"`
	Status    string     `gorm:"size:20;not null;default:'active'" json:"status"`
	FixTaskID *uint      `gorm:"index" json:"fixTaskId"`
	CreatedAt time.Time  `json:"createdAt"`
	DeletedAt *time.Time `json:"deletedAt"`
}

func (DefectRepo) TableName() string { return "defect_repos" }

type ProjectMCPServer struct {
	ID          uint      `gorm:"primaryKey" json:"id"`
	ProjectID   uint      `gorm:"index;not null" json:"projectId"`
	Name        string    `gorm:"size:100;not null" json:"name"`
	Command     string    `gorm:"size:500;not null" json:"command"`
	Args        string    `gorm:"type:text" json:"args"`
	Description string    `gorm:"type:text" json:"description"`
	Enabled     bool      `gorm:"default:true" json:"enabled"`
	CreatedBy   uint      `json:"createdBy"`
	CreatedAt   time.Time `json:"createdAt"`
	UpdatedAt   time.Time `json:"updatedAt"`
}

func (ProjectMCPServer) TableName() string { return "project_mcp_servers" }

type ProjectAgentSkill struct {
	ID               uint      `gorm:"primaryKey" json:"id"`
	ProjectID        uint      `gorm:"index;not null" json:"projectId"`
	Name             string    `gorm:"size:100;not null" json:"name"`
	AgentType        string    `gorm:"size:20;not null" json:"agentType"`
	Instruction      string    `gorm:"type:text" json:"instruction"`
	Tools            string    `gorm:"type:text" json:"tools"`
	MCPServerIDs     string    `gorm:"type:text;column:mcp_server_ids" json:"mcpServerIds"`
	MemoryCategories string    `gorm:"type:text" json:"memoryCategories"`
	Enabled          bool      `gorm:"default:true" json:"enabled"`
	IsDefault        bool      `gorm:"default:false" json:"isDefault"`
	CreatedBy        uint      `json:"createdBy"`
	CreatedAt        time.Time `json:"createdAt"`
	UpdatedAt        time.Time `json:"updatedAt"`
}

func (ProjectAgentSkill) TableName() string { return "project_agent_skills" }

type RetrieverPlugin struct {
	ID          uint      `gorm:"primaryKey" json:"id"`
	ProjectID   uint      `gorm:"uniqueIndex:idx_project_name;index;not null" json:"projectId"`
	Name        string    `gorm:"size:100;uniqueIndex:idx_project_name;not null" json:"name"`
	DisplayName string    `gorm:"size:200;not null" json:"displayName"`
	Description string    `gorm:"type:text" json:"description"`
	Config      string    `gorm:"type:text" json:"config"`
	Enabled     bool      `gorm:"default:true" json:"enabled"`
	SortOrder   int       `gorm:"default:0" json:"sortOrder"`
	IsBuiltIn   bool      `gorm:"default:false" json:"isBuiltIn"`
	CreatedBy   uint      `json:"createdBy"`
	CreatedAt   time.Time `json:"createdAt"`
	UpdatedAt   time.Time `json:"updatedAt"`
}

func (RetrieverPlugin) TableName() string { return "retriever_plugins" }

// Comment 评论
type Comment struct {
	ID             uint      `json:"id" gorm:"primaryKey"`
	DefectID       uint      `json:"defectId" gorm:"index;not null"`
	UserID         uint      `json:"userId" gorm:"index;not null"`
	Content        string    `json:"content" gorm:"type:text;not null"`
	AgentType      string    `json:"agentType" gorm:"size:20"`
	IsAgentMessage bool      `json:"isAgentMessage" gorm:"default:false"`
	CreatedAt      time.Time `json:"createdAt"`

	// Relations
	User   User   `json:"user,omitempty" gorm:"foreignKey:UserID"`
	Defect Defect `json:"defect,omitempty" gorm:"foreignKey:DefectID"`
}

func (Comment) TableName() string { return "comments" }

const (
	MemoryCategoryArchitecture     = "architecture"
	MemoryCategoryConvention       = "convention"
	MemoryCategoryCommonError      = "common_error"
	MemoryCategoryFixStrategy      = "fix_strategy"
	MemoryCategoryAvoidStrategy    = "avoid_strategy"
	MemoryCategoryIterationContext = "iteration_context"

	MemorySourceAutoExtract = "auto_extract"
	MemorySourceManual      = "manual"
	MemorySourcePRRejection = "pr_rejection"
)

type AgentMemory struct {
	ID             uint      `gorm:"primaryKey" json:"id"`
	ProjectID      uint      `gorm:"index:idx_memories_lookup;index:idx_memories_context;not null" json:"projectId"`
	IterationID    *uint     `gorm:"index:idx_memories_lookup;index:idx_memories_context" json:"iterationId"`
	Category       string    `gorm:"size:30;index:idx_memories_lookup;not null" json:"category"`
	Content        string    `gorm:"type:text;not null" json:"content"`
	Source         string    `gorm:"size:20;not null" json:"source"`
	SourceRefID    *uint     `json:"sourceRefId"`
	RelevanceScore float64   `gorm:"default:0" json:"relevanceScore"`
	Enabled        bool      `gorm:"default:true;index:idx_memories_context" json:"enabled"`
	CreatedBy      uint      `json:"createdBy"`
	CreatedAt      time.Time `json:"createdAt"`
	UpdatedAt      time.Time `json:"updatedAt"`
}

func (AgentMemory) TableName() string { return "agent_memories" }

type PRRejection struct {
	ID           uint      `gorm:"primaryKey" json:"id"`
	FixTaskID    uint      `gorm:"index;not null" json:"fixTaskId"`
	PRNumber     string    `gorm:"size:50" json:"prNumber"`
	PRURL        string    `gorm:"size:500" json:"prUrl"`
	RejectedBy   string    `gorm:"size:100" json:"rejectedBy"`
	RejectReason string    `gorm:"type:text" json:"rejectReason"`
	VCSProvider  string    `gorm:"size:20" json:"vcsProvider"`
	CreatedAt    time.Time `json:"createdAt"`
}

func (PRRejection) TableName() string { return "pr_rejections" }

func splitCommaField(s string) []string {
	if strings.TrimSpace(s) == "" {
		return []string{}
	}
	parts := strings.Split(s, ",")
	result := make([]string, 0, len(parts))
	for _, p := range parts {
		if v := strings.TrimSpace(p); v != "" {
			result = append(result, v)
		}
	}
	return result
}

// DefaultBranch 默认分支名
const DefaultBranch = "main"

// ResolveBranch 解析分支名，为空时返回默认分支
func ResolveBranch(branch string) string {
	if branch == "" {
		return DefaultBranch
	}
	return branch
}

// GenerateDefectCode 生成缺陷编号（递增序号）
// 格式: BUG-{项目代码}-{年月}-{序号}，例如 BUG-BUGAGENT-202603-001
func GenerateDefectCode(db *gorm.DB, project *Project) (string, error) {
	now := time.Now()
	yearMonth := now.Format("200601")

	var proj Project
	if err := db.Set("gorm:query_option", "FOR UPDATE").First(&proj, project.ID).Error; err != nil {
		return "", err
	}

	var seq int64
	if proj.DefectSeqYearMonth != yearMonth {
		if err := db.Model(&Project{}).Where("id = ?", project.ID).
			Updates(map[string]interface{}{"defect_seq": 1, "defect_seq_year_month": yearMonth}).Error; err != nil {
			return "", err
		}
		seq = 1
	} else {
		newSeq := proj.DefectSeq + 1
		if err := db.Model(&Project{}).Where("id = ?", project.ID).
			Update("defect_seq", newSeq).Error; err != nil {
			return "", err
		}
		seq = int64(newSeq)
	}

	return fmt.Sprintf("BUG-%s-%s-%03d", strings.ToUpper(project.Code), yearMonth, seq), nil
}
