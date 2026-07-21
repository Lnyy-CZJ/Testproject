package adk

import (
	"fmt"

	"google.golang.org/adk/agent"
	"google.golang.org/adk/agent/llmagent"
	"google.golang.org/adk/agent/workflowagents/parallelagent"
	adkmodel "google.golang.org/adk/model"
	"google.golang.org/adk/runner"
	"google.golang.org/adk/session"
	"google.golang.org/adk/tool"
)

type CollaborationConfig struct {
	LLM         adkmodel.LLM
	SessionSvc  session.Service
	AppName     string
	AgentTypes  []string
	MemoryCtx   string
	CollabTools []tool.Tool
}

func NewCollaborationPipeline(cfg CollaborationConfig) (*runner.Runner, error) {
	var agents []agent.Agent
	for _, agentType := range cfg.AgentTypes {
		a, err := llmagent.New(llmagent.Config{
			Name:        agentType + "_collaborator",
			Model:       cfg.LLM,
			Description: fmt.Sprintf("协作分析%s类型缺陷", agentType),
			Instruction: buildInstruction(agentType, cfg.MemoryCtx),
			Tools:       cfg.CollabTools,
		})
		if err != nil {
			return nil, fmt.Errorf("llmagent.New(%s_collaborator): %w", agentType, err)
		}
		agents = append(agents, a)
	}

	if len(agents) == 0 {
		return nil, fmt.Errorf("at least one agent type is required")
	}

	var rootAgent agent.Agent
	if len(agents) > 1 {
		pa, err := parallelagent.New(parallelagent.Config{
			AgentConfig: agent.Config{
				Name:      "parallel_collaboration",
				SubAgents: agents,
			},
		})
		if err != nil {
			return nil, fmt.Errorf("parallelagent.New: %w", err)
		}
		rootAgent = pa
	} else {
		rootAgent = agents[0]
	}

	return runner.New(runner.Config{
		AppName:        cfg.AppName,
		Agent:          rootAgent,
		SessionService: cfg.SessionSvc,
	})
}
