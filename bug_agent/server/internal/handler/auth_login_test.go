package handler

import (
	"bytes"
	"database/sql"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestAuthHandler_Login_ReturnsMustChangePassword(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	hashed, err := model.HashPassword("login-password-123")
	if err != nil {
		t.Fatalf("hash password failed: %v", err)
	}
	user := model.User{
		Username:           "login_flag_user",
		Email:              "login_flag_user@test.com",
		Password:           hashed,
		MustChangePassword: true,
	}
	if err := db.Create(&user).Error; err != nil {
		t.Fatalf("create user failed: %v", err)
	}

	h := NewAuthHandler(model.DB)
	r := gin.New()
	r.POST("/login", h.Login)

	body := `{"username":"login_flag_user","password":"login-password-123"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/login", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}
	if !bytes.Contains(w.Body.Bytes(), []byte(`"mustChangePassword":true`)) {
		t.Fatalf("expected mustChangePassword=true in login response: %s", w.Body.String())
	}
}

func TestAuthHandler_Login_UpdatesLastLoginAt(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	hashed, err := model.HashPassword("login-time-password-123")
	if err != nil {
		t.Fatalf("hash password failed: %v", err)
	}
	user := model.User{
		Username: "login_time_user",
		Email:    "login_time_user@test.com",
		Password: hashed,
	}
	if err := db.Create(&user).Error; err != nil {
		t.Fatalf("create user failed: %v", err)
	}

	h := NewAuthHandler(model.DB)
	r := gin.New()
	r.POST("/login", h.Login)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/login", bytes.NewBufferString(`{"username":"login_time_user","password":"login-time-password-123"}`))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var lastLoginAt sql.NullTime
	if err := db.Raw("SELECT last_login_at FROM users WHERE id = ?", user.ID).Scan(&lastLoginAt).Error; err != nil {
		t.Fatalf("query last_login_at failed: %v", err)
	}
	if !lastLoginAt.Valid {
		t.Fatalf("expected last_login_at to be populated after login")
	}
	if !bytes.Contains(w.Body.Bytes(), []byte(`"lastLoginAt"`)) {
		t.Fatalf("expected lastLoginAt in login response: %s", w.Body.String())
	}
}
