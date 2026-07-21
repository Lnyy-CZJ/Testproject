-- 为现有用户添加 client AGENT 类型
-- 执行时间: 2026-03-28
-- 说明: PRD 要求 6 种 AGENT 类型，现有用户缺少 client 类型

-- 方案 1: 为所有现有用户添加 client 类型（推荐）
UPDATE users 
SET agent_types = CONCAT(agent_types, ',client')
WHERE agent_types NOT LIKE '%client%'
  AND agent_types IS NOT NULL 
  AND agent_types != '';

-- 方案 2: 如果 agent_types 为空，设置完整的 6 种类型
UPDATE users 
SET agent_types = 'product,ui,frontend,client,backend,test'
WHERE agent_types IS NULL 
   OR agent_types = '';

-- 验证更新结果
SELECT id, username, agent_types 
FROM users 
WHERE deleted_at IS NULL
ORDER BY id;
