# V5.1 Project Intake Productionization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 v5.1 主干交付：项目内信号接入中心迁移、连接器生产化、分诊智能准确率、AI 处置可信化，以及接口测试与页面联调专项。

**Architecture:** 先收紧信息架构，把信号接入完全迁入项目内；再在项目上下文上补齐连接器健康检查、同步诊断和真实联调能力；随后增强问题池建议解释与批量分诊；最后补 AI 版本审计、降级与观测。所有阶段都必须伴随接口契约测试、页面联调和浏览器回归。

**Tech Stack:** Go + Gin + GORM + PostgreSQL, React + TypeScript + Ant Design, Playwright, Go test

---

## File Structure

### Backend
- Modify: `server/internal/router/router.go`
- Modify: `server/internal/handler/integration_connector.go`
- Modify: `server/internal/service/integration_connector.go`
- Modify: `server/internal/service/signal_triage.go`
- Modify: `server/internal/service/project_routing.go`
- Modify: `server/internal/service/analysis.go`
- Modify: `server/internal/service/fix_engine.go`
- Modify: `server/internal/model/signal.go`
- Create: `server/internal/service/integration_connector_diagnostics.go`
- Create: `server/internal/service/triage_feedback.go`
- Create: `server/internal/service/ai_observability.go`
- Modify: `server/internal/handler/issue_pool.go`
- Create: `server/internal/handler/project_integration_connector.go`
- Modify: `server/internal/handler/integration_connector_test.go`
- Modify: `server/internal/handler/issue_pool_test.go`
- Modify: `server/internal/service/signal_triage_test.go`
- Create: `server/internal/service/triage_feedback_test.go`
- Create: `server/internal/service/ai_observability_test.go`

### Frontend
- Modify: `web/src/router.tsx`
- Modify: `web/src/layouts/MainLayout.tsx`
- Modify: `web/src/layouts/ProjectLayout.tsx`
- Modify: `web/src/api/index.ts`
- Modify: `web/src/types/index.ts`
- Delete/Retire: `web/src/pages/system/IntegrationConnectorsPage.tsx`
- Create: `web/src/pages/projects/ProjectIntegrations.tsx`
- Modify: `web/src/pages/projects/ProjectIssuePool.tsx`
- Modify: `web/src/pages/projects/ProjectRoutingCenter.tsx`
- Modify: `web/src/pages/projects/ProjectQualityInsights.tsx`
- Modify: `web/src/pages/projects/ProjectDashboard.tsx`
- Modify: `web/e2e/browser-prd-flows.spec.ts`

### Docs
- Modify: `docs/PRD-v5.1-project-intake-productionization.md`
- Modify: `docs/ROADMAP-v5.1-project-intake-productionization.md`
- Modify: `docs/DEV_PLAN-v5.1-project-intake-productionization.md`
- Modify: `docs/PRD_COVERAGE_AND_TEST_CASES.md`

---

### Task 1: 建立接口与页面联调基线

**Files:**
- Modify: `server/internal/router/router.go`
- Modify: `web/src/api/index.ts`
- Modify: `web/src/router.tsx`
- Test: `web/e2e/browser-prd-flows.spec.ts`

- [ ] **Step 1: 梳理项目主链路页面与接口映射**

列出并写入开发记录：
- `项目工作台 -> /api/v1/projects/:id/...`
- `问题池 -> /api/v1/projects/:id/issue-clusters...`
- `信号接入 -> /api/v1/projects/:id/integrations...`
- `路由治理 -> /api/v1/projects/:id/modules / routing-rules / releases`
- `质量情报 -> /api/v1/projects/:id/quality-insights`

- [ ] **Step 2: 为关键页面失败态补统一策略**

前端统一要求：
- loading 时展示骨架或 Spin
- empty 时给业务说明
- error 时给错误文案和“重试”按钮

- [ ] **Step 3: 运行当前浏览器回归确认现状**

Run: `cd /Users/jame/Workspace/bug_agent/web && npm run test:e2e -- --reporter=list`
Expected: 记录当前通过/失败情况，作为后续迁移基线。

- [ ] **Step 4: Commit**

```bash
git add web/e2e/browser-prd-flows.spec.ts web/src/api/index.ts web/src/router.tsx server/internal/router/router.go
git commit -m "test: establish v5.1 integration hardening baseline"
```

### Task 2: 删除平台级接入入口并迁移到项目级路由

**Files:**
- Modify: `web/src/router.tsx`
- Modify: `web/src/layouts/MainLayout.tsx`
- Modify: `web/src/layouts/ProjectLayout.tsx`
- Delete/Retire: `web/src/pages/system/IntegrationConnectorsPage.tsx`
- Create: `web/src/pages/projects/ProjectIntegrations.tsx`
- Test: `web/e2e/browser-prd-flows.spec.ts`

- [ ] **Step 1: 写失败的浏览器测试**

测试目标：
1. 平台菜单中不存在“信号接入”
2. 项目侧边栏存在“信号接入”
3. 项目内可以进入接入页

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/jame/Workspace/bug_agent/web && npx playwright test --grep "信号接入" --reporter=list`
Expected: FAIL，当前仍是平台级入口。

- [ ] **Step 3: 最小实现前端迁移**

实现要求：
1. 删除 `/integration-connectors` 路由
2. 平台导航删除入口
3. 项目路由新增 `/projects/:projectId/integrations`
4. 把接入页面改为项目上下文，不再选择项目归属

- [ ] **Step 4: 运行前端构建与浏览器验证**

Run:
- `cd /Users/jame/Workspace/bug_agent/web && npm run build`
- `cd /Users/jame/Workspace/bug_agent/web && npx playwright test --grep "信号接入" --reporter=list`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/router.tsx web/src/layouts/MainLayout.tsx web/src/layouts/ProjectLayout.tsx web/src/pages/projects/ProjectIntegrations.tsx web/e2e/browser-prd-flows.spec.ts
git commit -m "feat: move integrations into project workspace"
```

### Task 3: 后端迁移到项目级连接器接口并删除平台级入口

**Files:**
- Modify: `server/internal/router/router.go`
- Modify: `server/internal/handler/integration_connector.go`
- Create: `server/internal/handler/project_integration_connector.go`
- Test: `server/internal/handler/integration_connector_test.go`

- [ ] **Step 1: 写失败测试**

目标：
1. `GET /api/v1/projects/:id/integrations` 返回当前项目连接器
2. `POST /api/v1/projects/:id/integrations` 创建连接器时无需 `projectId` body 字段
3. 平台级旧路由不再注册

- [ ] **Step 2: 运行定向测试确认失败**

Run: `cd /Users/jame/Workspace/bug_agent/server && go test ./internal/handler -run 'TestIntegrationConnectorHandler_' -count=1`
Expected: FAIL

- [ ] **Step 3: 最小实现项目级 handler 和路由**

实现要求：
1. 连接器全部走项目上下文
2. 删除平台级用户入口 API
3. 保留服务层以 `project_id` 为唯一归属口径

- [ ] **Step 4: 运行后端定向验证**

Run: `cd /Users/jame/Workspace/bug_agent/server && go test ./internal/handler -run 'TestIntegrationConnectorHandler_' -count=1`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/internal/router/router.go server/internal/handler/integration_connector.go server/internal/handler/project_integration_connector.go server/internal/handler/integration_connector_test.go
git commit -m "feat: move integration apis under project scope"
```

### Task 4: 连接器生产化 - 健康状态、错误分类、同步记录

**Files:**
- Modify: `server/internal/service/integration_connector.go`
- Create: `server/internal/service/integration_connector_diagnostics.go`
- Modify: `server/internal/model/signal.go`
- Modify: `web/src/pages/projects/ProjectIntegrations.tsx`
- Modify: `web/src/types/index.ts`
- Modify: `web/src/api/index.ts`
- Test: `server/internal/handler/integration_connector_test.go`
- Test: `web/e2e/browser-prd-flows.spec.ts`

- [ ] **Step 1: 写失败测试**

目标：
1. 列表返回连接器健康状态与最近错误
2. 同步失败时记录标准错误分类
3. 前端能看到状态、最近同步时间和错误摘要

- [ ] **Step 2: 运行测试确认失败**

Run:
- `cd /Users/jame/Workspace/bug_agent/server && go test ./internal/handler -run 'TestIntegrationConnectorHandler_' -count=1`
- `cd /Users/jame/Workspace/bug_agent/web && npx playwright test --grep '阿里云日志连接器|信号接入' --reporter=list`
Expected: FAIL

- [ ] **Step 3: 最小实现诊断能力**

实现要求：
1. 健康状态：`healthy / warning / failed / inactive`
2. 错误分类：鉴权失败、配置缺失、限流、超时、第三方异常
3. 同步记录带导入数、聚类数、错误摘要

- [ ] **Step 4: 运行后端与浏览器验证**

Run:
- `cd /Users/jame/Workspace/bug_agent/server && go test ./internal/handler ./internal/service -run 'TestIntegrationConnectorHandler_|TestIntegrationConnector' -count=1`
- `cd /Users/jame/Workspace/bug_agent/web && npm run build`
- `cd /Users/jame/Workspace/bug_agent/web && npx playwright test --grep '信号接入' --reporter=list`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/internal/service/integration_connector.go server/internal/service/integration_connector_diagnostics.go server/internal/model/signal.go web/src/pages/projects/ProjectIntegrations.tsx web/src/types/index.ts web/src/api/index.ts server/internal/handler/integration_connector_test.go web/e2e/browser-prd-flows.spec.ts
git commit -m "feat: add connector diagnostics and health states"
```

### Task 5: 连接器生产化 - 重试、失败记录、真实联调记录

**Files:**
- Modify: `server/internal/service/integration_connector.go`
- Modify: `server/internal/handler/project_integration_connector.go`
- Modify: `web/src/pages/projects/ProjectIntegrations.tsx`
- Modify: `docs/PRD_COVERAGE_AND_TEST_CASES.md`
- Test: `server/internal/handler/integration_connector_test.go`

- [ ] **Step 1: 写失败测试**

目标：
1. 失败同步记录支持重试
2. 重试成功后状态更新
3. 文档可回填真实外部联调结果或环境阻塞原因

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /Users/jame/Workspace/bug_agent/server && go test ./internal/handler -run 'TestIntegrationConnectorHandler_' -count=1`
Expected: FAIL

- [ ] **Step 3: 最小实现**

实现要求：
1. 重试接口
2. 页面“重试”动作
3. 失败记录状态联动
4. 文档模板支持真实联调结果回填

- [ ] **Step 4: 运行验证**

Run:
- `cd /Users/jame/Workspace/bug_agent/server && go test ./internal/handler -run 'TestIntegrationConnectorHandler_' -count=1`
- `cd /Users/jame/Workspace/bug_agent/web && npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/internal/service/integration_connector.go server/internal/handler/project_integration_connector.go web/src/pages/projects/ProjectIntegrations.tsx docs/PRD_COVERAGE_AND_TEST_CASES.md server/internal/handler/integration_connector_test.go
git commit -m "feat: add connector retry workflow"
```

### Task 6: 分诊智能准确率 - 推荐依据与批量分诊

**Files:**
- Modify: `server/internal/service/signal_triage.go`
- Modify: `server/internal/handler/issue_pool.go`
- Create: `server/internal/service/triage_feedback.go`
- Create: `server/internal/service/triage_feedback_test.go`
- Modify: `server/internal/handler/issue_pool_test.go`
- Modify: `web/src/pages/projects/ProjectIssuePool.tsx`
- Modify: `web/src/types/index.ts`
- Modify: `web/src/api/index.ts`
- Test: `web/e2e/browser-prd-flows.spec.ts`

- [ ] **Step 1: 写失败测试**

目标：
1. 列表/详情返回推荐依据
2. 支持批量分诊
3. 支持记录人工修正和采纳率

- [ ] **Step 2: 运行测试确认失败**

Run:
- `cd /Users/jame/Workspace/bug_agent/server && go test ./internal/handler ./internal/service -run 'TestIssuePoolHandler_|TestSignalTriageService_' -count=1`
- `cd /Users/jame/Workspace/bug_agent/web && npx playwright test --grep '问题池' --reporter=list`
Expected: FAIL

- [ ] **Step 3: 最小实现**

实现要求：
1. 问题池详情展示推荐依据
2. 批量指派、忽略、转缺陷
3. 采纳反馈落库

- [ ] **Step 4: 运行验证**

Run:
- `cd /Users/jame/Workspace/bug_agent/server && go test ./internal/handler ./internal/service -run 'TestIssuePoolHandler_|TestSignalTriageService_|TestTriageFeedback' -count=1`
- `cd /Users/jame/Workspace/bug_agent/web && npm run build`
- `cd /Users/jame/Workspace/bug_agent/web && npx playwright test --grep '问题池' --reporter=list`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/internal/service/signal_triage.go server/internal/handler/issue_pool.go server/internal/service/triage_feedback.go server/internal/service/triage_feedback_test.go server/internal/handler/issue_pool_test.go web/src/pages/projects/ProjectIssuePool.tsx web/src/types/index.ts web/src/api/index.ts web/e2e/browser-prd-flows.spec.ts
git commit -m "feat: improve triage explainability and batch actions"
```

### Task 7: AI 处置可信化 - 审计、降级、观测

**Files:**
- Modify: `server/internal/service/analysis.go`
- Modify: `server/internal/service/fix_engine.go`
- Create: `server/internal/service/ai_observability.go`
- Create: `server/internal/service/ai_observability_test.go`
- Modify: `server/internal/handler/agent.go`
- Modify: `web/src/pages/defects/DefectDetail.tsx`
- Modify: `web/src/pages/projects/ProjectQualityInsights.tsx`
- Modify: `web/src/types/index.ts`
- Test: `server/internal/handler/agent_analysis_failure_test.go`
- Test: `web/e2e/browser-prd-flows.spec.ts`

- [ ] **Step 1: 写失败测试**

目标：
1. AI 调用记录模型/Prompt 版本
2. 失败时触发降级策略
3. 页面可见风险摘要与验证建议
4. 质量情报可见 AI 成功率/延迟摘要

- [ ] **Step 2: 运行测试确认失败**

Run:
- `cd /Users/jame/Workspace/bug_agent/server && go test ./internal/handler ./internal/service -run 'TestAgentHandler_|TestAnalysis|TestAIObservability' -count=1`
Expected: FAIL

- [ ] **Step 3: 最小实现**

实现要求：
1. 记录模型和 Prompt 版本
2. 增加失败降级与 fallback
3. 输出风险摘要和验证建议
4. 聚合 AI 观测指标

- [ ] **Step 4: 运行验证**

Run:
- `cd /Users/jame/Workspace/bug_agent/server && go test ./internal/handler ./internal/service -run 'TestAgentHandler_|TestAnalysis|TestAIObservability' -count=1`
- `cd /Users/jame/Workspace/bug_agent/web && npm run build`
- `cd /Users/jame/Workspace/bug_agent/web && npx playwright test --grep '质量情报|缺陷' --reporter=list`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/internal/service/analysis.go server/internal/service/fix_engine.go server/internal/service/ai_observability.go server/internal/service/ai_observability_test.go server/internal/handler/agent.go web/src/pages/defects/DefectDetail.tsx web/src/pages/projects/ProjectQualityInsights.tsx web/src/types/index.ts server/internal/handler/agent_analysis_failure_test.go web/e2e/browser-prd-flows.spec.ts
git commit -m "feat: harden ai handling trustworthiness"
```

### Task 8: 全量回归、文档回填与收尾

**Files:**
- Modify: `docs/PRD-v5.1-project-intake-productionization.md`
- Modify: `docs/ROADMAP-v5.1-project-intake-productionization.md`
- Modify: `docs/DEV_PLAN-v5.1-project-intake-productionization.md`
- Modify: `docs/PRD_COVERAGE_AND_TEST_CASES.md`

- [ ] **Step 1: 运行后端全量测试**

Run: `cd /Users/jame/Workspace/bug_agent/server && go test ./... -count=1 -timeout 180s`
Expected: PASS

- [ ] **Step 2: 运行前端全量校验**

Run:
- `cd /Users/jame/Workspace/bug_agent/web && npm run lint`
- `cd /Users/jame/Workspace/bug_agent/web && npm run build`
Expected: PASS

- [ ] **Step 3: 运行浏览器回归**

Run: `cd /Users/jame/Workspace/bug_agent/web && npm run test:e2e -- --reporter=list`
Expected: PASS

- [ ] **Step 4: 回填文档中的真实联调与 DoD 状态**

要求：
1. 明确哪些连接器真实通过
2. 哪些仍受外部环境阻塞
3. 更新 v5.1 状态为实际交付情况

- [ ] **Step 5: Commit**

```bash
git add docs/PRD-v5.1-project-intake-productionization.md docs/ROADMAP-v5.1-project-intake-productionization.md docs/DEV_PLAN-v5.1-project-intake-productionization.md docs/PRD_COVERAGE_AND_TEST_CASES.md
git commit -m "docs: finalize v5.1 delivery plan and verification"
```
