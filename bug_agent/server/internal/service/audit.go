package service

import (
	"bug-agent/internal/asyncx"
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"encoding/json"
	"sync"
	"time"

	"gorm.io/gorm"
)

const auditBatchSize = 50
const auditFlushInterval = 2 * time.Second

// AuditService handles operation audit logging with batch writing
type AuditService struct {
	db    *gorm.DB
	batch chan model.AuditLog
	stop  chan struct{}
	wg    sync.WaitGroup
}

// NewAuditService creates a new audit service instance with batch writer
func NewAuditService(db *gorm.DB) *AuditService {
	s := &AuditService{
		db: db,
	}
	if asyncx.BackgroundWorkersDisabled() {
		return s
	}
	s.batch = make(chan model.AuditLog, 500)
	s.stop = make(chan struct{})
	s.wg.Add(1)
	go s.batchWriter()
	return s
}

// Stop gracefully shuts down the batch writer
func (s *AuditService) Stop() {
	if s.stop == nil {
		return
	}
	close(s.stop)
	s.wg.Wait()
}

func (s *AuditService) batchWriter() {
	defer s.wg.Done()

	ticker := time.NewTicker(auditFlushInterval)
	defer ticker.Stop()

	buffer := make([]model.AuditLog, 0, auditBatchSize)

	flush := func() {
		if len(buffer) == 0 {
			return
		}
		if err := s.db.Create(&buffer).Error; err != nil {
			logger.Errorf("[Audit] Batch flush failed: %v", err)
		}
		buffer = buffer[:0]
	}

	drainAndFlush := func() {
		for {
			select {
			case entry, ok := <-s.batch:
				if !ok {
					flush()
					return
				}
				buffer = append(buffer, entry)
				if len(buffer) >= auditBatchSize {
					flush()
				}
			default:
				flush()
				return
			}
		}
	}

	for {
		select {
		case entry, ok := <-s.batch:
			if !ok {
				flush()
				return
			}
			buffer = append(buffer, entry)
			if len(buffer) >= auditBatchSize {
				flush()
			}
		case <-ticker.C:
			flush()
		case <-s.stop:
			drainAndFlush()
			return
		}
	}
}

// LogAction records an audit entry (non-blocking, uses batch channel)
func (s *AuditService) LogAction(entry model.AuditLog) error {
	if entry.CreatedAt.IsZero() {
		entry.CreatedAt = time.Now()
	}
	if s.batch == nil {
		return s.db.Create(&entry).Error
	}
	select {
	case s.batch <- entry:
		return nil
	default:
		logger.Infof("[Audit] Batch full, falling back to direct write")
		return s.db.Create(&entry).Error
	}
}

// LogWithDetails creates a detailed audit log entry
func (s *AuditService) LogWithDetails(
	userID uint,
	username string,
	action string,
	targetType string,
	targetID *uint,
	oldValue interface{},
	newValue interface{},
	custom map[string]interface{},
) error {
	entry := model.AuditLog{
		UserID:     userID,
		Username:   username,
		Action:     action,
		TargetType: targetType,
		TargetID:   targetID,
		CreatedAt:  time.Now(),
	}

	if oldValue != nil {
		data, err := json.Marshal(oldValue)
		if err != nil {
			logger.Errorf("[Audit] marshal oldValue failed: %v", err)
		} else {
			entry.OldValue = string(data)
		}
	}
	if newValue != nil {
		data, err := json.Marshal(newValue)
		if err != nil {
			logger.Errorf("[Audit] marshal newValue failed: %v", err)
		} else {
			entry.NewValue = string(data)
		}
	}

	if custom != nil {
		if ip, ok := custom["ip_address"].(string); ok {
			entry.IPAddress = ip
		}
		if ua, ok := custom["user_agent"].(string); ok {
			entry.UserAgent = ua
		}
		if method, ok := custom["request_method"].(string); ok {
			entry.RequestMethod = method
		}
		if path, ok := custom["request_path"].(string); ok {
			entry.RequestPath = path
		}
		if status, ok := custom["status_code"].(int); ok {
			entry.StatusCode = status
		}
		if err, ok := custom["error_message"].(string); ok {
			entry.ErrorMessage = err
		}
		if duration, ok := custom["duration_ms"].(int); ok {
			entry.DurationMs = duration
		}
	}

	return s.LogAction(entry)
}

// QueryLogs retrieves audit logs with pagination and filtering
func (s *AuditService) QueryLogs(params AuditQueryParams) ([]model.AuditLog, int64, error) {
	var logs []model.AuditLog
	var total int64

	query := s.db.Model(&model.AuditLog{})

	if params.UserID > 0 {
		query = query.Where("user_id = ?", params.UserID)
	}
	if params.Action != "" {
		query = query.Where("action LIKE ?", "%"+escapeLike(params.Action)+"%")
	}
	if params.TargetType != "" {
		query = query.Where("target_type = ?", params.TargetType)
	}
	if params.TargetID > 0 {
		query = query.Where("target_id = ?", params.TargetID)
	}
	if params.StartDate != "" {
		query = query.Where("created_at >= ?", params.StartDate)
	}
	if params.EndDate != "" {
		query = query.Where("created_at <= ?", params.EndDate+" 23:59:59")
	}

	if err := query.Count(&total).Error; err != nil {
		return nil, 0, err
	}

	order := "created_at DESC"
	if params.OrderBy != "" {
		allowedAuditOrders := map[string]bool{
			"created_at ASC":      true,
			"created_at DESC":     true,
			"user_id ASC":         true,
			"user_id DESC":        true,
			"action ASC":          true,
			"action DESC":         true,
			"target_type ASC":     true,
			"target_type DESC":    true,
			"target_id ASC":       true,
			"target_id DESC":      true,
			"ip_address ASC":      true,
			"ip_address DESC":     true,
			"request_method ASC":  true,
			"request_method DESC": true,
			"status_code ASC":     true,
			"status_code DESC":    true,
		}
		if allowedAuditOrders[params.OrderBy] {
			order = params.OrderBy
		}
	}

	if params.Page < 1 {
		params.Page = 1
	}
	if params.PageSize < 1 {
		params.PageSize = 20
	}
	if params.PageSize > 100 {
		params.PageSize = 100
	}
	offset := (params.Page - 1) * params.PageSize
	err := query.Order(order).
		Offset(offset).
		Limit(params.PageSize).
		Find(&logs).Error

	return logs, total, err
}

// GetRecentLogs gets recent audit logs for a user or target
func (s *AuditService) GetRecentLogs(limit int, targetType string, targetID uint) []model.AuditLog {
	var logs []model.AuditLog

	query := s.db.Order("created_at DESC").Limit(limit)
	if targetType != "" && targetID > 0 {
		query = query.Where("target_type = ? AND target_id = ?", targetType, targetID)
	}
	if err := query.Find(&logs).Error; err != nil {
		logger.Errorf("查询审计日志失败: %v", err)
	}

	return logs
}

// AuditQueryParams parameters for querying audit logs
type AuditQueryParams struct {
	Page       int    `form:"page"`
	PageSize   int    `form:"pageSize"`
	UserID     uint   `form:"userId"`
	Action     string `form:"action"`
	TargetType string `form:"targetType"`
	TargetID   uint   `form:"targetId"`
	StartDate  string `form:"startDate"`
	EndDate    string `form:"endDate"`
	OrderBy    string
}
