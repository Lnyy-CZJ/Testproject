# V5 Phase 5B/5C Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 v5.0 剩余的 5B/5C 主干能力，包括异常抬升筛选、回归预防闭环与质量情报中心。

**Architecture:** 在现有问题池、路由治理和版本关联基础上，继续扩展一层项目级质量运营域。后端新增回归预防模型与质量情报聚合服务；前端新增项目级“回归预防”和“质量情报”页面，并把异常抬升级别与问题池联动。尽量复用现有 `IssueCluster / AppRelease / Defect / AnalysisReport / FixTask` 关系，避免再造并行模型。

**Tech Stack:** Go + Gin + GORM + PostgreSQL, React + TypeScript + Ant Design, Playwright, Go test

---

## File Structure

### Backend
- Modify: `server/internal/model/signal.go`
- Modify: `server/cmd/server/main.go`
- Modify: `server/testutil/testutil.go`
- Modify: `server/internal/service/project_routing.go`
- Modify: `server/internal/service/signal_triage.go`
- Create: `server/internal/service/regression_prevention.go`
- Create: `server/internal/service/quality_insight.go`
- Modify: `server/internal/handler/issue_pool.go`
- Modify: `server/internal/handler/project_routing.go`
- Create: `server/internal/handler/regression_prevention.go`
- Create: `server/internal/handler/quality_insight.go`
- Modify: `server/internal/router/router.go`
- Create: `server/internal/service/regression_prevention_test.go`
- Create: `server/internal/service/quality_insight_test.go`
- Modify: `server/internal/service/project_routing_test.go`
- Modify: `server/internal/handler/issue_pool_test.go`
- Create: `server/internal/handler/regression_prevention_test.go`
- Create: `server/internal/handler/quality_insight_test.go`

### Frontend
- Modify: `web/src/types/index.ts`
- Modify: `web/src/api/index.ts`
- Modify: `web/src/router.tsx`
- Modify: `web/src/layouts/ProjectLayout.tsx`
- Modify: `web/src/pages/projects/ProjectIssuePool.tsx`
- Modify: `web/src/pages/projects/ProjectRoutingCenter.tsx`
- Create: `web/src/pages/projects/ProjectRegressionCenter.tsx`
- Create: `web/src/pages/projects/ProjectQualityCenter.tsx`
- Modify: `web/e2e/browser-prd-flows.spec.ts`

---

### Task 1: 问题池增加异常抬升级别筛选与列表联动
- [ ] 写失败测试：后端列表支持 `anomalyLevel` 筛选，前端问题池显示异常标签。
- [ ] 运行定向测试确认失败。
- [ ] 最小实现：基于现有 release trend 结果回填问题簇的最高异常级别；问题池增加筛选与标签显示。
- [ ] 运行后端/前端/浏览器定向验证。
- [ ] Commit: `feat: filter issue pool by anomaly level`

### Task 2: 新增回归预防模型与 API
- [ ] 写失败测试：从问题簇生成回归项，列表可查询，支持状态更新。
- [ ] 运行定向测试确认失败。
- [ ] 最小实现：新增 `regression_items` 表，字段包含 `project_id / cluster_id / defect_id / title / summary / source_fingerprint / status / owner_user_id / created_by / last_verified_at`。
- [ ] 提供接口：
  - `GET /api/v1/projects/:id/regression-items`
  - `POST /api/v1/projects/:id/issue-clusters/:clusterId/regression-items`
  - `PUT /api/v1/projects/:id/regression-items/:itemId`
- [ ] 运行后端定向验证。
- [ ] Commit: `feat: add regression prevention api`

### Task 3: 新增回归预防页面与问题池沉淀入口
- [ ] 写或扩展浏览器测试：问题池可把已转缺陷问题簇沉淀为回归项，回归预防页面可看到并更新状态。
- [ ] 运行测试确认失败。
- [ ] 最小实现：
  - 项目侧边栏新增 `回归预防`
  - 问题池详情卡片新增“加入回归清单”入口
  - 新页面展示回归项列表、来源问题簇、关联缺陷、负责人、最近验证时间与状态流转
- [ ] 运行前端构建与浏览器验证。
- [ ] Commit: `feat: add regression prevention workspace`

### Task 4: 新增质量情报聚合服务
- [ ] 写失败测试：项目质量情报接口返回版本质量评分、模块热度、重复问题率、响应/修复时效、AI 处置率、再发率。
- [ ] 运行测试确认失败。
- [ ] 最小实现：新增 `QualityInsightService`，聚合 `IssueCluster / AppRelease / Defect / AnalysisReport / FixTask / ProjectModule` 生成项目级指标。
- [ ] 提供接口：`GET /api/v1/projects/:id/quality-insights`
- [ ] 运行后端定向验证。
- [ ] Commit: `feat: add quality insight aggregation`

### Task 5: 新增质量情报页面
- [ ] 写或扩展浏览器测试：质量情报页展示核心指标卡、版本质量表、模块热度表。
- [ ] 运行测试确认失败。
- [ ] 最小实现：
  - 项目侧边栏新增 `质量情报`
  - 页面展示 KPI 卡片、版本质量排行、模块热度、问题趋势摘要
  - 与现有发布趋势保持一致口径
- [ ] 运行前端构建与浏览器验证。
- [ ] Commit: `feat: add project quality center`

### Task 6: 全量回归与文档收口
- [ ] 运行后端定向与 `go test ./... -count=1 -timeout 180s`
- [ ] 运行前端 `npm run lint`、`npx tsc -p tsconfig.app.json --noEmit`、`npm run build`
- [ ] 运行关键 Playwright 场景：问题池、路由治理、回归预防、质量情报
- [ ] 更新 v5.0 路线图/PRD 状态描述为已交付的实际范围
- [ ] Commit: `docs: finalize v5 delivery status`
