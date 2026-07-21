package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
)

func setupYunxiaoEnv(t testing.TB) (*gin.Engine, *model.User, *model.Project, *service.CredentialService) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	user := testutil.CreateTestUser(t, db, "yunxiao_owner")
	project := testutil.CreateTestProject(t, db, "Yunxiao Import Project", "YXP")
	if err := db.Create(&model.ProjectMember{
		ProjectID: project.ID,
		UserID:    user.ID,
		Role:      "project_admin",
	}).Error; err != nil {
		t.Fatalf("create project member failed: %v", err)
	}

	r := gin.New()
	r.Use(func(c *gin.Context) {
		c.Set("userId", user.ID)
		c.Next()
	})
	return r, &user, &project, service.NewCredentialService(db)
}

func TestYunxiaoIntegration_ListReposAndImport(t *testing.T) {
	r, user, project, credSvc := setupYunxiaoEnv(t)

	cred, err := credSvc.Create(user.ID, "yunxiao-token", "pat", "yunxiao", "token-abc")
	if err != nil {
		t.Fatalf("create credential failed: %v", err)
	}

	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if req.Header.Get("x-yunxiao-token") == "" {
			http.Error(w, `{"message":"missing token"}`, http.StatusUnauthorized)
			return
		}
		if req.URL.Path == "/oapi/v1/codeup/repositories" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`[
				{"id":"101","name":"repo-a","httpUrlToRepo":"https://codeup.aliyun.com/acme/repo-a.git","defaultBranch":"main"}
			]`))
			return
		}
		http.NotFound(w, req)
	}))
	defer mockServer.Close()

	h := NewYunxiaoIntegrationHandler(model.DB)
	r.GET("/integrations/yunxiao/repos", h.ListRepositories)
	r.POST("/projects/:id/repos/import/yunxiao", h.ImportRepositories)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/integrations/yunxiao/repos?credentialId="+toStrUint(cred.ID)+"&endpoint="+mockServer.URL, nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("list repos failed: %d %s", w.Code, w.Body.String())
	}

	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	list := resp["data"].(map[string]interface{})["list"].([]interface{})
	if len(list) != 1 {
		t.Fatalf("expected 1 repo from list, got %d", len(list))
	}
	first := list[0].(map[string]interface{})
	if first["sourceType"] != "yunxiao" {
		t.Fatalf("expected sourceType=yunxiao, got %v", first["sourceType"])
	}
	if first["externalRepoId"] != "101" {
		t.Fatalf("expected externalRepoId=101, got %v", first["externalRepoId"])
	}

	importBody := `{
		"credentialId": ` + toStrUint(cred.ID) + `,
		"items": [
			{"externalId":"101","name":"repo-a","repoUrl":"https://codeup.aliyun.com/acme/repo-a.git","defaultBranch":"main"}
		]
	}`
	iw := httptest.NewRecorder()
	ireq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/repos/import/yunxiao", bytes.NewBufferString(importBody))
	ireq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(iw, ireq)
	if iw.Code != http.StatusOK {
		t.Fatalf("import repos failed: %d %s", iw.Code, iw.Body.String())
	}

	var importedResp map[string]interface{}
	_ = json.Unmarshal(iw.Body.Bytes(), &importedResp)
	summary := importedResp["data"].(map[string]interface{})["summary"].(map[string]interface{})
	if int(summary["imported"].(float64)) != 1 {
		t.Fatalf("expected imported=1, got %v", summary["imported"])
	}

	var count int64
	if err := model.DB.Model(&model.ProjectRepo{}).
		Where("project_id = ? AND source_type = ? AND repo_url = ?", project.ID, "yunxiao", "https://codeup.aliyun.com/acme/repo-a.git").
		Count(&count).Error; err != nil {
		t.Fatalf("count imported repo failed: %v", err)
	}
	if count != 1 {
		t.Fatalf("expected 1 imported repo row, got %d", count)
	}

	var imported model.ProjectRepo
	if err := model.DB.Where("project_id = ? AND repo_url = ?", project.ID, "https://codeup.aliyun.com/acme/repo-a.git").First(&imported).Error; err != nil {
		t.Fatalf("query imported repo failed: %v", err)
	}
	if imported.ExternalRepoID != "101" {
		t.Fatalf("expected externalRepoId=101, got %q", imported.ExternalRepoID)
	}
}

func TestYunxiaoIntegration_ListMembersAndImport(t *testing.T) {
	r, user, project, credSvc := setupYunxiaoEnv(t)

	localByEmail := testutil.CreateTestUser(t, model.DB, "yunxiao_member_email")
	localByEmail.Email = "member1@example.com"
	if err := model.DB.Save(&localByEmail).Error; err != nil {
		t.Fatalf("update email failed: %v", err)
	}
	localByUsername := testutil.CreateTestUser(t, model.DB, "yunxiao_member_username")
	localByUsername.Username = "member2"
	if err := model.DB.Save(&localByUsername).Error; err != nil {
		t.Fatalf("update username failed: %v", err)
	}

	content := "token-xyz"
	cred, err := credSvc.Create(user.ID, "yunxiao-member-token", "pat", "yunxiao", content)
	if err != nil {
		t.Fatalf("create credential failed: %v", err)
	}

	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if req.URL.Path == "/oapi/v1/platform/organizations/org-test/members" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`[
				{"id":"u1","name":"Member One","email":"member1@example.com","role":"admin"},
				{"id":"u2","name":"Member Two","username":"member2","role":"developer"},
				{"id":"u3","name":"Member Three","email":"notfound@example.com","role":"tester"}
			]`))
			return
		}
		http.NotFound(w, req)
	}))
	defer mockServer.Close()

	if err := model.DB.Model(&model.RepoCredential{}).
		Where("id = ?", cred.ID).
		Update("extra_config", `{"organizationId":"org-test","endpoint":"`+mockServer.URL+`"}`).
		Error; err != nil {
		t.Fatalf("update credential extra_config failed: %v", err)
	}

	h := NewYunxiaoIntegrationHandler(model.DB)
	r.GET("/integrations/yunxiao/members", h.ListMembers)
	r.POST("/projects/:id/members/import/yunxiao", h.ImportMembers)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/integrations/yunxiao/members?credentialId="+toStrUint(cred.ID), nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("list members failed: %d %s", w.Code, w.Body.String())
	}

	importBody := `{
		"credentialId": ` + toStrUint(cred.ID) + `,
		"updateExisting": true,
		"items": [
			{"externalId":"u1","name":"Member One","email":"member1@example.com","role":"admin"},
			{"externalId":"u2","name":"Member Two","username":"member2","role":"developer"},
			{"externalId":"u3","name":"Member Three","email":"notfound@example.com","role":"tester"}
		]
	}`
	iw := httptest.NewRecorder()
	ireq, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/members/import/yunxiao", bytes.NewBufferString(importBody))
	ireq.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(iw, ireq)
	if iw.Code != http.StatusOK {
		t.Fatalf("import members failed: %d %s", iw.Code, iw.Body.String())
	}

	var resp map[string]interface{}
	_ = json.Unmarshal(iw.Body.Bytes(), &resp)
	summary := resp["data"].(map[string]interface{})["summary"].(map[string]interface{})
	if int(summary["added"].(float64)) != 2 {
		t.Fatalf("expected added=2, got %v", summary["added"])
	}
	if int(summary["unmatched"].(float64)) != 1 {
		t.Fatalf("expected unmatched=1, got %v", summary["unmatched"])
	}

	var pm1 model.ProjectMember
	if err := model.DB.Where("project_id = ? AND user_id = ?", project.ID, localByEmail.ID).First(&pm1).Error; err != nil {
		t.Fatalf("member1 not imported: %v", err)
	}
	if pm1.Role != "project_admin" {
		t.Fatalf("member1 role expected project_admin, got %s", pm1.Role)
	}

	var pm2 model.ProjectMember
	if err := model.DB.Where("project_id = ? AND user_id = ?", project.ID, localByUsername.ID).First(&pm2).Error; err != nil {
		t.Fatalf("member2 not imported: %v", err)
	}
	if pm2.Role != "developer" {
		t.Fatalf("member2 role expected developer, got %s", pm2.Role)
	}
}

func TestYunxiaoIntegration_ListRepos_StatusCodeMapping(t *testing.T) {
	r, user, _, credSvc := setupYunxiaoEnv(t)

	cred, err := credSvc.Create(user.ID, "yunxiao-token", "pat", "yunxiao", "token-abc")
	if err != nil {
		t.Fatalf("create credential failed: %v", err)
	}

	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		http.Error(w, `{"message":"invalid token"}`, http.StatusUnauthorized)
	}))
	defer mockServer.Close()

	h := NewYunxiaoIntegrationHandler(model.DB)
	r.GET("/integrations/yunxiao/repos", h.ListRepositories)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/integrations/yunxiao/repos?credentialId="+toStrUint(cred.ID)+"&endpoint="+mockServer.URL, nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d: %s", w.Code, w.Body.String())
	}
}

func TestYunxiaoIntegration_ListRepos_WithAuthorizedPlatformCredential(t *testing.T) {
	r, user, project, credSvc := setupYunxiaoEnv(t)

	cred, err := credSvc.CreatePlatform(user.ID, "platform-yunxiao", "pat", "yunxiao", "token-platform", `{"organizationId":"org-test"}`, "active", []uint{project.ID})
	if err != nil {
		t.Fatalf("create platform credential failed: %v", err)
	}

	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if req.URL.Path == "/oapi/v1/codeup/organizations/org-test/repositories" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`[
				{"id":"201","name":"repo-platform","httpUrlToRepo":"https://codeup.aliyun.com/acme/repo-platform.git","defaultBranch":"main"}
			]`))
			return
		}
		http.NotFound(w, req)
	}))
	defer mockServer.Close()

	h := NewYunxiaoIntegrationHandler(model.DB)
	r.GET("/integrations/yunxiao/repos", h.ListRepositories)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/integrations/yunxiao/repos?projectId="+toStrUint(project.ID)+"&credentialId="+toStrUint(cred.ID)+"&endpoint="+mockServer.URL, nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}
}

func TestYunxiaoIntegration_ImportRepos_WithAuthorizedPlatformCredential(t *testing.T) {
	r, user, project, credSvc := setupYunxiaoEnv(t)

	cred, err := credSvc.CreatePlatform(user.ID, "platform-yunxiao-import", "pat", "yunxiao", "token-platform-import", "", "active", []uint{project.ID})
	if err != nil {
		t.Fatalf("create platform credential failed: %v", err)
	}

	h := NewYunxiaoIntegrationHandler(model.DB)
	r.POST("/projects/:id/repos/import/yunxiao", h.ImportRepositories)

	importBody := `{
		"credentialId": ` + toStrUint(cred.ID) + `,
		"items": [
			{"externalId":"301","name":"repo-platform-import","repoUrl":"https://codeup.aliyun.com/acme/repo-platform-import.git","defaultBranch":"main"}
		]
	}`
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/projects/"+toStrUint(project.ID)+"/repos/import/yunxiao", bytes.NewBufferString(importBody))
	req.Header.Set("Content-Type", "application/json")
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}
}

func TestYunxiaoIntegration_ListMembers_StatusCodeMapping(t *testing.T) {
	r, user, _, credSvc := setupYunxiaoEnv(t)

	cred, err := credSvc.Create(user.ID, "yunxiao-token", "pat", "yunxiao", "token-abc", `{"organizationId":"org-test"}`)
	if err != nil {
		t.Fatalf("create credential failed: %v", err)
	}

	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		http.Error(w, `{"message":"rate limited"}`, http.StatusTooManyRequests)
	}))
	defer mockServer.Close()

	if err := model.DB.Model(&model.RepoCredential{}).
		Where("id = ?", cred.ID).
		Update("extra_config", `{"organizationId":"org-test","endpoint":"`+mockServer.URL+`"}`).
		Error; err != nil {
		t.Fatalf("update credential extra_config failed: %v", err)
	}

	h := NewYunxiaoIntegrationHandler(model.DB)
	r.GET("/integrations/yunxiao/members", h.ListMembers)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodGet, "/integrations/yunxiao/members?credentialId="+toStrUint(cred.ID), nil)
	r.ServeHTTP(w, req)
	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429, got %d: %s", w.Code, w.Body.String())
	}
}

func toStrUint(v uint) string {
	return strconv.FormatUint(uint64(v), 10)
}
