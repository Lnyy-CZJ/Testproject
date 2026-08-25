# 平台用户级凭证与 LLM 配置隔离 PRD

> 文档版本：V1.0
> 创建日期：2026-08-23
> 文档状态：待评审
> 适用平台：`test-platform`
> 关联设计：[DEV_DESIGN-平台用户级凭证与LLM配置隔离-V1.0.md](./DEV_DESIGN-平台用户级凭证与LLM配置隔离-V1.0.md)
> 关联计划：[DEV_PLAN-平台用户级凭证与LLM配置隔离-V1.0.md](./DEV_PLAN-平台用户级凭证与LLM配置隔离-V1.0.md)

---

## 1. 文档摘要

平台当前已经按 `dev/prod` 环境管理工具配置、Secret、Credential 和 LLM Profile，但同一环境内仍只有一套业务凭证。任何获得工具执行权限的登录用户，最终都会使用同一套下游账号、Token 或 LLM API Key。

本期把配置控制面拆成两类清晰边界：

1. **系统配置继续全局统一管理**：功能开关、超时、队列限制、Provider Host 白名单、数据库连接、KEK、Tool Client Token 等保持平台或部署级作用域；
2. **业务凭证改为登录用户私有**：下游账号、用户名密码、Access/Refresh Token、设备标识、Admin 账号、个人 LLM 连接和 API Key 均按登录用户隔离。

本机与线上当前已配置的业务凭证全部迁移给各自数据库中的 `admin` 用户。其他用户迁移后处于“未配置”状态；任务必须失败关闭并提示用户配置自己的凭证，禁止回退使用 `admin`、其他用户或旧平台全局凭证。

---

## 2. 背景与现状

### 2.1 已有能力

平台已经具备：

- 平台本地用户、服务端 Session、RBAC 和网关统一鉴权；
- Nginx 向工具注入可信 `X-Platform-User-ID`、用户名和权限；
- `dev/prod` 环境、ConfigDefinition、Release、Activation；
- AES-256-GCM 信封加密的 Secret/SecretVersion；
- Credential 生命周期、刷新租约和 Credential Agent；
- LLM Profile、工具能力 Binding 和不可变运行快照；
- 功能测试智能体、API 测试智能体任务中的 `created_by_user_id`；
- Truthy Search、API AutoTest、日志 AI 和两个智能体的平台配置读取链路；
- Secret、配置、任务和工具事件审计。

### 2.2 当前问题

当前数据和运行时范围主要是：

```text
environment + tool/profile/binding + provider
```

缺少登录用户主体，产生以下问题：

1. 用户 A 配置或更新 Token 后，用户 B 的任务也会使用该 Token；
2. LLM Profile 和 API Key 是公共配置，无法按用户计费、停用或轮换；
3. Credential Agent 只维护每个工具/环境的一套会话；
4. 工具内部 `runtime-config` 只认证工作负载身份，不知道本次任务属于哪个登录用户；
5. 普通用户没有自助维护个人业务凭证的入口；
6. 将数据直接增加 `user_id` 后，如果旧版工具回滚且忽略该字段，可能读取并混合多名用户的凭证。

### 2.3 问题边界

本期解决的是**业务运行凭证和 LLM 连接的用户级隔离**，不是把所有平台配置复制给每个用户。

以下配置仍然全局：

- 平台会话、安全、审计和保留策略；
- 工具 URL、超时、队列、上传限制、功能开关；
- LLM Provider Host 允许列表；
- 数据库持久化连接等系统集成参数；
- PostgreSQL 密码、KEK、Bootstrap Token、Tool Client Token、用户上下文签名密钥；
- 工具能力目录与 LLM Binding 目录。

---

## 3. 产品目标与成功标准

### 3.1 产品目标

#### G1：用户级业务凭证隔离

每个登录用户只能查看、配置、验证和使用自己的业务账号、密码和 Token。

#### G2：用户级 LLM 隔离

每个用户可以维护自己的 OpenAI-compatible LLM 连接，并为自己有执行权限的 LLM 能力选择个人 Profile。

#### G3：运行时可信归属

工具执行任务时必须使用由平台签发、绑定用户/工具/环境的运行上下文，不能依赖工具自由传入的用户 ID。

#### G4：现有配置平滑归属 `admin`

本机和线上已有业务凭证、Credential、LLM Profile/Binding 在不输出明文的前提下迁移为 `admin` 私有数据。

#### G5：保留系统配置与工具独立模式

现有全局普通配置、系统 Secret、工具目录和独立模式保持不变；平台模式不得回退旧个人 Secret。

### 3.2 可衡量成功标准

- 用户 A 和用户 B 在同一 `dev` 环境可分别保存同一 Provider 的不同账号；
- A 发起的任务只记录和使用 A 的 Credential/LLM 版本，B 同理；
- B 未配置时返回稳定错误，不使用 A 或 `admin` 的值；
- A 无法通过列表、详情、修改、测试连接或构造资源 ID 获得 B 的凭证元数据；
- Credential Agent 分别刷新 A、B 的会话，任一用户失败不影响另一用户；
- 当前本机与线上 `admin` 在迁移后继续使用原有有效配置；
- Secret 明文不出现在 API、日志、审计、任务文件、报告、浏览器存储和迁移输出；
- `dev/prod` 继续使用独立数据、Credential、LLM Profile Release 和 KEK；
- 平台模式的所有相关工具完成用户上下文接入后才允许普通用户写入个人凭证；
- 全量自动化、数据库迁移、Nginx、双用户端到端和安全哨兵验证通过。

---

## 4. 范围与边界

### 4.1 本期包含

1. 用户个人凭证中心；
2. Truthy Search Gateway Session 和 Admin Login 私有化；
3. API AutoTest Gateway Session 和 Admin Login 私有化；
4. 用户个人 LLM Profile 和工具能力 Binding；
5. 可信用户上下文签发、持久化运行上下文和内部配置解析；
6. 功能/API 智能体、日志 AI、Truthy Search、API AutoTest 的用户上下文适配；
7. 用户级 Credential Agent 刷新和会话写回；
8. 管理员只读的全员凭证就绪度汇总；
9. 现有本机/线上业务凭证归属 `admin` 的受控迁移；
10. 审计、错误码、发布、回滚和安全验证。

### 4.2 本期不包含

- 用户共享凭证、团队凭证、项目凭证或跨用户授权；
- 管理员代填、代改或查看其他用户的 Secret 明文；
- 个人凭证导入导出；
- MFA、企业 SSO、OIDC、LDAP；
- 外部 Vault、云 KMS 或第三方 Secret 产品；
- 任意新增环境变量或任意凭证字段；
- LLM 协议扩展到非 OpenAI-compatible；
- 用户自定义 Provider Host 白名单；
- 对运行中任务热切换 Credential 或 LLM；
- 重构各工具核心分析、评测和测试生成业务逻辑；
- 移动端页面适配。

### 4.3 首期基数限制

- 每个 `(用户, 环境, 工具, provider_type)` 最多一条激活的个人 Credential；
- 每个用户可以创建多个个人 LLM Profile；
- 每个 `(用户, 环境, LLM 能力 Binding)` 只有一个 active Release；
- 只显示当前代码中真实存在的凭证字段和三个 LLM 能力；
- 用户只能为具备 `tool.execute` 权限的工具配置个人凭证或 LLM Binding。

---

## 5. 用户与权限

### 5.1 普通用户

满足以下条件时可以管理自己的配置：

- 账号状态为 `active`；
- 已登录且 Session 有效；
- 对目标工具具有 `tool.execute`；
- 写操作通过 CSRF 校验。

普通用户可以：

- 查看自己获授权工具的个人凭证状态；
- 保存、替换和验证自己的凭证；
- 创建、修改、归档自己的 LLM Profile；
- 为自己获授权的 LLM 能力选择个人 Profile；
- 查看自己的版本、过期时间、最近检查和稳定错误码。

普通用户不能：

- 查看其他用户是否配置了某个具体 Secret 键；
- 读取任何 Secret 明文；
- 修改系统配置、Host 白名单或工具目录；
- 将自己的凭证共享给其他用户。

### 5.2 平台管理员

平台管理员除管理自己的个人凭证外，可以：

- 维护全局普通配置、系统 Secret、Provider Host 白名单和工具能力目录；
- 查看全员凭证就绪度、状态、过期时间和最近错误；
- 按用户、环境、工具和 Provider 筛选就绪度；
- 查看个人凭证相关脱敏审计。

平台管理员不能通过管理接口读取或导出其他用户的 Secret 明文，也不能在本期代替其他用户修改个人凭证。

### 5.3 工作负载身份

Tool Client Token 仍只代表工具工作负载，不代表登录用户。读取个人凭证必须同时满足：

```text
有效 Tool Client + 有效 Runtime Context + Context 与工具/环境/用户匹配
```

---

## 6. 配置分类

### 6.1 系统级配置

| 分类 | 典型内容 | 管理者 | 运行时共享 |
|---|---|---|---:|
| 启动 Secret | PostgreSQL、KEK、Bootstrap、Tool Client、上下文签名密钥 | 运维 | 是 |
| 平台普通配置 | 会话、安全、审计、LLM Host 白名单 | 平台管理员 | 是 |
| 工具普通配置 | URL、超时、开关、队列、上传限制 | 工具配置管理员 | 是 |
| 系统集成 Secret | 可选数据库持久化连接 | 平台管理员 | 是 |

### 6.2 用户级配置

| 工具/能力 | Provider | 主要字段 |
|---|---|---|
| Truthy Search | `gateway_session` | Access/Refresh Token、User/Device ID、过期信息、请求头 |
| Truthy Search | `admin_login` | Admin 用户名/密码、Admin 请求头 |
| API AutoTest | `gateway_session` | Access/Refresh Token、User/Device ID、过期信息 |
| API AutoTest | `admin_login` | Admin 用户名/密码、Session/Operator 元数据 |
| 三个 LLM 能力 | `openai_compatible` | Base URL、模型、API Key、采样参数和超时 |

每个 ConfigDefinition 必须显式标记 `value_scope=system|user`。运行时不得仅凭字段名、`sensitivity=secret` 或 `group_key` 猜测作用域。

---

## 7. 用户故事

### US-1：首次配置个人凭证

作为测试工程师，我可以在“我的凭证”中选择环境和工具，保存自己的账号或 Token，并看到是否可用。

### US-2：个人 LLM 连接

作为 AI 测试工具用户，我可以创建自己的 LLM Profile，测试连接，并为功能测试、API 测试或日志总结选择该 Profile。

### US-3：未配置时明确失败

作为新用户，当我没有个人凭证时，任务应提示缺少哪一类个人配置，而不是悄悄使用公共账号。

### US-4：自动刷新互不影响

作为用户，我的 Refresh Token 临期时系统只更新我的 Credential；其他用户的版本和状态不变化。

### US-5：管理员迁移连续性

作为现有 `admin`，上线后我无需重新输入当前有效配置即可继续执行本机和线上任务。

### US-6：管理员查看就绪度

作为平台管理员，我能看到哪些用户的哪类 Credential 缺失、临期或异常，但不能看到其明文。

---

## 8. 功能需求

### FR-1：我的凭证中心

1. 新增所有已登录用户可访问的“我的凭证”入口；
2. 支持 `dev/prod` 环境切换；
3. 只展示用户具有 `tool.execute` 的工具；
4. 按 Provider 显示字段、必填状态、配置状态、版本、过期时间和最近检查；
5. Secret 输入保存后立即清空，刷新页面不得回显；
6. 更新要求携带 `expected_version`，冲突返回 `409 VERSION_CONFLICT`；
7. 支持受控验证或连接测试；
8. 不支持任意字段、明文读取、导出和跨用户复制。

### FR-2：用户级所有权

1. 所有个人 Credential 必须保存 `user_id`；
2. 所有个人 LLM Profile 必须保存 `owner_user_id`；
3. 所有个人 LLM Binding 必须保存 `user_id`；
4. 列表与详情接口只按服务端会话中的当前用户过滤；
5. API 不接受客户端指定 `owner_user_id`；
6. 未知或他人资源统一返回 `404`，避免资源枚举；
7. 管理员聚合接口使用独立路由和权限，不复用个人详情接口。

### FR-3：可信运行上下文

1. 平台授权响应生成短时、签名的用户上下文；
2. Nginx 清除浏览器自带的同名 Header，只转发平台签发值；
3. 工具在收到任务/Run 请求后立即把签名上下文兑换成不可猜测的 `runtime_context_id`；
4. Runtime Context 绑定用户、Session、权限版本、工具、环境、资源和过期时间；
5. 工具任务文件只保存 Context ID，不保存签名 Token 或 Secret；
6. 后台任务使用 Tool Client + Context ID 读取个人快照；
7. Session 撤销、用户禁用、权限版本变化、跨工具、跨环境或过期 Context 均拒绝；
8. 已经把 Secret 注入进程内存的运行中任务可以按不可变快照完成，不热切换。

### FR-4：运行配置合并

合并顺序固定为：

```text
全局普通配置
  → 系统级 Secret
  → 当前用户 Personal Credential
  → 当前用户 LLM Profile/Binding
```

规则：

1. 全局 Release 中标记为 `value_scope=user` 的 Secret 必须忽略；
2. 个人凭证只从当前 Runtime Context 对应用户读取；
3. 不读取其他用户、其他环境、其他工具或草稿；
4. 不回退到 `admin`、legacy Credential、旧 LLM Binding 或 env Secret；
5. `include_secrets=false` 只返回当前用户的配置键名和状态，不解密；
6. 快照记录非敏感 Release/Credential/Secret Version 元数据。

### FR-5：个人 Credential 生命周期

1. Credential Agent 扫描所有用户 Credential；
2. 唯一范围为 `(user_id, tool_id, environment_id, provider_type)`；
3. 刷新租约、行锁和 expected_version 均按个人 Credential 生效；
4. 刷新、登录和会话写回只创建该用户的新版本；
5. 某用户进入 `action_required` 不阻塞其他用户；
6. 状态上报和 Session 写回必须校验 Runtime Context 的用户归属；
7. 审计记录用户、工具、Provider、旧/新版本和结果，不记录明文。

### FR-6：个人 LLM

1. 用户可创建多个个人 LLM Profile；
2. Profile 首期只支持 `openai_compatible`；
3. Profile 名称仅在同一用户内唯一；
4. Base URL 必须满足系统 Host 白名单和 SSRF 硬限制；
5. 用户只能为具有 `tool.execute` 的能力配置 Binding；
6. 每个环境分别发布 Profile 和 Binding Release；
7. API Key 保存后不回显，连接测试使用固定最小请求；
8. Runtime Snapshot 包含个人 Profile/Binding Release 和 Secret Version；
9. 个人 Profile 不能被其他用户选择或引用；
10. 现有公共 Profile 和 Binding 迁移为 `admin` 的个人配置。

### FR-7：管理员就绪度

管理员页面/API 可以展示：

- 用户名和状态；
- 环境、工具和 Provider；
- Credential 状态和版本；
- 已配置字段数/必填字段数；
- 过期时间、最近检查和稳定错误码；
- LLM Profile/Binding 是否就绪。

不得展示 Secret 值、长度、前后缀、哈希、密文或可反推指纹。

### FR-8：现有数据迁移

1. 本机和线上数据库分别识别 `username_normalized='admin'`；
2. 找不到或找到多个管理员时迁移失败关闭；
3. 当前个人类工具 Secret/Credential 复制为 `admin` Personal Credential；
4. 当前 LLM Profile 和 Binding 复制/归属为 `admin`；
5. 真实 Secret 通过应用命令在内存中解密并重新加密，不进入 Alembic、命令参数或输出；
6. 原 legacy 数据保留为只读回滚资源；
7. 导入幂等，不覆盖管理员迁移后自行更新的数据；
8. 导入只报告键名、来源、状态和版本，不输出值或指纹；
9. 普通用户数据写入必须在所有平台模式工具完成新 Runtime Context 接入后开启。

### FR-9：错误与提示

新增稳定错误：

| 错误码 | HTTP | 用户提示 |
|---|---:|---|
| `PERSONAL_CREDENTIAL_NOT_CONFIGURED` | 409 | 请先配置当前工具的个人凭证 |
| `PERSONAL_LLM_NOT_CONFIGURED` | 409 | 请先配置并发布个人 LLM 连接 |
| `RUNTIME_CONTEXT_REQUIRED` | 403 | 当前请求缺少可信用户上下文 |
| `RUNTIME_CONTEXT_INVALID` | 403 | 用户上下文无效或与工具不匹配 |
| `RUNTIME_CONTEXT_EXPIRED` | 401 | 用户上下文已过期，请重新提交 |
| `RUNTIME_SNAPSHOT_INVALID` | 409 | 任务配置快照无效，请重新提交任务 |
| `CREDENTIAL_SCOPE_MISMATCH` | 403 | 凭证不属于当前用户或工具 |
| `VERSION_CONFLICT` | 409 | 配置已更新，请刷新后重试 |
| `LLM_PROFILE_IN_USE` | 409 | 该连接仍被能力绑定，请先解绑 |
| `LEGACY_CREDENTIAL_WRITE_DISABLED` | 410 | 旧凭证写入接口已停用，请升级工具 |

错误响应不得包含 Secret、内部 URL、SQL、堆栈或其他用户资源信息。

---

## 9. 页面与交互

### 9.1 导航

- 账户区域新增“我的凭证”和“我的 LLM”；
- `/settings/config`、`/settings/secrets` 继续表示系统/全局配置；
- `/settings/credentials` 调整为管理员凭证就绪度；
- 现有 `/settings/llm` 在迁移期重定向到“我的 LLM”，避免旧书签失效。

### 9.2 我的凭证

页面按环境和工具分组，每个 Provider 卡片包含：

- 状态、版本和过期时间；
- 已配置/缺失字段；
- Secret 输入和非敏感说明；
- 保存、验证、刷新状态；
- “仅你自己的任务使用”提示。

### 9.3 我的 LLM

页面包含：

- 个人 Profile 列表；
- Profile Base URL、模型、参数和 API Key 状态；
- 三个真实能力的个人 Binding；
- 草稿、校验、发布、回滚和连接测试；
- 当前环境、版本和“下一任务/下一请求生效”说明。

### 9.4 状态与无障碍

- 加载、空、缺失、临期、失败、无权限和冲突状态必须明确；
- 状态不能只依赖颜色；
- 所有表单和对话框支持键盘操作及焦点恢复；
- Secret 输入不得进入 localStorage/sessionStorage；
- 只验收 1280px 及以上桌面 Web。

---

## 10. 审计与数据保留

必须记录：

```text
personal.credential.create
personal.credential.replace
personal.credential.validate
personal.credential.refresh
personal.credential.writeback
personal.llm.profile.create
personal.llm.profile.update
personal.llm.profile.archive
personal.llm.binding.publish
runtime.context.create
runtime.context.reject
runtime.config.loaded
personal.migration.apply
```

允许记录用户 ID、环境、工具、Provider、资源 ID、版本、状态、耗时和稳定错误码。

禁止记录密码、Token、API Key、Authorization Header、签名用户上下文、Runtime Context ID 全值、Provider 原始响应正文和业务输入。

Runtime Context 按短期安全记录清理；Credential、Release、Secret Version 和审计沿用现有保留与不可变规则。

---

## 11. 非功能与安全要求

### 11.1 安全

- 用户上下文签名使用独立于 KEK 的至少 256 位随机密钥；
- 签名 Token 有效期不超过 5 分钟；
- Runtime Context 默认有效期覆盖队列和单任务最大时长，最长不超过 24 小时；
- Context ID 使用至少 256 位随机强度；
- 所有内部个人配置响应设置 `Cache-Control: no-store`；
- 个人资源查询必须从当前会话推导用户，不接受自由 owner 参数；
- Nginx 必须覆盖客户端伪造的身份和用户上下文 Header；
- 用户禁用、Session 撤销和权限版本改变应阻止尚未加载 Secret 的任务；
- Secret 加密、KEK 轮换和 `dev/prod` 隔离规则保持不变。

### 11.2 可用性

- 平台或 Secret 服务不可用时，新个人任务失败关闭；
- 日志分析的规则报告仍可返回，个人 LLM 总结降级失败；
- 单个用户 Credential 失败不影响平台及其他用户；
- 已运行任务使用已锁定快照，不因用户后续轮换产生漂移。

### 11.3 性能

- 个人凭证列表 P95 小于 500ms，不含外部连接测试；
- Runtime Context 兑换和运行快照解析合计 P95 小于 300ms，不含外部 Provider；
- 列表查询必须使用用户/环境/工具组合索引；
- Credential Agent 使用 `FOR UPDATE SKIP LOCKED`，不得串行阻塞全部用户。

### 11.4 兼容性

- 工具独立模式继续读取各自 env/key file；
- 平台模式不读取个人 legacy Secret；
- 原全局配置与 Secret API 继续服务系统配置；
- legacy Credential/Binding 在个人数据迁移完成后只读保留，不参与新 Runtime Resolver。

---

## 12. 发布与回滚要求

### 12.1 上线顺序

1. 备份数据库、KEK、任务和报告；
2. 生成并挂载 dev/prod 独立用户上下文签名密钥；
3. 执行扩展型 Schema 迁移；
4. 发布支持个人数据但保持写入口关闭的平台 API；
5. 发布 Nginx 和全部平台模式工具的 Runtime Context 适配；
6. 执行脱敏 dry-run 和 `admin` 数据导入；
7. 验证 `admin` 任务连续性；
8. 开启个人凭证写入口；
9. 使用第二个用户完成双用户隔离验收；
10. 本机通过后按同样门禁发布线上。

### 12.2 回滚原则

- legacy 全局数据在首期保留且不被个人写入修改；
- 普通用户写入口开启前，可以回滚工具和平台镜像；
- 普通用户已写入个人数据后，禁止回滚到会忽略用户作用域的旧 Runtime Resolver；
- 此时只能回滚到支持 Personal Credential 表但关闭新功能的兼容版本；
- 不默认执行 Alembic downgrade，不删除个人加密数据；
- 回滚不得导出明文或恢复平台/env 双写。

---

## 13. 验收场景

| ID | 场景 | 预期结果 |
|---|---|---|
| AC-1 | A、B 分别保存 Truthy Search Token | 两条 Personal Credential，版本和 Secret 完全独立 |
| AC-2 | B 未配置并创建任务 | 返回 `PERSONAL_CREDENTIAL_NOT_CONFIGURED`，无 admin fallback |
| AC-3 | A 构造 B 的 Credential ID | 返回 404/403，响应不泄露 B 的元数据 |
| AC-4 | A、B 使用不同 LLM Profile | 两个任务记录不同 Profile/Binding/Secret Version |
| AC-5 | 伪造 `X-Platform-User-Context` | Nginx 覆盖或平台拒绝签名 |
| AC-6 | A 的 Context 请求 B/其他工具资源 | 返回 `RUNTIME_CONTEXT_INVALID` 或 `CREDENTIAL_SCOPE_MISMATCH` |
| AC-7 | A 登出后排队任务尚未加载 Secret | Context 校验失败，任务不执行 LLM/下游请求 |
| AC-8 | A 任务已经启动后轮换 API Key | 当前任务使用旧快照，新任务使用新版本 |
| AC-9 | Credential Agent 同时扫描 A、B | 分别刷新，版本无交叉更新 |
| AC-10 | `include_secrets=false` | 不加载 KEK，不返回明文，只返回当前用户配置状态 |
| AC-11 | 迁移本机/线上已有配置 | 原值归 admin，其他用户为空，迁移日志无敏感信息 |
| AC-12 | dev 用户配置完成但 prod 未配置 | prod 仍显示未配置，不复制 dev Secret |
| AC-13 | 管理员查看就绪度 | 可见状态汇总，不可见值、长度、前后缀或哈希 |
| AC-14 | 回滚兼容版本 | legacy admin 数据可用，个人表保留且不会被旧全局 Resolver 混读 |
| AC-15 | 安全哨兵扫描 | API、日志、审计、任务、报告和浏览器存储均无哨兵明文 |

---

## 14. 风险与缓解

| 风险 | 缓解措施 |
|---|---|
| 旧 Runtime Resolver 忽略用户字段并混读 | 个人 Credential 使用独立表和独立 Secret owner_type；旧 Resolver 无法查询到 |
| 工具自由伪造 user_id | 使用平台签名用户上下文兑换 Runtime Context，不信任裸 user_id |
| 异步任务 Context 过期 | Context TTL 覆盖队列/任务上限；恢复操作重新签发 Context |
| 用户 Profile 被跨用户绑定 | 发布和解析时双重校验 `profile.owner_user_id` |
| legacy 与 personal 双写 | legacy 数据只读；新写入只进 Personal Credential/Binding |
| 管理员迁移输出 Secret | 应用命令只输出键名、状态和版本；安全哨兵扫描命令输出 |
| Credential Agent 用户数量增长 | 组合索引、SKIP LOCKED、短事务和单 Credential 故障隔离 |
| 回滚后泄露个人数据 | 普通用户写入后只允许回滚到理解 Personal 表的兼容版本 |

---

## 15. 已锁定产品决策

1. 普通非敏感配置继续全局统一管理；
2. 业务账号、密码、Token 和完整 LLM 连接归登录用户个人所有；
3. 现有本机和线上业务凭证全部归各自环境的 `admin`；
4. 其他用户不继承、不共享、不回退 `admin` 配置；
5. 首期不做团队/项目共享凭证；
6. 管理员只能查看他人就绪度，不能读取或代改明文；
7. 工具工作负载身份与登录用户身份必须同时校验；
8. 使用兼容隔离层保留安全回滚能力，不让旧 Resolver 看到个人 Credential；
9. 个人 LLM 继续复用现有 Release、Secret 和不可变快照原则；
10. `dev/prod` 环境、Credential、Release、Secret 和密钥继续完全隔离。
