# Gateway API Automation MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 搭建一个由 YAML 驱动、可通过 `runtest.py` 执行的 Gateway 单接口自动化测试框架。

**Architecture:** `config` 和 `data` 保存环境、接口、用例与断言数据；`api` 只构造 Gateway 信封；`utils/custom` 负责配置、HTTP、日志和断言；`test_cases` 使用 pytest 组织框架单元测试与真实接口用例。敏感值只从环境变量读取。

**Tech Stack:** Python 3.10+、pytest、requests、PyYAML

---

### Task 1: 框架核心行为测试

**Files:**
- Create: `test_cases/test_framework.py`
- Test: `test_cases/test_framework.py`

- [x] **Step 1: 编写失败测试**

覆盖以下公开行为：

```python
def test_load_settings_merges_environment_and_secrets(...): ...
def test_build_payload_creates_single_gateway_request(...): ...
def test_assert_gateway_response_accepts_success(...): ...
def test_assert_gateway_response_reports_business_failure(...): ...
def test_http_client_masks_auth_token_in_error_log(...): ...
def test_build_pytest_args_supports_filters(...): ...
```

- [x] **Step 2: 确认 RED**

Run: `python3 -m pytest test_cases/test_framework.py -q`

Expected: FAIL，原因是 `api`、`utils` 或 `runtest` 模块尚不存在。

### Task 2: 配置、接口与用例 YAML

**Files:**
- Create: `config/settings.yaml`
- Create: `config/env/test.yaml`
- Create: `data/api/gateway_invoke.yaml`
- Create: `data/cases/get_me.yaml`
- Create: `.env.example`
- Create: `requirements.txt`

- [x] **Step 1: 写入最小配置**

`settings.yaml` 保存超时和 `comm` 默认值；`test.yaml` 保存环境地址；接口 YAML 保存 `POST /gateway/invoke`；用例 YAML 保存 `GetMe` 路由、标签和断言。

- [x] **Step 2: 保持数据边界**

真实 `AUTH_TOKEN`、`USER_ID`、`DEVICE_ID` 不出现在 YAML，仅在 `.env.example` 声明变量名。

### Task 3: 最小 Python 实现

**Files:**
- Create: `api/__init__.py`
- Create: `api/gateway_api.py`
- Create: `utils/__init__.py`
- Create: `utils/custom/__init__.py`
- Create: `utils/custom/config_loader.py`
- Create: `utils/custom/http_client.py`
- Create: `utils/custom/assertions.py`
- Create: `utils/custom/logger.py`
- Create: `runtest.py`

- [x] **Step 1: 实现配置加载**

```python
def load_settings(env: str, project_root: Path | None = None) -> dict:
    """合并默认配置、环境配置与三个敏感环境变量。"""
```

- [x] **Step 2: 实现 Gateway 请求构造**

```python
def build_payload(settings: dict, case: dict) -> dict:
    """构造只包含一个 `req_0` 子请求的 `comm + requests` 信封。"""
```

- [x] **Step 3: 实现 HTTP 与脱敏日志**

```python
class HttpClient:
    def post_json(self, url: str, headers: dict, payload: dict, timeout: float): ...
```

- [x] **Step 4: 实现通用断言**

```python
def assert_gateway_response(response, expected: dict) -> dict:
    """校验 HTTP、Gateway 顶层、指定子响应和 data_fields。"""
```

- [x] **Step 5: 实现统一入口**

`runtest.py` 支持 `--env`、`--module`、`--tag` 和 `--` 后的 pytest 透传参数。

- [x] **Step 6: 确认 GREEN**

Run: `python3 -m pytest test_cases/test_framework.py -q`

Expected: 全部 PASS。

### Task 4: 真实 YAML 用例与使用说明

**Files:**
- Create: `test_cases/conftest.py`
- Create: `test_cases/test_single_api.py`
- Create: `README.md`

- [x] **Step 1: 编写真实接口测试**

从 `data/cases/*.yaml` 参数化加载；未提供敏感环境变量时明确 `skip`，提供后调用真实 Gateway。

- [x] **Step 2: 编写中文使用说明**

说明依赖安装、环境变量、三类执行命令、数据职责和新增单接口方法。

- [x] **Step 3: 创建预留目录**

创建 `data/global`、`data/flows`、`data/scenarios`、`data/assertions`、`reports`、`utils/third_party`，不添加未要求的功能实现。

### Task 5: 完成前验证

**Files:**
- Verify: 全项目

- [x] **Step 1: 运行全部测试**

Run: `python3 -m pytest -q`

Expected: 框架单元测试 PASS；缺少真实凭证时真实接口用例 SKIP。

- [x] **Step 2: 验证统一入口**

Run: `python3 runtest.py --help`

Expected: 显示 `--env`、`--module`、`--tag` 参数。

- [x] **Step 3: 验证语法**

Run: `python3 -m compileall -q api utils test_cases runtest.py`

Expected: exit code 0。

- [x] **Step 4: 对照约束自检**

确认目录与设计一致、Python 代码含中文功能/参数/返回值/异常注释、日志不泄露 token、没有实现 Flow/Allure/CI 等非 MVP 功能。
