# API AutoTest Release Device ID 优先级修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 确保 API AutoTest 新任务始终使用当前项目 Release 的 `gateway.comm.device_id`，旧个人凭证中的 `DEVICE_ID` 只保留历史兼容且不再覆盖运行值。

**Architecture:** 平台以 Runtime Scope Release 作为 Comm 静态参数唯一真源；个人 Credential 只提供 Token、用户与过期时间等动态会话字段。工具端再增加防御性优先级，防止旧平台快照中的 `DEVICE_ID` 覆盖静态 Comm。Credential Agent 刷新会话时读取 Credential 所属 Scope 的当前 Release，并复用同一 Comm。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Alembic、Flask/pytest、React/Vitest、Docker Compose。

**Spec:** `/Users/admin/Testproject/Truthy_ApiAutoTest2/docs/接口自动化多项目支持与Dating接入-PRD.md`

## Global Constraints

- dev 平台只执行 test，prod 平台只执行 prod。
- 平台 Release 是静态 Comm 唯一真源；个人 Credential 不得覆盖 `device_id`。
- 保留历史 Credential/Release 数据，不删除用户已有 Secret。
- 直接修改用户指定的本机工作目录，不创建 worktree，不提交现有未提交内容。
- 所有行为修改先执行 RED，再最小实现 GREEN。

---

### Task 1: 工具快照中 Release Device ID 优先

**Files:**
- Modify: `/Users/admin/Testproject/Truthy_ApiAutoTest2/tests/test_task_manager.py`
- Modify: `/Users/admin/Testproject/Truthy_ApiAutoTest2/tests/test_runtime_snapshot.py`
- Modify: `/Users/admin/Testproject/Truthy_ApiAutoTest2/web/task_manager.py`
- Modify: `/Users/admin/Testproject/Truthy_ApiAutoTest2/utils/custom/config_loader.py`

**Interfaces:**
- Consumes: 平台 materialize 的 `normal.gateway.comm` 与兼容期 `secrets.DEVICE_ID`。
- Produces: `settings.comm.device_id` 和 `runtime_session.device_id` 均为 Release 值。

- [ ] **Step 1: 修改 TaskManager 测试，使凭证 Device 与 Release 冲突时断言 Release 值胜出**

```python
assert settings["comm"]["device_id"] == "release-device"
assert settings["comm"]["auth_token"] == "credential-token"
```

- [ ] **Step 2: 增加运行快照加载测试，令 `runtime_variables.DEVICE_ID=credential-device`，断言 `runtime_session.device_id=release-device`**

```python
assert settings["runtime_session"]["device_id"] == "snapshot-device"
```

- [ ] **Step 3: 运行两个测试并确认因旧覆盖行为失败**

Run: `.venv/bin/python -m pytest tests/test_task_manager.py::TestMultiProjectTaskV2::test_platform_payload_preserves_gateway_comm_before_credential_overlay tests/test_runtime_snapshot.py::test_platform_snapshot_prefers_release_device_over_legacy_credential_device -q`

- [ ] **Step 4: 从 Secret→Comm 映射移除 `DEVICE_ID`，并在平台加载器中让 Comm Device 优先于兼容变量**

```python
secret_comm_mapping = {
    "AUTH_TOKEN": "auth_token",
    "ACCESS_TOKEN": "auth_token",
    "USER_ID": "user_id",
}
```

- [ ] **Step 5: 运行局部测试确认 GREEN**

Run: `.venv/bin/python -m pytest tests/test_task_manager.py tests/test_runtime_snapshot.py -q`

---

### Task 2: 平台停止把旧 DEVICE_ID 物化为运行凭证

**Files:**
- Create: `/Users/admin/Testproject/test-platform/backend/alembic/versions/20260828_0023_retire_api_autotest_credential_device_id.py`
- Modify: `/Users/admin/Testproject/test-platform/backend/tests/test_phase2.py`
- Modify: `/Users/admin/Testproject/test-platform/backend/tests/test_migrations.py`
- Modify: `/Users/admin/Testproject/test-platform/backend/app/api/internal.py`
- Modify: `/Users/admin/Testproject/test-platform/backend/app/api/configuration.py`
- Modify: `/Users/admin/Testproject/test-platform/frontend/src/App.tsx`
- Modify: `/Users/admin/Testproject/test-platform/frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `ConfigDefinition.validation_schema.runtime_config_excluded`。
- Produces: 新 selector、materialize 响应、凭证表单和会话写回均不再包含 `DEVICE_ID`。

- [ ] **Step 1: 增加平台集成测试：Credential 仍有旧 Device，Release 有新 Device，materialize 只在 normal 返回新 Device**

```python
assert materialized.json()["normal"]["gateway.comm"]["device_id"] == "release-device"
assert "DEVICE_ID" not in materialized.json()["secrets"]
```

- [ ] **Step 2: 增加迁移测试，断言 0023 将定义标记为 excluded、required=false，降级恢复**

- [ ] **Step 3: 增加前端测试，断言带 excluded 标记的 Device ID 不出现在个人凭证表单**

- [ ] **Step 4: 运行测试并确认 RED**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_phase2.py backend/tests/test_migrations.py -k 'device_id or runtime_scope_chain' -q`

Run: `npm test -- --run`（工作目录 `test-platform/frontend`）

- [ ] **Step 5: 实现 0023 与服务端过滤，旧 SecretVersion 保留但不解密、不进入 selector 或运行响应**

- [ ] **Step 6: 让凭证编辑/会话写回过滤 excluded 定义，前端按相同标记隐藏字段**

- [ ] **Step 7: 运行局部测试确认 GREEN**

---

### Task 3: Credential Agent 使用所属 Scope 的静态 Comm

**Files:**
- Modify: `/Users/admin/Testproject/test-platform/backend/tests/test_phase2.py`
- Modify: `/Users/admin/Testproject/test-platform/backend/app/jobs/credential_agent.py`

**Interfaces:**
- Consumes: `UserCredential.runtime_scope_id` 与 Scope 当前激活 Release。
- Produces: `_runtime_inputs()` 返回当前项目的 `gateway.comm`；`_gateway_session()` 请求使用其中的 `device_id/platform/app_version/...`。

- [ ] **Step 1: 增加失败测试，建立 tool 级旧 Comm 与 Dating Scope 新 Comm，断言 Agent 读取 Dating 值**

- [ ] **Step 2: 增加失败测试，断言 `_gateway_session()` 发送 Release Device 而非 Secret Device**

- [ ] **Step 3: 运行测试确认 RED**

Run: `.venv/bin/python -m pytest tests/test_phase2.py -k 'agent_uses_runtime_scope_comm or gateway_session_prefers_release_comm' -q`

- [ ] **Step 4: 按 Credential 类型选择 `tool_project_scope` Activation，并从 `gateway.comm` 构造静态 Comm**

- [ ] **Step 5: 跳过 excluded 的历史 Credential Item，运行局部测试确认 GREEN**

---

### Task 4: 回归、部署与真实任务验证

**Files:**
- Verify: `/Users/admin/Testproject/Truthy_ApiAutoTest2/logs/dating/test/<date>/`
- Verify: `/Users/admin/Testproject/Truthy_ApiAutoTest2/tasks/<new_task_id>.json`

**Interfaces:**
- Consumes: Dating/test 当前生效 v5。
- Produces: 新任务记录固化 v5，Gateway 请求日志使用 `apiautotest-device-test-002`。

- [ ] **Step 1: 运行平台后端、前端和工具全量回归**

Run: `backend/.venv/bin/python -m pytest -q`

Run: `npm test -- --run && npm run build`

Run: `.venv/bin/python -m pytest tests -q && .venv/bin/python -m pytest test_cases/test_framework.py test_cases/test_v12.py test_cases/test_v13.py test_cases/test_allure_report.py -q`

- [ ] **Step 2: 构建镜像、执行 0023、重建 platform-api、credential-agent、api-autotest 与 gateway**

- [ ] **Step 3: 通过平台任务 API 重跑 `anonymous_session_refresh`，不调用 prod**

- [ ] **Step 4: 检查新任务记录的 release_version=5，并核对日志所有 `device_id` 均为 `apiautotest-device-test-002`**

- [ ] **Step 5: 检查容器健康、错误日志与 `git diff --check`，记录外部 Gateway 失败（如有）而不伪报通过**

