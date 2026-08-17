# 测试开发平台

测试开发平台是 QA、研发和测试工程师的统一身份与配置控制面。平台使用 React + TypeScript + Vite、FastAPI、PostgreSQL、Alembic、Nginx 和 Docker Compose，当前聚合六个独立工具：

- `TrackEvents_tess`：埋点日志分析；
- `log_filter_tool`：日志筛选、统计与导出；
- `Truthy_Search`：检索执行、字段对比与评测报告；
- `Truthy_ApiAutoTest2`：Gateway 接口自动化与 Allure 报告。
- `functional-test-agent`：独立的需求拆解、测试点 Review 和功能用例生成项目；
- `api-test-agent`：独立的 API 文档解析、文件化用例生成和受控执行组件项目，真实执行默认关闭。

第二阶段由平台统一负责登录会话、RBAC、网关强制鉴权、审计日志、普通配置、加密 Secret 和凭证续期。`1.01.000` 起，平台同时统一管理功能 Agent、API Agent 与日志分析的 LLM Profile、工具绑定和不可变运行快照。工具仍保留独立源码、容器和独立运行模式。平台或数据库异常时鉴权失败关闭，不提供匿名回退。

## 平台版本

根目录 `VERSION` 是平台版本的唯一真源，格式固定为 `主版本.两位平台版本.三位发布序号`。普通工具或小功能发布递增最后三位（如 `1.00.000 → 1.00.001`）；AI 测试工作台或平台级升级递增中间两位并将发布序号归零（如 `1.00.015 → 1.01.000`）；不兼容升级才递增主版本。发布前只修改该文件，重新构建网关和平台 API 后，首页“平台状态”与 `/api/v1/health/live`、`/api/v1/health/ready` 会显示同一版本。

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
# 主 Compose 只消费版本化镜像；首次本机构建叠加 local-build 文件。
docker compose -f docker-compose.yml -f docker-compose.local-build.yml build functional-test-agent api-test-agent
docker compose up -d
docker compose ps -a
```

Compose 会依次运行 PostgreSQL、`alembic upgrade head`、工具 Client Token 注册、平台 API、Credential Agent 和统一网关。宿主机只暴露 `${PLATFORM_PORT:-8080}`。

开发环境初始化文件位于 Git 忽略的 `.runtime-secrets/`：

- `dev-kek.json`：dev Secret KEK；
- `prod-kek.json`：prod 准备使用的独立 KEK，不在 dev Compose 挂载；
- `<environment>/bootstrap-token`：仅用于对应环境数据库无用户时的 `/setup`；
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
| Session 空闲有效期 | 8 小时 |
| Session 绝对有效期 | 24 小时 |
| 登录锁定 | 15 分钟内失败 5 次，锁定 15 分钟 |
| Cookie | `tp_session` HttpOnly；`tp_csrf` 双提交 |
| dev Cookie Secure | 可关闭，仅限受控内网 HTTP |
| prod Cookie Secure | 必须开启，且必须 HTTPS |
| Secret 加密 | AES-256-GCM 信封加密，每版本独立 DEK |
| 审计保留目标 | 180 天 |
| 凭证提前刷新 | 60 分钟 |

Nginx 对全部六个工具前缀执行 `auth_request`。匿名页面请求重定向 `/login`，API 请求返回 401；无权限返回 403；身份服务异常返回 503。浏览器提供的 `X-Platform-*` 会被清除，只有授权成功后由网关注入可信身份和权限。

## 配置、Secret 与 Credential

Web 配置控制面只允许修改迁移中登记的白名单键：

1. 在 `/settings/config` 选择 `dev/prod` 和工具；
2. 创建草稿，编辑普通配置，保存并校验；
3. 在 `/settings/secrets` 写入 Secret。保存后永不回显明文；
4. 发布 Release；每个新 Run/任务保存 Release ID；
5. 在 `/settings/credentials` 创建 `gateway_session` 或 `admin_login` Credential；
6. Credential Agent 每分钟扫描临期凭证并刷新或重新登录。

配置生效模式为 `immediate`、`next_task`、`restart` 或 `deployment`。平台不挂载 Docker Socket；`restart/deployment` 只显示待操作状态，由管理员执行文档化的 Compose 命令。

`dev/prod` 的 PostgreSQL 卷、任务目录、配置、Secret、Credential、Client Token 和 KEK 必须隔离。Compose 默认使用 `test-platform-<environment>-db-data`，普通配置可人工提升为 prod 草稿，Secret 不自动复制。

### LLM 统一配置

`/settings/llm` 将模型配置分为公共 Profile 和预登记工具绑定。首期只登记：

- `functional-test-agent/default`；
- `api-test-agent/default`；
- `log-filter/people-search-summary`。

Profile 保存 OpenAI-compatible Base URL、模型和加密 API Key；Binding 可覆盖模型、Temperature、Max Tokens、超时或独立 API Key。普通参数经 Release 发布，Secret 保存后不回显，任务/请求只读取一次已发布快照。TrackEvents、Truthy_Search 和 API AutoTest 没有直接 LLM 调用，因此不显示无效配置。

旧配置导入先 dry-run，`apply` 只创建草稿和 Secret，不自动发布，也不会输出值、长度、前后缀或哈希：

```bash
cd /Users/admin/Testproject/test-platform/backend
python3 -m app.migrate_llm_config --environment dev --dry-run
python3 -m app.migrate_llm_config --environment dev --apply \
  --log-base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --log-model deepseek-v4-flash \
  --log-key-file /只读临时挂载/log-analyzer-key
```

之后在 Web 依次发布 Profile、三个 Binding，并由管理员手动执行一次最小连接测试。平台模式不回退旧 LLM Secret；独立模式仍使用各工具原 `.env`/key file。

## 真实凭证迁移门禁

用户曾在对话中暴露过 Truthy_Search Access/Refresh Token。迁移真实凭证前必须先在上游撤销或刷新这些 Token，并确认旧值失效；本实现不会把已暴露值写入数据库或代码。

完成门禁后才能切换 Provider：

```text
Truthy_Search: SEARCH_CONFIG_SOURCE=platform
Truthy_ApiAutoTest2: API_AUTOTEST_SESSION_PROVIDER=platform
```

切换前先暂停新任务并确认没有 `RUNNING` Run。验证双读结果一致后，删除平台 Compose 中 `Truthy_Search/.env` 和 `Truthy_ApiAutoTest2/.env.platform` 的旧凭证挂载。未完成门禁时保持 env Provider，避免错误迁移真实 Secret。

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

两个 Agent 在平台模式优先读取 `/settings/llm` 发布的 `llm` 快照；迁移期若快照不存在，继续兼容旧工具 Release 中的 `LLM_*` 字段。API 工具初始值必须保持：

```text
API_EXECUTION_ENABLED=false
DATABASE_PERSIST_ENABLED=false
ALLOWED_TARGETS=[]
```

任务摘要默认保留 180 天，输入、日志和产物保留 90 天，每个智能体最多保留 500 个终态任务。旧 `AItestcase_Agents/output/` 不挂载、不迁移且不作为新服务的写目录。

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

开关关闭时继续使用原在线 Review 页面；开启时，功能测试任务列表、新建弹窗、测试点 Review 和测试用例 Review 切换到桌面脑图工作台。脑图是唯一编辑入口，旁侧表格永久只读。平面 JSON、草稿 CAS、不可变确认版本、AI 建议、FIFO、权限和产物协议均保持不变，API 智能体页面不受影响。

脑图组件 `mind-elixir@5.14.0` 已固定版本并自托管，不使用 CDN。许可证和文件校验信息位于 `functional-test-agent/services/common/static/vendor/mind-elixir/`，可在功能项目执行 `node --test tests/ui/*.test.mjs` 校验供应链文件及投影/命令内核。

dev 发布时先完成自动化与浏览器验收，再新建 dev 配置 Release，把 `FUNCTIONAL_WORKBENCH_V2_ENABLED` 设为 `true` 并仅替换功能智能体。prod 首次发布保持 `false`。回滚优先发布新 Release 将开关设回 `false`；必要时恢复上一版功能智能体镜像，任务卷及 Review 文件全部保留。通常保留 0014；确需降级时先关闭开关，再执行 `alembic downgrade 20260815_0013`。

部署或回滚时可单独启动、停止两个服务；常规回滚不得删除任务目录。只有在已备份平台数据库并确认接受删除新工具配置数据时，才执行 Alembic downgrade 到 `20260811_0008`。

数据库备份、SQLite 一致性备份和工具产物备份放在 Git 忽略的 `backups/`。不要只复制正在运行的 SQLite 主文件，应使用 SQLite Backup API。

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
