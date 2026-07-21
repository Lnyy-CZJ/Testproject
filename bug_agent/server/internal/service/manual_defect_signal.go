package service

import (
	"bug-agent/internal/model"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"gorm.io/gorm"
)

type ManualDefectSignalService struct {
	db *gorm.DB
}

func NewManualDefectSignalService(db *gorm.DB) *ManualDefectSignalService {
	return &ManualDefectSignalService{db: db}
}

func (s *ManualDefectSignalService) Ingest(tx *gorm.DB, defect model.Defect, projectID uint, sourceType string) (*model.IssueSignal, *model.IssueCluster, error) {
	db := tx
	if db == nil {
		db = s.db
	}
	if db == nil {
		return nil, nil, fmt.Errorf("database unavailable")
	}
	if projectID == 0 {
		return nil, nil, fmt.Errorf("projectID 不能为空")
	}
	sourceType = normalizeManualIssueSourceType(sourceType)

	var existing model.IssueSignal
	if err := db.Where("linked_defect_id = ?", defect.ID).First(&existing).Error; err == nil {
		var cluster model.IssueCluster
		if existing.ClusterID != nil {
			_ = db.First(&cluster, *existing.ClusterID).Error
		}
		return &existing, &cluster, nil
	} else if err != nil && err != gorm.ErrRecordNotFound {
		return nil, nil, err
	}

	now := time.Now()
	firstSeen := defect.CreatedAt
	if firstSeen.IsZero() {
		firstSeen = now
	}
	clusterKey := fmt.Sprintf("manual-defect:%d", defect.ID)
	cluster := model.IssueCluster{
		ProjectID:         projectID,
		ClusterKey:        clusterKey,
		Title:             truncateText(defect.Title, 200),
		Summary:           defect.Description,
		Status:            model.IssueTriageStatusConverted,
		SignalCount:       1,
		AffectedUserCount: 1,
		Severity:          defect.Severity,
		Priority:          defect.Priority,
		OwnerUserID:       defect.AssigneeID,
		FirstSeenAt:       firstSeen,
		LastSeenAt:        now,
		LinkedDefectID:    &defect.ID,
	}
	if err := db.Create(&cluster).Error; err != nil {
		return nil, nil, err
	}

	rawPayload, _ := json.Marshal(generateDefectPayload(defect, sourceType))
	sourceInstance := fmt.Sprintf("%s:%d", sourceType, projectID)
	sourceEventID := fmt.Sprintf("defect:%d", defect.ID)
	signal := model.IssueSignal{
		ProjectID:         projectID,
		ConnectorID:       nil,
		ClusterID:         &cluster.ID,
		SourceType:        sourceType,
		SourceInstance:    sourceInstance,
		SourceEventID:     sourceEventID,
		Title:             truncateText(defect.Title, 200),
		Description:       defect.Description,
		RawSeverity:       defect.Severity,
		RawPriority:       defect.Priority,
		Fingerprint:       hashText(fmt.Sprintf("manual:%d:%s", defect.ID, strings.TrimSpace(defect.Title))),
		OccurrenceCount:   1,
		AffectedUserCount: 1,
		FirstSeenAt:       firstSeen,
		LastSeenAt:        now,
		RawPayloadJSON:    string(rawPayload),
		TriageStatus:      model.IssueTriageStatusConverted,
		LinkedDefectID:    &defect.ID,
	}
	if err := db.Create(&signal).Error; err != nil {
		return nil, nil, err
	}

	return &signal, &cluster, nil
}

func normalizeManualIssueSourceType(sourceType string) string {
	sourceType = strings.TrimSpace(sourceType)
	switch sourceType {
	case model.IssueSourceManualChat:
		return model.IssueSourceManualChat
	case model.IssueSourceManualForm:
		return model.IssueSourceManualForm
	default:
		return model.IssueSourceManualForm
	}
}

func generateDefectPayload(defect model.Defect, sourceType string) map[string]interface{} {
	return map[string]interface{}{
		"defectId":    defect.ID,
		"code":        defect.Code,
		"title":       defect.Title,
		"description": defect.Description,
		"severity":    defect.Severity,
		"priority":    defect.Priority,
		"type":        defect.Type,
		"tags":        strings.Split(strings.TrimSpace(defect.Tags), ","),
		"iterationId": defect.IterationID,
		"reporterId":  defect.ReporterID,
		"assigneeId":  defect.AssigneeID,
		"sourceType":  sourceType,
		"createdAt":   defect.CreatedAt,
	}
}
