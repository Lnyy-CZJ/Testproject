"""只补齐结构化业务覆盖缺口的最小 LLM 适配器。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

from services.api_agent.models import BaseTestCase, CoverageMatrixItem


ModelCallable = Callable[[str], Any]
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def create_business_supplementer(model: ModelCallable | None = None):
    """创建只允许返回基础用例字段的补齐器。

    模型不能修改契约事实、确定性用例或覆盖结论；非法输出被忽略并作为
    可见缺口保留，外层覆盖循环仍严格限制为最多三轮。
    """

    def invoke(prompt: str) -> Any:
        if model is not None:
            return model(prompt)
        from agents.common.config.settings import llm

        response = llm.invoke(prompt)
        return getattr(response, "content", response)

    def supplement(missing: list[CoverageMatrixItem], _cases: list[BaseTestCase], round_number: int) -> list[BaseTestCase]:
        allowed = {(item.contract_id, item.dimension) for item in missing}
        prompt = (
            "你只负责补充 API 测试业务场景，不得修改接口契约。"
            "仅返回 JSON 数组，每项只含 contract_id、dimension、name、objective；"
            f"当前轮次 {round_number}，允许的缺口为："
            + json.dumps([{"contract_id": item.contract_id, "dimension": item.dimension, "rule": item.rule} for item in missing], ensure_ascii=False)
        )
        try:
            raw = invoke(prompt)
            if isinstance(raw, str):
                raw = json.loads(_FENCE.sub("", raw.strip()))
        except Exception:
            return []
        generated = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("contract_id", "")), str(item.get("dimension", "")))
            if key not in allowed or not item.get("name") or not item.get("objective"):
                continue
            digest = hashlib.sha256(f"{key[0]}|{key[1]}|{item['name']}".encode()).hexdigest()[:20]
            generated.append(BaseTestCase(
                case_id=f"case_{digest}", contract_id=key[0], dimension=key[1],
                name=str(item["name"]), objective=str(item["objective"]),
                source="llm", status="confirmed_candidate",
            ))
        return generated

    return supplement
