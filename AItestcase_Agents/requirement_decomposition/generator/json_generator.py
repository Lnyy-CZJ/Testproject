"""JSON 输出生成器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_requirements_json(data: dict[str, Any], path: str) -> None:
    """写入完整结构化需求 JSON。"""

    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
