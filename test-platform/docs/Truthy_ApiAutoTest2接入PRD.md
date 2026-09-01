# api-autotest 接入测试开发平台 PRD

> 文档版本：V1.2  
> 创建日期：2026-08-07  
> 文档状态：已评审（确认项结论见配套开发设计文档第 22 章）  
> 修订记录：V1.2（2026-08-10）补充任务并发与原子落盘、二次脱敏、配置级凭证预检、取消结果边界；报告改为拉取最近已完成且有产物的 Jenkins 构建，并通过版本目录 + current 指针原子发布；8.3 环境变量清单补 `API_AUTOTEST_REPORT_DIR`  
> 修订记录：V1.1（2026-08-07）根据确认项结论修订执行链路：平台执行命令对齐 Jenkins、平台任务不生成 allure-results、报告改为 Jenkins 归档 + 宿主机拉取发布  
> 接入工具：`api-autotest` / Gateway 接口自动化 V1.3<br>
> 目标平台：`test-platform`  
> 目标入口：`/api-autotest/`  
> 方案定位：薄 Web 服务包装（任务型工具，即评审结论中的“方案 C”）

相关文档：

- [TestPlatform_MVP_PRD.md](../../TestPlatform_MVP_PRD.md)：平台接入总原则与新工具接入规范；
- [平台框架升级开发设计与计划.md](./平台框架升级开发设计与计划.md)：工具分类（页面型 / API 型 / 任务型）与标准任务协议；
- [Truthy_Search接入开发设计与计划.md](./Truthy_Search接入开发设计与计划.md)：前一个工具的接入先例；
- `api-autotest/README.md`、`api-autotest/Jenkinsfile`：被接入工具的现状依据。

---

## 1. 项目背景

测试开发平台目前已聚合三个**页面型**工具：埋点测试（`trackevents`）、日志分析（`log-filter`）、检索评测（`truthy-search`）。三者均为常驻 Web 服务，接入模式统一为：可配置基础路径 + 健康检查 + Dockerfile + 平台 Compose/Nginx/工具目录注册。

`api-autotest` 是基于 Python、pytest、requests、PyYAML 的数据驱动接口自动化框架，特点与已接入工具不同：

- 它是**批跑型 CLI 框架**：通过 `runtest.py --env/--tag/--flow/--module` 触发 pytest 执行，无常驻 Web 页面；
- 用例资产全部为 YAML：`data/apis/`（接口定义）、`data/cases/`（单接口用例）、`data/flows/` + `data/scenarios/`（多接口流程）；
- 运行产物明确：JUnit XML（`reports/junit*.xml`）、Allure 原始结果（`allure-results/`）、脱敏执行日志（`logs/YYYY-MM-DD/`）；
- 已有 Jenkins 流水线承担参数化执行、JUnit/Allure 发布与产物归档；
- 凭证（`AUTH_TOKEN`、`REFRESH_TOKEN` 等）保存于项目根目录 `.env`，框架自动复用/刷新会话，**刷新成功后会将新会话写回 `.env`**。

平台框架升级方案已将“接口自动化”归类为**任务型工具**，并定义标准任务协议：提交、查询状态、取消、获取结果、健康检查。本 PRD 按该定位定义接入需求，使 `api-autotest` 成为平台第一个任务型工具，为后续平台任务中心（`ApiAutomationAdapter`）预留对端。

---

## 2. 产品目标

### 2.1 目标

为 `api-autotest` 建设一个**薄 Web 服务**（下称“工具壳服务”），以独立容器接入平台，在不修改框架核心逻辑的前提下提供：

1. 平台首页出现“接口自动化”工具卡片，入口固定为 `/api-autotest/`；
2. 在平台页面上选择参数并**触发接口自动化执行**；
3. 查看任务状态、取消运行中的任务；
4. 查看任务结果：JUnit 通过/失败摘要、脱敏执行日志；
5. 查看由 Jenkins/宿主机链路生成并同步过来的 **Allure HTML 报告**；
6. 只读浏览用例库（API 定义、单接口 Case、Flow 清单）；
7. 保留框架完全独立运行能力：终端 `runtest.py`、Jenkins 链路均不受影响。

### 2.2 成功标准

- 一条 Docker Compose 命令启动平台后，首页展示第四个工具卡片且状态可探测；
- 通过 `/api-autotest/` 可提交一次执行任务（环境 + 运行类型 + 可选 Flow/标签），获得任务 ID；
- 任务状态机完整：`pending → running → succeeded/failed/cancelled`；
- 运行中的任务可以被取消，取消后 pytest 子进程终止；取消过程中已完整写出的产物保留，JUnit 未生成时页面明确标注“结果不可用”；
- 任务正常结束且 JUnit 已生成时，5 秒内可在页面看到统计摘要（总数、通过、失败、跳过、错误）；
- 任务详情页可查看该次执行产生的脱敏日志；框架日志之外的控制台兜底内容必须经过壳服务二次脱敏；
- Jenkins/宿主机生成 Allure HTML 报告并同步到约定目录后，平台页面可直接打开报告，并展示构建号、构建结果与生成时间；
- 同一时间最多只有一个执行任务处于 `pending`/`running`；并发提交通过原子互斥保证只有一个成功，其余明确拒绝（MVP 不排队）；
- 停止 `api-autotest` 容器不影响平台首页和其他三个工具；
- 平台 API 或 PostgreSQL 异常时，首页仍保留该工具的基础入口（前端回退目录）；
- `api-autotest` 仍可脱离平台独立运行：终端行为不变，Jenkins 执行阶段与测试语义不变；Jenkins post 仅增加 HTML 生成和归档；
- 框架现有自动化回归（不发送真实请求的部分）全部通过；
- 平台只暴露网关端口，`5003` 不映射到宿主机。

### 2.3 非目标

本期明确不包含：

- 登录、RBAC、工具级权限（平台当前整体无鉴权，部署于受控内网；按评审结论先不考虑）；
- 任务记录写入平台 PostgreSQL / 平台任务中心（属于框架升级阶段 4，本期工具侧自持任务记录）；
- 在容器内安装 Node / Allure CLI / 在容器内生成 Allure HTML 报告；
- 用例的在线编辑、新增、删除（用例库只读）；
- 定时/周期触发执行（后续可接平台定时任务能力）；
- 执行进度百分比（pytest 无进度语义，仅提供状态与最终统计）；
- 多环境扩展（仅支持 `config/env/` 下已存在的环境，当前为 `test`）；
- 平台代替框架做断言、报告重算或结果二次加工；
- 移动端适配。

---

## 3. 用户与使用场景

### 3.1 目标用户

- 测试工程师：触发冒烟/回归执行、查看结果与报告；
- 测试开发工程师：浏览用例库、定位失败用例、排查执行日志；
- 研发人员：查看接口回归结果和 Allure 报告。

### 3.2 核心场景

#### 场景一：在平台触发一次接口回归

1. 用户打开平台首页，点击“接口自动化”卡片进入 `/api-autotest/`；
2. 在执行区选择：环境（默认 `test`）、运行类型（全部 / 单接口 / Flow）、可选 Flow 名称、可选标签；
3. 提交后获得任务 ID，页面显示“运行中”；
4. 执行结束后状态变为“成功”或“失败”，页面展示通过/失败统计；
5. 用户点入任务详情查看脱敏日志，定位失败原因。

#### 场景二：查看最新 Allure 报告

1. Jenkins 或宿主机脚本已完成一次执行并生成 Allure HTML 报告，同步到平台约定目录；
2. 用户在工具首页“报告”区看到最新报告及其同步时间；
3. 点击后在平台路径内打开 Allure 报告，浏览后可返回工具首页。

#### 场景三：浏览用例库

1. 用户进入“用例库”页签；
2. 查看 API 定义列表（API ID、名称、service/method）、单接口 Case 列表（Case ID、名称、标签）、Flow 列表（名称、步骤数、标签）；
3. 数据全部只读，修改 YAML 需回到代码仓库。

#### 场景四：取消运行中的任务

1. 用户误提交了大范围执行；
2. 在任务列表点击“取消”；
3. 任务状态变为 `cancelled`，pytest 子进程被终止，后续用例不再执行。

#### 场景五：工具不可用

1. `api-autotest` 容器未启动或异常；
2. 平台首页卡片显示“异常”；
3. 用户点击进入时看到统一的“工具暂时不可用”错误页；
4. 平台首页和其他工具不受影响。

---

## 4. 总体方案

### 4.1 方案定位与架构原则

- 遵循平台既定接入模式：独立项目、独立容器、可配置基础路径、健康检查、平台只做导航/代理/注册；
- 按“任务型工具”落地标准任务协议（提交、查询状态、取消、获取结果、健康检查）；
- 工具壳服务是**薄层**：只负责页面、任务编排（构造与 Jenkins 语义一致的 pytest 命令并子进程执行）、产物读取与静态报告托管；不复制、不修改框架核心逻辑；
- **两条执行链路并存且互不替代**：
  - 链路 A（Jenkins/宿主机）：既有 CI 链路，负责正式回归执行与 **Allure HTML 报告生成**；Jenkins 归档产物，由宿主机拉取脚本发布到平台目录（见开发设计文档第 12 章）；
  - 链路 B（平台触发）：工具壳服务在容器内以子进程执行 pytest（命令与 Jenkins 语义一致），产出 JUnit XML 与脱敏日志；**不生成 `allure-results` 与 Allure HTML**（确认项 8 结论）。
- 报告展示统一收口：无论哪条链路产生，Allure HTML 报告只通过“同步到约定目录”这一种方式进入平台。

### 4.2 总体架构

```text
浏览器
  │
  ▼
platform-gateway (Nginx, 唯一对外端口 8080)
  ├── /                    平台首页（React）
  ├── /api/v1/             platform-api（工具目录与健康探测）
  ├── /trackevents/        埋点测试
  ├── /log-filter/         日志分析
  ├── /truthy-search/      检索评测
  └── /api-autotest/       api-autotest:5003  ← 本次新增
          │
          ▼
  工具壳服务（api-autotest 薄 Web 层）
  ├── 执行触发：子进程调用 pytest（命令对齐 Jenkins，链路 B）
  ├── 任务记录：文件级存储（tasks 目录）
  ├── 结果读取：reports/junit-*.xml、logs/YYYY-MM-DD/
  ├── 报告托管：挂载的 Allure HTML 目录（链路 A 同步产物）
  └── 用例库：只读解析 data/apis|cases|flows

  Jenkins / 宿主机脚本（链路 A）
  ├── 执行 pytest + 生成 Allure HTML
  └── 同步报告 → api-autotest/reports/allure-reports/<version>/
                → api-autotest/reports/allure-current
                    （平台容器以卷挂载方式读取 current 指向版本）
```

### 4.3 首期技术选型

| 模块 | 选择 | 理由 |
|---|---|---|
| 工具壳服务 | Python + 轻量 Web 框架（具体选型见开发设计文档） | 与框架同语言同依赖，复用 `requirements.txt` |
| 执行方式 | 子进程调用 pytest（入口文件与 Jenkinsfile 一致） | 不修改框架执行语义，与 Jenkins 链路完全对齐 |
| 任务记录 | 文件级存储（JSON），不引入任务数据库 | 单实例单任务；通过互斥与临时文件原子替换保证并发读写安全 |
| Allure HTML | 容器外生成、目录同步、静态托管 | 避免在镜像内引入 Node/Allure，控制镜像体积与维护面 |
| 容器 | 独立 Dockerfile，build context 为 `../api-autotest` | 与既有三个工具一致 |
| 平台注册 | tools 表迁移 + 前端回退目录 + Nginx 路由 | 与既有接入模式一致 |

---

## 5. 功能需求

### 5.1 平台首页工具卡片

| 字段 | 取值 |
|---|---|
| 工具 ID | `api-autotest` |
| 名称 | 接口自动化 |
| 描述 | 触发 Gateway 接口自动化执行，查看回归结果与 Allure 报告 |
| 入口路径 | `/api-autotest/` |
| 短码 | `API` |
| 图标 | `api`（新增图标） |
| 分类 | `automation` |
| 特性 | 执行触发、结果统计、报告查看 |
| 排序 | `40` |

卡片状态由平台既有健康探测机制展示（正常 / 异常 / 检测中），与其他工具一致。

### 5.2 工具首页（概览）

工具首页至少包含：

- 工具名称、简介、“返回平台”入口（指向 `PLATFORM_HOME_URL`）；
- 执行区：任务提交表单（见 5.3）；
- 当前运行状态提示：是否有任务运行中（运行中时禁用提交并提示）；
- 报告区：最新外部 Allure HTML 报告入口、同步时间、来源；Jenkins 来源展示构建号与构建结果，并提示“与平台任务无直接关联”；报告不存在时显示“暂无报告”；
- 任务列表区：最近任务（状态、运行类型、提交时间、耗时、结果摘要），可进入详情；
- 用例库入口；
- 配置就绪状态提示：按当前环境与所选 Flow 区分“基础配置就绪 / 缺失”和“任务专属凭证就绪 / 缺失”，只展示缺失字段名，**不展示任何 token 值**。

### 5.3 执行触发（任务提交）

提交参数：

| 参数 | 必填 | 取值 | 说明 |
|---|---|---|---|
| `env` | 是 | `config/env/*.yaml` 已存在的环境名（当前 `test`） | 默认 `test` |
| `run_type` | 是 | `all` / `single` / `flow` | 与 Jenkins `RUN_TYPE` 语义一致 |
| `flow` | 否 | `data/flows/` 下 Flow 文件名（不含 `.yaml`） | `run_type=flow` 时必填；`all` 时可选（仅执行指定 Flow）；`single` 时必须为空 |
| `tag` | 否 | pytest `-m` 标签表达式 | 对应 `runtest.py --tag` |

约束：

- 提交前校验 `env`、`flow` 是否真实存在（读取 `config/env/`、`data/flows/` 目录），非法值直接拒绝并提示；
- 存在运行中任务时拒绝新提交，返回明确错误（MVP 不做排队）；
- 提交成功立即返回任务 ID 与 `pending` 状态，执行异步进行；
- 不提供任意 pytest 参数透传（避免注入面，`--module` 等高级筛选不进入 MVP 页面）。

### 5.4 任务列表与状态

- 任务列表按提交时间倒序展示，MVP 保留最近 50 条；
- 每条任务展示：任务 ID、提交时间、参数摘要（env/run_type/flow/tag）、状态、耗时、通过/失败统计（结束后）；
- 状态机与平台标准协议一致：

```text
pending → running → succeeded
pending → running → failed
pending → cancelled
running → cancelled
```

- `failed` 包含两类：pytest 退出码非 0（存在失败用例）与执行启动/运行异常；两者在任务详情中通过错误信息区分；
- 页面通过轮询刷新任务状态（建议间隔 5 秒，仅在有未终态任务时轮询）。

### 5.5 任务取消

- 仅 `pending` / `running` 状态可取消；
- 取消动作为终止 pytest 子进程组；确认进程退出后状态置为 `cancelled`，且等待线程不得再用退出码覆盖该终态；
- 取消后保留已经完整写出的日志与 JUnit；pytest 未执行到 JUnit 写出阶段时允许没有 JUnit，不承诺产生“部分 JUnit”；
- 取消是尽力而为：先发送终止信号，宽限期内未退出时强制终止；取消与任务自然结束同时发生时，以受互斥保护的首次合法终态为准。

### 5.6 任务结果查看

任务详情页提供：

- 参数摘要与状态时间线（提交、开始、结束时间）；
- JUnit 统计：总数、通过、失败、错误、跳过（解析该任务的 `junit-*.xml`）；JUnit 不存在时返回 `result_available=false` 与稳定原因码，不把缺失文件本身改写为新的任务终态；
- 失败用例清单：用例名与失败摘要（来自 JUnit XML，不重新计算）；
- 脱敏日志查看：展示该次执行对应的 `logs/YYYY-MM-DD/` 日志文件内容（支持尾部查看与按任务筛选）；
- 错误信息：启动失败或运行异常时展示稳定错误码与经过脱敏、截断的摘要；禁止直接返回原始 stdout/stderr、traceback 或容器绝对路径。

边界：工具壳只**读取和展示**框架产物，不重新断言、不重算指标、不修改产物；对 `console.log` 等非框架脱敏产物必须执行壳服务二次脱敏后才能展示。

### 5.7 Allure 报告查看

- 报告来源：链路 A（Jenkins/宿主机）生成 Allure HTML 后同步到约定目录（见第 9 章）；
- 工具壳以静态文件方式在 `/api-autotest/reports/` 下托管该目录；
- 首页报告区展示最新外部报告入口、同步时间、来源、Jenkins 构建号与构建结果；报告缺失时显示“暂无报告”；
- Allure 报告来自独立的 Jenkins/手工链路，与平台任务没有一一对应关系；任务结果接口不得用 `report_available` 暗示该报告属于当前任务；
- 报告页面必须能在平台子路径下正常加载其全部静态资源；
- 报告内容可能包含接口明细（已脱敏 token），在未上线登录前仅限受控内网访问，页面应有该提示。

### 5.8 用例库浏览

只读展示三类资产：

| 类型 | 来源 | 展示字段 |
|---|---|---|
| API 定义 | `data/apis/*.yaml` | API ID、名称、`service_name`、`method_name` |
| 单接口 Case | `data/cases/*.yaml` | 关联 API、Case ID、名称、标签 |
| Flow | `data/flows/*.yaml` | Flow 名称、标签、步骤数、步骤引用的 API |

约束：

- 仅读取与展示，不提供编辑、上传、删除；
- YAML 解析失败的文件应在列表中显示文件名与错误提示，不导致整页失败；
- 用例库数据直接来自挂载的项目 `data/` 目录，保证与代码仓库一致。

### 5.9 健康检查

- 提供 `GET /api-autotest/health`，返回固定结构：

```json
{ "status": "ok", "service": "api-autotest" }
```

- 健康检查只验证 Web 进程可响应，不触发执行、不读取凭证、不依赖外部 Gateway；
- 凭证缺失、报告目录为空等属于“功能降级信息”，只在工具首页展示，不影响健康检查返回。

### 5.10 错误处理

- 工具未启动：由平台网关统一错误页承接（复用 `tool-unavailable.html`）；
- 提交参数非法：返回 4xx 与可读错误信息；
- 运行中重复提交：返回明确冲突提示；
- 执行异常（依赖缺失、凭证缺失、Gateway 不可达）：任务置 `failed`，以稳定错误码和脱敏摘要展示；
- 错误响应不暴露凭证、环境变量值、原始控制台内容或容器内部绝对路径；所有非框架日志经过二次脱敏。

---

## 6. 任务模型与接口约定

工具壳 REST 接口统一挂在基础路径下（平台模式为 `/api-autotest`），命名与平台框架升级文档中的任务协议对齐，便于未来 `ApiAutomationAdapter` 直接映射。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `{BASE}/api/tasks` | 提交执行任务 |
| GET | `{BASE}/api/tasks` | 任务列表（分页：`page`、`page_size`，默认 20，最大 100） |
| GET | `{BASE}/api/tasks/{task_id}` | 任务详情（状态、参数、时间线、错误信息） |
| POST | `{BASE}/api/tasks/{task_id}/cancel` | 取消任务 |
| GET | `{BASE}/api/tasks/{task_id}/result` | 结果摘要（JUnit 统计、失败用例清单） |
| GET | `{BASE}/api/tasks/{task_id}/logs` | 该任务脱敏日志（支持尾部行数参数） |
| GET | `{BASE}/api/catalog` | 用例库清单（API / Case / Flow） |
| GET | `{BASE}/api/report/meta` | 最新报告元信息（是否存在、同步时间） |
| GET | `{BASE}/reports/...` | Allure HTML 静态资源 |
| GET | `{BASE}/health` | 健康检查 |

任务对象的状态名称和基础接口与平台 `tasks` 模型对齐；工具侧 ID 与存储字段保持独立，未来由适配器映射：

```json
{
  "id": "任务 ID",
  "status": "pending | running | succeeded | failed | cancelled",
  "input": { "env": "test", "run_type": "all", "flow": null, "tag": null },
  "created_at": "...", "started_at": null, "finished_at": null,
  "cancel_requested_at": null,
  "error_code": null,
  "error_message": null,
  "result_available": false,
  "summary": { "total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0 }
}
```

列表响应沿用平台分页结构：`{ "items": [], "page": 1, "page_size": 20, "total": 0 }`。

说明：平台标准任务模型含 `progress` 字段，pytest 无进度语义，本工具不提供百分比进度，适配器接入时该字段留空或置 0/100。

---

## 7. 路由与接入约定

### 7.1 平台侧路由新增

| 路径 | 目标 | 说明 |
|---|---|---|
| `/api-autotest/` | `api-autotest:5003` | 工具壳页面与接口 |
| `/api-autotest` | 308 → `/api-autotest/` | 末尾斜杠规则与既有工具一致 |
| `/api-autotest/health` | `api-autotest:5003` | 健康检查 |
| `/api-autotest/api/...` | `api-autotest:5003` | 任务与用例库接口 |
| `/api-autotest/reports/...` | `api-autotest:5003` | Allure 静态报告 |

网关配置沿用既有工具的统一做法：`X-Forwarded-Prefix /api-autotest`、连接/读取超时、`proxy_intercept_errors` + 工具不可用错误页、25 MB 请求体限制。报告与执行接口均为内网 HTTP，无需单独放大请求体。

### 7.2 工具注册信息

```yaml
id: api-autotest
name: 接口自动化
description: 触发 Gateway 接口自动化执行，查看回归结果与 Allure 报告
base_path: /api-autotest
internal_port: 5003
health_path: /api-autotest/health
docker_build_context: ../api-autotest
```

平台侧注册方式与既有工具一致：新增一条 Alembic 迁移写入 `tools` 表；前端 `fallbackTools.ts` 增加回退条目与 `api` 图标。

### 7.3 基础路径要求

- 工具壳服务支持 `API_AUTOTEST_BASE_PATH` 环境变量：默认空（独立根路径模式），平台模式为 `/api-autotest`；
- 页面内所有静态资源、接口请求、报告链接均基于基础路径生成，不硬编码根路径；
- 独立运行时默认行为不变。

---

## 8. 凭证与配置边界

### 8.1 凭证现状与关键约束

框架从项目根目录 `.env` 读取凭证（进程环境变量可覆盖同名键），且**会话刷新成功后会将新 token 写回 `.env`**。因此：

- 凭证文件必须**可写**挂载，只读挂载会导致会话刷新写回失败；
- 本地开发与平台容器若共用同一份 `.env`，两侧同时运行会产生会话写回冲突（同一 token 状态被交叉覆盖），且与被测服务的单会话语义冲突。

### 8.2 平台模式凭证方案

- 平台容器使用**独立的平台专用凭证文件**（例如 `api-autotest/.env.platform`，命名以开发设计文档为准），以可写卷方式挂载为容器内项目根 `.env`；
- 该文件不提交 Git，模板与字段说明进入文档；
- 本地开发继续使用开发者自己的 `.env`，两条链路会话状态互相隔离；
- 镜像内**不得**打包任何 `.env`、token 或测试账号；Dockerfile 构建上下文需排除凭证文件。

### 8.3 环境变量清单（工具壳服务）

| 变量 | 默认值 | 平台模式值 | 说明 |
|---|---|---|---|
| `API_AUTOTEST_HOST` | `127.0.0.1` | `0.0.0.0` | 监听地址 |
| `API_AUTOTEST_PORT` | `5003` | `5003` | 服务端口 |
| `API_AUTOTEST_BASE_PATH` | 空 | `/api-autotest` | URL 基础路径 |
| `PLATFORM_HOME_URL` | `/` | `/` | 返回平台链接 |
| `API_AUTOTEST_TASK_TIMEOUT_SECONDS` | `1800` | `1800` | 单任务执行超时上限 |
| `API_AUTOTEST_TASKS_RETAIN` | `50` | `50` | 任务记录保留条数 |
| `API_AUTOTEST_REPORT_DIR` | `reports/allure-current` | 同左 | 当前 Allure 报告指针（相对项目根） |

### 8.4 明确禁止

- 禁止将凭证写入镜像、前端代码、Git 仓库；
- 禁止通过 URL 参数传递 token；
- 禁止在任何接口响应、页面、日志查看功能中输出凭证原文（框架脱敏规则之外的任何位置）；
- 禁止平台壳服务把凭证转发给除被测 Gateway 之外的任何服务。

---

## 9. 数据与文件方案

### 9.1 目录与挂载

| 内容 | 项目内位置 | 平台模式处理 |
|---|---|---|
| 凭证 | `.env`（容器内） | 由宿主机平台专用凭证文件可写挂载 |
| 环境配置 | `config/` | 随镜像打包（非敏感） |
| 用例资产 | `data/` | 镜像保留构建时副本；平台模式由宿主机 `data/` 只读挂载覆盖，保证与仓库一致 |
| 执行日志 | `logs/YYYY-MM-DD/` | 卷挂载持久化，容器重建不丢失 |
| JUnit 结果 | `reports/junit-*.xml` | 卷挂载持久化 |
| Allure 原始结果 | `allure-results/` | 平台任务不生成（确认结论）；容器不挂载；仅宿主机手动执行使用 |
| Allure HTML 报告 | `reports/allure-reports/<version>/` + `reports/allure-current` | 卷挂载，由链路 A 写入版本目录并原子切换 current 指针，工具壳只读托管 |
| 任务记录 | 运行时 `tasks/` 目录 | 卷挂载持久化 |

### 9.2 报告同步约定（链路 A → 平台）

- 报告版本目录固定为 `api-autotest/reports/allure-reports/<version>/`，当前报告由 `reports/allure-current` 原子指针指向；
- 发布时先完整写入新的版本目录并校验 `index.html`，再以同文件系统临时指针 + `os.replace`/`mv` 原子切换 `allure-current`；失败或中断时旧指针保持可用，启动/发布前清理无引用的临时目录；
- 同步方式（确认结论）：Jenkins 仅生成 HTML 并归档构建产物，不直接写宿主目录；宿主机拉取脚本选择**最近一次已完成且存在 HTML 归档产物的构建**（无论 SUCCESS/FAILURE/UNSTABLE）后调用发布脚本；宿主机手动执行链路直接调用发布脚本；
- MVP 触发方式为手动执行或用户自备的定时任务，不内置于平台；
- MVP 对外只展示 current 指向的一份 HTML 报告；切换成功后清理上一版本，历史报告归档不属于本期；
- `report-meta.json` 至少记录来源、生成时间；Jenkins 来源还必须记录 job、build number、build result 与 build URL，避免失败构建报告被误认为成功报告。

### 9.3 保留与清理

- 框架既有机制保留：`logs/` 超过 7 天的日期目录由框架自动清理；
- 任务记录保留最近 `API_AUTOTEST_TASKS_RETAIN` 条（默认 50）；超出时同步删除任务元数据、对应 `junit-task-<id>.xml` 与 `tasks/<id>/console.log`；
- `allure-results/` 不进入平台容器挂载；本地/Jenkins 执行自行维护各自目录的清理策略。

### 9.4 敏感数据

- 平台优先展示框架既有脱敏日志（token、`Authorization`、预签名 URL 查询参数置 `***`）；如需用 `console.log` 兜底，必须在壳服务侧再次遮蔽 Bearer/Cookie、常见 token 字段、`.env` 形式值和敏感查询参数，并截断 traceback；
- 报告与日志目录不提交 Git（沿用项目 `.gitignore`）；
- 登录上线前，报告 URL 视为内网可见资源，不做单独鉴权。

---

## 10. 并发与资源约束

- **单实例单任务**：与 Jenkins `disableConcurrentBuilds` 语义对齐；进程内互斥锁覆盖“检查槽位 → 创建任务 → 占用槽位 → 启动子进程”，保证并发提交只有一个成功；
- 任务 JSON 使用同目录临时文件写入、flush/fsync 后 `os.replace`；取消、超时和等待线程通过同一状态锁执行合法状态迁移，终态不可覆盖；
- 任务执行超时默认 1800 秒（Flow 轮询上限 120 秒/步骤，全集执行留足余量），超时按取消处理并置 `failed`（错误信息标注超时）；
- 平台 Compose 不为该服务预留超额资源承诺；pytest 执行为轻 CPU、网络 IO 型负载；
- 容器必须能访问 `config/env/<env>.yaml` 中的 `gateway_base_url`；网络不可达时任务失败并给出可读提示；
- 平台模式与本地/Jenkins 链路**不得同时对同一环境发起执行**（会话状态与被测数据副作用约束），该约束以文档和操作规范声明，MVP 不做技术互锁。

---

## 11. 非功能需求

### 11.1 可用性

- 工具壳页面在常用桌面浏览器正常显示；
- 任务提交、状态轮询、日志查看、报告打开均可在平台子路径下完成；
- 页面刷新、浏览器后退不跳出平台路径。

### 11.2 性能

- 页面首屏与用例库列表在内网环境 2 秒内加载；
- 任务状态查询为本地文件读取，P95 < 200ms；
- 执行性能与本地 `runtest.py` 一致，工具壳不引入额外请求链路开销。

### 11.3 安全

- 仅通过平台网关暴露，`5003` 不映射宿主机；
- 凭证按第 8 章管理；
- 任务提交参数严格白名单校验（env 枚举、flow 存在性、run_type 枚举、tag 表达式由 pytest 解析，不做字符串拼接 shell）；
- 执行调用以参数数组方式启动子进程，禁止 shell 拼接，防止命令注入。

### 11.4 可维护性

- 工具壳代码与框架核心代码在同一仓库内保持清晰目录边界；
- 工具壳具备独立启动与自身测试（不发送真实请求）；
- 接入配置（端口、路径、超时）全部环境变量化。

---

## 12. 职责边界

### 12.1 平台负责

- 工具导航、卡片与状态展示（tools 表注册、前端回退目录）；
- `/api-autotest/` 反向代理与统一错误页；
- Compose 编排、健康检查与端口收敛；
- 不承载任何执行逻辑与任务数据。

### 12.2 工具壳服务负责

- 页面与任务接口；
- 构造与 Jenkins 语义一致的 pytest 命令并子进程执行，管理其生命周期（启动、超时、取消）；
- 任务记录的文件级存储与清理；
- JUnit/日志产物的读取与展示；
- Allure HTML 目录的静态托管；
- 用例库只读解析；
- 自身健康检查。

### 12.3 框架核心负责（保持现状）

- pytest 收集与执行、YAML 校验、断言、提取与轮询；
- 会话复用/刷新与 `.env` 写回；
- 请求/响应脱敏日志；
- `runtest.py` 参数语义。

### 12.4 Jenkins / 宿主机链路负责

- 正式回归执行与既有 JUnit/Allure 发布；执行阶段保持不变，post 阶段新增 HTML 生成与归档；
- 在 Jenkins 工作区生成 Allure HTML 并归档为构建产物（不直接写宿主目录）；
- 宿主机拉取脚本：拉取 Jenkins 产物并原子发布到平台约定目录（手动/定时）。

### 12.5 明确不做清单

- 不修改框架核心逻辑：`data/` YAML 结构、断言引擎、会话机制、脱敏规则、`runtest.py` 语义；
- 不将任务记录写入平台 PostgreSQL，不实现平台任务中心对接（留待框架升级阶段 4）;
- 不实现登录与权限；
- 不在容器内生成 Allure HTML；
- 不替代、不改动 Jenkins 流水线的执行阶段与测试语义；仅调整 post 报告产物处理；
- 不提供用例在线编辑；
- 不做执行排队（MVP 拒绝并发提交）；
- 不复制框架源码到 `test-platform` 项目。

---

## 13. 文件影响范围（预估，供开发设计细化）

### 13.1 平台侧（test-platform）

- `docker-compose.yml`：新增 `api-autotest` 服务（build context `../api-autotest`、环境变量、卷挂载、healthcheck、`expose 5003`）；`platform-gateway` 依赖列表追加；
- `nginx/nginx.conf`：新增 `/api-autotest` 重定向与 `/api-autotest/` 代理块；
- `backend/alembic/versions/`：新增迁移，向 `tools` 表插入 `api-autotest` 记录；
- `frontend/src/data/fallbackTools.ts`：新增回退条目；新增 `api` 图标与图标映射；
- `tests/test_smoke.py`：新增平台冒烟用例。

### 13.2 工具侧（api-autotest）

- 新增薄 Web 服务入口与页面（文件组织由开发设计文档确定）；
- 新增 Dockerfile（不含 Node/Allure；排除 `.env`）；
- 新增平台专用凭证文件模板说明（文件本身不入库）；
- `.gitignore`：补充运行时目录（如 `tasks/`）；
- 不修改：`runtest.py`、`api/`、`utils/custom/`、`test_cases/`、`data/`、`config/`。

### 13.3 Jenkins / 宿主机侧

- Jenkinsfile post 阶段：新增 Allure HTML 生成与构建产物归档步骤；
- 新增宿主机拉取与发布脚本（`publish_allure_report.sh`、`fetch_jenkins_report.sh`）；
- 不改变 Jenkins 执行阶段与测试判定；post 报告失败可将原本成功的构建标记为 `UNSTABLE`，但不得掩盖或改写既有 pytest `FAILURE`。

---

## 14. 验收标准

### 14.1 平台验收

- [ ] Compose 一键启动后，首页展示“接口自动化”卡片，状态探测正确；
- [ ] 点击卡片进入 `/api-autotest/`，页面与全部接口在子路径下正常；
- [ ] 停止 `api-autotest` 容器后，平台首页与其他三个工具不受影响，入口显示友好错误页；
- [ ] 平台 API/数据库故障时，首页回退目录仍显示该工具入口；
- [ ] 宿主机仅暴露平台网关端口。

### 14.2 任务能力验收

- [ ] 提交 `all` / `single` / `flow`（指定 Flow）/ 带 `tag` 的任务均可正确执行并返回真实统计；
- [ ] 非法参数（不存在的环境、不存在的 Flow、`single` 携带 flow）被拒绝且有可读提示；
- [ ] 两个并发提交只有一个创建成功，另一个返回 409；任务 JSON 在并发轮询期间始终可解析；
- [ ] 取消 `running` 任务后子进程终止，状态为 `cancelled`，等待线程不会覆盖终态；JUnit 缺失时明确显示结果不可用；
- [ ] 任务超时按约定处理；
- [ ] 任务详情展示 JUnit 统计、失败用例与脱敏日志；
- [ ] `DEVICE_ID` 来自环境 YAML 时预检与框架行为一致；需要 `ADMIN_*` 的 Flow 缺少相应配置时提交被拒绝或明确失败，不产生假成功；
- [ ] 页面与接口不出现凭证原文。

### 14.3 报告与用例库验收

- [ ] 链路 A 同步报告后，页面展示最近已完成且有产物的构建报告并可完整打开；失败构建报告可发布，且构建结果清晰可见；
- [ ] 发布切换期间和模拟中断后旧报告持续可用，不出现半份报告或 404 空窗；
- [ ] 报告目录为空时展示“暂无报告”；
- [ ] 用例库正确列出当前全部 API / Case / Flow，且与 `data/` 目录一致。

### 14.4 隔离与回归验收

- [ ] 终端独立运行 `runtest.py` 行为不变；
- [ ] Jenkins 执行阶段与测试判定不变；post 报告处理不掩盖 pytest 失败；
- [ ] 框架现有不发送真实请求的回归测试全部通过；
- [ ] 工具壳自身测试（不发真实请求）通过；
- [ ] 平台模式与独立模式分别完成一次冒烟。

---

## 15. 测试方案

### 15.1 自动化测试

- 工具壳单元测试：参数校验、任务状态机、两个并发提交、取消/完成竞态、JSON 原子落盘、取消与超时、JUnit 缺失、二次脱敏、用例库解析（mock 目录，不发真实请求）；
- 框架回归：`python3 -m pytest -q -k "not gateway_flow and not single_gateway_api"` 保持通过；
- 平台冒烟：`GET /api-autotest/`、`/api-autotest/health`、`/api-autotest/api/catalog`、未知路径 404；
- 代理集成：GET/POST 转发、末尾斜杠重定向、工具不可用错误页。

### 15.2 手工回归

- 对 `test` 环境执行一次真实 `single` 与一次真实 Flow，核对统计与被测侧表现；
- 验证凭证来源与任务级依赖：`DEVICE_ID` 分别来自 YAML/.env；需要 Admin 凭证的 Flow 在缺失与完整配置下行为正确；
- 验证凭证刷新场景：临期 token 触发刷新后，平台专用 `.env` 被正确写回且后续任务可用；
- 验证报告同步原子性：同步过程中持续刷新不出现半份报告或 404；模拟切换前后中断时旧报告仍可用；
- 触发一次失败但产出报告的 Jenkins 构建，确认拉取的是该最新已完成构建而非更早的成功构建；
- 浏览器刷新、后退、返回平台路径正确。

### 15.3 安全检查

- 检查镜像内不含 `.env`；
- 检查接口响应、页面、框架日志及 `console.log` 兜底均无凭证原文、敏感查询参数和容器绝对路径；
- 检查任务提交无 shell 注入面；
- 检查 `5003` 未映射宿主机。

---

## 16. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 会话写回需要可写 `.env`，只读挂载会破坏刷新 | 会话刷新失败、任务全失败 | 平台专用凭证文件可写挂载，与本地 `.env` 隔离 |
| 仅检查 `.env` 中 `DEVICE_ID` 与框架真实配置不一致 | 误拒绝合法配置或遗漏 Flow 专属凭证 | 复用 `load_settings(env)`；按任务/Flow 校验专属凭证；全量跳过不得视为普通成功 |
| 并发提交或取消/完成竞态 | 同时启动多个 pytest、终态被覆盖、JSON 损坏 | 原子槽位锁、合法状态迁移锁、临时文件 + fsync + `os.replace`；并发测试覆盖 |
| 平台与本地/Jenkins 同时执行造成会话与数据冲突 | 结果不可信、token 交叉覆盖 | 文档声明互斥约束；单任务约束先落在平台侧 |
| 容器到被测 Gateway 网络不通 | 任务失败 | 任务错误信息透出可读原因；接入前验证网络可达 |
| Allure HTML 在子路径下资源 404 | 报告打不开 | 接入联调专项验证；必要时由同步脚本保证相对路径结构 |
| 报告目录两步改名出现空窗或发布中断 | 页面短暂 404、current 丢失 | 版本目录完整写入后原子切换 current 指针；失败保持旧指针并清理临时目录 |
| 只拉取 Jenkins 最近成功构建 | 测试失败时展示陈旧报告 | 选择最近已完成且存在 HTML 产物的构建；元信息展示构建号与结果 |
| 长任务占用容器导致健康探测误判 | 卡片状态抖动 | 健康检查与执行子进程解耦，探测只测 Web 进程 |
| 无登录状态下任何人可触发执行 | 误触发、刷接口 | 受控内网部署；单任务与超时约束兜底；登录上线后纳入权限 |
| 报告与日志含接口明细 | 内网泄露面 | 仅脱敏产物对外；报告页提示；登录/RBAC 为后续演进 |
| 原始 `console.log`/traceback 绕过框架脱敏 | token、环境值或内部路径泄漏 | 壳服务二次脱敏、截断与稳定错误码；原始 console 不直接通过 API 返回 |
| 框架升级改变产物结构 | JUnit/日志解析失效 | 工具壳解析层只依赖 JUnit XML 标准结构与框架既有日志目录约定 |

---

## 17. 后续演进

1. 平台任务中心阶段：工具壳接口按 `ApiAutomationAdapter` 映射进平台 `tasks`/`task_results`，任务记录迁移到 PostgreSQL；
2. 登录与 RBAC 上线后：执行触发与报告查看纳入权限控制；
3. 定时/周期回归：接平台定时任务能力，触发工具壳任务接口；
4. 报告历史与归档：保留多份 Allure HTML 并提供历史切换；
5. 执行排队与并发策略：按平台统一 Worker 能力演进；
6. 多环境支持：随 `config/env/` 扩展自动出现在执行参数中。

---

## 18. 交付物

- 工具壳服务（页面 + 任务接口 + 用例库 + 报告托管 + 健康检查）；
- `api-autotest` Dockerfile 与平台专用凭证模板说明；
- 平台 Compose、Nginx、tools 表迁移、前端卡片与图标；
- Jenkins/宿主机报告同步能力（按 9.2 约定）；
- 平台冒烟测试与工具壳测试；
- 启动、接入、排障与回滚说明（随开发设计文档交付）。
