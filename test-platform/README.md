# 测试开发平台

测试开发平台是 QA、研发和测试工程师的统一身份与配置控制面。平台使用 React + TypeScript + Vite、FastAPI、PostgreSQL、Alembic、Nginx 和 Docker Compose，当前聚合六个独立工具：

- `TrackEvents_tess`：埋点日志分析；
- `log_filter_tool`：日志筛选、统计与导出；
- `Truthy_Search`：检索执行、字段对比与评测报告；
- `Truthy_ApiAutoTest2`：Gateway 接口自动化与 Allure 报告。
- `functional-test-agent`：独立的需求拆解、测试点 Review 和功能用例生成项目；
- `api-test-agent`：独立的 API 文档解析、文件化用例生成和受控执行组件项目，真实执行默认关闭。

第二阶段由平台统一负责登录会话、RBAC、网关强制鉴权、审计日志和普通系统配置。业务账号、密码、Token、Credential、LLM Profile 与工具能力 Binding 则按登录用户隔离；用户未配置时失败关闭，不回退管理员、其他用户、legacy 数据或环境变量。工具仍保留独立源码、容器和独立运行模式。

## 平台版本

`versions.json` 是产品与全部可独立部署组件版本的唯一机器真源，版本使用无前导零的 Semantic Versioning。修复递增 PATCH，向后兼容功能递增 MINOR，不兼容接口递增 MAJOR；数据库继续单独使用 Alembic revision。运行身份同时记录组件版本、Git SHA、dirty 状态和镜像 digest，Release BOM 记录一次生产发布的完整组件组合。

## 目录与运行边界

```text
Testproject/
├── test-platform/
├── functional-test-agent/
├── api-test-agent/
├── TrackEvents_tess/
├── log_filter_tool/
├── Truthy_Search/
└── Truthy_ApiAutoTest2/
```

平台模式和工具独立模式不得同时写同一 SQLite、任务或报告目录。`web/` 只保留为旧首页回滚资源；生产页面来自 `frontend/dist`。

## 首次启动

```bash
cd /Users/admin/Testproject/test-platform
cp .env.example .env
# 修改 .env 中的数据库密码和部署环境设置。
# 标准入口会注入版本、Git SHA 和组件范围 dirty 状态并完成运行验证。
./scripts/dev-up.sh
docker compose ps -a
```

Compose 会依次运行 PostgreSQL、`alembic upgrade ${ALEMBIC_TARGET:-20260824_0019}`、工具 Client Token 注册、平台 API、Credential Agent 和统一网关。固定角色权限首次生产发布默认把 `ALEMBIC_TARGET` 固定为 `20260824_0019`（Expand）；只有角色与历史资源 manifest、shadow 对比和阻断校验清零后，Contract 发布才允许显式设置为 `head`。宿主机只暴露 `${PLATFORM_PORT:-8080}`。

历史资源先用 `scripts/export_business_resource_manifest.py` 从五个工具的只读存储枚举，再补齐 `user_roles`、`tool_projects` 和 `memberships`。Contract 发布（`ALEMBIC_TARGET=head` 或任何非 `20260824_0019` 目标）必须同时提供 `PROJECT_ACCESS_MANIFEST=/absolute/path/manifest.json`；部署脚本会先执行 dry-run 和原子 apply，0020 自身还会复核 readiness marker。任何源端计数不一致、owner/来源不明、非法关系或未经批准的 shadow 扩权都会在收紧约束前阻断。

开发环境初始化文件位于 Git 忽略的 `.runtime-secrets/`：

- `dev-kek.json`：dev Secret KEK；
- `prod-kek.json`：prod 准备使用的独立 KEK，不在 dev Compose 挂载；
- `<environment>/bootstrap-token`：仅用于对应环境数据库无用户时的 `/setup`；
- `<environment>/user-context-signing-key`：Nginx 可信用户上下文的独立 HMAC 密钥，只挂载给平台 API；
- `<environment>/*-client-token`：两个 AI 智能体按环境和工具独立的启动身份；
- `*-client-token`：既有工具的独立启动身份；
- `initial-admin-password`：自动初始化后的临时管理员密码。

当前 dev 管理员用户名为 `admin`。首次登录可在本机读取临时密码，登录后应立即修改：

```bash
cat /Users/admin/Testproject/test-platform/.runtime-secrets/initial-admin-password
```

这些文件不得提交、复制到聊天或写入普通配置。`/setup` 在已有用户后固定返回不可用。

## 身份与安全默认值

| 项目 | 默认值 |
|---|---|
| 新 Session 空闲有效期 | 168 小时（7 天） |
| 新 Session 绝对有效期 | 168 小时（7 天） |
| 新密码 | 6–18 个 Unicode 字符；登录继续兼容 1–256 位存量密码 |
| 自助注册 | `REGISTRATION_MODE=open`；新账号固定为 active tester，无项目或额外授权 |
| 注册防滥用 | 来源 5 次/15 分钟；全局 100 次/15 分钟；请求体最大 64 KiB |
| 登录锁定 | 15 分钟内失败 5 次，锁定 15 分钟 |
| Cookie | `tp_session` HttpOnly；`tp_csrf` 双提交 |
| dev Cookie Secure | 可关闭，仅限受控内网 HTTP |
| prod Cookie Secure | HTTP 关闭 Secure 时必须提供 `SESSION_COOKIE_RISK_ACCEPTANCE_ID`；HTTPS 应设为 `true` |
| Secret 加密 | AES-256-GCM 信封加密，每版本独立 DEK |
| 审计保留目标 | 180 天 |
| 凭证提前刷新 | 60 分钟 |
| 签名用户上下文 | 最长 5 分钟 |
| Runtime Context | 最长 24 小时，可因 Session、用户或权限变化提前失效 |

Nginx 对全部六个工具前缀执行 `auth_request`。匿名页面请求重定向 `/login`，API 请求返回 401；无权限返回 403；身份服务异常返回 503。浏览器提供的 `X-Platform-*` 会被清除，只有授权成功后由网关注入可信身份和权限。

发布前已存在的 Session 继续按数据库中原到期时间判断；配置改为 168 小时只影响新签发 Session。紧急停止新注册时设置 `REGISTRATION_MODE=disabled` 并重启平台 API/网关，不删除已创建用户。

## 共享配置与用户级凭证

普通非敏感配置和明确标记为 `system` 的系统级 Secret 保持共享。业务凭证只在“我的凭证”中由当前用户维护：

1. 在 `/settings/config` 选择 `dev/prod` 和工具；
2. 创建草稿，编辑普通配置，保存并校验；
3. 管理员只在 `/settings/secrets` 写入系统级 Secret，保存后永不回显明文；
4. 发布 Release；每个新 Run/任务保存 Release ID；
5. 用户在 `/account/credentials` 保存自己有执行权限工具的账号、密码或 Token；字段值保存后立即从表单清空；
6. 管理员在 `/settings/credentials` 只读查看用户就绪度，不能解密或代改；
7. Credential Agent 每分钟按用户分别扫描、加锁、刷新并写回个人 Credential。

配置生效模式为 `immediate`、`next_task`、`restart` 或 `deployment`。平台不挂载 Docker Socket；`restart/deployment` 只显示待操作状态，由管理员执行文档化的 Compose 命令。

`dev/prod` 的 PostgreSQL 卷、任务目录、配置、Secret、Credential、Client Token 和 KEK 必须隔离。Compose 默认使用 `test-platform-<environment>-db-data`，普通配置可人工提升为 prod 草稿，Secret 不自动复制。

### 我的 LLM

`/account/llm` 管理当前用户自己的 OpenAI-compatible Profile 与预登记工具能力 Binding。首期能力包括：

- `functional-test-agent/default`；
- `api-test-agent/default`；
- `log-filter/people-search-summary`。

Profile 保存 Base URL、模型和加密 API Key；Binding 可覆盖模型、Temperature、Max Tokens、超时或独立 API Key。新 API 不接受 `user_id`，所有权只来自登录 Session；Secret 保存后不回显。旧 `/settings/llm` 地址重定向到个人页面，legacy 空所有者 Profile 仅作为关闭开关时的回滚材料，不进入个人 Resolver。

工具请求先由 Nginx 清除客户端伪造的 `X-Platform-User-Context`，再用独立 HMAC 密钥注入最长 5 分钟的签名身份。工具凭 Tool Client Token 将其兑换成 Runtime Context；创建任务只记录不含 Secret 的 `snapshot_selector`，执行开始时才重新校验并物化精确历史版本。Session 撤销、用户禁用、权限变化、过期或跨用户/工具/环境请求均拒绝物化。

### dev 数据迁移与开关

升级后先保持两个开关关闭，迁移只处理当前环境且只认唯一有效 `admin`。命令默认 dry-run，apply 会重新加密 Secret，冲突整笔回滚且可重复执行：

```bash
cd /Users/admin/Testproject/test-platform
docker compose exec -T platform-api \
  python -m app.migrate_personal_credentials \
  --environment dev --admin-username admin --dry-run
docker compose exec -T platform-api \
  python -m app.migrate_personal_credentials \
  --environment dev --admin-username admin --apply
```

发布顺序固定为：`PERSONAL_CREDENTIALS_WRITE_ENABLED=true`、验证个人页面可写，再设置 `PERSONAL_CREDENTIALS_ENABLED=true` 切换 Resolver。读取开关开启后不允许任何 legacy/admin/env fallback。prod Compose 本轮只预留结构，两个开关保持 `false`，不执行迁移。

## 常用运维命令

```bash
cd /Users/admin/Testproject/test-platform

docker compose config
docker compose ps -a
docker compose run --rm platform-migrate
docker compose logs --tail=200 platform-api platform-credential-agent platform-gateway
docker compose exec -T platform-gateway nginx -t

curl -i http://127.0.0.1:8080/api/v1/health/live
curl -i http://127.0.0.1:8080/api/v1/health/ready
```

## 两个 AI 测试智能体

两个服务使用独立任务根和按环境隔离的 Tool Client Token：

```text
functional-test-agent/runtime/<environment>/functional
api-test-agent/runtime/<environment>/api
test-platform/.runtime-secrets/<environment>/functional-test-agent-client-token
test-platform/.runtime-secrets/<environment>/api-test-agent-client-token
```

两个 Agent 在平台模式使用签名用户上下文兑换 Runtime Context，并在任务执行开始时物化当前用户的个人 LLM 快照；缺少个人 Binding 时直接返回 `PERSONAL_LLM_NOT_CONFIGURED`，不读取旧工具 Release 中的 `LLM_*` 或进程环境变量。API 工具初始值必须保持：

```text
API_EXECUTION_ENABLED=false
DATABASE_PERSIST_ENABLED=false
ALLOWED_TARGETS=[]
```

任务摘要默认保留 180 天，输入、日志和产物保留 90 天，每个智能体最多保留 500 个终态任务。两个智能体只读写各自项目的 runtime，历史单体目录不作为运行或迁移来源。

功能智能体在线测试点 Review 使用任务目录中的 JSON 文件作为权威数据，不建立测试点业务表。模型原稿、可变草稿、AI 建议和不可变确认版本分别保存；正式用例生成只读取确认版本。普通用户在任务详情页使用结构化表格，原 JSON 下载/上传保留在“高级操作”。

```text
ONLINE_REVIEW_ENABLED=false
REVIEW_AI_ENABLED=false
REVIEW_AI_TIMEOUT_SECONDS=600
REVIEW_AI_MAX_SELECTED_POINTS=100
REVIEW_AI_MAX_SUGGESTIONS=200
REVIEW_AI_MAX_CONTEXT_POINTS=500
REVIEW_AI_MAX_INSTRUCTION_CHARACTERS=2000
```

配置目录默认关闭两个功能。迁移 `20260813_0010` 会克隆当前 dev Release 并显式开启在线 Review 与 AI Review；prod 不自动开启。AI 辅助和正式生成共享功能智能体的单运行槽位及 FIFO，AI 失败、取消、超时或重启中断会返回 `waiting_review`，不会删除草稿。

回滚时先关闭 `REVIEW_AI_ENABLED`；仍需回退时再关闭 `ONLINE_REVIEW_ENABLED`，页面恢复旧 JSON 流程。不要删除任务卷中的 `review-draft.json`、`review-test-points-vN.json` 或 `review-ai/`。数据库通常保留 0010；确需降级时先关闭开关，再降到 `20260812_0009`。

功能智能体在线测试用例 Review 复用测试点 Review 的文件事务、CAS、权限和单槽 FIFO，但使用独立用例校验、AI Prompt 和“列表 + 详情”桌面工作台。用例模型原稿、草稿、AI 建议、确认版本分别保存；`actual_result` 本期只读。确认时不会再次调用模型，而是从不可变确认 JSON 同源生成最终 JSON/XLSX。

```text
ONLINE_CASE_REVIEW_ENABLED=false
CASE_REVIEW_AI_ENABLED=false
CASE_REVIEW_AI_TIMEOUT_SECONDS=600
CASE_REVIEW_AI_MAX_SELECTED_CASES=50
CASE_REVIEW_AI_MAX_SUGGESTIONS=100
CASE_REVIEW_AI_MAX_CONTEXT_CASES=300
CASE_REVIEW_AI_MAX_CONTEXT_POINTS=300
CASE_REVIEW_AI_MAX_INSTRUCTION_CHARACTERS=2000
CASE_REVIEW_MAX_CASES=2000
CASE_REVIEW_MAX_BYTES=10485760
CASE_REVIEW_MAX_CHARACTERS=1000000
```

迁移 `20260814_0012` 下接 `20260813_0011`：配置定义默认关闭，dev Release 显式开启，prod 不自动开启。用例 AI 失败、取消、超时或服务重启后回到 `waiting_case_review`，不会修改草稿或删除已有产物。发布失败时任务保持可恢复 Review 状态，artifact registry 不登记半成品。

用例 Review 回滚按三层执行：先关闭 `CASE_REVIEW_AI_ENABLED`，再关闭 `ONLINE_CASE_REVIEW_ENABLED`，必要时恢复上一版功能智能体镜像并保留任务卷。通常保留 0012；确需降级时先关闭开关，再执行 `alembic downgrade 20260813_0011`。不得删除 `case-review-draft.json`、`review-test-cases-vN.json`、`case-review-ai/` 或 `published/test-cases/vN/`。

### 功能测试脑图工作台 V2

迁移 `20260816_0014` 下接 `20260815_0013`，增加统一界面开关：

```text
FUNCTIONAL_WORKBENCH_V2_ENABLED=false
```

开关关闭时继续使用原在线 Review 页面；开启时，功能测试任务列表、新建弹窗、测试点 Review 和测试用例 Review 切换到桌面脑图工作台。脑图、表格和详情面板共用同一份浏览器数据及撤销历史，修改仍需显式保存。平面 JSON、草稿 CAS、不可变确认版本、AI 建议、FIFO、权限和产物协议均保持不变，API 智能体页面不受影响。

脑图组件 `mind-elixir@5.14.0` 已固定版本并自托管，不使用 CDN。许可证和文件校验信息位于 `functional-test-agent/services/common/static/vendor/mind-elixir/`，可在功能项目执行 `node --test tests/ui/*.test.mjs` 校验供应链文件及投影/命令内核。

dev 发布时先完成自动化与浏览器验收，再新建 dev 配置 Release，把 `FUNCTIONAL_WORKBENCH_V2_ENABLED` 设为 `true` 并仅替换功能智能体。prod 首次发布保持 `false`。回滚优先发布新 Release 将开关设回 `false`；必要时恢复上一版功能智能体镜像，任务卷及 Review 文件全部保留。通常保留 0014；确需降级时先关闭开关，再执行 `alembic downgrade 20260815_0013`。

### 功能测试 Figma 工作台 V3

迁移 `20260818_0016` 下接 `20260817_0015`，增加独立界面开关：

```text
FUNCTIONAL_WORKBENCH_V3_ENABLED=false
```

V3 开启时使用固定阶段侧栏、紧凑任务中心和聚焦式 Review 工作区，并直接复用 V2 的脑图、表格、详情、AI 建议、CAS 与产物能力。选择优先级为 V3、V2、旧页面，因此 V3 不要求同时开启 V2。prod 首次发布保持关闭；dev 验收后通过配置 Release 显式开启。

回滚时优先发布新 dev Release 将 V3 设为 `false`，页面会立即恢复 V2 或旧页面。通常保留 0016；确需降级时先关闭 V3，再执行 `alembic downgrade 20260817_0015`。降级只删除 V3 配置定义和 Release 引用，不删除任务、草稿、建议、确认版本或产物。

部署或回滚时可单独启动、停止两个服务；常规回滚不得删除任务目录。只有在已备份平台数据库并确认接受删除新工具配置数据时，才执行 Alembic downgrade 到 `20260811_0008`。

数据库备份、SQLite 一致性备份和工具产物备份放在 Git 忽略的 `backups/`。不要只复制正在运行的 SQLite 主文件，应使用 SQLite Backup API。

## dev → main → prod 发布

本机只在 `dev` 开发并通过 `scripts/dev-up.sh` 原生构建。生产版本只从 `main` 创建 `release-YYYY.MM.DD.N` 标签，由 GitHub Actions 构建 `linux/amd64` 镜像并在 `production` Environment 审批后部署。服务器只执行镜像拉取，不执行 `git pull` 或 `docker compose build`。

生产基础变量参照 `.env.prod.example` 保存到 `/srv/test-platform/env/.env.prod`，真实密码和 Token 不进入 Git。Release 产物中的 `.env.images` 保存所有服务的完整 GHCR digest；部署时两个 env 文件共同传给 Compose，避免任何镜像回退到默认旧版本。

首次复制空 prod 配置中心时先执行 dry-run：

```bash
python -m app.promote_environment \
  --source dev --target prod --require-empty-target \
  --copy-secrets --seed-credentials --dry-run
```

确认数量后去掉 `--dry-run`。命令会重新加密 Secret、创建独立 prod Release，并只建立待验证 Credential；Client Token 由 `app.bootstrap_clients` 使用 `/srv/test-platform/secrets/prod/` 下的新 Token 注册。目标已有 Release、Secret、Credential 或 Client 时命令会拒绝执行。

常规生产部署入口为：

```bash
bash /srv/test-platform/releases/<release>/deploy-prod.sh \
  /srv/test-platform/releases/<release>
```

部署前自动备份已有 prod 数据库，随后依次校验无 `build`、拉取 digest、升级数据库、启动服务并检查平台与六个工具入口。成功后写入 `/srv/test-platform/state/current.json`、部署 JSON 和 Markdown 记录。功能智能体可传完整 digest 独立切换；API 智能体必须传包含四个 digest 的 env 文件原子切换。失败会恢复前一镜像组合，数据库默认不降级。

## 测试

```bash
# 平台前端
cd /Users/admin/Testproject/test-platform/frontend
npm test -- --run
npm run build
npm audit --audit-level=high

# 平台后端
cd /Users/admin/Testproject/test-platform/backend
python3 -m pytest -q

# 平台冒烟与 Nginx
cd /Users/admin/Testproject/test-platform
python3 -m unittest discover -s tests -v
docker compose exec -T platform-gateway nginx -t

# 各工具回归
cd /Users/admin/Testproject/TrackEvents_tess && python3 -m unittest discover -s tests -v
cd /Users/admin/Testproject/log_filter_tool && python3 -m unittest discover -s tests -v
cd /Users/admin/Testproject/Truthy_Search && python3 -m pytest -q
cd /Users/admin/Testproject/Truthy_ApiAutoTest2 && python3 -m pytest -q tests
```

## 回滚

1. 暂停新任务并停止 `platform-credential-agent`；
2. 等待运行任务结束；
3. Truthy_Search 与 API AutoTest 恢复 env Provider；
4. 确保平台不再写同一凭证后，恢复旧凭证文件；
5. 回滚工具和网关镜像，优先保留统一鉴权；
6. 只有旧代码确实无法使用新 Schema 时才执行 Alembic downgrade；
7. Secret 降级前保留加密数据库副本和对应 KEK，禁止导出明文。

数据库结构只通过 Alembic 修改。停止服务但保留数据使用 `docker compose down`；删除命名卷会不可恢复地删除平台数据库，不属于常规回滚操作。
