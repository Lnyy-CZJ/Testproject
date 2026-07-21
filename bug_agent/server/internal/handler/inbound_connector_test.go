package handler

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestInboundConnectorHandler_WebhookCreatesSignalAndCluster(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)

	user := testutil.CreateTestUser(t, db, "signal_inbound_owner")
	project := testutil.CreateTestProject(t, db, "Signal Intake", "SIGIN")

	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Webhook Inbound",
		Type:         model.ConnectorTypeWebhook,
		Status:       model.ConnectorStatusActive,
		InboundToken: "tok_123",
		CreatedBy:    user.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	svc := service.NewSignalIngestService(db)
	h := NewInboundConnectorHandler(db, svc)
	r := gin.New()
	r.POST("/inbound/connectors/:token", h.Receive)

	body := `{"eventId":"evt-1","title":"启动崩溃","description":"app启动后闪退","platform":"android","appVersion":"1.0.0","fingerprint":"fp-1","occurrenceCount":3,"affectedUserCount":2}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/inbound/connectors/tok_123", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var signals []model.IssueSignal
	if err := db.Find(&signals).Error; err != nil {
		t.Fatalf("query signals failed: %v", err)
	}
	if len(signals) != 1 {
		t.Fatalf("expected 1 signal, got %d", len(signals))
	}
	if signals[0].ClusterID == nil {
		t.Fatalf("expected signal cluster id to be populated")
	}

	var clusters []model.IssueCluster
	if err := db.Find(&clusters).Error; err != nil {
		t.Fatalf("query clusters failed: %v", err)
	}
	if len(clusters) != 1 {
		t.Fatalf("expected 1 cluster, got %d", len(clusters))
	}
	if clusters[0].SignalCount != 1 {
		t.Fatalf("expected cluster signal count 1, got %d", clusters[0].SignalCount)
	}

	var syncRecords []model.IntegrationSyncRecord
	if err := db.Find(&syncRecords).Error; err != nil {
		t.Fatalf("query sync records failed: %v", err)
	}
	if len(syncRecords) != 1 {
		t.Fatalf("expected 1 sync record, got %d", len(syncRecords))
	}
}

func TestInboundConnectorHandler_FeishuChallenge(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)

	user := testutil.CreateTestUser(t, db, "signal_feishu_owner")
	project := testutil.CreateTestProject(t, db, "Signal Feishu", "SIGFS")

	connector := model.IntegrationConnector{
		ProjectID:    project.ID,
		Name:         "Feishu Inbound",
		Type:         model.ConnectorTypeFeishu,
		Status:       model.ConnectorStatusActive,
		InboundToken: "tok_feishu",
		CreatedBy:    user.ID,
	}
	if err := db.Create(&connector).Error; err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	h := NewInboundConnectorHandler(db, service.NewSignalIngestService(db))
	r := gin.New()
	r.POST("/inbound/connectors/:token", h.Receive)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/inbound/connectors/tok_feishu", bytes.NewBufferString(`{"challenge":"challenge-demo","type":"url_verification"}`))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}
	if body := w.Body.String(); body == "" || !bytes.Contains([]byte(body), []byte("challenge-demo")) {
		t.Fatalf("expected challenge response body, got %s", body)
	}

	var count int64
	if err := db.Model(&model.IssueSignal{}).Count(&count).Error; err != nil {
		t.Fatalf("count signals failed: %v", err)
	}
	if count != 0 {
		t.Fatalf("expected no signal to be created for challenge, got %d", count)
	}
}

func TestInboundConnectorHandler_WebhookSignatureValidation(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)

	user := testutil.CreateTestUser(t, db, "signal_webhook_sig_owner")
	project := testutil.CreateTestProject(t, db, "Signal Signed", "SIGNS")
	ingestSvc := service.NewSignalIngestService(db)
	connectorSvc := service.NewIntegrationConnectorService(db, ingestSvc)
	view, err := connectorSvc.Create(project.ID, user.ID, service.IntegrationConnectorInput{
		Name:   "Signed Webhook",
		Type:   model.ConnectorTypeWebhook,
		Status: model.ConnectorStatusActive,
		Config: map[string]interface{}{
			"secret": "unit-test-secret",
		},
	})
	if err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	h := NewInboundConnectorHandler(db, ingestSvc)
	r := gin.New()
	r.POST("/inbound/connectors/:token", h.Receive)

	body := `{"eventId":"evt-sign-1","title":"签名校验","description":"签名通过后写入","platform":"android","fingerprint":"sig-ok"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/inbound/connectors/"+view.InboundToken, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Hub-Signature-256", buildWebhookSignature("unit-test-secret", []byte(body)))
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}
}

func TestInboundConnectorHandler_WebhookSignatureRejectsInvalid(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupHandlerTestDB(t)

	user := testutil.CreateTestUser(t, db, "signal_webhook_sig_invalid_owner")
	project := testutil.CreateTestProject(t, db, "Signal Signed Invalid", "SIGNI")
	ingestSvc := service.NewSignalIngestService(db)
	connectorSvc := service.NewIntegrationConnectorService(db, ingestSvc)
	view, err := connectorSvc.Create(project.ID, user.ID, service.IntegrationConnectorInput{
		Name:   "Signed Webhook Invalid",
		Type:   model.ConnectorTypeWebhook,
		Status: model.ConnectorStatusActive,
		Config: map[string]interface{}{
			"secret": "unit-test-secret",
		},
	})
	if err != nil {
		t.Fatalf("create connector failed: %v", err)
	}

	h := NewInboundConnectorHandler(db, ingestSvc)
	r := gin.New()
	r.POST("/inbound/connectors/:token", h.Receive)

	body := `{"eventId":"evt-sign-2","title":"签名校验","description":"签名失败应拒绝","platform":"android","fingerprint":"sig-bad"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/inbound/connectors/"+view.InboundToken, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Hub-Signature-256", "sha256=ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d: %s", w.Code, w.Body.String())
	}
}

func buildWebhookSignature(secret string, body []byte) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return "sha256=" + hex.EncodeToString(mac.Sum(nil))
}
