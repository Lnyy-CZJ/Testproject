package ai

import (
	"bug-agent/internal/git"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	ggit "github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing/object"
)

type stubAIClient struct {
	content  string
	contents []string
	calls    int
}

func (s *stubAIClient) Chat(ctx context.Context, req *ChatRequest) (*ChatResponse, error) {
	content := s.content
	if len(s.contents) > 0 {
		idx := s.calls
		if idx >= len(s.contents) {
			idx = len(s.contents) - 1
		}
		content = s.contents[idx]
	}
	s.calls++
	return &ChatResponse{
		Choices: []Choice{{Message: Message{Role: "assistant", Content: content}}},
		Usage:   Usage{PromptTokens: 10, CompletionTokens: 20, TotalTokens: 30},
	}, nil
}

func (s *stubAIClient) ChatStream(ctx context.Context, req *ChatRequest) (<-chan *StreamChunk, error) {
	return nil, nil
}

func seedLocalRepo(t *testing.T, filePath, content string) string {
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

func TestGenerateFixWithMetrics_UsesStepFilePath(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nfunc run() string {\n\treturn \"old\"\n}\n")

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	generator := NewCodeGenerator(&stubAIClient{content: `{"filePath":"src/foo.go","hunks":[{"oldContent":"\treturn \"old\"","newContent":"\treturn \"new\""}]}`})
	report := []byte(`{"affectedFiles":["src/foo.go"],"solution":{"steps":[{"step":1,"action":"更新返回值","filePath":"src/foo.go"}]}}`)

	plan, usage, err := generator.GenerateFixWithMetrics(context.Background(), report, repo)
	if err != nil {
		t.Fatalf("GenerateFixWithMetrics failed: %v", err)
	}
	if len(plan.Steps) != 1 {
		t.Fatalf("expected 1 step, got %d", len(plan.Steps))
	}
	if plan.Steps[0].FilePath != "src/foo.go" {
		t.Fatalf("file path = %q", plan.Steps[0].FilePath)
	}
	if plan.Steps[0].CodeChange == nil {
		t.Fatal("expected code change")
	}
	if !strings.Contains(plan.Steps[0].CodeChange.NewContent, "new") {
		t.Fatalf("expected new content to contain updated value, got %q", plan.Steps[0].CodeChange.NewContent)
	}
	if usage.TotalTokens == 0 {
		t.Fatalf("expected usage to be recorded")
	}
}

func TestGenerateFixWithMetrics_ReturnsErrorWhenNoApplicableCodeChangesGenerated(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nfunc run() string {\n\treturn \"same\"\n}\n")

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	generator := NewCodeGenerator(&stubAIClient{content: `{"filePath":"src/foo.go","hunks":[],"reason":"未发现可安全修改的代码片段"}`})
	report := []byte(`{"affectedFiles":["src/foo.go"],"solution":{"steps":[{"step":1,"action":"保持不变","filePath":"src/foo.go"}]}}`)

	_, usage, err := generator.GenerateFixWithMetrics(context.Background(), report, repo)
	if err == nil {
		t.Fatal("expected GenerateFixWithMetrics to fail when AI returns unchanged code")
	}
	if !strings.Contains(err.Error(), "未能生成有效的代码变更") &&
		!strings.Contains(err.Error(), "no applicable code changes generated") &&
		!strings.Contains(err.Error(), "file-level fix step failed") {
		t.Fatalf("unexpected error: %v", err)
	}
	if usage.TotalTokens == 0 {
		t.Fatal("expected failed AI generation usage to be preserved")
	}
}

func TestGenerateFixWithMetrics_RejectsInvalidGoPatchBeforeApply(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nimport \"fmt\"\n\nfunc run() string {\n\treturn fmt.Sprint(\"old\")\n}\n")

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	generator := NewCodeGenerator(&stubAIClient{content: `{"filePath":"src/foo.go","hunks":[{"oldContent":"import \"fmt\"","newContent":"import (\n\t\"fmt\"\n\tlog\n)"}]}`})
	report := []byte(`{"affectedFiles":["src/foo.go"],"solution":{"steps":[{"step":1,"action":"增加日志","filePath":"src/foo.go"}]}}`)

	_, _, err = generator.GenerateFixWithMetrics(context.Background(), report, repo)
	if err == nil {
		t.Fatal("expected invalid Go patch to be rejected")
	}
	if !strings.Contains(err.Error(), "generated Go code is invalid") {
		t.Fatalf("unexpected error: %v", err)
	}
	updated, readErr := repo.ReadFile("src/foo.go")
	if readErr != nil {
		t.Fatalf("read file failed: %v", readErr)
	}
	if strings.Contains(updated, "\tlog") {
		t.Fatalf("invalid generated code was applied: %s", updated)
	}
}

func TestGenerateFixWithMetrics_RetriesMalformedPatchJSON(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nfunc run() string {\n\treturn \"old\"\n}\n")

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	client := &stubAIClient{contents: []string{
		`{"filePath":"src/foo.go","hunks":[`,
		`{"filePath":"src/foo.go","hunks":[{"oldContent":"return \"old\"","newContent":"return \"new\""}]}`,
	}}
	generator := NewCodeGenerator(client)
	report := []byte(`{"affectedFiles":["src/foo.go"],"solution":{"steps":[{"step":1,"action":"更新返回值","filePath":"src/foo.go"}]}}`)

	plan, usage, err := generator.GenerateFixWithMetrics(context.Background(), report, repo)
	if err != nil {
		t.Fatalf("GenerateFixWithMetrics failed after retry: %v", err)
	}
	if client.calls != 2 {
		t.Fatalf("calls = %d, want 2", client.calls)
	}
	if usage.TotalTokens != 60 {
		t.Fatalf("total tokens = %d, want 60", usage.TotalTokens)
	}
	if len(plan.Steps) != 1 || plan.Steps[0].CodeChange == nil {
		t.Fatalf("expected code change after retry, got %+v", plan.Steps)
	}
}

func TestGenerateFixWithMetrics_UsesSingleAffectedFileWhenStepHasNoFilePath(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nfunc run() string {\n\treturn \"same\"\n}\n")

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	generator := NewCodeGenerator(&stubAIClient{content: `{"filePath":"src/foo.go","hunks":[{"oldContent":"\treturn \"same\"","newContent":"\treturn \"fixed\""}]}`})
	report := []byte(`{"affectedFiles":["src/foo.go"],"solution":{"steps":[{"step":1,"action":"根据分析思路修复缺陷","rawGuidance":"修改返回值"}]}}`)

	plan, _, err := generator.GenerateFixWithMetrics(context.Background(), report, repo)
	if err != nil {
		t.Fatalf("GenerateFixWithMetrics failed: %v", err)
	}
	if len(plan.Steps) != 1 || plan.Steps[0].FilePath != "src/foo.go" {
		t.Fatalf("expected fallback file target src/foo.go, got %+v", plan.Steps)
	}
}

func TestGenerateFixWithMetrics_UsesSingleAffectedFileObjectWhenStepHasNoFilePath(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nfunc run() string {\n\treturn \"same\"\n}\n")

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	generator := NewCodeGenerator(&stubAIClient{content: `{"filePath":"src/foo.go","hunks":[{"oldContent":"\treturn \"same\"","newContent":"\treturn \"fixed\""}]}`})
	report := []byte(`{"affectedFiles":[{"repoHint":"api","path":"src/foo.go"}],"solution":{"steps":[{"step":1,"action":"根据分析思路修复缺陷","rawGuidance":"修改返回值"}]}}`)

	plan, _, err := generator.GenerateFixWithMetrics(context.Background(), report, repo)
	if err != nil {
		t.Fatalf("GenerateFixWithMetrics failed: %v", err)
	}
	if len(plan.Steps) != 1 || plan.Steps[0].FilePath != "src/foo.go" {
		t.Fatalf("expected fallback file target src/foo.go, got %+v", plan.Steps)
	}
}

func TestGenerateFixWithMetrics_ReturnsClearErrorWhenAnalysisHasNoFileTargets(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nfunc run() string {\n\treturn \"same\"\n}\n")

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	generator := NewCodeGenerator(&stubAIClient{content: `{"filePath":"src/foo.go","hunks":[{"oldContent":"package main","newContent":"package main"}]}`})
	report := []byte(`{"affectedFiles":[],"solution":{"steps":[{"step":1,"action":"根据分析思路修复缺陷","rawGuidance":"未检索到相关文件"}]}}`)

	_, _, err = generator.GenerateFixWithMetrics(context.Background(), report, repo)
	if err == nil {
		t.Fatal("expected GenerateFixWithMetrics to fail when analysis has no file-level targets")
	}
	if !strings.Contains(err.Error(), "analysis report has no file-level fix target") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestGenerateFixWithMetrics_FailsWhenAnyFileLevelStepCannotGenerateChange(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nfunc run() string {\n\treturn \"old\"\n}\n")

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	generator := NewCodeGenerator(&stubAIClient{content: `{"filePath":"src/foo.go","hunks":[{"oldContent":"\treturn \"old\"","newContent":"\treturn \"new\""}]}`})
	report := []byte(`{"affectedFiles":["src/foo.go","src/missing.go"],"solution":{"steps":[{"step":1,"action":"更新返回值","filePath":"src/foo.go"},{"step":2,"action":"修复缺失文件","filePath":"src/missing.go"}]}}`)

	_, _, err = generator.GenerateFixWithMetrics(context.Background(), report, repo)
	if err == nil {
		t.Fatal("expected GenerateFixWithMetrics to fail when a file-level step cannot be applied")
	}
	if !strings.Contains(err.Error(), "file-level fix step failed") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestGenerateFixWithMetrics_AllowsPartialNoApplicableFileStep(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nfunc run() string {\n\treturn \"old\"\n}\n")
	barPath := filepath.Join(remoteDir, "src/bar.go")
	if err := os.WriteFile(barPath, []byte("package main\n\nfunc ready() bool {\n\treturn true\n}\n"), 0o644); err != nil {
		t.Fatalf("write second file failed: %v", err)
	}
	rawRepo, err := ggit.PlainOpen(remoteDir)
	if err != nil {
		t.Fatalf("open repo failed: %v", err)
	}
	worktree, err := rawRepo.Worktree()
	if err != nil {
		t.Fatalf("worktree failed: %v", err)
	}
	if _, err := worktree.Add("src/bar.go"); err != nil {
		t.Fatalf("add second file failed: %v", err)
	}
	if _, err := worktree.Commit("add bar", &ggit.CommitOptions{
		Author: &object.Signature{Name: "tester", Email: "tester@example.com", When: time.Now()},
	}); err != nil {
		t.Fatalf("commit second file failed: %v", err)
	}

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	generator := NewCodeGenerator(&stubAIClient{contents: []string{
		`{"filePath":"src/foo.go","hunks":[{"oldContent":"\treturn \"old\"","newContent":"\treturn \"new\""}]}`,
		`{"filePath":"src/bar.go","hunks":[],"reason":"当前代码已满足要求"}`,
	}})
	report := []byte(`{"affectedFiles":["src/foo.go","src/bar.go"],"solution":{"steps":[{"step":1,"action":"更新返回值","filePath":"src/foo.go"},{"step":2,"action":"确认无需修改","filePath":"src/bar.go"}]}}`)

	plan, _, err := generator.GenerateFixWithMetrics(context.Background(), report, repo)
	if err != nil {
		t.Fatalf("GenerateFixWithMetrics should keep valid patches when another file is no-op: %v", err)
	}
	changes := 0
	warnings := 0
	for _, step := range plan.Steps {
		if step.CodeChange != nil {
			changes++
		}
		if step.Status == "warning" {
			warnings++
		}
	}
	if changes != 1 || warnings != 1 {
		t.Fatalf("expected one code change and one no-op warning, got changes=%d warnings=%d steps=%+v", changes, warnings, plan.Steps)
	}
}

func TestApplyChangeAppliesHunksWithoutFullFileStaleCheck(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nfunc run() string {\n\treturn \"old\"\n}\n")

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	generator := NewCodeGenerator(&stubAIClient{})
	err = generator.ApplyChange(repo, &CodeChange{
		FilePath:   "src/foo.go",
		OldContent: "package main\n\nfunc run() string {\n\treturn \"stale\"\n}\n",
		NewContent: "package main\n\nfunc run() string {\n\treturn \"new\"\n}\n",
		Hunks: []CodeHunk{{
			OldContent: "\treturn \"old\"",
			NewContent: "\treturn \"new\"",
		}},
	})
	if err != nil {
		t.Fatalf("expected hunk apply to ignore stale full-file old content: %v", err)
	}

	updated, err := repo.ReadFile("src/foo.go")
	if err != nil {
		t.Fatalf("read updated file failed: %v", err)
	}
	if !strings.Contains(updated, `return "new"`) {
		t.Fatalf("expected updated file to contain new return value, got: %s", updated)
	}
}

func TestApplyChangeRejectsUnmatchedHunkContext(t *testing.T) {
	remoteDir := seedLocalRepo(t, "src/foo.go", "package main\n\nfunc run() string {\n\treturn \"old\"\n}\n")

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	generator := NewCodeGenerator(&stubAIClient{})
	err = generator.ApplyChange(repo, &CodeChange{
		FilePath: "src/foo.go",
		Hunks: []CodeHunk{{
			OldContent: "\treturn \"missing\"",
			NewContent: "\treturn \"new\"",
		}},
	})
	if err == nil {
		t.Fatal("expected unmatched hunk context to be rejected")
	}
	if !strings.Contains(err.Error(), "hunk context must match exactly once") {
		t.Fatalf("unexpected error: %v", err)
	}
}
