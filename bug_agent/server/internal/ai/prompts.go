package ai

import (
	"fmt"
	"strings"
)

// SystemPrompt 基础系统提示词
var SystemPrompt = "你是BugAgent平台的缺陷分析引擎。只输出结构化JSON，禁止输出任何JSON以外的文字。\n" +
	"约束：\n" +
	"1. rootCause：≤2句话，直指根因，不重复描述\n" +
	"2. affectedScope：≤1句话\n" +
	"3. steps[].action：≤1句话，只说改什么、怎么改\n" +
	"4. steps[].code：只包含变更部分，不要贴整个文件\n" +
	"5. affectedFiles：只列真实存在的文件路径，不确定则返回空数组\n" +
	"6. solution.steps[] 必须是文件级修复步骤；可自动修复的步骤必须包含 filePath\n" +
	"7. 多仓库缺陷必须在步骤中填写 repoHint，或把 affectedFiles 写成 仓库名/文件路径\n" +
	"8. 不做推测：没有代码证据的结论不要写"

// BuildFrontendPrompt 构建前端AGENT分析提示词
func BuildFrontendPrompt(params map[string]interface{}) string {
	prompt := fmt.Sprintf("%s\n\n分析以下前端缺陷：\n\n"+
		"## 缺陷信息\n"+
		"编号: %s | 标题: %s | 描述: %s | 严重级别: %s | 优先级: %s | 类型: %s",
		SystemPrompt,
		getParam(params, "DefectCode"),
		getParam(params, "DefectTitle"),
		getParam(params, "DefectDescription"),
		getParam(params, "Severity"),
		getParam(params, "Priority"),
		getParam(params, "DefectType"),
	)

	if attachments, ok := params["Attachments"].([]map[string]string); ok && len(attachments) > 0 {
		prompt += "\n\n## 附件信息\n"
		for _, att := range attachments {
			prompt += fmt.Sprintf("- %s (%s)\n", att["FileName"], att["FileType"])
		}
	}

	if codeCtx, ok := params["CodeContext"].(string); ok && codeCtx != "" {
		prompt += fmt.Sprintf("\n## 相关代码上下文\n```\n%s\n```\n", codeCtx)
	}

	if files, ok := params["RelatedFiles"].([]string); ok && len(files) > 0 {
		prompt += "\n## 相关文件列表\n"
		for _, f := range files {
			prompt += fmt.Sprintf("- %s\n", f)
		}
	}

	prompt += "\n\n输出JSON：\n{\n" +
		"  \"rootCause\": \"≤2句\",\n" +
		"  \"affectedFiles\": [\"path\"],\n" +
		"  \"affectedScope\": \"≤1句\",\n" +
		"  \"riskLevel\": \"high|medium|low\",\n" +
		"  \"solution\": {\n" +
		"    \"description\": \"≤1句\",\n" +
		"    \"steps\": [{ \"step\": 1, \"action\": \"≤1句\", \"filePath\": \"真实路径\", \"repoHint\": \"仓库名，可选\", \"code\": \"仅变更部分\" }],\n" +
		"    \"estimatedEffort\": \"低|中|高\",\n" +
		"    \"dependencies\": [\"dep\"]\n" +
		"  },\n" +
		"  \"references\": [{ \"type\": \"code|doc|test\", \"path\": \"\", \"line\": 0, \"description\": \"\" }]\n" +
		"}"

	return prompt
}

// BuildBackendPrompt 构建后端AGENT分析提示词
func BuildBackendPrompt(params map[string]interface{}) string {
	prompt := fmt.Sprintf("%s\n\n分析以下后端缺陷：\n\n"+
		"## 缺陷信息\n"+
		"编号: %s | 标题: %s | 描述: %s | 严重级别: %s | 优先级: %s | 类型: %s",
		SystemPrompt,
		getParam(params, "DefectCode"),
		getParam(params, "DefectTitle"),
		getParam(params, "DefectDescription"),
		getParam(params, "Severity"),
		getParam(params, "Priority"),
		getParam(params, "DefectType"),
	)

	if attachments, ok := params["Attachments"].([]map[string]string); ok && len(attachments) > 0 {
		prompt += "\n\n## 附件信息\n"
		for _, att := range attachments {
			prompt += fmt.Sprintf("- %s (%s)\n", att["FileName"], att["FileType"])
		}
	}

	if codeCtx, ok := params["CodeContext"].(string); ok && codeCtx != "" {
		prompt += fmt.Sprintf("\n## 相关代码上下文\n```\n%s\n```\n", codeCtx)
	}
	if files, ok := params["RelatedFiles"].([]string); ok && len(files) > 0 {
		prompt += "\n## 相关文件列表\n"
		for _, f := range files {
			prompt += fmt.Sprintf("- %s\n", f)
		}
		prompt += "\n请严格约束：affectedFiles 只能从相关文件列表中选择；solution.steps[].filePath 必须引用真实文件；多仓库时补充 repoHint 或使用 仓库名/文件路径；如果无法确定，请返回空数组，不要编造项目中不存在的路径。\n"
	}

	prompt += "\n\n输出JSON：\n{\n" +
		"  \"rootCause\": \"≤2句\",\n" +
		"  \"affectedFiles\": [\"path\"],\n" +
		"  \"affectedScope\": \"≤1句\",\n" +
		"  \"riskLevel\": \"high|medium|low\",\n" +
		"  \"solution\": {\n" +
		"    \"description\": \"≤1句\",\n" +
		"    \"steps\": [{ \"step\": 1, \"action\": \"≤1句\", \"filePath\": \"真实路径\", \"repoHint\": \"仓库名，可选\", \"code\": \"仅变更部分\" }],\n" +
		"    \"estimatedEffort\": \"低|中|高\",\n" +
		"    \"dependencies\": [\"dep\"]\n" +
		"  }\n" +
		"}"

	return prompt
}

// BuildUIPrompt 构建UI_AGENT分析提示词
func BuildUIPrompt(params map[string]interface{}) string {
	prompt := fmt.Sprintf("%s\n\n分析以下UI/交互缺陷：\n\n"+
		"## 缺陷信息\n"+
		"编号: %s | 标题: %s | 描述: %s | 严重级别: %s | 优先级: %s | 类型: %s",
		SystemPrompt,
		getParam(params, "DefectCode"),
		getParam(params, "DefectTitle"),
		getParam(params, "DefectDescription"),
		getParam(params, "Severity"),
		getParam(params, "Priority"),
		getParam(params, "DefectType"),
	)

	if attachments, ok := params["Attachments"].([]map[string]string); ok && len(attachments) > 0 {
		prompt += "\n\n## 截图/附件\n"
		for _, att := range attachments {
			prompt += fmt.Sprintf("- %s (%s)\n", att["FileName"], att["FileType"])
		}
	}

	if files, ok := params["RelatedFiles"].([]string); ok && len(files) > 0 {
		prompt += "\n## 相关文件列表\n"
		for _, f := range files {
			prompt += fmt.Sprintf("- %s\n", f)
		}
	}

	prompt += "\n\n输出JSON：\n{\n" +
		"  \"rootCause\": \"≤2句\",\n" +
		"  \"affectedFiles\": [\"path\"],\n" +
		"  \"affectedScope\": \"≤1句\",\n" +
		"  \"riskLevel\": \"high|medium|low\",\n" +
		"  \"solution\": {\n" +
		"    \"description\": \"≤1句\",\n" +
		"    \"steps\": [{ \"step\": 1, \"action\": \"≤1句\", \"filePath\": \"真实路径\", \"repoHint\": \"仓库名，可选\", \"code\": \"仅变更CSS/HTML\" }],\n" +
		"    \"estimatedEffort\": \"低|中|高\"\n" +
		"  }\n" +
		"}"

	return prompt
}

// BuildFixGenerationPrompt 构建代码修复生成提示词
func BuildFixGenerationPrompt(analysisReport, currentCode, language string, optional ...string) string {
	targetFile := ""
	fixDescription := ""
	projectKnowledge := ""
	if len(optional) > 0 {
		targetFile = optional[0]
	}
	if len(optional) > 1 {
		fixDescription = optional[1]
	}
	if len(optional) > 2 {
		projectKnowledge = optional[2]
	}

	var kb string
	if projectKnowledge != "" {
		kb = "\n\n## Project Knowledge\n" + projectKnowledge + "\n"
	}

	var tf string
	if targetFile != "" {
		tf = "\n目标文件: " + targetFile + "\n"
	}

	var fd string
	if fixDescription != "" {
		fd = "\n修复描述: " + fixDescription + "\n"
	}

	return "根据分析报告修复代码：\n\n" +
		"## 分析报告\n" + analysisReport + "\n\n" +
		"## 当前代码\n" + "```" + language + "\n" + currentCode + "\n```\n\n" +
		tf + fd + kb +
		"约束：\n" +
		"1. 只改必要的部分，不重构，不输出整文件\n" +
		"2. 保持原有代码风格\n" +
		"3. hunks[].oldContent 必须逐字复制当前代码中唯一且连续的一段内容\n" +
		"4. hunks[].newContent 只写替换后的内容，禁止省略号和占位符\n" +
		"5. 无法安全修复时返回空 hunks 并写 reason\n" +
		"6. 只输出JSON，禁止Markdown代码块和任何JSON以外的文字\n\n" +
		"输出JSON Schema：\n" +
		"{\n" +
		"  \"filePath\": \"目标文件路径\",\n" +
		"  \"hunks\": [\n" +
		"    {\"oldContent\": \"当前代码中的唯一连续片段\", \"newContent\": \"替换后的片段\"}\n" +
		"  ],\n" +
		"  \"reason\": \"无法生成补丁时说明原因，可省略\"\n" +
		"}"
}

// GetAgentPrompt 根据AGENT类型获取对应的Prompt构建函数
func GetAgentPromptBuilder(agentType string) func(map[string]interface{}) string {
	switch agentType {
	case "frontend":
		return BuildFrontendPrompt
	case "backend":
		return BuildBackendPrompt
	case "ui":
		return BuildUIPrompt
	default:
		return BuildFrontendPrompt // 默认使用前端AGENT
	}
}

// getParam 安全获取参数值
func getParam(params map[string]interface{}, key string) string {
	if val, ok := params[key]; ok {
		if str, ok := val.(string); ok {
			return str
		}
		return fmt.Sprintf("%v", val)
	}
	return ""
}

// SelectAgentByDefectType 根据缺陷类型智能选择AGENT类型
func SelectAgentByDefectType(defectType string) []string {
	defectType = strings.ToLower(strings.TrimSpace(defectType))

	switch defectType {
	case "ui":
		return []string{"ui"}
	case "functional":
		return []string{"frontend", "backend"}
	case "performance":
		return []string{"frontend", "backend"}
	case "security":
		return []string{"backend"}
	case "compatibility":
		return []string{"frontend", "client"}
	default:
		return []string{"frontend"} // 默认使用前端AGENT
	}
}
