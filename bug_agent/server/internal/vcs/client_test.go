package vcs

import "testing"

func TestDetectVCSProvider_GitHubHTTPS(t *testing.T) {
	provider, ownerRepo, baseURL := DetectVCSProvider("https://github.com/openai/codex.git")
	if provider != "github" {
		t.Fatalf("provider = %q, want github", provider)
	}
	if ownerRepo != "openai/codex" {
		t.Fatalf("ownerRepo = %q, want openai/codex", ownerRepo)
	}
	if baseURL != "" {
		t.Fatalf("baseURL = %q, want empty", baseURL)
	}
}

func TestDetectVCSProvider_GitHubSSH(t *testing.T) {
	provider, ownerRepo, baseURL := DetectVCSProvider("git@github.com:openai/codex.git")
	if provider != "github" {
		t.Fatalf("provider = %q, want github", provider)
	}
	if ownerRepo != "openai/codex" {
		t.Fatalf("ownerRepo = %q, want openai/codex", ownerRepo)
	}
	if baseURL != "" {
		t.Fatalf("baseURL = %q, want empty", baseURL)
	}
}

func TestDetectVCSProvider_GitLabSelfHosted(t *testing.T) {
	provider, projectPath, baseURL := DetectVCSProvider("https://gitlab.example.com/group/subgroup/repo.git")
	if provider != "gitlab" {
		t.Fatalf("provider = %q, want gitlab", provider)
	}
	if projectPath != "group/subgroup/repo" {
		t.Fatalf("projectPath = %q, want group/subgroup/repo", projectPath)
	}
	if baseURL != "https://gitlab.example.com/api/v4" {
		t.Fatalf("baseURL = %q, want https://gitlab.example.com/api/v4", baseURL)
	}
}
