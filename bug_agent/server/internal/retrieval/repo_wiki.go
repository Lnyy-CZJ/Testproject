package retrieval

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const (
	defaultRepoWikiSearchPath = "/search_symbols"
	defaultRepoWikiTopK       = 10
	defaultRepoWikiTimeoutMS  = 8000
)

func RepoWikiConfigSchema() *ConfigSchema {
	return &ConfigSchema{
		Type:  "object",
		Title: "repo-wiki 检索配置",
		Required: []string{
			"endpoint",
		},
		Properties: map[string]ConfigSchemaProperty{
			"endpoint": {
				Type:        "string",
				Title:       "服务地址",
				Description: "repo-wiki 服务基础地址，例如 http://127.0.0.1:8000。",
				Format:      "uri",
			},
			"apiKey": {
				Type:        "string",
				Title:       "API Key",
				Description: "服务未开启鉴权时可留空。",
				Format:      "password",
			},
			"topK": {
				Type:        "integer",
				Title:       "返回数量",
				Description: "每次检索最多返回的证据数量。",
				Default:     defaultRepoWikiTopK,
				Minimum:     floatPtr(1),
				Maximum:     floatPtr(50),
			},
			"timeoutMs": {
				Type:        "integer",
				Title:       "超时时间（毫秒）",
				Description: "调用 repo-wiki 的单次请求超时时间。",
				Default:     defaultRepoWikiTimeoutMS,
				Minimum:     floatPtr(1000),
				Maximum:     floatPtr(60000),
			},
			"expandDepth": {
				Type:        "integer",
				Title:       "上下文扩展深度",
				Description: "由 repo-wiki 决定是否扩展符号上下文。",
				Default:     0,
				Minimum:     floatPtr(0),
				Maximum:     floatPtr(5),
			},
			"rewrite": {
				Type:        "boolean",
				Title:       "查询改写",
				Description: "开启后由 repo-wiki 尝试改写查询以提升召回。",
				Default:     true,
			},
		},
	}
}

type RepoWikiRetriever struct {
	endpoint    string
	apiKey      string
	repo        string
	branch      string
	searchPath  string
	topK        int
	timeout     time.Duration
	expandDepth int
	rewrite     bool
	client      *http.Client
}

type repoWikiConfig struct {
	Endpoint    string `json:"endpoint"`
	BaseURL     string `json:"baseUrl"`
	APIKey      string `json:"apiKey"`
	Repo        string `json:"repo"`
	Branch      string `json:"branch"`
	SearchPath  string `json:"searchPath"`
	TopK        int    `json:"topK"`
	TimeoutMS   int    `json:"timeoutMs"`
	ExpandDepth int    `json:"expandDepth"`
	Rewrite     *bool  `json:"rewrite"`
}

func NewRepoWikiRetriever(config string) (*RepoWikiRetriever, error) {
	var cfg repoWikiConfig
	if strings.TrimSpace(config) != "" {
		if err := json.Unmarshal([]byte(config), &cfg); err != nil {
			return nil, fmt.Errorf("parse repo_wiki config: %w", err)
		}
	}

	endpoint := strings.TrimSpace(cfg.Endpoint)
	if endpoint == "" {
		endpoint = strings.TrimSpace(cfg.BaseURL)
	}
	if endpoint == "" {
		return nil, fmt.Errorf("repo_wiki config: endpoint is required")
	}
	if _, err := url.ParseRequestURI(endpoint); err != nil {
		return nil, fmt.Errorf("repo_wiki config: endpoint is invalid: %w", err)
	}

	searchPath := strings.TrimSpace(cfg.SearchPath)
	if searchPath == "" {
		searchPath = defaultRepoWikiSearchPath
	}
	if !strings.HasPrefix(searchPath, "/") {
		searchPath = "/" + searchPath
	}

	topK := cfg.TopK
	if topK <= 0 {
		topK = defaultRepoWikiTopK
	}

	timeoutMS := cfg.TimeoutMS
	if timeoutMS <= 0 {
		timeoutMS = defaultRepoWikiTimeoutMS
	}

	rewrite := true
	if cfg.Rewrite != nil {
		rewrite = *cfg.Rewrite
	}

	return &RepoWikiRetriever{
		endpoint:    strings.TrimRight(endpoint, "/"),
		apiKey:      strings.TrimSpace(cfg.APIKey),
		repo:        strings.TrimSpace(cfg.Repo),
		branch:      strings.TrimSpace(cfg.Branch),
		searchPath:  searchPath,
		topK:        topK,
		timeout:     time.Duration(timeoutMS) * time.Millisecond,
		expandDepth: cfg.ExpandDepth,
		rewrite:     rewrite,
		client:      &http.Client{Timeout: time.Duration(timeoutMS) * time.Millisecond},
	}, nil
}

func (r *RepoWikiRetriever) Name() string {
	return "repo_wiki"
}

func (r *RepoWikiRetriever) Retrieve(ctx context.Context, query Query) ([]Evidence, error) {
	if strings.TrimSpace(query.Text) == "" {
		return nil, nil
	}

	topK := query.TopK
	if topK <= 0 {
		topK = r.topK
	}

	repoName := strings.TrimSpace(r.repo)
	if repoName == "" {
		repoName = strings.TrimSpace(query.RepoName)
	}
	branchName := strings.TrimSpace(r.branch)
	if branchName == "" {
		branchName = strings.TrimSpace(query.BranchName)
	}

	payload := map[string]interface{}{
		"query":        query.Text,
		"repo":         repoName,
		"repo_url":     strings.TrimSpace(query.RepoURL),
		"branch":       branchName,
		"top_k":        topK,
		"expand_depth": r.expandDepth,
		"rewrite":      r.rewrite,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("repo_wiki marshal request: %w", err)
	}

	reqCtx, cancel := context.WithTimeout(ctx, r.timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, r.endpoint+r.searchPath, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("repo_wiki create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if r.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+r.apiKey)
	}

	resp, err := r.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("repo_wiki request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return nil, fmt.Errorf("repo_wiki read response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("repo_wiki status %d: %s", resp.StatusCode, strings.TrimSpace(string(respBody)))
	}

	evidences, err := parseRepoWikiEvidences(respBody)
	if err != nil {
		return nil, err
	}
	if len(evidences) > topK {
		evidences = evidences[:topK]
	}
	return evidences, nil
}

func parseRepoWikiEvidences(body []byte) ([]Evidence, error) {
	var raw interface{}
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("repo_wiki parse response: %w", err)
	}
	items := unwrapRepoWikiItems(raw)
	evidences := make([]Evidence, 0, len(items))
	for _, item := range items {
		m, ok := item.(map[string]interface{})
		if !ok {
			continue
		}
		filePath := firstString(m, "file_path", "filePath", "path", "document")
		if filePath == "" {
			continue
		}
		evidences = append(evidences, Evidence{
			FilePath: filePath,
			SymbolID: firstString(m, "symbol_id", "symbolId", "id"),
			Line:     firstInt(m, "line", "line_start", "lineStart"),
			Snippet:  firstString(m, "snippet", "content", "summary", "name"),
			Score:    firstFloat(m, "score"),
			Source:   "repo_wiki",
		})
	}
	return evidences, nil
}

func unwrapRepoWikiItems(raw interface{}) []interface{} {
	if arr, ok := raw.([]interface{}); ok {
		return arr
	}
	m, ok := raw.(map[string]interface{})
	if !ok {
		return nil
	}
	for _, key := range []string{"data", "results", "symbols", "hits"} {
		v, exists := m[key]
		if !exists {
			continue
		}
		if arr, ok := v.([]interface{}); ok {
			return arr
		}
		if nested, ok := v.(map[string]interface{}); ok {
			return unwrapRepoWikiItems(nested)
		}
	}
	return nil
}

func firstString(m map[string]interface{}, keys ...string) string {
	for _, key := range keys {
		v, ok := m[key]
		if !ok || v == nil {
			continue
		}
		switch typed := v.(type) {
		case string:
			if strings.TrimSpace(typed) != "" {
				return typed
			}
		case float64:
			return strconv.FormatFloat(typed, 'f', -1, 64)
		}
	}
	return ""
}

func firstInt(m map[string]interface{}, keys ...string) int {
	for _, key := range keys {
		v, ok := m[key]
		if !ok || v == nil {
			continue
		}
		switch typed := v.(type) {
		case float64:
			return int(typed)
		case string:
			if n, err := strconv.Atoi(strings.TrimSpace(typed)); err == nil {
				return n
			}
		}
	}
	return 0
}

func firstFloat(m map[string]interface{}, keys ...string) float64 {
	for _, key := range keys {
		v, ok := m[key]
		if !ok || v == nil {
			continue
		}
		switch typed := v.(type) {
		case float64:
			return typed
		case string:
			if n, err := strconv.ParseFloat(strings.TrimSpace(typed), 64); err == nil {
				return n
			}
		}
	}
	return 0
}
