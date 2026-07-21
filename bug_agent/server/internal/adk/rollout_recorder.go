package adk

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"bug-agent/pkg/logger"

	"gorm.io/gorm"
)

type RolloutRecord struct {
	ID        uint           `gorm:"primaryKey" json:"id"`
	SessionID string         `gorm:"uniqueIndex;size:200" json:"session_id"`
	DefectID  uint           `gorm:"index" json:"defect_id"`
	Events    string         `gorm:"type:text" json:"events"`
	Status    string         `gorm:"size:20;default:running" json:"status"`
	CreatedAt time.Time      `json:"created_at"`
	UpdatedAt time.Time      `json:"updated_at"`
	DeletedAt gorm.DeletedAt `gorm:"index" json:"-"`
}

func (RolloutRecord) TableName() string { return "rollout_records" }

type RolloutRecorder struct {
	db *gorm.DB
}

func NewRolloutRecorder(db *gorm.DB) *RolloutRecorder {
	return &RolloutRecorder{db: db}
}

func (r *RolloutRecorder) AutoMigrate() error {
	return r.db.AutoMigrate(&RolloutRecord{})
}

func (r *RolloutRecorder) Record(sessionID string, defectID uint, eventType string, data interface{}) error {
	dataJSON, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("marshal event data: %w", err)
	}

	eventEntry, _ := json.Marshal(map[string]interface{}{
		"type":      eventType,
		"data":      string(dataJSON),
		"timestamp": time.Now().UnixMilli(),
	})

	return r.db.Transaction(func(tx *gorm.DB) error {
		var record RolloutRecord
		if err := tx.Where("session_id = ?", sessionID).First(&record).Error; err != nil {
			if err == gorm.ErrRecordNotFound {
				record := RolloutRecord{
					SessionID: sessionID,
					DefectID:  defectID,
					Status:    "running",
					Events:    "[" + string(eventEntry) + "]",
				}
				return tx.Create(&record).Error
			}
			return err
		}

		currentEvents := record.Events
		if len(currentEvents) == 0 || currentEvents[len(currentEvents)-1] != ']' {
			currentEvents = "[]"
		}
		newEvents := currentEvents[:len(currentEvents)-1] + "," + string(eventEntry) + "]"
		return tx.Model(&RolloutRecord{}).Where("session_id = ?", sessionID).
			Updates(map[string]interface{}{"events": newEvents, "updated_at": time.Now()}).Error
	})
}

func (r *RolloutRecorder) MarkCompleted(sessionID string) error {
	return r.db.Model(&RolloutRecord{}).Where("session_id = ?", sessionID).
		Updates(map[string]interface{}{"status": "completed", "updated_at": time.Now()}).Error
}

func (r *RolloutRecorder) MarkFailed(sessionID string) error {
	return r.db.Model(&RolloutRecord{}).Where("session_id = ?", sessionID).
		Updates(map[string]interface{}{"status": "failed", "updated_at": time.Now()}).Error
}

func (r *RolloutRecorder) MarkCancelled(sessionID string) error {
	return r.db.Model(&RolloutRecord{}).Where("session_id = ?", sessionID).
		Updates(map[string]interface{}{"status": "cancelled", "updated_at": time.Now()}).Error
}

func (r *RolloutRecorder) ListByDefect(defectID uint) ([]RolloutRecord, error) {
	var records []RolloutRecord
	err := r.db.Where("defect_id = ?", defectID).Order("created_at DESC").Find(&records).Error
	return records, err
}

func (r *RolloutRecorder) GetBySession(sessionID string) (*RolloutRecord, error) {
	var record RolloutRecord
	err := r.db.Where("session_id = ?", sessionID).First(&record).Error
	if err != nil {
		return nil, err
	}
	return &record, nil
}

func (r *RolloutRecorder) ResumeLastIncomplete(ctx context.Context, defectID uint) (*RolloutRecord, error) {
	var record RolloutRecord
	err := r.db.Where("defect_id = ? AND status = ?", defectID, "running").
		Order("created_at DESC").First(&record).Error
	if err != nil {
		return nil, err
	}
	logger.Infof("[RolloutRecorder] found incomplete session %s for defect %d", record.SessionID, defectID)
	return &record, nil
}

func InitRolloutRecorder(db *gorm.DB) *RolloutRecorder {
	recorder := NewRolloutRecorder(db)
	if err := recorder.AutoMigrate(); err != nil {
		logger.Warnf("[RolloutRecorder] auto migrate failed: %v", err)
	}
	return recorder
}
