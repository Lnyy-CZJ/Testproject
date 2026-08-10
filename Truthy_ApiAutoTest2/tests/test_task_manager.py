"""TaskManager 单元测试。

功能说明:
    覆盖提交参数校验、两级凭证预检、单槽位语义、退出码映射、超时、
    取消、取消/完成竞态、子进程启动失败、启动恢复与框架日志关联。
    全部子进程经 patch_command 替换为 ``python -c`` 模拟脚本，不发真实请求。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from conftest import DOTENV_WITHOUT_ADMIN, junit_xml, patch_command
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

        def seed(suffix: str, status: str) -> str:
            task_id = f"20260101-000000-{suffix}"
            store.save({"id": task_id, "status": status, "input": {}})
            return task_id

        running_id = seed("0001", "running")
        pending_id = seed("0002", "pending")
        done_id = seed("0003", "succeeded")

        recovered = manager.recover_on_startup()
        assert recovered == 2
        assert store.load(running_id)["status"] == "failed"
        assert store.load(running_id)["error_message"] == "服务重启，任务中断"
        assert store.load(pending_id)["status"] == "failed"
        assert store.load(done_id)["status"] == "succeeded"

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
