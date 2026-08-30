"""TaskManager 单元测试。

功能说明:
    覆盖提交参数校验、两级凭证预检、单槽位语义、退出码映射、超时、
    取消、取消/完成竞态、子进程启动失败、启动恢复与框架日志关联。
    全部子进程经 patch_command 替换为 ``python -c`` 模拟脚本，不发真实请求。
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from werkzeug.datastructures import FileStorage

from conftest import BASE_DOTENV, DOTENV_WITHOUT_ADMIN, junit_xml, patch_command
from web.task_manager import SubmissionError, TaskManager

# 终端状态集合，与实现保持一致。
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def png_upload(name: str, payload: bytes = b"fixture-image") -> FileStorage:
    """构造带真实 PNG 文件头的内存上传对象，模拟 Flask multipart 文件。"""

    return FileStorage(
        stream=BytesIO(b"\x89PNG\r\n\x1a\n" + payload),
        filename=name,
        content_type="image/png",
    )


@pytest.fixture
def manager(fake_project: Path, make_manager) -> TaskManager:
    """基于伪造项目骨架的执行引擎。"""
    return make_manager(fake_project)


def wait_terminal(manager: TaskManager, task_id: str, timeout: float = 15.0) -> dict:
    """轮询等待任务到达终态并返回记录；超时使测试失败。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = manager.store.load(task_id)
        if record is not None and record["status"] in TERMINAL_STATUSES:
            return record
        time.sleep(0.05)
    raise AssertionError(f"任务 {task_id} 未在 {timeout} 秒内到达终态")


def wait_running(manager: TaskManager, task_id: str, timeout: float = 10.0) -> dict:
    """轮询等待任务进入 running（子进程已登记，取消可定位进程）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = manager.store.load(task_id)
        if record is not None and record["status"] == "running":
            return record
        time.sleep(0.05)
    raise AssertionError(f"任务 {task_id} 未在 {timeout} 秒内进入 running")


def copy_junit_script(staged: Path) -> str:
    """构造把预置 JUnit 文件复制到任务产物位置的模拟脚本。

    参数说明:
        staged: 测试预先写好的 JUnit XML 路径。

    返回值:
        模拟脚本；``{junit}`` 占位符由 patch_command 注入真实产物路径。
    """
    return f"import shutil; shutil.copy({str(staged)!r}, '{{junit}}')"


class TestInputValidation:
    """提交参数校验矩阵：全部本地拒绝，400 + INVALID_PARAMS。"""

    @pytest.mark.parametrize(
        "env",
        ["", "  ", "a/b", "../x", "prod"],
    )
    def test_invalid_env_rejected(self, manager, env):
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env=env, run_type="single")
        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == "INVALID_PARAMS"

    def test_invalid_run_type_rejected(self, manager):
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="bogus")
        assert exc_info.value.error_code == "INVALID_PARAMS"

    def test_exact_project_task_rejects_tag_filter(
        self, multi_project_root, make_manager
    ):
        """精确 Case/Flow 已经唯一定位资产，不能再被 pytest marker 二次过滤。"""

        manager = make_manager(multi_project_root)
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(
                project_id="dating",
                run_type="flow",
                flow_id="dating_demo_flow",
                tag="test",
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == "TAG_FILTER_NOT_ALLOWED"

    def test_single_with_flow_rejected(self, manager):
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="single", flow="DemoFlow")
        assert exc_info.value.error_code == "INVALID_PARAMS"

    def test_flow_run_requires_flow_name(self, manager):
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="flow")
        assert exc_info.value.error_code == "INVALID_PARAMS"

    def test_flow_must_exist(self, manager):
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="flow", flow="NoSuchFlow")
        assert exc_info.value.error_code == "INVALID_PARAMS"

    def test_flow_name_traversal_rejected(self, manager):
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="flow", flow="../evil")
        assert exc_info.value.error_code == "INVALID_PARAMS"

    @pytest.mark.parametrize("tag", ["bad!tag", "a;b", "rm -rf && x", "x" * 201])
    def test_invalid_tag_rejected(self, manager, tag):
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="all", tag=tag)
        assert exc_info.value.error_code == "INVALID_PARAMS"


class TestCredentialPrecheck:
    """两级凭证预检：配置合并级与任务级 Admin 检查。"""

    def test_env_directory_rejected(self, manager, fake_project):
        # .env 位置被目录占据（bind mount 误创建场景）。
        (fake_project / ".env").unlink()
        (fake_project / ".env").mkdir()
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="single")
        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == "CREDENTIAL_FILE_INVALID"

    def test_missing_credentials_rejected(
        self, manager, fake_project, monkeypatch
    ):
        # 删除 .env 并清理进程环境变量，load_settings 因缺少 DEVICE_ID 失败。
        (fake_project / ".env").unlink()
        for key in (
            "AUTH_TOKEN",
            "REFRESH_TOKEN",
            "USER_ID",
            "DEVICE_ID",
            "EXPIRES_TIME",
            "REFRESH_EXPIRES_TIME",
            "ADMIN_SESSION_TOKEN",
            "ADMIN_OPERATOR_ID",
            "ADMIN_OPERATOR_NAME",
        ):
            monkeypatch.delenv(key, raising=False)
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="single")
        assert exc_info.value.error_code == "CREDENTIALS_MISSING"

    def test_all_run_requires_admin_credentials(self, manager, fake_project):
        # AdminFlow 的 Scenario 引用 admin 占位符，all 运行必须带 Admin 凭证。
        (fake_project / ".env").write_text(DOTENV_WITHOUT_ADMIN, encoding="utf-8")
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="all")
        assert exc_info.value.error_code == "ADMIN_CREDENTIALS_MISSING"
        # 错误消息只列字段名。
        assert "ADMIN_SESSION_TOKEN" in exc_info.value.message

    def test_admin_flow_requires_admin_credentials(self, manager, fake_project):
        (fake_project / ".env").write_text(DOTENV_WITHOUT_ADMIN, encoding="utf-8")
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="flow", flow="AdminFlow")
        assert exc_info.value.error_code == "ADMIN_CREDENTIALS_MISSING"

    def test_demo_flow_without_admin_ok(
        self, manager, fake_project, monkeypatch
    ):
        patch_command(monkeypatch, manager, "print('ok')")
        (fake_project / ".env").write_text(DOTENV_WITHOUT_ADMIN, encoding="utf-8")
        record = manager.submit(env="test", run_type="flow", flow="DemoFlow")
        finished = wait_terminal(manager, record["id"])
        assert finished["status"] == "succeeded"

    def test_single_without_admin_ok(self, manager, fake_project, monkeypatch):
        patch_command(monkeypatch, manager, "print('ok')")
        (fake_project / ".env").write_text(DOTENV_WITHOUT_ADMIN, encoding="utf-8")
        record = manager.submit(env="test", run_type="single")
        finished = wait_terminal(manager, record["id"])
        assert finished["status"] == "succeeded"

    def test_all_with_unmatched_tag_skips_admin_check(
        self, manager, fake_project, monkeypatch
    ):
        # 标签未命中任何 Flow 时，Admin 检查不生效。
        patch_command(monkeypatch, manager, "print('ok')")
        (fake_project / ".env").write_text(DOTENV_WITHOUT_ADMIN, encoding="utf-8")
        record = manager.submit(env="test", run_type="all", tag="nosuchtag")
        finished = wait_terminal(manager, record["id"])
        assert finished["status"] == "succeeded"

    def test_platform_mode_admin_ready_from_platform_keys(
        self, fake_project, make_manager, monkeypatch
    ):
        # 平台模式：以平台 Secret 键名清单为准，本地 .env 无 Admin 凭证也放行。
        (fake_project / ".env").write_text(DOTENV_WITHOUT_ADMIN, encoding="utf-8")
        manager = make_manager(
            fake_project,
            platform_secret_keys_provider=lambda _signed_context: {
                "ADMIN_SESSION_TOKEN",
                "ADMIN_OPERATOR_ID",
                "ADMIN_OPERATOR_NAME",
            },
        )
        patch_command(monkeypatch, manager, "print('ok')")
        record = manager.submit(env="test", run_type="flow", flow="AdminFlow")
        finished = wait_terminal(manager, record["id"])
        assert finished["status"] == "succeeded"

    def test_platform_mode_admin_partial_keys_rejected(
        self, fake_project, make_manager
    ):
        # 本地 .env 含全部 Admin 凭证，但平台清单只配了一个键 → 以平台清单为准拒绝。
        (fake_project / ".env").write_text(BASE_DOTENV, encoding="utf-8")
        manager = make_manager(
            fake_project,
            platform_secret_keys_provider=lambda _signed_context: {"ADMIN_SESSION_TOKEN"},
        )
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="flow", flow="AdminFlow")
        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == "ADMIN_CREDENTIALS_MISSING"
        # 缺失明细只列平台未配置的键。
        assert "ADMIN_OPERATOR_ID" in exc_info.value.message
        assert "ADMIN_OPERATOR_NAME" in exc_info.value.message
        assert "ADMIN_SESSION_TOKEN" not in exc_info.value.message

    def test_platform_mode_provider_unavailable_rejected(
        self, fake_project, make_manager
    ):
        # 平台运行配置提供器返回 None（不可达）→ 503 PLATFORM_CONFIG_UNAVAILABLE。
        (fake_project / ".env").write_text(BASE_DOTENV, encoding="utf-8")
        manager = make_manager(
            fake_project, platform_secret_keys_provider=lambda _signed_context: None
        )
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="flow", flow="AdminFlow")
        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == "PLATFORM_CONFIG_UNAVAILABLE"


class TestBuildCommand:
    """pytest 命令组装：对齐 Jenkins 入口语义（纯参数断言，不启动进程）。"""

    def test_single_command(self, manager, fake_project):
        args = manager._build_command(
            {"env": "test", "run_type": "single", "flow": None, "tag": None},
            fake_project / "reports" / "j.xml",
        )
        assert args[1:3] == ["-m", "pytest"]
        assert "test_cases/test_single_api.py" in args
        assert "test_cases/test_gateway_flow.py" not in args
        assert "--env=test" in args
        assert f"--junitxml={fake_project / 'reports' / 'j.xml'}" in args
        assert "-m" not in args[3:]

    def test_flow_command_with_flow_and_tag(self, manager, fake_project):
        args = manager._build_command(
            {"env": "test", "run_type": "flow", "flow": "DemoFlow", "tag": "smoke (v2)"},
            fake_project / "reports" / "j.xml",
        )
        assert "test_cases/test_gateway_flow.py" in args
        assert "--flow=DemoFlow" in args
        # 跳过 "-m pytest" 中的 -m，定位标签表达式的 -m。
        assert args[args.index("-m", 3) + 1] == "smoke (v2)"

    def test_all_command_contains_both_entries(self, manager, fake_project):
        args = manager._build_command(
            {"env": "test", "run_type": "all", "flow": None, "tag": None},
            fake_project / "reports" / "j.xml",
        )
        assert "test_cases/test_single_api.py" in args
        assert "test_cases/test_gateway_flow.py" in args


class TestMultiProjectTaskV2:
    """多项目任务必须固化选择与平台快照元数据，且运行产物按项目隔离。"""

    def test_platform_payload_preserves_gateway_comm_before_credential_overlay(self):
        """Release 的静态 Device 必须压过兼容凭证中的旧值。

        平台的 ConfigDefinition 使用 ``gateway.comm`` 逻辑键保存公共通讯参数，
        Credential/Secret 只负责补充当前会话的 token、user_id 等动态字段。
        ``DEVICE_ID`` 曾被错误登记为个人凭证，为兼容历史快照仍可能出现在
        materialize 响应中，但它不能覆盖项目 Release 的静态设备标识。
        """

        settings = TaskManager._settings_from_platform_payload(
            {
                "normal": {
                    "gateway.base_url": "https://gateway.example",
                    "gateway.path": "/dating/gateway/invoke",
                    "gateway.comm": {
                        "platform": "ios",
                        "locale": "zh-Hans-CN",
                        "device_id": "release-device",
                    },
                },
                "secrets": {
                    "AUTH_TOKEN": "credential-token",
                    "DEVICE_ID": "credential-device",
                },
            }
        )

        assert settings["comm"] == {
            "platform": "ios",
            "locale": "zh-Hans-CN",
            "device_id": "release-device",
            "auth_token": "credential-token",
        }
        assert "gateway.comm" not in settings

    @staticmethod
    def _runtime_plan(task_id: str, signed_context: str, selection: dict) -> dict:
        """返回不含 Secret 的平台规划，模拟 Runtime Context 契约。"""

        assert task_id
        assert signed_context == "signed-user"
        assert selection["project_id"] == "dating"
        return {
            "runtime_context_id": "rtx_dating_user_1",
            "runtime_scope_id": "scope_dating_dev_test",
            "platform_project_id": "platform-dating",
            "platform_environment": "dev",
            "target_env": "test",
            "config_source": "platform",
            "release_id": "release-dating-v3",
            "release_version": 3,
            "credential_profiles": [
                {"id": "anonymous_session", "version": 4}
            ],
            "resource_snapshot": {
                "owner_user_id": "user-1",
                "access_scope_snapshot": "project",
                "project_id_snapshot": "platform-dating",
                "authorization_source_snapshot": "project-member",
            },
        }

    @staticmethod
    def _runtime_snapshot(_record: dict) -> tuple[dict, dict]:
        """返回执行期完整快照；Secret 只能写入临时文件，不得进入任务 JSON。"""

        return (
            {
                "tool_id": "api-autotest",
                "normal": {"GATEWAY_API_URL": "https://gateway.test.invalid"},
                "secrets": {"ACCESS_TOKEN": "snapshot-secret"},
                "credential_metadata": {
                    "profiles": [{"id": "anonymous_session", "version": 4}]
                },
            },
            {
                "release_id": "release-dating-v3",
                "release_version": 3,
                "runtime_scope_id": "scope_dating_dev_test",
                "credential_profiles": [
                    {"id": "anonymous_session", "version": 4}
                ],
                "process_environment": {
                    "API_AUTOTEST_SESSION_PROVIDER": "platform",
                    "PLATFORM_RUNTIME_CONTEXT_ID": "rtx_dating_user_1",
                },
            },
        )

    def test_build_command_uses_project_selection_and_fixed_target_env(
        self, multi_project_root, make_manager
    ):
        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        junit_path = multi_project_root / "reports" / "junit" / "dating" / "task.xml"
        args = manager._build_command(
            {
                "project_id": "dating",
                "target_env": "test",
                "config_source": "platform",
                "run_type": "single",
                "api_id": "GetMe",
                "case_id": "get_me_success",
                "flow_id": None,
                "tag": "smoke",
            },
            junit_path,
        )

        assert "--project=dating" in args
        assert "--target-env=test" in args
        assert "--config-source=platform" in args
        assert "--api=GetMe" in args
        # Web 契约分别传 api_id/case_id；pytest CaseLoader 使用完整稳定 ID，
        # TaskManager 必须在进程边界组合，不能把裸 case_id 传给收集器。
        assert "--case=GetMe::get_me_success" in args
        assert "--env=test" not in args

    def test_submit_persists_resolved_asset_snapshot_and_private_file_lifecycle(
        self,
        multi_project_root,
        make_manager,
        monkeypatch,
    ):
        """覆盖值应固化进 Task V2，并只通过 0600 临时文件传给 pytest。"""
        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        selection = manager._validate_input(
            None,
            "flow",
            None,
            None,
            project_id="dating",
            flow_id="dating_demo_flow",
        )
        preview = manager.preview_asset(
            selection,
            runtime_overrides={"client_locale": "zh-CN"},
        )
        patch_command(
            monkeypatch,
            manager,
            "import json, os, stat; "
            "p=os.environ['API_AUTOTEST_EXECUTION_ASSET_FILE']; "
            "d=json.load(open(p, encoding='utf-8')); "
            "assert stat.S_IMODE(os.stat(p).st_mode)==0o600; "
            "params=d['resolved_execution_asset']['flow_case']['scenario']"
            "['step_data']['get_me']['params']; "
            "assert params['locale']=='zh-CN'",
        )

        created = manager.submit(
            project_id="dating",
            run_type="flow",
            flow_id="dating_demo_flow",
            asset_revision=preview["asset_revision"],
            runtime_overrides={"client_locale": "zh-CN"},
            signed_user_context="signed-user",
        )
        finished = wait_terminal(manager, created["id"])

        assert finished["input"]["runtime_overrides"] == {
            "client_locale": "zh-CN"
        }
        assert finished["input"]["asset_revision"] == preview["asset_revision"]
        assert finished["asset_snapshot"]["applied_overrides"][0][
            "resolved_value"
        ] == "zh-CN"
        execution_path = (
            multi_project_root
            / "runtime"
            / "dating"
            / created["id"]
            / "execution-asset.json"
        )
        assert not execution_path.exists()
        assert manager.store.console_log_path(created["id"], "dating").is_file()

    def test_v2_cancel_removes_only_execution_asset(
        self,
        multi_project_root,
        make_manager,
        monkeypatch,
    ):
        """取消任务应删执行 JSON，但保留 Task JSON 与 console 审计产物。"""
        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        patch_command(monkeypatch, manager, "import time; time.sleep(10)")
        created = manager.submit(
            project_id="dating",
            run_type="flow",
            flow_id="dating_demo_flow",
            signed_user_context="signed-user",
        )
        wait_running(manager, created["id"])
        execution_path = manager.store.execution_asset_path(
            created["id"], "dating"
        )
        assert execution_path.is_file()

        manager.cancel(created["id"])
        manager.wait_idle()

        assert manager.store.load(created["id"])["status"] == "cancelled"
        assert not execution_path.exists()
        assert manager.store.console_log_path(created["id"], "dating").is_file()

    def test_v2_start_failure_removes_execution_asset_and_releases_slot(
        self,
        multi_project_root,
        make_manager,
        monkeypatch,
    ):
        """Popen 失败后不能遗留执行资产，且失败任务仍保留审计记录。"""
        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        monkeypatch.setattr(
            manager,
            "_build_command",
            lambda task_input, junit_path: [
                "/nonexistent-interpreter-runtime-override",
                "-c",
                "pass",
            ],
        )

        with pytest.raises(OSError):
            manager.submit(
                project_id="dating",
                run_type="flow",
                flow_id="dating_demo_flow",
                signed_user_context="signed-user",
            )

        record = manager.store.list()[0]
        assert record["status"] == "failed"
        assert not manager.store.execution_asset_path(
            record["id"], "dating"
        ).exists()
        patch_command(monkeypatch, manager, "print('slot-released')")
        next_task = manager.submit(
            project_id="dating",
            run_type="flow",
            flow_id="dating_demo_flow",
            signed_user_context="signed-user",
        )
        assert wait_terminal(manager, next_task["id"])["status"] == "succeeded"

    def test_submit_rejects_stale_asset_revision(
        self,
        multi_project_root,
        make_manager,
    ):
        """预检后 YAML/声明变化必须以稳定 409 拒绝提交。"""
        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        with pytest.raises(SubmissionError) as error:
            manager.submit(
                project_id="dating",
                run_type="single",
                api_id="GetMe",
                case_id="get_me_success",
                asset_revision=f"sha256:{'0' * 64}",
                runtime_overrides={"client_locale": "zh-CN"},
            )
        assert error.value.status_code == 409
        assert error.value.error_code == "RUNTIME_OVERRIDE_SCHEMA_CHANGED"
        assert manager.store.list() == []

    def test_all_run_rejects_runtime_overrides(
        self,
        multi_project_root,
        make_manager,
    ):
        """批量 all/tag 没有唯一目标资产，不能接受本次覆盖。"""
        manager = make_manager(multi_project_root)
        with pytest.raises(SubmissionError) as error:
            manager.submit(
                project_id="dating",
                run_type="all",
                runtime_overrides={"client_locale": "zh-CN"},
            )
        assert error.value.error_code == "RUNTIME_OVERRIDE_NOT_SUPPORTED"

    def test_platform_plan_never_receives_runtime_override_values(
        self,
        multi_project_root,
        make_manager,
        monkeypatch,
    ):
        """业务覆盖只留在工具，不得传入平台配置/凭证 Provider。"""
        captured: dict = {}

        def plan(task_id: str, signed_context: str, selection: dict) -> dict:
            captured.update(selection)
            return self._runtime_plan(task_id, signed_context, selection)

        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        preview = manager.preview_asset(
            manager._validate_input(
                None,
                "flow",
                None,
                None,
                project_id="dating",
                flow_id="dating_demo_flow",
            ),
            runtime_overrides={"client_locale": "zh-CN"},
        )
        patch_command(monkeypatch, manager, "print('ok')")
        created = manager.submit(
            project_id="dating",
            run_type="flow",
            flow_id="dating_demo_flow",
            asset_revision=preview["asset_revision"],
            runtime_overrides={"client_locale": "zh-CN"},
            signed_user_context="signed-user",
        )
        wait_terminal(manager, created["id"])
        assert "runtime_overrides" not in captured
        assert "asset_revision" not in captured

    def test_platform_snapshot_is_0600_isolated_and_deleted_at_terminal(
        self, multi_project_root, make_manager, monkeypatch
    ):
        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        # 若平台模式错误继承宿主配置，子进程会看到这个污染值；正确实现只传
        # 快照文件路径和平台会话写回所需的非 Secret 元数据。
        monkeypatch.setenv("ACCESS_TOKEN", "inherited-secret")
        patch_command(
            monkeypatch,
            manager,
            "import json, os, stat; "
            "p=os.environ['API_AUTOTEST_RUNTIME_SNAPSHOT_FILE']; "
            "d=json.load(open(p, encoding='utf-8')); "
            "assert d['settings']['runtime_variables']['ACCESS_TOKEN']=='snapshot-secret'; "
            "assert stat.S_IMODE(os.stat(p).st_mode)==0o600; "
            "assert 'ACCESS_TOKEN' not in os.environ",
        )

        record = manager.submit(
            project_id="dating",
            run_type="single",
            api_id="GetMe",
            case_id="get_me_success",
            signed_user_context="signed-user",
        )
        finished = wait_terminal(manager, record["id"])

        assert finished["schema_version"] == 3
        assert finished["project"] == {
            "platform_project_id": "platform-dating",
            "project_id": "dating",
            "display_name": "Dating AI Assistant",
        }
        assert finished["runtime"]["runtime_scope_id"] == "scope_dating_dev_test"
        assert finished["runtime"]["release_version"] == 3
        assert finished["selection"] == {
            "run_type": "single",
            "api_id": "GetMe",
            "case_id": "get_me_success",
            "flow_id": None,
            "tag": None,
        }
        assert finished["junit_file"] == (
            f"reports/junit/dating/{record['id']}.xml"
        )
        # 终态只销毁包含 Secret 的临时快照；同目录 console.log 是任务审计
        # 产物，必须保留供详情页查看，不能通过删除整个任务目录来清理。
        assert not (
            multi_project_root
            / "runtime"
            / "dating"
            / record["id"]
            / "snapshot.json"
        ).exists()
        serialized = json.dumps(finished, ensure_ascii=False)
        assert "snapshot-secret" not in serialized
        assert "inherited-secret" not in serialized

    def test_retry_creates_new_task_and_preserves_original_snapshot(
        self, multi_project_root, make_manager, monkeypatch
    ):
        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        patch_command(monkeypatch, manager, "print('ok')")
        original = manager.submit(
            project_id="dating",
            run_type="flow",
            flow_id="dating_demo_flow",
            signed_user_context="signed-user",
        )
        wait_terminal(manager, original["id"])

        retried = manager.retry(original["id"], signed_user_context="signed-user")
        wait_terminal(manager, retried["id"])

        assert retried["id"] != original["id"]
        assert retried["retry_of"] == original["id"]
        persisted_original = manager.store.load(original["id"])
        assert persisted_original["retry_of"] is None
        assert persisted_original["runtime"]["release_id"] == "release-dating-v3"

    def test_retry_copies_logical_overrides_using_current_schema(
        self,
        multi_project_root,
        make_manager,
        monkeypatch,
    ):
        """直接重试创建新快照，但保留旧任务的逻辑覆盖值。"""
        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        selection = manager._validate_input(
            None,
            "flow",
            None,
            None,
            project_id="dating",
            flow_id="dating_demo_flow",
        )
        preview = manager.preview_asset(
            selection,
            runtime_overrides={"client_locale": "zh-CN"},
        )
        patch_command(monkeypatch, manager, "print('ok')")
        original = manager.submit(
            project_id="dating",
            run_type="flow",
            flow_id="dating_demo_flow",
            asset_revision=preview["asset_revision"],
            runtime_overrides={"client_locale": "zh-CN"},
            signed_user_context="signed-user",
        )
        original_finished = wait_terminal(manager, original["id"])
        retried = manager.retry(
            original["id"],
            signed_user_context="signed-user",
        )
        retried_finished = wait_terminal(manager, retried["id"])

        assert retried_finished["retry_of"] == original["id"]
        assert retried_finished["input"]["runtime_overrides"] == {
            "client_locale": "zh-CN"
        }
        assert manager.store.load(original["id"]) == original_finished

    def test_retry_rejects_runtime_input_target_drift(
        self,
        multi_project_root,
        make_manager,
        monkeypatch,
    ):
        """同一逻辑键改绑到另一业务字段时，直接 Retry 必须返回 409。"""
        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        selection = manager._validate_input(
            None,
            "flow",
            None,
            None,
            project_id="dating",
            flow_id="dating_demo_flow",
        )
        preview = manager.preview_asset(
            selection,
            runtime_overrides={"client_locale": "zh-CN"},
        )
        patch_command(monkeypatch, manager, "print('ok')")
        original = manager.submit(
            project_id="dating",
            run_type="flow",
            flow_id="dating_demo_flow",
            asset_revision=preview["asset_revision"],
            runtime_overrides={"client_locale": "zh-CN"},
            signed_user_context="signed-user",
        )
        original_finished = wait_terminal(manager, original["id"])

        scenario_path = (
            multi_project_root
            / "projects"
            / "dating"
            / "data"
            / "scenarios"
            / "dating_demo_flow.yaml"
        )
        scenario_text = scenario_path.read_text(encoding="utf-8")
        scenario_path.write_text(
            scenario_text.replace("path: $.locale", "path: $.alternate_locale").replace(
                "      locale: en-US",
                "      locale: en-US\n      alternate_locale: en-US",
            ),
            encoding="utf-8",
        )

        with pytest.raises(SubmissionError) as error:
            manager.retry(original["id"], signed_user_context="signed-user")
        assert error.value.status_code == 409
        assert error.value.error_code == "RUNTIME_OVERRIDE_SCHEMA_CHANGED"
        assert manager.store.load(original["id"]) == original_finished
        assert len(manager.store.list()) == 1

    def test_task_inputs_are_stored_in_order_and_exposed_to_child_process(
        self, multi_project_root, make_manager, monkeypatch
    ):
        """任务图片必须以 0600 持久化，manifest 顺序与用户选择顺序一致。"""

        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        patch_command(
            monkeypatch,
            manager,
            "import hashlib, json, os, pathlib, stat; "
            "p=pathlib.Path(os.environ['API_AUTOTEST_TASK_INPUT_MANIFEST_FILE']); "
            "d=json.load(open(p, encoding='utf-8')); "
            "assert stat.S_IMODE(p.stat().st_mode)==0o600; "
            "assert [x['original_name'] for x in d['media_files']]=="
            "['chat_01.png','chat_02.png','chat_03.png']; "
            "assert all(stat.S_IMODE((p.parent/x['relative_path']).stat().st_mode)==0o600 "
            "for x in d['media_files'])",
        )

        created = manager.submit(
            project_id="dating",
            run_type="flow",
            flow_id="dating_demo_flow",
            signed_user_context="signed-user",
            uploads=[
                png_upload("chat_01.png", b"one"),
                png_upload("chat_02.png", b"two"),
                png_upload("chat_03.png", b"three"),
            ],
        )
        finished = wait_terminal(manager, created["id"])

        assert [item["original_name"] for item in finished["attachments"]] == [
            "chat_01.png",
            "chat_02.png",
            "chat_03.png",
        ]
        assert finished["input_manifest_file"] == (
            f"runtime/dating/{created['id']}/inputs/manifest.json"
        )
        input_directory = multi_project_root / "runtime" / "dating" / created["id"] / "inputs"
        manifest = json.loads((input_directory / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["project_id"] == "dating"
        assert manifest["task_id"] == created["id"]
        assert [item["order"] for item in manifest["media_files"]] == [1, 2, 3]
        assert stat.S_IMODE((input_directory / "manifest.json").stat().st_mode) == 0o600
        assert all(len(item["sha256"]) == 64 for item in finished["attachments"])

    @pytest.mark.parametrize(
        ("upload", "error_code"),
        [
            (
                FileStorage(
                    stream=BytesIO(b"not-a-png"),
                    filename="fake.png",
                    content_type="image/png",
                ),
                "TASK_INPUT_TYPE_INVALID",
            ),
            (
                FileStorage(
                    stream=BytesIO(b""),
                    filename="empty.png",
                    content_type="image/png",
                ),
                "TASK_INPUT_TYPE_INVALID",
            ),
        ],
    )
    def test_invalid_task_input_is_rejected_without_persisting_record(
        self,
        multi_project_root,
        make_manager,
        monkeypatch,
        upload,
        error_code,
    ):
        """声明 MIME 不能替代文件头校验，失败不得留下半成品任务。"""

        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        patch_command(monkeypatch, manager, "print('must-not-run')")

        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(
                project_id="dating",
                run_type="flow",
                flow_id="dating_demo_flow",
                signed_user_context="signed-user",
                uploads=[upload],
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == error_code
        assert manager.store.list() == []
        runtime_root = multi_project_root / "runtime" / "dating"
        assert not runtime_root.exists() or list(runtime_root.iterdir()) == []

    def test_more_than_nine_task_inputs_are_rejected(
        self, multi_project_root, make_manager, monkeypatch
    ):
        """首期服务端保护边界固定为最多 9 张，不能只依赖浏览器校验。"""

        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        patch_command(monkeypatch, manager, "print('must-not-run')")

        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(
                project_id="dating",
                run_type="flow",
                flow_id="dating_demo_flow",
                signed_user_context="signed-user",
                uploads=[png_upload(f"chat_{index:02d}.png") for index in range(10)],
            )

        assert exc_info.value.error_code == "TASK_INPUT_COUNT_INVALID"
        assert manager.store.list() == []

    def test_retry_copies_task_inputs_and_detects_tampering(
        self, multi_project_root, make_manager, monkeypatch
    ):
        """重试必须复制到新任务；源文件被删除或篡改时 fail-closed。"""

        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        patch_command(monkeypatch, manager, "print('ok')")
        original = manager.submit(
            project_id="dating",
            run_type="flow",
            flow_id="dating_demo_flow",
            signed_user_context="signed-user",
            uploads=[png_upload("../chat_01.png", b"one"), png_upload("chat_02.png", b"two")],
        )
        wait_terminal(manager, original["id"])

        retried = manager.retry(original["id"], signed_user_context="signed-user")
        retried_finished = wait_terminal(manager, retried["id"])
        assert retried_finished["retry_of"] == original["id"]
        assert [item["original_name"] for item in retried_finished["attachments"]] == [
            "chat_01.png",
            "chat_02.png",
        ]
        original_finished = manager.store.load(original["id"])
        assert [item["sha256"] for item in retried_finished["attachments"]] == [
            item["sha256"] for item in original_finished["attachments"]
        ]
        assert [
            item["task_relative_path"] for item in retried_finished["attachments"]
        ] != [item["task_relative_path"] for item in original_finished["attachments"]]
        assert retried_finished["input_manifest_file"] != original_finished[
            "input_manifest_file"
        ]

        source = (
            multi_project_root
            / original_finished["attachments"][0]["task_relative_path"]
        )
        source.write_bytes(b"tampered")
        with pytest.raises(SubmissionError) as exc_info:
            manager.retry(original["id"], signed_user_context="signed-user")
        assert exc_info.value.error_code == "TASK_INPUTS_MISSING"

    def test_retry_rejects_symlinked_source_input_inside_task_boundary(
        self, multi_project_root, make_manager, monkeypatch
    ):
        """即使链接目标仍在 inputs 内，重试也只能读取原始普通文件。"""

        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=self._runtime_plan,
            runtime_snapshot_provider=self._runtime_snapshot,
        )
        patch_command(monkeypatch, manager, "print('ok')")
        original = manager.submit(
            project_id="dating",
            run_type="flow",
            flow_id="dating_demo_flow",
            signed_user_context="signed-user",
            uploads=[png_upload("chat_01.png", b"one")],
        )
        original_finished = wait_terminal(manager, original["id"])
        source = (
            multi_project_root
            / original_finished["attachments"][0]["task_relative_path"]
        )
        linked_target = source.with_name("linked-target.png")
        linked_target.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(linked_target.name)

        with pytest.raises(SubmissionError) as exc_info:
            manager.retry(original["id"], signed_user_context="signed-user")

        assert exc_info.value.error_code == "TASK_INPUTS_MISSING"


class TestExecutionOutcomes:
    """退出码映射与结果语义。"""

    def test_success_with_junit(self, manager, fake_project, monkeypatch, tmp_path):
        staged = tmp_path / "staged.xml"
        staged.write_text(
            junit_xml([("case_a", "passed"), ("case_b", "passed")]),
            encoding="utf-8",
        )
        patch_command(monkeypatch, manager, copy_junit_script(staged))
        record = manager.submit(env="test", run_type="single")
        finished = wait_terminal(manager, record["id"])
        assert finished["status"] == "succeeded"
        assert finished["exit_code"] == 0
        assert finished["timeout"] is False
        assert finished["result_available"] is True
        assert finished["summary"]["total"] == 2
        assert finished["summary"]["passed"] == 2
        assert finished["started_at"] is not None
        assert finished["finished_at"] is not None
        assert (fake_project / finished["junit_file"]).is_file()

    def test_exit1_with_junit_marked_failed(
        self, manager, fake_project, monkeypatch, tmp_path
    ):
        staged = tmp_path / "staged.xml"
        staged.write_text(
            junit_xml(
                [("case_a", "passed"), ("case_b", "failure")], message="断言失败"
            ),
            encoding="utf-8",
        )
        # 模拟 pytest：写出 JUnit 后以退出码 1 结束。
        script = (
            f"import shutil, sys; shutil.copy({str(staged)!r}, '{{junit}}'); "
            "sys.exit(1)"
        )
        patch_command(monkeypatch, manager, script)
        record = manager.submit(env="test", run_type="single")
        finished = wait_terminal(manager, record["id"])
        assert finished["status"] == "failed"
        assert finished["exit_code"] == 1
        assert finished["result_available"] is True
        assert finished["summary"]["failed"] == 1
        # 退出码 1 且有 JUnit 时错误信息不附 console 尾部。
        assert finished["error_message"] == "存在失败或错误用例（pytest 退出码 1）"

    def test_exit5_no_tests_collected(self, manager, monkeypatch):
        patch_command(monkeypatch, manager, "import sys; sys.exit(5)")
        record = manager.submit(env="test", run_type="single")
        finished = wait_terminal(manager, record["id"])
        assert finished["status"] == "failed"
        assert finished["exit_code"] == 5
        assert finished["result_available"] is False
        assert "未收集到任何用例" in finished["error_message"]

    def test_exit2_without_junit_includes_raw_console(
        self, manager, monkeypatch
    ):
        script = (
            "import sys; "
            "print('Authorization: Bearer supersecret123'); sys.exit(2)"
        )
        patch_command(monkeypatch, manager, script)
        record = manager.submit(env="test", run_type="single")
        finished = wait_terminal(manager, record["id"])
        assert finished["status"] == "failed"
        assert finished["exit_code"] == 2
        assert finished["result_available"] is False
        assert "执行失败（pytest 退出码 2）" in finished["error_message"]
        # Console 是任务原始执行日志，失败摘要保留相同原文，避免排障信息分叉。
        assert "supersecret123" in finished["error_message"]

    def test_failure_message_keeps_the_real_console_tail(
        self, manager, monkeypatch
    ):
        """长单行输出必须保留末尾异常，不能截取文件开头伪装成 tail。"""
        script = "import sys; print('BEGIN-' + 'x' * 12000 + '-FINAL-ERROR'); sys.exit(2)"
        patch_command(monkeypatch, manager, script)

        record = manager.submit(env="test", run_type="single")
        finished = wait_terminal(manager, record["id"])

        assert finished["status"] == "failed"
        assert "FINAL-ERROR" in finished["error_message"]
        assert "BEGIN-" not in finished["error_message"]

    def test_all_skipped_marked_failed(
        self, manager, monkeypatch, tmp_path
    ):
        staged = tmp_path / "staged.xml"
        staged.write_text(
            junit_xml([("case_a", "skipped"), ("case_b", "skipped")]),
            encoding="utf-8",
        )
        patch_command(monkeypatch, manager, copy_junit_script(staged))
        record = manager.submit(env="test", run_type="single")
        finished = wait_terminal(manager, record["id"])
        assert finished["status"] == "failed"
        assert finished["error_code"] == "ALL_TESTS_SKIPPED"
        assert finished["exit_code"] == 0

    def test_timeout_kills_subprocess(self, fake_project, make_manager, monkeypatch):
        manager = make_manager(fake_project, timeout_seconds=1)
        patch_command(monkeypatch, manager, "import time; time.sleep(10)")
        record = manager.submit(env="test", run_type="single")
        finished = wait_terminal(manager, record["id"], timeout=20)
        assert finished["status"] == "failed"
        assert finished["timeout"] is True
        assert finished["error_code"] == "TASK_TIMEOUT"
        assert "超时" in finished["error_message"]

    def test_framework_log_associated_by_pid(self, manager, monkeypatch):
        script = (
            "import os, datetime, pathlib\n"
            "day = datetime.datetime.now().strftime('%Y-%m-%d')\n"
            "d = pathlib.Path('logs') / day\n"
            "d.mkdir(parents=True, exist_ok=True)\n"
            "name = '20200101-000000_test_' + str(os.getpid()) + '.log'\n"
            "(d / name).write_text('framework log line', encoding='utf-8')\n"
            "print('done')"
        )
        patch_command(monkeypatch, manager, script)
        record = manager.submit(env="test", run_type="single")
        finished = wait_terminal(manager, record["id"])
        assert finished["status"] == "succeeded"
        assert finished["log_file"] is not None
        assert finished["log_file"].startswith("logs/")
        assert finished["log_file"].endswith(f"_{record['pid']}.log")

    def test_v2_framework_log_is_associated_from_project_daily_directory(
        self, multi_project_root, make_manager
    ):
        """V2 任务必须从项目/环境/日期目录关联日志，不再依赖任务子目录。"""
        manager = make_manager(multi_project_root)
        day_directory = multi_project_root / "logs/dating/test/2026-08-28"
        day_directory.mkdir(parents=True)
        log_path = day_directory / "20260828_025800_346901_test_20019.log"
        log_path.write_text("framework log line", encoding="utf-8")
        stale_path = day_directory / "20260828_010000_000000_test_20019.log"
        stale_path.write_text("stale framework log", encoding="utf-8")
        record = {
            "schema_version": 2,
            "id": "20260828-025800-ada1",
            "pid": 20019,
            "started_at": "2026-08-28T02:58:00+00:00",
            "project": {"project_id": "dating"},
            "runtime": {"target_env": "test"},
        }

        associated = manager._associate_log_file(
            record,
            "2026-08-28T02:58:02+00:00",
        )

        assert associated == (
            "logs/dating/test/2026-08-28/"
            "20260828_025800_346901_test_20019.log"
        )

    def test_v2_framework_log_rejects_same_pid_outside_task_window(
        self, multi_project_root, make_manager
    ):
        """容器重启复用 PID 时，不得把旧任务原始日志绑定给新任务。"""
        manager = make_manager(multi_project_root)
        day_directory = multi_project_root / "logs/dating/test/2026-08-28"
        day_directory.mkdir(parents=True)
        (day_directory / "20260828_010000_000000_test_20019.log").write_text(
            "old secret log",
            encoding="utf-8",
        )
        record = {
            "schema_version": 2,
            "id": "20260828-025800-ada1",
            "pid": 20019,
            "started_at": "2026-08-28T02:58:00+00:00",
            "project": {"project_id": "dating"},
            "runtime": {"target_env": "test"},
        }

        assert (
            manager._associate_log_file(
                record,
                "2026-08-28T02:58:02+00:00",
            )
            is None
        )

    def test_v3_framework_log_prefers_exact_task_id(
        self, multi_project_root, make_manager
    ):
        """新日志名携带 task ID，必须优先精确关联而不是只靠 PID 时间窗。"""

        manager = make_manager(multi_project_root)
        day_directory = multi_project_root / "logs/dating/test/2026-08-28"
        day_directory.mkdir(parents=True)
        task_id = "20260828-025800-ada1"
        exact = day_directory / (
            f"20260828_025800_100000_test_{task_id}_20019.log"
        )
        exact.write_text("exact", encoding="utf-8")
        (day_directory / "20260828_025801_100000_test_20019.log").write_text(
            "same pid but another task", encoding="utf-8"
        )
        record = {
            "schema_version": 3,
            "id": task_id,
            "pid": 20019,
            "started_at": "2026-08-28T02:58:00+00:00",
            "project": {"project_id": "dating"},
            "runtime": {"target_env": "test"},
        }

        assert manager._associate_log_file(
            record, "2026-08-28T02:58:02+00:00"
        ) == exact.relative_to(multi_project_root).as_posix()


class TestBatchSubmission:
    """批次仍是一个 Task/pytest 进程，条目作为不可变逻辑子项保存。"""

    @staticmethod
    def _add_second_case(root: Path) -> None:
        case_path = root / "projects/dating/data/cases/GetMe.yaml"
        case_path.write_text(
            case_path.read_text(encoding="utf-8")
            + "\n  - id: get_me_second\n"
            + "    name: 再次获取当前用户\n"
            + "    tags: [regression]\n"
            + "    request:\n"
            + "      params:\n"
            + "        locale: zh-CN\n"
            + "    assert:\n"
            + "      http_status: 200\n"
            + "      gateway: {code: 0}\n"
            + "      response: {success: true}\n",
            encoding="utf-8",
        )

    @staticmethod
    def _case_item(manager: TaskManager, case_id: str) -> dict[str, str]:
        task_input = manager._validate_input(
            None,
            "single",
            None,
            None,
            project_id="dating",
            api_id="GetMe",
            case_id=case_id,
        )
        snapshot = manager._build_selected_asset_snapshot(task_input)
        assert snapshot is not None
        return {
            "asset_id": f"GetMe::{case_id}",
            "asset_revision": snapshot["asset_revision"],
        }

    @staticmethod
    def _add_compatible_media_flows(root: Path) -> None:
        """写入执行约束相同、仅展示文案不同的 Analysis/Reply Flow。"""

        flow_directory = root / "projects/dating/data/flows"
        scenario_directory = root / "projects/dating/data/scenarios"
        base_scenario = yaml.safe_load(
            (scenario_directory / "dating_demo_flow.yaml").read_text(
                encoding="utf-8"
            )
        )
        for flow_id, label, description in (
            (
                "multi_image_analysis",
                "分析图片",
                "按聊天顺序选择 1～9 张 Analysis 图片",
            ),
            (
                "multi_image_reply",
                "Reply 图片",
                "按聊天顺序选择 1～9 张 Reply 图片",
            ),
        ):
            flow_document = {
                "name": flow_id,
                "tags": ["interactive"],
                "inputs": {
                    "media_files": {
                        "type": "files",
                        "required": True,
                        "min_items": 1,
                        "max_items": 9,
                        "allowed_content_types": [
                            "image/jpeg",
                            "image/png",
                            "image/webp",
                        ],
                        "max_size_bytes": 7_000_000,
                        "label": label,
                        "description": description,
                    }
                },
                "steps": [{"id": "get_me", "api": "GetMe"}],
            }
            scenario_document = yaml.safe_load(
                yaml.safe_dump(base_scenario, allow_unicode=True, sort_keys=False)
            )
            scenario_document["name"] = f"{flow_id} 成功"
            (flow_directory / f"{flow_id}.yaml").write_text(
                yaml.safe_dump(
                    flow_document,
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (scenario_directory / f"{flow_id}.yaml").write_text(
                yaml.safe_dump(
                    scenario_document,
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

    @staticmethod
    def _flow_item(manager: TaskManager, flow_id: str) -> dict[str, str]:
        """返回 Web 批次契约使用的 Flow 逻辑 ID 与当前资产摘要。"""

        task_input = manager._validate_input(
            None,
            "flow",
            None,
            None,
            project_id="dating",
            flow_id=flow_id,
        )
        snapshot = manager._build_selected_asset_snapshot(task_input)
        assert snapshot is not None
        return {
            "asset_id": flow_id,
            "asset_revision": snapshot["asset_revision"],
        }

    def test_flow_batch_ignores_file_contract_display_copy(
        self, multi_project_root, make_manager
    ):
        """label/description 不影响共享附件能否满足两个 Flow 的执行约束。"""

        self._add_compatible_media_flows(multi_project_root)
        manager = make_manager(multi_project_root)
        items = [
            self._flow_item(manager, "multi_image_analysis"),
            self._flow_item(manager, "multi_image_reply"),
        ]
        task_input = manager._validate_input(
            None,
            "batch",
            None,
            None,
            project_id="dating",
        )

        preview = manager.preview_batch(
            task_input,
            batch_type="flows",
            selection_mode="selected",
            batch_items=items,
            tag_filters=[],
            risk_acknowledgements=[],
            has_uploads=True,
        )

        assert [item["asset_id"] for item in preview["batch"]["items"]] == [
            "multi_image_analysis",
            "multi_image_reply",
        ]

    def test_flow_batch_reports_contract_conflict_before_missing_uploads(
        self, multi_project_root, make_manager
    ):
        """不兼容图片契约必须优先报冲突，避免 Web 因上传区隐藏陷入死路。"""

        self._add_compatible_media_flows(multi_project_root)
        reply_path = (
            multi_project_root
            / "projects/dating/data/flows/multi_image_reply.yaml"
        )
        reply_document = yaml.safe_load(reply_path.read_text(encoding="utf-8"))
        reply_document["inputs"]["media_files"]["max_items"] = 8
        reply_path.write_text(
            yaml.safe_dump(reply_document, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        manager = make_manager(multi_project_root)
        items = [
            self._flow_item(manager, "multi_image_analysis"),
            self._flow_item(manager, "multi_image_reply"),
        ]
        task_input = manager._validate_input(
            None,
            "batch",
            None,
            None,
            project_id="dating",
        )

        with pytest.raises(SubmissionError) as exc_info:
            manager.preview_batch(
                task_input,
                batch_type="flows",
                selection_mode="selected",
                batch_items=items,
                tag_filters=[],
                risk_acknowledgements=[],
                has_uploads=False,
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == "BATCH_INPUT_CONTRACT_CONFLICT"

    def test_batch_start_failure_closes_all_pending_items(
        self, multi_project_root, make_manager, monkeypatch
    ):
        """pytest 未启动时根任务和逻辑子项都必须进入一致的终态。"""

        self._add_second_case(multi_project_root)
        manager = make_manager(multi_project_root)
        items = [
            self._case_item(manager, "get_me_success"),
            self._case_item(manager, "get_me_second"),
        ]
        monkeypatch.setattr(
            manager,
            "_build_command",
            lambda task_input, junit_path: [
                "/nonexistent-batch-interpreter-xyz",
                "-c",
                "pass",
            ],
        )

        with pytest.raises(OSError):
            manager.submit(
                project_id="dating",
                run_type="batch",
                batch_type="cases",
                selection_mode="selected",
                batch_items=items,
            )

        failed = manager.store.list()[0]
        assert failed["status"] == "failed"
        assert [item["status"] for item in failed["batch"]["items"]] == [
            "not_run",
            "not_run",
        ]

    def test_required_media_batch_retry_clones_inputs_and_rejects_missing_source(
        self, multi_project_root, make_manager, monkeypatch, tmp_path
    ):
        """批次重试先复用附件契约，再由 clone_inputs 完整校验源图片。"""

        self._add_compatible_media_flows(multi_project_root)
        manager = make_manager(multi_project_root)
        item = self._flow_item(manager, "multi_image_analysis")
        staged = tmp_path / "media-batch.xml"
        staged.write_text(
            junit_xml(
                [
                    (
                        "test_gateway_flow[dating::multi_image_analysis]",
                        "passed",
                    )
                ]
            ),
            encoding="utf-8",
        )
        patch_command(monkeypatch, manager, copy_junit_script(staged))
        original = manager.submit(
            project_id="dating",
            run_type="batch",
            batch_type="flows",
            selection_mode="selected",
            batch_items=[item],
            uploads=[png_upload("chat_01.png")],
        )
        original_finished = wait_terminal(manager, original["id"])

        retried = manager.retry(original["id"])
        retried_finished = wait_terminal(manager, retried["id"])
        assert retried_finished["status"] == "succeeded"
        assert retried_finished["retry_of"] == original["id"]
        assert retried_finished["attachments"][0]["sha256"] == (
            original_finished["attachments"][0]["sha256"]
        )

        source = (
            multi_project_root
            / original_finished["attachments"][0]["task_relative_path"]
        )
        source.unlink()
        with pytest.raises(SubmissionError) as exc_info:
            manager.retry(original["id"])

        assert exc_info.value.status_code == 409
        assert exc_info.value.error_code == "TASK_INPUTS_MISSING"

    def test_selected_case_batch_creates_one_v3_task(
        self, multi_project_root, make_manager, monkeypatch
    ):
        self._add_second_case(multi_project_root)
        manager = make_manager(multi_project_root)
        items = [
            self._case_item(manager, "get_me_second"),
            self._case_item(manager, "get_me_success"),
        ]
        patch_command(monkeypatch, manager, "print('batch')")

        record = manager.submit(
            project_id="dating",
            run_type="batch",
            batch_type="cases",
            selection_mode="selected",
            batch_items=items,
        )

        stored = manager.store.load(record["id"])
        assert stored["schema_version"] == 3
        assert stored["selection"]["run_type"] == "batch"
        assert stored["batch"]["type"] == "cases"
        assert stored["batch"]["item_count"] == 2
        assert [item["asset_id"] for item in stored["batch"]["items"]] == [
            "GetMe::get_me_success",
            "GetMe::get_me_second",
        ]
        assert stored["asset_snapshot"]["asset_type"] == "batch"
        assert len(
            stored["asset_snapshot"]["resolved_execution_asset"]["items"]
        ) == 2

    def test_batch_rejects_runtime_overrides(
        self, multi_project_root, make_manager
    ):
        manager = make_manager(multi_project_root)
        item = self._case_item(manager, "get_me_success")

        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(
                project_id="dating",
                run_type="batch",
                batch_type="cases",
                selection_mode="selected",
                batch_items=[item],
                runtime_overrides={"locale": "zh-CN"},
            )

        assert exc_info.value.error_code == "RUNTIME_OVERRIDE_NOT_SUPPORTED"

    def test_all_safe_excludes_risk_assets_and_manual_requires_ack(
        self, multi_project_root, make_manager
    ):
        """自动安全范围排除 explicit；手动选择必须显式确认风险。"""

        self._add_second_case(multi_project_root)
        case_path = multi_project_root / "projects/dating/data/cases/GetMe.yaml"
        document = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        document["cases"][1]["tags"] = ["explicit"]
        case_path.write_text(
            yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        manager = make_manager(multi_project_root)
        task_input = manager._validate_input(
            None,
            "batch",
            None,
            None,
            project_id="dating",
        )

        preview = manager.preview_batch(
            task_input,
            batch_type="cases",
            selection_mode="all_safe",
            batch_items=[],
            tag_filters=[],
            risk_acknowledgements=[],
            has_uploads=False,
        )
        assert [item["asset_id"] for item in preview["batch"]["items"]] == [
            "GetMe::get_me_success"
        ]

        explicit = self._case_item(manager, "get_me_second")
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(
                project_id="dating",
                run_type="batch",
                batch_type="cases",
                selection_mode="selected",
                batch_items=[explicit],
            )
        assert exc_info.value.error_code == "BATCH_UNSAFE_CONFIRMATION_REQUIRED"

    def test_batch_junit_maps_each_item_and_keeps_later_result(
        self, multi_project_root, make_manager, monkeypatch, tmp_path
    ):
        """一个子项失败时，聚合结果仍必须包含并映射后续子项。"""

        self._add_second_case(multi_project_root)
        manager = make_manager(multi_project_root)
        items = [
            self._case_item(manager, "get_me_success"),
            self._case_item(manager, "get_me_second"),
        ]
        staged = tmp_path / "batch.xml"
        staged.write_text(
            junit_xml(
                [
                    (
                        "test_gateway_single_case[dating::GetMe::get_me_success]",
                        "failure",
                    ),
                    (
                        "test_gateway_single_case[dating::GetMe::get_me_second]",
                        "passed",
                    ),
                ]
            ),
            encoding="utf-8",
        )
        patch_command(
            monkeypatch,
            manager,
            copy_junit_script(staged) + "; raise SystemExit(1)",
        )

        task = manager.submit(
            project_id="dating",
            run_type="batch",
            batch_type="cases",
            selection_mode="selected",
            batch_items=items,
        )
        finished = wait_terminal(manager, task["id"])

        assert finished["status"] == "failed"
        assert [item["status"] for item in finished["batch"]["items"]] == [
            "failed",
            "passed",
        ]
        assert finished["summary"]["total"] == 2

    def test_batch_missing_junit_item_fails_closed(
        self, multi_project_root, make_manager, monkeypatch, tmp_path
    ):
        """选中的条目若没有 testcase，不能把部分报告误报为成功。"""

        self._add_second_case(multi_project_root)
        manager = make_manager(multi_project_root)
        items = [
            self._case_item(manager, "get_me_success"),
            self._case_item(manager, "get_me_second"),
        ]
        staged = tmp_path / "partial.xml"
        staged.write_text(
            junit_xml(
                [
                    (
                        "test_gateway_single_case[dating::GetMe::get_me_success]",
                        "passed",
                    )
                ]
            ),
            encoding="utf-8",
        )
        patch_command(monkeypatch, manager, copy_junit_script(staged))

        task = manager.submit(
            project_id="dating",
            run_type="batch",
            batch_type="cases",
            selection_mode="selected",
            batch_items=items,
        )
        finished = wait_terminal(manager, task["id"])

        assert finished["status"] == "failed"
        assert finished["error_code"] == "BATCH_RESULT_INCOMPLETE"
        assert finished["batch"]["items"][1]["status"] == "not_run"


class TestQueueAndCancel:
    """持久 FIFO 队列与运行/排队取消。"""

    def test_second_submit_is_queued_while_first_runs(
        self, manager, monkeypatch
    ):
        calls = [0]

        def fake_build(_task_input, _junit_path):
            calls[0] += 1
            delay = 0.5 if calls[0] == 1 else 0
            return [
                sys.executable,
                "-c",
                f"import time; time.sleep({delay})",
            ]

        monkeypatch.setattr(manager, "_build_command", fake_build)
        first = manager.submit(env="test", run_type="single")
        wait_running(manager, first["id"])
        second = manager.submit(env="test", run_type="single")

        queued = manager.store.load(second["id"])
        assert queued["status"] == "pending"
        assert queued["queue"]["sequence"] > first["queue"]["sequence"]

        first_finished = wait_terminal(manager, first["id"])
        second_finished = wait_terminal(manager, second["id"])
        assert first_finished["status"] == "succeeded"
        assert second_finished["status"] == "succeeded"
        assert second_finished["started_at"] >= first_finished["finished_at"]

    def test_queue_full_rejects_only_after_pending_capacity_is_used(
        self, fake_project, make_manager, monkeypatch
    ):
        """运行中任务不占 pending 配额；真正排队满后返回稳定错误码。"""

        manager = make_manager(fake_project, max_pending_tasks=1)
        patch_command(monkeypatch, manager, "import time; time.sleep(1)")
        first = manager.submit(env="test", run_type="single")
        wait_running(manager, first["id"])
        queued = manager.submit(env="test", run_type="single")
        assert manager.store.load(queued["id"])["status"] == "pending"

        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="single")

        assert exc_info.value.status_code == 429
        assert exc_info.value.error_code == "QUEUE_FULL"

    @staticmethod
    def _runtime_plan_for_credentials(credential_ids: list[str]):
        """生成测试用规划器，每次提交冻结指定 Credential ID。"""

        remaining = iter(credential_ids)

        def provider(task_id, _signed_context, _selection):
            credential_id = next(remaining)
            return {
                "runtime_context_id": f"rtx-{task_id}",
                "runtime_scope_id": "scope-dating-dev-test",
                "platform_project_id": "platform-dating",
                "platform_environment": "dev",
                "target_env": "test",
                "snapshot_selector": {
                    "runtime_scope_id": "scope-dating-dev-test",
                    "credential_versions": {credential_id: 1},
                },
            }

        return provider

    def test_concurrency_two_allows_different_credentials(
        self, multi_project_root, make_manager, monkeypatch
    ):
        """显式并发 2 时，不同 Credential 的任务可以同时 running。"""

        manager = make_manager(
            multi_project_root,
            max_concurrency=2,
            runtime_plan_provider=self._runtime_plan_for_credentials(
                ["credential-a", "credential-b"]
            ),
        )
        patch_command(monkeypatch, manager, "import time; time.sleep(0.8)")
        first = manager.submit(
            project_id="dating",
            run_type="single",
            api_id="GetMe",
            case_id="get_me_success",
        )
        wait_running(manager, first["id"])
        second = manager.submit(
            project_id="dating",
            run_type="single",
            api_id="GetMe",
            case_id="get_me_success",
        )

        assert manager.store.load(first["id"])["status"] == "running"
        assert manager.store.load(second["id"])["status"] == "running"

    def test_concurrency_two_serializes_same_credential(
        self, multi_project_root, make_manager, monkeypatch
    ):
        """即使并发槽位空闲，相同 Credential 仍必须保持 FIFO 串行。"""

        manager = make_manager(
            multi_project_root,
            max_concurrency=2,
            runtime_plan_provider=self._runtime_plan_for_credentials(
                ["credential-a", "credential-a"]
            ),
        )
        patch_command(monkeypatch, manager, "import time; time.sleep(0.8)")
        first = manager.submit(
            project_id="dating",
            run_type="single",
            api_id="GetMe",
            case_id="get_me_success",
        )
        wait_running(manager, first["id"])
        second = manager.submit(
            project_id="dating",
            run_type="single",
            api_id="GetMe",
            case_id="get_me_success",
        )

        assert manager.store.load(second["id"])["status"] == "pending"

    def test_cancel_queued_task_never_starts(self, manager, monkeypatch):
        """取消 pending 任务应立即终态，不能等前一进程结束后误启动。"""

        patch_command(monkeypatch, manager, "import time; time.sleep(1)")
        first = manager.submit(env="test", run_type="single")
        wait_running(manager, first["id"])
        queued = manager.submit(env="test", run_type="single")
        assert manager.store.load(queued["id"])["status"] == "pending"

        cancelled = manager.cancel(queued["id"])

        assert cancelled["status"] == "cancelled"
        assert cancelled["pid"] is None
        assert cancelled["started_at"] is None
        wait_terminal(manager, first["id"])
        manager.wait_idle()
        assert manager.store.load(queued["id"])["status"] == "cancelled"

    def test_cancel_running_task(self, manager, monkeypatch):
        patch_command(monkeypatch, manager, "import time; time.sleep(10)")
        record = manager.submit(env="test", run_type="single")
        wait_running(manager, record["id"])
        cancelled = manager.cancel(record["id"])
        assert cancelled["cancel_requested_at"] is not None
        manager.wait_idle()
        finished = manager.store.load(record["id"])
        assert finished["status"] == "cancelled"
        assert finished["finished_at"] is not None
        # 取消后槽位释放。
        patch_command(monkeypatch, manager, "print('ok')")
        next_record = manager.submit(env="test", run_type="single")
        assert wait_terminal(manager, next_record["id"])["status"] == "succeeded"

    def test_cancel_missing_task(self, manager):
        with pytest.raises(SubmissionError) as exc_info:
            manager.cancel("20260101-000000-0000")
        assert exc_info.value.status_code == 404
        assert exc_info.value.error_code == "TASK_NOT_FOUND"

    def test_cancel_terminal_task_rejected(self, manager, monkeypatch):
        patch_command(monkeypatch, manager, "print('ok')")
        record = manager.submit(env="test", run_type="single")
        wait_terminal(manager, record["id"])
        manager.wait_idle()
        with pytest.raises(SubmissionError) as exc_info:
            manager.cancel(record["id"])
        assert exc_info.value.status_code == 409
        assert exc_info.value.error_code == "TASK_TERMINATED"

    def test_cancel_races_with_completion(self, manager, monkeypatch, tmp_path):
        # 取消与正常完成竞态：无论先后，终态唯一且记录一致。
        staged = tmp_path / "staged.xml"
        staged.write_text(junit_xml([("case_a", "passed")]), encoding="utf-8")
        patch_command(monkeypatch, manager, copy_junit_script(staged))
        record = manager.submit(env="test", run_type="single")
        try:
            manager.cancel(record["id"])
        except SubmissionError:
            pass  # 任务可能已先行进入终态。
        manager.wait_idle()
        finished = manager.store.load(record["id"])
        assert finished["status"] in TERMINAL_STATUSES
        assert finished["finished_at"] is not None


class TestRecoveryAndStartFailure:
    """启动恢复与子进程启动失败。"""

    def test_recover_pending_dispatch_cleans_private_files_before_redispatch(
        self, multi_project_root, make_manager, monkeypatch
    ):
        """预占后崩溃的 pending 任务必须先销毁旧临时文件再重新排队。"""

        manager = make_manager(multi_project_root)
        task_id = "20260101-000000-0010"
        record = {
            "schema_version": 3,
            "id": task_id,
            "status": "pending",
            "project": {"project_id": "dating"},
            "input": {},
            "queue": {
                "sequence": 10,
                "queued_at": "2026-01-01T00:00:00+08:00",
                "dispatched_at": "2026-01-01T00:00:01+08:00",
            },
        }
        manager.store.save(record)
        runtime_dir = multi_project_root / "runtime" / "dating" / task_id
        runtime_dir.mkdir(parents=True)
        snapshot_path = runtime_dir / "snapshot.json"
        snapshot_path.write_text('{"secret":"stale"}', encoding="utf-8")
        execution_path = runtime_dir / "execution-asset.json"
        execution_path.write_text('{"asset":"stale"}', encoding="utf-8")
        console_path = runtime_dir / "console.log"
        console_path.write_text("keep diagnostic\n", encoding="utf-8")
        monkeypatch.setattr(manager, "_dispatch_pending", lambda **_kwargs: None)

        manager.recover_on_startup()

        recovered = manager.store.load(task_id)
        assert recovered["status"] == "pending"
        assert recovered["queue"]["dispatched_at"] is None
        assert not snapshot_path.exists()
        assert not execution_path.exists()
        assert console_path.read_text(encoding="utf-8") == "keep diagnostic\n"

    def test_refreshed_dispatch_selector_is_saved_before_snapshot_file_creation(
        self, multi_project_root, make_manager, monkeypatch
    ):
        """物化成功后应立即落盘新 Credential 版本，缩小重启重复调度窗口。"""

        old_selector = {
            "release_id": "release-dating-v3",
            "credential_versions": {"cred-dating": 4},
        }
        refreshed_selector = {
            "release_id": "release-dating-v3",
            "credential_versions": {"cred-dating": 5},
        }

        def plan(task_id: str, signed_context: str, selection: dict) -> dict:
            del task_id, signed_context, selection
            return {
                "runtime_context_id": "rtx-dating-dispatch",
                "platform_project_id": "platform-dating",
                "platform_environment": "dev",
                "target_env": "test",
                "runtime_scope_id": "scope-dating-test",
                "release_id": "release-dating-v3",
                "release_version": 3,
                "snapshot_selector": old_selector,
            }

        def materialize(record: dict) -> tuple[dict, dict]:
            assert record["runtime_context"]["snapshot_selector"] == old_selector
            return (
                {
                    "runtime_scope_id": "scope-dating-test",
                    "release_id": "release-dating-v3",
                    "release_version": 3,
                    "snapshot_selector": refreshed_selector,
                    "settings": {},
                },
                {
                    "runtime_scope_id": "scope-dating-test",
                    "release_id": "release-dating-v3",
                    "release_version": 3,
                    "credential_profiles": [],
                    "process_environment": {},
                },
            )

        manager = make_manager(
            multi_project_root,
            runtime_plan_provider=plan,
            runtime_snapshot_provider=materialize,
        )

        def fail_snapshot_write(*_args, **_kwargs):
            raise OSError("simulated snapshot disk failure")

        monkeypatch.setattr(
            "web.task_manager.create_runtime_snapshot_file",
            fail_snapshot_write,
        )

        with pytest.raises(OSError):
            manager.submit(
                project_id="dating",
                run_type="single",
                api_id="GetMe",
                case_id="get_me_success",
            )

        failed = manager.store.list()[0]
        assert failed["status"] == "failed"
        assert failed["runtime_context"]["snapshot_selector"] == refreshed_selector

    def test_cancel_after_popen_does_not_revive_pending_task(
        self, manager, monkeypatch
    ):
        """Popen 已返回但尚未登记时取消，子进程应终止且 cancelled 不可覆盖。"""

        patch_command(
            monkeypatch,
            manager,
            "import time; time.sleep(2)",
        )
        real_popen = subprocess.Popen
        started_processes: list[subprocess.Popen] = []

        def racing_popen(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            started_processes.append(proc)
            pending = manager.store.list()[0]
            assert pending["status"] == "pending"
            manager.cancel(pending["id"])
            # cancel 发生在已预占任务的 Popen 窗口时，槽位和 Credential
            # 隔离锁必须保留到启动线程终止刚创建的进程；否则下一条同凭证
            # 任务可能在孤儿进程退出前被调度，造成短暂并发。
            assert pending["id"] in manager._active_ids
            return proc

        monkeypatch.setattr("web.task_manager.subprocess.Popen", racing_popen)

        created = manager.submit(env="test", run_type="single")

        persisted = manager.store.load(created["id"])
        assert persisted["status"] == "cancelled"
        assert persisted["pid"] is None
        assert started_processes[0].poll() is not None
        assert created["id"] not in manager._procs

    def test_recover_on_startup(self, fake_project, make_manager, monkeypatch):
        manager = make_manager(fake_project)
        store = manager.store

        def seed(suffix: str, status: str, *, project_id: str | None = None) -> str:
            task_id = f"20260101-000000-{suffix}"
            record = {"id": task_id, "status": status, "input": {}}
            if project_id is not None:
                record["project"] = {"project_id": project_id}
            store.save(record)
            return task_id

        running_id = seed("0001", "running", project_id="dating")
        pending_id = seed("0002", "pending")
        done_id = seed("0003", "succeeded")
        # 模拟服务在平台快照落盘后异常退出：重启恢复必须删除 Secret 快照，
        # 但同目录 console.log 属于任务审计产物，不能一并递归删除。
        runtime_dir = fake_project / "runtime" / "dating" / running_id
        runtime_dir.mkdir(parents=True)
        snapshot_path = runtime_dir / "snapshot.json"
        snapshot_path.write_text('{"secret":"must-not-survive-restart"}', encoding="utf-8")
        snapshot_path.chmod(0o600)
        execution_path = runtime_dir / "execution-asset.json"
        execution_path.write_text('{"private":"execution"}', encoding="utf-8")
        execution_path.chmod(0o600)
        console_path = runtime_dir / "console.log"
        console_path.write_text("diagnostic output\n", encoding="utf-8")

        # 只验证恢复状态迁移；pending 的真实重新启动由独立队列测试覆盖。
        monkeypatch.setattr(manager, "_dispatch_pending", lambda **_kwargs: None)
        recovered = manager.recover_on_startup()
        assert recovered == 1
        assert store.load(running_id)["status"] == "failed"
        assert store.load(running_id)["error_message"] == "服务重启，任务中断"
        assert store.load(pending_id)["status"] == "pending"
        assert store.load(pending_id)["queue"]["sequence"] > 0
        assert store.load(done_id)["status"] == "succeeded"
        assert not snapshot_path.exists()
        assert not execution_path.exists()
        assert console_path.read_text(encoding="utf-8") == "diagnostic output\n"

    def test_recover_running_v3_batch_closes_pending_items(
        self, fake_project, make_manager, monkeypatch
    ):
        """服务重启中断批次时，不得留下终态任务中的 pending 子项。"""

        manager = make_manager(fake_project)
        task_id = "20260101-000000-0004"
        manager.store.save(
            {
                "schema_version": 3,
                "id": task_id,
                "status": "running",
                "project": {"project_id": "dating"},
                "input": {},
                "batch": {
                    "type": "cases",
                    "items": [
                        {"asset_id": "GetMe::one", "status": "pending"},
                        {"asset_id": "GetMe::two", "status": "pending"},
                    ],
                },
            }
        )
        monkeypatch.setattr(manager, "_dispatch_pending", lambda **_kwargs: None)

        manager.recover_on_startup()

        recovered = manager.store.load(task_id)
        assert recovered["status"] == "failed"
        assert [item["status"] for item in recovered["batch"]["items"]] == [
            "not_run",
            "not_run",
        ]

    def test_start_failure_releases_slot(self, manager, monkeypatch):
        # 解释器不存在导致 Popen 失败：任务置 failed，槽位释放。
        monkeypatch.setattr(
            manager,
            "_build_command",
            lambda task_input, junit_path: ["/nonexistent-interpreter-xyz", "-c", "pass"],
        )
        with pytest.raises(OSError):
            manager.submit(env="test", run_type="single")
        records = manager.store.list()
        assert len(records) == 1
        assert records[0]["status"] == "failed"
        assert records[0]["error_message"] == "子进程启动失败，任务未执行"

        # 槽位已释放：恢复正常命令后可再次提交。
        patch_command(monkeypatch, manager, "print('ok')")
        record = manager.submit(env="test", run_type="single")
        assert wait_terminal(manager, record["id"])["status"] == "succeeded"
    def test_runtime_selector_is_persisted_and_secret_only_materialized_in_memory(
        self, fake_project, make_manager, monkeypatch
    ):
        """任务落盘不含签名/Secret，子进程启动前才按 selector 物化。"""

        calls: dict[str, object] = {}

        def plan(task_id: str, signed_context: str) -> dict:
            calls["plan"] = (task_id, signed_context)
            return {
                "runtime_context_id": "rtx_autotest_user_1",
                "runtime_context_expires_at": "2026-08-24T12:00:00Z",
                "snapshot_selector": {
                    "release_id": "rel_autotest_v1",
                    "credential_versions": {"ucred_gateway": 3},
                },
            }

        def materialize(record: dict) -> tuple[dict[str, str], dict]:
            calls["materialize"] = record["runtime_context"]["runtime_context_id"]
            return (
                {"AUTH_TOKEN": "runtime-secret-sentinel"},
                {"release_id": "rel_autotest_v1", "credential_version": 3},
            )

        manager = make_manager(
            fake_project,
            runtime_plan_provider=plan,
            runtime_environment_provider=materialize,
        )
        staged = fake_project / "runtime-junit.xml"
        staged.write_text(junit_xml([("runtime", "passed")]), encoding="utf-8")
        patch_command(
            monkeypatch,
            manager,
            "import os, shutil; "
            "assert os.environ['AUTH_TOKEN'] == 'runtime-secret-sentinel'; "
            f"shutil.copy({str(staged)!r}, '{{junit}}')",
        )

        created = manager.submit(
            env="test",
            run_type="single",
            signed_user_context="signed-autotest-user-1",
        )
        finished = wait_terminal(manager, created["id"])

        assert finished["status"] == "succeeded"
        assert calls["plan"] == (created["id"], "signed-autotest-user-1")
        assert calls["materialize"] == "rtx_autotest_user_1"
        persisted = json.dumps(finished, ensure_ascii=False)
        assert "signed-autotest-user-1" not in persisted
        assert "runtime-secret-sentinel" not in persisted
        assert finished["runtime_context"]["snapshot_selector"]["credential_versions"] == {
            "ucred_gateway": 3
        }
