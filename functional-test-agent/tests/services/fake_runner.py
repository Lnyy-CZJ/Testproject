"""TaskManager 测试使用的确定性子进程。"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from services.common.task_store import TaskStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    store = TaskStore(Path(os.environ["AGENT_DATA_DIR"]))
    task_dir = store.task_dir(args.task_id)
    payload = json.loads((task_dir / "request.json").read_text(encoding="utf-8"))
    execution_path = task_dir / "execution.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8")) if execution_path.exists() else {"kind": "initial", "sequence": 0}
    order_file = store.data_dir / "order.log"
    with order_file.open("a", encoding="utf-8") as handle:
        handle.write(f"{args.task_id}\n")
    time.sleep(float(payload.get("sleep", 0)))
    output = task_dir / "work" / "output.json"
    output.write_text("[]", encoding="utf-8")
    result = {"execution_kind": execution["kind"], "execution_sequence": execution["sequence"], "next_status": "succeeded", "stage": "completed"}
    if execution["kind"] == "review_ai":
        result["review_ai"] = {"request_version": execution.get("review_ai_request_version"), "suggestion_count": 1}
    elif execution["kind"] == "case_review_ai":
        result["case_review_ai"] = {"request_version": execution.get("case_review_ai_request_version"), "suggestion_count": 1}
    TaskStore.atomic_write_json(task_dir / "runner-result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
