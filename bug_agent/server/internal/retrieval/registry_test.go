package retrieval

import (
	"context"
	"testing"
)

type mockRetriever struct {
	name string
}

func (m *mockRetriever) Name() string                                            { return m.name }
func (m *mockRetriever) Retrieve(_ context.Context, _ Query) ([]Evidence, error) { return nil, nil }

func TestRegisterAndCreate(t *testing.T) {
	reg := NewRetrieverPluginRegistry()
	reg.Register("mock", func(config string) (Retriever, error) {
		return &mockRetriever{name: config}, nil
	})

	ret, err := reg.Create("mock", "test-name")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ret.Name() != "test-name" {
		t.Errorf("expected name %q, got %q", "test-name", ret.Name())
	}
}

func TestCreateUnknownPlugin(t *testing.T) {
	reg := NewRetrieverPluginRegistry()
	_, err := reg.Create("nonexistent", "")
	if err == nil {
		t.Fatal("expected error for unregistered plugin")
	}
}

func TestListRegistered(t *testing.T) {
	reg := NewRetrieverPluginRegistry()
	reg.Register("charlie", func(config string) (Retriever, error) {
		return &mockRetriever{name: config}, nil
	})
	reg.Register("alpha", func(config string) (Retriever, error) {
		return &mockRetriever{name: config}, nil
	})
	reg.Register("bravo", func(config string) (Retriever, error) {
		return &mockRetriever{name: config}, nil
	})

	names := reg.ListRegistered()
	expected := []string{"alpha", "bravo", "charlie"}
	if len(names) != len(expected) {
		t.Fatalf("expected %d names, got %d", len(expected), len(names))
	}
	for i, name := range names {
		if name != expected[i] {
			t.Errorf("index %d: expected %q, got %q", i, expected[i], name)
		}
	}
}

func TestHas(t *testing.T) {
	reg := NewRetrieverPluginRegistry()
	reg.Register("mock", func(config string) (Retriever, error) {
		return &mockRetriever{name: config}, nil
	})

	if !reg.Has("mock") {
		t.Error("expected Has(\"mock\") to be true")
	}
	if reg.Has("nonexistent") {
		t.Error("expected Has(\"nonexistent\") to be false")
	}
}

func TestOverwriteFactory(t *testing.T) {
	reg := NewRetrieverPluginRegistry()
	reg.Register("mock", func(config string) (Retriever, error) {
		return &mockRetriever{name: "first"}, nil
	})
	reg.Register("mock", func(config string) (Retriever, error) {
		return &mockRetriever{name: "second"}, nil
	})

	ret, err := reg.Create("mock", "")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ret.Name() != "second" {
		t.Errorf("expected name %q from overwritten factory, got %q", "second", ret.Name())
	}
}

func TestRegisterWithSchema(t *testing.T) {
	reg := NewRetrieverPluginRegistry()
	reg.RegisterWithSchema("mock", func(config string) (Retriever, error) {
		return &mockRetriever{name: config}, nil
	}, &ConfigSchema{
		Type:     "object",
		Required: []string{"endpoint"},
		Properties: map[string]ConfigSchemaProperty{
			"endpoint": {Type: "string", Title: "服务地址", Format: "uri"},
		},
	})

	schema := reg.ConfigSchema("mock")
	if schema == nil {
		t.Fatal("expected schema")
	}
	if schema.Properties["endpoint"].Format != "uri" {
		t.Fatalf("expected endpoint uri format, got %q", schema.Properties["endpoint"].Format)
	}
}

func TestBuiltinPluginsExposeConfigSchemas(t *testing.T) {
	reg := NewRetrieverPluginRegistry()
	RegisterBuiltinPlugins(reg)

	for _, name := range []string{"keyword", "repo_wiki", "rag", "requirement"} {
		if reg.ConfigSchema(name) == nil {
			t.Fatalf("expected builtin plugin %s to expose config schema", name)
		}
	}
}
