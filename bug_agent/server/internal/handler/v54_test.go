package handler

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestManualFixHandler_StartManualFix(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewManualFixHandler(db)
	user := testutil.CreateTestUser(t, db, "manual_fix_user")
	defect := testutil.CreateTestDefect(t, db, "manual-fix-defect", user.ID)

	db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusPendingFix)

	router.POST("/defects/:id/manual-fix/start", handler.StartManualFix)

	t.Run("success - status changes to manual_fixing", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", fmt.Sprintf("/defects/%d/manual-fix/start", defect.ID), nil)
		router.ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code)

		var updated model.Defect
		db.First(&updated, defect.ID)
		assert.Equal(t, model.DefectStatusManualFixing, updated.Status)
	})

	t.Run("wrong status returns error", func(t *testing.T) {
		db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusNew)
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", fmt.Sprintf("/defects/%d/manual-fix/start", defect.ID), nil)
		router.ServeHTTP(w, req)
		assert.NotEqual(t, http.StatusOK, w.Code)
	})

	t.Run("invalid defect id returns error", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/defects/99999/manual-fix/start", nil)
		router.ServeHTTP(w, req)
		assert.NotEqual(t, http.StatusOK, w.Code)
	})
}

func TestManualFixHandler_CompleteManualFix(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewManualFixHandler(db)
	user := testutil.CreateTestUser(t, db, "manual_fix_complete_user")
	defect := testutil.CreateTestDefect(t, db, "manual-fix-complete", user.ID)

	db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusManualFixing)

	router.POST("/defects/:id/manual-fix/complete", handler.CompleteManualFix)

	t.Run("success - creates FixTask and changes status to pending_verify", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"description": "Manual fix description",
			"prUrl":       "https://github.com/org/repo/pull/1",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", fmt.Sprintf("/defects/%d/manual-fix/complete", defect.ID), bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code)

		var updated model.Defect
		db.First(&updated, defect.ID)
		assert.Equal(t, model.DefectStatusPendingVerify, updated.Status)

		var fixTasks []model.FixTask
		db.Where("defect_id = ?", defect.ID).Find(&fixTasks)
		assert.Equal(t, 1, len(fixTasks))
		assert.Equal(t, "manual", fixTasks[0].Source)
		assert.Equal(t, "Manual fix description", fixTasks[0].ManualDescription)
	})

	t.Run("missing description returns error", func(t *testing.T) {
		db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusManualFixing)
		body, _ := json.Marshal(map[string]interface{}{
			"prUrl": "https://github.com/org/repo/pull/1",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", fmt.Sprintf("/defects/%d/manual-fix/complete", defect.ID), bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)
		assert.NotEqual(t, http.StatusOK, w.Code)
	})
}

func TestManualFixHandler_AbandonManualFix(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewManualFixHandler(db)
	user := testutil.CreateTestUser(t, db, "manual_fix_abandon_user")
	defect := testutil.CreateTestDefect(t, db, "manual-fix-abandon", user.ID)

	db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusManualFixing)

	router.POST("/defects/:id/manual-fix/abandon", handler.AbandonManualFix)

	t.Run("success - status reverts to pending_fix", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", fmt.Sprintf("/defects/%d/manual-fix/abandon", defect.ID), nil)
		router.ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code)

		var updated model.Defect
		db.First(&updated, defect.ID)
		assert.Equal(t, model.DefectStatusPendingFix, updated.Status)
	})
}

func TestPRLifecycleHandler_ManualRejectPR(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewPRLifecycleHandler(db)
	user := testutil.CreateTestUser(t, db, "pr_reject_user")
	defect := testutil.CreateTestDefect(t, db, "pr-reject-defect", user.ID)

	fixTask := model.FixTask{
		TaskCode:  "FIX-PR-REJECT-001",
		DefectID:  defect.ID,
		AgentType: "frontend",
		Status:    "completed",
		PRURL:     "https://github.com/org/repo/pull/1",
		PRNumber:  "1",
		PRStatus:  "open",
		Source:    "auto",
	}
	db.Create(&fixTask)

	db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusPendingVerify)

	router.POST("/defects/:id/fix-tasks/:taskId/reject", handler.ManualRejectPR)

	t.Run("success - PR rejected, defect reverts to pending_fix", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"rejectedBy":   "reviewer",
			"rejectReason": "Code style issues",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", fmt.Sprintf("/defects/%d/fix-tasks/%d/reject", defect.ID, fixTask.ID), bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code)

		var updated model.Defect
		db.First(&updated, defect.ID)
		assert.Equal(t, model.DefectStatusPendingFix, updated.Status)

		var updatedTask model.FixTask
		db.First(&updatedTask, fixTask.ID)
		assert.Equal(t, "rejected", updatedTask.PRStatus)

		var rejections []model.PRRejection
		db.Where("fix_task_id = ?", fixTask.ID).Find(&rejections)
		assert.Equal(t, 1, len(rejections))
		assert.Equal(t, "Code style issues", rejections[0].RejectReason)
	})
}

func TestPRLifecycleHandler_ManualMergePR(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewPRLifecycleHandler(db)
	user := testutil.CreateTestUser(t, db, "pr_merge_user")
	defect := testutil.CreateTestDefect(t, db, "pr-merge-defect", user.ID)

	fixTask := model.FixTask{
		TaskCode:  "FIX-PR-MERGE-001",
		DefectID:  defect.ID,
		AgentType: "frontend",
		Status:    "completed",
		PRURL:     "https://github.com/org/repo/pull/2",
		PRNumber:  "2",
		PRStatus:  "open",
		Source:    "auto",
	}
	db.Create(&fixTask)

	db.Model(&model.Defect{}).Where("id = ?", defect.ID).Update("status", model.DefectStatusPendingVerify)

	router.POST("/defects/:id/fix-tasks/:taskId/merge", handler.ManualMergePR)

	t.Run("success - PR merged, defect advances to fixed", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", fmt.Sprintf("/defects/%d/fix-tasks/%d/merge", defect.ID, fixTask.ID), nil)
		router.ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code)

		var updated model.Defect
		db.First(&updated, defect.ID)
		assert.Equal(t, model.DefectStatusFixed, updated.Status)

		var updatedTask model.FixTask
		db.First(&updatedTask, fixTask.ID)
		assert.Equal(t, "merged", updatedTask.PRStatus)
	})
}

func TestPRLifecycleHandler_ListPRRejections(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewPRLifecycleHandler(db)
	user := testutil.CreateTestUser(t, db, "pr_list_user")
	defect := testutil.CreateTestDefect(t, db, "pr-list-defect", user.ID)

	fixTask := model.FixTask{
		TaskCode:  "FIX-PR-LIST-001",
		DefectID:  defect.ID,
		AgentType: "frontend",
		Status:    "completed",
		PRURL:     "https://github.com/org/repo/pull/3",
		PRNumber:  "3",
		PRStatus:  "rejected",
		Source:    "auto",
	}
	db.Create(&fixTask)

	rejection := model.PRRejection{
		FixTaskID:    fixTask.ID,
		PRNumber:     "3",
		PRURL:        "https://github.com/org/repo/pull/3",
		RejectedBy:   "reviewer",
		RejectReason: "Needs more tests",
		VCSProvider:  "manual",
		CreatedAt:    time.Now(),
	}
	db.Create(&rejection)

	router.GET("/defects/:id/fix-tasks/:taskId/rejections", handler.ListPRRejections)

	t.Run("returns rejection list", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", fmt.Sprintf("/defects/%d/fix-tasks/%d/rejections", defect.ID, fixTask.ID), nil)
		router.ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code)
	})
}

func TestAgentMemoryHandler_CreateAndListProjectMemories(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewAgentMemoryHandler(db)
	project := testutil.CreateTestProject(t, db, "memory_test_proj", "MTP")

	router.GET("/projects/:id/memories", handler.ListProjectMemories)
	router.POST("/projects/:id/memories", handler.CreateProjectMemory)

	t.Run("create and list project memories", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"category": "architecture",
			"content":  "This project uses Next.js App Router",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", fmt.Sprintf("/projects/%d/memories", project.ID), bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)
		assert.Equal(t, http.StatusCreated, w.Code)

		w2 := httptest.NewRecorder()
		req2, _ := http.NewRequest("GET", fmt.Sprintf("/projects/%d/memories", project.ID), nil)
		router.ServeHTTP(w2, req2)
		assert.Equal(t, http.StatusOK, w2.Code)
	})
}

func TestAgentMemoryHandler_UpdateAndDeleteMemory(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewAgentMemoryHandler(db)
	project := testutil.CreateTestProject(t, db, "memory_ud_proj", "MUP")

	memory := model.AgentMemory{
		ProjectID:      project.ID,
		Category:       "convention",
		Content:        "Use camelCase for variables",
		Source:         "manual",
		RelevanceScore: 0.5,
		Enabled:        true,
		CreatedAt:      time.Now(),
		UpdatedAt:      time.Now(),
	}
	db.Create(&memory)

	router.PUT("/projects/:id/memories/:memoryId", handler.UpdateMemory)
	router.DELETE("/projects/:id/memories/:memoryId", handler.DeleteMemory)
	router.PATCH("/projects/:id/memories/:memoryId/toggle", handler.ToggleMemory)

	t.Run("update memory content", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{
			"content": "Use camelCase for all identifiers",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("PUT", fmt.Sprintf("/projects/%d/memories/%d", project.ID, memory.ID), bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code)
	})

	t.Run("toggle memory enabled status", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("PATCH", fmt.Sprintf("/projects/%d/memories/%d/toggle", project.ID, memory.ID), nil)
		router.ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code)
	})

	t.Run("delete memory", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("DELETE", fmt.Sprintf("/projects/%d/memories/%d", project.ID, memory.ID), nil)
		router.ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code)
	})
}

func TestVCSWebhookHandler_HandleWebhook(t *testing.T) {
	db := testutil.SetupTestDB(t)
	router := setupTestRouter(db)
	handler := NewVCSWebhookHandler(db)

	router.POST("/inbound/vcs/webhook", handler.HandleWebhook)

	t.Run("missing provider returns error", func(t *testing.T) {
		body, _ := json.Marshal(map[string]interface{}{"action": "closed"})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/inbound/vcs/webhook", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)
		assert.NotEqual(t, http.StatusOK, w.Code)
	})
}
