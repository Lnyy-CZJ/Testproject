# BugAgent Sprint 3 规划：协作与体验优化

**版本**: v1.0  
**日期**: 2026-04-05  
**周期**: Week 3-4 (2026-04-12 ~ 2026-04-25)  
**目标**: 提升团队协作效率和用户体验，达到企业级标准

---

## 🎯 Sprint 3 目标

基于Sprint 1和Sprint 2的成果（AI分析 + 自动修复已实现），Sprint 3将聚焦于：

1. **多AGENT协作机制** - 让多个专家同时分析一个缺陷
2. **实时通知系统** - WebSocket推送，替代轮询
3. **RBAC权限控制** - 细粒度的角色权限管理
4. **操作审计日志** - 完整的操作追踪
5. **前端体验优化** - 修复任务详情页、数据统计

---

## 📊 当前完成度

| Sprint | 状态 | 核心功能 | 完成度 |
|--------|------|----------|--------|
| **Sprint 1** | ✅ 完成 | AI真实分析 | 100% |
| **Sprint 2** | ✅ 完成 | 自动修复闭环 | 100% |
| **Sprint 3** | 🚀 规划中 | 协作与体验 | 0% → 目标90% |

---

## 🔧 Task 3.1: 多AGENT协作调度器

**优先级**: P0 | **预估**: 2天 | **负责人**: Backend

### 需求背景
当前系统只支持单个AGENT分析一个缺陷。实际场景中，一个复杂缺陷可能需要：
- 前端工程师分析UI问题
- 后端工程师分析API问题
- 测试工程师补充测试用例
- 产品经理确认需求理解

### 功能设计

#### 3.1.1 协作任务模型
```go
// server/internal/model/collaboration.go

type CollaborationTask struct {
    ID           uint      `gorm:"primaryKey"`
    TaskCode     string    `gorm:"uniqueIndex;size:64"` // COL-{YYYYMM}-{序号}
    DefectID     uint      
    TriggerUserID uint      // 触发者
    Status       string    // pending, running, completed, failed, timeout
    
    AgentTypes   string    `gorm:"size:255"` // "frontend,backend,test"
    
    StartedAt    *time.Time
    CompletedAt  *time.Time
    TimeoutAt    *time.Time
    
    CreatedAt    time.Time
    UpdatedAt    time.Time
    
    // 关联
    Defect      Defect             `gorm:"foreignKey:DefectID"`
    Reports     []CollaborationReport `gorm:"foreignKey:TaskID"`
}

type CollaborationReport struct {
    ID          uint
    TaskID      uint
    AgentType   string
    ReportID    uint // 关联到AnalysisReport
    Status      string // pending, analyzing, completed, failed
    StartedAt   *time.Time
    CompletedAt *time.Time
}
```

#### 3.1.2 协作调度服务
```go
// server/internal/service/collaboration.go

type CollaborationService struct {
    db         *gorm.DB
    aiClient   ai.AIClient
    analysisSvc *AnalysisService
}

// StartCollaboration 启动多AGENT协作
func (s *CollaborationService) StartCollaboration(
    ctx context.Context,
    defectID uint,
    agentTypes []string,
    triggerUserID uint,
) (*CollaborationTask, error) {
    
    // 1. 创建协作任务记录
    task := &CollaborationTask{
        TaskCode: generateCollabCode(),
        DefectID: defectID,
        TriggerUserID: triggerUserID,
        AgentTypes: strings.Join(agentTypes, ","),
        Status: "running",
    }
    s.db.Create(task)
    
    // 2. 并行启动多个AGENT分析（使用goroutine + WaitGroup）
    var wg sync.WaitGroup
    for _, agentType := range agentTypes {
        wg.Add(1)
        go func(at string) {
            defer wg.Done()
            
            report := &CollaborationReport{
                TaskID: task.ID,
                AgentType: at,
                Status: "analyzing",
            }
            s.db.Create(report)
            
            // 调用单个AGENT分析
            result, err := s.analysisSvc.PerformAnalysis(ctx, AnalysisRequest{
                DefectID: defectID,
                AgentTypes: []string{at},
            })
            
            if err != nil {
                report.Status = "failed"
            } else {
                report.Status = "completed"
                report.ReportID = result.ReportID
            }
            s.db.Save(report)
        }(agentType)
    }
    
    // 3. 等待所有AGENT完成（或超时）
    done := make(chan bool)
    go func() {
        wg.Wait()
        done <- true
    }()
    
    select {
    case <-done:
        task.Status = "completed"
    case <-time.After(5 * time.Minute):
        task.Status = "timeout"
    }
    
    now := time.Now()
    task.CompletedAt = &now
    s.db.Save(task)
    
    return task, nil
}

// AggregateResults 聚合多个AGENT的分析结果
func (s *CollaborationService) AggregateResults(
    taskID uint,
) (*AggregatedReport, error) {
    
    var reports []CollaborationReport
    s.db.Where("task_id = ?", taskID).Find(&reports)
    
    aggregated := &AggregatedReport{
        TaskID: taskID,
        Agents: make([]AgentResult, 0),
        Consensus: make(map[string]float64),
    }
    
    for _, report := range reports {
        var analysis AnalysisReport
        s.db.First(&analysis, report.ReportID)
        
        agentResult := AgentResult{
            AgentType: report.AgentType,
            Analysis: analysis.Analysis,
            Solution: analysis.Solution,
        }
        aggregated.Agents = append(aggregated.Agents, agentResult)
    }
    
    计算共识度
    aggregated.Consensus = calculateConsensus(aggregated.Agents)
    
    return aggregated, nil
}
```

#### 3.1.3 API端点
```
POST /api/v1/collaborations/start
Body: { "defectId": 1001, "agentTypes": ["frontend", "backend", "test"] }
Response: { "taskId": "COL-20260405-001", "status": "running" }

GET /api/v1/collaborations/:taskId
Response: { 
    "status": "completed",
    "agents": [
        {"agentType": "frontend", "status": "completed", ...},
        {"agentType": "backend", "status": "completed", ...}
    ],
    "aggregated": {...}
}

GET /api/v1/defects/:id/collaborations
Response: [{ "taskId": "...", "status": "completed" }]
```

### 验收标准
- [ ] 支持同时触发2+个AGENT并行分析
- [ ] 每个AGENT独立生成报告
- [ ] 结果聚合算法（投票/加权）
- [ ] 协作超时控制（5分钟）
- [ ] 协作历史记录可查

---

## 🔔 Task 3.2: WebSocket实时通知系统

**优先级**: P0 | **预估**: 2天 | **负责人**: Backend + Frontend

### 需求背景
当前使用轮询方式获取状态更新（每3秒一次），存在以下问题：
- 延迟高（最多3秒延迟）
- 浪费资源（大量无效请求）
- 无法实现真正的实时性

### 技术方案

#### 3.2.1 WebSocket Hub设计
```go
// server/internal/websocket/hub.go

type Client struct {
    hub  *Hub
    conn *websocket.Conn
    send chan []byte
    userID uint
}

type Hub struct {
    clients    map[*Client]bool
    register   chan *Client
    unregister chan *Client
    broadcast  chan []byte
    rooms      map[uint]map[*Client]bool // roomID -> clients
}

func NewHub() *Hub {
    return &Hub{
        clients:    make(map[*Client]bool),
        register:   make(chan *Client),
        unregister: make(chan *Client),
        broadcast:  make(chan []byte),
        rooms:      make(map[uint]map[*Client]bool),
    }
}

func (h *Hub) Run() {
    for {
        select {
        case client := <-h.register:
            h.clients[client] = true
            
        case client := <-h.unregister:
            if _, ok := h.clients[client]; ok {
                delete(h.clients, client)
                close(client.send)
            }
            
        case message := <-h.broadcast:
            for client := range h.clients {
                select {
                case client.send <- message:
                default:
                    close(client.send)
                    delete(h.clients, client)
                }
            }
        }
    }
}

func (h *Hub) JoinRoom(roomID uint, client *Client) {
    if h.rooms[roomID] == nil {
        h.rooms[roomID] = make(map[*Client]bool)
    }
    h.rooms[roomID][client] = true
}

func (h *Hub) LeaveRoom(roomID uint, client *Client) {
    if h.rooms[roomID] != nil {
        delete(h.rooms[roomID], client)
    }
}

func (h *Hub) BroadcastToRoom(roomID uint, message []byte) {
    for client := range h.rooms[roomID] {
        select {
        case client.send <- message:
        default:
            close(client.send)
            delete(h.rooms[roomID], client)
        }
    }
}
```

#### 3.2.2 事件类型定义
```typescript
// web/src/types/notification.ts

type NotificationEvent = 
    | { type: 'defect_assigned'; data: Defect; timestamp: number }
    | { type: 'analysis_started'; data: { defectId: number; agentTypes: string[] }; timestamp: number }
    | { type: 'analysis_completed'; data: AnalysisReport; timestamp: number }
    | { type: 'fix_started'; data: FixTask; timestamp: number }
    | { type: 'fix_progress'; data: { taskId: string; progress: number; step: string }; timestamp: number }
    | { type: 'fix_completed'; data: FixTask; timestamp: number }
    | { type: 'comment_new'; data: Comment; timestamp: number }
    | { type: 'mention'; data: { commentId: number; fromUser: User }; timestamp: number }
    | { type: 'collaboration_update'; data: CollaborationTask; timestamp: number };
```

#### 3.2.3 前端Hook
```typescript
// web/src/hooks/useWebSocket.ts

export function useWebSocket(defectID?: number) {
    const [socket, setSocket] = useState<WebSocket | null>(null);
    const [notifications, setNotifications] = useState<NotificationEvent[]>([]);
    const [isConnected, setIsConnected] = useState(false);

    useEffect(() => {
        const wsURL = `ws://${window.location.host}/ws/defects/${defectID}`;
        const ws = new WebSocket(wsURL);
        
        ws.onopen = () => {
            setIsConnected(true);
            console.log('WebSocket connected');
        };
        
        ws.onmessage = (event) => {
            const notification: NotificationEvent = JSON.parse(event.data);
            setNotifications(prev => [...prev, notification]);
            
            显示Toast提示
            switch (notification.type) {
                case 'analysis_completed':
                    message.success('AI分析完成！');
                    break;
                case 'fix_completed':
                    message.success('自动修复完成！');
                    break;
                case 'mention':
                    notification.open({
                        message: `${notification.data.fromUser.nickname} @了你`,
                        description: '点击查看',
                        icon: <BellOutlined />,
                    });
                    break;
            }
        };
        
        ws.onclose = () => {
            setIsConnected(false);
            3秒后自动重连
            setTimeout(() => {
                if (defectID) connect();
            }, 3000);
        };
        
        setSocket(ws);
        
        return () => {
            ws.close();
        };
    }, [defectID]);

    return { socket, notifications, isConnected };
}
```

### API端点
```
WS /ws/defects/:defectId  - 连接特定缺陷的通知频道
WS /ws/user/:userId       - 连接用户个人通知频道
WS /ws/projects/:projectId - 连接项目级通知
```

### 验收标准
- [ ] WebSocket连接稳定（断线重连）
- [ ] 支持3种粒度：缺陷/用户/项目
- [ ] 7种事件类型全覆盖
- [ ] 消息延迟 < 500ms
- [ ] 在线状态显示
- [ ] 前端Toast通知集成

---

## 🔐 Task 3.3: RBAC权限控制系统

**优先级**: P1 | **预估**: 2天 | **负责人**: Backend + Frontend

### 需求背景
当前所有认证用户拥有相同权限，无法满足企业级安全要求。

### 权限模型设计

#### 3.3.1 数据模型
```sql
-- 角色表
CREATE TABLE roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE, -- admin, project_admin, developer, tester, guest
    display_name VARCHAR(50) NOT NULL,
    description TEXT,
    is_system BOOLEAN DEFAULT FALSE, -- 系统内置角色不可删除
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 权限表
CREATE TABLE permissions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(100) NOT NULL UNIQUE, -- defects:create, projects:manage, ...
    name VARCHAR(100) NOT NULL,
    module VARCHAR(50), -- defects, projects, users, system
    description TEXT
);

-- 角色-权限关联表
CREATE TABLE role_permissions (
    role_id INT NOT NULL,
    permission_id INT NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    FOREIGN KEY (role_id) REFERENCES roles(id),
    FOREIGN KEY (permission_id) REFERENCES permissions(id)
);

-- 用户-角色关联表（支持多角色）
CREATE TABLE user_roles (
    user_id INT NOT NULL,
    role_id INT NOT NULL,
    scope_type VARCHAR(20), -- global, org, project
    scope_id INT, -- org_id 或 project_id
    PRIMARY KEY (user_id, role_id, scope_type, COALESCE(scope_id, 0))
);
```

#### 3.3.2 默认角色权限矩阵
```go
var DefaultRolePermissions = map[string][]string{
    "org_admin": {
        "users:create", "users:read", "users:update", "users:delete",
        "projects:create", "projects:read", "projects:update", "projects:delete",
        "defects:*",
        "ai_configs:manage",
        "roles:assign",
    },
    "project_admin": {
        "projects:read", "projects:update",
        "members:manage",
        "defects:*",
        "iterations:*",
        "repos:manage",
        "ai_configs:manage",
        "roles:assign:project",
    },
    "developer": {
        "defects:read", "defects:create", "defects:update",
        "fix_tasks:create", "fix_tasks:execute",
        "comments:create", "comments:read",
        "attachments:upload",
        "repos:read",
    },
    "tester": {
        "defects:read", "defects:create", "defects:update",
        "defects:verify", "defects:reject",
        "agents:analyze",
        "fix_tasks:create",
        "comments:*",
        "attachments:upload",
    },
    "guest": {
        "defects:read",
        "comments:read",
        "reports:read",
    },
}
```

#### 3.3.3 权限中间件
```go
// server/internal/middleware/rbac.go

func RequirePermission(permission string) gin.HandlerFunc {
    return func(c *gin.Context) {
        userID := GetUserID(c)
        
        获取用户在当前上下文中的角色
        projectID := c.Param("id") // 从URL获取
        
        roles, err := getUserRoles(userID, "project", projectID)
        if err != nil {
            c.JSON(403, gin.H{"error": "获取角色失败"})
            c.Abort()
            return
        }
        
        检查是否有该权限
        hasPerm := checkPermissions(roles, permission)
        if !hasPerm {
            c.JSON(403, gin.H{"error": "无权执行此操作"})
            c.Abort()
            return
        }
        
        c.Next()
    }
}

// 使用示例
defects.POST("", RequirePermission("defects:create"), handler.CreateDefect)
defects.PUT("/:id/status", RequirePermission("defects:update_status"), handler.ChangeStatus)
```

#### 3.3.4 前端权限控制组件
```tsx
// web/src/components/PermissionGuard.tsx

interface PermissionGuardProps {
    permission: string;
    fallback?: React.ReactNode;
    children: React.ReactNode;
}

export const PermissionGuard: FC<PermissionGuardProps> = ({ 
    permission, 
    fallback = null, 
    children 
}) => {
    const { user } = useAuth();
    const hasPermission = usePermission(user.id, permission);
    
    if (!hasPermission) {
        return <>{fallback}</>;
    }
    
    return <>{children}</>;
};

// 使用示例
<PermissionGuard permission="defects:create">
    <Button type="primary">创建缺陷</Button>
</PermissionGuard>

<PermissionGuard permission="defects:delete" fallback={null}>
    <Button danger>删除</Button>
</PermissionGuard>
```

### 初始化脚本
```sql
INSERT INTO roles (name, display_name, description, is_system) VALUES
('org_admin', '组织管理员', '组织的最高管理者', TRUE),
('project_admin', '项目管理员', '项目的管理者', TRUE),
('developer', '开发人员', '开发团队成员', TRUE),
('tester', '测试人员', '质量保证人员', TRUE),
('guest', '访客', '只读访问者', TRUE);

INSERT INTO permissions (code, name, module) VALUES
('defects:create', '创建缺陷', 'defects'),
('defects:read', '查看缺陷', 'defects'),
('defects:update', '编辑缺陷', 'defects'),
('defects:delete', '删除缺陷', 'defects'),
('defects:assign', '分配缺陷', 'defects'),
('defects:change_status', '变更状态', 'defects'),
('defects:verify', '验证缺陷', 'defects'),
('agents:analyze', '触发AI分析', 'agents'),
('fix_tasks:create', '创建修复任务', 'fixes'),
('fix_tasks:execute', '执行自动修复', 'fixes');
```

### 验收标准
- [ ] 5种默认角色及权限配置
- [ ] 接口级别权限拦截
- [ ] 前端按钮/菜单级权限控制
- [ ] 角色分配界面
- [ ] 权限变更审计日志

---

## 📝 Task 3.4: 操作审计日志系统

**优先级**: P1 | **预估**: 1天 | **负责人**: Backend

### 需求背景
企业级应用必须具备完整的操作追踪能力，用于：
- 安全合规审查
- 问题排查追溯
- 用户行为分析

### 数据模型
```sql
CREATE TABLE audit_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    username VARCHAR(50),
    action VARCHAR(100) NOT NULL, -- create_defect, update_ai_config, assign_role...
    target_type VARCHAR(50), -- defect, project, user, ai_config...
    target_id INT,
    old_value JSON, -- 变更前的值
    new_value JSON, -- 变更后的值
    ip_address VARCHAR(45),
    user_agent TEXT,
    request_method VARCHAR(10),
    request_path VARCHAR(255),
    status_code INT,
    error_message TEXT,
    duration_ms INT, -- 执行耗时
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_target (target_type, target_id),
    INDEX idx_action (action),
    INDEX idx_created_at (created_at)
);
```

### 实现方式
```go
// server/internal/middleware/audit.go

func AuditLog() gin.HandlerFunc {
    return func(c *gin.Context) {
        start := time.Now()
        
        执行请求
        c.Next()
        
        只记录写操作
        method := c.Request.Method
        if method == http.MethodGet || method == http.MethodHead || method == http.MethodOptions {
            return
        }
        
        userID := GetUserID(c)
        username := ""
        if userID > 0 {
            var user model.User
            model.DB.Select("username").First(&user, userID)
            username = user.Username
        }
        
        log := model.AuditLog{
            UserID:       userID,
            Username:     username,
            Action:       getActionName(c),
            TargetType:   getTargetType(c),
            TargetID:     getTargetID(c),
            IPAddress:   c.ClientIP(),
            UserAgent:    c.Request.UserAgent(),
            RequestMethod: method,
            RequestPath: c.Request.URL.Path,
            StatusCode:  c.Writer.Status(),
            DurationMs:   int(time.Since(start).Milliseconds()),
        }
        
        如果有错误
        if len(c.Errors) > 0 {
            log.ErrorMessage = c.Errors.String()
        }
        
        model.DB.Create(&log)
    }
}

// GORM钩子 - 敏感操作自动记录
func (u *User) BeforeUpdate(tx *gorm.DB) error {
    记录变更前后的差异
    var oldUser User
    tx.Find(&oldUser, u.ID)
    
    if oldUser.AgentTypes != u.AgentTypes {
        tx.Create(&AuditLog{
            Action: "update_user_agent_types",
            TargetType: "user",
            TargetID: u.ID,
            OldValue: map[string]interface{}{"agent_types": oldUser.AgentTypes},
            NewValue: map[string]interface{}{"agent_types": u.AgentTypes},
        })
    }
    
    return nil
}
```

### 查询API
```
GET /api/v1/audit-logs?userId=1&action=create_defect&startDate=2026-04-01&endDate=2026-04-30&page=1&pageSize=20
Response: {
    "data": [...],
    "total": 150,
    "page": 1
}

GET /api/v1/audit-logs/export?format=csv&startDate=...&endDate=...
Response: CSV文件下载
```

### 验收标准
- [ ] 所有写操作自动记录
- [ ] 敏感操作（AI配置、角色）特殊标记
- [ ] 支持多维查询过滤
- [ ] 数据导出功能（CSV）
- [ ] 数据保留策略配置

---

## 🎨 Task 3.5: 前端体验优化

**优先级**: P1 | **预估**: 2天 | **负责人**: Frontend

### 3.5.1 修复任务详情页
```tsx
// web/src/pages/defects/FixTaskDetail.tsx

const FixTaskDetail: FC<{ taskId: string }> = ({ taskId }) => {
    const [task, setTask] = useState<FixTask>(null);
    const [loading, setLoading] = useState(true);
    
    useEffect(() => {
        loadTaskDetail();
        设置轮询进度（如果任务还在进行中）
        const interval = setInterval(() => {
            if (task?.status === 'executing' || task?.status === 'planning') {
                loadProgress();
            }
        }, 2000);
        
        return () => clearInterval(interval);
    }, [taskId]);

    return (
        <div className="max-w-5xl mx-auto p-6">
            <PageHeader title={`修复任务 ${task?.taskCode}`} />
            
            {/* 进度条 */}
            <Card className="mb-4">
                <Progress percent={calculateProgress(task)} status={getStatusIcon(task.status)} />
                <div className="mt-2 text-center text-lg font-medium">{task?.status}</div>
            </Card>
            
            {/* 步骤时间线 */}
            <Card title="执行步骤" className="mb-4">
                <Timeline mode="left">
                    {task?.steps?.map((step, index) => (
                        <Timeline.Item
                            key={index}
                            color={getStepColor(step.status)}
                            dot={getStepIcon(step.status)}
                        >
                            <div className="font-medium">Step {step.step}: {step.action}</div>
                            <div className="text-sm text-gray-500">{step.status}</div>
                            {step.error && (
                                <Alert message={step.error} type="error" showIcon className="mt-2" />
                            )}
                        </Timeline.Item>
                    ))}
                </Timeline>
            </Card>
            
            {/* 结果展示 */}
            {task?.status === 'completed' && (
                <Card title="修复结果">
                    <Descriptions bordered column={2}>
                        <Descriptions.Item label="Commit Hash">{task.result?.commitHash}</Descriptions.Item>
                        <Descriptions.Item label="Branch">{task.fixBranch}</Descriptions.Item>
                        <Descriptions.Item label="PR URL" span={2}>
                            <a href={task.prUrl} target="_blank">{task.prUrl}</a>
                        </Descriptions.Item>
                    </Descriptions.Item>
                    
                    Diff展示
                    <pre className="bg-gray-100 p-4 rounded mt-4 overflow-auto max-h-96">
                        <code>{task.result?.diff}</code>
                    </pre>
                </Card>
            )}
        </div>
    );
};
```

### 3.5.2 全局Loading状态
```tsx
// web/src/components/GlobalLoading.tsx

export const GlobalLoading: FC = () => {
    const { loading, tip } = useSelector((state: RootState) => state.global.loading);
    
    if (!loading) return null;
    
    return (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-9999">
            <Spin size="large" tip={tip || "加载中..."} />
        </div>
    );
};
```

### 3.5.3 错误边界
```tsx
// web/src/components/ErrorBoundary.tsx

interface State {
    hasError: boolean;
    error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false, error: null };

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    render() {
        if (this.state.hasError) {
            return (
                <Result
                    status="error"
                    title="页面出错了"
                    subTitle={this.state.error?.message}
                    extra={[
                        <Button type="primary" onClick={() => this.setState({ hasError: false })}>
                            重试
                        </Button>,
                        <Button onClick={() => window.location.href = '/'}>
                            返回首页
                        </Button>,
                    ]}
                />
            );
        }

        return this.props.children;
    }
}
```

### 验收标准
- [ ] 修复任务详情页完整展示
- [ ] 7步流程可视化（Timeline组件）
- [ ] 进度实时更新
- [ ] Diff代码高亮显示
- [ ] PR链接可直接跳转
- [ ] 错误边界捕获异常
- [ ] 全局Loading统一管理

---

## 📊 Sprint 3 任务分解总览

| 任务 | 优先级 | 预估工期 | 依赖 | 状态 |
|------|--------|----------|------|------|
| 3.1 多AGENT协作调度器 | P0 | 2天 | Sprint 1 | ⏳ 待开始 |
| 3.2 WebSocket实时通知 | P0 | 2天 | 无 | ⏳ 待开始 |
| 3.3 RBAC权限控制 | P1 | 2天 | 无 | ⏳ 待开始 |
| 3.4 操作审计日志 | P1 | 1天 | 无 | ⏳ 待开始 |
| 3.5 前端体验优化 | P1 | 2天 | 3.2 | ⏳ 待开始 |
| **总计** | - | **9天** | - | - |

---

## 🎯 成功指标

### 技术指标
| 指标 | 当前值 | Sprint 3后 | 目标 |
|------|--------|-----------|------|
| WebSocket连接稳定性 | 0% | >95% | >99% |
| 权限接口覆盖率 | 0% | >80% | >95% |
| 审计日志覆盖率 | 0% | >90% | >100% |
| 多Agent协作成功率 | N/A | >80% | >90% |
| 前端错误率 | 未知 | <1% | <0.5% |

### 业务指标
| 指标 | 当前值 | Sprint 3后 | 目标 |
|------|--------|-----------|------|
| 团队协作效率 | 低 | 提升30% | 提升50% |
| 安全事件可追溯 | 否 | 是 | 完整 |
| 用户体验评分 | 未知 | 8/10 | 9/10 |

---

## ⚠️ 风险评估

### 高风险
1. **WebSocket大规模连接压力**
   - 缓解：使用Redis Pub/Sub支持多实例
   - 备选：降级为长轮询

2. **RBAC性能影响**
   - 缓解：权限数据缓存（Redis）
   - 备选：简化权限模型

### 中风险
3. **审计日志数据量增长**
   - 缓解：定期归档、分区表
   - 备选：仅保留关键操作日志

---

## 📁 文件结构规划

```
server/
├── internal/
│   ├── model/
│   │   ├── collaboration.go      # 协作任务模型
│   │   ├── role.go               # 角色权限模型
│   │   └── audit_log.go          # 审计日志模型
│   │
│   ├── service/
│   │   └── collaboration.go      # 协作服务
│   │
│   ├── middleware/
│   │   ├── rbac.go              # 权限中间件
│   │   └── audit.go             # 审计中间件
│   │
│   ├── websocket/
│   │   ├── hub.go               # WebSocket中心
│   │   ├── handler.go           # WS处理器
│   │   └── event.go             # 事件定义
│   │
│   └── handler/
│       └── collaboration.go     # 协作API Handler
│
└── migrations/
    └── v1.2_sprint3.sql        # 数据库迁移脚本

web/src/
├── components/
│   ├── PermissionGuard.tsx      # 权限守卫组件
│   ├── ErrorBoundary.tsx        # 错误边界
│   └── GlobalLoading.tsx        # 全局Loading
│
├── hooks/
│   └── useWebSocket.ts          # WS Hook
│
├── pages/
│   └── defects/
│       └── FixTaskDetail.tsx    # 修复任务详情页
│
└── types/
    └── notification.ts          # 通知类型定义
```

---

## 🔄 与Sprint 1/2的关系

```
Sprint 1 (AI分析) ──┐
                      ├─→ Sprint 3 (协作+体验) → 生产就绪
Sprint 2 (自动修复) ┘
```

**依赖关系**:
- ✅ Sprint 3.1 (多Agent协作) 依赖 Sprint 1 的AnalysisService
- ✅ Sprint 3.5 (前端优化) 依赖 Sprint 3.2 (WebSocket)
- 🔲 其他任务相对独立

---

## 📝 下一步行动

### 立即开始（本周）
1. 创建数据库迁移脚本 v1.2_sprint3.sql
2. 实现WebSocket Hub基础框架
3. 开发RBAC权限中间件

### 本周内完成
4. 多AGENT协作调度器
5. 审计日志系统
6. 前端修复任务详情页

### 下周完成
7. WebSocket前后端联调
8. 权限UI界面
9. 全面测试和性能优化

---

**文档版本**: v1.0  
**最后更新**: 2026-04-05  
**下次评审**: Sprint 3 开始后第3天
