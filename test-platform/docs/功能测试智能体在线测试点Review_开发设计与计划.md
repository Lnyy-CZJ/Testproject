# 功能测试智能体在线测试点 Review 开发设计与计划

> 文档版本：V1.0  
> 创建日期：2026-08-13  
> 文档状态：待开发评审  
> 需求基线：`test-platform/docs/功能测试智能体在线测试点Review_PRD.md` V1.1  
> 适用服务：`functional-test-agent`  
> 推荐入口：`/functional-test-agent/tasks/{task_id}#review`  
> 技术栈：Flask 3 + Jinja + 原生 JavaScript/CSS + 文件任务存储 + 持久化 FIFO + LangChain/OpenAI 兼容模型  
> 设计定位：增量扩展现有任务架构，不新增测试点数据库表，不改变正式测试用例 Runner 的 JSON 输入

关联文档：

- `test-platform/docs/AI测试智能体独立接入PRD.md`；
- `test-platform/docs/AI测试智能体独立接入开发设计与计划.md`；
- `test-platform/docs/功能测试智能体在线测试点Review_PRD.md`。

---

## 1. 文档目的

本文档把已评审的在线测试点 Review PRD 转换为可以直接实施、测试、部署和回滚的开发设计与工作计划。

本次开发同时交付两组能力：

1. 在线人工 Review：表格编辑、增删复制、筛选折叠、校验、草稿、revision、确认版本和继续排队；
2. AI 辅助 Review：补全测试点、改写选中项、按说明生成建议，以及建议差异预览、选择应用、取消、超时和恢复。

设计必须保持以下边界：

- JSON 文件仍是测试点权威数据；
- 模型生成原稿、可变草稿、AI 建议和确认版本相互隔离；
- 正式用例生成只读取确认版本；
- AI 只产生建议，不自动改写草稿或确认 Review；
- AI 辅助与正式任务共用一个持久化 FIFO 和一个运行槽位；
- 不新增测试点业务数据库表；
- 不建设 SPA、WebSocket、SSE、开放聊天或多人实时协作；
- 不修改 API 测试智能体的功能与安全开关；
- 不修改历史 `AItestcase_Agents/output/`。

---

## 2. 需求理解与成功标准

### 2.1 需求理解

用户在测试点生成后不再以下载 JSON 为默认操作，而是在任务详情页直接编辑结构化测试点。用户可以中途保存草稿，也可以让 LLM 基于已保存草稿和需求上下文提出建议。所有建议必须经过人工选择、草稿保存和最终确认后，才能成为生成测试用例的输入。

### 2.2 技术成功标准

开发完成必须满足：

1. 旧 `waiting_review` 任务可以从原始测试点产物初始化 revision 0；
2. 草稿保存使用独立 revision，两个页面不会静默覆盖；
3. 规范化与校验由服务端统一实现，前端只做同规则即时提示；
4. 未识别 JSON 扩展字段完整往返；
5. 模型原始产物永不覆盖；
6. 确认版本不可变，相同 SHA 重试不增加版本；
7. `resume` 重新按 `queued_at + task_id` 参与 FIFO；
8. AI 三种操作通过固定 Schema 输出建议；
9. AI 排队、运行、取消、超时、限流、非法输出和重启中断均有稳定结果；
10. AI 辅助失败后回到 `waiting_review`，草稿和原产物不变；
11. AI 建议不能自动进入正式 Review JSON；
12. 所有写请求通过 CSRF、RBAC、所有权和状态校验；
13. 页面在 1280×800、1440×900 完成关键浏览器验收；
14. 功能智能体、API 智能体和平台现有回归全部通过；
15. 关闭功能开关可回退到现有 JSON 上传/下载流程。

### 2.3 交付物

- 在线 Review 领域模型、校验、diff 和文件服务；
- Review GET、PUT、导入、下载及 JSON resume API；
- AI 辅助请求、查询和取消 API；
- 可区分执行类型的 FIFO 与 Runner；
- AI Review Adapter、结构化 Prompt 和建议文件；
- Jinja Review 工作区及原生 JavaScript/CSS；
- 平台配置定义迁移；
- 单元、集成、安全、恢复和浏览器测试；
- 部署、运维、回滚和用户说明更新。

### 2.4 非交付范围

- 测试用例在线编辑；
- AI 自动应用、自动删除和自动确认；
- 多人实时协作和三方合并；
- 测试点数据库资产库；
- 移动端；
- 语义向量去重；
- 流式 Token 展示；
- 新增模型供应商或改变原功能工作流 Prompt。

---

## 3. 当前实现评估

### 3.1 已有可复用能力

| 能力 | 当前文件 | 复用方式 |
|---|---|---|
| Flask 工具服务 | `services/common/web.py` | 在功能工具条件下注册 Review 路由 |
| 可信身份与权限 | `services/common/identity.py` | 复用 `require_task_access`、`require_csrf` |
| 文件任务存储 | `services/common/task_store.py` | 复用 containment、原子 JSON 和任务锁 |
| 单槽 FIFO | `services/common/task_manager.py` | 扩展执行类型、重入队时间和 AI 可恢复失败 |
| 上传校验 | `services/common/uploads.py` | 保留上传边界；领域校验迁入 Review 模块 |
| 产物白名单 | `services/common/artifacts.py` | 原始测试点继续按 artifact ID 下载 |
| 模型配置快照 | `TaskManager._runner_environment` | AI 使用同一环境的 Release 与 LLM Secret |
| Prompt Bundle SHA | `services/common/prompt_version.py` | 新 AI Prompt 自动纳入 Bundle |
| 功能 Runner | `services/functional_agent/runner.py` | 按 `execution_kind` 分派正式生成或 AI 建议 |
| 任务详情页 | `task_detail.html` | 替换简单上传区为结构化工作区 |
| 公共 JS/CSS | `agent-workbench.js/css` | 保留任务轮询，拆出 Review 专用资源 |
| 审计 | `services/common/audit.py` | 增加 Review 与 AI action |

### 3.2 当前差距

1. `validate_review_json` 只要求 `test_point`，不满足完整字段、重复和警告规则；
2. `review_draft` 当前实际表示“上传后立即继续的确认版本”，没有独立草稿 revision；
3. `POST /resume` 只接受 multipart 文件；
4. 任务详情没有 Review 数据查询接口；
5. `TaskStore.save` 的内部 revision 是任务记录写入版本，不能直接充当 Review revision；
6. `pending_fifo()` 仍按原始 `created_at` 排序，resume 后可能提前插队；
7. Runner 只根据 `operation + review_relative_path` 推断阶段，无法安全区分 AI 辅助；
8. 任何 Runner 非零退出、超时或重启中断都会把任务置为 `failed`；
9. `collect_result` 要求存在正式产物，不适合无产物的 AI 建议阶段；
10. 当前浏览器代码没有可编辑表格、客户端状态、冲突或差异模型；
11. 平台配置目录没有在线 Review 与 AI 辅助配置定义。

### 3.3 兼容性缺陷顺带修正

本设计必须修正 FIFO 重排依据，但不扩大产品范围：

```text
当前：pending 按 created_at + task_id
目标：pending 按 queued_at + task_id
```

- 新任务：`queued_at = created_at`；
- Review 正式继续：`queued_at = resume_requested_at`；
- AI 辅助：`queued_at = review_ai.requested_at`；
- 旧 pending 任务缺少 `queued_at` 时回退 `created_at`。

这保证所有重新入队动作都排到当时队尾，符合原已批准 FIFO 决策。

---

## 4. 方案选择

### 4.1 前端：Jinja + 原生 JavaScript/CSS

继续使用当前工具服务自带页面，不迁移到平台 React SPA。

理由：

- 页面只服务功能智能体任务详情；
- 现有身份、CSRF 和子路径已经在 Flask 服务内闭环；
- 原生表格、分页和筛选不需要大型组件库；
- 避免新增 Node 构建链和前后端跨仓发布耦合。

实现上新增专用 `review-workbench.js` 和 `review-workbench.css`，公共任务轮询继续留在 `agent-workbench.js`。两份脚本通过 DOM 数据属性和自定义事件协作，不建立全局框架。

### 4.2 存储：文件信封 + `task.json` 元数据缓存

`review-draft.json` 使用带 revision 的文件信封作为草稿事实来源，`task.json.review_draft` 是可重建的索引和公共摘要。

理由：单个文件和 `task.json` 无法跨文件系统原子提交。先原子发布自描述草稿信封，再保存任务索引；如果进程在两步之间崩溃，读取时可从草稿信封恢复索引，不会出现正文存在但 revision 不可判断的状态。

### 4.3 并发：服务端 Compare-And-Swap

前端提交 `revision + sha256`，服务端在同一 TaskStore 锁内重新读取文件并比较。冲突返回 409，不自动合并。

### 4.4 执行分派：独立 `execution.json`

保留原始 `request.json` 作为任务创建输入，新增当前执行信封：

```text
execution.json
```

每次进入 FIFO 前原子写入：

```json
{
  "schema_version": 1,
  "sequence": 3,
  "kind": "review_ai",
  "queued_at": "2026-08-13T02:00:00+00:00",
  "review_version": null,
  "review_ai_request_version": 2
}
```

`kind` 枚举：

- `initial`：创建任务后的原始 operation；
- `review_ai`：生成 AI Review 建议；
- `generate_cases`：确认 Review 后生成测试用例。

旧任务没有 `execution.json` 时，Runner 按原逻辑推断，保证兼容。

### 4.5 AI：异步结构化建议

AI 不返回完整替换草稿，只返回 `add/replace` 建议。服务端解析、规范化、过滤非法项并生成稳定 `suggestion_id`。原始模型响应不发布、不展示、不登记为下载产物。

### 4.6 配置：平台配置目录 + 环境 Release

需要新增 Alembic 迁移登记配置定义。该迁移只增加配置目录元数据，不保存任务或测试点正文，因此不违反“不新增测试点数据库表”的产品决策。

目录默认值对所有环境取安全值 `false`；dev Release 显式发布 `ONLINE_REVIEW_ENABLED=true`、`REVIEW_AI_ENABLED=true`，prod 首次发布保持 false。

---

## 5. 目标架构

### 5.1 组件关系

```text
Browser
  │
  │ GET/PUT Review、POST AI、POST resume
  ▼
Nginx auth_request
  │ 可信身份头 + 权限
  ▼
Functional Flask App
  ├── ReviewService
  │    ├── ReviewValidator
  │    ├── ReviewDiff
  │    └── TaskStore
  ├── TaskManager（单槽持久化 FIFO）
  └── PlatformClient（配置快照/审计）
          │
          ▼
    execution.json + request.json
          │
          ▼
Functional Runner 子进程
  ├── initial → 现有测试点工作流
  ├── review_ai → ReviewAIAdapter → LLM
  └── generate_cases → 现有用例工作流
```

### 5.2 人工 Review 数据流

```text
原始测试点 artifact
  → GET review
  → 浏览器表格编辑
  → PUT review-draft（revision CAS）
  → review-draft.json
  → POST resume
  → review-test-points-vN.json
  → execution.kind=generate_cases
  → pending（按 queued_at 排队）
  → Runner 读取确认 JSON
```

### 5.3 AI Review 数据流

```text
已保存草稿 revision/SHA
  → POST review-ai
  → request-vN.json
  → execution.kind=review_ai
  → pending/running
  → ReviewAIAdapter 调用 LLM
  → suggestions-vN.json
  → waiting_review/review_ai_ready
  → 浏览器差异预览
  → 用户选择应用（仅浏览器状态）
  → PUT review-draft
```

### 5.4 故障边界

| 故障 | 结果 |
|---|---|
| 草稿保存前校验失败 | 不写文件，返回错误；浏览器内容保留 |
| 草稿文件已写、任务索引未写 | GET 时从文件信封修复索引 |
| AI 请求队列满 | 不改变任务状态；请求文件可复用或清理为未提交孤儿 |
| AI 模型失败 | 回到 `waiting_review/review_ai_failed`，草稿不变 |
| AI Runner 中断 | 回到 `waiting_review`，记录 `WORKER_INTERRUPTED` |
| 正式生成失败 | 按既有语义进入 `failed` |
| AI 迟到结果 | execution sequence 不一致，丢弃，不覆盖新阶段 |
| 浏览器 revision 过期 | 409，禁止覆盖 |
| 平台配置不可用 | 写请求失败关闭；已保存文件可读 |

---

## 6. 推荐目录与文件设计

### 6.1 `AItestcase_Agents` 新增

```text
services/common/review.py
services/functional_agent/review_ai.py
agents/functional_test/prompts/review_test_points.py
services/common/static/review-workbench.js
services/common/static/review-workbench.css
tests/services/test_review_domain.py
tests/services/test_review_ai.py
```

新增理由：

- Review 规范化、校验、diff 和文件事务超过上传工具职责，单独领域模块可避免继续膨胀 `web.py/uploads.py`；
- AI Adapter 与现有 LangGraph 工作流职责不同，独立模块避免改变原 Prompt 和工作流；
- Review 页面状态复杂，拆出专用资源避免公共 100 行脚本变成不可维护单文件。

### 6.2 `AItestcase_Agents` 修改

```text
services/common/web.py
services/common/task_store.py
services/common/task_manager.py
services/common/task_models.py
services/common/errors.py
services/common/uploads.py
services/common/templates/base.html
services/common/templates/task_detail.html
services/common/static/agent-workbench.js
services/functional_agent/app.py
services/functional_agent/adapter.py
services/functional_agent/runner.py
tests/services/test_task_runtime.py
tests/services/test_web_routes.py
tests/services/test_uploads_artifacts.py
requirements-functional-agent.lock（仅依赖确实变化时）
```

### 6.3 `test-platform` 新增

```text
backend/alembic/versions/20260813_0010_add_online_review_config.py
```

### 6.4 `test-platform` 修改

```text
backend/tests/test_migrations.py
backend/tests/test_phase2.py（配置读取边界需要时）
tests/test_smoke.py
README.md
```

Nginx 当前 `/functional-test-agent/` 已覆盖全部子路由、可信身份头、6 MiB 请求和 60 秒短请求超时。AI 调用异步返回 202，不需要把 Nginx 超时提高到 600 秒。

Compose 当前已提供独立只读容器、任务卷、非 root 用户和功能 LLM Secret，不需要新增服务或卷。只需重建功能智能体镜像。

### 6.5 明确不修改

- `agents/functional_test/prompts/generator_*` 和 `supplement_*` 的现有内容；
- `generator_test_points`、`generator_case` 业务接口；
- API 智能体 Runner、数据库开关和目标访问开关；
- 平台主 React 应用架构；
- 历史 `output/`；
- prod Secret 明文。

---

## 7. Review 领域模型

### 7.1 Pydantic 模型

建议在 `services/common/review.py` 定义：

```python
class ReviewPoint(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = ""
    module: str = ""
    feature: str = ""
    scenario: str = ""
    test_point: str = ""
    risk_level: str = ""

class ValidationIssue(BaseModel):
    level: Literal["error", "warning"]
    code: str
    row_index: int | None = None
    point_id: str | None = None
    field: str | None = None
    message: str
    related_rows: list[int] = []

class ReviewValidation(BaseModel):
    valid_for_resume: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]

class ReviewDiffSummary(BaseModel):
    added: int
    modified: int
    deleted: int
    unchanged: int
    risk_changed: int

class ReviewDraftEnvelope(BaseModel):
    schema_version: int = 1
    revision: int
    content_sha256: str
    base_generated_sha256: str
    saved_by_user_id: str
    saved_by_username: str
    saved_at: str
    test_points: list[dict[str, Any]]
```

`ReviewPoint` 允许扩展字段，保存时标准字段排在前面，扩展字段按原对象键值保留。

### 7.2 Review revision 与 TaskStore revision

两者必须分离：

| revision | 作用 | 变化时机 |
|---|---|---|
| `task.internal.revision` | 任意任务记录写入版本 | 状态、日志元数据、配置等更新 |
| `review_draft.revision` | 草稿乐观锁 | 草稿正文 SHA 变化并成功保存 |
| `execution.sequence` | Runner 迟到结果隔离 | 每次进入 FIFO |
| `review.version` | 不可变确认文件版本 | 新 SHA 被确认 |
| `review_ai.request_version` | AI 请求/建议版本 | 新 AI 请求被接受 |

禁止用任一版本替代其他版本。

### 7.3 标准字段和扩展字段

标准字段保存顺序：

```text
id, module, feature, scenario, test_point, risk_level, <其他字段原顺序>
```

处理规则：

- 标准字段值必须是字符串；
- 标准字段仅去除首尾空白；
- 不改变正文大小写；
- 扩展字段可为 JSON 合法值；
- 浏览器不编辑扩展字段，但保存时必须原样带回；
- 客户端使用 `_rowKey` 作为临时行标识，提交前必须移除所有以下划线开头的客户端私有字段；
- 服务端拒绝浏览器提交保留内部字段，如 `relative_path`、`sha256`、`revision` 嵌入单行对象。

---

## 8. 规范化、校验与 Diff

### 8.1 规范化函数

```python
def normalize_for_storage(points: list[dict]) -> list[dict]: ...
def normalize_compare_text(value: str) -> str: ...
def canonical_review_bytes(points: list[dict]) -> bytes: ...
def review_content_sha256(points: list[dict]) -> str: ...
```

`canonical_review_bytes` 固定：

- UTF-8；
- `ensure_ascii=False`；
- `sort_keys=True`；
- 紧凑分隔符 `(',', ':')`；
- SHA 只覆盖规范化测试点列表，不覆盖保存人和时间。

### 8.2 阻塞错误

稳定错误码建议：

| code | 条件 |
|---|---|
| `POINTS_EMPTY` | 列表为空 |
| `POINTS_LIMIT_EXCEEDED` | 超过 5,000 条 |
| `REVIEW_SIZE_EXCEEDED` | 规范化内容超过字节/字符限制 |
| `POINT_NOT_OBJECT` | 行不是对象 |
| `FIELD_REQUIRED` | 标准字段为空 |
| `FIELD_TOO_LONG` | 字段超过 PRD 上限 |
| `FIELD_TYPE_INVALID` | 标准字段不是字符串 |
| `POINT_ID_DUPLICATE` | ID 重复 |
| `POINT_EXACT_DUPLICATE` | 完全重复键重复 |
| `RISK_LEVEL_INVALID` | 非 P0～P3 |
| `TEXT_CONTAINS_NUL` | 文本包含 NUL |
| `CLIENT_PRIVATE_FIELD` | 提交客户端私有字段 |

### 8.3 非阻塞警告

| code | 条件 |
|---|---|
| `POINT_ID_NON_STANDARD` | ID 不匹配 `^TP\d{3,}$` |
| `POINT_TEXT_TOO_SHORT` | `test_point` 少于 2 字符 |
| `POINT_TEXT_REUSED` | 不同上下文使用相同测试点文本 |
| `RISK_LEVEL_CHANGED` | 同 ID 风险等级改变 |
| `DELETE_RATIO_HIGH` | 删除比例大于 30% |
| `ADD_RATIO_HIGH` | 新增比例大于 50% |

### 8.4 重复键

比较键：

```text
normalize(module)
  + U+001F
  + normalize(feature)
  + U+001F
  + normalize(scenario)
  + U+001F
  + normalize(test_point)
```

`normalize`：Unicode 字符保持原样、首尾去空白、连续空白折叠、英文字母 `casefold()`。本期不做中文同义词判断。

### 8.5 Diff 算法

以 `id` 为稳定主键：

- 原始无该 ID、草稿有：added；
- 原始有、草稿无：deleted；
- 两边同 ID 且规范化对象不同：modified；
- 两边同 ID 且规范化对象相同：unchanged；
- ID 被编辑：表现为一条 deleted + 一条 added；
- 扩展字段变化计入 modified；
- `risk_level` 变化同时增加 `risk_changed`。

复杂度目标为 O(n)，禁止每行与所有行做 O(n²) 比较。

### 8.6 校验返回定位

所有 issue 返回：

- `row_index`：原提交数组下标，0 起；
- `point_id`：可用时返回；
- `field`：单元格问题返回；
- `related_rows`：重复冲突所有下标；
- `message`：稳定中文文案。

前端不得解析中文文案判断逻辑，只使用 `code/field/row_index`。

---

## 9. 文件与一致性设计

### 9.1 任务目录

```text
runtime/<env>/functional/tasks/<task_id>/
├── task.json
├── request.json
├── execution.json
├── runner-result.json
├── artifacts.json
├── console.log
├── input/
│   ├── source.md
│   ├── review-draft.json
│   ├── review-test-points-v1.json
│   ├── review-test-points-v2.json
│   └── review-ai/
│       ├── request-v1.json
│       ├── suggestions-v1.json
│       └── ...
├── work/
└── published/
    └── test-points/<generated>.json
```

### 9.2 原始测试点定位

优先使用 `task.review_source.artifact_id`，在初次测试点发布时由功能 Adapter 写入：

```json
{
  "artifact_id": "artifact_xxx",
  "sha256": "...",
  "test_point_count": 53
}
```

对旧任务：从 `artifacts.json` 中选择 `type=test_points_json` 且 `created_at` 最新的登记产物；只能通过 artifact registry 解析，禁止搜索用户传入路径。

### 9.3 草稿信封写入顺序

在 TaskStore 锁内：

1. 读取当前 `review-draft.json`，缺失时 revision=0；
2. 比较客户端 revision/SHA；
3. 规范化、校验和计算 content SHA；
4. SHA 未变化时直接返回，不增加 revision；
5. 构造 revision+1 的完整信封；
6. 原子写 `review-draft.json`；
7. 更新 `task.json.review_draft` 摘要；
8. 保存任务记录；
9. 返回新 revision。

如果第 6 步成功、第 8 步失败，下一次 GET 读取草稿信封并修复 `task.json.review_draft`。文件信封永远优先于索引摘要。

### 9.4 确认版本写入顺序

在同一锁内：

1. 重读草稿信封并比较 revision/SHA；
2. 执行完整校验；
3. 检查警告确认；
4. 检查 Idempotency-Key 哈希；
5. 若现有确认版本 SHA 相同，复用该版本；
6. 否则计算下一个版本号并原子写不可变文件；
7. 在有队列容量时写 `execution.json(kind=generate_cases)`；
8. 更新 `request.json.review_relative_path` 兼容旧 Runner；
9. 更新任务 `review`、`queued_at`、`status=pending`；
10. 通知调度器。

队列满时仍允许执行第 6 步并保存 `review` 元数据，但不写新的 execution、不改状态。重试时复用同 SHA 版本。

### 9.5 不可变文件

确认版本与 AI request/suggestion 文件使用 `open('xb')` 或“目标不存在才原子发布”。已存在版本禁止覆盖；内容不一致时返回 `STORAGE_WRITE_FAILED` 并记录运维错误。

### 9.6 下载

- 原始文件继续走 artifact ID；
- 草稿和确认版本增加逻辑类型下载接口，服务端从任务元数据解析；
- 响应使用 `Content-Disposition: attachment`；
- 对外文件使用纯测试点列表或兼容 `{"test_points": [...]}`，不返回内部保存人、路径等信封元数据；
- revision 冲突时“下载我的未保存版本”完全在浏览器通过 Blob 生成，不上传服务器。

---

## 10. TaskStore 与锁设计

### 10.1 新增原语

建议扩展：

```python
@contextmanager
def locked(self):
    with self._lock:
        yield

def load_json(self, task_id: str, relative_path: str) -> Any: ...
def atomic_create_json(self, path: Path, payload: Any) -> None: ...
```

所有相对路径先 `resolve()` 并确认位于任务目录内。调用方不能传浏览器提供的路径。

### 10.2 单进程假设

当前生产 Gunicorn 固定单 worker、多线程；TaskStore 的 `RLock` 可以覆盖 Web 请求和 TaskManager 线程的竞争。不得为了提高 HTTP 吞吐临时增加多个 worker，否则文件锁与队列锁不再跨进程有效。

若未来改多 worker，必须先引入跨进程锁或外部队列，非本期范围。

### 10.3 锁顺序

统一顺序：

```text
TaskManager._condition → TaskStore._lock
```

ReviewService 独立保存只获取 TaskStore 锁；需要状态入队时通过 TaskManager 方法完成，禁止先持有 TaskStore 锁再等待 Condition，避免死锁。

建议把“确认文件准备”和“任务入队”封装在 TaskManager 的单个公开方法中，由其按固定锁序执行。

---

## 11. 执行信封、状态机与 FIFO

### 11.1 任务主状态

主状态枚举保持不变：

```text
pending, running, waiting_review, succeeded, failed, cancelled
```

使用 `stage` 和 `execution.kind` 区分 Review AI，不新增主状态，避免列表、保留策略和平台权限大范围变化。

### 11.2 新增阶段

```text
review_editing
review_ai_queued
review_ai_running
review_ai_ready
review_ai_failed
review_ai_cancelled
review_confirmed_queue_full
queued
generating_test_cases
```

### 11.3 合法转换

```text
waiting_review/review_editing
  → pending/review_ai_queued
  → running/review_ai_running
  → waiting_review/review_ai_ready

running/review_ai_running
  → waiting_review/review_ai_failed
  → waiting_review/review_ai_cancelled

waiting_review/*
  → pending/queued
  → running/generating_test_cases
  → succeeded/failed
```

AI 子阶段错误不会写主任务 `finished_at`；正式用例生成失败仍写终态。

### 11.4 Execution sequence

每次入队递增 `task.internal.execution_sequence`，同时写入 execution 和 runner-result。TaskManager 应用结果前必须满足：

```text
runner_result.execution_sequence == task.internal.execution_sequence
runner_result.execution_kind == task.internal.execution_kind
```

不匹配视为迟到结果，记录日志后丢弃。

### 11.5 FIFO

`TaskStore.pending_fifo()` 排序键改为：

```python
(record.get("queued_at") or record.get("created_at", ""), record["id"])
```

队列上限仍统计 `pending` 数量，AI 辅助与正式生成共同占等待位。正在运行的一个任务不计入 5 个等待任务。

### 11.6 入队互斥

以下操作在同一 Condition 锁内重新读取状态：

- `enqueue_review_ai(...)`；
- `resume_with_review(...)`；
- `cancel_review_ai(...)`；
- `cancel(...)`。

两个请求同时竞争时，只有第一个从 `waiting_review` 转为 `pending` 的请求成功，另一个返回 `INVALID_TASK_STATE` 或幂等成功，不允许同一任务出现两个 pending 执行。

### 11.7 AI 超时与失败

TaskManager 根据 execution kind 选择超时：

```python
timeout = REVIEW_AI_TIMEOUT_SECONDS if kind == "review_ai" else TASK_TIMEOUT_SECONDS
```

AI 非零退出、配置错误、超时、取消和启动异常统一调用 `_return_to_review(...)`：

- `status=waiting_review`；
- `stage=review_ai_failed/review_ai_cancelled`；
- `review_ai.status=failed/cancelled`；
- 错误写入 `review_ai.error_code/error_message`；
- 清空 PID 和子阶段取消标记；
- 不设置 `finished_at`；
- 不清空主任务结果摘要和产物。

### 11.8 取消

新增 `cancel_review_ai`：

- pending review_ai：直接回到 waiting_review；
- running review_ai：设置 `internal.review_ai_cancel_requested_at` 并终止当前进程组；
- 非 review_ai：返回 `INVALID_TASK_STATE`；
- 不复用全任务 `cancel_requested_at`，否则会误把任务变为 cancelled。

原“取消任务”仍可把 waiting_review 或任意主执行阶段变为 cancelled。

### 11.9 启动恢复

`recover_interrupted()`：

- `running + execution_kind=review_ai` → `waiting_review/review_ai_failed`，错误 `WORKER_INTERRUPTED`；
- 其他 running → 保持既有 `failed/WORKER_INTERRUPTED`；
- pending 保留并重新 FIFO；
- waiting_review 保留；
- 清理 `.tmp`，不清理不可变 request/suggestion 文件；
- 存在草稿信封但索引缺失时由首次 GET 惰性修复。

---

## 12. AI Review Adapter 设计

### 12.1 模块职责

`services/functional_agent/review_ai.py` 负责：

- 读取已确认的 AI 请求文件；
- 读取基准草稿并校验 revision/SHA；
- 构建最小需求上下文；
- 调用当前配置的 LLM；
- 解析并修复一次 JSON；
- 校验建议动作和字段；
- 过滤非法建议；
- 为合法建议生成稳定 ID；
- 原子保存建议文件；
- 返回结构化元数据。

不负责：

- 应用建议到草稿；
- 修改任务状态；
- 直接操作 FIFO；
- 生成测试用例；
- 输出模型思维链。

### 12.2 请求模型

```python
class ReviewAIRequest(BaseModel):
    schema_version: int = 1
    request_version: int
    operation: Literal[
        "supplement",
        "rewrite_selected",
        "generate_from_instruction",
    ]
    base_revision: int
    base_sha256: str
    selected_ids: list[str] = []
    scope: dict[str, list[str]] = {}
    instruction: str = ""
    requested_by_user_id: str
    requested_at: str
    idempotency_key_sha256: str
    request_sha256: str
```

服务端生成 `request_sha256`，浏览器不能指定。

### 12.3 建议模型

```python
class ReviewSuggestion(BaseModel):
    suggestion_id: str
    action: Literal["add", "replace"]
    target_id: str | None = None
    point: dict[str, Any]
    reason: str = Field(max_length=500)
    source_basis: str = Field(max_length=1000)
    validation: ReviewValidation

class ReviewAISuggestionEnvelope(BaseModel):
    schema_version: int = 1
    request_version: int
    operation: str
    base_revision: int
    base_sha256: str
    model_name: str
    prompt_bundle_sha256: str
    started_at: str
    finished_at: str
    summary: str
    suggestions: list[ReviewSuggestion]
    rejected_suggestions: list[dict[str, str]]
    warnings: list[str]
```

### 12.4 三种操作

#### `supplement`

- 输入作用域内现有测试点的简表；
- 输入需求结构化上下文；
- 只接受 `action=add`；
- 与当前草稿完全重复的建议进入 rejected；
- 最多 200 条。

#### `rewrite_selected`

- `selected_ids` 1～100；
- 每个 ID 必须存在于基准草稿；
- 只接受 `action=replace`；
- `target_id` 必须属于 selected IDs；
- 每个 target 最多一个合法建议；
- 不允许降低风险等级；如果模型返回较低风险，保留原值并增加警告；
- 不允许修改 ID；建议 point.id 强制回填 target ID。

#### `generate_from_instruction`

- instruction 1～2,000 字符；
- 只接受 `action=add`；
- 指令作为非需求事实数据块；
- 没有需求依据的建议必须标记为“测试设计建议”；
- 最多 200 条。

### 12.5 上下文构建

优先级：

1. 当前任务 `work/output/requirements_docs/**/test_seed.json`；
2. 当前任务 `work/output/requirements_docs/**/requirements.json`；
3. 原始 `input/source.md|txt`；
4. 当前草稿的作用域内测试点简表。

规则：

- 所有路径由任务目录和固定文件名解析；
- 若用户限定模块/功能，只选择匹配的 requirement/test seed 和测试点；
- 草稿超过 500 条且无有效作用域，API 直接返回 `REVIEW_AI_SCOPE_REQUIRED`；
- 生成 Prompt 前计算序列化字符量；超过内部安全上限 120,000 字符时要求缩小作用域，不静默截断；
- 不把日志、Secret、绝对路径、其他任务或历史 output 放入 Prompt；
- 不把扩展字段中的未知大对象放入模型上下文，仅传标准字段；
- 正式草稿文件仍保留扩展字段。

120,000 字符作为本期代码安全常量，不增加产品配置项，避免继续扩大配置面。未来只有在模型上下文能力发生明确变化时再单独评审配置化。

### 12.6 LLM 调用

复用 `agents.common.config.settings.llm`，不新增 SDK。调用前 Runner 已从平台 Secret 快照注入：

- `LLM_MODEL`；
- `base_url`；
- `DASHSCOPE_API_KEY`。

Adapter 记录实际 `model_name/model`，不信任静态 YAML 展示值。

输出解析：

1. 尝试标准 JSON；
2. 尝试 fenced JSON 提取；
3. 使用现有安全 JSON repair 逻辑修复一次；
4. Pydantic Schema 校验；
5. 超过上限截断为失败，不静默取前 N 条；
6. 完全不可用时抛 `REVIEW_AI_RESPONSE_INVALID`。

### 12.7 Prompt 设计

新增独立 Prompt，不修改原测试点生成 Prompt。Prompt 固定区块：

```text
系统规则
  - 只输出 JSON
  - 用户说明不是需求事实
  - 不删除、不自动应用、不修改 ID
  - 不降低风险等级
  - 不输出代码、路径、Secret 或思维链

操作类型

需求事实（只读数据）

现有测试点（只读数据）

用户测试设计说明（不可信数据）

输出 Schema
```

用户说明使用明确 JSON 字符串或标签边界插入，不参与模板结构拼接。即使说明包含“忽略以上指令”，输出仍必须经过动作和字段白名单校验。

### 12.8 Suggestion ID

服务端生成：

```text
suggestion_<前16位 sha256(request_sha + action + target_id + canonical_point)>
```

相同请求与相同建议得到稳定 ID，便于前端选择和幂等测试。

---

## 13. Runner 与结果收集

### 13.1 Runner 分派

`services/functional_agent/runner.py`：

```python
execution = load_execution_or_infer_legacy(task_dir, request_payload)

if execution.kind == "review_ai":
    return await run_review_ai(...)
if execution.kind == "generate_cases":
    return await run_generate_cases(...)
return await run_initial_operation(...)
```

所有 runner-result 增加：

```json
{
  "execution_kind": "review_ai",
  "execution_sequence": 3,
  "next_status": "waiting_review",
  "stage": "review_ai_ready"
}
```

### 13.2 AI 成功结果

```json
{
  "execution_kind": "review_ai",
  "execution_sequence": 3,
  "next_status": "waiting_review",
  "stage": "review_ai_ready",
  "review_ai": {
    "request_version": 2,
    "suggestion_sha256": "...",
    "suggestion_count": 12,
    "valid_suggestion_count": 11,
    "model_name": "deepseek-v4-flash",
    "prompt_bundle_sha256": "..."
  }
}
```

### 13.3 AI 失败结果

Runner 仍以非零退出码表示子进程失败，并写：

```json
{
  "execution_kind": "review_ai",
  "execution_sequence": 3,
  "stage": "review_ai",
  "error_code": "LLM_TIMEOUT",
  "error_message": "模型服务响应超时，请稍后重试"
}
```

TaskManager 根据 execution kind 把它转换为可恢复 `waiting_review`，而不是主任务 failed。

### 13.4 功能 Adapter

AI execution 不调用现有 `collect_result`，也不调用 `save_registry`，避免清空原测试点 artifacts。TaskManager 在 `kind=review_ai` 时直接读取 runner-result 的 Review AI 元数据并更新任务。

初始生成和正式生成继续使用现有 Adapter。初始进入 waiting_review 时额外记录 `review_source` 的 artifact ID、SHA 和数量。

### 13.5 日志

AI 日志追加到同一 `console.log`，每段增加可读边界：

```text
[review_ai request=v2 sequence=3] started
[review_ai request=v2 sequence=3] completed suggestions=12 valid=11
```

不得记录：

- Prompt 全文；
- 用户说明全文；
- 测试点正文全集；
- LLM 原始响应；
- API Key、Base URL 查询参数或绝对路径。

---

## 14. HTTP API 详细设计

### 14.1 公共约束

- Base：`/functional-test-agent/api/v1`；
- JSON 响应 UTF-8；
- 写请求要求 `tool.execute`，取消 AI 要求 `task.cancel`；
- 所有权或 `task.view.all`；
- 越权与不存在统一 404；
- 所有 PUT/POST 双提交 CSRF；
- 错误结构保持 `{"error":{"code","message","request_id","details?"}}`；
- `details` 使用显式安全白名单，不放正文、路径或 Secret。

### 14.2 `GET /tasks/{id}/review`

处理：

1. 权限和所有权；
2. 判断在线 Review 开关；
3. 解析原始 artifact；
4. 加载草稿信封或初始化 revision 0；
5. 必要时修复 task 索引；
6. 运行校验与 diff；
7. 返回点列表和安全元数据。

`editable=true` 条件：

- 功能工具；
- `ONLINE_REVIEW_ENABLED=true`；
- status=waiting_review；
- 用户有 tool.execute；
- 文件未过期；
- 当前没有 pending/running AI 子阶段。

### 14.3 `PUT /tasks/{id}/review-draft`

请求体：

```json
{"revision":3,"sha256":"...","points":[]}
```

响应 200：

```json
{
  "revision": 4,
  "sha256": "...",
  "saved_at": "...",
  "saved_by": "tester",
  "validation": {"valid_for_resume": false, "errors": [], "warnings": []},
  "diff_summary": {}
}
```

幂等：正文 SHA 与当前相同返回当前 revision；保存人/时间不刷新，避免无意义审计噪声。

### 14.4 `POST /tasks/{id}/review-draft/import`

- multipart `review_file + revision`；
- 沿用 MIME、UTF-8、5 MiB、500,000 字符和 5,000 条；
- 解析包装对象或列表；
- 进入同一个 `save_draft`；
- 不直接 resume；
- 成功返回 200。

### 14.5 `POST /tasks/{id}/resume`

按 Content-Type 分派：

- `application/json`：新在线流程；
- `multipart/form-data`：旧兼容流程。

JSON 请求：

```json
{
  "revision": 4,
  "sha256": "...",
  "accept_warnings": true
}
```

Header：`Idempotency-Key`，长度 8～128，只存 SHA-256。

旧 multipart 流程内部改为：导入草稿 → 完整校验 → 生成确认版本 → 入队，保持一次请求可继续的旧行为。

### 14.6 `GET /tasks/{id}/review/download`

Query：

- `kind=generated`：重定向/发送原始 artifact；
- `kind=draft`：导出当前草稿点列表；
- `kind=confirmed&version=N`：导出确认版本。

服务端只解析枚举和整数版本，不接受路径。

### 14.7 `POST /tasks/{id}/review-ai`

请求：

```json
{
  "revision": 4,
  "sha256": "...",
  "operation": "supplement",
  "selected_ids": [],
  "scope": {"modules": ["登录"], "features": []},
  "instruction": ""
}
```

处理顺序：

1. 开关、权限、CSRF、所有权；
2. 状态必须 waiting_review；
3. 草稿 CAS；
4. 操作参数和作用域限制；
5. 队列容量；
6. Idempotency-Key/请求 SHA；
7. 创建不可变 request-vN；
8. 写 execution(kind=review_ai)；
9. 更新任务 pending、queued_at、review_ai；
10. 通知调度器；
11. 返回 202。

### 14.8 `GET /tasks/{id}/review-ai`

响应：

```json
{
  "status": "ready",
  "request_version": 2,
  "operation": "supplement",
  "base_revision": 4,
  "base_sha256": "...",
  "model_name": "deepseek-v4-flash",
  "prompt_bundle_sha256": "...",
  "started_at": "...",
  "finished_at": "...",
  "suggestions": [],
  "rejected_count": 1,
  "warnings": []
}
```

建议正文只在 status=ready 且文件校验 SHA 成功时返回。文件损坏返回 `REVIEW_AI_RESPONSE_INVALID`，不返回部分未验证内容。

### 14.9 `POST /tasks/{id}/review-ai/cancel`

- 网关因路径以 `/cancel` 结尾自动要求 `task.cancel`；
- 工具服务二次要求 task.cancel 和所有权；
- pending/running review_ai 可取消；
- 返回 200（已回 Review）或 202（终止请求已接受）；
- 与主任务 cancel 分离。

### 14.10 ServiceError details

扩展 `ServiceError`：

```python
details: dict[str, Any] | None = None
```

只允许以下详情：

- `current_revision`；
- `current_sha256`；
- `saved_at`；
- `saved_by`；
- `validation`；
- `max_points/max_bytes/max_characters`；
- `queue_max_waiting`。

不得直接把异常对象、文件路径或模型响应放入 details。

---

## 15. 权限、CSRF 与审计

### 15.1 网关权限映射

现有映射可以覆盖新接口：

| 方法/路径 | 网关权限 |
|---|---|
| GET `.../tasks/{id}/review*` | `tool.result.view` |
| PUT/POST Review | `tool.execute` |
| POST `.../review-ai/cancel` | `task.cancel` |

无需新增权限码。必须增加映射单元测试，防止 `/review-ai/cancel` 被普通 tool.execute 放行。

### 15.2 工具服务二次校验

- 查看：`require_task_access(..., tool.result.view)`；
- 编辑、AI、resume：`require_task_access(..., tool.execute)`；
- AI cancel：`require_task_access(..., task.cancel)`；
- 所有写请求 `require_csrf`；
- 管理员跨任务编辑必须同时具有操作权限和 `task.view.all`；
- 只具有 `task.view.all` 不能编辑。

### 15.3 审计

增加 action：

```text
agent.review.draft.save
agent.review.draft.import
agent.review.resume
agent.review.conflict
agent.review.ai.request
agent.review.ai.complete
agent.review.ai.cancel
agent.review.ai.failed
```

metadata 只保存版本、SHA、数量、稳定错误码、模型和 Prompt 版本。用户 instruction 只保存 SHA，不保存正文。

### 15.4 CSRF

原生 fetch 继续自动附加 `X-CSRF-Token`。multipart import 也使用 Header，不依赖隐藏字段。Cookie/Header 不一致返回 403。

---

## 16. 前端状态与模块设计

### 16.1 页面加载

Jinja 只渲染任务壳、权限布尔值、base path 和 feature flag；测试点数据通过 GET API 异步加载，避免把大 JSON 嵌入 HTML。

### 16.2 浏览器状态

```javascript
const reviewState = {
  taskId: "",
  originalPoints: [],
  points: [],
  revision: 0,
  sha256: "",
  validation: { errors: [], warnings: [] },
  diffSummary: {},
  selectedRowKeys: new Set(),
  filters: {},
  collapsedModules: new Set(),
  page: 1,
  pageSize: 100,
  dirty: false,
  saving: false,
  editable: false,
  ai: null,
};
```

每行在内存增加 `_rowKey=crypto.randomUUID()`；提交前转换为纯 JSON，移除 `_rowKey`。

### 16.3 模块拆分

`review-workbench.js` 内部使用 IIFE/模块级函数分区，不引入框架：

```text
API client
State reducer
Validation mirror
Filter/pagination selectors
Table renderer
Draft actions
AI actions
Dialog/focus helpers
beforeunload guard
```

禁止在 HTML 中拼接用户正文。所有文本使用 `textContent`，属性值使用 DOM API。

### 16.4 客户端校验

客户端镜像服务端确定性规则，用于即时反馈，但：

- 保存结果以服务端 validation 覆盖客户端结果；
- 客户端不决定最终可 resume；
- 客户端错误码与服务端共用常量表；
- 不在客户端做 LLM、语义去重或安全判断。

### 16.5 筛选与分页

流程：

```text
完整 points
  → 校验/修改状态标注
  → 关键字和多选筛选
  → 模块分组/折叠
  → 分页切片
  → DOM 渲染
```

- 默认 100 条；
- 切换 50/100/200；
- 筛选完整数据；
- 修改后保留合理页码；
- DOM 同时最多渲染 200 行；
- 5,000 条只在内存中保存，不一次生成 5,000 行 DOM。

### 16.6 编辑交互

- 输入框在 `change/input` 后更新 state；
- Tab/Shift+Tab 使用浏览器自然顺序；
- Enter 移到下一行同列；
- Escape 恢复单元格聚焦时的快照；
- 删除记录最近一次删除动作，提供一次撤销；
- 批量删除使用原生可访问 dialog；
- 新增 ID 从现有 `TP<number>` 最大值+1 开始，补足三位；
- 复制后立即触发完全重复错误；
- 风险使用 select。

### 16.7 Dirty 与离开保护

- 任意点内容变化设置 dirty；
- 保存成功且服务端 SHA 与当前内容一致后清除 dirty；
- `beforeunload` 仅 dirty 时启用；
- 站内“返回平台”等链接点击时使用同一确认；
- 冲突时保留 dirty，提供 Blob 下载。

---

## 17. 页面与视觉详细设计

### 17.1 页面层级

```text
任务标题 + 状态
下一步说明 / 可恢复错误
Review 摘要条
筛选工具栏
AI 辅助工具栏
测试点表格
AI 建议面板
固定操作栏
高级 JSON 操作
原产物 / 日志 / 生成信息
```

### 17.2 视觉约束

- 最大宽度沿用 1280px；
- 背景、文本、系统蓝和状态色复用现有 token；
- 表格为一个内容区域，不把每行做成卡片；
- sticky 表头；
- 固定底部操作栏只在 Review 区域可见时使用轻微边框/实色背景；
- AI 区使用中性次级样式，不使用紫色渐变、发光或聊天气泡；
- 建议 diff 使用文本标签“新增/修改/冲突”，颜色仅辅助；
- 动画 150～250ms，reduced-motion 关闭。

### 17.3 Review 摘要

展示：总数、新增、修改、删除、错误、警告、revision、保存状态。数字来自当前 state 或服务端响应，不显示虚假完成率。

### 17.4 AI 操作栏

三个明确按钮：

- “AI 补全缺失测试点”；
- “AI 改写已选测试点”；
- “按说明生成建议”。

按钮旁显示说明：“AI 只生成建议，不会自动修改或继续任务”。

禁用原因以可读文本展示：未保存、未选择、作用域过大、功能关闭、任务不在 Review 状态。

### 17.5 AI 建议面板

- 默认关闭，ready 后自动显示入口但不强制夺取焦点；
- 新增建议展示完整字段；
- replace 使用两列当前/建议值；
- 显示 reason 和 source_basis；
- 默认无选择；
- “应用选中”后关闭或保留面板均可，但必须提示尚未保存；
- 基准过期时显示冲突原因；
- 丢弃只改变浏览器展示，不删除不可变建议文件。

### 17.6 错误摘要与焦点

错误摘要按行和字段分组。点击错误：

1. 清除会隐藏该行的筛选；
2. 切换到对应页；
3. 展开模块；
4. 聚焦具体单元格；
5. 使用 `aria-describedby` 关联错误文本。

### 17.7 对话框

使用原生 `<dialog>` 或项目现有可访问实现：

- 批量删除确认；
- 接受非阻塞警告；
- 重置原始版本；
- AI 按说明输入；
- revision 冲突处理。

支持 Escape、焦点循环、关闭后焦点恢复。不可撤销动作说明后果；单行删除有撤销，不强制弹窗。

### 17.8 空、加载与错误状态

| 状态 | 设计 |
|---|---|
| 初始加载 | 表格骨架 + “正在读取测试点” |
| 无原始产物 | 错误面板 + 日志/刷新入口 |
| 只读 | 保留表格，隐藏编辑控件，说明原因 |
| 保存失败 | 固定错误条 + 重试，内存数据不清空 |
| revision 冲突 | 服务器版本信息 + 重新加载 + 下载本地 JSON |
| AI 排队/运行 | 编辑器只读，阶段和取消 AI 按钮 |
| AI 失败 | 稳定错误码 + 重试/继续人工编辑 |
| 文件过期 | 410 说明，不渲染空假数据 |

### 17.9 可访问性

- 语义 `<table>`、`<thead>`、`<th scope>`；
- 每个输入有列名和行 ID 组成的可访问名称；
- 状态不能只靠颜色；
- `aria-live=polite` 用于保存和 AI 状态；
- 批量删除等高风险结果用明确对话框；
- 正文对比度 WCAG AA；
- 1280px 以上桌面优先，横向溢出只发生在表格容器；
- 长文本可展开查看且不依赖 hover。

---

## 18. 配置与平台迁移

### 18.1 新迁移

建议 revision：

```text
20260813_0010
down_revision = 20260812_0009
```

只向 `config_definitions` 插入功能工具配置：

| Key | 类型 | 目录默认 | 校验 |
|---|---|---:|---|
| `ONLINE_REVIEW_ENABLED` | bool | false | - |
| `REVIEW_AI_ENABLED` | bool | false | - |
| `REVIEW_AI_TIMEOUT_SECONDS` | int | 600 | 60～1800 |
| `REVIEW_AI_MAX_SELECTED_POINTS` | int | 100 | 1～500 |
| `REVIEW_AI_MAX_SUGGESTIONS` | int | 200 | 1～500 |
| `REVIEW_AI_MAX_CONTEXT_POINTS` | int | 500 | 1～1000 |
| `REVIEW_AI_MAX_INSTRUCTION_CHARACTERS` | int | 2000 | 1～10000 |

模型上下文总字符安全上限固定为 120,000，不进入本期配置目录。

### 18.2 Upgrade

- 使用确定性 ID `functional-test-agent.<KEY>`；
- `owner_type=tool`、`owner_id=functional-test-agent`；
- `group_key=runtime`；
- `sensitivity=normal`；
- `apply_mode=next_task`；
- 不修改现有 Release。

### 18.3 环境发布

- dev：新建并发布 Release，两个开关 true；
- prod：首次迁移后默认 false；完成真实模型、安全和浏览器验收再发布 true；
- 页面只能读取当前 `PLATFORM_RUNTIME_ENV`；
- API 每次写操作读取安全普通配置；
- Runner 每次执行读取完整配置快照。

### 18.4 Downgrade

- 删除这批定义前先删除引用它们的 `config_release_items`；
- 不删除工具、任务、审计、Secret 或 Review 文件；
- downgrade 后功能开关不可读取，页面按 false 回退旧流程；
- 支持 upgrade → downgrade → upgrade。

### 18.5 Nginx 与 Compose

无需改变运行拓扑。只验证：

- PUT/POST JSON 可通过子路径；
- `/review-ai/cancel` 映射 `task.cancel`；
- 6 MiB 足够容纳 5 MiB 正文和 JSON 开销；
- AI POST 快速返回 202，60 秒代理超时不影响后台执行；
- 停止 API 智能体不影响功能 Review；
- 功能镜像仍非 root、只读源码、独立任务卷。

---

## 19. 错误码与失败语义

### 19.1 新增错误码

```text
REVIEW_REVISION_CONFLICT
REVIEW_DRAFT_REQUIRED
REVIEW_WARNING_CONFIRMATION_REQUIRED
REVIEW_VALIDATION_FAILED
REVIEW_AI_ALREADY_RUNNING
REVIEW_AI_BASE_CHANGED
REVIEW_AI_SCOPE_REQUIRED
REVIEW_AI_RESPONSE_INVALID
STORAGE_WRITE_FAILED
QUEUE_FULL
```

复用：

```text
INVALID_TASK_STATE
TASK_QUEUE_FULL（仅保留给新建任务接口，兼容既有错误码）
FEATURE_DISABLED
LLM_AUTH_FAILED
LLM_RATE_LIMITED
LLM_TIMEOUT
WORKER_INTERRUPTED
ARTIFACT_EXPIRED
```

Review 正式继续和 AI 辅助入队按新 PRD 返回 `QUEUE_FULL`。`TaskManager.assert_capacity` 增加可选 `error_code` 参数：新建任务沿用 `TASK_QUEUE_FULL`，两个 Review 入队方法传入 `QUEUE_FULL`，避免破坏旧创建任务客户端。

### 19.2 主任务与 AI 子阶段错误

| 场景 | 主状态 | 错误位置 |
|---|---|---|
| 草稿校验失败 | waiting_review | HTTP 响应 validation |
| AI 失败 | waiting_review | `task.review_ai.error_*` |
| AI 取消 | waiting_review | `task.review_ai.status=cancelled` |
| 正式 Runner 失败 | failed | 主 `error_code/error_message` |
| 取消整个任务 | cancelled | 主终态 |

任务详情顶部主错误区只展示主终态错误；Review 区展示 AI 可恢复错误，避免把 AI 建议失败误解为整个任务失败。

---

## 20. 安全设计

### 20.1 输入边界

- 5 MiB、500,000 字符、5,000 条；
- 标准字段类型与长度；
- JSON 安全解析；
- NUL 和私有字段拒绝；
- instruction 2,000 字符；
- selected 100、context 500、suggestions 200；
- 不接受服务器路径、模型参数或 Prompt 参数。

### 20.2 Prompt 注入

- 系统规则与用户数据分区；
- 用户说明 JSON 编码；
- 需求事实标记只读；
- 输出只接受 add/replace 白名单；
- replace target 必须在选择集；
- 不运行模型输出代码；
- 不向任何测试目标发送请求；
- 不展示原始模型响应。

### 20.3 数据隔离

- 任务所有权；
- 所有文件位于任务目录；
- AI 上下文只读取当前任务；
- dev/prod 配置与 Secret 隔离；
- Client Token 不传 Runner；
- LLM Secret 不进文件、日志、响应或 Prompt。

### 20.4 XSS 与下载

- 表格和建议全部 `textContent`；
- 不使用 `innerHTML` 渲染用户数据；
- 下载由服务端固定枚举解析；
- Content-Type 为 JSON、`nosniff`；
- 文件名安全固定；
- CSP 如平台后续统一增加，应确保本页不依赖内联脚本。

### 20.5 拒绝服务与成本

- 队列上限共享；
- AI 600 秒超时；
- 请求幂等；
- 上下文与输出上限；
- 同一任务只允许一个 AI 子阶段；
- 轮询最短 5 秒，不在 hidden 页面高频轮询；
- 不提供逐 Token 流式接口。

---

## 21. 可观测性

### 21.1 任务元数据

公开：

- review revision、SHA 前缀、保存人/时间、有效性；
- AI 状态、操作、数量、模型、Prompt SHA、开始/完成时间；
- execution stage 和 queued_at。

内部：

- 完整 SHA；
- execution sequence；
- PID；
- 文件相对路径；
- idempotency key SHA。

### 21.2 日志

结构化前缀：

```text
[task=<id> execution=<kind> sequence=<n>]
```

记录阶段、数量、耗时和稳定错误码，不记录正文。

### 21.3 指标建议

不引入新监控系统；先通过审计/结构化日志统计：

- draft save success/conflict/failure；
- review resume success/queue_full；
- AI request/complete/fail/cancel；
- AI suggestions valid/rejected/applied（应用数可在后续草稿保存元数据记录）；
- AI 耗时与错误码；
- Review 从 waiting 到正式 resume 的时长。

---

## 22. 兼容性设计

### 22.1 旧任务

- 无 review_draft：从原始 artifact 初始化 revision 0；
- 旧 `review_draft` 使用 `version/relative_path` 结构：识别为旧确认上传，读取对应文件并转换为当前草稿视图；
- 无 execution.json：Runner 按原 request 推断；
- 无 queued_at：FIFO 回退 created_at；
- 不批量改写旧任务文件，按需惰性升级。

### 22.2 旧 multipart resume

至少保留一个发布周期。响应和状态保持 202/pending；内部改走新草稿和确认逻辑。

### 22.3 旧 CLI

不调用 Web Review 模块，不受 execution.json 影响。现有工具函数、Prompt 和输出路径保持。

### 22.4 API 智能体

TaskManager 是共享模块，因此新增逻辑必须以 execution kind/agent 行为通用兼容：

- API 新任务仍为 initial；
- API 不注册 Review API；
- API 非零退出和中断仍为 failed；
- `REVIEW_AI_*` 不进入 API 配置定义；
- API_EXECUTION_ENABLED 仍为 false、ALLOWED_TARGETS 仍为空。

---

## 23. 自动化测试设计

### 23.1 测试方法

所有缺陷修复和新状态转换先写失败测试，再实施最小代码。LLM 测试默认使用 Fake/Mock，不要求真实凭据，不为通过测试降低安全开关。

### 23.2 Review 领域单元测试

新增 `test_review_domain.py`：

- 列表和三种包装对象解析；
- 标准字段顺序和扩展字段往返；
- 首尾空白处理；
- 空、数量、字节、字符和字段长度；
- 类型、NUL、客户端私有字段；
- ID 重复和完全重复；
- 跨上下文同文本警告；
- ID 格式、短文本、风险变化警告；
- 删除/新增比例；
- O(n) diff 的 added/modified/deleted/unchanged；
- ID 修改视为删除+新增；
- canonical SHA 稳定。

### 23.3 草稿与版本测试

- 首次 revision 0 → 1；
- 相同 SHA 不增加 revision；
- 两线程 CAS 只有一个成功；
- 草稿可有业务错误；
- task 索引写失败后从信封恢复；
- 确认版本不可覆盖；
- 相同 SHA 复用版本；
- Idempotency-Key 同 key 同 body 幂等；
- 同 key 不同 body 冲突；
- 队列满保留确认版本且 waiting_review；
- containment 和符号链接攻击拒绝。

### 23.4 FIFO 与状态测试

扩展 `test_task_runtime.py`：

- 新任务按 queued_at；
- waiting_review resume 排到现有 pending 后；
- AI 入队排到队尾；
- AI 与正式 resume 并发只有一个成功；
- AI pending cancel 回 Review；
- AI running cancel 终止进程组并回 Review；
- AI 超时回 Review；
- AI 非零退出回 Review；
- 正式非零退出仍 failed；
- AI running 重启恢复回 Review；
- 正式 running 重启仍 failed；
- execution sequence 迟到结果被丢弃；
- AI 运行不清空 artifacts registry。

### 23.5 AI Adapter 测试

新增 `test_review_ai.py`：

- 三种 operation Prompt 输入；
- 实际模型名记录；
- supplement 只接受 add；
- rewrite 只接受选中 target；
- rewrite 不修改 ID、不降低风险；
- instruction 作为非需求事实区块；
- fenced JSON 和一次 repair；
- 非法 action/target/字段隔离；
- 超建议数整体拒绝；
- 建议稳定 ID；
- 500 条作用域限制；
- 120,000 字符限制；
- 不读取其他任务、Secret、日志和历史 output；
- 不执行脚本、不发真实测试目标 HTTP 请求；
- 建议文件不可变和 SHA 校验。

### 23.6 Web API 测试

扩展 `test_web_routes.py`：

- GET 原稿、草稿、旧任务、只读和过期；
- PUT 保存有效/无效草稿；
- revision 冲突 details 脱敏；
- import 不自动入队；
- JSON resume 与 multipart 兼容；
- 警告确认；
- review download 三种 kind；
- AI feature disabled；
- AI request 参数、作用域和幂等；
- AI suggestion GET；
- AI cancel 权限；
- 创建者、其他用户、管理员、只读矩阵；
- 缺 CSRF；
- XSS 文本响应仍为 JSON 文本；
- API 智能体相同路径 404。

### 23.7 平台测试

- 0010 空库 upgrade；
- 重复 upgrade；
- downgrade 到 0009；
- 重新 upgrade；
- 配置定义数量和默认值；
- dev/prod Release 隔离；
- `review-ai/cancel` 权限映射；
- Nginx 子路径和 6 MiB；
- Compose config；
- API 执行安全默认回归。

### 23.8 前端与 DOM 合同测试

不新增前端框架。通过 pytest HTML 合同测试和浏览器验收覆盖：

- Review 根节点和 data 属性；
- 无权限不渲染编辑操作；
- 在线开关关闭回退旧表单；
- 语义表格、aria-live、dialog 和可访问名称；
- 静态资源只在功能 Review 页面加载；
- 用户正文不通过 innerHTML；
- 保存/冲突/AI 状态按钮切换。

若开发时 Node 原生 `node --test` 可直接运行且无需新增依赖，可把纯 normalize/filter/reducer 函数抽成 ES module 做额外单测；这不是引入构建链的前提。

### 23.9 回归命令

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

## 24. 浏览器验收设计

### 24.1 视口

- 1280×800；
- 1440×900。

仅桌面浏览器，本期不验收移动端。

### 24.2 人工 Review 主流程

1. 进入 waiting_review；
2. 加载 53 条真实结构测试点；
3. 编辑标准字段；
4. 新增、复制、删除和撤销；
5. 筛选、折叠和分页；
6. 制造 ID/重复错误并跳转；
7. 保存草稿并刷新恢复；
8. 第二标签页制造 revision 冲突；
9. 下载本地未保存 JSON；
10. 重新加载并保存；
11. 接受警告；
12. 确认并进入 FIFO；
13. 下载最终 JSON/XLSX。

### 24.3 AI 主流程

1. 保存草稿；
2. 发起补全；
3. 验证排队/运行只读状态；
4. 验证取消 AI 后回 Review；
5. 重新发起并完成；
6. 查看模型/Prompt/依据；
7. 默认无建议被选；
8. 选择部分建议应用；
9. 保存新 revision；
10. 对旧建议验证基准过期；
11. 正式继续生成用例。

### 24.4 状态矩阵

- 加载、空、只读；
- 未保存、保存中、保存失败；
- 错误、警告；
- revision 冲突；
- 队列满；
- AI 关闭、排队、运行、ready、failed、cancelled、base changed；
- artifact expired；
- 401、403、404、503。

### 24.5 可访问性

- 全流程键盘操作；
- 焦点可见；
- 错误跳转；
- dialog Esc、焦点循环与恢复；
- 状态非纯颜色；
- 200 行表格键盘可用；
- reduced motion；
- 长文本展开。

### 24.6 性能数据

使用构造但不冒充生产的数据集验证 100、500、5,000 条：

- 100 条首屏 ≤2 秒；
- 500 条筛选反馈 ≤300ms；
- 5,000 条不一次渲染全部 DOM；
- 保存 5,000 条服务端校验 ≤2 秒（本地环境记录硬件条件）。

真实 LLM 凭据不可用时，AI 浏览器流程使用隔离 Fake Adapter；真实模型联调列为外部依赖，不降低 Schema、权限或开关。

---

## 25. 开发工作包与依赖

### 25.1 工作包总览

| 工作包 | 内容 | 依赖 | 完成证据 |
|---|---|---|---|
| D01 基线与黄金数据 | 冻结测试、历史 output 摘要、真实测试点样本 | 无 | 基线记录 |
| D02 领域模型与错误码 | Review 模型、规范化、校验、diff | D01 | 单元测试 |
| D03 草稿与版本存储 | 信封、CAS、恢复、确认版本、下载 | D02 | 存储测试 |
| D04 Review HTTP API | GET/PUT/import/download/JSON resume | D03 | 路由测试 |
| D05 FIFO 重入与执行信封 | queued_at、execution、sequence、兼容 | D03 | 运行时测试 |
| D06 AI Schema 与 Prompt | 请求/建议模型、Prompt、安全边界 | D02 | Mock LLM 测试 |
| D07 AI Adapter/Runner | 三种操作、建议文件、结果映射 | D05,D06 | 集成测试 |
| D08 AI 取消与恢复 | 可恢复失败、超时、取消、重启 | D07 | 进程测试 |
| D09 Review 页面骨架 | Jinja、加载、摘要、开关回退 | D04 | DOM/路由测试 |
| D10 表格编辑器 | 编辑、增删复制、筛选折叠、分页 | D09 | 浏览器流程 |
| D11 草稿/冲突/继续 UI | dirty、保存、冲突、导入、resume | D10 | 浏览器流程 |
| D12 AI 建议 UI | AI 操作、轮询、diff、选择应用 | D07,D10 | 浏览器流程 |
| D13 权限、安全与审计 | RBAC、CSRF、IDOR、XSS、审计 | D04,D07,D12 | 安全测试 |
| D14 平台配置迁移 | 0010、Release、权限映射回归 | D01 | 迁移测试 |
| D15 容器与网关检查 | 镜像、Nginx、Compose、故障隔离 | D07,D14 | config/health |
| D16 E2E 与发布文档 | 全回归、双视口、部署回滚 | 全部 | 验收报告 |

### 25.2 推荐执行顺序

```text
D01
 → D02
 → D03
 → D04 ───────────────→ D09 → D10 → D11
 → D05 → D06 → D07 → D08 ─────────→ D12
 → D13
 → D14
 → D15
 → D16
```

D06 可在 D03 后与 D04/D05 部分并行；同一工作区实施时必须避免多人同时修改 `web.py/task_manager.py`。

### 25.3 工作量估算

按一名熟悉现有项目的工程师估算：

| 阶段 | 人日 |
|---|---:|
| R01 数据、校验和存储 | 3～4 |
| R02 Review API 与兼容 resume | 2～3 |
| R03 在线表格编辑器 | 4～6 |
| R04 AI 辅助 Review | 6～10 |
| R05 队列、恢复、安全和平台配置 | 3～4 |
| R06 E2E、浏览器和发布 | 2～3 |
| 合计 | 20～30 |

这是工程量，不等于自然日；不包含外部模型服务故障等待。若需要压缩，应优先并行后端领域/AI Prompt 与前端表格，不应删除权限、恢复或浏览器验收。

---

## 26. 分阶段实施计划

### 阶段 R01：数据、校验和存储

目标：建立不依赖 Web/LLM 的可靠 Review 内核。

步骤：

1. 写失败测试覆盖完整 PRD 校验；
2. 实现 Review 模型、规范化、SHA 和 O(n) diff；
3. 实现草稿信封与 CAS；
4. 实现不可变确认版本；
5. 实现旧任务/旧 review_draft 读取兼容；
6. 验证写入失败和恢复。

退出条件：D01～D03 测试通过。

### 阶段 R02：Review API

目标：在无前端依赖下完成所有人工 Review 协议。

步骤：

1. GET Review；
2. PUT 草稿；
3. import；
4. download；
5. JSON resume；
6. multipart 兼容重构；
7. 权限/CSRF/所有权/过期测试。

退出条件：D04 通过，curl/Flask client 可完成原稿→草稿→确认→pending。

### 阶段 R03：在线编辑器

目标：普通用户不接触 JSON 完成人工 Review。

步骤：

1. 页面壳和 feature flag；
2. 表格加载与语义结构；
3. 增删复制；
4. 筛选、折叠、分页；
5. 即时校验和错误跳转；
6. dirty/保存/冲突；
7. 导入下载与 resume；
8. 键盘和 reduced motion。

退出条件：D09～D11 浏览器主流程通过。

### 阶段 R04：AI 辅助 Review

目标：交付三种只建议、不自动应用的 AI 操作。

步骤：

1. AI 请求/建议 Schema；
2. 独立 Prompt；
3. execution kind 和 Runner 分派；
4. AI Adapter；
5. request/suggestion 不可变文件；
6. AI API；
7. 建议面板与差异应用；
8. Mock LLM 全边界。

退出条件：D06、D07、D12 通过。

### 阶段 R05：队列、恢复、安全和配置

目标：关闭状态竞争与发布风险。

步骤：

1. queued_at FIFO；
2. execution sequence 迟到保护；
3. AI cancel/timeout/recovery；
4. 审计和脱敏；
5. 0010 migration；
6. dev Release；
7. Nginx/Compose/容器检查；
8. API 智能体隔离回归。

退出条件：D05、D08、D13～D15 通过。

### 阶段 R06：E2E 与发布

目标：形成可交付版本。

步骤：

1. 全量自动化；
2. 双视口浏览器；
3. 100/500/5,000 数据；
4. Fake 与真实模型分层联调；
5. 故障隔离；
6. README/部署/回滚；
7. diff 与历史 output 校验。

退出条件：D16 验收报告完成，无未说明的阻塞缺陷。

---

## 27. 部署设计

### 27.1 dev 部署顺序

1. 记录两个项目 Git 状态和历史 output 摘要；
2. 运行现有全部回归；
3. 在隔离数据库验证 0010 upgrade/downgrade/upgrade；
4. 本地 dev 数据库 upgrade；
5. 发布功能工具 dev 配置，开启 ONLINE_REVIEW 和 REVIEW_AI；
6. 明确检查 prod 激活配置未变化；
7. 构建功能智能体镜像；
8. 只替换 functional-test-agent；
9. 验证 health/readiness；
10. 验证原 JSON Review 回退路径；
11. 完成在线人工 Review；
12. 使用 Fake/真实模型完成 AI Review；
13. 验证停止功能服务不影响 API 智能体，反之亦然；
14. 全量回归。

### 27.2 prod 发布前门槛

- dev 运行至少一个完整人工 Review 和一个 AI Review；
- revision 冲突、队列满、AI 超时和取消已验证；
- 真实模型建议通过 Schema；
- 模型和 Prompt 版本页面可见；
- Secret/路径扫描无泄露；
- prod Release 中两个开关仍 false；
- 获得上线确认后才创建 prod 开启 Release。

### 27.3 健康检查

`/health` 不调用 LLM、不读任务正文。`/readiness` 只返回：

- 存储可写；
- 配置可用；
- LLM Secret 是否配置；
- Release 和环境；
- 在线 Review/AI 开关状态（布尔值）。

---

## 28. 回滚设计

### 28.1 功能开关回滚

1. 先关闭 `REVIEW_AI_ENABLED`，保留人工在线编辑；
2. 如在线编辑也异常，关闭 `ONLINE_REVIEW_ENABLED`；
3. 页面回退旧 JSON 下载/上传；
4. 不删除草稿、建议或确认文件。

### 28.2 服务回滚

- 停止并恢复上一版功能镜像；
- 不删除任务卷；
- 旧服务忽略新增字段和文件；
- 已确认 Review JSON 可继续通过旧 multipart 路径使用；
- API 智能体和其他平台工具不回滚。

### 28.3 数据库回滚

- 通常保留 0010 配置定义；
- 确需 downgrade 时先关闭开关并确认无 Release 引用；
- downgrade 只删新增定义及其 release item；
- 不删工具、Secret、审计或任务文件。

### 28.4 运行中 AI 回滚

- 先取消/等待当前 review_ai；
- 若直接停止服务，启动恢复会把 running AI 返回 waiting_review；
- 正式 running 任务仍按既有中断失败语义；
- 回滚报告列出受影响 task ID，不输出正文。

---

## 29. 风险与缓解

| 风险 | 设计缓解 |
|---|---|
| 两文件无法原子提交 | 自描述草稿信封为事实来源，task 索引可修复 |
| 任务锁死锁 | 固定 Condition→TaskStore 锁序，封装入队方法 |
| resume 插队 | queued_at 重排 |
| AI 与正式继续竞争 | 锁内状态转换 + execution sequence |
| AI 失败误终结任务 | execution kind 分支，回 waiting_review |
| AI 清空 artifact registry | review_ai 跳过 result collector/save_registry |
| 建议覆盖新草稿 | base revision/SHA + 冲突策略 |
| 扩展字段丢失 | extra allow + 完整往返测试 |
| 浏览器大表格卡顿 | 分页，DOM 最多 200 行，O(n) 选择器 |
| Prompt 注入 | 数据分区、动作白名单、输出 Schema、无代码执行 |
| 模型成本失控 | 队列、幂等、超时、上下文/输出上限 |
| 多 worker 数据竞争 | 保持 Gunicorn 单 worker；未来扩展另立设计 |
| 平台迁移影响 prod | 目录默认 false，环境 Release 显式开启 |
| 回滚后新文件不识别 | 旧服务忽略额外文件，旧 multipart 保留 |

---

## 30. 最终完成检查单

### 30.1 代码与数据

- [ ] 原稿、草稿、建议、确认版本隔离；
- [ ] 扩展字段往返；
- [ ] revision CAS；
- [ ] 确认版本不可变；
- [ ] queued_at FIFO；
- [ ] execution sequence；
- [ ] AI 三操作；
- [ ] AI 不自动应用；
- [ ] AI 失败回 Review；
- [ ] 历史 output 未变化。

### 30.2 安全

- [ ] 所有权与管理员矩阵；
- [ ] CSRF；
- [ ] task.cancel；
- [ ] IDOR 404；
- [ ] XSS 文本；
- [ ] 路径 containment；
- [ ] Prompt 注入边界；
- [ ] Secret/路径/Prompt 全文不回显；
- [ ] API 真实执行仍关闭。

### 30.3 质量

- [ ] Review 单元测试；
- [ ] API 集成测试；
- [ ] FIFO/取消/超时/恢复；
- [ ] AI Mock 测试；
- [ ] 两项目完整回归；
- [ ] migration 往返；
- [ ] Nginx/Compose；
- [ ] 1280×800；
- [ ] 1440×900；
- [ ] 键盘/reduced-motion；
- [ ] 100/500/5,000 条性能。

### 30.4 发布

- [ ] dev 两开关开启；
- [ ] prod 初始关闭；
- [ ] 功能镜像健康；
- [ ] API 智能体不受影响；
- [ ] README 与运维说明；
- [ ] 回滚演练；
- [ ] 最终文件清单与设计差异报告。

---

## 31. 设计结论

本方案在现有功能智能体文件任务架构上增加一个独立 Review 领域层，通过草稿信封、revision CAS、不可变确认版本和 execution sequence 解决在线编辑的数据一致性问题；通过明确的 `review_ai` 执行类型，把 LLM 建议安全地纳入同一个持久化 FIFO，同时保留 AI 失败后返回人工 Review 的恢复能力。

前端继续采用 Flask + Jinja + 原生 JavaScript/CSS，以结构化表格和差异面板承载高密度工程任务，不引入聊天式交互或第二套设计系统。平台数据库只新增配置定义，不保存测试点正文；正式测试用例 Runner 继续读取确认 JSON，旧 multipart 和 CLI 均保留兼容。

按 D01～D16 与 R01～R06 推进并通过全部质量门槛后，该功能可在 dev 开启并逐步发布到 prod；任一阶段出现问题时，可通过独立开关回退到原 JSON Review 流程，不删除用户草稿和历史任务数据。
