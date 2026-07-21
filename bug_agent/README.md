# Bug Agent — AI 驱动的缺陷管理平台

面向中大型软件开发团队的智能化缺陷管理平台。将 AI Agent 嵌入缺陷处理主链路：从缺陷创建、智能分诊、自动分析、修复执行到代码合并，构建完整的 AI 协作工作流。

## 项目架构

```
bug_agent/
├── server/                  # Go 后端
│   ├── cmd/server/          #   服务入口 & 配置文件
│   │   ├── main.go          #     启动入口（含优雅关停）
│   │   └── config.yaml      #     配置文件（数据库/Redis/JWT/密钥等）
│   ├── internal/
│   │   ├── ai/              #   AI 模型接入（Anthropic/OpenAI/DeepSeek/DashScope/Zhipu）
│   │   ├── cache/           #   Redis 缓存封装
│   │   ├── config/          #   配置加载（Viper + YAML）
│   │   ├── database/        #   数据库初始化 & AutoMigrate
│   │   ├── git/             #   Git 操作（go-git）
│   │   ├── handler/         #   HTTP Handler（控制器层）
│   │   ├── middleware/       #   中间件（Auth/RBAC/RateLimit/Audit）
│   │   ├── model/           #   数据模型 & GORM ORM
│   │   ├── router/          #   路由注册
│   │   ├── service/         #   业务逻辑层
│   │   └── ws/              #   WebSocket 实时推送
│   ├── migrations/          #   SQL 增量迁移脚本
│   └── pkg/response/        #   统一响应封装
│
├── web/                     # React 前端
│   ├── src/
│   │   ├── api/             #   API 请求层（axios + 泛型封装）
│   │   ├── components/      #   通用组件
│   │   ├── constants/       #   共享常量（映射/标签/颜色）
│   │   ├── contexts/        #   React Context（项目上下文）
│   │   ├── hooks/           #   自定义 Hooks（WebSocket）
│   │   ├── layouts/         #   页面布局
│   │   ├── pages/           #   页面
│   │   │   ├── auth/        #     登录 & 注册
│   │   │   ├── defects/     #     缺陷（列表/详情/Chat创建）
│   │   │   ├── projects/    #     项目（工作台/成员/仓库/迭代/信号池/回归等）
│   │   │   ├── system/      #     平台管理（AI目录/审计/凭证/权限）
│   │   │   └── users/       #     用户管理
│   │   ├── types/           #   TypeScript 类型定义
│   │   └── utils/           #   工具函数（存储/日志/错误处理）
│   └── vite.config.ts       #   Vite 配置（含 API 代理）
│
├── docs/                    # PRD / 设计文档 / 测试计划
├── Makefile                 # 常用命令快捷入口
└── docker-compose.yml       # 全栈容器化编排
```

### 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | React 19 + Ant Design 6 + Tailwind CSS + Vite | SPA，Vite 代理 API 请求 |
| 后端 | Go 1.24 + Gin + GORM | RESTful API + WebSocket |
| AI | 多厂商抽象工厂 | Anthropic / OpenAI / DeepSeek / DashScope / Zhipu |
| 数据库 | PostgreSQL 16+ | GORM AutoMigrate 自动建表 |
| 缓存 | Redis 7+ | 会话缓存、性能加速 |
| 外部集成 | 阿里云日志 / Bugly / 云效 / GitHub | 信号接入、Webhook、CI 联动 |

### 核心业务模型

- **项目 / 迭代 / 仓库** — 多级租户体系，迭代绑定仓库和分支
- **缺陷** — 主实体，状态机驱动（新建→待分析→分析中→待修复→修复中→待验证→已完成）
- **AI Agent** — 6 种角色（product/ui/frontend/client/backend/test），支持多 Agent 协作分析
- **修复任务** — 自动修复（AI 生成代码+提 PR）和人工修复
- **信号 (Signal)** — 外部问题信号（Bugly/云效/Webhook），经分诊聚类转为缺陷
- **Agent Memory** — 项目级和迭代级记忆，跨会话上下文保持
- **RBAC** — 平台级（super_admin/admin/member）+ 项目级角色权限

## 启动方式

### 前置依赖

- Go 1.24+
- Node.js 20+
- PostgreSQL 16+
- Redis 7+

### 1. 配置

编辑 `server/cmd/server/config.yaml`，填入实际的数据库和 Redis 连接信息：

```yaml
database:
  host: "your-pg-host"
  port: "5432"
  user: "your-user"
  password: "your-password"
  dbname: "hi_claw"

redis:
  host: "your-redis-host"
  port: "6379"
  password: "your-password"
```

**安全提醒**：`jwt.secret`、`secrets.credential_encrypt_key`、`secrets.ai_config_encryption_key`、`secrets.invite_code_sign_key` 在生产环境必须替换为随机强密钥，不可使用默认值。

### 2. 启动后端

```bash
cd server
go run ./cmd/server/
```

服务监听 `:8765`。首次启动自动完成：
- AutoMigrate 建表
- 初始化 RBAC 权限
- 预置 AI 目录
- 创建默认管理员（admin，密码打印在启动日志中）

健康检查：`GET http://localhost:8765/healthz`

### 3. 启动前端

```bash
cd web
npm install
npm run dev
```

开发服务器监听 `:5678`，`/api` 和 `/ws` 请求自动代理到后端 `:8765`。

### 4. 一键启动（开发用）

```bash
make start     # 后台启动前后端
make stop      # 停止
make status    # 查看运行状态
make restart   # 重启
```

### 5. Docker Compose

```bash
cd server
# 修改 config.yaml 中数据库连接指向 docker-compose 服务名：
#   database.host: "postgres"
#   redis.host: "redis"
docker-compose up -d
```

## 配置参考

所有配置通过 `server/cmd/server/config.yaml` 管理，支持环境变量覆盖（前缀 `BUG_AGENT_`）。

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `server.port` | 服务端口 | `8765` |
| `server.mode` | 运行模式（debug/release） | `debug` |
| `server.cors_origins` | CORS 允许的来源 | localhost 系列 |
| `database.*` | PostgreSQL 连接信息 | — |
| `redis.*` | Redis 连接信息 | — |
| `jwt.secret` | JWT 签名密钥 | ⚠️ 必须修改 |
| `jwt.expire_hour` | Token 有效期（小时） | `72` |
| `secrets.credential_encrypt_key` | 凭证加密密钥（32字符） | ⚠️ 必须修改 |
| `secrets.ai_config_encryption_key` | AI 配置加密密钥（32字符） | ⚠️ 必须修改 |
| `secrets.invite_code_sign_key` | 邀请码签名密钥（32字符） | ⚠️ 必须修改 |
| `kiwiskil.base_url` | 语义搜索服务地址 | — |

## API 概览

所有 API 以 `/api/v1` 为前缀，需要 JWT 认证（登录接口除外）。

| 模块 | 路径前缀 | 说明 |
|---|---|---|
| 认证 | `/auth` | 登录、注册、邀请码 |
| 用户 | `/users` | 用户管理、头像、Agent 类型 |
| 项目 | `/projects` | 项目 CRUD、成员、统计 |
| 迭代 | `/projects/:id/iterations` | 迭代管理、仓库绑定 |
| 缺陷 | `/defects` | 缺陷 CRUD、状态流转、指派、验证 |
| 修复 | `/defects/:id/fix-tasks` | 修复任务、人工修复、PR 生命周期 |
| 分析 | `/agents` | AI 分析、报告查询 |
| 协作 | `/collaborations` | 多 Agent 协作分析 |
| 记忆 | `/projects/:id/memories` | Agent 记忆管理 |
| 信号 | `/projects/:id/issue-clusters` | 信号池、分诊、转换 |
| 仓库 | `/projects/:id/repos` | 仓库管理、连接测试 |
| 凭证 | `/credentials` | VCS 凭证管理 |
| AI 配置 | `/projects/:id/ai-configs` | 项目 AI 模型配置 |
| 通知 | `/notifications` | 站内通知、Webhook |
| RBAC | `/rbac` | 角色、权限管理 |
| 审计 | `/audit-logs` | 操作审计日志 |
| WebSocket | `/ws` | 实时推送（协作状态、通知） |
