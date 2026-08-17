"""功能智能体 LLM Token 用量的任务级采集与原子汇总。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from langchain_core.callbacks import UsageMetadataCallbackHandler


def _usage_path() -> Path | None:
    """根据 Runner 注入的任务环境返回汇总文件；CLI 未注入时不落盘。"""

    root, task_id = os.getenv("AGENT_DATA_DIR"), os.getenv("TASK_ID")
    if not root or not task_id or "/" in task_id or "\\" in task_id:
        return None
    task_dir = (Path(root).resolve() / task_id).resolve()
    if Path(root).resolve() not in task_dir.parents:
        return None
    return task_dir / "token-usage.json"


def _summarize(handler: UsageMetadataCallbackHandler) -> dict[str, int]:
    """合并回调按模型记录的 usage_metadata，兼容未返回用量的模型。"""

    result = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for usage in handler.usage_metadata.values():
        for key in result:
            result[key] += int(usage.get(key, 0) or 0)
    return result


def record_token_usage(stage: str, usage: dict[str, int]) -> None:
    """原子累计单次调用用量；模型不报告 Token 时仍记录调用次数。"""

    path = _usage_path()
    if path is None:
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "stages": {}}
    except (OSError, json.JSONDecodeError):
        payload = {"schema_version": 1, "stages": {}}
    item = payload.setdefault("stages", {}).setdefault(stage, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "calls": 0, "reported_calls": 0})
    item["calls"] += 1
    if any(usage.values()):
        item["reported_calls"] += 1
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            item[key] += int(usage.get(key, 0) or 0)
    totals = {key: sum(int(value.get(key, 0) or 0) for value in payload["stages"].values()) for key in ("input_tokens", "output_tokens", "total_tokens")}
    payload["totals"] = totals
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def invoke_with_token_usage(runnable: Any, payload: Any, stage: str) -> Any:
    """为一次 LangChain 调用附加 Usage 回调，并在成功或失败后累计用量。"""

    handler = UsageMetadataCallbackHandler()
    try:
        try:
            return runnable.invoke(payload, config={"callbacks": [handler]})
        except TypeError as exc:
            # 既有单元测试与 CLI 插件可能注入仅接受 payload 的轻量 fake。
            if "config" not in str(exc):
                raise
            return runnable.invoke(payload)
    finally:
        record_token_usage(stage, _summarize(handler))


def load_token_usage() -> dict[str, Any]:
    """读取当前任务汇总；文件缺失或损坏时返回空结构。"""

    path = _usage_path()
    if path is None or not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
