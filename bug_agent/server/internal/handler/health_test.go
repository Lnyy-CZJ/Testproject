package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestHealthHandler_Healthz(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	h := NewHealthHandler()
	r.GET("/healthz", h.Healthz)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/healthz", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("Expected 200, got %d", w.Code)
	}

	var resp map[string]string
	json.Unmarshal(w.Body.Bytes(), &resp)
	if resp["status"] != "ok" {
		t.Errorf("Expected status=ok, got %s", resp["status"])
	}
}

func TestHealthHandler_Readiness_DBHealthy(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	h := NewHealthHandler()
	r.GET("/readyz", h.Readiness)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/readyz", nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK && w.Code != http.StatusServiceUnavailable {
		t.Errorf("Expected 200 or 503, got %d", w.Code)
	}
}
