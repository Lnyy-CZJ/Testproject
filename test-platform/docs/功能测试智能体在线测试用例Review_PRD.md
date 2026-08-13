# 功能测试智能体在线测试用例 Review 与 AI 辅助 Review PRD

> 文档版本：V1.1  
> 创建日期：2026-08-13  
> 文档状态：已评审（第 24 章 16 项决策全部确认）  
> 修订记录：V1.1（2026-08-13）确认全部评审项，作为详细设计和实施基线  
> 产品阶段：功能测试智能体 Review 能力第二阶段  
> 适用工具：功能测试智能体 `/functional-test-agent/`  
> 关联任务状态：`waiting_case_review`  
> 需求定位：复用在线测试点 Review 的文件版本、CAS、AI 建议和共享 FIFO 能力，为生成后的功能测试用例提供在线人工 Review 与 AI 辅助 Review

关联基线文档：

- `test-platform/docs/AI测试智能体独立接入PRD.md`；
- `test-platform/docs/AI测试智能体独立接入开发设计与计划.md`；
- `test-platform/docs/功能测试智能体在线测试点Review_PRD.md`；
- `test-platform/docs/功能测试智能体在线测试点Review_开发设计与计划.md`。

本文档是在线测试点 Review 的增量产品需求。测试点 Review 的安全边界、文件任务架构、权限体系、单槽持久化 FIFO 和 JSON 权威格式继续有效；本期不重新建设第二套任务系统，也不改变原智能体 CLI 和历史 `output/`。

---

## 1. 文档目的

功能测试任务目前在测试点确认后生成测试用例 JSON 和 XLSX，并直接进入成功状态。用户如果发现用例名称、前置条件、步骤、测试数据或预期结果不合理，只能下载文件后在外部修改，修改结果不能回到同一任务形成可追溯的最终确认版本，也无法在任务上下文中安全地调用 LLM 补全或改写。

本 PRD 定义生成测试用例后的第二个 Review 关口：

```text
需求文档
  → 测试点生成
  → 在线测试点 Review
  → 测试用例生成
  → 在线测试用例 Review
  → 最终 JSON/XLSX 产物
```

用户可以直接在 Web 页面审核和修改测试用例，并可请求 AI 生成补充建议或改写建议。AI 仍只产生建议，必须经过人工选择、显式保存和最终确认，不能直接覆盖权威数据。

---

## 2. 可行性与复用结论

### 2.1 是否可以使用同一套逻辑快速实现

可以。预计约 **70%～80% 的底层能力可直接复用**，无需整体重构：

| 能力 | 复用结论 | 说明 |
|---|---|---|
| 任务所有权、RBAC、CSRF、IDOR 404 | 直接复用 | 权限规则与测试点 Review 相同 |
| JSON 原稿、草稿、确认版本隔离 | 直接复用 | 文件名和 Schema 改为测试用例 |
| revision + SHA CAS | 直接复用 | 防止双标签页静默覆盖 |
| 原子写入、不可变版本、索引恢复 | 直接复用 | 复用公共 Review 存储引擎 |
| 下载、上传和高级 JSON 入口 | 直接复用 | 使用独立测试用例路由和白名单 |
| AI 请求、建议文件、幂等和取消 | 直接复用 | 使用独立 Prompt 和用例建议 Schema |
| 单槽持久化 FIFO、execution sequence | 直接复用 | execution kind 增加 `case_review_ai` |
| AI 失败后返回 Review | 直接复用 | 返回 `waiting_case_review` |
| 页面筛选、分页、dirty 状态、离开确认 | 直接复用 | 页面结构按用例复杂度调整 |
| 数据 Schema 与校验 | 需要扩展 | 用例包含数组、对象和引用关系 |
| 编辑界面 | 需要专门设计 | 不适合把所有字段塞进一行表格 |
| 覆盖完整性 | 需要新增 | 必须校验确认测试点与用例映射 |
| 最终 XLSX 发布 | 需要新增 | 应从确认 JSON 重新生成，避免内容不一致 |

### 2.2 复杂度判断

综合复杂度为**中等**，明显低于首次建设测试点在线 Review。

主要新增复杂度来自：

1. `preconditions`、`test_steps` 是可排序列表，不是简单单元格；
2. `test_data` 可能是对象、数组或兼容旧字符串，需要安全编辑和往返；
3. `test_point_id` 必须引用本任务已确认的测试点；
4. 删除用例后可能造成某个确认测试点无任何用例覆盖；
5. AI 改写必须保持 `case_id`、`test_point_id` 和需求事实不变；
6. 最终 JSON 与 XLSX 必须由同一个确认版本生成。

### 2.3 推荐实施策略

不复制一份测试点 Review 代码后分别维护，而是把现有 Review 内核抽象为轻量资源策略：

```text
ReviewEngine
├── TestPointReviewPolicy
└── TestCaseReviewPolicy
```

公共引擎只处理：文件版本、CAS、原子发布、确认版本、AI 请求、队列和恢复；资源策略处理：Schema、规范化、校验、diff、文件命名和 AI 建议规则。

该调整仅限 Review 公共能力，不重构原测试点生成、测试用例生成和 CLI 工作流。

---

## 3. 产品目标

### 3.1 总体目标

在功能测试用例生成完成后提供桌面端在线 Review 工作台，使测试工程师能够：

- 结构化查看和编辑测试用例；
- 调整前置条件、步骤、数据和预期结果；
- 发现缺失覆盖、重复用例和引用错误；
- 使用 AI 补全或改写用例建议；
- 确认不可变最终版本并下载一致的 JSON/XLSX。

### 3.2 成功标准

上线后必须满足：

1. 生成测试用例后，任务进入 `waiting_case_review`，而不是直接成功；
2. 普通用户可以在 Web 页面直接编辑自己任务的测试用例；
3. 原始用例、可变草稿、AI 建议和确认版本隔离保存；
4. 支持用例增删复制、字段编辑、步骤增删排序和测试数据编辑；
5. 确认时保证 `case_id` 唯一、`test_point_id` 有效且确认测试点均有用例覆盖；
6. AI 只能生成建议，不能自动覆盖草稿、删除人工用例或确认版本；
7. AI 辅助与现有测试点 AI Review、正式生成共享同一个运行槽位和 FIFO；
8. 最终 JSON 和 XLSX 必须来自同一个不可变确认版本；
9. revision 冲突不能造成静默覆盖，用户可下载本地未保存副本；
10. 关闭功能开关时，原有直接生成 JSON/XLSX 的流程继续可用；
11. 不新增测试用例业务数据库表；
12. 不改变 API 测试智能体的安全边界。

### 3.3 建议量化指标

| 指标 | 目标 |
|---|---:|
| 草稿保存成功率 | ≥ 99%（排除网络、权限和存储故障） |
| revision 静默覆盖次数 | 0 |
| 非法引用在确认前拦截率 | 100% |
| 确认 JSON 与 XLSX 内容一致率 | 100% |
| 100 条用例首屏可交互时间 | ≤ 2 秒 |
| 500 条用例筛选反馈 | ≤ 300 毫秒 |
| 2,000 条用例服务端完整校验 | ≤ 2 秒 |
| AI 建议自动写入草稿次数 | 0 |

---

## 4. 用户与核心场景

### 4.1 目标用户

| 用户 | 核心诉求 |
|---|---|
| 测试工程师 | 修正步骤、数据和预期结果，补充遗漏用例 |
| 测试负责人 | 检查测试点覆盖、优先级和重复用例，确认最终版本 |
| 平台管理员 | 在授权范围内协助排查 Review、队列和文件问题 |
| 只读用户 | 查看已确认用例和元数据，但不能修改或发起 AI |

### 4.2 核心用户故事

1. 作为测试工程师，我希望在浏览器中修改测试步骤，无需下载 Excel 再上传。
2. 作为测试工程师，我希望给一个用例增加、删除或调整步骤顺序。
3. 作为测试负责人，我希望看到哪些测试点没有任何用例覆盖。
4. 作为测试负责人，我希望 AI 补充边界、异常和权限类用例，但必须由我决定是否采用。
5. 作为用户，我希望修改冲突时保留本地内容并下载副本，而不是被覆盖。
6. 作为高级用户，我希望继续下载或上传 JSON，以便批量处理和故障恢复。
7. 作为任务创建者，我希望最终 JSON 与 XLSX 都对应我确认的同一个版本。

---

## 5. 范围与非目标

### 5.1 本期范围

- 功能测试任务的 `waiting_case_review` 状态；
- 测试用例在线列表与详情编辑；
- 用例新增、复制、删除和批量删除；
- 前置条件和测试步骤的新增、删除、排序；
- 测试数据的结构化 JSON 编辑与安全文本兼容；
- 模块、功能、场景、测试点、优先级、错误和修改状态筛选；
- 测试点覆盖摘要和缺失覆盖定位；
- 确定性 Schema、引用、重复和覆盖校验；
- 草稿 revision/SHA CAS、原子保存和不可变确认版本；
- AI 补充、改写选中用例、按说明生成建议；
- AI 建议差异、逐条应用、显式保存；
- AI 共享 FIFO、取消、超时、失败和重启恢复；
- 最终确认 JSON 与 XLSX 重新发布；
- JSON 下载、上传兼容入口；
- 权限、CSRF、所有权、审计、脱敏和保留策略；
- dev/prod 功能开关与回滚路径。

### 5.2 明确非目标

本期不实现：

- 多人实时协同、光标同步、评论或审批会签；
- 测试用例业务数据库表或跨任务用例资产库；
- XMind、脑图或 Excel 的浏览器内原样编辑；
- 富文本编辑器、SPA、WebSocket、SSE；
- 开放式聊天机器人或任意多轮对话；
- AI 自动执行用例、访问测试目标或调用用户脚本；
- AI 自动覆盖草稿、自动确认、自动删除人工用例；
- 实际执行结果编辑和缺陷管理；
- 测试用例参数化执行引擎；
- 语义向量去重作为阻塞规则；
- 移动端适配；
- 修改已确认的历史版本；
- 改变需求拆解、测试点生成或原测试用例生成 Prompt 的既有语义。

---

## 6. 产品原则与关键决策

### 6.1 JSON 仍是权威格式

Web 页面只是测试用例 JSON 的结构化视图。草稿、SHA、确认版本、最终产物和故障恢复均以 UTF-8 JSON 为准。

XLSX 是确认 JSON 的派生产物，不是第二份权威数据，不能从 XLSX 反向覆盖确认 JSON。

### 6.2 四类数据严格隔离

```text
published/test-cases/generated-test-cases.json      # 模型原稿，只读
input/case-review-draft.json                        # 当前可变草稿
input/case-review-ai/suggestions-vN.json            # 不可变 AI 建议
input/review-test-cases-vN.json                     # 不可变确认版本
published/final-test-cases/vN/test-cases.json       # 最终发布 JSON
published/final-test-cases/vN/test-cases.xlsx       # 从同一确认 JSON 派生
```

- 模型原稿永不覆盖；
- 草稿可原子覆盖，并使用独立 revision；
- AI 建议不可变且不进入权威数据；
- 确认版本不可变；
- 最终 JSON/XLSX 必须携带同一确认版本和内容 SHA。

### 6.3 复用现有 Review 内核，但接口独立

测试点和测试用例使用同一套内部 ReviewEngine，但 HTTP 路由、文件名、配置开关和 AI Prompt 必须独立，避免资源类型混淆。

测试用例接口统一使用 `case-review`，不得通过客户端传入任意资源类型或文件路径。

### 6.4 普通用户默认使用结构化工作台

页面默认显示用例列表和详情编辑器。JSON 下载、导入与恢复操作收纳到高级区域。

不把嵌套步骤压缩进超宽表格的一行中，推荐采用“左侧/上方列表 + 右侧/下方详情编辑面板”的桌面工作台结构。

### 6.5 保存草稿允许业务错误，确认必须零阻塞错误

- 草稿保存允许必填字段为空、测试点暂时缺失覆盖等业务错误；
- JSON 结构不可解析、字段类型无法安全保留、总体大小超限时拒绝保存；
- 确认最终版本时所有阻塞错误必须清零；
- 非阻塞警告必须由用户显式确认。

### 6.6 AI 只产生建议

AI 建议必须经过：

```text
保存草稿
  → 发起 AI
  → AI 建议文件
  → 差异预览
  → 人工选择应用
  → 浏览器 dirty 状态
  → 显式保存草稿
  → 人工确认最终版本
```

任何 AI 接口都不能直接写 `case-review-draft.json` 或 `review-test-cases-vN.json`。

### 6.7 最终确认不重新调用 LLM

用户确认后只执行确定性的：

1. 服务端校验；
2. 不可变 JSON 发布；
3. XLSX 转换；
4. artifact 登记；
5. 任务完成状态提交。

不得在确认阶段再次调用 LLM，避免用户看到的内容与最终产物不同。

### 6.8 与测试点的引用关系不可破坏

每条测试用例必须引用当前任务已确认测试点版本中的 `test_point_id`。页面可修改引用，但只能从该确认测试点集合中选择。

默认要求每个确认测试点至少存在一条测试用例。缺失覆盖是阻塞错误，防止用户误删后仍确认成功。

---

## 7. 状态机与任务流程

### 7.1 开关启用时

```text
pending/generate_cases
  → running/generating_test_cases
  → waiting_case_review/case_review_editing

waiting_case_review/*
  → pending/case_review_ai_queued
  → running/case_review_ai_running
  → waiting_case_review/case_review_ai_ready|failed|cancelled

waiting_case_review/*
  → succeeded/case_review_confirmed
```

### 7.2 开关关闭时

保持现有兼容行为：

```text
pending → running/generating_test_cases → succeeded
```

模型生成的 JSON/XLSX 继续作为最终产物，不要求用户进入用例 Review。

### 7.3 AI 共享 FIFO

`case_review_ai` 与以下执行共享同一个运行槽位和最多 5 个 pending 位：

- 初次功能任务；
- 测试点 AI Review；
- 测试点确认后的用例生成；
- 测试用例 AI Review。

排序仍使用 `queued_at + task_id`。AI 失败、取消、超时或重启中断必须返回 `waiting_case_review`，不能把主任务置为 `failed`。

### 7.4 最终确认与队列

推荐本期最终确认采用**受控同步发布**，不重新占用 LLM FIFO：

- JSON/XLSX 发布是本地确定性操作；
- 单任务最多 2,000 条用例、10 MiB，操作应在短请求上限内完成；
- 发布过程使用临时目录、`fsync`、原子重命名和首次终态生效保护；
- 发布失败时任务仍保持 `waiting_case_review`，草稿与确认文件保留，可幂等重试。

若详细设计实测 XLSX 转换无法满足请求时限，可将发布切换为同一 FIFO 的 `publish_test_cases` execution kind，但不得引入第二套队列。

---

## 8. 信息架构与页面设计

### 8.1 页面入口

入口位于现有功能任务详情页：

```text
/functional-test-agent/tasks/{task_id}#case-review
```

当状态为 `waiting_case_review` 时，主操作显示“Review 测试用例”。其他状态只读展示确认摘要和最终产物。

### 8.2 页面顺序

1. 任务状态、测试点确认版本和下一步操作；
2. 用例 Review 摘要；
3. 覆盖情况和阻塞问题；
4. 筛选、分组和批量操作；
5. AI 辅助操作栏；
6. 用例列表；
7. 当前用例详情编辑面板；
8. AI 建议差异面板；
9. 保存草稿、确认最终版本；
10. 高级 JSON 操作；
11. 原测试点、日志、模型和 Prompt 版本信息。

### 8.3 用例列表

列表只展示适合快速浏览的字段：

| 列 | 说明 |
|---|---|
| 选择 | 批量删除或 AI 改写 |
| Case ID | 用例唯一标识 |
| Test Point ID | 来源测试点，可点击查看测试点摘要 |
| 模块/功能 | 上下文 |
| 用例名称 | 主要识别字段 |
| 优先级 | `P0/P1/P2/P3` |
| 步骤数 | 快速判断完整度 |
| 状态 | 新增、修改、错误、警告、未修改 |
| 操作 | 复制、删除、打开详情 |

默认每页 50 条，可选择 25/50/100。浏览器最多同时渲染 100 条用例列表，不一次生成 2,000 个详情表单。

### 8.4 用例详情编辑器

选中一条用例后编辑：

- `case_id`；
- `test_point_id` 下拉选择；
- 模块、功能、场景；
- 用例名称；
- 优先级；
- 前置条件列表；
- 测试步骤列表；
- 测试数据；
- 预期结果；
- 扩展字段只读摘要。

`actual_result` 不属于设计期测试用例 Review，页面只读展示或隐藏，AI 不得修改。若原始值非空，确认时保留原值并给出警告。

### 8.5 步骤编辑

前置条件和测试步骤支持：

- 新增一项；
- 删除一项；
- 上移、下移；
- 多行粘贴时按换行拆分，拆分前显示预览；
- 空项即时标记；
- 不依赖拖拽，确保键盘可操作。

本期不引入复杂拖拽组件。

### 8.6 测试数据编辑

优先使用安全 JSON 对象编辑区：

- 对象或数组以格式化 JSON 文本显示；
- 保存时使用安全 `JSON.parse`，不执行表达式；
- 旧数据为普通字符串时以字符串模式显示并原样保留；
- 用户可明确切换“结构化 JSON/纯文本”，切换前必须确认；
- 不使用 `eval`、`Function` 或动态脚本。

### 8.7 筛选与分组

支持：

- 关键字：ID、名称、预期结果；
- 模块、功能、场景；
- 测试点 ID；
- 优先级；
- 只看错误；
- 只看警告；
- 只看已修改；
- 只看未覆盖/覆盖异常；
- 按模块或测试点分组折叠；
- 一键清除筛选。

筛选只影响显示，不改变保存顺序。

### 8.8 覆盖摘要

页面持续展示：

- 已确认测试点数量；
- 用例总数；
- 已覆盖测试点数；
- 未覆盖测试点数；
- 新增、修改、删除用例数；
- 错误和警告数；
- 当前草稿 revision。

点击未覆盖数量后自动筛选并定位对应测试点。

---

## 9. 测试用例数据模型

### 9.1 标准对象

```json
{
  "case_id": "TC001",
  "test_point_id": "TP001",
  "module": "登录",
  "feature": "密码登录",
  "scenario": "用户名",
  "case_name": "用户名为空时登录失败",
  "priority": "P1",
  "preconditions": [
    "用户进入登录页面"
  ],
  "test_steps": [
    "用户名保持为空",
    "输入有效密码",
    "点击登录按钮"
  ],
  "test_data": {
    "username": "",
    "password": "Test123456"
  },
  "expected_result": "系统提示用户名不能为空，登录失败",
  "actual_result": ""
}
```

### 9.2 兼容性规范化

现有历史数据可能存在字段类型差异。加载 Review 时按以下规则兼容：

- `preconditions`：数组保持；字符串转为单元素数组；空值转为空数组；
- `test_steps`：数组保持；多行字符串按换行解析为数组；
- `test_data`：对象、数组、字符串均允许；不自动执行或插值；
- `actual_result`：缺失时补空字符串；
- 未识别扩展字段原样往返；
- 模型原始 JSON 不被改写，规范化只进入草稿和确认版本。

### 9.3 字段限制

| 字段 | 限制 |
|---|---|
| `case_id` | 必填，最长 64，任务内唯一 |
| `test_point_id` | 必填，必须引用确认测试点 |
| `module` | 必填，最长 200 |
| `feature` | 必填，最长 200 |
| `scenario` | 必填，最长 500 |
| `case_name` | 必填，最长 500 |
| `priority` | `P0/P1/P2/P3` |
| `preconditions` | 最多 50 项，单项最长 1,000 |
| `test_steps` | 1～100 项，单项最长 2,000 |
| `test_data` | 规范化后最长 20,000 字符 |
| `expected_result` | 必填，最长 4,000 |
| `actual_result` | 最长 4,000，设计期不编辑 |

任务级限制：

- 最多 2,000 条测试用例；
- 规范化 JSON 最大 10 MiB；
- 解码后最大 1,000,000 字符；
- 单次 AI 建议最多 100 条；
- AI 改写最多选择 50 条。

---

## 10. 校验规则

### 10.1 阻塞错误

以下情况允许保存草稿，但禁止最终确认：

| 规则 | 定位 |
|---|---|
| 用例列表为空 | 页面级 |
| 用例数量超过 2,000 | 页面级 |
| JSON 大小或字符数超限 | 页面级 |
| 任一用例不是对象 | 行级 |
| `case_id` 为空、超长或重复 | 字段/冲突行 |
| `test_point_id` 为空或不存在于确认测试点 | 字段 |
| 任一确认测试点没有对应测试用例 | 覆盖摘要/测试点 |
| 模块、功能、场景、名称缺失或超长 | 字段 |
| 优先级不属于 `P0/P1/P2/P3` | 字段 |
| 测试步骤为空、包含空项或超过上限 | 步骤项 |
| 前置条件包含空项或超过上限 | 条件项 |
| 测试数据 JSON 模式下无法安全解析 | 字段 |
| 预期结果为空或超长 | 字段 |
| 完全重复用例 | 所有重复行 |
| 字段含 NUL 或无法编码 UTF-8 | 字段/页面级 |

### 10.2 完全重复定义

确定性重复键为以下字段规范化后的组合：

```text
test_point_id
+ case_name
+ preconditions
+ test_steps
+ test_data
+ expected_result
```

完全相同为阻塞错误。

以下情况只做警告：

- 不同测试点下用例名称相同；
- 同一测试点下用例名称相同但数据或预期不同；
- 用例名称或预期结果过短；
- `case_id` 不符合推荐格式 `TC` + 三位以上数字；
- 用例优先级低于来源测试点风险等级；
- 相对原稿删除超过 30%；
- 相对原稿新增超过 50%；
- 原始 `actual_result` 非空；
- 模块/功能/场景与来源测试点不同。

### 10.3 覆盖规则

- 每个确认测试点至少一条用例是阻塞要求；
- 一个用例只能引用一个 `test_point_id`；
- 允许一个测试点对应多条用例；
- 不要求用例 ID 与测试点 ID 存在固定数值关系；
- 不调用 LLM 判断覆盖是否充分，阻塞判断只基于引用完整性；
- AI 可给出“覆盖可能不足”的建议，但不能作为确定性阻塞错误。

### 10.4 保存与确认

- 客户端校验用于即时反馈；
- 服务端校验是最终依据；
- 保存草稿返回 `valid_for_confirm=false` 和完整问题；
- 确认时重新加载确认测试点版本并完整校验，禁止使用客户端缓存代替。

---

## 11. 人工 Review 功能

### 11.1 加载优先级

```text
当前草稿
  > 已发布但索引尚未恢复的确认文件
  > 模型生成原稿
```

只允许从 artifact registry 中登记的 `test_cases_json` 加载模型原稿，不扫描任意目录。

### 11.2 显式保存

保存请求携带完整用例列表、revision 和 SHA：

1. 校验请求结构与大小；
2. 校验服务端 revision/SHA；
3. 规范化用例；
4. 计算稳定 SHA；
5. 内容未变化时不增加 revision；
6. 写入临时文件并 `fsync`；
7. 原子替换草稿；
8. 更新 `task.json` 非正文索引；
9. 返回校验、diff 和覆盖摘要。

### 11.3 冲突处理

CAS 冲突时：

- 返回当前 revision、SHA、保存时间和保存人；
- 不返回对方正文；
- 页面保留本地编辑内容；
- 显示“下载本地副本”和“重新加载服务端版本”；
- 本期不做自动合并或三方合并。

### 11.4 确认最终版本

确认前置条件：

- 状态为 `waiting_case_review`；
- 当前 revision/SHA 一致；
- 阻塞错误为零；
- 警告已显式确认；
- 用户具备 `tool.execute` 和所有权；
- CSRF 通过。

确认过程：

1. 创建或复用 `review-test-cases-vN.json`；
2. 同 SHA 重试复用原版本；
3. 从确认 JSON 生成 JSON/XLSX 发布目录；
4. 计算两个 artifact SHA；
5. 原子发布并登记 artifact；
6. 写入 `task.json.case_review` 索引；
7. 首次合法提交任务 `succeeded/case_review_confirmed`；
8. 迟到 Runner 或重复请求不能覆盖终态。

发布失败时：

- 任务保持 `waiting_case_review`；
- 草稿和确认文件保留；
- 已完整发布的文件可在重试时按 SHA 复用；
- 不登记半写入 artifact；
- 返回稳定错误码，不返回路径或异常堆栈。

### 11.5 JSON 导入导出

高级区域支持：

- 下载模型原始用例 JSON；
- 下载当前用例草稿；
- 下载指定确认版本；
- 导入 JSON 为草稿；
- 下载冲突时浏览器本地副本。

导入只更新草稿，不直接确认。旧的最终 JSON/XLSX 下载链接继续保留至少一个发布周期。

---

## 12. AI 辅助 Review

### 12.1 三种操作

#### A. `supplement`

目的：补充确认测试点下遗漏的正向、异常、边界、权限或状态类用例。

规则：

- 只允许返回 `add` 建议；
- 新用例的 `test_point_id` 必须存在；
- 不得删除或替换现有用例；
- 建议 ID 不能与当前草稿冲突。

#### B. `rewrite_selected`

目的：改进选中用例的名称、前置条件、步骤、数据和预期结果。

规则：

- 最多选择 50 条；
- 只允许返回 `replace` 建议；
- 必须保持原 `case_id` 和 `test_point_id`；
- 不得降低优先级；
- 不得修改 `actual_result`；
- 不得把用户说明当作需求事实。

#### C. `generate_from_instruction`

目的：按用户指定的测试设计方向生成补充用例，例如“补充弱网恢复和重复提交场景”。

规则：

- 说明最多 2,000 字符；
- 只允许返回 `add` 建议；
- 说明是覆盖侧重点，不是需求事实；
- 无需求证据的结果必须标记“需确认”，不得伪装为确定需求。

### 12.2 AI 上下文

只允许读取当前任务：

- 需求原文；
- 需求拆解；
- 已确认测试点版本；
- 已保存用例草稿；
- 用户选择的作用域和说明；
- 当前配置快照中的模型信息。

不得读取：

- Secret、Client Token、数据库凭据；
- 其他任务；
- 历史 `output/`；
- 控制台日志；
- 测试目标；
- 用户本地文件系统任意路径。

### 12.3 上下文限制

- 最多 300 条用例上下文；
- 最多 300 条测试点摘要；
- 总字符数最多 120,000；
- 单次最多 100 条建议；
- 超限整体拒绝并要求用户缩小模块、测试点或选中项范围；
- 不静默截断导致错误建议。

### 12.4 AI 建议 Schema

```json
{
  "summary": "建议摘要",
  "suggestions": [
    {
      "suggestion_id": "CAS-001",
      "action": "add",
      "target_id": null,
      "case": {},
      "reason": "补充异常覆盖",
      "source_basis": "TP011：连续失败后的限制规则"
    }
  ]
}
```

只允许 `add/replace`。执行一次安全 JSON 修复后仍不合法时，整体失败为 `CASE_REVIEW_AI_RESPONSE_INVALID`。

### 12.5 建议应用

- 建议默认不选中；
- 页面显示新增或字段级前后差异；
- 用户逐条或批量选择；
- 应用只修改浏览器内存并标记 dirty；
- 若草稿 revision/SHA 已变化，禁止应用并提示重新生成；
- 应用后仍需显式保存；
- 保存后仍需最终确认。

### 12.6 AI 失败与恢复

以下情况均返回 `waiting_case_review` 并保留草稿：

- 模型限流；
- 超时；
- 用户取消；
- 非法输出；
- Runner 异常；
- 服务重启中断。

AI 子阶段不得写主任务 `finished_at`，不得清除原用例 artifact。

---

## 13. 文件与元数据

### 13.1 任务目录

```text
task.json
request.json
execution.json
artifacts.json
input/
├── review-test-points-vN.json
├── case-review-draft.json
├── review-test-cases-vN.json
└── case-review-ai/
    ├── request-vN.json
    └── suggestions-vN.json
published/
├── test-cases/generated-test-cases.json
└── final-test-cases/vN/
    ├── test-cases.json
    └── test-cases.xlsx
```

### 13.2 草稿信封

```json
{
  "schema_version": 1,
  "resource_type": "test_cases",
  "revision": 3,
  "content_sha256": "...",
  "base_generated_sha256": "...",
  "test_point_review_version": 2,
  "saved_by_user_id": "usr_xxx",
  "saved_by_username": "tester",
  "saved_at": "2026-08-13T10:00:00+08:00",
  "test_cases": []
}
```

### 13.3 `task.json` 索引

`task.json` 只保存恢复和展示所需元数据，不保存完整用例正文：

```json
{
  "case_review_draft": {
    "revision": 3,
    "sha256": "...",
    "case_count": 128,
    "error_count": 0,
    "warning_count": 4,
    "covered_test_point_count": 53,
    "saved_at": "..."
  },
  "case_review": {
    "version": 1,
    "sha256": "...",
    "case_count": 128,
    "source_revision": 3,
    "test_point_review_version": 2,
    "reviewed_by_user_id": "usr_xxx",
    "reviewed_at": "..."
  }
}
```

公共响应不得返回相对路径、绝对路径、原始模型响应、Prompt 全文或 Secret。

---

## 14. HTTP API

所有接口位于 `/functional-test-agent/api/v1`。

### 14.1 获取工作区

```http
GET /tasks/{task_id}/case-review
```

返回：任务状态、编辑权限、测试点摘要、原稿/草稿来源、revision、SHA、用例列表、校验、覆盖和 diff。

### 14.2 保存草稿

```http
PUT /tasks/{task_id}/case-review-draft
Content-Type: application/json
X-CSRF-Token: <token>
```

```json
{
  "revision": 3,
  "sha256": "...",
  "test_cases": []
}
```

成功返回新 revision、SHA、校验、覆盖和 diff。冲突返回 `CASE_REVIEW_REVISION_CONFLICT`。

### 14.3 导入 JSON

```http
POST /tasks/{task_id}/case-review-draft/import
Content-Type: multipart/form-data
```

只导入为草稿，不直接确认。

### 14.4 下载

```http
GET /tasks/{task_id}/case-review/download?kind=generated|draft|confirmed&version=1
```

只接受固定枚举和整数版本，不接受客户端路径。

### 14.5 确认最终版本

```http
POST /tasks/{task_id}/case-review/confirm
Content-Type: application/json
X-CSRF-Token: <token>
Idempotency-Key: <uuid>
```

```json
{
  "revision": 3,
  "sha256": "...",
  "accept_warnings": true
}
```

成功返回 200 和 `succeeded` 任务以及最终 artifacts。若详细设计改为异步发布，则返回 202，但协议字段保持兼容。

### 14.6 发起 AI

```http
POST /tasks/{task_id}/case-review-ai
```

```json
{
  "revision": 3,
  "sha256": "...",
  "operation": "rewrite_selected",
  "selected_ids": ["TC011", "TC012"],
  "scope": {"test_point_ids": ["TP004"]},
  "instruction": "步骤保持原子化，并明确每一步对应的可观察结果"
}
```

### 14.7 获取和取消 AI

```http
GET  /tasks/{task_id}/case-review-ai
POST /tasks/{task_id}/case-review-ai/cancel
```

取消只取消用例 AI 子阶段，不取消整个任务。

### 14.8 错误码

| HTTP | 错误码 | 场景 |
|---:|---|---|
| 404 | `TASK_NOT_FOUND` | 不存在或越权 |
| 409 | `INVALID_TASK_STATE` | 非 `waiting_case_review` 写入 |
| 409 | `CASE_REVIEW_REVISION_CONFLICT` | revision/SHA 冲突 |
| 409 | `CASE_REVIEW_DRAFT_REQUIRED` | 未保存草稿 |
| 409 | `CASE_REVIEW_WARNING_CONFIRMATION_REQUIRED` | 警告未确认 |
| 409 | `CASE_REVIEW_AI_ALREADY_RUNNING` | 已有 AI 子阶段 |
| 409 | `CASE_REVIEW_AI_BASE_CHANGED` | AI 基准已变化 |
| 409 | `CASE_REVIEW_AI_SCOPE_REQUIRED` | 上下文过大 |
| 409 | `QUEUE_FULL` | 共享队列已满 |
| 410 | `ARTIFACT_EXPIRED` | 文件已过期 |
| 413 | `UPLOAD_TOO_LARGE` | 超过限制 |
| 422 | `CASE_REVIEW_FILE_INVALID` | JSON 结构非法 |
| 422 | `CASE_REVIEW_VALIDATION_FAILED` | 存在阻塞错误 |
| 422 | `CASE_REVIEW_REFERENCE_INVALID` | 测试点引用无效 |
| 422 | `CASE_REVIEW_AI_RESPONSE_INVALID` | AI 输出非法 |
| 429 | `LLM_RATE_LIMITED` | 模型限流 |
| 503 | `FEATURE_DISABLED` | 功能未启用 |
| 504 | `LLM_TIMEOUT` | AI 超时 |
| 500 | `STORAGE_WRITE_FAILED` | 原子保存或发布失败 |

错误响应保持统一 `code/message/request_id/details`，`details` 只允许白名单化数量、revision、SHA 和容量信息。

---

## 15. 权限、安全与审计

### 15.1 权限

| 操作 | 权限 |
|---|---|
| 查看用例 Review | `tool.result.view` |
| 保存、导入、应用后确认 | `tool.execute` |
| 发起 AI | `tool.execute` |
| 取消 AI | `task.cancel` |
| 查看其他创建者任务 | `task.view.all` |

普通用户仅能访问自己创建的任务。越权与不存在统一 404。

### 15.2 安全要求

- 所有写操作执行可信身份、所有权、RBAC 和双提交 CSRF；
- JSON 仅安全解析，不执行脚本、表达式或模板；
- 用例正文写入 DOM 使用 `textContent/value`，禁止 `innerHTML`；
- AI 不执行步骤、不发送测试目标 HTTP 请求；
- AI Runner 使用最小环境变量，不获得 Client Token；
- Prompt 输入分隔需求事实、测试点、草稿和用户说明；
- 页面不展示 Prompt 全文、Secret、路径和 traceback；
- 下载通过固定枚举、containment 和 artifact 白名单；
- 文件名不直接使用用户输入路径片段。

### 15.3 审计事件

至少记录：

- `agent.case_review.draft.save`；
- `agent.case_review.import`；
- `agent.case_review.confirm`；
- `agent.case_review.ai.request`；
- `agent.case_review.ai.cancel`；
- `agent.case_review.ai.complete`；
- `agent.case_review.ai.fail`；
- `agent.case_review.download`。

审计只记录数量、revision、SHA、模型、Prompt SHA、操作类型、稳定错误码，不记录用例正文和用户说明原文。

---

## 16. 配置与默认值

建议新增迁移 `20260814_0012`，下接当前 `20260813_0011`：

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

发布规则：

- 配置目录默认全部关闭；
- dev Release 在自动化与浏览器验收后显式开启两个功能开关；
- prod 首次发布保持关闭；
- prod 完成真实任务验收后再发布开启 Release；
- 页面只能读取当前 `PLATFORM_RUNTIME_ENV`；
- 不增加新 Secret，复用功能智能体自己的 `LLM_API_KEY`；
- Prompt 和模型版本继续在普通用户页面展示。

API 智能体必须继续保持：

```text
API_EXECUTION_ENABLED=false
DATABASE_PERSIST_ENABLED=false
ALLOWED_TARGETS=[]
```

---

## 17. 非功能需求

### 17.1 性能

- 100 条用例首屏 ≤ 2 秒；
- 500 条筛选 ≤ 300 毫秒；
- 2,000 条完整服务端校验 ≤ 2 秒；
- 页面只渲染当前页列表和一个详情表单；
- diff 与重复校验使用 O(n) 索引；
- AI 不在 HTTP 请求内同步等待。

### 17.2 可靠性

- 草稿、确认版本、建议和最终发布必须原子写入；
- 损坏文件返回稳定错误并保留其他版本；
- 同 SHA 确认幂等；
- 发布 JSON 成功但 XLSX 失败时不能把任务标记成功；
- artifact registry 不能登记半成品；
- 服务重启后 `case_review_ai` 返回可恢复 Review；
- 迟到 execution sequence 不得覆盖新状态。

### 17.3 保留策略

沿用任务保留策略：

- 草稿、AI 建议、确认版本和最终产物按 artifact 90 天保留；
- 任务摘要 180 天；
- 到期前 7 天提示；
- `waiting_case_review` 不自动清理；
- 清理后保留任务摘要和“产物已过期”状态；
- 不处理历史 `output/`。

### 17.4 可访问性

- 全部操作可使用键盘；
- 步骤排序提供按钮，不只依赖拖拽；
- 焦点在保存、删除、切页后可预测恢复；
- 错误不只使用颜色；
- 对话框具备标题、焦点限制和取消路径；
- 支持 `prefers-reduced-motion`；
- 1280×800 和 1440×900 桌面分辨率可用。

---

## 18. 验收标准

### 18.1 人工 Review 主流程

1. 测试点确认后生成用例，任务进入 `waiting_case_review`；
2. 页面加载模型用例原稿；
3. 用户修改名称、步骤、数据和预期；
4. 用户新增、复制、删除用例；
5. 草稿显式保存并增加 revision；
6. 刷新后草稿内容完整恢复；
7. 确认后创建不可变版本；
8. 任务成功；
9. 下载 JSON/XLSX 内容与确认版本一致。

### 18.2 校验与覆盖

- 重复 `case_id` 阻塞；
- 无效 `test_point_id` 阻塞；
- 任一确认测试点无用例覆盖时阻塞；
- 空步骤、空预期和非法优先级阻塞；
- 完全重复用例阻塞；
- 名称相同但数据或预期不同只警告；
- 服务端问题能定位到用例和字段；
- 警告必须确认后才可最终发布。

### 18.3 CAS 与幂等

- 双标签页后保存者收到冲突；
- 本地编辑内容不丢失；
- 可下载本地副本；
- 相同正文不增加 revision；
- 相同 SHA 重复确认不创建新版本；
- 发布成功但索引失败后可从文件恢复；
- 迟到 Runner 不覆盖成功状态。

### 18.4 AI

- 三种操作均可排队；
- 建议默认未选中；
- AI 不自动写草稿；
- 改写保持 `case_id/test_point_id`；
- 补充和按说明生成只返回新增建议；
- 风险/优先级降级建议被拒绝；
- 基准 revision 变化后禁止应用；
- 取消、超时、非法输出和重启均回到 `waiting_case_review`；
- AI 不执行步骤、不访问真实 HTTP 目标。

### 18.5 权限与安全

- 创建者可编辑；
- 其他普通用户统一 404；
- 管理员具备 `task.view.all` 时可查看；
- 只读用户不能保存、确认或发起 AI；
- 缺少 CSRF 的写请求失败；
- Prompt、Secret、路径和 traceback 不回显；
- 下载路径穿越失败；
- API 智能体安全默认不变。

### 18.6 开关与回滚

- 在线用例 Review 关闭时恢复现有直接成功流程；
- AI 关闭时人工 Review 可继续；
- prod 默认关闭；
- 回退旧镜像后已生成 JSON/XLSX 仍可下载；
- 不删除草稿、建议和确认版本。

---

## 19. 测试要求

### 19.1 单元测试

- Schema 规范化和扩展字段往返；
- 字符串/数组步骤兼容；
- 测试数据对象、数组和字符串兼容；
- 稳定 SHA 和 O(n) diff；
- ID、引用、覆盖和重复规则；
- CAS、原子写入、确认不可变和索引恢复；
- JSON/XLSX 同源发布；
- 三种 AI 建议校验；
- AI 保留 ID、引用和优先级规则。

### 19.2 API 集成测试

- GET/PUT/import/download/confirm；
- AI request/get/cancel；
- 队列满、超时、取消和重启；
- Idempotency-Key；
- 所有权、RBAC、CSRF、IDOR；
- 大小、数量、UTF-8 和路径攻击；
- artifact 过期 410；
- 开关关闭兼容流程。

### 19.3 浏览器验收

在 1280×800 和 1440×900 验收：

- 加载、空、只读、未保存、保存中、保存失败；
- 列表、详情、步骤增删排序、测试数据编辑；
- 筛选、分组、分页和错误跳转；
- 双标签冲突和本地副本下载；
- AI 排队、运行、取消、失败、建议、应用和保存；
- 确认最终版本和 JSON/XLSX 下载；
- 键盘、焦点、对话框和 reduced-motion。

### 19.4 回归

必须执行：

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

真实模型或登录凭据不可用时可使用 Fake/Mock 和隔离身份验证边界，但不得降低安全开关。

---

## 20. 实施范围建议

### 20.1 `AItestcase_Agents`

建议最小增量：

- 将公共 Review 文件事务抽象为资源策略；
- 保持现有测试点 Review API 行为不变；
- 新增 TestCase Review Schema、校验和 diff policy；
- 增加 `case_review_ai` Prompt、Adapter 和 Runner 分支；
- 增加测试用例 Review 路由；
- 增加用例列表/详情工作台 JS/CSS；
- 让用例生成完成后按开关进入 `waiting_case_review`；
- 从确认 JSON 生成最终 JSON/XLSX；
- 增加领域、运行时、Web、AI 和发布测试。

不得修改：

- 既有测试点/用例 Prompt 语义；
- CLI 默认能力；
- 历史 `output/`；
- API 测试智能体执行安全边界。

### 20.2 `test-platform`

- 新增配置迁移 `20260814_0012`；
- dev 配置 Release 显式启用；
- prod 不创建开启 Release；
- 复用现有 `/functional-test-agent/` Nginx 路由，无新增服务；
- 若 10 MiB JSON 导入需要网关调整，单独评审上传上限；推荐继续限制单文件 5 MiB 导入，10 MiB 仅用于服务端草稿正文；
- 更新 README、部署和回滚说明；
- 不新增工具卡片、容器或数据库业务表。

---

## 21. 分阶段交付建议

### 第一阶段：人工在线用例 Review

- Schema 和兼容规范化；
- 草稿、确认版本、最终发布；
- 列表 + 详情编辑器；
- 覆盖、重复和引用校验；
- JSON 导入导出；
- 权限和浏览器验收。

### 第二阶段：AI 辅助用例 Review

- 独立 Prompt 和建议 Schema；
- `case_review_ai` FIFO；
- 三种 AI 操作；
- 建议差异和人工应用；
- 取消、超时、恢复和成本限制。

建议在同一个版本开发，但以两道质量门禁推进：人工 Review 稳定后再开启 AI 开关。

### 初步工作量

在复用现有测试点 Review 基础上，预计 **10～16 人日**：

| 工作项 | 估算 |
|---|---:|
| 公共 ReviewEngine 资源策略抽取 | 1～2 人日 |
| 用例 Schema、兼容、校验、覆盖、发布 | 2～3 人日 |
| 列表 + 详情编辑器与步骤操作 | 3～4 人日 |
| AI Prompt、Adapter、建议差异 | 2～3 人日 |
| 权限、迁移、回归和浏览器验收 | 2～4 人日 |

该估算不包含多人协同、执行引擎、资产库和开放式聊天。

---

## 22. 发布与回滚

### 22.1 dev 发布

1. 冻结现有测试点 Review 回归基线；
2. 完成人工用例 Review 自动化；
3. 在隔离数据库验证 0012 upgrade/downgrade/re-upgrade；
4. dev 开启 `ONLINE_CASE_REVIEW_ENABLED`，AI 仍关闭；
5. 完成人工主流程浏览器验收；
6. 开启 `CASE_REVIEW_AI_ENABLED`；
7. 完成 AI、权限、恢复和故障隔离验收；
8. 重新执行全部回归；
9. 确认历史 `output/` 未变化。

### 22.2 回滚

1. 先关闭 `CASE_REVIEW_AI_ENABLED`；
2. 必要时关闭 `ONLINE_CASE_REVIEW_ENABLED`；
3. 新任务恢复生成后直接成功的旧流程；
4. 已处于 `waiting_case_review` 的任务提供管理员兼容完成或 JSON 下载，不删除任务文件；
5. 必要时恢复上一版功能智能体镜像；
6. 通常保留 0012；确需降级时先关闭开关，只删除本期配置定义和种子 Release；
7. 不删除草稿、建议、确认版本和最终 artifacts。

---

## 23. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 直接复制测试点代码形成两套分叉 | 后续修复不一致 | 抽取轻量 ReviewEngine policy |
| 嵌套字段导致页面过宽 | 难以编辑 | 列表 + 详情布局 |
| 历史字段类型不一致 | 无法加载旧用例 | 明确兼容规范化，原稿不改写 |
| 用户误删导致测试点无覆盖 | 最终质量下降 | 确认时阻塞覆盖校验 |
| AI 改变来源测试点 | 需求事实漂移 | 保持 ID/引用、输出白名单和来源校验 |
| AI 自动写草稿 | 用户修改不可控 | 建议文件隔离、人工应用、显式保存 |
| JSON 与 XLSX 不一致 | 交付混乱 | XLSX 只从确认 JSON 生成并记录同版本 |
| 大用例集浏览器卡顿 | Review 不可用 | 分页、单详情表单、不渲染全部 DOM |
| 发布中途失败 | 半成品 artifact | 临时目录、原子发布、registry 最后提交 |
| 开启后改变现有用户流程 | 用户无法快速获得产物 | 功能开关、dev 灰度、prod 默认关闭 |

---

## 24. 评审确认项

以下决策已于 2026-08-13 全部接受推荐并确认，作为详细设计与实施基线：

1. 在线测试用例 Review 作为用例生成后的默认入口；**已确认**。
2. JSON 为权威格式，XLSX 仅由确认 JSON 派生；**已确认**。
3. 不新增测试用例业务数据库表；**已确认**。
4. 使用“用例列表 + 详情编辑器”，不采用所有字段单行超宽表格；**已确认**。
5. 草稿显式保存，不自动保存；**已确认**。
6. 每个确认测试点至少一条用例作为最终确认的阻塞规则；**已确认**。
7. 完全重复用例阻塞，名称相同但数据或预期不同只警告；**已确认**。
8. AI 三种操作与测试点 Review 保持一致，但使用独立 Prompt 和 Schema；**已确认**。
9. AI 只能产生建议，不能自动写草稿、删除用例或确认；**已确认**。
10. AI 改写必须保持 `case_id/test_point_id`，不得降低优先级；**已确认**。
11. `actual_result` 本期不允许在线编辑或 AI 修改；**已确认**。
12. 最终确认采用本地确定性同步发布；性能不达标时才降级为同一 FIFO 的异步发布；**已确认**。
13. 用例 Review 最大 2,000 条、10 MiB、1,000,000 字符；**已确认**。
14. `ONLINE_CASE_REVIEW_ENABLED` 与 `CASE_REVIEW_AI_ENABLED` 配置默认关闭，dev 验收后开启，prod 首次发布保持关闭；**已确认**。
15. 旧的直接 JSON/XLSX 产物流程至少保留一个发布周期；**已确认**。
16. 本期不做多人实时协同、评论、资产库、用例执行或缺陷管理；**已确认**。

---

## 25. 最终产品结论

在线测试用例 Review 可以在现有测试点 Review 基础上快速落地，但正确的复用方式是共享底层 ReviewEngine，而不是复制页面和文件代码。

产品侧继续保持 JSON 权威、文件版本追溯、CAS、所有权和共享 FIFO；测试用例侧新增适合嵌套字段的列表 + 详情编辑器、测试点引用与覆盖校验，以及独立的 AI 用例建议规则。最终 JSON 和 XLSX 从同一个不可变确认版本生成，避免用户确认内容与下载产物不一致。

该方案不增加业务数据库表、不引入新服务、不改变原生成 Prompt 和 CLI，也不触碰 API 智能体执行边界。它能把当前完整流程从“只审核测试点”扩展为“测试点和测试用例双 Review”，是现有架构下风险最低、复用率最高且可直接进入详细设计的方案。
