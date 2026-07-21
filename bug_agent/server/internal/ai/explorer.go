package ai

import (
	"context"
	"encoding/json"
	"fmt"
	"bug-agent/pkg/logger"
	"regexp"
	"strings"
	"time"
)

type ExplorerTool struct {
	Name        string
	Description string
	Parameters  map[string]ExplorerParam
}

type ExplorerParam struct {
	Type        string `json:"type"`
	Description string `json:"description"`
	Required    bool   `json:"required"`
}

type ExplorerResult struct {
	EnrichedContext string
	ExtraFiles      []string
	ToolCalls       int
	TokensUsed      int
}

const explorerMaxTotalTokens = 128000

type CodeExplorer struct {
	client         AIClient
	tools          map[string]ExplorerTool
	maxRounds      int
	maxTotalTokens int
}

func NewCodeExplorer(client AIClient) *CodeExplorer {
	e := &CodeExplorer{
		client:         client,
		tools:          make(map[string]ExplorerTool),
		maxRounds:      8,
		maxTotalTokens: explorerMaxTotalTokens,
	}
	e.registerTools()
	return e
}

func (e *CodeExplorer) registerTools() {
	e.tools["search_code"] = ExplorerTool{
		Name:        "search_code",
		Description: "Search for code symbols related to a query using semantic search. Returns matching file paths, symbol names, and line numbers.",
		Parameters: map[string]ExplorerParam{
			"query": {Type: "string", Description: "Natural language search query", Required: true},
		},
	}

	e.tools["read_file"] = ExplorerTool{
		Name:        "read_file",
		Description: "Read the content of a file from the repository. Returns the full file content with line numbers.",
		Parameters: map[string]ExplorerParam{
			"file_path": {Type: "string", Description: "Path to the file relative to repo root", Required: true},
		},
	}

	e.tools["trace_call"] = ExplorerTool{
		Name:        "trace_call",
		Description: "Trace the call graph from a symbol. Follow upstream (who calls it) or downstream (what it calls). Useful for tracking data flow across files.",
		Parameters: map[string]ExplorerParam{
			"symbol_id": {Type: "string", Description: "Symbol ID in format 'path/to/file.go::StructName.methodName'", Required: true},
			"direction": {Type: "string", Description: "Trace direction: 'up' (callers) or 'down' (callees)", Required: true},
		},
	}

	e.tools["find_api_handler"] = ExplorerTool{
		Name:        "find_api_handler",
		Description: "Given a frontend API call path (e.g., '/audit-logs'), find the backend handler function that processes this request. Returns the handler file path and function name.",
		Parameters: map[string]ExplorerParam{
			"api_path":    {Type: "string", Description: "API path from frontend (e.g., '/audit-logs', '/defects/:id')", Required: true},
			"http_method": {Type: "string", Description: "HTTP method: GET, POST, PUT, DELETE", Required: true},
		},
	}
}

func (e *CodeExplorer) toolsDescription() string {
	var b strings.Builder
	b.WriteString("You have access to the following tools:\n\n")
	for _, tool := range e.tools {
		b.WriteString(fmt.Sprintf("### %s\n%s\nParameters:\n", tool.Name, tool.Description))
		paramsJSON, err := json.Marshal(tool.Parameters)
		if err != nil {
			paramsJSON = []byte("{}")
		}
		b.WriteString(fmt.Sprintf("```json\n%s\n```\n\n", string(paramsJSON)))
	}
	return b.String()
}

type ExplorerContext struct {
	DefectTitle       string
	DefectDescription string
	InitialContext    string
	RelatedFiles      []string
	RepoName          string

	SearchFn  func(ctx context.Context, query string) ([]SearchHit, error)
	ReadFn    func(ctx context.Context, filePath string) (string, error)
	TraceFn   func(ctx context.Context, symbolID, direction string) ([]TraceHit, error)
	HandlerFn func(ctx context.Context, apiPath, httpMethod string) ([]HandlerHit, error)
}

type SearchHit struct {
	FilePath string
	SymbolID string
	Line     int
	Snippet  string
}

type TraceHit struct {
	SymbolID string
	Document string
	FilePath string
}

type HandlerHit struct {
	FilePath   string
	FuncName   string
	LineNumber int
}

type DirEntry struct {
	Name string
	Type string
}

func (e *CodeExplorer) Explore(ctx context.Context, expCtx ExplorerContext) (*ExplorerResult, error) {
	startTime := time.Now()
	result := &ExplorerResult{}

	systemPrompt := `追踪代码中的数据通路断裂点。只输出JSON，不要其他文字。

工作流：
1. 读前端文件 → 找API调用
2. 用 find_api_handler 找后端handler
3. 读handler代码 → 检查响应格式
4. 对比前端期望 vs 后端实际返回

常见断裂模式：
- 前端期望 {code:0, data:...} 但后端返回裸 {data:...}
- 前端期望 camelCase 但后端返回 snake_case
- 前端期望 data.list 但后端返回扁平数组
- 请求拦截器解包了响应但前端又解包一次

` + e.toolsDescription() + `

调用工具时输出：
` + "```" + `json
{"thinking":"...","tool_call":{"name":"工具名","arguments":{...}}}
` + "```" + `

完成时输出：
` + "```" + `json
{"thinking":"...","findings":[{"file_path":"...","evidence":"...","severity":"critical|high|medium"}],"data_path_summary":"前端→API→后端→响应→前端状态→UI，断裂点在..."}
` + "```" + `

约束：
- 必须调用工具读代码，不要猜测
- 每次只输出一个JSON块
- findings.evidence ≤2句话`

	userMsg := fmt.Sprintf("缺陷: %s | 描述: %s\n\n代码上下文:\n%s\n\n相关文件:\n%s\n\n追踪数据通路，找到断裂点。",
		expCtx.DefectTitle,
		expCtx.DefectDescription,
		expCtx.InitialContext,
		strings.Join(expCtx.RelatedFiles, "\n"),
	)

	var conversation []Message
	conversation = append(conversation, Message{Role: "system", Content: systemPrompt}, Message{Role: "user", Content: userMsg})

	var allFindings []string
	var extraFiles []string
	totalTokens := 0

	for round := 0; round < e.maxRounds; round++ {
		resp, err := e.client.Chat(ctx, &ChatRequest{
			Messages:    conversation,
			Temperature: 0.3,
			MaxTokens:   2048,
		})
		if err != nil {
			logger.Errorf("[CodeExplorer] LLM call failed at round %d: %v", round, err)
			break
		}

		if len(resp.Choices) == 0 {
			break
		}

		assistantMsg := resp.Choices[0].Message.Content
		totalTokens += resp.Usage.TotalTokens
		if totalTokens > e.maxTotalTokens {
			logger.Infof("[CodeExplorer] Token budget exceeded (%d/%d), stopping", totalTokens, e.maxTotalTokens)
			break
		}
		conversation = append(conversation, Message{Role: "assistant", Content: assistantMsg})

		logger.Infof("[CodeExplorer] Round %d response (first 500 chars): %s", round, truncateStr(assistantMsg, 500))

		toolName, toolArgs, findings := e.parseResponse(assistantMsg)

		if findings != nil {
			for _, f := range findings {
				if f.FilePath != "" && f.Evidence != "" {
					allFindings = append(allFindings, fmt.Sprintf("- **%s** (%s): %s", f.FilePath, f.Severity, f.Evidence))
					extraFiles = append(extraFiles, f.FilePath)
				}
			}
			if summary := e.extractDataPathSummary(assistantMsg); summary != "" {
				allFindings = append(allFindings, fmt.Sprintf("\n**数据通路分析**: %s", summary))
			}
			break
		}

		if toolName == "" {
			logger.Infof("[CodeExplorer] No tool_call or findings in round %d, attempting fallback extraction", round)
			toolName, toolArgs = e.fallbackExtractToolCall(assistantMsg)
			if toolName == "" {
				conversation = append(conversation, Message{Role: "user", Content: `Please respond with a JSON block containing either a "tool_call" or "findings". Example: {"thinking":"...","tool_call":{"name":"search_code","arguments":{"query":"..."}}}`})
				continue
			}
		}

		if _, exists := e.tools[toolName]; !exists {
			conversation = append(conversation, Message{Role: "user", Content: fmt.Sprintf(`{"error": "unknown tool: %s, available tools: %s"}`, toolName, e.availableToolNames())})
			continue
		}

		toolResult := e.executeTool(ctx, expCtx, toolName, toolArgs)

		result.ToolCalls++
		logger.Infof("[CodeExplorer] Tool call: %s(%v), result length: %d", toolName, toolArgs, len(toolResult))
		conversation = append(conversation, Message{Role: "user", Content: fmt.Sprintf("Tool %s result:\n%s", toolName, toolResult)})
	}

	if len(allFindings) > 0 {
		result.EnrichedContext = "## Code Explorer 跨栈追踪发现\n\n" + strings.Join(allFindings, "\n")
	}
	result.ExtraFiles = uniqueStrings(extraFiles)
	result.TokensUsed = totalTokens

	logger.Infof("[CodeExplorer] Completed in %v, %d tool calls, %d tokens, %d findings",
		time.Since(startTime), result.ToolCalls, result.TokensUsed, len(allFindings))

	return result, nil
}

type explorerFinding struct {
	FilePath  string
	Evidence  string
	Severity  string
}

func (e *CodeExplorer) parseResponse(msg string) (string, map[string]interface{}, []explorerFinding) {
	jsonStr := extractJSON(msg)
	if jsonStr == "" {
		return "", nil, nil
	}

	var parsed map[string]interface{}
	if err := json.Unmarshal([]byte(jsonStr), &parsed); err != nil {
		logger.Errorf("[CodeExplorer] JSON parse error: %v", err)
		return "", nil, nil
	}

	if findingsRaw, ok := parsed["findings"]; ok {
		var findings []explorerFinding
		if fl, ok := findingsRaw.([]interface{}); ok {
			for _, f := range fl {
				if fm, ok := f.(map[string]interface{}); ok {
					fp, _ := fm["file_path"].(string)
					ev, _ := fm["evidence"].(string)
					sev, _ := fm["severity"].(string)
					findings = append(findings, explorerFinding{FilePath: fp, Evidence: ev, Severity: sev})
				}
			}
		}
		if len(findings) > 0 {
			return "", nil, findings
		}
	}

	toolCall, ok := parsed["tool_call"].(map[string]interface{})
	if !ok {
		return "", nil, nil
	}

	name, _ := toolCall["name"].(string)
	args, _ := toolCall["arguments"].(map[string]interface{})
	return name, args, nil
}

func (e *CodeExplorer) fallbackExtractToolCall(msg string) (string, map[string]interface{}) {
	patterns := []struct {
		regex  *regexp.Regexp
		parser func(matches []string) (string, map[string]interface{})
	}{
		{
			regexp.MustCompile(`(?i)(?:call|use|invoke)\s+(?:tool\s+)?(\w+)\s+(?:with|for|on|to)\s+(?:query|file|symbol|api|path)["\s]*(\S+)`),
			func(m []string) (string, map[string]interface{}) {
				toolName := m[1]
				arg := strings.Trim(m[2], `"'`)
				args := map[string]interface{}{}
				switch toolName {
				case "search_code":
					args["query"] = arg
				case "read_file":
					args["file_path"] = arg
				case "trace_call":
					args["symbol_id"] = arg
				case "find_api_handler":
					args["api_path"] = arg
				}
				return toolName, args
			},
		},
		{
			regexp.MustCompile(`(?i)read\s+(?:the\s+)?file\s+["'` + "`" + `](\S+)["'` + "`" + `]`),
			func(m []string) (string, map[string]interface{}) {
				return "read_file", map[string]interface{}{"file_path": strings.Trim(m[1], `"'`)}
			},
		},
		{
			regexp.MustCompile(`(?i)search\s+(?:for\s+)?["'` + "`" + `](.+?)["'` + "`" + `]`),
			func(m []string) (string, map[string]interface{}) {
				return "search_code", map[string]interface{}{"query": strings.Trim(m[1], `"'`)}
			},
		},
	}

	for _, p := range patterns {
		if matches := p.regex.FindStringSubmatch(msg); len(matches) > 1 {
			name, args := p.parser(matches)
			if _, exists := e.tools[name]; exists && len(args) > 0 {
				logger.Infof("[CodeExplorer] Fallback extracted: %s(%v)", name, args)
				return name, args
			}
		}
	}

	return "", nil
}

func (e *CodeExplorer) extractDataPathSummary(msg string) string {
	re := regexp.MustCompile(`"data_path_summary"\s*:\s*"((?:[^"\\]|\\.)*)"`)
	matches := re.FindStringSubmatch(msg)
	if len(matches) > 1 {
		return strings.ReplaceAll(matches[1], `\"`, `"`)
	}
	return ""
}

func (e *CodeExplorer) availableToolNames() string {
	names := make([]string, 0, len(e.tools))
	for name := range e.tools {
		names = append(names, name)
	}
	return strings.Join(names, ", ")
}

func (e *CodeExplorer) executeTool(ctx context.Context, expCtx ExplorerContext, toolName string, toolArgs map[string]interface{}) string {
	switch toolName {
	case "search_code":
		query, _ := toolArgs["query"].(string)
		if expCtx.SearchFn != nil {
			hits, err := expCtx.SearchFn(ctx, query)
			if err != nil {
				return fmt.Sprintf(`{"error": "%v"}`, err)
			}
			resultJSON, merr := json.Marshal(hits)
			if merr != nil {
				return fmt.Sprintf(`{"error": "marshal failed: %v"}`, merr)
			}
			return string(resultJSON)
		}
		return `{"error": "search not available"}`

	case "read_file":
		filePath, _ := toolArgs["file_path"].(string)
		if expCtx.ReadFn != nil {
			content, err := expCtx.ReadFn(ctx, filePath)
			if err != nil {
				return fmt.Sprintf(`{"error": "cannot read %s: %v"}`, filePath, err)
			}
			return fmt.Sprintf(`{"file_path": "%s", "content": %s}`, filePath, mustJSON(content))
		}
		return `{"error": "file reading not available"}`

	case "trace_call":
		symbolID, _ := toolArgs["symbol_id"].(string)
		direction, _ := toolArgs["direction"].(string)
		if expCtx.TraceFn != nil {
			hits, err := expCtx.TraceFn(ctx, symbolID, direction)
			if err != nil {
				return fmt.Sprintf(`{"error": "%v"}`, err)
			}
			resultJSON, merr := json.Marshal(hits)
			if merr != nil {
				return fmt.Sprintf(`{"error": "marshal failed: %v"}`, merr)
			}
			return string(resultJSON)
		}
		return `{"error": "trace not available"}`

	case "find_api_handler":
		apiPath, _ := toolArgs["api_path"].(string)
		httpMethod, _ := toolArgs["http_method"].(string)
		if expCtx.HandlerFn != nil {
			hits, err := expCtx.HandlerFn(ctx, apiPath, httpMethod)
			if err != nil {
				return fmt.Sprintf(`{"error": "%v"}`, err)
			}
			resultJSON, merr := json.Marshal(hits)
			if merr != nil {
				return fmt.Sprintf(`{"error": "marshal failed: %v"}`, merr)
			}
			return string(resultJSON)
		}
		return `{"error": "handler lookup not available"}`
	}

	return `{"error": "unknown tool"}`
}

func truncateStr(s string, maxLen int) string {
	runes := []rune(s)
	if len(runes) <= maxLen {
		return s
	}
	return string(runes[:maxLen]) + "..."
}

func extractJSON(s string) string {
	if idx := strings.Index(s, "```json"); idx >= 0 {
		start := idx + 7
		end := strings.Index(s[start:], "```")
		if end > 0 {
			return strings.TrimSpace(s[start : start+end])
		}
	}
	if idx := strings.Index(s, "```"); idx >= 0 {
		start := idx + 3
		end := strings.Index(s[start:], "```")
		if end > 0 {
			candidate := strings.TrimSpace(s[start : start+end])
			if strings.HasPrefix(candidate, "{") {
				return candidate
			}
		}
	}
	start := strings.Index(s, "{")
	end := strings.LastIndex(s, "}")
	if start >= 0 && end > start {
		return s[start : end+1]
	}
	return s
}

func mustJSON(v string) string {
	b, err := json.Marshal(v)
	if err != nil {
		return `""`
	}
	return string(b)
}

func uniqueStrings(ss []string) []string {
	seen := make(map[string]bool)
	result := make([]string, 0, len(ss))
	for _, s := range ss {
		if !seen[s] {
			seen[s] = true
			result = append(result, s)
		}
	}
	return result
}
