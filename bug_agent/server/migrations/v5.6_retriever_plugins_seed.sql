INSERT INTO retriever_plugins (project_id, name, display_name, description, config, enabled, sort_order, is_built_in, created_at, updated_at)
SELECT p.id, 'keyword', '仓库关键词检索', '基于文件名和内容的关键词匹配', '{}', true, 0, true, NOW(), NOW()
FROM projects p
WHERE NOT EXISTS (
    SELECT 1 FROM retriever_plugins rp WHERE rp.project_id = p.id AND rp.name = 'keyword'
);

INSERT INTO retriever_plugins (project_id, name, display_name, description, config, enabled, sort_order, is_built_in, created_at, updated_at)
SELECT p.id, 'rag', 'RAG 语义检索', '基于向量数据库的语义检索', '{}', false, 1, true, NOW(), NOW()
FROM projects p
WHERE NOT EXISTS (
    SELECT 1 FROM retriever_plugins rp WHERE rp.project_id = p.id AND rp.name = 'rag'
);

INSERT INTO retriever_plugins (project_id, name, display_name, description, config, enabled, sort_order, is_built_in, created_at, updated_at)
SELECT p.id, 'requirement', '需求文档检索', '从需求文档中检索相关上下文', '{}', false, 2, true, NOW(), NOW()
FROM projects p
WHERE NOT EXISTS (
    SELECT 1 FROM retriever_plugins rp WHERE rp.project_id = p.id AND rp.name = 'requirement'
);
