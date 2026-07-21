# searchTool 轻量开发设计与开发计划（MVP）

## 1. 结论

本期只需要一个**顺序执行的 Python 脚本**，不需要并发、数据库、Web 页面、复杂状态机或恢复机制。

用户提供 N 条（如 10 条）`CreateIntentTask.params` 输入，脚本每次完整处理一条后再处理下一条：

```text
第 1 条输入
  CreateIntentTask → 等 5 秒 → GetTask
  → 若 QUEUED：每隔 5 秒 GetTask
  → 若 SUCCEEDED：ListTaskCandidates（最多取 5 个 candidate_id）
  → 逐个 GetTaskCandidateDetail
  → 保存该输入得到的 ui_sections

第 2 条输入
  重复上述流程
```

最终得到 N 组结果；每组最多含 5 名候选人的 `ui_sections`。

> 实际字段路径以样例为准：`responses[0].data`，而不是 `responses.data`。

## 2. 范围

### 包含

- 读取一个 JSONL 输入文件，一行代表一次 `CreateIntentTask` 的 `params`；
- 顺序调用四个 HTTP 接口；
- `GetTask` 每 5 秒轮询一次；
- 任务成功后获取候选列表的前 5 名；
- 对每名候选人请求详情，提取完整 `ui_sections`；
- 输出一个 JSONL 结果文件和一个失败记录文件；
- HTTP 地址、基础请求头、token 和用户信息由 `.env` 配置。

### 不包含

- 并发/异步批处理；
- 数据库、断点恢复、失败自动重跑；
- CSV/XLSX 报告（可在拿到结果 JSONL 后按实际分析字段再加）；
- Web UI、token 自动续期、图片下载与二次分析。

## 3. 最小工程结构

```text
Truthy_Search/
├── search_tool.py             # 唯一的业务脚本
├── requirements.txt           # requests、python-dotenv
├── .env                       # 本地真实配置，不提交
├── .env.example               # 配置模板，可提交
├── .gitignore
├── input/
│   └── tasks.jsonl
└── output/
    ├── results.jsonl
    └── failures.jsonl
```

依赖仅使用：

- `requests`：发送同步 HTTP 请求；
- `python-dotenv`：读取 `.env`。

## 4. 配置

在项目根目录创建 `.env`，实际接口信息由使用者提供后填写：

```dotenv
SEARCH_API_URL=https://example.internal/api/rpc
SEARCH_HTTP_HEADERS_JSON={"x-app-id":"people-insight"}
AUTH_TOKEN=replace-me
DEVICE_ID=replace-me
USER_ID=replace-me
POLL_INTERVAL_SECONDS=5
MAX_POLL_COUNT=60
```

说明：

- 四个方法向同一个 `SEARCH_API_URL` 发 `POST`；
- `SEARCH_HTTP_HEADERS_JSON` 放接口要求的固定 HTTP headers；脚本额外设置 `Content-Type: application/json`；
- `AUTH_TOKEN` 过期时，手动更新 `.env` 后再次运行；
- `MAX_POLL_COUNT=60` 时，最长等待约 5 分钟，避免任务无限轮询。

`.env` 与 `output/` 必须加入 `.gitignore`，避免提交凭证和搜索结果。

## 5. 输入格式

文件：`input/tasks.jsonl`。一行是一条搜索任务，只放 `CreateIntentTask.params` 所需的业务字段。

```json
{"input_id":"case-001","match_strategy":"UNION","clues":[{"type":"FULL_NAME","full_name_query":{"full_name":"JOJO CCQQ MOCK"}},{"type":"LOCATION","location_query":{"location":"us"}}],"additional_details":[{"type":"PROFESSION","value":"photographer"}]}
{"input_id":"case-002","match_strategy":"UNION","clues":[{"type":"FULL_NAME","full_name_query":{"full_name":"Jane Doe"}}],"additional_details":[]}
```

- `input_id`：每一行唯一，用于关联结果；
- `clues`：必填，原样传给 `CreateIntentTask.params.clues`；
- `additional_details`：可选，缺省按空数组处理；
- `match_strategy`：可选，缺省为 `UNION`；
- 10 条输入即 10 行，按文件顺序执行 10 次完整流程。

## 6. 单条任务执行逻辑

### 6.1 通用 HTTP 请求体

每次请求都构造同一个外层结构，只改变 `method_name` 与 `params`：

```json
{
  "comm": {
    "auth_token": "<AUTH_TOKEN>",
    "device_id": "<DEVICE_ID>",
    "user_id": "<USER_ID>",
    "client_request_id": "自动生成的唯一 ID",
    "platform": "ios",
    "app_version": "1.0.0",
    "locale": "zh-Hans-CN",
    "timezone": "UTC+08:00"
  },
  "requests": [{
    "id": "req_0",
    "service_name": "tool.people_insight.SearchService",
    "method_name": "接口方法名",
    "params": {}
  }]
}
```

`platform`、`app_version` 以联调确认后的固定值为准。

### 6.2 伪代码

```python
for input_item in read_jsonl("input/tasks.jsonl"):
    # 1. 创建任务
    create = call("CreateIntentTask", {
        "match_strategy": input_item.get("match_strategy", "UNION"),
        "clues": input_item["clues"],
        "additional_details": input_item.get("additional_details", []),
    })
    task_id = create["responses"][0]["data"]["task_id"]

    # 2. 每 5 秒查询任务状态
    for _ in range(MAX_POLL_COUNT):
        sleep(POLL_INTERVAL_SECONDS)
        task = call("GetTask", {"task_id": task_id})
        status = task["responses"][0]["data"]["status"]
        if status == "SUCCEEDED":
            break
        if status != "QUEUED":
            raise RuntimeError(f"unexpected task status: {status}")
    else:
        raise TimeoutError("task polling timed out")

    # 3. 一次获取最多 5 名候选人
    candidates = call("ListTaskCandidates", {
        "task_id": task_id,
        "page": {"page_size": 5, "page_token": ""},
    })["responses"][0]["data"]["items"]

    # 4. 获取每个候选人的 ui_sections
    details = []
    for candidate in candidates[:5]:
        detail = call("GetTaskCandidateDetail", {
            "task_id": task_id,
            "candidate_id": candidate["candidate_id"],
        })
        details.append({
            "candidate_id": candidate["candidate_id"],
            "ui_sections": detail["responses"][0]["data"].get("ui_sections", {}),
        })

    append_jsonl("output/results.jsonl", {
        "input_id": input_item["input_id"],
        "task_id": task_id,
        "results": details,
    })
```

说明：`ListTaskCandidates` 的 `page_size` 设为 `5`，因此本期不需要分页。若接口不保证 `page_size=5` 可生效，仍只取返回数组的前 5 项。

## 7. 输出格式

### 7.1 成功结果：`output/results.jsonl`

一条输入对应输出一行；`results` 最多 5 项。`ui_sections` 原样保存，新增字段也会被保留。

```json
{
  "input_id": "case-001",
  "task_id": "task_cd520407e9d29ca4cc314d09",
  "results": [
    {
      "candidate_id": "report_xxx_candidate_1",
      "ui_sections": {
        "summary": {"status": "data", "data": {}},
        "profile": {"status": "data", "data": {}},
        "social": {"status": "data", "data": {}},
        "photos": {"status": "data", "data": {}},
        "insights": {"status": "empty", "data": {}}
      }
    }
  ]
}
```

### 7.2 失败记录：`output/failures.jsonl`

某一条输入失败时记录错误，但不中断后续输入：

```json
{"input_id":"case-002","task_id":"task_xxx","stage":"GetTask","error":"task polling timed out"}
```

常见失败点：创建接口失败、超时、状态不是 `QUEUED/SUCCEEDED`、候选列表或候选详情接口返回错误、响应缺少预期字段。

## 8. 开发计划

| 步骤 | 工作 | 产出 |
| --- | --- | --- |
| 1 | 创建最小工程、依赖、`.env.example` 与 `.gitignore` | 脚本可启动，凭证不会被提交 |
| 2 | 实现 `.env` 读取、JSONL 读取与统一 `call()` 请求函数 | 可向统一网关调用单个方法 |
| 3 | 实现 Create → 每 5 秒 GetTask 轮询 → List 前 5 名 → Detail 的单条链路 | 一条样本能写出 `ui_sections` |
| 4 | 外层循环处理 JSONL 的全部输入；每条异常写失败文件并继续 | 10 条输入可顺序执行 |
| 5 | 用实际接口联调，确认 URL、headers、`platform`、`app_version` 和响应字段路径 | 可用 MVP 脚本 |

## 9. 实现前仅需提供的内容

1. 实际 `SEARCH_API_URL`；
2. 实际固定 HTTP headers；
3. `AUTH_TOKEN`、`DEVICE_ID`、`USER_ID`；
4. 一条可用于联调的 JSONL 输入。

提供后即可按该设计直接开发。
