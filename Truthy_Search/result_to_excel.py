#!/usr/bin/env python3
"""Launch the artifact-tool based JSONL-to-Excel exporter.

This Python entry point keeps the project command consistent with ``search_tool.py``
while delegating workbook authoring to the bundled JavaScript spreadsheet runtime.
It does not read credentials or access the network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
BUILDER = PROJECT_ROOT / "result_to_excel_builder.mjs"
BUNDLED_NODE = Path(
    "/Users/admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
)


def find_node() -> Path:
    """Locate a Node.js executable that can load the spreadsheet runtime.

    Returns:
        Path to Node.js. ``SEARCHTOOL_NODE`` takes precedence, followed by the
        bundled Codex runtime and then the system ``node`` executable.

    Raises:
        RuntimeError: If no usable Node.js executable can be found.
    """

    configured = os.getenv("SEARCHTOOL_NODE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(BUNDLED_NODE)
    system_node = shutil.which("node")
    if system_node:
        candidates.append(Path(system_node))

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError(
        "找不到可用的 Node.js。请设置 SEARCHTOOL_NODE 指向 Codex 工作区依赖中的 node。"
    )


def prepare_arguments(argv: list[str]) -> list[str]:
    """Load an optional dotenv file and inject missing Excel CLI settings.

    Args:
        argv: Original command-line arguments, including the ``single`` or
            ``compare`` mode.

    Returns:
        Arguments for the JavaScript builder. ``--env-file`` is consumed by this
        wrapper, explicit CLI values are preserved, and only missing values are
        populated from ``EXCEL_*`` environment variables.

    Raises:
        ValueError: If ``--env-file`` has no following path.
    """

    prepared = list(argv)
    env_file = Path(".env")
    if "--env-file" in prepared:
        index = prepared.index("--env-file")
        if index + 1 >= len(prepared):
            raise ValueError("--env-file 后必须提供文件路径")
        env_file = Path(prepared[index + 1])
        del prepared[index : index + 2]
    load_dotenv(env_file, override=False)

    if not prepared or any(value in {"-h", "--help"} for value in prepared):
        return prepared
    mode = prepared[0]
    mappings = {
        "single": {
            "--results-file": "EXCEL_RESULTS_FILE",
            "--failures-file": "EXCEL_FAILURES_FILE",
            "--run-label": "EXCEL_RUN_LABEL",
            "--system-version": "EXCEL_SYSTEM_VERSION",
            "--evaluation-id": "EXCEL_EVALUATION_ID",
            "--metadata": "EXCEL_METADATA_FILE",
            "--output": "EXCEL_OUTPUT_FILE",
        },
        "compare": {
            "--baseline-results-file": "EXCEL_BASELINE_RESULTS_FILE",
            "--baseline-failures-file": "EXCEL_BASELINE_FAILURES_FILE",
            "--baseline-version": "EXCEL_BASELINE_VERSION",
            "--candidate-results-file": "EXCEL_CANDIDATE_RESULTS_FILE",
            "--candidate-failures-file": "EXCEL_CANDIDATE_FAILURES_FILE",
            "--candidate-version": "EXCEL_CANDIDATE_VERSION",
            "--evaluation-id": "EXCEL_EVALUATION_ID",
            "--metadata": "EXCEL_METADATA_FILE",
            "--output": "EXCEL_OUTPUT_FILE",
        },
    }
    for flag, env_name in mappings.get(mode, {}).items():
        if flag in prepared:
            continue
        value = os.getenv(env_name, "").strip()
        if value:
            prepared.extend([flag, value])
    return prepared


def main(argv: list[str] | None = None) -> int:
    """Run the JavaScript exporter and return its exit code.

    Args:
        argv: Exporter CLI arguments. Defaults to ``sys.argv[1:]``.

    Returns:
        The JavaScript process exit code. Startup errors return 1.
    """

    if not BUILDER.is_file():
        print(f"导出程序不存在: {BUILDER}", file=sys.stderr)
        return 1
    try:
        node = find_node()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        prepared_args = prepare_arguments(argv if argv is not None else sys.argv[1:])
    except ValueError as exc:
        print(f"参数错误: {exc}", file=sys.stderr)
        return 1

    completed = subprocess.run(
        [str(node), str(BUILDER), *prepared_args],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
