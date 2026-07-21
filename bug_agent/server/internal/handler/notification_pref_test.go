package handler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestNotificationPrefHandler_GetPreferences(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "pref_h_get")

	h := NewNotificationPrefHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.GET("/prefs", h.GetPreferences)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/prefs", nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].([]interface{})
	if len(data) != 8 {
		t.Errorf("Expected 8 default prefs, got %d", len(data))
	}
}

func TestNotificationPrefHandler_UpdatePreference(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "pref_h_update")

	h := NewNotificationPrefHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.GET("/prefs", h.GetPreferences)
	r.PUT("/prefs", h.UpdatePreference)

	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest("GET", "/prefs", nil)
	r.ServeHTTP(w1, req1)

	var resp1 map[string]interface{}
	json.Unmarshal(w1.Body.Bytes(), &resp1)
	prefs := resp1["data"].([]interface{})
	first := prefs[0].(map[string]interface{})
	pid := uint(first["id"].(float64))

	body := fmt.Sprintf(`{"id":%d,"channels":"webhook"}`, pid)
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest("PUT", "/prefs", bytes.NewReader([]byte(body)))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)

	if w2.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w2.Code, w2.Body.String())
	}
	var resp2 map[string]interface{}
	json.Unmarshal(w2.Body.Bytes(), &resp2)
	data := resp2["data"].(map[string]interface{})
	if data["channels"] != "webhook" {
		t.Errorf("Channels not updated: %v", data["channels"])
	}
}

func TestNotificationPrefHandler_BatchUpdate(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "pref_h_batch")

	h := NewNotificationPrefHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.PUT("/prefs/batch", h.BatchUpdate)

	body := `{"updates":{"defect_status_change":"webhook","defect_assigned":""}}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/prefs/batch", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}
}

func TestNotificationPrefHandler_BatchUpdate_RejectsInvalidCategory(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "pref_h_invalid")

	h := NewNotificationPrefHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.PUT("/prefs/batch", h.BatchUpdate)

	body := `{"updates":{"legacy_status":"webhook"}}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/prefs/batch", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 400 {
		t.Fatalf("Expected 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestNotificationPrefHandler_PersonalWebhookLifecycle(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "pref_h_webhook")

	h := NewNotificationPrefHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.GET("/prefs/webhook", h.GetWebhookSettings)
	r.PUT("/prefs/webhook", h.UpdateWebhookSettings)

	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest("GET", "/prefs/webhook", nil)
	r.ServeHTTP(w1, req1)
	if w1.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w1.Code, w1.Body.String())
	}

	body := `{"url":"https://example.com/user-hook","secret":"hook-secret","enabled":true}`
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest("PUT", "/prefs/webhook", bytes.NewReader([]byte(body)))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)
	if w2.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w2.Code, w2.Body.String())
	}
	var resp map[string]interface{}
	json.Unmarshal(w2.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["url"] != "https://example.com/user-hook" {
		t.Fatalf("url not saved: %v", data["url"])
	}
	if data["enabled"] != true {
		t.Fatalf("enabled not saved: %v", data["enabled"])
	}
	if data["secretConfigured"] != true {
		t.Fatalf("secretConfigured should be true: %v", data["secretConfigured"])
	}
}

func TestNotificationPrefHandler_TestPersonalWebhook(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "pref_h_webhook_test")

	called := false
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))
	defer upstream.Close()

	h := NewNotificationPrefHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.POST("/prefs/webhook/test", h.TestWebhookSettings)

	body := fmt.Sprintf(`{"url":"%s","secret":"hook-secret","enabled":true}`, upstream.URL)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/prefs/webhook/test", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}
	if !called {
		t.Fatal("expected personal webhook test request")
	}
}

func TestNotificationPrefHandler_TestPersonalWebhook_RejectsInvalidRequest(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "pref_h_webhook_invalid")

	h := NewNotificationPrefHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.POST("/prefs/webhook/test", h.TestWebhookSettings)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/prefs/webhook/test", bytes.NewReader([]byte(`{"enabled":true}`)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("Expected 400, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	if resp["message"] != "webhook url is required" {
		t.Fatalf("unexpected error message: %v", resp["message"])
	}
}

func TestNotificationPrefHandler_TestPersonalWebhook_ReturnsBadGatewayOnDispatchFailure(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "pref_h_webhook_failed")

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer upstream.Close()

	h := NewNotificationPrefHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.POST("/prefs/webhook/test", h.TestWebhookSettings)

	body := fmt.Sprintf(`{"url":"%s","enabled":true}`, upstream.URL)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/prefs/webhook/test", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != http.StatusBadGateway {
		t.Fatalf("Expected 502, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	if resp["code"] != float64(http.StatusBadGateway) {
		t.Fatalf("unexpected response code: %v", resp["code"])
	}
	if resp["message"] == "" {
		t.Fatal("expected error message")
	}
}
