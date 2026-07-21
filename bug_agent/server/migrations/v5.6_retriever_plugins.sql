-- v5.6 Retriever Plugin: 创建 retriever_plugins 表

CREATE TABLE IF NOT EXISTS retriever_plugins (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    description TEXT,
    config TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,
    is_built_in BOOLEAN DEFAULT FALSE,
    created_by BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retriever_plugins_project_id ON retriever_plugins (project_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_project_name ON retriever_plugins (project_id, name);
