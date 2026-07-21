package adk

import (
	"fmt"
	"os/exec"
	"path/filepath"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"google.golang.org/adk/agent"
	"google.golang.org/adk/agent/llmagent"
	adkmodel "google.golang.org/adk/model"
	"google.golang.org/adk/tool"
	"google.golang.org/adk/tool/mcptoolset"
)

type MCPServerConfig struct {
	Command string
	Args    []string
}

var allowedMCPCommands = map[string]bool{
	"mcp-server":    true,
	"mcp":           true,
}

func RegisterMCPTools(mcpServers []MCPServerConfig) {
	if len(mcpServers) == 0 {
		return
	}
	DefaultToolRegistry().InvalidateCache()
}

func IsAllowedMCPCommand(cmd string) bool {
	baseCmd := filepath.Base(cmd)
	return allowedMCPCommands[baseCmd]
}

func NewMCPToolset(serverCmd string, args ...string) (tool.Toolset, error) {
	baseCmd := filepath.Base(serverCmd)
	if !allowedMCPCommands[baseCmd] {
		return nil, fmt.Errorf("MCP command not allowed: %s", baseCmd)
	}
	return mcptoolset.New(mcptoolset.Config{
		Transport: &mcp.CommandTransport{Command: exec.Command(serverCmd, args...)},
	})
}

func NewExplorerAgentWithMCP(llm adkmodel.LLM, expCtx ExplorerContext, mcpServers []MCPServerConfig) (agent.Agent, error) {
	var agentTools []tool.Tool
	var toolsets []tool.Toolset

	if expCtx.SearchFn != nil {
		t, err := NewSearchCodeToolAdapted(expCtx)
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}

	if expCtx.ReadFn != nil {
		t, err := NewReadFileToolAdapted(expCtx)
		if err == nil {
			agentTools = append(agentTools, t)
		}
	}

	for _, srv := range mcpServers {
		ts, err := NewMCPToolset(srv.Command, srv.Args...)
		if err != nil {
			return nil, fmt.Errorf("NewMCPToolset(%s): %w", srv.Command, err)
		}
		toolsets = append(toolsets, ts)
	}

	return llmagent.New(llmagent.Config{
		Name:        "code_explorer_mcp",
		Model:       llm,
		Instruction: explorerSystemPrompt,
		Tools:       agentTools,
		Toolsets:    toolsets,
		Description: "跨栈代码探索Agent（含MCP工具），追踪数据通路断裂点",
	})
}
