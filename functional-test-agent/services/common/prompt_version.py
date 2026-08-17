"""计算实际 Prompt Bundle 的确定性版本。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def prompt_bundle_sha256(project_root: Path, paths: list[str]) -> str:
    """按相对路径排序哈希 Prompt 路径和原始字节。"""

    digest = hashlib.sha256()
    files: list[Path] = []
    root = Path(project_root).resolve()
    for raw in paths:
        candidate = (root / raw).resolve()
        if candidate.is_dir():
            files.extend(path for path in candidate.rglob("*") if path.is_file())
        elif candidate.is_file():
            files.append(candidate)
    for path in sorted(set(files), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()

