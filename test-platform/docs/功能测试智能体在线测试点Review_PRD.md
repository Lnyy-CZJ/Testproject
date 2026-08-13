# 功能测试智能体在线测试点 Review PRD

> 文档版本：V1.1  
> 创建日期：2026-08-12  
> 文档状态：已评审（在线 Review 基础决策已确认；V1.1 纳入 AI 辅助 Review）  
> 修订记录：V1.1（2026-08-12）确认第 21 章全部基础决策，并将 LLM 再次生成、改写和补全测试点纳入本期范围  
> 产品阶段：AI 测试智能体接入后的体验增强版本  
> 适用工具：功能测试智能体 `/functional-test-agent/`  
> 关联任务状态：`waiting_review`  
> 需求定位：在不改变 JSON 权威格式、文件任务架构和 FIFO 规则的前提下，增加 Web 结构化测试点编辑能力

关联基线文档：

- `test-platform/docs/AI测试智能体独立接入PRD.md`；
- `test-platform/docs/AI测试智能体独立接入开发设计与计划.md`。

本文档是上述已评审 MVP 的增量需求。原 MVP 中“下载 JSON → 本地修改 → 上传继续”的能力继续保留；本文档通过后，在线结构化编辑成为普通用户的默认 Review 方式，JSON 下载/上传调整为高级操作和故障恢复入口。

---

## 1. 文档目的

当前功能测试智能体在生成测试点后进入 `waiting_review`，用户需要下载 JSON、使用外部工具修改，再上传 JSON 并继续生成测试用例。该流程可以保证结构稳定，但存在以下体验问题：

1. JSON 不适合测试人员快速浏览和批量校正；
2. 用户容易因逗号、引号、字段名等语法问题导致上传失败；
3. JSON、Markdown、XMind 之间反复转换，操作链路长且容易丢失字段；
4. 用户无法在任务上下文中直接看到修改前后差异和校验结果；
5. 多个页面同时打开时，后保存的内容可能覆盖先保存的内容。

本 PRD 定义一个可直接实施的 Web 结构化测试点编辑器，让用户在任务详情页完成查看、修改、增删、校验、保存草稿和确认继续，同时保持现有 Runner、JSON Schema、任务目录、权限与队列机制兼容。

---

## 2. 产品目标

### 2.1 总体目标

为处于 `waiting_review` 状态的功能测试任务提供桌面端在线 Review 工作台，用户无需直接编辑 JSON 即可完成测试点审核，并可在受控范围内调用 LLM 获取补全、改写和按说明生成建议。

### 2.2 成功标准

上线后必须满足：

1. 普通用户可以在 Web 页面直接查看并编辑自己任务的测试点；
2. 支持新增、复制、删除、筛选、按模块折叠和风险等级选择；
3. 保存前能够定位必填字段、重复测试点和 ID 冲突；
4. 草稿保存不覆盖模型生成的原始 JSON；
5. 确认继续时生成不可变 Review 版本，并重新进入持久化 FIFO 队列；
6. 队列已满时保留已保存草稿和确认版本，任务仍为 `waiting_review`；
7. 多页面或多人并发修改时通过 revision 冲突阻止静默覆盖；
8. 旧的 JSON 下载、上传和直接生成用例入口继续可用；
9. 正式用例生成 Runner 继续读取确认后的 JSON 文件，不感知 Web 表格实现；AI 辅助使用独立受控子阶段；
10. 不新增测试点业务数据库表，不改变任务结果可见性和权限边界；
11. 用户可以请求 LLM 补全测试点、改写选中测试点或按说明生成测试点建议；
12. LLM 结果只能作为独立建议供用户预览和选择应用，不自动覆盖草稿、不自动确认 Review；
13. AI 辅助请求复用当前服务的持久化 FIFO 和单运行槽位，服务重启后可恢复或形成明确失败记录。

### 2.3 建议量化指标

| 指标 | 目标 |
|---|---:|
| 在线 Review 保存成功率 | ≥ 99%（排除网络中断和权限拒绝） |
| 有效草稿确认继续成功率 | ≥ 99%（排除队列满） |
| 100 条测试点首屏可交互时间 | ≤ 2 秒（开发环境、正常局域网） |
| 500 条测试点筛选反馈 | ≤ 300 毫秒 |
| 非法数据在继续前拦截率 | 100% |
| revision 冲突的静默覆盖次数 | 0 |

指标只使用真实前后端事件计算，不使用模拟数据。

---

## 3. 用户与核心场景

### 3.1 目标用户

| 用户 | 主要诉求 |
|---|---|
| 测试工程师 | 快速校正模型生成的测试点并继续生成用例 |
| 测试负责人 | 补充风险、边界和模块覆盖，确认测试点质量 |
| 平台管理员 | 在授权范围内协助查看或处理任务，排查 Review 问题 |
| 只读用户 | 查看有权限的任务结果，但不能修改或继续任务 |

### 3.2 核心用户故事

1. 作为任务创建者，我希望直接修改测试点字段，不再下载和编辑 JSON。
2. 作为测试工程师，我希望快速筛选某个模块、功能或风险等级，只处理相关测试点。
3. 作为测试负责人，我希望看到新增、删除和修改数量，确认本次 Review 的影响。
4. 作为用户，我希望保存未完成草稿，之后回到同一任务继续修改。
5. 作为用户，我希望在多个页面产生修改冲突时收到明确提示，而不是覆盖别人或自己的新版本。
6. 作为高级用户，我希望仍能下载或上传 JSON，以便批量处理或故障恢复。

---

## 4. 范围与非目标

### 4.1 本期范围

- `waiting_review` 任务的在线结构化表格编辑；
- 原始版本、当前草稿和已确认版本的读取；
- 测试点新增、复制、删除和字段修改；
- 模块、功能、场景、风险等级和关键字筛选；
- 按模块分组折叠；
- 必填、长度、枚举、ID 唯一性和重复测试点校验；
- 修改摘要和行级修改标识；
- 显式保存草稿；
- 使用 revision 的乐观并发控制；
- 确认 Review 并重新进入 FIFO；
- JSON 下载、上传兼容入口；
- LLM 补全、改写和按说明生成测试点建议；
- AI 建议差异预览、选择应用、丢弃和重新生成；
- AI 辅助任务的持久化排队、取消、超时、恢复和成本限制；
- 权限、CSRF、所有权、审计和日志脱敏；
- 桌面端可访问性和关键状态页面。

### 4.2 明确非目标

本期不实现：

- 测试用例在线编辑；
- 多人实时协同、光标同步或评论系统；
- 富文本、Markdown 或 XMind 内嵌编辑器；
- AI 自动覆盖草稿、自动删除原测试点或自动确认 Review；
- Review 页面中的开放式聊天机器人和多轮自由对话；
- AI 对测试用例进行生成或修改；测试用例仍由确认后的正式 Runner 阶段生成；
- 语义相似度服务或向量数据库去重；
- 测试点独立数据库表、跨任务测试点资产库；
- 移动端和窄屏适配；
- 审批流、多人会签和电子签名；
- 修改已进入 `pending/running/succeeded` 的确认版本；
- 改变 Prompt、需求拆解或测试用例生成算法。

---

## 5. 产品原则与关键决策

### 5.1 JSON 仍是权威格式

Web 表格只是 JSON 的结构化视图。服务端保存、Runner 输入、SHA-256、产物下载和故障恢复仍以 UTF-8 JSON 为准。

页面不把测试点正文写入平台 PostgreSQL，也不新建测试点业务表。

### 5.2 原始、草稿和确认版本分离

三类文件职责固定：

```text
published/test-points/<generated-file>.json   # 模型生成原始版本，只读
input/review-draft.json                       # 当前可变草稿，原子覆盖
input/review-test-points-v1.json              # 第一次确认的不可变版本
input/review-test-points-v2.json              # 后续确认的不可变版本
```

- 原始版本永不被在线编辑覆盖；
- 每次“保存草稿”原子更新 `review-draft.json`，并增加 revision；
- 每次“确认并继续”从当前有效草稿生成一个不可变版本；
- 相同 SHA-256 重试不得重复生成版本；
- JSON 上传先进入同一草稿模型，通过确认后再生成不可变版本。

### 5.3 普通用户默认不直接接触 JSON

任务详情默认展示结构化编辑器。JSON 下载、上传放入“高级操作”区域，避免与主操作竞争，但不能移除。

### 5.4 不绕过现有状态机和队列

合法链路保持：

```text
waiting_review → pending → running → succeeded
```

“确认并继续”必须重新参与 FIFO 排序。`waiting_review` 不占运行槽位，不能从页面直接启动 Runner。

### 5.5 保存草稿允许未完成，确认继续必须完全有效

- 保存草稿：允许存在必填项为空等业务校验错误，便于中途保存；但 JSON 结构、最大数量、总体大小和字段类型必须合法；
- 确认继续：所有阻塞级错误必须清零；警告可由用户确认后继续。

### 5.6 AI 只生成建议，不直接改写权威数据

LLM 辅助 Review 必须遵循：

- 发起前先显式保存当前草稿，并携带该草稿的 revision 和 SHA-256；
- LLM 输出保存为独立、不可变的建议文件；
- 页面先展示建议相对当前草稿的新增、修改和潜在冲突；
- 用户可逐条或批量选择应用；“应用”只更新浏览器编辑状态，不直接确认 Review；
- 用户再次点击“保存草稿”后，变更才成为新的草稿 revision；
- 用户仍需点击“确认并继续”才生成不可变 Review 版本并进入用例生成队列；
- LLM 不得自动降低风险等级、删除人工测试点或把补充说明当作已确认需求事实。

### 5.7 AI 辅助与正式用例生成共享运行槽位

AI 辅助调用不是同步 HTTP 请求，也不建立第二套旁路执行器。它复用功能智能体的持久化 FIFO、单运行槽位、超时和进程隔离：

```text
waiting_review
  → pending（review_ai）
  → running（review_ai）
  → waiting_review（建议已生成或辅助失败，可继续人工编辑）
```

正式继续仍为：

```text
waiting_review
  → pending（generate_test_cases）
  → running（generate_test_cases）
  → succeeded/failed
```

因此 AI 辅助不会绕过队列，也不会与正式生成任务并行争用同一个智能体。AI 辅助失败属于可恢复的 Review 子阶段失败，任务返回 `waiting_review` 并保留草稿，而不是把整个功能测试任务置为 `failed`。

---

## 6. 信息架构与页面布局

### 6.1 页面入口

入口保持在功能任务详情页：

- 当任务为 `waiting_review` 时，主操作显示“Review 测试点”；
- 点击后进入任务详情中的 Review 工作区，URL 可使用锚点或独立子路由；
- 其他状态只读展示已确认摘要，不提供编辑能力。

建议路由：

```text
/functional-test-agent/tasks/{task_id}#review
```

本期不强制增加单独 SPA 路由，优先适配现有 Flask + Jinja + 原生 JavaScript 架构。

### 6.2 信息顺序

页面按以下顺序组织：

1. 当前状态与下一步操作；
2. Review 摘要：测试点数量、错误数、警告数、草稿保存状态；
3. 筛选与批量操作栏；
4. AI 辅助操作栏：补全、改写选中项、按说明生成；
5. 结构化测试点表格；
6. AI 建议差异抽屉或面板；
7. 修改摘要；
8. 主操作栏：保存草稿、确认并继续；
9. 高级操作：下载原始 JSON、下载草稿 JSON、上传 JSON；
10. 需求拆解摘要、产物、日志和技术元数据。

### 6.3 桌面表格列

| 列 | 编辑方式 | 建议宽度 | 说明 |
|---|---|---:|---|
| 选择 | 复选框 | 44px | 用于批量删除，不替代行操作 |
| ID | 单行文本 | 100px | 必填、任务内唯一 |
| 模块 | 单行文本 | 140px | 必填 |
| 功能 | 单行文本 | 160px | 必填 |
| 场景 | 单行/扩展文本 | 190px | 必填 |
| 测试点 | 可扩展文本 | 自适应，最小 280px | 必填，主要编辑字段 |
| 风险 | 下拉框 | 88px | `P0/P1/P2/P3` |
| 状态 | 文本与图标 | 92px | 已修改、错误、警告、未修改 |
| 操作 | 文本按钮菜单 | 112px | 复制、删除 |

表头固定。表格横向空间不足时允许容器横向滚动，但主字段“测试点”不得被压缩到不可读。

### 6.4 分页与信息密度

- 默认每页 100 条，可切换 50/100/200；
- 筛选针对完整草稿数据，不只筛选当前页；
- 页码切换不丢失未保存的浏览器内修改；
- 最大 5,000 条与现有 Review 上限保持一致；
- 不为本期引入新的虚拟表格依赖；若性能验收不通过，再在详细设计阶段评估轻量虚拟化。

---

## 7. 详细功能需求

### 7.1 加载 Review 数据

进入页面后加载：

- 模型生成的原始测试点；
- 已存在的 `review-draft.json`，若有则优先作为当前编辑内容；
- 当前 revision、草稿 SHA-256、保存人和保存时间；
- 当前任务状态和编辑权限；
- 服务端校验结果；
- 相对原始版本的修改摘要。

优先级固定为：当前草稿 > 最近确认但尚未成功排队的版本 > 模型生成原始版本。

### 7.2 单元格编辑

- 点击或键盘聚焦后直接编辑；
- `Tab/Shift+Tab` 在可编辑单元格之间移动；
- `Enter` 确认当前输入并移动到下一行同列；多行文本按现有浏览器约定处理；
- `Escape` 撤销当前单元格尚未提交到页面状态的输入；
- 修改后立即执行客户端基础校验并标记该行；
- 服务端校验结果是最终依据，客户端规则不得比服务端更宽松。

### 7.3 新增测试点

- 提供“新增测试点”按钮；
- 新行追加到当前筛选结果之后，并滚动/定位到该行；
- ID 默认使用当前数据中下一个未占用的 `TP%03d`；
- 风险等级默认 `P2`；
- 若当前按模块或功能筛选，新行可预填对应字段；
- 新增后处于“未保存”状态。

### 7.4 复制测试点

- 单行操作支持“复制”；
- 复制模块、功能、场景、测试点和风险等级；
- 生成新的唯一 ID；
- 复制行紧跟原行；
- 因测试目标完全相同会触发重复错误，用户必须修改测试点或删除重复行后才能继续。

### 7.5 删除测试点

- 单行删除无需二次弹窗，但在页面底部提供一次“撤销删除”；
- 批量删除必须显示数量并要求确认；
- 删除仅影响当前草稿，不删除原始文件；
- 至少保留一条测试点，空列表不能保存为可确认草稿；
- 保存成功或离开页面后不再提供客户端撤销；用户仍可通过“重置为原始版本”恢复。

### 7.6 筛选与折叠

支持：

- 关键字：匹配 ID、模块、功能、场景和测试点；
- 模块多选；
- 功能多选，选项跟随模块过滤；
- 风险等级多选；
- 只看错误；
- 只看警告；
- 只看已修改；
- 按模块分组并折叠/展开；
- 一键清除筛选。

筛选和折叠只影响展示，不改变数据顺序和保存内容。

### 7.7 校验规则

#### 7.7.1 阻塞级错误

以下情况禁止“确认并继续”：

| 规则 | 错误定位 |
|---|---|
| 测试点列表为空 | 页面级 |
| 测试点数量超过 5,000 | 页面级 |
| 规范化 JSON 超过 5 MiB 或 500,000 字符 | 页面级 |
| 任一项不是对象 | 行级 |
| `id` 为空或长度超过 64 | 单元格 |
| `id` 在任务内重复 | 所有冲突行 |
| `module` 为空或长度超过 200 | 单元格 |
| `feature` 为空或长度超过 200 | 单元格 |
| `scenario` 为空或长度超过 500 | 单元格 |
| `test_point` 为空或长度超过 2,000 | 单元格 |
| `risk_level` 不属于 `P0/P1/P2/P3` | 单元格 |
| 模块、功能、场景和测试点规范化后完全相同 | 所有重复行 |
| 字段包含 NUL 或无法编码为 UTF-8 | 单元格/页面级 |

规范化仅用于比较：去除首尾空白、连续空白折叠、英文字母转小写。保存正文时保留用户输入的大小写，只去除字段首尾空白。

#### 7.7.2 非阻塞警告

以下情况提示但允许用户确认继续：

- 不同模块或功能下出现相同 `test_point` 文本；
- ID 不符合推荐格式 `TP` + 三位及以上数字，但仍为非空唯一字符串；
- 测试点文本过短，例如少于 2 个字符；
- 同一测试点风险等级相对原始版本发生变化；
- 删除超过原始测试点总数的 30%；
- 新增超过原始测试点总数的 50%。

非阻塞警告必须在确认对话框中汇总，用户点击“仍然继续”后才提交。

### 7.8 重复检测

本期只做确定性检测：

- 完全重复键：`module + feature + scenario + test_point` 规范化后相同，作为阻塞错误；
- 文本相同但上下文不同：只作为警告；
- 不调用 LLM、不使用向量相似度，不把模糊语义判断作为阻塞条件。

### 7.9 修改摘要

页面持续展示相对模型原始版本的摘要：

- 新增数量；
- 删除数量；
- 修改数量；
- 未修改数量；
- 风险等级变化数量；
- 当前错误和警告数量。

行级使用“新增、已修改、待删除、错误、警告”等文字或图标表达，不能只使用颜色。

本期不要求逐字符 diff；选中已修改行时，允许展示该行原始值与当前值对照。

### 7.10 保存草稿

“保存草稿”行为：

1. 前端携带当前 `revision` 和完整测试点列表；
2. 服务端执行结构、大小、字段类型和业务规则校验；
3. 服务端以稳定键顺序和 UTF-8 规范化生成 JSON；
4. 原子写入 `input/review-draft.json`；
5. 更新 `task.json` 中的草稿元数据；
6. revision 加一并返回最新 SHA-256、保存时间和校验结果；
7. 任务保持 `waiting_review`，不进入队列。

草稿存在阻塞错误时可以保存，但响应必须返回 `valid_for_resume=false` 和完整错误列表。

页面关闭或刷新时，如果存在未保存修改，必须通过浏览器离开确认提示用户。

### 7.11 重置为原始版本

- “重置为原始版本”位于高级操作中；
- 操作前明确说明当前未保存修改会丢失；
- 重置只更新页面数据，用户点击“保存草稿”后才写入服务端；
- 不删除已确认的历史版本。

### 7.12 JSON 下载与上传兼容

保留以下能力：

- 下载模型生成的原始 JSON；
- 下载当前草稿 JSON；
- 上传修改后的 JSON；
- 上传后先载入编辑器并展示校验结果，不默认立即排队；
- 用户必须点击“确认并继续”才进入 FIFO；
- 现有 `multipart/form-data` resume 接口在兼容期继续可用。

上传 JSON 缺少编辑器展示字段时：

- 允许加载为草稿；
- 缺失字段在表格中显示为空并标记错误；
- 用户补齐并通过校验后才能继续；
- 未识别的扩展字段原样保留，避免往返编辑造成数据丢失。

### 7.13 确认并继续

前置条件：

- 任务状态仍为 `waiting_review`；
- 当前页面 revision 与服务端一致；
- 当前草稿无阻塞错误；
- 用户具备 `tool.execute` 且满足任务所有权；
- CSRF 校验通过。

执行过程：

1. 若页面仍有未保存修改，先执行保存草稿；
2. 服务端再次完成全部校验；
3. 使用草稿规范化内容计算 SHA-256；
4. 相同 SHA 已存在确认版本时复用，不重复创建文件；
5. 否则原子生成 `review-test-points-vN.json`；
6. 更新 `request.json.review_relative_path`；
7. 尝试把任务从 `waiting_review` 转为 `pending`；
8. 成功后页面进入排队状态并停止编辑。

队列已满时：

- 返回 `409 QUEUE_FULL`；
- 已确认 JSON 版本和草稿均保留；
- 任务保持 `waiting_review`；
- 页面显示“Review 已保存，当前队列已满，请稍后再次继续”；
- 用户重试时复用相同 SHA 和版本，不产生重复文件。

### 7.14 AI 辅助 Review

#### 7.14.1 支持操作

| 操作 | 输入范围 | LLM 目标 | 输出类型 |
|---|---|---|---|
| 补全测试点 | 当前完整草稿、原始需求、需求拆解结果、可选补充说明 | 识别正常、异常、边界、权限、状态、幂等和并发等缺口 | 仅新增建议 |
| 改写选中项 | 最多 100 条选中测试点及其上下文 | 改善原子性、清晰度和字段一致性，不改变需求事实 | 修改建议 |
| 按说明生成 | 用户说明、当前筛选上下文、原始需求和现有草稿 | 在用户指定方向生成新增测试点 | 仅新增建议 |

本期不提供“自动删除”建议。LLM 发现疑似无效或重复测试点时，只返回警告说明，由用户人工删除。

#### 7.14.2 发起条件

发起 AI 辅助前必须满足：

- 任务处于 `waiting_review`；
- `REVIEW_AI_ENABLED=true`；
- 用户具备 `tool.execute` 和任务所有权；
- 当前浏览器内容已经显式保存，页面无未保存修改；
- 请求 revision、草稿 SHA 与服务端一致；
- 草稿满足结构与字段类型校验；允许存在业务必填错误，但“改写选中项”的目标行必须字段完整；
- 当前任务没有未结束的 AI 辅助请求；
- 功能智能体等待队列未满。

#### 7.14.3 用户输入限制

- 操作类型必须从固定枚举选择；
- “按说明生成”的补充说明最多 2,000 字符；
- 改写操作每次最多选择 100 条；
- 单次最多返回 200 条新增建议或 100 条改写建议；
- 单次进入 LLM 上下文的测试点最多 500 条；超过时用户必须先限定模块/功能范围，页面不得静默截断；
- 用户说明作为不可信的“测试设计补充要求”传入，不可覆盖需求事实和系统 Prompt；
- 页面不接受模型、Base URL、Prompt 路径、温度或任意服务器参数；
- 模型和 Prompt Bundle 使用任务当前环境的已发布配置快照。

#### 7.14.4 输出 Schema

LLM 必须输出结构化建议，不直接输出完整替换草稿：

```json
{
  "operation": "supplement",
  "base_revision": 4,
  "base_sha256": "...",
  "summary": "补充边界与重复提交场景",
  "suggestions": [
    {
      "suggestion_id": "suggestion_xxx",
      "action": "add",
      "target_id": null,
      "point": {
        "id": "TP054",
        "module": "评分反馈",
        "feature": "自动触发条件",
        "scenario": "重复触发",
        "test_point": "短时间内重复提交",
        "risk_level": "P1"
      },
      "reason": "现有测试点未覆盖幂等处理",
      "source_basis": "需求中的重复触发约束"
    }
  ],
  "warnings": []
}
```

约束：

- `action` 本期只允许 `add` 或 `replace`；
- `replace` 必须携带现有 `target_id`，不能修改其他行；
- LLM 返回的 ID 只作为候选，应用时由服务端/页面重新分配或检查唯一性；
- `source_basis` 必须说明依据；没有明确依据时标记为测试设计建议，不能声称是需求事实；
- 输出必须通过与 Review 草稿一致的字段和重复校验；
- 非法建议被隔离并显示为失败项，不得污染草稿。

#### 7.14.5 建议预览与应用

AI 完成后任务返回 `waiting_review`，页面展示建议面板：

- 顶部显示操作类型、模型名称、Prompt Bundle、基准 revision、耗时和建议数量；
- 新增建议显示完整字段、理由和依据；
- 改写建议并排显示“当前值 / 建议值”，逐字段突出变化；
- 默认不选中任何建议；
- 支持逐条选择、全选当前筛选结果、应用选中和丢弃全部；
- 应用前再次执行 ID、重复和字段校验；
- 应用只改变浏览器内编辑状态，页面显示“未保存”；
- 用户保存后形成新草稿 revision；
- 建议文件本身不可被修改或覆盖。

如果当前草稿 revision 已不同于建议的 `base_revision`，建议面板显示“基准已变化”：

- 禁止一键全部应用；
- 对仍能按 `target_id` 精确匹配且原值未变化的改写建议，可允许逐条应用；
- 新增建议可重新校验后逐条应用；
- 其余建议标记冲突，用户可重新发起 AI 辅助；
- 系统不得自动合并冲突建议。

#### 7.14.6 AI 辅助排队、取消与失败

- 发起成功返回 202，任务进入 `pending`，阶段为 `review_ai_queued`；
- 运行时阶段为 `review_ai_running`，编辑器只读；
- 成功后回到 `waiting_review/review_ai_ready`；
- 模型超时、限流、响应非法或进程重启后回到 `waiting_review/review_ai_failed`；
- AI 失败不得覆盖草稿、原始测试点或已有建议；
- 用户可取消等待中或运行中的 AI 辅助，任务回到 `waiting_review/review_ai_cancelled`；
- “取消 AI 辅助”和“取消整个任务”必须是两个明确操作；
- AI 辅助默认超时 600 秒，不使用正式任务的 3,600 秒上限；
- 取消运行中请求沿用进程组 SIGTERM 和超时强制终止策略。

#### 7.14.7 建议文件

```text
input/review-ai/request-v1.json
input/review-ai/suggestions-v1.json
input/review-ai/request-v2.json
input/review-ai/suggestions-v2.json
```

- 请求文件只保存必要的非 Secret 参数、base revision/SHA 和用户说明；
- 建议文件原子写入并登记 SHA-256；
- 不保存模型思维链；只保存结构化建议、简短理由、依据和稳定告警；
- 任务对外接口不返回内部路径；
- 相同 operation、base SHA、选中 ID 和说明 SHA 的重复请求复用已有成功结果或进行幂等拒绝。

---

## 8. 数据模型

### 8.1 测试点对象

编辑器的标准字段：

```json
{
  "id": "TP001",
  "module": "登录",
  "feature": "密码登录",
  "scenario": "用户名",
  "test_point": "为空",
  "risk_level": "P1"
}
```

服务端不得无故丢弃额外字段。额外字段不在本期页面中编辑，但需在读取、保存和确认过程中原样往返。

### 8.2 草稿元数据

建议在 `task.json` 增加内部字段 `review_draft`：

```json
{
  "revision": 3,
  "relative_path": "input/review-draft.json",
  "sha256": "...",
  "saved_by_user_id": "usr_xxx",
  "saved_by_username": "tester",
  "saved_at": "2026-08-12T15:30:00+08:00",
  "test_point_count": 53,
  "valid_for_resume": true,
  "error_count": 0,
  "warning_count": 2,
  "base_generated_sha256": "..."
}
```

普通任务详情响应只返回展示所需的非敏感字段，不返回内部相对路径。

### 8.3 确认版本元数据

`task.json.review` 保持确认版本语义：

```json
{
  "version": 2,
  "sha256": "...",
  "reviewed_by_user_id": "usr_xxx",
  "reviewed_by_username": "tester",
  "reviewed_at": "2026-08-12T15:35:00+08:00",
  "test_point_count": 53,
  "source_revision": 3
}
```

公共响应不得返回文件系统路径。

### 8.4 AI 辅助元数据

`task.json.review_ai` 只保存当前/最近一次 AI 辅助的可恢复元数据：

```json
{
  "request_version": 2,
  "operation": "supplement",
  "status": "ready",
  "base_revision": 4,
  "base_sha256": "...",
  "request_sha256": "...",
  "suggestion_sha256": "...",
  "suggestion_count": 12,
  "valid_suggestion_count": 11,
  "model_name": "deepseek-v4-flash",
  "prompt_bundle_sha256": "...",
  "requested_by_user_id": "usr_xxx",
  "requested_at": "2026-08-12T15:40:00+08:00",
  "finished_at": "2026-08-12T15:42:00+08:00",
  "error_code": null,
  "error_message": null
}
```

内部路径、模型凭据、Prompt 全文和原始模型响应不得进入公共响应。

---

## 9. HTTP API 需求

所有接口都位于 `/functional-test-agent/api/v1`，复用现有可信身份头、所有权、RBAC、CSRF 和统一错误响应。

### 9.1 获取 Review 工作区

```http
GET /functional-test-agent/api/v1/tasks/{task_id}/review
```

成功响应：

```json
{
  "task_id": "task_xxx",
  "task_status": "waiting_review",
  "editable": true,
  "source": "draft",
  "revision": 3,
  "sha256": "...",
  "generated_sha256": "...",
  "saved_at": "2026-08-12T15:30:00+08:00",
  "saved_by": "tester",
  "points": [],
  "validation": {
    "valid_for_resume": true,
    "errors": [],
    "warnings": []
  },
  "diff_summary": {
    "added": 2,
    "modified": 4,
    "deleted": 1,
    "unchanged": 46
  }
}
```

要求：

- 普通用户只能读取自己的任务；管理员需有 `task.view.all`；
- 不存在和越权统一返回 404；
- 非 `waiting_review` 可以返回只读数据，`editable=false`；
- 已过期且文件已清理时返回 410 `ARTIFACT_EXPIRED`。

### 9.2 保存草稿

```http
PUT /functional-test-agent/api/v1/tasks/{task_id}/review-draft
Content-Type: application/json
X-CSRF-Token: <token>
```

请求：

```json
{
  "revision": 3,
  "points": []
}
```

成功返回 200，包含新 revision、SHA、保存时间、校验结果和 diff 摘要。

规则：

- 需要 `tool.execute`、所有权和双提交 CSRF；
- 仅 `waiting_review` 可写；
- 请求 revision 必须等于服务端当前 revision；
- 首次保存时客户端传 `revision=0`；
- 请求体沿用 5 MiB、500,000 字符和 5,000 条限制；
- 规范化内容 SHA 与当前草稿相同时返回当前记录，不增加 revision；
- 文件写入与 `task.json` 元数据更新必须避免半写入；失败时旧草稿仍可读取。

revision 冲突：

```http
409 REVIEW_REVISION_CONFLICT
```

```json
{
  "code": "REVIEW_REVISION_CONFLICT",
  "message": "草稿已被更新，请先重新加载后再保存",
  "request_id": "req_xxx",
  "details": {
    "current_revision": 4,
    "saved_at": "2026-08-12T15:32:00+08:00",
    "saved_by": "tester"
  }
}
```

响应不得返回对方修改正文，用户通过 GET 主动重新加载。

### 9.3 确认并继续

推荐新增 JSON 调用方式，同时兼容现有 multipart 上传方式：

```http
POST /functional-test-agent/api/v1/tasks/{task_id}/resume
Content-Type: application/json
X-CSRF-Token: <token>
Idempotency-Key: <uuid>
```

请求：

```json
{
  "revision": 4,
  "sha256": "...",
  "accept_warnings": true
}
```

- 成功返回 202，任务状态为 `pending`；
- 无草稿返回 409 `REVIEW_DRAFT_REQUIRED`；
- revision 或 SHA 不一致返回 409 `REVIEW_REVISION_CONFLICT`；
- 存在阻塞错误返回 422 `REVIEW_VALIDATION_FAILED`；
- 有警告且未确认返回 409 `REVIEW_WARNING_CONFIRMATION_REQUIRED`；
- 队列满返回 409 `QUEUE_FULL`，但确认版本必须保留；
- 重复提交使用 Idempotency-Key 和 SHA 双重幂等。

### 9.4 上传 JSON 到草稿

建议新增：

```http
POST /functional-test-agent/api/v1/tasks/{task_id}/review-draft/import
Content-Type: multipart/form-data

review_file=<json>
revision=3
```

该接口只导入并保存草稿，不直接排队。现有 `POST .../resume` 上传文件行为在兼容期保留，页面新流程不再默认使用。

### 9.5 下载

下载继续通过 artifact 白名单或受控 Review 下载接口，不接受任意路径：

- 原始测试点 JSON；
- 当前草稿 JSON；
- 已确认 Review JSON。

文件名不得包含用户输入的未经清洗路径片段。

### 9.6 发起 AI 辅助

```http
POST /functional-test-agent/api/v1/tasks/{task_id}/review-ai
Content-Type: application/json
X-CSRF-Token: <token>
Idempotency-Key: <uuid>
```

请求示例：

```json
{
  "revision": 4,
  "sha256": "...",
  "operation": "rewrite_selected",
  "selected_ids": ["TP011", "TP012"],
  "instruction": "保持需求事实不变，改成更原子、可执行的测试点"
}
```

- `operation` 只允许 `supplement/rewrite_selected/generate_from_instruction`；
- 成功返回 202 和当前任务、AI 辅助阶段及请求版本；
- 队列满返回 `QUEUE_FULL`，任务和草稿保持 `waiting_review`；
- revision/SHA 不一致返回 `REVIEW_REVISION_CONFLICT`；
- 功能开关关闭返回 `FEATURE_DISABLED`；
- 相同幂等请求不得重复调用 LLM。

### 9.7 获取 AI 建议

```http
GET /functional-test-agent/api/v1/tasks/{task_id}/review-ai
```

返回当前请求状态；成功时返回经过 Schema 校验和脱敏的建议、失败项、模型与 Prompt 版本信息。普通用户只能读取自己的任务。

### 9.8 取消 AI 辅助

```http
POST /functional-test-agent/api/v1/tasks/{task_id}/review-ai/cancel
X-CSRF-Token: <token>
```

- 需要 `task.cancel`、任务所有权和 CSRF；
- 只取消当前 `review_ai_queued/review_ai_running` 子阶段；
- 成功后任务回到 `waiting_review`，草稿不变；
- 与现有“取消整个任务”接口分离，页面必须明确区分。

### 9.9 错误码

| HTTP | 错误码 | 场景 |
|---:|---|---|
| 400 | `INVALID_REQUEST` | 请求结构或字段类型错误 |
| 403 | `CSRF_INVALID` | 写请求 CSRF 校验失败 |
| 404 | `TASK_NOT_FOUND` | 任务不存在或越权 |
| 409 | `INVALID_TASK_STATE` | 任务不处于可编辑状态 |
| 409 | `REVIEW_REVISION_CONFLICT` | 草稿 revision/SHA 冲突 |
| 409 | `REVIEW_DRAFT_REQUIRED` | 未保存草稿直接继续 |
| 409 | `REVIEW_WARNING_CONFIRMATION_REQUIRED` | 警告尚未确认 |
| 409 | `REVIEW_AI_ALREADY_RUNNING` | 当前已有 AI 辅助请求 |
| 409 | `REVIEW_AI_BASE_CHANGED` | 建议基准草稿已变化 |
| 409 | `REVIEW_AI_SCOPE_REQUIRED` | 草稿过大，必须先限定 AI 分析范围 |
| 409 | `QUEUE_FULL` | 等待队列已满 |
| 410 | `ARTIFACT_EXPIRED` | Review 文件已过期 |
| 413 | `UPLOAD_TOO_LARGE` | 请求或文件超过上限 |
| 422 | `REVIEW_FILE_INVALID` | 上传 JSON 语法或结构错误 |
| 422 | `REVIEW_VALIDATION_FAILED` | 存在阻塞级业务校验错误 |
| 422 | `REVIEW_AI_RESPONSE_INVALID` | AI 建议无法通过结构校验 |
| 429 | `LLM_RATE_LIMITED` | 模型限流或额度不足 |
| 503 | `FEATURE_DISABLED` | 当前环境未启用 AI 辅助 Review |
| 504 | `LLM_TIMEOUT` | AI 辅助超过 600 秒 |
| 500 | `STORAGE_WRITE_FAILED` | 原子保存失败，旧版本保留 |

所有错误响应包含稳定 `code`、中文 `message` 和 `request_id`，不返回绝对路径、traceback 或 Secret。

---

## 10. 状态、并发与恢复

### 10.1 页面状态

| 页面状态 | 展示与操作 |
|---|---|
| 加载中 | 表格骨架或明确加载文案，禁止操作 |
| 空数据 | 说明未找到测试点并提供刷新/下载日志入口 |
| 可编辑 | 表格、保存草稿、确认继续可用 |
| 有未保存修改 | 固定显示“未保存”，离开页面提示 |
| 保存中 | 禁止重复保存，允许继续浏览，不允许确认 |
| 保存失败 | 保留浏览器内数据，提供重试 |
| revision 冲突 | 禁止覆盖，提示重新加载；用户可先下载本地未保存 JSON |
| 校验失败 | 聚焦错误摘要，可跳转到具体行 |
| AI 辅助排队 | 编辑器只读，展示排队位置和“取消 AI 辅助” |
| AI 辅助运行 | 编辑器只读，展示操作类型、开始时间和可取消操作，不展示虚假进度 |
| AI 建议就绪 | 回到可编辑状态，展示建议数量和差异入口 |
| AI 辅助失败 | 回到可编辑状态，显示稳定错误码并允许重试或继续人工 Review |
| AI 建议基准过期 | 展示基准变化，禁止一键应用并提供逐条校验或重新生成 |
| 队列已满 | 草稿/确认版本已保留，提供稍后重试 |
| 已进入队列 | 编辑器转只读，展示排队状态 |
| 任务被取消 | 编辑器只读，说明任务已取消 |
| 文件过期 | 展示 410 说明，不提供伪造空表格 |

### 10.2 乐观并发

- 服务端以整数 revision 为并发令牌；
- 任意保存必须携带加载时 revision；
- revision 不一致时不自动合并、不静默覆盖；
- 冲突页提供“重新加载服务器版本”和“下载我的未保存版本”；
- 本期不提供三方合并编辑器。

### 10.3 服务重启恢复

- `review-draft.json` 和元数据持久化后，服务重启仍可加载；
- `waiting_review` 状态保持；
- 已确认但因队列满未排队的版本保持可复用；
- 排队中的 AI 辅助按 `pending` 恢复；运行中的 AI 辅助标记 `WORKER_INTERRUPTED` 后返回 `waiting_review`；
- `pending/running` 任务按既有恢复规则处理；
- 不从浏览器 LocalStorage 恢复权威草稿。

---

## 11. 权限、安全与审计

### 11.1 权限

| 操作 | 权限要求 |
|---|---|
| 查看 Review | `tool.result.view` + 所有权，或 `task.view.all` |
| 编辑/保存草稿 | `tool.execute` + 所有权；管理员需同时具备跨用户查看能力 |
| 发起/查看/应用 AI 建议 | `tool.execute` + 所有权；查看仍受任务可见性约束 |
| 取消 AI 辅助 | `task.cancel` + 所有权 |
| 上传 JSON | `tool.execute` + 所有权 |
| 确认并继续 | `tool.execute` + 所有权 |
| 取消任务 | `task.cancel` + 所有权，或管理员授权 |

不存在和越权统一 404，防止任务 ID 枚举。只读用户只能查看，不显示伪可用编辑控件。

### 11.2 CSRF 与输入安全

- 所有 PUT/POST 使用现有双提交 CSRF；
- 服务端不信任客户端校验；
- JSON 使用安全标准解析器；
- 禁止 NUL、路径分隔符伪装、符号链接和任意路径下载；
- 用户文本按纯文本渲染，禁止作为 HTML 注入；
- 日志和错误继续二次脱敏；
- 任务 API 不返回 PID、绝对路径、Secret 或 Prompt 全文。

### 11.3 审计事件

至少记录：

| action | 触发时机 | 关键元数据 |
|---|---|---|
| `agent.review.draft.save` | 草稿保存成功 | task_id、revision、SHA、数量、错误/警告数 |
| `agent.review.draft.import` | JSON 导入成功 | task_id、revision、SHA、数量 |
| `agent.review.resume` | 确认并成功入队 | task_id、确认版本、SHA、数量 |
| `agent.review.resume` failed | 校验、冲突或队列满 | 稳定错误码，不记录正文 |
| `agent.review.conflict` | revision 冲突 | 客户端 revision、服务端 revision |
| `agent.review.ai.request` | 发起 AI 辅助 | operation、base revision/SHA、选中数量、说明 SHA |
| `agent.review.ai.complete` | AI 建议生成完成 | operation、建议数、有效数、模型和 Prompt 版本 |
| `agent.review.ai.cancel` | 取消 AI 辅助 | 原阶段、请求版本 |
| `agent.review.ai.failed` | AI 辅助失败 | 稳定错误码、阶段，不记录模型原始响应 |

审计不保存测试点正文、Prompt 全文或 Secret。

---

## 12. 非功能需求

### 12.1 性能

- 500 条测试点常规编辑和筛选不应出现明显卡顿；
- 保存请求单次只允许一个在途请求；
- 服务端校验 5,000 条测试点应在 2 秒内完成（不调用 LLM）；
- diff 和重复检查使用确定性本地算法；
- 不引入 WebSocket 或 SSE。
- AI 辅助通过现有任务轮询展示状态，不纳入 2 秒校验指标，也不承诺虚假百分比进度；
- 单次 AI 辅助默认超时 600 秒，Prompt 输入只包含完成该操作所需的最小上下文。

### 12.2 可靠性

- 草稿文件使用临时文件 + `fsync` + 原子替换；
- 文件成功但元数据保存失败时不得对外报告保存成功；详细设计需定义可恢复顺序或启动扫描；
- 确认版本一旦创建不可原地覆盖；
- Runner 只读取确认版本，不读取正在编辑的草稿；
- 迟到请求不能把 `pending/running/终态` 改回 `waiting_review`。

### 12.3 保留策略

Review 文件沿用任务输入和产物 90 天策略：

- 非终态任务不自动清理；
- `waiting_review` 草稿不因到期自动删除；
- 任务终态后按产物保留策略清理草稿和确认文件；
- 任务摘要按 180 天保留；
- 清理只操作经过 containment 校验的任务目录；
- 历史 `output/` 仍不纳入迁移或清理。

### 12.4 兼容性

- 不改变 `generator_test_points`、`generator_case` 和 Runner 参数；
- 不改变测试点 JSON 和测试用例 JSON 的权威格式；
- 不改变 Prompt 内容和模型执行逻辑；
- 不改变 API 测试智能体；
- 不要求平台数据库迁移；若详细设计发现必须迁移，需单独评审；
- 现有 multipart Review 上传接口至少保留一个发布周期。

### 12.5 AI 辅助配置与默认值

普通配置建议增加：

| 配置项 | dev 默认值 | prod 初始值 | 说明 |
|---|---:|---:|---|
| `REVIEW_AI_ENABLED` | `true` | `false` | prod 完成验收后再开启 |
| `REVIEW_AI_TIMEOUT_SECONDS` | `600` | `600` | 单次 AI 辅助执行超时 |
| `REVIEW_AI_MAX_SELECTED_POINTS` | `100` | `100` | 改写选中项上限 |
| `REVIEW_AI_MAX_SUGGESTIONS` | `200` | `200` | 单次建议数量上限 |
| `REVIEW_AI_MAX_CONTEXT_POINTS` | `500` | `500` | 单次进入模型上下文的测试点上限 |
| `REVIEW_AI_MAX_INSTRUCTION_CHARACTERS` | `2000` | `2000` | 用户说明字符上限 |

模型、Base URL 和 `LLM_API_KEY` 复用功能智能体当前环境的配置 Release 与独立 Secret，不增加浏览器可见 Secret，不允许 dev 读取 prod 配置。页面展示实际模型名称、Prompt Bundle SHA 和应用版本，不展示 Prompt 全文。

---

## 13. 视觉与可访问性要求

### 13.1 视觉原则

- 复用现有 `agent-workbench.css` 的系统字体、中性色、系统蓝、圆角和 8px 间距；
- 页面是工程工作台，不增加营销 Hero、AI 紫色渐变、发光或 Bento 卡片墙；
- 当前状态、下一步操作和错误摘要置于表格之前；
- 表格使用细分隔线和明确层级，避免每行独立卡片；
- 主要操作固定为“保存草稿”和“确认并继续”，高级 JSON 操作降低视觉权重；
- AI 辅助是次级操作组，不使用聊天气泡；运行、失败和建议就绪均使用稳定状态区；
- AI 建议采用差异面板展示“当前值、建议值、理由和依据”，应用按钮必须明确不会自动确认 Review；
- 动效只用于保存状态、行增删和提示，控制在 150～250ms；
- `prefers-reduced-motion` 下关闭非必要动画。

### 13.2 可访问性

- 桌面验收视口：1280×800、1440×900；
- 所有编辑、筛选、折叠、复制、删除和保存操作支持键盘；
- 焦点样式清晰，保存后焦点不丢失；
- 图标按钮必须有可访问名称，重要操作同时显示文字；
- 错误与警告除颜色外同时使用文字、图标和关联描述；
- 错误摘要可跳转并聚焦到对应单元格；
- 对话框支持 Esc、焦点循环和关闭后的焦点恢复；
- 表格使用语义化表头和可识别的行列关系；
- 正文、边框、状态文本满足 WCAG AA 对比度。

---

## 14. 验收标准

### 14.1 主流程

1. 创建完整流程任务并生成测试点；
2. 任务进入 `waiting_review`；
3. 页面正确加载原始测试点；
4. 修改字段、新增一条、复制一条并删除一条；
5. 页面展示正确的修改摘要和校验结果；
6. 保存草稿后刷新页面，修改完整恢复；
7. 确认并继续后生成不可变 Review 版本；
8. 任务状态依次变为 `pending → running → succeeded`；
9. Runner 使用确认版本生成测试用例；
10. 原始测试点 JSON 保持不变。

AI 辅助主流程同时验收：

1. 保存有效草稿后发起“补全测试点”；
2. 请求重新进入功能智能体 FIFO，编辑器在排队/运行时只读；
3. 完成后任务回到 `waiting_review`，草稿内容不变；
4. 页面展示新增建议、理由、依据、模型和 Prompt 版本；
5. 选择部分建议应用后页面进入未保存状态；
6. 保存草稿形成新 revision，再确认继续生成用例；
7. 未选择或已丢弃的建议不进入最终 Review JSON。

### 14.2 校验

- 必填字段为空时可保存草稿但不能继续；
- ID 重复时所有冲突行均可定位；
- 完全重复测试点不能继续；
- 风险等级只能选择 P0～P3；
- 超过数量、字符或请求体限制时稳定拒绝；
- 非阻塞警告需要二次确认；
- 未识别扩展字段往返保存后不丢失。

### 14.3 并发与幂等

- 两个页面加载同一 revision，页面 A 保存后，页面 B 保存得到 409；
- 页面 B 的本地内容仍可下载，不被清空；
- 相同内容重复保存不增加 revision；
- 相同 SHA 重复确认不增加确认版本；
- 重复 resume 不产生两个排队任务；
- 队列满时文件保存、任务仍为 `waiting_review`，稍后可重试。

### 14.4 权限与安全

- 创建者可编辑自己的任务；
- 其他普通用户统一得到 404；
- 管理员按权限矩阵查看和编辑；
- 只读用户无法保存或继续；
- 缺少或伪造 CSRF 的写请求被拒绝；
- HTML/脚本字符串只按文本显示；
- API 响应不包含路径、PID、Secret 或 Prompt 全文。

### 14.5 恢复与兼容

- 服务重启后草稿、revision 和 `waiting_review` 状态恢复；
- JSON 下载/上传仍可使用；
- 旧任务没有草稿元数据时可从原始产物初始化 revision 0；
- 旧 CLI 和原始智能体工作流回归通过；
- API 测试智能体功能与配置不受影响；
- 历史 `output/` 校验摘要无变化。

### 14.6 浏览器验收

在 1280×800 和 1440×900 验证：

- 加载、空、正常、未保存、保存中、保存失败；
- 校验错误、非阻塞警告、revision 冲突、队列满；
- 键盘编辑、焦点恢复、错误跳转和对话框；
- 100、500 和 5,000 条数据的可用性；
- 长模块名、长测试点和大量筛选选项；
- `prefers-reduced-motion`；
- Chrome 及平台当前支持的桌面浏览器。

---

## 15. 测试要求

### 15.1 单元测试

- 标准字段和扩展字段规范化；
- 必填、长度、枚举、ID 和重复校验；
- diff 摘要；
- revision 增长和相同 SHA 幂等；
- JSON 原子保存；
- 确认版本号生成；
- 5,000 条与大小边界；
- 特殊字符、UTF-8 和 XSS 文本。

### 15.2 API 集成测试

- GET 原始/草稿/只读 Review；
- PUT 保存有效与无效草稿；
- 两客户端 revision 冲突；
- JSON 导入草稿；
- resume 有效、警告未确认、校验失败和队列满；
- 所有权、管理员、只读、CSRF 和 IDOR；
- 服务重启恢复；
- 同 SHA 与 Idempotency-Key 重试；
- AI 补全、改写选中项和按说明生成三种操作；
- AI 辅助排队、取消、超时、限流、非法响应和重启恢复；
- AI 建议只读文件、基准 revision 冲突和选择性应用；
- AI 辅助失败后任务回到 `waiting_review` 且草稿不变；
- AI 请求与正式 resume 竞争时仅一个合法状态转换生效。

### 15.3 前端测试

- 表格加载、编辑、增删复制；
- 筛选、折叠、分页；
- 未保存状态和离开提示；
- 错误摘要到单元格定位；
- 保存与冲突处理；
- 确认警告与继续；
- AI 操作栏、排队/运行/失败/建议就绪状态；
- 建议差异预览、逐条选择、应用、丢弃和基准过期提示；
- 高级 JSON 操作；
- 键盘操作和可访问名称。

### 15.4 回归

至少运行：

```bash
cd /Users/admin/Testproject/AItestcase_Agents
python3 -m pytest -q

cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q

cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run
npm run build

cd /Users/admin/Testproject/test-platform
python3 -m unittest discover -s tests -v
docker compose config
```

---

## 16. 实施范围建议

详细设计阶段建议按以下最小增量实施，不作为未经评审的架构扩展：

### 16.1 `AItestcase_Agents`

主要影响：

- `services/common/web.py`：Review 查询、草稿保存、导入和 JSON resume；
- `services/common/uploads.py`：标准化、校验和重复检测；
- `services/common/task_models.py`：公共 Review 元数据；
- `services/common/task_store.py`：复用原子写入和 containment；
- `services/common/templates/task_detail.html`：结构化 Review 工作区；
- `services/common/static/agent-workbench.js`：编辑、筛选、保存、冲突和继续；
- `services/common/static/agent-workbench.css`：桌面表格及状态样式；
- `services/functional_agent/runner.py`：增加受控 `review_ai` 子阶段，复用现有 LLM 与任务目录；
- `agents/functional_test/`：在不改变既有 Prompt 的前提下新增独立 Review 建议 Prompt/Adapter；
- `tests/services/`：运行时、API、上传和页面测试。

明确不修改：

- 功能工作流 Prompt；
- `generator_test_points` 和 `generator_case` 的核心生成逻辑；
- API 测试智能体执行边界；
- 历史 `output/`。

### 16.2 `test-platform`

原则上不需要数据库迁移或主 React 架构调整。仅当网关对 JSON 请求体或新子路由需要显式配置时，精准修改 Nginx 和相关烟测。

---

## 17. 分阶段交付建议

| 阶段 | 内容 | 完成标准 |
|---|---|---|
| R01 数据与校验 | 标准化、校验、diff、草稿原子保存、revision | 单元测试通过 |
| R02 Review API | GET、PUT、导入、JSON resume、权限和审计 | API 集成测试通过 |
| R03 Web 编辑器 | 表格编辑、增删复制、筛选折叠、分页和状态 | 前端测试通过 |
| R04 AI 辅助 Review | 三种操作、结构化建议、差异应用、限制与错误映射 | Adapter 与 Mock LLM 集成测试通过 |
| R05 队列与恢复 | FIFO、队列满、AI/正式继续互斥、幂等、冲突和重启恢复 | 运行时集成测试通过 |
| R06 E2E 与发布 | 浏览器矩阵、真实模型隔离联调、回归、文档、部署和回滚 | 验收清单全部通过 |

详细设计需在该拆分上细化估算；本 PRD 不以压缩测试或安全范围换取排期。

---

## 18. 发布与回滚

### 18.1 发布策略

- 增加普通配置 `ONLINE_REVIEW_ENABLED=true`，按环境发布；
- 增加独立开关 `REVIEW_AI_ENABLED`；dev 默认开启，prod 完成成本、安全和真实模型验收后开启；
- 首次上线可在 dev 开启，prod 保持关闭完成验收；
- 开关关闭时页面回退现有 JSON 下载/上传流程；
- 不改变已有任务文件，旧任务按需在首次打开时初始化 revision 0；
- 发布前验证默认队列上限、任务权限和保留配置未被改变。

### 18.2 回滚

- 关闭 `ONLINE_REVIEW_ENABLED` 即可隐藏在线编辑器；
- 只关闭 `REVIEW_AI_ENABLED` 时保留在线人工编辑器和 JSON 流程；
- 保留已保存的 `review-draft.json` 和确认版本，不删除用户数据；
- 恢复旧页面后，用户仍可下载草稿并通过现有 JSON 上传流程继续；
- 不需要数据库 downgrade；
- 不回滚或清理历史任务目录；
- Runner 和旧 CLI 无需变更。

---

## 19. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 大量行导致页面卡顿 | 编辑体验下降 | 分页、确定性筛选、性能门槛；必要时详细设计再评估虚拟化 |
| 多页面覆盖 | 用户修改丢失 | revision + SHA 乐观锁，不自动覆盖 |
| 草稿存在错误 | 后续 Runner 失败 | 保存与确认分级校验，Runner 只读取确认版本 |
| UI 保存时丢失扩展字段 | 工作流兼容性下降 | 未识别字段原样往返，增加回归测试 |
| 每次保存产生过多版本 | 文件膨胀 | 草稿原子覆盖，只有确认时生成不可变版本 |
| 队列满造成重复确认 | 版本和任务混乱 | SHA 幂等、确认版本复用、任务保持 waiting_review |
| 前后端校验不一致 | 用户误判可继续 | 服务端为最终依据，前端展示服务端错误码与定位 |
| 在线编辑范围扩张为资产管理 | 项目复杂度失控 | 明确任务内编辑，不建数据库资产库和协作系统 |
| AI 建议幻觉或改变需求事实 | 错误测试点进入用例生成 | 只输出建议、展示依据、人工选择、保存和确认双门禁 |
| AI 建议覆盖人工草稿 | 用户修改丢失 | 独立建议文件、base revision/SHA、禁止自动应用 |
| AI 辅助占用正式任务槽位 | 正式任务等待变长 | 共用可观测 FIFO、600 秒超时、可取消、限制单次规模 |
| 模型响应格式不稳定 | 建议无法展示 | 严格 Schema、一次受控修复、非法项隔离、稳定错误码 |
| 用户说明形成 Prompt 注入 | 需求事实或安全边界被绕过 | 数据区隔、固定系统规则、最小上下文、输出白名单校验 |
| 重复请求增加模型成本 | 额度浪费 | Idempotency-Key、请求 SHA、数量与字符上限、审计指标 |

---

## 20. 实施复杂度与工作量判断

### 20.1 复杂度结论

将 LLM 辅助 Review 纳入本期是可行的，综合复杂度为**中等偏高**，但不需要整体重构。

简单部分是复用现有 LLM、需求文档、测试点 Schema、任务目录和配置快照；主要复杂度来自：

1. AI 请求必须异步排队，不能让浏览器同步等待模型；
2. AI 辅助完成后要回到 `waiting_review`，不能误触发正式用例生成；
3. 建议必须基于固定 revision，不能覆盖用户刚保存的新草稿；
4. 改写建议需要稳定关联 `target_id` 并展示差异；
5. AI 失败、取消、超时和重启都必须保留草稿并可继续人工 Review；
6. 必须限制输入、输出、超时和重复调用，控制成本与 Prompt 注入风险。

采用本 PRD 的“异步建议 → 差异预览 → 选择应用 → 显式保存”方案后，风险可以被现有文件任务架构和 FIFO 机制承接，不需要新增数据库表或第二套执行平台。

### 20.2 初步工作量

AI 辅助能力相对纯在线编辑器预计增加约 **6～10 人日**，作为详细设计前的工程量级判断，不作为最终排期承诺：

| 工作项 | 初步工作量 |
|---|---:|
| Review AI Prompt、结构化 Schema 与 Adapter | 1～2 人日 |
| 持久化子阶段、FIFO、取消、超时和恢复 | 2～3 人日 |
| 建议差异面板、选择应用和冲突处理 | 1～2 人日 |
| 权限、审计、Mock/集成/浏览器回归 | 2～3 人日 |

若改为聊天机器人、实时流式输出、AI 自动应用或多人协同，复杂度会明显上升，且不属于本期范围。

---

## 21. 评审确认项

以下产品选择已于 2026-08-12 全部确认，作为详细设计与开发基线：

1. 在线 Review 作为普通用户默认入口，JSON 操作收纳到高级区域；**已确认**。
2. 草稿采用“显式保存”而非自动保存，避免频繁写盘和版本冲突噪声；**已确认**。
3. 完全重复测试点作为阻塞错误，文本相同但上下文不同作为警告；**已确认**。
4. 保存草稿允许业务校验错误，确认继续必须零阻塞错误；**已确认**。
5. 确认版本不可变，草稿文件可原子覆盖；**已确认**。
6. 本期不提供多人实时协同和三方合并；**已确认**。
7. 本期不新增测试点数据库表；**已确认**。
8. 现有 multipart 上传并继续接口保留至少一个发布周期；**已确认**。
9. `ONLINE_REVIEW_ENABLED` 默认在 dev 开启、prod 完成验收后开启；**已确认**。
10. LLM 补全、改写和按说明生成测试点纳入本期，采用“只生成建议、人工选择应用、显式保存后再确认”的安全流程；**已确认纳入本期**。

---

## 22. 最终产品结论

在线 Review 的目标不是把 JSON 编辑器搬进浏览器，而是把测试点变成测试工程师可直接操作的结构化工作台。

系统内部继续以 JSON 文件作为权威数据，复用原子落盘、SHA-256、版本追溯、所有权和 FIFO；用户侧通过表格完成修改、校验和确认。LLM 在同一工作台中提供补全、改写和按说明生成建议，但建议必须经过差异预览、人工选择、草稿保存和最终确认，不得直接覆盖权威数据。

该方案减少格式转换和人工语法错误，增加 AI 辅助效率，同时不引入新的数据库模型、不改变正式 Runner 的确认 JSON 输入，也不破坏现有下载/上传恢复通道，是当前架构下可控且可实施的增强路径。
