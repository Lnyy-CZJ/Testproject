-- v5.5 Agent 能力一体化: 创建 project_mcp_servers 和 project_agent_skills 表

CREATE TABLE IF NOT EXISTS project_mcp_servers (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    name VARCHAR(100) NOT NULL,
    command VARCHAR(500) NOT NULL,
    args TEXT,
    description TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    created_by BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_mcp_servers_project_id ON project_mcp_servers (project_id);

CREATE TABLE IF NOT EXISTS project_agent_skills (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    name VARCHAR(100) NOT NULL,
    agent_type VARCHAR(20) NOT NULL,
    instruction TEXT,
    tools TEXT,
    mcp_server_ids TEXT,
    memory_categories TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    is_default BOOLEAN DEFAULT FALSE,
    created_by BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_project_agent_skills_project_id ON project_agent_skills (project_id);
