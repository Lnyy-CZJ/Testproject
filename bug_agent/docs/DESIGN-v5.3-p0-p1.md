# BugAgent v5.3 设计文档（P0 + P1）

> Date: 2026-04-18  
> Scope: `PRD-v5.3` P0/P1  
> 对应计划: `DEV_PLAN-v5.3-p0-p1.md`

---

## 1. 设计目标

1. 保证“搜索/筛选栏”跨页面视觉与交互一致，不再重复造轮子。
2. Webhook 入站具备签名校验能力，默认安全。
3. 在不引入复杂模型平台前提下，实现可解释的推荐分配与 AGENT 推荐。

---

## 2. 总体架构改动

### 2.1 UI 一致性层（Frontend）

1. 以 `PageFilterBar` 作为唯一筛选栏容器。
2. 统一搜索输入模式：`Input + prefix`（避免 `Input.Search` 的样式分叉风险）。
3. 保持输入高度、圆角、边框、placeholder 的全局 token 一致。
4. 页面仅负责“筛选字段配置”，不再维护私有搜索样式。

### 2.2 安全校验层（Backend）

1. Webhook 连接器配置存储 `secret`（密文）。
2. 入站处理链路新增 `VerifySignatureMiddleware`：
   - 读取 header: `X-Hub-Signature-256`
   - 计算 `sha256=` + HMAC(payload, secret)
   - 常量时间比较
3. 验签失败直接拒绝 + 记录审计事件。

### 2.3 推荐服务层（Backend + Frontend）

1. 新增 `RecommendationService`：
   - `RecommendAssignees(defectId)`：返回 Top-N 用户推荐
   - `RecommendAgents(defectId)`：返回 AGENT 类型推荐
2. 前端在指派面板展示推荐结果与推荐理由。
3. 采纳行为写入反馈表，用于后续迭代优化。

---

## 3. 详细设计

## 3.1 搜索/筛选栏统一方案

### 前端组件边界

1. `PageFilterBar`：布局容器（filters/actions/result）。
2. `Input`：用于搜索输入，统一 `prefix=<SearchOutlined/>`。
3. `Select`：统一 `allowClear` 与宽度策略。

### 约束

1. 列表页禁止新增私有 `Input.Search`。
2. 搜索触发统一为：
   - 回车触发
   - clear 重置
   - 显式刷新按钮（如页面有）。

### 回归防线

1. 关键页面快照对比。
2. CSS 规则集中在 `index.css`，避免页面内局部 hack。

---

## 3.2 Webhook 签名校验设计

### 配置模型（逻辑）

1. `Connector.secretEncrypted`：加密后的签名密钥。
2. `Connector.signatureRequired`：是否强制验签（生产默认 true）。

### 验签流程

1. 接收原始请求体 `rawBody`。
2. 读取 `X-Hub-Signature-256`，格式 `sha256=<hex>`。
3. 使用连接器 `secret` 计算 `expected`。
4. 比较 `expected` 与 header 签名：
   - 成功：继续处理标准化流程
   - 失败：返回 401/403 + 记录审计

### 安全点

1. 使用常量时间比较函数。
2. 审计记录不落明文 secret。
3. 可增加重放保护（时间戳/nonce）作为后续增强项。

---

## 3.3 智能推荐分配 v1 设计

### 输入

1. 缺陷属性：类型、模块、严重级别、优先级。
2. 用户画像：历史处理数量、同类型处理成功率、当前处理中数量。

### 评分公式（v1）

`score = typeMatch*0.4 + moduleMatch*0.2 + successRate*0.25 + workloadPenalty*0.15`

说明：

1. `typeMatch/moduleMatch` 来自规则映射和历史统计。
2. `workloadPenalty` 对高负载用户降权。
3. 输出 Top-3 用户及理由。

### 输出结构

1. userId
2. score
3. reasons[]（如“同类缺陷处理 18 次，成功率 92%”）

---

## 3.4 AGENT 自动推荐 v1 设计

### 推荐规则（初版）

1. `ui` -> `frontend`, `ui_agent`
2. `functional/backend` -> `backend`, `product`
3. `performance/security` -> `backend`, `test`
4. `compatibility` -> `client`, `test`

### 决策融合

1. 先规则推荐。
2. 再根据历史命中率排序。
3. 返回推荐列表 + 置信度。

### 人工覆盖

1. 用户可手动改选。
2. 覆盖行为写入反馈表（用于评估规则质量）。

---

## 4. API 与数据变更（建议）

1. `GET /api/v1/defects/:id/recommend-assignees`
2. `GET /api/v1/defects/:id/recommend-agents`
3. `POST /api/v1/recommendations/feedback`
   - body: `{ defectId, type, recommended, accepted, selected }`

数据表建议：

1. `recommendation_feedback`
2. `user_skill_profile`（可缓存或定时汇总）

---

## 5. 兼容性与迁移

1. 老页面可逐页切换到统一筛选栏，不需一次性重写。
2. Webhook 验签采用“配置驱动”上线，先灰度启用。
3. 推荐能力默认“建议模式”，不改变既有手动流程。

---

## 6. 验收要点

1. UI：核心页面筛选/搜索栏一致，无双边框/空白按钮/错位。
2. 安全：Webhook 非法签名被拒绝并可追溯。
3. 推荐：可返回可解释推荐，且可被采纳记录。

