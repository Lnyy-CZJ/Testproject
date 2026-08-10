# searchTool v1.3 MVP 照片检索执行线开发设计与开发计划

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | searchTool v1.3 MVP 照片检索执行线开发设计与开发计划 |
| 文档版本 | v1.0 |
| 编写日期 | 2026-08-10 |
| 依据 PRD | `docs/searchTool_v1.3_MVP_照片检索执行线PRD.md` |
| 接口依据 | `TruthyApi.py`、照片检索完整流程日志（均按脱敏结构使用） |
| 目标版本 | searchTool v1.3 MVP 增量版本 |
| 设计原则 | 不改变旧链路、不新增服务和数据库、顺序执行、安全失败、先测试后实现 |

## 2. 需求理解与成功标准

### 2.1 需求理解

当前 `FULL_NAME` 和 `FULL_NAME_SOCIAL` 直接从 `CreateIntentTask` 开始。
本次新增 `FULL_NAME_PHOTO`，在 Create 前增加以下前置链路：

```text
GetMediaUploadConfig
  → PrepareMediaUpload
  → PUT JPEG binary 到动态 COS URL
  → CompleteMediaUpload
  → CreateIntentTask（动态追加 PHOTO clue）
  → 现有 GetTask / Admin / List / Detail 链路
```

照片来自项目 `input/input_photos`，输入记录只保存相对路径。照片上传是
Query 级前置流程，不是 Candidate 级流程，也不属于无成本重处理。

### 2.2 可验证的成功标准

1. `FULL_NAME`、`FULL_NAME_SOCIAL` 的请求数量、顺序、参数和结果结构不变；
2. `FULL_NAME_PHOTO` 严格执行 Config → Prepare → PUT → Complete → Create；
3. Create 使用当前 Query 的 `media_asset_id`，且输入对象中不允许预置 PHOTO clue；
4. PUT 使用 Prepare 返回的完整签名 URL、`Content-Length`、`Content-Type` 和 JPEG 原始字节；
5. 上传任一步失败时不调用 Create，但 Run 继续处理后续 Query；
6. Raw、SQLite、results、failures 和人物日志中没有 binary、base64、完整签名 URL或认证数据；
7. Web Run、CLI、Query 重跑使用同一实现；
8. 历史导入和无成本重处理不会调用任何媒体接口；
9. 不新增服务、端口、数据库和前端上传页面；
10. 自动化测试、小批量真实 JPEG 和平台容器回归通过。

## 3. 样例接口与日志结论

### 3.1 已确认接口归属

三个媒体业务接口与现有 Search API 共用：

- `SEARCH_API_URL`；
- `SEARCH_HTTP_HEADERS_JSON`；
- `AUTH_TOKEN`、`DEVICE_ID`、`USER_ID`；
- 现有 `comm` 结构。

差异仅为 RPC `service_name`：

```text
tool.people_insight.MediaService
```

因此不新增媒体 Gateway URL 和认证配置。COS PUT 使用 Prepare 返回的动态 URL，
不得复用 Gateway Header 或认证信息。

### 3.2 GetMediaUploadConfig 契约

请求：

```json
{
  "service_name": "tool.people_insight.MediaService",
  "method_name": "GetMediaUploadConfig",
  "params": {}
}
```

成功数据路径：

```text
responses[0].data
```

已确认字段：

| 字段 | 类型 | 首版用途 |
| --- | --- | --- |
| `allowed_content_types` | array[string] | 必须包含 `image/jpeg` |
| `max_size_bytes` | integer | 上传大小上限，样例为 10,000,000，但代码不得固定该值 |
| `asset_ttl_seconds` | integer | Raw 审计，不参与首版调度 |
| `cache_expires_time` | integer(ms) | Raw 审计；首版仍按每个照片 Query 请求一次 Config |
| `config_cache_ttl_seconds` | integer | Raw 审计，后续可优化 Run 内缓存 |
| `config_version` | string | 保存到照片输入摘要，便于追溯 |
| `complete_retry.initial_delay_ms` | integer | Complete 重试初始等待 |
| `complete_retry.max_attempts` | integer | Complete 最大尝试次数 |
| `complete_retry.max_delay_ms` | integer | Complete 最大等待 |
| `face_detection_required` | boolean | 首版只接受 `false`；变为 `true` 时安全失败 |
| `strip_exif` | boolean | 作为上传前隐私校验策略 |
| `recommended_jpeg_quality` | number | 只记录，不自动压缩 |
| `recommended_max_width/height` | integer | 只记录，不自动缩放 |
| `upload_url_ttl_seconds` | integer | Raw 审计，Prepare 仍需校验具体过期时间 |

### 3.3 PrepareMediaUpload 契约

请求 params：

```json
{
  "client_request_id": "与当前请求关联的唯一 ID",
  "content_type": "image/jpeg",
  "size_bytes": 867067
}
```

RPC：

```text
service_name = tool.people_insight.MediaService
method_name  = PrepareMediaUpload
```

成功响应提取：

| 运行时字段 | 精确路径 | 校验 |
| --- | --- | --- |
| `media_asset_id` | `responses[0].data.media_asset_id` | 非空字符串 |
| `upload_url` | `responses[0].data.upload_url` | HTTPS、允许的 COS Host、签名未过期 |
| `upload_method` | `responses[0].data.upload_method` | 必须等于 `PUT` |
| `content_length` | `responses[0].data.upload_headers.Content-Length` | 正整数字符串且等于实际字节数 |
| `content_type` | `responses[0].data.upload_headers.Content-Type` | 必须等于 `image/jpeg` |
| `status` | `responses[0].data.status` | 必须等于 `pending` |
| `size_bytes` | `responses[0].data.size_bytes` | 必须等于实际字节数 |
| `max_size_bytes` | `responses[0].data.max_size_bytes` | 实际字节数不得超过 |
| `expires_time` | `responses[0].data.expires_time` | 当前时间必须早于该毫秒时间戳 |

### 3.4 COS PUT 契约

真实日志确认请求为：

```text
PUT <Prepare 返回的完整 upload_url>
Content-Length: <Prepare.upload_headers.Content-Length>
Content-Type: <Prepare.upload_headers.Content-Type>
Body: JPEG bytes
```

真实日志中的成功结果为：

```text
HTTP 200，响应 body 为空
```

实现要求：

- 将 Prepare 返回的 URL 原字符串交给 `requests`，不得自行拆分、拼接或再次 URL encode；
- 不手工修改签名 Query 参数，避免 `%3B` 被二次编码为 `%253B` 导致签名失效；
- PUT 使用独立 Session，避免把 Gateway Cookie 或默认认证带到 COS；
- Header 只显式传 Prepare 返回的 `Content-Length` 和 `Content-Type`；
- 首版以 HTTP 200 为正式成功状态；其他 2xx 是否支持需后端另行确认；
- 响应 body 不作为 JSON 解析。

### 3.5 CompleteMediaUpload 契约

请求：

```json
{
  "service_name": "tool.people_insight.MediaService",
  "method_name": "CompleteMediaUpload",
  "params": {
    "media_asset_id": "media_xxx"
  }
}
```

成功响应校验：

| 字段 | 路径 | 校验 |
| --- | --- | --- |
| `media_asset_id` | `responses[0].data.media_asset_id` | 必须与 Prepare 一致 |
| `content_type` | `responses[0].data.content_type` | 必须为 `image/jpeg` |
| `size_bytes` | `responses[0].data.size_bytes` | 必须与上传字节数一致 |
| `status` | `responses[0].data.status` | 必须为 `uploaded` |
| `uploaded_time` | `responses[0].data.uploaded_time` | 保存 Raw |
| `upload_expires_time` | `responses[0].data.upload_expires_time` | 保存 Raw |
| `expires_time` | `responses[0].data.expires_time` | 保存 Raw |

### 3.6 CreateIntentTask 契约

Complete 成功后，在输入 clues 的副本中追加：

```json
{
  "type": "PHOTO",
  "photo_query": {
    "media_asset_id": "media_xxx",
    "photo_type_hint": "face"
  }
}
```

其他 `FULL_NAME`、`SOCIAL_LINK`、`LOCATION` 和 `additional_details` 均原样保留。
`match_strategy` 继续由输入决定，本次不修改 `UNION` 等现有语义。

### 3.7 样例日志与当前系统顺序差异

样例日志的十步流程将 Debug、Cost 放在 Candidate Detail 后。当前 searchTool 已经按此前确认的
任务公共信息 PRD 实现为：

```text
GetTask 终态
  → 等待 1 秒
  → GetSearchTaskDebug
  → GetProviderCostSummary
  → ListTaskCandidates
  → Candidate Detail
```

本次设计只采用日志中已经验证的照片前置四步，不改变当前 Admin 顺序。最终照片链路为：

```text
PhotoValidation
  → GetMediaUploadConfig
  → PrepareMediaUpload
  → PutMediaBinary
  → CompleteMediaUpload
  → CreateIntentTask
  → GetTask 终态
  → 等待 1 秒
  → Debug
  → Cost
  → List
  → 全部 Detail
```

日志示例使用约 2 秒轮询，本项目仍使用 `POLL_INTERVAL_SECONDS`，默认 5 秒；不因样例改变。

## 4. 当前架构与复用能力

### 4.1 可直接复用

| 现有能力 | 复用方式 |
| --- | --- |
| `RunCoordinator` | 保持单线程，一个 Run 共用一个 `SearchClient` |
| `Config.from_env()` | 每个新 Run/Query 重跑读取最新 Secret，增加照片配置字段 |
| `SearchClient` | 复用统一 Gateway payload、响应校验和请求 Session |
| `process_one()` | 在现有 Create 前增加仅对照片 Query 生效的分支 |
| `FlowError` | 照片阶段失败携带 Raw 和安全错误继续走现有失败入库 |
| `build_raw_record()` | 记录四个照片阶段，不创建新 Raw 模型 |
| `RawCallback` | 继续写 `raw_records` |
| `QueryChainLogger` | 消费脱敏 Raw，逐请求记录照片链路 |
| `dataset_queries.metadata_json` | 保存 `photo_path`，不新增数据库列 |
| `failures` | 记录照片验证或上传失败 |
| `results.jsonl` | 向后兼容增加 `photo_input` 摘要 |
| `SUPPORTED_QUERY_STAGES` | 增加 `FULL_NAME_PHOTO` 后复用指标、筛选和对比结构 |
| Docker `/app/input` 挂载 | 直接读取 `/app/input/input_photos`，继续只读 |

### 4.2 当前需要补齐的能力

1. `SearchClient.call()` 当前固定使用 SearchService，需支持显式 `service_name`；
2. 当前 Client 没有安全的 binary PUT 方法；
3. `resolve_query_stage()` 只支持两个 Stage；
4. CLI `validate_input()` 会丢弃 `photo_path`；
5. Dataset 导入虽能将扩展字段放入 `metadata_json`，但执行和重跑没有读取该字段；
6. `analysis_service.SUPPORTED_QUERY_STAGES` 和 `web_app.QUERY_STAGES` 尚无照片 Stage；
7. `sanitize_raw()` 尚未专门处理 `upload_url` 和异常字符串中的签名 URL；
8. 测试中缺少可控 JPEG、媒体 RPC 和 PUT Session 夹具。

## 5. 核心实现设计

### 5.1 设计边界

- 不新建业务 Python 模块；
- 核心逻辑继续放在 `search_tool.py`；
- 不创建媒体表或修改 SQLite Schema；
- 不修改 Candidate、字段处理、指标算法和 ReportModel；
- Web 只扩展已有 Stage、导入和进度展示，不增加上传控件；
- 现有方法默认参数保持旧行为，避免批量修改调用方。

### 5.2 常量和轻量运行时对象

在 `search_tool.py` 增加：

```text
MEDIA_SERVICE_NAME = tool.people_insight.MediaService
PHOTO_QUERY_STAGE = FULL_NAME_PHOTO
PHOTO_CONTENT_TYPE = image/jpeg
PHOTO_UPLOAD_METHOD = PUT
```

使用一个普通字典保存当前 Query 的照片运行时上下文，不新增复杂类层次：

```json
{
  "photo_path": "input_photos/taylor_swift.jpg",
  "resolved_path": "仅内存使用的受控绝对路径",
  "content_type": "image/jpeg",
  "content_length": 867067,
  "sha256": "...",
  "config_version": "media_upload_v4_10mb",
  "media_asset_id": "media_xxx",
  "upload_status": "COMPLETED"
}
```

`resolved_path`、照片 bytes 和 `upload_url` 只在内存中存在，不能进入返回对象。

### 5.3 配置设计

在现有 `Config` 增加：

```dotenv
SEARCH_PHOTO_ENABLED=false
SEARCH_PHOTO_INPUT_DIR=input/input_photos
SEARCH_PHOTO_MAX_BYTES=
SEARCH_PHOTO_UPLOAD_HOST_SUFFIXES=.myqcloud.com
```

规则：

1. 照片开关默认关闭；
2. 普通 Query 不校验照片配置；
3. 照片目录相对路径从项目根目录解析，平台可显式设置 `/app/input/input_photos`；
4. `SEARCH_PHOTO_MAX_BYTES` 为空时以 Config 响应为准；非空时最终上限取本地值与接口值的较小者；
5. Host 后缀列表用于阻止动态 URL 指向任意主机；首版至少允许 `.myqcloud.com`；
6. PUT 只允许 HTTPS、无 userinfo、标准 HTTPS 端口和允许的 Host；
7. 环境变量继续高于 Secret 文件，Query 重跑仍读取最新 Search Token；
8. 不新增固定 `upload_url`、媒体 Token 或 COS Secret 配置。

### 5.4 SearchClient 改造

#### 5.4.1 Gateway 调用

将签名扩展为：

```python
call(method_name, params, service_name=SERVICE_NAME)
```

- 默认值仍为 `SearchService`，所有旧调用不改；
- 三个媒体 RPC 显式传 `MEDIA_SERVICE_NAME`；
- payload、HTTP Header、超时和业务信封校验继续复用现有实现；
- Raw 仍只记录业务 params，不记录完整 comm 和鉴权。

#### 5.4.2 COS PUT

在 `SearchClient` 内增加一个同步方法，例如：

```text
put_media_binary(upload_url, upload_headers, content_bytes)
```

职责：

- 使用独立 `media_upload_session`；
- 校验 URL 后按原字符串 PUT；
- 只设置签名要求的两个 Header；
- body 直接使用 bytes；
- 记录 `last_http_status` 和 `last_duration_ms`；
- HTTP 200 返回安全摘要，不读取为 JSON；
- 失败时抛出 `FlowError("PutMediaBinary", 安全错误)`；
- requests 异常中的 URL 必须先脱敏再进入错误消息。

为了测试，`SearchClient.__init__` 增加可选 `media_upload_session` 注入；生产默认创建新的
`requests.Session()`，不复用 Gateway/Admin Session。

### 5.5 本地照片校验

新增一个小型校验函数，职责保持单一：

1. `photo_path` 必须是非空字符串；
2. 输入必须以 `input_photos/` 为逻辑前缀，或在照片根目录下使用相对文件名；
3. 拒绝绝对路径、`..`、URL、目录和越界符号链接；
4. 扩展名为 `.jpg` / `.jpeg`；
5. 文件存在、可读且是普通文件；
6. 先使用 `stat()` 获取大小，不对超限文件执行完整读取；
7. Config 返回后按最终大小上限校验；
8. 读取不超过上限的文件 bytes；
9. 校验 JPEG SOI/EOI，并使用 Pillow 验证文件可解码；
10. 计算 SHA-256，供 Run 审计而不是身份判断。

`strip_exif=true` 的安全处理：

- 本需求不做裁剪、缩放和压缩；
- 为避免静默上传 GPS/设备信息，首版检测 JPEG EXIF；
- 如果 Config 要求去除 EXIF但照片仍带 EXIF，当前 Query 在 `PhotoValidation` 失败并提示测试人员先清理照片；
- 不在工具内重编码照片，避免像素、方向和 JPEG 质量变化影响照片检索结果；
- 后续若需要自动去 EXIF，应另行确认其对测试基准和图片哈希的影响。

该策略需要在 `requirements.txt` 增加 Pillow，用于可靠验证 JPEG 和检查 EXIF；不新增运行服务。

如果后端确认 `strip_exif` 表示服务端已处理而非客户端要求，可在阶段 0 删除 EXIF 拒绝规则，
但不得在未确认时忽略该安全字段。

### 5.6 媒体配置处理

每个 `FULL_NAME_PHOTO` Query 调用一次 Config，符合当前 PRD。首版不实现 Run 内缓存，原因是：

- Query 数量有限；
- 逻辑更简单；
- 避免处理 `cache_expires_time` 与本地时钟偏差；
- 保证每个上传使用当时有效的限制和 Complete 重试策略。

校验规则：

- `allowed_content_types` 必须包含 `image/jpeg`；
- `max_size_bytes` 为正整数；
- `face_detection_required` 必须为 `false`；
- Complete 重试参数必须为非负/正整数；
- 为防异常配置造成长时间阻塞，`max_attempts` 最多取 5，单次 delay 最多取 5000ms；
- `recommended_*`、TTL 和版本进入 Raw/结果摘要，不直接改变照片。

### 5.7 Prepare 处理

Prepare 的 `client_request_id` 由工具生成，并同时放在 comm 和 params；二者使用相同值。

响应必须一次性完成以下交叉校验：

```text
input bytes length
  == request.size_bytes
  == response.size_bytes
  == int(response.upload_headers.Content-Length)
  <= Config.max_size_bytes
  <= Prepare.max_size_bytes
```

同时校验：

- 请求、响应和 upload header MIME 均为 `image/jpeg`；
- `upload_method == PUT`；
- `status == pending`；
- `media_asset_id` 非空；
- `expires_time` 尚未过期；
- `upload_url` 通过 HTTPS 与 Host 白名单校验。

任一不一致都按 `PrepareMediaUpload` 契约错误失败，不尝试修正接口返回值。

### 5.8 PUT 处理

`process_one()` 不把 bytes 传入通用 `call_and_record()`，避免该函数误将二进制交给
`sanitize_raw()`。新增一个局部包装函数只记录安全摘要：

```json
{
  "photo_path": "input_photos/taylor_swift.jpg",
  "content_type": "image/jpeg",
  "content_length": 867067,
  "upload_url": "***SIGNED_UPLOAD_URL***",
  "binary_logged": false
}
```

PUT 成功 Raw response：

```json
{
  "status": "UPLOADED_TO_COS",
  "response_body_logged": false
}
```

首版 PUT 不自动重试。连接超时可能发生“服务端已收到但客户端未知”的状态，自动重放可能造成
不确定覆盖；用户可通过 Query 重跑重新 Prepare 一个资源。

### 5.9 Complete 处理与重试

Complete 使用 Config 返回的重试参数，并保持同一个 `media_asset_id`：

```text
attempt 1：立即调用
attempt 2+：initial_delay_ms × 2^(attempt-2)
delay 不超过 max_delay_ms
总尝试不超过 min(max_attempts, 5)
```

允许重试：

- 网络连接错误或读取超时；
- HTTP 408、429、5xx；
- 业务响应成功但 `data.status == pending`。

不允许重试：

- HTTP 400/401/403/404；
- 顶层/方法业务明确失败且未标记 pending；
- `media_asset_id`、size、MIME 不一致；
- 未知终态或 `status == failed`。

每次 Complete 尝试单独写 Raw，`sequence_no` 和 `attempt` 可追踪。成功条件固定为
`status == uploaded` 且关键字段与 Prepare 一致。

### 5.10 Create 参数构造

新增函数只负责返回 Create clues 副本：

```text
build_create_clues(item, media_asset_id=None)
```

- 普通 Query：返回现有 clues 的深拷贝；
- 照片 Query：确认无输入 PHOTO clue，再追加运行时 PHOTO；
- `photo_type_hint` 固定 `face`；
- 不修改 Dataset/CLI 原始对象；
- Create Raw 可以保留 `media_asset_id`，不得包含本地绝对路径或 upload URL。

## 6. process_one 执行流程

### 6.1 普通 Query

代码分支应尽量早返回原有路径：

```text
query_stage != FULL_NAME_PHOTO
  → 不读取照片配置
  → 不解析照片文件
  → 不创建 COS Session 请求
  → 原 Create 流程
```

### 6.2 照片 Query

在当前 `try` 和 QueryChainLogger 生命周期内执行：

1. `resolve_query_stage()` 返回 `FULL_NAME_PHOTO`；
2. 发出 `PhotoValidation` 进度；
3. 校验受控照片路径和文件基础信息；
4. 调用 Config 并记录 Raw；
5. 按 Config 完成大小、MIME、EXIF 和 JPEG 校验；
6. 调用 Prepare 并记录脱敏 Raw；
7. 提取并校验上传参数；
8. PUT bytes 并记录安全 Raw 摘要；
9. 按 Config 策略调用 Complete；
10. 构造 PHOTO clue；
11. 进入现有 Create；
12. 后续完全复用当前 GetTask → Admin → List → Detail；
13. 成功/失败都在 `finally` 写 QueryEnd 并关闭日志。

### 6.3 失败传播

照片阶段抛出的 `FlowError` 需要携带：

- 已产生的 `raw_records`；
- 安全的 `public_fields.photo_input` 摘要；
- 当前阶段、HTTP 状态和耗时；
- `task_id=""`，因为 Create 尚未发生。

`AnalysisService._persist_execution_failure()` 继续复用现有逻辑：

- run_queries 状态为 `FAILED/EXECUTION_FAILED`；
- failure.stage 是实际照片阶段；
- 已收集 Raw 正常入库；
- 下一个 Query 继续执行；
- 不调用 Admin，因为没有 task_id。

## 7. 输入、Dataset 与 Query 重跑

### 7.1 CLI JSONL

修改 `validate_input()`：

- 返回对象保留 `photo_path`；
- 照片 Stage 必填；
- 普通 Stage 携带 `photo_path` 时拒绝，防止输入含义不清；
- 所有输入禁止预置 PHOTO clue；
- 只做结构校验，文件读取放到执行阶段。

### 7.2 JSONL/Excel Dataset 导入

修改 `_normalize_dataset_records()`：

- 支持 `FULL_NAME_PHOTO`；
- 检查 `FULL_NAME` clue；
- 检查 `photo_path` 为非空相对路径字符串；
- 禁止预置 PHOTO clue；
- 将 `photo_path` 继续放入现有 `metadata_json`；
- Excel `Queries` Sheet 增加可选 `photo_path` 列，不修改必需列集合；
- 普通 Stage 对照片列非空时报错。

导入预览不要求实际文件存在，避免历史结果或跨环境 Dataset 无法查看。真实执行时才进行文件校验。

### 7.3 Run 执行

`execute_run()` 查询 `dataset_queries` 时增加 `metadata_json`，解析后只把受支持的
`photo_path` 传给 `process_one()`。不得将 metadata 中任意未知键直接作为接口参数。

### 7.4 Query 重跑

`execute_query_retry()` 同样读取 `metadata_json` 和 `photo_path`：

- 使用当前挂载目录中的照片重新执行完整上传；
- 生成新的 `media_asset_id`；
- 生成新的 Raw 和人物日志；
- 不覆盖原 Raw；
- 结果摘要保存本次照片 SHA-256，便于识别照片是否被替换。

## 8. 数据结构与数据流

### 8.1 数据流

```text
Dataset.photo_path
  → metadata_json
  → execute_run / query_retry
  → process_one PhotoValidation
  → 内存 JPEG bytes
  → MediaService Config/Prepare
  → 独立 COS PUT Session
  → MediaService Complete
  → media_asset_id
  → CreateIntentTask PHOTO clue
  → 原 Search 采集
```

旁路落库：

```text
媒体 RPC / PUT 安全事件
  ├─ RawCallback → raw_records
  ├─ QueryChainLogger → 人物日志
  ├─ public_fields.photo_input → run_queries.public_fields_json
  └─ result.photo_input → results.jsonl
```

### 8.2 photo_input 摘要

成功结果建议保存：

```json
{
  "photo_path": "input_photos/taylor_swift.jpg",
  "content_type": "image/jpeg",
  "content_length": 867067,
  "sha256": "照片字节摘要",
  "config_version": "media_upload_v4_10mb",
  "media_asset_id": "media_xxx",
  "upload_status": "COMPLETED"
}
```

失败时按已完成程度保存：

```json
{
  "photo_path": "input_photos/taylor_swift.jpg",
  "content_type": "image/jpeg",
  "content_length": 867067,
  "sha256": "可能存在",
  "config_version": "可能存在",
  "media_asset_id": "Prepare 成功后才存在",
  "upload_status": "PREPARED | PUT_FAILED | COMPLETE_FAILED"
}
```

永不保存：

- `resolved_path`；
- JPEG bytes/base64；
- `upload_url`；
- COS 签名参数；
- Gateway/Auth Header。

### 8.3 Result Schema

建议将 `RESULT_SCHEMA_VERSION` 从 `1.3.1` 提升到 `1.3.2`：

- 旧字段不删除、不改名；
- `photo_input` 为可选字段；
- 旧导入器忽略未知字段即可继续工作；
- 历史结果不自动改写。

### 8.4 SQLite

无需 Schema 迁移：

- `dataset_queries.metadata_json` 保存 `photo_path`；
- `run_queries.public_fields_json` 保存照片摘要；
- `raw_records` 保存四个新阶段；
- `failures` 保存失败阶段；
- 现有 Candidate 表保持不变。

## 9. 脱敏与安全设计

### 9.1 结构化脱敏

扩展 `sanitize_raw()`：

- 键名 `upload_url` 不删除审计语义，统一替换为 `***SIGNED_UPLOAD_URL***`；
- 对嵌套响应中的完整动态 URL同样替换；
- `upload_headers` 只保留 Content-Length、Content-Type；
- 现有 Token、Cookie、Header、Device ID、User ID 规则保持；
- `media_asset_id` 允许保存，用于接口链路关联。

### 9.2 异常文本脱敏

新增一个纯字符串脱敏函数：

- 匹配 `http(s)://...?...` 动态 URL并移除 Query；
- COS 地址最多保留 `scheme + host + /***`；
- 对 `requests` 抛出的异常先脱敏再构造 `FlowError`；
- 进度消息只显示阶段和安全原因，不输出 URL、文件绝对路径或 Header。

### 9.3 SSRF 与认证隔离

- PUT URL 只能来自刚完成校验的 Prepare 响应；
- 仅允许 HTTPS；
- Host 必须命中配置的 COS 后缀白名单；
- 禁止 localhost、IP 字面量、userinfo 和非标准端口；
- 不允许重定向，避免签名 URL被跳转到其他主机；
- PUT Session 不继承 Gateway Session Cookie；
- PUT 不携带 Search/Admin Secret；
- URL 校验后仍以原字符串请求，不重新编码签名。

### 9.4 文件安全

- 先 `resolve()` 再检查位于照片根目录；
- 拒绝越界符号链接；
- 先 stat 和大小限制，再读取；
- 单文件最大值来自接口与本地安全上限；
- 只读一次并以同一份 bytes 计算大小、哈希和上传，避免检查后文件被替换；
- binary 只存在于当前 Query 内存，Query 结束后解除引用；
- 容器继续只读挂载 `/app/input`。

## 10. Web 与平台设计

### 10.1 Web 变化

仅扩展现有页面能力：

- Dataset 预览识别 `FULL_NAME_PHOTO`；
- Query 列表筛选增加 `FULL_NAME_PHOTO`；
- Run 进度显示照片五个阶段；
- Query 详情显示安全照片输入摘要和照片失败阶段；
- 不展示本地绝对路径、签名 URL 或图片 binary；
- 本期不增加照片选择/上传表单。

如现有模板通过 `SUPPORTED_QUERY_STAGES` 动态生成选项，只修改常量和对应测试；
不得为照片复制一套新页面。

### 10.2 指标与报告

- `analysis_service.SUPPORTED_QUERY_STAGES` 加入 `FULL_NAME_PHOTO`；
- Threshold Profile 对旧版本缺少照片 Stage 时使用当前安全默认，不修改旧快照；
- Query Stage 指标复用现有分组；
- 无照片 Query 的报告不展示空照片 Stage；
- 双 Process 只比较同一 `person_id + FULL_NAME_PHOTO`；
- 单次报告的成本仍来自 Admin 接口，不把媒体上传 HTTP 耗时误算为 `search_duration_ms`；
- 照片前置耗时可在 Raw 查看，本期不新增核心指标。

### 10.3 Docker 与测试开发平台

现有挂载已经满足：

```text
../Truthy_Search/input:/app/input:ro
```

部署仅需：

- 在 `input/input_photos` 放置文件；
- Secret 或 Compose 配置照片开关、目录和 Host 后缀；
- 如加入 Pillow，重新构建现有 truthy-search 镜像；
- 保持 `/truthy-search`、5002、健康检查和导航不变；
- 不新增 Volume、端口、Service 或数据库。

## 11. 具体修改文件

### 11.1 `search_tool.py`

修改内容：

1. 增加 Media Service 和照片常量；
2. 扩展 `Config` 和 `.env` 读取；
3. 扩展 `SearchClient.call(service_name=...)`；
4. 增加独立 COS PUT Session 和方法；
5. 扩展 `resolve_query_stage()`；
6. 扩展 CLI `validate_input()` 保留 `photo_path`；
7. 增加路径、JPEG、Config、Prepare、Complete 校验函数；
8. 扩展签名 URL 结构化及字符串脱敏；
9. 在 `process_one()` Create 前加入照片分支；
10. 输出 `photo_input` 摘要；
11. 保持普通 Query 分支和后续主链路不变；
12. 为新增函数编写完整中文 docstring，说明参数、返回值和异常策略。

### 11.2 `analysis_service.py`

修改内容：

1. `SUPPORTED_QUERY_STAGES` 加入照片 Stage；
2. Dataset 校验 `photo_path` 和禁止预置 PHOTO；
3. JSONL/Excel 将 `photo_path` 保存到 metadata；
4. `execute_run()` 读取 metadata 并传入照片路径；
5. `execute_query_retry()` 同步处理；
6. 成功/失败继续复用现有 Raw 和 public_fields 入库；
7. 兼容旧 Threshold Profile 和历史结果；
8. 报告 Stage 分组识别照片类型但不改指标公式。

### 11.3 `web_app.py`

修改内容：

1. Query 筛选集合增加 `FULL_NAME_PHOTO`；
2. Web 配置读取照片目录；
3. 复用动态 Stage 选项和进度显示；
4. 不新建路由和上传页面。

### 11.4 `.env.example`

增加照片开关、目录、安全上限和 COS Host 后缀示例，不填写动态 URL或秘密。

### 11.5 `requirements.txt`

增加固定兼容版本范围的 Pillow，用于 JPEG 解码验证和 EXIF 检查；不引入图片搜索或人脸识别库。

### 11.6 `tests/test_search_tool.py`

增加照片核心链路、失败、脱敏和旧链路零影响测试。

### 11.7 `tests/test_analysis_service.py`

增加 JSONL/Excel 导入、metadata 传递、Run、重跑、历史导入和无成本重处理测试。

### 11.8 `tests/test_web_app.py`

增加 Dataset 预览、Stage 筛选、Web Run 进度和错误展示测试。

### 11.9 测试夹具

实现阶段需要在现有 fixtures 目录增加一张极小、无真人信息的合成 JPEG 和三个媒体接口脱敏响应。
这是复现二进制上传和 EXIF 安全校验所必需的测试资产；不使用用户真实照片和真实签名 URL。

## 12. 测试设计

### 12.1 接口契约测试

- Config 正常响应；
- Config 不允许 JPEG；
- Config 大小字段缺失/非法；
- `face_detection_required=true`；
- Prepare 四个必需字段缺失；
- Prepare size/header/MIME 不一致；
- Prepare status 非 pending；
- Prepare 已过期；
- upload_method 非 PUT；
- Complete status uploaded；
- Complete media ID/size/MIME 冲突；
- Complete pending 后按配置成功；
- Complete 超过最大次数停止。

### 12.2 文件与路径测试

- 合法 JPG/JPEG；
- 中文和空格文件名；
- 空文件、损坏 JPEG、扩展名伪装；
- PNG/WebP 即使 Config 允许，仍按产品范围拒绝；
- 文件超过 Config 或本地上限；
- 绝对路径、`../`、URL、目录和越界 symlink；
- 带 EXIF 且 Config 要求 strip 时失败；
- 不带 EXIF时通过；
- 读取后 SHA-256、长度与上传 bytes 一致。

### 12.3 顺序与隔离测试

- 正常照片完整顺序；
- Config 失败：Prepare/PUT/Complete/Create 均为 0；
- Prepare 失败：PUT/Complete/Create 为 0；
- PUT 失败：Complete/Create 为 0；
- Complete 失败：Create 为 0；
- Create 收到正确 PHOTO clue；
- Create 后 GetTask/Admin/List/Detail 顺序保持；
- 一个照片 Query 失败后下一个普通 Query 执行；
- 普通 Query 的媒体调用次数为 0；
- 一个 Run 继续共用原 Admin Session。

### 12.4 PUT 安全测试

- 使用独立 Session；
- 只传签名 Header；
- 不传 Authorization、Cookie、Device/User ID；
- body 为 bytes 且与本地文件相同；
- 不允许重定向；
- HTTP 200 成功、非 200 失败；
- URL host、scheme、端口、userinfo 校验；
- 签名 URL没有被二次编码；
- requests 异常不泄漏完整 URL。

### 12.5 数据与日志测试

- 四个新阶段进入 raw_records；
- PUT Raw 不含 binary；
- Prepare Raw 的 upload_url 被替换；
- Query 日志包含 Config/Prepare/PUT/Complete；
- 日志不包含 JPEG base64、签名、Token、Cookie 和绝对路径；
- success result 有安全 photo_input；
- pre-Create failure 的 task_id 为空且 Raw 完整；
- results/failures 向后兼容；
- 旧历史结果可导入。

### 12.6 Dataset、Web 和重处理测试

- JSONL/Excel 照片 Dataset 导入；
- 普通 Dataset 不受影响；
- metadata_json → process_one 传递；
- Query 重跑重新上传；
- Web 筛选照片 Stage；
- 容器重启后只读照片可访问；
- 无成本重处理媒体请求次数为 0；
- 没有照片 Query 的报告不出现空分组；
- 双 Process 照片 Stage 同条件比较正常。

### 12.7 回归测试

至少运行：

```text
tests/test_search_tool.py
tests/test_analysis_service.py
tests/test_web_app.py
现有 Excel / Report 回归
```

同时执行敏感字符串扫描和 `git diff --check`。

## 13. 分阶段开发计划

### 阶段 0：契约冻结与失败测试

目标：把真实样例转换为安全、稳定、无需真实网络的测试契约。

任务：

1. 从提供文件整理 Config、Prepare、Complete 脱敏 fixtures；
2. 用合成 JPEG 构造 PUT 测试；
3. 冻结 MediaService、params 和响应路径；
4. 冻结 PUT 仅 HTTP 200 成功；
5. 冻结签名 URL不得重编码；
6. 冻结 Config/Prepare/PUT/Complete/Create 顺序；
7. 冻结当前 Admin 在 GetTask 终态后、List 前的顺序；
8. 编写当前代码必然失败的接口、路径、脱敏和顺序测试；
9. 确认 `strip_exif` 是客户端要求；若后端确认不是，调整 EXIF测试但保留安全记录；
10. 确认 Complete pending/HTTP 重试范围。

完成标准：

- 测试不包含真实 Token、用户 ID、照片和签名 URL；
- 当前代码出现预期失败；
- 没有未确认字段被写成实现假设。

### 阶段 1：输入校验与媒体客户端

目标：完成照片读取和四步前置接口，不接触分析指标。

修改文件：

- `search_tool.py`
- `.env.example`
- `requirements.txt`
- `tests/test_search_tool.py`
- 已确认的测试 fixtures

任务：

1. 增加照片配置；
2. 支持 MediaService RPC；
3. 实现独立安全 PUT；
4. 实现路径/JPEG/大小/EXIF 校验；
5. 实现 Config、Prepare 和 Complete 解析；
6. 实现 Complete 有界重试；
7. 扩展脱敏；
8. 在 `process_one()` 接入照片分支；
9. 生成 PHOTO clue；
10. 保持普通 Query 代码路径不变。

完成标准：

- 核心正常/失败/安全测试通过；
- 普通 Query 的媒体请求数为 0；
- binary 和签名 URL不进入任何事件对象。

### 阶段 2：Dataset、SQLite 与平台执行集成

目标：打通 JSONL/Excel → Web Run/CLI → Raw/SQLite/results/failures。

修改文件：

- `analysis_service.py`
- `web_app.py`
- `tests/test_analysis_service.py`
- `tests/test_web_app.py`

任务：

1. 支持 `FULL_NAME_PHOTO`；
2. 导入并保存 `photo_path` metadata；
3. Run 和 Query 重跑读取 metadata；
4. 失败 Raw 和 photo_input 摘要入库；
5. Web 显示 Stage、进度和安全错误；
6. Threshold/指标/报告兼容新 Stage；
7. 验证历史导入和无成本重处理零请求；
8. 将 Result Schema 提升为向后兼容小版本。

完成标准：

- Web/CLI 共用 `process_one()`；
- 不修改 SQLite Schema；
- Query 重跑不覆盖原 Raw；
- 旧 Run、Process、Report 可读取。

### 阶段 3：测试开发平台部署与验收

目标：在现有 `/truthy-search` 平台完成小批量真实照片验收。

任务：

1. 在 `input/input_photos` 放置受控测试 JPEG；
2. 设置照片开关、目录和 COS Host 后缀；
3. 重建现有 truthy-search 镜像；
4. 验证 `/app/input/input_photos` 只读权限；
5. 执行普通、照片、混合 Dataset；
6. 验证照片 Query 重跑；
7. 验证容器重启和日志持久化；
8. 扫描 SQLite、Raw、结果和日志中的秘密/签名/binary；
9. 运行全量回归；
10. 更新 README 的输入示例、配置、错误排查和部署说明。

完成标准：

- 平台健康检查正常；
- 不新增端口、服务、数据库和挂载；
- 小批量真实照片完整成功；
- 上传失败安全隔离；
- 敏感信息扫描无泄漏。

## 14. 风险与控制

| 风险 | 影响 | 控制 |
| --- | --- | --- |
| 签名 URL被二次编码 | PUT 403 | 原 URL直接请求，不重新拼接 Query |
| Search Header 泄漏到 COS | 凭证泄漏 | 独立 Session，只传签名 Header |
| 动态 URL SSRF | 访问非预期主机 | HTTPS + Host 后缀白名单 + 禁止重定向 |
| 文件路径穿越 | 读取任意文件 | resolve 后检查根目录、拒绝 symlink 越界 |
| 大文件耗尽内存 | 进程异常 | 先 stat、接口/本地双上限，再读取 |
| EXIF 泄漏 | 暴露位置/设备信息 | Config 要求时检测并拒绝未清理照片 |
| PUT 超时但实际成功 | 状态不确定 | PUT 不自动重放；Query 重跑重新 Prepare |
| Complete 最终一致性 | Create 使用未完成资产 | 按 Config 有界重试，只接受 uploaded |
| Prepare 后 Create 失败 | 远端孤立媒体 | 保存安全告警；本期无清理接口不猜测删除 |
| photo_path 被替换 | 不同重跑使用不同照片 | 每次结果记录 SHA-256，差异可审计 |
| 新 Stage 破坏旧阈值 | 历史报告异常 | 旧快照不改，缺少照片 Stage 使用兼容默认 |
| 日志记录 binary/URL | 隐私和签名泄漏 | PUT 专用 Raw 摘要、结构+字符串双重脱敏 |

## 15. 回滚与兼容性

### 15.1 回滚

```dotenv
SEARCH_PHOTO_ENABLED=false
```

关闭后：

- `FULL_NAME`、`FULL_NAME_SOCIAL` 恢复原行为；
- `FULL_NAME_PHOTO` 在 Input 阶段明确不可执行；
- 已生成 Raw、结果和日志保留；
- 不需要数据库回滚；
- 可直接回滚上一 Docker 镜像。

### 15.2 兼容性

- 旧 Dataset 不要求 `photo_path`；
- 旧 results/failures 没有 `photo_input` 时正常读取；
- 历史 Run、Process、Report 不自动更新；
- 无成本重处理不读取本地照片；
- 原 Candidate Detail 单人失败隔离不变；
- Admin Session、成本提取和报告成本模块不变；
- 当前 `/truthy-search`、5002、导航和 Docker 架构不变。

## 16. 本次明确不实现

- Web 直接上传或预览本地照片；
- 从 URL 下载照片；
- PNG/WebP/HEIC 上传；
- 自动裁剪、缩放、压缩、旋转或人脸检测；
- 工具内自动重编码并去 EXIF；
- 多照片 Query；
- Social + Photo 新组合 Stage；
- media_asset_id 跨 Query 缓存；
- Config 的 Run 内缓存；
- PUT 自动重试；
- 远端媒体删除或生命周期管理；
- 媒体上传耗时核心指标；
- 照片相似度和身份规则调整；
- 新数据库表、独立上传服务或异步队列。

## 17. 实施前最终确认项

根据样例已确认绝大部分契约，仅保留以下必须在阶段 0 关闭的窄问题：

1. `strip_exif=true` 是否要求客户端清理；本设计在未确认前采用“检测到 EXIF 即拒绝”；
2. Complete 的 `pending` 是否为正式可重试状态；
3. HTTP 408/429/5xx 是否允许按 `complete_retry` 重放 Complete；
4. COS PUT 是否严格只有 HTTP 200 成功，还是允许 201/204；
5. `.myqcloud.com` 是否覆盖测试和后续环境的全部 COS Host；
6. `media_asset_id` 是否允许按当前设计进入 Raw、SQLite public_fields 和 results 摘要。

这些问题只影响安全边界和失败重试，不改变主链路、输入格式和总体开发方案。
