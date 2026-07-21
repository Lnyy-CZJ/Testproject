# BugAgent v5.6 决策文档

> Version: v5.6  
> Date: 2026-05-08  
> 对应 PRD: PRD-v5.6-agent-architecture-redesign.md

---

## 1. 架构决策记录（ADR）

### ADR-1: 用 Planner Agent 替代 Explorer Agent

**上下文**：当前 Explorer Agent 使用 LoopAgent 模式，每轮调用工具、读取结果、决定下一步。但在工具不可用时产出噪音（编造 JSON），干扰后续 Analysis Agent。

**决策**：用 Planner Agent 替代。Planner 一次性输出结构化探索计划（步骤列表），Executor 按计划依次调用工具。

**理由**：
- Planner 的输出是确定性的（JSON 步骤列表），不会产出噪音
- Executor 按计划执行，结果可控、可审计
- Planner 失败时可直接 fallback 到预检索代码上下文，不需要额外的错误恢复逻辑

**替代方案**：
- ~~保留 Explorer 但绑定更多工具~~ — Explorer 的 LoopAgent 模式仍然不可控，工具调用失败时会重试或编造
- ~~去掉 Explorer，直接用预检索~~ — 预检索的代码片段有限，AI 无法深入探索

### ADR-2: ToolRegistry 用内存缓存 + DB 持久化

**上下文**：工具集需要按项目类型动态组装，且需要支持运行时变更（启用/禁用 Retriever Plugin）。

**决策**：ToolRegistry 在启动时从 DB 加载工具配置到内存，变更时通过事件通知刷新缓存。Resolve 操作只读内存，响应时间 < 1ms。

**理由**：
- 工具配置变更频率极低（小时级），内存缓存命中率接近 100%
- DB 持久化保证重启后配置不丢失
- 事件通知保证多实例间缓存一致性

**替代方案**：
- ~~每次 Resolve 都查 DB~~ — 延迟不可接受（每次 Agent 调用都要 Resolve）
- ~~纯内存，不持久化~~ — 重启后配置丢失

### ADR-3: SubmissionQueue 用优先级堆而非 FIFO

**上下文**：用户手动触发的分析应该比自动触发的优先执行。

**决策**：使用 container/heap 实现优先级堆。优先级：0=用户触发，1=自动触发，2=后台补分析。同优先级 FIFO。

**理由**：
- 优先级堆保证高优先级任务先执行
- Go 标准库 container/heap 足够简单，无需引入外部依赖

**替代方案**：
- ~~FIFO 队列~~ — 无法区分优先级
- ~~Redis 队列~~ — 过重，单实例部署不需要分布式队列

### ADR-4: CancellationToken 用 context.WithCancel 而非独立信号

**上下文**：需要在分析过程中支持精细取消（取消整个分析 vs 取消当前步骤）。

**决策**：使用 context.WithCancel 创建分层 context。根 context 控制整个分析，子 context 控制单个步骤。

**理由**：
- Go 的 context 已经是标准取消模式，所有工具调用都接受 context
- 分层 context 自然支持精细取消
- 不需要额外的信号机制

**替代方案**：
- ~~独立 CancellationToken 结构体~~ — 需要改造所有工具调用签名，侵入性大
- ~~channel 信号~~ — 不如 context 标准

### ADR-5: RolloutRecorder 用 GORM + PostgreSQL 而非 SQLite

**上下文**：Codex 用 SQLite 存储会话记录，但 BugAgent 是多实例服务端部署。

**决策**：用 GORM + PostgreSQL 存储会话记录，复用现有数据库连接。

**理由**：
- BugAgent 已有 PostgreSQL 基础设施，无需引入新存储
- 多实例部署时 SQLite 无法共享
- GORM 已在项目中广泛使用

**替代方案**：
- ~~SQLite~~ — 多实例不兼容
- ~~文件系统~~ — 不可查询、不可管理

### ADR-6: SafetyGate 用白名单 + 路径校验而非操作系统沙箱

**上下文**：Codex 用 bwrap/landlock 做操作系统级沙箱，但 BugAgent 是服务端部署。

**决策**：SafetyGate 用工具白名单 + 文件路径校验。只读工具自动批准，写操作工具校验路径是否在项目范围内。

**理由**：
- 服务端部署不需要防御恶意代码（Agent 不执行用户代码）
- bwrap/landlock 在容器环境中配置复杂
- 白名单 + 路径校验足够覆盖当前需求

**替代方案**：
- ~~bwrap 沙箱~~ — 过重，服务端不需要
- ~~无安全评估~~ — 未来引入 apply_patch 时无审批机制

---

## 2. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| Planner 输出格式不稳定 | 中 | 高 | 强 JSON Schema 约束 + 解析容错 + fallback 到预检索 |
| 调度器 goroutine 泄漏 | 低 | 中 | defer cleanup + 定时健康检查 |
| ToolRegistry 缓存不一致 | 低 | 低 | 事件通知 + 5 分钟 TTL 兜底刷新 |
| 会话恢复后上下文丢失 | 中 | 中 | 恢复时重新注入代码上下文 |
