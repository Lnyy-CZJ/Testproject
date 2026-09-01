# Dating Multi-image Analysis Flow Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在现有多项目 Gateway 接口自动化工具中增加可从 Web 选择 1～9 张本机图片的 Dating Analysis Flow，安全保留任务输入、按顺序完成多图片上传并在 dev/test 获取分析结果。

**Architecture:** 平台仍是 Runtime Scope/Release/Credential 唯一真源；工具项目包仍是 Flow/Scenario 唯一真源。Web 仅把 multipart 文件保存到任务私有 `runtime/<project>/<task>/inputs`，执行进程通过受控 manifest 将文件元数据交给通用 FlowRunner。公共 DSL 用一层 `foreach`、受控点路径变量和 `input_file` 扩展表达多图上传，不写死 Dating 业务。

**Tech Stack:** Python 3、pytest、Flask/Jinja2、原生 JavaScript/CSS、YAML、现有 Gateway/Allure/JUnit 适配层。

**Execution note:** 用户明确要求在本机主工作目录实施，不使用隔离 worktree；因此保留当前所有既有未提交改动，只对本计划列出的文件做精准增量修改。

---

## Task 1: 锁定任务附件存储契约

**Files:**
- Modify: `tests/test_task_manager.py`
- Modify: `web/task_store.py`
- Modify: `web/task_manager.py`

**Step 1: Write the failing tests**

增加覆盖：

- 9 张合法 PNG 按传入顺序保存到 `runtime/dating/<task>/inputs`。
- manifest 和任务记录只有元数据，保存文件及 manifest 权限为 `0600`。
- 伪造 MIME、非法文件头、空文件、超过 7 MB、超过 9 张、路径型文件名被拒绝或安全归一化。
- 保存中途失败时清理未建成的任务目录且不占用执行槽。
- retry 复制输入到新任务并保持顺序，源文件缺失/摘要不符返回 `TASK_INPUTS_MISSING`。
- `TaskStore.delete()` 继续删除整个任务输入目录。

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_task_manager.py -q`

Expected: 新附件 API、元数据与重试语义尚不存在而失败。

**Step 3: Write minimal implementation**

- 在 `TaskStore` 内实现任务输入目录、安全文件名、流式写入、文件头识别、SHA-256、0600 manifest、复制校验和失败清理。
- `TaskManager.submit()` 接受内部 upload 对象，在生成 task_id 后持久化附件，再保存任务记录并启动执行。
- 任务记录增加 `attachments` 与 `input_manifest_file`；无附件的旧任务保持兼容。
- `retry()` 使用原任务记录复制附件，不修改旧任务。

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_task_manager.py -q`

Expected: PASS。

## Task 2: 扩展 Flow DSL 的安全表达能力

**Files:**
- Modify: `test_cases/test_v12.py`
- Modify: `tests/test_signed_upload.py`
- Modify: `utils/custom/runtime_context.py`
- Modify: `utils/custom/flow_loader.py`
- Modify: `utils/custom/project_registry.py`
- Modify: `utils/custom/flow_runner.py`

**Step 1: Write the failing tests**

增加覆盖：

- `{{media_file.relative_path}}` 逐层读取 Mapping，完整表达式保留数字/列表类型。
- 未定义字段、标量中途访问、非法表达式均失败。
- `foreach` 按原列表顺序执行，禁止嵌套，`collect` 生成有序列表。
- Scenario 可为 foreach 内 API step 提供数据，重复 step ID 被拒绝。
- `signed_binary_upload` 的 `fixture` / `input_file` 必须且只能选择一个。
- `input_file` 仅允许当前 task inputs 内普通文件；拒绝绝对路径、`..`、符号链接和越界。
- `validate_binary_inputs` 在外部调用前校验类型、数量和大小。
- `until.fail_on_termination=true` 在 failed/rejected 终态抛出 `FLOW_TERMINATED` 行为，不继续后续 API。
- 旧 fixture upload 和旧 Flow 行为不回归。

**Step 2: Run tests to verify they fail**

Run: `python -m pytest test_cases/test_v12.py tests/test_signed_upload.py -q`

Expected: 新 DSL 字段与运行能力尚不支持而失败。

**Step 3: Write minimal implementation**

- `RuntimeContext` 支持受控点路径读取和循环变量恢复所需的 contains/unset。
- Flow loader 递归校验一层 foreach 子步骤、collect 与 input contract；继续拒绝未知字段。
- ProjectRegistry 的 fixture 校验递归进入 foreach，并跳过合法 `input_file`。
- FlowRunner 抽出共享 step 执行函数，foreach 复用 API/action/wait 逻辑；Allure 名称包含迭代序号。
- 新 action 使用 manifest 元数据做实时约束校验；签名上传只从受控 task input root 读文件。
- 终态失败在明确配置时转为执行失败，原有可清理终止语义保持不变。

**Step 4: Run tests to verify they pass**

Run: `python -m pytest test_cases/test_v12.py tests/test_signed_upload.py -q`

Expected: PASS。

## Task 3: 让 pytest Flow 会话读取任务输入 manifest

**Files:**
- Modify: `test_cases/test_gateway_flow.py`
- Modify: `tests/test_dating_flow_behavior.py`
- Modify: `tests/test_project_cli.py`

**Step 1: Write the failing tests**

增加覆盖：

- manifest project/task 与当前环境不匹配时 fail-closed。
- manifest 相对路径越界、文件缺失或 SHA-256 不匹配时失败。
- 有 manifest 时向 FlowRunner 注入 `media_files` 和 input root。
- 未显式选 Flow 且无 manifest 时，默认集合跳过声明必填文件输入的交互 Flow。
- 显式选择交互 Flow 但无 manifest 时明确失败。

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dating_flow_behavior.py tests/test_project_cli.py -q`

Expected: manifest 尚未进入 pytest Flow 会话而失败。

**Step 3: Write minimal implementation**

- 从 `API_AUTOTEST_TASK_INPUT_MANIFEST_FILE` 读取任务私有 manifest。
- 校验 schema、项目、任务、路径、文件大小与摘要。
- 将图片元数据写入 RuntimeContext 初始变量，向 FlowRunner 传递唯一 input root。
- 调整默认 Flow 参数集合，只过滤必填交互输入 Flow；显式选择保持严格。

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dating_flow_behavior.py tests/test_project_cli.py -q`

Expected: PASS。

## Task 4: 新增 Dating 多图片 Analysis 资产

**Files:**
- Create: `projects/dating/data/flows/multi_image_analysis.yaml`
- Create: `projects/dating/data/scenarios/multi_image_analysis.yaml`
- Modify: `tests/test_dating_assets.py`
- Modify: `tests/test_dating_flow_behavior.py`

**Step 1: Write the failing tests**

断言：

- Dating catalog 现在包含 3 个 Flow，新 Flow 声明 1～9 图片输入契约且标签只有 `interactive`。
- Flow 的 API 顺序与循环结构正确，不包含 `DeleteTaskData`。
- 假 Gateway 使用 3 张输入时：GetMediaUploadConfig 1 次，准备/PUT/完成各 3 次，Create/GetTask/GetResult 各符合预期。
- `asset_ids` 顺序与输入顺序一致。
- failed/rejected 时不调用 GetAnalysisResult。

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dating_assets.py tests/test_dating_flow_behavior.py -q`

Expected: 新 Flow/Scenario 不存在而失败。

**Step 3: Create minimal project assets**

- Flow 先读取上传配置并校验全部输入。
- foreach 内执行 Prepare、PUT、Complete 并收集 asset_id。
- 一次创建分析任务，轮询终态，成功后获取结果。
- 不添加 DeleteTaskData 或任何本地环境配置。

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dating_assets.py tests/test_dating_flow_behavior.py -q`

Expected: PASS。

## Task 5: 增加 multipart Web API 与 catalog input contract

**Files:**
- Modify: `tests/test_web_routes.py`
- Modify: `web/catalog.py`
- Modify: `web/app.py`

**Step 1: Write the failing tests**

增加覆盖：

- catalog 返回 Flow 的真实 `inputs` 契约和递归业务步骤摘要。
- JSON 单接口/普通 Flow 提交继续成功。
- multipart `task_payload` + 重复 `media_files` 提交创建任务，并只把实际文件对象交给 TaskManager。
- 缺图片、错误 JSON、错误字段名、非输入 Flow 携带图片、非法类型、数量越界返回稳定错误码。
- preflight 接受非敏感文件元数据用于 UI 就绪判断，但不把它传给平台 Runtime API。
- retry 路由复制附件并返回新 task id。

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_routes.py -q`

Expected: 当前路由只接受 JSON 且 catalog 不返回 inputs。

**Step 3: Write minimal implementation**

- 保留 JSON 分支；multipart 分支严格解析一个 `task_payload` JSON 和 `media_files`。
- 所有运行覆盖字段继续统一拒绝。
- 根据 catalog input contract 判断是否需要/允许文件，服务端永远重新校验实际上传。
- catalog 递归展平 foreach 的业务步骤，并返回 input contract。

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_routes.py -q`

Expected: PASS。

## Task 6: 落地现有界面体系内的多图片交互

**Files:**
- Modify: `web/templates/task_form.html`
- Modify: `web/templates/task_detail.html`
- Modify: `web/static/app.js`
- Modify: `web/static/app.css`
- Modify: `tests/test_web_routes.py`

**Step 1: Write the failing render/contract tests**

断言 Flow 页面包含：可访问的多文件 label/input、文件列表、错误 live region、输入摘要；详情页包含附件元数据容器。断言 JS 构建 multipart 时不持久化文件内容或公开 URL。

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_web_routes.py -q`

Expected: 新 UI 节点不存在而失败。

**Step 3: Implement the interaction**

- 仅根据 selected flow 的 `inputs.media_files` 显示图片区。
- 浏览器校验 1～9、MIME、7 MB，并支持逐项移除与清空。
- 预检只发送文件名/类型/大小摘要；提交使用 FormData。
- 切换 Flow/项目时清理不再适用的 File 对象。
- 详情页显示名称、类型、大小、摘要前缀和“随任务保留”，不输出磁盘路径或下载 URL。
- 复用现有色彩、边框、圆角、focus-visible 和 reduced-motion；1280px 保持双栏可读。

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_web_routes.py -q`

Expected: PASS。

## Task 7: 局部回归与 example_02 本地验收

**Files:**
- Test only; acceptance artifacts under existing `output/playwright/`

**Step 1: Run focused automated tests**

Run:

```bash
python -m pytest \
  test_cases/test_v12.py \
  tests/test_signed_upload.py \
  tests/test_task_manager.py \
  tests/test_web_routes.py \
  tests/test_dating_assets.py \
  tests/test_dating_flow_behavior.py \
  tests/test_project_cli.py -q
```

Expected: PASS。

**Step 2: Use the authorized nine real images**

用 Playwright 在本机 Flow 页选择：

```text
/Users/admin/人际关系项目/dating assitsatant/测试数据/聊天截图测试数据/Defining relationship关系确认/example_02/chat_01.png
...
/Users/admin/人际关系项目/dating assitsatant/测试数据/聊天截图测试数据/Defining relationship关系确认/example_02/chat_09.png
```

检查顺序、数量、总大小、移除/恢复、提交状态和任务详情元数据。截图保存到既有 `output/playwright/`。

**Step 3: Verify storage and no cleanup call**

检查任务 inputs 目录、0600 权限、manifest 摘要、日志调用顺序，并扫描该任务日志确认没有 `DeleteTaskData`。

## Task 8: 完整回归、发布到本机平台与真实 dev/test 验收

**Files:**
- Existing deployment files only if current local deployment requires rebuild; no new deployment abstraction.

**Step 1: Run complete tool verification**

Run:

```bash
python -m pytest tests -q
python -m pytest test_cases --collect-only -q
python runtest.py --validate-projects
```

Expected: 全部通过，Dating 静态资产显示 11 API、现有 Flow 加新交互 Flow。

**Step 2: Rebuild local api-autotest service**

沿用 `/Users/admin/Testproject/test-platform/docker-compose.yml` 当前服务定义重建并启动接口自动化容器，不修改其他平台服务数据。

**Step 3: Browser visual and accessibility verification**

在 `/api-autotest/tasks/new/flow` 完成 1440px 与 1280px 截图核对、键盘焦点、错误恢复、刷新和任务详情验证。

**Step 4: Run real dev/test Gateway acceptance**

在已有平台登录态和 Dating/test Scope/Release/Credential 可用时提交 9 图真实任务；确认成功结果、日志时间、图片顺序、不调用 `DeleteTaskData`。若外部服务或登录态阻塞，保留已构造任务与证据，并明确区分代码验证与外部验收。

## Task 9: Completion review

**Step 1: Inspect diff scope**

确认只包含本计划增量和实施前已有用户改动；不暂存、不覆盖、不回滚用户文件。

**Step 2: Re-run evidence commands**

完成前再次运行与结论直接相关的测试、项目校验、容器 health 和页面截图。

**Step 3: Report handoff**

向用户提供本机可打开入口、实际任务 ID、9 图输入目录、测试结果、真实 Gateway 结果或外部阻塞，以及明确的验收步骤。

