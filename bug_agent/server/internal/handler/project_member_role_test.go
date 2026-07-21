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

func setupProjectRoleRouter(t testing.TB) (*gin.Engine, *model.User) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "project_role_owner")
	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", user.ID)
		c.Next()
	})
	return r, &user
}

func TestProjectHandler_CreateProject_AssignsProjectAdminRole(t *testing.T) {
	r, user := setupProjectRoleRouter(t)

	h := NewProjectHandler(model.DB)
	r.POST("/projects", h.CreateProject)

	body := `{"name":"RoleProject","code":"ROLEP"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/projects", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	projectID := uint(resp["data"].(map[string]interface{})["id"].(float64))

	var member model.ProjectMember
	if err := model.DB.Where("project_id = ? AND user_id = ?", projectID, user.ID).First(&member).Error; err != nil {
		t.Fatalf("Failed to query project member: %v", err)
	}
	if member.Role != "project_admin" {
		t.Fatalf("Expected role project_admin, got %s", member.Role)
	}
}

func TestProjectHandler_CreateProject_RejectDuplicateCodeCaseInsensitive(t *testing.T) {
	r, _ := setupProjectRoleRouter(t)

	h := NewProjectHandler(model.DB)
	r.POST("/projects", h.CreateProject)

	firstBody := `{"name":"Project A","code":"dup01"}`
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest("POST", "/projects", bytes.NewReader([]byte(firstBody)))
	req1.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w1, req1)
	if w1.Code != 201 {
		t.Fatalf("first create failed: %d %s", w1.Code, w1.Body.String())
	}

	secondBody := `{"name":"Project B","code":"DUP01"}`
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest("POST", "/projects", bytes.NewReader([]byte(secondBody)))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)
	if w2.Code != 400 {
		t.Fatalf("expected 400 for duplicate code, got %d: %s", w2.Code, w2.Body.String())
	}
}

func TestProjectHandler_AddMember_RejectsLegacyRoles(t *testing.T) {
	r, _ := setupProjectRoleRouter(t)

	project := testutil.CreateTestProject(t, model.DB, "RoleNormProject", "RNP")
	adminUser := testutil.CreateTestUser(t, model.DB, "project_role_admin")
	viewerUser := testutil.CreateTestUser(t, model.DB, "project_role_viewer")

	h := NewProjectHandler(model.DB)
	r.POST("/projects/:id/members", h.AddMember)

	testCases := []struct {
		userID uint
		input  string
	}{
		{userID: adminUser.ID, input: "admin"},
		{userID: viewerUser.ID, input: "visitor"},
	}

	for _, tc := range testCases {
		body := fmt.Sprintf(`{"userId":%d,"role":"%s"}`, tc.userID, tc.input)
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", fmt.Sprintf("/projects/%d/members", project.ID), bytes.NewReader([]byte(body)))
		req.Header.Set("Content-Type", "application/json")
		r.ServeHTTP(w, req)

		if w.Code != 400 {
			t.Fatalf("Expected 400 for legacy role %s, got %d: %s", tc.input, w.Code, w.Body.String())
		}

		var member model.ProjectMember
		if err := model.DB.Where("project_id = ? AND user_id = ?", project.ID, tc.userID).First(&member).Error; err == nil {
			t.Fatalf("Legacy role %s should be rejected, but member was created with role=%s", tc.input, member.Role)
		}
	}
}
