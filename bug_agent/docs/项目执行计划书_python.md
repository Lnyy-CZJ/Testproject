# BugAgent Python 重构 — 项目执行计划书

**项目代号**: BugAgent-Py
**版本**: v1.0
**日期**: 2026-06-06
**编制依据**: PRD_缺陷管理平台_python.md v1.0-python
**项目周期**: 11 周（约 3 个月）
**开发模式**: 单人全栈（分阶段渐进交付）

---

## 目录

- [一、项目总览](#一项目总览)
- [二、阶段零：基础设施与契约锁定（第 1 周）](#二阶段零基础设施与契约锁定第-1-周)
- [三、阶段一：CRUD 平台（第 2~4 周）](#三阶段一crud-平台第-24-周)
- [四、阶段二：Agent 分析接入（第 5~6 周）](#四阶段二agent-分析接入第-56-周)
- [五、阶段三：代码修复与 PR 生命周期（第 7~8 周）](#五阶段三代码修复与-pr-生命周期第-78-周)
- [六、阶段四：信号接入、检索与质量洞察（第 9~10 周）](#六阶段四信号接入检索与质量洞察第-910-周)
- [七、阶段五：加固与上线（第 11 周）](#七阶段五加固与上线第-11-周)
- [八、全局风险管理](#八全局风险管理)
- [九、开发规范与约定](#九开发规范与约定)
- [十、交付清单](#十交付清单)

---

## 一、项目总览

### 1.1 项目目标

用 **Python** 重新实现 BugAgent 后端服务，保持：

| 维度 | 要求 |
|------|------|
| 业务逻辑 | 与 Go 版 v5.8 完全一致（14 个功能模块、13 种缺陷状态、24 条转移规则） |
| API 契约 | 200+ 端点路径、请求响应格式、认证方式与现有 React 前端 **100% 兼容** |
| 数据库 Schema | 30+ 张表与现有 PostgreSQL 数据库结构一致 |
| 代码量 | Go版 ~12000行（不含前端）→ Python版目标 ~5000行（不含前端） |

### 1.2 项目时间线

```
第 1 周   第 2 周   第 3 周   第 4 周   第 5 周   第 6 周   第 7 周   第 8 周   第 9 周   第 10 周  第 11 周
   │         │         │         │         │         │         │         │         │         │         │
   ▼         ▼         ▼         ▼         ▼         ▼         ▼         ▼         ▼         ▼         ▼
┌─────┐ ┌──────────────────────┐ ┌────────────────────┐ ┌────────────────────┐ ┌────────────────────┐ ┌─────┐
│ S0  │ │         S1           │ │        S2          │ │        S3          │ │        S4          │ │ S5  │
│基础 │ │     CRUD 平台        │ │   Agent 分析接入   │ │ 代码修复+PR生命周期 │ │ 信号+检索+质量洞察 │ │加固 │
│设施 │ │  (用户/项目/缺陷)     │ │  (LangGraph+流式)  │ │  (8步流水线+VCS)   │ │  (问题池+RAG+报表) │ │上线 │
└─────┘ └──────────────────────┘ └────────────────────┘ └────────────────────┘ └────────────────────┘ └─────┘
  1周              3周                    2周                   2周                   2周                1周
```

### 1.3 各阶段任务量与 API 分组

| 阶段 | 周次 | 工期 | 新增文件数 | 代码量估计 | 覆盖 API 分组 | 累计覆盖 |
|------|------|------|-----------|-----------|--------------|---------|
| S0 | W1 | 1w | ~15 | ~800行 | 0 | 骨架 |
| S1 | W2~W4 | 3w | ~35 | ~2500行 | 14/22 | 14/22 |
| S2 | W5~W6 | 2w | ~15 | ~1200行 | +2 | 16/22 |
| S3 | W7~W8 | 2w | ~12 | ~800行 | +3 | 19/22 |
| S4 | W9~W10 | 2w | ~12 | ~700行 | +3 | 22/22 |
| S5 | W11 | 1w | ~5 | ~300行 | 0 | 22/22 |
| **合计** | **W1~W11** | **11w** | **~94** | **~6300行** | **22/22** | **100%** |

### 1.4 里程碑节点

| 里程碑 | 时间点 | 标志 | 前置条件 |
|--------|--------|------|---------|
| M0 | W1 结束 | 服务启动 + `/docs` 可访问 | S0 全部完成 |
| M1 | W4 结束 | 前端可登录、创建项目、管理缺陷 | S1 全部完成 |
| M2 | W6 结束 | AI 分析成功生成报告 | S2 全部完成 |
| M3 | W8 结束 | AI 修复生成合法代码 | S3 全部完成 |
| M4 | W10 结束 | 完整业务闭环可走通 | S4 全部完成 |
| M5 | W11 结束 | Docker 一键部署，前端零改动正常运行 | S5 全部完成 |

---

## 二、阶段零：基础设施与契约锁定（第 1 周）

### 2.1 目标

服务可启动，数据库可连接，全部 API Schema 已通过 Pydantic 定义完毕，这意味着 **22 组 API 的输入输出契约已经锁定**，后续开发只需要"填充实现"。

### 2.2 每日任务分解

#### Day 1（周一）：项目骨架搭建

| # | 任务 | 产出文件 | 预计 | 依赖 |
|---|------|---------|------|------|
| D1-1 | 创建项目目录结构 | `bug_agent_py/` 完整目录 | 0.5h | — |
| D1-2 | 编写 `pyproject.toml` | 依赖声明（20+ 个库） | 0.5h | D1-1 |
| D1-3 | 编写 `app/config.py` | Pydantic Settings 配置类 | 1h | D1-2 |
| D1-4 | 编写 `app/main.py` | FastAPI 应用工厂 + 生命周期 | 1h | D1-3 |
| D1-5 | 编写 `docker-compose.yml` | PostgreSQL + Redis + App | 0.5h | — |
| D1-6 | 编写 `Makefile` | `make dev` / `make test` / `make migrate` | 0.5h | — |
| D1-7 | 验证 `uvicorn app.main:app --reload` 可启动 | 返回 200 at `/healthz` | 0.5h | D1-4 |

**Day 1 小计：4.5h**

#### Day 2（周二）：数据库基础设施

| # | 任务 | 产出文件 | 预计 | 依赖 |
|---|------|---------|------|------|
| D2-1 | 编写 `app/infrastructure/database.py` | AsyncEngine + session factory | 1h | D1-4 |
| D2-2 | 编写 `app/infrastructure/redis.py` | Redis async client | 0.5h | D1-3 |
| D2-3 | 编写 `app/infrastructure/security.py` | JWT encode/decode + bcrypt + AES-GCM | 1.5h | D1-3 |
| D2-4 | 编写 `app/models/base.py` | DeclarativeBase + TimestampMixin | 0.5h | D2-1 |
| D2-5 | 初始化 Alembic | `alembic init` + `env.py` 配置 | 1h | D2-1 |

**Day 2 小计：4.5h**

#### Day 3（周三）：ORM 模型定义（上半）

| # | 任务 | 产出文件 | 预计 | 依赖 |
|---|------|---------|------|------|
| D3-1 | 编写用户/认证模型 | `app/models/user.py`, `auth.py` | 1h | D2-4 |
| D3-2 | 编写项目/成员模型 | `app/models/project.py` | 1h | D2-4 |
| D3-3 | 编写仓库/AI配置模型 | `app/models/repo.py`, `ai_config.py` | 1h | D2-4 |
| D3-4 | 编写迭代模型 | `app/models/iteration.py` | 0.5h | D2-4 |
| D3-5 | 编写缺陷/附件模型 | `app/models/defect.py`, `attachment.py` | 1h | D2-4 |

**Day 3 小计：4.5h**

#### Day 4（周四）：ORM 模型定义（下半）+ 首次迁移

| # | 任务 | 产出文件 | 预计 | 依赖 |
|---|------|---------|------|------|
| D4-1 | 编写分析报告/修复任务模型 | `app/models/analysis_report.py`, `fix_task.py` | 1h | D2-4 |
| D4-2 | 编写信号/问题簇/连接器模型 | `app/models/signal.py` | 1h | D2-4 |
| D4-3 | 编写通知/审计/权限模型 | `app/models/notification.py`, `audit.py`, `rbac.py` | 1h | D2-4 |
| D4-4 | 编写 Agent记忆/MCP/技能/Token 模型 | `app/models/agent_memory.py`, `token_usage.py` | 0.5h | D2-4 |
| D4-5 | 编写其余系统表模型 | `app/models/` 剩余文件 | 0.5h | D2-4 |
| D4-6 | 生成首次 Alembic 迁移并执行 | `alembic revision --autogenerate` | 0.5h | D4-1~5 |

**Day 4 小计：4.5h**

#### Day 5（周五）：Pydantic Schema + 路由骨架

| # | 任务 | 产出文件 | 预计 | 依赖 |
|---|------|---------|------|------|
| D5-1 | 编写 `app/schemas/common.py` | `ApiResult[T]`, `PaginatedResponse[T]` | 1h | — |
| D5-2 | 编写认证/用户相关 Schema | `app/schemas/auth.py` | 1h | D3-1 |
| D5-3 | 编写缺陷相关 Schema | `app/schemas/defect.py`（~15 个 Schema 类） | 1.5h | D3-5 |
| D5-4 | 编写项目/迭代/仓库 Schema | `app/schemas/project.py` | 1h | D3-2~4 |
| D5-5 | 编写 `app/api/v1/router.py` | 22 个 `include_router` 注册 + 全部路由文件骨架 | 1h | D5-1~4 |
| D5-6 | 编写 `tests/conftest.py` | async test client + test DB fixture | 1h | D2-1 |

**Day 5 小计：6.5h（含加班）**

### 2.3 阶段零交付验收

```
□ uvicorn app.main:app 可启动，无 import 错误
□ GET /healthz 返回 {"status": "ok"}
□ /docs 显示 22 组 API 全部路由（标注 "Not Implemented"）
□ alembic upgrade head 成功创建全部 40+ 张表
□ docker-compose up 一键启动 PostgreSQL + Redis + App
□ pytest 基础测试套件可通过（至少 conftest.py 可运行）
```

### 2.4 阶段零风险

| 风险 | 概率 | 缓解措施 |
|------|------|---------|
| ORM 模型字段与现有数据库不匹配 | 中 | 严格对照 PRD 第八章，`autogenerate` 后手动 review diff |
| Alembic 对已有数据库生成空迁移 | 低 | 首次使用 `--autogenerate`，后续手动编写迁移 |
| Pydantic camelCase alias 配置遗漏 | 中 | 写 1 个测试用例验证序列化输出 |

---

## 三、阶段一：CRUD 平台（第 2~4 周）

### 3.1 目标

实现 14 个 API 分组中除 Agent/修复/信号/检索外的全部端点。此阶段完成时，前端可以：
- 登录/注册/管理个人信息
- 创建项目、迭代、仓库、AI 配置
- 创建/浏览/筛选/编辑缺陷
- 缺陷全状态流转（分配→分析占位→修复占位→验证→完成→驳回→重新打开）
- 评论、通知、权限管控、审计日志

### 3.2 第一周（W2）：用户、认证与项目

#### Day 1（周一）：认证模块

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W2D1-1 | 实现注册 `POST /auth/register` | `api/v1/auth.py` + `services/auth_service.py` | 1.5h | test_auth.py |
| W2D1-2 | 实现登录 `POST /auth/login` | 同上 | 1h | test_auth.py |
| W2D1-3 | 实现登出 `POST /auth/logout`（Token黑名单） | 同上 + `infrastructure/security.py` | 0.5h | test_auth.py |
| W2D1-4 | 实现个人信息 CRUD | `api/v1/auth.py` | 1h | test_auth.py |
| W2D1-5 | 实现 JWT Depends + 强制改密检查 | `api/deps.py` | 1h | test_auth.py |

**Day 1 小计：5h**

#### Day 2（周二）：用户管理

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W2D2-1 | 实现用户列表 `GET /users` | `api/v1/users.py` + `services/user_service.py` | 1h | test_users.py |
| W2D2-2 | 实现用户创建/重置密码 | 同上 | 0.5h | test_users.py |
| W2D2-3 | 实现 Agent 身份分配 `PUT /users/:id/agent-types` | 同上 | 0.5h | test_users.py |
| W2D2-4 | 实现平台角色修改 | 同上 | 0.5h | test_users.py |
| W2D2-5 | 实现邀请码验证/接受 | `api/v1/users.py` + `services/invite_service.py` | 1h | test_users.py |

**Day 2 小计：3.5h**

#### Day 3（周三）：项目 CRUD

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W2D3-1 | 实现项目 CRUD `GET/POST/PUT /projects` | `api/v1/projects.py` + `services/project_service.py` | 1.5h | test_projects.py |
| W2D3-2 | 实现项目成员管理 | 同上 | 1h | test_projects.py |
| W2D3-3 | 实现用户项目列表 `GET /user/projects` | 同上 | 0.5h | test_projects.py |

**Day 3 小计：3h**

#### Day 4（周四）：仓库、AI 配置、迭代

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W2D4-1 | 实现仓库 CRUD `GET/POST/PUT/DELETE /projects/:id/repos` | `api/v1/repos.py` + `services/repo_service.py` | 1h | test_repos.py |
| W2D4-2 | 实现 AI 配置 CRUD | `api/v1/ai_configs.py` + `services/ai_config_service.py` | 1h | test_ai_config.py |
| W2D4-3 | 实现迭代 CRUD | `api/v1/iterations.py` + `services/iteration_service.py` | 1h | test_iterations.py |
| W2D4-4 | 实现迭代仓库绑定/解绑 | 同上 | 0.5h | test_iterations.py |
| W2D4-5 | 实现仓库分支列表 | `api/v1/repos.py` | 0.5h | test_repos.py |

**Day 4 小计：4h**

#### Day 5（周五）：单元测试补全 + AI 目录 + 凭证骨架

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W2D5-1 | AI 厂商/模型目录 CRUD | `api/v1/ai_configs.py`（admin 端点）| 1h |
| W2D5-2 | 凭证管理（个人 + 平台）骨架 | `api/v1/credentials.py` + `services/credential_service.py` | 1.5h |
| W2D5-3 | 补全 W2 所有模块的单元测试 | `tests/test_api/test_auth.py` 等 | 2h |
| W2D5-4 | 前后端联调：认证 + 项目列表 | 用现有前端验证 | 0.5h |

**Day 5 小计：5h**

### 3.3 第二周（W3）：缺陷管理与工作流

#### Day 1（周一）：缺陷 CRUD

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W3D1-1 | 实现缺陷创建 `POST /defects`（含缺陷编号自动生成） | `api/v1/defects.py` + `services/defect_service.py` | 1.5h | test_defects.py |
| W3D1-2 | 实现缺陷详情 `GET /defects/:id` | 同上 | 0.5h | test_defects.py |
| W3D1-3 | 实现缺陷列表 `GET /defects`（多维度筛选） | 同上 | 1.5h | test_defects.py |
| W3D1-4 | 实现缺陷更新 `PUT /defects/:id` | 同上 | 0.5h | test_defects.py |

**Day 1 小计：4h**

#### Day 2（周二）：缺陷高级功能

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W3D2-1 | 实现对话式缺陷草稿创建 | `api/v1/defects.py` + `services/defect_draft.py` | 2h | test_defects.py |
| W3D2-2 | 实现附件上传/下载/删除 | `api/v1/defects.py` + `services/attachment_service.py` | 1.5h | test_attachments.py |
| W3D2-3 | 实现缺陷合并 `PUT /defects/:id/merge` | `api/v1/defects.py` | 0.5h | test_defects.py |

**Day 2 小计：4h**

#### Day 3（周三）：状态机核心

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W3D3-1 | 实现 `WorkflowService` 完整状态机 | `services/workflow_service.py` | 1.5h | test_workflow.py |
| W3D3-2 | 实现状态流转 `PUT /defects/:id/transition` | `api/v1/workflow.py` | 1h | test_workflow.py |
| W3D3-3 | 实现可流转状态查询 `GET /defects/:id/transitions` | 同上 | 0.5h | test_workflow.py |
| W3D3-4 | 实现状态历史 `GET /defects/:id/history` | 同上 | 0.5h | test_workflow.py |
| W3D3-5 | 实现批量流转 `POST /workflow/batch` | 同上 | 1h | test_workflow.py |

**Day 3 小计：4.5h**

#### Day 4（周四）：状态流转联调 + 缺陷分配

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W3D4-1 | 实现缺陷分配 `PUT /defects/:id/assign` | `api/v1/defects.py` | 1h | test_defects.py |
| W3D4-2 | 实现负责人推荐 `GET /defects/:id/recommend-assignees` | `services/recommendation.py` | 1.5h | test_recommend.py |
| W3D4-3 | 实现 Agent 类型推荐 `GET /defects/:id/recommend-agents` | 同上 | 0.5h | test_recommend.py |
| W3D4-4 | 实现驳回/重新打开/重新分析 | `api/v1/defects.py`（reject/reopen/reanalyze） | 1h | test_workflow.py |
| W3D4-5 | 状态机全覆盖测试（24 条合法转移 + 逆向非法转移） | `tests/test_services/test_workflow.py` | 1h | — |

**Day 4 小计：5h**

#### Day 5（周五）：工作流 E2E + 评论

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W3D5-1 | 实现评论 CRUD | `api/v1/defects.py` + `services/comment_service.py` | 1.5h |
| W3D5-2 | 前后端联调：缺陷全流程（创建→分配→分析占位→修复占位→验证→完成） | 用现有前端走一遍完整流程 | 1h |
| W3D5-3 | 修复联调中发现的问题 | — | 1.5h |
| W3D5-4 | 写 W3 模块的单元测试 | `tests/test_api/test_defects.py` | 1h |

**Day 5 小计：5h**

### 3.4 第三周（W4）：权限、通知、审计

#### Day 1（周一）：RBAC 权限模型

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W4D1-1 | 实现 RBAC 数据模型 + 种子数据（角色/权限） | `services/rbac_service.py` | 1.5h | test_rbac.py |
| W4D1-2 | 实现权限校验 Depends（全局/项目/缺陷三级） | `api/deps.py` | 1.5h | test_rbac.py |
| W4D1-3 | 实现 RBAC API（角色列表/权限列表/分配/查询） | `api/v1/rbac_audit.py` | 1h | test_rbac.py |
| W4D1-4 | Redis 缓存 + 5分钟 TTL + 角色变更时失效 | `services/rbac_service.py` | 1h | test_rbac.py |

**Day 1 小计：5h**

#### Day 2（周二）：权限全覆盖 + 审计

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W4D2-1 | 给 S1 已实现的所有端点加上权限 Depends | `api/v1/*.py` 全量 | 2h | — |
| W4D2-2 | 实现审计日志服务（缓冲批量写入） | `services/audit_service.py` | 1h | test_audit.py |
| W4D2-3 | 实现审计日志 API（列表/统计） | `api/v1/rbac_audit.py` | 0.5h | test_audit.py |
| W4D2-4 | 实现审计中间件（自动记录操作） | `middleware/audit_middleware.py` | 1h | test_audit.py |

**Day 2 小计：4.5h**

#### Day 3（周三）：通知系统

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W4D3-1 | 实现站内通知 CRUD | `services/notification_service.py` | 1.5h | test_notification.py |
| W4D3-2 | 实现通知 API（列表/未读数/标记已读） | `api/v1/notifications.py` | 1h | test_notification.py |
| W4D3-3 | 实现个人通知偏好 | `services/notification_pref_service.py` | 1h | test_notification.py |
| W4D3-4 | 实现项目通知策略 | `services/project_notification_service.py` | 1h | test_notification.py |

**Day 3 小计：4.5h**

#### Day 4（周四）：邮件 + Webhook + 项目设置

| # | 任务 | 文件 | 预计 | 测试 |
|---|------|------|------|------|
| W4D4-1 | 实现邮件发送（SMTP） | `services/notification_service.py` | 1h | — |
| W4D4-2 | 实现 Webhook 通知 | 同上 | 1h | test_notification.py |
| W4D4-3 | 实现模板管理 | `services/notification_service.py` | 0.5h | — |
| W4D4-4 | 实现平台设置（SMTP配置/测试） | `api/v1/notifications.py` + `services/platform_setting_service.py` | 1.5h | — |

**Day 4 小计：4h**

#### Day 5（周五）：S1 收尾

| # | 任务 | 预计 |
|---|------|------|
| W4D5-1 | 前后端联调：权限 + 通知 + 审计 | 1.5h |
| W4D5-2 | S1 所有模块的单元测试 + API 集成测试补全 | 2h |
| W4D5-3 | 修复联调中发现的问题 | 1h |
| W4D5-4 | Code Review 自检（mypy + ruff + 测试覆盖率 > 80%） | 0.5h |

**Day 5 小计：5h**

### 3.5 阶段一交付验收

```
□ 14 个 API 分组（认证/用户/项目/仓库/AI配置/迭代/缺陷/附件/工作流/通知/权限/审计/评论/凭证）全部可用
□ 状态机 24 条转移规则全部通过测试，逆向非法转移返回 422
□ 权限校验在 3 个级别（全局/项目/缺陷）均生效
□ 前端可完成：登录 → 创建项目 → 创建迭代 → 创建缺陷 → 分配 → 状态流转 → 评论 → 通知
□ API 响应 camelCase 字段与前端一致（agentTypes, createdAt, defectId）
□ 测试覆盖率 > 80%
```

### 3.6 阶段一风险

| 风险 | 概率 | 缓解措施 |
|------|------|---------|
| 状态机遗漏边界条件 | 中 | 参数化测试覆盖 24×13=312 种组合 |
| 权限 Depends 遗漏端点 | 中 | 写测试扫描全部路由的 Depends 配置 |
| camelCase 序列化遗漏 | 低 | `model_config = {"populate_by_name": True}` 全局配置 |

---

## 四、阶段二：Agent 分析接入（第 5~6 周）

### 4.1 目标

实现 LangGraph 驱动的 AI 分析能力：Planner→Executor→Analyzer→PostProcess 四节点工作流，支持流式 SSE 输出、多 AI 厂商 fallback、Agent 记忆注入与提取、Celery 优先级调度。

### 4.2 第一周（W5）：Agent 核心

#### Day 1（周一）：Agent 基础设施

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W5D1-1 | 实现 LLM 客户端封装（OpenAI/Anthropic/DeepSeek/智谱/DashScope） | `agent/llm_client.py` | 2h |
| W5D1-2 | 实现多配置 fallback 机制 | `agent/llm_client.py` | 1h |
| W5D1-3 | 实现 `AnalysisState` TypedDict | `agent/state.py` | 0.5h |
| W5D1-4 | 实现 5 个 MCP 工具（search_code/read_file/list_directory/trace_call/find_api_handler） | `agent/tools/*.py` | 1.5h |

**Day 1 小计：5h**

#### Day 2（周二）：StateGraph 构建

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W5D2-1 | 实现 Planner Node（LLM 输出探索计划 JSON） | `agent/nodes/planner.py` | 2h |
| W5D2-2 | 实现 Executor Node（按计划调用工具 + SafetyGate） | `agent/nodes/executor.py` | 1.5h |
| W5D2-3 | 实现 Analyzer Node（LLM 分析 + Prompt 构建） | `agent/nodes/analyzer.py` | 1.5h |

**Day 2 小计：5h**

#### Day 3（周三）：后处理 + Graph 编译

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W5D3-1 | 实现 PostProcess Node（JSON 提取 + 字段归一化 + Token 记录） | `agent/nodes/post_process.py` | 1.5h |
| W5D3-2 | 实现 Graph 编译（四节点 + 重试条件路由） | `agent/graph.py` | 1.5h |
| W5D3-3 | 实现 LangGraph PostgresCheckpointer（会话持久化） | `agent/callbacks/checkpointer.py` | 1h |
| W5D3-4 | 集成测试：Graph 完整运行一次 | `tests/test_agent/test_analysis_graph.py` | 1h |

**Day 3 小计：5h**

#### Day 4（周四）：分析 API

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W5D4-1 | 实现 `POST /agents/analyze` 非流式分析 | `api/v1/agents.py` + `services/agent_service.py` | 1.5h |
| W5D4-2 | 实现分析报告存储（AnalysisReport 模型） | `services/agent_service.py` | 0.5h |
| W5D4-3 | 实现 `GET /agents/reports/:reportId` | `api/v1/agents.py` | 0.5h |
| W5D4-4 | 实现 `GET /defects/:id/reports` | `api/v1/agents.py` | 0.5h |
| W5D4-5 | 实现分析触发时的状态机联动（pending_analysis→analyzing→pending_fix） | `services/agent_service.py` | 1h |

**Day 4 小计：4h**

#### Day 5（周五）：LLM Prompt 迁移 + 测试

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W5D5-1 | 从 Go [prompts.go] 迁移 5 种 Agent 分析 Prompt 模板 | `agent/prompts/analysis.py` | 1.5h |
| W5D5-2 | 从 Go [prompt_engine.go] 迁移修复/探索 Prompt 模板 | `agent/prompts/fix.py`, `explorer.py` | 1h |
| W5D5-3 | Agent 分析端到端测试（真实 LLM 调用） | `tests/test_agent/test_e2e_analysis.py` | 2h |

**Day 5 小计：4.5h**

### 4.3 第二周（W6）：流式 + 记忆 + 调度

#### Day 1（周一）：流式分析

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W6D1-1 | 实现 `POST /agents/analyze/stream`（StreamingResponse + LangGraph stream_events） | `api/v1/agents.py` | 2h |
| W6D1-2 | 实现 StreamEvent Schema（与 SSE 事件格式对齐） | `schemas/analysis.py` | 0.5h |
| W6D1-3 | 实现流式→轮询降级机制 | `api/v1/agents.py` | 1.5h |
| W6D1-4 | 集成测试：流式分析端到端（验证 SSE 事件格式与前端兼容） | `tests/test_agent/test_stream_analysis.py` | 1h |

**Day 1 小计：5h**

#### Day 2（周二）：Agent 记忆

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W6D2-1 | 实现 Agent 记忆 CRUD（项目/迭代两级） | `services/agent_memory_service.py` | 1.5h |
| W6D2-2 | 实现记忆 API | `api/v1/agent_memory.py` | 0.5h |
| W6D2-3 | 实现记忆注入回调（分析前注入相关记忆到 Prompt） | `agent/nodes/memory.py` | 1h |
| W6D2-4 | 实现记忆提取回调（分析后从结果提取知识） | `agent/nodes/memory.py` | 1.5h |
| W6D2-5 | 实现 Jaccard 去重（相似度 > 0.8 合并更新） | `services/agent_memory_service.py` | 0.5h |

**Day 2 小计：5h**

#### Day 3（周三）：Celery 任务调度

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W6D3-1 | 实现 `celery_app.py` 配置 | `infrastructure/celery_app.py` | 1h |
| W6D3-2 | 实现 `tasks/analysis.py` Celery 分析任务 | `tasks/analysis.py` | 1.5h |
| W6D3-3 | 实现优先级调度（PriorityUser0 > PriorityAuto1 > PriorityBackground2） | `tasks/analysis.py` | 1h |
| W6D3-4 | 实现并发控制（max_concurrency=3） + 任务去重（同一 defect 不重复） | `tasks/analysis.py` | 1h |
| W6D3-5 | 实现分析取消 API `POST /agents/analyze/:id/cancel` | `api/v1/agents.py` | 0.5h |

**Day 3 小计：5h**

#### Day 4（周四）：Token 统计 + 队列管理

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W6D4-1 | 实现 Token 用量记录回调 | `agent/callbacks/token_tracker.py` | 1h |
| W6D4-2 | 实现 AI 成本估算 | `services/ai_runtime.py` | 0.5h |
| W6D4-3 | 实现队列状态 API `GET /agents/analyze/queue` | `api/v1/agents.py` | 0.5h |
| W6D4-4 | 实现分析历史 API `GET /agents/analyze/:id/history` | `api/v1/agents.py` | 0.5h |
| W6D4-5 | 实现缺陷维度 Token 用量 API | `api/v1/token_usage.py` | 1.5h |

**Day 4 小计：4h**

#### Day 5（周五）：S2 收尾

| # | 任务 | 预计 |
|---|------|------|
| W6D5-1 | Agent 全流程 E2E 测试（正常+失败+取消+流式降级） | 2h |
| W6D5-2 | 记忆注入/提取集成测试 | 1h |
| W6D5-3 | 修复所有已发现的 bug | 1h |
| W6D5-4 | S2 代码 Review（mypy + ruff） | 0.5h |
| W6D5-5 | 前后端联调：AI 分析触发→进度展示→报告查看 | 0.5h |

**Day 5 小计：5h**

### 4.4 阶段二交付验收

```
□ POST /agents/analyze 成功生成分析报告（含 rootCause + affectedFiles + solution.steps）
□ POST /agents/analyze/stream 流式输出 SSE 事件（与前端格式一致）
□ 流式失败自动降级到轮询，前端可正常展示
□ 多 AI 配置 fallback 正常工作（第一个失败自动切换第二个）
□ Agent 分析完成后异步提取记忆
□ 下次分析时自动注入匹配的记忆到 Prompt
□ Celery 分析任务按优先级调度，并发不超过 3
□ 取消分析 API 正常停止运行中的任务
□ Token 用量记录到 ai_token_usage 表
```

---

## 五、阶段三：代码修复与 PR 生命周期（第 7~8 周）

### 5.1 目标

实现 8 步修复流水线、结构化代码补丁生成、人工修复双路径、PR 状态跟踪（Webhook 驱动）、PR 拒绝自动回退。

### 5.2 第一周（W7）：修复引擎

#### Day 1（周一）：修复任务基础设施

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W7D1-1 | 实现修复任务 API（创建/查询/状态更新） | `api/v1/fix_tasks.py` + `services/fix_task_service.py` | 1.5h |
| W7D1-2 | 实现修复任务组 API | 同上 | 0.5h |
| W7D1-3 | 实现仓库认证解析（绑定→默认→个人优先级） | `services/repo_auth.py` | 1h |
| W7D1-4 | 实现 Git 操作封装（克隆/分支/提交/推送） | `agent/tools/git_ops.py`（基于 GitPython） | 1.5h |

**Day 1 小计：4.5h**

#### Day 2（周二）：AI 代码生成

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W7D2-1 | 实现 AI 修复 Prompt 构建 | `agent/prompts/fix.py`（从 Go [codegen.go] 迁移 Prompt） | 1h |
| W7D2-2 | 实现结构化补丁解析（parsePatchResponse） | `services/fix_engine.py` | 1h |
| W7D2-3 | 实现 `applyContentHunks`（oldContent 精确匹配一次） | `services/fix_engine.py` | 1.5h |
| W7D2-4 | 实现代码语法验证 | `services/fix_engine.py`（Python ast.parse） | 0.5h |
| W7D2-5 | 实现最多 3 次重试 + 无变更检测 | `services/fix_engine.py` | 1h |

**Day 2 小计：5h**

#### Day 3（周三）：8 步修复流水线

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W7D3-1 | 实现流水线步骤 1~4（克隆→分支→生成→应用） | `services/fix_engine.py` | 2h |
| W7D3-2 | 实现流水线步骤 5~8（提交→构建验证→推送→PR 创建） | `services/fix_engine.py` | 2h |
| W7D3-3 | 实现 Celery 修复任务 | `tasks/fix.py` | 1h |

**Day 3 小计：5h**

#### Day 4（周四）：修复安全

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W7D4-1 | 实现仓库隔离（按缺陷 ID 隔离临时目录） | `services/fix_engine.py` | 1h |
| W7D4-2 | 实现分析报告仓库范围限定 | `services/fix_analysis_scope.py` | 1.5h |
| W7D4-3 | 实现仓库解析（DefectRepoResolver） | `services/defect_repo_resolver.py` | 1h |
| W7D4-4 | 集成测试：完整修复流程 | `tests/test_services/test_fix_engine.py` | 1.5h |

**Day 4 小计：5h**

#### Day 5（周五）：修复测试 + Prompt 提取

| # | 任务 | 预计 |
|---|------|------|
| W7D5-1 | 从 Go [codegen.go] 提取修复生成 Prompt 模板 | 0.5h |
| W7D5-2 | hunks 精确匹配测试（0次匹配→拒绝、多次匹配→拒绝、1次匹配→成功） | 1h |
| W7D5-3 | 语法验证测试（合法代码→通过、非法代码→拒绝） | 0.5h |
| W7D5-4 | 3 次重试集成测试 | 1h |
| W7D5-5 | 修复联调中发现的 bug | 1h |

**Day 5 小计：4h**

### 5.3 第二周（W8）：PR 生命周期

#### Day 1（周一）：人工修复路径

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W8D1-1 | 实现人工修复 API（开始/提交/放弃） | `api/v1/fix_tasks.py`（manual-fix 端点） | 1.5h |
| W8D1-2 | 实现 FixTask.source=manual 逻辑 | `services/fix_task_service.py` | 0.5h |
| W8D1-3 | 实现 PR URL 补填 PATCH API | `api/v1/fix_tasks.py` | 0.5h |
| W8D1-4 | 集成测试：人工修复路径 | `tests/test_api/test_fix_tasks.py` | 1h |

**Day 1 小计：3.5h**

#### Day 2（周二）：PR 状态跟踪 + Webhook

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W8D2-1 | 实现 PRRejection 模型 + CRUD | `models/pr_rejection.py` + `services/pr_lifecycle_service.py` | 1h |
| W8D2-2 | 实现 VCS Webhook 统一入口 | `api/v1/integrations.py`（vcs_webhook 端点） | 1.5h |
| W8D2-3 | 实现 Webhook 签名校验（X-Hub-Signature-256） | `middleware/webhook_signature.py` | 1h |
| W8D2-4 | 实现 GitHub/GitLab 事件解析 | `services/vcs_webhook_service.py` | 1h |

**Day 2 小计：4.5h**

#### Day 3（周三）：PR 拒绝/合并处理

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W8D3-1 | 实现 PR 拒绝处理（创建 PRRejection + 更新 FixTask.PRStatus + 缺陷回退） | `services/pr_lifecycle_service.py` | 1.5h |
| W8D3-2 | 实现 PR 合并处理（更新 FixTask.PRStatus + 缺陷推进） | 同上 | 0.5h |
| W8D3-3 | 实现手动标记 PR 拒绝/合并 API（降级方案） | `api/v1/fix_tasks.py` | 1h |
| W8D3-4 | 实现 PR 拒绝历史查询 API | `api/v1/fix_tasks.py` | 0.5h |
| W8D3-5 | 实现 PR 拒绝→Agent 记忆沉淀 | `services/pr_lifecycle_service.py` | 1h |

**Day 3 小计：4.5h**

#### Day 4（周四）：PR 集成测试

| # | 任务 | 预计 |
|---|------|------|
| W8D4-1 | PR 拒绝回退 E2E 测试 | 1.5h |
| W8D4-2 | PR 合并推进 E2E 测试 | 1h |
| W8D4-3 | Webhook 签名校验测试（合法/非法签名） | 0.5h |
| W8D4-4 | 人工修复→登记 PR→PR 拒绝→回退完整链路测试 | 1.5h |
| W8D4-5 | 凭证 + 仓库认证集成测试 | 0.5h |

**Day 4 小计：5h**

#### Day 5（周五）：S3 收尾 + S2 回归

| # | 任务 | 预计 |
|---|------|------|
| W8D5-1 | 前后端联调：修复流程（触发修复→查看任务→查看 PR→验证） | 1h |
| W8D5-2 | 修复 S3 所有 bug | 1.5h |
| W8D5-3 | S2 回归测试（确保 Agent 分析 + 修复联调正常） | 1h |
| W8D5-4 | S3 代码 Review | 0.5h |

**Day 5 小计：4h**

### 5.4 阶段三交付验收

```
□ AI 修复生成的代码语法合法
□ hunks oldContent 精确匹配安全校验生效
□ 无变更（no_changes）时正确跳过后续步骤
□ 修复失败最多重试 3 次
□ 人工修复路径完整可用（开始→提交→放弃）
□ PR 拒绝后缺陷自动回退到 pending_fix
□ PR 拒绝原因沉淀为 Agent 记忆
□ PR 合并后缺陷自动推进到 fixed
□ VCS Webhook 签名校验生效
□ 修复工作目录按缺陷 ID 隔离
```

---

## 六、阶段四：信号接入、检索与质量洞察（第 9~10 周）

### 6.1 目标

实现外部信号接入（Bugly/阿里云/钉钉/飞书/Webhook）、SHA256 指纹聚类去重、问题簇管理、五维路由规则、关键词检索器、质量洞察和报表导出。

### 6.2 第一周（W9）：信号接入

#### Day 1（周一）：连接器管理

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W9D1-1 | 实现连接器 CRUD API | `api/v1/integrations.py` + `services/integration_service.py` | 1.5h |
| W9D1-2 | 实现连接器健康状态（status + health_message） | `services/integration_service.py` | 0.5h |
| W9D1-3 | 实现连接器测试（Test） + 同步（Sync） | `api/v1/integrations.py` | 1h |
| W9D1-4 | 实现同步记录查询 | `api/v1/integrations.py` | 0.5h |

**Day 1 小计：3.5h**

#### Day 2（周二）：信号接入端点

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W9D2-1 | 实现外部信号接入端点 `POST /inbound/connectors/:token` | `api/v1/integrations.py` | 1h |
| W9D2-2 | 实现字段归一化（NormalizePayload） | `services/signal_ingest.py` | 1.5h |
| W9D2-3 | 实现来源差异化补全（Bugly/阿里云/钉钉/飞书） | `services/signal_ingest.py` | 1.5h |
| W9D2-4 | 实现信号接入事务 + IntegrationSyncRecord | `services/signal_ingest.py` | 1h |

**Day 2 小计：5h**

#### Day 3（周三）：指纹聚类 + 问题簇管理

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W9D3-1 | 实现 SHA256 指纹生成 | `services/signal_ingest.py` | 0.5h |
| W9D3-2 | 实现 IssueCluster 聚类 + IssueSignal 去重 | `services/signal_triage.py` | 1.5h |
| W9D3-3 | 实现问题簇 API（列表/详情/分配/忽略/合并/转换） | `api/v1/issue_pool.py` + `services/signal_triage.py` | 2h |
| W9D3-4 | 实现批量操作（分配/忽略/转换） | 同上 | 1h |

**Day 3 小计：5h**

#### Day 4（周四）：路由规则 + 版本管理

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W9D4-1 | 实现五维路由匹配引擎 | `services/project_routing.py` | 1.5h |
| W9D4-2 | 实现路由规则 CRUD | `api/v1/issue_pool.py`（modules/routing-rules 端点） | 1h |
| W9D4-3 | 实现应用发布版本管理 CRUD | `api/v1/issue_pool.py`（releases 端点） | 1h |
| W9D4-4 | 实现自动分诊 API | `api/v1/issue_pool.py` | 0.5h |
| W9D4-5 | 实现版本趋势分析 + 异常等级计算 | `services/project_routing.py` | 1h |

**Day 4 小计：5h**

#### Day 5（周五）：信号测试

| # | 任务 | 预计 |
|---|------|------|
| W9D5-1 | 信号接入 E2E 测试（模拟 Bugly payload → 聚类 → 分诊） | 1.5h |
| W9D5-2 | 指纹去重测试（同一指纹→聚类、不同指纹→新簇） | 1h |
| W9D5-3 | 路由规则匹配测试（5 种匹配方式全覆盖） | 1h |
| W9D5-4 | 批量操作测试 | 0.5h |
| W9D5-5 | 修复 bug | 1h |

**Day 5 小计：5h**

### 6.3 第二周（W10）：检索 + 洞察 + 报表

#### Day 1（周一）：检索器

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W10D1-1 | 实现 Retriever Protocol + 插件注册表 | `retrieval/base.py` | 1h |
| W10D1-2 | 实现关键词检索器（文件路径匹配 + 内容搜索） | `retrieval/keyword.py` | 1.5h |
| W10D1-3 | 实现 RepoWiki 检索器（HTTP 调用外部服务） | `retrieval/repo_wiki.py` | 1.5h |
| W10D1-4 | 实现检索器插件 API | `api/v1/retriever.py` | 1h |

**Day 1 小计：5h**

#### Day 2（周二）：质量洞察

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W10D2-1 | 实现质量洞察概览 API | `api/v1/reports.py`（quality-insights） | 1.5h |
| W10D2-2 | 实现问题池摘要 + 版本健康聚合 | `services/quality_insights.py` | 1h |
| W10D2-3 | 实现 AI 统计聚合（成功率/平均耗时/Token 费用） | `services/quality_insights.py` | 1h |
| W10D2-4 | 实现模块热点分析 | `services/quality_insights.py` | 0.5h |
| W10D2-5 | 实现来源分布统计 | `services/quality_insights.py` | 0.5h |

**Day 2 小计：4.5h**

#### Day 3（周三）：回归预防 + 报表

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W10D3-1 | 实现回归检测项 API | `api/v1/reports.py`（regression-items） | 1h |
| W10D3-2 | 实现回归项状态流转（Draft→Active→Verified→Archived） | `services/regression.py` | 1h |
| W10D3-3 | 实现仪表盘 API | `api/v1/reports.py`（dashboard/trend/status-distribution/severity-distribution/team-metrics） | 1.5h |
| W10D3-4 | 实现 CSV/JSON 导出 API | `api/v1/reports.py`（export/csv, export/json） | 1h |

**Day 3 小计：4.5h**

#### Day 4（周四）：Token 统计 + MCP/技能 API

| # | 任务 | 文件 | 预计 |
|---|------|------|------|
| W10D4-1 | 实现项目/迭代/缺陷三级 Token 统计 API | `api/v1/token_usage.py` + `services/token_service.py` | 1.5h |
| W10D4-2 | 实现 MCP 服务管理 API | `api/v1/mcp_servers.py` | 1h |
| W10D4-3 | 实现 Agent 技能管理 API | `api/v1/skills.py` | 1h |
| W10D4-4 | 实现协作任务 API | `api/v1/collaborations.py` | 1.5h |

**Day 4 小计：5h**

#### Day 5（周五）：S4 收尾 + 全量回归

| # | 任务 | 预计 |
|---|------|------|
| W10D5-1 | S4 全部模块集成测试 | 1.5h |
| W10D5-2 | S0~S4 全量回归测试（确保新增模块不破坏已有功能） | 1.5h |
| W10D5-3 | 修复 S4 所有 bug | 1h |
| W10D5-4 | S4 代码 Review | 0.5h |
| W10D5-5 | API 契约兼容性检查（逐项验证附录 A 的 10 条约定） | 0.5h |

**Day 5 小计：5h**

### 6.4 阶段四交付验收

```
□ 外部信号可接入（Bugly/阿里云/钉钉/飞书/Webhook）
□ SHA256 指纹正确聚类去重
□ 问题簇可分配/忽略/合并/转换为缺陷
□ 路由规则五维匹配正常工作
□ 关键词检索器在分析流程中可用
□ 质量洞察 API 返回正确的聚合数据
□ 回归检测项状态流转正常
□ 仪表盘/趋势/分布 API 返回值正确
□ CSV/JSON 导出正常
□ 全部 22 组 API（200+ 端点）可用
```

---

## 七、阶段五：加固与上线（第 11 周）

### 7.1 目标

性能优化、安全审计、Docker 生产化、全流程 E2E、文档。

### 7.2 每日任务

#### Day 1（周一）：性能优化

| # | 任务 | 预计 |
|---|------|------|
| W11D1-1 | 数据库索引检查（确保 PRD 要求的 40+ 索引已创建） | 1h |
| W11D1-2 | Redis 缓存优化（RBAC 权限、AI 配置、项目配置） | 1.5h |
| W11D1-3 | 数据库连接池调优（pool_size=20, max_overflow=10） | 0.5h |
| W11D1-4 | API 响应时间基准测试（关键端点 < 500ms） | 1.5h |

**Day 1 小计：4.5h**

#### Day 2（周二）：安全审计

| # | 任务 | 预计 |
|---|------|------|
| W11D2-1 | 凭证加密验证（AES-256-GCM 正确加解密） | 0.5h |
| W11D2-2 | API 密钥脱敏验证 | 0.5h |
| W11D2-3 | Webhook 签名校验验证 | 0.5h |
| W11D2-4 | 权限越权测试（每个角色尝试访问越权端点） | 1.5h |
| W11D2-5 | SQL 注入测试 + XSS 测试 | 1h |
| W11D2-6 | Token 黑名单验证（登出后 Token 不可用） | 0.5h |

**Day 2 小计：4.5h**

#### Day 3（周三）：Docker 生产化

| # | 任务 | 预计 |
|---|------|------|
| W11D3-1 | 编写 `Dockerfile`（多阶段构建，最终镜像 < 500MB） | 1h |
| W11D3-2 | 编写 `docker-compose.prod.yml`（PostgreSQL + Redis + App + Celery Worker + Celery Beat） | 1h |
| W11D3-3 | 编写 `.env.example` | 0.5h |
| W11D3-4 | Celery Flower 监控容器配置 | 0.5h |
| W11D3-5 | Docker 部署测试（一键 `docker compose up -d` 可启动） | 1.5h |

**Day 3 小计：4.5h**

#### Day 4（周四）：全流程 E2E + 前端联调

| # | 任务 | 预计 |
|---|------|------|
| W11D4-1 | 前端联调：登录 → 创建项目 → 迭代 → 仓库 → 缺陷 → AI分析 → 修复 → PR → 验证 → 完成 | 1.5h |
| W11D4-2 | 前端联调：信号接入 → 问题簇 → 转缺陷 → AI分析 | 1h |
| W11D4-3 | 前端联调：权限校验（不同角色看到的页面和操作不同） | 1h |
| W11D4-4 | 前端联调：通知、审计、报表、Token 统计 | 1h |
| W11D4-5 | 记录并修复前端联调发现的问题 | 0.5h |

**Day 4 小计：5h**

#### Day 5（周五）：文档 + 交付

| # | 任务 | 预计 |
|---|------|------|
| W11D5-1 | 编写 `README.md`（项目介绍、快速开始、环境变量、API 文档链接） | 1h |
| W11D5-2 | 编写部署文档 `DEPLOY.md` | 0.5h |
| W11D5-3 | 更新 API 文档（FastAPI 自动生成 `/docs` 验证准确性） | 0.5h |
| W11D5-4 | 最终全量回归测试 | 1h |
| W11D5-5 | 测试覆盖率报告生成 + 归档 | 0.5h |
| W11D5-6 | 代码最终 Review + Tag 版本发布 | 0.5h |

**Day 5 小计：4h**

### 7.3 阶段五交付验收

```
□ Docker 一键部署（docker compose up -d）
□ 全流程 E2E 通过（创建→分配→分析→修复→PR→验证→完成）
□ 前端零改动正常使用
□ 安全审计全部通过
□ API 响应时间 < 500ms（非 AI 端点）
□ 测试覆盖率 > 80%
□ README + DEPLOY + API 文档完整
□ 权限越权测试全部通过（未授权返回 403）
```

---

## 八、全局风险管理

### 8.1 风险矩阵

| # | 风险 | 概率 | 影响 | 等级 | 缓解措施 | 应急方案 |
|---|------|------|------|------|---------|---------|
| R1 | API 契约与前端不兼容 | 中 | 🔴 高 | P1 | 阶段零锁定 Pydantic Schema，每阶段末尾联调；附录 A 10 条逐项检查 | 发现不兼容立即修，不推进下一阶段 |
| R2 | LangGraph 状态图逻辑 bug | 中 | 🟡 中 | P2 | 每个 Node 独立单元测试；使用 LangGraph checkpointer 可重放调试 | 回退到简单 LLM 调用（跳过 Planner/Executor） |
| R3 | AI 分析质量低于 Go 版 | 中 | 🟡 中 | P2 | 直接复用 Go 版 Prompt 模板，不重新设计；写对比测试 | 调整 Prompt 直到质量达标 |
| R4 | hunks 精确匹配误判 | 低 | 🟡 中 | P3 | 3 次重试 + 错误信息回传 AI 自我修正 | 跳过无法自动修复的 hunks，标记人工处理 |
| R5 | Celery 任务丢失或重复 | 低 | 🟡 中 | P3 | Redis 持久化 + `acks_late=True` + Flower 监控 | 手动重试失败任务 |
| R6 | 数据库迁移与现有表冲突 | 低 | 🔴 高 | P2 | 阶段零即执行首次迁移，确认与现有 PostgreSQL 兼容 | 使用 `--autogenerate` diff 模式，手动修正 |
| R7 | Python 异步性能问题 | 低 | 🟢 低 | P3 | asyncpg + SQLAlchemy async mode；关键路径写 benchmark | 增加 uvicorn worker 数量 |

### 8.2 风险应对原则

1. **API 契约优先**：任何变更先确认不影响前端，再改后端
2. **每阶段独立验收**：前一阶段不通过，不进入下一阶段
3. **Prompt 复刻而非重设计**：从 Go 版直接提取 Prompt 字符串
4. **安全校验不可变通**：hunks oldContent 精确匹配、AES 加密、权限校验必须在阶段内完成

---

## 九、开发规范与约定

### 9.1 代码规范

| 工具 | 用途 | 命令 |
|------|------|------|
| ruff | Lint + Format | `ruff check . && ruff format .` |
| mypy | 静态类型检查 | `mypy app/` |
| pytest | 测试 | `pytest -v --cov=app --cov-report=term` |

### 9.2 提交规范

```
feat(module): 添加缺陷创建 API
fix(workflow): 修复状态流转乐观锁
test(defect): 补充缺陷筛选测试
docs: 更新 API 文档
refactor(agent): 提取 Planner Node 为独立文件
```

### 9.3 分支策略

```
main           ← 生产分支，仅 S5 完成后合并
  └── develop  ← 开发主分支
       ├── s0/infra     ← 阶段零
       ├── s1/crud      ← 阶段一
       ├── s2/agent     ← 阶段二
       ├── s3/fix       ← 阶段三
       ├── s4/signal    ← 阶段四
       └── s5/polish    ← 阶段五
```

### 9.4 命名约定

| 层级 | 命名 | 示例 |
|------|------|------|
| 文件名 | `snake_case.py` | `defect_service.py` |
| 模型类 | `PascalCase` | `class Defect(Base)` |
| Schema 类 | `PascalCase` | `class DefectCreate(BaseModel)` |
| 函数/方法 | `snake_case` | `async def create_defect()` |
| API 端点 | kebab-case URL | `/api/v1/fix-tasks/:taskId` |
| 测试文件 | `test_*.py` | `test_workflow.py` |
| 测试函数 | `test_should_*` | `test_should_reject_invalid_transition` |

### 9.5 测试要求

| 层级 | 范围 | 工具 | 覆盖率目标 |
|------|------|------|-----------|
| 单元测试 | Service 层纯函数（状态机、指纹生成、hunks 匹配） | pytest | > 90% |
| API 集成测试 | 每个 API 端点的正常/异常路径 | pytest + httpx | > 80% |
| Agent 测试 | LangGraph 图执行（Mock LLM） | pytest | > 70% |
| E2E 测试 | 全流程（前端→后端→数据库） | 手动 + 前端 Playwright | 核心路径 |

---

## 十、交付清单

### 10.1 代码交付物

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | `bug_agent_py/` 完整源码 | Python 后端服务 |
| 2 | `alembic/` 数据库迁移脚本 | 与现有 PostgreSQL Schema 兼容 |
| 3 | `Dockerfile` + `docker-compose.yml` | 生产级容器化部署 |
| 4 | `tests/` 全套测试 | 单元 + 集成 + Agent 测试 |

### 10.2 文档交付物

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | `README.md` | 项目介绍 + 快速开始 |
| 2 | `DEPLOY.md` | 部署文档 |
| 3 | OpenAPI 文档 | FastAPI 自动生成（`/docs`） |
| 4 | 测试覆盖率报告 | pytest-cov 输出 |

### 10.3 验收条件

| # | 条件 | 验证方式 |
|---|------|---------|
| 1 | 22 组 API（200+ 端点）全部可用 | API 测试全覆盖 |
| 2 | 前端零改动正常使用 | 用现有 React 前端走完整业务流程 |
| 3 | 13 种状态 × 24 条转移规则全部通过 | 状态机参数化测试 |
| 4 | AI 分析成功生成报告 | Agent E2E 测试 |
| 5 | AI 修复生成语法合法代码 | 修复引擎测试 |
| 6 | PR 拒绝自动回退 pending_fix | PR 生命周期测试 |
| 7 | 外部信号正确聚类去重 | 信号接入测试 |
| 8 | Docker 一键部署 | `docker compose up -d` 验证 |
| 9 | 安全审计通过 | 权限越权测试 + 加密验证 |
| 10 | 测试覆盖率 > 80% | pytest-cov 报告 |

---

**文档变更记录**

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|---------|------|
| v1.0 | 2026-06-06 | 初稿：基于 Python PRD v1.0-python 编制，6 阶段 55 天详细任务分解，含每个任务的文件、工时、依赖、测试要求 | WorkBuddy |