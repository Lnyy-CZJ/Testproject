# BugAgent 项目 Code Wiki

> 版本：1.4.0 | 最后更新：2026-06-06

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈总览](#2-技术栈总览)
3. [项目目录结构](#3-项目目录结构)
4. [后端架构详解](#4-后端架构详解)
   - 4.1 [启动入口与服务生命周期](#41-启动入口与服务生命周期)
   - 4.2 [配置体系](#42-配置体系)
   - 4.3 [路由与API层](#43-路由与api层)
   - 4.4 [中间件层](#44-中间件层)
   - 4.5 [处理器层 (Handler)](#45-处理器层-handler)
   - 4.6 [业务逻辑层 (Service)](#46-业务逻辑层-service)
   - 4.7 [ADK Agent框架](#47-adk-agent框架)
   - 4.8 [AI模型适配层](#48-ai模型适配层)
   - 4.9 [检索模块 (Retrieval)](#49-检索模块-retrieval)
   - 4.10 [SSE实时推送](#410-sse实时推送)
   - 4.11 [数据模型与数据库](#411-数据模型与数据库)
   - 4.12 [外部集成](#412-外部集成)
5. [前端架构详解](#5-前端架构详解)
   - 5.1 [入口与主题系统](#51-入口与主题系统)
   - 5.2 [路由设计](#52-路由设计)
   - 5.3 [API层](#53-api层)
   - 5.4 [布局组件体系](#54-布局组件体系)
   - 5.5 [SSE实时通信](#55-sse实时通信)
   - 5.6 [核心页面说明](#56-核心页面说明)
6. [核心业务流程](#6-核心业务流程)
   - 6.1 [信号接入与分诊流程](#61-信号接入与分诊流程)
   - 6.2 [缺陷分析与自动修复流程](#62-缺陷分析与自动修复流程)
   - 6.3 [缺陷状态机](#63-缺陷状态机)
   - 6.4 [多Agent协作流程](#64-多agent协作流程)
7. [权限与安全体系](#7-权限与安全体系)
8. [数据库迁移历史](#8-数据库迁移历史)
9. [部署与运行方式](#9-部署与运行方式)
10. [开发指南](#10-开发指南)

---

## 1. 项目概述

BugAgent 是一个基于 AI 驱动的智能缺陷管理平台，核心能力包括：

- **信号接入**：从 Bugly、阿里云日志、钉钉、飞书等外部平台自动采集异常信号
- **智能分诊**：信号自动聚类、路由分配、问题分级
- **AI 分析与修复**：利用多 Agent 协作 + 大语言模型自动分析缺陷根因并生成修复代码
- **全生命周期管理**：从缺陷创建、分析、修复到验证、回归的完整工作流
- **质量洞察**：多维度质量数据聚合与可视化
- **RBAC 权限**：平台级 + 项目级双层次权限管理

项目由三部分组成：

| 组成部分 | 技术栈 | 目录 |
|---------|--------|------|
| 后端服务 | Go 1.25, Gin, GORM, PostgreSQL, Redis | `server/` |
| 前端应用 | React 18, TypeScript, Vite, Ant Design 5 | `web/` |
| 文档体系 | Markdown | `docs/` |

---

## 2. 技术栈总览

### 后端

| 类别 | 技术 | 用途 |
|------|------|------|
| 语言 | Go 1.25 | 后端服务 |
| Web 框架 | Gin v1.10 | HTTP 路由 |
| ORM | GORM v1.31 | 数据库操作 |
| 数据库 | PostgreSQL (主) / SQLite (开发) | 数据持久化 |
| 缓存 | Redis v9 | 缓存 / 限流 |
| AI SDK | Google ADK v0.3 | Agent 框架 |
| AI 厂商 | OpenAI / Anthropic / DeepSeek / 智谱 / DashScope | 大模型接入 |
| 版本控制 | go-git v5 | Git 操作（克隆/分支/提交/推送） |
| 认证 | JWT (golang-jwt v5) | 用户认证 |
| 配置 | Viper | 配置管理 |
| 文档 | Swagger | API 文档 |

### 前端

| 类别 | 技术 | 用途 |
|------|------|------|
| 框架 | React 18 | UI 框架 |
| 语言 | TypeScript | 类型安全 |
| 构建工具 | Vite | 开发与构建 |
| UI 组件库 | Ant Design 5 | 组件系统 |
| 路由 | React Router v6 | 路由管理 |
| HTTP | Axios | API 请求 |
| 样式 | Tailwind CSS + PostCSS | 样式方案 |
| E2E 测试 | Playwright | 浏览器自动化测试 |

---

## 3. 项目目录结构

```
bug_agent/
├── server/                          # Go 后端服务
│   ├── cmd/server/                  # 服务入口
│   │   ├── main.go                  # 主函数
│   │   ├── main_test.go             # 主函数测试
│   │   ├── config.yaml              # 配置文件
│   │   └── check_report.py          # 报告检查脚本
│   ├── internal/                    # 内部包
│   │   ├── adk/                     # Agent Development Kit 框架
│   │   │   ├── agents.go            # Agent 工厂函数
│   │   │   ├── analysis_service.go  # 分析服务（核心，~3258行）
│   │   │   ├── fix_service.go       # 修复服务
│   │   │   ├── collaboration_agent.go  # 协作Agent
│   │   │   ├── collaboration_service.go # 协作服务
│   │   │   ├── planner_agent.go     # 探索规划Agent
│   │   │   ├── tool_registry.go     # 工具注册中心
│   │   │   ├── tool_permissions.go  # 工具权限
│   │   │   ├── tool_adapters.go     # 工具适配器
│   │   │   ├── safety_gate.go       # 安全门控
│   │   │   ├── prompt_engine.go     # 提示词模板引擎
│   │   │   ├── scheduler.go         # 优先级任务调度器
│   │   │   ├── model_factory.go     # LLM模型工厂
│   │   │   ├── model_adapter.go     # ADK LLM适配器（~739行）
│   │   │   ├── mcp_integration.go   # MCP工具集成
│   │   │   ├── stream_adapter.go    # SSE流适配器
│   │   │   ├── rollout_recorder.go  # 灰度/事件记录器
│   │   │   ├── memory_callbacks.go  # 记忆注入/提取回调
│   │   │   ├── init.go              # 模块初始化
│   │   │   └── tools/code_tools.go  # 代码工具
│   │   ├── ai/                      # AI模型适配
│   │   │   ├── client.go            # AI客户端接口
│   │   │   ├── factory.go           # 客户端工厂
│   │   │   ├── openai.go            # OpenAI适配
│   │   │   ├── openai_compatible.go # OpenAI兼容基类
│   │   │   ├── anthropic.go         # Anthropic适配
│   │   │   ├── deepseek.go          # DeepSeek适配
│   │   │   ├── dashscope.go         # 阿里云适配
│   │   │   ├── zhipu.go             # 智谱适配
│   │   │   ├── codegen.go           # AI代码生成引擎
│   │   │   ├── prompts.go           # 提示词构建
│   │   │   ├── memory_prompts.go    # 记忆提取提示词
│   │   │   ├── explorer.go          # 代码探索引擎
│   │   │   ├── api_mapper.go        # API路由映射器
│   │   │   └── codegen_test.go      # 代码生成测试
│   │   ├── aiconfig/crypto.go       # AI配置加密
│   │   ├── asyncx/                  # 异步工具
│   │   │   ├── asyncx.go            # 异步任务工具
│   │   │   └── shutdown.go          # 优雅关闭
│   │   ├── cache/redis.go           # Redis缓存
│   │   ├── config/config.go         # 配置管理
│   │   ├── database/database.go     # 数据库初始化
│   │   ├── git/                     # Git操作
│   │   │   ├── operations.go        # Git操作封装
│   │   │   ├── repo.go              # 仓库管理
│   │   │   └── repo_test.go
│   │   ├── handler/                 # HTTP处理器层（40+文件）
│   │   │   ├── agent.go             # Agent分析处理器
│   │   │   ├── defect.go            # 缺陷CRUD处理器
│   │   │   ├── auth.go              # 认证处理器
│   │   │   ├── project.go           # 项目处理器
│   │   │   ├── fix_task.go          # 修复任务处理器
│   │   │   ├── collaboration.go     # 协作处理器
│   │   │   ├── workflow.go          # 工作流处理器
│   │   │   ├── rbac.go              # 权限处理器
│   │   │   ├── notification.go      # 通知处理器
│   │   │   ├── issue_pool.go        # 问题池处理器
│   │   │   ├── integration_connector.go # 集成连接器处理器
│   │   │   ├── ...                  # 其余处理器
│   │   │   └── testdb_test.go       # 测试数据库工具
│   │   ├── integration/             # 外部集成
│   │   │   ├── aliyunlog/client.go  # 阿里云日志
│   │   │   ├── bugly/client.go      # Bugly
│   │   │   └── yunxiao/             # 云效集成
│   │   │       ├── client.go
│   │   │       └── client_test.go
│   │   ├── middleware/              # 中间件
│   │   │   ├── auth.go              # JWT认证
│   │   │   ├── rbac.go              # 权限校验
│   │   │   ├── audit.go             # 审计日志
│   │   │   ├── rate_limit.go        # 限流
│   │   │   └── ...
│   │   ├── model/                   # 数据模型
│   │   │   ├── models.go            # 所有业务模型
│   │   │   ├── db.go                # 全局DB
│   │   │   ├── auth.go              # 认证模型
│   │   │   ├── rbac.go              # 权限模型
│   │   │   ├── signal.go            # 信号模型
│   │   │   ├── workflow.go          # 工作流模型
│   │   │   ├── notification.go      # 通知模型
│   │   │   ├── collaboration.go     # 协作模型
│   │   │   ├── ai_catalog.go        # AI目录模型
│   │   │   └── ai_catalog_seed.go   # AI目录种子数据
│   │   ├── retrieval/               # 检索模块
│   │   │   ├── retriever.go         # 检索器接口
│   │   │   ├── registry.go          # 插件注册表
│   │   │   ├── keyword.go           # 关键词检索器
│   │   │   ├── repo_wiki.go         # RepoWiki检索器
│   │   │   ├── rag.go               # RAG检索器（骨架）
│   │   │   ├── builtin.go           # 内置插件注册
│   │   │   └── seed.go              # 种子数据
│   │   ├── router/router.go         # 路由注册（核心~520行）
│   │   ├── service/                 # 业务逻辑层（30+文件）
│   │   │   ├── signal_ingest.go     # 信号接入
│   │   │   ├── signal_triage.go     # 信号分诊
│   │   │   ├── fix_engine.go        # 修复引擎
│   │   │   ├── fix_analysis_scope.go# 分析范围限定
│   │   │   ├── defect_draft.go      # 缺陷草稿生成
│   │   │   ├── defect_recommendation.go # 推荐服务
│   │   │   ├── defect_repo_resolver.go  # 仓库解析
│   │   │   ├── project_routing.go   # 项目路由
│   │   │   ├── regression_prevention.go# 回归预防
│   │   │   ├── quality_insights.go  # 质量洞察
│   │   │   ├── workflow.go          # 工作流
│   │   │   ├── rbac.go              # 权限服务
│   │   │   ├── notification.go      # 通知服务
│   │   │   ├── agent_memory.go      # Agent记忆
│   │   │   ├── ai_runtime.go        # AI运行时
│   │   │   ├── credential.go        # 凭证管理
│   │   │   ├── repo_auth.go         # 仓库认证
│   │   │   ├── report.go            # 报表
│   │   │   ├── audit.go             # 审计
│   │   │   └── ...
│   │   ├── sse/                     # Server-Sent Events
│   │   │   ├── broker.go            # SSE Broker
│   │   │   ├── handler.go           # SSE处理器
│   │   │   └── notify.go            # 通知工具
│   │   ├── util/analysis_util.go    # 分析工具
│   │   └── vcs/                     # 版本控制系统
│   │       └── client.go            # VCS客户端
│   ├── migrations/                  # 数据库迁移脚本（15个文件）
│   │   ├── v1.1_upgrade.sql
│   │   ├── v2.0_drop_legacy_rbac.sql
│   │   ├── v5.5_agent_capability.sql
│   │   ├── v5.6_retriever_plugins.sql
│   │   └── ...
│   ├── pkg/                         # 公共包
│   │   ├── logger/logger.go         # 日志库
│   │   └── response/response.go     # 统一响应格式
│   └── testutil/testutil.go         # 测试工具
│
├── web/                             # 前端应用
│   ├── src/
│   │   ├── main.tsx                 # 入口文件
│   │   ├── App.tsx                  # 根组件（主题 + 错误边界）
│   │   ├── router.tsx               # 路由配置
│   │   ├── api/                     # API层（12个文件）
│   │   ├── components/              # 通用组件
│   │   │   ├── layout/              # 布局组件（16个文件）
│   │   │   ├── AuthGuard.tsx        # 认证守卫
│   │   │   ├── CollaborationPanel.tsx # 协作面板
│   │   │   ├── DiffView.tsx         # Diff视图
│   │   │   ├── MemoryManager.tsx    # 记忆管理器
│   │   │   └── ...
│   │   ├── hooks/                   # 自定义Hooks
│   │   │   ├── sseManager.ts        # SSE连接管理器
│   │   │   ├── useSSE.ts            # SSE React Hook
│   │   │   └── useAnalysisStream.ts # 分析流Hook
│   │   ├── layouts/                 # 页面布局
│   │   │   ├── MainLayout.tsx       # 主布局
│   │   │   └── ProjectLayout.tsx    # 项目布局
│   │   ├── pages/                   # 页面组件
│   │   │   ├── defects/             # 缺陷管理（10+文件）
│   │   │   ├── projects/            # 项目管理（15+文件）
│   │   │   ├── system/              # 系统管理（5个文件）
│   │   │   └── auth/                # 认证页面
│   │   ├── types/                   # TypeScript类型定义
│   │   ├── contexts/                # React Context
│   │   └── utils/                   # 工具函数
│   ├── e2e/                         # Playwright E2E测试
│   └── vite.config.ts               # Vite配置
│
├── tests/                           # 端到端测试脚本
├── docs/                            # 项目文档
│   ├── PRD-v*.md                    # 产品需求文档
│   ├── DESIGN-v*.md                 # 设计文档
│   ├── DEV_PLAN-v*.md               # 开发计划
│   └── ...
├── Makefile                         # 构建自动化
└── deep_analysis.py                 # 分析脚本
```

---

## 4. 后端架构详解

### 4.1 启动入口与服务生命周期

**[main.go](file:///Users/admin/Testproject/bug_agent/server/cmd/server/main.go)** 是整个服务的入口，启动流程如下：

```
1. config.Init()            ← 加载配置（Viper + 环境变量）
2. validateRequiredSecrets() ← 校验密钥长度与默认值
3. database.Init()           ← 连接 PostgreSQL
4. cachepkg.Init()           ← 连接 Redis
5. model.SetDB(database.DB)  ← 设置全局DB
6. database.AutoMigrate()    ← 自动建表（50+模型）
7. applySchemaFixes()        ← Schema修复
8. SeedRBACData()            ← 预置RBAC角色权限
9. SeedDefaultAICatalog()    ← 预置AI目录
10. SeedDefaultPlugins()     ← 预置检索器插件
11. createPerformanceIndexes() ← 创建性能索引（40+索引）
12. createDefaultAdmin()     ← 创建默认管理员（首次运行）
13. sse.InitBroker()         ← 初始化SSE Broker
14. StartRateLimitCleanup()  ← 启动限流器清理
15. StartRepoCleanupLoop()   ← 启动仓库清理协程
16. router.Setup()           ← 注册路由
17. srv.ListenAndServe()     ← 启动HTTP服务
```

**优雅关闭**：监听 SIGINT/SIGTERM 信号，触发 `asyncx.TriggerShutdown()`，等待 10 秒完成清理。

### 4.2 配置体系

**[config.go](file:///Users/admin/Testproject/bug_agent/server/internal/config/config.go)** 使用 Viper 管理配置：

- **配置文件路径**：`config.yaml` / `cmd/server/config.yaml`
- **环境变量前缀**：`BUG_AGENT_`
- **敏感字段**：通过环境变量注入（DB_PASSWORD, JWT_SECRET, CREDENTIAL_ENCRYPT_KEY 等）

配置结构体：

```go
type Config struct {
    Server       ServerConfig       // 端口、模式、CORS、管理员密码、上传目录
    Database     DatabaseConfig     // 驱动、主机、端口、用户、密码、库名、Schema
    JWT          JWTConfig          // 密钥、过期时间
    Redis        RedisConfig        // 主机、端口、密码、DB
    Notification NotificationConfig // SMTP、Webhook
    Secrets      SecretsConfig      // 凭据加密密钥（AES-256-GCM）
    MCP          MCPConfig          // MCP服务器配置
}
```

### 4.3 路由与API层

**[router.go](file:///Users/admin/Testproject/bug_agent/server/internal/router/router.go)** 使用 Gin 框架注册所有 HTTP 路由。API 遵循 RESTful 设计，统一前缀 `/api/v1`。

**路由分组**：

| 分组 | 认证 | 说明 |
|------|------|------|
| `/healthz`, `/readyz` | 无 | 健康检查 |
| `/swagger/*any` | 无 | Swagger API文档 |
| `/api/v1/auth/*` | 无 | 注册/登录 |
| `/api/v1/inbound/connectors/:token` | 无 | 外部信号接入 |
| `/api/v1/invites/:code/*` | 无 | 邀请码验证/接受 |
| `/api/v1/sse` | 无（Token在Query） | SSE实时推送 |
| `/api/v1/*` (authed) | JWT | 所有业务API |

**认证路由中间件链**：
```
JWTAuth → PasswordChangeGuard → APILimitMiddleware → AuditMiddleware
```

**业务路由子分组**：

| 分组 | 主要端点 | 说明 |
|------|---------|------|
| `/projects/:id/*` | 30+ | 项目管理、迭代、仓库、AI配置、问题池、路由规则、发布版本、集成连接器、回归、质量、MCP、技能、检索器、记忆、Token用量 |
| `/defects/:id/*` | 25+ | 缺陷CRUD、指派、状态变更、验证、合并、驳回、重新打开、附件、评论、分析报告、修复任务、人工修复、PR生命周期、工作流状态机 |
| `/agents/*` | 6 | 分析触发(流/非流)、报告查询、取消、队列状态、历史 |
| `/fix-tasks/*` | 2 | 修复任务查询、状态更新 |
| `/collaborations/*` | 4 | 协作任务CRUD、聚合报告 |
| `/rbac/*` | 8 | 角色权限管理 |
| `/audit-logs/*` | 3 | 审计日志查询 |
| `/notifications/*` | 5 | 通知列表、未读计数、标记已读 |
| `/reports/*` | 6 | 仪表盘、趋势图、分布统计、导出 |
| `/admin/*` | 6 | 平台凭据、平台设置、AI目录、孤立仓库清理 |
| `/credentials/*` | 5 | 个人/平台凭据管理 |
| `/invites/*` | 2 | 邀请码管理 |
| `/users/*` | 10+ | 用户管理、平台角色 |
| `/notification-preferences/*` | 4 | 通知偏好 |
| `/uploads/*` | 1 | 认证文件下载 |

### 4.4 中间件层

| 中间件 | 文件 | 职责 |
|--------|------|------|
| JWTAuth | [auth.go](file:///Users/admin/Testproject/bug_agent/server/internal/middleware/auth.go) | JWT Token 验证 + 黑名单检查 |
| PasswordChangeGuard | [auth.go](file:///Users/admin/Testproject/bug_agent/server/internal/middleware/auth.go) | 密码修改保护 |
| APILimitMiddleware | [rate_limit.go](file:///Users/admin/Testproject/bug_agent/server/internal/middleware/rate_limit.go) | API调用限流 |
| RateLimitMiddleware | [rate_limit.go](file:///Users/admin/Testproject/bug_agent/server/internal/middleware/rate_limit.go) | 全局限流 |
| AuditMiddleware | [audit.go](file:///Users/admin/Testproject/bug_agent/server/internal/middleware/audit.go) | 操作审计日志 |
| RequirePermission | [rbac.go](file:///Users/admin/Testproject/bug_agent/server/internal/middleware/rbac.go) | 全局权限校验 |
| RequireProjectPermission | [rbac.go](file:///Users/admin/Testproject/bug_agent/server/internal/middleware/rbac.go) | 项目级权限校验 |
| RequireDefectPermission | [rbac.go](file:///Users/admin/Testproject/bug_agent/server/internal/middleware/rbac.go) | 缺陷级权限校验 |
| RequireRole | [rbac.go](file:///Users/admin/Testproject/bug_agent/server/internal/middleware/rbac.go) | 特定角色校验 |

### 4.5 处理器层 (Handler)

Handler 层位于 `server/internal/handler/`，是 Gin 路由与业务服务的桥梁。每个 Handler 通过构造函数注入 `*gorm.DB` 和所需 Service。

**核心 Handler**：

| Handler | 文件 | 关键方法 |
|---------|------|---------|
| AgentHandler | [agent.go](file:///Users/admin/Testproject/bug_agent/server/internal/handler/agent.go) | TriggerAnalysis, TriggerAnalysisStream, GetAnalysisReport, CancelAnalysis, QueueStatus |
| DefectHandler | [defect.go](file:///Users/admin/Testproject/bug_agent/server/internal/handler/defect.go) | CreateDefect, GetDefect, ListDefects, UpdateDefect, AssignDefect, ChangeStatus, VerifyDefect, MergeDefect, RejectDefect, ReopenDefect |
| AuthHandler | [auth.go](file:///Users/admin/Testproject/bug_agent/server/internal/handler/auth.go) | Register, Login, Logout, GetProfile, UpdateProfile, ChangeMyPassword, ListUsers |
| ProjectHandler | [project.go](file:///Users/admin/Testproject/bug_agent/server/internal/handler/project.go) | CreateProject, ListProjects, GetProject, CreateIteration, ListIterations, BindRepo |
| FixTaskHandler | [fix_task.go](file:///Users/admin/Testproject/bug_agent/server/internal/handler/fix_task.go) | CreateFixTask, GetFixTask, UpdateFixTaskStatus |
| WorkflowHandler | [workflow.go](file:///Users/admin/Testproject/bug_agent/server/internal/handler/workflow.go) | TransitionStatus, GetTransitions, GetHistory, BatchTransition |
| IssuePoolHandler | [issue_pool.go](file:///Users/admin/Testproject/bug_agent/server/internal/handler/issue_pool.go) | ListClusters, GetCluster, AssignCluster, IgnoreCluster, MergeCluster, ConvertCluster, AutoTriageClusters |
| IntegrationConnectorHandler | [integration_connector.go](file:///Users/admin/Testproject/bug_agent/server/internal/handler/integration_connector.go) | List, Create, Update, Delete, Test, Sync |
| RBACHandler | [rbac.go](file:///Users/admin/Testproject/bug_agent/server/internal/handler/rbac.go) | ListRoles, ListPermissions, AssignUserRole, GetUserPermissions |
| NotificationHandler | [notification.go](file:///Users/admin/Testproject/bug_agent/server/internal/handler/notification.go) | List, UnreadCount, MarkRead, MarkAllRead, Send |

### 4.6 业务逻辑层 (Service)

Service 层位于 `server/internal/service/`，承载所有核心业务逻辑。

#### 信号接入与服务

**SignalIngestService** ([signal_ingest.go](file:///Users/admin/Testproject/bug_agent/server/internal/service/signal_ingest.go))

```
IngestBatch()
  ├─ 创建/更新 IntegrationSyncRecord
  ├─ 事务内逐条处理
  │   ├─ parseAndNormalize()
  │   │   ├─ NormalizePayload()      ← 字段归一化
  │   │   └─ enrichPayloadForSource() ← 按来源差异化补全
  │   └─ ingestNormalized()
  │       ├─ 指纹生成 (SHA256)
  │       ├─ 信号入库/更新 (去重)
  │       └─ ApplyClusterRouting()   ← 自动路由
  └─ 刷新同步记录状态
```

**SignalTriageService** ([signal_triage.go](file:///Users/admin/Testproject/bug_agent/server/internal/service/signal_triage.go))

核心功能：问题簇（IssueCluster）管理，支持聚类、分诊、分配、合并、转换、批量操作。路由匹配引擎按 sort_order 依次匹配 source_type/platform/app_version/fingerprint_pattern/stack_keyword 五种规则。

#### 修复引擎

**FixService** ([fix_engine.go](file:///Users/admin/Testproject/bug_agent/server/internal/service/fix_engine.go))

8 步修复流水线：

```
CreateAutoFixGroup()
  └─ executeFixWorkflow()
      1. 克隆仓库 (浅克隆)
      2. 创建修复分支
      3. AI 生成修复代码 (多配置兜底)
      4. 应用代码变更 (hunk精确匹配)
      5. Git 提交
      6. 构建验证 (可选baseline对比)
      7. Git 推送
      8. 创建 PR (GitHub/GitLab)
```

**关键辅助服务**：

| Service | 职责 |
|---------|------|
| FixAnalysisScopeService | 将AI分析报告的文件路径限定到特定仓库 |
| DefectRepoResolver | 根据缺陷+Agent+分析报告解析目标仓库 |
| CodeGenerator | AI代码生成引擎，支持结构化补丁+3次重试+语法验证 |

#### 其他核心服务

| Service | 职责 |
|---------|------|
| ProjectRoutingService | 模块/路由规则/发布版本管理，信号-版本匹配 |
| RegressionPreventionService | 问题簇→回归检测项，防止问题复现 |
| QualityInsightsService | 多维度质量数据聚合（问题池/回归/版本/AI统计） |
| WorkflowService | 缺陷状态机流转（乐观锁并发控制） |
| RBACService | TTL缓存的角色权限校验 |
| NotificationService | 站内/邮件/Webhook多渠道异步通知 |
| AgentMemoryService | Agent知识记忆的提取、去重和上下文构建 |
| ReportService | 仪表盘数据聚合和CSV/JSON导出 |
| AuditService | 缓冲批量写入的审计日志 |
| CredentialService | AES-256-GCM加密的仓库凭证管理（个人+平台双范围） |
| RepoAuthResolver | 凭证优先级解析（仓库绑定→项目默认→个人） |

### 4.7 ADK Agent框架

ADK（Agent Development Kit）层位于 `server/internal/adk/`，基于 Google ADK SDK 构建，是整个 AI 智能体的核心框架。

#### 架构层次

```
┌─────────────────────────────────────────┐
│           编排层                         │
│  analysis_service.go  fix_service.go    │
│  collaboration_service.go               │
├─────────────────────────────────────────┤
│           执行层                         │
│  agents.go (Agent工厂)                  │
│  planner_agent.go (探索规划)             │
│  collaboration_agent.go (并行Agent)       │
├─────────────────────────────────────────┤
│           工具层                         │
│  tool_registry.go (插件化注册中心)        │
│  safety_gate.go (安全门控)               │
│  tools/code_tools.go (代码工具)          │
│  mcp_integration.go (MCP工具)            │
├─────────────────────────────────────────┤
│           模型层                         │
│  model_factory.go (LLM工厂+FC检测)       │
│  model_adapter.go (ADK LLM适配器)        │
│  prompt_engine.go (模板引擎)             │
├─────────────────────────────────────────┤
│           基础设施                       │
│  scheduler.go (优先级调度器)              │
│  stream_adapter.go (SSE流转换)            │
│  rollout_recorder.go (事件记录)           │
│  memory_callbacks.go (记忆注入/提取)      │
└─────────────────────────────────────────┘
```

#### 核心流程（分析服务）

**[analysis_service.go](file:///Users/admin/Testproject/bug_agent/server/internal/adk/analysis_service.go)** 的 `PerformAnalysis` 方法：

```
1. 加载缺陷和AI配置
2. 更新缺陷状态为 analyzing
3. 为每个 agentType 获取代码上下文（git克隆+检索）
4. Executor阶段：
   a. 创建 Session
   b. 构建 ExplorerContext + 注册工具
   c. 执行 Planner 探索阶段（计划→执行）
   d. 构建并运行 AnalysisPipeline
   e. 收集事件流
5. 后处理：
   a. 提取JSON/归一化字段
   b. 证据修复（normalizeAnalysisByRepoEvidence）
   c. 存储 AnalysisReport
   d. 记录 Token 用量
   e. 异步提取记忆
```

#### 调度器

**[AgentScheduler](file:///Users/admin/Testproject/bug_agent/server/internal/adk/scheduler.go)** 基于 `container/heap` 实现优先级队列，支持：

- 三级优先级：`PriorityUser(0)` > `PriorityAuto(1)` > `PriorityBackground(2)`
- 并发控制：`semaphore.Weighted` 限制最大并发数（默认3）
- 重复检测：同一缺陷不可重复提交
- 取消机制：支持按 defectID 取消排队或运行中的任务

#### 工具注册中心

**[ToolRegistry](file:///Users/admin/Testproject/bug_agent/server/internal/adk/tool_registry.go)** 支持：

- 按名称+工厂函数注册工具
- 按 Agent 类型白名单过滤
- 5分钟 TTL 缓存
- 数据库集成（加载检索器插件工具）

默认注册 5 个内置工具：

| 工具名 | 说明 |
|--------|------|
| `search_code` | 语义搜索代码符号 |
| `read_file` | 读取仓库文件内容 |
| `find_api_handler` | 查找后端API处理器 |
| `list_directory` | 列出目录内容 |
| `trace_call` | 追踪函数调用链 |

#### 提示词模板引擎

**[PromptTemplateEngine](file:///Users/admin/Testproject/bug_agent/server/internal/adk/prompt_engine.go)** 支持模板注册和 `{{.VarName}}` 格式的变量渲染。为每种 Agent 类型注册默认模板：

- `analysis_frontend` / `analysis_backend` / `analysis_test` / `analysis_ui` / `analysis_client`
- `fix_generator`
- `code_explorer`

### 4.8 AI模型适配层

位于 `server/internal/ai/`，采用 **策略模式 + 抽象工厂模式**。

#### 统一接口

```go
type AIClient interface {
    Chat(ctx context.Context, req *ChatRequest) (*ChatResponse, error)
    ChatStream(ctx context.Context, req *ChatRequest) (<-chan *StreamChunk, error)
}
```

#### 厂商适配

| 厂商 | 实现类 | 基类 | 差异点 |
|------|--------|------|--------|
| OpenAI | `OpenAIClient` | `OpenAICompatibleClient` | baseURL = `https://api.openai.com/v1` |
| DeepSeek | `DeepSeekClient` | `OpenAICompatibleClient` | baseURL = `https://api.deepseek.com/v1` |
| DashScope | `DashScopeClient` | `OpenAICompatibleClient` | baseURL = `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 智谱 | `ZhipuClient` | `OpenAICompatibleClient` | baseURL = `https://open.bigmodel.cn/api/paas/v4` |
| Anthropic | `AnthropicClient` | 独立实现 | x-api-key 认证, /v1/messages 端点 |

`OpenAICompatibleClient` 实现完整的 Chat/ChatStream 逻辑，其他厂商通过 Go struct embedding 复用。

#### 代码生成引擎

**[codegen.go](file:///Users/admin/Testproject/bug_agent/server/internal/ai/codegen.go)** 的 `GenerateFix` 流程：

```
分析报告 → 解析 solution.steps[]
  → 对每个 step:
    1. repo.ReadFile() 读取当前代码
    2. 构建修复 Prompt (BuildFixGenerationPrompt)
    3. AI Chat (JSON Response Format)
    4. 解析JSON补丁 (parsePatchResponse)
    5. 应用hunks (applyContentHunks: oldContent精确匹配一次)
    6. 验证 (ValidateFix + validateGeneratedFileSyntax)
    7. 最多重试3次
  → 返回 FixPlan (含 CodeChange 和 Diff)
```

### 4.9 检索模块 (Retrieval)

位于 `server/internal/retrieval/`，采用插件化架构。

#### 接口定义

```go
type Retriever interface {
    Name() string
    Retrieve(ctx context.Context, query Query) ([]Evidence, error)
}

type Query struct {
    Repo       *git.Repository
    Text       string
    Keywords   []string
    TopK       int
    RepoName   string
    RepoURL    string
}

type Evidence struct {
    FilePath string
    SymbolID string
    Line     int
    Snippet  string
    Score    float64
    Source   string
}
```

#### 内置检索器

| 检索器 | 状态 | 策略 |
|--------|------|------|
| **KeywordRetriever** | 已实现 | 文件路径匹配(+10分) + 文件内容搜索(+3分)，按分数降序TopK |
| **RepoWikiRetriever** | 已实现 | HTTP调用外部repo-wiki服务的 `/search_symbols` 端点 |
| **RAGRetriever** | 骨架 | 配置已解析，Retrieve返回未实现错误 |
| **RequirementRetriever** | 骨架 | 已注册 |

#### 注册表

[RetrieverPluginRegistry](file:///Users/admin/Testproject/bug_agent/server/internal/retrieval/registry.go) 支持：

- `RegisterPlugin`：注册插件及配置Schema
- `CreateFromDB`：从数据库记录创建检索器实例
- `ListAvailable`：列出所有可用插件

### 4.10 SSE实时推送

位于 `server/internal/sse/`，基于发布订阅模式。

**Broker** ([broker.go](file:///Users/admin/Testproject/bug_agent/server/internal/sse/broker.go))：

```go
type Broker struct {
    subscribers map[string]map[chan SSEEvent]bool  // room → {ch: true}
    mu          sync.RWMutex
}
```

- **Subscribe(rooms)**：加入指定房间，返回 buffered channel (1024)
- **Unsubscribe(ch)**：从所有房间移除，关闭 channel
- **Publish(room, event)**：向房间内所有客户端推送，慢客户端自动断开

**支持的事件类型**：

| 事件 | 触发场景 |
|------|---------|
| `defect:status_changed` | 缺陷状态变更 |
| `defect:created` / `defect:updated` | 缺陷创建/更新 |
| `analysis:started/progress/completed/failed` | AI分析过程 |
| `fix_task:created/progress/completed/failed` | 自动修复过程 |
| `comment:added` | 评论添加 |
| `collaboration:started/progress/completed` | 多Agent协作 |
| `notification` | 系统通知 |

### 4.11 数据模型与数据库

#### 核心业务模型

| 模型 | 表名 | 关键字段 |
|------|------|---------|
| User | `users` | Username, Email, Password, Nickname, AgentTypes, PlatformRole |
| Project | `projects` | Name, Description, OwnerID, MemoryEnabled, DefectSeq |
| ProjectMember | `project_members` | ProjectID, UserID, Role |
| Defect | `defects` | Code(BUG-XXX-YYYYMM-NNN), Title, Description, Severity, Priority, Type, Status, IterationID |
| FixTask | `fix_tasks` | DefectID, AgentType, RepoID, Plan(JSON), Result(JSON), PRURL, PRStatus |
| FixTaskGroup | `fix_task_groups` | DefectID, TargetBranch, Summary, AIProvider, AIModel |
| AnalysisReport | `analysis_reports` | DefectID, AgentType, Analysis(JSON), Solution(JSON), Provider, Model |
| IssueCluster | `issue_clusters` | ProjectID, Fingerprint, Title, TriageStatus, Severity, SignalCount |
| IssueSignal | `issue_signals` | ClusterID, SourceEventID, Payload(JSON), Platform, AppVersion |
| IntegrationConnector | `integration_connectors` | ProjectID, Type(bugly/aliyun/dingtalk/feishu), Config(JSON), Status |
| Iteration | `iterations` | ProjectID, Name, Status, StartDate, EndDate |
| ProjectRepo | `project_repos` | ProjectID, Name, URL, VCSProvider |
| AgentMemory | `agent_memories` | ProjectID, IterationID, Category, Content, RelevanceScore |
| AITokenUsage | `ai_token_usage` | ProjectID, DefectID, IterationID, Provider, Model, PromptTokens, CompletionTokens, EstimatedCostUSD |

#### 缺陷状态机

```
new → pending_assign → pending_analysis → analyzing → pending_fix
  → fixing → pending_verify → fixed → completed
                                    → rejected
                                    → suspended
```

支持状态：`new`, `pending_assign`, `pending_analysis`, `analyzing`, `pending_fix`, `fixing`, `manual_fixing`, `pending_verify`, `fixed`, `completed`, `rejected`, `suspended`

#### RBAC模型

- **平台角色**：`super_admin` > `admin` > `member`
- **项目角色**：`project_admin` > `developer` > `tester` > `viewer`
- **权限粒度**：`projects:read`, `defects:create`, `agents:analyze`, `fix_tasks:update`, `users:manage` 等 30+ 种权限

### 4.12 外部集成

| 集成 | 目录 | 说明 |
|------|------|------|
| Bugly | [integration/bugly/](file:///Users/admin/Testproject/bug_agent/server/internal/integration/bugly/) | 腾讯Bugly异常信号接入 |
| 阿里云日志 | [integration/aliyunlog/](file:///Users/admin/Testproject/bug_agent/server/internal/integration/aliyunlog/) | 阿里云日志服务信号接入 |
| 云效 | [integration/yunxiao/](file:///Users/admin/Testproject/bug_agent/server/internal/integration/yunxiao/) | 阿里云效仓库/成员同步 |
| VCS | [vcs/](file:///Users/admin/Testproject/bug_agent/server/internal/vcs/) | GitHub/GitLab API客户端（PR创建） |

---

## 5. 前端架构详解

### 5.1 入口与主题系统

**[main.tsx](file:///Users/admin/Testproject/bug_agent/web/src/main.tsx)** → React 18 `createRoot` + StrictMode

**[App.tsx](file:///Users/admin/Testproject/bug_agent/web/src/App.tsx)** 根组件负责：

- **国际化**：Ant Design 中文语言包 (`zhCN`)
- **主题定制**：
  - 主色 `#8b5cf6` (紫色)
  - 统一圆角体系 (16px/24px/12px)
  - 字体栈：Geist → PingFang SC → Microsoft YaHei
  - 细粒度组件 Token (Card/Button/Table/Input/Menu/Modal/Layout)
- **全局消息桥接**：`AntdAppBridge` 将 message API 暴露到工具模块
- **错误边界**：`ErrorBoundary` 捕获渲染异常，显示恢复界面
- **路由挂载**：`RouterProvider`

### 5.2 路由设计

**[router.tsx](file:///Users/admin/Testproject/bug_agent/web/src/router.tsx)** 使用 `createBrowserRouter` + 嵌套路由 + 懒加载。

**路由层级**：

```
/login, /register              → 公开页（无布局）
/                              → 主布局 (AuthGuard)
  /projects                    → 项目列表
  /users                       → 用户管理
  /audit-logs                  → 审计日志
  /ai-catalog                  → AI目录
  /platform-credentials        → 平台凭证
  /platform-settings           → 平台设置
  /role-permissions            → 角色权限
  /profile                     → 个人中心
/projects/:projectId           → 项目布局 (AuthGuard)
  /defects                     → 缺陷列表
  /defects/create              → 创建缺陷
  /defects/:defectId           → 缺陷详情
  /issue-pool                  → 问题池
  /integrations                → 集成管理
  /regression                  → 回归中心
  /quality-insights            → 质量洞察
  /routing                     → 路由中心
  /iterations                  → 迭代管理
  /members                     → 成员管理
  /repos                       → 仓库管理
  /ai-configs                  → AI配置
  /notifications               → 通知设置
  /settings                    → 项目设置
```

所有页面组件使用 `React.lazy` 懒加载 + `Suspense`。

### 5.3 API层

**[api/request.ts](file:///Users/admin/Testproject/bug_agent/web/src/api/request.ts)** 基于 Axios 封装：

- baseURL: `/api/v1`，超时 15 秒
- 请求拦截器：自动注入 `Authorization: Bearer <token>`
- 响应拦截器：
  - `transformCommaFields`：逗号分隔字符串→数组转换
  - 401 检测：匹配 `SESSION_EXPIRED_MESSAGES` 时自动跳转登录
  - 统一格式：`{ code: number; data?: T; message?: string }`

API 模块按业务拆分（12个文件），每个文件以函数导出，泛型贯穿始终。

### 5.4 布局组件体系

位于 [components/layout/](file:///Users/admin/Testproject/bug_agent/web/src/components/layout/)，共 16 个纯展示型组件：

| 组件 | 用途 |
|------|------|
| AppShell | 三栏式容器（sidebar + topbar + content） |
| ShellNavigation | 侧边栏导航菜单 |
| ShellSidebarHeader | 侧边栏品牌标识 |
| ShellTopbarHeading | 顶栏标题 |
| ShellSearchField | 顶栏搜索框 |
| ShellUserTrigger | 用户头像触发器 |
| UserMenuDropdown | 用户菜单（含登出/状态更新监听） |
| PageLayout | 页面级布局容器 |
| PageContent | 内容区包装 |
| PageActionBar | 操作栏 (compact/inline) |
| PageFilterBar | 筛选栏（filters + actions + result） |
| PageMetricSection | 指标+操作组合区 |
| MetricRail | 指标组展示（最多5个） |
| ContextSummaryCard | 上下文摘要卡片 |
| ContextSignalList | 信号标签列表 |
| IterationSummaryList | 迭代摘要列表 |

设计特点：BEM风格CSS命名，`compact`/`subtle`/`inline` prop控制密度，高度可组合。

### 5.5 SSE实时通信

三层架构：

1. **[sseManager.ts](file:///Users/admin/Testproject/bug_agent/web/src/hooks/sseManager.ts)** — 核心单例：
   - EventSource 连接管理，支持房间订阅
   - 16种服务端事件解析
   - 指数退避重连（3s→30s，最多10次）
   - 发布订阅模式 `on/off`

2. **[useSSE.ts](file:///Users/admin/Testproject/bug_agent/web/src/hooks/useSSE.ts)** — React Hooks：
   - `useSSE(rooms)`：连接生命周期管理
   - `useSSEEvent(event, handler)`：事件订阅

3. **[useAnalysisStream.ts](file:///Users/admin/Testproject/bug_agent/web/src/hooks/useAnalysisStream.ts)** — 业务Hook：
   - Fetch ReadableStream 流式读取
   - 自动降级到轮询模式（3s间隔，40轮超时）
   - 页面刷新后恢复分析轮询

### 5.6 核心页面说明

**缺陷列表 (DefectList)**：
- URL参数驱动筛选（iterationId/keyword/status/severity/priority/type/assigneeId/tags）
- 自动恢复上次选中迭代
- 指标卡片 + 筛选栏 + 表格

**缺陷详情 (DefectDetail)** — **最复杂页面 (~850行)**：
- `Promise.allSettled` 并行加载多项数据
- SSE 实时监听缺陷房间事件
- 两栏布局：Tabs(描述/AI分析/修复任务/Token/动态) + 侧边栏(概况/操作)
- 状态机驱动的操作面板
- 6种弹窗（指派/分析/修复/人工修复完成/编辑/驳回）
- `useDefectActions` Hook 抽离复杂状态

**创建缺陷 (DefectCreate)**：
- **对话模式**：自然语言→AI生成草稿→确认提交
- **高级模式**：传统表单（Markdown支持、HTML模板预设）

---

## 6. 核心业务流程

### 6.1 信号接入与分诊流程

```
外部平台 (Bugly/阿里云/钉钉/飞书)
    ↓ HTTP POST /api/v1/inbound/connectors/:token
SignalIngestService.IngestBatch()
    ├─ 字段归一化 (NormalizePayload)
    ├─ 来源差异化补全 (enrichPayloadForSource)
    ├─ 指纹生成 (SHA256: title+stack+description+platform+version)
    ├─ IssueCluster 聚类 (同指纹归入同一簇)
    ├─ IssueSignal 去重入库 (source_event_id)
    ├─ ApplyClusterRouting (路由匹配)
    │   ├─ 按 sort_order 匹配规则
    │   ├─ 匹配方式: source_type/platform/app_version/fingerprint_pattern/stack_keyword
    │   └─ 自动设置模块/负责人/优先级
    └─ Release 版本匹配 (buildNumber精确/appVersion模糊)
```

### 6.2 缺陷分析与自动修复流程

```
缺陷创建 (人工/信号转换)
    ↓
DefectRecommendation (负责人+Agent类型推荐)
    ↓
用户触发分析 (POST /agents/analyze)
    ↓
ADKAnalysisService.PerformAnalysis()
    ├─ 加载缺陷+AI配置
    ├─ 多配置兜底 (analyzeWithFallback)
    ├─ 代码上下文获取 (git克隆+检索)
    ├─ Planner探索阶段 (计划→安全执行)
    ├─ AnalysisPipeline运行 (LLM Agent + 工具调用)
    ├─ 后处理: JSON提取 → 字段归一化 → 证据修复
    ├─ 存储 AnalysisReport + AITokenUsage
    └─ 异步提取记忆 (AgentMemory)
    ↓
FixService.CreateAutoFixGroup()
    ├─ 解析目标仓库 (DefectRepoResolver)
    ├─ 创建 FixTaskGroup + 多个 FixTask
    ├─ executeFixWorkflow() (8步流水线)
    │   1. 浅克隆仓库
    │   2. 创建修复分支
    │   3. AI生成修复代码 (CodeGenerator)
    │   4. 应用代码变更 (hunk精确匹配)
    │   5. Git提交
    │   6. 构建验证 (可选)
    │   7. Git推送
    │   8. 创建PR (GitHub/GitLab)
    └─ SSE实时推送进度
    ↓
人工验证PR → 合并PR → 缺陷状态变更为 fixed → completed
```

### 6.3 缺陷状态机

```
                    ┌──────────────────────┐
                    │        new           │
                    └──────────┬───────────┘
                               │ 指派
                    ┌──────────▼───────────┐
                    │   pending_assign     │
                    └──────────┬───────────┘
                               │ 开始分析
                    ┌──────────▼───────────┐
                    │  pending_analysis    │
                    └──────────┬───────────┘
                               │ 进入分析
                    ┌──────────▼───────────┐
                    │      analyzing       │
                    └──────────┬───────────┘
                               │ 分析完成
                    ┌──────────▼───────────┐
                    │     pending_fix      │
                    └──────────┬───────────┘
                    ┌──────────▼───────────┐
                    │   fixing/manual_     │
                    │   fixing             │
                    └──────────┬───────────┘
                               │ 修复完成
                    ┌──────────▼───────────┐
                    │   pending_verify     │
                    └──────────┬───────────┘
                    ┌──────────▼───────────┐
                    │        fixed         │
                    └──────────┬───────────┘
                    ┌──────────▼───────────┐
                    │     completed        │
                    └──────────────────────┘

                    可中断路径:
                    analyzing → rejected
                    pending_fix → rejected
                    pending_verify → rejected
                    fixed → reopened
                    any → suspended
```

状态流转由 [WorkflowService](file:///Users/admin/Testproject/bug_agent/server/internal/service/workflow.go) 管理，使用乐观锁（`WHERE status = ?`）防止并发冲突。

### 6.4 多Agent协作流程

```
POST /collaborations
    ↓
CollaborationService.StartCollaboration()
    ├─ 创建 CollaborationTask
    ├─ NewCollaborationPipeline(cfg)
    │   └─ 每个 agentType 创建一个 LLM Agent
    │       └─ 超过1个Agent时使用 ParallelAgent 并行化
    ├─ 收集所有 Agent 的分析结果
    ├─ 生成汇总报告 (CollaborationReport)
    └─ SSE推送进度
```

---

## 7. 权限与安全体系

### 认证
- **JWT Token**：golang-jwt/v5，HS256 签名
- **Token黑名单**：进程内内存存储（`map[string]time.Time`），5分钟清理过期条目
- **密码哈希**：bcrypt

### 授权 (RBAC)
- **双层次**：平台角色（超级管理员/管理员/成员）+ 项目角色（管理员/开发者/测试/观察者）
- **TTL缓存**：5分钟过期，最多10000条
- **通配符**：super_admin 拥有 `"*"` 全部权限

### 数据安全
- **凭据加密**：AES-256-GCM 加密存储仓库凭证
- **AI配置加密**：AES-256-GCM 加密存储 API Key
- **邀请码签名**：HMAC-SHA256 签名

### 安全中间件
- **限流**：基于 Redis 的滑动窗口限流
- **审计日志**：缓冲批量写入，记录所有敏感操作
- **CORS**：可配置的跨域白名单

---

## 8. 数据库迁移历史

| 版本 | 文件 | 新增内容 |
|------|------|---------|
| v1.1 | `v1.1_upgrade.sql` | 项目仓库、AI配置 |
| v1.2 | `v1.2_sprint3.sql` | RBAC、审计日志 |
| v2.0 | `v2.0_drop_legacy_rbac.sql` | 清理旧RBAC |
| v2.1 | `v2.1_perf_indexes.sql` | 性能索引 |
| v2.2 | `v2.2_compound_indexes.sql` | 复合索引 |
| v5.5 | `v5.5_agent_capability.sql` | Agent能力/MCP/技能/Token用量/缺陷仓库 |
| v5.6 | `v5.6_*.sql` (4个文件) | 分析任务、检索器插件、灰度记录、权限修复 |
| v5.7 | `v5.7_function_calling_mode.sql` | Function Calling模式 |
| v5.8 | `v5.8_repo_wiki_retriever.sql` | RepoWiki检索器 |

---

## 9. 部署与运行方式

### 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Go | >= 1.25 | 后端编译 |
| PostgreSQL | >= 14 | 主数据库 |
| Redis | >= 6 | 缓存/限流 |
| Node.js | >= 18 | 前端构建 |
| Docker | 可选 | 容器化部署 |

### 后端启动

```bash
# 配置
cp server/cmd/server/config.yaml server/cmd/server/config.yaml
# 编辑 config.yaml 配置数据库/Redis/JWT等

# 直接启动
cd server && go run cmd/server/main.go

# 或通过 Makefile
make run

# Docker 部署
docker build -t bug-agent-server -f server/Dockerfile .
docker compose -f server/docker-compose.yml up
```

### 前端启动

```bash
cd web
npm install
npm run dev     # 开发模式，端口 5678
npm run build   # 生产构建
```

Vite 配置代理 `/api` → `http://localhost:8765`。

### 环境变量

| 变量 | 说明 |
|------|------|
| `DB_PASSWORD` | 数据库密码 |
| `JWT_SECRET` | JWT签名密钥（>=16字符） |
| `CREDENTIAL_ENCRYPT_KEY` | 凭据加密密钥（32字符） |
| `AI_CONFIG_ENCRYPTION_KEY` | AI配置加密密钥（32字符） |
| `INVITE_CODE_SIGN_KEY` | 邀请码签名密钥（>=32字符） |
| `ADMIN_PASSWORD` | 初始管理员密码 |
| `REDIS_PASSWORD` | Redis密码 |
| `SMTP_PASSWORD` | SMTP密码 |

### 测试

```bash
# 后端测试
cd server && go test ./...

# Playwright E2E 测试
cd web && npx playwright test

# E2E流程测试
python tests/e2e_full_flow.py
```

---

## 10. 开发指南

### 代码约定

- **Go**：遵循标准 Go 项目布局，内部包使用 `internal/` 防止外部导入
- **TypeScript**：使用 TypeScript 严格模式，泛型贯穿 API 层
- **前端组件**：纯展示型布局组件 + 业务页面组件 + 自定义 Hook 抽离逻辑
- **错误处理**：Go 使用 `logger.Errorf` 记录错误，前端使用 `getErrorMessage` 统一格式化

### 添加新 API 端点

1. 在 [handler/](file:///Users/admin/Testproject/bug_agent/server/internal/handler/) 中创建/扩展 Handler
2. 在 [service/](file:///Users/admin/Testproject/bug_agent/server/internal/service/) 中实现业务逻辑
3. 在 [router.go](file:///Users/admin/Testproject/bug_agent/server/internal/router/router.go) 中注册路由和中间件
4. 在前端 [api/](file:///Users/admin/Testproject/bug_agent/web/src/api/) 中添加 API 调用函数
5. 在 [types/](file:///Users/admin/Testproject/bug_agent/web/src/types/) 中添加类型定义

### 添加新的 AI 厂商

1. 在 [ai/](file:///Users/admin/Testproject/bug_agent/server/internal/ai/) 中创建新客户端（嵌入 `OpenAICompatibleClient` 或独立实现 `AIClient` 接口）
2. 在 [factory.go](file:///Users/admin/Testproject/bug_agent/server/internal/ai/factory.go) 中注册 Provider 映射
3. 在 [prompts.go](file:///Users/admin/Testproject/bug_agent/server/internal/ai/prompts.go) 中可选添加特定厂商的 Prompt 优化

### 添加新的检索器插件

1. 在 [retrieval/](file:///Users/admin/Testproject/bug_agent/server/internal/retrieval/) 中实现 `Retriever` 接口
2. 在 [builtin.go](file:///Users/admin/Testproject/bug_agent/server/internal/retrieval/builtin.go) 中注册
3. 创建数据库迁移脚本在 `migrations/` 中插入配置条目

### 关键设计模式

- **策略模式**：AI 客户端适配、检索器实现
- **抽象工厂模式**：AI 客户端创建（`NewAIClient`）
- **插件模式**：检索器插件注册表、工具注册中心
- **发布订阅**：SSE Broker
- **适配器模式**：ADK LLM 适配（`AIClientModel`）
- **模板方法**：修复流水线（8步流程）
- **装饰器模式**：HTTP 中间件链