# BugAgent v4.0 (Phase 4) PRD

> Version: v4.0  
> Date: 2026-04-10  
> Status: Draft  
> Owner: Product + Engineering

---

## 1. Background

当前系统已完成 v3.0 第三期能力，具备：

1. 项目、迭代、缺陷、仓库、AI 配置与协作主流程。
2. 云效凭证、仓库导入、成员导入。
3. AI 厂商/模型目录数据库化与后台维护。
4. 用户个人资料、个人凭证、个人通知偏好。

但在平台治理、通知体系和账户入口上仍存在明显缺口：

1. 凭证只支持用户私有维度，管理员无法统一维护可复用凭证，也无法限制项目可见范围。
2. 通知配置只有用户维度，缺少项目全局通知规则、项目 webhook 管理与平台 SMTP 管理。
3. 个人信息仍是独立页面，顶部通知按钮没有交互闭环。
4. AI 目录仍存在代码内置 fallback，平台无法完全以数据库为唯一配置源。
5. 用户安全能力不足，缺少管理员重置密码和首次登录强制改密机制。

本期目标是在不重做核心业务域模型的前提下，补齐“平台治理能力 + 通知闭环 + 账户安全能力”。

---

## 2. Product Goals And Non-Goals

### 2.1 Goals

1. 新增平台全局凭证管理，支持管理员统一维护并限制项目使用范围。
2. 新增项目级通知管理，支持多 webhook 地址、单类别单 webhook 目标选择。
3. 将个人信息改为全局弹窗，补齐个人 webhook 和修改密码入口。
4. 新增平台配置页，支持发件邮箱配置与测试。
5. 新增管理员重置密码与首次登录强制修改密码能力。
6. 彻底移除项目代码写死的 AI 厂商/模型配置，改为数据库唯一来源。
7. 修复顶部通知按钮无响应问题，形成消息中心闭环。

### 2.2 Non-Goals

1. 不做跨组织/多租户权限体系重构。
2. 不做完整的密码复杂度策略中心和 MFA。
3. 不做站内消息模板编排器。
4. 不做 AI 厂商动态能力探测调度系统，仅支持手动触发模型可用性测试。
5. 不兼容历史前端版本和旧交互路径（项目尚未上线）。

---

## 3. Personas

1. 平台管理员：维护平台凭证、SMTP、AI 目录、用户密码与平台级治理配置。
2. 项目管理员：配置项目通知规则、维护项目 webhook、选择可用凭证、管理项目 AI 配置。
3. 普通成员：维护个人资料、个人凭证、个人 webhook、通知偏好与密码。

---

## 4. Core Decisions

### 4.1 凭证并存策略

1. 平台全局凭证与个人凭证并存。
2. 项目侧选择器统一展示：
   - 平台凭证（仅展示当前项目被授权的项）
   - 当前用户个人凭证
3. 平台凭证仅管理员可增删改查，个人凭证仍由用户自己维护。

### 4.2 通知优先级策略

1. 项目通知配置是上限规则。
2. 个人通知偏好只能在项目允许的范围内细化，不能突破项目上限。
3. 个人 webhook 的语义是：
   - 只要某条消息最终成功写入该用户的站内消息中心
   - 且用户开启了个人 webhook
   - 系统就异步镜像一份消息到用户个人 webhook
4. 项目 webhook 的语义是：
   - 项目级事件的额外推送目标
   - 每个通知类别最多选择一个项目 webhook 地址

### 4.3 密码安全策略

1. 管理员重置密码时生成临时密码。
2. 被重置用户首次使用临时密码登录后必须修改密码。
3. 未完成修改前不可进入主业务页面。

### 4.4 AI 目录唯一数据源策略

1. AI 厂商/模型目录的唯一来源为数据库。
2. 不再保留代码内置厂商/模型列表作为运行时 fallback。
3. 初始目录通过 migration/seed 写入数据库。

---

## 5. User Stories

1. 作为平台管理员，我可以维护平台全局凭证，并限制哪些项目可以使用它。
2. 作为项目管理员，我可以在项目通知管理里配置每类通知允许的通道，并为 webhook 选择一个项目级目标地址。
3. 作为普通成员，我可以从任意页面打开个人中心弹窗，维护个人资料、密码、凭证和个人 webhook。
4. 作为平台管理员，我可以在平台配置页填写 SMTP 配置并测试发信是否成功。
5. 作为平台管理员，我可以在用户管理中按项目归属筛选用户，并为指定用户重置密码。
6. 作为平台管理员，我可以在 AI 目录页以“厂商 -> 模型”的展开结构维护目录，并对模型做可用性测试。
7. 作为所有登录用户，我点击顶部通知按钮时可以看到消息列表、未读数和已读操作。

---

## 6. Functional Requirements

### FR-1 平台全局凭证管理

1. 新增“平台凭证管理”页面，仅平台管理员可见。
2. 支持凭证字段：
   - `name`
   - `type`
   - `provider`
   - `content`
   - `extraConfig`
   - `status`（active/inactive）
   - `allowedProjectIds`（多选）
3. 支持凭证类型沿用现有体系：
   - `pat`
   - `oauth`
   - `ssh_key`
   - `username_password`
4. 支持平台凭证操作：
   - 创建
   - 编辑
   - 删除
   - 启用/停用
   - 测试连接
   - 调整项目授权范围
5. 平台凭证需要：
   - 服务端加密存储
   - 返回脱敏值
   - 审计日志
   - `lastUsedAt` 回写
6. 项目使用规则：
   - 项目只能看到被授权的活跃平台凭证
   - 未授权项目在接口和 UI 中均不可见
   - 平台凭证在项目选择器中带来源标签 `平台`
   - 个人凭证在项目选择器中带来源标签 `个人`

验收标准：
1. 平台管理员可创建 1 个凭证并授权给多个项目。
2. 被授权项目可正常选择该凭证，未授权项目完全看不到。
3. 平台凭证连接测试成功后更新时间与 `lastUsedAt` 正常回写。

### FR-2 项目全局通知管理

1. 在项目左侧菜单新增“通知管理”，位置在“AI 配置”下面。
2. 项目通知管理包含两个区域：
   - 项目 webhook 地址管理
   - 项目通知规则配置
3. 项目 webhook 地址管理：
   - 支持多个地址
   - 字段包括 `name/url/secret/enabled`
   - 支持新增、编辑、删除、启用、停用、测试发送
4. 项目通知规则按类别维护，首期覆盖：
   - `defect_assigned`
   - `defect_status_change`
   - `defect_mention`
   - `defect_due_soon`
   - `iteration_start`
   - `iteration_end`
   - `collaboration_complete`
5. 每个类别支持配置：
   - `站内消息` 开/关
   - `邮件` 开/关
   - `Webhook 目标` 单选下拉
   - 可选值为 `不发送 webhook` + 当前项目可用 webhook 地址
6. 项目配置是上限规则：
   - 若项目关闭某通道，则个人偏好不可再开启
   - 若项目未选择 webhook 目标，则项目级 webhook 不发送
7. 项目规则只适用于项目域事件；平台公告仍走平台/个人维度。

验收标准：
1. 项目管理员可为一个项目新增 3 个 webhook 地址。
2. 同一通知类别只能选择 1 个 webhook 目标。
3. 用户个人偏好无法突破项目关闭的通道上限。

### FR-3 全局个人中心弹窗

1. 移除独立 `/profile` 导航入口，改为全局 `User Center Modal`。
2. 打开入口：
   - 顶部头像菜单点击“个人信息”
   - 在任意页面均可打开
3. 弹窗内至少包含 5 个页签：
   - 基本信息
   - AGENT 身份
   - 访问凭证
   - 通知设置
   - 安全设置
4. “通知设置”页签新增个人 webhook 配置：
   - 首期采用单 webhook 配置
   - 字段包括 `url/secret/enabled`
   - 支持测试发送
5. 个人 webhook 推送规则：
   - 对所有成功写入该用户站内消息中心的消息，额外异步推送一份到用户个人 webhook
   - 若个人 webhook 关闭或发送失败，不影响站内消息写入
6. “安全设置”页签新增：
   - 修改密码
   - 当用户被标记为 `must_change_password=true` 时，登录后强制展示修改密码流程

验收标准：
1. 从项目页和全局页都能打开同一个个人中心弹窗。
2. 成员开启个人 webhook 后，收到 1 条站内消息时会额外收到 1 次 webhook 推送。
3. 被要求强制改密的用户登录后无法直接进入项目列表。

### FR-4 通知中心与顶部通知按钮修复

1. 修复顶部通知按钮点击无响应问题。
2. 顶部通知按钮改为“消息中心入口”，支持：
   - 显示未读数量
   - 打开抽屉/弹层
   - 列表分页加载
   - 单条标记已读
   - 全部标记已读
   - 点击消息跳转到关联对象
3. 顶部通知入口在全局布局和项目布局保持一致行为。

验收标准：
1. 点击通知按钮 100% 可打开消息中心。
2. 未读数与实际未读列表一致。
3. 点击消息可跳转到对应缺陷/协作/迭代详情页。

### FR-5 平台配置页（发件邮箱）

1. 新增“平台配置”页，仅平台管理员可见。
2. 首期支持通知发件邮箱配置：
   - `smtpHost`
   - `smtpPort`
   - `smtpUser`
   - `smtpPassword`
   - `smtpFrom`
   - `securityType`（none/ssl/tls）
3. 支持：
   - 保存配置
   - 测试发送到指定邮箱
   - 查看最近测试结果
4. 敏感字段需加密存储。
5. 通知服务发送邮件时优先读取数据库平台配置，不再依赖静态环境变量作为唯一来源。

验收标准：
1. 平台管理员可保存 SMTP 配置并测试发送成功。
2. SMTP 未配置时，邮件通道显示不可用但不影响站内消息和 webhook。

### FR-6 用户管理增强

1. 用户管理新增“项目归属筛选”：
   - 支持按单个项目筛选
   - 仅返回属于该项目的成员
2. 用户管理新增“管理员重置密码”：
   - 操作后生成临时密码
   - 标记用户 `must_change_password=true`
   - 返回一次性展示的临时密码给管理员复制
3. 用户成功修改密码后：
   - 清除 `must_change_password`
   - 记录最近密码修改时间

验收标准：
1. 平台管理员可以筛选查看某项目的用户列表。
2. 管理员重置密码后，用户首次登录必须完成改密。

### FR-7 AI 目录治理升级

1. 删除运行时代码写死的 AI 厂商/模型清单。
2. 初始厂商和模型通过数据库 seed 写入。
3. AI 目录后台展示改为“厂商列表”，点击展开模型列表：
   - 厂商层展示 `displayName/providerKey/status/defaultEndpoint`
   - 模型层展示 `modelName/status/capabilityTags/isDefault/endpoint`
4. 支持在模型维度执行“可用性测试”：
   - 输入临时 API Key
   - 使用当前模型与端点发送轻量探测请求
   - 返回成功/失败、耗时与错误摘要
5. 项目 AI 配置页读取数据库目录，不再回退代码内置列表。

验收标准：
1. 数据库中删除某个模型后，项目 AI 配置页刷新后不可再选到该模型。
2. 厂商列表可展开查看对应模型。
3. 管理员可对任意激活模型发起可用性测试并看到结果。

---

## 7. Interaction Design Requirements

1. 顶部右侧区域新增两个统一入口：
   - 通知中心
   - 个人中心
2. 个人中心不再进行页面跳转，应以模态层形式覆盖当前页面。
3. 项目通知管理页遵循“列表 + 规则表单”布局：
   - 上半部分为 webhook 地址列表
   - 下半部分为通知类别规则表
4. AI 目录页采用主从展开式列表，不再用两张平铺表割裂厂商和模型关系。
5. 所有测试动作都需有明确反馈：
   - 测试中
   - 成功
   - 失败原因

---

## 8. API Design (Draft)

### 8.1 平台凭证

1. `GET /api/v1/admin/platform-credentials`
2. `POST /api/v1/admin/platform-credentials`
3. `PUT /api/v1/admin/platform-credentials/:id`
4. `DELETE /api/v1/admin/platform-credentials/:id`
5. `POST /api/v1/admin/platform-credentials/:id/test`
6. `PUT /api/v1/admin/platform-credentials/:id/projects`
7. `GET /api/v1/projects/:id/available-credentials`

### 8.2 项目通知管理

1. `GET /api/v1/projects/:id/notification-settings`
2. `PUT /api/v1/projects/:id/notification-settings`
3. `GET /api/v1/projects/:id/webhooks`
4. `POST /api/v1/projects/:id/webhooks`
5. `PUT /api/v1/projects/:id/webhooks/:webhookId`
6. `DELETE /api/v1/projects/:id/webhooks/:webhookId`
7. `POST /api/v1/projects/:id/webhooks/:webhookId/test`

### 8.3 个人中心与安全

1. `GET /api/v1/users/me`
2. `PUT /api/v1/users/me`
3. `PUT /api/v1/users/me/password`
4. `GET /api/v1/users/me/webhook`
5. `PUT /api/v1/users/me/webhook`
6. `POST /api/v1/users/me/webhook/test`

### 8.4 通知中心

1. `GET /api/v1/notifications`
2. `GET /api/v1/notifications/unread-count`
3. `PUT /api/v1/notifications/read`
4. `PUT /api/v1/notifications/read-all`

### 8.5 平台配置

1. `GET /api/v1/admin/platform-settings/notification`
2. `PUT /api/v1/admin/platform-settings/notification`
3. `POST /api/v1/admin/platform-settings/notification/test-email`

### 8.6 用户管理增强

1. `GET /api/v1/users?projectId=xxx`
2. `POST /api/v1/users/:id/reset-password`

### 8.7 AI 目录

1. `GET /api/v1/admin/ai/catalog-tree`
2. `POST /api/v1/admin/ai/models/:id/test`

---

## 9. Data Model Changes

1. 新增 `platform_credentials`
   - 平台级凭证主表
2. 新增 `platform_credential_projects`
   - 平台凭证与项目授权关系
3. 新增 `project_webhooks`
   - 项目 webhook 地址表
4. 新增 `project_notification_policies`
   - 项目通知规则表
5. 新增 `user_webhook_settings`
   - 用户个人 webhook 配置
6. 新增 `platform_settings`
   - 平台配置键值表，首期用于 SMTP
7. 扩展 `users`
   - `must_change_password`
   - `password_changed_at`
   - `password_reset_at`
   - `password_reset_by`
8. `notification_preferences`
   - 继续保留用户维度偏好，但计算有效通道时需叠加项目上限规则
9. AI 目录表继续沿用：
   - `ai_provider_catalog`
   - `ai_model_catalog`
10. 数据初始化：
   - AI 厂商和模型通过 seed 写入，不再依赖代码内置列表

---

## 10. Permission Design

1. 平台凭证管理：仅 `super_admin/admin`。
2. 平台配置页：仅 `super_admin/admin`。
3. 用户重置密码：仅 `super_admin/admin`。
4. 项目通知管理：项目管理员及以上。
5. 项目 webhook 管理：项目管理员及以上。
6. 个人中心与个人 webhook：仅本人。
7. 通知中心：仅查看本人消息。

---

## 11. Error Handling

1. 平台凭证未授权给项目：返回 `403` + `当前项目无权使用该平台凭证`。
2. webhook 测试失败：返回明确失败原因（超时、状态码、证书错误等）。
3. SMTP 测试失败：返回服务器错误摘要，不落完整敏感凭证。
4. 强制改密用户试图跳过改密进入业务页：返回 `403` + `请先修改密码`。
5. 模型可用性测试失败：返回 `provider/model/endpoint` 与错误摘要。
6. 若 AI 目录数据库为空：系统视为初始化失败，后台提示缺少 seed 数据，不回退到代码清单。

---

## 12. Non-Functional Requirements

1. 性能：
   - 通知未读数接口 P95 < 200ms
   - 通知列表接口 P95 < 500ms（20 条）
   - 项目通知设置读取 P95 < 300ms
2. 稳定性：
   - webhook 推送失败不影响主交易流程
   - 个人 webhook 与项目 webhook 均采用异步派发
3. 安全：
   - 凭证、SMTP 密码、webhook secret 均加密存储
   - 临时密码不写入审计明文
4. 审计：
   - 记录平台凭证、项目通知规则、平台配置、密码重置、模型测试等关键动作
5. 可观测性：
   - 记录 webhook/邮件发送耗时、失败码、重试次数

---

## 13. Rollout Plan

1. 阶段 1：先交付通知按钮修复、个人中心弹窗与密码能力。
2. 阶段 2：交付平台凭证管理与项目授权。
3. 阶段 3：交付项目通知管理与 SMTP 平台配置。
4. 阶段 4：交付 AI 目录树形展示与模型可用性测试。
5. 阶段 5：完成联调、E2E、性能回归与上线准备。

回滚策略：
1. 新增表与新增接口可按功能开关隐藏入口。
2. 若项目通知管理异常，可退回现有用户维度通知偏好。
3. 若 AI 目录树形页异常，不影响已有项目 AI 配置读取。

---

## 14. Definition Of Done

1. FR-1 ~ FR-7 全部有实现与验收证据。
2. 顶部通知按钮具备完整交互闭环。
3. 平台凭证、项目通知、个人 webhook、SMTP、密码重置与 AI 目录测试均可演示。
4. 自动化验证至少覆盖：
   - 后端单测/集成测试
   - 浏览器 E2E
   - 关键接口联调
5. 文档、数据迁移、权限、前端入口保持一致。
