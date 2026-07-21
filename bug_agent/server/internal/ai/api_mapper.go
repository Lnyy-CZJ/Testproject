package ai

import (
	"context"
	"regexp"
	"strings"
)

type APIRouteMapper struct {
	routes []RouteEntry
}

type RouteEntry struct {
	Method      string
	Path        string
	HandlerFunc string
	HandlerFile string
}

func NewAPIRouteMapper(routerContent string) *APIRouteMapper {
	m := &APIRouteMapper{}
	m.parseRouter(routerContent)
	return m
}

func (m *APIRouteMapper) parseRouter(content string) {
	patterns := []struct {
		regex   *regexp.Regexp
		method  string
	}{
		{regexp.MustCompile(`(?i)\.GET\s*\(\s*"([^"]+)"[^,]+,\s*(\w+)\.(\w+)`), "GET"},
		{regexp.MustCompile(`(?i)\.POST\s*\(\s*"([^"]+)"[^,]+,\s*(\w+)\.(\w+)`), "POST"},
		{regexp.MustCompile(`(?i)\.PUT\s*\(\s*"([^"]+)"[^,]+,\s*(\w+)\.(\w+)`), "PUT"},
		{regexp.MustCompile(`(?i)\.DELETE\s*\(\s*"([^"]+)"[^,]+,\s*(\w+)\.(\w+)`), "DELETE"},
	}

	handlerFileMap := parseHandlerConstructors(content)

	for _, p := range patterns {
		matches := p.regex.FindAllStringSubmatch(content, -1)
		for _, match := range matches {
			if len(match) >= 4 {
				handlerVar := match[2]
				handlerFunc := match[3]
				handlerFile := handlerFileMap[handlerVar]
				m.routes = append(m.routes, RouteEntry{
					Method:      p.method,
					Path:        match[1],
					HandlerFunc: handlerFunc,
					HandlerFile: handlerFile,
				})
			}
		}
	}
}

func parseHandlerConstructors(content string) map[string]string {
	result := make(map[string]string)
	re := regexp.MustCompile(`(\w+)\s*:=\s*handler\.New(\w+)`)
	matches := re.FindAllStringSubmatch(content, -1)
	for _, match := range matches {
		if len(match) >= 3 {
			varName := match[1]
			handlerName := match[2]
			result[varName] = handlerNameToFilename(handlerName)
		}
	}
	return result
}

func handlerNameToFilename(name string) string {
	if strings.HasSuffix(name, "Handler") {
		name = strings.TrimSuffix(name, "Handler")
	}
	return strings.ToLower(name) + ".go"
}

func (m *APIRouteMapper) FindHandler(apiPath, httpMethod string) []RouteEntry {
	normalizedPath := normalizeAPIPath(apiPath)
	var results []RouteEntry
	for _, route := range m.routes {
		if strings.EqualFold(route.Method, httpMethod) && pathsMatch(route.Path, normalizedPath) {
			results = append(results, route)
		}
	}
	return results
}

func normalizeAPIPath(path string) string {
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	return path
}

func pathsMatch(routePath, requestPath string) bool {
	routeParts := strings.Split(strings.Trim(routePath, "/"), "/")
	requestParts := strings.Split(strings.Trim(requestPath, "/"), "/")

	if len(routeParts) != len(requestParts) {
		return false
	}

	for i := range routeParts {
		if strings.HasPrefix(routeParts[i], ":") || strings.HasPrefix(routeParts[i], "{") {
			continue
		}
		if !strings.EqualFold(routeParts[i], requestParts[i]) {
			return false
		}
	}
	return true
}

func ExtractFrontendAPICalls(content string) []FrontendAPICall {
	var calls []FrontendAPICall

	patterns := []struct {
		regex  *regexp.Regexp
		method string
	}{
		{regexp.MustCompile(`request\.get\s*\(\s*[` + "`" + `"]([^` + "`" + `"]+)[` + "`" + `"]`), "GET"},
		{regexp.MustCompile(`request\.post\s*\(\s*[` + "`" + `"]([^` + "`" + `"]+)[` + "`" + `"]`), "POST"},
		{regexp.MustCompile(`request\.put\s*\(\s*[` + "`" + `"]([^` + "`" + `"]+)[` + "`" + `"]`), "PUT"},
		{regexp.MustCompile(`request\.delete\s*\(\s*[` + "`" + `"]([^` + "`" + `"]+)[` + "`" + `"]`), "DELETE"},
	}

	for _, p := range patterns {
		matches := p.regex.FindAllStringSubmatch(content, -1)
		for _, match := range matches {
			if len(match) >= 2 {
				calls = append(calls, FrontendAPICall{
					Method: p.method,
					Path:   match[1],
				})
			}
		}
	}

	return calls
}

type FrontendAPICall struct {
	Method string
	Path   string
}

func FindAPIHandlersForFrontendFiles(ctx context.Context, frontendContents map[string]string, routerContent string) []RouteEntry {
	mapper := NewAPIRouteMapper(routerContent)
	var allRoutes []RouteEntry
	seen := make(map[string]bool)

	for _, content := range frontendContents {
		calls := ExtractFrontendAPICalls(content)
		for _, call := range calls {
			routes := mapper.FindHandler(call.Path, call.Method)
			for _, r := range routes {
				key := r.Method + " " + r.Path
				if !seen[key] {
					seen[key] = true
					allRoutes = append(allRoutes, r)
				}
			}
		}
	}

	return allRoutes
}
