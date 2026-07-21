# Python 重构开发计划与执行流程

> 版本: v1.0  
> 日期: 2026-06-20  
> 状态: 评审稿  
> 关联文档:
> - `docs/PRD_缺陷管理平台_python.md`
> - `docs/DESIGN-python-compatibility-migration.md`
> - `docs/CODE_WIKI.md`

---

## 1. 目标

在不修改前端业务代码、不破坏 Go 版历史数据库、不改变用户可见行为的前提下，将 BugAgent 后端从 Go 迁移为 Python 实现。

### 1.1 任务目标

任务目标: 完成 Python 后端重构并达到可灰度上线状态。

成功标准:

- API 契约与 Go 版兼容，前端零改动通过核心 E2E。
- Python ORM 可读取 Go 版 PostgreSQL 历史数据。
- 缺陷主流程、Agent 分析、修复链路、信号接入核心路径可用。
- Go/Python 双跑验证通过，具备切流和回滚方案。

交付物:

- Python 后端实现: `bug_agent_py/`
- 契约矩阵和测试基线: `docs/`、`bug_agent_py/tests/`
- 部署配置: Dockerfile、docker-compose、环境变量说明
- 上线和回滚说明

验证方法:

- 单元测试、API 集成测试、契约快照、前端 E2E、Go/Python 双跑测试。

---

## 2. 执行原则

1. 先契约，后实现。
2. 先主流程，后增强能力。
3. 每个阶段必须有可运行服务和可执行验收。
4. 所有写接口必须明确事务、副作用和权限。
5. 不做无关重构，不顺手调整前端交互。
6. 不引入 Go 版无法回滚的破坏性数据库变更。

---

## 3. 阶段计划

### 第零阶段: 契约冻结 + 基础设施

工期: 1.5 周

目标: 建立后续开发的兼容性地基。

任务:

- 生成 API 契约矩阵。
- 建立 schema diff 脚本。
- 建立 OpenAPI、JSON response、SSE golden event 快照测试。
- 完成 FastAPI app、配置、DB、Redis、JWT、AES、基础测试。
- 完成 SQLAlchemy 模型 baseline。
- 完成 Alembic baseline 策略评审。

交付物:

- `docs/API_CONTRACT-python-migration.md`
- `bug_agent_py/app/main.py`
- `bug_agent_py/app/config.py`
- `bug_agent_py/app/infrastructure/*`
- `bug_agent_py/app/models/*`
- `bug_agent_py/tests/test_smoke.py`

验收:

- `uvicorn app.main:app` 可启动。
- `/healthz`、`/readyz`、`/docs` 可访问。
- schema diff 无阻断差异。
- 契约矩阵覆盖前端已使用 API。

### 第一阶段: 账号、项目、迭代、仓库

工期: 2 周

目标: 前端登录和项目域可用。

任务:

- 实现 auth、users、profile。
- 实现 projects、members、iterations、repos。
- 实现 AI config 和 AI catalog 的基础 CRUD。
- 实现平台/项目基础权限。
- 实现统一错误响应和审计骨架。

验收:

- 前端可登录、查看个人信息、创建项目、维护成员、创建迭代、绑定仓库。
- 相关 API 通过契约快照。
- Go 版历史项目数据可只读展示。

### 第二阶段: 缺陷主流程

工期: 3 周

目标: 缺陷创建、分配、状态流转、附件、评论、通知可用。

任务:

- 实现 defects CRUD、列表筛选、详情。
- 实现附件上传下载。
- 实现 comments。
- 实现 WorkflowService 状态机。
- 实现状态历史、通知、SSE、审计副作用。
- 实现 RBAC 完整矩阵。
- 实现缺陷推荐的最小可用版本。

验收:

- 24 条合法状态流转全部通过。
- 非法流转返回 409。
- 无权限访问返回 403。
- 前端缺陷列表、详情、创建、分配、附件、评论流程可用。

### 第三阶段: Agent 分析

工期: 2.5 周

目标: LangGraph 分析闭环可用。

任务:

- 实现 LangGraph state、graph、planner、executor、analyzer、post_process。
- 实现 LLM client factory，支持 OpenAI、Anthropic、DeepSeek、智谱、DashScope。
- 实现安全工具: search_code、read_file、list_directory、trace_call、find_api_handler。
- 实现 Celery analysis task。
- 实现 SSE 流式事件和降级轮询。
- 实现 analysis_reports、analysis_tasks、ai_token_usage。
- 实现 Agent memory 注入和提取。

验收:

- 固定 fixture 可生成稳定结构分析报告。
- 分析过程前端可实时展示。
- 取消任务、失败任务、Token 统计可用。
- Agent 输出 schema 通过 golden test。

### 第四阶段: 修复任务和 PR 生命周期

工期: 2.5 周

目标: 自动修复和人工修复闭环可用。

任务:

- 实现 FixTaskGroup 和 FixTask。
- 实现 8 步修复流水线。
- 实现 GitPython 仓库克隆、分支、提交、推送。
- 实现结构化补丁生成、精确匹配应用、重试。
- 实现按语言的验证策略。
- 实现 PR 创建、状态同步、Webhook 签名校验。
- 实现 PR rejected 回退和人工修复路径。

验收:

- 自动修复可在测试仓库创建分支和 PR。
- PR rejected 后缺陷回到 `pending_fix`。
- 人工修复开始、提交、放弃流程可用。
- Git 临时目录隔离和清理通过测试。

### 第五阶段: 信号接入、检索、质量洞察

工期: 2 周

目标: 外部信号和质量分析能力可用。

任务:

- 实现 integration connectors。
- 实现 inbound signal endpoint。
- 实现 NormalizePayload、SHA256 指纹、聚类去重。
- 实现 issue clusters 管理、合并、忽略、转换。
- 实现路由规则五维匹配。
- 实现关键词检索器和 RepoWiki 检索器。
- 实现质量洞察和报表 API。
- LightRAG/Qdrant 仅在必要时接入。

验收:

- 外部信号可接入并聚类。
- 问题簇可转为正式缺陷。
- 检索器可被 Agent 分析流程调用。
- 前端问题池和质量洞察页面可用。

### 第六阶段: 双跑验证、加固、上线

工期: 1.5 周

目标: 达到灰度上线标准。

任务:

- Go/Python 双跑验证。
- 前端完整 E2E。
- 性能压测和慢查询处理。
- 安全审计。
- Docker 多阶段构建。
- 生产环境变量和密钥检查。
- 切流和回滚演练。
- README、部署文档、运维手册。

验收:

- 核心流程 E2E 通过。
- 双跑关键接口响应兼容。
- 生产配置无默认弱密钥。
- 切回 Go 版不需要数据库回滚。

---

## 4. 标准开发流程

每个功能按以下流程执行：

1. 阅读 Go 版 handler/service/model 和前端调用点。
2. 在契约矩阵中补齐路径、请求、响应、权限、副作用。
3. 编写或更新契约测试和最小 fixture。
4. 实现 Pydantic schema。
5. 实现 SQLAlchemy 查询或模型补齐。
6. 实现 service，明确事务边界。
7. 实现 FastAPI router。
8. 补单元测试和 API 集成测试。
9. 运行前端相关 E2E。
10. 更新文档和变更记录。

---

## 5. 测试门禁

### 5.1 提交级门禁

每次提交至少通过：

- `ruff check`
- `mypy` 或阶段内允许的类型检查子集
- Python 单元测试
- 当前模块 API 集成测试

### 5.2 阶段级门禁

每阶段完成必须通过：

- 契约快照测试
- schema diff
- 当前阶段前端 E2E
- 关键状态副作用测试
- 安全检查清单

### 5.3 上线级门禁

上线前必须通过：

- 全量 Python 测试
- 全量前端 E2E
- Go/Python 双跑测试
- 性能基线测试
- 凭证脱敏和密钥检查
- 回滚演练

---

## 6. 任务拆分模板

每个开发任务必须用以下格式定义：

```text
任务目标:

成功标准:
  - 

影响范围:
  - API:
  - DB:
  - Service:
  - Frontend:

实现步骤:
  1. 

测试验证:
  - 

回滚策略:
  - 
```

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| API 细节遗漏 | 前端联调返工 | 契约矩阵 + 快照测试先行 |
| Schema 不兼容 | 历史数据无法读取 | baseline + schema diff + 脱敏备份验证 |
| Agent 行为不稳定 | 分析结果不可用 | golden fixture + 输出 schema 强校验 |
| Celery/SSE 事件丢失 | 前端状态不同步 | 状态以数据库为准，SSE 可重连补偿 |
| Git 修复污染仓库 | 数据损坏或安全事故 | 临时目录隔离 + 凭证权限最小化 |
| 阶段目标过大 | 进度失控 | 每阶段必须可运行、可验收、可回滚 |

---

## 8. 里程碑

| 里程碑 | 完成标志 |
|--------|----------|
| M0 | 契约矩阵、schema diff、服务骨架完成 |
| M1 | 登录、项目、迭代、仓库前端流程可用 |
| M2 | 缺陷主流程可用 |
| M3 | Agent 分析闭环可用 |
| M4 | 自动/人工修复闭环可用 |
| M5 | 信号接入、检索、洞察可用 |
| M6 | 双跑通过并具备灰度上线条件 |

---

## 9. 评审点

每个阶段结束必须评审：

1. 本阶段是否达成成功标准。
2. 是否引入未评审 API 或 DB 变更。
3. 是否存在前端兼容问题。
4. 是否存在不可回滚变更。
5. 下一阶段是否需要调整范围。

