# Gateway 接口自动化 MVP PRD

## 1. 背景与目标

Gateway 业务在传输层均为 HTTP 请求：测试环境的地址固定，变化的是请求信封中的业务路由和参数。本版本只验证框架能以配置驱动的方式，稳定调用 **一个 Gateway 业务接口** 并完成基础断言。

**MVP 目标：**

1. 通过一条命令执行一个 YAML 用例；
2. 向固定的 Gateway 地址发起 `POST /gateway/invoke`；
3. 一个 HTTP 请求只携带一个 `requests[]` 业务子请求；
4. 从 YAML 读取 `service_name`、`method_name`、`params` 和断言；
5. 校验 HTTP 层、Gateway 顶层和目标子响应的成功结果；
6. 测试结果可直接在终端查看，失败时输出请求和响应（敏感字段脱敏）。

## 2. 范围

### 2.1 本版本包含

| 项目      | 约定                                                                              |
| ------- | ------------------------------------------------------------------------------- |
| 调用地址    | 由环境变量 `GATEWAY_BASE_URL` 配置，默认拼接 `/gateway/invoke`                              |
| HTTP 方法 | `POST`                                                                          |
| 请求格式    | JSON，默认仅发送 `comm` 和含一个元素的 `requests`                                            |
| 接口路由    | 每个用例配置 `service_name` 和 `method_name`                                           |
| 参数      | 每个用例配置该方法的 `params`                                                             |
| 鉴权      | 从环境变量读取 `AUTH_TOKEN`、`USER_ID`、`DEVICE_ID`，不写入仓库                                |
| 断言      | HTTP 状态、Gateway 顶层 `code/message`、子响应 `id/success/code/message`，以及可选的 `data` 字段 |
| 用例数量    | 先提供 1 个可运行的示例用例（建议 `GetMe` 或已确认可稳定调用的方法）                                        |

### 2.2 本版本明确不包含

- 一次请求携带多个 `requests[]` 子请求；
- 登录、刷新 token、变量提取和接口间传参；
- Flow YAML、多接口编排、异步轮询和等待；
- COS PUT、文件上传、Python 插件；
- JSON Schema、数据库校验、性能/并发测试；
- 用例管理平台、报告平台和复杂环境管理；
- 未经协议确认的 `execution` 字段。

以上能力作为后续版本需求，不能阻塞 MVP 上线。

## 3. 协议约定

### 3.1 固定传输层

```text
POST ${GATEWAY_BASE_URL}/gateway/invoke
Content-Type: application/json
```

`GATEWAY_BASE_URL` 示例：`http://gateway.spark-jam.top`。仓库中只能提交示例值，真实地址和凭证由本地环境变量或未提交的 `.env` 提供。

### 3.2 请求体

```json
{
  "comm": {
    "auth_token": "${AUTH_TOKEN}",
    "user_id": "${USER_ID}",
    "device_id": "${DEVICE_ID}",
    "client_request_id": "自动生成的唯一值",
    "platform": "ios",
    "app_version": "1.0.3",
    "locale": "zh-Hans-CN",
    "country": "CN",
    "timezone": "UTC+08:00"
  },
  "requests": [
    {
      "id": "req_0",
      "service_name": "tool.identity.IdentityService",
      "method_name": "GetMe",
      "params": {}
    }
  ]
}
```

规则：

- `client_request_id` 每次执行自动生成，生成规则为“crid_”+毫秒时间戳+随机3个数字；
- `id` 在 MVP 固定为 `req_0`；
- `params` 由用例 YAML 传入，空对象也必须可发送；
- `comm` 中可选字段为空时不序列化；
- 不记录真实 `auth_token`，日志只显示脱敏后的值。

## 4. 用例配置

一个 YAML 文件对应一个可执行的单接口用例。建议结构：

```yaml
name: 获取当前用户
request:
  service_name: tool.identity.IdentityService
  method_name: GetMe
  params: {}
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
    - user_id
```

`data_fields` 表示字段必须存在且值不为空；本期不支持复杂 JSONPath 或完整 Schema。

## 5. 最小技术方案

采用 Python + `pytest` + `requests` + `PyYAML`：

```text
测试用例 YAML
    ↓
通用执行器（读取 YAML、合成 comm、发 HTTP 请求）
    ↓
Gateway /gateway/invoke
    ↓
通用断言器（HTTP + 顶层 + responses[req_0] + data_fields）
```

建议目录：

```text
.
├── config/
│   └── settings.example.yaml       # 非敏感默认 comm 配置
├── data/cases/
│   └── get_me.yaml                 # MVP 示例用例
├── src/
│   └── gateway_client.py            # 请求构造、发送和脱敏日志
├── tests/
│   └── test_gateway_case.py         # 参数化加载并执行 YAML
├── requirements.txt
├── .env.example                    # 仅变量名与示例值
└── README.md                        # 安装、配置、执行方式
```

唯一执行入口：

```bash
pytest -q
```

## 6. 成功与失败判定

默认成功条件必须全部满足：

1. HTTP 状态码为用例配置值（通常 `200`）；
2. 响应为 JSON 且包含 `code`、`message`、`responses`；
3. Gateway 顶层 `code == 0`、`message == "ok"`；
4. `responses` 中存在 `id == "req_0"` 的对象；
5. 该对象满足 `success == true`、`code == 0`、`message == "ok"`；
6. YAML 配置的每个 `data_fields` 字段存在且非空。

任一条件不满足即用例失败；失败日志至少包含 HTTP 状态、请求 ID/trace ID（若有）、脱敏请求体和响应体。

## 7. 验收标准

1. 克隆项目、安装依赖、配置三个敏感环境变量后，可执行 `pytest -q`；
2. 示例用例能成功调用一个真实 Gateway 方法；
3. 修改 YAML 中的 `method_name` 或断言值后，测试能明确失败并定位原因；
4. 源码、示例 YAML 和终端输出不包含完整 token；
5. 新增另一个普通单接口时，只需新增/复制 YAML，不修改通用执行器。

## 8. 后续迭代顺序

1. 多个独立单接口 YAML；
2. 环境文件与 CI 注入；
3. 提取变量、串行多接口 Flow；
4. 异步轮询、COS 上传和特殊 Python 扩展。

## 9. 待确认项

在实现前只需确认两件事：

1. MVP 示例接口：优先使用 `GetMe`，若该接口不适合测试，请指定一个有稳定成功响应的接口；
2. `GetMe` 的 `params` 是否确实为空，以及是否还需要必须传递的 `comm` 字段。

确认事项：1、可以优先使用GetMe接口。2、`GetMe` 的 `params` 是为空，comm字段是所有接口必须要传的
