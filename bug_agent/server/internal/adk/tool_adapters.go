package adk

import (
	"context"
	"fmt"

	"bug-agent/internal/adk/tools"
	"bug-agent/internal/ai"
	"bug-agent/internal/retrieval"

	"google.golang.org/adk/tool"
	"google.golang.org/adk/tool/functiontool"
)

func NewSearchCodeToolAdapted(expCtx ExplorerContext) (tool.Tool, error) {
	return tools.NewSearchCodeTool(func(ctx context.Context, query string) ([]ai.SearchHit, error) {
		return expCtx.SearchFn(ctx, query)
	})
}

func NewReadFileToolAdapted(expCtx ExplorerContext) (tool.Tool, error) {
	return tools.NewReadFileTool(func(ctx context.Context, filePath string) (string, error) {
		return expCtx.ReadFn(ctx, filePath)
	})
}

func NewTraceCallToolAdapted(expCtx ExplorerContext) (tool.Tool, error) {
	return tools.NewTraceCallTool(func(ctx context.Context, symbolID, direction string) ([]ai.TraceHit, error) {
		return expCtx.TraceFn(ctx, symbolID, direction)
	})
}

func NewFindAPIHandlerToolAdapted(expCtx ExplorerContext) (tool.Tool, error) {
	return tools.NewFindAPIHandlerTool(func(ctx context.Context, apiPath, httpMethod string) ([]ai.HandlerHit, error) {
		return expCtx.HandlerFn(ctx, apiPath, httpMethod)
	})
}

func NewListDirectoryToolAdapted(expCtx ExplorerContext) (tool.Tool, error) {
	return tools.NewListDirectoryTool(func(ctx context.Context, path string) ([]tools.DirEntry, error) {
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
}

func NewRetrieverPluginToolAdapted(name string, displayName string, retriever retrieval.Retriever, repoCtx RepositoryContext) (tool.Tool, error) {
	toolName := "retriever_" + name
	return functiontool.New(
		functiontool.Config{
			Name:        toolName,
			Description: displayName,
		},
		func(ctx tool.Context, args tools.SearchCodeArgs) (tools.SearchCodeResult, error) {
			evidences, err := retriever.Retrieve(ctx, retrieval.Query{
				Text:       args.Query,
				TopK:       10,
				RepoName:   repoCtx.RepoName,
				RepoURL:    repoCtx.RepoURL,
				BranchName: repoCtx.BranchName,
			})
			if err != nil {
				return tools.SearchCodeResult{}, fmt.Errorf("retriever plugin %s failed: %w", name, err)
			}
			var results []tools.SearchHitResult
			for _, e := range evidences {
				results = append(results, tools.SearchHitResult{
					FilePath: e.FilePath,
					SymbolID: e.SymbolID,
					Line:     e.Line,
					Snippet:  e.Snippet,
				})
			}
			return tools.SearchCodeResult{Hits: results}, nil
		},
	)
}
