package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"

	"bug-agent/internal/ai"

	"google.golang.org/adk/tool"
	"google.golang.org/adk/tool/functiontool"
)

var (
	sqlLineCommentRe  = regexp.MustCompile(`(?i)--[^\n]*`)
	sqlBlockCommentRe = regexp.MustCompile(`(?i)/\*.*?\*/`)
)

// stripSQLComments removes SQL line comments (--) and block comments (/* */) from the input.
func stripSQLComments(sql string) string {
	sql = sqlBlockCommentRe.ReplaceAllString(sql, " ")
	sql = sqlLineCommentRe.ReplaceAllString(sql, " ")
	return sql
}

type SearchCodeArgs struct {
	Query string `json:"query" jsonschema:"description=语义搜索查询,required"`
}

type SearchCodeResult struct {
	Hits []SearchHitResult `json:"hits"`
}

type SearchHitResult struct {
	FilePath string `json:"filePath"`
	SymbolID string `json:"symbolId"`
	Line     int    `json:"line"`
	Snippet  string `json:"snippet"`
}

func NewSearchCodeTool(searchFn func(ctx context.Context, query string) ([]ai.SearchHit, error)) (tool.Tool, error) {
	return functiontool.New(
		functiontool.Config{
			Name:        "search_code",
			Description: "语义搜索代码符号，返回匹配的文件路径、符号名和行号",
		},
		func(ctx tool.Context, args SearchCodeArgs) (SearchCodeResult, error) {
			hits, err := searchFn(ctx, args.Query)
			if err != nil {
				return SearchCodeResult{}, fmt.Errorf("search_code: %w", err)
			}
			results := make([]SearchHitResult, len(hits))
			for i, h := range hits {
				results[i] = SearchHitResult{
					FilePath: h.FilePath,
					SymbolID: h.SymbolID,
					Line:     h.Line,
					Snippet:  h.Snippet,
				}
			}
			return SearchCodeResult{Hits: results}, nil
		},
	)
}

type ReadFileArgs struct {
	FilePath string `json:"filePath" jsonschema:"description=相对于仓库根目录的文件路径,required"`
}

type ReadFileResult struct {
	FilePath string `json:"filePath"`
	Content  string `json:"content"`
}

func NewReadFileTool(readFn func(ctx context.Context, filePath string) (string, error)) (tool.Tool, error) {
	return functiontool.New(
		functiontool.Config{
			Name:        "read_file",
			Description: "读取仓库中文件的内容，返回带行号的完整文件内容",
		},
		func(ctx tool.Context, args ReadFileArgs) (ReadFileResult, error) {
			if strings.Contains(args.FilePath, "..") || strings.HasPrefix(args.FilePath, "/") {
				return ReadFileResult{}, fmt.Errorf("read_file: path traversal not allowed")
			}
			content, err := readFn(ctx, args.FilePath)
			if err != nil {
				return ReadFileResult{}, fmt.Errorf("read_file(%s): %w", args.FilePath, err)
			}
			return ReadFileResult{FilePath: args.FilePath, Content: content}, nil
		},
	)
}

type TraceCallArgs struct {
	SymbolID  string `json:"symbolId" jsonschema:"description=符号ID，格式 path/to/file.go::StructName.methodName,required"`
	Direction string `json:"direction" jsonschema:"description=追踪方向: up(谁调用它) 或 down(它调用谁),required"`
}

type TraceCallResult struct {
	Hits []TraceHitResult `json:"hits"`
}

type TraceHitResult struct {
	SymbolID string `json:"symbolId"`
	Document string `json:"document"`
	FilePath string `json:"filePath"`
}

func NewTraceCallTool(traceFn func(ctx context.Context, symbolID, direction string) ([]ai.TraceHit, error)) (tool.Tool, error) {
	return functiontool.New(
		functiontool.Config{
			Name:        "trace_call",
			Description: "追踪符号的调用图，支持上游(谁调用它)和下游(它调用谁)方向，用于跨文件数据流追踪",
		},
		func(ctx tool.Context, args TraceCallArgs) (TraceCallResult, error) {
			hits, err := traceFn(ctx, args.SymbolID, args.Direction)
			if err != nil {
				return TraceCallResult{}, fmt.Errorf("trace_call: %w", err)
			}
			results := make([]TraceHitResult, len(hits))
			for i, h := range hits {
				results[i] = TraceHitResult{
					SymbolID: h.SymbolID,
					Document: h.Document,
					FilePath: h.FilePath,
				}
			}
			return TraceCallResult{Hits: results}, nil
		},
	)
}

type FindAPIHandlerArgs struct {
	APIPath    string `json:"apiPath" jsonschema:"description=前端API路径(如 /audit-logs, /defects/:id),required"`
	HTTPMethod string `json:"httpMethod" jsonschema:"description=HTTP方法: GET, POST, PUT, DELETE,required"`
}

type FindAPIHandlerResult struct {
	Hits []HandlerHitResult `json:"hits"`
}

type HandlerHitResult struct {
	FilePath   string `json:"filePath"`
	FuncName   string `json:"funcName"`
	LineNumber int    `json:"lineNumber"`
}

func NewFindAPIHandlerTool(handlerFn func(ctx context.Context, apiPath, httpMethod string) ([]ai.HandlerHit, error)) (tool.Tool, error) {
	return functiontool.New(
		functiontool.Config{
			Name:        "find_api_handler",
			Description: "根据前端API调用路径找到后端处理函数，返回handler文件路径和函数名",
		},
		func(ctx tool.Context, args FindAPIHandlerArgs) (FindAPIHandlerResult, error) {
			hits, err := handlerFn(ctx, args.APIPath, args.HTTPMethod)
			if err != nil {
				return FindAPIHandlerResult{}, fmt.Errorf("find_api_handler: %w", err)
			}
			results := make([]HandlerHitResult, len(hits))
			for i, h := range hits {
				results[i] = HandlerHitResult{
					FilePath:   h.FilePath,
					FuncName:   h.FuncName,
					LineNumber: h.LineNumber,
				}
			}
			return FindAPIHandlerResult{Hits: results}, nil
		},
	)
}

type GitOpsArgs struct {
	Operation string `json:"operation" jsonschema:"description=Git操作: diff, log, blame,required"`
	FilePath  string `json:"filePath" jsonschema:"description=文件路径(相对仓库根目录)"`
	Revision  string `json:"revision" jsonschema:"description=Git修订版本(分支名/commit hash)"`
}

type GitOpsResult struct {
	Output string `json:"output"`
}

func NewGitOpsTool(gitFn func(ctx context.Context, operation, filePath, revision string) (string, error)) (tool.Tool, error) {
	return functiontool.New(
		functiontool.Config{
			Name:        "git_ops",
			Description: "执行Git操作：diff(查看变更)、log(查看提交历史)、blame(查看行级作者)",
		},
		func(ctx tool.Context, args GitOpsArgs) (GitOpsResult, error) {
			allowedOps := map[string]bool{"diff": true, "log": true, "blame": true}
			if !allowedOps[args.Operation] {
				return GitOpsResult{}, fmt.Errorf("git_ops: operation %q not allowed, permitted: diff, log, blame", args.Operation)
			}
			if strings.Contains(args.FilePath, "..") || strings.HasPrefix(args.FilePath, "/") {
				return GitOpsResult{}, fmt.Errorf("git_ops: path traversal not allowed")
			}
			output, err := gitFn(ctx, args.Operation, args.FilePath, args.Revision)
			if err != nil {
				return GitOpsResult{}, fmt.Errorf("git_ops(%s): %w", args.Operation, err)
			}
			return GitOpsResult{Output: output}, nil
		},
	)
}

type ListDirectoryArgs struct {
	Path string `json:"path" jsonschema:"description=目录路径(相对仓库根目录),required"`
}

type ListDirectoryResult struct {
	Entries []DirEntry `json:"entries"`
}

type DirEntry struct {
	Name string `json:"name"`
	Type string `json:"type"`
}

func NewListDirectoryTool(listFn func(ctx context.Context, path string) ([]DirEntry, error)) (tool.Tool, error) {
	return functiontool.New(
		functiontool.Config{
			Name:        "list_directory",
			Description: "列出仓库中指定目录下的文件和子目录",
		},
		func(ctx tool.Context, args ListDirectoryArgs) (ListDirectoryResult, error) {
			if strings.Contains(args.Path, "..") || strings.HasPrefix(args.Path, "/") {
				return ListDirectoryResult{}, fmt.Errorf("list_directory: path traversal not allowed")
			}
			entries, err := listFn(ctx, args.Path)
			if err != nil {
				return ListDirectoryResult{}, fmt.Errorf("list_directory(%s): %w", args.Path, err)
			}
			return ListDirectoryResult{Entries: entries}, nil
		},
	)
}

type RunTestArgs struct {
	TestPath string `json:"testPath" jsonschema:"description=测试文件路径或Go包路径,required"`
	Args     string `json:"args" jsonschema:"description=额外测试参数(如 -run TestName)"`
}

type RunTestResult struct {
	Output   string `json:"output"`
	Pass     bool   `json:"pass"`
	Duration string `json:"duration"`
}

func NewRunTestTool(testFn func(ctx context.Context, testPath, args string) (*RunTestResult, error)) (tool.Tool, error) {
	return functiontool.New(
		functiontool.Config{
			Name:        "run_test",
			Description: "在沙箱中运行测试，返回测试结果和输出",
			IsLongRunning: true,
		},
		func(ctx tool.Context, args RunTestArgs) (RunTestResult, error) {
			result, err := testFn(ctx, args.TestPath, args.Args)
			if err != nil {
				return RunTestResult{}, fmt.Errorf("run_test: %w", err)
			}
			return *result, nil
		},
	)
}

type DBQueryArgs struct {
	Query string `json:"query" jsonschema:"description=只读SQL查询语句(SELECT only),required"`
}

type DBQueryResult struct {
	Rows    string `json:"rows"`
	Count   int    `json:"count"`
	Columns string `json:"columns"`
}

func NewDBQueryTool(queryFn func(ctx context.Context, query string) (*DBQueryResult, error)) (tool.Tool, error) {
	return functiontool.New(
		functiontool.Config{
			Name:        "db_query",
			Description: "执行只读SQL查询(SELECT only)，用于检查数据库状态和数据一致性",
		},
		func(ctx tool.Context, args DBQueryArgs) (DBQueryResult, error) {
			normalized := strings.ToUpper(strings.Map(func(r rune) rune {
				if r == '\t' || r == '\n' || r == '\r' {
					return ' '
				}
				return r
			}, args.Query))
			// Strip SQL comments before keyword checking to prevent bypass
			normalized = stripSQLComments(normalized)
			normalized = strings.TrimSpace(normalized)
			if strings.Contains(args.Query, ";") {
				return DBQueryResult{}, fmt.Errorf("db_query: semicolons are not allowed in queries")
			}
			if !strings.HasPrefix(normalized, "SELECT") {
				return DBQueryResult{}, fmt.Errorf("db_query: only SELECT statements are allowed")
			}
			for _, forbidden := range []string{"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "UNION", "INTO"} {
				if strings.Contains(normalized, forbidden) {
					return DBQueryResult{}, fmt.Errorf("db_query: forbidden keyword %s detected", forbidden)
				}
			}
			result, err := queryFn(ctx, args.Query)
			if err != nil {
				return DBQueryResult{}, fmt.Errorf("db_query: %w", err)
			}
			return *result, nil
		},
	)
}

func toJSON(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return fmt.Sprintf(`{"error":"json marshal: %v"}`, err)
	}
	return string(b)
}
