"""Prompt 模板加载器。"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel


class PromptTemplate(BaseModel):
    """带版本信息的 Prompt 模板。"""

    prompt_name: str
    version: str
    template: str
    path: str

    def render(self, variables: dict[str, object]) -> str:
        """渲染 `{{ name }}` 风格变量。"""

        rendered = self.template
        for key, value in variables.items():
            rendered = re.sub(
                r"\{\{\s*" + re.escape(key) + r"\s*\}\}",
                str(value),
                rendered,
            )
        return rendered


DEFAULT_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(prompt_name: str, prompt_dir: str | Path | None = None) -> PromptTemplate:
    """按名称加载 Prompt 文件。

    功能说明:
        默认从项目根目录的 prompts 读取，避免任务 Runner 切换 cwd 后把相对
        路径错误解析到每任务 work 目录。测试和专用调用仍可显式覆盖目录。

    参数说明:
        prompt_name: Prompt 文件名，不包含 `.md`。
        prompt_dir: 可选 Prompt 目录；为空时使用项目固定目录。

    返回值:
        PromptTemplate: 已解析 front matter 的模板。

    异常说明:
        文件不存在或元数据不合法时保持原异常语义，由需求拆解统一记录失败。
    """

    active_dir = DEFAULT_PROMPT_DIR if prompt_dir is None else Path(prompt_dir).expanduser().resolve()
    prompt_path = active_dir / f"{prompt_name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {prompt_path}")

    content = prompt_path.read_text(encoding="utf-8")
    metadata, template = _parse_front_matter(content, prompt_path)
    return PromptTemplate(
        prompt_name=metadata["prompt_name"],
        version=metadata["version"],
        template=template.strip(),
        path=str(prompt_path),
    )


def _parse_front_matter(content: str, prompt_path: Path) -> tuple[dict, str]:
    """解析 Markdown front matter。"""

    match = re.match(r"^---\n([\s\S]*?)\n---\n([\s\S]*)$", content)
    if not match:
        raise ValueError(f"Prompt 缺少 YAML front matter: {prompt_path}")

    metadata = yaml.safe_load(match.group(1)) or {}
    if "prompt_name" not in metadata or "version" not in metadata:
        raise ValueError(f"Prompt front matter 必须包含 prompt_name 和 version: {prompt_path}")
    return metadata, match.group(2)
