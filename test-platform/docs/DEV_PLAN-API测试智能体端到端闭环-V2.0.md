# API 测试智能体端到端闭环 V2.0 详细开发设计与计划

> 文档版本：V1.0  
> 编写日期：2026-08-13  
> 文档状态：待技术评审  
> 对应 PRD：`PRD-API测试智能体端到端闭环-V2.0.md`  
> 适用范围：`AItestcase_Agents`、`test-platform` 及新增的受控执行运行时

---

## 1. 文档目标

本文档把《API 测试智能体端到端闭环 PRD V2.0》转化为可分阶段实施的技术方案，明确：

- 现有代码的保留、扩展和替换边界；
- API 文档确定性解析与 LLM 解析的路由；
- 借鉴功能测试智能体后的证据、防幻觉和质量门禁实现；
- 接口契约与测试用例的 Review 数据和状态流；
- 阶段性产物、错误分类和从失败阶段重试；
- 每个 ExecutionRun 一个独立受限容器的执行架构；
- 执行结果、慢响应候选和本地 Bug 草稿；
- 页面、HTTP 接口、权限、审计、测试和上线门禁；
- P0-A、P0-B、P0-C、P1、P2 的文件级开发计划。

本设计不实现：

- 外部缺陷系统 Provider 或自动提交 Bug；
- 稳定资产发布到 `api-autotest`；
- Postman Collection 导入；
- gRPC、WebSocket、GraphQL；
- 压测、并发、吞吐量、P95/P99 性能测试；
- 自动创建 Git 分支、提交或 PR。

---

## 2. 已确认产品决策

| 决策项 | 最终决定 | 设计影响 |
| --- | --- | --- |
| Bug 处理 | 只生成、编辑、下载本地 Bug 草稿 | 不设计外部 Provider、提交接口和状态同步 |
| 执行环境 | 每个 ExecutionRun 使用独立短生命周期受限容器 | Web 服务不得直接执行真实请求或动态脚本 |
| 稳定资产发布 | 当前版本不实现，进入后续需求池 `POOL-019` | 不增加目标项目写权限、发布包或 Git 流程 |
| 慢响应 | SLA 优先；无 SLA 默认软阈值 3000ms；连续 3 次超限才可生成草稿 | 需要保存每次 Attempt 耗时与阈值来源 |
| 输入格式 | HTTP/Gateway 文档；OpenAPI/Swagger 与非结构化文本 | Postman、gRPC、WebSocket、GraphQL 明确拒绝 |

---

## 3. 现有系统基线

### 3.1 已有能力

当前 API 智能体已具备：

- 独立 Flask 服务和 `/api-test-agent/` 入口；
- 平台身份、RBAC、CSRF、任务所有权和审计；
- 持久化单槽 FIFO、Runner 子进程、取消和重启恢复；
- `.md/.txt/.json/.yaml/.yml` 上传和粘贴文本；
- LLM 文档解析、基础用例和可执行用例生成；
- 可执行脚本 Python 语法检查；
- 文件产物发布、日志增量读取和任务详情；
- 模型、Prompt Bundle、配置 Release 和应用版本追踪；
- 数据库写入可选且默认关闭；
- 真实 API 执行强制关闭。

### 3.2 现有关键代码

| 文件 | 当前职责 | V2.0 处理方式 |
| --- | --- | --- |
| `services/api_agent/app.py` | API 服务入口，只注册解析和生成 | 保留入口，扩展 API 专用路由和管理器 |
| `services/api_agent/runner.py` | 解析和生成任务 Runner | 拆分为阶段编排入口，禁止加入真实请求执行 |
| `services/api_agent/adapter.py` | 收集四类 JSON 产物 | 扩展为阶段产物注册，保留已有产物兼容 |
| `services/common/task_manager.py` | 单槽 FIFO 与生成子进程 | 保留生成队列；执行 Run 使用独立 RunManager |
| `services/common/task_store.py` | 文件化任务事实来源 | 保留并扩展版本、Attempt 和 Run 子目录 |
| `services/common/web.py` | 两个智能体公共 Web 协议 | 只保留公共协议；API 专属路由不得继续堆入公共文件 |
| `agents/api_test/parsers/ai_parser_api_document.py` | 全部文档经 LLM 解析 | 仅作为非结构化解析器，输出映射到新 Schema |
| `agents/api_test/workflows/api_basecase_workflow.py` | 生成、覆盖检查、补齐循环 | 改为结构化覆盖矩阵和固定补齐轮次 |
| `agents/api_test/workflows/api_run_case_wrokflow.py` | 可执行用例生成与语法检查 | 保留生成核心，增加 Schema、策略和依赖校验 |
| `agents/api_test/api_testcase_agent.py` | 旧 CLI 完整流程，含直接执行和报告 | CLI 兼容保留；平台不得调用旧 `execute_test_cases()` |

### 3.3 已知差距

- OpenAPI JSON/YAML 仍完全依赖 LLM，确定性不足且浪费模型调用。
- 缺少 `ApiContract` 证据、冲突、歧义和人工确认状态。
- 契约和用例没有页面 Review。
- 覆盖率通过依赖模型文本中的 `100%`，补齐循环没有明确上限。
- Runner 失败后只在成功终态统一发布产物，已完成阶段产物不可见。
- 错误页缺少建议动作和阶段重试。
- 平台执行接口固定关闭，旧 CLI 执行逻辑不具备正式隔离边界。
- 没有标准 Run/CaseResult、本地 Bug 草稿和慢响应重复验证模型。

---

## 4. 设计原则

1. **契约事实优先**：确定性解析器得到的字段是第一事实来源，LLM 不得静默覆盖。
2. **证据可追溯**：关键字段必须关联结构节点或原文片段。
3. **事实与建议分离**：AI 推断进入建议或未解决项，不伪装为接口契约。
4. **人工门禁**：契约、用例、高风险执行分别确认。
5. **阶段产物不回退**：后续失败不得删除或隐藏已经成功的上游产物。
6. **生成和执行隔离**：Web 与生成 Runner 不发送目标请求；执行容器不获得模型和平台凭证。
7. **一个 Run 一个容器**：容器短生命周期，不复用跨 Run 状态。
8. **默认拒绝网络**：执行容器不能直接访问任意网络，只能通过受控出口访问允许目标。
9. **文件事实来源优先**：本阶段沿用任务文件存储，不先引入新的统一资产数据库。
10. **最小改动分期上线**：每一阶段都可独立验收、关闭和回滚。

---

## 5. 总体架构

```text
浏览器
  │
  ▼
平台 Gateway / RBAC / CSRF
  │
  ▼
API Agent Web（不持有容器运行时权限）
  ├── TaskStore / Artifact Registry
  ├── Generation TaskManager
  ├── Contract Review Service
  ├── Case Review Service
  ├── RunManager
  └── DefectDraft Service
          │
          ├── 生成 Runner 子进程
          │     ├── 文档预检
          │     ├── 确定性/LLM 契约解析
          │     ├── 质量门禁
          │     ├── 基础用例与覆盖矩阵
          │     └── 可执行用例与静态校验
          │
          └── 内部鉴权 API
                ▼
        Execution Controller
        （唯一拥有创建受限容器权限的服务）
                │
                ▼
        单 Run 短生命周期执行容器
        ├── 只读输入挂载
        ├── 独立可写输出目录
        ├── 非 root / 只读根文件系统
        ├── CPU/内存/PID/磁盘/时长限制
        └── 仅连接受控 Egress Proxy
                │
                ▼
        DNS/重定向重校验 + 目标允许列表
                │
                ▼
        已登记的 HTTP/Gateway 测试目标
```

### 5.1 服务边界

| 服务 | 可以访问 | 禁止访问 |
| --- | --- | --- |
| API Agent Web | 平台运行配置、任务目录、Controller 内部 API | Docker Socket、目标网络、执行容器文件系统 |
| 生成 Runner | 当前任务输入/输出、LLM Secret、可选生成数据库 | 目标 API、平台 KEK、其他任务目录 |
| Execution Controller | 固定执行镜像、Run 输入/输出、容器运行时 | 用户文档正文、LLM Secret、平台数据库业务数据 |
| 执行容器 | 当前 Run 只读输入、当前 Run 输出、短期目标凭证、Egress Proxy | Docker Socket、源码写目录、平台内部网络、其他 Run |
| Egress Proxy | 已批准目标及必要 DNS | 平台内部网段、链接本地地址、元数据地址、未登记目标 |

### 5.2 为什么不由 Web 服务直接创建容器

API Web 服务需要处理用户输入和平台身份，属于高暴露面服务。若其持有 Docker Socket 或等价宿主机权限，一处 Web 漏洞可能扩大为宿主机控制。因此：

- Web 只调用 Controller 的窄接口；
- Controller 只接受平台预定义的镜像、资源模板和挂载路径；
- 用户不能提交镜像名、任意挂载、启动命令、网络模式或 capability；
- Controller API 仅在内部网络开放，并使用独立短期服务凭证；
- Controller 不提供通用容器管理或命令执行接口。

---

## 6. 任务、Attempt、Run 与版本模型

### 6.1 对象关系

```text
Task
  ├── DocumentVersion 1..n
  ├── ContractVersion 0..n
  ├── BaseCaseVersion 0..n
  ├── ExecutableCaseVersion 0..n
  ├── GenerationAttempt 1..n
  └── ExecutionRun 0..n
        ├── CaseResult 1..n
        ├── ExecutionAttempt 1..n
        ├── TestReport 1
        └── DefectDraft 0..n
```

### 6.2 状态模型

`TaskStatus` 扩展为：

```text
pending
running
waiting_contract_review
waiting_case_review
waiting_execution_confirmation
partial_success
succeeded
failed
cancelled
```

终态：`partial_success`、`succeeded`、`failed`、`cancelled`。等待 Review 和等待执行确认不是终态，不参与自动清理。

### 6.3 合法状态迁移

| 当前状态 | 触发 | 下一状态 |
| --- | --- | --- |
| `pending` | 调度启动 | `running` |
| `running/contract_quality_gate` | 有可 Review 契约 | `waiting_contract_review` |
| `waiting_contract_review` | Review 确认并请求生成 | `pending` |
| `running/coverage_validation` | 有可 Review 用例 | `waiting_case_review` |
| `waiting_case_review` | Review 确认并请求生成可执行用例 | `pending` |
| `running/executable_validation` | 执行未申请 | `succeeded` 或 `partial_success` |
| `running/executable_validation` | 申请执行且环境就绪 | `waiting_execution_confirmation` |
| `waiting_execution_confirmation` | 用户确认 | Task 保持等待/已生成，创建独立 `ExecutionRun` |
| 非终态 | 用户取消 | `cancelled` |
| 任一阶段 | 可恢复失败 | `failed`，保留 `retry_from_stage` |

执行 Run 使用独立状态：

```text
created → validating → provisioning → running → reporting
       → succeeded / failed / cancelled / timed_out
```

### 6.4 兼容策略

- 旧任务 `schema_version=1` 继续只读展示。
- 新任务使用 `schema_version=2`。
- 读取层对旧 `waiting_review` 映射为原功能智能体语义，不全局替换。
- API 新状态只在 API 专用模型中扩展，避免影响功能智能体既有 Review。
- 不批量修改历史任务文件；需要重试时以新任务或新 Attempt 进入 V2 Schema。

---

## 7. 文件存储设计

### 7.1 任务目录

```text
runtime/<environment>/api/tasks/<task_id>/
├── task.json
├── request.json
├── artifacts.json
├── input/
│   ├── source.yaml
│   └── document-profile.json
├── versions/
│   ├── contracts/
│   │   ├── v1-generated.json
│   │   └── v2-reviewed.json
│   ├── base-cases/
│   │   ├── v1-generated.json
│   │   └── v2-reviewed.json
│   └── executable-cases/
│       └── v1.json
├── attempts/
│   └── generation-001/
│       ├── result.json
│       └── console.log
├── runs/
│   └── <run_id>/
│       ├── run.json
│       ├── execution-input.json
│       ├── execution-result.json
│       ├── report.json
│       ├── console.log
│       ├── output/
│       └── defect-drafts/
│           ├── <draft_id>-v1.json
│           └── <draft_id>-v2.json
├── work/
└── published/
```

### 7.2 原子性

- 所有 JSON 使用临时文件、`fsync`、`os.replace` 原子提交。
- Review 先校验新版本，再更新 `task.json` 的当前版本指针。
- 阶段完成后立即注册该阶段产物，不等待整个 Runner 成功。
- `artifacts.json` 更新使用锁内读改写，防止阶段产物互相覆盖。
- Run 输入完成 SHA-256 后变为只读；Controller 校验 SHA 后才启动容器。

### 7.3 保留策略

- 任务摘要 180 天，输入/日志/产物 90 天，沿用现有默认值。
- `waiting_contract_review`、`waiting_case_review`、`waiting_execution_confirmation` 不自动清理。
- 运行中 Run 和未完成报告不清理。
- 本地 Bug 草稿跟随 Run 产物保留期，不单独无限保存。

---

## 8. 核心数据模型

### 8.1 ApiContract

建议新增 `agents/api_test/contracts/schema.py`：

```python
class ApiContract(BaseModel):
    contract_id: str
    name: str
    summary: str = ""
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str
    servers: list[ServerDefinition] = []
    parameters: list[ContractParameter] = []
    request_body: RequestBodyDefinition | None = None
    responses: list[ResponseDefinition] = []
    security: list[SecurityRequirement] = []
    dependencies: list[ApiDependency] = []
    source_trace: SourceTrace
    field_evidence: list[FieldEvidence] = []
    unresolved: list[ReviewIssue] = []
    ambiguity_notes: list[ReviewIssue] = []
    conflict_items: list[ReviewIssue] = []
    test_design_suggestions: list[TestSuggestion] = []
    quality_report: ContractQualityReport
    status: Literal["draft", "confirmed_candidate", "confirmed", "changed", "deprecated"]
```

实现要求：

- Pydantic `extra="forbid"`。
- `path` 必须是相对路径，以 `/` 开头，不允许协议和 Host。
- 参数位置只允许 `header/path/query/cookie`。
- Path 参数必须与路径模板一致。
- 所有人工修改记录 `field/source/old_value/new_value/reason/actor/updated_at`。

### 8.2 FieldEvidence

```text
field_path       例如 parameters[2].required
value            规范化后的字段值
source_type      openapi_node / source_quote / human_override
source_pointer   JSON Pointer 或 section_id
quote            非结构化文档原文；结构化节点可为空
evidence_type    explicit / inferred / missing / conflict
confidence       0..1
```

关键字段 `method/path/parameter.name/parameter.location/required/schema/security/response.status` 必须有 evidence。

### 8.3 BaseTestCase 与 CoverageMatrix

`BaseTestCase` 至少包含：

```text
case_id, contract_id, name, objective, dimension, risk_level,
preconditions, steps, expected_results, source, status, disabled_reason
```

`CoverageMatrixItem`：

```text
coverage_id, contract_id, dimension, rule, required,
covered, case_ids, decision_source, confidence, gap_reason
```

`decision_source` 只允许 `deterministic/llm/human`。

### 8.4 ExecutableCase

保留现有请求、前置依赖和脚本语义，但增加明确字段：

```text
executable_case_id
base_case_id
contract_id
name
risk_level
request
preconditions
assertions
variables
setup_script
teardown_script
validation_status
validation_issues
enabled
```

执行前要求 `validation_status=ready` 且 `enabled=true`。

### 8.5 ExecutionRun 与 CaseResult

`ExecutionRun`：

```text
run_id, task_id, executable_case_version, environment,
target_id, resolved_base_url_masked, status, created_by,
confirmed_by, config_release_id, container_ref, timestamps,
summary, error_code, error_message
```

`container_ref` 只保存在内部字段，不返回浏览器。

`CaseResult`：

```text
case_id, status, started_at, finished_at, duration_ms,
step_results, request_summary, response_summary,
assertion_results, failure_classification, error_signature,
performance_evaluation
```

### 8.6 DefectDraft

```text
draft_id, version, task_id, run_id, case_ids, title,
module, interface, severity_suggestion, environment,
preconditions, reproduction_steps, masked_request,
expected_result, actual_result, status_code, request_id,
error_summary, evidence_links, ai_analysis, confidence,
open_questions, created_by, updated_by, timestamps
```

约束：

- 仅本地版本化文件，不包含 `provider/external_id/external_url/submitted_at`。
- 保存前再次脱敏。
- 支持 JSON、Markdown 下载。
- 编辑永不覆盖旧版本。

---

## 9. 文档预检与解析设计

### 9.1 预检流程

```text
读取 UTF-8 文本
→ 扩展名与大小校验
→ JSON/YAML 安全加载
→ 格式指纹识别
→ Secret 特征扫描与脱敏标记
→ 生成 document-profile.json
→ 路由解析器
```

禁止 YAML 自定义对象构造，必须使用安全加载器。JSON/YAML 最大嵌套深度、节点数和别名展开量需限制，防止解析资源耗尽。

### 9.2 格式识别

| 格式 | 判断依据 | 处理 |
| --- | --- | --- |
| OpenAPI 3.x | 根节点 `openapi: 3.*` 且存在 `paths` | 确定性解析 |
| Swagger 2.0 | 根节点 `swagger: "2.0"` 且存在 `paths` | 确定性解析并规范化 |
| Markdown/TXT | 文本且不符合上述结构 | 切片后 LLM 解析 |
| Postman Collection | 存在 `info.schema` 的 Postman Collection 特征 | `DOCUMENT_FORMAT_UNSUPPORTED` |
| GraphQL/gRPC/AsyncAPI | 命中特征字段 | `DOCUMENT_FORMAT_UNSUPPORTED` |
| 普通 JSON/YAML | 无明确规范 | 作为非结构化内容进入 LLM，但显示低信任提示 |

### 9.3 确定性 OpenAPI 解析器

建议新增：

```text
agents/api_test/contracts/
├── schema.py
├── format_detector.py
├── openapi_parser.py
├── unstructured_parser.py
├── normalizer.py
├── evidence.py
└── quality_gate.py
```

`openapi_parser.py` 负责：

- 解析 `servers/basePath/host/schemes` 为元数据；
- 展开本地 `$ref`；首期不读取远程 `$ref`；
- 合并 path-level 与 operation-level 参数；
- 保留参数位置、必填、Schema、示例和描述；
- 解析 requestBody content；
- 解析 responses 和 security；
- 为每个字段生成 JSON Pointer evidence；
- 把 method/path 生成稳定 `contract_id`。

远程 `$ref` 返回未解决项，不允许 Parser 主动联网。

### 9.4 非结构化解析器

参考 `requirement_decomposition` 的方法：

1. 保留全文和 SHA。
2. 按标题和接口特征切片。
3. LLM 将片段拆成接口草稿。
4. 抽取契约事实和测试建议。
5. 绑定字段证据。
6. Grounding Check。
7. 无证据事实移动到建议或未解决项。
8. 应用契约质量门禁。

不得直接依赖功能需求 `Requirement` 模型；只复用可抽象的证据和质量门禁思想。首期避免为复用而重构整个 `requirement_decomposition`，可在 API 目录实现小型专用模块，待模型稳定后再评估公共包抽取。

### 9.5 质量评分

建议评分：

```text
关键字段完整率       25%
字段证据率           25%
Schema 有效率        20%
Grounding 通过率     15%
冲突解决率           10%
未支持事实惩罚        5%
```

进入 `confirmed_candidate` 的硬门禁：

- method/path 有效；
- 关键 evidence 齐全；
- 无未处理关键冲突；
- Grounding 通过；
- Schema 有效；
- `unsupported_facts=0`。

质量分只用于解释，不能覆盖硬门禁。

---

## 10. 契约 Review 设计

### 10.1 API

```text
GET  /api-test-agent/api/v1/tasks/{task_id}/contracts
GET  /api-test-agent/api/v1/tasks/{task_id}/contracts/{contract_id}
POST /api-test-agent/api/v1/tasks/{task_id}/contracts/review
POST /api-test-agent/api/v1/tasks/{task_id}/contracts/reparse
```

Review 请求包含：

```json
{
  "base_version": 1,
  "decisions": [
    {
      "contract_id": "contract_login_post",
      "action": "confirm",
      "patch": [],
      "reason": "与开发确认文档内容正确"
    }
  ],
  "continue_to_case_generation": true
}
```

### 10.2 并发控制

- `base_version` 必填。
- 当前版本变化时返回 `409 REVIEW_VERSION_CONFLICT`。
- Patch 仅允许修改白名单业务字段，禁止改 task_id、证据来源、创建者和版本元数据。
- Review 完成生成新契约版本。
- 批量确认只接受没有硬阻断项的 `confirmed_candidate`。

### 10.3 权限与审计

- 查看：`tool.result.view` + 所有权/`task.view.all`。
- Review：`api-test-agent.contract.review` + 所有权。
- 审计只记录 contract_id、action、字段路径和版本，不记录完整文档或 Secret。

### 10.4 页面

新增 API 专属模板，避免功能智能体公共模板过度分支：

```text
services/api_agent/templates/
├── index.html
├── task_detail.html
├── contract_review.html
├── case_review.html
├── execution_confirm.html
├── run_detail.html
└── defect_draft.html
```

契约 Review 页面桌面布局：

- 左栏 280px：接口、方法、路径、状态、问题数；
- 主栏：字段表单和 Schema；
- 右栏 360px：证据、AI 建议、冲突和历史；
- 顶部固定当前版本、质量摘要和主要操作；
- 长 Schema 默认折叠，可搜索字段路径。

---

## 11. 用例生成与 Review 设计

### 11.1 生成流程

```text
读取 confirmed ApiContract
→ 确定性规则生成基础覆盖骨架
→ LLM 生成业务场景候选
→ 合并和去重
→ 构建结构化 CoverageMatrix
→ LLM 只判断未确定覆盖项
→ 最多补齐 3 轮
→ 保存 base-cases 与 coverage-matrix
→ waiting_case_review
```

### 11.2 确定性覆盖规则

`rules/coverage_rules.py` 根据契约生成：

- 每个接口一个正常请求候选；
- 每个必填参数一个缺失候选；
- 类型、枚举、长度和数值边界候选；
- 鉴权缺失候选；
- 写方法的重复提交/幂等候选；
- 文档声明错误响应的对应候选。

规则生成的是基础测试意图，不直接填入危险 Payload 或真实凭证。

### 11.3 补齐终止

- `coverage_round` 初始为 0，最大 3。
- 每轮必须返回结构化 `missing_coverage_ids`。
- 新增用例数量为 0 或缺口集合连续两轮不变化时提前终止。
- 仍有缺口时任务进入 `partial_success` 候选，用户可接受缺口或人工补充。
- 不读取模型自由文本中的百分比决定路由。

### 11.4 用例 Review API

```text
GET  /api-test-agent/api/v1/tasks/{task_id}/cases
POST /api-test-agent/api/v1/tasks/{task_id}/cases/review
POST /api-test-agent/api/v1/tasks/{task_id}/cases/generate-executable
```

Review 支持：确认、编辑、新增、禁用、接受覆盖缺口。高风险用例必须逐条决策。

### 11.5 可执行用例校验

新增验证链：

1. Pydantic/JSON Schema。
2. method/path 与契约一致性。
3. 变量定义和使用关系。
4. 前置依赖拓扑及循环检测。
5. 断言操作符白名单。
6. setup/teardown `compile()` 语法检查。
7. AST 静态策略检查。
8. 目标 Host 不写入用例，只保存 `target_id` 占位。

AST 首期禁止：

- `subprocess`、`socket`、`ctypes`、`multiprocessing`、`importlib`；
- `os.system`、进程创建和信号操作；
- 任意文件读写；
- 动态 `eval/exec/compile/__import__`；
- 反射访问双下划线属性。

静态策略不能代替容器隔离，只作为提前失败提示。

---

## 12. 阶段产物与重试设计

### 12.1 阶段提交器

建议新增 `services/api_agent/stage_artifacts.py`：

```text
commit_stage_artifacts(task_id, stage, files, summary)
```

职责：

- 校验文件在当前任务目录内；
- 发布文件并计算 SHA；
- 合并产物注册表；
- 更新 `completed_stages` 和阶段摘要；
- 不提交任务终态。

这样解析成功、生成失败时，契约仍可下载和 Review。

### 12.2 GenerationAttempt

```text
attempt_id
task_id
from_stage
input_versions
config_release
model/prompt_hash
status/timestamps
completed_stages
error_code/error_message
```

### 12.3 从失败阶段重试

接口：

```text
POST /api-test-agent/api/v1/tasks/{task_id}/retry
```

请求：

```json
{
  "from_stage": "base_case_generation",
  "reuse": {
    "contract_version": 2
  }
}
```

服务端只允许从 `retryable_stages` 重试，并验证依赖版本存在、SHA 正确和状态已确认。新 Attempt 写新目录，不能清空旧日志。

### 12.4 错误分类

在 `services/common/errors.py` 增加稳定类型，但 API 业务错误的映射器放入 `services/api_agent/errors.py`，避免污染功能智能体：

```text
DOCUMENT_EMPTY
DOCUMENT_SYNTAX_INVALID
DOCUMENT_FORMAT_UNSUPPORTED
CONTRACT_PARSE_FAILED
CONTRACT_QUALITY_FAILED
REVIEW_VERSION_CONFLICT
CASE_SCHEMA_INVALID
CASE_VALIDATION_FAILED
WORKER_DEPENDENCY_MISSING
EXECUTION_NOT_READY
TARGET_NOT_ALLOWED
EXECUTION_PROVISION_FAILED
EXECUTION_TIMEOUT
ASSERTION_FAILED
DEFECT_DRAFT_INVALID
```

`ModuleNotFoundError` 映射为 `WORKER_DEPENDENCY_MISSING`；429/额度不足继续映射 `LLM_RATE_LIMITED`。

---

## 13. 独立受限容器执行设计

### 13.1 启用门禁

配置需同时满足：

```text
API_EXECUTION_ENABLED=true
EXECUTION_CONTROLLER_READY=true
ALLOWED_TARGETS 非空
EXECUTOR_IMAGE 使用不可变 digest
执行权限已授予
安全验收报告已登记
```

任一条件不满足：

- `/execute/preview` 可返回只读准备状态；
- `/execute` 返回 `FEATURE_DISABLED` 或 `EXECUTION_NOT_READY`；
- 页面不展示可点击执行按钮。

### 13.2 Controller API

内部接口建议：

```text
POST /internal/v1/runs
GET  /internal/v1/runs/{run_id}
POST /internal/v1/runs/{run_id}/cancel
GET  /internal/v1/readiness
```

`POST /runs` 只接受：

```text
run_id
input_path_id
input_sha256
output_path_id
resource_profile_id
egress_policy_id
timeout_seconds
```

禁止接受镜像名、命令、Host 路径、环境变量字典、网络模式、capability 或任意容器参数。

### 13.3 固定执行模板

默认建议值需要在安全压测后固化为配置：

| 项目 | 默认建议 |
| --- | --- |
| 用户 | 非 root 固定 UID/GID |
| 根文件系统 | 只读 |
| Linux capabilities | 全部 drop |
| `no-new-privileges` | 开启 |
| CPU | 1 core |
| 内存 | 512 MiB |
| PID | 64 |
| 临时空间 | 128 MiB tmpfs |
| 单用例超时 | 60 秒 |
| 单脚本超时 | 10 秒 |
| 整 Run 超时 | 30 分钟，可设更低项目值 |
| 重启策略 | never |
| 日志上限 | 10 MiB/Run，超出截断并标记 |

### 13.4 挂载

- `/run/input`：只读，只含已确认可执行用例和非敏感运行元数据。
- `/run/output`：当前 Run 独占可写目录。
- `/tmp`：独立 tmpfs。
- 不挂载源码、平台 Secret 目录、任务根目录、数据库卷或 Docker Socket。

### 13.5 Secret 注入

- Web 根据 `target_id` 请求当前 Run 所需的短期 Credential。
- Controller 使用内存或一次性 secret file 注入。
- 执行输入 JSON 只保存变量占位符，不保存 Secret。
- 容器退出后销毁临时 Secret。
- 报告和日志脱敏器覆盖 Authorization、Cookie、Token、签名 URL 和配置的敏感字段。

### 13.6 网络隔离

执行容器不能直接连接目标网络，只连接 Egress Proxy：

1. 目标由平台登记为 `target_id`，包含 scheme、hostname、port 和可选 path 前缀。
2. Proxy 解析 DNS 后拒绝 loopback、link-local、multicast、metadata 和未批准私网地址。
3. 每次连接和重定向都重新校验 scheme、Host、port 和解析 IP。
4. 禁止用户凭请求 Header 覆盖 Host。
5. 默认禁止跨 Host 重定向。
6. Proxy 记录脱敏目标、状态码和耗时，不记录 Secret。

必须覆盖 SSRF、DNS rebinding、IPv6、重定向逃逸和混淆 IP 测试。

### 13.7 Run 生命周期

```text
用户确认
→ Web 创建 run.json
→ RunManager 校验输入与目标
→ Controller 创建容器
→ 容器执行并写增量事件
→ Controller 监控超时/取消/退出
→ Web 收集结果并脱敏
→ 生成报告
→ 销毁容器和临时 Secret
→ 保留受控输出
```

### 13.8 失败恢复

- Controller 在 `provisioning` 失败时返回 `EXECUTION_PROVISION_FAILED`。
- Web 或 Controller 重启后，通过 run_id 对账；孤儿容器必须终止。
- 容器退出但结果缺失时标记 `EXECUTION_RESULT_MISSING`。
- 取消终止容器，等待最多 10 秒后强制停止。
- Run 不自动重新执行；用户重试生成新 Run。

---

## 14. 执行确认与结果设计

### 14.1 执行预览

```text
POST /api-test-agent/api/v1/tasks/{task_id}/execute/preview
```

返回：

- 可执行用例版本和数量；
- 目标 ID、环境、脱敏 Base URL；
- GET/写方法数量；
- 高风险和禁用用例数量；
- setup/teardown 脚本数量；
- 访问 Host；
- 配置 Release；
- Controller readiness 和阻断原因；
- 确认摘要 SHA。

### 14.2 执行确认

`POST /execute` 必须携带预览生成的 `confirmation_sha256`。任何用例、目标、配置 Release 或风险摘要变化都会导致 SHA 失效，需要重新确认。

### 14.3 执行结果

报告生成顺序：

1. 校验容器结果 Schema。
2. 对请求、响应和异常再次脱敏。
3. 计算总数和通过率。
4. 分类失败并生成错误签名。
5. 评价响应耗时。
6. 保存 `execution-result.json`。
7. 生成 `report.json`。
8. 注册产物并更新 Run 终态。

### 14.4 失败分类

首期规则优先，AI 仅输出辅助分析：

| 分类 | 示例 |
| --- | --- |
| `product_defect_candidate` | 断言失败、契约响应不一致、稳定 5xx |
| `environment_blocked` | DNS、连接拒绝、目标维护 |
| `test_data_issue` | 变量缺失、前置数据不存在 |
| `test_case_issue` | 脚本错误、断言配置错误 |
| `performance_candidate` | 满足慢响应候选规则 |
| `unknown` | 无法可靠分类 |

人工修正只生成报告分类修订版本，不改写原 CaseResult。

---

## 15. 慢响应候选设计

### 15.1 阈值选择

```text
接口文档 SLA
  > 项目/环境 slow_response_threshold_ms
  > 系统默认 3000ms
```

每条评价保存 `threshold_ms` 和 `threshold_source=document/project/environment/default`。

### 15.2 判断规则

- 单次 `duration_ms > threshold_ms`：`warning`。
- 用户点击“验证慢响应”后，系统创建包含同一用例的 3 个独立 ExecutionRun 或一个受控验证组；每次均使用相同环境和数据前提。
- 三次都超限：`performance_candidate`，允许生成本地性能 Bug 草稿。
- 任一次未超限：保持波动警告，不生成性能 Bug 草稿。
- 超时、连接错误或环境阻塞不计为慢响应样本。

### 15.3 不支持范围

- 并发用户和负载模型；
- 吞吐量；
- P95/P99；
- 长时间稳定性；
- 将测试环境数据直接推断为生产 SLA。

---

## 16. 本地 Bug 草稿设计

### 16.1 生成条件

- 用户从一个失败聚类或一个/多个 CaseResult 主动选择“生成 Bug 草稿”。
- 系统预填字段，但不自动认定为正式缺陷。
- 环境阻塞、数据问题和用例问题默认提示“不建议作为接口 Bug”，用户仍可生成草稿但需填写原因。

### 16.2 API

```text
POST /api-test-agent/api/v1/runs/{run_id}/defect-drafts
GET  /api-test-agent/api/v1/defect-drafts/{draft_id}
PUT  /api-test-agent/api/v1/defect-drafts/{draft_id}
GET  /api-test-agent/api/v1/defect-drafts/{draft_id}/download?format=json
GET  /api-test-agent/api/v1/defect-drafts/{draft_id}/download?format=markdown
```

没有 `submit` API。

### 16.3 编辑与版本

- `PUT` 请求包含 `base_version`。
- 版本冲突返回 409。
- 每次保存生成新文件和新 SHA。
- AI 分析、人工编辑字段和原始证据分开保存。
- 下载时生成确定性 JSON/Markdown，不加入外部链接或未脱敏正文。

### 16.4 权限

- 创建/编辑：`api-test-agent.defect.create` + Run 所有权。
- 查看/下载：`tool.result.view` + Run 所有权或 `task.view.all`。
- 不引入外部系统凭证。

---

## 17. Web 页面与交互设计

### 17.1 首页

- 配置就绪状态：LLM、解析、执行 Controller、目标数量。
- 新建任务：项目、模块、文档、操作类型、目标环境。
- 执行未就绪时，允许生成但明确说明不能执行。
- 最近任务：操作、阶段、状态、耗时、结果和下一步。
- 状态和内部阶段全部映射为中文产品文案。

### 17.2 任务详情

固定顺序：

1. 状态、阶段、下一步。
2. 流程步骤条。
3. 可操作错误与建议。
4. Review/确认区域。
5. 统计与覆盖矩阵。
6. 阶段产物。
7. 日志。
8. 模型、Prompt、Release 和版本。
9. 时间线。

空摘要不渲染空容器。

### 17.3 Run 详情

- 首屏：状态、环境、目标、耗时、总数和通过率。
- 失败聚类置于日志之前。
- Case 表支持状态、接口、分类和风险筛选。
- 请求与响应默认折叠，显式标记已脱敏。
- 操作：重试单条、重试失败项、生成本地 Bug 草稿。

### 17.4 可访问性

- 使用语义化表格或真实 list，不仅设置 ARIA role。
- 图标按钮有可访问名称。
- 状态使用文本与图形，不只使用颜色。
- Review 字段错误与控件关联。
- 键盘可完成筛选、Review、确认和下载。
- 焦点可见，日志区域不会强制抢焦点。
- 尊重 `prefers-reduced-motion`。

---

## 18. 配置设计

### 18.1 新增普通配置

| 配置 | 默认值 | 生效方式 |
| --- | --- | --- |
| `CONTRACT_QUALITY_MIN_SCORE` | `0.90` | next_task |
| `COVERAGE_MAX_ROUNDS` | `3` | next_task |
| `CASE_GENERATION_CONCURRENCY` | `3` | next_task |
| `API_EXECUTION_ENABLED` | `false` | deployment/release gate |
| `ALLOWED_TARGETS` | `[]` | next_run |
| `EXECUTION_CONTROLLER_URL` | 空 | restart |
| `EXECUTION_RESOURCE_PROFILE` | `api-default-v1` | next_run |
| `EXECUTION_TASK_TIMEOUT_SECONDS` | `1800` | next_run |
| `EXECUTION_CASE_TIMEOUT_SECONDS` | `60` | next_run |
| `EXECUTION_SCRIPT_TIMEOUT_SECONDS` | `10` | next_run |
| `SLOW_RESPONSE_THRESHOLD_MS` | `3000` | next_run |
| `SLOW_RESPONSE_CONFIRM_RUNS` | `3` | next_run |

### 18.2 Secret

| Secret | 归属 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 生成 Runner | 沿用现有配置 |
| 目标 Credential | target_id/environment | 仅执行 Run 临时注入 |
| Controller Service Token | API Web ↔ Controller | 独立轮换，不进入执行容器 |

不增加缺陷 Provider Secret。

### 18.3 目标登记结构

```json
{
  "target_id": "dev-gateway",
  "environment": "dev",
  "scheme": "https",
  "hostname": "gateway.dev.example.internal",
  "port": 443,
  "path_prefixes": ["/gateway/"],
  "credential_id": "cred_dev_gateway",
  "enabled": true
}
```

浏览器不能提交任意 Base URL；只提交 `target_id`。

---

## 19. 权限与审计

### 19.1 权限迁移

保留已有 `api-test-agent.execute`，新增：

```text
api-test-agent.contract.review
api-test-agent.case.review
api-test-agent.defect.create
```

不新增 `defect.submit` 或 `regression.publish`。

### 19.2 审计动作

```text
agent.contract.review
agent.contract.reparse
agent.case.review
agent.execution.preview
agent.execution.confirm
agent.execution.start
agent.execution.cancel
agent.execution.complete
agent.run.retry
agent.defect_draft.create
agent.defect_draft.update
agent.defect_draft.download
```

审计 metadata 不保存文档正文、请求体、响应体、Secret 或 Bug 草稿全文。

---

## 20. 文件级实施方案

以下是计划修改或新增的文件；实际编码前仍应按里程碑确认具体文件创建范围。

### 20.1 P0-A 可信解析与契约 Review

修改：

| 文件 | 修改内容 |
| --- | --- |
| `services/api_agent/app.py` | 注册 API 专属 Blueprint、阶段 Runner 和契约 Review |
| `services/api_agent/runner.py` | 改为阶段参数驱动，增加预检、契约解析和阶段提交 |
| `services/api_agent/adapter.py` | 兼容新契约和质量报告产物 |
| `services/common/task_models.py` | 保持公共模型兼容，API 扩展转入专用模型 |
| `services/common/errors.py` | 保留第三方模型通用错误映射 |
| `services/common/static/agent-workbench.js` | 公共轮询只保留通用逻辑，API 交互移入专属脚本 |
| 平台权限 Alembic 迁移 | 新增 contract/case/defect 权限并授予合适角色 |

新增：

```text
agents/api_test/contracts/schema.py
agents/api_test/contracts/format_detector.py
agents/api_test/contracts/openapi_parser.py
agents/api_test/contracts/unstructured_parser.py
agents/api_test/contracts/normalizer.py
agents/api_test/contracts/evidence.py
agents/api_test/contracts/quality_gate.py
services/api_agent/blueprint.py
services/api_agent/models.py
services/api_agent/review_service.py
services/api_agent/stage_artifacts.py
services/api_agent/errors.py
services/api_agent/templates/contract_review.html
services/api_agent/static/api-agent.js
```

### 20.2 P0-B 用例 Review 与结果模型

修改：

```text
agents/api_test/workflows/api_basecase_workflow.py
agents/api_test/workflows/api_case_generator_main_workflow.py
agents/api_test/workflows/api_run_case_wrokflow.py
services/api_agent/runner.py
services/api_agent/blueprint.py
```

新增：

```text
agents/api_test/cases/schema.py
agents/api_test/cases/coverage_rules.py
agents/api_test/cases/coverage_matrix.py
agents/api_test/cases/executable_validator.py
agents/api_test/cases/script_policy.py
services/api_agent/case_review_service.py
services/api_agent/templates/case_review.html
services/api_agent/templates/defect_draft.html
services/api_agent/defect_draft_service.py
```

### 20.3 P0-C 独立容器执行

新增独立服务目录的必要性：用户已明确要求每 Run 独立受限容器，现有 Web 服务不能安全承载容器控制职责。该目录需在 P0-C 开始前单独确认创建。

建议结构：

```text
AItestcase_Agents/services/execution_controller/
├── app.py
├── config.py
├── auth.py
├── controller.py
├── runtime_adapter.py
├── policies.py
├── reconciliation.py
└── tests/

AItestcase_Agents/executor/
├── Dockerfile
├── entrypoint.py
├── schema.py
├── runner.py
├── http_transport.py
├── assertions.py
├── scripts.py
└── redaction.py
```

API 服务侧新增：

```text
services/api_agent/run_manager.py
services/api_agent/run_store.py
services/api_agent/execution_client.py
services/api_agent/report_service.py
services/api_agent/performance_service.py
services/api_agent/templates/execution_confirm.html
services/api_agent/templates/run_detail.html
```

部署侧修改：

```text
test-platform/docker-compose.yml
test-platform/nginx/nginx.conf（不暴露 Controller）
test-platform/backend 配置白名单和权限迁移
test-platform/.env.example
```

### 20.4 不允许的修改

- 不把 Docker Socket 挂到 `api-test-agent` Web 容器。
- 不允许执行容器挂载整个任务根目录。
- 不把外部缺陷 Provider 加入当前设计。
- 不修改 `api-autotest/data/`。
- 不新增 Postman、gRPC、WebSocket、GraphQL 解析或执行分支。
- 不为此任务重构功能测试智能体整体架构。

---

## 21. 数据迁移与兼容

### 21.1 平台数据库

预计只需要：

- 新权限定义；
- API 智能体普通配置白名单；
- Controller 服务身份或内部凭证配置；
- 可选的目标登记配置模型，如果现有配置 JSON 不能满足结构化校验。

任务、Run 和 Bug 草稿首期仍保存在 API 智能体任务目录，不迁入平台 PostgreSQL。

### 21.2 任务数据

- 不迁移旧任务。
- V1 页面继续展示旧任务原有产物和日志。
- V2 页面根据 `schema_version` 选择组件。
- 新版本回滚后，旧代码可能无法理解 V2 状态，因此回滚时先停止新任务，并保留只读数据；需要提供降级只读页或导出工具，不能直接改写 V2 为 V1。

### 21.3 CLI

- 旧 `APITestCaseExecutor.run()` 暂时保留，避免破坏现有 CLI。
- 平台路径不调用旧直接执行。
- P0-C 后可新增显式 `--controller` 平台兼容入口，但不改变旧 CLI 默认行为。
- 旧 CLI 中硬编码示例密码和 URL 应另行清理，不能作为平台配置来源。

---

## 22. 测试策略

### 22.1 单元测试

#### 文档解析

- OpenAPI 2.0/3.x method/path/参数/响应/鉴权解析。
- 本地 `$ref`、循环 `$ref` 和远程 `$ref` 拒绝。
- JSON/YAML 语法、嵌套、别名和资源限制。
- Postman、AsyncAPI、GraphQL/gRPC 特征拒绝。
- contract_id 稳定性。
- Evidence JSON Pointer 正确性。

#### 质量门禁

- 无证据事实移动到建议。
- 关键冲突阻断。
- 人工 override 证据和版本记录。
- 评分与硬门禁互不替代。

#### 用例

- 覆盖规则和矩阵。
- 最多 3 轮及提前终止。
- 去重和缺口接受。
- 可执行用例 Schema、变量、拓扑和 AST 策略。

#### Run 与草稿

- 状态迁移和非法迁移。
- 预览 SHA 失效。
- Run 重试不覆盖原结果。
- 慢响应单次告警和 3 次确认。
- Bug 草稿编辑版本冲突、脱敏和确定性下载。

### 22.2 服务契约测试

- 身份、权限、所有权、CSRF。
- Review base_version 409。
- 阶段产物失败保留。
- 旧 schema_version 兼容。
- API 执行关闭时始终拒绝。
- Controller 未就绪时不创建 Run 容器。

### 22.3 执行安全测试

必须包含：

- 容器非 root、只读根、capabilities、PID/CPU/内存限制。
- 无 Docker Socket、无平台 Token、无其他任务挂载。
- 未允许 Host/IP/port/path 拒绝。
- IPv4/IPv6 loopback、link-local、metadata 地址拒绝。
- DNS rebinding 和跨 Host 重定向拒绝。
- 恶意 setup/teardown、进程创建、文件访问和资源耗尽。
- 取消、超时、Controller/Web 重启和孤儿容器回收。
- 日志、报告、Bug 草稿全链路脱敏。

### 22.4 集成测试

使用本地受控 Mock 目标，不访问公网：

- 正常 2xx、业务错误、4xx、5xx。
- 响应 Schema 不一致。
- 前置接口变量提取。
- 轮询成功和超时。
- 写方法执行确认。
- 慢响应 3 次确认。
- 报告和 Bug 草稿生成。

### 22.5 浏览器验收

桌面视口至少覆盖 1280×800 和 1440×900：

- 新建任务的加载、错误、空态。
- 契约 Review、冲突和版本冲突。
- 用例 Review、高风险确认和覆盖缺口。
- 执行未就绪、预览、确认、运行、取消和终态。
- 报告筛选、请求响应展开、Bug 草稿编辑和下载。
- 键盘导航、焦点、对比度和非颜色状态提示。

### 22.6 回归测试

每个里程碑至少运行：

```bash
cd /Users/admin/Testproject/AItestcase_Agents
python3 -m pytest -q tests/services
python3 -m pytest -q tests/functional_test tests/requirement_decomposition

cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q

cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run
npm run build

cd /Users/admin/Testproject/test-platform
python3 -m unittest discover -s tests -v
docker compose config
docker compose exec -T platform-gateway nginx -t
```

P0-C 另加执行 Controller、Executor 镜像和安全门禁测试。

---

## 23. 实施计划

工期为单工程团队的相对估算，不构成排期承诺；安全评审和基础设施等待时间不计入开发人日。

### 23.1 里程碑 M0：Schema 与黄金样例（2～3 人日）

任务：

1. 固化 ApiContract、BaseTestCase、ExecutableCase、Run、CaseResult、DefectDraft Schema。
2. 建立最小黄金文档集。
3. 定义稳定错误码和状态迁移表。
4. 评审阶段目录和版本规则。

完成标准：Schema、示例和状态机评审通过；尚不修改线上流程。

### 23.2 里程碑 M1：文档预检与确定性解析（4～6 人日）

任务：

1. 格式探测和拒绝范围。
2. OpenAPI/Swagger 确定性解析。
3. Evidence 和规范化。
4. 阶段产物提交器。
5. 解析单元和契约测试。

完成标准：黄金 OpenAPI method/path 100% 正确；解析产物可在后续失败时下载。

### 23.3 里程碑 M2：LLM 契约拆解与质量门禁（5～7 人日）

任务：

1. 非结构化文档切片。
2. 契约事实和建议抽取。
3. Evidence、Grounding、防幻觉。
4. 质量报告和 confirmed_candidate。
5. 模型错误分类和有限重试。

完成标准：无证据关键事实不进入 confirmed_candidate；模型额度不足显示明确建议且保留已完成产物。

### 23.4 里程碑 M3：契约 Review（4～6 人日）

任务：

1. Review API、版本冲突和审计。
2. 三栏 Review 页面。
3. 批量确认、修改、忽略、退回。
4. 新权限迁移。

完成标准：至少一个 confirmed 接口才能继续；所有修改可追踪和回滚到旧版本。

### 23.5 里程碑 M4：覆盖矩阵与用例 Review（6～9 人日）

任务：

1. 确定性覆盖规则。
2. 结构化矩阵和 LLM 补齐。
3. 最多 3 轮和 partial_success。
4. 用例 Review 页面和版本。
5. 高风险逐条确认。

完成标准：不存在无限循环；缺口、决策来源和关联用例全部可见。

### 23.6 里程碑 M5：可执行用例与静态验证（4～6 人日）

任务：

1. ExecutableCase Schema。
2. 变量、依赖、断言和 AST 策略。
3. 失败阶段重试。
4. 执行预览数据准备，但执行保持关闭。

完成标准：无效或高风险未确认用例不能进入执行预览。

### 23.7 安全检查点 S1：P0-C 开发授权

在开发执行 Controller 前必须完成：

- 威胁模型；
- 容器运行时方案；
- Egress Proxy 和目标登记方案；
- Credential 最小注入方案；
- 基础设施负责人和安全负责人书面结论；
- 新目录和部署组件创建授权。

未通过时，系统停留在“可信生成 + Review”，`API_EXECUTION_ENABLED=false`。

### 23.8 里程碑 M6：Controller 与 Executor（8～12 人日）

任务：

1. Controller 窄 API 和内部鉴权。
2. 固定 digest Executor 镜像。
3. 单 Run 容器、资源和挂载策略。
4. Egress Proxy 策略。
5. RunManager、取消、超时和对账。
6. 安全自动化测试。

完成标准：执行容器无法访问平台敏感资源或未允许网络；一个 Run 完成后容器被销毁。

### 23.9 里程碑 M7：执行确认、报告和慢响应（6～8 人日）

任务：

1. 执行预览和确认 SHA。
2. Run 页面、实时轮询和取消。
3. 结果 Schema、脱敏和报告。
4. 失败分类和重试。
5. SLA/3000ms/3 次慢响应规则。

完成标准：真实请求只能在权限、目标、确认和 Controller 门禁全部通过后发送。

### 23.10 里程碑 M8：本地 Bug 草稿（3～5 人日）

任务：

1. 草稿生成规则和字段预填。
2. 编辑、版本、冲突和审计。
3. JSON/Markdown 下载。
4. 页面与可访问性验证。

完成标准：系统没有外部提交能力；下载内容完整脱敏且可用于测试人员手工提 Bug。

### 23.11 P1/P2 后续实施

P1：文档差异、请求调试工作台、失败聚类优化。  
P2：黄金评测看板、缓存与 Token 预算、变更影响与重测推荐、指标观测。

稳定资产发布不在上述计划中，后续只从需求池 `POOL-019` 重新立项。

---

## 24. 发布与灰度

### 24.1 P0-A/P0-B

- 通过配置仅对管理员或试点角色开放 V2 新建入口。
- V1 任务详情保持可访问。
- 每个阶段可独立关闭新入口，不删除 V2 数据。
- 先使用 Mock LLM 和黄金样例，再使用真实 dev 模型。

### 24.2 P0-C

1. Controller 与 Executor 先在隔离 dev 网络部署。
2. `API_EXECUTION_ENABLED=false` 完成 readiness 和安全测试。
3. 只登记一个无生产数据的 Mock 目标。
4. 安全验收通过后，为指定试点角色和指定目标开启。
5. 观察取消、超时、孤儿容器、脱敏和资源使用。
6. 再评审是否增加其他非生产目标。

生产目标默认不进入首轮灰度。

---

## 25. 回滚方案

### 25.1 应用回滚

- 关闭 V2 新建入口。
- 设置 `API_EXECUTION_ENABLED=false`。
- 停止 Controller 接受新 Run，等待或取消现有 Run。
- 保留任务、Run 和草稿目录，只读访问。
- 回滚 API Agent Web/Runner 镜像。

### 25.2 Controller 回滚

- 先禁止新 Run。
- 对账并终止所有活动容器。
- 撤销 Controller 服务凭证。
- 保留脱敏输出和审计。
- 不删除目标 Credential 或任务数据，除非经过单独数据删除确认。

### 25.3 数据库迁移回滚

- 权限和配置迁移应提供 downgrade。
- downgrade 前确认没有依赖新权限的活动 Review 或 Run。
- 任务文件 Schema 不随 Alembic downgrade 删除。

---

## 26. 上线门禁

### 26.1 可信生成门禁

- [ ] Schema 和黄金样例评审通过。
- [ ] OpenAPI method/path 准确率 100%。
- [ ] Evidence、冲突和未解决项可见。
- [ ] 阶段失败保留上游产物。
- [ ] Review 版本冲突和权限测试通过。
- [ ] 覆盖补齐最多 3 轮。

### 26.2 真实执行门禁

- [ ] 一个 Run 一个独立短生命周期容器。
- [ ] Web 容器无 Docker Socket 或等价宿主权限。
- [ ] 执行容器非 root、只读根、无 capability。
- [ ] CPU、内存、PID、磁盘和三级超时生效。
- [ ] 只挂载当前 Run 输入和输出。
- [ ] Egress Proxy 的 SSRF、DNS 和重定向测试通过。
- [ ] 未登记目标请求数为 0。
- [ ] Secret、请求、响应、日志、报告和草稿脱敏通过。
- [ ] 取消和孤儿容器回收通过。
- [ ] 独立安全评审书面通过。

### 26.3 本地 Bug 草稿门禁

- [ ] 生成、编辑和版本冲突测试通过。
- [ ] JSON/Markdown 可下载。
- [ ] 不存在外部提交接口、按钮和 Provider Secret。
- [ ] 草稿失败不影响报告终态。
- [ ] 慢响应只有连续 3 次超限才允许生成性能草稿。

---

## 27. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| OpenAPI 方言和 `$ref` 复杂 | 解析不完整 | 首期只支持本地引用，未支持项显式进入 unresolved |
| LLM 幻觉 | 契约或用例错误 | Evidence、Grounding、硬门禁和人工 Review |
| 模型限流 | 任务失败或耗时长 | 确定性解析、有限重试、阶段缓存和并发上限 |
| 动态脚本逃逸 | 平台和内网风险 | AST 提前阻断 + 单 Run 容器 + Egress Proxy + 最小 Secret |
| Controller 权限过大 | 宿主机风险 | 窄 API、固定模板、内部鉴权、独立审计和安全评审 |
| 状态机复杂化 | 终态覆盖或卡死 | 显式合法迁移、锁内提交、对账任务和契约测试 |
| 文件版本增长 | 磁盘压力 | 沿用保留策略、阶段产物索引和容量告警 |
| 测试环境波动 | 误报慢接口 | 单次只告警、3 次确认、保存阈值来源 |
| Bug 草稿被误当正式结论 | 错误提单 | 明确“草稿”状态、人工编辑和本地下载，不自动提交 |

---

## 28. 开发完成定义

一个里程碑只有同时满足以下条件才算完成：

1. 对应 PRD 条目有代码、测试和页面或 API 证据。
2. 只修改该里程碑必要文件，不顺便重构无关模块。
3. 新增代码包含符合项目规范的中文功能、参数、返回和异常说明。
4. 单元、契约、集成、浏览器和相关回归测试通过。
5. 配置、权限、审计、数据保留和回滚同步更新。
6. 错误状态提供用户可执行的下一步，而非只显示内部错误码。
7. 文档、契约、用例、Run、报告和草稿版本可追溯。
8. P0-C 的安全专项门禁全部通过后才允许真实执行。

当前文档交付不授权直接开始 P0-C 基础设施变更；进入编码时应按 M0→M8 顺序逐里程碑实施和验收。
