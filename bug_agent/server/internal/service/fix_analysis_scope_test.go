package service

import (
	"bug-agent/internal/model"
	"encoding/json"
	"testing"
)

func TestBuildRepoScopedAnalysisInputFiltersAndStripsRepoPrefixedPaths(t *testing.T) {
	report := model.AnalysisReport{
		Analysis: `{"affectedFiles":["api/internal/server.go","admin/internal/router.go"],"solution":{"steps":[{"action":"fix api","filePath":"api/internal/server.go"},{"action":"fix admin","filePath":"admin/internal/router.go"}]}}`,
	}
	repo := model.ProjectRepo{Name: "admin", RepoURL: "https://example.com/admin.git"}

	scoped := buildRepoScopedAnalysisInput(report, repo)
	var payload map[string]interface{}
	if err := json.Unmarshal(scoped, &payload); err != nil {
		t.Fatalf("unmarshal scoped payload failed: %v", err)
	}

	files := payload["affectedFiles"].([]interface{})
	if len(files) != 1 || files[0] != "internal/router.go" {
		t.Fatalf("expected scoped affected file internal/router.go, got %#v", files)
	}
	solution := payload["solution"].(map[string]interface{})
	steps := solution["steps"].([]interface{})
	if len(steps) != 1 {
		t.Fatalf("expected one scoped step, got %d", len(steps))
	}
	step := steps[0].(map[string]interface{})
	if step["filePath"] != "internal/router.go" {
		t.Fatalf("expected stripped step path internal/router.go, got %#v", step["filePath"])
	}
}

func TestBuildRepoScopedAnalysisInputKeepsUnprefixedSingleRepoPaths(t *testing.T) {
	report := model.AnalysisReport{
		Analysis: `{"affectedFiles":["internal/router.go"],"solution":{"steps":[{"action":"fix","filePath":"internal/router.go"}]}}`,
	}
	repo := model.ProjectRepo{Name: "admin", RepoURL: "https://example.com/admin.git"}

	scoped := buildRepoScopedAnalysisInput(report, repo)
	var payload map[string]interface{}
	if err := json.Unmarshal(scoped, &payload); err != nil {
		t.Fatalf("unmarshal scoped payload failed: %v", err)
	}
	files := payload["affectedFiles"].([]interface{})
	if len(files) != 1 || files[0] != "internal/router.go" {
		t.Fatalf("expected unprefixed affected file to be preserved, got %#v", files)
	}
}
