# Dating 凭证就绪度可诊断化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Dating/test Gateway Session 自动续期使用错误 URL 的问题，并让任务预检与平台配置控制面直接展示未就绪凭证的状态、原因、过期时间、Scope 和正确修复入口。

**Architecture:** 平台继续区分普通 Release 配置与个人 Credential；Credential Secret 不回显。平台 Runtime Config 额外返回非敏感的 Profile 状态元数据，接口自动化工具把它映射为资产级预检错误；平台普通配置页只增加当前 Scope 的凭证状态摘要和入口，不把凭证值混入 Release。

**Tech Stack:** FastAPI、SQLAlchemy、React、TypeScript、Flask、Jinja2、原生 JavaScript、pytest、Vitest。

**Spec:** `/Users/admin/Testproject/api-autotest/docs/接口自动化多项目支持与Dating接入-PRD.md`

## Global Constraints

- dev 平台只对应 test 接口环境，prod 平台只对应 prod 接口环境。
- Runtime Scope、Release、Credential 与运行快照由平台管理；测试资产由项目包管理。
- Credential Secret 不进入普通配置、不回显到浏览器、不写入预检错误。
- 保留当前工作区已有改动，不创建 worktree，不提交或覆盖无关文件。
- 先运行失败测试，再做最小实现；完成后重建本机 Docker 服务并进行真实页面验收。

---

### Task 1: 修复 Dating Gateway Session 自动续期 URL

**Files:**
- Modify: `/Users/admin/Testproject/test-platform/backend/app/jobs/credential_agent.py`
- Test: `/Users/admin/Testproject/test-platform/backend/tests/test_phase2.py`

**Interfaces:**
- Consumes: Release 中的 `gateway.base_url` 与 `gateway.path`。
- Produces: `_gateway_session(normal, secrets)` 对 RefreshSession 与 CreateAnonymousSession 统一调用完整 Gateway URL。

- [ ] **Step 1: 写失败测试**

  在 Gateway Session 单元测试中记录 `_post_json` 收到的 URL，并断言 `https://gateway.example.test` 与 `/dating/gateway/invoke` 被安全拼接为 `https://gateway.example.test/dating/gateway/invoke`。

- [ ] **Step 2: 确认测试先失败**

  Run: `python -m pytest backend/tests/test_phase2.py -q -k 'gateway_session and path'`

- [ ] **Step 3: 实现最小修复**

  新增同文件私有 URL 组合函数：保留绝对 `gateway.path` 的同源约束，普通路径仅做单个斜杠拼接；`_gateway_session` 不再直接 POST `gateway.base_url`。

- [ ] **Step 4: 运行相关回归**

  Run: `python -m pytest backend/tests/test_phase2.py -q -k 'gateway_session or credential_agent'`

### Task 2: 保留未就绪 Credential 的非敏感诊断元数据

**Files:**
- Modify: `/Users/admin/Testproject/test-platform/backend/app/api/internal.py`
- Test: `/Users/admin/Testproject/test-platform/backend/tests/test_phase2.py`

**Interfaces:**
- Consumes: `UserCredential.status`、`expires_at`、`refresh_expires_at`、`last_checked_at`、`last_error_code`。
- Produces: `credential_metadata.providers[provider_type]` 的非敏感状态摘要；失效 Credential 仍不进入 selector、Secret 或物化数据。

- [ ] **Step 1: 写失败测试**

  对 `action_required` 的 Scope Credential 断言：selector 不含其版本，但规划态 Runtime Config 的 metadata 含 `status`、`last_error_code`、过期时间和最近检查时间。

- [ ] **Step 2: 确认测试先失败**

  Run: `python -m pytest backend/tests/test_phase2.py -q -k 'runtime_scope and credential'`

- [ ] **Step 3: 实现状态摘要**

  在规划阶段先记录当前 Scope 的 Credential 元数据，再过滤不可物化版本；可用凭证沿用同一摘要函数，避免两套字段漂移。

- [ ] **Step 4: 验证快照隔离**

  断言 `credential_versions`、`credential_secret_versions` 和 `secrets` 仍不包含未就绪 Credential。

### Task 3: 将资产级凭证错误改为可行动诊断

**Files:**
- Modify: `/Users/admin/Testproject/api-autotest/web/app.py`
- Modify: `/Users/admin/Testproject/api-autotest/web/static/app.js`
- Modify: `/Users/admin/Testproject/api-autotest/web/static/app.css`
- Test: `/Users/admin/Testproject/api-autotest/tests/test_web_routes.py`

**Interfaces:**
- Consumes: 平台 Profile 状态摘要与资产声明的逻辑 Profile。
- Produces: `profiles[]` 的 `provider_type/status/version/expires_at/last_checked_at/last_error_code/reason`；`PROJECT_CREDENTIAL_MISSING` 的 `profile_details` 与凭证管理深链。

- [ ] **Step 1: 写失败路由测试**

  模拟 Dating `gateway_session=action_required` 且最近错误为 `CREDENTIAL_REFRESH_HTTPSTATUSERROR`，断言错误明确包含 `anonymous_session`、需要处理、自动续期 HTTP 错误、过期时间、Scope 和 `/account/credentials?scope_id=...&provider_type=gateway_session`。

- [ ] **Step 2: 确认测试先失败**

  Run: `python -m pytest tests/test_web_routes.py -q -k 'credential and preflight'`

- [ ] **Step 3: 扩展安全错误契约**

  规范化 Profile 元数据并生成稳定中文原因；真正未创建时显示“当前 Scope 尚未配置”，刷新中显示“平台正在刷新”，需要处理时显示平台错误码对应的安全原因。

- [ ] **Step 4: 改造 Web 错误态**

  将单句红条改为紧凑诊断卡：标题、Profile、状态、原因、过期时间、最近检查、Scope 和“前往管理凭证”按钮；保留 `aria-live`、文本状态和键盘可达链接。

- [ ] **Step 5: 回归工具测试**

  Run: `python -m pytest tests/test_web_routes.py -q`

### Task 4: 让平台配置与个人凭证按 Scope 可发现

**Files:**
- Modify: `/Users/admin/Testproject/test-platform/frontend/src/App.tsx`
- Modify: `/Users/admin/Testproject/test-platform/frontend/src/app.css`
- Test: `/Users/admin/Testproject/test-platform/frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `/me/credentials?environment_id=<env>&runtime_scope_id=<scope>` 与现有 `ConfigurationOwnerSelector`。
- Produces: Scope-aware 的“我的凭证”页面，以及普通配置页中只读的“当前 Scope 凭证状态”摘要。

- [ ] **Step 1: 写失败前端测试**

  构造 Truthy 与 Dating 两个 Scope 下同名 `gateway_session`，断言 Dating 深链只展示 Dating 版本并在保存请求带 `runtime_scope_id`；普通配置页展示 `action_required`、最近错误与管理入口。

- [ ] **Step 2: 确认测试先失败**

  Run: `npm test -- --run src/App.test.tsx`

- [ ] **Step 3: 实现 Scope-aware 个人凭证页**

  复用配置归属选择器；按 `selectedToolId + selectedScope.id + provider_type` 选择 Credential，保存时提交 Scope，卡片显示项目名、状态、版本、过期时间与错误码。

- [ ] **Step 4: 添加普通配置页凭证摘要**

  仅对当前选中 Scope 读取本人 Credential 元数据。标题明确写“个人凭证（不属于普通 Release）”，不显示任何 Secret 值；显示状态、版本、过期时间、最近错误和入口。

- [ ] **Step 5: 前端回归与构建**

  Run: `npm test -- --run src/App.test.tsx`

  Run: `npm run build`

### Task 5: 本机部署与端到端验收

**Files:**
- Verify only: `/Users/admin/Testproject/test-platform/docker-compose.yml`

**Interfaces:**
- Consumes: 当前 Dating/test Scope `tps_e6c4218848a74086892a8abd87c7e8b8`。
- Produces: 本机可直接验收的健康 Credential 与清晰预检页面。

- [ ] **Step 1: 重建 API、前端网关和工具，保留旧 Agent 状态做错误态验收**

  验证任务页显示 `anonymous_session / action_required / 自动续期 HTTP 错误 / 过期时间 / 修复入口`，并保存 1440px 桌面截图。

- [ ] **Step 2: 重建 Credential Agent**

  等待其通过完整 Dating Gateway URL 自动刷新或创建匿名会话，确认状态从 `action_required` 变为 `healthy` 且版本递增。

- [ ] **Step 3: 验证健康态**

  刷新任务页，确认 Profile 显示 ready、提交按钮恢复；配置控制面与个人凭证页显示同一 Scope 和版本。

- [ ] **Step 4: 完整回归**

  Run: `cd /Users/admin/Testproject/test-platform/backend && python -m pytest -q`

  Run: `cd /Users/admin/Testproject/test-platform/frontend && npm test && npm run build`

  Run: `cd /Users/admin/Testproject/api-autotest && python -m pytest tests -q`

