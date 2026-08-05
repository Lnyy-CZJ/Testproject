# searchTool v1.3 MVP 任务公共信息采集 PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | searchTool v1.3 MVP 任务公共信息采集 PRD |
| 文档版本 | v1.3 |
| 基于版本 | searchTool v1.3 MVP |
| 编写日期 | 2026-08-05 |
| 需求状态 | 待开发设计 |
| 需求类型 | 采集链路增量优化 |
| 核心目标 | 接入 Admin Login、任务诊断与 Provider 成本接口，并按输入人物保存完整检索链路日志 |

## 2. 需求背景

当前 searchTool 的单个 Query 采集链路为：

```text
CreateIntentTask
  → GetTask 每 5 秒轮询
  → ListTaskCandidates
  → 依次请求全部 GetTaskCandidateDetail
  → 保存 results.jsonl、Raw 和 SQLite
```

该链路能够完成检索任务创建、状态轮询、候选人列表获取及全部候选人详情采集，
但原检索接口未提供或未稳定提供以下任务级公共信息：

- 实际检索处理时间；
- 排队时间和端到端时间；
- LLM 成本；
- 第三方 Provider 成本；
- 总成本和币种；
- PDL 是否调用及是否成功；
- Provider 请求数、工具调用数、失败数；
- Fallback、停止原因和任务诊断信息。

检索系统优化后新增了两个 Admin 数据接口：

1. `GetSearchTaskDebug`：查询检索任务时间、调用链和诊断信息；
2. `GetProviderCostSummary`：查询 Provider 调用及成本汇总。

两个接口使用与原检索接口不同的 URL 和认证参数，需要作为独立的任务级辅助采集链路接入。
两个接口所需的 `session_token` 不由使用者手动填写，而是通过 Admin `Login` 接口获取。
Token 有效期约 12 小时，实际失效时间以 Login 返回的 `expire_time` 为准；Token 到期或被服务端判定失效后，
searchTool 需要重新登录并更新当前运行进程使用的 Token。

## 3. 需求目标

### 3.1 产品目标

1. 每个已创建成功的检索任务都可以采集任务级耗时、成本、PDL 和诊断信息；
2. 公共信息与对应 `task_id`、`input_id`、Query 和 Run 稳定关联；
3. `SUCCEEDED` 和 `NO_RESULT` 均可保存公共信息；
4. 公共信息可进入 `results.jsonl`、Raw、SQLite、后续指标和报告；
5. 两个辅助接口异常时不改变原检索任务和候选人采集结果；
6. Admin 接口与原 Search API 使用独立配置，互不影响；
7. searchTool 自动通过 Login 获取并维护 Admin Session Token，支持超过 12 小时的长批次运行。
8. 每个输入人物均有一份可独立追溯的完整请求与响应日志。

### 3.2 成功标准

- `GetTask` 进入终态后，按顺序请求 `GetSearchTaskDebug` 和 `GetProviderCostSummary`；
- `SUCCEEDED` 时，公共信息采集完成后继续执行 List 和全部 Candidate Detail；
- `NO_RESULT` 时，完成公共信息采集后再结束当前 Query；
- 单个辅助接口失败不会阻断另一个辅助接口，也不会阻断原主链路；
- 成本、耗时和布尔值保持真实类型，缺失值保存为 `null`，不能按 0 或 `false` 替代；
- 完整响应可在 Raw 数据中追溯，报告只使用标准化后的安全字段；
- Admin Session Token 不写入日志、JSONL、SQLite 或报告；
- 首次调用 Admin 数据接口前完成登录并缓存 Token 和 `expire_time`；
- Token 到期或接口返回明确认证失效时，自动重新登录并只重放一次原请求；
- 距离 `expire_time` 不足 1 小时时提前重新登录；
- 每个输入人物的 Create、全部 GetTask 轮询、Debug、Cost、List 和全部 Detail 请求与响应写入同一日志；
- 日志文件位于项目根目录 `log/`，基础命名为“日期+输入人物姓名”；
- 未配置 Admin 接口时，原 searchTool 采集流程仍可正常运行。

## 4. 需求范围

### 4.1 本次包含

1. 独立 Admin Login URL、数据接口 URL、Headers 和账号配置；
2. Admin 登录、Session Token 内存缓存与过期更新；
3. `GetSearchTaskDebug` 请求与响应采集；
4. `GetProviderCostSummary` 请求与响应采集；
5. 检索时间、成本、PDL 和诊断字段标准化；
6. `results.jsonl`、Raw 和 SQLite 数据保存；
7. 辅助采集状态、异常、重试和降级规则；
8. 成本单位、币种和完整性状态处理；
9. 对现有 Run、导入、无成本重处理和报告的兼容要求。
10. 项目级 `log/` 目录及按输入人物拆分的完整链路日志。

### 4.2 本次不包含

- 修改 Create、GetTask、List、Candidate Detail 的接口契约；
- 修改现有候选人身份归类、字段比较和质量指标公式；
- 将 Admin Debug 全量响应直接展示在正式报告；
- Provider 调用级独立数据库表和调用明细分析页面；
- 将辅助接口失败计为检索执行失败；
- 多币种自动汇率换算；
- 对接口中未定价的调用自行估算成本；
- Admin 账号创建、密码找回、权限申请和统一密钥管理。
- 将链路日志作为长期归档、集中日志平台或告警系统使用。

## 5. 目标采集链路

### 5.1 正常链路

本次确定采用以下顺序：

```text
CreateIntentTask
    ↓ task_id
GetTask 每 5 秒轮询
    ↓ SUCCEEDED / NO_RESULT
等待 1 秒（等待公共信息最终写入）
    ↓
确保 Admin Session 有效
    ├─ 未登录/即将过期 → Login
    └─ 有效 → 复用进程内 Token
    ↓
GetSearchTaskDebug
    ↓
GetProviderCostSummary
    ↓
SUCCEEDED → ListTaskCandidates → 全部 Candidate Detail
NO_RESULT → 直接整理结果
    ↓
统一写入 results.jsonl / Raw / SQLite
```

### 5.2 接入位置说明

两个新接口必须放在 `GetTask` 进入终态之后、`ListTaskCandidates` 之前，原因如下：

1. 两个接口只依赖 `task_id`，属于 Query/Task 级信息，不属于 Candidate 级信息；
2. 终态后采集可以获得相对完整的任务时间、Provider 调用和成本；
3. 在 List 之前采集，可避免 List 或 Candidate Detail 异常导致公共信息丢失；
4. `NO_RESULT` 没有候选人，但仍然产生任务耗时和可能的 Provider 成本，因此也必须采集；
5. 两个接口不得放入 Candidate Detail 循环，避免对同一任务重复请求。
6. GetTask 进入任一终态后统一等待 1 秒，再检查 Admin Session 并调用两个公共接口；该等待用于规避成本等公共信息的最终一致性延迟。

Admin Login 同样不得按 Candidate 重复调用。正常情况下，一个 searchTool 运行进程在 Token 有效期内只登录一次；
只有 Token 到期、即将到期或服务端明确返回认证失效时才重新登录。

### 5.3 不同任务状态处理

| GetTask 状态 | 公共信息处理 | 后续处理 |
| --- | --- | --- |
| `QUEUED` | 不请求，继续每 5 秒轮询 | 继续 GetTask |
| `SEARCHING` | 不请求，继续每 5 秒轮询 | 继续 GetTask |
| `SUCCEEDED` | 请求 Debug，再请求 Cost | List → 全部 Candidate Detail |
| `NO_RESULT` | 请求 Debug，再请求 Cost | 不请求 List/Detail，整理结果 |
| 已确认的失败终态 | 等待 1 秒后请求 Debug 和 Cost，按实际响应保存 | 当前 Query 按原失败规则结束 |
| 缓存命中终态 | 等待 1 秒后请求 Debug 和 Cost，并保留 `cache_hit` | 按终态继续原后续流程 |
| 轮询超时 | 未进入终态，不将公共信息作为正式完整耗时和成本 | 当前 Query 按原规则失败 |
| Create 失败 | 无 `task_id`，不请求两个 Admin 接口 | 当前 Query 按原规则失败 |
| 未知状态 | 不将非终态数据写成正式成本；按原异常规则处理 | 保留错误和 Raw |

`NO_RESULT`、已确认的失败终态和缓存命中任务均已确认可以查询 `GetSearchTaskDebug` 与
`GetProviderCostSummary`。失败终态获得的字段按接口实际完整性保存，不影响 Query 原失败结论。

## 6. Admin API 配置需求

### 6.1 配置隔离原则

两个新接口不能复用：

- `SEARCH_API_URL`；
- 原检索 `AUTH_TOKEN`；
- 原检索 Device ID 和 User ID 认证逻辑。

它们应使用独立 Admin 配置。Login 使用 `/admin/invoke`，Debug 和 Cost 使用 `/gateway/invoke`；
登录成功后，两个数据接口共用本次登录获得的 Session Token 和操作人信息。

### 6.2 建议配置项

```dotenv
# 是否启用任务公共信息采集
SEARCH_ADMIN_ENABLED=true

# Admin Login 与数据接口地址，均与原 SEARCH_API_URL 独立
SEARCH_ADMIN_LOGIN_API_URL=http://admin-staging.spark-jam.top/admin/invoke
SEARCH_ADMIN_API_URL=http://admin-staging.spark-jam.top/gateway/invoke
SEARCH_ADMIN_HTTP_HEADERS_JSON={"Content-Type":"application/json"}

# Admin 登录账号；Session Token 和 Operator 信息由 Login 响应获得
SEARCH_ADMIN_USERNAME=
SEARCH_ADMIN_PASSWORD=
SEARCH_ADMIN_REASON=searchTool 测试数据采集

# 接口参数
SEARCH_ADMIN_DEBUG_SERVICE=worker
SEARCH_ADMIN_COST_LIMIT=100

# 每个输入人物的完整请求/响应日志
SEARCH_QUERY_LOG_ENABLED=true
SEARCH_QUERY_LOG_DIR=log
```

### 6.3 配置校验规则

1. `SEARCH_ADMIN_ENABLED=false` 时，不校验其他 Admin 配置；
2. `SEARCH_ADMIN_ENABLED=true` 时，Login URL、数据接口 URL、Username 和 Password 为必填；
3. Admin Headers 必须为合法 JSON 对象；
4. Admin 配置错误只关闭本次公共信息采集并记录明确原因，不应导致原 Search API 无法启动；
5. `session_token`、`operator_id`、`operator_name` 和 `expire_time` 从 Login 响应读取，不要求使用者写入 `.env`；
6. 用户名可以在脱敏审计信息中记录，密码和 Session Token 不允许出现在日志或数据文件中；
7. 登录账号配置错误时，将公共信息采集标记为认证失败，但原 Search API 仍可继续运行；
8. `SEARCH_QUERY_LOG_DIR` 默认解析为项目根目录下的 `log/`，不得接受指向项目外部的非法路径；
9. 日志开关只控制独立 `.log` 文件，不影响现有 Raw 和 SQLite 记录。

### 6.4 Session 生命周期

1. 首次需要请求 Debug 或 Cost 时执行 Login，避免未发生公共信息采集时无意义登录；
2. 登录成功后，将 `session_token`、`expire_time`、`operator_id` 和 `operator_name` 缓存在当前进程内；
3. Session Token 的有效期约 12 小时，但必须以响应 `expire_time` 为准，不能只按固定 12 小时计算；
4. 每次请求 Debug/Cost 前检查 Token 是否存在以及是否接近过期；
5. 为避免长时间 Query 或批次执行过程中 Token 失效，在距离 `expire_time` 不足 1 小时时提前重新登录；
6. 如果 Debug/Cost 返回明确的 Token 过期、未登录或认证失败状态，立即重新登录；
7. 重新登录成功后，只重放一次原 Debug/Cost 请求，防止账号配置错误造成无限循环；
8. 重新登录失败时，将对应公共信息采集状态标记为 `AUTH_FAILED`，但不阻断原检索主链路；
9. Token 只保存在内存中，searchTool 重启后重新登录，不从文件恢复旧 Token；
10. 同一运行进程的 Query 顺序执行时共用当前有效 Token，不允许每个 Query 都重新登录。

## 7. 接口需求

### 7.1 Admin Login

#### 7.1.1 请求用途

通过 Admin 用户名和密码换取 Debug、Cost 数据接口所需的 `session_token`、失效时间和操作人信息。

#### 7.1.2 请求地址

```text
POST http://admin-staging.spark-jam.top/admin/invoke
```

实际地址由 `SEARCH_ADMIN_LOGIN_API_URL` 配置，不在代码中固定环境域名。

#### 7.1.3 请求契约

```json
{
  "client_request_id": "每次登录生成唯一值",
  "method_name": "Login",
  "reason": "",
  "params": {
    "username": "来自 SEARCH_ADMIN_USERNAME",
    "password": "来自 SEARCH_ADMIN_PASSWORD"
  }
}
```

#### 7.1.4 响应提取

| 来源 | 运行时字段 | 用途 |
| --- | --- | --- |
| `responses[0].data.session_token` | `session_token` | Debug/Cost 请求认证 |
| `responses[0].data.expire_time` | `session_expire_time` | 判断 Token 是否需要更新 |
| `responses[0].data.operator.operator_id` | `operator_id` | Debug/Cost 请求参数 |
| `responses[0].data.operator.operator_name` | `operator_name` | Debug/Cost 请求参数 |
| `responses[0].data.operator.permissions` | `operator_permissions` | 权限诊断，不进入正式报告 |
| `responses[0].data.operator.role` | `operator_role` | 权限诊断，不进入正式报告 |

登录成功条件必须同时满足：

- 顶层 `code == 0`；
- `responses[0].success == true`；
- `session_token` 非空；
- `expire_time` 可以解析；
- `operator_id` 和 `operator_name` 非空。

任一条件不满足均视为登录失败，不能继续使用旧 Token 冒充登录成功。

### 7.2 GetSearchTaskDebug

#### 7.2.1 请求用途

获取任务时间、运行状态、请求链、Provider 调用、工具调用、失败、Fallback 和停止原因。

#### 7.2.2 请求契约

```json
{
  "comm": {
    "device_id": "admin-web",
    "platform": "web",
    "app_version": "1.0.0",
    "trace_id": "每次请求生成"
  },
  "requests": [
    {
      "service_name": "tool.admin.AdminService",
      "method_name": "GetSearchTaskDebug",
      "params": {
        "session_token": "来自 Login 响应/进程内缓存",
        "operator_id": "来自 Login 响应",
        "operator_name": "来自 Login 响应",
        "reason": "来自配置",
        "task_id": "当前任务 task_id",
        "service": "worker"
      }
    }
  ]
}
```

#### 7.2.3 首版提取范围

| 来源 | 目标字段 | 用途 |
| --- | --- | --- |
| `debug.task.create_time` | `task_create_time` | 计算排队和端到端耗时 |
| `debug.task.start_time` | `task_start_time` | 计算排队和检索耗时 |
| `debug.task.finish_time` | `task_finish_time` | 计算检索和端到端耗时 |
| `debug.task.status` | `debug_task_status` | 诊断与一致性检查 |
| `debug.task.cache_hit` | `cache_hit` | 区分缓存与真实检索 |
| `debug.diagnosis.provider_request_count` | `provider_request_count` | Provider 调用规模 |
| `debug.diagnosis.agent_tool_call_count` | `agent_tool_call_count` | 工具调用规模 |
| `debug.diagnosis.successful_call_count` | `successful_call_count` | 调用诊断 |
| `debug.diagnosis.failed_call_count` | `failed_call_count` | 调用诊断 |
| `debug.diagnosis.unpriced_call_count` | `debug_unpriced_call_count` | 成本完整性辅助检查 |
| `debug.diagnosis.fallback_used` | `fallback_used` | 降级分析 |
| `debug.diagnosis.fallback_reason` | `fallback_reason` | 降级原因 |
| `debug.diagnosis.stop_reason` | `stop_reason` | 任务停止原因 |
| `debug.diagnosis.final_status` | `debug_final_status` | 诊断终态 |
| `debug.diagnosis.warnings` | `debug_warnings` | 诊断警告 |

`provider_requests`、`agent_tool_calls`、事件和其他大对象首版保留在脱敏 Raw 中，
不全部展开成固定数据库列。

### 7.3 GetProviderCostSummary

#### 7.3.1 请求用途

获取任务级 Provider 调用明细和按币种、Provider、Worker、Search 汇总的正式成本信息。

#### 7.3.2 请求契约

```json
{
  "comm": {
    "device_id": "admin-web",
    "platform": "web",
    "app_version": "1.0.0",
    "trace_id": "每次请求生成"
  },
  "requests": [
    {
      "service_name": "tool.admin.AdminService",
      "method_name": "GetProviderCostSummary",
      "params": {
        "session_token": "来自 Login 响应/进程内缓存",
        "operator_id": "来自 Login 响应",
        "operator_name": "来自 Login 响应",
        "reason": "来自配置",
        "task_id": "当前任务 task_id",
        "limit": 100
      }
    }
  ]
}
```

#### 7.3.3 首版提取范围

| 来源 | 目标字段 | 用途 |
| --- | --- | --- |
| `cost_summary.totals` | `cost_totals_by_currency` | 各币种正式总成本和调用统计 |
| `cost_summary.by_provider` | `cost_by_provider` | LLM/第三方成本归类 |
| `cost_summary.by_worker` | `cost_by_worker` | Raw/诊断保留 |
| `cost_summary.by_search` | `cost_by_search` | Raw/诊断保留 |
| `cost_summary.calls` | `provider_cost_calls` | PDL 调用判断、完整 Raw 追溯 |
| `cost_summary.from_time` | `cost_from_time` | 成本统计范围 |
| `cost_summary.to_time` | `cost_to_time` | 成本统计范围 |

## 8. 字段口径

### 8.1 耗时字段

平台需要明确区分三类时间：

| 字段 | 计算公式 | 业务含义 |
| --- | --- | --- |
| `queue_duration_ms` | `start_time - create_time` | 任务创建后等待执行的时间 |
| `search_duration_ms` | `finish_time - start_time` | Worker 实际检索处理时间 |
| `end_to_end_duration_ms` | `finish_time - create_time` | 从创建任务到任务完成的总时间 |

规则：

1. 正式报告中的“检索耗时”默认使用 `search_duration_ms`；
2. 时间计算必须使用接口返回时间，不能用 searchTool 本地请求耗时替代；
3. 任一必要时间缺失或格式错误时，对应时长保存为 `null`；
4. 负数时长视为接口数据异常，保存 `null` 并记录警告；
5. 原始时间继续保存，用于审计。

### 8.2 成本字段

| 字段 | 数据来源 | 规则 |
| --- | --- | --- |
| `llm_cost` | `cost_summary.by_provider` | 汇总被归类为 LLM 的 Provider |
| `third_party_cost` | `cost_summary.by_provider` | 汇总 PDL 等第三方数据 Provider |
| `total_cost` | `cost_summary.totals` | 直接采用接口总额，不用子成本二次相加 |
| `cost_currency` | `cost_summary.totals` | 单币种时保存该币种 |
| `cost_totals_by_currency` | `cost_summary.totals` | 始终保留每个币种的汇总 |
| `cost_complete` | `unpriced_call_count` | 为 0 时为 `true`，大于 0 时为 `false` |
| `pdl_called` | Calls/Provider 汇总 | 存在 `people_data_labs` 调用即为 `true` |
| `pdl_success` | Calls | 至少一次 PDL 调用状态为成功时为 `true` |

成本处理规则：

1. `total_cost` 以 Cost Summary 为唯一正式数据源；
2. Debug 中的 `estimated_cost_microunit` 仅用于一致性检查，不能与正式成本相加或取平均；
3. 接口中的数字字符串需要安全转换为数字；
4. `microunit` 换算规则需由后端最终确认；确认前保留原始微单位值，不在报告中推测币种金额；
5. 单币种且单位确认后，标准金额按后端确认比例转换；
6. 多币种不能直接相加，`total_cost` 和 `cost_currency` 保存为 `null`，并按币种保留汇总；
7. `unpriced_call_count > 0` 时允许展示已定价部分，但必须标记“成本不完整”；
8. 没有返回成本和真实零成本必须区分：前者为 `null`，后者为数值 `0`。

### 8.3 Provider 分类

首版建议支持以下默认分类：

| Provider 特征 | 分类 |
| --- | --- |
| Provider 名以 `llm_search:` 开头 | LLM |
| Provider 为 `people_data_labs` | 第三方数据 |
| 未识别 Provider | 其他/待配置，不强行并入 LLM 或第三方 |

Provider 分类应集中配置，不能散落在指标和报告代码中。新增 Provider 后可以补充映射，
不需要修改原始采集流程。

## 9. 公共信息采集状态

每个 Query 需要保存独立的公共信息采集状态：

| 状态 | 含义 |
| --- | --- |
| `COMPLETE` | Debug 和 Cost 均成功，且成本数据完整 |
| `PARTIAL` | 只有一个接口成功，或存在未定价/缺失字段 |
| `FAILED` | 两个接口均请求失败或响应不可解析 |
| `AUTH_FAILED` | Login 失败，或 Token 失效后重新登录失败 |
| `NOT_CONFIGURED` | 未启用或缺少 Admin 配置 |
| `INCOMPLETE_TASK` | GetTask 未进入终态，仅保存诊断快照 |

同时分别保存：

- `debug_collection_status`；
- `cost_collection_status`；
- `public_info_status`；
- `public_info_collected_at`；
- `public_info_warnings`。

## 10. 请求失败与重试规则

### 10.1 基本原则

两个接口属于辅助采集接口，失败不能改变以下主链路结果：

- Query 是否执行成功；
- 是否返回候选人；
- Candidate Detail 是否采集成功；
- searchTool 主进程的业务成功状态。

### 10.2 顺序与隔离

1. 先请求 Debug，再请求 Cost；
2. Debug 失败后仍必须请求 Cost；
3. Cost 失败后仍必须继续 List/Detail；
4. 每个接口单独记录请求阶段、响应、异常和状态；
5. 不允许使用一个接口的失败覆盖另一个接口已成功采集的数据。

### 10.3 重试

1. GetTask 进入终态后先统一等待 1 秒，再首次请求 Debug 和 Cost；
2. 网络超时、5xx 或 Cost 空响应可再执行一次短重试；
3. 明确认证失败时，先重新 Login；登录成功后只重放一次原请求；
4. 重新登录失败、重放后仍认证失败、参数错误和权限错误不再持续重试；
5. 不新增类似 GetTask 的长期轮询；
6. 登录次数、Token 更新时间、请求重试次数和最终错误必须进入脱敏审计记录。

## 11. 数据保存需求

### 11.1 results.jsonl

标准化公共字段继续写入现有 `task_fields`：

```json
{
  "task_fields": {
    "queue_duration_ms": 1082,
    "search_duration_ms": 60997,
    "end_to_end_duration_ms": 62079,
    "llm_cost": 0.001928,
    "third_party_cost": 0.84,
    "total_cost": 0.841928,
    "cost_currency": "USD",
    "cost_complete": true,
    "pdl_called": true,
    "pdl_success": true,
    "provider_request_count": 1,
    "agent_tool_call_count": 5,
    "successful_call_count": 2,
    "failed_call_count": 3,
    "fallback_used": true,
    "fallback_reason": "LLM_INVALID_RESPONSE",
    "public_info_status": "COMPLETE"
  }
}
```

示例只用于说明目标结构，不代表接口样例中的业务数值必须固定。

### 11.2 Raw 数据

Raw 增加 Login 和两个数据请求阶段，但 Login 阶段只能保存脱敏摘要：

```json
{
  "raw": {
    "create_intent_task": {},
    "get_task_history": [],
    "admin_login": {
      "status": "SUCCESS",
      "expire_time": "2026-08-05T15:01:37.804Z",
      "operator_id": "已脱敏",
      "token_saved": false
    },
    "get_search_task_debug": {},
    "get_provider_cost_summary": {},
    "list_task_candidates": {},
    "candidate_details": []
  }
}
```

每个阶段至少保留：

- 请求时间；
- 接口名称；
- `task_id`；
- 请求序号和重试次数；
- HTTP 状态；
- 业务响应；
- 脱敏后的错误信息；
- 采集状态。

Login Raw/审计记录禁止保存：

- 明文密码；
- 明文 `session_token`；
- 完整认证请求体；
- 可以用于恢复 Token 的任何派生值。

### 11.3 SQLite

现有字段优先复用：

- `llm_cost`；
- `third_party_cost`；
- `total_cost`；
- `pdl_called`；
- `search_duration_ms`；
- `public_fields_json`。

其他耗时、成本明细、Provider 汇总和诊断信息首版保存到 `public_fields_json`。
本需求不要求为了 Provider 调用明细新增独立业务表。

### 11.4 数据来源标记

公共字段需要记录来源，至少可以区分：

- `GetSearchTaskDebug`；
- `GetProviderCostSummary`；
- 计算字段；
- 未接入；
- 接口缺失；
- 类型异常。

字段缺失不能被错误标记为数值 0、布尔值 `false` 或空字符串。

### 11.5 输入人物级完整链路日志

#### 11.5.1 日志对象

本需求中的“一次候选人检索日志”按输入 Query/人物划分，而不是按接口返回的每个 Candidate 划分。
一个输入人物可能返回多个 Candidate，这些 Candidate Detail 请求与响应全部进入该输入人物的同一份日志。

这样一份日志可以完整还原：

```text
输入人物/Query
  → CreateIntentTask
  → 每一次 GetTask 轮询
  → 必要时 Admin Login（只记录脱敏摘要）
  → GetSearchTaskDebug
  → GetProviderCostSummary
  → ListTaskCandidates
  → 每一个 GetTaskCandidateDetail
  → Query 最终结果或失败
```

#### 11.5.2 日志目录

日志目录固定建立在项目根目录，与 `input/`、`output/` 同级：

```text
/Users/admin/Testproject/Truthy_Search/
├── input/
├── output/
├── log/
└── search_tool.py
```

目录要求：

1. `SEARCH_QUERY_LOG_ENABLED=true` 时，启动运行后自动确保 `log/` 存在；
2. 不要求使用者手动创建目录；
3. 日志目录不可用时，需要给出明确错误；
4. 独立日志写入失败不能丢失现有 Raw 数据，但应将本次运行标记为日志不完整；
5. `log/` 中只保存链路日志，不混放报告、输入文件和 Excel。

#### 11.5.3 文件命名

基础命名格式：

```text
YYYY-MM-DD_输入人物姓名.log
```

例如：

```text
2026-08-05_Stephanie_McMahon.log
2026-08-05_张三.log
```

命名规则：

1. 日期使用 Query 实际开始执行时的本地日期，格式为 `YYYY-MM-DD`；
2. 人物姓名优先取输入 Query 的 `full_name`/人物姓名字段，不使用返回 Candidate 的姓名；
3. 空格统一替换为 `_`；
4. `/`、`\\`、`:`、控制字符和路径穿越字符需要替换，禁止人物姓名改变日志目录；
5. 输入人物姓名为空时使用 `input_id`；
6. 同一天同名人物首次运行使用基础名称；
7. 基础文件已经存在时禁止覆盖，追加 `input_id`；
8. 如果追加 `input_id` 后仍冲突，再追加运行时分秒或递增序号。

冲突示例：

```text
2026-08-05_张三.log
2026-08-05_张三_case-002.log
2026-08-05_张三_case-002_143520.log
```

#### 11.5.4 日志格式

文件扩展名为 `.log`，内容采用 JSON Lines：每次请求、响应、重试或关键状态各占一行。
相比自由文本，JSON Lines 既方便人工查看，也方便后续按 `stage`、`candidate_id` 或状态检索。

每行至少包含：

```json
{
  "timestamp": "2026-08-05 14:35:20",
  "sequence_no": 7,
  "run_id": "run_xxx",
  "input_id": "case-001",
  "person_name": "Stephanie McMahon",
  "task_id": "task_xxx",
  "candidate_id": null,
  "stage": "GetTask",
  "attempt": 3,
  "http_status": 200,
  "business_success": true,
  "duration_ms": 268,
  "request": {},
  "response": {},
  "error": null
}
```

时间格式统一使用平台当前展示格式：

```text
YYYY-MM-DD HH:mm:ss
```

#### 11.5.5 必须记录的阶段

| 阶段 | 记录要求 |
| --- | --- |
| Query Start | 输入人物、`input_id`、Run、输入条件和开始时间 |
| CreateIntentTask | 完整脱敏请求与响应，生成的 `task_id` |
| GetTask | 每一次轮询分别记录，不只保留最终一次 |
| Admin Login | 仅记录登录时间、结果、`expire_time` 和脱敏 Operator 摘要 |
| GetSearchTaskDebug | 完整脱敏请求与响应及重试 |
| GetProviderCostSummary | 完整脱敏请求与响应及重试 |
| ListTaskCandidates | 完整脱敏请求与响应、候选人数 |
| GetTaskCandidateDetail | 每个 `candidate_id` 分别记录请求与响应，单人失败也保留 |
| Query End | 最终状态、候选人数、Detail 成功/失败数和结束时间 |

#### 11.5.6 写入时机

1. 每次 HTTP 请求结束后立即追加一条日志，不能等整个 Run 结束后统一写入；
2. GetTask 多次轮询必须保持真实顺序；
3. Candidate Detail 必须包含对应 `candidate_id`；
4. 请求异常、超时、响应解析失败也必须写日志；
5. Query 中途失败时，已写日志继续保留，并追加 Query End 失败记录；
6. 日志与现有 Raw 使用同一套接口事件和脱敏函数，避免两套数据口径不一致；
7. 日志仅追加，不允许覆盖已经写入的内容。

#### 11.5.7 “完整请求与响应”的边界

“完整”指完整保存排障所需的业务请求和业务响应结构，但安全字段必须例外：

- 保留接口名、业务参数、响应状态、响应数据、错误信息和耗时；
- HTTP Header 只保留非敏感必要字段，不保存完整认证 Header；
- `password`、`session_token`、`auth_token`、Cookie 和其他认证凭据必须移除或统一写成 `***`；
- Login 请求不得保存密码，Login 响应不得保存 Token；
- 被脱敏字段需要保留字段名和 `***`，使使用者知道该字段存在但不能恢复其内容。

独立 `.log` 不能绕过现有 Raw 的脱敏规则。日志用于排障和追溯，不等于允许保存明文秘密。

## 12. Raw 与安全要求

1. Admin 登录密码和 `session_token` 必须在写日志和 Raw 前移除，不能只依赖前端隐藏；
2. 报告快照不得包含 Session Token、Operator 认证参数和完整请求头；
3. Debug 响应可能包含用户标识、IP、内部响应地址和请求载荷，进入 Raw 前需要执行已有敏感字段脱敏；
4. 正式报告只保存标准化后的耗时、成本、PDL 和诊断摘要；
5. 静态 HTML 不嵌入完整 Admin Debug 响应；
6. Admin 配置错误提示不得回显秘密值；
7. 导出 Excel 时只导出业务需要的标准字段，不导出认证参数。
8. Session Token 只允许存在于运行进程内存和当前 HTTP 请求中；
9. `.env` 中的 Admin Password 不得提交到版本库，示例配置只能保留空值；
10. Login 响应进入通用 HTTP 日志前必须先移除 `session_token`。
11. 独立人物日志与 Raw 执行相同或更严格的敏感字段脱敏；
12. 日志文件权限应仅允许当前运行用户访问，不作为 Web 静态文件公开；
13. 报告页面不得直接拼接本地日志绝对路径为公开下载地址。

## 13. 指标与报告衔接

### 13.1 可用字段

接入完成后，以下字段可用于 Query、Run 和报告聚合：

- 实际检索耗时；
- 排队和端到端耗时；
- LLM 成本；
- 第三方成本；
- 总成本；
- 币种；
- PDL 调用率和成功情况；
- 成本完整性；
- Provider/工具调用数；
- Fallback 使用率及原因。

### 13.2 聚合规则

1. 只聚合有效数值，`null` 不进入分母；
2. 不同币种分别汇总，不进行自动换算；
3. 成本不完整时展示已知成本和覆盖情况，不伪装成完整总成本；
4. 辅助接口失败不影响检索质量指标；
5. Debug 诊断字段只用于解释性能和异常，不参与身份命中、准确率和资料完整度；
6. 缓存命中任务应保留 `cache_hit`，避免将其耗时与完整检索错误比较。

## 14. 兼容性要求

1. `SEARCH_ADMIN_ENABLED=false` 时，原 Create → GetTask → List → Detail 流程完全不变；
2. 旧 `results.jsonl` 缺少新字段时继续兼容，显示“未接入/无数据”，不能按 0；
3. 旧 Run 和旧报告快照不自动修改；
4. 历史 Raw 中没有两个 Admin 响应时，无成本重处理不能凭空补齐数据；
5. 历史 Run 如需补采 Admin 数据，应作为后续独立功能，不属于本期无成本重处理；
6. Candidate Detail 单人失败规则保持不变，继续采集剩余候选人；
7. 当前全部候选人采集规则保持不变，不恢复前 5 名限制。

## 15. 验收场景

### 15.1 正常成功任务

- 首次需要采集公共信息时 Login 成功；
- 从 Login 响应获得 Token、`expire_time` 和 Operator 信息；
- GetTask 最终为 `SUCCEEDED`；
- Debug 和 Cost 均成功；
- List 和全部 Candidate Detail 正常执行；
- `task_fields` 包含耗时、成本、PDL 和诊断字段；
- Raw 包含两个新阶段；
- `public_info_status=COMPLETE`。

### 15.2 无候选人任务

- GetTask 最终为 `NO_RESULT`；
- 仍调用 Debug 和 Cost；
- 不调用 List 和 Detail；
- 保存真实耗时、成本和诊断；
- Query 结果仍按无候选人处理，而不是执行失败。

### 15.2.1 终态后延迟采集

- GetTask 进入 `SUCCEEDED`、`NO_RESULT` 或已确认失败终态；
- searchTool 等待 1 秒后才发起第一个 Admin 公共接口请求；
- 等待过程不重复请求 GetTask；
- Debug 与 Cost 的调用顺序保持不变。

### 15.3 Debug 失败、Cost 成功

- Cost 数据正常保存；
- Debug 字段保持 `null`；
- `public_info_status=PARTIAL`；
- 继续执行 List 和 Detail。

### 15.4 Debug 成功、Cost 失败

- 耗时和诊断信息正常保存；
- 成本字段保持 `null`；
- `public_info_status=PARTIAL`；
- 继续执行 List 和 Detail。

### 15.5 两个辅助接口均失败

- `public_info_status=FAILED`；
- 记录脱敏错误；
- 主检索任务和候选人采集不受影响；
- 缺失成本不能显示为 0。

### 15.6 未配置 Admin 接口

- 原采集链路可正常运行；
- `public_info_status=NOT_CONFIGURED`；
- Web/CLI 提示公共信息采集未启用，但不报告主任务失败。

### 15.7 成本存在未定价调用

- 已定价成本正常保存；
- `cost_complete=false`；
- 保存 `unpriced_call_count`；
- 报告明确显示“已知成本，统计不完整”。

### 15.8 多币种

- 各币种独立保存；
- 不生成跨币种 `total_cost`；
- 报告不自行换算或相加。

### 15.9 安全验收

- 在日志、JSONL、SQLite、Raw 和 HTML 中搜索不到明文密码和 Session Token；
- 请求失败提示不包含完整认证头；
- Debug 敏感字段按既有规则脱敏。

### 15.10 Token 有效期内复用

- 连续处理多个 Query 时不重复登录；
- 每次 Debug/Cost 请求前检查当前 `expire_time`；
- Token 仍有超过 1 小时有效期时直接复用。

### 15.11 Token 到期自动更新

- 当前时间接近或超过 `expire_time` 时重新 Login；
- 使用新 Token 和新 Operator 信息执行后续请求；
- 旧 Token 不写回 `.env`，也不保存在数据文件中；
- 长批次运行超过约 12 小时后无需人工介入。

### 15.12 服务端提前判定 Token 失效

- Debug 或 Cost 返回明确认证失效；
- searchTool 重新 Login，并只重放一次失败请求；
- 重放成功后继续正常链路；
- 重新登录或重放仍失败时标记 `AUTH_FAILED`，继续原 Search 主链路。

### 15.13 Login 配置或认证失败

- 用户名/密码缺失时显示明确配置错误；
- 用户名/密码错误或账号无权限时不进入无限重试；
- Debug/Cost 字段保存为 `null`，公共信息状态为 `AUTH_FAILED`；
- Create、GetTask、List 和 Candidate Detail 继续按原规则执行。

### 15.13.1 失败终态与缓存命中

- 失败终态仍可查询 Debug 和 Cost，公共字段按实际响应保存；
- Query 的失败状态不会被公共接口成功覆盖；
- 缓存命中任务仍查询 Debug 和 Cost，并保存 `cache_hit=true`；
- 缓存任务的耗时和成本可被识别，后续报告不得与非缓存任务混淆解释。

### 15.14 单人物完整链路日志

- 执行一个正常返回多个 Candidate 的 Query；
- `log/` 下生成一份“日期+输入人物姓名”的 `.log`；
- 同一文件包含 Create、每次 GetTask、Debug、Cost、List 和全部 Detail；
- 每个 Detail 记录包含正确的 `candidate_id`；
- Query End 的 Candidate 数量与 List 响应一致。

### 15.15 同名日志防覆盖

- 同一天执行两个同名输入人物；
- 第一份使用基础文件名；
- 第二份追加 `input_id`，不覆盖第一份；
- 两份日志分别关联正确的 `task_id` 和 Run。

### 15.16 失败链路日志

- 模拟 GetTask 超时、Cost 失败或单个 Candidate Detail 失败；
- 失败请求和已获得的响应仍写入人物日志；
- 日志以 Query End 失败/部分成功记录结束；
- 日志写入不会阻断其他人物继续执行。

### 15.17 日志脱敏

- `.log` 中不存在明文密码、Session Token、Auth Token、Cookie 和认证 Header；
- Login 和 Admin 请求仍可看到已脱敏字段名，便于确认请求结构；
- 日志中的业务响应、轮询历史和 Candidate Detail 数据完整可查。

## 16. 验收标准

- [ ] 两个接口只在任务级调用一次，不在 Candidate 循环中重复调用；
- [ ] 接口顺序为 GetTask 终态 → 等待 1 秒 → 确保 Session 有效 → Debug → Cost → List/Detail；
- [ ] `NO_RESULT`、失败终态和缓存命中任务均执行两个 Admin 公共接口；
- [ ] Session 在首次使用前通过 Login 获取，不要求人工填写 Token；
- [ ] Token 有效期内跨 Query 复用，不按 Query 重复登录；
- [ ] 距离 `expire_time` 不足 1 小时时提前重新登录；
- [ ] Token 到期或服务端提前判定失效时自动重新登录；
- [ ] 认证失败后的原请求最多重放一次，不会无限循环；
- [ ] `SUCCEEDED` 和 `NO_RESULT` 均采集公共信息；
- [ ] Debug 与 Cost 相互独立，一个失败不影响另一个；
- [ ] 辅助采集失败不影响原主链路成功状态；
- [ ] 耗时严格由接口时间计算；
- [ ] 正式总成本严格取自 Cost Summary；
- [ ] 缺失、零值和未定价状态能够区分；
- [ ] 多币种不直接相加；
- [ ] 新字段进入 results.jsonl、Raw 和 SQLite；
- [ ] 旧数据、旧 Run 和旧报告保持兼容；
- [ ] 密码、Session Token 和敏感数据不泄露；
- [ ] 项目根目录 `log/` 中按输入人物生成独立日志；
- [ ] 日志基础命名符合 `YYYY-MM-DD_输入人物姓名.log`；
- [ ] 同日同名日志不会覆盖，冲突时追加 `input_id`；
- [ ] 日志包含每次 GetTask 轮询和全部 Candidate Detail 请求与响应；
- [ ] 日志逐请求落盘，中途失败仍可追溯；
- [ ] 日志与 Raw 使用一致的脱敏和接口事件口径；
- [ ] 相关自动化测试和集成测试通过。

## 17. 待后端确认事项

以下字段及业务口径均不阻塞 Login、Debug、Cost 的链路开发。未确认字段先完整保存 Raw 和来源状态，
不能自行猜测或填 0；待后端信息整理完成后再补充正式映射：

1. `microunit` 与币种标准单位的正式换算比例；
2. `GetProviderCostSummary.limit` 是否只限制 `calls`，还是也影响 `totals`、`by_provider` 等汇总；
3. Cost Summary 是否可能返回多个币种；
4. Provider 的完整枚举及 LLM、第三方、其他 Provider 的正式分类规则；
5. PDL 调用成功状态的正式枚举；
6. Debug 中 `start_time` 到 `finish_time` 是否可正式定义为检索处理时间；
7. Cost Summary 的 `total_cost_microunit` 是否已经包含所有子 Provider 成本。

以下认证事项已经确认，不再列为待确认：

- Session Token 通过 Admin Login 获取；
- Token 有效期约 12 小时，以 Login 返回的 `expire_time` 为准；
- Token 过期后由 searchTool 重新登录并更新进程内 Token；
- GetTask 进入终态后等待 1 秒，再查询公共接口；
- `NO_RESULT`、失败终态和缓存命中任务均可查询 Debug 和 Cost。

## 18. 后续需求池

以下能力不在本期实现，可后续独立规划：

1. Provider 调用级查询、筛选和时间轴；
2. 历史 Run 按 `task_id` 补采 Debug 和 Cost；
3. Provider 成本趋势、预算和异常告警；
4. 不同 Worker、Search、Provider 的成本拆解报告；
5. Admin 账号统一密钥管理和凭据轮换；
6. 多币种汇率换算；
7. 将诊断警告与失败案例自动关联；
8. 成本和耗时参考线配置。
