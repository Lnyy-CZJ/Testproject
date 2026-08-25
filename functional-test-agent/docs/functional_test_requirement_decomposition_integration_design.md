# functional_test 接入 requirement_decomposition 详细设计

> 文档版本: v1.0
> 创建日期: 2026-06-19
> 状态: 已确认实施

## 1. 需求理解

当前 `functional_test` 的测试点生成流程直接消费原始需求文档，容易遗漏业务规则、异常流程、权限、状态流转和不确定项。`requirement_decomposition` 已经能够把原始需求拆解为结构化 Requirement，并输出按功能聚合的 `test_seeds`。

本次目标是在不重构现有测试点/测试用例工作流的前提下，将 `requirement_decomposition` 作为测试点生成前置增强环节，让测试点生成和测试点覆盖校验优先消费结构化 `test_seed` 上下文。

## 2. 成功标准

- 传入 `document_path` 时，测试点生成前自动执行 `requirement_decomposition.run_decomposition()`。
- 拆解成功且返回 `test_seeds` 时，测试点生成、测试点覆盖校验、缺失测试点补充均优先使用结构化上下文。
- 拆解失败、缺少 `document_path` 或没有 `test_seeds` 时，自动降级为原始需求文档流程。
- 人工测试点 `test_points_path` 的行为保持不变，仍跳过测试点生成。
- 至少有单元测试覆盖 `test_seed` 上下文构造、上下文优先级和拆解失败降级。

## 3. 影响范围

### 需要修改

- `agents/functional_test/workflows/case_generator_workflow.py`
  - 增加 `document_path`、`requirement_context` 等状态字段。
  - 增加 test_seed 到 LLM 上下文的格式化函数。
  - 增加基于 `document_path` 的需求拆解准备函数。
  - 修改 `build_requirement_context()`，优先返回结构化上下文。
  - 修改主流程获取测试点逻辑，向测试点子流程透传结构化上下文。

- `agents/common/tools/tools.py`
  - 读取文档后保留绝对 `document_path`。
  - 调用 workflow 时透传 `document_path`。

- `agents/functional_test/prompts/generator_test_point.py`
  - 明确当需求输入是结构化 `test_seed` 上下文时的生成规则。

- `agents/functional_test/prompts/verify_test_points_coverage.py`
  - 明确覆盖校验应检查结构化上下文中的对象、约束、权限、状态流转和预期结果。

### 需要新增

- `tests/functional_test/test_requirement_decomposition_integration.py`
  - 覆盖上下文构造、优先级和失败降级。

## 4. 方案设计

### 4.1 接入点

使用 `build_requirement_context(state)` 作为核心接入口。该函数当前直接返回 `state["document"]`，且已有注释说明后续接入结构化需求。将其调整为:

1. 如果 `state["requirement_context"]` 存在，返回结构化上下文。
2. 否则返回原始 `state["document"]`。

这样无需改动测试点生成、覆盖校验、补充测试点的每个 Prompt 调用点，它们会自然获得新的上下文。

### 4.2 拆解触发条件

只在有本地 `document_path` 时触发拆解:

- `requirement_decomposition.run_decomposition()` 当前以文件路径为入口。
- 对纯文本 `document` 不创建临时文件，避免额外文件生成和隐式副作用。
- 如果调用方只传 `document`，保持原流程。

### 4.3 数据映射

`DecompositionResult.test_seeds` 转换为面向测试点生成的文本上下文，每个 seed 包含:

- 模块、功能、需求 ID、来源 section
- 需求标题
- 测试对象
- 前置条件
- 业务约束
- 权限规则
- 有效/无效状态流转
- 风险标签
- 预期结果
- 负向建议
- 不确定项
- 证据摘要和状态标签

约束: `uncertain_items` 只能作为“需确认/建议类测试方向”，不能当作确认事实。

### 4.4 失败降级

需求拆解失败时不阻断 `functional_test`:

- 记录 writer 日志。
- 返回空 `requirement_context`。
- `build_requirement_context()` 自动回退原始文档。

原因: 当前 `functional_test` 是可用主链路，结构化拆解是质量增强，不应因为 LLM 拆解失败导致测试点生成完全不可用。

## 5. 风险与缓解

- 风险: `requirement_decomposition.yaml` 输出路径固定，可能覆盖历史中间产物。
  - 缓解: workflow 直接消费 `run_decomposition()` 返回对象，不依赖磁盘输出文件。

- 风险: 结构化上下文过长。
  - 缓解: 只使用 `test_seeds` 的聚合字段，不传完整 Requirement 明细。

- 风险: 不确定项被模型误当作确认需求。
  - 缓解: prompt 和上下文中明确标识不确定项语义。

## 6. 验证方案

- 运行新增测试:
  - `python3 -m pytest tests/functional_test/test_requirement_decomposition_integration.py -q`

- 运行相关回归:
  - `python3 -m pytest tests/requirement_decomposition/test_llm_only_pipeline.py tests/functional_test/test_requirement_decomposition_integration.py -q`

- 编译检查:
  - `python3 -m compileall agents/functional_test agents/common requirement_decomposition tests/functional_test -q`
