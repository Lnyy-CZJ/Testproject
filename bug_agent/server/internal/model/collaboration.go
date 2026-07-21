package model

import (
	crypto_rand "crypto/rand"
	"fmt"
	"time"

	"gorm.io/gorm"
)

// CollaborationTask 协作任务
type CollaborationTask struct {
	ID             uint     `gorm:"primaryKey" json:"id"`
	TaskCode       string   `gorm:"uniqueIndex;size:64" json:"taskCode"`
	DefectID       uint     `gorm:"index:idx_collab_defect_created,priority:1;index" json:"defectId"`
	TriggerUserID  uint     `gorm:"index" json:"triggerUserId"`
	Status         string   `gorm:"size:20;default:'pending';index:idx_collab_status_updated,priority:1" json:"status"`
	AgentTypes     string   `gorm:"size:255" json:"-"`
	AgentTypesList []string `gorm:"-" json:"agentTypes"`

	StartedAt   *time.Time `json:"startedAt"`
	CompletedAt *time.Time `json:"completedAt"`
	TimeoutAt   *time.Time `json:"timeoutAt"`

	CreatedAt time.Time `gorm:"index:idx_collab_defect_created,priority:2" json:"createdAt"`
	UpdatedAt time.Time `gorm:"index:idx_collab_status_updated,priority:2" json:"updatedAt"`

	Defect  Defect                `gorm:"foreignKey:DefectID" json:"-"`
	Reports []CollaborationReport `gorm:"foreignKey:TaskID" json:"reports,omitempty"`
}

func (c *CollaborationTask) AfterFind(tx *gorm.DB) error {
	c.AgentTypesList = splitCommaField(c.AgentTypes)
	return nil
}

// CollaborationReport 协作报告（单个AGENT的分析结果）
type CollaborationReport struct {
	ID        uint   `gorm:"primaryKey" json:"id"`
	TaskID    uint   `gorm:"index:idx_collab_report_task_status,priority:1;index" json:"taskId"`
	AgentType string `gorm:"size:50" json:"agentType"`
	ReportID  *uint  `gorm:"index" json:"reportId"`                                                                  // 关联到AnalysisReport.ID
	Status    string `gorm:"size:20;default:'pending';index:idx_collab_report_task_status,priority:2" json:"status"` // pending, analyzing, completed, failed

	StartedAt   *time.Time `json:"startedAt"`
	CompletedAt *time.Time `json:"completedAt"`
	Error       string     `gorm:"type:text" json:"error,omitempty"`

	CreatedAt time.Time `json:"createdAt"`
	UpdatedAt time.Time `json:"updatedAt"`
}

// AggregatedReport 聚合后的综合报告
type AggregatedReport struct {
	TaskID         uint               `json:"taskId"`
	TaskCode       string             `json:"taskCode"`
	Agents         []AgentResult      `json:"agents"`
	Consensus      map[string]float64 `json:"consensus"`      // 共识度统计
	Summary        string             `json:"summary"`        // 综合总结
	RiskLevel      string             `json:"riskLevel"`      // high/medium/low
	Recommendation string             `json:"recommendation"` // 最终建议
	Timestamp      time.Time          `json:"timestamp"`
}

// AgentResult 单个AGENT的分析结果
type AgentResult struct {
	AgentType string                 `json:"agentType"`
	Status    string                 `json:"status"`
	Analysis  map[string]interface{} `json:"analysis,omitempty"`
	Solution  map[string]interface{} `json:"solution,omitempty"`
	ReportID  uint                   `json:"reportId,omitempty"`
	ErrorMsg  string                 `json:"errorMsg,omitempty"`
}

// CollaborationTaskStatuses 任务状态常量
const (
	CollaborationStatusPending   = "pending"
	CollaborationStatusRunning   = "running"
	CollaborationStatusCompleted = "completed"
	CollaborationStatusFailed    = "failed"
	CollaborationStatusTimeout   = "timeout"
)

// CollaborationReportStatus 报告状态常量
const (
	CollabReportStatusPending   = "pending"
	CollabReportStatusAnalyzing = "analyzing"
	CollabReportStatusCompleted = "completed"
	CollabReportStatusFailed    = "failed"
)

// TableName 指定表名
func (CollaborationTask) TableName() string   { return "collaboration_tasks" }
func (CollaborationReport) TableName() string { return "collaboration_reports" }

// BeforeCreate 创建前生成任务编号
func (c *CollaborationTask) BeforeCreate(tx *gorm.DB) error {
	if c.TaskCode == "" {
		now := time.Now()
		c.TaskCode = GenerateCollaborationCode(now)
	}
	return nil
}

// GenerateCollaborationCode 生成协作任务编号
func GenerateCollaborationCode(t time.Time) string {
	b := make([]byte, 4)
	_, _ = crypto_rand.Read(b)
	suffix := uint32(b[0])<<24 | uint32(b[1])<<16 | uint32(b[2])<<8 | uint32(b[3])
	return fmt.Sprintf("COL-%s-%s-%08d", t.Format("200601"), t.Format("150405"), suffix%100000000)
}
