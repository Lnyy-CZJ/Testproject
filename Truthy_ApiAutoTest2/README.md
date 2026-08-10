# Gateway 接口自动化 V1.3

这是一个基于 Python、pytest、requests 和 PyYAML 的轻量接口自动化框架。
HTTP 地址固定为 Gateway，业务接口通过 `service_name` 和 `method_name` 区分。

V1.3 将接口定义与测试数据彻底拆开：

```text
接口定义 APIs
├── 单接口 Cases
└── 多接口 Flows + Scenarios
```

- API 只保存业务路由。
- Case 保存单接口测试参数、标签和断言。
- Flow 保存步骤顺序、提取、等待和轮询。
- Scenario 保存 Flow 每个接口步骤的完整参数和断言。
- Flow、自动会话均不读取单接口 Cases。

## 1. 安装依赖

建议使用 Python 3.10 及以上版本和独立虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## 2. 配置环境与会话

非敏感环境配置位于 `config/env/<环境>.yaml`。本地 `.env` 保存凭证和可复用
会话状态，禁止提交到仓库：

```bash
AUTH_TOKEN=your_access_token
REFRESH_TOKEN=your_refresh_token
USER_ID=your_user_id
DEVICE_ID=your_device_id
EXPIRES_TIME=milliseconds_since_epoch
REFRESH_EXPIRES_TIME=milliseconds_since_epoch
ADMIN_SESSION_TOKEN=your_admin_session_token
ADMIN_OPERATOR_ID=your_admin_operator_id
ADMIN_OPERATOR_NAME=your_admin_operator_name
```

启动时优先复用未临期的 access token。token 距过期不足配置的安全窗口时，
框架使用 `RefreshSession` API 定义刷新；刷新失败或 refresh token 已过期时，
使用 `CreateAnonymousSession` API 定义重建会话。

创建或刷新成功后，token、用户 ID 和过期时间会更新到 `.env`。终端显式设置的
同名环境变量优先于 `.env`。
`AnonymousSessionMediaSearch` 的两个 Admin 审计步骤使用三个 `ADMIN_*` 字段访问
独立的 Admin Gateway；pytest 真实 Flow 在任一字段缺失时会跳过，并提示对应变量名。

## 3. 目录职责

| 目录 | 职责 |
| --- | --- |
| `config/` | 默认配置和按环境变化的 Gateway 地址 |
| `data/api/` | Gateway 固定 HTTP 方法、路径和请求头 |
| `data/apis/` | 业务 API ID、`service_name` 和 `method_name` |
| `data/cases/` | 单接口多 case 的参数、标签、断言和可选提取 |
| `data/flows/` | 多接口步骤顺序、提取、等待、轮询和特殊 action |
| `data/scenarios/` | Flow 各接口步骤的完整参数和断言 |
| `api/` | Gateway 请求信封构造和调用入口 |
| `utils/custom/` | 配置、HTTP、日志、断言及 YAML 加载工具 |
| `utils/third_party/` | Allure、Jenkins、飞书等第三方集成预留层 |
| `test_cases/` | pytest 框架测试和真实接口测试入口 |
| `logs/` | 每次执行产生的脱敏请求、响应和异常日志 |
| `reports/` | 测试报告和运行产物预留目录 |

## 4. 运行测试

统一通过根目录 `runtest.py` 执行：

```bash
# 收集全部测试，不发送请求
python3 runtest.py --env test -- --collect-only

# 按 pytest 关键字筛选
python3 runtest.py --env test --module single_api

# 按 Case 或 Flow 中的 tags 筛选
python3 runtest.py --env test --tag smoke

# 收集或执行指定 Flow
python3 runtest.py --env test --flow AnonymousSessionMediaSearch -- --collect-only
python3 runtest.py --env test --flow AnonymousSessionMediaSearch

# 直接调试指定 Flow，并在终端显示请求和响应日志
python3 test_cases/test_gateway_flow.py \
  --env test \
  --flow AnonymousSessionMediaSearch

# 透传其他 pytest 参数
python3 runtest.py --env test --tag smoke -- -x -vv
```

只运行不发送真实请求的框架回归：

```bash
python3 -m pytest -q -k "not gateway_flow and not single_gateway_api"
```

直接调试单接口时，请运行通用入口：

```bash
python3 test_cases/test_single_api.py --env test
```

该入口保留 `-s --log-cli-level=INFO`，终端会实时显示脱敏后的请求和响应。

### 精确调试一条 Case

在 `test_cases/test_single_api.py` 中临时设置完整 Case ID：

```python
RUN_CASE_IDS: tuple[str, ...] = ("GetMe::get_me_success",)
```

正式代码应保持为空元组：

```python
RUN_CASE_IDS: tuple[str, ...] = ()
```

框架当前不增加 `--case` 参数。完整 ID 格式固定为：

```text
ApiId::case_id
```

## 5. 新增 API 定义

每个业务接口在 `data/apis/` 中维护一份定义，文件名必须等于 API ID：

```yaml
# data/apis/GetTask.yaml
id: GetTask
name: 获取搜索任务状态
request:
  service_name: tool.people_insight.SearchService
  method_name: GetTask
```

API 定义不得包含 `params`、`assert`、`extract`、`tags` 或 `cases`。

如果新接口只用于 Flow，只创建 API 定义即可，不需要创建空 Case 文件。

## 6. 新增单接口多 Case

Case 文件名必须与引用的 API ID 一致。一个文件可以配置成功、缺参、多参等多条
独立用例：

```yaml
# data/cases/GetTask.yaml
api: GetTask
cases:
  - id: get_task_success
    name: 获取任务成功
    tags: [smoke, search, positive]
    request:
      params:
        task_id: task_example
    assert:
      http_status: 200
      gateway:
        code: 0
        message: ok
      response:
        id: req_0
        success: true
        code: 0
        message: ok
      data_fields:
        - status
        - task_id

  - id: get_task_missing_task_id
    name: 缺少 task_id
    tags: [search, negative]
    request:
      params: {}
    assert:
      http_status: 200
      gateway:
        code: 0
      response:
        id: req_0
        success: false
```

每条 `request.params` 和 `assert` 都是完整数据，不继承同文件其他 case，也不从
API 定义补充默认参数。缺参用例直接省略目标参数。

`data_fields` 只校验字段存在，允许空字符串、`0`、`false` 和空数组。
需要保存响应值时，可增加以业务响应 `data` 为根的提取规则：

```yaml
extract:
  task_id: $.task_id
```

## 7. 新增标准多接口 Flow

在 `data/flows/` 和 `data/scenarios/` 中创建同名文件：

```text
data/flows/DemoFlow.yaml
data/scenarios/DemoFlow.yaml
```

Flow 直接引用 API ID，只保存控制信息：

```yaml
# data/flows/DemoFlow.yaml
name: 搜索流程
tags: [flow, search]
steps:
  - id: create_task
    api: CreateIntentTask
    extract:
      task_id: $.task_id

  - id: poll_task
    api: GetTask
    until:
      path: $.status
      equals: SUCCEEDED
      interval_seconds: 2
      timeout_seconds: 120
```

Scenario 为每个 API 步骤提供完整参数和断言：

```yaml
# data/scenarios/DemoFlow.yaml
name: 搜索成功场景
step_data:
  create_task:
    params:
      client_request_id: "{{client_request_id}}"
      match_strategy: UNION
      clues: []
      additional_details: []
    assert:
      http_status: 200
      gateway: {code: 0, message: ok}
      response: {id: req_0, success: true, code: 0, message: ok}
      data_fields: [status, task_id]
      data_equals:
        status: QUEUED

  poll_task:
    params:
      task_id: "{{task_id}}"
    assert:
      http_status: 200
      gateway: {code: 0, message: ok}
      response: {id: req_0, success: true, code: 0, message: ok}
      data_fields: [status, task_id]
      data_equals:
        status: SUCCEEDED
```

Flow 规则：

- 前序步骤通过 `extract` 写入当前 Flow 的运行时上下文。
- 后续步骤通过 `{{变量名}}` 引用已提取值。
- `until.path` 和 `data_equals` 都以业务响应 `data` 为根。
- 固定等待使用 `wait.seconds`。
- 特殊对象存储上传使用 `action: prepared_media_upload`。
- 不同 Flow 的运行时上下文相互隔离。
- Flow 不读取或合并 `data/cases`。

### 本地筛选多个 Flow

在 `test_cases/test_gateway_flow.py` 中临时设置 Flow 文件名 stem：

```python
RUN_FLOW_IDS: tuple[str, ...] = (
    "AnonymousSessionMediaSearch",
    "AnotherFlow",
)
```

正式代码应保持为空元组以收集全部 Flow。命令行 `--flow` 优先于
`RUN_FLOW_IDS`，适合临时执行一个指定 Flow。

## 8. 日志与脱敏

每次 pytest 执行会在 `logs/YYYY-MM-DD/` 生成独立 UTF-8 日志文件，记录请求、
响应、HTTP 状态和耗时。首次创建当天目录时，框架会清理超过 7 天的日期日志目录；
非日期目录不会被删除。以下敏感信息会脱敏：

- `auth_token`、refresh token 等 token 字段。
- `Authorization` 请求头。
- 预签名上传 URL 的查询参数。

日志中的敏感值显示为 `***`。新增日志字段时应同步补充脱敏测试。

## 9. 配置校验

YAML 在发送请求前完成校验，常见错误会包含文件名、API ID、Case ID 或 Flow
step ID：

- API ID 重复、必填路由缺失或文件名不一致。
- Case 引用不存在的 API、Case ID 重复或 params 类型错误。
- Flow/Scenario 不同名、步骤 ID 重复或 API 引用不存在。
- API 步骤缺少 Scenario 的完整 params 或 assert。
- V1.2 的 `call`、顶层 Case 数据和 `flow_only` 不再支持。

## 10. V1.2 迁移到 V1.3

V1.3 已完成一次性迁移，不维护两套格式：

1. 从旧 Case 提取路由，创建 `data/apis/<ApiId>.yaml`。
2. 可独立执行的旧 Case 转为 `api + cases[]` 集合。
3. 原 `flow_only` 模板只保留 API 定义，不生成空 Case。
4. Flow 的 `call: Xxx.yaml` 改为 `api: Xxx`。
5. 旧 Case 默认参数与 Scenario 覆盖计算后的最终完整数据写入 Scenario。
6. 自动会话参数、断言和提取规则由框架内部协议维护。

迁移后修改单接口 Case 不会影响 Flow；新增 Flow 接口也不要求先创建单接口 Case。

## 11. 生成 Allure 3 报告

Python 依赖已包含 `allure-pytest`。Allure 3 CLI 使用 npm 用户级目录安装，
不修改项目的 `package.json`：

```bash
npm install -g \
  --prefix /Users/admin/.local/allure-npm \
  allure@3.14.3

export PATH="/Users/admin/.local/allure-npm/bin:$PATH"
allure --version
```

执行全部测试并生成原始结果：

```bash
.venv/bin/python runtest.py \
  --env test \
  -- \
  --alluredir=allure-results \
  --clean-alluredir \
  --allure-no-capture
```

仅执行指定 Flow 时，在 `--env test` 后增加
`--flow AnonymousSessionMediaSearch`。`--allure-no-capture` 用于避免重复附加
stdout、stderr 和日志。

使用 Allure 3 内置 Awesome 报告生成并打开 HTML：

```bash
allure awesome allure-results \
  --output allure-report \
  --group-by parentSuite,suite,feature,story
allure open allure-report
```

`allure-results/` 和 `allure-report/` 都是本地运行产物，不提交到仓库。首次或
希望清空旧结果时使用 `--clean-alluredir`；需要合并多批结果时，后续执行不要
使用该参数。报告附件会脱敏 token 和签名 URL，不保存非 JSON 响应正文或媒体
二进制，但仍不应将结果目录对外公开。

## 12. 报告发布与同步

平台展示的报告统一从 `reports/allure-current` 读取。该指针由发布脚本原子
切换：报告先完整复制到 `reports/allure-reports/<版本>/`，再通过 rename 切换
软链接，切换前旧报告始终可用。

手动发布本地生成的报告（来源记为 `manual`）：

```bash
scripts/publish_allure_report.sh allure-report
```

从 Jenkins 拉取最近一次包含 HTML 归档的已完成构建并发布（来源记为
`jenkins`，凭证通过环境变量传入，不得写入仓库）：

```bash
JENKINS_USER=<用户名> JENKINS_TOKEN=<API令牌> \
  scripts/fetch_jenkins_report.sh
```

可选环境变量：`JENKINS_URL`（默认 http://10.0.30.33:8081）、`JOB_NAME`
（默认 truthy-api-autotest）、`BUILD_NUMBER`（指定构建号，缺省自动选取）。
Jenkins 侧的 HTML 归档由 `Jenkinsfile` post 阶段的
`allure-report-publish/**` 提供。
