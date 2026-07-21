package service_test

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestSignalModels_AutoMigrateCoreTables(t *testing.T) {
	db := setupServiceTestDB(t)
	tables := []string{
		"integration_connectors",
		"integration_sync_records",
		"issue_signals",
		"issue_clusters",
		"issue_triage_records",
	}

	for _, table := range tables {
		if !db.Migrator().HasTable(table) {
			t.Fatalf("expected table %s to exist", table)
		}
	}
}

func TestSignalIngestService_NormalizeDingTalkTextMessage(t *testing.T) {
	svc := service.NewSignalIngestService(nil)

	normalized, err := svc.NormalizePayload(model.IntegrationConnector{
		ID:   7,
		Type: model.ConnectorTypeDingTalk,
	}, map[string]interface{}{
		"msgtype": "text",
		"text": map[string]interface{}{
			"content": "启动崩溃\n用户打开 App 后立即闪退\n平台: android\n版本: 1.2.3",
		},
	})
	if err != nil {
		t.Fatalf("normalize dingtalk payload failed: %v", err)
	}

	if normalized.Title != "启动崩溃" {
		t.Fatalf("expected title from first line, got %q", normalized.Title)
	}
	if normalized.SourceType != model.ConnectorTypeDingTalk {
		t.Fatalf("expected source type dingtalk, got %q", normalized.SourceType)
	}
	if normalized.Description == "" {
		t.Fatalf("expected description to be populated")
	}
}

func TestSignalIngestService_NormalizeFeishuMessageContent(t *testing.T) {
	svc := service.NewSignalIngestService(nil)
	messageContent, _ := json.Marshal(map[string]string{
		"text": "登录后白屏\n用户进入首页后页面空白",
	})

	normalized, err := svc.NormalizePayload(model.IntegrationConnector{
		ID:   8,
		Type: model.ConnectorTypeFeishu,
	}, map[string]interface{}{
		"event": map[string]interface{}{
			"message": map[string]interface{}{
				"message_id": "om_123",
				"content":    string(messageContent),
			},
		},
	})
	if err != nil {
		t.Fatalf("normalize feishu payload failed: %v", err)
	}

	if normalized.SourceEventID != "om_123" {
		t.Fatalf("expected source event id om_123, got %q", normalized.SourceEventID)
	}
	if normalized.Title != "登录后白屏" {
		t.Fatalf("expected title from feishu text, got %q", normalized.Title)
	}
	if normalized.Description == "" {
		t.Fatalf("expected description to be populated")
	}
}

func TestSignalIngestService_NormalizeAliyunLogPayload(t *testing.T) {
	svc := service.NewSignalIngestService(nil)

	normalized, err := svc.NormalizePayload(model.IntegrationConnector{
		ID:   9,
		Type: model.ConnectorTypeAliyun,
	}, map[string]interface{}{
		"event_id":       "sls-evt-1",
		"message":        "支付确认页闪退\njava.lang.IllegalStateException: boom",
		"stack":          "java.lang.IllegalStateException: boom\n\tat checkout.ConfirmActivity.onCreate(ConfirmActivity.kt:42)",
		"level":          "fatal",
		"app_version":    "6.2.1",
		"build_number":   "6201001",
		"platform":       "android",
		"device_model":   "Pixel 8",
		"fingerprint":    "aliyun-fp-1",
		"count":          "9",
		"affected_users": "4",
		"__time__":       "2026-04-12 10:11:12",
	})
	if err != nil {
		t.Fatalf("normalize aliyun log payload failed: %v", err)
	}

	if normalized.SourceType != model.ConnectorTypeAliyun {
		t.Fatalf("expected source type aliyun_log, got %q", normalized.SourceType)
	}
	if normalized.SourceEventID != "sls-evt-1" {
		t.Fatalf("expected event id sls-evt-1, got %q", normalized.SourceEventID)
	}
	if normalized.Title != "支付确认页闪退" {
		t.Fatalf("expected title from message first line, got %q", normalized.Title)
	}
	if normalized.AppVersion != "6.2.1" {
		t.Fatalf("expected app version 6.2.1, got %q", normalized.AppVersion)
	}
	if normalized.BuildNumber != "6201001" {
		t.Fatalf("expected build number 6201001, got %q", normalized.BuildNumber)
	}
	if normalized.RawSeverity != "fatal" {
		t.Fatalf("expected severity fatal, got %q", normalized.RawSeverity)
	}
	if normalized.OccurrenceCount != 9 {
		t.Fatalf("expected occurrence count 9, got %d", normalized.OccurrenceCount)
	}
	if normalized.AffectedUserCount != 4 {
		t.Fatalf("expected affected user count 4, got %d", normalized.AffectedUserCount)
	}
	if !normalized.LastSeenAt.Equal(time.Date(2026, 4, 12, 10, 11, 12, 0, time.UTC)) &&
		!normalized.LastSeenAt.Equal(time.Date(2026, 4, 12, 10, 11, 12, 0, time.Local)) {
		t.Fatalf("expected last seen time parsed from __time__, got %s", normalized.LastSeenAt.Format(time.RFC3339))
	}
	if !strings.Contains(normalized.DeviceInfoJSON, "Pixel 8") {
		t.Fatalf("expected device info to include device model, got %q", normalized.DeviceInfoJSON)
	}
	if !strings.Contains(normalized.LogExcerpt, "支付确认页闪退") {
		t.Fatalf("expected log excerpt to include message, got %q", normalized.LogExcerpt)
	}
}
