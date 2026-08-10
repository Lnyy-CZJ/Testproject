# Gateway API Automation V1.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在现有 Gateway 自动化框架中增加文件日志和通用 Flow/Scenario YAML 执行能力。

**Architecture:** 保留现有 GatewayApi、RuntimeContext、case YAML 与 pytest 入口。logger/http_client 负责可追溯文件日志；FlowLoader 负责配对与配置校验；FlowRunner 负责独立上下文、步骤调度、参数覆盖、断言、提取、等待、轮询及现有 COS PUT。

**Tech Stack:** Python 3.10+、pytest、requests、PyYAML、logging 标准库

---

### Task 1: 文件日志

**Files:**
- Modify: `utils/custom/logger.py`
- Modify: `utils/custom/http_client.py`
- Modify: `config/settings.yaml`
- Modify: `test_cases/conftest.py`
- Test: `test_cases/test_v12.py`

- [x] **Step 1: 编写失败测试**

```python
def test_configure_logging_creates_one_utf8_file(tmp_path):
    path = configure_logging(log_directory=tmp_path, env="test", console=False)
    get_logger("v12").info("中文日志")
    assert path and "中文日志" in path.read_text(encoding="utf-8")

def test_http_client_logs_elapsed_time(caplog):
    HttpClient(session=SuccessfulSession()).post_json("http://example", {}, {}, 1)
    assert "elapsed_ms" in caplog.text
```

- [x] **Step 2: 确认 RED**

Run: `python3 -m pytest test_cases/test_v12.py -q`

Expected: FAIL，logger 尚不接受日志目录，HTTP 日志尚无耗时。

- [x] **Step 3: 最小实现**

`configure_logging` 幂等添加终端和 UTF-8 FileHandler，返回日志路径；HttpClient 使用 `perf_counter` 记录 POST/PUT 耗时；pytest_configure 根据 settings 初始化一次。

- [x] **Step 4: 确认 GREEN**

Run: `python3 -m pytest test_cases/test_v12.py -q`

Expected: PASS。

### Task 2: 断言扩展和 Flow 配对加载

**Files:**
- Create: `utils/custom/flow_loader.py`
- Modify: `utils/custom/assertions.py`
- Modify: `utils/custom/runtime_context.py`
- Test: `test_cases/test_v12.py`

- [x] **Step 1: 编写失败测试**

```python
def test_data_fields_accepts_empty_values(): ...
def test_data_equals_reads_nested_paths(): ...
def test_flow_loader_pairs_same_name_files(tmp_path): ...
def test_flow_loader_rejects_duplicate_step_ids(tmp_path): ...
def test_flow_loader_rejects_unknown_scenario_step(tmp_path): ...
```

- [x] **Step 2: 确认 RED**

Run: `python3 -m pytest test_cases/test_v12.py -q`

Expected: FAIL，FlowLoader 和 data_equals 尚不存在。

- [x] **Step 3: 最小实现**

新增 `FlowConfigError` 与 `load_flow_cases(project_root, selected_flow=None)`；公开受控路径读取；data_fields 仅检查存在，新增 data_equals 相等断言。

- [x] **Step 4: 确认 GREEN**

Run: `python3 -m pytest test_cases/test_v12.py -q`

Expected: PASS。

### Task 3: 通用 FlowRunner

**Files:**
- Create: `utils/custom/flow_runner.py`
- Test: `test_cases/test_v12.py`

- [x] **Step 1: 编写失败测试**

```python
def test_flow_runner_merges_scenario_params_and_extracts_value(tmp_path): ...
def test_flow_runner_keeps_contexts_isolated(tmp_path): ...
def test_flow_runner_executes_fixed_wait_without_real_sleep(tmp_path): ...
def test_flow_runner_polls_until_value_matches(tmp_path): ...
def test_flow_runner_reports_poll_timeout(tmp_path): ...
```

- [x] **Step 2: 确认 RED**

Run: `python3 -m pytest test_cases/test_v12.py -q`

Expected: FAIL，FlowRunner 尚不存在。

- [x] **Step 3: 最小实现**

FlowRunner 为每次 run 创建 RuntimeContext；支持 call、wait、call+until、prepared_media_upload；参数递归覆盖、默认/场景断言和提取按设计顺序执行；时钟和 sleep 可注入。

- [x] **Step 4: 确认 GREEN**

Run: `python3 -m pytest test_cases/test_v12.py -q`

Expected: PASS。

### Task 4: pytest 与 CLI 接入

**Files:**
- Modify: `test_cases/conftest.py`
- Modify: `test_cases/test_gateway_flow.py`
- Modify: `runtest.py`
- Test: `test_cases/test_v12.py`
- Test: `test_cases/test_framework.py`

- [x] **Step 1: 编写失败测试**

```python
def test_build_pytest_args_supports_flow_filter():
    assert "--flow=Demo" in build_pytest_args("test", flow="Demo")
```

- [x] **Step 2: 确认 RED**

Run: `python3 -m pytest test_cases/test_framework.py test_cases/test_v12.py -q`

Expected: FAIL，入口尚无 flow 参数。

- [x] **Step 3: 最小实现**

注册 `--flow`；test_gateway_flow 使用 pytest_generate_tests 加载配对文件；删除固定路径和写死步骤；runtest 透传筛选参数。

- [x] **Step 4: 确认 GREEN**

Run: `python3 -m pytest test_cases/test_framework.py test_cases/test_v12.py -q`

Expected: PASS。

### Task 5: 示例迁移、文档和完成验证

**Files:**
- Rename: `data/flows/anonymous_session_media_search.yaml` -> `data/flows/AnonymousSessionMediaSearch.yaml`
- Create: `data/scenarios/AnonymousSessionMediaSearch.yaml`
- Modify: `README.md`
- Modify: `.gitignore`

- [x] **Step 1: 迁移示例**

Flow 只保存编排、提取和等待；Scenario 保存 MEDIA_FILE、CreateIntentTask 参数及场景断言。

- [x] **Step 2: 更新说明**

README 增加日志位置、Flow/Scenario 配对、新增流程方法和 `--flow` 命令；`.gitignore` 忽略 `logs/*`。

- [x] **Step 3: 全量验证**

Run: `python3 -m pytest -q`

Expected: 全部单元测试 PASS；缺少真实媒体文件时真实流程 SKIP。

Run: `python3 -m compileall -q api utils test_cases runtest.py`

Expected: exit code 0。

Run: `python3 runtest.py --help`

Expected: 显示 `--flow`。

- [x] **Step 4: 安全检查**

确认日志测试中 token、refresh token 和签名 URL 查询参数均未出现在文件内容；Flow 配置错误发生在网络调用前。
