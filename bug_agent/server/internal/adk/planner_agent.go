package adk

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"google.golang.org/adk/agent"
	"google.golang.org/adk/agent/llmagent"
	adkmodel "google.golang.org/adk/model"
)

type PlanStep struct {
	Goal string                 `json:"goal"`
	Tool string                 `json:"tool"`
	Args map[string]interface{} `json:"args"`
}

type PlanOutput struct {
	Steps []PlanStep `json:"steps"`
}

var plannerSystemPrompt = `分析缺陷描述，制定代码探索计划。只输出JSON，不要其他文字。

工作流：
1. 从缺陷描述提取关键实体（API路径、组件名、错误信息、函数名）
2. 为每个实体制定搜索步骤
3. 规划阅读步骤（读取搜索结果中最相关的文件）

输出格式：
` + "```" + `json
{"steps":[{"goal":"找到处理 /api/users 的后端handler","tool":"find_api_handler","args":{"apiPath":"/api/users","httpMethod":"GET"}},{"goal":"阅读handler代码","tool":"read_file","args":{"filePath":"server/internal/handler/user.go"}}]}
` + "```" + `

约束：
- 步骤不超过5步
- 每步只使用一个工具
- tool 只能是 search_code / read_file / find_api_handler / list_directory
- 优先搜索最可能出问题的模块
- args 必须与 tool 匹配：
  - search_code: {"query":"关键词"}
  - read_file: {"filePath":"文件路径"}
  - find_api_handler: {"apiPath":"/api/path","httpMethod":"GET"}
  - list_directory: {"path":"目录路径"}`

func NewPlannerAgent(llm adkmodel.LLM) (agent.Agent, error) {
	cfg := llmagent.Config{
		Name:        "code_planner",
		Model:       llm,
		Instruction: plannerSystemPrompt,
	}
	cfg.BeforeModelCallbacks = append(cfg.BeforeModelCallbacks, maxTurnsBeforeModelCallback(1))
	return llmagent.New(cfg)
}

func ParsePlanOutput(text string) (*PlanOutput, error) {
	start := strings.Index(text, "{")
	end := strings.LastIndex(text, "}")
	if start < 0 || end < 0 || end <= start {
		return nil, fmt.Errorf("no JSON object found in planner output")
	}

	jsonStr := text[start : end+1]
	var plan PlanOutput
	if err := json.Unmarshal([]byte(jsonStr), &plan); err != nil {
		return nil, fmt.Errorf("failed to parse plan JSON: %w", err)
	}

	validTools := map[string]bool{
		"search_code": true, "read_file": true,
		"find_api_handler": true, "list_directory": true,
	}

	var filtered []PlanStep
	for _, step := range plan.Steps {
		if !validTools[step.Tool] {
			continue
		}
		if step.Args == nil {
			step.Args = make(map[string]interface{})
		}
		filtered = append(filtered, step)
	}

	if len(filtered) == 0 {
		return nil, fmt.Errorf("planner produced no valid steps")
	}

	if len(filtered) > 5 {
		filtered = filtered[:5]
	}

	plan.Steps = filtered
	return &plan, nil
}

type ExecResult struct {
	Steps    []ExecStep
	Evidence string
	Files    []string
}

type ExecStep struct {
	Goal   string
	Tool   string
	Args   map[string]interface{}
	Result string
	Error  string
}

func ExecutePlan(ctx context.Context, plan *PlanOutput, expCtx ExplorerContext) (*ExecResult, error) {
	result := &ExecResult{}
	gate := NewSafetyGate()

	for i, step := range plan.Steps {
		select {
		case <-ctx.Done():
			return result, ctx.Err()
		default:
		}

		es := ExecStep{
			Goal: step.Goal,
			Tool: step.Tool,
			Args: step.Args,
		}

		decision := gate.Assess(ToolCall{Name: step.Tool, Args: step.Args})
		if decision == Reject {
			es.Error = fmt.Sprintf("tool %s rejected by safety gate", step.Tool)
			result.Steps = append(result.Steps, es)
			continue
		}

		var output string

		switch step.Tool {
		case "search_code":
			if expCtx.SearchFn == nil {
				es.Error = "search_code: no repository available"
				result.Steps = append(result.Steps, es)
				continue
			}
			query, _ := step.Args["query"].(string)
			if query == "" {
				es.Error = "missing query arg"
				result.Steps = append(result.Steps, es)
				continue
			}
			hits, herr := expCtx.SearchFn(ctx, query)
			if herr != nil {
				es.Error = herr.Error()
			} else {
				var paths []string
				for _, h := range hits {
					paths = append(paths, h.FilePath)
				}
				output = fmt.Sprintf("Found %d files: %s", len(paths), strings.Join(paths, ", "))
				result.Files = append(result.Files, paths...)
			}
		case "read_file":
			if expCtx.ReadFn == nil {
				es.Error = "read_file: no repository available"
				result.Steps = append(result.Steps, es)
				continue
			}
			filePath, _ := step.Args["filePath"].(string)
			if filePath == "" {
				es.Error = "missing filePath arg"
				result.Steps = append(result.Steps, es)
				continue
			}
			content, rerr := expCtx.ReadFn(ctx, filePath)
			if rerr != nil {
				es.Error = rerr.Error()
			} else {
				output = content
				result.Files = appendIfMissing(result.Files, filePath)
			}
		case "find_api_handler":
			if expCtx.HandlerFn == nil {
				es.Error = "find_api_handler: no repository available"
				result.Steps = append(result.Steps, es)
				continue
			}
			apiPath, _ := step.Args["apiPath"].(string)
			httpMethod, _ := step.Args["httpMethod"].(string)
			if apiPath == "" {
				es.Error = "missing apiPath arg"
				result.Steps = append(result.Steps, es)
				continue
			}
			hits, herr := expCtx.HandlerFn(ctx, apiPath, httpMethod)
			if herr != nil {
				es.Error = herr.Error()
			} else {
				var lines []string
				for _, h := range hits {
					lines = append(lines, fmt.Sprintf("%s:%d", h.FilePath, h.LineNumber))
				}
				output = fmt.Sprintf("Found %d handlers: %s", len(lines), strings.Join(lines, ", "))
				for _, h := range hits {
					result.Files = appendIfMissing(result.Files, h.FilePath)
				}
			}
		case "list_directory":
			if expCtx.ListFn == nil {
				es.Error = "list_directory: no repository available"
				result.Steps = append(result.Steps, es)
				continue
			}
			path, _ := step.Args["path"].(string)
			entries, lerr := expCtx.ListFn(ctx, path)
			if lerr != nil {
				es.Error = lerr.Error()
			} else {
				var names []string
				for _, e := range entries {
					names = append(names, fmt.Sprintf("%s (%s)", e.Name, e.Type))
				}
				output = fmt.Sprintf("Directory listing: %s", strings.Join(names, ", "))
			}
		default:
			es.Error = fmt.Sprintf("unknown tool: %s", step.Tool)
		}

		if output != "" {
			es.Result = output
			result.Evidence += fmt.Sprintf("### Step %d: %s\n**Tool**: %s\n**Result**:\n%s\n\n", i+1, step.Goal, step.Tool, truncateString(output, 3000))
		}
		result.Steps = append(result.Steps, es)
	}

	return result, nil
}

func truncateString(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen] + "\n... (truncated)"
}

func appendIfMissing(slice []string, s string) []string {
	for _, v := range slice {
		if v == s {
			return slice
		}
	}
	return append(slice, s)
}
