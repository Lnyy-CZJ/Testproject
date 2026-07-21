package service

import (
	"bug-agent/internal/model"
	"bug-agent/testutil"
	"fmt"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestWorkflowService_Transition(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewWorkflowService(db)
	user := testutil.CreateTestUser(t, db, "wf_user")
	defect := testutil.CreateTestDefect(t, db, "wf-transition", user.ID)

	t.Run("valid transition new->analyzing", func(t *testing.T) {
		db.Model(&defect).Update("status", model.DefectStatusNew)

		change, err := svc.Transition(&TransitionRequest{
			DefectID: defect.ID,
			ToStatus: model.DefectStatusAnalyzing,
			UserID:   user.ID,
			Comment:  "start analysis",
		})

		assert.NoError(t, err)
		assert.Equal(t, defect.ID, change.DefectID)
		assert.Equal(t, model.DefectStatusNew, change.FromStatus)
		assert.Equal(t, model.DefectStatusAnalyzing, change.ToStatus)
		assert.Equal(t, user.ID, change.ChangedBy)
		assert.Equal(t, "start analysis", change.Comment)
		assert.Greater(t, change.ID, uint(0))

		var updated model.Defect
		db.First(&updated, defect.ID)
		assert.Equal(t, model.DefectStatusAnalyzing, updated.Status)
	})

	t.Run("invalid transition returns error with valid options", func(t *testing.T) {
		db.Model(&defect).Update("status", model.DefectStatusNew)

		_, err := svc.Transition(&TransitionRequest{
			DefectID: defect.ID,
			ToStatus: model.DefectStatusCompleted,
			UserID:   user.ID,
		})

		assert.Error(t, err)
		assert.Contains(t, err.Error(), "invalid transition")
		assert.Contains(t, err.Error(), "valid:")
	})

	t.Run("non-existent defect returns error", func(t *testing.T) {
		_, err := svc.Transition(&TransitionRequest{
			DefectID: 999999,
			ToStatus: model.DefectStatusAnalyzing,
			UserID:   user.ID,
		})

		assert.Error(t, err)
		assert.Contains(t, err.Error(), "defect not found")
	})

	t.Run("self-transition is invalid", func(t *testing.T) {
		db.Model(&defect).Update("status", model.DefectStatusAnalyzing)

		_, err := svc.Transition(&TransitionRequest{
			DefectID: defect.ID,
			ToStatus: model.DefectStatusAnalyzing,
			UserID:   user.ID,
		})

		assert.Error(t, err)
	})
}

func TestWorkflowService_FullLifecycle(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewWorkflowService(db)
	user := testutil.CreateTestUser(t, db, "wf_lifecycle")
	defect := testutil.CreateTestDefect(t, db, "wf-lifecycle-full", user.ID)
	db.Model(&defect).Update("status", model.DefectStatusNew)

	steps := []struct {
		toStatus string
		comment  string
	}{
		{model.DefectStatusPendingAssign, "assigned to team"},
		{model.DefectStatusPendingAnalysis, "queued for analysis"},
		{model.DefectStatusAnalyzing, "analyzing root cause"},
		{model.DefectStatusPendingFix, "ready for fix"},
		{model.DefectStatusFixing, "developer working"},
		{model.DefectStatusPendingVerify, "fix done, verify"},
		{model.DefectStatusFixed, "verified fixed"},
		{model.DefectStatusCompleted, "all good"},
	}

	for i, step := range steps {
		t.Run(fmt.Sprintf("step%d_%s", i+1, step.toStatus), func(t *testing.T) {
			change, err := svc.Transition(&TransitionRequest{
				DefectID: defect.ID,
				ToStatus: step.toStatus,
				UserID:   user.ID,
				Comment:  step.comment,
			})
			assert.NoError(t, err, "step %d failed: %s -> %s", i+1, step.toStatus)
			assert.Equal(t, step.toStatus, change.ToStatus)
		})
	}

	var finalDefect model.Defect
	db.First(&finalDefect, defect.ID)
	assert.Equal(t, model.DefectStatusCompleted, finalDefect.Status)
}

func TestWorkflowService_ReopenCycle(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewWorkflowService(db)
	user := testutil.CreateTestUser(t, db, "wf_reopen")
	defect := testutil.CreateTestDefect(t, db, "wf-reopen-cycle", user.ID)
	db.Model(&defect).Update("status", model.DefectStatusCompleted)

	reopenSteps := []struct {
		toStatus string
		comment  string
	}{
		{model.DefectStatusReopened, "bug came back"},
		{model.DefectStatusAnalyzing, "re-analyzing"},
		{model.DefectStatusPendingFix, "need fix again"},
		{model.DefectStatusFixing, "fixing again"},
		{model.DefectStatusPendingVerify, "re-verify"},
		{model.DefectStatusFixed, "fixed again"},
		{model.DefectStatusCompleted, "done"},
	}

	for i, step := range reopenSteps {
		change, err := svc.Transition(&TransitionRequest{
			DefectID: defect.ID,
			ToStatus: step.toStatus,
			UserID:   user.ID,
			Comment:  step.comment,
		})
		assert.NoError(t, err, "reopen step %d failed", i+1)
		assert.Equal(t, step.toStatus, change.ToStatus)
	}
}

func TestWorkflowService_GetHistory(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewWorkflowService(db)
	user := testutil.CreateTestUser(t, db, "wf_history")
	defect := testutil.CreateTestDefect(t, db, "wf-history-test", user.ID)
	db.Model(&defect).Update("status", model.DefectStatusNew)

	svc.Transition(&TransitionRequest{
		DefectID: defect.ID, ToStatus: model.DefectStatusAnalyzing,
		UserID: user.ID, Comment: "step1",
	})
	svc.Transition(&TransitionRequest{
		DefectID: defect.ID, ToStatus: model.DefectStatusPendingFix,
		UserID: user.ID, Comment: "step2",
	})
	svc.Transition(&TransitionRequest{
		DefectID: defect.ID, ToStatus: model.DefectStatusFixing,
		UserID: user.ID, Comment: "step3",
	})

	history, err := svc.GetHistory(defect.ID)
	assert.NoError(t, err)
	assert.Len(t, history, 3)

	comments := make(map[string]string)
	for _, h := range history {
		comments[h.Comment] = h.FromStatus
	}
	assert.Equal(t, model.DefectStatusNew, comments["step1"])
	assert.Equal(t, model.DefectStatusAnalyzing, comments["step2"])
	assert.Equal(t, model.DefectStatusPendingFix, comments["step3"])
}

func TestWorkflowService_GetAvailableTransitions(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewWorkflowService(db)
	user := testutil.CreateTestUser(t, db, "wf_trans")
	defect := testutil.CreateTestDefect(t, db, "wf-transitions", user.ID)

	t.Run("new status transitions", func(t *testing.T) {
		db.Model(&defect).Update("status", model.DefectStatusNew)

		transitions, err := svc.GetAvailableTransitions(defect.ID)
		assert.NoError(t, err)
		assert.Len(t, transitions, 3)
		assert.Contains(t, transitions, model.DefectStatusPendingAssign)
		assert.Contains(t, transitions, model.DefectStatusAnalyzing)
		assert.Contains(t, transitions, model.DefectStatusRejected)
	})

	t.Run("completed only allows reopen", func(t *testing.T) {
		db.Model(&defect).Update("status", model.DefectStatusCompleted)

		transitions, err := svc.GetAvailableTransitions(defect.ID)
		assert.NoError(t, err)
		assert.Len(t, transitions, 1)
		assert.Equal(t, model.DefectStatusReopened, transitions[0])
	})

	t.Run("non-existent defect returns error", func(t *testing.T) {
		_, err := svc.GetAvailableTransitions(999999)
		assert.Error(t, err)
		assert.Contains(t, err.Error(), "defect not found")
	})
}

func TestWorkflowService_BatchTransition(t *testing.T) {
	db := testutil.SetupTestDB(t)
	svc := NewWorkflowService(db)
	user := testutil.CreateTestUser(t, db, "wf_batch")

	d1 := testutil.CreateTestDefect(t, db, "batch-1", user.ID)
	d2 := testutil.CreateTestDefect(t, db, "batch-2", user.ID)
	d3 := testutil.CreateTestDefect(t, db, "batch-3", user.ID)

	db.Model(&d1).Update("status", model.DefectStatusNew)
	db.Model(&d2).Update("status", model.DefectStatusNew)
	db.Model(&d3).Update("status", model.DefectStatusCompleted)

	successes, errs := svc.BatchTransition(
		[]uint{d1.ID, d2.ID, d3.ID},
		model.DefectStatusRejected,
		user.ID,
		"batch close",
	)

	assert.Equal(t, 2, successes)
	assert.Len(t, errs, 1)
	assert.Contains(t, errs[0].Error(), fmt.Sprintf("defect %d", d3.ID))

	var def1, def2, def3 model.Defect
	db.First(&def1, d1.ID)
	db.First(&def2, d2.ID)
	db.First(&def3, d3.ID)
	assert.Equal(t, model.DefectStatusRejected, def1.Status)
	assert.Equal(t, model.DefectStatusRejected, def2.Status)
	assert.Equal(t, model.DefectStatusCompleted, def3.Status)
}
