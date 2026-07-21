package service

import (
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"gorm.io/gorm"
)

var (
	ErrIntegrationConnectorNotFound = errors.New("integration connector not found")
	ErrIntegrationConnectorInactive = errors.New("integration connector inactive")
	ErrInvalidSignalPayload         = errors.New("invalid signal payload")
)

type SignalIngestService struct {
	db         *gorm.DB
	routingSvc *ProjectRoutingService
}

type NormalizedSignalInput struct {
	SourceType        string
	SourceInstance    string
	SourceEventID     string
	Title             string
	Description       string
	RawSeverity       string
	RawPriority       string
	AppVersion        string
	BuildNumber       string
	Platform          string
	DeviceInfoJSON    string
	StackTrace        string
	LogExcerpt        string
	Fingerprint       string
	OccurrenceCount   int
	AffectedUserCount int
	FirstSeenAt       time.Time
	LastSeenAt        time.Time
}

func NewSignalIngestService(db *gorm.DB) *SignalIngestService {
	return &SignalIngestService{
		db:         db,
		routingSvc: NewProjectRoutingService(db),
	}
}

func (s *SignalIngestService) Ingest(connector model.IntegrationConnector, triggerType string, rawBody []byte) (*model.IssueSignal, *model.IssueCluster, *model.IntegrationSyncRecord, error) {
	signals, clusters, record, err := s.IngestBatch(connector, triggerType, []json.RawMessage{json.RawMessage(rawBody)}, string(rawBody))
	if err != nil {
		return nil, nil, record, err
	}
	if len(signals) == 0 || len(clusters) == 0 {
		return nil, nil, record, nil
	}
	return signals[0], clusters[0], record, nil
}

func (s *SignalIngestService) IngestBatch(connector model.IntegrationConnector, triggerType string, rawBodies []json.RawMessage, requestSummary string) ([]*model.IssueSignal, []*model.IssueCluster, *model.IntegrationSyncRecord, error) {
	if connector.ID == 0 {
		return nil, nil, nil, ErrIntegrationConnectorNotFound
	}
	if connector.Status != model.ConnectorStatusActive {
		return nil, nil, nil, ErrIntegrationConnectorInactive
	}

	summary := truncateText(strings.TrimSpace(requestSummary), 4000)
	if summary == "" {
		summary = fmt.Sprintf("{\"items\":%d}", len(rawBodies))
	}
	syncRecord := &model.IntegrationSyncRecord{
		ConnectorID:    connector.ID,
		TriggerType:    triggerType,
		Status:         model.SyncStatusPending,
		RequestSummary: summary,
		StartedAt:      time.Now(),
		CreatedAt:      time.Now(),
	}
	if err := s.db.Create(syncRecord).Error; err != nil {
		return nil, nil, nil, err
	}

	signals := make([]*model.IssueSignal, 0, len(rawBodies))
	clusters := make([]*model.IssueCluster, 0, len(rawBodies))
	clusterIDs := make(map[uint]struct{})

	err := s.db.Transaction(func(tx *gorm.DB) error {
		for _, rawBody := range rawBodies {
			payload, normalized, err := s.parseAndNormalize(connector, rawBody)
			if err != nil {
				return err
			}
			signal, cluster, err := s.ingestNormalized(tx, connector, payload, rawBody, normalized)
			if err != nil {
				return err
			}
			signals = append(signals, signal)
			clusters = append(clusters, cluster)
			clusterIDs[cluster.ID] = struct{}{}
		}
		return nil
	})
	if err != nil {
		record := s.finishSyncRecord(syncRecord, connector.ID, triggerType, summary, 0, 0, err)
		return nil, nil, record, err
	}

	record := s.finishSyncRecord(syncRecord, connector.ID, triggerType, summary, len(signals), len(clusterIDs), nil)
	return signals, clusters, record, nil
}

func (s *SignalIngestService) parseAndNormalize(connector model.IntegrationConnector, rawBody []byte) (map[string]interface{}, NormalizedSignalInput, error) {
	var payload map[string]interface{}
	if err := json.Unmarshal(rawBody, &payload); err != nil {
		return nil, NormalizedSignalInput{}, ErrInvalidSignalPayload
	}
	normalized, err := s.NormalizePayload(connector, payload)
	if err != nil {
		return nil, NormalizedSignalInput{}, err
	}
	return payload, normalized, nil
}

func (s *SignalIngestService) ingestNormalized(tx *gorm.DB, connector model.IntegrationConnector, payload map[string]interface{}, rawBody []byte, normalized NormalizedSignalInput) (*model.IssueSignal, *model.IssueCluster, error) {
	clusterKey := normalized.Fingerprint
	if clusterKey == "" {
		clusterKey = hashText(fmt.Sprintf("%d:%s:%s", connector.ProjectID, normalized.Title, normalized.Platform))
	}

	var cluster model.IssueCluster
	if err := tx.Where("project_id = ? AND cluster_key = ?", connector.ProjectID, clusterKey).First(&cluster).Error; err != nil {
		if !errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, nil, err
		}
		cluster = model.IssueCluster{
			ProjectID:         connector.ProjectID,
			ClusterKey:        clusterKey,
			Title:             truncateText(normalized.Title, 200),
			Summary:           truncateText(normalized.Description, 2000),
			Status:            model.IssueTriageStatusNew,
			SignalCount:       0,
			AffectedUserCount: 0,
			Severity:          truncateText(normalized.RawSeverity, 20),
			Priority:          truncateText(normalized.RawPriority, 20),
			FirstSeenAt:       normalized.FirstSeenAt,
			LastSeenAt:        normalized.LastSeenAt,
		}
		if err := tx.Create(&cluster).Error; err != nil {
			return nil, nil, err
		}
	}

	var signal model.IssueSignal
	err := tx.Where("source_instance = ? AND source_event_id = ?", normalized.SourceInstance, normalized.SourceEventID).First(&signal).Error
	switch {
	case errors.Is(err, gorm.ErrRecordNotFound):
		signal = buildIssueSignal(connector, cluster.ID, normalized, string(rawBody))
		if err := tx.Create(&signal).Error; err != nil {
			return nil, nil, err
		}
	case err != nil:
		return nil, nil, err
	default:
		updateIssueSignal(&signal, connector, cluster.ID, normalized, string(rawBody))
		if err := tx.Save(&signal).Error; err != nil {
			return nil, nil, err
		}
	}

	if err := s.refreshClusterMetrics(tx, &cluster, normalized); err != nil {
		return nil, nil, err
	}
	routingSvc := s.routingSvc
	if err := routingSvc.ApplyClusterRouting(&signal, &cluster); err != nil {
		return nil, nil, err
	}
	if err := tx.Save(&cluster).Error; err != nil {
		return nil, nil, err
	}
	return &signal, &cluster, nil
}

func buildIssueSignal(connector model.IntegrationConnector, clusterID uint, normalized NormalizedSignalInput, rawPayload string) model.IssueSignal {
	connectorID := connector.ID
	return model.IssueSignal{
		ProjectID:         connector.ProjectID,
		ConnectorID:       &connectorID,
		ClusterID:         &clusterID,
		SourceType:        normalized.SourceType,
		SourceInstance:    normalized.SourceInstance,
		SourceEventID:     normalized.SourceEventID,
		Title:             truncateText(normalized.Title, 200),
		Description:       normalized.Description,
		RawSeverity:       truncateText(normalized.RawSeverity, 30),
		RawPriority:       truncateText(normalized.RawPriority, 30),
		AppVersion:        truncateText(normalized.AppVersion, 50),
		BuildNumber:       truncateText(normalized.BuildNumber, 50),
		Platform:          truncateText(normalized.Platform, 30),
		DeviceInfoJSON:    normalized.DeviceInfoJSON,
		StackTrace:        normalized.StackTrace,
		LogExcerpt:        normalized.LogExcerpt,
		Fingerprint:       truncateText(normalized.Fingerprint, 255),
		OccurrenceCount:   normalized.OccurrenceCount,
		AffectedUserCount: normalized.AffectedUserCount,
		FirstSeenAt:       normalized.FirstSeenAt,
		LastSeenAt:        normalized.LastSeenAt,
		RawPayloadJSON:    rawPayload,
		TriageStatus:      model.IssueTriageStatusNew,
	}
}

func updateIssueSignal(signal *model.IssueSignal, connector model.IntegrationConnector, clusterID uint, normalized NormalizedSignalInput, rawPayload string) {
	connectorID := connector.ID
	signal.ClusterID = &clusterID
	signal.ProjectID = connector.ProjectID
	signal.ConnectorID = &connectorID
	signal.SourceType = normalized.SourceType
	signal.Title = truncateText(normalized.Title, 200)
	signal.Description = normalized.Description
	signal.RawSeverity = truncateText(normalized.RawSeverity, 30)
	signal.RawPriority = truncateText(normalized.RawPriority, 30)
	signal.AppVersion = truncateText(normalized.AppVersion, 50)
	signal.BuildNumber = truncateText(normalized.BuildNumber, 50)
	signal.Platform = truncateText(normalized.Platform, 30)
	signal.DeviceInfoJSON = normalized.DeviceInfoJSON
	signal.StackTrace = normalized.StackTrace
	signal.LogExcerpt = normalized.LogExcerpt
	signal.Fingerprint = truncateText(normalized.Fingerprint, 255)
	signal.OccurrenceCount = normalized.OccurrenceCount
	signal.AffectedUserCount = normalized.AffectedUserCount
	signal.FirstSeenAt = normalized.FirstSeenAt
	signal.LastSeenAt = normalized.LastSeenAt
	signal.RawPayloadJSON = rawPayload
}

func (s *SignalIngestService) NormalizePayload(connector model.IntegrationConnector, payload map[string]interface{}) (NormalizedSignalInput, error) {
	now := time.Now()
	sourceType := strings.TrimSpace(connector.Type)
	if sourceType == "" {
		sourceType = model.ConnectorTypeWebhook
	}
	sourceInstance := fmt.Sprintf("%s:%d", sourceType, connector.ID)
	flattened := enrichPayloadForSource(sourceType, payload)

	title := firstString(flattened, "title", "summary", "issueTitle", "name")
	description := firstString(flattened, "description", "message", "content", "detail")
	stackTrace := firstString(flattened, "stackTrace", "stack", "stacktrace", "stackInfo")
	logExcerpt := firstString(flattened, "logExcerpt", "logger", "logs")

	if title == "" {
		if stackTrace != "" {
			title = firstLine(stackTrace)
		} else if description != "" {
			title = firstLine(description)
		}
	}
	if title == "" {
		title = "未命名问题"
	}
	if description == "" {
		description = stackTrace
	}

	sourceEventID := firstString(flattened, "eventId", "eventID", "id", "issueId", "messageId")
	if sourceEventID == "" {
		sourceEventID = hashText(mustMarshal(flattened))
	}

	fingerprint := firstString(flattened, "fingerprint", "issueKey", "crashHash", "hash")
	if fingerprint == "" {
		fingerprint = hashText(strings.Join([]string{title, stackTrace, description, firstString(flattened, "platform"), firstString(flattened, "appVersion")}, "|"))
	}

	deviceInfoJSON := normalizeDeviceInfo(flattened)
	firstSeen := firstTime(flattened, now, "firstSeenAt", "firstSeen", "firstOccurredAt")
	lastSeen := firstTime(flattened, now, "lastSeenAt", "lastSeen", "occurredAt", "timestamp")

	input := NormalizedSignalInput{
		SourceType:        sourceType,
		SourceInstance:    sourceInstance,
		SourceEventID:     sourceEventID,
		Title:             title,
		Description:       description,
		RawSeverity:       firstString(flattened, "severity", "level"),
		RawPriority:       firstString(flattened, "priority"),
		AppVersion:        firstString(flattened, "appVersion", "version"),
		BuildNumber:       firstString(flattened, "buildNumber", "build"),
		Platform:          firstString(flattened, "platform", "appPlatform", "os"),
		DeviceInfoJSON:    deviceInfoJSON,
		StackTrace:        stackTrace,
		LogExcerpt:        logExcerpt,
		Fingerprint:       fingerprint,
		OccurrenceCount:   firstInt(flattened, 1, "occurrenceCount", "count", "crashCount"),
		AffectedUserCount: firstInt(flattened, 1, "affectedUserCount", "affectedUsers", "userCount"),
		FirstSeenAt:       firstSeen,
		LastSeenAt:        lastSeen,
	}

	if strings.TrimSpace(input.Title) == "" {
		return NormalizedSignalInput{}, ErrInvalidSignalPayload
	}
	return input, nil
}

func (s *SignalIngestService) refreshClusterMetrics(tx *gorm.DB, cluster *model.IssueCluster, normalized NormalizedSignalInput) error {
	type aggResult struct {
		SignalCount     int64
		AffectedUserSum int64
	}
	var agg aggResult
	err := tx.Model(&model.IssueSignal{}).
		Where("cluster_id = ?", cluster.ID).
		Select("COUNT(*) AS signal_count, COALESCE(SUM(affected_user_count), 0) AS affected_user_sum").
		Scan(&agg).Error
	if err != nil {
		return err
	}
	var firstSignal model.IssueSignal
	if err := tx.Where("cluster_id = ?", cluster.ID).Order("first_seen_at ASC, id ASC").First(&firstSignal).Error; err != nil {
		return err
	}
	var lastSignal model.IssueSignal
	if err := tx.Where("cluster_id = ?", cluster.ID).Order("last_seen_at DESC, id DESC").First(&lastSignal).Error; err != nil {
		return err
	}

	cluster.Title = truncateText(normalized.Title, 200)
	cluster.Summary = truncateText(normalized.Description, 2000)
	cluster.SignalCount = int(agg.SignalCount)
	cluster.AffectedUserCount = int(agg.AffectedUserSum)
	cluster.Severity = truncateText(normalized.RawSeverity, 20)
	cluster.Priority = truncateText(normalized.RawPriority, 20)
	cluster.FirstSeenAt = firstSignal.FirstSeenAt
	cluster.LastSeenAt = lastSignal.LastSeenAt
	if cluster.Status == "" {
		cluster.Status = model.IssueTriageStatusNew
	}
	return tx.Save(cluster).Error
}

func (s *SignalIngestService) finishSyncRecord(record *model.IntegrationSyncRecord, connectorID uint, triggerType, summary string, importedCount, clusteredCount int, err error) *model.IntegrationSyncRecord {
	now := time.Now()
	detail := ExplainConnectorError(err)
	if record == nil {
		record = &model.IntegrationSyncRecord{
			ConnectorID:    connectorID,
			TriggerType:    triggerType,
			RequestSummary: truncateText(summary, 4000),
			StartedAt:      now,
			CreatedAt:      now,
		}
		if err != nil {
			record.Status = model.SyncStatusFailed
			record.ErrorMessage = err.Error()
			record.ErrorKind = detail.Kind
			record.Retryable = detail.Retryable
		}
		record.FinishedAt = &now
		if err == nil {
			record.Status = model.SyncStatusSuccess
			record.ImportedCount = importedCount
			record.ClusteredCount = clusteredCount
			record.ErrorKind = ""
			record.Retryable = false
		}
		if err := s.db.Create(record).Error; err != nil {
			logger.Errorf("db operation failed: %v", err)
		}
	} else {
		record.FinishedAt = &now
		record.ImportedCount = importedCount
		record.ClusteredCount = clusteredCount
		if err != nil {
			record.Status = model.SyncStatusFailed
			record.ErrorMessage = err.Error()
			record.ErrorKind = detail.Kind
			record.Retryable = detail.Retryable
		} else {
			record.Status = model.SyncStatusSuccess
			record.ErrorMessage = ""
			record.ErrorKind = ""
			record.Retryable = false
		}
		if err := s.db.Save(record).Error; err != nil {
			logger.Errorf("db operation failed: %v", err)
		}
	}

	connectorUpdates := map[string]interface{}{
		"last_sync_at":     now,
		"last_sync_status": record.Status,
		"last_error":       record.ErrorMessage,
	}
	if err := s.db.Model(&model.IntegrationConnector{}).Where("id = ?", connectorID).Updates(connectorUpdates).Error; err != nil {
		logger.Errorf("更新连接器状态失败: %v", err)
	}
	return record
}

func enrichPayloadForSource(sourceType string, payload map[string]interface{}) map[string]interface{} {
	flattened := cloneStringMap(payload)
	switch sourceType {
	case model.ConnectorTypeBugly:
		setIfEmpty(flattened, "description", firstString(flattened, "detail", "detailMessage", "message"))
		setIfEmpty(flattened, "stackTrace", firstString(flattened, "stackInfo", "stack"))
	case model.ConnectorTypeAliyun:
		setIfEmpty(flattened, "title", firstLine(firstString(flattened, "message", "content", "body", "logger")))
		setIfEmpty(flattened, "eventId", firstString(flattened, "event_id", "__tag__:event_id", "__tag__:eventId"))
		setIfEmpty(flattened, "description", firstString(flattened, "message", "content", "body", "logger"))
		setIfEmpty(flattened, "logExcerpt", firstString(flattened, "message", "content", "body", "logger"))
		setIfEmpty(flattened, "stackTrace", firstString(flattened, "stack", "stack_trace", "stacktrace", "trace"))
		setIfEmpty(flattened, "appVersion", firstString(flattened, "app_version", "__tag__:app_version", "__tag__:version"))
		setIfEmpty(flattened, "buildNumber", firstString(flattened, "build_number", "__tag__:build_number"))
		setIfEmpty(flattened, "platform", firstString(flattened, "app_platform", "os", "os_type"))
		setIfEmpty(flattened, "deviceModel", firstString(flattened, "device_model"))
		setIfEmpty(flattened, "deviceBrand", firstString(flattened, "device_brand", "brand"))
		setIfEmpty(flattened, "osVersion", firstString(flattened, "os_version"))
		setIfEmpty(flattened, "fingerprint", firstString(flattened, "crash_hash", "error_hash"))
		setIfEmpty(flattened, "affectedUserCount", firstString(flattened, "affected_users", "user_count"))
		setIfEmpty(flattened, "occurredAt", firstString(flattened, "__time__", "time", "log_time"))
	case model.ConnectorTypeDingTalk:
		content := firstNestedString(payload, "text.content")
		if content == "" {
			content = firstString(flattened, "text", "message", "content")
		}
		applyMessageContent(flattened, content)
	case model.ConnectorTypeFeishu:
		setIfEmpty(flattened, "messageId", firstNestedString(payload, "event.message.message_id", "message.message_id"))
		setIfEmpty(flattened, "eventId", firstNestedString(payload, "header.event_id", "event.message.message_id"))
		content := extractFeishuMessageText(payload)
		applyMessageContent(flattened, content)
	}
	return flattened
}

func applyMessageContent(payload map[string]interface{}, content string) {
	trimmed := strings.TrimSpace(content)
	if trimmed == "" {
		return
	}
	setIfEmpty(payload, "content", trimmed)
	setIfEmpty(payload, "message", trimmed)
	setIfEmpty(payload, "description", trimmed)
	setIfEmpty(payload, "title", firstLine(trimmed))
}

func extractFeishuMessageText(payload map[string]interface{}) string {
	content := firstNestedString(payload, "event.message.content", "message.content")
	trimmed := strings.TrimSpace(content)
	if trimmed == "" {
		return ""
	}
	if strings.HasPrefix(trimmed, "{") {
		var decoded map[string]interface{}
		if err := json.Unmarshal([]byte(trimmed), &decoded); err == nil {
			if text := firstString(decoded, "text", "title", "content"); text != "" {
				return text
			}
		}
	}
	return trimmed
}

func firstNestedString(payload map[string]interface{}, paths ...string) string {
	for _, path := range paths {
		segments := strings.Split(path, ".")
		var current interface{} = payload
		for _, segment := range segments {
			mapValue, ok := current.(map[string]interface{})
			if !ok {
				current = nil
				break
			}
			current = mapValue[segment]
		}
		switch typed := current.(type) {
		case string:
			if trimmed := strings.TrimSpace(typed); trimmed != "" {
				return trimmed
			}
		case fmt.Stringer:
			if trimmed := strings.TrimSpace(typed.String()); trimmed != "" {
				return trimmed
			}
		}
	}
	return ""
}

func setIfEmpty(payload map[string]interface{}, key, value string) {
	if strings.TrimSpace(value) == "" {
		return
	}
	if existing := firstString(payload, key); existing == "" {
		payload[key] = value
	}
}

func cloneStringMap(payload map[string]interface{}) map[string]interface{} {
	cloned := make(map[string]interface{}, len(payload))
	for key, value := range payload {
		cloned[key] = value
	}
	return cloned
}

func firstString(payload map[string]interface{}, keys ...string) string {
	for _, key := range keys {
		if value, ok := payload[key]; ok {
			switch vv := value.(type) {
			case string:
				if trimmed := strings.TrimSpace(vv); trimmed != "" {
					return trimmed
				}
			case fmt.Stringer:
				if trimmed := strings.TrimSpace(vv.String()); trimmed != "" {
					return trimmed
				}
			}
		}
	}
	return ""
}

func firstInt(payload map[string]interface{}, fallback int, keys ...string) int {
	for _, key := range keys {
		if value, ok := payload[key]; ok {
			switch vv := value.(type) {
			case float64:
				if vv > 0 {
					return int(vv)
				}
			case int:
				if vv > 0 {
					return vv
				}
			case int64:
				if vv > 0 {
					return int(vv)
				}
			case string:
				var parsed int
				if _, err := fmt.Sscanf(strings.TrimSpace(vv), "%d", &parsed); err == nil && parsed > 0 {
					return parsed
				}
			}
		}
	}
	return fallback
}

func firstTime(payload map[string]interface{}, fallback time.Time, keys ...string) time.Time {
	for _, key := range keys {
		if value, ok := payload[key]; ok {
			switch vv := value.(type) {
			case string:
				trimmed := strings.TrimSpace(vv)
				if trimmed == "" {
					continue
				}
				if parsed, err := time.Parse(time.RFC3339, trimmed); err == nil {
					return parsed
				}
				if parsed, err := time.Parse("2006-01-02 15:04:05", trimmed); err == nil {
					return parsed
				}
			case float64:
				if vv > 0 {
					return time.Unix(int64(vv), 0)
				}
			case int64:
				if vv > 0 {
					return time.Unix(vv, 0)
				}
			}
		}
	}
	return fallback
}

func normalizeDeviceInfo(payload map[string]interface{}) string {
	if value, ok := payload["deviceInfo"]; ok {
		if bytes, err := json.Marshal(value); err == nil {
			return string(bytes)
		}
	}

	device := map[string]string{}
	for _, key := range []string{"deviceModel", "deviceBrand", "osVersion", "manufacturer"} {
		if value := firstString(payload, key); value != "" {
			device[key] = value
		}
	}
	if len(device) == 0 {
		return ""
	}
	bytes, err := json.Marshal(device)
	if err != nil {
		logger.Errorf("[SignalIngest] marshal device info failed: %v", err)
	}
	return string(bytes)
}

func firstLine(text string) string {
	text = strings.TrimSpace(text)
	if text == "" {
		return ""
	}
	lines := strings.Split(text, "\n")
	return truncateText(strings.TrimSpace(lines[0]), 200)
}

func truncateText(text string, limit int) string {
	if limit <= 0 {
		return ""
	}
	runes := []rune(strings.TrimSpace(text))
	if len(runes) <= limit {
		return string(runes)
	}
	return string(runes[:limit])
}

func mustMarshal(payload map[string]interface{}) string {
	bytes, err := json.Marshal(payload)
	if err != nil {
		logger.Errorf("[SignalIngest] marshal payload failed: %v", err)
	}
	return string(bytes)
}

func hashText(text string) string {
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:])
}
