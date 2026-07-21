-- v2.2 补充复合索引
-- 目标：优化评论列表、修复任务列表、分析报告列表、邀请码查询

CREATE INDEX IF NOT EXISTS idx_comments_defect_created
ON comments (defect_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_fix_tasks_defect_created
ON fix_tasks (defect_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_analysis_reports_defect_created
ON analysis_reports (defect_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_invite_codes_inviter_created
ON invite_codes (inviter_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notifications_user_created
ON notifications (user_id, created_at DESC);
