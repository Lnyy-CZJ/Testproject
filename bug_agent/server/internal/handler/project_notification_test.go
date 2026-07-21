package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func setupProjectNotificationRouter(t testing.TB) (*gin.Engine, uint) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "project_notification_owner")
	project := testutil.CreateTestProject(t, db, "Project Notification", "PNOTI")

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", user.ID)
		c.Next()
	})
	return r, project.ID
}

func TestProjectNotificationHandler_GetPolicies_Defaults(t *testing.T) {
	r, projectID := setupProjectNotificationRouter(t)

	h := NewProjectNotificationHandler(model.DB)
	r.GET("/projects/:id/notification-policies", h.GetPolicies)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(projectID)+"/notification-policies", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	items := resp["data"].([]interface{})
	if len(items) != 7 {
		t.Fatalf("expected 7 default policies, got %d", len(items))
	}
}

func TestProjectNotificationHandler_BatchUpdatePolicies(t *testing.T) {
	r, projectID := setupProjectNotificationRouter(t)

	webhook := model.ProjectWebhook{
		ProjectID: projectID,
		Name:      "Feishu",
		URL:       "https://example.com/webhook",
		Secret:    "secret-1",
		Enabled:   true,
	}
	if err := model.DB.Create(&webhook).Error; err != nil {
		t.Fatalf("create webhook failed: %v", err)
	}

	h := NewProjectNotificationHandler(model.DB)
	r.PUT("/projects/:id/notification-policies", h.BatchUpdatePolicies)

	body := `{"policies":[{"category":"defect_mention","inAppEnabled":true,"emailEnabled":false,"webhookId":` + toStrUint(webhook.ID) + `}]}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPut, "/projects/"+toStrUint(projectID)+"/notification-policies", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var policy model.ProjectNotificationPolicy
	if err := model.DB.Where("project_id = ? AND category = ?", projectID, "defect_mention").First(&policy).Error; err != nil {
		t.Fatalf("query updated policy failed: %v", err)
	}
	if policy.EmailEnabled {
		t.Fatalf("expected email disabled")
	}
	if policy.WebhookID == nil || *policy.WebhookID != webhook.ID {
		t.Fatalf("expected webhook id %d, got %v", webhook.ID, policy.WebhookID)
	}
}

func TestProjectNotificationHandler_WebhookCRUDAndTest(t *testing.T) {
	r, projectID := setupProjectNotificationRouter(t)

	var receivedSecret string
	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		receivedSecret = req.Header.Get("X-Webhook-Secret")
		w.WriteHeader(http.StatusOK)
	}))
	defer mockServer.Close()

	h := NewProjectNotificationHandler(model.DB)
	r.POST("/projects/:id/notification-webhooks", h.CreateWebhook)
	r.GET("/projects/:id/notification-webhooks", h.ListWebhooks)
	r.POST("/projects/:id/notification-webhooks/:webhookId/test", h.TestWebhook)

	createBody := `{"name":"Slack","url":"` + mockServer.URL + `","secret":"hook-secret","enabled":true}`
	createResp := httptest.NewRecorder()
	createReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(projectID)+"/notification-webhooks", bytes.NewBufferString(createBody))
	createReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(createResp, createReq)
	if createResp.Code != http.StatusCreated {
		t.Fatalf("create webhook expected 201, got %d: %s", createResp.Code, createResp.Body.String())
	}

	var createPayload map[string]interface{}
	_ = json.Unmarshal(createResp.Body.Bytes(), &createPayload)
	webhookID := uint(createPayload["data"].(map[string]interface{})["id"].(float64))

	listResp := httptest.NewRecorder()
	listReq, _ := http.NewRequest(http.MethodGet, "/projects/"+toStrUint(projectID)+"/notification-webhooks", nil)
	r.ServeHTTP(listResp, listReq)
	if listResp.Code != http.StatusOK {
		t.Fatalf("list webhook expected 200, got %d: %s", listResp.Code, listResp.Body.String())
	}

	testResp := httptest.NewRecorder()
	testReq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(projectID)+"/notification-webhooks/"+toStrUint(webhookID)+"/test", bytes.NewBufferString(`{"event":"project_notification_test"}`))
	testReq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(testResp, testReq)
	if testResp.Code != http.StatusOK {
		t.Fatalf("test webhook expected 200, got %d: %s", testResp.Code, testResp.Body.String())
	}
	if receivedSecret != "hook-secret" {
		t.Fatalf("expected webhook secret header, got %q", receivedSecret)
	}
}
