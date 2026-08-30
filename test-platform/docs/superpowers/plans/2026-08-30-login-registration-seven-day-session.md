# 登录注册与 7 天会话改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有固定角色、项目授权和服务端 Session 架构的前提下，正式开放安全的测试人员自助注册，将所有新设置密码统一为 6–18 个 Unicode code point，并让新登录或注册产生的浏览器会话固定有效 168 小时。

**Architecture:** 继续使用 FastAPI + SQLAlchemy + PostgreSQL 的服务端 Session Cookie 方案。注册请求先经过专用纯 ASGI middleware，在现有 `login_throttles` 表的隔离注册命名空间中完成模式检查、全量提交计数、来源限流与全局熔断，再进入既有 Pydantic 校验和注册 handler；前端在现有 `AuthProvider` 中统一管理注册模式、认证恢复和带认证代次的 `AUTH_REQUIRED` 失效事件，不引入 JWT、Refresh Token、新状态库或新的前端目录层级。

**Tech Stack:** Python 3、FastAPI、Pydantic v2、SQLAlchemy 2、PostgreSQL、Argon2id、React 19.2、TypeScript、React Router 7、Vitest、Testing Library、Docker Compose、Nginx、Playwright CLI。

**Spec:** `docs/PRD-登录注册与7天会话-V1.0.md`；产品于 2026-08-30 确认：6–18 位只约束新设置密码，登录继续兼容存量长密码。

## Global Constraints

- 所有实现以当前工作树为基线。当前 `backend/app/services/auth.py`、`backend/tests/test_phase2.py`、`docker-compose.yml`、`frontend/src/App.tsx`、`frontend/src/App.test.tsx`、`frontend/src/api/client.ts` 等文件已有用户改动；执行前必须逐文件检查 diff，禁止覆盖、回退或把无关改动混入提交。
- 不引入 JWT、Refresh Token、“记住我”、邮箱/手机号/验证码、邀请码页面、审批流或新角色模型。
- 新注册用户固定为 `status="active"`、`platform_role="tester"`，不创建项目成员关系、旧多角色关联或额外工具授权。
- 密码不得 trim；长度按 Unicode code point 计算。登录请求仍允许 1–256 位输入并直接执行 Argon2id verify，不能调用新密码策略。
- 新 Session 的 idle 与 absolute 均为 168 小时；absolute 在创建时固化，任何 touch 都不得越过 absolute。存量 Session 不批量延长。
- 注册模式只允许 `open`、`disabled`、`invite`。本期 `invite` 与 `disabled` 一样失败关闭；状态查询失败或返回未知值时，前端也必须失败关闭。
- 注册提交的密码、完整请求体、原始 Session Token、CSRF Token、原始限流 key 不得进入日志、审计、浏览器持久化存储或错误响应。
- 登录失败限流保持原逻辑；注册限流复用 `login_throttles` 的物理表，但使用 `reg_global`、`reg_ip`、`reg_username`、`reg_device` 独立 key_type 与不同哈希输入，不与登录 key 共用计数。注册路径使用原子行锁，不能据此宣称既有登录限流也获得相同并发保证。
- UI 沿用现有桌面端登录双栏布局、组件和 CSS；不新建设计系统，不做营销化重设计。支持 1280px 及以上桌面宽度、键盘操作、可见焦点、`role="alert"` 和 `prefers-reduced-motion`。
- 只修改本文列出的文件。发现必须扩大架构、引入外部告警服务或改变生产 HTTPS 方案时，停止该扩展并单独提交决策说明。

---

## 1. 需求落地摘要

### 1.1 成功标准

| 目标 | 可验证结果 |
|---|---|
| 自助注册 | `registration_mode=open` 时，未登录用户可从 `/login` 进入 `/register`，合法提交返回 201、建立 Cookie Session 并进入工作台 |
| 失败关闭 | `disabled`、`invite`、状态接口异常或未知模式时，前端不开放注册；注册 API 返回 503 且不写用户 |
| 固定权限 | 新注册用户只有 `tester`，状态为 `active`，项目数和额外工具授权数均为 0 |
| 密码统一 | 注册、setup、改密、管理员建号、管理员重置均接受 6/18 位并拒绝 5/19 位；登录仍接受存量 19 位以上密码 |
| 7 天会话 | 新 Session 在 T+6 天 23 小时有效，T+168 小时失效；Cookie `Max-Age=604800`；触摸不延长 absolute |
| 防滥用 | IP、规范化用户名及可用的可信设备信号每 15 分钟允许 5 次，第 6 次 429；全局 100 次后熔断，后续 503，15 分钟后恢复 |
| 全提交计数 | 成功、重复用户名、字段错误、未知字段、畸形 JSON 都进入各维度计数，不能通过制造 422 绕过；已被来源锁拒绝的 429 仍计 global 但不续来源锁，已被 global 熔断拒绝的 503 只审计且不续熔断 |
| 失效体验 | 任意受保护请求收到 `401 AUTH_REQUIRED` 后清空内存认证态，安全保留 `next`，登录页只提示一次会话已过期 |
| 数据安全 | 响应、日志、审计、限流表和浏览器 Storage 均不出现密码、密码哈希或原始认证 Token |

### 1.2 明确不做

- 不改变 `User`、`ProjectMembership`、`UserToolGrant` 的授权语义。
- 不把确认密码发送给后端。
- 不对存量密码或存量 Session 做批处理迁移。
- 不在常规 smoke 中向生产数据库永久创建测试账号。
- 不把浏览器可任意伪造的 Header 当作可信设备信号。

---

## 2. 当前基线与差距

| 范围 | 当前实现 | 本次差距 |
|---|---|---|
| 注册 API | `backend/app/api/auth.py:160-199` 已能创建 active tester 和 Session | 无模式状态接口、重复用户名泄露明确语义、无全量限流/熔断、空白显示名称可落库 |
| 密码 | `backend/app/core/security.py:36-50` 为 12–256；Schema 多处写死 12–256 | 需共享 6–18 规则；`verify_password()` 与 `LoginRequest` 必须保持长密码兼容 |
| Session | `Settings` 默认 idle=8h、absolute=24h；Cookie 使用 absolute | 默认值及部署配置需改为 168/168；现有 `min()` 触摸上限可以复用 |
| 注册前端 | `/register` 路由和基础表单已存在 | 缺确认密码、模式 fail-closed、Unicode 长度、失败清密和细化错误状态 |
| 会话失效 | `apiJson()` 只抛 `ApiError`；`AuthProvider` 只在启动 `/auth/me` 处理 401 | 任意业务请求 401 无法统一清认证态和展示一次性提示 |
| 注册防滥用 | 已有 `LoginThrottle` 持久化桶，当前登录更新为查询后 Python 自增 | 需要隔离注册 key namespace、前置计数、注册专用原子并发更新和全局熔断；不新增表 |
| 部署文档 | `.env`/Compose/README 仍写 8h/24h，生产示例为 HTTP + `Secure=false` | 需同步 168h、注册配置、可信网关 IP 覆盖和 7 天 Cookie 正式风险记录 |

---

## 3. 总体技术设计

### 3.1 请求与状态流

```text
匿名浏览器
  ├─ GET /api/v1/auth/registration-status
  │    └─ 返回 {"mode":"open|disabled|invite"}
  │         └─ 前端仅对明确的 open 展示/启用注册
  │
  └─ POST /api/v1/auth/register
       └─ RequestIdMiddleware（外层，写 request_id）
            └─ RegistrationAttemptMiddleware
                 ├─ 限制并原样缓存请求体
                 ├─ 仅提取 username；绝不读取或记录 password 值
                 ├─ 独立事务在 reg_* key namespace 原子统计 global/ip/username
                 ├─ disabled/invite → 503
                 ├─ 全局熔断 → 503
                 ├─ 来源锁定 → 429
                 └─ 放行并原样回放 body
                      └─ FastAPI/Pydantic 422 或 register handler
                           ├─ 重复用户名 → 409 安全语义
                           └─ 成功 → active tester + 168h Session + 201
```

### 3.2 为什么使用纯 ASGI middleware

`RegisterRequest` 校验失败或出现未知字段时，handler 不会执行。只在 `register()` 或普通业务依赖中计数无法可靠覆盖所有 422；读取请求体的 `BaseHTTPMiddleware` 还可能改变下游 receive 行为。专用纯 ASGI middleware 在路由校验之前完成计数，并把原始字节逐字回放，能够同时满足：

- 任何业务成功/失败/422 payload 均计数；命中已生效来源锁时只继续增加 global 并审计，不修改来源桶或续锁；命中已生效 global 熔断时只审计，不修改桶或续熔断；
- 未知字段仍由 `extra="forbid"` 返回 422；
- 畸形 JSON 仍使用现有统一验证错误；
- 密码不进入中间件日志或持久化数据；
- 第 6 次或熔断后的请求可在进入业务事务前立即拒绝。

middleware 只匹配 `scope["type"] == "http"`、`method == "POST"`、`path == "/api/v1/auth/register"`，其他请求零行为变化。请求体最大缓存固定为 64 KiB；超过上限时继续 drain 剩余 `http.request` 消息直至 `more_body=False`，只记 IP/global 维度，不解析 username，也不把截断 body 交给下游；在没有更高优先级的模式关闭、global 熔断或来源锁定时返回 413 `PAYLOAD_TOO_LARGE`。

### 3.3 Middleware 顺序

Starlette middleware 必须保持：

```python
app.add_middleware(RegistrationAttemptMiddleware)
app.add_middleware(RequestIdMiddleware)
```

按当前 Starlette 的包装顺序，后添加的 `RequestIdMiddleware` 位于外层，因此 413、422、429、503 都能得到同一 `request_id` 与 `X-Request-ID`。自动化测试必须锁定该顺序，不能只依赖人工理解。

`RegistrationAttemptMiddleware.__init__(app)` 保存下游 ASGI app；`__call__(scope, receive, send)` 对计数数据库会话使用 `try/except/finally`，任何数据库异常或唯一键竞争重试耗尽都 rollback、close 并显式返回 503。middleware 位于 FastAPI 异常处理器之外，不能依赖全局 `SQLAlchemyError` handler 替它清理资源。

---

## 4. 接口设计

### 4.1 公开注册状态

```http
GET /api/v1/auth/registration-status
```

成功固定返回 200：

```json
{"mode":"open"}
```

响应 Schema：

```python
class RegistrationStatusResponse(BaseModel):
    """公开注册开关；不返回阈值、计数或部署内部信息。"""

    mode: Literal["open", "disabled", "invite"]
```

该接口无需登录、无需 CSRF，响应带 `Cache-Control: no-store`，不返回 `available` 等重复推导字段。前端只有在 `mode === "open"` 时开放注册；`disabled`、`invite`、网络错误、503、缺字段或未知字符串一律视为关闭。

### 4.2 注册

```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "username": "new.tester",
  "display_name": "新测试人员",
  "password": "123456"
}
```

成功：201 + 现有 `MeResponse` + `tp_session`/`tp_csrf` Cookie。注册与登录一样是建立首个 Session 的匿名 JSON 端点，没有可供校验的既有 CSRF Token，因此不新增 `require_csrf`；前端仍使用同源 fetch，项目不开放跨域 CORS。成功签发 `tp_csrf` 后，所有既有已认证写接口继续执行双提交 CSRF 校验，不能因开放注册而放宽。

| 场景 | HTTP | `code` | 固定外部消息 |
|---|---:|---|---|
| 字段/未知字段/畸形 JSON | 422 | `VALIDATION_ERROR` | 请求参数不正确 |
| body 超过 64 KiB | 413 | `PAYLOAD_TOO_LARGE` | 请求内容过大 |
| 规范化用户名不可用 | 409 | `REGISTRATION_UNAVAILABLE` | 暂时无法创建账号，请更换信息或稍后重试 |
| 来源限流 | 429 | `REGISTRATION_RATE_LIMITED` | 操作过于频繁，请稍后重试 |
| disabled/invite/熔断/计数存储不可用 | 503 | `REGISTRATION_UNAVAILABLE` | 暂未开放注册，请稍后重试 |

外部响应不返回用户名是否存在、当前计数、阈值、锁定结束时间或内部失败原因。内部审计通过稳定 action/error_code 区分。

### 4.3 登录与会话接口

- `POST /api/v1/auth/login` 请求/响应形状不变；`LoginRequest.password` 保持 1–256。
- 新登录、注册和 setup 创建的 Cookie `Max-Age=604800`。
- `GET /api/v1/auth/me` 继续返回 `session_expires_at`，不新增 Token 字段。
- 到期、撤销、停用等统一由受保护接口返回 `401 AUTH_REQUIRED`。
- logout、用户撤销 Session、管理员撤销/停用、改密与重置密码的现有提前失效语义保持。

---

## 5. 密码策略设计

### 5.1 服务端共享规则

在 `backend/app/core/security.py` 定义唯一常量和最终保护：

```python
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 18


def validate_new_password(password: str) -> str:
    """校验新设置密码的 Unicode code point 数量，不修改原值。"""

    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ValueError("密码长度必须为 6 到 18 个字符")
    return password


def hash_password(password: str) -> str:
    """仅为符合新密码策略的原始字符串生成 Argon2id 哈希。"""

    return PASSWORD_HASHER.hash(validate_new_password(password))
```

Python `len(str)` 与 Pydantic v2 字符串长度按 Unicode code point 计算。密码不调用 `strip()`。

`verify_password()` 不调用 `validate_new_password()`。`LoginRequest.password` 和 `ChangePasswordRequest.current_password` 保持 1–256，以便验证旧账号的长密码。

现有模块级假密码必须改为合法新长度，否则导入 `auth.py` 时就会失败：

```python
DUMMY_PASSWORD_HASH = hash_password("dummy-password")
```

### 5.2 需要执行 6–18 的入口

| 入口 | 后端请求字段 | 前端位置 |
|---|---|---|
| 自助注册 | `RegisterRequest.password` | `RegisterPage` |
| 首次 setup | `SetupRequest.password` | `SetupPage` |
| 用户改密/强制首次改密 | `ChangePasswordRequest.new_password` | `ChangePasswordPage` |
| 管理员创建用户 | `UserCreateRequest.password` | `FixedUsersPage` 与兼容 `UsersPage` |
| 管理员重置 | `ResetPasswordRequest.new_password` | `UsersPage` 重置对话框 |

### 5.3 前端一致计数

```ts
const PASSWORD_MIN_CODE_POINTS = 6;
const PASSWORD_MAX_CODE_POINTS = 18;

function codePointLength(value: string): number {
  return Array.from(value).length;
}

function validateNewPassword(value: string): string {
  const length = codePointLength(value);
  return length < PASSWORD_MIN_CODE_POINTS || length > PASSWORD_MAX_CODE_POINTS
    ? "密码长度必须为 6–18 位"
    : "";
}
```

新密码输入不能使用 HTML `maxLength={18}` 作为权威限制，因为浏览器按 UTF-16 code unit 计数，emoji 等字符会与服务端不一致。表单提交时调用共享函数，并通过 `aria-invalid`/`aria-describedby` 展示字段错误。登录页不调用该函数。

---

## 6. 注册防滥用数据与并发设计

### 6.1 复用现有持久化表并隔离命名空间

不新增数据库表。复用现有 `login_throttles` 的物理结构：

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | 内部主键 |
| `key_type` | String(16) | NOT NULL | 注册固定为 `reg_global` / `reg_ip` / `reg_username` / `reg_device` |
| `key_hash` | String(64) | NOT NULL | `token_hash(f"{kind}:{value}")` |
| `window_started_at` | timezone datetime | NOT NULL | 当前计数窗口起点 |
| `attempt_count` | Integer | NOT NULL, default 0 | 当前窗口提交数 |
| `blocked_until` | timezone datetime | nullable | 来源锁定或全局熔断结束时间 |

沿用唯一约束 `uq_login_throttle_key(key_type, key_hash)`。注册哈希输入也带 `reg_*` kind，例如 `token_hash("reg_username:" + normalized_username)`，所以现有 `clear_login_failures()` 生成的 `username`/`ip` 哈希不会删除注册桶。

选择复用的理由：当前表字段、唯一约束和 `String(16)` 均能容纳四个 `reg_*` key；PRD 不要求独立表；可以避免新增 migration 被当前 0019 expand → 0020 contract 发布门禁阻断。注册与登录在逻辑上仍完全分离：不修改现有登录计数算法，不抽取会改变登录行为的共享写函数，并新增“登录成功清理不影响注册桶”的回归测试。既有固定角色开发设计中未落地的独立表描述，由本计划以当前仓库和发布约束为准修正。

### 6.2 配置

```python
from pydantic import Field, model_validator

registration_mode: Literal["open", "disabled", "invite"] = "open"
registration_rate_limit: int = Field(default=5, ge=1, le=5)
registration_rate_window_minutes: int = Field(default=15, ge=15)
registration_lock_minutes: int = Field(default=15, ge=15)
registration_global_limit: int = Field(default=100, ge=1, le=100)
registration_global_window_minutes: int = Field(default=15, ge=15)
registration_global_lock_minutes: int = Field(default=15, ge=15)
```

所有字段都放入 `Settings`，环境变量由 Pydantic Settings 的大小写不敏感映射读取。再用 `model_validator(mode="after")` 保证来源 lock ≥ rate window、global lock ≥ global window，避免锁先结束但旧计数窗口仍残留。阈值只能保持或收紧，不能通过 0、负数、缩短窗口/锁定时间或超大尝试数关闭保护；未知 mode 使 Settings 启动校验失败，绝不能回退为 open。

当前 Nginx 没有可信设备信号来源，因此本期 middleware 固定传 `device_signal=None`，只启用 global + IP + username。网关明确清除客户端 `X-Registration-Device`，后端不提供启用该 Header 的配置；未来只有完成可信注入设计后才启用 `reg_device`。

### 6.3 计数键

固定锁顺序，避免多维事务死锁：

```text
global → ip → username → device
```

- global 使用固定值 `register` 后哈希；
- Nginx 的平台 API location 必须用 `proxy_set_header X-Forwarded-For $remote_addr` 覆盖而非追加浏览器输入，固定写入 `X-Test-Platform-Gateway: 1`，并清空 `X-Registration-Device`；后端仅在 `X-Test-Platform-Gateway` 精确为 `1` 时读取唯一 XFF 值，否则使用 peer address。`platform-api` 不发布宿主机端口，因此该标记只存在于内部网关边界；两种地址都不可得时跳过 IP，但仍计 global；
- username 仅在 JSON 顶层为对象且字段为字符串时执行 `normalize_username()` 后哈希；解析失败时跳过 username，但仍计 global/IP；
- device 本期固定跳过；
- 表内不保存以上任一原值。

部署验收必须通过网关发送伪造 `X-Forwarded-For` 与 `X-Registration-Device`，确认后端看到的是网关覆盖后的真实远端 IP且 device 未参与。`platform-api` 不得直接发布宿主机端口。

### 6.4 原子窗口算法

服务接口：

```python
@dataclass(frozen=True)
class RegistrationRateDecision:
    blocked_kind: Literal["rate", "circuit"] | None = None
    circuit_opened: bool = False


def evaluate_registration_attempt(
    database: Session,
    *,
    username: str | None,
    ip_address: str | None,
    device_signal: str | None,
    settings: Settings,
) -> RegistrationRateDecision:
    """在传入事务中查询、修改并 flush；不 commit、rollback 或 close。"""
```

事务所有权固定如下，不能由实现者自行调整：

- `evaluate_registration_attempt()` 只操作调用方传入的 Session，并在返回前 `flush()`，不负责 `commit()`、`rollback()` 或 `close()`；
- middleware 对所有注册 POST（包括 `disabled` / `invite`）创建专用计数 Session，执行 `factory() → evaluate() → commit()`；放行、来源拒绝、熔断拒绝和模式关闭结果均先保存安全计数再响应；
- `disabled` / `invite` 提交计数后始终对外返回 503，不进入 Pydantic 或 handler，不写 User/Session/项目/授权等业务数据；即使同时达到来源阈值，也不把 429 暴露为当前模式的响应，但全局熔断首次打开仍写单次内部告警；
- 任一异常由 middleware `rollback()`；首次唯一键竞争还必须 `close()` 当前 Session、用 factory 新建 Session 后完整重试一次；第二次失败返回 503；
- 注册 handler 的用户/Session 业务事务继续由下游 `get_db()` 创建，绝不复用或接收 middleware 的计数 Session。

算法按以下不可变顺序执行：

1. 按 `reg_global=0 → reg_ip=1 → reg_username=2 → reg_device=3` 的显式 rank 生成 keys，禁止按 key_hash 或自然字符串顺序替代；
2. PostgreSQL 对已存在的匹配行用同一 rank 的 `CASE` 排序后执行带 `FOR UPDATE` 的 SELECT；不存在的行无法预先锁定，只能按 rank 插入并依靠唯一约束检测竞争，竞争方按步骤 9 回滚、重建 Session、重新读取后重试；
3. 若 global `blocked_until > now`，立即返回 `circuit`；该拒绝请求只写安全审计，不修改任何 throttle 桶，也不延长阻断时间；
4. 对已过窗口且不在有效阻断中的行重置 `window_started_at=now`、`attempt_count=0`、`blocked_until=None`；配置校验已保证 lock 不短于 window；
5. global `attempt_count += 1`。达到 global limit 时写 `blocked_until=now+global_lock` 并设置 `circuit_opened=True`，本次阈值请求仍继续判断来源并可放行；下一请求命中步骤 3；
6. 若任一来源 `blocked_until > now`，返回 `blocked_kind="rate"`，不增加或延长该来源桶，但保留步骤 5 的 global 计数；因此 429 等失败提交仍进入全局熔断统计；
7. 对未阻断来源的 `attempt_count += 1`；达到来源 limit 时写 `blocked_until=now+lock`，本次阈值请求仍放行，第 6 个请求命中步骤 6；
8. 返回决策；允许 `blocked_kind="rate"` 与 `circuit_opened=True` 同时存在，以便第 100 次恰好来自已锁来源时响应 429、同时只告警一次全局熔断；`circuit_opened=True` 只表示本次提交打开熔断，不等于 `blocked_kind="circuit"`，第 101 次起才返回熔断 503；
9. 首次插入遇到唯一键竞争时，middleware 对当前 Session 执行 rollback 并 close，通过注入的 factory 创建新 Session后最多重试一次；绝不复用 failed transaction Session，第二次仍失败则失败关闭为 503；
10. 计数事务先于业务事务提交，因此后续 422、409 或用户创建回滚不会抹掉尝试记录。

SQLite 单元测试验证窗口、命名空间隔离与错误语义；PostgreSQL 隔离环境用并发测试验证唯一键竞争和行锁不会丢增量。不能用 SQLite 的串行通过结果宣称生产行锁正确。

### 6.5 安全事件与告警

| 内部 action | outcome | error_code | 触发点 |
|---|---|---|---|
| `auth.register` | `success` | null | 用户与 Session 成功提交 |
| `auth.register` | `failed` | `REGISTRATION_VALIDATION_FAILED` | 一般 Pydantic/JSON 422 |
| `auth.register` | `failed` | `REGISTRATION_UNKNOWN_FIELDS` | `extra_forbidden` 422 |
| `auth.register` | `failed` | `REGISTRATION_PAYLOAD_TOO_LARGE` | middleware 拒绝超过 64 KiB 的 body |
| `auth.register` | `denied` | `REGISTRATION_UNAVAILABLE` | 重复规范化用户名 |
| `auth.register` | `denied` | `REGISTRATION_MODE_DISABLED` | disabled |
| `auth.register` | `denied` | `REGISTRATION_INVITE_UNAVAILABLE` | invite |
| `auth.register` | `denied` | `REGISTRATION_RATE_LIMITED` | 来源锁定 |
| `auth.register.circuit` | `denied` | `REGISTRATION_CIRCUIT_OPEN` | global 从关闭转为打开，恰好一次告警 |
| `auth.register.circuit` | `denied` | `REGISTRATION_UNAVAILABLE` | 熔断期间的请求 |

审计 metadata 只允许布尔分类和 key 类型列表，例如 `{"dimensions":["global","ip","username"]}`；不得放原始 username、IP、device、请求体、密码或阈值。现有 `AuditLog.ip_address` 仍按平台统一审计规则记录连接来源。

`RequestValidationError` handler 只有在 `request.method == "POST"` 且 `request.url.path == "/api/v1/auth/register"` 时，才使用独立 `SessionLocal()` 写注册失败审计；其他 API 的 422 保持现状。分类只读取 `exc.errors()` 中的固定 `type` 名，不能序列化 `input`、`ctx`、`exc.body` 或完整 errors：`json_invalid` 归为 malformed、任一 `extra_forbidden` 归为 unknown fields，其余归为 validation。审计提交失败时 rollback/close 并写脱敏错误日志，不递归调用同一异常处理器，也不把原本 422 改成 500。

熔断从关闭转为打开时，同时写一条不含敏感值的 `logger.warning`。本期不引入新告警供应商；生产运维必须把该 action/日志关键字接入现有日志告警规则，且测试保证同一熔断窗口只发一次“打开”事件。

---

## 7. 前端状态与交互设计

### 7.1 AuthContext 扩展

```ts
type RegistrationMode = "open" | "disabled" | "invite";

interface RegistrationStatus {
  mode: RegistrationMode;
}

interface AuthContextValue {
  auth: AuthState | null;
  loading: boolean;
  registrationMode: RegistrationMode;
  registrationModeLoading: boolean;
  reload: () => Promise<void>;
  setAuth: (value: AuthState | null) => void;
}
```

- `registrationMode` 初始固定为 `disabled`；
- 独立请求 `/auth/registration-status`，不会阻塞已登录工作台；
- 只有响应严格匹配 `open|disabled|invite` 才更新，其他情况保持 `disabled`；
- 查询 effect 使用 `cancelled` 标记并在 cleanup 置 true；组件卸载后的成功/失败回调不得更新状态，旧响应不得覆盖后续挂载状态；
- `/login` 在 loading 和非 open 时均不渲染注册链接；
- `/register` loading 时显示现有 `LoadingPage`，非 open 时在 `LoginLayout` 中显示“暂未开放注册”和“返回登录”。

### 7.2 注册表单

```ts
interface RegisterValues {
  username: string;
  display_name: string;
  password: string;
  confirm_password: string;
}
```

提交 body 必须显式构造，不能展开整个 form：

```ts
const payload = {
  username: values.username,
  display_name: values.display_name,
  password: values.password,
};
```

交互顺序：

1. 校验显示名称 trim 后非空；
2. 使用 `Array.from()` 校验密码 6–18；
3. 严格比较密码与确认密码原值；
4. 任一客户端校验失败，显示字段错误、清空两个密码字段、不发请求；
5. 请求中按钮文案“正在创建…”，按钮 disabled；
6. 201 后 `setAuth(result)` 并 `navigate("/", {replace:true})`；工作台按既有流程再请求 `/tools`；
7. 任何服务端/网络失败都保留 username/display_name，清空 password/confirm_password；
8. 409/503 显示不可用安全文案，429 显示频繁提示，422 显示检查信息，均不显示阈值或账号存在状态。

### 7.3 全局认证失效事件

`frontend/src/api/client.ts` 使用无敏感信息的认证代次，防止登录前发出的旧请求在新登录成功后迟到并清空新认证态：

```ts
export const AUTH_REQUIRED_EVENT = "test-platform:auth-required";

export interface AuthRequiredEventDetail {
  generation: number;
}

let authGeneration = 0;

export function currentAuthGeneration(): number {
  return authGeneration;
}

export function advanceAuthGeneration(): number {
  authGeneration += 1;
  return authGeneration;
}
```

每个 `request()` 在发起 fetch 前捕获当前 generation。当且仅当响应满足 `status === 401 && payload.code === "AUTH_REQUIRED"` 时，在抛 `ApiError` 前派发只含该数字的 `CustomEvent<AuthRequiredEventDetail>`。不把 path、响应体、用户名或 Token 放入事件。

`AuthProvider` 在启动 `/auth/me` 之前注册监听。为区分“首次匿名”与“已有会话失效”，只保存两个非敏感布尔标记：

```ts
const AUTH_SESSION_SEEN_KEY = "tp_session_seen";       // localStorage，跨浏览器重启
const AUTH_EXPIRED_NOTICE_KEY = "tp_auth_expired_notice"; // sessionStorage，一次提示
```

- `/auth/me`、登录或注册成功：先 `advanceAuthGeneration()`，再 `localStorage.setItem(AUTH_SESSION_SEEN_KEY, "1")`；
- 收到事件时先比较 `event.detail.generation === currentAuthGeneration()`；不一致说明这是旧请求，完全忽略；
- generation 一致且 seen 存在：先移除 seen、写一次 notice、推进 generation，再设置 `auth=null`；
- 并发 401：第一个事件推进 generation，后续同代事件被忽略，不重复清状态或提示；
- 初次匿名 `/auth/me` 401：没有 seen，只设置 `auth=null`，不显示过期提示；
- 主动 logout：清除 seen 和 notice，再设置 `auth=null`；
- `LoginPage` 挂载时读取并立即删除 notice，使用现有 `InlineMessage` 展示一次；
- `Protected` 继续生成 `/login?next=`；登录成功仍只接受单 `/` 开头且非 `//` 的站内地址。

`localStorage` marker 只表达“此浏览器 profile 曾建立会话”，不代表认证凭据；清 Cookie、切换账号、服务端撤销最终都由下一次 401 消费并清除它。多标签页共享 seen，所以同一浏览器 profile 只保证一个标签显示一次过期提示，其他标签仍会回登录但不重复提示。每个 Vitest 用例必须在 beforeEach/afterEach 清除两个 key。Storage 中不得保存用户信息、Session 到期时间、密码或任何 Token。

### 7.4 可访问性和视觉约束

- 登录和注册继续使用 `LoginLayout`，不增加第三列、插画或装饰动画。
- 确认密码和字段级错误加入现有表单纵向节奏；错误容器使用 `role="alert"`。
- 密码长度错误使用稳定 id `register-password-error`，确认密码错误使用 `register-confirm-password-error`；对应输入的 `aria-invalid` 与 `aria-describedby` 必须精确指向自己的错误节点。
- 空白显示名称错误使用稳定 id `register-display-name-error`，显示名称输入以同样方式关联；用户名及服务端表单级错误继续沿用现有安全提示容器。
- Tab 顺序：用户名 → 显示名称 → 密码 → 确认密码 → 创建账号 → 返回登录。
- Enter 只触发一次提交；submitting 时禁用按钮。
- 焦点样式沿用现有 token，并在 1280×720、1440×900 桌面视口验证无溢出。
- 新增状态变化不依赖动画；若补充 transition，必须服从 `prefers-reduced-motion`。

---

## 8. 配置、迁移与发布设计

### 8.1 环境变量

```dotenv
SESSION_IDLE_HOURS=168
SESSION_ABSOLUTE_HOURS=168
REGISTRATION_MODE=open
REGISTRATION_RATE_LIMIT=5
REGISTRATION_RATE_WINDOW_MINUTES=15
REGISTRATION_LOCK_MINUTES=15
REGISTRATION_GLOBAL_LIMIT=100
REGISTRATION_GLOBAL_WINDOW_MINUTES=15
REGISTRATION_GLOBAL_LOCK_MINUTES=15
```

`.env.example` 和 dev/隔离测试 Compose fallback 使用以上值。`.env.prod.example` 与真实 `/srv/test-platform/env/.env.prod` 必须显式列出，生产不能依赖 fallback。

生产部署主机的 env 还声明一个只供发布门禁使用、不得传入应用容器的字段：

```dotenv
SESSION_COOKIE_RISK_ACCEPTANCE_ID=
```

当前生产示例是已知的 HTTP + `COOKIE_SECURE=false`。本功能不能把它降格为普通 warning：`.env.prod` 还需提供 `SESSION_COOKIE_RISK_ACCEPTANCE_ID`，值为 3–64 位、匹配 `[A-Z][A-Z0-9._-]{2,63}` 的人工审批记录编号，例如 `RISK-20260830-001`。对应 release record 必须可追溯地记录审批人、时间、适用入口、接受 7 天 Cookie 传输风险范围和 HTTPS 退出条件；发布负责人在部署前人工核验并把证据附到发布记录。脚本只能校验配置项是否存在及编号格式，不能声称已验证外部审批内容；缺少编号或人工记录时部署阻断并保持 `REGISTRATION_MODE=disabled`。完成 HTTPS 改造后，`APP_PUBLIC_URL` 使用实际 HTTPS 入口并设置 `COOKIE_SECURE=true`，此时 acceptance ID 可为空。

### 8.2 数据库与 Alembic

本功能不新增、修改或回退 Alembic revision：Session 字段、用户字段和 `login_throttles` 结构均已存在，注册使用隔离的 `reg_*` key。生产继续遵守现有 0019 expand → 0020 contract 门禁；本功能不能为了注册强行推进 `ALEMBIC_TARGET`，也不新增或放宽任何 manifest 要求。若 target 保持 `20260824_0019`，沿用 expand 发布；若 target 不是 0019，仍必须按现有 `deploy-prod.sh` 规则提供并验证 `PROJECT_ACCESS_MANIFEST`、readiness 与授权摘要。本功能实施时运行两种 target 的既有部署门禁测试，并证明模型 metadata 与当前数据库兼容。

### 8.3 发布顺序

1. 保持生产 `REGISTRATION_MODE=disabled`，发布后端兼容代码；
2. 验证状态接口、密码规则、168h Session、`reg_*` 限流桶、XFF 覆盖和旧长密码登录；
3. 发布前端，验证 disabled 直达页失败关闭；
4. 配置现有日志系统对 `auth.register.circuit` 告警；
5. 完成 HTTPS/Secure 或当前 HTTP 临时偏离的正式 release record；
6. 将 `REGISTRATION_MODE=open`，只在隔离/专用 dev 数据库完成真实注册，不在生产创建验收账号；
7. 观察 409/422/429/503、注册成功率、401、Session 撤销及公共工具成本指标。

### 8.4 回滚

- 第一优先级：把 `REGISTRATION_MODE=disabled`，无需回滚数据库即可停止新注册。
- 前端回滚必须与后端模式一致，不能留下可点击但不可用的入口。
- 代码回滚不删除已注册用户，不回写密码，不批量缩短已签发 168h Session。
- 如安全事件要求立即终止 7 天 Session，必须走受保护的管理员撤销流程并记录审计；仅修改默认值无效。
- `login_throttles` 中既有 `reg_*` 桶可保留；普通应用回滚不删除安全计数。
- 回滚后的登录仍不得恢复“最少 12 位”的输入预校验，否则 6–11 位新账号会被锁定。

---

## 9. 文件影响清单

### 后端

- `backend/app/core/security.py`
- `backend/app/core/config.py`
- `backend/app/models/identity.py`
- `backend/app/schemas/auth.py`
- `backend/app/schemas/admin.py`
- `backend/app/services/auth.py`
- `backend/app/api/auth.py`
- `backend/app/main.py`
- `backend/tests/conftest.py`
- `backend/tests/test_phase2.py`
- `backend/tests/test_registration_and_catalog.py`
- `backend/tests/test_api.py`

### 前端

- `frontend/src/App.tsx`
- `frontend/src/App.test.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/app.css`

### 配置、部署、文档与 smoke

- `.env.example`
- `.env.prod.example`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `nginx/nginx.conf`
- `scripts/deploy-prod.sh`
- `tests/test_smoke.py`
- `README.md`
- `docs/接口文档.md`
- `docs/PRD-固定角色与项目工具权限-V1.0.md`
- `docs/固定角色与项目工具权限_开发设计与计划.md`

本计划不新增项目文件。

---

## 10. 实施任务

### Task 0: 固化执行基线与变更边界

**Files:**
- Read: all files in section 9
- Read: `docs/PRD-登录注册与7天会话-V1.0.md`

- [ ] **Step 1: 检查当前工作树，不修改或清理用户改动**

Run:

```bash
cd /Users/admin/Testproject/test-platform
git status --short
git diff -- backend/app/services/auth.py backend/tests/test_phase2.py docker-compose.yml frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/api/client.ts
```

Expected: 能识别现有用户改动；不得运行 reset/checkout/clean。

- [ ] **Step 2: 记录当前迁移 head，确认本功能不创建 revision**

Run:

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m alembic heads
python3 -m alembic history -r 20260824_0019:heads
```

Expected: 记录实际 head 和现有 0019→0020 contract 状态；本功能不改变 revision graph，不修改 `ALEMBIC_TARGET`。

- [ ] **Step 3: 记录基线测试，不把既有失败归因于本功能**

Run:

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_phase2.py tests/test_registration_and_catalog.py tests/test_api.py tests/test_migrations.py

cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run
```

Expected: 保存精确通过/失败数量和失败名；后续只接受与本功能有关且被修复的新增失败。

---

### Task 1: 在现有 throttle 表实现隔离且原子的注册计数服务

**Files:**
- Modify: `backend/app/core/config.py:1-40`
- Modify: `backend/app/models/identity.py`（仅同步 `LoginThrottle` 职责注释，不改表结构）
- Modify: `backend/app/services/auth.py:16-100`
- Modify: `backend/tests/test_registration_and_catalog.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: 先写命名空间、配置和窗口算法失败测试**

新增测试名：

```text
test_registration_keys_use_reg_namespace_and_hash_values
test_login_success_clear_does_not_delete_registration_buckets
test_registration_rate_settings_reject_disabled_or_weakened_protection
test_registration_rate_settings_require_lock_not_shorter_than_window
test_registration_counter_allows_five_and_blocks_sixth
test_registration_global_counter_opens_at_one_hundred
test_rate_limited_submissions_still_increment_global_counter
test_registration_counter_resets_after_window_and_lock
```

断言 `key_type` 只使用 `reg_global/reg_ip/reg_username/reg_device`，表中没有原始 username/IP/device；登录的 `username/ip` 桶与注册桶互不删除。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_registration_and_catalog.py tests/test_api.py -k "registration_keys or registration_rate_settings or registration_counter or registration_global_counter"
```

Expected: 因注册配置和服务函数不存在而失败。

- [ ] **Step 3: 实现 Settings 与注册计数服务**

在 `core/config.py` 导入 `pydantic.Field` 与 `model_validator` 并加入第 6.2 节配置和 lock/window 交叉校验；把 `models/identity.py` 中 `LoginThrottle` 的职责注释同步为“认证防滥用持久化桶，登录与注册通过 key namespace 隔离”，保留兼容类名和全部字段不变；在 `services/auth.py` 复用 `LoginThrottle`，实现：

```python
def registration_throttle_keys(
    *,
    username: str | None,
    ip_address: str | None,
    device_signal: str | None,
) -> list[tuple[str, str]]:
    """按固定锁序返回只含 reg_* 类型与 SHA-256 哈希的计数键。"""


def evaluate_registration_attempt(
    database: Session,
    *,
    username: str | None,
    ip_address: str | None,
    device_signal: str | None,
    settings: Settings,
) -> RegistrationRateDecision:
    """在传入事务中原子检查、修改并 flush；事务提交与释放由调用方负责。"""
```

查询已存在行时使用 `with_for_update()`；新行仍使用现有 `LoginThrottle`。不修改 `record_login_failure()`、`is_login_blocked()` 或 `clear_login_failures()` 的代码路径。

- [ ] **Step 4: 运行服务测试和既有登录限流回归**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_registration_and_catalog.py tests/test_api.py -k "registration_counter or registration_keys or login"
```

Expected: 注册窗口测试通过，现有登录锁定和清理行为不变。

- [ ] **Step 5: 提交独立检查点**

仅当这些文件未混入无法归属的用户改动时执行：

```bash
cd /Users/admin/Testproject/test-platform
git add backend/app/core/config.py backend/app/models/identity.py backend/app/services/auth.py backend/tests/test_registration_and_catalog.py backend/tests/test_api.py
git commit -m "feat(auth): add atomic registration throttle namespace"
```

---

### Task 2: 统一服务端新密码策略并保留存量登录兼容

**Files:**
- Modify: `backend/app/core/security.py:20-59`
- Modify: `backend/app/schemas/auth.py:8-62`
- Modify: `backend/app/schemas/admin.py:11-35`
- Modify: `backend/app/services/auth.py:14`
- Modify: `backend/tests/test_phase2.py:148-170`
- Modify: `backend/tests/test_registration_and_catalog.py`
- Modify: `backend/tests/conftest.py:87-90`

- [ ] **Step 1: 写 5/6/18/19 与存量长密码失败测试**

测试名：

```text
test_password_policy_accepts_six_and_eighteen_code_points
test_password_policy_rejects_five_and_nineteen_code_points
test_password_policy_counts_unicode_code_points_without_trimming
test_register_setup_change_and_admin_schemas_share_password_boundaries
test_login_request_accepts_legacy_long_password
test_legacy_long_password_user_can_login
```

存量长密码测试用测试内 `argon2.PasswordHasher` 直接生成旧哈希并插入 User；不能调用新的 `hash_password()` 伪造存量数据。

- [ ] **Step 2: 运行测试确认旧 12–256 规则失败**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_phase2.py tests/test_registration_and_catalog.py -k "password_policy or password_boundaries or legacy_long_password"
```

Expected: 6 位相关测试失败；19 位新设密码拒绝测试失败；存量登录测试锁定兼容目标。

- [ ] **Step 3: 实现共享常量、校验与 Schema 边界**

- `hash_password()` 调用 `validate_new_password()`；
- `verify_password()` 保持原样；
- `RegisterRequest.password`、`SetupRequest.password`、`ChangePasswordRequest.new_password`、`UserCreateRequest.password`、`ResetPasswordRequest.new_password` 使用共享常量 6/18；
- `LoginRequest.password`、`ChangePasswordRequest.current_password` 保持 1/256；
- `DUMMY_PASSWORD_HASH` 改用 `dummy-password`；它只用于未知用户的等价成本校验，不能作为存量长密码测试来源；
- 更新现有测试 fixture 中用于“设置新密码”的 19 位以上样例为 6–18 位；仅专用存量兼容用例保留长密码。

- [ ] **Step 4: 运行定向与认证回归**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_phase2.py tests/test_registration_and_catalog.py -k "password or login or setup"
```

Expected: 新规则和旧长密码登录均通过；Argon2id 断言仍通过。

- [ ] **Step 5: 提交独立检查点**

```bash
cd /Users/admin/Testproject/test-platform
git add backend/app/core/security.py backend/app/schemas/auth.py backend/app/schemas/admin.py backend/app/services/auth.py backend/tests/test_phase2.py backend/tests/test_registration_and_catalog.py backend/tests/conftest.py
git commit -m "feat(auth): enforce new password length policy"
```

---

### Task 3: 增加注册模式、状态接口与安全注册语义

**Files:**
- Modify: `backend/app/schemas/auth.py:8-18`
- Modify: `backend/app/api/auth.py:46-199`
- Modify: `backend/tests/test_registration_and_catalog.py:10-70`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: 写模式、显示名称、重复用户名和固定权限测试**

测试名：

```text
test_registration_status_exposes_only_mode
test_registration_status_uses_no_store
test_registration_mode_open_creates_session
test_anonymous_registration_issues_csrf_for_followup_writes
test_registration_mode_disabled_fails_closed
test_registration_mode_invite_fails_closed
test_registration_rejects_blank_display_name
test_duplicate_normalized_username_uses_safe_error
test_registration_creates_only_active_tester_without_grants
```

同时断言 disabled/invite 不写 User、不写 Session，状态响应不含阈值或内部配置。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_registration_and_catalog.py tests/test_api.py -k "registration_status or registration_mode or blank_display or duplicate_normalized"
```

- [ ] **Step 3: 使用 Task 1 的严格 Settings，实现 Schema 和接口**

- `Settings.registration_mode` 已由 Task 1 使用严格 `Literal` 和默认 open；本任务不另建开关；
- `RegisterRequest` 用 `field_validator("display_name")` 返回 trim 后非空值；
- 增加 `RegistrationStatusResponse`；
- 增加公开 `GET /auth/registration-status`，固定 `Cache-Control: no-store`；
- `register()` 保留 mode 防御性检查，即使 middleware 未挂载也不能开放 disabled/invite；
- 重复用户名先写 `auth.register` denied 审计并 commit，再抛 `409 REGISTRATION_UNAVAILABLE`；
- 用户创建 `flush()` 仍可能遇到并发唯一键竞争：捕获 `IntegrityError` 后 rollback 当前业务 Session，通过 `request.app.state.registration_session_factory` 新建隔离 Session 重新查询规范化用户名；确认已存在时写同一安全审计并返回 409，若 factory 缺失或无法确认是用户名冲突则继续交给数据库 503 路径，不能 fallback 到真实库，也不能把任意约束异常伪装成重复用户名；
- 成功响应固定 `role="tester"`、`roles=["tester"]`，不增加关联记录。

- [ ] **Step 4: 运行测试**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_registration_and_catalog.py tests/test_api.py -k "registration"
```

Expected: 模式、错误语义、空白显示名称和固定权限均通过。

- [ ] **Step 5: 提交独立检查点**

```bash
cd /Users/admin/Testproject/test-platform
git add backend/app/schemas/auth.py backend/app/api/auth.py backend/tests/test_registration_and_catalog.py backend/tests/test_api.py
git commit -m "feat(auth): add fail-closed registration modes"
```

---

### Task 4: 实现全提交注册限流、熔断、审计与告警

**Files:**
- Modify: `backend/app/services/auth.py:16-100`
- Modify: `backend/app/main.py:97-225`
- Modify: `backend/app/api/auth.py:46-199`
- Modify: `backend/tests/conftest.py:15-65`
- Modify: `backend/tests/test_registration_and_catalog.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: 先写 middleware body 回放与全提交计数测试**

测试名：

```text
test_registration_middleware_replays_body_to_pydantic
test_registration_attempt_counts_valid_submission
test_registration_attempt_counts_duplicate_username
test_registration_attempt_counts_unknown_field_submission
test_registration_attempt_counts_malformed_json_by_available_dimensions
test_disabled_and_invite_submissions_are_counted_without_business_writes
test_registration_oversized_body_is_counted_then_rejected
test_registration_attempt_stores_only_hashed_keys
```

测试直接检查数据库不存在 password、display_name、原始 username/IP/device 值。

测试 fixture 必须把 `app.state.registration_session_factory` 临时替换为当前 `database_factory` 并在 teardown 恢复。middleware 的 provider 每次调用时动态读取该 state，确保独立事务仍使用隔离测试库，不能绕过依赖覆盖连接开发/生产数据库；另加“factory 缺失时返回 503 且不尝试模块级 `SessionLocal`”的测试。

- [ ] **Step 2: 写阈值、恢复与失败关闭测试**

```text
test_registration_rate_limit_allows_five_and_blocks_sixth
test_registration_rate_limit_recovers_after_fifteen_minutes
test_registration_global_circuit_opens_at_one_hundred
test_registration_global_circuit_returns_503_on_next_request
test_registration_global_circuit_recovers_after_fifteen_minutes
test_registration_counter_database_failure_fails_closed
test_registration_session_factory_missing_fails_closed
test_registration_request_id_is_present_on_middleware_errors
test_registration_rejection_precedence_is_mode_circuit_rate_payload
test_registration_middleware_drains_oversized_request_body
test_gateway_overwrites_spoofed_forwarded_for_and_clears_device_header
test_unmarked_direct_request_ignores_spoofed_forwarded_for
```

全局测试轮换 100 个 IP/username，确保不会先命中单来源限制；时间测试 monkeypatch `app.services.auth.utc_now`。

- [ ] **Step 3: 写审计与单次告警测试**

```text
test_registration_validation_and_unknown_fields_have_distinct_audit_codes
test_registration_oversized_body_has_distinct_safe_audit_code
test_registration_rate_and_circuit_have_distinct_audit_codes
test_registration_circuit_open_logs_warning_once_per_window
test_registration_audit_contains_no_password_hash_or_raw_token
test_non_registration_validation_error_does_not_write_registration_audit
test_registration_validation_audit_failure_preserves_422
```

- [ ] **Step 4: 运行新增测试确认全部失败**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_registration_and_catalog.py tests/test_api.py -k "registration_middleware or registration_attempt or registration_rate or registration_global or registration_circuit"
```

- [ ] **Step 5: 实现原子 service 与纯 ASGI middleware**

复用 Task 1 的原子 service，实现以下最小接口，不改现有登录 throttle：

```python
def resolve_client_ip(
    *,
    forwarded_for: str | None,
    peer_host: str | None,
    gateway_marker: str | None,
) -> str | None:
    """只在网关已覆盖标记时接受唯一 XFF，否则回退连接地址。"""


def extract_registration_username(raw_body: bytes) -> str | None:
    """只解析并规范化 username；不读取或返回其他字段值。"""


class RegistrationAttemptMiddleware:
    """在 Pydantic 校验前统计、限流并原样回放注册请求。"""

    def __init__(
        self,
        app: ASGIApp,
        session_factory_provider: Callable[[], sessionmaker[Session]],
    ) -> None:
        self.app = app
        self.session_factory_provider = session_factory_provider

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """仅拦截注册 POST；其他 ASGI scope 原样传递。"""
```

应用初始化和 middleware 顺序必须明确写成：

```python
app.state.registration_session_factory = SessionLocal
app.add_middleware(
    RegistrationAttemptMiddleware,
    session_factory_provider=lambda: app.state.registration_session_factory,
)
app.add_middleware(RequestIdMiddleware)
```

provider 闭包捕获根 FastAPI `app`，每次请求动态读取 state，不能通过 `self.app.state` 猜测下游 ASGI 包装对象，也不能在缺失/异常时 fallback 到模块级 `SessionLocal`。每个注册 POST（所有模式）创建独立计数 Session；`evaluate_registration_attempt()` 只修改并 flush，middleware 对放行、429、熔断 503 和模式关闭 503 的计数决策统一 commit，对异常 rollback；`IntegrityError` 后 rollback、close、通过 provider 创建新 Session并只重试一次，所有路径 finally close。commit 后的响应优先级固定为 `disabled/invite 503 → blocked_kind=circuit 的 503 → blocked_kind=rate 的 429 → oversized body 的 413 → 下游`；`circuit_opened=True` 单独触发告警而不改变本次响应。因此关闭模式不会泄露内部阈值；只要尚未命中已生效 global circuit，其提交仍计数。用户与 Session 创建始终由下游 `get_db()` 的另一业务 Session 完成。超过 64 KiB 时 drain 剩余消息。

`RequestValidationError` handler 只在注册 POST 通过 `request.app.state.registration_session_factory` 新建独立 Session，写 validation/unknown-field/malformed 固定分类；factory 缺失或审计失败都只写脱敏错误日志并保留原 422。不读取 errors 的 `input`/`ctx`/body，也不再递增计数，避免 middleware 与异常 handler 双计；所有审计路径显式 commit 或 rollback 并 close。

- [ ] **Step 6: 验证阈值、body 和敏感数据测试**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_registration_and_catalog.py tests/test_api.py -k "registration"
```

Expected: 5/100 边界、15 分钟恢复、422 计数、413、429、503、审计与 request_id 全通过。

- [ ] **Step 7: 在一次性 PostgreSQL 容器验证并发**

现有 Compose 卷名由 `PLATFORM_RUNTIME_ENV` 固定，不能仅靠新 project name保证隔离。使用无 volume、只绑定本机 55432 的一次性 PostgreSQL 容器；端口已被占用时立即停止并改用明确的新测试端口，不能复用占用者。集成测试通过 `REGISTRATION_INTEGRATION_DATABASE_URL` 自建 engine，并在 fixture 中执行 `Base.metadata.create_all()` / `drop_all()`，不依赖 Alembic 或共享数据库：

```bash
cd /Users/admin/Testproject/test-platform
registration_it_container=tp-registration-it-db-20260830
cleanup_registration_it() { docker rm -f "$registration_it_container" >/dev/null 2>&1 || true; }
trap cleanup_registration_it EXIT
if lsof -nP -iTCP:55432 -sTCP:LISTEN >/dev/null 2>&1; then
  echo '55432 已被占用；请选择未占用的专用测试端口' >&2
  exit 1
fi
docker run --rm -d --name "$registration_it_container" \
  -e POSTGRES_DB=registration_it \
  -e POSTGRES_USER=registration_it \
  -e POSTGRES_PASSWORD=registration_it_only \
  -p 127.0.0.1:55432:5432 postgres:17-alpine
until docker exec "$registration_it_container" pg_isready -U registration_it -d registration_it; do sleep 1; done
cd backend
REGISTRATION_INTEGRATION_DATABASE_URL='postgresql+psycopg://registration_it:registration_it_only@127.0.0.1:55432/registration_it' \
  python3 -m pytest -q tests/test_registration_and_catalog.py -k "registration_concurrent or concurrent_duplicate_username"
```

集成 fixture 必须解析 URL，并只接受 loopback host 与数据库名 `registration_it`；建立 engine 后先 `Base.metadata.create_all(engine)`，结束时 `drop_all()` 和 `dispose()`。用例还包含 `test_concurrent_duplicate_username_returns_201_and_safe_409`。Expected: 测试从空表同时发起两个首次创建相同 global/IP bucket 的请求，随后扩展到 20 个并发请求；global/同一 IP 计数不丢失，阈值后没有额外成功请求，没有死锁或唯一键 500；两个并发同名注册固定为一个 201、一个安全 409，数据库只有一个用户。trap 删除容器，且没有持久卷。该用例不得接受共享或生产数据库 URL。

- [ ] **Step 8: 提交独立检查点**

```bash
cd /Users/admin/Testproject/test-platform
git add backend/app/services/auth.py backend/app/main.py backend/app/api/auth.py backend/tests/conftest.py backend/tests/test_registration_and_catalog.py backend/tests/test_api.py
git commit -m "feat(auth): enforce registration abuse controls"
```

---

### Task 5: 将新 Session 生命周期统一为 168 小时

**Files:**
- Modify: `backend/app/core/config.py:27-30`
- Verify: `backend/app/services/auth.py:101-148`
- Verify: `backend/app/api/auth.py:53-64`
- Modify: `backend/tests/test_phase2.py`
- Modify: `backend/tests/conftest.py:87-90`

- [ ] **Step 1: 写 Session 创建、Cookie 和边界失败测试**

测试名：

```text
test_settings_default_session_lifetime_is_168_hours
test_create_session_uses_168_hour_idle_and_absolute_expiry
test_auth_cookies_use_604800_max_age
test_session_is_valid_at_six_days_twenty_three_hours
test_session_is_invalid_at_exactly_seven_days
test_session_touch_never_extends_absolute_expiry
test_existing_session_keeps_persisted_expiry_after_config_change
```

- [ ] **Step 2: 运行测试确认 8/24 默认值失败**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_phase2.py -k "168_hour or 604800 or six_days or exactly_seven_days or persisted_expiry"
```

- [ ] **Step 3: 最小修改默认值和 fixture**

```python
session_idle_hours: int = 168
session_absolute_hours: int = 168
```

保留 `create_session()` 和 `resolve_session()` 的现有字段与 `min(now + idle, absolute)`。fixture 不再写死 8/24，改用测试 Settings 或 168/168。

- [ ] **Step 4: 运行 Session、安全撤销与 CSRF 回归**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q tests/test_phase2.py tests/test_access_control.py -k "session or logout or disabled or csrf or password"
```

Expected: 7 天边界通过，logout、停用、撤销、改密仍可提前失效。

- [ ] **Step 5: 提交独立检查点**

```bash
cd /Users/admin/Testproject/test-platform
git add backend/app/core/config.py backend/tests/test_phase2.py backend/tests/conftest.py
git commit -m "feat(auth): issue fixed seven-day sessions"
```

---

### Task 6: 前端注册状态与全局会话失效处理

**Files:**
- Modify: `frontend/src/api/client.ts:7-112`
- Modify: `frontend/src/App.tsx` 中 `AuthProvider`、`LoginPage`、`RegisterPage`、`Protected`（当前约 127-264、337-391 行）
- Modify: `frontend/src/App.test.tsx` shared fetch helpers and current registration test near line 1207

- [ ] **Step 1: 写 fail-closed 与 AUTH_REQUIRED 失败测试**

测试名：

```text
注册模式明确为 open 时显示注册链接
注册模式 disabled 时隐藏入口并阻止直达提交
invite 模式在未实现邀请码时失败关闭
注册状态查询失败或返回未知值时默认关闭
初次匿名 auth me 401 不显示会话过期提示
已有会话后任意 AUTH_REQUIRED 只显示一次过期提示
登录成功后迟到的旧代 401 不得清空新认证态
受保护的 tools 或 sessions 请求 401 触发全局失效而非只测 auth me
主动退出后匿名恢复不显示过期提示
登录继续支持站内 next 并拒绝外部 next
INVALID_CREDENTIALS 固定显示用户名或密码错误
ACCOUNT_LOCKED 固定显示登录尝试过多请稍后再试
AuthProvider 卸载后移除 AUTH_REQUIRED 事件监听
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run src/App.test.tsx
```

- [ ] **Step 3: 在 API client 派发稳定认证事件**

在解析错误 payload 后、抛出 `ApiError` 前：

```ts
const requestGeneration = currentAuthGeneration();

if (response.status === 401 && payload?.code === "AUTH_REQUIRED") {
  window.dispatchEvent(new CustomEvent<AuthRequiredEventDetail>(
    AUTH_REQUIRED_EVENT,
    { detail: { generation: requestGeneration } },
  ));
}
```

添加对应中文注释；detail 只能包含数字 generation。

- [ ] **Step 4: 扩展 AuthProvider**

- 注册事件监听 effect 必须声明在初次 `reload()` effect 之前；
- 增加注册模式状态，默认 disabled；
- 严格验证状态响应，并用 effect cleanup 的 `cancelled` 标记忽略卸载后的结果；
- 用包装后的 `setAuth` 推进 generation 并维护非敏感 seen 标记；事件 generation 不一致时忽略；
- logout 清除 seen/notice；
- `LoginPage` 读取一次性提示；
- `LoginPage` 按稳定错误码映射文案：`INVALID_CREDENTIALS` 只显示“用户名或密码错误”，`ACCOUNT_LOCKED` 只显示“登录尝试过多，请稍后再试”，不得直接信任未来可能变化的后端 detail；
- 保留现有 Protected 和 next 安全判断；
- 测试 beforeEach/afterEach 清两个 Storage key；共享 fetch helper 对 registration-status 返回明确模式；
- 现有 line 1207 注册测试必须 mock `{mode:"open"}`，密码改为 6–18 位并填写新增确认密码。
- `authGeneration` 是模块级单调值，测试不得假设初始为 0，也不为测试暴露生产 reset API；迟到 401 用例先通过 `currentAuthGeneration()` 捕获当前值，以 deferred fetch 控制“旧请求发出 → 登录推进 generation → 旧 401 返回”的顺序。
- 每个事件相关用例结束前必须 resolve/reject 并 `await` 全部 deferred Promise，再调用 Testing Library `cleanup()`；单独测试 unmount 后派发 AUTH_REQUIRED 不再改变 Storage 或认证状态，证明 effect cleanup 已移除监听器，避免事件污染下一用例。

- [ ] **Step 5: 运行测试与类型构建**

```bash
cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run src/App.test.tsx
npm run build
```

- [ ] **Step 6: 提交独立检查点**

```bash
cd /Users/admin/Testproject/test-platform
git add frontend/src/api/client.ts frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(auth): handle registration mode and expired sessions"
```

---

### Task 7: 完成注册表单、Unicode 校验与失败清密

**Files:**
- Modify: `frontend/src/App.tsx:196-264`
- Modify: `frontend/src/App.test.tsx` current registration test near line 1207 and new registration cases
- Modify: `frontend/src/app.css`（仅在现有选择器不足时增加字段提示样式）

- [ ] **Step 1: 写注册表单行为失败测试**

测试名：

```text
注册支持 6 位和 18 位 Unicode code point 密码
注册拒绝 5 位和 19 位密码且不请求 API
注册确认密码不一致时不发送请求
注册拒绝仅含空格的显示名称且不发送请求
注册请求只发送 username display_name password
注册失败清空两个密码并保留身份字段
注册提交中禁止重复请求
注册成功自动进入工作台并加载可见工具
密码与确认密码错误节点具有正确 aria-describedby
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run -t "注册"
```

- [ ] **Step 3: 实现共享密码函数和 RegisterValues**

- 使用 `Array.from(value).length`；
- 不 trim 密码；
- 增加确认密码输入和字段级错误；
- body 显式只取三个后端字段；
- 任何失败路径调用函数式 `setValues` 清空两个密码；
- 429 与 409/503 使用不同安全文案；
- 密码/确认密码分别绑定 `register-password-error` 和 `register-confirm-password-error`；
- 显示名称 trim 后为空时绑定 `register-display-name-error`，清密但不发送请求；
- 保持 `LoginLayout` 和按钮视觉；
- 成功测试的 `/tools` mock 只返回公共工具，并明确断言该请求发生且页面不呈现未返回的项目工具。

- [ ] **Step 4: 运行注册测试和构建**

```bash
cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run -t "注册"
npm run build
```

- [ ] **Step 5: 提交独立检查点**

```bash
cd /Users/admin/Testproject/test-platform
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/app.css
git commit -m "feat(auth): complete accessible registration form"
```

---

### Task 8: 同步所有其他新密码前端入口

**Files:**
- Modify: `frontend/src/App.tsx:302-358,2020-2155`
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: 写每个入口的 5/6/18/19 测试**

测试名：

```text
setup 使用共享 6 到 18 位密码规则
用户改密使用共享 6 到 18 位密码规则
固定角色管理员建号使用共享密码规则
兼容用户管理建号使用共享密码规则
管理员重置密码使用共享密码规则
登录表单不拒绝存量 19 位以上密码
```

- [ ] **Step 2: 运行测试确认 `minLength=12` 入口失败**

```bash
cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run -t "密码规则|存量"
```

- [ ] **Step 3: 复用 `validateNewPassword`，移除不一致的 HTML 长度权威**

每个新设密码 submit 在请求前调用同一函数并显示字段错误。登录 submit 不增加长度判断。管理员现有权限、CSRF、`must_change_password` 和 Session 撤销行为不变。

- [ ] **Step 4: 扫描遗漏并回归**

```bash
cd /Users/admin/Testproject/test-platform
rg -n 'minLength=\{12\}|maxLength=\{256\}|至少 12 位|12–256|12 到 256' frontend/src backend/app README.md docs .env.example .env.prod.example docker-compose.yml docker-compose.prod.yml

cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run
npm run build
```

Expected: 扫描只剩明确描述存量历史的文本；所有新密码 UI 测试通过。

- [ ] **Step 5: 提交独立检查点**

```bash
cd /Users/admin/Testproject/test-platform
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(auth): align all password entry points"
```

---

### Task 9: 同步环境、Compose、部署校验、接口文档与 smoke

**Files:**
- Modify: `.env.example:18-23`
- Modify: `.env.prod.example:6-18`
- Modify: `docker-compose.yml:99-113`
- Modify: `docker-compose.prod.yml:10-35`
- Modify: `nginx/nginx.conf:106-117`
- Modify: `scripts/deploy-prod.sh:17-40`
- Modify: `tests/test_agent_split.py`
- Modify: `tests/test_smoke.py:57-100`
- Modify: `README.md:66-82`
- Modify: `docs/接口文档.md:8-100`
- Modify: `docs/PRD-固定角色与项目工具权限-V1.0.md:73,528-550,830-850`
- Modify: `docs/固定角色与项目工具权限_开发设计与计划.md:179,1605-1609`

- [ ] **Step 1: 先补配置和 smoke 失败测试/断言**

新增或扩展：

```text
test_public_registration_status_is_reachable
test_compose_uses_seven_day_session_defaults
test_compose_exposes_registration_protection_settings
test_gateway_overwrites_forwarded_for_and_clears_untrusted_device_signal
test_platform_api_has_no_host_port
test_prod_insecure_cookie_requires_release_acceptance_reference
test_prod_secure_cookie_requires_https_public_url
test_deploy_env_parser_never_executes_values
test_registration_release_preserves_existing_migration_manifest_gate
```

`test_public_registration_status_is_reachable` 放在运行态 `tests/test_smoke.py`，只 GET 状态，不 POST 注册。Compose、Nginx 与 deploy 静态断言放在 `tests/test_agent_split.py`，不能伪装成线上 smoke。部署门禁测试使用临时 env：`.env.prod.example` 只要求声明空键，不把示例占位值当成有效审批；临时“真实 env”才覆盖 insecure/secure/恶意值各分支，并以 sentinel 断言失败发生在任何 Compose、pull、backup 之前。迁移门禁分别测试 target=0019 不新增 manifest 条件、target≠0019 仍按既有规则缺 manifest 即阻断。

- [ ] **Step 2: 更新 env 与 Compose**

- 写入第 8.1 节全部环境变量；
- base Compose fallback 改为 168/168 和注册默认值；
- prod example 显式列出，不依赖 fallback；
- 生产 `ALEMBIC_TARGET` 保持现有权限迁移策略，本功能不改 target；
- Nginx 平台 API location 必须精确包含 `proxy_set_header X-Forwarded-For $remote_addr;`、`proxy_set_header X-Test-Platform-Gateway "1";`、`proxy_set_header X-Registration-Device "";`；静态测试锁定三行，不能使用 `$proxy_add_x_forwarded_for`；
- Compose 中 `platform-api` 不增加 `ports`，静态与运行时都验证没有宿主机端口映射；
- `SESSION_COOKIE_RISK_ACCEPTANCE_ID` 只声明在 `.env.prod.example` 和真实 `.env.prod`，不映射进应用容器；
- 登录限制变量保持原值。

- [ ] **Step 3: 增加部署前配置验证和 Cookie 风险提示**

`deploy-prod.sh` 在已有文件存在性检查之后、任何 Compose/pull/backup/目录创建之前执行安全门禁。新增只解析精确 `KEY=value` 的 helper，从 `base_env` 读取所需键；不得 `source`、`eval` 或执行 env 内容，重复键、缺 `=`、空 key 等异常格式直接阻断。Session 必须 168/168；mode 必须为三种之一；rate/global limit 必须大于 0 且不超过默认上限；窗口和锁定不得短于 15 分钟，且两类 lock 都不得短于对应 window。若 `COOKIE_SECURE=false`，真实 `.env.prod` 必须提供符合 `[A-Z][A-Z0-9._-]{2,63}` 的 `SESSION_COOKIE_RISK_ACCEPTANCE_ID`；若 `COOKIE_SECURE=true`，acceptance ID 可为空，但 `APP_PUBLIC_URL` 必须为 HTTPS。日志只写“检测到格式有效的人工风险审批引用”，不得回显完整 ID、宣称外部审批内容已机器验证或输出其他 env 值。门禁通过后，生产主机再用 `--env-file "$base_env" --env-file "$release_images"` 执行 Compose config 校验；发布 checklist 另行签字确认对应人工记录确实存在且字段完整。

- [ ] **Step 4: 同步文档**

- README：密码、注册模式、168h、Cookie 风险；
- 接口文档：公开例外加入 registration-status/register，补请求/响应、错误码、7 天说明，setup/改密改 6–18；
- 固定角色 PRD 第 73 行：把“当前没有自助注册接口”的基线陈述更新为“注册能力按 open/invite/disabled 部署模式开放”，保持第 8.1 节 active tester、无项目、无额外授权规则；
- 固定角色开发设计第 179 行及迁移测试表清单：将未实现的独立 `registration_throttles` 表改为权威表述——“复用既有 `login_throttles` 物理表，以 `reg_global/reg_ip/reg_username/reg_device` key_type 和带 kind 的哈希输入实现逻辑隔离；登录成功清理不影响注册桶；本功能不新增 migration”，并从预期新表集合删除 `registration_throttles`；
- 不改本 PRD 已锁定的需求含义。

- [ ] **Step 5: 验证配置和文档扫描**

```bash
cd /Users/admin/Testproject/test-platform
docker compose config --quiet
python3 -m unittest discover -s tests -v
rg -n 'SESSION_IDLE_HOURS=(8|24)|SESSION_ABSOLUTE_HOURS=(8|24)|至少 12 位密码|new_password":"至少 12 位|当前没有自助注册|registration_throttles' README.md docs/接口文档.md docs/PRD-固定角色与项目工具权限-V1.0.md docs/固定角色与项目工具权限_开发设计与计划.md .env.example .env.prod.example docker-compose.yml docker-compose.prod.yml
```

Expected: dev Compose 有效；临时 env 的部署脚本测试覆盖真实生产组合且不执行值；正式生产 Compose config 由部署脚本在主机上使用 `base_env + release_images` 验证；smoke 不创建账号；扫描无过时权威陈述。

- [ ] **Step 6: 提交独立检查点**

```bash
cd /Users/admin/Testproject/test-platform
git add .env.example .env.prod.example docker-compose.yml docker-compose.prod.yml nginx/nginx.conf scripts/deploy-prod.sh tests/test_agent_split.py tests/test_smoke.py README.md docs/接口文档.md docs/PRD-固定角色与项目工具权限-V1.0.md docs/固定角色与项目工具权限_开发设计与计划.md
git commit -m "docs(auth): align deployment with registration and seven-day sessions"
```

---

### Task 10: 全量回归、真实浏览器验收与发布证据

**Files:**
- Verify only: all files in section 9
- Artifacts: `output/playwright/`（测试产物，不提交）

- [ ] **Step 1: 后端全量测试与现有迁移回归**

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q
python3 -m alembic heads
```

Expected: 全量通过；`alembic heads` 与 Task 0 记录一致，本功能没有新增 revision，现有 0019/0020 migration gate 测试继续通过。

- [ ] **Step 2: 前端全量测试与生产构建**

```bash
cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run
npm run build
```

Expected: Vitest 全绿，TypeScript/Vite 构建成功。

- [ ] **Step 3: Compose、Nginx 与 live smoke**

```bash
cd /Users/admin/Testproject/test-platform
docker compose config --quiet
./scripts/dev-up.sh
docker compose ps -a
docker compose exec -T platform-gateway nginx -t
if docker compose port platform-api 8000 2>/dev/null | rg -q '.'; then
  echo 'platform-api 不得发布宿主机端口' >&2
  exit 1
fi
python3 -m unittest discover -s tests -v
```

Expected: 关键容器 healthy，Nginx 配置通过，`platform-api` 无宿主机绑定，公共状态接口可达，既有匿名保护和登录 smoke 不回归。可信 IP 边界由三类不写业务数据的证据共同锁定：Nginx 静态测试精确验证覆盖/marker/清除三行；后端测试验证没有 marker 时忽略伪造 XFF；运行态验证 API 无法被宿主机直连。常规发布验收不通过 POST 注册来探测该边界，避免污染共享或生产数据。

- [ ] **Step 4: 使用 Playwright CLI 做桌面真实浏览器验收**

先确认前置命令并创建产物目录：

```bash
command -v npx >/dev/null 2>&1
playwright_runner=/Users/admin/.codex/skills/playwright/scripts/playwright_cli.sh
test -x "$playwright_runner"
mkdir -p /Users/admin/Testproject/test-platform/output/playwright
curl --fail --silent http://127.0.0.1:8080/version.json | python3 -c 'import json,sys; assert json.load(sys.stdin)["runtime_environment"] == "dev"'
"$playwright_runner" -s=tp-auth open about:blank --headed
"$playwright_runner" -s=tp-auth resize 1280 720
"$playwright_runner" -s=tp-auth run-code "await page.context().clearCookies(); await page.goto('http://127.0.0.1:8080/version.json'); await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); }); await page.goto('about:blank')"
"$playwright_runner" -s=tp-auth route '**/api/v1/auth/me' --status 401 --content-type application/json --body '{"code":"AUTH_REQUIRED","message":"需要登录"}'
```

浏览器验收先清 Cookie 和当前 origin 的两类 Storage，并把 `/auth/me` 固定为匿名 401，保证命名 session 即使曾被使用也不会继承旧登录态或过期提示。随后对 registration-status、register、tools 和认证失效响应使用 CLI `route`；它使用真实浏览器和构建产物，但不会向任何数据库写注册账号。真实后端注册由 Task 3/4 的隔离数据库 API 测试证明，生产与共享 dev 禁止浏览器 POST。必须先在 `about:blank` 安装模式 route，再导航应用，避免 `AuthProvider` 已缓存 open 后才改 route。使用 snapshot 返回的实时 ref 填写/点击，每次交互后重新 snapshot。disabled 与 invite 的可执行顺序为：

```bash
"$playwright_runner" -s=tp-auth route '**/api/v1/auth/registration-status' --status 200 --content-type application/json --body '{"mode":"disabled"}'
"$playwright_runner" -s=tp-auth goto http://127.0.0.1:8080/register
"$playwright_runner" -s=tp-auth snapshot
"$playwright_runner" -s=tp-auth screenshot --filename=/Users/admin/Testproject/test-platform/output/playwright/register-disabled.png --full-page
"$playwright_runner" -s=tp-auth unroute '**/api/v1/auth/registration-status'
"$playwright_runner" -s=tp-auth route '**/api/v1/auth/registration-status' --status 200 --content-type application/json --body '{"mode":"invite"}'
"$playwright_runner" -s=tp-auth goto http://127.0.0.1:8080/register
"$playwright_runner" -s=tp-auth snapshot
"$playwright_runner" -s=tp-auth screenshot --filename=/Users/admin/Testproject/test-platform/output/playwright/register-invite-disabled.png --full-page
"$playwright_runner" -s=tp-auth unroute '**/api/v1/auth/registration-status'
"$playwright_runner" -s=tp-auth route '**/api/v1/auth/registration-status' --status 200 --content-type application/json --body '{"mode":"open"}'
"$playwright_runner" -s=tp-auth goto http://127.0.0.1:8080/login
"$playwright_runner" -s=tp-auth snapshot
```

open/登录/退出的安全 mock 在交互前安装；以下 payload 与当前前端类型完整对齐，所有 route 在对应场景后逐一 unroute：

```bash
auth_fixture='{"user":{"id":"usr_e2e","username":"e2e-tester","display_name":"验收测试人员","status":"active","must_change_password":false},"role":"tester","roles":["tester"],"projects":[],"extra_tool_grants":[],"platform_permissions":[],"tool_permissions":{"trackevents":["tool.view"]},"permission_version":1,"session_expires_at":"2026-09-06T00:00:00Z"}'
tools_fixture='{"items":[{"id":"trackevents","name":"埋点测试","description":"解析埋点日志","entry_url":"/trackevents/","short_code":"EVENT","icon_key":"event","category":"analysis","features":["事件统计"],"sort_order":10,"access_scope":"public","access_source":"public","project":null,"can_manage":false}]}'
health_fixture='{"tool_id":"trackevents","status":"healthy","checked_at":"2026-08-30T00:00:00Z"}'
"$playwright_runner" -s=tp-auth route '**/api/v1/auth/register' --status 201 --content-type application/json --body "$auth_fixture"
"$playwright_runner" -s=tp-auth route '**/api/v1/auth/login' --status 200 --content-type application/json --body "$auth_fixture"
"$playwright_runner" -s=tp-auth route '**/api/v1/auth/logout' --status 204
"$playwright_runner" -s=tp-auth route '**/api/v1/tools' --status 200 --content-type application/json --body "$tools_fixture"
"$playwright_runner" -s=tp-auth route '**/api/v1/tools/*/health' --status 200 --content-type application/json --body "$health_fixture"
```

open 注册成功流程在填写前再 route `/api/v1/auth/register` 为 201 的完整 AuthState fixture、route `/api/v1/tools` 为只含一个公共工具的完整 ToolListResponse fixture；断言工作台只显示该公共工具。校验失败/清密用例把 register route 设为 422/409/429/503 对应稳定错误体；会话过期用例把 `/api/v1/tools` route 设为 `401 {"code":"AUTH_REQUIRED","message":"需要登录"}`。登录/退出场景还必须分别 route `/api/v1/auth/login` 为 200 AuthState、`/api/v1/auth/logout` 为 204，并在场景结束后 unroute，不能让浏览器向共享 dev 发送任何写请求。本次浏览器清单不执行改密、会话撤销或其他写操作。fixture 复用 `frontend/src/App.test.tsx` 的完整类型结构并作为命令中的 JSON body 传入，不用省略字段的伪响应。每组场景完成后 `unroute`，模式切换后都用 `goto` 触发整页重新挂载。

覆盖：

1. open 时注册链接可见，disabled/invite 时隐藏且 `/register` 直达显示关闭态；
2. 6/18 code point 注册成功，5/19 和确认不一致不发请求；
3. 注册失败清空密码、保留身份字段；
4. 注册成功直接进入工作台并只看到有权公共工具；
5. logout 后登录并回到合法 `next`，外部 `next` 被拒绝；
6. 模拟任意受保护 API 的 `AUTH_REQUIRED`，只出现一次提示；
7. Tab/Shift+Tab/Enter、错误 alert、焦点可见；
8. 1280×720 和 1440×900 下无横向溢出。

截图保存为：

```text
output/playwright/login-open.png
output/playwright/register-default.png
output/playwright/register-validation.png
output/playwright/register-disabled.png
output/playwright/register-invite-disabled.png
output/playwright/session-expired.png
```

运行时使用 snapshot 返回的实时 ref，不在计划中写死 ref。完成后执行：

```bash
"$playwright_runner" -s=tp-auth close
```

- [ ] **Step 5: 时间、Cookie 与安全证据**

在后端自动化报告中确认：

- 201/200 的 `Set-Cookie` 均有 `Max-Age=604800`、`HttpOnly`（Session）、`SameSite=Lax`；
- HTTPS 环境为 Secure；当前 HTTP 环境有明确风险审批记录；
- T+6d23h/T+7d、touch、存量 Session、存量长密码用例通过；
- 429/503、一次熔断告警、审计分类、敏感数据扫描通过；
- 新用户 role/status/项目/额外授权断言通过。

- [ ] **Step 6: 对照 PRD AC-01 至 AC-31 逐项签收**

把每个 AC 映射到自动化测试名或 Playwright 截图；没有证据的条目不能标记完成。

- [ ] **Step 7: 最终提交前检查**

```bash
cd /Users/admin/Testproject/test-platform
git status --short
git diff --check
git diff --stat
```

Expected: 无空白错误；变更只覆盖第 9 节文件；`output/playwright/` 不进入提交。

---

## 11. PRD 验收覆盖矩阵

| PRD 范围 | 设计/任务 | 主要证据 |
|---|---|---|
| AC-01/AC-02 注册入口与直达 | Task 3、6、7、10 | 前端模式测试、Playwright open/disabled 截图 |
| AC-03/AC-08/AC-09/AC-10/AC-11/AC-12/AC-31 注册业务与权限 | Task 3、7 | 后端注册测试、前端表单测试、工作台工具请求 |
| AC-04/AC-05/AC-06/AC-07 新密码边界 | Task 2、7、8 | Python/TypeScript 5/6/18/19 code point 测试 |
| AC-13/AC-14/AC-15 登录 | Task 2、6 | 存量长密码、登录限流、next 测试 |
| AC-16/AC-17/AC-18/AC-19 7 天与恢复 | Task 5、6、10 | 注入时钟、Cookie、浏览器恢复测试 |
| AC-20/AC-21/AC-22/AC-23 提前失效与 CSRF | Task 5、10 | 既有 Session/权限回归 |
| AC-24 存量长密码 | Task 2 | 直接旧 Argon2 哈希登录测试 |
| AC-25 敏感信息 | Task 4、6、7、10 | 数据库/日志/审计/Storage 断言 |
| AC-26 注册关闭 | Task 3、4、6 | 503、无 User/Session/授权业务写入；保留防滥用计数与安全审计；前端 fail-closed |
| AC-27 来源限流 | Task 1、4、10 | SQLite 验证第 6 次 429/15 分钟恢复；一次性 PostgreSQL 验证同 IP 并发无丢增量；Nginx 静态覆盖测试 + 后端未标记请求测试 + API 无宿主端口共同证明 Header 信任边界 |
| AC-28 全局熔断 | Task 1、4 | SQLite 验证第 101 次 503/恢复与单次告警；一次性 PostgreSQL 验证全局并发无丢增量、无唯一键 500 |
| AC-29 重复用户名安全 | Task 3、4 | 409 通用语义与内部区分审计 |
| AC-30 注册失败审计 | Task 4 | validation/unknown/rate/circuit 事件测试 |

---

## 12. 实施完成定义

只有同时满足以下条件，才可以声称功能完成：

- 第 10 节全部验证命令有本次运行输出且成功；
- PRD AC-01 至 AC-31 均有自动化或真实浏览器证据；
- 本功能没有新增 Alembic revision；生产 `ALEMBIC_TARGET` 继续遵守既有 0019/0020 权限发布门禁，注册发布不得擅自推进 migration target；
- 当前 HTTP 生产若仍使用 `COOKIE_SECURE=false`，发布审批明确记录 7 天 Cookie 风险；
- 没有覆盖当前工作树的用户改动，没有无关重构或新增依赖；
- 日志、审计、数据库、响应和浏览器 Storage 的敏感数据检查通过；
- 实施代码经过 `superpowers:requesting-code-review` 复核，并在最终结论前使用 `superpowers:verification-before-completion` 检查最新证据。

## 13. 执行方式

1. **Subagent-Driven（推荐）**：在当前任务中按 Task 1–10 拆分独立文件边界，主智能体负责集成、迁移顺序和最终回归；同一核心文件（尤其 `App.tsx`、`auth.py`、`config.py`）必须串行修改。
2. **Inline Execution**：由一个实现会话严格按 Task 0–10 顺序执行，每个任务完成测试和检查点后再进入下一项。

两种方式都必须先处理 Task 0 的脏工作树与迁移 head 检查，不能直接从编码步骤开始。
