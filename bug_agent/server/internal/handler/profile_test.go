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

func setupProfileTestRouter(t testing.TB) (*gin.Engine, *model.User) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "profile_user")

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", user.ID)
		c.Next()
	})
	return r, &user
}

func TestGetProfile_Success(t *testing.T) {
	r, user := setupProfileTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.GET("/test-profile", h.GetProfile)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test-profile", nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})

	if data["username"] != "profile_user" {
		t.Errorf("Expected username 'profile_user', got %v", data["username"])
	}
	if data["id"].(float64) != float64(user.ID) {
		t.Errorf("Expected ID %d, got %v", user.ID, data["id"])
	}
}

func TestUpdateProfile_Nickname(t *testing.T) {
	r, _ := setupProfileTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.PUT("/test-profile", h.UpdateProfile)

	body := `{"nickname":"NewNickname"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/test-profile", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["nickname"] != "NewNickname" {
		t.Errorf("Nickname not updated: %v", data["nickname"])
	}
}

func TestUpdateProfile_Avatar(t *testing.T) {
	r, _ := setupProfileTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.PUT("/test-profile", h.UpdateProfile)

	body := `{"avatar":"https://example.com/avatar.png"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/test-profile", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["avatar"] != "https://example.com/avatar.png" {
		t.Errorf("Avatar not updated: %v", data["avatar"])
	}
}

func TestUpdateProfile_AgentTypes(t *testing.T) {
	r, _ := setupProfileTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.PUT("/test-profile", h.UpdateProfile)

	body := `{"agentTypes":"product,backend,test"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/test-profile", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["agentTypes"] != "product,backend,test" {
		t.Errorf("AgentTypes not updated: %v", data["agentTypes"])
	}
}

func TestUpdateProfile_MultipleFields(t *testing.T) {
	r, _ := setupProfileTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.PUT("/test-profile", h.UpdateProfile)

	body := `{"nickname":"Multi","avatar":"https://img.com/pic.jpg","agentTypes":"ui,frontend"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/test-profile", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["nickname"] != "Multi" {
		t.Errorf("Nickname mismatch: %v", data["nickname"])
	}
	if data["avatar"] != "https://img.com/pic.jpg" {
		t.Errorf("Avatar mismatch: %v", data["avatar"])
	}
	if data["agentTypes"] != "ui,frontend" {
		t.Errorf("AgentTypes mismatch: %v", data["agentTypes"])
	}
}

func TestUpdateUserAgentTypes_Success(t *testing.T) {
	r, user := setupProfileTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.PUT("/test-users/:id/agent-types", h.UpdateUserAgentTypes)

	body := `{"agentTypes":["product","frontend","test"]}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/test-users/"+fmt.Sprintf("%d", user.ID)+"/agent-types", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["agentTypes"] != "product,frontend,test" {
		t.Errorf("AgentTypes mismatch: %v", data["agentTypes"])
	}
}

func TestUpdateUserAgentTypes_InvalidType(t *testing.T) {
	r, user := setupProfileTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.PUT("/test-users/:id/agent-types", h.UpdateUserAgentTypes)

	body := `{"agentTypes":["product","hacker"]}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/test-users/"+fmt.Sprintf("%d", user.ID)+"/agent-types", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 400 {
		t.Errorf("Invalid agent type should return 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestGetProfile_PersistedChanges(t *testing.T) {
	r, _ := setupProfileTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.PUT("/test-profile", h.UpdateProfile)
	r.GET("/test-profile", h.GetProfile)

	updateBody := `{"nickname":"PersistedNick"}`
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest("PUT", "/test-profile", bytes.NewReader([]byte(updateBody)))
	req1.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w1, req1)

	if w1.Code != 200 {
		t.Fatalf("Update failed: %d", w1.Code)
	}

	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest("GET", "/test-profile", nil)
	r.ServeHTTP(w2, req2)

	var resp map[string]interface{}
	json.Unmarshal(w2.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["nickname"] != "PersistedNick" {
		t.Errorf("Nickname should persist, got: %v", data["nickname"])
	}
}

func TestChangeMyPassword_Success(t *testing.T) {
	r, user := setupProfileTestRouter(t)

	hashed, err := model.HashPassword("old-password-123")
	if err != nil {
		t.Fatalf("failed to hash old password: %v", err)
	}
	if err := model.DB.Model(&model.User{}).Where("id = ?", user.ID).Update("password", hashed).Error; err != nil {
		t.Fatalf("failed to seed password: %v", err)
	}

	h := NewAuthHandler(model.DB)
	r.PUT("/test-profile/password", h.ChangeMyPassword)

	body := `{"currentPassword":"old-password-123","newPassword":"new-password-456"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/test-profile/password", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var updated model.User
	if err := model.DB.First(&updated, user.ID).Error; err != nil {
		t.Fatalf("failed to reload user: %v", err)
	}
	if !model.CheckPassword("new-password-456", updated.Password) {
		t.Fatalf("expected stored password to be updated")
	}
}

func TestChangeMyPassword_ClearsMustChangePassword(t *testing.T) {
	r, user := setupProfileTestRouter(t)

	hashed, err := model.HashPassword("old-password-123")
	if err != nil {
		t.Fatalf("failed to hash old password: %v", err)
	}
	if err := model.DB.Model(&model.User{}).Where("id = ?", user.ID).Updates(map[string]interface{}{
		"password":             hashed,
		"must_change_password": true,
	}).Error; err != nil {
		t.Fatalf("failed to seed password flag: %v", err)
	}

	h := NewAuthHandler(model.DB)
	r.PUT("/test-profile/password", h.ChangeMyPassword)

	body := `{"currentPassword":"old-password-123","newPassword":"new-password-456"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/test-profile/password", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var updated model.User
	if err := model.DB.First(&updated, user.ID).Error; err != nil {
		t.Fatalf("failed to reload user: %v", err)
	}
	if updated.MustChangePassword {
		t.Fatal("change password should clear must_change_password")
	}
}

func TestChangeMyPassword_WrongCurrentPassword(t *testing.T) {
	r, user := setupProfileTestRouter(t)

	hashed, err := model.HashPassword("old-password-123")
	if err != nil {
		t.Fatalf("failed to hash old password: %v", err)
	}
	if err := model.DB.Model(&model.User{}).Where("id = ?", user.ID).Update("password", hashed).Error; err != nil {
		t.Fatalf("failed to seed password: %v", err)
	}

	h := NewAuthHandler(model.DB)
	r.PUT("/test-profile/password", h.ChangeMyPassword)

	body := `{"currentPassword":"wrong-password","newPassword":"new-password-456"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", "/test-profile/password", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 400 {
		t.Fatalf("Expected 400, got %d: %s", w.Code, w.Body.String())
	}

	var updated model.User
	if err := model.DB.First(&updated, user.ID).Error; err != nil {
		t.Fatalf("failed to reload user: %v", err)
	}
	if !model.CheckPassword("old-password-123", updated.Password) {
		t.Fatalf("expected password to remain unchanged")
	}
}
