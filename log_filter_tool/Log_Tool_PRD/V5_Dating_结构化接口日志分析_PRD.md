# Log 工具 V5 Dating 结构化接口日志分析 PRD

> 文档版本：v1.0  
> 创建日期：2026-08-29  
> 状态：待评审  
> 适用项目：`log_filter_tool`  
> 方案：方案三——通用 Gateway 日志解析器 + Dating 领域适配器 + 确定性规则  
> 首期约束：不接入 LLM，不调用任何外部 AI 服务

---

## 1. 产品定位

在现有 Log 工具的接口筛选、接口统计和 People Insight 专项分析能力基础上，新增 Dating 接口日志的确定性结构化分析能力。

本功能将 Dating 自动化测试日志中的 Gateway 请求、Gateway 响应、对象存储 PUT 上传、异步任务轮询和最终结果接口还原为可检索、可比较、可导出的结构化数据，并通过固定规则检查接口和字段之间的一致性。

首期只做事实整理和确定性判断：

- 展示实际调用了哪些接口。
- 展示每个接口的请求参数、HTTP 状态、业务状态、耗时和响应字段。
- 聚合 Reply 与 Analysis 异步任务的完整生命周期。
- 按 Schema 对最终结果字段分组。
- 明确区分字段有值、`null`、空字符串、空数组、空对象和缺失。
- 对任务状态、计数、时间、Schema、Top Pick 等执行确定性检查。
- 每个结果和检查项都能定位到原始日志行号。

本功能不负责判断自然语言分析内容是否正确，也不生成 AI 总结。

---

## 2. 背景与问题

### 2.1 当前问题

现有 Log 工具的通用解析主要提供：

- method 提取。
- request_id、trace_id 提取。
- HTTP 状态码统计。
- 请求数、响应数、成功率统计。
- 日志筛选、搜索、复制和导出。

这些能力不能完整回答 Dating 接口调试中的关键问题：

1. 一次 Gateway 请求中的 `requests[]` 与响应中的 `responses[]` 是否正确对应。
2. HTTP 200 时，Gateway 外层和子响应是否也成功。
3. 图片是否完成 `Prepare → PUT → Complete` 全链路。
4. Reply 或 Analysis 任务经历了哪些状态和进度。
5. 创建任务、轮询任务和获取结果的 `task_id`、`task_type` 是否一致。
6. 最终结果有哪些字段，哪些字段是 `null`、空值或缺失。
7. Reply 的 Top Pick、Alternatives 和 Replies 是否一致。
8. Analysis 的图片数、消息数和 Dashboard 字段是否自洽。
9. 一个异常结论对应原日志的哪一段。

当前人工分析可以还原上述信息，但结果依赖分析人员经验，无法稳定复用到日志工具中。

### 2.2 样本日志

首期以以下两份真实日志作为黄金样本：

1. `Truthy_ApiAutoTest2/logs/dating/test/2026-08-29/20260829_185108_082227_test_332.log`
   - 业务类型：多图 Reply。
   - 最终 Schema：`dating.reply_generation.v1`。

2. `Truthy_ApiAutoTest2/logs/dating/test/2026-08-29/20260829_185318_825054_test_445.log`
   - 业务类型：多图 Analysis。
   - 最终 Schema：`dating.relationship_analysis.v1`。

进入自动化测试夹具前，样本必须完成鉴权令牌、签名 URL 和用户标识脱敏；脱敏不能改变接口方法、task_id、asset_id、业务字段、状态、计数、时间和行结构。

---

## 3. 目标与成功标准

### 3.1 产品目标

1. 不依赖 LLM，还原 Dating 接口调用和异步任务链路。
2. 将请求、响应和最终业务结果转换为稳定 JSON 数据结构。
3. 支持 Reply 与 Analysis 两种结果 Schema 的业务分组展示。
4. 自动发现明确的字段不一致、空值和数据缺口。
5. 让测试人员无需手工搜索原日志即可看到关键字段实际值。
6. 保持现有 People Insight 分析、接口过滤和统计行为不变。

### 3.2 可衡量成功标准

- 两份黄金日志均能被识别为 `dating`，且无阻断性解析错误。
- Reply 黄金日志识别到 19 次 Gateway 调用、2 次 PUT 上传和 1 个 Reply 任务。
- Analysis 黄金日志识别到 30 次 Gateway 调用、3 次 PUT 上传和 1 个 Analysis 任务。
- 每个 Gateway 请求能与正确响应配对。
- HTTP、Gateway 外层和 Gateway 子响应三层状态均被独立保存。
- Reply 的 2 个 asset_id、11 次轮询、任务终态和最终结果完整展示。
- Analysis 的 3 个 asset_id、21 次轮询、任务终态和最终结果完整展示。
- 最终结果中所有叶子字段均进入字段索引，不得静默丢弃未知字段。
- `null`、空字符串、空数组、空对象和缺失字段能够分别统计。
- 每个调用、字段和检查项包含日志行号或行范围。
- 相同输入重复分析时，除分析时间外的结果完全一致。
- 分析过程不进行网络请求，不读取 LLM 配置，不产生模型费用。
- 现有 People Insight 测试和通用日志过滤测试全部通过。

---

## 4. 用户与使用场景

### 4.1 目标用户

- Dating 接口测试工程师。
- Dating 后端工程师。
- Dating 客户端工程师。
- 测试平台维护人员。

### 4.2 核心场景

#### 场景 A：检查 Reply 最终返回

测试人员粘贴 Reply 完整日志，点击“结构化接口分析”，查看：

- 上传了几张图片。
- 创建了哪个任务。
- 任务轮询了多少次。
- 最终生成了几条回复。
- Top Pick 是哪一条。
- warning 和 degradation 是否一致。

#### 场景 B：检查 Analysis 最终返回

测试人员粘贴 Analysis 完整日志，查看：

- 多少张图片有效。
- 分析了多少条消息。
- relationship_stage、current_state 和 reliability_level 的实际值。
- effort、match_degree、keywords 等字段是否为空。
- signals 和 key_events 的证据消息 ID。

#### 场景 C：定位接口异常

某接口 HTTP 200，但 Gateway 子响应 `success=false`。工具必须标记为业务失败，并显示：

- method。
- Gateway request_id、trace_id。
- 子响应 code、message。
- 原始请求和响应行范围。

#### 场景 D：检查日志完整性

日志缺少响应、JSON 被截断或任务未到终态时，工具必须保留已解析数据，并说明无法判断的原因，不能把日志不足解释为业务失败。

---

## 5. 范围

### 5.1 首期范围

- Dating Gateway 请求和响应解析。
- Dating 图片 PUT 上传请求和响应解析。
- 请求与响应配对。
- Gateway 外层和子响应解包。
- 上传资源链路聚合。
- Reply 异步任务聚合。
- Analysis 异步任务聚合。
- 两种已知结果 Schema 的字段分组。
- 未知 Schema 的通用字段树兜底。
- 字段状态索引。
- 确定性一致性检查。
- 页面结构化展示。
- Markdown 和 JSON 导出。
- 单任务选择。
- 解析告警和证据行号。
- 敏感字段脱敏。

### 5.2 明确不在首期范围

- LLM、Skill 或其他 AI 总结。
- 自然语言文案事实判断或情感判断。
- 判断一段关系建议是否正确。
- OCR 图片内容重新识别。
- 从日志外部请求任务、图片或数据库信息。
- 多个任务的批量统计报表。
- 跨日志、跨用户或跨环境任务关联。
- 任意业务 Schema 的自动语义推断。
- 修改 Dating 服务端业务逻辑。
- 修改 People Insight 规则结论。
- 新建插件系统或复杂类继承框架。

### 5.3 功能需求清单

| Requirement ID | 优先级 | 需求 | 验收映射 |
|---|---:|---|---|
| `FR-001` | P0 | 识别并解析 Gateway 请求、Gateway 响应和 PUT 上传 marker | AC-001、AC-002 |
| `FR-002` | P0 | 按子请求 ID 配对 Gateway requests[] 与 responses[] | AC-003 |
| `FR-003` | P0 | 分层保存 HTTP、Gateway 外层和 Gateway 子响应状态 | AC-003 |
| `FR-004` | P0 | 聚合 Prepare、PUT、Complete 上传资源链路 | AC-001、AC-002 |
| `FR-005` | P0 | 聚合 Reply/Analysis 创建、轮询、结果任务链路 | AC-004、AC-005 |
| `FR-006` | P0 | 同时生成原始结果树和扁平字段索引 | AC-006、AC-007 |
| `FR-007` | P0 | 支持两个首期 Dating Schema 的业务分组 | AC-006、AC-007 |
| `FR-008` | P0 | 区分 PRESENT、NULL、EMPTY 和 MISSING | AC-008 |
| `FR-009` | P0 | 执行固定一致性检查并输出 PASS/FAIL/WARN/UNKNOWN/NA | AC-012 |
| `FR-010` | P0 | 调用、字段和检查项包含可回溯的日志行范围 | AC-011 |
| `FR-011` | P1 | 页面展示摘要、接口链路、上传、时间线、字段和规则 | AC-017 |
| `FR-012` | P1 | 支持脱敏后的 Markdown 和 JSON 导出 | AC-018 |
| `FR-013` | P0 | 响应和导出统一脱敏 | AC-013 |
| `FR-014` | P1 | 未知字段保留，未知 Schema 降级为通用字段树 | AC-009、AC-010 |
| `FR-015` | P0 | 分析全程不调用 LLM 或其他外部服务 | AC-015 |

---

## 6. 术语与状态

| 术语 | 定义 |
|---|---|
| Gateway 调用 | 发送到 `/dating/gateway/invoke` 的请求及其响应 |
| 子请求 | Gateway 请求中的 `requests[]` 单项 |
| 子响应 | Gateway 响应中的 `responses[]` 单项 |
| PUT 上传 | 使用签名 URL 向对象存储上传二进制图片 |
| InterfaceCall | 一次配对后的标准接口调用记录 |
| TaskSnapshot | 某个 Dating 异步任务的统一快照 |
| Result Field | 最终结果中一个可定位的字段节点 |
| 确定性检查 | 仅依赖结构、枚举、计数、ID 和时间关系的固定规则 |
| 业务成功 | HTTP、Gateway 外层和子响应均成功 |
| 解析成功 | 日志 JSON 能完整提取并转换为结构化数据，不等同于业务成功 |

字段存在状态：

| 状态 | 定义 |
|---|---|
| `PRESENT` | 字段存在且具有非空值 |
| `NULL` | 字段存在且值为 `null` |
| `EMPTY_STRING` | 字段存在且值为 `""` |
| `EMPTY_ARRAY` | 字段存在且值为 `[]` |
| `EMPTY_OBJECT` | 字段存在且值为 `{}` |
| `MISSING` | 已知 Schema 预期字段不存在 |

规则结果状态：

| 状态 | 定义 |
|---|---|
| `PASS` | 已有充分证据且满足规则 |
| `FAIL` | 已有充分证据且违反明确契约 |
| `WARN` | 存在风险、语义待确认或非阻断性异常 |
| `UNKNOWN` | 日志不足，无法判断 |
| `NA` | 当前任务不适用 |

---

## 7. 总体产品流程

```text
用户粘贴或上传日志
→ 点击“解析日志”保留现有过滤能力
→ 点击“结构化接口分析”
→ POST /dating/analyze
→ 规范化日志行和时间戳
→ 识别 Gateway / PUT marker
→ 提取 JSON
→ 解包 Gateway 信封
→ 配对请求和响应
→ 生成 InterfaceCall[]
→ 按 task_id 聚合 TaskSnapshot
→ 根据 schema_version 选择结果整理器
→ 建立字段树和字段索引
→ 执行确定性检查
→ 返回结构化 JSON 和固定 Markdown 报告
→ 页面展示摘要、链路、任务时间线、字段和问题
```

整个分析过程必须在单次请求内完成，不启动后台任务，不访问外部网络。

---

## 8. 支持的日志格式

### 8.1 Gateway 请求

```text
2026-08-29 18:51:12,634 | INFO | utils.custom.http_client | Gateway 请求数据:
{
  "url": "https://.../dating/gateway/invoke",
  "headers": {...},
  "payload": {
    "comm": {...},
    "requests": [
      {
        "id": "req_0",
        "service_name": "tool.dating.DatingAssistantService",
        "method_name": "CreateReplyTask",
        "params": {...}
      }
    ]
  }
}
```

### 8.2 Gateway 响应

```text
2026-08-29 18:51:12,857 | INFO | utils.custom.http_client | Gateway 响应数据: HTTP 200 elapsed_ms=222.33
headers={...}
body={
  "code": 0,
  "message": "ok",
  "request_id": "gw_req_...",
  "trace_id": "trace_...",
  "responses": [
    {
      "id": "req_0",
      "success": true,
      "code": 0,
      "message": "ok",
      "data": {...}
    }
  ]
}
```

### 8.3 PUT 上传

```text
PUT 上传请求数据:
{
  "url": "https://...signed-url...",
  "headers": {...}
}

PUT 上传响应: HTTP 200 elapsed_ms=1543.22
headers={...}
```

### 8.4 Flow 步骤

```text
开始 Flow 步骤: flow=... step=create_reply (6/8)
完成 Flow 步骤: step=create_reply
因条件跳过 Flow 步骤: step=update_preferences
```

Flow 步骤用于展示测试脚本阶段，不作为业务接口成功的唯一依据。

### 8.5 首期识别的接口

#### DatingMediaService

- `GetMediaUploadConfig`
- `PrepareMediaUpload`
- `CompleteMediaUpload`

#### DatingAssistantService

- `GetUserPreferences`
- `CreateReplyTask`
- `GetTask`
- `GetTaskResult`
- `CreateAnalysisTask`
- `GetAnalysisTask`
- `GetAnalysisResult`

未知 method 仍进入通用 InterfaceCall，但不会参与 Dating 专属任务规则。

---

## 9. 通用 Gateway 解析规则

### 9.1 行规范化

每一行必须保留：

```json
{
  "line_no": 477,
  "raw": "原始日志行",
  "content": "去除日志前缀后的内容",
  "timestamp": "2026-08-29T18:51:12.634+08:00"
}
```

规范化只能移除已知 logger 前缀，不得修改 JSON 字符串内容。

### 9.2 JSON 提取

- 只从已识别 marker 后开始扫描 JSON。
- 同时支持 `{}` 和 `[]` 根节点。
- 使用括号平衡算法处理跨行对象和数组。
- 正确处理字符串中的 `{`、`}`、`[`、`]` 和转义字符。
- Gateway 响应必须跳过 `headers={...}`，读取 `body={...}` 作为业务响应。
- PUT 响应允许只有 headers、没有 body。
- 单个 JSON 块扫描上限为 100000 行。
- JSON 失败只影响当前记录，不阻止后续记录解析。
- 禁止扫描日志中的任意大括号并猜测接口，避免误解析普通文本。

### 9.3 Gateway 请求解包

从请求中提取：

- URL。
- comm 中允许展示的公共字段。
- client_request_id。
- `requests[].id`。
- service_name。
- method_name。
- params。
- 请求开始和结束行号。

每个 `requests[]` 子项生成独立的逻辑请求记录；同一个 HTTP Gateway 请求允许包含多个子请求。

### 9.4 Gateway 响应解包

分别保存：

1. HTTP 层
   - http_status。
   - elapsed_ms。
2. Gateway 外层
   - code。
   - message。
   - request_id。
   - trace_id。
3. Gateway 子响应
   - id。
   - success。
   - code。
   - message。
   - data。

HTTP 200 不代表业务成功。只要 Gateway 外层 code 非 0 或子响应失败，业务结果就不能标记为成功。

### 9.5 请求与响应配对

配对优先级：

1. 同一 Gateway HTTP 调用内，按 `requests[].id ↔ responses[].id` 配对。
2. 使用 client_request_id 和 method_name 辅助关联。
3. 使用日志时序和未关闭请求队列兜底。

禁止只按 `requests[]` 和 `responses[]` 数组下标配对。

配对失败时：

- 请求无响应：生成 `UNMATCHED_REQUEST` warning。
- 响应无请求：生成 `UNMATCHED_RESPONSE` warning。
- 多个候选：生成 `AMBIGUOUS_PAIRING` warning，并保留候选信息。

### 9.6 PUT 上传关联

PUT 请求自身通常不包含 asset_id。首期按以下证据关联：

1. 最近一个成功的 `PrepareMediaUpload` 响应。
2. PUT URL 去除查询参数后的对象路径。
3. 后续 `CompleteMediaUpload.params.asset_id`。
4. 时间顺序。

无法唯一关联时保留 PUT 调用，但将 `asset_id` 标记为未知，不猜测。

---

## 10. 标准 InterfaceCall 数据结构

```json
{
  "call_id": "call_0007",
  "gateway_exchange_id": "gateway_0007",
  "sequence": 7,
  "transport": "gateway",
  "service_name": "tool.dating.DatingAssistantService",
  "method_name": "CreateReplyTask",
  "request": {
    "timestamp": "2026-08-29T18:51:12.634+08:00",
    "line_start": 477,
    "line_end": 515,
    "client_request_id": "crid_1788000672634723888",
    "params": {
      "asset_ids": [
        "dating_media_c93f2385b50067579d9b14a28ec7ba32",
        "dating_media_6ae2a0b08fce432f9461936399ffaceb"
      ],
      "locale": "en-US"
    }
  },
  "response": {
    "timestamp": "2026-08-29T18:51:12.857+08:00",
    "line_start": 516,
    "line_end": 544,
    "http_status": 200,
    "elapsed_ms": 222.33,
    "gateway": {
      "code": 0,
      "message": "ok",
      "request_id": "gw_req_c1619ea2c5a23a1bb0e36293b6701d12",
      "trace_id": "trace_4f07cefac199c6434287f31ac2d29cff"
    },
    "sub_response": {
      "id": "req_0",
      "success": true,
      "code": 0,
      "message": "ok"
    },
    "data": {
      "task_id": "dating_task_147b21ac92063a1b24bbb8f8865e3bde",
      "task_type": "reply_generation",
      "status": "queued",
      "phase": "queued"
    }
  },
  "result_class": "success",
  "parse_status": "PARSED",
  "warnings": []
}
```

`transport` 枚举：

- `gateway`
- `object_storage_put`
- `unknown`

`result_class` 枚举：

- `success`
- `http_error`
- `gateway_error`
- `business_error`
- `no_response`
- `parse_error`
- `unknown`

### 10.1 Gateway 与逻辑调用计数口径

- `gateway_call_count`：Gateway 外层 HTTP 请求/响应交换数。
- `logical_interface_call_count`：展开 `requests[]` 后的逻辑子请求数。
- `upload_call_count`：对象存储 PUT 请求数。
- 当一个 Gateway 请求只包含一个子请求时，前两项相等。
- 当一个 Gateway 请求包含多个子请求时，`logical_interface_call_count` 大于 `gateway_call_count`。

### 10.2 接口统计结构

```json
{
  "service_name": "tool.dating.DatingAssistantService",
  "method_name": "GetAnalysisTask",
  "request_count": 21,
  "response_count": 21,
  "success_count": 21,
  "failure_count": 0,
  "unresponded_count": 0,
  "http_status_counts": {
    "200": 21
  },
  "result_class_counts": {
    "success": 21
  },
  "average_elapsed_ms": 191.38,
  "max_elapsed_ms": 254.28
}
```

统计按 `service_name + method_name` 分组。平均值只统计具有 `elapsed_ms` 的已配对响应。

---

## 11. Dating 任务聚合

### 11.1 task_id 来源

仅从以下已解析路径收集主任务 ID：

- Create 接口响应 `data.task_id`。
- Poll 接口请求 `params.task_id`。
- Poll 接口响应 `data.task_id`。
- Result 接口请求 `params.task_id`。
- Result 接口响应 `data.task_id`。

不得使用全文正则收集所有 `task_id`，避免把历史快照或嵌套文本中的 ID 当成当前任务。

### 11.2 单任务选择

- 未提供 task_id 且只识别到一个任务：自动选择。
- 未提供 task_id 且识别到多个任务：返回 `MULTIPLE_TASKS_FOUND`。
- 提供 task_id 且存在：只分析指定任务，同时保留公共上传调用。
- 提供 task_id 但不存在：返回 `TASK_NOT_FOUND`。
- 只有上传日志、没有任务：仍返回接口结构，但 `task_snapshot=null`。

首期不自动批量分析多个任务。

### 11.3 任务类型识别

| 创建接口 | 轮询接口 | 结果接口 | task_type |
|---|---|---|---|
| `CreateReplyTask` | `GetTask` | `GetTaskResult` | `reply_generation` |
| `CreateAnalysisTask` | `GetAnalysisTask` | `GetAnalysisResult` | `relationship_analysis` |

当接口组合和响应 `task_type` 不一致时，输出 `TASK_TYPE_MISMATCH`。

### 11.4 任务状态样本

每次 Poll 响应转换为：

```json
{
  "call_id": "call_0008",
  "timestamp": "2026-08-29T18:51:13.110+08:00",
  "status": "queued",
  "phase": "queued",
  "progress_percent": 5,
  "retryable": false,
  "error_code": "",
  "create_time": 1788000673651,
  "completed_time": null,
  "expire_time": 1788087073651,
  "line_start": 581,
  "line_end": 613
}
```

不得对重复状态去重。重复轮询本身是诊断信息。

### 11.5 任务统一快照

```json
{
  "task_id": "dating_task_147b21ac92063a1b24bbb8f8865e3bde",
  "task_type": "reply_generation",
  "schema_version": "dating.reply_generation.v1",
  "create_call_id": "call_0007",
  "poll_call_ids": ["call_0008"],
  "result_call_id": "call_0019",
  "input_assets": [],
  "lifecycle": {
    "initial_status": "queued",
    "final_status": "succeeded",
    "final_phase": "finalizing",
    "final_progress_percent": 100,
    "poll_count": 11,
    "duration_ms": 11781,
    "retryable": false,
    "error_code": ""
  },
  "progress_diagnostics": {
    "distinct_progress_values": [5, 30, 100],
    "unchanged_poll_count": 8,
    "longest_unchanged_progress": 30
  },
  "status_samples": [],
  "result_payload": {},
  "result_sections": [],
  "result_fields": [],
  "field_health": {},
  "checks": [],
  "warnings": []
}
```

`duration_ms` 优先使用 `completed_time - create_time`；缺失时使用首个 Create 响应到终态 Poll 响应的日志时间差。

---

## 12. 上传资源结构

```json
{
  "asset_id": "dating_media_c93f2385b50067579d9b14a28ec7ba32",
  "content_type": "image/png",
  "size_bytes": 93468,
  "purpose": "chat_screenshot",
  "prepare_status": "pending",
  "put_http_status": 200,
  "complete_status": "uploaded",
  "prepare_call_id": "call_0003",
  "put_call_id": "upload_0001",
  "complete_call_id": "call_0004",
  "used_by_task": true,
  "warnings": []
}
```

上传链路状态：

- `complete`：Prepare、PUT、Complete 均成功。
- `prepare_only`：只有 Prepare。
- `put_failed`：PUT 非 2xx。
- `complete_failed`：PUT 成功但 Complete 失败。
- `orphan_put`：PUT 无法关联 asset_id。
- `unknown`：日志不足。

---

## 13. 最终结果字段模型

### 13.1 同时保留字段树和字段索引

响应必须同时包含：

- `result_payload`：脱敏后的原始嵌套结果。
- `result_sections`：按业务语义分组的展示数据。
- `result_fields`：所有节点的扁平字段索引。

禁止只保存扁平字段。数组对象的父子关系必须在 `result_payload` 中保留。

### 13.2 Result Field

```json
{
  "path": "result.overview.dashboard.effort.you_score",
  "parent_path": "result.overview.dashboard.effort",
  "key": "you_score",
  "array_index": null,
  "label": "你的投入度",
  "value": null,
  "value_type": "null",
  "presence": "NULL",
  "schema_known": true,
  "source": {
    "method": "GetAnalysisResult",
    "call_id": "call_0030",
    "line_start": 2140,
    "line_end": 2140,
    "location_precision": "exact"
  }
}
```

字段定位允许两种精度：

- `exact`：能够定位到该 JSON path 对应的键和值行范围。
- `block`：只能定位到所属响应 body 的完整行范围。

解析器必须保证每个字段至少具有 `block` 级定位。对于 `MISSING` 字段和无法稳定区分的重复 key，使用 `block`，不得伪造精确行号。

### 13.3 字段遍历规则

- 对对象递归遍历全部 key。
- 对数组保留索引，例如 `roles[0].replies[2].text`。
- 对容器节点也生成字段项，以支持显示数组长度和对象 key 数。
- 未知字段必须保留，`schema_known=false`。
- 字段顺序跟随响应原始顺序。
- 最大递归深度 50；超过时生成 `MAX_FIELD_DEPTH_REACHED`。
- 单个结果最多 20000 个字段节点；超过时生成 `MAX_FIELD_COUNT_REACHED` 并停止继续展开。

### 13.4 字段健康摘要

```json
{
  "total_field_count": 84,
  "present_count": 77,
  "null_count": 3,
  "empty_string_count": 0,
  "empty_array_count": 4,
  "empty_object_count": 0,
  "missing_count": 0,
  "unknown_schema_field_count": 0
}
```

字段健康摘要只描述事实，不等同于任务失败结论。

---

## 14. Reply Schema 整理

### 14.1 支持版本

```text
dating.reply_generation.v1
```

### 14.2 业务分组

| 分组 | JSON path |
|---|---|
| 上下文 | `result.context` |
| 综合分析 | `result.comprehensive_analysis` |
| 当前情况 | `result.whats_happening` |
| 推荐角色 | `result.roles` |
| 人物关联 | `result.association` |
| 降级 | `result.degradation` |
| 警告 | `result.warnings` |

### 14.3 Reply 摘要

```json
{
  "conversation_stage": "boundary",
  "moment_type": "rejection",
  "reply_state": "user_waiting",
  "requested_intent": "",
  "effective_goal": "respect_boundary",
  "signal_count": 1,
  "role_count": 1,
  "reply_count": 4,
  "top_pick_reply_id": "reply_1",
  "person_history_used": false,
  "is_degraded": false,
  "warning_count": 1
}
```

### 14.4 Reply 展示要求

- Roles 按 rank 排序。
- 每个 Role 展示 role_id、role_name、selection_rule_id、selection_reasons 和 coach_note。
- Replies 使用表格展示 reply_id、text、is_top_pick。
- top_pick 和 alternatives 单独展示其引用关系。
- 不把文案重复视为解析错误。
- 原始英文文本必须完整保留，不进行翻译或改写。

---

## 15. Analysis Schema 整理

### 15.1 支持版本

```text
dating.relationship_analysis.v1
```

### 15.2 业务分组

| 分组 | JSON path |
|---|---|
| 分析范围 | `result.analysis_scope` |
| 总览 | `result.overview` |
| Dashboard | `result.overview.dashboard` |
| 聊天信号 | `result.chat_signals` |
| 关键事件 | `result.key_events` |
| 警告 | `result.warnings` |

### 15.3 Analysis 摘要

```json
{
  "relationship_stage": "ENDED",
  "current_state": "SETTING_BOUNDARIES",
  "reliability_level": "VERY_HIGH",
  "uploaded_asset_count": 3,
  "valid_asset_count": 3,
  "ignored_asset_count": 0,
  "analyzed_message_count": 38,
  "positive_signal_count": 3,
  "watch_signal_count": 1,
  "risk_signal_count": 0,
  "turning_point_count": 3,
  "warning_count": 0
}
```

### 15.4 Analysis 展示要求

- Overview 文案保持原文。
- next_steps 分 action、communication、observation 三项展示。
- Dashboard 中 `null` 和空数组必须显示明确空态，不隐藏整个模块。
- Signals 展示 signal_id、text 和 evidence_message_ids。
- Key Events 按 turning_points、hidden_meanings、did_well、could_improve 分组。
- 不使用规则判断自然语言文案是否正确或矛盾。

---

## 16. 未知 Schema 兼容

当 `schema_version` 不是已知版本时：

- `supported=true`，只要接口格式和任务类型能够识别。
- `schema_status=UNKNOWN_SCHEMA`。
- 完整生成通用字段树和字段索引。
- 不生成 Reply/Analysis 业务摘要。
- Schema 专属规则返回 `NA`。
- 输出 `UNKNOWN_SCHEMA_VERSION` warning。
- 不丢弃未知字段。

外层 `data.schema_version` 缺失但内层 `result.schema_version` 存在时，使用内层版本并输出 `OUTER_SCHEMA_VERSION_MISSING`。

---

## 17. 确定性检查规则

### 17.1 通用规则

| Rule ID | 优先级 | 规则 |
|---|---:|---|
| `PARSE-001` | P0 | 已识别请求或响应 JSON 必须可解析 |
| `PAIR-001` | P0 | 每个 Gateway 子请求应有唯一子响应 |
| `HTTP-001` | P0 | HTTP 状态应为 2xx |
| `GATEWAY-001` | P0 | Gateway 外层 code 应为 0 |
| `SUBRESP-001` | P0 | 子响应 success=true 且 code=0 |
| `TRACE-001` | P2 | Gateway 响应应有 request_id 和 trace_id |
| `UPLOAD-001` | P0 | 任务使用的 asset 应完成 Prepare、PUT、Complete |
| `UPLOAD-002` | P1 | 上传 size/content_type 在 Prepare 与 Complete 中应一致 |

### 17.2 任务规则

| Rule ID | 优先级 | 规则 |
|---|---:|---|
| `TASK-001` | P0 | Create、Poll、Result task_id 一致 |
| `TASK-002` | P0 | 接口组合和 task_type 一致 |
| `TASK-003` | P0 | status 不发生非法回退 |
| `TASK-004` | P1 | progress_percent 不下降 |
| `TASK-005` | P0 | succeeded 时 progress_percent=100 |
| `TASK-006` | P0 | failed 时应有 error_code 或可定位错误信息 |
| `TASK-007` | P1 | create_time ≤ result create_time ≤ completed_time ≤ expire_time |
| `TASK-008` | P1 | 成功任务应存在对应结果接口 |
| `TASK-009` | P2 | succeeded 但 phase=finalizing 时输出 WARN，不直接 FAIL |
| `TASK-010` | P2 | processing 状态下进度连续 5 次以上不变时输出 WARN，并保留停滞次数 |

### 17.3 Result 通用规则

| Rule ID | 优先级 | 规则 |
|---|---:|---|
| `RESULT-001` | P0 | 结果接口 task_id 与任务一致 |
| `RESULT-002` | P0 | 外层和内层 schema_version 一致 |
| `RESULT-003` | P1 | result_id 非空 |
| `RESULT-004` | P1 | 已知 Schema 必填字段存在 |
| `RESULT-005` | P2 | 汇总 null、空字符串、空数组和空对象 |
| `RESULT-006` | P2 | 未知字段保留并标记，不直接 FAIL |

### 17.4 Reply 规则

| Rule ID | 优先级 | 规则 |
|---|---:|---|
| `REPLY-001` | P0 | 每个 reply_id 唯一 |
| `REPLY-002` | P0 | 每个 Role 最多一个 is_top_pick=true |
| `REPLY-003` | P0 | top_pick.reply_id 必须存在于 replies[] |
| `REPLY-004` | P1 | top_pick 文案与对应 reply 文案一致 |
| `REPLY-005` | P1 | alternatives 与非 Top Pick replies 一致 |
| `REPLY-006` | P1 | role rank 不重复且从小到大可排序 |
| `REPLY-007` | P1 | warnings 含降级项但 is_degraded=false 时输出 WARN |
| `REPLY-008` | P2 | person_history_used=false 时允许 person_id=null |

### 17.5 Analysis 规则

| Rule ID | 优先级 | 规则 |
|---|---:|---|
| `ANALYSIS-001` | P0 | valid_asset_count + ignored_asset_count = uploaded_asset_count |
| `ANALYSIS-002` | P0 | analyzed_message_count ≤ valid_message_count |
| `ANALYSIS-003` | P0 | user + other 消息数等于 analyzed_message_count |
| `ANALYSIS-004` | P1 | signal_id 在同一类型数组中唯一 |
| `ANALYSIS-005` | P1 | event_id 在 key_events 中唯一 |
| `ANALYSIS-006` | P1 | Signal/Event 的 evidence_message_ids 非空 |
| `ANALYSIS-007` | P2 | effort、match_degree、keywords 空值单独汇总，不直接 FAIL |
| `ANALYSIS-008` | P2 | warnings 数组单独汇总 |

### 17.6 明确禁止的规则

首期不得使用固定规则判断：

- 英文分析内容是否符合真实关系。
- 某段回复是否足够礼貌。
- `VERY_HIGH` 的自然语言结论是否合理。
- 某个 Positive Signal 在情感上是否“正向”。
- 文案是否由模型幻觉产生。

这些属于语义分析，必须等未来明确启用 LLM 后另立需求。

---

## 18. Rule Result 数据结构

```json
{
  "rule_id": "REPLY-007",
  "priority": "P1",
  "outcome": "WARN",
  "title": "降级状态与警告一致性",
  "actual": {
    "degradation.is_degraded": false,
    "warnings": ["SAFETY_DEGRADED"]
  },
  "expected": "warning 表示结果降级时，degradation 应提供一致状态或明确区分降级范围",
  "evidence": [
    {
      "method": "GetTaskResult",
      "json_path": "responses[0].data.result.degradation.is_degraded",
      "value": false,
      "line_start": 1423,
      "line_end": 1425
    },
    {
      "method": "GetTaskResult",
      "json_path": "responses[0].data.result.warnings",
      "value": ["SAFETY_DEGRADED"],
      "line_start": 1427,
      "line_end": 1429
    }
  ]
}
```

任何 `FAIL` 或 `WARN` 都必须包含 evidence；没有证据时只能返回 `UNKNOWN`。

---

## 19. 后端分析接口

### 19.1 Endpoint

```text
POST /dating/analyze
Content-Type: application/json
```

部署在 base path 时必须继续使用 Flask Blueprint，例如：

```text
/log-tool/dating/analyze
```

### 19.2 请求

```json
{
  "log_text": "完整日志文本",
  "task_id": null
}
```

字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `log_text` | 是 | 完整日志，UTF-8，最大 10 MiB |
| `task_id` | 否 | 多任务日志中选择单个任务 |

首期不提供规则开关、Schema 覆盖或 AI 参数。

### 19.3 成功响应

```json
{
  "analyzer_version": "dating-structured-v1",
  "parser_version": "gateway-log-v1",
  "ruleset_version": "2026-08-29",
  "supported": true,
  "detected_domain": "dating",
  "verdict": "WARNINGS_FOUND",
  "selection_error": null,
  "task_ids": [
    "dating_task_147b21ac92063a1b24bbb8f8865e3bde"
  ],
  "summary": {
    "gateway_call_count": 19,
    "logical_interface_call_count": 19,
    "upload_call_count": 2,
    "http_error_count": 0,
    "gateway_error_count": 0,
    "business_error_count": 0,
    "unmatched_request_count": 0,
    "unmatched_response_count": 0,
    "parse_warning_count": 0,
    "task_count": 1,
    "result_count": 1,
    "check_fail_count": 0,
    "check_warn_count": 1,
    "check_unknown_count": 0
  },
  "interface_statistics": [],
  "flow_steps": [],
  "calls": [],
  "task_snapshot": {},
  "checks": [],
  "parse_warnings": [],
  "report_markdown": "# Dating 结构化接口日志分析..."
}
```

`verdict` 计算规则：

| verdict | 条件 |
|---|---|
| `ISSUES_FOUND` | 至少一个检查结果为 FAIL |
| `WARNINGS_FOUND` | 无 FAIL，至少一个 WARN |
| `INCOMPLETE_LOG` | 无 FAIL/WARN，但关键检查因日志不足为 UNKNOWN |
| `NO_ISSUES` | 无 FAIL/WARN，关键检查均可判断 |

字段空值统计和 P2 诊断信息本身不改变 verdict，除非对应明确规则产生 WARN/FAIL。

### 19.4 HTTP 状态码

| HTTP | error_code | 场景 |
|---:|---|---|
| 200 | 无 | 解析成功；允许 checks 中存在 FAIL/WARN |
| 400 | `EMPTY_LOG` | log_text 为空 |
| 400 | `INVALID_REQUEST` | 请求体类型或字段类型错误 |
| 413 | `LOG_TOO_LARGE` | 日志超过 10 MiB |
| 422 | `UNSUPPORTED_LOG` | 未识别 Dating Gateway/PUT 日志 |
| 422 | `MULTIPLE_TASKS_FOUND` | 多任务但未指定 task_id |
| 422 | `TASK_NOT_FOUND` | 指定 task_id 不存在 |
| 503 | `ANALYZER_DISABLED` | Dating 结构化分析开关关闭 |
| 500 | `ANALYSIS_INTERNAL_ERROR` | 未处理内部异常 |

业务检查失败不返回 HTTP 4xx/5xx。分析接口本身成功时始终返回 200。

### 19.5 错误响应

```json
{
  "error_code": "MULTIPLE_TASKS_FOUND",
  "message": "日志包含多个 Dating 任务，请指定 task_id",
  "task_ids": ["dating_task_a", "dating_task_b"]
}
```

### 19.6 安全接入

- 复用现有 CSRF 校验。
- 复用现有平台资源访问校验。
- 复用现有审计日志。
- 分析结果响应前执行统一脱敏。
- 后端异常响应不得包含堆栈和原始日志。

---

## 20. 页面需求

### 20.1 入口

现有工具栏新增按钮：

```text
[解析日志] [分析检索链路] [结构化接口分析]
```

- “分析检索链路”继续对应 People Insight。
- “结构化接口分析”对应 Dating 确定性分析。
- 两个入口互不覆盖。

### 20.2 分析中状态

- 点击后按钮 disabled。
- 状态显示“正在解析接口和结果字段…”。
- 请求完成后恢复按钮。
- 分析失败时显示 error_code 和可操作提示。

### 20.3 页面区块

#### A. 总体摘要

展示：

- 任务类型。
- task_id。
- result_id。
- schema_version。
- 最终状态。
- 任务耗时。
- Gateway 调用数。
- PUT 上传数。
- 图片数。
- 轮询次数。
- HTTP/业务错误数。
- FAIL/WARN 数。

#### B. 接口执行链路

表格字段：

| 列 | 内容 |
|---|---|
| # | sequence |
| 时间 | 请求时间 |
| Service | service_name |
| Method | method_name |
| HTTP | http_status |
| Gateway | 外层 code |
| Business | 子响应 success/code |
| 耗时 | elapsed_ms |
| 任务/资源 | task_id 或 asset_id |
| 结果 | result_class |
| 行号 | 请求/响应行范围 |

点击一行展开：

- 请求 params。
- Gateway envelope。
- 子响应 data。
- warnings。

#### C. 上传链路

每个 asset 展示：

```text
Prepare pending → PUT 200 → Complete uploaded → Used by Task
```

#### D. 任务状态时间线

展示每次 Poll，不合并重复项：

```text
queued 5%
processing/analyzing 30%
...
succeeded/finalizing 100%
```

另显示：

- poll_count。
- distinct_progress_values。
- unchanged_poll_count。
- duration_ms。

#### E. 最终结果

提供两个视图：

1. 业务分组视图。
2. 原始字段树视图。

业务分组视图根据 Schema 展示 Reply 或 Analysis 区块；未知 Schema 只显示字段树。

#### F. 字段索引

表格字段：

| Path | Type | Presence | Value | Source |
|---|---|---|---|---|

筛选项：

- 全部。
- 有值。
- Null。
- 空字符串。
- 空数组。
- 空对象。
- Missing。
- 未知 Schema 字段。

支持按 path 和 value 搜索。

#### G. 一致性检查

按以下顺序展示：

```text
FAIL → WARN → UNKNOWN → PASS → NA
```

每项显示 rule_id、实际值、期望值、证据 path 和行号。

#### H. 固定报告

展示可复制 Markdown，内容由确定性模板生成，不包含 AI 章节。

### 20.4 原日志定位

点击调用或字段行号后：

- 滚动到原始日志对应位置。
- 高亮目标行范围。
- 不改变当前 method 筛选条件；若目标行被筛选隐藏，提示用户切换到“全部接口”。

---

## 21. 固定 Markdown 报告

报告结构固定为：

```markdown
# Dating 结构化接口日志分析

## 总体结论
## 任务与结果摘要
## 接口执行链路
## 上传资源
## 任务状态时间线
## 最终结果字段
## Null 与空值
## 已确认正常
## 已确认异常
## 需要确认
## 日志不足
```

报告只允许使用结构化数据和固定模板生成。

不得出现：

- “AI 说明”。
- 模型名称。
- 推测性根因。
- 对自然语言结果的主观评价。

---

## 22. 导出需求

新增导出类型：

| export_type | 文件前缀 | 后缀 |
|---|---|---|
| `dating_analysis_report` | `dating_structured_analysis` | `.md` |
| `dating_analysis_json` | `dating_structured_analysis` | `.json` |

JSON 导出内容必须与接口返回的脱敏结构一致，不包含：

- 原始 auth_token。
- 完整签名 URL 查询参数。
- Authorization/Cookie。
- 原始二进制或 Base64 图片。

---

## 23. 脱敏规则

### 23.1 必须脱敏

- `auth_token`。
- `authorization`。
- `cookie`、`set-cookie`。
- API key、secret、session token。
- 签名上传 URL 查询参数。
- Base64 图片和超长二进制文本。

### 23.2 保留字段

为保证接口分析可用，以下字段允许保留：

- method_name。
- service_name。
- task_id。
- result_id。
- asset_id。
- client_request_id。
- Gateway request_id、trace_id。
- code、message、status、phase。
- 业务结果文本。
- 计数、枚举、时间戳和耗时。

### 23.3 签名 URL

```text
输入：https://host/path/file.png?q-sign-algorithm=...&q-signature=...
输出：https://host/path/file.png?[REDACTED]
```

对象路径保留，用于关联上传；查询参数整体移除。

### 23.4 响应大小限制

- 单个自由文本字段最多返回 20000 字符。
- 超限时保留前 20000 字符，并标记 `value_truncated=true`。
- 原始日志只在当前请求内存中使用，不持久化。

---

## 24. 错误处理与降级

### 24.1 局部 JSON 解析失败

- 保留其他已解析调用。
- 当前记录 parse_status=`PARSE_ERROR`。
- 生成包含行号的 warning。
- 依赖该记录的检查返回 `UNKNOWN`。

### 24.2 缺少响应

- 调用 result_class=`no_response`。
- 不猜测 HTTP 状态和业务结果。
- 任务可能因此无法确定终态。

### 24.3 任务未完成

- final_status 使用最后一次已知状态。
- `terminal=false`。
- 没有结果接口时 RESULT 规则返回 UNKNOWN。
- 页面显示“任务未到终态或日志截断”。

### 24.4 未知字段

- 正常保留。
- 不阻断分析。
- 标记 schema_known=false。

### 24.5 分析器内部异常

- HTTP 500。
- error_code=`ANALYSIS_INTERNAL_ERROR`。
- 服务端记录异常堆栈。
- 客户端只显示安全错误信息。

---

## 25. 非功能需求

### 25.1 性能

- 10 MiB 以内日志的后端结构化分析目标时间 ≤ 2 秒，不含浏览器渲染。
- 两份黄金日志单次分析目标时间 ≤ 500 ms。
- 算法应为近似 O(n)，不得针对每个字段重复全文扫描。
- 页面首次只渲染摘要和可见区块；大字段树按展开状态渲染。

### 25.2 确定性

- 相同日志、相同 analyzer/ruleset 版本必须产生相同结构结果。
- 禁止使用随机 ID；call_id 根据解析顺序生成。
- 禁止调用系统时间参与业务检查，分析生成时间除外。

### 25.3 兼容性

- 不改变现有 `/people-search/analyze` 契约。
- 不改变现有日志过滤、统计、复制和导出默认行为。
- 未启用 Dating 分析器时页面其他功能正常。
- 新解析器支持 macOS 本地运行和现有 Docker 部署。

### 25.4 可维护性

- 通用 Gateway 解析不得依赖 Dating 字段。
- Dating 适配器不得修改原始日志文本。
- 确定性规则必须有唯一 rule_id 和测试。
- Schema 字段表集中维护，不能散落在前端模板中。
- 关键解析和业务规则使用中文注释说明原因、边界和失败策略。

---

## 26. 推荐实现边界

### 26.1 模块职责

```text
log_filter_tool/
├── gateway_log_parser.py
│   ├── 日志行规范化
│   ├── JSON 平衡扫描
│   ├── Gateway/PUT marker 识别
│   ├── Gateway 信封解包
│   └── 请求响应配对
├── dating_log_analyzer.py
│   ├── task_id 选择
│   ├── 上传资源聚合
│   ├── Reply/Analysis 任务聚合
│   ├── Schema 字段树和字段索引
│   └── 结构化摘要
├── dating_log_rules.py
│   ├── 确定性检查
│   └── Markdown 报告
├── app.py
│   └── /dating/analyze 与导出接入
└── templates/index.html
    └── Dating 分析结果展示
```

### 26.2 通用解析复用策略

现有 `people_search_analyzer.py` 中已经存在成熟的日志规范化、JSON 平衡扫描和 Gateway 解包思路。

V5 采用以下确定方案：

1. 将与业务无关的行规范化、JSON 平衡扫描和基础 Gateway 解包原语抽到 `gateway_log_parser.py`。
2. `people_search_analyzer.py` 通过兼容导入继续使用公共原语；其对外函数、SUPPORTED_METHODS、任务快照和规则契约保持不变。
3. Dating 在公共原语之上实现新的 Gateway/PUT marker、配对和领域聚合逻辑。
4. 不在本需求中重写 People Insight 任务快照和规则。
5. Dating 模块不得依赖 People 领域常量、SUPPORTED_METHODS 或规则函数。

公共原语抽取必须先由现有 People 测试锁定行为，抽取后再运行 People 全量回归；若回归失败，必须修复兼容性后才能继续 Dating 页面接入，不能以保留两套重复解析实现作为最终交付。

### 26.3 配置

新增：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `DATING_STRUCTURED_ANALYZER_ENABLED` | `true` | Dating 分析总开关 |
| `DATING_STRUCTURED_MAX_LOG_BYTES` | `10485760` | 最大日志大小 |

不得新增任何 LLM endpoint、model 或 API key 配置。

---

## 27. 测试设计

### 27.1 黄金夹具

在 `tests/fixtures/dating/` 中保存两份脱敏夹具：

- `reply_generation_multi_image_success.log`
- `relationship_analysis_multi_image_success.log`

夹具只允许做稳定脱敏，不允许手工删减关键接口或结果字段。

### 27.2 通用解析单元测试

- Gateway 请求 JSON 提取。
- Gateway 响应跳过 headers 并读取 body。
- 字符串内大括号不破坏扫描。
- 嵌套数组和对象。
- 一个 Gateway 请求包含多个子请求。
- `requests[]` 与 `responses[]` 顺序不同但 id 可配对。
- HTTP 200、Gateway 失败。
- HTTP 200、子响应失败。
- PUT 有响应 body 和无响应 body。
- JSON 截断。
- 请求无响应。
- 响应无请求。
- 签名 URL 脱敏。

### 27.3 Dating 聚合测试

- Reply 创建、轮询、结果聚合。
- Analysis 创建、轮询、结果聚合。
- task_id 一致。
- task_type 不一致。
- 多任务要求显式选择。
- 上传资源与 task asset_ids 关联。
- 未完成任务。
- failed 任务。
- 未知 Schema 兜底。
- 字段存在状态分类。
- 字段树保留数组父子关系。

### 27.4 规则测试

- Reply top_pick 一致和不一致。
- Reply alternatives 一致和不一致。
- 重复 reply_id。
- warnings 与 degradation 风险提示。
- Analysis asset 计数一致和不一致。
- Analysis 消息计数一致和不一致。
- 重复 signal_id/event_id。
- evidence_message_ids 为空。
- progress 倒退。
- succeeded 但进度非 100。
- 时间顺序错误。
- 日志不足返回 UNKNOWN。

### 27.5 Flask 集成测试

- 成功响应。
- EMPTY_LOG。
- INVALID_REQUEST。
- LOG_TOO_LARGE。
- UNSUPPORTED_LOG。
- MULTIPLE_TASKS_FOUND。
- TASK_NOT_FOUND。
- 分析器开关关闭。
- base path 路由正确。
- CSRF 和平台权限复用。
- 响应中无 auth_token 和签名参数。

### 27.6 前端测试

- Dating 按钮状态变化。
- 摘要卡片展示。
- 接口表格展开。
- 状态时间线不合并重复轮询。
- Reply 分组展示。
- Analysis 分组展示。
- Null/空值筛选。
- 检查项排序。
- 行号跳转。
- Markdown/JSON 导出。
- 错误提示。

### 27.7 回归测试

- `tests/test_log_filter.py` 全部通过。
- 所有 `test_people_search_*.py` 全部通过。
- 原有 `/people-search/analyze` 响应契约不变。
- 原有导出类型仍可用。

---

## 28. 黄金日志验收基线

### 28.1 Reply 黄金日志

必须得到：

```text
detected_domain = dating
task_type = reply_generation
schema_version = dating.reply_generation.v1
gateway_call_count = 19
upload_call_count = 2
http_error_count = 0
business_error_count = 0

task_id = dating_task_147b21ac92063a1b24bbb8f8865e3bde
result_id = dating_result_ac0e7b514cba0f21621223193f2cbc31
poll_count = 11
final_status = succeeded
final_phase = finalizing
final_progress_percent = 100
duration_ms = 11781

input_asset_count = 2
reply_count = 4
top_pick_reply_id = reply_1
conversation_stage = boundary
moment_type = rejection
effective_goal = respect_boundary
warnings = [SAFETY_DEGRADED]
```

状态样本计数：

```text
queued = 1
processing = 9
succeeded = 1
```

必须产生：

- Top Pick 一致性 PASS。
- Alternatives 一致性 PASS。
- warning 与 degradation 检查 WARN。
- `requested_intent` 分类为 EMPTY_STRING。
- `association.person_id` 分类为 NULL。
- `degradation.reason` 分类为 NULL。

### 28.2 Analysis 黄金日志

必须得到：

```text
detected_domain = dating
task_type = relationship_analysis
schema_version = dating.relationship_analysis.v1
gateway_call_count = 30
upload_call_count = 3
http_error_count = 0
business_error_count = 0

task_id = dating_task_0e872c9510861f0b21fa76a91076f733
result_id = dating_result_420614d6489334dccea7528a830da0d8
poll_count = 21
final_status = succeeded
final_phase = finalizing
final_progress_percent = 100
duration_ms = 23337

uploaded_asset_count = 3
valid_asset_count = 3
ignored_asset_count = 0
valid_message_count = 38
analyzed_message_count = 38
message_counts.user = 19
message_counts.other = 19

relationship_stage = ENDED
current_state = SETTING_BOUNDARIES
reliability_level = VERY_HIGH
positive_signal_count = 3
watch_signal_count = 1
risk_signal_count = 0
turning_point_count = 3
warnings = []
```

状态样本计数：

```text
queued = 1
processing = 19
succeeded = 1
```

必须产生：

- Asset 计数一致性 PASS。
- 消息计数一致性 PASS。
- `effort.you_score` 分类为 NULL。
- `effort.them_score` 分类为 NULL。
- `match_degree.score` 分类为 NULL。
- `keywords.user_focus` 分类为 EMPTY_ARRAY。
- `keywords.other_focus` 分类为 EMPTY_ARRAY。
- `risk_signals` 分类为 EMPTY_ARRAY。
- `warnings` 分类为 EMPTY_ARRAY。

---

## 29. 验收用例

| AC ID | 验收内容 | 期望 |
|---|---|---|
| `AC-001` | Reply 黄金日志解析 | 19 Gateway、2 PUT、1 个任务 |
| `AC-002` | Analysis 黄金日志解析 | 30 Gateway、3 PUT、1 个任务 |
| `AC-003` | 三层成功状态 | HTTP/Gateway/SubResponse 分别展示 |
| `AC-004` | Reply 生命周期 | 11 次 Poll，终态 succeeded/100 |
| `AC-005` | Analysis 生命周期 | 21 次 Poll，终态 succeeded/100 |
| `AC-006` | Reply 字段 | context、roles、replies、top_pick 完整 |
| `AC-007` | Analysis 字段 | scope、overview、signals、events 完整 |
| `AC-008` | 空值分类 | null、空字符串、空数组分别统计 |
| `AC-009` | 未知字段 | 字段保留且 schema_known=false |
| `AC-010` | 未知 Schema | 通用字段树可展示，专属规则 NA |
| `AC-011` | 证据定位 | 调用、字段、检查项均有行号 |
| `AC-012` | 解析失败降级 | 其他调用继续解析，相关规则 UNKNOWN |
| `AC-013` | 敏感信息 | 响应和导出无 token、签名参数 |
| `AC-014` | 确定性 | 重复分析结果一致 |
| `AC-015` | 无外部依赖 | 分析期间无网络和 LLM 调用 |
| `AC-016` | People 回归 | People Insight 全量测试通过 |
| `AC-017` | 页面展示 | 摘要、链路、时间线、字段、规则可用 |
| `AC-018` | 导出 | Markdown 和 JSON 内容完整且脱敏 |

---

## 30. 开发实施阶段

### 阶段 0：契约和夹具

交付物：

- 两份脱敏黄金夹具。
- Gateway marker 和标准数据结构测试。
- Reply/Analysis 黄金期望值。

完成标准：

- 夹具不包含有效 token 或签名参数。
- 本 PRD 第 28 章所有期望值可由夹具验证。

### 阶段 1：通用 Gateway 解析器

交付物：

- 行规范化。
- JSON 扫描。
- Gateway/PUT marker 解析。
- Gateway 信封解包。
- 请求响应配对。
- 通用 InterfaceCall。

完成标准：

- 通用解析单元测试通过。
- 两份黄金日志调用数准确。

### 阶段 2：Dating 任务与结果聚合

交付物：

- 上传资源聚合。
- Reply TaskSnapshot。
- Analysis TaskSnapshot。
- Schema 识别。
- 字段树、字段索引和字段健康摘要。

完成标准：

- 第 28 章任务、计数和字段验收全部通过。

### 阶段 3：确定性规则与报告

交付物：

- 通用规则。
- Reply 规则。
- Analysis 规则。
- 固定 Markdown 报告。

完成标准：

- 每条 FAIL/WARN 有 evidence。
- 无自然语言语义判断规则。

### 阶段 4：Flask、页面和导出

交付物：

- `/dating/analyze`。
- 页面入口和结果面板。
- 原日志行号跳转。
- Markdown/JSON 导出。

完成标准：

- Flask 和前端测试通过。
- base path 下路由可用。

### 阶段 5：回归、部署与验收

交付物：

- 全量测试结果。
- Docker 镜像更新。
- 本地部署验证。
- 两份黄金日志页面验收截图或记录。

完成标准：

- AC-001 至 AC-018 全部通过。
- People Insight 和通用日志功能无回归。

---

## 31. 部署与回滚

### 31.1 部署

- Docker 构建必须包含新增 Python 模块。
- 默认启用 `DATING_STRUCTURED_ANALYZER_ENABLED=true`。
- 健康检查继续使用现有 `/health`。
- 部署后用两份黄金日志各执行一次页面分析。

### 31.2 回滚

优先使用配置回滚：

```text
DATING_STRUCTURED_ANALYZER_ENABLED=false
```

关闭后：

- `/dating/analyze` 返回 `ANALYZER_DISABLED`。
- 页面隐藏或禁用“结构化接口分析”。
- People Insight、日志过滤和导出继续工作。

若配置回滚不足，再回滚对应镜像版本。

---

## 32. 风险与控制

| 风险 | 影响 | 控制措施 |
|---|---|---|
| Gateway 日志格式变化 | 解析失败 | marker 宽容识别、局部失败、黄金夹具 |
| 多子请求乱序 | 错误配对 | 按 id 配对，时序只作兜底 |
| PUT 缺少 asset_id | 无法关联资源 | 对象路径、相邻 Prepare/Complete、未知态 |
| Schema 新增字段 | 页面漏字段 | 通用字段树保留未知字段 |
| Schema 版本升级 | 专属规则过期 | UNKNOWN_SCHEMA，不套用旧规则 |
| 大结果拖慢页面 | 渲染卡顿 | 字段上限、按需展开、搜索索引 |
| 敏感信息泄漏 | 安全风险 | 响应前统一脱敏、导出复用脱敏结果 |
| 公共解析抽取影响 People | 功能回归 | 保留契约、兼容导入、全量 People 测试 |
| 规则误报 | 测试判断错误 | 无证据不 FAIL，语义问题不规则化 |

---

## 33. Definition of Done

功能只有同时满足以下条件才可标记完成：

- [ ] 通用 Gateway 解析器完成并有单元测试。
- [ ] Reply 和 Analysis 黄金日志均准确解析。
- [ ] 两种 Schema 的所有叶子字段可检索。
- [ ] Null、空字符串、空数组、空对象和 Missing 可区分。
- [ ] 请求响应、上传资源和任务链路可定位。
- [ ] 确定性规则全部有测试。
- [ ] 每个 FAIL/WARN 有证据行号。
- [ ] `/dating/analyze` 契约和错误码完成。
- [ ] 页面摘要、链路、时间线、字段和检查面板完成。
- [ ] Markdown 和 JSON 导出完成。
- [ ] 响应和导出完成敏感字段脱敏。
- [ ] 不存在 LLM 调用、模型配置或 AI 文案。
- [ ] People Insight 与通用日志测试无回归。
- [ ] Docker 构建和本地部署验证通过。
- [ ] AC-001 至 AC-018 全部通过。

---

## 34. 已确认产品决策

1. 采用方案三：通用 Gateway 解析器 + Dating 领域适配器 + 确定性规则。
2. 首期只覆盖 Dating Reply 与 Analysis。
3. 首期不接入 LLM。
4. 首期不进行自然语言语义正确性判断。
5. 原始嵌套结果和扁平字段索引同时保留。
6. Null、空值和缺失必须分开表达。
7. HTTP、Gateway 和子响应状态必须分层表达。
8. 未知字段保留，未知 Schema 使用通用字段树降级。
9. 多任务日志首期要求显式指定 task_id。
10. 现有 People Insight 分析接口和页面行为不得改变。

---

**文档结束**
