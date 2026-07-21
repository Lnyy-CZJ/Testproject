# searchTool PRD（轻量 MVP）

## 1. 目标

做一个本地运行的批量搜索脚本。

用户一次准备多条 `CreateIntentTask` 的搜索条件（例如 10 条），脚本按输入顺序逐条调用现有 HTTP 接口，最终取得每条搜索任务中最多 5 名候选人的 `ui_sections` 数据，并保存为结果文件。

本期核心是稳定跑通接口链路和拿到原始结果，不做页面、并发或复杂报表。

## 2. 用户流程

```text
准备 tasks.jsonl（例如 10 条搜索条件）
  ↓
脚本处理第 1 条：
  CreateIntentTask
  ↓ 等待 5 秒
  GetTask
  ↓ status = QUEUED：再等待 5 秒，继续 GetTask
  ↓ status = SUCCEEDED：ListTaskCandidates
  ↓
取前 5 个 candidate_id（不足 5 个则全取）
  ↓
逐个调用 GetTaskCandidateDetail，保存 ui_sections
  ↓
继续处理第 2 条，直至全部完成
```

## 3. 功能需求

### 3.1 批量输入

- 输入文件格式为 JSONL：一行代表一次搜索任务；
- 用户可提供 10 条、100 条或更多条输入；
- 脚本必须按文件顺序**依次**处理，每次只处理一个任务，不并发；
- 每条输入都有唯一的 `input_id`，用于对应最终结果；
- `clues` 与 `additional_details` 原样传入 `CreateIntentTask`。

输入文件：`input/tasks.jsonl`

```json
{"input_id":"case-001","match_strategy":"UNION","clues":[{"type":"FULL_NAME","full_name_query":{"full_name":"JOJO CCQQ MOCK"}},{"type":"LOCATION","location_query":{"location":"us"}}],"additional_details":[{"type":"PROFESSION","value":"photographer"}]}
{"input_id":"case-002","match_strategy":"UNION","clues":[{"type":"FULL_NAME","full_name_query":{"full_name":"Jane Doe"}}],"additional_details":[]}
```

字段说明：

| 字段 | 是否必填 | 说明 |
| --- | --- | --- |
| `input_id` | 是 | 本批次内唯一的输入标识 |
| `clues` | 是 | 直接传入 `CreateIntentTask.params.clues` |
| `additional_details` | 否 | 直接传入 `CreateIntentTask.params.additional_details`；缺省按空数组处理 |
| `match_strategy` | 否 | 直接传入 `CreateIntentTask.params.match_strategy`；缺省为 `UNION` |

### 3.2 单条接口调用流程

#### 1）创建任务：`CreateIntentTask`

使用当前输入的 `clues`、`additional_details` 和 `match_strategy` 创建任务。

- 从 `responses[0].data.task_id` 获取 `task_id`；
- 创建失败时，将该条输入写入失败文件，并继续下一条输入。

#### 2）轮询状态：`GetTask`

- 取得 `task_id` 后，先等待 5 秒；
- 调用 `GetTask`，从 `responses[0].data.status` 读取状态；
- 状态为 `QUEUED`：再等待 5 秒并重复查询；
- 状态为 `SUCCEEDED`：进入候选人列表查询；
- 超过最大轮询次数仍非 `SUCCEEDED`：记录超时并继续下一条；
- 返回任何其他状态或接口异常：记录失败并继续下一条。

默认最大轮询次数为 60，即最多等待约 5 分钟；该值可配置。

#### 3）获取候选人：`ListTaskCandidates`

- 仅在任务状态为 `SUCCEEDED` 后调用；
- 从 `responses[0].data.items` 读取候选人；
- 按接口返回顺序取前 5 个 `candidate_id`；若候选人不足 5 个，取得全部；若没有候选人，记录一条成功但无结果的输出。

本期不翻页，因为仅需要前 5 名候选人。

#### 4）获取候选详情：`GetTaskCandidateDetail`

对每个已选的 `candidate_id` 依次调用：

```json
{
  "task_id": "<task_id>",
  "candidate_id": "<candidate_id>"
}
```

从 `responses[0].data.ui_sections` 获取并原样保存完整对象。未来 `ui_sections` 新增字段时，不需要修改输入或丢弃新字段。

### 3.3 配置

四个接口共用一个 HTTP 地址和基础请求头。真实配置放在项目根目录 `.env` 文件中，不写入输入或代码：

```dotenv
SEARCH_API_URL=https://example.internal/api/rpc
SEARCH_HTTP_HEADERS_JSON={"x-app-id":"people-insight"}
AUTH_TOKEN=replace-me
DEVICE_ID=replace-me
USER_ID=replace-me
POLL_INTERVAL_SECONDS=5
MAX_POLL_COUNT=60
```

- `AUTH_TOKEN` 失效后由用户手动更新；
- `DEVICE_ID`、`USER_ID` 由用户提供；
- `SEARCH_HTTP_HEADERS_JSON` 由用户提供接口所需固定请求头；
- `.env` 不得提交到版本库。

## 4. 输出需求

### 4.1 成功结果

输出文件：`output/results.jsonl`。

每个输入任务输出一行，包含输入标识、任务标识和最多 5 个候选人的 `ui_sections`：

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

- `results` 为空数组表示任务成功但没有候选人；
- `ui_sections` 保持 JSON 结构，不转换为 CSV；
- 后续确认报告字段后，再单独增加 JSONL 转 CSV/XLSX 功能。

### 4.2 失败记录

输出文件：`output/failures.jsonl`。

单条请求失败、轮询超时或返回未知状态时，记录失败原因，但不阻止处理下一条输入：

```json
{"input_id":"case-002","task_id":"task_xxx","stage":"GetTask","error":"task polling timed out"}
```

## 5. 非功能要求

| 项目 | 要求 |
| --- | --- |
| 执行方式 | 同步、顺序执行，不并发 |
| 轮询间隔 | 默认 5 秒，可配置 |
| 最大等待 | 默认 60 次轮询，约 5 分钟，可配置 |
| 异常处理 | 单条失败写入失败文件，继续下一条 |
| 安全 | token 和身份信息仅存 `.env`；不得写入结果文件或日志 |
| 数据保留 | 保存完整 `ui_sections`，包括未知字段 |

## 6. 不在本期范围内

- 并发请求、限流调度；
- 数据库、断点恢复和自动重跑；
- CSV/XLSX 报告、固定字段映射；
- Web 管理页面；
- token 自动刷新；
- 图片下载、OCR、AI 分析或结果真实性判断。

## 7. 验收标准

1. 给定 10 条合法 JSONL 输入，脚本按顺序发起 10 次完整的任务处理流程；
2. 每条任务先调用 `CreateIntentTask`，再每隔 5 秒调用 `GetTask`，直到 `SUCCEEDED` 或超时；
3. 每个成功任务只请求一次 `ListTaskCandidates`，并仅对前 5 名（或全部不足 5 名）候选人请求详情；
4. 成功结果写入 `output/results.jsonl`，且每个候选人均包含完整的 `ui_sections`；
5. 任一条输入失败或超时后，错误写入 `output/failures.jsonl`，后续输入仍继续执行；
6. token、固定请求头等敏感信息不出现在输入和输出文件中。

## 8. 开发前需要提供的信息

1. 统一的 `SEARCH_API_URL`；
2. 固定 HTTP 请求头；
3. `AUTH_TOKEN`、`DEVICE_ID`、`USER_ID`；
4. 一条可用于联调的输入样本；
5. `platform`、`app_version` 的最终值（若样例中的值可用，则按样例固定）。
