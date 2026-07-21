# BugAgent v5.4 PRD

> Version: v5.4  
> Date: 2026-04-25  
> Status: Draft  
> Owner: Product + Engineering  
> Baseline: v5.3 已交付

---

## 1. 背景与现状

截至 `v5.3`，BugAgent 已具备完整的"信号接入 → 分诊 → AI分析 → AI修复 → PR提交"自动化链路，平台稳定性和智能效率有基础保障。

但当前修复链路存在三个结构性问题：

1. **修复路径单一**：只有 AI 自动修复一条路。AI 修复失败后，用户无法在系统内完成人工修复并提交 PR，只能跳到外部工具操作，导致状态脱节。
2. **PR 生命周期断裂**：PR 创建后系统不再跟踪。PR 被拒绝/关闭时，缺陷状态不会回退，也无法记录拒绝原因，形成"已提交但实际未合入"的假完成。
3. **Agent 无记忆**：每次分析/修复从零开始，不利用历史经验。同类缺陷反复犯同样的分析错误，修复成功率无法随使用积累提升。

`v5.4` 的核心目标是：**打通人工修复闭环，补齐 PR 生命周期管理，建立 Agent 记忆体系——让修复链路从"自动但脆弱"进化为"自动+人工协同且可积累"。**

---

## 2. v5.4 目标与非目标

### 2.1 目标（Goals）

1. 支持人工修复路径，用户可在系统内手动提交修复并关联 PR。
2. PR 被拒绝时自动回退缺陷状态，并记录拒绝历史。
3. 建立 Agent 记忆体系（迭代级 + 项目级），让 AI 分析和修复能利用历史经验。

### 2.2 非目标（Non-Goals）

1. 不在 v5.4 实现完整的在线代码编辑器（人工修复指"用户在外部完成代码修改后回系统登记"）。
2. 不在 v5.4 实现自动 PR 合并或 CI/CD 触发（仅跟踪 PR 状态变更）。
3. 不在 v5.4 实现跨项目的 Agent 记忆共享（记忆隔离在项目维度）。
4. 不在 v5.4 做 Agent 记忆的自动训练/微调（仅做 Prompt 注入式记忆）。

---

## 3. 核心问题定义（按优先级）

### P0（必须做）

1. **修复路径单一，AI 失败后无出路**
   - 现状：AI 修复失败 → 状态回退到 `pending_fix` → 只能再次触发 AI 修复，无法人工介入。
   - 影响：用户被迫脱离系统操作，状态脱节，缺陷生命周期不可控。

2. **PR 被拒绝后状态不回退**
   - 现状：PR 创建成功 → 缺陷进入 `pending_verify` → PR 被拒绝 → 缺陷仍停在 `pending_verify`。
   - 影响：缺陷看板数据失真，无法反映真实修复进度。

### P1（应该做）

1. **Agent 无记忆，同类缺陷反复低效分析**
   - 现状：每次 AI 分析/修复是无状态单次调用，不引用历史。
   - 影响：分析质量无法随使用积累提升，Token 消耗重复浪费。

---

## 4. 功能需求（FR）

### FR-1 人工修复路径（P0）

#### 4.1.1 问题本质

当前状态机 `pending_fix` → `fixing` → `pending_verify` 只服务于 AI 自动修复流程。用户在 AI 修复失败或不想等 AI 修复时，没有入口在系统内登记"我已手动修复"。

#### 4.1.2 方案

**新增状态 `manual_fixing`**，作为人工修复的中间态：

```
pending_fix ──→ fixing          (AI 自动修复)
pending_fix ──→ manual_fixing   (人工修复，新增)
manual_fixing ──→ pending_verify (人工提交修复完成)
manual_fixing ──→ pending_fix   (放弃人工修复，回退)
```

**具体能力**：

1. **触发人工修复**：在缺陷详情页，`pending_fix` 状态下新增"人工修复"按钮，点击后状态变为 `manual_fixing`。
2. **登记修复信息**：`manual_fixing` 状态下，用户可填写：
   - 修复描述（必填）
   - 关联 PR URL（选填，可在提交时填也可后续补填）
   - 修复分支名（选填）
3. **提交修复完成**：点击"修复完成"后，状态变为 `pending_verify`，系统自动创建一条 `FixTask`（`source=manual`）。
4. **放弃人工修复**：可回退到 `pending_fix`，重新选择 AI 修复或再次人工修复。
5. **补关联 PR**：`pending_verify` 状态下，仍可补填/修改关联的 PR URL。

#### 4.1.3 数据模型变更

**FixTask 新增字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `Source` | string | `"auto"` / `"manual"`，标识修复来源，默认 `"auto"` |
| `ManualDescription` | text | 人工修复描述（`source=manual` 时必填） |

**状态机变更**：

在 `DefectTransitionMatrix` 中新增：

```go
DefectStatusPendingFix: {
    ...existing,
    DefectStatusManualFixing: true,  // 新增
},
DefectStatusManualFixing: {
    DefectStatusPendingVerify: true,  // 提交修复完成
    DefectStatusPendingFix:    true,  // 放弃人工修复
},
```

新增状态常量：

```go
DefectStatusManualFixing = "manual_fixing"
```

#### 4.1.4 API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/defects/:id/manual-fix/start` | 开始人工修复，状态 → `manual_fixing` |
| POST | `/defects/:id/manual-fix/complete` | 提交人工修复完成，状态 → `pending_verify` |
| POST | `/defects/:id/manual-fix/abandon` | 放弃人工修复，状态 → `pending_fix` |
| PATCH | `/defects/:id/fix-tasks/:taskId/pr` | 补填/修改关联 PR URL |

#### 4.1.5 验收标准

1. `pending_fix` 状态下可触发人工修复，状态正确流转。
2. 人工修复完成后生成 `FixTask`（`source=manual`），包含修复描述和 PR URL。
3. 人工修复的 FixTask 在缺陷详情页与 AI 修复的 FixTask 统一展示，但标注来源。
4. 放弃人工修复后状态正确回退，不产生脏数据。

---

### FR-2 PR 拒绝处理与状态回退（P0）

#### 4.2.1 问题本质

当前 PR 创建后，系统不再跟踪其生命周期。PR 被拒绝（closed without merge）时：
- 缺陷仍停在 `pending_verify`，与实际状态不符。
- 无法追溯"这个缺陷的 PR 被拒绝过几次"。
- 无法基于拒绝原因指导后续修复。

#### 4.2.2 方案

**PR 状态跟踪 + Webhook 回调 + 拒绝记录**：

1. **FixTask 新增 PR 状态字段**：`PRStatus`，值为 `open` / `merged` / `closed` / `rejected`。
2. **新增 PR 拒绝记录模型**：`PRRejection`，记录每次 PR 被拒绝的详情。
3. **VCS Webhook 接收 PR 状态变更**：
   - GitHub: `pull_request` event（`closed` action, `merged=false`）
   - GitLab: `Merge Request` event（`state=closed`）
4. **PR 被拒绝时的处理逻辑**：
   - 新增一条 `PRRejection` 记录
   - FixTask 的 `PRStatus` 更新为 `rejected`
   - 缺陷状态回退：`pending_verify` → `pending_fix`
   - 发布评论通知："PR #xxx 被拒绝，原因：xxx，缺陷已回退到待修复"
5. **PR 被合并时的处理逻辑**：
   - FixTask 的 `PRStatus` 更新为 `merged`
   - 缺陷状态推进：`pending_verify` → `fixed`

#### 4.2.3 数据模型变更

**FixTask 新增字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `PRStatus` | string | `"open"` / `"merged"` / `"closed"` / `"rejected"`，默认 `"open"` |

**新增 PRRejection 模型**：

```go
type PRRejection struct {
    ID          uint   `gorm:"primaryKey" json:"id"`
    FixTaskID   uint   `gorm:"index;not null" json:"fixTaskId"`
    PRNumber    string `gorm:"size:50" json:"prNumber"`
    PRURL       string `gorm:"size:500" json:"prUrl"`
    RejectedBy  string `gorm:"size:100" json:"rejectedBy"`
    RejectReason string `gorm:"type:text" json:"rejectReason"`
    VCSProvider string `gorm:"size:20" json:"vcsProvider"`
    CreatedAt   int64  `json:"createdAt"`
}
```

#### 4.2.4 API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/inbound/vcs/webhook` | VCS Webhook 统一入口（GitHub/GitLab） |
| GET | `/defects/:id/fix-tasks/:taskId/rejections` | 获取某 FixTask 的 PR 拒绝记录列表 |
| POST | `/defects/:id/fix-tasks/:taskId/reject` | 手动标记 PR 被拒绝（用于 Webhook 未覆盖场景） |
| POST | `/defects/:id/fix-tasks/:taskId/merge` | 手动标记 PR 已合并 |

#### 4.2.5 Webhook 处理流程

```
VCS Webhook 到达
  → 验证签名（复用 v5.3 FR-2 签名校验能力）
  → 解析事件类型（PR closed / merged）
  → 查找关联 FixTask（通过 repo + PR number 匹配）
  → 如果 PR 被拒绝（closed & not merged）：
      → 创建 PRRejection 记录
      → 更新 FixTask.PRStatus = "rejected"
      → 缺陷状态回退到 pending_fix
      → 发布拒绝评论
  → 如果 PR 被合并：
      → 更新 FixTask.PRStatus = "merged"
      → 缺陷状态推进到 fixed
      → 发布合并评论
```

#### 4.2.6 验收标准

1. PR 被拒绝后，缺陷状态自动回退到 `pending_fix`。
2. `PRRejection` 记录包含拒绝人、原因、时间。
3. 缺陷详情页可查看 PR 拒绝历史。
4. PR 被合并后，缺陷状态自动推进到 `fixed`。
5. 手动标记 PR 拒绝/合并的 API 可用（作为 Webhook 不可用时的降级方案）。
6. Webhook 签名校验生效。

---

### FR-3 Agent 记忆体系（P1）

#### 4.3.1 问题本质

当前 AI 分析和修复是无状态调用，每次从零开始。这导致：
- 同类缺陷重复分析，浪费 Token。
- 项目特有的架构模式、编码规范无法被 AI 感知。
- 迭代内的上下文（如"本次迭代在做 React 18 迁移"）无法传递给 AI。

#### 4.3.2 方案

**两级记忆架构**：

| 维度 | 作用域 | 生命周期 | 典型内容 |
|------|--------|----------|----------|
| 迭代级记忆 | 单个迭代 | 随迭代归档 | "本次迭代在做支付模块重构"、"API 路径从 /api/v1 迁移到 /api/v2" |
| 项目级记忆 | 整个项目 | 持久 | "本项目使用 Next.js App Router"、"错误处理统一用 Result<T> 模式"、"数据库用 Prisma ORM" |

**记忆来源**：

1. **自动提取**：AI 分析/修复完成后，自动从结果中提取可复用的知识条目（架构模式、常见错误模式、修复策略）。
2. **人工录入**：用户可在项目/迭代设置中手动添加记忆条目。
3. **PR 拒绝反馈**：PR 被拒绝时，拒绝原因自动沉淀为记忆条目（避免同类修复策略再次被拒）。

**记忆注入**：AI 分析和修复的 Prompt 中，在上下文区域注入匹配的记忆条目。注入规则：
- 迭代级记忆：当前缺陷所属迭代的所有记忆条目。
- 项目级记忆：当前缺陷所属项目的所有记忆条目。
- 注入总量控制：单次注入不超过 2000 token，按相关度排序截断。

#### 4.3.3 数据模型

**新增 AgentMemory 模型**：

```go
type AgentMemory struct {
    ID           uint   `gorm:"primaryKey" json:"id"`
    ProjectID    uint   `gorm:"index;not null" json:"projectId"`
    IterationID  *uint  `gorm:"index" json:"iterationId"`       // nil = 项目级
    Category     string `gorm:"size:30;not null" json:"category"`
    Content      string `gorm:"type:text;not null" json:"content"`
    Source       string `gorm:"size:20;not null" json:"source"` // "auto_extract" / "manual" / "pr_rejection"
    SourceRefID  *uint  `json:"sourceRefId"`                    // 来源关联ID（FixTaskID / PRRejectionID）
    RelevanceScore float64 `gorm:"default:0" json:"relevanceScore"`
    Enabled      bool   `gorm:"default:true" json:"enabled"`
    CreatedBy    uint   `json:"createdBy"`
    CreatedAt    int64  `json:"createdAt"`
    UpdatedAt    int64  `json:"updatedAt"`
}
```

**Category 枚举**：

| 值 | 说明 |
|---|---|
| `architecture` | 项目架构模式（框架、目录结构、设计模式） |
| `convention` | 编码规范（命名、错误处理、日志模式） |
| `common_error` | 常见错误模式及根因 |
| `fix_strategy` | 有效修复策略 |
| `avoid_strategy` | 被拒绝/失败的修复策略（来自 PR 拒绝） |
| `iteration_context` | 迭代级上下文（本次迭代做什么） |

#### 4.3.4 自动提取逻辑

AI 分析/修复完成后，增加一轮"记忆提取"调用：

1. 输入：分析报告 / 修复结果 + 缺陷信息。
2. Prompt 要求 AI 输出结构化的记忆条目（category + content）。
3. 去重：与现有记忆做语义相似度比对，相似度 > 0.85 的合并（更新 content，保留更高 relevanceScore）。
4. 存储：写入 `AgentMemory`，`source=auto_extract`。

**PR 拒绝时自动提取**：

PR 被拒绝时，自动生成一条 `avoid_strategy` 类型的记忆：
- Content 格式：`"修复策略 [简要描述] 在 [场景] 下被拒绝，原因：[rejectReason]"`
- Source: `pr_rejection`
- Scope: 项目级（因为修复策略的适用范围通常跨迭代）

#### 4.3.5 记忆注入逻辑

在 AI 分析和修复的 Prompt 构建阶段：

1. 查询当前缺陷所属迭代的所有启用记忆（迭代级）。
2. 查询当前缺陷所属项目的所有启用记忆（项目级）。
3. 合并去重（迭代级优先）。
4. 按 `relevanceScore` 降序排列。
5. 截断到 2000 token 上限。
6. 注入到 Prompt 的 `## Project Knowledge` 区块。

#### 4.3.6 API 变更

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/projects/:id/memories` | 获取项目级记忆列表 |
| GET | `/projects/:id/iterations/:iterId/memories` | 获取迭代级记忆列表 |
| POST | `/projects/:id/memories` | 新增项目级记忆 |
| POST | `/projects/:id/iterations/:iterId/memories` | 新增迭代级记忆 |
| PUT | `/projects/:id/memories/:memoryId` | 编辑记忆条目 |
| DELETE | `/projects/:id/memories/:memoryId` | 删除记忆条目 |
| PATCH | `/projects/:id/memories/:memoryId/toggle` | 启用/禁用记忆条目 |

#### 4.3.7 验收标准

1. AI 分析/修复完成后，`AgentMemory` 表自动新增记忆条目。
2. 后续同项目/迭代的 AI 分析 Prompt 中包含已积累的记忆内容。
3. 用户可在项目/迭代设置中查看、新增、编辑、删除、启禁用记忆条目。
4. PR 拒绝时自动生成 `avoid_strategy` 记忆。
5. 记忆注入总量不超过 2000 token。
6. 语义去重生效（相似记忆不重复存储）。

---

## 5. 迭代计划

> 节奏建议：每迭代 2 周，总计 3 个迭代（6 周）。  
> 优先顺序：修复闭环 > PR 生命周期 > Agent 记忆。

### Iteration 5.4.1（P0）- 人工修复路径

目标：打通人工修复闭环，让 AI 修复失败不再是死胡同。

必须完成：
1. 新增 `manual_fixing` 状态及状态机转换。
2. 人工修复 API（start / complete / abandon）。
3. FixTask `Source` 字段区分 AI/人工来源。
4. 缺陷详情页人工修复交互（按钮、表单、状态展示）。
5. 补关联 PR 的 API 和 UI。

交付物：
1. 人工修复完整可用流程。
2. AI 修复与人工修复在 FixTask 列表中统一展示且可区分。

### Iteration 5.4.2（P0）- PR 生命周期管理

目标：PR 状态可跟踪，拒绝自动回退，拒绝历史可追溯。

必须完成：
1. FixTask `PRStatus` 字段及状态更新逻辑。
2. `PRRejection` 模型及 CRUD。
3. VCS Webhook 接入（GitHub PR closed/merged 事件）。
4. PR 拒绝 → 状态回退 + 评论通知。
5. PR 合并 → 状态推进 + 评论通知。
6. 手动标记 PR 拒绝/合并的降级 API。
7. 缺陷详情页展示 PR 拒绝历史。

交付物：
1. PR 状态自动跟踪可用。
2. PR 拒绝后缺陷状态正确回退。
3. 拒绝历史可在缺陷详情页查看。

### Iteration 5.4.3（P1）- Agent 记忆体系

目标：AI 分析和修复能利用历史经验，随使用积累提升质量。

必须完成：
1. `AgentMemory` 模型及 CRUD API。
2. 自动提取逻辑（分析/修复完成后提取记忆）。
3. 记忆注入逻辑（Prompt 中注入记忆）。
4. PR 拒绝自动沉淀 `avoid_strategy` 记忆。
5. 语义去重机制。
6. 项目/迭代设置中的记忆管理 UI。

交付物：
1. Agent 记忆自动积累且可注入 AI Prompt。
2. 记忆管理界面可用。
3. PR 拒绝经验自动沉淀。

---

## 6. 里程碑与成功指标

### 里程碑

1. M1（第 2 周）：人工修复路径完整可用，AI 修复失败不再是死胡同。
2. M2（第 4 周）：PR 生命周期闭环，拒绝自动回退，拒绝历史可追溯。
3. M3（第 6 周）：Agent 记忆体系上线，AI 分析可利用历史经验。

### 成功指标

1. 人工修复使用率：AI 修复失败的缺陷中，≥ 50% 通过人工修复路径完成。
2. PR 状态同步准确率：≥ 95% 的 PR 状态变更在 5 分钟内反映到缺陷状态。
3. PR 拒绝后状态回退率：100%（PR 被拒绝的缺陷必须回退到 `pending_fix`）。
4. Agent 记忆覆盖率：活跃项目中 ≥ 80% 的 AI 分析调用注入了记忆上下文。
5. 重复分析减少：同项目同类缺陷的 AI 分析 Token 消耗较无记忆基线下降 ≥ 15%。

---

## 7. 风险与对策

1. **风险：VCS Webhook 配置门槛高**
   - 对策：提供手动标记 API 作为降级方案；Webhook 配置提供详细文档和一键测试。
2. **风险：Agent 记忆自动提取质量不稳定**
   - 对策：提取结果默认 `enabled=true` 但用户可禁用；首版不做语义去重的精确匹配，用关键词+简单相似度即可。
3. **风险：记忆注入增加 Prompt 长度导致成本上升**
   - 对策：硬限 2000 token 上限；按 relevanceScore 排序截断；用户可禁用低价值记忆。
4. **风险：人工修复与 AI 修复的 FixTask 混淆**
   - 对策：`Source` 字段明确区分；UI 上用标签/颜色区分来源；查询 API 支持 `source` 过滤。

---

## 8. v5.4 最终优先级结论

如果资源不足，按以下顺序确保收益最大化：

1. **必须先做**：`FR-1 人工修复路径` + `FR-2 PR 拒绝处理` — 这是修复链路闭环的硬需求，不做则现有流程有结构性缺陷。
2. **第二优先**：`FR-3 Agent 记忆体系` — 这是质量提升的加速器，有则加分，无则不影响基本功能。

这条顺序保证：先把修复链路的"断头路"接通，再通过记忆体系提升 AI 效率和质量。
