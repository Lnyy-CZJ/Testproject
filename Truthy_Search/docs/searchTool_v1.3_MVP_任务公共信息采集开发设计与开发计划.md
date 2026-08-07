# searchTool v1.3 MVP 任务公共信息采集开发设计与开发计划

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | searchTool v1.3 MVP 任务公共信息采集开发设计与开发计划 |
| 文档版本 | v1.0 |
| 编写日期 | 2026-08-05 |
| 需求依据 | `docs/searchTool_v1.3_MVP_任务公共信息采集PRD.md` v1.3 |
| 当前系统 | 已集成到测试开发平台的 searchTool v1.3 MVP |
| 数据库 | 继续使用现有 SQLite Schema，不新增业务表 |
| 核心原则 | 复用平台 Run/Query/Raw 架构、顺序请求、辅助接口失败不阻断检索、字段口径可后补 |

## 2. 开发目标

### 2.1 任务目标

在不重构现有测试开发平台的前提下完成：

1. 使用 Admin Login 自动获取 `session_token`；
2. Token 有效期内跨 Query 复用，距离过期不足 1 小时时自动重新登录；
3. GetTask 进入终态后等待 1 秒；
4. 依次请求 `GetSearchTaskDebug` 和 `GetProviderCostSummary`；
5. `SUCCEEDED`、`NO_RESULT`、失败终态和缓存命中任务均采集公共信息；
6. 将完整脱敏响应写入现有 Raw 和人物级链路日志；
7. 将已确认公共字段写入 `task_fields` 和 SQLite；
8. 未确认字段保留 Raw 和来源状态，后续只补映射，不重做采集流程；
9. 保持 Web、CLI、历史导入、无成本重处理和报告兼容。

### 2.2 成功标准

- 原检索链路仍为顺序执行，不引入并发请求；
- 新链路为：

```text
Create
  → GetTask 轮询到终态
  → 等待 1 秒
  → 确保 Admin Session 有效
  → GetSearchTaskDebug
  → GetProviderCostSummary
  → SUCCEEDED 时 List + 全部 Detail
  → 保存结果
```

- 一个 Run 内的多个 Query 共用同一个有效 Admin Session；
- Admin 登录、Debug 或 Cost 失败不阻断 List 和 Candidate Detail；
- `NO_RESULT` 和失败终态的公共信息仍可入库；
- 每个输入人物生成一份完整链路 `.log`；
- 日志和 Raw 均不包含密码、Token、Cookie 或认证 Header；
- Docker/测试开发平台重启后，SQLite、Raw、报告和 `log/` 均能持久保存；
- 自动化测试覆盖正常、过期刷新、失败降级、无结果、失败终态、缓存命中和日志防覆盖。

### 2.3 本次不实现

- 新建独立微服务；
- 新建第二套数据库；
- 新增 Admin 管理页面；
- 在 Web 页面展示完整 Debug/Cost Raw；
- 多币种换汇；
- Provider 调用级分析表；
- 历史 Run 反向补采 Admin 数据；
- 修改身份归类、字段准确率和完整度算法；
- 将未确认的成本单位或字段含义猜测成正式值。

## 3. 现有平台基线

### 3.1 当前运行结构

当前 searchTool 已经作为测试开发平台中的一个功能运行：

```text
测试开发平台
  └─ searchTool Web（Flask，平台路径 /truthy-search）
       ├─ RunCoordinator：单线程后台顺序执行 Run
       ├─ AnalysisService：Run/Query/Candidate/Raw 入库
       ├─ SearchClient：原检索 RPC 调用
       ├─ SQLite：运行、候选人、处理、指标和报告
       └─ data/raw、data/reports：持久化文件
```

本次不改变：

- 平台入口和 `SEARCH_WEB_BASE_PATH`；
- 5002 容器端口；
- `RunCoordinator` 单线程执行模型；
- Evaluation → Dataset → Run → Process → Report 业务结构；
- 现有 SQLite、Raw、Report 快照和 Excel 导出；
- Docker 中使用 `/run/secrets/searchtool.env` 加载配置的方式。

### 3.2 可复用能力

| 现有能力 | 本次复用方式 |
| --- | --- |
| `SearchClient` | 保留原 Search API 请求，不改变 Create/Get/List/Detail 契约 |
| `raw_callback` | Debug、Cost 和脱敏 Login 摘要进入同一 Raw 流 |
| `build_raw_record()` | 统一请求顺序、阶段、Query、Task、Candidate 标识 |
| `sanitize_raw()` | 扩展敏感字段清单后同时供 Raw 和 `.log` 使用 |
| `run_queries` | 复用成本、PDL、耗时列及 `public_fields_json` |
| `raw_records` | 直接存储 `AdminLogin`、Debug、Cost 阶段，无需改表 |
| `RunCoordinator` | 一个 Run 使用一个 Client，使 Token 可跨 Query 复用 |
| `AnalysisService.execute_run()` | 继续负责逐 Query 入库、失败隔离和进度更新 |

## 4. 总体设计

### 4.1 简化组件关系

```text
RunCoordinator
    ↓ 每个 Run 创建一次
SearchClient
    ├─ 原 Search API Session
    └─ AdminClient
          ├─ Login Session 状态
          ├─ GetSearchTaskDebug
          └─ GetProviderCostSummary
    ↓
process_one()
    ├─ RawCallback → SQLite raw_records
    ├─ QueryChainLogger → log/人物日志
    └─ result.task_fields/public_fields → run_queries
```

### 4.2 设计原则

1. **不新增服务**：Admin Client 放在现有 `search_tool.py`；
2. **一个 Run 一个 Session**：利用当前 Web 每个 Run 创建一次 Client 的行为复用 Token；
3. **公共采集独立失败**：Debug、Cost 各自捕获异常，返回状态而不是抛出主链路；
4. **Raw 先行**：字段口径未确认时仍完整保存接口响应；
5. **数据库不迁移**：标准字段写现有列，扩展字段写 `public_fields_json`；
6. **一套事件两种落地**：同一脱敏接口事件同时进入 SQLite Raw 和人物 `.log`；
7. **平台持久化**：Docker 中的 `log/` 必须挂载，不写入临时容器层。

## 5. 配置设计

### 5.1 新增配置

在现有 `.env.example` 和平台 Secret 配置中增加：

```dotenv
SEARCH_ADMIN_ENABLED=true
SEARCH_ADMIN_LOGIN_API_URL=http://admin-staging.spark-jam.top/admin/invoke
SEARCH_ADMIN_API_URL=http://admin-staging.spark-jam.top/gateway/invoke
SEARCH_ADMIN_HTTP_HEADERS_JSON={"Content-Type":"application/json"}
SEARCH_ADMIN_USERNAME=
SEARCH_ADMIN_PASSWORD=
SEARCH_ADMIN_REASON=searchTool 测试数据采集
SEARCH_ADMIN_DEBUG_SERVICE=worker
SEARCH_ADMIN_COST_LIMIT=100

SEARCH_QUERY_LOG_ENABLED=true
SEARCH_QUERY_LOG_DIR=log
```

### 5.2 Config 结构

继续使用现有 `Config.from_env()`，新增可选字段，不创建第二套配置加载器：

```text
admin_enabled
admin_login_api_url
admin_api_url
admin_headers
admin_username
admin_password
admin_reason
admin_debug_service
admin_cost_limit
query_log_enabled
query_log_dir
```

### 5.3 校验规则

1. `SEARCH_ADMIN_ENABLED=false` 时不要求 Admin 账号；
2. 启用时 Login URL、Admin URL、Username、Password 必填；
3. 两份 Headers JSON 都必须是字符串键值对象；
4. `SEARCH_ADMIN_COST_LIMIT` 必须是正整数；
5. 日志目录只允许项目受控路径；
6. 配置报错不得输出密码；
7. Web 后台启动 Run 时读取平台挂载的 Secret，不把账号写入数据库。

## 6. Admin Session 设计

### 6.1 AdminClient 状态

在 `search_tool.py` 内新增轻量 `AdminClient`，不新增项目文件。只保存运行时状态：

```text
session_token
expire_time
operator_id
operator_name
session（requests.Session）
```

Token、密码不得作为 dataclass 的可打印内容，不实现包含秘密值的 `repr`。

### 6.2 登录流程

```text
ensure_session()
  ├─ 没有 Token → Login
  ├─ expire_time - 当前时间 < 1 小时 → Login
  └─ 否则复用现有 Token
```

Login 成功必须满足：

- 顶层 `code == 0`；
- `responses[0].success == true`；
- `session_token` 非空；
- `expire_time` 可解析；
- Operator ID、Name 非空。

登录后只在内存更新状态，不修改 `.env`，不写 SQLite。

### 6.3 认证失败重试

Debug/Cost 返回明确认证失败时：

```text
清空旧 Session
  → Login 一次
  → 重放原请求一次
  → 仍失败则 AUTH_FAILED
```

不允许递归重试或无限循环。网络失败和业务认证失败分别记录。

### 6.4 Login Raw

Login 只记录以下脱敏摘要：

```json
{
  "stage": "AdminLogin",
  "status": "SUCCESS",
  "expire_time": "2026-08-05T15:01:37.804Z",
  "operator_id": "***",
  "token_saved": false
}
```

请求密码、响应 Token 和完整 Operator 权限不写人物日志；权限信息如需排障，只进入脱敏 Raw。

## 7. 采集流程改造

### 7.1 主流程

在 `process_one()` 中，GetTask 退出轮询后增加一次公共信息采集：

```text
GetTask 终态
  → sleep_fn(1.0)
  → collect_public_info(task_id)
       ├─ AdminLogin（需要时）
       ├─ GetSearchTaskDebug
       └─ GetProviderCostSummary
  → 根据原 GetTask 状态继续原流程
```

使用已注入的 `sleep_fn`，不直接写死 `time.sleep(1)`，便于测试精确验证等待顺序。

### 7.2 状态分支

| 状态类型 | 公共接口 | 原后续流程 |
| --- | --- | --- |
| `QUEUED`、`SEARCHING` | 不请求 | 继续轮询 |
| `SUCCEEDED` | 等待 1 秒后 Debug、Cost | List → 全部 Detail |
| `NO_RESULT` | 等待 1 秒后 Debug、Cost | 直接生成无候选人结果 |
| 已确认失败终态 | 等待 1 秒后 Debug、Cost | 保持 Query 失败 |
| 缓存命中终态 | 等待 1 秒后 Debug、Cost | 按实际终态继续，并保存 `cache_hit` |
| Create 失败 | 无 task_id，不请求 | 保持失败 |
| 轮询超时 | 未进入终态，不写正式公共信息 | 保持失败 |

失败终态的具体枚举集中放在一个常量集合中，不把判断散落在流程代码。后端补充枚举时只改契约常量和测试夹具。

### 7.3 公共接口相互隔离

`collect_public_info()` 返回一个结构对象，不因单接口错误中断：

```json
{
  "public_info_status": "PARTIAL",
  "debug_status": "SUCCESS",
  "cost_status": "FAILED",
  "debug_body": {},
  "cost_body": null,
  "warnings": ["GetProviderCostSummary: ..."]
}
```

规则：

1. Debug 失败仍请求 Cost；
2. Cost 失败仍继续 List/Detail；
3. 两者失败只将公共信息标记为 `FAILED`；
4. Login 失败时两个接口均记 `AUTH_FAILED`，主 Search 流程继续；
5. Cost 空响应允许一次短重试；首次调用前的统一 1 秒等待不重复执行。

### 7.4 失败终态数据保存

现有 `FlowError` 只携带 `raw_records`。为保存失败终态已采集的公共信息，最小扩展为：

```text
FlowError.public_fields
FlowError.task_fields
```

`AnalysisService._persist_execution_failure()` 同步保存：

- `task_id`；
- 公共信息状态；
- 已确认的成本/耗时字段；
- Debug/Cost Raw；
- 原 Query 失败状态与错误。

公共接口成功不能把失败 Query 改成成功。

## 8. Admin 接口实现

### 8.1 Login

请求：

```text
POST SEARCH_ADMIN_LOGIN_API_URL
method_name = Login
params.username/password = .env
```

响应只在内存保留 Token，解析 `expire_time` 为带时区时间。

### 8.2 GetSearchTaskDebug

请求参数：

```text
session_token：当前内存 Token
operator_id/operator_name：Login 响应
reason：配置
task_id：当前 Query
service：worker
```

保存完整脱敏响应，首版提取已明确的任务时间、`cache_hit` 和 diagnosis 摘要。

### 8.3 GetProviderCostSummary

请求参数：

```text
session_token：当前内存 Token
operator_id/operator_name：Login 响应
reason：配置
task_id：当前 Query
limit：配置，默认 100
```

保存 `cost_summary` 完整脱敏响应。未确认的单位、Provider 分类和多币种规则只保存原值，不推算正式金额。

### 8.4 HTTP 行为

1. 两个 Admin 地址与原 `SEARCH_API_URL` 分离；
2. 复用 `requests.Session`；
3. 超时继续使用现有 `HTTP_TIMEOUT_SECONDS`；
4. 每次请求生成唯一 Request/Trace ID；
5. HTTP、JSON、顶层 code、`responses[0]` 分层校验；
6. 错误对象不包含密码和 Token。

## 9. 公共字段映射

### 9.1 输出结构

结果继续使用现有结构，不增加平行结果格式：

```json
{
  "task_fields": {
    "llm_cost": null,
    "third_party_cost": null,
    "total_cost": null,
    "pdl_called": null,
    "search_duration_ms": null,
    "public_info_status": "COMPLETE",
    "cache_hit": false,
    "debug_collection_status": "SUCCESS",
    "cost_collection_status": "SUCCESS"
  },
  "raw": {
    "get_search_task_debug": {},
    "get_provider_cost_summary": {}
  }
}
```

### 9.2 字段处理策略

字段分两组处理：

#### A. 已确认结构字段

可以立即提取并保存：

- 公共采集状态；
- Debug/Cost 请求状态；
- `cache_hit`；
- Debug 原始时间；
- Provider 调用计数；
- Fallback 和失败计数；
- Cost 原始微单位和币种汇总；
- `pdl_called` 的原始判断证据。

#### B. 已确认业务口径字段

以下字段从已入库 Admin Raw 提取，并写入现有正式标量：

- `llm_cost`；
- `third_party_cost`；
- `total_cost`；
- `cost_currency`；
- `pdl_called`；
- `search_duration_ms`。

映射规则：

- 三项 USD 成本由 microunit 除以 1,000,000；
- LLM 与第三方按已确认 Provider 分类分别累计；
- 总成本优先取当前 task_id 的 by_search USD 项，回退 totals USD 项；
- PDL 读取 diagnosis.pdl_called，耗时由 finish_time 减 start_time；
- 缺失值保持 `null`，真实零值保留 `0`，Raw 不修改。

### 9.3 来源优先级

字段口径确认后使用：

```text
Admin 正式映射值
  > 原 GetTask 已存在的兼容值
  > null
```

同时保存字段来源，避免无法判断成本来自哪个接口。

## 10. SQLite 与 Raw 设计

### 10.1 不升级 Schema

现有 `run_queries` 已有：

- `llm_cost`；
- `third_party_cost`；
- `total_cost`；
- `pdl_called`；
- `search_duration_ms`；
- `public_fields_json`。

现有 `raw_records` 已支持任意 `stage + payload_json`。本期不增加列、不增加表、不执行迁移。

### 10.2 Raw 阶段

新增阶段名：

```text
AdminLogin
GetSearchTaskDebug
GetProviderCostSummary
```

使用同一 `run_id + query_id + task_id` 关联当前 Query。Admin Login 没有 Candidate ID。

### 10.3 public_fields_json

建议保存：

```json
{
  "public_info_status": "COMPLETE",
  "debug_collection_status": "SUCCESS",
  "cost_collection_status": "SUCCESS",
  "cache_hit": false,
  "queue_duration_ms": null,
  "end_to_end_duration_ms": null,
  "cost_complete": null,
  "cost_totals_by_currency": {},
  "provider_request_count": 0,
  "agent_tool_call_count": 0,
  "fallback_used": false,
  "fallback_reason": null,
  "warnings": []
}
```

`null`、`0` 和 `false` 保持不同含义，不互相替换。

## 11. 人物级链路日志

### 11.1 实现位置

在 `search_tool.py` 中增加轻量 `QueryChainLogger`，复用现有 Raw 事件，不新增日志服务。

人物姓名从输入中提取：

```text
clues[].type == FULL_NAME
  → clues[].full_name_query.full_name
  → 为空时回退 input_id
```

### 11.2 文件路径

本地默认：

```text
/Users/admin/Testproject/Truthy_Search/log/YYYY-MM-DD_人物姓名.log
```

容器默认：

```text
/app/log/YYYY-MM-DD_人物姓名.log
```

平台部署必须将 `/app/log` 挂载到持久化目录，否则容器重建会丢失日志。

### 11.3 命名和防覆盖

```text
首次：YYYY-MM-DD_人物姓名.log
冲突：YYYY-MM-DD_人物姓名_input-id.log
再次冲突：YYYY-MM-DD_人物姓名_input-id_HHmmss.log
```

姓名必须清理路径分隔符、控制字符和路径穿越内容。

### 11.4 日志内容

每行一个 JSON 对象，按实际发生顺序立即追加：

- Query Start；
- Create；
- 每次 GetTask；
- 脱敏 Login；
- Debug；
- Cost；
- List；
- 每个 Candidate Detail；
- Query End。

每条包含：

```text
timestamp、sequence_no、run_id、input_id、person_name、task_id、candidate_id、
stage、attempt、duration_ms、http_status、business_success、request、response、error
```

### 11.5 写入方式

1. `process_one()` 开始时创建日志文件并写 Query Start；
2. 每次 Raw 事件产生后同步追加日志；
3. 每次写入后 flush，保证中途失败仍可查看；
4. `finally` 中写 Query End；
5. 日志写入失败记录警告，不丢弃已产生的 SQLite Raw；
6. 不在内存中累计整份大日志，避免 100 Query、多个 Detail 时内存增长。

### 11.6 脱敏

扩展 `sanitize_raw()` 敏感键：

```text
password
session_token
auth_token
authorization
cookie / set-cookie
headers / http_headers
device_id / user_id
```

现有 Raw 对敏感键的行为保持兼容。人物日志只消费脱敏后的事件，不直接消费 HTTP 原始对象。

## 12. 平台集成设计

### 12.1 Web 执行

`RunCoordinator._default_client()` 仍只创建一个顶层 Client：

```text
一个 Run
  → 一个 SearchClient
  → 一个 AdminClient
  → 一个可复用 Admin Session
```

不增加线程，不允许 Query 并发。单条 Query 重跑会创建新 Client 并重新 Login，符合当前重跑隔离规则。

### 12.2 平台路径

保持：

- `SEARCH_WEB_BASE_PATH=/truthy-search`；
- `PLATFORM_HOME_URL=/`；
- 容器端口 5002；
- 原平台反向代理和导航入口。

本需求没有新增 Web 路由，因此不修改平台导航和代理规则。

### 12.3 Docker 持久化

平台部署配置需要增加：

```text
宿主机持久目录/卷  →  /app/log
平台 Secret          →  /run/secrets/searchtool.env
```

必须保证：

1. `/app/log` 对容器运行用户可写；
2. `.env` 仍只读挂载；
3. 密码不写 Dockerfile 或镜像；
4. 容器重启后旧日志仍存在；
5. 新版本继续使用当前 SQLite/Data 挂载，不迁移数据。

### 12.4 平台页面表现

本期不新增日志查看页面。现有运行详情继续通过 `current_stage` 显示：

```text
GetTask
PublicInfoDelay
AdminLogin
GetSearchTaskDebug
GetProviderCostSummary
ListTaskCandidates
GetTaskCandidateDetail
```

公共接口失败只显示“公共信息采集部分失败”，不将已成功检索的 Run 标红为执行失败。

## 13. 主要修改文件

| 文件 | 修改内容 |
| --- | --- |
| `search_tool.py` | Admin 配置、AdminClient、Session 更新、终态等待、Debug/Cost、字段标准化、人物链路日志、脱敏扩展 |
| `analysis_service.py` | 成功/失败 Query 的公共字段与新 Raw 阶段入库、平台进度状态、日志路径传递 |
| `web_app.py` | 保持一个 Run 一个 Client；必要时传入平台日志目录，不新增页面 |
| `.env.example` | Admin Login、Admin API 和日志配置示例，秘密字段留空 |
| `README.md` | 平台配置、Docker 日志挂载、Token 生命周期、排障说明 |
| `tests/test_search_tool.py` | Login、Token 复用/更新、终态等待、Debug/Cost、日志和脱敏测试 |
| `tests/test_analysis_service.py` | 公共字段、失败终态、Raw 和 SQLite 入库测试 |
| `tests/test_web_app.py` | 平台 Run 执行兼容、进度和配置错误测试 |

原则上不修改：

- `analysis_store.py` Schema；
- 字段配置、Processing、Metrics 和 Report 核心算法；
- 前端模板和 CSS；
- Dockerfile（没有新增运行文件或依赖时无需修改）。

## 14. 核心测试设计

### 14.1 Admin Session

1. 首次 Debug 前触发一次 Login；
2. 多个 Query 在有效期内只登录一次；
3. 距离过期 59 分钟时重新登录；
4. 距离过期超过 1 小时时复用；
5. 服务端提前返回认证失败时重新 Login 并重放一次；
6. 重放仍失败时停止认证重试；
7. 密码和 Token 不出现在异常字符串、Raw、日志。

### 14.2 流程顺序

断言调用顺序：

```text
Create
GetTask...
sleep(1.0)
AdminLogin（如果需要）
Debug
Cost
List
Detail...
```

覆盖 `SUCCEEDED`、`NO_RESULT`、失败终态和缓存命中。

### 14.3 降级

- Debug 失败、Cost 成功；
- Debug 成功、Cost 失败；
- Login 失败；
- Cost 空响应重试；
- 两个 Admin 接口都失败；
- 以上场景中 List/Detail 或 Query 原失败状态均符合原规则。

### 14.4 数据保存

- 新 Raw 阶段进入 `raw_records`；
- 成功 Query 的标准字段和 `public_fields_json` 正确；
- 失败终态也保存公共字段和 Raw；
- 未确认字段保持 `null`；
- 零成本不被变成 `null`；
- 历史结果导入不要求存在新字段。

### 14.5 人物日志

- 日志名称提取 FULL_NAME；
- 中文、空格和特殊字符安全处理；
- 同名不覆盖；
- 每次 GetTask 和全部 Detail 都存在；
- 中途失败仍有 Query End；
- 大响应逐行写入，不等待 Run 完成；
- 密码、Token、Cookie、Header 不存在。

### 14.6 平台回归

- Web 启动执行；
- 单 Query 重跑；
- Run 中断恢复；
- 原历史导入；
- 无成本重处理不调用任何 Admin 接口；
- 原报告和 Excel 可继续生成；
- `/truthy-search` 平台路径和 5002 健康检查正常。

## 15. 开发计划

本次按四个阶段完成，避免拆分过细。

### 阶段 0：契约冻结与测试准备

#### 开发内容

1. 将三个 RTF 接口样例整理为脱敏测试夹具；
2. 固定 Login、Debug、Cost 的请求结构和响应校验；
3. 固定终态后等待 1 秒的调用顺序；
4. 固定 `NO_RESULT`、失败终态、缓存命中均采集公共信息；
5. 确认失败终态实际枚举并集中登记；
6. 编写当前代码必然失败的新测试，先复现缺失能力。

#### 交付结果

- 接口契约测试；
- 顺序测试；
- Token 生命周期测试；
- 日志格式与脱敏测试。

#### 完成标准

- 不访问真实接口即可稳定复现待开发功能；
- 样例中不包含真实密码和 Token；
- 未确认字段明确标记为 `NOT_MAPPED`。

### 阶段 1：Admin 会话与公共接口

#### 开发内容

1. 扩展 `Config` 和 `.env.example`；
2. 实现 Admin Login；
3. 实现 Token 缓存、1 小时提前更新和认证失败重放；
4. 实现 Debug、Cost 请求；
5. GetTask 终态后等待 1 秒并接入公共信息采集；
6. 保证单接口失败不阻断主流程；
7. 将 Login、Debug、Cost 转成统一脱敏 Raw 事件。

#### 完成标准

- 一个 Run 内 Token 可复用；
- 调用顺序符合 PRD；
- 四类终态场景均能采集；
- 原 Create/Get/List/Detail 测试无回归。

### 阶段 2：平台落库与人物链路日志

#### 开发内容

1. 标准化已确认公共字段；
2. 扩展成功和失败 Query 入库；
3. 将额外字段写入 `public_fields_json`；
4. 实现 `QueryChainLogger`；
5. 从 FULL_NAME 输入提取人物姓名；
6. 实现日志目录、命名、防覆盖、逐行写入和 Query End；
7. 扩展密码、Session Token 等脱敏；
8. 验证 Raw 与人物日志内容一致。

#### 完成标准

- SQLite 无 Schema 迁移；
- `NO_RESULT` 和失败终态也有公共 Raw；
- 每个输入人物有一份完整 `.log`；
- 日志写入失败有明确告警且不破坏 Raw。

### 阶段 3：测试开发平台集成验收与文档

#### 开发内容

1. 更新平台 Secret 配置；
2. 为 `/app/log` 增加持久化挂载；
3. 构建 Docker 镜像并在现有 searchTool 服务中替换；
4. 验证 `/truthy-search`、5002 和平台首页入口；
5. 使用小规模真实 Dataset 验证完整链路；
6. 验证容器重启后数据库、Raw 和日志保留；
7. 运行 searchTool、AnalysisService、Web 全量回归测试；
8. 更新 README 的配置、日志位置和故障排查。

#### 完成标准

- 不新增平台服务和端口；
- 原平台入口正常；
- 真实 Run 可看到 Debug/Cost Raw 和结构化公共字段；
- `/app/log` 可持久化；
- Admin 失败不影响原检索结果；
- 全量自动化测试通过。

## 16. 实施顺序与依赖

```text
阶段 0 契约测试
    ↓
阶段 1 Admin 会话与请求
    ↓
阶段 2 数据落库与日志
    ↓
阶段 3 平台部署与验收
```

依赖关系：

- 字段业务口径不阻塞阶段 0～2 的 Raw 采集；
- 失败终态枚举需要在阶段 0 登记，避免把未知状态误判为终态；
- 平台日志挂载必须在阶段 3 部署前完成；
- 成本单位确认后只补字段映射和报告展示，不重新请求历史接口。

## 17. 风险与处理

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| Token 过期 | Debug/Cost 失败 | 1 小时提前更新，认证失败后登录并重放一次 |
| Admin 接口延迟 | 成本暂未写入 | GetTask 终态后统一等待 1 秒，空响应短重试一次 |
| Admin 接口不可用 | 公共字段缺失 | 标记 PARTIAL/FAILED，继续原检索链路 |
| 字段口径未确认 | 成本误算 | 标准字段保持 null，Raw 完整保存 |
| 日志过大 | 占用磁盘 | 逐行写入、不重复嵌套；日志归档策略后续规划 |
| 容器日志未挂载 | 重启丢失 | 平台部署必须挂载 `/app/log` |
| 同名人物覆盖 | 丢失历史日志 | 文件存在时追加 input_id 和时间 |
| 敏感信息泄露 | 安全风险 | HTTP 响应进入 Raw/日志前统一脱敏并做搜索验收 |
| 失败终态未知 | 错误分支 | 集中终态常量，未登记状态继续按未知状态处理 |

## 18. 回滚方案

1. 设置 `SEARCH_ADMIN_ENABLED=false`，立即关闭 Login、Debug 和 Cost；
2. 设置 `SEARCH_QUERY_LOG_ENABLED=false`，关闭独立人物日志；
3. 原 Search API、Run、Raw、SQLite 和报告仍可运行；
4. 本期不改数据库 Schema，因此无需数据库回滚；
5. 已生成的 Raw 和日志保留，不删除用户数据；
6. 平台可回滚到上一 Docker 镜像，现有数据库继续兼容。

## 19. 最终验收清单

- [ ] 终态后确实等待 1 秒；
- [ ] `SUCCEEDED`、`NO_RESULT`、失败终态、缓存命中均请求 Debug 和 Cost；
- [ ] Debug 在 Cost 之前；
- [ ] Token 距过期不足 1 小时自动更新；
- [ ] 一个 Run 内有效 Token 不重复登录；
- [ ] Admin 失败不阻断 List/Detail；
- [ ] 标准字段、`public_fields_json` 和 Raw 来源一致；
- [ ] 未确认字段不猜测、不填 0；
- [ ] 每个输入人物生成独立完整日志；
- [ ] 日志包含全部 GetTask 和全部 Candidate Detail；
- [ ] 同日同名文件不覆盖；
- [ ] 密码和 Token 不出现在任何落盘内容；
- [ ] SQLite 无 Schema 迁移；
- [ ] 无成本重处理不调用新接口；
- [ ] Docker 日志目录持久挂载；
- [ ] `/truthy-search` 和 5002 保持正常；
- [ ] 自动化测试和真实小批量验收通过。
