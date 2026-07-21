-- v5.5 Token Usage: 创建 ai_token_usages 表
-- 注意：不删除 analysis_reports 和 fix_tasks 的 Token 字段，两者并存
-- AITokenUsage 作为独立的汇总/明细表，旧字段保留用于兼容

CREATE TABLE IF NOT EXISTS ai_token_usages (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL,
    iteration_id BIGINT,
    defect_id BIGINT NOT NULL,
    consumption_type VARCHAR(20) NOT NULL,
    source_id BIGINT NOT NULL,
    attempt_index INT DEFAULT 0,
    is_final_attempt BOOLEAN DEFAULT FALSE,
    provider VARCHAR(50),
    model_name VARCHAR(100),
    prompt_tokens INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    estimated_cost_usd DOUBLE PRECISION DEFAULT 0,
    duration_ms BIGINT DEFAULT 0,
    created_at BIGINT
);

CREATE INDEX IF NOT EXISTS idx_project_type ON ai_token_usages (project_id, consumption_type);
CREATE INDEX IF NOT EXISTS idx_iteration_type ON ai_token_usages (iteration_id, consumption_type);
CREATE INDEX IF NOT EXISTS idx_defect_type ON ai_token_usages (defect_id, consumption_type);
CREATE INDEX IF NOT EXISTS idx_ai_token_usages_source_id ON ai_token_usages (source_id);
CREATE INDEX IF NOT EXISTS idx_ai_token_usages_created_at ON ai_token_usages (created_at);

-- 回填 analysis_reports 数据
INSERT INTO ai_token_usages (project_id, iteration_id, defect_id, consumption_type, source_id, attempt_index, is_final_attempt, provider, model_name, prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd, duration_ms, created_at)
SELECT
    i.project_id,
    d.iteration_id,
    ar.defect_id,
    'analysis',
    ar.id,
    0,
    TRUE,
    ar.provider,
    ar.model_name,
    ar.prompt_tokens,
    ar.completion_tokens,
    ar.total_tokens,
    ar.estimated_cost_usd,
    ar.duration_ms,
    EXTRACT(EPOCH FROM ar.created_at)::BIGINT
FROM analysis_reports ar
JOIN defects d ON d.id = ar.defect_id
JOIN iterations i ON i.id = d.iteration_id
WHERE ar.total_tokens > 0;

-- 回填 fix_tasks 数据
INSERT INTO ai_token_usages (project_id, iteration_id, defect_id, consumption_type, source_id, attempt_index, is_final_attempt, provider, model_name, prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd, duration_ms, created_at)
SELECT
    i.project_id,
    d.iteration_id,
    ft.defect_id,
    'fix',
    ft.id,
    0,
    TRUE,
    ft.ai_provider,
    ft.ai_model_name,
    ft.ai_prompt_tokens,
    ft.ai_completion_tokens,
    ft.ai_total_tokens,
    ft.ai_estimated_cost_usd,
    ft.ai_duration_ms,
    EXTRACT(EPOCH FROM ft.created_at)::BIGINT
FROM fix_tasks ft
JOIN defects d ON d.id = ft.defect_id
JOIN iterations i ON i.id = d.iteration_id
WHERE ft.ai_total_tokens > 0;
