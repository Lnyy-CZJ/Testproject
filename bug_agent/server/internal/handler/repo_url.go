package handler

import (
	"net/url"
	"strings"
)

func normalizeRepoURL(raw string) string {
	s := strings.TrimSpace(raw)
	if s == "" {
		return ""
	}

	parsed, err := url.Parse(s)
	if err != nil || parsed.Host == "" {
		return normalizeRepoPathOnly(s)
	}

	parsed.Scheme = strings.ToLower(strings.TrimSpace(parsed.Scheme))
	parsed.Host = strings.ToLower(strings.TrimSpace(parsed.Host))
	parsed.User = nil
	parsed.RawQuery = ""
	parsed.Fragment = ""

	path := normalizeRepoPathOnly(parsed.Path)
	if path == "" {
		path = "/"
	}
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	parsed.Path = path

	return strings.TrimSpace(parsed.String())
}

func normalizeRepoPathOnly(path string) string {
	s := strings.TrimSpace(path)
	s = strings.TrimSuffix(s, "/")
	s = strings.TrimSuffix(s, ".git")
	return s
}
