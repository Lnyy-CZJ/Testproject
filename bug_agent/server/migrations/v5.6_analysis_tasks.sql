-- v5.6 Analysis Tasks: 创建 analysis_tasks 表

CREATE TABLE IF NOT EXISTS analysis_tasks (
    id BIGSERIAL PRIMARY KEY,
    defect_id BIGINT NOT NULL,
    task_id VARCHAR(100) NOT NULL,
    priority INT NOT NULL DEFAULT 1,
    agent_types TEXT[] NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_analysis_tasks_defect_id ON analysis_tasks (defect_id);
CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status ON analysis_tasks (status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_tasks_task_id ON analysis_tasks (task_id);
