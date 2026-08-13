"""Markdown 文档解析。"""

from __future__ import annotations

from pathlib import Path

from requirement_decomposition.models.schema import SourceDocument


def parse_markdown_document(
    path: str,
    source_id: str = "SRC-001",
    trust_level: str = "high",
) -> SourceDocument:
    """读取 Markdown 文档并保留原文。

    第一阶段只做轻量解析：文件读取、类型标记和原文保留。标题切片由
    `section_chunker` 负责完成。
    """

    source_path = Path(path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Markdown 需求文档不存在: {source_path}")

    content = source_path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"Markdown 需求文档内容为空: {source_path}")

    return SourceDocument(
        source_id=source_id,
        source_type="markdown",
        path=str(source_path),
        trust_level=trust_level,  # type: ignore[arg-type]
        content=content,
    )
