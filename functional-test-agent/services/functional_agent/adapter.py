"""功能测试工作流与公共任务协议之间的适配器。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from services.common.artifacts import publish_artifact
from services.common.task_store import TaskStore


def safe_slug(value: str, fallback: str) -> str:
    """把展示名称转换为不会形成目录越界的稳定 slug。"""

    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return (slug[:64] or fallback)


def _json_count(path: Path) -> int:
    """读取 JSON 列表数量，格式异常时返回零。"""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            for key in ("test_points", "test_point", "point", "test_cases"):
                if isinstance(value.get(key), list):
                    return len(value[key])
    except (OSError, json.JSONDecodeError):
        pass
    return 0


def collect_result(store: TaskStore, task_id: str, task_dir: Path, runner_result: dict[str, Any]) -> dict[str, Any]:
    """发布功能工作流产物并从真实文件生成摘要。"""

    output_dir = task_dir / "work" / "output"
    artifacts = []
    points_count = 0
    cases_count = 0
    for source in sorted(path for path in output_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".json", ".md", ".xlsx"}):
        relative = source.relative_to(output_dir).as_posix()
        if "test_points" in relative:
            artifact_type, group = ("test_points_json" if source.suffix == ".json" else "test_points_markdown"), "test-points"
            if source.suffix == ".json":
                points_count = max(points_count, _json_count(source))
        elif source.suffix == ".xlsx" or "testcases" in source.name:
            artifact_type, group = ("test_cases_xlsx" if source.suffix == ".xlsx" else "test_cases_json"), "test-cases"
            if source.suffix == ".json":
                cases_count = max(cases_count, _json_count(source))
        else:
            artifact_type, group = ("requirements_json" if source.suffix == ".json" else "requirements_markdown"), "requirements"
        artifacts.append(publish_artifact(
            store, task_id, source, artifact_type=artifact_type,
            stage=runner_result.get("stage", "publishing_artifacts"), destination_group=group,
        ))
    if not artifacts:
        raise RuntimeError("功能工作流没有可发布产物")
    result = {
        "status": runner_result.get("next_status", "succeeded"),
        "stage": runner_result.get("stage", "completed"),
        "result_summary": {"test_points": points_count, "test_cases": cases_count, "artifact_count": len(artifacts)},
        "artifacts": artifacts,
        "token_usage": runner_result.get("token_usage", {}),
    }
    if result["status"] == "waiting_review":
        point_artifacts = [item for item in artifacts if item.get("type") == "test_points_json"]
        if point_artifacts:
            source = point_artifacts[-1]
            result["review_source"] = {"artifact_id": source["id"], "sha256": source["sha256"], "test_point_count": points_count}
    if result["status"] == "waiting_case_review":
        case_artifacts = [item for item in artifacts if item.get("type") == "test_cases_json"]
        if case_artifacts:
            source = case_artifacts[-1]
            result["case_review_source"] = {"artifact_id": source["id"], "sha256": source["sha256"], "test_case_count": cases_count}
    return result
