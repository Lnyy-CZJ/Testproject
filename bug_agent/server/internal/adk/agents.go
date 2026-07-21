package adk

import (
	"context"
	"fmt"
	"sync"

	"bug-agent/internal/adk/tools"
	"bug-agent/internal/ai"

	"google.golang.org/adk/agent"
	"google.golang.org/adk/agent/llmagent"
	adkmodel "google.golang.org/adk/model"
	"google.golang.org/adk/tool"
	"google.golang.org/genai"
)

var baseSystemPrompt = `你是BugAgent平台的缺陷分析引擎。只输出结构化JSON，禁止输出JSON以外的文字。
约束：
1. rootCause：≤2句话，直指根因，不重复描述
2. affectedScope：≤1句话
3. steps[].action：≤1句话，只说改什么、怎么改
4. steps[].code：只包含变更部分，不要贴整个文件
5. affectedFiles：只列真实存在的文件路径，不确定则返回空数组
6. solution.steps[] 必须是文件级修复步骤；可自动修复的步骤必须包含 filePath
7. 多仓库缺陷必须在步骤中填写 repoHint，或把 affectedFiles 写成 仓库名/文件路径
8. 不做推测：没有代码证据的结论不要写
9. 你必须基于用户消息中的「代码证据」和「相关文件」来分析，在 affectedFiles 中引用真实文件路径
10. 如果代码证据充分，在 steps[].filePath、references[].path 中标注具体文件路径和行号
11. 没有代码证据时，只基于缺陷描述做合理性分析，affectedFiles 返回空数组`

var (
	promptEngine     *PromptTemplateEngine
	promptEngineOnce sync.Once
)

func getPromptEngine() *PromptTemplateEngine {
	promptEngineOnce.Do(func() {
		promptEngine = DefaultPromptTemplates()
	})
	return promptEngine
}

func buildInstructionRaw(agentType string) string {
	var instruction string

	switch agentType {
	case "frontend":
		instruction = fmt.Sprintf(`%s

分析前端缺陷。重点关注：
- React组件状态管理、Props传递
- API请求/响应格式不匹配
- CSS/样式问题
- 浏览器兼容性

输出JSON：
{
  "rootCause": "≤2句",
  "affectedFiles": ["path"],
  "affectedScope": "≤1句",
  "riskLevel": "high|medium|low",
  "solution": {
    "description": "≤1句",
    "steps": [{ "step": 1, "action": "≤1句", "filePath": "真实路径", "repoHint": "仓库名，可选", "code": "仅变更部分" }],
    "estimatedEffort": "低|中|高",
    "dependencies": ["dep"]
  },
  "references": [{ "type": "code|doc|test", "path": "", "line": 0, "description": "" }]
}`, baseSystemPrompt)

	case "backend":
		instruction = fmt.Sprintf(`%s

分析后端缺陷。重点关注：
- API接口参数/返回值不匹配
- 数据库查询/事务问题
- 并发安全
- 错误处理缺失

输出JSON：
{
  "rootCause": "≤2句",
  "affectedFiles": ["path"],
  "affectedScope": "≤1句",
  "riskLevel": "high|medium|low",
  "solution": {
    "description": "≤1句",
    "steps": [{ "step": 1, "action": "≤1句", "filePath": "真实路径", "repoHint": "仓库名，可选", "code": "仅变更部分" }],
    "estimatedEffort": "低|中|高",
    "dependencies": ["dep"]
  }
}`, baseSystemPrompt)

	case "ui":
		instruction = fmt.Sprintf(`%s

分析UI/交互缺陷。重点关注：
- CSS布局/响应式问题
- 交互逻辑错误
- 无障碍访问
- 截图对比

输出JSON：
{
  "rootCause": "≤2句",
  "affectedFiles": ["path"],
  "affectedScope": "≤1句",
  "riskLevel": "high|medium|low",
  "solution": {
    "description": "≤1句",
    "steps": [{ "step": 1, "action": "≤1句", "filePath": "真实路径", "repoHint": "仓库名，可选", "code": "仅变更CSS/HTML" }],
    "estimatedEffort": "低|中|高"
  }
}`, baseSystemPrompt)

	case "test":
		instruction = fmt.Sprintf(`%s

分析测试相关缺陷。重点关注：
- 测试覆盖不足
- 测试数据问题
- Mock/Stub配置错误
- 集成测试环境差异

输出JSON：
{
  "rootCause": "≤2句",
  "affectedFiles": ["path"],
  "affectedScope": "≤1句",
  "riskLevel": "high|medium|low",
  "solution": {
    "description": "≤1句",
    "steps": [{ "step": 1, "action": "≤1句", "filePath": "真实路径", "repoHint": "仓库名，可选", "code": "仅变更部分" }],
    "estimatedEffort": "低|中|高"
  }
}`, baseSystemPrompt)

	case "client":
		instruction = fmt.Sprintf(`%s

分析客户端缺陷。重点关注：
- 客户端SDK集成问题
- 平台兼容性
- 网络请求/重试逻辑
- 本地存储/缓存

输出JSON：
{
  "rootCause": "≤2句",
  "affectedFiles": ["path"],
  "affectedScope": "≤1句",
  "riskLevel": "high|medium|low",
  "solution": {
    "description": "≤1句",
    "steps": [{ "step": 1, "action": "≤1句", "filePath": "真实路径", "repoHint": "仓库名，可选", "code": "仅变更部分" }],
    "estimatedEffort": "低|中|高"
  }
}`, baseSystemPrompt)

	default:
		instruction = fmt.Sprintf(`%s

分析缺陷。输出JSON：
{
  "rootCause": "≤2句",
  "affectedFiles": ["path"],
  "affectedScope": "≤1句",
  "riskLevel": "high|medium|low",
  "solution": {
    "description": "≤1句",
    "steps": [{ "step": 1, "action": "≤1句", "filePath": "真实路径", "repoHint": "仓库名，可选", "code": "仅变更部分" }],
    "estimatedEffort": "低|中|高"
  }
}`, baseSystemPrompt)
	}

	return instruction
}

func buildInstruction(agentType string, memoryCtx string) string {
	tmplName := "analysis_" + agentType
	engine := getPromptEngine()
	if rendered, err := engine.Render(tmplName, map[string]interface{}{
		"MemoryCtx": memoryCtx,
	}); err == nil && rendered != "" {
		return rendered
	}

	instruction := buildInstructionRaw(agentType)

	if memoryCtx != "" {
		instruction += fmt.Sprintf("\n\n## 历史记忆\n%s", memoryCtx)
	}

	return instruction
}

func maxTurnsBeforeModelCallback(maxTurns int) llmagent.BeforeModelCallback {
	counter := 0
	return func(ctx agent.CallbackContext, llmRequest *adkmodel.LLMRequest) (*adkmodel.LLMResponse, error) {
		counter++
		if counter > maxTurns {
			return &adkmodel.LLMResponse{
				Content: &genai.Content{
					Role: genai.RoleModel,
					Parts: []*genai.Part{{
						Text: "分析步数已达上限，请基于已有信息输出分析结果。",
					}},
				},
			}, nil
		}
		return nil, nil
	}
}

func NewAnalysisAgent(agentType string, llm adkmodel.LLM, agentTools []tool.Tool, memoryCtx string, callbacks ...Callback) (agent.Agent, error) {
	cfg := llmagent.Config{
		Name:        agentType + "_analyzer",
		Model:       llm,
		Description: fmt.Sprintf("分析%s类型的缺陷", agentType),
		Instruction: buildInstruction(agentType, memoryCtx),
		Tools:       agentTools,
	}
	cfg.BeforeModelCallbacks = append(cfg.BeforeModelCallbacks, maxTurnsBeforeModelCallback(8))
	for _, cb := range callbacks {
		if cb.BeforeModel != nil {
			cfg.BeforeModelCallbacks = append(cfg.BeforeModelCallbacks, cb.BeforeModel)
		}
		if cb.AfterModel != nil {
			cfg.AfterModelCallbacks = append(cfg.AfterModelCallbacks, cb.AfterModel)
		}
		if cb.BeforeTool != nil {
			cfg.BeforeToolCallbacks = append(cfg.BeforeToolCallbacks, cb.BeforeTool)
		}
		if cb.AfterTool != nil {
			cfg.AfterToolCallbacks = append(cfg.AfterToolCallbacks, cb.AfterTool)
		}
	}
	return llmagent.New(cfg)
}

type Callback struct {
	BeforeModel llmagent.BeforeModelCallback
	AfterModel  llmagent.AfterModelCallback
	BeforeTool  llmagent.BeforeToolCallback
	AfterTool   llmagent.AfterToolCallback
}

type ExplorerContext struct {
	Repository RepositoryContext
	SearchFn   func(ctx interface{}, query string) ([]ai.SearchHit, error)
	ReadFn     func(ctx interface{}, filePath string) (string, error)
	TraceFn    func(ctx interface{}, symbolID, direction string) ([]ai.TraceHit, error)
	HandlerFn  func(ctx interface{}, apiPath, httpMethod string) ([]ai.HandlerHit, error)
	ListFn     func(ctx interface{}, path string) ([]ai.DirEntry, error)
}

type RepositoryContext struct {
	RepoName   string
	RepoURL    string
	BranchName string
}

func NewExplorerAgent(llm adkmodel.LLM, expCtx ExplorerContext) (agent.Agent, error) {
	var agentTools []tool.Tool

	if expCtx.SearchFn != nil {
		t, err := tools.NewSearchCodeTool(func(ctx context.Context, query string) ([]ai.SearchHit, error) {
			return expCtx.SearchFn(ctx, query)
		})
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}

	if expCtx.ReadFn != nil {
		t, err := tools.NewReadFileTool(func(ctx context.Context, filePath string) (string, error) {
			return expCtx.ReadFn(ctx, filePath)
		})
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}

	if expCtx.TraceFn != nil {
		t, err := tools.NewTraceCallTool(func(ctx context.Context, symbolID, direction string) ([]ai.TraceHit, error) {
			return expCtx.TraceFn(ctx, symbolID, direction)
		})
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}

	if expCtx.HandlerFn != nil {
		t, err := tools.NewFindAPIHandlerTool(func(ctx context.Context, apiPath, httpMethod string) ([]ai.HandlerHit, error) {
			return expCtx.HandlerFn(ctx, apiPath, httpMethod)
		})
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}

	if expCtx.ListFn != nil {
		t, err := tools.NewListDirectoryTool(func(ctx context.Context, path string) ([]tools.DirEntry, error) {
			entries, err := expCtx.ListFn(ctx, path)
			if err != nil {
				return nil, err
			}
			result := make([]tools.DirEntry, len(entries))
			for i, e := range entries {
				result[i] = tools.DirEntry{Name: e.Name, Type: e.Type}
			}
			return result, nil
		})
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}

	return llmagent.New(llmagent.Config{
		Name:        "code_explorer",
		Model:       llm,
		Description: "跨栈代码探索Agent，追踪数据通路断裂点",
		Instruction: explorerSystemPrompt,
		Tools:       agentTools,
		BeforeModelCallbacks: []llmagent.BeforeModelCallback{
			maxTurnsBeforeModelCallback(10),
		},
	})
}

var explorerSystemPrompt = `探索代码仓库，定位与缺陷相关的代码路径。

工作流：
1. 用 search_code 搜索与缺陷关键词相关的文件
2. 用 read_file 读取相关源码
3. 用 trace_call 追踪调用链
4. 用 find_api_handler 定位API处理函数
5. 找出代码中的断裂点或异常

约束：
- 必须调用工具读代码，不要猜测
- 每次调用一个工具，根据结果决定下一步
- 完成探索后，输出最终分析结果

最终输出格式：
` + "```" + `json
{"thinking":"...","findings":[{"file_path":"...","evidence":"...","severity":"critical|high|medium"}],"data_path_summary":"前端→API→后端→响应→前端状态→UI，断裂点在..."}
` + "```" + `

- findings.evidence ≤2句话`
