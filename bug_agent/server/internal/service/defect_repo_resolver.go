package service

import (
	"bug-agent/internal/git"
	"bug-agent/internal/model"
	"encoding/json"
	"fmt"
	"path"
	"strings"

	"gorm.io/gorm"
)

type DefectRepositorySelection struct {
	ProjectRepo     model.ProjectRepo
	Auth            *git.Auth
	IterationBranch string
}

type projectRepoCandidate struct {
	repo            model.ProjectRepo
	iterationBranch string
}

func ResolveDefectProjectRepoForReport(
	db *gorm.DB,
	defect model.Defect,
	agentType string,
	report model.AnalysisReport,
) (model.ProjectRepo, string, error) {
	candidates, err := listDefectProjectRepoCandidates(db, defect, agentType)
	if err != nil {
		return model.ProjectRepo{}, "", err
	}
	if selected, branch, ok := selectProjectRepoByAnalysisReport(candidates, report); ok {
		return selected, branch, nil
	}
	return ResolveDefectProjectRepo(db, defect, agentType)
}

func ResolveDefectProjectReposForReport(
	db *gorm.DB,
	defect model.Defect,
	agentType string,
	report model.AnalysisReport,
) ([]projectRepoCandidate, error) {
	candidates, err := listDefectProjectRepoCandidates(db, defect, agentType)
	if err != nil {
		return nil, err
	}
	if len(candidates) == 0 {
		projectRepo, branch, err := ResolveDefectProjectRepo(db, defect, agentType)
		if err != nil {
			return nil, err
		}
		return []projectRepoCandidate{{repo: projectRepo, iterationBranch: branch}}, nil
	}

	hints, filePaths := extractRepoHintsAndFiles(report)
	bestScore := 0
	selected := make([]projectRepoCandidate, 0, len(candidates))
	for _, candidate := range candidates {
		score := scoreProjectRepoCandidate(candidate.repo, hints, filePaths)
		if score <= 0 {
			continue
		}
		if score > bestScore {
			bestScore = score
			selected = selected[:0]
		}
		if score == bestScore {
			selected = append(selected, candidate)
		}
	}
	if len(selected) > 0 {
		return selected, nil
	}

	if len(candidates) > 1 && (len(hints) > 0 || len(filePaths) > 0) {
		return nil, fmt.Errorf("分析报告包含代码文件线索，但无法明确匹配 agentType=%s 的目标仓库，请在分析结果中输出 repoHint 或使用 仓库名/文件路径 格式", strings.TrimSpace(agentType))
	}

	projectRepo, branch, err := ResolveDefectProjectRepo(db, defect, agentType)
	if err != nil {
		return nil, err
	}
	return []projectRepoCandidate{{repo: projectRepo, iterationBranch: branch}}, nil
}

func ResolveDefectProjectRepo(
	db *gorm.DB,
	defect model.Defect,
	agentType string,
) (model.ProjectRepo, string, error) {
	var iteration model.Iteration
	if err := db.Select("id, project_id").Where("id = ?", defect.IterationID).First(&iteration).Error; err != nil {
		return model.ProjectRepo{}, "", fmt.Errorf("迭代不存在，请检查缺陷关联的迭代是否正确: %w", err)
	}

	projectRepo, iterationBranch, ok := selectIterationProjectRepo(db, defect.IterationID, agentType)
	if !ok {
		var projectRepos []model.ProjectRepo
		if err := db.Where("project_id = ?", iteration.ProjectID).Order("id ASC").Find(&projectRepos).Error; err == nil {
			for _, candidate := range projectRepos {
				if !matchAgentType(candidate.AgentTypes, agentType) {
					continue
				}
				projectRepo = candidate
				ok = true
				break
			}
			if !ok && len(projectRepos) > 0 {
				return model.ProjectRepo{}, "", fmt.Errorf("项目仓库未配置 agentType=%s 的代码仓库，请在项目仓库设置中补充 AGENT 类型绑定", strings.TrimSpace(agentType))
			}
		}
	}
	if !ok {
		return model.ProjectRepo{}, "", fmt.Errorf("迭代和项目均未绑定代码仓库，请先在项目设置中添加仓库并绑定到迭代")
	}
	return projectRepo, strings.TrimSpace(iterationBranch), nil
}

func listDefectProjectRepoCandidates(db *gorm.DB, defect model.Defect, agentType string) ([]projectRepoCandidate, error) {
	var iteration model.Iteration
	if err := db.Select("id, project_id").Where("id = ?", defect.IterationID).First(&iteration).Error; err != nil {
		return nil, fmt.Errorf("迭代不存在，请检查缺陷关联的迭代是否正确: %w", err)
	}

	candidates := make([]projectRepoCandidate, 0)
	seen := map[uint]bool{}
	var iterationRepos []model.IterationRepo
	if err := db.Where("iteration_id = ?", defect.IterationID).Find(&iterationRepos).Error; err == nil {
		for _, iterationRepo := range iterationRepos {
			if iterationRepo.RepoID == nil || seen[*iterationRepo.RepoID] {
				continue
			}
			var repo model.ProjectRepo
			if err := db.First(&repo, *iterationRepo.RepoID).Error; err != nil || !matchAgentType(repo.AgentTypes, agentType) {
				continue
			}
			seen[repo.ID] = true
			candidates = append(candidates, projectRepoCandidate{repo: repo, iterationBranch: strings.TrimSpace(iterationRepo.Branch)})
		}
	}

	var projectRepos []model.ProjectRepo
	if err := db.Where("project_id = ?", iteration.ProjectID).Order("id ASC").Find(&projectRepos).Error; err != nil {
		return candidates, nil
	}
	for _, repo := range projectRepos {
		if seen[repo.ID] || !matchAgentType(repo.AgentTypes, agentType) {
			continue
		}
		seen[repo.ID] = true
		candidates = append(candidates, projectRepoCandidate{repo: repo})
	}
	return candidates, nil
}

func selectProjectRepoByAnalysisReport(candidates []projectRepoCandidate, report model.AnalysisReport) (model.ProjectRepo, string, bool) {
	if len(candidates) == 0 {
		return model.ProjectRepo{}, "", false
	}
	hints, filePaths := extractRepoHintsAndFiles(report)
	bestScore := 0
	var best projectRepoCandidate
	for _, candidate := range candidates {
		score := scoreProjectRepoCandidate(candidate.repo, hints, filePaths)
		if score > bestScore {
			bestScore = score
			best = candidate
		}
	}
	if bestScore <= 0 {
		return model.ProjectRepo{}, "", false
	}
	return best.repo, best.iterationBranch, true
}

func extractRepoHintsAndFiles(report model.AnalysisReport) ([]string, []string) {
	hints := make([]string, 0)
	files := make([]string, 0)
	collectReportHints(report.Analysis, &hints, &files)
	collectReportHints(report.Solution, &hints, &files)
	return uniqueNonEmpty(hints), uniqueNonEmpty(files)
}

func collectReportHints(raw string, hints, files *[]string) {
	if strings.TrimSpace(raw) == "" || strings.TrimSpace(raw) == "null" {
		return
	}
	var payload interface{}
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		return
	}
	walkReportPayload(payload, hints, files)
}

func walkReportPayload(value interface{}, hints, files *[]string) {
	switch typed := value.(type) {
	case map[string]interface{}:
		for key, raw := range typed {
			lowerKey := strings.ToLower(key)
			if s, ok := raw.(string); ok {
				switch lowerKey {
				case "repohint", "repo", "repository", "repositoryname", "reponame", "projectrepo":
					*hints = append(*hints, s)
				case "filepath", "path", "targetfile":
					*files = append(*files, s)
				}
			}
			walkReportPayload(raw, hints, files)
		}
	case []interface{}:
		for _, item := range typed {
			if s, ok := item.(string); ok && looksLikeAnalysisFilePath(s) {
				*files = append(*files, s)
			}
			walkReportPayload(item, hints, files)
		}
	}
}

func scoreProjectRepoCandidate(repo model.ProjectRepo, hints, filePaths []string) int {
	keys := repoMatchKeys(repo)
	score := 0
	for _, hint := range hints {
		hint = normalizeRepoMatchValue(hint)
		for _, key := range keys {
			if hint == key {
				score += 100
			} else if strings.Contains(hint, key) || strings.Contains(key, hint) {
				score += 50
			}
		}
	}
	for _, filePath := range filePaths {
		firstSegment := normalizeRepoMatchValue(firstPathSegment(filePath))
		for _, key := range keys {
			if firstSegment == key {
				score += 40
			}
		}
	}
	return score
}

func repoMatchKeys(repo model.ProjectRepo) []string {
	return uniqueNonEmpty([]string{
		normalizeRepoMatchValue(repo.Name),
		normalizeRepoMatchValue(repo.ExternalRepoID),
		normalizeRepoMatchValue(repoURLBaseName(repo.RepoURL)),
	})
}

func repoURLBaseName(repoURL string) string {
	repoURL = strings.TrimSpace(strings.TrimSuffix(repoURL, ".git"))
	repoURL = strings.TrimRight(repoURL, "/")
	if repoURL == "" {
		return ""
	}
	return path.Base(repoURL)
}

func firstPathSegment(value string) string {
	value = strings.Trim(strings.ReplaceAll(value, "\\", "/"), "/")
	if value == "" {
		return ""
	}
	if idx := strings.Index(value, "/"); idx >= 0 {
		return value[:idx]
	}
	return value
}

func stripRepoPathPrefix(value string, repo model.ProjectRepo) (string, bool) {
	normalized := strings.Trim(strings.ReplaceAll(strings.TrimSpace(value), "\\", "/"), "/")
	if normalized == "" {
		return "", false
	}
	first := normalizeRepoMatchValue(firstPathSegment(normalized))
	for _, key := range repoMatchKeys(repo) {
		if first != key {
			continue
		}
		if idx := strings.Index(normalized, "/"); idx >= 0 {
			return normalized[idx+1:], true
		}
		return "", true
	}
	return normalized, false
}

func normalizeRepoMatchValue(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	value = strings.TrimSuffix(value, ".git")
	value = strings.ReplaceAll(value, "\\", "/")
	value = strings.Trim(value, "/")
	return value
}

func looksLikeAnalysisFilePath(value string) bool {
	value = strings.TrimSpace(value)
	return value != "" && strings.Contains(value, "/") && !strings.ContainsAny(value, "\n\r")
}

func uniqueNonEmpty(values []string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" || seen[value] {
			continue
		}
		seen[value] = true
		out = append(out, value)
	}
	return out
}

func ResolveDefectRepositorySelection(
	db *gorm.DB,
	defect model.Defect,
	agentType string,
	operatorID uint,
) (*DefectRepositorySelection, error) {
	var iteration model.Iteration
	if err := db.Select("id, project_id").Where("id = ?", defect.IterationID).First(&iteration).Error; err != nil {
		return nil, fmt.Errorf("迭代不存在，请检查缺陷关联的迭代是否正确: %w", err)
	}

	projectRepo, iterationBranch, err := ResolveDefectProjectRepo(db, defect, agentType)
	if err != nil {
		return nil, err
	}

	repoAuth, _, err := ResolveRepositoryAuth(db, iteration.ProjectID, projectRepo, agentType, operatorID)
	if err != nil {
		return nil, err
	}
	if repoAuth == nil {
		return nil, fmt.Errorf("请先配置仓库凭证")
	}

	return &DefectRepositorySelection{
		ProjectRepo:     projectRepo,
		Auth:            repoAuth,
		IterationBranch: strings.TrimSpace(iterationBranch),
	}, nil
}

func ResolveDefectRepositorySelectionByRepoID(
	db *gorm.DB,
	defect model.Defect,
	projectRepoID uint,
	agentType string,
	operatorID uint,
) (*DefectRepositorySelection, error) {
	var iteration model.Iteration
	if err := db.Select("id, project_id").Where("id = ?", defect.IterationID).First(&iteration).Error; err != nil {
		return nil, fmt.Errorf("迭代不存在，请检查缺陷关联的迭代是否正确: %w", err)
	}

	var projectRepo model.ProjectRepo
	if err := db.Where("id = ? AND project_id = ?", projectRepoID, iteration.ProjectID).First(&projectRepo).Error; err != nil {
		return nil, fmt.Errorf("修复单元绑定的代码仓库不存在或不属于当前项目: %w", err)
	}
	if !matchAgentType(projectRepo.AgentTypes, agentType) {
		return nil, fmt.Errorf("修复单元绑定的代码仓库未配置 agentType=%s", strings.TrimSpace(agentType))
	}

	iterationBranch := ""
	var iterationRepo model.IterationRepo
	if err := db.Where("iteration_id = ? AND repo_id = ?", defect.IterationID, projectRepo.ID).First(&iterationRepo).Error; err == nil {
		iterationBranch = strings.TrimSpace(iterationRepo.Branch)
	}

	repoAuth, _, err := ResolveRepositoryAuth(db, iteration.ProjectID, projectRepo, agentType, operatorID)
	if err != nil {
		return nil, err
	}
	if repoAuth == nil {
		return nil, fmt.Errorf("请先配置仓库凭证")
	}

	return &DefectRepositorySelection{
		ProjectRepo:     projectRepo,
		Auth:            repoAuth,
		IterationBranch: iterationBranch,
	}, nil
}

func selectIterationProjectRepo(db *gorm.DB, iterationID uint, agentType string) (model.ProjectRepo, string, bool) {
	var iterationRepos []model.IterationRepo
	if err := db.Where("iteration_id = ?", iterationID).Find(&iterationRepos).Error; err != nil {
		return model.ProjectRepo{}, "", false
	}

	var selected model.ProjectRepo
	var selectedBranch string
	found := false
	mismatched := false
	for _, iterationRepo := range iterationRepos {
		if iterationRepo.RepoID == nil {
			continue
		}
		var candidate model.ProjectRepo
		if err := db.First(&candidate, *iterationRepo.RepoID).Error; err != nil {
			continue
		}
		if matchAgentType(candidate.AgentTypes, agentType) {
			selected = candidate
			selectedBranch = iterationRepo.Branch
			found = true
			break
		}
		mismatched = true
	}

	if !found && mismatched {
		return model.ProjectRepo{}, "", false
	}

	return selected, selectedBranch, found
}
