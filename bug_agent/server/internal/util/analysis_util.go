package util

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"

	"bug-agent/pkg/logger"
)

// GetStringField extracts a string value from a map by key.
// Returns TrimSpace'd string for string values, fmt.Sprintf for others, "" if missing.
func GetStringField(payload map[string]interface{}, key string) string {
	if payload == nil {
		return ""
	}
	value, ok := payload[key]
	if !ok || value == nil {
		return ""
	}
	switch typed := value.(type) {
	case string:
		return strings.TrimSpace(typed)
	default:
		return strings.TrimSpace(fmt.Sprintf("%v", typed))
	}
}

// GetStringSliceField converts common AI JSON list shapes to []string.
// Besides plain string arrays, it accepts object entries with file path keys.
func GetStringSliceField(value interface{}) []string {
	var items []interface{}
	switch typed := value.(type) {
	case []string:
		items = make([]interface{}, 0, len(typed))
		for _, item := range typed {
			items = append(items, item)
		}
	case []interface{}:
		items = typed
	default:
		return nil
	}

	result := make([]string, 0, len(items))
	seen := map[string]struct{}{}
	for _, item := range items {
		text := strings.TrimSpace(stringFromAIListItem(item))
		if text == "" {
			continue
		}
		if _, ok := seen[text]; ok {
			continue
		}
		seen[text] = struct{}{}
		result = append(result, text)
	}
	return result
}

func stringFromAIListItem(item interface{}) string {
	switch typed := item.(type) {
	case string:
		return typed
	case map[string]interface{}:
		for _, key := range []string{"filePath", "path", "targetFile", "file_path", "filepath"} {
			if value := strings.TrimSpace(GetStringField(typed, key)); value != "" {
				return value
			}
		}
		return ""
	default:
		return fmt.Sprintf("%v", item)
	}
}

// ExtractJSONObjectFromText finds the outermost JSON object in text.
// Uses first-{ / last-} matching.
var jsonCodeBlockRe = regexp.MustCompile("(?s)```(?:json)?\\s*\\n(\\{.*?\\})\\s*\\n```")

func ExtractJSONObjectFromText(text string) (string, error) {
	raw := strings.TrimSpace(text)
	if raw == "" {
		return "", fmt.Errorf("empty text")
	}
	if m := jsonCodeBlockRe.FindStringSubmatch(raw); len(m) >= 2 {
		candidate := strings.TrimSpace(m[1])
		if json.Valid([]byte(candidate)) {
			return candidate, nil
		}
	}
	start := strings.Index(raw, "{")
	if start < 0 {
		return "", fmt.Errorf("json object not found")
	}
	depth := 0
	inStr := false
	escape := false
	for i := start; i < len(raw); i++ {
		ch := raw[i]
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
				candidate := raw[start : i+1]
				if json.Valid([]byte(candidate)) {
					return candidate, nil
				}
			}
		}
	}
	return "", fmt.Errorf("no valid json object found in text")
}

// MapSeverityToRisk maps defect severity to risk level.
func MapSeverityToRisk(severity string) string {
	switch severity {
	case "fatal":
		return "high"
	case "major":
		return "high"
	case "normal":
		return "medium"
	case "minor":
		return "low"
	case "suggest":
		return "low"
	default:
		return "medium"
	}
}

// GetAgentLabel returns the Chinese display name for an agent type.
func GetAgentLabel(agentType string) string {
	labels := map[string]string{
		"frontend": "前端AGENT",
		"backend":  "后端AGENT",
		"ui":       "UI_AGENT",
		"client":   "客户端AGENT",
		"product":  "产品AGENT",
		"test":     "测试AGENT",
	}
	if label, ok := labels[agentType]; ok {
		return label
	}
	return agentType
}

// FormatValidationSuggestions formats a list of suggestions as a bullet list.
// Returns "- 暂无" for empty input.
func FormatValidationSuggestions(items []string) string {
	if len(items) == 0 {
		return "- 暂无"
	}
	var builder strings.Builder
	for _, item := range items {
		builder.WriteString("- ")
		builder.WriteString(item)
		builder.WriteString("\n")
	}
	return strings.TrimSpace(builder.String())
}

// MarshalStringSlice serializes a string slice to JSON.
// Returns "[]" on error.
func MarshalStringSlice(items []string) string {
	bytes, err := json.Marshal(items)
	if err != nil {
		logger.Errorf("[Util] marshal string slice failed: %v", err)
		return "[]"
	}
	return string(bytes)
}

// DefaultString returns s if non-empty (after TrimSpace), otherwise fallback.
func DefaultString(s, fallback string) string {
	if strings.TrimSpace(s) != "" {
		return s
	}
	return fallback
}

// ExtractRepoName extracts the repository name from a URL.
// Returns just the repo name (last path segment, without .git suffix).
func ExtractRepoName(repoURL string) string {
	repoURL = strings.TrimRight(repoURL, "/")
	parts := strings.Split(repoURL, "/")
	if len(parts) >= 2 {
		name := parts[len(parts)-1]
		name = strings.TrimSuffix(name, ".git")
		return name
	}
	return ""
}

// CollectOutOfScopeFiles returns files in referenced that are not in relatedFiles.
func CollectOutOfScopeFiles(referenced, relatedFiles []string) []string {
	if len(referenced) == 0 || len(relatedFiles) == 0 {
		return nil
	}
	allowed := make(map[string]struct{}, len(relatedFiles))
	for _, file := range relatedFiles {
		file = strings.TrimSpace(file)
		if file != "" {
			allowed[file] = struct{}{}
		}
	}
	out := make([]string, 0)
	seen := make(map[string]struct{})
	for _, file := range referenced {
		file = strings.TrimSpace(file)
		if file == "" {
			continue
		}
		if _, ok := allowed[file]; ok {
			continue
		}
		if _, ok := seen[file]; ok {
			continue
		}
		seen[file] = struct{}{}
		out = append(out, file)
	}
	sort.Strings(out)
	return out
}

func SanitizeUTF8(s string) string {
	if utf8.ValidString(s) {
		return s
	}
	var b strings.Builder
	b.Grow(len(s))
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		if r == utf8.RuneError && size == 1 {
			b.WriteByte(' ')
			i++
		} else {
			b.WriteRune(r)
			i += size
		}
	}
	return b.String()
}

func SanitizeJSONUTF8(data []byte) []byte {
	if json.Valid(data) && utf8.Valid(data) {
		return data
	}
	var m json.RawMessage = data
	raw, err := m.MarshalJSON()
	if err != nil {
		return []byte(SanitizeUTF8(string(data)))
	}
	return raw
}
