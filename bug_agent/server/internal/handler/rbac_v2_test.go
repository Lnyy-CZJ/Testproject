package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/middleware"
	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestRBACV2_SevenRolesSeeded(t *testing.T) {
	db := testutil.SetupTestDB(t)
	middleware.SeedRBACData(db)

	var roles []model.Role
	if err := db.Find(&roles).Error; err != nil {
		t.Fatalf("Failed to query roles: %v", err)
	}
	if len(roles) < 7 {
		t.Errorf("Expected at least 7 roles, got %d", len(roles))
	}

	names := make(map[string]bool)
	for _, r := range roles {
		names[r.Name] = true
	}
	for _, n := range []string{"super_admin", "admin", "member"} {
		if !names[n] {
			t.Errorf("Missing platform role: %s", n)
		}
	}
	for _, n := range []string{"project_admin", "developer", "tester", "viewer"} {
		if !names[n] {
			t.Errorf("Missing project role: %s", n)
		}
	}
}

func TestRBACV2_AdminHasSuperAdminRole(t *testing.T) {
	db := testutil.SetupTestDB(t)
	adminUser := model.User{Username: "admin", Email: "admin@test.com", Password: "$2a$10$hashedpassword123456789012345678901234567890", Nickname: "System Admin"}
	db.Create(&adminUser)
	middleware.SeedRBACData(db)

	var user model.User
	db.Where("username = ?", "admin").First(&user)
	if user.ID == 0 {
		t.Fatal("Admin user not found")
	}

	var ur model.UserRole
	if err := db.Where("user_id = ?", user.ID).First(&ur).Error; err != nil {
		t.Fatalf("Admin has no UserRole: %v", err)
	}
	var role model.Role
	db.First(&role, ur.RoleID)
	if role.Name != "super_admin" {
		t.Errorf("Admin should have super_admin, got %s", role.Name)
	}
}

func TestRBACV2_RolesHavePermissions(t *testing.T) {
	db := testutil.SetupTestDB(t)
	middleware.SeedRBACData(db)

	var permCount int64
	db.Model(&model.RolePermission{}).Count(&permCount)
	if permCount == 0 {
		t.Error("Should have role-permission mappings")
	}
}

func TestRBACV2_ListPermissions(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	testutil.CreateTestUser(t, db, "rbac_list_perm")

	middleware.SeedRBACData(db)

	h := NewRBACHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", uint(1)); c.Next() })
	r.GET("/perms-v2", h.ListPermissions)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/perms-v2", nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	dataVal := resp["data"]
	if dataVal == nil {
		t.Fatalf("Response missing data: %s", w.Body.String())
	}
	dataMap, ok := dataVal.(map[string]interface{})
	if !ok {
		t.Fatalf("Data should be a map (grouped by module), got %T", dataVal)
	}
	totalPerms := 0
	for _, v := range dataMap {
		if arr, ok := v.([]interface{}); ok {
			totalPerms += len(arr)
		}
	}
	if totalPerms < 5 {
		t.Errorf("Expected at least 5 permissions total, got %d", totalPerms)
	}
}

func TestRBACV2_TierClassification(t *testing.T) {
	db := testutil.SetupTestDB(t)
	middleware.SeedRBACData(db)

	var roles []model.Role
	db.Find(&roles)

	platformSet := map[string]bool{"super_admin": true, "admin": true, "member": true}
	projectSet := map[string]bool{"project_admin": true, "developer": true, "tester": true, "viewer": true}

	pCount, projCount := 0, 0
	for _, role := range roles {
		if platformSet[role.Name] {
			pCount++
		} else if projectSet[role.Name] {
			projCount++
		}
	}
	if pCount < 3 {
		t.Errorf("Platform roles: got %d, want >=3", pCount)
	}
	if projCount < 4 {
		t.Errorf("Project roles: got %d, want >=4", projCount)
	}
}
