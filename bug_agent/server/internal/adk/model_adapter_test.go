package adk

import (
	"context"
	"testing"

	"bug-agent/internal/ai"
	bugmodel "bug-agent/internal/model"

	"google.golang.org/genai"
	adkmodel "google.golang.org/adk/model"
)

type mockAIClient struct {
	chatResp *ai.ChatResponse
	chatErr  error
	streamCh chan *ai.StreamChunk
}

func (m *mockAIClient) Chat(ctx context.Context, req *ai.ChatRequest) (*ai.ChatResponse, error) {
	return m.chatResp, m.chatErr
}

func (m *mockAIClient) ChatStream(ctx context.Context, req *ai.ChatRequest) (<-chan *ai.StreamChunk, error) {
	if m.streamCh == nil {
		ch := make(chan *ai.StreamChunk, 1)
		close(ch)
		return ch, nil
	}
	return m.streamCh, m.chatErr
}

func TestAIClientModel_Name(t *testing.T) {
	client := &mockAIClient{}
	model := NewAIClientModel(client, "test-model")
	if model.Name() != "test-model" {
		t.Errorf("Name() = %q, want %q", model.Name(), "test-model")
	}
}

func TestAIClientModel_GenerateContent(t *testing.T) {
	client := &mockAIClient{
		chatResp: &ai.ChatResponse{
			Choices: []ai.Choice{
				{
					Message:      ai.Message{Role: "assistant", Content: "hello world"},
					FinishReason: "stop",
				},
			},
			Usage: ai.Usage{PromptTokens: 10, CompletionTokens: 5, TotalTokens: 15},
		},
	}

	model := NewAIClientModel(client, "test-model")
	req := &adkmodel.LLMRequest{
		Contents: []*genai.Content{
			{Role: genai.RoleUser, Parts: []*genai.Part{{Text: "say hello"}}},
		},
	}

	var resp *adkmodel.LLMResponse
	for r, err := range model.GenerateContent(context.Background(), req, false) {
		if err != nil {
			t.Fatalf("GenerateContent error: %v", err)
		}
		resp = r
	}

	if resp == nil {
		t.Fatal("resp is nil")
	}
	if resp.Content == nil || len(resp.Content.Parts) == 0 {
		t.Fatal("no content parts")
	}
	if resp.Content.Parts[0].Text != "hello world" {
		t.Errorf("text = %q, want %q", resp.Content.Parts[0].Text, "hello world")
	}
	if !resp.TurnComplete {
		t.Error("TurnComplete should be true")
	}
	if resp.UsageMetadata == nil {
		t.Fatal("UsageMetadata is nil")
	}
	if resp.UsageMetadata.PromptTokenCount != 10 {
		t.Errorf("PromptTokenCount = %d, want 10", resp.UsageMetadata.PromptTokenCount)
	}
}

func TestAIClientModel_StreamGenerate(t *testing.T) {
	stopReason := "stop"
	ch := make(chan *ai.StreamChunk, 3)
	ch <- &ai.StreamChunk{
		Choices: []ai.StreamChoice{
			{Delta: ai.Message{Role: "assistant", Content: "hel"}, FinishReason: nil},
		},
	}
	ch <- &ai.StreamChunk{
		Choices: []ai.StreamChoice{
			{Delta: ai.Message{Role: "assistant", Content: "lo"}, FinishReason: nil},
		},
	}
	ch <- &ai.StreamChunk{
		Choices: []ai.StreamChoice{
			{Delta: ai.Message{Role: "assistant", Content: ""}, FinishReason: &stopReason},
		},
	}
	close(ch)

	client := &mockAIClient{streamCh: ch}
	model := NewAIClientModel(client, "test-model")
	req := &adkmodel.LLMRequest{
		Contents: []*genai.Content{
			{Role: genai.RoleUser, Parts: []*genai.Part{{Text: "say hello"}}},
		},
	}

	var texts []string
	var turnComplete bool
	for r, err := range model.GenerateContent(context.Background(), req, true) {
		if err != nil {
			t.Fatalf("StreamGenerate error: %v", err)
		}
		if r.Content != nil && len(r.Content.Parts) > 0 && r.Content.Parts[0].Text != "" {
			texts = append(texts, r.Content.Parts[0].Text)
		}
		turnComplete = r.TurnComplete
	}

	combined := ""
	for _, t := range texts {
		combined += t
	}
	if combined != "hello" {
		t.Errorf("streamed text = %q, want %q", combined, "hello")
	}
	if !turnComplete {
		t.Error("TurnComplete should be true at end of stream")
	}
}

func TestAIClientModel_ConvertRequest(t *testing.T) {
	temp := float32(0.7)
	topP := float32(0.9)
	client := &mockAIClient{}
	model := NewAIClientModel(client, "test-model")

	req := &adkmodel.LLMRequest{
		Contents: []*genai.Content{
			{Role: genai.RoleUser, Parts: []*genai.Part{{Text: "hello"}}},
			{Role: genai.RoleModel, Parts: []*genai.Part{{Text: "hi there"}}},
		},
		Config: &genai.GenerateContentConfig{
			Temperature:    &temp,
			MaxOutputTokens: 1024,
			TopP:           &topP,
			StopSequences:  []string{"END"},
		},
	}

	chatReq := model.convertRequest(req, false)
	if chatReq.Model != "test-model" {
		t.Errorf("Model = %q, want %q", chatReq.Model, "test-model")
	}
	if len(chatReq.Messages) != 2 {
		t.Fatalf("Messages count = %d, want 2", len(chatReq.Messages))
	}
	if chatReq.Messages[0].Role != "user" || chatReq.Messages[0].Content != "hello" {
		t.Errorf("first message = %+v", chatReq.Messages[0])
	}
	if chatReq.Temperature < 0.69 || chatReq.Temperature > 0.71 {
		t.Errorf("Temperature = %f, want ~0.7", chatReq.Temperature)
	}
	if chatReq.MaxTokens != 1024 {
		t.Errorf("MaxTokens = %d, want 1024", chatReq.MaxTokens)
	}
	if chatReq.TopP < 0.89 || chatReq.TopP > 0.91 {
		t.Errorf("TopP = %f, want ~0.9", chatReq.TopP)
	}
	if len(chatReq.Stop) != 1 || chatReq.Stop[0] != "END" {
		t.Errorf("Stop = %v, want [END]", chatReq.Stop)
	}
}

func TestAIClientModel_NonFCMode_ConvertRequest(t *testing.T) {
	client := &mockAIClient{}
	model := NewAIClientModelWithFC(client, "test-model", false)

	req := &adkmodel.LLMRequest{
		Contents: []*genai.Content{
			{Role: genai.RoleUser, Parts: []*genai.Part{{Text: "find the bug"}}},
		},
		Config: &genai.GenerateContentConfig{
			SystemInstruction: &genai.Content{
				Parts: []*genai.Part{{Text: "You are a code explorer."}},
			},
			Tools: []*genai.Tool{
				{
					FunctionDeclarations: []*genai.FunctionDeclaration{
						{
							Name:        "search_code",
							Description: "Search for code",
							Parameters: &genai.Schema{
								Type: "object",
								Properties: map[string]*genai.Schema{
									"query": {Type: "string", Description: "search query"},
								},
								Required: []string{"query"},
							},
						},
					},
				},
			},
		},
	}

	chatReq := model.convertRequest(req, false)

	if len(chatReq.Tools) > 0 {
		t.Errorf("NonFC mode should not pass tools in API request, got %d tools", len(chatReq.Tools))
	}

	if len(chatReq.Messages) < 1 {
		t.Fatal("expected at least 1 message")
	}

	sysMsg := chatReq.Messages[0]
	if sysMsg.Role != "system" {
		t.Fatalf("first message role = %q, want system", sysMsg.Role)
	}
	if !contains(sysMsg.Content, "search_code") {
		t.Errorf("system prompt should contain tool definition, got: %s", truncate(sysMsg.Content, 200))
	}
	if !contains(sysMsg.Content, "tool_call") {
		t.Errorf("system prompt should contain tool_call instruction, got: %s", truncate(sysMsg.Content, 200))
	}
}

func TestAIClientModel_NonFCMode_ConvertResponse(t *testing.T) {
	client := &mockAIClient{}
	model := NewAIClientModelWithFC(client, "test-model", false)

	resp := &ai.ChatResponse{
		Choices: []ai.Choice{
			{
				Message: ai.Message{
					Role:    "assistant",
					Content: "Let me search for that.\n```json\n{\"tool_call\":{\"name\":\"search_code\",\"arguments\":{\"query\":\"login bug\"}}}\n```",
				},
				FinishReason: "stop",
			},
		},
		Usage: ai.Usage{PromptTokens: 10, CompletionTokens: 5, TotalTokens: 15},
	}

	adkResp := model.convertResponse(resp)

	if adkResp.TurnComplete {
		t.Error("NonFC mode with tool_call should have TurnComplete=false")
	}

	hasFunctionCall := false
	for _, part := range adkResp.Content.Parts {
		if part.FunctionCall != nil {
			hasFunctionCall = true
			if part.FunctionCall.Name != "search_code" {
				t.Errorf("FunctionCall.Name = %q, want search_code", part.FunctionCall.Name)
			}
			if q, ok := part.FunctionCall.Args["query"].(string); !ok || q != "login bug" {
				t.Errorf("FunctionCall.Args[query] = %v, want 'login bug'", part.FunctionCall.Args["query"])
			}
		}
	}
	if !hasFunctionCall {
		t.Error("expected FunctionCall part in response")
	}
}

func TestAIClientModel_NonFCMode_FinalResponse(t *testing.T) {
	client := &mockAIClient{}
	model := NewAIClientModelWithFC(client, "test-model", false)

	resp := &ai.ChatResponse{
		Choices: []ai.Choice{
			{
				Message: ai.Message{
					Role:    "assistant",
					Content: `{"thinking":"found it","findings":[{"file_path":"main.go","evidence":"nil pointer","severity":"critical"}]}`,
				},
				FinishReason: "stop",
			},
		},
		Usage: ai.Usage{PromptTokens: 10, CompletionTokens: 5, TotalTokens: 15},
	}

	adkResp := model.convertResponse(resp)

	if !adkResp.TurnComplete {
		t.Error("NonFC mode without tool_call should have TurnComplete=true")
	}

	hasFunctionCall := false
	for _, part := range adkResp.Content.Parts {
		if part.FunctionCall != nil {
			hasFunctionCall = true
		}
	}
	if hasFunctionCall {
		t.Error("final response should not have FunctionCall")
	}
}

func TestAIClientModel_NonFCMode_ToolResultAsUserMessage(t *testing.T) {
	client := &mockAIClient{}
	model := NewAIClientModelWithFC(client, "test-model", false)

	req := &adkmodel.LLMRequest{
		Contents: []*genai.Content{
			{Role: genai.RoleUser, Parts: []*genai.Part{{Text: "find the bug"}}},
			{Role: genai.RoleModel, Parts: []*genai.Part{
				{FunctionCall: &genai.FunctionCall{Name: "search_code", Args: map[string]interface{}{"query": "login"}}},
			}},
			{Role: genai.RoleUser, Parts: []*genai.Part{
				{FunctionResponse: &genai.FunctionResponse{Name: "search_code", Response: map[string]interface{}{"results": []string{"auth.go"}}}},
			}},
		},
	}

	chatReq := model.convertRequest(req, false)

	toolResultFound := false
	for _, msg := range chatReq.Messages {
		if msg.Role == "tool" {
			t.Errorf("NonFC mode should not have 'tool' role messages, got: %s", msg.Content)
		}
		if contains(msg.Content, "search_code result:") {
			toolResultFound = true
		}
	}
	if !toolResultFound {
		t.Error("expected tool result formatted as text in messages")
	}
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > 0 && containsHelper(s, substr))
}

func containsHelper(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}

func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen] + "..."
}

func TestParseToolCallFromText_CodeBlock(t *testing.T) {
	text := "Let me search.\n```json\n{\"tool_call\":{\"name\":\"search_code\",\"arguments\":{\"query\":\"login\"}}}\n```"
	name, args, _, found := parseToolCallFromText(text)
	if !found {
		t.Fatal("expected to find tool_call")
	}
	if name != "search_code" {
		t.Errorf("name = %q, want search_code", name)
	}
	if q, ok := args["query"].(string); !ok || q != "login" {
		t.Errorf("args[query] = %v, want login", args["query"])
	}
}

func TestParseToolCallFromText_BareJSON(t *testing.T) {
	text := `{"tool_call":{"name":"read_file","arguments":{"file_path":"main.go"}}}`
	name, args, _, found := parseToolCallFromText(text)
	if !found {
		t.Fatal("expected to find tool_call in bare JSON")
	}
	if name != "read_file" {
		t.Errorf("name = %q, want read_file", name)
	}
	if fp, ok := args["file_path"].(string); !ok || fp != "main.go" {
		t.Errorf("args[file_path] = %v, want main.go", args["file_path"])
	}
}

func TestParseToolCallFromText_NestedArgs(t *testing.T) {
	text := `{"tool_call":{"name":"search_code","arguments":{"query":"test","filters":{"lang":"go"}}}}`
	name, args, _, found := parseToolCallFromText(text)
	if !found {
		t.Fatal("expected to find tool_call with nested args")
	}
	if name != "search_code" {
		t.Errorf("name = %q, want search_code", name)
	}
	filters, ok := args["filters"].(map[string]interface{})
	if !ok {
		t.Fatalf("args[filters] type = %T, want map[string]interface{}", args["filters"])
	}
	if filters["lang"] != "go" {
		t.Errorf("filters[lang] = %v, want go", filters["lang"])
	}
}

func TestParseToolCallFromText_NoToolCall(t *testing.T) {
	text := `{"thinking":"done","findings":[{"file_path":"main.go"}]}`
	_, _, remaining, found := parseToolCallFromText(text)
	if found {
		t.Error("should not find tool_call in final response")
	}
	if remaining != text {
		t.Error("remainingText should equal original text when no tool_call found")
	}
}

func TestParseToolCallFromText_EmptyInput(t *testing.T) {
	_, _, _, found := parseToolCallFromText("")
	if found {
		t.Error("should not find tool_call in empty string")
	}
}

func TestParseToolCallFromText_MultipleCodeBlocks(t *testing.T) {
	text := "First analysis.\n```json\n{\"thinking\":\"need more info\"}\n```\n\nNow calling tool.\n```json\n{\"tool_call\":{\"name\":\"read_file\",\"arguments\":{\"file_path\":\"app.go\"}}}\n```"
	name, args, _, found := parseToolCallFromText(text)
	if !found {
		t.Fatal("expected to find tool_call in second code block")
	}
	if name != "read_file" {
		t.Errorf("name = %q, want read_file", name)
	}
	if fp, ok := args["file_path"].(string); !ok || fp != "app.go" {
		t.Errorf("args[file_path] = %v, want app.go", args["file_path"])
	}
}

func TestExtractBalancedJSON(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{`{"a":1}`, `{"a":1}`},
		{`{"a":{"b":2}}`, `{"a":{"b":2}}`},
		{`{"a":"{\"b\":2}"}`, `{"a":"{\"b\":2}"}`},
		{`{"a":1} extra`, `{"a":1}`},
		{`not json`, ""},
		{``, ""},
		{`{"a":1`, ""},
		{`{"tool_call":{"name":"search","arguments":{"q":"test"}}} more text`, `{"tool_call":{"name":"search","arguments":{"q":"test"}}}`},
	}

	for _, tt := range tests {
		got := extractBalancedJSON(tt.input)
		if got != tt.expected {
			t.Errorf("extractBalancedJSON(%q) = %q, want %q", tt.input, got, tt.expected)
		}
	}
}

func TestAIClientModel_NonFCMode_StreamGenerate(t *testing.T) {
	stopReason := "stop"
	ch := make(chan *ai.StreamChunk, 4)
	ch <- &ai.StreamChunk{
		Choices: []ai.StreamChoice{
			{Delta: ai.Message{Role: "assistant", Content: "Let me "}, FinishReason: nil},
		},
	}
	ch <- &ai.StreamChunk{
		Choices: []ai.StreamChoice{
			{Delta: ai.Message{Role: "assistant", Content: "search.\n```json\n"}, FinishReason: nil},
		},
	}
	ch <- &ai.StreamChunk{
		Choices: []ai.StreamChoice{
			{Delta: ai.Message{Role: "assistant", Content: `{"tool_call":{"name":"search_code","arguments":{"query":"bug"}}}` + "\n```"}, FinishReason: nil},
		},
	}
	ch <- &ai.StreamChunk{
		Choices: []ai.StreamChoice{
			{Delta: ai.Message{Role: "assistant", Content: ""}, FinishReason: &stopReason},
		},
	}
	close(ch)

	client := &mockAIClient{streamCh: ch}
	model := NewAIClientModelWithFC(client, "test-model", false)
	req := &adkmodel.LLMRequest{
		Contents: []*genai.Content{
			{Role: genai.RoleUser, Parts: []*genai.Part{{Text: "find the bug"}}},
		},
	}

	var resp *adkmodel.LLMResponse
	for r, err := range model.GenerateContent(context.Background(), req, true) {
		if err != nil {
			t.Fatalf("StreamGenerate error: %v", err)
		}
		resp = r
	}

	if resp == nil {
		t.Fatal("resp is nil")
	}

	hasFunctionCall := false
	for _, part := range resp.Content.Parts {
		if part.FunctionCall != nil {
			hasFunctionCall = true
			if part.FunctionCall.Name != "search_code" {
				t.Errorf("FunctionCall.Name = %q, want search_code", part.FunctionCall.Name)
			}
		}
	}
	if !hasFunctionCall {
		t.Error("expected FunctionCall in non-FC stream response")
	}
	if resp.TurnComplete {
		t.Error("tool_call response should have TurnComplete=false")
	}
}

func TestAIClientModel_NonFCMode_StreamFinalResponse(t *testing.T) {
	stopReason := "stop"
	ch := make(chan *ai.StreamChunk, 2)
	ch <- &ai.StreamChunk{
		Choices: []ai.StreamChoice{
			{Delta: ai.Message{Role: "assistant", Content: `{"thinking":"done","findings":[]}`}, FinishReason: nil},
		},
	}
	ch <- &ai.StreamChunk{
		Choices: []ai.StreamChoice{
			{Delta: ai.Message{Role: "assistant", Content: ""}, FinishReason: &stopReason},
		},
	}
	close(ch)

	client := &mockAIClient{streamCh: ch}
	model := NewAIClientModelWithFC(client, "test-model", false)
	req := &adkmodel.LLMRequest{
		Contents: []*genai.Content{
			{Role: genai.RoleUser, Parts: []*genai.Part{{Text: "analyze"}}},
		},
	}

	var resp *adkmodel.LLMResponse
	for r, err := range model.GenerateContent(context.Background(), req, true) {
		if err != nil {
			t.Fatalf("StreamGenerate error: %v", err)
		}
		resp = r
	}

	if resp == nil {
		t.Fatal("resp is nil")
	}
	if !resp.TurnComplete {
		t.Error("final response without tool_call should have TurnComplete=true")
	}
}

func TestAIClientModel_NonFCMode_NoResponseFormatWithTools(t *testing.T) {
	client := &mockAIClient{}
	model := NewAIClientModelWithFC(client, "test-model", false)

	req := &adkmodel.LLMRequest{
		Contents: []*genai.Content{
			{Role: genai.RoleUser, Parts: []*genai.Part{{Text: "search"}}},
		},
		Config: &genai.GenerateContentConfig{
			Tools: []*genai.Tool{
				{
					FunctionDeclarations: []*genai.FunctionDeclaration{
						{Name: "search_code", Description: "Search"},
					},
				},
			},
		},
	}

	chatReq := model.convertRequest(req, false)
	if chatReq.ResponseFormat != nil {
		t.Error("NonFC mode with tools should not set ResponseFormat")
	}
}

func TestAIClientModel_FCMode_ResponseFormatWithoutTools(t *testing.T) {
	client := &mockAIClient{}
	model := NewAIClientModelWithFC(client, "test-model", true)

	req := &adkmodel.LLMRequest{
		Contents: []*genai.Content{
			{Role: genai.RoleUser, Parts: []*genai.Part{{Text: "analyze"}}},
		},
	}

	chatReq := model.convertRequest(req, false)
	if chatReq.ResponseFormat == nil {
		t.Error("FC mode without tools should set ResponseFormat")
	}
	if chatReq.ResponseFormat.Type != "json_object" {
		t.Errorf("ResponseFormat.Type = %q, want json_object", chatReq.ResponseFormat.Type)
	}
}

func TestResolveFCSupport(t *testing.T) {
	tests := []struct {
		mode     string
		expected bool
	}{
		{"enabled", true},
		{"disabled", false},
		{"", true},
		{"auto", true},
	}

	for _, tt := range tests {
		cfg := &bugmodel.ProjectAIConfig{
			Provider:            "test",
			ModelName:           "test-model",
			FunctionCallingMode: tt.mode,
		}
		got := resolveFCSupport(cfg)
		if got != tt.expected {
			t.Errorf("resolveFCSupport(mode=%q) = %v, want %v", tt.mode, got, tt.expected)
		}
	}
}
