package ai

import "fmt"

func BuildAnalysisMemoryExtractionPrompt(title, defectType, analysisJSON string) string {
	return fmt.Sprintf(`从以下缺陷分析中提取可复用的项目知识。只输出JSON数组，不要其他文字。

缺陷: %s | 类型: %s
分析: %s

输出: [{"category":"architecture|convention|common_error|fix_strategy","content":"≤200字","relevanceScore":0.0-1.0}]

约束:
1. 只提取项目级/模式级知识，不提取缺陷特有细节
2. 每条独立可用
3. 最多5条`, title, defectType, analysisJSON)
}

func BuildFixMemoryExtractionPrompt(title, planJSON, resultJSON string) string {
	return fmt.Sprintf(`从以下修复结果中提取有效的修复策略知识。只输出JSON数组，不要其他文字。

缺陷: %s
修复步骤: %s
结果: %s

输出: [{"category":"fix_strategy|avoid_strategy|convention","content":"≤200字","relevanceScore":0.0-1.0}]

约束:
1. 只提取有效的策略或重要模式
2. 最多3条`, title, planJSON, resultJSON)
}
