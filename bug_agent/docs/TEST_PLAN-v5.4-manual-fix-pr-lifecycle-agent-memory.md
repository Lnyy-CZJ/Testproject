# BugAgent v5.4 测试计划

> Date: 2026-04-25  
> Scope: `PRD-v5.4` 全部（P0 + P1）  
> 基于文档: `PRD-v5.4-manual-fix-pr-lifecycle-agent-memory.md` / `DESIGN-v5.4-manual-fix-pr-lifecycle-agent-memory.md`

---

## 1. 测试范围

### P0

1. 人工修复路径（状态流转 + FixTask 创建 + PR 关联）。
2. PR 生命周期管理（VCS Webhook + 手动标记 + 状态回退/推进 + 拒绝历史）。

### P1

1. Agent 记忆体系（自动提取 + 注入 + 去重 + PR 拒绝沉淀 + CRUD）。

---

## 2. 测试策略

1. 单元测试：状态机转换、Service 逻辑、去重算法、Prompt 构建。
2. 集成测试：API 参数/权限/错误码、Webhook 签名校验、数据库事务。
3. E2E 测试：人工修复完整流程、PR 拒绝回退流程、记忆注入验证。
4. 人工冒烟：前端交互、Webhook 联调、记忆管理界面。

---

## 3. 关键测试用例（按模块）

## 3.1 P0-人工修复路径

### 自动化

1. `MF-01` `pending_fix` 状态下调用 `start` API → 状态变为 `manual_fixing`。
2. `MF-02` 非 `pending_fix` 状态下调用 `start` API → 返回 400/409。
3. `MF-03` `manual_fixing` 状态下调用 `complete` API（含 description + prUrl）→ 状态变为 `pending_verify`，FixTask 创建（source=manual）。
4. `MF-04` `complete` API 缺少 description → 返回 400。
5. `MF-05` `manual_fixing` 状态下调用 `abandon` API → 状态回退为 `pending_fix`。
6. `MF-06` 放弃后不产生 FixTask 记录。
7. `MF-07` `pending_verify` 状态下调用 `UpdateFixTaskPR` → PRURL 更新成功。
8. `MF-08` FixTask `source` 字段：AI 修复为 `auto`，人工修复为 `manual`。
9. `MF-09` 人工修复 FixTask 不含 AI 相关字段（AIProvider 等为空）。
10. `MF-10` StatusChange 记录完整（from/to/comment/changedBy）。

### 人工

1. `MF-M01` 缺陷详情页"人工修复"按钮可见且可点击。
2. `MF-M02` 人工修复 Drawer 表单校验（description 必填）。
3. `MF-M03` FixTask 列表中 AI/人工来源标签正确区分。
4. `MF-M04` 放弃人工修复后页面状态正确刷新。

验收标准：

1. `pending_fix` → `manual_fixing` → `pending_verify` 完整流程 PASS。
2. 放弃回退不产生脏数据。
3. AI/人工 FixTask 统一展示且可区分。

---

## 3.2 P0-PR 生命周期管理

### 自动化

1. `PR-01` FixTask 创建后 `PRStatus` 默认为 `open`。
2. `PR-02` GitHub Webhook（PR closed, merged=false）→ FixTask `PRStatus=rejected`，缺陷状态回退为 `pending_fix`。
3. `PR-03` GitHub Webhook（PR closed, merged=true）→ FixTask `PRStatus=merged`，缺陷状态推进为 `fixed`。
4. `PR-04` GitLab Webhook（MR state=closed）→ 同 PR-02 逻辑。
5. `PR-05` GitLab Webhook（MR state=merged）→ 同 PR-03 逻辑。
6. `PR-06` PR 拒绝后 `PRRejection` 记录包含 rejectedBy/rejectReason/createdAt。
7. `PR-07` PR 拒绝后发布评论（含拒绝原因）。
8. `PR-08` 手动标记 PR 拒绝 API → 同 Webhook 拒绝逻辑。
9. `PR-09` 手动标记 PR 合并 API → 同 Webhook 合并逻辑。
10. `PR-10` 获取 PR 拒绝记录列表 API 返回正确。
11. `PR-11` Webhook 签名校验失败 → 请求被拒绝。
12. `PR-12` Webhook 无法匹配 FixTask → 不报错，记录日志。
13. `PR-13` 非 `pending_verify` 状态的缺陷，PR 拒绝不触发状态回退。
14. `PR-14` 多次 PR 拒绝（修了再提再被拒）→ 多条 PRRejection 记录。

### 人工联调

1. `PR-M01` 使用 ngrok/localtunnel 暴露本地 Webhook 端点，GitHub 实际推送验证。
2. `PR-M02` 手动标记 PR 拒绝/合并按钮可用且结果正确。
3. `PR-M03` FixTask 卡片 PR 状态标签颜色正确（open=黄，merged=绿，rejected=红）。
4. `PR-M04` 拒绝历史列表展示正确。

验收标准：

1. PR 拒绝后缺陷状态 100% 回退。
2. PR 合并后缺陷状态正确推进。
3. 拒绝历史完整可追溯。
4. 手动标记 API 作为降级方案可用。

---

## 3.3 P1-Agent 记忆体系

### 自动化

1. `MEM-01` AI 分析完成后 `agent_memories` 表新增记录（source=auto_extract）。
2. `MEM-02` AI 修复完成后 `agent_memories` 表新增记录（source=auto_extract）。
3. `MEM-03` 记忆条目 category 在枚举范围内。
4. `MEM-04` 记忆注入：后续 AI 分析 Prompt 中包含已积累记忆。
5. `MEM-05` 记忆注入总量不超过 2000 token。
6. `MEM-06` 迭代级记忆仅在当前迭代缺陷的 AI 调用中注入。
7. `MEM-07` 项目级记忆在项目所有缺陷的 AI 调用中注入。
8. `MEM-08` 禁用的记忆不注入。
9. `MEM-09` 语义去重：相似度 > 0.7 的记忆合并而非重复插入。
10. `MEM-10` PR 拒绝时自动生成 `avoid_strategy` 记忆（source=pr_rejection）。
11. `MEM-11` PR 拒绝记忆为项目级（iteration_id=NULL）。
12. `MEM-12` CRUD API：创建/读取/更新/删除/启禁用 均正常。
13. `MEM-13` 非项目成员无法操作记忆（权限校验）。
14. `MEM-14` 记忆列表支持 category 过滤。

### 人工

1. `MEM-M01` 项目设置"Agent 记忆"Tab 可见且数据正确。
2. `MEM-M02` 迭代设置"Agent 记忆"Tab 可见且数据正确。
3. `MEM-M03` 手动新增记忆条目成功。
4. `MEM-M04` 编辑/删除/启禁用记忆条目成功。
5. `MEM-M05` AI 分析详情中展示注入记忆数量。

验收标准：

1. AI 分析/修复后自动提取记忆。
2. 后续 AI 调用注入记忆。
3. PR 拒绝自动沉淀 `avoid_strategy`。
4. 记忆管理界面可用。

---

## 4. 回归测试清单（必须）

1. 登录、项目切换、迭代切换不受影响。
2. 缺陷创建、缺陷详情、评论、AI 分析、AI 修复链路不受影响。
3. 问题池筛选、路由治理、回归预防、质量情报可正常加载。
4. 通知中心、个人中心、用户管理核心操作可用。
5. 现有状态机流转（new → pending_assign → ... → completed）不受 `manual_fixing` 新状态影响。
6. FixTask 列表和详情页正常展示（新增字段不破坏现有展示）。

---

## 5. 执行计划

### 阶段 A（Iteration 5.4.1）

1. 人工修复 API 单测 + 集成测试先过。
2. 前端交互 E2E + 人工冒烟。
3. 状态机回归验证。

### 阶段 B（Iteration 5.4.2）

1. PRRejection 模型 + 手动标记 API 单测。
2. VCS Webhook 集成测试（Mock GitHub/GitLab payload）。
3. Webhook 联调（人工）。
4. 状态回退/推进回归验证。

### 阶段 C（Iteration 5.4.3）

1. AgentMemory 模型 + CRUD API 单测。
2. 记忆提取逻辑单测（Mock AI 响应）。
3. 记忆注入逻辑单测（验证 Prompt 包含记忆）。
4. 去重算法单测。
5. PR 拒绝沉淀记忆集成测试。
6. 记忆管理界面 E2E + 人工冒烟。
7. 全链路回归。

---

## 6. 通过标准（Go/No-Go）

1. P0 用例通过率 100%。
2. P1 用例通过率 >= 95%，且无阻塞缺陷。
3. 核心回归链路全绿。
4. 数据库迁移向后兼容（老数据不受影响）。
5. 无高危安全缺陷残留（Webhook 签名校验生效）。
