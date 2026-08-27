"""标准项目包发现、Manifest 校验与项目内安全路径解析。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils.custom.api_loader import ApiConfigError, load_api_definitions
from utils.custom.case_loader import CaseConfigError, load_single_cases
from utils.custom.config_loader import ConfigError, load_yaml
from utils.custom.flow_loader import FlowConfigError, load_flow_cases


class ProjectRegistryError(ValueError):
    """表示项目选择、发现或解析无法安全完成。"""


class ProjectNotFoundError(ProjectRegistryError):
    """表示调用方选择了不存在的标准项目包。"""


class ProjectValidationError(ProjectRegistryError):
    """表示项目 Manifest、目录或资产不符合标准项目包契约。"""


_PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_SUPPORTED_CAPABILITIES = frozenset({"gateway", "signed_binary_upload"})
_CREDENTIAL_PROFILE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_REQUIRED_DIRECTORIES = (
    "data/api",
    "data/apis",
    "data/cases",
    "data/flows",
    "data/scenarios",
    "fixtures",
)
_MANIFEST_FIELDS = {
    "schema_version",
    "project_id",
    "display_name",
    "capabilities",
    "config_contract",
    "redaction",
}
_FULL_VARIABLE_PATTERN = re.compile(r"^{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}$")


@dataclass(frozen=True)
class ConfigContract:
    """项目对平台 Release 与 Credential Profile 的逻辑契约。"""

    required_keys: tuple[str, ...]
    credential_profiles: tuple[str, ...]


@dataclass(frozen=True)
class ProjectManifest:
    """经过 Schema V1 校验的不可变 Project Manifest。"""

    schema_version: int
    project_id: str
    display_name: str
    capabilities: tuple[str, ...]
    config_contract: ConfigContract
    redaction_extra_keys: tuple[str, ...]


@dataclass(frozen=True)
class ProjectPackage:
    """Manifest 与已确认未越界的项目根目录及标准资产路径。"""

    manifest: ProjectManifest
    root: Path

    @property
    def project_id(self) -> str:
        """返回稳定项目键。"""
        return self.manifest.project_id

    @property
    def display_name(self) -> str:
        """返回项目展示名称。"""
        return self.manifest.display_name

    @property
    def data_root(self) -> Path:
        return self.root / "data"

    @property
    def api_dir(self) -> Path:
        return self.data_root / "api"

    @property
    def apis_dir(self) -> Path:
        return self.data_root / "apis"

    @property
    def cases_dir(self) -> Path:
        return self.data_root / "cases"

    @property
    def flows_dir(self) -> Path:
        return self.data_root / "flows"

    @property
    def scenarios_dir(self) -> Path:
        return self.data_root / "scenarios"

    @property
    def fixtures_dir(self) -> Path:
        return self.root / "fixtures"

    def resolve_path(
        self,
        relative_path: str | Path,
        *,
        base: Path | None = None,
        require_exists: bool = True,
    ) -> Path:
        """安全解析项目内相对路径，拒绝绝对路径、穿越和越界符号链接。

        ``resolve`` 后再做 ``relative_to`` 检查，既阻止 ``..``，也阻止项目内
        符号链接把读取目标引到兄弟项目或仓库外。错误只暴露项目相对输入，避免
        在 Web/日志中泄漏服务器绝对目录。
        """
        requested = Path(relative_path)
        if requested.is_absolute() or not str(relative_path).strip():
            raise ProjectValidationError(
                f"项目 {self.project_id} 路径必须为非空相对路径: {relative_path!s}"
            )
        boundary = self.root.resolve()
        anchor = (base or self.root).resolve()
        try:
            anchor.relative_to(boundary)
        except ValueError as exc:
            raise ProjectValidationError(f"项目 {self.project_id} 路径基准越界") from exc
        resolved = (anchor / requested).resolve(strict=False)
        try:
            resolved.relative_to(boundary)
        except ValueError as exc:
            raise ProjectValidationError(
                f"项目 {self.project_id} 路径越界: {relative_path!s}"
            ) from exc
        if require_exists and not resolved.exists():
            raise ProjectValidationError(
                f"项目 {self.project_id} 路径不存在: {relative_path!s}"
            )
        return resolved

    def resolve_fixture(self, relative_path: str | Path) -> Path:
        """只在当前项目 ``fixtures`` 中解析测试素材。"""
        try:
            resolved = self.resolve_path(relative_path, base=self.fixtures_dir)
        except ProjectValidationError as exc:
            raise ProjectValidationError(
                f"项目 {self.project_id} fixture 路径越界或不存在: {relative_path!s}"
            ) from exc
        try:
            resolved.relative_to(self.fixtures_dir.resolve())
        except ValueError as exc:
            raise ProjectValidationError(
                f"项目 {self.project_id} fixture 路径越界: {relative_path!s}"
            ) from exc
        if not resolved.is_file():
            raise ProjectValidationError(
                f"项目 {self.project_id} fixture 不是文件: {relative_path!s}"
            )
        return resolved


def _string_list(value: Any, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    """校验 Manifest 字符串数组并保持声明顺序。"""
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ProjectValidationError(f"project.yaml.{field} 必须是非空字符串数组")
    normalized = tuple(item.strip() for item in value)
    if not allow_empty and not normalized:
        raise ProjectValidationError(f"project.yaml.{field} 不能为空")
    if len(set(normalized)) != len(normalized):
        raise ProjectValidationError(f"project.yaml.{field} 包含重复值")
    return normalized


def _parse_manifest(content: dict[str, Any], directory_name: str) -> ProjectManifest:
    """按 schema_version=1 严格解析 Manifest，未知字段与能力均失败。"""
    unexpected = sorted(set(content) - _MANIFEST_FIELDS)
    if unexpected:
        raise ProjectValidationError(
            f"项目 {directory_name} project.yaml 包含未知字段: {', '.join(unexpected)}"
        )
    if content.get("schema_version") != 1:
        raise ProjectValidationError(
            f"项目 {directory_name} project.yaml.schema_version 仅支持 1"
        )
    project_id = content.get("project_id")
    if not isinstance(project_id, str) or not _PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ProjectValidationError(
            f"项目目录 {directory_name} 的 project_id 不符合 ^[a-z][a-z0-9-]{{1,31}}$"
        )
    if project_id != directory_name:
        raise ProjectValidationError(
            f"项目目录 {directory_name} 与 project.yaml.project_id={project_id} 不一致"
        )
    display_name = content.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ProjectValidationError(f"项目 {project_id} display_name 必须为非空字符串")
    capabilities = _string_list(
        content.get("capabilities"), "capabilities", allow_empty=False
    )
    unknown_capabilities = sorted(set(capabilities) - _SUPPORTED_CAPABILITIES)
    if unknown_capabilities:
        raise ProjectValidationError(
            f"项目 {project_id} 声明未知 capability: {', '.join(unknown_capabilities)}"
        )
    contract = content.get("config_contract")
    if not isinstance(contract, dict) or set(contract) != {
        "required_keys",
        "credential_profiles",
    }:
        raise ProjectValidationError(
            f"项目 {project_id} config_contract 必须只含 required_keys、credential_profiles"
        )
    required_keys = _string_list(
        contract.get("required_keys"), "config_contract.required_keys"
    )
    profiles = _string_list(
        contract.get("credential_profiles"),
        "config_contract.credential_profiles",
    )
    unsafe_profiles = sorted(
        profile for profile in profiles if not _CREDENTIAL_PROFILE_PATTERN.fullmatch(profile)
    )
    if unsafe_profiles:
        raise ProjectValidationError(
            f"项目 {project_id} credential profile ID 不合法: {', '.join(unsafe_profiles)}"
        )
    redaction = content.get("redaction")
    if not isinstance(redaction, dict) or set(redaction) != {"extra_keys"}:
        raise ProjectValidationError(
            f"项目 {project_id} redaction 必须只含 extra_keys"
        )
    extra_keys = _string_list(redaction.get("extra_keys"), "redaction.extra_keys")
    return ProjectManifest(
        schema_version=1,
        project_id=project_id,
        display_name=display_name.strip(),
        capabilities=capabilities,
        config_contract=ConfigContract(required_keys, profiles),
        redaction_extra_keys=extra_keys,
    )


class ProjectRegistry:
    """从受控 ``projects`` 根目录发现并静态校验标准项目包。"""

    def __init__(self, projects_root: Path | None = None) -> None:
        default_root = Path(__file__).resolve().parents[2] / "projects"
        self.projects_root = (projects_root or default_root).resolve(strict=False)

    @staticmethod
    def _validate_project_id(project_id: str) -> None:
        if not isinstance(project_id, str) or not _PROJECT_ID_PATTERN.fullmatch(project_id):
            raise ProjectRegistryError(f"project_id 不合法: {project_id!r}")

    def _load_package(self, directory: Path) -> ProjectPackage:
        directory_name = directory.name
        if not _PROJECT_ID_PATTERN.fullmatch(directory_name):
            raise ProjectValidationError(
                f"项目目录的 project_id 不合法: {directory_name!r}"
            )
        if directory.is_symlink():
            raise ProjectValidationError(f"项目 {directory_name} 目录禁止使用符号链接越界")
        resolved = directory.resolve(strict=False)
        try:
            resolved.relative_to(self.projects_root)
        except ValueError as exc:
            raise ProjectValidationError(f"项目 {directory_name} 目录越界") from exc
        manifest_path = resolved / "project.yaml"
        try:
            content = load_yaml(manifest_path)
        except ConfigError as exc:
            raise ProjectValidationError(
                f"项目 {directory_name} project.yaml 无法加载: {exc}"
            ) from exc
        manifest = _parse_manifest(content, directory_name)
        package = ProjectPackage(manifest=manifest, root=resolved)
        missing = [relative for relative in _REQUIRED_DIRECTORIES if not (resolved / relative).is_dir()]
        if missing:
            raise ProjectValidationError(
                f"项目 {directory_name} 缺少目录: {', '.join(missing)}"
            )
        return package

    def discover(self) -> list[ProjectPackage]:
        """只扫描一级目录，并按 project_id 排序返回全部有效项目包。"""
        if not self.projects_root.is_dir():
            raise ProjectRegistryError(f"projects 根目录不存在: {self.projects_root}")
        packages: list[ProjectPackage] = []
        seen_ids: set[str] = set()
        for directory in sorted(self.projects_root.iterdir(), key=lambda item: item.name):
            if not directory.is_dir():
                continue
            package = self._load_package(directory)
            if package.project_id in seen_ids:
                raise ProjectValidationError(f"存在重复 project_id: {package.project_id}")
            seen_ids.add(package.project_id)
            packages.append(package)
        return packages

    def list_projects(self) -> list[ProjectPackage]:
        """Web/CLI 使用的项目列表接口。"""
        return self.discover()

    def get(self, project_id: str) -> ProjectPackage:
        """安全解析一个项目，未知或非法 ID 不尝试文件系统路径拼接。"""
        self._validate_project_id(project_id)
        directory = self.projects_root / project_id
        if not directory.is_dir():
            raise ProjectNotFoundError(f"项目不存在: {project_id}")
        return self._load_package(directory)

    def validate(self, project_id: str) -> list[str]:
        """静态校验单项目全部 API/Case/Flow/Scenario，成功返回空错误列表。"""
        package = self.get(project_id)
        try:
            definitions = load_api_definitions(package.root)
            allowed_profiles = {
                "public", *package.manifest.config_contract.credential_profiles
            }
            undeclared_profiles = sorted({
                str(definition.get("credential_profile"))
                for definition in definitions.values()
                if definition.get("credential_profile") not in allowed_profiles
            })
            if undeclared_profiles:
                raise ProjectValidationError(
                    "credential profile 未在 Manifest 声明: "
                    + ", ".join(undeclared_profiles)
                )
            if any(package.cases_dir.glob("*.yaml")):
                load_single_cases(package.root)
            if any(package.flows_dir.glob("*.yaml")) or any(
                package.scenarios_dir.glob("*.yaml")
            ):
                flow_cases = load_flow_cases(package.root)
                self._validate_flow_fixtures(package, flow_cases)
        except (ApiConfigError, CaseConfigError, FlowConfigError, ConfigError) as exc:
            raise ProjectValidationError(f"项目 {project_id} 资产校验失败: {exc}") from exc
        return []

    @staticmethod
    def _validate_flow_fixtures(
        package: ProjectPackage,
        flow_cases: list[dict[str, Any]],
    ) -> None:
        """验证上传动作声明的 fixture 均落在当前项目且真实存在。"""
        for flow_case in flow_cases:
            scenario = flow_case.get("scenario") or {}
            variables = scenario.get("variables") or {}
            for step in (flow_case.get("flow") or {}).get("steps") or []:
                action = step.get("action")
                if action == "prepared_media_upload":
                    fixture = variables.get("media_file")
                    if isinstance(fixture, str) and fixture.startswith("fixtures/"):
                        fixture = fixture.removeprefix("fixtures/")
                elif isinstance(action, dict) and action.get("type") == "signed_binary_upload":
                    fixture = action.get("fixture")
                    if isinstance(fixture, str) and (
                        match := _FULL_VARIABLE_PATTERN.fullmatch(fixture)
                    ):
                        fixture = variables.get(match.group(1))
                else:
                    continue
                if not isinstance(fixture, str) or not fixture:
                    raise ProjectValidationError(
                        f"项目 {package.project_id} Flow {flow_case['id']} fixture 无法静态解析"
                    )
                package.resolve_fixture(fixture)

    def validate_all(self) -> dict[str, list[str]]:
        """校验全部项目；任何项目失败都立即抛错，禁止静默跳过坏包。"""
        result: dict[str, list[str]] = {}
        for package in self.list_projects():
            result[package.project_id] = self.validate(package.project_id)
        return result


def validate_project_package(package: ProjectPackage) -> list[str]:
    """为已有 ProjectPackage 提供设计文档约定的公共校验函数。"""
    return ProjectRegistry(package.root.parent).validate(package.project_id)
