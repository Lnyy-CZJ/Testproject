"""Markdown section 切片。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from requirement_decomposition.models.schema import RequirementSection, SourceDocument

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class _OpenSection:
    """切片过程中的临时 section。"""

    title: str
    heading_path: list[str]
    lines: list[str] = field(default_factory=list)


def chunk_markdown_sections(document: SourceDocument) -> list[RequirementSection]:
    """按 Markdown 标题切分文档。

    只有包含正文的标题块才会生成 section，避免把纯父级标题误当成需求。
    """

    sections: list[RequirementSection] = []
    heading_stack: list[tuple[int, str]] = []
    current: _OpenSection | None = None

    for raw_line in document.content.splitlines():
        heading = _HEADING_RE.match(raw_line)
        if heading:
            _flush_section(document, sections, current)
            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_stack = [
                (existing_level, existing_title)
                for existing_level, existing_title in heading_stack
                if existing_level < level
            ]
            heading_stack.append((level, title))
            current = _OpenSection(
                title=title,
                heading_path=[item_title for _, item_title in heading_stack],
            )
            continue

        if current is None:
            # 没有标题的前置正文使用“未命名章节”承接，避免丢失原文。
            current = _OpenSection(title="未命名章节", heading_path=["未命名章节"])
        current.lines.append(raw_line)

    _flush_section(document, sections, current)
    return sections


def _flush_section(
    document: SourceDocument,
    sections: list[RequirementSection],
    current: _OpenSection | None,
) -> None:
    """将当前 section 写入结果列表。"""

    if current is None:
        return

    content = "\n".join(current.lines).strip()
    if not content:
        return

    section_id = f"SEC-{len(sections) + 1:03d}"
    sections.append(
        RequirementSection(
            source_id=document.source_id,
            section_id=section_id,
            title=current.title,
            heading_path=current.heading_path,
            content=content,
            quote=content,
        )
    )
