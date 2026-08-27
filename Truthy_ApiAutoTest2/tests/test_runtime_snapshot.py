"""platform/local 互斥配置源与任务快照文件的行为测试。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from utils.custom.config_loader import (
    ConfigError,
    load_settings,
    runtime_snapshot_file,
    validate_settings_contract,
)


def _snapshot(**overrides: object) -> dict[str, object]:
    """返回平台模式最小版本化快照，调用方可覆盖作用域字段。"""
    data: dict[str, object] = {
        "schema_version": 1,
        "task_id": "task-1",
        "runtime_scope_id": "scope-1",
        "platform_environment": "dev",
        "tool_id": "api-autotest",
        "platform_project_id": "platform-project-1",
        "project_id": "dating",
        "target_env": "test",
        "config_release_id": "release-1",
        "config_release_version": 3,
        "settings": {
            "gateway_base_url": "https://snapshot.example",
            "timeout": 12,
            "comm": {"device_id": "snapshot-device", "auth_token": "snapshot-token"},
            "flow": {"analysis": {"poll_interval_seconds": 1, "timeout_seconds": 90}},
        },
        "credential_profiles": [{"id": "anonymous_session", "version": 4}],
        "snapshot_time": "2026-08-27T12:00:00+08:00",
    }
    data.update(overrides)
    return data


def test_platform_snapshot_is_only_configuration_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """平台模式必须忽略根 YAML、.env 和继承环境变量，防止跨 Scope 污染。"""
    (tmp_path / "config/env").mkdir(parents=True)
    (tmp_path / "config/settings.yaml").write_text(
        "gateway_base_url: https://root.example\ncomm:\n  device_id: root-device\n",
        encoding="utf-8",
    )
    (tmp_path / "config/env/test.yaml").write_text(
        "timeout: 999\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("DEVICE_ID=dotenv-device\n", encoding="utf-8")
    monkeypatch.setenv("DEVICE_ID", "process-device")
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    snapshot_path.chmod(0o600)

    settings = load_settings(
        "test",
        project_root=tmp_path,
        config_source="platform",
        snapshot_file=snapshot_path,
        project_id="dating",
        task_id="task-1",
        runtime_scope_id="scope-1",
    )

    assert settings["gateway_base_url"] == "https://snapshot.example"
    assert settings["timeout"] == 12
    assert settings["comm"]["device_id"] == "snapshot-device"
    assert settings["runtime_metadata"]["runtime_scope_id"] == "scope-1"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"schema_version": 2}, "schema_version"),
        ({"project_id": "truthy"}, "project_id"),
        ({"target_env": "prod"}, "target_env"),
        ({"runtime_scope_id": "scope-2"}, "runtime_scope_id"),
        ({"task_id": "task-2"}, "task_id"),
    ],
)
def test_platform_snapshot_identity_mismatch_fails_closed(
    tmp_path: Path,
    override: dict[str, object],
    message: str,
) -> None:
    """快照版本或不可变 Scope 身份不一致时不得回退本地配置。"""
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot(**override)), encoding="utf-8")
    snapshot_path.chmod(0o600)

    with pytest.raises(ConfigError, match=message):
        load_settings(
            "test",
            project_root=tmp_path,
            config_source="platform",
            snapshot_file=snapshot_path,
            project_id="dating",
            task_id="task-1",
            runtime_scope_id="scope-1",
        )


def test_platform_snapshot_requires_private_regular_file(tmp_path: Path) -> None:
    """平台快照缺失、权限过宽或为符号链接时均应在读取前失败。"""
    missing = tmp_path / "missing.json"
    with pytest.raises(ConfigError, match="快照"):
        load_settings(
            "test", config_source="platform", snapshot_file=missing, project_id="dating"
        )

    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(json.dumps(_snapshot()), encoding="utf-8")
    unsafe.chmod(0o644)
    with pytest.raises(ConfigError, match="0600"):
        load_settings(
            "test", config_source="platform", snapshot_file=unsafe, project_id="dating"
        )


def test_runtime_snapshot_context_manager_creates_0600_and_deletes_terminal_file(
    tmp_path: Path,
) -> None:
    """TaskManager 可复用的公共上下文管理器应保证 0600 创建和终态清理。"""
    expected: Path | None = None
    with runtime_snapshot_file(tmp_path, "dating", "task-1", _snapshot()) as path:
        expected = path
        assert path.is_file()
        assert os.stat(path).st_mode & 0o777 == 0o600
        assert json.loads(path.read_text(encoding="utf-8"))["project_id"] == "dating"
    assert expected is not None and not expected.exists()


def test_platform_snapshot_normalizes_session_values_without_process_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """平台快照中的会话字段应进入运行上下文，但同名宿主环境值必须忽略。"""
    snapshot = _snapshot()
    settings = snapshot["settings"]
    assert isinstance(settings, dict)
    settings["runtime_variables"] = {
        "REFRESH_TOKEN": "snapshot-refresh",
        "EXPIRES_TIME": 1800000000000,
        "REFRESH_EXPIRES_TIME": 1800100000000,
        "ADMIN_SESSION_TOKEN": "snapshot-admin",
        "analysis_poll_interval_seconds": 1,
    }
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    snapshot_path.chmod(0o600)
    monkeypatch.setenv("REFRESH_TOKEN", "inherited-refresh")
    monkeypatch.setenv("ADMIN_SESSION_TOKEN", "inherited-admin")

    loaded = load_settings(
        "test",
        config_source="platform",
        snapshot_file=snapshot_path,
        project_id="dating",
    )

    assert loaded["runtime_session"]["refresh_token"] == "snapshot-refresh"
    assert loaded["runtime_session"]["expires_time"] == 1800000000000
    assert loaded["runtime_variables"]["admin_session_token"] == "snapshot-admin"
    assert loaded["runtime_variables"]["analysis_poll_interval_seconds"] == 1
    assert "REFRESH_TOKEN" not in loaded["runtime_variables"]


def test_platform_snapshot_normalizes_manifest_logical_gateway_and_flow_keys(
    tmp_path: Path,
) -> None:
    """Release 逻辑键应映射为 Gateway/Flow 运行结构，不读取项目环境 YAML。"""
    snapshot = _snapshot(
        settings={
            "gateway.base_url": "https://gateway.scope.example",
            "gateway.path": "/gateway/scoped-invoke",
            "gateway.method": "POST",
            "gateway.comm": {"device_id": "scope-device", "platform": "web"},
            "flow.analysis.poll_interval_seconds": 1.5,
            "flow.analysis.timeout_seconds": 75,
        }
    )
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    snapshot_path.chmod(0o600)

    loaded = load_settings(
        "test",
        config_source="platform",
        snapshot_file=snapshot_path,
        project_id="dating",
    )

    assert loaded["gateway_base_url"] == "https://gateway.scope.example"
    assert loaded["gateway_path"] == "/gateway/scoped-invoke"
    assert loaded["comm"] == {"device_id": "scope-device", "platform": "web"}
    assert loaded["flow"]["analysis"] == {
        "poll_interval_seconds": 1.5,
        "timeout_seconds": 75,
    }


def test_platform_settings_contract_reports_missing_logical_keys() -> None:
    """项目 Manifest 所需 Release 键缺失时应在网络请求前给出逻辑键名。"""
    with pytest.raises(ConfigError, match="flow.analysis.timeout_seconds"):
        validate_settings_contract(
            {
                "gateway_base_url": "https://gateway.example",
                "gateway_path": "/gateway/invoke",
                "comm": {"device_id": "device"},
                "flow": {"analysis": {"poll_interval_seconds": 1}},
            },
            (
                "gateway.base_url",
                "gateway.path",
                "gateway.comm",
                "flow.analysis.poll_interval_seconds",
                "flow.analysis.timeout_seconds",
            ),
        )
