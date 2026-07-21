package router

import (
	"bug-agent/internal/model"
	"net/http"
	"net/http/httptest"
	"testing"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func TestSetup_CORSAllowsLoopbackDevOrigins(t *testing.T) {
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	if err != nil {
		t.Fatalf("open sqlite: %v", err)
	}
	model.SetDB(db)

	r := Setup()

	req := httptest.NewRequest(http.MethodOptions, "/api/v1/auth/login", nil)
	req.Header.Set("Origin", "http://127.0.0.1:5688")
	req.Header.Set("Access-Control-Request-Method", http.MethodPost)
	req.Header.Set("Access-Control-Request-Headers", "Content-Type")

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusNoContent {
		t.Fatalf("expected 204 for loopback preflight, got %d body=%s", w.Code, w.Body.String())
	}

	if got := w.Header().Get("Access-Control-Allow-Origin"); got != "http://127.0.0.1:5688" {
		t.Fatalf("expected Access-Control-Allow-Origin to echo loopback origin, got %q", got)
	}
}
