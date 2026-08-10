# Truthy_ApiAutoTest2 接入测试开发平台开发设计与计划

> 文档版本：V1.2  
> 创建日期：2026-08-07  
> 文档状态：已确认（确认项结论见第 22 章）  
> 需求依据：[Truthy_ApiAutoTest2接入PRD.md](./Truthy_ApiAutoTest2接入PRD.md)  
> 接入工具：`Truthy_ApiAutoTest2` / Gateway 接口自动化 V1.3  
> 目标入口：`/api-autotest/`  
> 体例参考：[Truthy_Search接入开发设计与计划.md](./Truthy_Search接入开发设计与计划.md)
> 修订记录：V1.2（2026-08-10）补充并发状态保护、原子任务存储、二次脱敏、配置级凭证预检和取消产物边界；修正 Jenkins 构建选择/归档路径；报告采用版本目录 + current 指针发布；对齐 8.1 scripts/ 目录（补 fetch_jenkins_report.sh）

本文档中的 **【确认项 N】** 已于 2026-08-07 由用户确认：事项 1、2、3、4、5、6、7、9、10 采用推荐方案，事项 8、11 采用备选方案；结论汇总见第 22 章。

---

## 1. 文档目的

本文档将《Truthy_ApiAutoTest2 接入 PRD》转换为可实施的技术方案，明确：

- 工具壳服务（薄 Web 层）的技术选型、模块结构与任务执行引擎设计；
- 任务模型、接口契约、状态机、取消与超时机制；
- 凭证隔离、数据目录、产物清理与报告同步链路；
- Dockerfile、Docker Compose、Nginx 与平台工具目录的接入细节；
- Jenkins 报告发布链路的调整方式；
- 分阶段开发顺序、测试方案、验收标准、上线步骤与回滚方案；
- 存在备选方案、需要确认的设计决策（第 22 章）。

本阶段坚持最小化改动：不修改框架核心（`api/`、`utils/custom/`、`test_cases/`、`data/`、`config/`、`runtest.py`），不引入数据库，不改动既有三个工具。

---

## 2. 任务目标与成功标准

### 2.1 任务目标

将 `Truthy_ApiAutoTest2` 作为平台第一个**任务型工具**接入：

```text
测试开发平台
├── 埋点测试
├── 日志分析
├── 检索评测
└── 接口自动化（本次接入，/api-autotest/）
```

用户通过平台唯一对外端口 `8080` 访问 `http://<platform-host>:8080/api-autotest/`，可提交执行任务、查看状态与结果、浏览用例库、打开由 Jenkins/宿主机链路同步的 Allure 报告。

### 2.2 成功标准

与 PRD 2.2 一致，此处补充工程化判据：

- 工具壳服务可在独立模式（根路径）与平台模式（`/api-autotest`）下分别完成全部页面与接口操作；
- 任务状态机 `pending → running → succeeded/failed/cancelled` 完整可验证，含超时路径；
- 取消操作终止 pytest 进程组；已完整写出的日志/JUnit 保留，未生成 JUnit 时明确记录结果不可用；
- 凭证预检与框架真实配置合并逻辑一致，并覆盖指定 Flow 的专属凭证；全量跳过不允许作为普通成功；
- 并发提交只有一个成功；取消、超时和进程完成不会互相覆盖终态；任务 JSON 在并发轮询时始终完整可读；
- 原始 `console.log` 不通过接口直接返回，所有兜底输出经过二次脱敏和截断；
- 服务重启后历史任务记录可读，运行中任务被标记为中断；
- 报告发布通过版本目录 + current 指针原子切换；发布失败或中断时旧报告持续可用；
- 拉取最近一次已完成且存在 HTML 产物的 Jenkins 构建，包括测试失败构建，并展示构建号与结果；
- 平台冒烟测试、工具壳单元测试、框架回归测试全部通过；
- `5003` 端口不映射宿主机；镜像内不含 `.env` 与任何凭证。

### 2.3 交付物

- `Truthy_ApiAutoTest2` 工具壳服务（页面 + 任务接口 + 用例库 + 报告托管 + 健康检查）；
- `Dockerfile`、`.dockerignore`、`requirements-web.txt`（见【确认项 3】）；
- 平台专用凭证模板 `.env.platform.example` 与填写说明；
- 报告发布与拉取脚本 `scripts/publish_allure_report.sh`、`scripts/fetch_jenkins_report.sh`；
- Jenkinsfile post 阶段 HTML 生成与产物归档步骤；
- 平台侧：Compose 服务、Nginx 路由、Alembic 迁移、前端卡片与图标、冒烟测试；
- 工具壳单元测试；
- 启动、接入、排障与回滚说明（并入平台 README 与工具 README）。

---

## 3. 实施范围

### 3.1 本次包含

- 工具壳服务及其任务执行引擎（子进程方式执行 pytest）；
- 任务提交、查询、取消、结果、日志查看接口与页面；
- 用例库只读接口与页面；
- Allure HTML 报告静态托管与报告元信息接口；
- 健康检查与子路径能力；
- Dockerfile 与平台 Compose/Nginx/工具目录注册；
- 报告发布与拉取脚本；Jenkins post HTML 生成与产物归档步骤；
- 平台专用凭证文件机制；
- 相关自动化测试与文档。

### 3.2 本次不包含

- 登录、RBAC、工具级权限；
- 任务记录写入平台 PostgreSQL / 平台任务中心对接；
- 容器内安装 Node / Allure CLI / 容器内生成 Allure HTML；
- 用例在线编辑；定时触发；执行排队；进度百分比；
- 多环境扩展（仅 `config/env/` 已有环境）；
- 框架核心逻辑与 Jenkins 执行阶段的任何修改。

---

## 4. 当前系统评估

### 4.1 Truthy_ApiAutoTest2 当前架构

```text
终端 / Jenkins
  │  runtest.py --env/--tag/--flow/--module 或直接 pytest
  ▼
pytest
  ├── test_cases/test_single_api.py   单接口真实用例（YAML 驱动）
  ├── test_cases/test_gateway_flow.py 多接口 Flow 真实用例
  ├── test_cases/test_framework.py    框架回归（不发真实请求）
  ├── test_cases/test_v12/v13.py      迁移基线回归
  └── test_cases/test_allure_report.py Allure 元数据回归
        │
        ├── config/           settings + env/<env>.yaml
        ├── data/apis|cases|flows|scenarios   YAML 用例资产
        ├── api/ utils/       Gateway 信封、加载器、断言、会话、脱敏日志
        ├── logs/YYYY-MM-DD/  脱敏执行日志
        ├── reports/          junit*.xml（Jenkins 产物）
        └── allure-results/   Allure 原始结果
```

### 4.2 技术栈

| 能力 | 当前实现 |
|---|---|
| 执行框架 | pytest 8 + requests + PyYAML |
| 报告 | allure-pytest（原始结果）+ Allure 3 CLI（HTML，容器外） |
| 结果 | JUnit XML（`--junitxml`） |
| 凭证 | 项目根 `.env`，进程环境变量可覆盖 |
| CI | Jenkinsfile（参数化执行 + JUnit/Allure 发布 + 产物归档） |
| Web 能力 | 无（本次新增薄壳） |
| 容器 | 无 Dockerfile（本次新增） |

### 4.3 执行入口与命令（关键事实）

`Jenkinsfile` 的 `RUN_TYPE` 语义为**直接调用 pytest 并指定入口文件**：

| RUN_TYPE | 命令（简化） |
|---|---|
| `single` | `pytest test_cases/test_single_api.py --env=$ENV` |
| `flow` | `pytest test_cases/test_gateway_flow.py --env=$ENV [--flow=$FLOW]` |
| `all` | `pytest test_cases/test_single_api.py test_cases/test_gateway_flow.py --env=$ENV [--flow=$FLOW]` |

而 `runtest.py` 在未指定 `--flow` 时的收集目标是整个 `test_cases/` 目录（含框架回归文件），与 Jenkins 的 `all` 语义不一致。平台执行链路采用哪一种，见【确认项 1】（已确认：对齐 Jenkins）。

### 4.4 产物结构与任务关联依据

- JUnit：`--junitxml=<路径>` 指定，本设计按任务命名为 `reports/junit-task-<task_id>.xml`（与 Jenkins 的 `junit-all/single/flow.xml` 区分，避免清理误伤）；
- 日志：`logs/YYYY-MM-DD/{时间戳}_{env}_{pid}.log`，**文件名包含 pytest 进程 PID**，壳服务以子进程 PID 关联任务日志；
- Allure：`--alluredir` 指定；平台任务不生成 Allure 原始结果（【确认项 8】已确认）；
- 框架自动清理 7 天前的日期日志目录，本设计不覆盖该机制。

### 4.5 凭证与会话机制（关键约束）

- `load_settings` 从 `PROJECT_ROOT/.env` 读取凭证，进程环境变量可覆盖同名键；
- 会话刷新成功后 `persist_session_to_dotenv` **写回 `.env`**，因此凭证文件必须可写；
- `load_settings` 会合并环境 YAML、`.env` 与进程环境变量；有效 `DEVICE_ID` 不限定来源。配置不满足框架要求时 conftest 可能将真实用例 **skip**，pytest 退出码仍为 0；特定 Flow 还可能因缺少 `ADMIN_*` 跳过步骤。平台侧必须按 8.3 做与真实配置一致的预检和全量跳过判定。

### 4.6 当前测试基线

- 框架回归（不发真实请求）：`python3 -m pytest -q -k "not gateway_flow and not single_gateway_api"`；
- 阶段 0 需记录该基线的用例数与通过情况，作为后续回归对照。

### 4.7 当前接入阻碍

| 阻碍 | 说明 | 本方案处理 |
|---|---|---|
| 无 Web 层 | CLI 批跑型 | 新增薄壳服务 |
| 无 Dockerfile | 无法进入平台 Compose | 新增（不含 Node/Allure） |
| 无健康检查 | 平台状态无法探测 | 新增 `{BASE}/health` |
| 凭证需写回 | 只读挂载不可行 | 平台专用 `.env.platform` 可写挂载 |
| 无凭证时静默跳过 | 假成功风险 | 提交前凭证预检 |
| Allure HTML 依赖 Node | 镜像膨胀 | 容器外生成 + 目录同步 |

---

## 5. 方案选择

### 5.1 Web 技术：Flask 3 + Blueprint

- 与 `log_filter_tool`、`Truthy_Search` 的平台接入先例一致（Blueprint `url_prefix` 实现基础路径，`url_for` 生成内部地址）;
- 静态托管（Allure 报告）用 Flask `send_from_directory` 即可满足，无需额外组件；
- 页面沿用各工具既有风格：服务端渲染单页 + 原生 JavaScript，不引入前端框架；
- 运行方式与既有工具一致：容器内 Flask 自带服务器，不引入 Gunicorn（与 MVP 既定约束一致）。

备选：标准库 `http.server`（TrackEvents 方式）。不选择原因：任务接口较多，路由、JSON、静态文件手写成本高。

### 5.2 执行方式：子进程 `python -m pytest`

- 壳服务以参数数组方式启动子进程（`start_new_session=True` 新建进程组），**不经过 shell**，无命令注入面；
- 选择子进程而非 `pytest.main` 进程内调用：可取消（终止进程组）、可隔离（日志/root logger/全局状态不污染 Web 进程）、与 Jenkins 命令形态一致；
- 命令构成见 8.3；入口文件选择按【确认项 1】确认结论（对齐 Jenkins）。

### 5.3 任务存储：文件级 JSON

- `tasks/<task_id>.json` 保存任务记录；`tasks/<task_id>/console.log` 保存子进程标准输出/错误；
- 单实例单任务但允许页面轮询与取消并发访问：进程内锁保护槽位与状态迁移，JSON 通过同目录临时文件 + fsync + `os.replace` 原子落盘；
- 不引入 SQLite/PostgreSQL 任务存储；
- 任务 ID 采用 `YYYYMMDD-HHMMSS-<4位十六进制>`，天然按时间排序。

### 5.4 报告托管：目录挂载 + 静态服务

- Allure HTML 由链路 A 完整写入 `reports/allure-reports/<version>/`，再原子切换 `reports/allure-current` 指针；
- 壳服务将 current 指向的版本作为静态目录托管在 `{BASE}/reports/` 下；
- Allure 3 awesome 报告内部资源为相对路径，子路径托管可行（阶段 4 联调专项验证，见风险清单）。

### 5.5 不引入数据库、队列、Worker

与 PRD 一致。执行排队、并发、任务中心对接留待平台框架升级阶段 4/5。

---

## 6. 目标架构

### 6.1 服务边界

```text
platform-gateway (Nginx :8080)
  └── /api-autotest/ ──► api-autotest :5003（本次新增容器）
        ├── web 层：Flask Blueprint
        │     ├── 页面：首页 / 任务详情 / 用例库
        │     ├── API：tasks / catalog / report-meta / health
        │     └── 静态：reports/（Allure HTML）
        ├── 执行引擎：TaskManager（单槽位）
        │     └── subprocess: python -m pytest <入口文件> ...
        ├── 任务存储：tasks/*.json（卷挂载）
        └── 产物读取：reports/junit-task-*.xml、logs/、allure-current/
```

### 6.2 两条执行链路

```text
链路 A（Jenkins / 宿主机）：
  pytest 执行 → allure-results → allure awesome 生成 HTML
  → Jenkins 归档产物 → 宿主机 fetch_jenkins_report.sh 拉取
  → publish_allure_report.sh 原子发布 → reports/allure-reports/<version>/
                                      → reports/allure-current
  （宿主机手动链路：生成 HTML 后直接调用发布脚本）

链路 B（平台触发）：
  页面提交 → TaskManager → pytest 子进程
  → junit-task-<id>.xml + 脱敏日志
  → 页面展示统计与日志（本链路不生成 allure-results 与 HTML 报告）
```

### 6.3 运行模式

| 模式 | 启动方式 | 基础路径 |
|---|---|---|
| 独立模式 | 项目内 `python -m web.app`（命令以代码实现为准） | 空（根路径） |
| 平台模式 | 平台 Compose 容器 | `/api-autotest` |

框架本体和终端 `runtest.py` 行为不变；Jenkins 执行阶段与测试判定不变，post 报告生成和归档按第 12 章调整。

---

## 7. 子路径与路由设计

### 7.1 环境变量

| 变量 | 默认值 | 平台模式值 | 说明 |
|---|---|---|---|
| `API_AUTOTEST_HOST` | `127.0.0.1` | `0.0.0.0` | 监听地址 |
| `API_AUTOTEST_PORT` | `5003` | `5003` | 服务端口 |
| `API_AUTOTEST_BASE_PATH` | 空字符串 | `/api-autotest` | URL 基础路径 |
| `PLATFORM_HOME_URL` | `/` | `/` | 返回平台链接 |
| `API_AUTOTEST_TASK_TIMEOUT_SECONDS` | `1800` | `1800` | 单任务超时上限 |
| `API_AUTOTEST_TASKS_RETAIN` | `50` | `50` | 任务记录保留条数 |
| `API_AUTOTEST_REPORT_DIR` | `reports/allure-current` | 同左 | 当前报告指针（相对项目根） |

基础路径校验规则与既有工具一致：空值合法；非空必须以 `/` 开头、去除末尾 `/`，禁止查询参数、协议、域名、`..`、重复斜杠；非法值启动时报错退出。

### 7.2 Flask 前缀适配

```text
create_app()
  └── Blueprint "apiautotest"
        ├── GET  /                       首页
        ├── GET  /tasks/<task_id>        任务详情页
        ├── GET  /catalog                用例库页
        ├── POST /api/tasks              提交任务
        ├── GET  /api/tasks              任务列表
        ├── GET  /api/tasks/<id>         任务详情
        ├── POST /api/tasks/<id>/cancel  取消任务
        ├── GET  /api/tasks/<id>/result  结果摘要
        ├── GET  /api/tasks/<id>/logs    脱敏日志（tail）
        ├── GET  /api/catalog            用例库清单
        ├── GET  /api/report/meta        报告元信息
        ├── GET  /health                 健康检查
        └── GET  /reports/<path:filename> Allure 静态资源
  └── app.register_blueprint(bp, url_prefix=BASE_PATH or None)
```

页面模板中所有地址使用 `url_for`；JavaScript 的接口基址由模板注入（`window.__BASE_PATH__`），禁止硬编码根路径。

### 7.3 尾斜杠与重定向

- Nginx：`location = /api-autotest { return 308 /api-autotest/; }`；
- Flask `strict_slashes` 保持默认，首页仅注册 `/`；
- 报告入口 URL 固定为 `{BASE}/reports/index.html`。

---

## 8. 工具壳服务设计

### 8.1 模块结构

推荐在项目内新增 `web/` 包与 `tests/` 目录（备选位置见【确认项 2】）：

```text
Truthy_ApiAutoTest2/
├── web/
│   ├── __init__.py
│   ├── app.py              # Flask app 工厂、路由、页面与 API
│   ├── task_manager.py     # 单槽位执行引擎：启动/等待/取消/超时/恢复
│   ├── task_store.py       # tasks/*.json 读写、列表、保留策略
│   ├── junit_report.py     # JUnit XML 解析（统计与失败清单）
│   ├── catalog.py          # 复用 api_loader/case_loader/flow_loader 的只读清单
│   ├── credentials.py      # 凭证预检（.env 存在性与必填键）
│   └── templates/          # index.html / task_detail.html / catalog.html
├── tests/
│   ├── conftest.py         # 壳服务测试夹具（临时目录、mock 子进程）
│   ├── test_task_manager.py
│   ├── test_task_store.py
│   ├── test_junit_report.py
│   ├── test_catalog.py
│   └── test_web_routes.py  # Flask test client，不发真实请求
└── scripts/
    ├── publish_allure_report.sh
    └── fetch_jenkins_report.sh
```

依赖方向约束：`web/` 只读使用 `utils/custom/` 的既有加载器（`api_loader`、`case_loader`、`flow_loader`、`config_loader.load_dotenv_values`），不修改其行为；`web/` 不被框架核心反向依赖。

### 8.2 任务模型与状态机

任务记录 `tasks/<task_id>.json`：

```json
{
  "id": "20260807-163012-a1b2",
  "status": "running",
  "input": { "env": "test", "run_type": "all", "flow": null, "tag": null },
  "pid": 12345,
  "created_at": "2026-08-07T16:30:12+08:00",
  "started_at": "2026-08-07T16:30:13+08:00",
  "finished_at": null,
  "cancel_requested_at": null,
  "exit_code": null,
  "timeout": false,
  "error_code": null,
  "error_message": null,
  "result_available": false,
  "junit_file": "reports/junit-task-20260807-163012-a1b2.xml",
  "log_file": null,
  "summary": { "total": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0 }
}
```

状态名称与主要流转和平台标准协议一致；工具侧 ID、存储字段由未来适配器映射：

```text
pending → running → succeeded
pending → running → failed
pending → cancelled
running → cancelled
```

退出码映射：

| pytest 退出码 | 状态 | 说明 |
|---|---|---|
| 0 | `succeeded` | 全部通过 |
| 1 | `failed` | 存在失败用例，摘要来自 JUnit |
| 2 | `failed` | 执行中断/内部错误，摘要来自二次脱敏后的 console 尾部 |
| 5 | `failed` | 未收集到用例（见【确认项 7】） |
| 其他 | `failed` | 记录退出码与二次脱敏后的 console 尾部 |
| 被取消 | `cancelled` | 用户取消 |
| 超时 | `failed` | `timeout=true`，错误信息标注超时 |

### 8.3 执行引擎（TaskManager）

提交前校验（全部本地检查，不发请求）：

1. 在进程内槽位锁中原子完成“检查 `pending`/`running` → 创建任务 → 占用槽位”；并发请求只有一个成功，其余返回 409；
2. `env` 存在于 `config/env/`，名称字符合法（沿用框架 `Path(env).name != env` 规则）；
3. `run_type` ∈ `all|single|flow`；`run_type=flow` 时 `flow` 必填且存在于 `data/flows/`；`single` 时 `flow` 必须为空；`all` 时可选；
4. `tag` 非空时仅做长度与字符白名单校验（交给 pytest `-m` 解析，壳服务不解释表达式）；
5. **基础配置预检**：只读调用 `load_settings(env, project_root=PROJECT_ROOT)`，复用框架对 `config/settings.yaml`、`config/env/<env>.yaml`、`.env` 和进程环境变量的真实合并逻辑；不得额外要求 `DEVICE_ID` 必须来自 `.env`。配置不完整时返回 400 与稳定错误码 `CREDENTIALS_MISSING`；
6. **任务级凭证预检**：解析实际选择的 Flow/标签，若目标包含 Admin 审计步骤，则校验 `ADMIN_SESSION_TOKEN`、`ADMIN_OPERATOR_ID`、`ADMIN_OPERATOR_NAME`；缺失时提交被拒绝并列出缺失字段名，但不返回字段值；
7. **跳过语义**：JUnit 显示全部目标用例均为 skipped 时，任务置 `failed`，`error_code=ALL_TESTS_SKIPPED`；仅部分跳过时保留 pytest 终态并在摘要中显著展示 skipped 数和原因，避免“0 用例/全跳过假成功”。

命令构成（按【确认项 1】确认结论，对齐 Jenkinsfile 语义）：

```python
# run_type=single
[python, "-m", "pytest", "test_cases/test_single_api.py", ...]
# run_type=flow
[python, "-m", "pytest", "test_cases/test_gateway_flow.py", ...]
# run_type=all
[python, "-m", "pytest", "test_cases/test_single_api.py",
 "test_cases/test_gateway_flow.py", ...]

# 公共参数
f"--env={env}"
f"--flow={flow}"                    # 仅提供了 flow 时
"-m", tag                           # 仅提供了 tag 时
f"--junitxml=reports/junit-task-{task_id}.xml"
```

按【确认项 8】确认结论，平台任务不带 `--alluredir`，不生成 Allure 原始结果。

进程管理：

- `subprocess.Popen(args, cwd=PROJECT_ROOT, stdout/stderr → tasks/<id>/console.log, start_new_session=True)`；
- 等待线程 `proc.wait()` 返回后：解析 JUnit、按 PID 及任务起止时间关联日志文件，再在状态锁中提交终态；若任务已合法进入 `cancelled`，等待线程只补充退出码/产物信息，不覆盖终态；
- **取消**：在状态锁内记录 `cancel_requested_at`，发送 `SIGTERM`，宽限 10 秒未退出则 `SIGKILL`；确认退出后以首次合法终态写入 `cancelled`；
- **超时**：等待线程计时达到 `API_AUTOTEST_TASK_TIMEOUT_SECONDS` 后走同一终止流程，最终状态为 `failed`，`timeout=true`、`error_code=TASK_TIMEOUT`；
- **JUnit 边界**：取消或强制终止可能不会触发 pytest session finish，因此允许 JUnit 不存在；此时 `result_available=false`，不承诺部分 JUnit，也不因文件缺失覆盖 `cancelled`；
- **状态与存储原子性**：槽位检查、取消请求和终态提交使用同一 TaskManager 状态锁；任务 JSON 先写同目录临时文件，flush/fsync 后用 `os.replace` 替换正式文件；终态不可再次迁移；
- **启动恢复**：服务启动时扫描 `tasks/*.json`，将遗留 `pending`/`running` 置为 `failed`，错误信息“服务重启，任务中断”（容器重建后子进程必然不存在）。

### 8.4 接口契约

统一 JSON；错误返回 `{ "error": "可读信息" }` + 对应状态码（400/404/409/500）。列表分页沿用平台约定（`page`、`page_size` 默认 20 最大 100，响应含 `items/page/page_size/total`）。

提交任务：

```http
POST /api-autotest/api/tasks
{ "env": "test", "run_type": "flow", "flow": "AnonymousSessionMediaSearch", "tag": null }

→ 201
{ "id": "20260807-163012-a1b2", "status": "pending", "created_at": "..." }
```

任务详情 / 结果：

```http
GET /api-autotest/api/tasks/{id}          # 记录全量字段
GET /api-autotest/api/tasks/{id}/result
→ 200
{
  "status": "failed",
  "result_available": true,
  "summary": { "total": 8, "passed": 6, "failed": 1, "errors": 1, "skipped": 0 },
  "failed_cases": [
    { "name": "test_single_gateway_api[GetMe::get_me_success]", "message": "断言失败摘要（截断 500 字符）" }
  ]
}
```

取消或强制终止且未生成 JUnit 时返回 `200`，其中 `result_available=false`、`summary=null`、`reason_code=JUNIT_NOT_GENERATED`；Allure 报告属于独立 Jenkins/手工链路，不放入任务结果对象，避免误导为当前任务报告。

日志查看：

```http
GET /api-autotest/api/tasks/{id}/logs?tail=500    # tail 默认 500，上限 2000
→ 200 { "log_file": "logs/2026-08-07/..._test_12345.log", "lines": ["..."] }
```

日志优先返回框架脱敏日志文件内容。任务未产生日志文件时，可读取 `console.log` 作为内部兜底输入，但必须先执行壳服务二次脱敏并截断后才可响应，并标注 `source=console_redacted`；原始 `console.log`、原始 traceback 和容器绝对路径不得通过 API 返回。

二次脱敏至少覆盖：Bearer/Authorization、Cookie、`*_TOKEN`/`*_SECRET`/`*_PASSWORD`、`.env` 形式的敏感键值、预签名 URL 及常见敏感查询参数。错误摘要复用同一脱敏函数，并设置最大长度；自动化测试使用伪造 token 验证零明文泄漏。

用例库：

```http
GET /api-autotest/api/catalog
→ 200
{
  "apis":  [ { "id": "GetMe", "name": "...", "service_name": "...", "method_name": "..." } ],
  "cases": [ { "api": "GetMe", "id": "get_me_success", "name": "...", "tags": ["smoke"] } ],
  "flows": [ { "name": "AnonymousSessionMediaSearch", "tags": [], "step_count": 5, "apis": ["CreateAnonymousSession", "..."] } ],
  "errors": [ { "file": "data/flows/Bad.yaml", "message": "YAML 格式错误..." } ]
}
```

解析复用既有加载器；单个文件解析失败进入 `errors` 数组，不导致整体失败。

报告元信息：

```http
GET /api-autotest/api/report/meta
→ 200 { "exists": true, "report_url": "/api-autotest/reports/index.html",
        "synced_at": "2026-08-07T16:00:00+08:00", "source": "jenkins",
        "job_name": "InterfaceAutomation", "build_number": 123,
        "build_result": "FAILURE", "build_url": "http://jenkins/job/.../123/" }
```

元信息优先读取 current 指向版本目录内的 `report-meta.json`（发布脚本写入）。`source=jenkins` 时 job、build number、build result、build URL 为必填；手工来源可为空。元信息缺失时退化为目录 mtime，`source=unknown`，页面不得推断测试成功。

健康检查：

```http
GET /api-autotest/health
→ 200 { "status": "ok", "service": "api-autotest" }
```

不触发执行、不读取凭证、不依赖外部 Gateway。

### 8.5 页面设计

三个服务端渲染页面，风格与既有工具保持一致（原生 HTML/CSS/JS）：

- **首页**：工具简介与返回平台链接；凭证状态（按所选任务显示基础配置/专属凭证是否就绪，不展示值）；执行表单（env 下拉来自 `config/env/`，run_type 单选，flow 下拉来自 `data/flows/`，tag 输入）；运行中提示与提交禁用；报告区（入口 + 同步时间 + 来源；Jenkins 报告展示构建号和构建结果，并标注“外部报告，与平台任务无直接关联”）；最近任务表（5 秒轮询，仅存在非终态任务时轮询）；
- **任务详情页**：参数与时间线、JUnit 统计、失败用例清单、日志查看（默认尾部 500 行，可切换）；
- **用例库页**：API / Case / Flow 三个列表与解析错误提示。

报告在 `{BASE}/reports/index.html` 直接打开（同标签页），报告页顶部由壳服务无法注入内容，因此在首页报告入口处展示敏感数据提示文案。

---

## 9. Dockerfile 与镜像设计

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

COPY . .

EXPOSE 5003

CMD ["python", "-m", "web.app"]
```

要点：

- 依赖分文件：`requirements.txt`（框架，不动）+ `requirements-web.txt`（新增，仅 `flask>=3.0,<4.0`），见【确认项 3】；
- 镜像不包含 Node/npm/Allure CLI；
- `.dockerignore` 必须排除：`.env*`、`logs/`、`reports/`、`allure-results/`、`tasks/`、`__pycache__/`、`.venv/`、`docs/`、`.git/`；`data/`（含 `data/photo/` 上传素材）与 `config/` 保留在镜像内；
- 平台模式下 `data/` 以只读卷覆盖镜像内副本（见【确认项 4】与 11 章），保证用例资产与仓库实时一致；
- 健康检查由 Compose 定义（镜像内用 Python 标准库 urllib，避免安装 curl/wget）。

---

## 10. 凭证与配置设计

### 10.1 平台专用凭证文件

- 文件：`Truthy_ApiAutoTest2/.env.platform`（可写，不提交 Git）；
- 模板：新增 `.env.platform.example`，字段与 README 第 2 节一致（`AUTH_TOKEN`、`REFRESH_TOKEN`、`USER_ID`、`DEVICE_ID`、`EXPIRES_TIME`、`REFRESH_EXPIRES_TIME`、`ADMIN_*`）；
- 平台模式挂载为容器内 `/app/.env`（框架读取与写回路径，零框架改动）；
- 本地开发继续使用个人 `.env`；平台 `.env.platform` 使用不同测试账号/会话，与本地状态隔离（【确认项 5】）。

### 10.2 缺失与异常处理

- 平台模式要求 `/app/.env` 是可写普通文件；宿主 `.env.platform` 缺失时 Docker bind mount 可能创建目录，壳服务应识别为 `CREDENTIAL_FILE_INVALID` 并拒绝提交。普通文件内容是否就绪由 `load_settings(env)` 的合并结果判断，不要求 `DEVICE_ID` 必须写在该文件内；
- 会话写回失败（磁盘/权限）由框架抛出，任务以 `failed` 记录错误信息，不静默。

### 10.3 禁止事项

凭证不进入镜像、前端、Git、接口响应；任务提交参数不进入 shell；页面与日志接口不输出凭证原文。

---

## 11. 数据与文件设计

### 11.1 目录与卷挂载

| 内容 | 宿主路径 | 容器路径 | 模式 |
|---|---|---|---|
| 平台凭证 | `../Truthy_ApiAutoTest2/.env.platform` | `/app/.env` | 可写 |
| 用例资产 | `../Truthy_ApiAutoTest2/data` | `/app/data` | 只读（【确认项 4】） |
| 执行日志 | `../Truthy_ApiAutoTest2/logs` | `/app/logs` | 可写 |
| JUnit/报告目录 | `../Truthy_ApiAutoTest2/reports` | `/app/reports` | 可写 |
| Allure 原始结果 | 平台任务不生成，不挂载（【确认项 8】确认） | — | — |
| 任务记录 | `../Truthy_ApiAutoTest2/tasks` | `/app/tasks` | 可写 |

`config/` 随镜像打包，不挂载（环境配置变更需重建镜像，可接受；如需热更可后续调整）。

### 11.2 命名与清理策略

- 任务 JUnit：`reports/junit-task-<task_id>.xml`；任务记录删除时同步删除（【确认项 10】）；
- `console.log`：`tasks/<task_id>/console.log`，随任务记录删除；
- `logs/`：不清理，沿用框架 7 天策略；
- 保留策略：任务记录按 ID 倒序保留 `API_AUTOTEST_TASKS_RETAIN`（默认 50）条，超出在新任务落盘时清理；
- Jenkins 产物命名（`junit-all/single/flow.xml`）与任务产物命名互不冲突；平台目录中的 Jenkins 历史文件不在本服务清理范围内。

### 11.3 报告版本目录与原子发布

- 版本目录：`Truthy_ApiAutoTest2/reports/allure-reports/<version>/`；当前指针：`Truthy_ApiAutoTest2/reports/allure-current`（对外只展示 current 指向的一份，【确认项 6】）；
- `version` 使用不可冲突的构建标识：Jenkins 为 `jenkins-<job-safe-name>-<build-number>`，手工为 `manual-<UTC timestamp>-<random>`；
- 元信息：版本目录内 `report-meta.json` 至少包含 `{ "generated_at": "...", "source": "jenkins|manual", "allure_version": "3.14.3" }`；Jenkins 来源额外包含 `job_name`、`build_number`、`build_result`、`build_url`；
- 发布脚本 `scripts/publish_allure_report.sh` 行为：

```text
输入：源 HTML 目录、报告根目录（默认项目内 reports）、来源及构建元信息
1. 校验源目录存在 index.html，否则退出码 2；
2. 获取发布锁，清理无引用且超过安全时间的临时目录；
3. 将完整报告复制到 allure-reports/.<version>.tmp，并写入 report-meta.json；
4. 再次校验暂存目录 index.html 与元信息，然后改名为 allure-reports/<version>；
5. 在 reports 下创建指向新版本的临时相对软链接 .allure-current.tmp；
6. 使用同文件系统原子 rename/replace 将临时链接替换为 allure-current；旧 current 在此之前始终可用；
7. 切换成功后删除旧版本；失败时保留旧 current，并清理本次临时目录。
```

- 禁止采用“先把当前非空目录改名为 `.bak`，再把 `.new` 改为当前目录”的两步方案，该方案存在 404 空窗和中断后 current 缺失风险；
- 壳服务对该目录只读展示，不写入；
- `.gitignore` 追加：`reports/allure-reports/`、`reports/allure-current`、`tasks/`、`.env.platform`、`allure-results/`（如尚未覆盖）。

---

## 12. Jenkins 链路调整设计

按【确认项 11】确认的备选方案：Jenkins 不直接写宿主平台目录，只做产物归档；由宿主机拉取脚本拉取后发布。不改动执行阶段。

### 12.1 Jenkins 侧调整（post 阶段）

1. 现有 `allure(...)` 插件发布保留（Jenkins 页面内查看不受影响）；
2. 新增 sh 步骤：明确在 `dir("${PROJECT_DIR}")` 作用域内生成 HTML 报告

```bash
allure awesome allure-results --output allure-report-publish
```

3. 在相同 `dir("${PROJECT_DIR}")` 作用域调用 `archiveArtifacts('allure-report-publish/**')`，使 Jenkins 归档根固定为 `archive/allure-report-publish/`；若归档仍在工作区根调用，则 pattern 和拉取路径必须统一改为带 `Truthy_ApiAutoTest2/` 前缀，禁止两种写法混用；
4. 生成/归档失败可将原本成功的构建标记为 `UNSTABLE`，但不得把 pytest `FAILURE` 改为成功或掩盖测试结论；文档和页面需区分“测试结果”与“报告发布状态”。

### 12.2 宿主机拉取脚本

新增 `scripts/fetch_jenkins_report.sh`：

```text
入参（均可选）：
  JENKINS_HOME（默认 ~/.jenkins）、JOB_NAME（默认 InterfaceAutomation）、
  BUILD_NUMBER（缺省选择最近一次已完成且包含 HTML 归档产物的构建）
步骤：
  1. 若显式指定 BUILD_NUMBER，直接校验该构建；否则从新到旧扫描已完成构建，
     选择第一个包含目标归档的构建，不按 SUCCESS/FAILURE/UNSTABLE 过滤；
  2. 定位构建产物目录（以下路径依赖 12.1 的统一 dir 作用域）：
     ${JENKINS_HOME}/jobs/${JOB_NAME}/builds/${BUILD_NUMBER}/archive/allure-report-publish
  3. 校验存在且包含 index.html，并读取构建 result、URL 等元信息，否则以非零退出码报错；
  4. 调用 publish_allure_report.sh <产物目录> <报告根目录> jenkins <构建元信息> 完成原子发布。
```

- MVP 触发方式：手动执行或用户自备 cron，不内置于平台与工具；
- 本地文件系统读取仅适用于 Jenkins 与平台宿主机可访问同一 `JENKINS_HOME` 的部署；若为 Jenkins Folder/Multibranch、容器化或远端 Jenkins，必须改用 Jenkins Artifact HTTP API 并配置受控凭证；
- Jenkins 任务名、归档目录结构在阶段 4 以一次成功构建和一次测试失败构建共同验证，脚本默认值按实际调整。

### 12.3 手动执行链路

宿主机手动执行使用同一发布脚本，`source` 传 `manual`，命令写入工具 README。

---

## 13. 平台侧接入设计

### 13.1 Docker Compose 新增服务

```yaml
  api-autotest:
    build:
      context: ../Truthy_ApiAutoTest2
    environment:
      API_AUTOTEST_HOST: 0.0.0.0
      API_AUTOTEST_PORT: "5003"
      API_AUTOTEST_BASE_PATH: /api-autotest
      PLATFORM_HOME_URL: /
      API_AUTOTEST_TASK_TIMEOUT_SECONDS: "${API_AUTOTEST_TASK_TIMEOUT_SECONDS:-1800}"
      API_AUTOTEST_TASKS_RETAIN: "${API_AUTOTEST_TASKS_RETAIN:-50}"
    volumes:
      - ../Truthy_ApiAutoTest2/.env.platform:/app/.env
      - ../Truthy_ApiAutoTest2/data:/app/data:ro
      - ../Truthy_ApiAutoTest2/logs:/app/logs
      - ../Truthy_ApiAutoTest2/reports:/app/reports
      - ../Truthy_ApiAutoTest2/tasks:/app/tasks
    expose:
      - "5003"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5003/api-autotest/health', timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: unless-stopped
```

同时把 `api-autotest` 追加到 `platform-gateway.depends_on`。启动前置条件：`.env.platform` 已存在（否则 bind mount 生成目录，服务降级但健康；上线检查单中强制核对）。

### 13.2 Nginx 新增路由

与既有工具块同构：

```nginx
location = /api-autotest {
    return 308 /api-autotest/;
}

location /api-autotest/ {
    set $api_autotest_upstream api-autotest:5003;
    proxy_pass http://$api_autotest_upstream;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /api-autotest;
    proxy_connect_timeout 3s;
    proxy_read_timeout 60s;
    proxy_intercept_errors on;
    error_page 502 503 504 /tool-unavailable.html;
}
```

报告静态资源体积较大但为内网访问，沿用现有超时与 `client_max_body_size 25m` 即可（报告链路无上传）。

### 13.3 Alembic 迁移

新增 `backend/alembic/versions/20260807_0003_add_api_autotest_tool.py`（`down_revision = "20260731_0002"`），以 `op.bulk_insert` 写入：

```python
{
    "id": "api-autotest",
    "name": "接口自动化",
    "description": "触发 Gateway 接口自动化执行，查看回归结果与 Allure 报告",
    "entry_url": "/api-autotest/",
    "health_url": "http://api-autotest:5003/api-autotest/health",
    "short_code": "API",
    "icon_key": "api",
    "category": "automation",
    "features": ["执行触发", "结果统计", "报告查看"],
    "sort_order": 40,
    "is_enabled": True,
}
```

`downgrade()` 仅删除该记录。迁移测试沿用 `backend/tests/test_migrations.py` 现有模式补充断言。

### 13.4 前端卡片与图标

- `frontend/src/data/fallbackTools.ts` 追加：

```typescript
{
  id: "api-autotest",
  name: "接口自动化",
  description: "触发 Gateway 接口自动化执行，查看回归结果与 Allure 报告。",
  entry_url: "/api-autotest/",
  short_code: "API",
  icon_key: "api",
  category: "automation",
  features: ["执行触发", "结果统计", "报告查看"],
  sort_order: 40,
  fallback_health_path: "/api-autotest/health",
}
```

- `ToolCard.tsx` 图标映射追加 `api: { className: "tool-icon-api", label: "AP" }`；
- `app.css` 追加 `.tool-icon-api` 配色（沿用现有图标样式结构）。

### 13.5 平台冒烟测试

`test-platform/tests/test_smoke.py` 追加：

```text
GET  /api-autotest/            → 200
GET  /api-autotest/health      → 200 + status=ok
GET  /api-autotest/api/catalog → 200
GET  /api-autotest/api/tasks   → 200
GET  /unknown                  → 404（保持）
```

---

## 14. 安全设计

- 命令注入：子进程参数数组化，无 shell；`env`/`flow` 做目录存在性与字符白名单校验后才拼入参数；
- 凭证：见第 10 章；构建上下文排除 `.env*`；
- 上传：本工具无用户上传入口；请求体限制沿用网关 25 MB；
- 日志与报告：框架日志可直接读取；`console.log` 等其他内容必须二次脱敏和截断后展示；接口不返回凭证、环境变量值、原始 traceback 或容器内部绝对路径；
- 取消接口无鉴权（平台整体无登录，PRD 已确认），取消仅影响本工具任务。

---

## 15. 文件影响范围

### 15.1 Truthy_ApiAutoTest2（新增为主）

| 文件/目录 | 动作 |
|---|---|
| `web/`（app、task_manager、task_store、junit_report、catalog、credentials、templates） | 新增 |
| `tests/`（壳服务测试） | 新增 |
| `scripts/publish_allure_report.sh`、`scripts/fetch_jenkins_report.sh` | 新增 |
| `requirements-web.txt` | 新增（【确认项 3】） |
| `Dockerfile`、`.dockerignore` | 新增 |
| `.env.platform.example` | 新增 |
| `.gitignore` | 追加运行时目录 |
| `README.md` | 追加平台接入与手动发布报告说明 |
| `runtest.py`、`api/`、`utils/`、`test_cases/`、`data/`、`config/` | **不修改** |

### 15.2 test-platform

| 文件 | 动作 |
|---|---|
| `docker-compose.yml` | 新增 `api-autotest` 服务；`platform-gateway.depends_on` 追加 |
| `nginx/nginx.conf` | 新增 `/api-autotest` 两块 location |
| `backend/alembic/versions/20260807_0003_add_api_autotest_tool.py` | 新增 |
| `backend/tests/test_migrations.py` | 补充断言 |
| `frontend/src/data/fallbackTools.ts` | 追加工具 |
| `frontend/src/components/ToolCard.tsx`、`frontend/src/app.css` | 追加图标 |
| `tests/test_smoke.py` | 追加冒烟用例 |
| `.env.example` | 追加 `API_AUTOTEST_*` 可选项说明 |

### 15.3 Jenkins

| 文件 | 动作 |
|---|---|
| `Truthy_ApiAutoTest2/Jenkinsfile` | post 阶段追加 HTML 生成与 `archiveArtifacts` 调整；执行阶段不改 |

---

## 16. 开发执行顺序

### 阶段 0：基线冻结

1. 记录工作区 Git 状态；
2. 运行框架回归 `python3 -m pytest -q -k "not gateway_flow and not single_gateway_api"`，记录用例数与结果；
3. 运行壳服务将依赖的加载器现有测试（如有），确认基线；
4. 实测 Docker bridge 网络到 `config/env/test.yaml` 中 `gateway_base_url` 的连通性（【确认项 9】）；
5. 确认 Jenkins 最近一次成功构建和一次测试失败构建的产物形态、归档根路径与 build result 元数据。

完成标准：基线数字明确；网络连通性结论记录。

### 阶段 1：工具壳服务（独立模式）

1. `web/` 骨架：app 工厂、健康检查、首页占位；
2. task_store + task_manager（含原子槽位、JSON 原子落盘、取消/完成竞态、超时、启动恢复）；
3. 配置合并级和任务级凭证预检、参数校验；
4. JUnit 解析、缺失结果语义、日志关联与 console 二次脱敏；
5. catalog 接口；
6. 页面（首页、任务详情、用例库）；
7. 壳服务单元测试全量通过（不发真实请求，子进程用 `pytest --collect-only` 或 mock 命令替代）。

完成标准：根路径模式下完整跑通“提交 → 执行 → 结果 → 日志 → 取消 → 超时”闭环（可用框架回归命令作为被驱动对象验证引擎，不依赖真实 Gateway）。

### 阶段 2：容器化与子路径

1. `requirements-web.txt`、`Dockerfile`、`.dockerignore`；
2. `API_AUTOTEST_BASE_PATH` 全链路生效（页面、接口、静态报告）；
3. `.env.platform.example` 与凭证预检在挂载场景验证；
4. 镜像内无 `.env` 检查。

完成标准：容器独立启动（`docker run` 手动指定挂载）完成一次真实 `single` 执行。

### 阶段 3：平台接入

1. Alembic 迁移与迁移测试；
2. 前端回退目录、图标、卡片渲染测试；
3. Nginx 路由与错误页；
4. Compose 服务与 healthcheck；
5. 平台冒烟测试。

完成标准：`docker compose up -d --build` 后，首页出现第四张卡片，入口、状态探测、执行闭环均正常。

### 阶段 4：报告同步链路

1. `scripts/publish_allure_report.sh` 与脚本自测（正常源、缺 index.html、并发发布、current 已存在、切换前后模拟中断）；
2. `scripts/fetch_jenkins_report.sh` 与自测（成功/失败/不稳定构建选择、构建目录定位、归档缺失）；
3. Jenkinsfile post 调整（统一 `dir(PROJECT_DIR)` 作用域、HTML 生成 + 归档），分别触发成功与测试失败构建验证产物；
4. 宿主机拉取链路验证（fetch 脚本 → 发布脚本 → 页面）；
5. 宿主机手动链路验证（runtest + allure awesome + 发布脚本）；
6. 平台页面报告展示与子路径资源加载专项验证。

完成标准：两条来源（Jenkins 拉取、手动）各发布一次，页面均可打开完整报告；失败构建报告可被选中且结果标识正确；发布和模拟中断期间旧报告持续可用，不出现半份报告或 404。

### 阶段 5：端到端验收与文档

1. PRD 第 14 章验收项逐项执行；
2. 故障隔离验证（停止 api-autotest、停止平台 API/DB）；
3. 回归：框架回归、壳服务测试、平台冒烟、既有三个工具抽测；
4. README、接入说明、排障与回滚文档更新。

---

## 17. 自动化测试计划

### 17.1 工具壳单元测试（不发真实请求）

- task_manager：参数校验矩阵；配置合并级/Flow 专属凭证缺失拒绝；两个并发提交只有一个成功；取消与完成竞态不覆盖终态；超时路径（用 `sleep` 子进程模拟）；启动恢复；
- task_store：临时文件 + fsync + `os.replace` 原子落盘、轮询并发读取、列表排序、保留与关联产物清理；
- junit_report：正常/失败/错误/跳过统计、全量跳过映射、空文件、缺文件、取消时 `result_available=false`、失败摘要截断；
- redaction：Bearer/Cookie、常见敏感键、`.env` 格式、预签名 URL、traceback 中的容器路径；原始 console 永不直接返回；
- catalog：对当前 `data/` 真实目录解析快照；构造坏 YAML 进入 `errors` 分支；
- web_routes：Flask test client 覆盖全部接口状态码与基础路径两种模式；健康检查不依赖凭证。

### 17.2 框架回归

`python3 -m pytest -q -k "not gateway_flow and not single_gateway_api"` 与阶段 0 基线一致。

### 17.3 平台测试

- 后端迁移测试：升级到 head 后 `tools` 含 4 条记录，`api-autotest` 字段正确；
- 前端：回退目录渲染 4 张卡片；未知 icon_key 回退不报错（现有用例扩展）；
- 冒烟：13.5 清单。

### 17.4 集成与手工

- 真实执行：`single`（全部单接口）与指定 Flow 各一次，核对统计与日志；
- 凭证来源与任务依赖：`DEVICE_ID` 分别来自 YAML/.env；需要 Admin 凭证的 Flow 在缺失和完整配置下行为正确；
- 凭证刷新场景：构造临期 `EXPIRES_TIME`，验证刷新后 `.env.platform` 写回且后续任务成功；
- 报告 current 指针原子性、发布中断恢复与子路径资源；页面刷新/后退/返回平台；
- Jenkins 拉取链路：各触发一次成功和测试失败构建，默认选择最新已完成且含报告的构建，页面展示构建号与结果。

---

## 18. 验收标准

直接采用 PRD 第 14 章四组验收项（平台 / 任务能力 / 报告与用例库 / 隔离与回归），此处不重复。工程补充：

- [ ] 镜像层检查无 `.env`（`docker history` 与构建上下文核对）；
- [ ] `tasks/`、`reports/allure-reports/`、`reports/allure-current`、`.env.platform` 均在 `.gitignore`；
- [ ] Jenkins post 报告失败不掩盖 pytest `FAILURE`；测试成功时若标记 `UNSTABLE`，页面和文档可区分测试结论与发布状态。

---

## 19. 上线切换步骤

1. 合并工具侧代码，本地独立模式自测通过；
2. 在 `Truthy_ApiAutoTest2/` 创建 `.env.platform`（从 `.env.platform.example` 复制并填入平台专用会话，见【确认项 5】）；
3. 平台侧代码合并，`docker compose build api-autotest platform-gateway`；
4. `docker compose up -d`，核对 4 张卡片与冒烟清单；
5. 手动执行一次报告发布脚本，验证报告页；
6. 合并 Jenkinsfile post 调整，触发一次构建验证产物归档；运行 fetch 脚本验证报告页面；
7. 观察一个工作日：任务记录、日志增长、报告更新、凭证写回。

---

## 20. 回滚方案

### 20.1 平台接入回滚

- 将 `tools` 中 `api-autotest` 置 `is_enabled=false`（卡片隐藏），或回退迁移；
- Compose 移除 `api-autotest` 服务并 `docker compose up -d`；
- Nginx 配置回退；网关重启不影响其他工具。

### 20.2 工具侧回滚

- 工具侧改动全部为新增文件，`git revert` 即可；框架核心未动，终端与 Jenkins 执行不受影响；
- 平台任务运行时目录为 `tasks/` 和 `reports/junit-task-*.xml`；平台任务不生成 `allure-results/<task_id>/`。清理前先停止服务，并保留当前报告版本及 `allure-current`；

### 20.3 Jenkins 回滚

- post 发布步骤独立成块，revert 该提交即恢复原状；Jenkins 页面内 Allure 发布不受影响。

### 20.4 数据

- 无任务业务表或表结构变更；平台存在一条 Alembic 数据迁移用于写入 `tools` 目录记录，回滚时按 20.1 downgrade/禁用该记录；任务记录与执行产物均为文件；
- `.env.platform` 中的会话状态丢弃无副作用（重新创建会话即可）。

---

## 21. 风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| 容器到 Gateway 网络不通 | 平台任务全部失败 | 阶段 0 实测；任务错误信息透出原因 |
| 配置来源误判或专属凭证缺失导致 skip 假成功 | 结果误导 | 复用 `load_settings`，按 Flow 校验 `ADMIN_*`；全量 skipped 映射 `ALL_TESTS_SKIPPED` |
| 并发提交、取消与完成竞态 | 多进程执行、终态覆盖、JSON 损坏 | 原子槽位锁、合法状态迁移锁、临时文件 + fsync + `os.replace`；专项并发测试 |
| 原始 console/traceback 绕过脱敏 | 凭证、查询参数或容器路径泄漏 | 统一二次脱敏和截断；原始 console 不通过 API 返回 |
| Allure 报告子路径资源 404 | 报告打不开 | 阶段 4 专项验证；必要时在发布脚本内校正相对路径 |
| 报告目录两步替换存在空窗或中断 | 页面 404、current 丢失 | 版本目录写完后原子切换 current 指针；失败保持旧版本 |
| 只选择 Jenkins 成功构建 | 测试失败时展示旧报告 | 选择最近已完成且有 HTML 产物的构建；元信息展示 build result |
| 平台与本地/Jenkins 并发执行 | 会话与数据冲突 | 文档声明互斥；平台侧单槽位；账号隔离（【确认项 5】） |
| `.env.platform` 缺失被 Docker 挂成目录 | 服务降级 | 启动检测 + 上线检查单强制核对 |
| 长任务与健康探测互相影响 | 卡片状态抖动 | 健康检查只测 Web 进程，与执行引擎解耦 |
| 任务产物磁盘增长 | 占满磁盘 | 保留策略 + 任务删除联动清理（【确认项 10】） |
| pytest 版本升级改变退出码/JUnit 结构 | 解析失效 | requirements 锁定 pytest>=8,<9；解析层只依赖标准 JUnit 结构 |
| Jenkins 归档作用域、Folder/Multibranch 或远端部署与本地路径假设不符 | 拉取不到报告 | 固定 `dir(PROJECT_DIR)` 归档根；真实构建核对；非本地 Jenkins 改用 Artifact HTTP API |

---

## 22. 确认项结论（2026-08-07 已确认）

用户确认结论：事项 1、2、3、4、5、6、7、9、10 采用推荐方案；事项 8、11 采用备选方案。

| 编号 | 设计点 | 结论 |
|---|---|---|
| 确认项 1 | 平台执行的命令构成 | 壳服务直接构造 `python -m pytest <入口文件>`，与 Jenkinsfile `RUN_TYPE` 语义完全一致（PRD 措辞已同步修订） |
| 确认项 2 | 壳服务代码位置 | 新增 `web/` 包 + `tests/` 目录 |
| 确认项 3 | Flask 依赖载体 | 新增 `requirements-web.txt`，不动框架 `requirements.txt` |
| 确认项 4 | `data/` 供给方式 | 平台模式只读挂载宿主 `data/`（PRD 措辞已同步修订） |
| 确认项 5 | 平台专用凭证账号策略 | `.env.platform` 使用与本地不同的测试账号/会话，避免写回冲突 |
| 确认项 6 | Allure HTML 保留策略 | 对外只展示 current 指向的最新一份；以版本目录生成并原子切换，成功后清理旧版本 |
| 确认项 7 | pytest 退出码 5 | 映射为 `failed` 并标注“未收集到用例” |
| 确认项 8 | 平台任务是否生成 `allure-results` | **不生成**（备选方案）：执行命令不带 `--alluredir`，容器不挂载该目录；后续如需从平台任务出报告需另行改造 |
| 确认项 9 | 容器出口网络 | 阶段 0 实测 Docker bridge → `gateway_base_url` 连通 |
| 确认项 10 | 任务记录清理范围 | 删除记录时同步删除 `junit-task-<id>.xml`、`console.log`；`logs/` 交给框架 7 天策略（平台任务不产生 allure 产物） |
| 确认项 11 | Jenkins 报告发布目标 | **备选方案**：Jenkins 仅生成 HTML 并归档构建产物，不直接写宿主目录；宿主机拉取最近已完成且存在 HTML 产物的构建，再通过版本目录 + current 指针原子发布（见第 12 章） |

原与 PRD 的执行命令、`data/` 挂载、清理范围、Allure 目录和 Jenkins post 表述偏差已在 PRD V1.2 中同步修订。

---

## 23. 任务拆分与依赖

| 编号 | 任务 | 依赖 | 主要产出 |
|---|---|---|---|
| T0 | 基线冻结与网络实测 | 无 | 基线记录、连通性结论 |
| T1 | 壳服务骨架与健康检查 | T0 | `web/` 骨架、health |
| T2 | 任务引擎（执行/取消/超时/恢复） | T1 | task_manager、task_store |
| T3 | 结果链路（JUnit/日志/凭证预检） | T2 | junit_report、credentials |
| T4 | 用例库与页面 | T1 | catalog、三个页面 |
| T5 | 壳服务单元测试 | T2、T3、T4 | `tests/` |
| T6 | Dockerfile 与子路径 | T5 | 镜像、基础路径 |
| T7 | 平台迁移/前端/Nginx/Compose | T6 | 平台接入件 |
| T8 | 报告发布/拉取脚本与 Jenkins 归档调整 | T6 | 脚本、Jenkinsfile |
| T9 | 冒烟与端到端验收 | T7、T8 | 验收记录 |
| T10 | 文档与检查单 | T9 | README、回滚说明 |

执行主线：

```text
T0 → T1 → T2 → T3 ┐
        └→ T4 ─────┼→ T5 → T6 ─┬→ T7 ─┬→ T9 → T10
                              └→ T8 ─┘
```

---

## 24. 最终执行检查单

### 开发前

- [ ] 第 22 章确认项全部有结论；
- [ ] 阶段 0 基线与网络实测完成；
- [ ] `.env.platform` 账号策略确定。
- [ ] Jenkins 成功/失败构建的归档根路径和元数据读取方式已实测确定。

### 开发中

- [ ] 框架核心零改动（提交前 diff 核对）；
- [ ] 壳服务测试不发真实请求；
- [ ] 并发提交、取消/完成竞态、JSON 原子落盘和 console 二次脱敏测试通过；
- [ ] 镜像无凭证（构建上下文与 `docker history` 核对）。

### 上线前

- [ ] `.env.platform` 已创建且非目录；
- [ ] 冒烟清单全部通过；
- [ ] Jenkins 成功/失败构建拉取与手工报告链路均验证；current 切换中断时旧报告仍可用；
- [ ] 回滚步骤演练或至少走查一遍。
