package retrieval

func RegisterBuiltinPlugins(registry *RetrieverPluginRegistry) {
	registry.RegisterWithSchema("keyword", func(config string) (Retriever, error) {
		return NewKeywordRetriever(), nil
	}, &ConfigSchema{
		Type:       "object",
		Title:      "关键词检索配置",
		Properties: map[string]ConfigSchemaProperty{},
	})
	registry.RegisterWithSchema("repo_wiki", func(config string) (Retriever, error) {
		return NewRepoWikiRetriever(config)
	}, RepoWikiConfigSchema())
	registry.RegisterWithSchema("rag", func(config string) (Retriever, error) {
		return NewRAGRetriever(config)
	}, RAGConfigSchema())
	registry.RegisterWithSchema("requirement", func(config string) (Retriever, error) {
		return NewRequirementRetriever(config)
	}, RequirementConfigSchema())
}
