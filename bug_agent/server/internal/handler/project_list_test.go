package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func TestProjectHandler_ListProjects(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	user1 := testutil.CreateTestUser(t, db, "proj_list_user1")
	user2 := testutil.CreateTestUser(t, db, "proj_list_user2")

	project1 := testutil.CreateTestProject(t, db, "Alpha", "ALPHA")
	project2 := testutil.CreateTestProject(t, db, "Beta", "BETA")

	if err := db.Create(&model.ProjectMember{ProjectID: project1.ID, UserID: user1.ID, Role: "developer"}).Error; err != nil {
		t.Fatalf("create member1 failed: %v", err)
	}
	if err := db.Create(&model.ProjectMember{ProjectID: project2.ID, UserID: user2.ID, Role: "developer"}).Error; err != nil {
		t.Fatalf("create member2 failed: %v", err)
	}

	h := NewProjectHandler(model.DB)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user1.ID); c.Next() })
	r.GET("/projects", h.ListProjects)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/projects?page=1&pageSize=20", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data, ok := resp["data"].(map[string]interface{})
	if !ok {
		t.Fatalf("unexpected response data shape: %s", w.Body.String())
	}
	rawItems, exists := data["items"]
	if !exists {
		t.Fatalf("response missing items: %s", w.Body.String())
	}
	items, ok := rawItems.([]interface{})
	if !ok {
		t.Fatalf("unexpected items shape: %T, body=%s", rawItems, w.Body.String())
	}
	if len(items) != 1 {
		t.Fatalf("Expected 1 project for current user, got %d", len(items))
	}
	first := items[0].(map[string]interface{})
	if first["id"].(float64) != float64(project1.ID) {
		t.Fatalf("Expected project id %d, got %v", project1.ID, first["id"])
	}
}

func TestProjectHandler_ListProjects_AllForPlatformAdmin(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	admin := testutil.CreateTestUser(t, db, "proj_list_admin")
	if err := db.Model(&model.User{}).Where("id = ?", admin.ID).Update("platform_role", "admin").Error; err != nil {
		t.Fatalf("update admin role failed: %v", err)
	}

	testutil.CreateTestProject(t, db, "Alpha", "ALPHA")
	testutil.CreateTestProject(t, db, "Beta", "BETA")

	h := NewProjectHandler(model.DB)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", admin.ID); c.Next() })
	r.GET("/projects", h.ListProjects)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/projects?all=true&page=1&pageSize=20", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	items := data["items"].([]interface{})
	if len(items) != 2 {
		t.Fatalf("Expected 2 projects for platform admin with all=true, got %d", len(items))
	}
}

func TestProjectHandler_ListProjects_AllIgnoredForMember(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	member := testutil.CreateTestUser(t, db, "proj_list_member")
	other := testutil.CreateTestUser(t, db, "proj_list_other")

	project1 := testutil.CreateTestProject(t, db, "Alpha", "ALPHA")
	project2 := testutil.CreateTestProject(t, db, "Beta", "BETA")
	if err := db.Create(&model.ProjectMember{ProjectID: project1.ID, UserID: member.ID, Role: "developer"}).Error; err != nil {
		t.Fatalf("create member relation failed: %v", err)
	}
	if err := db.Create(&model.ProjectMember{ProjectID: project2.ID, UserID: other.ID, Role: "developer"}).Error; err != nil {
		t.Fatalf("create other relation failed: %v", err)
	}

	h := NewProjectHandler(model.DB)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", member.ID); c.Next() })
	r.GET("/projects", h.ListProjects)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/projects?all=true&page=1&pageSize=20", nil)
	r.ServeHTTP(w, req)
	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	items := data["items"].([]interface{})
	if len(items) != 1 {
		t.Fatalf("Expected 1 project for non-admin with all=true, got %d", len(items))
	}
}
