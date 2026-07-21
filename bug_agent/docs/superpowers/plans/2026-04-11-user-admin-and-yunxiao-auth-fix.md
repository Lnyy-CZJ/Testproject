# User Admin And Yunxiao Auth Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复用户管理最近登录时间、重置密码交互、项目 Webhook 操作区布局，以及云效错误误登出问题。

**Architecture:** 后端补充用户登录时间字段与登录写入逻辑，同时收紧云效错误映射；前端调整用户管理展示与交互，并将全局 401 拦截改为只处理系统登录态失效。通过后端定向测试、前端构建和真实接口验证收口。

**Tech Stack:** Go, Gin, GORM, React, TypeScript, Ant Design, Axios

---

### Task 1: 后端行为测试与实现
**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/server/internal/model/models.go`
- Modify: `/Users/jame/Workspace/bug_agent/server/internal/handler/auth.go`
- Modify: `/Users/jame/Workspace/bug_agent/server/internal/handler/yunxiao_integration.go`
- Modify: `/Users/jame/Workspace/bug_agent/server/internal/handler/auth_create_test.go`
- Create/Modify: `/Users/jame/Workspace/bug_agent/server/internal/handler/yunxiao_integration_test.go`

- [ ] 写最近登录时间与云效错误映射的失败测试
- [ ] 运行定向测试，确认红灯
- [ ] 实现最小后端修复
- [ ] 重新运行定向测试，确认绿灯

### Task 2: 前端页面与拦截器修复
**Files:**
- Modify: `/Users/jame/Workspace/bug_agent/web/src/types/index.ts`
- Modify: `/Users/jame/Workspace/bug_agent/web/src/api/request.ts`
- Modify: `/Users/jame/Workspace/bug_agent/web/src/pages/users/index.tsx`
- Modify: `/Users/jame/Workspace/bug_agent/web/src/pages/projects/ProjectNotifications.tsx`

- [ ] 调整用户类型与用户列表列定义
- [ ] 为重置密码增加行级 loading 与禁点
- [ ] 调整 Webhook 操作区为单行布局
- [ ] 收紧 401/403 拦截逻辑

### Task 3: 验证
**Files:**
- Reuse existing tests and runtime

- [ ] 运行后端定向测试
- [ ] 运行前端 `npm run build`
- [ ] 对登录、用户列表、重置密码、云效仓库拉取做一次真实联调验证
