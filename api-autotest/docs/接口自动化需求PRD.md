## 1. 目标
1. 普通单接口：增加一条接口配置和一份用例 YAML。
2. 标准多接口流程：通过 Flow YAML 或复杂流程使用`pytest-yaml`（主要指`pytest-yaml-yoyo`）实现编排调用、提取、断言和等待。
3. 特殊流程：只有 COS PUT、异步复杂状态机、外部夹具等场景才编写 Python 插件。
4. 所有 Gateway 业务调用统一执行 `POST {gateway_base_url}/gateway/invoke`。
5. 真正调用哪个业务方法，只由 `requests[].service_name`、`requests[].method_name` 决定。

## 2. 已确认的真实协议

### 2.1 Transport 边界

| Transport | 地址/来源                                              | HTTP 方法 | 用途             |
| --------- | -------------------------------------------------- | ------- | -------------- |
| Gateway   | test：`http://gateway.spark-jam.top/gateway/invoke` | `POST`  | 除图片二进制外的全部业务接口 |
| COS PUT   | `PrepareMediaUpload` 响应中的预签名 `upload_url`          | `PUT`   | 图片二进制上传        |

### 已知请求接口的service_name与method_name

| service\_name                                | method\_name               | 说明                |
| -------------------------------------------- | -------------------------- | ----------------- |
| `tool.identity.IdentityService`              | `CreateAnonymousSession`   | 创建匿名登录态           |
| `tool.identity.IdentityService`              | `RefreshSession`           | 刷新登录态             |
| `tool.identity.IdentityService`              | `GetMe`                    | 获取当前用户            |
| `tool.subscription.SubscriptionService`      | `ListSubscriptionProducts` | 查询可展示订阅商品         |
| `tool.subscription.SubscriptionService`      | `GetSubscriptionStatus`    | 查询订阅状态            |
| `tool.subscription.SubscriptionService`      | `GetEntitlement`           | 查询搜索权益            |
| `tool.people_insight.MediaService`           | `GetMediaUploadConfig`     | 获取图片上传规则          |
| `tool.people_insight.MediaService`           | `PrepareMediaUpload`       | 获取 COS 上传 URL     |
| `tool.people_insight.MediaService`           | `CompleteMediaUpload`      | 确认图片上传完成          |
| `tool.people_insight.SearchService`          | `CreateIntentTask`         | 创建并启动 3\.0 线索搜索任务 |
| `tool.people_insight.SearchService`          | `RefineTask`               | 基于原报告和补充条件创建二次搜索  |
| `tool.people_insight.SearchService`          | `GetTask`                  | 轮询任务状态            |
| `tool.people_insight.SearchService`          | `ListTaskCandidates`       | 候选集列表             |
| `tool.people_insight.SearchService`          | `GetTaskCandidateDetail`   | 单个候选详情            |
| `tool.people_insight.SearchService`          | `ListSearchHistory`        | 搜索历史              |
| `tool.people_insight.ReportService`          | `AddReportPhotos`          | 报告页补充图片并创建刷新任务    |
| `tool.people_insight.ReportService`          | `SubmitFeedback`           | 提交报告结果反馈          |
| `tool.people_insight.HomeService`            | `GetHomeContent`           | 首页检索案例和用户故事       |
| `tool.people_insight.HomeService`            | `GetSampleCaseDetail`      | 首页样例详情，按订阅态上锁     |
| `tool.people_insight.ProfileFeedbackService` | `SubmitProfileFeedback`    | 个人中心/通用产品反馈       |


 


### 2.2 Gateway 最小请求结构

根据本次补充说明，默认请求根对象由 `comm` 和 `requests` 组成：

```json
{

"comm": {

"auth_token": "${AUTH_TOKEN}",

"user_id": "${USER_ID}",

"device_id": "${DEVICE_ID}",

"client_request_id": "crid_1784087090369799",

"platform": "ios",

"app_version": "1.0.3",

"locale": "zh-Hans-CN",

"country": "CN",

"timezone": "UTC+08:00"

},

"requests": [

{

"id": "req_0",

"service_name": "tool.people_insight.SearchService",

"method_name": "GetTask",

"params": {

"task_id": "task_example"

}

}

]

}
```

说明：

- 文档示例只使用占位符，不保存真实 token。
- `auth_token` 是用户登录后获取的 token。
- `comm` 是整个 Gateway envelope 共享的客户端上下文。
- `requests` 是业务子请求数组；每项通过 `service_name + method_name` 路由。
- `params` 只包含该业务方法自己的参数。
- `user_id` 写入 `comm`，用户身份由 `auth_token` + `user_id` + `device_id` 解析。
- 空值字段默认不序列化，避免发送未确认字段。
- 当前接口文档中存在可选 `execution` 对象，但本次用户确认的默认请求结构不包含它。因此目标实现默认只发送 `comm + requests`；只有协议再次确认后才允许通过环境配置显式开启 `execution`。

### 2.3 Gateway 响应和双层结果

目标框架继续按两层结果处理：

```text
HTTP 层
  └── HTTP 2xx：只表示 Gateway 收到并返回 envelope

Gateway 顶层
  ├── code
  ├── message
  ├── request_id
  ├── trace_id
  └── responses[]
        ├── id                # 与 requests[].id 对应
        ├── code
        ├── success
        ├── business_error_code
        ├── http_status
        ├── message
        └── data
```



业务成功必须同时满足：

1. HTTP 状态为 2xx；
2. Gateway 顶层结构有效；
3. 目标 `responses[].id` 能与子请求 ID 对应；
4. 当子响应成功时 `success == true` 且 `code == 0`，"message": "ok"；
5. 当子响应失败时，`success == false` 且 `code != 0`；这时才会有 `business_error_code` 与 `http_status`，`message` 为错误描述。
6. 用例配置的业务字段和 Schema 断言通过。

响应成功例子：
response:
{
  "code": 0,
  "message": "ok",
  "request_id": "gw_req_example_success",
  "trace_id": "trace_example_success",
  "responses": [
    {
      "id": "req_0",
      "success": true,
      "code": 0,
      "message": "ok",
      "data": {
        "acquisition_summary": {
          "channel": "Organic",
          "channel_code": "Organic",
          "report_time": 1783678334087,
          "source": "Organic",
          "sub_channel": "",
          "sub_channel_code": ""
        },
        "consent_policy_version": "2026-06-08",
        "create_time": 1783156880851,
        "device_id": "${DEVICE_ID}",
        "profile_summary": {
          "bucket": "bucket_10",
          "country": "CN",
          "last_app_version": "1.0.3",
          "last_ip": "43.173.72.75",
          "last_platform": "ios",
          "last_seen_time": 1784087005840,
          "recharge_cnt": 0,
          "recharge_total_micros": 0
        },
        "subscription_summary": {
          "expires_time": 1784025932000,
          "plan_code": "basic",
          "product_code": "people_insight",
          "subscription_status": "expired"
        },
        "user_id": "${USER_ID}",
        "user_type": "anonymous"
      }
    }
  ]
}

响应失败的例子：
response:
{
  "code": 0,
  "message": "ok",
  "request_id": "gw_req_example_failure",
  "trace_id": "trace_example_failure",
  "responses": [
    {
      "id": "req_0",
      "success": false,
      "code": 300002,
      "message": "unauthenticated",
      "business_error_code": "UNAUTHENTICATED",
      "http_status": 401,
      "data": {
        "error_code": "UNAUTHENTICATED"
      }
    }
  ]
}
## 3. 目标实现

| 领域     | 目标实现                                                          |
| ------ | ------------------------------------------------------------- |
| 接口管理   | `data/Apidata/*.yaml` 统一注册                                    |
| 请求地址   | 环境配置固定 Gateway 地址；                                            |
| 请求信封   | 默认 `comm + requests`；同时支持单请求和批量请求                             |
| `comm` | 使用配置 Schema 管理固定字段、动态字段和可选字段                                  |
| 接口参数   | 接口 Schema + Case 数据分层管理                                       |
| 用例数据   | `data/casesdata` 为普通用例数据唯一入口                                  |
| 多接口流程  | 标准流程使用 Flow YAML，复杂流程使用`pytest-yaml`（主要指`pytest-yaml-yoyo`）实现 |
| 通用调用方式 |                                                               |
| 扩展成本   | 普通接口只增加 YAML，不修改框架代码                                          |
