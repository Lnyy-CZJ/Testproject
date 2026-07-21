# BugAgent v5.4 开发迭代计划

> Date: 2026-04-25  
> Scope: `PRD-v5.4` 全部（P0 + P1）  
> 目标: 打通人工修复闭环，补齐 PR 生命周期，建立 Agent 记忆体系

---

## 1. 迭代目标

1. P0-1：人工修复路径——新增 `manual_fixing` 状态，支持人工修复登记和 PR 关联。
2. P0-2：PR 生命周期管理——VCS Webhook 跟踪 PR 状态，拒绝自动回退，拒绝历史可追溯。
3. P1-1：Agent 记忆体系——两级记忆存储，自动提取+注入，PR 拒绝经验沉淀。

---

## 2. 迭代拆分（6周，3个迭代）

### Iteration 5.4.1（Week 1-2）— 人工修复路径（P0）

目标：AI 修复失败不再是死胡同，用户可在系统内完成人工修复。

任务：

**Backend**：

1. `model/workflow.go`：新增 `DefectStatusManualFixing` 常量，更新 `AllDefectStatuses` 和 `DefectTransitionMatrix`。
2. `model/models.go`：FixTask 新增 `Source`（default:auto）和 `ManualDescription` 字段。
3. `model/models.go`：AutoMigrate 注册新字段。
4. `service/manual_fix.go`（新建）：
   - `StartManualFix`：校验状态 → 更新为 `manual_fixing` → 记录 StatusChange。
   - `CompleteManualFix`：校验状态 → 创建 FixTask（source=manual）→ 更新为 `pending_verify` → 记录 StatusChange → 发布评论。
   - `AbandonManualFix`：校验状态 → 回退为 `pending_fix` → 记录 StatusChange。
   - `UpdateFixTaskPR`：校验 FixTask 归属 → 更新 PRURL/PRNumber。
5. `handler/manual_fix.go`（新建）：4 个 API Handler。
6. `router/router.go`：注册人工修复路由组。

**Frontend**：

7. 缺陷详情页：`pending_fix` 状态下新增"人工修复"按钮。
8. 人工修复 Drawer/Modal：修复描述（必填）、PR URL（选填）、修复分支（选填）。
9. `manual_fixing` 状态展示："人工修复中"标签 + "提交修复完成"/"放弃"操作。
10. FixTask 列表：`source` 字段区分标签（AI=蓝色"自动"，Manual=绿色"手动"）。
11. `pending_verify` 状态下 PR URL 可编辑（补关联）。

完成标准：

1. `pending_fix` → `manual_fixing` → `pending_verify` 完整流程可用。
2. 放弃人工修复正确回退，不产生脏数据。
3. AI/人工 FixTask 统一展示且可区分。

---

### Iteration 5.4.2（Week 3-4）— PR 生命周期管理（P0）

目标：PR 状态可跟踪，拒绝自动回退，拒绝历史可追溯。

任务：

**Backend**：

1. `model/models.go`：FixTask 新增 `PRStatus` 字段（default:open），新增 `PRRejection` 模型。
2. `model/models.go`：AutoMigrate 注册新表和新字段。
3. `service/vcs_webhook.go`（新建）：
   - `HandleWebhook`：分发到 GitHub/GitLab 处理器。
   - `handleGitHubPREvent`：解析 PR closed/merged 事件。
   - `handleGitLabMREvent`：解析 MR closed/merged 事件。
   - `findFixTaskByPR`：通过 repo URL + PR number 反查 FixTask。
   - `handlePRRejected`：创建 PRRejection → 更新 PRStatus → 回退缺陷状态 → 发布评论。
   - `handlePRMerged`：更新 PRStatus → 推进缺陷状态 → 发布评论。
4. `handler/pr_lifecycle.go`（新建）：
   - `ManualRejectPR`：手动标记 PR 被拒绝。
   - `ManualMergePR`：手动标记 PR 已合并。
   - `ListPRRejections`：获取 PR 拒绝记录列表。
5. `router/router.go`：注册 VCS Webhook 路由（公开）和 PR 生命周期路由（需认证）。
6. `fix_engine.go`：`finalizeFixSuccess` 中设置 `PRStatus = "open"`。

**Frontend**：

7. FixTask 卡片：PR 状态标签（open=黄，merged=绿，rejected=红）。
8. PR 拒绝历史：FixTask 详情中展示 PRRejection 列表。
9. 手动标记按钮：`pending_verify` 状态下"标记 PR 被拒绝"/"标记 PR 已合并"。
10. 状态回退提示：PR 被拒绝后缺陷详情页显示回退通知。

完成标准：

1. GitHub Webhook 触发 PR 拒绝 → 缺陷状态自动回退。
2. GitHub Webhook 触发 PR 合并 → 缺陷状态自动推进。
3. 手动标记 API 可用（降级方案）。
4. 拒绝历史可在缺陷详情页查看。

---

### Iteration 5.4.3（Week 5-6）— Agent 记忆体系（P1）

目标：AI 分析和修复能利用历史经验，随使用积累提升质量。

任务：

**Backend**：

1. `model/models.go`：新增 `AgentMemory` 模型及 Category/Source 常量。
2. `model/models.go`：AutoMigrate 注册新表。
3. `service/agent_memory.go`（新建）：
   - CRUD：ListMemories / CreateMemory / UpdateMemory / DeleteMemory / ToggleMemory。
   - 自动提取：ExtractMemoriesFromAnalysis / ExtractMemoriesFromFix / ExtractMemoryFromPRRejection。
   - 注入：BuildMemoryContext（查询+排序+截断+格式化）。
   - 去重：jaccardSimilarity + 合并逻辑。
4. `ai/memory_prompts.go`（新建）：记忆提取 Prompt 模板。
5. `service/analysis.go`：在 `analyzeDefect` 中调用 `BuildMemoryContext` 注入记忆到 Prompt。
6. `service/fix_engine.go`：在 `executeFixWorkflow` 中调用 `BuildMemoryContext` 注入记忆到修复上下文。
7. `service/vcs_webhook.go`：在 `handlePRRejected` 中调用 `ExtractMemoryFromPRRejection` 沉淀记忆。
8. `handler/agent_memory.go`（新建）：7 个 API Handler。
9. `router/router.go`：注册 Agent 记忆路由组。

**Frontend**：

10. 项目设置页：新增"Agent 记忆"Tab，展示项目级记忆列表。
11. 迭代设置页：新增"Agent 记忆"Tab，展示迭代级记忆列表。
12. 记忆卡片：category 标签 + content + 来源 + 启用状态。
13. 操作：新增、编辑、删除、启禁用记忆条目。
14. AI 分析详情：展示注入的记忆条目数量和 token 估算。

完成标准：

1. AI 分析/修复后 `agent_memories` 表自动新增条目。
2. 后续 AI 调用 Prompt 中包含记忆内容。
3. PR 拒绝时自动沉淀 `avoid_strategy` 记忆。
4. 记忆管理界面可用。

---

## 3. 角色分工

### Backend

1. Iteration 5.4.1：状态机扩展 + FixTask 模型变更 + ManualFixService + Handler + 路由。
2. Iteration 5.4.2：PRRejection 模型 + VCSWebhookService + PRLifecycle Handler + 路由。
3. Iteration 5.4.3：AgentMemory 模型 + AgentMemoryService + 记忆提取 Prompt + 注入集成 + Handler + 路由。

### Frontend

1. Iteration 5.4.1：人工修复按钮 + Drawer + 状态展示 + FixTask 来源标签 + PR 补关联。
2. Iteration 5.4.2：PR 状态标签 + 拒绝历史 + 手动标记按钮 + 回退提示。
3. Iteration 5.4.3：项目/迭代记忆 Tab + 记忆卡片 + CRUD 操作 + AI 分析记忆展示。

### QA

1. Iteration 5.4.1：人工修复流程 E2E + 状态流转验证 + 边界条件。
2. Iteration 5.4.2：Webhook 联调 + 手动标记 + 状态回退/推进 + 拒绝历史。
3. Iteration 5.4.3：记忆自动提取 + 注入验证 + 去重 + PR 拒绝沉淀 + CRUD。

---

## 4. 依赖关系

```
Iteration 5.4.1 (人工修复) ──→ Iteration 5.4.2 (PR生命周期)
                                    │
                                    └──→ Iteration 5.4.3 (Agent记忆)
```

- 5.4.2 依赖 5.4.1：PR 生命周期需要 FixTask 有 `PRStatus` 字段，且人工修复也需要 PR 关联能力。
- 5.4.3 依赖 5.4.2：PR 拒绝沉淀记忆需要 `PRRejection` 模型。
- 5.4.1 可独立开发。

---

## 5. 风险与缓解

1. **风险：VCS Webhook 配置门槛高**
   - 缓解：首版以手动标记 API 为主，Webhook 作为增强能力。提供 Webhook 配置文档和测试工具。

2. **风险：Agent 记忆自动提取质量不稳定**
   - 缓解：提取结果默认启用但用户可禁用；首版用 Jaccard 去重而非精确语义匹配。

3. **风险：记忆注入增加 Prompt 长度**
   - 缓解：硬限 2000 token；按 relevanceScore 截断；用户可禁用低价值记忆。

4. **风险：人工修复与 AI 修复 FixTask 混淆**
   - 缓解：`Source` 字段明确区分；UI 用标签/颜色区分；API 支持 source 过滤。

---

## 6. 交付出口（Exit Criteria）

1. P0 两项全部上线：人工修复路径 + PR 生命周期管理。
2. P1 一项可用：Agent 记忆体系。
3. 对应自动化与冒烟用例通过，无 P0/P1 回归阻塞。
4. 数据库迁移脚本可执行且向后兼容。
