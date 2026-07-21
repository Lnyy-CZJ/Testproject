# 缺陷管理平台 — 系统级完整测试计划

**版本**: v1.0  
**日期**: 2026-03-28  
**基于PRD**: PRD_缺陷管理平台 v1.0  
**覆盖范围**: 全部 46 个 API 端点 · 9 个前端页面 · 11 个数据模型 · 完整状态流转  
**编写人**: API测试员 🔌

---

## 目录

1. [测试概述](#1-测试概述)
2. [测试环境](#2-测试环境)
3. [测试数据准备](#3-测试数据准备)
4. [模块一：认证与用户管理](#4-模块一认证与用户管理) — 10 条
5. [模块二：组织管理](#5-模块二组织管理) — 9 条
6. [模块三：项目管理](#6-模块三项目管理) — 8 条
7. [模块四：迭代管理](#7-模块四迭代管理) — 12 条
8. [模块五：缺陷管理](#8-模块五缺陷管理) — 22 条
9. [模块六：缺陷状态流转](#9-模块六缺陷状态流转) — 15 条
10. [模块七：AGENT分析](#10-模块七agent分析) — 8 条
11. [模块八：评论与@提及](#11-模块八评论与提及) — 7 条
12. [模块九：修复任务](#12-模块九修复任务) — 9 条
13. [模块十：附件管理](#13-模块十附件管理) — 8 条
14. [模块十一：前端页面验证](#14-模块十一前端页面验证) — 16 条
15. [模块十二：安全性测试](#15-模块十二安全性测试) — 10 条
16. [模块十三：性能测试](#16-模块十三性能测试) — 7 条
17. [缺陷编号规则专项测试](#17-缺陷编号规则专项测试)
18. [已知问题与遗留风险](#18-已知问题与遗留风险)
19. [测试执行追踪矩阵](#19-测试执行追踪矩阵)
20. [通过标准与发布门禁](#20-通过标准与发布门禁)

---

## 1. 测试概述

### 1.1 测试目标

| 维度 | 目标 |
|------|------|
| 功能覆盖 | 覆盖 PRD 4.x 所有功能模块，100% API 端点验证 |
| 状态流转 | 验证 PRD 5.3 全部 12 条流转规则 |
| 数据完整性 | 验证 PRD 6.2 全部数据表字段约束 |
| 安全性 | JWT 认证、越权防护、输入校验 |
| 性能 | API 响应 < 500ms（PRD 8.1 要求） |
| 已知缺陷 | 跟踪并回归已修复的 5 个 PRD 符合度问题 |

### 1.2 测试范围

| 范围 | 包含 | 不包含 |
|------|------|--------|
| **后端API** | 全部 46 个端点（含静态文件服务） | — |
| **前端页面** | 9 个页面 + 2 个公共组件 | — |
| **数据模型** | 12 个模型全部字段验证 | — |
| **状态流转** | 11 个状态 · 12 条合法转换 | — |
| **集成** | 前后端联调、JWT 认证链 | 真实 LLM 接口调用 |
| **非功能** | 安全性、基础性能 | 压力测试、灾备恢复 |

### 1.3 测试方法

| 方法 | 工具 | 说明 |
|------|------|------|
| API 功能测试 | curl / httpie | 端点级别输入输出验证 |
| 数据库验证 | psql (PostgreSQL) | 数据持久化与约束验证 |
| 前端验证 | 浏览器手动 + DevTools | 页面渲染、路由守卫、交互 |
| 安全测试 | curl 构造异常请求 | 认证绕过、注入、越权 |
| 性能测试 | curl -w 计时 | 单请求响应时间测量 |

---

## 2. 测试环境

### 2.1 环境配置

| 组件 | 地址/配置 | 说明 |
|------|----------|------|
| 后端服务 | `http://localhost:8765` | Go + Gin |
| 前端服务 | `http://localhost:5678` | React + Vite |
| API 前缀 | `/api/v1` | 全部接口前缀 |
| 数据库 | 阿里云 RDS PostgreSQL, 库 `hi_claw`, schema `public` | — |
| Redis | 阿里云 Redis, db=1 | — |
| 测试账号 | admin / testuser1 / testuser2 | 见 3.1 |

### 2.2 前置条件

- [ ] 后端服务已启动且无报错
- [ ] 前端服务已启动且可访问
- [ ] 数据库连接正常
- [ ] Redis 连接正常
- [ ] 测试数据已初始化（见第 3 节）

---

## 3. 测试数据准备

### 3.1 测试账号

| 账号 | 密码 | 角色 | AGENT类型 | 用途 |
|------|------|------|-----------|------|
| admin | admin123 | 超级管理员 | product,ui,frontend,client,backend,test | 全功能测试 |
| testuser1 | test1234 | 普通用户 | frontend,backend | 缺陷分配测试 |
| testuser2 | test1234 | 普通用户 | ui,client | AGENT协作测试 |

> **注意**: admin 账号在 `main.go` 中自动初始化。testuser1/2 需通过注册接口创建，再通过 psql 更新 agentTypes。

```sql
-- 创建测试用户后更新 AGENT 类型
UPDATE users SET agent_types = 'frontend,backend' WHERE username = 'testuser1';
UPDATE users SET agent_types = 'ui,client' WHERE username = 'testuser2';
```

### 3.2 测试组织结构

```
测试组织 (TestOrg)
├── 测试项目 (TEST) — code: TEST
│   ├── Sprint-01 迭代
│   │   └── repo: https://github.com/example/test-repo
│   └── Sprint-02 迭代
└── (admin 为 org admin, testuser1/2 为 member)
```

### 3.3 数据初始化脚本

```bash
# Step 1: 注册测试用户
curl -X POST http://localhost:8765/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser1","email":"test1@test.com","password":"test1234"}'

curl -X POST http://localhost:8765/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser2","email":"test2@test.com","password":"test1234"}'

# Step 2: 更新 AGENT 类型（通过 psql）
psql -h <host> -U <user> -d hi_claw -c \
  "UPDATE users SET agent_types = 'frontend,backend' WHERE username = 'testuser1';"
psql -h <host> -U <user> -d hi_claw -c \
  "UPDATE users SET agent_types = 'ui,client' WHERE username = 'testuser2';"

# Step 3: 获取 JWT Token
TOKEN=$(curl -s -X POST http://localhost:8765/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | jq -r '.data.token')
echo "Token: $TOKEN"
```

---

## 4. 模块一：认证与用户管理

### TC-AUTH-001: 用户注册 — 正常注册

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/auth/register` |
| **前置** | 无 |
| **输入** | `{"username":"newuser","email":"new@test.com","password":"Pass123!","nickname":"新用户"}` |
| **预期** | HTTP 201，返回用户信息（不含密码），nickname 正确存储 |

**验证 SQL**:
```sql
SELECT id, username, email, nickname FROM users WHERE username = 'newuser';
-- 预期: 记录存在，password 非明文（bcrypt hash）
```

---

### TC-AUTH-002: 用户注册 — 重复用户名

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/auth/register` |
| **前置** | admin 已存在 |
| **输入** | `{"username":"admin","email":"other@test.com","password":"Pass123!"}` |
| **预期** | HTTP 400，返回用户名已存在错误 |

---

### TC-AUTH-003: 用户注册 — 参数校验

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/auth/register` |
| **前置** | 无 |
| **输入A** | `{"username":"","email":"a@b.com","password":"Pass123!"}` (空用户名) |
| **输入B** | `{"username":"ok","email":"invalid","password":"Pass123!"}` (无效邮箱) |
| **输入C** | `{"username":"ok","email":"a@b.com","password":"123"}` (弱密码) |
| **预期** | 均返回 HTTP 400，提示对应字段校验失败 |

---

### TC-AUTH-004: 用户登录 — 正常登录

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/auth/login` |
| **前置** | admin 账号存在 |
| **输入** | `{"username":"admin","password":"admin123"}` |
| **预期** | HTTP 200，返回 `{ code: 0, data: { token: "eyJ...", user: {...} } }` |
| **验证** | token 可正确解析为 JWT，包含 user_id |

```bash
# 解析 JWT payload
echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq .
```

---

### TC-AUTH-005: 用户登录 — 错误密码

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/auth/login` |
| **输入** | `{"username":"admin","password":"wrong"}` |
| **预期** | HTTP 401，返回认证失败 |

---

### TC-AUTH-006: 获取个人信息

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/profile` |
| **前置** | 已登录，持有有效 Token |
| **Header** | `Authorization: Bearer <token>` |
| **预期** | HTTP 200，返回当前用户信息，包含 agentTypes 字段 |
| **验证** | agentTypes 为逗号分隔字符串（如 "product,ui,frontend,client,backend,test"） |

---

### TC-AUTH-007: 更新个人信息 — 更新 AGENT 类型

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/profile` |
| **前置** | 已登录 |
| **输入** | `{"agentTypes":"frontend,backend,test"}` |
| **预期** | HTTP 200，返回更新后的用户信息 |

> ⚠️ **已知 Bug**: GORM `Updates(map)` 使用驼峰 key `agentTypes`，但数据库列名是 `agent_types`（snake_case），导致更新不生效。需通过 psql 直接验证或使用 snake_case key。

**验证 SQL**:
```sql
SELECT agent_types FROM users WHERE id = <current_user_id>;
```

---

### TC-AUTH-008: 获取用户列表

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/users` |
| **前置** | 已登录，至少有 2 个用户 |
| **预期** | HTTP 200，返回用户列表，不包含 password 字段 |

---

### TC-AUTH-009: 获取指定用户信息

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/users/:id` |
| **前置** | 已登录，目标用户存在 |
| **预期** | HTTP 200，返回指定用户信息 |
| **边界** | id 不存在时返回 404 |

---

### TC-AUTH-010: JWT 认证 — 无 Token 访问受保护接口

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/profile`（任意需认证接口） |
| **前置** | 不携带 Authorization header |
| **预期** | HTTP 401，返回未认证错误 |

**验证场景**:
- [ ] 完全不携带 header
- [ ] 携带无效 token（如 `Bearer invalid`）
- [ ] 携带过期 token

---

## 5. 模块二：组织管理

### TC-ORG-001: 创建组织

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/orgs` |
| **前置** | 已登录 |
| **输入** | `{"name":"测试组织","logo":"https://example.com/logo.png"}` |
| **预期** | HTTP 201，返回组织信息，id 自增 |

**验证 SQL**:
```sql
SELECT * FROM organizations WHERE name = '测试组织';
```

---

### TC-ORG-002: 创建组织 — 参数校验

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/orgs` |
| **输入A** | `{"name":""}` (空名称) |
| **输入B** | `{}` (缺少 name) |
| **预期** | HTTP 400，返回校验错误 |

---

### TC-ORG-003: 获取组织列表

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/orgs` |
| **前置** | 至少存在 1 个组织 |
| **预期** | HTTP 200，返回组织列表数组 |

---

### TC-ORG-004: 获取组织详情

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/orgs/:id` |
| **前置** | 组织存在 |
| **预期** | HTTP 200，返回组织详情 |
| **边界** | id 不存在返回 404 |

---

### TC-ORG-005: 更新组织信息

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/orgs/:id` |
| **输入** | `{"name":"更新后的组织名"}` |
| **预期** | HTTP 200，返回更新后的组织信息 |

---

### TC-ORG-006: 添加组织成员

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/orgs/:id/members` |
| **前置** | 组织存在，目标用户存在 |
| **输入** | `{"userId":<testuser1_id>,"role":"member"}` |
| **预期** | HTTP 201，成员添加成功 |

**验证 SQL**:
```sql
SELECT * FROM org_members WHERE organization_id = <org_id> AND user_id = <testuser1_id>;
```

---

### TC-ORG-007: 添加组织成员 — 重复添加

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/orgs/:id/members` |
| **前置** | testuser1 已是该组织成员 |
| **输入** | `{"userId":<testuser1_id>,"role":"admin"}` |
| **预期** | 返回错误（联合唯一约束 org_user） |

---

### TC-ORG-008: 移除组织成员

| 项目 | 内容 |
|------|------|
| **接口** | `DELETE /api/v1/orgs/:id/members/:memberId` |
| **前置** | 成员存在 |
| **预期** | HTTP 200，成员被移除 |

**验证 SQL**:
```sql
-- 确认记录已删除或软删除
SELECT * FROM org_members WHERE id = <member_id>;
```

---

### TC-ORG-009: 获取组织下的项目列表

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/orgs/:id/projects` |
| **前置** | 组织下已有项目 |
| **预期** | HTTP 200，返回项目列表 |

---

## 6. 模块三：项目管理

### TC-PROJ-001: 创建项目

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/projects` |
| **前置** | 组织存在 |
| **输入** | `{"orgId":<org_id>,"name":"测试项目","code":"TEST","description":"用于测试的项目"}` |
| **预期** | HTTP 201，返回项目信息，status 默认 `active` |

**验证 SQL**:
```sql
SELECT * FROM projects WHERE code = 'TEST';
-- 确认 defect_seq = 0, defect_seq_year_month 为空
```

---

### TC-PROJ-002: 创建项目 — 重复 code

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/projects` |
| **前置** | code=TEST 已存在 |
| **输入** | `{"orgId":<org_id>,"name":"另一个项目","code":"TEST"}` |
| **预期** | 返回错误（code 唯一约束） |

---

### TC-PROJ-003: 获取项目详情

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/projects/:id` |
| **前置** | 项目存在 |
| **预期** | HTTP 200，返回项目详情（含 defectSeq、defectSeqYearMonth） |

---

### TC-PROJ-004: 更新项目信息

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/projects/:id` |
| **输入** | `{"name":"更新后的项目名","description":"更新描述","status":"archived"}` |
| **预期** | HTTP 200，项目状态变为 `archived` |

---

### TC-PROJ-005: 添加项目成员

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/projects/:id/members` |
| **输入** | `{"userId":<testuser1_id>,"role":"developer"}` |
| **预期** | HTTP 201，成员添加成功 |

**角色枚举验证**: admin / developer / tester / visitor

---

### TC-PROJ-006: 移除项目成员

| 项目 | 内容 |
|------|------|
| **接口** | `DELETE /api/v1/projects/:id/members/:memberId` |
| **预期** | HTTP 200，成员被移除 |

---

### TC-PROJ-007: 项目成员角色枚举校验

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/projects/:id/members` |
| **输入** | `{"userId":<testuser2_id>,"role":"invalid_role"}` |
| **预期** | 校验不通过或正常创建（取决于后端是否校验枚举值） |

---

### TC-PROJ-008: 获取项目列表（通过组织）

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/orgs/:id/projects` |
| **预期** | 返回该组织下的所有项目 |

---

## 7. 模块四：迭代管理

### TC-ITER-001: 创建迭代

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/projects/:id/iterations` |
| **前置** | 项目存在 |
| **输入** | `{"name":"Sprint-01","startDate":"2026-03-01","endDate":"2026-03-15","goal":"完成首页开发"}` |
| **预期** | HTTP 201，返回迭代信息，status 默认 `planning` |

---

### TC-ITER-002: 获取迭代列表

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/projects/:id/iterations` |
| **前置** | 项目下有迭代 |
| **预期** | HTTP 200，返回迭代列表 |

---

### TC-ITER-003: 获取迭代详情

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/projects/:id/iterations/:iterationId` |
| **预期** | HTTP 200，返回迭代详情 |

---

### TC-ITER-004: 更新迭代信息

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/projects/:id/iterations/:iterationId` |
| **输入** | `{"name":"Sprint-01-Updated","status":"active"}` |
| **预期** | HTTP 200，迭代状态更新为 `active` |

**状态枚举验证**: planning / active / completed

---

### TC-ITER-005: 绑定代码仓库

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/projects/:id/iterations/:iterationId/repos` |
| **输入** | `{"repoUrl":"https://github.com/example/test-repo","repoName":"test-repo"}` |
| **预期** | HTTP 201，仓库绑定成功 |

**验证 SQL**:
```sql
SELECT * FROM iteration_repos WHERE iteration_id = <iter_id>;
```

---

### TC-ITER-006: 绑定仓库 — 重复绑定同一 URL

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/projects/:id/iterations/:iterationId/repos` |
| **前置** | 同一 iteration 已绑定该 repoUrl |
| **输入** | `{"repoUrl":"https://github.com/example/test-repo","repoName":"test-repo"}` |
| **预期** | 返回错误（联合唯一约束 iter_repo_url） |

---

### TC-ITER-007: 解绑代码仓库

| 项目 | 内容 |
|------|------|
| **接口** | `DELETE /api/v1/projects/:id/iterations/:iterationId/repos/:repoId` |
| **前置** | 仓库已绑定 |
| **预期** | HTTP 200，仓库解绑成功 |

---

### TC-ITER-008: 获取迭代下的缺陷列表

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/projects/:id/iterations/:iterationId/defects` |
| **前置** | 迭代下有缺陷 |
| **预期** | HTTP 200，返回缺陷列表 |

---

### TC-ITER-009: 迭代状态流转 — planning → active

| 项目 | 内容 |
|------|------|
| **操作** | 更新迭代 status 为 `active` |
| **预期** | 状态成功变更 |

---

### TC-ITER-010: 迭代状态流转 — active → completed

| 项目 | 内容 |
|------|------|
| **操作** | 更新迭代 status 为 `completed` |
| **预期** | 状态成功变更 |

---

### TC-ITER-011: 创建迭代 — 缺少必填字段

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/projects/:id/iterations` |
| **输入A** | `{}` (缺少 name) |
| **输入B** | `{"name":""}` (空名称) |
| **预期** | HTTP 400，返回校验错误 |

---

### TC-ITER-012: 获取不存在的迭代

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/projects/:id/iterations/999999` |
| **预期** | HTTP 404，返回迭代不存在 |

---

## 8. 模块五：缺陷管理

### TC-DEFECT-001: 创建缺陷 — 完整参数

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/defects` |
| **前置** | 迭代存在，已登录 |
| **输入** | ```json
{
  "iterationId": <iteration_id>,
  "title": "登录页面表单校验异常",
  "description": "在登录页面输入空用户名时，系统未给出提示信息",
  "severity": "major",
  "priority": "P1",
  "type": "functional",
  "tags": ["登录模块", "表单校验"]
}
``` |
| **预期** | HTTP 201，返回缺陷信息 |
| **验证** | code 格式为 `BUG-TEST-YYYYMM-NNN`，status 为 `pending_assign`，reporterId 为当前用户 |

---

### TC-DEFECT-002: 创建缺陷 — 默认值验证

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/defects` |
| **输入** | `{"iterationId":<id>,"title":"最小参数缺陷","description":"desc"}` |
| **预期** | severity 默认 `normal`，priority 默认 `P2`，type 默认 `functional`，status 默认 `pending_assign` |

---

### TC-DEFECT-003: 创建缺陷 — 参数校验

| 项目 | 内容 |
|------|------|
| **输入A** | `{"iterationId":0,"title":"t","description":"d"}` (iterationId 无效) |
| **输入B** | `{"title":"","description":"d"}` (缺少 iterationId) |
| **输入C** | `{"iterationId":<id>,"title":"","description":"d"}` (空标题) |
| **输入D** | `{"iterationId":<id>,"title":"t","description":""}` (空描述) |
| **预期** | 均返回 HTTP 400 |

---

### TC-DEFECT-004: 创建缺陷 — 标题长度边界

| 项目 | 内容 |
|------|------|
| **输入A** | title 为 200 字符（恰好 max） |
| **输入B** | title 为 201 字符（超限） |
| **预期** | A 成功创建（HTTP 201），B 返回 400 |

> ⚠️ **PRD 偏差**: PRD 要求标题限 100 字，数据库允许 200 字符。记录此偏差。

---

### TC-DEFECT-005: 获取缺陷列表 — 全量

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects` |
| **前置** | 已有缺陷数据 |
| **预期** | HTTP 200，返回 `{ list: [...], total: N, page: 1, size: 20 }` |
| **验证** | 缺陷包含 Assignee 和 Reporter 关联数据 |

---

### TC-DEFECT-006: 获取缺陷列表 — 按状态筛选

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects?status=pending_assign` |
| **预期** | 仅返回 status 为 `pending_assign` 的缺陷 |

---

### TC-DEFECT-007: 获取缺陷列表 — 按严重级别筛选

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects?severity=major` |
| **预期** | 仅返回 severity 为 `major` 的缺陷 |

---

### TC-DEFECT-008: 获取缺陷列表 — 按优先级筛选

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects?priority=P1` |
| **预期** | 仅返回 priority 为 `P1` 的缺陷 |

---

### TC-DEFECT-009: 获取缺陷列表 — 按缺陷类型筛选

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects?type=ui` |
| **预期** | 仅返回 type 为 `ui` 的缺陷 |

---

### TC-DEFECT-010: 获取缺陷列表 — 关键字搜索

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects?keyword=登录` |
| **预期** | 返回 title 或 code 中包含"登录"的缺陷（模糊匹配） |
| **验证** | 同时测试搜索缺陷编号，如 `keyword=BUG-TEST` |

---

### TC-DEFECT-011: 获取缺陷列表 — 按标签筛选

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects?tags=登录模块` |
| **前置** | 存在标签含"登录模块"的缺陷（逗号分隔存储） |
| **预期** | 返回标签包含"登录模块"的缺陷 |

**多标签筛选**:
```bash
# 测试多标签筛选
curl "http://localhost:8765/api/v1/defects?tags=登录模块,表单校验" \
  -H "Authorization: Bearer $TOKEN"
```

---

### TC-DEFECT-012: 获取缺陷列表 — 按处理人筛选

| 项目 | 内容 |
|------|------|
| **接口A** | `GET /api/v1/defects?assigneeId=<user_id>` |
| **接口B** | `GET /api/v1/defects?assigneeId=me` |
| **预期** | A 返回指定处理人的缺陷，B 返回当前用户的缺陷 |

---

### TC-DEFECT-013: 获取缺陷列表 — 按报告人筛选

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects?reporterId=me` |
| **预期** | 返回当前用户创建的缺陷 |

---

### TC-DEFECT-014: 获取缺陷列表 — 排序

| 项目 | 内容 |
|------|------|
| **接口A** | `GET /api/v1/defects?sortBy=created_at&orderBy=desc` (默认) |
| **接口B** | `GET /api/v1/defects?sortBy=priority&orderBy=asc` |
| **接口C** | `GET /api/v1/defects?sortBy=invalid_field` (非法排序字段) |
| **预期** | A/B 正确排序，C 回退到默认排序（created_at desc） |

**合法排序字段**: created_at, updated_at, priority, severity

---

### TC-DEFECT-015: 获取缺陷列表 — 分页

| 项目 | 内容 |
|------|------|
| **接口A** | `GET /api/v1/defects?page=1&size=5` |
| **接口B** | `GET /api/v1/defects?page=2&size=5` |
| **接口C** | `GET /api/v1/defects?page=0` (非法页码) |
| **接口D** | `GET /api/v1/defects?size=101` (超过上限) |
| **预期** | A/B 正确分页且不重叠，C 回退到 page=1，D 回退到 size=20 |

---

### TC-DEFECT-016: 获取缺陷列表 — 多条件组合筛选

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects?status=pending_assign&severity=major&priority=P1&keyword=登录&page=1&size=10` |
| **预期** | 所有条件 AND 组合过滤，分页正确 |

---

### TC-DEFECT-017: 获取缺陷详情

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects/:id` |
| **预期** | HTTP 200，返回完整缺陷详情，包含： |
| **验证字段** | defect（含 iteration, assignee, reporter） |
| | comments（按 created_at ASC 排序） |
| | fixTasks（按 created_at DESC 排序） |
| | reports（按 created_at DESC 排序） |
| | attachments |

---

### TC-DEFECT-018: 更新缺陷信息

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id` |
| **输入** | ```json
{
  "title": "更新后的标题",
  "severity": "fatal",
  "priority": "P0",
  "type": "security",
  "tags": ["安全","紧急"]
}
``` |
| **预期** | HTTP 200，字段全部更新，tags 以逗号分隔存储 |

---

### TC-DEFECT-019: 更新缺陷 — 部分更新

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id` |
| **输入** | `{"priority":"P3"}` (仅更新一个字段) |
| **预期** | HTTP 200，仅 priority 更新，其他字段不变 |

---

### TC-DEFECT-020: 获取不存在的缺陷

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects/999999` |
| **预期** | HTTP 404，返回缺陷不存在 |

---

### TC-DEFECT-021: 缺陷枚举值完整性

| 字段 | 合法值 |
|------|--------|
| severity | fatal, major, normal, minor, suggest |
| priority | P0, P1, P2, P3, P4 |
| type | functional, ui, performance, security, compatibility, other |
| status | new, pending_assign, pending_analysis, analyzing, pending_fix, fixing, pending_verify, fixed, completed, rejected, suspended |

**验证方式**: 分别用所有枚举值创建缺陷，确认全部成功。

---

### TC-DEFECT-022: 创建缺陷 — 空标签

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/defects` |
| **输入** | `{"iterationId":<id>,"title":"无标签缺陷","description":"desc","tags":[]}` |
| **预期** | HTTP 201，tags 字段为空字符串 |

---

## 9. 模块六：缺陷状态流转

> 基于 `isValidTransition()` 函数定义的合法转换（PRD 5.3）

### 状态流转规则速查

```
pending_assign  → pending_analysis    (分配缺陷)
pending_analysis → analyzing           (开始分析)
pending_analysis → rejected            (驳回)
analyzing        → pending_fix         (分析完成)
pending_fix      → fixing              (开始修复)
pending_fix      → suspended           (暂停)
fixing           → pending_verify      (修复完成)
fixing           → pending_fix         (回退)
pending_verify   → fixed               (验证通过)
pending_verify   → pending_fix         (验证失败回退)
fixed            → completed           (合并完成)
suspended        → pending_fix         (恢复)
```

### TC-STATUS-001: pending_assign → pending_analysis（分配缺陷）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/assign` |
| **前置** | 缺陷 status = `pending_assign` |
| **输入** | `{"assigneeId":<testuser1_id>}` |
| **预期** | HTTP 200，status 变为 `pending_analysis`，assigneeId 更新，返回 `agentAnalysisTriggered: true` |
| **验证** | 同时产生一条系统评论（如有实现） |

---

### TC-STATUS-002: pending_analysis → analyzing（开始分析）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/status` |
| **前置** | 缺陷 status = `pending_analysis` |
| **输入** | `{"status":"analyzing","comment":"开始分析此缺陷"}` |
| **预期** | HTTP 200，status 变为 `analyzing`，评论区新增评论 |

---

### TC-STATUS-003: pending_analysis → rejected（驳回缺陷）

| 项目 | 内容 |
|------|------|
| **方式A** | `PUT /api/v1/defects/:id/status` → `{"status":"rejected"}` |
| **方式B** | `PUT /api/v1/defects/:id/reject` → `{"reason":"不是缺陷"}` |
| **前置** | 缺陷 status = `pending_analysis` |
| **预期** | A 和 B 都成功，status 变为 `rejected` |
| **验证** | 方式 B 产生评论 "🚫 驳回原因: 不是缺陷" |

---

### TC-STATUS-004: analyzing → pending_fix（分析完成）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/status` |
| **输入** | `{"status":"pending_fix"}` |
| **预期** | status 变为 `pending_fix` |

---

### TC-STATUS-005: pending_fix → fixing（开始修复）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/status` |
| **输入** | `{"status":"fixing"}` |
| **预期** | status 变为 `fixing` |

---

### TC-STATUS-006: pending_fix → suspended（暂停）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/status` |
| **输入** | `{"status":"suspended"}` |
| **预期** | status 变为 `suspended` |

---

### TC-STATUS-007: fixing → pending_verify（修复完成）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/status` |
| **输入** | `{"status":"pending_verify"}` |
| **预期** | status 变为 `pending_verify` |

---

### TC-STATUS-008: fixing → pending_fix（回退）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/status` |
| **输入** | `{"status":"pending_fix","comment":"修复方案需要调整"}` |
| **预期** | status 回退为 `pending_fix`，评论区新增评论 |

---

### TC-STATUS-009: pending_verify → fixed（验证通过）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/verify` |
| **输入** | `{"passed":true,"comment":"验证通过，修复符合预期"}` |
| **预期** | status 变为 `fixed`，产生评论 "✅ 验证通过\n验证通过，修复符合预期" |

---

### TC-STATUS-010: pending_verify → pending_fix（验证失败）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/verify` |
| **输入** | `{"passed":false,"comment":"仍然有问题，请重新修复"}` |
| **预期** | status 回退为 `pending_fix`，产生评论 "❌ 验证失败\n仍然有问题，请重新修复" |

---

### TC-STATUS-011: fixed → completed（合并完成）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/status` |
| **输入** | `{"status":"completed"}` |
| **预期** | status 变为 `completed`（终态） |

---

### TC-STATUS-012: suspended → pending_fix（恢复）

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/defects/:id/status` |
| **输入** | `{"status":"pending_fix"}` |
| **预期** | status 变为 `pending_fix` |

---

### TC-STATUS-013: 非法状态转换 — 应拒绝

以下转换应全部返回 HTTP 400：

| 当前状态 | 目标状态 | 应拒绝原因 |
|---------|---------|-----------|
| `pending_assign` | `analyzing` | 必须先分配 |
| `pending_assign` | `fixing` | 跳过分析阶段 |
| `completed` | `pending_fix` | 已完成不可回退 |
| `rejected` | `pending_analysis` | 驳回为终态 |
| `fixed` | `pending_verify` | 已验证不可重复 |
| `new` | *任何状态* | new 无出口转换 |

**测试方式**: 对每种非法转换调用 `ChangeStatus`，确认返回 400。

---

### TC-STATUS-014: 驳回操作 — 任意状态下可驳回

| 项目 | 内容 |
|------|------|
| **前置** | 缺陷处于 `pending_fix` 状态 |
| **接口** | `PUT /api/v1/defects/:id/reject` |
| **输入** | `{"reason":"需求变更，此缺陷不再处理"}` |
| **预期** | 无论当前状态如何（除终态外），RejectDefect 均应成功 |
| **验证** | `RejectDefect` 不经过 `isValidTransition` 校验 |

---

### TC-STATUS-015: 完整生命周期 — 端到端

| 步骤 | 操作 | 预期状态 |
|------|------|---------|
| 1 | 创建缺陷 | `pending_assign` |
| 2 | 分配处理人 | `pending_analysis` |
| 3 | 开始分析 | `analyzing` |
| 4 | 分析完成 | `pending_fix` |
| 5 | 开始修复 | `fixing` |
| 6 | 修复完成 | `pending_verify` |
| 7 | 验证失败（回退） | `pending_fix` |
| 8 | 重新修复 | `fixing` |
| 9 | 修复完成 | `pending_verify` |
| 10 | 验证通过 | `fixed` |
| 11 | 合并完成 | `completed` |

**验证**: 每步后查询缺陷详情确认状态正确。

---

## 10. 模块七：AGENT分析

### TC-AGENT-001: 触发分析 — 单 AGENT 类型

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/agents/analyze` |
| **前置** | 缺陷存在，用户已登录 |
| **输入** | `{"defectId":<defect_id>,"agentTypes":["frontend"]}` |
| **预期** | HTTP 200，创建分析报告，返回 reportId |

**验证 SQL**:
```sql
SELECT * FROM analysis_reports WHERE defect_id = <defect_id> AND agent_type = 'frontend';
```

---

### TC-AGENT-002: 触发分析 — 多 AGENT 类型

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/agents/analyze` |
| **输入** | `{"defectId":<defect_id>,"agentTypes":["frontend","backend","test"]}` |
| **预期** | HTTP 200，创建 3 份分析报告，agent_type 分别为 frontend, backend, test |

---

### TC-AGENT-003: 触发分析 — 全部 6 种 AGENT 类型

| 项目 | 内容 |
|------|------|
| **输入** | `{"defectId":<defect_id>,"agentTypes":["product","ui","frontend","client","backend","test"]}` |
| **预期** | 创建 6 份报告，涵盖全部 AGENT 类型 |

> ⚠️ **注意**: 需确保被分配用户的 agentTypes 包含全部 6 种类型。

---

### TC-AGENT-004: 触发分析 — AGENT 类型校验

| 项目 | 内容 |
|------|------|
| **输入** | `{"defectId":<defect_id>,"agentTypes":["invalid_type"]}` |
| **预期** | 返回错误（非预定义 AGENT 类型） |

---

### TC-AGENT-005: 获取分析报告

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/agents/reports/:reportId` |
| **前置** | 报告存在 |
| **预期** | HTTP 200，返回报告详情（含 analysis, solution JSON） |

---

### TC-AGENT-006: 获取缺陷的分析报告列表

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects/:id/reports` |
| **前置** | 缺陷有多个分析报告 |
| **预期** | HTTP 200，返回报告列表，按 created_at DESC 排序 |

---

### TC-AGENT-007: 分析报告编号格式

| 项目 | 内容 |
|------|------|
| **验证** | 创建分析报告后，检查 reportCode 格式 |
| **预期** | reportCode 格式为 `AR-YYYYMM-NNN`（根据代码实现确认） |

---

### TC-AGENT-008: 触发分析 — 缺陷不存在

| 项目 | 内容 |
|------|------|
| **输入** | `{"defectId":999999,"agentTypes":["frontend"]}` |
| **预期** | HTTP 404 或 400，返回缺陷不存在 |

---

## 11. 模块八：评论与@提及

### TC-COMMENT-001: 发布评论 — 基本评论

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/defects/:id/comments` |
| **输入** | `{"content":"这个缺陷需要前端处理"}` |
| **预期** | HTTP 201，返回评论信息，isAgentMessage = false |

**验证 SQL**:
```sql
SELECT * FROM comments WHERE defect_id = <defect_id> ORDER BY created_at DESC LIMIT 1;
```

---

### TC-COMMENT-002: 发布评论 — 带 @提及

| 项目 | 内容 |
|------|------|
| **输入** | `{"content":"@testuser1 请协助看一下前端部分","mentions":[<testuser1_id>]}` |
| **预期** | HTTP 201，评论成功创建，mentions 数据存储 |

---

### TC-COMMENT-003: 获取评论列表

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects/:id/comments` |
| **前置** | 缺陷有评论 |
| **预期** | HTTP 200，返回评论列表，按 created_at ASC 排序，每条评论包含 User 关联数据 |

---

### TC-COMMENT-004: 评论为空内容

| 项目 | 内容 |
|------|------|
| **输入** | `{"content":""}` |
| **预期** | HTTP 400，评论内容不能为空 |

---

### TC-COMMENT-005: AGENT 消息标识

| 项目 | 内容 |
|------|------|
| **验证** | 查看 AGENT 分析产生的评论 |
| **预期** | isAgentMessage = true，agent_type 字段非空 |

---

### TC-COMMENT-006: 状态变更自动评论

| 项目 | 内容 |
|------|------|
| **操作** | 调用 `ChangeStatus` 带 `comment` 参数 |
| **预期** | 系统自动创建评论，内容格式为 `🔄 状态变更为: <status>\n<comment>` |

---

### TC-COMMENT-007: 验证操作自动评论

| 项目 | 内容 |
|------|------|
| **操作A** | `VerifyDefect` with `passed: true` |
| **操作B** | `VerifyDefect` with `passed: false` |
| **预期A** | 产生评论 `✅ 验证通过\n<comment>` |
| **预期B** | 产生评论 `❌ 验证失败\n<comment>` |

---

## 12. 模块九：修复任务

### TC-FIX-001: 创建修复任务

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/defects/:id/fix-tasks` |
| **前置** | 缺陷存在 |
| **输入** | `{"agentType":"frontend","targetBranch":"test/sprint-01"}` |
| **预期** | HTTP 201，创建修复任务，status 默认 `pending`，taskCode 格式正确 |

---

### TC-FIX-002: 创建修复任务 — 默认参数

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/defects/:id/fix-tasks` |
| **输入** | `{}` 或不传 body |
| **预期** | 使用默认值创建修复任务 |

---

### TC-FIX-003: 获取修复任务列表

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects/:id/fix-tasks` |
| **预期** | HTTP 200，返回修复任务列表 |

---

### TC-FIX-004: 获取修复任务详情

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/fix-tasks/:taskId` |
| **预期** | HTTP 200，返回修复任务详情（含关联的 defect） |

---

### TC-FIX-005: 更新修复任务状态

| 项目 | 内容 |
|------|------|
| **接口** | `PUT /api/v1/fix-tasks/:taskId` |
| **输入A** | `{"status":"planning"}` |
| **输入B** | `{"status":"executing"}` |
| **输入C** | `{"status":"completed"}` |
| **预期** | 状态依次更新 |

**状态枚举**: pending → planning → executing → testing → completed / failed

---

### TC-FIX-006: 修复任务编号格式

| 项目 | 内容 |
|------|------|
| **验证** | 创建修复任务后检查 taskCode |
| **预期** | taskCode 格式为 `FT-YYYYMM-NNN`（根据代码实现确认） |

---

### TC-FIX-007: 更新修复任务 — 带结果信息

| 项目 | 内容 |
|------|------|
| **输入** | ```json
{
  "status": "completed",
  "fixBranch": "fix/BUG-TEST-202603-001-001",
  "prUrl": "https://github.com/example/test-repo/pull/1",
  "result": "{\"filesChanged\":[\"src/index.ts\"]}"
}
``` |
| **预期** | 字段全部更新，completedAt 自动设置 |

---

### TC-FIX-008: 一个缺陷多个修复任务

| 项目 | 内容 |
|------|------|
| **操作** | 对同一缺陷创建 2 个修复任务 |
| **预期** | 两个任务独立，均关联同一 defect_id |

---

### TC-FIX-009: 修复任务状态枚举验证

| 项目 | 内容 |
|------|------|
| **合法值** | pending, planning, executing, testing, completed, failed |
| **输入** | `{"status":"invalid"}` |
| **预期** | 校验不通过或正常更新（取决于后端校验逻辑） |

---

## 13. 模块十：附件管理

### TC-ATTACH-001: 上传图片文件

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/defects/:id/attachments` |
| **Content-Type** | `multipart/form-data` |
| **输入** | file = `test_image.png` (500KB PNG 图片) |
| **预期** | HTTP 201，返回附件信息，fileType = `image` |

**验证**:
- [ ] 返回的 fileUrl 以 `/uploads/` 开头
- [ ] fileName 与上传文件名一致
- [ ] fileSize 正确
- [ ] 文件物理存储在 `uploads/YYYY/MM/DD/` 目录下
- [ ] 通过 `http://localhost:8765/uploads/...` 可访问文件

---

### TC-ATTACH-002: 上传 PDF 文件

| 项目 | 内容 |
|------|------|
| **输入** | file = `test_doc.pdf` (1MB PDF) |
| **预期** | HTTP 201，fileType = `pdf` |

---

### TC-ATTACH-003: 上传压缩包

| 项目 | 内容 |
|------|------|
| **输入** | file = `test_logs.zip` (2MB ZIP) |
| **预期** | HTTP 201，fileType = `archive` |

---

### TC-ATTACH-004: 上传文档文件

| 项目 | 内容 |
|------|------|
| **输入** | file = `test_notes.txt` (10KB 文本文件) |
| **预期** | HTTP 201，fileType = `document` |

---

### TC-ATTACH-005: 上传超大文件（超限）

| 项目 | 内容 |
|------|------|
| **输入** | file = `large_file.bin` (15MB，超过 10MB 限制) |
| **预期** | HTTP 400，返回文件大小超限错误 |

---

### TC-ATTACH-006: 上传不支持的文件类型

| 项目 | 内容 |
|------|------|
| **输入** | file = `malicious.exe` |
| **预期** | 返回错误（不在允许的文件类型列表中） |

**允许的类型**（前端限制）: `.jpg,.jpeg,.png,.gif,.webp,.pdf,.doc,.docx,.xls,.xlsx,.txt,.md,.json,.xml,.zip,.tar,.gz,.log`

> ⚠️ **PRD 偏差**: PRD 要求支持视频文件，当前仅支持图片/文档/压缩包。

---

### TC-ATTACH-007: 获取附件列表

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects/:id/attachments` |
| **前置** | 缺陷有附件 |
| **预期** | HTTP 200，返回附件列表 |

---

### TC-ATTACH-008: 删除附件

| 项目 | 内容 |
|------|------|
| **接口** | `DELETE /api/v1/defects/:id/attachments/:attachmentId` |
| **前置** | 附件存在 |
| **预期** | HTTP 200，附件被删除 |
| **验证** | 文件物理文件也被删除；再次通过 URL 访问返回 404 |

---

## 14. 模块十一：前端页面验证

### TC-FE-001: 登录页面

| 项目 | 内容 |
|------|------|
| **URL** | `http://localhost:5678/login` |
| **验证** | [ ] 页面正常渲染，无控制台错误 |
| | [ ] 渐变背景 + 毛玻璃效果正常显示 |
| | [ ] 用户名/密码输入框可用 |
| | [ ] 登录按钮可点击 |
| | [ ] 输入正确凭证后跳转到 Dashboard |
| | [ ] 输入错误凭证显示错误提示 |

---

### TC-FE-002: 注册页面

| 项目 | 内容 |
|------|------|
| **URL** | `http://localhost:5678/register` |
| **验证** | [ ] 页面正常渲染 |
| | [ ] 注册表单包含用户名、邮箱、密码、确认密码 |
| | [ ] 注册成功后跳转到登录页 |
| | [ ] 重复用户名显示错误提示 |

---

### TC-FE-003: 路由守卫 — 未登录跳转

| 项目 | 内容 |
|------|------|
| **操作** | 清除 token 后访问 `http://localhost:5678/` |
| **预期** | 自动重定向到 `/login` |

---

### TC-FE-004: Dashboard 工作台

| 项目 | 内容 |
|------|------|
| **URL** | `http://localhost:5678/` |
| **验证** | [ ] 5 个统计卡片正常显示（总缺陷数、待处理、进行中、已完成等） |
| | [ ] 最近缺陷列表正常显示 |
| | [ ] 快速入口按钮可点击 |
| | [ ] AGENT 能力展示区域正常 |

---

### TC-FE-005: 组织管理页面

| 项目 | 内容 |
|------|------|
| **URL** | `http://localhost:5678/orgs` |
| **验证** | [ ] 组织列表以卡片布局显示 |
| | [ ] 创建组织弹窗/表单可用 |
| | [ ] 成员管理功能可用 |
| | [ ] 空状态引导显示 |

---

### TC-FE-006: 项目详情页面

| 项目 | 内容 |
|------|------|
| **URL** | `http://localhost:5678/projects/:id` |
| **验证** | [ ] 项目基本信息正确显示 |
| | [ ] 迭代管理 Tab 可用（创建/编辑/列表） |
| | [ ] 仓库绑定/解绑功能可用 |
| | [ ] 项目成员管理可用 |

---

### TC-FE-007: 缺陷列表页面

| 项目 | 内容 |
|------|------|
| **URL** | `http://localhost:5678/defects` |
| **验证** | [ ] 统计概览卡片显示正确 |
| | [ ] 筛选面板可展开/折叠 |
| | [ ] 按状态/严重级别/优先级/类型/标签筛选可用 |
| | [ ] 关键字搜索可用 |
| | [ ] 列表/看板视图切换可用 |
| | [ ] 分页正常工作 |
| | [ ] 点击缺陷可跳转详情页 |

---

### TC-FE-008: 缺陷创建页面

| 项目 | 内容 |
|------|------|
| **URL** | `http://localhost:5678/defects/create` |
| **验证** | [ ] 表单包含所有必填和可选字段 |
| | [ ] 严重级别/优先级/类型下拉选择可用 |
| | [ ] 标签输入可用 |
| | [ ] 附件上传可用 |
| | [ ] 创建成功后跳转到缺陷详情页 |

---

### TC-FE-009: 缺陷详情页面 — 基本信息展示

| 项目 | 内容 |
|------|------|
| **URL** | `http://localhost:5678/defects/:id` |
| **验证** | [ ] 缺陷编号、标题、描述正确显示 |
| | [ ] 严重级别、优先级、类型标签正确显示 |
| | [ ] 状态进度条正确显示当前状态 |
| | [ ] 处理人和报告人信息正确 |
| | [ ] 创建/更新时间正确显示 |

---

### TC-FE-010: 缺陷详情页面 — 状态流转操作

| 项目 | 内容 |
|------|------|
| **验证** | [ ] 分配按钮可用（pending_assign 状态） |
| | [ ] 状态变更按钮显示正确的可流转目标 |
| | [ ] 验证按钮可用（pending_verify 状态） |
| | [ ] 驳回按钮可用 |
| | [ ] 状态变更后页面自动刷新 |

---

### TC-FE-011: 缺陷详情页面 — 编辑功能

| 项目 | 内容 |
|------|------|
| **验证** | [ ] 编辑按钮存在 |
| | [ ] 点击编辑弹出编辑弹窗 |
| | [ ] 可修改标题、描述、严重级别、优先级、类型、标签 |
| | [ ] 保存后页面信息更新 |

---

### TC-FE-012: 缺陷详情页面 — AGENT 分析

| 项目 | 内容 |
|------|------|
| **验证** | [ ] AGENT 类型多选 UI 可用（6 种类型全显示） |
| | [ ] 触发分析按钮可用 |
| | [ ] 分析报告列表正确显示 |
| | [ ] 报告详情可展开查看 |

---

### TC-FE-013: 缺陷详情页面 — 评论区

| 项目 | 内容 |
|------|------|
| **验证** | [ ] 评论文本框和发送按钮可用 |
| | [ ] @提及功能可用（弹出成员选择） |
| | [ ] 评论列表按时间正序显示 |
| | [ ] AGENT 消息有特殊标识 |

---

### TC-FE-014: 缺陷详情页面 — 附件 Tab

| 项目 | 内容 |
|------|------|
| **验证** | [ ] 附件上传组件可用 |
| | [ ] 图片附件显示缩略图预览 |
| | [ ] 非 image 类型显示文件图标和下载链接 |
| | [ ] 删除附件有确认弹窗 |
| | [ ] 文件大小和上传时间正确显示 |

---

### TC-FE-015: 缺陷详情页面 — 修复任务 Tab

| 项目 | 内容 |
|------|------|
| **验证** | [ ] 修复任务列表正确显示 |
| | [ ] 任务状态、分支信息正确 |
| | [ ] 创建修复任务按钮可用 |

---

### TC-FE-016: 侧边栏与导航

| 项目 | 内容 |
|------|------|
| **验证** | [ ] 侧边栏菜单结构正确（工作台 + 缺陷管理 + 组织树） |
| | [ ] AGENT 信息卡片显示 |
| | [ ] 待处理缺陷 Badge 正确显示 |
| | [ ] 菜单项点击可正确导航 |
| | [ ] 响应式布局正常 |

---

## 15. 模块十二：安全性测试

### TC-SEC-001: JWT Token 认证

| 场景 | 预期 |
|------|------|
| 不携带 Token 访问受保护接口 | HTTP 401 |
| Token 格式错误（如 `Bearer xyz`） | HTTP 401 |
| Token 过期 | HTTP 401 |
| 有效 Token | HTTP 200 |

---

### TC-SEC-002: SQL 注入防护

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects?keyword='; DROP TABLE defects; --` |
| **预期** | 返回空结果或 400，不崩溃，defects 表不被删除 |
| **验证SQL** | `SELECT count(*) FROM defects;` — 确认表完整 |

---

### TC-SEC-003: XSS 防护

| 项目 | 内容 |
|------|------|
| **操作** | 创建缺陷 title = `<script>alert('xss')</script>` |
| **预期** | 脚本不被执行，前端正确转义显示 |

---

### TC-SEC-004: 越权访问 — 修改他人缺陷

| 项目 | 内容 |
|------|------|
| **操作** | 用 testuser1 的 Token 尝试修改 testuser2 创建的缺陷 |
| **预期** | 当前系统无 RBAC 校验（所有认证用户可操作所有缺陷） |
| **风险** | ⚠️ 记录为已知风险，PRD 3.1 要求角色权限控制 |

---

### TC-SEC-005: 越权访问 — 获取其他用户信息

| 项目 | 内容 |
|------|------|
| **操作** | 通过 `/api/v1/users/:id` 获取其他用户信息 |
| **预期** | 当前无权限校验，返回完整用户信息（不含密码） |

---

### TC-SEC-006: 文件上传安全

| 项目 | 内容 |
|------|------|
| **场景A** | 上传 `.exe` 可执行文件 |
| **场景B** | 上传 `.php` 文件 |
| **场景C** | 上传文件名包含 `../`（路径遍历） |
| **预期** | 不允许的文件类型被拒绝，路径遍历被防护 |

---

### TC-SEC-007: CORS 配置

| 项目 | 内容 |
|------|------|
| **场景A** | 从 `http://localhost:5678` 发起跨域请求 |
| **场景B** | 从 `http://evil.com` 发起跨域请求 |
| **预期** | A 成功（AllowOrigins），B 被拒绝 |

---

### TC-SEC-008: 密码安全

| 项目 | 内容 |
|------|------|
| **验证SQL** | `SELECT password FROM users WHERE username = 'admin';` |
| **预期** | 密码为 bcrypt hash，非明文 |

---

### TC-SEC-009: API 响应不泄露敏感信息

| 项目 | 内容 |
|------|------|
| **验证** | 检查所有 API 响应不包含 password、token 等敏感字段 |
| **预期** | User 模型 password 字段 JSON tag 为 `-`，不序列化 |

---

### TC-SEC-010: 请求方法限制

| 项目 | 内容 |
|------|------|
| **操作** | 对 `GET /api/v1/defects` 发送 POST 请求 |
| **操作** | 对 `POST /api/v1/defects` 发送 GET 请求 |
| **预期** | Gin 框架返回 405 Method Not Allowed |

---

## 16. 模块十三：性能测试

### TC-PERF-001: API 响应时间 — 登录接口

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/auth/login` |
| **PRD 要求** | < 500ms |
| **测量方式** | `curl -w '%{time_total}\n' -o /dev/null -s -X POST ...` |
| **通过标准** | 95th 百分位 < 500ms |

```bash
# 执行 10 次取平均值
for i in {1..10}; do
  curl -w '%{time_total}\n' -o /dev/null -s -X POST http://localhost:8765/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"admin123"}'
done
```

---

### TC-PERF-002: API 响应时间 — 缺陷列表

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects` |
| **PRD 要求** | < 500ms |
| **场景** | 50 条缺陷数据 |

---

### TC-PERF-003: API 响应时间 — 缺陷详情

| 项目 | 内容 |
|------|------|
| **接口** | `GET /api/v1/defects/:id` |
| **PRD 要求** | < 500ms |
| **场景** | 缺陷含 5 条评论、3 个附件、2 个修复任务 |

---

### TC-PERF-004: API 响应时间 — 创建缺陷

| 项目 | 内容 |
|------|------|
| **接口** | `POST /api/v1/defects` |
| **PRD 要求** | < 500ms |

---

### TC-PERF-005: 前端页面加载时间

| 项目 | 内容 |
|------|------|
| **PRD 要求** | < 2 秒 |
| **测量方式** | Chrome DevTools → Network → DOMContentLoaded |
| **页面** | Dashboard / 缺陷列表 / 缺陷详情 |

---

### TC-PERF-006: 并发请求测试

| 项目 | 内容 |
|------|------|
| **场景** | 10 个并发请求同时访问 `GET /api/v1/defects` |
| **通过标准** | 全部返回 200，无 5xx 错误，响应时间 < 1s |

```bash
# 并发测试
for i in {1..10}; do
  curl -s -o /dev/null -w '%{http_code} %{time_total}\n' \
    -H "Authorization: Bearer $TOKEN" \
    http://localhost:8765/api/v1/defects &
done
wait
```

---

### TC-PERF-007: 文件上传性能

| 项目 | 内容 |
|------|------|
| **场景** | 上传 5MB PDF 文件 |
| **通过标准** | 上传完成 < 3 秒 |

---

## 17. 缺陷编号规则专项测试

### TC-CODE-001: 编号格式验证

| 项目 | 内容 |
|------|------|
| **规则** | `BUG-{项目代码}-{YYYYMM}-{NNN}` |
| **示例** | `BUG-TEST-202603-001` |
| **验证** | 项目代码大写，月份 6 位，序号 3 位补零 |

---

### TC-CODE-002: 序号递增

| 项目 | 内容 |
|------|------|
| **操作** | 同一项目下连续创建 3 个缺陷 |
| **预期** | 编号分别为 `BUG-TEST-202603-001`, `BUG-TEST-202603-002`, `BUG-TEST-202603-003` |

---

### TC-CODE-003: 月份切换序号重置

| 项目 | 内容 |
|------|------|
| **前置** | 3 月创建了 3 个缺陷（序号到 003） |
| **操作** | 模拟 4 月创建缺陷（需修改数据库 project 的 defect_seq_year_month） |
| **预期** | 4 月第一个缺陷编号为 `BUG-TEST-202604-001` |

> **测试方法**: 通过 psql 直接更新 `defect_seq_year_month` 为旧值，再创建缺陷验证序号重置。

```sql
-- 模拟月份切换
UPDATE projects SET defect_seq = 0, defect_seq_year_month = '202602' WHERE id = <project_id>;
```

---

### TC-CODE-004: 不同项目编号独立

| 项目 | 内容 |
|------|------|
| **操作** | 项目 A 创建缺陷后，项目 B 也创建缺陷 |
| **预期** | 各项目独立计数，互不影响 |

---

## 18. 已知问题与遗留风险

### 18.1 已修复的 PRD 符合度问题（回归验证）

| # | 问题 | 修复状态 | 回归测试用例 |
|---|------|---------|-------------|
| 1 | 缺陷编号格式 | ✅ 已修复 | TC-CODE-001 ~ TC-CODE-004 |
| 2 | 标签筛选功能 | ✅ 已修复 | TC-DEFECT-011 |
| 3 | 附件上传功能 | ✅ 已修复 | TC-ATTACH-001 ~ TC-ATTACH-008 |
| 4 | 缺陷编辑功能 | ✅ 已修复 | TC-FE-011, TC-DEFECT-018 ~ TC-DEFECT-019 |
| 5 | 多 AGENT 类型选择 | ✅ 已修复 | TC-AGENT-002, TC-AGENT-003 |
| 6 | CLIENT AGENT 类型缺失 | ✅ 已修复 | TC-AGENT-003 |

### 18.2 已知 Bug

| # | Bug 描述 | 严重程度 | 影响 | 临时方案 |
|---|---------|---------|------|---------|
| 1 | GORM UpdateProfile 驼峰/蛇形字段名不匹配，agentTypes 更新不生效 | Medium | 用户无法通过 API 更新 AGENT 类型 | 通过 psql 直接更新数据库 |

### 18.3 PRD 偏差

| # | PRD 要求 | 实际实现 | 偏差程度 |
|---|---------|---------|---------|
| 1 | 标题限 100 字 | 数据库允许 200 字符 | Low |
| 2 | 附件支持视频 | 仅支持图片/文档/压缩包 | Medium |
| 3 | 关联需求字段 | 未实现 | Low（PRD 标注为可选） |
| 4 | 智能推荐分配对象 | 未实现 | Low |
| 5 | RBAC 权限控制 | 所有认证用户可操作所有资源 | Medium |
| 6 | 操作审计日志 | 未实现 | Low |
| 7 | 新建 → 待分配 状态转换 | 创建直接为 pending_assign，跳过 new | Low |
| 8 | `new` 状态无出口转换 | `new` 为"死胡同"状态 | Low |

### 18.4 待扩展功能（非本期）

- AGENT 真正的 AI 分析能力（接入 LLM）
- 自动修复的 Git 操作（clone, branch, commit, PR）
- WebSocket 实时通知
- 统计报表
- 需求管理
- 测试用例管理

---

## 19. 测试执行追踪矩阵

### 19.1 模块覆盖统计

| 模块 | 测试用例数 | API 端点覆盖 | PRD 章节映射 |
|------|-----------|-------------|-------------|
| 认证与用户管理 | 10 | 6/6 | PRD 3.x |
| 组织管理 | 9 | 7/7 | PRD 4.1.1 |
| 项目管理 | 8 | 5/5 | PRD 4.1.2 |
| 迭代管理 | 12 | 7/7 | PRD 4.1.3 |
| 缺陷管理 | 22 | 8/8 | PRD 4.2 |
| 缺陷状态流转 | 15 | 4/4 (assign/status/verify/reject) | PRD 5.x |
| AGENT 分析 | 8 | 3/3 | PRD 4.3 |
| 评论与@提及 | 7 | 2/2 | PRD 4.4 |
| 修复任务 | 9 | 4/4 | PRD 4.5 |
| 附件管理 | 8 | 3/3 | PRD 2.3 |
| 前端页面 | 16 | — | PRD 4.x |
| 安全性 | 10 | — | PRD 8.2 |
| 性能 | 7 | — | PRD 8.1 |
| **合计** | **141** | **46/46 (100%)** | — |

### 19.2 API 端点覆盖明细

| # | 方法 | 路径 | 覆盖用例 |
|---|------|------|---------|
| 1 | POST | `/auth/register` | TC-AUTH-001~003 |
| 2 | POST | `/auth/login` | TC-AUTH-004~005 |
| 3 | GET | `/profile` | TC-AUTH-006, TC-SEC-001 |
| 4 | PUT | `/profile` | TC-AUTH-007 |
| 5 | GET | `/users` | TC-AUTH-008 |
| 6 | GET | `/users/:id` | TC-AUTH-009 |
| 7 | POST | `/orgs` | TC-ORG-001~002 |
| 8 | GET | `/orgs` | TC-ORG-003 |
| 9 | GET | `/orgs/:id` | TC-ORG-004 |
| 10 | PUT | `/orgs/:id` | TC-ORG-005 |
| 11 | POST | `/orgs/:id/members` | TC-ORG-006~007 |
| 12 | DELETE | `/orgs/:id/members/:memberId` | TC-ORG-008 |
| 13 | GET | `/orgs/:id/projects` | TC-ORG-009 |
| 14 | POST | `/projects` | TC-PROJ-001~002 |
| 15 | GET | `/projects/:id` | TC-PROJ-003 |
| 16 | PUT | `/projects/:id` | TC-PROJ-004 |
| 17 | POST | `/projects/:id/members` | TC-PROJ-005~007 |
| 18 | DELETE | `/projects/:id/members/:memberId` | TC-PROJ-006 |
| 19 | POST | `/projects/:id/iterations` | TC-ITER-001, 011 |
| 20 | GET | `/projects/:id/iterations` | TC-ITER-002 |
| 21 | GET | `/projects/:id/iterations/:iterationId` | TC-ITER-003, 012 |
| 22 | PUT | `/projects/:id/iterations/:iterationId` | TC-ITER-004 |
| 23 | POST | `/projects/:id/iterations/:iterationId/repos` | TC-ITER-005~006 |
| 24 | DELETE | `/projects/:id/iterations/:iterationId/repos/:repoId` | TC-ITER-007 |
| 25 | GET | `/projects/:id/iterations/:iterationId/defects` | TC-ITER-008 |
| 26 | GET | `/defects` | TC-DEFECT-005~016, TC-PERF-002 |
| 27 | POST | `/defects` | TC-DEFECT-001~004, 022, TC-PERF-004 |
| 28 | GET | `/defects/:id` | TC-DEFECT-017, 020, TC-PERF-003 |
| 29 | PUT | `/defects/:id` | TC-DEFECT-018~019 |
| 30 | PUT | `/defects/:id/assign` | TC-STATUS-001 |
| 31 | PUT | `/defects/:id/status` | TC-STATUS-002~008, 011~012, 013 |
| 32 | PUT | `/defects/:id/verify` | TC-STATUS-009~010 |
| 33 | PUT | `/defects/:id/reject` | TC-STATUS-003, 014 |
| 34 | POST | `/defects/:id/attachments` | TC-ATTACH-001~006, TC-PERF-007 |
| 35 | GET | `/defects/:id/attachments` | TC-ATTACH-007 |
| 36 | DELETE | `/defects/:id/attachments/:attachmentId` | TC-ATTACH-008 |
| 37 | POST | `/defects/:id/comments` | TC-COMMENT-001~004 |
| 38 | GET | `/defects/:id/comments` | TC-COMMENT-003 |
| 39 | POST | `/agents/analyze` | TC-AGENT-001~004, 008 |
| 40 | GET | `/agents/reports/:reportId` | TC-AGENT-005 |
| 41 | GET | `/defects/:id/reports` | TC-AGENT-006 |
| 42 | POST | `/defects/:id/fix-tasks` | TC-FIX-001~002 |
| 43 | GET | `/defects/:id/fix-tasks` | TC-FIX-003 |
| 44 | GET | `/fix-tasks/:taskId` | TC-FIX-004 |
| 45 | PUT | `/fix-tasks/:taskId` | TC-FIX-005, 007, 009 |
| 46 | GET | `/uploads/*` | TC-ATTACH-001 (文件访问验证) |

---

## 20. 通过标准与发布门禁

### 20.1 测试通过标准

| 标准 | 要求 |
|------|------|
| **功能测试** | 141 条用例中 ≥ 95% 通过（允许 ≤ 7 条因已知风险/PRD偏差失败） |
| **状态流转** | 15 条状态流转用例 100% 通过 |
| **安全性** | 10 条安全测试中无 P0/P1 级问题 |
| **性能** | API 响应时间满足 PRD 8.1 要求（< 500ms） |
| **回归测试** | 已修复的 6 个 PRD 符合度问题全部通过回归 |

### 20.2 发布门禁清单

- [ ] 全部 TC-STATUS-* 用例通过（状态流转核心功能）
- [ ] 全部 TC-AUTH-* 用例通过（认证安全）
- [ ] 全部 TC-SEC-* 用例通过（无 P0/P1 安全问题）
- [ ] TC-PERF-001~004 平均响应时间 < 500ms
- [ ] TC-FE-001~016 前端页面无控制台错误
- [ ] 已知 Bug 列表无新增 P0/P1
- [ ] PRD 偏差已记录并有明确的版本规划

### 20.3 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| GORM agentTypes 更新 Bug | Medium | 通过 psql 绕过，代码修复排入下个迭代 |
| 无 RBAC 权限控制 | Medium | 当前为原型阶段，后续实现基于角色的访问控制 |
| AGENT 分析为模拟数据 | Low | AI 能力接入排入下期规划 |
| 文件上传未支持视频 | Low | 扩展允许的文件类型即可 |

---

## 附录 A：测试执行记录模板

| 用例ID | 执行日期 | 执行人 | 结果 | 备注 |
|--------|---------|--------|------|------|
| TC-AUTH-001 | YYYY-MM-DD | — | ✅/❌ | |
| TC-AUTH-002 | YYYY-MM-DD | — | ✅/❌ | |

## 附录 B：快速执行脚本

```bash
#!/bin/bash
# 快速冒烟测试脚本
BASE="http://localhost:8765/api/v1"

echo "=== 1. 登录 ==="
TOKEN=$(curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | jq -r '.data.token')
[ "$TOKEN" = "null" ] && echo "❌ 登录失败" && exit 1
echo "✅ 登录成功"

echo "=== 2. 获取个人信息 ==="
curl -s $BASE/profile -H "Authorization: Bearer $TOKEN" | jq '.code'

echo "=== 3. 获取组织列表 ==="
curl -s $BASE/orgs -H "Authorization: Bearer $TOKEN" | jq '.code'

echo "=== 4. 获取缺陷列表 ==="
curl -s "$BASE/defects?page=1&size=5" -H "Authorization: Bearer $TOKEN" | jq '{code, total: .data.total}'

echo "=== 5. 无 Token 访问 ==="
CODE=$(curl -s -o /dev/null -w '%{http_code}' $BASE/profile)
[ "$CODE" = "401" ] && echo "✅ 未认证返回 401" || echo "❌ 期望 401 实际 $CODE"

echo "=== 冒烟测试完成 ==="
```

---

**文档结束**

_本测试计划覆盖缺陷管理平台全部功能模块，共 141 条测试用例，对应 PRD v1.0 所有章节要求。测试计划将随系统迭代持续更新。_
