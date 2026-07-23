#!/usr/bin/env python3
"""Run People Insight search tasks sequentially and save ui_sections results."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

import requests
from dotenv import load_dotenv


SERVICE_NAME = "tool.people_insight.SearchService"


class ConfigError(ValueError):
    """Raised when local configuration is invalid."""


class FlowError(RuntimeError):
    """A failure at one stage of the four-step request flow."""

    def __init__(self, stage: str, message: str, task_id: str = "") -> None:
        super().__init__(message)
        self.stage = stage
        self.task_id = task_id


@dataclass(frozen=True)
class Config:
    api_url: str
    headers: dict[str, str]
    auth_token: str
    device_id: str
    user_id: str
    poll_interval_seconds: float = 5.0
    max_poll_count: int = 60
    http_timeout_seconds: float = 30.0
    platform: str = "ios"
    app_version: str = "1.0.0"
    locale: str = "zh-Hans-CN"
    timezone: str = "UTC+08:00"
    input_file: str = "input/tasks.jsonl"
    output_dir: str = "output"
    allow_duplicate_run: bool = False

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Config":
        load_dotenv(dotenv_path=env_file, override=False)

        required_names = [
            "SEARCH_API_URL",
            "AUTH_TOKEN",
            "DEVICE_ID",
            "USER_ID",
        ]
        missing = [name for name in required_names if not os.getenv(name, "").strip()]
        if missing:
            raise ConfigError(f"缺少必要配置: {', '.join(missing)}")

        raw_headers = os.getenv("SEARCH_HTTP_HEADERS_JSON", "{}")
        try:
            headers = json.loads(raw_headers)
        except json.JSONDecodeError as exc:
            raise ConfigError("SEARCH_HTTP_HEADERS_JSON 必须是合法 JSON 对象") from exc
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in headers.items()
        ):
            raise ConfigError("SEARCH_HTTP_HEADERS_JSON 的键和值都必须是字符串")

        poll_interval = _positive_float("POLL_INTERVAL_SECONDS", 5.0)
        max_poll_count = _positive_int("MAX_POLL_COUNT", 60)
        http_timeout = _positive_float("HTTP_TIMEOUT_SECONDS", 30.0)

        return cls(
            api_url=os.environ["SEARCH_API_URL"].strip(),
            headers=headers,
            auth_token=os.environ["AUTH_TOKEN"].strip(),
            device_id=os.environ["DEVICE_ID"].strip(),
            user_id=os.environ["USER_ID"].strip(),
            poll_interval_seconds=poll_interval,
            max_poll_count=max_poll_count,
            http_timeout_seconds=http_timeout,
            platform=os.getenv("PLATFORM", "ios").strip() or "ios",
            app_version=os.getenv("APP_VERSION", "1.0.0").strip() or "1.0.0",
            locale=os.getenv("LOCALE", "zh-Hans-CN").strip() or "zh-Hans-CN",
            timezone=os.getenv("TIMEZONE", "UTC+08:00").strip() or "UTC+08:00",
            input_file=os.getenv("SEARCH_INPUT_FILE", "input/tasks.jsonl").strip()
            or "input/tasks.jsonl",
            output_dir=os.getenv("SEARCH_OUTPUT_DIR", "output").strip() or "output",
            allow_duplicate_run=_env_bool("ALLOW_DUPLICATE_RUN", False),
        )


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是数字") from exc
    if value <= 0:
        raise ConfigError(f"{name} 必须大于 0")
    return value


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数") from exc
    if value <= 0:
        raise ConfigError(f"{name} 必须大于 0")
    return value


def _env_bool(name: str, default: bool) -> bool:
    """Parse a strict boolean environment setting.

    Args:
        name: Environment variable name.
        default: Value returned when the variable is absent or blank.

    Returns:
        ``True`` for ``true/1/yes/on`` and ``False`` for
        ``false/0/no/off`` (case-insensitive).

    Raises:
        ConfigError: If a non-empty value is not a recognized boolean.
    """

    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"true", "1", "yes", "on"}:
        return True
    if raw in {"false", "0", "no", "off"}:
        return False
    raise ConfigError(f"{name} 必须是 true 或 false")


def select_output_paths(
    input_path: Path,
    output_dir: Path,
    allow_duplicate: bool,
    run_date: date | None = None,
) -> tuple[Path, Path]:
    """Choose protected result/failure paths for one search run.

    Args:
        input_path: Selected JSONL input. Only its filename stem is used.
        output_dir: Directory receiving result files.
        allow_duplicate: Whether an existing same-day run may create a new,
            incremented ``runNN`` pair.
        run_date: Date used in filenames. Defaults to the local current date;
            tests inject a fixed date.

    Returns:
        ``(results_path, failures_path)`` using ``YYYYMMDD_input`` naming.

    Raises:
        FileExistsError: If the first pair already exists and duplicate runs are
        disabled. Existing files are never overwritten by this selector.
    """

    date_text = (run_date or date.today()).strftime("%Y%m%d")
    base_prefix = f"{date_text}_{input_path.stem}"

    def paths_for(prefix: str) -> tuple[Path, Path]:
        return (
            output_dir / f"{prefix}_results.jsonl",
            output_dir / f"{prefix}_failures.jsonl",
        )

    first = paths_for(base_prefix)
    if not any(path.exists() for path in first):
        return first
    if not allow_duplicate:
        raise FileExistsError(
            f"同日同输入的结果已存在: {first[0]}。如需新增一次运行，请在 .env 设置 "
            "ALLOW_DUPLICATE_RUN=true"
        )

    run_number = 2
    while True:
        candidate = paths_for(f"{base_prefix}_run{run_number:02d}")
        if not any(path.exists() for path in candidate):
            return candidate
        run_number += 1


class SearchClient:
    def __init__(self, config: Config, session: Any | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def call(self, method_name: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "comm": {
                "auth_token": self.config.auth_token,
                "device_id": self.config.device_id,
                "user_id": self.config.user_id,
                "client_request_id": f"crid-{int(time.time() * 1000)}-{uuid.uuid4().hex[:10]}",
                "platform": self.config.platform,
                "app_version": self.config.app_version,
                "locale": self.config.locale,
                "timezone": self.config.timezone,
            },
            "requests": [
                {
                    "id": "req_0",
                    "service_name": SERVICE_NAME,
                    "method_name": method_name,
                    "params": params,
                }
            ],
        }
        headers = {"Content-Type": "application/json", **self.config.headers}

        try:
            response = self.session.post(
                self.config.api_url,
                headers=headers,
                json=payload,
                timeout=self.config.http_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            raise FlowError(method_name, f"HTTP 请求失败: {exc}") from exc
        except (ValueError, TypeError) as exc:
            raise FlowError(method_name, "接口响应不是合法 JSON") from exc

        return self._validate_response(method_name, body)

    @staticmethod
    def _validate_response(method_name: str, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise FlowError(method_name, "接口响应必须是 JSON 对象")
        if body.get("code") != 0:
            raise FlowError(
                method_name,
                f"接口返回失败: code={body.get('code')}, message={body.get('message', '')}",
            )
        responses = body.get("responses")
        if not isinstance(responses, list) or not responses or not isinstance(responses[0], dict):
            raise FlowError(method_name, "接口响应缺少 responses[0]")
        item = responses[0]
        if item.get("success") is not True or item.get("code", 0) != 0:
            raise FlowError(
                method_name,
                f"方法返回失败: code={item.get('code')}, message={item.get('message', '')}",
            )
        data = item.get("data")
        if not isinstance(data, dict):
            raise FlowError(method_name, "接口响应缺少 responses[0].data")
        return body


def response_data(body: dict[str, Any], stage: str, task_id: str = "") -> dict[str, Any]:
    try:
        data = body["responses"][0]["data"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FlowError(stage, "接口响应缺少 responses[0].data", task_id) from exc
    if not isinstance(data, dict):
        raise FlowError(stage, "responses[0].data 必须是对象", task_id)
    return data


def validate_input(item: Any, line_number: int, seen_ids: set[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise FlowError("Input", f"第 {line_number} 行必须是 JSON 对象")
    input_id = item.get("input_id")
    if not isinstance(input_id, str) or not input_id.strip():
        raise FlowError("Input", f"第 {line_number} 行缺少非空 input_id")
    if input_id in seen_ids:
        raise FlowError("Input", f"第 {line_number} 行 input_id 重复: {input_id}")
    seen_ids.add(input_id)

    clues = item.get("clues")
    if not isinstance(clues, list) or not clues:
        raise FlowError("Input", f"第 {line_number} 行 clues 必须是非空数组")
    additional_details = item.get("additional_details", [])
    if not isinstance(additional_details, list):
        raise FlowError("Input", f"第 {line_number} 行 additional_details 必须是数组")
    match_strategy = item.get("match_strategy", "UNION")
    if not isinstance(match_strategy, str) or not match_strategy:
        raise FlowError("Input", f"第 {line_number} 行 match_strategy 必须是非空字符串")

    return {
        "input_id": input_id,
        "clues": clues,
        "additional_details": additional_details,
        "match_strategy": match_strategy,
    }


def read_jsonl(path: Path) -> Iterable[tuple[int, Any, str | None]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                yield line_number, json.loads(line), None
            except json.JSONDecodeError as exc:
                yield line_number, None, f"第 {line_number} 行 JSON 格式错误: {exc.msg}"


def process_one(
    item: dict[str, Any],
    client: SearchClient,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """顺序执行单条完整检索流程并生成 JSONL 结果记录。

    参数说明:
        item: 已校验的 CreateIntentTask 参数，包含唯一 ``input_id``。
        client: 按顺序调用四个接口的同步客户端。
        sleep_fn: GetTask 轮询等待函数，测试时可注入无等待实现。

    返回值:
        包含候选人总数、List 实际返回数及全部候选人详情的字典。每名候选人
        保留从 1 开始的排名和 ``rank_score``；分数缺失或不是数值时返回 None。

    异常说明:
        FlowError: 任一接口失败、轮询超时或必要响应字段结构不合法时抛出，
        上层批处理会记录失败并继续处理下一条输入。
    """

    input_id = item["input_id"]
    task_id = ""
    candidate_count_total: int | None = None
    try:
        create_body = client.call(
            "CreateIntentTask",
            {
                "match_strategy": item["match_strategy"],
                "clues": item["clues"],
                "additional_details": item["additional_details"],
            },
        )
        create_data = response_data(create_body, "CreateIntentTask")
        task_id_value = create_data.get("task_id")
        if not isinstance(task_id_value, str) or not task_id_value:
            raise FlowError("CreateIntentTask", "响应缺少 task_id")
        task_id = task_id_value

        for _ in range(client.config.max_poll_count):
            sleep_fn(client.config.poll_interval_seconds)
            task_body = client.call("GetTask", {"task_id": task_id})
            task_data = response_data(task_body, "GetTask", task_id)
            status = task_data.get("status")
            if status == "SUCCEEDED":
                total_value = task_data.get("candidate_count")
                if isinstance(total_value, int) and not isinstance(total_value, bool) and total_value >= 0:
                    candidate_count_total = total_value
                break
            # QUEUED 和 SEARCHING 都表示任务尚未完成，继续下一轮 GetTask 轮询。
            if status not in {"QUEUED", "SEARCHING"}:
                raise FlowError("GetTask", f"未知任务状态: {status!r}", task_id)
        else:
            raise FlowError("GetTask", "任务轮询超时", task_id)

        list_body = client.call(
            "ListTaskCandidates",
            # 分页字段当前仅为接口预留；固定放大 page_size，接收接口返回的全部候选人。
            {"task_id": task_id, "page": {"page_size": 100, "page_token": ""}},
        )
        items = response_data(list_body, "ListTaskCandidates", task_id).get("items")
        if not isinstance(items, list):
            raise FlowError("ListTaskCandidates", "响应中的 items 必须是数组", task_id)

        results = []
        for candidate_rank, candidate in enumerate(items, start=1):
            if not isinstance(candidate, dict):
                raise FlowError("ListTaskCandidates", "候选人数据必须是对象", task_id)
            candidate_id = candidate.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise FlowError("ListTaskCandidates", "候选人缺少 candidate_id", task_id)
            rank_score_value = candidate.get("rank_score")
            rank_score = (
                rank_score_value
                if isinstance(rank_score_value, (int, float))
                and not isinstance(rank_score_value, bool)
                else None
            )
            detail_body = client.call(
                "GetTaskCandidateDetail",
                {"task_id": task_id, "candidate_id": candidate_id},
            )
            detail_data = response_data(detail_body, "GetTaskCandidateDetail", task_id)
            ui_sections = detail_data.get("ui_sections", {})
            if not isinstance(ui_sections, dict):
                raise FlowError(
                    "GetTaskCandidateDetail",
                    f"候选人 {candidate_id} 的 ui_sections 必须是对象",
                    task_id,
                )
            results.append(
                {
                    "candidate_rank": candidate_rank,
                    "candidate_id": candidate_id,
                    "rank_score": rank_score,
                    "ui_sections": ui_sections,
                }
            )

        return {
            "input_id": input_id,
            "task_id": task_id,
            "candidate_count_total": candidate_count_total,
            "candidate_count_listed": len(items),
            "results": results,
        }
    except FlowError as exc:
        if not exc.task_id and task_id:
            exc.task_id = task_id
        raise


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")


def run_batch(
    input_path: Path,
    output_dir: Path,
    client: SearchClient,
    sleep_fn: Callable[[float], None] = time.sleep,
    results_path: Path | None = None,
    failures_path: Path | None = None,
) -> tuple[int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_path or output_dir / "results.jsonl"
    failures_path = failures_path or output_dir / "failures.jsonl"
    results_path.write_text("", encoding="utf-8")
    failures_path.write_text("", encoding="utf-8")

    success_count = 0
    failure_count = 0
    seen_ids: set[str] = set()

    for line_number, raw_item, parse_error in read_jsonl(input_path):
        fallback_input_id = f"line-{line_number}"
        if isinstance(raw_item, dict) and isinstance(raw_item.get("input_id"), str):
            fallback_input_id = raw_item["input_id"]
        try:
            if parse_error:
                raise FlowError("Input", parse_error)
            item = validate_input(raw_item, line_number, seen_ids)
            print(f"[{item['input_id']}] 开始处理", flush=True)
            result = process_one(item, client, sleep_fn)
            append_jsonl(results_path, result)
            success_count += 1
            print(
                f"[{item['input_id']}] 完成，候选人 {len(result['results'])} 个",
                flush=True,
            )
        except FlowError as exc:
            append_jsonl(
                failures_path,
                {
                    "input_id": fallback_input_id,
                    "task_id": exc.task_id,
                    "stage": exc.stage,
                    "error": str(exc),
                },
            )
            failure_count += 1
            print(f"[{fallback_input_id}] 失败（{exc.stage}）: {exc}", file=sys.stderr, flush=True)

    return success_count, failure_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="顺序执行 People Insight 搜索任务并提取 ui_sections"
    )
    parser.add_argument(
        "--input",
        default=None,
        help="输入 JSONL 文件；未提供时读取 .env 的 SEARCH_INPUT_FILE",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="结果输出目录；未提供时读取 .env 的 SEARCH_OUTPUT_DIR",
    )
    parser.add_argument("--env-file", default=".env", help="环境变量文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = Config.from_env(Path(args.env_file))
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1

    input_path = Path(args.input or config.input_file)
    if not input_path.is_file():
        print(f"输入文件不存在: {input_path}", file=sys.stderr)
        return 1
    output_dir = Path(args.output or config.output_dir)
    try:
        results_path, failures_path = select_output_paths(
            input_path,
            output_dir,
            config.allow_duplicate_run,
        )
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"输入文件: {input_path}")
    print(f"结果文件: {results_path}")
    print(f"失败文件: {failures_path}")

    success_count, failure_count = run_batch(
        input_path=input_path,
        output_dir=output_dir,
        client=SearchClient(config),
        results_path=results_path,
        failures_path=failures_path,
    )
    print(f"处理结束：成功 {success_count} 条，失败 {failure_count} 条")
    return 2 if failure_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
