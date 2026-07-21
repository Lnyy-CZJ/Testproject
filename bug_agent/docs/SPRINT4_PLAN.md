# BugAgent Sprint 4 — 全栈生产级路线图

> 状态：**规划中** | 基线：Sprint 3 完成 (56+ tests, PostgreSQL, WebSocket, RBAC)
> 规划时间：2026-04-06

---

## 📌 Sprint 4 总览

```
Phase 1: 架构升级 (Infrastructure)     ← 基础先行
    ↓
Phase 2: 质量工程 (Quality Gate)       ← 质量兜底
    ↓
Phase 3: 生产就绪化 (Production)      ← 上线准备
    ↓
Phase 4: 功能增强 (Features)          ← 价值交付
```

---

## Phase 1: 架构升级 (预计 3 天)

### 1.1 Redis 完整集成
| 任务 | 描述 | 文件 |
|------|------|------|
| P1-1-1 | Redis Session 存储（替代内存session） | `internal/cache/redis_session.go` |
| P1-1-2 | RBAC 缓存迁移到 Redis（当前是进程内map） | `internal/service/rbac.go` |
| P1-1-3 | 分布式锁（协作任务防重复启动） | `internal/cache/redis_lock.go` |
| P1-1-4 | WS Hub 状态 Redis 持久化（重启恢复） | `internal/ws/hub.go` |

### 1.2 API 版本控制 + 限流熔断
| 任务 | 描述 | 文件 |
|------|------|------|
| P1-2-1 | API 版本路由 `/api/v1/` → `/api/v2/` 预留 | `internal/router/router.go` |
| P1-2-2 | 全局限流中间件（令牌桶，100 req/s） | `middleware/rate_limit.go` |
| P1-2-3 | 接口超时控制（context.WithTimeout） | 各 handler 统一 |
| P1-2-4 | 请求体大小限制（max 10MB） | gin 中间件配置 |

### 1.3 连接池优化
| 任务 | 描述 | 文件 |
|------|------|------|
| P1-3-1 | PG 连接池参数调优（MaxOpenConns=50, MaxIdleConns=10） | `internal/database/database.go` |
| P1-3-2 | 慢查询日志（>500ms 记录 warning） | GORM callback |
| P1-3-3 | Redis 连接池配置 | `internal/cache/` |

---

## Phase 2: 质量工程 (预计 2 天)

### 2.1 测试覆盖率提升
| 目标 | 当前 | 目标 |
|------|------|------|
| 后端覆盖率 | ~45% | >70% |
| 关键路径覆盖 | 协作流程 | 100% |

| 任务 | 描述 |
|------|------|
| P2-1-1 | Handler 层完整测试（含错误路径 4xx/5xx） |
| P2-1-2 | Middleware 组合测试（Auth+RBAC+Audit 链路） |
| P2-1-3 | AI Factory mock 测试（不依赖真实 API） |
| P2-1-4 | 覆盖率报告生成 (`go test -coverprofile`) |

### 2.2 安全扫描
| 任务 | 描述 |
|------|------|
| P2-2-1 | `go vet` + `staticcheck` 集成到 Makefile |
| P2-2-2 | 依赖漏洞扫描 (`govulncheck`) |
| P2-2-3 | SQL 注入审查（GORM 参数化查询验证） |
| P2-2-4 | XSS/CSRF 前端安全检查 |

### 2.3 性能基准回归
| 任务 | 描述 |
|------|------|
| P2-3-1 | 建立 benchmark 基线文件 (`bench_baseline.txt`) |
| P2-3-2 | 每次 PR 自动对比 benchmark 结果 |
| P2-3-3 | 内存泄漏检测 (`go test -race -memprofile`) |

---

## Phase 3: 生产就绪化 (预计 3 天)

### 3.1 AI 厂商补全
| 任务 | 描述 | 优先级 |
|------|------|--------|
| P3-1-1 | **Anthropic Claude 客户端实现** | P0 |
| P3-1-2 | **阿里云百炼(DashScope)客户端实现** | P0 |
| P3-1-3 | AI 客户端统一重试机制（指数退避） | P1 |
| P3-1-4 | AI Token 用量统计 & 成本追踪 | P2 |

### 3.2 Docker + 部署
| 任务 | 描述 |
|------|------|
| P3-2-1 | 多阶段 Dockerfile（build → runtime，镜像 <150MB） |
| P3-2-2 | docker-compose.yml（app + postgres + redis） |
| P3-2-3 | 健康检查端点 `/healthz` + `/readyz` |
| P3-2-4 | 优雅关闭（SIGTERM 处理，连接排空） |

### 3.3 CI/CD Pipeline
| 任务 | 描述 |
|------|------|
| P3-3-1 | GitHub Actions workflow（lint → test → build → docker） |
| P3-3-2 | 自动发布到容器 registry |
| P3-3-3 | 数据库迁移自动化（启动时 AutoMigrate 或独立 migrator） |

### 3.4 API 文档
| 任务 | 描述 |
|------|------|
| P3-4-1 | Swagger/OpenAPI 3.0 注解添加到所有 handler |
| P3-4-2 | Swagger UI 集成 (`swag init` + `gin-swagger`) |
| P3-4-3 | API 变更日志 (`CHANGELOG.md`) |

---

## Phase 4: 功能增强 (预计 4 天)

### 4.1 缺陷生命周期工作流
```
new → analyzing → confirmed → 
  ├── fixing → testing → resolved → closed
  └── wonfix → closed
      └── reopened → fixing ...
```

| 任务 | 描述 |
|------|------|
| P4-1-1 | Defect 状态机实现（合法转换矩阵） |
| P4-1-2 | 状态变更审计记录（who/when/from/to/comment） |
| P4-1-3 | 前端状态流转按钮（根据当前状态动态显示） |
| P4-1-4 | 批量操作（批量指派、批量修改状态、批量删除） |

### 4.2 通知系统
| 渠道 | 实现 |
|------|------|
| 站内信 | 已有 ✅ (WebSocket) |
| 邮件 | SMTP 模板通知（缺陷分配/状态变更/到期提醒） |
| Webhook | 用户自定义回调 URL |
| 钉钉/企微 | Webhook adapter（后续扩展） |

### 4.3 报表与数据可视化
| 任务 | 描述 |
|------|------|
| P4-3-1 | 缺陷趋势图（按日/周/月：新增/修复/遗留） |
| P4-3-2 | 团队工作量分布（热力图） |
| P4-3-3 | 缺陷密度分析（按模块/严重度） |
| P4-3-4 | 导出功能（Excel/PDF 格式报告） |

### 4.4 数据导入导出
| 任务 | 描述 |
|------|------|
| P4-4-1 | Excel 批量导入缺陷（模板校验） |
| P4-4-2 | 缺陷列表导出（支持筛选条件） |
| P4-4-3 | 项目配置导出/导入（环境迁移） |

---

## 📊 Sprint 4 交付物清单

```
server/
├── internal/
│   ├── cache/              # 新增: Redis session/lock
│   │   ├── redis.go        # Redis client wrapper
│   │   ├── redis_session.go # Session store
│   │   └── redis_lock.go   # Distributed lock
│   ├── middleware/         # 新增: rate_limit, cors
│   │   └── rate_limit.go  # Token bucket limiter
│   └── ai/                 # 增强: anthropic, dashscope
│       ├── anthropic.go   # NEW
│       └── dashscope.go   # NEW
├── docs/                  # 新增
│   ├── swagger/           # Auto-generated
│   └── api.md             # API reference
├── Dockerfile             # NEW
├── docker-compose.yml     # NEW
├── .github/workflows/     # NEW: CI/CD
└── Makefile               # Enhanced

web/
├── src/
│   ├── pages/
│   │   ├── defects/
│   │   │   ├── WorkflowPanel.tsx    # NEW: state machine UI
│   │   │   └── BatchActions.tsx     # NEW: bulk operations
│   │   ├── dashboard/
│   │   │   └── StatsDashboard.tsx   # NEW: charts & trends
│   │   └── settings/
│   │       ├── NotificationPage.tsx # NEW: notify config
│   │       └── ImportExport.tsx     # NEW: data migration
│   └── components/
│       ├── StateMachine.tsx         # NEW
│       └── TrendChart.tsx           # NEW
```

---

## ⏱️ 时间线

```
Week 1: Phase 1 架构升级 + Phase 2 质量工程基础
Week 2: Phase 3 生产就绪化 (AI/Docker/CI/Docs)
Week 3: Phase 4 功能增强 Part 1 (工作流+通知)
Week 4: Phase 4 功能增强 Part 2 (报表+导入导出) + 收尾
```

---

## ✅ 验收标准

- [ ] 所有新代码测试覆盖率 >70%
- [ ] `go vet` + `staticcheck` 零警告
- [ ] Docker 一键启动（`docker-compose up`）
- [ ] CI/CD 绿色通道（PR 自动 lint+test+build）
- [ ] Swagger UI 可访问
- [ ] Anthropic + 百炼 AI 可用
- [ ] 缺陷完整生命周期可用
- [ ] Benchmark 无回归
