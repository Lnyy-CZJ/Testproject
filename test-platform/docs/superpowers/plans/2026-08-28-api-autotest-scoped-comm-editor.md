# 接口自动化项目化 Comm 配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Truthy 与 Dating 的静态 Gateway `comm` 按 Runtime Scope 独立配置，并在配置控制面原位置查看草稿、生效及历史版本的普通配置值。

**Architecture:** `ConfigDefinition` 继续保持 Tool 级，`validation_schema` 只声明字段编辑元数据、动态键禁用规则及项目适用范围；具体值继续存入 `tool_project_scope` 所属的 `ConfigReleaseItem`。前端在现有配置网格内按 Release 状态切换只读/编辑模式，工具运行时再次剔除动态 `comm` 键，形成平台校验与执行器双重防线。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、PostgreSQL/SQLite、React、TypeScript、Vitest、Testing Library、Pytest、Docker Compose。

**Spec:** `/Users/admin/Testproject/Truthy_ApiAutoTest2/docs/接口自动化多项目支持与Dating接入-PRD.md`，以及 2026-08-28 用户确认的结构化 Comm 编辑与历史版本查看设计。

## Global Constraints

- 平台配置仍是 Runtime Scope、Release 和静态 `comm` 的唯一真源。
- `auth_token`、`user_id`、`client_request_id` 不允许写入 Release。
- Dating/test 使用独立 `device_id`，初始静态值为 `ios / 1.0.0 / en-US / UTC+08:00 / CN / com.example.dating`。
- Dating 只展示 Analysis 专属配置；Truthy 只展示 Admin 登录配置；公共 Gateway 配置两边都展示。
- 沿用现有 React、CSS Token 和双列配置网格，不引入依赖或新页面。
- 当前主工作区包含用户未提交内容；只修改本计划列出的文件，不暂存或提交其他文件。

---

### Task 1: 后端静态 Comm 与项目适用范围约束

**Files:**
- Create: `backend/alembic/versions/20260828_0022_projectize_api_autotest_comm.py`
- Modify: `backend/app/api/configuration.py`
- Test: `backend/tests/test_phase2.py`
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: `ConfigDefinition.validation_schema`、`ToolProjectScope.project_id`。
- Produces: `gateway.comm` 的 `required_keys`、`forbidden_keys`、`field_order`、`field_labels` 元数据，以及 `_definition_applies_to_owner(...) -> bool`。

- [ ] **Step 1: 写 API 失败测试**

  在 Scope Release 集成测试中提交 `gateway.comm`：静态键对象应成功；包含 `auth_token`、`user_id` 或 `client_request_id` 应返回 `422 CONFIG_VALIDATION_FAILED`；Dating Scope 提交 Truthy-only `ADMIN_LOGIN_API_URL` 也应返回 422。

- [ ] **Step 2: 运行测试并确认因缺少约束而失败**

  Run: `backend/.venv/bin/python -m pytest backend/tests/test_phase2.py -q -k 'comm or project_specific_definition'`

- [ ] **Step 3: 写迁移失败测试**

  从 0021 构造具有相同 Truthy/Dating `gateway.comm` 的两个 Active Release，升级 0022 后断言：Definition 带编辑元数据；Dating 获得新 Active Release；旧 Dating Release 变为 superseded；Truthy 值不变。

- [ ] **Step 4: 运行迁移测试并确认 0022 不存在而失败**

  Run: `backend/.venv/bin/python -m pytest backend/tests/test_migrations.py -q -k projectize_api_autotest_comm`

- [ ] **Step 5: 实现最小后端约束与迁移**

  `validation_schema` 使用以下稳定结构：

  ```json
  {
    "required_keys": ["device_id", "platform", "app_version"],
    "forbidden_keys": ["auth_token", "user_id", "client_request_id"],
    "property_name_pattern": "^[a-z][a-z0-9_]{0,63}$",
    "string_values": true,
    "max_properties": 32,
    "field_order": ["device_id", "platform", "app_version", "locale", "timezone", "country", "app_package"],
    "field_labels": {
      "device_id": "Device ID",
      "platform": "客户端平台",
      "app_version": "客户端版本",
      "locale": "语言区域",
      "timezone": "时区",
      "country": "国家/地区",
      "app_package": "应用包名"
    }
  }
  ```

  `_validate_value` 对 JSON 对象校验必填键、禁用键、键名、字符串值与数量；`_definition_applies_to_owner` 根据 `validation_schema.project_ids` 拒绝跨项目字段。

- [ ] **Step 6: 运行局部后端测试**

  Run: `backend/.venv/bin/python -m pytest backend/tests/test_phase2.py backend/tests/test_migrations.py -q`

### Task 2: 执行器剔除动态 Comm 配置

**Files:**
- Modify: `../Truthy_ApiAutoTest2/api/gateway_api.py`
- Test: `../Truthy_ApiAutoTest2/test_cases/test_v12.py`

**Interfaces:**
- Consumes: Release 或接口 transport 提供的静态 `comm`。
- Produces: `build_payload(...)` 只从配置复制静态键，再由运行时写入 `auth_token`、`user_id`、`client_request_id`。

- [ ] **Step 1: 写失败测试**

  构造含三个动态键的静态 `comm`，在无会话和有会话两种情况下断言：配置值不会透传；有会话时 Token/User ID 来自 `RuntimeContext`；request ID 始终由执行器生成。

- [ ] **Step 2: 运行测试并确认旧实现会透传无会话动态键**

  Run: `.venv/bin/python -m pytest test_cases/test_v12.py -q -k dynamic_comm`

- [ ] **Step 3: 实现并验证**

  增加单一动态键常量，并在 `build_payload` 复制 `comm_source` 时排除这些键。

  Run: `.venv/bin/python -m pytest test_cases/test_v12.py -q`

### Task 3: 配置控制面展示生效/历史值并结构化编辑 Comm

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/app.css`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `ConfigRelease.items` 和 `ConfigDefinition.validation_schema`。
- Produces: `GatewayCommEditor`、Release 查看状态，以及相同配置网格中的只读/草稿模式。

- [ ] **Step 1: 写只读生效值失败测试**

  返回无草稿、有 Active Release 的响应，断言当前值出现在禁用输入框中，工具栏显示“当前生效 v2 · 只读”，不再显示空输入框。

- [ ] **Step 2: 写历史版本与 Comm 编辑失败测试**

  点击 v1 的“查看配置”后同一区域显示 v1 值；返回草稿后，七个已知静态字段和额外静态字段可编辑；动态键不显示且不能新增。

- [ ] **Step 3: 运行前端测试并确认失败原因正确**

  Run: `npm test -- --run src/App.test.tsx`

- [ ] **Step 4: 实现最小组件和状态切换**

  默认选择 `draft ?? active ?? releases[0]`；只有当前查看对象是 draft 时可编辑。`gateway.comm` 跨两列渲染嵌套字段网格，已知字段固定排序，未知静态字段继续展示，并提供键名/值输入与“新增静态参数”。

- [ ] **Step 5: 实现项目适用范围过滤和 Apple-inspired 状态样式**

  根据 `project_ids` 隐藏无关字段；版本行提供清晰“查看配置”操作和当前选中状态；保持 8px 网格、系统字体、可见焦点和非纯颜色状态。

- [ ] **Step 6: 运行前端测试与构建**

  Run: `npm test`

  Run: `npm run build`

### Task 4: 部署、数据迁移和真实页面验收

**Files:**
- Create: `frontend/design-qa.md`（按 Product Design 视觉核对流程生成）

**Interfaces:**
- Consumes: 0022 数据迁移和构建后的 platform frontend/backend。
- Produces: 本机 Dating Active Release v3、可打开的配置控制面和视觉 QA 结果。

- [ ] **Step 1: 跑完整回归和 diff 检查**

  Run: `backend/.venv/bin/python -m pytest -q`

  Run: `npm test && npm run build`

  Run: `../Truthy_ApiAutoTest2/.venv/bin/python -m pytest ../Truthy_ApiAutoTest2/tests -q`

  Run: `../Truthy_ApiAutoTest2/.venv/bin/python -m pytest ../Truthy_ApiAutoTest2/test_cases -q -k 'not gateway_flow and not single_gateway_api'`

  Run: `git diff --check`

- [ ] **Step 2: 重建本机平台服务并应用 0022**

  Run: `docker compose up -d --build --force-recreate platform-migrate platform-api platform-gateway api-autotest`

- [ ] **Step 3: 核对数据库隔离**

  断言 Dating/Truthy Active Release ID 不同、`device_id` 不同、Dating 包含 `app_package`，且各自 Session Credential 仍绑定各自 Scope。

- [ ] **Step 4: 在 1280px 和 1440px 桌面视口完成浏览器验收**

  覆盖 Active 只读、历史版本查看、创建草稿、Comm 编辑、动态键拒绝、键盘焦点、加载/错误状态；将参考截图与实现截图并排检查，`design-qa.md` 最终写入 `final result: passed`。
