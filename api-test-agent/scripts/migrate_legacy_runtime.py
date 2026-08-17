"""把旧单仓库中的 API 任务运行数据安全复制到独立项目。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


AGENT = "api"
EXCLUDED_NAMES = {".env", ".git", ".pytest_cache", "__pycache__", "output", "secrets"}


def file_sha256(path: Path) -> str:
    """流式计算文件 SHA-256，避免把日志或产物整体载入内存。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_root(path: Path, environment: str, *, must_exist: bool) -> Path:
    """校验运行数据根目录，拒绝宽泛路径、符号链接和跨环境目录。"""

    if not environment or "/" in environment or ".." in environment:
        raise ValueError("environment 不合法")
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ValueError(f"拒绝符号链接根目录: {expanded}")
    resolved = expanded.resolve(strict=must_exist)
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise ValueError("拒绝宽泛运行数据路径")
    if resolved.name != AGENT or resolved.parent.name != environment:
        raise ValueError(f"路径必须以 runtime/{environment}/{AGENT} 结尾")
    return resolved


def scan_source(source: Path) -> list[dict[str, Any]]:
    """扫描可复制文件并生成包含任务状态与恢复说明的权威清单。"""

    entries: list[dict[str, Any]] = []
    task_status: dict[str, str] = {}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_symlink():
            raise ValueError(f"源目录包含符号链接: {relative}")
        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        if not path.is_file():
            continue
        if relative.name == "task.json" and len(relative.parts) >= 3 and relative.parts[0] == "tasks":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                task_status[relative.parts[1]] = str(payload.get("status", "unknown"))
            except (OSError, ValueError):
                task_status[relative.parts[1]] = "corrupt"
        entries.append({
            "relative_path": relative.as_posix(),
            "size": path.stat().st_size,
            "sha256": file_sha256(path),
        })
    for entry in entries:
        parts = Path(entry["relative_path"]).parts
        if len(parts) >= 2 and parts[0] == "tasks":
            status = task_status.get(parts[1], "unknown")
            entry["task_status"] = status
            if status == "running":
                entry["recovery"] = "启动后由 TaskStore 恢复为 failed/WORKER_INTERRUPTED"
    return entries


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """在目标目录内原子发布 JSON，异常时不留下半写文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def compare_destination(destination: Path, entries: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """返回缺失与冲突文件；同名不同内容永远视为阻断。"""

    missing: list[str] = []
    conflicts: list[str] = []
    for entry in entries:
        target = (destination / entry["relative_path"]).resolve()
        if destination not in target.parents:
            raise ValueError("目标文件越界")
        if target.is_symlink():
            conflicts.append(entry["relative_path"])
        elif not target.exists():
            missing.append(entry["relative_path"])
        elif not target.is_file() or file_sha256(target) != entry["sha256"]:
            conflicts.append(entry["relative_path"])
    return missing, conflicts


def copy_missing(source: Path, destination: Path, missing: list[str]) -> None:
    """逐文件临时写入并原子发布；中断后可安全重跑补齐剩余文件。"""

    for relative in missing:
        source_file = source / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with source_file.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
                for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            os.replace(temporary, target)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise


def migrate(args: argparse.Namespace) -> dict[str, Any]:
    """执行 dry-run、复制或只校验模式，并返回机器可读结果。"""

    source = validate_root(Path(args.source), args.environment, must_exist=True)
    destination = validate_root(Path(args.destination), args.environment, must_exist=False)
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("源与目标不得相同或互相包含")
    entries = scan_source(source)
    missing, conflicts = compare_destination(destination, entries) if destination.exists() else ([item["relative_path"] for item in entries], [])
    if conflicts:
        raise FileExistsError(f"目标存在同名不同内容文件: {', '.join(conflicts[:10])}")
    result = {
        "schema_version": 1,
        "agent": AGENT,
        "environment": args.environment,
        "source": str(source),
        "destination": str(destination),
        "mode": "verify-only" if args.verify_only else ("dry-run" if args.dry_run else "copy"),
        "file_count": len(entries),
        "total_bytes": sum(item["size"] for item in entries),
        "missing_count": len(missing),
        "conflict_count": 0,
        "files": entries,
    }
    if args.verify_only and missing:
        raise FileNotFoundError(f"目标缺少 {len(missing)} 个文件")
    if not args.dry_run and not args.verify_only:
        destination.mkdir(parents=True, exist_ok=True)
        copy_missing(source, destination, missing)
        remaining, post_conflicts = compare_destination(destination, entries)
        if remaining or post_conflicts:
            raise RuntimeError("复制后 SHA 校验失败")
        result["missing_count"] = 0
        result["copied_count"] = len(missing)
    if args.manifest:
        atomic_json(Path(args.manifest).expanduser().resolve(), result)
    return result


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""

    parser = argparse.ArgumentParser(description=f"迁移 {AGENT} 智能体旧 runtime")
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--manifest")
    return parser


def main() -> int:
    """运行迁移并输出不含文件正文与 Secret 的摘要。"""

    parser = build_parser()
    args = parser.parse_args()
    if args.dry_run and args.verify_only:
        parser.error("--dry-run 与 --verify-only 不能同时使用")
    try:
        result = migrate(args)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"迁移失败: {exc}\n")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
