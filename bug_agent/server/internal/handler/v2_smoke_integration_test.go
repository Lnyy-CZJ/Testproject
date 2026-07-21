package handler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"bug-agent/internal/model"
	"bug-agent/testutil"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

func TestV2Smoke_EndToEndFlow(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := testutil.SetupTestDB(t)
	model.DB = db

	inviter := testutil.CreateTestUser(t, db, "smoke_inviter")

	r := setupV2SmokeRouter(db)

	// 1) 邀请码创建与校验
	createInviteResp := doJSONRequest(t, r, "POST", "/invites", inviter.ID, map[string]any{
		"maxUses": 1,
	})
	if createInviteResp.Code != http.StatusCreated {
		t.Fatalf("create invite failed: %d %s", createInviteResp.Code, createInviteResp.Body.String())
	}
	inviteCode := mustJSONPathString(t, createInviteResp.Body.Bytes(), "data.code")
	if inviteCode == "" {
		t.Fatalf("invite code is empty: %s", createInviteResp.Body.String())
	}

	validateInviteResp := doJSONRequest(t, r, "GET", "/invites/"+inviteCode+"/validate", 0, nil)
	if validateInviteResp.Code != http.StatusOK {
		t.Fatalf("validate invite failed: %d %s", validateInviteResp.Code, validateInviteResp.Body.String())
	}

	// 2) 邀请注册链接注册新用户
	username := fmt.Sprintf("smoke_user_%d", time.Now().UnixNano())
	acceptInviteResp := doJSONRequest(t, r, "POST", "/invites/"+inviteCode+"/accept", 0, map[string]any{
		"username": username,
		"email":    username + "@example.com",
		"password": "smoke_password_123456",
		"nickname": "Smoke User",
	})
	if acceptInviteResp.Code != http.StatusCreated {
		t.Fatalf("accept invite failed: %d %s", acceptInviteResp.Code, acceptInviteResp.Body.String())
	}
	invitedUserID := uint(mustJSONPathFloat(t, acceptInviteResp.Body.Bytes(), "data.user.id"))
	if invitedUserID == 0 {
		t.Fatalf("invited user id invalid: %s", acceptInviteResp.Body.String())
	}

	// 3) 个人信息与 AGENT 身份更新
	getMeResp := doJSONRequest(t, r, "GET", "/users/me", invitedUserID, nil)
	if getMeResp.Code != http.StatusOK {
		t.Fatalf("get profile failed: %d %s", getMeResp.Code, getMeResp.Body.String())
	}

	updateAgentResp := doJSONRequest(t, r, "PUT", "/users/me/agent-types", invitedUserID, map[string]any{
		"agentTypes": []string{"frontend", "backend"},
	})
	if updateAgentResp.Code != http.StatusOK {
		t.Fatalf("update my agent types failed: %d %s", updateAgentResp.Code, updateAgentResp.Body.String())
	}

	// 4) 项目创建 + 项目切换数据源（用户项目列表）
	projectCode := fmt.Sprintf("SMK%d", time.Now().Unix()%100000)
	createProjectResp := doJSONRequest(t, r, "POST", "/projects", invitedUserID, map[string]any{
		"name":        "Smoke Project",
		"code":        projectCode,
		"description": "v2 smoke flow project",
	})
	if createProjectResp.Code != http.StatusCreated {
		t.Fatalf("create project failed: %d %s", createProjectResp.Code, createProjectResp.Body.String())
	}
	projectID := uint(mustJSONPathFloat(t, createProjectResp.Body.Bytes(), "data.id"))
	if projectID == 0 {
		t.Fatalf("project id invalid: %s", createProjectResp.Body.String())
	}

	userProjectsResp := doJSONRequest(t, r, "GET", "/user/projects", invitedUserID, nil)
	if userProjectsResp.Code != http.StatusOK {
		t.Fatalf("list user projects failed: %d %s", userProjectsResp.Code, userProjectsResp.Body.String())
	}

	// 5) 凭证 + 仓库 + 仓库测试连接
	createCredResp := doJSONRequest(t, r, "POST", "/credentials", invitedUserID, map[string]any{
		"name":     "Smoke Generic Credential",
		"type":     "pat",
		"provider": "generic",
		"content":  "smoke-token-123",
	})
	if createCredResp.Code != http.StatusCreated {
		t.Fatalf("create credential failed: %d %s", createCredResp.Code, createCredResp.Body.String())
	}
	credentialID := uint(mustJSONPathFloat(t, createCredResp.Body.Bytes(), "data.id"))

	createRepoResp := doJSONRequest(t, r, "POST", fmt.Sprintf("/projects/%d/repos", projectID), invitedUserID, map[string]any{
		"name":          "smoke-repo",
		"repoUrl":       "file:///tmp/smoke-not-exists-repo.git",
		"sourceType":    "custom",
		"credentialId":  credentialID,
		"agentTypes":    "backend,test",
		"defaultBranch": "main",
	})
	if createRepoResp.Code != http.StatusCreated {
		t.Fatalf("create repo failed: %d %s", createRepoResp.Code, createRepoResp.Body.String())
	}
	repoID := uint(mustJSONPathFloat(t, createRepoResp.Body.Bytes(), "data.id"))

	testConnResp := doJSONRequest(t, r, "POST", fmt.Sprintf("/repos/%d/test-connection", repoID), invitedUserID, nil)
	if testConnResp.Code != http.StatusOK {
		t.Fatalf("repo test connection failed: %d %s", testConnResp.Code, testConnResp.Body.String())
	}
	_, ok := mustJSONPath(t, testConnResp.Body.Bytes(), "data.success").(bool)
	if !ok {
		t.Fatalf("repo test connection response missing success bool: %s", testConnResp.Body.String())
	}

	// 6) 通知偏好获取与更新
	getPrefsResp := doJSONRequest(t, r, "GET", "/notification-preferences", invitedUserID, nil)
	if getPrefsResp.Code != http.StatusOK {
		t.Fatalf("get notification preferences failed: %d %s", getPrefsResp.Code, getPrefsResp.Body.String())
	}

	updatePrefsResp := doJSONRequest(t, r, "PUT", "/notification-preferences", invitedUserID, map[string]any{
		"updates": map[string]any{
			"iteration_start": "in_app,webhook",
		},
	})
	if updatePrefsResp.Code != http.StatusOK {
		t.Fatalf("update notification preferences failed: %d %s", updatePrefsResp.Code, updatePrefsResp.Body.String())
	}

	// 7) 协作分析链路（创建迭代+缺陷后启动协作）
	now := time.Now()
	iteration := model.Iteration{
		ProjectID: projectID,
		Name:      "Smoke Iteration",
		StartDate: now,
		EndDate:   now.Add(7 * 24 * time.Hour),
		Status:    "active",
	}
	if err := db.Create(&iteration).Error; err != nil {
		t.Fatalf("create iteration failed: %v", err)
	}

	defect := model.Defect{
		Code:        fmt.Sprintf("BUG-%s-%s-001", projectCode, now.Format("200601")),
		IterationID: iteration.ID,
		Title:       "Smoke defect for collaboration",
		Description: "smoke defect",
		Severity:    "normal",
		Priority:    "P2",
		Type:        "functional",
		Status:      model.DefectStatusPendingAnalysis,
		ReporterID:  invitedUserID,
	}
	if err := db.Create(&defect).Error; err != nil {
		t.Fatalf("create defect failed: %v", err)
	}

	startCollabResp := doJSONRequest(t, r, "POST", "/collaborations", invitedUserID, map[string]any{
		"defectId":   defect.ID,
		"agentTypes": []string{"backend"},
	})
	if startCollabResp.Code != http.StatusOK {
		t.Fatalf("start collaboration failed: %d %s", startCollabResp.Code, startCollabResp.Body.String())
	}
	taskID := uint(mustJSONPathFloat(t, startCollabResp.Body.Bytes(), "data.id"))
	if taskID == 0 {
		t.Fatalf("collaboration task id invalid: %s", startCollabResp.Body.String())
	}

	waitForCollaborationDone(t, r, invitedUserID, taskID)

	reportResp := doJSONRequest(t, r, "GET", fmt.Sprintf("/collaborations/%d/report", taskID), invitedUserID, nil)
	if reportResp.Code != http.StatusOK {
		t.Fatalf("get aggregated report failed: %d %s", reportResp.Code, reportResp.Body.String())
	}
	gotTaskID := uint(mustJSONPathFloat(t, reportResp.Body.Bytes(), "data.taskId"))
	if gotTaskID != taskID {
		t.Fatalf("aggregated report taskId mismatch: got=%d want=%d", gotTaskID, taskID)
	}
}

func setupV2SmokeRouter(db *gorm.DB) *gin.Engine {
	r := gin.New()
	r.Use(func(c *gin.Context) {
		raw := strings.TrimSpace(c.GetHeader("X-User-ID"))
		if raw != "" {
			if id, err := strconv.ParseUint(raw, 10, 64); err == nil && id > 0 {
				c.Set("userId", uint(id))
				c.Set("user_id", uint(id))
			}
		}
		c.Next()
	})

	inviteHandler := NewInviteHandler(db)
	authHandler := NewAuthHandler(model.DB)
	projectHandler := NewProjectHandler(model.DB)
	userProjectsHandler := NewUserProjectsHandler(model.DB)
	credentialHandler := NewCredentialHandler(db)
	projectRepoHandler := NewProjectRepoHandler(model.DB)
	prefHandler := NewNotificationPrefHandler(db)
	collaborationHandler := NewCollaborationHandler(db, nil)

	r.POST("/invites", inviteHandler.CreateInvite)
	r.GET("/invites/:code/validate", inviteHandler.ValidateInvite)
	r.POST("/invites/:code/accept", inviteHandler.AcceptInvite)

	r.GET("/users/me", authHandler.GetProfile)
	r.PUT("/users/me", authHandler.UpdateProfile)
	r.PUT("/users/me/agent-types", authHandler.UpdateMyAgentTypes)

	r.POST("/projects", projectHandler.CreateProject)
	r.GET("/user/projects", userProjectsHandler.ListUserProjects)

	r.POST("/credentials", credentialHandler.CreateCredential)
	r.POST("/projects/:id/repos", projectRepoHandler.CreateRepo)
	r.POST("/repos/:id/test-connection", credentialHandler.TestConnection)

	r.GET("/notification-preferences", prefHandler.GetPreferences)
	r.PUT("/notification-preferences", prefHandler.BatchUpdate)

	r.POST("/collaborations", collaborationHandler.StartCollaboration)
	r.GET("/collaborations/:taskId", collaborationHandler.GetCollaborationTask)
	r.GET("/collaborations/:taskId/report", collaborationHandler.GetAggregatedReport)

	return r
}

func doJSONRequest(
	t *testing.T,
	r *gin.Engine,
	method string,
	path string,
	userID uint,
	body map[string]any,
) *httptest.ResponseRecorder {
	t.Helper()

	var payload []byte
	var err error
	if body != nil {
		payload, err = json.Marshal(body)
		if err != nil {
			t.Fatalf("marshal body failed: %v", err)
		}
	}

	req, err := http.NewRequest(method, path, bytes.NewReader(payload))
	if err != nil {
		t.Fatalf("new request failed: %v", err)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if userID > 0 {
		req.Header.Set("X-User-ID", strconv.FormatUint(uint64(userID), 10))
	}

	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func waitForCollaborationDone(t *testing.T, r *gin.Engine, userID uint, taskID uint) {
	t.Helper()

	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		resp := doJSONRequest(t, r, "GET", fmt.Sprintf("/collaborations/%d", taskID), userID, nil)
		if resp.Code != http.StatusOK {
			time.Sleep(300 * time.Millisecond)
			continue
		}

		status := mustJSONPathString(t, resp.Body.Bytes(), "data.status")
		switch status {
		case model.CollaborationStatusCompleted:
			return
		case model.CollaborationStatusFailed, model.CollaborationStatusTimeout:
			t.Fatalf("collaboration ended unexpectedly: status=%s body=%s", status, resp.Body.String())
		}

		time.Sleep(300 * time.Millisecond)
	}
	t.Fatalf("collaboration did not complete before timeout: taskID=%d", taskID)
}

func mustJSONPath(t *testing.T, payload []byte, path string) any {
	t.Helper()
	var obj map[string]any
	if err := json.Unmarshal(payload, &obj); err != nil {
		t.Fatalf("unmarshal response failed: %v; body=%s", err, string(payload))
	}
	current := any(obj)
	for _, part := range strings.Split(path, ".") {
		m, ok := current.(map[string]any)
		if !ok {
			t.Fatalf("path %s not found in %s", path, string(payload))
		}
		next, exists := m[part]
		if !exists {
			t.Fatalf("path %s not found in %s", path, string(payload))
		}
		current = next
	}
	return current
}

func mustJSONPathString(t *testing.T, payload []byte, path string) string {
	t.Helper()
	v := mustJSONPath(t, payload, path)
	s, ok := v.(string)
	if !ok {
		t.Fatalf("path %s is not string: %T (%v)", path, v, v)
	}
	return s
}

func mustJSONPathFloat(t *testing.T, payload []byte, path string) float64 {
	t.Helper()
	v := mustJSONPath(t, payload, path)
	f, ok := v.(float64)
	if !ok {
		t.Fatalf("path %s is not number: %T (%v)", path, v, v)
	}
	return f
}
