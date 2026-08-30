# 功能测试智能体标准需求 Review 与场景级测试点生成 PRD

> 文档版本：V1.0  
> 文档状态：待评审  
> 编制日期：2026-08-25  
> 适用系统：功能测试智能体、测试开发平台  
> 需求基线：《功能测试智能体需求文档整理规则》V1.2 / FRD-2.0  
> 产品原则：人工确认优先、需求事实不丢失、场景级测试设计、确定性覆盖

---

## 1. 文档目的

本 PRD 定义功能测试智能体从“原始需求输入”到“标准需求文档 Review”“场景级测试点 Review”“测试用例生成与 Review”的新主流程。

本期不再把 LLM 需求拆解作为测试点生成的必经步骤，而是：

1. 使用 LLM 按 FRD-2.0 规则将原始需求整理为可人工审核的标准需求文档；
2. 标准需求文档经人工确认后，直接作为测试点生成的需求基线；
3. 测试点以完整业务场景为粒度，一个测试点可以覆盖多个 Requirement ID；
4. 覆盖率由程序基于 Requirement ID 确定性计算；
5. 测试点确认后，将完整事实字段传递给测试用例生成流程，避免 LLM 重新猜测预期结果。

本文档作为产品、设计、开发和测试共同使用的需求基线。具体代码、接口内部实现和文件改造在后续开发设计文档中确定。

---

## 2. 背景与问题

### 2.1 当前流程

```text
需求文档
→ 按标题切分大量需求片段
→ LLM逐片拆解Requirement和字段
→ 生成原子级测试点
→ LLM判断覆盖率并多轮补充
→ 测试点Review
→ 生成测试用例
```

### 2.2 已确认问题

#### 需求拆解调用过多

一份约 13,000 字、业务规模较小的新手引导需求被解析为 67 个片段。背景、范围、附录等非功能章节也进入逐片 LLM 处理，导致调用次数、Token、耗时和重复事实增加，完整功能上下文被破坏。

#### 测试点粒度方向错误

现有 Prompt 强调字段级、原子级和穷举级拆分，容易把“默认选中、切换、单选、本地保存、Continue、返回保持”等同一业务路径拆成大量碎片，不利于执行、Review 和维护。

#### 覆盖补充放大结果

覆盖模型主动检查需求未明确规定的并发、幂等、非法状态和通用 UI，并允许多轮补充；补充结果只做弱字符串去重，造成重复、未确认建议混入正式测试点和 ID 不稳定。

#### 测试点事实未完整传给测试用例

测试用例生成前可能丢失前置条件、预期结果、Requirement ID 和确认状态，导致 LLM 重新猜测页面、默认值和状态。已观察到 `Reply tab` 被泛化、“已跳过”被误写为“已完成”、待确认风险被写成确定断言以及 `test_data` 不是合法 JSON 等问题。

### 2.3 改造机会

用户已经形成稳定工作方式：先使用 AI 按规则整理原始需求，再将整理后的文档交给功能测试智能体。该步骤已完成需求理解、事实提取、冲突隔离和结构化，不需要平台再次执行不可见的原子化 LLM 拆解。

本期将标准需求整理结果提升为正式、可版本化、可人工确认的中间产物，并作为后续测试设计的唯一需求基线。

---

## 3. 产品目标与成功指标

### 3.1 产品目标

1. 建立“原始需求 → 标准需求文档 → 测试点 → 测试用例”的三层人工确认链路。
2. 标准 FRD-2.0 文档通过结构校验后跳过内部 LLM 原子需求拆解。
3. 将测试点粒度调整为可独立执行和判断结果的业务场景级。
4. 使用 Requirement ID 确定性计算正式需求覆盖率。
5. 将未确认项、歧义、冲突和测试建议与已确认需求严格隔离。
6. 保证需求事实、测试点和测试用例之间可追溯。
7. 减少 LLM 调用、生成时间和无效 Token 消耗。
8. 保持现有在线 Review、AI 辅助、队列、权限和 Artifact 能力兼容。

### 3.2 可量化指标

#### 正确性

- 已确认 Requirement ID 映射覆盖率达到 100%，或明确展示未覆盖清单；
- 测试点 ID 缺失率为 0；
- 正式测试点中未确认建议混入率为 0；
- 测试点到用例的 Requirement ID、状态和明确预期保留率为 100%；
- 测试用例 `test_data` 可被标准 JSON 解析的比例为 100%；
- 明确页面、默认值、状态和错误处理不得被用例生成器改写。

#### 效率

- FRD-2.0 标准需求的内部 LLM 需求拆解调用次数为 0；
- 5,000 条 Requirement 的结构校验和覆盖计算各不超过 2 秒；
- 与旧流程相比，标准需求到测试点的 LLM 调用次数减少至少 60%；
- 页面展示需求整理、测试点生成和测试用例生成各阶段 Token。

#### 体验

- 用户可清楚识别需求 Review、测试点 Review 和用例 Review；
- 每个阶段展示当前结果、问题和下一步；
- 所有 AI 结果必须先人工确认；
- CAS 冲突不得丢失用户本地修改。

### 3.3 不以数量为目标

本期不设置固定测试点数量目标。质量以 Requirement 覆盖、可执行性、重复度、事实保真和人工可维护性为准，不能由 Requirement、字段或页面元素数量直接推导测试点数量。

---

## 4. 非目标

1. 不直接解析图片、Figma、PDF 或 Word 的视觉内容；非文本资料需先由 Codex 或人工转写。
2. 不建设通用 PRD 管理系统或 Requirement 业务数据库表。
3. 不实现多人实时协同、三方合并、WebSocket 或自动保存。
4. 不自动裁决冲突、歧义和未确认问题。
5. 不把测试设计建议自动升级为已确认需求。
6. 不自动执行真实测试用例。
7. 不改变 API 测试智能体的安全边界。
8. 不删除原始需求、历史测试点、历史用例和已发布产物。
9. 不在本期物理删除旧需求拆解代码，仅停止新主流程自动调用。

---

## 5. 用户与权限

### 5.1 角色

| 角色 | 能力 |
|---|---|
| 测试工程师 | 创建任务、上传需求、Review 标准需求/测试点/测试用例、下载产物 |
| 管理员 | 按权限跨用户查看和处理 Review、取消任务、查看审计与版本信息 |
| 只读用户 | 查看有权限的结果，不得保存、确认、继续或取消 |

### 5.2 权限规则

沿用现有权限：`tool.view`、`tool.result.view`、`tool.execute`、`task.cancel`、`task.view.all`。

所有写操作必须执行身份、CSRF、RBAC、任务所有权、状态和 revision/SHA 校验。越权访问与任务不存在统一返回 404。

---

## 6. 核心术语

| 术语 | 定义 |
|---|---|
| 原始需求 | 用户上传的 Markdown/TXT，只读保存。 |
| 标准需求文档 | LLM 按 V1.2 规则生成并符合 FRD-2.0 的 Markdown。 |
| 需求草稿 | 用户可修改、使用 revision/SHA 保护的标准需求草稿。 |
| 确认需求版本 | 用户确认后不可变的标准需求 Markdown 和 Requirement 索引。 |
| Requirement | 单条需求事实追踪单位，不等同于测试点。 |
| 业务场景 | 完整前置条件、连续操作路径和相关可观察结果。 |
| 场景级测试点 | 可独立执行和判断结果、可引用多个 Requirement 的测试点。 |
| 正式覆盖率 | 已确认 Requirement 被已确认测试点引用的比例。 |
| 待确认项 | 原始资料未给出唯一结论的问题，不计入正式覆盖率。 |
| 测试建议 | 未经产品确认的风险方向，不计入正式覆盖率。 |

---

## 7. 目标用户流程

### 7.1 新任务主流程

```text
上传原始需求
→ 排队并整理FRD-2.0文档
→ waiting_document_review
→ 人工编辑、保存、确认标准需求版本
→ 重新进入FIFO生成场景级测试点
→ waiting_review
→ 人工/AI辅助Review测试点并确认
→ 重新进入FIFO生成测试用例
→ waiting_case_review
→ 人工/AI辅助Review测试用例
→ 确认发布JSON/XLSX
→ succeeded
```

### 7.2 标准需求快速路径

上传已符合 FRD-2.0 的文档时，系统识别标识并执行结构校验，将内容作为需求 Review 草稿；仍需人工确认，但不调用需求整理或需求拆解 LLM。

### 7.3 非标准文档

非标准 Markdown/TXT 进入 LLM 整理流程。整理完成后必须停留在需求 Review，不得自动生成测试点。

### 7.4 兼容旧流程

旧任务和旧 CLI 保持可读取、可下载。原 `decompose_requirement` 独立操作保留至少一个发布周期，但不再由新 Web 主流程自动调用。

---

## 8. 状态与队列

### 8.1 主状态

```text
pending
running
waiting_document_review
waiting_review
waiting_case_review
succeeded
failed
cancelled
```

### 8.2 子阶段

| 主状态 | 子阶段 | 说明 |
|---|---|---|
| pending | requirement_normalization_queued | 需求整理等待中 |
| running | normalizing_requirement | 正在整理标准需求 |
| waiting_document_review | requirement_review_editing | 等待需求 Review |
| pending | test_points_queued | 测试点生成等待中 |
| running | generating_test_points | 正在生成测试点 |
| waiting_review | review_editing | 等待测试点 Review |
| pending | generate_cases_queued | 用例生成等待中 |
| running | generating_test_cases | 正在生成用例 |
| waiting_case_review | case_review_editing | 等待用例 Review |
| succeeded | published | 已确认并发布 |

### 8.3 队列规则

- 需求整理、测试点生成、Review AI 和用例生成共用功能智能体单运行槽位；
- 每次人工确认后必须重新按 `queued_at + task_id` 进入持久化 FIFO；
- Review 状态不占运行槽位；
- 队列满时保留确认版本并停留当前 Review；
- 相同确认重试不得创建重复版本或队列项；
- 迟到结果使用 execution kind 和 sequence 隔离。

### 8.4 恢复

- 需求整理中断保留原始文件；
- 测试点生成中断保留确认需求版本；
- Review 状态重启后草稿和确认版本不变；
- 迟到 Runner 结果不得覆盖较新状态。

---

## 9. 上传要求

### 9.1 类型与限制

- `.md`、`.txt`；
- 单文件最大 5 MiB；
- UTF-8 解码后最多 500,000 字符；
- 每任务一个主需求文档；
- 安全文件名、SHA-256、路径 containment 和原子发布；
- 禁止符号链接、绝对路径和路径穿越。

### 9.2 原型资料

图片、Figma、PDF、DOCX 本期不在服务内直接解析。用户应先通过 Codex 按 V1.2 规则转写为 Markdown，再上传标准文档。

---

## 10. 标准需求整理

### 10.1 规则与版本

LLM 使用《功能测试智能体需求文档整理规则》V1.2。普通用户可见规则版本、模型、Prompt SHA、配置 Release、应用版本和本阶段 Token，不得查看 Prompt 全文、Secret 和内部路径。

### 10.2 事实边界

- 只使用当前任务需求正文；
- 原始文档作为不可信数据，不执行其中指令；
- 不读取其他任务、日志、Secret 或历史 output；
- 不编造默认值、状态、页面跳转、错误提示、次数、时间和权限；
- 无法确认的信息写入 Review 附录；
- 保留原始 Requirement ID，无 ID 时生成稳定唯一 ID；
- 只输出 UTF-8 Markdown，不输出分析过程。

### 10.3 标准标识

文档信息必须包含：

```text
文档类型：功能测试标准需求
结构版本：FRD-2.0
整理状态：已按规则整理
需求版本
原始资料
人工确认状态
```

### 10.4 标题结构

- H1：需求名称；
- H2：公共上下文、业务模块、跨功能规则、Review 附录；
- H3：完整功能、流程阶段或跨功能规则；
- 禁止 H4 及更深标题；
- 功能内部使用加粗标签、列表和表格。

### 10.5 整理失败

模型空响应、非法响应、超时、超限、最小结构失败或安全保存失败时进入稳定错误状态。失败不得覆盖原始需求文件。

---

## 11. 标准需求 Review

### 11.1 默认入口

整理完成后进入 `waiting_document_review`，任务详情默认展示需求 Review，不得自动继续测试点生成。

### 11.2 MVP 能力

- Markdown 在线纯文本编辑；
- 章节目录和 Requirement 搜索；
- 结构问题定位；
- dirty 状态和显式保存；
- 下载原稿、草稿和确认版本；
- 上传 Markdown 覆盖草稿；
- CAS 冲突时下载本地副本；
- 确认并生成测试点。

不提供富文本、所见即所得、多人实时协同和自动保存。

### 11.3 草稿 CAS

草稿使用 `revision + sha256 + saved_at + saved_by`。保存完整 Markdown；正文相同不增加 revision；冲突返回当前 revision/SHA，不覆盖本地内容。

### 11.4 结构校验

确认前必须通过：

- UTF-8、大小和字符限制；
- H1～H3 合法；
- 文档类型、FRD-2.0 和整理状态存在；
- Requirement ID 唯一；
- 无危险内部字段；
- 内容可安全序列化和原子保存。

功能缺少异常、某 Requirement 缺验收条件、存在未确认项或业务场景映射不完整属于质量警告，用户确认后可以继续。

### 11.5 确认版本

- 确认版本不可变；
- 相同 SHA 重复确认复用版本；
- 不同内容生成 v2、v3；
- 测试点生成只能读取明确指定的确认版本；
- 历史版本可查看和下载；
- 确认时同步生成确定性 Requirement 索引。

---

## 12. Requirement 索引

Requirement 索引由程序从确认 Markdown 确定性生成，不是 LLM 拆解结果，也不写业务数据库。

```json
{
  "schema_version": 1,
  "document_type": "functional_test_requirement",
  "structure_version": "FRD-2.0",
  "requirement_version": 1,
  "document_sha256": "...",
  "requirements": [
    {
      "id": "REQ-GOAL-001",
      "module": "新手引导",
      "feature": "Dating Goal",
      "text": "首次进入默认选中Not sure",
      "status": "confirmed",
      "source_section": "2.2 Dating Goal"
    }
  ],
  "review_items": []
}
```

解析规则：

- 只解析规则规定的结构，不做语义推理；
- 重复 ID 是阻塞错误；
- Review 附录的 Q/A/C 和测试建议不进入 confirmed 集合；
- 无法确定状态时标记 pending；
- 索引记录需求版本和文档 SHA。

---

## 13. 场景级测试点生成

### 13.1 生成输入

每个批次必须包含完整上下文：

```text
公共上下文
+ 当前完整H3功能章节
+ 相关跨功能规则
+ 当前Requirement索引
+ 测试点输出协议
```

不得把 H3 按加粗标签、表格行或单条 Requirement 重新拆成独立 LLM 请求。

### 13.2 测试点定义

一条测试点必须表达一个可独立执行和判断结果的业务场景，包含明确前置条件、操作目标、可观察结果以及一个或多个 Requirement ID，并保留 confirmed/pending 状态。

### 13.3 合并规则

以下 Requirement 应优先组合：

- 相同前置条件；
- 连续操作路径；
- 相互关联的结果；
- 相同角色和起始状态；
- 相同错误处理和风险等级。

### 13.4 拆分规则

以下差异才需要独立测试点：

- 前置条件、角色或权限不同；
- 操作路径或预期结果不同；
- 成功、网络失败和业务失败需要独立定位；
- 风险等级明显不同；
- 需要独立定位缺陷。

不得仅因多个字段、页面元素、步骤或 Requirement ID 而拆分。

### 13.5 特殊规则

- 同一页面展示要求聚合为少量有具体可观察内容的测试点，禁止通用“UI显示检查”；
- 需求明确规定的状态流转可生成 confirmed 测试点；
- 模型推测的并发、幂等、超时、兼容和安全方向只能生成 pending 建议；
- pending 建议不参与正式覆盖率。

### 13.6 输出 Schema

```json
{
  "id": "TP-GOAL-001",
  "module": "新手引导",
  "feature": "Dating Goal",
  "scenario": "目标选择并继续",
  "test_point": "验证默认选择、切换、本地保存和继续流程",
  "preconditions": ["新用户从Personalize进入Dating Goal"],
  "expected_result": "Not sure默认唯一选中；切换后保持单选并立即保存；Continue后进入Your Voice且选择不丢失",
  "requirement_ids": [
    "REQ-GOAL-001",
    "REQ-GOAL-002",
    "REQ-GOAL-003",
    "REQ-GOAL-004"
  ],
  "status": "confirmed",
  "source_type": "requirement",
  "risk_level": "P0"
}
```

### 13.7 ID 规则

- 首次生成后由程序统一规范化和分配 ID；
- ID 在同一确认版本内唯一；
- 补充结果不得保留空 ID；
- Review 修改内容不自动改变 ID；
- 复制测试点必须生成新 ID；
- Requirement ID 和测试点 ID 不得混用。

---

## 14. 确定性覆盖与补充

### 14.1 正式覆盖率

```text
confirmed Requirement ID集合
- confirmed测试点requirement_ids集合
= 未覆盖Requirement ID集合
```

正式覆盖率为：已映射 confirmed Requirement 数量 / confirmed Requirement 总数。

### 14.2 不计入正式覆盖率

- pending Requirement；
- Q/A/C Review 项；
- 测试设计建议；
- 未映射到原始事实的 AI 风险建议。

### 14.3 映射校验

- 引用不存在的 Requirement ID：阻塞错误；
- confirmed 测试点只引用 pending Requirement：阻塞错误；
- 一个 Requirement 被多个场景合理覆盖：允许；
- 一个测试点引用多个相关 Requirement：允许；
- Requirement 未覆盖：展示缺口，不伪造覆盖。

### 14.4 补充流程

只允许对真正未覆盖的 confirmed Requirement 执行最多一次补充。补充输入包含完整事实、所在功能章节和已有测试点摘要。补充后仍未覆盖的 Requirement 进入人工 Review，不继续循环 LLM。

### 14.5 去重

完全重复是阻塞错误。规范化比较字段包括 module、feature、scenario、preconditions、test_point、expected_result、requirement_ids 和 status。文本相似但上下文不同显示警告，由人工决定是否合并。

---

## 15. 测试点 Review

复用现有在线测试点 Review、脑图、表格、AI 建议、CAS、确认版本和 JSON 高级操作。

新增展示：

- 来源需求版本；
- Requirement 映射数量；
- confirmed 需求覆盖率；
- 未覆盖 Requirement 清单；
- pending 建议数量；
- 重复和相似提示；
- 测试点生成 Token。

保存允许业务质量问题；确认并继续前必须通过 JSON 技术结构、Requirement 引用和完全重复校验，并由用户确认未覆盖清单和 pending 风险。确认后创建不可变测试点版本并重新进入 FIFO。

---

## 16. 测试点到测试用例的数据契约

测试用例生成必须读取确认测试点完整字段：

```text
id
module
feature
scenario
test_point
preconditions
expected_result
requirement_ids
status
source_type
risk_level
```

不得在生成前删除前置条件、明确预期、Requirement ID 或确认状态。

### 16.1 确定性骨架

程序调用 LLM 前锁定 test_point_id、module、feature、scenario、priority、requirement_ids、requirement_status 和 expected_result 中的明确事实。LLM 主要补充可执行前置条件、步骤、测试数据和检查方式，不得修改明确目标页面、默认值、状态、错误处理和 Requirement 映射。

### 16.2 Schema 类型

- `preconditions`：字符串数组；
- `test_steps`：字符串数组；
- `test_data`：JSON 对象、数组或兼容字符串；
- `requirement_ids`：字符串数组；
- `requirement_status`：confirmed/pending；
- `expected_result`：字符串；
- `actual_result`：只读兼容字段。

### 16.3 质量门槛

程序检查每个确认测试点至少有对应用例、关键事实未丢失、pending 状态保留、test_data 可安全序列化和 Requirement 映射完整。失败时仅重试受影响测试点一次。

---

## 17. 页面与交互

### 17.1 新建任务

保留标题、项目、模块、补充说明和文件。页面提示两种输入：普通需求由系统整理，FRD-2.0 标准需求校验后直接进入 Review。识别由服务端完成，不能由前端选项绕过校验。

### 17.2 阶段导航

```text
任务信息
需求整理
需求Review
测试点生成
测试点Review
测试用例生成
测试用例Review
发布产物
```

未来阶段不可点击，已完成阶段可只读查看。

### 17.3 需求 Review 布局

- 左侧：章节目录和 Requirement 搜索；
- 中间：Markdown 纯文本编辑器；
- 右侧：结构校验、未确认项、冲突和保存状态；
- 操作区：保存草稿、下载、确认并生成测试点。

页面不自动保存，离开脏页面必须确认。

### 17.4 生成信息

每个 LLM 阶段展示模型、Prompt SHA、输入/输出/总 Token、耗时、配置 Release 和应用版本。普通用户不得查看 Prompt 全文和 Secret。

---

## 18. 文件与版本

```text
input/original/requirement.md
input/requirement-review/generated.md
input/requirement-review/draft.json
input/requirement-review/confirmed-vN.md
input/requirement-review/requirement-index-vN.json
input/review-draft.json
input/review-test-points-vN.json
input/case-review-draft.json
input/review-test-cases-vN.json
published/test-cases/vN/test-cases.json
published/test-cases/vN/test-cases.xlsx
```

版本职责：原始 SHA 证明输入未变；需求、测试点和用例草稿使用 revision/SHA；三类确认版本均不可变；execution sequence 隔离迟到结果。

确认文件必须通过临时文件、fsync 和原子创建发布。索引更新失败时首次读取根据不可变文件恢复，不覆盖历史版本。

---

## 19. API 产品需求

新增功能智能体需求 Review 接口：

```text
GET  /api/v1/tasks/{task_id}/requirement-review
PUT  /api/v1/tasks/{task_id}/requirement-review-draft
POST /api/v1/tasks/{task_id}/requirement-review-draft/import
GET  /api/v1/tasks/{task_id}/requirement-review/download
POST /api/v1/tasks/{task_id}/requirement-review/confirm
```

### 19.1 GET

返回原稿/草稿/确认版本、revision/SHA、结构校验、Requirement 统计、版本列表和允许操作。

### 19.2 PUT

提交完整 Markdown、revision 和 SHA；返回最新 revision/SHA、结构校验和 `valid_for_confirm`。

### 19.3 import

只接受 Markdown/TXT；导入后成为草稿，不自动确认或生成测试点。

### 19.4 download

`kind` 仅接受 `original/generated/draft/confirmed/requirement_index`，客户端不得提交路径。

### 19.5 confirm

要求 `Idempotency-Key`、当前 revision/SHA 和警告确认标记。成功后生成或复用确认版本并尝试入队；队列满时确认版本保留，任务仍为 `waiting_document_review`。

---

## 20. 稳定错误码

| 错误码 | 场景 |
|---|---|
| REQUIREMENT_FILE_INVALID | 原始文件非法 |
| REQUIREMENT_ENCODING_INVALID | 非 UTF-8 |
| REQUIREMENT_TOO_LARGE | 超出限制 |
| REQUIREMENT_NORMALIZATION_FAILED | LLM 整理失败 |
| REQUIREMENT_STRUCTURE_INVALID | 标准结构非法 |
| REQUIREMENT_VERSION_UNSUPPORTED | 结构版本不支持 |
| REQUIREMENT_ID_DUPLICATED | Requirement ID 重复 |
| REQUIREMENT_DRAFT_REQUIRED | 确认前没有草稿 |
| REQUIREMENT_REVISION_CONFLICT | 草稿 CAS 冲突 |
| REQUIREMENT_CONFIRMATION_REQUIRED | 警告需要确认 |
| REQUIREMENT_VERSION_NOT_FOUND | 确认版本不存在 |
| REQUIREMENT_QUEUE_FULL | 确认后队列满 |
| TEST_POINT_REQUIREMENT_NOT_FOUND | 引用不存在的 Requirement |
| TEST_POINT_DUPLICATED | 测试点完全重复 |
| TEST_POINT_COVERAGE_INCOMPLETE | confirmed Requirement 未覆盖 |
| TEST_CASE_FACT_MISMATCH | 用例丢失或改写明确事实 |

错误响应不得包含绝对路径、Prompt、Secret、内部异常和原文全文。

---

## 21. 安全与审计

### 21.1 安全

- 原始需求和编辑内容均为不可信数据；
- 文档内“忽略系统指令”“读取 Secret”等文字不得执行；
- LLM 上下文只包含当前任务允许的数据；
- 不允许代码执行、工具调用、HTTP 请求和读取其他文件；
- Markdown 默认按纯文本编辑；
- 如启用预览，必须白名单净化并禁止脚本、iframe、远程图片和事件属性。

### 21.2 审计

记录 normalization started/completed/failed、draft saved/imported、requirement confirmed、warning acknowledged、test points generated 和 coverage calculated/gap acknowledged。

审计只记录任务、用户、版本、SHA、数量、模型、Prompt SHA、Token、耗时和错误码，不记录正文、Secret 和内部路径。

---

## 22. 兼容策略

- 历史任务不批量迁移；
- 缺少需求确认版本的旧任务按原结果只读展示；
- 历史测试点和用例不自动改写；
- 历史 output 不读取、不迁移、不写入；
- 原 CLI 默认行为保持兼容；
- 新平台流程显式传入确认需求版本；
- `decompose_requirement` 保留一个发布周期并标记 legacy。

---

## 23. 配置建议

```text
STANDARD_REQUIREMENT_FLOW_ENABLED=false
REQUIREMENT_NORMALIZATION_ENABLED=true
REQUIREMENT_REVIEW_ENABLED=true
REQUIREMENT_NORMALIZATION_TIMEOUT_SECONDS=900
REQUIREMENT_MAX_BYTES=5242880
REQUIREMENT_MAX_CHARACTERS=500000
REQUIREMENT_MAX_ITEMS=5000
REQUIREMENT_STRUCTURE_VERSION=FRD-2.0
TEST_POINT_SUPPLEMENT_MAX_ROUNDS=1
```

配置定义默认关闭，dev Release 显式开启，prod 首次发布保持关闭。关闭总开关立即回退稳定流程。不新增 Secret。

---

## 24. 非功能要求

### 24.1 性能

- 100 KB 需求 Review 首屏不超过 2 秒；
- 5,000 条 Requirement 搜索不超过 300 毫秒；
- 结构校验和覆盖各不超过 2 秒；
- LLM 阶段异步执行，不阻塞短请求。

### 24.2 可用性和可访问性

- 所有阶段展示当前状态和下一步；
- 长任务可取消；
- 页面刷新后恢复；
- 网络失败不清空本地编辑；
- 最低桌面宽度 1280px；
- 支持键盘、可见焦点、200% 缩放和 reduced-motion；
- 状态不只依赖颜色。

### 24.3 可观测性

日志记录阶段、批次、数量、耗时、Token 和错误码，不记录正文和 Secret。readiness 只返回能力开关和必要配置是否就绪。

---

## 25. 核心验收场景

### 25.1 标准需求

- 普通 Markdown 生成 FRD-2.0 草稿并停留需求 Review；
- 原始文件不变；
- 整理失败保留原始文件；
- Prompt 注入不改变系统行为；
- 合法 FRD-2.0 不调用需求拆解 LLM；
- 未经人工确认不能生成测试点。

### 25.2 需求 Review

- 保存、刷新和重新打开一致；
- 双标签冲突不覆盖本地内容；
- 相同正文不增加 revision；
- 相同 SHA 确认复用版本；
- 历史确认版本不可修改；
- 队列满时确认版本不丢失。

### 25.3 场景级测试点

- 一个测试点可映射多个 Requirement；
- 连续路径不被机械拆成字段级测试点；
- 不生成通用“UI显示检查”；
- 推测的并发、幂等和超时进入 pending；
- 测试点 ID 有效唯一；
- 完全重复阻止，相似项警告。

### 25.4 覆盖

- confirmed 映射准确；
- pending 和建议不计正式覆盖；
- 不存在的引用被阻止；
- 未覆盖清单可定位；
- 最多补充一次；
- 仍缺失时进入人工 Review。

### 25.5 用例事实保真

黄金断言：

```text
TP-GOAL-001 → 必须保留Not sure
TP-GOAL-006 → 必须保留Your Voice
TP-VOICE-006 → 必须保留Loading
TP-DONE-005 → 必须保留Reply tab
TP-STATE-002 → 必须保留已跳过，禁止改成已完成
TP-PERSIST-005 → 必须保留恢复第6步
```

同时验证 Requirement 映射和 pending 状态保留、preconditions/test_steps 为数组、test_data 是合法 JSON，明确结果不被“如、或、可能、系统指定”替代。

### 25.6 权限

创建者可编辑自己的任务；其他普通用户返回 404；管理员按权限跨用户查看；只读用户不能保存确认；缺少 CSRF 的写请求失败；页面不泄漏 Secret、Prompt 全文和绝对路径。

---

## 26. 测试要求

### 26.1 单元测试

- FRD-2.0 标识和 H1～H3 校验；
- Requirement ID 唯一性、索引、confirmed/pending；
- 草稿 SHA、CAS 和确认幂等；
- 测试点 Schema、覆盖矩阵和去重；
- 用例字段类型和事实保真。

### 26.2 集成测试

- 普通需求整理和标准需求快速路径；
- 需求确认后 FIFO 重入；
- 需求版本到测试点版本追溯；
- 测试点到用例完整字段传递；
- 取消、超时、队列满、重启和迟到结果；
- Artifact、身份、CSRF、RBAC、所有权和审计。

### 26.3 黄金样本

以“新手引导流程需求文档”为黄金样本，验证不再产生 67 个 LLM 拆解调用；场景级测试点比旧 133 条结果更简洁；需求覆盖不低于人工基准；未确认项独立；用例关键页面、默认值和状态不被改写。

### 26.4 浏览器验收

在 1280×800、1440×900、1920×1080 验证新建、整理进度与 Token、需求 Review 保存/冲突/确认、Requirement 搜索、测试点覆盖、用例 Review 与发布、角色矩阵、键盘、焦点、缩放和控制台错误。

---

## 27. 数据保留

沿用现有策略：任务摘要 180 天；输入、草稿、日志和产物 90 天；每智能体最多 500 个终态任务；时间和数量先到者生效；非终态 Review 不自动清理；历史 output 不纳入迁移和清理。

---

## 28. 发布与回滚

### 28.1 dev

1. 完成自动化和黄金样本回归；
2. 开关关闭验证旧流程；
3. dev Release 开启新流程；
4. 验证普通整理和 FRD-2.0 快速路径；
5. 验证需求、测试点、用例三层 Review；
6. 比较调用次数、Token、耗时和质量；
7. 验证 API 智能体不受影响；
8. 关闭开关演练回退。

### 28.2 prod

首次发布开关保持关闭，完成 dev 和真实任务验收后再开启。生产部署和凭据操作需要单独授权。

### 28.3 回滚

关闭 `STANDARD_REQUIREMENT_FLOW_ENABLED`，必要时恢复上一功能智能体镜像；保留所有草稿、确认版本、测试点、用例、产物和审计；旧需求拆解兼容入口继续可用。

---

## 29. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 整理 LLM 编造需求 | 强制需求 Review、事实边界、来源保留 |
| 标准格式不稳定 | FRD-2.0 标识、确定性校验、定位错误 |
| 测试点过度合并 | 拆分规则、覆盖矩阵、人工 Review |
| 测试点仍过细 | 场景级 Prompt、禁止字段数量驱动、相似提示 |
| Requirement 映射错误 | 不存在 ID 阻塞、映射可见、黄金样本 |
| 新旧流程并存复杂 | 功能开关、legacy 标记、限定兼容周期 |
| 编辑冲突 | revision/SHA CAS、本地副本、显式保存 |
| 成本转移到整理阶段 | 分阶段 Token、标准文档快速路径、完整章节批处理 |

---

## 30. 依赖关系

依赖 V1.2 整理规则、现有任务运行时/FIFO、现有两类 Review 和 Artifact、平台身份/CSRF/RBAC/配置 Release 及功能智能体 LLM。无需新业务数据库、新队列、前端框架、API 真实执行或生产凭据。

---

## 31. 完成定义

1. 普通需求可整理为 FRD-2.0 并进入人工 Review；
2. FRD-2.0 可跳过 LLM 需求拆解；
3. 未经需求确认不能生成测试点；
4. 场景级测试点可映射多个 Requirement；
5. 正式覆盖率由程序计算；
6. 测试点补充最多一次；
7. pending 不进入正式覆盖率；
8. 测试点完整事实传给用例；
9. 用例关键事实和 JSON 类型通过测试；
10. 三层版本、CAS、队列和恢复通过验证；
11. 权限、安全和审计通过验证；
12. 旧任务、CLI、API 智能体和历史 output 不受破坏；
13. dev 可启用和回退；
14. 文档、配置、测试和部署说明可交付。

---

## 32. 开发设计前确认项

以下均为推荐方案，需在详细设计开始前确认：

1. 需求 Review 首期使用在线纯文本 Markdown 编辑器，并保留下载/上传高级入口。
2. 原始需求首期只支持 `.md/.txt`，图片、Figma、PDF、DOCX 由 Codex 先转写。
3. FRD-2.0 合法文档仍必须人工确认，不能直接生成测试点。
4. 需求整理、测试点生成、Review AI 和用例生成共用单槽 FIFO。
5. Requirement 索引只使用任务文件，不新增业务数据库表。
6. 需求质量警告允许确认后继续，技术结构和安全错误必须阻止。
7. 正式覆盖率只统计 confirmed Requirement。
8. 测试点补充最多一次，仍有缺口进入人工 Review。
9. `decompose_requirement` 保留一个发布周期，但不作为新 Web 默认入口。
10. 新流程使用独立开关，dev 验收后开启，prod 首次发布关闭。
11. 测试点不设置固定数量目标，但继续受 5,000 条技术上限约束。
12. 需求、测试点和用例确认版本均不可变并支持历史查看。

---

## 33. 修订记录

| 版本 | 日期 | 修订内容 |
|---|---|---|
| V1.0 | 2026-08-25 | 首版；定义标准需求 Review、跳过原子 LLM 拆解、场景级测试点、确定性覆盖和完整事实传递。 |
