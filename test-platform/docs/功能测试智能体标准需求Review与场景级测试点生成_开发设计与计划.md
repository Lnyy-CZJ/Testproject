# 功能测试智能体标准需求 Review 与场景级测试点生成——开发设计与计划

> **执行要求：** 实施本计划时使用 `superpowers:executing-plans`，按 SR01～SR18 逐包执行“失败测试 → 最小实现 → 局部回归 → 阶段回归”，并持续维护工作包状态。  
> **目标：** 将原始需求整理、标准需求人工 Review、场景级测试点生成、确定性覆盖与测试用例事实保真接入现有功能智能体。  
> **架构：** 增量扩展现有 Flask 服务、TaskStore、单槽 FIFO、Runner 和三层文件 Review；不新增服务、队列或业务数据库表。  
> **技术栈：** Python 3.12、Flask 3、Pydantic、LangChain、Jinja、原生 JavaScript/CSS、pytest、Node test、Alembic、Docker Compose、Nginx。  
> **需求文档：** `/Users/admin/Testproject/test-platform/docs/功能测试智能体标准需求Review与场景级测试点生成_PRD.md`

> 文档版本：V1.0  
> 文档状态：待评审  
> 编制日期：2026-08-30  
> 需求基线：《功能测试智能体标准需求 Review 与场景级测试点生成 PRD》V1.0  
> 规则基线：《功能测试智能体需求文档整理规则》V1.2 / FRD-2.0  
> 适用仓库：`functional-test-agent`、`test-platform`  
> 实施原则：增量扩展、文件为事实来源、人工确认优先、场景级生成、确定性覆盖、兼容旧流程

---

## 1. 文档目的

本文档将已评审 PRD 转换为可直接进入开发的技术设计和实施计划，明确：

- 当前代码与目标流程之间的差距；
- 标准需求整理、需求 Review、Requirement 索引、场景级测试点、确定性覆盖和用例事实保真的实现边界；
- HTTP 接口、任务状态、execution 信封、文件事务、权限和错误协议；
- 前后端文件职责与精准修改范围；
- 平台配置迁移、dev 发布和回滚方式；
- SR01～SR18 工作包、阶段质量门槛、自动化与浏览器验收标准。

本文档不授权生产部署、真实生产 Secret 操作、Git 提交或推送。实施时应继续保护当前工作区中所有已跟踪和未跟踪的用户修改。

---

## 2. 需求理解与技术成功标准

### 2.1 目标流程

```text
原始 Markdown/TXT
→ 标准需求检测
→ 非标准文档：单次 LLM 整理为 FRD-2.0
→ 标准文档：零 LLM 快速校验
→ waiting_document_review
→ 人工编辑、显式保存、确认标准需求
→ 确定性 Requirement 索引
→ 重新进入单槽 FIFO
→ 按完整 H3 功能章节生成场景级测试点
→ 程序计算 confirmed Requirement 覆盖率
→ 最多一轮缺口补充
→ waiting_review
→ 人工/AI Review 测试点并确认
→ 重新进入 FIFO
→ 基于确认测试点的锁定骨架生成测试用例
→ waiting_case_review
→ 人工/AI Review 并发布 JSON/XLSX
→ succeeded
```

### 2.2 必须满足的技术结果

1. 新 Web 主流程不再调用 `requirement_decomposition.pipeline.run_decomposition()`。
2. FRD-2.0 合法文档在本任务中的需求整理 LLM 调用次数为零。
3. 非标准文档最多执行一次完整文档整理调用，不按标题逐片调用模型。
4. 未确认需求版本时，任何路径都不能生成测试点。
5. Requirement 索引只由确定性解析器生成，不由模型生成，不写业务数据库。
6. 测试点以完整场景为粒度，允许一条测试点映射多个 Requirement。
7. 正式覆盖率只统计 confirmed Requirement；pending、Q/A/C 和测试建议不计入分母。
8. 测试点缺口最多补充一轮，仍有缺口时交由人工处理。
9. 测试用例生成的锁定字段不得被 LLM 改写。
10. 需求、测试点和测试用例确认版本均不可变，并可查看历史版本。
11. 三次人工确认均重新参与 `queued_at + task_id` FIFO；Review 等待不占执行槽位。
12. 身份、CSRF、RBAC、所有权、CAS、幂等、审计和脱敏边界保持有效。
13. 旧任务、旧 CLI、`decompose_requirement` 独立操作、API 智能体和历史 `output/` 不被改写。

### 2.3 不实施内容

- 不新增 Requirement 业务数据库表；
- 不建设多人协作编辑器、自动保存、WebSocket、SSE 或 SPA；
- 不在服务内解析图片、Figma、PDF、DOCX；
- 不自动裁决未确认项、歧义和冲突；
- 不自动执行真实测试；
- 不物理删除旧需求拆解包；
- 不改变 API 智能体的执行、数据库写入和目标网络安全默认值。

---

## 3. 当前实现审计与基线

### 3.1 功能智能体现状

当前 `functional-test-agent` 已具备：

- Flask/Jinja/原生 JavaScript/CSS 页面；
- `TaskStore` 文件任务存储；
- `TaskManager` 单槽持久化 FIFO；
- `execution.json` sequence 迟到结果隔离；
- 测试点和测试用例 Review、CAS、不可变确认版本；
- 测试点和用例 Review AI；
- 自由脑图、表格、详情、版本和产物预览；
- 平台配置快照、身份头、CSRF、RBAC、所有权和审计；
- Token 分阶段累计；
- 任务独立目录、原子 JSON 写入、Artifact 白名单和保留策略。

主要相关文件：

```text
functional-test-agent/
├── agents/functional_test/
│   ├── case_generator_agent.py
│   ├── prompts/
│   └── workflows/case_generator_workflow.py
├── requirement_decomposition/
├── services/common/
│   ├── task_store.py
│   ├── task_manager.py
│   ├── task_models.py
│   ├── review.py
│   ├── case_review.py
│   ├── versioned_review.py
│   ├── web.py
│   ├── templates/
│   └── static/
├── services/functional_agent/
│   ├── app.py
│   ├── adapter.py
│   ├── runner.py
│   ├── review_ai.py
│   └── case_review_ai.py
└── tests/
```

### 3.2 当前执行模型

`TaskManager` 当前支持 `initial`、`review_ai`、`generate_cases` 和 `case_review_ai`。`submit()` 固定写入 `initial` execution；测试点确认通过 `resume()` 写入 `generate_cases`。

`runner.py` 当前行为：

- `decompose_requirement` 调用旧拆解 pipeline；
- `generate_test_points/full_pipeline` 首次执行调用 `generator_test_points`；
- 测试点确认后调用 `generator_case`；
- Review AI 使用独立 execution kind，但共用同一槽位；
- 运行结果由 `collect_result()` 发布 Artifact 并转换为任务公开状态。

### 3.3 当前生成根因

`GeneratorPointWorkflow` 仍通过 `prepare_requirement_context_from_document_path()` 接入需求拆解结果，并执行模型覆盖判断与补充。这是新流程需要旁路而不是继续加强的路径。

旧路径仍需保留，原因是：

- CLI 和历史脚本可能直接依赖；
- `decompose_requirement` 仍需保留一个发布周期；
- 功能开关关闭时必须立即恢复稳定流程。

### 3.4 当前规则差异

PRD 已固定规则基线为 V1.2 / FRD-2.0；但当前平台仓库中的：

```text
test-platform/docs/功能测试智能体需求文档整理规则.md
```

仍标记为 V1.1，模板也未完整包含 PRD 要求的 FRD-2.0 标识字段。实施第一步必须对齐规则副本、运行时 Prompt 资产和黄金样本，避免快速路径误判。

### 3.5 当前自动化基线

2026-08-30 实测：

- `functional-test-agent` Python：89 passed，3 skipped；
- `functional-test-agent` Node UI：25 passed；
- `test-platform/frontend`：52 passed；
- `docker compose config --quiet`：通过；
- `test-platform/backend`：存在一个与本需求无关、位于用户当前修改中的既有失败：
  `test_create_user_sets_fixed_role_before_contract_insert`。

该既有失败不得通过本任务顺便修改；实施前应再次确认其基线状态，并在最终报告中单独列示。

### 3.6 数据库迁移基线

当前本地 Alembic head 为：

```text
20260828_0023
```

其中 `0022/0023` 当前属于工作区用户修改的一部分。本期建议迁移：

```text
20260830_0024_add_standard_requirement_flow.py
down_revision = 20260828_0023
```

正式开发前必须再次运行 `alembic heads`；如果用户在此期间新增迁移，只调整 `down_revision`，不改 PRD 的配置决策。

---

## 4. 方案比较与选择

### 4.1 方案 A：增量扩展现有服务，推荐

做法：

- 在 `services/common` 增加需求 Review 领域模块；
- 扩展现有 `TaskManager`、`runner.py` 和 `collect_result()`；
- 在测试点工作流中增加标准需求生成分支；
- 复用现有任务目录、队列、权限、审计和工作台。

优点：改动边界最小，Review 和 FIFO 语义一致，旧流程可由开关立即恢复。

缺点：`web.py`、`TaskManager` 和生成工作流会增加分支，需要用测试固定 execution kind 和状态转换。

### 4.2 方案 B：把三类 Review 抽象为通用文档平台

做法：将 Markdown、测试点和用例全部重构为通用 `ReviewResource` 插件。

优点：长期抽象统一。

缺点：本期会扩大重构面，增加回归风险；Markdown 文本与 JSON rows 的校验、版本和发布语义并不完全相同。

结论：本期不采用。只复用原子写入、CAS、权限和接口模式，不强行统一领域模型。

### 4.3 方案 C：新增独立需求整理服务

优点：部署隔离。

缺点：新增容器、队列、Secret、任务关联和跨服务恢复，违背 PRD 的单槽 FIFO 和最小变更原则。

结论：不采用。

### 4.4 最终选择

采用方案 A。需求整理、测试点生成、Review AI、用例生成继续在同一功能智能体服务和同一执行槽位中完成；三类 Review 使用各自领域模型，但共享身份、TaskStore、文件事务和错误协议。

---

## 5. 目标架构

```text
┌──────────────────────────── test-platform ────────────────────────────┐
│ 配置定义/Release │ 身份/RBAC/CSRF │ Nginx /functional-test-agent/    │
└───────────────────────────────┬───────────────────────────────────────┘
                                │可信身份头 + Tool Client
┌──────────────────────── functional-test-agent ────────────────────────┐
│ Flask Web                                                            │
│  ├─ 任务创建/列表/详情                                               │
│  ├─ Requirement Review API                                           │
│  ├─ Test Point Review API                                            │
│  └─ Test Case Review API                                             │
│                                                                      │
│ TaskManager：单槽持久化 FIFO                                         │
│  ├─ normalize_requirement                                            │
│  ├─ generate_test_points                                             │
│  ├─ review_ai                                                        │
│  ├─ generate_cases                                                   │
│  └─ case_review_ai                                                   │
│                                                                      │
│ Runner                                                               │
│  ├─ StandardRequirementNormalizer                                    │
│  ├─ ScenarioTestPointGenerator                                       │
│  └─ Existing Case Generator                                          │
│                                                                      │
│ TaskStore                                                            │
│  ├─ 原始需求/需求草稿/需求确认版本/Requirement 索引                  │
│  ├─ 测试点草稿/确认版本                                              │
│  ├─ 用例草稿/确认版本                                                │
│  └─ execution、日志、Token、Artifact                                 │
└──────────────────────────────────────────────────────────────────────┘
```

### 5.1 依赖方向

```text
web routes
→ RequirementReviewService
→ RequirementDocumentParser / Validator / IndexBuilder
→ TaskStore

TaskManager
→ runner module subprocess
→ requirement normalizer / scenario generator / case generator

adapter
→ stage-scoped artifact publisher
→ Review source initializer
```

领域解析器不得依赖 Flask、平台 Client、LLM 或 UI；因此可以在不启动服务的情况下完成 5,000 条 Requirement 性能测试。

---

## 6. 目录与文件设计

### 6.1 功能智能体新增文件

```text
functional-test-agent/
├── agents/functional_test/prompts/
│   ├── normalize_requirement.py
│   └── generate_scenario_test_points.py
├── prompts/
│   └── functional_requirement_rule_v1_2.md
├── services/common/
│   └── requirement_review.py
├── services/functional_agent/
│   └── requirement_normalizer.py
├── services/common/static/
│   ├── requirement-review-workbench.js
│   └── requirement-review-workbench.css
└── tests/
    ├── fixtures/standard_requirement/
    │   ├── source-small.md
    │   ├── frd-2.0-valid.md
    │   ├── frd-2.0-warning.md
    │   ├── frd-2.0-invalid.md
    │   ├── requirement-index.json
    │   └── expected-scenario-points.json
    ├── services/test_requirement_review_domain.py
    ├── services/test_standard_requirement_flow.py
    └── ui/requirement-review-workbench.test.mjs
```

新增文件理由：Markdown Review 与 JSON rows Review 的数据模型不同；独立领域模块和前端控制器可避免继续扩大已经较大的 `review.py`、`case_review.py` 和工作台脚本。

### 6.2 功能智能体修改文件

```text
services/common/task_models.py
services/common/task_store.py
services/common/task_manager.py
services/common/web.py
services/common/templates/task_detail.html
services/common/static/agent-workbench.js
services/common/static/functional-workbench-v2.mjs
services/functional_agent/app.py
services/functional_agent/adapter.py
services/functional_agent/runner.py
agents/common/utils/token_usage.py
agents/functional_test/prompts/generator_test_point.py
agents/functional_test/prompts/supplement_missing_test_points.py
agents/functional_test/prompts/generator_testcase.py
agents/functional_test/workflows/case_generator_workflow.py
tests/services/test_task_runtime.py
tests/services/test_web_routes.py
tests/functional_test/test_requirement_decomposition_integration.py
README.md
```

其中 `agents/common/utils/token_usage.py` 只在现有同步调用包装不能满足需求整理时增加同等语义的异步包装；如新 normalizer 继续使用同步 `invoke()`，则无需修改。

### 6.3 平台新增与修改文件

```text
test-platform/backend/alembic/versions/
└── 20260830_0024_add_standard_requirement_flow.py

test-platform/backend/tests/test_migrations.py
test-platform/docs/功能测试智能体需求文档整理规则.md
test-platform/docker-compose.yml                 # 预计无需修改，验证为主
test-platform/nginx/nginx.conf                   # 预计无需修改，验证为主
```

Compose 和 Nginx 的现有功能智能体子路径已经覆盖新增 API，设计上不增加 location；只有实际测试证明请求体或超时配置不足时才精准修改。

---

## 7. 任务状态与 operation 兼容设计

### 7.1 主状态扩展

在现有公开状态中增加：

```text
waiting_document_review
```

非终态集合变为：

```text
pending
running
waiting_document_review
waiting_review
waiting_case_review
```

`waiting_document_review`：

- 不占执行槽位；
- 可保存、导入、下载和确认需求；
- 可取消；
- 不参与自动保留清理；
- 不能直接调用测试点或用例 Review 接口。

### 7.2 execution kind

```text
normalize_requirement
generate_test_points
review_ai
generate_cases
case_review_ai
```

旧 `initial` 保留，仅用于开关关闭的旧流程和旧任务兼容。

### 7.3 operation 映射

| operation | 输入类型 | 新流程开关开启 | 新流程开关关闭 |
|---|---|---|---|
| `decompose_requirement` | document | 继续旧独立拆解并标记 legacy | 原行为 |
| `generate_test_points` | document | 需求整理/Review → 测试点 Review | 原行为 |
| `full_pipeline` | document | 三层 Review 完整流程 | 原行为 |
| `generate_test_cases` | document | 三层 Review 完整流程，最终目标为用例发布 | 原行为 |
| `generate_test_cases` | test_points JSON | 保留高级兼容路径，直接生成用例 | 原行为 |

新建任务页面默认推荐 `full_pipeline`。前端不得通过自报“这是标准文档”绕过服务端检测。

### 7.4 状态转换

```text
pending/requirement_normalization_queued
→ running/normalizing_requirement
→ waiting_document_review/requirement_review_editing

waiting_document_review/*
→ pending/test_points_queued
→ running/generating_test_points
→ waiting_review/review_editing

waiting_review/*
→ pending/generate_cases_queued
→ running/generating_test_cases
→ waiting_case_review/case_review_editing

waiting_case_review/*
→ succeeded/published
```

通用异常分支：

```text
pending/running/waiting_* → cancelled
running(normalization/test_points/cases) → failed
running(review_ai) → waiting_review/review_ai_failed|cancelled
running(case_review_ai) → waiting_case_review/case_review_ai_failed|cancelled
```

### 7.5 快速路径是否入队

FRD-2.0 文档仍提交 `normalize_requirement` execution，但 Runner 只执行确定性检测、校验和草稿初始化，不调用 LLM。这样可以：

- 保持创建任务的事务和恢复模型一致；
- 避免在 Flask 短请求中写入多份 Review 文件；
- 继续通过 execution sequence 隔离重复或迟到结果；
- 保证“LLM 调用为零”，同时只短暂占用槽位。

该确定性步骤目标耗时小于 2 秒。

---

## 8. execution 信封与 TaskManager 设计

### 8.1 execution.json

```json
{
  "schema_version": 1,
  "sequence": 4,
  "kind": "generate_test_points",
  "queued_at": "2026-08-30T10:00:00Z",
  "requirement_version": 2,
  "review_version": null,
  "review_ai_request_version": null,
  "case_review_ai_request_version": null
}
```

字段规则：

- `sequence` 每次入队递增；
- `kind` 决定 Runner 分支；
- `requirement_version` 只由需求确认继续写入；
- `review_version` 继续表示确认测试点版本；
- AI request version 保持现有语义；
- 未使用字段写 `null`，不得复用同一个字段表达不同版本。

### 8.2 TaskManager 最小扩展

建议签名：

```python
def submit(
    self,
    record: dict[str, Any],
    request_payload: dict[str, Any],
    *,
    execution_kind: str = "initial",
    queued_stage: str = "queued",
    max_waiting: int | None = None,
) -> dict[str, Any]: ...

def resume_requirement(
    self,
    task_id: str,
    requirement_metadata: dict[str, Any],
    *,
    max_waiting: int | None = None,
) -> dict[str, Any]: ...
```

`resume_requirement()` 必须：

1. 在 `TaskManager._condition` 锁内加载任务；
2. 只接受 `waiting_document_review`；
3. 检查等待队列上限，错误码使用 `REQUIREMENT_QUEUE_FULL`；
4. 保存 `record.requirement_review` 元数据；
5. 更新 `request.json.requirement_relative_path/version/sha256/index_relative_path`；
6. 写入 `generate_test_points` execution；
7. 更新 `status=pending`、`stage=test_points_queued`、`queued_at`；
8. 保存任务并唤醒 dispatcher。

队列满时第 3 步即失败，确认文件保留，任务状态和 `request.json` 的活动输入指针不前移；重试相同确认可以重新入队。

### 8.3 迟到结果

Runner 返回必须携带：

```json
{
  "execution_kind": "generate_test_points",
  "execution_sequence": 4
}
```

TaskManager 仅在 kind 和 sequence 同时匹配时提交结果。旧 execution 的退出码、超时或结果文件不得覆盖新的 Review、确认版本或任务状态。

### 8.4 启动恢复

- `pending`：按 `queued_at + task_id` 重新参与 FIFO；
- `running/normalize_requirement`：标记 `failed/WORKER_INTERRUPTED`，原始需求保留；
- `running/generate_test_points`：标记 `failed/WORKER_INTERRUPTED`，确认需求版本保留；
- `waiting_document_review`：保持状态、草稿和确认版本；
- Review AI 按现有规则回到对应 Review 状态；
- `waiting_document_review` 必须加入 TaskStore 的非终态集合，不能被保留策略清理。

---

## 9. 任务模型与公开字段

### 9.1 task.json 新增内部/公开索引

```json
{
  "status": "waiting_document_review",
  "stage": "requirement_review_editing",
  "requirement_source": {
    "kind": "generated",
    "relative_path": "input/requirement-review/generated.md",
    "sha256": "..."
  },
  "requirement_review_draft": {
    "revision": 3,
    "sha256": "...",
    "saved_at": "...",
    "saved_by_username": "tester"
  },
  "requirement_review": {
    "version": 2,
    "sha256": "...",
    "relative_path": "input/requirement-review/confirmed-v2.md",
    "index_relative_path": "input/requirement-review/requirement-index-v2.json",
    "confirmed_requirement_count": 28,
    "pending_requirement_count": 3
  }
}
```

### 9.2 PublicTaskModel

新增公开字段：

```python
requirement_source: dict[str, Any]
requirement_review_draft: dict[str, Any]
requirement_review: dict[str, Any]
requirement_review_version: int | None
requirement_count: int
confirmed_requirement_count: int
pending_requirement_count: int
```

公开模型继续排除：

- 绝对路径；
- PID、退出码和内部 revision；
- Client Token、Secret 和 LLM API Key；
- Prompt 全文；
- 原始异常对象和 traceback；
- `request.json` 内部路径字段。

### 9.3 completed_stages 与 current_versions

新增标准值：

```json
{
  "completed_stages": [
    "requirement_input",
    "requirement_normalization",
    "requirement_review"
  ],
  "current_versions": {
    "requirement": 2,
    "test_points": 1,
    "test_cases": null
  }
}
```

阶段只根据已落盘的不可变文件推导，不能仅根据 UI 或内存状态推算。

---

## 10. 文件布局与事务

### 10.1 任务目录

```text
runtime/<environment>/functional/tasks/<task_id>/
├── task.json
├── request.json
├── execution.json
├── runner-result.json
├── token-usage.json
├── console.log
├── input/
│   ├── original/
│   │   └── requirement.md
│   ├── requirement-review/
│   │   ├── generated.md
│   │   ├── draft.json
│   │   ├── confirmed-v1.md
│   │   ├── confirmed-v2.md
│   │   ├── requirement-index-v1.json
│   │   └── requirement-index-v2.json
│   ├── review-draft.json
│   ├── review-test-points-vN.json
│   ├── case-review-draft.json
│   └── review-test-cases-vN.json
├── work/
│   └── output/
└── published/
```

上传 `.txt` 时仍将原始字节写入固定任务路径 `requirement.md`；`request.json` 单独保存原始文件名、扩展名、MIME 和 SHA。固定路径减少客户端路径参与，但不得修改文件正文。

### 10.2 原子文本写入

`TaskStore` 增加：

```python
@staticmethod
def atomic_write_bytes(path: Path, payload: bytes) -> None: ...

@staticmethod
def atomic_create_bytes(path: Path, payload: bytes) -> None: ...
```

规则：

1. 目标父目录必须位于任务目录内；
2. 拒绝符号链接；
3. 临时文件与目标文件位于同一目录；
4. 写入后 `flush + fsync`；
5. 覆盖草稿使用 `os.replace`；
6. 创建确认版本使用排他创建语义；
7. 必要时 fsync 父目录；
8. 失败清理明确的临时文件，不删除目标文件。

`atomic_write_json()` 可复用该底层实现，但本期不得借机重构无关调用。

### 10.3 Markdown 规范化与 SHA

为稳定 CAS：

- 只将 `CRLF/CR` 统一为 `LF`；
- 文末统一保留一个换行；
- 不执行 Unicode NFC/NFKC；
- 不自动删除空行、尾随空格或重新排版表格；
- SHA-256 基于规范化后的 UTF-8 字节。

这样可避免跨平台换行造成伪冲突，同时不改变用户文本语义。

### 10.4 需求确认事务

确认 vN 的提交顺序：

1. 在内存中完成 Markdown 校验和 Requirement 索引生成；
2. 写临时 Requirement index 并 fsync；
3. 原子创建 `requirement-index-vN.json`；
4. 写临时 Markdown 并 fsync；
5. 原子创建 `confirmed-vN.md`，该文件作为版本提交标记；
6. 更新 `task.json` 的版本索引；
7. 请求入队。

读取版本时只有 Markdown 和 index 同时存在才视为完整版本。若步骤 3 成功但步骤 5 失败：

- 孤立 index 不出现在版本列表；
- 相同正文重试时，如果 index 字节一致则复用后继续创建 Markdown；
- 字节不一致则返回内部一致性错误，绝不覆盖。

步骤 6 失败时，首次 GET 根据不可变文件恢复 `task.json` 索引。

---

## 11. 标准需求检测设计

### 11.1 检测结果

```python
class StandardDocumentKind(StrEnum):
    NON_STANDARD = "non_standard"
    STANDARD_VALID = "standard_valid"
    STANDARD_INVALID = "standard_invalid"
```

```python
def detect_standard_requirement(markdown: str) -> StandardDocumentKind: ...
```

### 11.2 FRD-2.0 标识

在文档的“公共上下文 → 文档信息”中确定性读取：

```text
文档类型：功能测试标准需求
结构版本：FRD-2.0
整理状态：已按规则整理
需求版本：...
原始资料：...
人工确认状态：...
```

检测不得只执行全文字符串包含判断，必须确认字段位于 `文档信息` 区域。

### 11.3 分支规则

- 三个核心标识均不存在：`NON_STANDARD`，进入 LLM 整理；
- 文档自称 FRD-2.0，但标识缺失、重复或结构非法：`STANDARD_INVALID`，不调用 LLM，将原文作为可编辑草稿进入需求 Review并展示阻塞问题；
- 标识和技术结构合法：`STANDARD_VALID`，复制为 generated/draft，进入需求 Review；
- 前端传入的任何“已标准化”字段均忽略。

此设计避免用户已整理的文档因局部格式错误被模型重新改写，也防止伪造参数绕过校验。

---

## 12. 标准需求整理 LLM 设计

### 12.1 模块职责

新增：

```python
class StandardRequirementNormalizer:
    def normalize(
        self,
        *,
        source_markdown: str,
        original_name: str,
        additional_context: str,
    ) -> NormalizationResult: ...
```

```python
@dataclass(frozen=True)
class NormalizationResult:
    markdown: str
    model_name: str
    prompt_sha256: str
    rule_version: str
    structure_version: str
```

职责仅包括：加载规则和 Prompt、构建封闭上下文、调用模型一次、提取 Markdown、执行最小技术校验。不负责保存任务、生成索引或改变状态。

### 12.2 Prompt 资产

运行时包含两个资产：

```text
prompts/functional_requirement_rule_v1_2.md
agents/functional_test/prompts/normalize_requirement.py
```

规则文件是 V1.2 的运行时镜像；Python Prompt 只定义系统边界、输入占位符和输出协议。两者都进入现有 `prompt_bundle_sha256` 计算。

自动化检查：

- 用户文档和运行时规则都包含 `V1.2`、`FRD-2.0`；
- 标准标识和标题层级契约一致；
- Prompt 不包含旧的逐片原子拆解指令；
- 规则变更必须同步更新版本号和 Prompt SHA。

### 12.3 输入边界

Prompt 结构：

```text
SYSTEM RULES
<运行时整理规则>

UNTRUSTED SOURCE DOCUMENT
<document>...</document>

TEST DESIGN CONTEXT, NOT REQUIREMENT FACT
<additional_context>...</additional_context>

OUTPUT CONTRACT
只返回 UTF-8 Markdown；不得返回解释、代码围栏或分析过程。
```

`additional_context` 只能影响整理侧重点，不能作为需求事实写入 confirmed Requirement；如包含新业务断言，应进入 Review 附录的待确认项或测试建议。

### 12.4 调用与 Token

- 使用功能智能体当前任务配置快照中的 LLM；
- 使用 `invoke_with_token_usage(..., stage="requirement_normalization")`；
- 模型超时读取 `REQUIREMENT_NORMALIZATION_TIMEOUT_SECONDS`；
- 只允许一次模型调用，不执行逐片调用；
- 允许确定性移除最外层单个 Markdown 代码围栏；
- 不使用第二个 LLM 修复格式；
- 空响应、超限或最小结构失败返回 `REQUIREMENT_NORMALIZATION_FAILED`。

### 12.5 模型不可执行能力

Normalizer 不暴露 LangChain tool、文件系统工具、HTTP client、代码解释器或其他任务检索接口。模型上下文只包含当前规则、当前原始文档、补充说明和输出协议。

---

## 13. Requirement Review 领域模型

### 13.1 草稿信封

```json
{
  "schema_version": 1,
  "revision": 3,
  "content_sha256": "...",
  "markdown": "# 新手引导流程需求\n...\n",
  "source_sha256": "...",
  "rule_version": "V1.2",
  "structure_version": "FRD-2.0",
  "saved_at": "2026-08-30T10:00:00Z",
  "saved_by_user_id": "user-1",
  "saved_by_username": "tester"
}
```

草稿信封不保存渲染 HTML、编辑器光标、滚动位置、搜索内容或未保存本地文本。

### 13.2 校验问题

```python
@dataclass(frozen=True)
class RequirementValidationIssue:
    code: str
    severity: Literal["error", "warning"]
    message: str
    line: int | None
    section: str | None
    requirement_id: str | None
```

```python
@dataclass(frozen=True)
class RequirementValidation:
    issues: list[RequirementValidationIssue]
    valid_for_save: bool
    valid_for_confirm: bool
    validation_sha256: str
    requirement_count: int
    confirmed_count: int
    pending_count: int
    review_item_count: int
```

### 13.3 保存规则

```python
def save_draft(
    task_id: str,
    markdown: str,
    revision: int,
    sha256: str,
    user_id: str,
    username: str,
    max_bytes: int,
    max_characters: int,
) -> dict[str, Any]: ...
```

- 只允许 `waiting_document_review`；
- revision/SHA 必须同时匹配；
- 业务质量警告和可修复结构错误允许保存；
- 非 UTF-8、NUL、容量超限、危险内部字段或无法序列化不得保存；
- 同正文 SHA 不增加 revision；
- 保存返回完整服务端校验结果；
- 冲突返回当前 revision/SHA，不返回当前正文。

### 13.4 确认规则

```python
def confirm(
    task_id: str,
    revision: int,
    sha256: str,
    *,
    accept_warnings: bool,
    expected_validation_sha256: str,
) -> RequirementConfirmation: ...
```

硬错误阻止确认；质量警告要求 `accept_warnings=true` 且 validation SHA 与当前校验一致，防止用户确认了旧问题集合后内容又变化。

### 13.5 服务职责

`RequirementReviewService` 负责：

- 初始化 generated/draft；
- 加载 original/generated/draft/confirmed；
- CAS 保存；
- 生成不可变确认 Markdown 和 index；
- 恢复任务版本索引；
- 生成允许操作；
- 不直接入队。入队仍由 Web route 在确认事务完成后调用 TaskManager。

---

## 14. Markdown 解析与校验

### 14.1 解析器原则

解析器是受限 Markdown 词法扫描器，不实现完整 HTML 渲染。它只识别：

- 围栏代码块边界；
- H1～H6 ATX 标题；
- `**标签**`；
- 无序列表；
- Requirement、Q/A/C 标识；
- 文档信息键值。

代码围栏中的 `#`、`REQ-` 和标签不得被识别为业务结构。

### 14.2 标题规则

- 恰好一个 H1；
- 允许 H2、H3；
- H4～H6 为阻塞错误；
- H3 必须归属于 H2；
- `Review 附录` 必须是 H2；
- 公共上下文、业务模块、跨功能规则、Review 附录允许多个 H3；
- 空标题为阻塞错误；
- 重复标题是警告，不自动改名。

### 14.3 Requirement 语法

正式 Requirement 行：

```text
- REQ-{模块缩写}-{三位及以上序号}：{非空、单行、可验证规则}
```

推荐正则：

```text
^\s*[-*]\s+(REQ-[A-Z0-9][A-Z0-9_-]{0,47}-\d{3,})[：:]\s*(\S.*)$
```

规则：

- ID 最长 64 字符；
- 大小写统一转为大写用于比较，但保存原文不自动改写；
- 全文重复 ID 为阻塞错误；
- 正常业务 H2/H3 下的 Requirement 状态为 confirmed；
- Review 附录中的 Requirement 不进入 confirmed 集合；
- Review 附录的 Q/A/C 和测试建议进入 `review_items`；
- 无法映射到有效 H2/H3 的 Requirement 标记 pending 并产生警告。

### 14.4 技术错误

- 编码、字节、字符或节点数超限；
- 缺少或重复 H1；
- H4～H6；
- FRD-2.0 核心标识缺失/冲突；
- Requirement ID 重复或非法；
- NUL、危险内部字段、不可安全序列化；
- 解析器状态异常，例如未闭合代码围栏。

### 14.5 质量警告

- 功能没有 Requirement；
- Requirement 缺少验收标准关联；
- 功能缺少异常/反向流程；
- 未确认项、歧义或冲突存在；
- 业务模块或功能标题重复；
- 场景映射不完整；
- 文档信息中的人工确认状态未更新。

质量警告允许用户明确确认后继续。

---

## 15. Requirement 索引设计

### 15.1 Schema

```json
{
  "schema_version": 1,
  "document_type": "functional_test_requirement",
  "structure_version": "FRD-2.0",
  "requirement_version": 2,
  "document_sha256": "...",
  "generated_at": "...",
  "requirements": [
    {
      "id": "REQ-GOAL-001",
      "module": "新手引导",
      "feature": "Dating Goal",
      "text": "首次进入默认选中 Not sure",
      "status": "confirmed",
      "source_section": "2.2 Dating Goal",
      "source_line": 126
    }
  ],
  "review_items": [
    {
      "id": "Q-001",
      "kind": "question",
      "text": "网络失败后是否自动重试尚未说明",
      "source_section": "Review 附录",
      "source_line": 280
    }
  ]
}
```

### 15.2 确定性规则

- `module` 来自最近的业务 H2；
- `feature` 来自最近的 H3；
- 跨功能规则保留 H2=`跨功能规则` 和具体 H3；
- `source_section` 使用稳定标题路径；
- `source_line` 仅用于 UI 定位，不参与正式覆盖语义；
- requirements 按文档出现顺序保存；
- review_items 按 Q/A/C/建议出现顺序保存；
- 相同 Markdown 字节必须生成完全相同的业务内容和 SHA；`generated_at` 不参与内容 SHA。

### 15.3 索引内容 SHA

索引的 `content_sha256` 应基于移除 `generated_at` 后的稳定 JSON 字节计算，用于检测程序非确定性。文档 SHA 必须与确认 Markdown 一致。

### 15.4 数量上限

- Requirement 最大 5,000；
- Review item 最大 5,000；
- 单个 ID 最大 64 字符；
- 单条 text 最大 10,000 字符；
- 超限返回稳定技术错误，不静默截断。

---

## 16. Requirement Review HTTP API

所有路径位于：

```text
/functional-test-agent/api/v1/tasks/{task_id}
```

### 16.1 GET /requirement-review

查询参数：

```text
kind=generated|draft|confirmed
version=N  # kind=confirmed 时可选；默认当前版本
```

响应：

```json
{
  "task_id": "...",
  "status": "waiting_document_review",
  "kind": "draft",
  "editable": true,
  "markdown": "# ...\n",
  "revision": 3,
  "sha256": "...",
  "validation": {
    "valid_for_confirm": true,
    "validation_sha256": "...",
    "errors": [],
    "warnings": []
  },
  "summary": {
    "requirements": 31,
    "confirmed": 28,
    "pending": 3,
    "review_items": 4
  },
  "versions": [1, 2],
  "allowed_actions": ["save", "import", "confirm", "download"]
}
```

原始需求通过 download 接口获取，不在普通 GET 中同时返回两份大文本。

### 16.2 PUT /requirement-review-draft

请求：

```json
{
  "revision": 3,
  "sha256": "...",
  "markdown": "# ...\n"
}
```

成功返回 200；相同正文返回原 revision；CAS 冲突返回 409：

```json
{
  "code": "REQUIREMENT_REVISION_CONFLICT",
  "message": "需求草稿已被其他页面更新",
  "request_id": "...",
  "details": {
    "current_revision": 4,
    "current_sha256": "..."
  }
}
```

### 16.3 POST /requirement-review-draft/import

使用 multipart：

```text
requirement_file=.md/.txt
revision=3
sha256=...
```

导入按完整草稿保存，执行相同 CAS、UTF-8、容量和结构校验，不自动确认或入队。

### 16.4 GET /requirement-review/download

```text
kind=original|generated|draft|confirmed|requirement_index
version=N
```

服务端将 kind/version 映射到固定路径；不接受文件名或路径参数。过期返回 410，不存在返回 404。

### 16.5 POST /requirement-review/confirm

Header：

```text
Idempotency-Key: 8～128字符
```

Body：

```json
{
  "revision": 3,
  "sha256": "...",
  "accept_warnings": true,
  "validation_sha256": "..."
}
```

成功返回 202：

```json
{
  "task_id": "...",
  "status": "pending",
  "stage": "test_points_queued",
  "requirement_version": 2,
  "requirement_sha256": "...",
  "queue_position": 3
}
```

队列满返回 409/`REQUIREMENT_QUEUE_FULL`，响应仍返回已确认版本元数据；任务保持 `waiting_document_review`。

### 16.6 权限与状态

| 接口 | 权限 | 状态 |
|---|---|---|
| GET/download | `tool.result.view` + 所有权 | Review、后续状态、历史成功任务 |
| PUT/import | `tool.execute` + 所有权 + CSRF | `waiting_document_review` |
| confirm | `tool.execute` + 所有权 + CSRF | `waiting_document_review` |
| 管理员跨用户 | 额外 `task.view.all` | 同上 |

越权和任务不存在统一 404。

---

## 17. Runner 与 Adapter 设计

### 17.1 normalize_requirement 分支

伪代码：

```python
if execution.kind == "normalize_requirement":
    source = read_current_task_source()
    kind = detect_standard_requirement(source)
    if kind is NON_STANDARD:
        generated = normalizer.normalize(...)
    else:
        generated = source
    validation = validate_requirement_document(generated)
    if kind is NON_STANDARD and validation.has_hard_errors:
        raise RequirementNormalizationError(...)
    write_work_output(generated)
    return {
        "next_status": "waiting_document_review",
        "stage": "requirement_review_editing",
        "requirement_source_kind": kind.value,
        "validation_summary": validation.summary,
    }
```

上传的 `STANDARD_INVALID` 文档允许进入 Review 修复；模型新生成的非法文档按 PRD 进入失败状态。

### 17.2 generate_test_points 分支

Runner 只从 `request.json.requirement_relative_path` 和 `requirement_index_relative_path` 读取不可变确认版本，并校验：

- 两个路径位于当前任务目录；
- 文件不是符号链接；
- version 与 execution 一致；
- Markdown SHA 与 index.document_sha256 一致；
- index schema 和 FRD 版本受支持。

校验通过后调用标准场景测试点生成器；不得回退到原始需求或旧拆解结果。

### 17.3 collect_result 阶段化

现有 `collect_result()` 会扫描整个 `work/output`。本期应根据 execution kind 只发布当前阶段允许的产物：

| kind | 允许发布 |
|---|---|
| normalize_requirement | 标准需求 Markdown |
| generate_test_points | 测试点 JSON/Markdown、覆盖摘要 |
| generate_cases | 用例 JSON/XLSX |
| Review AI | 仍由不可变建议文件管理，不重新发布历史 Artifact |

Artifact registry 使用 merge，不清空前一阶段产物。这样可避免后续执行再次发布旧文件或错误覆盖 Review source。

### 17.4 request.json 指针

```json
{
  "input_relative_path": "input/original/requirement.md",
  "input_sha256": "...",
  "requirement_relative_path": "input/requirement-review/confirmed-v2.md",
  "requirement_index_relative_path": "input/requirement-review/requirement-index-v2.json",
  "requirement_version": 2,
  "requirement_sha256": "...",
  "review_relative_path": "input/review-test-points-v1.json"
}
```

活动指针只在成功入队时更新。历史版本路径只能由服务端生成。

---

## 18. 场景级测试点生成设计

### 18.1 新旧分支隔离

`case_generator_workflow.py` 增加显式入口：

```python
def generate_scenario_test_points(
    *,
    requirement_markdown: str,
    requirement_index: dict[str, Any],
    additional_context: str,
) -> list[dict[str, Any]]: ...
```

新入口不调用：

- `prepare_requirement_context_from_document_path()`；
- `run_decomposition()`；
- 旧 test seed；
- 旧 LLM 覆盖判断器。

旧 `GeneratorPointWorkflow` 保留给开关关闭和 CLI 兼容路径。

### 18.2 功能批次构造

解析确认 Markdown 为：

```python
@dataclass(frozen=True)
class RequirementGenerationBatch:
    module: str
    feature: str
    public_context: str
    feature_markdown: str
    cross_rules_markdown: str
    requirements: list[IndexedRequirement]
```

批次规则：

- 一个完整 H3 功能章节为一个基本批次；
- 不按加粗标签、表格行或单 Requirement 拆分；
- 公共上下文进入每个批次；
- 明确适用于该功能的跨功能规则进入批次；
- 无法确定适用范围的跨功能规则进入所有相关模块批次并记录来源；
- 单个批次超过 120,000 字符时返回 `REQUIREMENT_CONTEXT_TOO_LARGE`，不得静默截断；
- 批次顺序使用文档顺序，结果合并顺序稳定。

### 18.3 Prompt 输出

模型只返回测试点数组，不返回覆盖结论：

```json
[
  {
    "module": "新手引导",
    "feature": "Dating Goal",
    "scenario": "目标选择并继续",
    "test_point": "验证默认选择、切换、本地保存和继续流程",
    "preconditions": ["新用户从 Personalize 进入 Dating Goal"],
    "expected_result": "Not sure 默认唯一选中；切换后保持单选并立即保存；Continue 后进入 Your Voice 且选择不丢失",
    "requirement_ids": ["REQ-GOAL-001", "REQ-GOAL-002"],
    "status": "confirmed",
    "source_type": "requirement",
    "risk_level": "P0"
  }
]
```

Prompt 必须明确：

- 业务场景是最小设计单位；
- 连续操作和相关结果优先合并；
- 不按字段数、页面元素数、步骤数或 Requirement 数拆分；
- 禁止通用“UI 显示检查”；
- 只有需求明确的事实可标 confirmed；
- 模型推测的并发、幂等、超时、兼容和安全方向必须标 pending；
- Requirement ID 只能从当前批次白名单选择；
- 不生成 ID，由程序统一分配。

### 18.4 规范化和 ID

程序完成：

- 类型规范化；
- 空白和换行标准化；
- Requirement ID 白名单校验；
- 风险等级校验；
- confirmed/pending 校验；
- 稳定排序；
- ID 分配。

ID 格式：

```text
TP-{模块稳定缩写}-{三位全局序号}
```

模块缩写由安全 slug/稳定哈希生成；首次生成顺序固定为文档批次顺序和模型返回顺序。补充结果从当前最大序号继续，永不复用已分配 ID。

### 18.5 失败策略

- 单批模型失败：任务失败，已完成批次保留在 work 供诊断但不发布为 Review source；
- 非法 JSON：执行一次确定性代码围栏/尾逗号安全修复，仍失败则任务失败；
- Requirement 引用越界：该批失败，不自动改成其他 ID；
- 不允许以空数组伪装成功；
- 失败错误响应不包含原始 Prompt 或需求全文。

---

## 19. 确定性覆盖、补充与去重

### 19.1 覆盖计算

```python
def calculate_requirement_coverage(
    index: RequirementIndex,
    points: list[dict[str, Any]],
) -> CoverageResult: ...
```

```python
@dataclass(frozen=True)
class CoverageResult:
    confirmed_total: int
    covered_confirmed: int
    ratio: float
    missing_requirement_ids: list[str]
    invalid_requirement_ids: list[str]
    pending_only_point_ids: list[str]
```

算法复杂度 O(R + P + M)，其中 R 为 Requirement 数，P 为测试点数，M 为映射数。

### 19.2 正式集合

```text
confirmed_ids = index.requirements where status == confirmed
covered_ids = union(point.requirement_ids) where point.status == confirmed
missing = confirmed_ids - covered_ids
ratio = |confirmed_ids ∩ covered_ids| / |confirmed_ids|
```

confirmed Requirement 为空时 ratio 返回 `null` 而不是伪造 100%，并产生质量警告。

### 19.3 补充一轮

测试点补充最多一次；不得因覆盖仍有缺口而继续循环调用模型。

仅当 `missing` 非空且 `TEST_POINT_SUPPLEMENT_MAX_ROUNDS=1` 时执行：

1. 按所在 H3 功能对 missing ID 分组；
2. 输入完整 Requirement 事实、功能章节和已有测试点摘要；
3. 模型只可输出覆盖这些 missing ID 的候选测试点；
4. 规范化、分配新 ID、去重；
5. 重新执行一次确定性覆盖；
6. 仍缺失则停止模型调用并进入人工 Review。

补充轮次和 Token 记录到 `test_points_supplement` stage。

### 19.4 完全重复

规范键包含：

```text
module
feature
scenario
preconditions
test_point
expected_result
sorted(requirement_ids)
status
```

完全重复是阻塞错误；补充结果与已有结果重复时直接丢弃重复候选并记录数量。文本相似但上下文不同只产生警告，不进行模型去重。

---

## 20. 测试点 Review 集成

### 20.1 Schema 扩展

现有 Review rows 必须完整保留：

```text
preconditions
expected_result
requirement_ids
status
source_type
risk_level
```

未知扩展字段继续往返。`requirement_ids` 在脑图、表格和详情编辑时保持数组，不允许保存为逗号拼接字符串。

### 20.2 GET 响应新增

```json
{
  "requirement_trace": {
    "requirement_version": 2,
    "requirement_sha256": "...",
    "confirmed_total": 28,
    "covered_confirmed": 27,
    "coverage_ratio": 0.9643,
    "missing_requirement_ids": ["REQ-VOICE-009"],
    "pending_suggestion_count": 3
  }
}
```

### 20.3 保存与确认

- 保存允许未覆盖、相似和 pending 建议；
- 引用不存在 Requirement、confirmed 点只引用 pending Requirement、完全重复为阻塞错误；
- 确认并继续必须展示未覆盖清单和 pending 数量；
- 用户确认风险时提交当前 `validation_sha256`；
- Requirement index 由服务端按任务确认版本读取，客户端不得上传覆盖基线；
- 确认测试点版本记录来源 requirement version/SHA。

### 20.4 AI Review

现有测试点 AI Review 继续只产生建议。AI 上下文增加当前确认 Requirement 和映射，但：

- 不得更换 Requirement 版本；
- add 建议只能引用索引中的 ID；
- replace 建议必须保留原点的 confirmed 事实映射，除非用户随后人工编辑；
- AI 失败仍回 `waiting_review`；
- 应用建议只修改浏览器内存，仍需显式保存。

---

## 21. 测试点到测试用例事实契约

### 21.1 输入 DTO

```python
@dataclass(frozen=True)
class ConfirmedTestPointInput:
    id: str
    module: str
    feature: str
    scenario: str
    test_point: str
    preconditions: list[str]
    expected_result: str
    requirement_ids: list[str]
    status: Literal["confirmed", "pending"]
    source_type: str
    risk_level: str
```

### 21.2 锁定用例骨架

程序在调用 LLM 前生成：

```json
{
  "test_point_id": "TP-GOAL-001",
  "module": "新手引导",
  "feature": "Dating Goal",
  "scenario": "目标选择并继续",
  "priority": "P0",
  "requirement_ids": ["REQ-GOAL-001", "REQ-GOAL-002"],
  "requirement_status": "confirmed",
  "expected_result": "来自确认测试点的明确结果"
}
```

LLM 主要补充：

- 可执行的前置条件细化；
- 测试步骤；
- 测试数据；
- 不改变明确事实的检查表达。

合并时，锁定字段以程序骨架为准，模型同名字段不得覆盖。

### 21.3 类型规则

- `preconditions`：字符串数组；
- `test_steps`：字符串数组；
- `test_data`：对象、数组或兼容字符串，但必须可安全 JSON 序列化；
- `requirement_ids`：字符串数组；
- `requirement_status`：confirmed/pending；
- `expected_result`：字符串；
- `actual_result`：保留兼容、只读。

### 21.4 单点重试

生成后逐测试点检查：

- 至少一条用例；
- test_point_id 绑定正确；
- Requirement 映射完整；
- 锁定事实一致；
- 必要数组和 JSON 类型有效。

仅对失败的测试点重试一次。重试仍失败则任务失败并返回 `TEST_CASE_FACT_MISMATCH`，不得用其他测试点结果填充。

### 21.5 黄金事实

自动化必须固定：

```text
TP-GOAL-001 → Not sure
TP-GOAL-006 → Your Voice
TP-VOICE-006 → Loading
TP-DONE-005 → Reply tab
TP-STATE-002 → 已跳过，禁止改成已完成
TP-PERSIST-005 → 恢复第6步
```

---

## 22. Requirement Review 页面设计

### 22.1 加载与开关

当：

```text
STANDARD_REQUIREMENT_FLOW_ENABLED=true
REQUIREMENT_REVIEW_ENABLED=true
task.status=waiting_document_review
```

渲染在线 Review。关闭总开关时，新任务走旧流程；已处于 `waiting_document_review` 的任务仍必须提供只读下载和安全处理入口，不能因关闭开关变成不可访问数据。

### 22.2 页面布局

```text
┌─────────────────────────────────────────────────────────────────────┐
│ 任务头：标题 / 状态 / 来源 / 规则版本 / 保存状态                    │
├──────────────┬──────────────────────────────────┬───────────────────┤
│ 章节目录     │ Markdown 纯文本编辑器            │ 校验与统计        │
│ Requirement │                                  │ 错误/警告         │
│ 搜索结果     │                                  │ 未确认/冲突       │
├──────────────┴──────────────────────────────────┴───────────────────┤
│ 高级操作：下载/导入              保存草稿    确认并生成测试点      │
└─────────────────────────────────────────────────────────────────────┘
```

桌面宽度：

- 左侧 240～280px；
- 右侧 300～360px；
- 中间编辑器自适应，最小 560px；
- 1280px 时允许左右栏压缩，不允许覆盖主操作；
- 不实现移动端。

### 22.3 编辑器

使用原生 `<textarea>`，不引入 Monaco、CodeMirror 或富文本依赖。能力：

- UTF-8 纯文本编辑；
- Tab 键插入两个空格；
- `Ctrl/Command+S` 保存；
- dirty 状态；
- 离开确认；
- 服务端问题行定位；
- 当前行和选择范围恢复；
- 只读历史版本。

不渲染或执行 Markdown HTML。若后续增加预览，必须使用白名单 sanitizer 并另行评审。

### 22.4 章节和 Requirement 搜索

前端使用服务端返回的轻量 outline/index：

```json
{
  "outline": [
    {"level": 2, "title": "新手引导", "line": 42},
    {"level": 3, "title": "Dating Goal", "line": 51}
  ],
  "requirement_refs": [
    {"id": "REQ-GOAL-001", "line": 67, "status": "confirmed"}
  ]
}
```

点击结果聚焦 textarea 对应行。搜索在 5,000 条索引下不超过 300ms；输入延迟 150ms。

### 22.5 保存和冲突

- 仅显式保存；
- 保存成功显示 revision 和 3 秒状态提示；
- CAS 冲突保留本地文本；
- 提供“下载本地副本”和“重新载入服务器版本”；
- 不提供自动三方合并；
- 相同 SHA 时 dirty 自动恢复为 false。

### 22.6 确认

- 有硬错误时禁用并定位第一项；
- 有警告时显示分组、数量和 validation SHA 对应确认对话框；
- 确认成功进入排队状态；
- 队列满时仍显示“需求版本已确认，可稍后重新入队”；
- 重复点击使用同一 Idempotency-Key 复用结果。

### 22.7 阶段导航

现有功能工作台导航扩展为：

```text
任务信息
需求整理
需求 Review
测试点生成
测试点 Review
测试用例生成
测试用例 Review
发布产物
```

已完成阶段可只读查看；未来阶段不可点击；阶段判断来自任务状态和不可变版本，不使用虚假百分比。

---

## 23. 前端控制器设计

新增 `requirement-review-workbench.js`，职责保持单一：

```javascript
class RequirementReviewController {
  async load(kind = "draft", version = null) {}
  onEditorInput() {}
  async saveDraft() {}
  async importDraft(file) {}
  async confirmAndQueue() {}
  selectIssue(issueId) {}
  selectRequirement(requirementId) {}
  downloadLocalCopy() {}
  destroy() {}
}
```

### 23.1 客户端状态

```javascript
{
  markdown,
  serverMarkdown,
  revision,
  sha256,
  validationSha256,
  validation,
  summary,
  outline,
  versions,
  kind,
  editable,
  dirty,
  saving,
  conflict,
  abortController
}
```

### 23.2 竞态控制

- 每次 load/save 使用单调 request sequence；
- 旧响应不得覆盖新编辑；
- 页面销毁时 abort 未完成请求；
- 保存期间再次点击只复用当前 Promise；
- 状态轮询不得重载 dirty 页面；
- 任务离开 Review 状态后，只有 dirty=false 时自动刷新一次。

### 23.3 纯函数测试

将以下逻辑导出为纯函数供 Node 内置测试：

- `canonicalizeMarkdown()`；
- `isDirty()`；
- `lineOffset()`；
- `filterRequirementRefs()`；
- `canTransitionAfterPoll()`；
- `buildConfirmPayload()`。

不引入新的前端测试依赖。

---

## 24. 配置设计

### 24.1 配置项

| 配置 | 类型 | 默认值 | 作用 |
|---|---|---:|---|
| `STANDARD_REQUIREMENT_FLOW_ENABLED` | boolean | false | 新主流程总开关 |
| `REQUIREMENT_NORMALIZATION_ENABLED` | boolean | true | 允许非标准文档执行 LLM 整理 |
| `REQUIREMENT_REVIEW_ENABLED` | boolean | true | 在线需求 Review |
| `REQUIREMENT_NORMALIZATION_TIMEOUT_SECONDS` | integer | 900 | 整理 execution 超时 |
| `REQUIREMENT_MAX_BYTES` | integer | 5242880 | 原始/草稿字节上限 |
| `REQUIREMENT_MAX_CHARACTERS` | integer | 500000 | 解码字符上限 |
| `REQUIREMENT_MAX_ITEMS` | integer | 5000 | Requirement 上限 |
| `REQUIREMENT_STRUCTURE_VERSION` | string | `FRD-2.0` | 受支持结构版本 |
| `TEST_POINT_SUPPLEMENT_MAX_ROUNDS` | integer | 1 | 缺口补充上限 |

总开关为 false 时，两个子能力即使为 true 也不生效。

### 24.2 任务配置快照

任务创建时平台保存配置选择器；Runner 启动时仍按现有二阶段物化得到普通配置与 Secret。任务进行多次 execution 时沿用该任务的配置快照，不自动漂移到新 Release。

页面展示：

- 模型；
- Prompt bundle SHA；
- 规则版本；
- 结构版本；
- 配置 Release；
- 应用版本；
- 各阶段 Token 和耗时。

### 24.3 readiness

新增布尔字段：

```json
{
  "standard_requirement_flow_enabled": true,
  "requirement_normalization_enabled": true,
  "requirement_review_enabled": true,
  "requirement_rule_ready": true
}
```

不返回规则正文、Prompt、Secret 或配置值全集。

---

## 25. 平台迁移设计

### 25.1 迁移文件

```text
test-platform/backend/alembic/versions/20260830_0024_add_standard_requirement_flow.py
```

升级只插入 9 个 `functional-test-agent` 普通配置定义：

- ID 使用 `functional-test-agent.<KEY>`；
- `apply_mode=next_task`；
- `editable=true`；
- 使用现有 JSON validation schema；
- 不增加 Secret；
- 不创建业务表；
- 不修改权限。

### 25.2 dev Release

迁移只登记定义，不在数据库迁移中隐式开启功能。dev 发布步骤通过现有配置中心创建新 Release：

```text
STANDARD_REQUIREMENT_FLOW_ENABLED=true
REQUIREMENT_NORMALIZATION_ENABLED=true
REQUIREMENT_REVIEW_ENABLED=true
```

prod 不创建启用 Release，首次发布保持总开关 false。

### 25.3 downgrade

降级到 `20260828_0023` 时：

1. 删除引用 9 个定义的 `config_release_items`；
2. 删除 9 个 definitions；
3. 不删除其他 Release、Secret、任务、审计或文件；
4. 若 active Release 引用了这些定义，剩余配置项仍保持 Release 有效；
5. 不修改功能智能体任务卷。

### 25.4 迁移验证

- 空库 upgrade 到 head；
- 已到 0023 的库 upgrade；
- 重复 upgrade 无重复定义；
- downgrade 到 0023；
- re-upgrade；
- dev/prod 配置隔离；
- API 智能体定义不变化。

---

## 26. 身份、权限、CSRF 与安全

### 26.1 权限矩阵

| 操作 | 权限 | 所有权 |
|---|---|---|
| 查看需求 Review | `tool.result.view` | 创建者；管理员需 `task.view.all` |
| 保存/导入/确认需求 | `tool.execute` | 同上 |
| 取消任务 | `task.cancel` | 同上 |
| 下载历史需求版本 | `tool.result.view` | 同上 |

所有写请求执行双提交 CSRF。越权和不存在统一 404，避免 task ID 枚举。

### 26.2 Prompt 注入

原始需求、草稿和补充说明均是不可信文本：

- 文档中的“忽略系统指令”“读取文件”“调用 URL”等不执行；
- 不把需求正文拼接为 system message；
- 使用明确数据边界标签；
- 不为 normalizer 和测试点生成器绑定工具；
- 不读取日志、其他任务、历史 output 或任意路径；
- 模型输出只作为 Markdown/JSON 数据处理。

### 26.3 Markdown/XSS

MVP 编辑器只使用 textarea 和 `textContent`。目录、问题、Requirement 文本、标题、文件名和 AI 输出均不得通过 `innerHTML` 注入。下载响应固定 `Content-Disposition` 安全文件名。

### 26.4 路径和文件

- 所有 task_id 使用现有格式校验；
- 路径由服务端枚举生成；
- containment 在 resolve 后校验；
- 禁止 symlink；
- download 不接受路径；
- 过期文件返回 410；
- 日志和错误二次脱敏。

### 26.5 容量与拒绝服务

- 网关继续使用 6 MiB 请求体限制；
- 应用流式限制 5 MiB；
- 解码后 500,000 字符；
- 5,000 Requirement；
- 单功能生成上下文 120,000 字符；
- 问题响应只返回定位摘要，不返回整份正文。

---

## 27. 审计、日志、Token 与观测

### 27.1 审计事件

```text
requirement.normalization.started
requirement.normalization.completed
requirement.normalization.failed
requirement.draft.saved
requirement.draft.imported
requirement.confirmed
requirement.warning.acknowledged
test_points.generation.started
test_points.generation.completed
test_points.coverage.calculated
test_points.coverage_gap.acknowledged
```

审计 metadata 白名单：任务 ID、用户、版本、SHA、数量、模型、Prompt SHA、Token、耗时和稳定错误码。不得记录正文、Secret、绝对路径或 traceback。

### 27.2 Token stage

```text
requirement_normalization
test_points_generation
test_points_supplement
test_points_review_ai
test_cases_generation
test_cases_supplement
test_cases_review_ai
```

快速路径 `requirement_normalization` 记录 `calls=0` 和零 Token，页面明确显示“标准文档快速路径，未调用模型”。

### 27.3 日志

允许记录：

- execution kind/sequence；
- 当前批次序号和总批次数；
- H3 标题的安全摘要或哈希；
- Requirement/测试点/缺口数量；
- Token、耗时和错误码。

不得记录完整需求正文、完整 Prompt、Secret 或平台 Client Token。

### 27.4 progress

```json
{
  "phase": "generating_test_points",
  "completed_items": 3,
  "total_items": 8,
  "unit": "feature_sections"
}
```

总量未知时使用 null；不推算虚假百分比。

---

## 28. 错误协议

### 28.1 PRD 错误码

保留：

```text
REQUIREMENT_FILE_INVALID
REQUIREMENT_ENCODING_INVALID
REQUIREMENT_TOO_LARGE
REQUIREMENT_NORMALIZATION_FAILED
REQUIREMENT_STRUCTURE_INVALID
REQUIREMENT_VERSION_UNSUPPORTED
REQUIREMENT_ID_DUPLICATED
REQUIREMENT_DRAFT_REQUIRED
REQUIREMENT_REVISION_CONFLICT
REQUIREMENT_CONFIRMATION_REQUIRED
REQUIREMENT_VERSION_NOT_FOUND
REQUIREMENT_QUEUE_FULL
TEST_POINT_REQUIREMENT_NOT_FOUND
TEST_POINT_DUPLICATED
TEST_POINT_COVERAGE_INCOMPLETE
TEST_CASE_FACT_MISMATCH
```

### 28.2 设计补充错误码

| 错误码 | HTTP | 场景 |
|---|---:|---|
| `REQUIREMENT_CONTEXT_TOO_LARGE` | 422 | 单个完整功能批次超过安全上下文限制 |
| `REQUIREMENT_INDEX_INVALID` | 409 | 确认 Markdown 与 index 不一致或损坏 |
| `REQUIREMENT_CONFIRMATION_CONFLICT` | 409 | Idempotency-Key 被用于不同草稿 |
| `TEST_POINT_GENERATION_INVALID` | 500 | 模型输出无法形成合法测试点集合 |

错误响应：

```json
{
  "code": "REQUIREMENT_STRUCTURE_INVALID",
  "message": "标准需求文档存在阻塞问题",
  "request_id": "...",
  "details": {
    "issue_count": 2,
    "first_issue": {
      "code": "REQUIREMENT_ID_DUPLICATED",
      "line": 86,
      "requirement_id": "REQ-GOAL-001"
    }
  }
}
```

`details` 使用明确白名单，不包含全文和内部对象。

---

## 29. 兼容与恢复设计

### 29.1 功能开关回退

`STANDARD_REQUIREMENT_FLOW_ENABLED=false` 时：

- 新任务走当前 `initial` 路径；
- 旧测试点/用例 Review 不变；
- `decompose_requirement` 可用；
- 已存在需求 Review 任务仍可查看和下载，管理员可取消；
- 不删除任何新流程文件。

### 29.2 旧任务

- 不批量迁移；
- 缺少 `requirement_review` 的任务按旧页面展示；
- 旧测试点/用例确认版本不补 Requirement 映射；
- 历史 output 不扫描；
- PublicTaskModel 对缺失字段使用空值。

### 29.3 CLI

`case_generator_agent.py` 和现有工具函数默认行为保持不变。新标准流程由平台 Runner 显式选择，不改变用户直接运行旧 CLI 时的默认语义。

后续若需要 CLI 使用标准流程，应新增显式参数，而不是改变默认值；该能力不属于本期。

### 29.4 文件损坏

- draft.json 损坏：隔离该文件，回退 generated 或最近确认版本，只读提示恢复；
- confirmed Markdown 或 index 单边缺失：版本不对外可用，任务索引不指向该版本；
- task.json 索引损坏：从成对的不可变文件恢复；
- 原始文件损坏/缺失：不得重新从 Artifact 猜测输入，返回稳定错误；
- Artifact registry 损坏：不影响 Review 事实文件，按现有策略恢复或隔离。

---

## 30. 性能与非功能设计

### 30.1 后端指标

| 场景 | 目标 |
|---|---:|
| 100 KB 需求 Review GET | ≤ 2 秒 |
| 5,000 Requirement 解析+校验 | ≤ 2 秒 |
| 5,000 Requirement 覆盖计算 | ≤ 2 秒 |
| 5,000 Requirement 搜索 | ≤ 300ms |
| 确认事务，不含排队 | ≤ 2 秒 |

### 30.2 算法

- Markdown 扫描 O(N)；
- ID 唯一性使用 dict/set；
- 覆盖使用 set；
- 去重使用规范化 tuple/hash；
- 不对 5,000 条记录执行 O(N²) 相似度比较；
- 文本相似提示只在同模块/功能的小桶内执行受限比较，或首期不做自动相似度阻塞。

### 30.3 前端

- textarea 不生成逐字符 DOM；
- outline/Requirement 列表虚拟分页或最多渲染 200 项；
- 搜索只更新列表，不重建编辑器；
- 页面轮询复用现有 `agentFetch`；
- 200% 缩放下主操作可见；
- `prefers-reduced-motion` 关闭非必要动画；
- 状态同时有文字/图标，不只依赖颜色。

---

## 31. 自动化测试设计

### 31.1 Requirement 领域单元测试

- FRD-2.0 标识合法、缺失、重复、冲突；
- H1/H2/H3、H4+、空标题、代码围栏保护；
- Requirement 正则、大小写比较、重复 ID、非法 ID；
- Review 附录 Q/A/C/建议；
- confirmed/pending 归类；
- module/feature/source line；
- 换行规范化与稳定 SHA；
- 5,000 条性能；
- NUL、字节、字符和内容上限。

### 31.2 文件事务

- 草稿首次保存；
- 相同正文不增 revision；
- CAS 冲突；
- confirmed/index 成对不可变；
- 相同 SHA 确认复用版本；
- 不同 SHA 生成 v2/v3；
- index 成功、Markdown 失败恢复；
- task 索引失败后读取恢复；
- symlink 和路径穿越拒绝。

### 31.3 TaskManager

- normalize_requirement 与 generate_test_points execution；
- `queued_at + task_id` FIFO；
- 最后一个等待位竞争；
- 队列满保留确认版本；
- waiting_document_review 取消；
- timeout、进程组终止、迟到结果；
- 重启恢复；
- Review AI/正式生成共享一个槽位。

### 31.4 Normalizer

- 标准有效文档零 LLM；
- 标准无效文档零 LLM且可编辑；
- 普通文档一次 LLM；
- 空响应、围栏、超时、超限和非法结构；
- Prompt 注入不执行；
- 只读取当前任务；
- Token stage 正确。

### 31.5 场景测试点

- 一个 H3 一个完整批次；
- 不按粗体标签/表格行/Requirement 拆分；
- 多 Requirement 合并为一个场景；
- 角色、前置、路径和结果差异合理拆分；
- pending 建议隔离；
- ID 稳定且唯一；
- 非法引用阻塞；
- 完全重复阻塞；
- 一次补充后停止；
- 覆盖 O(N)。

### 31.6 用例事实保真

- 完整测试点字段进入生成器；
- 锁定字段不能被模型覆盖；
- `preconditions/test_steps/requirement_ids` 为数组；
- `test_data` 可序列化；
- pending 状态保留；
- 只重试失败测试点一次；
- 黄金事实全部保留。

### 31.7 HTTP 与安全

- GET/PUT/import/download/confirm；
- owner/admin/read-only/other user；
- CSRF、RBAC、IDOR 404；
- Idempotency-Key 复用和冲突；
- 错误脱敏；
- Artifact 过期；
- Secret、Prompt、路径不回显。

### 31.8 平台

- 0024 upgrade/downgrade/re-upgrade；
- 配置默认值和 schema；
- dev/prod Release 隔离；
- readiness；
- Compose/Nginx；
- API 智能体安全默认值。

---

## 32. 黄金样本与质量评估

### 32.1 黄金输入

以“新手引导流程需求文档”建立固定夹具，不从用户业务目录直接运行测试；测试副本应脱敏后放入 `tests/fixtures/standard_requirement/`。

### 32.2 旧新对照

记录：

| 指标 | 旧流程 | 新流程 |
|---|---:|---:|
| 标题片段数 | 67 | 不适用 |
| 需求拆解 LLM 调用 | 逐片多次 | 0 |
| 标准整理 LLM 调用 | 无 | 普通文档 1，标准文档 0 |
| 测试点生成调用 | 依原子 seed | H3 功能批次 |
| 覆盖补充轮次 | 多轮可能 | 最多 1 |
| 测试点数量 | 旧基准约 133 | 不设数量目标 |

质量比较不把“数量更少”单独视为成功，必须同时满足：

- confirmed Requirement 覆盖可解释；
- 未确认项不混入正式结果；
- 场景可独立执行；
- 无机械字段级重复；
- 用例保留关键事实。

### 32.3 人工评审表

测试工程师对新旧结果分别评分：

```text
需求事实准确性
场景粒度
重复度
可执行性
覆盖可解释性
Review 修改成本
```

每项 1～5 分；新流程不得在事实准确性和覆盖可解释性上低于旧基准。

---

## 33. 浏览器验收设计

在 1280×800、1440×900、1920×1080 验收：

### 33.1 普通文档

- 新建任务并上传 Markdown；
- 排队和整理阶段真实展示；
- 展示模型、Prompt SHA、规则版本、Token 和耗时；
- 进入需求 Review，不自动生成测试点；
- 原始文件可下载且 SHA 不变。

### 33.2 标准文档快速路径

- 上传合法 FRD-2.0；
- `requirement_normalization.calls=0`；
- 直接进入需求 Review；
- 上传自称 FRD-2.0 但结构有误的文档，零 LLM并可定位修复。

### 33.3 需求 Review

- 编辑、保存、刷新；
- 目录和 Requirement 搜索；
- 错误定位；
- dirty 离开确认；
- 双标签 CAS 冲突与本地副本；
- 版本切换只读；
- 警告确认；
- 队列满后版本保留并可重试。

### 33.4 后续链路

- 场景级测试点生成；
- Requirement 覆盖和缺口定位；
- pending 风险确认；
- 测试点确认后重新排队；
- 测试用例关键事实保留；
- 用例 Review 和发布。

### 33.5 权限与可访问性

- 创建者、其他普通用户、管理员和只读用户；
- 缺 CSRF；
- 键盘操作、焦点、200% 缩放、reduced-motion；
- 状态非纯颜色；
- 网络失败不清空本地编辑；
- 浏览器控制台无未处理异常。

无真实 LLM 凭据时，normalizer 和生成阶段使用 Fake/Mock，真实权限和文件边界不得放宽。

---

## 34. 工作包 SR01～SR18

### SR01：基线冻结与规则对齐

**目标**：建立可重复实施基线，消除 V1.1/V1.2 差异。

**修改/新增**：

```text
test-platform/docs/功能测试智能体需求文档整理规则.md
functional-test-agent/prompts/functional_requirement_rule_v1_2.md
functional-test-agent/tests/fixtures/standard_requirement/*
```

**步骤**：

- [ ] 记录两个仓库 Git 状态和用户修改清单；
- [ ] 使用固定文件清单和 SHA-256 记录历史 `output/`；
- [ ] 再次运行功能智能体 Python/Node 和平台基线；
- [ ] 将规则升级为 V1.2，并补全 FRD-2.0 标识协议；
- [ ] 建立标准、警告、非法和普通输入夹具；
- [ ] 增加规则版本一致性测试。

**完成门槛**：规则、Prompt 资产和夹具一致；既有失败与本期失败分开记录；历史 output 摘要不变。

### SR02：Requirement 文档模型与规范化

**目标**：实现文本 canonicalization、SHA、数据类和容量边界。

**文件**：

```text
services/common/requirement_review.py
tests/services/test_requirement_review_domain.py
```

**步骤**：

- [ ] 先编写换行、SHA、NUL、字节、字符上限失败测试；
- [ ] 定义 issue、validation、index 和 confirmation 模型；
- [ ] 实现 Markdown canonicalization；
- [ ] 运行领域局部测试。

**完成门槛**：相同逻辑正文 SHA 稳定，危险和超限输入被稳定拒绝。

### SR03：FRD-2.0 解析、校验和索引

**目标**：确定性生成 Requirement 索引。

**步骤**：

- [ ] 编写标题、围栏、标识、Requirement、Q/A/C 测试；
- [ ] 实现单遍扫描器；
- [ ] 实现错误/警告分类和 validation SHA；
- [ ] 实现索引 builder 与稳定序列化；
- [ ] 验证 5,000 条 ≤2 秒。

**完成门槛**：黄金 FRD 生成固定 index；重复 ID 阻塞；Review 附录不进入 confirmed 集合。

### SR04：需求草稿与不可变版本事务

**目标**：完成 CAS、原子确认和恢复。

**文件**：

```text
services/common/task_store.py
services/common/requirement_review.py
tests/services/test_requirement_review_domain.py
```

**步骤**：

- [ ] 编写草稿 CAS、相同 SHA、确认 v1/v2 失败测试；
- [ ] 增加原子 bytes 写入/创建；
- [ ] 实现 draft envelope；
- [ ] 实现 index-first、Markdown commit marker 事务；
- [ ] 实现索引恢复和损坏隔离测试。

**完成门槛**：半写入不产生可见版本；确认文件不可覆盖；相同内容幂等。

### SR05：标准检测与 LLM Normalizer

**目标**：普通文档一次整理，标准文档零 LLM。

**文件**：

```text
services/functional_agent/requirement_normalizer.py
agents/functional_test/prompts/normalize_requirement.py
prompts/functional_requirement_rule_v1_2.md
tests/services/test_standard_requirement_flow.py
```

**步骤**：

- [ ] 编写三种 detector 结果测试；
- [ ] 编写 Fake LLM 调用次数测试；
- [ ] 实现封闭 Prompt 与输出提取；
- [ ] 接入 Token 统计和超时；
- [ ] 验证 Prompt 注入不触发工具/HTTP/文件读取。

**完成门槛**：标准有效/无效文档均零 LLM；普通文档恰好一次；非法模型输出稳定失败。

### SR06：TaskManager execution 与状态恢复

**目标**：接入需求整理和测试点生成 execution。

**文件**：

```text
services/common/task_manager.py
services/common/task_store.py
services/common/task_models.py
tests/services/test_task_runtime.py
```

**步骤**：

- [ ] 为新 execution 和状态写失败测试；
- [ ] 扩展 submit 和 `_write_execution()`；
- [ ] 实现 `resume_requirement()`；
- [ ] 增加 waiting_document_review 取消/恢复/保留；
- [ ] 验证 FIFO、队列竞争、迟到结果和重启。

**完成门槛**：确认继续不能绕过 FIFO；队列满不丢确认版本；迟到结果不覆盖。

### SR07：Runner 与阶段化 Adapter

**目标**：打通 normalization → Review → test points。

**文件**：

```text
services/functional_agent/runner.py
services/functional_agent/adapter.py
services/functional_agent/app.py
tests/services/test_standard_requirement_flow.py
```

**步骤**：

- [ ] 为各 kind 的输入/输出写集成测试；
- [ ] 实现 normalize_requirement Runner 分支；
- [ ] 实现 generate_test_points 不可变输入校验；
- [ ] 按 execution kind 收集 Artifact；
- [ ] 验证旧 initial 路径不变。

**完成门槛**：每阶段只发布本阶段产物；需求 source、状态和 Token 正确。

### SR08：Requirement Review API

**目标**：完成五个接口和统一错误协议。

**文件**：

```text
services/common/web.py
services/common/errors.py
tests/services/test_web_routes.py
```

**步骤**：

- [ ] 编写 GET/PUT/import/download/confirm 失败测试；
- [ ] 实现状态、身份、权限、CSRF 和所有权；
- [ ] 实现 Idempotency-Key；
- [ ] 实现固定 kind/version 下载；
- [ ] 加入审计和白名单错误 details。

**完成门槛**：创建者/管理员/只读/越权矩阵通过；冲突不回显正文。

### SR09：需求 Review 工作台

**目标**：提供纯文本在线 Review。

**文件**：

```text
services/common/templates/task_detail.html
services/common/static/requirement-review-workbench.js
services/common/static/requirement-review-workbench.css
services/common/static/agent-workbench.js
tests/ui/requirement-review-workbench.test.mjs
```

**步骤**：

- [ ] 编写 canonical dirty、定位、轮询竞态纯函数测试；
- [ ] 接入三栏工作台和状态；
- [ ] 实现显式保存、导入、下载、确认；
- [ ] 实现 CAS 本地副本；
- [ ] 完成键盘、焦点和 200% 缩放测试。

**完成门槛**：普通用户无需下载文件即可完成需求 Review；网络失败不丢文本。

### SR10：场景级测试点 Prompt 与批次

**目标**：移除新路径的原子 seed 粒度。

**文件**：

```text
agents/functional_test/prompts/generate_scenario_test_points.py
agents/functional_test/prompts/generator_test_point.py
agents/functional_test/workflows/case_generator_workflow.py
tests/functional_test/test_requirement_decomposition_integration.py
```

**步骤**：

- [ ] 编写完整 H3 批次测试；
- [ ] 编写多 Requirement 合并和合理拆分测试；
- [ ] 实现场景 Prompt 和标准入口；
- [ ] 实现规范化与 ID 分配；
- [ ] 断言新路径不调用 decomposition runner。

**完成门槛**：标准需求到测试点无需求拆解调用，不生成字段级机械碎片。

### SR11：覆盖、补充与去重

**目标**：程序覆盖替代 LLM 覆盖判断。

**步骤**：

- [ ] 编写 confirmed/pending 集合测试；
- [ ] 实现 O(N) 覆盖；
- [ ] 实现非法引用和重复检查；
- [ ] 实现一次补充；
- [ ] 验证仍有缺口时停止并进入 Review。

**完成门槛**：覆盖结果可重复；模型不能伪造覆盖；补充调用不超过配置。

### SR12：测试点 Review 追溯集成

**目标**：显示并确认 Requirement 映射。

**文件**：

```text
services/common/review.py
services/common/web.py
services/common/static/review-workbench.js
services/common/static/functional-workbench-v2.mjs
tests/services/test_review_domain.py
tests/services/test_web_routes.py
tests/ui/mindmap-domain.test.mjs
```

**步骤**：

- [ ] 扩展测试点 normalize/validate；
- [ ] 返回 coverage trace；
- [ ] 接入脑图、表格和详情的 Requirement IDs；
- [ ] 增加未覆盖/pending 风险确认；
- [ ] 验证 AI 建议不越过 Requirement 白名单。

**完成门槛**：保存 JSON、脑图、表格、详情和覆盖面板一致。

### SR13：测试用例事实锁定

**目标**：修复测试点到用例事实丢失。

**文件**：

```text
agents/functional_test/prompts/generator_testcase.py
agents/functional_test/workflows/case_generator_workflow.py
tests/functional_test/test_requirement_decomposition_integration.py
tests/services/test_case_review_domain.py
```

**步骤**：

- [ ] 编写黄金事实失败测试；
- [ ] 建立 ConfirmedTestPointInput；
- [ ] 生成锁定 skeleton；
- [ ] 合并模型可编辑字段；
- [ ] 实现按失败测试点单次重试。

**完成门槛**：关键页面、默认值、状态、Requirement 映射和 expected_result 不被改写。

### SR14：公开模型、阶段导航和 Token

**目标**：让平台用户理解每个阶段。

**文件**：

```text
services/common/task_models.py
services/common/templates/task_detail.html
services/common/static/agent-workbench.js
services/common/static/functional-workbench-v2.mjs
tests/services/test_web_routes.py
```

**步骤**：

- [ ] 增加 PublicTaskModel 字段测试；
- [ ] 扩展 8 阶段导航；
- [ ] 展示三类版本和 counts；
- [ ] 展示 normalization/test points/test cases Token；
- [ ] 验证内部字段不泄露。

**完成门槛**：状态、阶段、下一步、版本和 Token 与任务文件一致。

### SR15：平台配置迁移

**目标**：登记配置并保持环境隔离。

**文件**：

```text
test-platform/backend/alembic/versions/20260830_0024_add_standard_requirement_flow.py
test-platform/backend/tests/test_migrations.py
```

**步骤**：

- [ ] 编写 9 个定义的迁移失败测试；
- [ ] 实现 upgrade/downgrade；
- [ ] 验证空库、0023、重复升级、降级和重升；
- [ ] 验证 dev/prod 和 API 智能体隔离。

**完成门槛**：默认总开关 false；无新 Secret；downgrade 不删除无关数据。

### SR16：安全、审计、保留与兼容

**目标**：关闭跨任务、路径、权限和旧流程风险。

**步骤**：

- [ ] Prompt 注入、XSS、路径和容量测试；
- [ ] CSRF/RBAC/所有权/IDOR 测试；
- [ ] 审计脱敏测试；
- [ ] waiting_document_review 保留/取消测试；
- [ ] 旧任务、旧 CLI、旧 multipart 和开关关闭回归。

**完成门槛**：安全矩阵全绿，API 智能体默认值不变，历史 output 摘要不变。

### SR17：全量自动化、性能与黄金样本

**目标**：完成质量门槛。

**步骤**：

- [ ] 运行功能智能体 Python/Node 全量测试；
- [ ] 运行平台后端/前端测试；
- [ ] 运行迁移往返；
- [ ] 运行 Compose/Nginx 检查；
- [ ] 运行 5,000 Requirement 和覆盖性能；
- [ ] 运行新手引导黄金样本并输出新旧对比。

**完成门槛**：本期新增测试全通过；既有无关失败不增加；性能和质量指标达标。

### SR18：本机 dev 发布、浏览器与文档

**目标**：形成可交付版本。

**步骤**：

- [ ] 更新 README、配置、运维和回滚说明；
- [ ] 创建 dev Release 并开启总开关；
- [ ] 仅重建功能智能体；
- [ ] 在本机 8080 完成三种分辨率浏览器验收；
- [ ] 验证关闭开关回退旧流程；
- [ ] 复核 Git diff、用户修改和 output SHA；
- [ ] 输出最终交付报告。

**完成门槛**：新旧路径均可用，关闭开关即时回退，不修改生产和用户历史数据。

---

## 35. 实施阶段与质量门槛

| 阶段 | 工作包 | 阶段结果 |
|---|---|---|
| RR01 基础 | SR01～SR04 | 规则、解析、索引、CAS 和不可变版本完成 |
| RR02 执行链 | SR05～SR08 | 整理、FIFO、Runner、API 完成 |
| RR03 工作台 | SR09、SR14 | 需求 Review 与阶段信息完成 |
| RR04 测试设计 | SR10～SR13 | 场景测试点、覆盖和用例事实保真完成 |
| RR05 平台与安全 | SR15～SR16 | 配置、权限、审计和兼容完成 |
| RR06 验证 | SR17 | 自动化、性能和黄金样本完成 |
| RR07 交付 | SR18 | dev、本机浏览器、回滚和文档完成 |

每个工作包固定执行：

```text
复现/失败测试
→ 最小实现
→ 局部测试
→ 阶段回归
→ 检查用户基线
→ 更新工作包状态
```

不得因普通实现细节或等价方案暂停。只有生产凭据、破坏性迁移、核心文档冲突、用户修改直接冲突或必须突破安全边界时才停止。

---

## 36. 完整验证命令

### 36.1 功能智能体

```bash
cd /Users/admin/Testproject/functional-test-agent
./.venv/bin/python -m pytest -q
node --test tests/ui/*.test.mjs
```

### 36.2 平台

```bash
cd /Users/admin/Testproject/test-platform
backend/.venv/bin/python -m pytest -q backend/tests

cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run
npm run build
npm audit --audit-level=high
```

### 36.3 配置与网关

```bash
cd /Users/admin/Testproject/test-platform
docker compose config --quiet
docker compose exec -T platform-gateway nginx -t
```

### 36.4 迁移

在隔离 PostgreSQL 中执行：

```bash
alembic upgrade head
alembic upgrade head
alembic downgrade 20260828_0023
alembic upgrade head
```

不得为了迁移测试修改本机生产等价库或读取生产 Secret。

---

## 37. dev 发布顺序

1. 冻结 Git 状态、测试基线和 output 摘要；
2. 完成 SR01～SR17；
3. 在隔离数据库验证 0024 往返；
4. 升级本地 dev 数据库；
5. 构建功能智能体镜像并以非 root 用户检查；
6. 保持总开关 false，验证旧流程；
7. 创建 dev Release 并开启新流程；
8. 只替换 `functional-test-agent` 容器；
9. 验证标准和非标准文档；
10. 验证三层 Review、覆盖、用例事实和产物；
11. 验证 API 智能体与平台其他工具不受影响；
12. 关闭总开关演练回退，再恢复 dev 开关；
13. 执行最终回归和 output SHA 复核。

prod 首次发布总开关保持 false；生产启用需单独评审和授权。

---

## 38. 回滚设计

### 38.1 首选回滚

```text
STANDARD_REQUIREMENT_FLOW_ENABLED=false
```

新任务立即恢复当前稳定流程；已有需求 Review 任务保留文件和只读访问。

### 38.2 镜像回滚

恢复上一功能智能体镜像，保留任务卷。旧镜像不能处理 `waiting_document_review` 时，应在回滚前：

- 暂停创建新标准流程任务；
- 保留任务文件；
- 通过当前版本完成或取消非终态需求 Review；
- 不手工改写任务状态。

### 38.3 数据库回滚

通常保留 0024。确需 downgrade 时：

1. 先关闭总开关；
2. 确认 active dev Release 不再依赖配置定义；
3. 降级到 0023；
4. 不删除任务、草稿、确认版本、索引、测试点、用例、产物或审计。

---

## 39. 风险与缓解

| 风险 | 表现 | 缓解 |
|---|---|---|
| 规则版本漂移 | 快速路径误判 | SR01 对齐、版本测试、Prompt SHA |
| 整理模型编造事实 | 错误 Requirement | 事实边界、人工 Review、Review 附录 |
| Markdown 解析歧义 | 索引不稳定 | 受限语法、围栏保护、黄金夹具 |
| H3 过大 | 超出模型上下文 | 不截断，稳定报错并提示拆分功能 |
| 测试点过度合并 | 缺陷难定位 | 明确拆分规则、人工 Review、覆盖映射 |
| 测试点仍过细 | Review 成本高 | 场景 Prompt、禁止数量驱动、相似提示 |
| Requirement 映射错误 | 覆盖失真 | ID 白名单、确定性校验、不可伪造覆盖 |
| 确认与入队分离 | 版本确认但未执行 | 明确可重试状态、幂等、队列满提示 |
| 多阶段 work 残留 | 重复 Artifact | stage-scoped collector |
| 新旧分支交叉 | 旧 CLI 回归 | 显式 execution kind 和总开关 |
| 当前工作区既有失败 | 难以判定回归 | 基线记录、只修本期新增失败 |
| 平台迁移链变化 | down_revision 冲突 | 实施前重新读取 head，仅调整链 |

---

## 40. 与 PRD 的设计细化和差异

1. PRD 未明确 FRD-2.0 无效上传的处理。设计选择“零 LLM进入需求 Review 修复”，避免重新改写用户已整理内容；确认仍受硬错误阻止。
2. PRD 未明确快速路径是否占队列。设计选择短暂执行 `normalize_requirement`，但模型调用为零，以复用任务事务和恢复逻辑。
3. PRD 文件列表未定义需求确认的双文件提交标记。设计使用 index-first、confirmed Markdown 作为 commit marker。
4. PRD 未给出单 H3 上下文边界。设计固定 120,000 字符，超限稳定失败，不静默截断。
5. PRD 未规定配置迁移编号。根据 2026-08-30 当前 head 0023，建议使用 0024；实施前重新核对。
6. PRD 的规则基线是 V1.2，但仓库副本仍为 V1.1。SR01 必须先完成对齐。
7. PRD 未要求新增需求 Review AI，本设计不增加该能力。
8. PRD 未要求调整旧 CLI，本设计用显式平台分支保持其默认语义。

这些细化不改变 PRD 的产品目标、安全边界或兼容决策。

---

## 41. 开发设计评审确认项

本设计采用 PRD 第 32 章全部推荐项，并补充以下实施确认：

1. FRD-2.0 无效上传不调用 LLM，进入可编辑需求 Review，由硬错误阻止确认。
2. 标准快速路径仍进入同一 FIFO 的轻量 `normalize_requirement` execution，LLM 调用为零。
3. 单个完整 H3 上下文上限为 120,000 字符，超限不拆碎、不截断。
4. 需求确认版本使用 index-first、confirmed Markdown commit marker 的双文件事务。
5. 平台迁移仅登记定义；dev 开关通过单独 Release 开启，prod 不开启。
6. `generate_test_cases + document` 在新 Web 流程中走完整三层 Review；测试点 JSON 高级输入继续直达用例生成。
7. 需求 Review MVP 使用原生 textarea，不增加 Markdown 预览和第三方编辑器。
8. 新流程不增加需求 Review AI。
9. 新增错误码 `REQUIREMENT_CONTEXT_TOO_LARGE`、`REQUIREMENT_INDEX_INVALID` 和 `REQUIREMENT_CONFIRMATION_CONFLICT`。
10. 当前平台后端既有角色测试失败作为外部基线处理，不纳入本功能顺便修复。

---

## 42. 完成定义

- [ ] SR01～SR18、RR01～RR07 全部完成；
- [ ] 规则副本、运行时 Prompt 与 FRD-2.0 契约一致；
- [ ] 普通需求可整理并停留需求 Review；
- [ ] 标准需求零 LLM进入需求 Review；
- [ ] 未确认需求不能生成测试点；
- [ ] 新主流程不调用旧需求拆解 pipeline；
- [ ] 场景级测试点支持多 Requirement 映射；
- [ ] 覆盖由程序确定性计算；
- [ ] 补充最多一次；
- [ ] pending 不计正式覆盖；
- [ ] 测试点完整事实进入用例生成；
- [ ] 黄金事实和 JSON 类型测试通过；
- [ ] 需求、测试点、用例三层 CAS 和不可变版本通过；
- [ ] FIFO、队列满、取消、超时、恢复和迟到结果通过；
- [ ] 身份、CSRF、RBAC、所有权、IDOR 和审计脱敏通过；
- [ ] 0024 往返迁移通过；
- [ ] dev 开关、关闭回退和故障隔离通过；
- [ ] 旧任务、旧 CLI、现有 Review 和 API 智能体无回归；
- [ ] 历史 output 和用户已有修改未被覆盖、删除或写入；
- [ ] README、部署、运维、回滚和最终交付报告完整。

---

## 43. 修订记录

| 版本 | 日期 | 修订内容 |
|---|---|---|
| V1.0 | 2026-08-30 | 首版；基于 PRD V1.0 完成标准需求检测、需求 Review、Requirement 索引、场景级测试点、确定性覆盖、用例事实契约、API、UI、迁移、测试、发布和 SR01～SR18 计划。 |
