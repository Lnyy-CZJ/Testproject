package vcs

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// VCSClient 版本控制系统客户端接口
type VCSClient interface {
	CreatePR(ownerOrProjectID, repoOrEmpty string, pr *PullRequest) (*PR, error)
	GetPRStatus(ownerOrProjectID, repoOrPrNumber string, prNumber string) (*PR, error)
	MergePR(ownerOrProjectID, repoOrPrNumber string, prNumber string, opts *MergeOptions) (*PR, error)
}

// MergeOptions 合并选项
type MergeOptions struct {
	CommitTitle   string `json:"commit_title,omitempty"`
	CommitMessage string `json:"commit_message,omitempty"`
	MergeMethod   string `json:"merge_method,omitempty"` // merge, squash, rebase
}

// PullRequest PR/MR请求
type PullRequest struct {
	Title       string `json:"title"`
	Description string `json:"body"`
	HeadBranch  string `json:"head"`
	BaseBranch  string `json:"base"`
}

// PR PR/MR响应
type PR struct {
	Number    int    `json:"number,omitempty"`
	IID       int    `json:"iid,omitempty"` // GitLab使用
	URL       string `json:"html_url,omitempty"`
	WebURL    string `json:"web_url,omitempty"` // GitLab
	State     string `json:"state"`
	Title     string `json:"title"`
	CreatedAt string `json:"created_at,omitempty"`
}

// GitHubClient GitHub API客户端
type GitHubClient struct {
	token   string
	baseURL string
	client  *http.Client
}

// NewGitHubClient 创建GitHub客户端
func NewGitHubClient(token string) *GitHubClient {
	return &GitHubClient{
		token:   token,
		baseURL: "https://api.github.com",
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// CreatePR 创建GitHub Pull Request
func (c *GitHubClient) CreatePR(owner, repo string, pr *PullRequest) (*PR, error) {
	url := fmt.Sprintf("%s/repos/%s/%s/pulls", c.baseURL, url.PathEscape(owner), url.PathEscape(repo))

	bodyBytes, err := json.Marshal(pr)
	if err != nil {
		return nil, fmt.Errorf("marshal request failed: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, fmt.Errorf("create request failed: %w", err)
	}

	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/vnd.github.v3+json")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("send request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
	if err != nil {
		return nil, fmt.Errorf("read response body failed: %w", err)
	}

	if resp.StatusCode != http.StatusCreated && resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API error: status=%d body=%s", resp.StatusCode, truncateBody(respBody, 200))
	}

	var githubPR struct {
		Number    int    `json:"number"`
		HtmlURL   string `json:"html_url"`
		State     string `json:"state"`
		Title     string `json:"title"`
		CreatedAt string `json:"created_at"`
	}

	if err := json.Unmarshal(respBody, &githubPR); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %w", err)
	}

	return &PR{
		Number:    githubPR.Number,
		URL:       githubPR.HtmlURL,
		State:     githubPR.State,
		Title:     githubPR.Title,
		CreatedAt: githubPR.CreatedAt,
	}, nil
}

// GetPRStatus 获取PR状态
func (c *GitHubClient) GetPRStatus(owner, repo, prNumber string) (*PR, error) {
	url := fmt.Sprintf("%s/repos/%s/%s/pulls/%s", c.baseURL, url.PathEscape(owner), url.PathEscape(repo), url.PathEscape(prNumber))

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("create request failed: %w", err)
	}

	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Accept", "application/vnd.github.v3+json")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("send request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
	if err != nil {
		return nil, fmt.Errorf("read response body failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API error: status=%d body=%s", resp.StatusCode, truncateBody(respBody, 200))
	}

	var githubPR struct {
		Number  int    `json:"number"`
		HtmlURL string `json:"html_url"`
		State   string `json:"state"`
		Merged  bool   `json:"merged"`
		Title   string `json:"title"`
	}

	if err := json.Unmarshal(respBody, &githubPR); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %w", err)
	}

	state := githubPR.State
	if githubPR.Merged {
		state = "merged"
	}

	return &PR{
		Number: githubPR.Number,
		URL:    githubPR.HtmlURL,
		State:  state,
		Title:  githubPR.Title,
	}, nil
}

// MergePR 合并GitHub Pull Request
func (c *GitHubClient) MergePR(owner, repo, prNumber string, opts *MergeOptions) (*PR, error) {
	url := fmt.Sprintf("%s/repos/%s/%s/pulls/%s/merge", c.baseURL, url.PathEscape(owner), url.PathEscape(repo), url.PathEscape(prNumber))

	bodyMap := map[string]string{}
	if opts != nil {
		if opts.CommitTitle != "" {
			bodyMap["commit_title"] = opts.CommitTitle
		}
		if opts.CommitMessage != "" {
			bodyMap["commit_message"] = opts.CommitMessage
		}
		if opts.MergeMethod != "" {
			bodyMap["merge_method"] = opts.MergeMethod
		}
	}

	bodyBytes, err := json.Marshal(bodyMap)
	if err != nil {
		return nil, fmt.Errorf("marshal request failed: %w", err)
	}

	req, err := http.NewRequest("PUT", url, bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, fmt.Errorf("create request failed: %w", err)
	}

	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/vnd.github.v3+json")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("send request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
	if err != nil {
		return nil, fmt.Errorf("read response body failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("merge API error: status=%d body=%s", resp.StatusCode, truncateBody(respBody, 200))
	}

	var mergeResp struct {
		Merged  bool   `json:"merged"`
		Message string `json:"message"`
		SHA     string `json:"sha"`
	}
	if err := json.Unmarshal(respBody, &mergeResp); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %w", err)
	}

	if !mergeResp.Merged {
		return nil, fmt.Errorf("merge not performed: %s", mergeResp.Message)
	}

	statusPR, _ := c.GetPRStatus(owner, repo, prNumber)
	if statusPR != nil {
		statusPR.State = "merged"
		return statusPR, nil
	}

	return &PR{
		Number: 0,
		State:  "merged",
		Title:  "",
	}, nil
}

// GitLabClient GitLab API客户端
type GitLabClient struct {
	token   string
	baseURL string
	client  *http.Client
}

// NewGitLabClient 创建GitLab客户端
func NewGitLabClient(token, baseURL string) *GitLabClient {
	if baseURL == "" {
		baseURL = "https://gitlab.com/api/v4"
	}

	return &GitLabClient{
		token:   token,
		baseURL: baseURL,
		client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// CreatePR 创建GitLab Merge Request
func (c *GitLabClient) CreatePR(projectID string, pr *PullRequest) (*PR, error) {
	url := fmt.Sprintf("%s/projects/%s/merge_requests", c.baseURL, url.PathEscape(projectID))

	bodyBytes, err := json.Marshal(pr)
	if err != nil {
		return nil, fmt.Errorf("marshal request failed: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, fmt.Errorf("create request failed: %w", err)
	}

	req.Header.Set("Private-Token", c.token)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("send request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
	if err != nil {
		return nil, fmt.Errorf("read response body failed: %w", err)
	}

	if resp.StatusCode != http.StatusCreated && resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API error: status=%d body=%s", resp.StatusCode, truncateBody(respBody, 200))
	}

	var gitlabMR struct {
		IID       int    `json:"iid"`
		WebURL    string `json:"web_url"`
		State     string `json:"state"`
		Title     string `json:"title"`
		CreatedAt string `json:"created_at"`
	}

	if err := json.Unmarshal(respBody, &gitlabMR); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %w", err)
	}

	return &PR{
		IID:       gitlabMR.IID,
		WebURL:    gitlabMR.WebURL,
		State:     gitlabMR.State,
		Title:     gitlabMR.Title,
		CreatedAt: gitlabMR.CreatedAt,
	}, nil
}

// GetPRStatus 获取Merge Request状态
func (c *GitLabClient) GetPRStatus(projectID, mrIID string) (*PR, error) {
	url := fmt.Sprintf("%s/projects/%s/merge_requests/%s", c.baseURL, url.PathEscape(projectID), url.PathEscape(mrIID))

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("create request failed: %w", err)
	}

	req.Header.Set("Private-Token", c.token)

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("send request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
	if err != nil {
		return nil, fmt.Errorf("read response body failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("API error: status=%d body=%s", resp.StatusCode, truncateBody(respBody, 200))
	}

	var gitlabMR struct {
		IID    int    `json:"iid"`
		WebURL string `json:"web_url"`
		State  string `json:"state"`
		Title  string `json:"title"`
		Merged bool   `json:"merged"`
	}

	if err := json.Unmarshal(respBody, &gitlabMR); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %w", err)
	}

	state := gitlabMR.State
	if gitlabMR.Merged {
		state = "merged"
	}

	return &PR{
		IID:    gitlabMR.IID,
		WebURL: gitlabMR.WebURL,
		State:  state,
		Title:  gitlabMR.Title,
	}, nil
}

// MergePR 合并GitLab Merge Request
func (c *GitLabClient) MergePR(projectID, mrIID string, opts *MergeOptions) (*PR, error) {
	url := fmt.Sprintf("%s/projects/%s/merge_requests/%s/merge", c.baseURL, url.PathEscape(projectID), url.PathEscape(mrIID))

	bodyMap := map[string]interface{}{}
	if opts != nil {
		if opts.CommitTitle != "" {
			bodyMap["squash_commit_message"] = opts.CommitTitle
		}
		if opts.MergeMethod == "squash" {
			bodyMap["squash"] = true
		}
		bodyMap["should_remove_source_branch"] = true
	}

	bodyBytes, err := json.Marshal(bodyMap)
	if err != nil {
		return nil, fmt.Errorf("marshal request failed: %w", err)
	}

	req, err := http.NewRequest("PUT", url, bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, fmt.Errorf("create request failed: %w", err)
	}

	req.Header.Set("Private-Token", c.token)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("send request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
	if err != nil {
		return nil, fmt.Errorf("read response body failed: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("merge API error: status=%d body=%s", resp.StatusCode, truncateBody(respBody, 200))
	}

	var gitlabMR struct {
		IID    int    `json:"iid"`
		WebURL string `json:"web_url"`
		State  string `json:"state"`
		Title  string `json:"title"`
		Merged bool   `json:"merged"`
	}
	if err := json.Unmarshal(respBody, &gitlabMR); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %w", err)
	}

	state := gitlabMR.State
	if gitlabMR.Merged || state == "merged" {
		state = "merged"
	}

	return &PR{
		IID:    gitlabMR.IID,
		WebURL: gitlabMR.WebURL,
		State:  state,
		Title:  gitlabMR.Title,
	}, nil
}

// DetectVCSProvider 检测VCS提供商（从仓库URL）
func DetectVCSProvider(repoURL string) (string, string, string) {
	host, projectPath := parseRepoHostAndPath(repoURL)
	if host == "" || projectPath == "" {
		return "unknown", "", ""
	}

	switch {
	case strings.EqualFold(host, "github.com"):
		return "github", projectPath, ""
	case strings.EqualFold(host, "gitlab.com"), strings.Contains(strings.ToLower(host), "gitlab."):
		baseURL := buildGitLabAPIBaseURL(host)
		return "gitlab", projectPath, baseURL
	}

	return "unknown", "", ""
}

func parseRepoHostAndPath(raw string) (string, string) {
	repoURL := strings.TrimSpace(raw)
	if repoURL == "" {
		return "", ""
	}

	// SCP-like SSH URL: git@host:owner/repo.git
	if strings.Contains(repoURL, "@") && strings.Contains(repoURL, ":") &&
		!strings.HasPrefix(repoURL, "http://") &&
		!strings.HasPrefix(repoURL, "https://") &&
		!strings.HasPrefix(repoURL, "ssh://") {
		parts := strings.SplitN(repoURL, "@", 2)
		hostAndPath := parts[len(parts)-1]
		hostPathParts := strings.SplitN(hostAndPath, ":", 2)
		if len(hostPathParts) != 2 {
			return "", ""
		}
		return strings.ToLower(strings.TrimSpace(hostPathParts[0])), normalizeProjectPath(hostPathParts[1])
	}

	parsed, err := url.Parse(repoURL)
	if err != nil {
		return "", ""
	}
	host := strings.ToLower(strings.TrimSpace(parsed.Hostname()))
	return host, normalizeProjectPath(parsed.Path)
}

func normalizeProjectPath(path string) string {
	value := strings.TrimSpace(path)
	value = strings.TrimPrefix(value, "/")
	value = strings.TrimSuffix(value, ".git")
	parts := strings.Split(value, "/")
	cleaned := make([]string, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part != "" {
			cleaned = append(cleaned, part)
		}
	}
	if len(cleaned) < 2 {
		return ""
	}
	return strings.Join(cleaned, "/")
}

func buildGitLabAPIBaseURL(host string) string {
	host = strings.TrimSpace(strings.ToLower(host))
	if host == "" {
		host = "gitlab.com"
	}
	return "https://" + host + "/api/v4"
}

// truncateBody 截断响应体，防止错误消息中泄露过长的敏感信息
func truncateBody(body []byte, maxLen int) string {
	s := string(body)
	if len(s) > maxLen {
		return s[:maxLen] + "...(truncated)"
	}
	return s
}
