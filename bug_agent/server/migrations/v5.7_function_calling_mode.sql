-- v5.7: Add function_calling_mode to project_ai_configs
-- Add capability_tags fc flag to ai_model_catalog

ALTER TABLE project_ai_configs ADD COLUMN IF NOT EXISTS function_calling_mode VARCHAR(20) DEFAULT 'auto';

-- Update existing model catalog entries with fc capability tags
-- OpenAI models
UPDATE ai_model_catalog SET capability_tags = 'chat,fc' WHERE provider_key = 'openai' AND model_name IN ('gpt-5.4', 'gpt-5.4-mini', 'gpt-5.4-nano', 'gpt-4.1', 'gpt-4.1-mini') AND (capability_tags IS NULL OR capability_tags = '');
UPDATE ai_model_catalog SET capability_tags = 'chat,reasoning,fc' WHERE provider_key = 'openai' AND model_name = 'o3' AND (capability_tags IS NULL OR capability_tags = '');

-- Anthropic models
UPDATE ai_model_catalog SET capability_tags = 'chat,fc' WHERE provider_key = 'anthropic' AND model_name IN ('claude-opus-4-1-20250805', 'claude-sonnet-4-20250514', 'claude-haiku-3-5-20241022') AND (capability_tags IS NULL OR capability_tags = '');

-- Zhipu models
UPDATE ai_model_catalog SET capability_tags = 'chat,fc' WHERE provider_key = 'zhipu' AND model_name IN ('glm-5', 'glm-4.7', 'glm-4.6') AND (capability_tags IS NULL OR capability_tags = '');

-- DeepSeek models
UPDATE ai_model_catalog SET capability_tags = 'chat,fc' WHERE provider_key = 'deepseek' AND model_name = 'deepseek-chat' AND (capability_tags IS NULL OR capability_tags = '');
UPDATE ai_model_catalog SET capability_tags = 'chat,reasoning' WHERE provider_key = 'deepseek' AND model_name = 'deepseek-reasoner' AND (capability_tags IS NULL OR capability_tags = '');

-- DashScope models
UPDATE ai_model_catalog SET capability_tags = 'chat,fc' WHERE provider_key = 'dashscope' AND model_name IN ('qwen-max-latest', 'qwen-plus-latest', 'qwen-turbo-latest', 'qwen-flash', 'qwen3-max-preview') AND (capability_tags IS NULL OR capability_tags = '');
