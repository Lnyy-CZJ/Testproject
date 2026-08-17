# 两个 AI 测试智能体源码物理拆分与独立发布——开发设计与计划

> 文档版本：V1.0  
> 创建日期：2026-08-17  
> 文档状态：待开发评审  
> 需求基线：`test-platform/docs/两个AI测试智能体源码物理拆分与独立发布_PRD.md` V1.0  
> 实施范围：本机拆分、独立开发、独立构建、独立 Compose 接入、数据迁移和回滚验证  
> 首次生产发布约束：只交付可信生成与 Review，继续关闭 API 真实执行

---

## 1. 文档目的

本文档将已确认的源码物理拆分 PRD 转换为可直接实施、测试、灰度和回滚的开发设计。

本期不是简单移动文件，而是完成以下工程结果：

1. 创建两个完全自包含的本机项目目录；
2. 消除两个项目与旧 `AItestcase_Agents`、兄弟目录之间的源码依赖；
3. 分拆公共运行时、依赖、Docker 构建上下文、镜像、Revision 和操作入口；
4. 保持平台 HTTP、身份、权限、任务、Review、产物和 Prompt 行为兼容；
5. 迁移终态和非终态任务，保留原状态语义和恢复规则；
6. 让平台通过独立镜像运行两个项目，并可分别升级、停止和回滚；
7. 在两个稳定 Release 后冻结并只读归档旧仓；
8. 不改变 API 生产真实执行关闭的安全决策。

---

## 2. 已确认决策

### 2.1 评审项结论

| 编号 | 评审项 | 技术结论 |
|---|---|---|
| D01 | 远程 Git 仓库 | 本期先在本机开发；两个目录按可独立 Git 仓库设计，远程地址和最终负责人延期到首次推送前确认 |
| D02 | 目录命名 | 固定为 `/Users/admin/Testproject/functional-test-agent`、`/Users/admin/Testproject/api-test-agent` |
| D03 | 镜像仓库和命名 | 本机阶段不依赖远程仓库；使用独立本地镜像名和统一 Release tag，未来通过 `AGENT_IMAGE_REGISTRY` 增加前缀 |
| D04 | 部署方式 | 本期使用本机 Docker Compose；prod 消费方式延期到生产发布评审 |
| D05 | 非终态任务 | 迁移；pending/Review 原样恢复，running 数据迁移但按既有恢复规则转为 `failed/WORKER_INTERRUPTED` 后重试 |
| D06 | 旧历史入口 | 至少保留 180 天且不自动删除；到期后必须由管理员再次批准才能下线或删除 |
| D07 | 旧仓归档 | 两个稳定 Release 后迁入 `/Users/admin/Testproject/archive/AItestcase_Agents/<baseline-tag>/`，目录只读，不挂载给新服务 |
| D08 | Release/回滚责任 | 本机阶段由平台管理员审批 Release 并负责紧急回滚 |
| D09 | 公共代码基线 | 目标 tag 为 `ai-agents-split-baseline-20260817`；当前用户修改先形成可追溯基线，再创建 tag；复制代码使用文件清单和 SHA |
| D10 | 首次生产范围 | 只完成可信生成和 Review；`API_EXECUTION_ENABLED=false`，API 生产真实执行不因拆分自动获批 |

### 2.2 镜像命名

本机默认：

```text
functional-test-agent:<release>
api-test-agent:<release>
api-execution-controller:<release>
api-egress-proxy:<release>
api-test-executor:<release>
```

其中 `<release>` 使用：

```text
0.1.0-local.<YYYYMMDD>.<short-sha>
```

未来远程仓库启用后，镜像完整名称为：

```text
${AGENT_IMAGE_REGISTRY}/functional-test-agent:<release>
${AGENT_IMAGE_REGISTRY}/api-test-agent:<release>
${AGENT_IMAGE_REGISTRY}/api-execution-controller:<release>
${AGENT_IMAGE_REGISTRY}/api-egress-proxy:<release>
${AGENT_IMAGE_REGISTRY}/api-test-executor:<release>
```

`AGENT_IMAGE_REGISTRY` 本机默认为空。API 四个镜像必须使用同一个 `<release>`，不得混用版本。

### 2.3 基线 tag 创建约束

当前工作区存在用户未完成修改，因此禁止立即对当前 HEAD 创建一个会遗漏这些修改的“伪基线” tag。

W01 必须：

1. 记录当前 commit、`git status`、文件 SHA 和未跟踪文件清单；
2. 由用户将现有修改纳入可追溯提交或明确保存为基线补丁；
3. 重新运行全量测试；
4. 只有工作区基线可复现后，才创建 `ai-agents-split-baseline-20260817`；
5. 不得为创建 tag 丢弃、覆盖或还原用户修改。

---

## 3. 设计原则

1. **先复制后切换**：不直接移动或删除旧源码；新项目验证通过后逐个切流。
2. **先功能后 API**：功能项目先完成拆分和回滚演练，再拆 API，避免两个变量同时变化。
3. **接口不变**：拆分期不修改 HTTP 路径、Schema、Prompt、任务状态和 artifact 类型。
4. **实现隔离**：不使用相对 import、`PYTHONPATH`、symlink、submodule、editable sibling package 或源码 bind mount。
5. **数据独立**：新项目分别拥有 runtime 根，不共享可写目录。
6. **发布独立**：功能一个 Release；API 四镜像一个 Release；平台分别引用。
7. **失败可回滚**：新旧镜像和旧数据根在回滚窗口内并存，任何切换都可恢复旧版本。
8. **安全不降级**：功能项目不能获得 API 执行能力；API 生产真实执行继续关闭。
9. **最小重构**：只做拆分所需包路径和边界调整，不重写业务流程。
10. **复制有来源**：复制的公共运行时代码必须记录源文件、基线 SHA、目标文件和责任项目。

---

## 4. 现状与目标架构

### 4.1 当前架构

```text
Testproject/
├── AItestcase_Agents/
│   ├── agents/functional_test
│   ├── agents/api_test
│   ├── services/common
│   ├── services/functional_agent
│   ├── services/api_agent
│   ├── services/execution_controller
│   ├── services/egress_proxy
│   ├── executor
│   └── runtime/dev/{functional,api}
└── test-platform/
    └── docker-compose.yml  # 五个镜像均从同一旧目录构建
```

主要耦合：

- `services/common.web` 同时包含公共路由、功能 Review 和 API 接入逻辑；
- `services/common.task_manager` 同时服务两个任务模型；
- 功能和 API 镜像的 Docker context 都是整个旧仓；
- 两个服务共用 `APP_REVISION`；
- API Controller/Egress/Executor 仍从旧仓构建；
- runtime 虽已分子目录，但宿主根仍位于旧仓。

### 4.2 目标架构

```text
Testproject/
├── functional-test-agent/
│   ├── src/functional_agent
│   ├── src/functional_workflows
│   ├── src/runtime
│   ├── prompts
│   ├── templates
│   ├── static
│   ├── tests
│   ├── runtime/dev
│   ├── Dockerfile
│   └── compose.local.yml
├── api-test-agent/
│   ├── src/api_agent
│   ├── src/api_workflows
│   ├── src/runtime
│   ├── src/execution_controller
│   ├── src/egress_proxy
│   ├── src/executor
│   ├── tests
│   ├── runtime/dev
│   ├── Dockerfile.*
│   └── compose.local.yml
├── test-platform/
│   ├── docker-compose.yml             # 只引用镜像
│   └── docker-compose.local-build.yml # 本机 build override
└── archive/
    └── AItestcase_Agents/<baseline-tag>/  # 稳定后只读归档
```

### 4.3 运行关系

```text
Browser
  → platform-gateway
      ├── /functional-test-agent/ → functional-test-agent image
      └── /api-test-agent/        → api-test-agent image
                                       └── 本机 S2 profile（默认不启动）
                                           ├── execution-controller
                                           ├── egress-proxy
                                           └── per-run executor
```

平台继续提供统一身份、权限、配置和 Secret 控制面，但不再读取两个项目源码。

---

## 5. 目录和包设计

### 5.1 功能项目

```text
functional-test-agent/
├── src/
│   ├── functional_agent/
│   │   ├── app.py
│   │   ├── web.py
│   │   ├── runner.py
│   │   ├── adapter.py
│   │   ├── review_ai.py
│   │   ├── case_review_ai.py
│   │   └── case_review_publisher.py
│   ├── functional_workflows/
│   │   ├── requirement_decomposition/
│   │   ├── test_points/
│   │   └── test_cases/
│   └── runtime/
│       ├── artifacts.py
│       ├── audit.py
│       ├── case_review.py
│       ├── config.py
│       ├── errors.py
│       ├── identity.py
│       ├── platform_client.py
│       ├── prompt_version.py
│       ├── redaction.py
│       ├── review.py
│       ├── task_manager.py
│       ├── task_models.py
│       ├── task_store.py
│       ├── uploads.py
│       └── versioned_review.py
├── prompts/
├── templates/
├── static/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── ui/
├── runtime/                 # Git/Docker 忽略
├── requirements.lock
├── pyproject.toml
├── Dockerfile
├── compose.local.yml
├── .dockerignore
├── .gitignore
├── SOURCE_SPLIT_BASELINE.md
└── README.md
```

设计说明：

- 原 `services/common/web.py` 不整体复制，功能路由抽到 `functional_agent/web.py`；
- `runtime` 仅保留功能使用的公共能力；
- 功能模板、测试点 Review、用例 Review、脑图/工作台资源全部归功能项目；
- 原 CLI 通过功能项目自己的入口兼容，不依赖旧包路径；
- 依赖从现有 `requirements-functional-agent.lock` 冻结迁入，拆分期不顺便升级。

### 5.2 API 项目

```text
api-test-agent/
├── src/
│   ├── api_agent/
│   │   ├── app.py
│   │   ├── web.py
│   │   ├── blueprint.py
│   │   ├── runner.py
│   │   ├── adapter.py
│   │   ├── task_manager.py
│   │   ├── review_service.py
│   │   ├── execution_service.py
│   │   ├── controller_client.py
│   │   ├── defect_service.py
│   │   └── v2_store.py
│   ├── api_workflows/
│   │   ├── contracts/
│   │   ├── cases/
│   │   ├── parsers/
│   │   └── generators/
│   ├── runtime/
│   │   ├── artifacts.py
│   │   ├── audit.py
│   │   ├── config.py
│   │   ├── errors.py
│   │   ├── identity.py
│   │   ├── platform_client.py
│   │   ├── prompt_version.py
│   │   ├── redaction.py
│   │   ├── task_models.py
│   │   ├── task_store.py
│   │   └── uploads.py
│   ├── execution_controller/
│   ├── egress_proxy/
│   └── executor/
├── prompts/
├── templates/
├── static/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── security/
│   └── ui/
├── runtime/                 # Git/Docker 忽略
├── requirements-agent.lock
├── requirements-controller.lock
├── pyproject.toml
├── Dockerfile.agent
├── Dockerfile.controller
├── Dockerfile.egress
├── Dockerfile.executor
├── compose.local.yml
├── .dockerignore
├── .gitignore
├── SOURCE_SPLIT_BASELINE.md
└── README.md
```

设计说明：

- API Web 路由全部归 `api_agent/web.py` 和 `blueprint.py`；
- API 不复制功能 Review、功能页面和功能 Prompt；
- Controller contracts/policies 属于 API 项目，可被 Egress/Agent 在该项目内部引用；
- Executor 仍只包含标准库 Runner，不安装 Agent、LLM、数据库或平台依赖；
- 依赖从现有 API/Controller lock 冻结迁入，拆分期不顺便升级；
- API 四镜像使用同一 Release 元数据。

### 5.3 旧目录映射

| 旧路径 | 功能目标 | API 目标 | 处理 |
|---|---|---|---|
| `agents/functional_test` | `src/functional_workflows` | — | 迁移并调整包路径 |
| `requirement_decomposition`、`rkm` | `src/functional_workflows` | — | 按实际调用迁移 |
| `agents/api_test` | — | `src/api_workflows` | 迁移并调整包路径 |
| `services/functional_agent` | `src/functional_agent` | — | 迁移 |
| `services/api_agent` | — | `src/api_agent` | 迁移 |
| `services/execution_controller` | — | `src/execution_controller` | 迁移 |
| `services/egress_proxy` | — | `src/egress_proxy` | 迁移 |
| `executor` | — | `src/executor` | 迁移 |
| `services/common/review.py` | `src/runtime/review.py` | — | 功能独占 |
| `services/common/case_review.py` | `src/runtime/case_review.py` | — | 功能独占 |
| `services/common/versioned_review.py` | `src/runtime/versioned_review.py` | — | 功能独占 |
| 通用 task/config/file/security 模块 | `src/runtime` | `src/runtime` | 按基线复制、裁剪、分别拥有 |
| `services/common/web.py` | `functional_agent/web.py` | `api_agent/web.py` | 按路由拆分，不整体复制 |
| 公共 templates/static | 功能资源归功能 | API 资源归 API | 不保留跨项目资源目录 |
| `tests/services` | 功能及契约测试 | API 公共契约测试 | 按被测模块拆分，必要契约分别保留 |
| `tests/api_v2` | — | API 测试 | 全部迁移 |
| `output/` | — | — | 不迁移、不修改 |

W02 必须输出逐文件清单，表格只定义原则，不能用目录级复制替代精确归属。

---

## 6. 公共运行时复制与治理

### 6.1 为什么不建第三个公共包

用户目标是两个目录可完全独立开发和操作。首期若提取第三个包，会增加版本、发布、兼容和故障依赖，因此本期明确采用两个项目分别拥有运行时实现。

### 6.2 复制清单

每个项目根目录保存 `SOURCE_SPLIT_BASELINE.md`，至少包含：

```text
baseline_tag
baseline_commit
source_path
source_sha256
target_path
target_sha256
ownership
copied_at
reason
```

迁移脚本只负责复制和校验，不在复制时自动格式化或改写业务逻辑。

### 6.3 双项目安全修复流程

对复制的身份、权限、文件 containment、脱敏、TaskStore 等安全模块：

1. 发现问题后创建一个主安全编号 `SEC-SHARED-YYYY-NNN`；
2. 在两个项目分别创建关联修复项；
3. 先判断漏洞是否同时适用，不机械同步无关代码；
4. 适用项目分别最小修复并添加复现测试；
5. 两个项目分别运行完整安全和回归测试；
6. 分别发布 Patch 版本，不要求同一时间部署，但高风险项目不得继续使用受影响版本；
7. 平台记录两个项目的修复 Release；
8. 在 `SOURCE_SPLIT_BASELINE.md` 的安全修复附录记录是否同步及原因。

建议响应目标：

| 等级 | 响应 | 修复目标 |
|---|---:|---:|
| Critical | 4 小时 | 24 小时或立即关闭能力 |
| High | 1 个工作日 | 3 个工作日 |
| Medium | 3 个工作日 | 下一 Patch/Minor |
| Low | 正常排期 | 后续版本 |

### 6.4 禁止重新耦合

CI 增加检查，拒绝：

- 源码出现 `AItestcase_Agents` 绝对/相对 import；
- 源码出现 `../functional-test-agent` 或 `../api-test-agent`；
- symlink 指向项目根外；
- `pyproject.toml`、requirements 出现本地兄弟路径；
- Dockerfile 使用项目父目录 context 或复制父目录文件；
- Compose 将兄弟源码目录挂入容器。

---

## 7. 配置、Secret 和版本设计

### 7.1 独立 Revision

平台不再向两个服务传同一个 `APP_REVISION`：

```text
FUNCTIONAL_AGENT_REVISION
API_AGENT_REVISION
```

API 的四个组件同时使用 `API_AGENT_REVISION`。页面继续输出 `app_revision`，值来自所属项目变量，HTTP 字段不变。

### 7.2 独立镜像变量

平台 `.env.example` 新增：

```text
AGENT_IMAGE_REGISTRY=
FUNCTIONAL_AGENT_IMAGE=functional-test-agent:0.1.0-local
API_AGENT_IMAGE=api-test-agent:0.1.0-local
API_EXECUTION_CONTROLLER_IMAGE=api-execution-controller:0.1.0-local
API_EGRESS_PROXY_IMAGE=api-egress-proxy:0.1.0-local
API_EXECUTOR_IMAGE=api-test-executor:0.1.0-local
FUNCTIONAL_AGENT_REVISION=local
API_AGENT_REVISION=local
```

prod 配置必须使用不可变 digest；本机允许使用明确 local tag，但禁止 `latest`。

### 7.3 Secret

保持现有平台 Secret 控制面，但挂载路径按服务最小化：

| Secret | 功能 | API Web | Controller | Executor |
|---|---:|---:|---:|---:|
| 功能 Platform Client Token | 是 | 否 | 否 | 否 |
| API Platform Client Token | 否 | 是 | 否 | 否 |
| 功能 LLM Key | 是 | 否 | 否 | 否 |
| API LLM Key | 否 | 是 | 否 | 否 |
| Controller Token | 否 | 是（只读） | 是（只读） | 否 |
| API DB Credential | 否 | 仅开关启用 | 否 | 否 |
| Target Credential | 否 | 后续受控 | 后续受控 | 仅单 Run，当前无 |

任何新项目 `.env`、镜像、日志和测试 fixture 不得包含真实 Secret。

### 7.4 功能开关

拆分后默认值保持：

```text
DATABASE_PERSIST_ENABLED=false
API_EXECUTION_ENABLED=false
ALLOWED_TARGETS=[]
```

功能 Review 开关继续由功能项目读取；API 配置不包含功能 Review 定义。首次生产发布即使管理员拥有执行权限，API 真实执行仍由 prod 代码门禁拒绝。

---

## 8. Docker 与 Compose 设计

### 8.1 项目镜像构建

功能：

```text
docker build -f Dockerfile -t functional-test-agent:<release> .
```

API：

```text
docker build -f Dockerfile.agent -t api-test-agent:<release> .
docker build -f Dockerfile.controller -t api-execution-controller:<release> .
docker build -f Dockerfile.egress -t api-egress-proxy:<release> .
docker build -f Dockerfile.executor -t api-test-executor:<release> .
```

每条命令的 context 都是所属项目根 `.`，不得从 `/Users/admin/Testproject` 构建。

### 8.2 平台 Compose 分层

`test-platform/docker-compose.yml`：

- 只使用 `image:` 变量；
- 保留服务名、网络、健康检查、端口和权限；
- 不包含两个新项目的 `build.context`；
- 不包含旧 `../AItestcase_Agents` 路径；
- prod 和普通本机运行都可直接消费已构建镜像。

`test-platform/docker-compose.local-build.yml`：

- 仅本机开发使用；
- 为功能和 API 服务增加各自 build context；
- 功能 context 为 `../functional-test-agent`；
- API 四镜像 context 为 `../api-test-agent`；
- 不覆盖安全配置、Secret 和数据根。

本机用法：

```text
docker compose -f docker-compose.yml -f docker-compose.local-build.yml build functional-test-agent
docker compose -f docker-compose.yml -f docker-compose.local-build.yml up -d functional-test-agent

docker compose -f docker-compose.yml -f docker-compose.local-build.yml build \
  api-test-agent api-execution-controller api-egress-proxy api-test-executor-image
docker compose -f docker-compose.yml -f docker-compose.local-build.yml up -d api-test-agent
```

S2 本机执行仍需显式 `--profile s2-execution` 和 `API_EXECUTION_ENABLED=true`，不因拆分默认启动。

### 8.3 资源和权限

保持现有：

- Agent 非 root、只读根、`cap_drop=ALL`、`no-new-privileges`；
- 功能和 API Web 不挂 Docker Socket；
- Controller 是唯一 Docker Socket 持有者；
- Executor 非 root、只读根、独立网络和资源限制；
- 功能服务不加入 API executor 网络；
- 每个服务只挂载所属项目 runtime 和 Secret。

### 8.4 镜像内容验证

构建后导出镜像文件清单并断言：

- 功能镜像不存在 `api_agent`、`api_workflows`、`execution_controller`、`egress_proxy`、`executor`；
- API 镜像不存在 `functional_agent`、`functional_workflows`、功能 Review Prompt 和功能工作台；
- 所有镜像不存在 `.git`、`.env`、`runtime`、`output`、缓存和测试临时文件；
- Executor 镜像不包含 LLM、数据库、平台 SDK 和其他项目代码。

---

## 9. HTTP、状态和产物兼容设计

### 9.1 URL

保持：

```text
/functional-test-agent/
/api-test-agent/
```

所有现有 `/api/v1` 路由保持，不在拆分中增加 v2 URL。

### 9.2 身份和权限

继续使用平台可信身份头、CSRF、所有权和 404 防枚举。拆分不改变：

- `tool.view`；
- `tool.result.view`；
- `tool.execute`；
- `task.cancel`；
- `task.view.all`；
- `api-test-agent.contract.review`；
- `api-test-agent.case.review`；
- `api-test-agent.defect.create`；
- `api-test-agent.execute`。

平台 Client Token 仍按工具隔离，工具 ID 与原值一致。

### 9.3 状态

功能状态和恢复语义保持：

```text
pending → running → waiting_review
waiting_review → pending → running → waiting_case_review/succeeded
waiting_case_review → succeeded
```

API V2 状态、Review 和 Run 状态保持。拆分不得借机重命名状态或 stage。

### 9.4 产物

保持现有 artifact type、JSON 字段、XLSX 列、报告和缺陷草稿 Schema。平台下载只依赖 artifact registry，不依赖宿主绝对路径。

### 9.5 Prompt 版本

Prompt 文件原样迁移，并记录拆分前后 SHA。若只有 import/包路径变化，Prompt bundle SHA 必须保持；如打包路径参与 SHA，应使用稳定的相对内容清单计算，不能因项目绝对路径变化导致虚假版本变化。

---

## 10. 任务数据迁移设计

### 10.1 源和目标

```text
源功能：AItestcase_Agents/runtime/<env>/functional/
目标功能：functional-test-agent/runtime/<env>/

源 API：AItestcase_Agents/runtime/<env>/api/
目标 API：api-test-agent/runtime/<env>/
```

容器内路径继续由 `AGENT_DATA_DIR` 指向固定任务根，不向 HTTP 响应暴露宿主路径。

### 10.2 迁移清单

迁移每个任务的：

- `task.json`、`request.json`、`execution.json`；
- `runner-result.json`、`artifacts.json`、`console.log`；
- `input/`、`work/`、`published/`；
- 功能 Review 草稿、AI 建议、确认版本；
- API version store、Run、报告和缺陷草稿。

不迁移：

- `AItestcase_Agents/output/`；
- `.env`、Secret、Token；
- `__pycache__`、`.pytest_cache`、临时文件和损坏隔离区之外的缓存；
- 运行中的容器或宿主进程。

### 10.3 状态迁移

| 源状态 | 迁移结果 |
|---|---|
| succeeded/failed/cancelled/partial_success | 原样迁移，只读校验 |
| pending | 保留 `created_at`、`queued_at` 和 task ID，新服务启动后按原 FIFO 排序恢复 |
| waiting_review | 原样迁移，草稿/确认版本可继续操作 |
| waiting_case_review | 原样迁移，草稿/AI 建议可继续操作 |
| waiting_contract_review | 原样迁移 |
| waiting_execution_confirmation | 原样迁移，确认 SHA 由当前用例和目标重新校验 |
| running | 数据迁移；启动恢复为 `failed/WORKER_INTERRUPTED`，不伪造续跑；用户按现有 retry/resume 重新排队 |
| API RUNNING Run | 切换前优先等待；无法结束则取消并保留证据，不跨 Controller 恢复正在运行的容器 |

### 10.4 迁移工具

新增一次性工具，分别放在两个新项目：

```text
scripts/migrate_legacy_runtime.py
```

参数设计：

```text
--source <absolute-path>
--destination <absolute-path>
--environment <dev|prod>
--dry-run
--verify-only
--manifest <path>
```

要求：

- source/destination 必须是明确绝对路径；
- 拒绝 `/`、用户主目录、项目根等宽泛目标；
- 禁止跟随 symlink；
- 先生成 manifest，再复制到临时目标，最后原子切换；
- 使用 SHA-256、相对路径、大小和权限校验；
- destination 已存在不同内容时阻断，不覆盖；
- dry-run 不写入；
- 失败时保留 source，不清理旧数据；
- 日志不输出正文和 Secret。

### 10.5 切换步骤

1. 网关进入工具维护状态，拒绝新建和写请求；
2. 等待普通 running 任务完成；
3. 检查 API Executor 无残留；
4. 停止旧功能和 API 服务；
5. 分别执行 dry-run；
6. 生成源 manifest 和 SHA；
7. 复制到两个新 runtime 临时目录；
8. verify-only 通过后原子改名为正式目录；
9. 源目录改为只读；
10. 先启动新功能，执行恢复和历史读取检查；
11. 再启动新 API，执行恢复和历史读取检查；
12. 解除维护状态；
13. 保存迁移报告、差异和回滚点。

### 10.6 幂等和回滚

相同 source manifest 重试不得重复生成任务或 Review 版本。回滚时：

- 停止新服务写入；
- 保存新服务切换后的增量数据 manifest；
- 如果旧服务可兼容，将增量任务按同一工具回迁；
- 若无法安全回迁，则新任务保持新服务只读，网关临时提供新旧历史入口，不覆盖旧数据；
- 平台镜像引用切回旧版本；
- 任何回滚都不删除新旧数据根。

---

## 11. 旧历史和归档设计

### 11.1 历史入口保留

- 从切换完成日起至少保留 180 天；
- 两个稳定 Release 完成前不得归档旧源码；
- 180 天内旧任务必须能通过新服务迁移数据访问，或通过管理员只读入口访问；
- 到期前 30 天生成使用量和未访问任务报告；
- 到期不自动删除，管理员书面批准后才能下线入口；
- 历史 `output/` 不接入普通用户页面。

### 11.2 归档路径

目标：

```text
/Users/admin/Testproject/archive/AItestcase_Agents/ai-agents-split-baseline-20260817/
├── source/
├── legacy-runtime/
├── output/               # 原样保留，不导入
├── manifests/
├── test-reports/
└── README.md
```

### 11.3 权限

- 归档目录由本机管理员拥有；
- 目录默认 `0555`，文件默认 `0444`；
- Secret 文件不进入归档；如旧目录存在 Secret，只记录已排除项和轮换状态；
- 新服务和平台 Compose 不挂载 archive；
- 修改归档前必须由管理员临时解除只读并记录原因；
- 归档不等于删除，后续删除需单独不可逆操作审批。

### 11.4 归档时机

只有以下条件全部满足才执行：

1. 功能项目至少两个稳定 Release；
2. API 项目至少两个稳定 Release；
3. 独立升级和回滚演练通过；
4. 所有旧非终态任务已迁移或转为可解释终态；
5. 数据 manifest/SHA 验证通过；
6. 平台和新项目不再引用旧源码路径；
7. 管理员批准归档窗口。

---

## 12. 本机独立开发流程

### 12.1 功能项目

目标命令：

```text
python3 -m pytest -q
docker build -t functional-test-agent:<release> .
docker compose -f compose.local.yml config
docker compose -f compose.local.yml up -d
docker compose -f compose.local.yml down
```

`compose.local.yml` 可使用平台已经运行的外部网络和只读 Secret，但不得读取平台源码或 API 项目源码。若平台未运行，单元和集成测试必须仍可使用 Mock Platform Client 完成。

### 12.2 API 项目

目标命令：

```text
python3 -m pytest -q
docker compose -f compose.local.yml build
docker compose -f compose.local.yml up -d api-test-agent
docker compose -f compose.local.yml --profile s2-execution up -d
docker compose -f compose.local.yml down
```

S2 Profile 默认关闭；没有明确本机试点配置时，API execute 必须返回稳定禁用错误。

### 12.3 平台集成

从 `test-platform` 可分别执行：

```text
docker compose up -d functional-test-agent
docker compose up -d api-test-agent
docker compose stop functional-test-agent
docker compose stop api-test-agent api-execution-controller api-egress-proxy
```

不得要求同时重建或重启两个服务。

---

## 13. 测试设计

### 13.1 基线测试

W01 重新记录当时实际数量，不硬编码旧的 112 项结果。至少运行：

```text
cd AItestcase_Agents && python3 -m pytest -q
cd test-platform/backend && python3 -m pytest -q
cd test-platform/frontend && npm test -- --run && npm run build
cd test-platform && python3 -m unittest discover -s tests -v
cd test-platform && docker compose config
```

平台 smoke 若仍受本地登录凭据限制，必须使用隔离账号或浏览器已有会话，不得重置真实用户凭据绕过。

### 13.2 功能项目测试

- 原需求拆解、测试点和测试用例工作流；
- 四种 operation 和 CLI 兼容；
- 测试点 Review 草稿、CAS、导入、确认、resume 和 FIFO；
- 测试用例 Review、覆盖、AI、同源 JSON/XLSX 和公式注入；
- Brain map/工作台等当前用户新增功能完整回归；
- TaskStore 原子写、损坏隔离、保留、取消和恢复；
- 上传、artifact、身份、权限、CSRF、所有权和脱敏；
- 干净目录安装和镜像构建；
- 镜像内容不包含 API 源码；
- 1280×800、1440×900 浏览器验收。

### 13.3 API 项目测试

- OpenAPI/Swagger/非结构化解析和硬门禁；
- 契约 Review、基础用例、覆盖、用例 Review、可执行用例；
- 数据库写入关闭/开启/失败；
- 任务、版本、阶段重试和中间产物；
- 执行确认 SHA、Run、报告、取消、重试、缺陷草稿；
- Controller Token、窄协议、固定镜像和资源策略；
- Egress SSRF、DNS、Host、path、重定向和 metadata；
- Executor 脱敏、输出大小、超时和回收；
- 默认执行关闭和 prod 固定禁止；
- 干净目录构建四个镜像；
- 镜像内容不包含功能源码。

### 13.4 契约测试

两个项目分别保存平台消费方契约 fixture，覆盖：

- 任务公共字段；
- 错误响应；
- 日志游标；
- artifact registry；
- 版本展示；
- 身份头、权限和 CSRF；
- 配置/Secret snapshot；
- health/readiness。

`test-platform` 保留对两个服务的消费者契约测试，防止某个项目独立发布时破坏平台。

### 13.5 黄金样例

功能：

- 个人中心需求文档；
- 测试点 Review JSON；
- 测试用例 Review JSON/XLSX；
- 当前脑图/任务工作台样例。

API：

- LoginApi_Doc；
- OpenAPI 3.x、Swagger 2.0；
- 非结构化 Markdown；
- 本机健康目标和 metadata 负向目标。

比较：Schema、ID、状态、数量、关键字段、artifact type、SHA 计算规则和失败码。LLM 文本不要求逐字一致。

### 13.6 独立性测试

自动化检查：

1. 将功能项目复制到临时目录，只保留该目录，运行测试和构建；
2. 将 API 项目复制到另一临时目录，只保留该目录，运行测试和四镜像构建；
3. 拒绝指向项目根外的 symlink；
4. 扫描源码、锁、Dockerfile、Compose 中的旧路径和 sibling path；
5. 扫描镜像文件清单；
6. 修改功能文件，证明 API 构建缓存和 digest 不变化；
7. 修改 API 文件，证明功能构建缓存和 digest 不变化；
8. 分别停止、升级和回滚，另一个服务持续健康。

### 13.7 数据迁移测试

- dry-run 无写入；
- source/destination containment；
- symlink/path traversal 拒绝；
- 同内容幂等；
- 不同内容冲突阻断；
- pending FIFO 保持；
- waiting Review 草稿可继续；
- running 转 `WORKER_INTERRUPTED`；
- API Run 和报告完整；
- 中途中断不产生正式半目录；
- manifest/SHA 校验；
- 回滚保留新旧数据。

---

## 14. 发布与回滚设计

### 14.1 发布顺序

```text
旧仓基线冻结
  → 功能项目本机 Release F1
  → 功能独立性与回滚
  → API 项目本机 Release A1（执行关闭）
  → API 独立性与安全回归
  → 平台镜像引用切换
  → 非终态任务迁移
  → 双项目 Release F2/A2
  → 旧仓只读归档
```

### 14.2 功能回滚

1. 网关暂停功能写请求；
2. 停止新功能容器；
3. 将 `FUNCTIONAL_AGENT_IMAGE` 切回上一版本；
4. 如数据仍兼容，继续挂载新功能 runtime；
5. 如需旧服务，切回旧镜像和旧只读数据根；
6. 验证 API 镜像、容器、Run 和数据未变化；
7. 恢复功能入口。

### 14.3 API 回滚

1. 设置 `API_EXECUTION_ENABLED=false`；
2. 停止 Controller/Egress 并回收受管 Executor；
3. 暂停 API 写请求；
4. 将 API 四个镜像同时切回上一兼容 Release；
5. 验证 Run、报告和任务目录；
6. 验证功能镜像、容器和任务未变化；
7. 恢复 API 可信生成和 Review；
8. 不在回滚中重新启用真实执行。

### 14.4 数据回滚

原则是保留而非覆盖。任何增量数据不能直接复制回旧目录覆盖同名文件。必须先形成增量 manifest，再决定：

- 旧服务可兼容：按任务 ID 导入不存在任务；
- 不兼容：新服务保持历史只读，旧服务仅处理旧任务；
- 冲突：阻断并由管理员选择权威版本；
- Review/Run 不做字段级合并。

---

## 15. 可观测与运维

### 15.1 版本展示

任务详情和 readiness 至少展示：

- project name；
- project release；
- app revision；
- image digest（受保护 readiness）；
- config release；
- model 和 Prompt hash。

### 15.2 日志

两个项目使用独立服务名和日志流。日志不得输出：

- 绝对宿主路径；
- Client Token、LLM Key、Controller Token；
- 完整 Header/Cookie/Query；
- 未脱敏正文和响应；
- 另一个项目的配置或任务数据。

### 15.3 健康和故障隔离

- 功能 health 只检查功能进程和本地存储；
- API Agent health 不访问 LLM、目标或数据库；
- Controller/Egress 只在 S2 Profile 中检查；
- 一个服务 unhealthy 不改变另一个工具卡片状态；
- 平台首页分别读取两个健康状态和 Revision。

---

## 16. 文件影响清单

### 16.1 新增目录

```text
/Users/admin/Testproject/functional-test-agent/
/Users/admin/Testproject/api-test-agent/
```

仅在实施 W03/W06 时创建。本设计文档不提前创建空目录。

### 16.2 平台预计修改

```text
test-platform/docker-compose.yml
test-platform/docker-compose.local-build.yml
test-platform/.env.example
test-platform/README.md
test-platform/tests/test_smoke.py
test-platform/backend/tests/（必要的消费者契约测试）
test-platform/frontend/（仅当 Revision 展示需要兼容调整）
```

Nginx 路由原则上不改；如只变上游镜像，不应修改 URL 和权限配置。

### 16.3 旧仓

实施期只允许：

- 读取和生成归属清单；
- 增加迁移兼容测试或必要的阻断修复；
- 创建可追溯基线 tag（需用户现有修改先妥善保存）；
- 切换完成后添加只读归档说明。

不得顺便重构或删除旧源码、runtime、output 和用户新增功能。

---

## 17. 工作包计划

### W01 基线冻结

任务：

- 保护当前用户修改；
- 记录 commit/status/未跟踪文件；
- 运行两项目现有测试、平台测试、构建和 Compose 检查；
- 记录 Prompt、Schema、artifact、任务目录和镜像摘要；
- 建立黄金输入；
- 创建可复现基线后打 `ai-agents-split-baseline-20260817`。

交付：基线清单、测试报告、SHA manifest、tag。

门禁：不得丢失当前功能工作台 V2 等用户新修改。

### W02 逐文件归属

任务：

- 枚举旧仓全部运行源码、模板、静态资源、Prompt、测试和部署文件；
- 标记 `functional`、`api`、`copy-both`、`legacy-only`、`exclude`；
- 记录 SHA、依赖调用方和目标路径；
- 识别动态 import、路径字符串和资源加载。

交付：`split-inventory.json`、人类可读映射表。

门禁：无未归属运行文件。

### W03 功能工程骨架

任务：

- 创建 `functional-test-agent`；
- 建立 `src` 包、pyproject、锁、pytest、Dockerfile、ignore 和 README；
- 建立本机 Release/Revision 读取；
- 只迁移最小启动路径。

验证：干净目录安装、导入和 health 测试。

### W04 功能源码迁移

任务：

- 迁移功能工作流、Prompt、Review、UI 和 CLI；
- 拆解旧公共 web/task manager；
- 迁移当前脑图/工作台 V2 等最新功能；
- 调整 import 和资源路径；
- 保持 Prompt/Schema/API 兼容。

验证：功能全量测试、黄金样例、浏览器流程。

### W05 功能独立镜像与操作

任务：

- 构建本地镜像；
- 验证非 root、只读根、最小挂载和镜像内容；
- 完成 compose.local 和平台 dev 接入；
- 验证单独启动/停止/升级/回滚。

门禁：镜像不含 API 源码，API 容器/digest 不变化。

### W06 API 工程骨架

任务：

- 创建 `api-test-agent`；
- 建立 Agent/Controller 锁、四个 Dockerfile、pytest 和 README；
- 建立统一 API Release 元数据；
- 只迁移最小 Agent health 和 Controller contract。

验证：干净目录安装、四镜像最小构建。

### W07 API 源码迁移

任务：

- 迁移解析、契约、用例、Review、任务、报告和缺陷；
- 迁移 API Web 模板和静态资源；
- 迁移可选数据库持久化；
- 拆解公共 web/task model；
- 保持 V2 状态和 Schema。

验证：API 可信生成全回归和黄金样例。

### W08 API 执行组件迁移

任务：

- 迁移 Controller、Egress、Executor；
- 保持固定镜像、窄协议、目标策略、资源限制和脱敏；
- 四镜像绑定同一 Release；
- 默认关闭 S2，prod 固定禁止。

验证：S2 单元/安全测试、本机获批目标正向与 metadata 负向。

### W09 平台镜像接入

任务：

- 主 Compose 改为 image-only；
- 新增 local build override；
- 增加独立镜像/Revision 变量；
- 保持 Nginx、权限、Secret 和健康检查；
- 更新 README 和 smoke/contract 测试。

验证：普通 Compose config、local override config、平台回归。

### W10 任务数据迁移

任务：

- 实现两个 migration tool；
- 覆盖状态映射、SHA、幂等、containment 和中断；
- 维护窗口 dry-run；
- 分别复制功能/API runtime；
- 新服务启动恢复并验证历史任务。

门禁：非终态任务可解释恢复，running 不伪造续跑，旧数据只读保留。

### W11 独立性 E2E

任务：

- 执行干净目录构建；
- 互不重建、互不停机、互不访问数据/Secret；
- 分别升级和回滚；
- 两套浏览器核心流程；
- 平台跨用户权限矩阵。

门禁：任一隔离失败都阻断切换。

### W12 灰度和旧仓归档

任务：

- 发布功能 F1、API A1；
- 观察并完成回滚演练；
- 发布 F2/A2；
- 满足条件后迁入 archive；
- 设置只读权限和 180 天历史策略；
- 输出最终交付报告。

门禁：管理员批准；API 生产执行仍关闭。

---

## 18. 依赖与里程碑

```text
W01 → W02 → W03 → W04 → W05
                    ↓
                   W06 → W07 → W08
                                  ↓
                                 W09 → W10 → W11 → W12
```

里程碑：

| 里程碑 | 工作包 | 结果 |
|---|---|---|
| M0 可复现基线 | W01～W02 | 可安全开始拆分 |
| M1 功能独立 | W03～W05 | 功能可独立开发、构建和回滚 |
| M2 API 独立 | W06～W08 | API 四镜像可独立发布 |
| M3 平台切换 | W09～W10 | 平台消费独立镜像，任务完成迁移 |
| M4 完成交付 | W11～W12 | 隔离验收、灰度、回滚和旧仓归档完成 |

粗略投入建议：

| 阶段 | 预计工程量 |
|---|---:|
| W01～W02 | 2～3 人日 |
| W03～W05 | 5～8 人日 |
| W06～W08 | 7～10 人日 |
| W09～W10 | 4～6 人日 |
| W11～W12 | 3～5 人日 |
| 合计 | 21～32 人日 |

估算不含外部 LLM 配额、生产审批、远程 Git/镜像仓库申请时间。

---

## 19. 每工作包执行规则

每个工作包必须遵循：

1. 更新计划状态；
2. 先读取目标文件、调用方和现有测试；
3. 只修改该工作包需要的文件；
4. 运行本包测试；
5. 失败先复现、定位、最小修复；
6. 运行相关回归；
7. 记录文件、命令、结果和未验证外部依赖；
8. 不提交、推送、建远程仓或删除旧目录，除非用户另行授权；
9. 不覆盖当前用户未提交修改；
10. 不因拆分顺便升级无关依赖或重做 UI。

---

## 20. 完成标准

全部满足后方可完成：

- [ ] 两个固定目录已创建并成为唯一新功能开发入口；
- [ ] 两个目录可在干净环境独立安装、测试、构建；
- [ ] 无跨项目、旧仓和兄弟目录源码依赖；
- [ ] 功能一个镜像、API 四镜像分别按 Release 管理；
- [ ] 平台主 Compose 只消费独立镜像；
- [ ] 功能和 API 使用独立 Revision、Secret、数据根和操作入口；
- [ ] 现有终态和非终态任务迁移完成；
- [ ] pending/Review 恢复，running 按规则转为可重试失败；
- [ ] HTTP、权限、Prompt、Schema、产物和 CLI 兼容；
- [ ] 功能、API、平台、迁移、镜像、安全和浏览器测试通过；
- [ ] 单独升级、停止、故障和回滚不影响另一个项目；
- [ ] 两个稳定 Release 后旧仓完成只读归档；
- [ ] 历史入口至少保留 180 天且不自动删除；
- [ ] 历史 `output/` 未迁移、未修改、未删除；
- [ ] 首次生产发布继续保持 API 真实执行关闭；
- [ ] W01～W12 交付记录完整。

---

## 21. 实施启动记录

以下信息在 W01 执行时自动记录，不再作为技术方案评审项：

1. 当前用户修改通过 Git 状态、文件 SHA 和基线补丁/提交形成可追溯记录；
2. Release 与紧急回滚责任人记录为执行时的本机平台管理员账号；
3. 首次本机 Release 默认使用 `0.1.0-local.<date>.<sha>`；
4. 远程 Git、远程镜像仓库和 prod 部署平台不阻塞本机实施，首次推送或生产发布前再补充外部标识。

---

## 22. 设计结论

本设计采用两个自包含项目、公共运行时按基线复制并独立拥有、平台通过镜像和 HTTP 契约消费的方案。它避免引入第三个公共包，也不通过路径技巧制造隐式依赖，能够真正满足两个智能体分别开发、构建、操作、发布和回滚。

实施按“冻结基线 → 功能拆分 → API 拆分 → 平台切换 → 数据迁移 → 独立性验收 → 旧仓归档”推进。非终态任务被完整迁移，但正在运行的进程不伪造跨仓续跑；旧数据和旧仓始终保留回滚窗口。首次生产范围只包含可信生成和 Review，API 真实执行继续保持关闭。
