package model

import "time"

const (
	ConnectorTypeWebhook  = "webhook"
	ConnectorTypeBugly    = "bugly"
	ConnectorTypeDingTalk = "dingtalk"
	ConnectorTypeFeishu   = "feishu"
	ConnectorTypeAliyun   = "aliyun_log"
	IssueSourceManualChat = "manual_chat"
	IssueSourceManualForm = "manual_form"

	ConnectorStatusActive   = "active"
	ConnectorStatusInactive = "inactive"

	SyncStatusSuccess = "success"
	SyncStatusFailed  = "failed"
	SyncStatusPending = "pending"

	IssueTriageStatusNew       = "new"
	IssueTriageStatusTriaging  = "triaging"
	IssueTriageStatusClustered = "clustered"
	IssueTriageStatusConverted = "converted"
	IssueTriageStatusIgnored   = "ignored"
	IssueTriageStatusClosed    = "closed"

	RegressionItemStatusDraft    = "draft"
	RegressionItemStatusActive   = "active"
	RegressionItemStatusVerified = "verified"
	RegressionItemStatusArchived = "archived"
)

type IntegrationConnector struct {
	ID              uint       `json:"id" gorm:"primaryKey"`
	ProjectID       uint       `json:"projectId" gorm:"index;not null"`
	Name            string     `json:"name" gorm:"size:100;not null"`
	Type            string     `json:"type" gorm:"size:30;index;not null"`
	Status          string     `json:"status" gorm:"size:20;index;not null;default:'active'"`
	InboundToken    string     `json:"inboundToken" gorm:"size:120;uniqueIndex;not null"`
	ConfigEncrypted string     `json:"-" gorm:"type:text"`
	LastSyncAt      *time.Time `json:"lastSyncAt"`
	LastSyncStatus  string     `json:"lastSyncStatus" gorm:"size:20"`
	LastError       string     `json:"lastError" gorm:"type:text"`
	CreatedBy       uint       `json:"createdBy" gorm:"index;not null"`
	CreatedAt       time.Time  `json:"createdAt"`
	UpdatedAt       time.Time  `json:"updatedAt"`

	Project     Project                 `json:"project,omitempty" gorm:"foreignKey:ProjectID"`
	Creator     User                    `json:"creator,omitempty" gorm:"foreignKey:CreatedBy"`
	SyncRecords []IntegrationSyncRecord `json:"syncRecords,omitempty" gorm:"foreignKey:ConnectorID;constraint:OnDelete:CASCADE"`
	Signals     []IssueSignal           `json:"signals,omitempty" gorm:"foreignKey:ConnectorID;constraint:OnDelete:CASCADE"`
}

func (IntegrationConnector) TableName() string { return "integration_connectors" }

type IntegrationSyncRecord struct {
	ID             uint       `json:"id" gorm:"primaryKey"`
	ConnectorID    uint       `json:"connectorId" gorm:"index;not null"`
	TriggerType    string     `json:"triggerType" gorm:"size:30;not null"`
	Status         string     `json:"status" gorm:"size:20;index;not null"`
	RequestSummary string     `json:"requestSummary" gorm:"type:text"`
	ImportedCount  int        `json:"importedCount"`
	ClusteredCount int        `json:"clusteredCount"`
	ErrorKind      string     `json:"errorKind" gorm:"size:40;index"`
	Retryable      bool       `json:"retryable"`
	ErrorMessage   string     `json:"errorMessage" gorm:"type:text"`
	StartedAt      time.Time  `json:"startedAt" gorm:"index"`
	FinishedAt     *time.Time `json:"finishedAt"`
	CreatedAt      time.Time  `json:"createdAt"`

	Connector IntegrationConnector `json:"connector,omitempty" gorm:"foreignKey:ConnectorID"`
}

func (IntegrationSyncRecord) TableName() string { return "integration_sync_records" }

type IssueSignal struct {
	ID                uint      `json:"id" gorm:"primaryKey"`
	ProjectID         uint      `json:"projectId" gorm:"index;not null"`
	ConnectorID       *uint     `json:"connectorId" gorm:"index"`
	ClusterID         *uint     `json:"clusterId" gorm:"index"`
	SourceType        string    `json:"sourceType" gorm:"size:30;index;not null"`
	SourceEventID     string    `json:"sourceEventId" gorm:"size:120;index:uk_signal_source_event,priority:2;not null"`
	SourceInstance    string    `json:"sourceInstance" gorm:"size:120;index:uk_signal_source_event,priority:1;not null"`
	Title             string    `json:"title" gorm:"size:200;not null"`
	Description       string    `json:"description" gorm:"type:text"`
	RawSeverity       string    `json:"rawSeverity" gorm:"size:30"`
	RawPriority       string    `json:"rawPriority" gorm:"size:30"`
	AppVersion        string    `json:"appVersion" gorm:"size:50;index"`
	BuildNumber       string    `json:"buildNumber" gorm:"size:50"`
	Platform          string    `json:"platform" gorm:"size:30;index"`
	DeviceInfoJSON    string    `json:"deviceInfoJson" gorm:"type:text"`
	StackTrace        string    `json:"stackTrace" gorm:"type:text"`
	LogExcerpt        string    `json:"logExcerpt" gorm:"type:text"`
	Fingerprint       string    `json:"fingerprint" gorm:"size:255;index"`
	OccurrenceCount   int       `json:"occurrenceCount" gorm:"not null;default:1"`
	AffectedUserCount int       `json:"affectedUserCount" gorm:"not null;default:1"`
	FirstSeenAt       time.Time `json:"firstSeenAt" gorm:"index;not null"`
	LastSeenAt        time.Time `json:"lastSeenAt" gorm:"index;not null"`
	RawPayloadJSON    string    `json:"rawPayloadJson" gorm:"type:text;not null"`
	TriageStatus      string    `json:"triageStatus" gorm:"size:20;index;not null;default:'new'"`
	LinkedDefectID    *uint     `json:"linkedDefectId" gorm:"index"`
	CreatedAt         time.Time `json:"createdAt"`
	UpdatedAt         time.Time `json:"updatedAt"`

	Project   Project               `json:"project,omitempty" gorm:"foreignKey:ProjectID"`
	Connector *IntegrationConnector `json:"connector,omitempty" gorm:"foreignKey:ConnectorID"`
	Cluster   *IssueCluster         `json:"cluster,omitempty" gorm:"foreignKey:ClusterID"`
	Defect    *Defect               `json:"defect,omitempty" gorm:"foreignKey:LinkedDefectID"`
}

func (IssueSignal) TableName() string { return "issue_signals" }

type IssueCluster struct {
	ID                uint      `json:"id" gorm:"primaryKey"`
	ProjectID         uint      `json:"projectId" gorm:"index:uk_issue_cluster_key,priority:1;index;not null"`
	ClusterKey        string    `json:"clusterKey" gorm:"size:255;index:uk_issue_cluster_key,priority:2;not null"`
	Title             string    `json:"title" gorm:"size:200;not null"`
	Summary           string    `json:"summary" gorm:"type:text"`
	Status            string    `json:"status" gorm:"size:20;index;not null;default:'new'"`
	SignalCount       int       `json:"signalCount" gorm:"not null;default:0"`
	AffectedUserCount int       `json:"affectedUserCount" gorm:"not null;default:0"`
	Severity          string    `json:"severity" gorm:"size:20"`
	Priority          string    `json:"priority" gorm:"size:20"`
	OwnerUserID       *uint     `json:"ownerUserId" gorm:"index"`
	ModuleID          *uint     `json:"moduleId" gorm:"index"`
	FirstSeenAt       time.Time `json:"firstSeenAt" gorm:"index;not null"`
	LastSeenAt        time.Time `json:"lastSeenAt" gorm:"index;not null"`
	LinkedDefectID    *uint     `json:"linkedDefectId" gorm:"index"`
	CreatedAt         time.Time `json:"createdAt"`
	UpdatedAt         time.Time `json:"updatedAt"`

	Project Project        `json:"project,omitempty" gorm:"foreignKey:ProjectID"`
	Owner   *User          `json:"owner,omitempty" gorm:"foreignKey:OwnerUserID"`
	Module  *ProjectModule `json:"module,omitempty" gorm:"foreignKey:ModuleID"`
	Defect  *Defect        `json:"defect,omitempty" gorm:"foreignKey:LinkedDefectID"`
}

func (IssueCluster) TableName() string { return "issue_clusters" }

type IssueTriageRecord struct {
	ID         uint      `json:"id" gorm:"primaryKey"`
	SignalID   *uint     `json:"signalId" gorm:"index"`
	ClusterID  *uint     `json:"clusterId" gorm:"index"`
	Action     string    `json:"action" gorm:"size:40;not null"`
	OperatorID uint      `json:"operatorId" gorm:"index;not null"`
	BeforeJSON string    `json:"beforeJson" gorm:"type:text"`
	AfterJSON  string    `json:"afterJson" gorm:"type:text"`
	Reason     string    `json:"reason" gorm:"type:text"`
	CreatedAt  time.Time `json:"createdAt"`

	Signal   *IssueSignal  `json:"signal,omitempty" gorm:"foreignKey:SignalID"`
	Cluster  *IssueCluster `json:"cluster,omitempty" gorm:"foreignKey:ClusterID"`
	Operator User          `json:"operator,omitempty" gorm:"foreignKey:OperatorID"`
}

func (IssueTriageRecord) TableName() string { return "issue_triage_records" }

type IssueRoutingRule struct {
	ID               uint      `json:"id" gorm:"primaryKey"`
	ProjectID        uint      `json:"projectId" gorm:"index;not null"`
	MatchType        string    `json:"matchType" gorm:"size:40;not null"`
	MatchValue       string    `json:"matchValue" gorm:"size:255;not null"`
	ModuleID         *uint     `json:"moduleId" gorm:"index"`
	OwnerUserID      *uint     `json:"ownerUserId" gorm:"index"`
	PriorityOverride string    `json:"priorityOverride" gorm:"size:20"`
	SeverityOverride string    `json:"severityOverride" gorm:"size:20"`
	Enabled          bool      `json:"enabled"`
	SortOrder        int       `json:"sortOrder" gorm:"default:0"`
	CreatedAt        time.Time `json:"createdAt"`
	UpdatedAt        time.Time `json:"updatedAt"`
}

func (IssueRoutingRule) TableName() string { return "issue_routing_rules" }

type ProjectModule struct {
	ID          uint      `json:"id" gorm:"primaryKey"`
	ProjectID   uint      `json:"projectId" gorm:"index;not null"`
	Name        string    `json:"name" gorm:"size:100;not null"`
	Code        string    `json:"code" gorm:"size:60;not null"`
	Description string    `json:"description" gorm:"type:text"`
	OwnerUserID *uint     `json:"ownerUserId" gorm:"index"`
	RepoID      *uint     `json:"repoId" gorm:"index"`
	PathPattern string    `json:"pathPattern" gorm:"size:255"`
	Tags        string    `json:"tags" gorm:"size:255"`
	CreatedAt   time.Time `json:"createdAt"`
	UpdatedAt   time.Time `json:"updatedAt"`
}

func (ProjectModule) TableName() string { return "project_modules" }

type AppRelease struct {
	ID           uint      `json:"id" gorm:"primaryKey"`
	ProjectID    uint      `json:"projectId" gorm:"index;not null"`
	Platform     string    `json:"platform" gorm:"size:30;index;not null"`
	AppVersion   string    `json:"appVersion" gorm:"size:50;index;not null"`
	BuildNumber  string    `json:"buildNumber" gorm:"size:50;index"`
	Channel      string    `json:"channel" gorm:"size:50"`
	ReleaseTime  time.Time `json:"releaseTime" gorm:"index"`
	CommitSHA    string    `json:"commitSha" gorm:"size:100"`
	RepoID       *uint     `json:"repoId" gorm:"index"`
	MetadataJSON string    `json:"metadataJson" gorm:"type:text"`
	CreatedAt    time.Time `json:"createdAt"`
	UpdatedAt    time.Time `json:"updatedAt"`
}

func (AppRelease) TableName() string { return "app_releases" }

type ExternalSyncRecord struct {
	ID                uint       `json:"id" gorm:"primaryKey"`
	EntityType        string     `json:"entityType" gorm:"size:30;index;not null"`
	EntityID          uint       `json:"entityId" gorm:"index;not null"`
	TargetType        string     `json:"targetType" gorm:"size:30;index;not null"`
	ExternalThreadID  string     `json:"externalThreadId" gorm:"size:120"`
	ExternalMessageID string     `json:"externalMessageId" gorm:"size:120"`
	SyncDirection     string     `json:"syncDirection" gorm:"size:20;not null"`
	SyncStatus        string     `json:"syncStatus" gorm:"size:20;index;not null"`
	LastSyncedAt      *time.Time `json:"lastSyncedAt"`
	LastError         string     `json:"lastError" gorm:"type:text"`
	CreatedAt         time.Time  `json:"createdAt"`
	UpdatedAt         time.Time  `json:"updatedAt"`
}

func (ExternalSyncRecord) TableName() string { return "external_sync_records" }

type RegressionItem struct {
	ID                uint       `json:"id" gorm:"primaryKey"`
	ProjectID         uint       `json:"projectId" gorm:"index;not null"`
	ClusterID         *uint      `json:"clusterId" gorm:"index"`
	DefectID          *uint      `json:"defectId" gorm:"index"`
	Title             string     `json:"title" gorm:"size:200;not null"`
	Summary           string     `json:"summary" gorm:"type:text"`
	SourceFingerprint string     `json:"sourceFingerprint" gorm:"size:255;index"`
	Status            string     `json:"status" gorm:"size:20;index;not null;default:'draft'"`
	OwnerUserID       *uint      `json:"ownerUserId" gorm:"index"`
	CreatedBy         uint       `json:"createdBy" gorm:"index;not null"`
	LastVerifiedAt    *time.Time `json:"lastVerifiedAt"`
	CreatedAt         time.Time  `json:"createdAt"`
	UpdatedAt         time.Time  `json:"updatedAt"`

	Project Project       `json:"project,omitempty" gorm:"foreignKey:ProjectID"`
	Cluster *IssueCluster `json:"cluster,omitempty" gorm:"foreignKey:ClusterID"`
	Defect  *Defect       `json:"defect,omitempty" gorm:"foreignKey:DefectID"`
	Owner   *User         `json:"owner,omitempty" gorm:"foreignKey:OwnerUserID"`
	Creator User          `json:"creator,omitempty" gorm:"foreignKey:CreatedBy"`
}

func (RegressionItem) TableName() string { return "regression_items" }

type RoutingSuggestionFeedback struct {
	ID              uint      `json:"id" gorm:"primaryKey"`
	ClusterID       uint      `json:"clusterId" gorm:"index;not null"`
	RoutingRuleID   *uint     `json:"routingRuleId" gorm:"index"`
	SuggestedOwner  *uint     `json:"suggestedOwner" gorm:"index"`
	SuggestedModule *uint     `json:"suggestedModule" gorm:"index"`
	Confidence      float64   `json:"confidence"`
	EvidenceJSON    string    `json:"evidenceJson" gorm:"type:text"`
	Accepted        bool      `json:"accepted"`
	ActualOwner     *uint     `json:"actualOwner" gorm:"index"`
	ActualModule    *uint     `json:"actualModule" gorm:"index"`
	OperatorID      uint      `json:"operatorId" gorm:"index;not null"`
	CreatedAt       time.Time `json:"createdAt"`

	Cluster  IssueCluster     `json:"cluster,omitempty" gorm:"foreignKey:ClusterID"`
	Rule     *IssueRoutingRule `json:"rule,omitempty" gorm:"foreignKey:RoutingRuleID"`
	Operator User             `json:"operator,omitempty" gorm:"foreignKey:OperatorID"`
}

func (RoutingSuggestionFeedback) TableName() string { return "routing_suggestion_feedbacks" }
