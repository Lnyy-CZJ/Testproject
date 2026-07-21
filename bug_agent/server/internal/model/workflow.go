package model

import "time"

const (
	DefectStatusReopened     = "reopened"
	DefectStatusManualFixing = "manual_fixing"
)

var AllDefectStatuses = []string{
	DefectStatusNew, DefectStatusPendingAssign,
	DefectStatusPendingAnalysis, DefectStatusAnalyzing,
	DefectStatusPendingFix, DefectStatusFixing, DefectStatusManualFixing,
	DefectStatusPendingVerify, DefectStatusFixed,
	DefectStatusCompleted, DefectStatusRejected,
	DefectStatusSuspended, DefectStatusReopened,
}

var DefectTransitionMatrix = map[string]map[string]bool{
	DefectStatusNew: {
		DefectStatusPendingAssign:  true,
		DefectStatusPendingAnalysis: true,
		DefectStatusAnalyzing:       true,
		DefectStatusRejected:        true,
	},
	DefectStatusPendingAssign: {
		DefectStatusPendingAnalysis: true,
	},
	DefectStatusPendingAnalysis: {
		DefectStatusAnalyzing:    true,
		DefectStatusPendingAssign: true,
		DefectStatusRejected:     true,
	},
	DefectStatusAnalyzing: {
		DefectStatusPendingFix:    true,
		DefectStatusPendingAssign: true,
		DefectStatusRejected:      true,
	},
	DefectStatusPendingFix: {
		DefectStatusPendingAnalysis: true,
		DefectStatusFixing:          true,
		DefectStatusManualFixing:    true,
		DefectStatusRejected:        true,
		DefectStatusSuspended:       true,
	},
	DefectStatusManualFixing: {
		DefectStatusPendingVerify: true,
		DefectStatusPendingFix:    true,
		DefectStatusRejected:      true,
	},
	DefectStatusFixing: {
		DefectStatusPendingVerify: true,
		DefectStatusPendingFix:    true,
		DefectStatusSuspended:     true,
		DefectStatusRejected:      true,
	},
	DefectStatusPendingVerify: {
		DefectStatusFixed:      true,
		DefectStatusPendingFix: true,
		DefectStatusRejected:   true,
	},
	DefectStatusFixed: {
		DefectStatusCompleted: true,
		DefectStatusReopened:  true,
	},
	DefectStatusCompleted: {
		DefectStatusReopened: true,
	},
	DefectStatusRejected: {
		DefectStatusReopened:        true,
		DefectStatusPendingAnalysis: true,
	},
	DefectStatusSuspended: {
		DefectStatusReopened:  true,
		DefectStatusPendingFix: true,
	},
	DefectStatusReopened: {
		DefectStatusPendingAnalysis: true,
		DefectStatusAnalyzing:       true,
		DefectStatusPendingFix:      true,
		DefectStatusRejected:        true,
	},
}

var TerminalDefectStatuses = map[string]bool{
	DefectStatusCompleted: true,
}

func IsValidDefectTransition(from, to string) bool {
	if from == to {
		return false
	}
	transitions, ok := DefectTransitionMatrix[from]
	if !ok {
		return false
	}
	return transitions[to]
}

func GetValidTransitions(currentStatus string) []string {
	var result []string
	for status := range DefectTransitionMatrix[currentStatus] {
		result = append(result, status)
	}
	return result
}

func IsTerminalStatus(status string) bool {
	return TerminalDefectStatuses[status]
}

type StatusChange struct {
	ID        uint   `gorm:"primaryKey" json:"id"`
	DefectID  uint   `json:"defectId" gorm:"index"`
	FromStatus string `json:"fromStatus"`
	ToStatus  string `json:"toStatus"`
	ChangedBy uint   `json:"changedBy"`
	Comment   string    `json:"comment" gorm:"type:text"`
	CreatedAt time.Time `json:"createdAt"`
}

func (StatusChange) TableName() string { return "status_changes" }
