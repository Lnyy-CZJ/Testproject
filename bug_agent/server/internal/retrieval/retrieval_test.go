package retrieval

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"bug-agent/internal/git"

	ggit "github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing/object"
)

func seedRepo(t *testing.T, files map[string]string) string {
	t.Helper()
	root := t.TempDir()
	repo, err := ggit.PlainInit(root, false)
	if err != nil {
		t.Fatalf("init repo failed: %v", err)
	}
	worktree, err := repo.Worktree()
	if err != nil {
		t.Fatalf("worktree failed: %v", err)
	}
	for path, content := range files {
		fullPath := filepath.Join(root, filepath.FromSlash(path))
		if err := os.MkdirAll(filepath.Dir(fullPath), 0o755); err != nil {
			t.Fatalf("mkdir failed: %v", err)
		}
		if err := os.WriteFile(fullPath, []byte(content), 0o644); err != nil {
			t.Fatalf("write failed: %v", err)
		}
		if _, err := worktree.Add(path); err != nil {
			t.Fatalf("add failed: %v", err)
		}
	}
	if _, err := worktree.Commit("init", &ggit.CommitOptions{Author: &object.Signature{Name: "tester", Email: "tester@example.com", When: time.Now()}}); err != nil {
		t.Fatalf("commit failed: %v", err)
	}
	return root
}

func TestKeywordRetriever_ReturnsRankedFiles(t *testing.T) {
	remoteDir := seedRepo(t, map[string]string{
		"web/src/pages/projects/ProjectRepos.tsx": "export function ProjectRepos() { return null }\n",
		"web/src/pages/Dashboard.tsx":             "export function Dashboard() { return null }\n",
	})

	repo, err := git.NewRepository(context.Background(), git.CloneOptions{URL: remoteDir})
	if err != nil {
		t.Fatalf("clone repo failed: %v", err)
	}
	defer repo.Cleanup()

	retriever := NewKeywordRetriever()
	evidences, err := retriever.Retrieve(context.Background(), Query{
		Repo: repo,
		Text: "ProjectRepos 云效仓库导入搜索无效，文件在 web/src/pages/projects/ProjectRepos.tsx",
		TopK: 5,
	})
	if err != nil {
		t.Fatalf("retrieve failed: %v", err)
	}
	if len(evidences) == 0 {
		t.Fatal("expected evidence")
	}
	if evidences[0].FilePath != "web/src/pages/projects/ProjectRepos.tsx" {
		t.Fatalf("expected ProjectRepos.tsx first, got %q", evidences[0].FilePath)
	}
}

type staticRetriever struct {
	name string
	hits []Evidence
}

func (s *staticRetriever) Name() string { return s.name }

func (s *staticRetriever) Retrieve(context.Context, Query) ([]Evidence, error) {
	return s.hits, nil
}

func TestRouter_MergesByRRF(t *testing.T) {
	router := NewRouter(
		&staticRetriever{name: "a", hits: []Evidence{{FilePath: "a.go"}, {FilePath: "b.go"}}},
		&staticRetriever{name: "b", hits: []Evidence{{FilePath: "b.go"}, {FilePath: "c.go"}}},
	)

	hits, err := router.Retrieve(context.Background(), Query{TopK: 3})
	if err != nil {
		t.Fatalf("router retrieve failed: %v", err)
	}
	if len(hits) != 3 {
		t.Fatalf("expected 3 hits, got %d", len(hits))
	}
	if hits[0].FilePath != "b.go" {
		t.Fatalf("expected b.go first due to multi-retriever support, got %q", hits[0].FilePath)
	}
}
