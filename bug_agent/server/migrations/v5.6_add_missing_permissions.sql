BEGIN;

INSERT INTO permissions (code, name, module, description) VALUES
    ('projects:read',   '查看项目',   'projects', '允许查看项目详情'),
    ('projects:update', '更新项目',   'projects', '允许更新项目配置与成员'),
    ('projects:create', '创建项目',   'projects', '允许创建新项目'),
    ('agents:read_report', '查看分析报告', 'agents', '允许查看AI分析报告'),
    ('fix_tasks:update', '更新修复任务', 'fixes', '允许更新修复任务状态'),
    ('notifications:send', '发送通知', 'notifications', '允许手动发送通知'),
    ('reports:export', '导出报表', 'reports', '允许导出报表数据'),
    ('rbac:manage', '管理角色权限', 'rbac', '允许管理角色与权限分配'),
    ('audit:read', '查看审计日志', 'audit', '允许查看操作审计日志'),
    ('system:settings', '系统配置', 'system', '允许修改系统级配置'),
    ('users:manage', '管理用户', 'users', '允许创建、更新、删除用户及分配角色')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
CROSS JOIN permissions p
WHERE r.name = 'super_admin'
  AND p.code IN (
      'projects:read', 'projects:update', 'projects:create',
      'agents:read_report', 'fix_tasks:update',
      'notifications:send', 'reports:export',
      'rbac:manage', 'audit:read',
      'system:settings', 'users:manage'
  )
  AND NOT EXISTS (
      SELECT 1 FROM role_permissions rp
      WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );

COMMIT;
