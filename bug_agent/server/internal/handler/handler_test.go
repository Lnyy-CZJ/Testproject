package handler

import (
	"bug-agent/testutil"
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"gorm.io/gorm"
)

func setupTestRouter(db *gorm.DB) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(gin.Recovery())
	return r
}

func TestCollaborationHandler_StartCollaboration(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewCollaborationHandler(db, nil)
	user := testutil.CreateTestUser(t, db, "collab_handler_user")
	defect := testutil.CreateTestDefect(t, db, "handler-test-defect", user.ID)

	router.POST("/api/collaborations", handler.StartCollaboration)

	t.Run("missing defectId returns 400", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/api/collaborations", bytes.NewBufferString(`{}`))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code)
	})

	t.Run("valid request with nil service returns 500", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"defectId":   defect.ID,
			"agentTypes": []string{"frontend", "backend"},
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/api/collaborations", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusInternalServerError, w.Code)
	})
}

func TestCollaborationHandler_GetCollaborationTask(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewCollaborationHandler(db, nil)

	router.GET("/api/collaborations/:taskId", handler.GetCollaborationTask)

	t.Run("invalid task ID returns 400", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/collaborations/abc", nil)
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code)
	})

	t.Run("non-existent task returns 404", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/collaborations/99999", nil)
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusNotFound, w.Code)
	})
}

func TestRBACHandler_ListRoles(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewRBACHandler(db)
	testutil.CreateTestRoles(t, db)

	router.GET("/api/rbac/roles", handler.ListRoles)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/rbac/roles", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var response map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &response)
	data, ok := response["data"].([]interface{})
	assert.True(t, ok)
	assert.GreaterOrEqual(t, len(data), 4)
}

func TestRBACHandler_CheckPermission(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewRBACHandler(db)

	router.GET("/api/rbac/check", handler.CheckPermission)

	t.Run("missing code parameter returns 400", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/rbac/check", nil)
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code)
	})

	t.Run("valid code returns result", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/rbac/check?code=defects:read", nil)
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)

		var response map[string]interface{}
		json.Unmarshal(w.Body.Bytes(), &response)
		assert.Contains(t, response, "hasPermission")
	})
}

func TestAuditHandler_ListAuditLogs(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewAuditHandler(db)

	router.GET("/api/audit-logs", handler.ListAuditLogs)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/audit-logs?page=1&pageSize=10", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var response map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &response)
	assert.Contains(t, response, "total")
	assert.Contains(t, response, "data")
}

func TestAuditHandler_GetRecentAuditLogs(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewAuditHandler(db)

	router.GET("/api/audit-logs/recent", handler.GetRecentAuditLogs)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/audit-logs/recent?limit=5", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestAuditHandler_GetAuditStats(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewAuditHandler(db)

	router.GET("/api/audit-logs/stats", handler.GetAuditStats)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/audit-logs/stats", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var response map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &response)
	assert.Contains(t, response, "totalLogs")
}
