package ai

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"bug-agent/internal/asyncx"
)

const defaultAnthropicMaxTokens = 4096

type AnthropicClient struct {
	apiKey     string
	baseURL    string
	httpClient *http.Client
	model      string
}

func NewAnthropicClient(apiKey, baseURL, model string) *AnthropicClient {
	if baseURL == "" {
		baseURL = "https://api.anthropic.com"
	}
	return &AnthropicClient{
		apiKey:  apiKey,
		baseURL: strings.TrimRight(baseURL, "/"),
		httpClient: &http.Client{
			Timeout: defaultAIHTTPTimeout,
		},
		model: model,
	}
}

type anthropicRequest struct {
	Model     string                `json:"model"`
	MaxTokens int                   `json:"max_tokens"`
	Messages  []anthropicMessage    `json:"messages"`
	System    string                `json:"system,omitempty"`
	Temperature float64             `json:"temperature,omitempty"`
	Stream    bool                  `json:"stream,omitempty"`
}

type anthropicMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type anthropicResponse struct {
	ID           string              `json:"id"`
	Type         string              `json:"type"`
	Role         string              `json:"_role"`
	Model        string              `json:"model"`
	Content      []anthropicContent  `json:"content"`
	StopReason   string              `json:"stop_reason"`
	Usage        anthropicUsage      `json:"usage"`
}

type anthropicContent struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

type anthropicUsage struct {
	InputTokens  int `json:"input_tokens"`
	OutputTokens int `json:"output_tokens"`
}

func (c *AnthropicClient) Chat(ctx context.Context, req *ChatRequest) (*ChatResponse, error) {
	messages := make([]anthropicMessage, len(req.Messages))
	for i, m := range req.Messages {
		messages[i] = anthropicMessage{Role: m.Role, Content: m.Content}
	}

	system := ""
	if len(req.Messages) > 0 && req.Messages[0].Role == "system" {
		system = req.Messages[0].Content
		messages = messages[1:]
	}

	maxTokens := req.MaxTokens
	if maxTokens == 0 {
		maxTokens = defaultAnthropicMaxTokens
	}

	bodyReq := anthropicRequest{
		Model:       c.model,
		MaxTokens:   maxTokens,
		Messages:    messages,
		System:      system,
		Temperature: req.Temperature,
	}

	reqBody, err := json.Marshal(bodyReq)
	if err != nil {
		return nil, fmt.Errorf("marshal failed: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/v1/messages", bytes.NewReader(reqBody))
	if err != nil {
		return nil, fmt.Errorf("create request failed: %w", err)
	}

	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("x-api-key", c.apiKey)
	httpReq.Header.Set("anthropic-version", "2023-06-01")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("send failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
	if err != nil {
		return nil, fmt.Errorf("read response failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API error: status=%d body=%s", resp.StatusCode, truncateBody(respBody, 200))
	}

	var aResp anthropicResponse
	if err := json.Unmarshal(respBody, &aResp); err != nil {
		return nil, fmt.Errorf("unmarshal failed: %w", err)
	}

	content := ""
	for _, block := range aResp.Content {
		if block.Type == "text" {
			content += block.Text
		}
	}

	finishReason := aResp.StopReason
	if finishReason == "" {
		finishReason = "stop"
	}

	return &ChatResponse{
		ID:      aResp.ID,
		Object:  "chat.completion",
		Created: time.Now().Unix(),
		Model:   aResp.Model,
		Choices: []Choice{{
			Message:      Message{Role: "assistant", Content: content},
			FinishReason: finishReason,
		}},
		Usage: Usage{
			PromptTokens:     aResp.Usage.InputTokens,
			CompletionTokens: aResp.Usage.OutputTokens,
			TotalTokens:      aResp.Usage.InputTokens + aResp.Usage.OutputTokens,
		},
	}, nil
}

func (c *AnthropicClient) ChatStream(ctx context.Context, req *ChatRequest) (<-chan *StreamChunk, error) {
	messages := make([]anthropicMessage, len(req.Messages))
	for i, m := range req.Messages {
		messages[i] = anthropicMessage{Role: m.Role, Content: m.Content}
	}

	system := ""
	if len(req.Messages) > 0 && req.Messages[0].Role == "system" {
		system = req.Messages[0].Content
		messages = messages[1:]
	}

	maxTokens := req.MaxTokens
	if maxTokens == 0 {
		maxTokens = defaultAnthropicMaxTokens
	}

	bodyReq := anthropicRequest{
		Model:       c.model,
		MaxTokens:   maxTokens,
		Messages:    messages,
		System:      system,
		Temperature: req.Temperature,
		Stream:      true,
	}

	reqBody, err := json.Marshal(bodyReq)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/v1/messages", bytes.NewReader(reqBody))
	if err != nil {
		return nil, err
	}

	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("x-api-key", c.apiKey)
	httpReq.Header.Set("anthropic-version", "2023-06-01")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, err
	}

	if resp.StatusCode != http.StatusOK {
		defer resp.Body.Close()
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("anthropic ChatStream API error: HTTP %d %s", resp.StatusCode, truncateBody(raw, 200))
	}

	ch := make(chan *StreamChunk, 64)
	asyncx.Go(func() {
		defer close(ch)
		defer resp.Body.Close()

		scanner := bufio.NewScanner(resp.Body)
		scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
		for scanner.Scan() {
			select {
			case <-ctx.Done():
				return
			default:
			}

			line := scanner.Text()
			if !strings.HasPrefix(line, "data: ") {
				continue
			}
			data := strings.TrimPrefix(line, "data: ")
			if data == "[DONE]" {
				break
			}

			var evt struct {
				Type  string `json:"type"`
				Delta struct {
					Type string `json:"type"`
					Text string `json:"text"`
				} `json:"delta"`
			}
			if json.Unmarshal([]byte(data), &evt) != nil {
				continue
			}

			if evt.Type == "content_block_delta" && evt.Delta.Text != "" {
				select {
				case ch <- &StreamChunk{
					Choices: []StreamChoice{{
						Delta: Message{Content: evt.Delta.Text},
					}},
				}:
				case <-ctx.Done():
					return
				}
			}

			if evt.Type == "message_stop" {
				break
			}
		}

		if err := scanner.Err(); err != nil {
			finishReason := "error"
			select {
			case ch <- &StreamChunk{Choices: []StreamChoice{{FinishReason: &finishReason}}}:
			case <-ctx.Done():
			}
		}
	})

	return ch, nil
}
