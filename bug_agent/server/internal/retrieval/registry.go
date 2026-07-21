package retrieval

import (
	"fmt"
	"sort"
)

type RetrieverFactory func(config string) (Retriever, error)

type ConfigSchema struct {
	Type       string                          `json:"type"`
	Title      string                          `json:"title,omitempty"`
	Properties map[string]ConfigSchemaProperty `json:"properties,omitempty"`
	Required   []string                        `json:"required,omitempty"`
}

type ConfigSchemaProperty struct {
	Type        string        `json:"type"`
	Title       string        `json:"title,omitempty"`
	Description string        `json:"description,omitempty"`
	Default     interface{}   `json:"default,omitempty"`
	Format      string        `json:"format,omitempty"`
	Enum        []interface{} `json:"enum,omitempty"`
	Minimum     *float64      `json:"minimum,omitempty"`
	Maximum     *float64      `json:"maximum,omitempty"`
}

func floatPtr(v float64) *float64 {
	return &v
}

type RetrieverPluginDefinition struct {
	Factory RetrieverFactory
	Schema  *ConfigSchema
}

type RetrieverPluginRegistry struct {
	definitions map[string]RetrieverPluginDefinition
}

func NewRetrieverPluginRegistry() *RetrieverPluginRegistry {
	return &RetrieverPluginRegistry{
		definitions: make(map[string]RetrieverPluginDefinition),
	}
}

func (r *RetrieverPluginRegistry) Register(name string, factory RetrieverFactory) {
	r.RegisterWithSchema(name, factory, nil)
}

func (r *RetrieverPluginRegistry) RegisterWithSchema(name string, factory RetrieverFactory, schema *ConfigSchema) {
	r.definitions[name] = RetrieverPluginDefinition{Factory: factory, Schema: schema}
}

func (r *RetrieverPluginRegistry) Create(name string, config string) (Retriever, error) {
	definition, ok := r.definitions[name]
	if !ok {
		return nil, fmt.Errorf("retriever plugin %q not registered", name)
	}
	return definition.Factory(config)
}

func (r *RetrieverPluginRegistry) ListRegistered() []string {
	names := make([]string, 0, len(r.definitions))
	for name := range r.definitions {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func (r *RetrieverPluginRegistry) Has(name string) bool {
	_, ok := r.definitions[name]
	return ok
}

func (r *RetrieverPluginRegistry) ConfigSchema(name string) *ConfigSchema {
	definition, ok := r.definitions[name]
	if !ok {
		return nil
	}
	return definition.Schema
}
