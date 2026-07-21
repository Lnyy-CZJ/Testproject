package service

import (
	"bug-agent/internal/integration/aliyunlog"
	"bug-agent/internal/integration/bugly"
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net"
	"strings"
	"time"

	"gorm.io/gorm"
)

var ErrIntegrationConnectorConfigInvalid = errors.New("integration connector config invalid")
var ErrIntegrationConnectorHasSignals = errors.New("integration connector has signals")

type IntegrationConnectorInput struct {
	ProjectID uint
	Name      string
	Type      string
	Status    string
	Config    map[string]interface{}
}

type IntegrationConnectorView struct {
	ID             uint                   `json:"id"`
	ProjectID      uint                   `json:"projectId"`
	ProjectName    string                 `json:"projectName,omitempty"`
	Name           string                 `json:"name"`
	Type           string                 `json:"type"`
	Status         string                 `json:"status"`
	InboundToken   string                 `json:"inboundToken"`
	InboundPath    string                 `json:"inboundPath"`
	LastSyncAt     *time.Time             `json:"lastSyncAt,omitempty"`
	LastSyncStatus string                 `json:"lastSyncStatus,omitempty"`
	LastError      string                 `json:"lastError,omitempty"`
	LastErrorKind  string                 `json:"lastErrorKind,omitempty"`
	LastRetryable  bool                   `json:"lastErrorRetryable"`
	HealthStatus   string                 `json:"healthStatus,omitempty"`
	HealthSummary  string                 `json:"healthSummary,omitempty"`
	SupportsPull   bool                   `json:"supportsPull"`
	HasConfig      bool                   `json:"hasConfig"`
	Config         map[string]interface{} `json:"config,omitempty"`
	CreatedBy      uint                   `json:"createdBy"`
	CreatedAt      time.Time              `json:"createdAt"`
	UpdatedAt      time.Time              `json:"updatedAt"`
}

type IntegrationConnectorService struct {
	db     *gorm.DB
	crypto *CredentialService
	ingest *SignalIngestService
}

type ConnectorErrorDetail struct {
	Kind      string
	Message   string
	Retryable bool
}

func NewIntegrationConnectorService(db *gorm.DB, ingest *SignalIngestService) *IntegrationConnectorService {
	return &IntegrationConnectorService{
		db:     db,
		crypto: NewCredentialService(db),
		ingest: ingest,
	}
}

func (s *IntegrationConnectorService) List(projectID uint) ([]IntegrationConnectorView, error) {
	var connectors []model.IntegrationConnector
	if err := s.db.Preload("Project").
		Where("project_id = ?", projectID).
		Order("created_at desc, id desc").
		Find(&connectors).Error; err != nil {
		return nil, err
	}

	views := make([]IntegrationConnectorView, 0, len(connectors))
	for _, connector := range connectors {
		config, err := s.getDecryptedConfig(connector.ConfigEncrypted)
		if err != nil {
			logger.Warnf("[IntegrationConnector] decrypt connector config failed: connectorID=%d err=%v", connector.ID, err)
			view := toIntegrationConnectorView(connector, map[string]interface{}{})
			view.HealthStatus = "error"
			view.HealthSummary = "连接器配置无法读取，请重新保存配置"
			view.LastErrorKind = "config_invalid"
			view.LastRetryable = false
			views = append(views, view)
			continue
		}
		views = append(views, toIntegrationConnectorView(connector, redactConnectorConfig(connector.Type, config)))
	}
	return views, nil
}

func (s *IntegrationConnectorService) Create(projectID, createdBy uint, input IntegrationConnectorInput) (*IntegrationConnectorView, error) {
	input.ProjectID = projectID
	if err := s.validateInput(input); err != nil {
		return nil, err
	}

	configEncrypted, err := s.encryptConfig(input.Config)
	if err != nil {
		return nil, err
	}

	connector := model.IntegrationConnector{
		ProjectID:       input.ProjectID,
		Name:            strings.TrimSpace(input.Name),
		Type:            strings.TrimSpace(input.Type),
		Status:          normalizeConnectorStatus(input.Status),
		InboundToken:    "sig_" + generateRandomString(24),
		ConfigEncrypted: configEncrypted,
		CreatedBy:       createdBy,
	}

	if err := s.db.Create(&connector).Error; err != nil {
		return nil, err
	}
	if err := s.db.Preload("Project").First(&connector, connector.ID).Error; err != nil {
		return nil, err
	}

	view := toIntegrationConnectorView(connector, redactConnectorConfig(connector.Type, input.Config))
	return &view, nil
}

func (s *IntegrationConnectorService) Update(projectID, id uint, input IntegrationConnectorInput) (*IntegrationConnectorView, error) {
	connector, _, err := s.getConnectorWithConfig(projectID, id)
	if err != nil {
		return nil, err
	}

	input.ProjectID = projectID
	if strings.TrimSpace(input.Name) == "" {
		input.Name = connector.Name
	}
	if strings.TrimSpace(input.Type) == "" {
		input.Type = connector.Type
	}
	if strings.TrimSpace(input.Status) == "" {
		input.Status = connector.Status
	}

	if err := s.validateInput(input); err != nil {
		return nil, err
	}

	connector.ProjectID = input.ProjectID
	connector.Name = strings.TrimSpace(input.Name)
	connector.Type = strings.TrimSpace(input.Type)
	connector.Status = normalizeConnectorStatus(input.Status)

	if input.Config != nil {
		encrypted, err := s.encryptConfig(input.Config)
		if err != nil {
			return nil, err
		}
		connector.ConfigEncrypted = encrypted
	}

	if err := s.db.Save(&connector).Error; err != nil {
		return nil, err
	}
	if err := s.db.Preload("Project").First(connector, connector.ID).Error; err != nil {
		return nil, err
	}

	config, err := s.getDecryptedConfig(connector.ConfigEncrypted)
	if err != nil {
		return nil, err
	}
	view := toIntegrationConnectorView(*connector, redactConnectorConfig(connector.Type, config))
	return &view, nil
}

func (s *IntegrationConnectorService) Delete(projectID, id uint) error {
	return s.db.Transaction(func(tx *gorm.DB) error {
		var connector model.IntegrationConnector
		if err := tx.Where("project_id = ? AND id = ?", projectID, id).First(&connector).Error; err != nil {
			if errors.Is(err, gorm.ErrRecordNotFound) {
				return ErrIntegrationConnectorNotFound
			}
			return err
		}

		var signalCount int64
		if err := tx.Model(&model.IssueSignal{}).Where("connector_id = ?", id).Count(&signalCount).Error; err != nil {
			return err
		}
		if signalCount > 0 {
			return ErrIntegrationConnectorHasSignals
		}

		if err := tx.Where("connector_id = ?", id).Delete(&model.IntegrationSyncRecord{}).Error; err != nil {
			return err
		}

		result := tx.Delete(&model.IntegrationConnector{}, id)
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return ErrIntegrationConnectorNotFound
		}
		return nil
	})
}

func (s *IntegrationConnectorService) Test(projectID, id uint) (map[string]interface{}, error) {
	connector, config, err := s.getConnectorWithConfig(projectID, id)
	if err != nil {
		return nil, err
	}

	if strings.TrimSpace(connector.Name) == "" || strings.TrimSpace(connector.Type) == "" {
		return nil, ErrIntegrationConnectorConfigInvalid
	}

	if connector.Type != model.ConnectorTypeWebhook && len(config) == 0 {
		return nil, ErrIntegrationConnectorConfigInvalid
	}

	if connector.Type == model.ConnectorTypeBugly {
		if _, err := s.pullBuglyIssues(*connector, config); err != nil {
			return nil, err
		}
	}
	if connector.Type == model.ConnectorTypeAliyun {
		if _, err := s.pullAliyunLogs(config); err != nil {
			return nil, err
		}
	}

	return map[string]interface{}{
		"ok":            true,
		"type":          connector.Type,
		"supportsPull":  supportsPullConnectorType(connector.Type),
		"healthStatus":  "healthy",
		"healthSummary": "连接器配置有效",
		"inboundPath":   toIntegrationConnectorView(*connector, redactConnectorConfig(connector.Type, config)).InboundPath,
	}, nil
}

func (s *IntegrationConnectorService) Sync(projectID, id uint, items []map[string]interface{}) (map[string]interface{}, error) {
	connector, config, err := s.getConnectorWithConfig(projectID, id)
	if err != nil {
		return nil, err
	}
	if connector.Status != model.ConnectorStatusActive {
		return nil, ErrIntegrationConnectorInactive
	}

	if len(items) == 0 {
		switch connector.Type {
		case model.ConnectorTypeBugly:
			return s.syncBugly(*connector, config)
		case model.ConnectorTypeAliyun:
			return s.syncAliyunLog(*connector, config)
		}
		return map[string]interface{}{
			"importedCount":  0,
			"clusteredCount": 0,
			"syncRecordId":   0,
		}, nil
	}

	rawItems := make([]json.RawMessage, 0, len(items))
	for _, item := range items {
		bytes, err := json.Marshal(item)
		if err != nil {
			return nil, err
		}
		rawItems = append(rawItems, json.RawMessage(bytes))
	}
	_, clusters, syncRecord, err := s.ingest.IngestBatch(*connector, "manual_sync", rawItems, fmt.Sprintf("{\"items\":%d}", len(rawItems)))
	if err != nil {
		return nil, err
	}

	return map[string]interface{}{
		"importedCount":  syncRecord.ImportedCount,
		"clusteredCount": len(clusters),
		"syncRecordId":   syncRecord.ID,
		"supportsPull":   supportsPullConnectorType(connector.Type),
	}, nil
}

func (s *IntegrationConnectorService) ListSyncRecords(projectID, id uint) ([]model.IntegrationSyncRecord, error) {
	var count int64
	if err := s.db.Model(&model.IntegrationConnector{}).Where("project_id = ? AND id = ?", projectID, id).Count(&count).Error; err != nil {
		return nil, err
	}
	if count == 0 {
		return nil, ErrIntegrationConnectorNotFound
	}

	var records []model.IntegrationSyncRecord
	if err := s.db.Where("connector_id = ?", id).Order("created_at desc, id desc").Find(&records).Error; err != nil {
		return nil, err
	}
	return records, nil
}

func (s *IntegrationConnectorService) validateInput(input IntegrationConnectorInput) error {
	if input.ProjectID == 0 || strings.TrimSpace(input.Name) == "" || strings.TrimSpace(input.Type) == "" {
		return ErrIntegrationConnectorConfigInvalid
	}
	if normalizeConnectorStatus(input.Status) == "" {
		return ErrIntegrationConnectorConfigInvalid
	}
	if !isSupportedConnectorType(input.Type) {
		return ErrIntegrationConnectorConfigInvalid
	}
	return nil
}

func (s *IntegrationConnectorService) getConnectorWithConfig(projectID, id uint) (*model.IntegrationConnector, map[string]interface{}, error) {
	var connector model.IntegrationConnector
	if err := s.db.Preload("Project").Where("project_id = ? AND id = ?", projectID, id).First(&connector).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, nil, ErrIntegrationConnectorNotFound
		}
		return nil, nil, err
	}

	config := map[string]interface{}{}
	if strings.TrimSpace(connector.ConfigEncrypted) != "" {
		var err error
		config, err = s.getDecryptedConfig(connector.ConfigEncrypted)
		if err != nil {
			return nil, nil, err
		}
	}
	return &connector, config, nil
}

func (s *IntegrationConnectorService) getDecryptedConfig(encrypted string) (map[string]interface{}, error) {
	config := map[string]interface{}{}
	if strings.TrimSpace(encrypted) == "" {
		return config, nil
	}
	plaintext, err := s.crypto.decrypt(encrypted)
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal([]byte(plaintext), &config); err != nil {
		return nil, err
	}
	return config, nil
}

// ResolveConfig decrypts connector config payload for downstream runtime checks.
func (s *IntegrationConnectorService) ResolveConfig(connector model.IntegrationConnector) (map[string]interface{}, error) {
	return s.getDecryptedConfig(connector.ConfigEncrypted)
}

func (s *IntegrationConnectorService) encryptConfig(config map[string]interface{}) (string, error) {
	if config == nil {
		config = map[string]interface{}{}
	}
	bytes, err := json.Marshal(config)
	if err != nil {
		return "", err
	}
	return s.crypto.encrypt(string(bytes))
}

func toIntegrationConnectorView(connector model.IntegrationConnector, config map[string]interface{}) IntegrationConnectorView {
	var detail ConnectorErrorDetail
	if strings.TrimSpace(connector.LastError) != "" {
		detail = ExplainConnectorError(errors.New(connector.LastError))
	}
	healthStatus := "warning"
	healthSummary := "等待首次同步"
	switch connector.Status {
	case model.ConnectorStatusInactive:
		healthStatus = "inactive"
		healthSummary = "连接器已停用"
	case model.ConnectorStatusActive:
		if strings.TrimSpace(connector.LastSyncStatus) == model.SyncStatusSuccess {
			healthStatus = "healthy"
			healthSummary = "最近同步成功"
		} else if strings.TrimSpace(connector.LastSyncStatus) == model.SyncStatusFailed {
			healthStatus = "error"
			healthSummary = detail.Message
		} else if strings.TrimSpace(connector.ConfigEncrypted) == "" && supportsPullConnectorType(connector.Type) {
			healthStatus = "error"
			healthSummary = "连接器配置不完整"
		}
	}
	return IntegrationConnectorView{
		ID:             connector.ID,
		ProjectID:      connector.ProjectID,
		ProjectName:    connector.Project.Name,
		Name:           connector.Name,
		Type:           connector.Type,
		Status:         connector.Status,
		InboundToken:   connector.InboundToken,
		InboundPath:    fmt.Sprintf("/api/v1/inbound/connectors/%s", connector.InboundToken),
		LastSyncAt:     connector.LastSyncAt,
		LastSyncStatus: connector.LastSyncStatus,
		LastError:      connector.LastError,
		LastErrorKind:  detail.Kind,
		LastRetryable:  detail.Retryable,
		HealthStatus:   healthStatus,
		HealthSummary:  healthSummary,
		SupportsPull:   supportsPullConnectorType(connector.Type),
		HasConfig:      strings.TrimSpace(connector.ConfigEncrypted) != "",
		Config:         config,
		CreatedBy:      connector.CreatedBy,
		CreatedAt:      connector.CreatedAt,
		UpdatedAt:      connector.UpdatedAt,
	}
}

func (s *IntegrationConnectorService) syncBugly(connector model.IntegrationConnector, config map[string]interface{}) (map[string]interface{}, error) {
	items, err := s.pullBuglyIssues(connector, config)
	if err != nil {
		s.recordConnectorFailure(connector.ID, "bugly_pull", err)
		return nil, err
	}
	_, clusters, record, err := s.ingest.IngestBatch(connector, "bugly_pull", items, fmt.Sprintf("{\"source\":\"bugly\",\"items\":%d}", len(items)))
	if err != nil {
		return nil, err
	}
	return map[string]interface{}{
		"importedCount":  record.ImportedCount,
		"clusteredCount": len(clusters),
		"syncRecordId":   record.ID,
	}, nil
}

func (s *IntegrationConnectorService) syncAliyunLog(connector model.IntegrationConnector, config map[string]interface{}) (map[string]interface{}, error) {
	items, err := s.pullAliyunLogs(config)
	if err != nil {
		s.recordConnectorFailure(connector.ID, "aliyun_log_pull", err)
		return nil, err
	}

	_, clusters, record, err := s.ingest.IngestBatch(connector, "aliyun_log_pull", items, fmt.Sprintf("{\"source\":\"aliyun_log\",\"items\":%d}", len(items)))
	if err != nil {
		return nil, err
	}
	return map[string]interface{}{
		"importedCount":  record.ImportedCount,
		"clusteredCount": len(clusters),
		"syncRecordId":   record.ID,
	}, nil
}

func (s *IntegrationConnectorService) pullBuglyIssues(connector model.IntegrationConnector, config map[string]interface{}) ([]json.RawMessage, error) {
	endpoint := normalizeOptionalString(config["endpoint"])
	if endpoint == "" {
		return nil, ErrIntegrationConnectorConfigInvalid
	}
	client := bugly.NewClient(
		endpoint,
		normalizeOptionalString(firstConfigValue(config, "issuesPath", "path")),
		normalizeOptionalString(firstConfigValue(config, "appId", "productId")),
		normalizeOptionalString(firstConfigValue(config, "appKey", "productKey")),
		normalizeOptionalString(firstConfigValue(config, "apiToken", "token")),
	)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	return client.FetchIssues(ctx)
}

func (s *IntegrationConnectorService) recordConnectorFailure(connectorID uint, triggerType string, err error) {
	detail := ExplainConnectorError(err)
	now := time.Now()
	record := model.IntegrationSyncRecord{
		ConnectorID:    connectorID,
		TriggerType:    triggerType,
		Status:         model.SyncStatusFailed,
		ErrorKind:      detail.Kind,
		Retryable:      detail.Retryable,
		ErrorMessage:   err.Error(),
		StartedAt:      now,
		FinishedAt:     integrationTimePtr(now),
		CreatedAt:      now,
		ImportedCount:  0,
		ClusteredCount: 0,
	}
	if err := s.db.Create(&record).Error; err != nil {
		logger.Errorf("db operation failed: %v", err)
	}
	if err := s.db.Model(&model.IntegrationConnector{}).Where("id = ?", connectorID).Updates(map[string]interface{}{
		"last_sync_at":     now,
		"last_sync_status": model.SyncStatusFailed,
		"last_error":       err.Error(),
	}).Error; err != nil {
		logger.Errorf("更新连接器失败状态失败: %v", err)
	}
}

func (s *IntegrationConnectorService) pullAliyunLogs(config map[string]interface{}) ([]json.RawMessage, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	items, err := aliyunlog.FetchLogs(ctx, aliyunlog.FetchOptions{
		Endpoint:        normalizeOptionalString(firstConfigValue(config, "endpoint")),
		Project:         normalizeOptionalString(firstConfigValue(config, "project")),
		Logstore:        normalizeOptionalString(firstConfigValue(config, "logstore")),
		Query:           normalizeOptionalString(firstConfigValue(config, "query")),
		AccessKeyID:     normalizeOptionalString(firstConfigValue(config, "accessKeyId")),
		AccessKeySecret: normalizeOptionalString(firstConfigValue(config, "accessKeySecret")),
		SecurityToken:   normalizeOptionalString(firstConfigValue(config, "securityToken")),
		FromMinutes:     normalizeOptionalInt(firstConfigValue(config, "fromMinutes"), 15),
		ToDelaySeconds:  normalizeOptionalInt(firstConfigValue(config, "toDelaySeconds"), 60),
		Lines:           int64(normalizeOptionalInt(firstConfigValue(config, "lines"), 100)),
		Reverse:         normalizeOptionalBool(firstConfigValue(config, "reverse")),
	})
	if err != nil {
		return nil, aliyunlog.WrapError(err)
	}
	return items, nil
}

func supportsPullConnectorType(connectorType string) bool {
	switch strings.TrimSpace(connectorType) {
	case model.ConnectorTypeBugly, model.ConnectorTypeAliyun:
		return true
	default:
		return false
	}
}

func ExplainConnectorError(err error) ConnectorErrorDetail {
	if err == nil {
		return ConnectorErrorDetail{}
	}
	if errors.Is(err, ErrIntegrationConnectorConfigInvalid) ||
		errors.Is(err, bugly.ErrIssuesEndpointRequired) ||
		errors.Is(err, aliyunlog.ErrEndpointRequired) ||
		errors.Is(err, aliyunlog.ErrProjectRequired) ||
		errors.Is(err, aliyunlog.ErrLogstoreRequired) ||
		errors.Is(err, aliyunlog.ErrAccessKeyIDRequired) ||
		errors.Is(err, aliyunlog.ErrAccessKeySecretRequired) {
		return ConnectorErrorDetail{Kind: "config_invalid", Message: "连接器配置不完整", Retryable: false}
	}
	if errors.Is(err, ErrIntegrationConnectorInactive) {
		return ConnectorErrorDetail{Kind: "inactive", Message: "连接器未启用", Retryable: false}
	}
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return ConnectorErrorDetail{Kind: "network_timeout", Message: "请求第三方服务超时", Retryable: true}
	}

	lower := strings.ToLower(strings.TrimSpace(err.Error()))
	switch {
	case strings.Contains(lower, "401"), strings.Contains(lower, "403"), strings.Contains(lower, "unauthorized"), strings.Contains(lower, "forbidden"), strings.Contains(lower, "invalid token"), strings.Contains(lower, "signature"):
		return ConnectorErrorDetail{Kind: "auth_failed", Message: "连接器认证失败，请检查令牌或密钥", Retryable: false}
	case strings.Contains(lower, "429"), strings.Contains(lower, "rate"), strings.Contains(lower, "throttl"):
		return ConnectorErrorDetail{Kind: "rate_limited", Message: "第三方接口限流，请稍后重试", Retryable: true}
	case strings.Contains(lower, "timeout"), strings.Contains(lower, "deadline exceeded"):
		return ConnectorErrorDetail{Kind: "network_timeout", Message: "请求第三方服务超时", Retryable: true}
	case strings.Contains(lower, "500"), strings.Contains(lower, "502"), strings.Contains(lower, "503"), strings.Contains(lower, "upstream"):
		return ConnectorErrorDetail{Kind: "upstream_error", Message: "第三方服务异常，请稍后重试", Retryable: true}
	case strings.Contains(lower, "does not contain issue items"), strings.Contains(lower, "invalid character"), strings.Contains(lower, "bad request"):
		return ConnectorErrorDetail{Kind: "payload_invalid", Message: "第三方返回数据格式异常", Retryable: false}
	default:
		return ConnectorErrorDetail{Kind: "unknown", Message: truncateText(strings.TrimSpace(err.Error()), 255), Retryable: false}
	}
}

func isSupportedConnectorType(connectorType string) bool {
	switch strings.TrimSpace(connectorType) {
	case model.ConnectorTypeWebhook, model.ConnectorTypeBugly, model.ConnectorTypeDingTalk, model.ConnectorTypeFeishu, model.ConnectorTypeAliyun:
		return true
	default:
		return false
	}
}

func firstConfigValue(config map[string]interface{}, keys ...string) interface{} {
	for _, key := range keys {
		if value, ok := config[key]; ok {
			return value
		}
	}
	return nil
}

func normalizeOptionalString(value interface{}) string {
	switch typed := value.(type) {
	case string:
		return strings.TrimSpace(typed)
	case fmt.Stringer:
		return strings.TrimSpace(typed.String())
	default:
		return ""
	}
}

func normalizeOptionalInt(value interface{}, fallback int) int {
	switch typed := value.(type) {
	case int:
		if typed > 0 {
			return typed
		}
	case int64:
		if typed > 0 {
			return int(typed)
		}
	case float64:
		if typed > 0 {
			return int(typed)
		}
	case string:
		trimmed := strings.TrimSpace(typed)
		if trimmed == "" {
			return fallback
		}
		var parsed int
		if _, err := fmt.Sscanf(trimmed, "%d", &parsed); err == nil && parsed > 0 {
			return parsed
		}
	}
	return fallback
}

func normalizeOptionalBool(value interface{}) bool {
	switch typed := value.(type) {
	case bool:
		return typed
	case string:
		return strings.EqualFold(strings.TrimSpace(typed), "true")
	default:
		return false
	}
}

func redactConnectorConfig(connectorType string, config map[string]interface{}) map[string]interface{} {
	if len(config) == 0 {
		return map[string]interface{}{}
	}
	view := map[string]interface{}{}
	for key, value := range config {
		view[key] = value
	}
	switch connectorType {
	case model.ConnectorTypeBugly:
		maskKeys(view, "appKey", "apiToken", "token", "productKey")
	case model.ConnectorTypeAliyun:
		maskKeys(view, "accessKeySecret", "securityToken")
	case model.ConnectorTypeDingTalk, model.ConnectorTypeFeishu:
		maskKeys(view, "secret", "signingSecret", "verificationToken")
	}
	return view
}

func maskKeys(config map[string]interface{}, keys ...string) {
	for _, key := range keys {
		if value, ok := config[key]; ok && normalizeOptionalString(value) != "" {
			config[key] = "__configured__"
		}
	}
}

func normalizeConnectorStatus(status string) string {
	switch strings.TrimSpace(status) {
	case "", model.ConnectorStatusActive:
		return model.ConnectorStatusActive
	case model.ConnectorStatusInactive:
		return model.ConnectorStatusInactive
	default:
		return ""
	}
}

func integrationTimePtr(v time.Time) *time.Time {
	return &v
}

func generateRandomString(length int) string {
	if length <= 0 {
		return ""
	}
	const alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	var builder strings.Builder
	builder.Grow(length)
	max := big.NewInt(int64(len(alphabet)))
	for i := 0; i < length; i++ {
		n, err := rand.Int(rand.Reader, max)
		if err != nil {
			entropy := make([]byte, length)
			if _, readErr := rand.Read(entropy); readErr == nil {
				builder.WriteByte(alphabet[int(entropy[i])%len(alphabet)])
				continue
			}
			return ""
		}
		builder.WriteByte(alphabet[n.Int64()])
	}
	return builder.String()
}
