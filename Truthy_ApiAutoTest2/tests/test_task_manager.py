"""TaskManager 单元测试。

功能说明:
    覆盖提交参数校验、两级凭证预检、单槽位语义、退出码映射、超时、
    取消、取消/完成竞态、子进程启动失败、启动恢复与框架日志关联。
    全部子进程经 patch_command 替换为 ``python -c`` 模拟脚本，不发真实请求。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conftest import BASE_DOTENV, DOTENV_WITHOUT_ADMIN, junit_xml, patch_command
from web.task_manager import SubmissionError, TaskManager

# 终端状态集合，与实现保持一致。
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


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
        manager = make_manager(multi_project_root)
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
            tag="smoke",
            signed_user_context="signed-user",
        )
        finished = wait_terminal(manager, record["id"])

        assert finished["schema_version"] == 2
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
            "tag": "smoke",
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
            tag="regression",
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

    def test_exit2_without_junit_includes_redacted_console(
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
        # 二次脱敏兜底：console 尾部进入错误信息前必须掩码。
        assert "supersecret123" not in finished["error_message"]
        assert "[REDACTED]" in finished["error_message"]

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


class TestSlotAndCancel:
    """单槽位语义与取消。"""

    def test_second_submit_rejected_while_busy(
        self, manager, monkeypatch
    ):
        patch_command(monkeypatch, manager, "import time; time.sleep(2)")
        first = manager.submit(env="test", run_type="single")
        wait_running(manager, first["id"])
        with pytest.raises(SubmissionError) as exc_info:
            manager.submit(env="test", run_type="single")
        assert exc_info.value.status_code == 409
        assert exc_info.value.error_code == "SLOT_BUSY"
        # 任务结束后槽位释放，可再次提交。
        wait_terminal(manager, first["id"])
        manager.wait_idle()
        patch_command(monkeypatch, manager, "print('ok')")
        second = manager.submit(env="test", run_type="single")
        finished = wait_terminal(manager, second["id"])
        assert finished["status"] == "succeeded"

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

    def test_recover_on_startup(self, fake_project, make_manager):
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
        console_path = runtime_dir / "console.log"
        console_path.write_text("diagnostic output\n", encoding="utf-8")

        recovered = manager.recover_on_startup()
        assert recovered == 2
        assert store.load(running_id)["status"] == "failed"
        assert store.load(running_id)["error_message"] == "服务重启，任务中断"
        assert store.load(pending_id)["status"] == "failed"
        assert store.load(done_id)["status"] == "succeeded"
        assert not snapshot_path.exists()
        assert console_path.read_text(encoding="utf-8") == "diagnostic output\n"

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
