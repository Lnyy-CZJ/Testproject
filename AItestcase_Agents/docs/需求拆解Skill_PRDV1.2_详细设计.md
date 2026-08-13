# 需求拆解 Skill PRD V1.2 详细设计文档

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 文档名称 | 需求拆解 Skill PRD V1.2 详细设计文档 |
| 来源 PRD | `PRD/需求拆解Skill_PRDV1.2.md` |
| 当前状态 | 待用户 Review |
| 设计目标 | 将 PRD 转化为可分步开发、可验证、可追溯的详细实现设计 |
| 开发状态 | 未开始开发 |

## 2. 设计目标

本设计面向一个轻量级“需求拆解 Skill”。系统接收原始需求文档，输出 AI 可读、可追溯、可测试的结构化 Requirement 模型，并为后续测试点生成系统提供稳定的 `test_seed`。

核心目标如下：

1. 将自然语言需求拆解为单一、可验证、可测试的 Requirement。
2. 使用 LLM 辅助识别业务语义、测试对象、约束、状态、权限、风险和验收标准。
3. 使用规则、Schema、字段级 evidence、Grounding Check 约束 LLM 输出。
4. 防止 LLM 编造、过度推断或曲解原始需求。
5. 将原文明确支持的需求事实与 AI 推断出的测试设计建议分离。
6. 输出结构化 JSON、Markdown、test_seed、质量报告和 LLM 追踪信息。
7. 在 LLM 不可用时降级为规则模式，保证系统仍可给出可审查的草稿输出。

## 3. 非目标

本期不实现以下能力：

1. 不直接生成完整测试用例。
2. 不建设 Web 平台或多人审批流。
3. 不建设复杂知识图谱数据库。
4. 不做完整需求生命周期管理。
5. 不允许 LLM 自动确认冲突需求。
6. 不允许 LLM 绕过 Schema 和规则校验直接输出最终可信结果。
7. 不允许无原文证据的 AI 推断进入正式需求事实。

## 4. 总体架构

系统采用流水线架构：

```text
文档输入
  -> 文档解析
  -> 文档切片
  -> LLM 语义拆解
  -> 字段级证据绑定
  -> Grounding Check
  -> Facts/Suggestions 分层
  -> 规则校验
  -> 状态判定
  -> JSON / Markdown / test_seed 输出
```

设计原则：

1. LLM 负责语义理解，不负责最终可信判断。
2. 规则负责结构约束和准入门槛。
3. evidence 负责证明字段来自原文。
4. Grounding Check 负责发现无依据或曲解内容。
5. 人工确认负责处理高风险、不确定和冲突内容。

## 5. 目标目录结构

```text
requirement_decomposition/
  __init__.py
  pipeline.py
  parser/
    __init__.py
    document_parser.py
  chunker/
    __init__.py
    section_chunker.py
  models/
    __init__.py
    schema.py
  llm/
    __init__.py
    llm_client.py
    prompt_loader.py
    semantic_analyzer.py
    requirement_splitter.py
    test_object_extractor.py
    constraint_extractor.py
    state_model_extractor.py
    permission_extractor.py
    risk_tag_extractor.py
    gwt_generator.py
    evidence_binder.py
    grounding_checker.py
    self_checker.py
  validator/
    __init__.py
    schema_validator.py
    quality_validator.py
    evidence_validator.py
    confirmed_gate_validator.py
  generator/
    __init__.py
    json_generator.py
    markdown_generator.py
    test_seed_generator.py
  config/
    __init__.py
    loader.py
prompts/
  semantic_analysis.md
  requirement_split.md
  test_object_extract.md
  constraint_extract.md
  state_model_extract.md
  risk_tag_extract.md
  gwt_generate.md
  evidence_bind.md
  grounding_check.md
  self_check.md
```

## 6. 模块职责设计

### 6.1 parser/document_parser.py

负责读取原始需求文档。

本期只要求支持 Markdown：

1. 读取文件内容。
2. 提取标题、段落、列表、代码块。
3. 保留原文内容。
4. 生成 source 基础信息。

输出核心结构：

```json
{
  "source_id": "SRC-001",
  "source_type": "markdown",
  "path": "docs/prd.md",
  "content": "...",
  "trust_level": "high"
}
```

### 6.2 chunker/section_chunker.py

负责将文档切为 section。

切片规则：

1. 优先按 Markdown 标题层级切分。
2. 标题下正文为空时，不生成有效 section。
3. section 必须保留 `section_id`、`title`、`content`、`source_id`。
4. section 的 `quote` 必须来自原文，不允许改写。
5. 过长 section 可按段落进一步切分，但必须保留父标题路径。

输出示例：

```json
{
  "section_id": "SEC-001",
  "source_id": "SRC-001",
  "title": "取消订单",
  "heading_path": ["订单", "取消订单"],
  "content": "用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。"
}
```

### 6.3 llm/prompt_loader.py

负责加载 prompt 模板。

要求：

1. 每个 prompt 文件必须包含 `prompt_name` 和 `version`。
2. Prompt 版本参与 `llm_metadata` 和 `llm_trace` 输出。
3. 找不到 prompt 时，返回明确错误，不能静默使用空 prompt。

### 6.4 llm/llm_client.py

负责封装 LLM 调用。

要求：

1. 支持配置模型、温度、最大 token、base_url、api_key_env。
2. 所有 LLM 任务必须要求输出 JSON。
3. 记录调用成功、失败、耗时、模型、prompt_version。
4. LLM 失败时向 pipeline 返回可降级错误，不直接终止全流程。

### 6.5 LLM 任务模块

LLM 任务按职责拆分，不将所有字段放在一个大 prompt 中一次生成。

模块包括：

1. `semantic_analyzer.py`：识别业务意图、实体、动作、规则。
2. `requirement_splitter.py`：将复合需求拆解为原子 Requirement 候选项。
3. `test_object_extractor.py`：提取字段、按钮、状态、角色、接口、数据对象等测试对象。
4. `constraint_extractor.py`：提取 required、format、length、range、enum、state、permission、business_rule 等约束。
5. `state_model_extractor.py`：提取状态集合、合法流转、非法流转。
6. `permission_extractor.py`：提取角色、身份、权限边界。
7. `risk_tag_extractor.py`：从固定风险枚举中选择风险标签。
8. `gwt_generator.py`：生成 Given / When / Then 验收标准。
9. `evidence_binder.py`：为关键字段绑定原文 quote。
10. `grounding_checker.py`：检查字段是否有原文依据。
11. `self_checker.py`：检查遗漏、合并错误、无依据推断和分层错误。

## 7. 核心数据模型

### 7.1 顶层输出模型

```json
{
  "project": {},
  "sources": [],
  "domains": [],
  "modules": [],
  "features": [],
  "requirements": [],
  "llm_trace": {},
  "quality_report": {},
  "version": {}
}
```

### 7.2 Requirement 模型

```json
{
  "requirement_id": "REQ-ORDER-001",
  "title": "待支付订单允许取消",
  "domain": "订单",
  "module": "订单状态管理",
  "feature": "取消订单",
  "description": "订单状态为待支付时，订单创建人可以取消订单。",
  "source_trace": {},
  "requirement_facts": {
    "test_objects": [],
    "preconditions": [],
    "trigger": "",
    "constraints": [],
    "state_model": {},
    "permissions": [],
    "main_flow": [],
    "exception_flows": [],
    "acceptance_criteria": []
  },
  "test_design_suggestions": {
    "risk_tags": [],
    "test_generation_hints": [],
    "negative_suggestions": [],
    "boundary_suggestions": []
  },
  "field_evidence": [],
  "grounding_check": {},
  "unresolved": [],
  "ambiguity_notes": [],
  "conflict_items": [],
  "llm_metadata": {},
  "llm_self_check": {},
  "status": "draft"
}
```

### 7.3 Source Trace

```json
{
  "source_id": "SRC-001",
  "section_id": "SEC-001",
  "quote": "用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。"
}
```

### 7.4 Field Evidence

```json
{
  "field": "constraints",
  "value": "订单状态必须为待支付",
  "evidence": {
    "source_id": "SRC-001",
    "section_id": "SEC-001",
    "quote": "用户可以取消待支付订单"
  },
  "evidence_type": "explicit",
  "confidence": 0.91
}
```

### 7.5 Evidence Type

| evidence_type | 含义 | 是否可进入 requirement_facts |
|---|---|---|
| explicit | 原文明确说明 | 是 |
| inferred | LLM 基于上下文或测试经验推断 | 否 |
| missing | 原文缺失，无法确认 | 否 |
| conflict | 多处原文冲突 | 否 |

## 8. Facts 与 Suggestions 分层规则

`requirement_facts` 只保存原文明确支持的事实。

允许进入 `requirement_facts` 的内容：

1. evidence_type 为 `explicit`。
2. quote 能从原始 section 中匹配。
3. Grounding Check 未标记为 unsupported。
4. Schema 和字段规则校验通过。

`test_design_suggestions` 保存测试设计建议。

进入 suggestions 的内容：

1. evidence_type 为 `inferred`。
2. Grounding Check 标记为 unsupported 但具有测试价值。
3. 风险、边界、异常、负向测试方向等非需求事实内容。

处理硬规则：

1. 无证据内容不得进入 `requirement_facts`。
2. unsupported 内容不直接删除，应移动到 suggestions 并记录 issue。
3. conflict 内容不得自动裁决，应进入 `conflict_items`。
4. missing 内容进入 `unresolved`。

## 9. Grounding Check 设计

Grounding Check 负责检查每个关键字段是否有原文依据。

检查对象：

1. Requirement title。
2. Requirement description。
3. test_objects。
4. constraints。
5. state_model。
6. permissions。
7. acceptance_criteria。
8. requirement_facts。

输出示例：

```json
{
  "passed": false,
  "unsupported_items": [
    {
      "field": "risk_tags",
      "value": "并发",
      "reason": "原文未提到重复提交、并发操作或锁控制",
      "action": "move_to_test_design_suggestions"
    }
  ]
}
```

处理规则：

1. unsupported_items 不直接删除。
2. 可作为测试建议的内容移动到 `test_design_suggestions`。
3. unsupported_items 不允许作为 confirmed Requirement 的事实字段。
4. Grounding Check 未通过时，Requirement 状态不能为 `confirmed`。

## 10. 冲突与不确定项设计

### 10.1 unresolved

用于记录原文缺失但影响测试设计的信息。

示例：

```json
{
  "field": "output_result",
  "reason": "原文未说明取消成功后的提示文案"
}
```

### 10.2 ambiguity_notes

用于记录存在多种理解但未形成直接冲突的内容。

示例：

```json
{
  "field": "用户身份",
  "note": "原文提到非本人不可操作，但未说明管理员是否例外"
}
```

### 10.3 conflict_items

用于记录多处需求冲突。

示例：

```json
{
  "field": "取消订单规则",
  "source_a": "已支付订单不可取消",
  "source_b": "支付后 30 分钟内可以取消",
  "resolution": "pending_manual_confirm"
}
```

规则：

1. 存在 conflict_items 时，Requirement 默认状态为 `draft`。
2. LLM 不得自动解决冲突。
3. 人工确认后才允许进入 `confirmed`。

## 11. 状态流转设计

Requirement 状态包括：

| 状态 | 含义 | 是否进入测试点生成 |
|---|---|---|
| draft | 初步拆解，待确认 | 否 |
| confirmed_candidate | 高可信来源生成，且证据校验通过 | 可配置 |
| confirmed | 已确认 | 是 |
| changed | 需求变化，待复核 | 否 |
| deprecated | 已废弃 | 否 |

默认状态判定：

1. 来源可信度 high 且 Grounding Check 通过，进入 `confirmed_candidate`。
2. 来源可信度 high 但存在 unsupported_items，进入 `draft`。
3. 来源可信度 medium 或 low，进入 `draft`。
4. 存在 conflict_items，进入 `draft`。
5. 存在关键字段 unresolved，进入 `draft`。

confirmed 准入门槛：

1. source_trace 存在。
2. 关键字段具备字段级 evidence。
3. requirement_facts 中不存在 unsupported_items。
4. 不存在 conflict_items。
5. unresolved 不包含关键字段。
6. JSON Schema 校验通过。
7. Grounding Check 通过。
8. risk_tags 使用固定枚举。
9. state_model 合法性校验通过。
10. 人工确认或配置允许 confirmed_candidate 自动进入。

## 12. 校验设计

### 12.1 schema_validator.py

负责 JSON Schema / Pydantic 模型校验。

校验内容：

1. 顶层字段完整。
2. Requirement 必填字段完整。
3. 字段类型正确。
4. 枚举值合法。
5. 数组、对象、字符串字段格式正确。

### 12.2 evidence_validator.py

负责字段级证据校验。

校验内容：

1. 关键字段必须有 evidence。
2. evidence quote 必须来自原始 section。
3. explicit 字段必须有非空 quote。
4. inferred 字段不得进入 requirement_facts。
5. missing 字段必须进入 unresolved。
6. conflict 字段必须进入 conflict_items。

### 12.3 quality_validator.py

负责质量指标计算。

指标包括：

1. 字段完整率。
2. 来源可追溯率。
3. 字段级证据覆盖率。
4. 测试对象覆盖率。
5. 约束提取覆盖率。
6. GWT 覆盖率。
7. 风险标签覆盖率。
8. LLM 自检通过率。
9. Grounding Check 通过率。
10. Schema 校验通过率。
11. unsupported_facts 数量。

### 12.4 confirmed_gate_validator.py

负责 confirmed 准入判断。

输入：

1. Requirement。
2. 来源可信度。
3. quality_report。
4. 配置项。

输出：

1. 最终 status。
2. 阻断原因。
3. 是否允许进入 test_seed。

## 13. 风险标签设计

风险标签必须使用固定枚举：

```text
输入校验
权限
状态流转
金额
数据一致性
并发
幂等
异常流程
接口
兼容性
性能
安全
```

规则：

1. LLM 不允许输出枚举外风险标签。
2. 枚举外标签应进入 validator issue。
3. inferred 风险标签进入 `test_design_suggestions.risk_tags`。
4. 原文明确描述的风险规则可进入 `requirement_facts.constraints`。

## 14. State Model 校验设计

state_model 示例：

```json
{
  "entity": "订单",
  "states": ["待支付", "已支付", "已取消"],
  "transitions": [
    {
      "from": "待支付",
      "to": "已取消",
      "trigger": "取消订单",
      "valid": true
    },
    {
      "from": "已支付",
      "to": "已取消",
      "trigger": "取消订单",
      "valid": false
    }
  ]
}
```

校验规则：

1. `from` 和 `to` 必须存在于 `states`。
2. `trigger` 不允许为空。
3. 同一状态流转不能重复。
4. 非法流转必须有原文或业务规则依据。
5. 无依据的非法流转建议进入 `test_design_suggestions`，不能作为事实。

## 15. test_seed 生成设计

测试点生成系统优先消费 `test_seed`，而不是完整 Requirement。

输出结构：

```json
{
  "requirement_id": "REQ-ORDER-001",
  "module": "订单状态管理",
  "feature": "取消订单",
  "source_trace": {
    "source_id": "SRC-001",
    "section_id": "SEC-001"
  },
  "test_seed": {
    "objects": ["订单状态", "用户身份", "取消订单操作"],
    "conditions": ["订单状态=待支付", "用户=订单创建人"],
    "constraints": ["仅待支付订单允许取消", "仅订单创建人允许取消"],
    "state_transitions": ["待支付 -> 已取消"],
    "invalid_state_transitions": ["已支付 -> 已取消"],
    "permissions": ["订单创建人"],
    "risk_tags": ["状态流转", "权限", "幂等"],
    "expected_results": ["订单状态变为已取消"],
    "negative_suggestions": [
      "已支付订单取消失败",
      "非订单创建人取消失败",
      "重复点击取消订单"
    ]
  },
  "evidence_summary": {
    "fact_fields_grounded": true,
    "suggestions_include_inferred_items": true
  }
}
```

生成规则：

1. 默认只为 `confirmed` 生成 test_seed。
2. 配置允许时，可为 `confirmed_candidate` 生成 test_seed，但必须标记状态。
3. `risk_tags` 可包含 suggestions，但必须保留 inferred 标识或 evidence_summary。
4. `expected_results` 优先来自 GWT Then 或 output_result。
5. unresolved 和 conflict 内容不进入正式 conditions 或 constraints。

## 16. LLM 降级策略

当 LLM 不可用、超时、返回非 JSON、Schema 校验失败或配置关闭 LLM 时，系统进入规则模式。

规则模式能力：

| 能力 | 规则模式处理 |
|---|---|
| Requirement 拆解 | 按标题、列表、句号切分 |
| test_objects 提取 | 关键词、名词、字段名识别 |
| constraints 提取 | 规则词匹配，如必须、不可、只能、限制 |
| state_model 提取 | 状态关键词和状态转移词匹配 |
| permissions 提取 | 角色、身份、本人、管理员等词匹配 |
| risk_tags 识别 | 关键词映射固定枚举 |
| GWT 生成 | 使用模板生成 |
| evidence 绑定 | 基于字符串匹配 |
| Grounding Check | 基于 quote 包含关系和关键词匹配 |

降级输出必须包含：

```json
{
  "llm_metadata": {
    "llm_enabled": false,
    "fallback_mode": "rule_based"
  }
}
```

## 17. 配置设计

配置文件示例：

```yaml
project:
  project_id: "PROJECT-001"
  project_name: "订单系统"
  version: "1.0.0"

sources:
  - source_id: "SRC-001"
    source_type: "markdown"
    path: "docs/order_prd.md"
    trust_level: "high"

llm:
  enabled: true
  model: "gpt-4.1"
  temperature: 0.1
  max_tokens: 4096
  prompt_version: "v1.0"
  fallback_to_rule: true

decomposition:
  min_confidence: 0.7
  auto_resolve_conflicts: false
  split_mode: "semantic"
  require_source_trace: true
  require_field_evidence: true
  require_grounding_check: true
  require_llm_self_check: true
  separate_facts_and_suggestions: true

anti_hallucination:
  enabled: true
  require_explicit_evidence_for_facts: true
  allow_inferred_as_suggestions: true
  move_unsupported_items_to_suggestions: true
  fail_confirmed_on_unsupported_facts: true
  fail_confirmed_on_conflict: true

output:
  requirement_json:
    enabled: true
    path: "output/requirements.json"
  markdown:
    enabled: true
    path: "output/requirements_md"
  test_seed:
    enabled: true
    path: "output/test_seed.json"

quality_gate:
  min_quality_score: 0.9
  require_source_trace: true
  require_field_evidence: true
  require_test_objects: true
  require_constraints: true
  require_gwt: true
  require_schema_valid: true
  require_grounding_check_passed: true
  max_unsupported_facts: 0
```

## 18. 核心接口设计

对外入口：

```python
from requirement_decomposition import run_decomposition

result = run_decomposition(
    source_path="docs/prd.md",
    config_path="requirement_decomposition.yaml"
)
```

返回结构：

```json
{
  "success": true,
  "requirements": [],
  "test_seeds": [],
  "quality_report": {},
  "llm_trace": {
    "enabled": true,
    "model": "gpt-4.1",
    "prompt_version": "v1.0",
    "fallback_used": false
  },
  "grounding_summary": {
    "checked": true,
    "unsupported_facts": 0,
    "moved_to_suggestions": 3
  },
  "warnings": [],
  "errors": []
}
```

## 19. 质量报告设计

质量报告示例：

```json
{
  "quality_score": 0.91,
  "field_completeness": 0.97,
  "traceability_rate": 1.0,
  "field_evidence_rate": 0.96,
  "grounding_check_rate": 0.95,
  "schema_valid_rate": 1.0,
  "unsupported_facts": 0,
  "confirmed_requirements": 8,
  "draft_requirements": 2,
  "issues": [
    {
      "issue_type": "unsupported_inference",
      "requirement_id": "REQ-ORDER-001",
      "field": "risk_tags",
      "value": "并发",
      "action": "moved_to_test_design_suggestions",
      "reason": "原文未提到并发操作或重复提交"
    }
  ]
}
```

质量分计算建议：

1. 字段完整率权重 20%。
2. 来源可追溯率权重 20%。
3. 字段级证据覆盖率权重 20%。
4. Grounding Check 通过率权重 20%。
5. Schema 校验通过率权重 10%。
6. unsupported_facts 惩罚项 10%。

## 20. 错误处理设计

错误分为阻断错误和非阻断警告。

阻断错误：

1. 输入文件不存在。
2. 配置文件无法解析。
3. Markdown 内容为空。
4. 输出目录不可写。
5. Schema 定义加载失败。

非阻断警告：

1. LLM 调用失败后降级为规则模式。
2. 部分 section 未能拆解 Requirement。
3. 部分字段缺失 evidence。
4. risk_tags 存在枚举外值并被移除。
5. 存在 unresolved 或 conflict_items。

## 21. 测试策略

### 21.1 单元测试

覆盖模块：

1. Markdown 解析。
2. section 切片。
3. Prompt 加载。
4. LLM JSON 响应解析。
5. evidence quote 匹配。
6. Grounding Check 结果处理。
7. Facts/Suggestions 分层。
8. risk_tags 枚举校验。
9. state_model 合法性校验。
10. confirmed gate 判定。
11. test_seed 生成。

### 21.2 集成测试

准备示例 PRD：

1. 正常需求：有明确状态、权限、约束、预期结果。
2. 无证据推断：LLM 输出原文没有的内容。
3. 冲突需求：两处原文规则矛盾。
4. 缺失需求：原文没有说明关键预期结果。
5. LLM 不可用：验证规则降级模式。

### 21.3 验收测试

验收目标：

1. 能从 Markdown 生成完整 requirements JSON。
2. 能生成 Markdown 可读文件。
3. 能生成 test_seed。
4. 无证据事实不会进入 requirement_facts。
5. conflict_items 不会被自动确认。
6. confirmed Requirement 满足准入门槛。

## 22. 分阶段开发建议

### 阶段一：基础骨架与数据模型

目标：

1. 建立目录结构。
2. 实现配置加载。
3. 实现数据模型。
4. 实现 Markdown parser。
5. 实现 section chunker。
6. 实现 JSON / Markdown / test_seed 基础输出。

阶段验收：

1. 输入 Markdown 后能生成 section。
2. 能输出空壳 Requirement JSON。
3. 能写入目标 output 文件。

### 阶段二：LLM 拆解链路

目标：

1. 实现 LLM client。
2. 实现 prompt_loader。
3. 实现语义识别。
4. 实现 Requirement 拆解。
5. 实现 test_objects、constraints、state_model、permissions、risk_tags、GWT 提取。

阶段验收：

1. LLM 返回 JSON 可被解析。
2. 复合需求可拆成多个 Requirement。
3. 每个 Requirement 有基础 facts 和 suggestions。

### 阶段三：防幻觉机制

目标：

1. 实现字段级 evidence。
2. 实现 Grounding Check。
3. 实现 unsupported 降级到 suggestions。
4. 实现 unresolved、ambiguity、conflict 处理。
5. 实现 LLM self_check。

阶段验收：

1. 无证据内容不能进入 facts。
2. inferred 内容进入 suggestions。
3. conflict 内容保持 draft。

### 阶段四：质量门禁

目标：

1. 实现 schema_validator。
2. 实现 evidence_validator。
3. 实现 quality_validator。
4. 实现 confirmed_gate_validator。
5. 实现质量报告。

阶段验收：

1. confirmed Requirement 满足全部准入门槛。
2. quality_report 能说明阻断原因。
3. unsupported_facts 数量为 0。

### 阶段五：规则降级与端到端验收

目标：

1. 实现规则模式拆解。
2. 实现规则模式 evidence 和 Grounding Check。
3. 实现端到端 pipeline。
4. 准备样例 PRD 和验收测试。

阶段验收：

1. LLM 关闭时仍可生成 draft Requirement。
2. 输出包含 fallback 标记。
3. 完成从 Markdown 到 test_seed 的端到端流程。

## 23. 用户 Review 关注点

请重点确认以下问题：

1. 是否接受本期只支持 Markdown 输入。
2. 是否接受 LLM 任务拆成多个模块，而不是一个大 prompt 一次性生成。
3. 是否接受默认只让 `confirmed` 进入 test_seed，`confirmed_candidate` 通过配置控制。
4. 是否接受 inferred 风险和负向测试建议进入 suggestions，而不是 facts。
5. 是否需要在本期增加 Word、PDF、Excel 输入支持。
6. 是否需要把人工确认做成配置文件标记，还是先只保留状态字段。

## 24. 待确认事项

在进入开发前，需要用户确认：

1. 详细设计是否通过。
2. 是否需要调整目录结构或文件命名。
3. 是否需要调整 Requirement JSON 字段。
4. 是否允许使用 Pydantic 做模型和 Schema 校验。
5. 是否需要真实 LLM 接入，还是先用可注入 mock client 完成开发测试。

