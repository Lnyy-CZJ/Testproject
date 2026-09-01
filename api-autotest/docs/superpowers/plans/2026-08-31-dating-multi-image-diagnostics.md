# Dating 多图 Flow 诊断与成本查询 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `multi_image_analysis` 与 `multi_image_reply` 成功查询正式结果后，继续使用同一个 `task_id` 查询 Task Debug 和 Provider Cost，并保留全部远端 Task 数据。

**Architecture:** 不修改公共 FlowRunner，也不新增 API 定义；复用 Dating 项目现有 `GetTaskDebug`、`GetProviderCostSummary` 资产。两个 Flow 各追加两个顺序步骤，Scenario 只传 `task_id`，并复用平台 Release 的轮询间隔和超时处理诊断数据短暂未就绪状态。

**Tech Stack:** YAML 项目资产、Python、pytest、现有 `FlowRunner`

**Spec:** `/Users/admin/人际关系项目/dating assitsatant/测试设计/Dating Task Debug 与 Provider Cost 查询接口后端支持需求（staging）.md`

## Global Constraints

- DEV 平台继续映射 Dating `test`，不新增 staging 环境。
- Debug 与 Cost 请求只能传当前 Flow 动态提取的 `task_id`。
- 两个步骤必须位于正式 Result 查询之后，顺序固定为 Debug、Cost。
- 不调用 `DeleteTaskData` 或其他删除接口，Task、Result、Debug、Cost 均保留。
- `DATING_EVALUATION_API_KEY` 只由平台 Scope Secret 提供，不写入项目资产、日志或测试报告。
- 不修改公共引擎、平台配置模型或现有上传与轮询行为。

---

### Task 1: 用真实项目资产锁定两个 Flow 的诊断步骤契约

**Files:**
- Modify: `tests/test_dating_assets.py`
- Modify: `tests/test_dating_flow_behavior.py`

**Interfaces:**
- Consumes: `load_flow_cases(project_root, selected_flow)` 与 `_MultiImageGateway.invoke(case)`
- Produces: 对步骤顺序、`task_id` 请求参数、无删除步骤的可重复回归验证

- [ ] **Step 1: 扩展测试替身支持诊断响应**

在 `_MultiImageGateway.invoke` 中为 `GetTaskDebug` 返回 `{"task": {"task_id": resolved_params["task_id"]}}`，为 `GetProviderCostSummary` 返回 `{"task_id": resolved_params["task_id"]}`。替身仍记录真实方法顺序和解析后的请求参数。

- [ ] **Step 2: 写入失败断言**

将 Analysis 和 Reply 的预期方法尾部固定为：

```python
[
    "GetAnalysisResult",  # Reply 对应 GetTaskResult
    "GetTaskDebug",
    "GetProviderCostSummary",
]
```

并逐一断言两个诊断方法的解析参数严格等于当前任务的 `{"task_id": "analysis-1"}` 或 `{"task_id": "reply-1"}`。

- [ ] **Step 3: 运行测试并确认 RED**

Run:

```bash
python3 -m pytest -q \
  tests/test_dating_assets.py::test_dating_flow_catalog_covers_stateful_contracts \
  tests/test_dating_flow_behavior.py::test_real_multi_image_flow_uploads_each_image_and_keeps_remote_task \
  tests/test_dating_flow_behavior.py::test_reply_flow_updates_incomplete_preferences_before_ordered_uploads
```

Expected: FAIL；两个真实 Flow 尚未执行 `GetTaskDebug` 与 `GetProviderCostSummary`。

### Task 2: 给两个 Flow 追加诊断与成本步骤

**Files:**
- Modify: `projects/dating/data/flows/multi_image_analysis.yaml`
- Modify: `projects/dating/data/scenarios/multi_image_analysis.yaml`
- Modify: `projects/dating/data/flows/multi_image_reply.yaml`
- Modify: `projects/dating/data/scenarios/multi_image_reply.yaml`

**Interfaces:**
- Consumes: 创建步骤提取的 `{{task_id}}`、平台 Release 中的 `{{analysis_poll_interval_seconds}}` 和 `{{analysis_timeout_seconds}}`
- Produces: Result → GetTaskDebug → GetProviderCostSummary 的完整 Flow 拓扑

- [ ] **Step 1: 在两个 Result 步骤后追加 Debug**

```yaml
- id: get_task_debug
  api: GetTaskDebug
  until:
    path: $.task.task_id
    equals: "{{task_id}}"
    retry_on_business_error_codes: [DEBUG_DATA_NOT_READY]
    interval_seconds: "{{analysis_poll_interval_seconds}}"
    timeout_seconds: "{{analysis_timeout_seconds}}"
```

- [ ] **Step 2: 紧接 Debug 追加 Cost**

```yaml
- id: get_provider_cost
  api: GetProviderCostSummary
  until:
    path: $.task_id
    equals: "{{task_id}}"
    retry_on_business_error_codes: [COST_DATA_PENDING]
    interval_seconds: "{{analysis_poll_interval_seconds}}"
    timeout_seconds: "{{analysis_timeout_seconds}}"
```

- [ ] **Step 3: 给两个 Scenario 添加最小请求和宽松成功断言**

```yaml
get_task_debug:
  params: {task_id: "{{task_id}}"}
  assert: {http_status: 200, gateway: {message: "ok"}}
get_provider_cost:
  params: {task_id: "{{task_id}}"}
  assert: {http_status: 200, gateway: {message: "ok"}}
```

- [ ] **Step 4: 运行 Task 1 测试并确认 GREEN**

Run: Task 1 Step 3 的同一条 pytest 命令。

Expected: 3 passed。

### Task 3: 完整验证并部署本机平台

**Files:**
- Verify only: `api-autotest` 全部项目资产与测试
- Deploy: `test-platform` 的 `api-autotest` 组件

**Interfaces:**
- Consumes: 修改后的 Dating 项目包
- Produces: 本机 `http://localhost:8080/api-autotest` 可见的 10 步 Analysis Flow 与 12 步 Reply Flow

- [ ] **Step 1: 运行完整验证**

```bash
python3 -m pytest -q tests
python3 -m pytest -q test_cases/test_framework.py
python3 runtest.py --validate-projects
node --check web/static/app.js
```

Expected: 全部退出码为 0。

- [ ] **Step 2: 部署工具组件**

```bash
cd /Users/admin/Testproject/test-platform
./scripts/dev-up.sh api-autotest
```

Expected: `test-platform-api-autotest-1` 为 `healthy`。

- [ ] **Step 3: 验证 Web 目录步骤顺序**

在 Flow 创建页面选择 Dating，并确认：

- `multi_image_analysis` 显示 10 个业务步骤，最后三个依次是 Result、Debug、Cost。
- `multi_image_reply` 显示 12 个业务步骤，最后三个依次是 Result、Debug、Cost。
- 页面预检仍使用 Dating/test Scope，且没有 Delete 步骤。

## Self-Review

- Spec coverage: 两个 Flow、固定顺序、最小 `task_id` 请求、不清理、短暂未就绪重试、平台部署均有对应步骤。
- Placeholder scan: 无 TBD、TODO 或未定义实现步骤。
- Type consistency: Flow step id 与 Scenario `step_data` key 完全一致；动态变量均沿用现有字符串模板协议。
