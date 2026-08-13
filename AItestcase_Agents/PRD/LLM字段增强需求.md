# RKM 模块 - LLM 字段增强需求文档（V1.0）

---

## 1. 文档信息

| 字段   | 内容                                       |
| ---- | ---------------------------------------- |
| 文档名称 | RKM 模块 - LLM 字段增强需求文档                    |
| 文档版本 | V1.0                                     |
| 所属模块 | rkm/builder（RKM 构建引擎）                    |
| 核心目标 | 在规则引擎初拆的基础上，通过 LLM 多轮增强提升 Requirement 各字段质量，显著提高 RKM 质量分数 |
| 前置依赖 | RKM V3.0 基础模块（规则引擎拆解、配置加载、质量校验）已可用 |

---

## 2. 背景与问题

### 2.1 当前现状

RKM V3.0 的 Requirement 拆解流程为：

```text
原文 → Markdown 解析 → 规则引擎拆解 → Requirement 输出
```

规则引擎（`requirement_splitter.py`）通过关键词匹配和模板拼接填充字段，存在以下问题：

### 2.2 字段质量问题清单

| 字段 | 当前实现方式 | 质量问题 | 影响 |
|---|---|---|---|
| description | 取第一句正文 | 经常截断不完整，缺少主语和条件 | 后续所有依赖 description 的环节质量下降 |
| preconditions | 关键词匹配（"前置"、"条件"） | 原文很少显式写"前置条件"，大量隐含条件漏抽 | 测试前置条件不完整 |
| main_flow | 关键词匹配（"流程"、"步骤"、"点击"等） | 只能抽取包含特定关键词的行，大量流程步骤丢失 | 测试步骤不完整 |
| exception_flows | 关键词匹配（"异常"、"失败"、"错误"等） | 原文不会总写"异常"二字，隐含异常场景全部漏掉 | 异常测试覆盖不足 |
| business_rules | 关键词匹配（"规则"、"必须"、"仅"等） | 大量业务约束不含这些关键词，漏抽严重 | 规则类测试点缺失 |
| acceptance_criteria | 模板拼接："给定…当执行X时…" | 不是真正的验收标准，只是占位文本 | 验收标准形同虚设，无法指导测试断言 |
| test_mapping_hints | 模板拼接："验证X的正向流程" | 太笼统，对测试生成没有实际价值 | 测试点生成质量低 |
| input_data / output_result | 关键词匹配（"输入"、"输出"等） | 原文很少显式标注输入输出，大量字段漏抽 | 输入校验和预期结果测试缺失 |
| user_role | 正则匹配固定角色词 | 只能识别预定义的 6 个角色 | 权限测试点不完整 |

### 2.3 质量分数影响

由于上述字段质量问题，当前规则引擎输出的 RKM 在质量评估中表现：

- **字段完整率**：表面完整（模板填充了占位值），但实际有效内容不足
- **原子化合格率**：规则引擎按 section 一对一生成，未做原子化拆分
- **验收标准覆盖率**：100%（模板保证），但验收标准质量极低
- **测试映射覆盖率**：100%（模板保证），但映射提示过于笼统

---

## 3. 需求目标

### 3.1 核心目标

在规则引擎初拆的基础上，增加 LLM 字段增强环节，使每条 Requirement 的字段从"有值"提升为"高质量"。

### 3.2 设计原则

1. **规则保底，LLM 增强**：规则引擎先产出可追溯的 Requirement 骨架，LLM 在此基础上增强字段质量，不替代规则引擎。
2. **可追溯性不丢失**：LLM 增强不修改 `source_trace`、`requirement_id`、`domain_id`、`module_id`、`feature_id` 等追溯字段。
3. **可降级运行**：LLM 增强失败时，保留规则引擎的原始输出，不影响流水线整体执行。
4. **按需开关**：通过配置文件控制是否启用 LLM 增强，不强制依赖 LLM。
5. **合并策略明确**：LLM 输出与规则引擎输出按明确的合并规则融合，不盲目覆盖。

---

## 4. 改造后流程

### 4.1 整体流程

```text
原文
 ↓
[规则] Markdown 解析 → sections
 ↓
[规则] 层级识别 → Domain / Module / Feature
 ↓
[规则] Requirement 初拆 → 骨架 Requirement（保证可追溯性）
 ↓
[LLM] 字段增强 → 高质量 Requirement（本次新增）
 ↓
[规则] 关联关系识别 → dependency_graph
 ↓
[规则] 质量校验 → quality_report
 ↓
输出 RKM
```

### 4.2 字段增强在流水线中的位置

字段增强发生在 `build_rkm()` 函数内部，位于规则引擎拆解之后、关联关系识别之前：

```text
build_rkm() 内部流程:

1. resolve_hierarchy()          ← 不变
2. split_requirements()         ← 不变（规则引擎初拆）
3. enrich_requirements()        ← 新增（LLM 字段增强）
4. resolve_dependencies()       ← 不变
5. 组装 RKMData                 ← 不变
```

### 4.3 降级策略

```text
LLM 字段增强
    ↓ 成功
使用增强后的 Requirement
    ↓ 失败（LLM 不可用、返回格式错误、超时等）
保留规则引擎的原始 Requirement，在 build_warnings 中记录降级信息
```

---

## 5. 字段增强详细需求

### 5.1 增强范围

以下字段需要 LLM 增强，按优先级排序：

| 优先级 | 字段 | 增强目标 |
|---|---|---|
| P0 | description | 改写为完整的功能描述，包含主语、动作、对象和条件 |
| P0 | acceptance_criteria | 生成 Given-When-Then 格式的可验证验收标准 |
| P0 | test_mapping_hints | 生成具体的测试场景名称（正向、反向、边界） |
| P0 | business_rules | 从描述和原文中提炼所有业务约束，每条一个明确规则 |
| P1 | preconditions | 补充隐含的前置条件（如登录状态、数据存在性等） |
| P1 | main_flow | 拆分为有序的操作步骤，每步一个动作 |
| P1 | exception_flows | 补充原文隐含的异常场景（网络超时、并发冲突、权限不足等） |
| P1 | input_data | 明确输入字段名称和约束 |
| P1 | output_result | 明确输出结果、提示信息和数据变化 |
| P2 | user_role | 识别操作角色，不限于预定义的 6 个角色 |
| P2 | trigger | 明确触发动作 |
| P2 | state_changes | 补充隐含的状态变化 |

### 5.2 不增强的字段

以下字段由规则引擎生成，LLM 不修改，保证可追溯性：

| 字段 | 原因 |
|---|---|
| requirement_id | 编号由系统生成，不可变 |
| domain_id / module_id / feature_id | 层级归属由层级识别器决定 |
| source_trace | 来源追溯信息必须与原文一致 |
| version | 版本号由配置决定 |
| status | 状态由来源可信度决定 |
| priority | 优先级由规则引擎根据状态变化和异常流程判断 |

### 5.3 合并策略

LLM 增强输出与规则引擎原始输出的合并规则：

| 场景 | 合并规则 |
|---|---|
| 规则引擎字段为空，LLM 有值 | 使用 LLM 输出 |
| 规则引擎有值，LLM 也有值 | 使用 LLM 输出（LLM 质量更高） |
| LLM 未返回该字段或返回空 | 保留规则引擎原始值 |
| LLM 返回格式错误 | 整条 Requirement 保留规则引擎原始值 |

### 5.4 增强粒度

- **逐条增强**：每次 LLM 调用处理一条 Requirement，避免批量处理导致上下文过长或字段混淆。
- **携带原文上下文**：每次调用时将 Requirement 对应的原文片段（source_trace.quote）一并传入，确保 LLM 基于原文增强而非凭空编造。

---

## 6. LLM 提示词设计

### 6.1 字段增强提示词

```text
你是资深测试需求分析专家。请对以下 Requirement 草稿进行字段增强。

## 原始 Requirement
- 标题: {title}
- 描述: {description}
- 原文片段: {source_quote}
- 已抽取的业务规则: {business_rules}
- 已抽取的异常流程: {exception_flows}
- 已抽取的状态变化: {state_changes}
- 已抽取的前置条件: {preconditions}
- 已抽取的主流程: {main_flow}
- 已抽取的输入数据: {input_data}
- 已抽取的输出结果: {output_result}

## 增强要求

请输出增强后的 JSON 对象，包含以下字段：

1. description: 用一句话准确描述功能行为，必须包含主语（谁）、动作（做什么）、对象（对什么）和条件（在什么条件下）。如果原文信息不足，基于原文片段合理推断，无法推断的部分标记到 unresolved。

2. preconditions: 列出所有前置条件，包括：
   - 原文明确提到的前置条件
   - 隐含的前置条件（如用户已登录、数据已存在、系统正常运行等）
   - 每条前置条件应可独立验证

3. main_flow: 将功能拆分为有序的操作步骤，要求：
   - 每步只包含一个动作
   - 步骤之间有明确的先后顺序
   - 包含系统响应和用户操作

4. exception_flows: 补充异常场景，包括：
   - 原文明确提到的异常
   - 隐含的异常（如网络超时、数据不存在、并发冲突、权限不足、输入非法等）
   - 每条异常应说明触发条件和系统响应

5. business_rules: 从描述和原文中提炼所有业务约束，要求：
   - 每条规则是一个独立的、可判断真假的约束
   - 包含计算规则、校验规则、权限规则、状态约束等
   - 不要使用"原文未明确业务规则"作为占位

6. acceptance_criteria: 用 Given-When-Then 格式写出可验证的验收标准，要求：
   - 至少包含一条正向验收标准
   - 至少包含一条反向验收标准（如果存在异常场景）
   - Given 部分说明前置条件，When 部分说明操作，Then 部分说明预期结果

7. test_mapping_hints: 列出具体的测试场景名称，要求：
   - 包含正向场景、反向场景和边界场景
   - 每个场景名称应具体明确，不要使用"验证X的正向流程"这类笼统描述
   - 示例："正常取消待支付订单"、"已支付订单取消失败"、"非本人订单取消失败"

8. input_data: 明确输入字段，包括字段名称和约束条件

9. output_result: 明确输出结果，包括返回值、提示信息、数据变化

10. user_role: 识别操作该功能的用户角色

11. trigger: 明确触发动作

12. state_changes: 补充状态变化，使用 "状态A -> 状态B" 格式

13. unresolved: 原文信息不足、无法确定的字段列表

## 输出格式

只输出 JSON 对象，不要输出 Markdown、解释或代码块。
```

### 6.2 提示词设计原则

| 原则 | 说明 |
|---|---|
| 携带原文 | 每次调用都传入 source_quote，防止 LLM 编造原文外的需求 |
| 携带规则引擎输出 | 将规则引擎已抽取的字段作为参考传入，LLM 在此基础上补充而非从零开始 |
| 明确输出格式 | 要求 JSON 对象，字段名与 Requirement 模型一致 |
| 给出示例 | 对 test_mapping_hints 等字段给出正反示例，引导 LLM 输出质量 |
| 允许 unresolved | 明确告诉 LLM 信息不足时写入 unresolved，而非编造 |

---

## 7. 技术实现要求

### 7.1 新增文件

| 文件路径 | 说明 |
|---|---|
| `rkm/builder/llm_enricher.py` | LLM 字段增强器，包含提示词构建、LLM 调用、结果解析和合并逻辑 |

### 7.2 修改文件

| 文件路径 | 修改内容 |
|---|---|
| `rkm/builder/rkm_builder.py` | 在 `build_rkm()` 中，规则引擎拆解后调用字段增强 |
| `rkm/config/schema.py` | `LLMConfig` 中新增 `enrich_fields` 开关字段 |

### 7.3 核心接口

```python
# rkm/builder/llm_enricher.py

def enrich_requirements(
    requirements: list[Requirement],
    documents: list[ParsedDocument],
    llm_config: LLMConfig,
    llm_client: LLMClient | None = None,
) -> list[Requirement]:
    """
    对规则引擎产出的 Requirement 列表进行 LLM 字段增强。

    参数说明:
        requirements: 规则引擎拆解产出的 Requirement 列表。
        documents: 原始解析文档，用于获取原文片段。
        llm_config: LLM 配置。
        llm_client: 可注入的 LLM 客户端，用于测试。

    返回值:
        list[Requirement]: 增强后的 Requirement 列表。
        单条增强失败时保留原始值，不影响其他 Requirement。
    """
```

### 7.4 单条增强流程

```text
输入: 一条 Requirement + 对应的原文片段
  ↓
构建增强提示词（填入 Requirement 各字段 + 原文）
  ↓
调用 LLM 获取增强结果
  ↓
解析 LLM JSON 响应
  ↓
按合并策略合并字段
  ↓
输出: 增强后的 Requirement
```

### 7.5 错误处理

| 异常场景 | 处理方式 |
|---|---|
| LLM 调用超时或网络错误 | 跳过当前 Requirement，保留原始值，记录 warning |
| LLM 返回非法 JSON | 跳过当前 Requirement，保留原始值，记录 warning |
| LLM 返回字段类型错误（如数组字段返回字符串） | 使用 `_normalize_llm_draft()` 归一化后重试，仍失败则保留原始值 |
| LLM 返回空对象 | 保留原始值 |
| 全部 Requirement 增强均失败 | 整体降级为规则引擎输出，在 `build_warnings` 中记录 |

### 7.6 配置扩展

在 `LLMConfig` 中新增字段：

```python
class LLMConfig(BaseModel):
    enabled: bool = False
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 4096
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    enrich_fields: bool = True    # 新增：是否启用 LLM 字段增强，默认开启
```

配置文件示例：

```yaml
build:
  llm:
    enabled: true
    model: "gpt-4o-mini"
    temperature: 0.2
    max_tokens: 4096
    enrich_fields: true     # 启用字段增强
```

当 `llm.enabled = true` 且 `llm.enrich_fields = true` 时，执行字段增强。
当 `llm.enabled = true` 但 `llm.enrich_fields = false` 时，仅执行 LLM 拆解（现有逻辑），不做字段增强。
当 `llm.enabled = false` 时，所有 LLM 功能关闭，纯规则引擎运行。

---

## 8. build_rkm 改造后的内部流程

```python
def build_rkm(sections, project_config, llm_config=None, llm_client=None):
    # 1. 层级识别（不变）
    domains, modules, features, section_mapping = resolve_hierarchy(sections, project_config)

    # 2. Requirement 拆解（不变）
    requirements = []
    build_warnings = []

    if llm_config and llm_config.enabled:
        # 2a. 优先 LLM 拆解（现有逻辑）
        try:
            requirements = split_requirements_with_llm(...)
        except Exception as exc:
            build_warnings.append(f"llm_fallback: ...")

    if not requirements:
        # 2b. 降级为规则引擎拆解（现有逻辑）
        requirements = split_requirements(sections, project_config, section_mapping)

    # 3. LLM 字段增强（新增）
    if llm_config and llm_config.enabled and llm_config.enrich_fields:
        try:
            requirements = enrich_requirements(
                requirements, sections, llm_config, llm_client
            )
        except Exception as exc:
            build_warnings.append(f"enrich_fallback: LLM 字段增强失败，保留规则引擎输出。error={exc}")

    # 4. 关联关系识别（不变）
    dependency_graph = resolve_dependencies(requirements)

    # 5. 组装 RKMData（不变）
    ...
```

**关键设计**：LLM 拆解（步骤 2a）和 LLM 字段增强（步骤 3）是两个独立环节。即使 LLM 拆解失败降级为规则引擎，字段增强仍可对规则引擎的输出执行。

---

## 9. 质量预期

### 9.1 字段质量对比

| 字段 | 规则引擎输出示例 | LLM 增强后预期输出 |
|---|---|---|
| description | "用户可以取消处于待支付状态的订单" | "普通用户在订单处于待支付状态时，可以通过订单详情页取消订单，取消后订单状态变更为已取消且不可恢复" |
| acceptance_criteria | "给定满足前置条件，当执行取消订单时，则应符合需求描述：用户可以取消…" | ["给定订单状态为待支付且用户为订单创建人，当用户点击取消订单时，则订单状态变为已取消", "给定订单状态为已支付，当用户点击取消订单时，则系统拒绝操作并提示'已支付订单不可取消'"] |
| test_mapping_hints | ["验证取消订单的正向流程"] | ["正常取消待支付订单", "已支付订单取消失败", "非本人订单取消失败", "订单不存在时取消失败", "并发取消同一订单"] |
| business_rules | ["仅待支付订单允许取消"] | ["仅待支付状态的订单允许取消", "只有订单创建人可以取消订单", "取消操作不可逆，取消后无法恢复"] |
| exception_flows | ["订单不存在时返回错误提示"] | ["订单不存在时返回错误提示", "订单状态非待支付时拒绝取消并提示原因", "网络超时导致取消请求失败时保持原状态", "并发取消同一订单时仅首次请求成功"] |

### 9.2 质量分数预期提升

| 指标 | 规则引擎 | LLM 增强后预期 |
|---|---|---|
| 字段完整率 | ~95%（模板填充） | ~98%（LLM 补全隐含字段） |
| 原子化合格率 | ~85% | ~92%（LLM 辅助判断） |
| 验收标准质量 | 低（模板占位） | 高（Given-When-Then 格式） |
| 测试映射质量 | 低（笼统描述） | 高（具体场景名称） |
| 综合质量分数 | ~0.75-0.85 | ~0.90-0.95 |

---

## 10. 验收标准

### 10.1 功能验收

- 启用 LLM 字段增强后，每条 Requirement 的 description、acceptance_criteria、test_mapping_hints、business_rules 字段质量明显优于规则引擎输出。
- acceptance_criteria 使用 Given-When-Then 格式，可直接作为测试断言参考。
- test_mapping_hints 包含具体的测试场景名称，而非笼统的"验证X的正向流程"。
- exception_flows 包含原文隐含的异常场景（如网络超时、并发冲突等）。
- LLM 增强失败时，保留规则引擎原始输出，流水线不中断。
- `build_warnings` 中记录了每条增强失败的 Requirement 及原因。

### 10.2 降级验收

- LLM 不可用时（API Key 缺失、网络不通等），字段增强自动跳过，输出与纯规则引擎一致。
- 单条 Requirement 增强失败不影响其他 Requirement 的增强。
- `enrich_fields: false` 配置可正确关闭字段增强。

### 10.3 可追溯性验收

- LLM 增强不修改 requirement_id、source_trace、domain_id、module_id、feature_id。
- 增强后的 Requirement 仍可通过 source_trace 追溯到原文位置。

### 10.4 质量分数验收

- 同一份输入文档，LLM 增强后的 quality_score 高于纯规则引擎输出。
- acceptance_criteria 和 test_mapping_hints 的人工评审质量明显提升。

---

## 11. 后续扩展方向（不在当前版本范围）

以下能力不在当前版本实现，但架构设计应预留扩展空间：

| 扩展方向 | 说明 |
|---|---|
| LLM 关联识别增强 | 用 LLM 替代纯文本重叠匹配，进行语义级依赖分析 |
| LLM 质量审查 | 在 validate_rkm 之后增加 LLM 审查环节，发现人工容易遗漏的问题 |
| LLM 层级识别增强 | 用 LLM 辅助 Domain/Module/Feature 划分，改善按标题硬切的准确性问题 |
| 批量增强优化 | 当 Requirement 数量较多时，支持批量调用 LLM 以减少请求次数 |
| 增强结果缓存 | 对相同输入缓存 LLM 增强结果，避免重复调用 |
