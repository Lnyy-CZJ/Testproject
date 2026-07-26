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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests
from dotenv import load_dotenv


SERVICE_NAME = "tool.people_insight.SearchService"
RESULT_SCHEMA_VERSION = "1.3.1"
ProgressCallback = Callable[[dict[str, Any]], None]
RawCallback = Callable[[dict[str, Any]], None]
FailureCallback = Callable[[dict[str, Any]], None]


def normalize_result_status(
    query_status: str,
    candidate_count_listed: int | None,
) -> str:
    """把采集流程状态转换为稳定的评估结果状态。

    参数说明:
        query_status: Query 的采集明细状态。
        candidate_count_listed: ListTaskCandidates 实际返回数量。

    返回值:
        ``HAS_CANDIDATES``、``NO_CANDIDATES`` 或
        ``EXECUTION_FAILED``。候选人数优先，避免部分详情失败影响结果分类。
    """

    try:
        count = int(candidate_count_listed or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        return "HAS_CANDIDATES"
    if query_status in {"FAILED", "EXECUTION_FAILED"}:
        return "EXECUTION_FAILED"
    return "NO_CANDIDATES"


class ConfigError(ValueError):
    """Raised when local configuration is invalid."""


class FlowError(RuntimeError):
    """表示采集流程中的可记录业务失败。

    除失败阶段、消息和 task_id 外，还可携带接口已返回的业务响应以及本
    Query 已收集的脱敏 Raw，供上层写入 failures.jsonl。
    """

    def __init__(
        self,
        stage: str,
        message: str,
        task_id: str = "",
        response_body: Any = None,
    ) -> None:
        """初始化流程错误。

        参数说明:
            stage: 失败的输入或接口阶段。
            message: 面向测试人员的可读错误。
            task_id: 已创建的任务标识，创建前失败时为空。
            response_body: 失败时已获得的业务响应，HTTP 无响应时为 None。
        """

        super().__init__(message)
        self.stage = stage
        self.task_id = task_id
        self.response_body = response_body
        self.raw_records: list[dict[str, Any]] = []


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
        """调用统一 HTTP RPC 接口并校验公共业务响应。

        参数说明:
            method_name: Create/Get/List/Detail 的接口方法名。
            params: 当前接口的业务参数。

        返回值:
            已通过 HTTP、顶层 code 和 responses[0] 校验的完整响应对象。

        异常说明:
            FlowError: HTTP、JSON 格式或业务 code 异常时抛出；如果已经取得
            业务响应，会放入异常的 response_body 供 Raw 记录使用。
        """

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
            response_body = None
            error_response = getattr(exc, "response", None)
            if error_response is not None:
                try:
                    response_body = error_response.json()
                except (ValueError, TypeError):
                    response_body = None
            raise FlowError(
                method_name,
                f"HTTP 请求失败: {exc}",
                response_body=response_body,
            ) from exc
        except (ValueError, TypeError) as exc:
            raise FlowError(method_name, "接口响应不是合法 JSON") from exc

        try:
            return self._validate_response(method_name, body)
        except FlowError as exc:
            # 业务失败响应仍属于可追溯 Raw；只挂到异常，不在客户端保存鉴权请求。
            exc.response_body = body
            raise

    @staticmethod
    def _validate_response(method_name: str, body: Any) -> dict[str, Any]:
        """校验 RPC 公共响应结构并返回原始对象。

        参数说明:
            method_name: 用于错误定位的接口方法名。
            body: HTTP JSON 响应。

        返回值:
            结构及业务状态均合法的原始响应字典。

        异常说明:
            FlowError: 响应不是对象、缺少 data 或任一级业务状态失败。
        """

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


def sanitize_raw(value: Any) -> Any:
    """递归移除 Raw 数据中的鉴权字段并保留其他未知业务字段。

    功能说明:
        Raw 只允许保存接口业务参数和业务响应。该函数会从任意层级移除
        Token、Cookie、Header、Device ID 和 User ID 等敏感键，数组顺序和
        其他未识别字段保持不变。

    参数说明:
        value: 待保存的 JSON 兼容值，可以是对象、数组或标量。

    返回值:
        可安全写入 Raw 的新值；不会原地修改接口返回对象。

    异常说明:
        本函数不主动抛出业务异常；非容器值按原值返回。
    """

    sensitive_keys = {
        "auth_token",
        "authorization",
        "cookie",
        "set_cookie",
        "headers",
        "http_headers",
        "device_id",
        "user_id",
    }
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if normalized_key in sensitive_keys:
                continue
            sanitized[str(key)] = sanitize_raw(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_raw(item) for item in value]
    return value


def utc_now_text() -> str:
    """返回带时区的 UTC ISO 8601 时间，用于采集和失败记录。"""

    return datetime.now(timezone.utc).isoformat()


def emit_callback(
    callback: Callable[[dict[str, Any]], None] | None,
    record: dict[str, Any],
) -> None:
    """在配置回调时同步发送记录，未配置时保持旧 CLI 行为。"""

    if callback is not None:
        callback(record)


def resolve_query_stage(item: dict[str, Any]) -> str:
    """解析 v1.3 Query 类型，并兼容未显式配置类型的旧输入。

    参数说明:
        item: 当前 Query 输入对象。

    返回值:
        ``FULL_NAME`` 或 ``FULL_NAME_SOCIAL``。旧输入存在 SOCIAL_LINK
        线索时推断为后者，否则推断为前者。

    异常说明:
        FlowError: 显式 query_stage 不属于 v1.3 MVP 支持范围时抛出。
    """

    query_stage = item.get("query_stage")
    if query_stage is None:
        clues = item.get("clues")
        clue_list = clues if isinstance(clues, list) else []
        clue_types = {
            clue.get("type")
            for clue in clue_list
            if isinstance(clue, dict)
        }
        return "FULL_NAME_SOCIAL" if "SOCIAL_LINK" in clue_types else "FULL_NAME"
    if query_stage not in {"FULL_NAME", "FULL_NAME_SOCIAL"}:
        raise FlowError(
            "Input",
            "query_stage 只支持 FULL_NAME 或 FULL_NAME_SOCIAL",
        )
    return query_stage


def build_raw_record(
    *,
    run_id: str,
    input_id: str,
    task_id: str,
    candidate_id: str,
    stage: str,
    sequence_no: int,
    request_params: dict[str, Any],
    response_body: Any,
    error: str = "",
) -> dict[str, Any]:
    """构造一条不含鉴权信息的 v1.3 Raw 回调记录。

    参数说明:
        run_id: 当前批次标识。
        input_id: Query 唯一标识。
        task_id: 已取得的接口任务标识，Create 阶段允许为空。
        candidate_id: Candidate Detail 阶段的候选人标识，其他阶段为空。
        stage: 实际接口方法名。
        sequence_no: 同阶段调用顺序，GetTask 从 1 开始。
        request_params: 请求中的业务参数，不包含 comm 和 HTTP Header。
        response_body: 接口完整业务响应；HTTP 无响应时为 None。
        error: 失败时的可读错误，成功时为空字符串。

    返回值:
        可直接交给 RawCallback 或写入 JSONL 的脱敏字典。
    """

    return {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "input_id": input_id,
        "task_id": task_id,
        "candidate_id": candidate_id,
        "stage": stage,
        "sequence_no": sequence_no,
        "request_params": sanitize_raw(request_params),
        "response_body": sanitize_raw(response_body),
        "error": error,
        "collected_at": utc_now_text(),
    }


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
    query_stage = resolve_query_stage(item)

    return {
        "input_id": input_id,
        "query_stage": query_stage,
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
    progress_callback: ProgressCallback | None = None,
    raw_callback: RawCallback | None = None,
    failure_callback: FailureCallback | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """顺序执行单条检索流程并生成向后兼容的 v1.3 结果记录。

    参数说明:
        item: 已校验的 CreateIntentTask 参数，包含唯一 ``input_id``。
        client: 按顺序调用四个接口的同步客户端。
        sleep_fn: GetTask 轮询等待函数，测试时可注入无等待实现。
        progress_callback: 可选进度回调，只发送业务标识、阶段和状态。
        raw_callback: 可选 Raw 回调，每次接口调用后发送脱敏业务请求与响应。
        failure_callback: 可选候选级失败回调，用于写入 failures.jsonl。
        run_id: 当前运行标识；未提供时为直接调用自动生成。

    返回值:
        v1.3 结果字典。保留旧的 input/task/count/results 字段，并新增
        Query 状态、详情成功/失败数、完整 Raw、List 原项和详情状态。

    异常说明:
        FlowError: Create/Get/List 的 Query 级错误仍向上抛出；单个 Candidate
        Detail 错误在循环内隔离、记录后继续处理下一候选人。
    """

    input_id = item["input_id"]
    effective_run_id = run_id or f"run_{uuid.uuid4().hex}"
    task_id = ""
    candidate_count_total: int | None = None
    raw_records: list[dict[str, Any]] = []

    def emit_progress(event: str, **values: Any) -> None:
        """补齐通用标识后发送单条进度事件。"""

        emit_callback(
            progress_callback,
            {
                "event": event,
                "run_id": effective_run_id,
                "input_id": input_id,
                "task_id": task_id,
                **values,
            },
        )

    def call_and_record(
        stage: str,
        params: dict[str, Any],
        *,
        sequence_no: int = 1,
        candidate_id: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """执行一次接口调用，并在成功或失败后立即生成脱敏 Raw。"""

        try:
            body = client.call(stage, params)
        except FlowError as exc:
            record = build_raw_record(
                run_id=effective_run_id,
                input_id=input_id,
                task_id=task_id or exc.task_id,
                candidate_id=candidate_id,
                stage=stage,
                sequence_no=sequence_no,
                request_params=params,
                response_body=exc.response_body,
                error=str(exc),
            )
            raw_records.append(record)
            emit_callback(raw_callback, record)
            raise

        record_task_id = task_id
        if stage == "CreateIntentTask" and not record_task_id:
            create_task_id = body.get("responses", [{}])[0].get("data", {}).get(
                "task_id"
            )
            if isinstance(create_task_id, str):
                record_task_id = create_task_id
        record = build_raw_record(
            run_id=effective_run_id,
            input_id=input_id,
            task_id=record_task_id,
            candidate_id=candidate_id,
            stage=stage,
            sequence_no=sequence_no,
            request_params=params,
            response_body=body,
        )
        raw_records.append(record)
        emit_callback(raw_callback, record)
        return body, record

    def raw_payload(record: dict[str, Any]) -> dict[str, Any]:
        """提取适合嵌入 results.jsonl 的请求、响应和顺序字段。"""

        return {
            "sequence_no": record["sequence_no"],
            "request_params": record["request_params"],
            "response_body": record["response_body"],
            "error": record["error"],
            "collected_at": record["collected_at"],
        }

    emit_progress("query_started", stage="Input", status="RUNNING")
    try:
        query_stage = resolve_query_stage(item)
        create_params = {
            "match_strategy": item["match_strategy"],
            "clues": item["clues"],
            "additional_details": item["additional_details"],
        }
        create_body, create_raw = call_and_record(
            "CreateIntentTask",
            create_params,
        )
        create_data = response_data(create_body, "CreateIntentTask")
        task_id_value = create_data.get("task_id")
        if not isinstance(task_id_value, str) or not task_id_value:
            raise FlowError("CreateIntentTask", "响应缺少 task_id")
        task_id = task_id_value
        emit_progress(
            "query_stage",
            stage="CreateIntentTask",
            status="SUCCEEDED",
            message="任务创建成功",
        )

        get_task_history: list[dict[str, Any]] = []
        task_data: dict[str, Any] = {}
        for poll_sequence in range(1, client.config.max_poll_count + 1):
            sleep_fn(client.config.poll_interval_seconds)
            task_body, task_raw = call_and_record(
                "GetTask",
                {"task_id": task_id},
                sequence_no=poll_sequence,
            )
            get_task_history.append(raw_payload(task_raw))
            task_data = response_data(task_body, "GetTask", task_id)
            status = task_data.get("status")
            emit_progress(
                "query_stage",
                stage="GetTask",
                status=status,
                message=(
                    "任务完成"
                    if status == "SUCCEEDED"
                    else "任务未完成，继续轮询"
                ),
            )
            if status == "SUCCEEDED":
                total_value = task_data.get("candidate_count")
                if (
                    isinstance(total_value, int)
                    and not isinstance(total_value, bool)
                    and total_value >= 0
                ):
                    candidate_count_total = total_value
                break
            # QUEUED 和 SEARCHING 都表示任务尚未完成，继续下一轮 GetTask 轮询。
            if status not in {"QUEUED", "SEARCHING"}:
                raise FlowError("GetTask", f"未知任务状态: {status!r}", task_id)
        else:
            raise FlowError("GetTask", "任务轮询超时", task_id)

        # 分页字段当前仅为接口预留；固定放大 page_size，接收全部候选人。
        list_params = {
            "task_id": task_id,
            "page": {"page_size": 100, "page_token": ""},
        }
        list_body, list_raw = call_and_record("ListTaskCandidates", list_params)
        items = response_data(list_body, "ListTaskCandidates", task_id).get("items")
        if not isinstance(items, list):
            raise FlowError("ListTaskCandidates", "响应中的 items 必须是数组", task_id)
        emit_progress(
            "query_stage",
            stage="ListTaskCandidates",
            status="SUCCEEDED",
            candidate_count=len(items),
            message=f"返回候选人 {len(items)} 个",
        )

        results: list[dict[str, Any]] = []
        detail_success_count = 0
        detail_failure_count = 0

        def record_candidate_failure(
            *,
            candidate_rank: int,
            candidate_id: str,
            rank_score: int | float | None,
            stage: str,
            error: str,
            list_item: Any,
            detail_response: Any = None,
        ) -> None:
            """同时构造失败候选人结果、失败记录和进度事件。"""

            nonlocal detail_failure_count
            detail_failure_count += 1
            sanitized_list_item = sanitize_raw(list_item)
            sanitized_detail_response = sanitize_raw(detail_response)
            results.append(
                {
                    "candidate_rank": candidate_rank,
                    "candidate_id": candidate_id,
                    "rank_score": rank_score,
                    "detail_status": "FAILED",
                    "detail_error": error,
                    "list_item_raw": sanitized_list_item,
                    "detail_data_raw": None,
                    "detail_response_raw": sanitized_detail_response,
                    "ui_sections": None,
                }
            )
            failure_record = {
                "failure_schema_version": RESULT_SCHEMA_VERSION,
                "run_id": effective_run_id,
                "input_id": input_id,
                "task_id": task_id,
                "candidate_id": candidate_id,
                "candidate_rank": candidate_rank,
                "scope": "CANDIDATE",
                "stage": stage,
                "query_status": "PARTIAL_DETAIL_FAILED",
                "result_status": "HAS_CANDIDATES",
                "error": error,
                "raw": {
                    "list_item_raw": sanitized_list_item,
                    "detail_response_raw": sanitized_detail_response,
                },
                "created_at": utc_now_text(),
            }
            emit_callback(failure_callback, failure_record)
            emit_progress(
                "candidate_failed",
                stage=stage,
                status="FAILED",
                candidate_id=candidate_id,
                candidate_rank=candidate_rank,
                message=error,
            )

        for candidate_rank, candidate in enumerate(items, start=1):
            candidate_id = ""
            rank_score: int | float | None = None
            if isinstance(candidate, dict):
                candidate_id_value = candidate.get("candidate_id")
                if isinstance(candidate_id_value, str):
                    candidate_id = candidate_id_value
                rank_score_value = candidate.get("rank_score")
                if (
                    isinstance(rank_score_value, (int, float))
                    and not isinstance(rank_score_value, bool)
                ):
                    rank_score = rank_score_value
            emit_progress(
                "candidate_started",
                stage="GetTaskCandidateDetail",
                status="RUNNING",
                candidate_id=candidate_id,
                candidate_rank=candidate_rank,
            )

            if not isinstance(candidate, dict):
                record_candidate_failure(
                    candidate_rank=candidate_rank,
                    candidate_id="",
                    rank_score=None,
                    stage="ListTaskCandidates",
                    error="候选人数据必须是对象",
                    list_item=candidate,
                )
                continue
            if not candidate_id:
                record_candidate_failure(
                    candidate_rank=candidate_rank,
                    candidate_id="",
                    rank_score=rank_score,
                    stage="ListTaskCandidates",
                    error="候选人缺少 candidate_id",
                    list_item=candidate,
                )
                continue

            detail_body: dict[str, Any] | None = None
            try:
                detail_body, _ = call_and_record(
                    "GetTaskCandidateDetail",
                    {"task_id": task_id, "candidate_id": candidate_id},
                    sequence_no=candidate_rank,
                    candidate_id=candidate_id,
                )
                detail_data = response_data(
                    detail_body,
                    "GetTaskCandidateDetail",
                    task_id,
                )
                ui_sections = detail_data.get("ui_sections", {})
                if not isinstance(ui_sections, dict):
                    raise FlowError(
                        "GetTaskCandidateDetail",
                        f"候选人 {candidate_id} 的 ui_sections 必须是对象",
                        task_id,
                    )
            except FlowError as exc:
                detail_response = (
                    exc.response_body
                    if exc.response_body is not None
                    else detail_body
                )
                record_candidate_failure(
                    candidate_rank=candidate_rank,
                    candidate_id=candidate_id,
                    rank_score=rank_score,
                    stage=exc.stage,
                    error=str(exc),
                    list_item=candidate,
                    detail_response=detail_response,
                )
                continue

            detail_success_count += 1
            results.append(
                {
                    "candidate_rank": candidate_rank,
                    "candidate_id": candidate_id,
                    "rank_score": rank_score,
                    "detail_status": "SUCCESS",
                    "detail_error": "",
                    "list_item_raw": sanitize_raw(candidate),
                    "detail_data_raw": sanitize_raw(detail_data),
                    "detail_response_raw": sanitize_raw(detail_body),
                    "ui_sections": sanitize_raw(ui_sections),
                }
            )
            emit_progress(
                "candidate_succeeded",
                stage="GetTaskCandidateDetail",
                status="SUCCESS",
                candidate_id=candidate_id,
                candidate_rank=candidate_rank,
            )

        if not items:
            query_status = "NO_CANDIDATE"
        elif detail_failure_count:
            query_status = "PARTIAL_DETAIL_FAILED"
        else:
            query_status = "SUCCESS"

        result = {
            "result_schema_version": RESULT_SCHEMA_VERSION,
            "run_id": effective_run_id,
            "input_id": input_id,
            "task_id": task_id,
            "query_stage": query_stage,
            "query_status": query_status,
            "result_status": normalize_result_status(
                query_status,
                len(items),
            ),
            "candidate_count_total": candidate_count_total,
            "candidate_count_listed": len(items),
            "detail_success_count": detail_success_count,
            "detail_failure_count": detail_failure_count,
            "task_fields": {
                "llm_cost": sanitize_raw(task_data.get("llm_cost")),
                "third_party_cost": sanitize_raw(
                    task_data.get("third_party_cost")
                ),
                "total_cost": sanitize_raw(task_data.get("total_cost")),
                "pdl_called": sanitize_raw(task_data.get("pdl_called")),
                "search_duration_ms": sanitize_raw(
                    task_data.get("search_duration_ms")
                ),
            },
            "raw": {
                "create_intent_task": raw_payload(create_raw),
                "get_task_history": get_task_history,
                "list_task_candidates": raw_payload(list_raw),
            },
            "results": results,
        }
        emit_progress(
            "query_succeeded",
            stage="Completed",
            status=query_status,
            candidate_count=len(items),
            detail_success_count=detail_success_count,
            detail_failure_count=detail_failure_count,
        )
        return result
    except FlowError as exc:
        if not exc.task_id and task_id:
            exc.task_id = task_id
        exc.raw_records = raw_records
        emit_progress(
            "query_failed",
            stage=exc.stage,
            status="FAILED",
            message=str(exc),
        )
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
    progress_callback: ProgressCallback | None = None,
    raw_callback: RawCallback | None = None,
    run_id: str = "",
) -> tuple[int, int]:
    """顺序执行一个 JSONL 批次并写入 v1.3 结果与失败文件。

    功能说明:
        保持现有 CLI 的文件选择和顺序执行方式。Query 级失败继续下一输入；
        Candidate 级失败由 ``process_one`` 隔离并立即写入 failures.jsonl。

    参数说明:
        input_path: 输入任务 JSONL。
        output_dir: 未显式传入结果路径时使用的输出目录。
        client: 同步搜索接口客户端。
        sleep_fn: 轮询等待函数。
        results_path: 可选结果文件；为空时使用 output/results.jsonl。
        failures_path: 可选失败文件；为空时使用 output/failures.jsonl。
        progress_callback: 可选进度事件回调。
        raw_callback: 可选脱敏 Raw 回调。
        run_id: 可选运行标识；为空时为整个批次生成一个标识。

    返回值:
        ``(完整成功或无候选人 Query 数, 失败或部分失败 Query 数)``。

    异常说明:
        单条业务 FlowError 会写失败文件并继续；文件系统错误和回调自身错误
        不会被吞掉，交由调用方处理。
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = results_path or output_dir / "results.jsonl"
    failures_path = failures_path or output_dir / "failures.jsonl"
    results_path.write_text("", encoding="utf-8")
    failures_path.write_text("", encoding="utf-8")
    effective_run_id = run_id or f"run_{uuid.uuid4().hex}"

    def write_candidate_failure(record: dict[str, Any]) -> None:
        """把候选级失败写入本批次 failures.jsonl。"""

        append_jsonl(failures_path, record)

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
            result = process_one(
                item,
                client,
                sleep_fn,
                progress_callback=progress_callback,
                raw_callback=raw_callback,
                failure_callback=write_candidate_failure,
                run_id=effective_run_id,
            )
            append_jsonl(results_path, result)
            if result["query_status"] == "PARTIAL_DETAIL_FAILED":
                failure_count += 1
                print(
                    f"[{item['input_id']}] 部分完成，候选人详情成功 "
                    f"{result['detail_success_count']} 个、失败 "
                    f"{result['detail_failure_count']} 个",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                success_count += 1
                print(
                    f"[{item['input_id']}] 完成，候选人 {len(result['results'])} 个",
                    flush=True,
                )
        except FlowError as exc:
            failure_record = {
                "failure_schema_version": RESULT_SCHEMA_VERSION,
                "run_id": effective_run_id,
                "input_id": fallback_input_id,
                "task_id": exc.task_id,
                "candidate_id": "",
                "scope": "INPUT" if exc.stage == "Input" else "QUERY",
                "stage": exc.stage,
                "query_status": "FAILED",
                "result_status": "EXECUTION_FAILED",
                "error": str(exc),
                "raw": exc.raw_records,
                "created_at": utc_now_text(),
            }
            append_jsonl(failures_path, failure_record)
            if exc.stage == "Input":
                emit_callback(
                    progress_callback,
                    {
                        "event": "query_failed",
                        "run_id": effective_run_id,
                        "input_id": fallback_input_id,
                        "task_id": exc.task_id,
                        "stage": exc.stage,
                        "status": "FAILED",
                        "message": str(exc),
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
