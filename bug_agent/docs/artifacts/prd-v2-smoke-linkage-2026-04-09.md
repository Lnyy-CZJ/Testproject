# PRD v2.0 前后端联调冒烟报告（2026-04-09）

## 1. 目标
对 v2.0 关键链路进行一轮“接口顺序级”前后端联调冒烟，覆盖：
- 邀请注册
- 项目创建与项目切换数据源
- 仓库凭证与连接测试
- 个人信息与 AGENT 身份
- 通知偏好
- 协作分析与聚合报告

## 2. 本轮执行

### 2.1 新增链路级烟囱测试
- 新增测试文件：
  - `server/internal/handler/v2_smoke_integration_test.go`
- 关键步骤（单测内顺序执行）：
  1. `POST /invites` 创建邀请码
  2. `GET /invites/:code/validate` 校验邀请码
  3. `POST /invites/:code/accept` 邀请注册新用户
  4. `GET /users/me` 获取个人信息
  5. `PUT /users/me/agent-types` 更新 AGENT 身份
  6. `POST /projects` 创建项目
  7. `GET /user/projects` 验证项目切换数据源
  8. `POST /credentials` 创建凭证
  9. `POST /projects/:id/repos` 创建仓库
  10. `POST /repos/:id/test-connection` 测试连接（使用仓库绑定信息）
  11. `GET /notification-preferences` 获取通知偏好
  12. `PUT /notification-preferences` 更新通知偏好
  13. `POST /collaborations` 启动协作分析
  14. `GET /collaborations/:taskId` 轮询直到完成
  15. `GET /collaborations/:taskId/report` 获取聚合报告

### 2.2 联调中发现并修复的问题
- 协作完成评论在“无 assignee 场景”可能写入非法 `user_id`，触发外键错误。
  - 修复文件：`server/internal/service/collaboration.go`
  - 修复策略：
    - 评论作者优先级：`triggerUserID` -> `assigneeID` -> `reporterID`
    - 写入前校验 `defect` 与 `user` 仍存在，不满足则跳过评论发布
  - 回归测试：
    - 新增 `TestCollaborationService_publishCollaborationComment_FallbackActor`
    - 文件：`server/internal/service/collaboration_test.go`

## 3. 验证结果

### 3.1 链路冒烟
- `go test ./internal/handler -run TestV2Smoke_EndToEndFlow -count=1 -v`
- 结果：PASS

### 3.2 后端回归
- `go test ./... -count=1`
- 结果：PASS

### 3.3 前端构建回归
- `npm run build`
- 结果：PASS

## 4. 本轮联调结论
- 关键链路已打通，核心接口可以按 PRD v2.0 流程顺序协同工作。
- 冒烟过程中发现的协作评论外键问题已修复并补测。

## 5. 剩余风险（本轮后）
- 协作分析是异步流程，当前链路测试使用轮询等待完成；高并发下建议增加任务级超时与重试观测指标。
- 仓库连接测试依赖运行环境（网络/DNS/仓库可达性）；当前链路已验证“调用闭环”，建议上线前补充真实仓库环境 smoke。
- 前端联调目前以“构建成功 + 后端链路测试”为主，建议补充浏览器侧自动化 e2e（登录态、路由跳转、页面交互断言）。
