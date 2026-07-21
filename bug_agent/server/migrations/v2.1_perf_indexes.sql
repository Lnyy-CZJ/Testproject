-- v2.1 性能索引增强
-- 目标：优化缺陷列表、项目列表与协作轮询链路

-- 缺陷列表常用筛选 + 排序
CREATE INDEX IF NOT EXISTS idx_defects_iteration_status_created
ON defects (iteration_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_defects_iteration_created
ON defects (iteration_id, created_at DESC);

-- 项目成员查询（按用户找项目 / 按项目找成员）
CREATE INDEX IF NOT EXISTS idx_project_members_user_project
ON project_members (user_id, project_id);

CREATE INDEX IF NOT EXISTS idx_project_members_project_user
ON project_members (project_id, user_id);

-- 协作任务轮询与列表
CREATE INDEX IF NOT EXISTS idx_collab_tasks_status_updated
ON collaboration_tasks (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_collab_tasks_defect_created
ON collaboration_tasks (defect_id, created_at DESC);

-- 协作报告查询（按 task 聚合、按 report 反查）
CREATE INDEX IF NOT EXISTS idx_collab_reports_task_status
ON collaboration_reports (task_id, status);

CREATE INDEX IF NOT EXISTS idx_collab_reports_report_id
ON collaboration_reports (report_id);
