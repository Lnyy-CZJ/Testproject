package adk

import (
	"context"
	"encoding/json"
	"fmt"
	"iter"
	"regexp"
	"strings"

	"bug-agent/internal/ai"
	"bug-agent/pkg/logger"

	"google.golang.org/genai"
	adkmodel "google.golang.org/adk/model"
)

type AIClientModel struct {
	client         ai.AIClient
	model          string
	responseFormat *ai.ResponseFormat
	supportsFC     bool
}

func NewAIClientModel(client ai.AIClient, modelName string) *AIClientModel {
	return &AIClientModel{client: client, model: modelName, supportsFC: true}
}

func NewAIClientModelWithJSON(client ai.AIClient, modelName string) *AIClientModel {
	return &AIClientModel{
		client:         client,
		model:          modelName,
		responseFormat: &ai.ResponseFormat{Type: "json_object"},
		supportsFC:     true,
	}
}

func NewAIClientModelWithFC(client ai.AIClient, modelName string, supportsFC bool) *AIClientModel {
	return &AIClientModel{
		client:         client,
		model:          modelName,
		responseFormat: &ai.ResponseFormat{Type: "json_object"},
		supportsFC:     supportsFC,
	}
}

func (m *AIClientModel) WithoutResponseFormat() *AIClientModel {
	return &AIClientModel{
		client:         m.client,
		model:          m.model,
		responseFormat: nil,
		supportsFC:     m.supportsFC,
	}
}

func LLMWithoutResponseFormat(llm adkmodel.LLM) adkmodel.LLM {
	if m, ok := llm.(*AIClientModel); ok {
		return m.WithoutResponseFormat()
	}
	return llm
}

func (m *AIClientModel) SupportsFC() bool {
	return m.supportsFC
}

func (m *AIClientModel) Name() string {
	return m.model
}

func (m *AIClientModel) GenerateContent(ctx context.Context, req *adkmodel.LLMRequest, stream bool) iter.Seq2[*adkmodel.LLMResponse, error] {
	if stream {
		return m.streamGenerate(ctx, req)
	}
	return m.generateContent(ctx, req)
}

func (m *AIClientModel) generateContent(ctx context.Context, req *adkmodel.LLMRequest) iter.Seq2[*adkmodel.LLMResponse, error] {
	return func(yield func(*adkmodel.LLMResponse, error) bool) {
		chatReq := m.convertRequest(req, false)
		resp, err := m.client.Chat(ctx, chatReq)
		if err != nil {
			yield(nil, fmt.Errorf("AIClientModel.Chat: %w", err))
			return
		}
		yield(m.convertResponse(resp), nil)
	}
}

func (m *AIClientModel) streamGenerate(ctx context.Context, req *adkmodel.LLMRequest) iter.Seq2[*adkmodel.LLMResponse, error] {
	return func(yield func(*adkmodel.LLMResponse, error) bool) {
		chatReq := m.convertRequest(req, true)
		ch, err := m.client.ChatStream(ctx, chatReq)
		if err != nil {
			yield(nil, fmt.Errorf("AIClientModel.ChatStream: %w", err))
			return
		}

		if !m.supportsFC {
			m.streamGenerateNonFC(ctx, ch, yield)
			return
		}

		var pendingToolCalls []streamToolCallAccumulator

		for chunk := range ch {
			select {
			case <-ctx.Done():
				yield(nil, ctx.Err())
				return
			default:
			}
			if chunk == nil {
				continue
			}

			isFinal := len(chunk.Choices) > 0 && chunk.Choices[0].FinishReason != nil

			if isFinal {
				resp := m.convertStreamChunk(chunk)

				if len(pendingToolCalls) > 0 {
					var parts []*genai.Part
					if resp.Content != nil {
						for _, p := range resp.Content.Parts {
							if p.Text != "" {
								parts = append(parts, p)
							}
						}
					}
					for _, acc := range pendingToolCalls {
						var args map[string]interface{}
						if err := json.Unmarshal([]byte(acc.arguments), &args); err != nil {
							args = map[string]interface{}{"raw": acc.arguments}
						}
						parts = append(parts, &genai.Part{
							FunctionCall: &genai.FunctionCall{
								Name: acc.name,
								Args: args,
							},
						})
					}
					if len(parts) == 0 {
						parts = append(parts, &genai.Part{Text: ""})
					}
					resp.Content.Parts = parts
				}

				resp.TurnComplete = true
				resp.Partial = false
				if !yield(resp, nil) {
					return
				}
				return
			}

			if len(chunk.Choices) > 0 {
				delta := chunk.Choices[0].Delta
				for _, tc := range delta.ToolCalls {
					idx := tc.Index
					for len(pendingToolCalls) <= idx {
						pendingToolCalls = append(pendingToolCalls, streamToolCallAccumulator{})
					}
					if tc.Name != "" {
						pendingToolCalls[idx].name = tc.Name
					}
					if tc.Arguments != "" {
						pendingToolCalls[idx].arguments += tc.Arguments
					}
				}

				if len(delta.ToolCalls) > 0 && delta.Content == "" {
					continue
				}
			}

			resp := m.convertStreamChunk(chunk)
			if !yield(resp, nil) {
				return
			}
		}
	}
}

func (m *AIClientModel) streamGenerateNonFC(ctx context.Context, ch <-chan *ai.StreamChunk, yield func(*adkmodel.LLMResponse, error) bool) {
	var textBuf strings.Builder

	for chunk := range ch {
		select {
		case <-ctx.Done():
			yield(nil, ctx.Err())
			return
		default:
		}
		if chunk == nil {
			continue
		}

		if len(chunk.Choices) > 0 && chunk.Choices[0].Delta.Content != "" {
			textBuf.WriteString(chunk.Choices[0].Delta.Content)
		}

		isFinal := len(chunk.Choices) > 0 && chunk.Choices[0].FinishReason != nil
		if isFinal {
			fullText := textBuf.String()
			resp := m.parseTextResponseAsLLMResponse(fullText)

			if !resp.TurnComplete {
				resp.Partial = false
			} else {
				for _, sc := range chunk.Choices {
					if sc.FinishReason != nil {
						resp.TurnComplete = *sc.FinishReason == "stop"
						resp.Partial = false
					}
				}
			}

			if !yield(resp, nil) {
				return
			}
			return
		}
	}
}

type streamToolCallAccumulator struct {
	name      string
	arguments string
}

func (m *AIClientModel) convertRequest(req *adkmodel.LLMRequest, isStream bool) *ai.ChatRequest {
	messages := make([]ai.Message, 0, len(req.Contents)+1)

	if req.Config != nil && req.Config.SystemInstruction != nil {
		var sysParts []string
		for _, part := range req.Config.SystemInstruction.Parts {
			if part.Text != "" {
				sysParts = append(sysParts, part.Text)
			}
		}
		if len(sysParts) > 0 {
			messages = append(messages, ai.Message{
				Role:    "system",
				Content: joinStrings(sysParts),
			})
		}
	}

	var adkTools []*genai.Tool
	if req.Config != nil {
		adkTools = req.Config.Tools
	}

	if m.supportsFC {
		messages = m.convertMessagesFC(req, messages)
	} else {
		messages = m.convertMessagesNonFC(req, messages, adkTools)
	}

	chatReq := &ai.ChatRequest{
		Model:    m.model,
		Messages: messages,
	}

	if m.supportsFC && len(adkTools) > 0 {
		tools := convertADKTools(adkTools)
		if len(tools) > 0 {
			chatReq.Tools = tools
		}
	}

	if m.responseFormat != nil && !isStream && len(chatReq.Tools) == 0 {
		if m.supportsFC || len(adkTools) == 0 {
			chatReq.ResponseFormat = m.responseFormat
		}
	}

	if req.Config != nil {
		if req.Config.Temperature != nil {
			chatReq.Temperature = float64(*req.Config.Temperature)
		}
		chatReq.MaxTokens = int(req.Config.MaxOutputTokens)
		if req.Config.TopP != nil {
			chatReq.TopP = float64(*req.Config.TopP)
		}
		if len(req.Config.StopSequences) > 0 {
			chatReq.Stop = req.Config.StopSequences
		}
	}

	return chatReq
}

func (m *AIClientModel) convertMessagesFC(req *adkmodel.LLMRequest, messages []ai.Message) []ai.Message {
	for _, content := range req.Contents {
		role := string(content.Role)
		var textParts []string
		var toolCalls []ai.ToolCall
		var toolResults []ai.ToolResult

		for _, part := range content.Parts {
			if part.Text != "" {
				textParts = append(textParts, part.Text)
			}
			if part.FunctionCall != nil {
				argsJSON, err := json.Marshal(part.FunctionCall.Args)
				if err != nil {
					argsJSON = []byte("{}")
				}
				callID := part.FunctionCall.Name
				if part.FunctionCall.ID != "" {
					callID = part.FunctionCall.ID
				}
				toolCalls = append(toolCalls, ai.ToolCall{
					ID:        callID,
					Name:      part.FunctionCall.Name,
					Arguments: string(argsJSON),
				})
			}
			if part.FunctionResponse != nil {
				respJSON, err := json.Marshal(part.FunctionResponse.Response)
				if err != nil {
					respJSON = []byte("{}")
				}
				respID := part.FunctionResponse.Name
				if part.FunctionResponse.ID != "" {
					respID = part.FunctionResponse.ID
				}
				toolResults = append(toolResults, ai.ToolResult{
					ID:     respID,
					Name:   part.FunctionResponse.Name,
					Result: string(respJSON),
				})
			}
		}

		if len(toolResults) > 0 {
			for _, tr := range toolResults {
				messages = append(messages, ai.Message{
					Role:       "tool",
					Content:    tr.Result,
					ToolCallID: tr.ID,
				})
			}
			continue
		}

		msg := ai.Message{Role: role}
		if len(textParts) > 0 {
			msg.Content = joinStrings(textParts)
		}
		if len(toolCalls) > 0 {
			msg.ToolCalls = toolCalls
			if msg.Content == "" {
				msg.Content = formatToolCallsAsText(toolCalls)
			}
		}

		if msg.Content != "" || len(msg.ToolCalls) > 0 {
			messages = append(messages, msg)
		}
	}
	return messages
}

func (m *AIClientModel) convertMessagesNonFC(req *adkmodel.LLMRequest, messages []ai.Message, adkTools []*genai.Tool) []ai.Message {
	if len(adkTools) > 0 {
		toolPrompt := buildToolPrompt(adkTools)
		if len(messages) > 0 && messages[0].Role == "system" {
			messages[0].Content += "\n\n" + toolPrompt
		} else {
			messages = append([]ai.Message{{Role: "system", Content: toolPrompt}}, messages...)
		}
	}

	for _, content := range req.Contents {
		role := string(content.Role)
		var textParts []string

		for _, part := range content.Parts {
			if part.Text != "" {
				textParts = append(textParts, part.Text)
			}
			if part.FunctionCall != nil {
				argsJSON, _ := json.Marshal(part.FunctionCall.Args)
				textParts = append(textParts, fmt.Sprintf("Tool call: %s(%s)", part.FunctionCall.Name, string(argsJSON)))
			}
			if part.FunctionResponse != nil {
				respJSON, _ := json.Marshal(part.FunctionResponse.Response)
				textParts = append(textParts, fmt.Sprintf("Tool %s result:\n%s", part.FunctionResponse.Name, string(respJSON)))
			}
		}

		if len(textParts) > 0 {
			msgRole := role
			if role == "tool" {
				msgRole = "user"
			}
			messages = append(messages, ai.Message{
				Role:    msgRole,
				Content: joinStrings(textParts),
			})
		}
	}
	return messages
}

func buildToolPrompt(adkTools []*genai.Tool) string {
	var b strings.Builder
	b.WriteString("You have access to the following tools:\n\n")

	for _, t := range adkTools {
		for _, fd := range t.FunctionDeclarations {
			b.WriteString(fmt.Sprintf("### %s\n%s\n", fd.Name, fd.Description))
			if fd.Parameters != nil {
				params := map[string]interface{}{}
				params["type"] = "object"
				props := map[string]map[string]string{}
				for name, prop := range fd.Parameters.Properties {
					p := map[string]string{"type": "string"}
					if prop.Type != "" {
						p["type"] = string(prop.Type)
					}
					if prop.Description != "" {
						p["description"] = prop.Description
					}
					props[name] = p
				}
				params["properties"] = props
				if len(fd.Parameters.Required) > 0 {
					params["required"] = fd.Parameters.Required
				}
				paramsJSON, _ := json.Marshal(params)
				b.WriteString(fmt.Sprintf("Parameters: %s\n\n", string(paramsJSON)))
			}
		}
	}

	b.WriteString("To call a tool, output a JSON block in this exact format:\n")
	b.WriteString("```json\n")
	b.WriteString(`{"tool_call":{"name":"tool_name","arguments":{"param1":"value1"}}}` + "\n")
	b.WriteString("```\n\n")
	b.WriteString("You can call only ONE tool per response. After receiving the tool result, decide your next step.\n")
	b.WriteString("When you have completed your analysis and no longer need tools, output your final result WITHOUT a tool_call field.\n")

	return b.String()
}

var toolCallPattern = regexp.MustCompile("(?s)```json\\s*\\n?(\\{.*?\\})\\s*\\n?```")

func parseToolCallFromText(text string) (toolName string, toolArgs map[string]interface{}, remainingText string, found bool) {
	matches := toolCallPattern.FindAllStringSubmatch(text, -1)
	for _, match := range matches {
		if len(match) < 2 {
			continue
		}
		jsonStr := match[1]
		var parsed map[string]interface{}
		if err := json.Unmarshal([]byte(jsonStr), &parsed); err != nil {
			continue
		}
		tc, ok := parsed["tool_call"]
		if !ok {
			continue
		}
		tcMap, ok := tc.(map[string]interface{})
		if !ok {
			continue
		}
		name, _ := tcMap["name"].(string)
		args, _ := tcMap["arguments"].(map[string]interface{})
		if name == "" {
			continue
		}
		return name, args, "", true
	}

	idx := strings.Index(text, `{"tool_call"`)
	if idx >= 0 {
		jsonStr := extractBalancedJSON(text[idx:])
		if jsonStr != "" {
			var parsed map[string]interface{}
			if err := json.Unmarshal([]byte(jsonStr), &parsed); err == nil {
				if tc, ok := parsed["tool_call"].(map[string]interface{}); ok {
					name, _ := tc["name"].(string)
					args, _ := tc["arguments"].(map[string]interface{})
					if name != "" {
						return name, args, "", true
					}
				}
			}
		}
	}

	return "", nil, text, false
}

func extractBalancedJSON(s string) string {
	if len(s) == 0 || s[0] != '{' {
		return ""
	}
	depth := 0
	inStr := false
	escape := false
	for i, c := range s {
		if escape {
			escape = false
			continue
		}
		if c == '\\' && inStr {
			escape = true
			continue
		}
		if c == '"' {
			inStr = !inStr
			continue
		}
		if inStr {
			continue
		}
		if c == '{' {
			depth++
		} else if c == '}' {
			depth--
			if depth == 0 {
				return s[:i+1]
			}
		}
	}
	return ""
}

func (m *AIClientModel) parseTextResponseAsLLMResponse(text string) *adkmodel.LLMResponse {
	adkResp := &adkmodel.LLMResponse{
		Content: &genai.Content{
			Role: genai.RoleModel,
		},
	}

	if !m.supportsFC {
		toolName, toolArgs, remainingText, found := parseToolCallFromText(text)
		if found {
			logger.Infof("[NonFC] Parsed tool call from text: %s(%v)", toolName, toolArgs)
			var parts []*genai.Part
			if remainingText != "" {
				parts = append(parts, &genai.Part{Text: remainingText})
			}
			parts = append(parts, &genai.Part{
				FunctionCall: &genai.FunctionCall{
					Name: toolName,
					Args: toolArgs,
				},
			})
			adkResp.Content.Parts = parts
			adkResp.TurnComplete = false
			return adkResp
		}
	}

	parts := []*genai.Part{{Text: text}}
	if text == "" {
		parts[0].Text = ""
	}
	adkResp.Content.Parts = parts
	adkResp.TurnComplete = true
	return adkResp
}

func convertADKTools(adkTools []*genai.Tool) []ai.Tool {
	var tools []ai.Tool
	for _, t := range adkTools {
		for _, fd := range t.FunctionDeclarations {
			tool := ai.Tool{
				Type: "function",
				Function: ai.ToolFunction{
					Name:        fd.Name,
					Description: fd.Description,
				},
			}
			if fd.Parameters != nil {
				params := &ai.ToolFunctionParameters{
					Type:       "object",
					Properties: make(map[string]ai.ToolParamProperty),
					Required:   fd.Parameters.Required,
				}
				for name, prop := range fd.Parameters.Properties {
					propType := "string"
					if prop.Type != "" {
						propType = string(prop.Type)
					}
					params.Properties[name] = ai.ToolParamProperty{
						Type:        propType,
						Description: prop.Description,
					}
				}
				tool.Function.Parameters = params
			}
			tools = append(tools, tool)
		}
	}
	return tools
}

func (m *AIClientModel) convertResponse(resp *ai.ChatResponse) *adkmodel.LLMResponse {
	adkResp := &adkmodel.LLMResponse{
		Content: &genai.Content{
			Role: genai.RoleModel,
		},
	}

	if len(resp.Choices) == 0 {
		adkResp.Content.Parts = []*genai.Part{{Text: ""}}
		return adkResp
	}

	choice := resp.Choices[0]

	if m.supportsFC {
		parts := []*genai.Part{}

		if choice.Message.Content != "" {
			parts = append(parts, &genai.Part{Text: choice.Message.Content})
		}

		for _, tc := range choice.Message.ToolCalls {
			var args map[string]interface{}
			if err := json.Unmarshal([]byte(tc.Arguments), &args); err != nil {
				args = map[string]interface{}{"raw": tc.Arguments}
			}
			parts = append(parts, &genai.Part{
				FunctionCall: &genai.FunctionCall{
					Name: tc.Name,
					Args: args,
				},
			})
		}

		if len(parts) == 0 {
			parts = append(parts, &genai.Part{Text: ""})
		}

		adkResp.Content.Parts = parts
		adkResp.TurnComplete = choice.FinishReason == "stop"
	} else {
		text := choice.Message.Content
		toolName, toolArgs, remainingText, found := parseToolCallFromText(text)
		if found {
			var parts []*genai.Part
			if remainingText != "" {
				parts = append(parts, &genai.Part{Text: remainingText})
			}
			parts = append(parts, &genai.Part{
				FunctionCall: &genai.FunctionCall{
					Name: toolName,
					Args: toolArgs,
				},
			})
			adkResp.Content.Parts = parts
			adkResp.TurnComplete = false
		} else {
			adkResp.Content.Parts = []*genai.Part{{Text: text}}
			adkResp.TurnComplete = choice.FinishReason == "stop"
		}
	}

	adkResp.UsageMetadata = &genai.GenerateContentResponseUsageMetadata{
		PromptTokenCount:     int32(resp.Usage.PromptTokens),
		CandidatesTokenCount: int32(resp.Usage.CompletionTokens),
		TotalTokenCount:      int32(resp.Usage.TotalTokens),
	}

	return adkResp
}

func (m *AIClientModel) convertStreamChunk(chunk *ai.StreamChunk) *adkmodel.LLMResponse {
	adkResp := &adkmodel.LLMResponse{
		Content: &genai.Content{
			Role: genai.RoleModel,
		},
		Partial: true,
	}

	if len(chunk.Choices) > 0 {
		choice := chunk.Choices[0]
		parts := []*genai.Part{}

		if choice.Delta.Content != "" {
			parts = append(parts, &genai.Part{Text: choice.Delta.Content})
		}

		if m.supportsFC {
			for _, tc := range choice.Delta.ToolCalls {
				var args map[string]interface{}
				if err := json.Unmarshal([]byte(tc.Arguments), &args); err != nil {
					args = map[string]interface{}{"raw": tc.Arguments}
				}
				parts = append(parts, &genai.Part{
					FunctionCall: &genai.FunctionCall{
						Name: tc.Name,
						Args: args,
					},
				})
			}
		}

		if len(parts) == 0 {
			parts = append(parts, &genai.Part{Text: ""})
		}

		adkResp.Content.Parts = parts
		if choice.FinishReason != nil {
			adkResp.TurnComplete = *choice.FinishReason == "stop"
			adkResp.Partial = false
		}
	}

	return adkResp
}

func joinStrings(parts []string) string {
	return strings.Join(parts, "")
}

func formatToolCallsAsText(toolCalls []ai.ToolCall) string {
	b, err := json.Marshal(toolCalls)
	if err != nil {
		return "[]"
	}
	return string(b)
}

func formatToolResultsAsText(results []ai.ToolResult) string {
	b, err := json.Marshal(results)
	if err != nil {
		return "[]"
	}
	return string(b)
}
