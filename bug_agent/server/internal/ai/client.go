package ai

import (
	"context"
	"io"
	"time"
)

const defaultAIHTTPTimeout = 10 * time.Minute

// AIClient AI服务客户端接口
type AIClient interface {
	Chat(ctx context.Context, req *ChatRequest) (*ChatResponse, error)
	ChatStream(ctx context.Context, req *ChatRequest) (<-chan *StreamChunk, error)
}

// ChatRequest 聊天请求
type ChatRequest struct {
	Model          string          `json:"model"`
	Messages       []Message       `json:"messages"`
	Temperature    float64         `json:"temperature,omitempty"`
	MaxTokens      int             `json:"max_tokens,omitempty"`
	TopP           float64         `json:"top_p,omitempty"`
	Stream         bool            `json:"stream,omitempty"`
	Stop           []string        `json:"stop,omitempty"`
	ResponseFormat *ResponseFormat `json:"response_format,omitempty"`
	Tools          []Tool          `json:"tools,omitempty"`
}

type ResponseFormat struct {
	Type string `json:"type"` // "json_object" or "text"
}

type Tool struct {
	Type     string       `json:"type"` // "function"
	Function ToolFunction `json:"function"`
}

type ToolFunction struct {
	Name        string                  `json:"name"`
	Description string                  `json:"description,omitempty"`
	Parameters  *ToolFunctionParameters `json:"parameters,omitempty"`
}

type ToolFunctionParameters struct {
	Type       string                       `json:"type"` // "object"
	Properties map[string]ToolParamProperty `json:"properties,omitempty"`
	Required   []string                     `json:"required,omitempty"`
}

type ToolParamProperty struct {
	Type        string `json:"type"`
	Description string `json:"description,omitempty"`
}

// Message 消息
type Message struct {
	Role       string     `json:"role"`    // system, user, assistant, tool
	Content    string     `json:"content"` // 可以是文本或JSON
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
	ToolCallID string     `json:"tool_call_id,omitempty"`
}

type ToolCall struct {
	Index     int    `json:"index"`
	ID        string `json:"id"`
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

type ToolResult struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Result string `json:"result"`
}

// ChatResponse 聊天响应
type ChatResponse struct {
	ID      string   `json:"id"`
	Object  string   `json:"object"`
	Created int64    `json:"created"`
	Model   string   `json:"model"`
	Choices []Choice `json:"choices"`
	Usage   Usage    `json:"usage"`
}

// Choice 选择项
type Choice struct {
	Index        int     `json:"index"`
	Message      Message `json:"message"`
	FinishReason string  `json:"finish_reason"`
}

// Usage 使用量统计
type Usage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

// StreamChunk 流式响应块
type StreamChunk struct {
	ID      string         `json:"id"`
	Object  string         `json:"object"`
	Created int64          `json:"created"`
	Model   string         `json:"index"`
	Choices []StreamChoice `json:"choices"`
}

// StreamChoice 流式选择项
type StreamChoice struct {
	Index        int     `json:"index"`
	Delta        Message `json:"delta"`
	FinishReason *string `json:"finish_reason"`
}

// StreamReader 流式读取器
type StreamReader interface {
	Recv() (StreamChunk, error)
	Close() error
	io.Closer
}

// truncateBody 截断响应体，防止错误消息中泄露过长的敏感信息
func truncateBody(body []byte, maxLen int) string {
	s := string(body)
	if len(s) > maxLen {
		return s[:maxLen] + "...(truncated)"
	}
	return s
}
