package git

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	ggit "github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing/object"
	githttp "github.com/go-git/go-git/v5/plumbing/transport/http"
)

func TestBuildHTTPAuthMethod(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name     string
		auth     Auth
		wantNil  bool
		wantUser string
		wantPass string
	}{
		{
			name:    "empty auth returns nil",
			auth:    Auth{},
			wantNil: true,
		},
		{
			name:     "token auth maps to basic auth",
			auth:     Auth{Token: "token-123"},
			wantUser: "oauth2",
			wantPass: "token-123",
		},
		{
			name:     "username password maps to basic auth",
			auth:     Auth{Username: "demo", Password: "secret"},
			wantUser: "demo",
			wantPass: "secret",
		},
		{
			name:     "token with explicit username keeps username",
			auth:     Auth{Username: "git", Token: "token-456"},
			wantUser: "git",
			wantPass: "token-456",
		},
	}

	for _, tt := range tests {
		tt := tt
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()

			method := buildHTTPAuthMethod(tt.auth)
			if tt.wantNil {
				if method != nil {
					t.Fatalf("expected nil auth method, got %T", method)
				}
				return
			}

			if method == nil {
				t.Fatal("expected non-nil auth method")
			}
			basicAuth := method
			if _, ok := interface{}(basicAuth).(*githttp.BasicAuth); !ok {
				t.Fatalf("expected *http.BasicAuth, got %T", method)
			}
			if basicAuth.Username != tt.wantUser {
				t.Fatalf("username = %q, want %q", basicAuth.Username, tt.wantUser)
			}
			if basicAuth.Password != tt.wantPass {
				t.Fatalf("password = %q, want %q", basicAuth.Password, tt.wantPass)
			}
		})
	}
}

func TestRunBuild_PreservesFailingBuildOutput(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "Makefile"), []byte("build:\n\t@echo failing-build-output\n\t@exit 2\n"), 0o644); err != nil {
		t.Fatalf("write Makefile failed: %v", err)
	}

	r := &Repository{workDir: dir}
	result, err := r.RunBuild([]string{"main.go"})
	if err != nil {
		t.Fatalf("RunBuild returned error: %v", err)
	}
	if result.Success {
		t.Fatal("expected build to fail")
	}
	if !strings.Contains(result.Output, "failing-build-output") {
		t.Fatalf("build output = %q, want failing-build-output", result.Output)
	}
}

func TestRunBuild_FindsNearestBuildManifestForChangedFile(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	webDir := filepath.Join(dir, "apps", "web")
	if err := os.MkdirAll(filepath.Join(webDir, "src"), 0o755); err != nil {
		t.Fatalf("create nested app failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(webDir, "Makefile"), []byte("build:\n\t@echo nested-build-ok\n"), 0o644); err != nil {
		t.Fatalf("write nested Makefile failed: %v", err)
	}

	r := &Repository{workDir: dir}
	result, err := r.RunBuild([]string{"apps/web/src/App.tsx"})
	if err != nil {
		t.Fatalf("RunBuild returned error: %v", err)
	}
	if result.Skipped {
		t.Fatal("expected nested build target to run")
	}
	if !result.Success {
		t.Fatalf("expected build to pass, output: %s", result.Output)
	}
	if !strings.Contains(result.Output, "nested-build-ok") {
		t.Fatalf("build output = %q, want nested-build-ok", result.Output)
	}
}

func TestRunBuild_ReportsMissingBuildToolAsUnverified(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "package.json"), []byte(`{"scripts":{"build":"echo ok"}}`), 0o644); err != nil {
		t.Fatalf("write package.json failed: %v", err)
	}

	r := &Repository{workDir: dir}
	result, err := r.runBuildWithPath([]string{"src/App.tsx"}, "/definitely/missing")
	if err != nil {
		t.Fatalf("RunBuild returned error: %v", err)
	}
	if result.Success {
		t.Fatal("missing build tool should not be treated as successful verification")
	}
	if result.SkipReason != "missing_tool" {
		t.Fatalf("skip reason = %q, want missing_tool", result.SkipReason)
	}
	if !strings.Contains(result.Output, `build tool "npm" not found`) {
		t.Fatalf("build output = %q", result.Output)
	}
}

func TestOpenLocalRepository_UsesWorktreeWithoutGitMetadata(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	srcDir := filepath.Join(dir, "internal", "service")
	if err := os.MkdirAll(srcDir, 0o755); err != nil {
		t.Fatalf("create source dir failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(srcDir, "quality_insights.go"), []byte("package service\n"), 0o644); err != nil {
		t.Fatalf("write source file failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, ".git"), []byte("gitdir: /tmp/nonexistent\n"), 0o644); err != nil {
		t.Fatalf("write worktree git file failed: %v", err)
	}

	r, err := OpenLocalRepository(dir, "https://example.com/bug_agent.git", "main")
	if err != nil {
		t.Fatalf("OpenLocalRepository failed: %v", err)
	}

	files, err := r.ListFiles("")
	if err != nil {
		t.Fatalf("ListFiles failed: %v", err)
	}
	if len(files) != 1 || files[0] != "internal/service/quality_insights.go" {
		t.Fatalf("files = %#v", files)
	}
	content, err := r.ReadFile("internal/service/quality_insights.go")
	if err != nil {
		t.Fatalf("ReadFile failed: %v", err)
	}
	if content != "package service\n" {
		t.Fatalf("content = %q", content)
	}
}

func TestCreateBranch_CreatesAndChecksOutNewBranch(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	repo, err := ggit.PlainInit(dir, false)
	if err != nil {
		t.Fatalf("init repo failed: %v", err)
	}

	if err := os.WriteFile(dir+"/README.md", []byte("hello\n"), 0o644); err != nil {
		t.Fatalf("write seed file failed: %v", err)
	}

	worktree, err := repo.Worktree()
	if err != nil {
		t.Fatalf("get worktree failed: %v", err)
	}
	if _, err := worktree.Add("README.md"); err != nil {
		t.Fatalf("stage file failed: %v", err)
	}
	if _, err := worktree.Commit("init", &ggit.CommitOptions{
		Author: &object.Signature{
			Name:  "BugAgent",
			Email: "bug-agent@test.local",
			When:  time.Now(),
		},
	}); err != nil {
		t.Fatalf("commit failed: %v", err)
	}

	r := &Repository{repo: repo, workDir: dir}
	if err := r.CreateBranch("master", "fix/BUG-TEST-001"); err != nil {
		t.Fatalf("CreateBranch failed: %v", err)
	}

	current, err := r.GetCurrentBranch()
	if err != nil {
		t.Fatalf("GetCurrentBranch failed: %v", err)
	}
	if current != "fix/BUG-TEST-001" {
		t.Fatalf("current branch = %q, want %q", current, "fix/BUG-TEST-001")
	}
}
