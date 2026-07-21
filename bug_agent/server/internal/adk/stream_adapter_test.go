package adk

import (
	"encoding/json"
	"fmt"
	"iter"
	"net/http/httptest"
	"strings"
	"testing"

	"google.golang.org/adk/model"
	"google.golang.org/adk/session"
	"google.golang.org/genai"
)

func TestConvertEvent_TextOnly_Thinking(t *testing.T) {
	event := &session.Event{
		LLMResponse: model.LLMResponse{
			Content: &genai.Content{
				Parts: []*genai.Part{
					{Text: "analyzing the code"},
				},
			},
			Partial: true,
		},
		Author: "analyst",
	}

	events := convertEvent(event)
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	evt := events[0]
	if evt.Type != "thinking" {
		t.Errorf("type = %q, want %q", evt.Type, "thinking")
	}
	if evt.Content != "analyzing the code" {
		t.Errorf("content = %q, want %q", evt.Content, "analyzing the code")
	}
	if evt.Agent != "analyst" {
		t.Errorf("agent = %q, want %q", evt.Agent, "analyst")
	}
	if evt.Phase != "analysis" {
		t.Errorf("phase = %q, want %q", evt.Phase, "analysis")
	}
	if !evt.Partial {
		t.Error("partial should be true")
	}
	if evt.Done {
		t.Error("done should be false")
	}
}

func TestConvertEvent_FunctionCall_ToolCall(t *testing.T) {
	event := &session.Event{
		LLMResponse: model.LLMResponse{
			Content: &genai.Content{
				Parts: []*genai.Part{
					{
						FunctionCall: &genai.FunctionCall{
							Name: "search_code",
							Args: map[string]interface{}{"query": "bug"},
						},
					},
				},
			},
		},
		Author: "analyst",
	}

	events := convertEvent(event)
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	evt := events[0]
	if evt.Type != "tool_call" {
		t.Errorf("type = %q, want %q", evt.Type, "tool_call")
	}
	if evt.ToolName != "search_code" {
		t.Errorf("toolName = %q, want %q", evt.ToolName, "search_code")
	}
	if evt.Phase != "retrieval" {
		t.Errorf("phase = %q, want %q", evt.Phase, "retrieval")
	}
	if evt.ToolInput == "" {
		t.Error("toolInput should not be empty")
	}
	if evt.StepIndex != 0 {
		t.Errorf("stepIndex = %d, want 0", evt.StepIndex)
	}
}

func TestConvertEvent_FunctionResponse_ToolResult(t *testing.T) {
	event := &session.Event{
		LLMResponse: model.LLMResponse{
			Content: &genai.Content{
				Parts: []*genai.Part{
					{
						FunctionResponse: &genai.FunctionResponse{
							Name: "validate_fix",
							Response: map[string]interface{}{
								"success": true,
							},
						},
					},
				},
			},
		},
		Author: "analyst",
	}

	events := convertEvent(event)
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	evt := events[0]
	if evt.Type != "tool_result" {
		t.Errorf("type = %q, want %q", evt.Type, "tool_result")
	}
	if evt.ToolName != "validate_fix" {
		t.Errorf("toolName = %q, want %q", evt.ToolName, "validate_fix")
	}
	if evt.Phase != "validation" {
		t.Errorf("phase = %q, want %q", evt.Phase, "validation")
	}
	if evt.ToolOutput == "" {
		t.Error("toolOutput should not be empty")
	}
}

func TestConvertEvent_FinalResponse(t *testing.T) {
	event := &session.Event{
		LLMResponse: model.LLMResponse{
			Content: &genai.Content{
				Parts: []*genai.Part{
					{Text: "final answer"},
				},
			},
			TurnComplete: true,
		},
		Author: "analyst",
	}

	events := convertEvent(event)
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	evt := events[0]
	if evt.Type != "final" {
		t.Errorf("type = %q, want %q", evt.Type, "final")
	}
	if !evt.Done {
		t.Error("done should be true")
	}
	if evt.Partial {
		t.Error("partial should be false for final events")
	}
	if evt.Content != "final answer" {
		t.Errorf("content = %q, want %q", evt.Content, "final answer")
	}
}

func TestConvertEvent_MixedParts_MultipleEvents(t *testing.T) {
	event := &session.Event{
		LLMResponse: model.LLMResponse{
			Content: &genai.Content{
				Parts: []*genai.Part{
					{Text: "let me search"},
					{
						FunctionCall: &genai.FunctionCall{
							Name: "read_file",
							Args: map[string]interface{}{"path": "/tmp/test.go"},
						},
					},
					{
						FunctionResponse: &genai.FunctionResponse{
							Name:     "read_file",
							Response: map[string]interface{}{"content": "package main"},
						},
					},
				},
			},
		},
		Author: "analyst",
	}

	events := convertEvent(event)
	if len(events) != 3 {
		t.Fatalf("expected 3 events, got %d", len(events))
	}

	if events[0].Type != "thinking" {
		t.Errorf("event[0] type = %q, want %q", events[0].Type, "thinking")
	}
	if events[0].Content != "let me search" {
		t.Errorf("event[0] content = %q, want %q", events[0].Content, "let me search")
	}
	if events[0].StepIndex != 0 {
		t.Errorf("event[0] stepIndex = %d, want 0", events[0].StepIndex)
	}

	if events[1].Type != "tool_call" {
		t.Errorf("event[1] type = %q, want %q", events[1].Type, "tool_call")
	}
	if events[1].ToolName != "read_file" {
		t.Errorf("event[1] toolName = %q, want %q", events[1].ToolName, "read_file")
	}
	if events[1].Phase != "retrieval" {
		t.Errorf("event[1] phase = %q, want %q", events[1].Phase, "retrieval")
	}
	if events[1].StepIndex != 1 {
		t.Errorf("event[1] stepIndex = %d, want 1", events[1].StepIndex)
	}

	if events[2].Type != "tool_result" {
		t.Errorf("event[2] type = %q, want %q", events[2].Type, "tool_result")
	}
	if events[2].ToolName != "read_file" {
		t.Errorf("event[2] toolName = %q, want %q", events[2].ToolName, "read_file")
	}
	if events[2].StepIndex != 2 {
		t.Errorf("event[2] stepIndex = %d, want 2", events[2].StepIndex)
	}
}

func TestConvertEvent_NilContent_Final(t *testing.T) {
	event := &session.Event{
		LLMResponse: model.LLMResponse{
			TurnComplete: true,
		},
		Author: "analyst",
	}

	events := convertEvent(event)
	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	if events[0].Type != "final" {
		t.Errorf("type = %q, want %q", events[0].Type, "final")
	}
	if !events[0].Done {
		t.Error("done should be true")
	}
}

func TestConvertEvent_NilContent_NotFinal(t *testing.T) {
	event := &session.Event{
		LLMResponse: model.LLMResponse{
			Partial: true,
		},
		Author: "analyst",
	}

	events := convertEvent(event)
	if len(events) != 0 {
		t.Fatalf("expected 0 events, got %d", len(events))
	}
}

func TestInferPhase_Retrieval(t *testing.T) {
	tools := []string{"search_code", "read_file", "trace_call", "list_directory", "search_symbol", "grep_content"}
	for _, tool := range tools {
		if phase := inferPhase(tool); phase != "retrieval" {
			t.Errorf("inferPhase(%q) = %q, want %q", tool, phase, "retrieval")
		}
	}
}

func TestInferPhase_Validation(t *testing.T) {
	tools := []string{"validate_fix", "run_test", "check_syntax", "verify_fix"}
	for _, tool := range tools {
		if phase := inferPhase(tool); phase != "validation" {
			t.Errorf("inferPhase(%q) = %q, want %q", tool, phase, "validation")
		}
	}
}

func TestInferPhase_Analysis(t *testing.T) {
	tools := []string{"apply_patch", "write_file", "unknown_tool", "execute_command"}
	for _, tool := range tools {
		if phase := inferPhase(tool); phase != "analysis" {
			t.Errorf("inferPhase(%q) = %q, want %q", tool, phase, "analysis")
		}
	}
}

func TestInferPhase_PartialMatch(t *testing.T) {
	if phase := inferPhase("mcp_search_code"); phase != "retrieval" {
		t.Errorf("inferPhase(%q) = %q, want %q", "mcp_search_code", phase, "retrieval")
	}
	if phase := inferPhase("mcp_validate_fix"); phase != "validation" {
		t.Errorf("inferPhase(%q) = %q, want %q", "mcp_validate_fix", phase, "validation")
	}
}

func parseSSEMessages(t *testing.T, body string) []sseMessage {
	t.Helper()
	var messages []sseMessage
	rawMsgs := strings.Split(body, "\n\n")
	for _, raw := range rawMsgs {
		raw = strings.TrimSpace(raw)
		if raw == "" {
			continue
		}
		msg := sseMessage{}
		for _, line := range strings.Split(raw, "\n") {
			if strings.HasPrefix(line, "event: ") {
				msg.event = strings.TrimPrefix(line, "event: ")
			} else if strings.HasPrefix(line, "id: ") {
				msg.id = strings.TrimPrefix(line, "id: ")
			} else if strings.HasPrefix(line, "data: ") {
				msg.data = strings.TrimPrefix(line, "data: ")
			}
		}
		messages = append(messages, msg)
	}
	return messages
}

type sseMessage struct {
	event string
	id    string
	data  string
}

func makeEventsIter(events []*session.Event, errs []error) iter.Seq2[*session.Event, error] {
	return func(yield func(*session.Event, error) bool) {
		for i, evt := range events {
			if i < len(errs) && errs[i] != nil {
				if !yield(nil, errs[i]) {
					return
				}
				return
			}
			if !yield(evt, nil) {
				return
			}
		}
	}
}

func TestStreamToSSE_EventAndIdAndDataLines(t *testing.T) {
	events := []*session.Event{
		{
			LLMResponse: model.LLMResponse{
				Content: &genai.Content{
					Parts: []*genai.Part{
						{Text: "thinking..."},
					},
				},
				Partial: true,
			},
			Author: "analyst",
		},
		{
			LLMResponse: model.LLMResponse{
				Content: &genai.Content{
					Parts: []*genai.Part{
						{
							FunctionCall: &genai.FunctionCall{
								Name: "search_code",
								Args: map[string]interface{}{"query": "bug"},
							},
						},
					},
				},
			},
			Author: "analyst",
		},
		{
			LLMResponse: model.LLMResponse{
				Content: &genai.Content{
					Parts: []*genai.Part{
						{Text: "done"},
					},
				},
				TurnComplete: true,
			},
			Author: "analyst",
		},
	}

	rec := httptest.NewRecorder()
	StreamToSSE(makeEventsIter(events, nil), rec)

	msgs := parseSSEMessages(t, rec.Body.String())
	if len(msgs) != 3 {
		t.Fatalf("expected 3 SSE messages, got %d", len(msgs))
	}

	if msgs[0].event != "thinking" {
		t.Errorf("msg[0] event = %q, want %q", msgs[0].event, "thinking")
	}
	if msgs[0].id != "1" {
		t.Errorf("msg[0] id = %q, want %q", msgs[0].id, "1")
	}
	var data0 StreamEvent
	if err := json.Unmarshal([]byte(msgs[0].data), &data0); err != nil {
		t.Fatalf("msg[0] data unmarshal: %v", err)
	}
	if data0.Type != "thinking" {
		t.Errorf("msg[0] data.type = %q, want %q", data0.Type, "thinking")
	}

	if msgs[1].event != "tool_call" {
		t.Errorf("msg[1] event = %q, want %q", msgs[1].event, "tool_call")
	}
	if msgs[1].id != "2" {
		t.Errorf("msg[1] id = %q, want %q", msgs[1].id, "2")
	}

	if msgs[2].event != "final" {
		t.Errorf("msg[2] event = %q, want %q", msgs[2].event, "final")
	}
	if msgs[2].id != "3" {
		t.Errorf("msg[2] id = %q, want %q", msgs[2].id, "3")
	}
	var data2 StreamEvent
	if err := json.Unmarshal([]byte(msgs[2].data), &data2); err != nil {
		t.Fatalf("msg[2] data unmarshal: %v", err)
	}
	if !data2.Done {
		t.Error("msg[2] data.done should be true")
	}
}

func TestStreamToSSE_SequentialIDs(t *testing.T) {
	events := []*session.Event{
		{
			LLMResponse: model.LLMResponse{
				Content: &genai.Content{
					Parts: []*genai.Part{
						{Text: "step1"},
						{
							FunctionCall: &genai.FunctionCall{
								Name: "read_file",
								Args: map[string]interface{}{"path": "/a"},
							},
						},
					},
				},
				Partial: true,
			},
			Author: "analyst",
		},
		{
			LLMResponse: model.LLMResponse{
				Content: &genai.Content{
					Parts: []*genai.Part{
						{Text: "final"},
					},
				},
				TurnComplete: true,
			},
			Author: "analyst",
		},
	}

	rec := httptest.NewRecorder()
	StreamToSSE(makeEventsIter(events, nil), rec)

	msgs := parseSSEMessages(t, rec.Body.String())
	if len(msgs) != 3 {
		t.Fatalf("expected 3 SSE messages, got %d", len(msgs))
	}
	for i, msg := range msgs {
		expected := fmt.Sprintf("%d", i+1)
		if msg.id != expected {
			t.Errorf("msg[%d] id = %q, want %q", i, msg.id, expected)
		}
	}
}

func TestStreamToSSE_ErrorEvent(t *testing.T) {
	events := []*session.Event{nil}
	errs := []error{fmt.Errorf("stream broke")}

	rec := httptest.NewRecorder()
	StreamToSSE(makeEventsIter(events, errs), rec)

	msgs := parseSSEMessages(t, rec.Body.String())
	if len(msgs) != 1 {
		t.Fatalf("expected 1 SSE message, got %d", len(msgs))
	}
	if msgs[0].event != "error" {
		t.Errorf("event = %q, want %q", msgs[0].event, "error")
	}
	if msgs[0].id != "1" {
		t.Errorf("id = %q, want %q", msgs[0].id, "1")
	}
	var data StreamEvent
	if err := json.Unmarshal([]byte(msgs[0].data), &data); err != nil {
		t.Fatalf("data unmarshal: %v", err)
	}
	if data.Type != "error" {
		t.Errorf("data.type = %q, want %q", data.Type, "error")
	}
	if data.Error == "" {
		t.Error("data.error should not be empty")
	}
}

func TestStreamToSSE_FinalTerminatesStream(t *testing.T) {
	events := []*session.Event{
		{
			LLMResponse: model.LLMResponse{
				Content: &genai.Content{
					Parts: []*genai.Part{
						{Text: "final answer"},
					},
				},
				TurnComplete: true,
			},
			Author: "analyst",
		},
		{
			LLMResponse: model.LLMResponse{
				Content: &genai.Content{
					Parts: []*genai.Part{
						{Text: "should not appear"},
					},
				},
				Partial: true,
			},
			Author: "analyst",
		},
	}

	rec := httptest.NewRecorder()
	StreamToSSE(makeEventsIter(events, nil), rec)

	body := rec.Body.String()
	if strings.Contains(body, "should not appear") {
		t.Error("stream should have terminated at final event, but got more data")
	}
	msgs := parseSSEMessages(t, body)
	if len(msgs) != 1 {
		t.Fatalf("expected 1 SSE message, got %d", len(msgs))
	}
	if msgs[0].event != "final" {
		t.Errorf("event = %q, want %q", msgs[0].event, "final")
	}
}

func TestStreamToSSE_SetsHeaders(t *testing.T) {
	events := []*session.Event{
		{
			LLMResponse: model.LLMResponse{
				Content: &genai.Content{
					Parts: []*genai.Part{
						{Text: "hi"},
					},
				},
				TurnComplete: true,
			},
			Author: "analyst",
		},
	}

	rec := httptest.NewRecorder()
	StreamToSSE(makeEventsIter(events, nil), rec)

	if ct := rec.Header().Get("Content-Type"); ct != "text/event-stream" {
		t.Errorf("Content-Type = %q, want %q", ct, "text/event-stream")
	}
	if cc := rec.Header().Get("Cache-Control"); cc != "no-cache" {
		t.Errorf("Cache-Control = %q, want %q", cc, "no-cache")
	}
	if conn := rec.Header().Get("Connection"); conn != "keep-alive" {
		t.Errorf("Connection = %q, want %q", conn, "keep-alive")
	}
	if xab := rec.Header().Get("X-Accel-Buffering"); xab != "no" {
		t.Errorf("X-Accel-Buffering = %q, want %q", xab, "no")
	}
}
