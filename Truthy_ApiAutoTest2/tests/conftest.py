"""壳服务单元测试公共夹具。

功能说明:
    提供隔离的临时项目骨架（合法 config/.env 与占位 Flow）、TaskManager
    工厂与 JUnit XML 生成助手。全部测试不发真实请求：执行引擎的子进程
    一律替换为 ``python -c`` 模拟命令。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from web.task_manager import TaskManager
from web.task_store import TaskStore

# 被测框架项目根目录（tests/ 的上一级）。
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 基础 .env：包含全量会话字段与 Admin 凭证，值均为伪造占位。
BASE_DOTENV = (
    "AUTH_TOKEN=fake-auth-token\n"
    "REFRESH_TOKEN=fake-refresh-token\n"
    "USER_ID=user-1\n"
    "DEVICE_ID=device-1\n"
    "EXPIRES_TIME=9999999999999\n"
    "REFRESH_EXPIRES_TIME=9999999999999\n"
    "ADMIN_SESSION_TOKEN=fake-admin-token\n"
    "ADMIN_OPERATOR_ID=op-1\n"
    "ADMIN_OPERATOR_NAME=tester\n"
)

# 不含 Admin 凭证的 .env，用于任务级凭证预检测试。
DOTENV_WITHOUT_ADMIN = (
    "AUTH_TOKEN=fake-auth-token\n"
    "REFRESH_TOKEN=fake-refresh-token\n"
    "USER_ID=user-1\n"
    "DEVICE_ID=device-1\n"
    "EXPIRES_TIME=9999999999999\n"
    "REFRESH_EXPIRES_TIME=9999999999999\n"
)


def junit_xml(cases: list[tuple[str, str]], message: str = "断言失败") -> str:
    """生成最小可用的 JUnit XML 文本。

    参数说明:
        cases: ``(testcase name, kind)`` 列表；kind 取
            passed/failure/error/skipped。
        message: failure/error 的摘要消息。

    返回值:
        JUnit XML 字符串。
    """
    body: list[str] = []
    for name, kind in cases:
        if kind == "passed":
            body.append(f'    <testcase classname="fake" name="{name}" />')
        elif kind == "skipped":
            body.append(
                f'    <testcase classname="fake" name="{name}">'
                f'<skipped type="pytest.skip" message="跳过" /></testcase>'
            )
        else:
            body.append(
                f'    <testcase classname="fake" name="{name}">'
                f'<{kind} message="{message}">traceback 文本</{kind}></testcase>'
            )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuites>\n  <testsuite name="pytest">\n'
        + "\n".join(body)
        + "\n  </testsuite>\n</testsuites>\n"
    )


@pytest.fixture
def project_root() -> Path:
    """真实项目根目录（catalog 真实快照等只读测试使用）。"""
    return PROJECT_ROOT


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """构造可被 load_settings/提交校验接受的最小项目骨架。"""
    (tmp_path / "config" / "env").mkdir(parents=True)
    (tmp_path / "config" / "settings.yaml").write_text("comm: {}\n", encoding="utf-8")
    (tmp_path / "config" / "env" / "test.yaml").write_text(
        "gateway_base_url: http://gateway.example.invalid\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(BASE_DOTENV, encoding="utf-8")

    for directory in (
        "data/apis",
        "data/cases",
        "data/flows",
        "data/scenarios",
        "tasks",
        "reports",
        "logs",
    ):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)

    # 普通 Flow 与包含 Admin 审计步骤的 Flow（Scenario 引用 admin 占位符）。
    (tmp_path / "data" / "flows" / "DemoFlow.yaml").write_text(
        "name: Demo\ntags: []\n", encoding="utf-8"
    )
    (tmp_path / "data" / "scenarios" / "DemoFlow.yaml").write_text(
        "input: {}\n", encoding="utf-8"
    )
    (tmp_path / "data" / "flows" / "AdminFlow.yaml").write_text(
        "name: Admin\ntags: []\n", encoding="utf-8"
    )
    (tmp_path / "data" / "scenarios" / "AdminFlow.yaml").write_text(
        "admin:\n  session_token: \"{{admin_session_token}}\"\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def multi_project_root(fake_project: Path) -> Path:
    """在旧版临时骨架上增加两个合法项目包，供多项目 Web/任务测试使用。

    这里保留根 ``data/`` 只是为了让旧版兼容测试仍能证明迁移前行为；新增
    行为必须显式选择 ``projects/<project_id>``，测试会校验目录内容不会被
    合并扫描。生产仓库完成迁移后不会同时保留两份资产。
    """

    manifests = {
        "truthy": ("Truthy Gateway", "truthy_session"),
        "dating": ("Dating AI Assistant", "anonymous_session"),
    }
    for project_id, (display_name, profile_id) in manifests.items():
        project = fake_project / "projects" / project_id
        for directory in (
            "data/api",
            "data/apis",
            "data/cases",
            "data/flows",
            "data/scenarios",
            "fixtures",
        ):
            (project / directory).mkdir(parents=True, exist_ok=True)
        required_keys = ["gateway.base_url", "gateway.path", "gateway.comm"]
        if project_id == "dating":
            required_keys.extend(
                [
                    "flow.analysis.poll_interval_seconds",
                    "flow.analysis.timeout_seconds",
                ]
            )
        (project / "project.yaml").write_text(
            "\n".join(
                [
                    "schema_version: 1",
                    f"project_id: {project_id}",
                    f"display_name: {display_name}",
                    "capabilities:",
                    "  - gateway",
                    "config_contract:",
                    "  required_keys:",
                    *[f"    - {key}" for key in required_keys],
                    "  credential_profiles:",
                    f"    - {profile_id}",
                    "redaction:",
                    "  extra_keys: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        api_id = "GetMe"
        (project / "data" / "apis" / f"{api_id}.yaml").write_text(
            "\n".join(
                [
                    f"id: {api_id}",
                    f"name: {display_name} 当前用户",
                    f"credential_profile: {profile_id}",
                    "request:",
                    "  service_name: example.IdentityService",
                    "  method_name: GetMe",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (project / "data" / "cases" / f"{api_id}.yaml").write_text(
            "\n".join(
                [
                    f"api: {api_id}",
                    "cases:",
                    "  - id: get_me_success",
                    "    name: 获取当前用户成功",
                    "    tags: [smoke]",
                    "    request:",
                    "      params: {}",
                    "    assert:",
                    "      http_status: 200",
                    "      gateway: {code: 0}",
                    "      response: {success: true}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        flow_id = "dating_demo_flow" if project_id == "dating" else "truthy_demo_flow"
        (project / "data" / "flows" / f"{flow_id}.yaml").write_text(
            "\n".join(
                [
                    f"name: {display_name} Demo Flow",
                    "tags: [regression]",
                    "steps:",
                    "  - id: get_me",
                    "    api: GetMe",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (project / "data" / "scenarios" / f"{flow_id}.yaml").write_text(
            "\n".join(
                [
                    f"name: {display_name} Demo Flow 成功",
                    "variables: {}",
                    "step_data:",
                    "  get_me:",
                    "    params: {}",
                    "    assert:",
                    "      http_status: 200",
                    "      gateway: {code: 0}",
                    "      response: {success: true}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return fake_project


@pytest.fixture
def make_manager():
    """TaskManager 工厂；测试结束统一等待等待线程退出。

    功能说明:
        除常用参数外的其余关键字参数原样透传给 TaskManager 构造器，
        便于注入平台模式提供器等可选依赖。
    """
    managers: list[TaskManager] = []

    def _make(root: Path, **kwargs) -> TaskManager:
        store = TaskStore(root / "tasks", root / "reports")
        manager = TaskManager(
            root,
            store,
            timeout_seconds=kwargs.pop("timeout_seconds", 30),
            retain=kwargs.pop("retain", 50),
            cancel_grace_seconds=kwargs.pop("cancel_grace_seconds", 0.5),
            **kwargs,
        )
        managers.append(manager)
        return manager

    yield _make
    for manager in managers:
        manager.wait_idle(timeout=15)


def patch_command(monkeypatch, manager: TaskManager, script: str) -> None:
    """把执行引擎的子进程命令替换为执行指定 Python 脚本。

    参数说明:
        manager: 被测执行引擎。
        script: ``python -c`` 执行的脚本；可用 ``{junit}`` 占位符引用
            本任务 JUnit 目标路径。
    """

    def fake_build(task_input, junit_path):
        return [sys.executable, "-c", script.format(junit=junit_path)]

    monkeypatch.setattr(manager, "_build_command", fake_build)
