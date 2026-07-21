-- PRD v1.1 数据库迁移脚本
-- 新增：project_repos、project_ai_configs 表
-- 改造：iteration_repos 表结构

-- 1. 新增项目仓库表
CREATE TABLE IF NOT EXISTS project_repos (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    repo_url VARCHAR(500) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 项目仓库唯一约束：同一项目内仓库地址不重复
CREATE UNIQUE INDEX IF NOT EXISTS idx_project_repos_project_url ON project_repos(project_id, repo_url);
CREATE INDEX IF NOT EXISTS idx_project_repos_project_id ON project_repos(project_id);

-- 2. 新增项目AI配置表
CREATE TABLE IF NOT EXISTS project_ai_configs (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    api_key TEXT,  -- 加密存储
    api_endpoint VARCHAR(500),
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_project_ai_configs_project_id ON project_ai_configs(project_id);

-- 3. 改造迭代仓库绑定表
-- 先备份原有数据（可选）
-- CREATE TABLE iteration_repos_backup AS SELECT * FROM iteration_repos;

-- 删除旧的唯一约束
DROP INDEX IF EXISTS iter_repo_url;

-- 添加新字段 repo_id
ALTER TABLE iteration_repos ADD COLUMN IF NOT EXISTS repo_id BIGINT REFERENCES project_repos(id) ON DELETE CASCADE;

-- 迁移数据：根据 repo_url 匹配到 project_repos.id
-- 注意：需要先在 project_repos 中手动创建对应的仓库记录，或跳过此步骤
-- UPDATE iteration_repos ir SET repo_id = pr.id FROM project_repos pr WHERE ir.repo_url = pr.repo_url;

-- 删除旧字段
ALTER TABLE iteration_repos DROP COLUMN IF EXISTS repo_url;
ALTER TABLE iteration_repos DROP COLUMN IF EXISTS repo_name;

-- 新的唯一约束
CREATE UNIQUE INDEX IF NOT EXISTS idx_iteration_repos_iter_repo ON iteration_repos(iteration_id, repo_id);

-- 4. 添加 users 表的 agent_types 字段（如果不存在）
ALTER TABLE users ADD COLUMN IF NOT EXISTS agent_types VARCHAR(200);

-- 5. 添加触发器自动更新 updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_project_repos_updated_at BEFORE UPDATE ON project_repos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_project_ai_configs_updated_at BEFORE UPDATE ON project_ai_configs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 迁移完成提示
SELECT 'Migration v1.1 completed. Please verify data integrity.' AS status;
