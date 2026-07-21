INSERT INTO retriever_plugins (project_id, name, display_name, description, config, enabled, sort_order, is_built_in, created_at, updated_at)
SELECT p.id,
       'repo_wiki',
       'repo-wiki 代码智能检索',
       '基于 repo-wiki 的语义代码搜索、调用链定位和源码上下文检索',
       '{"endpoint":"http://127.0.0.1:8766","repo":"","branch":"","topK":10,"timeoutMs":8000,"searchPath":"/search_symbols","expandDepth":1,"rewrite":true}',
       true,
       0,
       true,
       NOW(),
       NOW()
FROM projects p
WHERE NOT EXISTS (
    SELECT 1 FROM retriever_plugins rp WHERE rp.project_id = p.id AND rp.name = 'repo_wiki'
);

UPDATE retriever_plugins
SET sort_order = 10,
    updated_at = NOW()
WHERE name = 'keyword'
  AND sort_order < 10;

UPDATE retriever_plugins
SET sort_order = 20,
    updated_at = NOW()
WHERE name = 'rag'
  AND sort_order < 20;

UPDATE retriever_plugins
SET sort_order = 30,
    updated_at = NOW()
WHERE name = 'requirement'
  AND sort_order < 30;
