# 需求拆解 Skill PRD V1.2

## 1. 文档信息

| 字段   | 内容                                                                                        |
| ---- | ----------------------------------------------------------------------------------------- |
| 产品名称 | 需求拆解 Skill                                                                                |
| 文档版本 | V1.2                                                                                      |
| 版本说明 | 在 V1.1 基础上收敛为 LLM + LangChain + Prompts 的轻量需求拆解方案，保留防幻觉、防曲解、字段级证据、Grounding Check 与人工确认机制 |
| 适用角色 | 测试工程师、产品经理、开发工程师、AI 测试平台                                                                  |
| 核心目标 | 将原始需求文档拆解为 AI 可读、可追溯、可测试的结构化需求模型，为测试点生成智能体提供更准确、更全面的输入                                    |
| 设计原则 | 轻量、可测试、可追溯、LLM 负责理解与抽取、代码负责约束与校验、防止需求曲解、可人工修正                                             |

---

## 2. 背景

从 PRD 直接生成测试点时，存在以下问题：

1. 原始需求表达不稳定，测试点生成容易漏掉规则、异常、边界和状态流转。
2. 仅靠固定逻辑拆解需求，容易机械切分，缺少业务语义理解。
3. 仅靠 LLM 直接生成测试点，输出容易不稳定、不可追溯、不可校验。
4. LLM 可能补充原文没有的内容，导致需求被曲解或扩大范围。
5. 需求中的测试对象、约束、状态、权限、风险点没有统一结构。
6. 需求变更后，测试点影响范围难以判断。

因此，需求拆解 Skill 采用轻量方案：

```text
文档解析 + LangChain 调用 LLM + Prompt 语义拆解 + 证据追溯 + 结构化校验 + 人工确认
```

不是建设复杂平台，也不在 LLM 失败时自动生成低可信结果；核心是先把需求拆清楚，让测试点生成智能体拿到更稳定的结构化输入。

核心原则是：

```text
LLM 负责理解、拆解和抽取需求
LangChain 负责组织调用链和结构化输出
Prompt 负责约束拆解口径和字段格式
代码负责 Schema、证据、枚举、状态模型和质量门禁校验
证据负责防止曲解
人工负责确认高风险与不确定项
```

---

## 3. 产品目标

需求拆解 Skill 的目标是：

1. 将需求文档拆解为单一、可验证、可测试的 Requirement。
2. 使用 LLM + LangChain + Prompts 理解自然语言需求，避免机械拆解。
3. 从每个 Requirement 中提取测试点生成所需的核心信息。
4. 明确测试对象、业务约束、状态流转、权限规则、风险标签和验收标准。
5. 对 LLM 输出结果进行证据校验，防止乱添加、过度推断或曲解原文。
6. 将“需求事实”和“测试设计建议”分离，避免 AI 推断污染正式需求。
7. 输出统一 JSON / Markdown / test_seed，供测试点生成系统直接消费。
8. 保持轻量，不建设复杂知识图谱、不做完整测试用例生成、不引入重型平台能力。
9. LLM 不可用或输出不合格时，直接返回错误和质量报告，不生成低可信 Requirement。

---

## 4. 非目标

当前版本不做以下内容：

1. 不直接生成完整测试用例。
2. 不建设独立 Web 平台。
3. 不建设复杂知识图谱数据库。
4. 不做多人审批流。
5. 不做完整需求生命周期管理。
6. 不让 LLM 自动确认冲突需求。
7. 不让 LLM 绕过 Schema 校验直接输出最终结果。
8. 不允许没有原文证据的 AI 推断直接成为需求事实。
9. 不实现 LLM 失败后的自动拆解结果。
10. 不把需求拆解 Skill 做成复杂编排平台；优先服务测试点生成智能体。

---

## 5. 核心处理流程

```text
Step 1  输入原始需求文档
Step 2  代码解析文档结构
Step 3  生成文档切片 section，并保留来源追溯
Step 4  LangChain 加载 Prompt 并调用 LLM 识别业务语义
Step 5  LLM 拆解 Requirement 候选项
Step 6  LLM 提取 test_objects
Step 7  LLM 提取 constraints
Step 8  LLM 提取 state_model / permissions / risk_tags
Step 9  LLM 生成 GWT 验收标准
Step 10 字段级 evidence 绑定
Step 11 Grounding Check 校验是否有原文依据
Step 12 区分 requirement_facts 与 test_design_suggestions
Step 13 代码校验结构完整性
Step 14 生成结构化需求模型
Step 15 生成 test_seed
Step 16 测试点生成系统消费 test_seed
```

---

## 6. LLM 在流程中的职责

### 6.1 LLM 使用原则

LLM 只用于语义理解、需求拆解和结构化抽取，不用于最终可信判断。LangChain 负责组织 Prompt 调用、模型调用和结构化解析；代码负责最终约束与校验。

| 阶段              | 是否使用 LLM / LangChain | 说明                                   |
| --------------- | -------------------- | ------------------------------------ |
| 文档读取            | 否                    | 由代码解析 Markdown，保留原文和标题层级             |
| 文档切片            | 否                    | 由代码按标题和段落切片，保持实现简单稳定                |
| 业务层级识别          | 是                    | 识别 domain、module、feature             |
| Requirement 拆解  | 是                    | 将复合需求拆成原子需求候选项                       |
| 测试对象提取          | 是                    | 提取字段、按钮、状态、角色、接口、数据对象                |
| 约束提取            | 是                    | 提取输入约束、业务规则、权限规则、状态限制                |
| 状态模型提取          | 是                    | 提取状态集合和状态流转                          |
| 权限规则提取          | 是                    | 提取角色、身份、数据归属、操作权限                    |
| 风险标签识别          | 是                    | 根据需求语义标记测试风险                         |
| GWT 验收标准生成      | 是                    | 生成 Given / When / Then               |
| 字段级证据绑定         | 是 + 代码校验            | LLM 可辅助寻找 quote，代码校验 quote 必须来自原文    |
| Grounding Check | 是 + 代码校验            | 检查字段是否有原文依据                          |
| JSON Schema 校验  | 否                    | 由代码强制校验                              |
| 质量评分            | 否                    | 由代码按固定规则计算                           |
| 文件输出            | 否                    | 由代码生成 JSON / Markdown                |
| 是否 confirmed    | 否                    | 由人工或配置决定                             |

### 6.2 LangChain 与 Prompt 使用边界

本 Skill 可以使用 LangChain，但只用于简化 LLM 调用链，不引入复杂 Agent 编排。

建议使用范围：

1. PromptTemplate：管理拆解、抽取、GWT、Grounding Check 等 Prompt。
2. Structured Output Parser 或 PydanticOutputParser：约束 LLM 返回 JSON。
3. Runnable 链：按固定顺序执行语义拆解、字段抽取和自检。
4. 可注入 LLM client：复用项目已有 `agents.common.config.settings.llm`。

不建议使用范围：

1. 不需要多 Agent 协作。
2. 不需要长期记忆。
3. 不需要向量数据库。
4. 不需要复杂工具调用。
5. 不需要在 LLM 失败时自动生成低可信拆解结果。

---

## 7. LLM 拆解任务设计

### 7.1 任务一：语义识别

目标：理解需求片段表达的业务意图。

输入：

```json
{
  "section_id": "SEC-001",
  "title": "取消订单",
  "content": "用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。"
}
```

LLM 输出：

```json
{
  "business_intent": "用户在满足状态和身份条件时可以取消订单",
  "main_entities": ["订单", "用户"],
  "actions": ["取消订单"],
  "rules": [
    "待支付订单允许取消",
    "已支付订单不可取消",
    "非本人订单不可操作"
  ]
}
```

---

### 7.2 任务二：Requirement 拆解

目标：将复合需求拆为多个原子 Requirement。

输入：

```text
用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。
```

LLM 输出：

```json
[
  {
    "title": "待支付订单允许取消",
    "description": "订单状态为待支付时，订单创建人可以取消订单。"
  },
  {
    "title": "已支付订单不允许取消",
    "description": "订单状态为已支付时，用户不可取消订单。"
  },
  {
    "title": "非订单创建人不允许取消订单",
    "description": "非订单创建人不可取消该订单。"
  }
]
```

拆解要求：

1. 一个 Requirement 只表达一个业务目标或业务规则。
2. 每个 Requirement 必须能独立生成测试点。
3. 不按按钮、字段、文案机械拆分。
4. 不把异常、权限、状态规则混在一个 Requirement 中。
5. 不能确定的信息必须标记 unresolved，不允许编造。
6. 拆解出的每个 Requirement 必须能追溯到原文 quote。

---

### 7.3 任务三：提取 test_objects

目标：识别测试点生成时“测什么”。

LLM 输出：

```json
"test_objects": [
  {
    "name": "订单状态",
    "type": "enum",
    "values": ["待支付", "已支付", "已取消"]
  },
  {
    "name": "用户身份",
    "type": "role",
    "values": ["订单创建人", "非订单创建人"]
  },
  {
    "name": "取消订单操作",
    "type": "action"
  }
]
```

---

### 7.4 任务四：提取 constraints

目标：识别测试点生成时“怎么限制”。

LLM 输出：

```json
"constraints": [
  {
    "object": "订单状态",
    "rule": "订单状态必须为待支付",
    "constraint_type": "state",
    "test_dimension": "状态校验"
  },
  {
    "object": "用户身份",
    "rule": "用户必须为订单创建人",
    "constraint_type": "permission",
    "test_dimension": "权限校验"
  }
]
```

约束类型包括：

```text
required
format
length
range
enum
state
permission
unique
business_rule
dependency
```

---

### 7.5 任务五：提取 state_model

目标：从需求中识别状态集合、状态流转和非法流转。

LLM 输出：

```json
"state_model": {
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

代码校验要求：

1. `from` 和 `to` 必须存在于 `states` 中。
2. `trigger` 不允许为空。
3. 同一状态流转不能重复。
4. 非法流转必须能追溯到原文或业务规则。

---

### 7.6 任务六：识别 risk_tags

目标：提示测试点生成系统补充高风险测试方向。

LLM 输出：

```json
"risk_tags": [
  "状态流转",
  "权限",
  "幂等"
]
```

风险标签建议固定枚举：

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

LLM 不允许生成无限制自定义风险标签，避免测试点生成失控。

---

### 7.7 任务七：生成 GWT 验收标准

目标：将需求转换为可验证的 Given / When / Then。

LLM 输出：

```json
"acceptance_criteria": [
  {
    "given": "订单状态为待支付，且用户为订单创建人",
    "when": "用户执行取消订单操作",
    "then": "订单状态变为已取消，并返回取消成功提示"
  }
]
```

要求：

1. given 必须描述前置状态或条件。
2. when 必须描述触发动作。
3. then 必须描述可验证结果。
4. 不允许出现“系统正常处理”这类不可验证表述。

---

## 8. 防幻觉与防曲解机制

### 8.1 核心原则

需求拆解 Skill 不直接信任 LLM 输出。LLM 输出只视为候选结构，必须经过证据绑定、Grounding Check、代码校验和人工确认。

硬规则：

```text
任何没有原文证据支撑的内容，不得作为需求事实，只能作为测试设计建议。
```

---

### 8.2 字段级证据机制

除 Requirement 级 source_trace 外，关键字段必须记录字段级 evidence。

适用字段包括：

1. title
2. description
3. test_objects
4. constraints
5. state_model
6. permissions
7. acceptance_criteria
8. requirement_facts

字段级 evidence 示例：

```json
{
  "field": "constraints",
  "value": "订单状态必须为待支付",
  "evidence": {
    "source_id": "SRC-001",
    "section_id": "SEC-001",
    "quote": "用户可以取消待支付订单"
  }
}
```

处理规则：

1. 关键字段没有 evidence 时，不得进入 confirmed。
2. evidence quote 必须来自原始 section，不允许 LLM 自造 quote。
3. evidence 只证明字段来源，不代表字段一定正确，仍需代码校验。

---

### 8.3 evidence_type 分类

每个抽取项必须标记 evidence_type。

| evidence_type | 说明 | 是否可作为需求事实 |
|---|---|---|
| explicit | 原文明确说明 | 是 |
| inferred | LLM 基于上下文或测试经验推断 | 否，只能作为建议 |
| missing | 原文缺失，无法确认 | 否，进入 unresolved |
| conflict | 多处原文冲突 | 否，进入 conflict_items |

示例：

```json
{
  "value": "重复点击取消订单需要幂等处理",
  "evidence_type": "inferred",
  "confidence": 0.62
}
```

该内容只能进入 `test_design_suggestions`，不能进入 `requirement_facts`。

---

### 8.4 requirement_facts 与 test_design_suggestions 分离

为避免 AI 推断污染正式需求，模型必须拆成两层：

```json
{
  "requirement_facts": {},
  "test_design_suggestions": {}
}
```

示例：

```json
{
  "requirement_facts": {
    "constraints": [
      {
        "value": "订单状态必须为待支付",
        "evidence_type": "explicit"
      }
    ]
  },
  "test_design_suggestions": {
    "risk_tags": [
      {
        "value": "幂等",
        "evidence_type": "inferred"
      }
    ],
    "negative_suggestions": [
      "重复点击取消订单"
    ]
  }
}
```

处理规则：

1. requirement_facts 只保存原文明确支持的需求事实。
2. test_design_suggestions 可保存 AI 推断出的测试风险、边界、异常、补充测试方向。
3. 测试点生成系统可以消费 suggestions，但必须标记为“测试建议”，不能当作需求本身。

---

### 8.5 Grounding Check

LLM 输出后必须执行 Grounding Check。

目标：检查每个 Requirement / constraint / state / permission / acceptance_criteria 是否能在原文 quote 中找到依据。

输出示例：

```json
{
  "grounding_check": {
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
}
```

处理规则：

1. unsupported_items 不直接删除。
2. unsupported_items 应移动到 test_design_suggestions。
3. unsupported_items 不允许作为 confirmed Requirement 的事实字段。
4. Grounding Check 未通过时，Requirement 状态不得为 confirmed。

---

### 8.6 冲突与不确定项处理

LLM 不允许自动解决冲突。

示例：

```text
A 文档：已支付订单不可取消
B 文档：支付后 30 分钟内可以取消
```

输出：

```json
"conflict_items": [
  {
    "field": "取消订单规则",
    "source_a": "已支付订单不可取消",
    "source_b": "支付后 30 分钟内可以取消",
    "resolution": "pending_manual_confirm"
  }
]
```

处理规则：

1. 存在 conflict_items 的 Requirement 默认状态为 draft。
2. conflict_items 不得被 LLM 自动裁决。
3. 人工确认后才可以进入 confirmed。

---

### 8.7 曲解或乱添加后的处理流程

当发现 LLM 输出 unsupported / conflict / low_confidence 内容时，按以下流程处理：

```text
发现问题字段
↓
标记 issue
↓
Requirement 状态保持 draft
↓
将无证据内容移动到 test_design_suggestions
↓
质量报告输出 issue
↓
等待人工确认
```

示例：

```json
{
  "issue_type": "unsupported_inference",
  "requirement_id": "REQ-ORDER-001",
  "field": "constraints",
  "value": "订单取消后库存自动回滚",
  "action": "moved_to_test_design_suggestions",
  "reason": "原文没有库存回滚描述"
}
```

---

## 9. LLM 输出约束

### 9.1 必须输出 JSON

LLM 每个任务必须输出 JSON，不输出自然语言解释。

### 9.2 必须保留来源

每个 Requirement 必须保留：

```json
"source_trace": {
  "source_id": "SRC-001",
  "section_id": "SEC-001",
  "quote": "用户可以取消待支付订单，已支付订单不可取消，非本人订单不可操作。"
}
```

### 9.3 不允许编造

如果原文没有明确说明，应输出：

```json
"unresolved": [
  {
    "field": "output_result",
    "reason": "原文未说明取消成功后的提示文案"
  }
]
```

### 9.4 不允许自动解决冲突

如果多处需求冲突，应输出 conflict_items，并等待人工确认。

---

## 10. 人工确认机制

LLM 输出的 Requirement 默认状态根据来源可信度与校验结果决定。

| 来源可信度 | 默认状态 |
|---|---|
| high 且 Grounding Check 通过 | confirmed_candidate |
| high 但存在 unsupported_items | draft |
| medium | draft |
| low | draft |

状态说明：

| 状态 | 说明 | 是否进入测试点生成 |
|---|---|---|
| draft | 初步拆解，待确认 | 否 |
| confirmed_candidate | 高可信来源生成，且证据校验通过，建议抽样确认 | 可配置 |
| confirmed | 已确认 | 是 |
| changed | 需求变化，待复核 | 否 |
| deprecated | 已废弃 | 否 |

---

## 11. confirmed 准入门槛

Requirement 进入 confirmed 必须满足：

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

不满足以上条件时，只能保持 draft 或 confirmed_candidate。

---

## 12. 结构化需求模型

### 12.1 顶层结构

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

新增字段：

| 字段 | 说明 |
|---|---|
| llm_trace | 记录 LLM 使用情况、模型、prompt 版本、置信度、失败原因 |

---

## 13. Requirement 数据结构

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
  "llm_metadata": {
    "model": "",
    "prompt_version": "",
    "confidence": 0.0,
    "reasoning_summary": ""
  },
  "status": "draft"
}
```

---

## 14. LLM Metadata

每个 Requirement 应记录 LLM 元信息：

```json
"llm_metadata": {
  "model": "gpt-4.1",
  "prompt_version": "requirement_decompose_v1",
  "confidence": 0.87,
  "reasoning_summary": "该需求包含状态规则和权限规则，拆分为独立可测试需求。",
  "generated_at": "2026-06-17T10:00:00+08:00"
}
```

说明：

1. confidence 用于质量提示，不直接决定是否可信。
2. reasoning_summary 只保留简短摘要，不保存完整推理过程。
3. prompt_version 用于后续回归和效果对比。

---

## 15. LLM Prompt 管理

### 15.1 Prompt 模板目录

```text
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

### 15.2 Prompt 版本规则

每个 Prompt 必须有版本号：

```yaml
prompt_name: requirement_split
version: v1.0
```

当修改拆解规则或输出字段时，必须更新 prompt version。

---

## 16. LLM 自检机制

在输出 Requirement 后，增加一次 LLM 自检。

自检问题：

1. 是否存在多个业务规则被错误合并？
2. 是否存在不可测试的 Requirement？
3. 是否遗漏权限、状态、边界、异常？
4. 是否存在原文没有依据的推断？
5. 是否所有字段都能追溯到 source_trace？
6. 是否有 inferred 内容被错误放入 requirement_facts？

自检输出：

```json
"llm_self_check": {
  "passed": false,
  "issues": [
    {
      "type": "missing_permission",
      "description": "原文提到非本人不可操作，但 permissions 字段为空"
    }
  ]
}
```

---

## 17. 代码校验机制

LLM 输出后必须经过代码校验。代码校验只负责判断结构、证据和字段是否合法，不负责生成 Requirement。

代码校验包括：

1. JSON Schema 校验。
2. 必填字段校验。
3. 枚举值校验。
4. source_trace 校验。
5. field_evidence 校验。
6. requirement_facts 与 test_design_suggestions 分层校验。
7. test_objects 非空校验。
8. constraints 非空校验。
9. GWT 可验证性校验。
10. risk_tags 枚举校验。
11. state_model 合法性校验。
12. grounding_check 结果校验。
13. confirmed 状态准入校验。

代码校验失败时，不允许进入 confirmed。若关键字段缺失或 Schema 不合法，本次拆解应返回错误或保留 draft，并在质量报告中说明原因。

---

## 18. LLM-only 失败处理

LLM 不可用、调用失败、返回非 JSON 或输出无法通过 Schema 校验时，系统应直接返回失败结果，并输出清晰错误信息。

失败返回示例：

```json
{
  "success": false,
  "requirements": [],
  "test_seeds": [],
  "errors": [
    "LLM 调用失败或输出无法通过 Schema 校验"
  ],
  "warnings": [],
  "quality_report": {
    "quality_score": 0.0,
    "quality_gate_passed": false
  }
}
```

处理原则：

1. 不使用标题、关键词、句号切分等方式自动生成低可信 Requirement。
2. 不生成低可信的 test_seed。
3. 不把失败结果交给测试点生成智能体消费。
4. 错误信息必须便于定位：LLM 调用失败、JSON 解析失败、Schema 校验失败或质量门禁失败。
5. 用户修复配置、Prompt 或原始需求后重新执行。

---

## 19. test_seed 输出

测试点生成系统不直接消费完整 Requirement，而是优先消费 test_seed。

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

---

## 20. 质量指标

| 指标 | 合格标准 |
|---|---|
| 字段完整率 | >= 95% |
| 来源可追溯率 | 100% |
| 字段级证据覆盖率 | >= 95% |
| 测试对象覆盖率 | >= 95% |
| 约束提取覆盖率 | >= 90% |
| GWT 覆盖率 | >= 95% |
| 风险标签覆盖率 | >= 90% |
| LLM 自检通过率 | >= 90% |
| Grounding Check 通过率 | >= 95% |
| Schema 校验通过率 | 100% |
| confirmed 需求可生成测试点比例 | 100% |
| unsupported_facts 数量 | 0 |

---

## 21. 质量报告示例

```json
{
  "quality_score": 0.91,
  "field_completeness": 0.97,
  "traceability_rate": 1.0,
  "field_evidence_rate": 0.96,
  "grounding_check_rate": 0.95,
  "unsupported_facts": 0,
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

---

## 22. 配置文件示例

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

---

## 23. 轻量实现架构

```text
requirement_decomposition/
  parser/
    document_parser.py
  chunker/
    section_chunker.py
  llm/
    llm_client.py
    prompt_loader.py
    langchain_chain.py
    semantic_analyzer.py
    requirement_splitter.py
    test_object_extractor.py
    constraint_extractor.py
    state_model_extractor.py
    risk_tag_extractor.py
    gwt_generator.py
    evidence_binder.py
    grounding_checker.py
    self_checker.py
  validator/
    schema_validator.py
    quality_validator.py
    evidence_validator.py
    confirmed_gate_validator.py
  generator/
    json_generator.py
    markdown_generator.py
    test_seed_generator.py
  pipeline.py
prompts/
  requirement_split.md
  test_object_extract.md
  constraint_extract.md
  state_model_extract.md
  risk_tag_extract.md
  gwt_generate.md
  evidence_bind.md
  grounding_check.md
```

---

## 24. 核心接口

```python
from requirement_decomposition import run_decomposition

result = run_decomposition(
    source_path="docs/prd.md",
    config_path="requirement_decomposition.yaml"
)
```

返回：

```json
{
  "success": true,
  "requirements": [],
  "test_seeds": [],
  "quality_report": {},
  "llm_trace": {
    "enabled": true,
    "model": "gpt-4.1",
    "prompt_version": "v1.0"
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

---

## 25. 验收标准

### 25.1 功能验收

1. 支持读取 Markdown 需求文档。
2. 支持使用 LLM 将复合需求拆解为 Requirement。
3. 支持提取 test_objects。
4. 支持提取 constraints。
5. 支持提取 state_model。
6. 支持识别 permissions。
7. 支持生成 risk_tags。
8. 支持生成 GWT 格式验收标准。
9. 支持生成字段级 evidence。
10. 支持执行 Grounding Check。
11. 支持区分 requirement_facts 与 test_design_suggestions。
12. 支持将无证据推断移动到 suggestions。
13. 支持生成 test_seed。
14. 支持 LLM 自检。
15. 支持代码校验。
16. 支持 LLM 失败时返回错误，不生成低可信拆解结果。
17. 支持输出 llm_trace 与 grounding_summary。

---

### 25.2 质量验收

1. 每个 confirmed Requirement 必须有 source_trace。
2. 每个 confirmed Requirement 的关键字段必须有 field_evidence。
3. 每个 confirmed Requirement 必须有 test_objects。
4. 每个 confirmed Requirement 必须有 constraints。
5. 每个 confirmed Requirement 必须有 acceptance_criteria。
6. 每个 confirmed Requirement 必须通过 Grounding Check。
7. requirement_facts 中不得存在 unsupported_items。
8. LLM 生成内容必须通过 JSON Schema 校验。
9. LLM 不得自动解决冲突需求。
10. LLM 不得编造原文没有的信息作为需求事实。
11. 每个 confirmed Requirement 至少可以生成一个测试点。

---

## 26. 最终定位

需求拆解 Skill 不是纯固定逻辑解析器，也不是让 LLM 自由发挥的测试生成器。

它的定位是：

```text
具备防幻觉机制的 LLM 辅助轻量需求语义拆解层
```

核心价值是：

```text
用 LLM 理解自然语言需求
用 LangChain 和 Prompts 组织稳定的拆解链路
用证据机制防止曲解需求
用结构化模型承接测试设计信息
用代码校验保证输出稳定可信
```

最终输出应稳定回答：

```text
测什么？
有什么条件？
有什么约束？
有什么状态？
有什么权限？
有什么风险？
预期结果是什么？
来源在哪里？
哪些内容是原文事实？
哪些内容只是测试建议？
哪些内容不确定？
哪些内容需要人工确认？
```
