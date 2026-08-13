"""API 生成工作流与公共任务协议之间的适配器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.common.artifacts import publish_artifact
from services.common.task_store import TaskStore


def _count(path: Path) -> int:
    """读取 JSON 数组数量，异常时返回零。"""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return len(value) if isinstance(value, list) else 1
    except (OSError, json.JSONDecodeError):
        return 0


def collect_result(store: TaskStore, task_id: str, task_dir: Path, runner_result: dict[str, Any]) -> dict[str, Any]:
    """发布 API JSON 产物并生成真实数量摘要。"""

    record = store.load(task_id) or {}
    if record.get("schema_version") == 2:
        return {
            "status": runner_result.get("next_status", "failed"),
            "stage": runner_result.get("stage", "api_v2"),
            "result_summary": {
                key: value for key, value in runner_result.items()
                if key.endswith("_count") or key.endswith("_version") or key == "interface_count"
            },
            "artifacts": [],
        }

    mapping = {
        "parsed-api.json": "parsed_api_json",
        "base-cases.json": "api_base_cases_json",
        "executable-cases.json": "api_executable_cases_json",
        "generation-summary.json": "api_generation_summary_json",
    }
    artifacts = []
    output = task_dir / "work" / "output"
    for name, artifact_type in mapping.items():
        source = output / name
        if source.is_file():
            artifacts.append(publish_artifact(
                store, task_id, source, artifact_type=artifact_type,
                stage=runner_result.get("stage", "publishing_artifacts"), destination_group="test-cases",
            ))
    if not artifacts:
        raise RuntimeError("API 工作流没有可发布产物")
    return {
        "status": "succeeded",
        "stage": "completed",
        "result_summary": {
            "interfaces": runner_result.get("interface_count", _count(output / "parsed-api.json")),
            "base_cases": runner_result.get("base_case_count", _count(output / "base-cases.json")),
            "executable_cases": runner_result.get("executable_case_count", _count(output / "executable-cases.json")),
            "database_persist_status": runner_result.get("database_persist_status", "skipped"),
            "artifact_count": len(artifacts),
        },
        "artifacts": artifacts,
    }
