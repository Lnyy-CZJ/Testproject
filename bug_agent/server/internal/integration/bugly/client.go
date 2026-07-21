package bugly

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

var ErrIssuesEndpointRequired = errors.New("bugly issues endpoint is required")

type Client struct {
	endpoint   string
	issuesPath string
	appID      string
	appKey     string
	apiToken   string
	httpClient *http.Client
}

func NewClient(endpoint, issuesPath, appID, appKey, apiToken string) *Client {
	return &Client{
		endpoint:   strings.TrimRight(strings.TrimSpace(endpoint), "/"),
		issuesPath: normalizeIssuesPath(issuesPath),
		appID:      strings.TrimSpace(appID),
		appKey:     strings.TrimSpace(appKey),
		apiToken:   strings.TrimSpace(apiToken),
		httpClient: &http.Client{Timeout: 15 * time.Second},
	}
}

func (c *Client) FetchIssues(ctx context.Context) ([]json.RawMessage, error) {
	if c.endpoint == "" {
		return nil, ErrIssuesEndpointRequired
	}

	const maxAttempts = 3
	var lastErr error
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		items, err := c.doFetchIssues(ctx)
		if err == nil {
			return items, nil
		}
		lastErr = err
		if attempt < maxAttempts {
			delay := time.Duration(1<<(attempt-1)) * 200 * time.Millisecond
			timer := time.NewTimer(delay)
			select {
			case <-ctx.Done():
				timer.Stop()
				return nil, ctx.Err()
			case <-timer.C:
			}
		}
	}
	return nil, lastErr
}

func (c *Client) doFetchIssues(ctx context.Context) ([]json.RawMessage, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.endpoint+c.issuesPath, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	if c.appID != "" {
		req.Header.Set("X-Bugly-App-Id", c.appID)
	}
	if c.appKey != "" {
		req.Header.Set("X-Bugly-App-Key", c.appKey)
	}
	if c.apiToken != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiToken)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(resp.Body, 10<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return nil, fmt.Errorf("bugly sync failed (%d): %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}

	items, err := extractItems(body)
	if err != nil {
		return nil, err
	}
	return items, nil
}

func normalizeIssuesPath(path string) string {
	trimmed := strings.TrimSpace(path)
	if trimmed == "" {
		return "/issues"
	}
	if strings.HasPrefix(trimmed, "/") {
		return trimmed
	}
	return "/" + trimmed
}

func extractItems(body []byte) ([]json.RawMessage, error) {
	var decoded interface{}
	if err := json.Unmarshal(body, &decoded); err != nil {
		return nil, err
	}

	switch typed := decoded.(type) {
	case []interface{}:
		return marshalItems(typed)
	case map[string]interface{}:
		if items, ok := findFirstArray(typed); ok {
			return marshalItems(items)
		}
	}

	return nil, errors.New("bugly sync response does not contain issue items")
}

func findFirstArray(payload map[string]interface{}) ([]interface{}, bool) {
	for _, key := range []string{"items", "issues", "list", "rows"} {
		if value, ok := payload[key]; ok {
			if rows, ok := value.([]interface{}); ok {
				return rows, true
			}
		}
	}
	for _, key := range []string{"data", "result"} {
		if value, ok := payload[key]; ok {
			if rows, ok := value.([]interface{}); ok {
				return rows, true
			}
			if nested, ok := value.(map[string]interface{}); ok {
				if rows, ok := findFirstArray(nested); ok {
					return rows, true
				}
			}
		}
	}
	return nil, false
}

func marshalItems(items []interface{}) ([]json.RawMessage, error) {
	result := make([]json.RawMessage, 0, len(items))
	for _, item := range items {
		bytes, err := json.Marshal(item)
		if err != nil {
			return nil, err
		}
		result = append(result, json.RawMessage(bytes))
	}
	return result, nil
}
