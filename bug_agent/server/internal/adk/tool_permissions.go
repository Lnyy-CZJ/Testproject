package adk

import (
	"fmt"
	"sync"

	"google.golang.org/adk/agent/llmagent"
	"google.golang.org/adk/tool"
)

type ToolPermission int

const (
	PermissionRead ToolPermission = iota
	PermissionWrite
	PermissionExecute
	PermissionAdmin
)

type ToolPermissionRule struct {
	ToolName      string
	AgentTypes    map[string]bool
	MinPermission ToolPermission
}

type ToolPermissionMatrix struct {
	rules map[string]*ToolPermissionRule
	mu    sync.RWMutex
}

func NewToolPermissionMatrix() *ToolPermissionMatrix {
	return &ToolPermissionMatrix{
		rules: make(map[string]*ToolPermissionRule),
	}
}

func (m *ToolPermissionMatrix) AddRule(toolName string, agentTypes []string, minPerm ToolPermission) {
	m.mu.Lock()
	defer m.mu.Unlock()
	types := make(map[string]bool, len(agentTypes))
	for _, t := range agentTypes {
		types[t] = true
	}
	m.rules[toolName] = &ToolPermissionRule{
		ToolName:      toolName,
		AgentTypes:    types,
		MinPermission: minPerm,
	}
}

func (m *ToolPermissionMatrix) IsAllowed(toolName, agentType string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	rule, ok := m.rules[toolName]
	if !ok {
		return false
	}
	if len(rule.AgentTypes) == 0 {
		return true
	}
	return rule.AgentTypes[agentType]
}

func ToolPermissionBeforeToolCallback(matrix *ToolPermissionMatrix, agentType string) llmagent.BeforeToolCallback {
	gate := NewSafetyGate()
	return func(ctx tool.Context, t tool.Tool, args map[string]interface{}) (map[string]interface{}, error) {
		if !matrix.IsAllowed(t.Name(), agentType) {
			return nil, fmt.Errorf("tool %s not allowed for agent type %s", t.Name(), agentType)
		}
		decision := gate.Assess(ToolCall{Name: t.Name(), Args: args})
		if decision == Reject {
			return nil, fmt.Errorf("tool %s rejected by safety gate", t.Name())
		}
		return nil, nil
	}
}

func DefaultToolPermissionMatrix() *ToolPermissionMatrix {
	m := NewToolPermissionMatrix()
	m.AddRule("search_code", nil, PermissionRead)
	m.AddRule("read_file", nil, PermissionRead)
	m.AddRule("trace_call", nil, PermissionRead)
	m.AddRule("find_api_handler", nil, PermissionRead)
	m.AddRule("list_directory", nil, PermissionRead)
	m.AddRule("git_ops", []string{"backend", "frontend"}, PermissionRead)
	m.AddRule("run_test", []string{"test", "backend"}, PermissionExecute)
	m.AddRule("db_query", []string{"backend"}, PermissionRead)
	return m
}
