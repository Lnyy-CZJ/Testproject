# API 测试智能体稳定性与可解释性优化 V2.3 开发设计与计划

> 文档版本：V2.3
> 日期：2026-08-20
> 依据：`PRD-API测试智能体稳定性与可解释性优化-V2.3.md`
> 实施范围：P0～P2 文件化统计方案

## 1. 设计目标与边界

本期解决任务创建至基础用例 Review 之间的稳定性和可解释性问题：契约尚未生成时的读取竞态、模型枚举不兼容、单条模型候选拖垮整个阶段、文档依据难理解、Token 与阶段记录不可用，以及缺少调用质量汇总。

保持 Flask、Jinja、原生 JavaScript、Pydantic V2、文件化 `TaskStore` 和单槽 FIFO 调度。P2 直接聚合 Attempt 下的不可变文件，不新增数据库、对象存储、模型单价或成本权限。

本期不修改真实执行开关、Controller、Executor、Egress、目标凭证、外部 Bug 提交和稳定资产发布，也不发送真实目标 API 请求。

## 2. 现有调用链与问题定位

### 2.1 契约读取

```text
任务详情页 loadContracts()
  → GET /api-test-agent/api/v1/tasks/{task_id}/contracts
  → ApiV2Store.load_version(task_id, "contracts")
  → versions/contracts/v{current_version}.json
```

新任务的 `current_versions.contracts` 尚不存在时，现有实现仍按版本 0 读取 `v0.json`，把正常生成中状态误报为系统错误。修复点放在 Blueprint 的契约读取响应构造层，不改变 `ApiV2Store` 对真实版本文件的严格校验。

### 2.2 基础用例生成

```text
POST /cases/generate
  → ApiTaskManager.enqueue_stage(base_case_generation)
  → services.api_agent.runner._base_case_stage
  → generate_fused_cases
  → base_case_generator.v2_prompt
  → BaseTestCase
  → Grounding / Coverage / 版本保存
```

当前融合内核把模型字典直接交给 `BaseTestCase`。模型输出 `positive` 时违反 `normal/negative/exploratory` 枚举，且异常位于数组循环内但没有单条隔离，最终映射为 `LLM_RESPONSE_INVALID` 并令整个阶段失败。

### 2.3 阶段记录与用量

每个 Attempt 已保存：

```text
attempts/{attempt_id}/events.jsonl
attempts/{attempt_id}/model-usage.json
attempts/{attempt_id}/generation-provenance.json
```

后端已经分别记录输入、输出和总 Token，但页面把输出与总量合并；阶段事件接口已有 cursor，却只在页面加载和手工点击时调用。V2.3 复用这些文件和接口，不建立第二套日志平台。

## 3. Schema 与状态设计

### 3.1 契约读取状态

`GET /contracts` 固定返回 `stage_state`：

- `not_generated`：尚未开始生成；
- `generating`：当前 Attempt 为 pending/running；
- `ready`：当前版本可读取；
- `failed`：当前 Attempt 失败；
- `stale`：契约来源版本不再是当前文档或范围。

未生成时返回版本 0、空 SHA 和空数组。显式请求不存在版本与当前版本损坏继续分别使用 404 和 500，不能退化为空数据。

### 3.2 模型候选归一化

在 Pydantic 前执行纯函数归一化：

- `positive/success/valid/happy_path` → `normal`；
- `abnormal/invalid/error/failure` → `negative`；
- `exploration/observe/unknown_expectation` → `exploratory`；
- 未知值 → `exploratory` 并添加 `CASE_ENUM_NORMALIZED` 警告。

未知值且没有观察目标时，该候选以 `CASE_PROMPT_ITEM_INVALID` 拒绝，不进入基础用例版本。

### 3.3 生成来源与拒绝摘要

扩展 `GenerationProvenance`：

- `deterministic_case_count`；
- `llm_case_count`；
- `rejected_case_count`；
- `ai_supplement_status`；
- `rejections`。

单条拒绝只保存 Attempt、Contract、模型调用、条目序号、Prompt、错误码、字段路径、拒绝阶段和建议，不保存模型原始输出。合法用例存在时阶段仍进入 `waiting_case_review`，拒绝信息作为生成警告展示。

### 3.4 阶段事件

在保持历史事件可读的前提下，为 `StageEvent` 增加默认兼容字段 `level` 和 `request_id`。空的关联 ID 使用 `null`，不伪造空字符串。应用日志采用 Python 标准库 JSON Formatter，字段与阶段事件一致；日志内容先经过现有脱敏器。

## 4. 服务端设计

### 4.1 契约接口

`GET /tasks/{task_id}/contracts` 在未生成时返回 200；真实损坏映射 `CONTRACT_VERSION_CORRUPTED`。响应始终包含 `stage_state/version/sha256/items/task_status`。

### 4.2 单条输出隔离

`generate_fused_cases` 先保留确定性用例，再逐条处理模型数组。每条候选依次经过对象、枚举、Schema、Grounding、完整性和去重检查。任何异常转换为拒绝摘要并继续下一条。

模型整体不可解析时记录 AI 补充失败；若确定性用例存在，仍保存覆盖矩阵和基础用例。只有确定性阶段也没有合法用例时才令阶段失败。

### 4.3 仅重试 AI 补充

新增：

```http
POST /api-test-agent/api/v1/tasks/{task_id}/cases/supplement/retry
```

接口要求用例 Review 权限和 CSRF，任务必须已有当前契约、基础用例和覆盖版本。它创建新的 `base_case_generation` Attempt，并在请求中携带 `supplement_only=true` 与上游版本。Runner 复用已保存确定性/合法用例，仅重新调用业务补充模型、重新 Grounding 和去重，然后生成新版本，不覆盖旧 Attempt。

### 4.4 阶段事件与结构化日志

`GET /stage-events` 增加 `level` 筛选。必须记录 Runner 阶段开始、完成、失败，模型调用，契约/用例数量，质量门禁，Review，版本保存和拒绝摘要。Web 请求错误通过现有 request ID 写结构化日志；事件或日志写入失败不得影响主产物。

### 4.5 文件化用量统计

新增：

```http
GET /api-test-agent/api/v1/tasks/{task_id}/usage/summary
GET /api-test-agent/api/v1/usage/summary
```

允许按 Attempt、阶段、节点、模型、Prompt、内核、项目和模块分组。任务级接口沿用任务所有权；全局接口要求 `task.view.all`，默认最近30天且最长90天。

聚合指标包括调用、已报告/未报告、输入/输出/总 Token、平均/最大耗时、重试、Schema 失败、Grounding 拒绝、部分成功以及每个有效契约/用例 Token。成本字段固定返回 `estimated_cost=null`、`cost_status=not_configured`。

## 5. 页面设计

### 5.1 生成中状态

契约未就绪时显示当前节点、已耗时和“无需重复创建任务”，隐藏编辑和确认区。每2～3秒读取稳定状态，ready 后加载工作区；页面隐藏时降频。

### 5.2 文档依据

默认使用测试人员术语，将问题拆成“字段冲突、文档待确认、AI 建议”。字段卡片展示业务名、接口、当前值、来源、原文、推断理由、影响和推荐动作；字段路径、Issue ID、置信度和版本放在折叠技术详情。

### 5.3 阶段记录与 Token

输入、输出和总 Token 使用独立卡片，增加未报告数量。阶段事件使用 cursor 增量追加；进入 Review 或终态最后刷新一次后停止。增加 Attempt 选择、级别筛选、调用明细和文件化统计分组，不显示虚假百分比或金额成本。

## 6. 错误码与兼容

- `CONTRACT_VERSION_NOT_FOUND`：指定契约版本不存在；
- `CONTRACT_VERSION_CORRUPTED`：当前版本 JSON、SHA 或信封损坏；
- `CASE_ENUM_NORMALIZED`：非阻断枚举归一化警告；
- `CASE_PROMPT_ITEM_INVALID`：单条候选被拒绝；
- `CASE_GENERATION_PARTIAL`：存在合法用例和拒绝候选；
- `LLM_RESPONSE_INVALID`：整体输出不可解析且无可保留结果；
- `MODEL_USAGE_UNAVAILABLE`：供应商未报告 Token；
- `STAGE_EVENT_QUERY_INVALID`：阶段记录筛选不合法。

历史任务缺少新增字段时按默认值读取，不回写历史文件。历史 Run、报告和 Bug 草稿不受影响。

## 7. 测试、发布与回滚

开发采用失败测试先行，覆盖契约竞态、枚举映射、9+1 单条隔离、整体模型失败保留确定性用例、AI-only 重试、文档依据分类、Token 拆分、cursor/level、脱敏、RBAC 和文件统计一致性。

发布顺序为服务端兼容响应、P0 生成修复、P1 页面与日志、P2 统计。回滚只停止创建 V2.3 Attempt 并回退页面入口，不删除或改写历史文件。

验收期间保持 `API_EXECUTION_ENABLED` 现状，不创建真实执行容器，不配置真实 Egress 或目标凭证。
