"""Web 页面展示用的四条冻结 Flow；执行仍由 Adapter/Runner 负责。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowSpec:
    key: str
    label: str
    mode: str
    task_kind: str
    steps: tuple[str, ...]


FLOWS = (
    FlowSpec(
        "e2e-analysis",
        "完整 E2E · Analysis",
        "e2e",
        "analysis",
        ("Identity", "Media Upload", "Quota", "Task", "Result", "Delete"),
    ),
    FlowSpec(
        "e2e-reply",
        "完整 E2E · Reply",
        "e2e",
        "reply",
        ("Identity", "Preferences", "Media Upload", "Task", "Result", "Delete"),
    ),
    FlowSpec(
        "eval-analysis",
        "快速批量 · Analysis",
        "eval",
        "analysis",
        ("Create Evaluation Task", "Poll", "Result", "Diagnostics", "Delete"),
    ),
    FlowSpec(
        "eval-reply",
        "快速批量 · Reply",
        "eval",
        "reply",
        ("Create Evaluation Task", "Poll", "Result", "Diagnostics", "Delete"),
    ),
)


def flow_catalog() -> tuple[FlowSpec, ...]:
    return FLOWS


__all__ = ["FlowSpec", "FLOWS", "flow_catalog"]
