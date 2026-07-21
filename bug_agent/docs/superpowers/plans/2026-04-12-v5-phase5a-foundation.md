# V5 Phase 5A Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 v5.0 首期“统一接入内核 + 问题池 + 分诊 + 转缺陷”可运行闭环，并预留 5B/5C 扩展模型。

**Architecture:** 后端新增问题信号域模型、接入服务、公共入站 Webhook 和项目级问题池/分诊 API；前端新增连接器管理页与项目问题池页面。正式缺陷、AI 分析、协作、修复链路继续复用现有主域。首期连接器以通用 Webhook 为基础，同时提供 Bugly / 钉钉 / 飞书的标准化适配入口和配置界面。

**Tech Stack:** Go + Gin + GORM + PostgreSQL, React + TypeScript + Ant Design, Playwright, Go test

---

## File Structure

### Backend
- Create: `server/internal/model/signal.go`
- Create: `server/internal/service/signal_ingest.go`
- Create: `server/internal/service/signal_triage.go`
- Create: `server/internal/handler/integration_connector.go`
- Create: `server/internal/handler/issue_pool.go`
- Create: `server/internal/handler/inbound_connector.go`
- Create: `server/internal/handler/integration_connector_test.go`
- Create: `server/internal/handler/issue_pool_test.go`
- Create: `server/internal/service/signal_ingest_test.go`
- Modify: `server/cmd/server/main.go`
- Modify: `server/internal/router/router.go`
- Modify: `server/testutil/testutil.go`

### Frontend
- Create: `web/src/pages/system/IntegrationConnectorsPage.tsx`
- Create: `web/src/pages/projects/ProjectIssuePool.tsx`
- Modify: `web/src/router.tsx`
- Modify: `web/src/layouts/MainLayout.tsx`
- Modify: `web/src/layouts/ProjectLayout.tsx`
- Modify: `web/src/api/index.ts`
- Modify: `web/src/types/index.ts`
- Modify: `web/e2e/browser-prd-flows.spec.ts`

---

### Task 1: 新增问题信号域数据模型与迁移接入

**Files:**
- Create: `server/internal/model/signal.go`
- Modify: `server/cmd/server/main.go`
- Modify: `server/testutil/testutil.go`
- Test: `server/internal/service/signal_ingest_test.go`

- [ ] **Step 1: 写失败测试，验证模型已迁移并可在测试库中使用**

```go
func TestSignalModels_AutoMigrateCoreTables(t *testing.T) {
    db := testutil.SetupTestDB(t)
    tables := []string{"integration_connectors", "issue_signals", "issue_clusters", "issue_triage_records"}
    for _, table := range tables {
        if !db.Migrator().HasTable(table) {
            t.Fatalf("expected table %s to exist", table)
        }
    }
}
```

- [ ] **Step 2: 运行测试确保失败**

Run: `cd server && go test ./internal/service -run TestSignalModels_AutoMigrateCoreTables -count=1`
Expected: FAIL because models are not registered

- [ ] **Step 3: 新增模型并接入 AutoMigrate / testutil**

实现实体：
- `IntegrationConnector`
- `IntegrationSyncRecord`
- `IssueSignal`
- `IssueCluster`
- `IssueTriageRecord`
- `IssueRoutingRule`
- `ProjectModule`
- `AppRelease`
- `ExternalSyncRecord`

- [ ] **Step 4: 运行测试确保通过**

Run: `cd server && go test ./internal/service -run TestSignalModels_AutoMigrateCoreTables -count=1`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/internal/model/signal.go server/cmd/server/main.go server/testutil/testutil.go server/internal/service/signal_ingest_test.go
git commit -m "feat: add signal domain models"
```

### Task 2: 接入内核与公共入站 Webhook

**Files:**
- Create: `server/internal/service/signal_ingest.go`
- Create: `server/internal/handler/inbound_connector.go`
- Create: `server/internal/service/signal_ingest_test.go`
- Modify: `server/internal/router/router.go`

- [ ] **Step 1: 写失败测试，验证 Webhook 入站会创建 signal 和 cluster**

```go
func TestInboundConnectorHandler_WebhookCreatesSignalAndCluster(t *testing.T) {
    db := testutil.SetupTestDB(t)
    connector := model.IntegrationConnector{ProjectID: 1, Name: "Webhook", Type: "webhook", Status: "active", InboundToken: "tok_123"}
    if err := db.Create(&connector).Error; err != nil { t.Fatal(err) }
    svc := service.NewSignalIngestService(db)
    h := handler.NewInboundConnectorHandler(db, svc)
    r := gin.New()
    r.POST("/inbound/connectors/:token", h.Receive)

    body := `{"eventId":"evt-1","title":"启动崩溃","description":"app启动后闪退","platform":"android","appVersion":"1.0.0","fingerprint":"fp-1"}`
    w := httptest.NewRecorder()
    req, _ := http.NewRequest(http.MethodPost, "/inbound/connectors/tok_123", bytes.NewBufferString(body))
    req.Header.Set("Content-Type", "application/json")
    r.ServeHTTP(w, req)

    if w.Code != http.StatusOK { t.Fatalf("expected 200, got %d", w.Code) }

    var signals []model.IssueSignal
    if err := db.Find(&signals).Error; err != nil { t.Fatal(err) }
    if len(signals) != 1 { t.Fatalf("expected 1 signal, got %d", len(signals)) }
}
```

- [ ] **Step 2: 运行测试确保失败**

Run: `cd server && go test ./internal/handler -run TestInboundConnectorHandler_WebhookCreatesSignalAndCluster -count=1`
Expected: FAIL because handler/service do not exist

- [ ] **Step 3: 实现最小接入服务与公开入站处理器**

要求：
- 通过 `InboundToken` 识别连接器
- 仅允许 `status=active`
- 将 payload 标准化为 `IssueSignal`
- 基于 `project_id + fingerprint` 聚合 `IssueCluster`
- 更新 `signal_count / affected_user_count / first_seen_at / last_seen_at`
- 写入 `integration_sync_records`

- [ ] **Step 4: 运行测试确保通过**

Run: `cd server && go test ./internal/handler -run TestInboundConnectorHandler_WebhookCreatesSignalAndCluster -count=1`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/internal/service/signal_ingest.go server/internal/handler/inbound_connector.go server/internal/router/router.go server/internal/service/signal_ingest_test.go
git commit -m "feat: add inbound connector ingestion"
```

### Task 3: 连接器管理 API

**Files:**
- Create: `server/internal/handler/integration_connector.go`
- Create: `server/internal/handler/integration_connector_test.go`
- Modify: `server/internal/router/router.go`

- [ ] **Step 1: 写失败测试，验证管理员可 CRUD 连接器并查看同步记录**
- [ ] **Step 2: 运行测试确保失败**
- [ ] **Step 3: 实现 API**

接口：
- `GET /api/v1/admin/integration-connectors`
- `POST /api/v1/admin/integration-connectors`
- `PUT /api/v1/admin/integration-connectors/:id`
- `DELETE /api/v1/admin/integration-connectors/:id`
- `POST /api/v1/admin/integration-connectors/:id/test`
- `POST /api/v1/admin/integration-connectors/:id/sync`
- `GET /api/v1/admin/integration-connectors/:id/sync-records`

设计决策：
- `test` 只验证配置完整性和 webhook token / 基础配置，不做真实三方强依赖
- `sync` 首期先支持 `bugly` 的手动 pull 协议化入口和 `webhook` no-op 响应

- [ ] **Step 4: 运行测试确保通过**
- [ ] **Step 5: Commit**

### Task 4: 项目问题池与分诊 API

**Files:**
- Create: `server/internal/service/signal_triage.go`
- Create: `server/internal/handler/issue_pool.go`
- Create: `server/internal/handler/issue_pool_test.go`
- Modify: `server/internal/router/router.go`

- [ ] **Step 1: 写失败测试，验证项目问题簇列表、详情、忽略、指派、转缺陷**
- [ ] **Step 2: 运行测试确保失败**
- [ ] **Step 3: 实现最小分诊服务**

接口：
- `GET /api/v1/projects/:id/issue-clusters`
- `GET /api/v1/projects/:id/issue-clusters/:clusterId`
- `GET /api/v1/projects/:id/issue-clusters/:clusterId/signals`
- `POST /api/v1/projects/:id/issue-clusters/:clusterId/assign`
- `POST /api/v1/projects/:id/issue-clusters/:clusterId/ignore`
- `POST /api/v1/projects/:id/issue-clusters/:clusterId/convert`

转缺陷要求：
- 自动创建 `Defect`
- `IssueCluster.LinkedDefectID` 回写
- 所有 `IssueSignal.LinkedDefectID` 回写
- 生成一条系统评论，说明来源于问题池

- [ ] **Step 4: 运行测试确保通过**
- [ ] **Step 5: Commit**

### Task 5: 前端连接器管理页

**Files:**
- Create: `web/src/pages/system/IntegrationConnectorsPage.tsx`
- Modify: `web/src/router.tsx`
- Modify: `web/src/layouts/MainLayout.tsx`
- Modify: `web/src/api/index.ts`
- Modify: `web/src/types/index.ts`

- [ ] **Step 1: 写或扩展前端/浏览器测试，验证连接器页可创建和查看连接器**
- [ ] **Step 2: 运行测试确保失败**
- [ ] **Step 3: 实现 UI**

要求：
- 列表展示名称、类型、状态、项目、最近同步状态
- 新增/编辑弹窗
- 展示入站 URL（Webhook / 钉钉 / 飞书）
- 手动测试与手动同步按钮

- [ ] **Step 4: 运行测试确保通过**
- [ ] **Step 5: Commit**

### Task 6: 项目问题池页面

**Files:**
- Create: `web/src/pages/projects/ProjectIssuePool.tsx`
- Modify: `web/src/router.tsx`
- Modify: `web/src/layouts/ProjectLayout.tsx`
- Modify: `web/src/api/index.ts`
- Modify: `web/src/types/index.ts`

- [ ] **Step 1: 写或扩展浏览器测试，验证问题池可查看问题簇并执行忽略/转缺陷**
- [ ] **Step 2: 运行测试确保失败**
- [ ] **Step 3: 实现 UI**

要求：
- 问题簇列表
- 详情抽屉
- 原始信号列表
- 指派、忽略、转缺陷按钮
- 与现有缺陷页可跳转联动

- [ ] **Step 4: 运行测试确保通过**
- [ ] **Step 5: Commit**

### Task 7: 首批连接器类型适配与 5B/5C 预留

**Files:**
- Modify: `server/internal/service/signal_ingest.go`
- Modify: `server/internal/model/signal.go`
- Modify: `web/src/pages/system/IntegrationConnectorsPage.tsx`
- Test: `server/internal/service/signal_ingest_test.go`

- [ ] **Step 1: 写测试，验证 `bugly`、`dingtalk`、`feishu` 类型的 payload 归一化差异**
- [ ] **Step 2: 运行测试确保失败**
- [ ] **Step 3: 实现适配器**

要求：
- `bugly`：优先从堆栈/版本/次数提取字段
- `dingtalk` / `feishu`：优先从文本消息和链接提取标题/描述/来源标识
- 同时把 `project_modules`、`issue_routing_rules`、`app_releases`、`external_sync_records` 模型纳入迁移但 UI 可暂不暴露

- [ ] **Step 4: 运行测试确保通过**
- [ ] **Step 5: Commit**

### Task 8: 全量回归与联调

**Files:**
- Modify: `web/e2e/browser-prd-flows.spec.ts`
- Verify existing test suites

- [ ] **Step 1: 运行后端定向测试**

Run: `cd server && go test ./internal/handler ./internal/service -run 'Test(InboundConnector|IntegrationConnector|IssuePool|SignalIngest)' -count=1`
Expected: PASS

- [ ] **Step 2: 运行后端全量测试**

Run: `cd server && go test ./... -count=1 -timeout 180s`
Expected: PASS

- [ ] **Step 3: 运行前端构建与 e2e**

Run: `cd web && npm run build && npm run test:e2e -- --reporter=list`
Expected: PASS

- [ ] **Step 4: 真实联调检查**

验证：
- 创建连接器
- 通过入站 URL 发 1 条 webhook
- 问题池出现 1 条问题簇
- 执行转缺陷
- 缺陷详情页出现来源评论

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: deliver v5 phase5a signal intake and issue pool"
```
