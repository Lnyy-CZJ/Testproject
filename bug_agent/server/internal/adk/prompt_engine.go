package adk

import (
	"bytes"
	"fmt"
	"strings"
	"sync"
	"text/template"
	"time"
)

type PromptTemplate struct {
	Name      string
	Version   string
	Content   string
	Variables []string
	CreatedAt time.Time
}

type PromptTemplateEngine struct {
	templates map[string]*PromptTemplate
	mu        sync.RWMutex
}

func NewPromptTemplateEngine() *PromptTemplateEngine {
	return &PromptTemplateEngine{
		templates: make(map[string]*PromptTemplate),
	}
}

func (e *PromptTemplateEngine) Register(name, version, content string) error {
	e.mu.Lock()
	defer e.mu.Unlock()

	tmpl, err := template.New(name).Parse(content)
	if err != nil {
		return fmt.Errorf("parse template %s: %w", name, err)
	}
	_ = tmpl

	vars := extractTemplateVariables(content)
	e.templates[name] = &PromptTemplate{
		Name:      name,
		Version:   version,
		Content:   content,
		Variables: vars,
		CreatedAt: time.Now(),
	}
	return nil
}

func (e *PromptTemplateEngine) Render(name string, data map[string]interface{}) (string, error) {
	e.mu.RLock()
	tmpl, ok := e.templates[name]
	e.mu.RUnlock()
	if !ok {
		return "", fmt.Errorf("template %s not found", name)
	}

	t, err := template.New(name).Parse(tmpl.Content)
	if err != nil {
		return "", fmt.Errorf("parse: %w", err)
	}

	var buf bytes.Buffer
	if err := t.Execute(&buf, data); err != nil {
		return "", fmt.Errorf("execute: %w", err)
	}
	return buf.String(), nil
}

func (e *PromptTemplateEngine) Get(name string) (*PromptTemplate, bool) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	t, ok := e.templates[name]
	return t, ok
}

func (e *PromptTemplateEngine) List() []string {
	e.mu.RLock()
	defer e.mu.RUnlock()
	names := make([]string, 0, len(e.templates))
	for name := range e.templates {
		names = append(names, name)
	}
	return names
}

func extractTemplateVariables(content string) []string {
	var vars []string
	seen := make(map[string]bool)
	for i := 0; i < len(content); i++ {
		if content[i] == '{' && i+1 < len(content) && content[i+1] == '.' {
			end := strings.Index(content[i:], "}}")
			if end < 0 {
				continue
			}
			varName := strings.TrimSpace(content[i+2 : i+end])
			if varName != "" && !seen[varName] {
				seen[varName] = true
				vars = append(vars, varName)
			}
		}
	}
	return vars
}

func DefaultPromptTemplates() *PromptTemplateEngine {
	engine := NewPromptTemplateEngine()
	for _, agentType := range []string{"frontend", "backend", "test", "ui", "client"} {
		content := buildInstructionRaw(agentType) + "{{if .MemoryCtx}}\n\n## 历史记忆\n{{.MemoryCtx}}{{end}}"
		engine.Register("analysis_"+agentType, "v1", content)
	}
	engine.Register("fix_generator", "v1", fixSystemPrompt)
	engine.Register("code_explorer", "v1", explorerSystemPrompt)
	return engine
}
