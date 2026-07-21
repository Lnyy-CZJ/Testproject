package handler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func setupRepoHandlerEnv(t testing.TB) (*gin.Engine, uint, *model.User) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db
	user := testutil.CreateTestUser(t, db, "repo_h_user")

	project := testutil.CreateTestProject(t, db, "RepoHProj", "RHP")

	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("userId", user.ID); c.Next() })
	return r, project.ID, &user
}

func TestProjectRepoHandler_CreateWithNewFields(t *testing.T) {
	r, pid, _ := setupRepoHandlerEnv(t)

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)

	body := `{"name":"ba-server","repoUrl":"https://github.com/ex/ba","sourceType":"github","defaultBranch":"main","agentTypes":"backend,test"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d: %s", w.Code, w.Body.String())
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	d := resp["data"].(map[string]interface{})
	if d["sourceType"] != "github" {
		t.Errorf("sourceType=%v", d["sourceType"])
	}
	if d["defaultBranch"] != "main" {
		t.Errorf("defaultBranch=%v", d["defaultBranch"])
	}
}

func TestProjectRepoHandler_DefaultValues(t *testing.T) {
	r, pid, _ := setupRepoHandlerEnv(t)

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)

	body := `{"name":"min-repo","repoUrl":"https://gitlab.com/ex/min","sourceType":"gitlab"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d", w.Code)
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	d := resp["data"].(map[string]interface{})
	if d["defaultBranch"] != "main" {
		t.Errorf("defaultBranch should be main, got %v", d["defaultBranch"])
	}
	if d["agentTypes"] != "backend,test" {
		t.Errorf("agentTypes should be backend,test, got %v", d["agentTypes"])
	}
}

func TestProjectRepoHandler_WithCredential(t *testing.T) {
	r, pid, user := setupRepoHandlerEnv(t)

	svc := service.NewCredentialService(model.DB)
	cred, _ := svc.Create(user.ID, "GH PAT", "pat", "github", "ghp_repo")

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)

	body := fmt.Sprintf(`{"name":"crepo","repoUrl":"https://github.com/ex/cr","sourceType":"github","credentialId":%d,"agentTypes":"frontend"}`, cred.ID)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("Expected 201, got %d", w.Code)
	}
	var resp map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &resp)
	cid := resp["data"].(map[string]interface{})["credentialId"]
	if cid == nil {
		t.Error("credentialId should be set")
	}
}

func TestProjectRepoHandler_UpdateNewFields(t *testing.T) {
	r, pid, _ := setupRepoHandlerEnv(t)

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)
	r.PUT("/:id/repos/:repoId", h.UpdateRepo)

	cb := `{"name":"upd","repoUrl":"https://github.com/ex/u","sourceType":"custom"}`
	wc := httptest.NewRecorder()
	rc, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(cb)))
	rc.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wc, rc)

	var cr map[string]interface{}
	json.Unmarshal(wc.Body.Bytes(), &cr)
	rid := uint(cr["data"].(map[string]interface{})["id"].(float64))

	ub := `{"sourceType":"gitea","defaultBranch":"develop","agentTypes":"test"}`
	wu := httptest.NewRecorder()
	ru, _ := http.NewRequest("PUT", fmt.Sprintf("/%d/repos/%d", pid, rid), bytes.NewReader([]byte(ub)))
	ru.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wu, ru)

	if wu.Code != 200 {
		t.Fatalf("Expected 200, got %d", wu.Code)
	}
	var ur map[string]interface{}
	json.Unmarshal(wu.Body.Bytes(), &ur)
	d := ur["data"].(map[string]interface{})
	if d["sourceType"] != "gitea" {
		t.Errorf("sourceType=%v", d["sourceType"])
	}
}

func TestProjectRepoHandler_ListIncludesNewFields(t *testing.T) {
	r, pid, _ := setupRepoHandlerEnv(t)

	h := NewProjectRepoHandler(model.DB)
	r.GET("/:id/repos", h.ListRepos)
	r.POST("/:id/repos", h.CreateRepo)

	cb := `{"name":"lrepo","repoUrl":"https://github.com/ex/lt","sourceType":"github","defaultBranch":"master","agentTypes":"product,ui"}`
	wc := httptest.NewRecorder()
	rc, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(cb)))
	rc.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wc, rc)

	wl := httptest.NewRecorder()
	rl, _ := http.NewRequest("GET", fmt.Sprintf("/%d/repos", pid), nil)
	r.ServeHTTP(wl, rl)

	if wl.Code != 200 {
		t.Fatalf("Expected 200, got %d", wl.Code)
	}
	var lr map[string]interface{}
	json.Unmarshal(wl.Body.Bytes(), &lr)
	data := lr["data"].([]interface{})
	if len(data) == 0 {
		t.Fatal("Should have at least one repo")
	}
	repo := data[0].(map[string]interface{})
	if repo["sourceType"] == nil {
		t.Error("sourceType missing")
	}
	if repo["agentTypes"] == nil {
		t.Error("agentTypes missing")
	}
	if repo["defaultBranch"] == nil {
		t.Error("defaultBranch missing")
	}
}

func TestProjectRepoHandler_DuplicateURLRejected(t *testing.T) {
	r, pid, _ := setupRepoHandlerEnv(t)

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)

	body := `{"name":"dupr","repoUrl":"https://github.com/ex/dup-url","sourceType":"github"}`

	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req1.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w1, req1)
	if w1.Code != 201 {
		t.Fatalf("First create failed: %d", w1.Code)
	}

	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req2.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w2, req2)
	if w2.Code != 400 {
		t.Errorf("Duplicate URL should return 400, got %d", w2.Code)
	}
}

func TestProjectRepoHandler_CreateRejectsInvalidSourceType(t *testing.T) {
	r, pid, _ := setupRepoHandlerEnv(t)

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)

	body := `{"name":"invalid-source","repoUrl":"https://example.com/repo.git","sourceType":"bitbucket"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 400 {
		t.Fatalf("Expected 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestProjectRepoHandler_CreateRejectsInvalidAgentTypes(t *testing.T) {
	r, pid, _ := setupRepoHandlerEnv(t)

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)

	body := `{"name":"invalid-agent","repoUrl":"https://github.com/ex/agent-invalid","sourceType":"github","agentTypes":"backend,hacker"}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 400 {
		t.Fatalf("Expected 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestProjectRepoHandler_CreateRejectsCredentialNotOwnedByCurrentUser(t *testing.T) {
	r, pid, _ := setupRepoHandlerEnv(t)
	other := testutil.CreateTestUser(t, model.DB, "repo_h_other")

	svc := service.NewCredentialService(model.DB)
	cred, err := svc.Create(other.ID, "other-pat", "pat", "github", "ghp_other")
	if err != nil {
		t.Fatalf("create foreign credential failed: %v", err)
	}

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)

	body := fmt.Sprintf(`{"name":"foreign-cred","repoUrl":"https://github.com/ex/foreign","sourceType":"github","credentialId":%d}`, cred.ID)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 400 {
		t.Fatalf("Expected 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestProjectRepoHandler_CreateRejectsCredentialProviderMismatch(t *testing.T) {
	r, pid, user := setupRepoHandlerEnv(t)

	svc := service.NewCredentialService(model.DB)
	cred, err := svc.Create(user.ID, "gitlab-token", "pat", "gitlab", "glpat_1")
	if err != nil {
		t.Fatalf("create credential failed: %v", err)
	}

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)

	body := fmt.Sprintf(`{"name":"provider-mismatch","repoUrl":"https://github.com/ex/mismatch","sourceType":"github","credentialId":%d}`, cred.ID)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 400 {
		t.Fatalf("Expected 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestProjectRepoHandler_UpdateAllowsClearCredential(t *testing.T) {
	r, pid, user := setupRepoHandlerEnv(t)

	svc := service.NewCredentialService(model.DB)
	cred, err := svc.Create(user.ID, "mine", "pat", "github", "ghp_mine")
	if err != nil {
		t.Fatalf("create credential failed: %v", err)
	}

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)
	r.PUT("/:id/repos/:repoId", h.UpdateRepo)

	createBody := fmt.Sprintf(`{"name":"repo-with-cred","repoUrl":"https://github.com/ex/with-cred","sourceType":"github","credentialId":%d}`, cred.ID)
	wc := httptest.NewRecorder()
	rc, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(createBody)))
	rc.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wc, rc)
	if wc.Code != 201 {
		t.Fatalf("create repo failed: %d %s", wc.Code, wc.Body.String())
	}

	var created map[string]interface{}
	_ = json.Unmarshal(wc.Body.Bytes(), &created)
	repoID := uint(created["data"].(map[string]interface{})["id"].(float64))

	updateBody := `{"credentialId":null}`
	wu := httptest.NewRecorder()
	ru, _ := http.NewRequest("PUT", fmt.Sprintf("/%d/repos/%d", pid, repoID), bytes.NewReader([]byte(updateBody)))
	ru.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wu, ru)
	if wu.Code != 200 {
		t.Fatalf("update repo failed: %d %s", wu.Code, wu.Body.String())
	}

	var updated map[string]interface{}
	_ = json.Unmarshal(wu.Body.Bytes(), &updated)
	data := updated["data"].(map[string]interface{})
	if v, ok := data["credentialId"]; ok && v != nil {
		t.Fatalf("expected credentialId nil in response, got %v", v)
	}

	var repo model.ProjectRepo
	if err := model.DB.First(&repo, repoID).Error; err != nil {
		t.Fatalf("query repo failed: %v", err)
	}
	if repo.CredentialID != nil {
		t.Fatalf("expected credential_id cleared, got %v", *repo.CredentialID)
	}
}

func TestProjectRepoHandler_UpdateRejectsSourceTypeMismatchWithExistingCredential(t *testing.T) {
	r, pid, user := setupRepoHandlerEnv(t)

	svc := service.NewCredentialService(model.DB)
	cred, err := svc.Create(user.ID, "github-token", "pat", "github", "ghp_1")
	if err != nil {
		t.Fatalf("create credential failed: %v", err)
	}

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)
	r.PUT("/:id/repos/:repoId", h.UpdateRepo)

	createBody := fmt.Sprintf(`{"name":"repo-with-gh","repoUrl":"https://github.com/ex/source-change","sourceType":"github","credentialId":%d}`, cred.ID)
	wc := httptest.NewRecorder()
	rc, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(createBody)))
	rc.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wc, rc)
	if wc.Code != 201 {
		t.Fatalf("create repo failed: %d %s", wc.Code, wc.Body.String())
	}

	var created map[string]interface{}
	_ = json.Unmarshal(wc.Body.Bytes(), &created)
	repoID := uint(created["data"].(map[string]interface{})["id"].(float64))

	updateBody := `{"sourceType":"gitlab"}`
	wu := httptest.NewRecorder()
	ru, _ := http.NewRequest("PUT", fmt.Sprintf("/%d/repos/%d", pid, repoID), bytes.NewReader([]byte(updateBody)))
	ru.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(wu, ru)
	if wu.Code != 400 {
		t.Fatalf("Expected 400, got %d: %s", wu.Code, wu.Body.String())
	}
}

func TestProjectRepoHandler_CreateWithAuthorizedPlatformCredential(t *testing.T) {
	r, pid, user := setupRepoHandlerEnv(t)

	svc := service.NewCredentialService(model.DB)
	cred, err := svc.CreatePlatform(user.ID, "platform-github", "pat", "github", "ghp_platform", "", "active", []uint{pid})
	if err != nil {
		t.Fatalf("create platform credential failed: %v", err)
	}

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)

	body := fmt.Sprintf(`{"name":"platform-cred","repoUrl":"https://github.com/ex/platform","sourceType":"github","credentialId":%d}`, cred.ID)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 201 {
		t.Fatalf("expected 201, got %d: %s", w.Code, w.Body.String())
	}
}

func TestProjectRepoHandler_CreateRejectsUnauthorizedPlatformCredential(t *testing.T) {
	r, pid, user := setupRepoHandlerEnv(t)
	otherProject := testutil.CreateTestProject(t, model.DB, "Other Platform Project", "OPP")

	svc := service.NewCredentialService(model.DB)
	cred, err := svc.CreatePlatform(user.ID, "platform-github-other", "pat", "github", "ghp_platform_other", "", "active", []uint{otherProject.ID})
	if err != nil {
		t.Fatalf("create platform credential failed: %v", err)
	}

	h := NewProjectRepoHandler(model.DB)
	r.POST("/:id/repos", h.CreateRepo)

	body := fmt.Sprintf(`{"name":"unauthorized-platform","repoUrl":"https://github.com/ex/platform-no","sourceType":"github","credentialId":%d}`, cred.ID)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", fmt.Sprintf("/%d/repos", pid), bytes.NewReader([]byte(body)))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)

	if w.Code != 403 {
		t.Fatalf("expected 403, got %d: %s", w.Code, w.Body.String())
	}
}
