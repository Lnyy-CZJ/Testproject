# 缺陷管理平台需求文档（Python 重构版）

**版本**: v1.1-python
**日期**: 2026-06-20
**文档状态**: 兼容性评审稿
**基准来源**: PRD_缺陷管理平台.md v5.8（Go 版），CODE_WIKI.md
**定位**: Python 语言重新实现，API 契约完全兼容现有前端

---

## 目录

- [一、项目背景与重构目标](#一项目背景与重构目标)
- [二、Python 技术栈](#二python-技术栈)
- [三、核心概念（不变）](#三核心概念不变)
- [四、角色与权限（不变）](#四角色与权限不变)
- [五、功能模块（不变）](#五功能模块不变)
- [六、状态模型（不变）](#六状态模型不变)
- [七、实时通信（不变）](#七实时通信不变)
- [八、安全架构](#八安全架构)
- [九、数据模型（不变）](#九数据模型不变)
- [十、API 契约（不变）](#十api-契约不变)
- [十一、Python 项目结构设计](#十一python-项目结构设计)
- [十二、Agent 架构设计（Python 原生方案）](#十二agent-架构设计python-原生方案)
- [十三、非功能性需求](#十三非功能性需求)
- [十四、分阶段开发计划](#十四分阶段开发计划)
- [十五、附录](#十五附录)

---

## 一、项目背景与重构目标

### 1.1 背景

BugAgent 是一个 AI 驱动的智能缺陷管理平台，Go 语言版已完整实现了从信号接入、智能分诊、AI 分析到自动修复的质量闭环（v1.0 ~ v5.8）。

本次重构目标是使用 **Python** 语言重新实现后端服务，保持：

- **业务逻辑不变**：所有功能模块、状态机、工作流与 Go 版一致
- **API 契约兼容**：URL 路径、请求/响应格式、认证方式与前端的现有调用完全兼容
- **数据库 Schema 兼容**：表名、字段名、数据类型与现有 PostgreSQL 数据库一致
- **领域模型不变**：核心实体、实体关系、业务规则不变

### 1.2 重构原则

1. **不是翻译 Go 代码**：用 Python 生态的原生工具重新设计实现，不 1:1 翻译
2. **API 契约优先**：先锁定 Pydantic Schema、路由矩阵、错误响应与 SSE 事件，确保前端零改动
3. **Python 原生 Agent**：用 LangGraph 替代 Google ADK，用 `@mcp.tool()` 替代自研 ToolRegistry
4. **渐进交付**：分 7 个阶段（第零阶段到第六阶段），每阶段产出独立可运行、可验收、可回滚的服务能力
5. **行为等价优先于代码形态**：Python 版可以采用原生架构，但用户可见行为、前端契约、数据库读写语义必须与 Go 版等价

### 1.3 兼容性迁移原则

Python 重构不是重新定义产品，而是在保持 Go 版业务行为的前提下替换后端实现。所有开发任务必须先满足以下兼容性边界：

| 兼容维度 | 必须保持 | 验证方式 |
|---------|---------|---------|
| 前端 API | 路径、方法、请求参数、响应字段、分页结构、错误格式不变 | 契约快照测试 + 前端 E2E |
| 数据库 | 表名、字段名、类型、默认值、索引、唯一约束、历史数据读取语义不变 | SQLAlchemy 元数据与 Go 版 schema diff |
| 状态机 | 13 个状态、24 条流转、状态副作用、历史记录不变 | 状态矩阵单测 + 并发流转测试 |
| 权限 | 平台角色、项目角色、权限码、拒绝响应不变 | RBAC 权限矩阵测试 |
| SSE | 连接方式、事件名、data JSON 字段、断线行为不破坏前端 | SSE golden event 测试 |
| Agent 输出 | 分析报告 JSON、思考过程、Token 用量、失败报告格式不变 | 固定输入 golden report 测试 |
| 修复链路 | 修复任务组、PR 生命周期、拒绝回退、人工修复路径不变 | Git fixture 集成测试 |

当 Python 原生实现与 Go 版行为存在差异时，以 Go 版已上线行为为准；如需调整产品行为，必须单独形成变更说明并经过评审。

### 1.4 与 Go 版的关键差异

| 维度 | Go 版 | Python 版 |
|------|-------|-----------|
| Web 框架 | Gin | FastAPI |
| ORM | GORM | SQLAlchemy 2.0 (async) |
| Agent 框架 | Google ADK | LangGraph + PydanticAI |
| 任务调度 | 自研 AgentScheduler (heap+semaphore) | Celery + Redis |
| 工具系统 | ToolRegistry (自研) | MCP Python SDK (`@mcp.tool()`) |
| SSE Broker | 自研 channel-based | `sse-starlette` + Redis Pub/Sub |
| 配置管理 | Viper | Pydantic Settings |
| Git 操作 | go-git | GitPython |
| 提示词引擎 | 自研模板引擎 | Jinja2 / 直接 Python f-string |
| 序列化 | struct tag | Pydantic v2 |
| 异步模型 | goroutine + channel | asyncio + Celery Task |
| 数据库迁移 | 手动 SQL | Alembic |

---

## 二、Python 技术栈

### 2.1 核心依赖

| 类别 | 库 | 版本 | 用途 |
|------|-----|------|------|
| Web 框架 | FastAPI | >= 0.115 | HTTP API + 自动 OpenAPI 文档 |
| ASGI 服务器 | Uvicorn | >= 0.30 | 生产级 ASGI 服务 |
| ORM | SQLAlchemy | >= 2.0 | 异步数据库操作 |
| 数据库驱动 | asyncpg | >= 0.29 | PostgreSQL 异步驱动 |
| 数据校验 | Pydantic | >= 2.0 | Schema 定义与验证 |
| 数据库迁移 | Alembic | >= 1.13 | 数据库版本迁移 |
| 认证 | python-jose + passlib | — | JWT + bcrypt |
| 缓存 | redis-py | >= 5.0 | Redis 客户端 |
| 任务队列 | Celery | >= 5.3 | 异步任务调度 |
| 配置 | Pydantic Settings | >= 2.0 | 类型安全配置管理 |
| Git | GitPython | >= 3.1 | Git 操作（克隆/分支/提交/推送） |
| SSE | sse-starlette | >= 2.0 | Server-Sent Events |
| HTTP 客户端 | httpx | >= 0.27 | 外部 API 调用 |
| 加密 | cryptography | >= 42.0 | AES-GCM 加密 |

### 2.2 Agent 相关

| 类别 | 库 | 版本 | 用途 |
|------|-----|------|------|
| Agent 框架 | LangGraph | >= 0.2 | Agent 状态图编排 |
| LLM 客户端 | PydanticAI / langchain-openai | — | 统一 LLM 调用接口 |
| MCP 工具 | mcp (Python SDK) | >= 1.0 | Agent 工具定义 |
| 检索 | LightRAG / Qdrant | — | 向量检索（第四阶段） |

### 2.3 开发与部署

| 类别 | 工具 | 用途 |
|------|------|------|
| 包管理 | uv / poetry | 依赖管理 |
| 代码格式化 | ruff | Lint + Format |
| 类型检查 | mypy | 静态类型检查 |
| 测试 | pytest + pytest-asyncio | 单元/集成测试 |
| 容器化 | Docker + docker-compose | 部署 |
| CI/CD | GitHub Actions | 自动化流水线 |

---

## 三、核心概念（不变）

### 3.1 组织架构

| 概念 | 说明 |
|------|------|
| 项目 | 具体的软件开发项目，拥有独立的成员、迭代、AI 配置和代码仓库 |
| 代码仓库 | 项目级别的 Git 仓库资源池，可在创建迭代时复用绑定 |
| 迭代 | 项目的时间盒管理单元，一个项目可以有多个迭代，绑定项目仓库中的子集 |
| AI配置 | 项目级别的 AI 模型配置，包含厂商、模型、访问密钥等 |

### 3.2 核心实体

| 实体 | 说明 |
|------|------|
| 缺陷 | 记录软件中存在的问题，归属于迭代 |
| 缺陷草稿 | AI 根据用户自然语言描述生成的结构化草稿，确认后转为正式缺陷 |
| 修复任务 | Agent 执行或人工完成的修复任务单元，关联到缺陷和仓库 |
| 修复任务组 | 多仓库修复的聚合任务，包含多个 FixTask |
| 评论 | 缺陷讨论区的消息记录 |
| Agent身份 | 平台内置的 AI 角色，具备特定领域的分析和修复能力 |
| 分析报告 | Agent 对缺陷进行分析后生成的报告（含根因、影响范围、修复建议） |
| 问题簇 | 外部信号聚类后的聚合单元，通过指纹识别归并 |
| 问题信号 | 外部平台上报的原始异常信号，归一化后归入问题簇 |
| 连接器 | 从外部平台接入信号的通道配置 |
| Agent记忆 | 项目级/迭代级的知识沉淀，AI 分析和修复时自动注入上下文 |
| MCP服务 | 项目内配置的 MCP（Model Context Protocol）服务，扩展 AI 能力 |
| Agent技能 | 项目内配置的 Agent 指令、工具和 MCP 绑定 |

### 3.3 缺陷属性

| 属性 | 类型 | 说明 |
|------|------|------|
| 标题 | 文本 | 缺陷的简要描述 |
| 描述 | 富文本 | 缺陷的详细说明，支持 Markdown |
| 严重级别 | 枚举 | 致命/严重/一般/轻微/建议 |
| 优先级 | 枚举 | P0/P1/P2/P3/P4 |
| 缺陷类型 | 枚举 | 功能缺陷/UI问题/性能问题/安全问题/兼容性问题/其他 |
| 状态 | 枚举 | 见状态流转章节 |
| 附件 | 文件 | 截图、日志、复现视频等 |
| 标签 | 多选 | 自定义标签，便于分类筛选 |

---

## 四、角色与权限（不变）

### 4.1 平台角色

| 角色 | 说明 | 核心权限 |
|------|------|---------|
| 超级管理员 | 平台级别最高管理者 | 管理全平台用户、凭证、AI 目录、平台设置、审计日志 |
| 管理员 | 平台级别管理者 | 管理用户、项目全局配置 |
| 成员 | 普通平台用户 | 参与项目、使用系统功能 |

### 4.2 项目角色

| 角色 | 说明 | 核心权限 |
|------|------|---------|
| 项目管理员 | 项目级别管理者 | 管理项目成员、创建迭代、配置项目规则、AI 配置、Agent 能力 |
| 开发者 | 负责开发修复 | 查看分配缺陷、处理缺陷、合并代码、管理 Agent 记忆 |
| 测试人员 | 负责质量验证 | 创建缺陷、分配缺陷、验证缺陷、发起自动/人工修复 |
| 观察者 | 只读权限 | 查看缺陷详情、查看统计数据和报告 |

### 4.3 Agent身份

平台内置以下 Agent 身份，每个 Agent 具备特定领域的专业能力：

| Agent类型 | 角色标识 | 核心能力 | 分析维度 |
|-----------|---------|---------|---------|
| 产品Agent | product | 需求理解、业务逻辑分析、用户场景分析 | 产品需求偏离、功能定义问题、业务逻辑缺陷 |
| UI_Agent | ui | 视觉规范分析、交互设计评估、设计系统校验 | UI还原度问题、交互体验问题、设计规范偏离 |
| 前端Agent | frontend | 前端代码分析、浏览器兼容性分析、性能诊断 | 前端逻辑错误、样式问题、兼容性问题、性能瓶颈 |
| 客户端Agent | client | 移动端特性分析、原生能力评估、平台适配 | 平台适配问题、原生交互问题、移动端性能问题 |
| 后端Agent | backend | 服务端逻辑分析、数据库分析、API设计评估 | 接口逻辑错误、数据一致性问题、性能问题、安全问题 |
| 测试Agent | test | 测试用例分析、复现步骤生成、测试覆盖评估 | 测试覆盖不足、边界条件遗漏、复现步骤不完整 |

### 4.4 用户-Agent绑定规则

- 一个用户可以绑定多个 Agent 身份（如：前端+后端）
- 管理员可在用户管理页面为用户分配或调整 Agent 身份
- 用户被分配缺陷时，系统根据其绑定的 Agent 身份激活对应能力
- Agent 身份变更后，对后续缺陷分析生效

### 4.5 RBAC 权限模型（Python 实现方式）

```python
# FastAPI 中通过 Depends 实现权限校验
from fastapi import Depends

@router.get("/defects/{defect_id}")
async def get_defect(
    defect_id: int,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(RequirePermission("defects:read")),
) -> DefectDetail:
    ...
```

- **平台角色**：super_admin > admin > member
- **项目角色**：project_admin > developer > tester > viewer
- **权限粒度**：30+ 种权限（`projects:read`, `defects:create`, `agents:analyze`, `fix_tasks:update`, `users:manage` 等）
- **缓存策略**：Redis 缓存用户权限列表（TTL 5分钟），角色变更时主动失效

---

## 五、功能模块（不变）

以下 14 个功能模块的完整业务逻辑与 Go 版一致，仅列出模块清单。详细流程请参考原版 PRD 第四章。

| 序号 | 模块 | 说明 |
|------|------|------|
| 4.1 | 项目管理 | 项目 CRUD、仓库资源池、AI 配置、迭代管理 |
| 4.2 | 用户与权限管理 | 用户列表、Agent身份分配、RBAC 权限模型 |
| 4.3 | 缺陷管理 | 缺陷创建（表单/对话双模式）、列表筛选、详情展示、分配、附件管理 |
| 4.4 | Agent分析 | 分析触发、Planner+Executor流程、流式分析、分析报告 |
| 4.5 | 修复管理 | AI自动修复（8步流水线）、人工修复双路径、修复任务组 |
| 4.6 | PR生命周期 | PR状态跟踪、拒绝回退、合并推进、Webhook回调 |
| 4.7 | 问题池与信号接入 | 外部连接器、信号归一化、问题簇管理、路由规则 |
| 4.8 | Agent能力管理 | Agent记忆（项目/迭代两级）、MCP服务、Agent技能 |
| 4.9 | 检索器插件 | 关键词检索、RepoWiki、RAG（预留） |
| 4.10 | 通知管理 | 站内通知、邮件、Webhook、项目/个人通知策略 |
| 4.11 | 质量洞察与回归预防 | 多维度质量聚合、回归检测项 |
| 4.12 | 报表与统计 | 仪表盘、Token成本统计、CSV/JSON导出 |
| 4.13 | 平台治理 | 凭证管理、AI目录、平台设置、审计日志 |
| 4.14 | 协作讨论 | 缺陷评论、多Agent并行协作 |

---

## 六、状态模型（不变）

### 6.1 状态定义

| 状态 | 说明 | 可操作角色 |
|------|------|-----------|
| `new` | 新建 | 测试人员 |
| `pending_assign` | 待分配 | 测试人员 |
| `pending_analysis` | 待分析 | 系统（自动流转） |
| `analyzing` | 分析中 | 系统（自动流转） |
| `pending_fix` | 待修复 | 测试人员、被分配用户 |
| `fixing` | AI修复中 | 系统（自动流转） |
| `manual_fixing` | 人工修复中 | 被分配用户 |
| `pending_verify` | 待验证 | 测试人员 |
| `fixed` | 已修复 | 被分配用户 |
| `completed` | 已完成 | 所有人员（只读） |
| `rejected` | 驳回 | 被分配用户 |
| `suspended` | 暂停 | 被分配用户 |
| `reopened` | 重新打开 | 被分配用户 |

### 6.2 状态流转规则

| 当前状态 | 目标状态 | 触发条件 | 操作人 |
|---------|---------|---------|--------|
| new | pending_assign | 提交缺陷 | 测试人员 |
| pending_assign | pending_analysis | 分配缺陷 | 测试人员 |
| pending_analysis | analyzing | 开始分析 | 用户/系统 |
| pending_analysis | rejected | 认为不是缺陷 | 被分配用户 |
| analyzing | pending_fix | AI分析完成 | 系统自动 |
| pending_fix | fixing | 发起自动修复 | 测试人员 |
| pending_fix | manual_fixing | 发起人工修复 | 测试人员 |
| pending_fix | pending_analysis | 重新分析 | 测试人员 |
| pending_fix | rejected | 驳回 | 被分配用户 |
| pending_fix | suspended | 暂停处理 | 被分配用户 |
| fixing | pending_verify | AI修复完成 | 系统自动 |
| manual_fixing | pending_verify | 提交修复完成 | 被分配用户 |
| manual_fixing | pending_fix | 放弃人工修复 | 被分配用户 |
| pending_verify | fixed | PR合并 | VCS Webhook/手动 |
| pending_verify | pending_fix | PR拒绝/验证失败 | VCS Webhook/手动 |
| fixed | completed | 代码合并完成 | 被分配用户 |
| completed | — | 终态 | — |
| rejected | reopened | 重新打开 | 被分配用户 |
| rejected | pending_analysis | 重新打开到待分析 | 被分配用户 |
| reopened | pending_analysis | 回到待分析 | 被分配用户 |
| reopened | analyzing | 直接重新分析 | 被分配用户 |
| reopened | pending_fix | 跳过分析直接修复 | 被分配用户 |
| reopened | rejected | 驳回 | 被分配用户 |
| suspended | pending_fix | 恢复处理 | 被分配用户 |

### 6.3 Python 状态机实现

```python
from enum import StrEnum
from typing import ClassVar

class DefectStatus(StrEnum):
    NEW = "new"
    PENDING_ASSIGN = "pending_assign"
    PENDING_ANALYSIS = "pending_analysis"
    ANALYZING = "analyzing"
    PENDING_FIX = "pending_fix"
    FIXING = "fixing"
    MANUAL_FIXING = "manual_fixing"
    PENDING_VERIFY = "pending_verify"
    FIXED = "fixed"
    COMPLETED = "completed"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    REOPENED = "reopened"

class WorkflowService:
    _TRANSITIONS: ClassVar[dict[DefectStatus, set[DefectStatus]]] = {
        DefectStatus.NEW: {DefectStatus.PENDING_ASSIGN},
        DefectStatus.PENDING_ASSIGN: {DefectStatus.PENDING_ANALYSIS},
        DefectStatus.PENDING_ANALYSIS: {DefectStatus.ANALYZING, DefectStatus.REJECTED},
        DefectStatus.ANALYZING: {DefectStatus.PENDING_FIX},
        DefectStatus.PENDING_FIX: {
            DefectStatus.FIXING, DefectStatus.MANUAL_FIXING,
            DefectStatus.PENDING_ANALYSIS, DefectStatus.REJECTED,
            DefectStatus.SUSPENDED,
        },
        DefectStatus.FIXING: {DefectStatus.PENDING_VERIFY},
        DefectStatus.MANUAL_FIXING: {DefectStatus.PENDING_VERIFY, DefectStatus.PENDING_FIX},
        DefectStatus.PENDING_VERIFY: {DefectStatus.FIXED, DefectStatus.PENDING_FIX},
        DefectStatus.FIXED: {DefectStatus.COMPLETED},
        DefectStatus.REJECTED: {DefectStatus.REOPENED, DefectStatus.PENDING_ANALYSIS},
        DefectStatus.REOPENED: {
            DefectStatus.PENDING_ANALYSIS, DefectStatus.ANALYZING,
            DefectStatus.PENDING_FIX, DefectStatus.REJECTED,
        },
        DefectStatus.SUSPENDED: {DefectStatus.PENDING_FIX},
    }

    _TERMINAL: ClassVar[set[DefectStatus]] = {DefectStatus.COMPLETED}

    @classmethod
    def is_valid_transition(cls, from_: DefectStatus, to: DefectStatus) -> bool:
        return to in cls._TRANSITIONS.get(from_, set())

    @classmethod
    def get_valid_transitions(cls, current: DefectStatus) -> set[DefectStatus]:
        return cls._TRANSITIONS.get(current, set())
```

---

## 七、实时通信（不变）

### 7.1 SSE 推送架构（Python 实现）

使用 `sse-starlette` + Redis Pub/Sub 替代 Go 版的自研 SSE Broker。

- **连接端点**：`GET /api/v1/sse?token={jwt}&rooms=defect:1,project:5`
- **Redis Pub/Sub**：`room` → `channel` 映射，支持多进程部署
- **慢客户端保护**：当客户端 buffer 满时自动断开

**支持的事件类型**（与 Go 版完全一致）：

| 事件 | 说明 |
|------|------|
| `defect:status_changed` | 缺陷状态变更 |
| `defect:created` / `defect:updated` | 缺陷创建/更新 |
| `analysis:started/progress/completed/failed/cancelled` | AI分析过程 |
| `fix_task:created/progress/completed/failed` | 自动修复过程 |
| `comment:added` | 评论添加 |
| `collaboration:started/progress/completed` | 多Agent协作 |
| `notification` | 系统通知 |

### 7.2 流式分析（Python 实现）

使用 FastAPI `StreamingResponse` + LangGraph `stream_events()` 实现：

```python
from fastapi.responses import StreamingResponse

@router.post("/agents/analyze/stream")
async def trigger_analysis_stream(request: AnalysisRequest):
    async def event_generator():
        async for event in agent_service.stream_analyze(request):
            yield f"data: {event.model_dump_json()}\n\n"
            await asyncio.sleep(0)  # 让出控制权

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

- 降级机制：流式失败时自动切换到 Celery 轮询模式
- 前端兼容：事件格式与 Go 版完全一致

---

## 八、安全架构

### 8.1 认证与授权

| 机制 | Python 实现 |
|------|------------|
| JWT认证 | `python-jose` + `passlib[bcrypt]` |
| Token黑名单 | Redis SET（TTL = JWT有效期） |
| RBAC | FastAPI `Depends` + Redis 缓存（5分钟 TTL） |
| 强制改密 | 登录时检查 `must_change_password` 标志 |

### 8.2 数据安全

| 措施 | Python 实现 |
|------|------------|
| 凭据加密 | `cryptography` 库 AES-256-GCM |
| 密钥脱敏 | Pydantic `model_serializer` 自动脱敏 |
| 邀请码签名 | HMAC-SHA256 |
| 仓库隔离 | `tempfile.mkdtemp(prefix=f"defect-{defect_id}-")` |

### 8.3 安全中间件

| 中间件 | Python 实现 |
|--------|------------|
| 限流 | `slowapi`（基于 Redis 滑动窗口） |
| CORS | FastAPI `CORSMiddleware` |
| 审计日志 | SQLAlchemy `after_flush` 事件 + 缓冲批量写入 |

### 8.4 Agent 安全

| 措施 | Python 实现 |
|------|------------|
| 工具权限 | LangGraph 的 `ToolNode` 可配置允许的工具列表 |
| MCP命令白名单 | 启动时校验 `mcp-server` 或 `mcp` |
| 操作溯源 | LangGraph `checkpointer` 持久化 Agent 对话历史 |

---

## 九、数据模型（不变）

数据库 Schema 与 Go 版完全一致。以下为 Python ORM 的实现约定。

### 9.1 核心数据表（16 张详细表）

| 表名 | 模型类 | 关键约束 |
|------|--------|---------|
| `users` | User | username UNIQUE, email UNIQUE |
| `projects` | Project | name NOT NULL |
| `project_members` | ProjectMember | (project_id, user_id) UNIQUE |
| `project_repos` | ProjectRepo | (project_id, repo_url) UNIQUE |
| `project_ai_configs` | ProjectAIConfig | project_id FK |
| `iterations` | Iteration | project_id FK |
| `iteration_repos` | IterationRepo | (iteration_id, repo_id) UNIQUE |
| `defects` | Defect | code UNIQUE, iteration_id FK |
| `analysis_reports` | AnalysisReport | defect_id FK |
| `fix_task_groups` | FixTaskGroup | defect_id FK |
| `fix_tasks` | FixTask | defect_id FK, repo_id FK |
| `comments` | Comment | defect_id FK |
| `attachments` | Attachment | defect_id FK |
| `issue_clusters` | IssueCluster | fingerprint INDEX, project_id FK |
| `issue_signals` | IssueSignal | (connector_id, source_event_id) UNIQUE |
| `integration_connectors` | IntegrationConnector | project_id FK, token UNIQUE |
| `agent_memories` | AgentMemory | (project_id, iteration_id) INDEX |
| `ai_token_usage` | AITokenUsage | (project_id, defect_id, iteration_id) INDEX |

### 9.2 其他系统表

`roles`, `permissions`, `role_permissions`, `user_roles`, `status_changes`, `notifications`, `notification_templates`, `notification_preferences`, `project_webhooks`, `project_notification_policies`, `platform_settings`, `pr_rejections`, `analysis_tasks`, `retriever_plugins`, `rollout_records`, `collaboration_tasks`, `collaboration_reports`, `repo_credentials`, `platform_credential_projects`, `invite_codes`, `audit_logs`, `project_mcp_servers`, `project_agent_skills`, `project_modules`, `issue_routing_rules`, `app_releases`, `regression_items`, `integration_sync_records`, `project_ai_catalog`, `ai_model_catalog`

### 9.3 数据库兼容性要求

Python 版必须能够直接读取 Go 版生产数据库备份。数据库兼容不只包含表名字段名一致，还包括默认值、索引、唯一约束、空值语义、时间精度和 JSON 字段结构一致。

| 检查项 | 要求 | 验收方式 |
|-------|------|---------|
| 表结构 | Python ORM 覆盖 Go 版全部业务表，不新增破坏性字段 | 导出 SQLAlchemy metadata 与 PostgreSQL information_schema diff |
| 字段类型 | BigInt、Text、JSON、DateTime、Boolean 等类型与 Go 版一致 | schema diff 报告无阻断差异 |
| 默认值 | 状态、角色、布尔开关、时间字段默认值一致 | 插入最小记录并比对结果 |
| 约束索引 | 唯一约束、组合索引、外键约束不丢失 | 迁移后运行约束测试 |
| 历史数据 | Go 版已有数据可被 Python ORM 正常反序列化 | 使用脱敏备份执行只读回归 |
| 迁移策略 | Python Alembic 只管理 Python 后续变更，不重写 Go 历史 SQL | Alembic baseline 评审通过 |

数据库迁移采用 **baseline + 增量迁移** 方案：先用 Go 版现有 schema 作为 Alembic baseline，再由 Python 后续版本生成增量迁移。不得在首版 Python 迁移中删除、重命名或改变 Go 版已有字段语义。

### 9.4 Python ORM 实现示例

```python
from sqlalchemy import String, Text, Boolean, Integer, BigInteger, DateTime, ForeignKey, JSON, Float, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50))
    avatar: Mapped[str | None] = mapped_column(String(255))
    agent_types: Mapped[str | None] = mapped_column(String(200))
    platform_role: Mapped[str] = mapped_column(String(30), default="member")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class Defect(Base):
    __tablename__ = "defects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    iteration_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("iterations.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), default="一般")
    priority: Mapped[str] = mapped_column(String(10), default="P2")
    type: Mapped[str] = mapped_column(String(30), default="功能缺陷")
    status: Mapped[str] = mapped_column(String(20), default="new")
    assignee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    reporter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    tags: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

### 9.5 Pydantic API Schema 示例

所有 API 响应的字段名使用 **camelCase**，与前端保持一致：

```python
from pydantic import BaseModel, Field
from datetime import datetime

class DefectListItem(BaseModel):
    id: int
    code: str
    title: str = Field(alias="title")
    severity: str
    priority: str
    type: str = Field(alias="type")
    status: str
    assigneeId: int | None = Field(default=None, alias="assignee_id")
    reporterId: int = Field(alias="reporter_id")
    createdAt: datetime = Field(alias="created_at")
    iterationId: int = Field(alias="iteration_id")
    tags: list[str] = []

    model_config = {"populate_by_name": True}  # 同时接受 snake_case 和 camelCase

class PaginatedResponse(BaseModel):
    list: list
    total: int
    page: int
    size: int

class ApiResult(BaseModel):
    code: int = 0
    data: object | None = None
    message: str | None = None
```

---

## 十、API 契约（不变）

### 10.1 响应格式约定（与前端的契约）

```json
{
    "code": 0,
    "data": { ... },
    "message": "..."
}
```

- `code: 0` 表示成功，非 0 表示失败
- 认证失败返回 HTTP 401 + `code: 401`
- 分页列表返回 `{ "list": [...], "total": N, "page": N, "size": N }`
- 字段统一使用 **camelCase**（`agentTypes`, `createdAt`, `defectId` 等）

### 10.2 API 分组总览（22 组，200+ 端点）

| 分组 | 前缀 | 端点数 | 认证 |
|------|------|--------|------|
| 认证 | `/api/v1/auth/*`, `/api/v1/users/me/*` | 8 | 部分公开 |
| 用户管理 | `/api/v1/users/*` | 6 | JWT + RBAC |
| 项目管理 | `/api/v1/projects/*` | 8 | JWT + RBAC |
| 仓库管理 | `/api/v1/projects/:id/repos/*` | 6 | JWT + RBAC |
| AI配置 | `/api/v1/projects/:id/ai-configs/*` | 4 | JWT + RBAC |
| 迭代管理 | `/api/v1/projects/:id/iterations/*` | 9 | JWT + RBAC |
| 缺陷管理 | `/api/v1/defects/*` | 19 | JWT + RBAC |
| 附件 | `/api/v1/defects/:id/attachments/*` | 3 | JWT + RBAC |
| Agent分析 | `/api/v1/agents/*` | 7 | JWT + RBAC |
| 修复任务 | `/api/v1/defects/:id/fix-tasks/*`, `/api/v1/fix-tasks/*` | 8 | JWT + RBAC |
| 工作流 | `/api/v1/defects/:id/transition`, `/api/v1/workflow/batch` | 4 | JWT + RBAC |
| 问题池 | `/api/v1/projects/:id/issue-clusters/*` | 14 | JWT + RBAC |
| 连接器 | `/api/v1/projects/:id/integrations/*`, `/api/v1/inbound/connectors/:token` | 8 | Token/ JWT |
| 权限审计 | `/api/v1/rbac/*`, `/api/v1/audit-logs/*` | 8 | JWT + RBAC |
| 通知 | `/api/v1/notifications/*`, `/api/v1/notification-preferences/*` | 9 | JWT |
| Agent记忆 | `/api/v1/projects/:id/memories/*` | 6 | JWT + RBAC |
| MCP服务 | `/api/v1/projects/:id/mcp-servers/*` | 5 | JWT + RBAC |
| Agent技能 | `/api/v1/projects/:id/skills/*` | 4 | JWT + RBAC |
| 检索器 | `/api/v1/projects/:id/retriever-plugins/*` | 4 | JWT + RBAC |
| 报表统计 | `/api/v1/reports/*` | 7 | JWT |
| Token统计 | `/api/v1/projects/:id/token-usage/*`, `/api/v1/defects/:id/token-usage/*` | 7 | JWT + RBAC |
| 协作 | `/api/v1/collaborations/*` | 4 | JWT + RBAC |

> 完整的路径、方法、权限列表参见原版 PRD 第九章。

### 10.3 Python FastAPI 路由实现示例

```python
from fastapi import APIRouter, Depends, Query
from app.api.deps import get_current_user, RequirePermission
from app.schemas.defect import DefectCreate, DefectDetail, PaginatedResponse, ApiResult

router = APIRouter(prefix="/api/v1/defects", tags=["defects"])

@router.get("", response_model=ApiResult[PaginatedResponse])
async def list_defects(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    severity: str | None = None,
    keyword: str | None = None,
    iteration_id: int | None = None,
    current_user = Depends(get_current_user),
    _: bool = Depends(RequirePermission("defects:read")),
) -> ApiResult[PaginatedResponse]:
    ...

@router.post("", response_model=ApiResult[DefectDetail], status_code=201)
async def create_defect(
    body: DefectCreate,
    current_user = Depends(get_current_user),
    _: bool = Depends(RequirePermission("defects:create")),
) -> ApiResult[DefectDetail]:
    ...

@router.get("/{defect_id}", response_model=ApiResult[DefectDetail])
async def get_defect(
    defect_id: int,
    current_user = Depends(get_current_user),
    _: bool = Depends(RequireDefectPermission("defects:read", "defect_id")),
) -> ApiResult[DefectDetail]:
    ...
```

### 10.4 API 契约冻结要求

Python 版开发前必须生成并评审 API 契约矩阵。矩阵以 Go 版 `server/internal/router/router.go`、前端 `web/src/api/*` 和现有 E2E 用例为来源，每个端点必须包含以下字段：

| 字段 | 说明 |
|------|------|
| 分组 | auth / users / projects / defects / agents / fix_tasks 等 |
| Method + Path | 完整路径，使用 FastAPI 风格参数但必须兼容 Go 版 URL |
| 认证方式 | public / JWT / connector token / invite code |
| 权限码 | 平台权限、项目权限或缺陷权限 |
| Request | query、path、body、form-data、file 字段 |
| Response | 成功响应的 `data` schema，字段必须为 camelCase |
| Error | 401、403、404、409、422、500 的 HTTP 状态和业务 code |
| 前端依赖 | 使用该接口的页面、组件或 API 封装文件 |
| SSE 副作用 | 是否产生事件、事件名、room |
| 数据副作用 | 写入哪些表、是否创建状态历史、通知或审计日志 |

未进入契约矩阵的 API 不允许进入开发；矩阵变更必须同步更新测试快照。

### 10.5 兼容性测试基线

Python 版必须建立三类兼容性测试：

1. **契约快照测试**：对 OpenAPI schema、关键响应 JSON、错误响应 JSON 做快照比对。
2. **黄金样例测试**：使用固定数据库 fixture，验证登录、项目、缺陷、状态流转、分析报告、修复任务、通知、SSE 事件输出。
3. **前端零改动 E2E**：复用 `web/e2e` 中核心用例，前端只切换后端地址，不改 TypeScript 代码。

最低黄金样例清单：

| 场景 | 必须验证 |
|------|---------|
| 登录 | 成功、密码错误、强制改密、token 过期 |
| 缺陷列表 | 分页、筛选、排序、空数组、camelCase 字段 |
| 缺陷详情 | assignee/reporter 嵌套对象、附件、评论、分析报告 |
| 状态流转 | 24 条合法流转、非法流转拒绝、并发流转只成功一次 |
| 权限 | 平台角色、项目角色、缺陷级权限、403 响应 |
| SSE | status_changed、analysis progress、notification 的 event/data 格式 |
| Agent | 成功报告、失败报告、取消、Token 统计 |
| 修复 | 自动修复任务组、人工修复、PR rejected 回退 |

---

## 十一、Python 项目结构设计

```
bug_agent_py/
├── pyproject.toml                 # 项目元数据 + 依赖声明
├── Dockerfile                     # 生产镜像
├── docker-compose.yml             # 本地开发环境（PostgreSQL + Redis + App）
├── Makefile                       # 常用命令快捷方式
│
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 应用工厂 + 生命周期事件
│   ├── config.py                  # Pydantic Settings（环境变量 + .env）
│   │
│   ├── api/                       # ── 路由层 ──
│   │   ├── __init__.py
│   │   ├── deps.py                # FastAPI Depends 可复用依赖
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py          # 总路由注册（include_router）
│   │       ├── auth.py            # POST /auth/register, POST /auth/login ...
│   │       ├── users.py           # GET /users, PUT /users/:id/agent-types ...
│   │       ├── projects.py        # GET/POST/PUT /projects ...
│   │       ├── repos.py           # GET/POST/PUT/DELETE /projects/:id/repos ...
│   │       ├── ai_configs.py      # /projects/:id/ai-configs ...
│   │       ├── iterations.py      # /projects/:id/iterations ...
│   │       ├── defects.py         # GET/POST/PUT/DELETE /defects ...
│   │       ├── agents.py          # POST /agents/analyze ...
│   │       ├── fix_tasks.py       # POST /defects/:id/fix-tasks ...
│   │       ├── workflow.py        # PUT /defects/:id/transition ...
│   │       ├── issue_pool.py      # /projects/:id/issue-clusters ...
│   │       ├── integrations.py    # /projects/:id/integrations ...
│   │       ├── rbac_audit.py      # /rbac/*, /audit-logs ...
│   │       ├── notifications.py   # /notifications, /notification-preferences ...
│   │       ├── agent_memory.py    # /projects/:id/memories ...
│   │       ├── mcp_servers.py     # /projects/:id/mcp-servers ...
│   │       ├── skills.py          # /projects/:id/skills ...
│   │       ├── retriever.py       # /projects/:id/retriever-plugins ...
│   │       ├── reports.py         # /reports/* ...
│   │       ├── token_usage.py     # /projects/:id/token-usage ...
│   │       ├── collaborations.py  # /collaborations ...
│   │       ├── credentials.py     # /credentials, /admin/platform-credentials ...
│   │       └── sse.py             # GET /sse (SSE端点)
│   │
│   ├── models/                    # ── SQLAlchemy ORM 模型 ──
│   │   ├── __init__.py
│   │   ├── base.py                # DeclarativeBase + TimestampMixin
│   │   ├── user.py
│   │   ├── project.py
│   │   ├── defect.py
│   │   ├── fix_task.py
│   │   ├── analysis_report.py
│   │   ├── signal.py              # IssueCluster + IssueSignal
│   │   ├── workflow.py
│   │   ├── notification.py
│   │   ├── agent_memory.py
│   │   ├── credential.py
│   │   ├── audit.py
│   │   └── ...
│   │
│   ├── schemas/                   # ── Pydantic DTO ──
│   │   ├── __init__.py
│   │   ├── common.py              # ApiResult[T], PaginatedResponse[T]
│   │   ├── auth.py                # LoginRequest, LoginResponse, UserProfile
│   │   ├── defect.py              # DefectCreate, DefectUpdate, DefectDetail
│   │   ├── project.py             # ProjectCreate, ProjectDetail
│   │   ├── analysis.py            # AnalysisReport, StreamEvent
│   │   ├── fix_task.py            # FixTaskCreate, FixTaskDetail
│   │   ├── signal.py              # IssueClusterDetail, SignalPayload
│   │   └── ...
│   │
│   ├── services/                  # ── 业务逻辑层 ──
│   │   ├── __init__.py
│   │   ├── defect_service.py
│   │   ├── workflow_service.py    # 状态机（DefectStatus + _TRANSITIONS）
│   │   ├── signal_ingest.py       # 信号接入 + SHA256指纹 + 归一化
│   │   ├── signal_triage.py       # 问题簇管理 + 路由匹配
│   │   ├── fix_engine.py          # 8步修复流水线
│   │   ├── fix_analysis_scope.py  # 分析报告仓库范围限定
│   │   ├── defect_draft.py        # AI缺陷草稿生成
│   │   ├── recommendation.py      # 负责人/Agent推荐
│   │   ├── defect_repo_resolver.py # 仓库解析
│   │   ├── project_routing.py     # 项目路由规则
│   │   ├── regression.py          # 回归预防
│   │   ├── quality_insights.py    # 质量洞察
│   │   ├── rbac_service.py        # 权限管理 + Redis缓存
│   │   ├── notification_service.py # 站内/邮件/Webhook通知
│   │   ├── agent_memory_service.py # Agent记忆提取/去重/注入
│   │   ├── ai_runtime.py          # AI配置管理 + Token计费
│   │   ├── credential_service.py  # AES-GCM加密凭证
│   │   ├── repo_auth.py           # 仓库认证解析
│   │   ├── report_service.py      # 仪表盘 + 导出
│   │   └── audit_service.py       # 缓冲批量审计写入
│   │
│   ├── agent/                     # ── LangGraph Agent 框架 ──
│   │   ├── __init__.py
│   │   ├── state.py               # AnalysisState TypedDict 定义
│   │   ├── graph.py               # StateGraph 构建与编译
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── planner.py         # Planner Node（输出探索计划）
│   │   │   ├── executor.py        # Executor Node（按计划调用工具）
│   │   │   ├── analyzer.py        # Analyzer Node（LLM分析）
│   │   │   ├── post_process.py    # 后处理（JSON提取/字段归一化）
│   │   │   └── memory.py          # 记忆提取 Node
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── code_search.py     # @mcp.tool() search_code
│   │   │   ├── file_read.py       # @mcp.tool() read_file
│   │   │   ├── list_directory.py  # @mcp.tool() list_directory
│   │   │   ├── trace_call.py      # @mcp.tool() trace_call
│   │   │   ├── find_handler.py    # @mcp.tool() find_api_handler
│   │   │   └── git_ops.py         # Git克隆/分支操作工具
│   │   ├── prompts/
│   │   │   ├── __init__.py
│   │   │   ├── analysis.py        # 前端/后端/UI/客户端/测试分析模板
│   │   │   ├── fix.py             # 修复生成模板
│   │   │   └── memory.py          # 记忆提取模板
│   │   └── callbacks/
│   │       ├── __init__.py
│   │       ├── token_tracker.py   # Token用量记录回调
│   │       └── checkpointer.py    # LangGraph checkpointer（会话持久化）
│   │
│   ├── retrieval/                 # ── 检索模块 ──
│   │   ├── __init__.py
│   │   ├── base.py                # Retriever Protocol
│   │   ├── keyword.py             # 关键词检索器
│   │   ├── repo_wiki.py           # RepoWiki HTTP检索器
│   │   └── rag.py                 # LightRAG向量检索（预留）
│   │
│   ├── infrastructure/            # ── 基础设施 ──
│   │   ├── __init__.py
│   │   ├── database.py            # async engine + session factory
│   │   ├── redis.py               # Redis client (async)
│   │   ├── security.py            # JWT + bcrypt + AES-GCM
│   │   ├── sse.py                 # SSE Broker (sse-starlette + Redis Pub/Sub)
│   │   └── celery_app.py          # Celery app 配置
│   │
│   └── middleware/                # ── FastAPI 中间件 ──
│       ├── __init__.py
│       ├── auth_middleware.py      # JWT 验证 Depends
│       ├── rbac_middleware.py      # 权限校验 Depends
│       ├── audit_middleware.py     # 审计日志中间件
│       └── rate_limit.py          # 限流中间件
│
├── alembic/                       # 数据库迁移
│   ├── alembic.ini
│   ├── env.py
│   └── versions/                  # 迁移脚本
│
├── tasks/                         # Celery 任务定义
│   ├── __init__.py
│   ├── analysis.py                # 分析任务
│   └── fix.py                     # 修复任务
│
└── tests/
    ├── conftest.py                # fixtures (async client, test DB)
    ├── test_api/                  # API 集成测试
    │   ├── test_auth.py
    │   ├── test_defects.py
    │   ├── test_projects.py
    │   └── ...
    ├── test_services/             # Service 单元测试
    │   ├── test_workflow.py       # 状态机测试（覆盖所有合法/非法转移）
    │   └── test_signal_ingest.py  # 指纹生成测试
    └── test_agent/                # Agent 集成测试
        └── test_analysis_graph.py
```

---

## 十二、Agent 架构设计（Python 原生方案）

### 12.1 核心设计思路

**不用 LangGraph 自己写编排**，LangGraph 的 `StateGraph` 天生就是 Agent 编排工具：

```
Go版 ADK 框架                      Python版 LangGraph 替代
────────────                      ──────────────────────
analysis_service.go (3258行)      → app/agent/graph.py (~150行)
planner_agent.go                  → app/agent/nodes/planner.py (~80行)
tool_registry.go                  → MCP Python SDK (@mcp.tool() 装饰器)
scheduler.go                      → Celery tasks/analysis.py
model_adapter.go (739行)          → PydanticAI (10行 LLM 调用)
stream_adapter.go                 → LangGraph stream_events() 原生支持
rollout_recorder.go               → LangGraph SqliteSaver/PostgresSaver
memory_callbacks.go               → app/agent/callbacks/checkpointer.py
```

**代码量预估减少 80%**：Go版 ADK 目录 ~6000行 → Python版 ~1200行。

### 12.2 Agent 状态定义

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class AnalysisState(TypedDict):
    # 输入
    defect_id: int
    agent_type: str
    ai_config: dict  # {provider, model, api_key, api_endpoint}

    # 探索阶段
    plan_steps: list[dict]  # [{goal, tool, args}, ...]
    evidence: list[dict]    # [{file_path, snippet, line}, ...]
    file_list: list[str]    # 探索阶段发现的相关文件

    # 分析阶段
    messages: Annotated[list[BaseMessage], add_messages]
    analysis_json: dict | None  # LLM输出的结构化JSON
    analysis_report_id: int | None

    # 元数据
    token_usage: dict  # {prompt_tokens, completion_tokens}
    error: str | None
```

### 12.3 Agent 图结构

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

def build_analysis_graph() -> StateGraph:
    workflow = StateGraph(AnalysisState)

    # 添加节点
    workflow.add_node("planner", planner_node)       # 生成探索计划
    workflow.add_node("executor", executor_node)     # 按计划调用工具
    workflow.add_node("analyzer", analyzer_node)     # LLM分析
    workflow.add_node("post_process", post_process_node)  # JSON归一化

    # 设置边
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "executor")
    workflow.add_edge("executor", "analyzer")
    workflow.add_edge("analyzer", "post_process")

    # 条件路由：分析失败时重试（最多3次）
    workflow.add_conditional_edges(
        "post_process",
        should_retry,
        {"retry": "analyzer", "done": END},
    )

    # 编译
    checkpointer = PostgresSaver.from_conn_string(DATABASE_URL)
    return workflow.compile(checkpointer=checkpointer)
```

### 12.4 Planner Node

```python
PLANNER_PROMPT = """\
你是代码分析计划生成器。根据缺陷信息，制定代码探索计划。

输出格式：
{
  "steps": [
    {"goal": "目标描述", "tool": "search_code", "args": {"query": "..."}},
    {"goal": "目标描述", "tool": "read_file", "args": {"file_path": "..."}}
  ]
}

规则：
- 最多5步
- 仅允许工具：search_code, read_file, find_api_handler, list_directory
- 每步的args必须完整可执行
"""

async def planner_node(state: AnalysisState) -> AnalysisState:
    defect = await defect_service.get_defect(state["defect_id"])
    prompt = PLANNER_PROMPT + f"\n缺陷：{defect.title}\n{defect.description}"

    response = await llm_client.chat(prompt, response_format="json")
    plan = json.loads(response)
    state["plan_steps"] = plan["steps"][:5]
    return state
```

### 12.5 Executor Node

```python
from app.agent.tools import safe_execute_tool

SAFE_TOOLS = {"search_code", "read_file", "find_api_handler", "list_directory"}

async def executor_node(state: AnalysisState) -> AnalysisState:
    evidence = []
    files = []

    for step in state["plan_steps"]:
        tool_name = step.get("tool")
        if tool_name not in SAFE_TOOLS:
            raise ValueError(f"不允许的工具: {tool_name}")

        result = await safe_execute_tool(tool_name, step.get("args", {}))
        evidence.append({"goal": step["goal"], "tool": tool_name, "result": result})

        # 收集发现的文件路径
        if result.get("file_path"):
            files.append(result["file_path"])

    state["evidence"] = evidence
    state["file_list"] = list(set(files))
    return state
```

### 12.6 Analyzer Node

```python
async def analyzer_node(state: AnalysisState) -> AnalysisState:
    evidence_text = format_evidence(state["evidence"])
    defect = await defect_service.get_defect(state["defect_id"])

    prompt = build_analysis_prompt(
        agent_type=state["agent_type"],
        defect=defect,
        evidence=evidence_text,
        memories=await memory_service.get_context(defect.project_id, defect.iteration_id),
    )

    response = await llm_client.chat(prompt, response_format="json")
    state["messages"].append(response.message)
    state["analysis_json"] = extract_json(response.content)
    state["token_usage"] = response.usage
    return state
```

### 12.7 Agent 调度（Celery）

```python
# tasks/analysis.py
from celery import shared_task

@shared_task(bind=True, max_retries=0)
def run_analysis(self, defect_id: int, agent_type: str, user_id: int):
    """Celery 任务：执行单个Agent分析"""
    loop = asyncio.new_event_loop()
    try:
        # 构建 LangGraph 并流式执行
        graph = build_analysis_graph()
        config = {"configurable": {"thread_id": f"defect-{defect_id}-{agent_type}"}}

        for event in graph.stream(
            {"defect_id": defect_id, "agent_type": agent_type},
            config,
            stream_mode="values",
        ):
            # 推送 SSE 事件
            publish_sse_event(f"defect:{defect_id}", event)

        # 保存分析报告
        loop.run_until_complete(save_analysis_report(defect_id, agent_type, event))
    finally:
        loop.close()
```

### 12.8 并发控制

```python
# tasks/analysis.py
from celery import chord, group

def trigger_multi_agent_analysis(defect_id: int, agent_types: list[str], user_id: int):
    """触发多Agent分析，按优先级调度"""
    tasks = [
        run_analysis.signature(
            args=(defect_id, agent_type, user_id),
            priority={"user": 0, "auto": 1, "background": 2}.get("user", 0),
        )
        for agent_type in agent_types
    ]
    # 使用 Celery group 并行执行，max_concurrency 控制并发
    group(tasks).apply_async()
```

---

## 十三、非功能性需求

### 13.1 性能需求

| 指标 | 要求 |
|------|------|
| 页面加载时间 | < 2秒 |
| API响应时间（非AI） | < 500ms |
| Agent分析时间 | < 60秒（典型场景） |
| 流式分析首帧时间 | < 3秒 |
| 支持并发用户数 | > 1000 |
| 并发分析数 | 可配置（默认3，通过 Celery worker concurrency 控制） |

### 13.2 安全需求

- 用户认证：JWT Token（HS256签名）
- 权限控制：RBAC 双层次（平台 + 项目），Redis 缓存
- 数据加密：AES-256-GCM 加密存储（`cryptography` 库）
- 密钥脱敏：API 返回时仅显示前4位和后4位
- 仓库隔离：`tempfile.mkdtemp(prefix=f"defect-{defect_id}-")`
- Webhook签名：`X-Hub-Signature-256` 校验

### 13.3 可靠性需求

- AI 失败不阻断缺陷主流程
- 通知失败不阻断主流程
- 外部系统不可用时保留手动路径
- Celery 任务失败自动重试（可配置次数）
- SSE 推送失败不影响主流程状态写入

### 13.4 可观测性

- FastAPI 自动生成 OpenAPI 文档（`/docs`）
- AI 调用有 Token 和耗时记录（`ai_token_usage` 表）
- 状态流转有历史记录（`status_changes` 表）
- Celery 任务状态可通过 Flower 监控
- 结构化日志（`structlog`）

---

## 十四、分阶段开发计划

### 概览

| 阶段 | 内容 | 工期 | 产出 |
|------|------|------|------|
| 第零阶段 | 契约冻结 + 基础设施 | 1.5周 | API矩阵、Schema diff、服务骨架、测试基线 |
| 第一阶段 | 账号、项目、迭代、仓库 | 2周 | 前端基础导航和项目域可用 |
| 第二阶段 | 缺陷、状态机、附件、评论、权限 | 3周 | 缺陷主流程可用 |
| 第三阶段 | Agent 分析 + SSE + Token + 记忆 | 2.5周 | 分析闭环可用 |
| 第四阶段 | 修复任务 + Git/PR 生命周期 | 2.5周 | 自动/人工修复闭环可用 |
| 第五阶段 | 信号接入 + 检索 + 洞察 | 2周 | 问题池、检索器、质量洞察可用 |
| 第六阶段 | 双跑验证 + 加固上线 | 1.5周 | 前端零改动、Docker部署、回滚方案 |

**总计：约 15 周（~3.5个月）**

### 第零阶段：契约冻结 + 基础设施（1.5周）

**目标**：服务可启动，数据库可连接，核心兼容性基线可自动验证

**任务清单**：
- [ ] 从 Go 路由、前端 API、E2E 用例生成 API 契约矩阵
- [ ] 建立 OpenAPI / JSON response / SSE golden event 快照测试
- [ ] 建立 Go schema 与 SQLAlchemy metadata diff 脚本
- [ ] `pyproject.toml` 依赖声明
- [ ] `app/main.py` FastAPI 应用工厂
- [ ] `app/config.py` Pydantic Settings 配置
- [ ] `app/infrastructure/database.py` SQLAlchemy async engine
- [ ] `app/infrastructure/redis.py` Redis 客户端
- [ ] `app/infrastructure/security.py` JWT + bcrypt + AES
- [ ] `app/models/base.py` + 全部 30+ 个 ORM Model 定义
- [ ] `app/schemas/` 全部 Pydantic Schema 定义（与前端契约对齐）
- [ ] `app/api/v1/router.py` 路由注册骨架
- [ ] `alembic/` 初始化 + 自动生成首次迁移
- [ ] `docker-compose.yml` PostgreSQL + Redis + App
- [ ] `tests/conftest.py` 测试基础设施

**验收标准**：
- `uvicorn app.main:app` 可启动
- `/docs` 页面可见已冻结 API 端点
- `alembic upgrade head` 可创建全部表
- 契约矩阵、schema diff、golden fixture 已进入 CI

### 第一阶段：账号、项目、迭代、仓库（2周）

**目标**：前端登录、用户中心、项目切换、项目配置、仓库和迭代管理可用

**任务清单**：
- [ ] 注册/登录/登出/个人信息
- [ ] 项目 CRUD / 成员管理 / 迭代管理 / 仓库管理
- [ ] AI 配置 CRUD / AI 厂商和模型目录
- [ ] 平台凭证和仓库凭证的最小可用接口
- [ ] 用户、项目、迭代、仓库相关权限校验

**验收标准**：
- 前端无需修改即可完成登录、项目创建、成员维护、迭代创建、仓库绑定
- 相关 API 通过契约快照测试
- Go 版历史项目数据可只读展示

### 第二阶段：缺陷、状态机、附件、评论、权限（3周）

**目标**：缺陷主流程完整可用，状态和权限行为与 Go 版一致

**任务清单**：
- [ ] 缺陷 CRUD / 列表筛选 / 表单创建 + 对话草稿创建
- [ ] 附件上传下载（JWT认证）
- [ ] 状态机（DefectStatus + WorkflowService）
- [ ] 状态流转 API / 批量流转
- [ ] 缺陷分配 + AI 推荐
- [ ] RBAC 权限模型（平台角色 + 项目角色）
- [ ] 权限校验 Depends（全局 / 项目 / 缺陷三级）
- [ ] 站内通知 / 未读计数 / 标记已读
- [ ] 项目通知策略 / 个人偏好
- [ ] 邮件 + Webhook 通知
- [ ] 评论 CRUD
- [ ] 审计日志
- [ ] 凭证管理（个人+平台，AES加密）

**验收标准**：
- 状态机全部 24 条转移规则通过测试
- 缺陷创建、分配、流转、附件、评论、通知前端流程可用
- 非法状态流转、无权限访问、并发流转均有确定响应

### 第三阶段：Agent 分析 + SSE + Token + 记忆（2.5周）

**目标**：LangGraph 驱动的 AI 分析能力，支持流式输出和记忆注入

**周 4 — Agent 核心**
- [ ] `app/agent/state.py` 状态定义
- [ ] `app/agent/graph.py` StateGraph 构建
- [ ] Planner Node + Executor Node + Analyzer Node
- [ ] 5 个 MCP 工具定义（search_code/read_file/list_directory/trace_call/find_api_handler）
- [ ] LLM 客户端封装（支持 OpenAI/Anthropic/DeepSeek/智谱/DashScope）
- [ ] 多配置 fallback 机制

**周 5 — 流式 + 记忆 + 调度**
- [ ] 流式分析 API（StreamingResponse + LangGraph stream_events）
- [ ] 降级到 Celery 轮询模式
- [ ] Agent 记忆注入（BeforeModel 回调）
- [ ] Agent 记忆提取（AfterModel 回调）
- [ ] Celery 分析任务调度（优先级 + 并发控制）
- [ ] 分析取消 API / 队列状态 API
- [ ] Token 用量记录

**验收标准**：
- AI 分析成功生成报告（含 rootCause + affectedFiles + solution.steps）
- 流式分析实时显示思考步骤
- 分析失败不阻断缺陷流转
- 记忆注入/提取正常工作
- SSE 事件格式与前端现有消费逻辑兼容

### 第四阶段：修复任务 + Git/PR 生命周期（2.5周）

**目标**：完整的 AI/人工修复闭环 + PR 生命周期管理

**周 6 — 修复引擎**
- [ ] 8 步修复流水线（克隆→分支→生成→应用→提交→构建→推送→PR）
- [ ] AI 代码生成（结构化 hunks + oldContent 精确匹配）
- [ ] 代码语法验证（Python `ast.parse`）
- [ ] 最多 3 次重试机制
- [ ] 无变更检测（no_changes）
- [ ] 仓库隔离（按缺陷 ID 隔离临时目录）

**周 7 — PR 生命周期**
- [ ] 人工修复路径（开始/提交/放弃）
- [ ] FixTask + FixTaskGroup 模型和 CRUD
- [ ] PR 状态跟踪（open/merged/closed/rejected）
- [ ] VCS Webhook 接收（GitHub/GitLab）
- [ ] PR 拒绝回退 + 拒绝记录
- [ ] PR 合并自动推进
- [ ] 个人/平台凭证管理
- [ ] 仓库认证解析（绑定→默认→个人优先级）

**验收标准**：
- AI 修复生成的代码语法合法
- PR 拒绝后缺陷自动回退到 pending_fix
- 人工修复路径完整可用
- Git 操作在隔离临时目录执行，失败可重试且不会污染仓库

### 第五阶段：信号接入 + 检索 + 洞察（2周）

**目标**：外部信号接入、知识检索、质量洞察

**周 8 — 信号接入**
- [ ] 连接器管理 CRUD（Bugly/阿里云/钉钉/飞书/Webhook）
- [ ] 外部信号接入端点
- [ ] 字段归一化（NormalizePayload）
- [ ] SHA256 指纹生成 + 聚类去重
- [ ] 问题簇管理（分配/忽略/合并/转换）
- [ ] 路由规则（五维匹配引擎）
- [ ] 批量操作（分配/忽略/转换）

**周 9 — 检索 + 洞察**
- [ ] 关键词检索器（文件路径匹配 + 内容搜索）
- [ ] RepoWiki 检索器（HTTP 调用外部服务）
- [ ] 质量洞察概览（问题池/回归/版本/AI统计）
- [ ] 回归预防（问题簇→回归检测项）
- [ ] LightRAG 集成（向量检索，如需要）
- [ ] 报表 API（仪表盘、趋势、分布、导出）

**验收标准**：
- 外部信号可接入并正确聚类
- 问题簇可转为正式缺陷
- 检索器在分析流程中可用

### 第六阶段：双跑验证 + 加固上线（1.5周）

**目标**：生产就绪，可灰度切换，可快速回滚

**任务清单**：
- [ ] 性能优化（数据库索引、Redis 缓存、连接池调优）
- [ ] 安全审计（凭证加密、密钥脱敏、Webhook 签名）
- [ ] Celery Flower 监控部署
- [ ] Docker 多阶段构建 + docker-compose 生产配置
- [ ] 前端联调（确认全部 API 契约兼容）
- [ ] 全流程 E2E 测试（创建→分配→分析→修复→验证→完成）
- [ ] Go/Python 双跑验证：同一 fixture 下响应、事件、状态副作用一致
- [ ] 灰度切流和回滚方案
- [ ] 文档（README、部署文档、API 文档）

**验收标准**：
- 全部核心流程可走通
- 前端零改动可正常使用
- Docker 一键部署
- 切回 Go 版不需要数据库回滚

---

## 十五、附录

### 附录 A：API 契约兼容性检查清单

以下是从 Go 版导出的 API 契约关键约定，Python 版必须逐项验证：

| # | 契约项 | 预期值 | 验收方法 |
|---|--------|--------|---------|
| 1 | 响应格式 | `{"code": 0, "data": {...}, "message": "..."}` | JSON 快照 |
| 2 | 成功 code | `0` | API 集成测试 |
| 3 | 分页格式 | `{"list": [...], "total": N, "page": N, "size": N}` | 列表接口 golden case |
| 4 | 认证头 | `Authorization: Bearer <token>` | 登录后访问受保护接口 |
| 5 | 401 处理 | HTTP 401 + `code: 401` + `message: "登录已过期"` | 过期 token 测试 |
| 6 | 403 处理 | HTTP 403 + `code: 403` + 稳定 message | RBAC 矩阵测试 |
| 7 | 字段大小写 | camelCase：`agentTypes`, `createdAt`, `defectId`, `iterationId` | Pydantic 序列化测试 |
| 8 | 空值处理 | `null`（不是删除字段），数组空值 `[]` | 响应字段快照 |
| 9 | 逗号字段 | `"frontend,backend"` → 前端解析为 `["frontend", "backend"]` | 用户 Agent 身份测试 |
| 10 | SSE 事件格式 | `event: defect:status_changed\ndata: {"defectId": ...}\n\n` | SSE golden event |
| 11 | 文件下载 | `GET /api/v1/uploads/*filename` + JWT 认证 | 附件下载 E2E |
| 12 | 状态副作用 | 写入 `status_changes`，必要时发送通知和 SSE | 状态流转集成测试 |
| 13 | 审计副作用 | 写接口产生审计日志，失败不阻断主流程 | 审计测试 |
| 14 | 时间字段 | ISO/RFC3339 可被前端解析，字段名保持 camelCase | 前端 E2E |

### 附录 B：从 Go 版继承的设计精华

| Go 版设计 | Python 版继承方式 |
|-----------|------------------|
| 13 状态 × 24 转移规则的状态机矩阵 | `WorkflowService._TRANSITIONS` dict |
| SHA256 指纹去重算法 | `hashlib.sha256()` 相同实现 |
| 8 步修复流水线 | `FixService._execute_workflow()` async 方法 |
| AES-256-GCM 凭证加密 | `cryptography.hazmat.primitives.ciphers.aead.AESGCM` |
| 多 AI 配置 fallback 机制 | `for cfg in configs: try...except...` 循环 |
| SSE room→subscriber 发布订阅 | Redis Pub/Sub channel 模式 |
| oldContent 精确匹配一次 | `text.count(old_content) != 1` 校验 |

### 附录 C：术语表

| 术语 | 说明 |
|------|------|
| Agent | 内置的AI智能体，具备特定领域的分析和修复能力 |
| LangGraph | Python Agent 编排框架，用 StateGraph 定义 Agent 工作流 |
| MCP | Model Context Protocol，模型上下文协议，扩展 AI 能力 |
| Celery | Python 分布式任务队列，替代 Go 版自研 AgentScheduler |
| Pydantic | Python 数据校验库，替代 Go 版 struct tag 序列化 |
| Alembic | SQLAlchemy 数据库迁移工具，替代 Go 版手动 SQL 迁移 |
| StateGraph | LangGraph 核心概念，有向图定义 Agent 节点和边 |
| Checkpointer | LangGraph 会话持久化组件，替代 Go 版 RolloutRecorder |
| SSE | Server-Sent Events，服务端到客户端的单向实时推送协议 |

### 附录 D：参考文档

- [PRD_缺陷管理平台.md](file:///Users/admin/Testproject/bug_agent/docs/PRD_缺陷管理平台.md) — Go 版 PRD v5.8
- [CODE_WIKI.md](file:///Users/admin/Testproject/bug_agent/docs/CODE_WIKI.md) — Go 版 Code Wiki
- [BugAgent_流程图.html](file:///Users/admin/Testproject/bug_agent/docs/BugAgent_流程图.html) — 业务流程图
- [PRD-v5.6-agent-architecture-redesign.md](file:///Users/admin/Testproject/bug_agent/docs/PRD-v5.6-agent-architecture-redesign.md) — Agent 架构重设计
- [PRD-COMPLETE.md](file:///Users/admin/Testproject/bug_agent/docs/PRD-COMPLETE.md) — 上线版 PRD
- [DESIGN-python-compatibility-migration.md](file:///Users/admin/Testproject/bug_agent/docs/DESIGN-python-compatibility-migration.md) — Python 重构兼容性详细设计
- [DEV_PLAN-python-migration.md](file:///Users/admin/Testproject/bug_agent/docs/DEV_PLAN-python-migration.md) — Python 重构开发计划与执行流程

---

**文档变更记录**

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|---------|------|
| v1.0-python | 2026-06-06 | Python重构版初稿：基于 Go 版 PRD v5.8 重新设计，保持业务逻辑和数据模型不变，替换技术栈为 Python 生态，新增 LangGraph Agent 架构、Celery 任务调度、项目结构设计、分阶段开发计划 | WorkBuddy |
| v1.1-python | 2026-06-20 | 补充兼容性迁移原则、数据库兼容要求、API契约冻结、兼容性测试基线，并将开发阶段调整为按可验收兼容边界推进 | Codex |
