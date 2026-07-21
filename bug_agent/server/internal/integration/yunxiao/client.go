package yunxiao

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"bug-agent/pkg/logger"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const defaultEndpoint = "https://openapi-rdc.aliyuncs.com"

type Client struct {
	baseURL    string
	token      string
	httpClient *http.Client
}

type Repository struct {
	ExternalID     string `json:"externalId"`
	ExternalRepoID string `json:"externalRepoId"`
	Name           string `json:"name"`
	RepoURL        string `json:"repoUrl"`
	DefaultBranch  string `json:"defaultBranch,omitempty"`
	SourceType     string `json:"sourceType"`
	Path           string `json:"path,omitempty"`
	Description    string `json:"description,omitempty"`
}

type Member struct {
	ExternalID string `json:"externalId"`
	Name       string `json:"name"`
	Username   string `json:"username,omitempty"`
	Email      string `json:"email,omitempty"`
	Role       string `json:"role,omitempty"`
}

type APIError struct {
	StatusCode int
	Message    string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("云效 API 请求失败(%d): %s", e.StatusCode, e.Message)
}

func NewClient(endpoint, token string) *Client {
	base := strings.TrimSpace(endpoint)
	if base == "" {
		base = defaultEndpoint
	}
	base = strings.TrimRight(base, "/")
	return &Client{
		baseURL: base,
		token:   strings.TrimSpace(token),
		httpClient: &http.Client{
			Timeout: 15 * time.Second,
		},
	}
}

func (c *Client) Endpoint() string {
	return c.baseURL
}

func (c *Client) TestConnection(ctx context.Context, organizationID string) error {
	if strings.TrimSpace(c.token) == "" {
		return errors.New("云效访问令牌不能为空")
	}

	path := "/oapi/v1/codeup/repositories"
	if strings.TrimSpace(organizationID) != "" {
		path = "/oapi/v1/codeup/organizations/" + url.PathEscape(strings.TrimSpace(organizationID)) + "/repositories"
	}

	_, err := c.get(ctx, path, map[string]string{
		"page":    "1",
		"perPage": "1",
	})
	return err
}

func (c *Client) ListRepositories(ctx context.Context, organizationID string, page, perPage int, search string) ([]Repository, error) {
	if strings.TrimSpace(c.token) == "" {
		return nil, errors.New("云效访问令牌不能为空")
	}
	if page <= 0 {
		page = 1
	}
	if perPage <= 0 || perPage > 200 {
		perPage = 20
	}

	path := "/oapi/v1/codeup/repositories"
	if strings.TrimSpace(organizationID) != "" {
		path = "/oapi/v1/codeup/organizations/" + url.PathEscape(strings.TrimSpace(organizationID)) + "/repositories"
	}
	query := map[string]string{
		"page":    strconv.Itoa(page),
		"perPage": strconv.Itoa(perPage),
	}
	if s := strings.TrimSpace(search); s != "" {
		query["search"] = s
	}

	body, err := c.get(ctx, path, query)
	if err != nil {
		return nil, err
	}

	rows := extractArrayRows(body, "data", "result", "items", "list", "repositories")
	repos := make([]Repository, 0, len(rows))
	for _, row := range rows {
		repoURL := firstNonEmpty(
			row["httpUrlToRepo"],
			row["http_url_to_repo"],
			row["httpsUrl"],
			row["https_url"],
			row["cloneUrl"],
			row["clone_url"],
			row["webUrl"],
			row["web_url"],
			row["repoUrl"],
			row["repo_url"],
			row["sshUrlToRepo"],
		)
		name := firstNonEmpty(row["name"], row["path"], row["pathWithNamespace"])
		if strings.TrimSpace(name) == "" || strings.TrimSpace(repoURL) == "" {
			continue
		}

		externalID := firstNonEmpty(row["id"], row["repositoryId"], row["repoId"])
		repos = append(repos, Repository{
			ExternalID:     externalID,
			ExternalRepoID: externalID,
			Name:           strings.TrimSpace(name),
			RepoURL:        strings.TrimSpace(repoURL),
			DefaultBranch:  strings.TrimSpace(firstNonEmpty(row["defaultBranch"], row["default_branch"], row["defaultBranchName"])),
			SourceType:     "yunxiao",
			Path:           strings.TrimSpace(firstNonEmpty(row["pathWithNamespace"], row["path"])),
			Description:    strings.TrimSpace(firstNonEmpty(row["description"], row["desc"])),
		})
	}
	return repos, nil
}

func (c *Client) ListMembers(ctx context.Context, organizationID string, page, perPage int, search string) ([]Member, error) {
	if strings.TrimSpace(c.token) == "" {
		return nil, errors.New("云效访问令牌不能为空")
	}
	org := strings.TrimSpace(organizationID)
	if org == "" {
		return nil, errors.New("organizationId 不能为空")
	}
	if page <= 0 {
		page = 1
	}
	if perPage <= 0 || perPage > 200 {
		perPage = 20
	}

	path := "/oapi/v1/platform/organizations/" + url.PathEscape(org) + "/members"
	query := map[string]string{
		"page":    strconv.Itoa(page),
		"perPage": strconv.Itoa(perPage),
	}
	if s := strings.TrimSpace(search); s != "" {
		query["search"] = s
	}

	body, err := c.get(ctx, path, query)
	if err != nil {
		return nil, err
	}

	rows := extractArrayRows(body, "data", "result", "items", "list", "members")
	members := make([]Member, 0, len(rows))
	for _, row := range rows {
		name := strings.TrimSpace(firstNonEmpty(row["name"], row["nickName"], row["nickname"], row["username"]))
		if name == "" {
			continue
		}
		members = append(members, Member{
			ExternalID: strings.TrimSpace(firstNonEmpty(row["id"], row["userId"], row["accountId"])),
			Name:       name,
			Username:   strings.TrimSpace(firstNonEmpty(row["username"], row["loginName"], row["userName"])),
			Email:      strings.TrimSpace(firstNonEmpty(row["email"], row["mail"])),
			Role:       strings.TrimSpace(firstNonEmpty(row["role"], row["roleName"], row["memberRole"])),
		})
	}
	return members, nil
}

func (c *Client) get(ctx context.Context, path string, query map[string]string) ([]byte, error) {
	if strings.TrimSpace(c.token) == "" {
		return nil, errors.New("云效访问令牌不能为空")
	}

	u, err := url.Parse(c.baseURL + path)
	if err != nil {
		return nil, err
	}
	q := u.Query()
	for k, v := range query {
		if strings.TrimSpace(v) == "" {
			continue
		}
		q.Set(k, v)
	}
	u.RawQuery = q.Encode()

	const maxAttempts = 3
	var lastStatusCode int
	var lastRespBody []byte
	var lastErr error
	startAt := time.Now()
	attempts := 0

	for attempt := 1; attempt <= maxAttempts; attempt++ {
		attempts = attempt
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("x-yunxiao-token", c.token)
		req.Header.Set("Accept", "application/json")

		resp, err := c.httpClient.Do(req)
		if err != nil {
			lastErr = err
			logger.Errorf("[Yunxiao] GET %s attempt=%d transport_error=%v", u.Path, attempt, err)
			if attempt < maxAttempts {
				if waitErr := waitRetryBackoff(ctx, attempt); waitErr != nil {
					return nil, waitErr
				}
				continue
			}
			return nil, err
		}

		body, readErr := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
		resp.Body.Close()
		if readErr != nil {
			return nil, readErr
		}

		if resp.StatusCode < 400 {
			logger.Infof("[Yunxiao] GET %s status=%d attempts=%d duration_ms=%d", u.Path, resp.StatusCode, attempts, time.Since(startAt).Milliseconds())
			return body, nil
		}

		lastStatusCode = resp.StatusCode
		lastRespBody = body
		logger.Errorf("[Yunxiao] GET %s attempt=%d status=%d body=%s", u.Path, attempt, resp.StatusCode, parseErrorMessage(body))

		if shouldRetryStatus(resp.StatusCode) && attempt < maxAttempts {
			if waitErr := waitRetryBackoffWithHeader(ctx, attempt, resp); waitErr != nil {
				return nil, waitErr
			}
			continue
		}

		msg := parseErrorMessage(body)
		logger.Errorf("[Yunxiao] GET %s failed status=%d attempts=%d duration_ms=%d", u.Path, resp.StatusCode, attempts, time.Since(startAt).Milliseconds())
		return nil, &APIError{StatusCode: resp.StatusCode, Message: msg}
	}

	if lastErr != nil {
		logger.Errorf("[Yunxiao] GET %s failed transport attempts=%d duration_ms=%d err=%v", u.Path, attempts, time.Since(startAt).Milliseconds(), lastErr)
		return nil, lastErr
	}
	msg := parseErrorMessage(lastRespBody)
	logger.Errorf("[Yunxiao] GET %s failed status=%d attempts=%d duration_ms=%d", u.Path, lastStatusCode, attempts, time.Since(startAt).Milliseconds())
	return nil, &APIError{StatusCode: lastStatusCode, Message: msg}
}

func shouldRetryStatus(statusCode int) bool {
	return statusCode == http.StatusTooManyRequests || statusCode >= 500
}

func waitRetryBackoff(ctx context.Context, attempt int) error {
	if attempt < 1 {
		attempt = 1
	}
	delay := time.Duration(1<<(attempt-1)) * 200 * time.Millisecond
	timer := time.NewTimer(delay)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

// waitRetryBackoffWithHeader respects the Retry-After header from a 429 response.
func waitRetryBackoffWithHeader(ctx context.Context, attempt int, resp *http.Response) error {
	if attempt < 1 {
		attempt = 1
	}
	delay := time.Duration(1<<(attempt-1)) * 200 * time.Millisecond

	if resp.StatusCode == http.StatusTooManyRequests {
		if ra := resp.Header.Get("Retry-After"); ra != "" {
			if seconds, err := strconv.Atoi(ra); err == nil && seconds > 0 {
				delay = time.Duration(seconds) * time.Second
			}
		}
	}

	timer := time.NewTimer(delay)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func parseErrorMessage(body []byte) string {
	type errBody struct {
		Message string `json:"message"`
		Error   string `json:"error"`
		Code    string `json:"code"`
	}
	var eb errBody
	if err := json.Unmarshal(body, &eb); err == nil {
		msg := firstNonEmpty(eb.Message, eb.Error, eb.Code)
		if msg != "" {
			return msg
		}
	}
	raw := strings.TrimSpace(string(body))
	if raw == "" {
		return "unknown error"
	}
	if len(raw) > 300 {
		return raw[:300]
	}
	return raw
}

func extractArrayRows(body []byte, keys ...string) []map[string]string {
	var payload interface{}
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil
	}

	if rows := toRowArray(payload); len(rows) > 0 {
		return rows
	}
	root, ok := payload.(map[string]interface{})
	if !ok {
		return nil
	}
	for _, k := range keys {
		if rows := toRowArray(root[k]); len(rows) > 0 {
			return rows
		}
	}
	return nil
}

func toRowArray(v interface{}) []map[string]string {
	arr, ok := v.([]interface{})
	if !ok {
		return nil
	}
	rows := make([]map[string]string, 0, len(arr))
	for _, item := range arr {
		rowMap, ok := item.(map[string]interface{})
		if !ok {
			continue
		}
		row := make(map[string]string, len(rowMap))
		for key, val := range rowMap {
			row[key] = strings.TrimSpace(fmt.Sprintf("%v", val))
		}
		rows = append(rows, row)
	}
	return rows
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if s := strings.TrimSpace(v); s != "" && s != "<nil>" {
			return s
		}
	}
	return ""
}
