"""同名资产的项目隔离与跨项目引用拒绝测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from utils.custom.api_loader import ApiConfigError, load_api_definitions
from utils.custom.case_loader import load_single_cases
from utils.custom.flow_loader import FlowConfigError, load_flow_cases


def _write_assets(root: Path, service_name: str) -> None:
    """为一个临时项目写入同名 API、Case、Flow 和 Scenario。"""
    for directory in ("apis", "cases", "flows", "scenarios"):
        (root / "data" / directory).mkdir(parents=True, exist_ok=True)
    (root / "data/apis/Same.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "Same",
                "name": "同名接口",
                "credential_profile": "public",
                "request": {"service_name": service_name, "method_name": "Same"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (root / "data/cases/Same.yaml").write_text(
        yaml.safe_dump(
            {
                "api": "Same",
                "cases": [
                    {
                        "id": "same-case",
                        "name": "同名 Case",
                        "request": {"params": {}},
                        "assert": {},
                    }
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (root / "data/flows/same-flow.yaml").write_text(
        "name: 同名 Flow\nsteps:\n  - id: call_same\n    api: Same\n",
        encoding="utf-8",
    )
    (root / "data/scenarios/same-flow.yaml").write_text(
        "name: 同名 Scenario\nstep_data:\n  call_same:\n    params: {}\n    assert: {}\n",
        encoding="utf-8",
    )


def test_same_ids_are_loaded_only_from_selected_project(tmp_path: Path) -> None:
    """两个项目可拥有同名 ID，路由和来源必须保持各自项目隔离。"""
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _write_assets(alpha, "alpha.Service")
    _write_assets(beta, "beta.Service")

    assert load_api_definitions(alpha)["Same"]["request"]["service_name"] == "alpha.Service"
    assert load_api_definitions(beta)["Same"]["request"]["service_name"] == "beta.Service"
    assert load_single_cases(alpha)[0]["id"] == "Same::same-case"
    assert load_single_cases(beta)[0]["id"] == "Same::same-case"
    assert load_flow_cases(alpha)[0]["id"] == "same-flow"
    assert load_flow_cases(beta)[0]["id"] == "same-flow"


def test_flow_cannot_resolve_api_that_exists_only_in_sibling_project(tmp_path: Path) -> None:
    """Flow 引用只查当前项目 API 注册表，兄弟项目同名定义不能补偿缺失。"""
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _write_assets(alpha, "alpha.Service")
    _write_assets(beta, "beta.Service")
    (alpha / "data/apis/Same.yaml").rename(alpha / "data/apis/Local.yaml")
    (alpha / "data/apis/Local.yaml").write_text(
        "id: Local\nname: 本地接口\ncredential_profile: public\nrequest:\n"
        "  service_name: alpha.Service\n  method_name: Local\n",
        encoding="utf-8",
    )

    with pytest.raises(FlowConfigError, match="引用的 API 不存在: Same"):
        load_flow_cases(alpha)


def test_api_symlink_cannot_import_definition_from_sibling_project(tmp_path: Path) -> None:
    """项目内同名 YAML 符号链接不得把兄弟项目 API 伪装成本项目资产。"""
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    _write_assets(alpha, "alpha.Service")
    _write_assets(beta, "beta.Service")
    (alpha / "data/apis/Same.yaml").unlink()
    (alpha / "data/apis/Same.yaml").symlink_to(beta / "data/apis/Same.yaml")

    with pytest.raises(ApiConfigError, match="符号链接|越界"):
        load_api_definitions(alpha)


@pytest.mark.parametrize("selected_flow", ("../same-flow", "same-flow.yaml", "/same-flow"))
def test_flow_selector_rejects_paths_and_filename_extensions(
    tmp_path: Path,
    selected_flow: str,
) -> None:
    """CLI Flow 选择器只接受逻辑 ID，不把路径、扩展名静默归一为其他资产。"""

    project = tmp_path / "alpha"
    _write_assets(project, "alpha.Service")

    with pytest.raises(FlowConfigError, match="Flow ID 不合法"):
        load_flow_cases(project, selected_flow=selected_flow)
