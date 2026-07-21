package adk

import (
	gitrepo "bug-agent/internal/git"
	bugmodel "bug-agent/internal/model"
	"bug-agent/internal/util"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
	"unicode/utf8"

	ggit "github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing/object"
	adkmodel "google.golang.org/adk/model"
	"google.golang.org/adk/session"
	"google.golang.org/genai"
)

func TestNormalizeAnalysisFieldNames_DataPathSummary(t *testing.T) {
	analysis := map[string]interface{}{
		"data_path_summary": "前端→API→后端→响应→前端状态→UI，断裂点在 service.go",
		"findings": []interface{}{
			map[string]interface{}{
				"file_path": "server/internal/service/quality_insights.go",
				"evidence":  "GetOverview 函数体被截断",
				"severity":  "critical",
			},
		},
		"riskSummary": "待补充",
		"solution": map[string]interface{}{
			"steps": []interface{}{
				map[string]interface{}{"action": "修复 GetOverview", "rawGuidance": "详细指导"},
			},
		},
	}

	normalizeAnalysisFieldNames(analysis)

	if rc, ok := analysis["rootCause"].(string); !ok || rc == "" {
		t.Errorf("rootCause should be set from data_path_summary, got %v", analysis["rootCause"])
	} else if rc != "前端→API→后端→响应→前端状态→UI，断裂点在 service.go" {
		t.Errorf("rootCause = %q, want data_path_summary value", rc)
	}

	af, ok := analysis["affectedFiles"].([]string)
	if !ok {
		if afInterface, ok2 := analysis["affectedFiles"].([]interface{}); ok2 {
			af = make([]string, len(afInterface))
			for i, v := range afInterface {
				af[i], _ = v.(string)
			}
		}
	}
	if len(af) == 0 || af[0] != "server/internal/service/quality_insights.go" {
		t.Errorf("affectedFiles = %v, want [server/internal/service/quality_insights.go]", analysis["affectedFiles"])
	}

	rl, ok := analysis["riskLevel"].(string)
	if !ok || rl != "high" {
		t.Errorf("riskLevel = %v, want high (from critical severity)", analysis["riskLevel"])
	}

	if _, ok := analysis["findings"]; ok {
		t.Error("findings should be removed after normalization")
	}
	if _, ok := analysis["data_path_summary"]; ok {
		t.Error("data_path_summary should be removed after normalization")
	}
}

func TestCleanupStreamCleansRepositoryAfterStreamLifecycle(t *testing.T) {
	remoteDir := seedADKLocalRepo(t, "src/main.go", "package main\n")

	cloneCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	repo, err := gitrepo.NewRepository(cloneCtx, gitrepo.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}

	if _, err := repo.ReadFile("src/main.go"); err != nil {
		t.Fatalf("expected repo readable before cleanup: %v", err)
	}

	svc := &ADKAnalysisService{}
	svc.cleanupStream(streamPostProcessContext{repo: repo})

	if _, err := repo.ReadFile("src/main.go"); err == nil {
		t.Fatal("expected repo to be cleaned when stream lifecycle ends")
	}
}

func seedADKLocalRepo(t *testing.T, filePath, content string) string {
	t.Helper()

	dir := t.TempDir()
	repo, err := ggit.PlainInit(dir, false)
	if err != nil {
		t.Fatalf("init repo failed: %v", err)
	}

	fullPath := filepath.Join(dir, filepath.FromSlash(filePath))
	if err := os.MkdirAll(filepath.Dir(fullPath), 0o755); err != nil {
		t.Fatalf("mkdir failed: %v", err)
	}
	if err := os.WriteFile(fullPath, []byte(content), 0o644); err != nil {
		t.Fatalf("write file failed: %v", err)
	}

	worktree, err := repo.Worktree()
	if err != nil {
		t.Fatalf("worktree failed: %v", err)
	}
	if _, err := worktree.Add(filePath); err != nil {
		t.Fatalf("add failed: %v", err)
	}
	if _, err := worktree.Commit("init", &ggit.CommitOptions{
		Author: &object.Signature{Name: "tester", Email: "tester@example.com", When: time.Now()},
	}); err != nil {
		t.Fatalf("commit failed: %v", err)
	}

	return dir
}

func TestNormalizeAnalysisFieldNames_FindingsWithoutFilePath(t *testing.T) {
	analysis := map[string]interface{}{
		"findings": []interface{}{
			map[string]interface{}{
				"evidence": "nil pointer dereference",
				"severity": "high",
			},
		},
	}

	normalizeAnalysisFieldNames(analysis)

	if rc, ok := analysis["rootCause"].(string); !ok || rc != "nil pointer dereference" {
		t.Errorf("rootCause = %v, want 'nil pointer dereference'", analysis["rootCause"])
	}
	if rl, ok := analysis["riskLevel"].(string); !ok || rl != "high" {
		t.Errorf("riskLevel = %v, want high", analysis["riskLevel"])
	}
}

func TestNormalizeAnalysisFieldNames_ExistingRootCauseNotOverwritten(t *testing.T) {
	analysis := map[string]interface{}{
		"rootCause":         "existing root cause",
		"data_path_summary": "this should not overwrite",
		"findings": []interface{}{
			map[string]interface{}{
				"evidence": "evidence from findings",
				"severity": "medium",
			},
		},
	}

	normalizeAnalysisFieldNames(analysis)

	if rc, ok := analysis["rootCause"].(string); !ok || rc != "existing root cause" {
		t.Errorf("rootCause = %v, want 'existing root cause' (not overwritten)", analysis["rootCause"])
	}
}

func TestNormalizeAnalysisFieldNames_SnakeCaseAliases(t *testing.T) {
	analysis := map[string]interface{}{
		"root_cause":     "snake case cause",
		"affected_files": []interface{}{"a.go", "b.go"},
		"risk_level":     "high",
		"risk_summary":   "snake case summary",
	}

	normalizeAnalysisFieldNames(analysis)

	if rc, ok := analysis["rootCause"].(string); !ok || rc != "snake case cause" {
		t.Errorf("rootCause = %v, want 'snake case cause'", analysis["rootCause"])
	}
	if rl, ok := analysis["riskLevel"].(string); !ok || rl != "high" {
		t.Errorf("riskLevel = %v, want high", analysis["riskLevel"])
	}
	if _, ok := analysis["root_cause"]; ok {
		t.Error("root_cause should be removed after alias mapping")
	}
}

func TestCollectReferencedFilesReadsObjectFileRefsAndStepAliases(t *testing.T) {
	analysis := map[string]interface{}{
		"affectedFiles": []interface{}{
			map[string]interface{}{"repoHint": "admin", "path": "internal/router.go"},
		},
		"solution": map[string]interface{}{
			"steps": []interface{}{
				map[string]interface{}{"targetFile": "internal/service.go", "action": "fix"},
			},
		},
	}

	files := collectReferencedFiles(analysis)
	if len(files) != 2 {
		t.Fatalf("expected 2 referenced files, got %#v", files)
	}
	if files[0] != "internal/router.go" || files[1] != "internal/service.go" {
		t.Fatalf("unexpected referenced files: %#v", files)
	}
}

func TestNormalizeAnalysisFieldNames_EmptyRiskSummaryRemoved(t *testing.T) {
	analysis := map[string]interface{}{
		"riskSummary": "待补充",
	}

	normalizeAnalysisFieldNames(analysis)

	if _, ok := analysis["riskSummary"]; ok {
		t.Error("empty riskSummary '待补充' should be removed")
	}
}

func TestNormalizeAnalysisFieldNames_FixStrategyToSolution(t *testing.T) {
	analysis := map[string]interface{}{
		"fixStrategy": map[string]interface{}{
			"approach": "fix approach description",
			"steps": []interface{}{
				map[string]interface{}{"action": "step 1"},
			},
		},
	}

	normalizeAnalysisFieldNames(analysis)

	if rc, ok := analysis["rootCause"].(string); !ok || rc != "fix approach description" {
		t.Errorf("rootCause = %v, want 'fix approach description'", analysis["rootCause"])
	}
	if _, ok := analysis["solution"]; !ok {
		t.Error("solution should be set from fixStrategy")
	}
	if _, ok := analysis["fixStrategy"]; ok {
		t.Error("fixStrategy should be removed")
	}
}

func TestNormalizeAnalysisFieldNames_RealExplorerOutput(t *testing.T) {
	rawJSON := `{
		"thinking": "需要追踪前端到后端的完整数据通路",
		"findings": [
			{"file_path": "server/internal/service/quality_insights.go", "evidence": "GetOverview 函数体被截断，显示 '... (truncated)'", "severity": "critical"},
			{"file_path": "web/src/pages/QualityInsights.tsx", "evidence": "组件调用 API 失败时未处理错误状态", "severity": "high"}
		],
		"data_path_summary": "前端→API→后端→响应→前端状态→UI，断裂点在 server/internal/service/quality_insights.go 的 GetOverview 函数实现不完整。",
		"riskSummary": "待补充",
		"solution": {
			"steps": [
				{"action": "根据分析思路修复缺陷", "rawGuidance": "根据提供的代码证据，可以定位到缺陷位于服务层。"}
			]
		}
	}`

	var analysis map[string]interface{}
	if err := json.Unmarshal([]byte(rawJSON), &analysis); err != nil {
		t.Fatalf("Failed to parse JSON: %v", err)
	}

	normalizeAnalysisFieldNames(analysis)

	if rc, ok := analysis["rootCause"].(string); !ok || rc == "" {
		t.Errorf("rootCause should be set, got %v", analysis["rootCause"])
	}

	afRaw := analysis["affectedFiles"]
	var af []string
	switch v := afRaw.(type) {
	case []string:
		af = v
	case []interface{}:
		for _, item := range v {
			if s, ok := item.(string); ok {
				af = append(af, s)
			}
		}
	}
	if len(af) < 2 {
		t.Errorf("affectedFiles should have at least 2 entries, got %v", af)
	}

	if rl, ok := analysis["riskLevel"].(string); !ok || rl != "high" {
		t.Errorf("riskLevel = %v, want high (from critical)", analysis["riskLevel"])
	}

	if _, ok := analysis["findings"]; ok {
		t.Error("findings should be removed")
	}
	if _, ok := analysis["data_path_summary"]; ok {
		t.Error("data_path_summary should be removed")
	}
}

func TestNormalizeAnalysisFieldNames_PromotesFilesAndSummaryFromReasoningText(t *testing.T) {
	analysis := map[string]interface{}{
		"riskSummary": "待补充",
		"rootCause":   "",
		"thinking": "通过搜索和读取代码，发现质量问题概览的后端处理位于 `server/internal/handler/quality_insights.go`，" +
			"而前端页面在 `web/src/pages/projects/ProjectQualityInsights.tsx`。关键文件需要继续确认API处理逻辑。",
		"solution": map[string]interface{}{
			"steps": []interface{}{
				map[string]interface{}{
					"step":        1,
					"action":      "根据分析思路修复缺陷",
					"rawGuidance": "检查 `server/internal/handler/quality_insights.go` 和 `web/src/pages/projects/ProjectQualityInsights.tsx` 的请求响应是否匹配。",
				},
			},
		},
	}

	normalizeAnalysisFieldNames(analysis)

	files := util.GetStringSliceField(analysis["affectedFiles"])
	if len(files) != 2 {
		t.Fatalf("expected 2 affected files, got %#v", files)
	}
	if files[0] != "server/internal/handler/quality_insights.go" || files[1] != "web/src/pages/projects/ProjectQualityInsights.tsx" {
		t.Fatalf("unexpected affected files: %#v", files)
	}
	if rootCause, ok := analysis["rootCause"].(string); !ok || !strings.Contains(rootCause, "server/internal/handler/quality_insights.go") {
		t.Fatalf("expected rootCause to be derived from reasoning text, got %#v", analysis["rootCause"])
	}
	if riskSummary, ok := analysis["riskSummary"].(string); !ok || riskSummary == "" || riskSummary == "待补充" {
		t.Fatalf("expected riskSummary to be generated, got %#v", analysis["riskSummary"])
	}
}

func TestBuildRiskSummary_TruncatesMultibyteTextSafely(t *testing.T) {
	rootCause := strings.Repeat("质量情报概览的 API 路由未在 server/internal/router/router.go 中注册，导致前端无法加载数据。", 4)

	summary := buildRiskSummary(rootCause, "high")

	if !utf8.ValidString(summary) {
		t.Fatalf("risk summary must remain valid UTF-8, got %q", summary)
	}
	if strings.ContainsRune(summary, utf8.RuneError) {
		t.Fatalf("risk summary must not contain replacement characters, got %q", summary)
	}
	if !strings.HasPrefix(summary, "[HIGH] ") {
		t.Fatalf("expected risk prefix, got %q", summary)
	}
	if !strings.HasSuffix(summary, "...") {
		t.Fatalf("expected truncated summary suffix, got %q", summary)
	}
}

func TestADKExtractKeywords_ExpandsQualityInsightsAliases(t *testing.T) {
	keywords := adkExtractKeywords("质量情报-获取质量情报概览失败")
	got := map[string]bool{}
	for _, keyword := range keywords {
		got[keyword] = true
	}
	for _, want := range []string{"质量情报", "获取质量情报概览失败", "quality", "insights", "quality_insights", "overview", "getoverview"} {
		if !got[want] {
			t.Fatalf("expected keyword %q in %v", want, keywords)
		}
	}
}

func TestADKAnalysisNeedsEvidenceRepair_RequiresAffectedFilesWhenEvidenceExists(t *testing.T) {
	payload := map[string]interface{}{
		"rootCause": "missed repo evidence",
		"solution": map[string]interface{}{
			"steps": []interface{}{
				map[string]interface{}{"step": 1, "action": "fix matched handler"},
			},
		},
	}
	relatedFiles := []string{"src/a.ts", "src/b.ts"}

	needsRepair, reason := analysisNeedsEvidenceRepair(payload, relatedFiles)
	if !needsRepair {
		t.Fatal("expected repair to be required when repo evidence exists but affectedFiles is empty")
	}
	if reason != "missing_affected_files" {
		t.Fatalf("expected missing_affected_files, got %q", reason)
	}
}

func TestNormalizeAnalysisByRepoEvidencePromotesCandidateFilesToActionableScope(t *testing.T) {
	svc := &ADKAnalysisService{}
	payload := map[string]interface{}{
		"rootCause": "missed repo evidence",
		"solution": map[string]interface{}{
			"steps": []interface{}{
				map[string]interface{}{"step": 1, "action": "fix matched handler"},
			},
		},
	}

	normalized, telemetry := svc.normalizeAnalysisByRepoEvidence(nil, payload, []string{"src/a.ts", "src/b.ts"}, "", bugmodel.ProjectAIConfig{})
	if !telemetry.Repaired {
		t.Fatal("expected repair telemetry")
	}
	if files := util.GetStringSliceField(normalized["affectedFiles"]); len(files) != 2 || files[0] != "src/a.ts" {
		t.Fatalf("affectedFiles = %#v, want candidate files", files)
	}
	if evidenceFiles := util.GetStringSliceField(normalized["evidenceFiles"]); len(evidenceFiles) != 2 {
		t.Fatalf("evidenceFiles = %#v, want candidate files", evidenceFiles)
	}
	if !adkAnalysisHasFixSteps(mustMarshalRaw(t, normalized)) {
		t.Fatalf("normalized analysis should be actionable: %#v", normalized)
	}
}

func mustMarshalRaw(t *testing.T, value interface{}) json.RawMessage {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("marshal raw: %v", err)
	}
	return raw
}

func TestADKAnalysisHasActionableFixStepsRejectsGenericGuidance(t *testing.T) {
	raw := json.RawMessage(`{
		"affectedFiles": [],
		"solution": {
			"steps": [
				{"step": 1, "action": "根据分析思路修复缺陷", "rawGuidance": "未检索到相关文件"}
			]
		}
	}`)

	if adkAnalysisHasFixSteps(raw) {
		t.Fatal("generic guidance without affectedFiles or filePath should not be actionable")
	}
}

func TestADKAnalysisHasActionableFixStepsRejectsAffectedFilesWithoutFileStep(t *testing.T) {
	raw := json.RawMessage(`{
		"affectedFiles": ["server/internal/service/quality_insights.go"],
		"solution": {
			"steps": [
				{"step": 1, "action": "根据影响文件修复缺陷"}
			]
		}
	}`)

	if adkAnalysisHasFixSteps(raw) {
		t.Fatal("affectedFiles without file-level solution step should not be actionable")
	}
}

func TestADKAnalysisHasActionableFixStepsAcceptsFileLevelStep(t *testing.T) {
	raw := json.RawMessage(`{
		"affectedFiles": ["server/internal/service/quality_insights.go"],
		"solution": {
			"steps": [
				{"step": 1, "action": "修复概览查询", "filePath": "server/internal/service/quality_insights.go"}
			]
		}
	}`)

	if !adkAnalysisHasFixSteps(raw) {
		t.Fatal("file-level step should be actionable")
	}
}

func TestExtractFinalAnalysisJSONPrefersAnalyzerOutputOverExplorerOutput(t *testing.T) {
	fullText := strings.Join([]string{
		"```json\n" + `{"thinking":"explorer only","findings":[{"file_path":"server/internal/handler/a.go","evidence":"read code","severity":"high"}],"data_path_summary":"explorer summary"}` + "\n```",
		"```json\n" + `{"rootCause":"最终根因","affectedFiles":["server/internal/service/b.go"],"riskLevel":"high","solution":{"steps":[{"step":1,"action":"修复服务逻辑","filePath":"server/internal/service/b.go"}]}}` + "\n```",
	}, "\n\n")

	rawJSON, err := extractFinalAnalysisJSONObjectFromText(fullText)
	if err != nil {
		t.Fatalf("extract final analysis json failed: %v", err)
	}

	var payload map[string]interface{}
	if err := json.Unmarshal([]byte(rawJSON), &payload); err != nil {
		t.Fatalf("unmarshal extracted json failed: %v", err)
	}
	if got := util.GetStringField(payload, "rootCause"); got != "最终根因" {
		t.Fatalf("rootCause = %q, want final analyzer output", got)
	}
	if _, ok := payload["findings"]; ok {
		t.Fatalf("expected analyzer JSON, got explorer payload: %#v", payload)
	}
}

func TestCollectAnalysisEventTextPrefersAnalyzerAuthor(t *testing.T) {
	events := []*session.Event{
		{
			Author: "code_explorer",
			LLMResponse: adkmodel.LLMResponse{
				Content: &genai.Content{Parts: []*genai.Part{{
					Text: `{"rootCause":"explorer summary","affectedFiles":["server/internal/handler/a.go"]}`,
				}}},
			},
		},
		{
			Author: "backend_analyzer",
			LLMResponse: adkmodel.LLMResponse{
				Content: &genai.Content{Parts: []*genai.Part{{
					Text: `{"rootCause":"final analyzer","affectedFiles":["server/internal/service/b.go"],"riskLevel":"high","solution":{"steps":[{"filePath":"server/internal/service/b.go","action":"fix"}]}}`,
				}}},
			},
		},
	}

	text := collectAnalysisEventText(events, "backend")
	if !strings.Contains(text, "final analyzer") {
		t.Fatalf("analysis text = %q, want analyzer output", text)
	}
	if strings.Contains(text, "explorer summary") {
		t.Fatalf("analysis text should not include explorer output: %q", text)
	}
}

func TestCollectEventTextWithAnalysisKeepsMaxTokenUsage(t *testing.T) {
	var fullText, analysisText string
	var totalTokens, promptTokens, completionTokens int

	collectEventTextWithAnalysis(&session.Event{
		Author: "backend_analyzer",
		LLMResponse: adkmodel.LLMResponse{
			Content: &genai.Content{Parts: []*genai.Part{{Text: `{"rootCause":"first"}`}}},
			UsageMetadata: &genai.GenerateContentResponseUsageMetadata{
				PromptTokenCount:     40,
				CandidatesTokenCount: 20,
				TotalTokenCount:      60,
			},
		},
	}, &fullText, &analysisText, "backend", &totalTokens, &promptTokens, &completionTokens)

	collectEventTextWithAnalysis(&session.Event{
		Author: "backend_analyzer",
		LLMResponse: adkmodel.LLMResponse{
			Content: &genai.Content{Parts: []*genai.Part{{Text: `{"rootCause":"second"}`}}},
			UsageMetadata: &genai.GenerateContentResponseUsageMetadata{
				PromptTokenCount:     10,
				CandidatesTokenCount: 5,
				TotalTokenCount:      15,
			},
		},
	}, &fullText, &analysisText, "backend", &totalTokens, &promptTokens, &completionTokens)

	if totalTokens != 60 || promptTokens != 40 || completionTokens != 20 {
		t.Fatalf("usage = total:%d prompt:%d completion:%d, want max usage 60/40/20", totalTokens, promptTokens, completionTokens)
	}
	if !strings.Contains(analysisText, "first") || !strings.Contains(analysisText, "second") {
		t.Fatalf("analysisText should include analyzer chunks, got %q", analysisText)
	}
}
