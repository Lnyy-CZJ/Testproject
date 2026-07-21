# BugAgent v2.0 产品需求文档（PRD）

> **版本**: v2.0 | **日期**: 2026-04-06 | **状态**: Draft
> **基于版本**: v1.4.0（Sprint 4 完成状态：201 测试、PostgreSQL 全栈）

---

## 一、产品概述

### 1.1 背景与目标

BugAgent v1.x 已完成核心缺陷管理闭环（创建→分析→修复→验证→关闭），并具备 AI 协作分析、RBAC 权限、审计日志、通知系统、报表看板等能力。v2.0 的核心目标是**降低使用门槛、提升操作效率、简化权限模型**，从"能用"走向"好用"。

### 1.2 核心变更摘要

| 维度 | v1.x 现状 | v2.0 目标 |
|------|-----------|-----------|
| **组织架构** | Organization → Project → Iteration 三层 | 移除 Organization，Project 为顶层 |
| **权限模型** | Role + ScopeType(global/project) + 复杂 RBAC | 简化为「平台角色」+「项目角色」两级 |
| **交互效率** | AI 配置手动输入厂商/模型名；每次进入需选项目 | 厂商/模型下拉选择；全局项目切换器；首页直入工作台 |
| **仓库管理** | 仅存 URL 和名称 | 新增来源类型(GitHub/GitLab等)、凭证管理、AGENT 类型绑定 |
| **用户体系** | 仅管理员可创建账号；无个人信息页 | 邀请链接注册 + 管理员创建；个人信息页(AGENT身份/仓库范围) |
| **通知** | 统一发送，用户无法配置 | 按通知类型 × 渠道 自定义开关 |

---

## 二、需求详情

### 需求 1: 交互优化

#### 1.1 AI 配置表单改造 — 下拉替代手动输入

**当前问题**: [ProjectAIConfigs.tsx](web/src/pages/projects/ProjectAIConfigs.tsx) 中 `provider` 和 `modelName` 均为自由文本 Input，用户需记忆和手输。

**目标方案**:

| 字段 | 当前 | 改造后 |
|------|------|--------|
| AI 厂商 (`provider`) | `<Input placeholder="如 OpenAI...">` | `<Select>` 下拉列表 |
| 模型名称 (`modelName`) | `<Input placeholder="如 gpt-4o...">` | 根据 provider 联动的 `<Select>` 下拉 |

**厂商-模型预设数据表**:

```typescript
const PROVIDER_MODELS: Record<string, { name: string; endpoint?: string }[]> = {
  'OpenAI': [
    { name: 'gpt-4o', endpoint: 'https://api.openai.com/v1' },
    { name: 'gpt-4o-mini', endpoint: 'https://api.openai.com/v1' },
    { name: 'gpt-4-turbo', endpoint: 'https://api.openai.com/v1' },
    { name: 'o3', endpoint: 'https://api.openai.com/v1' },
    { name: 'o4-mini', endpoint: 'https://api.openai.com/v1' },
  ],
  '智谱AI': [
    { name: 'glm-4-plus', endpoint: 'https://open.bigmodel.cn/api/paas/v4' },
    { name: 'glm-4-flash', endpoint: 'https://open.bigmodel.cn/api/paas/v4' },
    { name: 'glm-4-long', endpoint: 'https://open.bigmodel.cn/api/paas/v4' },
    { name: 'codegeex-4', endpoint: 'https://open.bigmodel.cn/api/paas/v4' },
  ],
  'DeepSeek': [
    { name: 'deepseek-chat', endpoint: 'https://api.deepseek.com' },
    { name: 'deepseek-reasoner', endpoint: 'https://api.deepseek.com' },
  ],
  'Anthropic': [
    { name: 'claude-sonnet-4-20250514', endpoint: 'https://api.anthropic.com' },
    { name: 'claude-opus-4-20250514', endpoint: 'https://api.anthropic.com' },
    { name: 'claude-haiku-3-5-20241022', endpoint: 'https://api.anthropic.com' },
  ],
  '阿里云 DashScope': [
    { name: 'qwen-plus', endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
    { name: 'qwen-max', endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
    { name: 'qwen-coder-plus', endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  ],
};
```

**交互逻辑**:
1. 选择厂商后 → 模型下拉自动加载对应模型列表
2. 选择模型后 → API Endpoint 自动填充（允许手动修改）
3. 保留"自定义"选项，选则回退为自由输入模式
4. 后端新增接口 `GET /api/v1/ai/providers` 返回支持的厂商-模型列表

#### 1.2 全局项目/迭代切换器

**当前问题**: 
- 首页 `/` 显示项目列表（[ProjectList](web/src/pages/projects/ProjectList.tsx)），需点击才能进入项目
- 进入项目后无快速切换项目的入口
- 迭代选择分散在各页面中

**目标方案**:

```
┌─────────────────────────────────────────────────────────┐
│ 🔍 搜索缺陷...                    👤 admin ▼  🔔(0)     │
├──────────┬──────────────────────────────────────────────┤
│          │  📁 项目: [BugAgent平台 ▼]  📅 迭代: [Sprint5 ▼]│
│          ├──────────────────────────────────────────────┤
│  📋 缺陷  │                                              │
│  📊 报表  │         （工作台内容区域）                     │
│  ⚙️ 设置  │                                              │
│          │                                              │
└──────────┴──────────────────────────────────────────────┘
```

**实现要点**:

| 组件 | 位置 | 说明 |
|------|------|------|
| **项目切换器** | [ProjectLayout](web/src/layouts/ProjectLayout.tsx) 顶部栏 | Select 下拉，含搜索过滤；切换时路由跳转 `/projects/:projectId` |
| **迭代切换器** | 项目切换器右侧 | 根据选中项目动态加载该项目的迭代列表 |
| **默认行为** | 登录后自动进入"最近访问的项目"工作台 | localStorage 记录 `lastProjectId`，优先跳转 |

**涉及文件修改**:
- 新建 `web/src/components/ProjectSwitcher.tsx`
- 修改 `web/src/layouts/ProjectLayout.tsx` — 顶部增加切换器区域
- 修改 `web/src/router.tsx` — 首页重定向逻辑改为 `/projects/:lastProjectId`

---

### 需求 2: 仓库管理升级

#### 2.1 当前模型 vs 目标模型

**当前** ([models.go:88-99](server/internal/model/models.go#L88-L99)):
```go
type ProjectRepo struct {
    ID          uint   // 主键
    ProjectID   uint   // 所属项目
    Name        string // 名称
    RepoURL     string // URL
    Description string // 描述
}
```

**目标**:
```go
type ProjectRepo struct {
    ID            uint      `json:"id"`
    ProjectID     uint      `json:"projectId"`
    Name          string    `json:"name"`           // 仓库名称
    RepoURL       string    `json:"repoUrl"`        // 仓库地址
    SourceType    string    `json:"sourceType"`     // 来源: github / gitlab / gitea / custom
    CredentialID  *uint     `json:"credentialId"`   // 关联凭证 ID（外键）
    AgentTypes    string    `json:"agentTypes"`     // 绑定的 AGENT 类型，逗号分隔
    DefaultBranch string    `json:"defaultBranch"`  // 默认分支
    Description   string    `json:"description"`
    CreatedAt     time.Time `json:"createdAt"`
    UpdatedAt     time.Time `json:"updatedAt"`
}
```

#### 2.2 凭证管理 (Credential)

**新增模型**:
```go
type RepoCredential struct {
    ID          uint      `json:"id"`
    UserID      uint      `json:"userId"`        // 归属用户
    Name        string    `json:"name"`          // 凭证名称（如 "GitHub-PAT"）
    Type        string    `json:"type"`          // pat / oauth / ssh_key / username_password
    Provider    string    `json:"provider"`      // github / gitlab / gitea / generic
    Content     string    `json:"-"`             // 加密存储的凭证内容
    MaskedValue string    `json:"maskedValue"`   // 脱敏显示值（如 "ghp_x***xxx"）
    LastUsedAt  *time.Time `json:"lastUsedAt"`   // 最后使用时间
    CreatedAt   time.Time `json:"createdAt"`
}
func (RepoCredential) TableName() string { return "repo_credentials" }
```

**凭证加密策略**: 使用 AES-256-GCM 加密，密钥从环境变量 `CREDENTIAL_ENCRYPT_KEY` 读取。API 返回仅返回 `maskedValue`，不返回明文。

#### 2.3 仓库来源类型

| SourceType | 名称 | URL 格式示例 | 特殊处理 |
|------------|------|-------------|---------|
| `github` | GitHub | `https://github.com/org/repo.git` | 自动解析 owner/repo，支持 GitHub API |
| `gitlab` | GitLab | `https://gitlab.com/group/repo.git` | 支持 GitLab API |
| `gitea` | Gitea | `https://gitea.example.com/user/repo.git` | 自托管实例 |
| `custom` | 自定义 | 任意 Git URL | 仅做 Git 操作，无平台 API |

#### 2.4 AGENT 操作仓库时的身份绑定

**场景**: AGENT 执行代码分析、生成 FixTask 时需要 clone/读取仓库代码。

**规则**:
1. 仓库配置了 `agent_types` 字段 → 匹配当前 AGENT 类型的凭证
2. 未匹配到专属凭证 → 使用项目默认凭证
3. 都没有 → 使用操作者（触发人）的个人凭证池中匹配 source_type 的凭证
4. 最终都找不到 → 报错提示"请先配置仓库凭证"

**前端改动** ([ProjectRepos.tsx](web/src/pages/projects/ProjectRepos.tsx)):
- 新增字段：来源类型（Select）、关联凭证（Select）、绑定 AGENT 类型（Checkbox.Group）、默认分支（Input）
- 新增凭证管理 Tab 或弹窗

**新增 API**:

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/credentials` | 当前用户的凭证列表 |
| POST | `/api/v1/credentials` | 创建凭证 |
| PUT | `/api/v1/credentials/:id` | 更新凭证 |
| DELETE | `/api/v1/credentials/:id` | 删除凭证 |
| POST | `/api/v1/repos/:id/test-connection` | 测试仓库连接性 |

---

### 需求 3: 个人信息管理

#### 3.1 新增页面: 个人设置

**路由**: `/profile` （在 MainLayout 下）

**功能模块**:

##### 3.1.1 基本信息

| 字段 | 说明 | 可编辑 |
|------|------|--------|
| 头像 | Avatar 上传 | ✅ |
| 昵称 | Nickname | ✅ |
| 邮箱 | Email | ❌ (需走单独流程) |

##### 3.1.2 AGENT 身份配置

**当前问题**: `user.agent_types` 是逗号字符串，只能在用户管理页由管理员修改。

**目标**: 用户自行配置自己能扮演的 AGENT 角色。

```
┌─────────────────────────────────────┐
│  我的 AGENT 身份                      │
│                                     │
│  ☑ 产品经理    ☐ UI设计师             │
│  ☑ 前端开发    ☑ 客户端开发           │
│  ☑ 后端开发    ☐ 测试工程师           │
│                                     │
│  提示: 你的 AGENT 身份决定了          │
│  你可以参与哪些类型的协作任务          │
└─────────────────────────────────────┘
```

**可用选项**（从系统预置枚举获取）:
```
product, ui, frontend, client, backend, test
```

##### 3.1.3 仓库操作权限（我的凭证）

复用需求 2 的凭证系统，展示当前用户已配置的所有仓库凭证，支持在此页面快捷管理。

##### 3.1.4 通知偏好

复用需求 4 的通知配置，提供快捷入口。

**涉及文件**:
- 新建 `web/src/pages/profile/ProfilePage.tsx`
- 新建 `web/src/pages/profile/AgentIdentity.tsx`
- 修改 `web/src/layouts/MainLayout.tsx` — 用户菜单增加"个人设置"
- 后端新增 `PUT /api/v1/users/profile` 接口

---

### 需求 4: 通知偏好配置

#### 4.1 当前问题

[notification.go](server/internal/service/notification.go) 已实现三通道发送（邮件/Webhook/站内信），但：
- 所有通知统一发送，用户无法控制
- 无按类型/渠道的精细配置

#### 4.2 目标: 用户通知偏好

**新增模型**:
```go
type UserNotificationPreference struct {
    ID         uint   `json:"id"`
    UserID     uint   `json:"userId"`
    Category   string `json:"category"`   // 通知分类
    Channel    string `json:"channel"`    // 通道: in_app / email / webhook
    Enabled    bool   `json:"enabled"`    // 是否启用
    UniqueIndex(userId, category, channel)
}
func (UserNotificationPreference.TableName()) string { return "user_notification_prefs" }
```

**通知分类枚举**:

| Category | 中文名称 | 默认 in_app | 默认 email | 默认 webhook |
|----------|---------|:-----------:|:----------:|:------------:|
| `defect_assigned` | 被指派缺陷 | ✅ | ✅ | ❌ |
| `defect_status_change` | 缺陷状态变更 | ✅ | ✅ | ❌ |
| `defect_mention` | 在评论中被@ | ✅ | ✅ | ❌ |
| `defect_due_soon` | 缺陷即将到期 | ✅ | ✅ | ❌ |
| `iteration_start` | 迭代开始 | ✅ | ❌ | ❌ |
| `iteration_end` | 迭代即将结束 | ✅ | ✅ | ❌ |
| `collaboration_complete` | 协作任务完成 | ✅ | ❌ | ❌ |
| `system_announce` | 系统公告 | ✅ | ✅ | ❌ |

**前端界面**: 在个人设置页或独立 `/notifications/settings` 页面，以矩阵形式展示：

```
              站内信    邮件    Webhook
被指派缺陷     [✅]     [✅]     [ ]
缺陷状态变更   [✅]     [✅]     [ ]
被@提及        [✅]     [✅]     [ ]
...
```

**发送逻辑修改** ([service/notification.go](server/internal/service/notification.go)):
```go
func (s *NotificationService) Send(req *NotifyRequest) error {
    for _, userID := range req.UserIDs {
        pref := s.getPreference(userID, req.Category, req.Type)
        if !pref.Enabled {
            continue  // 用户关闭了此通道，跳过
        }
        // ... 原有发送逻辑
    }
}
```

**新增 API**:

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/notification-preferences` | 获取当前用户的通知偏好矩阵 |
| PUT | `/api/v1/notification-preferences` | 批量更新通知偏好 |

---

### 需求 5: 用户管理体系增强

#### 5.1 注册方式扩展

**当前**: 仅 [Register.tsx](web/src/pages/auth/Register.tsx) 页面开放注册（但实际可能未暴露入口）

**目标: 三种账号创建方式**

| 方式 | 触发者 | 流程 | 适用场景 |
|------|--------|------|---------|
| **自助注册** | 用户自己 | 用户名+密码+邮箱 | 开放注册的平台 |
| **邀请链接** | 现有用户分享 | 生成带 token 的链接 → 点击→ 设置密码→ 自动加入 | 内部团队 |
| **管理员创建** | 平台管理员 | 管理员填写用户名/邮箱/初始密码 → 系统通知用户 | 企业部署 |

#### 5.2 邀请链接机制

**新增模型**:
```go
type InviteCode struct {
    Code        string    `json:"code"`         // 随机生成的邀请码
    InviterID   uint      `json:"inviterId"`    // 邀请人
    MaxUses     int       `json:"maxUses"`      // 最大使用次数 (0=无限)
    UsedCount   int       `json:"usedCount"`    // 已用次数
    ExpiresAt   *time.Time `json:"expiresAt"`   // 过期时间 (nil=永不过期)
    CreatedAt   time.Time `json:"createdAt"`
}
func (InviteCode.TableName()) string { return "invite_codes" }
```

**流程**:
```
管理员/有权限用户 → 生成邀请链接
    → https://bugagent.local/register?invite=abc123
用户打开链接 → 填写用户名/密码/昵称
    → 自动建立账号 + 关联邀请人
    → 跳转登录
```

#### 5.3 管理员创建账号

在现有 [UserManagement](web/src/pages/users/index.tsx) 页面增加"添加用户"按钮：

```
弹出框:
  用户名: [________]
  邮箱:   [________]
  初始密码: [________] (自动生成可选)
  平台角色: [▼ 选择角色]
  分配项目: [▼ 多选项目] (可选)
  [取消]  [创建]
```

创建成功后 → 触发欢迎通知（站内信 + 邮件如有配置）。

#### 5.4 平台身份字段

**User 模型新增字段**:
```go
type User struct {
    // ... 现有字段 ...
    PlatformRole string `json:"platformRole" gorm:"size:20;default:'member'"` // 平台角色: super_admin / admin / member
    InvitedBy     *uint  `json:"invitedBy"`     // 邀请人 ID
}
```

**平台角色定义**:

| PlatformRole | 名称 | 权限范围 |
|-------------|------|---------|
| `super_admin` | 超级管理员 | 全部权限（唯一或少量） |
| `admin` | 管理员 | 用户管理、项目管理、系统配置 |
| `member` | 普通成员 | 参与被分配的项目 |

**权限联动**: `platform_role` 作为 RBAC 的全局维度，配合需求 7 的简化权限模型使用。

**新增 API**:

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/invites` | 生成邀请链接 |
| GET | `/api/v1/invites` | 邀请链接列表 |
| POST | `/api/v1/invites/:code/accept` | 接受邀请（注册+绑定） |
| POST | `/api/v1/users` | 管理员创建用户 |
| PUT | `/api/v1/users/:id/platform-role` | 修改用户平台角色 |

---

### 需求 6: 移除组织(Organization)概念

#### 6.1 变更影响分析

**当前依赖 Organization 的模块**:

| 模块 | 文件 | 依赖方式 | 改动方案 |
|------|------|---------|---------|
| Project | `models.go:50` | `OrgID uint` 外键 | 移除 OrgID，Project 变为顶层实体 |
| OrgMember | `models.go:38-45` | 组织成员关系 | 废弃此表（被 ProjectMember 替代） |
| OrgList 页面 | `orgs/OrgList.tsx` | 组织 CRUD | 删除整个页面 |
| MainLayout 导航 | `MainLayout.tsx:44-48` | "组织管理"菜单项 | 移除菜单项 |
| Router | `router.tsx:37` | `/orgs` 路由 | 删除路由 |
| 数据库迁移 | — | organizations, org_members 表 | 不物理删除（保留历史），应用层不再使用 |

#### 6.2 具体改动

**Model 层** ([models.go](server/internal/model/models.go)):
```go
// Project - 移除 OrgID
type Project struct {
    ID              uint      `json:"id"`
    // OrgID           uint   ← 删除这行
    Name            string    `json:"name"`
    Code            string    `json:"code"`
    // ... 其余不变
}
```

**前端清理**:
- 删除 `web/src/pages/orgs/OrgList.tsx`
- 从 `router.tsx` 移除 `{ path: 'orgs', element: <OrgList /> }`
- 从 `MainLayout.tsx` 移除"组织管理"菜单项
- 清理所有引用 `orgId`/`org_id` 的组件

**数据库兼容**: 
- `organizations` 和 `org_members` 表不执行 DROP（保护历史数据）
- `projects.org_id` 列设为 nullable，新项目不再填写
- GORM AutoMigrate 不删除列，仅需移除 Model 定义中的字段即可

---

### 需求 7: 简化权限模型

#### 7.1 当前模型的问题

**当前** ([rbac.go](server/internal/middleware/rbac.go)):
- 5 种系统角色 (org_admin, project_admin, developer, tester, guest)
- 19 种细粒度权限码
- ScopeType 区分 global / project
- UserRole 表关联 role + scope_type + scope_id
- **问题**: 过于复杂，普通用户难以理解，管理员配置成本高

#### 7.2 目标模型: 两级权限

```
┌─────────────────────────────────────────┐
│           平台级权限 (Platform)            │
│  super_admin / admin / member            │
│  → 决定能在平台上做什么                   │
│  (管理用户? 创建项目? 查看报表?)           │
├─────────────────────────────────────────┤
│           项目级权限 (Project)            │
│  project_admin / developer / tester / viewer │
│  → 决定在某个项目中能做什么               │
│  (编辑缺陷? 执行AI分析? 管理成员?)          │
└─────────────────────────────────────────┘
```

#### 7.3 平台角色 → 权限映射

| 平台角色 | 用户管理 | 项目CRUD | 系统设置 | 报表导出 | 审计日志 |
|---------|:-------:|:-------:|:-------:|:-------:|:-------:|
| super_admin | ✅ | ✅ | ✅ | ✅ | ✅ |
| admin | ❌ | ✅ | ❌ | ✅ | ✅ |
| member | ❌ | (仅参与) | ❌ | (自己的) | ❌ |

#### 7.4 项目角色 → 权限映射

| 项目角色 | 缺陷CRUD | AI分析 | 仓库管理 | 成员管理 | 迭代管理 | 项目设置 |
|---------|:-------:|:-----:|:-------:|:-------:|:-------:|:-------:|
| project_admin | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| developer | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| tester | ✅(只读) | ❌ | ❌ | ❌ | ❌ | ❌ |
| viewer | ✅(只读) | ❌ | ❌ | ❌ | ❌ | ❌ |

#### 7.5 实现方案

**简化 RBAC 数据结构**:

不再维护 permissions 表的复杂多对多关系，改为**角色内置权限**：

```go
// 平台权限常量
var PlatformPermissions = map[string][]string{
    "super_admin": {"*"},  // 全部权限
    "admin":        {"projects:create", "projects:update", "users:read",
                     "reports:export", "audit:read", "invites:create"},
    "member":       {},  // 基础权限（参与项目）
}

// 项目权限常量
var ProjectPermissions = map[string][]string{
    "project_admin": {"*"},
    "developer":     {"defects:*", "agents:analyze", "agents:read_report"},
    "tester":        {"defects:read", "defects:create", "comments:*"},
    "viewer":        {"defects:read", "reports:read"},
}
```

**权限检查中间件简化**:
```go
func RequirePermission(permission string) gin.HandlerFunc {
    return func(c *gin.Context) {
        userID := GetUserID(c)
        
        // 1. 检查平台权限
        if isPlatformPermission(permission) {
            if checkPlatformRole(userID, permission) {
                c.Next()
                return
            }
        }
        
        // 2. 检查项目权限
        projectID := getProjectID(c)
        if checkProjectRole(userID, projectID, permission) {
            c.Next()
            return
        }
        
        c.JSON(403, gin.H{"code": 403, "error": "无权限"})
        c.Abort()
    }
}
```

**PermissionPage 简化**: 
原来的复杂权限矩阵 UI 简化为**项目成员管理中的角色下拉选择**：
- 添加/编辑成员时选择角色即可
- 无需单独的"权限管理"页面（或降级为只读查看）

---

## 三、实施计划

### Phase 1: 基础改造（建议优先）

| 序号 | 需求 | 工作量估计 | 依赖 |
|------|------|-----------|------|
| P1-1 | 需求6: 移除组织概念 | 0.5d | 无 |
| P1-2 | 需求1.1: AI配置下拉改造 | 0.5d | 无 |
| P1-3 | 需求1.2: 全局项目切换器 | 1d | 无 |

### Phase 2: 核心功能

| 序号 | 需求 | 工作量估计 | 依赖 |
|------|------|-----------|------|
| P2-1 | 需求2: 仓库管理升级（模型+凭证+API） | 2d | P1-1 |
| P2-2 | 需求3: 个人信息管理页面 | 1.5d | P2-1(凭证部分) |
| P2-3 | 需求5: 用户管理增强（邀请+管理员创建） | 2d | P1-1 |

### Phase 3: 权限与通知

| 序号 | 需求 | 工作量估计 | 依赖 |
|------|------|-----------|------|
| P3-1 | 需求7: 简化权限模型 | 2d | P1-1, P2-3 |
| P3-2 | 需求4: 通知偏好配置 | 1.5d | P2-2(嵌入个人设置) |

**总计预估**: ~11 天

---

## 四、数据模型变更汇总

### 新增表

| 表名 | 对应需求 | 核心字段 |
|------|---------|---------|
| `repo_credentials` | N2 仓库管理 | user_id, type, provider, content(加密), masked_value |
| `invite_codes` | N5 用户管理 | code, inviter_id, max_used, expires_at |
| `user_notification_prefs` | N4 通知 | user_id, category, channel, enabled |

### 修改表

| 表名 | 变更 | 对应需求 |
|------|------|---------|
| `users` | +platform_role, +invited_by | N5, N7 |
| `project_repos` | +source_type, +credential_id, +agent_types, +default_branch | N2 |
| `project_ai_configs` | 无结构变化（前端行为改变） | N1 |

### 废弃表（不删除，停止使用）

| 表名 | 替代方案 | 对应需求 |
|------|---------|---------|
| `organizations` | Project 成为顶层 | N6 |
| `org_members` | project_members | N6 |
| `permissions` | 角色内置权限常量 | N7 |
| `role_permissions` | 同上 | N7 |

---

## 五、API 变更清单

### 新增 API

```
# 需求1 - 交互优化
GET    /api/v1/ai/providers                          # 获取支持的AI厂商/模型列表

# 需求2 - 仓库管理
GET    /api/v1/credentials                           # 我的凭证列表
POST   /api/v1/credentials                           # 创建凭证
PUT    /api/v1/credentials/:id                        # 更新凭证
DELETE /api/v1/credentials/:id                        # 删除凭证
POST   /api/v1/repos/:id/test-connection             # 测试仓库连接

# 需求3 - 个人信息
GET    /api/v1/users/me                              # 获取我的详细信息
PUT    /api/v1/users/me                              # 更新我的个人信息
PUT    /api/v1/users/me/agent-types                  # 更新我的AGENT身份

# 需求4 - 通知偏好
GET    /api/v1/notification-preferences              # 我的通知偏好
PUT    /api/v1/notification-preferences              # 更新通知偏好

# 需求5 - 用户管理
POST   /api/v1/invites                               # 生成邀请链接
GET    /api/v1/invites                               # 邀请链接列表
POST   /api/v1/invites/:code/accept                 # 接受邀请注册
POST   /api/v1/users                                 # 管理员创建用户
PUT    /api/v1/users/:id/platform-role               # 修改平台角色
```

### 修改 API

```
# 仓库相关 - 增加新字段
PUT    /api/v1/projects/:projectId/repos/:id         # body 增加 sourceType/credentialId/agentTypes

# 用户相关 - 返回新字段
GET    /api/v1/users/me                              # response 增加 platformRole/agentTypes/invitedBy
GET    /api/v1/users                                 # list 增加 platformRole 列
```

### 废弃 API

```
GET    /api/v1/orgs                                  # 组织列表
POST   /api/v1/orgs                                  # 创建组织
PUT    /api/v1/orgs/:id                              # 更新组织
DELETE /api/v1/orgs/:id                              # 删除组织
GET    /api/v1/orgs/:id/members                      # 组织成员
POST   /api/v1/orgs/:id/members                      # 添加组织成员
DELETE /api/v1/orgs/:id/members/:userId              # 移除组织成员
```

---

## 六、非功能性需求

### 6.1 安全要求

| 项目 | 要求 |
|------|------|
| 凭证存储 | AES-256-GCM 加密，密钥轮换机制 |
| 邀请码 | 32字节随机，HMAC-SHA256 签名校验 |
| 敏感接口 | 管理员操作全部记录审计日志 |
| 密码策略 | 管理员创建用户时强制随机密码（≥16位） |

### 6.2 兼容性要求

| 项目 | 要求 |
|------|------|
| 数据库迁移 | 向后兼容，不 DROP 任何表/列 |
| API 兼容 | 废弃 API 返回 301 重定向而非 404（过渡期 2 个版本） |
| 前端兼容 | LocalStorage 中的 `lastProjectId` 缺失时优雅降级到项目列表页 |
