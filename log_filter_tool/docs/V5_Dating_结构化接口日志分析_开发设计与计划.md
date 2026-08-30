# Dating 结构化接口日志分析开发设计与实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Log 工具中实现不依赖 LLM 的 Dating Gateway/PUT 日志解析、Reply/Analysis 任务聚合、最终结果字段整理、确定性检查、页面展示和脱敏导出。

**Architecture:** 采用方案三。`gateway_log_parser.py` 提供与业务无关的行规范化、JSON 扫描、Gateway/PUT 配对和统一 `InterfaceCall`；`dating_log_analyzer.py` 在其上构建上传资源、异步任务和结果字段快照；`dating_log_rules.py` 只做确定性检查、脱敏和固定 Markdown 报告。Flask 路由与现有单页模板仅负责输入校验、权限复用和展示，不承载领域解析逻辑。

**Tech Stack:** Python 3.12、Python 标准库、Flask 3.x、Jinja2、原生 JavaScript、CSS、`unittest`、Docker Compose；不新增第三方依赖。

**Spec:** `Log_Tool_PRD/V5_Dating_结构化接口日志分析_PRD.md`

## Global Constraints

- 首期只支持 Dating Reply 和 Analysis，Schema 为 `dating.reply_generation.v1` 与 `dating.relationship_analysis.v1`。
- 分析过程不得调用 LLM、Skill、外部 HTTP 服务、数据库或对象存储。
- 最大日志大小默认 `10485760` bytes；单个 JSON 扫描最多 100000 行。
- 单个自由文本字段响应上限为 20000 字符；超限时截断并在对应字段节点标记 `value_truncated=true`。
- 必须区分 HTTP、Gateway 外层和 Gateway 子响应三层状态。
- 必须同时保留脱敏后的嵌套结果和扁平字段索引。
- 字段存在状态固定为 `PRESENT`、`NULL`、`EMPTY_STRING`、`EMPTY_ARRAY`、`EMPTY_OBJECT`、`MISSING`。
- 检查结果固定为 `PASS`、`FAIL`、`WARN`、`UNKNOWN`、`NA`；无证据不得返回 `FAIL` 或 `WARN`。
- 未知字段必须保留；未知 Schema 只能降级展示，不能套用旧规则。
- 不改变 `/people-search/analyze`、现有日志过滤、现有统计和原有导出契约。
- 所有响应和导出必须移除 token、Authorization/Cookie、签名 URL 查询参数和二进制/Base64 内容。
- 使用现有 `unittest`；不得引入 pytest 或前端构建工具。
- 修改代码时添加与现有风格一致的中文职责、参数、返回值、边界和异常注释。
- 工作区存在其他项目修改时不得暂存、提交或覆盖无关文件。

---

## 1. 当前实现基线

### 1.1 当前主流程

现有页面处理流程位于 `app.py`：

```text
浏览器 GET/POST /
→ extract_methods
→ split_log_blocks
→ filter_log_text / format_result_text
→ parse_log_blocks
→ build_interface_statistics
→ render_template("index.html")
```

现有通用统计只识别 `[HTTP] -->`、`[HTTP] <--` 等格式；虽然能从 JSON 中提取 `method_name`，但不能正确识别当前 Dating 日志的请求/响应方向和完整 payload。

### 1.2 可复用能力

| 能力 | 当前文件与位置 | V5 用法 |
|---|---|---|
| 控制台前缀清理 | `app.py:295-304` | 抽到公共解析器，`app.py` 兼容导入 |
| 日志行规范化 | `people_search_analyzer.py:73-105` | 抽到公共解析器，保持原签名 |
| JSON 平衡扫描 | `people_search_analyzer.py:108-160` | 抽到公共解析器，保持原签名 |
| Gateway 信封解包思路 | `people_search_analyzer.py:184-245` | 提炼为无业务依赖的返回式函数 |
| 专项接口接入模式 | `app.py:604-703` | 新增 `/dating/analyze`，复用错误处理与 CSRF |
| 固定导出目录 | `app.py:319-359,706-767` | 增加 Dating Markdown/JSON 类型 |
| 专项分析页面 | `templates/index.html:684-723,1000-1235` | 新增独立 Dating 结果区，不复用 People DOM ID |
| Flask 集成测试模式 | `tests/test_people_search_phase3.py` | 新增 Dating endpoint/page/export 测试 |
| Docker 显式 COPY | `Dockerfile:21-27` | COPY 三个新增 Python 模块 |

### 1.3 不应复用的内容

- People Insight `SUPPORTED_METHODS`。
- People Insight task selection、coverage、provider timeline 和候选规则。
- People Insight AI 配置、Skill 和 Evidence Packet。
- People Insight 报告模板。

Dating 可以复用纯解析原语，但不得导入 `people_search_rules.py` 或 `people_search_ai.py`。

---

## 2. 设计决策

### 2.1 文件级边界

```text
log_filter_tool/
├── gateway_log_parser.py                    # 新增：通用日志与传输层解析
├── dating_log_analyzer.py                   # 新增：Dating 上传、任务、Schema 和字段聚合
├── dating_log_rules.py                      # 新增：确定性规则、脱敏、固定报告
├── app.py                                   # 修改：配置、路由、导出类型
├── people_search_analyzer.py                # 修改：兼容导入公共解析原语
├── templates/index.html                     # 修改：Dating 分析 UI 与 JS
├── Dockerfile                               # 修改：复制新增模块
├── docker-compose.yml                       # 修改：增加 Dating 开关和大小配置
├── tests/
│   ├── fixtures/dating/
│   │   ├── reply_generation_multi_image_success.log
│   │   └── relationship_analysis_multi_image_success.log
│   ├── test_dating_fixtures.py              # 新增：夹具安全和黄金契约
│   ├── test_gateway_log_parser.py           # 新增：通用解析器
│   ├── test_dating_log_analyzer.py          # 新增：任务、字段、Schema
│   ├── test_dating_log_rules.py             # 新增：40 条确定性规则
│   ├── test_dating_report.py                # 新增：固定报告与脱敏
│   ├── test_dating_log_routes.py            # 新增：Flask、页面、导出、部署配置
│   └── test_log_filter.py                    # 修改：新增导出类型回归
└── docs/V5_Dating_结构化接口日志分析_开发设计与计划.md
```

`requirements.txt` 不修改。

### 2.2 依赖方向

```text
gateway_log_parser
        ↑
dating_log_analyzer
        ↑
dating_log_rules（读取 analyzer 结果，不反向调用 analyzer）
        ↑
app.py / templates

people_search_analyzer → gateway_log_parser 的兼容原语
people_search_rules 不依赖 Dating
```

禁止形成以下依赖：

```text
gateway_log_parser → app.py
gateway_log_parser → dating_log_analyzer
dating_log_analyzer → dating_log_rules
dating_* → people_search_*
```

### 2.3 为什么保留三个 Python 文件

- 通用传输解析与 Dating 业务结构变化频率不同。
- Analyzer 和 Rules 可以独立测试，避免 1000 行以上单文件再次混合解析、业务和报告。
- Flask 路由不包含领域实现，便于关闭功能或替换 UI。
- 这是职责拆分，不建立 parser/rules/provider 多层包或插件框架。

---

## 3. 公共接口和类型契约

项目继续使用普通 `dict`/`list`，不新增 dataclass、Pydantic 或外部 Schema 库。

### 3.1 `gateway_log_parser.py`

```python
PARSER_VERSION = "gateway-log-v1"
MAX_SCAN_LINES = 100000

def clean_log_line(line: str) -> str:
    """移除已知 Flutter 控制台前缀并保留 JSON 内容。"""

def normalize_log_lines(log_text: str) -> list[dict]:
    """返回含 line_no/raw/content/json_text/timestamp 的规范化日志行。"""

def scan_json_block(
    lines: list[dict],
    start_idx: int,
) -> tuple[object | None, int, int | None, int | None, str | None]:
    """保持 People 现有调用签名的 JSON 平衡扫描器。"""

def scan_named_json_block(
    lines: list[dict],
    start_idx: int,
    assignment_name: str,
) -> tuple[object | None, int, int | None, int | None, str | None]:
    """读取 headers={JSON 对象} 或 body={JSON 对象} 指定赋值对象。"""

def unwrap_gateway_envelope(payload: object) -> dict:
    """返回 Gateway 外层、请求子项、响应子项和 data，不修改入参。"""

def parse_interface_log(log_text: str) -> dict:
    """解析 Gateway、PUT 和 Flow marker，返回统一 calls/flow_steps/warnings。"""
```

`parse_interface_log()` 固定返回：

```python
{
    "parser_version": "gateway-log-v1",
    "calls": list[dict],
    "flow_steps": list[dict],
    "parse_warnings": list[dict],
}
```

### 3.2 InterfaceCall

所有 Gateway 逻辑子请求和 PUT 上传都进入同一个 `calls` 数组：

```python
{
    "call_id": "call_0007",
    "gateway_exchange_id": "gateway_0007",  # PUT 为 None
    "sequence": 7,
    "transport": "gateway",                # gateway/object_storage_put/unknown
    "service_name": "tool.dating.DatingAssistantService",
    "method_name": "CreateReplyTask",
    "request": {
        "timestamp": "2026-08-29T18:51:12.634+08:00",
        "line_start": 477,
        "line_end": 515,
        "client_request_id": "crid_fixture_001",
        "url": "https://gateway.example.test/dating/gateway/invoke",
        "headers": {},
        "params": {},
    },
    "response": {
        "timestamp": "2026-08-29T18:51:12.857+08:00",
        "line_start": 516,
        "line_end": 544,
        "http_status": 200,
        "elapsed_ms": 222.33,
        "headers": {},
        "gateway": {
            "code": 0,
            "message": "ok",
            "request_id": "gw_req_fixture_001",
            "trace_id": "trace_fixture_001",
        },
        "sub_response": {
            "id": "req_0",
            "success": True,
            "code": 0,
            "message": "ok",
        },
        "data": {},
    },
    "result_class": "success",
    "parse_status": "PARSED",
    "warnings": [],
}
```

### 3.3 `dating_log_analyzer.py`

```python
from collections.abc import Sequence

ANALYZER_VERSION = "dating-structured-v1"
REPLY_SCHEMA_VERSION = "dating.reply_generation.v1"
ANALYSIS_SCHEMA_VERSION = "dating.relationship_analysis.v1"
SUPPORTED_METHODS = (
    "GetUserPreferences", "GetMediaUploadConfig", "PrepareMediaUpload",
    "CompleteMediaUpload", "CreateReplyTask", "GetTask", "GetTaskResult",
    "CreateAnalysisTask", "GetAnalysisTask", "GetAnalysisResult",
)

def classify_presence(value: object, *, missing: bool = False) -> str:
    """将值分类为 PRESENT/NULL/EMPTY_STRING/EMPTY_ARRAY/EMPTY_OBJECT/MISSING。"""

def build_field_index(
    value: object,
    *,
    root_path: str,
    source: dict,
    known_paths: frozenset[str] | None = None,
    required_paths: Sequence[str] = (),
    max_depth: int = 50,
    max_fields: int = 20000,
) -> tuple[list[dict], list[dict]]:
    """返回字段节点和局部 warning；数组索引保留，未知字段不丢弃。"""

def build_interface_statistics(calls: list[dict]) -> list[dict]:
    """按 service_name + method_name 聚合调用数、状态和耗时。"""

def analyze_dating_log(
    log_text: str,
    requested_task_id: str | None = None,
) -> dict:
    """Dating 唯一公共分析入口；只调用本地确定性代码。"""
```

`analyze_dating_log()` 返回未脱敏内部结构；只有路由响应和导出前执行脱敏：

```python
{
    "analyzer_version": "dating-structured-v1",
    "parser_version": "gateway-log-v1",
    "supported": True,
    "detected_domain": "dating",
    "selection_error": None,
    "task_ids": ["dating_task_fixture_001"],
    "summary": {},
    "interface_statistics": [],
    "flow_steps": [],
    "calls": [],
    "task_snapshot": {},
    "parse_warnings": [],
}
```

`task_snapshot.result_fields` 的每个字段节点固定为：

```python
{
    "path": "result.overview.dashboard.effort.you_score",
    "parent_path": "result.overview.dashboard.effort",
    "key": "you_score",
    "array_index": None,
    "label": "你的投入度",
    "value": None,
    "value_type": "null",
    "presence": "NULL",
    "schema_known": True,
    "value_truncated": False,
    "source": {
        "method": "GetAnalysisResult",
        "call_id": "call_0030",
        "line_start": 2140,
        "line_end": 2188,
        "location_precision": "block",
    },
}
```

字段名严格使用 `path`；`json_path` 只用于 rule evidence 和 warning。`result_payload` 保留嵌套父子结构，`result_fields` 提供扁平检索，两者都在响应阶段执行敏感值处理和 20000 字符上限。

### 3.4 `dating_log_rules.py`

```python
RULESET_VERSION = "2026-08-29"

def run_dating_checks(analysis_result: dict) -> list[dict]:
    """运行 PRD §17 的所有固定规则，顺序稳定。"""

def compute_dating_verdict(checks: list[dict]) -> str:
    """返回 ISSUES_FOUND/WARNINGS_FOUND/INCOMPLETE_LOG/NO_ISSUES。"""

def render_dating_report(analysis_result: dict, checks: list[dict]) -> str:
    """渲染无 AI 章节的固定 Markdown。"""

def redact_dating_response(value: object) -> object:
    """递归复制并脱敏接口响应和导出结构，不修改 analyzer 内存原值。"""
```

### 3.5 Check Result

```python
{
    "rule_id": "REPLY-007",
    "priority": "P1",
    "outcome": "WARN",
    "title": "降级状态与警告一致性",
    "actual": {},
    "expected": "warning 表示结果降级时，degradation 应提供一致状态或明确区分降级范围",
    "evidence": [
        {
            "method": "GetTaskResult",
            "json_path": "responses[0].data.result.warnings",
            "value": ["SAFETY_DEGRADED"],
            "line_start": 1320,
            "line_end": 1436,
            "location_precision": "block",
        }
    ],
}
```

首期字段和规则证据至少提供响应 body 的 `block` 级行范围；不得为了显示精确行号编写不可靠的 key 搜索。后续如引入 JSON token path 定位器，可将部分证据升级为 `exact`。

---

## 4. 核心算法设计

### 4.1 单次扫描

`parse_interface_log()` 对规范化行只做一次顺序扫描：

```text
Gateway 请求 marker
→ 扫描整个请求 JSON
→ 入 pending_gateway_requests

Gateway 响应 marker
→ 解析 HTTP/elapsed_ms
→ 分别扫描 headers= 和 body=
→ 与最早未关闭 Gateway 请求组成 exchange
→ requests[].id 与 responses[].id 配对
→ 每个子请求生成一个 InterfaceCall

PUT 请求 marker
→ 扫描请求 JSON
→ 入 pending_put_requests

PUT 响应 marker
→ 解析 HTTP/elapsed_ms 和 headers
→ 与最早未关闭 PUT 请求组成 InterfaceCall

Flow marker
→ 生成 flow_step，不进入 InterfaceCall
```

复杂度目标为 O(日志行数 + JSON 字符数 + 字段节点数)。

### 4.2 Gateway 子请求配对

```python
request_by_id = {item["id"]: item for item in requests if item.get("id")}
response_by_id = {item["id"]: item for item in responses if item.get("id")}
```

- 先按 ID 配对。
- 重复 ID 产生 `AMBIGUOUS_PAIRING`。
- 没有 ID 时才按数组位置兜底，并产生 `POSITIONAL_PAIRING_FALLBACK`。
- 请求无响应产生 `UNMATCHED_REQUEST`。
- 响应无请求产生 `UNMATCHED_RESPONSE`。
- 一个 Gateway exchange 的所有逻辑调用共享 `gateway_exchange_id`，但具有独立 `call_id`。

### 4.3 result_class

优先级：

```text
parse_error
> no_response
> http_error
> gateway_error
> business_error
> success
> unknown
```

规则：

```python
if parse_status != "PARSED":
    return "parse_error"
if response is None:
    return "no_response"
if http_status is not None and not 200 <= http_status <= 299:
    return "http_error"
if gateway_code not in (None, 0):
    return "gateway_error"
if sub_success is False or sub_code not in (None, 0):
    return "business_error"
if 200 <= http_status <= 299:
    return "success"
return "unknown"
```

### 4.4 上传资源关联

`dating_log_analyzer.py` 只使用确定性证据：

1. `PrepareMediaUpload` 响应中的 asset_id、content_type、size_bytes。
2. Prepare 后最近的未关联 PUT。
3. PUT URL 去查询参数后的对象路径。
4. `CompleteMediaUpload.params.asset_id`。
5. `Create*Task.params.asset_ids`。

同一时间有多个未关闭 Prepare 且无法唯一匹配时，不猜测；PUT 保留为 orphan，生成 `AMBIGUOUS_UPLOAD_ASSOCIATION`。

### 4.5 任务选择

```text
0 个 task_id：supported 可为 true，task_snapshot=None
1 个 task_id：自动选择
多个 task_id + requested_task_id=None：selection_error=MULTIPLE_TASKS_FOUND
requested_task_id 存在：选择对应任务
requested_task_id 不存在：selection_error=TASK_NOT_FOUND
```

task_id 只从 Create/Poll/Result 的已知 request/response path 提取，不全文正则扫描。

### 4.6 任务时间线

- Reply：`CreateReplyTask → GetTask* → GetTaskResult`。
- Analysis：`CreateAnalysisTask → GetAnalysisTask* → GetAnalysisResult`。
- Poll 不去重。
- final sample 使用日志顺序最后一条 Poll。
- `duration_ms` 优先 `completed_time - create_time`，否则使用日志时间差。
- 状态比较时规范化为小写，但 `raw_status` 保留原值。
- `unchanged_poll_count` 为相邻 Poll 中 progress 未变化的次数。
- `longest_unchanged_progress` 为最长连续停滞对应的 progress 值。

### 4.7 字段索引

递归时同时生成容器节点与叶子节点：

```text
result.roles                         object/array 容器
result.roles[0]                      object
result.roles[0].replies              array
result.roles[0].replies[0].reply_id  string  PRESENT
```

Schema path 比较先将数组索引转换为 `[]`：

```python
result.roles[0].replies[2].text
→ result.roles[].replies[].text
```

已知 Schema 的必填 path 缺失时额外生成 `presence=MISSING` 节点。未知响应字段照常保留并标记 `schema_known=False`。

---

## 5. API、导出和页面契约

### 5.1 Flask 成功响应

`POST /dating/analyze` 严格返回 PRD §19.3 定义的直接 JSON 对象，不额外包裹 `code/data` 信封：

```json
{
  "analyzer_version": "dating-structured-v1",
  "parser_version": "gateway-log-v1",
  "ruleset_version": "2026-08-29",
  "supported": true,
  "detected_domain": "dating",
  "verdict": "WARNINGS_FOUND",
  "selection_error": null,
  "task_ids": ["dating_task_fixture_001"],
  "summary": {},
  "interface_statistics": [],
  "flow_steps": [],
  "calls": [],
  "task_snapshot": {},
  "checks": [],
  "parse_warnings": [],
  "report_markdown": "# Dating 结构化接口日志分析"
}
```

### 5.2 错误响应

```json
{
  "error_code": "MULTIPLE_TASKS_FOUND",
  "message": "日志包含多个 Dating 任务，请指定 task_id",
  "task_ids": ["dating_task_a", "dating_task_b"]
}
```

状态码严格按 PRD：400、413、422、503、500。

### 5.3 导出

`EXPORT_FILE_TYPES` 增加：

```python
"dating_analysis_report": ("dating_structured_analysis", ".md"),
"dating_analysis_json": ("dating_structured_analysis", ".json"),
```

页面保留最近一次脱敏分析对象：

```javascript
var latestDatingAnalysis = null;
var latestDatingReport = '';
```

- Markdown：导出 `latestDatingReport`。
- JSON：导出 `JSON.stringify(latestDatingAnalysis, null, 2)`。
- 不从原始日志重新构造导出内容。

### 5.4 页面 DOM

新增独立 ID，避免与 People 冲突：

```text
analyze-dating-btn
dating-analysis
dating-status
dating-summary
dating-interface-table
dating-upload-list
dating-task-timeline
dating-result-sections
dating-field-filter
dating-field-search
dating-field-table
dating-check-list
dating-report
copy-dating-report-btn
export-dating-report-btn
export-dating-json-btn
```

所有服务端文本通过 `textContent` 写入，禁止使用 `innerHTML` 渲染日志或业务结果。

### 5.5 原日志行定位

```javascript
function focusLogLines(startLine, endLine) {
  var textarea = document.getElementById('log_text');
  var lines = textarea.value.split('\n');
  var start = lines.slice(0, Math.max(startLine - 1, 0)).join('\n').length;
  if (startLine > 1) start += 1;
  var end = lines.slice(0, Math.max(endLine, startLine)).join('\n').length;
  textarea.focus();
  textarea.setSelectionRange(start, end);
  var lineHeight = parseFloat(getComputedStyle(textarea).lineHeight) || 20;
  textarea.scrollTop = Math.max(startLine - 2, 0) * lineHeight;
}
```

行号来自原始日志，不依赖当前 method 过滤结果。

---

## 6. 测试与验收策略

### 6.1 测试命令

单文件：

```bash
.venv/bin/python -m unittest tests.test_gateway_log_parser -v
```

全量：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Docker：

```bash
docker compose build log-filter-tool
docker compose up -d log-filter-tool
docker compose ps
```

### 6.2 黄金值

Reply：

```text
gateway_call_count=19
upload_call_count=2
poll_count=11
queued=1 processing=9 succeeded=1
duration_ms=11781
reply_count=4
top_pick_reply_id=reply_1
```

Analysis：

```text
gateway_call_count=30
upload_call_count=3
poll_count=21
queued=1 processing=19 succeeded=1
duration_ms=23337
uploaded_asset_count=3
analyzed_message_count=38
user=19 other=19
```

### 6.3 PRD 覆盖映射

| PRD 能力 | 负责任务 |
|---|---|
| FR-001～FR-003 | Task 2、Task 3 |
| FR-004～FR-005 | Task 4 |
| FR-006～FR-008、FR-014 | Task 5 |
| FR-009～FR-010 | Task 6、Task 7 |
| FR-011 | Task 9 |
| FR-012～FR-013 | Task 7、Task 8、Task 9 |
| FR-015 | 全局约束、Task 8、Task 10 |
| AC-001～AC-010 | Task 3～Task 7 |
| AC-011～AC-016 | Task 6～Task 10 |
| AC-017～AC-018 | Task 8～Task 10 |

---

## 7. 任务依赖与提交顺序

```text
Task 1 夹具
  ↓
Task 2 公共原语与 People 兼容
  ↓
Task 3 Gateway/PUT InterfaceCall
  ↓
Task 4 Dating 上传与任务快照
  ↓
Task 5 Schema 和字段索引
  ↓
Task 6 通用/任务规则
  ↓
Task 7 Reply/Analysis 规则与报告
  ↓
Task 8 Flask/导出
  ↓
Task 9 页面
  ↓
Task 10 打包、全量回归、本地部署验收
```

任务具有强顺序依赖；执行时不要让多个实现者同时修改 `app.py`、`dating_log_analyzer.py`、`dating_log_rules.py` 或 `templates/index.html`。

---

## 8. 逐任务实施计划

### Task 1: 建立脱敏黄金夹具和不可变验收契约

**Files:**

- Create: `tests/fixtures/dating/reply_generation_multi_image_success.log`
- Create: `tests/fixtures/dating/relationship_analysis_multi_image_success.log`
- Create: `tests/test_dating_fixtures.py`

**Interfaces:**

- Consumes: PRD §2.2 两份原始日志。
- Produces: 后续所有 parser/analyzer/rules 测试使用的稳定脱敏夹具。

- [ ] **Step 1: 从指定原始日志创建完整夹具副本并执行稳定脱敏**

复制来源：

```text
/Users/admin/Testproject/Truthy_ApiAutoTest2/logs/dating/test/2026-08-29/20260829_185108_082227_test_332.log
/Users/admin/Testproject/Truthy_ApiAutoTest2/logs/dating/test/2026-08-29/20260829_185318_825054_test_445.log
```

替换规则：

```text
auth_token 的值                     → ***
Authorization/Cookie 的值           → ***
签名 URL 第一个 ? 之后的所有内容     → [REDACTED]
user_id                              → dating_user_fixture
device_id                            → dating_device_fixture
```

不得修改 method、task_id、result_id、asset_id、请求/响应顺序、JSON 层级、状态、计数、时间和业务结果文本。

- [ ] **Step 2: 编写夹具安全和黄金 marker 测试**

```python
from pathlib import Path
import re
import unittest


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dating"


class DatingFixtureTests(unittest.TestCase):
    def test_reply_fixture_is_complete_and_sanitized(self):
        text = (FIXTURE_DIR / "reply_generation_multi_image_success.log").read_text(
            encoding="utf-8"
        )
        self.assertEqual(text.count("Gateway 请求数据:"), 19)
        self.assertEqual(text.count("PUT 上传请求数据:"), 2)
        self.assertIn('"method_name": "GetTaskResult"', text)
        self.assertIn('"schema_version": "dating.reply_generation.v1"', text)
        self.assertNotRegex(text, r'"auth_token"\s*:\s*"(?!\*\*\*)')
        self.assertNotRegex(text, r"q-signature=|q-ak=|q-sign-time=")

    def test_analysis_fixture_is_complete_and_sanitized(self):
        text = (
            FIXTURE_DIR / "relationship_analysis_multi_image_success.log"
        ).read_text(encoding="utf-8")
        self.assertEqual(text.count("Gateway 请求数据:"), 30)
        self.assertEqual(text.count("PUT 上传请求数据:"), 3)
        self.assertIn('"method_name": "GetAnalysisResult"', text)
        self.assertIn('"schema_version": "dating.relationship_analysis.v1"', text)
        self.assertNotRegex(text, r'"auth_token"\s*:\s*"(?!\*\*\*)')
        self.assertNotRegex(text, r"q-signature=|q-ak=|q-sign-time=")
```

- [ ] **Step 3: 运行夹具测试**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_fixtures -v
```

Expected: 2 tests PASS；任何有效 token 或签名参数都使测试失败。

- [ ] **Step 4: 检查夹具差异只包含允许的脱敏变化**

Run:

```bash
git diff --check -- tests/fixtures/dating tests/test_dating_fixtures.py
```

Expected: exit 0。

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/dating tests/test_dating_fixtures.py
git commit -m "test: add sanitized dating log fixtures"
```

### Task 2: 抽取公共日志与 JSON 解析原语并保持 People 兼容

**Files:**

- Create: `gateway_log_parser.py`
- Create: `tests/test_gateway_log_parser.py`
- Modify: `app.py:1-39,295-304`
- Modify: `people_search_analyzer.py:15-21,61-160,184-245`
- Test: `tests/test_log_filter.py`
- Test: `tests/test_people_search_phase1.py`
- Test: `tests/test_people_search_review_fixes.py`

**Interfaces:**

- Consumes: `app.clean_log_line`、People `normalize_log_lines`/`scan_json_block` 的当前行为。
- Produces: `clean_log_line()`、`normalize_log_lines()`、`scan_json_block()`、`scan_named_json_block()`、`unwrap_gateway_envelope()`。

- [ ] **Step 1: 先写公共原语的失败测试**

在 `tests/test_gateway_log_parser.py` 写入：

```python
import unittest

from gateway_log_parser import (
    clean_log_line,
    normalize_log_lines,
    scan_json_block,
    scan_named_json_block,
    unwrap_gateway_envelope,
)


class SharedParserPrimitiveTests(unittest.TestCase):
    def test_scan_json_block_ignores_braces_inside_strings(self):
        lines = normalize_log_lines('marker\n{"text":"a } b", "ok":true}\nafter')
        value, end_idx, start_line, end_line, error = scan_json_block(lines, 1)
        self.assertIsNone(error)
        self.assertEqual(value, {"text": "a } b", "ok": True})
        self.assertEqual((start_line, end_line), (2, 2))

    def test_scan_named_body_skips_headers(self):
        lines = normalize_log_lines(
            'Gateway 响应数据: HTTP 200 elapsed_ms=1.25\n'
            'headers={"Content-Type":"application/json"}\n'
            'body={"code":0,"responses":[]}'
        )
        value, _, start_line, end_line, error = scan_named_json_block(lines, 1, "body")
        self.assertIsNone(error)
        self.assertEqual(value["code"], 0)
        self.assertEqual((start_line, end_line), (3, 3))

    def test_unwrap_gateway_envelope_preserves_three_layers(self):
        result = unwrap_gateway_envelope({
            "code": 0,
            "message": "ok",
            "request_id": "gw_req_1",
            "trace_id": "trace_1",
            "responses": [{
                "id": "req_0", "success": True, "code": 0,
                "message": "ok", "data": {"status": "queued"},
            }],
        })
        self.assertEqual(result["gateway"]["code"], 0)
        self.assertEqual(result["responses"][0]["data"]["status"], "queued")
```

- [ ] **Step 2: 运行测试确认缺少公共模块**

Run:

```bash
.venv/bin/python -m unittest tests.test_gateway_log_parser.SharedParserPrimitiveTests -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gateway_log_parser'`。

- [ ] **Step 3: 创建公共模块并迁移纯函数**

最小模块骨架：

```python
"""通用接口日志解析原语与 Gateway/PUT 传输解析。

本模块不得导入 Flask、app.py 或任何 People/Dating 领域模块。
"""

from __future__ import annotations

import json
import re


PARSER_VERSION = "gateway-log-v1"
MAX_SCAN_LINES = 100000
CONSOLE_PREFIX_PATTERN = re.compile(r"^.*?\bflutter:\s?")
RE_LOGGER_PREFIX = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]\d+)\s*\|\s*(\w+)\s*\|\s*([\w.]+)\s*\|\s*"
)
RE_FLUTTER_TIMESTAMP = re.compile(r"\t(\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{4})\t")


def clean_log_line(line: str) -> str:
    return CONSOLE_PREFIX_PATTERN.sub("", line or "").rstrip()
```

将 People 当前 `normalize_log_lines()` 和 `scan_json_block()` 实现原样迁移；新增 `scan_named_json_block()` 时只允许匹配精确的 `assignment_name=` 前缀。

`unwrap_gateway_envelope()` 必须返回新 dict，不修改 payload：

```python
def unwrap_gateway_envelope(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {"gateway": None, "requests": [], "responses": [], "data": payload}
    return {
        "gateway": {
            "code": payload.get("code"),
            "message": payload.get("message"),
            "request_id": payload.get("request_id"),
            "trace_id": payload.get("trace_id"),
        },
        "requests": payload.get("requests") if isinstance(payload.get("requests"), list) else [],
        "responses": payload.get("responses") if isinstance(payload.get("responses"), list) else [],
        "data": payload.get("data") if "data" in payload else payload,
    }
```

- [ ] **Step 4: 让 app.py 兼容导入 clean_log_line**

在 `app.py` 顶部加入：

```python
from gateway_log_parser import clean_log_line
```

删除原 `CONSOLE_PREFIX_PATTERN` 和本地 `clean_log_line()` 定义。因为导入名仍位于 `app` 模块命名空间，现有 `from app import clean_log_line` 调用方保持兼容。

- [ ] **Step 5: 让 People analyzer 使用公共 normalize/scan，并保留 wrapper**

```python
from gateway_log_parser import (
    normalize_log_lines,
    scan_json_block,
    unwrap_gateway_envelope,
)
```

删除 People 中重复的 normalize/scan 常量和函数。保留 `unwrap_gateway_payload(record)` 名称，但内部改为使用公共返回值，并继续填充当前 `record["gateway"]`、`record["data"]`、request_id、trace_id，保证现有 snapshot 契约不变。

- [ ] **Step 6: 运行公共原语测试**

Run:

```bash
.venv/bin/python -m unittest tests.test_gateway_log_parser.SharedParserPrimitiveTests -v
```

Expected: PASS。

- [ ] **Step 7: 运行 People 和通用解析回归**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_log_filter \
  tests.test_people_search_phase1 \
  tests.test_people_search_review_fixes -v
```

Expected: 全部 PASS；People snapshot、marker、行号和脱敏测试无变化。

- [ ] **Step 8: Commit**

```bash
git add gateway_log_parser.py app.py people_search_analyzer.py tests/test_gateway_log_parser.py
git commit -m "refactor: extract shared gateway log parser primitives"
```

### Task 3: 实现 Gateway/PUT 交换解析和统一 InterfaceCall

**Files:**

- Modify: `gateway_log_parser.py`
- Modify: `tests/test_gateway_log_parser.py`

**Interfaces:**

- Consumes: Task 2 公共原语。
- Produces: `parse_interface_log(log_text) -> {parser_version,calls,flow_steps,parse_warnings}`。

- [ ] **Step 1: 编写黄金调用计数和字段失败测试**

```python
from pathlib import Path

from gateway_log_parser import parse_interface_log


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dating"


class DatingTransportParsingTests(unittest.TestCase):
    def test_reply_fixture_produces_gateway_and_put_calls(self):
        text = (FIXTURE_DIR / "reply_generation_multi_image_success.log").read_text(
            encoding="utf-8"
        )
        parsed = parse_interface_log(text)
        gateway = [c for c in parsed["calls"] if c["transport"] == "gateway"]
        puts = [c for c in parsed["calls"] if c["transport"] == "object_storage_put"]
        self.assertEqual(len({c["gateway_exchange_id"] for c in gateway}), 19)
        self.assertEqual(len(gateway), 19)
        self.assertEqual(len(puts), 2)
        create = next(c for c in gateway if c["method_name"] == "CreateReplyTask")
        self.assertEqual(create["response"]["http_status"], 200)
        self.assertEqual(create["response"]["gateway"]["code"], 0)
        self.assertTrue(create["response"]["sub_response"]["success"])
        self.assertEqual(create["result_class"], "success")

    def test_analysis_fixture_produces_thirty_gateway_calls(self):
        text = (
            FIXTURE_DIR / "relationship_analysis_multi_image_success.log"
        ).read_text(encoding="utf-8")
        parsed = parse_interface_log(text)
        gateway = [c for c in parsed["calls"] if c["transport"] == "gateway"]
        puts = [c for c in parsed["calls"] if c["transport"] == "object_storage_put"]
        self.assertEqual(len({c["gateway_exchange_id"] for c in gateway}), 30)
        self.assertEqual(len(puts), 3)
```

- [ ] **Step 2: 运行测试确认 parse_interface_log 尚未实现**

Run:

```bash
.venv/bin/python -m unittest tests.test_gateway_log_parser.DatingTransportParsingTests -v
```

Expected: FAIL with missing `parse_interface_log`。

- [ ] **Step 3: 增加 marker、记录构造和 result_class 函数**

```python
RE_GATEWAY_REQUEST = re.compile(r"^Gateway 请求数据:\s*$")
RE_GATEWAY_RESPONSE = re.compile(
    r"^Gateway 响应数据:\s*HTTP\s+(\d{3})\s+elapsed_ms=([\d.]+)\s*$"
)
RE_PUT_REQUEST = re.compile(r"^PUT 上传请求数据:\s*$")
RE_PUT_RESPONSE = re.compile(
    r"^PUT 上传响应:\s*HTTP\s+(\d{3})\s+elapsed_ms=([\d.]+)\s*$"
)
RE_FLOW_START = re.compile(r"^开始 Flow 步骤:.*?step=([^\s]+)\s+\((\d+)/(\d+)\)")
RE_FLOW_END = re.compile(r"^完成 Flow 步骤:\s*step=([^\s]+)")
RE_FLOW_SKIP = re.compile(r"^因条件跳过 Flow 步骤:\s*step=([^\s]+)")


def classify_result(call: dict) -> str:
    if call.get("parse_status") != "PARSED":
        return "parse_error"
    response = call.get("response")
    if response is None:
        return "no_response"
    http_status = response.get("http_status")
    if http_status is not None and not 200 <= http_status <= 299:
        return "http_error"
    gateway = response.get("gateway") or {}
    if gateway.get("code") not in (None, 0):
        return "gateway_error"
    sub_response = response.get("sub_response") or {}
    if sub_response.get("success") is False or sub_response.get("code") not in (None, 0):
        return "business_error"
    if http_status is not None and 200 <= http_status <= 299:
        return "success"
    return "unknown"
```

- [ ] **Step 4: 实现单次扫描和外层请求响应配对**

```python
def parse_interface_log(log_text: str) -> dict:
    lines = normalize_log_lines(log_text)
    pending_gateway: list[dict] = []
    pending_put: list[dict] = []
    calls: list[dict] = []
    flow_steps: list[dict] = []
    warnings: list[dict] = []
    # 顺序扫描 marker；每次 JSON 扫描后将 idx 跳到 end_idx + 1。
    # Gateway 响应分别调用 scan_named_json_block(lines, idx, "headers") 与 body 分支。
    # 最后将 pending 项转换为 no_response 调用。
    return {
        "parser_version": PARSER_VERSION,
        "calls": calls,
        "flow_steps": flow_steps,
        "parse_warnings": warnings,
    }
```

代码中必须实现注释列出的每一步，不保留伪代码。

- [ ] **Step 5: 实现子请求按 ID 配对并补充乱序/缺失测试**

增加内联最小日志测试：

```python
def test_subresponses_are_paired_by_id_not_array_position(self):
    log = make_gateway_exchange(
        requests=[
            {"id": "a", "service_name": "svc", "method_name": "First", "params": {}},
            {"id": "b", "service_name": "svc", "method_name": "Second", "params": {}},
        ],
        responses=[
            {"id": "b", "success": True, "code": 0, "message": "ok", "data": {"v": 2}},
            {"id": "a", "success": True, "code": 0, "message": "ok", "data": {"v": 1}},
        ],
    )
    calls = parse_interface_log(log)["calls"]
    by_method = {c["method_name"]: c for c in calls}
    self.assertEqual(by_method["First"]["response"]["data"]["v"], 1)
    self.assertEqual(by_method["Second"]["response"]["data"]["v"], 2)
```

同一测试文件提供 `make_gateway_exchange()`，用 `json.dumps(payload, indent=2)` 生成真实 marker/body，不手写不完整 JSON。

- [ ] **Step 6: 实现 PUT 和 Flow 解析**

PUT `service_name` 固定为 `object_storage`、`method_name` 固定为 `PUT`、`gateway_exchange_id=None`。PUT 响应无 body 时 `data=None`，但 HTTP 2xx 应为 success。

Flow 记录结构：

```python
{
    "step": "create_reply",
    "event": "start",  # start/complete/skip
    "current": 6,
    "total": 8,
    "timestamp": "2026-08-29T18:51:08.082+08:00",
    "line": 476,
}
```

- [ ] **Step 7: 运行 parser 全部测试**

Run:

```bash
.venv/bin/python -m unittest tests.test_gateway_log_parser -v
```

Expected: PASS；Reply 19+2、Analysis 30+3，乱序配对正确。

- [ ] **Step 8: 运行 People 回归**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_people_search_phase1 \
  tests.test_people_search_phase2 \
  tests.test_people_search_review_fixes -v
```

Expected: PASS。

- [ ] **Step 9: Commit**

```bash
git add gateway_log_parser.py tests/test_gateway_log_parser.py
git commit -m "feat: parse gateway and upload interface calls"
```

### Task 4: 聚合 Dating 上传资源和异步任务生命周期

**Files:**

- Create: `dating_log_analyzer.py`
- Create: `tests/test_dating_log_analyzer.py`

**Interfaces:**

- Consumes: `gateway_log_parser.parse_interface_log()`。
- Produces: `build_upload_assets()`、`select_dating_task()`、`build_task_snapshot()`、基础 `analyze_dating_log()`。

- [ ] **Step 1: 编写 Reply/Analysis 生命周期失败测试**

```python
from pathlib import Path
import unittest

from dating_log_analyzer import analyze_dating_log


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dating"


class DatingTaskAggregationTests(unittest.TestCase):
    def test_reply_task_lifecycle_and_assets(self):
        result = analyze_dating_log(
            (FIXTURE_DIR / "reply_generation_multi_image_success.log").read_text(
                encoding="utf-8"
            )
        )
        task = result["task_snapshot"]
        self.assertEqual(task["task_id"], "dating_task_147b21ac92063a1b24bbb8f8865e3bde")
        self.assertEqual(task["task_type"], "reply_generation")
        self.assertEqual(task["lifecycle"]["poll_count"], 11)
        self.assertEqual(task["lifecycle"]["final_status"], "succeeded")
        self.assertEqual(task["lifecycle"]["final_progress_percent"], 100)
        self.assertEqual(task["lifecycle"]["duration_ms"], 11781)
        self.assertEqual(len(task["input_assets"]), 2)
        self.assertTrue(all(a["upload_state"] == "complete" for a in task["input_assets"]))

    def test_analysis_task_lifecycle_and_assets(self):
        result = analyze_dating_log(
            (FIXTURE_DIR / "relationship_analysis_multi_image_success.log").read_text(
                encoding="utf-8"
            )
        )
        task = result["task_snapshot"]
        self.assertEqual(task["task_type"], "relationship_analysis")
        self.assertEqual(task["lifecycle"]["poll_count"], 21)
        self.assertEqual(task["lifecycle"]["duration_ms"], 23337)
        self.assertEqual(len(task["input_assets"]), 3)
```

- [ ] **Step 2: 运行测试确认模块缺失**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_analyzer.DatingTaskAggregationTests -v
```

Expected: FAIL with `ModuleNotFoundError`。

- [ ] **Step 3: 创建 analyzer 常量和辅助选择函数**

```python
from __future__ import annotations

from collections import Counter
from datetime import datetime

from gateway_log_parser import PARSER_VERSION, parse_interface_log


ANALYZER_VERSION = "dating-structured-v1"
REPLY_SCHEMA_VERSION = "dating.reply_generation.v1"
ANALYSIS_SCHEMA_VERSION = "dating.relationship_analysis.v1"
SUPPORTED_METHODS = (
    "GetUserPreferences",
    "GetMediaUploadConfig",
    "PrepareMediaUpload",
    "CompleteMediaUpload",
    "CreateReplyTask",
    "GetTask",
    "GetTaskResult",
    "CreateAnalysisTask",
    "GetAnalysisTask",
    "GetAnalysisResult",
)
```

实现以下内部函数，输入、输出和算法边界固定：

| 函数 | 输入/输出 | 实现要求 |
|---|---|---|
| `_gateway_calls` | `calls, method -> list[dict]` | 只返回 `transport=gateway`，传 method 时再精确过滤 |
| `_call_task_ids` | `call -> list[str]` | 仅读取已知 Create/Poll/Result params 与 data path，按出现顺序去重 |
| `select_dating_task` | `calls, requested_task_id -> selected_id, all_ids, error` | 实现 §4.5 的 0/1/多任务和显式选择分支 |
| `build_upload_assets` | `calls, selected_task_id -> assets, warnings` | 按 Prepare → 最近唯一 PUT → Complete → Create task 关联，歧义不猜测 |
| `build_task_snapshot` | `calls, assets, task_id -> snapshot, warnings` | 聚合 Create、全部 Poll、Result、终态、时间线、停滞统计与 Result 原值 |
| `build_analysis_summary` | `calls, task_snapshot, warnings -> summary` | 统一计算 PRD §19.3 的调用、错误、配对、任务、结果和 warning 计数 |

- [ ] **Step 4: 实现上传状态与 task asset 使用关系**

上传状态计算：

```python
if prepare_ok and put_ok and complete_ok:
    upload_state = "complete"
elif put_status is not None and not 200 <= put_status <= 299:
    upload_state = "put_failed"
elif complete_seen and not complete_ok:
    upload_state = "complete_failed"
elif put_seen and asset_id is None:
    upload_state = "orphan_put"
elif prepare_seen and not put_seen:
    upload_state = "prepare_only"
else:
    upload_state = "unknown"
```

`used_by_task` 只根据 Create task 的 `asset_ids` 判断。

- [ ] **Step 5: 实现状态样本和进度诊断**

状态样本必须保留每次 Poll。增加测试：

```python
samples = result["task_snapshot"]["status_samples"]
self.assertEqual(Counter(s["status"] for s in samples), {
    "queued": 1,
    "processing": 9,
    "succeeded": 1,
})
self.assertEqual(
    result["task_snapshot"]["progress_diagnostics"]["distinct_progress_values"],
    [5, 30, 100],
)
```

Analysis 对应 `processing=19`。

- [ ] **Step 6: 实现基础 analyze_dating_log**

```python
def analyze_dating_log(log_text: str, requested_task_id: str | None = None) -> dict:
    parsed = parse_interface_log(log_text)
    calls = parsed["calls"]
    supported = any(
        call.get("method_name") in SUPPORTED_METHODS
        or call.get("transport") == "object_storage_put"
        for call in calls
    )
    selected_task_id, task_ids, selection_error = select_dating_task(
        calls, requested_task_id
    )
    warnings = list(parsed["parse_warnings"])
    assets, asset_warnings = build_upload_assets(calls, selected_task_id)
    warnings.extend(asset_warnings)
    task_snapshot = None
    if selected_task_id is not None:
        task_snapshot, task_warnings = build_task_snapshot(
            calls, assets, selected_task_id
        )
        warnings.extend(task_warnings)
    summary = build_analysis_summary(calls, task_snapshot, warnings)
    return {
        "analyzer_version": ANALYZER_VERSION,
        "parser_version": PARSER_VERSION,
        "supported": supported,
        "detected_domain": "dating" if supported else None,
        "selection_error": selection_error,
        "task_ids": task_ids,
        "summary": summary,
        "interface_statistics": build_interface_statistics(calls),
        "flow_steps": parsed["flow_steps"],
        "calls": calls,
        "task_snapshot": task_snapshot,
        "parse_warnings": warnings,
    }
```

- [ ] **Step 7: 增加多任务、TASK_NOT_FOUND 和未完成任务测试**

将两个夹具拼接：无 task_id 时断言 `MULTIPLE_TASKS_FOUND`；显式传 Reply task_id 时只选择 Reply；传未知 ID 时断言 `TASK_NOT_FOUND`。用裁剪到最后一次 processing Poll 的最小日志断言 `terminal=False` 且没有伪造结果。

- [ ] **Step 8: 运行 analyzer 生命周期测试**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_analyzer -v
```

Expected: 生命周期、资源和任务选择全部 PASS。

- [ ] **Step 9: Commit**

```bash
git add dating_log_analyzer.py tests/test_dating_log_analyzer.py
git commit -m "feat: build dating task and upload snapshots"
```

### Task 5: 实现 Result Schema 投影、字段索引和空值健康摘要

**Files:**

- Modify: `dating_log_analyzer.py`
- Modify: `tests/test_dating_log_analyzer.py`

**Interfaces:**

- Consumes: Task 4 `task_snapshot` 和最后一个成功 Result 调用。
- Produces: `classify_presence()`、`build_field_index()`、Reply/Analysis result summary、未知 Schema 兜底。

- [ ] **Step 1: 编写字段存在状态失败测试**

```python
from dating_log_analyzer import classify_presence


class PresenceClassificationTests(unittest.TestCase):
    def test_presence_states_are_distinct(self):
        self.assertEqual(classify_presence("value"), "PRESENT")
        self.assertEqual(classify_presence(None), "NULL")
        self.assertEqual(classify_presence(""), "EMPTY_STRING")
        self.assertEqual(classify_presence([]), "EMPTY_ARRAY")
        self.assertEqual(classify_presence({}), "EMPTY_OBJECT")
        self.assertEqual(classify_presence(None, missing=True), "MISSING")

    def test_long_text_is_truncated_with_marker(self):
        fields, warnings = build_field_index(
            {"note": "x" * 20001},
            root_path="result",
            source=fixture_source(),
        )
        note = next(field for field in fields if field["path"] == "result.note")
        self.assertEqual(len(note["value"]), 20000)
        self.assertTrue(note["value_truncated"])
        self.assertIn("VALUE_TRUNCATED", {item["code"] for item in warnings})
```

- [ ] **Step 2: 编写 Reply 和 Analysis 黄金字段失败测试**

```python
class DatingResultProjectionTests(unittest.TestCase):
    def test_reply_result_summary_and_empty_fields(self):
        task = analyze_reply_fixture()["task_snapshot"]
        summary = task["result_summary"]
        self.assertEqual(task["schema_version"], "dating.reply_generation.v1")
        self.assertEqual(summary["reply_count"], 4)
        self.assertEqual(summary["top_pick_reply_id"], "reply_1")
        fields = {f["path"]: f for f in task["result_fields"]}
        self.assertEqual(fields["result.context.requested_intent"]["presence"], "EMPTY_STRING")
        self.assertEqual(fields["result.association.person_id"]["presence"], "NULL")

    def test_analysis_result_summary_and_empty_fields(self):
        task = analyze_analysis_fixture()["task_snapshot"]
        summary = task["result_summary"]
        self.assertEqual(summary["relationship_stage"], "ENDED")
        self.assertEqual(summary["analyzed_message_count"], 38)
        fields = {f["path"]: f for f in task["result_fields"]}
        self.assertEqual(
            fields["result.overview.dashboard.effort.you_score"]["presence"], "NULL"
        )
        self.assertEqual(
            fields["result.chat_signals.risk_signals"]["presence"], "EMPTY_ARRAY"
        )
```

- [ ] **Step 3: 运行测试确认字段接口未实现**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_dating_log_analyzer.PresenceClassificationTests \
  tests.test_dating_log_analyzer.DatingResultProjectionTests -v
```

Expected: FAIL with missing functions/keys。

- [ ] **Step 4: 定义 Schema path 集合和必填 path**

在 `dating_log_analyzer.py` 集中定义：

```python
MAX_TEXT_VALUE_CHARS = 20000
REPLY_REQUIRED_PATHS = (
    "result.schema_version",
    "result.context",
    "result.roles",
    "result.association",
    "result.degradation",
    "result.warnings",
)
ANALYSIS_REQUIRED_PATHS = (
    "result.schema_version",
    "result.analysis_scope",
    "result.overview",
    "result.chat_signals",
    "result.key_events",
    "result.warnings",
)
```

已知 path 集合至少覆盖 PRD §14～§15 的完整样本字段；数组索引统一使用 `[]` 模板。

- [ ] **Step 5: 实现递归字段索引**

核心递归必须：

```python
def visit(current: object, path: str, parent_path: str | None, depth: int) -> None:
    if depth > max_depth:
        warnings.append({"code": "MAX_FIELD_DEPTH_REACHED", "json_path": path})
        return
    if len(fields) >= max_fields:
        warnings.append({"code": "MAX_FIELD_COUNT_REACHED", "json_path": path})
        return
    field, field_warning = make_field_node(current, path, parent_path, source, known_paths)
    fields.append(field)
    if field_warning is not None:
        warnings.append(field_warning)
    if isinstance(current, dict):
        for key, child in current.items():
            visit(child, join_object_path(path, key), path, depth + 1)
    elif isinstance(current, list):
        for index, child in enumerate(current):
            visit(child, f"{path}[{index}]", path, depth + 1)
```

`make_field_node()` 对字符串值执行 20000 字符限制，设置 `value_truncated` 并返回 `VALUE_TRUNCATED` warning；遍历后为未出现的 required path 追加 `MISSING` 节点。初版所有字段 `location_precision="block"`。

- [ ] **Step 6: 实现 Reply projector**

```python
def _project_reply_result(result_payload: dict) -> tuple[dict, list[dict]]:
    roles = result_payload.get("roles") if isinstance(result_payload.get("roles"), list) else []
    replies = [reply for role in roles for reply in (role.get("replies") or [])]
    top_pick = next((reply for reply in replies if reply.get("is_top_pick") is True), None)
    context = result_payload.get("context") or {}
    association = result_payload.get("association") or {}
    degradation = result_payload.get("degradation") or {}
    return {
        "conversation_stage": context.get("conversation_stage"),
        "moment_type": context.get("moment_type"),
        "reply_state": context.get("reply_state"),
        "requested_intent": context.get("requested_intent"),
        "effective_goal": context.get("effective_goal"),
        "signal_count": len(context.get("signals") or []),
        "role_count": len(roles),
        "reply_count": len(replies),
        "top_pick_reply_id": top_pick.get("reply_id") if top_pick else None,
        "person_history_used": association.get("person_history_used"),
        "is_degraded": degradation.get("is_degraded"),
        "warning_count": len(result_payload.get("warnings") or []),
    }, build_reply_sections(result_payload)
```

- [ ] **Step 7: 实现 Analysis projector**

按 PRD §15.3 返回全部摘要计数；所有数组先验证类型再计数。`message_counts`、signals 和 key_events 缺失时返回 `None` 或 0 的选择必须由 Schema path 是否存在决定，不能把缺失和空数组混同。

- [ ] **Step 8: 实现未知 Schema 兜底测试和逻辑**

构造 `schema_version="dating.relationship_analysis.v2"` 的最小 Result，断言：

```python
self.assertEqual(task["schema_status"], "UNKNOWN_SCHEMA")
self.assertEqual(task["result_summary"], {})
self.assertGreater(len(task["result_fields"]), 0)
self.assertIn("UNKNOWN_SCHEMA_VERSION", warning_codes)
```

- [ ] **Step 9: 运行 analyzer 全部测试**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_analyzer -v
```

Expected: 两种 Schema、空值、Missing、未知字段和未知 Schema 全部 PASS。

- [ ] **Step 10: Commit**

```bash
git add dating_log_analyzer.py tests/test_dating_log_analyzer.py
git commit -m "feat: structure dating result schemas and fields"
```

### Task 6：实现确定性规则框架与通用、任务、结果规则

**Files:**

- Create: `dating_log_rules.py`
- Create: `tests/test_dating_log_rules.py`
- Modify: `dating_log_analyzer.py`

**目标：** 把 PRD §16 的规则统一落为稳定、可测试、无 LLM 依赖的检查结果；本任务先实现通用层、任务层和结果层 24 条规则，业务 Schema 规则留给 Task 7。

**公开接口：**

```python
def run_dating_checks(analysis: dict) -> list[dict]:
    """按固定顺序执行全部 Dating 规则并返回结构化检查列表。"""


def compute_dating_verdict(checks: list[dict]) -> str:
    """按 PRD §19.3 计算 ISSUES_FOUND、WARNINGS_FOUND、INCOMPLETE_LOG 或 NO_ISSUES。"""
```

检查项契约固定为：

```python
{
    "rule_id": "TASK-003",
    "priority": "P0",
    "title": "轮询状态转换合法",
    "outcome": "PASS | FAIL | WARN | UNKNOWN | NA",
    "actual": "QUEUED -> PROCESSING -> SUCCEEDED",
    "expected": "只允许配置表中的合法状态转换",
    "evidence": [
        {
            "method": "GetTask",
            "json_path": "responses[0].data.status",
            "value": "SUCCEEDED",
            "line_start": 410,
            "line_end": 438,
            "location_precision": "block"
        }
    ]
}
```

- [ ] **Step 1: 编写规则框架失败测试**

在 `tests/test_dating_log_rules.py` 中覆盖：

```python
class DatingRuleFrameworkTest(unittest.TestCase):
    def test_every_check_has_stable_contract(self):
        checks = run_dating_checks(load_reply_analysis())
        required = {"rule_id", "priority", "title", "outcome", "actual", "expected", "evidence"}
        self.assertTrue(checks)
        for check in checks:
            self.assertEqual(set(check), required)
            self.assertIn(check["outcome"], CHECK_OUTCOMES)

    def test_rule_order_is_stable(self):
        checks = run_dating_checks(load_reply_analysis())
        self.assertEqual(
            [item["rule_id"] for item in checks[:24]],
            [
                "PARSE-001", "PAIR-001", "HTTP-001", "GATEWAY-001",
                "SUBRESP-001", "TRACE-001", "UPLOAD-001", "UPLOAD-002",
                "TASK-001", "TASK-002", "TASK-003", "TASK-004", "TASK-005",
                "TASK-006", "TASK-007", "TASK-008", "TASK-009", "TASK-010",
                "RESULT-001", "RESULT-002", "RESULT-003", "RESULT-004",
                "RESULT-005", "RESULT-006",
            ],
        )

    def test_unavailable_evidence_returns_unknown(self):
        analysis = load_reply_analysis()
        analysis["summary"]["trace_chain"] = None
        trace_check = check_by_id(run_dating_checks(analysis), "TRACE-001")
        self.assertEqual(trace_check["outcome"], "UNKNOWN")
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_rules.DatingRuleFrameworkTest -v
```

Expected: `ModuleNotFoundError: No module named 'dating_log_rules'`。

- [ ] **Step 3: 实现统一规则构造器**

`dating_log_rules.py` 内部只保留一套结果构造逻辑：

```python
CHECK_OUTCOMES = {"PASS", "FAIL", "WARN", "UNKNOWN", "NA"}


def _check(
    rule_id: str,
    priority: str,
    title: str,
    outcome: str,
    actual: object,
    expected: object,
    evidence: list[dict] | None = None,
) -> dict:
    resolved_evidence = evidence or []
    if outcome not in CHECK_OUTCOMES:
        raise ValueError(f"unsupported check outcome: {outcome}")
    if outcome in {"FAIL", "WARN"} and not resolved_evidence:
        raise ValueError(f"{rule_id} cannot return {outcome} without evidence")
    return {
        "rule_id": rule_id,
        "priority": priority,
        "title": title,
        "outcome": outcome,
        "actual": actual,
        "expected": expected,
        "evidence": resolved_evidence,
    }
```

`_evidence(call, json_path, value)` 负责从 `InterfaceCall` 提取 `method`、`line_start`、`line_end` 和 `location_precision`；规则函数不得自行拼装不同形状的 evidence。

- [ ] **Step 4: 为每个规则写一组变异测试**

从正常 golden analysis 深拷贝后，只改一个字段构造异常，至少覆盖：

| 规则 | 变异 | 期望 |
|---|---|---|
| `PAIR-001` | 删除一条 Gateway Response | `FAIL` |
| `HTTP-001` | 一次外层 HTTP=500 | `FAIL` |
| `GATEWAY-001` | 外层 HTTP=200、Gateway code=500 | `FAIL` |
| `SUBRESP-001` | 子响应 success=false 或 code 非 0 | `FAIL` |
| `TRACE-001` | 移除 Gateway request_id | `WARN` |
| `UPLOAD-001` | 任务引用的 asset 缺少 Complete | `FAIL` |
| `UPLOAD-002` | Prepare/Complete 的 size 不一致 | `WARN` |
| `TASK-003` | 状态从 `SUCCEEDED` 回退为 `PROCESSING` | `FAIL` |
| `TASK-004` | progress_percent 从 30 降到 20 | `FAIL` |
| `TASK-005` | succeeded 但 progress_percent=95 | `FAIL` |
| `TASK-007` | completed_time 早于 result create_time | `FAIL` |
| `TASK-009` | succeeded 且 phase=finalizing | `WARN` |
| `TASK-010` | processing 进度连续至少 5 次不变 | `WARN` |
| `RESULT-001` | 结果 task_id 与任务 task_id 不同 | `FAIL` |
| `RESULT-002` | 外层和内层 schema_version 不同 | `FAIL` |
| `RESULT-003` | result_id 为空 | `FAIL` |
| `RESULT-004` | 已知 Schema 缺失必填 path | `FAIL` |
| `RESULT-006` | 增加未知字段 | `PASS` 并标记未知字段 |

每个 FAIL/WARN 测试还要断言 `evidence` 非空；证据确实不存在的分支只能返回 `UNKNOWN`，不得生成伪造证据。

- [ ] **Step 5: 实现 8 条通用规则**

固定执行顺序：

```python
GENERIC_RULES = (
    check_parse_complete,
    check_gateway_pairing,
    check_outer_http_status,
    check_gateway_status,
    check_subresponse_status,
    check_trace_ids_present,
    check_used_asset_upload_chain,
    check_upload_metadata_consistency,
)
```

判定原则：

- 解析警告包含 `MALFORMED_JSON_BLOCK` 或 `UNPAIRED_GATEWAY_BLOCK` 时 `PARSE-001=FAIL`；仅有可恢复噪声时 `WARN`。
- `PAIR-001` 要求每个 Gateway 子请求存在唯一同 ID 子响应。
- `HTTP-001` 检查真实外层 HTTP 2xx；`GATEWAY-001` 检查 Gateway envelope code=0；`SUBRESP-001` 检查 `responses[].success=true` 且 code=0，三层不得混用。
- `TRACE-001` 检查 Gateway 响应 request_id 和 trace_id 均非空；缺失时按 P2 输出 WARN。
- `UPLOAD-001` 和 `UPLOAD-002` 在任务未引用 asset 的日志中返回 `NA`，而不是 PASS。
- `UPLOAD-001` 检查任务使用的每个 asset 都完成 Prepare、PUT、Complete；`UPLOAD-002` 检查 Prepare/Complete 的 size/content_type 一致。

- [ ] **Step 6: 实现 10 条任务生命周期规则**

状态机使用显式配置：

```python
ALLOWED_TRANSITIONS = {
    "QUEUED": {"QUEUED", "PROCESSING", "SUCCEEDED", "FAILED"},
    "PROCESSING": {"PROCESSING", "SUCCEEDED", "FAILED"},
    "SUCCEEDED": set(),
    "FAILED": set(),
}
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED"}
```

任务规则逐条遵循 PRD §17.2：

- `TASK-001`：Create、Poll、Result 的 task_id 一致。
- `TASK-002`：Reply/Analysis 的 Create、Poll、Result 方法组合与 task_type 一致。
- `TASK-003`：状态不发生非法回退。
- `TASK-004`：progress_percent 不下降。
- `TASK-005`：succeeded 时 progress_percent 必须为 100。
- `TASK-006`：failed 时必须有 error_code 或可定位错误信息。
- `TASK-007`：create_time ≤ result create_time ≤ completed_time ≤ expire_time；缺任一关键时间时为 UNKNOWN。
- `TASK-008`：成功任务存在对应结果接口。
- `TASK-009`：succeeded 且 phase=finalizing 时输出 WARN，不直接 FAIL。
- `TASK-010`：processing 进度连续 5 次以上不变时输出 WARN，并保留停滞次数。

- [ ] **Step 7: 实现 6 条 Result 规则**

规则必须基于 `result_schema`、`result_fields`、`schema_status` 和任务终态，不重新解析原始日志：

- `RESULT-001`：结果接口 task_id 与任务一致。
- `RESULT-002`：外层和内层 schema_version 一致。
- `RESULT-003`：result_id 非空。
- `RESULT-004`：已知 Schema 必填字段存在。
- `RESULT-005`：汇总 NULL、EMPTY_STRING、EMPTY_ARRAY 和 EMPTY_OBJECT，不把诊断统计本身判为异常。
- `RESULT-006`：未知字段保留并标记，不直接 FAIL；未知 Schema 的专属规则返回 NA。

- [ ] **Step 8: 实现总体 verdict 计算**

固定优先级：

```python
def compute_dating_verdict(checks: list[dict]) -> str:
    outcomes = {item["outcome"] for item in checks}
    if "FAIL" in outcomes:
        return "ISSUES_FOUND"
    if "WARN" in outcomes:
        return "WARNINGS_FOUND"
    if any(
        item["outcome"] == "UNKNOWN" and item["priority"] in {"P0", "P1"}
        for item in checks
    ):
        return "INCOMPLETE_LOG"
    return "NO_ISSUES"
```

本设计将 P0/P1 定义为“关键检查”，P2 UNKNOWN 仅作为诊断信息，不改变 verdict；字段空值统计也只有在对应规则明确产生 WARN/FAIL 时才改变 verdict。

Golden verdict 固定断言：Reply 因 `TASK-009` 和 `REPLY-007` 为 WARN，结果是 `WARNINGS_FOUND`；Analysis 因 `TASK-009` 为 WARN，结果同样是 `WARNINGS_FOUND`。`ANALYSIS-007/008` 的空值汇总不额外改变 verdict。

- [ ] **Step 9: 接入 analyzer 并运行规则测试**

保持依赖方向：`analyze_dating_log()` 只返回解析与聚合结果，不导入规则模块。`app.py` 先调用 analyzer，再调用 `run_dating_checks()`、`compute_dating_verdict()` 和 `render_dating_report()`，最后补齐 `ruleset_version`、`verdict`、`checks`、`report_markdown` 以及 summary 中的 fail/warn/unknown 计数。

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_rules tests.test_dating_log_analyzer -v
```

Expected: 通用、生命周期、Result 规则与 analyzer 回归全部 PASS。

- [ ] **Step 10: Commit**

```bash
git add dating_log_rules.py dating_log_analyzer.py tests/test_dating_log_rules.py tests/test_dating_log_analyzer.py
git commit -m "feat: add deterministic dating log checks"
```

### Task 7：实现 Reply/Analysis 业务规则、固定报告和脱敏

**Files:**

- Modify: `dating_log_rules.py`
- Modify: `dating_log_analyzer.py`
- Modify: `tests/test_dating_log_rules.py`
- Create: `tests/test_dating_report.py`

**目标：** 完成 PRD §16.4～§16.5 的 16 条业务规则，并输出与结构化数据完全一致的固定模板 Markdown；任何报告或导出内容都不能泄漏签名 URL、Authorization、Cookie 或长 Base64。

**新增接口：**

```python
def render_dating_report(analysis_result: dict, checks: list[dict]) -> str:
    """由已脱敏的结构化分析和检查结果渲染固定 Markdown，不调用模型。"""


def redact_dating_response(value: object, key: str | None = None) -> object:
    """递归脱敏敏感键、签名查询参数与长 Base64 字符串。"""
```

- [ ] **Step 1: 编写 Reply 规则失败测试**

覆盖正常 golden 与单字段变异：

```python
class ReplyRuleTest(unittest.TestCase):
    def test_reply_golden_has_expected_rule_results(self):
        checks = checks_for_schema(load_reply_analysis(), "REPLY")
        self.assertEqual([item["rule_id"] for item in checks], [f"REPLY-{index:03d}" for index in range(1, 9)])
        self.assertEqual(check_by_id(checks, "REPLY-001")["outcome"], "PASS")
        self.assertEqual(check_by_id(checks, "REPLY-003")["outcome"], "PASS")
        self.assertEqual(check_by_id(checks, "REPLY-005")["outcome"], "PASS")
        self.assertEqual(check_by_id(checks, "REPLY-007")["outcome"], "WARN")

    def test_multiple_top_picks_fail(self):
        analysis = load_reply_analysis()
        mark_two_replies_as_top_pick(analysis)
        check = check_by_id(run_dating_checks(analysis), "REPLY-002")
        self.assertEqual(check["outcome"], "FAIL")
        self.assertTrue(check["evidence"])
```

其余变异覆盖 reply_id 唯一性、每个 Role 的 Top Pick 数量、top_pick 引用与文案、alternatives 集合、role rank，以及 degradation/warnings 一致性。

- [ ] **Step 2: 编写 Analysis 规则失败测试**

断言 `ANALYSIS-001`～`ANALYSIS-008` 顺序稳定，并覆盖：上传/有效/忽略 asset 计数、valid/analyzed 消息数、双方消息总和、同类型 signal_id 唯一性、event_id 唯一性、evidence_message_ids 非空，以及空值与 warnings 汇总。

`ANALYSIS-007` 和 `ANALYSIS-008` 是 P2 诊断统计，空值本身不直接产生 FAIL/WARN；Schema 必填字段 Missing 由 `RESULT-004` 统一判定。

- [ ] **Step 3: 运行业务规则测试并确认失败**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_rules.ReplyRuleTest tests.test_dating_log_rules.AnalysisRuleTest -v
```

Expected: 找不到业务规则或业务规则数量为 0，测试 FAIL。

- [ ] **Step 4: 实现 8 条 Reply 规则**

规则输入仅使用 `task.result_summary`、`task.result_sections` 和 `task.result_fields`：

```python
REPLY_RULES = (
    check_reply_ids_unique,
    check_reply_one_top_pick_per_role,
    check_reply_top_pick_reference,
    check_reply_top_pick_text,
    check_reply_alternatives,
    check_reply_role_ranks,
    check_reply_degradation_consistency,
    check_reply_person_history_nullability,
)
```

规则 ID 与语义固定为：

| ID | 判定 |
|---|---|
| `REPLY-001` | 每个 reply_id 唯一 |
| `REPLY-002` | 每个 Role 最多一个 is_top_pick=true |
| `REPLY-003` | top_pick.reply_id 存在于 replies[] |
| `REPLY-004` | top_pick 文案与对应 reply 文案一致 |
| `REPLY-005` | alternatives 与非 Top Pick replies 一致 |
| `REPLY-006` | role rank 不重复且可从小到大排序 |
| `REPLY-007` | warnings 含降级项但 is_degraded=false 时 WARN |
| `REPLY-008` | person_history_used=false 时允许 person_id=null |

Reply golden 的 `warnings=[SAFETY_DEGRADED]` 且 `is_degraded=false`，因此 `REPLY-007=WARN`；`person_history_used=false/person_id=null` 对 `REPLY-008` 是 PASS，不得把它误报为效果异常。

- [ ] **Step 5: 实现 8 条 Analysis 规则**

```python
ANALYSIS_RULES = (
    check_analysis_asset_counts,
    check_analysis_valid_message_count,
    check_analysis_participant_counts,
    check_analysis_signal_ids,
    check_analysis_event_ids,
    check_analysis_evidence_message_ids,
    check_analysis_empty_value_summary,
    check_analysis_warning_summary,
)
```

规则 ID 与语义固定为：

| ID | 判定 |
|---|---|
| `ANALYSIS-001` | valid_asset_count + ignored_asset_count = uploaded_asset_count |
| `ANALYSIS-002` | analyzed_message_count ≤ valid_message_count |
| `ANALYSIS-003` | user + other 消息数等于 analyzed_message_count |
| `ANALYSIS-004` | signal_id 在同一类型数组中唯一 |
| `ANALYSIS-005` | event_id 在 key_events 中唯一 |
| `ANALYSIS-006` | Signal/Event 的 evidence_message_ids 非空 |
| `ANALYSIS-007` | effort、match_degree、keywords 空值单独汇总，不直接 FAIL |
| `ANALYSIS-008` | warnings 数组单独汇总 |

规则只对 `dating.relationship_analysis.v1` 生效；Reply Schema 返回 `NA`。Reply 规则对 Analysis Schema 同理。

- [ ] **Step 6: 编写报告与脱敏失败测试**

`tests/test_dating_report.py` 至少包含：

```python
class DatingReportTest(unittest.TestCase):
    def test_report_sections_are_fixed_and_llm_free(self):
        analysis = load_reply_analysis()
        report = render_dating_report(analysis, run_dating_checks(analysis))
        self.assertIn("## 总体结论", report)
        self.assertIn("## 接口调用链", report)
        self.assertIn("## 任务生命周期", report)
        self.assertIn("## Result 字段", report)
        self.assertIn("## 规则检查", report)
        self.assertNotIn("AI 说明", report)

    def test_sensitive_values_are_redacted(self):
        analysis = inject_sensitive_values(load_reply_analysis())
        report = render_dating_report(analysis, run_dating_checks(analysis))
        self.assertNotIn("secret-token-value", report)
        self.assertNotIn("X-Amz-Signature", report)
        self.assertNotIn("q-signature", report)
        self.assertNotIn("data:image/png;base64", report)
        self.assertIn("[REDACTED]", report)
```

- [ ] **Step 7: 运行报告测试并确认失败**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_report -v
```

Expected: `render_dating_report` 或 `redact_dating_response` 尚不存在，测试 FAIL。

- [ ] **Step 8: 实现递归脱敏**

脱敏规则固定为：

- 键名先转小写并将连字符规范化为下划线；命中 `authorization`、`cookie`、`set_cookie`、`token`、`auth_token`、`access_token`、`refresh_token`、`session_token`、`api_key`、`secret` 时，值替换为 `[REDACTED]`。
- URL 查询参数含 `q-signature`、`q-sign-algorithm`、`X-Amz-Signature`、`Signature` 或同类签名键时，移除整个 query，输出 `scheme://host/path?[REDACTED]`；对象路径必须保留用于资产关联。
- 以 `data:` 开头且包含 `;base64,` 的值，以及连续 256 字符以上的 Base64 候选值，替换为 `[REDACTED_BASE64 length=N]`。
- 其他自由文本超过 20000 字符时保留前 20000 字符；Result Field 设置 `value_truncated=true`，并生成带 path 的 `VALUE_TRUNCATED` warning。`result_payload` 与 `calls` 中的同一值也必须截断，不能通过嵌套原值绕过限制。
- 普通业务 ID、Schema 名称、状态、计数和短文本不脱敏。

分析对象进入 `render_dating_report`、JSON export 和 API response 前统一执行脱敏，不依赖前端隐藏。

- [ ] **Step 9: 实现固定 Markdown 模板**

报告顺序固定：

1. 总体结论：verdict、任务类型、Schema、接口/异常计数。
2. 接口调用链：序号、接口名、method、状态、request_id、耗时。
3. 上传与任务生命周期：上传资产、创建任务、轮询状态序列、终态和持续时间。
4. Result 摘要：按 Reply 或 Analysis sections 输出。
5. Result 字段：`path`、value_type、presence、value、schema_known、source、value_truncated。
6. 规则检查：按 FAIL → WARN → UNKNOWN → PASS → NA 排序。
7. 解析警告：code、message、证据位置。

模板不得添加推测性“原因分析”，只描述可以从日志证明的实际值、期望值与证据。

`render_dating_report()` 入口再次调用 `redact_dating_response()`，因此即使未来调用方误传内部对象，报告仍不会泄漏原始敏感值；该防御不替代 Task 8 的响应级脱敏顺序。

- [ ] **Step 10: 运行规则、报告与 golden 回归**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_rules tests.test_dating_report tests.test_dating_log_analyzer -v
```

Expected: 40 条规则契约、固定报告和脱敏测试全部 PASS；两份 golden 的核心统计保持 PRD 值。

- [ ] **Step 11: Commit**

```bash
git add dating_log_rules.py dating_log_analyzer.py tests/test_dating_log_rules.py tests/test_dating_report.py
git commit -m "feat: add dating schema checks and fixed report"
```

### Task 8：接入 Flask API、功能开关与导出

**Files:**

- Modify: `app.py`
- Create: `tests/test_dating_log_routes.py`
- Modify: `tests/test_log_filter.py`

**目标：** 新增 `/dating/analyze` 和 Dating 两种导出类型，复用现有上传、错误响应和 Content-Disposition 约定，不影响 `/filter`、People 分析和现有 export。

- [ ] **Step 1: 编写配置与禁用开关失败测试**

```python
class DatingRouteTest(unittest.TestCase):
    def test_dating_config_defaults(self):
        app = create_app()
        self.assertTrue(app.config["DATING_STRUCTURED_ANALYZER_ENABLED"])
        self.assertEqual(app.config["DATING_STRUCTURED_MAX_BYTES"], 10 * 1024 * 1024)

    def test_disabled_analyzer_returns_503(self):
        app = create_app()
        app.config.update(TESTING=True, DATING_STRUCTURED_ANALYZER_ENABLED=False)
        response = app.test_client().post("/dating/analyze", json={"log_text": "safe sample"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error_code"], "ANALYZER_DISABLED")

    def test_base_path_route_is_registered(self):
        app = create_app("/log-tool")
        app.config["TESTING"] = True
        response = app.test_client().post("/log-tool/dating/analyze", json={"log_text": "safe sample"})
        self.assertNotEqual(response.status_code, 404)
```

- [ ] **Step 2: 编写 endpoint 成功与错误映射失败测试**

严格覆盖 `Content-Type: application/json` 请求；请求体只接受 `log_text: str` 和可选 `task_id: str | null`：

| 场景 | HTTP | `error.code` |
|---|---:|---|
| golden Reply | 200 | 无 |
| golden Analysis | 200 | 无 |
| 空请求 | 400 | `EMPTY_LOG` |
| 非 JSON 或字段类型错误 | 400 | `INVALID_REQUEST` |
| 超过大小 | 413 | `LOG_TOO_LARGE` |
| 未识别 Dating Gateway/PUT | 422 | `UNSUPPORTED_LOG` |
| 多任务但未指定 task_id | 422 | `MULTIPLE_TASKS_FOUND` |
| 指定 task_id 不存在 | 422 | `TASK_NOT_FOUND` |
| 功能关闭 | 503 | `ANALYZER_DISABLED` |
| 内部异常 | 500 | `ANALYSIS_INTERNAL_ERROR` |

成功响应还要断言顶层键严格为 `analyzer_version`、`parser_version`、`ruleset_version`、`supported`、`detected_domain`、`verdict`、`selection_error`、`task_ids`、`summary`、`interface_statistics`、`flow_steps`、`calls`、`task_snapshot`、`checks`、`parse_warnings`、`report_markdown`。

- [ ] **Step 3: 运行路由测试并确认失败**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_routes -v
```

Expected: 路由或配置尚未实现，至少一个断言 FAIL。

- [ ] **Step 4: 在 `create_app` 增加配置**

沿用现有 `create_app(base_path=None)` 和逐项配置方式，不改变函数签名：

```python
app.config["DATING_STRUCTURED_ANALYZER_ENABLED"] = os.environ.get(
    "DATING_STRUCTURED_ANALYZER_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")
try:
    app.config["DATING_STRUCTURED_MAX_BYTES"] = max(
        1, int(os.environ.get("DATING_STRUCTURED_MAX_BYTES", "10485760"))
    )
except ValueError:
    app.config["DATING_STRUCTURED_MAX_BYTES"] = 10485760
```

测试通过 `app.config.update()` 覆盖配置；环境变量非法时安全回落到 10 MiB，不能让应用启动失败。

- [ ] **Step 5: 实现 `/dating/analyze`**

路由职责仅包含：

1. 功能开关检查。
2. 使用 `request.get_json(silent=True)` 读取对象；非对象、未知字段或字段类型错误返回 `INVALID_REQUEST`。
3. 对 `log_text.encode("utf-8")` 的字节长度检查 10 MiB 上限；空白字符串返回 `EMPTY_LOG`。
4. 调用 `analyze_dating_log(log_text, requested_task_id=task_id)`。
5. `supported=false` 映射 `UNSUPPORTED_LOG`；selection_error 映射 `MULTIPLE_TASKS_FOUND` 或 `TASK_NOT_FOUND`。
6. 对内部分析结果运行 `run_dating_checks()` 和 `compute_dating_verdict()`，补齐 `ruleset_version`、`verdict`、`checks` 及 summary 的 fail/warn/unknown 计数。
7. 先执行 `safe_result = redact_dating_response(result)`，再用 `render_dating_report(safe_result, safe_result["checks"])` 生成 `report_markdown`；报告不得读取未脱敏对象。
8. 返回 `jsonify(safe_result)`。

解析、任务识别、规则计算和报告渲染不得写进 `app.py`。

- [ ] **Step 6: 编写导出失败测试**

```python
def test_export_dating_report(self):
    response = self.client.post(
        "/export",
        json={"export_type": "dating_analysis_report", "content": "# Dating report"},
    )
    self.assertEqual(response.status_code, 200)
    self.assertTrue(response.get_json()["filename"].endswith(".md"))

def test_export_dating_json(self):
    response = self.client.post(
        "/export",
        json={"export_type": "dating_analysis_json", "content": '{"verdict":"NO_ISSUES"}'},
    )
    self.assertEqual(response.status_code, 200)
    self.assertTrue(response.get_json()["filename"].endswith(".json"))
```

测试使用临时 `LOG_EXPORT_DIR`，读取实际保存文件并断言 UTF-8 内容；客户端不能传文件名或目录，继续由现有 `save_exported_log()` 生成安全名称。

- [ ] **Step 7: 扩展 export allow-list**

在 `EXPORT_FILE_TYPES` 增加：

```python
"dating_analysis_report": ("dating_structured_analysis", ".md"),
"dating_analysis_json": ("dating_structured_analysis", ".json"),
```

现有 `/export` 的 `content` 合同保持字符串：Dating JSON 分支先用 `json.loads(content)` 验证，再执行 `redact_dating_response()` 和 `json.dumps(redacted_content, ensure_ascii=False, indent=2)` 规范化；Dating Markdown 分支使用同一脱敏模块的文本规则做后端兜底。其他 export_type 不改变现有行为。

- [ ] **Step 8: 添加既有能力回归测试**

在 `tests/test_log_filter.py` 保留并补充断言：

- `/filter` 请求/响应不变。
- `analysis_report` 原导出仍可用。
- `EXPORT_FILE_TYPES` 新增类型不会改变未知类型的 400 行为。
- `clean_log_line` 对现有输入结果不变。
- 首页 route 将 `dating_analyzer_enabled=app.config["DATING_STRUCTURED_ANALYZER_ENABLED"]` 传给模板；关闭时其他页面能力正常。

- [ ] **Step 9: 运行 API 和回归测试**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_routes tests.test_log_filter tests.test_people_search_phase3 -v
```

Expected: Dating API、原过滤器、People 分析和导出全部 PASS。

- [ ] **Step 10: Commit**

```bash
git add app.py tests/test_dating_log_routes.py tests/test_log_filter.py
git commit -m "feat: expose dating log analysis API and exports"
```

### Task 9：实现 Dating 分析页面与浏览器验收

**Files:**

- Modify: `templates/index.html`
- Modify: `tests/test_dating_log_routes.py`

**执行时技能要求：** 开始本任务前读取并使用 `apple-web-development`；页面实现后读取并使用 `playwright` 做真实浏览器关键流程和截图核对。这两项仅约束执行阶段，不改变本计划的后端契约。

**目标：** 在现有单页工具中增加“Dating 结构化分析”入口和结果区，保持现有视觉语言；默认先展示摘要与异常，字段树和完整接口调用按需展开。

- [ ] **Step 1: 编写页面结构失败测试**

在 `tests/test_dating_log_routes.py` 对首页 HTML 断言：

```python
for marker in (
    'id="analyze-dating-btn"',
    'id="dating-analysis"',
    'id="dating-summary"',
    'id="dating-interface-table"',
    'id="dating-upload-list"',
    'id="dating-task-timeline"',
    'id="dating-result-sections"',
    'id="dating-field-filter"',
    'id="dating-field-search"',
    'id="dating-field-table"',
    'id="dating-check-list"',
    'id="dating-report"',
    'id="copy-dating-report-btn"',
    'id="export-dating-report-btn"',
    'id="export-dating-json-btn"',
):
    self.assertIn(marker, html)
self.assertIn("/dating/analyze", html)
```

- [ ] **Step 2: 运行页面测试并确认失败**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_routes.DatingPageTest -v
```

Expected: Dating DOM 标识和 endpoint JS 不存在，测试 FAIL。

- [ ] **Step 3: 增加入口与容器**

在现有工具栏 People 分析按钮旁增加 Dating 按钮；在 People panel 后增加独立 `dating-analysis`。按钮和 panel 放在 `{% if dating_analyzer_enabled %}` 条件内；不得复用 People panel 的内部状态，以免两个分析模式互相覆盖。

页面层级固定：

```text
Dating 结构化分析
├── 总体摘要卡片
├── 上传与任务生命周期
├── Result 业务摘要
├── Result 字段索引（可搜索、可展开）
├── 接口调用链（默认折叠）
├── 规则检查（FAIL/WARN 默认展开）
├── 解析警告
└── Markdown / JSON 导出
```

各区块的数据列固定：

- 总体摘要：task_type、task_id、result_id、schema_version、final_status、duration_ms、Gateway/PUT/asset/Poll 数、HTTP/business error 数、FAIL/WARN 数。
- 接口链路：sequence、请求时间、service_name、method_name、HTTP、Gateway code、SubResponse success/code、elapsed_ms、task_id/asset_id、result_class、请求/响应行号；展开后显示脱敏 params、Gateway envelope、data 和 warnings。
- 上传链路：每个 asset 的 Prepare → PUT → Complete → Used by Task 状态。
- 时间线：每次 Poll 原样显示，不合并；附 poll_count、distinct_progress_values、unchanged_poll_count、duration_ms。
- 最终结果：业务分组和原始字段树两个视图；未知 Schema 只显示字段树。
- 字段筛选：全部、PRESENT、NULL、EMPTY_STRING、EMPTY_ARRAY、EMPTY_OBJECT、MISSING、未知 Schema 字段，并支持 path/value 搜索。

- [ ] **Step 4: 实现前端状态和请求函数**

新增函数名固定，便于测试和后续维护：

```javascript
async function analyzeDatingLog() {
  const logText = document.getElementById('log_text').value;
  const analyzeUrl = {{ url_for('tool.analyze_dating')|tojson }};
  setDatingLoading(true);
  try {
    const response = await fetch(analyzeUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ log_text: logText, task_id: null }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || 'Dating 日志分析失败');
    latestDatingAnalysis = payload;
    latestDatingReport = payload.report_markdown;
    renderDatingAnalysis(payload);
  } catch (error) {
    latestDatingAnalysis = null;
    latestDatingReport = '';
    renderDatingError(error.message);
  } finally {
    setDatingLoading(false);
  }
}
```

必须由 `url_for('tool.analyze_dating')` 生成 URL，确保 `APP_BASE_PATH=/log-tool` 等前缀部署仍能调用正确 endpoint；不得在 JavaScript 中硬编码根路径。

还需实现：

- `setDatingLoading(isLoading)`：禁用按钮并显示现有 loading 样式。
- `renderDatingAnalysis(data)`：编排各分区渲染，不直接拼业务判断。
- `renderDatingSummary(summary)`。
- `renderDatingLifecycle(taskSnapshot)`：展示上传资源和完整 Poll 时间线。
- `renderDatingResult(taskSnapshot)`：根据 `schema_version` 选择 Reply/Analysis 摘要。
- `renderDatingCalls(calls)`：展示 HTTP、Gateway、SubResponse 三层值与行号。
- `renderDatingFields(fields)`：按 `path` 搜索和 `parent_path` 展开。
- `renderDatingChecks(checks)`：按 FAIL、WARN、UNKNOWN、PASS、NA 排序显示。
- `appendDatingText(parent, value)`：通过 `textContent` 或 `document.createTextNode` 写入日志值；禁止用 `innerHTML` 渲染服务端数据。

- [ ] **Step 5: 实现状态、空值和字段视觉语义**

复用现有 CSS token，不新增 UI 框架。展示约束：

- verdict：`NO_ISSUES` 为成功色、`WARNINGS_FOUND` 为警告色、`ISSUES_FOUND` 为错误色、`INCOMPLETE_LOG` 为中性色。
- field state：`PRESENT` 显示格式化值；`NULL` 显示 `null`；`MISSING` 显示“字段缺失”；`EMPTY_STRING`、`EMPTY_ARRAY`、`EMPTY_OBJECT` 使用不同标签。
- `schema_known=false` 显示“未知字段”标签，不隐藏字段。
- evidence 显示 method、json_path、value、line_start/line_end；无 evidence 时明确显示“日志证据不足”。
- 调用、字段 source 和 evidence 的行号可点击，统一调用 §5.5 `focusLogLines(startLine, endLine)`；若当前 method 筛选隐藏目标，提示切换“全部接口”，不静默改变筛选。
- 大数组只展示计数和前 20 个节点，用户展开后再渲染下一批，避免阻塞页面。

- [ ] **Step 6: 接入导出按钮**

`export-dating-report-btn` 使用 `latestDatingReport` 调用现有 `/export`，请求字段为 `export_type="dating_analysis_report"` 与字符串 content；`export-dating-json-btn` 传入 `JSON.stringify(latestDatingAnalysis, null, 2)`，类型为 `dating_analysis_json`。无当前结果时按钮保持 disabled。

- [ ] **Step 7: 运行页面和后端测试**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_routes tests.test_log_filter tests.test_people_search_phase3 -v
```

Expected: 新 DOM/JS 合同和既有页面功能全部 PASS。

- [ ] **Step 8: 使用真实浏览器验证 Reply 日志**

启动本地服务：

```bash
.venv/bin/python app.py
```

使用 Playwright 打开 `http://127.0.0.1:5001`，上传 `tests/fixtures/dating/reply_generation_multi_image_success.log`，点击 Dating 分析并核对：

- 显示 `dating.reply_generation.v1`。
- Gateway=19、PUT=2、Poll=11、Duration=11781ms。
- Reply 数=4、Top Pick=`reply_1`。
- `REPLY-007` 显示 WARN，证据可展开。
- Markdown/JSON 导出按钮可用。
- 浏览器 console 无 error。

保存截图到 `/tmp/dating-reply-structured-analysis.png` 作为执行期视觉证据。

- [ ] **Step 9: 使用真实浏览器验证 Analysis 日志与异常态**

上传 `tests/fixtures/dating/relationship_analysis_multi_image_success.log`，核对 Gateway=30、PUT=3、Poll=21、Duration=23337ms、assets=3、messages=38、双方各 19 条。再输入一份无 Dating Gateway/PUT 的短文本，核对页面展示 422/`UNSUPPORTED_LOG` 且旧结果不被误当成本次结果。

保存截图到 `/tmp/dating-relationship-structured-analysis.png` 和 `/tmp/dating-analysis-error-state.png`。

- [ ] **Step 10: Commit**

```bash
git add templates/index.html tests/test_dating_log_routes.py
git commit -m "feat: add dating structured analysis interface"
```

### Task 10：补齐容器打包、全量回归、本地部署与 PRD 验收

**Files:**

- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `tests/test_dating_log_routes.py`
- Verify: `Log_Tool_PRD/V5_Dating_结构化接口日志分析_PRD.md`
- Verify: `docs/V5_Dating_结构化接口日志分析_开发设计与计划.md`

**目标：** 确保新增模块进入镜像，环境开关可配置，完整测试通过，并在本地 Docker 服务上使用两份 golden 日志验收真实接口。

- [ ] **Step 1: 编写容器配置失败测试**

在 `tests/test_dating_log_routes.py` 增加静态配置合同测试：

```python
def test_dockerfile_packages_dating_modules(self):
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    self.assertIn("dating_log_analyzer.py", dockerfile)
    self.assertIn("dating_log_rules.py", dockerfile)
    self.assertIn("gateway_log_parser.py", dockerfile)

def test_compose_exposes_dating_feature_flags(self):
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    self.assertIn("DATING_STRUCTURED_ANALYZER_ENABLED", compose)
    self.assertIn("DATING_STRUCTURED_MAX_BYTES", compose)
```

- [ ] **Step 2: 运行容器配置测试并确认失败**

Run:

```bash
.venv/bin/python -m unittest tests.test_dating_log_routes.DatingDeploymentConfigTest -v
```

Expected: Dockerfile 尚未 COPY Dating 模块或 compose 尚无环境项，测试 FAIL。

- [ ] **Step 3: 更新 Dockerfile 与 compose**

Dockerfile 沿用现有逐文件 COPY 风格，加入：

```dockerfile
COPY gateway_log_parser.py dating_log_analyzer.py dating_log_rules.py ./
```

`docker-compose.yml` 的现有服务环境中加入：

```yaml
DATING_STRUCTURED_ANALYZER_ENABLED: ${DATING_STRUCTURED_ANALYZER_ENABLED:-true}
DATING_STRUCTURED_MAX_BYTES: ${DATING_STRUCTURED_MAX_BYTES:-10485760}
```

不改变端口、volume、People 配置或服务名。

- [ ] **Step 4: 运行全部单元测试**

先在 `tests/test_dating_log_analyzer.py` 增加非功能验收：

- 两份 golden 各运行 3 次，取中位数，单份目标 ≤500ms。
- 使用重复合法 Gateway block 加安全噪声构造接近但不超过 10 MiB 的输入，后端分析目标 ≤2s。
- `DatingDeterminismTest`：同一输入连续分析两次，移除允许变化的服务端处理时长后做深度相等断言；该类始终执行。
- `DatingDeterminismTest`：断言 `call_id` 严格为解析顺序生成的 `call_0001` 起始序列，代码不得使用随机数或当前时间生成业务字段。

`DatingPerformanceAcceptanceTest` 仅在 `RUN_DATING_PERF=1` 时启用，避免共享低性能 CI 产生毫秒级误报；CI 始终运行复杂度、字段上限和确定性断言。

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
RUN_DATING_PERF=1 .venv/bin/python -m unittest tests.test_dating_log_analyzer.DatingPerformanceAcceptanceTest -v
```

Expected: 全部核心测试 PASS；默认全量中只允许性能类按环境条件 skipped；显式性能命令中 golden 中位数 ≤500ms、10 MiB 输入 ≤2s。

- [ ] **Step 5: 执行静态与变更范围检查**

Run:

```bash
.venv/bin/python -m py_compile app.py gateway_log_parser.py people_search_analyzer.py people_search_rules.py dating_log_analyzer.py dating_log_rules.py
git diff --check
git status --short
```

Expected: Python 编译成功、无 whitespace error；`git status` 中仅包含本计划列出的文件以及用户已有的无关改动，不能把无关改动纳入提交。

- [ ] **Step 6: 构建并启动本地容器**

Run:

```bash
docker compose build log-filter-tool
docker compose up -d log-filter-tool
docker compose ps
```

Expected: `log-filter-tool` 为 running/healthy（若项目未配置 healthcheck，则至少为 Up），端口与现有 compose 配置一致。

- [ ] **Step 7: 调用容器内真实 Reply 分析接口**

Run:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from urllib.request import Request, urlopen

log_text = Path("tests/fixtures/dating/reply_generation_multi_image_success.log").read_text(encoding="utf-8")
body = json.dumps({"log_text": log_text, "task_id": None}).encode("utf-8")
request = Request(
    "http://127.0.0.1:5001/dating/analyze",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
Path("/tmp/dating-reply-analysis.json").write_bytes(urlopen(request).read())
PY
```

用 Python 标准库验证返回：

```bash
.venv/bin/python -c 'import json; d=json.load(open("/tmp/dating-reply-analysis.json", encoding="utf-8")); s=d["summary"]; t=d["task_snapshot"]; r=t["result_summary"]; assert s["gateway_call_count"] == 19; assert s["upload_call_count"] == 2; assert t["poll_count"] == 11; assert t["duration_ms"] == 11781; assert r["reply_count"] == 4; assert r["top_pick_reply_id"] == "reply_1"; print("reply acceptance: PASS")'
```

- [ ] **Step 8: 调用容器内真实 Analysis 分析接口**

Run:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from urllib.request import Request, urlopen

log_text = Path("tests/fixtures/dating/relationship_analysis_multi_image_success.log").read_text(encoding="utf-8")
body = json.dumps({"log_text": log_text, "task_id": None}).encode("utf-8")
request = Request(
    "http://127.0.0.1:5001/dating/analyze",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
Path("/tmp/dating-relationship-analysis.json").write_bytes(urlopen(request).read())
PY
```

验证返回：

```bash
.venv/bin/python -c 'import json; d=json.load(open("/tmp/dating-relationship-analysis.json", encoding="utf-8")); s=d["summary"]; t=d["task_snapshot"]; r=t["result_summary"]; assert s["gateway_call_count"] == 30; assert s["upload_call_count"] == 3; assert t["poll_count"] == 21; assert t["duration_ms"] == 23337; assert r["uploaded_asset_count"] == 3; assert r["analyzed_message_count"] == 38; assert r["message_counts"] == {"user": 19, "other": 19}; print("analysis acceptance: PASS")'
```

- [ ] **Step 9: 验收错误码、导出与脱敏**

逐项执行：

- 空输入返回 400/`EMPTY_LOG`。
- 无 Dating Gateway/PUT 文本返回 422/`UNSUPPORTED_LOG`。
- 超限输入返回 413/`LOG_TOO_LARGE`。
- Reply Markdown 导出为 `.md` 且不含 `AI 说明`。
- JSON 导出为合法 UTF-8 JSON。
- API、Markdown、JSON 中均不存在原始 Authorization、Cookie、签名参数值和长 Base64。
- 将 `DATING_STRUCTURED_ANALYZER_ENABLED=false` 后重启服务，endpoint 返回 503/`ANALYZER_DISABLED`；恢复 true 后重新启动并复验 200。

- [ ] **Step 10: 按 PRD §29 逐条核对 AC-001～AC-018**

建立执行记录，至少记录“用例编号、输入 fixture/变异方式、期望、实际、证据命令”。通过标准：

- 两份 golden 统计完全匹配。
- Gateway 分层状态、生命周期、Result 字段和空值健康规则均可触发对应 PASS/FAIL/WARN/UNKNOWN。
- 40 条规则均有测试，规则顺序稳定。
- 未知 Schema 不崩溃并保留字段索引。
- 两种导出和脱敏通过。
- People 与基础过滤功能无回归。

验收追踪表：

| AC | 执行输入 | 自动/人工证据 |
|---|---|---|
| `AC-001` | Reply golden | parser 断言 19 Gateway、2 PUT、1 task |
| `AC-002` | Analysis golden | parser 断言 30 Gateway、3 PUT、1 task |
| `AC-003` | 两份 golden | InterfaceCall 分别断言 HTTP/Gateway/SubResponse 成功值 |
| `AC-004` | Reply golden | 11 Poll、succeeded/100、11781ms |
| `AC-005` | Analysis golden | 21 Poll、succeeded/100、23337ms |
| `AC-006` | Reply golden | context、roles、replies、top_pick 字段树和摘要 |
| `AC-007` | Analysis golden | scope、overview、signals、events 字段树和摘要 |
| `AC-008` | 两份 golden | NULL、EMPTY_STRING、EMPTY_ARRAY 分别计数 |
| `AC-009` | 增加 `result.extension_field` | 字段保留且 `schema_known=false` |
| `AC-010` | 将 schema_version 改为 v2 | 通用字段树保留，Reply/Analysis 专属规则为 NA |
| `AC-011` | 任一调用、字段和 FAIL/WARN | 均有 line_start/line_end 或 block 级 evidence |
| `AC-012` | 破坏一个响应 JSON | 其他调用保留，相关规则 UNKNOWN，接口仍为 200 |
| `AC-013` | 注入 token、签名 URL、Base64 | API/Markdown/JSON 均无法检出原值 |
| `AC-014` | 同一输入连续分析两次 | 移除服务端处理时间等非业务元数据后结果深度相等 |
| `AC-015` | analyzer/rules 单测 | mock 网络入口并断言零调用，代码无 LLM 配置依赖 |
| `AC-016` | People 回归 | People 相关 unittest 全部通过 |
| `AC-017` | Reply/Analysis 浏览器流程 | 摘要、链路、时间线、字段、规则可用并有截图 |
| `AC-018` | Markdown/JSON 导出 | 文件内容完整、UTF-8、结构合法且脱敏 |

- [ ] **Step 11: Commit**

```bash
git add Dockerfile docker-compose.yml tests/test_dating_log_routes.py
git commit -m "chore: package and verify dating log analyzer"
```

## 9. 发布、回滚与可观测性

### 9.1 发布顺序

1. 在本地完成 Task 1～10 和全部测试。
2. 构建新镜像并以默认 `DATING_STRUCTURED_ANALYZER_ENABLED=true` 启动。
3. 用两份 golden 日志做接口与页面冒烟。
4. 检查 People 分析和 `/filter` 冒烟。
5. 保留上一镜像标签，确认新版本稳定后再清理旧镜像。

### 9.2 回滚方案

- 功能级回滚：设置 `DATING_STRUCTURED_ANALYZER_ENABLED=false` 并重启服务，隐藏接口能力；前端按钮同时读取后端注入的能力标志，禁用时不展示。
- 版本级回滚：切回上一镜像标签并执行 `docker compose up -d log-filter-tool`。
- 数据回滚：本功能不写数据库、不修改原日志，无数据迁移与数据回滚动作。

### 9.3 服务端日志

新增分析入口仅记录以下元数据：

- 输入字节数。
- 解析出的 Gateway、PUT、Task 数量。
- 分析耗时。
- verdict 与 error code。

不得记录上传日志全文、Authorization、Cookie、签名 URL、Base64 或完整 Result 文本。内部异常用 `logger.exception` 保留堆栈，但结构化上下文只包含上述安全元数据。

## 10. PRD 可追溯矩阵

| PRD 范围 | 设计/实现任务 | 自动验证 |
|---|---|---|
| §1、§2、§3、§4、§5、§6 定位、目标、范围与术语 | 设计章节 1～3、Task 1 | golden 契约与顶层数据模型评审 |
| §7 总体产品流程 | Task 2～9 | parser → analyzer → rules → API/UI 端到端测试 |
| §8 支持的日志格式 | Task 2～3 | `test_gateway_log_parser.py` marker/前缀/多行 JSON 用例 |
| §9 通用 Gateway 解析规则 | Task 2～3 | 配对、三层状态、警告和顺序测试 |
| §10 InterfaceCall | Task 3 | InterfaceCall 完整合同测试 |
| §11 Dating 任务聚合 | Task 4 | 创建、轮询、结果、多任务选择测试 |
| §12 上传资源结构 | Task 4 | Prepare/PUT/Complete/任务引用关联测试 |
| §13 最终结果字段模型 | Task 5 | 字段树、扁平索引、presence 与证据测试 |
| §14 Reply Schema | Task 5、Task 7 | Reply projector 与 `REPLY-001`～`REPLY-008` |
| §15 Analysis Schema | Task 5、Task 7 | Analysis projector 与 `ANALYSIS-001`～`ANALYSIS-008` |
| §16 未知 Schema | Task 5、Task 7 | 通用字段树与专属规则 NA 测试 |
| §17 确定性检查规则 | Task 6～7 | 40 条规则顺序、outcome 和证据测试 |
| §18 Rule Result | Task 6 | 固定键、枚举与 evidence 合同测试 |
| §19 后端分析接口 | Task 8 | JSON 请求、成功结构、全部 HTTP/error_code 测试 |
| §20 页面需求 | Task 9 | HTML 合同 + Playwright Reply/Analysis/错误态截图 |
| §21 固定 Markdown 报告 | Task 7 | `test_dating_report.py` 固定章节与无 AI 测试 |
| §22 导出需求 | Task 8～9 | `dating_analysis_report/json` 保存与内容测试 |
| §23 脱敏规则 | Task 7～8 | API、Markdown、JSON 三层脱敏测试 |
| §24 错误处理与降级 | Task 2～8 | 局部解析、未知 Schema、大小和领域错误测试 |
| §25 非功能需求 | Task 2、Task 8、Task 10 | O(n) 解析、10 MiB、确定性、全量回归 |
| §26 推荐实现边界 | §2、Task 2～8 | 依赖方向与 People 兼容测试 |
| §27 测试设计 | Task 1～10 | 单元、集成、变异、浏览器与 Docker 验收 |
| §28 黄金日志基线 | Task 1、Task 3～7、Task 10 | 两份 golden 精确值断言 |
| §29 AC-001～AC-018 | Task 10 | 18 项验收执行记录 |
| §30 开发实施阶段 | Task 1～10 | 按依赖顺序的 10 个可提交任务 |
| §31 部署与回滚 | Task 10、§9 | feature flag、Docker 冒烟与版本回滚 |
| §32 风险与控制 | Global Constraints、§9 | 限制、脱敏、兼容和回滚检查 |
| §33 Definition of Done | §11 | 完成条件逐项勾选 |
| §34 已确认产品决策 | §2～§5 | 三模块边界、无 LLM、JSON API 与固定报告 |

## 11. Definition of Done

只有同时满足以下条件才可声明完成：

- [ ] 所有新增函数与返回结构符合本文数据契约。
- [ ] 两份脱敏 golden fixture 的统计值与 PRD 完全一致。
- [ ] 40 条确定性规则均有正向或变异测试，FAIL/WARN 均提供真实 evidence。
- [ ] 报告、API 和两种导出通过敏感信息扫描。
- [ ] 未知字段、Missing、Null、Empty 和未知 Schema 均可区分且不崩溃。
- [ ] `.venv/bin/python -m unittest discover -s tests -v` 全部通过。
- [ ] Python 编译与 `git diff --check` 通过。
- [ ] Playwright 完成 Reply、Analysis 和错误态真实浏览器验收并保存截图。
- [ ] Docker 镜像构建成功，本地容器接口通过两份 golden 冒烟。
- [ ] `/filter`、People 分析和原有 export 无回归。
- [ ] 功能开关关闭时可以安全回退，且无需数据迁移。

## 12. 执行交接

计划已经拆成可独立验证、可逐步提交的 10 个任务。执行时有两种方式：

1. **Subagent-Driven（推荐）**：在当前任务中按文件边界分派独立子任务，主智能体负责共享接口、代码整合、阶段评审和最终回归；适合 parser、rules、UI 测试边界清晰的部分。
2. **Inline Execution**：由主智能体按 Task 1 → Task 10 串行实现，每个任务严格遵循“失败测试 → 最小实现 → 回归 → commit”；适合希望逐步人工检查每次改动的场景。

无论采用哪种方式，均不应跳过 Task 2 的 People 兼容测试、Task 7 的三层脱敏或 Task 10 的本地容器验收。
