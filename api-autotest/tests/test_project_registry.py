"""项目包注册、Manifest 校验与路径边界的行为测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from utils.custom.project_registry import (
    ProjectRegistry,
    ProjectRegistryError,
    ProjectValidationError,
)


def _write_project(
    projects_root: Path,
    project_id: str,
    *,
    schema_version: int = 1,
    capabilities: list[str] | None = None,
) -> Path:
    """创建只含最小合法资产的临时项目包，测试不依赖仓库真实项目。"""
    root = projects_root / project_id
    for relative in (
        "data/api",
        "data/apis",
        "data/cases",
        "data/flows",
        "data/scenarios",
        "fixtures",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "data/api/gateway_invoke.yaml").write_text(
        "method: POST\npath: /gateway/invoke\n",
        encoding="utf-8",
    )
    (root / "data/apis/Ping.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "Ping",
                "name": "Ping",
                "credential_profile": "public",
                "request": {"service_name": "demo.Service", "method_name": "Ping"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (root / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": schema_version,
                "project_id": project_id,
                "display_name": project_id.title(),
                "capabilities": capabilities or ["gateway"],
                "config_contract": {
                    "required_keys": ["gateway.base_url", "gateway.path"],
                    "credential_profiles": ["anonymous_session"],
                },
                "redaction": {"extra_keys": []},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return root


def test_registry_discovers_sorted_project_packages_with_stable_paths(tmp_path: Path) -> None:
    """新增项目包后，公共代码应按 ID 排序发现并暴露标准资产目录。"""
    projects_root = tmp_path / "projects"
    _write_project(projects_root, "zeta")
    _write_project(projects_root, "alpha")

    packages = ProjectRegistry(projects_root).list_projects()

    assert [package.project_id for package in packages] == ["alpha", "zeta"]
    assert packages[0].display_name == "Alpha"
    assert packages[0].apis_dir == projects_root / "alpha/data/apis"
    assert packages[0].fixtures_dir == projects_root / "alpha/fixtures"
    assert packages[0].manifest.schema_version == 1


@pytest.mark.parametrize(
    ("project_id", "schema_version", "capabilities", "message"),
    [
        ("demo", 2, ["gateway"], "schema_version"),
        ("demo", 1, ["gateway", "dating-special"], "未知 capability"),
        ("Demo", 1, ["gateway"], "project_id"),
    ],
)
def test_registry_rejects_invalid_manifest_contracts(
    tmp_path: Path,
    project_id: str,
    schema_version: int,
    capabilities: list[str],
    message: str,
) -> None:
    """未知 Schema、业务专属能力和非法项目 ID 都必须在收集阶段失败。"""
    projects_root = tmp_path / "projects"
    _write_project(
        projects_root,
        project_id,
        schema_version=schema_version,
        capabilities=capabilities,
    )

    with pytest.raises(ProjectValidationError, match=message):
        ProjectRegistry(projects_root).list_projects()


def test_registry_rejects_api_profile_not_declared_by_manifest(tmp_path: Path) -> None:
    """API 只能引用 public 或当前 Manifest 声明的逻辑 Profile。"""

    projects_root = tmp_path / "projects"
    root = _write_project(projects_root, "alpha")
    api_path = root / "data/apis/Ping.yaml"
    content = yaml.safe_load(api_path.read_text(encoding="utf-8"))
    content["credential_profile"] = "admin_session"
    api_path.write_text(yaml.safe_dump(content, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ProjectValidationError, match="credential profile.*未在 Manifest"):
        ProjectRegistry(projects_root).validate("alpha")


@pytest.mark.parametrize("unsafe_id", ["../dating", "truthy/../dating", "/tmp/demo", ".."])
def test_registry_rejects_project_path_traversal(tmp_path: Path, unsafe_id: str) -> None:
    """用户输入不得通过相对、绝对或复合路径逃离 projects 根目录。"""
    projects_root = tmp_path / "projects"
    _write_project(projects_root, "truthy")

    with pytest.raises(ProjectRegistryError, match="project_id"):
        ProjectRegistry(projects_root).get(unsafe_id)


def test_registry_rejects_project_symlink_that_escapes_projects_root(tmp_path: Path) -> None:
    """一级项目目录即使名称合法，符号链接指向根外也必须拒绝。"""
    projects_root = tmp_path / "projects"
    outside = _write_project(tmp_path / "outside", "escaped")
    projects_root.mkdir()
    (projects_root / "escaped").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ProjectValidationError, match="符号链接|越界"):
        ProjectRegistry(projects_root).list_projects()


def test_project_resolve_rejects_fixture_crossing_package_boundary(tmp_path: Path) -> None:
    """fixture 解析只允许当前项目目录，不能借助 .. 或符号链接读取兄弟项目。"""
    projects_root = tmp_path / "projects"
    alpha = _write_project(projects_root, "alpha")
    beta = _write_project(projects_root, "beta")
    (beta / "fixtures/secret.jpg").write_bytes(b"secret")
    (alpha / "fixtures/escape.jpg").symlink_to(beta / "fixtures/secret.jpg")
    package = ProjectRegistry(projects_root).get("alpha")

    with pytest.raises(ProjectValidationError, match="越界"):
        package.resolve_fixture("../../beta/fixtures/secret.jpg")
    with pytest.raises(ProjectValidationError, match="越界"):
        package.resolve_fixture("escape.jpg")


def test_static_validation_rejects_flow_fixture_path_traversal(tmp_path: Path) -> None:
    """--validate-projects 必须在无网络阶段发现通用上传动作的 fixture 越界。"""
    projects_root = tmp_path / "projects"
    root = _write_project(projects_root, "alpha")
    (root / "data/flows/upload.yaml").write_text(
        """name: upload
steps:
  - id: upload
    action:
      type: signed_binary_upload
      url: '{{signed_url}}'
      headers: '{{signed_headers}}'
      fixture: ../../beta/fixtures/secret.jpg
      method: PUT
      success_statuses: [200]
""",
        encoding="utf-8",
    )
    (root / "data/scenarios/upload.yaml").write_text(
        "name: upload\nvariables: {}\nstep_data: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectValidationError, match="fixture.*越界"):
        ProjectRegistry(projects_root).validate("alpha")
