package adk

import (
	"fmt"

	"google.golang.org/adk/agent/llmagent"
	adkmodel "google.golang.org/adk/model"
	"google.golang.org/adk/runner"
	"google.golang.org/adk/session"
	"google.golang.org/adk/tool"
)

var fixSystemPrompt = `你是BugAgent的代码修复引擎。根据分析报告修复代码。

工作流：
1. 读取分析报告和当前代码
2. 生成修复方案
3. 应用代码变更
4. 验证修复

约束：
1. 只改必要的部分，不重构
2. 保持原有代码风格
3. 只输出变更部分，不要贴整个文件
4. 每次修复只处理一个缺陷
5. 修复后必须验证编译通过

输出JSON：
{
  "fixSummary": "≤2句",
  "changedFiles": [{"path": "...", "change": "描述变更"}],
  "codeChanges": [{"path": "...", "original": "原始代码片段", "fixed": "修复后代码片段"}],
  "verificationSteps": ["验证步骤"],
  "riskAssessment": "low|medium|high",
  "needsReview": true|false
}`

type FixPipelineConfig struct {
	LLM        adkmodel.LLM
	SessionSvc session.Service
	AppName    string
	FixTools   []tool.Tool
	Callbacks  []Callback
}

func NewFixPipeline(cfg FixPipelineConfig) (*runner.Runner, error) {
	fixAgent, err := llmagent.New(llmagent.Config{
		Name:        "fix_generator",
		Model:       cfg.LLM,
		Description: "根据分析报告生成并应用代码修复",
		Instruction: fixSystemPrompt,
		Tools:       cfg.FixTools,
	})
	if err != nil {
		return nil, fmt.Errorf("llmagent.New(fix_generator): %w", err)
	}

	return runner.New(runner.Config{
		AppName:        cfg.AppName,
		Agent:          fixAgent,
		SessionService: cfg.SessionSvc,
	})
}
