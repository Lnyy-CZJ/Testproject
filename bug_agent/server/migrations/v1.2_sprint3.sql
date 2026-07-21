-- Sprint 3 数据库迁移脚本
-- 版本: v1.2
-- 日期: 2026-04-05
-- 内容: 多AGENT协作、WebSocket、RBAC权限、审计日志

-- ============================================================
-- 1. 协作任务表（多AGENT并行分析）
-- ============================================================
CREATE TABLE IF NOT EXISTS collaboration_tasks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_code VARCHAR(64) NOT NULL UNIQUE,
    defect_id INT NOT NULL,
    trigger_user_id INT NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    agent_types VARCHAR(255),
    
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    timeout_at TIMESTAMP NULL,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_collab_defect (defect_id),
    INDEX idx_collab_status (status),
    INDEX idx_collab_trigger_user (trigger_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 2. 协作报告表（单个AGENT的分析结果）
-- ============================================================
CREATE TABLE IF NOT EXISTS collaboration_reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id INT NOT NULL,
    agent_type VARCHAR(50) NOT NULL,
    report_id INT,
    status VARCHAR(20) DEFAULT 'pending',
    error TEXT,
    
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_collab_report_task (task_id),
    INDEX idx_collab_report_agent (agent_type),
    FOREIGN KEY (task_id) REFERENCES collaboration_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (report_id) REFERENCES analysis_reports(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 3. 角色表
-- ============================================================
CREATE TABLE IF NOT EXISTS roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    display_name VARCHAR(50) NOT NULL,
    description TEXT,
    is_system BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入默认角色
INSERT INTO roles (name, display_name, description, is_system) VALUES
('org_admin', '组织管理员', '组织的最高管理者，拥有所有权限', TRUE),
('project_admin', '项目管理员', '项目的管理者，可以管理项目成员和配置', TRUE),
('developer', '开发人员', '开发团队成员，可以修复缺陷', TRUE),
('tester', '测试人员', '质量保证人员，可以创建和验证缺陷', TRUE),
('guest', '访客', '只读访问者，只能查看内容', TRUE);

-- ============================================================
-- 4. 权限表
-- ============================================================
CREATE TABLE IF NOT EXISTS permissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    module VARCHAR(50), -- defects, projects, users, agents, fixes, system
    description TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 插入默认权限
INSERT INTO permissions (code, name, module, description) VALUES
-- 缺陷相关权限
('defects:create', '创建缺陷', 'defects', '允许创建新缺陷'),
('defects:read', '查看缺陷', 'defects', '允许查看缺陷详情'),
('defects:update', '编辑缺陷', 'defects', '允许编辑缺陷信息'),
('defects:delete', '删除缺陷', 'defects', '允许删除缺陷'),
('defects:assign', '分配缺陷', 'defects', '允许分配缺陷给成员'),
('defects:change_status', '变更状态', 'defects', '允许变更缺陷状态'),
('defects:verify', '验证缺陷', 'defects', '允许验证和关闭缺陷'),
('defects:reject', '驳回缺陷', 'defects', '允许驳回缺陷'),

-- AGENT分析权限
('agents:analyze', '触发AI分析', 'agents', '允许触发AGENT进行AI分析'),
('agents:read_reports', '查看分析报告', 'agents', '允许查看AI分析报告'),

-- 修复任务权限
('fix_tasks:create', '创建修复任务', 'fixes', '允许创建自动修复任务'),
('fix_tasks:execute', '执行自动修复', 'fixes', '允许执行自动修复流程'),
('fix_tasks:read', '查看修复任务', 'fixes', '允许查看修复任务详情'),
('fix_tasks:cancel', '取消修复任务', 'fixes', '允许取消正在执行的修复任务'),

-- 项目管理权限
('projects:manage', '管理项目', 'projects', '完整的项目管理权限'),
('members:manage', '管理成员', 'projects', '可以添加/移除项目成员'),
('repos:manage', '管理仓库', 'projects', '可以管理项目仓库'),
('ai_configs:manage', '管理AI配置', 'projects', '可以管理项目AI配置'),
('iterations:manage', '管理迭代', 'projects', '可以管理迭代'),

-- 用户管理权限
('users:create', '创建用户', 'users', '允许创建新用户'),
('users:read', '查看用户', 'users', '允许查看用户信息'),
('users:update', '更新用户', 'users', '允许更新用户信息'),
('users:delete', '删除用户', 'users', '允许删除用户'),
('users:assign_roles', '分配角色', 'users', '可以为用户分配角色'),

-- 系统权限
('roles:assign', '分配角色', 'system', '可以为用户分配角色'),
('roles:manage', '管理角色', 'system', '可以创建和管理角色'),
('audit_logs:read', '查看审计日志', 'system', '可以查看操作审计日志');

-- ============================================================
-- 5. 角色-权限关联表
-- ============================================================
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INT NOT NULL,
    permission_id INT NOT NULL,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (role_id, permission_id),
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 为默认角色分配权限
-- 组织管理员：拥有所有权限
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p WHERE r.name = 'org_admin';

-- 项目管理员：拥有项目和缺陷的大部分权限
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id 
FROM roles r 
JOIN permissions p ON p.module IN ('defects', 'agents', 'fixes', 'projects')
WHERE r.name = 'project_admin';

-- 开发人员：缺陷读写、修复执行、评论
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id 
FROM roles r 
JOIN permissions p ON p.code IN (
    'defects:read', 'defects:create', 'defects:update',
    'fix_tasks:create', 'fix_tasks:execute', 'fix_tasks:read',
    'comments:*', 'attachments:upload',
    'repos:read'
)
WHERE r.name = 'developer';

-- 测试人员：缺陷创建验证、AI分析触发
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id 
FROM roles r 
JOIN permissions p ON p.code IN (
    'defects:read', 'defects:create', 'defects:update',
    'defects:verify', 'defects:reject',
    'agents:analyze', 'agents:read_reports',
    'fix_tasks:create',
    'comments:*', 'attachments:upload'
)
WHERE r.name = 'tester';

-- 访客：只读权限
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id 
FROM roles r 
JOIN permissions p ON p.code IN ('defects:read', 'reports:read')
WHERE r.name = 'guest';

-- ============================================================
-- 6. 用户-角色关联表（支持多角色，支持不同范围）
-- ============================================================
CREATE TABLE IF NOT EXISTS user_roles (
    user_id INT NOT NULL,
    role_id INT NOT NULL,
    scope_type VARCHAR(20) DEFAULT 'global', -- global, org, project
    scope_id INT DEFAULT 0, -- org_id 或 project_id
    
    assigned_by INT, -- 分配者
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    PRIMARY KEY (user_id, role_id, scope_type, scope_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 为现有用户分配默认角色（访客）
INSERT INTO user_roles (user_id, role_id, scope_type)
SELECT u.id, r.id, 'global'
FROM users u
CROSS JOIN roles r 
WHERE r.name = 'guest'
AND NOT EXISTS (
    SELECT 1 FROM user_roles ur WHERE ur.user_id = u.id AND ur.role_id = r.id
);

-- ============================================================
-- 7. 审计日志表
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    username VARCHAR(50),
    action VARCHAR(100) NOT NULL, -- create_defect, update_ai_config, assign_role...
    target_type VARCHAR(50), -- defect, project, user, ai_config, fix_task, collaboration...
    target_id INT,
    old_value JSON, -- 变更前的值（敏感数据脱敏）
    new_value JSON, -- 变更后的值
    
    ip_address VARCHAR(45),
    user_agent TEXT,
    request_method VARCHAR(10),
    request_path VARCHAR(255),
    status_code INT,
    error_message TEXT,
    duration_ms INT, -- 执行耗时（毫秒）
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_audit_user (user_id),
    INDEX idx_audit_target (target_type, target_id),
    INDEX idx_audit_action (action),
    INDEX idx_audit_created_at (created_at),
    INDEX idx_audit_date (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 8. WebSocket连接记录表（可选）
-- ============================================================
CREATE TABLE IF NOT EXISTS ws_connections (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    session_id VARCHAR(64) NOT NULL UNIQUE, -- WebSocket会话ID
    room_type VARCHAR(20), -- defect, user, project, global
    room_id INT,
    
    connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_ping_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    disconnected_at TIMESTAMP NULL,
    ip_address VARCHAR(45),
    
    INDEX idx_ws_user (user_id),
    INDEX idx_ws_room (room_type, room_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 完成迁移标记
-- ============================================================
ALTER TABLE collaboration_tasks ADD CONSTRAINT fk_collab_defect 
    FOREIGN KEY (defect_id) REFERENCES defects(id) ON DELETE CASCADE;
    
ALTER TABLE collaboration_tasks ADD CONSTRAINT fk_collab_trigger_user 
    FOREIGN KEY (trigger_user_id) REFERENCES users(id) ON DELETE SET NULL;

-- 添加注释
ALTER TABLE collaboration_tasks MODIFY COLUMN status VARCHAR(20) 
    COMMENT 'pending|running|completed|failed|timeout';
    
ALTER TABLE collaboration_reports MODIFY COLUMN agent_type VARCHAR(50) 
    COMMENT 'frontend|backend|ui|client|product|test';
    
ALTER TABLE collaboration_reports MODIFY COLUMN status VARCHAR(20) 
    COMMENT 'pending|analyzing|completed|failed';

-- 迁移完成提示
SELECT '✅ Sprint 3 数据库迁移成功！' AS message,
       COUNT(*) AS total_tables_created
FROM information_schema.tables 
WHERE table_schema = DATABASE()
AND table_name IN (
    'collaboration_tasks', 'collaboration_reports',
    'roles', 'permissions', 'role_permissions', 'user_roles',
    'audit_logs', 'ws_connections'
);
