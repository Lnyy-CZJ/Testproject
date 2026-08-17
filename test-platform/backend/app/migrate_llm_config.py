"""把现有工具 LLM 配置导入平台草稿；命令永不输出配置值或指纹。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func, select

from app.api.llm import _profile_definitions
from app.core.config import get_settings
from app.core.security import new_id
from app.db.session import SessionLocal
from app.models.configuration import ConfigDefinition, ConfigRelease, ConfigReleaseItem, Secret
from app.models.llm import LlmProfile
from app.services.llm import active_release, release_values
from app.services.secret_store import decrypt_secret, decrypt_secret_version, load_secret_cipher, replace_secret


@dataclass(frozen=True)
class SourceConfig:
    tool_id: str
    binding_id: str
    base_url: str
    model: str
    api_key: str
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None


def _legacy_source(database, cipher, environment: str, tool_id: str, binding_id: str) -> SourceConfig | None:
    release = active_release(database, environment, "tool", tool_id)
    normal, secrets = release_values(database, release)
    key = secrets.get("LLM_API_KEY")
    if not release or not normal.get("LLM_BASE_URL") or not normal.get("LLM_MODEL") or key is None:
        return None
    secret, version = key
    return SourceConfig(
        tool_id, binding_id, str(normal["LLM_BASE_URL"]), str(normal["LLM_MODEL"]),
        decrypt_secret_version(database, cipher, secret, version.id),
    )


def _ensure_profile(database, profile_id: str, name: str) -> None:
    if database.get(LlmProfile, profile_id) is None:
        database.add(LlmProfile(
            id=profile_id, name=name, name_normalized=name.casefold(),
            description="由一次性导入命令创建的兼容配置", protocol="openai_compatible",
            created_by="system/llm-import",
        ))
        database.flush()
    existing = set(database.scalars(select(ConfigDefinition.id).where(
        ConfigDefinition.owner_type == "llm_profile", ConfigDefinition.owner_id == profile_id,
    )).all())
    database.add_all([row for row in _profile_definitions(profile_id) if row.id not in existing])


def _draft(database, environment: str, owner_type: str, owner_id: str, values: dict[str, object]) -> ConfigRelease:
    row = database.scalar(select(ConfigRelease).where(
        ConfigRelease.environment_id == environment, ConfigRelease.owner_type == owner_type,
        ConfigRelease.owner_id == owner_id, ConfigRelease.status == "draft",
    ).order_by(ConfigRelease.version.desc()))
    if row and row.created_by != "system/llm-import":
        raise RuntimeError(f"{owner_type}/{owner_id} 已有非导入草稿，拒绝覆盖")
    if row is None:
        version = (database.scalar(select(func.max(ConfigRelease.version)).where(
            ConfigRelease.environment_id == environment, ConfigRelease.owner_type == owner_type,
            ConfigRelease.owner_id == owner_id,
        )) or 0) + 1
        row = ConfigRelease(
            id=new_id("rel"), environment_id=environment, owner_type=owner_type,
            owner_id=owner_id, version=version, revision=1, status="draft",
            created_by="system/llm-import",
        )
        database.add(row)
        database.flush()
    definitions = {item.key: item for item in database.scalars(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == owner_type, ConfigDefinition.owner_id == owner_id,
        ConfigDefinition.sensitivity == "normal",
    )).all()}
    database.execute(delete(ConfigReleaseItem).where(
        ConfigReleaseItem.release_id == row.id, ConfigReleaseItem.value_json.is_not(None),
    ))
    for key, value in values.items():
        definition = definitions.get(key)
        if definition is not None and value is not None:
            database.add(ConfigReleaseItem(release_id=row.id, definition_id=definition.id, value_json=value))
    row.revision += 1
    return row


def _put_secret(database, cipher, environment: str, owner_type: str, owner_id: str,
                definition_key: str, plaintext: str) -> None:
    definition = database.scalar(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == owner_type, ConfigDefinition.owner_id == owner_id,
        ConfigDefinition.key == definition_key,
    ))
    if definition is None:
        raise RuntimeError("导入目标 Secret 定义不存在")
    secret_id = f"sec_{environment}_{definition.id.replace('.', '_')}"
    secret = database.get(Secret, secret_id)
    if secret is None:
        secret = Secret(
            id=secret_id, environment_id=environment, owner_type=owner_type,
            owner_id=owner_id, definition_id=definition.id, status="missing",
        )
        database.add(secret)
        database.flush()
    if secret.current_version_id:
        try:
            if decrypt_secret(database, cipher, secret) == plaintext:
                return
        except ValueError:
            pass
    replace_secret(database, cipher, secret, plaintext, "system/llm-import")


def main() -> None:
    parser = argparse.ArgumentParser(description="导入现有 LLM 配置为未发布草稿")
    parser.add_argument("--environment", required=True, choices=("dev", "prod"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--log-base-url")
    parser.add_argument("--log-model")
    parser.add_argument("--log-key-file")
    args = parser.parse_args()
    settings = get_settings()
    with SessionLocal() as database:
        cipher = load_secret_cipher(settings)
        sources = [source for source in (
            _legacy_source(database, cipher, args.environment, "functional-test-agent", "llmb_functional_default"),
            _legacy_source(database, cipher, args.environment, "api-test-agent", "llmb_api_default"),
        ) if source]
        if args.log_base_url or args.log_model or args.log_key_file:
            if not all((args.log_base_url, args.log_model, args.log_key_file)):
                raise SystemExit("日志配置参数必须同时提供；未输出任何配置值")
            sources.append(SourceConfig(
                "log-filter", "llmb_log_people_search", args.log_base_url, args.log_model,
                Path(args.log_key_file).read_text(encoding="utf-8").strip(), 0.1, 3400, 28,
            ))
        groups: list[list[SourceConfig]] = []
        for source in sources:
            group = next((item for item in groups if (item[0].base_url, item[0].model, item[0].api_key) ==
                          (source.base_url, source.model, source.api_key)), None)
            if group is None:
                groups.append([source])
            else:
                group.append(source)
        if args.dry_run:
            print(f"dry-run: 可导入工具 {len(sources)}，需要 Profile {len(groups)}；未读取输出任何 Secret")
            return
        for index, group in enumerate(groups, start=1):
            profile_id = "llmp_shared_default" if len(groups) == 1 else f"llmp_legacy_{group[0].tool_id.replace('-', '_')}"
            _ensure_profile(database, profile_id, "DeepSeek Shared" if len(groups) == 1 else f"Legacy {index}")
            source = group[0]
            _draft(database, args.environment, "llm_profile", profile_id, {
                "BASE_URL": source.base_url, "MODEL": source.model, "ENABLED": True,
            })
            _put_secret(database, cipher, args.environment, "llm_profile", profile_id, "API_KEY", source.api_key)
            for item in group:
                _draft(database, args.environment, "llm_binding", item.binding_id, {
                    "PROFILE_ID": profile_id, "ENABLED": True,
                    "TEMPERATURE_OVERRIDE": item.temperature,
                    "MAX_TOKENS_OVERRIDE": item.max_tokens,
                    "TIMEOUT_SECONDS_OVERRIDE": item.timeout_seconds,
                })
        database.commit()
        print(f"apply: 已创建或更新 {len(groups)} 个 Profile 草稿和 {len(sources)} 个 Binding 草稿；未发布")


if __name__ == "__main__":
    main()
