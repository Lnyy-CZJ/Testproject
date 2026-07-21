package handler

import (
	"bug-agent/internal/model"
	"bug-agent/internal/service"
	"bug-agent/testutil"
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

func setupWorkflowRouter(db interface{}) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(gin.Recovery())
	return r
}

func TestWorkflowHandler_TransitionStatus(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupWorkflowRouter(db)
	handler := NewWorkflowHandler(db)
	user := testutil.CreateTestUser(t, db, "wf_handler")
	defect := testutil.CreateTestDefect(t, db, "handler-wf-trans", user.ID)
	db.Model(&defect).Update("status", model.DefectStatusNew)

	router.PUT("/api/defects/:id/transition", func(c *gin.Context) {
		c.Set("user_id", float64(user.ID))
		handler.TransitionStatus(c)
	})

	t.Run("valid transition returns 200", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"defect_id": defect.ID,
			"to_status": model.DefectStatusAnalyzing,
			"comment":   "start analysis",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("PUT", "/api/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/transition", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)

		var resp map[string]interface{}
		json.Unmarshal(w.Body.Bytes(), &resp)
		assert.Equal(t, float64(0), resp["code"])
		assert.NotNil(t, resp["data"])

		data := resp["data"].(map[string]interface{})
		assert.Equal(t, model.DefectStatusAnalyzing, data["to_status"])
	})

	t.Run("invalid transition returns 422 with valid options", func(t *testing.T) {
		db.Model(&defect).Update("status", model.DefectStatusNew)

		body, _ := json.Marshal(map[string]interface{}{
			"defect_id": defect.ID,
			"to_status": model.DefectStatusCompleted,
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("PUT", "/api/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/transition", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusUnprocessableEntity, w.Code)

		var resp map[string]interface{}
		json.Unmarshal(w.Body.Bytes(), &resp)
		assert.Contains(t, resp["message"].(string), "invalid transition")
	})

	t.Run("missing body returns 400", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("PUT", "/api/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/transition", bytes.NewBufferString(`{}`))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code)
	})
}

func TestWorkflowHandler_GetTransitions(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupWorkflowRouter(db)
	handler := NewWorkflowHandler(db)
	user := testutil.CreateTestUser(t, db, "wf_trans_handler")
	defect := testutil.CreateTestDefect(t, db, "handler-wf-gettrans", user.ID)
	db.Model(&defect).Update("status", model.DefectStatusNew)

	router.GET("/api/defects/:id/transitions", handler.GetTransitions)

	t.Run("valid defect returns transitions list", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/transitions", nil)
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)

		var resp map[string]interface{}
		json.Unmarshal(w.Body.Bytes(), &resp)
		assert.Equal(t, float64(0), resp["code"])

		transitions := resp["data"].([]interface{})
		assert.Len(t, transitions, 3)
	})

	t.Run("non-existent defect returns 404", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/defects/999999/transitions", nil)
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusNotFound, w.Code)
	})
}

func TestWorkflowHandler_GetHistory(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupWorkflowRouter(db)
	handler := NewWorkflowHandler(db)
	user := testutil.CreateTestUser(t, db, "wf_hist_handler")
	wfSvc := service.NewWorkflowService(db)
	defect := testutil.CreateTestDefect(t, db, "handler-wf-history", user.ID)
	db.Model(&defect).Update("status", model.DefectStatusNew)

	wfSvc.Transition(&service.TransitionRequest{
		DefectID: defect.ID, ToStatus: model.DefectStatusAnalyzing,
		UserID: user.ID, Comment: "first change",
	})

	router.GET("/api/defects/:id/history", handler.GetHistory)

	t.Run("returns history records", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/history", nil)
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)

		var resp map[string]interface{}
		json.Unmarshal(w.Body.Bytes(), &resp)
		history := resp["data"].([]interface{})
		assert.GreaterOrEqual(t, len(history), 1)
	})
}

func TestWorkflowHandler_BatchTransition(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupWorkflowRouter(db)
	handler := NewWorkflowHandler(db)
	user := testutil.CreateTestUser(t, db, "wf_batch_handler")

	d1 := testutil.CreateTestDefect(t, db, "batch-h-1", user.ID)
	d2 := testutil.CreateTestDefect(t, db, "batch-h-2", user.ID)
	db.Model(&d1).Update("status", model.DefectStatusNew)
	db.Model(&d2).Update("status", model.DefectStatusNew)

	router.POST("/api/workflow/batch", func(c *gin.Context) {
		c.Set("user_id", float64(user.ID))
		handler.BatchTransition(c)
	})

	t.Run("batch transition returns summary", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"defect_ids": []uint{d1.ID, d2.ID},
			"to_status":  model.DefectStatusRejected,
			"comment":    "batch reject",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/api/workflow/batch", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)

		var resp map[string]interface{}
		json.Unmarshal(w.Body.Bytes(), &resp)
		assert.Equal(t, float64(0), resp["code"])
		assert.Equal(t, float64(2), resp["successes"])
	})

	t.Run("empty defect_ids returns 400", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"defect_ids": []uint{},
			"to_status":  model.DefectStatusRejected,
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/api/workflow/batch", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusBadRequest, w.Code)
	})
}
