# Gateway 接口自动化 MVP

这是一个基于 Python、pytest、requests 和 PyYAML 的最小接口自动化框架。当前版本只处理固定 Gateway 地址下的单业务子请求，默认执行 `POST /gateway/invoke`。

## 1. 安装依赖

建议使用 Python 3.10 及以上版本和独立虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## 2. 配置环境与会话

根目录 `.env` 保存本地凭证与可复用会话状态，禁止写入 YAML 或提交到仓库：

```bash
AUTH_TOKEN=your_access_token
REFRESH_TOKEN=your_refresh_token
USER_ID=your_user_id
DEVICE_ID=your_device_id
EXPIRES_TIME=milliseconds_since_epoch
REFRESH_EXPIRES_TIME=milliseconds_since_epoch
```

启动时会优先复用未临期的 `AUTH_TOKEN`。access token 距毫秒过期时间不足一天时会调用
`RefreshSession`；刷新失败或 refresh token 已过期时才会调用 `CreateAnonymousSession`。
创建或刷新成功后，`AUTH_TOKEN`、`REFRESH_TOKEN`、`USER_ID` 与两项过期时间会自动更新到
`.env`；`DEVICE_ID` 保持由你维护。终端中显式设置的同名环境变量优先于 `.env`。

## 3. 运行测试

统一通过根目录下的 `runtest.py` 执行：

```bash
# 运行 test 环境全部测试
python3 runtest.py --env test

# 按测试名称或模块关键字筛选
python3 runtest.py --env test --module single_api

# 按 YAML 中的 tags 筛选
python3 runtest.py --env test --tag smoke

# 透传额外 pytest 参数
python3 runtest.py --env test --tag smoke -- -x -vv
```

也可直接运行框架单元测试：

```bash
python3 -m pytest test_cases/test_framework.py -q
```

调试单一接口时，可直接运行通用入口。该命令会在终端实时显示脱敏后的请求数据和响应数据：

```bash
python3 test_cases/test_single_api.py --env test
```

请求日志中的 `auth_token` 和 `Authorization` 会显示为 `***`，不会输出完整凭证。

每次 pytest 执行还会在根目录 `logs/` 生成独立 UTF-8 日志文件。文件同时记录
请求、响应、HTTP 状态和耗时；token、refresh token 与预签名 URL 查询参数会脱敏。

真实上传流程还需设置本地媒体文件路径：

```bash
export MEDIA_FILE='/absolute/path/to/image.jpg'
python3 runtest.py --env test --flow AnonymousSessionMediaSearch
```

未提供媒体文件时仅跳过真实上传流程，框架单元测试和普通单接口测试仍可执行。

## 4. 目录职责

- `config/`：默认运行配置和按环境变化的 Gateway 地址。
- `data/api/`：固定 HTTP 方法、路径和请求头。
- `data/cases/`：单接口的路由、参数、标签和断言。
- `data/flows/`：声明存在响应提取和变量传递的接口执行顺序。
- `data/scenarios/`：保存与 Flow 同名的独立业务输入和步骤期望。
- `data/global/`、`data/scenarios/`、`data/assertions/`：预留的数据层。
- `api/`：Gateway 信封构造和调用入口。
- `utils/custom/`：配置、HTTP、日志和断言工具。
- `utils/third_party/`：未来 Allure、Jenkins、飞书等第三方集成预留层。
- `test_cases/`：pytest 框架测试和真实接口测试。
- `logs/`：每次测试执行生成的请求、响应和异常日志。
- `reports/`：未来测试报告和运行产物目录。

## 5. 新增普通单接口

复制 `data/cases/GetMe.yaml`，修改以下数据即可：

```yaml
name: 用例名称
tags: [smoke]
request:
  service_name: 业务服务名
  method_name: 业务方法名
  params: {}
assert:
  http_status: 200
  gateway: {code: 0, message: ok}
  response: {id: req_0, success: true, code: 0, message: ok}
  data_fields: []
```

`data_fields` 校验 `data` 下的一级字段存在且非空。需要把响应字段交给后续接口时，
可以通过 `extract` 声明以业务 `data` 为根的路径，并在后续请求中使用
`{{变量名}}`。COS 上传由流程使用 `PrepareMediaUpload` 返回的 `upload_url` 和
`upload_headers` 执行二进制 PUT。

## 6. 新增标准多接口流程

在 `data/flows/` 和 `data/scenarios/` 中各增加一个同名 YAML：

```text
data/flows/DemoFlow.yaml
data/scenarios/DemoFlow.yaml
```

Flow 只保存步骤顺序、case 引用、提取、等待和轮询；Scenario 保存初始变量、
步骤参数覆盖与 `data_equals` 场景断言。新增合法配对后不需要修改 Python：

```bash
python3 runtest.py --env test --flow DemoFlow
```

固定等待使用 `wait.seconds`；异步接口使用 `call + until`，其中 `until` 支持
响应 data 路径相等判断、轮询间隔和超时时间。不同 Flow 使用独立运行时上下文。
