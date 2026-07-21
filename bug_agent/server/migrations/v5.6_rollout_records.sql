-- v5.6 Rollout Records: 创建 rollout_records 表

CREATE TABLE IF NOT EXISTS rollout_records (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(200) NOT NULL,
    defect_id BIGINT NOT NULL,
    events TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rollout_records_session_id ON rollout_records (session_id);
CREATE INDEX IF NOT EXISTS idx_rollout_records_defect_id ON rollout_records (defect_id);
