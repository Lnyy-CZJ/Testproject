# Dating Case 与 Flow 扩展实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 2026-08-28 最新后端协议补齐 Dating 已交付接口、单接口 Case、状态型 Flow 和破坏性隔离 Flow，并将成功断言统一为 HTTP 200 与 Gateway 顶层 `message=ok`。

**Architecture:** API YAML 只保存 Gateway 路由，Case YAML 承担可独立执行的输入矩阵，依赖动态 `asset_id/task_id/version` 的能力全部由自包含 Flow 生成上游数据。普通 Analysis/Reply Flow 保留远端数据；删除任务、清除 Dating 数据和注销账号分别使用显式 `cleanup/destructive/isolated` Flow。为支持跨步骤幂等请求，执行器向每个 Flow 注入稳定且任务唯一的 `flow_run_id`；`isolated` Flow 使用任务级 device id 且禁止写回平台共享 Credential。

**Tech Stack:** Python 3、pytest、PyYAML、Flask/Jinja2、现有 Gateway API/FlowRunner/TaskManager。

**Spec:** `/Users/admin/人际关系项目/dating assitsatant/需求文档/Dating AI Assistant V1.0.0 后端接口协议 (1).md`

## Global Constraints

- dev 平台只执行 Dating test；不创建或读取 staging 配置。
- 平台配置与 Credential 仍为运行配置唯一真源，项目 YAML 只保存测试资产。
- 成功请求只断言 HTTP 200 与 Gateway 顶层 `message=ok`；流程必需字段仍通过 `extract` 强制存在。
- 负向请求断言子响应 `success=false`，只有协议已冻结时才断言 `business_error_code`。
- `multi_image_analysis` 与 `multi_image_reply` 不调用 `DeleteTaskData`。
- `DeleteAccount`、`DeleteUserData` 必须使用任务级隔离匿名账号，不得污染平台 `anonymous_session`。
- 不使用隔离 worktree；用户已明确要求在本机主工作目录开发。

---

### Task 1: 锁定 20 个 API 与成功断言契约

**Files:**
- Create: `projects/dating/data/apis/UpdateReplyAssociation.yaml`
- Create: `projects/dating/data/apis/SubmitFeedback.yaml`
- Create: `projects/dating/data/apis/DeleteUserData.yaml`
- Modify: `projects/dating/data/cases/*.yaml`
- Modify: `projects/dating/data/scenarios/anonymous_session_refresh.yaml`
- Test: `tests/test_dating_assets.py`

**Interfaces:**
- Produces: API ID 到真实 Gateway `service_name/method_name` 的 20 项注册表。
- Produces: `SUCCESS_ASSERTION = {http_status: 200, gateway: {message: ok}}` 对应的项目资产契约。

- [ ] **Step 1: 写失败测试**

  在 `EXPECTED_APIS` 增加：

  ```python
  "UpdateReplyAssociation": (
      "tool.dating.DatingAssistantService",
      "UpdateReplyAssociation",
      "anonymous_session",
  ),
  "SubmitFeedback": (
      "tool.dating.DatingFeedbackService",
      "SubmitFeedback",
      "anonymous_session",
  ),
  "DeleteUserData": (
      "tool.dating.DatingAssistantService",
      "DeleteUserData",
      "anonymous_session",
  ),
  ```

  并断言所有成功 Case 与 `anonymous_session_refresh` 成功步骤只使用 `http_status/message`。

- [ ] **Step 2: 运行测试确认因缺少 3 个 API 和旧断言失败**

  Run: `.venv/bin/python -m pytest tests/test_dating_assets.py -q`

- [ ] **Step 3: 添加路由并统一成功断言**

  API 文件沿用现有四字段模型；保留 Case/Flow 所需 `extract`，删除易变化的 `data_fields/data_equals/data_types`。

- [ ] **Step 4: 运行测试确认通过**

  Run: `.venv/bin/python -m pytest tests/test_dating_assets.py -q`

### Task 2: 增加 15 个独立 Case

**Files:**
- Create: `projects/dating/data/cases/RefreshSession.yaml`
- Create: `projects/dating/data/cases/PrepareMediaUpload.yaml`
- Create: `projects/dating/data/cases/SubmitFeedback.yaml`
- Test: `tests/test_dating_assets.py`
- Test: `tests/test_runtime_overrides.py`

**Interfaces:**
- Produces: Refresh 2、Prepare 6、Feedback 7，共 15 个新 Case。

- [ ] **Step 1: 写失败的 Case 清单与参数边界测试**

  断言完整 ID 集合，并检查：

  ```python
  assert prepare_cases["prepare_size_at_limit_success"] == 7_000_000
  assert prepare_cases["prepare_size_over_limit"] == 7_000_001
  assert feedback_cases["submit_feedback_message_max_success"] == "测" * 500
  assert feedback_cases["submit_feedback_message_too_long"] == "测" * 501
  ```

- [ ] **Step 2: 运行测试确认 Case 缺失**

  Run: `.venv/bin/python -m pytest tests/test_dating_assets.py tests/test_runtime_overrides.py -q`

- [ ] **Step 3: 添加 Case YAML**

  成功 Case 使用顶层 message 断言；无效 refresh token 使用 `UNAUTHENTICATED`，其余未冻结校验错误只断言 `responses[0].success=false`，避免猜错误码。

- [ ] **Step 4: 运行测试确认通过**

  Run: `.venv/bin/python -m pytest tests/test_dating_assets.py tests/test_runtime_overrides.py -q`

### Task 3: 为 Flow 注入稳定运行 ID 与隔离会话

**Files:**
- Modify: `utils/custom/flow_runner.py`
- Modify: `test_cases/test_gateway_flow.py`
- Modify: `utils/custom/assertions.py`
- Test: `tests/test_dating_flow_behavior.py`
- Test: `test_cases/test_gateway_flow.py`

**Interfaces:**
- Produces: `FlowRunner.run()` 上下文中的 `flow_run_id: str`，同一 Flow 内稳定、不同任务不同。
- Produces: `assert.data_not_equals` 路径断言，用于注销后新旧 user id 比较。
- Produces: `isolated` 标签执行语义：清空共享会话、派生任务级 device id、禁用 Credential write-back。

- [ ] **Step 1: 写稳定 ID、非相等断言和隔离会话失败测试**

  测试同一 Runner 内两个 API 参数都解析到相同 `{{flow_run_id}}-analysis`；隔离 Flow 的 Gateway 设置不得携带共享 token，且 device id 必须含任务 ID。

- [ ] **Step 2: 运行局部测试确认失败**

  Run: `.venv/bin/python -m pytest tests/test_dating_flow_behavior.py test_cases/test_gateway_flow.py -q`

- [ ] **Step 3: 最小实现三个执行契约**

  `FlowRunner` 仅在调用方未注入时生成 UUID；pytest 平台路径优先使用 `--task-id`。`isolated` 逻辑只按标签启用，不改变普通 Flow。

- [ ] **Step 4: 运行局部测试确认通过**

  Run: `.venv/bin/python -m pytest tests/test_dating_flow_behavior.py test_cases/test_gateway_flow.py -q`

### Task 4: 扩展现有主 Flow 并隔离清理 Flow

**Files:**
- Modify: `projects/dating/data/scenarios/multi_image_analysis.yaml`
- Modify: `projects/dating/data/scenarios/multi_image_reply.yaml`
- Delete: `projects/dating/data/flows/single_image_analysis_happy_path.yaml`
- Delete: `projects/dating/data/scenarios/single_image_analysis_happy_path.yaml`
- Create: `projects/dating/data/flows/delete_task_data_contract.yaml`
- Create: `projects/dating/data/scenarios/delete_task_data_contract.yaml`
- Test: `tests/test_dating_assets.py`
- Test: `tests/test_dating_flow_behavior.py`

**Interfaces:**
- Produces: Analysis 的 `other_person_name/background/locale` 运行输入。
- Produces: Reply 的 `requested_intent/background/locale` 运行输入。
- Produces: 仅显式选择时执行的 `delete_task_data_contract`。

- [ ] **Step 1: 写失败的运行输入、保留和清理隔离测试**
- [ ] **Step 2: 运行局部测试确认失败**
- [ ] **Step 3: 修改两个 Scenario 并迁移清理 Flow**
- [ ] **Step 4: 运行局部测试确认通过**

### Task 5: 增加媒体与 Analysis Flow

**Files:**
- Create: `projects/dating/data/flows/media_upload_contract.yaml`
- Create: `projects/dating/data/scenarios/media_upload_contract.yaml`
- Create: `projects/dating/data/flows/analysis_idempotency.yaml`
- Create: `projects/dating/data/scenarios/analysis_idempotency.yaml`
- Create: `projects/dating/data/flows/analysis_not_ready_then_success.yaml`
- Create: `projects/dating/data/scenarios/analysis_not_ready_then_success.yaml`
- Create: `projects/dating/data/flows/analysis_rejected.yaml`
- Create: `projects/dating/data/scenarios/analysis_rejected.yaml`
- Test: `tests/test_dating_assets.py`
- Test: `tests/test_dating_flow_behavior.py`

**Interfaces:**
- Produces: 1～9 张动态文件输入、上传完成、幂等、不就绪和预期拒绝场景。

- [ ] **Step 1: 写失败的拓扑与执行行为测试**
- [ ] **Step 2: 运行局部测试确认失败**
- [ ] **Step 3: 添加四组 Flow/Scenario**
- [ ] **Step 4: 运行局部测试确认通过**

### Task 6: 增加 Reply、关联与反馈 Flow

**Files:**
- Create: `projects/dating/data/flows/reply_preferences_lifecycle.yaml`
- Create: `projects/dating/data/scenarios/reply_preferences_lifecycle.yaml`
- Create: `projects/dating/data/flows/reply_idempotency_supersede_resume.yaml`
- Create: `projects/dating/data/scenarios/reply_idempotency_supersede_resume.yaml`
- Create: `projects/dating/data/flows/reply_association.yaml`
- Create: `projects/dating/data/scenarios/reply_association.yaml`
- Create: `projects/dating/data/flows/feedback_with_attachments.yaml`
- Create: `projects/dating/data/scenarios/feedback_with_attachments.yaml`
- Test: `tests/test_dating_assets.py`
- Test: `tests/test_dating_flow_behavior.py`

**Interfaces:**
- Produces: 偏好版本、Reply 活跃任务复用/替换/恢复、人物关联与反馈附件完整链路。

- [ ] **Step 1: 写失败的拓扑、参数复用与保留行为测试**
- [ ] **Step 2: 运行局部测试确认失败**
- [ ] **Step 3: 添加四组 Flow/Scenario**
- [ ] **Step 4: 运行局部测试确认通过**

### Task 7: 增加用户数据与账号删除隔离 Flow

**Files:**
- Create: `projects/dating/data/flows/delete_user_data_contract.yaml`
- Create: `projects/dating/data/scenarios/delete_user_data_contract.yaml`
- Create: `projects/dating/data/flows/delete_account_contract.yaml`
- Create: `projects/dating/data/scenarios/delete_account_contract.yaml`
- Test: `tests/test_dating_assets.py`
- Test: `tests/test_dating_flow_behavior.py`

**Interfaces:**
- Consumes: Task 3 的 `isolated` 会话和 `data_not_equals`。
- Produces: 不进入 smoke/regression 的显式破坏性验收资产。

- [ ] **Step 1: 写失败的破坏性标签与隔离行为测试**
- [ ] **Step 2: 运行局部测试确认失败**
- [ ] **Step 3: 添加两个隔离 Flow/Scenario**
- [ ] **Step 4: 运行局部测试确认通过**

### Task 8: 完整验证与本机发布

**Files:**
- Modify: `README.md`（仅在用例清单或运行说明已有对应章节时更新）

**Interfaces:**
- Produces: 可由本机 `/api-autotest/catalog` 读取并提交的最终资产。

- [ ] **Step 1: 静态资产校验**

  Run: `.venv/bin/python runtest.py --validate-projects`

- [ ] **Step 2: 工具完整回归**

  Run: `.venv/bin/python -m pytest tests -q`

- [ ] **Step 3: 真实测试只执行低风险成功 Case 与媒体/主 Flow**

  通过本机平台提交 Dating/test；不自动运行 `destructive/isolated` Flow，不向 prod 发请求。

- [ ] **Step 4: 重启或刷新本机 api-autotest 服务并验证 Catalog**

  验证 `/api-autotest/catalog` 显示 20 API、新 Cases 和新 Flows，页面可提交任务。

