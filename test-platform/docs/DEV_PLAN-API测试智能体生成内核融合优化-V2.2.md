# API 测试智能体生成内核融合优化开发设计与计划

> 文档版本：V2.2
> 文档状态：待实施
> 依据文档：`PRD-API测试智能体生成内核融合优化-V2.2.md`
> 适用仓库：`/Users/admin/Testproject/api-test-agent`
> 计划范围：P0、P1；P2 不进入本次实施
> 已确认决策：PRD 第 19 章全部建议决策已接受

## 1. 开发目标

本次开发把旧版 API 测试智能体的测试设计和执行定义生成能力重新接入当前 V2 平台流程，同时保留 V2 的契约可信、人工 Review、版本追溯、安全校验和受控执行能力。

最终调用链必须满足：

```text
V2 文档预检/契约解析
→ 契约 Evidence 与人工确认
→ 融合生成上下文
→ 旧测试设计规则和 Prompt 生成基础用例候选
→ V2 Grounding、完整性、覆盖矩阵和最多 3 轮补齐
→ 基础用例 Review
→ 旧可执行用例生成规则和 Prompt 生成执行候选
→ V2 Schema、请求完整性、变量、依赖、断言、AST 和风险校验
→ 执行预览与最终确认
→ Controller/受限容器执行
```

任务完成后，旧 prompts 和生成逻辑继续是 API 测试智能体的生成核心，但以下旧副作用不得进入平台调用链：

- MySQL 用例直写；
- 模型文本“100%”覆盖判断；
- 旧 CLI `execute_test_cases()`；
- Web/生成 Runner 直接请求目标 API；
- 未经过 V2 静态安全校验的脚本执行。

## 2. 已确认架构决策

| 决策项 | 最终决策 | 开发约束 |
| --- | --- | --- |
| 旧 LangGraph 整图 | 不直接恢复 | 复用 Prompt、测试设计规则和生成节点，使用无副作用适配层接入 V2 Runner |
| 旧 MySQL 持久化 | 不恢复 | 所有新产物继续进入 TaskStore 不可变版本和 Attempt 目录 |
| 旧 CLI 真实执行 | 不恢复 | 平台只允许 Controller/Executor 执行 |
| L1-L5、T1-T4 | 保留 | 作为用例分类和测试设计规则，不作为覆盖率自报依据 |
| 无文档依据探索用例 | 允许 | 必须标记 `exploratory`、人工确认，不自动生成产品 Bug |
| LLM 业务用例确认 | 不自动确认 | Schema、Grounding、完整性通过后进入候选，再由人工确认 |
| 历史 `v2_minimal` | 重新校验 | 不合格执行定义禁止创建新 Run，历史报告保持不变 |
| 阶段日志 | 单一跨阶段面板 | 不实现四套重复日志窗口 |

以上决策按本次评审结论固化：不恢复完整 LangGraph 执行图、不恢复旧 MySQL 持久化、不恢复旧 CLI 直接执行；保留旧测试设计标签与规则；允许受控的探索性用例，但必须人工确认且不得自动形成产品 Bug；LLM 生成用例不得自动确认；历史 `v2_minimal` 用例必须重新校验；日志采用一个跨阶段窗口。

### 2.1 PRD 需求追踪矩阵

| PRD 编号 | 设计落点 | 主要交付物 | 验证重点 |
| --- | --- | --- | --- |
| `KERNEL-01` | 6.1 生成上下文 | `GenerationContext`、契约/文档/范围/历史上下文装配 | 输入版本和 SHA 可追溯，禁止无关领域上下文 |
| `KERNEL-02` | 6.2～6.3 候选生成 | 确定性用例、LLM 业务候选、旧 Prompt 适配 | 登录接口不生成商品、订单、支付等无依据场景 |
| `KERNEL-03` | 6.2、6.5 规则融合 | L1～L5、T1～T4 标签与覆盖规则映射 | 旧测试设计能力被复用且不恢复旧副作用 |
| `KERNEL-04` | 6.4 Grounding | 字段级 Evidence、质量报告、阻断原因 | 无依据的关键步骤、数据和预期不得进入确认候选 |
| `KERNEL-05` | 6.5 覆盖矩阵 | 结构化矩阵、补齐轮次、缺口与来源 | 最多补齐 3 轮，不能以模型文本宣称覆盖完成 |
| `KERNEL-06` | 7.1 用例详情 | 步骤、依赖、数据、预期、Evidence 工作区 | 测试人员能够查看完整基础用例，而非只看标题 |
| `KERNEL-07` | 7.2 Review | 编辑、确认、禁用、高风险审计、版本冲突 | 授权角色可复核，高风险不能批量静默放行 |
| `KERNEL-08` | 8.1 生成输入 | 仅使用已确认基础用例和绑定契约版本 | 未确认、过期、禁用用例不得进入执行定义生成 |
| `KERNEL-09` | 8.2～8.4 执行候选 | 完整请求、断言、提取、依赖、探索观察定义 | 禁止 `body=null`、默认 200 等伪完整用例进入预览 |
| `KERNEL-10` | 8.3 静态校验 | Schema、变量、依赖、断言、AST 和风险门禁 | 所有阻断均有稳定错误码和修复建议 |
| `OBS-01` | 9.1～9.2 阶段记录 | `StageEvent`、单一跨阶段日志面板 | 阶段 1～4 均可按 Attempt、接口和级别过滤 |
| `OBS-02` | 9.3 日志安全 | 结构化脱敏、正文摘要、下载前复检 | 日志和异常不泄露 Token、Cookie、请求/响应 Secret |
| `OBS-03` | 9.4 Prompt 来源 | 模块、模板版本、Prompt SHA、模型、Attempt 绑定 | 页面可证明实际使用了哪个文件和提示词 |
| `OBS-04` | 9.5 Token 用量 | `ModelUsageRecord`、阶段/版本汇总 | 展示输入、输出、总 Token、调用次数和缺失原因 |
| `COMPAT-01` | 10.1 内核标识 | `API_GENERATION_KERNEL`、`generation_kernel` 来源信息 | `v2_minimal` 与 `v2_fused` 可识别、可灰度 |
| `COMPAT-02` | 10.2 历史兼容 | 旧任务只读、重新校验、旧执行确认失效 | 历史数据不迁移、不覆盖，不合格用例不可执行 |

## 3. 当前代码基线与差异

### 3.1 当前 V2 入口

平台通过 `services/api_agent/app.py` 配置 `runner_module="services.api_agent.runner"`。当前 `runner.py` 直接调用：

- `contracts/openapi_parser.py`；
- `contracts/unstructured_parser.py`；
- `cases/coverage.py`；
- `cases/business_supplement.py`；
- `cases/executable.py`。

旧 `ApiCaseGeneratoMainWorkFlow` 没有进入平台任务调用链。

### 3.2 当前基础用例生成差异

`business_supplement.py` 当前只向模型发送缺口的 Contract ID、dimension 和 rule，只接受 `name/objective`，导致：

- 模型看不到 method/path/summary/参数/响应/Evidence；
- LLM 用例的 steps、expected_results、preconditions 为空；
- 错误业务场景仍能按 `contract_id + dimension` 填平覆盖缺口。

### 3.3 当前执行定义差异

`cases/executable.py` 当前主要把已确认基础用例映射成：

- Contract method/path；
- 空 Header、Query、Body；
- 默认状态码 200 断言。

它没有使用旧 `api_case_generator.py` 中的目标接口、依赖接口、测试数据、变量和脚本生成能力。

### 3.4 当前可观察性差异

- Runner 成功路径基本不输出日志；
- `console.log` 只接收 stdout/stderr；
- 日志区域只位于页面第 4 阶段；
- Prompt Bundle SHA 是整个 prompts 目录的哈希，不表示本阶段实际调用文件；
- API V2 没有 Token 采集和 Attempt 级模型用量。

## 4. 总体技术设计

### 4.1 分层职责

```text
services/api_agent/runner.py
  负责阶段编排、版本读取/保存、Attempt 状态和错误映射

agents/api_test/cases/fused_kernel.py
  负责构造生成上下文、调用旧 Prompt 的 V2 变体、规范化候选

agents/api_test/cases/grounding.py
  负责用例 Evidence、业务实体、参数、依赖、预期结果和完整性校验

agents/api_test/cases/coverage.py
  负责确定性覆盖骨架、有效用例关联、最多 3 轮补齐

agents/api_test/cases/executable.py
  负责执行候选规范化和 V2 静态安全校验

services/api_agent/stage_events.py
  负责 Attempt/Run 结构化阶段事件、Prompt 来源和模型用量读写

services/api_agent/v2_store.py
  负责不可变版本、Attempt 文档和 Run 文档
```

新增文件的理由：

- `fused_kernel.py` 隔离旧生成能力与旧数据库/执行副作用，避免在 `runner.py` 内堆积 Prompt 和模型解析；
- `grounding.py` 同时被基础用例确认、覆盖关联和执行定义生成复用，不能只放在页面或单一路由；
- `stage_events.py` 是任务级可观察性边界，需要被 Runner、Review 和执行流程共同调用。

除上述三个必要文件外，不新增生成框架、前端框架或第三方依赖。

### 4.2 旧生成核心的复用方式

不直接调用旧 `create_workflow()`，而是抽取并复用以下能力：

1. `base_case_generator.py` 中的测试设计体系、参数角色规则、依赖规则和基础用例 Prompt；
2. `base_case_check_coverage.py` 中的文档对照思路，但输出改为结构化缺口；
3. `supplement_case.py` 中的差异化补齐规则，但由 V2 控制轮次和有效性；
4. `api_case_generator.py` 中的请求、变量、测试数据、依赖、setup/teardown 和执行定义规则；
5. 旧 workflows 的节点事件名称，用于阶段记录，不恢复其数据库和执行节点。

旧工作流继续兼容 CLI；平台融合路径调用纯函数，不导入 `APITestCaseExecutor.execute_test_cases()`。

### 4.3 Prompt 兼容设计

现有 Prompt 模块保留旧 `prompt` 导出，避免破坏 CLI。每个相关模块增加 `v2_prompt` 导出：

- `base_case_generator.v2_prompt`；
- `base_case_check_coverage.v2_prompt`；
- `supplement_case.v2_prompt`；
- `api_case_generator.v2_prompt`。

实现要求：

- 旧版和 V2 变体共用同一组测试设计规则常量；
- 旧 `prompt` 的 input variables 和输出结构保持兼容；
- `v2_prompt` 接受规范化 JSON 上下文；
- `v2_prompt` 只返回严格 JSON，不返回 Markdown 说明；
- 每个 `v2_prompt` 有稳定 `prompt_id` 和内容 SHA；
- 不通过复制整份大 Prompt 形成两套长期漂移文本。

### 4.4 依赖注入和测试

融合内核的模型调用通过 `ModelInvoker` 协议或等价可调用对象注入：

```python
Callable[[PromptTemplate, dict[str, Any], ModelCallContext], Any]
```

生产实现调用当前 LangChain `llm`；测试使用 Fake Model，不访问真实模型和网络。

## 5. Schema 设计

所有新增 Pydantic 模型继续使用 `extra="forbid"`，旧版本缺失字段时由读取兼容层补默认值，不回写历史文件。

### 5.1 基础用例扩展

在 `BaseTestCase` 增加：

```python
test_level: Literal["L1", "L2", "L3", "L4", "L5"] | None
test_type: Literal["T1", "T2", "T3", "T4"] | None
execution_mode: Literal["assertion", "exploratory"] = "assertion"
data_ref: str = ""
parameter_mutations: list[CaseParameterMutation]
dependency_contract_ids: list[str]
evidence_refs: list[CaseEvidenceRef]
quality_report: CaseQualityReport
generation_kernel: Literal["legacy", "v2_minimal", "v2_fused", "human"]
source_versions: dict[str, int]
```

`CaseParameterMutation`：

```python
location: Literal["header", "cookie", "query", "path", "body"]
name: str
operation: Literal["set", "omit", "invalid_type", "boundary", "inject", "reuse"]
value_source: Literal["constant", "test_data", "environment", "dependency", "generated"]
value: Any | None
source_path: str
```

`CaseEvidenceRef`：

```python
field_path: str
source_pointer: str
evidence_type: Literal["contract", "document", "human_override"]
quote: str = ""
```

`CaseQualityReport`：

```python
schema_valid: bool
grounding_passed: bool
completeness_passed: bool
dependency_passed: bool
blockers: list[ReviewIssue]
warnings: list[ReviewIssue]
checked_at: str
```

兼容规则：

- 历史用例默认 `generation_kernel="v2_minimal"`；
- 历史空 `steps` 或 `expected_results` 不自动补造，只在重新校验时产生 blocker；
- 完全人工新增用例使用 `generation_kernel="human"`；
- `human_override` Evidence 必须记录操作者和原因到审计，不把人员信息塞入 Evidence quote。

### 5.2 覆盖矩阵扩展

`CoverageMatrixItem` 增加：

```python
accepted_case_ids: list[str]
rejected_case_ids: list[str]
rejection_reasons: list[str]
last_evaluated_round: int
```

`CoverageMatrix` 增加：

```python
round_summaries: list[CoverageRoundSummary]
generation_kernel: str
```

`CoverageRoundSummary` 保存 round、before_gap_count、candidate_count、accepted_count、rejected_count、after_gap_count 和 stop_reason。

只有 `quality_report.grounding_passed=true` 且 `completeness_passed=true` 的用例可以进入 `accepted_case_ids` 和 `case_ids`。

### 5.3 可执行用例扩展

`ExecutableCase` 增加：

```python
generation_kernel: Literal["legacy", "v2_minimal", "v2_fused", "human"]
source_versions: dict[str, int]
generation_provenance_id: str
data_lineage: dict[str, Any]
```

保持真实 Host 不进入版本文件；仍只保存 `target_id` 占位和相对 path。

### 5.4 生成来源

`GenerationProvenance`：

```python
provenance_id: str
task_id: str
attempt_id: str
stage: str
node: str
kernel: str
prompt_id: str | None
prompt_sha256: str | None
model_name: str | None
input_versions: dict[str, int]
input_sha256: str
output_kind: str
output_version: int | None
output_sha256: str | None
started_at: str
finished_at: str | None
duration_ms: int | None
status: Literal["started", "succeeded", "failed", "rejected"]
error_code: str | None
```

### 5.5 阶段事件与模型用量

`StageEvent`：

```python
event_id: str
task_id: str
attempt_id: str | None
run_id: str | None
stage: str
node: str
event_type: Literal["started", "progress", "artifact", "review", "completed", "failed"]
status: str
message: str
input_versions: dict[str, int]
output_versions: dict[str, int]
duration_ms: int | None
model_call_id: str | None
error_code: str | None
created_at: str
```

`ModelUsageRecord`：

```python
call_id: str
attempt_id: str
stage: str
node: str
prompt_id: str
prompt_sha256: str
model_name: str
input_tokens: int
output_tokens: int
total_tokens: int
reported: bool
retry_number: int
started_at: str
finished_at: str
duration_ms: int
status: Literal["succeeded", "failed", "rejected"]
```

供应商未报告 usage 时 Token 均保存 0，但 `reported=false`；页面必须显示“未报告”，不能把 0 当成真实消耗。

## 6. 融合基础用例生成设计

### 6.1 GenerationContext

`fused_kernel.py` 从已确认契约构造每接口独立上下文：

```json
{
  "contract": {},
  "source_sections": [],
  "field_evidence": [],
  "human_overrides": [],
  "dependencies": [],
  "test_data_catalog": [],
  "deterministic_cases": [],
  "coverage_gaps": [],
  "source_versions": {},
  "security_policy": {}
}
```

安全要求：

- 只传当前接口和已确认依赖接口；
- Secret 值替换为变量名称和来源类型；
- 文档原文只传关联 Section，不把全项目文档无差别发送给模型；
- 生成上下文计算 canonical SHA，并写入 provenance；
- 远程 `$ref`、真实 Host 和执行凭证不进入模型输入。

### 6.2 确定性用例先行

沿用 `coverage.py` 的正常、必填、类型、枚举、边界、鉴权、错误响应和幂等规则，但补齐：

- 参数 mutation；
- 关联 FieldEvidence；
- 文档声明的预期状态码或错误码；
- 缺少文档预期时改成探索式观察目标，不默认断言 200；
- L1-L5/T1-T4 分类。

确定性用例也必须通过完整性门禁，但不产生模型 Token。

### 6.3 LLM 基础用例候选

每个已确认 Contract 单独调用 `base_case_generator.v2_prompt`，避免多个接口 Contract ID 串位。模型输出先经 Pydantic Schema，再映射为 `BaseTestCase`。

默认状态：

- Schema 或 Grounding 失败：`draft`，不关联覆盖；
- 门禁通过：`confirmed_candidate`；
- 高风险：`draft`，等待逐条确认；
- 探索式：`draft`，等待人工确认其观察目标。

### 6.4 Grounding 算法

`grounding.py` 执行以下确定性检查：

1. Contract ID 必须属于当前契约版本；
2. 用例步骤涉及的 method/path 必须与目标或已确认依赖一致；
3. mutation 参数必须存在于契约或人工补充字段；
4. 状态码、错误码、响应字段必须能绑定契约 Evidence；
5. Evidence pointer 必须存在于当前文档/契约版本；
6. 非通用业务实体必须出现在关联 Section、契约 summary/tags、人工补充说明或已确认依赖中；
7. 依赖接口必须已确认且不存在自依赖；
8. assertion 模式必须有预期结果；exploratory 模式必须有观察目标。

业务实体检查不使用简单全局敏感词黑名单。实现为：

- 模型必须为业务结论返回 Evidence pointer；
- pointer 对应文本中必须包含支撑该结论的关键短语或字段；
- 无法验证时产生 `CASE_BUSINESS_ENTITY_UNSUPPORTED`；
- 人工可以通过 `human_override` 补充依据，但必须有理由。

### 6.5 覆盖合并和补齐

流程：

1. 构造确定性 CoverageMatrix；
2. 关联通过门禁的确定性和首轮 LLM 用例；
3. 计算结构化缺口；
4. 仅对缺口调用 `supplement_case.v2_prompt`；
5. 对候选执行 Schema、去重、Grounding 和完整性门禁；
6. 记录接受/拒绝；
7. 重新计算矩阵；
8. 最多 3 轮，满足停止条件立即结束。

停止原因使用稳定枚举：

- `all_required_covered`；
- `max_rounds_reached`；
- `no_valid_candidate`；
- `unchanged_for_two_rounds`；
- `model_unavailable`。

模型失败不删除确定性用例；保存 `partial_success`、已完成矩阵和可执行的人工补齐建议。

### 6.6 去重

用例指纹由以下字段 canonical SHA 生成：

- contract_id；
- dimension；
- execution_mode；
- parameter_mutations；
- dependency_contract_ids；
- expected_results/观察目标的规范化形式。

不能只根据用例名称去重。名称不同但测试输入和目标相同视为重复；名称相同但 mutation 不同可以并存。

## 7. 基础用例 Review 设计

### 7.1 API 响应

继续使用 `GET /tasks/{task_id}/cases`，返回：

```json
{
  "stage_state": "ready",
  "base_cases": {
    "version": 1,
    "sha256": "...",
    "lifecycle_status": "current",
    "generation_kernel": "v2_fused",
    "items": []
  },
  "coverage_matrix": {
    "version": 1,
    "items": [],
    "round_summaries": []
  }
}
```

旧响应兼容层继续保留一个发布周期。`items` 始终为数组。

### 7.2 Review 服务

`ApiReviewService.review_cases()` 增加服务端质量门禁：

- confirm 前重新计算 quality_report；
- blocker 存在时返回 409 和稳定错误码；
- `exploratory` 确认需要明确理由；
- `human_override` 生成新 Evidence 和审计记录；
- 高风险继续逐条审计；
- 修改 steps、expected_results、mutations、dependencies 后重新运行 Grounding；
- 任何 Review 生成新 base-cases 版本，不覆盖旧版本。

### 7.3 页面

修改 `task_detail.html`、`api-v2-workbench.js` 和 `api-v2-workbench.css`：

- 用例名称改为可聚焦详情按钮；
- 详情区域展示目标、步骤、参数变化、测试数据、依赖、预期、Evidence、质量门禁和历史；
- 用例编辑使用受控对话框，不开放任意 JSON 编辑；
- blocker 使用文字、图标/状态和颜色共同表达；
- 显示生成内核 `legacy/v2_minimal/v2_fused/human`；
- 显示覆盖轮次接受/拒绝数据；
- 键盘关闭详情后焦点返回原用例；
- `stale` 和 `legacy_validation_required` 明确只读。

不引入 React、Vue、图标库或新构建工具。

## 8. 融合可执行用例生成设计

### 8.1 生成方式

`fused_kernel.py` 使用 `api_case_generator.v2_prompt`，输入单条已确认基础用例、目标契约、依赖契约、测试数据目录和允许工具清单。

禁止向模型传递：

- 真实 base_url；
- 真实 Cookie、Token、密码和数据库凭证；
- 宿主路径；
- Docker/Kubernetes 控制参数；
- 任意模块或命令执行能力。

### 8.2 规范化

模型输出先转换为 V2 `ExecutableCase`：

- base_url 丢弃并替换为 target_id；
- URL 强制转换为相对 path；
- Header、Query、Cookie、Body 中的 Secret 只能引用变量；
- dependencies 转换为 `precondition_case_ids`；
- 环境变量和响应提取转换为 `VariableDefinition`；
- 断言转换为白名单 `AssertionDefinition`；
- 脚本保留为字符串，尚未通过 AST 前 `enabled=false`。

### 8.3 请求完整性校验

在现有静态校验前增加：

- 契约必填 Header 是否存在或有变量来源；
- 必填 Query/Path 是否存在；
- path 模板是否全部绑定；
- requestBody.required 时 body 不能为 null；
- body 必填字段是否存在或有 mutation/数据来源；
- Content-Type 是否与请求体契约一致；
- status_code 断言必须来自文档、基础用例人工决定或 exploratory 特殊规则；
- 基础用例 quality_report 必须通过；
- source_versions 必须为 current。

### 8.4 探索式用例

探索式用例可以生成执行定义，但：

- 只允许协议级安全断言，例如请求成功发送、响应可解析；
- 不把未声明的业务结果作为失败；
- 报告标记为“探索观察”；
- 不能基于探索观察自动生成产品缺陷候选；
- 人工 Review 后才能进入执行预览。

### 8.5 旧工作流兼容

旧 `api_run_case_wrokflow.py` 保留文件名和 CLI 导入路径，不在本期顺手更名。纯生成函数可以由旧 workflow 调用，减少两套生成逻辑漂移；旧数据库保存节点保持默认关闭。

## 9. 阶段记录、Prompt 来源与 Token

### 9.1 存储

每个 Attempt 增加：

```text
attempts/{attempt_id}/events.jsonl
attempts/{attempt_id}/model-usage.json
attempts/{attempt_id}/generation-provenance.json
```

`events.jsonl` 在 TaskStore 锁内追加、flush、fsync；单条事件先完成 Pydantic 校验和结构化脱敏。

`model-usage.json` 和 `generation-provenance.json` 使用临时文件、fsync、`os.replace` 原子写入。

事件只包含摘要和引用，不保存完整文档、完整 Prompt、Secret 或请求/响应正文。

### 9.2 模型调用包装器

参考功能测试智能体 `invoke_with_token_usage()`，API V2 包装器额外记录 Attempt、node、Prompt SHA 和重试序号。

调用过程：

1. 写 `model_call_started`；
2. 使用 `UsageMetadataCallbackHandler` 调用 LangChain；
3. 提取 input/output/total tokens；
4. 记录供应商是否报告；
5. 输出 Schema/Grounding 失败时把调用标记 `rejected`，但仍记录 Token；
6. 成功或异常均在 finally 中写用量和耗时；
7. Runner 终态聚合当前 Attempt 用量；
8. API 按 Attempt 汇总任务累计，不修改历史记录。

### 9.3 API

新增：

```http
GET /api-test-agent/api/v1/tasks/{task_id}/stage-events
GET /api-test-agent/api/v1/tasks/{task_id}/model-usage
GET /api-test-agent/api/v1/tasks/{task_id}/generation-provenance
```

参数：

- `attempt_id`；
- `run_id`；
- `stage`；
- `cursor`；
- `limit`，最大 500。

安全：

- 复用 `get_task()` 的所有权和 `task.view.all`；
- 只解析受控 ID，不接受路径；
- 返回前执行字段白名单和递归脱敏；
- 非管理员不返回异常堆栈或内部路径；
- 非 JSON 或损坏事件跳过并记录内部告警，不影响其他事件。

### 9.4 页面

在阶段工作台外层增加常驻“阶段记录”详情面板：

- 当前阶段默认筛选当前 Attempt；
- 可切换历史 Attempt 和阶段 1～4；
- 展示节点、状态、时间、耗时、输入/输出版本和错误；
- 模型调用展开后展示 Prompt ID/SHA、模型、Token、重试和 Grounding 结果；
- 原始 Runner 日志作为“技术日志”二级入口；
- 确定性阶段显示“未调用模型”；
- reported=false 显示“Token 未报告”。

## 10. 版本与历史兼容

### 10.1 内核选择

增加配置：

```text
API_GENERATION_KERNEL=v2_minimal|v2_fused
```

规则：

- 值在任务/Attempt 创建时快照，不在运行中动态切换；
- 本机开发和测试环境灰度开启 `v2_fused`；
- 生产初始保持 `v2_minimal`，通过黄金集后切换；
- 已创建 Attempt 继续使用快照值；
- 不允许一次 Attempt 混用两个内核的基础用例。

### 10.2 历史版本识别

读取层按以下规则补充内核标识：

- 文件显式字段优先；
- Schema V1/旧 CLI → `legacy`；
- Schema V2 且无字段 → `v2_minimal`；
- 新融合版本 → `v2_fused`；
- 页面人工新增 → `human`。

读取兼容不回写旧文件。

### 10.3 历史执行门禁

在 `execute/preview` 和 `execute` 共同调用的服务端校验中增加：

- 当前 executable 版本来源不是 current → 阻断；
- 来源基础用例没有新 quality_report → 执行兼容校验；
- 空 steps、空 expected/观察目标、必填 body=null、Grounding 不通过 → `LEGACY_VALIDATION_REQUIRED`；
- 阻断只影响创建新 Run，不修改历史 Run、报告和草稿。

用户可以从已确认契约选择融合内核重新生成，产生新 Attempt、新 base-cases、coverage 和 executable-cases 版本。

## 11. 状态机与失败恢复

保持现有 Task、Contract、Case 和 Run 主状态，不新增全局状态枚举。通过 stage、Attempt status 和阶段事件表达融合节点。

基础用例 Attempt：

```text
created
→ context_building
→ deterministic_generation
→ llm_generation
→ grounding
→ coverage_evaluation
→ waiting_case_review
```

执行定义 Attempt：

```text
created
→ executable_generation
→ normalization
→ static_validation
→ waiting_execution_confirmation / partial_success
```

失败规则：

- 上下文构造失败：Attempt failed，不创建空版本；
- 模型失败：保留确定性用例和上下文产物，可 partial_success；
- Grounding 全拒绝：保留拒绝记录和覆盖缺口；
- 单接口失败：其他接口继续，任务 partial_success；
- 版本保存失败：不移动 current pointer；
- 阶段事件写入失败：不掩盖业务错误，但在 Runner 结果增加 observability warning；
- Token 写入失败：调用结果仍可使用，记录 `MODEL_USAGE_UNAVAILABLE`；
- 重试创建新 Attempt，复用明确上游版本，不覆盖旧 Attempt。

## 12. 稳定错误码映射

在 `services/api_agent/errors.py` 和公共错误协议中增加：

| 错误码 | HTTP | 场景 | 是否可重试 |
| --- | --- | --- | --- |
| `CASE_GROUNDING_FAILED` | 409 | 用例缺少可验证依据 | 修改用例或 Evidence 后重试 |
| `CASE_EVIDENCE_MISSING` | 409 | Evidence 为空或版本无效 | 是，人工补充 |
| `CASE_STEPS_REQUIRED` | 409 | 确认时步骤为空 | 是 |
| `CASE_EXPECTATION_REQUIRED` | 409 | 无预期或观察目标 | 是 |
| `CASE_BUSINESS_ENTITY_UNSUPPORTED` | 409 | 引入文档无依据业务实体 | 是 |
| `CASE_DEPENDENCY_UNRESOLVED` | 409 | 依赖不存在或未确认 | 是 |
| `CASE_COVERAGE_LINK_REJECTED` | 422 | 无效候选不能关联覆盖项 | 否，保留缺口 |
| `EXECUTABLE_BODY_REQUIRED` | 422 | 必填请求体为空 | 是，重新生成/编辑基础用例 |
| `EXECUTABLE_SOURCE_CASE_INVALID` | 409 | 来源基础用例质量未通过 | 是 |
| `GENERATION_KERNEL_UNAVAILABLE` | 503 | 融合内核配置或模型不可用 | 是 |
| `PROMPT_PROVENANCE_MISSING` | 500 | 模型调用缺少 Prompt 来源 | 否，开发修复 |
| `MODEL_USAGE_UNREPORTED` | 200/告警 | 供应商未报告 Token | 否，不视为任务失败 |
| `LEGACY_VALIDATION_REQUIRED` | 409 | 历史执行定义未通过新门禁 | 是，融合重生成 |

批量确认时返回逐项结果；不能因为一条失败而静默确认其他 blocker 用例。

## 13. 文件级修改计划

### 13.1 旧核心与生成层

| 文件 | 修改内容 |
| --- | --- |
| `agents/api_test/prompts/base_case_generator.py` | 提取共享测试设计规则；保留旧 prompt；增加 V2 严格 Schema、Evidence 和分类输出 |
| `agents/api_test/prompts/base_case_check_coverage.py` | 保留旧 prompt；增加结构化 CoverageGap 输出，禁止文本 100% 作为 V2 判断 |
| `agents/api_test/prompts/supplement_case.py` | 增加 V2 缺口补齐 Prompt，要求 Evidence 和完整用例字段 |
| `agents/api_test/prompts/api_case_generator.py` | 增加 V2 执行候选 Prompt，输出相对 path、数据血缘、变量、依赖和断言 |
| `agents/api_test/workflows/api_basecase_workflow.py` | 调用共享纯生成函数；保留 CLI 图、stream writer 和默认关闭数据库行为 |
| `agents/api_test/workflows/api_run_case_wrokflow.py` | 调用共享执行候选生成函数；不改现有导入路径 |
| `agents/api_test/workflows/api_case_generator_main_workflow.py` | 只做旧 CLI 兼容，不进入平台 Runner |
| `agents/api_test/cases/fused_kernel.py` | 新增无副作用融合内核、上下文、模型调用和候选规范化 |
| `agents/api_test/cases/grounding.py` | 新增 Evidence、业务语义、参数、依赖和完整性门禁 |
| `agents/api_test/cases/coverage.py` | 接入 quality_report、round summary、有效关联和指纹去重 |
| `agents/api_test/cases/business_supplement.py` | 保留兼容入口，内部委托融合补齐器；逐步停止极简内联 Prompt |
| `agents/api_test/cases/executable.py` | 接入执行候选、请求完整性、来源质量和历史门禁 |

### 13.2 服务与存储

| 文件 | 修改内容 |
| --- | --- |
| `services/api_agent/models.py` | 增加用例扩展、Grounding、CoverageRound、Provenance、StageEvent 和 ModelUsage Schema |
| `services/api_agent/runner.py` | 使用内核快照选择融合生成；写阶段事件、用量和 provenance；保留分阶段重试 |
| `services/api_agent/v2_store.py` | 增加 Attempt 文档、事件追加和安全读取；历史兼容不回写 |
| `services/api_agent/task_manager.py` | 创建 Attempt 时快照 generation_kernel；Runner 环境注入 Attempt ID |
| `services/api_agent/review_service.py` | 确认/编辑前重新运行质量门禁；审计 exploratory 和 human_override |
| `services/api_agent/blueprint.py` | 增加三个只读可观察性接口；扩展 cases 和执行预览门禁 |
| `services/api_agent/errors.py` | 增加稳定错误码和建议动作 |
| `services/api_agent/stage_events.py` | 新增事件、Token、Prompt 来源和聚合服务 |
| `services/api_agent/execution_service.py` | 创建 Run 前再次验证来源版本和历史质量门禁 |
| `services/common/task_models.py` | 公共任务增加脱敏 Token 摘要和 generation kernel 字段 |
| `services/common/task_manager.py` | 成功/失败时合并 Attempt 摘要，不覆盖旧阶段产物 |

### 13.3 页面

| 文件 | 修改内容 |
| --- | --- |
| `services/api_agent/templates/task_detail.html` | 基础用例详情/编辑、生成内核标识、统一阶段记录、Token/Prompt 信息 |
| `services/common/static/api-v2-workbench.js` | 用例详情、质量门禁、事件游标、Attempt 筛选、Token 渲染 |
| `services/common/static/api-v2-workbench.css` | 详情抽屉、阶段记录和质量状态样式；保持 API 命名空间 |

### 13.4 测试

新增：

- `tests/api_v2/test_fused_kernel.py`；
- `tests/api_v2/test_case_grounding.py`；
- `tests/api_v2/test_stage_events.py`；
- `tests/api_v2/test_model_usage.py`。

扩展：

- `test_models.py`；
- `test_cases.py`；
- `test_runner_stages.py`；
- `test_review_service.py`；
- `test_execution_and_defects.py`；
- `test_web_routes.py`；
- 旧 workflow 和 CLI 兼容测试。

## 14. 分阶段开发计划

### M0：基线、黄金集和历史安全门禁

目标：先阻止当前错误执行定义继续创建新 Run，再开始替换生成内核。

实施：

- 固化登录、退出登录、当前用户、必填 Body、依赖接口黄金样例；
- 固化商品/订单/支付错误回放输出；
- 为当前 `v2_minimal` 空步骤、空预期、body=null 建立失败测试；
- 增加 generation_kernel 读取兼容；
- 在执行预览和执行入口增加 `LEGACY_VALIDATION_REQUIRED`；
- 不修改历史 Run 和报告。

验证：Schema、历史任务读取、执行预览阻断、旧报告可读。

风险：门禁上线后部分历史任务不能再次执行；页面必须给出融合重生成建议。

预计：2～3 人日。

### M1：Schema、Prompt 版本和纯生成内核

目标：建立 V2 融合 Schema 和无数据库/无执行副作用的生成调用。

实施：

- 扩展 BaseTestCase、CoverageMatrix、ExecutableCase；
- 增加 Provenance、StageEvent、ModelUsage；
- 为旧 Prompt 增加共享规则和 v2_prompt；
- 实现 `fused_kernel.py`；
- Fake Model 契约测试；
- 旧 CLI 继续使用旧 prompt 和导入路径。

验证：Pydantic 正反例、Prompt SHA 稳定、旧 CLI import、融合内核不导入数据库/执行器。

风险：Prompt 重构影响旧 CLI；必须先锁定旧 Prompt 快照和输出兼容测试。

预计：4～6 人日。

### M2：Grounding、覆盖矩阵和基础用例生成

目标：恢复旧测试设计能力并阻止无依据场景。

实施：

- 构造每 Contract GenerationContext；
- 确定性用例增加 mutation、Evidence 和预期；
- 调用 V2 基础用例 Prompt；
- 实现 Grounding/完整性/依赖门禁；
- 结构化覆盖关联和指纹去重；
- 最多 3 轮补齐及 round summary；
- 单接口失败保留其他接口。

验证：认证接口无商品/订单/支付；错误模型回放 100% 被拒；空步骤不能进入候选；3 轮停止；模型失败保留确定性用例。

风险：业务实体判断误杀；以 Evidence pointer 验证为主，不使用简单关键词黑名单。

预计：5～7 人日。

### M3：基础用例详情和 Review

目标：测试人员能够完整理解、编辑并确认用例。

实施：

- `/cases` 返回完整字段；
- Review 服务重新运行质量门禁；
- 用例详情、编辑、Evidence 和历史页面；
- exploratory/human_override 流程；
- 高风险逐条确认；
- stale/legacy 只读状态。

验证：RBAC、所有权、CSRF、409、键盘焦点、批量确认 blocker、高风险审计。

风险：详情信息密度较高；沿用现有工作台，不把全部字段塞回列表表格。

预计：3～5 人日。

### M4：完整可执行用例生成与静态校验

目标：恢复旧接口依赖、测试数据和请求生成能力，并由 V2 安全放行。

实施：

- 接入 `api_case_generator.v2_prompt`；
- 规范化相对 path、Header、Query、Cookie、Body、变量、依赖和断言；
- 增加请求完整性、来源质量和版本门禁；
- exploratory 执行规则；
- 生成 provenance；
- 禁止旧执行器进入平台调用链。

验证：登录请求 Body、Cookie/CSRF、依赖变量、循环依赖、断言、AST、必填 Body、stale 和高风险负向测试。

风险：旧 Prompt 可能生成自由脚本；所有输出默认 disabled，静态校验通过后才 ready。

预计：5～7 人日。

### M5：阶段事件、Prompt 来源和 Token

目标：阶段 1～4 的真实过程可见。

实施：

- Attempt 事件、model usage、provenance 原子存储；
- 模型调用包装器；
- 三个只读 API；
- 常驻阶段记录面板；
- Prompt SHA、模型、Token、重试和拒绝原因；
- 成功阶段也写事件；
- 技术日志作为二级入口。

验证：游标、非法 ID、脱敏、未报告 usage、失败调用 Token、阶段切换、Attempt 汇总和只读角色。

风险：日志过量；事件只保存产品级摘要，限制单事件大小和接口分页。

预计：3～5 人日。

### M6：旧工作流兼容和融合回归

目标：确认恢复旧核心没有破坏旧 CLI 和 V2 治理能力。

实施：

- 旧 workflow 委托共享纯函数；
- 保留旧 prompt、类名和文件路径；
- 数据库默认关闭；
- 旧 CLI 只在显式命令使用，平台静态扫描不导入；
- 新旧内核黄金集对比；
- 执行、报告和 Bug 草稿回归。

验证：旧 CLI 生成测试、平台 import 图、无 MySQL 写入、无旧执行调用、历史任务读取。

风险：共享函数改变旧输出；使用兼容映射，不要求旧 CLI 输出升级为 V2 Schema。

预计：3～4 人日。

### M7：浏览器验收、灰度和发布

目标：安全切换新任务到 `v2_fused`。

实施：

- 1440×900、1280×800 验收；
- 覆盖用例详情、编辑、Grounding blocker、覆盖补齐、阶段记录和 Token；
- 本机测试环境运行 Mock/非生产目标；
- 先上线历史门禁，再灰度基础用例，再灰度可执行生成；
- 监控 Grounding 拒绝率、人工禁用率、静态校验和 Token。

验证：完整端到端、浏览器键盘、焦点、非颜色状态、reduced motion、回滚演练。

风险：灰度期间用户混淆内核版本；所有版本和页面必须明确显示 generation_kernel。

预计：3～5 人日。

总预计：28～42 人日，不包含 P2、真实执行基础设施扩容和外部系统集成。

## 15. 测试设计

### 15.1 单元测试

- GenerationContext 最小化和脱敏；
- BaseTestCase/Mutation/Evidence/Quality Schema；
- Prompt ID 和 SHA；
- Grounding 每条规则；
- 指纹去重；
- 覆盖轮次停止；
- 请求完整性；
- ModelUsage reported/unreported；
- StageEvent 序列化和大小限制。

### 15.2 契约和 API 测试

- `/cases` 新旧结构；
- confirm blocker；
- exploratory/human_override；
- stage-events 游标和筛选；
- model-usage 聚合；
- generation-provenance 白名单；
- 执行预览历史门禁；
- 任务所有权、RBAC、CSRF、路径遍历和非法 ID。

### 15.3 黄金集

至少包含：

1. 登录、失败锁定和 Session Cookie；
2. 退出登录、Cookie 和 CSRF Header；
3. 当前用户信息；
4. OpenAPI 2.0 请求体；
5. OpenAPI 3.x requestBody；
6. Path/Query/Header 混合参数；
7. 前置登录获取 Token；
8. 多接口依赖和变量提取；
9. 文档明确状态流转；
10. 文档无业务语义的探索式接口；
11. 商品/订单/支付幻觉回放；
12. 恶意脚本、远程 `$ref`、路径穿越和 Secret 输入。

### 15.4 集成测试

- 契约确认 → 融合基础用例 → Review → 执行候选 → 静态校验；
- 模型限流、超时、鉴权失败和格式错误；
- 单接口失败 partial_success；
- 重新分析使旧下游 stale；
- 重试创建新 Attempt；
- Prompt/Token/事件在失败后仍可查看；
- Fake Controller Run、报告和 Bug 草稿不受生成内核变化影响。

### 15.5 安全负向测试

- Prompt 注入不得修改契约和执行目标；
- 模型输出真实 Host 被剥离；
- Secret 不进入上下文、事件、Prompt 来源和下载；
- setup/teardown 文件、进程、网络、反射调用被阻断；
- 历史 body=null 无法创建 Run；
- 旧 `execute_test_cases()` 不在平台 import graph；
- Web 服务不新增 Docker Socket、数据库凭证或目标 Credential。

## 16. 测试命令

每个里程碑运行相关子集，最终运行：

```bash
cd /Users/admin/Testproject/api-test-agent
python3 -m pytest -q tests/api_v2
python3 -m pytest -q tests/services
python3 -m pytest -q

cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q

cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run
npm run build

cd /Users/admin/Testproject/test-platform
docker compose config --quiet
python3 -m unittest discover -s tests -v
```

专项静态检查：

```bash
rg -n "execute_test_cases|TestExecutor|pymysql|Docker Socket" services/api_agent agents/api_test/cases
rg -n "submit|Provider Secret|asset publish" services/api_agent agents/api_test
```

静态搜索结果需要人工判断允许的旧 CLI 定义和测试引用，平台 Runner、融合内核和 Web 调用链不得出现旧执行器或数据库写入。

## 17. 浏览器验收

使用已认证平台会话，在 1440×900 和 1280×800 验收：

1. 登录文档的契约确认；
2. 基础用例详情；
3. 商品/订单/支付候选被拒绝；
4. 用例编辑和重新 Grounding；
5. 高风险和 exploratory 确认；
6. 覆盖轮次和拒绝原因；
7. 执行定义请求详情；
8. 必填 Body 阻断；
9. 阶段 1～4 记录；
10. Prompt、模型、Token 和 Attempt；
11. 历史 `v2_minimal` 阻断和融合重生成；
12. 执行预览、Run、报告和 Bug 草稿回归。

检查键盘、焦点返回、ARIA 状态、非颜色提示和 reduced motion。截图只用于视觉对比，主要操作必须真实调用本机接口。

## 18. 发布门禁

必须同时满足：

- 认证接口黄金集不再生成无关业务场景；
- 固定无依据回放输出 100% 被拒；
- 空步骤、空预期、必填 body=null 不得进入 ready；
- 覆盖补齐最多 3 轮；
- 旧 CLI import 和基础生成兼容；
- 平台不调用旧执行器和 MySQL 保存；
- 阶段 1～4 有结构化记录；
- Token 未报告状态正确；
- 全量 API Agent 测试通过；
- 平台相关回归通过；
- 浏览器验收通过；
- `API_EXECUTION_ENABLED` 和 S2 安全边界没有被绕过；
- 未增加外部 Bug 提交或稳定资产发布能力。

## 19. 回滚方案

1. 将 `API_GENERATION_KERNEL` 切回 `v2_minimal` 或停止创建新生成 Attempt；
2. 已生成 `v2_fused` 版本保持只读，不删除、不改写；
3. current pointer 只允许切回已验证来源 SHA 的上一版本；
4. 历史安全门禁保持生效，不因回滚重新允许不完整用例执行；
5. 不回滚契约、文档修订、Run、报告和 Bug 草稿；
6. 不启用旧 CLI 直接执行作为降级方案；
7. 本期无数据库迁移，不需要 database downgrade。

## 20. 实施期间保护项

- 当前工作区已有 V2.1 未提交代码，实施前逐文件保存 diff 基线；
- 不 reset、checkout、覆盖或删除用户改动；
- 不修改与融合生成无关的 Gateway、平台 React 和外部系统模块；
- 不创建 Git 分支、Commit 或 PR；
- 不连接真实生产目标；
- 不配置新的真实 Credential、Egress 或容器权限；
- 不重命名 `api_run_case_wrokflow.py` 等旧兼容路径；
- 新注释解释复杂规则、安全边界和状态转换，不复述显而易见代码。

## 21. 最终交付说明要求

实施完成后交付说明必须包含：

1. M0～M7 完成状态；
2. PRD `KERNEL-01～10`、`OBS-01～04`、`COMPAT-01～02` 对应实现；
3. 修改文件及作用；
4. 旧核心实际复用点和未复用原因；
5. 当前 V2 与设计文档的实现差异；
6. 测试命令和结果；
7. 黄金集对比结果；
8. 未完成项和已知风险；
9. 灰度和回滚状态；
10. 明确说明平台是否调用旧执行器或 MySQL 持久化；
11. 明确说明 `API_EXECUTION_ENABLED` 状态、是否发送真实请求、是否创建真实容器；
12. 明确说明是否存在外部 Bug 提交或稳定资产发布能力。

## 22. 完成定义

本计划只有在以下结果同时成立时才算完成：

> 用户在覆盖矩阵与基础用例 Review 中重新看到旧 API 测试智能体应有的测试场景、步骤、依赖、数据和预期；每条内容又具备 V2 的契约依据、人工控制、版本追溯和安全门禁；最终执行仍只通过受控 Controller/Executor 完成。
