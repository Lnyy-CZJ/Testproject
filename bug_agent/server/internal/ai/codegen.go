package ai

import (
	"bug-agent/internal/git"
	"bug-agent/pkg/logger"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"go/parser"
	"go/token"
	"path/filepath"
	"strings"
)

// CodeGenerator AI代码修改引擎
type CodeGenerator struct {
	client AIClient
}

const (
	codegenTemperature = 0.3
	codegenMaxTokens   = 8192
	codegenMaxAttempts = 3
)

var ErrNoApplicableCodeChanges = errors.New("no applicable code changes generated")

func IsNoApplicableCodeChanges(err error) bool {
	return errors.Is(err, ErrNoApplicableCodeChanges)
}

// NewCodeGenerator 创建代码生成器
func NewCodeGenerator(client AIClient) *CodeGenerator {
	return &CodeGenerator{
		client: client,
	}
}

// CodeChange 代码变更
type CodeChange struct {
	FilePath    string     `json:"filePath"`
	OldContent  string     `json:"oldContent"`
	NewContent  string     `json:"newContent"`
	Diff        string     `json:"diff"`
	Description string     `json:"description"`
	Hunks       []CodeHunk `json:"hunks,omitempty"`
}

type CodeHunk struct {
	OldStart   int    `json:"oldStart"`
	OldLines   int    `json:"oldLines"`
	NewStart   int    `json:"newStart"`
	NewLines   int    `json:"newLines"`
	OldContent string `json:"oldContent"`
	NewContent string `json:"newContent"`
}

type patchResponse struct {
	FilePath string     `json:"filePath"`
	Hunks    []CodeHunk `json:"hunks"`
	Reason   string     `json:"reason,omitempty"`
}

// FixPlan 修复计划
type FixPlan struct {
	Steps []FixStep `json:"steps"`
}

type FixGenerationMetrics struct {
	PromptTokens     int   `json:"promptTokens"`
	CompletionTokens int   `json:"completionTokens"`
	TotalTokens      int   `json:"totalTokens"`
	DurationMs       int64 `json:"durationMs"`
}

// FixStep 修复步骤
type FixStep struct {
	Step       int         `json:"step"`
	Action     string      `json:"action"`
	FilePath   string      `json:"filePath,omitempty"`
	CodeChange *CodeChange `json:"codeChange,omitempty"`
	Status     string      `json:"status"` // pending, executing, completed, failed
	Error      string      `json:"error,omitempty"`
}

// GenerateFix 根据分析报告生成修复代码
func (g *CodeGenerator) GenerateFix(
	ctx context.Context,
	analysisReport json.RawMessage,
	repo *git.Repository,
) (*FixPlan, error) {
	plan, _, err := g.GenerateFixWithMetrics(ctx, analysisReport, repo)
	return plan, err
}

func (g *CodeGenerator) GenerateFixWithMetrics(
	ctx context.Context,
	analysisReport json.RawMessage,
	repo *git.Repository,
) (*FixPlan, FixGenerationMetrics, error) {

	var analysisData map[string]interface{}
	if err := json.Unmarshal(analysisReport, &analysisData); err != nil {
		return nil, FixGenerationMetrics{}, fmt.Errorf("parse analysis report failed: %w", err)
	}

	solution, ok := analysisData["solution"]
	if !ok || solution == nil {
		if topSteps, ok := analysisData["steps"]; ok && topSteps != nil {
			solution = map[string]interface{}{
				"steps": topSteps,
			}
		} else if rawResp, ok := analysisData["rawResponse"].(string); ok && rawResp != "" {
			solution = map[string]interface{}{
				"steps": []interface{}{
					map[string]interface{}{
						"action":      "根据分析报告修复缺陷",
						"code":        "",
						"rawGuidance": rawResp,
					},
				},
			}
		} else {
			return nil, FixGenerationMetrics{}, fmt.Errorf("no solution in analysis report")
		}
	}

	solutionMap, ok := solution.(map[string]interface{})
	if !ok {
		return nil, FixGenerationMetrics{}, fmt.Errorf("invalid solution format")
	}

	steps, ok := solutionMap["steps"].([]interface{})
	if !ok || len(steps) == 0 {
		return nil, FixGenerationMetrics{}, fmt.Errorf("no fix steps in solution")
	}

	fixPlan := &FixPlan{
		Steps: make([]FixStep, 0),
	}
	metrics := FixGenerationMetrics{}
	analysisFileTargets := extractAnalysisFileTargets(analysisData)
	if !solutionHasFileTargets(steps) && len(analysisFileTargets) != 1 {
		return nil, FixGenerationMetrics{}, fmt.Errorf("analysis report has no file-level fix target")
	}
	var lastGenerateErr error
	var fileStepErrors []string
	hasHardFileStepError := false

	for i, stepData := range steps {
		stepMap, ok := stepData.(map[string]interface{})
		if !ok {
			continue
		}

		action, _ := stepMap["action"].(string)
		filePath := extractStepFilePath(stepMap, analysisFileTargets)
		rawGuidance, _ := stepMap["rawGuidance"].(string)
		if desc, ok := stepMap["description"].(string); ok && desc != "" && rawGuidance == "" {
			rawGuidance = desc
		}

		fixStep := FixStep{
			Step:   i + 1,
			Action: action,
			Status: "pending",
		}

		if repo != nil {
			if !looksLikeRepoFilePath(filePath) {
				filePath = ""
			}
		}

		if filePath != "" && repo != nil {
			currentCode, err := repo.ReadFile(filePath)
			if err != nil {
				logger.Infof("[CodeGenerator] Warning: cannot read file %s: %v", filePath, err)
				fixStep.Status = "failed"
				fixStep.Error = err.Error()
				fileStepErrors = append(fileStepErrors, fmt.Sprintf("%s: %v", filePath, err))
				hasHardFileStepError = true
				fixPlan.Steps = append(fixPlan.Steps, fixStep)
				continue
			}

			language := detectLanguage(filePath)

			fixDescription := strings.TrimSpace(strings.Join([]string{action, rawGuidance}, "\n"))
			newCode, diff, hunks, usage, err := g.generatePatchChange(ctx, analysisReport, currentCode, language, filePath, fixDescription)
			metrics.PromptTokens += usage.PromptTokens
			metrics.CompletionTokens += usage.CompletionTokens
			metrics.TotalTokens += usage.TotalTokens
			if err != nil {
				logger.Errorf("[CodeGenerator] Generate fixed code failed: %v", err)
				fixStep.Error = err.Error()
				if IsNoApplicableCodeChanges(err) {
					fixStep.Status = "warning"
				} else {
					fixStep.Status = "failed"
				}
				lastGenerateErr = err
				fileStepErrors = append(fileStepErrors, fmt.Sprintf("%s: %v", filePath, err))
				if !IsNoApplicableCodeChanges(err) {
					hasHardFileStepError = true
				}
				fixPlan.Steps = append(fixPlan.Steps, fixStep)
				continue
			}

			fixStep.FilePath = filePath
			fixStep.CodeChange = &CodeChange{
				FilePath:    filePath,
				OldContent:  currentCode,
				NewContent:  newCode,
				Diff:        diff,
				Description: action,
				Hunks:       hunks,
			}
		}

		fixPlan.Steps = append(fixPlan.Steps, fixStep)
	}

	if len(fixPlan.Steps) == 0 {
		return nil, FixGenerationMetrics{}, fmt.Errorf("no valid fix steps generated")
	}

	hasCodeChange := false
	for _, step := range fixPlan.Steps {
		if step.CodeChange != nil {
			hasCodeChange = true
			break
		}
	}

	if len(fileStepErrors) > 0 {
		if hasHardFileStepError {
			return nil, metrics, fmt.Errorf("file-level fix step failed: %s", strings.Join(fileStepErrors, "; "))
		}
		if !hasCodeChange {
			return nil, metrics, fmt.Errorf("%w: file-level fix step failed: %s", ErrNoApplicableCodeChanges, strings.Join(fileStepErrors, "; "))
		}
	}

	if hasCodeChange {
		return fixPlan, metrics, nil
	}

	if lastGenerateErr != nil {
		return nil, metrics, fmt.Errorf("%w: %v", ErrNoApplicableCodeChanges, lastGenerateErr)
	}

	return nil, metrics, ErrNoApplicableCodeChanges
}

// generatePatchChange 调用AI生成结构化最小补丁
func (g *CodeGenerator) generatePatchChange(
	ctx context.Context,
	analysisReport json.RawMessage,
	currentCode string,
	language string,
	targetFile string,
	fixDescription string,
) (string, string, []CodeHunk, Usage, error) {

	prompt := BuildFixGenerationPrompt(string(analysisReport), currentCode, language, targetFile, fixDescription)
	messages := []Message{{Role: "user", Content: prompt}}
	totalUsage := Usage{}
	var lastErr error

	for attempt := 0; attempt < codegenMaxAttempts; attempt++ {
		resp, err := g.client.Chat(ctx, &ChatRequest{
			Model:          "", // 使用默认模型
			Messages:       messages,
			Temperature:    codegenTemperature, // 降低随机性，确保代码质量
			MaxTokens:      codegenMaxTokens,
			ResponseFormat: &ResponseFormat{Type: "json_object"},
		})
		if err != nil {
			return "", "", nil, totalUsage, fmt.Errorf("AI call failed: %w", err)
		}
		totalUsage.PromptTokens += resp.Usage.PromptTokens
		totalUsage.CompletionTokens += resp.Usage.CompletionTokens
		totalUsage.TotalTokens += resp.Usage.TotalTokens

		if len(resp.Choices) == 0 {
			lastErr = fmt.Errorf("empty response from AI")
			continue
		}

		aiResponse := resp.Choices[0].Message.Content
		patch, err := parsePatchResponse(aiResponse, targetFile)
		if err == nil {
			var newCode string
			var normalizedHunks []CodeHunk
			newCode, normalizedHunks, err = applyContentHunks(currentCode, patch.Hunks)
			if err == nil {
				if err = ValidateFix(currentCode, newCode); err == nil {
					if err = validateGeneratedFileSyntax(language, targetFile, newCode); err == nil {
						diff := generateSimpleDiff(currentCode, newCode)
						return newCode, diff, normalizedHunks, totalUsage, nil
					}
				}
			}
		}
		lastErr = err
		messages = append(messages,
			Message{Role: "assistant", Content: aiResponse},
			Message{Role: "user", Content: buildPatchRetryPrompt(lastErr)},
		)
	}

	if isPatchApplicabilityError(lastErr) {
		return "", "", nil, totalUsage, fmt.Errorf("%w: %v", ErrNoApplicableCodeChanges, lastErr)
	}
	return "", "", nil, totalUsage, lastErr
}

func parsePatchResponse(aiResponse, targetFile string) (patchResponse, error) {
	patchJSON, err := extractJSONObjectFromText(aiResponse)
	if err != nil {
		return patchResponse{}, fmt.Errorf("extract patch json failed: %w", err)
	}

	var patch patchResponse
	if err := json.Unmarshal([]byte(patchJSON), &patch); err != nil {
		return patchResponse{}, fmt.Errorf("parse patch json failed: %w", err)
	}
	if patch.FilePath != "" && targetFile != "" && strings.TrimSpace(patch.FilePath) != targetFile {
		return patchResponse{}, fmt.Errorf("patch file path mismatch: got %s want %s", patch.FilePath, targetFile)
	}
	if len(patch.Hunks) == 0 {
		reason := strings.TrimSpace(patch.Reason)
		if reason == "" {
			reason = "empty patch hunks"
		}
		return patchResponse{}, fmt.Errorf("%w: %s", ErrNoApplicableCodeChanges, reason)
	}
	return patch, nil
}

func buildPatchRetryPrompt(err error) string {
	return "上一次补丁无效，错误：" + err.Error() +
		"\n请重新检查上方“当前代码”，当前代码是唯一事实来源。" +
		"如果分析报告与当前代码不一致，或当前代码已具备要求的逻辑，请返回空 hunks 并在 reason 中说明无法安全生成变更。" +
		"否则只输出一个合法 JSON 对象，hunks[].oldContent 必须逐字匹配当前代码，newContent 必须保持目标文件语法正确。"
}

func isPatchApplicabilityError(err error) bool {
	if err == nil {
		return false
	}
	if IsNoApplicableCodeChanges(err) {
		return true
	}
	message := err.Error()
	for _, marker := range []string{
		"patch file path mismatch",
		"hunk context must match exactly once",
		"hunk produces no changes",
		"no changes made",
		"generated Go code is invalid",
		"empty hunk oldContent",
	} {
		if strings.Contains(message, marker) {
			return true
		}
	}
	return false
}

func validateGeneratedFileSyntax(language, targetFile, content string) error {
	if language != "go" && !strings.EqualFold(filepath.Ext(targetFile), ".go") {
		return nil
	}
	if _, err := parser.ParseFile(token.NewFileSet(), targetFile, content, parser.AllErrors); err != nil {
		return fmt.Errorf("generated Go code is invalid: %w", err)
	}
	return nil
}

func looksLikeRepoFilePath(value string) bool {
	value = strings.TrimSpace(value)
	if value == "" || strings.Contains(value, "\n") || strings.Contains(value, "\r") {
		return false
	}
	if strings.ContainsAny(value, "\"'`{}()") {
		return false
	}
	if strings.Contains(value, " ") {
		return false
	}
	ext := filepath.Ext(value)
	if ext == "" {
		return false
	}
	return true
}

func solutionHasFileTargets(steps []interface{}) bool {
	for _, stepData := range steps {
		stepMap, ok := stepData.(map[string]interface{})
		if !ok {
			continue
		}
		for _, key := range []string{"filePath", "path", "targetFile"} {
			if path, ok := stepMap[key].(string); ok && looksLikeRepoFilePath(path) {
				return true
			}
		}
	}
	return false
}

func extractStepFilePath(stepMap map[string]interface{}, fallbackTargets []string) string {
	for _, key := range []string{"filePath", "path", "targetFile"} {
		if path, ok := stepMap[key].(string); ok && looksLikeRepoFilePath(path) {
			return strings.TrimSpace(path)
		}
	}
	if len(fallbackTargets) == 1 {
		return fallbackTargets[0]
	}
	return ""
}

func extractAnalysisFileTargets(analysisData map[string]interface{}) []string {
	candidates := make([]string, 0)
	for _, key := range []string{"affectedFiles", "evidenceFiles", "relatedFiles"} {
		values, ok := analysisData[key]
		if !ok {
			continue
		}
		for _, path := range stringSliceFromInterface(values) {
			if looksLikeRepoFilePath(path) && !containsString(candidates, path) {
				candidates = append(candidates, strings.TrimSpace(path))
			}
		}
	}
	return candidates
}

func stringSliceFromInterface(value interface{}) []string {
	switch typed := value.(type) {
	case []string:
		return typed
	case []interface{}:
		result := make([]string, 0, len(typed))
		for _, item := range typed {
			switch v := item.(type) {
			case string:
				result = append(result, v)
			case map[string]interface{}:
				for _, key := range []string{"filePath", "path", "targetFile", "file_path", "filepath"} {
					if path, ok := v[key].(string); ok && strings.TrimSpace(path) != "" {
						result = append(result, strings.TrimSpace(path))
						break
					}
				}
			}
		}
		return result
	default:
		return nil
	}
}

func containsString(values []string, target string) bool {
	target = strings.TrimSpace(target)
	for _, value := range values {
		if strings.TrimSpace(value) == target {
			return true
		}
	}
	return false
}

func extractJSONObjectFromText(text string) (string, error) {
	start := strings.Index(text, "{")
	if start < 0 {
		return "", fmt.Errorf("response does not contain json object")
	}

	inString := false
	escaped := false
	depth := 0
	for i := start; i < len(text); i++ {
		ch := text[i]
		if inString {
			if escaped {
				escaped = false
				continue
			}
			if ch == '\\' {
				escaped = true
				continue
			}
			if ch == '"' {
				inString = false
			}
			continue
		}

		switch ch {
		case '"':
			inString = true
		case '{':
			depth++
		case '}':
			depth--
			if depth == 0 {
				return text[start : i+1], nil
			}
			if depth < 0 {
				return "", fmt.Errorf("invalid json object braces")
			}
		}
	}

	return "", fmt.Errorf("unterminated json object")
}

// generateSimpleDiff 生成简单的diff（简化版）
func generateSimpleDiff(oldCode, newCode string) string {
	oldLines := strings.Split(oldCode, "\n")
	newLines := strings.Split(newCode, "\n")

	var diff strings.Builder
	diff.WriteString("--- Original\n+++ Fixed\n")

	maxLen := len(oldLines)
	if len(newLines) > maxLen {
		maxLen = len(newLines)
	}

	for i := 0; i < maxLen; i++ {
		if i < len(oldLines) && i < len(newLines) {
			if oldLines[i] == newLines[i] {
				diff.WriteString(" " + oldLines[i] + "\n")
			} else {
				if oldLines[i] != "" {
					diff.WriteString("-" + oldLines[i] + "\n")
				}
				if newLines[i] != "" {
					diff.WriteString("+" + newLines[i] + "\n")
				}
			}
		} else if i < len(newLines) {
			diff.WriteString("+" + newLines[i] + "\n")
		} else if i < len(oldLines) {
			diff.WriteString("-" + oldLines[i] + "\n")
		}
	}

	return diff.String()
}

// ApplyChange 应用代码变更到仓库
func (g *CodeGenerator) ApplyChange(
	repo *git.Repository,
	change *CodeChange,
) error {
	if change == nil {
		return fmt.Errorf("nil code change")
	}
	if len(change.Hunks) == 0 {
		return fmt.Errorf("no code hunks to apply: %s", change.FilePath)
	}
	currentContent, err := repo.ReadFile(change.FilePath)
	if err != nil {
		return fmt.Errorf("read current file before apply failed: %w", err)
	}

	nextContent, err := applyCodeHunks(currentContent, change.Hunks)
	if err != nil {
		return fmt.Errorf("apply code hunks failed: %w", err)
	}
	if normalizeCodeContent(currentContent) == normalizeCodeContent(nextContent) {
		return fmt.Errorf("code hunks produced no changes: %s", change.FilePath)
	}

	err = repo.ModifyFile(change.FilePath, nextContent)
	if err != nil {
		return fmt.Errorf("apply file modification failed: %w", err)
	}

	logger.Infof("[CodeGenerator] Applied changes to %s", change.FilePath)
	return nil
}

// detectLanguage 检测编程语言
func detectLanguage(filePath string) string {
	idx := strings.LastIndex(filePath, ".")
	if idx < 0 {
		return "text"
	}
	ext := filePath[idx:]

	languageMap := map[string]string{
		".go":   "go",
		".js":   "javascript",
		".ts":   "typescript",
		".tsx":  "typescript",
		".jsx":  "javascript",
		".py":   "python",
		".java": "java",
		".rb":   "ruby",
		".php":  "php",
		".cs":   "csharp",
		".cpp":  "cpp",
		".c":    "c",
		".h":    "c",
		".html": "html",
		".css":  "css",
		".scss": "scss",
		".less": "less",
		".vue":  "html",
		".sql":  "sql",
		".xml":  "xml",
		".yaml": "yaml",
		".yml":  "yaml",
		".json": "json",
		".sh":   "bash",
		".bat":  "batch",
	}

	if lang, ok := languageMap[ext]; ok {
		return lang
	}

	return "text"
}

// ValidateFix 验证修复是否合理（基础检查）
func ValidateFix(originalCode, fixedCode string) error {
	if fixedCode == "" {
		return fmt.Errorf("fixed code is empty")
	}

	if normalizeCodeContent(originalCode) == normalizeCodeContent(fixedCode) {
		return fmt.Errorf("no changes made")
	}

	if len(fixedCode) < len(originalCode)/2 {
		openBraces := strings.Count(fixedCode, "{") - strings.Count(fixedCode, "\\{")
		closeBraces := strings.Count(fixedCode, "}") - strings.Count(fixedCode, "\\}")
		if openBraces != closeBraces {
			return fmt.Errorf("fixed code is too short and has unbalanced braces, possible data loss")
		}
	}

	return nil
}

func normalizeCodeContent(content string) string {
	content = strings.ReplaceAll(content, "\r\n", "\n")
	return strings.TrimSpace(content)
}

func applyCodeHunks(current string, hunks []CodeHunk) (string, error) {
	next, _, err := applyContentHunks(current, hunks)
	return next, err
}

func applyContentHunks(current string, hunks []CodeHunk) (string, []CodeHunk, error) {
	if len(hunks) == 0 {
		return "", nil, fmt.Errorf("no code hunks")
	}

	next := current
	normalized := make([]CodeHunk, 0, len(hunks))
	for _, hunk := range hunks {
		oldContent := hunk.OldContent
		if oldContent == "" {
			return "", nil, fmt.Errorf("empty hunk oldContent")
		}
		if oldContent == hunk.NewContent {
			return "", nil, fmt.Errorf("hunk produces no changes")
		}
		if count := strings.Count(next, oldContent); count != 1 {
			return "", nil, fmt.Errorf("hunk context must match exactly once, matched %d", count)
		}

		startIdx := strings.Index(next, oldContent)
		oldStart := lineNumberAtByteIndex(next, startIdx)
		next = strings.Replace(next, oldContent, hunk.NewContent, 1)
		normalized = append(normalized, CodeHunk{
			OldStart:   oldStart,
			OldLines:   countLogicalLines(oldContent),
			NewStart:   oldStart,
			NewLines:   countLogicalLines(hunk.NewContent),
			OldContent: oldContent,
			NewContent: hunk.NewContent,
		})
	}

	return next, normalized, nil
}

func lineNumberAtByteIndex(content string, idx int) int {
	if idx <= 0 {
		return 1
	}
	return strings.Count(content[:idx], "\n") + 1
}

func countLogicalLines(content string) int {
	if content == "" {
		return 0
	}
	return len(strings.SplitAfter(content, "\n"))
}
