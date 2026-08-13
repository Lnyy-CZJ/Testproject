"""LLM 客户端协议与 JSON 解析工具。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from requirement_decomposition.models.schema import LLMConfig


class LLMClient(Protocol):
    """可注入 LLM 客户端协议。

    测试阶段使用 fake client；真实客户端后续只要实现同名 `complete` 方法即可接入。
    """

    def complete(self, task_name: str, prompt: str, config: LLMConfig) -> str:
        """执行一次 LLM 调用，并返回 JSON 字符串。"""


@dataclass(frozen=True)
class LLMCall:
    """一次 LLM 调用的元信息。"""

    task_name: str
    prompt_version: str
    prompt: str


class DefaultLLMClient:
    """默认 LLM 客户端。

    默认直接复用项目已有配置：`from agents.common.config.settings import llm`。
    该对象是 LangChain ChatOpenAI 实例，通常通过 `invoke(prompt)` 返回消息对象。
    """

    def __init__(self, llm_instance: Any | None = None):
        """初始化默认客户端，测试中可注入 fake llm。"""

        self.llm_instance = llm_instance

    def complete(self, task_name: str, prompt: str, config: LLMConfig) -> str:
        """调用项目统一 LLM，并返回文本内容。"""

        model = self.llm_instance or _load_project_llm()
        actual_model = getattr(model, "model_name", None) or getattr(model, "model", None)
        if actual_model and config is not None:
            # 记录实际 ChatOpenAI 实例的模型，避免 YAML 展示值与真实调用不一致。
            config.model = str(actual_model)
        response = model.invoke(prompt)
        if isinstance(response, str):
            return response
        content = getattr(response, "content", None)
        if content is None:
            raise RuntimeError(f"LLM 任务 {task_name} 未返回 content")
        if isinstance(content, list):
            return "\n".join(str(item) for item in content)
        return str(content)


def _load_project_llm() -> Any:
    """延迟导入项目已有 LLM 配置，避免模块导入时就初始化模型。"""

    from agents.common.config.settings import llm

    return llm


def parse_json_response(raw_response: str) -> Any:
    """解析 LLM 返回的 JSON，支持裸 JSON 和 Markdown fenced JSON。"""

    text = raw_response.strip()
    fence_match = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 容错处理：有些模型会在 JSON 前后追加少量说明，这里提取第一个对象或数组。
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if not match:
            raise
        return json.loads(match.group(1))


def parse_json_response_with_repair(
    raw_response: str,
    client: LLMClient,
    config: LLMConfig,
    task_name: str,
) -> Any:
    """解析 JSON，失败时调用 LLM 做一次格式修复。

    功能说明:
        真实模型偶尔会漏逗号、混入说明文字或输出半结构化 JSON。这里不改变语义，
        只在解析失败时请求模型修复为合法 JSON，避免整篇需求拆解被单个格式错误中断。

    参数说明:
        raw_response (str): 原始 LLM 输出。
        client (LLMClient): 当前 LLM 客户端。
        config (LLMConfig): LLM 配置。
        task_name (str): 原任务名，用于修复 Prompt 中说明上下文。

    返回值:
        Any: 解析后的 JSON 对象或数组。
    """

    try:
        return parse_json_response(raw_response)
    except json.JSONDecodeError:
        from requirement_decomposition.llm.prompt_loader import load_prompt

        prompt = load_prompt("json_repair")
        repaired = client.complete(
            "json_repair",
            prompt.render({"task_name": task_name, "raw_response": raw_response}),
            config,
        )
        return parse_json_response(repaired)
