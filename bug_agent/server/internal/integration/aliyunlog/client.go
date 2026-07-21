package aliyunlog

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"strconv"
	"strings"
	"time"

	sls "github.com/aliyun/aliyun-log-go-sdk"
)

var (
	ErrEndpointRequired        = errors.New("aliyun log endpoint is required")
	ErrProjectRequired         = errors.New("aliyun log project is required")
	ErrLogstoreRequired        = errors.New("aliyun log logstore is required")
	ErrAccessKeyIDRequired     = errors.New("aliyun log accessKeyId is required")
	ErrAccessKeySecretRequired = errors.New("aliyun log accessKeySecret is required")
)

type FetchOptions struct {
	Endpoint        string
	Project         string
	Logstore        string
	Query           string
	AccessKeyID     string
	AccessKeySecret string
	SecurityToken   string
	FromMinutes     int
	ToDelaySeconds  int
	Lines           int64
	Reverse         bool
}

func FetchLogs(ctx context.Context, options FetchOptions) ([]json.RawMessage, error) {
	if strings.TrimSpace(options.Endpoint) == "" {
		return nil, ErrEndpointRequired
	}
	if strings.TrimSpace(options.Project) == "" {
		return nil, ErrProjectRequired
	}
	if strings.TrimSpace(options.Logstore) == "" {
		return nil, ErrLogstoreRequired
	}
	if strings.TrimSpace(options.AccessKeyID) == "" {
		return nil, ErrAccessKeyIDRequired
	}
	if strings.TrimSpace(options.AccessKeySecret) == "" {
		return nil, ErrAccessKeySecretRequired
	}

	provider := sls.NewStaticCredentialsProvider(
		strings.TrimSpace(options.AccessKeyID),
		strings.TrimSpace(options.AccessKeySecret),
		strings.TrimSpace(options.SecurityToken),
	)

	projectName := strings.TrimSpace(options.Project)
	if isLocalEndpoint(options.Endpoint) {
		projectName = ""
	}

	project, err := sls.NewLogProjectV2(projectName, strings.TrimSpace(options.Endpoint), provider)
	if err != nil {
		return nil, err
	}
	logstore, err := sls.NewLogStore(strings.TrimSpace(options.Logstore), project)
	if err != nil {
		return nil, err
	}

	now := time.Now()
	fromMinutes := options.FromMinutes
	if fromMinutes <= 0 {
		fromMinutes = 15
	}
	toDelaySeconds := options.ToDelaySeconds
	if toDelaySeconds < 0 {
		toDelaySeconds = 0
	}
	to := now.Add(-time.Duration(toDelaySeconds) * time.Second)
	from := to.Add(-time.Duration(fromMinutes) * time.Minute)

	lines := options.Lines
	if lines <= 0 {
		lines = 100
	}
	if lines > 100 {
		lines = 100
	}

	req := &sls.GetLogRequest{
		From:    from.Unix(),
		To:      to.Unix(),
		Lines:   lines,
		Query:   strings.TrimSpace(options.Query),
		Reverse: options.Reverse,
	}

	resp, err := logstore.GetLogsV2(req)
	if err != nil {
		return nil, err
	}

	items := make([]json.RawMessage, 0, len(resp.Logs))
	for _, logItem := range resp.Logs {
		bytes, marshalErr := json.Marshal(logItem)
		if marshalErr != nil {
			return nil, marshalErr
		}
		items = append(items, json.RawMessage(bytes))
	}
	return items, nil
}

func isLocalEndpoint(raw string) bool {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return false
	}
	if !strings.Contains(trimmed, "://") {
		return false
	}
	parsed, err := url.Parse(trimmed)
	if err != nil {
		return false
	}
	host := parsed.Hostname()
	if strings.EqualFold(host, "localhost") {
		return true
	}
	if ip := net.ParseIP(host); ip != nil {
		return true
	}
	if strings.HasSuffix(strings.ToLower(host), ".local") {
		return true
	}
	if _, err := strconv.Atoi(host); err == nil {
		return true
	}
	return false
}

func WrapError(err error) error {
	if err == nil {
		return nil
	}
	return fmt.Errorf("aliyun log sync failed: %w", err)
}
