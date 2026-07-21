package adk

import (
	"strings"
)

type SafetyDecision int

const (
	AutoApprove SafetyDecision = iota
	AskUser
	Reject
)

type ToolCall struct {
	Name string
	Args map[string]interface{}
}

type SafetyGate struct {
	projectRoot string
}

func NewSafetyGate() *SafetyGate {
	return &SafetyGate{}
}

func NewSafetyGateWithRoot(projectRoot string) *SafetyGate {
	return &SafetyGate{projectRoot: projectRoot}
}

func (g *SafetyGate) Assess(tc ToolCall) SafetyDecision {
	readOnlyTools := map[string]bool{
		"search_code": true, "read_file": true,
		"list_directory": true, "find_api_handler": true,
		"trace_call": true,
	}

	if readOnlyTools[tc.Name] {
		return AutoApprove
	}

	switch tc.Name {
	case "apply_patch":
		if g.projectRoot == "" {
			return AskUser
		}
		filePath, _ := tc.Args["filePath"].(string)
		if filePath == "" {
			return AskUser
		}
		if strings.HasPrefix(filePath, g.projectRoot) || !strings.HasPrefix(filePath, "/") {
			return AutoApprove
		}
		return AskUser
	default:
		return Reject
	}
}
