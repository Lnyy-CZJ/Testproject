package adk

import (
	"fmt"

	"google.golang.org/adk/agent"
	"google.golang.org/adk/agent/workflowagents/parallelagent"
	"google.golang.org/adk/agent/workflowagents/sequentialagent"
	adkmodel "google.golang.org/adk/model"
	"google.golang.org/adk/runner"
	"google.golang.org/adk/session"
	"google.golang.org/adk/tool"
)

type AnalysisPipelineConfig struct {
	LLM         adkmodel.LLM
	SessionSvc  session.Service
	ExplorerCtx ExplorerContext
	MemoryCtx   string
	AgentTypes  []string
	AgentTools  []tool.Tool
	AppName     string
	MCPServers  []MCPServerConfig
	Callbacks   []Callback
}

func NewAnalysisPipeline(cfg AnalysisPipelineConfig) (*runner.Runner, error) {
	var explorer agent.Agent
	var err error
	if len(cfg.MCPServers) > 0 {
		explorer, err = NewExplorerAgentWithMCP(cfg.LLM, cfg.ExplorerCtx, cfg.MCPServers)
		if err != nil {
			return nil, fmt.Errorf("NewExplorerAgentWithMCP: %w", err)
		}
	} else {
		explorer, err = NewExplorerAgent(cfg.LLM, cfg.ExplorerCtx)
		if err != nil {
			return nil, fmt.Errorf("NewExplorerAgent: %w", err)
		}
	}

	var analysisAgents []agent.Agent
	for _, agentType := range cfg.AgentTypes {
		a, err := NewAnalysisAgent(agentType, cfg.LLM, cfg.AgentTools, cfg.MemoryCtx, cfg.Callbacks...)
		if err != nil {
			return nil, fmt.Errorf("NewAnalysisAgent(%s): %w", agentType, err)
		}
		analysisAgents = append(analysisAgents, a)
	}

	var pipeline agent.Agent
	if len(analysisAgents) > 1 {
		parallelAnalysis, err := parallelagent.New(parallelagent.Config{
			AgentConfig: agent.Config{
				Name:      "parallel_analysis",
				SubAgents: analysisAgents,
			},
		})
		if err != nil {
			return nil, fmt.Errorf("parallelagent.New: %w", err)
		}

		pipeline, err = sequentialagent.New(sequentialagent.Config{
			AgentConfig: agent.Config{
				Name:      "analysis_pipeline",
				SubAgents: []agent.Agent{explorer, parallelAnalysis},
			},
		})
		if err != nil {
			return nil, fmt.Errorf("sequentialagent.New: %w", err)
		}
	} else if len(analysisAgents) == 1 {
		pipeline, err = sequentialagent.New(sequentialagent.Config{
			AgentConfig: agent.Config{
				Name:      "analysis_pipeline",
				SubAgents: []agent.Agent{explorer, analysisAgents[0]},
			},
		})
		if err != nil {
			return nil, fmt.Errorf("sequentialagent.New: %w", err)
		}
	} else {
		pipeline = explorer
	}

	return runner.New(runner.Config{
		AppName:        cfg.AppName,
		Agent:          pipeline,
		SessionService: cfg.SessionSvc,
	})
}
