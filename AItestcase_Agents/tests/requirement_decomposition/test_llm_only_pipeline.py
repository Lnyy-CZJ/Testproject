from __future__ import annotations

import yaml

from requirement_decomposition import run_decomposition


class BrokenLLMClient:
    """模拟 LLM 调用失败。"""

    def complete(self, task_name: str, prompt: str, config) -> str:
        raise RuntimeError("LLM unavailable")


def test_llm_failure_returns_error_in_llm_only_pipeline(tmp_path):
    source_file = tmp_path / "order.md"
    source_file.write_text(
        "# 订单系统\n\n## 取消订单\n用户可以取消待支付订单。\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "requirement_decomposition.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "sources": [{"source_id": "SRC-001", "path": str(source_file)}],
                "llm": {"enabled": True},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    result = run_decomposition(
        source_path=str(source_file),
        config_path=str(config_file),
        llm_client=BrokenLLMClient(),
    )

    assert result.success is False
    assert result.requirements == []
    assert "LLM unavailable" in result.errors[0]


def test_llm_disabled_returns_error_in_llm_only_pipeline(tmp_path):
    source_file = tmp_path / "order.md"
    source_file.write_text(
        "# 订单系统\n\n## 取消订单\n用户可以取消待支付订单。\n",
        encoding="utf-8",
    )
    config_file = tmp_path / "requirement_decomposition.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "sources": [{"source_id": "SRC-001", "path": str(source_file)}],
                "llm": {"enabled": False},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    result = run_decomposition(source_path=str(source_file), config_path=str(config_file))

    assert result.success is False
    assert "LLM 已关闭" in result.errors[0]
