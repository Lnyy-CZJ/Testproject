# 平台用户级凭证与 LLM 配置隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended when file boundaries are independent) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将业务凭证、账号密码、Token 与完整 LLM 连接配置从环境级共享改为登录用户级隔离，并把本机、线上现有值安全迁移给各自环境的 `admin` 用户。

**Architecture:** 保留现有全局配置发布链，增加用户私有覆盖层；浏览器请求经 Nginx 获取平台签名的用户上下文，工具再用 Tool Client 身份兑换短期 Runtime Context，平台据此只解析该用户的数据。旧全局凭证数据保留为只读回滚材料，但新解析器不再把它作为普通用户的兜底值。

**Tech Stack:** FastAPI、SQLAlchemy 2、PostgreSQL、Alembic、AES-GCM Secret Store、React 19、TypeScript、Vite、Vitest、Pytest、Nginx、Docker Compose。

**Spec:** `test-platform/docs/PRD-平台用户级凭证与LLM配置隔离-V1.0.md`、`test-platform/docs/DEV_DESIGN-平台用户级凭证与LLM配置隔离-V1.0.md`

---

## 0. 执行约束与成功标准

### 0.1 必须遵守的实现约束

- [ ] 每个任务先补充会失败的测试，再做最小实现，再执行聚焦回归。
- [ ] 仅修改任务列出的文件；如果发现必须扩大范围，先更新本计划并说明原因。
- [ ] 新增或修改的模块、公共接口、业务规则、状态迁移和安全边界使用清晰的中文注释说明“为什么”。
- [ ] 不引入新的加密库；用户上下文签名使用 Python 标准库 `hmac`、`hashlib`、`base64`。
- [ ] 任何 API、日志、审计事件和管理页面都不得回显明文 Secret。
- [ ] 不允许客户端提交 `user_id` 决定数据归属；归属只能来自已验证会话或 Runtime Context。
- [ ] 用户私有项缺失时必须明确失败，不得回退旧环境级凭证或环境变量。
- [ ] 所有数据库迁移先在本机 `dev` 验证，再以同一版本部署到线上 `prod`；两个环境分别使用自己的 KEK 与用户上下文签名密钥。
- [ ] 每个任务末尾的 `git commit` 是建议检查点；只有在当前工作区与用户现有改动不冲突且得到既有工作流允许时才执行。

### 0.2 可验证成功标准

- [ ] 同一工具、同一环境中，用户 A 与用户 B 配置不同 Token 后，运行时分别得到自己的值。
- [ ] 用户 A 无法列出、读取、更新、验证或间接使用用户 B 的凭证与 LLM Profile。
- [ ] 普通配置仍按现有环境级发布机制对所有用户生效。
- [ ] 未配置私有凭证或 LLM 的用户得到稳定错误码和配置引导，不会拿到 `admin` 或旧全局值。
- [ ] 本机与线上现有用户型数据只迁移到各自数据库中的有效 `admin`；迁移可 dry-run、可重复、冲突即停止。
- [ ] 伪造 `X-Platform-User-ID`、跨工具 Runtime Context、过期/撤销会话和旧权限版本均无法解析 Secret。
- [ ] 后端、前端及五个接入工具的相关测试通过，最终双用户隔离哨兵测试通过。

## 1. 实施顺序与发布门禁

严格按以下顺序实施：

1. 数据结构和分类字段。
2. `admin` 数据迁移工具。
3. 用户自助凭证和 LLM API。
4. 签名用户上下文与 Runtime Context。
5. 用户级运行时解析和 Credential Agent。
6. 前端自助配置页。
7. 各工具接入。
8. 灰度开关、双用户验收、生产迁移。

在任务 1～7 完成前，`PERSONAL_CREDENTIALS_ENABLED=false`、`PERSONAL_CREDENTIALS_WRITE_ENABLED=false`。任务 8 验证通过后先打开写入，再完成 `admin` 迁移，最后打开运行时读取。

---

## Task 1：建立用户私有数据模型与配置分类

**Files:**

- Create: `test-platform/backend/alembic/versions/20260823_0018_add_user_credential_scopes.py`
- Modify: `test-platform/backend/app/models/configuration.py`
- Modify: `test-platform/backend/app/models/identity.py`
- Modify: `test-platform/backend/app/models/llm.py`
- Modify: `test-platform/backend/app/models/__init__.py`
- Modify: `test-platform/backend/app/db/base.py`
- Modify: `test-platform/backend/app/schemas/configuration.py`
- Modify: `test-platform/backend/app/schemas/llm.py`
- Test: `test-platform/backend/tests/test_migrations.py`
- Test: `test-platform/backend/tests/test_phase2.py`

### Step 1：先写会失败的迁移与约束测试

- [ ] 在 `test_migrations.py` 增加 `test_user_scope_migration_builds_isolated_tables_and_constraints`，升级到 `head` 后断言存在：
  - `config_definitions.value_scope`
  - `config_definitions.credential_provider_type`
  - `user_credentials`
  - `user_credential_items`
  - `user_llm_bindings`
  - `runtime_contexts`
  - `llm_profiles.owner_user_id`
- [ ] 断言数据库唯一约束分别覆盖：
  - `user_credentials(user_id, tool_id, environment_id, provider_type)`
  - `user_credential_items(credential_id, credential_version, key)`
  - `user_llm_bindings(user_id, binding_id)`
  - `llm_profiles(owner_user_id, name_normalized)`
- [ ] 增加 `test_user_scope_migration_downgrade_is_scoped`，确认只回退本版本新增对象，不删除原有 `credentials`、`credential_items`、`config_releases`、`secrets`。
- [ ] 在 `test_phase2.py` 增加模型约束测试：同一用户同一 Provider 重复插入失败，不同用户可各自插入。

运行：

```bash
cd test-platform/backend
pytest tests/test_migrations.py tests/test_phase2.py -q
```

预期：测试因列、表或模型尚不存在而失败；不得出现测试收集错误。

### Step 2：实现最小数据结构

- [ ] 给 `ConfigDefinition` 增加：
  - `value_scope: String(16)`，非空，服务端默认 `system`，只允许 `system|user`。
  - `credential_provider_type: String(64) | None`，只在 `value_scope=user` 时使用。
- [ ] 新增 `UserCredential`，ID 前缀 `ucred_`，包含 `user_id`、`tool_id`、`environment_id`、`provider_type`、`status`、`current_version`、过期时间、租约字段和审计时间。
- [ ] 新增 `UserCredentialItem`，每个版本的键只能关联一个 `secret_version_id` 或一个受允许的非敏感 `value`；数据库约束禁止二者同时为空或同时有值。
- [ ] 新增 `UserLlmBinding`，ID 前缀 `ullmb_`，以 `binding_id` 引用现有工具能力目录；其发布数据仍写入 `config_releases`，`owner_type=user_llm_binding`。
- [ ] 给 `LlmProfile` 增加 `owner_user_id`，所有新 Profile 必须有所有者。
- [ ] 新增 `RuntimeContext`，包含 `user_id`、`session_id`、`permission_version`、`tool_id`、`environment_id`、`status`、可选资源关联和过期时间；不得存储明文签名 Token。
- [ ] 为所有外键定义明确的删除策略：用户删除时私有绑定、Runtime Context 级联删除；Secret 与版本沿用现有 Secret Store 生命周期。
- [ ] 在迁移中只创建结构、系统分类元数据和权限元数据，不解密、不复制真实 Secret。
- [ ] 给现有配置定义回填明确分类：普通项为 `system`；设计文档第 7 节列出的登录态、账号密码、Token、用户型 LLM Key 为 `user`。

### Step 3：验证迁移可逆性与模型约束

```bash
cd test-platform/backend
pytest tests/test_migrations.py tests/test_phase2.py -q
alembic upgrade head
alembic downgrade 20260821_0017
alembic upgrade head
```

预期：测试通过；升级、单版本回退、再次升级均成功。

### Step 4：建议提交检查点

```bash
git add test-platform/backend/alembic/versions/20260823_0018_add_user_credential_scopes.py \
  test-platform/backend/app/models/configuration.py \
  test-platform/backend/app/models/identity.py \
  test-platform/backend/app/models/llm.py \
  test-platform/backend/app/models/__init__.py \
  test-platform/backend/app/db/base.py \
  test-platform/backend/app/schemas/configuration.py \
  test-platform/backend/app/schemas/llm.py \
  test-platform/backend/tests/test_migrations.py \
  test-platform/backend/tests/test_phase2.py
git commit -m "feat(platform): add user-scoped credential models"
```

---

## Task 2：实现现有数据归属 `admin` 的安全迁移命令

**Files:**

- Create: `test-platform/backend/app/migrate_personal_credentials.py`
- Modify: `test-platform/backend/app/core/config.py`
- Modify: `test-platform/backend/app/services/secret_store.py`
- Test: `test-platform/backend/tests/test_migrations.py`
- Test: `test-platform/backend/tests/test_llm.py`

### Step 1：先写 dry-run、幂等和冲突测试

- [ ] 构造包含旧全局 Gateway/Admin Credential、用户型 Config Release、LLM Profile 和 LLM Binding 的数据库。
- [ ] 测试 dry-run：输出将创建/复用/跳过/冲突的数量，数据库行数和 SecretVersion 数量均不变化，输出不包含明文。
- [ ] 测试 apply：只为有效用户名 `admin` 创建用户凭证和 LLM 绑定；普通系统配置不复制。
- [ ] 测试重复 apply：第二次不创建新 SecretVersion，结果为幂等跳过。
- [ ] 测试冲突：目标 `admin` 已有不同值时命令返回非零，不覆盖目标值。
- [ ] 测试前置条件：没有有效 `admin`、存在多个规范化用户名为 `admin` 的有效用户、环境不匹配时都拒绝执行。

运行：

```bash
cd test-platform/backend
pytest tests/test_migrations.py tests/test_llm.py -q
```

预期：新测试因迁移入口不存在而失败。

### Step 2：实现可审计迁移入口

- [ ] CLI 固定提供以下接口：

```bash
python -m app.migrate_personal_credentials \
  --environment dev \
  --admin-username admin \
  --dry-run

python -m app.migrate_personal_credentials \
  --environment dev \
  --admin-username admin \
  --apply
```

- [ ] 默认必须是 dry-run；只有显式 `--apply` 才写数据库，两个参数互斥。
- [ ] 校验 CLI 的环境与平台当前 `environment_id` 一致，且只存在一个 `status=active` 的 `admin`。
- [ ] 使用稳定来源标识生成确定性目标关系；源 ID 与目标类型相同的重复迁移直接跳过。
- [ ] Credential 的 Secret 在内存中通过现有 `SecretCipher` 解密，再以 `owner_type=user_credential`、`owner_id=ucred_*` 加密成新版本；明文不写日志、不落临时文件。
- [ ] 现有全局 LLM Profile 归属设置为 `admin`；为 `admin` 创建 `UserLlmBinding` 并复制已激活发布，旧全局 Binding 与 Release 原样保留。
- [ ] 输出只包含源对象 ID、目标对象 ID、键名、版本号和动作，不包含 Secret 值。
- [ ] 一旦发现目标已有不同指纹、缺失 KEK、无法解密、数据分类未知，整个事务回滚并返回非零。

### Step 3：验证迁移行为

```bash
cd test-platform/backend
pytest tests/test_migrations.py tests/test_llm.py -q
python -m app.migrate_personal_credentials --help
```

预期：聚焦测试通过；帮助文本明确 dry-run 默认行为和不可覆盖规则。

### Step 4：建议提交检查点

```bash
git add test-platform/backend/app/migrate_personal_credentials.py \
  test-platform/backend/app/core/config.py \
  test-platform/backend/app/services/secret_store.py \
  test-platform/backend/tests/test_migrations.py \
  test-platform/backend/tests/test_llm.py
git commit -m "feat(platform): add safe admin credential migration"
```

---

## Task 3：实现当前用户的凭证自助 API

**Files:**

- Modify: `test-platform/backend/app/api/configuration.py`
- Modify: `test-platform/backend/app/schemas/configuration.py`
- Modify: `test-platform/backend/app/services/secret_store.py`
- Modify: `test-platform/backend/app/core/errors.py`
- Modify: `test-platform/backend/app/main.py`
- Test: `test-platform/backend/tests/test_phase2.py`
- Test: `test-platform/backend/tests/test_api.py`

### Step 1：先写双用户 API 隔离测试

- [ ] 为 `admin` 和 `member` 建立独立登录会话。
- [ ] `PUT /api/v1/me/credentials/truthy-search/gateway_session` 分别写入不同 Token，body 固定为：

```json
{
  "environment_id": "dev",
  "expected_version": 0,
  "values": {
    "AUTH_TOKEN": "user-specific-access-token",
    "REFRESH_TOKEN": "user-specific-refresh-token",
    "EXPIRES_TIME": "1787462400000",
    "DEVICE_ID": "user-specific-device"
  }
}
```

- [ ] 断言响应只返回键名、`configured`、版本、状态和掩码摘要，不返回输入值。
- [ ] `GET /api/v1/me/credentials?environment_id=dev` 只返回当前用户对象，响应体中不得出现另一用户的凭证 ID。
- [ ] 当前用户用另一用户的 `credential_id` 调用验证接口得到 `404 NOT_FOUND`，避免泄露对象是否存在。
- [ ] 未声明为 `user` 或不属于该 Provider 的键返回 `403 CREDENTIAL_SCOPE_MISMATCH`。
- [ ] 首次创建缺少必填键时返回字段级校验错误；更新时未提交的既有键沿用当前版本，且 `expected_version` 不匹配时返回 `409 VERSION_CONFLICT`。

运行：

```bash
cd test-platform/backend
pytest tests/test_phase2.py tests/test_api.py -q
```

预期：路由不存在或返回旧全局对象，测试失败。

### Step 2：实现自助 API 与所有权查询

- [ ] 实现以下接口：
  - `GET /api/v1/me/credentials?environment_id={dev|prod}`
  - `PUT /api/v1/me/credentials/{tool_id}/{provider_type}`
  - `POST /api/v1/me/credentials/{credential_id}/validate`
- [ ] 所有查询都以 `current_auth_context.user.id` 为首个过滤条件；请求 schema 不接受 `user_id`。
- [ ] 使用配置定义中的 `credential_provider_type` 生成允许键清单，拒绝客户端自定义 Secret 键。
- [ ] 更新采用单事务版本化写入：建立新的 SecretVersion 与 UserCredentialItem，全部成功后再更新 `current_version`。
- [ ] 验证接口复用现有 Provider 校验能力；如果 Provider 不支持在线校验，返回 `validation_state=unsupported`，不伪造成功。
- [ ] 审计事件记录用户、工具、环境、Provider、版本和结果，不记录值。
- [ ] 响应头保持 `Cache-Control: no-store`。

### Step 3：验证 API 与明文防泄漏

```bash
cd test-platform/backend
pytest tests/test_phase2.py tests/test_api.py -q
```

并在测试中对序列化响应、捕获日志和审计 payload 执行明文 Token 否定断言。

### Step 4：建议提交检查点

```bash
git add test-platform/backend/app/api/configuration.py \
  test-platform/backend/app/schemas/configuration.py \
  test-platform/backend/app/services/secret_store.py \
  test-platform/backend/app/core/errors.py \
  test-platform/backend/app/main.py \
  test-platform/backend/tests/test_phase2.py \
  test-platform/backend/tests/test_api.py
git commit -m "feat(platform): add self-service personal credentials"
```

---

## Task 4：实现用户自有 LLM Profile 与能力绑定

**Files:**

- Modify: `test-platform/backend/app/api/llm.py`
- Modify: `test-platform/backend/app/schemas/llm.py`
- Modify: `test-platform/backend/app/services/llm.py`
- Modify: `test-platform/backend/app/services/secret_store.py`
- Test: `test-platform/backend/tests/test_llm.py`
- Test: `test-platform/backend/tests/test_phase2.py`

### Step 1：先写 Profile 所有权与绑定隔离测试

- [ ] 两个用户可创建同名 Profile；同一用户的规范化名称不可重复。
- [ ] Profile 创建/更新 body 包含 `provider`、`base_url`、`model`、`api_key` 和允许的非敏感参数；响应不返回 `api_key`。
- [ ] 用户 A 不能查看、更新、删除或绑定用户 B 的 Profile，统一返回 `404 NOT_FOUND`。
- [ ] `PUT /api/v1/me/llm/bindings/{binding_id}` 只能绑定当前用户自己的 Profile，且环境必须匹配。
- [ ] 没有个人绑定时，解析返回 `PERSONAL_LLM_NOT_CONFIGURED`，不得回退全局 Binding。
- [ ] 同一工具能力下两用户解析出的 `profile_id`、model、base URL 和 API Key 均分别来自本人。

运行：

```bash
cd test-platform/backend
pytest tests/test_llm.py tests/test_phase2.py -q
```

预期：所有权与个人绑定测试失败。

### Step 2：实现个人 LLM API

- [ ] 实现以下接口：
  - `GET /api/v1/me/llm/profiles?environment_id={dev|prod}`
  - `POST /api/v1/me/llm/profiles`
  - `PATCH /api/v1/me/llm/profiles/{profile_id}`
  - `POST /api/v1/me/llm/profiles/{profile_id}/archive`
  - `POST /api/v1/me/llm/profiles/{profile_id}/restore`
  - `GET /api/v1/me/llm/bindings?environment_id={dev|prod}`
  - `PUT /api/v1/me/llm/bindings/{binding_id}`
  - `POST /api/v1/me/llm/test-connection`
- [ ] Profile API Key 继续写入 Secret Store，`owner_type=llm_profile`；所有权由 `llm_profiles.owner_user_id` 决定。
- [ ] Binding 的可选目录仍由平台管理；用户只能从现有启用的工具能力中选择，不可创建任意 capability。
- [ ] 更新 Binding 时发布不可变 Config Release，并激活到 `owner_type=user_llm_binding`。
- [ ] 归档被绑定的 Profile 返回 `409 LLM_PROFILE_IN_USE`，要求先解绑，避免静默破坏运行任务。
- [ ] `resolve_llm_snapshot` 增加必填 `user_id`，只接受属于该用户的 `UserLlmBinding` 与 Profile。

### Step 3：验证 LLM 解析无全局兜底

```bash
cd test-platform/backend
pytest tests/test_llm.py tests/test_phase2.py -q
```

预期：测试通过；专门放入旧全局 API Key 哨兵值后，普通用户响应和内部快照中均找不到该哨兵。

### Step 4：建议提交检查点

```bash
git add test-platform/backend/app/api/llm.py \
  test-platform/backend/app/schemas/llm.py \
  test-platform/backend/app/services/llm.py \
  test-platform/backend/app/services/secret_store.py \
  test-platform/backend/tests/test_llm.py \
  test-platform/backend/tests/test_phase2.py
git commit -m "feat(platform): isolate llm profiles and bindings by user"
```

---

## Task 5：建立签名用户上下文和 Runtime Context 信任链

**Files:**

- Modify: `test-platform/backend/app/core/config.py`
- Modify: `test-platform/backend/app/core/security.py`
- Modify: `test-platform/backend/app/api/internal.py`
- Modify: `test-platform/backend/app/schemas/internal.py`
- Modify: `test-platform/backend/app/services/auth.py`
- Modify: `test-platform/nginx/nginx.conf`
- Modify: `test-platform/docker-compose.yml`
- Modify: `test-platform/docker-compose.local-build.yml`
- Modify: `test-platform/docker-compose.prod.yml`
- Test: `test-platform/backend/tests/test_phase2.py`
- Test: `test-platform/backend/tests/test_api.py`

### Step 1：先写签名、篡改、重放边界测试

- [ ] 测试 `/api/v1/internal/authorize` 在有效浏览器会话和授权工具路径下返回 `X-Platform-User-Context`。
- [ ] 解码后 claims 精确包含 `v`、`sid`、`uid`、`pv`、`tid`、`env`、`iat`、`exp`、`nonce`；有效期不超过 5 分钟。
- [ ] 修改 payload 任意字节、修改签名、跨工具、跨环境或过期时，兑换接口返回 `RUNTIME_CONTEXT_INVALID` 或 `RUNTIME_CONTEXT_EXPIRED`。
- [ ] 只有同时持有正确 Tool Client Bearer Token 和有效签名上下文才能调用：
  `POST /api/v1/internal/tools/{tool_id}/runtime-contexts`。
- [ ] 创建后撤销 Session 或增加 `user.permission_version`，既有 Runtime Context 立即失效。
- [ ] 直接向工具发送伪造 `X-Platform-User-ID` 不影响签名上下文；Nginx 必须覆盖外部同名 Header。

运行：

```bash
cd test-platform/backend
pytest tests/test_phase2.py tests/test_api.py -q
```

预期：缺少签名函数、兑换路由和 Nginx 变量，测试失败。

### Step 2：实现 HMAC 签名与验证

- [ ] 在配置中增加：
  - `USER_CONTEXT_SIGNING_KEY_FILE`
  - `USER_CONTEXT_TTL_SECONDS=300`
  - `RUNTIME_CONTEXT_TTL_SECONDS=86400`
- [ ] 启动时读取独立签名密钥文件；缺失、权限错误、长度不足 32 字节时平台拒绝启动。
- [ ] 使用规范 JSON（UTF-8、键排序、无多余空格）与 HMAC-SHA256，Token 格式为 `base64url(payload).base64url(signature)`。
- [ ] 签名验证使用 `hmac.compare_digest`，并验证版本、时间、工具、环境、Session、用户状态和权限版本。
- [ ] 签名密钥不得复用 Secret KEK，不得进入数据库或 API 响应。

### Step 3：扩展 authorize 和 Nginx 注入

- [ ] `/internal/authorize` 继续返回现有身份 Header，同时返回签名的 `X-Platform-User-Context`。
- [ ] Nginx 新增：

```nginx
auth_request_set $platform_user_context $upstream_http_x_platform_user_context;
proxy_set_header X-Platform-User-Context $platform_user_context;
```

- [ ] 对所有受保护工具 location 都注入该 Header；先将客户端传入的同名 Header 覆盖为空，再设置平台值。
- [ ] Header 只传给对应工具，不暴露给浏览器响应。

### Step 4：实现 Runtime Context 兑换与校验

- [ ] 从 `X-Platform-User-Context` 请求 Header 读取签名上下文；body 必须提供白名单内的 `resource_type` 和非空 `resource_id`，不接受 `user_id`、`tool_id`、`environment_id` 覆盖 claims。
- [ ] 响应 schema：`runtime_context_id`、`tool_id`、`environment_id`、`expires_at`；不回显签名 Token。
- [ ] 持久化签名中的用户、Session、权限版本、工具、环境和资源关联，默认最长 24 小时。
- [ ] 每次使用 Runtime Context 都重新校验：状态 active、未过期、Session 未撤销、用户 active、权限版本相同、Tool Client scope 相同。

### Step 5：验证信任链

```bash
cd test-platform/backend
pytest tests/test_phase2.py tests/test_api.py -q
nginx -t -c "$(pwd)/../nginx/nginx.conf"
```

若宿主机没有 Nginx，则使用项目 Nginx 镜像执行等价的 `nginx -t`；不得把“未安装”记作通过。

### Step 6：建议提交检查点

```bash
git add test-platform/backend/app/core/config.py \
  test-platform/backend/app/core/security.py \
  test-platform/backend/app/api/internal.py \
  test-platform/backend/app/schemas/internal.py \
  test-platform/backend/app/services/auth.py \
  test-platform/nginx/nginx.conf \
  test-platform/docker-compose.yml \
  test-platform/docker-compose.local-build.yml \
  test-platform/docker-compose.prod.yml \
  test-platform/backend/tests/test_phase2.py \
  test-platform/backend/tests/test_api.py
git commit -m "feat(platform): add signed runtime user context"
```

---

## Task 6：把内部运行时解析切换到当前用户私有覆盖层

**Files:**

- Modify: `test-platform/backend/app/api/internal.py`
- Modify: `test-platform/backend/app/schemas/internal.py`
- Modify: `test-platform/backend/app/services/llm.py`
- Modify: `test-platform/backend/app/services/secret_store.py`
- Modify: `test-platform/backend/app/core/errors.py`
- Test: `test-platform/backend/tests/test_phase2.py`
- Test: `test-platform/backend/tests/test_llm.py`

### Step 1：先写运行时解析矩阵测试

- [ ] `include_secrets=false` 且不请求 LLM 时，无 Runtime Context 仍可读取全局普通配置元数据。
- [ ] `include_secrets=true` 或传入 `llm_capability` 时，缺少 Runtime Context 返回 `403 RUNTIME_CONTEXT_REQUIRED`。
- [ ] Runtime Context 与 URL 的 `tool_id`、查询环境或 Tool Client 不一致时返回 `403 RUNTIME_CONTEXT_INVALID`。
- [ ] 用户 A、B 分别请求相同工具/环境，响应中的 `credentials.primary.items` 和 `llm` 快照严格不同。
- [ ] 用户未配置必需 Provider 返回 `409 PERSONAL_CREDENTIAL_NOT_CONFIGURED`；未配置 LLM 返回 `409 PERSONAL_LLM_NOT_CONFIGURED`。
- [ ] 旧全局凭证中放入 `legacy-global-secret-sentinel`，任何启用个人解析的请求均不能得到该值。
- [ ] 创建任务只规划非敏感版本引用；用户在执行物化前登出时返回 `RUNTIME_CONTEXT_INVALID`，不加载 Secret。
- [ ] 物化请求中的版本不属于当前用户、工具或环境时返回 `409 RUNTIME_SNAPSHOT_INVALID`，不切换到最新版本。
- [ ] `credential-status` 和会话写回只能更新 Runtime Context 所属用户的 `UserCredential`；传入另一用户 ID 返回 `404`。

运行：

```bash
cd test-platform/backend
pytest tests/test_phase2.py tests/test_llm.py -q
```

预期：旧解析器仍返回全局值，测试失败。

### Step 2：实现确定的分层解析规则

- [ ] `runtime-config` 增加查询参数 `runtime_context_id`。
- [ ] 先加载所有 `value_scope=system` 的已激活全局普通配置。
- [ ] 对 `value_scope=user` 的定义，不读取全局 Release 值；只从 Runtime Context 对应用户的 UserCredential、UserLlmBinding 和 Profile 解析。
- [ ] 用户私有项不能覆盖 `system` 项；客户端提交同名项在写入 API 已被拒绝，运行时再做防御性检查。
- [ ] 返回快照包含 `user_scope_id` 的不可逆摘要或用户 ID 仅供内部追踪，但不得向不需要它的工具页面展示用户名。
- [ ] 保持任务快照不可变：工具创建任务时以 `include_secrets=false` 规划并保存 `snapshot_selector`，其中只有 `release_id`、个人 Credential ID/Version、个人 LLM Profile/Binding Release ID 和 Secret Version ID，不保存明文。
- [ ] 增加 `POST /api/v1/internal/tools/{tool_id}/runtime-config/materialize`：任务执行开始时携带 Runtime Context 与 `snapshot_selector`，服务端重新按 Context 所属用户校验并解密精确历史版本。
- [ ] 物化前 Session 撤销、权限版本变化或 Context 过期必须失败；物化成功后 Secret 只保存在执行进程内存，当前任务不受后续轮换影响，新任务选择新版本。

### Step 3：修改状态上报与会话写回

- [ ] `POST /api/v1/internal/tools/{tool_id}/credential-status` 请求增加 `runtime_context_id`，服务端从 Context 得到 `user_id`。
- [ ] 新路径为：
  `PUT /api/v1/internal/tools/{tool_id}/user-credentials/{credential_id}/session`。
- [ ] 保留旧全局写回路由但在个人模式下返回 `410 LEGACY_CREDENTIAL_WRITE_DISABLED`；不得同时写新旧两套数据。
- [ ] 乐观并发以个人 Credential 的 `current_version` 为基准，冲突返回 `409 VERSION_CONFLICT`。

### Step 4：验证聚焦回归

```bash
cd test-platform/backend
pytest tests/test_phase2.py tests/test_llm.py tests/test_api.py -q
```

### Step 5：建议提交检查点

```bash
git add test-platform/backend/app/api/internal.py \
  test-platform/backend/app/schemas/internal.py \
  test-platform/backend/app/services/llm.py \
  test-platform/backend/app/services/secret_store.py \
  test-platform/backend/app/core/errors.py \
  test-platform/backend/tests/test_phase2.py \
  test-platform/backend/tests/test_llm.py \
  test-platform/backend/tests/test_api.py
git commit -m "feat(platform): resolve runtime secrets by authenticated user"
```

---

## Task 7：让 Credential Agent 按用户维护登录态

**Files:**

- Modify: `test-platform/backend/app/jobs/credential_agent.py`
- Modify: `test-platform/backend/app/models/configuration.py`
- Modify: `test-platform/backend/app/api/internal.py`
- Test: `test-platform/backend/tests/test_phase2.py`

### Step 1：先写用户级租约和刷新测试

- [ ] 同一 Provider 的两个用户可分别领取租约，互不阻塞。
- [ ] 同一用户同一 Credential 只能有一个有效租约。
- [ ] 刷新用户 A 的 Gateway Session 只增加 A 的版本，不改变 B 和旧全局 Credential。
- [ ] 刷新失败只将 A 标记为 `degraded|invalid`，不得影响其他用户状态。
- [ ] Agent 日志与审计事件不包含 Access Token、Refresh Token、密码或完整 Cookie/Header JSON。

运行：

```bash
cd test-platform/backend
pytest tests/test_phase2.py -q
```

预期：旧 Agent 只扫描全局 `credentials`，测试失败。

### Step 2：切换 Agent 扫描和租约主键

- [ ] 个人模式启用时只扫描 `user_credentials`，租约作用域为个人 Credential ID。
- [ ] Provider 适配器输入增加 `user_id` 仅用于审计关联，不允许 Provider 自行选择其他用户。
- [ ] 刷新成功通过同一事务写入新 SecretVersion、UserCredentialItem 和 `current_version`。
- [ ] 个人模式未启用时保持现有全局扫描，支持发布前兼容；启用后禁止双写。
- [ ] Agent 的状态上报、重试、退避和过期判断复用现有逻辑，不增加新的后台系统。

### Step 3：验证 Agent 回归

```bash
cd test-platform/backend
pytest tests/test_phase2.py -q
```

### Step 4：建议提交检查点

```bash
git add test-platform/backend/app/jobs/credential_agent.py \
  test-platform/backend/app/models/configuration.py \
  test-platform/backend/app/api/internal.py \
  test-platform/backend/tests/test_phase2.py
git commit -m "feat(platform): refresh credentials per user"
```

---

## Task 8：改造前端为“我的凭证 / 我的 LLM”并增加管理员就绪度

**Files:**

- Modify: `test-platform/frontend/src/App.tsx`
- Modify: `test-platform/frontend/src/App.test.tsx`
- Modify: `test-platform/frontend/src/api/client.ts`
- Modify: `test-platform/frontend/src/types/platform.ts`
- Modify: `test-platform/frontend/src/app.css`
- Modify: `test-platform/backend/app/api/admin.py`
- Modify: `test-platform/backend/app/schemas/admin.py`
- Modify: `test-platform/backend/app/core/permissions.py`
- Test: `test-platform/backend/tests/test_phase2.py`

### Step 1：先写前端与管理员 API 测试

- [ ] 普通用户导航显示“我的凭证”“我的 LLM”，不显示全局 Secret 编辑入口。
- [ ] 凭证页按环境和工具展示 Provider 状态、配置键、版本、更新时间；密码框永不回填。
- [ ] 保存成功后输入框清空，只显示“已配置”和掩码摘要。
- [ ] LLM 页只能选择本人 Profile，支持为每个工具能力绑定。
- [ ] 缺少配置时展示后端错误码对应的可操作引导，不显示后端栈或对象 ID。
- [ ] 管理员就绪度页只展示用户、环境、工具、Provider/能力的 `configured|missing|invalid|expiring` 元数据，不提供查看明文或代改入口。
- [ ] 非管理员访问 `GET /api/v1/admin/credential-readiness` 返回 403。

运行：

```bash
cd test-platform/frontend
npm test -- App.test.tsx

cd ../backend
pytest tests/test_phase2.py -q
```

预期：导航、页面和就绪度接口尚不存在，测试失败。

### Step 2：实现用户自助页面

- [ ] 复用现有 `App.tsx` 页面与路由组织，不引入新状态管理依赖。
- [ ] 将旧 Secrets/Credentials/LLM 管理入口按角色拆分：普通用户进入 `me` API；管理员保留系统配置发布入口和只读就绪度。
- [ ] API Client 为所有写请求沿用现有 CSRF 机制；错误处理保留稳定错误码。
- [ ] 所有 Secret 输入设置 `autocomplete="new-password"`，响应数据不写入本地存储、URL、浏览器日志。
- [ ] 环境选择只允许后端授权且存在于当前部署的环境命名空间；选择环境不跨数据库访问，生产部署绝不连接本机数据库。

### Step 3：实现管理员就绪度聚合

- [ ] 增加权限 `platform.credential.readiness.view`，仅默认授予平台管理员角色。
- [ ] 后端用聚合查询返回状态元数据，不解密 Secret。
- [ ] 审计管理员查询行为，记录过滤条件和结果数量，不记录键值。

### Step 4：验证前端构建与后端回归

```bash
cd test-platform/frontend
npm test -- App.test.tsx
npm run build

cd ../backend
pytest tests/test_phase2.py tests/test_api.py -q
```

### Step 5：建议提交检查点

```bash
git add test-platform/frontend/src/App.tsx \
  test-platform/frontend/src/App.test.tsx \
  test-platform/frontend/src/api/client.ts \
  test-platform/frontend/src/types/platform.ts \
  test-platform/frontend/src/app.css \
  test-platform/backend/app/api/admin.py \
  test-platform/backend/app/schemas/admin.py \
  test-platform/backend/app/core/permissions.py \
  test-platform/backend/tests/test_phase2.py
git commit -m "feat(platform): add personal credential settings UI"
```

---

## Task 9：接入 Functional Agent 与 API Agent

**Files:**

- Modify: `functional-test-agent/services/common/identity.py`
- Modify: `functional-test-agent/services/common/platform_client.py`
- Modify: `functional-test-agent/services/common/task_manager.py`
- Modify: `functional-test-agent/services/functional_agent/app.py`
- Modify: `functional-test-agent/services/functional_agent/runner.py`
- Test: `functional-test-agent/tests/services/test_web_routes.py`
- Test: `functional-test-agent/tests/services/test_task_runtime.py`
- Modify: `api-test-agent/services/common/identity.py`
- Modify: `api-test-agent/services/common/platform_client.py`
- Modify: `api-test-agent/services/common/task_manager.py`
- Modify: `api-test-agent/services/api_agent/app.py`
- Modify: `api-test-agent/services/api_agent/runner.py`
- Test: `api-test-agent/tests/services/test_web_routes.py`
- Test: `api-test-agent/tests/services/test_llm_runtime.py`

### Step 1：先写请求到任务快照的用户绑定测试

- [ ] 创建任务请求缺少 `X-Platform-User-Context` 时，在平台模式返回明确的 401/409，不读取环境 LLM Key。
- [ ] 工具使用自身 Tool Client Token 兑换 Runtime Context，再请求个人 runtime-config。
- [ ] 两个用户连续创建任务，任务快照中的个人 LLM Profile/Binding 版本不同，且运行结果不会串用。
- [ ] 篡改签名、复用另一工具 Runtime Context、平台不可用时 fail closed；不回退本地 LLM Key。
- [ ] 非平台独立开发模式仍按现有显式本地配置工作，不受平台签名要求影响。

运行：

```bash
cd functional-test-agent
pytest tests/services/test_web_routes.py tests/services/test_task_runtime.py -q

cd ../api-test-agent
pytest tests/services/test_web_routes.py tests/services/test_llm_runtime.py -q
```

预期：客户端未兑换 Runtime Context，测试失败。

### Step 2：实现共享流程但不新增跨仓库依赖

- [ ] 在两个 Agent 各自的 `platform_client.py` 中实现相同协议：接收签名 Header、兑换 Context、携带 `runtime_context_id` 读取快照。
- [ ] `identity.py` 只解析显示身份；不得把 `X-Platform-User-ID` 当成 Secret 解析授权依据。
- [ ] 创建任务路由在写入任务前只执行非敏感规划，把 `snapshot_selector` 写入既有任务快照字段；执行器启动任务时再调用 materialize，验证 Context 后把 Secret 注入一次性进程内存。
- [ ] 原始签名 Header 和 Runtime Context ID 不写业务日志；必要审计只记录 Runtime Context ID 的短摘要。
- [ ] 两个项目复制当前已有的 common 模式，不创建新的共享包或依赖。

### Step 3：验证两个 Agent

```bash
cd functional-test-agent
pytest tests/services/test_web_routes.py tests/services/test_task_runtime.py -q

cd ../api-test-agent
pytest tests/services/test_web_routes.py tests/services/test_llm_runtime.py -q
```

### Step 4：建议提交检查点

```bash
git add functional-test-agent/services/common/identity.py \
  functional-test-agent/services/common/platform_client.py \
  functional-test-agent/services/common/task_manager.py \
  functional-test-agent/services/functional_agent/app.py \
  functional-test-agent/services/functional_agent/runner.py \
  functional-test-agent/tests/services/test_web_routes.py \
  functional-test-agent/tests/services/test_task_runtime.py \
  api-test-agent/services/common/identity.py \
  api-test-agent/services/common/platform_client.py \
  api-test-agent/services/common/task_manager.py \
  api-test-agent/services/api_agent/app.py \
  api-test-agent/services/api_agent/runner.py \
  api-test-agent/tests/services/test_web_routes.py \
  api-test-agent/tests/services/test_llm_runtime.py
git commit -m "feat(agents): bind runtime snapshots to platform user"
```

---

## Task 10：接入 Log Filter、Truthy Search 与 API AutoTest

**Files:**

- Modify: `log_filter_tool/app.py`
- Modify: `log_filter_tool/people_search_ai.py`
- Test: `log_filter_tool/tests/test_people_search_phase4.py`
- Test: `log_filter_tool/tests/test_people_search_phase5.py`
- Modify: `Truthy_Search/web_app.py`
- Modify: `Truthy_Search/search_tool.py`
- Test: `Truthy_Search/tests/test_web_app.py`
- Test: `Truthy_Search/tests/test_search_tool.py`
- Modify: `Truthy_ApiAutoTest2/web/app.py`
- Modify: `Truthy_ApiAutoTest2/web/credentials.py`
- Modify: `Truthy_ApiAutoTest2/utils/custom/runtime_context.py`
- Modify: `Truthy_ApiAutoTest2/test_cases/conftest.py`
- Test: `Truthy_ApiAutoTest2/tests/test_web_routes.py`

### Step 1：先写三个工具的隔离测试

- [ ] Log Filter：两名用户请求 `people-search-summary`，分别兑换 Runtime Context 并得到自己的 LLM 快照；平台模式缺失上下文时不回退 `PEOPLE_SEARCH_ANALYZER_LLM_API_KEY_FILE`。
- [ ] Truthy Search：同一进程连续处理两名用户请求时，Gateway/Admin Provider 的 Token、Device ID、用户名和密码不留在 Flask 全局 config 或模块缓存中。
- [ ] Truthy Search：状态上报带 `runtime_context_id`，只更新当前用户 Provider。
- [ ] API AutoTest：网页检查和测试执行使用当前请求兑换的 Context；登录刷新写回新 `user-credentials` 路由。
- [ ] API AutoTest：两个用户并发执行时，Session Writer 的 `credential_id` 与 Runtime Context 对应，不发生交叉写回。

运行：

```bash
cd log_filter_tool
python3 -m pytest tests/test_people_search_phase4.py tests/test_people_search_phase5.py -q

cd ../Truthy_Search
python3 -m pytest tests/test_web_app.py tests/test_search_tool.py -q

cd ../Truthy_ApiAutoTest2
python3 -m pytest tests/test_web_routes.py -q
```

预期：旧客户端没有 Runtime Context，或把配置保存在进程级状态中，测试失败。

### Step 2：改造 Log Filter

- [ ] `app.py` 从 Nginx 注入 Header 取签名上下文，只在当前请求生命周期内传给 AI 配置加载器。
- [ ] `people_search_ai.py` 先兑换 Runtime Context，再请求带 `llm_capability=people-search-summary` 的 runtime-config。
- [ ] 平台模式任何验证或请求失败都 fail closed；本地 env 模式保持原行为。

### Step 3：改造 Truthy Search

- [ ] `web_app.py` 的平台运行时配置函数接收当前请求签名上下文，不把用户 Secret 写入 `app.config`。
- [ ] `search_tool.py` 接收显式的运行时配置对象，生命周期限定为一次任务。
- [ ] `credential-status` 调用加入 Runtime Context；错误页面只显示缺少哪个 Provider，不显示键值。
- [ ] Gateway 与 Admin Provider 分别按设计文档的键分类读取，禁止跨 Provider 混用。

### Step 4：改造 API AutoTest

- [ ] `web/app.py` 在请求或任务创建时兑换 Context，并把解析后的任务快照交给执行层。
- [ ] `web/credentials.py` 只做就绪度判断和掩码展示，不缓存明文。
- [ ] `utils/custom/runtime_context.py` 明确保存快照版本与当前用户作用域，不从宿主 `.env.platform` 补用户凭证。
- [ ] `test_cases/conftest.py` 的 Session Writer 改用 `/user-credentials/{credential_id}/session` 并携带 Runtime Context。

### Step 5：验证三个工具回归

```bash
cd log_filter_tool
python3 -m pytest tests/test_people_search_phase4.py tests/test_people_search_phase5.py -q

cd ../Truthy_Search
python3 -m pytest tests/test_web_app.py tests/test_search_tool.py -q

cd ../Truthy_ApiAutoTest2
python3 -m pytest tests/test_web_routes.py tests/test_task_manager.py -q
```

### Step 6：建议提交检查点

```bash
git add log_filter_tool/app.py log_filter_tool/people_search_ai.py \
  log_filter_tool/tests/test_people_search_phase4.py \
  log_filter_tool/tests/test_people_search_phase5.py \
  Truthy_Search/web_app.py Truthy_Search/search_tool.py \
  Truthy_Search/tests/test_web_app.py Truthy_Search/tests/test_search_tool.py \
  Truthy_ApiAutoTest2/web/app.py Truthy_ApiAutoTest2/web/credentials.py \
  Truthy_ApiAutoTest2/utils/custom/runtime_context.py \
  Truthy_ApiAutoTest2/test_cases/conftest.py \
  Truthy_ApiAutoTest2/tests/test_web_routes.py
git commit -m "feat(tools): consume user-scoped platform credentials"
```

---

## Task 11：完成开关、部署配置和运维文档

**Files:**

- Modify: `test-platform/backend/app/core/config.py`
- Modify: `test-platform/docker-compose.yml`
- Modify: `test-platform/docker-compose.local-build.yml`
- Modify: `test-platform/docker-compose.prod.yml`
- Modify: `test-platform/README.md`
- Modify: `functional-test-agent/compose.local.yml`
- Modify: `functional-test-agent/README.md`
- Modify: `api-test-agent/compose.local.yml`
- Modify: `api-test-agent/README.md`
- Modify: `log_filter_tool/docker-compose.yml`
- Modify: `Truthy_Search/compose.yml`
- Modify: `Truthy_Search/README.md`
- Modify: `Truthy_ApiAutoTest2/.env.platform.example`
- Modify: `Truthy_ApiAutoTest2/README.md`
- Test: `test-platform/backend/tests/test_api.py`

### Step 1：先写配置失败测试

- [ ] 个人读取开关开启但签名密钥缺失时启动失败。
- [ ] 个人写入开关开启而数据结构版本未到 `0018` 时健康检查失败。
- [ ] `prod` 使用示例/默认签名密钥时启动失败。
- [ ] compose 渲染后每个工具仍只挂载自己的 Tool Client Token，不挂载用户 Secret 文件。

运行：

```bash
cd test-platform/backend
pytest tests/test_api.py -q
```

预期：配置门禁尚未实现，测试失败。

### Step 2：增加发布开关和密钥挂载

- [ ] 增加：
  - `PERSONAL_CREDENTIALS_WRITE_ENABLED=false`
  - `PERSONAL_CREDENTIALS_ENABLED=false`
- [ ] 两个开关独立：先允许用户配置，再切换运行时读取。
- [ ] 本机和线上分别生成不少于 32 字节的随机签名密钥文件；文件不提交 Git，容器只读挂载。
- [ ] 工具仅接收平台 API 地址和自身 Client Token 文件；移除用户型 Token/密码/LLM Key 的平台模式环境变量注入。
- [ ] 保留非平台独立开发模式需要的本地配置示例，并明确它不能用于平台模式兜底。

### Step 3：更新运维步骤

- [ ] README 固定记录以下顺序：备份数据库 → 升级 schema → dry-run → 核对清单 → apply 给 `admin` → 打开写入 → 双用户配置与验证 → 打开读取 → 观察指标。
- [ ] 记录回滚门禁：一旦非 `admin` 用户创建私有数据，不允许回滚到忽略用户作用域的旧运行时；只能关闭新写入、修复前滚。
- [ ] 记录密钥轮换：维护窗口原子替换签名密钥并滚动重启平台；最多 5 分钟内尚未兑换的旧签名由用户重试，已经签发的 Runtime Context 不受影响，仍通过数据库 Session/权限版本校验。

### Step 4：验证 Compose 与配置文档

```bash
cd test-platform
docker compose -f docker-compose.yml config >/dev/null
docker compose -f docker-compose.local-build.yml config >/dev/null
docker compose -f docker-compose.prod.yml config >/dev/null

cd ../functional-test-agent
docker compose -f compose.local.yml config >/dev/null

cd ../api-test-agent
docker compose -f compose.local.yml config >/dev/null

cd ../log_filter_tool
docker compose -f docker-compose.yml config >/dev/null

cd ../Truthy_Search
docker compose -f compose.yml config >/dev/null
```

### Step 5：建议提交检查点

```bash
git add test-platform/backend/app/core/config.py \
  test-platform/docker-compose.yml \
  test-platform/docker-compose.local-build.yml \
  test-platform/docker-compose.prod.yml \
  test-platform/README.md \
  functional-test-agent/compose.local.yml functional-test-agent/README.md \
  api-test-agent/compose.local.yml api-test-agent/README.md \
  log_filter_tool/docker-compose.yml \
  Truthy_Search/compose.yml Truthy_Search/README.md \
  Truthy_ApiAutoTest2/.env.platform.example Truthy_ApiAutoTest2/README.md \
  test-platform/backend/tests/test_api.py
git commit -m "docs(platform): document personal credential rollout"
```

---

## Task 12：全量验证、双用户验收与本机/线上迁移

**Files:**

- Modify only if a test exposes a defect: files already listed in Tasks 1–11
- No new production files

### Step 1：运行静态与自动化验证

- [ ] 后端：

```bash
cd test-platform/backend
pytest -q
```

- [ ] 前端：

```bash
cd test-platform/frontend
npm test
npm run build
```

- [ ] Functional Agent：

```bash
cd functional-test-agent
pytest -q
```

- [ ] API Agent：

```bash
cd api-test-agent
pytest -q
```

- [ ] Log Filter：

```bash
cd log_filter_tool
python3 -m pytest -q
```

- [ ] Truthy Search：

```bash
cd Truthy_Search
python3 -m pytest -q
```

- [ ] API AutoTest：

```bash
cd Truthy_ApiAutoTest2
python3 -m pytest -q
```

任何失败都回到产生失败的 Task，补充最小复现测试后修复；不得在 Task 12 做无关重构。

### Step 2：执行 dev 双用户隔离验收

- [ ] 备份 dev 数据库并记录当前 Alembic revision。
- [ ] 升级到 `20260823_0018`，运行 `--dry-run`，人工核对每个源对象都只指向 `admin`。
- [ ] 执行 `--apply` 两次，第二次必须全部为幂等跳过。
- [ ] 打开写入开关，分别用 `admin` 与一个普通测试用户配置不同的 Truthy Search Token 和不同的 LLM Profile。
- [ ] 运行相同工具和相同任务，确认两份任务快照的凭证版本、Profile/Binding 版本不同。
- [ ] 删除普通用户的一项必需凭证后再次运行，应得到 `PERSONAL_CREDENTIAL_NOT_CONFIGURED`，不得成功。
- [ ] 撤销该用户 Session 后重放 Runtime Context，应得到 `RUNTIME_CONTEXT_INVALID`。
- [ ] 在旧全局 Credential 写入唯一哨兵字符串，检索应用响应、任务快照、日志和审计数据，均不得出现哨兵或被普通用户实际使用。

### Step 3：执行 prod 变更前门禁

- [ ] dev 连续稳定运行至少一个完整凭证刷新周期。
- [ ] 数据库备份已完成并验证可恢复；签名密钥、KEK、Tool Client Token 三类文件互不相同。
- [ ] prod dry-run 输出由两人核对：目标用户名、用户 ID、环境、对象数量、冲突数均正确，冲突数必须为 0。
- [ ] 确认没有任何非 `admin` 用户私有数据需要从旧系统迁移。

### Step 4：执行 prod 迁移

```bash
cd test-platform/backend
python -m app.migrate_personal_credentials \
  --environment prod \
  --admin-username admin \
  --dry-run

python -m app.migrate_personal_credentials \
  --environment prod \
  --admin-username admin \
  --apply
```

- [ ] 先打开 `PERSONAL_CREDENTIALS_WRITE_ENABLED`，验证 `admin` 页面显示已迁移状态。
- [ ] 再打开 `PERSONAL_CREDENTIALS_ENABLED`，验证 `admin` 的既有工具流程。
- [ ] 让一个普通用户配置自己的值并执行双用户哨兵验证。
- [ ] 观察至少一个完整刷新周期：Runtime Context 失败率、缺失个人配置数、Credential 刷新失败率、403/409 错误率、工具任务成功率。

### Step 5：记录最终验收证据

最终交付报告必须包含：

- [ ] 三份需求/设计/计划文档版本。
- [ ] Alembic revision 与本机/线上迁移时间。
- [ ] dry-run/apply 的对象数量和冲突数，不含 Secret。
- [ ] 各项目测试命令、退出码、通过/失败数量。
- [ ] 双用户、缺失配置、伪造 Header、会话撤销、旧全局哨兵五类验收结果。
- [ ] 未验证的外部 Provider 或人工步骤，以及责任人和后续动作。

---

## 2. 需求覆盖矩阵

| PRD 能力 | 实施任务 | 核心证据 |
|---|---:|---|
| FR-1 我的凭证中心 | Task 1、3、8 | 分类、版本化写入、自助页面和不回显测试 |
| FR-2 用户级所有权 | Task 1、3、4、5、6 | 双用户 API、数据查询和运行时隔离测试 |
| FR-3 可信运行上下文 | Task 5、9、10 | 签名篡改、跨工具、撤销会话和工具兑换测试 |
| FR-4 运行配置合并 | Task 6 | system + 当前用户 Personal 解析矩阵 |
| FR-5 个人 Credential 生命周期 | Task 3、7 | 版本、校验、租约、刷新与失败隔离测试 |
| FR-6 个人 LLM | Task 1、4、6、8 | Profile 所有权、Binding、解析与 UI 测试 |
| FR-7 管理员就绪度 | Task 8 | 权限与非解密聚合测试 |
| FR-8 既有值迁移给 admin | Task 2、12 | dry-run、幂等、冲突和双环境记录 |
| FR-9 错误与提示 | Task 3～10 | 稳定错误码、安全提示和无内部信息泄漏 |
| AC-1 | Task 3、6、12 | 双用户相同工具不同凭证版本 |
| AC-2 | Task 6、12 | 缺失个人凭证且无 admin fallback |
| AC-3 | Task 3、12 | 跨用户 IDOR 拒绝且不泄露元数据 |
| AC-4 | Task 4、6、9、10、12 | 不同个人 LLM Profile/Binding/Secret Version |
| AC-5 | Task 5、12 | Nginx 覆盖伪造 Header、签名篡改失败 |
| AC-6 | Task 5、6、12 | Context 跨用户/工具/环境拒绝 |
| AC-7 | Task 5、6、9、10、12 | 登出后未物化任务失败 |
| AC-8 | Task 6、9、10、12 | 已物化任务版本稳定、新任务使用新版本 |
| AC-9 | Task 7、12 | Credential Agent 多用户刷新隔离 |
| AC-10 | Task 6、12 | `include_secrets=false` 不加载 KEK |
| AC-11 | Task 2、12 | dev/prod 旧值只归各自 admin |
| AC-12 | Task 1、2、11、12 | dev/prod 数据和密钥不互相复制 |
| AC-13 | Task 8、12 | 管理员只见就绪度元数据 |
| AC-14 | Task 2、6、11、12 | legacy 回滚材料保留且不混读 |
| AC-15 | Task 3～12 | API、日志、审计、任务、报告、浏览器哨兵扫描 |

## 3. 明确不在本计划中的内容

- 团队共享凭证、项目级凭证、代理授权和凭证转赠。
- 管理员查看或代填其他用户的 Secret 明文。
- 跨 dev/prod 同步用户凭证。
- 将第三方账号托管给新的外部密码管理产品。
- 重写现有配置中心、任务系统、RBAC 或 Agent 架构。
- 清理旧全局 Credential 数据；V1 只保留为只读回滚材料，清理需另立变更。

## 4. 实施完成定义

只有同时满足以下条件，才可宣称功能完成：

- [ ] Tasks 1～11 的聚焦测试全部通过。
- [ ] Task 12 的所有可运行测试通过，未运行项有明确外部原因。
- [ ] dev 与 prod 各自现有值归属 `admin`，没有复制给普通用户。
- [ ] 双用户隔离、缺失配置、伪造身份、会话撤销、全局哨兵均通过。
- [ ] 线上开关、密钥、迁移记录和回滚门禁已写入运维记录。
- [ ] 没有明文 Secret 出现在 API、日志、审计、任务结果、浏览器存储或 Git diff 中。
