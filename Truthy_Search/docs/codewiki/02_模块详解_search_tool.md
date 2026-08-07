# 02 · 模块详解：search_tool.py（CLI 采集工具）

文件：[search_tool.py](../../search_tool.py)（约 2552 行）

## 1. 职责

命令行批量检索采集工具，同时也是 Web 后台采集的**可复用内核**。对输入 JSONL 中的每条检索任务（Query），按顺序调用四个业务接口并采集候选人完整 `ui_sections`：

```text
CreateIntentTask → GetTask（每 5 秒轮询）→ ListTaskCandidates → GetTaskCandidateDetail
```

v1.3 起在 GetTask 进入终态后，可选地经 Admin 通道采集任务公共信息（Debug 诊断 + 成本汇总）。所有落盘数据经 `sanitize_raw` 脱敏。

## 2. 类与数据结构

### 2.1 异常

| 类 | 行号 | 说明 |
|---|---|---|
| `ConfigError(ValueError)` | 66–67 | 本地配置非法；主链路配置错误直接终止进程（退出码 1） |
| `FlowError(RuntimeError)` | 70–101 | 可记录的业务失败。携带 `stage`（失败阶段/接口名）、`task_id`、`response_body`、`raw_records`（已收集的脱敏 Raw）、`task_fields`、`public_fields`、`http_status`、`duration_ms` |

### 2.2 `Config`（frozen dataclass，行 104–282）

不可变运行配置。关键字段：

- 主链路：`api_url / headers / auth_token / device_id / user_id`、`poll_interval_seconds=5.0`、`max_poll_count=60`、`http_timeout_seconds=30.0`、`platform/app_version/locale/timezone`（默认 `ios / 1.0.0 / zh-Hans-CN / UTC+08:00`）；
- IO：`input_file="input/tasks.jsonl"`、`output_dir="output"`、`allow_duplicate_run=False`；
- Admin：`admin_enabled`、`admin_login_api_url`、`admin_api_url`、`admin_headers`、`admin_username/password`、`admin_reason`、`admin_debug_service="worker"`、`admin_cost_limit=100`、`admin_config_error`；
- 日志：`query_log_enabled`、`query_log_dir="log"`、`query_log_timezone="Asia/Shanghai"`。

核心方法 `Config.from_env(env_file)`（135–282）：

- 用 `dotenv_values` 读取 `.env`（或平台只读 Secret 文件），随后 `config_values.update(os.environ)` —— **进程环境变量覆盖文件值**，且不写入 `os.environ`（支持平台热更新 Token、避免污染重跑）；
- 必填校验：`SEARCH_API_URL / AUTH_TOKEN / DEVICE_ID / USER_ID`，缺失抛 `ConfigError`；
- **Admin 配置错误不抛异常**：只记入 `admin_config_error` 并关闭公共信息采集，不阻断主链路；
- 辅助解析：`_positive_float`（285–297）、`_positive_int`（300–312）、`_env_bool`（315–341，仅接受 `true/1/yes/on`、`false/0/no/off`）。

### 2.3 `SearchClient`（行 394–521）

主链路 HTTP 客户端，持有 `requests.Session` 与内建的 `AdminClient`（同一 Run 复用 Admin 会话）。

- `call(method_name, params)`（409–485）：构造统一 RPC 报文——`comm` 段含 `auth_token/device_id/user_id/client_request_id(crid-时间戳-随机)/platform/app_version/locale/timezone`；POST 后记录 HTTP 状态与耗时，失败时把已取得的响应体挂到 `FlowError.response_body`；
- `_validate_response`（487–521，staticmethod）：校验顶层 `code==0`、`responses[0].success is True` 且 `code==0`、`data` 为对象。

### 2.4 `AdminClient`（行 524–806）

管理一个 Run 内复用的 Admin 登录会话（公共信息采集通道）。

| 方法 | 行号 | 说明 |
|---|---|---|
| `available` | 541–545 | `admin_enabled` 且无 `admin_config_error` |
| `drain_audit_events / drain_call_attempts` | 547–559 | 取出审计缓冲，由 `process_one` 转成 Raw 记录 |
| `_session_is_fresh` | 561–567 | Token 距失效 ≥ 1 小时（`ADMIN_REFRESH_WINDOW`）才算新鲜 |
| `login` | 647–714 | 调 `Login`；成败均追加脱敏审计事件（`operator_id` 恒为 `"***"`，`token_saved=False`） |
| `_is_auth_failure` | 722–742 | 通过 HTTP 401/403、响应 code 或关键词（`token expired`、`未登录` 等）识别认证失效 |
| `call(method_name, params)` | 744–806 | 调 `GetSearchTaskDebug / GetProviderCostSummary`；认证失效时重新登录并**仅重放一次** |

### 2.5 `QueryChainLogger`（行 1211–1394）

按输入人物追加**人工可读**的脱敏链路日志：

- 文件名 `YYYY-MM-DD_HHMMSS_{人物名}.log`，独占模式（`open("x")`）创建，冲突时逐级追加后缀（最多 `_9999`），绝不覆盖；
- `write_event(stage, **values)`（1281–1366）：写事件标题、缩进 JSON 的请求/响应（全部脱敏）、HTTP 状态与耗时，立即 flush；
- `write_raw(record)`（1368–1383）：把统一 Raw 记录转成日志格式，避免第二套脱敏口径；
- 目录/创建错误不中断检索，只记录 `self.error` 并停用日志。

## 3. 主流程

入口链：`main`（2513–2548）→ `run_batch`（2372–2492）→ `process_one`（1439–2363）。

### 3.1 `main`

1. 解析 `--input / --output / --env-file`（`build_parser`，2495–2510）；
2. `Config.from_env`；`ConfigError` → 打印并返回 1；
3. 输入路径（CLI 优先于 `.env`），不存在 → 1；
4. `select_output_paths`（344–391）选定输出文件，冲突且不允许重复 → 1；
5. `run_batch` 批处理，返回 `2 if failure_count else 0`。

### 3.2 `run_batch`

1. 创建输出目录并**先清空**本批次的 `results.jsonl` / `failures.jsonl`；
2. 生成批次 `run_id`（`run_{uuid4hex}`）；
3. 逐行 `read_jsonl`（1427–1436，空行跳过、JSON 错误带行号下传）→ `validate_input`（1397–1424，校验 `input_id` 非空且批内唯一、`clues` 非空、`match_strategy` 默认 `UNION`）→ `process_one`；
4. 成功写入 results；`query_status == PARTIAL_DETAIL_FAILED` 计入失败数但仍写入 results；
5. Query 级 `FlowError` → 构造 scope=`INPUT/QUERY` 的失败记录（含已收集全部 Raw）写入 failures，**继续下一行**。

### 3.3 `process_one` —— 单条 Query 完整链路

```text
1. 初始化        创建 QueryChainLogger，写 QueryStart；定义 emit_progress /
                 call_and_record（每次调用成功或失败都生成脱敏 Raw + 日志）等闭包
2. CreateIntentTask   resolve_query_stage 判定 FULL_NAME / FULL_NAME_SOCIAL
                 （旧输入按 clues 是否含 SOCIAL_LINK 推断），校验返回 task_id
3. GetTask 轮询  先 sleep(poll_interval) 再调用，最多 max_poll_count 次；
                 SUCCEEDED/NO_RESULT 为成功终态（NO_RESULT 直接短路后续）；
                 FAILED 为失败终态（先补采公共信息再抛 FlowError）；超时抛错
4. 公共信息采集  终态后固定等待 1 秒 → GetSearchTaskDebug → GetProviderCostSummary
                 （无 cost_summary 时短等 1 秒重试一次）；失败只降级不中断；
                 extract_admin_task_fields（819–1040）提取 5 个正式任务字段
5. ListTaskCandidates   固定 page_size=100 一次拉全部候选人
6. GetTaskCandidateDetail 循环   逐候选人取详情；单个失败隔离处理：
                 results 写 detail_status=FAILED 占位项 + 候选级失败记录，继续下一个
7. 汇总          query_status = NO_CANDIDATE / PARTIAL_DETAIL_FAILED / SUCCESS；
                 result_status = HAS_CANDIDATES / NO_CANDIDATES / EXECUTION_FAILED
                 （normalize_result_status，40–63）；finally 写 QueryEnd 关闭日志
```

**任务字段提取**（`extract_admin_task_fields`，819–1040）：成本按 Admin Cost Summary 的 USD microunit ÷ 1,000,000；`llm_search*` 前缀计入 `llm_cost`，排除集合 `{"llm_search","public_figure","agent_people","search_agent"}` 计入第三方成本；`pdl_called` 读 Debug diagnosis，`search_duration_ms = finish_time - start_time`；明细完整时缺失类别补真实 0，否则保持 None；映射状态 `COMPLETE/PARTIAL/NOT_MAPPED`。

## 4. 输出文件格式与命名

### 4.1 路径与去重（`select_output_paths`，344–391）

- 命名：`{YYYYMMDD}_{输入文件stem}_results.jsonl` / `..._failures.jsonl`；
- 同日文件已存在时：`ALLOW_DUPLICATE_RUN=false` 抛 `FileExistsError`（退出码 1）；`true` 时递增生成 `_run02`、`_run03`…；已有文件永不覆盖。

### 4.2 results.jsonl（`result_schema_version="1.3.1"`）

每行一条 Query 记录：`run_id / input_id / task_id / query_stage / query_status / result_status / candidate_count_total / candidate_count_listed / detail_success_count / detail_failure_count / task_fields / public_fields / raw / results`。

- `raw`：`create_intent_task / get_task_history / admin 各阶段 / list_task_candidates` 的脱敏业务请求与响应；
- `results[]`：`candidate_rank / candidate_id / rank_score / detail_status / detail_error / list_item_raw / detail_data_raw / detail_response_raw / ui_sections`；`detail_status=FAILED` 时 `ui_sections` 固定 `null`。

### 4.3 failures.jsonl（`failure_schema_version=1.3`）

`run_id / input_id / task_id / candidate_id / scope / stage / error / result_status` + 失败时已取得的脱敏 Raw。`scope ∈ {INPUT, QUERY, CANDIDATE}`：Query 级失败在批处理收尾写入，候选级失败即时写入。

## 5. 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 全部成功（含无候选人） |
| `1` | 配置错误 / 输入文件不存在 / 输出路径冲突，无法启动 |
| `2` | 批处理完成但存在 Query 失败或部分候选人详情失败 |

## 6. 脱敏（`sanitize_raw`，1043–1083）

递归遍历任意 JSON，按键名归一化（小写、去空格、`-`→`_`）后删除敏感键：

```text
password, session_token, auth_token, authorization, cookie,
set_cookie, headers, http_headers, device_id, user_id
```

应用点：所有 Raw 记录的 request/response、人物日志事件、候选人三快照与 `ui_sections`。Raw 本身不含 `comm` 鉴权段；Admin Login Raw 的 `username/password` 恒写 `"***"`。

## 7. 关键常量与辅助函数

| 名称 | 行号 | 说明 |
|---|---|---|
| `SERVICE_NAME` | 25 | `tool.people_insight.SearchService` |
| `ADMIN_SERVICE_NAME` | 26 | `tool.admin.AdminService` |
| `RESULT_SCHEMA_VERSION` | 27 | `"1.3.1"` |
| `GET_TASK_RUNNING_STATUSES` | 28 | `{"QUEUED","SEARCHING"}` |
| `GET_TASK_FAILURE_TERMINAL_STATUSES` | 32 | `{"FAILED"}`（后端扩枚举只需改此集合） |
| `ADMIN_REFRESH_WINDOW` | 33 | 1 小时 Token 刷新窗口 |
| `PUBLIC_INFO_TERMINAL_DELAY_SECONDS` | 34 | 终态后等 1 秒再采公共信息 |
| `resolve_query_stage` | 1102–1131 | `FULL_NAME` / `FULL_NAME_SOCIAL` 判定 |
| `extract_person_name` | 1185–1199 | 从 FULL_NAME 线索取人物名（日志文件名用） |
| `build_raw_record` | 1166–1182 | 统一 Raw 记录结构 |
| `append_jsonl / read_jsonl` | 2366 / 1427 | JSONL 读写 |

## 8. 与其他模块的关系

- **被 `analysis_service.execute_run` 复用**：Web 采集时直接调用本模块的 `process_one`（注入回调），并复用 `FlowError / extract_admin_task_fields / normalize_result_status / sanitize_raw / RESULT_SCHEMA_VERSION`；
- **产物被消费**：`results.jsonl / failures.jsonl` 可导入 Web（`import_results_jsonl`）或被 `result_to_excel.py` 的 single/compare 模式读取；
- **测试**：[tests/test_search_tool.py](../../tests/test_search_tool.py) 使用 `tests/fixtures/v1_3_*` 脱敏夹具做契约测试，不调真实接口。
