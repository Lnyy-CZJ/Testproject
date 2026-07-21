package adk

import (
	"fmt"
	"sync"
	"time"

	bugmodel "bug-agent/internal/model"
	"bug-agent/internal/retrieval"

	"google.golang.org/adk/tool"
	"gorm.io/gorm"
)

type ToolFactory func(ExplorerContext) (tool.Tool, error)

type toolRegistryEntry struct {
	name       string
	factory    ToolFactory
	agentTypes map[string]bool
}

type ToolRegistry struct {
	mu        sync.RWMutex
	entries   []toolRegistryEntry
	cache     map[string]cacheEntry
	db        *gorm.DB
	retriever *retrieval.RetrieverPluginRegistry
}

type cacheEntry struct {
	tools []tool.Tool
	at    time.Time
}

const toolCacheTTL = 5 * time.Minute

var defaultRegistry = NewToolRegistry()

func NewToolRegistry() *ToolRegistry {
	r := &ToolRegistry{
		cache: make(map[string]cacheEntry),
	}
	r.registerDefaults()
	return r
}

func DefaultToolRegistry() *ToolRegistry {
	return defaultRegistry
}

func (r *ToolRegistry) SetDB(db *gorm.DB) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.db = db
	r.cache = make(map[string]cacheEntry)
}

func (r *ToolRegistry) SetRetrieverRegistry(reg *retrieval.RetrieverPluginRegistry) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.retriever = reg
	r.cache = make(map[string]cacheEntry)
}

func (r *ToolRegistry) registerDefaults() {
	r.entries = []toolRegistryEntry{
		{
			name:    "search_code",
			factory: NewSearchCodeToolAdapted,
			agentTypes: map[string]bool{
				"planner": true, "explorer": true, "analysis": true,
			},
		},
		{
			name:    "read_file",
			factory: NewReadFileToolAdapted,
			agentTypes: map[string]bool{
				"planner": true, "explorer": true, "analysis": true,
			},
		},
		{
			name:    "find_api_handler",
			factory: NewFindAPIHandlerToolAdapted,
			agentTypes: map[string]bool{
				"planner": true, "explorer": true,
			},
		},
		{
			name:    "list_directory",
			factory: NewListDirectoryToolAdapted,
			agentTypes: map[string]bool{
				"planner": true, "explorer": true,
			},
		},
		{
			name:    "trace_call",
			factory: NewTraceCallToolAdapted,
			agentTypes: map[string]bool{
				"planner": true, "explorer": true,
			},
		},
	}
}

func (r *ToolRegistry) Register(name string, factory ToolFactory, agentTypes []string) {
	r.mu.Lock()
	defer r.mu.Unlock()

	atMap := make(map[string]bool, len(agentTypes))
	for _, t := range agentTypes {
		atMap[t] = true
	}
	r.entries = append(r.entries, toolRegistryEntry{
		name:       name,
		factory:    factory,
		agentTypes: atMap,
	})
	r.cache = make(map[string]cacheEntry)
}

func (r *ToolRegistry) Resolve(agentType string, expCtx ExplorerContext) []tool.Tool {
	cacheKey := fmt.Sprintf("%s:%t:%t:%t:%t:%t", agentType,
		expCtx.SearchFn != nil, expCtx.ReadFn != nil,
		expCtx.HandlerFn != nil, expCtx.ListFn != nil,
		expCtx.TraceFn != nil)

	r.mu.RLock()
	if entry, ok := r.cache[cacheKey]; ok && time.Since(entry.at) < toolCacheTTL {
		r.mu.RUnlock()
		return entry.tools
	}
	r.mu.RUnlock()

	r.mu.Lock()
	defer r.mu.Unlock()

	if entry, ok := r.cache[cacheKey]; ok && time.Since(entry.at) < toolCacheTTL {
		return entry.tools
	}

	var resolved []tool.Tool
	for _, entry := range r.entries {
		if !entry.agentTypes[agentType] {
			continue
		}
		t, err := entry.factory(expCtx)
		if err != nil {
			continue
		}
		resolved = append(resolved, t)
	}

	r.cache[cacheKey] = cacheEntry{tools: resolved, at: time.Now()}
	return resolved
}

func (r *ToolRegistry) ResolveWithPlugins(agentType string, expCtx ExplorerContext, projectID uint) []tool.Tool {
	base := r.Resolve(agentType, expCtx)

	if r.db == nil || projectID == 0 {
		return base
	}

	var plugins []bugmodel.RetrieverPlugin
	if err := r.db.Where("project_id = ? AND enabled = ?", projectID, true).
		Order("sort_order ASC").Find(&plugins).Error; err != nil {
		return base
	}

	if len(plugins) == 0 {
		return base
	}

	pluginTools := make([]tool.Tool, 0, len(plugins))
	for _, p := range plugins {
		if p.Name == "keyword" {
			continue
		}
		if r.retriever == nil || !r.retriever.Has(p.Name) {
			continue
		}
		retrieverInst, err := r.retriever.Create(p.Name, p.Config)
		if err != nil {
			continue
		}
		t, err := NewRetrieverPluginToolAdapted(p.Name, p.DisplayName, retrieverInst, expCtx.Repository)
		if err != nil {
			continue
		}
		pluginTools = append(pluginTools, t)
	}

	return append(pluginTools, base...)
}

func (r *ToolRegistry) InvalidateCache() {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.cache = make(map[string]cacheEntry)
}
