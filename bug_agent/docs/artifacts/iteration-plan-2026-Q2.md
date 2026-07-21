# BugAgent 平台开发迭代计划

**基于PRD v1.1合规性分析报告制定**  
**计划周期**: 2026-04-05 ~ 2026-05-15 (6周)  
**当前状态**: 基础功能85%完成，核心AI能力待落地

---

## 📊 迭代总览

| 迭代 | 名称 | 周期 | 目标 | 优先级 |
|------|------|------|------|--------|
| **Sprint 1** | AI核心能力接入 | Week 1-2 | 真实AI分析和代码仓库集成 | P0 🔴 |
| **Sprint 2** | 自动修复引擎 | Week 2-3 | 完整的自动修复闭环 | P0 🔴 |
| **Sprint 3** | 协作与体验优化 | Week 3-4 | 多Agent协作+通知+权限 | P1 🟡 |
| **Sprint 4** | 企业级特性 | Week 5-6 | SSO/审计/性能优化 | P2 🟢 |

---

## 🚀 Sprint 1: AI核心能力接入

**目标**: 让AGENT分析功能真正工作，能够读取代码仓库并调用真实AI服务

**时间**: Week 1-2 (2026-04-05 ~ 2026-04-18)

### 任务清单

#### Task 1.1: AI服务客户端封装
**优先级**: P0 | **预估**: 2天 | **负责人**: Backend

**验收标准**:
- [ ] 支持OpenAI API调用
- [ ] 支持智谱AI API调用
- [ ] 支持DeepSeek API调用
- [ ] 统一的错误处理和重试机制
- [ ] 支持流式响应（可选）

**技术方案**:
```go
// server/internal/ai/client.go
type AIClient interface {
    Chat(ctx context.Context, req *ChatRequest) (*ChatResponse, error)
    ChatStream(ctx context.Context, req *ChatRequest) (<-chan *StreamChunk, error)
}

// 支持多厂商
type OpenAIClient struct { ... }
type ZhipuClient struct { ... }
type DeepSeekClient struct { ... }
```

**文件位置**:
- 新建: `server/internal/ai/client.go`
- 新建: `server/internal/ai/openai.go`
- 新建: `server/internal/ai/zhipu.go`
- 新建: `server/internal/ai/deepseek.go`

---

#### Task 1.2: Prompt工程模板
**优先级**: P0 | **预估**: 1天 | **负责人**: Backend + Product

**验收标准**:
- [ ] 产品AGENT分析Prompt模板
- [ ] UI_AGENT分析Prompt模板
- [ ] 前端AGENT分析Prompt模板
- [ ] 客户端AGENT分析Prompt模板
- [ ] 后端AGENT分析Prompt模板
- [ ] 测试AGENT分析Prompt模板
- [ ] 缺陷修复建议生成Prompt模板
- [ ] Prompt支持变量注入（缺陷信息、代码上下文等）

**技术方案**:
```go
// server/internal/ai/prompts.go
const (
    PromptFrontend = `你是一个前端开发专家AGENT...
请分析以下缺陷：
{{.DefectInfo}}
相关代码：
{{.CodeContext}}
...`
    
    PromptBackend = `你是一个后端开发专家AGENT...`
    // ... 其他AGENT类型
)
```

**文件位置**:
- 新建: `server/internal/ai/prompts.go`

---

#### Task 1.3: 代码仓库读取器（go-git集成）
**优先级**: P0 | **预估**: 2天 | **负责人**: Backend

**验收标准**:
- [ ] 克隆远程Git仓库到本地
- [ ] 读取指定分支的代码文件
- [ ] 根据关键词搜索相关代码文件
- [ ] 获取文件的最近修改记录
- [ ] 支持GitHub/GitLab/Gitee等平台
- [ ] 临时目录自动清理

**技术方案**:
```go
// server/internal/git/repo.go
type CodeRepo interface {
    Clone(ctx context.Context, url string, branch string) (*Repository, error)
    ReadFile(path string) (string, error)
    SearchFiles(keyword string) ([]string, error)
    GetFileHistory(path string, limit int) ([]Commit, error)
    Cleanup() error
}
```

**依赖库**:
```bash
go get go-git/go-git/v5
```

**文件位置**:
- 新建: `server/internal/git/repo.go`
- 新建: `server/internal/git/clone.go`
- 新建: `server/internal/git/reader.go`
- 新建: `server/internal/git/search.go`

---

#### Task 1.4: 重构AGENT分析Handler
**优先级**: P0 | **预估**: 2天 | **负责人**: Backend

**验收标准**:
- [ ] 替换Mock数据为真实AI调用
- [ ] 集成代码仓库读取能力
- [ ] 根据缺陷类型智能选择AGENT
- [ ] 异步执行分析任务（不阻塞HTTP请求）
- [ ] 分析结果结构化存储
- [ ] 分析失败时的降级处理
- [ ] 分析进度可查询

**重构要点**:
```go
// server/internal/handler/agent.go (重写)
func (h *AgentHandler) TriggerAnalysis(c *gin.Context) {
    // 1. 获取缺陷信息和关联仓库
    // 2. 根据缺陷类型选择AGENT（或使用用户指定的）
    // 3. 异步启动分析goroutine
    // 4. 立即返回taskId
}

// 后台分析流程
func performAnalysis(defectID uint, agentTypes []string) {
    // 1. 读取代码仓库
    // 2. 收集上下文（代码、日志、历史）
    // 3. 构造Prompt
    // 4. 调用AI服务
    // 5. 解析结果并存储
    // 6. 发布评论通知
}
```

**文件位置**:
- 重构: `server/internal/handler/agent.go`
- 新建: `server/internal/service/analysis.go` (业务逻辑层)

---

#### Task 1.5: 前端分析状态展示优化
**优先级**: P0 | **预估**: 1天 | **负责人**: Frontend

**验收标准**:
- [ ] 分析中显示loading动画
- [ ] 支持轮询分析进度
- [ ] 分析完成后自动刷新报告
- [ ] 分析失败时显示错误信息和重试按钮
- [ ] 显示分析耗时统计

**文件位置**:
- 修改: `web/src/pages/defects/DefectDetail.tsx`

---

### Sprint 1 交付物

✅ AI服务客户端（支持3+厂商）  
✅ 6种AGENT的Prompt模板  
✅ 代码仓库读取器  
✅ 真实的AGENT分析流程  
✅ 前端分析状态展示  

**完成标志**: 能够对真实缺陷触发AI分析，并获得有价值的分析报告

---

## 🔧 Sprint 2: 自动修复引擎

**目标**: 实现完整的自动修复链路：克隆→修改→提交→创建PR

**时间**: Week 2-3 (2026-04-12 ~ 2026-04-25)  
**依赖**: Sprint 1 的AI能力和代码仓库读取器

### 任务清单

#### Task 2.1: Git操作工具集
**优先级**: P0 | **预估**: 2天 | **负责人**: Backend

**验收标准**:
- [ ] 创建新分支（fix/BUG-{code}-{序号}）
- [ ] 修改文件内容
- [ ] 执行git add + commit
- [ ] 推送到远程仓库
- [ ] 支持合并冲突检测
- [ ] 操作日志记录

**技术方案**:
```go
// server/internal/git/operations.go
type GitOperations interface {
    CreateBranch(baseBranch string, newBranch string) error
    ModifyFile(filePath string, content string) error
    Commit(message string) error
    Push() error
    CreatePullRequest(title, body, baseBranch string) (*PR, error)
}
```

**文件位置**:
- 新建: `server/internal/git/operations.go`
- 新建: `server/internal/git/branch.go`
- 新建: `server/internal/git/commit.go`

---

#### Task 2.2: AI代码修改引擎
**优先级**: P0 | **预估**: 2天 | **负责人**: Backend

**验收标准**:
- [ ] 根据分析报告生成修复代码
- [ ] 支持diff格式输出
- [ ] 应用diff到实际文件
- [ ] 代码修改前的备份机制
- [ ] 修改后的语法检查（基础）
- [ ] 多文件修改支持

**技术方案**:
```go
// server/internal/ai/codegen.go
type CodeGenerator interface {
    GenerateFix(report *AnalysisReport, repo *CodeRepo) (*CodeChange, error)
    ApplyChange(change *CodeChange, repo *CodeRepo) error
}

type CodeChange struct {
    FilePath    string
    OldContent  string
    NewContent  string
    Diff        string
}
```

**文件位置**:
- 新建: `server/internal/ai/codegen.go`

---

#### Task 2.3: GitHub/GitLab API客户端
**优先级**: P0 | **预估**: 1天 | **负责人**: Backend

**验收标准**:
- [ ] GitHub PR创建API
- [ ] GitLab MR创建API
- [ ] Token认证
- [ ] PR/MR状态查询
- [ ] 错误处理和重试

**技术方案**:
```go
// server/internal/vcs/github.go
type GitHubClient struct {
    token    string
    baseURL string
}

func (c *GitHubClient) CreatePR(owner, repo string, pr *PullRequest) (*PR, error)
```

**依赖库**:
```bash
go get github.com/google/go-github/v56/github
```

**文件位置**:
- 新建: `server/internal/vcs/github.go`
- 新建: `server/internal/vcs/gitlab.go`
- 新建: `server/internal/vcs/client.go` (统一接口)

---

#### Task 2.4: 自动修复执行流程
**优先级**: P0 | **预估**: 2天 | **负责人**: Backend

**验收标准**:
- [ ] 完整的修复流程编排
- [ ] 步骤状态实时更新（pending→executing→completed）
- [ ] 每个步骤的错误处理
- [ ] 失败回滚机制
- [ ] 修复报告自动发布到评论区
- [ ] 支持手动触发重新修复

**执行流程**:
```
1. 初始化任务 → 更新status=planning
2. 克隆仓库 → 更新plan.steps[0].status=executing
3. 创建分支 → 更新plan.steps[1].status=completed
4. AI生成修复代码 → 更新plan.steps[2].status=in_progress
5. 应用代码修改 → 更新plan.steps[3].status=completed
6. 提交代码 → 更新commits
7. 推送远程 → 更新plan.steps[4].status=completed
8. 创建PR → 更新pullRequest
9. 发布修复报告 → 更新status=completed
10. 发送通知
```

**文件位置**:
- 重构: `server/internal/handler/fix_task.go`
- 新建: `server/internal/service/fix_engine.go`

---

#### Task 2.5: 前端修复任务详情页
**优先级**: P1 | **预估**: 1天 | **负责人**: Frontend

**验收标准**:
- [ ] 修复步骤可视化展示（Steps组件）
- [ ] 实时状态更新（WebSocket或轮询）
- [ ] PR链接可直接跳转
- [ ] 代码变更Diff展示
- [ ] 失败步骤显示错误日志
- [ ] 手动重试按钮

**文件位置**:
- 新建: `web/src/pages/defects/FixTaskDetail.tsx`
- 修改: `web/src/pages/defects/DefectDetail.tsx` (修复任务卡片增强)

---

### Sprint 2 交付物

✅ Git操作完整工具集  
✅ AI代码修改引擎  
✅ GitHub/GitLab API集成  
✅ 自动修复执行引擎  
✅ 前端修复任务监控  

**完成标志**: 点击"发起自动修复"后，系统能够自动完成：克隆代码→AI修改→提交→创建PR的全流程

---

## 🤝 Sprint 3: 协作与体验优化

**目标**: 提升团队协作效率和用户体验

**时间**: Week 3-4 (2026-04-19 ~ 2026-05-02)

### 任务清单

#### Task 3.1: 多AGENT协作调度器
**优先级**: P1 | **预估**: 2天 | **负责人**: Backend

**验收标准**:
- [ ] 支持@多个成员触发协作
- [ ] 并行调度多个AGENT分析
- [ ] 结果聚合算法（投票/加权）
- [ ] 冲突解决机制（意见不一致时）
- [ ] 协作超时控制
- [ ] 协作结果综合报告生成

**技术方案**:
```go
// server/internal/service/collaboration.go
type CollaborationManager struct {}

func (m *CollaborationManager) StartCollaboration(
    defectID uint,
    mentionedUserIDs []uint,
    triggerUserID uint,
) (*CollaborationTask, error)

func (m *CollaborationManager) AggregateResults(
    reports []*AnalysisReport,
) (*AggregatedReport, error)
```

**文件位置**:
- 新建: `server/internal/service/collaboration.go`
- 修改: `server/internal/handler/comment.go` (解析@提及)

---

#### Task 3.2: WebSocket实时通知系统
**优先级**: P1 | **预估**: 2天 | **负责人**: Backend + Frontend

**验收标准**:
- [ ] WebSocket连接管理
- [ ] 缺陷分配通知
- [ ] 分析完成通知
- [ ] 修复完成通知
- [ ] @提及通知
- [ ] 在线状态显示
- [ ] 断线重连机制

**事件类型**:
```typescript
type NotificationEvent = 
    | { type: 'defect_assigned'; data: Defect }
    | { type: 'analysis_completed'; data: AnalysisReport }
    | { type: 'fix_completed'; data: FixTask }
    | { type: 'mention'; data: Comment }
    | { type: 'comment_new'; data: Comment }
```

**文件位置**:
- 新建: `server/internal/websocket/hub.go`
- 新建: `server/internal/websocket/handler.go`
- 新建: `web/src/hooks/useWebSocket.ts`

---

#### Task 3.3: RBAC权限控制系统
**优先级**: P1 | **预估**: 2天 | **负责人**: Backend + Frontend

**验收标准**:
- [ ] 5种角色定义（组织管理员/项目管理员/开发人员/测试人员/访客）
- [ ] 权限规则配置表
- [ ] API级别权限中间件
- [ ] 前端菜单/按钮级权限控制
- [ ] 角色分配界面
- [ ] 权限变更审计日志

**角色权限矩阵**:
```
                    组织管理员  项目管理员  开发人员  测试人员  访客
创建组织              ✅         ❌         ❌       ❌      ❌
创建项目              ✅         ✅         ❌       ❌      ❌
创建缺陷              ✅         ✅         ❌       ✅      ❌
分配缺陷              ✅         ✅         ❌       ✅      ❌
发起自动修复          ✅         ✅         ❌       ✅      ❌
验证缺陷              ✅         ✅         ❌       ✅      ❌
查看缺陷              ✅         ✅         ✅       ✅      ✅
管理成员              ✅         ✅         ❌       ❌      ❌
配置AI                ✅         ✅         ❌       ❌      ❌
```

**文件位置**:
- 新建: `server/internal/middleware/rbac.go`
- 新建: `server/internal/model/permission.go`
- 新建: `web/src/components/PermissionGuard.tsx`

---

#### Task 3.4: 操作审计日志系统
**优先级**: P1 | **预估**: 1天 | **负责人**: Backend

**验收标准**:
- [ ] 审计日志数据表
- [ ] 关键操作自动记录（GORM钩子）
- [ ] 操作人、时间、内容、IP记录
- [ ] 审计日志查询API
- [ ] 日志导出功能（CSV）
- [ ] 数据保留策略配置

**监听的操作**:
- 用户AGENT身份变更
- AI配置修改
- 缺陷状态流转
- 修复任务操作
- 敏感数据访问

**文件位置**:
- 新建: `server/internal/model/audit_log.go`
- 新建: `server/internal/handler/audit.go`
- 新建: `server/internal/middleware/audit.go`

---

#### Task 3.5: 前端体验优化
**优先级**: P1 | **预估**: 2天 | **负责人**: Frontend

**优化项**:
- [ ] 全局Loading状态管理
- [ ] 错误边界和友好提示
- [ ] 表单验证增强
- [ ] 响应式布局优化
- [ ] 键盘快捷键支持
- [ ] 页面性能优化（懒加载、虚拟列表）

**文件位置**:
- 修改: `web/src/components/*`
- 修改: `web/src/utils/notification.ts`

---

### Sprint 3 交付物

✅ 多AGENT协作机制  
✅ WebSocket实时通知  
✅ RBAC权限控制  
✅ 审计日志系统  
✅ 前端体验优化  

**完成标志**: 团队可以高效协作，@成员能触发多Agent并行分析，所有关键操作可追溯

---

## 🏢 Sprint 4: 企业级特性

**目标**: 满足企业客户的高级需求和安全合规

**时间**: Week 5-6 (2026-05-03 ~ 2026-05-15)

### 任务清单

#### Task 4.1: OAuth2.0/SSO单点登录
**优先级**: P2 | **预估**: 3天 | **负责人**: Backend

**支持的SSO提供商**:
- [ ] Generic OAuth2.0
- [ ] 企业微信
- [ ] 钉钉
- [ ] 飞书

**文件位置**:
- 新建: `server/internal/auth/sso.go`
- 新建: `server/internal/auth/oauth.go`
- 修改: `server/internal/handler/auth.go`

---

#### Task 4.2: 多渠道通知集成
**优先级**: P2 | **预估**: 2天 | **负责人**: Backend

**通知渠道**:
- [ ] 邮件通知（SMTP）
- [ ] 钉钉机器人
- [ ] 企业微信机器人
- [ ] Webhook回调

**文件位置**:
- 新建: `server/internal/notifier/email.go`
- 新建: `server/internal/notifier/dingtalk.go`
- 新建: `server/internal/notifier/wechat.go`

---

#### Task 4.3: 数据统计报表
**优先级**: P2 | **预估**: 2天 | **负责人**: Frontend + Backend

**报表类型**:
- [ ] 缺陷趋势图（按日/周/月）
- [ ] 缺陷分布图（按严重程度/类型/状态）
- [ ] 团队效率分析
- [ ] AGENT分析效果统计
- [ ] 修复成功率统计
- [ ] 数据导出（Excel/PDF）

**技术选型**: ECharts / Apache ECharts

**文件位置**:
- 新建: `server/internal/handler/stats.go`
- 新建: `web/src/pages/projects/ProjectStats.tsx`

---

#### Task 4.4: 性能优化
**优先级**: P2 | **预估**: 2天 | **负责人**: Backend

**优化项**:
- [ ] 数据库查询优化（索引、慢查询）
- [ ] Redis缓存集成（热点数据）
- [ ] API响应压缩
- [ ] 静态资源CDN
- [ ] 连接池优化
- [ ] 并发控制（限流）

**文件位置**:
- 修改: `server/internal/database/database.go`
- 修改: `server/internal/cache/redis.go` (增强)
- 新建: `server/internal/middleware/rate_limit.go`

---

#### Task 4.5: 安全加固
**优先级**: P2 | **预估**: 2天 | **负责人**: Backend

**安全措施**:
- [ ] SQL注入防护（已通过ORM部分实现）
- [ ] XSS攻击防护
- [ ] CSRF token验证
- [ ] 敏感接口频率限制
- [ ] 安全响应头设置
- [ ] 依赖库漏洞扫描
- [ ] 配置敏感信息环境变量化

**文件位置**:
- 修改: `server/internal/middleware/security.go`
- 新建: `server/internal/middleware/csrf.go`
- 修改: `server/cmd/server/config.yaml`

---

#### Task 4.6: API文档和测试
**优先级**: P2 | **预估**: 2天 | **负责人**: Backend

**交付物**:
- [ ] Swagger/OpenAPI 3.0文档
- [ ] 核心API单元测试（覆盖率>60%）
- [ ] 集成测试用例
- [ ] Postman集合导出
- [ ] 接口Mock服务

**文件位置**:
- 新建: `server/docs/swagger.yaml`
- 新建: `server/*_test.go` (各模块测试文件)

---

### Sprint 4 交付物

✅ SSO单点登录（支持企业微信/钉钉）  
✅ 多渠道通知（邮件/IM/Webhook）  
✅ 数据统计报表  
✅ 性能优化（缓存+限流）  
✅ 安全加固  
✅ API文档和测试  

**完成标志**: 产品达到企业级生产标准，可以通过安全合规审查

---

## 📈 成功指标

### 技术指标

| 指标 | 当前值 | Sprint 1后 | Sprint 2后 | 最终目标 |
|------|--------|-----------|-----------|----------|
| AI分析真实率 | 0% | 100% | 100% | 100% |
| 自动修复成功率 | 0% | - | >70% | >80% |
| API测试覆盖率 | <10% | - | - | >60% |
| 平均响应时间 | <500ms | <500ms | <500ms | <300ms |
| WebSocket连接稳定性 | 0% | - | >95% | >99% |

### 业务指标

| 指标 | 当前值 | Sprint 1后 | Sprint 2后 | 最终目标 |
|------|--------|-----------|-----------|----------|
| 缺陷分析自动化率 | 0% | >50% | >80% | >90% |
| 平均修复时长 | 人工 | - | 缩短50% | 缩短70% |
| 团队协作效率 | 低 | - | 提升30% | 提升50% |

---

## ⚠️ 风险和缓解措施

### 高风险

**风险1**: AI服务质量不稳定
- **影响**: 分析结果质量波动
- **缓解**: 
  - 多厂商备选机制
  - 结果质量评分
  - 人工审核兜底

**风险2**: Git操作权限问题
- **影响**: 无法自动推送代码
- **缓解**: 
  - 使用Deploy Key而非个人Token
  - 详细的错误提示
  - 手动修复降级方案

**风险3**: 代码修改引入新Bug
- **影响**: 自动修复反而制造问题
- **缓解**: 
  - 仅修改明确指出的文件
  - 保留原始代码备份
  - 强制人工Code Review

### 中风险

**风险4**: 性能瓶颈
- **影响**: 大量并发分析时系统变慢
- **缓解**: 
  - 任务队列异步处理
  - 资源限制和排队机制
  - Redis缓存热点数据

**风险5**: 安全漏洞
- **影响**: 数据泄露或系统被攻击
- **缓解**: 
  - 定期安全扫描
  - 最小权限原则
  - 敏感操作审计

---

## 🛠️ 开发规范

### 代码规范
- Go代码遵循官方Effective Go
- React代码遵循Airbnb风格
- 所有新增代码必须有注释
- 关键函数必须有单元测试

### Git工作流
```
main ← release/v1.1 ← feature/ai-client
                      ← feature/git-integration
                      ← feature/auto-fix-engine
                      ← ...
```

### 提交信息格式
```
feat(ai): 添加OpenAI客户端实现
fix(git): 修复分支创建竞态条件
docs(api): 更新Swagger文档
test(analysis): 添加分析流程单元测试
```

### Code Review要求
- 所有P0任务必须经过Review
- 至少1人 approve才能合并
- 自动CI检查必须通过

---

## 📞 联系方式

**项目负责人**: [待填写]  
**技术负责人**: [待填写]  
**产品负责人**: [待填写]

**文档版本**: v1.0  
**最后更新**: 2026-04-05  
**下次评审**: 2026-04-12 (Sprint 1结束后)
