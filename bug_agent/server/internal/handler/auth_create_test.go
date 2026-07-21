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

func setupAuthTestRouter(t testing.TB) (*gin.Engine, *model.User) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	admin := testutil.CreateTestUser(t, db, "admin_auth")
	if err := db.Model(&model.User{}).Where("id = ?", admin.ID).Update("platform_role", "admin").Error; err != nil {
		t.Fatalf("failed to set admin role: %v", err)
	}

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", admin.ID)
		c.Next()
	})
	return r, &admin
}

func TestAuthHandler_CreateUser_Success(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.POST("/test-users", h.CreateUser)

	body := `{"username":"newuser","email":"new@test.com","password":"password123456789","nickname":"New User"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["username"] != "newuser" {
		t.Errorf("Username mismatch: %v", data["username"])
	}
	if data["email"] != "new@test.com" {
		t.Errorf("Email mismatch: %v", data["email"])
	}
	if data["nickname"] != "New User" {
		t.Errorf("Nickname mismatch: %v", data["nickname"])
	}
	if _, ok := data["password"]; ok {
		t.Error("Password should not be in response")
	}
}

func TestAuthHandler_CreateUser_PasswordHashed(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.POST("/test-users", h.CreateUser)

	body := `{"username":"hashed_user","email":"hashed@test.com","password":"mypassword123456"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d", w.Code)
	}

	var user model.User
	data := make(map[string]interface{})
	json.Unmarshal(w.Body.Bytes(), &data)
	userData := data["data"].(map[string]interface{})
	_ = userData

	model.DB.First(&user, "username = ?", "hashed_user")
	if user.Password == "mypassword123456" {
		t.Error("Password should be hashed, not stored as plaintext")
	}
	if !model.CheckPassword("mypassword123456", user.Password) {
		t.Error("Password should verify correctly")
	}
}

func TestAuthHandler_CreateUser_DuplicateUsername(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.POST("/test-users", h.CreateUser)

	body := `{"username":"dup_user","email":"dup1@test.com","password":"pass123456789012"}`
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body)))
	req1.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w1, req1)

	if w1.Code != 201 {
		t.Fatalf("First create should succeed, got %d", w1.Code)
	}

	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body)))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)

	if w2.Code != 400 {
		t.Errorf("Duplicate username should return 400, got %d", w2.Code)
	}
}

func TestAuthHandler_CreateUser_DuplicateEmail(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.POST("/test-users", h.CreateUser)

	body1 := `{"username":"email_user1","email":"same@test.com","password":"pass123456789012"}`
	body2 := `{"username":"email_user2","email":"same@test.com","password":"pass123456789012"}`

	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body1)))
	req1.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w1, req1)

	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body2)))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)

	if w2.Code != 400 {
		t.Errorf("Duplicate email should return 400, got %d", w2.Code)
	}
}

func TestAuthHandler_CreateUser_MissingFields(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.POST("/test-users", h.CreateUser)

	tests := []struct {
		name string
		body string
	}{
		{"No username", `{"email":"a@b.com","password":"pass123456789012"}`},
		{"No email", `{"username":"x","password":"pass123456789012"}`},
		{"Empty body", `{}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			req, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(tt.body)))
			req.Header.Set("Content-Type", "application/json")
			r.ServeHTTP(w, req)

			if w.Code != 400 {
				t.Errorf("%s: Expected 400, got %d", tt.name, w.Code)
			}
		})
	}
}

func TestAuthHandler_CreateUser_ShortPassword(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.POST("/test-users", h.CreateUser)

	body := `{"username":"short_pass","email":"sp@test.com","password":"12345"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 400 {
		t.Errorf("Short password should return 400, got %d", w.Code)
	}
}

func TestAuthHandler_CreateUser_WithPlatformRoleAndProjectAssignments(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	projectA := testutil.CreateTestProject(t, model.DB, "AuthCreateP1", "ACP1")
	projectB := testutil.CreateTestProject(t, model.DB, "AuthCreateP2", "ACP2")

	h := NewAuthHandler(model.DB)
	r.POST("/test-users", h.CreateUser)

	body := fmt.Sprintf(`{
		"username":"role_project_user",
		"email":"rp@test.com",
		"password":"password123456789",
		"platformRole":"admin",
		"projectIds":[%d,%d],
		"projectRole":"tester"
	}`, projectA.ID, projectB.ID)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d: %s", w.Code, w.Body.String())
	}

	var created model.User
	if err := model.DB.Where("username = ?", "role_project_user").First(&created).Error; err != nil {
		t.Fatalf("Failed to query created user: %v", err)
	}
	if created.PlatformRole != "admin" {
		t.Fatalf("Expected platformRole=admin, got %s", created.PlatformRole)
	}

	var members []model.ProjectMember
	if err := model.DB.Where("user_id = ?", created.ID).Find(&members).Error; err != nil {
		t.Fatalf("Failed to query project members: %v", err)
	}
	if len(members) != 2 {
		t.Fatalf("Expected 2 project assignments, got %d", len(members))
	}
	for _, m := range members {
		if m.Role != "tester" {
			t.Fatalf("Expected project role tester, got %s", m.Role)
		}
	}
}

func TestAuthHandler_CreateUser_InvalidPlatformRole(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.POST("/test-users", h.CreateUser)

	body := `{"username":"bad_role_user","email":"badrole@test.com","password":"password123456789","platformRole":"owner"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 400 {
		t.Fatalf("Expected 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestAuthHandler_CreateUser_ForbiddenForMember(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	member := testutil.CreateTestUser(t, db, "member_auth")

	h := NewAuthHandler(model.DB)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", member.ID)
		c.Next()
	})
	r.POST("/test-users", h.CreateUser)

	body := `{"username":"denied_user","email":"denied@test.com","password":"password123456789"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 403 {
		t.Fatalf("Expected 403, got %d: %s", w.Code, w.Body.String())
	}
}

func TestAuthHandler_CreateUser_AutoGeneratePassword(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	h := NewAuthHandler(model.DB)
	r.POST("/test-users", h.CreateUser)

	body := `{"username":"auto_pass_user","email":"autopass@test.com","nickname":"Auto Pass"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/test-users", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})

	temp, ok := data["temporaryPassword"].(string)
	if !ok || len(temp) < 16 {
		t.Fatalf("Expected temporaryPassword with length >= 16, got %#v", data["temporaryPassword"])
	}

	var user model.User
	if err := model.DB.Where("username = ?", "auto_pass_user").First(&user).Error; err != nil {
		t.Fatalf("Failed to query created user: %v", err)
	}
	if !model.CheckPassword(temp, user.Password) {
		t.Fatal("temporaryPassword should match stored hash")
	}
	if !user.MustChangePassword {
		t.Fatal("auto generated password should require password change")
	}
}

func TestAuthHandler_ResetPassword_SetsTemporaryPasswordAndMustChangeFlag(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	target := testutil.CreateTestUser(t, model.DB, "reset_password_user")
	if err := model.DB.Model(&model.User{}).Where("id = ?", target.ID).Update("must_change_password", false).Error; err != nil {
		t.Fatalf("failed to reset must_change_password: %v", err)
	}

	h := NewAuthHandler(model.DB)
	r.POST("/test-users/:id/reset-password", h.ResetUserPassword)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/test-users/"+fmt.Sprintf("%d", target.ID)+"/reset-password", nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	temp, ok := data["temporaryPassword"].(string)
	if !ok || len(temp) < 16 {
		t.Fatalf("Expected temporaryPassword with length >= 16, got %#v", data["temporaryPassword"])
	}

	var updated model.User
	if err := model.DB.First(&updated, target.ID).Error; err != nil {
		t.Fatalf("reload user failed: %v", err)
	}
	if !updated.MustChangePassword {
		t.Fatal("reset password should set must_change_password")
	}
	if !model.CheckPassword(temp, updated.Password) {
		t.Fatal("temporaryPassword should match stored hash after reset")
	}
}

func TestAuthHandler_ListUsers_FilterByProjectID(t *testing.T) {
	r, _ := setupAuthTestRouter(t)

	projectA := testutil.CreateTestProject(t, model.DB, "UserFilterP1", "UFP1")
	projectB := testutil.CreateTestProject(t, model.DB, "UserFilterP2", "UFP2")
	userA := testutil.CreateTestUser(t, model.DB, "filter_user_a")
	userB := testutil.CreateTestUser(t, model.DB, "filter_user_b")

	if err := model.DB.Create(&model.ProjectMember{ProjectID: projectA.ID, UserID: userA.ID, Role: "developer"}).Error; err != nil {
		t.Fatalf("create project member A failed: %v", err)
	}
	if err := model.DB.Create(&model.ProjectMember{ProjectID: projectB.ID, UserID: userB.ID, Role: "developer"}).Error; err != nil {
		t.Fatalf("create project member B failed: %v", err)
	}

	h := NewAuthHandler(model.DB)
	r.GET("/test-users", h.ListUsers)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/test-users?projectId="+fmt.Sprintf("%d", projectA.ID), nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	list := data["list"].([]interface{})
	if len(list) != 1 {
		t.Fatalf("Expected 1 user in project filter, got %d", len(list))
	}
	first := list[0].(map[string]interface{})
	if first["username"] != "filter_user_a" {
		t.Fatalf("Expected filter_user_a, got %v", first["username"])
	}
}
