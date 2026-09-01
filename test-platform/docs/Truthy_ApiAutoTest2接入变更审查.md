# api-autotest 接入变更审查台账（Review）

> 文档版本：V2.0
> 创建日期：2026-08-10
> 文档状态：持续更新台账（提交即记录）
> 配套文档：[Truthy_ApiAutoTest2接入PRD.md](./Truthy_ApiAutoTest2接入PRD.md)（V1.2）、[Truthy_ApiAutoTest2接入开发设计与计划.md](./Truthy_ApiAutoTest2接入开发设计与计划.md)（V1.2）
>
> **定位说明**：按用户 2026-08-10 指令，本文档不再是"用户确认后才提交"的审批文档，而是**提交即记录**的变更台账——每个阶段的改动完成 git 提交后即追加记录到本文档，供用户后期随时查看。文件名保留"阶段0"字样仅为历史延续。

## 0. 提交记录总览

| 阶段 | Commit | 日期 | 摘要 |
|------|--------|------|------|
| 阶段 0：基线冻结 | `c0ba41f` | 2026-08-10 | 恢复 CI 全量收集语义并同步 phase-six 迁移断言（2 个代码文件） |
| 阶段 1：壳服务独立模式 | `268bfeb` | 2026-08-10 | 新增 web/ 壳服务与 tests/ 单元测试，.gitignore 追加 tasks/（19 个文件） |
| 阶段 2：容器化与子路径 | `ee442ef` | 2026-08-10 | Dockerfile/.dockerignore/requirements-web.txt/平台凭证模板（5 个文件） |
| 阶段 3：平台接入 | `901b003` | 2026-08-10 | 迁移/前端第四卡片/Nginx 路由/Compose 服务/冒烟扩展（10 个文件，均在 test-platform/） |
| 阶段 4：报告同步链路 | `ce92754` | 2026-08-10 | 原子发布脚本/Jenkins HTTP 拉取脚本/Jenkinsfile 归档调整/README（5 个文件，均在 api-autotest/） |
| 阶段 5：端到端验收收尾 | `46ed333` | 2026-08-10 | session_token 脱敏修复/守卫测试同步阶段 4 契约/双 README 接入与排障文档（5 个文件，4 个在 api-autotest/、1 个在 test-platform/） |
| 推送 dev 与 Jenkins 端到端验证 | `d659f96`→`d071965` | 2026-08-10 | 探针/revert/报告端点 stat 异常修复/README 排障补充（4 个提交，均已在 dev） |

> 阶段 0 的 PRD/设计文档小修（下文清单第 3、4 项）位于 test-platform/docs/ 目录，为用户新建的未跟踪文件，尚未入库；入库时将在本台账补记。

---

# 第一部分：阶段 0 变更记录

## 1. 记录范围与授权依据

本部分记录 **api-autotest 接入 test-platform 阶段 0（基线冻结）** 期间的全部文件改动。

授权依据（均为用户在本阶段会话中逐项确认）：

- 用户将 PRD 与开发设计文档修订至 V1.2 后，审查发现两处表述不一致，用户选择"先修正再开发"；
- 基线回归出现 3 个失败用例，用户授权"我调查并全部修复"；
- 调查结论与两个修复方案（下文方案①②）经用户明确批准；方案③（NameWithConditionsSearch 测试与场景数据对齐）用户声明由本人自行处理，本次**未触碰**该 Flow 的任何测试与数据文件；
- 用户限定本阶段范围为"执行完阶段 0 就行了，然后出一份 review 文档"，因此**未开始阶段 1 及以后的任何开发**。

## 2. 改动文件清单

| # | 文件 | 改动类型 | 性质 | 原因 |
|---|------|---------|------|------|
| 1 | `api-autotest/test_cases/test_gateway_flow.py` | 代码修改（2 行） | 方案①修复 | RUN_FLOW_IDS 调试残留导致 CI/平台全量收集语义被破坏 |
| 2 | `api-autotest/test_cases/test_v13.py` | 代码修改（+17 行） | 方案②修复 | phase-six 迁移断言未跟随 extract→optional_extract 迁移 |
| 3 | `test-platform/docs/Truthy_ApiAutoTest2接入PRD.md` | 文档补充（2 处） | V1.2 一致性小修 | 8.3 环境变量清单缺 `API_AUTOTEST_REPORT_DIR` |
| 4 | `test-platform/docs/Truthy_ApiAutoTest2接入开发设计与计划.md` | 文档补充（2 处） | V1.2 一致性小修 | 8.1 模块树 scripts/ 缺 `fetch_jenkins_report.sh` |

> 说明：清单 3、4 两份文档整体为用户新建的未跟踪文件（尚未入库），此处改动指本次会话在用户 V1.2 版本上的增量小修。

**明确未改动的文件**：`data/flows/NameWithConditionsSearch.yaml`、`data/scenarios/NameWithConditionsSearch.yaml`、`test_v13.py` 中 `test_name_with_conditions_flow_uses_non_photo_create_task_clues`（用户自留处理）。

## 3. 详细改动内容

### 3.1 test_cases/test_gateway_flow.py（方案①：清除调试残留）

**问题**：提交 `bc754e5` 将 `RUN_FLOW_IDS` 从空元组改为 `("NameWithConditionsAndPhotoSearch",)`。该常量非空时，不带 `--flow` 的入口（平台 `run_type=all`、Jenkins `RUN_TYPE=all`）只会收集这一个 Flow，破坏全量执行语义。仓库内守卫测试 `test_v13.py::test_ci_entry_defaults_collect_all_cases_and_flows`（断言 `RUN_FLOW_IDS == ()`）也因此失败。

**改动 diff**：

```diff
 # 本地调试 Flow 的完整文件名 stem；空元组表示收集全部 Flow。
 # 临时调试示例：("AnonymousSessionMediaSearch",)。
-RUN_FLOW_IDS: tuple[str, ...] = ("NameWithConditionsAndPhotoSearch",)
+# 提交入库时必须保持空元组，否则 CI/平台不带 --flow 的入口只会执行此处列出的 Flow。
+RUN_FLOW_IDS: tuple[str, ...] = ()
```

**影响**：恢复全量收集语义；守卫测试通过。未修改任何收集逻辑本身。

### 3.2 test_cases/test_v13.py（方案②：phase-six 断言跟随迁移）

**问题**：提交 `bc754e5` 将 `AnonymousSessionMediaSearch.yaml` 的 `list_candidates` 步骤从 `extract` 迁移为 `optional_extract`（并新增 `list_empty_reason` 提取与 `candidate_detail` 的 `skip_if` 条件跳过），但 `test_phase_six_migration_preserves_legacy_flow_routes_and_extracts` 的基线仍断言旧的 `extract`，导致失败。

**改动 diff**（`test_phase_six_migration_preserves_legacy_flow_routes_and_extracts` 内）：

```diff
     }
     for step_id, snapshot in LEGACY_FLOW_FINAL_SNAPSHOT.items()
 }
+    # 无候选人是正常结果：list_candidates 的提取规则已由 extract 迁移为
+    # optional_extract（见下方断言），此处基线跟随当前 Flow 结构放宽为空，
+    # 不改动 LEGACY_FLOW_FINAL_SNAPSHOT 本身（它仍是 V1.2 迁移冻结基线）。
+    expected["list_candidates"]["extract"] = {}

 for step_id, expected_step in expected.items():
     assert step_id in actual
@@ poll_task 断言之后 @@
 poll_step = next(step for step in flow["steps"] if step["id"] == "poll_task")
 assert poll_step["until"]["path"] == "$.status"

+    # 空结果扩展行为必须固化：items[0] 不存在时不再强制提取，
+    # 候选人详情步骤依据列表为空原因条件跳过。
+    list_step = next(step for step in flow["steps"] if step["id"] == "list_candidates")
+    assert list_step.get("optional_extract") == {
+        "candidate_id": "$.items[0].candidate_id",
+        "list_empty_reason": "$.empty_reason",
+    }
+    detail_step = next(step for step in flow["steps"] if step["id"] == "candidate_detail")
+    assert detail_step.get("skip_if") == {
+        "variable": "list_empty_reason",
+        "equals": "NO_CANDIDATES",
+    }
```

**为什么不直接改 `LEGACY_FLOW_FINAL_SNAPSHOT`**：该快照同时被 `test_phase_zero_snapshot_records_final_flow_params_and_assertions` 复用（从内联 fixture 计算，语义不同），直接改快照会引入新的失败。因此只在本测试内覆盖期望值，并把新的 `optional_extract`/`skip_if` 行为固化为断言，防止回退。

### 3.3 Truthy_ApiAutoTest2接入PRD.md（小修）

- 8.3 环境变量清单追加一行：`| API_AUTOTEST_REPORT_DIR | reports/allure-current | 同左 | 当前 Allure 报告指针（相对项目根） |`
- 文档头修订记录（V1.2 行）追加："8.3 环境变量清单补 `API_AUTOTEST_REPORT_DIR`"。

### 3.4 Truthy_ApiAutoTest2接入开发设计与计划.md（小修）

- 8.1 模块树 `scripts/` 补齐 `fetch_jenkins_report.sh`（原只列了 `publish_allure_report.sh`，与 12.2 节不一致）；
- 文档头修订记录（V1.2 行）追加："对齐 8.1 scripts/ 目录（补 fetch_jenkins_report.sh）"。

## 4. 阶段 0 基线记录

### 4.1 Git 状态

- 仓库：`/Users/admin/Testproject`（多子项目同仓），分支 `dev`；阶段 0 开始时 HEAD `7665e6b`（与 `origin/dev` 一致）；
- 本次改动的 2 个代码文件经用户确认无误后，已于 2026-08-10 提交为 `c0ba41f`（提交时只精确暂存这 2 个文件，工作区其余无关改动未入库）；
- 相关提交考古：`bc754e5`（2026-08-07，新增照片搜索场景）、`66789bb`（NameWithConditionsSearch 场景首引入）。

### 4.2 框架回归基线（与设计文档第 16 章命令一致）

命令：`python3 -m pytest -q -k "not gateway_flow and not single_gateway_api"`

| 时点 | 结果 |
|------|------|
| 修复前（dev@7665e6b 原样） | `3 failed, 115 passed, 9 deselected` |
| 修复后（方案①②落盘） | `1 failed, 117 passed, 11 deselected` |

修复前后收集数差异（9→11 deselected）原因：`RUN_FLOW_IDS` 非空时收集阶段只参数化 1 个 Flow，恢复空元组后全量 Flow 被收集、相应多出 2 条被 `-k` 排除的参数化项，属预期行为。

剩余唯一失败：`test_v13.py::test_name_with_conditions_flow_uses_non_photo_create_task_clues`（用户自留，见 4.3 与第 5 章）。

### 4.3 基线 3 个失败的考古结论

3 个失败全部追溯到用户自己的场景提交（`bc754e5` / `66789bb`），**非接入工作引入**：

1. `test_ci_entry_defaults_collect_all_cases_and_flows`：`bc754e5` 遗留 `RUN_FLOW_IDS` 非空 → 已由方案①修复；
2. `test_phase_six_migration_preserves_legacy_flow_routes_and_extracts`：`bc754e5` 的 extract→optional_extract 迁移未同步该断言 → 已由方案②修复；
3. `test_name_with_conditions_flow_uses_non_photo_create_task_clues`：`66789bb` 引入该测试当日，断言（FULL_NAME/LOCATION/SOCIAL_LINK、JOJO/CCQQ/MOCK、linkedin URL、4 项 additional_details）就与场景数据不一致；`bc754e5` 又把数据改为 Casey Neistat/x.com 且 LOCATION 保持注释、additional_details 保持为空。测试与数据自始不匹配 → 用户声明自行处理，本次未改。

### 4.4 网络实测

- Docker 默认 bridge 网络可访问 `gateway_base_url`（http://gateway.spark-jam.top）与 Admin（http://admin-staging.spark-jam.top），确认项 9 的容器内执行前提成立。

### 4.5 Jenkins 实测（用户提供：http://10.0.30.33:8081/，远程服务器）

- 任务名为 `truthy-api-autotest`（**不是**设计文档 12.1 中的示例默认值 `InterfaceAutomation`）；
- 匿名访问返回 403，需 Basic 认证（用户名+密码方式可用）；JSON API 可取 `number/result/url/artifacts`；
- 实测构建：#14（SUCCESS）与 #9（FAILURE）均有 `allure-report.zip` → 支持设计文档"拉取最近已完成且有产物构建"的选择策略（失败构建也有报告）；
- 归档形态：`allure-report.zip` 位于归档根；`allure-results/**`、`logs/**` 带 `api-autotest/` 前缀，说明 `archiveArtifacts` 当前在工作区根调用（印证设计 12.1 统一 `dir(PROJECT_DIR)` 作用域的必要性）；
- 调用注意：URL 中 `tree=jobs[name]` 的方括号会被 curl 当作 globbing，必须加 `-g`（globoff）。

## 5. 遗留事项与对后续开发的影响

1. **NameWithConditionsSearch 失败用例由用户处理**。该 Flow 的设计意图为"可以只有 name，也可以 name 加其他 ConditionsSearch"，测试断言与场景数据的对齐方式由用户决定；在用户对齐全量回归仍为 1 failed，阶段 1 冒烟门槛判断时需知悉。
2. **设计文档 JOB_NAME 默认值需同步**：12.1 中示例默认值 `InterfaceAutomation` 应在阶段 4 实施时改为实测任务名 `truthy-api-autotest`。
3. **fetch 脚本实现方式确定**：因 Jenkins 为远程服务器（本机无 JENKINS_HOME），`scripts/fetch_jenkins_report.sh` 必须走 HTTP API + Basic 认证方式；凭证通过环境变量注入，**不得写入仓库任何文件**。
4. **归档路径前缀**：阶段 4 统一 `dir(PROJECT_DIR)` 后产物前缀会从 `api-autotest/...` 变化，fetch 脚本的产物定位逻辑需按届时实际归档形态编写。

## 6. 结论

- 阶段 0（基线冻结）四项工作全部完成：Git 状态记录、框架回归基线、Docker 网络实测、Jenkins 产物形态实测；
- 基线 3 个失败中 2 个已按用户批准方案修复并验证（回归结果 4.2），1 个由用户自留；
- 除本文档所列 4 个文件外，未改动任何其他文件；
- 用户已于 2026-08-10 确认改动无误，2 个代码文件提交为 `c0ba41f`；随后按设计文档第 16/17 章进入阶段 1（见第二部分）。

---

# 第二部分：阶段 1 变更记录（壳服务独立模式）

## 7. 提交信息

- Commit：`268bfeb`（分支 `dev`，父提交 `c0ba41f`）
- 提交消息：`feat: api-autotest 新增阶段 1 独立模式壳服务 web/ 与配套单元测试`
- 改动规模：19 个文件，+3569 行（除 .gitignore 为修改外全部为新增）

## 8. 文件清单

| # | 文件 | 类型 | 说明 |
|---|------|------|------|
| 1 | `web/__init__.py` | 新增 | 壳服务包声明 |
| 2 | `web/redaction.py` | 新增 | 壳服务自产内容二次脱敏与截断（设计偏离①，见第 11 节） |
| 3 | `web/task_store.py` | 新增 | 任务记录原子落盘（.tmp+fsync+os.replace）、列表、保留策略、关联产物清理 |
| 4 | `web/junit_report.py` | 新增 | JUnit XML 解析：统计摘要 + 失败清单（消息脱敏截断 500 字符） |
| 5 | `web/credentials.py` | 新增 | 两级凭证预检、Admin 需求判定（Scenario 原文查 `{{admin_` 占位符）、env/flow 列表 |
| 6 | `web/catalog.py` | 新增 | 用例库只读清单，复用框架加载器；单文件解析失败进 errors 不阻断整体 |
| 7 | `web/task_manager.py` | 新增 | 单槽位执行引擎：提交校验、等待、取消、超时、启动恢复、日志 PID 关联 |
| 8 | `web/app.py` | 新增 | Flask 应用工厂与全部路由；BASE_PATH 校验与 url_prefix 适配（设计偏离②，见第 11 节） |
| 9 | `web/templates/index.html` | 新增 | 首页：执行表单、凭证状态徽章、报告入口、最近任务轮询 |
| 10 | `web/templates/task_detail.html` | 新增 | 任务详情：时间线、结果统计、失败清单、日志查看器、取消 |
| 11 | `web/templates/catalog.html` | 新增 | 用例库页：API/Case/Flow 三表与解析错误 |
| 12 | `tests/conftest.py` | 新增 | 公共夹具：fake_project 骨架、make_manager 工厂、patch_command、junit_xml |
| 13 | `tests/test_task_store.py` | 新增 | 原子落盘、并发读写、列表、删除、保留策略 |
| 14 | `tests/test_junit_report.py` | 新增 | 统计、脱敏、截断、缺失/损坏边界 |
| 15 | `tests/test_redaction.py` | 新增 | 二次脱敏零泄漏（设计偏离③，见第 11 节） |
| 16 | `tests/test_task_manager.py` | 新增 | 参数校验矩阵、凭证预检、退出码映射、超时、取消、竞态、恢复 |
| 17 | `tests/test_catalog.py` | 新增 | 真实项目快照 + 伪造项目错误隔离 |
| 18 | `tests/test_web_routes.py` | 新增 | 全端点契约、根路径/子路径两种模式、分页、报告、日志兜底脱敏 |
| 19 | `.gitignore` | 修改 | 追加忽略壳服务任务记录目录 `tasks/` |

## 9. 关键实现要点

- **单槽位与终态不可迁移**：槽位检查→建记录→占槽在同一锁内原子完成；等待线程是终态唯一写入者，取消只标记 `cancel_requested_at` 并向进程组发信号，避免取消/完成竞态产生双终态；
- **子进程安全**：`Popen` 参数数组不经 shell（无注入面）、`start_new_session` 独立进程组；取消/超时走 SIGTERM → 宽限期 → SIGKILL；命令构成对齐 Jenkinsfile（single/flow/all 入口 + `--env=` + 可选 `--flow=`/`-m tag` + `--junitxml`，平台任务不带 `--alluredir`）；
- **退出码语义**：0→succeeded（但全跳过→failed + ALL_TESTS_SKIPPED）；1→failed（有 JUnit 时错误信息不附 console）；2/其他→failed + 脱敏 console 尾部；5→"未收集到用例"；超时→failed + timeout=true + TASK_TIMEOUT；
- **日志策略**：优先按子进程 PID 关联框架脱敏日志（`logs/YYYY-MM-DD/{时间戳}_{env}_{pid}.log`）；无框架日志时兜底返回二次脱敏后的 console 尾部，接口显式标注来源（framework_log / console_redacted / none）；
- **展示安全**：console、失败摘要等壳服务自产内容统一经 `redaction.redact_text` 脱敏（Authorization/Bearer、Cookie、敏感键值、预签名 URL 参数、容器内绝对路径）并截断；
- **启动恢复**：服务启动时把遗留 pending/running 任务置为 failed（"服务重启，任务中断"）；
- **稳定错误码**：SLOT_BUSY(409)、INVALID_PARAMS、CREDENTIALS_MISSING、CREDENTIAL_FILE_INVALID、ADMIN_CREDENTIALS_MISSING、TASK_NOT_FOUND(404)、TASK_TERMINATED(409)、TASK_TIMEOUT、ALL_TESTS_SKIPPED、JUNIT_NOT_GENERATED。

## 10. 验证结果

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 壳服务单元测试 | `python3 -m pytest tests/ -q` | **108 passed**（子进程全部用 `python -c` 模拟，不发真实请求） |
| 框架回归 | `python3 -m pytest -q -k "not gateway_flow and not single_gateway_api"` | `1 failed, 225 passed, 11 deselected` |

回归中唯一失败仍为阶段 0 基线中的用户自留用例 `test_name_with_conditions_flow_uses_non_photo_create_task_clues`（NameWithConditionsSearch，由用户自行处理），接入改动未引入任何新失败；225 = 基线 117 + 新增壳服务测试 108。

## 11. 与设计文档 V1.2 的偏离点（审查重点）

1. **新增 `web/redaction.py` 独立模块**：设计 8.1 模块树未列出该模块，但 8.4 要求"壳服务自产内容统一脱敏后输出"、17.1 列有 redaction 测试项；抽为独立模块便于 junit_report/task_manager/app 三处复用与单测。
2. **新增端点 `GET /api/credentials/status`**：设计 8.4 契约未列出，为支撑 8.5 首页"凭证状态徽章"所必需；只返回就绪状态与缺失字段名，不返回任何凭证值。
3. **新增 `tests/test_redaction.py`**：设计 8.1 测试文件清单未列出，对应 17.1 的 redaction 测试要求。

除以上三点外无范围偏离：框架核心（utils/、test_cases/、data/）零改动；NameWithConditionsSearch 相关 Flow/场景/测试文件一律未触碰；阶段 1 全程未发真实请求。

## 12. 备注

- Flask 3.1.3 已在当前环境安装但尚未声明进依赖文件；按设计文档计划，阶段 2（容器化）将新增 `requirements-web.txt`；
- 独立模式启动方式：`python -m web.app`（默认 127.0.0.1:5003，环境变量 `API_AUTOTEST_*` 可配）；容器内使用 Flask 自带服务器，不引入 Gunicorn（与设计一致）。

---

# 第三部分：阶段 2 变更记录（容器化与子路径）

## 13. 提交信息

- Commit：`ee442ef`（分支 `dev`，父提交 `268bfeb`）
- 提交消息：`feat: api-autotest 新增阶段 2 容器化（Dockerfile/dockerignore/requirements-web/凭证模板）`
- 改动规模：5 个文件，+71/-1 行（4 个新增 + .gitignore 修改）

## 14. 文件清单

| # | 文件 | 类型 | 说明 |
|---|------|------|------|
| 1 | `Dockerfile` | 新增 | python:3.12-slim；框架 + Web 依赖分层安装；镜像内固化 `API_AUTOTEST_HOST=0.0.0.0`；不含 Node/Allure CLI |
| 2 | `.dockerignore` | 新增 | 排除 `.env*`、`logs/`、`reports/`、`tasks/`、`allure-results/`、`allure-report/`、`.git/`、`__pycache__/`、`.venv/`、`.pytest_cache/`、`.vscode/`、`.DS_Store`、`AGENTS.md`、`docs/`；`config/` 与 `data/` 保留在镜像内 |
| 3 | `requirements-web.txt` | 新增 | 仅 `flask>=3.0,<4.0`（【确认项 3】，框架 requirements.txt 不动） |
| 4 | `.env.platform.example` | 新增 | 平台专用凭证模板（9 个字段，【确认项 5】）；挂载为容器内 `/app/.env` 供框架读写 |
| 5 | `.gitignore` | 修改 | 追加 `!.env.platform.example` 放行模板入库（`.env.*` 会将其一并忽略） |

## 15. 验证记录（全部实测）

| # | 验证项 | 结果 |
|---|--------|------|
| 1 | 镜像构建 | `docker build` 成功（truthy-api-autotest:phase2） |
| 2 | 镜像无凭证 | 容器内 `ls /app` 无 `.env`；`docker history` 无 `.env` 相关层；构建后检查输出 `NO-ENV-IN-IMAGE` |
| 3 | 容器独立启动 | `docker run` 挂载宿主 `.env`、`data`(只读)、`logs`、`reports`、`tasks` 后 `/health` 返回 ok |
| 4 | **真实 single 执行**（阶段 2 完成标准） | 任务 `20260810-045200-14c1`：`succeeded`，JUnit 统计 `5 passed / 0 failed`，日志来源 `framework_log`（`logs/2026-08-10/20260810_045200_789125_test_9.log`，PID 关联正确） |
| 5 | BASE_PATH 全链路 | 子路径容器（`API_AUTOTEST_BASE_PATH=/api-autotest`）：`/health` 返回 404、`/api-autotest/health` ok；首页注入 `const BASE = "/api-autotest"`；catalog/凭证状态接口 200；报告元信息 `report_url=/api-autotest/reports/index.html`；静态报告 200 |
| 6 | 挂载异常凭证预检 | 挂载不存在的 `.env.platform` 路径（Docker 自动创建目录）：提交返回 400 `CREDENTIAL_FILE_INVALID`，凭证状态接口同步提示（设计 10.2 场景） |

## 16. 与设计文档 V1.2 的偏离点（审查重点）

1. **Dockerfile 固化 `ENV API_AUTOTEST_HOST=0.0.0.0`**：设计第 9 章 Dockerfile 草案无此 ENV。验证中发现容器内默认绑定 127.0.0.1 时端口映射不可达（健康检查超时），故在镜像内固化全网卡监听；本地非容器运行不受影响（该值只存在于镜像），Compose/`docker run -e` 仍可覆盖。
2. **`.dockerignore` 额外排除 `.pytest_cache/`、`.vscode/`、`.DS_Store`、`AGENTS.md`**：设计仅列出"必须排除"项；首次构建后发现上述杂物进入镜像，补充排除以减小体积并避免无关文件入库。
3. **`.gitignore` 追加 `!.env.platform.example`**：设计 15.1 要求该模板入库，而既有 `.env.*` 规则会将其忽略，需显式放行。

除以上三点外无范围偏离：框架核心与 web/ 代码零改动；Jenkins 凭证未入库；验证全程只使用宿主本地 `.env` 会话。

## 17. 备注

- 阶段 2 验证使用宿主个人 `.env` 作为容器凭证；平台模式正式接入（阶段 3）时应改用 `.env.platform`（不同测试账号，避免与本地写回冲突）；
- 真实执行期间框架如刷新会话会写回挂载的凭证文件，与本地运行行为一致；
- 独立容器启动参考命令：

```bash
docker run -d -p 127.0.0.1:5003:5003 \
  -v "$PWD/.env:/app/.env" \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/logs:/app/logs" \
  -v "$PWD/reports:/app/reports" \
  -v "$PWD/tasks:/app/tasks" \
  truthy-api-autotest:phase2
```

---

# 第四部分：阶段 3 变更记录（平台接入）

## 18. 提交信息

- Commit：`901b003`（分支 `dev`，父提交 `ee442ef`）
- 提交消息：`feat: api-autotest 新增阶段 3 平台接入（迁移/前端卡片/网关路由/Compose/冒烟）`
- 改动规模：10 个文件，+239/-11 行（1 个新增迁移 + 9 个修改），全部位于 `test-platform/`；api-autotest 仓库本阶段**零改动**

## 19. 文件清单

| # | 文件 | 类型 | 说明 |
|---|------|------|------|
| 1 | `backend/alembic/versions/20260807_0003_add_api_autotest_tool.py` | 新增 | 迁移 `20260731_0002 → 20260807_0003`：`sa.table` + `bulk_insert` 写入 api-autotest 目录记录（entry_url `/api-autotest/`、health_url `http://api-autotest:5003/api-autotest/health`、short_code API、icon_key api、category automation、features 三项、sort_order 40）；downgrade 只删本记录 |
| 2 | `backend/tests/test_migrations.py` | 修改 | ids 断言扩为 4 条；新增第四条全字段断言；`downgrade -1` 后剩 3 条 |
| 3 | `frontend/src/data/fallbackTools.ts` | 修改 | 回退目录追加第四工具（含 `fallback_health_path: /api-autotest/health`）；注释"三个"→"四个" |
| 4 | `frontend/src/components/ToolCard.tsx` | 修改 | 图标映射追加 `api: { className: "tool-icon-api", label: "AP" }`；未知 icon_key 仍回退 event |
| 5 | `web/styles.css` | 修改 | 追加 `.tool-icon-api` 配色（紫调 #5b34a8/#f1ecff，沿用既有结构；设计偏离①，见第 22 节） |
| 6 | `frontend/src/App.test.tsx` | 修改 | 既有断言 3→4（检测中/回退入口）；新增 2 用例：动态目录 AP 图标渲染、未知 icon_key 回退不报错；共 8 用例 |
| 7 | `nginx/nginx.conf` | 修改 | 追加 `location = /api-autotest`（308 补斜杠）与 `location /api-autotest/`（`set $api_autotest_upstream api-autotest:5003` + `X-Forwarded-Prefix` + 502/503/504 → tool-unavailable.html），与既有三工具块完全同构 |
| 8 | `docker-compose.yml` | 修改 | 新增 `api-autotest` 服务（build `../api-autotest`、环境变量、五组挂载、healthcheck 走 5003 子路径）；`platform-gateway.depends_on` 追加 api-autotest |
| 9 | `tests/test_smoke.py` | 修改 | `tool_ids` 断言扩为 4 条；新增用例：页面含"接口自动化"、health status=ok、catalog 含 apis/cases/flows、tasks 含 items；文档串"三个"→"四个" |
| 10 | `.env.example` | 修改 | 追加 `API_AUTOTEST_TASK_TIMEOUT_SECONDS`/`API_AUTOTEST_TASKS_RETAIN` 可选项说明 |

## 20. 验证记录（全部实测）

| # | 验证项 | 结果 |
|---|--------|------|
| 1 | 后端迁移测试 | `pytest tests/test_migrations.py`：1 passed；后端全量 6 passed |
| 2 | 前端测试 | `vitest run`：8 passed |
| 3 | Compose 语法 | `docker compose config -q` 通过 |
| 4 | 全栈启动 | `docker compose up -d --build`：migrate 日志显示 `Running upgrade 20260731_0002 -> 20260807_0003`；7 容器全部 healthy（含新增 api-autotest） |
| 5 | 第四张卡片数据源 | `GET /api/v1/tools` 返回 4 条，api-autotest entry_url `/api-autotest/`、sort_order 40；前端卡片渲染由测试项 2 覆盖 |
| 6 | 状态探测 | `GET /api/v1/tools/api-autotest/health` → `{"status": "healthy"}` |
| 7 | **执行闭环**（阶段 3 完成标准） | 经网关 `POST /api-autotest/api/tasks`（single）→ 任务 `20260810-054709-2023` → succeeded，JUnit `5 passed / 0 failed` |
| 8 | 路由细节 | `GET /api-autotest` → 308 → `/api-autotest/`；页面/catalog/tasks/health 经网关均 200 |
| 9 | 平台冒烟 | `python3 tests/test_smoke.py`：6 passed |

## 21. 验证中的问题与修正

1. **冒烟断言修正**：初版按设计 13.5 断言 catalog 返回含 `items`，实测壳服务 catalog 契约为 `{apis, cases, flows, errors}`（tasks 才是 `items`）；已按真实契约修正断言。属测试编写误差，不影响服务代码。
2. **前端断言修正**：`findByText("接口自动化")` 与页面 hero 文案重复导致多元素匹配，改为 `findByRole("heading", ...)` 精确定位卡片标题。

## 22. 与设计文档 V1.2 的偏离点（审查重点）

1. **图标配色落在 `web/styles.css` 而非设计 13.4 所述"app.css"**：`frontend/src/app.css` 首行即 `@import "../../web/styles.css"`，三个既有 `.tool-icon-*` 配色全部定义在 `web/styles.css`；为与既有样式同源，`.tool-icon-api` 追加在 `web/styles.css`（渲染效果与设计意图一致）。
2. **Compose 挂载 `.env.platform` 的前置文件由验证时创建**：设计要求平台侧使用独立凭证文件 `../api-autotest/.env.platform`，验证前该文件不存在（缺失时 Docker 会将其创建为目录导致挂载损坏）。已从用户现有 `.env` 复制生成该文件用于验证；**该文件被 gitignore，未入库**。如设计要求落地"不同测试账号"，后续替换该文件内容即可，无需改代码。

除以上两点外无范围偏离：api-autotest 框架与 web/ 壳服务零改动；NameWithConditionsSearch 相关文件未触碰；Jenkins 凭证未入库。

## 23. 备注

- `GET /api-autotest/reports/...` 当前对 JUnit XML 返回 404 属预期：该路由只服务 Allure 静态报告目录（阶段 4 报告同步链路发布后才有内容），JUnit 摘要经 `/api/tasks/<id>/result` 暴露；
- 平台容器任务列表可见阶段 2 与阶段 3 的任务记录（tasks 目录宿主挂载共享，符合设计）；
- 阶段 4 待办提醒：JOB_NAME 默认值改为 `truthy-api-autotest`、fetch 脚本走 HTTP API + 环境变量凭证（见第 5 节遗留事项 2、3）。

---

# 第五部分：阶段 4 变更记录（报告同步链路）

## 24. 提交信息

- Commit：`ce92754`（分支 `dev`，父提交 `901b003`）
- 提交消息：`feat: api-autotest 新增阶段 4 报告同步链路（原子发布/Jenkins 拉取/Jenkinsfile 归档）`
- 改动规模：5 个文件，+984/-5 行（3 个新增 + 2 个修改），全部位于 `api-autotest/`；test-platform 本阶段**零改动**

## 25. 文件清单

| # | 文件 | 类型 | 说明 |
|---|------|------|------|
| 1 | `scripts/publish_allure_report.sh` | 新增 | Allure HTML 报告原子发布：版本目录 `reports/allure-reports/<version>/` + `report-meta.json` 元信息 + `allure-current` 相对软链接经 rename(2) 原子切换；mkdir 原子锁（超龄 600s 回收）、无引用暂存目录清理（超龄 3600s）、退出码 0/2/3/4（设计 11.3） |
| 2 | `scripts/fetch_jenkins_report.sh` | 新增 | Jenkins HTTP API + Basic 认证拉取：扫描已完成构建（result 非 null，不按结果过滤）→ 校验归档含 `allure-report-publish/index.html` → 下载 zip 解压 → 带构建元信息调用发布脚本；凭证仅经环境变量；退出码 0/2/5/6（设计 12.2 + 第 5 节遗留事项 3，偏离①） |
| 3 | `tests/test_report_scripts.py` | 新增 | 17 个自测用例：发布脚本 12 个（正常发布、jenkins 元信息、缺 index/非法来源拒绝、版本切换与旧版本清理、同名重发布、遗留实体 current 迁移、锁占用/超龄回收、并发、残留暂存清理、SIGTERM 中断不破坏旧报告）+ 拉取脚本 5 个（内置假 Jenkins：无 Basic 认证返 403；覆盖跳过进行中构建、跳过无归档构建、显式构建号、无可用构建、缺凭证） |
| 4 | `Jenkinsfile` | 修改 | post 调整（设计 12.1）：保留 allure 插件发布；新增 `dir(PROJECT_DIR)` 作用域内 `allure awesome allure-results --output allure-report-publish`（catchError UNSTABLE，不掩盖 pytest FAILURE）；归档统一移入 dir 作用域并去掉 `api-autotest/` 前缀（logs、allure-results、allure-report-publish 一次归档），归档根固定为 `archive/<pattern>` |
| 5 | `README.md` | 修改 | 新增"12. 报告发布与同步"章节：`allure-current` 指针语义、手动发布命令、Jenkins 拉取命令与可选环境变量（设计 12.3） |

## 26. 关键实现要点

- **原子性**：报告先完整复制到 `reports/allure-reports/.<version>.tmp` 暂存目录并写入 meta、二次校验 `index.html` 后才 `mv` 为正式版本目录；`allure-current` 切换先建临时相对软链接再 `python3 os.replace`（rename(2)，不跟随符号链接）一步替换——切换完成前旧报告始终可用，任何时刻失败都不出现半份报告或 404（设计 11.3 禁止 .bak 两步方案）；
- **版本命名与元信息**：jenkins → `jenkins-<任务安全名>-<构建号>`，manual → `manual-<UTC时间戳>-<pid>-<random>`；`report-meta.json` 固定字段 `generated_at/source/allure_version/version`，jenkins 来源追加 `job_name/build_number(整数)/build_result/build_url`，壳服务 `GET /api/report/meta` 原样透传；
- **中断安全**：`trap cleanup EXIT` 失败时删除暂存目录与临时链接并释放锁；并发由 mkdir 原子锁互斥（拿不到锁 exit 3，不误伤旧报告）；
- **同构建重发布**：同名版本目录先挪为 `.<version>.old.tmp` 再发布，成功后清理，避免覆盖中途失败留下空版本；
- **旧构建自然跳过**：fetch 只认归档中存在 `allure-report-publish/index.html` 的构建；旧 Jenkinsfile 归档的 `allure-report.zip`（不同形态）不匹配，扫描自动跳过（第 27 节验证项 6 实测）。

## 27. 验证记录（全部实测）

| # | 验证项 | 结果 |
|---|--------|------|
| 1 | 脚本自测 | `python3 -m pytest tests/test_report_scripts.py -v`：**17 passed**（含并发双发布、SIGTERM 中断、锁超时回收） |
| 2 | 框架回归 | `python3 -m pytest -q -k "not gateway_flow and not single_gateway_api"`：`1 failed, 242 passed, 11 deselected`；242 = 阶段 1 基线 225 + 本阶段新增 17；唯一失败为用户自留用例 `test_name_with_conditions_flow_uses_non_photo_create_task_clues`（0.04s 纯断言失败、确定性复现，属 NameWithConditionsSearch 自留区预存问题，与本阶段改动无关） |
| 3 | Allure CLI 命令验证 | 本机临时安装 `allure@3.14.3`（npm）：`allure awesome allure-results --output <dir>` 真实生成含 `index.html` 的完整报告，确认设计 12.1 命令有效后移除临时安装 |
| 4 | 手动链路发布 | `scripts/publish_allure_report.sh allure-report` → 版本 `manual-20260810T064516Z-85287-17192`；`allure-current` 为相对软链接；`report-meta.json` 含 `source=manual` 四字段 |
| 5 | 页面经网关展示 | `GET /api-autotest/api/report/meta` 200（`exists=true`、`report_url=/api-autotest/reports/index.html`、版本一致）；`/api-autotest/reports/index.html` 200；子路径资源 css/字体/`summary.json`/`data/test-results/*.json` 全部 200 |
| 6 | 真实 Jenkins 连通与扫描 | fetch 脚本以环境变量凭证访问 `http://10.0.30.33:8081`：认证通过、任务 `truthy-api-autotest` 构建扫描正常；现存构建均无新归档 → 按设计返回 exit 5（"未找到包含 allure-report-publish/index.html 的已完成构建"） |

## 28. 开发中的问题与修正（均已修复并复测通过）

1. **发布锁误报**：初版 `mkdir -p` 报告根目录在获取锁之后，报告根不存在时 `mkdir` 锁目录因缺父目录失败被误判为锁冲突（exit 3）→ 目录准备前移到加锁之前；
2. **fetch URL 转义错误**：bash 双引号内 `\[` 会以字面反斜杠传给 Jenkins API → 去除 `tree=builds[...]`、`tree=artifacts[...]` 两处多余转义（阶段 0 已知的 curl globbing 问题由 `-g` 解决，与引号内转义是两回事）；
3. **自测假 Jenkins 路由**：按路径分段计数偏差导致构建详情/zip 端点误匹配 → 重写分段条件后全绿；
4. **变量边界缺陷**：`"$SELECTED_BUILD（…"` 中变量紧跟全角括号，bash 将多字节字符首字节 0xEF 并入变量名触发 `unbound variable` → 统一改为 `${SELECTED_BUILD}` 花括号形式；
5. **macOS `mv` 陷阱**：实测 `mv -f` 目标是"指向目录的符号链接"时会把源移入该目录内部而非替换 → 指针切换改用 `python3 os.replace`（rename(2)），并在自测中固化"二次发布后 current 指向新版本"断言。

## 29. 与设计文档 V1.2 的偏离点（审查重点）

1. **fetch 走 HTTP API 而非设计 12.2 字面的本地 `JENKINS_HOME` 读取**：Jenkins 为远程服务器（阶段 0 实测，本机无 JENKINS_HOME）；设计 12.2 本身留有"远端 Jenkins 必须改用 Jenkins Artifact HTTP API 并配置受控凭证"的但书，本实现即该但书路径。凭证（用户名/API 令牌）只经环境变量传入脚本，仓库任何文件均未写入。
2. **`JOB_NAME` 默认值为 `truthy-api-autotest`**：设计 12.2 示例默认值 `InterfaceAutomation` 在真实 Jenkins 上不存在（阶段 0 实测），按遗留事项 2 修正。
3. **`allure-current` 原子切换用 `python3 os.replace` 替代 shell `mv`**：macOS/BSD 的 `mv` 无法原子替换指向目录的符号链接（实测会移入目录内）；os.replace 即 rename(2)，不跟随符号链接，行为跨平台一致。设计 11.3 只要求 rename(2) 语义，未限定实现载体。
4. **手动链路验证源使用既有本地 `allure-report/`（7/31 由同批 allure-results 生成的完整 HTML 报告）**：本机无常驻 allure CLI（验证项 3 为临时安装后即移除），且发布链路验证关注的是复制/元信息/原子切换/网关展示，与报告生成时点无关。
5. **`allure_version` 元信息为 `unknown`**：发布脚本无法从 HTML 目录感知 Allure 版本，保留 `PUBLISH_ALLURE_VERSION` 环境变量注入口但两条链路均未传值；不影响页面展示与报告内容，如后续需要可在 Jenkinsfile 生成步骤旁落版本文件再透传。
6. **`JENKINS_URL` 默认值 `http://10.0.30.33:8081` 固化在 fetch 脚本中**：为用户提供的内网地址，非敏感凭证，可用环境变量覆盖。

除以上六点外无范围偏离：框架核心（utils/、test_cases/、data/）与 web/ 壳服务零改动；NameWithConditionsSearch 相关文件未触碰。

## 30. 遗留事项与备注

1. **Jenkins 端到端验证待推送后执行**：Jenkins 任务从 GitHub `origin/dev` 拉取 `api-autotest/Jenkinsfile`，本地 dev 领先 5 个提交（阶段 0–4 全部改动）。新 Jenkinsfile 生效与"成功/失败两种构建各拉取发布一次"的完成标准（设计 16 章）依赖：推送 dev → 触发（或等待）新构建 → fetch 拉取验证页面 `source=jenkins` 与构建元信息。本次会话已向用户发起确认未获答复，**未推送**；批准推送后按此顺序补齐验证并回记本台账。
2. **旧构建归档形态差异已由扫描逻辑兜底**：#14（SUCCESS）/#9（FAILURE）归档的是工作区根 `allure-report.zip`，fetch 扫描不匹配即跳过（验证项 6），无需人工清理；新 Jenkinsfile 生效后首个含 `allure-report-publish/**` 归档的构建即可被选中，同时验证阶段 0 遗留事项 4（统一 dir 作用域后的产物定位）。
3. **阶段 0 遗留事项闭环情况**：事项 2（JOB_NAME 默认值）已修正；事项 3（fetch 实现方式）已按 HTTP API + 环境变量凭证落地；事项 4（归档前缀）代码侧已按新归档形态编写，待事项 1 的真实构建最终确认；事项 1（NameWithConditionsSearch）仍由用户自留，本阶段回归基线保持 1 failed。
4. **平台侧无代码改动**：报告展示（`/api/report/meta`、`/reports/<path>`）为阶段 1 已实现契约，本阶段发布落盘后经网关直接可见（验证项 5），无需重启或重建容器。

---

# 第六部分：阶段 5 变更记录（端到端验收与文档）

## 31. 记录范围与执行依据

本部分记录 **阶段 5（端到端验收与文档）** 期间的全部改动与验收结论。执行依据：设计 V1.2 第 16 章阶段 5（行 877-883）、17.4 集成清单、第 18 章工程补充三项；PRD V1.2 第 14 章四组验收项（14.1 平台 / 14.2 任务能力 / 14.3 报告与用例库 / 14.4 隔离与回归）。

用户指令（2026-08-10）："先全部完成阶段后，最后在推送 dev 并执行 Jenkins 端到端验证。现在开始阶段 5，把阶段 5 的改动也要整理进去 review。"据此：**推送 origin/dev 与 Jenkins 端到端验证延后至全部阶段完成后统一执行**（见第 36 节遗留事项 1）。

验收过程中发现并修复了一个真实凭证脱敏盲区（第 35 节问题 1），这是本阶段唯一的框架核心代码改动。

## 32. 改动文件清单（Commit `46ed333`，5 个文件，+78/-8）

| # | 文件 | 改动类型 | 性质 | 原因 |
|---|------|---------|------|------|
| 1 | `api-autotest/utils/custom/http_client.py` | 代码修改（+2 行） | 安全修复 | `SENSITIVE_KEYS` 增加 `session_token`：Admin Gateway 审计步骤以请求体参数传递会话凭证，原集合未覆盖构成日志脱敏盲区 |
| 2 | `api-autotest/test_cases/test_framework.py` | 代码修改（+3 行） | 单测固化 | 脱敏用例 payload 增加 `params.session_token` 并断言其值不进入 caplog |
| 3 | `api-autotest/test_cases/test_allure_report.py` | 代码修改（+12/-2 行） | 守卫同步 | 两处 Jenkinsfile 守卫断言同步阶段 4 新契约：`allure awesome allure-results --output allure-report-publish` 生成命令与 `logs/**/*,allure-results/**/*,allure-report-publish/**/*` 归档 pattern |
| 4 | `api-autotest/README.md` | 文档新增（+51 行） | 阶段 5 文档项 | 新增第 13 节"Web 壳服务与平台接入"：独立/平台两种模式、任务契约、排障表、回滚步骤 |
| 5 | `test-platform/README.md` | 文档修改（+11/-3 行） | 阶段 5 文档项 | 接入工具清单更新为四个；目录树加 `api-autotest/`；路由表加 `/api-autotest/`；回退目录说明由"三个"改"四个"；新增凭证隔离说明与 api-autotest 健康探测命令 |

**明确未改动**：`data/flows/NameWithConditionsSearch.yaml`、`data/scenarios/NameWithConditionsSearch.yaml` 及对应测试（用户自留区，延续阶段 0 约定）；`runtest.py`、`web/`、`scripts/`、`Jenkinsfile` 本阶段零改动。

## 33. 关键改动说明

### 33.1 session_token 脱敏盲区（安全修复）

**发现经过**：14.2 验收中对任务 `20260810-075144-1583` 的 `/api/tasks/<id>/logs` 端点做凭证子串检测，命中 `ADMIN_SESSION_TOKEN` 原值。定位：Admin 步骤 `tool.admin.AdminService.GetProviderCostSummary` 以请求体参数 `session_token` 传递会话凭证，`http_client.py` 的 `SENSITIVE_KEYS`（access_token/auth_token/authorization/refresh_token/token）按 key 名递归脱敏，未覆盖该参数名。

**修复**：`SENSITIVE_KEYS` 追加 `"session_token"`（含注释说明来源），最小侵入、不改脱敏机制；`test_framework.py` 脱敏用例补断言固化。修复后重建容器（`docker compose up -d --build api-autotest`），复跑任务确认日志端点无 T1/T2/T3 泄漏。

**遗留清理**：修复前产生的框架日志 `logs/2026-08-10/20260810_075145_252051_test_3549.log`（任务 1583 的 log_file）含凭证原值，已删除；删除后端点降级为 `source=console_redacted`（console 兜底经 `web/redaction.py` 二次脱敏），复验无泄漏。全量扫描 `logs/`、`tasks/`、`reports/` 确认其余运行时产物无三个凭证残留。

### 33.2 守卫测试同步阶段 4 契约

阶段 4 修改 Jenkinsfile 后未即时重跑回归（会话切换疏漏），阶段 5 回归首跑暴露 `test_allure_report.py` 两个守卫用例失败：断言仍指向旧的生成命令与归档字符串。更新为阶段 4 实际契约后回归恢复。**教训：凡改被守卫文件，当轮必须重跑守卫测试。**

### 33.3 文档（设计 16 章第 4 项：README、接入说明、排障与回滚）

按设计行 73"并入平台 README 与工具 README"，未新建文档：

- 工具 README 第 13 节：独立模式启动（`requirements-web.txt` + `python -m web.app`）、平台模式（`.env.platform` 挂载隔离、data 只读、5003 仅内网）、任务契约（参数、409、退出码语义、TASK_TIMEOUT、取消、日志二次脱敏）、排障表（5 类常见现象）、回滚（平台侧 stop/downgrade、工具侧 git revert）；
- 平台 README：四工具化（清单/目录树/路由/回退目录"四个基础工具入口"）、api-autotest 凭证与文件产物说明、排障新增 `curl -i http://127.0.0.1:8080/api-autotest/health`。

## 34. 验收记录（PRD 第 14 章逐项实测）

### 34.1 14.2 任务能力验收

| # | 验收项 | 结果 |
|---|--------|------|
| 1 | 非法参数拒绝 | 6 例全部 400 `INVALID_PARAMS`：非法 run_type、single 带 flow、flow 缺 flow 名、非法 env、非法 tag 字符、路径穿越 flow=`../evil` |
| 2 | 并发控制 | 任务运行中再次提交 → 409 `SLOT_BUSY` |
| 3 | `run_type=flow` | 指定 Flow 执行成功（1 passed），统计与日志一致 |
| 4 | `tag` 筛选 | `tag=smoke` 单接口 1 passed；`tag=search`+single 返回 exit 5"未收集到任何用例"——search 标签全在 Flow 上，单接口无匹配，属诚实行为（不产生假成功），非缺陷 |
| 5 | `run_type=all` | 任务 `20260810-080933-67c7`：8 用例（single 5 + flow 3）全绿，exit 0，66s，junit 正常生成。`all` 语义对齐 Jenkinsfile：仅两个执行入口（`test_single_api.py` + `test_gateway_flow.py`），不含框架自测 |
| 6 | 取消 | 取消后 `status=cancelled`、`result_available=false`、`reason_code=JUNIT_NOT_GENERATED` |
| 7 | 超时 | `API_AUTOTEST_TASK_TIMEOUT_SECONDS=8` 临时重启验证：任务被强制终止标记 `TASK_TIMEOUT`；验证后恢复默认 1800 |
| 8 | Admin 凭证缺失 | 临时移除三个 `ADMIN_*` 字段 → 提交拒绝 400 `ADMIN_CREDENTIALS_MISSING` 并列出缺失字段；恢复后正常 |
| 9 | 凭证不落接口 | tasks/logs/report/meta/catalog/credentials/status 六端点响应做三凭证子串匹配：全部无泄漏（期间发现并修复问题 1） |

### 34.2 14.3 报告与用例库验收

| # | 验收项 | 结果 |
|---|--------|------|
| 1 | 暂无报告态 | 临时移走 `allure-current` + 重启容器后：`/api/report/meta` 返回 `{"exists":false,"report_url":null}`，`/reports/index.html` 404；恢复后 exists=true、200。单测 `tests/test_web_routes.py::test_report_missing/test_report_published` 亦覆盖 |
| 2 | 用例库一致性 | `/api/catalog` 返回 apis=14/flows=3/cases=5/errors=0，与 `data/apis`、`data/flows`、`data/cases` 磁盘文件数逐一相符 |
| 3 | 原子切换 | 阶段 4 发布脚本自测 12 用例覆盖（含并发、SIGTERM 中断、同名重发布），本阶段不重复实测 |

**环境发现（非缺陷）**：Docker Desktop for Mac 绑定挂载对宿主机 rename 存在缓存——移走 symlink 后容器内 `Path('/app/reports/allure-current').exists()` 仍为 True 而 `iterdir()` 已不见该项（幽灵残留）。重启容器刷新挂载视图后行为正确。排障时如遇"报告状态与目录实际不符"，优先 `docker compose restart api-autotest`。

### 34.3 14.1 平台与隔离验收

| # | 验收项 | 结果 |
|---|--------|------|
| 1 | 停 api-autotest | 网关返回 502 + 友好错误页（"工具暂时不可用"样式页）；平台首页 200、truthy-search 200 不受影响；`docker compose start` 恢复后 healthcheck healthy |
| 2 | 停 platform-api/db | SPA 壳 200；前端源码确认回退链路：API 加载失败 → `fallbackTools` 四工具目录（含 api-autotest：entry `/api-autotest/`、健康探测 `/api-autotest/health`）+ 提示"平台服务暂时不可用，当前显示基础工具入口"（`App.tsx` + `fallbackTools.ts`，`App.test.tsx` 有既有用例）；期间 api-autotest health 200 不受影响；恢复后 7 容器全部 healthy |
| 3 | 端口暴露面 | 仅 platform-gateway 映射 `0.0.0.0:8080->80`；api-autotest 5003、其余工具 5001/5002/8000、DB 5432 均仅 Docker 内网 expose |

### 34.4 14.4 隔离与回归验收

| # | 验收项 | 结果 |
|---|--------|------|
| 1 | 框架回归 | `-k "not gateway_flow and not single_gateway_api"`：242 passed + 1 failed（用户自留用例，阶段 0 起预存，与本阶段无关） |
| 2 | 壳服务单测 | `tests/` 125 passed |
| 3 | 平台冒烟 | `python3 -m unittest discover -s tests`：6 passed |
| 4 | 独立模式 | 安装 `requirements-web.txt`（flask 3.1.3）后 `python -m web.app` 启动于 127.0.0.1:5003：health/凭证状态/catalog/报告 meta 全绿；smoke 任务 `20260810-161939-6158` 1 passed exit 0 |
| 5 | 既有三工具抽测 | truthy-search/log-filter/trackevents 经网关 health 全部 200，platform-api 200 |
| 6 | runtest.py 行为不变 | 本阶段零改动；`--collect-only` 收集 129 例正常，参数契约（env/module/tag/flow/透传）完整 |
| 7 | 凭证刷新场景（17.4） | 构造 `EXPIRES_TIME=1` 临期态（REFRESH_EXPIRES_TIME 仍有效）→ 平台任务内自动 `RefreshSession` → `.env.platform` 写回：AUTH_TOKEN 轮换、REFRESH_TOKEN 轮换、EXPIRES_TIME 更新为未来毫秒时间戳、ADMIN_SESSION_TOKEN 不受影响；后续任务用写回凭证再次成功 |

### 34.5 设计第 18 章工程补充三项

| # | 验收项 | 结果 |
|---|--------|------|
| 1 | gitignore 覆盖 | `git check-ignore` 实证：`.env.platform`、`tasks/*`、`reports/allure-current`、`reports/allure-reports/*`、`logs/*`、`allure-results/*` 全部被忽略（项目级 `.gitignore`：`.env.*` 白名单两个 example、`reports/*` 白名单 `.gitkeep`） |
| 2 | 镜像无 .env | 以构建产物镜像起一次性容器：无 `/app/.env`（凭证仅经 bind mount 注入）；镜像内含代码与 `data/`（运行时被只读挂载覆盖），无凭证类文件 |
| 3 | Jenkins post 不掩盖 FAILURE | 结构分析：post.always 内三处 catchError——junit 失败 `buildResult: 'FAILURE'`（持平或更差）、Allure 工具与 `allure awesome` 发布失败 `buildResult: 'UNSTABLE'`（catchError 仅在当前结果更好时降级，已有 FAILURE 不会被改为 UNSTABLE）；归档在 post 内且不改变结论。测试失败结论不会被报告链路掩盖 |

## 35. 验收中发现并处理的问题

1. **session_token 脱敏盲区（真实安全缺陷，已修复）**：见 33.1。发现→最小修复→单测固化→容器重建→复测无泄漏→删除含凭证旧日志→全目录扫描清零，闭环完成。
2. **守卫测试滞后（流程疏漏，已修复）**：见 33.2。
3. **验收脚本假阳性（方法论记录）**：期间一次"console 兜底泄漏"告警系检测脚本自身缺陷——环境变量未导出导致空串子串匹配恒真。复核手法：检测前必须 `export` 并打印凭证长度，用 `grep -cF` 定点计数。最终以导出态复测为准：console.log 实际无凭证。
4. **Docker Desktop 挂载 rename 缓存（环境现象，非缺陷）**：见 34.2 备注，已写入排障经验。

## 36. 遗留事项与备注

1. **推送 dev 与 Jenkins 端到端验证（用户已定顺序）**：用户明确"先全部完成阶段后，最后再推送 dev 并执行 Jenkins 端到端验证"。当前本地 dev 领先 origin/dev 共 6 个提交（阶段 0–5：`c0ba41f`…`46ed333`）。待执行：推送 → 新 Jenkinsfile 生效 → 成功与测试失败构建各拉取发布一次 → 验证页面 `source=jenkins` 与构建元信息（阶段 4 遗留事项 1 一并闭环）。
2. **NameWithConditionsSearch 仍为用户自留**：阶段 0 起约定不变；回归基线保持 1 failed（该用例），平台 `all` 任务中该 Flow 当前可通过（真实 Gateway 语义），两处口径均为真实结论，无冲突。
3. **平台模式报告来源**：`reports/allure-current` 当前指向阶段 4 手动发布版本（`source=manual`）；`source=jenkins` 版本有待事项 1 的 Jenkins 构建产生。
4. **容器镜像已含脱敏修复**：问题 1 修复后经 `--build` 重建生效；后续如仅改框架代码，平台模式需同样重建镜像（data 只读挂载，代码固化在镜像内）。
5. **平台侧本阶段无代码改动**：test-platform 仅 README 文档更新（已随 `46ed333` 入库）；前端/后端/网关行为由阶段 3 交付，本阶段全部复验通过。PRD、设计、本台账三份文档仍为未跟踪文件，延续既有留存方式。

---

# 第七部分：推送 dev 与 Jenkins 端到端验证记录

## 37. 记录范围

按用户指令（2026-08-10）"先全部完成阶段后，最后再推送 dev 并执行 Jenkins 端到端验证"，阶段 0–5 全部完成后执行本部分。闭环设计阶段 5 验收标准"推送后验证新 Jenkinsfile 生效"与阶段 4 遗留事项 1（Jenkins 连通性）。

## 38. 推送记录

| 顺序 | 提交 | 说明 |
|------|------|------|
| 1 | `7665e6b..46ed333` | 阶段 0–5 共 6 个提交一次性推送（c0ba41f/268bfeb/ee442ef/901b003/ce92754/46ed333） |
| 2 | `d659f96` | 临时失败探针用例（test_single_api.py 追加必然失败用例，验证失败构建报告链路用） |
| 3 | `6815ef7` | revert 探针（验证完成后立即回退，dev 恢复全绿） |
| 4 | `537f15b` | fix：报告端点容忍挂载文件系统 stat 异常（见第 40 节问题 1） |
| 5 | `d071965` | docs：README 排障表补充 Docker Desktop 挂载缓存指引 |

Jenkins 任务核对：`truthy-api-autotest`，构建分支 `*/dev`，Jenkinsfile 路径 `api-autotest/Jenkinsfile`，参数 ENVIRONMENT/RUN_TYPE/FLOW——推送即生效。

## 39. Jenkins 端到端验证结果

### 39.1 失败构建（#15，RUN_TYPE=single，含探针）

| 验收项 | 结果 |
|--------|------|
| 构建结果 | FAILURE（探针 `test_jenkins_failure_build_probe` 必然失败） |
| 测试统计 | fail=1 / pass=5 / skip=0，junit 记录正确 |
| post 不掩盖 FAILURE | 结果保持 FAILURE；post.always 仍执行，`allure awesome` 生成并归档 `allure-report-publish/**` 共 77 个文件 |
| 拉取发布 | `BUILD_NUMBER=15 scripts/fetch_jenkins_report.sh` exit 0，版本 `jenkins-truthy-api-autotest-15`，source=jenkins |
| 页面展示 | meta：source=jenkins / build_number=15 / build_result=FAILURE / build_url 正确；报告页 200，饼图 failed=1 统计可见 |
| 旧版本清理 | 发布 #15 时自动删除阶段 4 的 manual 版本 |

### 39.2 成功构建（#16，RUN_TYPE=all，revert 后）

| 验收项 | 结果 |
|--------|------|
| 构建结果 | SUCCESS |
| 测试统计 | 5 passed / 3 skipped：3 个 Flow 用例因 Jenkins agent 的 `.env` 无 `ADMIN_*` 凭证被 skip_if 跳过（agent 环境既有差异，非回归；平台容器 `.env.platform` 有完整凭证故平台任务 8/8） |
| 报告归档 | `allure-report-publish/**` 79 个文件 |
| 拉取发布 | `BUILD_NUMBER=16` 拉取发布成功，版本 `jenkins-truthy-api-autotest-16`；发布时自动清理 #15 版本 |
| 页面展示 | meta：source=jenkins / build_number=16 / build_result=SUCCESS；报告页 200 |

### 39.3 结论

- 新 Jenkinsfile 生效：pytest 直驱入口文件 + junit + allure-results + post 生成发布 + 统一归档，失败/成功两态均验证；
- 报告同步链路真实 Jenkins 闭环：构建 → 归档 → fetch 脚本拉取 → 原子发布 → 网关展示 `source=jenkins` 与构建元信息；
- fetch 脚本凭证契约实测为 `JENKINS_USER` + `JENKINS_TOKEN`（README 第 12 节已一致）。

## 40. 端到端期间发现并处理的问题

1. **报告端点 500（OSError EINVAL，已修复 `537f15b`）**：发布 #16 后 meta/报告页 500。容器日志：`Path('/app/reports/allure-current').exists()` 抛 `OSError: [Errno 22] Invalid argument`——Docker Desktop for Mac 绑定挂载在宿主机 os.replace 原子切换 symlink 并删除旧版本目录后，容器内残留句柄使 stat 返回 EINVAL（Python 3.12 `Path.exists()` 仅吞 ENOENT 类错误）。修复：`_resolve_report_dir` 对 exists/resolve 的 OSError 按"暂无报告"降级；新增单测 `test_report_stat_oserror_degrades_to_missing`（壳服务测试 126 passed）；容器已重建生效。运维指引（重启刷新挂载视图）已写入 README 排障表。
2. **curl glob 干扰（验证手法记录）**：URL 中 `tree=...[...]` 方括号被 curl 当 glob 导致空响应，须加 `-g`/`--globoff`；fetch 脚本内部调用已验证不受影响。
3. **Jenkins 触发认证（验证手法记录）**：buildWithParameters 直接 POST 返回 403，需先取 CSRF crumb（`/crumbIssuer/api/json`）并携带 `Jenkins-Crumb` 头与会话 cookie。
4. **归档查询时序**：构建刚结束时 artifacts API 可能尚未就绪（#16 首查 0 个，片刻后 79 个）；拉取前确认构建完全结束即可。

## 41. 最终状态

- **dev 分支**：与 origin/dev 同步，全绿（探针已 revert）；
- **平台**：7 容器 healthy；报告区展示 Jenkins 构建 #16（SUCCESS，source=jenkins）；
- **Jenkins**：#15（FAILURE）/#16（SUCCESS）两次构建完整验证新 Jenkinsfile 与报告链路；
- **遗留清零**：阶段 4 遗留事项 1、阶段 5 遗留事项 1 均已闭环；NameWithConditionsSearch 维持用户自留约定；
- **已知环境差异**：Jenkins agent 无 ADMIN 凭证 → Flow 用例在 CI 为 skipped（如需 CI 全量 Flow，需为 agent 配置 ADMIN_* 凭证，由用户决定）。
