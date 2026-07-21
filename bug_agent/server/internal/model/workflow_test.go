package model

import (
	"fmt"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestIsValidDefectTransition_ValidTransitions(t *testing.T) {
	tests := []struct {
		name     string
		from     string
		to       string
		expected bool
	}{
		{"new->pending_assign", DefectStatusNew, DefectStatusPendingAssign, true},
		{"new->pending_analysis", DefectStatusNew, DefectStatusPendingAnalysis, true},
		{"new->analyzing", DefectStatusNew, DefectStatusAnalyzing, true},
		{"new->rejected", DefectStatusNew, DefectStatusRejected, true},
		{"pending_assign->pending_analysis", DefectStatusPendingAssign, DefectStatusPendingAnalysis, true},
		{"pending_analysis->analyzing", DefectStatusPendingAnalysis, DefectStatusAnalyzing, true},
		{"pending_analysis->pending_assign", DefectStatusPendingAnalysis, DefectStatusPendingAssign, true},
		{"pending_analysis->rejected", DefectStatusPendingAnalysis, DefectStatusRejected, true},
		{"analyzing->pending_fix", DefectStatusAnalyzing, DefectStatusPendingFix, true},
		{"analyzing->pending_assign", DefectStatusAnalyzing, DefectStatusPendingAssign, true},
		{"analyzing->rejected", DefectStatusAnalyzing, DefectStatusRejected, true},
		{"pending_fix->fixing", DefectStatusPendingFix, DefectStatusFixing, true},
		{"pending_fix->suspended", DefectStatusPendingFix, DefectStatusSuspended, true},
		{"fixing->pending_fix", DefectStatusFixing, DefectStatusPendingFix, true},
		{"fixing->pending_verify", DefectStatusFixing, DefectStatusPendingVerify, true},
		{"fixing->rejected", DefectStatusFixing, DefectStatusRejected, true},
		{"manual_fixing->rejected", DefectStatusManualFixing, DefectStatusRejected, true},
		{"pending_verify->rejected", DefectStatusPendingVerify, DefectStatusRejected, true},
		{"pending_verify->fixed", DefectStatusPendingVerify, DefectStatusFixed, true},
		{"pending_verify->pending_fix", DefectStatusPendingVerify, DefectStatusPendingFix, true},
		{"fixed->completed", DefectStatusFixed, DefectStatusCompleted, true},
		{"completed->reopened", DefectStatusCompleted, DefectStatusReopened, true},
		{"rejected->reopened", DefectStatusRejected, DefectStatusReopened, true},
		{"suspended->reopened", DefectStatusSuspended, DefectStatusReopened, true},
		{"suspended->pending_fix", DefectStatusSuspended, DefectStatusPendingFix, true},
		{"reopened->analyzing", DefectStatusReopened, DefectStatusAnalyzing, true},
		{"reopened->pending_fix", DefectStatusReopened, DefectStatusPendingFix, true},
		{"reopened->pending_analysis", DefectStatusReopened, DefectStatusPendingAnalysis, true},
		{"rejected->pending_analysis", DefectStatusRejected, DefectStatusPendingAnalysis, true},
		{"pending_fix->pending_analysis", DefectStatusPendingFix, DefectStatusPendingAnalysis, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, IsValidDefectTransition(tt.from, tt.to))
		})
	}
}

func TestIsValidDefectTransition_InvalidTransitions(t *testing.T) {
	tests := []struct {
		name string
		from string
		to   string
	}{
		{"same status", DefectStatusNew, DefectStatusNew},
		{"new->completed (skip too many)", DefectStatusNew, DefectStatusCompleted},
		{"new->fixing (skip)", DefectStatusNew, DefectStatusFixing},
		{"pending_assign->analyzing (must enter pending_analysis first)", DefectStatusPendingAssign, DefectStatusAnalyzing},
		{"pending_analysis->pending_fix (must analyze first)", DefectStatusPendingAnalysis, DefectStatusPendingFix},
		{"completed->analyzing (terminal)", DefectStatusCompleted, DefectStatusAnalyzing},
		{"unknown status", "unknown_status", DefectStatusAnalyzing},
		{"from unknown to new", "ghost", DefectStatusNew},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.False(t, IsValidDefectTransition(tt.from, tt.to))
		})
	}
}

func TestGetValidTransitions(t *testing.T) {
	tests := []struct {
		name           string
		current        string
		expectedCount  int
		mustContain    []string
		mustNotContain []string
	}{
		{
			name:          "new has 4 transitions",
			current:       DefectStatusNew,
			expectedCount: 4,
			mustContain:   []string{DefectStatusPendingAssign, DefectStatusPendingAnalysis, DefectStatusAnalyzing, DefectStatusRejected},
		},
		{
			name:          "pending_assign only enters pending_analysis",
			current:       DefectStatusPendingAssign,
			expectedCount: 1,
			mustContain:   []string{DefectStatusPendingAnalysis},
			mustNotContain: []string{
				DefectStatusAnalyzing,
				DefectStatusRejected,
			},
		},
		{
			name:          "pending_analysis has 3 transitions",
			current:       DefectStatusPendingAnalysis,
			expectedCount: 3,
			mustContain:   []string{DefectStatusAnalyzing, DefectStatusPendingAssign, DefectStatusRejected},
		},
		{
			name:          "fixing has 4 transitions",
			current:       DefectStatusFixing,
			expectedCount: 4,
			mustContain:   []string{DefectStatusPendingVerify, DefectStatusPendingFix, DefectStatusSuspended, DefectStatusRejected},
		},
		{
			name:          "completed only reopens",
			current:       DefectStatusCompleted,
			expectedCount: 1,
			mustContain:   []string{DefectStatusReopened},
		},
		{
			name:          "rejected reopens or goes to pending_analysis",
			current:       DefectStatusRejected,
			expectedCount: 2,
			mustContain:   []string{DefectStatusReopened, DefectStatusPendingAnalysis},
		},
		{
			name:          "unknown status returns empty",
			current:       "nonexistent",
			expectedCount: 0,
		},
		{
			name:          "reopened has 4 transitions",
			current:       DefectStatusReopened,
			expectedCount: 4,
			mustContain:   []string{DefectStatusPendingAnalysis, DefectStatusAnalyzing, DefectStatusPendingFix, DefectStatusRejected},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			transitions := GetValidTransitions(tt.current)
			assert.Len(t, transitions, tt.expectedCount)

			for _, s := range tt.mustContain {
				assert.Contains(t, transitions, s)
			}
			for _, s := range tt.mustNotContain {
				assert.NotContains(t, transitions, s)
			}
		})
	}
}

func TestIsTerminalStatus(t *testing.T) {
	assert.True(t, IsTerminalStatus(DefectStatusCompleted))
	assert.False(t, IsTerminalStatus(DefectStatusRejected))
	assert.False(t, IsTerminalStatus(DefectStatusNew))
	assert.False(t, IsTerminalStatus(DefectStatusFixing))
	assert.False(t, IsTerminalStatus(DefectStatusReopened))
	assert.False(t, IsTerminalStatus("unknown"))
}

func TestAllDefectStatuses_Completeness(t *testing.T) {
	statusSet := make(map[string]bool)
	for _, s := range AllDefectStatuses {
		statusSet[s] = true
	}

	expectedStatuses := []string{
		DefectStatusNew, DefectStatusPendingAssign,
		DefectStatusPendingAnalysis, DefectStatusAnalyzing,
		DefectStatusPendingFix, DefectStatusFixing,
		DefectStatusManualFixing,
		DefectStatusPendingVerify, DefectStatusFixed,
		DefectStatusCompleted, DefectStatusRejected,
		DefectStatusSuspended, DefectStatusReopened,
	}
	assert.Equal(t, len(expectedStatuses), len(AllDefectStatuses))

	for _, s := range expectedStatuses {
		assert.True(t, statusSet[s], "missing status in AllDefectStatuses: %s", s)
	}
}

func TestTransitionMatrix_AllStatesHaveEntries(t *testing.T) {
	for _, status := range AllDefectStatuses {
		_, exists := DefectTransitionMatrix[status]
		assert.True(t, exists, "status %s missing from transition matrix", status)
	}
}

func TestTransitionMatrix_NoSelfLoops(t *testing.T) {
	from, to := DefectStatusNew, DefectStatusNew
	assert.False(t, IsValidDefectTransition(from, to), "self-transition should be invalid")
}

func TestFullLifecycle_NewToComplete(t *testing.T) {
	lifecycle := []struct{ from, to string }{
		{DefectStatusNew, DefectStatusPendingAssign},
		{DefectStatusPendingAssign, DefectStatusPendingAnalysis},
		{DefectStatusPendingAnalysis, DefectStatusAnalyzing},
		{DefectStatusAnalyzing, DefectStatusPendingFix},
		{DefectStatusPendingFix, DefectStatusFixing},
		{DefectStatusFixing, DefectStatusPendingVerify},
		{DefectStatusPendingVerify, DefectStatusFixed},
		{DefectStatusFixed, DefectStatusCompleted},
	}

	for i, step := range lifecycle {
		t.Run(fmt.Sprintf("step%d_%s_%s", i+1, step.from, step.to), func(t *testing.T) {
			assert.True(t, IsValidDefectTransition(step.from, step.to),
				"step %d: %s -> %s should be valid", i+1, step.from, step.to)
		})
	}
}

func TestFullLifecycle_WithReopen(t *testing.T) {
	steps := []struct{ from, to string }{
		{DefectStatusCompleted, DefectStatusReopened},
		{DefectStatusReopened, DefectStatusAnalyzing},
		{DefectStatusAnalyzing, DefectStatusPendingFix},
		{DefectStatusPendingFix, DefectStatusFixing},
		{DefectStatusFixing, DefectStatusPendingVerify},
		{DefectStatusPendingVerify, DefectStatusFixed},
		{DefectStatusFixed, DefectStatusCompleted},
	}

	for i, step := range steps {
		assert.True(t, IsValidDefectTransition(step.from, step.to),
			"reopen cycle step %d: %s -> %s should be valid", i+1, step.from, step.to)
	}
}
