package adk

import (
	"encoding/json"
	"fmt"
	"io"
	"iter"
	"net/http"
	"strings"

	"bug-agent/pkg/logger"

	"google.golang.org/adk/session"
)

type StreamEvent struct {
	Type       string `json:"type"`
	Agent      string `json:"agent,omitempty"`
	Content    string `json:"content,omitempty"`
	Partial    bool   `json:"partial,omitempty"`
	Done       bool   `json:"done,omitempty"`
	Error      string `json:"error,omitempty"`
	ToolName   string `json:"toolName,omitempty"`
	ToolInput  string `json:"toolInput,omitempty"`
	ToolOutput string `json:"toolOutput,omitempty"`
	StepIndex  int    `json:"stepIndex,omitempty"`
	Phase      string `json:"phase,omitempty"`
}

func StreamToSSE(events iter.Seq2[*session.Event, error], w http.ResponseWriter) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	id := 0
	writeSSE := func(evtType string, data []byte) {
		id++
		fmt.Fprintf(w, "event: %s\nid: %d\ndata: %s\n\n", evtType, id, data)
		flusher.Flush()
	}

	done := false
	for event, err := range events {
		if err != nil {
			logger.Errorf("[StreamAdapter] stream error: %v", err)
			errMsg := err.Error()
			if len(errMsg) > 500 {
				errMsg = errMsg[:500]
			}
			streamEvt := StreamEvent{Type: "error", Error: errMsg}
			data, marshalErr := json.Marshal(streamEvt)
			if marshalErr != nil {
				writeSSE("error", []byte(`{"type":"error","error":"marshal failed"}`))
			} else {
				writeSSE("error", data)
			}
			break
		}

		if event == nil {
			continue
		}

		streamEvts := convertEvent(event)
		for _, streamEvt := range streamEvts {
			data, marshalErr := json.Marshal(streamEvt)
			if marshalErr != nil {
				continue
			}
			writeSSE(streamEvt.Type, data)

			if streamEvt.Done {
				done = true
				break
			}
		}
		if done {
			break
		}
	}
}

func StreamToWriter(events iter.Seq2[*session.Event, error], w io.Writer) error {
	for event, err := range events {
		if err != nil {
			return fmt.Errorf("stream error: %w", err)
		}
		if event == nil {
			continue
		}

		streamEvts := convertEvent(event)
		for _, streamEvt := range streamEvts {
			data, marshalErr := json.Marshal(streamEvt)
			if marshalErr != nil {
				return fmt.Errorf("marshal stream event: %w", marshalErr)
			}
			if _, err := w.Write(data); err != nil {
				return fmt.Errorf("write error: %w", err)
			}
			if f, ok := w.(http.Flusher); ok {
				f.Flush()
			}

			if streamEvt.Done {
				break
			}
		}
	}
	return nil
}

func CollectEvents(events iter.Seq2[*session.Event, error]) ([]*session.Event, error) {
	var collected []*session.Event
	for event, err := range events {
		if err != nil {
			return collected, err
		}
		if event != nil {
			collected = append(collected, event)
		}
	}
	return collected, nil
}

func convertEvent(event *session.Event) []StreamEvent {
	var result []StreamEvent

	agent := event.Author
	isFinal := event.IsFinalResponse()

	if event.Content == nil || len(event.Content.Parts) == 0 {
		if isFinal {
			return []StreamEvent{{
				Type:    "final",
				Agent:   agent,
				Done:    true,
				Partial: false,
			}}
		}
		return nil
	}

	stepIdx := 0
	for _, part := range event.Content.Parts {
		if part.FunctionCall != nil {
			inputJSON, err := json.Marshal(part.FunctionCall.Args)
			if err != nil {
				inputJSON = []byte("{}")
			}
			result = append(result, StreamEvent{
				Type:      "tool_call",
				Agent:     agent,
				ToolName:  part.FunctionCall.Name,
				ToolInput: string(inputJSON),
				StepIndex: stepIdx,
				Phase:     inferPhase(part.FunctionCall.Name),
				Partial:   !isFinal,
			})
			stepIdx++
		} else if part.FunctionResponse != nil {
			outputJSON, err := json.Marshal(part.FunctionResponse.Response)
			if err != nil {
				outputJSON = []byte("{}")
			}
			result = append(result, StreamEvent{
				Type:       "tool_result",
				Agent:      agent,
				ToolName:   part.FunctionResponse.Name,
				ToolOutput: string(outputJSON),
				StepIndex:  stepIdx,
				Phase:      inferPhase(part.FunctionResponse.Name),
				Partial:    !isFinal,
			})
			stepIdx++
		} else if part.Text != "" {
			evt := StreamEvent{
				Type:     "thinking",
				Agent:    agent,
				Content:  part.Text,
				StepIndex: stepIdx,
				Phase:    "analysis",
				Partial:  !isFinal,
			}
			if isFinal {
				evt.Type = "final"
				evt.Done = true
				evt.Partial = false
			}
			result = append(result, evt)
			stepIdx++
		}
	}

	if len(result) == 0 && isFinal {
		return []StreamEvent{{
			Type:    "final",
			Agent:   agent,
			Done:    true,
			Partial: false,
		}}
	}

	return result
}

func inferPhase(toolName string) string {
	retrievalTools := []string{"search_code", "read_file", "trace_call", "list_directory", "search_symbol", "grep_content"}
	for _, t := range retrievalTools {
		if strings.Contains(toolName, t) {
			return "retrieval"
		}
	}
	validationTools := []string{"validate_fix", "run_test", "check_syntax", "verify_fix"}
	for _, t := range validationTools {
		if strings.Contains(toolName, t) {
			return "validation"
		}
	}
	return "analysis"
}
