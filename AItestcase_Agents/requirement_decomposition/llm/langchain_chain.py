"""轻量 Prompt 调用链。

本模块只负责把 Prompt 渲染后交给可注入 LLMClient 执行。真实 LangChain
调用由 DefaultLLMClient 复用项目已有 `agents.common.config.settings.llm` 完成。
"""

from __future__ import annotations

from requirement_decomposition.llm.llm_client import LLMClient
from requirement_decomposition.llm.prompt_loader import load_prompt
from requirement_decomposition.models.schema import LLMConfig


def run_prompt_task(
    prompt_name: str,
    variables: dict[str, object],
    config: LLMConfig,
    client: LLMClient,
    task_name: str | None = None,
) -> str:
    """执行一个固定 Prompt 任务。

    功能说明:
        统一 Prompt 加载、变量渲染和 LLM 调用入口，避免各抽取器重复组织调用逻辑。

    参数说明:
        prompt_name (str): prompts 目录中的 Prompt 文件名，不包含 `.md`。
        variables (dict[str, object]): Prompt 渲染变量。
        config (LLMConfig): LLM 运行配置，用于传递模型和 prompt 版本信息。
        client (LLMClient): 可注入 LLM 客户端，测试中可传入 mock client。
        task_name (str | None): 记录到 LLM client 的任务名，默认与 prompt_name 一致。

    返回值:
        str: LLM 返回的原始文本，通常应为 JSON 字符串。
    """

    prompt = load_prompt(prompt_name)
    rendered = prompt.render(variables)
    return client.complete(task_name or prompt_name, rendered, config)
