package service

import (
	"bug-agent/internal/model"
	"encoding/json"
	"strings"
)

func buildRepoScopedAnalysisInput(report model.AnalysisReport, repo model.ProjectRepo) json.RawMessage {
	payload := mergeAnalysisAndSolution(report)
	if payload == nil {
		return json.RawMessage(report.Analysis)
	}
	scoped := scopeAnalysisValue(payload, repo, "")
	bytes, err := json.Marshal(scoped)
	if err != nil {
		return json.RawMessage(report.Analysis)
	}
	return json.RawMessage(bytes)
}

func mergeAnalysisAndSolution(report model.AnalysisReport) map[string]interface{} {
	var analysis map[string]interface{}
	if err := json.Unmarshal([]byte(report.Analysis), &analysis); err != nil {
		return nil
	}
	if strings.TrimSpace(report.Solution) == "" || strings.TrimSpace(report.Solution) == "null" {
		return analysis
	}
	if _, ok := analysis["solution"]; ok {
		return analysis
	}
	var solution interface{}
	if err := json.Unmarshal([]byte(report.Solution), &solution); err != nil {
		return analysis
	}
	analysis["solution"] = solution
	return analysis
}

func scopeAnalysisValue(value interface{}, repo model.ProjectRepo, parentKey string) interface{} {
	switch typed := value.(type) {
	case map[string]interface{}:
		out := make(map[string]interface{}, len(typed))
		for key, raw := range typed {
			lowerKey := strings.ToLower(key)
			if s, ok := raw.(string); ok && isAnalysisFilePathKey(lowerKey) {
				out[key] = normalizeAnalysisFilePathForRepo(s, repo)
				continue
			}
			out[key] = scopeAnalysisValue(raw, repo, lowerKey)
		}
		return out
	case []interface{}:
		if isAnalysisFileArrayKey(parentKey) {
			return scopeAnalysisFileArray(typed, repo)
		}
		if parentKey == "steps" {
			return scopeAnalysisStepArray(typed, repo)
		}
		out := make([]interface{}, 0, len(typed))
		for _, item := range typed {
			out = append(out, scopeAnalysisValue(item, repo, parentKey))
		}
		return out
	default:
		return value
	}
}

func scopeAnalysisFileArray(items []interface{}, repo model.ProjectRepo) []interface{} {
	hasRepoScopedItem := false
	for _, item := range items {
		if analysisItemTargetsRepo(item, repo) {
			hasRepoScopedItem = true
			break
		}
	}

	out := make([]interface{}, 0, len(items))
	for _, item := range items {
		targetsRepo := analysisItemTargetsRepo(item, repo)
		if hasRepoScopedItem && !targetsRepo {
			continue
		}
		if s, ok := item.(string); ok {
			out = append(out, normalizeAnalysisFilePathForRepo(s, repo))
			continue
		}
		out = append(out, scopeAnalysisValue(item, repo, ""))
	}
	return out
}

func scopeAnalysisStepArray(items []interface{}, repo model.ProjectRepo) []interface{} {
	hasRepoScopedStep := false
	for _, item := range items {
		if analysisItemTargetsRepo(item, repo) {
			hasRepoScopedStep = true
			break
		}
	}

	out := make([]interface{}, 0, len(items))
	for _, item := range items {
		targetsRepo := analysisItemTargetsRepo(item, repo)
		if hasRepoScopedStep && !targetsRepo {
			continue
		}
		out = append(out, scopeAnalysisValue(item, repo, ""))
	}
	return out
}

func analysisItemTargetsRepo(item interface{}, repo model.ProjectRepo) bool {
	switch typed := item.(type) {
	case string:
		_, matched := stripRepoPathPrefix(typed, repo)
		return matched
	case map[string]interface{}:
		for key, raw := range typed {
			lowerKey := strings.ToLower(key)
			if s, ok := raw.(string); ok {
				if isAnalysisRepoHintKey(lowerKey) && repoHintMatchesRepo(s, repo) {
					return true
				}
				if isAnalysisFilePathKey(lowerKey) {
					if _, matched := stripRepoPathPrefix(s, repo); matched {
						return true
					}
				}
			}
		}
	}
	return false
}

func normalizeAnalysisFilePathForRepo(value string, repo model.ProjectRepo) string {
	if stripped, matched := stripRepoPathPrefix(value, repo); matched {
		return stripped
	}
	return strings.Trim(strings.ReplaceAll(strings.TrimSpace(value), "\\", "/"), "/")
}

func repoHintMatchesRepo(value string, repo model.ProjectRepo) bool {
	hint := normalizeRepoMatchValue(value)
	for _, key := range repoMatchKeys(repo) {
		if hint == key || strings.Contains(hint, key) || strings.Contains(key, hint) {
			return true
		}
	}
	return false
}

func isAnalysisRepoHintKey(key string) bool {
	switch key {
	case "repohint", "repo", "repository", "repositoryname", "reponame", "projectrepo":
		return true
	default:
		return false
	}
}

func isAnalysisFilePathKey(key string) bool {
	switch key {
	case "filepath", "path", "targetfile":
		return true
	default:
		return false
	}
}

func isAnalysisFileArrayKey(key string) bool {
	switch key {
	case "affectedfiles", "evidencefiles", "relatedfiles":
		return true
	default:
		return false
	}
}
