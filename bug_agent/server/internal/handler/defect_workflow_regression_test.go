package handler

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestDefectHandler_AssignAndChangeStatus_FollowsPRDWorkflow(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	h := NewDefectHandler(model.DB)

	reporter := testutil.CreateTestUser(t, db, "defect_workflow_reporter")
	assignee := testutil.CreateTestUser(t, db, "defect_workflow_assignee")
	defect := testutil.CreateTestDefect(t, db, "defect-workflow-regression", reporter.ID)
	db.Model(&defect).Update("status", model.DefectStatusPendingAssign)

	router.PUT("/defects/:id/assign", h.AssignDefect)
	router.PUT("/defects/:id/status", h.ChangeStatus)

	t.Run("assign moves pending_assign to pending_analysis", func(t *testing.T) {
		body, _ := json.Marshal(map[string]any{
			"assigneeId": assignee.ID,
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodPut, "/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/assign", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)

		var updated model.Defect
		db.First(&updated, defect.ID)
		assert.NotNil(t, updated.AssigneeID)
		assert.Equal(t, assignee.ID, *updated.AssigneeID)
		assert.Contains(t, []string{model.DefectStatusPendingAnalysis, model.DefectStatusAnalyzing, model.DefectStatusPendingFix}, updated.Status,
			"分配后状态应为 pending_analysis 或异步分析后的状态")
	})

	t.Run("pending_analysis can move to analyzing", func(t *testing.T) {
		db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusPendingAnalysis)

		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodPut, "/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/status", bytes.NewBufferString(`{"status":"analyzing"}`))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code, w.Body.String())

		var updated model.Defect
		db.First(&updated, defect.ID)
		assert.Equal(t, model.DefectStatusAnalyzing, updated.Status)
	})

	t.Run("analyzing can move to pending_fix", func(t *testing.T) {
		db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusAnalyzing)

		w := httptest.NewRecorder()
		req, _ := http.NewRequest(http.MethodPut, "/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/status", bytes.NewBufferString(`{"status":"pending_fix"}`))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code, w.Body.String())

		var updated model.Defect
		db.First(&updated, defect.ID)
		assert.Equal(t, model.DefectStatusPendingFix, updated.Status)
	})
}

func TestDefectHandler_AssignAutoTriggersAnalysis(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	h := NewDefectHandler(model.DB)

	reporter := testutil.CreateTestUser(t, db, "auto_trigger_reporter")
	assignee := testutil.CreateTestUser(t, db, "auto_trigger_assignee")
	defect := testutil.CreateTestDefect(t, db, "auto-trigger-defect", reporter.ID)
	db.Model(&defect).Update("status", model.DefectStatusPendingAssign)

	router.PUT("/defects/:id/assign", h.AssignDefect)

	body, _ := json.Marshal(map[string]any{
		"assigneeId": assignee.ID,
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest(http.MethodPut, "/defects/"+strconv.FormatUint(uint64(defect.ID), 10)+"/assign", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	time.Sleep(2 * time.Second)

	var updated model.Defect
	db.First(&updated, defect.ID)
	assert.NotEqual(t, model.DefectStatusPendingAnalysis, updated.Status,
		"分配后异步分析应已触发，状态不应停留在 pending_analysis")
}
