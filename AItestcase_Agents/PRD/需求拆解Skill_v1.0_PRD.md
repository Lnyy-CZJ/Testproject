# 需求拆解 Skill PRD

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 产品名称 | 需求拆解 Skill |
| 文档版本 | V1.0 |
| 适用角色 | 测试工程师、产品经理、开发工程师、AI测试平台 |
| 核心目标 | 将原始需求文档拆解为 AI 可读、可追溯、可测试的结构化需求模型，为测试点生成系统提供稳定输入 |
| 设计原则 | 轻量、可测试、可追溯、可人工修正、直接服务测试点生成 |

---

## 2. 背景

当前从 PRD 直接生成测试点时，存在以下问题：

1. 原始需求文档表达不稳定，AI容易漏掉规则、异常、边界和状态流转。
2. 测试点生成依赖自然语言理解，结果不够稳定。
3. 需求中的对象、条件、约束、权限、状态变化没有结构化表达。
4. 测试点无法准确追溯到原始需求来源。
5. 需求变更后，难以判断哪些测试点需要补充或回归。

因此需要在 PRD 和测试点生成之间增加一层轻量结构化模型：

- 原始需求文档--需求拆解--结构化需求模型--测试点生成系统 

---

## 3. 产品目标

需求拆解 Skill 的目标是：

1. 将需求文档拆解为单一、可验证、可测试的 Requirement。
2. 从每个 Requirement 中提取测试点生成所需的核心信息。
3. 明确需求的测试对象、业务约束、输入条件、状态流转、权限规则和风险标签。
4. 输出统一 JSON / Markdown 结构，供测试点生成系统直接消费。
5. 保持模型轻量，不建设复杂知识图谱、不做完整测试用例生成、不引入重型平台能力。

---

## 4. 非目标

当前版本不做以下内容：

1. 不生成完整测试用例。
2. 不建设独立 Web 平台。
3. 不建设复杂知识图谱数据库。
4. 不做多人审批流。
5. 不做完整需求生命周期管理。
6. 不强制支持所有文档格式的完美解析。
7. 不替代测试点生成系统，只提供高质量结构化输入。

---

## 5. 核心使用流程

- Step 1  输入原始需求文档 
- Step 2  文档切片与来源追溯 
- Step 3  识别业务域、模块、功能 
- Step 4  拆解 Requirement 
- Step 5  提取测试对象 test_objects 
- Step 6  提取约束 constraints 
- Step 7  提取状态模型 state_model 
- Step 8  提取权限、风险标签、验收标准 
- Step 9  输出结构化需求模型 
- Step 10 测试点生成系统消费模型 

---

## 6. 核心概念

| 概念 | 说明 |
|---|---|
| Requirement | 最小可测试需求单元 |
| Test Object | 测试对象，例如字段、按钮、接口、订单状态、用户角色 |
| Constraint | 约束规则，例如不能为空、长度限制、状态限制、金额范围 |
| State Model | 状态模型，用于表达状态集合与合法流转 |
| Risk Tag | 风险标签，用于提示测试生成系统重点补充测试点 |
| GWT | Given / When / Then 格式的验收标准 |
| Source Trace | 来源追溯，用于定位结构化内容来自原始文档的位置 |

---

## 7. 结构化需求模型

### 7.1 顶层结构

    {
    "project": {},
    "sources": [],
    "domains": [],
    "modules": [],
    "features": [],
    "requirements": [],
    "quality_report": {},
    "version": {}
    }

---

## 8. Requirement 数据结构

### 8.1 字段定义

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| requirement_id | string | 是 | 需求编号 |
| title | string | 是 | 需求标题 |
| domain | string | 否 | 所属业务域 |
| module | string | 是 | 所属模块 |
| feature | string | 是 | 所属功能 |
| description | string | 是 | 需求描述 |
| source_trace | object | 是 | 来源追溯 |
| test_objects | array | 是 | 测试对象 |
| preconditions | array | 否 | 前置条件 |
| trigger | string | 否 | 触发动作 |
| constraints | array | 是 | 业务约束、字段约束、规则约束 |
| state_model | object | 否 | 状态模型 |
| permissions | array | 否 | 权限规则 |
| main_flow | array | 否 | 正常流程 |
| exception_flows | array | 否 | 异常流程 |
| acceptance_criteria | array | 是 | GWT格式验收标准 |
| risk_tags | array | 是 | 风险标签 |
| test_generation_hints | array | 是 | 测试点生成提示 |
| status | enum | 是 | draft / confirmed / changed / deprecated |
| confidence | number | 否 | AI拆解置信度 |

---

## 9. 核心字段说明

### 9.1 test_objects

用于描述测试点生成时“测什么”。

    "test_objects": [
    {
        "name": "订单状态",
        "type": "enum",
        "values": ["待支付", "已支付", "已取消"]
    },
    {
        "name": "取消订单按钮",
        "type": "action"
    },
    {
        "name": "用户身份",
        "type": "role"
    }
    ]

对象类型建议包括：

| 类型 | 说明 |
|---|---|
| input | 输入字段 |
| output | 输出结果 |
| action | 用户动作 |
| status | 状态 |
| enum | 枚举值 |
| role | 用户角色 |
| api | 接口 |
| data | 数据对象 |

---

### 9.2 constraints

用于描述测试点生成时“怎么限制”。

"test_objects": [
  {
    "name": "订单状态",
    "type": "enum",
    "values": ["待支付", "已支付", "已取消"]
  },
  {
    "name": "取消订单按钮",
    "type": "action"
  },
  {
    "name": "用户身份",
    "type": "role"
  }
]

常见约束类型：

| 类型 | 示例 |
|---|---|
| 必填约束 | 用户名不能为空 |
| 格式约束 | 手机号必须为11位数字 |
| 长度约束 | 昵称最长20个字符 |
| 范围约束 | 金额必须大于0 |
| 枚举约束 | 状态只能是待支付、已支付、已取消 |
| 权限约束 | 仅管理员可审核 |
| 状态约束 | 已支付订单不可取消 |
| 唯一性约束 | 用户名不可重复 |

---

### 9.3 state_model

用于描述状态流转。
    "state_model": {
    "entity": "订单",
    "states": ["待支付", "已支付", "已取消"],
    "transitions": [
        {
        "from": "待支付",
        "to": "已取消",
        "trigger": "用户取消订单",
        "valid": true
        },
        {
        "from": "已支付",
        "to": "已取消",
        "trigger": "用户取消订单",
        "valid": false
        }
    ]
    }

测试点生成系统应基于 state_model 生成：

1. 合法状态流转测试点。
2. 非法状态流转测试点。
3. 重复操作测试点。
4. 跨状态操作测试点。
5. 状态变更后数据一致性测试点。

---

### 9.4 acceptance_criteria

统一使用 Given / When / Then 格式。

    "acceptance_criteria": [
  {
    "given": "订单状态为待支付，且用户为订单创建人",
    "when": "用户点击取消订单",
    "then": "订单状态变为已取消，并返回取消成功提示"
  }
]
---

### 9.5 risk_tags

用于提示测试生成系统重点关注风险。
    "risk_tags": [
    "状态流转",
    "权限",
    "数据一致性"
    ]

建议内置风险标签：

| 风险标签 | 生成测试点方向 |
|---|---|
| 权限 | 越权、未登录、角色不匹配 |
| 状态流转 | 合法流转、非法流转、重复流转 |
| 金额 | 精度、边界、负数、零值 |
| 数据一致性 | 主表、明细表、缓存、异步结果 |
| 并发 | 重复提交、并发修改 |
| 幂等 | 重复请求、重复点击 |
| 输入校验 | 空值、格式、长度、范围 |
| 异常流程 | 异常提示、失败回滚 |
| 接口 | 入参、出参、错误码 |
| 兼容性 | 不同端、不同版本、不同环境 |

---

## 10. Requirement 示例

    {
  "requirement_id": "REQ-ORDER-001",
  "title": "待支付订单允许取消",
  "domain": "订单",
  "module": "订单状态管理",
  "feature": "取消订单",
  "description": "用户可以取消处于待支付状态的订单。",
  "source_trace": {
    "source_id": "SRC-001",
    "section": "3.2 取消订单",
    "quote": "待支付订单允许用户取消"
  },
  "test_objects": [
    {
      "name": "订单状态",
      "type": "enum",
      "values": ["待支付", "已支付", "已取消"]
    },
    {
      "name": "用户身份",
      "type": "role"
    },
    {
      "name": "取消订单按钮",
      "type": "action"
    }
  ],
  "preconditions": [
    "订单存在",
    "用户已登录"
  ],
  "trigger": "用户点击取消订单",
  "constraints": [
    {
      "object": "订单状态",
      "rule": "订单状态必须为待支付",
      "test_dimension": "状态校验"
    },
    {
      "object": "用户身份",
      "rule": "用户必须为订单创建人",
      "test_dimension": "权限校验"
    }
  ],
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
  },
  "permissions": [
    "仅订单创建人可以取消订单"
  ],
  "main_flow": [
    "用户进入订单详情页",
    "系统展示取消订单按钮",
    "用户点击取消订单",
    "系统校验订单状态和用户身份",
    "系统取消订单并更新状态"
  ],
  "exception_flows": [
    "订单不存在时返回错误提示",
    "订单状态非待支付时拒绝取消",
    "非订单创建人操作时拒绝取消"
  ],
  "acceptance_criteria": [
    {
      "given": "订单状态为待支付，且用户为订单创建人",
      "when": "用户点击取消订单",
      "then": "订单状态变为已取消，并返回取消成功提示"
    },
    {
      "given": "订单状态为已支付",
      "when": "用户点击取消订单",
      "then": "系统拒绝取消，并返回状态不允许取消提示"
    }
  ],
  "risk_tags": [
    "状态流转",
    "权限",
    "幂等"
  ],
  "test_generation_hints": [
    "验证待支付订单可取消",
    "验证已支付订单不可取消",
    "验证非订单创建人不可取消",
    "验证重复点击取消订单的幂等性"
  ],
  "status": "confirmed",
  "confidence": 0.92
}

---

## 11. 拆解规则

### 11.1 Requirement 拆解标准

一个 Requirement 必须满足：

1. 只描述一个明确业务目标。
2. 有明确测试对象。
3. 有明确触发动作或判断条件。
4. 有可验证结果。
5. 至少能生成一个测试点。
6. 能追溯到原始需求来源。

---

### 11.2 不应过度拆解

以下情况不建议拆成独立 Requirement：

1. 只是一个按钮文案。
2. 只是一个页面展示字段。
3. 不能独立验证。
4. 没有独立业务含义。
5. 拆开后不会增加测试覆盖价值。

---

### 11.3 推荐拆解粒度

推荐粒度：

- 一个业务动作 + 一个核心规则 + 一个可验证结果 

示例：

- 待支付订单允许取消
- 已支付订单不允许取消
- 非订单创建人不允许取消 

不推荐：

- 取消按钮展示
- 取消按钮点击
- 取消按钮颜色 

除非这些本身就是明确需求。

---

## 12. 测试点生成映射规则

| 需求模型字段 | 测试点生成用途 |
|---|---|
| title | 测试点标题参考 |
| description | 正向功能测试点 |
| test_objects | 测试对象维度 |
| constraints | 规则、边界、异常测试点 |
| preconditions | 测试前置条件 |
| trigger | 测试步骤触发动作 |
| state_model | 状态流转测试点 |
| permissions | 权限测试点 |
| exception_flows | 异常测试点 |
| acceptance_criteria | 预期结果 |
| risk_tags | 补充风险测试点 |
| test_generation_hints | 直接生成测试点参考 |

---

## 13. 输出给测试点生成系统的数据格式

### 13.1 单个 Requirement 映射输出

    {
  "requirement_id": "REQ-ORDER-001",
  "module": "订单状态管理",
  "feature": "取消订单",
  "test_seed": {
    "objects": ["订单状态", "用户身份", "取消订单按钮"],
    "conditions": ["订单状态=待支付", "用户=订单创建人"],
    "constraints": ["仅待支付订单允许取消", "仅订单创建人允许取消"],
    "state_transitions": ["待支付 -> 已取消"],
    "permissions": ["订单创建人"],
    "risk_tags": ["状态流转", "权限", "幂等"],
    "expected_results": ["订单状态变为已取消", "返回取消成功提示"]
  }
}
---

## 14. 质量校验规则

### 14.1 必填校验

每个 Requirement 必须包含：

1. requirement_id
2. title
3. module
4. feature
5. description
6. source_trace
7. test_objects
8. constraints
9. acceptance_criteria
10. risk_tags
11. test_generation_hints
12. status

---

### 14.2 质量指标

| 指标 | 合格标准 |
|---|---|
| 字段完整率 | >= 95% |
| 来源可追溯率 | 100% |
| 测试对象覆盖率 | >= 95% |
| 约束提取覆盖率 | >= 90% |
| 验收标准覆盖率 | >= 95% |
| 风险标签覆盖率 | >= 90% |
| confirmed需求可生成测试点比例 | 100% |

---

### 14.3 质量报告示例

    {
  "quality_score": 0.93,
  "field_completeness": 0.97,
  "traceability_rate": 1.0,
  "test_object_rate": 0.96,
  "constraint_rate": 0.91,
  "acceptance_criteria_rate": 0.98,
  "risk_tag_rate": 0.92,
  "issues": [
    {
      "requirement_id": "REQ-ORDER-003",
      "type": "missing_constraints",
      "severity": "medium",
      "suggestion": "补充字段约束或业务规则约束"
    }
  ]
}

---

## 15. 状态管理

| 状态 | 说明 | 是否进入测试点生成 |
|---|---|---|
| draft | AI初步拆解，未人工确认 | 默认不进入 |
| confirmed | 已确认，可用于测试生成 | 是 |
| changed | 需求发生变化，需要复核 | 默认不进入 |
| deprecated | 已废弃 | 否 |

---

## 16. 输入来源支持

| 来源类型 | 当前处理策略 |
|---|---|
| Markdown | 优先支持 |
| Word | 提取标题、段落、表格 |
| PDF文本 | 提取文本和页码 |
| Excel | 提取规则、字段、状态、权限 |
| 接口文档 | 提取接口、入参、出参、错误码 |
| 原型说明 | 提取页面、控件、交互 |
| 会议纪要 | 仅作为低置信候选需求 |

---

## 17. 异常与不确定信息处理

| 场景 | 处理方式 |
|---|---|
| 原文缺少条件 | 标记 unresolved |
| 原文多种理解 | 生成 ambiguity_notes |
| 多来源冲突 | 生成 conflict_items |
| 来源可信度低 | status 默认为 draft |
| 图片或扫描件无法解析 | 标记 unsupported_source |
| 字段缺失 | 进入 quality_report issues |

---

## 18. 轻量实现方案

### 18.1 模块结构

    requirement_decomposition/
    parser/
        document_parser.py
    splitter/
        requirement_splitter.py
    extractor/
        test_object_extractor.py
        constraint_extractor.py
        state_model_extractor.py
        risk_tag_extractor.py
    validator/
        quality_validator.py
    generator/
        json_generator.py
        markdown_generator.py
        test_seed_generator.py
    pipeline.py

---

### 18.2 核心接口
python
from requirement_decomposition import run_decomposition

result = run_decomposition(
    source_path="docs/prd.md",
    output_format="json"
)

返回：

{
  "success": True,
  "requirements": [],
  "quality_report": {},
  "test_seeds": [],
  "warnings": [],
  "errors": []
}

---

## 19. 配置文件示例

project:
  project_id: "PROJECT-001"
  project_name: "订单系统"
  version: "1.0.0"

sources:
  - source_id: "SRC-001"
    source_type: "markdown"
    path: "docs/order_prd.md"
    trust_level: "high"

decomposition:
  enable_llm: true
  min_confidence: 0.7
  auto_resolve_conflicts: false

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
  require_test_objects: true
  require_constraints: true

---

## 20. Markdown 输出模板
# REQ-ORDER-001 - 待支付订单允许取消

## 基础信息

- Module: 订单状态管理
- Feature: 取消订单
- Status: confirmed
- Confidence: 0.92

## 来源追溯

- Source: SRC-001
- Section: 3.2 取消订单
- Quote: 待支付订单允许用户取消

## 需求描述

用户可以取消处于待支付状态的订单。

## 测试对象

- 订单状态：待支付、已支付、已取消
- 用户身份：订单创建人、非订单创建人
- 取消订单按钮

## 约束规则

- 订单状态必须为待支付
- 用户必须为订单创建人

## 状态模型

- 待支付 -> 已取消：合法
- 已支付 -> 已取消：非法

## 验收标准

- Given 订单状态为待支付，且用户为订单创建人
- When 用户点击取消订单
- Then 订单状态变为已取消，并返回取消成功提示

## 风险标签

- 状态流转
- 权限
- 幂等

## 测试生成提示

- 验证待支付订单可取消
- 验证已支付订单不可取消
- 验证非订单创建人不可取消
- 验证重复取消订单的幂等性

---

## 21. 验收标准

### 21.1 功能验收

1. 可读取至少一种文本型需求文档。
2. 可将复合需求拆解为多个 Requirement。
3. 每个 Requirement 可提取 test_objects。
4. 每个 Requirement 可提取 constraints。
5. 可识别状态流转并生成 state_model。
6. 可生成 GWT 格式 acceptance_criteria。
7. 可生成 risk_tags。
8. 可输出测试点生成系统可消费的 test_seed。
9. 可输出质量报告。
10. 可保留 source_trace。

---

### 21.2 质量验收

1. confirmed Requirement 必填字段完整率 >= 95%。
2. confirmed Requirement 来源可追溯率 = 100%。
3. 每个 confirmed Requirement 至少有一个 test_object。
4. 每个 confirmed Requirement 至少有一个 constraint。
5. 每个 confirmed Requirement 至少有一个 acceptance_criteria。
6. 每个 confirmed Requirement 至少有一个 risk_tag。
7. 每个 confirmed Requirement 至少可以生成一个测试点。

---

## 22. 最终定位

需求拆解 Skill 不是完整的需求管理平台，也不是测试用例生成器。

它的定位是：

- 面向测试点生成的轻量需求结构化中间层 

核心价值是：

- 把自然语言 PRD 转换为测试点生成系统更容易理解的结构化输入 

最终输出应回答测试生成最关心的几个问题：

- 测什么？ 有什么条件？ 有什么约束？ 有什么状态？ 有什么权限？ 有什么风险？ 预期结果是什么？ 来源在哪里？ 