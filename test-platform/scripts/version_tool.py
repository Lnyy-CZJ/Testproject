#!/usr/bin/env python3
"""Validate component versions and produce deterministic build/release metadata."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "test-platform" / "versions.json"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    """Load and validate the version manifest without third-party dependencies."""

    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("versions.json schema_version must be 1")
    product = data.get("product", {})
    validate_semver(product.get("version"), "product.version")
    components = data.get("components")
    if not isinstance(components, dict) or not components:
        raise ValueError("versions.json must define components")
    image_envs: set[str] = set()
    for component_id, component in components.items():
        validate_semver(component.get("version"), f"components.{component_id}.version")
        if component.get("compatible_product_major") != int(product["version"].split(".")[0]):
            raise ValueError(f"{component_id} is incompatible with product major")
        if not component.get("source_paths") or not component.get("image_envs"):
            raise ValueError(f"{component_id} requires source_paths and image_envs")
        for image_env in component["image_envs"]:
            if image_env in image_envs:
                raise ValueError(f"duplicate image variable: {image_env}")
            image_envs.add(image_env)
    return data


def validate_semver(value: Any, field: str) -> tuple[int, int, int]:
    """Return comparable SemVer parts and reject leading zeroes or prereleases."""

    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        raise ValueError(f"{field} must be strict SemVer (MAJOR.MINOR.PATCH): {value!r}")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def git(*args: str) -> str:
    """Run a read-only Git command from the repository root."""

    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def component_dirty(paths: list[str]) -> bool:
    """Report tracked or untracked source changes for one component scope."""

    output = git("status", "--porcelain", "--", *paths)
    return bool(output)


def command_validate(_: argparse.Namespace) -> int:
    data = load_manifest()
    print(f"valid: product {data['product']['version']}, {len(data['components'])} components")
    return 0


def command_export(args: argparse.Namespace) -> int:
    data = load_manifest()
    revision = git("rev-parse", "HEAD")
    selected = args.components or list(data["components"])
    unknown = sorted(set(selected) - set(data["components"]))
    if unknown:
        raise ValueError(f"unknown components: {', '.join(unknown)}")
    result = {
        "product_version": data["product"]["version"],
        "revision": revision,
        "components": {
            component_id: {
                "version": data["components"][component_id]["version"],
                "dirty": component_dirty(data["components"][component_id]["source_paths"]),
                "image_envs": data["components"][component_id]["image_envs"],
            }
            for component_id in selected
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def command_check_bump(args: argparse.Namespace) -> int:
    current = load_manifest()
    try:
        previous_raw = git("show", f"{args.base}:test-platform/versions.json")
    except subprocess.CalledProcessError:
        print("versions.json is new; accepting initial component baseline")
        return 0
    previous = json.loads(previous_raw)
    changed = set(git("diff", "--name-only", f"{args.base}...HEAD").splitlines())
    failures: list[str] = []
    for component_id, component in current["components"].items():
        source_changed = any(
            path == prefix or path.startswith(f"{prefix}/")
            for path in changed
            for prefix in component["source_paths"]
        )
        old = previous.get("components", {}).get(component_id, {}).get("version")
        new = component["version"]
        if old is None:
            continue
        if validate_semver(new, component_id) < validate_semver(old, component_id):
            failures.append(f"{component_id}: version decreased {old} -> {new}")
        elif source_changed and new == old:
            failures.append(f"{component_id}: source changed but version remains {new}")
    migration_changed = any(path.startswith("test-platform/backend/alembic/versions/") for path in changed)
    if migration_changed and current["database"]["alembic_revision"] == previous.get("database", {}).get("alembic_revision"):
        failures.append("database migration changed but alembic_revision was not updated")
    for tag in git("tag", "--list", "release-*").splitlines():
        try:
            published = json.loads(git("show", f"{tag}:test-platform/versions.json"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        for component_id, component in current["components"].items():
            old_component = published.get("components", {}).get(component_id, {})
            if old_component.get("version") != component["version"]:
                continue
            diff = git("diff", "--name-only", tag, "HEAD", "--", *component["source_paths"])
            if diff:
                failures.append(
                    f"{component_id}: published version {component['version']} is reused for different source"
                )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("component version changes are valid")
    return 0


def command_bom(args: argparse.Namespace) -> int:
    data = load_manifest()
    images = json.loads(Path(args.images).read_text(encoding="utf-8"))
    components: dict[str, Any] = {}
    for component_id, component in data["components"].items():
        components[component_id] = {
            "version": component["version"],
            "images": {key: images[key] for key in component["image_envs"]},
        }
    bom = {
        "schema_version": 2,
        "product_version": data["product"]["version"],
        "release": args.release,
        "commit": args.commit,
        "components": components,
        "database": data["database"],
        "test_result": args.test_result,
    }
    output = json.dumps(bom, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


def command_report(args: argparse.Namespace) -> int:
    """Render a human-readable Dev/Prod report from machine snapshots and BOM v1/v2."""

    manifest = load_manifest()
    dev = json.loads(Path(args.dev).read_text(encoding="utf-8")) if args.dev else {}
    prod = json.loads(Path(args.prod).read_text(encoding="utf-8")) if args.prod else {}
    bom = json.loads(Path(args.bom).read_text(encoding="utf-8")) if args.bom else {}
    expected = bom.get("components", {})
    lines = [
        "# Environment Version Report", "",
        f"- Product version: `{manifest['product']['version']}`",
        f"- Dev release: `{dev.get('release') or 'unknown'}`",
        f"- Prod release: `{prod.get('release') or bom.get('release') or 'unknown'}`",
        "", "| Component | Manifest | Dev actual | Prod actual | Prod expected |",
        "| --- | --- | --- | --- | --- |",
    ]
    for component_id, component in manifest["components"].items():
        dev_version = dev.get("components", {}).get(component_id, {}).get("version", "unknown")
        prod_version = prod.get("components", {}).get(component_id, {}).get("version", "unknown")
        expected_version = expected.get(component_id, {}).get("version", "旧发布记录 / 版本未知")
        lines.append(
            f"| {component_id} | `{component['version']}` | `{dev_version}` | `{prod_version}` | `{expected_version}` |"
        )
    lines.extend([
        "",
        f"- Dev database: `{dev.get('database', {}).get('alembic_revision', 'unknown')}`",
        f"- Prod database: `{prod.get('database', {}).get('alembic_revision', bom.get('database', {}).get('alembic_revision', 'unknown'))}`",
    ])
    output = "\n".join(lines) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.set_defaults(handler=command_validate)
    export = commands.add_parser("export")
    export.add_argument("components", nargs="*")
    export.set_defaults(handler=command_export)
    bump = commands.add_parser("check-bump")
    bump.add_argument("--base", required=True)
    bump.set_defaults(handler=command_check_bump)
    bom = commands.add_parser("bom")
    bom.add_argument("--release", required=True)
    bom.add_argument("--commit", required=True)
    bom.add_argument("--images", required=True)
    bom.add_argument("--output")
    bom.add_argument("--test-result", default="passed")
    bom.set_defaults(handler=command_bom)
    report = commands.add_parser("report")
    report.add_argument("--dev")
    report.add_argument("--prod")
    report.add_argument("--bom")
    report.add_argument("--output")
    report.set_defaults(handler=command_report)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        return args.handler(args)
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"version-tool: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
