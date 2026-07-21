package sse

import (
	"fmt"

	"bug-agent/pkg/logger"
)

type NotifyService struct {
	broker *Broker
}

var Notifier *NotifyService

func InitNotifyService(broker *Broker) {
	Notifier = NewNotifyService(broker)
}

func NewNotifyService(broker *Broker) *NotifyService {
	return &NotifyService{broker: broker}
}

func (n *NotifyService) NotifyAnalysisStarted(defectID uint, agentTypes []string) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.Publish(defectRoom(defectID), SSEEvent{
		Event: "analysis:started",
		Data: map[string]interface{}{
			"defectId":   defectID,
			"agentTypes": agentTypes,
			"status":     "analyzing",
		},
	})
	logger.Infof("[SSE Notify] Analysis started: defect #%d", defectID)
}

func (n *NotifyService) NotifyAnalysisCompleted(defectID uint, reportCode string) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.Publish(defectRoom(defectID), SSEEvent{
		Event: "analysis:completed",
		Data: map[string]interface{}{
			"defectId":   defectID,
			"reportCode": reportCode,
			"status":     "completed",
		},
	})
}

func (n *NotifyService) NotifyAnalysisFailed(defectID uint, errMsg string) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.Publish(defectRoom(defectID), SSEEvent{
		Event: "analysis:failed",
		Data: map[string]interface{}{
			"defectId": defectID,
			"error":    errMsg,
			"status":   "failed",
		},
	})
}

func (n *NotifyService) NotifyAnalysisCancelled(defectID uint) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.Publish(defectRoom(defectID), SSEEvent{
		Event: "analysis:cancelled",
		Data: map[string]interface{}{
			"defectId": defectID,
			"status":   "cancelled",
		},
	})
}

func (n *NotifyService) NotifyCollaborationStarted(taskID uint, taskCode string, defectID uint) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.Publish(defectRoom(defectID), SSEEvent{
		Event: "collaboration:started",
		Data: map[string]interface{}{
			"taskId":   taskID,
			"taskCode": taskCode,
		},
	})
}

func (n *NotifyService) NotifyCollaborationProgress(taskID uint, agentType string, status string) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.PublishGlobal(SSEEvent{
		Event: "collaboration:progress",
		Data: map[string]interface{}{
			"taskId":    taskID,
			"agentType": agentType,
			"status":    status,
		},
	})
}

func (n *NotifyService) NotifyCollaborationCompleted(taskID uint, taskCode string, riskLevel string) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.PublishGlobal(SSEEvent{
		Event: "collaboration:completed",
		Data: map[string]interface{}{
			"taskId":    taskID,
			"taskCode":  taskCode,
			"riskLevel": riskLevel,
			"status":    "completed",
		},
	})
}

func (n *NotifyService) NotifyFixTaskCreated(taskID uint, defectID uint) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.Publish(defectRoom(defectID), SSEEvent{
		Event: "fix_task:created",
		Data: map[string]interface{}{
			"taskId":   taskID,
			"defectId": defectID,
			"status":   "pending",
		},
	})
}

func (n *NotifyService) NotifyFixTaskProgress(taskID uint, step string, progress int) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.PublishGlobal(SSEEvent{
		Event: "fix_task:progress",
		Data: map[string]interface{}{
			"taskId":   taskID,
			"step":     step,
			"progress": progress,
		},
	})
}

func (n *NotifyService) NotifyFixTaskPlanProgress(defectID uint, groupID *uint, taskID uint, taskCode string, agentType string, status string, plan interface{}) {
	if n == nil || n.broker == nil {
		return
	}
	data := map[string]interface{}{
		"defectId":  defectID,
		"taskId":    taskID,
		"taskCode":  taskCode,
		"agentType": agentType,
		"status":    status,
		"plan":      plan,
	}
	if groupID != nil {
		data["groupId"] = *groupID
	}
	n.broker.Publish(defectRoom(defectID), SSEEvent{
		Event: "fix_task:progress",
		Data:  data,
	})
}

func (n *NotifyService) NotifyFixTaskCompleted(taskID uint, prURL string) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.PublishGlobal(SSEEvent{
		Event: "fix_task:completed",
		Data: map[string]interface{}{
			"taskId": taskID,
			"prUrl":  prURL,
			"status": "completed",
		},
	})
}

func (n *NotifyService) NotifyFixTaskFinished(defectID uint, groupID *uint, taskID uint, taskCode string, agentType string, status string, prURL string) {
	if n == nil || n.broker == nil {
		return
	}
	data := map[string]interface{}{
		"defectId":  defectID,
		"taskId":    taskID,
		"taskCode":  taskCode,
		"agentType": agentType,
		"status":    status,
		"prUrl":     prURL,
	}
	if groupID != nil {
		data["groupId"] = *groupID
	}
	eventName := "fix_task:completed"
	if status == "failed" || status == "cancelled" || status == "partial_failed" {
		eventName = "fix_task:failed"
	}
	n.broker.Publish(defectRoom(defectID), SSEEvent{
		Event: eventName,
		Data:  data,
	})
}

func (n *NotifyService) NotifyDefectStatusChanged(defectID uint, oldStatus string, newStatus string) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.Publish(defectRoom(defectID), SSEEvent{
		Event: "defect:status_changed",
		Data: map[string]interface{}{
			"defectId":  defectID,
			"oldStatus": oldStatus,
			"newStatus": newStatus,
		},
	})
}

func (n *NotifyService) NotifyCommentAdded(defectID uint, content string, isAgent bool) {
	if n == nil || n.broker == nil {
		return
	}
	n.broker.Publish(defectRoom(defectID), SSEEvent{
		Event: "comment:added",
		Data: map[string]interface{}{
			"defectId":   defectID,
			"content":    truncateContent(content),
			"isAgentMsg": isAgent,
		},
	})
}

func defectRoom(defectID uint) string {
	return fmt.Sprintf("defect:%d", defectID)
}

func truncateContent(s string) string {
	runes := []rune(s)
	if len(runes) > 200 {
		return string(runes[:200]) + "..."
	}
	return s
}
