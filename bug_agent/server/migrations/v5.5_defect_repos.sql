-- v5.5 Defect Repo: 创建 defect_repos 表
CREATE TABLE IF NOT EXISTS defect_repos (
    id BIGSERIAL PRIMARY KEY,
    defect_id BIGINT NOT NULL,
    project_id BIGINT NOT NULL,
    repo_url VARCHAR(500) NOT NULL,
    branch VARCHAR(100),
    local_path VARCHAR(500) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    fix_task_id BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_defect_repos_defect_id ON defect_repos (defect_id);
CREATE INDEX IF NOT EXISTS idx_defect_repos_project_id ON defect_repos (project_id);
CREATE INDEX IF NOT EXISTS idx_defect_repos_fix_task_id ON defect_repos (fix_task_id);
CREATE INDEX IF NOT EXISTS idx_defect_repos_status ON defect_repos (status);
