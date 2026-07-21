package handler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
	"github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing/object"
)

func TestCredentialHandler_ListCredentials(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "cred_list_h")

	h := NewCredentialHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.POST("/creds", h.CreateCredential)
	r.GET("/creds", h.ListCredentials)

	for _, name := range []string{"GH Token", "GL Token"} {
		body := fmt.Sprintf(`{"name":"%s","type":"pat","provider":"github","content":"ghp_%s"}`, name, name)
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/creds", bytes.NewReader([]byte(body)))
		req.Header.Set("Content-Type", "application/json")
		r.ServeHTTP(w, req)
		if w.Code != 201 {
			t.Fatalf("Setup create failed for %s: %d", name, w.Code)
		}
	}

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/creds", nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].([]interface{})
	if len(data) != 2 {
		t.Errorf("Expected 2 creds, got %d", len(data))
	}
}

func TestCredentialHandler_ListCredentials_IsolatedByCurrentUser(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user1 := testutil.CreateTestUser(t, db, "cred_iso_u1")
	user2 := testutil.CreateTestUser(t, db, "cred_iso_u2")

	h := NewCredentialHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) {
		raw := c.GetHeader("X-User-ID")
		if raw == fmt.Sprintf("%d", user2.ID) {
			c.Set("userId", user2.ID)
		} else {
			c.Set("userId", user1.ID)
		}
		c.Next()
	})
	r.POST("/creds", h.CreateCredential)
	r.GET("/creds", h.ListCredentials)

	createAs := func(uid uint, body string) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/creds", bytes.NewReader([]byte(body)))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-User-ID", fmt.Sprintf("%d", uid))
		r.ServeHTTP(w, req)
		if w.Code != 201 {
			t.Fatalf("create credential failed for user %d: %d %s", uid, w.Code, w.Body.String())
		}
	}

	createAs(user1.ID, `{"name":"u1","type":"pat","provider":"github","content":"ghp_u1_token"}`)
	createAs(user2.ID, `{"name":"u2","type":"pat","provider":"github","content":"ghp_u2_token"}`)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/creds", nil)
	req.Header.Set("X-User-ID", fmt.Sprintf("%d", user1.ID))
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].([]interface{})
	if len(data) != 1 {
		t.Fatalf("Expected 1 credential for user1, got %d", len(data))
	}
	got := data[0].(map[string]interface{})
	if uint(got["userId"].(float64)) != user1.ID {
		t.Fatalf("Expected userId=%d, got %v", user1.ID, got["userId"])
	}
}

func TestCredentialHandler_CreateCredential(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "cred_create_h")

	h := NewCredentialHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.POST("/creds", h.CreateCredential)

	body := `{"name":"My GH","type":"pat","provider":"github","content":"ghp_secret","extraConfig":"{\"organizationId\":\"org-a\"}"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/creds", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d: %s", w.Code, w.Body.String())
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["name"] != "My GH" || data["type"] != "pat" {
		t.Errorf("Unexpected data: %+v", data)
	}
	if data["extraConfig"] != `{"organizationId":"org-a"}` {
		t.Errorf("extraConfig not returned correctly: %v", data["extraConfig"])
	}
	masked := data["maskedValue"].(string)
	if masked == "" || masked == "ghp_secret" {
		t.Errorf("MaskedValue should be masked, got: %s", masked)
	}
}

func TestCredentialHandler_CreateCredential_MissingFields(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	testutil.CreateTestUser(t, db, "cred_missing_h")

	h := NewCredentialHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", uint(1)); c.Next() })
	r.POST("/creds", h.CreateCredential)

	body := `{"name":"Incomplete"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/creds", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 400 {
		t.Errorf("Expected 400, got %d", w.Code)
	}
}

func TestCredentialHandler_UpdateCredential(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "cred_update_h")

	h := NewCredentialHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.POST("/creds", h.CreateCredential)
	r.PUT("/creds/:id", h.UpdateCredential)

	cb := `{"name":"Old Name","type":"pat","provider":"github","content":"ghp_old"}`
	wc := httptest.NewRecorder()
	rc, _ := http.NewRequest("POST", "/creds", bytes.NewReader([]byte(cb)))
	rc.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wc, rc)

	var cr map[string]interface{}
	json.Unmarshal(wc.Body.Bytes(), &cr)
	credID := cr["data"].(map[string]interface{})["id"].(float64)

	body := `{"name":"New Name","provider":"gitlab"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("PUT", fmt.Sprintf("/creds/%d", uint(credID)), bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["name"] != "New Name" {
		t.Errorf("Name not updated: %v", data["name"])
	}
}

func TestCredentialHandler_DeleteCredential(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "cred_delete_h")

	h := NewCredentialHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.POST("/creds", h.CreateCredential)
	r.DELETE("/creds/:id", h.DeleteCredential)

	cb := `{"name":"To Del","type":"pat","provider":"github","content":"ghp_del"}`
	wc := httptest.NewRecorder()
	rc, _ := http.NewRequest("POST", "/creds", bytes.NewReader([]byte(cb)))
	rc.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wc, rc)

	var cr map[string]interface{}
	json.Unmarshal(wc.Body.Bytes(), &cr)
	credID := cr["data"].(map[string]interface{})["id"].(float64)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("DELETE", fmt.Sprintf("/creds/%d", uint(credID)), nil)
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var count int64
	db.Model(&model.RepoCredential{}).Where("id = ?", uint(credID)).Count(&count)
	if count > 0 {
		t.Error("Credential should be deleted")
	}
}

func TestCredentialHandler_TestConnection(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	localRepoURL := createLocalGitRepoURL(t)

	h := NewCredentialHandler(db)
	r := gin.New()
	r.POST("/creds/test-conn", h.TestConnection)

	body := fmt.Sprintf(`{"provider":"generic","repoUrl":"%s"}`, localRepoURL)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/creds/test-conn", bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 200 {
		t.Fatalf("Expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["success"].(bool) != true {
		t.Errorf("Expected success=true")
	}
}

func TestCredentialHandler_CreatePlatformCredential(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	admin := testutil.CreateTestUser(t, db, "platform_cred_admin")
	projectA := testutil.CreateTestProject(t, db, "Platform Allowed A", "PCA")
	projectB := testutil.CreateTestProject(t, db, "Platform Allowed B", "PCB")

	h := NewCredentialHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", admin.ID); c.Next() })
	r.POST("/admin/platform-credentials", h.CreatePlatformCredential)

	body := fmt.Sprintf(`{
		"name":"Platform Yunxiao",
		"type":"pat",
		"provider":"yunxiao",
		"content":"token-platform",
		"status":"active",
		"allowedProjectIds":[%d,%d]
	}`, projectA.ID, projectB.ID)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/admin/platform-credentials", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	data := resp["data"].(map[string]interface{})
	if data["scope"] != "platform" {
		t.Fatalf("expected scope=platform, got %v", data["scope"])
	}
	if data["status"] != "active" {
		t.Fatalf("expected status=active, got %v", data["status"])
	}
	allowed := data["allowedProjectIds"].([]interface{})
	if len(allowed) != 2 {
		t.Fatalf("expected 2 allowed projects, got %d", len(allowed))
	}
}

func TestCredentialHandler_ListCredentials_ForProjectIncludesAuthorizedPlatformCredentials(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "platform_cred_user")
	admin := testutil.CreateTestUser(t, db, "platform_cred_admin_list")
	projectAllowed := testutil.CreateTestProject(t, db, "Allowed Project", "ALW")
	projectDenied := testutil.CreateTestProject(t, db, "Denied Project", "DNY")

	svc := service.NewCredentialService(db)
	if _, err := svc.Create(user.ID, "Personal GitHub", "pat", "github", "ghp_personal"); err != nil {
		t.Fatalf("create personal credential failed: %v", err)
	}
	if _, err := svc.CreatePlatform(admin.ID, "Platform Allowed", "pat", "github", "ghp_platform_allowed", "", "active", []uint{projectAllowed.ID}); err != nil {
		t.Fatalf("create allowed platform credential failed: %v", err)
	}
	if _, err := svc.CreatePlatform(admin.ID, "Platform Denied", "pat", "github", "ghp_platform_denied", "", "active", []uint{projectDenied.ID}); err != nil {
		t.Fatalf("create denied platform credential failed: %v", err)
	}

	h := NewCredentialHandler(db)
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	r.GET("/creds", h.ListCredentials)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, fmt.Sprintf("/creds?projectId=%d", projectAllowed.ID), nil)
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	items := resp["data"].([]interface{})
	if len(items) != 2 {
		t.Fatalf("expected 2 visible credentials, got %d", len(items))
	}

	scopes := make(map[string]bool)
	names := make(map[string]bool)
	for _, item := range items {
		row := item.(map[string]interface{})
		scopes[row["scope"].(string)] = true
		names[row["name"].(string)] = true
	}
	if !scopes["personal"] || !scopes["platform"] {
		t.Fatalf("expected both personal and platform credentials, got scopes=%v", scopes)
	}
	if names["Platform Denied"] {
		t.Fatalf("unauthorized platform credential should not be visible")
	}
}

func createLocalGitRepoURL(t *testing.T) string {
	t.Helper()

	dir := t.TempDir()
	repo, err := git.PlainInit(dir, false)
	if err != nil {
		t.Fatalf("init local git repo failed: %v", err)
	}

	readmePath := filepath.Join(dir, "README.md")
	if err := os.WriteFile(readmePath, []byte("# handler repo\n"), 0644); err != nil {
		t.Fatalf("write readme failed: %v", err)
	}

	worktree, err := repo.Worktree()
	if err != nil {
		t.Fatalf("get worktree failed: %v", err)
	}
	if _, err := worktree.Add("README.md"); err != nil {
		t.Fatalf("git add failed: %v", err)
	}
	if _, err := worktree.Commit("init", &git.CommitOptions{
		Author: &object.Signature{Name: "tester", Email: "tester@example.com", When: time.Now()},
	}); err != nil {
		t.Fatalf("git commit failed: %v", err)
	}

	return "file://" + dir
}
