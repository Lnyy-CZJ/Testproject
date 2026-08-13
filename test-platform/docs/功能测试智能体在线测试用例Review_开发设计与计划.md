# 功能测试智能体在线测试用例 Review 与 AI 辅助 Review 开发设计与计划

> 文档版本：V1.0  
> 创建日期：2026-08-13  
> 文档状态：待开发评审  
> 需求基线：`test-platform/docs/功能测试智能体在线测试用例Review_PRD.md` V1.1  
> 适用服务：`functional-test-agent`  
> 推荐入口：`/functional-test-agent/tasks/{task_id}#case-review`  
> 技术栈：Flask 3 + Jinja + 原生 JavaScript/CSS + 文件任务存储 + 持久化 FIFO + LangChain/OpenAI 兼容模型  
> 设计定位：复用已上线测试点 Review 的事务与执行能力，新增测试用例领域策略、列表 + 详情工作台和最终 JSON/XLSX 同源发布

关联文档：

- `test-platform/docs/AI测试智能体独立接入PRD.md`；
- `test-platform/docs/AI测试智能体独立接入开发设计与计划.md`；
- `test-platform/docs/功能测试智能体在线测试点Review_PRD.md`；
- `test-platform/docs/功能测试智能体在线测试点Review_开发设计与计划.md`；
- `test-platform/docs/功能测试智能体在线测试用例Review_PRD.md`。

---

## 1. 文档目的

本文档把已评审的测试用例在线 Review PRD 转换为可直接编码、测试、部署和回滚的详细开发设计。

本期交付两组能力：

1. 在线人工用例 Review：列表 + 详情编辑、步骤与测试数据编辑、覆盖校验、草稿 CAS、不可变确认版本和 JSON/XLSX 同源发布；
2. AI 辅助用例 Review：补充用例、改写选中用例、按说明生成建议，以及建议差异、人工应用、取消、超时和恢复。

设计必须保持：

- JSON 是测试用例权威数据；
- XLSX 只由确认 JSON 派生；
- 模型原稿、草稿、AI 建议和确认版本隔离；
- AI 只生成建议，不自动修改草稿或确认；
- 不新增测试用例业务数据库表；
- 不新增服务、队列或前端框架；
- 不修改原测试点/用例生成 Prompt 语义；
- 不修改原 CLI 和历史 `AItestcase_Agents/output/`；
- 不改变 API 智能体安全默认值。

---

## 2. 需求理解与技术成功标准

### 2.1 需求理解

测试点 Review 确认后，功能智能体继续生成测试用例。开启本期功能时，生成完成不再直接把任务提交为成功，而是发布模型用例原稿并进入 `waiting_case_review`。用户在同一任务页面编辑用例、保存草稿、请求 AI 建议并最终确认。最终确认只执行确定性 JSON/XLSX 发布，不再次调用模型。

### 2.2 技术成功标准

开发完成必须满足：

1. 原测试点 Review 全部行为与接口兼容；
2. `generate_test_cases/full_pipeline` 生成用例后按开关进入 `waiting_case_review`；
3. 旧任务和开关关闭时仍保持生成后直接成功；
4. 用例原稿只从 artifact registry 的 `test_cases_json` 读取；
5. 草稿 revision/SHA 冲突不会覆盖服务端新版本；
6. 步骤、前置条件和测试数据兼容现有历史类型；
7. 每个确认测试点至少存在一条用例；
8. 确认 JSON 与最终 XLSX 来源完全一致；
9. AI 三种操作输出严格结构化建议；
10. AI 改写保持 `case_id/test_point_id` 且不得降低优先级；
11. AI 失败、取消、超时和重启返回 `waiting_case_review`；
12. AI 与现有任务共享单槽 FIFO；
13. 所有写请求通过身份、所有权、RBAC、状态和 CSRF 校验；
14. 普通响应不泄露 Prompt 全文、Secret、路径或异常堆栈；
15. 1280×800 与 1440×900 关键流程通过；
16. 两项目完整回归通过；
17. 关闭两个用例 Review 开关可恢复旧流程。

### 2.3 交付物

- 公共版本化 Review 文件内核；
- 测试点 Review 兼容包装和回归；
- 测试用例模型、规范化、校验、覆盖和 diff；
- 用例草稿、确认版本和最终发布服务；
- 用例 Review GET/PUT/import/download/confirm API；
- 用例 AI request/get/cancel API；
- `case_review_ai` execution kind、Runner 和恢复行为；
- 独立测试用例 AI Prompt；
- Jinja 用例 Review 页面与原生 JavaScript/CSS；
- Alembic `20260814_0012`；
- 自动化、浏览器、部署和回滚文档。

### 2.4 非交付范围

- 多人实时协同和评论；
- 测试用例数据库资产库；
- 在线执行、实际结果和缺陷编辑；
- XMind/Excel 原样编辑；
- SPA、WebSocket、SSE；
- 开放式聊天；
- AI 自动应用或确认；
- 移动端；
- 向量语义去重。

---

## 3. 当前实现评估

### 3.1 当前已具备的能力

| 能力 | 当前实现 | 本期处理 |
|---|---|---|
| 测试点 Review 模型与事务 | `services/common/review.py` | 抽取版本化文件内核，保留兼容 API |
| Review Web API | `services/common/web.py` | 增加独立 `case-review` 路由 |
| 测试点 AI | `services/functional_agent/review_ai.py` | 复用请求/建议模式，新增用例 Adapter |
| 单槽 FIFO | `services/common/task_manager.py` | 增加 `case_review_ai` 分派和恢复目标 |
| execution sequence | `execution.json` | 继续隔离迟到结果 |
| 产物发布 | `services/common/artifacts.py` | 增加版本组发布与 registry 事务 |
| 功能 Runner | `services/functional_agent/runner.py` | 用例生成后按开关进入 Review |
| 功能 Adapter | `services/functional_agent/adapter.py` | 保存 `case_review_source` |
| 任务状态模型 | `services/common/task_models.py` | 已包含 `waiting_case_review` |
| 页面与 token | 公共 Jinja/JS/CSS | 复用视觉 token，新增用例工作台资源 |
| 平台配置目录 | 0010 已有测试点 Review 配置 | 新增 0012 用例 Review 定义 |

### 3.2 当前差距

1. `review.py` 将测试点字段、文件名和事务混在同一模块，不能直接安全复用；
2. Runner 当前生成用例后固定返回 `succeeded`；
3. Adapter 虽发布 `test_cases_json/xlsx`，但没有 Review 原稿索引；
4. `TaskManager` 只识别 `review_ai` 的可恢复语义；
5. `PublicTaskModel` 没有 `case_review_*` 白名单字段；
6. 没有用例字段兼容、引用和覆盖校验；
7. 没有从确认 JSON 确定性重建 XLSX 的服务；
8. 页面只实现测试点表格，不适合嵌套用例字段；
9. 当前 AI Prompt 和建议 Schema 只支持测试点；
10. 平台没有用例 Review 配置定义。

### 3.3 已知兼容问题

当前 `TestCaseModel` 类型声明与 Prompt 实际输出存在历史差异：

- 模型声明中的 `preconditions/test_steps/test_data` 为字符串；
- Prompt 示例输出分别为数组、数组和对象；
- 历史产物可能同时存在字符串、数组和对象。

本期不强制修改原生成工作流模型，以免改变 CLI 或 Prompt 解析。用例 Review 在加载边界做兼容规范化，确认版本统一为 PRD V1.1 Schema。

---

## 4. 方案选择

### 4.1 公共复用：抽取版本化文件事务，不泛化业务校验

新增 `services/common/versioned_review.py`：

- 负责 artifact 原稿定位；
- 草稿信封、revision/SHA CAS；
- 不可变确认版本；
- 文件 SHA 和原子写入；
- 索引丢失恢复；
- containment 和固定文件名策略。

测试点和测试用例分别保留业务 policy：

```text
versioned_review.py       # 文件与版本事务
review.py                 # 测试点 parse/normalize/validate/diff + 兼容 ReviewService
case_review.py            # 测试用例 parse/normalize/validate/coverage/diff
```

不把所有规则塞入复杂继承体系。公共内核通过小型 `ReviewResourceSpec` 配置文件名和 artifact 类型，通过回调接收 parse/normalize/validate/diff。

### 4.2 前端：列表 + 详情，不复制测试点超宽表格

继续 Flask + Jinja + 原生 JavaScript/CSS，无新依赖。

界面拆为：

```text
摘要/覆盖
筛选与 AI 工具栏
┌──────────── 用例列表 ────────────┐
│ TC001  TP001  名称  P1  3步 ... │
└─────────────────────────────────┘
┌──────────── 当前用例详情 ────────┐
│ 基本字段 / 前置条件 / 步骤 / 数据 │
└─────────────────────────────────┘
AI 建议差异
固定操作栏
```

列表最多渲染当前页 100 行，详情只渲染一个用例。

### 4.3 最终发布：确认 JSON 为唯一输入

新增 `CaseReviewPublisher`：

1. 读取不可变确认 JSON；
2. 在临时版本目录写 JSON；
3. 使用 `openpyxl` 从同一内存对象写 XLSX；
4. `fsync` 文件；
5. 原子发布版本目录；
6. 生成 artifact metadata；
7. 最后合并 registry 和任务终态。

不复用模型生成阶段的旧 XLSX，因为用户可能已经修改用例。

### 4.4 AI：独立 Adapter 和 Prompt

新增 `case_review_ai.py`，复用测试点 AI 的：

- 不可变 request/suggestion 文件；
- Idempotency-Key；
- 安全 JSON 修复一次；
- 上下文限制；
- 模型和 Prompt SHA；
- 建议默认不应用。

不在 `review_ai.py` 中增加大量 `if resource_type`，防止测试点规则和用例规则相互污染。

### 4.5 状态：复用 `waiting_case_review`

该状态已在公共模型中存在，无需新增主状态。功能服务通过 stage 区分：

- `case_review_editing`；
- `case_review_ai_queued`；
- `case_review_ai_running`；
- `case_review_ai_ready`；
- `case_review_ai_failed`；
- `case_review_ai_cancelled`；
- `case_review_publishing`；
- `case_review_confirmed`。

---

## 5. 目标架构

### 5.1 组件关系

```text
Browser
  │
  ▼
Nginx auth_request
  │ trusted identity / RBAC
  ▼
Functional Flask App
  ├── CaseReviewService
  │    ├── VersionedReviewStore
  │    ├── CaseReviewPolicy
  │    └── ConfirmedPointResolver
  ├── CaseReviewPublisher
  ├── TaskManager
  └── PlatformClient / Audit
          │
          ├── PUT draft / confirm（本地确定性事务）
          │
          └── execution.kind=case_review_ai
                       │
                       ▼
              Functional Runner subprocess
                       │
                       ▼
               CaseReviewAIAdapter → LLM
```

### 5.2 生成到人工 Review

```text
Runner 生成 testcases JSON/XLSX
  → Adapter 发布 generated artifacts
  → ONLINE_CASE_REVIEW_ENABLED?
       false → succeeded/completed
       true  → waiting_case_review/case_review_editing
  → GET case-review
  → revision 0（原稿）
```

### 5.3 人工确认

```text
浏览器修改
  → PUT case-review-draft（CAS）
  → case-review-draft.json
  → POST case-review/confirm
  → 完整校验 + 警告确认
  → review-test-cases-vN.json
  → CaseReviewPublisher
  → final JSON/XLSX
  → registry merge
  → succeeded/case_review_confirmed
```

### 5.4 AI Review

```text
已保存草稿 revision/SHA
  → POST case-review-ai
  → request-vN.json
  → pending/case_review_ai_queued
  → running/case_review_ai_running
  → suggestions-vN.json
  → waiting_case_review/case_review_ai_ready
  → 人工应用到浏览器
  → PUT draft
```

### 5.5 故障边界

| 故障 | 结果 |
|---|---|
| 草稿临时文件写失败 | 旧草稿继续有效 |
| 草稿发布后 task 索引失败 | GET 从信封恢复索引 |
| 确认文件发布后索引失败 | 相同 SHA 扫描固定确认文件并恢复 |
| XLSX 生成失败 | 保持 `waiting_case_review`，不登记半成品 |
| registry 保存失败 | 已发布版本保留，重试按 SHA 恢复 |
| AI 失败/超时/取消 | 返回 `waiting_case_review` |
| AI 建议基准过期 | 禁止应用 |
| 服务重启中断 AI | `case_review_ai` 恢复为失败并返回 Review |
| 迟到 Runner | execution sequence 不匹配，丢弃 |

---

## 6. 文件影响设计

### 6.1 `AItestcase_Agents` 新增

```text
services/common/versioned_review.py
services/common/case_review.py
services/functional_agent/case_review_ai.py
services/functional_agent/case_review_publisher.py
agents/functional_test/prompts/review_test_cases.py
services/common/static/case-review-workbench.js
services/common/static/case-review-workbench.css
tests/services/test_versioned_review.py
tests/services/test_case_review_domain.py
tests/services/test_case_review_ai.py
tests/services/test_case_review_publish.py
```

### 6.2 `AItestcase_Agents` 修改

```text
services/common/review.py
services/common/web.py
services/common/task_manager.py
services/common/task_models.py
services/common/artifacts.py（仅在需要版本组发布帮助函数时）
services/functional_agent/runner.py
services/functional_agent/adapter.py
services/common/templates/task_detail.html
services/common/templates/base.html
services/common/static/agent-workbench.js
tests/services/test_review_domain.py
tests/services/test_review_ai.py
tests/services/test_task_runtime.py
tests/services/test_web_routes.py
tests/services/fake_runner.py
```

### 6.3 `test-platform` 新增

```text
backend/alembic/versions/20260814_0012_add_case_review_config.py
```

### 6.4 `test-platform` 修改

```text
backend/tests/test_migrations.py
backend/tests/test_phase2.py（如权限映射合同需要补充）
README.md
```

Nginx 和 Compose 原则上不修改。只有自动化证明现有 6 MiB 网关限制无法满足已确认导入范围时，才提交最小配置变更；PRD 已建议导入仍限制 5 MiB，因此默认无需调整。

### 6.5 明确不修改

- 既有测试点、用例和需求拆解 Prompt；
- 原 CLI 参数和默认路径；
- `AItestcase_Agents/output/`；
- API 智能体执行、数据库和目标网络配置；
- 平台主 React 架构和工具卡片；
- Secret 加密、Session 和身份体系。

---

## 7. 公共 VersionedReviewStore 设计

### 7.1 资源配置

```python
@dataclass(frozen=True)
class ReviewResourceSpec:
    resource_type: Literal["test_points", "test_cases"]
    artifact_type: str
    envelope_key: str
    draft_filename: str
    confirmed_pattern: str
    task_draft_key: str
    task_confirmed_key: str
```

实例：

```text
test_points:
  artifact_type=test_points_json
  envelope_key=test_points
  draft_filename=review-draft.json
  confirmed_pattern=review-test-points-v{version}.json

test_cases:
  artifact_type=test_cases_json
  envelope_key=test_cases
  draft_filename=case-review-draft.json
  confirmed_pattern=review-test-cases-v{version}.json
```

### 7.2 公共接口

```python
class VersionedReviewStore:
    def load_original(task_id) -> OriginalReview
    def load_draft_envelope(task_id) -> dict | None
    def save_draft(task_id, envelope, expected_revision, expected_sha) -> None
    def find_confirmed_by_sha(task_id, sha256) -> ConfirmedVersion | None
    def create_confirmed(task_id, payload, sha256) -> ConfirmedVersion
    def read_confirmed(task_id, version) -> list[Any]
```

业务 Service 负责：parse、normalize、validate 和 task 元数据内容；公共 Store 不知道测试点或用例字段。

### 7.3 兼容包装

现有 `ReviewService` 的方法签名保持：

```text
original_points
load
save_draft
confirm
_atomic_create
```

内部改为调用 `VersionedReviewStore`。现有 Web API、测试和文件名不变化。

### 7.4 锁和原子性

- 所有 CAS 在 `TaskStore.locked()` 内重新读取；
- 临时文件必须位于目标同目录；
- 写入后 flush + `fsync`；
- 可变草稿用 `os.replace`；
- 不可变确认用硬链接或 `O_EXCL` 语义；
- 所有路径由固定 spec 生成，不接收浏览器路径；
- task 目录 containment 和 symlink 拒绝继续有效。

### 7.5 损坏恢复

- 草稿信封 SHA 与正文 SHA 不一致：500 `STORAGE_WRITE_FAILED`；
- 确认索引缺失：扫描固定 `review-test-*-vN.json` 文件名并按内容 SHA 恢复；
- 任意文件名和任意目录不扫描；
- 损坏确认文件不覆盖，跳过并记录脱敏错误；
- 原始 artifact 不存在或过期：404/410。

---

## 8. 测试用例领域模型

### 8.1 Pydantic 模型

```python
class TestCaseReviewItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    case_id: str = ""
    test_point_id: str = ""
    module: str = ""
    feature: str = ""
    scenario: str = ""
    case_name: str = ""
    priority: str = ""
    preconditions: list[str] = Field(default_factory=list)
    test_steps: list[str] = Field(default_factory=list)
    test_data: dict | list | str = Field(default_factory=dict)
    expected_result: str = ""
    actual_result: str = ""
```

为允许保存业务错误，解析入口不能直接用严格 Pydantic 拒绝全部请求；先做兼容 normalize，再由权威 validator 产生可定位问题。

### 8.2 校验问题

扩展现有 `ValidationIssue`：

```python
class ValidationIssue(BaseModel):
    level: Literal["error", "warning"]
    code: str
    message: str
    row_index: int | None
    case_id: str | None
    test_point_id: str | None
    field: str | None
    item_index: int | None       # preconditions/test_steps 子项
    related_rows: list[int]
```

测试点兼容响应中不返回无值的新字段或由白名单过滤。

### 8.3 校验结果

```python
class CaseReviewValidation(BaseModel):
    valid_for_confirm: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    coverage: CoverageSummary

class CoverageSummary(BaseModel):
    confirmed_test_points: int
    covered_test_points: int
    uncovered_test_points: int
    uncovered_ids: list[str]
```

### 8.4 草稿响应

```python
class CaseReviewPayload(BaseModel):
    task_id: str
    editable: bool
    source: Literal["generated", "draft", "confirmed"]
    revision: int
    sha256: str
    cases: list[dict]
    test_points: list[dict]      # 仅摘要字段
    validation: CaseReviewValidation
    diff_summary: dict
    case_review_ai: dict
```

### 8.5 扩展字段

- 未识别字段原样往返；
- 客户端 `_rowKey/_uiState` 等以下划线开头字段拒绝保存；
- 页面仅编辑标准字段；
- 扩展字段在详情中只读显示 JSON 摘要；
- AI 建议不得新增未知顶层字段，除非该字段已存在于目标用例且为 replace 往返。

---

## 9. 规范化设计

### 9.1 顶层解析

接受：

```json
[]
{"test_cases": []}
{"cases": []}
```

其他结构返回 `CASE_REVIEW_FILE_INVALID`。

### 9.2 文本字段

- 标准文本去除首尾空白；
- 不改变内部换行、大小写和中文标点；
- NUL 拒绝；
- 比较时折叠连续空白并 `casefold`；
- 用户正文保存时不应用比较规范化。

### 9.3 前置条件

```text
list[str] → 去每项首尾空白，保留顺序
str       → 空字符串变 []，多行按非空行拆分
null      → []
其他类型  → 保留原值给 validator 标记 FIELD_TYPE_INVALID
```

### 9.4 测试步骤

```text
list[str] → 去每项首尾空白，保留顺序
str       → 按换行拆分，并只移除展示编号前缀
null      → []
```

只移除明确的 `1.`、`1、`、`1)` 前缀，不改正文。确认 JSON 统一保存无编号字符串数组，XLSX 导出时重新编号。

### 9.5 测试数据

- dict/list 保持结构并使用稳定 JSON；
- str 保持纯文本，不猜测执行；
- 页面 JSON 模式提交 dict/list；
- 页面纯文本模式提交 str；
- 不对 `${variable}`、模板或代码做插值；
- 深度超过 20 或节点数超过 5,000 阻塞，防止解析消耗攻击。

### 9.6 `actual_result`

- 缺失补 `""`；
- 非字符串标记错误；
- 页面只读；
- AI replace 必须复制原值；
- 非空形成警告但不清空。

---

## 10. 校验、覆盖与 Diff

### 10.1 阻塞校验

实现 PRD 第 10.1 节全部规则，稳定错误码建议：

```text
CASES_EMPTY
CASES_LIMIT_EXCEEDED
CASE_NOT_OBJECT
CASE_ID_REQUIRED
CASE_ID_DUPLICATE
CASE_REFERENCE_REQUIRED
CASE_REFERENCE_INVALID
CASE_FIELD_REQUIRED
CASE_FIELD_TOO_LONG
CASE_PRIORITY_INVALID
CASE_PRECONDITION_INVALID
CASE_STEP_REQUIRED
CASE_STEP_INVALID
CASE_DATA_INVALID
CASE_EXPECTED_RESULT_REQUIRED
CASE_EXACT_DUPLICATE
CASE_TEST_POINT_UNCOVERED
CASE_REVIEW_SIZE_EXCEEDED
CLIENT_PRIVATE_FIELD
TEXT_CONTAINS_NUL
```

### 10.2 警告

```text
CASE_ID_NON_STANDARD
CASE_NAME_REUSED
CASE_NAME_TOO_SHORT
CASE_EXPECTED_RESULT_TOO_SHORT
CASE_PRIORITY_LOWER_THAN_POINT
CASE_CONTEXT_DIFFERS_FROM_POINT
CASE_ACTUAL_RESULT_PRESENT
CASE_DELETE_RATIO_HIGH
CASE_ADD_RATIO_HIGH
```

### 10.3 确认测试点解析

`ConfirmedPointResolver` 只读取：

1. `task.json.review.relative_path` 指向的确认测试点文件；
2. 路径 containment；
3. SHA 与 `task.json.review.sha256` 一致；
4. 测试点 ID 唯一且非空。

不存在确认测试点时，用例 Review 不可进入编辑状态，返回 `CASE_REVIEW_POINT_BASE_MISSING`。不得回退到未确认模型测试点。

### 10.4 完全重复索引

规范化指纹：

```python
(
  test_point_id,
  normalized(case_name),
  tuple(normalized(preconditions)),
  tuple(normalized(test_steps)),
  canonical(test_data),
  normalized(expected_result),
)
```

使用 `defaultdict[fingerprint, list[index]]`，O(n)。

### 10.5 覆盖

```python
point_ids = set(confirmed_points)
referenced = {case.test_point_id for valid case}
uncovered = point_ids - referenced
invalid = referenced - point_ids
```

两者均为阻塞；响应 `uncovered_ids` 最多返回 500 个 ID，超过时返回数量和前 500 个，避免响应放大。

### 10.6 Diff

以 `case_id` 为主键：

```text
added
modified
deleted
unchanged
priority_changed
reference_changed
steps_changed
```

不存在/重复 ID 的行仍由校验定位，不参与可靠 diff 映射。

### 10.7 性能

- 一次规范化；
- 构建 ID/重复/引用索引共用遍历；
- 不在双层循环中比较用例；
- 2,000 条目标 ≤ 2 秒；
- 测试必须记录 100/500/2,000 三档耗时，但不把环境波动写成脆弱单元断言。

---

## 11. 文件与一致性设计

### 11.1 目录

```text
input/
├── review-test-points-vN.json
├── case-review-draft.json
├── review-test-cases-vN.json
└── case-review-ai/
    ├── request-vN.json
    └── suggestions-vN.json
published/
├── test-cases/
│   ├── generated.json
│   └── generated.xlsx
└── final-test-cases/
    └── vN/
        ├── test-cases.json
        └── test-cases.xlsx
```

### 11.2 草稿写入顺序

1. TaskStore 锁内读取当前草稿；
2. 比较 revision/SHA；
3. 规范化、校验和计算 SHA；
4. 同 SHA 且已有草稿时直接返回；
5. 构造自描述信封；
6. 原子替换 `case-review-draft.json`；
7. 更新 `task.json.case_review_draft`；
8. 索引失败不回滚正文，后续 GET 修复。

### 11.3 确认写入顺序

1. 锁内重新 load 草稿；
2. CAS；
3. 重新读取确认测试点；
4. 完整校验；
5. 检查警告确认；
6. 搜索同 SHA 确认版本；
7. 不存在则不可变发布 `review-test-cases-vN.json`；
8. 返回 metadata；
9. 进入最终发布步骤。

### 11.4 草稿信封

```json
{
  "schema_version": 1,
  "resource_type": "test_cases",
  "revision": 4,
  "content_sha256": "...",
  "base_generated_sha256": "...",
  "test_point_review_version": 2,
  "test_point_review_sha256": "...",
  "saved_by_user_id": "usr_xxx",
  "saved_by_username": "tester",
  "saved_at": "...",
  "test_cases": []
}
```

### 11.5 确认版本

确认文件正文只保存规范化用例数组，不包信封，保持与 Runner/下载消费者兼容。元数据保存在 `task.json.case_review`。

### 11.6 旧任务

- 只有 `test_cases_json` artifact 且任务已成功：只读查看，不反向改状态；
- 新功能发布后仍在 `waiting_case_review` 的任务：从 artifact 初始化 revision 0；
- 没有确认测试点文件的旧任务：不允许编辑，保留原 artifact 下载；
- 不批量迁移历史任务文件。

---

## 12. 最终 JSON/XLSX 发布设计

### 12.1 Publisher 接口

```python
class CaseReviewPublisher:
    def publish(
        self,
        task_id: str,
        confirmed_version: int,
        confirmed_sha256: str,
    ) -> PublishResult:
        ...
```

### 12.2 临时目录

```text
published/final-test-cases/.vN.<random>.tmp/
```

在临时目录完成两个文件后再原子重命名为 `vN`。目标存在时读取 manifest/SHA 判断是否为同一发布；同版本不同内容视为存储错误，不能覆盖。

### 12.3 JSON

- UTF-8；
- `ensure_ascii=false`；
- 2 空格缩进；
- 内容来自确认文件解析后的规范化列表；
- 发布 JSON 内容 SHA 与确认内容 SHA 的计算口径分别记录：正文规范化 SHA 和文件字节 SHA。

### 12.4 XLSX

继续使用现有 `openpyxl`，不新增 pandas 依赖要求。列顺序固定：

```text
case_id
test_point_id
module
feature
scenario
case_name
priority
preconditions
test_steps
test_data
expected_result
actual_result
```

序列化规则：

- 前置条件：换行连接；
- 测试步骤：重新编号后换行连接；
- 测试数据对象/数组：稳定 JSON 字符串；
- 纯文本：原样；
- 启用换行、顶部对齐、冻结首行和自动筛选；
- 禁止把以 `= + - @` 开头的用户文本作为公式，写入前加安全前缀或显式字符串类型；
- 不使用宏。

### 12.5 Artifact

类型：

```text
final_test_cases_json
final_test_cases_xlsx
```

stage：`case_review_confirmed`。metadata 增加可选展示字段：

```json
{
  "review_version": 1,
  "source_content_sha256": "..."
}
```

若不扩展 `ArtifactModel`，字段放入 `task.json.case_review.published_artifact_ids`，artifact 仍用现有模型。

### 12.6 提交顺序

1. 发布目录；
2. 生成两个 artifact metadata；
3. 合并 registry；
4. 锁内重新读取任务；
5. 若仍为 `waiting_case_review` 且 SHA 相同，提交 `succeeded`；
6. 若已取消/终态，保留文件但不覆盖终态；
7. 重试按确认 SHA 和版本复用文件。

### 12.7 请求超时

同步确认目标时间 ≤ 30 秒。自动化构造 2,000 条、10 MiB 上限数据验证。若超时门槛不满足，不在开发中临时放宽 Nginx；按 PRD 已确认降级为同一 FIFO 的 `publish_test_cases`，并记录设计差异。

---

## 13. 状态机、TaskManager 与 FIFO

### 13.1 Execution kind

新增：

```text
case_review_ai
```

现有：

```text
initial
review_ai
generate_cases
```

### 13.2 执行信封

```json
{
  "schema_version": 1,
  "sequence": 5,
  "kind": "case_review_ai",
  "queued_at": "...",
  "review_version": null,
  "review_ai_request_version": null,
  "case_review_ai_request_version": 2
}
```

### 13.3 TaskManager 新接口

```python
enqueue_case_review_ai(task_id, metadata, max_waiting)
cancel_case_review_ai(task_id)
complete_case_review(task_id, metadata, artifacts)
```

`complete_case_review` 不进入调度线程，只在锁内提交首次合法终态。

### 13.4 队列

- `case_review_ai` 计入 pending 上限；
- FIFO 继续 `queued_at + task_id`；
- 测试点 AI 与用例 AI 竞争最后一个队列位时只能一个成功；
- 用例最终确认同步发布不占 FIFO；
- AI 请求期间任务不能同时最终确认；
- 最终确认期间通过状态/锁阻止发起 AI。

### 13.5 运行状态

调度开始：

```text
kind=case_review_ai
status=running
stage=case_review_ai_running
```

超时使用 `CASE_REVIEW_AI_TIMEOUT_SECONDS`，其他 execution 不受影响。

### 13.6 返回 Review

把 `_return_to_review` 泛化为：

```python
_return_from_ai(record, resource="test_points" | "test_cases", ...)
```

资源决定：

```text
test_points → waiting_review + review_ai
test_cases  → waiting_case_review + case_review_ai
```

必须保持现有测试点状态和字段不变。

### 13.7 取消

- `cancel_case_review_ai` 使用独立 `case_review_ai_cancel_requested_at`；
- pending 立即回 `waiting_case_review`；
- running 终止进程组；
- 不写主任务 `cancel_requested_at`；
- “取消整个任务”仍可取消 `waiting_case_review`。

### 13.8 启动恢复

启动扫描：

- `running + case_review_ai` → `waiting_case_review/case_review_ai_failed`，错误 `WORKER_INTERRUPTED`；
- `pending + case_review_ai` → 保留 pending 并重新排队；
- `waiting_case_review` → 保留；
- `case_review_publishing` 若作为临时 stage 留在 task.json，启动时检查确认/发布文件并恢复为 waiting 或 succeeded；推荐同步发布期间不先持久化 running 主状态，减少恢复分支。

---

## 14. Runner 与 Adapter 设计

### 14.1 功能 Runner 分派

```python
if kind == "review_ai":
    run_review_ai(...)
elif kind == "case_review_ai":
    run_case_review_ai(...)
else:
    run_existing_workflow(...)
```

### 14.2 用例生成完成状态

Runner 不能直接读取平台配置 Client；配置由 TaskManager 快照以允许列表环境变量传入：

```text
ONLINE_CASE_REVIEW_ENABLED=true|false
```

用例产物存在后：

```python
next_status = "waiting_case_review" if enabled else "succeeded"
stage = "case_review_editing" if enabled else "completed"
```

### 14.3 Adapter

当收集结果状态为 `waiting_case_review`：

- 找出最新登记的 `test_cases_json`；
- 保存 `case_review_source.artifact_id/sha256/case_count`；
- 原生成 XLSX 保留为模型原稿产物；
- 不把原 XLSX 标成最终确认产物；
- `result_summary.test_cases` 正常保留。

### 14.4 AI Runner 成功

```json
{
  "execution_kind": "case_review_ai",
  "execution_sequence": 5,
  "next_status": "waiting_case_review",
  "stage": "case_review_ai_ready",
  "case_review_ai": {}
}
```

### 14.5 AI Runner 失败

runner-result 写稳定错误码、kind 和 sequence，退出码非零。TaskManager 根据 kind 返回 `waiting_case_review`，不调用 `collect_result`，不覆盖 artifacts。

### 14.6 Runner 环境允许列表

新增普通配置：

```text
ONLINE_CASE_REVIEW_ENABLED
CASE_REVIEW_AI_ENABLED
CASE_REVIEW_AI_TIMEOUT_SECONDS
CASE_REVIEW_AI_MAX_SELECTED_CASES
CASE_REVIEW_AI_MAX_SUGGESTIONS
CASE_REVIEW_AI_MAX_CONTEXT_CASES
CASE_REVIEW_AI_MAX_CONTEXT_POINTS
CASE_REVIEW_AI_MAX_INSTRUCTION_CHARACTERS
```

仍不得传 `PLATFORM_CLIENT_TOKEN`、数据库 Secret 或其他工具配置。

---

## 15. Case Review AI Adapter

### 15.1 模块职责

`case_review_ai.py` 负责：

- 读取不可变请求；
- 验证草稿 revision/SHA；
- 读取确认测试点；
- 构建受控上下文；
- 调用模型；
- 一次安全 JSON 修复；
- 动作和字段白名单；
- 引用、ID、优先级和 `actual_result` 保护；
- 保存不可变建议文件。

### 15.2 请求模型

```python
class CaseReviewAIRequest(BaseModel):
    schema_version: int = 1
    request_version: int
    operation: Literal["supplement", "rewrite_selected", "generate_from_instruction"]
    base_revision: int
    base_sha256: str
    selected_ids: list[str]
    scope: dict[str, list[str]]
    instruction: str
    requested_by_user_id: str
    requested_at: str
    idempotency_key_sha256: str
    request_sha256: str
```

### 15.3 建议模型

```python
class CaseSuggestion(BaseModel):
    suggestion_id: str
    action: Literal["add", "replace"]
    target_id: str | None
    case: dict[str, Any]
    reason: str
    source_basis: str
    validation: dict[str, Any]
```

### 15.4 三种操作

`supplement`：只接受 add；ID 新且引用有效。

`rewrite_selected`：只接受 replace；target 必须在 selected；强制覆盖模型返回的 `case_id/test_point_id/actual_result` 为原值；优先级降低则拒绝建议，不静默修改模型输出，便于审计质量。

`generate_from_instruction`：只接受 add；instruction 不进入需求事实区；缺乏证据的预期必须包含“需确认”。

### 15.5 上下文构建

```text
系统规则
确认测试点摘要（最多 300）
需求事实（固定候选）
作用域内用例（最多 300）
选中用例
用户说明（独立不可信数据区）
输出 Schema
```

总字符数超过 120,000 整体拒绝。

### 15.6 输出安全

- 不接受 delete；
- 不接受未知 action；
- 不接受无效 target；
- 不接受跨测试点引用；
- 不接受超过 100 条；
- 单个建议先 normalize，再运行领域 validator；
- add 建议不得制造重复 `case_id`；
- replace 建议不得修改保护字段；
- 原始模型响应不保存为 artifact、不展示。

### 15.7 Prompt

新增 `review_test_cases.py`，不修改现有 Prompt。Prompt 必须明确：

- 用户说明不是需求事实；
- 不执行测试步骤；
- 不访问网络；
- 只返回 JSON；
- add/replace 约束；
- 保护 ID、引用、优先级和 actual_result；
- 预期结果必须可观察；
- 步骤必须原子、按顺序且不包含执行结果伪造。

### 15.8 Suggestion ID

```text
sha256(request_sha + action + target_id + canonical_case)[:16]
```

前缀使用 `case_suggestion_`，同请求重算稳定。

---

## 16. HTTP API 详细设计

### 16.1 公共约束

- 基路径复用功能服务；
- 所有写请求 CSRF；
- 所有接口所有权；
- 普通读取 `tool.result.view`；
- 写入/确认/AI `tool.execute`；
- AI cancel `task.cancel`；
- 越权和不存在统一 404；
- 状态仅 `waiting_case_review` 可写；
- 功能开关关闭返回 `FEATURE_DISABLED`。

### 16.2 GET `/tasks/{id}/case-review`

响应示例：

```json
{
  "task_id": "task_xxx",
  "task_status": "waiting_case_review",
  "editable": true,
  "source": "draft",
  "revision": 3,
  "sha256": "...",
  "saved_at": "...",
  "saved_by": "tester",
  "cases": [],
  "test_points": [
    {"id": "TP001", "module": "登录", "feature": "密码登录", "scenario": "用户名", "test_point": "用户名为空", "risk_level": "P1"}
  ],
  "validation": {},
  "coverage": {},
  "diff_summary": {},
  "case_review_ai": {}
}
```

只读终态可返回确认版本，`editable=false`。过期返回 410。

### 16.3 PUT `/tasks/{id}/case-review-draft`

请求：

```json
{"revision": 3, "sha256": "...", "cases": []}
```

服务端先用请求 Content-Length 做早期限制，再以规范化实际字节和字符数做权威限制。业务错误允许保存。

冲突 details：

```json
{
  "current_revision": 4,
  "current_sha256": "...",
  "saved_at": "...",
  "saved_by": "tester"
}
```

### 16.4 POST `/tasks/{id}/case-review-draft/import`

- multipart `review_file/revision/sha256`；
- `.json`；
- 文件上传仍 5 MiB/500,000 字符；
- 若导入数据规范化后超过用例草稿限制，拒绝；
- 只保存草稿；
- 不确认、不发布。

### 16.5 GET `/tasks/{id}/case-review/download`

参数：

```text
kind=generated|draft|confirmed
version=<int>  # confirmed 必填
```

不得接受路径。确认版本必须在固定文件名和 task metadata 中匹配。

### 16.6 POST `/tasks/{id}/case-review/confirm`

请求：

```json
{"revision": 3, "sha256": "...", "accept_warnings": true}
```

请求头要求 Idempotency-Key。幂等依据：

- 同 key + 同 revision/SHA：返回相同结果；
- 同 key + 不同正文：409；
- 没有 key：422；
- 相同 SHA 即使 key 不同，复用确认和发布版本。

发布成功返回 200：

```json
{
  "task": {},
  "case_review": {"version": 1, "sha256": "...", "case_count": 128},
  "artifacts": []
}
```

### 16.7 POST `/tasks/{id}/case-review-ai`

验证顺序：

1. 身份/权限/所有权/CSRF；
2. 状态；
3. 两个开关；
4. 草稿存在；
5. revision/SHA；
6. operation/selected/scope/instruction；
7. Idempotency-Key；
8. 不可变请求文件；
9. 队列容量；
10. 入队；
11. 审计。

队列失败必须删除未引用的新请求文件，历史请求文件不删除。

### 16.8 GET `/tasks/{id}/case-review-ai`

只返回当前/最近一次用例 AI 元数据。ready 时读取 suggestions 文件并校验文件字节 SHA。不得返回 relative_path。

### 16.9 POST `/tasks/{id}/case-review-ai/cancel`

独立取消标记。pending 返回 200；running 发终止请求并返回 202；最终状态均回 `waiting_case_review`。

### 16.10 readiness

现有 readiness 增加：

```json
{
  "online_case_review_enabled": true,
  "case_review_ai_enabled": true
}
```

只返回布尔值，不返回配置正文或 Secret。

---

## 17. 权限、CSRF 与审计

### 17.1 网关

所有路由仍位于 `/functional-test-agent/`，Nginx 现有鉴权 location 可覆盖，无需新增路径块。权限映射继续：

- GET：`tool.result.view`；
- PUT/POST：`tool.execute`；
- cancel：`task.cancel`。

工具服务仍二次校验，不能只依赖网关。

### 17.2 所有权

复用 `get_task`：

- 创建者可访问；
- 管理员需 `task.view.all`；
- 其他用户统一 404；
- ID 格式错误和越权均不暴露差异。

### 17.3 CSRF

所有 PUT/POST 使用当前双提交：可信 cookie + `X-CSRF-Token`。multipart import 同样要求 header。

### 17.4 审计

action：

```text
agent.case_review.draft.save
agent.case_review.draft.import
agent.case_review.confirm
agent.case_review.download
agent.case_review.ai.request
agent.case_review.ai.cancel
agent.case_review.ai.complete
agent.case_review.ai.fail
```

metadata 白名单：revision、SHA、数量、错误/警告数、覆盖数、operation、selected_count、instruction_sha256、模型、Prompt SHA、错误码。

不记录正文、测试数据、用户说明原文、路径或 Secret。

---

## 18. 前端状态与模块设计

### 18.1 页面入口

`task_detail.html` 根据：

```text
task.agent_type == functional
task.status == waiting_case_review
online_case_review_enabled
```

渲染用例工作台。开关关闭时显示旧生成产物，不提供编辑。

### 18.2 浏览器状态

```javascript
{
  cases: [],
  original: [],
  testPoints: [],
  revision: 0,
  sha256: "",
  validation: {},
  coverage: {},
  diff: {},
  selectedCaseId: null,
  selected: Set,
  filters: {},
  groupBy: "module",
  collapsedGroups: Set,
  page: 1,
  pageSize: 50,
  dirty: false,
  saving: false,
  editable: true,
  ai: null,
  lastDeleted: null
}
```

### 18.3 模块边界

保持一个 `case-review-workbench.js` 文件，但按函数分区：

```text
API/state
normalization
client validation
filters/list
detail editor
step editors
test data editor
AI suggestions
save/conflict/confirm
bootstrap
```

不为本期引入 bundler 或模块框架。

### 18.4 列表

- 语义化 table；
- 表头固定；
- 25/50/100 分页；
- 选中行使用文字和背景，不只颜色；
- 行点击打开详情，但复选框/按钮阻止冒泡；
- 长名称截断并提供 title/详情全文；
- 分组行可键盘折叠；
- 筛选针对完整浏览器内草稿。

### 18.5 详情编辑

- 基本字段使用两列网格；
- `test_point_id` 使用确认测试点下拉；
- 下拉项展示 `TPID · 模块 · 测试点`；
- 选中测试点后不自动覆盖模块/功能/场景，只提示差异；
- 前置条件和步骤分别为可排序列表；
- `actual_result` 只读；
- 扩展字段折叠只读；
- 编辑 `case_id` 后保持内部 `_rowKey` 关联，避免丢失选中状态。

### 18.6 测试数据

- 默认根据当前类型选择 JSON/文本模式；
- JSON textarea 失焦或校验时格式化；
- 解析错误保留用户文本，不覆盖；
- 切换类型使用确认对话框；
- 不使用 contenteditable、innerHTML 或代码执行；
- 长内容显示字符计数。

### 18.7 步骤操作

- 新增、删除、上移、下移按钮；
- 每项 textarea；
- 按钮有 `aria-label`，包含步骤序号；
- 删除后焦点回上一项或新增按钮；
- 批量粘贴先弹确认并显示将拆分数量；
- 空步骤即时错误。

### 18.8 Dirty 与保存

- 任一字段变更 `dirty=true`；
- AI 应用后 dirty；
- 分页/筛选/折叠不 dirty；
- 保存成功更新 revision/SHA 并清 dirty；
- beforeunload 提示；
- CAS 冲突保留内存数据并显示本地副本下载；
- 重新加载必须二次确认。

### 18.9 客户端校验

客户端实现轻量必填、枚举、ID、步骤、JSON 和完全重复检查。覆盖和服务端限制仍由后端最终决定。

错误点击行为：

1. 清除冲突筛选；
2. 展开所属分组；
3. 切到正确页；
4. 选中用例；
5. 展开详情区；
6. 聚焦字段或步骤项。

### 18.10 AI 建议

- 复用测试点建议面板视觉语言；
- add 显示完整新用例摘要；
- replace 显示字段级 before/after；
- 默认 checkbox 未选中；
- 应用前检查 base revision/SHA；
- 应用后不自动保存；
- 保护字段差异即使模型返回也标记“已拒绝”，不进入可选项。

---

## 19. 页面与视觉详细设计

### 19.1 设计判断

该页面是高信息密度的桌面工程工作台，主要目标是发现覆盖问题、逐条修正嵌套测试用例并确认最终产物。视觉优先级为“当前状态 → 阻塞问题 → 用例列表 → 当前详情 → 下一步操作”。

### 19.2 设计 token

继续使用现有：

```text
背景 #F5F5F7 / #FFFFFF
正文 #1D1D1F
次要 #6E6E73
分隔 rgba(0,0,0,.12)
强调 #0071E3
错误 #B42318
成功 #18794E
系统字体栈
8px 间距网格
```

不新增紫色 AI 渐变、发光、卡片墙或聊天气泡。

### 19.3 页面层级

- 页面只保留一个 H1；
- Review 工作台使用 H2；
- 摘要采用一条分隔式统计区域，不为每项加阴影卡片；
- 覆盖错误紧邻摘要；
- 列表和详情用清晰分隔，不堆叠浮层；
- AI 面板是辅助区域，不抢占主操作；
- 固定操作栏只包含撤销、保存和确认。

### 19.4 布局

在 1280～1400 宽容器内：

- 列表占全宽；
- 详情在列表下方，避免左右双栏压缩嵌套步骤；
- 桌面较宽时基本字段可两列；
- 步骤和预期保持足够行宽；
- 不设计 1280 以下移动响应式。

### 19.5 状态

必须覆盖：

- 加载；
- 空原稿；
- 只读；
- 未保存；
- 保存中；
- 保存失败；
- revision 冲突；
- 校验错误；
- 覆盖缺失；
- AI 关闭；
- AI 排队/运行/取消/失败/完成；
- 最终发布中/失败/完成；
- artifact 过期。

### 19.6 可访问性

- 语义化 table/form/fieldset/dialog；
- 所有按钮有文字或 accessible name；
- 焦点环沿用系统蓝；
- 错误同时提供文本、图标/形状和位置；
- AI 建议面板使用 `aria-live` 汇报状态，不播报完整正文；
- dialog 打开后焦点进入，关闭后返回触发按钮；
- `prefers-reduced-motion` 关闭非必要动画。

---

## 20. 平台配置与迁移

### 20.1 新迁移

```text
Revision: 20260814_0012
Revises: 20260813_0011
```

仅新增 11 个功能工具配置定义：

```text
ONLINE_CASE_REVIEW_ENABLED=false
CASE_REVIEW_AI_ENABLED=false
CASE_REVIEW_AI_TIMEOUT_SECONDS=600
CASE_REVIEW_AI_MAX_SELECTED_CASES=50
CASE_REVIEW_AI_MAX_SUGGESTIONS=100
CASE_REVIEW_AI_MAX_CONTEXT_CASES=300
CASE_REVIEW_AI_MAX_CONTEXT_POINTS=300
CASE_REVIEW_AI_MAX_INSTRUCTION_CHARACTERS=2000
CASE_REVIEW_MAX_CASES=2000
CASE_REVIEW_MAX_BYTES=10485760
CASE_REVIEW_MAX_CHARACTERS=1000000
```

### 20.2 Upgrade

- owner_type=`tool`；
- owner_id=`functional-test-agent`；
- 目录默认 false/安全限制；
- 克隆当前 dev active Release；
- dev 新 Release 显式开启两个开关；
- 其他配置和 Secret 引用保持；
- prod 不创建开启 Release；
- migration 不读取 Secret 明文。

### 20.3 Downgrade

- 若当前激活的是 migration 创建的 dev Release，恢复 based_on；
- 只删除 created_by 和 owner/environment 精确匹配的 Release；
- 删除本期 release items 和定义；
- 不删除工具、Secret、审计和任务文件；
- 支持 downgrade 0011 后重新 upgrade。

### 20.4 迁移测试

- SQLite 测试合同；
- PostgreSQL 空库 upgrade head；
- 重复 upgrade；
- downgrade 0011；
- re-upgrade；
- dev 两开关 true；
- prod 无开启 Release；
- downgrade 不影响测试点 Review 0010 定义和 API V2 0011 定义。

### 20.5 Compose/Nginx

- 服务拓扑不变；
- 功能镜像依赖已有 `openpyxl`；
- 单 worker 不变；
- 非 root 和只读源码不变；
- 任务卷不变；
- 网关 6 MiB 上传限制满足 5 MiB JSON import；
- 不增加端口、Token 或 Secret。

---

## 21. 错误码与失败语义

### 21.1 新错误码

```text
CASE_REVIEW_FILE_INVALID
CASE_REVIEW_DRAFT_REQUIRED
CASE_REVIEW_REVISION_CONFLICT
CASE_REVIEW_VALIDATION_FAILED
CASE_REVIEW_WARNING_CONFIRMATION_REQUIRED
CASE_REVIEW_REFERENCE_INVALID
CASE_REVIEW_POINT_BASE_MISSING
CASE_REVIEW_AI_ALREADY_RUNNING
CASE_REVIEW_AI_BASE_CHANGED
CASE_REVIEW_AI_SCOPE_REQUIRED
CASE_REVIEW_AI_RESPONSE_INVALID
CASE_REVIEW_PUBLISH_FAILED
```

继续复用：`TASK_NOT_FOUND/INVALID_TASK_STATE/QUEUE_FULL/FEATURE_DISABLED/UPLOAD_TOO_LARGE/ARTIFACT_EXPIRED/LLM_TIMEOUT/LLM_RATE_LIMITED/STORAGE_WRITE_FAILED`。

### 21.2 主任务错误语义

- 用例 AI 错误：主任务不失败，回 `waiting_case_review`；
- 草稿保存失败：状态不变；
- 最终发布失败：状态保持 `waiting_case_review`，错误在可重试的 case_review publish metadata 中；
- 用户取消整个任务：`cancelled`；
- 用例生成 Runner 失败：仍为 `failed`；
- 已提交成功后任何迟到错误不覆盖。

### 21.3 HTTP details 白名单

允许：revision、SHA、保存时间/人、数量、限制、错误/警告/覆盖摘要。

禁止：正文、Prompt、模型原始响应、绝对/相对路径、异常对象、PID、Secret。

---

## 22. 安全设计

### 22.1 输入

- JSON 安全解析；
- 深度/节点数限制；
- 类型、数量、字节和字符限制；
- NUL/UTF-8；
- 固定扩展和 MIME；
- 客户端私有字段拒绝；
- XLSX 公式注入防护。

### 22.2 Prompt 注入

- 系统规则与数据区明确分隔；
- 用户说明 JSON 编码；
- 需求事实只从当前任务固定路径；
- 不把步骤当作可执行指令；
- 输出动作白名单；
- Schema 后再做领域校验；
- 不访问网络或测试目标。

### 22.3 XSS

- 用例正文只写 `textContent/value`；
- JSON 差异使用 `<pre>.textContent`；
- 不使用 `innerHTML`；
- Jinja 默认转义；
- 下载文件使用 attachment。

### 22.4 数据隔离

- 当前 task_dir containment；
- artifact registry；
- 当前确认测试点；
- 不读取其他任务或 output；
- dev/prod 配置和 Secret 继续隔离。

### 22.5 DoS/成本

- 2,000 条/10 MiB/1,000,000 字符；
- AI 300 用例/300 测试点/120,000 字符；
- 100 建议；
- FIFO 上限；
- 600 秒超时；
- Idempotency-Key；
- 单 AI 请求占同一槽位。

---

## 23. 可观测性

### 23.1 Task metadata

公共白名单新增：

```text
case_review
case_review_draft
case_review_ai
case_review_source
```

嵌套字段严格过滤。

### 23.2 日志

允许：阶段、数量、revision、短 SHA、模型名、Prompt SHA、耗时、错误码。

禁止：用例正文、测试数据、用户说明、Prompt 全文、Secret、路径。

### 23.3 建议指标

```text
case_review_draft_save_total
case_review_conflict_total
case_review_validation_error_total
case_review_confirm_total
case_review_publish_seconds
case_review_ai_request_total
case_review_ai_ready_total
case_review_ai_failed_total
case_review_ai_cancelled_total
case_review_ai_suggestion_applied_total
```

本期不为指标引入新监控依赖；先通过审计和结构化日志统计。

---

## 24. 兼容性设计

### 24.1 测试点 Review

- 路由、文件名、字段和状态完全不变；
- 原测试点 `review_ai` 行为不变；
- 公共内核抽取前先用当前回归锁定行为；
- 抽取后同一测试全部通过。

### 24.2 旧功能任务

- 已 succeeded 的任务不自动转 `waiting_case_review`；
- 原 JSON/XLSX 可继续下载；
- 不批量生成草稿；
- 不修改历史 task.json。

### 24.3 开关关闭

用例生成仍直接成功，Adapter 仍发布原 JSON/XLSX。页面不显示用例编辑器。

### 24.4 CLI

CLI 不读取 `ONLINE_CASE_REVIEW_ENABLED` 时保持原行为；平台 TaskManager 显式传配置。不得使本地 CLI 因默认 false/true 产生等待 Web Review 的死流程。

### 24.5 API 智能体

不共用页面和用例 Schema，不修改：

```text
API_EXECUTION_ENABLED=false
DATABASE_PERSIST_ENABLED=false
ALLOWED_TARGETS=[]
```

---

## 25. 自动化测试设计

### 25.1 方法

每个缺陷先写失败测试。按领域 → 文件 → API → 队列 → UI 合同 → E2E 分层。

### 25.2 公共内核

- 测试点兼容行为；
- 两种 resource spec 隔离；
- artifact 原稿定位；
- CAS；
- 同正文不增 revision；
- 原子替换；
- 不可变确认；
- 确认索引恢复；
- 损坏草稿/确认；
- containment/symlink/伪造文件名。

### 25.3 用例领域

- 三种顶层包装；
- preconditions/test_steps 类型兼容；
- test_data dict/list/string；
- 扩展字段；
- 稳定 SHA；
- ID/字段/优先级；
- 步骤和数据限制；
- 完全重复与警告；
- 引用和覆盖；
- O(n) diff；
- 100/500/2,000 性能。

### 25.4 Publisher

- JSON 与确认内容一致；
- XLSX 行数、列顺序和单元格内容；
- 步骤编号；
- 公式注入；
- 同 SHA 幂等；
- JSON 成功/XLSX 失败不登记；
- registry 失败恢复；
- 版本目录不可覆盖。

### 25.5 状态与 FIFO

- 用例生成进入 waiting；
- 开关关闭直接成功；
- case AI 入队；
- 与 test-point AI 竞争最后一个位置；
- FIFO；
- cancel pending/running；
- timeout；
- restart；
- sequence 迟到；
- AI 回 waiting_case_review；
- 主任务 cancel。

### 25.6 AI Adapter

- supplement 只 add；
- rewrite 只 replace/selected；
- instruction 只 add；
- ID/引用/actual_result 保护；
- 优先级降级拒绝；
- 无效动作/target/schema；
- JSON repair 一次；
- 上下文/建议上限；
- revision 过期；
- Prompt 注入文本不改变规则；
- 不执行代码、不 HTTP；
- 建议文件不可变。

### 25.7 Web API

- GET/PUT/import/download/confirm；
- AI request/get/cancel；
- Idempotency-Key；
- 业务错误草稿可保存；
- 确认阻塞；
- 警告确认；
- CAS details；
- 过期 410；
- 路径攻击；
- 创建者/他人/管理员/只读；
- CSRF；
- 开关。

### 25.8 前端合同

- 模板包含工作台语义结构；
- 脚本无 innerHTML/eval/Function；
- 列表分页上限；
- 详情字段；
- 步骤键盘按钮；
- dirty/save/conflict；
- AI 默认未选；
- reduced-motion CSS；
- actual_result 只读。

### 25.9 平台

- 0012 定义数量和值；
- dev/prod；
- downgrade 精确范围；
- Secret 不回显；
- Nginx/Compose；
- API 安全默认。

### 25.10 完整回归命令

```bash
cd /Users/admin/Testproject/AItestcase_Agents
python3 -m pytest -q

cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q

cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run
npm run build
npm audit --audit-level=high

cd /Users/admin/Testproject/test-platform
python3 -m unittest discover -s tests -v
docker compose config
docker compose exec -T platform-gateway nginx -t
```

---

## 26. 浏览器验收设计

### 26.1 视口

- 1280×800；
- 1440×900。

只验收桌面端。

### 26.2 人工主流程

```text
生成用例
→ waiting_case_review
→ 加载原稿
→ 修改基本字段
→ 增删/排序步骤
→ 编辑测试数据
→ 新增/复制/删除用例
→ 保存草稿
→ 刷新恢复
→ 确认
→ succeeded
→ 下载 JSON/XLSX
```

### 26.3 覆盖与错误

- 删除某测试点全部用例后显示阻塞；
- 点击未覆盖定位；
- 无效引用；
- 重复 ID/用例；
- JSON 数据错误；
- 保存带业务错误草稿；
- 确认失败；
- 修复后确认。

### 26.4 冲突

- 双标签加载同 revision；
- 标签 A 保存；
- 标签 B 保存返回冲突；
- 标签 B 内容保留；
- 下载本地副本；
- 重新加载服务端版本。

### 26.5 AI

- AI 关闭；
- 排队；
- 运行；
- 取消；
- 失败；
- ready；
- 默认未选；
- replace 差异；
- 选择应用；
- dirty；
- 保存；
- 基准过期拒绝。

### 26.6 权限

- 创建者；
- 其他普通用户 404；
- 管理员；
- 只读用户；
- 缺少 CSRF；
- 直接构造接口。

### 26.7 可访问性

- Tab 顺序；
- 步骤按钮；
- dialog 焦点；
- 保存后焦点；
- 错误跳转；
- 非纯颜色；
- reduced-motion。

### 26.8 性能

- 100 条首屏；
- 500 条筛选；
- 2,000 条服务端校验；
- DOM 不超过当前页 + 一个详情；
- 长步骤和长 JSON 不破坏布局。

无真实模型或登录凭据时使用 Fake/Mock 与隔离身份；真实联调单列外部限制。

---

## 27. 工作包与依赖

### 27.1 工作包总览

| 工作包 | 内容 | 依赖 | 完成标准 |
|---|---|---|---|
| C01 | 基线冻结 | 无 | Git、测试、output、黄金用例记录 |
| C02 | VersionedReviewStore | C01 | 公共事务测试和测试点兼容通过 |
| C03 | 用例模型/规范化 | C01 | 类型兼容和 SHA 测试通过 |
| C04 | 校验/覆盖/diff | C03 | 领域规则与性能通过 |
| C05 | 用例草稿/确认 Service | C02-C04 | CAS、不可变、恢复通过 |
| C06 | 生成结果进入 Review | C01 | 开关开/关状态测试通过 |
| C07 | 人工 Review API | C05-C06 | GET/PUT/import/download 通过 |
| C08 | 最终 Publisher/confirm | C05-C07 | JSON/XLSX 同源和终态通过 |
| C09 | TaskManager case AI | C01 | FIFO、取消、超时、恢复通过 |
| C10 | AI Prompt/Adapter | C04-C05 | 三操作 Mock 测试通过 |
| C11 | Runner case AI | C09-C10 | kind/sequence 集成通过 |
| C12 | 页面壳/用例列表 | C07 | 双视口列表流程通过 |
| C13 | 详情/步骤/数据编辑 | C12 | 嵌套编辑和键盘通过 |
| C14 | 校验/筛选/冲突 UI | C12-C13 | 错误定位和 CAS 通过 |
| C15 | AI 建议 UI | C10-C14 | 默认未选和人工应用通过 |
| C16 | 权限/审计/安全 | C07-C11 | 安全矩阵通过 |
| C17 | 0012 配置迁移 | C01 | upgrade/downgrade/re-upgrade 通过 |
| C18 | E2E、文档、发布 | 全部 | 全量回归和交付报告完成 |

### 27.2 推荐顺序

```text
C01
 ├→ C02 → C05 → C07 → C08
 ├→ C03 → C04 ───────┘
 ├→ C06
 ├→ C09 → C11
 │        ↑
 └→ C10 ──┘

C07 → C12 → C13 → C14 → C15
C07/C11 → C16
C01 → C17
全部 → C18
```

### 27.3 工作量

| 阶段 | 人日 |
|---|---:|
| 公共内核与领域 | 3～5 |
| 状态/API/发布 | 3～4 |
| 页面工作台 | 3～4 |
| AI | 2～3 |
| 安全/迁移/E2E | 2～4 |
| 合计 | 13～20 |

比 PRD 初估略增加公共内核兼容保护和 XLSX 安全发布测试，但后续两类 Review 的维护成本更低。

---

## 28. 分阶段实施计划

### CR01：基线与公共内核

范围：C01～C02。

步骤：

1. 完整读取 AGENTS 和基线文档；
2. 记录 Git、版本、测试和 output；
3. 选择含嵌套步骤/数据的黄金用例；
4. 为当前测试点 Review 编写行为锁定测试；
5. 抽取 VersionedReviewStore；
6. 测试点 Review 兼容包装；
7. 完整测试点回归。

退出条件：测试点在线 Review 行为零变化。

### CR02：用例领域与生命周期

范围：C03～C08。

步骤：

1. 用例兼容规范化；
2. 校验、覆盖和 diff；
3. 草稿与确认 Service；
4. Runner/Adapter 进入 waiting；
5. 人工 API；
6. Publisher；
7. confirm 与终态；
8. 文件故障恢复。

退出条件：Flask client 可完成原稿→草稿→确认→JSON/XLSX→成功。

### CR03：人工用例工作台

范围：C12～C14。

步骤：

1. 页面壳和 feature flag；
2. 列表/筛选/分页/分组；
3. 详情基本字段；
4. 前置条件/步骤；
5. 测试数据；
6. 客户端校验；
7. dirty/save/conflict；
8. 导入/下载/确认；
9. 键盘与 reduced-motion。

退出条件：不用 JSON 完成人工 Review 主流程。

### CR04：AI 辅助

范围：C09～C11、C15。

步骤：

1. TaskManager execution kind；
2. Prompt 和请求/建议 Schema；
3. Adapter 输出保护；
4. Runner 分派；
5. request/get/cancel API；
6. 建议差异和应用；
7. 取消、超时、恢复；
8. Mock 全边界。

退出条件：三操作只建议、人工应用、失败回 Review。

### CR05：安全与配置

范围：C16～C17。

步骤：

1. 所有权/RBAC/CSRF；
2. 审计；
3. XSS/路径/公式注入；
4. 0012；
5. dev/prod Release；
6. Secret/Tool Client 隔离；
7. Nginx/Compose；
8. API 安全默认。

退出条件：安全矩阵与迁移往返通过。

### CR06：E2E 与性能

范围：C18 测试部分。

步骤：

1. 全自动化；
2. 100/500/2,000；
3. 双视口；
4. 冲突；
5. AI 状态；
6. 发布失败恢复；
7. 功能/API 服务故障隔离；
8. output 完整性。

退出条件：无未说明阻塞缺陷。

### CR07：发布与交付

范围：C18 文档和部署。

步骤：

1. README；
2. 迁移和配置说明；
3. dev 灰度；
4. 人工开关验收；
5. AI 开关验收；
6. 回滚演练；
7. 最终文件/测试/风险报告。

退出条件：可交付状态。

---

## 29. 部署设计

### 29.1 dev 顺序

1. 记录工作区与 output；
2. 完整回归；
3. 隔离 PostgreSQL 验证 0012 往返；
4. 本地 dev upgrade；
5. 发布 dev Release，先只开启 `ONLINE_CASE_REVIEW_ENABLED`；
6. 构建并只替换功能智能体；
7. 人工 Review 验收；
8. 开启 `CASE_REVIEW_AI_ENABLED`；
9. AI 验收；
10. JSON/XLSX 同源验证；
11. 故障隔离；
12. 全量回归。

### 29.2 prod 门槛

- dev 至少完成一条完整双 Review 任务；
- 2,000 条发布时间符合门槛；
- 真实模型三操作 Schema 合法；
- 冲突、取消、超时、恢复已验证；
- Secret/路径扫描通过；
- prod 两开关仍 false；
- 获得上线确认后单独发布 prod Release。

### 29.3 健康和隔离

- `/health` 不访问 LLM/任务正文；
- readiness 仅布尔元数据；
- 停止功能智能体不影响 API 智能体；
- 用例 Review 异常不影响测试点 Review 静态查看和旧 artifact 下载。

---

## 30. 回滚设计

### 30.1 开关

1. 关闭 `CASE_REVIEW_AI_ENABLED`；
2. 关闭 `ONLINE_CASE_REVIEW_ENABLED`；
3. 新任务恢复直接成功；
4. 不删除任何 Review 文件。

### 30.2 已等待任务

关闭在线开关前已有 `waiting_case_review` 任务：

- 管理员可重新开启开关完成；或
- 下载模型原稿；或
- 使用受保护运维动作将模型原稿发布为最终版本。

本期不提供普通用户“跳过 Review”按钮，避免绕过已确认流程。运维动作如需实现必须独立审计且仅管理员可用；默认回滚方案优先短暂重开功能完成任务。

### 30.3 镜像

- 恢复上一版功能镜像；
- 保留任务卷；
- 旧镜像忽略新增文件；
- 已成功最终 artifacts 继续可下载；
- 不回滚 API 智能体和其他工具。

### 30.4 数据库

- 通常保留 0012；
- downgrade 前关闭开关；
- 若存在更后迁移先按链路逐级降级；
- 0012 只删除本期定义/Release；
- 不删除任务、审计和 Secret。

---

## 31. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 公共内核抽取破坏测试点 Review | 先锁定行为测试，兼容包装，分步回归 |
| 历史字段类型不一致 | 边界规范化，原稿不改写 |
| 用例详情 UI 复杂 | 列表 + 单详情，无新框架 |
| 覆盖校验误用未确认测试点 | 只读取确认版本和 SHA |
| AI 改写需求事实 | 保护 ID/引用、数据分区和输出校验 |
| XLSX 公式注入 | 强制字符串和危险前缀处理 |
| JSON/XLSX 不一致 | 同确认对象派生、版本/SHA 记录 |
| 同步发布超时 | 2,000 条性能门槛；不达标切同 FIFO publish kind |
| registry 半提交 | 文件先完整发布，registry 后提交，幂等恢复 |
| 两种 AI 状态混淆 | 独立 metadata/cancel 标记/stage |
| 任务终态竞争 | 锁内首次合法提交 + execution sequence |
| prod 意外开启 | 目录默认 false，prod 不建开启 Release |
| 回滚遗留 waiting 任务 | 保留文件，短暂重开或管理员运维处理 |

---

## 32. 最终完成检查单

### 32.1 数据与功能

- [ ] 测试点 Review 兼容；
- [ ] 用例原稿/草稿/建议/确认隔离；
- [ ] 类型兼容；
- [ ] 扩展字段；
- [ ] CAS；
- [ ] 不可变确认；
- [ ] 引用和覆盖；
- [ ] JSON/XLSX 同源；
- [ ] 开关关闭旧流程；
- [ ] 历史 output 未变化。

### 32.2 AI 与队列

- [ ] 三操作；
- [ ] 保护 ID/引用/优先级/actual_result；
- [ ] 默认未选；
- [ ] 不自动保存；
- [ ] 共享 FIFO；
- [ ] cancel/timeout/restart；
- [ ] 返回 waiting_case_review；
- [ ] sequence 迟到保护。

### 32.3 安全

- [ ] 所有权/RBAC/CSRF；
- [ ] IDOR 404；
- [ ] 路径 containment；
- [ ] XSS；
- [ ] JSON 深度/节点；
- [ ] XLSX 公式注入；
- [ ] Prompt 注入；
- [ ] Secret/路径/Prompt 不回显；
- [ ] API 安全默认。

### 32.4 质量与发布

- [ ] 全量回归；
- [ ] 0012 往返；
- [ ] Compose/Nginx；
- [ ] 1280×800；
- [ ] 1440×900；
- [ ] 键盘/reduced-motion；
- [ ] 100/500/2,000 性能；
- [ ] dev 人工开关；
- [ ] dev AI 开关；
- [ ] prod 初始关闭；
- [ ] 回滚演练；
- [ ] 最终交付报告。

---

## 33. 设计结论

本设计以现有测试点 Review 为基础，但只抽取稳定、可验证的版本化文件事务，不把测试点和测试用例业务规则强行合并。测试点继续通过原 `ReviewService` 兼容入口运行；测试用例使用独立 policy、API、AI Prompt 和列表 + 详情工作台，从而获得高复用率并降低回归风险。

测试用例生成后通过开关进入 `waiting_case_review`；人工编辑使用 revision/SHA CAS；AI 使用独立 `case_review_ai` execution kind 并与所有功能任务共享单槽 FIFO；最终确认从不可变 JSON 同源生成 JSON/XLSX，并以首次合法终态保护提交成功。

按 C01～C18、CR01～CR07 推进并通过质量门槛后，可先在 dev 开启人工 Review，再开启 AI Review，prod 首次发布仍保持关闭。任一阶段出现问题均可通过两个独立开关回退到现有直接生成流程，同时保留用户草稿、建议、确认版本和历史任务数据。
