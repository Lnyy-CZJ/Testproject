package sse

import "testing"

func TestSSEBrokerPublishPreservesStructuredData(t *testing.T) {
	broker := NewBroker()
	ch := broker.Subscribe([]string{"defect:1"})
	defer broker.Unsubscribe(ch)

	payload := map[string]interface{}{"defectId": 1, "toStatus": "pending_fix"}
	broker.Publish("defect:1", SSEEvent{Event: "defect:status_changed", Data: payload})

	got := <-ch
	data, ok := got.Data.(map[string]interface{})
	if !ok {
		t.Fatalf("expected structured map payload, got %T: %#v", got.Data, got.Data)
	}
	if data["toStatus"] != "pending_fix" {
		t.Fatalf("unexpected payload: %#v", data)
	}
}
