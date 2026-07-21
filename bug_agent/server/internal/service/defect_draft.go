package service

import (
	"bug-agent/internal/ai"
	"bug-agent/internal/model"
	"bug-agent/pkg/logger"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"

	"gorm.io/gorm"
)

const defectDraftPromptVersion = "v5.2-draft-1"

type DefectDraftRequest struct {
	IterationID *uint    `json:"iterationId,omitempty"`
	Message     string   `json:"message"`
	Tags        []string `json:"tags,omitempty"`
}

type DefectDraft struct {
	Title                string   `json:"title"`
	DescriptionMarkdown  string   `json:"descriptionMarkdown"`
	Severity             string   `json:"severity"`
	Priority             string   `json:"priority"`
	Type                 string   `json:"type"`
	Tags                 []string `json:"tags"`
	SuggestedIterationID *uint    `json:"suggestedIterationId,omitempty"`
	MissingInformation   []string `json:"missingInformation,omitempty"`
	Confidence           float64  `json:"confidence"`
	SourceMode           string   `json:"sourceMode"`
	Provider             string   `json:"provider,omitempty"`
	ModelName            string   `json:"modelName,omitempty"`
	PromptVersion        string   `json:"promptVersion,omitempty"`
	FallbackUsed         bool     `json:"fallbackUsed,omitempty"`
	FallbackReason       string   `json:"fallbackReason,omitempty"`
}

type flexibleUint struct {
	value uint
	valid bool
}

func (f *flexibleUint) UnmarshalJSON(data []byte) error {
	s := strings.TrimSpace(string(data))
	if s == "" || s == `""` || s == "null" {
		f.valid = false
		return nil
	}
	if n, err := strconv.ParseUint(s, 10, 64); err == nil {
		f.value = uint(n)
		f.valid = true
		return nil
	}
	var n uint
	if err := json.Unmarshal(data, &n); err == nil {
		f.value = n
		f.valid = true
		return nil
	}
	f.valid = false
	return nil
}

func (f flexibleUint) ToUintPtr() *uint {
	if !f.valid {
		return nil
	}
	return &f.value
}

type flexibleFloat struct {
	value float64
	valid bool
}

func (f *flexibleFloat) UnmarshalJSON(data []byte) error {
	s := strings.TrimSpace(string(data))
	s = strings.Trim(s, `"`)
	if s == "" || s == "null" {
		f.valid = false
		return nil
	}
	n, err := strconv.ParseFloat(s, 64)
	if err != nil {
		f.valid = false
		return nil
	}
	f.value = n
	f.valid = true
	return nil
}

func (f flexibleFloat) Value() float64 {
	if !f.valid {
		return 0
	}
	return f.value
}

type defectDraftAIResponse struct {
	Title                string        `json:"title"`
	DescriptionMarkdown  string        `json:"descriptionMarkdown"`
	Severity             string        `json:"severity"`
	Priority             string        `json:"priority"`
	Type                 string        `json:"type"`
	Tags                 []string      `json:"tags"`
	SuggestedIterationID flexibleUint  `json:"suggestedIterationId,omitempty"`
	MissingInformation   []string      `json:"missingInformation,omitempty"`
	Confidence           flexibleFloat `json:"confidence"`
}

type DefectDraftService struct {
	db        *gorm.DB
	newClient func(config model.ProjectAIConfig) (ai.AIClient, error)
}

func NewDefectDraftService(db *gorm.DB) *DefectDraftService {
	return &DefectDraftService{
		db: db,
		newClient: func(config model.ProjectAIConfig) (ai.AIClient, error) {
			return ai.NewAIClient(config.Provider, config.APIKey, config.APIEndpoint, config.ModelName)
		},
	}
}

func (s *DefectDraftService) GenerateDraft(ctx context.Context, projectID uint, req DefectDraftRequest) (*DefectDraft, error) {
	message := strings.TrimSpace(req.Message)
	if projectID == 0 {
		return nil, fmt.Errorf("projectID 不能为空")
	}
	if message == "" {
		return nil, fmt.Errorf("message 不能为空")
	}

	iterations, err := s.listProjectIterations(projectID)
	if err != nil {
		return nil, err
	}
	fallbackIterationID := pickSuggestedIterationID(iterations, req.IterationID)
	seedTags := sanitizeDraftTags(req.Tags)

	var fallbackReason string
	configs, err := listUsableProjectAIConfigs(s.db, projectID)
	if err == nil {
		var lastDraftErr error
		var lastClientErr error
		for _, config := range configs {
			client, clientErr := s.newClient(config)
			if clientErr != nil {
				lastClientErr = clientErr
				continue
			}
			draft, draftErr := s.generateWithAI(ctx, client, config, projectID, iterations, req, seedTags, fallbackIterationID)
			if draftErr == nil {
				return draft, nil
			}
			lastDraftErr = draftErr
		}
		if lastDraftErr != nil {
			fallbackReason = normalizeDraftFallbackReason(lastDraftErr)
		} else if lastClientErr != nil {
			fallbackReason = normalizeDraftFallbackReason(lastClientErr)
		}
	} else {
		fallbackReason = normalizeDraftFallbackReason(err)
	}

	return s.fallbackDraft(req, seedTags, fallbackIterationID, fallbackReason), nil
}

func (s *DefectDraftService) generateWithAI(ctx context.Context, client ai.AIClient, config model.ProjectAIConfig, projectID uint, iterations []model.Iteration, req DefectDraftRequest, seedTags []string, fallbackIterationID *uint) (*DefectDraft, error) {
	prompt := buildDefectDraftPrompt(iterations, req)
	resp, err := client.Chat(ctx, &ai.ChatRequest{
		Model: config.ModelName,
		Messages: []ai.Message{
			{Role: "system", Content: defectDraftSystemPrompt},
			{Role: "user", Content: prompt},
		},
		Temperature: 0.2,
		MaxTokens:   defaultAnalysisMaxTokens,
	})
	if err != nil {
		return nil, err
	}
	if len(resp.Choices) == 0 {
		return nil, fmt.Errorf("AI 返回空结果")
	}

	payload := strings.TrimSpace(resp.Choices[0].Message.Content)
	payload = stripMarkdownCodeBlock(payload)

	jsonStr, err := extractJSONObject(payload)
	if err != nil {
		logger.Infof("[defect-draft] AI raw response (first 500 chars): %.500s", resp.Choices[0].Message.Content)
		return nil, fmt.Errorf("AI 返回非 JSON 内容: %w", err)
	}

	var parsed defectDraftAIResponse
	if err := json.Unmarshal([]byte(jsonStr), &parsed); err != nil {
		cleaned := fixCommonJSONIssues(jsonStr)
		if err2 := json.Unmarshal([]byte(cleaned), &parsed); err2 != nil {
			logger.Errorf("[defect-draft] JSON parse failed: %v, raw (first 300): %.300s", err, jsonStr)
			return nil, fmt.Errorf("AI 草稿解析失败: %w", err)
		}
	}

	draft := &DefectDraft{
		Title:                strings.TrimSpace(parsed.Title),
		DescriptionMarkdown:  strings.TrimSpace(parsed.DescriptionMarkdown),
		Severity:             normalizeDraftSeverity(parsed.Severity),
		Priority:             normalizeDraftPriority(parsed.Priority),
		Type:                 normalizeDraftType(parsed.Type),
		Tags:                 mergeDraftTags(seedTags, parsed.Tags),
		SuggestedIterationID: validateSuggestedIteration(iterations, parsed.SuggestedIterationID.ToUintPtr(), fallbackIterationID),
		MissingInformation:   sanitizeDraftStrings(parsed.MissingInformation),
		Confidence:           clampConfidence(parsed.Confidence.Value()),
		SourceMode:           model.IssueSourceManualChat,
		Provider:             config.Provider,
		ModelName:            config.ModelName,
		PromptVersion:        defectDraftPromptVersion,
	}
	if draft.Title == "" {
		draft.Title = truncateText(req.Message, 100)
	}
	if draft.DescriptionMarkdown == "" {
		draft.DescriptionMarkdown = strings.TrimSpace(req.Message)
	}
	if len(draft.Tags) == 0 {
		draft.Tags = seedTags
	}
	return draft, nil
}

func (s *DefectDraftService) fallbackDraft(req DefectDraftRequest, seedTags []string, suggestedIterationID *uint, fallbackReason string) *DefectDraft {
	title := truncateText(req.Message, 100)
	if title == "" {
		title = "未命名缺陷"
	}
	fallbackReason = strings.TrimSpace(fallbackReason)
	if fallbackReason == "" {
		fallbackReason = "AI 服务暂时不可用，已切换为基础草稿，请手动确认字段。"
	}
	return &DefectDraft{
		Title:                title,
		DescriptionMarkdown:  strings.TrimSpace(req.Message),
		Severity:             model.SeverityNormal,
		Priority:             model.PriorityP2,
		Type:                 model.DefectTypeOther,
		Tags:                 seedTags,
		SuggestedIterationID: suggestedIterationID,
		Confidence:           0,
		SourceMode:           model.IssueSourceManualChat,
		PromptVersion:        defectDraftPromptVersion,
		FallbackUsed:         true,
		FallbackReason:       fallbackReason,
	}
}

func normalizeDraftFallbackReason(err error) string {
	if err == nil {
		return ""
	}
	lower := strings.ToLower(strings.TrimSpace(err.Error()))
	switch {
	case strings.Contains(lower, "未找到ai配置"):
		return "当前项目未配置 AI 模型，已切换为基础草稿，请在 AI 配置页补全模型和密钥。"
	case strings.Contains(lower, "未找到可用ai配置"):
		return "当前项目 AI 配置不可用，已切换为基础草稿，请检查模型、端点和 API Key。"
	case strings.Contains(lower, "api key"), strings.Contains(lower, "unauthorized"), strings.Contains(lower, "401"), strings.Contains(lower, "forbidden"):
		return "AI 鉴权失败，已切换为基础草稿，请检查 API Key 是否有效。"
	case strings.Contains(lower, "timeout"), strings.Contains(lower, "deadline exceeded"):
		return "AI 请求超时，已切换为基础草稿，请稍后重试。"
	case strings.Contains(lower, "429"), strings.Contains(lower, "rate"), strings.Contains(lower, "throttl"):
		return "AI 请求频率过高，已切换为基础草稿，请稍后重试。"
	case strings.Contains(lower, "解析失败"), strings.Contains(lower, "非 json"), strings.Contains(lower, "empty result"):
		return "AI 返回内容格式异常，已切换为基础草稿，请重试。"
	default:
		return "AI 整理失败，已切换为基础草稿，请手动确认字段。"
	}
}

func (s *DefectDraftService) listProjectIterations(projectID uint) ([]model.Iteration, error) {
	var iterations []model.Iteration
	if err := s.db.Where("project_id = ?", projectID).Order("created_at desc, id desc").Find(&iterations).Error; err != nil {
		return nil, fmt.Errorf("查询迭代失败: %w", err)
	}
	return iterations, nil
}

func buildDefectDraftPrompt(iterations []model.Iteration, req DefectDraftRequest) string {
	var iterationLines []string
	for _, iteration := range iterations {
		iterationLines = append(iterationLines, fmt.Sprintf("- id=%d name=%s status=%s", iteration.ID, iteration.Name, iteration.Status))
	}
	if len(iterationLines) == 0 {
		iterationLines = append(iterationLines, "- 暂无可用迭代")
	}

	message := strings.TrimSpace(req.Message)
	return fmt.Sprintf("请将以下缺陷描述整理成结构化草稿。\n\n用户原始输入:\n%s\n\n可用迭代:\n%s\n\n补充标签: %s", message, strings.Join(iterationLines, "\n"), strings.Join(req.Tags, ", "))
}

func pickSuggestedIterationID(iterations []model.Iteration, preferred *uint) *uint {
	if preferred != nil {
		for _, iteration := range iterations {
			if iteration.ID == *preferred {
				id := iteration.ID
				return &id
			}
		}
	}
	for _, iteration := range iterations {
		if strings.EqualFold(strings.TrimSpace(iteration.Status), "active") {
			id := iteration.ID
			return &id
		}
	}
	for _, iteration := range iterations {
		if strings.EqualFold(strings.TrimSpace(iteration.Status), "planning") {
			id := iteration.ID
			return &id
		}
	}
	if len(iterations) == 0 {
		return nil
	}
	id := iterations[0].ID
	return &id
}

func validateSuggestedIteration(iterations []model.Iteration, candidate *uint, fallback *uint) *uint {
	if candidate != nil {
		for _, iteration := range iterations {
			if iteration.ID == *candidate {
				id := iteration.ID
				return &id
			}
		}
	}
	return fallback
}

func normalizeDraftSeverity(value string) string {
	switch strings.TrimSpace(strings.ToLower(value)) {
	case model.SeverityFatal:
		return model.SeverityFatal
	case model.SeverityMajor:
		return model.SeverityMajor
	case model.SeverityMinor:
		return model.SeverityMinor
	case model.SeveritySuggest:
		return model.SeveritySuggest
	default:
		return model.SeverityNormal
	}
}

func normalizeDraftPriority(value string) string {
	value = strings.ToUpper(strings.TrimSpace(value))
	switch value {
	case model.PriorityP0, model.PriorityP1, model.PriorityP2, model.PriorityP3, model.PriorityP4:
		return value
	default:
		return model.PriorityP2
	}
}

func normalizeDraftType(value string) string {
	switch strings.TrimSpace(strings.ToLower(value)) {
	case model.DefectTypeFunctional:
		return model.DefectTypeFunctional
	case model.DefectTypeUI:
		return model.DefectTypeUI
	case model.DefectTypePerformance:
		return model.DefectTypePerformance
	case model.DefectTypeSecurity:
		return model.DefectTypeSecurity
	case model.DefectTypeCompatibility:
		return model.DefectTypeCompatibility
	default:
		return model.DefectTypeOther
	}
}

func sanitizeDraftTags(tags []string) []string {
	seen := make(map[string]struct{}, len(tags))
	items := make([]string, 0, len(tags))
	for _, tag := range tags {
		tag = strings.TrimSpace(tag)
		if tag == "" {
			continue
		}
		if _, ok := seen[tag]; ok {
			continue
		}
		seen[tag] = struct{}{}
		items = append(items, tag)
	}
	return items
}

func sanitizeDraftStrings(items []string) []string {
	seen := make(map[string]struct{}, len(items))
	cleaned := make([]string, 0, len(items))
	for _, item := range items {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}
		if _, ok := seen[item]; ok {
			continue
		}
		seen[item] = struct{}{}
		cleaned = append(cleaned, item)
	}
	return cleaned
}

func mergeDraftTags(seed []string, aiTags []string) []string {
	return sanitizeDraftTags(append(append([]string{}, seed...), aiTags...))
}

func clampConfidence(value float64) float64 {
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return 0
	}
	if value < 0 {
		return 0
	}
	if value > 1 {
		return 1
	}
	return value
}

const defectDraftSystemPrompt = `将用户描述整理为缺陷JSON草稿。只输出JSON，不要其他文字。
字段：title(简洁标题) | descriptionMarkdown(Markdown:现象/预期/影响) | severity(fatal|major|normal|minor|suggest) | priority(P0-P4) | type(functional|ui|performance|security|compatibility|other) | tags(数组) | suggestedIterationId(迭代id,可空) | missingInformation(缺失信息数组) | confidence(0-1)
信息不足也必须返回合法JSON。`

var markdownCodeBlockRe = regexp.MustCompile("(?s)^```(?:json)?\\s*\\n?(.*?)\\n?```\\s*$")
var trailingCommaRe = regexp.MustCompile(`,\s*([}\]])`)

func stripMarkdownCodeBlock(s string) string {
	if m := markdownCodeBlockRe.FindStringSubmatch(s); len(m) >= 2 {
		return strings.TrimSpace(m[1])
	}
	s = strings.TrimPrefix(s, "```json")
	s = strings.TrimPrefix(s, "```")
	s = strings.TrimSuffix(s, "```")
	return strings.TrimSpace(s)
}

func extractJSONObject(s string) (string, error) {
	s = strings.TrimSpace(s)
	s = stripMarkdownCodeBlock(s)
	s = strings.TrimPrefix(s, "\xEF\xBB\xBF")
	s = strings.TrimSpace(s)

	start := strings.Index(s, "{")
	if start < 0 {
		return "", fmt.Errorf("no opening brace found")
	}
	depth := 0
	inStr := false
	escape := false
	for i := start; i < len(s); i++ {
		ch := s[i]
		if escape {
			escape = false
			continue
		}
		if ch == '\\' && inStr {
			escape = true
			continue
		}
		if ch == '"' {
			inStr = !inStr
			continue
		}
		if inStr {
			continue
		}
		if ch == '{' {
			depth++
		} else if ch == '}' {
			depth--
			if depth == 0 {
				candidate := s[start : i+1]
				if json.Valid([]byte(candidate)) {
					return candidate, nil
				}
				fixed := fixCommonJSONIssues(candidate)
				if json.Valid([]byte(fixed)) {
					return fixed, nil
				}
				return fixed, fmt.Errorf("extracted JSON is invalid even after fix")
			}
		}
	}
	return "", fmt.Errorf("unbalanced braces")
}

func fixCommonJSONIssues(s string) string {
	s = trailingCommaRe.ReplaceAllString(s, "$1")
	s = stripJSONComments(s)
	return s
}

func stripJSONComments(s string) string {
	var result strings.Builder
	inString := false
	escape := false
	i := 0
	for i < len(s) {
		ch := s[i]
		if escape {
			result.WriteByte(ch)
			escape = false
			i++
			continue
		}
		if ch == '\\' && inString {
			result.WriteByte(ch)
			escape = true
			i++
			continue
		}
		if ch == '"' {
			inString = !inString
			result.WriteByte(ch)
			i++
			continue
		}
		if !inString && ch == '/' && i+1 < len(s) {
			if s[i+1] == '/' {
				for i < len(s) && s[i] != '\n' {
					i++
				}
				continue
			}
			if s[i+1] == '*' {
				i += 2
				for i+1 < len(s) && !(s[i] == '*' && s[i+1] == '/') {
					i++
				}
				if i+1 < len(s) {
					i += 2
				}
				continue
			}
		}
		result.WriteByte(ch)
		i++
	}
	return result.String()
}
