# Dating Evaluation Admin 误判修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Dating Evaluation Flow 因 `GetProviderCostSummary` 同名而错误依赖 Truthy Admin 凭证的问题，并证明 Reply/Analysis 实际 HTTP 报文符合根级 `/admin/invoke` 契约。

**Architecture:** 保留项目内 API ID 可重复的多项目边界，不通过重命名资产规避冲突。Flow 执行入口改为读取所选项目快照中 API Definition 的 `credential_profile`；只有真实声明 `admin_session` 的接口才启用本地 Admin 环境检查。Evaluation 继续使用 `public` Profile、独立命名目标和 `DATING_EVALUATION_API_KEY`。

**Tech Stack:** Python 3.12、pytest、YAML、Flask/Jinja2、Docker Compose。

**Spec:** 用户在任务中提供的 Dating Evaluation `/admin/invoke` 协议与任务 `20260831-174542-af89` 的本机执行证据。

## Global Constraints

- DEV 平台只执行 Dating test，不新增 staging 环境。
- Evaluation API Key 只保存于 Dating Runtime Scope Secret，不写入 Git、报告或请求日志。
- Reply/Analysis 均发送根级 `service_name/method_name/client_request_id/reason/params`，不发送 `comm/requests` 包装。
- 不调用任何 Evaluation 删除接口，保留 Task、Result、Debug 与 Cost 数据。
- 不修改用户其他未提交内容，不提交 Git commit。

---

### Task 1: Admin 凭证守卫按真实 Profile 判定

**Files:**
- Modify: `tests/test_dating_flow_behavior.py`
- Modify: `test_cases/test_gateway_flow.py`

**Interfaces:**
- Consumes: `flow_case.flow.steps` 与 `flow_case.api_definitions`。
- Produces: `_flow_requires_admin_credentials(flow_case: dict[str, Any]) -> bool`。

- [ ] **Step 1: 写失败测试**

  Dating 与 Truthy 使用相同 `GetProviderCostSummary` API ID；断言 `credential_profile=public` 返回 `False`、`credential_profile=admin_session` 返回 `True`。

- [ ] **Step 2: 验证测试失败**

  Run: `python3 -m pytest -q tests/test_dating_flow_behavior.py -k admin_flow_guard`

  Expected: FAIL，提示缺少按 Profile 判定的守卫入口。

- [ ] **Step 3: 最小实现**

  删除全局 `_ADMIN_FLOW_API_IDS` 识别方式；遍历当前 Flow 引用的 API Definition，只在 `credential_profile == "admin_session"` 时检查 Admin 变量。

- [ ] **Step 4: 验证测试通过**

  Run: `python3 -m pytest -q tests/test_dating_flow_behavior.py -k admin_flow_guard`

  Expected: PASS。

### Task 2: Reply 与 Analysis 请求契约核对

**Files:**
- Modify: `test_cases/test_framework.py`
- Verify: `projects/dating/data/apis/CreateReplyEvaluationTask.yaml`
- Verify: `projects/dating/data/apis/CreateAnalysisEvaluationTask.yaml`
- Verify: `projects/dating/data/scenarios/structured_reply_evaluation.yaml`
- Verify: `projects/dating/data/scenarios/structured_analysis_evaluation.yaml`

**Interfaces:**
- Consumes: `build_payload(...)` 与两个真实 Evaluation API Definition。
- Produces: 与协议一致的根级 POST JSON。

- [ ] **Step 1: 用 Reply/Analysis 两组字面量断言构造后的最终 HTTP payload**

  断言顶层只有 `service_name`、`method_name`、`client_request_id`、`reason`、`params`；`params` 中直接包含 `case_id/run_id/client_request_id/locale/transcript` 及 Reply 专属字段，不包含内部 `input`。

- [ ] **Step 2: 执行契约测试**

  Run: `python3 -m pytest -q test_cases/test_framework.py -k root_single`

  Expected: 两种方法均 PASS；若发现差异，只修改产生差异的最小资产或构造逻辑。

### Task 3: 回归、部署与真实重跑

**Files:**
- Verify: `tests/`
- Verify: `test_cases/test_framework.py`
- Deploy: `/Users/admin/Testproject/test-platform/scripts/dev-up.sh`

**Interfaces:**
- Consumes: Dating Scope `tps_e6c4218848a74086892a8abd87c7e8b8` 的 Release 与 Secret。
- Produces: 本机 DEV 平台可执行的修复版本及新任务证据。

- [ ] **Step 1: 运行本地完整回归和项目校验**

  Run: `python3 -m pytest -q tests`

  Run: `python3 -m pytest -q test_cases/test_framework.py`

  Run: `python3 runtest.py --validate-projects`

- [ ] **Step 2: 部署接口自动化工具**

  Run: `cd /Users/admin/Testproject/test-platform && ./scripts/dev-up.sh api-autotest`

- [ ] **Step 3: 真实重跑 Reply Flow**

  在已登录平台使用用户提供的有效 Reply JSON 创建新任务；确认不再检查 Truthy Admin，实际请求到达 Dating Evaluation Gateway。

- [ ] **Step 4: 检查新任务日志和结果**

  断言日志包含 Evaluation 方法执行，不包含 API Key；如果 Gateway 返回业务错误，保留原始响应与 Task 数据并按稳定错误码报告。
