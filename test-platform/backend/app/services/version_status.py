from __future__ import annotations

import hmac
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.configuration import (
    ConfigActivation, ConfigDefinition, ConfigRelease, ConfigReleaseItem, Secret,
)
from app.models.tool import Tool
from app.services.tool_health import probe_tool_health


TOOL_COMPONENTS = {
    "trackevents": "trackevents-web",
    "log-filter": "log-filter-tool",
    "truthy-search": "truthy-search",
    "api-autotest": "api-autotest",
    "functional-test-agent": "functional-test-agent",
    "api-test-agent": "api-test-agent",
}
STATUS_PRIORITY = [
    "不可用", "不兼容", "环境漂移", "配置不一致", "内容不一致",
    "结构不一致", "迁移不一致", "未验证构建", "配置未验证", "待重建",
    "Dirty 构建", "待发布", "Prod 领先", "一致",
]


def _sha256(payload: Any) -> str:
    """Hash a canonical JSON value so environments can compare without sharing IDs."""

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _database_structure(database: Session) -> dict[str, Any]:
    """Fingerprint table, column, constraint and index metadata; never read business rows."""

    try:
        inspector = inspect(database.get_bind())
        schema = "public" if database.get_bind().dialect.name == "postgresql" else None
        tables = sorted(inspector.get_table_names(schema=schema))
        structure: list[dict[str, Any]] = []
        column_count = constraint_count = index_count = 0
        for table_name in tables:
            columns = inspector.get_columns(table_name, schema=schema)
            primary_key = inspector.get_pk_constraint(table_name, schema=schema)
            foreign_keys = inspector.get_foreign_keys(table_name, schema=schema)
            unique_constraints = inspector.get_unique_constraints(table_name, schema=schema)
            indexes = inspector.get_indexes(table_name, schema=schema)
            normalized_columns = [{
                "name": column["name"], "type": str(column["type"]),
                "nullable": bool(column.get("nullable", True)),
                "default": str(column.get("default") or ""),
            } for column in columns]
            normalized_constraints = {
                "primary_key": primary_key,
                "foreign_keys": foreign_keys,
                "unique": unique_constraints,
            }
            structure.append({
                "table": table_name, "columns": normalized_columns,
                "constraints": normalized_constraints, "indexes": indexes,
            })
            column_count += len(columns)
            constraint_count += bool(primary_key.get("constrained_columns")) + len(foreign_keys) + len(unique_constraints)
            index_count += len(indexes)
        return {
            "schema_sha256": _sha256(structure), "tables": len(tables),
            "columns": column_count, "constraints": constraint_count, "indexes": index_count,
            "data_compared": False,
        }
    except SQLAlchemyError:
        return {"schema_sha256": None, "data_compared": False}


def _configuration_fingerprints(
    database: Session, environment_id: str, activations: list[ConfigActivation]
) -> dict[str, Any]:
    """Hash resolved normal values and Secret state without reading Secret plaintext."""

    result: dict[str, Any] = {}
    for activation in activations:
        scope = f"{activation.owner_type}:{activation.owner_id}"
        release = database.get(ConfigRelease, activation.active_release_id)
        if release is None:
            continue
        definitions = database.scalars(select(ConfigDefinition).where(
            ConfigDefinition.owner_type == activation.owner_type,
            ConfigDefinition.owner_id == activation.owner_id,
        ).order_by(ConfigDefinition.key)).all()
        items = {item.definition_id: item for item in database.scalars(select(ConfigReleaseItem).where(
            ConfigReleaseItem.release_id == release.id
        )).all()}
        normal: dict[str, Any] = {}
        secret_state: dict[str, Any] = {}
        for definition in definitions:
            item = items.get(definition.id)
            if definition.sensitivity == "secret":
                secret = database.scalar(select(Secret).where(
                    Secret.environment_id == environment_id,
                    Secret.owner_type == activation.owner_type,
                    Secret.owner_id == activation.owner_id,
                    Secret.definition_id == definition.id,
                ))
                secret_state[definition.key] = {
                    "configured": bool(secret and secret.current_version_id),
                    "status": secret.status if secret else "missing",
                }
            else:
                normal[definition.key] = item.value_json if item is not None else definition.default_value
        result[scope] = {
            "release_id": release.id, "release_version": release.version,
            "effective_sha256": _sha256(normal),
            "secret_state_sha256": _sha256(secret_state),
            "normal_count": len(normal), "secret_count": len(secret_state),
        }
    return result


def _component_config_sha(scopes: list[str], fingerprints: dict[str, Any]) -> str | None:
    """Combine only effective values and Secret state; environment-specific release IDs are excluded."""

    if not scopes or any(scope not in fingerprints for scope in scopes):
        return None
    return _sha256({scope: {
        "effective_sha256": fingerprints[scope]["effective_sha256"],
        "secret_state_sha256": fingerprints[scope]["secret_state_sha256"],
    } for scope in scopes})


def _deployment_state(settings: Settings) -> dict[str, Any]:
    """读取部署验证产生的非敏感运行清单；文件缺失时返回空状态。"""

    if not settings.prod_release_bom_file:
        return {}
    path = Path(settings.prod_release_bom_file)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _component_record(payload: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """将上游健康响应收敛为不泄露内部地址的组件身份。"""

    return {
        "version": payload.get("version", "unknown"),
        "revision": payload.get("revision", "unknown"),
        "dirty": payload.get("dirty"),
        "content_sha256": payload.get("content_sha256", "unknown"),
        "runtime_environment": payload.get("runtime_environment", "unknown"),
        "health": "healthy" if payload.get("healthy") else "unavailable",
        "digest": expected.get("digest"),
        "image": expected.get("image"),
    }


def collect_snapshot(database: Session, settings: Settings) -> dict[str, Any]:
    """聚合当前环境的组件、数据库和配置 Release 只读快照。"""

    manifest = settings.read_versions_manifest()
    deployment = _deployment_state(settings)
    expected_images = deployment.get("images", {})
    expected_components: dict[str, Any] = {}
    for component_id, component in deployment.get("components", {}).items():
        images = component.get("images", {}) if isinstance(component, dict) else {}
        image = next(iter(images.values()), None)
        expected_components[component_id] = {
            "version": component.get("version", "unknown"),
            "revision": component.get("revision", deployment.get("commit")),
            "content_sha256": component.get("content_sha256", "unknown"),
            "digest": image,
            "image": image,
            "health": "expected",
            "dirty": False,
            "runtime_environment": settings.platform_runtime_env,
        }
    components: dict[str, Any] = {
        "platform-backend": {
            "version": settings.app_version,
            "revision": settings.app_revision,
            "dirty": settings.app_build_dirty,
            "content_sha256": settings.app_content_sha256,
            "runtime_environment": settings.platform_runtime_env,
            "health": "healthy",
            "digest": expected_images.get("PLATFORM_BACKEND_IMAGE"),
        }
    }
    gateway = probe_tool_health(
        "http://platform-gateway/version.json", settings.tool_health_timeout_seconds
    )
    components["platform-gateway"] = _component_record(
        gateway, {"digest": expected_images.get("PLATFORM_GATEWAY_IMAGE")}
    )
    tools = database.scalars(select(Tool).where(Tool.is_enabled.is_(True))).all()
    for tool in tools:
        component_id = TOOL_COMPONENTS.get(tool.id)
        if component_id is None:
            continue
        components[component_id] = _component_record(
            probe_tool_health(tool.health_url, settings.tool_health_timeout_seconds),
            {"digest": expected_images.get(manifest["components"][component_id]["image_envs"][0])},
        )
    for component_id in manifest["components"]:
        components.setdefault(component_id, {
            "version": "unknown", "revision": "unknown", "dirty": None,
            "runtime_environment": settings.platform_runtime_env, "health": "unavailable",
            "digest": None,
            "content_sha256": "unknown",
        })
    try:
        revision = database.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except SQLAlchemyError:
        revision = None
    activations = list(database.scalars(select(ConfigActivation).where(
        ConfigActivation.environment_id == settings.platform_runtime_env
    )).all())
    config_fingerprints = _configuration_fingerprints(
        database, settings.platform_runtime_env, activations
    )
    for component_id, component in manifest["components"].items():
        scopes = component.get("config_scopes", [])
        components[component_id]["config_sha256"] = _component_config_sha(scopes, config_fingerprints)
        components[component_id]["config_scopes"] = scopes
    database_structure = _database_structure(database)
    database_structure["alembic_revision"] = revision
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "product_version": manifest["product"]["version"],
        "runtime_environment": settings.platform_runtime_env,
        "release": deployment.get("release"),
        "commit": deployment.get("commit"),
        "components": components,
        "expected_components": expected_components,
        "database": database_structure,
        "config_releases": {
            f"{row.owner_type}:{row.owner_id}": row.active_release_id for row in activations
        },
        "config_fingerprints": config_fingerprints,
    }


def fetch_prod_snapshot(settings: Settings) -> tuple[dict[str, Any] | None, str | None]:
    """在固定三秒内读取生产只读快照；任何失败均关闭为不可达。"""

    if not settings.prod_version_snapshot_url:
        return None, "未配置 Prod 版本互查地址"
    token = settings.read_version_peer_token()
    if not token:
        return None, "未配置 Prod 版本互查 Token"
    try:
        response = httpx.get(
            settings.prod_version_snapshot_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=3.0,
        )
        response.raise_for_status()
        return response.json(), None
    except (httpx.HTTPError, ValueError):
        return None, "Prod 无法获取"


def _semver(value: str) -> tuple[int, int, int] | None:
    try:
        parts = tuple(int(part) for part in value.split("."))
        return parts if len(parts) == 3 else None
    except (AttributeError, ValueError):
        return None


def compare_component(
    component_id: str,
    manifest_component: dict[str, Any],
    dev: dict[str, Any] | None,
    prod: dict[str, Any] | None,
    prod_expected: dict[str, Any] | None,
    product_major: int,
) -> dict[str, Any]:
    """按固定优先级计算一个组件的全部问题和主状态。"""

    issues: list[str] = []
    if any(item is not None and item.get("health") == "unavailable" for item in (dev, prod)):
        issues.append("不可用")
    if manifest_component["compatible_product_major"] != product_major:
        issues.append("不兼容")
    if prod and prod_expected:
        for field in ("version", "digest", "content_sha256"):
            expected = prod_expected.get(field)
            if expected and prod.get(field) != expected:
                issues.append("环境漂移")
                break
    if dev and prod:
        dev_content = dev.get("content_sha256")
        prod_content = prod.get("content_sha256")
        if dev_content in {None, "unknown"} or prod_content in {None, "unknown"}:
            issues.append("未验证构建")
        elif dev.get("version") == prod.get("version") and dev_content != prod_content:
            issues.append("内容不一致")
        if manifest_component.get("config_scopes"):
            if not dev.get("config_sha256") or not prod.get("config_sha256"):
                issues.append("配置未验证")
            elif dev["config_sha256"] != prod["config_sha256"]:
                issues.append("配置不一致")
    if dev and dev.get("version") != manifest_component["version"]:
        issues.append("待重建")
    if any(item and item.get("dirty") for item in (dev, prod)):
        issues.append("Dirty 构建")
    dev_version = _semver((dev or {}).get("version", ""))
    prod_version = _semver((prod or {}).get("version", ""))
    if dev_version and prod_version:
        if dev_version > prod_version:
            issues.append("待发布")
        elif prod_version > dev_version:
            issues.append("Prod 领先")
    issues = list(dict.fromkeys(issues)) or ["一致"]
    primary = min(issues, key=STATUS_PRIORITY.index)
    return {
        "component_id": component_id,
        "manifest_version": manifest_component["version"],
        "dev": dev,
        "prod": prod,
        "prod_expected": prod_expected,
        "issues": issues,
        "primary_status": primary,
    }


def build_matrix(
    current: dict[str, Any],
    prod: dict[str, Any] | None,
    settings: Settings,
    prod_error: str | None = None,
) -> dict[str, Any]:
    """组合 Dev 实际、Prod 实际与 Prod BOM 期望状态。"""

    manifest = settings.read_versions_manifest()
    dev = current if current["runtime_environment"] == "dev" else None
    actual_prod = current if current["runtime_environment"] == "prod" else prod
    expected_payload = _deployment_state(settings)
    expected_components: dict[str, Any] = {}
    for component_id, component in expected_payload.get("components", {}).items():
        images = component.get("images", {}) if isinstance(component, dict) else {}
        image = next(iter(images.values()), None)
        expected_components[component_id] = {
            "version": component.get("version", "unknown"),
            "revision": component.get("revision", expected_payload.get("commit")),
            "content_sha256": component.get("content_sha256", "unknown"),
            "digest": image,
            "image": image,
            "health": "expected",
            "dirty": False,
            "runtime_environment": "prod",
        }
    if actual_prod and actual_prod.get("expected_components"):
        expected_components = actual_prod["expected_components"]
    product_major = int(manifest["product"]["version"].split(".")[0])
    rows = []
    for component_id, component in manifest["components"].items():
        expected = expected_components.get(component_id)
        rows.append(compare_component(
            component_id, component,
            (dev or {}).get("components", {}).get(component_id),
            (actual_prod or {}).get("components", {}).get(component_id),
            expected,
            product_major,
        ))
    dev_database = (dev or {}).get("database", {})
    prod_database = (actual_prod or {}).get("database", {})
    database_issues: list[str] = []
    if not dev_database or not prod_database:
        database_issues.append("不可用")
    else:
        if dev_database.get("alembic_revision") != prod_database.get("alembic_revision"):
            database_issues.append("迁移不一致")
        if not dev_database.get("schema_sha256") or not prod_database.get("schema_sha256"):
            database_issues.append("未验证构建")
        elif dev_database["schema_sha256"] != prod_database["schema_sha256"]:
            database_issues.append("结构不一致")
    database_issues = list(dict.fromkeys(database_issues)) or ["一致"]
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "product_version": manifest["product"]["version"],
        "runtime_environment": settings.platform_runtime_env,
        "prod_error": prod_error,
        "dev": dev,
        "prod": actual_prod,
        "rows": rows,
        "database_comparison": {
            "dev": dev_database, "prod": prod_database,
            "issues": database_issues,
            "primary_status": min(database_issues, key=STATUS_PRIORITY.index),
            "data_compared": False,
        },
    }


def peer_token_matches(settings: Settings, presented: str) -> bool:
    """使用恒定时间比较只读环境互查 Token。"""

    expected = settings.read_version_peer_token()
    return bool(expected) and hmac.compare_digest(expected, presented)
