# Gateway 接口自动化 Allure 报告接入详细开发设计

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 能力版本 | 报告能力 R1.0 |
| 项目基线 | Gateway 接口自动化 V1.3 |
| 日期 | 2026-07-31 |
| 需求依据 | `docs/接口自动化Allure报告接入-PRD.md` |
| 技术栈 | Python + pytest + requests + PyYAML + Allure Pytest |
| 文档状态 | 待 Review |

## 2. 设计目标

在不改变 V1.3 数据模型和请求执行协议的前提下，完成以下接入：

1. pytest 原生生成 Allure 结果。
2. 单接口 case 映射为具备业务标题和分层信息的 Allure 测试。
3. Flow/Scenario 映射为 Allure 测试，Flow step 映射为 Allure Step。
4. HTTP 请求、响应和上传摘要作为安全附件展示。
5. Allure 逻辑集中封装，避免第三方调用散落在执行核心中。
6. Allure 未启用结果目录时，现有测试行为保持不变。

## 3. 设计原则

### 3.1 报告是观察层

```text
API / Case / Flow / Scenario 数据
              │
              ▼
现有加载、执行、断言和变量处理
              │
              ├── 原有日志
              └── Allure 观察与附件
```

Allure 只观察并展示已有执行结果，不参与：

- 请求参数合并。
- RuntimeContext 变量解析。
- 会话创建和刷新。
- 断言成功与失败判断。
- Flow 步骤顺序和轮询退出条件。

### 3.2 复用现有脱敏结果

HTTP 层已经构造以下安全数据：

- Gateway 的 `safe_request`。
- `mask_sensitive(response_body)`。
- PUT 的脱敏签名 URL、headers 和 content length。

Allure 附件必须复用这些对象，不得再次从原始请求或响应构造附件。

### 3.3 集中封装第三方能力

项目已预留 `utils/third_party/`。Allure 运行时调用集中在一个封装文件中：

```text
utils/third_party/allure_reporter.py
```

该文件负责：

- 动态测试元数据。
- Step 上下文。
- JSON 和文本附件。
- 对 Allure 调用异常的边界控制。

测试入口、FlowRunner 和 HttpClient 只调用该封装，不重复维护 Allure API 细节。

## 4. 当前实现分析

| 位置 | 当前行为 | Allure 接入点 |
| --- | --- | --- |
| `runtest.py` | 向 pytest 透传未知参数 | 无需修改即可透传 `--alluredir` |
| `test_single_api.py` | 参数化执行 `single_case` | 设置单接口动态元数据和顶层 Step |
| `test_gateway_flow.py` | 参数化执行 `flow_case` | 设置 Flow 动态元数据 |
| `flow_runner.py` | 按顺序执行 api/wait/action | 为每个步骤及轮询尝试创建 Step |
| `http_client.py` | 记录脱敏请求、响应和耗时 | 附加同一份脱敏数据 |
| `conftest.py` | 注册环境参数、tags 和 fixtures | 首期无需增加 Allure hook |
| `requirements.txt` | 未包含 Allure | 增加 `allure-pytest` |
| `.gitignore` | 管理运行产物 | 增加 Allure 结果及报告目录 |

## 5. 目标结构

```text
.
├── requirements.txt
├── .gitignore
├── README.md
├── test_cases/
│   ├── test_single_api.py
│   ├── test_gateway_flow.py
│   ├── test_framework.py
│   └── test_allure_report.py
├── utils/
│   ├── custom/
│   │   ├── flow_runner.py
│   │   └── http_client.py
│   └── third_party/
│       └── allure_reporter.py
└── allure-results/              # 运行生成，不提交
```

新增文件理由：

| 文件 | 理由 |
| --- | --- |
| `utils/third_party/allure_reporter.py` | 项目已有第三方预留目录；集中隔离 Allure API，避免执行核心散落第三方调用 |
| `test_cases/test_allure_report.py` | 单独验证元数据、Step、附件和脱敏行为，避免把第三方报告测试堆进框架核心测试 |

除上述文件外，不新增其他模块、配置层或抽象层。

## 6. 依赖设计

### 6.1 Python 依赖

`requirements.txt` 增加：

```text
allure-pytest>=2.13,<3.0
```

版本范围遵循项目现有依赖约束方式：

- 声明可用最低版本。
- 限制下一个主版本，避免破坏性升级。
- Allure CLI 版本由开发和运行环境独立管理。

### 6.2 Allure CLI

使用 npm 用户级全局前缀安装固定版本，不创建或修改项目 `package.json`：

```bash
npm install -g --prefix /Users/admin/.local/allure-npm allure@3.14.3
export PATH="/Users/admin/.local/allure-npm/bin:$PATH"
allure --version
```

CLI 只负责把 `allure-results` 转换为 Allure 3 Awesome HTML，不进入 Python
运行时依赖。官方 pytest 适配器产生的结果可由 Allure 3 读取。

## 7. AllureReporter 设计

### 7.1 职责

建议暴露以下最小接口：

```python
set_single_case_metadata(single_case: dict[str, Any]) -> None
set_flow_metadata(flow_case: dict[str, Any]) -> None
step(title: str) -> ContextManager[Any]
attach_json(name: str, data: Any) -> None
attach_text(name: str, content: str) -> None
```

不设计通用插件注册系统，不引入基类或复杂依赖注入。

### 7.2 单接口元数据

输入：

```python
{
    "id": "GetMe::get_me_success",
    "api_id": "GetMe",
    "case_id": "get_me_success",
    "name": "获取当前用户成功",
    "tags": ["smoke", "identity"],
}
```

映射：

| 输入字段 | Allure 字段 |
| --- | --- |
| `name` | title |
| 固定值 `Gateway API 自动化` | parent suite |
| 固定值 `单接口测试` | suite |
| `api_id` | feature |
| `case_id` | story |
| `tags` | tags |

### 7.3 Flow 元数据

输入：

```python
{
    "id": "AnonymousSessionMediaSearch",
    "name": "搜索流程",
    "tags": ["flow", "media", "search"],
    "scenario": {
        "name": "姓名搜索成功场景"
    }
}
```

标题优先级：

1. `scenario.name`
2. `flow_case.name`
3. `flow_case.id`

映射：

| 输入字段 | Allure 字段 |
| --- | --- |
| 解析后的标题 | title |
| 固定值 `Gateway API 自动化` | parent suite |
| 固定值 `多接口流程` | suite |
| `flow_case.id` | feature |
| `tags` | tags |

### 7.4 附件序列化

JSON 附件：

```python
json.dumps(
    data,
    ensure_ascii=False,
    indent=2,
    default=str,
)
```

附件类型：

```python
allure.attachment_type.JSON
```

约束：

- reporter 不读取 `.env`。
- reporter 不读取 RuntimeContext 全量值。
- reporter 不主动读取媒体文件。
- 调用方必须传入已经脱敏的数据。

## 8. 单接口执行设计

### 8.1 修改位置

`test_cases/test_single_api.py`

### 8.2 执行顺序

```text
pytest 参数化 single_case
    │
    ├── 设置 Allure 动态元数据
    │
    └── Step：执行接口 API ID
            │
            └── gateway_api.execute()
```

伪代码：

```python
def test_single_gateway_api(single_case, gateway_api):
    set_single_case_metadata(single_case)
    with step(f"执行接口：{single_case['api_id']}"):
        gateway_api.execute(single_case["execution_case"])
```

原有 pytest 参数 ID 保持 `ApiId::case_id`，Allure 标题仅改变报告展示，不改变 pytest 收集和筛选。

## 9. Flow 执行设计

### 9.1 Flow 顶层元数据

`test_cases/test_gateway_flow.py` 在调用 `FlowRunner` 前设置：

- title。
- parent suite。
- suite。
- feature。
- tags。

### 9.2 Step 命名

`FlowRunner.run()` 根据步骤类型生成标题：

| 步骤类型 | 标题格式 |
| --- | --- |
| API | `{position}/{total} {step_id}：{api_id}` |
| wait | `{position}/{total} {step_id}：等待 {seconds}s` |
| action | `{position}/{total} {step_id}：{action}` |

示例：

```text
1/4 create_task：CreateIntentTask
2/4 poll_task：GetTask
3/4 list_candidates：ListTaskCandidates
4/4 candidate_detail：GetTaskCandidateDetail
```

### 9.3 轮询步骤

轮询 API 外层使用 Flow API Step。每一次调用使用子 Step：

```text
2/4 poll_task：GetTask
├── 第 1 次轮询：status=RUNNING
├── 第 2 次轮询：status=RUNNING
└── 第 3 次轮询：status=SUCCEEDED
```

实现注意：

- 子 Step 在得到 `last_value` 后完成。
- 超时错误继续使用现有 `FlowExecutionError`。
- 不修改轮询次数、间隔、截止时间或成功判断。
- 报告代码不得吞掉原始异常。

## 10. HTTP 附件设计

### 10.1 Gateway POST 请求

现有安全请求对象：

```python
safe_request = {
    "url": url,
    "headers": mask_sensitive(headers),
    "payload": mask_sensitive(payload),
}
```

请求前附加：

```text
附件名：Gateway 请求
类型：application/json
内容：safe_request
```

### 10.2 Gateway POST 响应

响应附件结构：

```python
{
    "status_code": response.status_code,
    "elapsed_ms": elapsed_ms,
    "body_type": "json",
    "body": mask_sensitive(response_body),
}
```

附件名：

```text
Gateway 响应
```

若响应不是 JSON：

- 附件只保存 `status_code`、`elapsed_ms`、`body_type` 和 `body_length`。
- 原始正文不进入附件，避免代理错误页或文本意外携带凭证。
- 不改变现有非 JSON 日志行为。

### 10.3 网络异常

异常时附加：

```python
{
    "request": safe_request,
    "elapsed_ms": elapsed_ms,
    "exception_type": type(exc).__name__,
}
```

不附加 `str(exc)`，避免代理、URL 或底层异常意外携带敏感内容。

异常继续原样抛出，由 pytest 和 Allure 标记失败。

### 10.4 PUT 上传

请求附件复用：

```python
safe_request = {
    "url": _mask_signed_url(url),
    "headers": mask_sensitive(headers),
    "content_length": len(content),
}
```

不附加：

- `content` 二进制。
- 完整签名 URL。
- 媒体文件本地绝对路径。

响应附件：

```python
{
    "http_status": response.status_code,
    "elapsed_ms": elapsed_ms,
}
```

## 11. 安全设计

### 11.1 敏感字段

继续使用 `http_client.py` 中的敏感键集合：

- `access_token`
- `auth_token`
- `authorization`
- `refresh_token`
- `token`

### 11.2 URL 脱敏

字段名为 `url` 或以 `_url` 结尾时：

- 保留 scheme、host、path。
- 查询参数整体替换为 `***`。

### 11.3 安全不变量

以下不变量必须通过测试保证：

```text
Allure 请求附件 == 日志使用的 safe_request
Allure 响应附件 == mask_sensitive(response_body)
Allure PUT 附件 == 已脱敏 URL + headers + content_length
```

禁止出现另一套独立脱敏实现。

## 12. 兼容性设计

### 12.1 未启用 Allure 结果目录

即使代码调用动态元数据、Step 和附件，未传 `--alluredir` 时：

- pytest 仍按原方式执行。
- 不生成 Allure 结果目录。
- 不改变测试通过、失败或跳过状态。

### 12.2 pytest 参数化

- 保留单接口 `pytest.param(..., id=single_case["id"])`。
- 保留 Flow `pytest.param(..., id=flow_case["id"])`。
- 保留 `-k`、`-m`、`--env` 和 `--flow` 筛选。

### 12.3 YAML

以下目录内容和 Schema 不修改：

- `data/apis`
- `data/cases`
- `data/flows`
- `data/scenarios`

## 13. 文件修改清单

| 文件 | 修改内容 |
| --- | --- |
| `requirements.txt` | 增加 `allure-pytest` |
| `.gitignore` | 忽略 `allure-results/` 和 `allure-report/` |
| `utils/third_party/allure_reporter.py` | 新增 Allure 元数据、Step 和附件封装 |
| `test_cases/test_single_api.py` | 设置单接口元数据并包装执行 Step |
| `test_cases/test_gateway_flow.py` | 设置 Flow 元数据 |
| `utils/custom/flow_runner.py` | 包装 Flow 步骤和轮询子步骤 |
| `utils/custom/http_client.py` | 附加脱敏请求、响应和 PUT 摘要 |
| `test_cases/test_allure_report.py` | 新增报告层单元测试 |
| `README.md` | 增加安装、生成、查看及安全说明 |

明确不修改：

- `api/gateway_api.py`
- `utils/custom/assertions.py`
- `utils/custom/runtime_context.py`
- V1.3 YAML 文件
- `Jenkinsfile`

## 14. 测试设计

### 14.1 Reporter 单元测试

1. 单接口元数据字段映射正确。
2. Flow 标题优先使用 Scenario 名称。
3. tags 全部传给 Allure。
4. JSON 附件使用中文友好格式和 JSON 类型。
5. Step 上下文正确透传标题。

测试通过 monkeypatch 替换 Allure API，不要求生成真实 HTML。

### 14.2 HTTP 附件测试

1. Gateway 请求附件不含真实 token。
2. Gateway 响应附件不含 access/refresh token。
3. 预签名 URL 查询参数被替换。
4. PUT 附件不包含文件内容。
5. 网络异常附件只包含异常类型。

### 14.3 Flow Step 测试

1. API、wait 和 action 标题正确。
2. 步骤顺序与 YAML 一致。
3. 轮询成功显示每次尝试。
4. 轮询超时仍抛出原有异常。
5. Reporter 异常不得改变 Flow 业务异常判断。

### 14.4 集成验证

```bash
python3 -m pytest test_cases/test_allure_report.py -q
python3 -m pytest test_cases/test_framework.py test_cases/test_v13.py -q
python3 -m pytest -q
python3 runtest.py --env test -- --alluredir=allure-results --clean-alluredir --allure-no-capture
allure awesome allure-results --output allure-report --group-by parentSuite,suite,feature,story
allure open allure-report
```

## 15. 异常处理

| 场景 | 处理 |
| --- | --- |
| `allure-pytest` 未安装 | 测试收集时报明确依赖错误；通过 requirements 安装解决 |
| Allure CLI 未安装 | 不影响 pytest 执行和 results 生成，只影响 HTML 转换 |
| JSON 序列化遇到特殊对象 | 使用 `default=str` |
| 附件调用失败 | 不回退到原始敏感数据；错误应可定位 |
| HTTP 请求失败 | 附加安全诊断后原样抛出 requests 异常 |
| Flow 断言失败 | 对应 Allure Step 自动标记失败，原断言继续抛出 |

## 16. 回滚方案

Allure 接入不涉及 YAML 或业务数据迁移，回滚路径明确：

1. 移除测试入口和执行器中的 reporter 调用。
2. 移除 HTTP 附件调用。
3. 删除 Allure reporter 和专用测试文件。
4. 从 requirements 移除依赖。
5. 保留原日志、执行和断言代码不变。

回滚不会影响 API、Cases、Flows、Scenarios 或运行时会话数据。

## 17. 完成条件

满足以下条件才视为 R1.0 设计实现完成：

1. PRD 中 AR-001～AR-405 全部实现。
2. 单接口与 Flow 报告层级符合设计。
3. Flow 步骤和轮询可以在 Allure 中定位。
4. 请求及响应附件完整且通过安全测试。
5. 不启用 Allure 时现有测试无回归。
6. 可使用官方 CLI 成功生成并打开 HTML 报告。
7. README 已包含安装、使用和结果目录说明。
