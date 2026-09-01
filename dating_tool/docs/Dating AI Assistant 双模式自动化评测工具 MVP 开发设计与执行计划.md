# Dating AI Assistant 双模式自动化评测工具 MVP 开发设计与执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

| 项目 | 内容 |
|---|---|
| 计划版本 | V0.3.0 |
| 对应 PRD | V0.3.0（双流程轻量 MVP） |
| 更新日期 | 2026-08-27 |
| 当前状态 | 可进入编码；Public Reply 真实验收受 staging 外部依赖阻塞 |

**Goal:** 构建一个独立 Python CLI，同时支持 Reply / Analysis 的“完整 E2E 小规模验证”和“快速批量评测”两条流程；MVP 只执行链路、验证接口与确定性规则、保存最小排障产物，不建设 AI Judge、内容质量评分、正式报告、自动发布、门禁或 CI。

**Architecture:** 使用一个轻量 `CaseRunner` 协调两个 Adapter。`PublicE2EAdapter` 负责匿名会话、Reply Preferences、私密截图上传、Reply / Analysis Task、Result 和 Delete；`InternalEvaluationAdapter` 负责结构化 `dating.transcript.v1` 的 Reply / Analysis Evaluation Task、Result、Diagnostics 和 Delete。两者共用 Case/Task 领域模型、HTTP 基础设施、状态记录、脱敏和清理规则，但不强行统一两套 Wire Schema。

**Tech Stack:** Python 3.12、标准库 `argparse/dataclasses/json/pathlib/concurrent.futures/threading/unittest`、`requests>=2.34.2,<3`、`python-dotenv>=1.2.3,<2`、`Pillow>=12.3,<13`、setuptools。

依赖下限于 2026-08-27 按官方 PyPI 当前版本核对，不引入额外包管理器：[Requests](https://pypi.org/project/requests/)、[python-dotenv](https://pypi.org/project/python-dotenv/)、[Pillow](https://pypi.org/project/pillow/)。

**Spec:** `docs/Dating AI Assistant 双模式自动化评测工具 MVP PRD.md`

**Runtime Contract:** `/Users/admin/人际关系项目/dating assitsatant/测试设计/Dating 当前可测试接口文档（staging）.md`（公开 staging 现状）与后端 2026-08-27 内部 Evaluation 部署说明。

**Design Basis:** 《Dating AI Assistant 双模式自动化评测工具开发与项目框架设计》中的独立工程、CLI、Ports/Adapters、Case 与 Wire Schema 分离思路；Judge、Normalizer、Baseline、Reporter、Replay/Mock 产品能力按 V0.3.0 PRD 从 MVP 删除，仅保留测试用 Fake。

Truthy_Search 只参考其 JSONL 输入、命令行批处理、Fixture 测试和产物隔离经验；不直接依赖
其 `web_app/analysis_store/Excel/报告/基线` 代码，避免把旧工具的重量带入本 MVP。

## 全局约束

- 项目根目录固定为 `/Users/admin/Testproject/dating_tool`，工具不放入 Go 后端仓库。
- Public E2E 按 V0.3.0 PRD 实现 Reply + Analysis；根据 2026-08-26 staging 现状，当前只能真实验收 Analysis，Reply 的 Preferences、Task 与 Result 属于环境阻塞，不得用 Mock 冒充真实通过。
- Internal Evaluation 按后端 2026-08-27 部署说明实现 Reply + Analysis，并各自完成 Create、Task、Result、Diagnostics、Delete 闭环。
- 公开 Gateway 固定为 `https://gateway.spark-jam.top/dating/gateway/invoke`，健康检查为 `https://gateway.spark-jam.top/healthz`。
- 公开 Analysis 使用 staging 真实方法名 `GetAnalysisTask` 和 `GetAnalysisResult`；Reply 暂按公开协议的 `GetTask` / `GetTaskResult` 封装，但在真实联调前必须由后端冻结 Reply 当前方法名。
- 内部 Evaluation 固定服务名为 `tool.dating.internal.DatingEvaluationService`，临时 HTTP 只允许已确认的 staging CLB 精确主机。
- E2E MVP 固定串行；内部 Evaluation 默认并发 3、最大 5。
- Eval 创建平均不快于每 2 秒 1 个；所有 Admin Gateway 请求合计不超过 120 次/分钟。
- E2E 轮询前 10 秒每秒一次，之后每 2 秒一次，等待上限 90 秒。
- Eval 每 3 秒轮询一次，等待上限 240 秒。
- API Key、Access Token、Refresh Token、Authorization Header、图片二进制、COS 签名 URL、聊天正文和生成正文不得进入控制台日志。
- `artifacts/` 不进入 Git；目录权限 `0700`，敏感文件权限 `0600`。
- MVP 不编辑、生成或自动脱敏测试截图；只读取已人工脱敏 Fixture，校验格式/大小/元数据后原样上传。
- 不实现 AI Judge、内容质量评分、HTML/JUnit 等正式报告、自动发布、门禁、CI、基线、Web UI、SQLite 或任意步骤断点恢复。
- 所有新增或修改的业务代码使用清晰中文注释，说明职责、参数、返回值、错误行为和非显而易见的安全选择。

---

## 1. 契约口径与范围决议

### 1.1 信息源优先级

| 范围 | 权威信息源 | 计划采用的结论 |
|---|---|---|
| 公开客户端 staging | `Dating 当前可测试接口文档（staging）.md` | Identity、Media、Analysis、Quota 当前可测；Preferences/Reply 当前不可测 |
| 内部结构化评测 | 后端 2026-08-27 部署说明 | `InternalEvaluationAdapter` 实现已部署的 Reply + Analysis Evaluation |
| 产品范围 | V0.3.0 PRD + 用户本轮确认 | MVP 保留完整 E2E 与快速批量评测两条流程，排除质量平台能力 |

staging 文档中的“自动化 Evaluation API 尚未实现”是 2026-08-26 的旧状态；内部接口以 2026-08-27 后端部署说明为准。`doctor --mode eval` 仍需通过真实鉴权探测再次确认；若返回 `FEATURE_NOT_READY`，快速评测标记为环境阻塞，禁止退化成 Mock 后宣称联通。

### 1.2 开发交付边界与当前可验收边界

本计划最终交付的两条真实流程是：

```text
流程 A1：公开 Reply 完整 E2E（代码与 Fake Contract 纳入 MVP；真实 staging 当前阻塞）
CreateAnonymousSession
→ GetMe
→ GetUserPreferences / UpdateUserPreferences
→ GetMediaUploadConfig
→ PrepareMediaUpload
→ COS PUT
→ CompleteMediaUpload
→ CreateReplyTask
→ GetTask（当前 Reply 方法名待后端冻结）
→ GetTaskResult（当前 Reply 方法名待后端冻结）
→ DeleteTaskData
→ 验证 Task / Result 不可访问
```

```text
流程 A2：公开 Analysis 完整 E2E（当前 staging 可真实验收）
CreateAnonymousSession
→ GetMe
→ GetMediaUploadConfig
→ PrepareMediaUpload
→ COS PUT
→ CompleteMediaUpload
→ GetQuotaStatus
→ CreateAnalysisTask
→ GetAnalysisTask
→ GetAnalysisResult
→ DeleteTaskData
→ 验证 Task / Result 不可访问
```

```text
流程 B：内部 Reply / Analysis 快速批量评测（当前 staging 可真实验收）
dating.transcript.v1 JSONL
→ Create{Reply|Analysis}EvaluationTask
→ Get{Reply|Analysis}EvaluationTask
→ Get{Reply|Analysis}EvaluationResult
→ GetEvaluationDiagnostics
→ Delete{Reply|Analysis}EvaluationTaskData
```

`PublicE2EAdapter` 必须保持 `Identity → Preferences（仅 Reply）→ Media → Task → Result → Delete`。实现阶段用 Fixture/Fake Gateway 验证 Reply 的字段和顺序；真实 staging 执行时，`doctor`/预检若发现 Preferences 或 Reply 未开放，应返回 `FEATURE_NOT_READY`/环境阻塞，并且不上传媒体、不创建 Task。Analysis 不调用 Preferences。

依据最新 staging 文档，第 5.11 节外部依赖更新为：

| 依赖 | 当前状态 | 对计划的影响 |
|---|---|---|
| 公开 Gateway 与 Health URL | 已提供、Health HTTP 200 | Analysis E2E 可联调 |
| Anonymous Session / Refresh / GetMe | 已开放 | 身份阶段可联调 |
| Media 配置、签名上传和 Complete | 已开放 | 上传阶段可联调；以动态配置为准 |
| Analysis Task / Result / Delete / Quota | 已开放 | 使用当前真实 Analysis 方法名 |
| Preferences 与 Help Me Reply | 尚未交付 | Reply E2E 可开发、不可形成真实通过结论 |
| `dating_goal` / `your_voice` 稳定 code | 尚未交付 | Reply Fixture 暂用 PRD 示例，联调前替换为后端冻结值 |
| 公开接口限流 | 未完整说明 | E2E 固定串行，不推测容量 |
| CreateTask 前孤立 Asset 清理 | 未提供独立接口 | 记录安全的 `asset_id`，依赖 Asset TTL，并保留风险项 |
| 匿名测试身份清理/TTL | 当前文档未说明 | 每个 Run 仅建一个 Session，记录为后端待确认的数据生命周期问题 |

### 1.3 不在本计划中的能力

- Practice Mode、Person、历史记录和订阅购买；
- `ReportAcquisitionChannel`；
- `aura-cue.com` staging 域名；
- 任何生产环境连接能力。

---

## 2. 设计方案

### 2.1 最终目录

```text
dating_tool/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── datasets/
│   ├── e2e-smoke/
│   │   ├── analysis-single.json
│   │   └── analysis-multi.json
│   ├── eval-smoke.jsonl
│   └── media/
│       └── README.md
├── src/
│   └── aidating_eval/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── errors.py
│       ├── domain.py
│       ├── cases.py
│       ├── redaction.py
│       ├── artifacts.py
│       ├── http.py
│       ├── public_gateway.py
│       ├── evaluation_gateway.py
│       ├── ports.py
│       ├── runner.py
│       ├── scheduling.py
│       ├── media_validation.py
│       └── adapters/
│           ├── __init__.py
│           ├── public_e2e.py
│           └── internal_evaluation.py
├── tests/
│   ├── __init__.py
│   ├── helpers.py
│   ├── fixtures/
│   │   ├── public/
│   │   └── evaluation/
│   ├── unit/
│   │   └── __init__.py
│   ├── integration/
│   │   └── __init__.py
│   └── staging/
│       ├── __init__.py
│       ├── test_public_analysis_smoke.py
│       └── test_internal_analysis_smoke.py
├── artifacts/
│   └── .gitkeep
└── docs/
    ├── Dating AI Assistant 双模式自动化评测工具 MVP PRD.md
    ├── Dating AI Assistant 双模式自动化评测工具 MVP 开发设计与执行计划.md
    └── 默认模块.openapi.json
```

### 2.2 组件职责

| 文件 | 单一职责 |
|---|---|
| `config.py` | 从环境变量加载两种模式配置，并执行环境/HTTP 安全校验 |
| `domain.py` | 定义 Case、Task、PollPolicy、Outcome 和 Cleanup 等稳定领域类型 |
| `cases.py` | 读取 E2E JSON 与 Eval JSONL，执行模式专属本地校验 |
| `redaction.py` | 递归脱敏 Secret、Token、签名 URL 和正文类字段 |
| `artifacts.py` | 以安全权限写入 manifest、事件和每案例原始结果 |
| `http.py` | 提供不带业务重试的 HTTP Transport，确保日志不泄密 |
| `public_gateway.py` | 构造公开 `comm/execution/requests` 信封并解析 `responses[0]` |
| `evaluation_gateway.py` | 构造内部 Admin 请求并解析 `responses[0]` |
| `ports.py` | 定义 Runner 依赖的最小 `TaskFlowAdapter` Protocol |
| `runner.py` | 执行单案例 create/poll/result/diagnostics/finally-delete 状态机 |
| `scheduling.py` | 管理 Eval 创建节奏、Gateway 总速率和最多 5 个并发 Worker |
| `media_validation.py` | 只读校验已脱敏图片的真实格式、大小和敏感元数据，不编辑源文件 |
| `public_e2e.py` | 串联公开身份、Reply Preferences、Media、Reply/Analysis Task、Result 和 Delete |
| `internal_evaluation.py` | 串联结构化 Reply / Analysis Evaluation 的独立方法闭环 |
| `cli.py` | 暴露 `doctor/validate/run/cleanup`，不包含业务请求拼装 |

### 2.3 核心领域接口

`ports.py` 最终接口固定为：

```python
from collections.abc import Mapping
from typing import Any, Protocol

from aidating_eval.domain import (
    CaseDefinition,
    CleanupResult,
    DoctorCheck,
    PollPolicy,
    PreparedCase,
    RunContext,
    TaskSnapshot,
)


class TaskFlowAdapter(Protocol):
    """Runner 调用的最小任务执行端口。"""

    @property
    def poll_policy(self) -> PollPolicy: ...

    def doctor(self) -> list[DoctorCheck]: ...

    def prepare_run(self, context: RunContext) -> None: ...

    def prepare_case(
        self, case: CaseDefinition, context: RunContext
    ) -> PreparedCase: ...

    def create_task(
        self, case: CaseDefinition, prepared: PreparedCase, context: RunContext
    ) -> TaskSnapshot: ...

    def get_task(self, task_id: str, context: RunContext) -> TaskSnapshot: ...

    def get_result(
        self, task_id: str, case: CaseDefinition, context: RunContext
    ) -> Mapping[str, Any]: ...

    def get_diagnostics(
        self, task_id: str, case: CaseDefinition, context: RunContext
    ) -> Mapping[str, Any] | None: ...

    def delete_task(self, task_id: str, context: RunContext) -> CleanupResult: ...
```

### 2.4 Runner 状态机

```text
validate
  ↓
prepare_run（每个 Run 一次）
  ↓
prepare_case
  ↓
create_task ──失败且无 task_id──→ failed
  ↓ task_id
poll queued/processing
  ├── succeeded → result → diagnostics(optional)
  ├── rejected  → diagnostics(optional)
  ├── failed    → diagnostics(optional)
  └── timeout   → incomplete
  ↓
finally delete_task
  ├── success → completed/failed/incomplete
  └── failure → cleanup_pending
```

Runner 只判断终态和时序，不解释业务正文。`phase` 保存但不参与状态分支。

### 2.5 Secret 与数据生命周期

- `Settings.eval_api_key`、`SessionTokens.access_token`、`SessionTokens.refresh_token` 使用 `field(repr=False)`；
- `redact_mapping()` 对 Key 名和 URL 值双重脱敏；
- Public Token 只在 E2E 进程内存中存在；因此 `cleanup --run` 的跨进程重试首期只支持 Internal Evaluation；
- Public E2E 依靠 `finally`、SIGINT/SIGTERM 的优雅停止和服务端 TTL 兜底；硬杀进程后无法在不持久化 Token 的前提下恢复原用户清理权限；
- 该限制必须在 README 和 CLI 提示中明确，不通过明文落盘 Token 规避；
- Eval API Key 只从环境变量读取；
- `result.json` 允许在本地安全目录保存完整服务端结果，控制台只输出元数据；
- MVP 不自动删除本地 Artifact；README 明确其可能包含对话衍生正文，由执行者在排障结束后
  手工删除整个精确 `artifacts/<run_id>` 目录；`cleanup` 命令只处理远端 Task，不删除本地证据；
- Public E2E 删除后验证 Task/Result 返回 `NOT_FOUND`；Eval 普通案例以 Delete 成功为清理完成，专门契约案例再验证 `NOT_FOUND`。

MVP 产物固定为排障文件，不生成聚合报告：

```text
artifacts/<run_id>/
├── manifest.json
├── run-state.jsonl
└── cases/<case_id>/
    ├── metadata.json
    ├── quota.json          # 仅 Public Analysis，有查询时
    ├── task.json
    ├── result.json         # 仅取得 Result 时
    ├── diagnostics.json    # 仅 Internal 且有数据时
    ├── cleanup.json
    └── error.json          # 仅失败或命中预期业务错误时
```

### 2.6 测试分层

| 层级 | 是否默认运行 | 内容 |
|---|---|---|
| Unit | 是 | 配置、校验、脱敏、字节计算、状态机、限流和图片处理 |
| Contract | 是 | 使用脱敏 Fixture 校验请求信封、方法名、响应和错误解析 |
| Integration Fake | 是 | 用 Fake Transport 完整跑通两种 Adapter 与 Runner |
| Staging Smoke | 否，显式环境变量开启 | Public Analysis 1 条；Internal Reply/Analysis 各 1 条；Public Reply 保留阻塞检查 |

默认测试命令：

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

staging 测试不会被默认发现后自动执行真实请求；测试文件必须同时检查 `AIDATING_RUN_STAGING_TESTS=1`。

---

## Task 1: 工程骨架、依赖与安全默认值

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/aidating_eval/__init__.py`
- Create: `src/aidating_eval/errors.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `artifacts/.gitkeep`
- Create: `datasets/media/README.md`
- Create: `tests/unit/test_project_contract.py`
- Create: `README.md`

**Interfaces:**
- Produces: 可安装包 `aidating-eval`、版本常量 `__version__`、公共异常类型。
- Consumes: 无。

- [ ] **Step 1: 写工程约束失败测试**

```python
# tests/unit/test_project_contract.py
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProjectContractTests(unittest.TestCase):
    def test_artifacts_and_env_are_git_ignored(self):
        rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("artifacts/*", rules)
        self.assertIn(".env", rules)

    def test_example_env_never_contains_real_key(self):
        content = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertNotIn("adm_key_", content)
        self.assertIn("AIDATING_EVAL_API_KEY=", content)

    def test_package_version_is_importable(self):
        from aidating_eval import __version__

        self.assertRegex(__version__, r"^0\.3\.\d+$")
```

- [ ] **Step 2: 运行测试并确认工程文件尚不存在**

Run:

```bash
python -m unittest tests.unit.test_project_contract -v
```

Expected: FAIL，原因是 `.gitignore`、`.env.example` 或包尚未创建。

- [ ] **Step 3: 创建最小可安装工程**

`pyproject.toml` 使用以下固定配置：

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "aidating-eval"
version = "0.3.0"
requires-python = ">=3.12"
dependencies = [
  "requests>=2.34.2,<3",
  "python-dotenv>=1.2.3,<2",
  "Pillow>=12.3,<13",
]

[project.scripts]
dating-eval = "aidating_eval.cli:main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
```

`.gitignore` 至少包含：

```gitignore
.env
.env.*
!.env.example
.venv/
__pycache__/
*.py[cod]
artifacts/*
!artifacts/.gitkeep
datasets/media/*
!datasets/media/README.md
```

`.env.example` 只写变量名：

```dotenv
AIDATING_PUBLIC_GATEWAY_URL=https://gateway.spark-jam.top/dating/gateway/invoke
AIDATING_PUBLIC_HEALTH_URL=https://gateway.spark-jam.top/healthz
AIDATING_E2E_DEVICE_ID=
AIDATING_E2E_PLATFORM=ios
AIDATING_E2E_APP_VERSION=1.0.0
AIDATING_E2E_LOCALE=en-US
AIDATING_E2E_TIMEZONE=UTC+08:00
AIDATING_E2E_COUNTRY=CN
AIDATING_E2E_APP_PACKAGE=com.example.dating
AIDATING_E2E_CONSENT_POLICY_VERSION=2026-08-25
AIDATING_E2E_FIXTURE_ROOT=datasets
AIDATING_EVAL_BASE_URL=http://lb-rg3phjei-vzmdn2i7ey8rq40l.clb.usw-tencentclb.com/admin/invoke
AIDATING_EVAL_API_KEY=
AIDATING_EVAL_ALLOW_INSECURE_HTTP=false
AIDATING_EVAL_CONCURRENCY=3
AIDATING_RUN_STAGING_TESTS=0
AIDATING_RUN_PUBLIC_REPLY_STAGING=0
```

`errors.py` 定义以下异常，不放 HTTP 文案分支逻辑：

```python
class DatingEvalError(Exception):
    """工具可预期错误的基类。"""


class ConfigurationError(DatingEvalError):
    """运行配置缺失或不安全。"""


class CaseValidationError(DatingEvalError):
    """Case 在发请求前不满足本地约束。"""


class TransportError(DatingEvalError):
    """HTTP、JSON 或连接层失败。"""


class RunInterrupted(DatingEvalError):
    """收到停止信号后中止业务步骤，但仍需进入清理。"""


class ContractError(DatingEvalError):
    """响应信封、状态或 Schema 与冻结契约不一致。"""


class BusinessError(DatingEvalError):
    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        data: dict[str, object] | None = None,
        retryable: bool = False,
        task_id_to_cleanup: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.safe_message = message
        self.data = dict(data or {})
        self.retryable = retryable
        self.task_id_to_cleanup = task_id_to_cleanup
```

- [ ] **Step 4: 安装开发包并运行测试**

Run:

```bash
python -m pip install -e .
python -m unittest tests.unit.test_project_contract -v
```

Expected: 3 tests PASS。

- [ ] **Step 5: 提交工程骨架**

```bash
git add pyproject.toml .gitignore .env.example README.md src/aidating_eval tests artifacts/.gitkeep datasets/media/README.md
git commit -m "chore: scaffold lightweight dating evaluation tool"
```

---

## Task 2: 配置模型、精确 HTTP allowlist 与 doctor 基础检查

**Files:**
- Create: `src/aidating_eval/config.py`
- Create: `tests/unit/test_config.py`
- Modify: `src/aidating_eval/errors.py`

**Interfaces:**
- Produces: `Settings.from_env(mode) -> Settings`、`Settings.validate_for_mode(mode) -> None`、`Settings.redacted() -> dict[str, object]`。
- Consumes: Task 1 的 `ConfigurationError`。

- [ ] **Step 1: 写配置安全失败测试**

```python
# tests/unit/test_config.py
import unittest
from unittest.mock import patch

from aidating_eval.config import Settings
from aidating_eval.errors import ConfigurationError


class SettingsTests(unittest.TestCase):
    def test_eval_http_requires_exact_host_and_explicit_switch(self):
        env = {
            "AIDATING_EVAL_BASE_URL": (
                "http://lb-rg3phjei-vzmdn2i7ey8rq40l.clb.usw-tencentclb.com/admin/invoke"
            ),
            "AIDATING_EVAL_API_KEY": "test-secret",
            "AIDATING_EVAL_ALLOW_INSECURE_HTTP": "false",
        }
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env("eval")

    def test_unknown_http_host_is_always_rejected(self):
        env = {
            "AIDATING_EVAL_BASE_URL": "http://evil.example/admin/invoke",
            "AIDATING_EVAL_API_KEY": "test-secret",
            "AIDATING_EVAL_ALLOW_INSECURE_HTTP": "true",
        }
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env("eval")

    def test_secret_is_not_in_repr_or_redacted_dict(self):
        env = {
            "AIDATING_EVAL_BASE_URL": (
                "http://lb-rg3phjei-vzmdn2i7ey8rq40l.clb.usw-tencentclb.com/admin/invoke"
            ),
            "AIDATING_EVAL_API_KEY": "test-secret",
            "AIDATING_EVAL_ALLOW_INSECURE_HTTP": "true",
        }
        with patch.dict("os.environ", env, clear=True):
            settings = Settings.from_env("eval")
        self.assertNotIn("test-secret", repr(settings))
        self.assertEqual("***", settings.redacted()["eval_api_key"])
```

- [ ] **Step 2: 运行测试确认缺少 `Settings`**

```bash
python -m unittest tests.unit.test_config -v
```

Expected: FAIL with import error or missing `Settings`。

- [ ] **Step 3: 实现不可泄密配置模型**

```python
# src/aidating_eval/config.py
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import os

from aidating_eval.errors import ConfigurationError


EVAL_STAGING_HOST = "lb-rg3phjei-vzmdn2i7ey8rq40l.clb.usw-tencentclb.com"
PUBLIC_GATEWAY_URL = "https://gateway.spark-jam.top/dating/gateway/invoke"
PUBLIC_HEALTH_URL = "https://gateway.spark-jam.top/healthz"


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    if value.lower() not in {"true", "false", "1", "0"}:
        raise ConfigurationError(f"{name} 必须为 true/false/1/0")
    return value.lower() in {"true", "1"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须为整数") from exc


@dataclass(frozen=True)
class Settings:
    mode: str
    public_gateway_url: str = ""
    public_health_url: str = ""
    device_id: str = field(default="", repr=False)
    platform: str = "ios"
    app_version: str = "1.0.0"
    locale: str = "en-US"
    timezone: str = "UTC+08:00"
    country: str = "CN"
    app_package: str = "com.example.dating"
    consent_policy_version: str = "2026-08-25"
    e2e_fixture_root: Path = Path("datasets")
    eval_base_url: str = ""
    eval_api_key: str = field(default="", repr=False)
    allow_insecure_eval_http: bool = False
    artifacts_root: Path = Path("artifacts")
    eval_concurrency: int = 3

    @classmethod
    def from_env(cls, mode: str) -> "Settings":
        settings = cls(
            mode=mode,
            public_gateway_url=os.getenv("AIDATING_PUBLIC_GATEWAY_URL", ""),
            public_health_url=os.getenv("AIDATING_PUBLIC_HEALTH_URL", ""),
            device_id=os.getenv("AIDATING_E2E_DEVICE_ID", ""),
            platform=os.getenv("AIDATING_E2E_PLATFORM", "ios"),
            app_version=os.getenv("AIDATING_E2E_APP_VERSION", "1.0.0"),
            locale=os.getenv("AIDATING_E2E_LOCALE", "en-US"),
            timezone=os.getenv("AIDATING_E2E_TIMEZONE", "UTC+08:00"),
            country=os.getenv("AIDATING_E2E_COUNTRY", "CN"),
            app_package=os.getenv("AIDATING_E2E_APP_PACKAGE", "com.example.dating"),
            consent_policy_version=os.getenv(
                "AIDATING_E2E_CONSENT_POLICY_VERSION", "2026-08-25"
            ),
            e2e_fixture_root=Path(
                os.getenv("AIDATING_E2E_FIXTURE_ROOT", "datasets")
            ),
            eval_base_url=os.getenv("AIDATING_EVAL_BASE_URL", ""),
            eval_api_key=os.getenv("AIDATING_EVAL_API_KEY", ""),
            allow_insecure_eval_http=_bool_env(
                "AIDATING_EVAL_ALLOW_INSECURE_HTTP"
            ),
            eval_concurrency=_int_env("AIDATING_EVAL_CONCURRENCY", 3),
        )
        settings.validate_for_mode(mode)
        return settings

    def validate_for_mode(self, mode: str) -> None:
        if mode == "e2e":
            if self.public_gateway_url != PUBLIC_GATEWAY_URL:
                raise ConfigurationError("公开 E2E Gateway 必须是已确认的 staging 地址")
            if self.public_health_url != PUBLIC_HEALTH_URL:
                raise ConfigurationError("公开 Health URL 必须是已确认的 staging 地址")
            if not self.device_id:
                raise ConfigurationError("AIDATING_E2E_DEVICE_ID 不能为空")
            if not self.e2e_fixture_root.is_dir():
                raise ConfigurationError("AIDATING_E2E_FIXTURE_ROOT 必须是现有目录")
            return
        if mode != "eval":
            raise ConfigurationError("mode 必须为 e2e 或 eval")
        parsed = urlparse(self.eval_base_url)
        if not self.eval_api_key:
            raise ConfigurationError("AIDATING_EVAL_API_KEY 不能为空")
        if (
            parsed.netloc != EVAL_STAGING_HOST
            or parsed.path != "/admin/invoke"
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError("Eval URL 必须命中精确 staging 主机和路径")
        if parsed.scheme == "http":
            if not self.allow_insecure_eval_http:
                raise ConfigurationError("内部 HTTP 只允许精确 staging 主机并显式开启")
        elif parsed.scheme != "https":
            raise ConfigurationError("Eval URL 必须使用 http 或 https")
        if not 1 <= self.eval_concurrency <= 5:
            raise ConfigurationError("AIDATING_EVAL_CONCURRENCY 必须在 1 到 5 之间")

    def redacted(self) -> dict[str, object]:
        values = dict(self.__dict__)
        values["eval_api_key"] = "***" if self.eval_api_key else ""
        values["device_id"] = "***" if self.device_id else ""
        values["artifacts_root"] = str(self.artifacts_root)
        values["e2e_fixture_root"] = str(self.e2e_fixture_root)
        return values
```

- [ ] **Step 4: 补充边界测试并运行**

新增测试：E2E 地址/Health 非精确 allowlist 拒绝、缺 `device_id` 拒绝、Fixture Root 不存在
拒绝、`device_id` 在 redacted 配置中隐藏、`eval_concurrency` 非整数或超过 5 拒绝、未知
mode 拒绝。

```bash
python -m unittest tests.unit.test_config -v
```

Expected: all tests PASS。

- [ ] **Step 5: 提交配置层**

```bash
git add src/aidating_eval/config.py src/aidating_eval/errors.py tests/unit/test_config.py
git commit -m "feat: add secure dual-mode configuration"
```

---

## Task 3: 领域模型、E2E JSON 和 Eval JSONL 校验

**Files:**
- Create: `src/aidating_eval/domain.py`
- Create: `src/aidating_eval/cases.py`
- Create: `tests/unit/test_cases.py`
- Create: `tests/fixtures/cases/e2e-analysis-valid.json`
- Create: `tests/fixtures/cases/e2e-reply-valid.json`
- Create: `tests/fixtures/cases/e2e-path-traversal.json`
- Create: `tests/fixtures/cases/eval-mixed-valid.jsonl`

**Interfaces:**
- Produces: `E2EReplyCase`、`E2EAnalysisCase`、`EvaluationReplyCase`、`EvaluationAnalysisCase`、`TranscriptMessage`、`TaskSnapshot`、`PollPolicy`、`CaseOutcome`、`load_cases(path, mode, fixture_root=None)`；E2E 必须显式传根目录，Eval 忽略该参数。
- Consumes: `CaseValidationError`。

- [ ] **Step 1: 写 Case Loader 失败测试**

```python
# tests/unit/test_cases.py
import json
import tempfile
import unittest
from pathlib import Path

from aidating_eval.cases import load_cases
from aidating_eval.errors import CaseValidationError


class CaseLoaderTests(unittest.TestCase):
    def test_e2e_reply_resolves_media_inside_explicit_fixture_root(self):
        case = json.loads(
            Path("tests/fixtures/cases/e2e-reply-valid.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "media").mkdir()
            (root / "media" / "reply.png").write_bytes(b"fixture-placeholder")
            case["media"] = [{"path": "media/reply.png"}]
            path = root / "reply.json"
            path.write_text(json.dumps(case), encoding="utf-8")
            loaded = load_cases(path, "e2e", fixture_root=root)
        self.assertEqual("reply", loaded[0].task_kind)

    def test_eval_maps_self_to_user_and_counts_utf8_bytes(self):
        cases = load_cases(
            Path("tests/fixtures/cases/eval-mixed-valid.jsonl"), "eval"
        )
        reply = next(case for case in cases if case.task_kind == "reply")
        self.assertEqual("user", reply.messages[1].speaker)
        self.assertGreater(reply.text_bytes, 0)

    def test_eval_rejects_reply_only_fields(self):
        case = {
            "schema_version": "aidating.eval.case.v1",
            "case_id": "bad-reply-field",
            "task_kind": "analysis",
            "locale": "en-US",
            "background": "not supported for internal analysis",
            "transcript": {
                "schema_version": "dating.transcript.v1",
                "messages": [
                    {"message_id": "m1", "message_type": "text", "speaker": "other", "text": "a"},
                    {"message_id": "m2", "message_type": "text", "speaker": "self", "text": "b"},
                    {"message_id": "m3", "message_type": "text", "speaker": "other", "text": "c"},
                    {"message_id": "m4", "message_type": "text", "speaker": "self", "text": "d"}
                ]
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"
            path.write_text(json.dumps(case) + "\n", encoding="utf-8")
            with self.assertRaises(CaseValidationError):
                load_cases(path, "eval")

    def test_public_reply_requires_preferences(self):
        case = json.loads(
            Path("tests/fixtures/cases/e2e-reply-valid.json").read_text(
                encoding="utf-8"
            )
        )
        del case["preferences"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reply.json"
            path.write_text(json.dumps(case), encoding="utf-8")
            with self.assertRaises(CaseValidationError):
                load_cases(path, "e2e", fixture_root=Path(directory))

    def test_controlled_negative_requires_matching_stable_error(self):
        case = json.loads(
            Path("tests/fixtures/cases/eval-mixed-valid.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        case["negative_variant"] = "message_count_below_min"
        case["expect"] = {
            "task_status": None,
            "result_schema": None,
            "business_error_code": "INPUT_INVALID",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "negative.jsonl"
            path.write_text(json.dumps(case) + "\n", encoding="utf-8")
            self.assertEqual(1, len(load_cases(path, "eval")))

    def test_e2e_rejects_media_outside_fixture_root(self):
        with self.assertRaises(CaseValidationError):
            load_cases(
                Path("tests/fixtures/cases/e2e-path-traversal.json"),
                "e2e",
                fixture_root=Path("tests/fixtures/media"),
            )
```

`e2e-path-traversal.json` 使用合法 E2E Case 结构，但媒体路径固定写为
`../../outside-private-image.png`，用于证明 Loader 在任何文件读取或网络请求前拒绝越出
`datasets/media` 根目录的路径。

- [ ] **Step 2: 运行测试确认模型尚未实现**

```bash
python -m unittest tests.unit.test_cases -v
```

Expected: FAIL with missing module/classes。

- [ ] **Step 3: 定义稳定领域类型**

```python
# src/aidating_eval/domain.py
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class RunMode(StrEnum):
    E2E = "e2e"
    EVAL = "eval"


class TaskKind(StrEnum):
    REPLY = "reply"
    ANALYSIS = "analysis"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class TranscriptMessage:
    message_id: str
    message_type: str
    speaker: str
    text: str


@dataclass(frozen=True)
class CaseExpectation:
    task_status: str | None = "succeeded"
    result_schema: str | None = None
    business_error_code: str | None = None
    warning_codes: tuple[str, ...] = ()
    policy_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplyPreferences:
    dating_goal: str
    your_voice: str


@dataclass(frozen=True)
class E2EReplyCase:
    case_id: str
    locale: str
    media_paths: tuple[Path, ...]
    preferences: ReplyPreferences
    requested_intent: str | None
    background: str | None
    expect: CaseExpectation = field(
        default_factory=lambda: CaseExpectation(
            result_schema="dating.reply_generation.v1"
        )
    )

    @property
    def task_kind(self) -> TaskKind:
        return TaskKind.REPLY


@dataclass(frozen=True)
class E2EAnalysisCase:
    case_id: str
    locale: str
    media_paths: tuple[Path, ...]
    other_person_name: str | None
    background: str | None
    expect: CaseExpectation = field(
        default_factory=lambda: CaseExpectation(
            result_schema="dating.relationship_analysis.v1"
        )
    )

    @property
    def task_kind(self) -> TaskKind:
        return TaskKind.ANALYSIS


@dataclass(frozen=True)
class EvaluationReplyCase:
    case_id: str
    locale: str
    messages: tuple[TranscriptMessage, ...]
    dating_goal: str
    your_voice: str
    requested_intent: str | None = None
    background: str | None = None
    negative_variant: str | None = None
    expect: CaseExpectation = field(
        default_factory=lambda: CaseExpectation(
            result_schema="dating.reply_generation.v1"
        )
    )

    @property
    def task_kind(self) -> TaskKind:
        return TaskKind.REPLY

    @property
    def text_bytes(self) -> int:
        return sum(len(message.text.encode("utf-8")) for message in self.messages)


@dataclass(frozen=True)
class EvaluationAnalysisCase:
    case_id: str
    locale: str
    messages: tuple[TranscriptMessage, ...]
    negative_variant: str | None = None
    expect: CaseExpectation = field(
        default_factory=lambda: CaseExpectation(
            result_schema="dating.relationship_analysis.v1"
        )
    )

    @property
    def task_kind(self) -> TaskKind:
        return TaskKind.ANALYSIS

    @property
    def text_bytes(self) -> int:
        return sum(len(message.text.encode("utf-8")) for message in self.messages)


CaseDefinition = (
    E2EReplyCase
    | E2EAnalysisCase
    | EvaluationReplyCase
    | EvaluationAnalysisCase
)


@dataclass(frozen=True)
class PollPolicy:
    timeout_seconds: float
    initial_interval_seconds: float
    steady_interval_seconds: float
    switch_after_seconds: float = 0

    def interval_for(self, elapsed_seconds: float) -> float:
        if elapsed_seconds < self.switch_after_seconds:
            return self.initial_interval_seconds
        return self.steady_interval_seconds


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    task_type: str
    status: TaskStatus
    phase: str
    retryable: bool
    error_code: str | None
    raw: Mapping[str, Any] = field(repr=False)
```

`cases.py` 必须执行以下精确规则：

- E2E `dataset` 必须是目录或单个 `.json`，目录时只读取根层 `*.json` 并按文件名稳定排序；
  Eval 必须是 UTF-8 `.jsonl`，忽略纯空行但不允许注释；
- E2E 只接受 `schema_version=aidating.e2e.case.v1`，`task_kind` 为 `reply/analysis`；
- `case_id` 在数据集内唯一，只允许 1～80 个 ASCII 字母、数字、点、下划线和连字符，
  防止 Artifact 路径穿越并保证可安全用于请求追踪；
- `locale` 必须为 1～64 个字符；MVP 不擅自维护完整 BCP 47 枚举；
- E2E 媒体至少 1 张；Loader 不硬编码服务端最大数量，路径相对显式 `fixture_root` 解析，
  `Path.resolve()` 后仍必须位于该根目录，且文件存在可读；运行时再按
  `GetMediaUploadConfig` 动态约束复核；
- Reply E2E 必须有 `preferences.dating_goal/your_voice` 和 `reply` 字段；Analysis E2E
  禁止 `preferences/reply`，可使用 `analysis.other_person_name/background`；
- Eval 只接受 `schema_version=aidating.eval.case.v1`、`task_kind=reply/analysis`，Transcript
  固定 `schema_version=dating.transcript.v1`；
- Reply Eval 为 4～300 条，Analysis Eval 为 4～500 条；双方至少各 2 条，`self` 在内存
  模型中转换为 `user`，`message_id` 唯一且 `message_type=text`；
- Reply 正文总计不超过 131,072 UTF-8 字节，`background` 最多 1,000 Unicode 字符，
  `requested_intent` 仅允许 `opener/flirt/tease/advance`；
- Analysis 单条正文不超过 4,096 UTF-8 字节、正文总计不超过 131,072 字节、发送前
  使用 `json.dumps(params, ensure_ascii=False, separators=(",", ":"))` 序列化后的整个
  `params` 不超过 262,144 UTF-8 字节；
- Analysis 拒绝 `background/dating_goal/your_voice/requested_intent`；
- `dating_goal/your_voice` 先要求非空稳定 code，并集中在可替换枚举表；后端冻结最终
  code 后只改枚举表，不改数据解析流程；Public Preferences 与 Internal Reply 使用两张
  独立表，不能假设 `find_relationship` 与 `serious_relationship` 等 code 可互换；
- 所有偏好 code 同时满足小写稳定格式 `^[a-z][a-z0-9_]{0,63}$`；
- `expect` 只接受 `task_status/result_schema/business_error_code/warning_codes/policy_codes`；
  warning 与 policy 仅做包含关系断言，不比较自由文本或字段顺序；
- 正向 Reply/Analysis 的 `expect.result_schema` 必须分别是
  `dating.reply_generation.v1` / `dating.relationship_analysis.v1`；预期 Create 阶段业务错误
  的 Case 必须令 `task_status=null`、`result_schema=null`；
- JSON/JSONL 未知字段直接拒绝，唯有受控负向变体可由工具在合法基础 Case 上生成。
- Case 永远不接受 `model/prompt/app_id/user_id/service_name/method_name/task_id/api_key`；这些
  要么由服务端控制，要么只属于 Adapter/运行时。

受控负向变体固定为枚举，不允许任意原始 JSON 直通：

```python
class NegativeVariant(StrEnum):
    MESSAGE_COUNT_BELOW_MIN = "message_count_below_min"
    INSUFFICIENT_PARTY_MESSAGES = "insufficient_party_messages"
    DUPLICATE_MESSAGE_ID = "duplicate_message_id"
    UNSUPPORTED_FIELD = "unsupported_field"
    IDEMPOTENCY_SAME = "idempotency_same"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
```

Loader 先验证未变异的基础 Case 合法，再验证变体和 `expect.business_error_code` 的对应关系；
具体非法 Payload 只在 Evaluation Adapter 的请求构造末端生成，从而既能测服务端边界，
又不开放任意请求注入能力。

- [ ] **Step 4: 运行 Case 测试并补齐边界**

新增 Reply 的 4/300/301 条、Analysis 的 4/301/500/501 条、4,096/4,097 字节、
`background` 1,000/1,001 字符、无效 intent、重复 ID、双方不足、E2E 缺 Preferences、
Analysis 混入 Reply 字段，以及六种受控负向变体映射测试。

```bash
python -m unittest tests.unit.test_cases -v
```

Expected: all tests PASS。

- [ ] **Step 5: 提交领域与数据校验**

```bash
git add src/aidating_eval/domain.py src/aidating_eval/cases.py tests/unit/test_cases.py tests/fixtures/cases
git commit -m "feat: add reply and analysis case models"
```

---

## Task 4: 递归脱敏与安全 Artifact Store

**Files:**
- Create: `src/aidating_eval/redaction.py`
- Create: `src/aidating_eval/artifacts.py`
- Create: `tests/unit/test_redaction.py`
- Create: `tests/unit/test_artifacts.py`

**Interfaces:**
- Produces: `redact_mapping(value) -> object`、`ArtifactStore.start_run()`、`append_event()`、`write_case_payload()`。
- Consumes: `RunMode` 和标准 JSON 可序列化数据。

- [ ] **Step 1: 写 Secret 脱敏失败测试**

```python
# tests/unit/test_redaction.py
import unittest

from aidating_eval.redaction import redact_mapping


class RedactionTests(unittest.TestCase):
    def test_redacts_nested_tokens_and_signed_urls(self):
        source = {
            "comm": {"auth_token": "access-secret"},
            "refresh_token": "refresh-secret",
            "headers": {"Authorization": "Bearer eval-secret"},
            "upload_url": "https://cos.example/object?signature=secret",
            "task_id": "dating_task_safe",
        }
        redacted = redact_mapping(source)
        serialized = repr(redacted)
        for secret in ("access-secret", "refresh-secret", "eval-secret", "signature=secret"):
            self.assertNotIn(secret, serialized)
        self.assertEqual("dating_task_safe", redacted["task_id"])
```

```python
# tests/unit/test_artifacts.py
import json
import tempfile
import unittest
from pathlib import Path

from aidating_eval.artifacts import ArtifactStore


class ArtifactStoreTests(unittest.TestCase):
    def test_writes_private_files_and_append_only_events(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory), "run-1")
            store.append_event("case-1", "task_created", {"task_id": "task-1"})
            store.write_case_payload("case-1", "task.json", {"status": "queued"})
            event_path = Path(directory) / "run-1" / "run-state.jsonl"
            self.assertEqual(0o600, event_path.stat().st_mode & 0o777)
            self.assertEqual(1, len(event_path.read_text().splitlines()))
```

- [ ] **Step 2: 运行测试确认模块不存在**

```bash
python -m unittest tests.unit.test_redaction tests.unit.test_artifacts -v
```

Expected: FAIL with missing modules。

- [ ] **Step 3: 实现确定性脱敏与原子写入**

`redaction.py` 使用 Key 白名单规则，不依赖正则猜测业务消息：

```python
SECRET_KEYS = {
    "authorization",
    "auth_token",
    "access_token",
    "refresh_token",
    "api_key",
    "upload_url",
    "required_headers",
    "x-cos-security-token",
    "signature",
    "credential",
    "user_id",
    "device_id",
}


def redact_mapping(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "***" if key.lower() in SECRET_KEYS else redact_mapping(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact_mapping(child) for child in value]
    if isinstance(value, tuple):
        return [redact_mapping(child) for child in value]
    return value
```

`ArtifactStore` 要求：

- 创建 Run 目录后立即 `chmod(0o700)`；
- 临时文件写完、`fsync` 后使用 `Path.replace()` 原子替换；
- 文件完成后 `chmod(0o600)`；
- `run-state.jsonl` 使用进程内 `threading.Lock` 保护并发追加；
- 每次 JSONL 追加后执行 `flush + os.fsync`，确保中断后的 cleanup 能读取已创建 Task；
- `write_case_payload()` 写入前调用 `redact_mapping()`；
- Result 正文只写文件，不进入 logger；
- `manifest.json` 只保存配置的 `redacted()` 结果。

- [ ] **Step 4: 运行脱敏和权限测试**

```bash
python -m unittest tests.unit.test_redaction tests.unit.test_artifacts -v
```

Expected: all tests PASS。

- [ ] **Step 5: 提交安全产物层**

```bash
git add src/aidating_eval/redaction.py src/aidating_eval/artifacts.py tests/unit/test_redaction.py tests/unit/test_artifacts.py
git commit -m "feat: add redacted private run artifacts"
```

---

## Task 5: HTTP Transport 与两种响应信封解析

**Files:**
- Create: `src/aidating_eval/http.py`
- Create: `src/aidating_eval/public_gateway.py`
- Create: `src/aidating_eval/evaluation_gateway.py`
- Create: `tests/helpers.py`
- Create: `tests/unit/test_http.py`
- Create: `tests/unit/test_gateway_clients.py`

**Interfaces:**
- Produces: `RequestsTransport.get_status()`、`request_json()`、`put_bytes()`、`PublicGatewayClient.call()`、`EvaluationGatewayClient.call()`。
- Consumes: `Settings`、`TransportError`、`ContractError`、`BusinessError`。

- [ ] **Step 1: 写公开与内部信封失败测试**

```python
# tests/unit/test_gateway_clients.py
import unittest

from aidating_eval.evaluation_gateway import EvaluationGatewayClient
from aidating_eval.public_gateway import PublicGatewayClient
from tests.helpers import FakeTransport


class GatewayClientTests(unittest.TestCase):
    def test_public_access_token_is_in_comm_not_authorization_header(self):
        transport = FakeTransport([{"code": 0, "responses": [{"id": "r1", "success": True, "code": 0, "data": {}}]}])
        client = PublicGatewayClient.example_for_test(transport)
        client.call("tool.identity.IdentityService", "GetMe", {}, "r1", "token")
        call = transport.calls[0]
        self.assertEqual("token", call.json_body["comm"]["auth_token"])
        self.assertNotIn("Authorization", call.headers)

    def test_internal_key_is_bearer_header(self):
        transport = FakeTransport([{"responses": [{"success": True, "data": {"ok": True}}]}])
        client = EvaluationGatewayClient(
            transport=transport,
            url="http://allowed.test/admin/invoke",
            api_key="secret",
        )
        client.call("GetAnalysisEvaluationTask", {"task_id": "task-1"})
        self.assertEqual("Bearer secret", transport.calls[0].headers["Authorization"])

    def test_business_error_uses_code_not_message(self):
        transport = FakeTransport([{
            "code": 0,
            "responses": [{
                "id": "r1",
                "success": False,
                "code": 306409,
                "http_status": 409,
                "message": "arbitrary text",
                "business_error_code": "TASK_NOT_READY",
                "data": {"error_code": "TASK_NOT_READY"},
            }],
        }])
        client = PublicGatewayClient.example_for_test(transport)
        with self.assertRaisesRegex(Exception, "TASK_NOT_READY"):
            client.call("tool.dating.DatingAssistantService", "GetAnalysisResult", {}, "r1", "token")
```

- [ ] **Step 2: 运行测试确认 Client 尚未定义**

```bash
python -m unittest tests.unit.test_http tests.unit.test_gateway_clients -v
```

Expected: FAIL with import errors。

- [ ] **Step 3: 实现无业务重试的 Transport**

```python
# src/aidating_eval/http.py
from dataclasses import dataclass
from typing import Any
import threading

import requests

from aidating_eval.errors import TransportError


@dataclass(frozen=True)
class HttpCall:
    method: str
    url: str
    headers: dict[str, str]
    json_body: dict[str, Any] | None


class RequestsTransport:
    """每个线程持有独立 Session，Transport 自身不做业务重试。"""

    def __init__(self, timeout_seconds: float = 15) -> None:
        self.timeout_seconds = timeout_seconds
        self._local = threading.local()

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def get_status(self, url: str) -> int:
        """只返回健康检查状态码；异常中不携带 URL 或响应正文。"""
        try:
            response = self._session().get(
                url, timeout=self.timeout_seconds, allow_redirects=False
            )
        except requests.RequestException as exc:
            raise TransportError(type(exc).__name__) from exc
        return response.status_code

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            response = self._session().request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
            if not 200 <= response.status_code < 300:
                raise TransportError(f"HTTP_{response.status_code}")
            body = response.json()
        except TransportError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise TransportError(type(exc).__name__) from exc
        if not isinstance(body, dict):
            raise TransportError("响应 JSON 顶层必须是对象")
        return body
```

`get_status()` 仅供公开 `/healthz` 使用，要求 HTTP 200；`put_bytes()` 单独接收
`url/required_headers/content`，固定禁止重定向。两者的异常中均不得包含 URL；测试必须
断言异常字符串没有查询参数。
`put_bytes()` 只接受 2xx，错误中仅保留 HTTP 状态码，不读取或记录 COS 响应正文。

- [ ] **Step 4: 实现两种 Gateway Client**

`PublicGatewayClient.call()`：

- 构造 `comm/execution/requests`：`comm` 固定包含配置中的
  `device_id/platform/app_version/locale/timezone/country/app_package`，有会话时才加入
  `auth_token`；`execution` 包含每次调用唯一的 `request_id` 和当前毫秒时间；`requests`
  恰好包含一个 `service_name/method_name/params` 子请求；
- `access_token` 只放 `comm.auth_token`；
- 禁止 `params` 出现 `app_id/user_id`；
- 校验顶层 `code == 0`；
- 校验 `responses` 是长度恰好为 1 的数组且首项为对象；
- 校验 `responses[0].id` 与本次唯一子请求 ID 一致；
- 公开成功子响应要求 `success=true` 且 `code=0`；失败时保留安全的数值 `code/http_status`
  供排障，但业务分支仍只使用稳定 `business_error_code`；
- `success=false` 时抛出带 `business_error_code` 的 `BusinessError`；
- 服务端自由文本 `message` 不参与分支，也不直接进入异常、日志或产物；`safe_message`
  只允许来自工具本地的稳定 code 映射；
- 返回 `responses[0].data`。

`EvaluationGatewayClient.call()` 先构造所有方法共用字段：

```python
payload = {
    "service_name": "tool.dating.internal.DatingEvaluationService",
    "method_name": method_name,
    "params": params,
}
if client_request_id is not None:
    payload["client_request_id"] = client_request_id
if reason is not None:
    payload["reason"] = reason
```

Create 传 `client_request_id + reason`，Delete 传 `reason`，Task/Result/Diagnostics 不添加
文档示例中不存在的顶层字段。读取相同的 `responses[0]`；Authorization Header 只存在于
内存中的调用参数，绝不传给 Artifact Store。
内部调用同样要求 `responses` 恰好一个对象，并只根据 `success/business_error_code` 分支。

- [ ] **Step 5: 运行 Client 和 Transport 测试**

Transport 测试同时覆盖连接异常、非 JSON、JSON 顶层非对象、3xx 不跟随、4xx/5xx 只保留
状态码、COS PUT 响应正文不进入异常。

```bash
python -m unittest tests.unit.test_http tests.unit.test_gateway_clients -v
```

Expected: all tests PASS。

- [ ] **Step 6: 提交 HTTP 与信封层**

```bash
git add src/aidating_eval/http.py src/aidating_eval/public_gateway.py src/aidating_eval/evaluation_gateway.py tests/helpers.py tests/unit/test_http.py tests/unit/test_gateway_clients.py
git commit -m "feat: add public and evaluation gateway clients"
```

---

## Task 6: TaskFlowAdapter 端口与单案例 Runner

**Files:**
- Create: `src/aidating_eval/ports.py`
- Create: `src/aidating_eval/runner.py`
- Create: `tests/unit/test_runner.py`
- Modify: `src/aidating_eval/domain.py`
- Modify: `tests/helpers.py`

**Interfaces:**
- Produces: `TaskFlowAdapter`、`RunControl`、`CaseRunner.execute(case, context) -> CaseOutcome`。
- Consumes: Task 3 的领域模型、Task 4 的 `ArtifactStore`、Task 5 的错误类型。

- [ ] **Step 1: 写 Runner 必须 finally 删除的失败测试**

```python
# tests/unit/test_runner.py
import unittest

from aidating_eval.domain import (
    CaseOutcomeStatus,
    CleanupResult,
    PollPolicy,
    TaskSnapshot,
    TaskStatus,
)
from aidating_eval.runner import CaseRunner
from tests.helpers import FakeAdapter, MemoryArtifactStore


class RunnerTests(unittest.TestCase):
    def test_succeeded_task_fetches_result_and_deletes(self):
        adapter = FakeAdapter(
            tasks=[
                TaskSnapshot("task-1", "relationship_analysis", TaskStatus.QUEUED, "queued", False, None, {}),
                TaskSnapshot("task-1", "relationship_analysis", TaskStatus.SUCCEEDED, "finalizing", False, None, {}),
            ],
            result={"schema_version": "dating.relationship_analysis.v1"},
            diagnostics={"model_alias": "staging-model"},
            cleanup=CleanupResult(True, "deleted"),
        )
        runner = CaseRunner(adapter, MemoryArtifactStore(), sleep_fn=lambda _: None)
        outcome = runner.execute(FakeAdapter.case(), FakeAdapter.context())
        self.assertEqual(CaseOutcomeStatus.COMPLETED, outcome.status)
        self.assertEqual(["task-1"], adapter.deleted_task_ids)

    def test_result_failure_still_deletes_task(self):
        adapter = FakeAdapter.succeeded_but_result_fails()
        runner = CaseRunner(adapter, MemoryArtifactStore(), sleep_fn=lambda _: None)
        outcome = runner.execute(FakeAdapter.case(), FakeAdapter.context())
        self.assertEqual(CaseOutcomeStatus.FAILED, outcome.status)
        self.assertEqual(["task-1"], adapter.deleted_task_ids)

    def test_delete_failure_overrides_status_to_cleanup_pending(self):
        adapter = FakeAdapter.succeeded_but_delete_fails()
        runner = CaseRunner(adapter, MemoryArtifactStore(), sleep_fn=lambda _: None)
        outcome = runner.execute(FakeAdapter.case(), FakeAdapter.context())
        self.assertEqual(CaseOutcomeStatus.CLEANUP_PENDING, outcome.status)
```

- [ ] **Step 2: 运行测试确认 Runner 缺失**

```bash
python -m unittest tests.unit.test_runner -v
```

Expected: FAIL with missing `CaseRunner` or domain types。

- [ ] **Step 3: 补齐 Runner 所需领域类型**

```python
# additions to src/aidating_eval/domain.py
from datetime import datetime, timezone
from uuid import uuid4


class CaseOutcomeStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    CLEANUP_PENDING = "cleanup_pending"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    attempt_id: str
    mode: RunMode
    task_kind: TaskKind

    @classmethod
    def for_case(
        cls, run_id: str, case_id: str, mode: RunMode, task_kind: TaskKind
    ) -> "RunContext":
        return cls(
            run_id=run_id,
            attempt_id=f"{case_id}-{uuid4().hex[:12]}",
            mode=mode,
            task_kind=task_kind,
        )

    def next_attempt(self, case_id: str) -> "RunContext":
        return RunContext.for_case(
            self.run_id, case_id, self.mode, self.task_kind
        )


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid4().hex[:8]}"


@dataclass(frozen=True)
class PreparedCase:
    payload: Mapping[str, Any]
    safe_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CleanupResult:
    success: bool
    status: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    status: CaseOutcomeStatus
    task_id: str | None
    business_error_code: str | None
    schema_version: str | None
    cleanup: CleanupResult | None
    retryable: bool = False

    @classmethod
    def not_started(cls, case_id: str, code: str) -> "CaseOutcome":
        return cls(
            case_id=case_id,
            status=CaseOutcomeStatus.INCOMPLETE,
            task_id=None,
            business_error_code=code,
            schema_version=None,
            cleanup=None,
        )


# src/aidating_eval/runner.py
from aidating_eval.errors import RunInterrupted


class RunControl:
    """协调用户中断和批次级致命错误，不保存服务端自由文本。"""

    def __init__(self) -> None:
        from threading import Event, Lock

        self._stopped = Event()
        self._lock = Lock()
        self._reason: str | None = None

    def request_stop(self, stable_reason: str) -> None:
        with self._lock:
            self._reason = self._reason or stable_reason
            self._stopped.set()

    def may_start_new_case(self) -> bool:
        return not self._stopped.is_set()

    def raise_if_stopped(self) -> None:
        if self._stopped.is_set():
            raise RunInterrupted(self._reason or "RUN_STOP_REQUESTED")
```

- [ ] **Step 4: 实现 Runner 状态机**

先把单次尝试实现为 `_execute_once()`：

`CaseRunner` 构造函数可注入共享 `RunControl`；单元测试未传时创建仅供当前 Runner 使用的
默认实例。

```python
from aidating_eval.errors import BusinessError, DatingEvalError, RunInterrupted


def _execute_once(self, case: CaseDefinition, context: RunContext) -> CaseOutcome:
    task_id: str | None = None
    cleanup: CleanupResult | None = None
    outcome_status = CaseOutcomeStatus.FAILED
    business_code: str | None = None
    schema_version: str | None = None
    retryable = False
    expected_error = case.expect.business_error_code
    try:
        self.artifacts.write_case_payload(
            case.case_id,
            "metadata.json",
            {
                "case_id": case.case_id,
                "mode": context.mode,
                "task_kind": case.task_kind,
                "locale": case.locale,
                "attempt_id": context.attempt_id,
            },
        )
        prepared = self.adapter.prepare_case(case, context)
        self.artifacts.append_event(
            case.case_id, "case_prepared", prepared.safe_metadata
        )
        created = self.adapter.create_task(case, prepared, context)
        task_id = created.task_id
        self.artifacts.append_event(
            case.case_id,
            "task_created",
            {
                "task_id": task_id,
                "task_kind": case.task_kind,
                "task_type": created.task_type,
            },
        )
        terminal = self._poll_until_terminal(task_id, context)
        self.artifacts.write_case_payload(case.case_id, "task.json", terminal.raw)
        status_matches = (
            case.expect.task_status is None
            or terminal.status.value == case.expect.task_status
        )
        if terminal.status is TaskStatus.SUCCEEDED:
            result = self.adapter.get_result(task_id, case, context)
            schema_version = str(result.get("schema_version", ""))
            self.artifacts.write_case_payload(case.case_id, "result.json", result)
            if expected_error is None and status_matches:
                outcome_status = CaseOutcomeStatus.COMPLETED
            else:
                business_code = (
                    "EXPECTED_BUSINESS_ERROR_NOT_OBSERVED"
                    if expected_error is not None
                    else "UNEXPECTED_TASK_STATUS"
                )
                outcome_status = CaseOutcomeStatus.FAILED
        elif terminal.status in {TaskStatus.REJECTED, TaskStatus.FAILED}:
            business_code = terminal.error_code
            retryable = (
                terminal.status is TaskStatus.FAILED and terminal.retryable
            )
            outcome_status = (
                CaseOutcomeStatus.COMPLETED
                if status_matches
                and (expected_error is None or business_code == expected_error)
                else CaseOutcomeStatus.FAILED
            )
    except TimeoutError:
        outcome_status = CaseOutcomeStatus.INCOMPLETE
    except RunInterrupted:
        business_code = "RUN_STOP_REQUESTED"
        outcome_status = CaseOutcomeStatus.INCOMPLETE
    except BusinessError as exc:
        business_code = exc.code
        if business_code in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
            self.run_control.request_stop(business_code)
        if task_id is None:
            task_id = exc.task_id_to_cleanup
        retryable = exc.retryable
        outcome_status = (
            CaseOutcomeStatus.COMPLETED
            if business_code == expected_error
            and case.expect.task_status is None
            else CaseOutcomeStatus.FAILED
        )
        self.artifacts.write_case_payload(
            case.case_id,
            "error.json",
            {"error_type": type(exc).__name__, "business_error_code": business_code},
        )
    except DatingEvalError as exc:
        business_code = getattr(exc, "code", type(exc).__name__)
        self.artifacts.write_case_payload(
            case.case_id,
            "error.json",
            {"error_type": type(exc).__name__, "business_error_code": business_code},
        )
    finally:
        if task_id is not None:
            # Result 解析失败时仍尝试取得内部诊断；公开 Adapter 在这里返回 None。
            try:
                diagnostics = self.adapter.get_diagnostics(task_id, case, context)
                if diagnostics is not None:
                    self.artifacts.write_case_payload(
                        case.case_id, "diagnostics.json", diagnostics
                    )
            except DatingEvalError as exc:
                self.artifacts.append_event(
                    case.case_id,
                    "diagnostics_failed",
                    {
                        "error_type": type(exc).__name__,
                        "business_error_code": getattr(exc, "code", None),
                    },
                )

            # 清理失败不能从 finally 向外逃逸，否则批次会丢失可恢复状态。
            try:
                cleanup = self.adapter.delete_task(task_id, context)
                self.artifacts.write_case_payload(
                    case.case_id, "cleanup.json", cleanup.raw
                )
            except DatingEvalError as exc:
                cleanup = CleanupResult(False, "delete_failed")
                self.artifacts.write_case_payload(
                    case.case_id,
                    "cleanup.json",
                    {
                        "success": False,
                        "error_type": type(exc).__name__,
                        "business_error_code": getattr(exc, "code", None),
                    },
                )
            delete_event = (
                "delete_already_absent"
                if cleanup.status == "already_absent"
                else "delete_succeeded"
                if cleanup.success
                else "delete_failed"
            )
            self.artifacts.append_event(
                case.case_id,
                delete_event,
                {"task_id": task_id, "task_kind": case.task_kind},
            )
            if not cleanup.success:
                outcome_status = CaseOutcomeStatus.CLEANUP_PENDING
    return CaseOutcome(
        case_id=case.case_id,
        status=outcome_status,
        task_id=task_id,
        business_error_code=business_code,
        schema_version=schema_version,
        cleanup=cleanup,
        retryable=retryable,
    )
```

公开 `execute()` 只包一层最多两次的尝试控制：

```python
def execute(self, case: CaseDefinition, context: RunContext) -> CaseOutcome:
    outcome = self._execute_once(case, context)
    if (
        not outcome.retryable
        or outcome.status is CaseOutcomeStatus.COMPLETED
        or outcome.status is CaseOutcomeStatus.CLEANUP_PENDING
    ):
        return outcome
    return self._execute_once(case, context.next_attempt(case.case_id))
```

第一次尝试必须先完成删除，才允许第二次创建；第二次使用同一 `run_id`、新的
`attempt_id/client_request_id`。`rejected`、输入错误、权限错误、幂等冲突和清理未确认
永不重试。单个 HTTP 请求因网络结果未知的幂等重试仍在 Adapter 内复用原请求 ID，不计为
新的 Case Attempt。

代码片段省略的事件写入仍是必做项：每条事件都带 `case_id/attempt_id/task_kind`，按实际
转移追加：

```text
case_started → prepare_started → case_prepared → task_created
→ task_queued | task_processing
→ task_succeeded | task_rejected | task_failed | task_timeout
→ result_fetched → diagnostics_fetched
→ delete_started → delete_succeeded | delete_already_absent | delete_failed
→ case_finished
```

重复轮询到相同状态时只更新控制台，不重复写正文或整份响应到 `run-state.jsonl`。

`_poll_until_terminal()`：

- 使用注入的 `monotonic_fn` 计算经过时间；
- 每次 Prepare/Create/Poll 前检查共享 `RunControl`；Task 已创建后收到停止信号时抛出
  受控 `RunInterrupted`，由 `finally` 删除；
- 每次调用 Adapter 前检查是否超过 `poll_policy.timeout_seconds`；
- 只对 `queued/processing` 睡眠；
- 未知状态在 `TaskSnapshot` 解析阶段转成 `ContractError`；
- `TASK_NOT_READY` 只允许 Result 提前查询专项测试处理，正常 Runner 不提前获取 Result。

`PreparedCase.safe_metadata` 严格限制为排障元数据：Public 只放有序 `asset_ids` 和数量，
Internal 只放消息数与 UTF-8 字节数；不得放媒体路径、聊天正文、Preferences 或完整 Payload。
这样 Public 在 CreateTask 前失败时仍能留下孤立 Asset ID 供后端排查，同时不把输入正文写入
`run-state.jsonl`。

稳定负向预期只比较 `expect.business_error_code` 与实际稳定 code。匹配时 Case 状态为
`completed`，但仍保留 `error.json` 作为协议证据；不匹配或预期错误未出现时为 `failed`。
幂等冲突专项在第一次 Create 已得到 Task 后才触发第二次冲突，Adapter 必须通过
`BusinessError.task_id_to_cleanup` 把首个 Task ID 交回 Runner，保证 `finally` 仍能删除。

- [ ] **Step 5: 增加 rejected、failed、timeout、unknown status 测试**

同时增加“预期稳定错误算协议完成”“预期错误未出现则失败”“幂等冲突仍删除首个 Task”、
“停止信号在下一检查点中断并删除”、
“Result 失败仍取 Diagnostics”“Diagnostics 失败仍删除”“Delete 抛异常时返回
`cleanup_pending` 而不是中断整个 Batch”等测试。

```bash
python -m unittest tests.unit.test_runner -v
```

Expected: all Runner tests PASS，FakeAdapter 断言调用顺序固定。

- [ ] **Step 6: 提交 Runner**

```bash
git add src/aidating_eval/domain.py src/aidating_eval/ports.py src/aidating_eval/runner.py tests/helpers.py tests/unit/test_runner.py
git commit -m "feat: add shared task runner with guaranteed cleanup"
```

---

## Task 7: 公开身份 Session、Reply Preferences 与 Gateway 健康检查

**Files:**
- Create: `src/aidating_eval/adapters/__init__.py`
- Create: `src/aidating_eval/adapters/public_e2e.py`
- Create: `tests/unit/test_public_session.py`
- Create: `tests/unit/test_public_preferences.py`
- Modify: `src/aidating_eval/domain.py`
- Modify: `src/aidating_eval/public_gateway.py`

**Interfaces:**
- Produces: `SessionTokens`、`DoctorCheck`、`PublicE2EAdapter.create_session()`、`refresh_session()`、`get_me()`、`ensure_preferences()`、`doctor()`。
- Consumes: `PublicGatewayClient`、`Settings`。

- [ ] **Step 1: 写身份调用顺序失败测试**

```python
# tests/unit/test_public_session.py
import unittest

from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from tests.helpers import FakePublicGateway


class PublicSessionTests(unittest.TestCase):
    def test_create_session_then_get_me(self):
        gateway = FakePublicGateway(
            responses=[
                {
                    "user_id": "user-1",
                    "access_token": "access-1",
                    "expires_time": 1787558400000,
                    "refresh_token": "refresh-1",
                    "refresh_expires_time": 1790064000000,
                    "is_new_user": True,
                },
                {"user_id": "user-1"},
            ]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway)
        adapter.prepare_run(adapter.test_context())
        self.assertEqual(
            ["CreateAnonymousSession", "GetMe"],
            [call.method_name for call in gateway.calls],
        )
        self.assertNotIn("access-1", repr(adapter.session_tokens))

    def test_refresh_replaces_both_tokens_atomically(self):
        gateway = FakePublicGateway.refresh_scenario()
        adapter = PublicE2EAdapter.for_test(gateway=gateway)
        adapter.prepare_run(adapter.test_context())
        adapter.refresh_session()
        self.assertEqual("access-2", adapter.session_tokens.access_token)
        self.assertEqual("refresh-2", adapter.session_tokens.refresh_token)
```

```python
# tests/unit/test_public_preferences.py
import unittest

from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from tests.helpers import FakePublicGateway


class PublicPreferencesTests(unittest.TestCase):
    def test_reply_reads_updates_and_confirms_preferences_before_media(self):
        gateway = FakePublicGateway.preferences_update_scenario()
        adapter = PublicE2EAdapter.for_test(gateway=gateway)
        adapter.prepare_run(adapter.test_context())
        adapter.prepare_case(adapter.reply_case(), adapter.test_context())
        methods = [call.method_name for call in gateway.calls]
        self.assertEqual(
            ["GetUserPreferences", "UpdateUserPreferences", "GetUserPreferences"],
            [name for name in methods if "Preferences" in name],
        )
        self.assertLess(
            methods.index("GetUserPreferences"),
            methods.index("GetMediaUploadConfig"),
        )

    def test_analysis_never_reads_or_updates_reply_preferences(self):
        gateway = FakePublicGateway.analysis_prepare_scenario()
        adapter = PublicE2EAdapter.for_test(gateway=gateway)
        adapter.prepare_run(adapter.test_context())
        adapter.prepare_case(adapter.analysis_case(), adapter.test_context())
        self.assertFalse(
            any("Preferences" in call.method_name for call in gateway.calls)
        )
```

- [ ] **Step 2: 运行测试确认公开 Adapter 尚未实现**

```bash
python -m unittest tests.unit.test_public_session tests.unit.test_public_preferences -v
```

Expected: FAIL with missing `PublicE2EAdapter`。

- [ ] **Step 3: 实现内存 Session 模型和身份方法**

```python
# addition to src/aidating_eval/domain.py
class DoctorStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    DEFERRED = "DEFERRED"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: DoctorStatus
    safe_message: str


@dataclass(frozen=True)
class SessionTokens:
    user_id: str = field(repr=False)
    access_token: str = field(repr=False)
    access_expires_time: int
    refresh_token: str = field(repr=False)
    refresh_expires_time: int
```

`PublicE2EAdapter.prepare_run()`：

1. 使用 `tool.identity.IdentityService/CreateAnonymousSession`；
2. `params` 只含 `consent_policy_version`；
3. 原子构造完整 `SessionTokens`，不先写半组 Token；
4. 使用新 Access Token 调用 `GetMe`；
5. 确认 `GetMe.user_id` 与 Session 返回一致；
6. 不把 User ID 主动放入后续 `params`。

`refresh_session()`：

1. 使用 `tool.identity.IdentityService/RefreshSession`；
2. Refresh Token 放 `params.refresh_token`，请求不带 Access Token；
3. 成功后整体替换 Token 对；
4. 再次 `GetMe` 验证新 Access Token；
5. `UNAUTHENTICATED` 终止 E2E Run，不无限刷新。

`doctor()`：

- `GET https://gateway.spark-jam.top/healthz` 必须为 HTTP 200；
- `AIDATING_E2E_FIXTURE_ROOT` 必须存在、可读，且 Artifact 根目录可创建私有文件；
- 只返回 `DoctorCheck(check_name, PASS|FAIL|DEFERRED, safe_message)`；
- 默认不创建匿名 Session；真实身份检查由 staging smoke 执行。
- COS 主机只有调用 `PrepareMediaUpload` 后才知道；为保持 doctor 无写入，它把 COS 连通性
  标记为 `DEFERRED`，由首条真实 Media Smoke 验证，不能在 doctor 中伪造 PASS。

- [ ] **Step 4: 实现 Reply Preferences 乐观并发更新**

`ensure_preferences()` 只由 Reply Case 调用，并且必须早于任何 Media 请求：

1. `GetUserPreferences` 读取 `dating_goal/your_voice/version/preferences_complete`；
2. 已匹配且 `preferences_complete=true` 时不更新；
3. 不匹配时调用 `UpdateUserPreferences`，首次版本使用 `expected_version=0`，否则使用读取值；
4. 更新请求使用稳定 `client_request_id`，网络结果未知时只复用原请求一次；
5. `PREFERENCES_VERSION_CONFLICT` 时重新 Get 并最多再 Update 一次；
6. 再次 Get，只有目标值匹配且 `preferences_complete=true` 才继续 Media；
7. `FEATURE_NOT_READY` 作为 Reply E2E 环境阻塞直接返回，禁止继续上传截图。

Analysis Case 的 `prepare_case()` 不得调用任何 Preferences 方法。

- [ ] **Step 5: 增加身份与 Preferences 边界测试**

覆盖无 Token Header、过期刷新、User ID 不一致、无需更新、版本冲突重试一次、重复冲突
失败、更新后仍不完整、Analysis 零 Preferences 调用。

```bash
python -m unittest tests.unit.test_public_session tests.unit.test_public_preferences -v
```

Expected: all tests PASS。

- [ ] **Step 6: 提交公开身份与 Preferences 能力**

```bash
git add src/aidating_eval/domain.py src/aidating_eval/public_gateway.py src/aidating_eval/adapters/__init__.py src/aidating_eval/adapters/public_e2e.py tests/unit/test_public_session.py tests/unit/test_public_preferences.py tests/helpers.py
git commit -m "feat: add public session and reply preferences"
```

---

## Task 8: 已脱敏截图只读校验与私密 Media Upload

**Files:**
- Create: `src/aidating_eval/media_validation.py`
- Create: `tests/unit/test_media_validation.py`
- Create: `tests/unit/test_public_media.py`
- Modify: `src/aidating_eval/adapters/public_e2e.py`
- Modify: `tests/helpers.py`

**Interfaces:**
- Produces: `inspect_media(source) -> InspectedMedia`（`content` 使用 `repr=False`）、`validate_against_media_config(media, config) -> None`、`PublicE2EAdapter.upload_media(case) -> tuple[str, ...]`。
- Consumes: `PublicGatewayClient`、`RequestsTransport.put_bytes()`、Pillow。

- [ ] **Step 1: 写图片处理失败测试**

```python
# tests/unit/test_media_validation.py
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from aidating_eval.errors import CaseValidationError
from aidating_eval.media_validation import inspect_media


class MediaValidationTests(unittest.TestCase):
    def test_rejects_exif_without_modifying_source_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jpg"
            image = Image.new("RGB", (1200, 800), "white")
            exif = Image.Exif()
            exif[0x010E] = "private metadata"
            image.save(source, exif=exif)
            original = source.read_bytes()
            with self.assertRaises(CaseValidationError):
                inspect_media(source)
            self.assertEqual(original, source.read_bytes())

    def test_accepts_clean_image_and_uses_detected_mime(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clean.bin"
            Image.new("RGB", (1200, 800), "white").save(source, format="JPEG")
            media = inspect_media(source)
            self.assertEqual("image/jpeg", media.content_type)
            self.assertEqual(source.stat().st_size, media.size_bytes)
            self.assertEqual(source.read_bytes(), media.content)
```

- [ ] **Step 2: 写 Media 顺序与签名保密失败测试**

```python
# tests/unit/test_public_media.py
import unittest

from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from tests.helpers import FakePublicGateway, FakeTransport


class PublicMediaTests(unittest.TestCase):
    def test_prepare_put_complete_preserves_case_order(self):
        gateway = FakePublicGateway.media_scenario(asset_ids=["asset-2", "asset-1"])
        transport = FakeTransport.put_successes(2)
        adapter = PublicE2EAdapter.for_test(gateway=gateway, transport=transport)
        asset_ids = adapter.upload_media(adapter.two_image_case())
        self.assertEqual(("asset-2", "asset-1"), asset_ids)
        self.assertEqual(2, len(transport.put_calls))
        self.assertEqual(
            ["PrepareMediaUpload", "CompleteMediaUpload", "PrepareMediaUpload", "CompleteMediaUpload"],
            [call.method_name for call in gateway.media_calls],
        )

    def test_signed_url_is_absent_from_transport_error(self):
        transport = FakeTransport.put_failure("https://cos.test/object?signature=secret")
        with self.assertRaises(Exception) as caught:
            transport.put_bytes(
                "https://cos.test/object?signature=secret",
                {"Content-Type": "image/jpeg"},
                b"bytes",
            )
        self.assertNotIn("signature=secret", str(caught.exception))
```

- [ ] **Step 3: 运行测试确认 Media 能力缺失**

```bash
python -m unittest tests.unit.test_media_validation tests.unit.test_public_media -v
```

Expected: FAIL with missing functions。

- [ ] **Step 4: 实现只读媒体校验**

`inspect_media()` 必须：

- 通过 Pillow 解码并识别真实 MIME，不信任扩展名；
- 不缩放、不裁切、不重编码、不覆盖源文件；
- 发现 EXIF 或无法识别的图片时本地失败，要求测试人员重新提供脱敏 Fixture；
- 单次读取原始文件为内存 `bytes`，通过 `BytesIO` 完成格式/元数据校验，并返回
  `content/content_type/size_bytes`；Transport 直接上传这组 `content`，避免校验后文件被替换；
- 不把绝对路径、图片内容或散列值输出到控制台。

`validate_against_media_config()` 在 Run 已取得动态配置后检查 MIME、单图字节和整组数量；
`validate` 命令只执行 `inspect_media()` 并输出本地类型/大小，不伪称已通过实时服务配置。

- [ ] **Step 5: 实现动态 Media 链路**

`upload_media()`：

1. 每个 Run 首次调用 `GetMediaUploadConfig`，在 `config_cache_ttl_seconds` 内复用；
2. 按服务端 `min_asset_count/max_asset_count/allowed_content_types/max_size_bytes` 校验；
3. 按 Case 数组顺序逐张只读校验；
4. `PrepareMediaUpload` 使用当前图片的 `content_type/size_bytes` 和稳定幂等键；
5. 校验 Prepare 回包的 `content_type/size_bytes` 与请求一致，图片大小同时不超过回包的
   `max_size_bytes`；`upload_method` 必须为 `PUT`，`upload_url` 必须为无 userinfo 的 HTTPS；
6. PUT 原值携带全部 `required_headers`，并设置 `allow_redirects=False`；
7. URL 过期时用同一媒体幂等键重新 Prepare 一次，不修改 URL；
8. `CompleteMediaUpload` 按服务端 `complete_retry` 退避，最多使用返回的 `max_attempts`；
9. 确认 Complete 响应 `status=uploaded`；
10. 直接追加返回 `asset_id`，禁止排序；
11. `asset_id` 重复时在 CreateTask 前本地失败。

每张图完成 PUT/Complete 后立即释放其内存 `bytes`，不同时缓存整组截图。

- [ ] **Step 6: 运行图片与 Media 测试**

```bash
python -m unittest tests.unit.test_media_validation tests.unit.test_public_media -v
```

Expected: all tests PASS，包括 JPEG/PNG/WebP、EXIF 拒绝；在 Fake 动态配置最大 9 张时，
1/9 张通过、10 张拒绝；同时覆盖大小边界和 URL 过期重试。

- [ ] **Step 7: 提交 Media 能力**

```bash
git add src/aidating_eval/media_validation.py src/aidating_eval/adapters/public_e2e.py tests/unit/test_media_validation.py tests/unit/test_public_media.py tests/helpers.py
git commit -m "feat: add validated ordered media upload flow"
```

---

## Task 9: PublicE2EAdapter 的 Reply / Analysis Task、Result 与 Delete

**Files:**
- Create: `tests/unit/test_public_reply_adapter.py`
- Create: `tests/unit/test_public_analysis_adapter.py`
- Modify: `src/aidating_eval/adapters/public_e2e.py`
- Modify: `src/aidating_eval/domain.py`
- Modify: `tests/helpers.py`

**Interfaces:**
- Produces: 完整 `PublicE2EAdapter`，支持 `E2EReplyCase` 与 `E2EAnalysisCase`。
- Consumes: Session、Preferences、Media、Runner、公开 Gateway Client。

- [ ] **Step 1: 写公开 Analysis 方法名与顺序失败测试**

```python
# tests/unit/test_public_analysis_adapter.py
import unittest

from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from aidating_eval.runner import CaseRunner
from tests.helpers import FakePublicGateway, MemoryArtifactStore


class PublicAnalysisAdapterTests(unittest.TestCase):
    def test_full_public_analysis_sequence_uses_current_method_names(self):
        gateway = FakePublicGateway.complete_analysis_scenario()
        adapter = PublicE2EAdapter.for_test(gateway=gateway)
        context = adapter.test_context()
        adapter.prepare_run(context)
        outcome = CaseRunner(
            adapter,
            MemoryArtifactStore(),
            sleep_fn=lambda _: None,
        ).execute(adapter.one_image_case(), context)
        self.assertEqual("completed", outcome.status)
        methods = [call.method_name for call in gateway.calls]
        self.assertIn("GetAnalysisTask", methods)
        self.assertIn("GetAnalysisResult", methods)
        self.assertNotIn("GetTask", methods)
        self.assertNotIn("GetTaskResult", methods)
        self.assertLess(methods.index("GetQuotaStatus"), methods.index("CreateAnalysisTask"))
        self.assertEqual("DeleteTaskData", methods[-3])
```

```python
# tests/unit/test_public_reply_adapter.py
import unittest

from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from aidating_eval.runner import CaseRunner
from tests.helpers import FakePublicGateway, MemoryArtifactStore


class PublicReplyAdapterTests(unittest.TestCase):
    def test_full_reply_sequence_places_preferences_before_media(self):
        gateway = FakePublicGateway.complete_reply_scenario()
        adapter = PublicE2EAdapter.for_test(gateway=gateway)
        context = adapter.test_context()
        adapter.prepare_run(context)
        outcome = CaseRunner(
            adapter,
            MemoryArtifactStore(),
            sleep_fn=lambda _: None,
        ).execute(adapter.reply_case(), context)
        self.assertEqual("completed", outcome.status)
        methods = [
            call.method_name
            for call in gateway.calls
            if call.params.get("task_id") != "dating_task_public_reply_probe"
        ]
        self.assertLess(methods.index("GetMe"), methods.index("GetUserPreferences"))
        self.assertLess(methods.index("GetUserPreferences"), methods.index("PrepareMediaUpload"))
        self.assertLess(methods.index("CompleteMediaUpload"), methods.index("CreateReplyTask"))
        self.assertLess(methods.index("CreateReplyTask"), methods.index("GetTask"))
        self.assertLess(methods.index("GetTask"), methods.index("GetTaskResult"))
        self.assertLess(methods.index("GetTaskResult"), methods.index("DeleteTaskData"))
```

Reply 的 `GetTask/GetTaskResult` 来自当前 V0.3.0 PRD 与公开协议评审稿；最新 staging 文档
只冻结了 Analysis 的新方法名。代码必须把两类方法映射分开，不能让 Analysis 回退到旧名。
Reply 真实联调前，将方法名确认列为阻塞检查；若后端也改为类型专属名称，只改 Reply 映射
和 Contract Fixture，不改 Runner。

在 Reply 上传媒体前执行只读 readiness：用工具永远不会生成的 sentinel `task_id` 分别调用
Reply 的 Task/Result 查询方法，两者返回 `NOT_FOUND` 表示方法存在且鉴权通过；
`FEATURE_NOT_READY`、未知方法或其他契约错误均在 Media 前终止。该探测不能证明
`CreateReplyTask` 一定可用，但能避免在已知查询接口未就绪时产生孤立 Asset。

- [ ] **Step 2: 运行测试确认两类 Task 流程未串联**

```bash
python -m unittest tests.unit.test_public_reply_adapter tests.unit.test_public_analysis_adapter -v
```

Expected: FAIL because Reply/Analysis Task、Result、Delete 尚未实现。

- [ ] **Step 3: 实现 Quota 读取但不伪造完整 Schema**

调用：

```python
data = self.gateway.call(
    "tool.subscription.SubscriptionService",
    "GetQuotaStatus",
    {
        "product_code": "dating_assistant",
        "entitlement_code": "quota.dating.analysis.monthly",
    },
    request_id="analysis-quota",
    auth_token=self.session_tokens.access_token,
)
```

强断言仅检查 `responses[0].data` 是对象。若存在 `remaining` 且为数字，则在
`remaining <= 0` 且 `unlimited is not True` 时提前标记 `QUOTA_EXHAUSTED`。脱敏后的实际
响应写入案例私有 `quota.json`，但未冻结字段只标记 observed，不从一次 staging 返回推导
永久 Schema。

- [ ] **Step 4: 实现按 `task_kind` 固定分派的 Task 方法**

方法映射必须是代码内显式常量，不从 Case 接收任意方法名：

```python
PUBLIC_METHODS = {
    TaskKind.REPLY: PublicTaskMethods(
        create="CreateReplyTask",
        get_task="GetTask",
        get_result="GetTaskResult",
        task_type="reply_generation",
        schema_version="dating.reply_generation.v1",
    ),
    TaskKind.ANALYSIS: PublicTaskMethods(
        create="CreateAnalysisTask",
        get_task="GetAnalysisTask",
        get_result="GetAnalysisResult",
        task_type="relationship_analysis",
        schema_version="dating.relationship_analysis.v1",
    ),
}
```

Reply `create_task()` 参数固定为：

```python
params = {
    "client_request_id": context.attempt_id,
    "asset_ids": list(prepared.payload["asset_ids"]),
    "locale": case.locale,
}
if case.requested_intent is not None:
    params["requested_intent"] = case.requested_intent
if case.background is not None:
    params["background"] = case.background
```

Preferences 不重复放入 `CreateReplyTask`。成功响应要求 `task_type=reply_generation`、
`status=queued`、`task_id` 为非空不透明字符串。

Analysis `create_task()` 请求字段固定：

```python
params = {
    "client_request_id": context.attempt_id,
    "asset_ids": list(prepared.payload["asset_ids"]),
    "locale": case.locale,
}
if case.other_person_name is not None:
    params["other_person_name"] = case.other_person_name
if case.background is not None:
    params["background"] = case.background
```

禁止加入 `app_id/user_id/person_id`。成功响应必须为：

- `task_type=relationship_analysis`；
- `status=queued`；
- `task_id` 非空不透明字符串。

`get_task()` 根据当前 Case 的冻结映射调用相应方法，将未知 `status` 转为
`ContractError`。Public PollPolicy 对两类 Task 固定：

```python
PollPolicy(
    timeout_seconds=90,
    initial_interval_seconds=1,
    steady_interval_seconds=2,
    switch_after_seconds=10,
)
```

Reply `get_result()` 检查：

- 外层 `task_type=reply_generation`；
- 外层 `schema_version=dating.reply_generation.v1`；
- `result.whats_happening` 存在；
- `result.roles` 为 1～2 个，`rank` 从 1 连续且唯一，并且恰有一个
  `is_best_fit=true`；
- 每个角色的 `top_pick` 是单个对象，`alternatives` 恰有 3 个；只检查
  `reply_id/text` 的存在和类型，不比较文案；
- `warnings` 缺失时按空列表处理，存在时必须为稳定结构；
- `case.expect.warning_codes` 必须全部出现；
- 不评价候选回复文案、语气质量或语义正确性。

Analysis `get_result()` 检查：

- 外层 `task_type=relationship_analysis`；
- 外层 `schema_version=dating.relationship_analysis.v1`；
- `result` 是对象；
- `result` 存在 `overview/chat_signals/key_events`；
- `overview.next_steps` 恰好 3 条且顺序为 `action/communication/observation`；
- `match_degree.status=unclear` 时 `score is None`；
- Signal 每类 0～3；Event 每类 0～3、总数最多 8；
- 不对正文语义形成断言。

两类结果都必须同时匹配固定方法映射的 Schema 和 `case.expect.result_schema`。后者若与
固定映射冲突，Loader 应已拒绝；Adapter 再做防御性检查。

- [ ] **Step 5: 实现 Delete 与不可访问验证**

`delete_task()`：

1. 调用 `DeleteTaskData`；
2. 要求 `logical_deleted is True`；
3. 保存 `object_deletion_status`，允许 `pending`；
4. 随后按当前 `task_kind` 分别调用对应 Task 与 Result 查询；
5. 两者均必须返回 `NOT_FOUND`；
6. 其他错误标记清理未确认；
7. Delete 网络结果未知时只使用同一 Task ID重试一次。

- [ ] **Step 6: 增加公开负向契约测试**

覆盖：

- Result 提前查询专项返回 `TASK_NOT_READY`，正常 Runner 不提前取 Result；
- `QUOTA_EXHAUSTED` 不重试；
- Reply 缺 Preferences 时不上传媒体；
- Reply 结果角色、Top Pick、Alternatives 数量不符时报告契约错误；
- `rejected` 不取 Result；
- `failed/retryable=false` 不重建；
- 相同 `client_request_id` 不同参数返回 `IDEMPOTENCY_CONFLICT`；
- Delete 后 Task/Result 为 `NOT_FOUND`；
- 未知 `interaction_metric` 字段保存但不做枚举强断言。

```bash
python -m unittest tests.unit.test_public_reply_adapter tests.unit.test_public_analysis_adapter -v
```

Expected: all tests PASS。

- [ ] **Step 7: 提交完整公开 Reply / Analysis E2E Adapter**

```bash
git add src/aidating_eval/adapters/public_e2e.py src/aidating_eval/domain.py tests/unit/test_public_reply_adapter.py tests/unit/test_public_analysis_adapter.py tests/helpers.py
git commit -m "feat: complete public reply and analysis e2e adapter"
```

---

## Task 10: InternalEvaluationAdapter 的 Reply / Analysis Evaluation 闭环

**Files:**
- Create: `src/aidating_eval/adapters/internal_evaluation.py`
- Create: `tests/unit/test_internal_reply_adapter.py`
- Create: `tests/unit/test_internal_analysis_adapter.py`
- Modify: `src/aidating_eval/domain.py`
- Modify: `src/aidating_eval/evaluation_gateway.py`
- Modify: `tests/helpers.py`

**Interfaces:**
- Produces: 完整 `InternalEvaluationAdapter`，支持 `EvaluationReplyCase` 与 `EvaluationAnalysisCase`。
- Consumes: `EvaluationGatewayClient`、Runner、Eval Case 校验。

- [ ] **Step 1: 写五方法调用顺序失败测试**

```python
# tests/unit/test_internal_analysis_adapter.py
import unittest

from aidating_eval.adapters.internal_evaluation import InternalEvaluationAdapter
from aidating_eval.runner import CaseRunner
from tests.helpers import FakeEvaluationGateway, MemoryArtifactStore


class InternalEvaluationAdapterTests(unittest.TestCase):
    def test_analysis_evaluation_runs_result_diagnostics_and_delete(self):
        gateway = FakeEvaluationGateway.complete_analysis_scenario()
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        outcome = CaseRunner(
            adapter,
            MemoryArtifactStore(),
            sleep_fn=lambda _: None,
        ).execute(adapter.valid_case(), adapter.test_context())
        self.assertEqual("completed", outcome.status)
        self.assertEqual(
            [
                "CreateAnalysisEvaluationTask",
                "GetAnalysisEvaluationTask",
                "GetAnalysisEvaluationTask",
                "GetAnalysisEvaluationResult",
                "GetEvaluationDiagnostics",
                "DeleteAnalysisEvaluationTaskData",
            ],
            [call.method_name for call in gateway.calls],
        )

    def test_request_maps_self_to_user_and_omits_reply_fields(self):
        gateway = FakeEvaluationGateway.create_only()
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        case = adapter.valid_case_with_self()
        adapter.create_task(
            case,
            adapter.prepare_case(case, adapter.test_context()),
            adapter.test_context(),
        )
        params = gateway.calls[0].params
        self.assertEqual("user", params["transcript"]["messages"][1]["speaker"])
        for field in ("background", "dating_goal", "your_voice", "requested_intent"):
            self.assertNotIn(field, params)
```

```python
# tests/unit/test_internal_reply_adapter.py
import unittest

from aidating_eval.adapters.internal_evaluation import InternalEvaluationAdapter
from aidating_eval.runner import CaseRunner
from tests.helpers import FakeEvaluationGateway, MemoryArtifactStore


class InternalReplyAdapterTests(unittest.TestCase):
    def test_reply_evaluation_runs_result_diagnostics_and_delete(self):
        gateway = FakeEvaluationGateway.complete_reply_scenario()
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        outcome = CaseRunner(
            adapter,
            MemoryArtifactStore(),
            sleep_fn=lambda _: None,
        ).execute(adapter.valid_reply_case(), adapter.test_context())
        self.assertEqual("completed", outcome.status)
        self.assertEqual(
            [
                "CreateReplyEvaluationTask",
                "GetReplyEvaluationTask",
                "GetReplyEvaluationTask",
                "GetReplyEvaluationResult",
                "GetEvaluationDiagnostics",
                "DeleteReplyEvaluationTaskData",
            ],
            [call.method_name for call in gateway.calls],
        )

    def test_reply_request_contains_only_confirmed_reply_fields(self):
        gateway = FakeEvaluationGateway.create_only()
        adapter = InternalEvaluationAdapter.for_test(gateway=gateway)
        case = adapter.valid_reply_case()
        adapter.create_task(
            case,
            adapter.prepare_case(case, adapter.test_context()),
            adapter.test_context(),
        )
        params = gateway.calls[0].params
        self.assertEqual("serious_relationship", params["dating_goal"])
        self.assertEqual("warm_direct", params["your_voice"])
        self.assertNotIn("app_id", params)
        self.assertNotIn("user_id", params)
```

- [ ] **Step 2: 运行测试确认内部 Adapter 未实现**

```bash
python -m unittest tests.unit.test_internal_reply_adapter tests.unit.test_internal_analysis_adapter -v
```

Expected: FAIL with missing `InternalEvaluationAdapter`。

- [ ] **Step 3: 实现创建请求与幂等规则**

`prepare_case()` 生成发送用 Transcript，所有消息严格只含：

```python
{
    "message_id": message.message_id,
    "message_type": "text",
    "speaker": message.speaker,
    "text": message.text,
}
```

内部方法也采用固定映射，Case 不得提供方法名：

```python
EVALUATION_METHODS = {
    TaskKind.REPLY: EvaluationMethods(
        create="CreateReplyEvaluationTask",
        get_task="GetReplyEvaluationTask",
        get_result="GetReplyEvaluationResult",
        delete="DeleteReplyEvaluationTaskData",
        task_type="reply_generation",
        schema_version="dating.reply_generation.v1",
    ),
    TaskKind.ANALYSIS: EvaluationMethods(
        create="CreateAnalysisEvaluationTask",
        get_task="GetAnalysisEvaluationTask",
        get_result="GetAnalysisEvaluationResult",
        delete="DeleteAnalysisEvaluationTaskData",
        task_type="relationship_analysis",
        schema_version="dating.relationship_analysis.v1",
    ),
}
```

`create_task()` 先生成共用参数：

```python
params = {
    "case_id": case.case_id,
    "run_id": context.run_id,
    "client_request_id": context.attempt_id,
    "locale": case.locale,
    "transcript": {
        "schema_version": "dating.transcript.v1",
        "messages": list(prepared.payload["messages"]),
    },
}
```

Reply 再加入 `dating_goal/your_voice` 和可选 `requested_intent/background`，调用
`CreateReplyEvaluationTask`；Analysis 不允许加入这些字段，调用
`CreateAnalysisEvaluationTask`。顶层与 `params.client_request_id` 使用同一
`attempt_id`。网络结果未知的创建重试复用同一参数；用户重新运行 Case 时生成新的
`attempt_id`。

Create 顶层 `reason` 分别固定为 `automated Reply evaluation` 与
`automated Analysis evaluation`，Case 不可覆盖。

受控负向 Case 在这一层的最后一步应用枚举变体；除幂等专项外，一次只允许一种变体。
`create_task()` 对 `IDEMPOTENCY_SAME/CONFLICT` 发起两次调用，第二次复用首个
`params.client_request_id`：同输入必须返回相同 `task_id` 后继续正常轮询；不同输入必须
返回 `IDEMPOTENCY_CONFLICT`，并在抛出的 `BusinessError.task_id_to_cleanup` 中携带第一
次创建的 Task ID，交由 Runner 的 `finally` 删除。普通重复运行永远生成新 key。

成功响应必须包含非空 `task_id`、`status=queued`，并按类型要求
`reply_generation/relationship_analysis`。

- [ ] **Step 4: 实现 Task、Result 和 Diagnostics**

`get_task()`：

- Reply 调用 `GetReplyEvaluationTask`，Analysis 调用 `GetAnalysisEvaluationTask`；
- 识别 `queued/processing/succeeded/rejected/failed`；
- Task 查询必须返回显式状态；`TASK_NOT_READY` 只在 Result 提前查询专项中作为预期业务错误；
- PollPolicy 固定为 3 秒间隔、240 秒上限。

Reply `get_result()`：

- 调用 `GetReplyEvaluationResult`；
- 要求 `schema_version=dating.reply_generation.v1`；
- 要求 `whats_happening`、`roles` 1～2 个、唯一连续 `rank`、恰好一个最佳角色、每角色
  一个 `top_pick` 与 3 个 `alternatives`；只检查 `reply_id/text` 的存在和类型；
- `warnings` 存在时必须为稳定列表；
- `case.expect.warning_codes` 必须全部出现；
- 对安全 Case 只检查 `SAFETY_DEGRADED` 和 Diagnostics 稳定策略 code，不判断文案；
- 不读取 Prompt、思维链或模型原始响应。

Analysis `get_result()`：

- 调用 `GetAnalysisEvaluationResult`；
- 要求 `schema_version=dating.relationship_analysis.v1`；
- 要求 `overview/chat_signals/key_events`；
- 301～500 条消息时要求：

```python
scope = result["analysis_scope"]
assert scope["truncated_to_recent_300"] is True
assert scope["analyzed_message_count"] == 300
assert "TRUNCATED_TO_RECENT_300" in result.get("warnings", [])
```

- 构造最近 300 条 `message_id` 集合，递归收集全部 `evidence_message_ids`，发现旧 ID 时抛 `ContractError`；
- 4～300 条时不强制要求截断 warning。
- `case.expect.warning_codes` 必须全部出现。

`get_diagnostics()` 对两类 Task 都调用 `GetEvaluationDiagnostics`，只保存后端允许字段，
不要求 Prompt 正文或模型原始输出。安全降级 Case 同时断言后端已确认的策略 code；这是
确定性协议验证，不是 AI Judge。

Diagnostics 中的稳定策略 code 必须包含 `case.expect.policy_codes`；只做 code 集合包含判断。

允许保存的诊断字段使用显式白名单：`case_id`、`run_id`、`model_alias`、
`prompt_version`、`policy_version`、`result_schema_version`、`policy_codes`、
`validation_codes`、`retry_count`、`input_tokens`、`output_tokens`、`model_latency_ms`。
响应出现其他字段时可在内存中做契约告警，但不得未经审查直接落盘，尤其禁止任何正文、
Prompt、候选回复或模型原始输出。

- [ ] **Step 5: 实现稳定错误码策略**

```python
NON_RETRYABLE_CODES = {
    "UNAUTHENTICATED",
    "PERMISSION_DENIED",
    "FEATURE_NOT_READY",
    "INPUT_INVALID",
    "IDEMPOTENCY_CONFLICT",
    "NO_VALID_CONVERSATION",
    "INSUFFICIENT_MESSAGES",
    "MODEL_OUTPUT_INVALID",
}
```

- `EVALUATION_LIMIT_EXCEEDED` 由 Scheduler 读取 `retry_after_seconds`；
- `NOT_FOUND` 在正常查询时是失败，在删除后契约验证时是成功；
- Delete/cleanup 本身返回 `NOT_FOUND` 时记录 `already_absent` 并视为隐私清理已满足，但
  另记契约告警，不能伪写成服务端明确返回的删除成功；
- `INTERNAL` 只在响应明确 `retryable=true` 时允许重建一次；
- 未知 code 记录原值并标记契约失败；
- 不根据 `message` 判断。

- [ ] **Step 6: 实现删除**

- Reply 调用 `DeleteReplyEvaluationTaskData`，Analysis 调用 `DeleteAnalysisEvaluationTaskData`；
- `reason="evaluation case completed"`；
- 成功响应视为清理完成；
- 删除网络结果未知时用相同 Task ID 重试一次；
- 专门的删除契约测试再调用 Task、Result、Diagnostics，三者都应为 `NOT_FOUND`；
- 任何查询都不打印 Result 正文。

- [ ] **Step 7: 实现无副作用 doctor 鉴权探测**

`doctor()` 分别调用 `GetReplyEvaluationTask` 和 `GetAnalysisEvaluationTask`，使用不可能由
正常工具生成的两个探测 Task ID：

- `NOT_FOUND` 表示鉴权和权限通过；
- `UNAUTHENTICATED`、`PERMISSION_DENIED` 表示失败；
- `FEATURE_NOT_READY` 表示部署状态阻塞；
- 其他响应保存稳定 code，不尝试创建 Task。

- [ ] **Step 8: 运行内部 Adapter 全部测试**

新增 Reply 结构、安全 warning/策略 code、4/300 条边界、Analysis 301/500 条截断、旧
evidence ID、两类未知 Schema、受控负向变体、幂等同输入/冲突、两类 Delete 幂等和
doctor 双探测测试。

```bash
python -m unittest tests.unit.test_internal_reply_adapter tests.unit.test_internal_analysis_adapter -v
```

Expected: all tests PASS。

- [ ] **Step 9: 提交内部 Reply / Analysis Evaluation Adapter**

```bash
git add src/aidating_eval/adapters/internal_evaluation.py src/aidating_eval/domain.py src/aidating_eval/evaluation_gateway.py tests/unit/test_internal_reply_adapter.py tests/unit/test_internal_analysis_adapter.py tests/helpers.py
git commit -m "feat: add internal reply and analysis evaluation adapter"
```

---

## Task 11: Eval 共享限流器与并发批量调度

**Files:**
- Create: `src/aidating_eval/scheduling.py`
- Create: `tests/unit/test_scheduling.py`
- Modify: `src/aidating_eval/http.py`
- Modify: `src/aidating_eval/runner.py`
- Modify: `tests/helpers.py`

**Interfaces:**
- Produces: `SlidingWindowRateLimiter.acquire()`、`CreatePacer.acquire()`、`SharedCooldown.defer()`、`BatchRunner.run(cases) -> list[CaseOutcome]`。
- Consumes: `CaseRunner` Factory、Task 6 的 `RunControl`、Eval Settings。

- [ ] **Step 1: 写固定时间限流失败测试**

```python
# tests/unit/test_scheduling.py
import unittest

from aidating_eval.scheduling import (
    CreatePacer,
    SharedCooldown,
    SlidingWindowRateLimiter,
)
from tests.helpers import FakeClock


class SchedulingTests(unittest.TestCase):
    def test_create_pacer_keeps_two_second_spacing(self):
        clock = FakeClock()
        pacer = CreatePacer(2.0, monotonic_fn=clock.monotonic, sleep_fn=clock.sleep)
        pacer.acquire()
        pacer.acquire()
        pacer.acquire()
        self.assertEqual([2.0, 2.0], clock.sleeps)

    def test_gateway_window_never_exceeds_120_calls(self):
        clock = FakeClock()
        limiter = SlidingWindowRateLimiter(
            max_calls=120,
            period_seconds=60,
            monotonic_fn=clock.monotonic,
            sleep_fn=clock.sleep,
        )
        for _ in range(121):
            limiter.acquire()
        self.assertGreaterEqual(sum(clock.sleeps), 60)

    def test_server_retry_after_blocks_all_workers(self):
        clock = FakeClock()
        cooldown = SharedCooldown(
            monotonic_fn=clock.monotonic, sleep_fn=clock.sleep
        )
        cooldown.defer(12)
        cooldown.wait_if_needed()
        self.assertEqual([12], clock.sleeps)
```

- [ ] **Step 2: 运行测试确认 Scheduler 尚未实现**

```bash
python -m unittest tests.unit.test_scheduling -v
```

Expected: FAIL with missing classes。

- [ ] **Step 3: 实现线程安全限流器**

`SlidingWindowRateLimiter`：

- 用 `collections.deque[float]` 保存最近调用时间；
- 用 `threading.Condition` 保护队列；
- 清除 `now - timestamp >= period_seconds` 的记录；
- 窗口已满时睡到最早记录离开窗口；
- Internal Evaluation 的 Create、Task、Result、Diagnostics、Delete 共用同一个
  Admin Gateway 限流器；
- COS PUT 不计入 Admin Gateway 120/分钟，但仍受 HTTP timeout 限制。

公开 E2E 不套用 Admin Gateway 的 120 次/分钟限制；MVP 对公开流程固定串行执行，遇到
公开服务端稳定限流码时记录实际结果，不凭内部评测限额推导公开链路容量。

`CreatePacer`：

- 只在内部 Evaluation Create 前调用；
- 两次 Create 开始时间至少相隔 2 秒；
- `EVALUATION_LIMIT_EXCEEDED` 的服务端等待不减少该间隔。

`SharedCooldown`：

- 所有 Internal Worker 在每次 Admin Gateway 请求前调用 `wait_if_needed()`；
- 任意请求收到 `EVALUATION_LIMIT_EXCEEDED` 时，把安全解析后的
  `retry_after_seconds`（限制到 1～300 秒）写入共享 `blocked_until`；
- Create 使用完全相同的幂等请求重试一次；Task/Result/Diagnostics/Delete 使用相同
  `task_id` 重试一次；再次限流则保留稳定 code 并结束对应案例，不无限循环；
- Gateway Client 本身不静默重试，便于 Adapter 明确控制请求是否幂等。

- [ ] **Step 4: 实现 `BatchRunner`**

```python
class BatchRunner:
    def __init__(
        self,
        case_runner_factory,
        max_workers: int,
        create_pacer: CreatePacer,
        run_control: RunControl,
    ) -> None:
        if not 1 <= max_workers <= 5:
            raise ValueError("max_workers 必须在 1 到 5 之间")
        self.case_runner_factory = case_runner_factory
        self.max_workers = max_workers
        self.create_pacer = create_pacer
        self.run_control = run_control

    def run(self, cases, context_factory):
        from concurrent.futures import ThreadPoolExecutor

        def execute(case):
            if not self.run_control.may_start_new_case():
                return CaseOutcome.not_started(case.case_id, "RUN_STOP_REQUESTED")
            runner = self.case_runner_factory(self.create_pacer)
            return runner.execute(case, context_factory(case))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            outcomes = list(executor.map(execute, cases))
        return outcomes
```

实现时确保每个 Worker 通过 `RequestsTransport` 的 thread-local Session 调用，Artifact Store 的共享事件文件有锁。返回顺序保持数据集输入顺序。
`context_factory(case)` 必须复用批次级 `run_id`，并把 `case.task_kind` 写入
`RunContext.task_kind`；Adapter 依据该字段选择固定方法映射，因此混合 Reply/Analysis
并发时不依赖共享“当前 Case”可变状态。

`RunControl` 使用线程安全 `Event`：SIGINT/SIGTERM、`UNAUTHENTICATED`、
`PERMISSION_DENIED` 或无法继续的配置错误会设置停止原因。已提交到线程池但尚未开始的
Case 在任何远端请求前返回 `RUN_STOP_REQUESTED`；正在轮询的 Case 在下一检查点停止业务
步骤并进入 `finally` 删除。停止原因不包含服务端自由文本。

- [ ] **Step 5: 加入批次预算预检查**

Run 前计算并打印但不保存正文：

- Case 数；
- 本批正常 Create 数，以及每 Case 最多一次明确 retryable 重建后的最坏 Create 数；
- 消息总数；
- UTF-8 正文字节；
- 最大并发；
- 按受控变体和最坏一次重建展开后计算 Create 请求数和输入字节；任一超过 1,000 或
  268,435,456 时直接拒绝；
- 工具不猜测服务账号当日其他 Run 已消耗额度，服务端仍是最终权威。

- [ ] **Step 6: 处理服务端 retry_after**

Fake Gateway 在 Create 或 Poll 返回 `BusinessError("EVALUATION_LIMIT_EXCEEDED")` 且携带
安全的 `retry_after_seconds` 数据时：

- Scheduler 暂停所有新的 Admin Gateway 请求；
- 等待值限制在 1～300 秒，缺失或异常值按 300 秒处理；
- 等待后只重试当前幂等请求一次；
- 不高频循环。

- [ ] **Step 7: 运行 Scheduler 与 Runner 回归**

```bash
python -m unittest tests.unit.test_scheduling tests.unit.test_runner -v
```

Expected: all tests PASS，无真实睡眠。

- [ ] **Step 8: 提交批量调度**

```bash
git add src/aidating_eval/scheduling.py src/aidating_eval/http.py src/aidating_eval/runner.py tests/unit/test_scheduling.py tests/helpers.py
git commit -m "feat: add bounded evaluation batch scheduling"
```

---

## Task 12: CLI doctor、validate、run 与 cleanup

**Files:**
- Create: `src/aidating_eval/cli.py`
- Create: `tests/unit/test_cli.py`
- Modify: `src/aidating_eval/config.py`
- Modify: `src/aidating_eval/artifacts.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `dating-eval doctor|validate|run|cleanup`。
- Consumes: Config、Case Loader、Adapter、Runner、BatchRunner、Artifact Store。

- [ ] **Step 1: 写 CLI 解析和退出码失败测试**

```python
# tests/unit/test_cli.py
import unittest
from unittest.mock import patch

from aidating_eval.cli import main


class CliTests(unittest.TestCase):
    def test_validate_does_not_build_adapter_or_call_network(self):
        with patch("aidating_eval.cli.build_adapter") as build_adapter:
            code = main([
                "validate",
                "--mode",
                "eval",
                "--dataset",
                "tests/fixtures/cases/eval-mixed-valid.jsonl",
            ])
        self.assertEqual(0, code)
        build_adapter.assert_not_called()

    def test_unknown_mode_returns_configuration_exit_code(self):
        code = main(["doctor", "--mode", "unknown"])
        self.assertEqual(2, code)

    def test_e2e_cleanup_explains_in_memory_token_limit(self):
        code = main(["cleanup", "--run", "run-1"])
        self.assertEqual(4, code)
```

- [ ] **Step 2: 运行测试确认 CLI 尚未实现**

```bash
python -m unittest tests.unit.test_cli -v
```

Expected: FAIL with missing `main`。

- [ ] **Step 3: 使用 argparse 实现固定命令面**

`main()` 启动时调用 `load_dotenv(override=False)`：本地 `.env` 只补充当前 Shell 未设置的
变量，显式环境变量始终优先；`.env` 内容绝不回显。

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dating-eval")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "validate", "run"):
        command = subcommands.add_parser(name)
        command.add_argument("--mode", choices=("e2e", "eval"), required=True)
        if name in {"validate", "run"}:
            command.add_argument("--dataset", type=Path, required=True)
            command.add_argument("--case", dest="case_id")
    cleanup = subcommands.add_parser("cleanup")
    cleanup.add_argument("--run", dest="run_id", required=True)
    return parser
```

CLI 不提供 `judge/report/compare/gate/serve/ci/reprocess` 子命令。

- [ ] **Step 4: 实现命令行为**

`doctor`：

- 加载对应模式 Settings；
- E2E 检查 Health URL，不创建 Task；
- Eval 分别执行 Reply / Analysis 的只读 Task 鉴权探测；
- 每个检查只打印 `PASS/FAIL/DEFERRED + safe_message`；任一 FAIL 返回退出码 3，只有
  DEFERRED 不阻塞 doctor，但真实 Smoke 必须覆盖该检查。

`validate`：

- 不构建 Adapter、不发网络请求；
- 输出 Case 数、媒体数或消息数、预计 Task 和输入字节；
- 不打印聊天正文、文件内容或图片路径；媒体只显示 Case ID、数组下标、检测类型和字节数。
- E2E 只确认本地图片可解码、无 EXIF、类型和大小可读；动态服务端 Media 限制在 `run`
  获取 `GetMediaUploadConfig` 后二次校验。

`run`：

- 二次执行本地校验；
- 先校验完整数据集，再应用 `--case`，避免同一数据集因筛选参数不同而绕过坏行；
- 可选 `--case` 按完整 Case ID 精确筛选；0 个或多于 1 个匹配都返回输入错误；
- 创建 RunManifest 与私有 Artifact Store；
- E2E 调用一个 `CaseRunner` 串行执行；
- Eval 调用 `BatchRunner`；
- SIGINT/SIGTERM 设置停止接收新 Case 标志，等待正在运行的 finally 删除；
- 输出完成、失败、未完成、待清理数量。

`cleanup`：

- 从目标 Run 的 `manifest.json` 读取模式，并与 `run-state.jsonl` 交叉校验；用户不能通过
  参数把 Public Task 误送到 Internal Delete；
- Eval 从 `run-state.jsonl` 提取拥有 Task ID 且没有 `delete_succeeded` 或
  `delete_already_absent` 的记录；
- 根据 `run-state.jsonl` 中的 `task_kind` 调用
  `DeleteReplyEvaluationTaskData` 或 `DeleteAnalysisEvaluationTaskData`；
- 成功后追加 `delete_succeeded`；
- 目标已过期或已被 TTL 清除而返回 `NOT_FOUND` 时追加 `delete_already_absent`，同样停止重试；
- E2E 因 Token 不落盘返回退出码 4，并明确依赖当前进程 finally 与 TTL；
- 不以落盘 Token 绕过限制。

- [ ] **Step 5: 实现固定退出码**

```python
EXIT_OK = 0
EXIT_CASE_FAILURE = 1
EXIT_CONFIG_OR_INPUT = 2
EXIT_AUTH_OR_ENV = 3
EXIT_INCOMPLETE_OR_CLEANUP = 4
```

鉴权与权限错误全局停止对应 Run；单 Case 输入/业务失败不终止其他已经合法调度的 Eval Case。

- [ ] **Step 6: 运行 CLI 测试**

```bash
python -m unittest tests.unit.test_cli -v
dating-eval --help
dating-eval run --help
```

Expected: unit tests PASS；帮助只显示四类命令。

- [ ] **Step 7: 提交 CLI**

```bash
git add src/aidating_eval/cli.py src/aidating_eval/config.py src/aidating_eval/artifacts.py tests/unit/test_cli.py README.md
git commit -m "feat: add lightweight dual-flow cli"
```

---

## Task 13: 脱敏 Case、契约 Fixture 与 Fake Integration

**Files:**
- Create: `datasets/e2e-smoke/reply-single.json`
- Create: `datasets/e2e-smoke/reply-multi.json`
- Create: `datasets/e2e-smoke/analysis-single.json`
- Create: `datasets/e2e-smoke/analysis-multi.json`
- Create: `datasets/eval-smoke.jsonl`
- Modify: `datasets/media/README.md`
- Create: `tests/fixtures/public/*.json`
- Create: `tests/fixtures/evaluation/*.json`
- Create: `tests/integration/test_public_e2e_flow.py`
- Create: `tests/integration/test_internal_eval_flow.py`
- Create: `tests/integration/__init__.py`

**Interfaces:**
- Produces: 可提交的脱敏数据模板、完整 Fake 双链路验证。
- Consumes: 所有实现模块。

- [ ] **Step 1: 建立脱敏契约 Fixture**

公开 Fixture 至少包含：

```text
identity-create-success.json
identity-get-me-success.json
preferences-get-incomplete.json
preferences-update-success.json
preferences-get-complete.json
media-config-success.json
media-prepare-success.json
media-complete-success.json
quota-observed-success.json
reply-create-success.json
reply-task-processing.json
reply-task-succeeded.json
reply-result-success.json
analysis-create-success.json
analysis-task-processing.json
analysis-task-succeeded.json
analysis-result-success.json
analysis-delete-success.json
not-found.json
```

内部 Fixture 至少包含：

```text
reply-evaluation-create-success.json
reply-evaluation-task-processing.json
reply-evaluation-task-succeeded.json
reply-evaluation-result-success.json
analysis-evaluation-create-success.json
analysis-evaluation-task-processing.json
analysis-evaluation-task-succeeded.json
analysis-evaluation-result-success.json
evaluation-diagnostics-success.json
evaluation-delete-success.json
evaluation-limit-exceeded.json
```

所有 Fixture：

- 使用虚构 ID；
- 不含真实聊天正文；
- 不含 Token、Key、签名 URL；
- 使用测试包装结构 `{"source":"documented|staging_observed","response":{...}}`，
  `FakeTransport` 只把 `response` 交给 Client，避免测试元数据混入真实 Wire Schema；
- `staging_observed` 只保留字段形状与稳定 code，所有正文、ID、时间和数值改为虚构值；
- `staging_observed` 不能升级为强 Schema 断言。

- [ ] **Step 2: 写完整公开 Fake Integration 测试**

```python
# tests/integration/test_public_e2e_flow.py
import unittest

from aidating_eval.runner import CaseRunner
from tests.helpers import build_public_fixture_adapter, MemoryArtifactStore


class PublicE2EIntegrationTests(unittest.TestCase):
    def test_identity_preferences_media_reply_result_delete(self):
        adapter, case, context = build_public_fixture_adapter("reply")
        adapter.prepare_run(context)
        outcome = CaseRunner(
            adapter,
            MemoryArtifactStore(),
            sleep_fn=lambda _: None,
        ).execute(case, context)
        self.assertEqual("completed", outcome.status)
        self.assertEqual("dating.reply_generation.v1", outcome.schema_version)
        self.assertTrue(outcome.cleanup.success)

    def test_identity_media_quota_analysis_result_delete(self):
        adapter, case, context = build_public_fixture_adapter("analysis")
        adapter.prepare_run(context)
        outcome = CaseRunner(
            adapter,
            MemoryArtifactStore(),
            sleep_fn=lambda _: None,
        ).execute(case, context)
        self.assertEqual("completed", outcome.status)
        self.assertEqual("dating.relationship_analysis.v1", outcome.schema_version)
        self.assertTrue(outcome.cleanup.success)
```

- [ ] **Step 3: 写内部 Batch Fake Integration 测试**

```python
# tests/integration/test_internal_eval_flow.py
import unittest

from tests.helpers import build_internal_batch_fixture


class InternalEvalIntegrationTests(unittest.TestCase):
    def test_mixed_reply_and_analysis_finish_in_input_order_and_delete(self):
        batch, cases, context_factory = build_internal_batch_fixture()
        outcomes = batch.run(cases, context_factory)
        self.assertEqual([case.case_id for case in cases], [o.case_id for o in outcomes])
        self.assertEqual({"reply", "analysis"}, {case.task_kind for case in cases})
        self.assertTrue(all(o.cleanup and o.cleanup.success for o in outcomes))
```

- [ ] **Step 4: 创建最小数据模板**

E2E Case 固定字段：

```json
{
  "schema_version": "aidating.e2e.case.v1",
  "case_id": "e2e-analysis-single-001",
  "task_kind": "analysis",
  "locale": "en-US",
  "media": [{"path": "media/analysis-single-01.png"}],
  "analysis": {
    "other_person_name": "Maya",
    "background": "Synthetic test conversation."
  },
  "expect": {
    "task_status": "succeeded",
    "result_schema": "dating.relationship_analysis.v1"
  }
}
```

另创建两个 Reply Case，严格包含 `preferences` 与 `reply`，并分别使用 1 张和 2～3 张
脱敏图片；两个 Analysis Case 不包含 `preferences`。这四个文件与 PRD 首批 E2E Smoke
一一对应。

Eval JSONL 至少包含：

- Reply 4 条消息成功 Case；
- Analysis 4 条消息成功 Case；
- Reply 明确边界安全降级 Case；
- Reply Prompt Injection 稳定策略 Case；
- Analysis 301 条截断 Case；
- 消息不足 `INPUT_INVALID` 受控变体；
- 幂等同输入与同 key 不同输入冲突专项 Case。

每个负向 Case 都从合法基础 Case 生成，明确 `negative_variant` 与稳定预期 code；数据集不
允许写入任意 `service_name/method_name/raw_params`。

真实媒体文件不提交仓库。`datasets/media/README.md` 说明文件命名、脱敏、EXIF 和本地放置规则。

- [ ] **Step 5: 运行全部默认测试**

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: Unit、Contract、Fake Integration 全部 PASS；staging 测试被明确 SKIP。

- [ ] **Step 6: 提交数据模板和 Integration 测试**

```bash
git add datasets tests/fixtures tests/integration
git commit -m "test: add sanitized dual-flow contract fixtures"
```

---

## Task 14: 真实 staging Smoke 与使用说明

**Files:**
- Create: `tests/staging/__init__.py`
- Create: `tests/staging/test_public_analysis_smoke.py`
- Create: `tests/staging/test_public_reply_readiness.py`
- Create: `tests/staging/test_public_reply_smoke.py`
- Create: `tests/staging/test_internal_reply_smoke.py`
- Create: `tests/staging/test_internal_analysis_smoke.py`
- Modify: `README.md`
- Modify: `tests/helpers.py`

**Interfaces:**
- Produces: 显式 opt-in 的真实联调测试和人工执行 Runbook。
- Consumes: 完整 CLI、两个 Adapter、脱敏本地数据。

- [ ] **Step 1: 写默认跳过的 staging 测试**

```python
# tests/staging/test_public_analysis_smoke.py
import os
import unittest


RUN_STAGING = os.getenv("AIDATING_RUN_STAGING_TESTS") == "1"


@unittest.skipUnless(RUN_STAGING, "需要显式开启 staging 测试")
class PublicAnalysisStagingTests(unittest.TestCase):
    def test_one_sanitized_case_reaches_result_and_delete(self):
        from tests.helpers import run_public_staging_case

        outcome = run_public_staging_case("e2e-analysis-single-001")
        self.assertEqual("completed", outcome.status)
        self.assertTrue(outcome.cleanup and outcome.cleanup.success)
```

内部 Reply 与 Analysis staging 测试使用相同 opt-in 开关，各只跑 1 条四消息合法 Case。
`test_public_reply_readiness.py` 不把当前未交付状态写成失败的成功链路：它只记录
Preferences / Reply 的稳定阻塞 code；后端宣告能力开放后，再将其升级为真实 Reply Smoke。
`test_public_reply_smoke.py` 额外要求 `AIDATING_RUN_PUBLIC_REPLY_STAGING=1`，未设置时始终
SKIP；后端完成外部 Gate 后才开启，并要求真实 Result/Delete 全闭环。

- [ ] **Step 2: 运行默认测试确认不会访问 staging**

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: staging tests SKIP；其他测试 PASS。

- [ ] **Step 3: 编写 Public E2E Runbook**

README 给出以下顺序，不包含任何真实 Secret：

```bash
cp .env.example .env
dating-eval doctor --mode e2e
dating-eval validate --mode e2e --dataset datasets/e2e-smoke
dating-eval run --mode e2e --dataset datasets/e2e-smoke --case e2e-analysis-single-001
```

运行前人工确认：

- 本地媒体已脱敏；
- `GetQuotaStatus` 有剩余额度或 `unlimited=true`；
- 只运行 1 条 Smoke；
- 运行结束 `DeleteTaskData` 成功；
- Task 和 Result 再查均为 `NOT_FOUND`；
- `object_deletion_status=pending` 只记录，不轮询 COS 物理删除。

当前不要把 `e2e-reply-*` 纳入真实通过标准。可以执行 readiness 检查：Preferences 返回
`FEATURE_NOT_READY/NOT_FOUND`，或 sentinel Task/Result 探测返回 `NOT_FOUND` 以外的结果，
都记录为“staging 能力未交付”，并确认在 Media Upload 前停止；不得把它统计为工具失败，
也不得用 Fake 结果替代真实结论。

后端开放后执行：

```bash
AIDATING_RUN_STAGING_TESTS=1 AIDATING_RUN_PUBLIC_REPLY_STAGING=1 \
python -m unittest tests.staging.test_public_reply_smoke -v
```

- [ ] **Step 4: 编写 Internal Eval Runbook**

```bash
dating-eval doctor --mode eval
dating-eval validate --mode eval --dataset datasets/eval-smoke.jsonl
dating-eval run --mode eval --dataset datasets/eval-smoke.jsonl --case eval-reply-happy-001
dating-eval run --mode eval --dataset datasets/eval-smoke.jsonl --case eval-analysis-happy-001
```

API Key 通过当前 Shell 环境注入。README 不提供带值的 `export` 示例，避免密钥进入 Shell History。

- [ ] **Step 5: 执行公开 staging Smoke**

前置环境配置齐全后运行：

```bash
AIDATING_RUN_STAGING_TESTS=1 \
python -m unittest tests.staging.test_public_analysis_smoke -v
```

Expected:

- Health、Session、GetMe 成功；
- Media 上传完成；
- Quota 可创建 Task；
- Task reached `succeeded`；
- Result Schema 为 `dating.relationship_analysis.v1`；
- Delete 成功且再次查询不可访问。

若 Quota 耗尽，结果记录为环境阻塞而不是工具缺陷。

- [ ] **Step 6: 执行内部 Reply / Analysis staging Smoke**

```bash
AIDATING_RUN_STAGING_TESTS=1 \
python -m unittest tests.staging.test_internal_reply_smoke tests.staging.test_internal_analysis_smoke -v
```

Expected:

- 鉴权通过；
- Reply 与 Analysis Task 各 reached `succeeded`；
- 两类 Result 和 Diagnostics 成功；
- 两类 Delete 成功；
- 不消耗用户 Subscription/Billing 权益。

若得到 `FEATURE_NOT_READY`，保留稳定 code 和时间，按内部接口部署阻塞处理，不切换 Mock 宣称成功。

- [ ] **Step 7: 扫描 Secret 与敏感产物**

```bash
if rg --hidden --no-ignore -n 'adm_key_[[:alnum:]]{16,}[.][[:alnum:]]{32,}|Bearer [[:alnum:]._=-]{16,}|access_token[^[:cntrl:]]{0,80}[[:alnum:]._=-]{16,}|refresh_token[^[:cntrl:]]{0,80}[[:alnum:]._=-]{16,}' \
  --glob '!.git/**' --glob '!.venv/**' --glob '!.env' --glob '!.env.*' .; then
  exit 1
fi
git check-ignore -q .env
```

Expected: 源码、测试、文档和 `artifacts/` 均无匹配，退出码 0。`.env`/`.env.*` 是允许的
本地 Secret 来源，因此不扫描内容，但必须另由 `git check-ignore .env` 证明不会进入 Git。

- [ ] **Step 8: 运行最终默认回归与编译检查**

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: compile exit 0；默认测试 0 failure，staging tests 为显式 SKIP。

- [ ] **Step 9: 提交 staging 测试和使用说明**

```bash
git add tests/staging tests/helpers.py README.md
git commit -m "docs: add staging smoke runbook and acceptance checks"
```

---

## 3. 任务依赖与建议执行批次

| 批次 | Tasks | 可交付结果 | Review Checkpoint |
|---|---|---|---|
| A | 1～3 | 可安装工程、安全配置、两种 Case Loader | 本地数据不发请求即可校验 |
| B | 4～6 | 脱敏产物、HTTP Client、共用 Runner | Fake Adapter 可证明 finally 删除 |
| C | 7～9 | 公开 Reply / Analysis E2E Adapter | Fake 覆盖 Identity/Preferences/Media/两类 Task/Result/Delete |
| D | 10～11 | 内部 Reply / Analysis Eval + 批量限流 | 混合 Fake Case 并发且不越限 |
| E | 12～13 | CLI、数据模板、双流程 Integration | 四命令可用，默认测试全绿 |
| F | 14 | 真实 staging 联调与 Runbook | Public Analysis、Internal Reply/Analysis 成功；Public Reply 阻塞证据明确 |

不并行修改同一核心文件。Tasks 1～6 顺序执行；Task 7～9 和 Task 10 可在端口冻结后由不同实现者开发，但主 Agent 必须在 Task 11 前统一检查类型签名。

---

## 4. PRD 覆盖矩阵

| PRD 能力 | 对应任务 | 验证证据 |
|---|---|---|
| FR-01 双模式配置隔离 | 2、12 | `test_config.py`、`doctor --mode` |
| FR-02 E2E JSON 与 Eval JSONL | 3、13 | `test_cases.py`、脱敏数据模板 |
| FR-03 PublicE2EAdapter | 7～9 | `test_public_*`、公开 staging smoke |
| FR-04 InternalEvaluationAdapter | 10 | `test_internal_reply_adapter.py`、`test_internal_analysis_adapter.py` |
| FR-05 共用 Runner | 6 | `test_runner.py` |
| FR-06 确定性协议校验 | 5、9、10 | Gateway 和 Adapter Contract Tests |
| FR-07 最小原始产物 | 4 | `test_artifacts.py` |
| FR-08 主动删除 | 6、9、10、12 | finally、Delete、cleanup 测试 |
| Eval 并发与限流（§6.8） | 11 | `test_scheduling.py` |
| CLI 四命令（§8） | 12 | `test_cli.py` |
| 真实双流程验收 | 14 | Public Analysis + Internal Reply/Analysis opt-in smoke，Public Reply readiness |
| 排除 Judge/报告/门禁/CI | 1、12、14 | 目录和 CLI 命令面检查 |

### 4.1 与 PRD 的已知差异和验收拆分

功能开发范围保持 V0.3.0：Public 与 Internal 两种模式都实现 Reply + Analysis。最新 staging
文档只改变“现在能否真实验收”，不删除代码范围：

- Public Analysis：按真实 `GetAnalysisTask/GetAnalysisResult` 开发并完成 staging Smoke；
- Public Reply：实现 Identity → Preferences → Media → Reply Task → Result → Delete，并以
  Fake/Contract Test 验证；真实通过结论等待 Preferences、Reply 接口、稳定偏好 code 和
  Reply 当前 Task/Result 方法名交付；
- Internal Evaluation：以后端 2026-08-27 部署说明为准，Reply 与 Analysis 都实现并真实联调；
- Public 跨进程 `cleanup`：PRD 希望两种模式都可重试删除，但在 Token 不落盘约束下无法
  用新 Session 删除旧用户 Task。MVP 只保证当前进程 `finally`/信号清理，跨进程 cleanup
  只支持 Internal；这是必须显式接受的安全性实现差异。

因此开发完成与外部环境验收分开记录，禁止把 Public Reply 的 Fake PASS 写成 staging PASS。

---

## 5. 风险与控制

| 风险 | 影响 | 控制方式 |
|---|---|---|
| Public Analysis 与旧协议方法名不同 | 调用旧 Analysis 名称直接失败 | Analysis Contract Test 禁止 `GetTask/GetTaskResult`；Reply 映射独立等待冻结 |
| Eval 部署状态与 2026-08-26 文档冲突 | 快速链路可能返回未就绪 | doctor 真实探测；`FEATURE_NOT_READY` 明确阻塞 |
| Public Token 不落盘 | 硬杀进程后无法跨进程主动删除 | 串行、信号 finally、短 Smoke、TTL；不以明文 Token 解决 |
| E2E 产生匿名测试身份 | staging 账号数据持续累积 | 每 Run 复用一个 Session；请求后端确认匿名身份 TTL 或测试账号清理方式 |
| COS 签名泄漏 | 可导致私密资产风险 | URL 不进日志/产物，Transport 异常只写错误类型 |
| E2E 消耗 Analysis 额度 | Smoke 被 `QUOTA_EXHAUSTED` 阻塞 | Create 前 GetQuotaStatus；一次只跑一条 |
| Quota Schema 未冻结 | 强类型解析可能误报 | 只强断言对象；字段标记 documented/observed |
| Result 部分枚举未冻结 | 把 staging 一次返回当永久契约 | 只断言已冻结数量/空值规则，保留 Raw |
| Eval 并发挤占 Gateway 120/min | 轮询被限流 | 默认并发 3、共享滑动窗口、2 秒 Create 间隔 |
| 本地 Fixture 含真实信息 | 隐私泄漏 | 媒体不入 Git、人工脱敏、检测到 EXIF 即拒绝、Secret 扫描 |

---

## 6. Definition of Done

### 6.1 当前阶段代码交付完成

代码交付必须同时满足：

- [ ] `python -m compileall -q src tests` 退出码为 0；
- [ ] `python -m unittest discover -s tests -p 'test_*.py' -v` 为 0 failure；
- [ ] 默认测试不会访问 staging；
- [ ] `dating-eval --help` 只包含 `doctor/validate/run/cleanup`；
- [ ] Public Fake Integration 完整覆盖 Reply 的 Identity/Preferences/Media/Task/Result/Delete，以及 Analysis 的 Identity/Media/Quota/Task/Result/Delete；
- [ ] Internal Fake Integration 完整覆盖 Reply / Analysis Evaluation、Diagnostics、Delete；
- [ ] Public staging Smoke 至少成功 1 条脱敏 Analysis E2E；
- [ ] Internal staging Smoke 至少成功 1 条 Reply 和 1 条 Analysis Evaluation；
- [ ] 三条真实 Smoke 都完成主动删除；
- [ ] Public Analysis 只使用 `GetAnalysisTask/GetAnalysisResult`；Reply 方法映射不与 Analysis 共用；
- [ ] Public Reply readiness 在 Media 前识别当前 staging 阻塞，后端开放后再升级为真实 Smoke；
- [ ] Eval 默认并发 3、最大 5，创建间隔和 Gateway 总速率测试通过；
- [ ] Secret 扫描无匹配；
- [ ] Git 中没有真实媒体、Token、API Key、签名 URL 或运行 Result；
- [ ] 工具没有 AI Judge、内容评分、报告生成、门禁和 CI 代码；
- [ ] README 明确 Public E2E 跨进程清理限制，以及“Reply 已开发但当前 staging 阻塞”的验收边界。

### 6.2 V0.3.0 MVP 最终验收完成

以下外部 Gate 未满足前，只能称“代码交付完成”，不能称整个 V0.3.0 MVP 已验收：

- [ ] 后端开放并冻结 Public `GetUserPreferences/UpdateUserPreferences`；
- [ ] 后端开放 `CreateReplyTask`，并确认 Reply 当前 Task/Result 方法名；
- [ ] 后端提供 Public `dating_goal/your_voice` 稳定 code；
- [ ] `e2e-reply-single-001` 在真实 staging 完成 Preferences、Media、Reply Task、Result、
  Delete，Schema 为 `dating.reply_generation.v1`；
- [ ] 至少一个 Public Reply 多图 Case 验证 `asset_ids` 顺序；
- [ ] Public Reply Task/Result 删除后均不可访问；
- [ ] 上述真实结果与 Public Analysis、Internal Reply/Analysis 的结果分开记录，不以 Fake
  Contract Test 替代。

---

## 7. 执行时的最终命令顺序

```bash
cd /Users/admin/Testproject/dating_tool
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -p 'test_*.py' -v
dating-eval doctor --mode e2e
dating-eval validate --mode e2e --dataset datasets/e2e-smoke
dating-eval doctor --mode eval
dating-eval validate --mode eval --dataset datasets/eval-smoke.jsonl
```

在本地默认测试和两次 `doctor` 都通过后，才分别运行单条 staging Smoke。不要直接从完整批量数据集开始，也不要在同一次命令中混合 Public E2E 与 Internal Evaluation。
