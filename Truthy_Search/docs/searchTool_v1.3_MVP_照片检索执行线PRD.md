# searchTool v1.3 MVP 照片检索执行线 PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | searchTool v1.3 MVP 照片检索执行线 PRD |
| 文档版本 | v1.0 |
| 基于版本 | searchTool v1.3 MVP |
| 编写日期 | 2026-08-10 |
| 需求状态 | 待接口契约冻结 |
| 需求类型 | 检索采集链路增量能力 |
| 核心目标 | 在不改变现有检索执行线的前提下，新增“本地 JPEG 上传 + FULL_NAME_PHOTO 检索”执行线 |

## 2. 需求背景

当前 searchTool 支持以下两种检索条件：

- `FULL_NAME`：全名检索；
- `FULL_NAME_SOCIAL`：全名 + Social Link 检索。

现有 Query 的主链路为：

```text
CreateIntentTask
  → GetTask 轮询
  → 任务公共信息采集
  → ListTaskCandidates
  → 全部 GetTaskCandidateDetail
  → 保存 results.jsonl、Raw、SQLite 和人物链路日志
```

现有链路不能直接使用本地照片作为检索线索。照片不能直接写入
`CreateIntentTask`，必须先完成媒体配置获取、上传准备、COS 二进制上传和上传完成确认，
取得可用的 `media_asset_id` 后才能创建检索任务。

本次需要新增一条独立的照片检索执行线。原有 `FULL_NAME` 和
`FULL_NAME_SOCIAL` 链路必须保持原样，不能因为照片功能产生额外请求或行为变化。

## 3. 需求目标

### 3.1 产品目标

1. 支持从项目 `input/input_photos` 目录读取本地 JPEG 照片；
2. 支持 `FULL_NAME_PHOTO` Query；
3. 在 `CreateIntentTask` 前顺序完成四步媒体上传流程；
4. 使用上传流程生成的 `media_asset_id` 动态构造 `PHOTO` clue；
5. 照片任务创建成功后，完整复用当前 GetTask、公共信息、候选人和结果处理链路；
6. 照片上传失败时只终止当前 Query，不影响同一 Run 中的后续 Query；
7. 二进制照片、动态签名 URL 和认证信息不得写入日志、Raw、SQLite 或结果文件；
8. CLI、Web Run 和 Query 重跑使用同一套照片执行逻辑。

### 3.2 成功标准

- 不含照片的 Query 调用顺序与当前版本完全一致；
- `FULL_NAME_PHOTO` 严格按以下顺序执行：

```text
GetMediaUploadConfig
  → PrepareMediaUpload
  → PUT upload_url
  → CompleteMediaUpload
  → CreateIntentTask（含 PHOTO clue）
  → 原有 searchTool 后续链路
```

- `Content-Length`、`Content-Type`、`media_asset_id`、`upload_url` 缺失时不得继续上传；
- PUT 使用原始 JPEG 字节作为 body，不使用 JSON、base64 或 multipart；
- Create 只能使用当前 Query 上传成功的 `media_asset_id`；
- 任一上传前置步骤失败时，不调用 `CreateIntentTask`；
- 一个照片 Query 失败不会阻断 Run 中其他 Query；
- 无成本重处理、历史结果导入不会调用任何媒体上传接口；
- 所有新增请求阶段均可在 Raw 和人物链路日志中追溯，但不包含照片 binary 和完整签名 URL。

## 4. 需求范围

### 4.1 本次包含

1. 新增 `FULL_NAME_PHOTO` Query Stage；
2. JSONL 和 Excel Query 输入增加本地照片相对路径；
3. 本地 JPEG 文件存在性、类型、大小和路径安全校验；
4. `GetMediaUploadConfig` 请求；
5. `PrepareMediaUpload` 请求；
6. 使用动态签名 URL PUT JPEG 原始字节；
7. `CompleteMediaUpload` 请求；
8. 动态构造 `PHOTO` clue 并调用 `CreateIntentTask`；
9. 新增阶段的进度、Raw、失败记录和人物链路日志；
10. Web 已有 Dataset 选择和 Run 启动流程兼容；
11. 测试开发平台 Docker 的只读照片目录兼容；
12. `FULL_NAME_PHOTO` 在处理、指标和报告中作为独立 Query Stage 展示。

### 4.2 本次不包含

- 修改现有 `FULL_NAME`、`FULL_NAME_SOCIAL` 请求流程；
- 浏览器页面直接上传照片；
- 从互联网 URL 下载照片；
- PNG、WebP、HEIC、GIF 或视频上传；
- 图片裁剪、压缩、旋转、人脸检测或格式转换；
- 一张 Query 上传多张照片；
- `FULL_NAME_SOCIAL_PHOTO` 等多线索组合；
- 跨 Query 复用 `media_asset_id`；
- 自动清理已上传但 Create 失败的远端媒体；
- 为上传流程新增独立服务、端口、队列或数据库；
- 修改候选人身份归类、照片 80% 阈值、字段指标或报告布局；
- 历史 Run 自动补传照片或自动重新调用检索接口。

## 5. 总体执行设计

### 5.1 原有执行线

以下 Query 不进入任何照片逻辑：

```text
FULL_NAME / FULL_NAME_SOCIAL
  → CreateIntentTask
  → GetTask
  → 现有后续流程
```

验收时媒体接口请求次数必须为 0。

### 5.2 新增照片执行线

```text
读取 FULL_NAME_PHOTO 输入
  ↓
校验照片相对路径、JPEG 类型、文件大小
  ↓
GetMediaUploadConfig
  ↓
PrepareMediaUpload
  ├─ Content-Length
  ├─ Content-Type
  ├─ media_asset_id
  └─ upload_url
  ↓
PUT upload_url
  Headers:
    Content-Length: Prepare 响应值
    Content-Type: Prepare 响应值
  Body:
    JPEG 原始 binary
  ↓
CompleteMediaUpload
  ↓
CreateIntentTask
  clues += PHOTO(media_asset_id, face)
  ↓
GetTask → 公共信息 → List → 全部 Candidate Detail
  ↓
现有 results / Raw / SQLite / 日志
```

### 5.3 关键顺序约束

1. 四个照片前置步骤必须串行，不能并发；
2. `PrepareMediaUpload` 成功前不能发起 PUT；
3. PUT 成功前不能调用 `CompleteMediaUpload`；
4. `CompleteMediaUpload` 成功前不能调用 `CreateIntentTask`；
5. `media_asset_id` 只能来自当前 Query 的 Prepare 响应；
6. 照片上传完成后，现有检索链路不增加照片专属分支；
7. Run 仍由现有 `RunCoordinator` 单线程按 Query 顺序执行。

## 6. 输入需求

### 6.1 照片存放目录

照片统一存放在：

```text
项目根目录/input/input_photos/
```

输入记录只保存相对于 `input/` 的路径，例如：

```text
input_photos/taylor_swift.jpg
```

禁止输入：

- `/Users/.../photo.jpg` 等绝对路径；
- `../` 路径穿越；
- `file://`、`http://`、`https://` URL；
- 指向 `input/` 目录之外的符号链接；
- 目录路径或不存在的文件。

### 6.2 JSONL 输入格式

首版新增字段：

| 字段 | 必填条件 | 类型 | 说明 |
| --- | --- | --- | --- |
| `input_id` | 是 | string | Query 唯一标识，沿用现有规则 |
| `person_id` | 否 | string | 与基准人物稳定关联 |
| `query_stage` | 是 | string | 照片执行线固定为 `FULL_NAME_PHOTO` |
| `photo_path` | `FULL_NAME_PHOTO` 必填 | string | 相对于 `input/` 的 JPEG 路径 |
| `match_strategy` | 否 | string | 原样传入，不在本需求中改变语义 |
| `clues` | 是 | array | 输入中保留 FULL_NAME 等非 PHOTO 线索 |
| `additional_details` | 否 | array | 沿用现有规则 |

示例：

```json
{
  "input_id": "case-photo-001",
  "person_id": "person-taylor-swift",
  "query_stage": "FULL_NAME_PHOTO",
  "photo_path": "input_photos/taylor_swift.jpg",
  "match_strategy": "UNION",
  "clues": [
    {
      "type": "FULL_NAME",
      "full_name_query": {
        "full_name": "Taylor Swift"
      }
    }
  ],
  "additional_details": []
}
```

输入文件不得预先包含 `PHOTO` clue，原因是 `media_asset_id` 只能在运行时通过上传流程生成。
如果发现输入中已存在 `PHOTO` clue，应在 Input 阶段明确报错，避免使用过期或跨 Query 的媒体资源。

### 6.3 Excel 输入格式

现有 Query Excel 导入保持不变，仅在 `Queries` Sheet 增加可选列：

```text
photo_path
```

- `FULL_NAME`、`FULL_NAME_SOCIAL`：该列必须为空；
- `FULL_NAME_PHOTO`：该列必须填写；
- Excel 导入后内部统一转换为与 JSONL 相同的数据对象。

### 6.4 文件校验

运行照片接口前必须完成：

1. 路径解析后仍位于配置的照片目录内；
2. 扩展名只能为 `.jpg` 或 `.jpeg`，大小写不敏感；
3. 文件必须是普通文件且可读；
4. 文件开头和结尾满足 JPEG 基础签名校验；
5. 文件字节数大于 0；
6. 文件大小不超过 `GetMediaUploadConfig` 返回的限制；
7. 如果 Config 响应不提供最大文件大小，必须使用平台显式配置的安全上限，不能无限制读取；
8. 文件校验失败时停在 Input/PhotoValidation 阶段，不调用任何上传接口。

## 7. 接口流程需求

> 三个业务接口的 URL、Service、请求参数和完整响应路径尚未提供。本节冻结业务行为，
> 正式开发前必须用脱敏请求/响应样例补齐接口契约，不允许根据接口名称猜测字段结构。

### 7.1 GetMediaUploadConfig

用途：获取当前媒体上传支持的类型、大小或其他约束。

要求：

- 每个 `FULL_NAME_PHOTO` Query 在上传前调用一次；
- 返回失败时当前 Query 失败；
- 必须校验 JPEG 是否在允许类型内；
- Config 响应可以完整脱敏保存到 Raw；
- 普通 Query 不得调用该接口。

待确认：

- 请求 URL、Service 和 Method；
- 是否复用现有 Search API 的 HTTP Header 和认证；
- 请求 params；
- 支持类型、最大文件大小和有效期的正式字段路径。

### 7.2 PrepareMediaUpload

用途：为当前 JPEG 创建媒体资产并获得 COS 动态签名上传 URL。

成功响应至少需要提取：

| 字段 | 用途 | 校验要求 |
| --- | --- | --- |
| `Content-Length` | PUT Header | 必须为正整数且与本地实际字节数一致 |
| `Content-Type` | PUT Header | 首版必须为 `image/jpeg` |
| `media_asset_id` | Complete 和 Create 使用 | 必须为非空字符串 |
| `upload_url` | PUT 请求 URL | 必须为合法 HTTP/HTTPS URL，且只在内存中使用 |

要求：

- Prepare 请求应携带后端正式契约要求的文件名、文件大小和 MIME；
- 本地文件大小与响应 `Content-Length` 不一致时必须失败，不得擅自改写任一值；
- 不允许把 `upload_url` 写入普通日志、异常文本、SQLite 或 results；
- Raw 中只记录 `upload_url` 已返回，不记录其完整值。

待确认：

- 请求 params 完整结构；
- 四个返回值的精确 JSON 路径；
- `upload_url` 允许的 scheme、host 范围和有效期；
- Prepare 是否存在业务幂等键。

### 7.3 PUT 上传图片至 COS

请求规则：

```text
Method: PUT
URL: PrepareMediaUpload 返回的 upload_url
Headers:
  Content-Length: PrepareMediaUpload 返回值
  Content-Type: PrepareMediaUpload 返回值
Body:
  本地 JPEG 文件原始 bytes
```

安全要求：

1. PUT 不能携带原 Search API 的 `Authorization`、Cookie、Device ID、User ID 或通用业务 Header；
2. 除 Prepare 明确要求的 Header 外，不向 COS 透传平台 Secret；
3. 禁止把图片转换为 JSON、base64 或 multipart；
4. 禁止把 binary body 写入 Raw、日志、异常或 results；
5. 禁止记录完整 `upload_url` 及其签名 Query 参数；
6. 日志只记录脱敏目标、文件相对路径、字节数、MIME、HTTP 状态和耗时；
7. 只有接口契约规定的成功 HTTP 状态才视为上传成功；
8. PUT 超时或失败后不调用 Complete 和 Create。

### 7.4 CompleteMediaUpload

用途：通知媒体服务 COS 上传已经完成，使 `media_asset_id` 可用于检索。

要求：

- 仅在 PUT 成功后调用；
- 使用当前 Query 的 `media_asset_id`；
- 必须按正式响应校验业务成功状态；
- 响应若回传 `media_asset_id`，必须与 Prepare 返回值一致；
- Complete 失败时不调用 Create；
- 完整脱敏响应保存到 Raw。

待确认：

- 请求 URL、Service、Method 和 params；
- 是否需要 ETag、文件大小、MIME 或校验值；
- 成功响应字段；
- 媒体完成后是否存在可用状态延迟。

### 7.5 CreateIntentTask

Complete 成功后，在当前输入 `clues` 的副本中追加：

```json
{
  "type": "PHOTO",
  "photo_query": {
    "media_asset_id": "运行时取得的 media_asset_id",
    "photo_type_hint": "face"
  }
}
```

最终 Create params 示例：

```json
{
  "match_strategy": "UNION",
  "clues": [
    {
      "type": "FULL_NAME",
      "full_name_query": {
        "full_name": "Taylor Swift"
      }
    },
    {
      "type": "PHOTO",
      "photo_query": {
        "media_asset_id": "media_xxx",
        "photo_type_hint": "face"
      }
    }
  ],
  "additional_details": []
}
```

约束：

- 不修改输入对象本身，使用运行时副本追加 PHOTO；
- 不覆盖输入中的 FULL_NAME 和 additional_details；
- `photo_type_hint` 首版固定为 `face`，不做用户配置；
- Create 失败后按现有 Query 失败规则处理；
- 已上传媒体的远端回收依赖后端能力，本期只记录安全告警，不猜测清理接口。

## 8. 状态、失败与重试规则

### 8.1 Query 阶段

新增阶段名称：

```text
PhotoValidation
GetMediaUploadConfig
PrepareMediaUpload
PutMediaBinary
CompleteMediaUpload
```

阶段顺序后继续使用现有：

```text
CreateIntentTask
GetTask
AdminLogin / GetSearchTaskDebug / GetProviderCostSummary
ListTaskCandidates
GetTaskCandidateDetail
QueryEnd
```

### 8.2 失败处理

| 失败阶段 | 当前 Query | 后续 Query | 是否调用 Create |
| --- | --- | --- | --- |
| PhotoValidation | 失败 | 继续 | 否 |
| GetMediaUploadConfig | 失败 | 继续 | 否 |
| PrepareMediaUpload | 失败 | 继续 | 否 |
| PUT | 失败 | 继续 | 否 |
| CompleteMediaUpload | 失败 | 继续 | 否 |
| CreateIntentTask | 按现有规则失败 | 继续 | 已调用 |
| Create 后续阶段 | 按现有规则处理 | 继续 | 已调用 |

### 8.3 重试原则

为避免重复创建媒体资产或重复 Complete，首版默认规则为：

- 三个媒体业务接口和 PUT 各调用一次；
- 不在内部自动重放完整上传链路；
- HTTP 客户端连接级行为沿用现有超时配置；
- Query 重跑时重新执行完整上传流程并生成新的 `media_asset_id`；
- 只有后端明确确认幂等键和安全重试状态后，才允许在后续版本增加短重试。

## 9. 数据保存与安全

### 9.1 Raw 阶段

`raw_records` 增加：

```text
GetMediaUploadConfig
PrepareMediaUpload
PutMediaBinary
CompleteMediaUpload
```

Raw 保存：

- 脱敏后的业务请求参数；
- 脱敏后的业务响应；
- HTTP 状态、耗时、阶段、顺序号和错误；
- 本地照片相对路径、文件大小和 MIME；
- PUT 是否成功。

Raw 禁止保存：

- JPEG binary；
- base64 照片；
- 完整 `upload_url`；
- COS 签名 Query 参数；
- Search/Admin Token、Cookie 和认证 Header；
- 主机绝对文件路径。

### 9.2 人物链路日志

人物日志沿用当前文件和逐请求追加机制，新增四个上传阶段。

PUT 日志示例只允许表达为：

```json
{
  "stage": "PutMediaBinary",
  "request": {
    "photo_path": "input_photos/taylor_swift.jpg",
    "content_type": "image/jpeg",
    "content_length": 123456,
    "upload_url": "***SIGNED_UPLOAD_URL***",
    "binary_logged": false
  },
  "http_status": 200,
  "business_success": true
}
```

### 9.3 results.jsonl

成功结果保持现有候选人结构，增加安全的 Query 输入摘要：

```json
{
  "query_stage": "FULL_NAME_PHOTO",
  "photo_input": {
    "photo_path": "input_photos/taylor_swift.jpg",
    "content_type": "image/jpeg",
    "content_length": 123456,
    "upload_status": "COMPLETED"
  }
}
```

`media_asset_id` 是否进入结果摘要需以其敏感等级和后端复用规则确认；首版至少在
Create 的脱敏 Raw 中可追踪，但不得把 `upload_url` 写入结果。

### 9.4 SQLite

优先复用现有字段：

- Dataset Query 原始输入保存 `photo_path`；
- `query_stage` 保存 `FULL_NAME_PHOTO`；
- 新请求进入现有 `raw_records`；
- Query 失败进入现有 `failures`；
- 候选人和详情继续进入现有表。

首版不为照片新增业务表。开发设计阶段应先验证现有 Query JSON 字段能否保存照片输入摘要；
只有现有结构无法表达时，才另行提出最小 Schema 变更，不能在本 PRD 中预设新表。

## 10. 配置与平台要求

建议配置：

```dotenv
# 默认关闭，接口契约和平台照片目录准备完成后再开启。
SEARCH_PHOTO_ENABLED=false

# 本地模式默认指向项目 input/input_photos；平台模式为 /app/input/input_photos。
SEARCH_PHOTO_INPUT_DIR=input/input_photos

# Config 未返回最大文件大小时必须显式配置；为空时拒绝无上限上传。
SEARCH_PHOTO_MAX_BYTES=
```

配置原则：

1. `SEARCH_PHOTO_ENABLED=false` 时，`FULL_NAME` 和 `FULL_NAME_SOCIAL` 正常运行；
2. 收到 `FULL_NAME_PHOTO` 但开关关闭时，在 Input 阶段明确失败；
3. 三个媒体业务接口若与现有 Search API 使用同一 Gateway，则复用现有 URL 配置；
4. 如果后端确认使用独立 URL，再增加最少的媒体 URL 配置，不能提前猜测；
5. 动态 `upload_url` 不是配置项，不写入 `.env`；
6. 平台 Secret 仍只用于 Search/Admin 认证，不向 COS PUT 透传。

测试开发平台当前已有：

```text
../Truthy_Search/input:/app/input:ro
```

因此 `input/input_photos` 可通过 `/app/input/input_photos` 只读访问，无需新增端口、服务或数据库。
部署前只需确认容器运行用户对照片文件有读取权限。

## 11. Web、导入和重处理兼容

### 11.1 Web Run

- Web 仍通过导入 Dataset 后选择数据集启动；
- 首版不增加浏览器照片上传控件；
- Dataset 中 `FULL_NAME_PHOTO` 的 `photo_path` 必须对应平台挂载目录中的文件；
- 页面进度可展示五个照片阶段；
- 单 Query 重跑重新上传照片，不复用旧资源。

### 11.2 历史导入

- 旧 JSONL/Excel 不包含 `photo_path` 时继续正常导入；
- `FULL_NAME`、`FULL_NAME_SOCIAL` 不要求照片；
- 导入已有 `FULL_NAME_PHOTO` 结果时，可以没有本地照片文件；
- 只有启动真实照片检索时才校验本地文件。

### 11.3 无成本重处理

无成本重处理只读取已入库的 Raw、Query 和 Candidate：

- 不调用 GetMediaUploadConfig；
- 不调用 PrepareMediaUpload；
- 不执行 PUT；
- 不调用 CompleteMediaUpload；
- 不调用 Create 或其他 Search API。

## 12. 指标与报告兼容

1. `FULL_NAME_PHOTO` 作为新的 `query_stage` 独立分组；
2. 单 Run 报告中的 Query Stage 表可以单独展示照片条件结果；
3. 双 Process 报告只比较相同人物、相同 `query_stage` 的 Query；
4. `FULL_NAME` 与 `FULL_NAME_PHOTO` 不直接混为同条件结果；
5. 照片上传是否成功是执行质量信息，不进入候选人资料准确度或完整度；
6. Candidate Detail 返回的 `photos` 模块继续使用现有字段配置与指标规则；
7. 本需求不改变 `photos_identity_match_rate` 的身份判定阈值。

## 13. 测试与验收

### 13.1 输入测试

- 合法 `.jpg`、`.jpeg`；
- 中文、空格文件名；
- 文件不存在；
- 空文件；
- 扩展名伪装的非 JPEG；
- PNG/HEIC 等不支持格式；
- 超过大小限制；
- 绝对路径、`../` 和指向目录外的符号链接；
- `FULL_NAME_PHOTO` 缺少 `photo_path`；
- 普通 Query 错误携带 `photo_path`；
- 输入预置 PHOTO clue。

### 13.2 接口顺序测试

- 正常四步上传后才调用 Create；
- Config 失败时后续调用次数为 0；
- Prepare 失败时 PUT、Complete、Create 次数为 0；
- PUT 失败时 Complete、Create 次数为 0；
- Complete 失败时 Create 次数为 0；
- Create 使用当前 Prepare 产生的 `media_asset_id`；
- Create 后完整复用现有轮询、公共信息、List 和 Detail；
- `FULL_NAME`、`FULL_NAME_SOCIAL` 的所有媒体请求次数为 0。

### 13.3 PUT 测试

- URL 使用 Prepare 返回值；
- Header 中只包含允许的上传 Header；
- Content-Length 与实际字节数一致；
- Content-Type 为 `image/jpeg`；
- body 与本地 JPEG 字节完全一致；
- 不使用 JSON、base64 和 multipart；
- 成功状态判定符合接口契约；
- 超时、非成功 HTTP 状态和连接错误均安全失败。

### 13.4 数据安全测试

- Raw、results、failures、SQLite、人物日志中搜索不到 JPEG binary/base64；
- 搜索不到完整 `upload_url` 和签名参数；
- 搜索不到 Auth Token、Cookie、Device ID 和 User ID；
- 不记录宿主机绝对文件路径；
- 日志仍能通过 `run_id + input_id + stage` 定位失败步骤。

### 13.5 平台回归测试

- Web Run 执行照片 Dataset；
- Query 重跑生成新媒体资源；
- 容器重启后照片仍可从只读挂载读取；
- 旧 Dataset、旧 Run、历史导入和报告可用；
- 无成本重处理的媒体接口调用次数为 0；
- `/truthy-search`、5002 和平台导航不变；
- 现有 Admin 公共信息采集顺序不变。

### 13.6 最终验收标准

- 新旧执行线完全隔离；
- 照片上传和 Create 调用顺序符合本 PRD；
- 上传失败不会产生无效 Create，也不会中断整个 Run；
- 本地文件、动态签名 URL 和认证信息安全处理；
- 成功 Query 的候选人采集、处理和报告能力与现有链路一致；
- 不新增独立服务、端口、数据库或浏览器上传页面；
- 自动化测试和小批量真实 JPEG Run 验收通过。

## 14. 开发前必须确认的接口契约

以下事项必须在阶段 0 用脱敏接口样例冻结，但不改变本 PRD 的业务方向：

1. `GetMediaUploadConfig` 的 URL、Service、Method、请求 params 和响应字段；
2. `PrepareMediaUpload` 的 URL、Service、Method、请求 params；
3. `Content-Length`、`Content-Type`、`media_asset_id`、`upload_url` 的精确响应路径；
4. `CompleteMediaUpload` 的 URL、Service、Method、请求 params 和成功响应；
5. 三个业务接口是否复用 Search API 的认证和统一 Gateway；
6. PUT 的成功 HTTP 状态集合；
7. PUT 是否还要求 ETag、Content-MD5 或其他签名 Header；
8. `upload_url` 允许的 scheme、host 范围和有效期；
9. Config 是否返回最大文件大小和支持 MIME；
10. Complete 后媒体是否立即可用于 Create；
11. Prepare/Complete 是否支持幂等，以及允许安全重试的条件；
12. `media_asset_id` 的敏感等级、保存范围和生命周期。

接口契约未冻结前可以完成输入校验、分支设计和测试夹具准备，但不得接入真实照片上传。

## 15. 快速安全实施建议

建议拆为三个小阶段：

### 阶段 0：契约与失败测试

- 整理三个业务接口和 PUT 的脱敏夹具；
- 冻结字段路径、认证、成功状态和大小限制；
- 先编写执行顺序、路径安全、二进制不落盘的失败测试。

### 阶段 1：CLI/核心执行线

- 扩展输入校验和 `FULL_NAME_PHOTO`；
- 在现有 `process_one()` 的 Create 前增加照片分支；
- 复用现有 Client、RawCallback、Failure 和 QueryChainLogger；
- 不改变普通 Query 分支。

### 阶段 2：平台兼容与验收

- 扩展 JSONL/Excel Dataset 导入；
- 展示照片执行阶段进度；
- 验证 `/app/input/input_photos` 只读挂载；
- 完成 Web Run、Query 重跑、重处理和回归验收。

回滚时关闭 `SEARCH_PHOTO_ENABLED` 即恢复现有执行范围；由于不新增数据库和服务，
旧数据无需迁移或回滚。
