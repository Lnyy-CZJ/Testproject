"""pytest 不可变执行资产接入测试。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_cases.test_gateway_flow as flow_module
import test_cases.test_single_api as single_module
import test_cases.conftest as conftest_module
from utils.custom.runtime_overrides import canonical_sha256


TASK_ID = "20260829-120000-abcd"


class FakePytestConfig:
    """只实现收集函数需要的 getoption。"""

    def __init__(self, project: str = "dating") -> None:
        self.options = {
            "--project": project,
            "--task-id": TASK_ID,
            "--api": "Demo",
            "--case": "Demo::success",
            "--flow": "demo_flow",
        }

    def getoption(self, name: str):
        """返回测试构造的 pytest CLI 选项。"""
        return self.options.get(name)


class BatchFakePytestConfig(FakePytestConfig):
    """批次 pytest 命令不携带单条 API、Case 或 Flow 选择器。"""

    def __init__(self, project: str = "dating") -> None:
        super().__init__(project)
        self.options.update({"--api": None, "--case": None, "--flow": None})


def _resolved_asset(asset_type: str, locale: str = "zh-CN") -> tuple[str, dict]:
    """构造 Case 或 Flow 的最小最终执行对象。"""
    api_definitions = {
        "Demo": {
            "id": "Demo",
            "name": "Demo API",
            "credential_profile": "anonymous_session",
            "request": {
                "service_name": "example.DemoService",
                "method_name": "Demo",
            },
        }
    }
    if asset_type == "case":
        asset_id = "Demo::success"
        selected = {
            "id": asset_id,
            "api_id": "Demo",
            "case_id": "success",
            "name": "Demo success",
            "tags": ["smoke"],
            "runtime_inputs": {},
            "execution_case": {
                "request": {
                    "service_name": "example.DemoService",
                    "method_name": "Demo",
                    "params": {"locale": locale},
                },
                "assert": {"http_status": 200},
                "extract": {},
            },
        }
        resolved = {"single_case": selected, "api_definitions": api_definitions}
    else:
        asset_id = "demo_flow"
        selected = {
            "id": asset_id,
            "name": "Demo flow",
            "tags": ["regression"],
            "runtime_inputs": {},
            "flow": {
                "name": "Demo flow",
                "steps": [{"id": "create_demo", "api": "Demo"}],
            },
            "scenario": {
                "name": "Demo scenario",
                "step_data": {
                    "create_demo": {
                        "params": {"locale": locale},
                        "assert": {"http_status": 200},
                    }
                },
            },
            "api_definitions": api_definitions,
        }
        resolved = {"flow_case": selected, "api_definitions": api_definitions}
    return asset_id, resolved


def _write_execution_asset(
    root: Path,
    *,
    asset_type: str,
    locale: str = "zh-CN",
) -> Path:
    """按生产固定路径写入一份 0600 执行文件。"""
    asset_id, resolved = _resolved_asset(asset_type, locale)
    document = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "project_id": "dating",
        "asset_type": asset_type,
        "asset_id": asset_id,
        "asset_revision": f"sha256:{'1' * 64}",
        "resolved_asset_revision": canonical_sha256(resolved),
        "resolved_execution_asset": resolved,
    }
    path = root / "runtime" / "dating" / TASK_ID / "execution-asset.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def _write_batch_execution_asset(
    root: Path,
    *,
    batch_type: str,
) -> Path:
    """按 TaskManager 契约写入包含两个有序逻辑条目的批次快照。"""

    asset_type = "case" if batch_type == "cases" else "flow"
    items: list[dict] = []
    shared_definitions: dict = {}
    for index, locale in enumerate(("en-US", "zh-CN"), start=1):
        asset_id, resolved = _resolved_asset(asset_type, locale)
        if index == 2:
            asset_id = f"{asset_id}_secondary"
            identity_key = "single_case" if asset_type == "case" else "flow_case"
            resolved[identity_key]["id"] = asset_id
            if asset_type == "case":
                resolved[identity_key]["case_id"] = "secondary"
            resolved[identity_key]["tags"] = [
                "regression" if asset_type == "case" else "interactive"
            ]
        if asset_type == "flow":
            # 两条 Flow 共用同一任务级图片 manifest；pytest 不复制或改写图片。
            resolved["flow_case"]["flow"]["inputs"] = {
                "media_files": {
                    "type": "files",
                    "required": True,
                }
            }
        shared_definitions.update(deepcopy(resolved["api_definitions"]))
        items.append(
            {
                "asset_type": asset_type,
                "asset_id": asset_id,
                "asset_revision": f"sha256:{str(index) * 64}",
                "resolved_asset_revision": canonical_sha256(resolved),
                "resolved_execution_asset": resolved,
            }
        )
    batch_resolved = {
        "batch_type": batch_type,
        "items": items,
        "api_definitions": shared_definitions,
    }
    document = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "project_id": "dating",
        "asset_type": "batch",
        "asset_id": f"{batch_type}:2",
        "asset_revision": f"sha256:{'a' * 64}",
        "resolved_asset_revision": canonical_sha256(batch_resolved),
        "resolved_execution_asset": batch_resolved,
    }
    path = root / "runtime" / "dating" / TASK_ID / "execution-asset.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    return path


def test_single_collection_uses_snapshot_instead_of_current_yaml(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """设置执行文件后，即使项目 YAML 不存在也只能收集固化 Case。"""
    path = _write_execution_asset(tmp_path, asset_type="case", locale="zh-CN")
    monkeypatch.setenv("API_AUTOTEST_EXECUTION_ASSET_FILE", str(path))
    monkeypatch.setattr(single_module, "PROJECT_ROOT", tmp_path)

    collected = single_module._load_case_params(FakePytestConfig())

    single_case = collected[0].values[0]
    assert single_case["execution_case"]["request"]["params"]["locale"] == "zh-CN"


def test_flow_collection_uses_snapshot_instead_of_current_yaml(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Flow 收集使用固化 Scenario，同时保留图片 manifest 的独立入口。"""
    path = _write_execution_asset(tmp_path, asset_type="flow", locale="zh-CN")
    monkeypatch.setenv("API_AUTOTEST_EXECUTION_ASSET_FILE", str(path))
    monkeypatch.setattr(flow_module, "PROJECT_ROOT", tmp_path)

    selected = flow_module._load_selected_flow_cases(
        "demo_flow",
        "dating",
        FakePytestConfig(),
    )

    assert selected[0]["scenario"]["step_data"]["create_demo"]["params"][
        "locale"
    ] == "zh-CN"


def test_case_batch_collection_preserves_snapshot_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Case 批次必须按不可变清单顺序收集，且不读取当前 YAML。"""

    path = _write_batch_execution_asset(tmp_path, batch_type="cases")
    monkeypatch.setenv("API_AUTOTEST_EXECUTION_ASSET_FILE", str(path))
    monkeypatch.setattr(single_module, "PROJECT_ROOT", tmp_path)

    collected = single_module._load_case_params(BatchFakePytestConfig())

    assert [param.values[0]["id"] for param in collected] == [
        "Demo::success",
        "Demo::success_secondary",
    ]
    assert [
        param.values[0]["execution_case"]["request"]["params"]["locale"]
        for param in collected
    ] == ["en-US", "zh-CN"]


def test_flow_batch_collection_reuses_one_task_input_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Flow 批次按清单顺序收集，并让全部条目读取同一任务图片入口。"""

    path = _write_batch_execution_asset(tmp_path, batch_type="flows")
    monkeypatch.setenv("API_AUTOTEST_EXECUTION_ASSET_FILE", str(path))
    monkeypatch.setenv(
        "API_AUTOTEST_TASK_INPUT_MANIFEST_FILE",
        str(tmp_path / "task-inputs.json"),
    )
    monkeypatch.setattr(flow_module, "PROJECT_ROOT", tmp_path)

    selected = flow_module._load_selected_flow_cases(
        None,
        "dating",
        BatchFakePytestConfig(),
    )

    assert [flow_case["id"] for flow_case in selected] == [
        "demo_flow",
        "demo_flow_secondary",
    ]
    assert [
        flow_case["scenario"]["step_data"]["create_demo"]["params"]["locale"]
        for flow_case in selected
    ] == ["en-US", "zh-CN"]


@pytest.mark.parametrize(
    ("batch_type", "expected_markers"),
    [
        ("cases", {"smoke", "regression"}),
        ("flows", {"regression", "interactive"}),
    ],
)
def test_batch_snapshot_registers_only_frozen_item_markers(
    tmp_path: Path,
    monkeypatch,
    batch_type: str,
    expected_markers: set[str],
) -> None:
    """pytest marker 注册必须来自批次快照，而不是重新扫描项目 YAML。"""

    path = _write_batch_execution_asset(tmp_path, batch_type=batch_type)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text(
        "logging:\n  file: false\n  console: false\n",
        encoding="utf-8",
    )
    (tmp_path / "flows").mkdir()
    monkeypatch.setenv("API_AUTOTEST_EXECUTION_ASSET_FILE", str(path))
    monkeypatch.setattr(conftest_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conftest_module, "configure_logging", lambda **_kwargs: None)

    class Registry:
        """避免测试创建无关项目包，只提供配置阶段需要的路径。"""

        def __init__(self, _root: Path) -> None:
            pass

        def get(self, _project_id: str):
            return SimpleNamespace(root=tmp_path, flows_dir=tmp_path / "flows")

    monkeypatch.setattr(conftest_module, "ProjectRegistry", Registry)

    class Config(BatchFakePytestConfig):
        def __init__(self) -> None:
            super().__init__()
            self.options.update({"--target-env": "test", "--env": None})
            self.registered: set[str] = set()

        def addinivalue_line(self, _name: str, value: str) -> None:
            self.registered.add(value.split(":", 1)[0])

    config = Config()
    conftest_module.pytest_configure(config)  # type: ignore[arg-type]

    assert config.registered == expected_markers


def test_snapshot_type_mismatch_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """单接口入口收到 Flow 快照时不得回退当前 YAML。"""
    path = _write_execution_asset(tmp_path, asset_type="flow")
    monkeypatch.setenv("API_AUTOTEST_EXECUTION_ASSET_FILE", str(path))
    monkeypatch.setattr(single_module, "PROJECT_ROOT", tmp_path)

    with pytest.raises(Exception, match="类型"):
        single_module._load_case_params(FakePytestConfig())


def test_snapshot_tampering_fails_closed_in_collection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """摘要不一致时收集失败，不读取当前 YAML 兜底。"""
    path = _write_execution_asset(tmp_path, asset_type="case")
    document = json.loads(path.read_text(encoding="utf-8"))
    tampered = deepcopy(document)
    tampered["resolved_execution_asset"]["single_case"]["name"] = "tampered"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv("API_AUTOTEST_EXECUTION_ASSET_FILE", str(path))
    monkeypatch.setattr(single_module, "PROJECT_ROOT", tmp_path)

    with pytest.raises(Exception, match="完整性"):
        single_module._load_case_params(FakePytestConfig())
