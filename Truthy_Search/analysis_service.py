"""searchTool v1.3 历史 JSONL/Excel 校验、归档和统一入库。"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from openpyxl import load_workbook

from analysis_store import AnalysisStore, utc_now_text
from search_tool import (
    RESULT_SCHEMA_VERSION,
    FlowError,
    normalize_result_status,
    process_one,
    sanitize_raw,
)


SUPPORTED_QUERY_STAGES = {"FULL_NAME", "FULL_NAME_SOCIAL"}
EVALUATION_THRESHOLD_FIELDS = {
    "min_retrieval_success": "minimum_ratio",
    "min_matched_completeness": "minimum_ratio",
    "min_matched_accuracy": "minimum_ratio",
    "max_average_total_cost": "maximum_number",
    "max_average_search_duration_ms": "maximum_number",
}
EVALUATION_PHASES = {
    "PHASE_1_BASELINE",
    "PHASE_2_POST_OPTIMIZATION",
    "PHASE_3_TARGETED_ITERATION",
    "UNSPECIFIED",
}
RESULT_STATUSES = {
    "HAS_CANDIDATES",
    "NO_CANDIDATES",
    "EXECUTION_FAILED",
}
TASK_FIELD_KEYS = {
    "llm_cost",
    "third_party_cost",
    "total_cost",
    "pdl_called",
    "search_duration_ms",
}
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FIELD_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
FIELD_PATH_PART_PATTERN = re.compile(
    r"^(?P<key>[A-Za-z0-9_-]+)(?:\[(?P<index>\d+|\*)\])?$"
)
FIELD_MODULES = {
    "Task",
    "Candidate",
    "Insights",
    "Photos",
    "Profile",
    "Social",
    "Summary",
}
FIELD_SOURCE_STAGES = {
    "GetTask",
    "ListTaskCandidates",
    "GetTaskCandidateDetail",
}
FIELD_DATA_TYPES = {
    "string",
    "number",
    "boolean",
    "object",
    "array",
    "url",
    "image",
}
FIELD_ARRAY_MODES = {"preserve", "first", "collect", "join"}
FIELD_EMPTY_RULES = {"default", "zero_is_empty", "false_is_empty"}
FIELD_NORMALIZERS = {
    "identity",
    "trim_text",
    "number",
    "percentage",
    "social_url",
    "string_list",
    "profile_sections",
}
FIELD_SCORING_ROLES = {
    "identity",
    "completeness",
    "accuracy",
    "display",
    "none",
}
FIELD_COMPARE_MODES = {
    "exact",
    "normalized_text",
    "set",
    "url_set",
    "manual",
}
FIELD_VALUE_SCOPES = {"QUERY", "CANDIDATE"}
FIELD_MISSING_POLICIES = {"EMPTY", "ERROR"}
FINAL_JUDGEMENTS = {"HIT", "NOT_HIT", "SUSPECTED"}
REVIEW_REASONS = {
    "SOCIAL_MATCH",
    "SOCIAL_CONFLICT",
    "NO_STRONG_FIELD",
    "MANUAL",
}
CONTENT_FIELD_COUNT = 22
DEFAULT_FIELD_SCHEMA_VERSION = "field-schema-default-v2"
LEGACY_FIELD_PROCESSING_RULE_VERSION = "field-processing-v1"
FIELD_PROCESSING_RULE_VERSION = "field-processing-v2"
METRICS_RULE_VERSION = "metrics-v2"
REPORT_MODEL_VERSION = "report-model-v2"


def _default_field(
    field_key: str,
    display_name: str,
    module: str,
    source_path: str,
    data_type: str,
    sort_order: int,
    *,
    source_stage: str = "GetTaskCandidateDetail",
    array_mode: str = "preserve",
    normalizer: str = "identity",
    scoring_role: list[str] | None = None,
    compare_mode: str = "exact",
    value_scope: str | None = None,
    missing_policy: str | None = None,
) -> dict[str, Any]:
    """构造默认字段配置，并显式保存作用域和字段缺失处理策略。"""

    return {
        "field_key": field_key,
        "display_name": display_name,
        "module": module,
        "source_stage": source_stage,
        "source_path": source_path,
        "data_type": data_type,
        "array_mode": array_mode,
        "empty_rule": "default",
        "normalizer": normalizer,
        "scoring_role": scoring_role or ["display"],
        "compare_mode": compare_mode,
        "enabled": True,
        "sort_order": sort_order,
        "value_scope": value_scope or (
            "QUERY" if module == "Task" else "CANDIDATE"
        ),
        "missing_policy": missing_policy or (
            "ERROR" if field_key in {"task_id", "candidate_id"} else "EMPTY"
        ),
    }


DEFAULT_FIELD_DEFINITIONS = [
    _default_field(
        "task_id",
        "Task ID",
        "Task",
        "task.task_id",
        "string",
        10,
        source_stage="GetTask",
    ),
    _default_field(
        "llm_cost",
        "LLM Cost",
        "Task",
        "task.llm_cost",
        "number",
        20,
        source_stage="GetTask",
    ),
    _default_field(
        "third_party_cost",
        "Third-party Cost",
        "Task",
        "task.third_party_cost",
        "number",
        25,
        source_stage="GetTask",
    ),
    _default_field(
        "total_cost",
        "Total Cost",
        "Task",
        "task.total_cost",
        "number",
        30,
        source_stage="GetTask",
    ),
    _default_field(
        "search_duration_ms",
        "Search Duration (ms)",
        "Task",
        "task.search_duration_ms",
        "number",
        45,
        source_stage="GetTask",
    ),
    _default_field(
        "pdl_called",
        "PDL Called",
        "Task",
        "task.pdl_called",
        "boolean",
        40,
        source_stage="GetTask",
    ),
    _default_field(
        "candidate_id",
        "Candidate ID",
        "Candidate",
        "candidate.candidate_id",
        "string",
        50,
        source_stage="ListTaskCandidates",
    ),
    _default_field(
        "candidate_rank",
        "Candidate Rank",
        "Candidate",
        "candidate.candidate_rank",
        "number",
        60,
        source_stage="ListTaskCandidates",
    ),
    _default_field(
        "rank_score",
        "Rank Score",
        "Candidate",
        "candidate.rank_score",
        "number",
        70,
        source_stage="ListTaskCandidates",
    ),
    _default_field(
        "insights_status",
        "Insights Status",
        "Insights",
        "ui_sections.insights.status",
        "string",
        100,
        normalizer="trim_text",
    ),
    _default_field(
        "insights_description",
        "Insights Description",
        "Insights",
        "ui_sections.insights.data.items[0].description",
        "string",
        110,
        normalizer="trim_text",
        compare_mode="normalized_text",
    ),
    _default_field(
        "insights_links",
        "Insights Links",
        "Insights",
        "ui_sections.insights.data.items[0].links",
        "array",
        120,
        array_mode="collect",
        compare_mode="set",
    ),
    _default_field(
        "insights_data",
        "Insights Data",
        "Insights",
        "ui_sections.insights.data",
        "object",
        130,
    ),
    _default_field(
        "photos_status",
        "Photos Status",
        "Photos",
        "ui_sections.photos.status",
        "string",
        200,
        normalizer="trim_text",
    ),
    _default_field(
        "photos_data",
        "Photos Data",
        "Photos",
        "ui_sections.photos.data",
        "object",
        210,
    ),
    _default_field(
        "photos_identity_match_rate",
        "Photo Identity Match Rate",
        "Photos",
        "ui_sections.photos.data.identity_match_rate",
        "number",
        220,
        normalizer="percentage",
    ),
    _default_field(
        "profile_status",
        "Profile Status",
        "Profile",
        "ui_sections.profile.status",
        "string",
        300,
        normalizer="trim_text",
    ),
    _default_field(
        "profile_data",
        "Profile Data",
        "Profile",
        "ui_sections.profile.data",
        "object",
        310,
    ),
    _default_field(
        "profile_sections",
        "Profile Sections",
        "Profile",
        "ui_sections.profile.data.sections",
        "object",
        320,
        normalizer="profile_sections",
        compare_mode="manual",
    ),
    _default_field(
        "social_status",
        "Social Status",
        "Social",
        "ui_sections.social.status",
        "string",
        400,
        normalizer="trim_text",
    ),
    _default_field(
        "social_display_handles",
        "Social Display Handles",
        "Social",
        "ui_sections.social.data.profiles[*].display_handle",
        "array",
        410,
        array_mode="collect",
        normalizer="string_list",
        compare_mode="set",
    ),
    _default_field(
        "social_platforms",
        "Social Platforms",
        "Social",
        "ui_sections.social.data.profiles[*].platform",
        "array",
        420,
        array_mode="collect",
        normalizer="string_list",
        compare_mode="set",
    ),
    _default_field(
        "social_urls",
        "Social URLs",
        "Social",
        "ui_sections.social.data.profiles[*].url",
        "array",
        430,
        array_mode="collect",
        normalizer="social_url",
        scoring_role=["identity", "completeness", "accuracy"],
        compare_mode="url_set",
    ),
    _default_field(
        "summary_avatar_url",
        "Summary Avatar URL",
        "Summary",
        "ui_sections.summary.data.avatar_url",
        "image",
        500,
    ),
    _default_field(
        "candidate_confidence",
        "Summary Confidence Level",
        "Summary",
        "ui_sections.summary.data.confidence_level",
        "string",
        510,
        normalizer="trim_text",
    ),
    _default_field(
        "summary_primary_image_url",
        "Summary Primary Image URL",
        "Summary",
        "ui_sections.summary.data.primary_image.url",
        "image",
        520,
    ),
    _default_field(
        "summary_social_links",
        "Summary Social Links",
        "Summary",
        "ui_sections.summary.data.social_links",
        "array",
        530,
        array_mode="collect",
        compare_mode="set",
    ),
    _default_field(
        "summary_web_links",
        "Summary Web Links",
        "Summary",
        "ui_sections.summary.data.web_links",
        "array",
        540,
        array_mode="collect",
        compare_mode="set",
    ),
    _default_field(
        "summary_display_name",
        "Summary Display Name",
        "Summary",
        "ui_sections.summary.data.display_name",
        "string",
        550,
        normalizer="trim_text",
        compare_mode="normalized_text",
    ),
    _default_field(
        "summary_location",
        "Summary Location",
        "Summary",
        "ui_sections.summary.data.location",
        "string",
        560,
        normalizer="trim_text",
        compare_mode="normalized_text",
    ),
    _default_field(
        "summary_match_score",
        "Summary Match Score",
        "Summary",
        "ui_sections.summary.data.match_score",
        "number",
        570,
        normalizer="percentage",
    ),
    _default_field(
        "summary_is_top_result",
        "Summary Is Top Result",
        "Summary",
        "ui_sections.summary.data.is_top_result",
        "boolean",
        580,
    ),
    _default_field(
        "summary_is_best_match",
        "Summary Is Best Match",
        "Summary",
        "ui_sections.summary.data.is_best_match",
        "boolean",
        590,
    ),
]


class ImportValidationError(ValueError):
    """导入文件存在格式或业务校验错误。"""

    def __init__(self, errors: Iterable[str]) -> None:
        """保存可供页面预览的全部错误。"""

        self.errors = list(errors)
        super().__init__("；".join(self.errors))


class DuplicateImportError(ValueError):
    """相同 SHA-256 内容已经导入，禁止静默创建副本。"""


class ActiveRunError(RuntimeError):
    """已有待执行或执行中的采集 Run，禁止并行启动第二个 Run。"""


class FieldSchemaValidationError(ValueError):
    """字段配置、路径或转换器输入不符合受限规则。"""

    def __init__(self, errors: str | Iterable[str]) -> None:
        """保存适合 Web 展示的一个或多个字段错误。"""

        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("；".join(self.errors))


class ReviewValidationError(ValueError):
    """候选人复核内容非法或页面版本已经过期。"""

    def __init__(self, errors: str | Iterable[str]) -> None:
        """保存可直接展示给测试人员的复核错误。"""

        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("；".join(self.errors))


@dataclass
class ImportPreview:
    """导入前校验摘要。"""

    checksum: str
    valid_count: int
    errors: list[str]


@dataclass
class ImportResult:
    """一次成功导入的最小返回信息。"""

    object_id: str
    imported_count: int
    checksum: str
    archived_files: list[str]


@dataclass
class ProcessResult:
    """一次字段处理完成后的摘要。"""

    process_id: str
    candidate_count: int
    error_count: int
    status: str


@dataclass
class ReportResult:
    """一次报告快照创建后的可展示和可导出结果。"""

    report_id: str
    model: dict[str, Any]
    html_file: str
    excel_file: str | None


def _source_path_tokens(path: str) -> list[tuple[str, str | int | None]]:
    """解析受限字段路径，不接受表达式、过滤器或函数调用。"""

    if not isinstance(path, str) or not path.strip():
        raise FieldSchemaValidationError("source_path 不能为空")
    tokens: list[tuple[str, str | int | None]] = []
    for part in path.split("."):
        match = FIELD_PATH_PART_PATTERN.fullmatch(part)
        if match is None:
            raise FieldSchemaValidationError(
                f"source_path 语法无效: {path}；只支持点号、[数字] 和 [*]"
            )
        tokens.append(("key", match.group("key")))
        index = match.group("index")
        if index == "*":
            tokens.append(("wildcard", None))
        elif index is not None:
            tokens.append(("index", int(index)))
    return tokens


def extract_source_path(
    source: Any,
    path: str,
    *,
    missing_policy: str = "ERROR",
) -> Any:
    """按受限路径从 JSON 兼容对象提取值。

    参数说明:
        source: Candidate Detail、Task 和 Candidate 组成的处理源对象。
        path: 点号、固定索引和数组通配组成的路径。
        missing_policy: ``EMPTY`` 将缺失键、空父节点和越界索引返回为空；
            ``ERROR`` 保持旧版严格行为。

    返回值:
        无通配时返回单值，缺失可返回 ``None``；存在通配时返回保持原
        顺序的数组，缺失或空数组返回 ``[]``。

    异常说明:
        FieldSchemaValidationError: 策略/路径语法非法，严格模式下路径缺失，
        或已有数据的结构类型不匹配。
    """

    if missing_policy not in FIELD_MISSING_POLICIES:
        raise FieldSchemaValidationError(
            f"不支持的 missing_policy: {missing_policy}"
        )
    values = [source]
    wildcard_used = False
    for token_type, token_value in _source_path_tokens(path):
        next_values: list[Any] = []
        if token_type == "key":
            key = str(token_value)
            for value in values:
                if value is None and missing_policy == "EMPTY":
                    continue
                if not isinstance(value, dict):
                    raise FieldSchemaValidationError(
                        f"source_path 字段父节点不是对象: {path}"
                    )
                if key not in value:
                    if missing_policy == "EMPTY":
                        continue
                    raise FieldSchemaValidationError(
                        f"source_path 找不到字段: {path}"
                    )
                next_values.append(value[key])
        elif token_type == "index":
            index = int(token_value)
            for value in values:
                if value is None and missing_policy == "EMPTY":
                    continue
                if not isinstance(value, list):
                    raise FieldSchemaValidationError(
                        f"source_path 索引目标不是数组: {path}"
                    )
                if index >= len(value):
                    if missing_policy == "EMPTY":
                        continue
                    raise FieldSchemaValidationError(
                        f"source_path 数组索引不存在: {path}"
                    )
                next_values.append(value[index])
        else:
            wildcard_used = True
            for value in values:
                if value is None and missing_policy == "EMPTY":
                    continue
                if not isinstance(value, list):
                    raise FieldSchemaValidationError(
                        f"source_path 通配目标不是数组: {path}"
                    )
                next_values.extend(value)
        values = next_values
    if wildcard_used:
        return values
    if not values and missing_policy == "EMPTY":
        return None
    if len(values) != 1:
        raise FieldSchemaValidationError(f"source_path 无法得到单一值: {path}")
    return values[0]


def _normalize_social_url(value: str) -> str:
    """规范化单个 Social URL，移除明确跟踪信息但保留账号语义。"""

    text = value.strip()
    parsed = urlsplit(text)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise FieldSchemaValidationError(f"不是有效的 http/https URL: {value!r}")
    hostname = parsed.hostname.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    netloc = hostname
    try:
        port = parsed.port
    except ValueError as exc:
        raise FieldSchemaValidationError(
            f"URL 端口无效: {value!r}"
        ) from exc
    if port is not None:
        netloc = f"{hostname}:{port}"
    tracking_names = {"fbclid", "gclid", "mc_cid", "mc_eid"}
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in tracking_names
    ]
    path = parsed.path.rstrip("/")
    return urlunsplit(
        (scheme, netloc, path, urlencode(query, doseq=True), "")
    )


def _normalize_profile_sections(value: Any) -> dict[str, dict[str, Any]]:
    """把 Profile sections/items 转为 section → label → value 对象。"""

    if not isinstance(value, list):
        raise FieldSchemaValidationError("profile_sections 输入必须是数组")
    result: dict[str, dict[str, Any]] = {}
    for section_index, section in enumerate(value):
        if not isinstance(section, dict):
            raise FieldSchemaValidationError(
                f"profile_sections[{section_index}] 必须是对象"
            )
        title = section.get("title")
        items = section.get("items")
        if not isinstance(title, str) or not title.strip():
            raise FieldSchemaValidationError(
                f"profile_sections[{section_index}] 缺少 title"
            )
        if not isinstance(items, list):
            raise FieldSchemaValidationError(
                f"profile_sections[{section_index}].items 必须是数组"
            )
        section_values: dict[str, Any] = {}
        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                raise FieldSchemaValidationError(
                    f"profile_sections[{section_index}].items[{item_index}] "
                    "必须是对象"
                )
            label = item.get("label")
            if not isinstance(label, str) or not label.strip():
                raise FieldSchemaValidationError(
                    f"profile_sections[{section_index}].items[{item_index}] "
                    "缺少 label"
                )
            section_values[label.strip()] = sanitize_raw(item.get("value"))
        result[title.strip()] = section_values
    return result


def normalize_field_value(value: Any, normalizer: str) -> Any:
    """执行白名单内置转换器，不运行用户代码或任意表达式。"""

    if normalizer == "identity":
        return sanitize_raw(value)
    if normalizer == "trim_text":
        if not isinstance(value, str):
            raise FieldSchemaValidationError("trim_text 输入必须是字符串")
        return value.strip()
    if normalizer in {"number", "percentage"}:
        if isinstance(value, bool):
            raise FieldSchemaValidationError(f"{normalizer} 不接受布尔值")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise FieldSchemaValidationError(
                f"{normalizer} 输入必须是有限数值"
            ) from exc
        if not math.isfinite(number):
            raise FieldSchemaValidationError(
                f"{normalizer} 输入必须是有限数值"
            )
        if normalizer == "percentage":
            if 0 <= number <= 1:
                number *= 100
            if not 0 <= number <= 100:
                raise FieldSchemaValidationError("percentage 必须在 0–100 范围")
        return number
    if normalizer == "social_url":
        if isinstance(value, list):
            return [_normalize_social_url(str(item)) for item in value]
        if not isinstance(value, str):
            raise FieldSchemaValidationError(
                "social_url 输入必须是字符串或字符串数组"
            )
        return _normalize_social_url(value)
    if normalizer == "string_list":
        items = value if isinstance(value, list) else [value]
        normalized: list[str] = []
        for item in items:
            if not isinstance(item, (str, int, float, bool)):
                raise FieldSchemaValidationError(
                    "string_list 只接受标量或标量数组"
                )
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized
    if normalizer == "profile_sections":
        return _normalize_profile_sections(value)
    raise FieldSchemaValidationError(f"不支持的 normalizer: {normalizer}")


def _is_empty_value(value: Any, empty_rule: str) -> bool:
    """按字段空值规则判断空值，默认不把0和False当空。"""

    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    if empty_rule == "zero_is_empty" and value == 0 and not isinstance(value, bool):
        return True
    if empty_rule == "false_is_empty" and value is False:
        return True
    return False


def _apply_array_mode(value: Any, array_mode: str) -> Any:
    """应用保留、首项、收集或合并数组策略。"""

    if array_mode == "preserve":
        return value
    if array_mode == "first":
        if not isinstance(value, list):
            raise FieldSchemaValidationError("array_mode=first 的输入必须是数组")
        return value[0] if value else None
    if array_mode == "collect":
        return value if isinstance(value, list) else [value]
    if array_mode == "join":
        if not isinstance(value, list):
            raise FieldSchemaValidationError("array_mode=join 的输入必须是数组")
        if not all(isinstance(item, (str, int, float, bool)) for item in value):
            raise FieldSchemaValidationError("array_mode=join 只支持标量数组")
        return "\n".join(str(item) for item in value)
    raise FieldSchemaValidationError(f"不支持的 array_mode: {array_mode}")


def _validate_field_data_type(value: Any, data_type: str) -> Any:
    """校验规范化后的值类型，并返回可稳定 JSON 序列化的值。"""

    if value is None:
        return None
    if data_type in {"string", "url", "image"}:
        if not isinstance(value, str):
            raise FieldSchemaValidationError(f"{data_type} 字段必须是字符串")
        if value and data_type in {"url", "image"}:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise FieldSchemaValidationError(
                    f"{data_type} 字段必须是 http/https URL"
                )
        return value
    if data_type == "number":
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            raise FieldSchemaValidationError("number 字段必须是有限数值")
        return value
    if data_type == "boolean":
        if isinstance(value, bool):
            return value
        if value in {0, 1}:
            return bool(value)
        raise FieldSchemaValidationError("boolean 字段必须是布尔值或0/1")
    if data_type == "object":
        if not isinstance(value, dict):
            raise FieldSchemaValidationError("object 字段必须是对象")
        return value
    if data_type == "array":
        if not isinstance(value, list):
            raise FieldSchemaValidationError("array 字段必须是数组")
        return value
    raise FieldSchemaValidationError(f"不支持的 data_type: {data_type}")


def validate_field_definitions(
    definitions: Any,
) -> list[dict[str, Any]]:
    """校验字段配置 v2，并为旧版配置推导作用域与缺失策略。

    兼容规则:
        旧配置中 ``Task`` 模块归为 ``QUERY``，其余模块归为
        ``CANDIDATE``；系统标识字段缺失时报错，业务字段缺失记为空。
    """

    if not isinstance(definitions, list) or not definitions:
        raise FieldSchemaValidationError("字段配置必须是非空数组")
    required = {
        "field_key",
        "display_name",
        "module",
        "source_stage",
        "source_path",
        "data_type",
        "array_mode",
        "empty_rule",
        "normalizer",
        "scoring_role",
        "compare_mode",
        "enabled",
        "sort_order",
    }
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_keys: set[str] = set()
    for index, raw_definition in enumerate(definitions, start=1):
        label = f"第 {index} 个字段"
        if not isinstance(raw_definition, dict):
            errors.append(f"{label}必须是对象")
            continue
        missing = sorted(required - set(raw_definition))
        if missing:
            errors.append(f"{label}缺少配置项: {', '.join(missing)}")
            continue
        definition = {key: sanitize_raw(raw_definition[key]) for key in required}
        field_key = definition["field_key"]
        definition["value_scope"] = sanitize_raw(
            raw_definition.get(
                "value_scope",
                "QUERY" if definition["module"] == "Task" else "CANDIDATE",
            )
        )
        definition["missing_policy"] = sanitize_raw(
            raw_definition.get(
                "missing_policy",
                "ERROR"
                if field_key in {"task_id", "candidate_id"}
                else "EMPTY",
            )
        )
        if not isinstance(field_key, str) or not FIELD_KEY_PATTERN.fullmatch(
            field_key
        ):
            errors.append(f"{label} field_key 格式无效")
        elif field_key in seen_keys:
            errors.append(f"{label} field_key 重复: {field_key}")
        else:
            seen_keys.add(field_key)
        if (
            not isinstance(definition["display_name"], str)
            or not definition["display_name"].strip()
        ):
            errors.append(f"{label} display_name 不能为空")
        if (
            not isinstance(definition["module"], str)
            or definition["module"] not in FIELD_MODULES
        ):
            errors.append(f"{label} module 不受支持")
        if (
            not isinstance(definition["source_stage"], str)
            or definition["source_stage"] not in FIELD_SOURCE_STAGES
        ):
            errors.append(f"{label} source_stage 不受支持")
        if (
            not isinstance(definition["value_scope"], str)
            or definition["value_scope"] not in FIELD_VALUE_SCOPES
        ):
            errors.append(f"{label} value_scope 不受支持")
        if (
            not isinstance(definition["missing_policy"], str)
            or definition["missing_policy"] not in FIELD_MISSING_POLICIES
        ):
            errors.append(f"{label} missing_policy 不受支持")
        if (
            definition["value_scope"] == "QUERY"
            and definition["source_stage"] != "GetTask"
        ):
            errors.append(f"{label} QUERY 字段仅支持 GetTask")
        try:
            _source_path_tokens(definition["source_path"])
        except FieldSchemaValidationError as exc:
            errors.extend(f"{label} {item}" for item in exc.errors)
        if (
            not isinstance(definition["data_type"], str)
            or definition["data_type"] not in FIELD_DATA_TYPES
        ):
            errors.append(f"{label} data_type 不受支持")
        if (
            field_key == "candidate_confidence"
            and definition["data_type"] != "string"
        ):
            errors.append(f"{label} candidate_confidence 必须是 string")
        if (
            field_key
            in {
                "llm_cost",
                "third_party_cost",
                "total_cost",
                "search_duration_ms",
            }
            and definition["data_type"] != "number"
        ):
            errors.append(f"{label} 成本/耗时字段必须是 number")
        if field_key == "pdl_called" and definition["data_type"] != "boolean":
            errors.append(f"{label} pdl_called 必须是 boolean")
        if (
            not isinstance(definition["array_mode"], str)
            or definition["array_mode"] not in FIELD_ARRAY_MODES
        ):
            errors.append(f"{label} array_mode 不受支持")
        if (
            not isinstance(definition["empty_rule"], str)
            or definition["empty_rule"] not in FIELD_EMPTY_RULES
        ):
            errors.append(f"{label} empty_rule 不受支持")
        if (
            not isinstance(definition["normalizer"], str)
            or definition["normalizer"] not in FIELD_NORMALIZERS
        ):
            errors.append(f"{label} normalizer 不受支持")
        roles = definition["scoring_role"]
        if (
            not isinstance(roles, list)
            or not roles
            or any(
                not isinstance(role, str)
                or role not in FIELD_SCORING_ROLES
                for role in roles
            )
        ):
            errors.append(f"{label} scoring_role 必须是受支持的非空数组")
        if (
            not isinstance(definition["compare_mode"], str)
            or definition["compare_mode"] not in FIELD_COMPARE_MODES
        ):
            errors.append(f"{label} compare_mode 不受支持")
        if not isinstance(definition["enabled"], bool):
            errors.append(f"{label} enabled 必须是布尔值")
        if (
            not isinstance(definition["sort_order"], int)
            or isinstance(definition["sort_order"], bool)
        ):
            errors.append(f"{label} sort_order 必须是整数")
        definition["display_name"] = str(definition["display_name"]).strip()
        normalized.append(definition)
    if errors:
        raise FieldSchemaValidationError(errors)
    return sorted(normalized, key=lambda item: (item["sort_order"], item["field_key"]))


def json_text(value: Any) -> str:
    """将 JSON 兼容值序列化为稳定、紧凑的 UTF-8 文本。"""

    return json.dumps(
        sanitize_raw(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def read_jsonl(path: Path) -> tuple[list[Any], list[str]]:
    """读取 JSONL 并返回合法对象与可预览的行级错误。"""

    records: list[Any] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                errors.append(f"第 {line_number} 行 JSON 格式错误: {exc.msg}")
    return records, errors


def file_checksum(files: Iterable[tuple[str, Path]]) -> str:
    """按文件角色和内容计算稳定 SHA-256，支持多文件导入包去重。"""

    digest = hashlib.sha256()
    for role, path in files:
        digest.update(role.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def validate_storage_id(value: str, label: str) -> str:
    """校验会进入数据库主键和归档目录的外部 ID。"""

    if not SAFE_ID_PATTERN.fullmatch(value) or ".." in value:
        raise ValueError(
            f"{label} 只能包含字母、数字、点、下划线和连字符，且不能包含 '..'"
        )
    return value


def cell_value(value: Any) -> Any:
    """把 Excel 文本中的 JSON 或多行值恢复为可用 Python 值。"""

    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    if text[:1] in {"[", "{"}:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    if "\n" in text:
        return [item.strip() for item in text.splitlines() if item.strip()]
    return text


def normalize_available_fields(value: Any) -> list[str]:
    """校验并去重 Baseline 可用字段键。

    参数说明:
        value: 必须为字符串数组；允许显式空数组表示完整度未就绪。

    返回值:
        保持首次出现顺序的去重字段键数组。

    异常说明:
        ValueError: 输入不是数组、包含空字符串或非字符串。
    """

    if not isinstance(value, list):
        raise ValueError("baseline_available_fields 必须是字符串数组")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                "baseline_available_fields 不能包含空值或非字符串"
            )
        field_key = item.strip()
        if field_key not in normalized:
            normalized.append(field_key)
    return normalized


def normalize_evaluation_thresholds(value: Any) -> dict[str, dict[str, float | None]]:
    """校验并补齐 Evaluation 的分检索条件参考线。

    参数说明:
        value: 以 ``FULL_NAME``、``FULL_NAME_SOCIAL`` 为键的对象；每个
            阶段可以只提交部分阈值，空字符串和 ``None`` 均表示未配置。

    返回值:
        包含两个 Query Stage 和全部支持字段的稳定对象，数值统一为 float。

    异常说明:
        ReviewValidationError: 结构、字段名、数值类型或取值范围非法。
    """

    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ReviewValidationError("Evaluation 参考线必须是对象")
    unknown_stages = set(value) - SUPPORTED_QUERY_STAGES
    if unknown_stages:
        raise ReviewValidationError(
            "参考线包含不支持的 query_stage: "
            + ", ".join(sorted(unknown_stages))
        )
    normalized: dict[str, dict[str, float | None]] = {}
    errors: list[str] = []
    for query_stage in sorted(SUPPORTED_QUERY_STAGES):
        raw_stage = value.get(query_stage, {})
        if raw_stage is None:
            raw_stage = {}
        if not isinstance(raw_stage, dict):
            errors.append(f"{query_stage} 参考线必须是对象")
            raw_stage = {}
        unknown_fields = set(raw_stage) - set(EVALUATION_THRESHOLD_FIELDS)
        if unknown_fields:
            errors.append(
                f"{query_stage} 包含未知参考线: "
                + ", ".join(sorted(unknown_fields))
            )
        stage_values: dict[str, float | None] = {}
        for field_key, rule in EVALUATION_THRESHOLD_FIELDS.items():
            raw_value = raw_stage.get(field_key)
            if raw_value in (None, ""):
                stage_values[field_key] = None
                continue
            if isinstance(raw_value, bool):
                errors.append(f"{query_stage}.{field_key} 必须是数值")
                stage_values[field_key] = None
                continue
            try:
                number = float(raw_value)
            except (TypeError, ValueError):
                errors.append(f"{query_stage}.{field_key} 必须是数值")
                stage_values[field_key] = None
                continue
            if not math.isfinite(number):
                errors.append(f"{query_stage}.{field_key} 必须是有限数值")
            elif rule == "minimum_ratio" and not 0 <= number <= 1:
                errors.append(f"{query_stage}.{field_key} 必须在0到1之间")
            elif rule == "maximum_number" and number < 0:
                errors.append(f"{query_stage}.{field_key} 不能为负数")
            stage_values[field_key] = number
        normalized[query_stage] = stage_values
    if errors:
        raise ReviewValidationError(errors)
    return normalized


def _derived_available_fields(fields: dict[str, Any]) -> list[str]:
    """从旧 Baseline 非空值推导兼容字段键，不改变显式空数组语义。"""

    return [
        str(field_key)
        for field_key, value in fields.items()
        if not _is_empty_value(value, "default")
    ]


def _value_items(value: Any) -> list[Any]:
    """把单值或数组统一为可比较数组，空值返回空数组。"""

    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _stable_item(value: Any) -> str:
    """将集合比较项转换为稳定 JSON 文本，支持对象和标量。"""

    return json.dumps(
        sanitize_raw(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalized_text(value: Any) -> str:
    """用于准确率比较的轻量文本规范化，不改变原始处理结果。"""

    return " ".join(str(value).strip().casefold().split())


def _compare_field_values(
    baseline_value: Any,
    returned_value: Any,
    compare_mode: str,
) -> tuple[float | None, float | None, str]:
    """计算单字段建议完整度和准确率。

    返回值:
        ``(完整度, 准确率, 错误)``。基准缺失或 manual 模式返回 ``None``；
        返回为空时准确率分母为0，因此准确率保持 ``None``。
    """

    if _is_empty_value(baseline_value, "default"):
        return None, None, ""
    if compare_mode == "manual":
        return None, None, ""
    returned_empty = _is_empty_value(returned_value, "default")
    if returned_empty:
        return 0.0, None, ""
    try:
        if compare_mode == "normalized_text":
            matched = _normalized_text(baseline_value) == _normalized_text(
                returned_value
            )
            score = 1.0 if matched else 0.0
            return score, score, ""
        if compare_mode == "exact":
            matched = sanitize_raw(baseline_value) == sanitize_raw(returned_value)
            score = 1.0 if matched else 0.0
            return score, score, ""
        if compare_mode in {"set", "url_set"}:
            baseline_items = _value_items(baseline_value)
            returned_items = _value_items(returned_value)
            if compare_mode == "url_set":
                baseline_items = [
                    _normalize_social_url(str(item)) for item in baseline_items
                ]
                returned_items = [
                    _normalize_social_url(str(item)) for item in returned_items
                ]
            baseline_set = {_stable_item(item) for item in baseline_items}
            returned_set = {_stable_item(item) for item in returned_items}
            intersection_count = len(baseline_set & returned_set)
            completeness = (
                intersection_count / len(baseline_set)
                if baseline_set
                else None
            )
            accuracy = (
                intersection_count / len(returned_set)
                if returned_set
                else None
            )
            return completeness, accuracy, ""
    except (FieldSchemaValidationError, TypeError, ValueError) as exc:
        return None, None, str(exc)
    return None, None, f"不支持的 compare_mode: {compare_mode}"


def _social_platform(url: str) -> str:
    """从规范化 Social URL 提取平台，合并少量已知等价域名。"""

    hostname = (urlsplit(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    aliases = {
        "x.com": "twitter",
        "twitter.com": "twitter",
        "facebook.com": "facebook",
        "fb.com": "facebook",
        "instagram.com": "instagram",
        "linkedin.com": "linkedin",
        "tiktok.com": "tiktok",
        "youtube.com": "youtube",
        "youtu.be": "youtube",
    }
    return aliases.get(hostname, hostname)


def _candidate_social_suggestion(
    baseline_urls: Any,
    returned_urls: Any,
) -> tuple[str, str, str]:
    """按 PRD 的 Social Link 规则生成非最终候选人判定建议。"""

    try:
        baseline = {
            _normalize_social_url(str(item))
            for item in _value_items(baseline_urls)
            if str(item).strip()
        }
        returned = {
            _normalize_social_url(str(item))
            for item in _value_items(returned_urls)
            if str(item).strip()
        }
    except FieldSchemaValidationError as exc:
        return "PENDING_REVIEW", "NO_STRONG_FIELD", str(exc)
    if not baseline or not returned:
        return "SUSPECTED", "NO_STRONG_FIELD", "没有可用于判断的 Social Link"
    matched = sorted(baseline & returned)
    conflicts = sorted(
        returned_url
        for returned_url in returned
        if returned_url not in baseline
        and any(
            _social_platform(returned_url) == _social_platform(baseline_url)
            for baseline_url in baseline
        )
    )
    evidence = json_text(
        {
            "matched_social_urls": matched,
            "conflicting_social_urls": conflicts,
        }
    )
    if matched and conflicts:
        return "PENDING_REVIEW", "SOCIAL_CONFLICT", evidence
    if conflicts:
        return "NOT_HIT", "SOCIAL_CONFLICT", evidence
    if matched:
        return "HIT", "SOCIAL_MATCH", evidence
    return "NOT_HIT", "NO_STRONG_FIELD", evidence


def _suggested_field_scores(
    definitions: list[dict[str, Any]],
    fields: dict[str, Any],
    empty_fields: dict[str, bool],
    baseline_fields: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """生成可被人工覆盖的字段完整度和准确率建议。"""

    scores: dict[str, dict[str, Any]] = {}
    for definition in definitions:
        roles = definition["scoring_role"]
        if not definition["enabled"] or not (
            {"completeness", "accuracy"} & set(roles)
        ):
            continue
        field_key = definition["field_key"]
        baseline_available = (
            field_key in baseline_fields
            and not _is_empty_value(baseline_fields.get(field_key), "default")
        )
        returned_value = fields.get(field_key)
        returned_nonempty = not empty_fields.get(
            field_key,
            _is_empty_value(returned_value, "default"),
        )
        completeness, accuracy, comparison_error = _compare_field_values(
            baseline_fields.get(field_key),
            returned_value,
            definition["compare_mode"],
        )
        if "completeness" not in roles:
            completeness = None
        if "accuracy" not in roles:
            accuracy = None
        scores[field_key] = {
            "compare_mode": definition["compare_mode"],
            "baseline_available": baseline_available,
            "returned_nonempty": returned_nonempty,
            "suggested_completeness_score": completeness,
            "suggested_accuracy_score": accuracy,
            "completeness_score": completeness,
            "accuracy_score": accuracy,
            "manual_override": False,
            "review_note": "",
            "comparison_error": comparison_error,
        }
    return scores


class AnalysisService:
    """编排导入、Web 执行、字段处理、复核和指标计算。"""

    def __init__(
        self,
        store: AnalysisStore,
        data_dir: Path | str,
        *,
        import_dir: Path | str | None = None,
        raw_dir: Path | str | None = None,
        report_dir: Path | str | None = None,
    ) -> None:
        """绑定已初始化 Store 与受控数据目录。

        参数说明:
            store: 已初始化的 SQLite Store。
            data_dir: 所有数据库文件引用的共同根目录。
            import_dir: 可选上传归档目录，必须位于 data_dir 内。
            raw_dir: 可选标准化结果目录，必须位于 data_dir 内。
            report_dir: 可选报告目录；Web 可将其配置到 output/reports。

        异常说明:
            ValueError: import_dir 或 raw_dir 越出 data_dir。
        """

        self.store = store
        self.data_dir = Path(data_dir).resolve()
        self.import_dir = (
            Path(import_dir).resolve()
            if import_dir is not None
            else self.data_dir / "imports"
        )
        self.raw_dir = (
            Path(raw_dir).resolve()
            if raw_dir is not None
            else self.data_dir / "raw"
        )
        self.report_dir = (
            Path(report_dir).resolve()
            if report_dir is not None
            else self.data_dir / "reports"
        )
        for label, directory in (
            ("import_dir", self.import_dir),
            ("raw_dir", self.raw_dir),
        ):
            try:
                directory.relative_to(self.data_dir)
            except ValueError as exc:
                raise ValueError(f"{label} 必须位于 SEARCH_DATA_DIR 内") from exc
        # 单进程 Web 中串行保护“检查活动 Run → 创建 Run”，避免并发 POST 穿透。
        self._execution_lock = threading.Lock()

    def update_evaluation_thresholds(
        self,
        evaluation_id: str,
        thresholds: Any,
    ) -> dict[str, dict[str, float | None]]:
        """校验并保存 Evaluation 参考线。

        参数说明:
            evaluation_id: 已存在的 Evaluation 标识。
            thresholds: 分 Query Stage 的参考线对象，允许部分字段为空。

        返回值:
            已补齐并持久化的稳定阈值对象。

        异常说明:
            ReviewValidationError: Evaluation 不存在或阈值结构/范围非法。
        """

        normalized = normalize_evaluation_thresholds(thresholds)
        now = utc_now_text()
        with self.store.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE evaluations
                SET thresholds_json = ?, updated_at = ?
                WHERE evaluation_id = ?
                """,
                (json_text(normalized), now, evaluation_id),
            )
            if cursor.rowcount != 1:
                raise ReviewValidationError(
                    f"Evaluation 不存在: {evaluation_id}"
                )
        return normalized

    def _source_path(self, source: Path | str, suffixes: set[str]) -> Path:
        """解析并校验只读导入文件。"""

        path = Path(source).resolve()
        if not path.is_file():
            raise ImportValidationError([f"导入文件不存在: {path}"])
        if path.suffix.lower() not in suffixes:
            raise ImportValidationError(
                [f"不支持的文件类型: {path.suffix or '无后缀'}"]
            )
        return path

    def _archive_sources(
        self,
        object_id: str,
        sources: list[tuple[str, Path]],
    ) -> tuple[Path, list[str]]:
        """复制原文件到唯一归档目录，不覆盖任何既有归档。"""

        archive_dir = self.import_dir / object_id
        if archive_dir.exists():
            raise DuplicateImportError(f"归档目录已存在: {archive_dir}")
        archive_dir.mkdir(parents=True)
        archived_files: list[str] = []
        for role, source in sources:
            # 角色前缀避免同名文件冲突，同时保留原始文件名便于审计。
            target = archive_dir / f"{role}__{source.name}"
            shutil.copy2(source, target)
            archived_files.append(target.relative_to(self.data_dir).as_posix())
        return archive_dir, archived_files

    def _cleanup_created(self, *directories: Path) -> None:
        """仅清理由当前失败导入创建、且位于 data_dir 内的目录。"""

        for directory in directories:
            try:
                directory.resolve().relative_to(self.data_dir)
            except ValueError:
                continue
            if directory.exists():
                shutil.rmtree(directory)

    def _write_jsonl(self, path: Path, records: Iterable[dict[str, Any]]) -> None:
        """写入规范化脱敏 JSONL，供恢复和后续导入使用。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json_text(record))
                handle.write("\n")

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        """追加一条脱敏 JSONL，供后台执行逐 Query 持久化。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json_text(record))
            handle.write("\n")

    def ensure_default_field_schema(self) -> str:
        """幂等创建 v2 默认配置，仅替换系统自带的 v1 活跃配置。

        用户发布的活跃配置始终保留；只有当前仍使用系统默认 v1 时，新安装
        才把默认选择升级到 v2，旧配置记录不会删除。
        """

        existing = self.store.fetch_one(
            """
            SELECT schema_version FROM field_schemas
            WHERE schema_version = ?
            """,
            (DEFAULT_FIELD_SCHEMA_VERSION,),
        )
        if existing is not None:
            return existing["schema_version"]
        active = self.store.fetch_one(
            """
            SELECT schema_version, created_by FROM field_schemas
            WHERE is_active = 1 LIMIT 1
            """
        )
        activate_default = active is None or (
            active["schema_version"] == "field-schema-default-v1"
            and active["created_by"] == "system"
        )
        definitions = validate_field_definitions(DEFAULT_FIELD_DEFINITIONS)
        now = utc_now_text()
        try:
            with self.store.transaction() as connection:
                if activate_default and active is not None:
                    connection.execute(
                        "UPDATE field_schemas SET is_active = 0 WHERE is_active = 1"
                    )
                connection.execute(
                    """
                    INSERT INTO field_schemas(
                        schema_version, name, definitions_json, created_by,
                        created_at, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        DEFAULT_FIELD_SCHEMA_VERSION,
                        "默认字段配置",
                        json_text(definitions),
                        "system",
                        now,
                        int(activate_default),
                    ),
                )
        except sqlite3.IntegrityError:
            # 多线程同时初始化时，唯一主键保证只保留一份默认配置。
            existing = self.store.fetch_one(
                """
                SELECT schema_version FROM field_schemas
                WHERE schema_version = ?
                """,
                (DEFAULT_FIELD_SCHEMA_VERSION,),
            )
            if existing is None:
                raise
        return DEFAULT_FIELD_SCHEMA_VERSION

    def publish_field_schema(
        self,
        *,
        name: str,
        definitions: Any,
        created_by: str = "",
        schema_version: str | None = None,
        activate: bool = True,
    ) -> str:
        """校验并发布不可变字段配置新版本。

        参数说明:
            name: 配置版本的可读名称。
            definitions: 完整字段定义数组，不接受增量补丁。
            created_by: 单用户模式下可选的维护人文本。
            schema_version: 测试或迁移可指定；默认按时间和随机后缀生成。
            activate: 是否切换为新处理任务的默认版本。

        返回值:
            新生成的 schema_version。

        异常说明:
            FieldSchemaValidationError: 名称或任一字段配置不合法。
            sqlite3.IntegrityError: 指定版本已经存在；旧版本绝不更新。
        """

        if not isinstance(name, str) or not name.strip():
            raise FieldSchemaValidationError("字段配置名称不能为空")
        normalized = validate_field_definitions(definitions)
        generated_version = (
            schema_version
            or "field-schema-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-")
            + uuid.uuid4().hex[:6]
        )
        try:
            validate_storage_id(generated_version, "schema_version")
        except ValueError as exc:
            raise FieldSchemaValidationError(str(exc)) from exc
        now = utc_now_text()
        with self.store.transaction() as connection:
            if activate:
                connection.execute("UPDATE field_schemas SET is_active = 0")
            connection.execute(
                """
                INSERT INTO field_schemas(
                    schema_version, name, definitions_json, created_by,
                    created_at, is_active
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    generated_version,
                    name.strip(),
                    json_text(normalized),
                    created_by.strip() if isinstance(created_by, str) else "",
                    now,
                    int(activate),
                ),
            )
        return generated_version

    def _processing_source(self, candidate: sqlite3.Row) -> dict[str, Any]:
        """组合 Candidate Detail 与 List 字段为 Candidate 处理源。"""

        detail_data: dict[str, Any] = {}
        if candidate["detail_data_json"]:
            parsed_detail = json.loads(candidate["detail_data_json"])
            if not isinstance(parsed_detail, dict):
                raise FieldSchemaValidationError(
                    "Candidate detail_data_json 必须是对象"
                )
            detail_data = parsed_detail
        ui_sections: dict[str, Any] = {}
        if candidate["ui_sections_json"]:
            parsed_sections = json.loads(candidate["ui_sections_json"])
            if not isinstance(parsed_sections, dict):
                raise FieldSchemaValidationError(
                    "Candidate ui_sections_json 必须是对象"
                )
            ui_sections = parsed_sections
        source = dict(detail_data)
        if ui_sections or not isinstance(source.get("ui_sections"), dict):
            source["ui_sections"] = ui_sections
        source["candidate"] = {
            "candidate_id": candidate["candidate_id"],
            "candidate_rank": candidate["candidate_rank"],
            "rank_score": candidate["rank_score"],
            "detail_status": candidate["detail_status"],
            "list_item": (
                json.loads(candidate["list_item_json"])
                if candidate["list_item_json"]
                else {}
            ),
        }
        return sanitize_raw(source)

    def _process_field_values(
        self,
        source: dict[str, Any],
        definitions: list[dict[str, Any]],
        value_scope: str,
    ) -> tuple[dict[str, Any], dict[str, bool], list[dict[str, Any]]]:
        """处理指定作用域的字段，空路径与真实结构错误分别记录。"""

        fields: dict[str, Any] = {}
        empty_fields: dict[str, bool] = {}
        errors: list[dict[str, Any]] = []
        for definition in definitions:
            if (
                not definition["enabled"]
                or definition["value_scope"] != value_scope
            ):
                continue
            field_key = definition["field_key"]
            source_path = definition["source_path"]
            try:
                raw_value = extract_source_path(
                    source,
                    source_path,
                    missing_policy=definition["missing_policy"],
                )
                if raw_value is None:
                    # 数组型可选字段使用空数组，避免 collect 把空值变成 [null]。
                    array_value = (
                        []
                        if definition["data_type"] == "array"
                        else None
                    )
                else:
                    array_value = _apply_array_mode(
                        raw_value,
                        definition["array_mode"],
                    )
                normalized_value = (
                    None
                    if array_value is None
                    else normalize_field_value(
                        array_value,
                        definition["normalizer"],
                    )
                )
                normalized_value = _validate_field_data_type(
                    normalized_value,
                    definition["data_type"],
                )
                fields[field_key] = sanitize_raw(normalized_value)
                empty_fields[field_key] = _is_empty_value(
                    normalized_value,
                    definition["empty_rule"],
                )
            except FieldSchemaValidationError as exc:
                errors.append(
                    {
                        "code": "FIELD_PROCESSING_ERROR",
                        "field_key": field_key,
                        "source_path": source_path,
                        "error": str(exc),
                    }
                )
        return fields, empty_fields, errors

    @staticmethod
    def _get_task_response(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """从 Raw 包装或直接响应中提取 GetTask 的标准响应体与 data。"""

        response_body = payload.get("response_body", payload)
        if not isinstance(response_body, dict):
            return None
        responses = response_body.get("responses")
        if not isinstance(responses, list) or not responses:
            return None
        response = responses[0]
        if not isinstance(response, dict) or response.get("success") is False:
            return None
        data = response.get("data")
        if not isinstance(data, dict):
            return None
        return response_body, data

    def _query_processing_source(
        self,
        query: sqlite3.Row,
    ) -> dict[str, Any]:
        """使用最后一条成功 GetTask Raw 构造 Query 字段处理源。

        缺少 Raw 时保留数据库中的 Task 基础值；Raw JSON 本身损坏时抛出
        结构错误，由调用方记录为 Query 处理错误而不阻断 Candidate。
        """

        selected_body: dict[str, Any] = {}
        selected_data: dict[str, Any] = {}
        fallback: tuple[dict[str, Any], dict[str, Any]] | None = None
        rows = self.store.fetch_all(
            """
            SELECT payload_json FROM raw_records
            WHERE run_id = ? AND query_id = ? AND stage = 'GetTask'
            ORDER BY sequence_no, collected_at, raw_id
            """,
            (query["run_id"], query["query_id"]),
        )
        for row in rows:
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                raise FieldSchemaValidationError(
                    "GetTask Raw payload_json 必须是对象"
                )
            parsed = self._get_task_response(payload)
            if parsed is None:
                continue
            fallback = parsed
            if parsed[1].get("status") == "SUCCEEDED":
                selected_body, selected_data = parsed
        if not selected_data and fallback is not None:
            selected_body, selected_data = fallback

        public_fields: dict[str, Any] = {}
        if query["public_fields_json"]:
            parsed_public = json.loads(query["public_fields_json"])
            if not isinstance(parsed_public, dict):
                raise FieldSchemaValidationError(
                    "run_queries.public_fields_json 必须是对象"
                )
            public_fields = parsed_public
        task = {
            "task_id": query["task_id"],
            "llm_cost": query["llm_cost"],
            "third_party_cost": query["third_party_cost"],
            "total_cost": query["total_cost"],
            "pdl_called": query["pdl_called"],
            "search_duration_ms": query["search_duration_ms"],
        }
        task.update(public_fields)
        task.update(selected_data)
        if not task.get("task_id"):
            task["task_id"] = query["task_id"]
        result_status = (
            query["result_status"]
            or normalize_result_status(
                query["status"],
                query["candidate_count_listed"],
            )
        )
        return sanitize_raw(
            {
                "query": {
                    "query_id": query["query_id"],
                    "person_id": query["person_id"],
                    "query_stage": query["query_stage"],
                    "task_id": query["task_id"],
                    "result_status": result_status,
                },
                "task": task,
                "raw": selected_body,
            }
        )

    def _process_query_fields(
        self,
        query: sqlite3.Row,
        definitions: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, bool], list[dict[str, Any]]]:
        """处理单条 Query 公共字段，Raw 结构错误不影响其他 Query。"""

        try:
            source = self._query_processing_source(query)
        except (
            FieldSchemaValidationError,
            json.JSONDecodeError,
            TypeError,
        ) as exc:
            return (
                {},
                {},
                [
                    {
                        "code": "INVALID_TASK_DATA",
                        "field_key": "",
                        "source_path": "",
                        "error": str(exc),
                    }
                ],
            )
        return self._process_field_values(source, definitions, "QUERY")

    def _process_candidate_fields(
        self,
        candidate: sqlite3.Row,
        definitions: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, bool], list[dict[str, Any]]]:
        """处理单名候选人的字段，任一字段错误不影响其他字段。"""

        if candidate["detail_status"] != "SUCCESS":
            return (
                {},
                {},
                [
                    {
                        "code": "DETAIL_FAILED",
                        "field_key": "",
                        "source_path": "",
                        "error": candidate["detail_error"]
                        or "Candidate Detail 未成功",
                    }
                ],
            )
        try:
            source = self._processing_source(candidate)
        except (
            FieldSchemaValidationError,
            json.JSONDecodeError,
            TypeError,
        ) as exc:
            return (
                {},
                {},
                [
                    {
                        "code": "INVALID_DETAIL_DATA",
                        "field_key": "",
                        "source_path": "",
                        "error": str(exc),
                    }
                ],
            )
        return self._process_field_values(source, definitions, "CANDIDATE")

    def process_run(
        self,
        *,
        run_id: str,
        schema_version: str,
        baseline_version: str | None = None,
        process_id: str | None = None,
    ) -> ProcessResult:
        """使用字段配置快照处理一个 Run，并保留所有旧处理结果。

        功能说明:
            读取 Candidate Detail 和关联 Task/List 字段，逐候选人生成结构化
            值、空值标记和字段级错误；关联基准时同时生成候选人判定及字段
            得分建议。处理只新增版本数据，不更新 Candidate 或 Raw。

        参数说明:
            run_id: 已完成或已导入的 Run。
            schema_version: 已发布的不可变字段配置版本。
            baseline_version: 可选基准版本；为空时仍可处理但不能形成正式指标。
            process_id: 测试或迁移可指定的唯一处理标识。

        返回值:
            包含 process_id、候选人数、错误数和状态的摘要。

        异常说明:
            FieldSchemaValidationError: Run、配置或状态不允许处理。
            非预期处理异常会把 Process 标记 FAILED 并记录 PROCESS Failure。
        """

        run = self.store.fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if run is None:
            raise FieldSchemaValidationError(f"Run 不存在: {run_id}")
        if run["status"] in {"PENDING", "RUNNING"}:
            raise FieldSchemaValidationError(
                f"Run {run_id} 尚未结束，不能启动字段处理"
            )
        schema = self.store.fetch_one(
            "SELECT * FROM field_schemas WHERE schema_version = ?",
            (schema_version,),
        )
        if schema is None:
            raise FieldSchemaValidationError(
                f"字段配置不存在: {schema_version}"
            )
        baseline_version = (baseline_version or "").strip() or None
        if baseline_version is not None and self.store.fetch_one(
            """
            SELECT baseline_version FROM baseline_sets
            WHERE baseline_version = ?
            """,
            (baseline_version,),
        ) is None:
            raise FieldSchemaValidationError(
                f"基准版本不存在: {baseline_version}"
            )
        try:
            definitions = validate_field_definitions(
                json.loads(schema["definitions_json"])
            )
        except json.JSONDecodeError as exc:
            raise FieldSchemaValidationError(
                f"字段配置快照 JSON 已损坏: {schema_version}"
            ) from exc
        candidate_definitions = [
            definition
            for definition in definitions
            if definition["value_scope"] == "CANDIDATE"
        ]
        object_id = process_id or f"process_{uuid.uuid4().hex}"
        try:
            validate_storage_id(object_id, "process_id")
        except ValueError as exc:
            raise FieldSchemaValidationError(str(exc)) from exc
        now = utc_now_text()
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO process_runs(
                    process_id, run_id, schema_version, baseline_version,
                    rule_version, status, error_count, created_at
                ) VALUES (?, ?, ?, ?, ?, 'PROCESSING', 0, ?)
                """,
                (
                    object_id,
                    run_id,
                    schema_version,
                    baseline_version,
                    FIELD_PROCESSING_RULE_VERSION,
                    now,
                ),
            )

        queries = self.store.fetch_all(
            """
            SELECT * FROM run_queries
            WHERE run_id = ?
            ORDER BY query_id
            """,
            (run_id,),
        )
        candidates = self.store.fetch_all(
            """
            SELECT c.*, rq.person_id, rq.query_stage, rq.task_id
            FROM candidates AS c
            JOIN run_queries AS rq
              ON rq.run_id = c.run_id AND rq.query_id = c.query_id
            WHERE c.run_id = ?
            ORDER BY c.query_id, c.candidate_rank
            """,
            (run_id,),
        )
        baseline_people: dict[str, dict[str, Any]] = {}
        if baseline_version is not None:
            for row in self.store.fetch_all(
                """
                SELECT person_id, fields_json
                FROM baseline_people WHERE baseline_version = ?
                """,
                (baseline_version,),
            ):
                try:
                    value = json.loads(row["fields_json"])
                except (TypeError, json.JSONDecodeError):
                    value = {}
                baseline_people[row["person_id"]] = (
                    value if isinstance(value, dict) else {}
                )
        outputs: list[
            tuple[
                sqlite3.Row,
                dict[str, Any],
                dict[str, bool],
                list[dict[str, Any]],
            ]
        ] = []
        query_outputs: list[
            tuple[
                sqlite3.Row,
                dict[str, Any],
                dict[str, bool],
                list[dict[str, Any]],
            ]
        ] = []
        try:
            for query in queries:
                fields, empty_fields, errors = self._process_query_fields(
                    query,
                    definitions,
                )
                query_outputs.append(
                    (query, fields, empty_fields, errors)
                )
            for candidate in candidates:
                fields, empty_fields, errors = self._process_candidate_fields(
                    candidate,
                    definitions,
                )
                outputs.append(
                    (
                        candidate,
                        fields,
                        empty_fields,
                        errors,
                    )
                )
            error_count = sum(
                len(item[3]) for item in [*query_outputs, *outputs]
            )
            with self.store.transaction() as connection:
                for query, fields, empty_fields, errors in query_outputs:
                    result_status = (
                        query["result_status"]
                        or normalize_result_status(
                            query["status"],
                            query["candidate_count_listed"],
                        )
                    )
                    connection.execute(
                        """
                        INSERT INTO processed_queries(
                            process_id, run_id, query_id, result_status,
                            fields_json, empty_fields_json,
                            processing_errors_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            object_id,
                            run_id,
                            query["query_id"],
                            result_status,
                            json_text(fields),
                            json_text(empty_fields),
                            json_text(errors),
                        ),
                    )
                for candidate, fields, empty_fields, errors in outputs:
                    candidate_pk = candidate["candidate_pk"]
                    connection.execute(
                        """
                        INSERT INTO processed_candidates(
                            process_id, candidate_pk, fields_json,
                            empty_fields_json, processing_errors_json
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            object_id,
                            candidate_pk,
                            json_text(fields),
                            json_text(empty_fields),
                            json_text(errors),
                        ),
                    )
                    baseline_fields = baseline_people.get(
                        candidate["person_id"],
                        {},
                    )
                    field_scores = _suggested_field_scores(
                        candidate_definitions,
                        fields,
                        empty_fields,
                        baseline_fields,
                    )
                    baseline_identity_urls: list[Any] = []
                    returned_identity_urls: list[Any] = []
                    for definition in candidate_definitions:
                        if (
                            definition["enabled"]
                            and "identity" in definition["scoring_role"]
                            and definition["compare_mode"] == "url_set"
                        ):
                            baseline_identity_urls.extend(
                                _value_items(
                                    baseline_fields.get(definition["field_key"])
                                )
                            )
                            returned_identity_urls.extend(
                                _value_items(fields.get(definition["field_key"]))
                            )
                    if candidate["detail_status"] != "SUCCESS":
                        judgement, reason, evidence = (
                            "PENDING_REVIEW",
                            "NO_STRONG_FIELD",
                            candidate["detail_error"] or "Candidate Detail 未成功",
                        )
                    elif not baseline_fields:
                        judgement, reason, evidence = (
                            "PENDING_REVIEW",
                            "NO_STRONG_FIELD",
                            "缺少该人物的基准数据",
                        )
                    else:
                        judgement, reason, evidence = (
                            _candidate_social_suggestion(
                                baseline_identity_urls,
                                returned_identity_urls,
                            )
                        )
                    connection.execute(
                        """
                        INSERT INTO reviews(
                            process_id, candidate_pk, judgement, reason,
                            evidence, field_scores_json, reviewer,
                            review_note, reviewed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, NULL, '', NULL)
                        """,
                        (
                            object_id,
                            candidate_pk,
                            judgement,
                            reason,
                            evidence,
                            json_text(field_scores),
                        ),
                    )
                connection.execute(
                    """
                    UPDATE process_runs
                    SET status = 'COMPLETED', error_count = ?, finished_at = ?
                    WHERE process_id = ?
                    """,
                    (error_count, utc_now_text(), object_id),
                )
                # 同一 Run 重新处理会改变最新分析结果，旧 READY 报告需过期。
                connection.execute(
                    """
                    UPDATE reports
                    SET status = 'STALE'
                    WHERE status = 'READY'
                      AND (
                        candidate_process_id IN (
                            SELECT process_id FROM process_runs
                            WHERE run_id = ? AND process_id <> ?
                        )
                        OR baseline_process_id IN (
                            SELECT process_id FROM process_runs
                            WHERE run_id = ? AND process_id <> ?
                        )
                      )
                    """,
                    (run_id, object_id, run_id, object_id),
                )
        except Exception as exc:
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    UPDATE process_runs
                    SET status = 'FAILED', error_count = 1, finished_at = ?
                    WHERE process_id = ?
                    """,
                    (utc_now_text(), object_id),
                )
                connection.execute(
                    """
                    INSERT INTO failures(
                        failure_id, run_id, query_id, candidate_id,
                        scope, stage, error, created_at
                    ) VALUES (?, ?, NULL, '', 'PROCESS', 'FieldProcessing', ?, ?)
                    """,
                    (
                        f"failure_{uuid.uuid4().hex}",
                        run_id,
                        str(exc)[:2000],
                        utc_now_text(),
                    ),
                )
            raise
        return ProcessResult(
            process_id=object_id,
            candidate_count=len(candidates),
            error_count=error_count,
            status="COMPLETED",
        )

    def get_review_context(
        self,
        process_id: str,
        candidate_pk: str,
    ) -> dict[str, Any]:
        """读取候选人的处理结果、基准、建议得分和当前人工复核。

        参数说明:
            process_id: 不可变字段处理结果标识。
            candidate_pk: 候选人内部主键。

        返回值:
            页面和保存校验共用的复核上下文。

        异常说明:
            ReviewValidationError: Process/Candidate 不匹配或配置快照损坏。
        """

        row = self.store.fetch_one(
            """
            SELECT pc.fields_json, pc.empty_fields_json,
                   pc.processing_errors_json,
                   pr.run_id, pr.schema_version, pr.baseline_version,
                   pr.rule_version, pr.status AS process_status,
                   fs.definitions_json,
                   c.candidate_pk, c.candidate_id, c.candidate_rank,
                   c.detail_status, c.detail_error, c.query_id,
                   rq.person_id, rq.query_stage,
                   bp.display_name AS baseline_display_name,
                   bp.fields_json AS baseline_fields_json,
                   bp.evidence_json AS baseline_evidence_json,
                   rv.judgement AS review_judgement,
                   rv.reason AS review_reason,
                   rv.evidence AS review_evidence,
                   rv.field_scores_json, rv.reviewer, rv.review_note,
                   rv.reviewed_at
            FROM processed_candidates AS pc
            JOIN process_runs AS pr ON pr.process_id = pc.process_id
            JOIN field_schemas AS fs
              ON fs.schema_version = pr.schema_version
            JOIN candidates AS c ON c.candidate_pk = pc.candidate_pk
            JOIN run_queries AS rq
              ON rq.run_id = c.run_id AND rq.query_id = c.query_id
            LEFT JOIN baseline_people AS bp
              ON bp.baseline_version = pr.baseline_version
             AND bp.person_id = rq.person_id
            LEFT JOIN reviews AS rv
              ON rv.process_id = pc.process_id
             AND rv.candidate_pk = pc.candidate_pk
            WHERE pc.process_id = ? AND pc.candidate_pk = ?
            """,
            (process_id, candidate_pk),
        )
        if row is None:
            raise ReviewValidationError(
                f"处理结果 {process_id} 中不存在候选人 {candidate_pk}"
            )
        try:
            definitions = validate_field_definitions(
                json.loads(row["definitions_json"])
            )
            fields = json.loads(row["fields_json"])
            empty_fields = json.loads(row["empty_fields_json"])
            baseline_fields = (
                json.loads(row["baseline_fields_json"])
                if row["baseline_fields_json"]
                else {}
            )
        except (
            json.JSONDecodeError,
            FieldSchemaValidationError,
            TypeError,
        ) as exc:
            raise ReviewValidationError(
                f"复核依赖的数据快照已损坏: {exc}"
            ) from exc
        if not isinstance(fields, dict):
            fields = {}
        if not isinstance(empty_fields, dict):
            empty_fields = {}
        if not isinstance(baseline_fields, dict):
            baseline_fields = {}
        if row["field_scores_json"]:
            try:
                field_scores = json.loads(row["field_scores_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ReviewValidationError("字段复核得分快照已损坏") from exc
        else:
            field_scores = _suggested_field_scores(
                definitions,
                fields,
                empty_fields,
                baseline_fields,
            )
        if not isinstance(field_scores, dict):
            raise ReviewValidationError("字段复核得分快照必须是对象")
        return {
            "process_id": process_id,
            "run_id": row["run_id"],
            "candidate_pk": row["candidate_pk"],
            "candidate_id": row["candidate_id"],
            "candidate_rank": row["candidate_rank"],
            "query_id": row["query_id"],
            "person_id": row["person_id"],
            "query_stage": row["query_stage"],
            "detail_status": row["detail_status"],
            "detail_error": row["detail_error"],
            "schema_version": row["schema_version"],
            "baseline_version": row["baseline_version"],
            "baseline_display_name": row["baseline_display_name"],
            "baseline_fields": baseline_fields,
            "baseline_evidence": (
                json.loads(row["baseline_evidence_json"])
                if row["baseline_evidence_json"]
                else {}
            ),
            "fields": fields,
            "empty_fields": empty_fields,
            "definitions": {
                item["field_key"]: item for item in definitions
            },
            "field_scores": field_scores,
            "judgement": row["review_judgement"] or "PENDING_REVIEW",
            "reason": row["review_reason"] or "NO_STRONG_FIELD",
            "evidence": row["review_evidence"] or "",
            "reviewer": row["reviewer"] or "",
            "review_note": row["review_note"] or "",
            "reviewed_at": row["reviewed_at"],
            "review_exists": row["review_judgement"] is not None,
            "is_final": row["reviewed_at"] is not None,
        }

    def save_review(
        self,
        *,
        process_id: str,
        candidate_pk: str,
        judgement: str,
        reason: str,
        evidence: str = "",
        reviewer: str = "",
        review_note: str = "",
        field_scores: dict[str, Any] | None = None,
        expected_reviewed_at: str | None = None,
    ) -> dict[str, Any]:
        """事务保存人工最终判定与字段得分，并使关联报告过期。

        ``expected_reviewed_at`` 来自页面隐藏字段；数据库时间变化时拒绝覆盖，
        避免同一用户的多个浏览器标签互相覆盖。
        """

        context = self.get_review_context(process_id, candidate_pk)
        if judgement not in FINAL_JUDGEMENTS:
            raise ReviewValidationError(
                "最终判定只支持 HIT、NOT_HIT 或 SUSPECTED"
            )
        if reason not in REVIEW_REASONS:
            raise ReviewValidationError("复核原因不受支持")
        expected = expected_reviewed_at or ""
        current = context["reviewed_at"] or ""
        if expected != current:
            raise ReviewValidationError(
                "该复核已在其他页面更新，请刷新后重新提交"
            )
        proposed = field_scores if field_scores is not None else context["field_scores"]
        if not isinstance(proposed, dict):
            raise ReviewValidationError("字段得分必须是对象")
        current_scores = context["field_scores"]
        if set(proposed) - set(current_scores):
            raise ReviewValidationError("字段得分包含当前配置之外的字段")
        validated_scores: dict[str, dict[str, Any]] = {}
        overridden = False
        errors: list[str] = []
        for field_key, current_score in current_scores.items():
            raw_score = proposed.get(field_key, current_score)
            if not isinstance(raw_score, dict):
                errors.append(f"{field_key} 字段得分必须是对象")
                continue
            item = dict(current_score)
            for score_name in ("completeness_score", "accuracy_score"):
                value = raw_score.get(score_name)
                if value in (None, ""):
                    item[score_name] = None
                    continue
                if isinstance(value, bool):
                    errors.append(f"{field_key} {score_name} 必须在0到1之间")
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    errors.append(f"{field_key} {score_name} 必须在0到1之间")
                    continue
                if not math.isfinite(number) or not 0 <= number <= 1:
                    errors.append(f"{field_key} {score_name} 必须在0到1之间")
                    continue
                item[score_name] = number
            item["review_note"] = str(raw_score.get("review_note", "")).strip()
            item["manual_override"] = (
                item["completeness_score"]
                != item.get("suggested_completeness_score")
                or item["accuracy_score"]
                != item.get("suggested_accuracy_score")
            )
            overridden = overridden or item["manual_override"]
            validated_scores[field_key] = item
        if judgement == "HIT":
            for field_key, definition in context["definitions"].items():
                score = validated_scores.get(field_key)
                if score is None or not score.get("baseline_available"):
                    continue
                roles = definition["scoring_role"]
                if (
                    "completeness" in roles
                    and score.get("completeness_score") is None
                ):
                    errors.append(f"{field_key} 的完整度得分尚未确认")
                if (
                    "accuracy" in roles
                    and score.get("returned_nonempty")
                    and score.get("accuracy_score") is None
                ):
                    errors.append(f"{field_key} 的准确率得分尚未确认")
        if overridden and not review_note.strip():
            errors.append("人工覆盖建议得分时必须填写复核说明")
        if errors:
            raise ReviewValidationError(errors)
        reviewed_at = utc_now_text()
        with self.store.transaction() as connection:
            if context["review_exists"]:
                cursor = connection.execute(
                    """
                    UPDATE reviews
                    SET judgement = ?, reason = ?, evidence = ?,
                        field_scores_json = ?, reviewer = ?,
                        review_note = ?, reviewed_at = ?
                    WHERE process_id = ? AND candidate_pk = ?
                      AND COALESCE(reviewed_at, '') = ?
                    """,
                    (
                        judgement,
                        reason,
                        evidence.strip(),
                        json_text(validated_scores),
                        reviewer.strip() or None,
                        review_note.strip(),
                        reviewed_at,
                        process_id,
                        candidate_pk,
                        expected,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ReviewValidationError(
                        "该复核已在其他页面更新，请刷新后重新提交"
                    )
            else:
                try:
                    connection.execute(
                        """
                        INSERT INTO reviews(
                            process_id, candidate_pk, judgement, reason,
                            evidence, field_scores_json, reviewer,
                            review_note, reviewed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            process_id,
                            candidate_pk,
                            judgement,
                            reason,
                            evidence.strip(),
                            json_text(validated_scores),
                            reviewer.strip() or None,
                            review_note.strip(),
                            reviewed_at,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ReviewValidationError(
                        "该复核已在其他页面更新，请刷新后重新提交"
                    ) from exc
            connection.execute(
                """
                UPDATE reports SET status = 'STALE'
                WHERE status = 'READY'
                  AND (
                    baseline_process_id = ?
                    OR candidate_process_id = ?
                  )
                """,
                (process_id, process_id),
            )
        return {
            "process_id": process_id,
            "candidate_pk": candidate_pk,
            "judgement": judgement,
            "reviewed_at": reviewed_at,
        }

    def calculate_process_metrics(self, process_id: str) -> dict[str, Any]:
        """按 Process 固化的字段处理规则分派指标口径。

        历史 ``field-processing-v1`` 继续使用固定分母旧口径；当前
        ``field-processing-v2`` 使用人物 Baseline 可用字段和独立任务字段
        聚合。未知规则直接拒绝，避免历史结果被静默套用错误公式。
        """

        process = self.store.fetch_one(
            """
            SELECT rule_version FROM process_runs
            WHERE process_id = ?
            """,
            (process_id,),
        )
        if process is None:
            raise ReviewValidationError(f"处理结果不存在: {process_id}")
        if process["rule_version"] == LEGACY_FIELD_PROCESSING_RULE_VERSION:
            metrics = self._calculate_process_metrics_v1(process_id)
            metrics["metrics_rule_version"] = "metrics-v1"
            return metrics
        if process["rule_version"] == FIELD_PROCESSING_RULE_VERSION:
            return self._calculate_process_metrics_v2(process_id)
        raise ReviewValidationError(
            f"不支持的指标规则来源: {process['rule_version']}"
        )

    def _calculate_process_metrics_v1(self, process_id: str) -> dict[str, Any]:
        """按最终人工复核计算 Query 与 Run 核心指标。

        未完成复核或缺少基准时仍返回可下钻的预览分子、分母，但正式
        ``value`` 保持 ``None``，避免把系统建议或缺失数据当成正式结论。
        """

        process = self.store.fetch_one(
            """
            SELECT pr.*, r.evaluation_id, r.run_label, r.system_version,
                   fs.definitions_json
            FROM process_runs AS pr
            JOIN runs AS r ON r.run_id = pr.run_id
            JOIN field_schemas AS fs
              ON fs.schema_version = pr.schema_version
            WHERE pr.process_id = ?
            """,
            (process_id,),
        )
        if process is None:
            raise ReviewValidationError(f"处理结果不存在: {process_id}")
        try:
            definitions = validate_field_definitions(
                json.loads(process["definitions_json"])
            )
        except (json.JSONDecodeError, FieldSchemaValidationError) as exc:
            raise ReviewValidationError(f"字段配置快照已损坏: {exc}") from exc
        completeness_keys = {
            item["field_key"]
            for item in definitions
            if item["enabled"] and "completeness" in item["scoring_role"]
        }
        accuracy_keys = {
            item["field_key"]
            for item in definitions
            if item["enabled"] and "accuracy" in item["scoring_role"]
        }
        baseline_people = {
            row["person_id"]
            for row in self.store.fetch_all(
                """
                SELECT person_id FROM baseline_people
                WHERE baseline_version = ?
                """,
                (process["baseline_version"],),
            )
        } if process["baseline_version"] else set()
        queries = self.store.fetch_all(
            """
            SELECT * FROM run_queries
            WHERE run_id = ? ORDER BY query_id
            """,
            (process["run_id"],),
        )
        candidate_rows = self.store.fetch_all(
            """
            SELECT c.candidate_pk, c.query_id, c.candidate_id,
                   c.candidate_rank, c.detail_status,
                   pc.fields_json, pc.empty_fields_json,
                   rv.judgement, rv.field_scores_json, rv.reviewed_at
            FROM candidates AS c
            JOIN processed_candidates AS pc
              ON pc.candidate_pk = c.candidate_pk AND pc.process_id = ?
            LEFT JOIN reviews AS rv
              ON rv.process_id = pc.process_id
             AND rv.candidate_pk = pc.candidate_pk
            WHERE c.run_id = ?
            ORDER BY c.query_id, c.candidate_rank
            """,
            (process_id, process["run_id"]),
        )
        by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in candidate_rows:
            item = dict(row)
            for key, default in (
                ("fields_json", {}),
                ("empty_fields_json", {}),
                ("field_scores_json", {}),
            ):
                try:
                    parsed = json.loads(item[key]) if item[key] else default
                except (TypeError, json.JSONDecodeError):
                    parsed = default
                item[key.removesuffix("_json")] = (
                    parsed if isinstance(parsed, dict) else default
                )
            by_query[row["query_id"]].append(item)

        query_metrics: list[dict[str, Any]] = []
        nonmatched_values: list[float] = []
        for query in queries:
            successful_candidates = [
                item
                for item in by_query.get(query["query_id"], [])
                if item["detail_status"] == "SUCCESS"
            ]
            final_candidates = [
                item for item in successful_candidates if item["reviewed_at"]
            ]
            hit_candidates = [
                item
                for item in final_candidates
                if item["judgement"] == "HIT"
            ]
            hit_completeness: list[float] = []
            hit_accuracy: list[float] = []
            query_nonmatched_values: list[float] = []
            score_complete = True
            for candidate in hit_candidates:
                scores = candidate["field_scores"]
                completeness_scores = [
                    scores.get(field_key, {}).get("completeness_score")
                    for field_key in completeness_keys
                ]
                if any(value is None for value in completeness_scores):
                    score_complete = False
                else:
                    hit_completeness.append(
                        sum(float(value) for value in completeness_scores)
                        / CONTENT_FIELD_COUNT
                    )
                accuracy_scores = [
                    scores.get(field_key, {}).get("accuracy_score")
                    for field_key in accuracy_keys
                    if scores.get(field_key, {}).get("returned_nonempty")
                ]
                if any(value is None for value in accuracy_scores):
                    score_complete = False
                elif accuracy_scores:
                    hit_accuracy.append(
                        sum(float(value) for value in accuracy_scores)
                        / len(accuracy_scores)
                    )
            for candidate in final_candidates:
                if candidate["judgement"] not in {"NOT_HIT", "SUSPECTED"}:
                    continue
                empty_fields = candidate["empty_fields"]
                nonempty_count = sum(
                    1
                    for field_key in completeness_keys
                    if field_key in candidate["fields"]
                    and not empty_fields.get(field_key, True)
                )
                nonmatched_values.append(
                    nonempty_count / CONTENT_FIELD_COUNT
                )
                query_nonmatched_values.append(
                    nonempty_count / CONTENT_FIELD_COUNT
                )
            baseline_available = (
                bool(process["baseline_version"])
                and bool(query["person_id"])
                and query["person_id"] in baseline_people
            )
            review_complete = len(final_candidates) == len(successful_candidates)
            formal_ready = baseline_available and review_complete and score_complete
            query_metrics.append(
                {
                    "query_id": query["query_id"],
                    "person_id": query["person_id"],
                    "query_stage": query["query_stage"],
                    "retrieval_success": bool(hit_candidates),
                    "matched_completeness": (
                        sum(hit_completeness) / len(hit_completeness)
                        if hit_completeness
                        else None
                    ),
                    "matched_accuracy": (
                        sum(hit_accuracy) / len(hit_accuracy)
                        if hit_accuracy
                        else None
                    ),
                    "formal_ready": formal_ready,
                    "pending_review_count": (
                        len(successful_candidates) - len(final_candidates)
                    ),
                    "hit_candidate_ids": [
                        item["candidate_pk"] for item in hit_candidates
                    ],
                    "nonmatched_candidate_ids": [
                        item["candidate_pk"]
                        for item in final_candidates
                        if item["judgement"] in {"NOT_HIT", "SUSPECTED"}
                    ],
                    "nonmatched_completeness_values": query_nonmatched_values,
                    "candidate_ids": [
                        item["candidate_pk"] for item in successful_candidates
                    ],
                }
            )
        formal_ready = bool(query_metrics) and all(
            item["formal_ready"] for item in query_metrics
        )

        def aggregate(
            numerator: float,
            denominator: int,
        ) -> dict[str, Any]:
            """构造含正式值和预览值的统一指标对象。"""

            preview_value = (
                numerator / denominator if denominator else None
            )
            return {
                "numerator": numerator,
                "denominator": denominator,
                "value": preview_value if formal_ready else None,
                "preview_value": preview_value,
            }

        successful_queries = [
            item for item in query_metrics if item["retrieval_success"]
        ]
        matched_completeness_values = [
            item["matched_completeness"]
            for item in successful_queries
            if item["matched_completeness"] is not None
        ]
        matched_accuracy_values = [
            item["matched_accuracy"]
            for item in successful_queries
            if item["matched_accuracy"] is not None
        ]
        task_rows = self.store.fetch_all(
            """
            SELECT llm_cost, total_cost, pdl_called
            FROM run_queries WHERE run_id = ?
            """,
            (process["run_id"],),
        )
        cost_columns = ("llm_cost", "total_cost", "pdl_called")
        all_cost_missing = all(
            row[column] is None
            for row in task_rows
            for column in cost_columns
        )
        all_cost_complete = bool(task_rows) and all(
            row[column] is not None
            for row in task_rows
            for column in cost_columns
        )
        cost_status = {
            "status": (
                "NOT_CONNECTED"
                if all_cost_missing
                else "COMPLETE" if all_cost_complete else "PARTIAL"
            ),
            "task_count": len(task_rows),
            "missing_task_count": sum(
                1
                for row in task_rows
                if any(row[column] is None for column in cost_columns)
            ),
            "llm_cost_total": (
                sum(float(row["llm_cost"]) for row in task_rows)
                if all_cost_complete
                else None
            ),
            "total_cost_total": (
                sum(float(row["total_cost"]) for row in task_rows)
                if all_cost_complete
                else None
            ),
            "pdl_called_total": (
                sum(int(row["pdl_called"]) for row in task_rows)
                if all_cost_complete
                else None
            ),
        }
        return {
            "process_id": process_id,
            "run_id": process["run_id"],
            "evaluation_id": process["evaluation_id"],
            "schema_version": process["schema_version"],
            "baseline_version": process["baseline_version"],
            "rule_version": process["rule_version"],
            "formal_ready": formal_ready,
            "review_status": "REVIEWED" if formal_ready else "PENDING_REVIEW",
            "retrieval_success": aggregate(
                float(len(successful_queries)),
                len(query_metrics),
            ),
            "matched_completeness": aggregate(
                sum(matched_completeness_values),
                len(matched_completeness_values),
            ),
            "matched_accuracy": aggregate(
                sum(matched_accuracy_values),
                len(matched_accuracy_values),
            ),
            "nonmatched_completeness": aggregate(
                sum(nonmatched_values),
                len(nonmatched_values),
            ),
            "cost_status": cost_status,
            "query_metrics": query_metrics,
        }

    @staticmethod
    def _metrics_v2_value(
        numerator: float,
        denominator: int,
        *,
        ready: bool,
        not_ready_reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        """构造可追溯的 v2 指标值。

        参数说明:
            numerator: 已纳入计算的分子。
            denominator: 已纳入计算的分母。
            ready: 依赖的 Baseline、复核和字段得分是否完整。
            not_ready_reasons: 未就绪原因，供页面和 API 下钻。

        返回值:
            包含分子、分母、正式值、预览值和状态的字典。分母为0时正式
            值保持 ``None``，不会把“不适用”展示成0%。
        """

        preview_value = numerator / denominator if denominator else None
        status = (
            "NOT_READY"
            if not ready
            else "READY" if denominator else "NOT_APPLICABLE"
        )
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": preview_value if ready and denominator else None,
            "preview_value": preview_value,
            "status": status,
            "not_ready_reasons": sorted(set(not_ready_reasons or [])),
        }

    @staticmethod
    def _metrics_v2_result_status(
        query_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """按规范化 Query 结果状态计算有结果、无结果和执行失败比例。"""

        counts = {
            status: sum(row["result_status"] == status for row in query_rows)
            for status in RESULT_STATUSES
        }
        completed = (
            counts["HAS_CANDIDATES"] + counts["NO_CANDIDATES"]
        )
        total = len(query_rows)
        return {
            "total_formal_queries": total,
            "has_candidates_count": counts["HAS_CANDIDATES"],
            "no_candidates_count": counts["NO_CANDIDATES"],
            "execution_failed_count": counts["EXECUTION_FAILED"],
            "has_result_rate": (
                counts["HAS_CANDIDATES"] / completed if completed else None
            ),
            "no_result_rate": (
                counts["NO_CANDIDATES"] / completed if completed else None
            ),
            "execution_failed_rate": (
                counts["EXECUTION_FAILED"] / total if total else None
            ),
        }

    @staticmethod
    def _metrics_v2_numeric_aggregate(
        query_rows: list[dict[str, Any]],
        field_key: str,
    ) -> dict[str, Any]:
        """独立汇总一个成本或耗时字段，缺失和非法值都不按0补齐。

        负数、布尔值、非数字和非有限数值记为类型错误，不进入汇总；
        合法的0仍是有效值。
        """

        values: list[float] = []
        missing_query_ids: list[str] = []
        invalid_query_ids: list[str] = []
        for row in query_rows:
            value = row["task_fields"].get(field_key)
            if value is None or value == "":
                has_processing_error = any(
                    isinstance(error, dict)
                    and error.get("field_key") == field_key
                    for error in row.get("task_processing_errors", [])
                )
                (
                    invalid_query_ids
                    if has_processing_error
                    else missing_query_ids
                ).append(row["query_id"])
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                invalid_query_ids.append(row["query_id"])
                continue
            values.append(float(value))
        status = (
            "NOT_CONNECTED"
            if not values
            else "COMPLETE"
            if len(values) == len(query_rows)
            else "PARTIAL"
        )
        return {
            "status": status,
            "task_count": len(query_rows),
            "value_count": len(values),
            "missing_count": len(missing_query_ids),
            "invalid_count": len(invalid_query_ids),
            "total": sum(values) if values else None,
            "average": sum(values) / len(values) if values else None,
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
            "missing_query_ids": missing_query_ids,
            "invalid_query_ids": invalid_query_ids,
        }

    @staticmethod
    def _metrics_v2_pdl(
        query_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """统计 PDL 的 true、false、未知和只基于已知值的调用率。"""

        true_count = 0
        false_count = 0
        invalid_query_ids: list[str] = []
        unknown_query_ids: list[str] = []
        for row in query_rows:
            value = row["task_fields"].get("pdl_called")
            if value is True:
                true_count += 1
            elif value is False:
                false_count += 1
            else:
                unknown_query_ids.append(row["query_id"])
                has_processing_error = any(
                    isinstance(error, dict)
                    and error.get("field_key") == "pdl_called"
                    for error in row.get("task_processing_errors", [])
                )
                if value not in (None, "") or has_processing_error:
                    invalid_query_ids.append(row["query_id"])
        known_count = true_count + false_count
        return {
            "true_count": true_count,
            "false_count": false_count,
            "unknown_count": len(unknown_query_ids),
            "known_count": known_count,
            "call_rate": true_count / known_count if known_count else None,
            "unknown_query_ids": unknown_query_ids,
            "invalid_query_ids": invalid_query_ids,
        }

    @staticmethod
    def _metrics_v2_confidence(
        candidate_rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, int]]:
        """统计 Candidate Confidence，保留未知新枚举的原始字符串。"""

        def label(row: dict[str, Any]) -> str:
            value = row.get("confidence")
            return value.strip() if isinstance(value, str) and value.strip() else "UNKNOWN"

        def distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
            result: dict[str, int] = {}
            for row in rows:
                key = label(row)
                result[key] = result.get(key, 0) + 1
            return dict(sorted(result.items()))

        return {
            "overall": distribution(candidate_rows),
            "matched": distribution(
                [
                    row
                    for row in candidate_rows
                    if row["reviewed_at"] and row["judgement"] == "HIT"
                ]
            ),
            "nonmatched": distribution(
                [
                    row
                    for row in candidate_rows
                    if row["reviewed_at"]
                    and row["judgement"] in {"NOT_HIT", "SUSPECTED"}
                ]
            ),
        }

    def _metrics_v2_quality(
        self,
        query_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """从人物级明细聚合正式质量指标，并保留各自独立就绪状态。"""

        retrieval_reasons = [
            reason
            for row in query_rows
            for reason in row["retrieval_not_ready_reasons"]
        ]
        retrieval_ready = bool(query_rows) and not retrieval_reasons
        hit_rows = [row for row in query_rows if row["retrieval_success"]]
        completeness_reasons = [
            reason
            for row in hit_rows
            for reason in row["matched_completeness_not_ready_reasons"]
        ]
        accuracy_reasons = [
            reason
            for row in hit_rows
            for reason in row["matched_accuracy_not_ready_reasons"]
        ]
        completeness_values = [
            float(row["matched_completeness"])
            for row in hit_rows
            if row["matched_completeness"] is not None
        ]
        accuracy_values = [
            float(row["matched_accuracy"])
            for row in hit_rows
            if row["matched_accuracy"] is not None
        ]
        nonmatched_values = [
            float(value)
            for row in query_rows
            for value in row["nonmatched_completeness_values"]
        ]
        return {
            "formal_ready": retrieval_ready and not completeness_reasons and not accuracy_reasons,
            "retrieval_success": self._metrics_v2_value(
                float(sum(row["retrieval_success"] for row in query_rows)),
                len(query_rows),
                ready=retrieval_ready,
                not_ready_reasons=retrieval_reasons,
            ),
            "matched_completeness": self._metrics_v2_value(
                sum(completeness_values),
                len(hit_rows),
                ready=not completeness_reasons,
                not_ready_reasons=completeness_reasons,
            ),
            "matched_accuracy": self._metrics_v2_value(
                sum(accuracy_values),
                len(accuracy_values),
                ready=not accuracy_reasons,
                not_ready_reasons=accuracy_reasons,
            ),
            "nonmatched_completeness": self._metrics_v2_value(
                sum(nonmatched_values),
                len(nonmatched_values),
                ready=True,
            ),
        }

    def _calculate_process_metrics_v2(self, process_id: str) -> dict[str, Any]:
        """按 metrics-v2 计算结果、质量、任务字段、置信度和阶段分组。

        所有 Task 值来自 ``processed_queries`` 不可变快照；完整度分母来自
        每个人物的 ``baseline_available_fields``。依赖缺失时保留预览和
        原因，但正式值保持空。
        """

        process = self.store.fetch_one(
            """
            SELECT pr.*, r.evaluation_id, r.run_label, r.system_version,
                   r.evaluation_phase, fs.definitions_json
            FROM process_runs AS pr
            JOIN runs AS r ON r.run_id = pr.run_id
            JOIN field_schemas AS fs
              ON fs.schema_version = pr.schema_version
            WHERE pr.process_id = ?
            """,
            (process_id,),
        )
        if process is None:
            raise ReviewValidationError(f"处理结果不存在: {process_id}")
        try:
            definitions = validate_field_definitions(
                json.loads(process["definitions_json"])
            )
        except (json.JSONDecodeError, FieldSchemaValidationError) as exc:
            raise ReviewValidationError(f"字段配置快照已损坏: {exc}") from exc
        definitions_by_key = {
            item["field_key"]: item
            for item in definitions
            if item["enabled"] and item["value_scope"] == "CANDIDATE"
        }
        completeness_keys = {
            key
            for key, item in definitions_by_key.items()
            if "completeness" in item["scoring_role"]
        }
        accuracy_keys = {
            key
            for key, item in definitions_by_key.items()
            if "accuracy" in item["scoring_role"]
        }

        baseline_people: dict[str, dict[str, Any]] = {}
        if process["baseline_version"]:
            for row in self.store.fetch_all(
                """
                SELECT person_id, available_fields_json
                FROM baseline_people
                WHERE baseline_version = ?
                """,
                (process["baseline_version"],),
            ):
                try:
                    available_fields = json.loads(row["available_fields_json"])
                except (TypeError, json.JSONDecodeError):
                    available_fields = []
                baseline_people[row["person_id"]] = {
                    "available_fields": (
                        available_fields
                        if isinstance(available_fields, list)
                        else []
                    )
                }

        raw_queries = self.store.fetch_all(
            """
            SELECT rq.query_id, rq.person_id, rq.query_stage,
                   rq.candidate_count_listed, rq.detail_failure_count,
                   pq.result_status, pq.fields_json,
                   pq.empty_fields_json, pq.processing_errors_json
            FROM run_queries AS rq
            JOIN processed_queries AS pq
              ON pq.run_id = rq.run_id AND pq.query_id = rq.query_id
             AND pq.process_id = ?
            WHERE rq.run_id = ?
            ORDER BY rq.query_id
            """,
            (process_id, process["run_id"]),
        )
        query_rows: list[dict[str, Any]] = []
        for row in raw_queries:
            if row["result_status"] not in RESULT_STATUSES:
                raise ReviewValidationError(
                    f"Query {row['query_id']} 结果状态无效: {row['result_status']}"
                )
            item = dict(row)
            try:
                task_fields = json.loads(row["fields_json"])
            except (TypeError, json.JSONDecodeError):
                task_fields = {}
            item["task_fields"] = (
                task_fields if isinstance(task_fields, dict) else {}
            )
            try:
                task_processing_errors = json.loads(
                    row["processing_errors_json"]
                )
            except (TypeError, json.JSONDecodeError):
                task_processing_errors = []
            item["task_processing_errors"] = (
                task_processing_errors
                if isinstance(task_processing_errors, list)
                else []
            )
            query_rows.append(item)

        raw_candidates = self.store.fetch_all(
            """
            SELECT c.candidate_pk, c.query_id, c.candidate_id,
                   c.candidate_rank, c.detail_status,
                   pc.fields_json, pc.empty_fields_json,
                   rv.judgement, rv.field_scores_json, rv.reviewed_at
            FROM candidates AS c
            JOIN processed_candidates AS pc
              ON pc.candidate_pk = c.candidate_pk AND pc.process_id = ?
            LEFT JOIN reviews AS rv
              ON rv.process_id = pc.process_id
             AND rv.candidate_pk = pc.candidate_pk
            WHERE c.run_id = ?
            ORDER BY c.query_id, c.candidate_rank
            """,
            (process_id, process["run_id"]),
        )
        candidate_rows: list[dict[str, Any]] = []
        candidates_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in raw_candidates:
            item = dict(row)
            for source_name, target_name in (
                ("fields_json", "fields"),
                ("empty_fields_json", "empty_fields"),
                ("field_scores_json", "field_scores"),
            ):
                try:
                    value = (
                        json.loads(row[source_name])
                        if row[source_name]
                        else {}
                    )
                except (TypeError, json.JSONDecodeError):
                    value = {}
                item[target_name] = value if isinstance(value, dict) else {}
            confidence = item["fields"].get("candidate_confidence")
            if not isinstance(confidence, str) or not confidence.strip():
                confidence = item["fields"].get("summary_confidence_level")
            item["confidence"] = confidence
            candidate_rows.append(item)
            candidates_by_query[item["query_id"]].append(item)

        warnings: list[str] = []
        for query in query_rows:
            all_candidates = candidates_by_query.get(query["query_id"], [])
            successful_candidates = [
                item
                for item in all_candidates
                if item["detail_status"] == "SUCCESS"
            ]
            reviewed_candidates = [
                item for item in successful_candidates if item["reviewed_at"]
            ]
            hit_candidates = [
                item
                for item in reviewed_candidates
                if item["judgement"] == "HIT"
            ]
            selected_hit = hit_candidates[0] if hit_candidates else None
            baseline = baseline_people.get(query["person_id"])
            available_fields = (
                list(baseline["available_fields"]) if baseline else []
            )
            retrieval_reasons: list[str] = []
            if baseline is None:
                retrieval_reasons.append(
                    f"{query['query_id']}: 未关联该人物 Baseline"
                )
            if query["result_status"] == "HAS_CANDIDATES":
                pending_count = len(successful_candidates) - len(reviewed_candidates)
                if pending_count:
                    retrieval_reasons.append(
                        f"{query['query_id']}: {pending_count} 个候选人待复核"
                    )
                if not all_candidates:
                    retrieval_reasons.append(
                        f"{query['query_id']}: HAS_CANDIDATES 但没有候选人"
                    )
            else:
                pending_count = 0

            completeness_numerator = 0.0
            completeness_denominator = len(available_fields)
            completeness_missing: list[str] = []
            accuracy_numerator = 0.0
            accuracy_denominator = 0
            accuracy_missing: list[str] = []
            if selected_hit is not None:
                scores = selected_hit["field_scores"]
                for field_key in available_fields:
                    score = scores.get(field_key)
                    if field_key not in completeness_keys or not isinstance(score, dict):
                        completeness_missing.append(field_key)
                        continue
                    value = score.get("completeness_score")
                    if value is None:
                        completeness_missing.append(field_key)
                    else:
                        completeness_numerator += float(value)
                    if field_key not in accuracy_keys or not score.get(
                        "returned_nonempty"
                    ):
                        continue
                    accuracy_denominator += 1
                    accuracy_value = score.get("accuracy_score")
                    if accuracy_value is None:
                        accuracy_missing.append(field_key)
                    else:
                        accuracy_numerator += float(accuracy_value)
                if not available_fields:
                    completeness_missing.append("baseline_available_fields 为空")
                if completeness_missing:
                    warnings.append(
                        f"{query['query_id']}: 完整度字段未就绪 "
                        + ", ".join(completeness_missing)
                    )

            nonmatched_values: list[float] = []
            for candidate in reviewed_candidates:
                if candidate["judgement"] not in {"NOT_HIT", "SUSPECTED"}:
                    continue
                nonempty_count = sum(
                    field_key in candidate["fields"]
                    and not candidate["empty_fields"].get(field_key, True)
                    for field_key in completeness_keys
                )
                if completeness_keys:
                    nonmatched_values.append(
                        nonempty_count / len(completeness_keys)
                    )

            query.update(
                {
                    "candidate_count": len(all_candidates),
                    "successful_candidate_count": len(successful_candidates),
                    "pending_review_count": pending_count,
                    "retrieval_success": bool(selected_hit),
                    "retrieval_not_ready_reasons": retrieval_reasons,
                    "baseline_available_fields": available_fields,
                    "selected_hit_candidate_id": (
                        selected_hit["candidate_pk"] if selected_hit else None
                    ),
                    "matched_completeness_numerator": completeness_numerator,
                    "matched_completeness_denominator": completeness_denominator,
                    "matched_completeness": (
                        completeness_numerator / completeness_denominator
                        if selected_hit
                        and completeness_denominator
                        and not completeness_missing
                        else None
                    ),
                    "matched_completeness_not_ready_reasons": [
                        f"{query['query_id']}: {field_key}"
                        for field_key in completeness_missing
                    ],
                    "matched_accuracy_numerator": accuracy_numerator,
                    "matched_accuracy_denominator": accuracy_denominator,
                    "matched_accuracy": (
                        accuracy_numerator / accuracy_denominator
                        if selected_hit
                        and accuracy_denominator
                        and not accuracy_missing
                        else None
                    ),
                    "matched_accuracy_not_ready_reasons": [
                        f"{query['query_id']}: {field_key}"
                        for field_key in accuracy_missing
                    ],
                    "nonmatched_completeness_values": nonmatched_values,
                    "candidate_confidence": [
                        item["confidence"]
                        for item in all_candidates
                    ],
                    "formal_ready": (
                        not retrieval_reasons
                        and (
                            selected_hit is None
                            or (
                                not completeness_missing
                                and not accuracy_missing
                            )
                        )
                    ),
                    "hit_candidate_ids": [
                        item["candidate_pk"] for item in hit_candidates
                    ],
                    "nonmatched_candidate_ids": [
                        item["candidate_pk"]
                        for item in reviewed_candidates
                        if item["judgement"] in {"NOT_HIT", "SUSPECTED"}
                    ],
                    "candidate_ids": [
                        item["candidate_pk"] for item in successful_candidates
                    ],
                }
            )

        quality = self._metrics_v2_quality(query_rows)
        cost_metrics = {
            field_key: self._metrics_v2_numeric_aggregate(
                query_rows,
                field_key,
            )
            for field_key in (
                "llm_cost",
                "third_party_cost",
                "total_cost",
                "search_duration_ms",
            )
        }
        pdl_metrics = self._metrics_v2_pdl(query_rows)
        confidence_metrics = self._metrics_v2_confidence(candidate_rows)
        result_status_metrics = self._metrics_v2_result_status(query_rows)

        grouped_metrics: list[dict[str, Any]] = []
        for query_stage in sorted(
            {row["query_stage"] or "UNSPECIFIED" for row in query_rows}
        ):
            grouped_queries = [
                row
                for row in query_rows
                if (row["query_stage"] or "UNSPECIFIED") == query_stage
            ]
            grouped_query_ids = {
                row["query_id"] for row in grouped_queries
            }
            grouped_candidates = [
                row
                for row in candidate_rows
                if row["query_id"] in grouped_query_ids
            ]
            grouped_metrics.append(
                {
                    "evaluation_phase": process["evaluation_phase"],
                    "system_version": process["system_version"],
                    "query_stage": query_stage,
                    "query_count": len(grouped_queries),
                    "result_status_metrics": self._metrics_v2_result_status(
                        grouped_queries
                    ),
                    "quality_metrics": self._metrics_v2_quality(
                        grouped_queries
                    ),
                    "cost_metrics": {
                        field_key: self._metrics_v2_numeric_aggregate(
                            grouped_queries,
                            field_key,
                        )
                        for field_key in cost_metrics
                    },
                    "pdl_metrics": self._metrics_v2_pdl(grouped_queries),
                    "confidence_metrics": self._metrics_v2_confidence(
                        grouped_candidates
                    ),
                }
            )

        cost_status_values = [
            item["status"] for item in cost_metrics.values()
        ]
        cost_status = {
            "status": (
                "NOT_CONNECTED"
                if all(status == "NOT_CONNECTED" for status in cost_status_values)
                else "COMPLETE"
                if all(status == "COMPLETE" for status in cost_status_values)
                else "PARTIAL"
            ),
            "task_count": len(query_rows),
            "missing_task_count": sum(
                any(
                    row["task_fields"].get(field_key) in (None, "")
                    for field_key in cost_metrics
                )
                for row in query_rows
            ),
            "llm_cost_total": cost_metrics["llm_cost"]["total"],
            "total_cost_total": cost_metrics["total_cost"]["total"],
            "pdl_called_total": (
                pdl_metrics["true_count"]
                if pdl_metrics["known_count"]
                else None
            ),
        }
        module_metrics, field_metrics = self._process_field_report_metrics(
            process
        )
        return {
            "process_id": process_id,
            "run_id": process["run_id"],
            "evaluation_id": process["evaluation_id"],
            "evaluation_phase": process["evaluation_phase"],
            "system_version": process["system_version"],
            "schema_version": process["schema_version"],
            "baseline_version": process["baseline_version"],
            "rule_version": process["rule_version"],
            "metrics_rule_version": METRICS_RULE_VERSION,
            "formal_ready": quality["formal_ready"],
            "review_status": (
                "REVIEWED" if quality["formal_ready"] else "PENDING_REVIEW"
            ),
            "result_status_metrics": result_status_metrics,
            "quality_metrics": quality,
            "retrieval_success": quality["retrieval_success"],
            "matched_completeness": quality["matched_completeness"],
            "matched_accuracy": quality["matched_accuracy"],
            "nonmatched_completeness": quality[
                "nonmatched_completeness"
            ],
            "cost_metrics": cost_metrics,
            "pdl_metrics": pdl_metrics,
            "confidence_metrics": confidence_metrics,
            "grouped_metrics": grouped_metrics,
            "module_metrics": module_metrics,
            "field_metrics": field_metrics,
            "cost_status": cost_status,
            "query_metrics": query_rows,
            "warnings": sorted(set(warnings)),
        }

    def compare_processes(
        self,
        baseline_process_id: str,
        candidate_process_id: str,
    ) -> dict[str, Any]:
        """生成同条件、新增线索和不可比三类 Process 对比结果。

        正式同条件必须同时满足人物、Query Stage 和 Dataset 输入签名一致。
        缺少回归 Query、签名缺失或签名不一致不会再中断整份报告，而是进入
        ``not_comparable`` 并保留原因。
        """

        if baseline_process_id == candidate_process_id:
            raise ReviewValidationError("baseline 与 candidate 不能是同一 Process")
        processes = []
        for process_id in (baseline_process_id, candidate_process_id):
            row = self.store.fetch_one(
                """
                SELECT pr.*, r.evaluation_id, r.dataset_id,
                       fs.definitions_json
                FROM process_runs AS pr
                JOIN runs AS r ON r.run_id = pr.run_id
                JOIN field_schemas AS fs
                  ON fs.schema_version = pr.schema_version
                WHERE pr.process_id = ?
                """,
                (process_id,),
            )
            if row is None:
                raise ReviewValidationError(f"处理结果不存在: {process_id}")
            processes.append(row)
        baseline_process, candidate_process = processes
        compatibility_fields = (
            "evaluation_id",
            "baseline_version",
            "rule_version",
        )
        differences = [
            field
            for field in compatibility_fields
            if baseline_process[field] != candidate_process[field]
        ]
        if (
            baseline_process["schema_version"]
            != candidate_process["schema_version"]
        ):
            try:
                baseline_definitions = validate_field_definitions(
                    json.loads(baseline_process["definitions_json"])
                )
                candidate_definitions = validate_field_definitions(
                    json.loads(candidate_process["definitions_json"])
                )
            except (
                TypeError,
                json.JSONDecodeError,
                FieldSchemaValidationError,
            ) as exc:
                raise ReviewValidationError(
                    "字段配置快照损坏，无法判断对比兼容性"
                ) from exc
            if json_text(baseline_definitions) != json_text(
                candidate_definitions
            ):
                differences.append("schema_version")
        if differences:
            raise ReviewValidationError(
                "两个 Process 不兼容: " + ", ".join(differences)
            )

        baseline_metrics = self.calculate_process_metrics(
            baseline_process_id
        )
        candidate_metrics = self.calculate_process_metrics(
            candidate_process_id
        )
        metric_maps = {
            baseline_process_id: {
                row["query_id"]: row
                for row in baseline_metrics["query_metrics"]
            },
            candidate_process_id: {
                row["query_id"]: row
                for row in candidate_metrics["query_metrics"]
            },
        }

        def query_map(process: sqlite3.Row) -> dict[tuple[str, str], dict[str, Any]]:
            """读取 Query、稳定输入签名和人物级指标，并检查配对键唯一。"""

            input_signatures: dict[str, str] = {}
            if process["dataset_id"]:
                for input_row in self.store.fetch_all(
                    """
                    SELECT query_id, match_strategy, clues_json,
                           additional_details_json
                    FROM dataset_queries WHERE dataset_id = ?
                    """,
                    (process["dataset_id"],),
                ):
                    try:
                        input_signatures[input_row["query_id"]] = json_text(
                            {
                                "match_strategy": input_row["match_strategy"],
                                "clues": json.loads(input_row["clues_json"]),
                                "additional_details": json.loads(
                                    input_row["additional_details_json"]
                                ),
                            }
                        )
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise ReviewValidationError(
                            f"Dataset Query 输入快照已损坏: {input_row['query_id']}"
                        ) from exc
            rows = self.store.fetch_all(
                """
                SELECT rq.query_id, rq.person_id, rq.query_stage
                FROM run_queries AS rq
                WHERE rq.run_id = ?
                ORDER BY rq.query_id
                """,
                (process["run_id"],),
            )
            result: dict[tuple[str, str], dict[str, Any]] = {}
            for row in rows:
                if not row["person_id"] or not row["query_stage"]:
                    raise ReviewValidationError(
                        f"Process {process['process_id']} 缺少 person_id/query_stage"
                    )
                key = (row["person_id"], row["query_stage"])
                if key in result:
                    raise ReviewValidationError(
                        "同一 Process 中 person_id + query_stage 必须唯一"
                    )
                query_metrics = metric_maps[process["process_id"]].get(
                    row["query_id"],
                    {},
                )
                result[key] = {
                    "query_id": row["query_id"],
                    "has_hit": bool(
                        query_metrics.get("retrieval_success")
                    ),
                    "input_signature": input_signatures.get(row["query_id"]),
                    "metrics": query_metrics,
                }
            return result

        baseline_queries = query_map(baseline_process)
        candidate_queries = query_map(candidate_process)
        category_counts = {
            "持续命中": 0,
            "新增命中": 0,
            "退化未命中": 0,
            "持续未命中": 0,
        }
        pairs: list[dict[str, Any]] = []
        new_clue_queries: list[dict[str, Any]] = []
        not_comparable_queries: list[dict[str, Any]] = []

        def metric_value(
            query: dict[str, Any],
            field_key: str,
        ) -> Any:
            """从人物级指标读取可比较值，缺失保持 None。"""

            return query["metrics"].get(field_key)

        def primary_confidence(query: dict[str, Any]) -> str | None:
            """返回最高排名候选人的原始 Confidence，空值统一 UNKNOWN。"""

            values = query["metrics"].get("candidate_confidence", [])
            if not values:
                return None
            value = values[0]
            return (
                value.strip()
                if isinstance(value, str) and value.strip()
                else "UNKNOWN"
            )

        for person_id, query_stage in sorted(
            set(baseline_queries) | set(candidate_queries)
        ):
            key = (person_id, query_stage)
            baseline_query = baseline_queries.get(key)
            candidate_query = candidate_queries.get(key)
            if baseline_query is None:
                baseline_person_exists = any(
                    item_person_id == person_id
                    for item_person_id, _ in baseline_queries
                )
                if baseline_person_exists:
                    new_clue_queries.append(
                        {
                            "person_id": person_id,
                            "query_stage": query_stage,
                            "candidate_query_id": candidate_query["query_id"],
                            "result_status": candidate_query["metrics"].get(
                                "result_status"
                            ),
                            "retrieval_success": candidate_query[
                                "metrics"
                            ].get("retrieval_success"),
                            "matched_completeness": candidate_query[
                                "metrics"
                            ].get("matched_completeness"),
                            "matched_accuracy": candidate_query[
                                "metrics"
                            ].get("matched_accuracy"),
                            "candidate_confidence": primary_confidence(
                                candidate_query
                            ),
                            "candidate_count": candidate_query[
                                "metrics"
                            ].get("candidate_count", 0),
                            "task_fields": candidate_query["metrics"].get(
                                "task_fields",
                                {},
                            ),
                        }
                    )
                else:
                    not_comparable_queries.append(
                        {
                            "person_id": person_id,
                            "query_stage": query_stage,
                            "baseline_query_id": None,
                            "candidate_query_id": candidate_query["query_id"],
                            "reason": "CANDIDATE_PERSON_NOT_IN_BASELINE",
                        }
                    )
                continue
            if candidate_query is None:
                not_comparable_queries.append(
                    {
                        "person_id": person_id,
                        "query_stage": query_stage,
                        "baseline_query_id": baseline_query["query_id"],
                        "candidate_query_id": None,
                        "reason": "MISSING_REGRESSION_QUERY",
                    }
                )
                continue
            baseline_signature = baseline_query["input_signature"]
            candidate_signature = candidate_query["input_signature"]
            if baseline_signature is None or candidate_signature is None:
                not_comparable_queries.append(
                    {
                        "person_id": person_id,
                        "query_stage": query_stage,
                        "baseline_query_id": baseline_query["query_id"],
                        "candidate_query_id": candidate_query["query_id"],
                        "reason": "INPUT_SIGNATURE_UNAVAILABLE",
                    }
                )
                continue
            if baseline_signature != candidate_signature:
                not_comparable_queries.append(
                    {
                        "person_id": person_id,
                        "query_stage": query_stage,
                        "baseline_query_id": baseline_query["query_id"],
                        "candidate_query_id": candidate_query["query_id"],
                        "reason": "INPUT_SIGNATURE_MISMATCH",
                    }
                )
                continue
            baseline_hit = baseline_query["has_hit"]
            candidate_hit = candidate_query["has_hit"]
            if baseline_hit and candidate_hit:
                category = "持续命中"
            elif not baseline_hit and candidate_hit:
                category = "新增命中"
            elif baseline_hit and not candidate_hit:
                category = "退化未命中"
            else:
                category = "持续未命中"
            category_counts[category] += 1
            baseline_completeness = metric_value(
                baseline_query,
                "matched_completeness",
            )
            candidate_completeness = metric_value(
                candidate_query,
                "matched_completeness",
            )
            baseline_accuracy = metric_value(
                baseline_query,
                "matched_accuracy",
            )
            candidate_accuracy = metric_value(
                candidate_query,
                "matched_accuracy",
            )
            baseline_task = baseline_query["metrics"].get("task_fields", {})
            candidate_task = candidate_query["metrics"].get("task_fields", {})
            pairs.append(
                {
                    "person_id": person_id,
                    "query_stage": query_stage,
                    "baseline_query_id": baseline_query["query_id"],
                    "candidate_query_id": candidate_query["query_id"],
                    "baseline_hit": baseline_hit,
                    "candidate_hit": candidate_hit,
                    "category": category,
                    "baseline_matched_completeness": baseline_completeness,
                    "candidate_matched_completeness": candidate_completeness,
                    "matched_completeness_delta": (
                        candidate_completeness - baseline_completeness
                        if baseline_completeness is not None
                        and candidate_completeness is not None
                        else None
                    ),
                    "baseline_matched_accuracy": baseline_accuracy,
                    "candidate_matched_accuracy": candidate_accuracy,
                    "matched_accuracy_delta": (
                        candidate_accuracy - baseline_accuracy
                        if baseline_accuracy is not None
                        and candidate_accuracy is not None
                        else None
                    ),
                    "baseline_confidence": primary_confidence(
                        baseline_query
                    ),
                    "candidate_confidence": primary_confidence(
                        candidate_query
                    ),
                    "baseline_total_cost": baseline_task.get("total_cost"),
                    "candidate_total_cost": candidate_task.get("total_cost"),
                    "total_cost_delta": (
                        candidate_task["total_cost"]
                        - baseline_task["total_cost"]
                        if isinstance(
                            baseline_task.get("total_cost"),
                            (int, float),
                        )
                        and not isinstance(
                            baseline_task.get("total_cost"),
                            bool,
                        )
                        and isinstance(
                            candidate_task.get("total_cost"),
                            (int, float),
                        )
                        and not isinstance(
                            candidate_task.get("total_cost"),
                            bool,
                        )
                        else None
                    ),
                    "baseline_search_duration_ms": baseline_task.get(
                        "search_duration_ms"
                    ),
                    "candidate_search_duration_ms": candidate_task.get(
                        "search_duration_ms"
                    ),
                    "search_duration_ms_delta": (
                        candidate_task["search_duration_ms"]
                        - baseline_task["search_duration_ms"]
                        if isinstance(
                            baseline_task.get("search_duration_ms"),
                            (int, float),
                        )
                        and not isinstance(
                            baseline_task.get("search_duration_ms"),
                            bool,
                        )
                        and isinstance(
                            candidate_task.get("search_duration_ms"),
                            (int, float),
                        )
                        and not isinstance(
                            candidate_task.get("search_duration_ms"),
                            bool,
                        )
                        else None
                    ),
                    "baseline_pdl_called": baseline_task.get("pdl_called"),
                    "candidate_pdl_called": candidate_task.get("pdl_called"),
                    "baseline_candidate_count": baseline_query[
                        "metrics"
                    ].get("candidate_count", 0),
                    "candidate_candidate_count": candidate_query[
                        "metrics"
                    ].get("candidate_count", 0),
                    "formal_ready": (
                        bool(baseline_query["metrics"].get("formal_ready"))
                        and bool(
                            candidate_query["metrics"].get("formal_ready")
                        )
                    ),
                }
            )

        reason_counts: dict[str, int] = {}
        for item in not_comparable_queries:
            reason = item["reason"]
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        coverage = {
            "baseline_query_count": len(baseline_queries),
            "candidate_query_count": len(candidate_queries),
            "paired_count": len(pairs),
            "new_clue_count": len(new_clue_queries),
            "baseline_pairable_query_count": len(baseline_queries),
            "candidate_pairable_query_count": len(candidate_queries),
            "successful_pair_count": len(pairs),
            "candidate_new_condition_count": len(new_clue_queries),
            "missing_regression_query_count": reason_counts.get(
                "MISSING_REGRESSION_QUERY",
                0,
            ),
            "input_signature_mismatch_count": reason_counts.get(
                "INPUT_SIGNATURE_MISMATCH",
                0,
            ),
            "input_signature_unavailable_count": reason_counts.get(
                "INPUT_SIGNATURE_UNAVAILABLE",
                0,
            ),
            "not_comparable_count": len(not_comparable_queries),
        }
        same_condition_ready = bool(pairs) and all(
            item["formal_ready"] for item in pairs
        )
        blocking_not_comparable = bool(not_comparable_queries)

        new_clue_stage_metrics: dict[str, Any] = {}
        for query_stage in sorted(
            {item["query_stage"] for item in new_clue_queries}
        ):
            rows = [
                candidate_queries[
                    (item["person_id"], item["query_stage"])
                ]["metrics"]
                for item in new_clue_queries
                if item["query_stage"] == query_stage
            ]
            if (
                candidate_metrics.get("metrics_rule_version")
                == METRICS_RULE_VERSION
            ):
                new_clue_stage_metrics[query_stage] = {
                    "query_count": len(rows),
                    "result_status_metrics": self._metrics_v2_result_status(
                        rows
                    ),
                    "quality_metrics": self._metrics_v2_quality(rows),
                    "cost_metrics": {
                        field_key: self._metrics_v2_numeric_aggregate(
                            rows,
                            field_key,
                        )
                        for field_key in (
                            "llm_cost",
                            "third_party_cost",
                            "total_cost",
                            "search_duration_ms",
                        )
                    },
                    "pdl_metrics": self._metrics_v2_pdl(rows),
                }
            else:
                new_clue_stage_metrics[query_stage] = {
                    "query_count": len(rows),
                    "formal_ready": all(
                        row.get("formal_ready", False) for row in rows
                    ),
                }
        same_condition = {
            "formal_ready": same_condition_ready,
            "pairs": pairs,
            "coverage": coverage,
            "category_counts": category_counts,
        }
        new_clue = {
            "queries": new_clue_queries,
            "query_stage_metrics": new_clue_stage_metrics,
        }
        not_comparable = {
            "queries": not_comparable_queries,
            "reasons": reason_counts,
        }
        if reason_counts.get("INPUT_SIGNATURE_MISMATCH"):
            input_check_status = "MISMATCH"
        elif reason_counts.get("INPUT_SIGNATURE_UNAVAILABLE"):
            input_check_status = "UNAVAILABLE"
        elif not_comparable_queries:
            input_check_status = "PARTIAL"
        else:
            input_check_status = "VERIFIED"
        return {
            "baseline_process_id": baseline_process_id,
            "candidate_process_id": candidate_process_id,
            "formal_ready": (
                same_condition_ready
                and not blocking_not_comparable
            ),
            "input_check_status": input_check_status,
            "same_condition": same_condition,
            "new_clue": new_clue,
            "not_comparable": not_comparable,
            "coverage": coverage,
            # 兼容旧 ReportModel v1 页面和已存在的调用方。
            "category_counts": category_counts,
            "pairs": pairs,
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
        }

    def _report_process(self, process_id: str) -> sqlite3.Row:
        """读取生成报告所需的 Process、Run、Evaluation 和字段快照元数据。"""

        row = self.store.fetch_one(
            """
            SELECT pr.*, r.evaluation_id, r.dataset_id, r.run_label,
                   r.system_version, r.source_type, r.status AS run_status,
                   r.total_queries, r.success_queries, r.failed_queries,
                   r.started_at, r.finished_at, r.evaluation_phase,
                   e.name AS evaluation_name, e.notes AS evaluation_notes,
                   e.thresholds_json,
                   fs.name AS schema_name, fs.definitions_json
            FROM process_runs AS pr
            JOIN runs AS r ON r.run_id = pr.run_id
            JOIN evaluations AS e ON e.evaluation_id = r.evaluation_id
            JOIN field_schemas AS fs
              ON fs.schema_version = pr.schema_version
            WHERE pr.process_id = ?
            """,
            (process_id,),
        )
        if row is None:
            raise ReviewValidationError(f"处理结果不存在: {process_id}")
        if row["status"] != "COMPLETED":
            raise ReviewValidationError(
                f"处理结果尚未完成，不能生成报告: {process_id}"
            )
        return row

    @staticmethod
    def _report_metric(
        values: list[float],
        *,
        formal_ready: bool,
        numerator: float | None = None,
        denominator: int | None = None,
    ) -> dict[str, Any]:
        """构造报告内统一的分子、分母、正式值和预览值。"""

        actual_numerator = sum(values) if numerator is None else numerator
        actual_denominator = len(values) if denominator is None else denominator
        preview_value = (
            actual_numerator / actual_denominator
            if actual_denominator
            else None
        )
        return {
            "numerator": actual_numerator,
            "denominator": actual_denominator,
            "value": preview_value if formal_ready else None,
            "preview_value": preview_value,
        }

    def _query_stage_report_metrics(
        self,
        metrics: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """按 FULL_NAME/FULL_NAME_SOCIAL 聚合阶段5 Query 指标。"""

        result: dict[str, dict[str, Any]] = {}
        for query_stage in sorted(SUPPORTED_QUERY_STAGES):
            rows = [
                row
                for row in metrics["query_metrics"]
                if row["query_stage"] == query_stage
            ]
            if not rows:
                continue
            formal_ready = all(row["formal_ready"] for row in rows)
            successful = [
                row for row in rows if row["retrieval_success"]
            ]
            completeness = [
                float(row["matched_completeness"])
                for row in successful
                if row["matched_completeness"] is not None
            ]
            accuracy = [
                float(row["matched_accuracy"])
                for row in successful
                if row["matched_accuracy"] is not None
            ]
            nonmatched = [
                float(value)
                for row in rows
                for value in row["nonmatched_completeness_values"]
            ]
            result[query_stage] = {
                "formal_ready": formal_ready,
                "query_count": len(rows),
                "retrieval_success": self._report_metric(
                    [],
                    formal_ready=formal_ready,
                    numerator=float(len(successful)),
                    denominator=len(rows),
                ),
                "matched_completeness": self._report_metric(
                    completeness,
                    formal_ready=formal_ready,
                ),
                "matched_accuracy": self._report_metric(
                    accuracy,
                    formal_ready=formal_ready,
                ),
                "nonmatched_completeness": self._report_metric(
                    nonmatched,
                    formal_ready=formal_ready,
                ),
                "query_ids": [row["query_id"] for row in rows],
            }
        return result

    def _process_field_report_metrics(
        self,
        process: sqlite3.Row,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """计算模块返回率和字段级返回率/复核得分。"""

        try:
            definitions = validate_field_definitions(
                json.loads(process["definitions_json"])
            )
        except (json.JSONDecodeError, FieldSchemaValidationError) as exc:
            raise ReviewValidationError(
                f"字段配置快照已损坏: {process['schema_version']}"
            ) from exc
        rows = self.store.fetch_all(
            """
            SELECT c.candidate_pk, c.detail_status,
                   pc.fields_json, pc.empty_fields_json,
                   rv.judgement, rv.field_scores_json, rv.reviewed_at
            FROM processed_candidates AS pc
            JOIN candidates AS c ON c.candidate_pk = pc.candidate_pk
            LEFT JOIN reviews AS rv
              ON rv.process_id = pc.process_id
             AND rv.candidate_pk = pc.candidate_pk
            WHERE pc.process_id = ?
            """,
            (process["process_id"],),
        )
        parsed_rows = []
        for row in rows:
            item = dict(row)
            for source_name, target_name in (
                ("fields_json", "fields"),
                ("empty_fields_json", "empty_fields"),
                ("field_scores_json", "field_scores"),
            ):
                try:
                    value = (
                        json.loads(row[source_name])
                        if row[source_name]
                        else {}
                    )
                except (TypeError, json.JSONDecodeError):
                    value = {}
                item[target_name] = value if isinstance(value, dict) else {}
            parsed_rows.append(item)
        successful = [
            row for row in parsed_rows if row["detail_status"] == "SUCCESS"
        ]
        hit_rows = [
            row
            for row in successful
            if row["reviewed_at"] and row["judgement"] == "HIT"
        ]
        nonmatched_rows = [
            row
            for row in successful
            if row["reviewed_at"]
            and row["judgement"] in {"NOT_HIT", "SUSPECTED"}
        ]
        field_metrics: dict[str, Any] = {}
        module_candidates: dict[str, set[str]] = defaultdict(set)
        module_hit_candidates: dict[str, set[str]] = defaultdict(set)
        module_nonmatched_candidates: dict[str, set[str]] = defaultdict(set)
        for definition in definitions:
            if not definition["enabled"]:
                continue
            field_key = definition["field_key"]
            returned_candidates = [
                row
                for row in successful
                if field_key in row["fields"]
                and not row["empty_fields"].get(field_key, True)
            ]
            for row in returned_candidates:
                module_candidates[definition["module"]].add(
                    row["candidate_pk"]
                )
            returned_hit_rows = [
                row
                for row in hit_rows
                if field_key in row["fields"]
                and not row["empty_fields"].get(field_key, True)
            ]
            returned_nonmatched_rows = [
                row
                for row in nonmatched_rows
                if field_key in row["fields"]
                and not row["empty_fields"].get(field_key, True)
            ]
            for row in returned_hit_rows:
                module_hit_candidates[definition["module"]].add(
                    row["candidate_pk"]
                )
            for row in returned_nonmatched_rows:
                module_nonmatched_candidates[definition["module"]].add(
                    row["candidate_pk"]
                )
            completeness_values = [
                float(row["field_scores"][field_key]["completeness_score"])
                for row in hit_rows
                if field_key in row["field_scores"]
                and row["field_scores"][field_key].get(
                    "completeness_score"
                )
                is not None
            ]
            accuracy_values = [
                float(row["field_scores"][field_key]["accuracy_score"])
                for row in hit_rows
                if field_key in row["field_scores"]
                and row["field_scores"][field_key].get("returned_nonempty")
                and row["field_scores"][field_key].get("accuracy_score")
                is not None
            ]
            field_metrics[field_key] = {
                "field_key": field_key,
                "display_name": definition["display_name"],
                "module": definition["module"],
                "scoring_role": definition["scoring_role"],
                "compare_mode": definition["compare_mode"],
                "returned_count": len(returned_candidates),
                "empty_count": len(successful) - len(returned_candidates),
                "candidate_count": len(successful),
                "return_rate": (
                    len(returned_candidates) / len(successful)
                    if successful
                    else None
                ),
                "hit_returned_count": len(returned_hit_rows),
                "hit_candidate_count": len(hit_rows),
                "hit_return_rate": (
                    len(returned_hit_rows) / len(hit_rows)
                    if hit_rows
                    else None
                ),
                "nonmatched_returned_count": len(
                    returned_nonmatched_rows
                ),
                "nonmatched_candidate_count": len(nonmatched_rows),
                "nonmatched_nonempty_rate": (
                    len(returned_nonmatched_rows) / len(nonmatched_rows)
                    if nonmatched_rows
                    else None
                ),
                "hit_completeness": (
                    sum(completeness_values) / len(completeness_values)
                    if completeness_values
                    else None
                ),
                "hit_accuracy": (
                    sum(accuracy_values) / len(accuracy_values)
                    if accuracy_values
                    else None
                ),
            }
        module_metrics = {
            module: {
                "module": module,
                "returned_candidate_count": len(candidate_ids),
                "candidate_count": len(successful),
                "hit_returned_candidate_count": len(
                    module_hit_candidates[module]
                ),
                "hit_candidate_count": len(hit_rows),
                "nonmatched_returned_candidate_count": len(
                    module_nonmatched_candidates[module]
                ),
                "nonmatched_candidate_count": len(nonmatched_rows),
                "return_rate": (
                    len(candidate_ids) / len(successful)
                    if successful
                    else None
                ),
                "hit_return_rate": (
                    len(module_hit_candidates[module]) / len(hit_rows)
                    if hit_rows
                    else None
                ),
                "nonmatched_return_rate": (
                    len(module_nonmatched_candidates[module])
                    / len(nonmatched_rows)
                    if nonmatched_rows
                    else None
                ),
            }
            for module, candidate_ids in sorted(module_candidates.items())
        }
        for module in sorted(
            {
                definition["module"]
                for definition in definitions
                if definition["enabled"]
            }
        ):
            module_metrics.setdefault(
                module,
                {
                    "module": module,
                    "returned_candidate_count": 0,
                    "candidate_count": len(successful),
                    "hit_returned_candidate_count": 0,
                    "hit_candidate_count": len(hit_rows),
                    "nonmatched_returned_candidate_count": 0,
                    "nonmatched_candidate_count": len(nonmatched_rows),
                    "return_rate": 0.0 if successful else None,
                    "hit_return_rate": 0.0 if hit_rows else None,
                    "nonmatched_return_rate": (
                        0.0 if nonmatched_rows else None
                    ),
                },
            )
        return module_metrics, field_metrics

    def _report_candidate_lookup(
        self,
        process_id: str,
    ) -> dict[str, dict[str, Any]]:
        """按 query_id 返回报告配对案例使用的首名候选人。"""

        rows = self.store.fetch_all(
            """
            SELECT c.query_id, c.candidate_pk, c.candidate_id,
                   c.candidate_rank, rv.judgement, rv.reviewed_at
            FROM processed_candidates AS pc
            JOIN candidates AS c ON c.candidate_pk = pc.candidate_pk
            LEFT JOIN reviews AS rv
              ON rv.process_id = pc.process_id
             AND rv.candidate_pk = pc.candidate_pk
            WHERE pc.process_id = ?
            ORDER BY c.query_id, c.candidate_rank
            """,
            (process_id,),
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            result.setdefault(row["query_id"], dict(row))
        return result

    def _report_case_groups(
        self,
        process: sqlite3.Row,
        comparison: dict[str, Any] | None,
    ) -> dict[str, list[dict[str, Any]]]:
        """构造可从报告下钻到 Query/Candidate 的人物级案例。"""

        rows = self.store.fetch_all(
            """
            SELECT c.candidate_pk, c.candidate_id, c.candidate_rank,
                   c.query_id, c.detail_status, c.detail_error,
                   rq.person_id, rq.query_stage, rq.status AS query_status,
                   rv.judgement, rv.reason, rv.reviewed_at,
                   pc.processing_errors_json
            FROM processed_candidates AS pc
            JOIN candidates AS c ON c.candidate_pk = pc.candidate_pk
            JOIN run_queries AS rq
              ON rq.run_id = c.run_id AND rq.query_id = c.query_id
            LEFT JOIN reviews AS rv
              ON rv.process_id = pc.process_id
             AND rv.candidate_pk = pc.candidate_pk
            WHERE pc.process_id = ?
            ORDER BY c.query_id, c.candidate_rank
            """,
            (process["process_id"],),
        )
        groups: dict[str, list[dict[str, Any]]] = {
            "命中": [],
            "疑似": [],
            "待复核": [],
            "详情失败": [],
            "处理异常": [],
            "改善最明显": [],
            "持续命中": [],
            "新增命中": [],
            "退化未命中": [],
            "持续未命中": [],
            "新增线索": [],
            "不可比": [],
        }
        for row in rows:
            item = dict(row)
            try:
                processing_errors = json.loads(
                    row["processing_errors_json"]
                )
            except (TypeError, json.JSONDecodeError):
                processing_errors = []
            item["processing_error_count"] = (
                len(processing_errors)
                if isinstance(processing_errors, list)
                else 0
            )
            item.pop("processing_errors_json", None)
            if row["detail_status"] == "FAILED":
                groups["详情失败"].append(item)
            if item["processing_error_count"]:
                groups["处理异常"].append(item)
            if not row["reviewed_at"]:
                groups["待复核"].append(item)
            elif row["judgement"] == "HIT":
                groups["命中"].append(item)
            elif row["judgement"] == "SUSPECTED":
                groups["疑似"].append(item)
        if comparison is not None:
            baseline_lookup = self._report_candidate_lookup(
                comparison["baseline_process_id"]
            )
            candidate_lookup = self._report_candidate_lookup(
                comparison["candidate_process_id"]
            )
            for pair in comparison["pairs"]:
                baseline_candidate = baseline_lookup.get(
                    pair["baseline_query_id"],
                    {},
                )
                candidate_candidate = candidate_lookup.get(
                    pair["candidate_query_id"],
                    {},
                )
                enriched = {
                    **pair,
                    "baseline_candidate_pk": baseline_candidate.get(
                        "candidate_pk"
                    ),
                    "baseline_candidate_id": baseline_candidate.get(
                        "candidate_id"
                    ),
                    "candidate_candidate_pk": candidate_candidate.get(
                        "candidate_pk"
                    ),
                    "candidate_candidate_id": candidate_candidate.get(
                        "candidate_id"
                    ),
                }
                groups[pair["category"]].append(enriched)
            for item in comparison["new_clue"]["queries"]:
                candidate_candidate = candidate_lookup.get(
                    item["candidate_query_id"],
                    {},
                )
                groups["新增线索"].append(
                    {
                        **item,
                        "candidate_candidate_pk": candidate_candidate.get(
                            "candidate_pk"
                        ),
                        "candidate_candidate_id": candidate_candidate.get(
                            "candidate_id"
                        ),
                        "category": "新增线索",
                    }
                )
            groups["不可比"].extend(
                comparison["not_comparable"]["queries"]
            )
            comparable_cases = [
                item
                for category in (
                    "持续命中",
                    "新增命中",
                    "退化未命中",
                    "持续未命中",
                )
                for item in groups[category]
            ]
            improved_cases = [
                item
                for item in comparable_cases
                if item["category"] == "新增命中"
                or (item.get("matched_completeness_delta") or 0) > 0
                or (item.get("matched_accuracy_delta") or 0) > 0
            ]
            improved_cases.sort(
                key=lambda item: (
                    item["category"] == "新增命中",
                    item.get("matched_completeness_delta") is not None,
                    item.get("matched_completeness_delta") or 0,
                    item.get("matched_accuracy_delta") is not None,
                    item.get("matched_accuracy_delta") or 0,
                ),
                reverse=True,
            )
            groups["改善最明显"] = improved_cases[:5]
            groups["新增命中"].sort(
                key=lambda item: (
                    item.get("matched_completeness_delta") is not None,
                    item.get("matched_completeness_delta") or 0,
                    item.get("matched_accuracy_delta") is not None,
                    item.get("matched_accuracy_delta") or 0,
                ),
                reverse=True,
            )
            groups["持续未命中"].sort(
                key=lambda item: (
                    item.get("candidate_candidate_count", 0),
                    str(item.get("candidate_confidence") or ""),
                ),
                reverse=True,
            )
        return groups

    @staticmethod
    def _merge_comparison_metrics(
        baseline: dict[str, Any],
        candidate: dict[str, Any],
    ) -> dict[str, Any]:
        """合并 baseline/candidate 模块或字段指标并计算可用差值。"""

        merged: dict[str, Any] = {}
        for key in sorted(set(baseline) | set(candidate)):
            baseline_item = baseline.get(key, {})
            candidate_item = candidate.get(key, {})
            item = {**baseline_item, **candidate_item}
            for metric_name in (
                "return_rate",
                "hit_return_rate",
                "nonmatched_return_rate",
                "nonmatched_nonempty_rate",
                "hit_completeness",
                "hit_accuracy",
            ):
                baseline_value = baseline_item.get(metric_name)
                candidate_value = candidate_item.get(metric_name)
                item[f"baseline_{metric_name}"] = baseline_value
                item[f"candidate_{metric_name}"] = candidate_value
                item[f"{metric_name}_delta"] = (
                    candidate_value - baseline_value
                    if baseline_value is not None
                    and candidate_value is not None
                    else None
                )
            merged[key] = item
        return merged

    @staticmethod
    def assess_evaluation_thresholds(
        metrics: dict[str, Any],
        thresholds: Any,
    ) -> dict[str, Any]:
        """按 Query Stage 判断参考线并给出可解释建议。

        参数说明:
            metrics: ``metrics-v2`` Process 指标模型。
            thresholds: Evaluation 保存的参考线快照。

        返回值:
            每项实际值、参考线、PASS/FAIL/NOT_CONFIGURED/NOT_READY，
            以及“建议上线/继续优化/暂不能判断”的总体建议。

        异常说明:
            ReviewValidationError: 阈值快照损坏或指标规则不是 v2。
        """

        normalized = normalize_evaluation_thresholds(thresholds)
        groups = {
            item["query_stage"]: item
            for item in metrics.get("grouped_metrics", [])
        }
        stage_results: dict[str, Any] = {}
        configured_count = 0
        pass_count = 0
        fail_count = 0
        not_ready_count = 0
        for query_stage in sorted(SUPPORTED_QUERY_STAGES):
            group = groups.get(query_stage)
            actual_values = {
                "min_retrieval_success": (
                    group["quality_metrics"]["retrieval_success"]["value"]
                    if group
                    else None
                ),
                "min_matched_completeness": (
                    group["quality_metrics"]["matched_completeness"]["value"]
                    if group
                    else None
                ),
                "min_matched_accuracy": (
                    group["quality_metrics"]["matched_accuracy"]["value"]
                    if group
                    else None
                ),
                "max_average_total_cost": (
                    group["cost_metrics"]["total_cost"]["average"]
                    if group
                    else None
                ),
                "max_average_search_duration_ms": (
                    group["cost_metrics"]["search_duration_ms"]["average"]
                    if group
                    else None
                ),
            }
            items: dict[str, Any] = {}
            for field_key, rule in EVALUATION_THRESHOLD_FIELDS.items():
                threshold = normalized[query_stage][field_key]
                actual = actual_values[field_key]
                if threshold is None:
                    status = "NOT_CONFIGURED"
                    reason = "未配置参考线"
                else:
                    configured_count += 1
                    if actual is None:
                        status = "NOT_READY"
                        reason = "指标缺失或尚未完成正式复核"
                        not_ready_count += 1
                    else:
                        passed = (
                            actual >= threshold
                            if rule == "minimum_ratio"
                            else actual <= threshold
                        )
                        status = "PASS" if passed else "FAIL"
                        reason = (
                            "达到参考线" if passed else "未达到参考线"
                        )
                        if passed:
                            pass_count += 1
                        else:
                            fail_count += 1
                items[field_key] = {
                    "threshold": threshold,
                    "actual": actual,
                    "direction": (
                        "MINIMUM"
                        if rule == "minimum_ratio"
                        else "MAXIMUM"
                    ),
                    "status": status,
                    "reason": reason,
                }
            stage_results[query_stage] = {
                "query_count": group["query_count"] if group else 0,
                "items": items,
            }
        if fail_count:
            recommendation = "继续优化"
            recommendation_code = "CONTINUE_OPTIMIZATION"
        elif not configured_count or not_ready_count:
            recommendation = "暂不能判断"
            recommendation_code = "NOT_READY"
        else:
            recommendation = "建议上线"
            recommendation_code = "RECOMMEND_RELEASE"
        return {
            "threshold_snapshot": normalized,
            "stages": stage_results,
            "configured_count": configured_count,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "not_ready_count": not_ready_count,
            "recommendation": recommendation,
            "recommendation_code": recommendation_code,
        }

    def build_report_model(
        self,
        *,
        report_id: str,
        candidate_process_id: str,
        baseline_process_id: str | None = None,
        data_marker: str = "REAL_TEST_DATA",
    ) -> dict[str, Any]:
        """构建 Web、静态 HTML 和 Excel 共用的不可变 ReportModel。"""

        if data_marker not in {"REAL_TEST_DATA", "MOCK"}:
            raise ReviewValidationError(
                "data_marker 只支持 REAL_TEST_DATA 或 MOCK"
            )
        candidate_process = self._report_process(candidate_process_id)
        candidate_metrics = self.calculate_process_metrics(
            candidate_process_id
        )
        try:
            threshold_source = json.loads(
                candidate_process["thresholds_json"] or "{}"
            )
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReviewValidationError(
                "Evaluation 参考线快照 JSON 已损坏"
            ) from exc
        threshold_assessment = self.assess_evaluation_thresholds(
            candidate_metrics,
            threshold_source,
        )
        baseline_process = None
        baseline_metrics = None
        comparison = None
        if baseline_process_id:
            baseline_process = self._report_process(baseline_process_id)
            comparison = self.compare_processes(
                baseline_process_id,
                candidate_process_id,
            )
            baseline_metrics = comparison["baseline_metrics"]
        candidate_modules, candidate_fields = (
            self._process_field_report_metrics(candidate_process)
        )
        if baseline_process is not None:
            baseline_modules, baseline_fields = (
                self._process_field_report_metrics(baseline_process)
            )
            module_metrics = self._merge_comparison_metrics(
                baseline_modules,
                candidate_modules,
            )
            field_metrics = self._merge_comparison_metrics(
                baseline_fields,
                candidate_fields,
            )
        else:
            module_metrics = candidate_modules
            field_metrics = candidate_fields
        formal_ready = candidate_metrics["formal_ready"] and (
            comparison is None or comparison["formal_ready"]
        )
        warnings = [
            "系统返回内容仅用于检索能力测试，不代表已经核实的事实。"
        ]
        if not formal_ready:
            warnings.append(
                "基准或人工复核尚未完成，本报告只提供预览值，不输出正式结论。"
            )
        if candidate_metrics["cost_status"]["status"] != "COMPLETE":
            warnings.append(
                "成本与 PDL 数据未完整接入，缺失值未按0计算。"
            )
        if comparison is not None:
            coverage = comparison["same_condition"]["coverage"]
            if coverage["input_signature_unavailable_count"]:
                warnings.append(
                    "部分历史结果缺少 Dataset 输入签名，已归入不可比数据，"
                    "未进入正式同条件结论。"
                )
            if coverage["input_signature_mismatch_count"]:
                warnings.append(
                    "部分 Query 输入签名不一致，已归入不可比数据。"
                )
            if coverage["missing_regression_query_count"]:
                warnings.append(
                    f"Candidate Run 缺少 "
                    f"{coverage['missing_regression_query_count']} 条回归 Query。"
                )
            if coverage["new_clue_count"]:
                warnings.append(
                    f"本阶段包含 {coverage['new_clue_count']} 条新增线索结果，"
                    "不表述为系统版本提升。"
                )
        if candidate_process["failed_queries"]:
            warnings.append(
                f"Candidate Run 含 {candidate_process['failed_queries']} 条失败或部分失败 Query。"
            )
        return {
            "metadata": {
                "report_model_version": REPORT_MODEL_VERSION,
                "metrics_rule_version": candidate_metrics.get(
                    "metrics_rule_version",
                    "metrics-v1",
                ),
                "report_id": report_id,
                "report_type": "COMPARE" if comparison else "SINGLE",
                "evaluation_id": candidate_process["evaluation_id"],
                "evaluation_name": candidate_process["evaluation_name"],
                "evaluation_phase": candidate_process["evaluation_phase"],
                "baseline_evaluation_phase": (
                    baseline_process["evaluation_phase"]
                    if baseline_process
                    else None
                ),
                "generated_at": utc_now_text(),
                "data_marker": data_marker,
                "candidate_process_id": candidate_process_id,
                "baseline_process_id": baseline_process_id,
                "candidate_run_id": candidate_process["run_id"],
                "baseline_run_id": (
                    baseline_process["run_id"] if baseline_process else None
                ),
                "candidate_run_label": candidate_process["run_label"],
                "baseline_run_label": (
                    baseline_process["run_label"] if baseline_process else None
                ),
                "candidate_system_version": candidate_process[
                    "system_version"
                ],
                "baseline_system_version": (
                    baseline_process["system_version"]
                    if baseline_process
                    else None
                ),
                "schema_version": candidate_process["schema_version"],
                "schema_name": candidate_process["schema_name"],
                "baseline_version": candidate_process["baseline_version"],
                "rule_version": candidate_process["rule_version"],
                "source_type": candidate_process["source_type"],
            },
            "summary": {
                "formal_ready": formal_ready,
                "review_status": (
                    "REVIEWED" if formal_ready else "PENDING_REVIEW"
                ),
                "candidate": candidate_metrics,
                "baseline": baseline_metrics,
            },
            "result_status_metrics": candidate_metrics.get(
                "result_status_metrics",
                {},
            ),
            "quality_metrics": candidate_metrics.get(
                "quality_metrics",
                {
                    "retrieval_success": candidate_metrics[
                        "retrieval_success"
                    ],
                    "matched_completeness": candidate_metrics[
                        "matched_completeness"
                    ],
                    "matched_accuracy": candidate_metrics[
                        "matched_accuracy"
                    ],
                    "nonmatched_completeness": candidate_metrics[
                        "nonmatched_completeness"
                    ],
                },
            ),
            "cost_metrics": candidate_metrics.get("cost_metrics", {}),
            "pdl_metrics": candidate_metrics.get("pdl_metrics", {}),
            "confidence_metrics": candidate_metrics.get(
                "confidence_metrics",
                {},
            ),
            "grouped_metrics": candidate_metrics.get(
                "grouped_metrics",
                [],
            ),
            "comparison": comparison or {
                "same_condition": {},
                "new_clue": {},
                "not_comparable": {},
            },
            "threshold_assessment": threshold_assessment,
            "query_stage_metrics": self._query_stage_report_metrics(
                candidate_metrics
            ),
            "paired_metrics": comparison,
            "module_metrics": module_metrics,
            "field_metrics": field_metrics,
            "case_groups": self._report_case_groups(
                candidate_process,
                comparison,
            ),
            "cost_status": candidate_metrics["cost_status"],
            "warnings": warnings,
        }

    def _report_directory(
        self,
        evaluation_id: str,
        report_id: str,
    ) -> Path:
        """返回受控报告目录并验证两个外部标识。"""

        validate_storage_id(evaluation_id, "evaluation_id")
        validate_storage_id(report_id, "report_id")
        target = (self.report_dir / evaluation_id / report_id).resolve()
        try:
            target.relative_to(self.report_dir.resolve())
        except ValueError as exc:
            raise ReviewValidationError("报告目录越出 SEARCH_REPORT_DIR") from exc
        return target

    def _report_export_records(
        self,
        process: sqlite3.Row,
        metrics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """生成 processed Excel 使用的 Query/Candidate/Failure 统一记录。"""

        query_metric_map = {
            row["query_id"]: row for row in metrics["query_metrics"]
        }
        query_rows = self.store.fetch_all(
            """
            SELECT * FROM run_queries
            WHERE run_id = ? ORDER BY query_id
            """,
            (process["run_id"],),
        )
        records: list[dict[str, Any]] = []
        for row in query_rows:
            metric = query_metric_map.get(row["query_id"], {})
            task_fields = metric.get("task_fields", {})
            if not isinstance(task_fields, dict):
                task_fields = {}
            task_processing_errors = metric.get(
                "task_processing_errors",
                [],
            )
            if not isinstance(task_processing_errors, list):
                task_processing_errors = []
            records.append(
                {
                    "record_type": "query",
                    "run_id": process["run_id"],
                    "run_label": process["run_label"],
                    "system_version": process["system_version"],
                    "evaluation_phase": process["evaluation_phase"],
                    "query_id": row["query_id"],
                    "person_id": row["person_id"],
                    "query_stage": row["query_stage"],
                    "task_id": row["task_id"],
                    "query_status": row["status"],
                    "result_status": metric.get("result_status"),
                    "candidate_count_total": row["candidate_count_total"],
                    "candidate_count_listed": row[
                        "candidate_count_listed"
                    ],
                    "detail_success_count": row["detail_success_count"],
                    "detail_failure_count": row["detail_failure_count"],
                    "llm_cost": task_fields.get("llm_cost"),
                    "third_party_cost": task_fields.get(
                        "third_party_cost"
                    ),
                    "total_cost": task_fields.get("total_cost"),
                    "pdl_called": task_fields.get("pdl_called"),
                    "search_duration_ms": task_fields.get(
                        "search_duration_ms"
                    ),
                    "retrieval_success": metric.get("retrieval_success"),
                    "matched_completeness": metric.get(
                        "matched_completeness"
                    ),
                    "matched_accuracy": metric.get("matched_accuracy"),
                    "formal_ready": metric.get("formal_ready", False),
                    "processing_errors": task_processing_errors,
                }
            )
        candidate_rows = self.store.fetch_all(
            """
            SELECT c.*, rq.person_id, rq.query_stage, rq.task_id,
                   rq.status AS query_status,
                   pc.fields_json, pc.empty_fields_json,
                   pc.processing_errors_json,
                   rv.judgement, rv.reason, rv.evidence,
                   rv.field_scores_json, rv.reviewer, rv.review_note,
                   rv.reviewed_at
            FROM processed_candidates AS pc
            JOIN candidates AS c ON c.candidate_pk = pc.candidate_pk
            JOIN run_queries AS rq
              ON rq.run_id = c.run_id AND rq.query_id = c.query_id
            LEFT JOIN reviews AS rv
              ON rv.process_id = pc.process_id
             AND rv.candidate_pk = pc.candidate_pk
            WHERE pc.process_id = ?
            ORDER BY c.query_id, c.candidate_rank
            """,
            (process["process_id"],),
        )
        for row in candidate_rows:
            records.append(
                {
                    "record_type": "candidate",
                    "evaluation_id": process["evaluation_id"],
                    "process_id": process["process_id"],
                    "run_id": process["run_id"],
                    "run_label": process["run_label"],
                    "system_version": process["system_version"],
                    "query_id": row["query_id"],
                    "person_id": row["person_id"],
                    "query_stage": row["query_stage"],
                    "task_id": row["task_id"],
                    "query_status": row["query_status"],
                    "candidate_pk": row["candidate_pk"],
                    "candidate_id": row["candidate_id"],
                    "candidate_rank": row["candidate_rank"],
                    "rank_score": row["rank_score"],
                    "detail_status": row["detail_status"],
                    "detail_error": row["detail_error"],
                    "judgement": row["judgement"] or "PENDING_REVIEW",
                    "reason": row["reason"] or "",
                    "evidence": row["evidence"] or "",
                    "reviewer": row["reviewer"] or "",
                    "review_note": row["review_note"] or "",
                    "reviewed_at": row["reviewed_at"],
                    "fields": json.loads(row["fields_json"]),
                    "empty_fields": json.loads(row["empty_fields_json"]),
                    "field_scores": (
                        json.loads(row["field_scores_json"])
                        if row["field_scores_json"]
                        else {}
                    ),
                    "processing_errors": json.loads(
                        row["processing_errors_json"]
                    ),
                }
            )
        for row in self.store.fetch_all(
            """
            SELECT query_id, candidate_id, scope, stage, error, created_at
            FROM failures WHERE run_id = ? ORDER BY created_at
            """,
            (process["run_id"],),
        ):
            records.append({"record_type": "failure", **dict(row)})
        return records

    def create_report(
        self,
        *,
        candidate_process_id: str,
        baseline_process_id: str | None = None,
        data_marker: str = "REAL_TEST_DATA",
        report_id: str | None = None,
    ) -> ReportResult:
        """创建不可变报告模型快照和 processed Excel 输入文件。"""

        object_id = validate_storage_id(
            report_id or f"report_{uuid.uuid4().hex}",
            "report_id",
        )
        candidate_process = self._report_process(candidate_process_id)
        model = self.build_report_model(
            report_id=object_id,
            candidate_process_id=candidate_process_id,
            baseline_process_id=baseline_process_id,
            data_marker=data_marker,
        )
        report_directory = self._report_directory(
            candidate_process["evaluation_id"],
            object_id,
        )
        if report_directory.exists():
            raise ReviewValidationError(
                f"报告目录已经存在，未覆盖: {object_id}"
            )
        report_directory.mkdir(parents=True, exist_ok=False)
        generated_date = model["metadata"]["generated_at"][:10].replace("-", "")
        version_slug = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "-",
            str(candidate_process["system_version"]),
        ).strip("-.")[:48] or "version"
        report_filename = (
            f"{generated_date}_{candidate_process['evaluation_id']}_"
            f"{version_slug}_report.html"
        )
        html_relative = (
            Path(candidate_process["evaluation_id"])
            / object_id
            / report_filename
        ).as_posix()
        try:
            model_path = report_directory / "report_model.json"
            model_path.write_text(
                json.dumps(
                    model,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            self._write_jsonl(
                report_directory / "processed_export.jsonl",
                self._report_export_records(
                    candidate_process,
                    model["summary"]["candidate"],
                ),
            )
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO reports(
                        report_id, evaluation_id, baseline_process_id,
                        candidate_process_id, report_type, status,
                        metrics_json, html_file, excel_file, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'READY', ?, ?, NULL, ?)
                    """,
                    (
                        object_id,
                        candidate_process["evaluation_id"],
                        baseline_process_id,
                        candidate_process_id,
                        model["metadata"]["report_type"],
                        json_text(model),
                        html_relative,
                        model["metadata"]["generated_at"],
                    ),
                )
        except Exception:
            self._cleanup_created(report_directory)
            raise
        return ReportResult(
            report_id=object_id,
            model=model,
            html_file=html_relative,
            excel_file=None,
        )

    def _report_file_from_row(
        self,
        row: sqlite3.Row,
        relative_path: str,
    ) -> Path:
        """把数据库报告相对路径解析到受控报告目录。"""

        target = (self.report_dir / relative_path).resolve()
        try:
            target.relative_to(self.report_dir.resolve())
        except ValueError as exc:
            raise ReviewValidationError("报告文件路径越界") from exc
        expected_directory = self._report_directory(
            row["evaluation_id"],
            row["report_id"],
        )
        try:
            target.relative_to(expected_directory)
        except ValueError as exc:
            raise ReviewValidationError("报告文件不属于对应报告目录") from exc
        return target

    def save_report_html(self, report_id: str, html: str) -> str:
        """原子写入已创建报告的静态 HTML，不修改指标快照。"""

        row = self.store.fetch_one(
            "SELECT * FROM reports WHERE report_id = ?",
            (report_id,),
        )
        if row is None:
            raise ReviewValidationError(f"报告不存在: {report_id}")
        target = self._report_file_from_row(row, row["html_file"])
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".html.tmp")
        temporary.write_text(html, encoding="utf-8")
        temporary.replace(target)
        return row["html_file"]

    def export_report_excel(
        self,
        report_id: str,
        *,
        exporter_path: Path | str | None = None,
        timeout_seconds: int = 180,
    ) -> str:
        """调用现有 Excel 构建器的 processed 模式并登记导出文件。"""

        row = self.store.fetch_one(
            "SELECT * FROM reports WHERE report_id = ?",
            (report_id,),
        )
        if row is None:
            raise ReviewValidationError(f"报告不存在: {report_id}")
        report_directory = self._report_directory(
            row["evaluation_id"],
            report_id,
        )
        input_path = report_directory / "processed_export.jsonl"
        model_path = report_directory / "report_model.json"
        output_path = report_directory / Path(row["html_file"]).name.replace(
            "_report.html",
            "_report.xlsx",
        )
        script = (
            Path(exporter_path).resolve()
            if exporter_path is not None
            else Path(__file__).resolve().parent / "result_to_excel.py"
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "processed",
                "--input-file",
                str(input_path),
                "--report-model",
                str(model_path),
                "--output",
                str(output_path),
            ],
            cwd=script.parent,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0 or not output_path.is_file():
            message = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "Excel 构建器未生成文件"
            )
            raise RuntimeError(f"Excel 导出不可用: {message[:1000]}")
        relative_path = (
            Path(row["evaluation_id"]) / report_id / output_path.name
        ).as_posix()
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE reports SET excel_file = ?
                WHERE report_id = ?
                """,
                (relative_path, report_id),
            )
        return relative_path

    def resolve_report_artifact(
        self,
        report_id: str,
        artifact: str,
    ) -> Path:
        """解析可下载的 html/excel 报告文件并验证存在性。"""

        columns = {"html": "html_file", "excel": "excel_file"}
        column = columns.get(artifact)
        if column is None:
            raise ReviewValidationError("不支持的报告文件类型")
        row = self.store.fetch_one(
            f"SELECT * FROM reports WHERE report_id = ?",
            (report_id,),
        )
        if row is None or not row[column]:
            raise ReviewValidationError("报告文件不存在")
        target = self._report_file_from_row(row, row[column])
        if not target.is_file():
            raise ReviewValidationError("报告文件不存在")
        return target

    def mark_report_failed(self, report_id: str) -> None:
        """静态报告渲染失败时只标记报告，不删除模型和 Raw。"""

        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE reports SET status = 'FAILED'
                WHERE report_id = ?
                """,
                (report_id,),
            )

    def create_execution_run(
        self,
        *,
        evaluation_id: str,
        dataset_id: str,
        run_label: str,
        system_version: str,
        evaluation_phase: str,
        run_id: str | None = None,
    ) -> str:
        """创建一个等待后台执行的 Run 和全部 PENDING Query。

        功能说明:
            仅创建数据库记录，不在 Web 请求线程中调用真实接口。全局只允许
            一个 ``PENDING`` 或 ``RUNNING`` 的 EXECUTION Run。

        参数说明:
            evaluation_id: 已存在的评测标识。
            dataset_id: 已导入且至少包含一条 Query 的数据集标识。
            run_label: 本次运行标签。
            system_version: 被测系统版本。
            evaluation_phase: 明确的评估阶段；新执行不允许 UNSPECIFIED。
            run_id: 测试或外部编排可显式提供的唯一标识。

        返回值:
            新创建的 Run ID。

        异常说明:
            ImportValidationError: 关联对象不存在或必填值为空。
            ActiveRunError: 已有活动执行任务。
        """

        if not run_label.strip() or not system_version.strip():
            raise ImportValidationError(["run_label 和 system_version 不能为空"])
        if (
            evaluation_phase not in EVALUATION_PHASES
            or evaluation_phase == "UNSPECIFIED"
        ):
            raise ImportValidationError(["新执行必须选择明确的 evaluation_phase"])
        validate_storage_id(evaluation_id, "evaluation_id")
        validate_storage_id(dataset_id, "dataset_id")
        object_id = validate_storage_id(
            run_id or f"run_{uuid.uuid4().hex}",
            "run_id",
        )
        evaluation = self.store.fetch_one(
            "SELECT evaluation_id FROM evaluations WHERE evaluation_id = ?",
            (evaluation_id,),
        )
        dataset = self.store.fetch_one(
            "SELECT dataset_id, query_count FROM datasets WHERE dataset_id = ?",
            (dataset_id,),
        )
        if evaluation is None:
            raise ImportValidationError([f"Evaluation 不存在: {evaluation_id}"])
        if dataset is None:
            raise ImportValidationError([f"Dataset 不存在: {dataset_id}"])
        if int(dataset["query_count"]) <= 0:
            raise ImportValidationError(["Dataset 没有可执行 Query"])
        dataset_queries = self.store.fetch_all(
            """
            SELECT query_id, person_id, query_stage
            FROM dataset_queries
            WHERE dataset_id = ?
            ORDER BY rowid
            """,
            (dataset_id,),
        )
        now = utc_now_text()
        with self._execution_lock:
            active = self.store.fetch_one(
                """
                SELECT run_id FROM runs
                WHERE source_type = 'EXECUTION'
                  AND status IN ('PENDING', 'RUNNING')
                LIMIT 1
                """
            )
            if active is not None:
                raise ActiveRunError(
                    f"已有执行任务 {active['run_id']} 正在等待或运行"
                )
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO runs(
                        run_id, evaluation_id, dataset_id, run_label,
                        system_version, source_type, status,
                        result_schema_version, total_queries, success_queries,
                        failed_queries, message, evaluation_phase, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'EXECUTION', 'PENDING', ?, ?, 0, 0, ?, ?, ?)
                    """,
                    (
                        object_id,
                        evaluation_id,
                        dataset_id,
                        run_label.strip(),
                        system_version.strip(),
                        RESULT_SCHEMA_VERSION,
                        len(dataset_queries),
                        "等待后台执行",
                        evaluation_phase,
                        now,
                    ),
                )
                for query in dataset_queries:
                    connection.execute(
                        """
                        INSERT INTO run_queries(
                            run_id, query_id, person_id, query_stage, status,
                            current_stage
                        ) VALUES (?, ?, ?, ?, 'PENDING', 'Input')
                        """,
                        (
                            object_id,
                            query["query_id"],
                            query["person_id"],
                            query["query_stage"],
                        ),
                    )
        return object_id

    def update_run_evaluation_phase(
        self,
        run_id: str,
        evaluation_phase: str,
    ) -> None:
        """更新 Run 的显式评估阶段并令关联报告过期。

        历史 Run 允许从 ``UNSPECIFIED`` 补录阶段，也允许测试人员纠正误选；
        不根据 run_label 或 system_version 自动猜测。
        """

        if evaluation_phase not in EVALUATION_PHASES:
            raise ImportValidationError(
                [f"evaluation_phase 不受支持: {evaluation_phase}"]
            )
        with self.store.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE runs SET evaluation_phase = ?
                WHERE run_id = ?
                """,
                (evaluation_phase, run_id),
            )
            if cursor.rowcount != 1:
                raise ImportValidationError([f"Run 不存在: {run_id}"])
            connection.execute(
                """
                UPDATE reports SET status = 'STALE'
                WHERE status = 'READY'
                  AND (
                    candidate_process_id IN (
                        SELECT process_id FROM process_runs WHERE run_id = ?
                    )
                    OR baseline_process_id IN (
                        SELECT process_id FROM process_runs WHERE run_id = ?
                    )
                  )
                """,
                (run_id, run_id),
            )

    def _execution_paths(
        self,
        evaluation_id: str,
        run_id: str,
    ) -> tuple[Path, Path]:
        """返回一个执行 Run 的受控 results/failures JSONL 路径。"""

        validate_storage_id(evaluation_id, "evaluation_id")
        validate_storage_id(run_id, "run_id")
        run_dir = self.raw_dir / evaluation_id / run_id
        return run_dir / "results.jsonl", run_dir / "failures.jsonl"

    def _update_execution_progress(
        self,
        run_id: str,
        event: dict[str, Any],
    ) -> None:
        """把采集回调转换为页面可轮询的 Query 与 Run 最新状态。"""

        query_id = str(event.get("input_id") or "")
        stage = str(event.get("stage") or "")
        task_id = str(event.get("task_id") or "")
        message = str(event.get("message") or event.get("status") or stage)
        with self.store.transaction() as connection:
            if query_id:
                connection.execute(
                    """
                    UPDATE run_queries
                    SET current_stage = ?,
                        task_id = CASE WHEN ? = '' THEN task_id ELSE ? END
                    WHERE run_id = ? AND query_id = ?
                    """,
                    (stage, task_id, task_id, run_id, query_id),
                )
            connection.execute(
                "UPDATE runs SET message = ? WHERE run_id = ?",
                (f"{query_id}: {message}" if query_id else message, run_id),
            )

    def _persist_execution_success(
        self,
        *,
        run_id: str,
        result: dict[str, Any],
        raw_records: list[dict[str, Any]],
        candidate_failures: list[dict[str, Any]],
    ) -> None:
        """在一个事务内保存成功或部分成功 Query 的全部数据。"""

        query_id = result["input_id"]
        now = utc_now_text()
        task_fields = (
            result.get("task_fields")
            if isinstance(result.get("task_fields"), dict)
            else {}
        )
        public_fields = {
            key: value
            for key, value in task_fields.items()
            if key not in TASK_FIELD_KEYS
        }
        if isinstance(result.get("public_fields"), dict):
            public_fields.update(result["public_fields"])
        result_status = normalize_result_status(
            result["query_status"],
            result.get("candidate_count_listed"),
        )
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE run_queries
                SET task_id = ?, status = ?, current_stage = 'Completed',
                    candidate_count_total = ?, candidate_count_listed = ?,
                    detail_success_count = ?, detail_failure_count = ?,
                    llm_cost = ?, third_party_cost = ?, total_cost = ?,
                    pdl_called = ?, search_duration_ms = ?,
                    result_status = ?, public_fields_json = ?,
                    error = '', finished_at = ?
                WHERE run_id = ? AND query_id = ?
                """,
                (
                    result.get("task_id"),
                    result["query_status"],
                    result.get("candidate_count_total"),
                    result.get("candidate_count_listed", 0),
                    result.get("detail_success_count", 0),
                    result.get("detail_failure_count", 0),
                    task_fields.get("llm_cost"),
                    task_fields.get("third_party_cost"),
                    task_fields.get("total_cost"),
                    task_fields.get("pdl_called"),
                    task_fields.get("search_duration_ms"),
                    result_status,
                    json_text(public_fields),
                    now,
                    run_id,
                    query_id,
                ),
            )
            candidate_by_identity: dict[tuple[str, int], str] = {}
            for candidate in result.get("results", []):
                candidate_pk = f"candidate_{uuid.uuid4().hex}"
                rank = int(candidate["candidate_rank"])
                candidate_id = str(candidate.get("candidate_id") or "")
                candidate_by_identity[(candidate_id, rank)] = candidate_pk
                connection.execute(
                    """
                    INSERT INTO candidates(
                        candidate_pk, run_id, query_id, candidate_id,
                        candidate_rank, rank_score, detail_status,
                        detail_error, ui_sections_json, detail_data_json,
                        list_item_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_pk,
                        run_id,
                        query_id,
                        candidate_id,
                        rank,
                        candidate.get("rank_score"),
                        candidate.get("detail_status", "FAILED"),
                        str(candidate.get("detail_error") or ""),
                        (
                            json_text(candidate["ui_sections"])
                            if candidate.get("ui_sections") is not None
                            else None
                        ),
                        (
                            json_text(candidate["detail_data_raw"])
                            if candidate.get("detail_data_raw") is not None
                            else None
                        ),
                        json_text(candidate.get("list_item_raw") or {}),
                        now,
                    ),
                )
            for raw in raw_records:
                raw_candidate_id = str(raw.get("candidate_id") or "")
                sequence_no = int(raw.get("sequence_no") or 1)
                candidate_pk = candidate_by_identity.get(
                    (raw_candidate_id, sequence_no)
                )
                if candidate_pk is None and raw_candidate_id:
                    candidate_pk = next(
                        (
                            value
                            for (candidate_id, _), value in candidate_by_identity.items()
                            if candidate_id == raw_candidate_id
                        ),
                        None,
                    )
                self._insert_raw(
                    connection,
                    run_id=run_id,
                    query_id=query_id,
                    candidate_pk=candidate_pk,
                    stage=str(raw.get("stage") or "Import"),
                    sequence_no=sequence_no,
                    payload=raw,
                    collected_at=raw.get("collected_at"),
                )
            for failure in candidate_failures:
                connection.execute(
                    """
                    INSERT INTO failures(
                        failure_id, run_id, query_id, candidate_id,
                        scope, stage, error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"failure_{uuid.uuid4().hex}",
                        run_id,
                        query_id,
                        str(failure.get("candidate_id") or ""),
                        "CANDIDATE",
                        str(failure.get("stage") or "GetTaskCandidateDetail"),
                        str(failure.get("error") or ""),
                        failure.get("created_at") or now,
                    ),
                )

    def _persist_execution_failure(
        self,
        *,
        run_id: str,
        query_id: str,
        error: FlowError,
    ) -> dict[str, Any]:
        """保存 Query 级失败及失败前已获得的 Raw，并返回文件记录。"""

        now = utc_now_text()
        failure_record = {
            "failure_schema_version": RESULT_SCHEMA_VERSION,
            "run_id": run_id,
            "input_id": query_id,
            "task_id": error.task_id,
            "candidate_id": "",
            "scope": "INPUT" if error.stage == "Input" else "QUERY",
            "stage": error.stage,
            "query_status": "FAILED",
            "result_status": "EXECUTION_FAILED",
            "error": str(error),
            "raw": error.raw_records,
            "created_at": now,
        }
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE run_queries
                SET task_id = ?, status = 'FAILED', current_stage = ?,
                    result_status = 'EXECUTION_FAILED',
                    error = ?, finished_at = ?
                WHERE run_id = ? AND query_id = ?
                """,
                (error.task_id, error.stage, str(error), now, run_id, query_id),
            )
            for raw in error.raw_records:
                self._insert_raw(
                    connection,
                    run_id=run_id,
                    query_id=query_id,
                    candidate_pk=None,
                    stage=str(raw.get("stage") or error.stage),
                    sequence_no=int(raw.get("sequence_no") or 1),
                    payload=raw,
                    collected_at=raw.get("collected_at"),
                )
            connection.execute(
                """
                INSERT INTO failures(
                    failure_id, run_id, query_id, candidate_id,
                    scope, stage, error, created_at
                ) VALUES (?, ?, ?, '', ?, ?, ?, ?)
                """,
                (
                    f"failure_{uuid.uuid4().hex}",
                    run_id,
                    query_id,
                    failure_record["scope"],
                    error.stage,
                    str(error),
                    now,
                ),
            )
        return failure_record

    def execute_run(
        self,
        run_id: str,
        client: Any,
        *,
        sleep_fn: Callable[[float], None],
    ) -> None:
        """顺序执行一个 PENDING Run，并持续保存页面进度与 Query 结果。

        参数说明:
            run_id: ``create_execution_run`` 创建的 Run。
            client: 与 ``SearchClient`` 相同接口的同步客户端。
            sleep_fn: GetTask 轮询等待函数；生产传入 ``time.sleep``。

        返回值:
            无。最终状态和计数写入 SQLite，结果写入受控 Raw 目录。

        异常说明:
            ValueError: Run 不存在或不是可启动的执行 Run。
            非业务异常向上抛出，由后台协调器标记 Run 失败。
        """

        run = self.store.fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if run is None:
            raise ValueError(f"Run 不存在: {run_id}")
        if run["source_type"] != "EXECUTION" or run["status"] != "PENDING":
            raise ValueError(f"Run {run_id} 当前状态不可执行: {run['status']}")
        results_path, failures_path = self._execution_paths(
            run["evaluation_id"],
            run_id,
        )
        if results_path.exists() or failures_path.exists():
            raise FileExistsError(f"Run {run_id} 的执行文件已存在，禁止覆盖")
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text("", encoding="utf-8")
        failures_path.write_text("", encoding="utf-8")
        now = utc_now_text()
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = 'RUNNING', started_at = ?, message = ?,
                    results_file = ?, failures_file = ?
                WHERE run_id = ?
                """,
                (
                    now,
                    "开始执行",
                    results_path.relative_to(self.data_dir).as_posix(),
                    failures_path.relative_to(self.data_dir).as_posix(),
                    run_id,
                ),
            )
        queries = self.store.fetch_all(
            """
            SELECT dq.query_id, dq.person_id, dq.query_stage,
                   dq.match_strategy, dq.clues_json,
                   dq.additional_details_json
            FROM dataset_queries AS dq
            JOIN runs AS r ON r.dataset_id = dq.dataset_id
            WHERE r.run_id = ?
            ORDER BY dq.rowid
            """,
            (run_id,),
        )
        success_count = 0
        failed_count = 0
        for query in queries:
            query_id = query["query_id"]
            started_at = utc_now_text()
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    UPDATE run_queries
                    SET status = 'RUNNING', current_stage = 'Input',
                        started_at = ?
                    WHERE run_id = ? AND query_id = ?
                    """,
                    (started_at, run_id, query_id),
                )
            item = {
                "input_id": query_id,
                "query_stage": query["query_stage"],
                "match_strategy": query["match_strategy"],
                "clues": json.loads(query["clues_json"]),
                "additional_details": json.loads(query["additional_details_json"]),
            }
            raw_records: list[dict[str, Any]] = []
            candidate_failures: list[dict[str, Any]] = []
            try:
                result = process_one(
                    item,
                    client,
                    sleep_fn=sleep_fn,
                    progress_callback=lambda event: self._update_execution_progress(
                        run_id,
                        event,
                    ),
                    raw_callback=raw_records.append,
                    failure_callback=candidate_failures.append,
                    run_id=run_id,
                )
                result["person_id"] = query["person_id"]
                self._persist_execution_success(
                    run_id=run_id,
                    result=result,
                    raw_records=raw_records,
                    candidate_failures=candidate_failures,
                )
                self._append_jsonl(results_path, result)
                for candidate_failure in candidate_failures:
                    self._append_jsonl(failures_path, candidate_failure)
                if result["query_status"] in {"SUCCESS", "NO_CANDIDATE"}:
                    success_count += 1
                else:
                    failed_count += 1
            except FlowError as exc:
                failure = self._persist_execution_failure(
                    run_id=run_id,
                    query_id=query_id,
                    error=exc,
                )
                self._append_jsonl(failures_path, failure)
                failed_count += 1
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    UPDATE runs
                    SET success_queries = ?, failed_queries = ?,
                        message = ?
                    WHERE run_id = ?
                    """,
                    (
                        success_count,
                        failed_count,
                        f"已完成 {success_count + failed_count}/{len(queries)}",
                        run_id,
                    ),
                )
        if failed_count == len(queries):
            final_status = "FAILED"
        elif failed_count:
            final_status = "PARTIAL_FAILED"
        else:
            final_status = "COMPLETED"
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = ?, finished_at = ?, message = ?
                WHERE run_id = ?
                """,
                (
                    final_status,
                    utc_now_text(),
                    f"执行结束：成功 {success_count}，失败或部分失败 {failed_count}",
                    run_id,
                ),
            )

    def mark_run_failed(self, run_id: str, message: str) -> None:
        """后台初始化或意外错误时把活动 Run 标记为失败，避免永久卡住。"""

        safe_message = str(message).replace("\n", " ")[:1000]
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE run_queries
                SET status = 'FAILED', current_stage = 'Execution',
                    result_status = 'EXECUTION_FAILED',
                    error = CASE WHEN error = '' THEN ? ELSE error END,
                    finished_at = COALESCE(finished_at, ?)
                WHERE run_id = ? AND status IN ('PENDING', 'RUNNING')
                """,
                (safe_message, utc_now_text(), run_id),
            )
            connection.execute(
                """
                UPDATE runs
                SET status = 'FAILED', finished_at = ?, message = ?
                WHERE run_id = ? AND status IN ('PENDING', 'RUNNING')
                """,
                (utc_now_text(), safe_message, run_id),
            )

    def recover_interrupted_runs(self) -> int:
        """应用启动时标记遗留 RUNNING Run，并保留已落库数据。"""

        now = utc_now_text()
        with self.store.transaction() as connection:
            rows = connection.execute(
                """
                SELECT run_id, total_queries, success_queries
                FROM runs
                WHERE source_type = 'EXECUTION' AND status = 'RUNNING'
                """
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE run_queries
                    SET status = 'FAILED',
                        result_status = 'EXECUTION_FAILED',
                        error = CASE WHEN error = ''
                            THEN 'Web 应用重启，当前 Query 执行已中断'
                            ELSE error END,
                        finished_at = COALESCE(finished_at, ?)
                    WHERE run_id = ? AND status = 'RUNNING'
                    """,
                    (now, row["run_id"]),
                )
                connection.execute(
                    """
                    UPDATE runs
                    SET status = 'INTERRUPTED', finished_at = ?,
                        failed_queries = MAX(
                            failed_queries,
                            total_queries - success_queries
                        ),
                        message = 'Web 应用重启，执行已中断；已完成数据已保留'
                    WHERE run_id = ?
                    """,
                    (now, row["run_id"]),
                )
        return len(rows)

    def _excel_rows(
        self,
        workbook: Any,
        sheet_name: str,
        required_headers: set[str],
        *,
        optional: bool = False,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """读取一个 Sheet 为字典行，并验证表头。"""

        if sheet_name not in workbook.sheetnames:
            if optional:
                return [], []
            return [], [f"缺少必需 Sheet: {sheet_name}"]
        sheet = workbook[sheet_name]
        iterator = sheet.iter_rows(values_only=True)
        try:
            raw_headers = next(iterator)
        except StopIteration:
            return [], [f"Sheet {sheet_name} 为空"]
        headers = [str(value).strip() if value is not None else "" for value in raw_headers]
        missing = sorted(required_headers - set(headers))
        if missing:
            return [], [f"Sheet {sheet_name} 缺少列: {', '.join(missing)}"]
        rows: list[dict[str, Any]] = []
        for row_number, values in enumerate(iterator, start=2):
            if not any(value not in (None, "") for value in values):
                continue
            row = {
                header: values[index] if index < len(values) else None
                for index, header in enumerate(headers)
                if header
            }
            row["_row_number"] = row_number
            rows.append(row)
        return rows, []

    def _normalize_dataset_records(
        self,
        records: list[Any],
        initial_errors: list[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """校验 Dataset Query 并转换为数据库需要的统一结构。"""

        normalized: list[dict[str, Any]] = []
        errors = list(initial_errors)
        seen_ids: set[str] = set()
        for index, record in enumerate(records, start=1):
            label = f"第 {index} 条"
            if not isinstance(record, dict):
                errors.append(f"{label}必须是对象")
                continue
            query_id = record.get("input_id")
            query_stage = record.get("query_stage")
            clues = record.get("clues")
            additional_details = record.get("additional_details", [])
            if not isinstance(query_id, str) or not query_id.strip():
                errors.append(f"{label}缺少非空 input_id")
                continue
            if query_id in seen_ids:
                errors.append(f"{label} input_id 重复: {query_id}")
                continue
            seen_ids.add(query_id)
            if query_stage not in SUPPORTED_QUERY_STAGES:
                errors.append(
                    f"{label} query_stage 只支持 FULL_NAME/FULL_NAME_SOCIAL"
                )
                continue
            if not isinstance(clues, list) or not clues:
                errors.append(f"{label} clues 必须是非空数组")
                continue
            clue_types = {
                clue.get("type") for clue in clues if isinstance(clue, dict)
            }
            if "FULL_NAME" not in clue_types:
                errors.append(f"{label}缺少 FULL_NAME 线索")
                continue
            if query_stage == "FULL_NAME_SOCIAL" and "SOCIAL_LINK" not in clue_types:
                errors.append(f"{label}缺少 SOCIAL_LINK 线索")
                continue
            if not isinstance(additional_details, list):
                errors.append(f"{label} additional_details 必须是数组")
                continue
            match_strategy = record.get("match_strategy") or "UNION"
            if not isinstance(match_strategy, str):
                errors.append(f"{label} match_strategy 必须是字符串")
                continue
            metadata = {
                key: value
                for key, value in record.items()
                if key
                not in {
                    "input_id",
                    "person_id",
                    "query_stage",
                    "match_strategy",
                    "clues",
                    "additional_details",
                }
            }
            normalized.append(
                {
                    "query_id": query_id,
                    "person_id": record.get("person_id"),
                    "query_stage": query_stage,
                    "match_strategy": match_strategy,
                    "clues": clues,
                    "additional_details": additional_details,
                    "metadata": metadata,
                }
            )
        return normalized, errors

    def preview_dataset_jsonl(self, source: Path | str) -> ImportPreview:
        """预览 Dataset JSONL 的合法数量和全部错误，不写文件或数据库。"""

        path = self._source_path(source, {".jsonl"})
        records, parse_errors = read_jsonl(path)
        normalized, errors = self._normalize_dataset_records(records, parse_errors)
        return ImportPreview(file_checksum([("source", path)]), len(normalized), errors)

    def import_dataset_jsonl(
        self,
        source: Path | str,
        *,
        name: str,
        dataset_id: str | None = None,
    ) -> ImportResult:
        """校验、归档并事务导入 Query Dataset JSONL。"""

        path = self._source_path(source, {".jsonl"})
        records, parse_errors = read_jsonl(path)
        normalized, errors = self._normalize_dataset_records(records, parse_errors)
        return self._import_dataset(
            path,
            normalized,
            errors,
            name=name,
            dataset_id=dataset_id,
            source_type="JSONL",
        )

    def import_dataset_excel(
        self,
        source: Path | str,
        *,
        name: str,
        dataset_id: str | None = None,
    ) -> ImportResult:
        """从固定 Queries Sheet 导入 Query Dataset。"""

        path = self._source_path(source, {".xlsx"})
        workbook = load_workbook(
            path,
            read_only=True,
            data_only=True,
            keep_links=False,
        )
        try:
            rows, errors = self._excel_rows(
                workbook,
                "Queries",
                {"input_id", "query_stage", "clues"},
            )
        finally:
            workbook.close()
        records = []
        for row in rows:
            record = {
                key: cell_value(value)
                for key, value in row.items()
                if key != "_row_number"
            }
            records.append(record)
        normalized, errors = self._normalize_dataset_records(records, errors)
        return self._import_dataset(
            path,
            normalized,
            errors,
            name=name,
            dataset_id=dataset_id,
            source_type="EXCEL",
        )

    def _import_dataset(
        self,
        source: Path,
        records: list[dict[str, Any]],
        errors: list[str],
        *,
        name: str,
        dataset_id: str | None,
        source_type: str,
    ) -> ImportResult:
        """执行 Dataset JSONL/Excel 共用的归档和事务写入。"""

        if errors:
            raise ImportValidationError(errors)
        if not records:
            raise ImportValidationError(["Dataset 不包含合法 Query"])
        object_id = validate_storage_id(
            dataset_id or f"dataset_{uuid.uuid4().hex}",
            "dataset_id",
        )
        checksum = file_checksum([("source", source)])
        if self.store.fetch_one(
            "SELECT dataset_id FROM datasets WHERE checksum = ?",
            (checksum,),
        ):
            raise DuplicateImportError("相同 Dataset 文件已经导入")
        archive_dir, archived = self._archive_sources(
            object_id,
            [("source", source)],
        )
        now = utc_now_text()
        try:
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO datasets(
                        dataset_id, name, source_type, source_file,
                        checksum, query_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        object_id,
                        name,
                        source_type,
                        archived[0],
                        checksum,
                        len(records),
                        now,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO dataset_queries(
                        dataset_id, query_id, person_id, query_stage,
                        match_strategy, clues_json, additional_details_json,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            object_id,
                            record["query_id"],
                            record["person_id"],
                            record["query_stage"],
                            record["match_strategy"],
                            json_text(record["clues"]),
                            json_text(record["additional_details"]),
                            json_text(record["metadata"]),
                        )
                        for record in records
                    ],
                )
        except sqlite3.IntegrityError as exc:
            self._cleanup_created(archive_dir)
            if "checksum" in str(exc).lower():
                raise DuplicateImportError("相同 Dataset 文件已经导入") from exc
            raise
        except Exception:
            self._cleanup_created(archive_dir)
            raise
        return ImportResult(object_id, len(records), checksum, archived)

    def _normalize_baseline_records(
        self,
        records: list[Any],
        initial_errors: list[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """校验 Person 基准并保留字段及证据对象。"""

        normalized: list[dict[str, Any]] = []
        errors = list(initial_errors)
        seen: set[str] = set()
        for index, record in enumerate(records, start=1):
            label = f"第 {index} 条"
            if not isinstance(record, dict):
                errors.append(f"{label}必须是对象")
                continue
            person_id = record.get("person_id")
            fields = record.get("fields", {})
            evidence = record.get("evidence", {})
            if not isinstance(person_id, str) or not person_id.strip():
                errors.append(f"{label}缺少非空 person_id")
                continue
            if person_id in seen:
                errors.append(f"{label} person_id 重复: {person_id}")
                continue
            seen.add(person_id)
            if not isinstance(fields, dict) or not isinstance(evidence, dict):
                errors.append(f"{label} fields 和 evidence 必须是对象")
                continue
            if "baseline_available_fields" in record:
                try:
                    available_fields = normalize_available_fields(
                        record["baseline_available_fields"]
                    )
                except ValueError as exc:
                    errors.append(f"{label} {exc}")
                    continue
                available_fields_source = "IMPORT"
            else:
                available_fields = _derived_available_fields(fields)
                available_fields_source = (
                    "DERIVED_LEGACY"
                    if available_fields
                    else "UNSPECIFIED"
                )
            normalized.append(
                {
                    "person_id": person_id,
                    "display_name": record.get("display_name"),
                    "fields": fields,
                    "evidence": evidence,
                    "available_fields": available_fields,
                    "available_fields_source": available_fields_source,
                }
            )
        return normalized, errors

    def import_baseline_jsonl(
        self,
        source: Path | str,
        *,
        name: str,
        baseline_version: str,
    ) -> ImportResult:
        """校验、归档并事务导入基准 JSONL。"""

        path = self._source_path(source, {".jsonl"})
        records, parse_errors = read_jsonl(path)
        normalized, errors = self._normalize_baseline_records(records, parse_errors)
        return self._import_baseline(
            path,
            normalized,
            errors,
            name=name,
            baseline_version=baseline_version,
            source_type="JSONL",
        )

    def import_baseline_excel(
        self,
        source: Path | str,
        *,
        name: str,
        baseline_version: str,
    ) -> ImportResult:
        """从固定“基准数据”Sheet 导入 Person 基准。"""

        path = self._source_path(source, {".xlsx"})
        workbook = load_workbook(
            path,
            read_only=True,
            data_only=True,
            keep_links=False,
        )
        try:
            rows, errors = self._excel_rows(
                workbook,
                "基准数据",
                {"person_id"},
            )
        finally:
            workbook.close()
        records = []
        for row in rows:
            available_value = row.get("baseline_available_fields")
            available_present = available_value not in (None, "")
            available_fields: Any = None
            if available_present:
                if isinstance(available_value, str):
                    text = available_value.strip()
                    if text.startswith("["):
                        try:
                            available_fields = json.loads(text)
                        except json.JSONDecodeError:
                            errors.append(
                                f"基准数据第 {row['_row_number']} 行 "
                                "baseline_available_fields JSON 格式错误"
                            )
                            available_fields = []
                    else:
                        available_fields = [
                            item.strip() for item in text.split(",")
                        ]
                else:
                    available_fields = cell_value(available_value)
            fields = {
                key: cell_value(value)
                for key, value in row.items()
                if key
                not in {
                    "_row_number",
                    "person_id",
                    "display_name",
                    "evidence",
                    "baseline_available_fields",
                }
                and value not in (None, "")
            }
            evidence_value = cell_value(row.get("evidence"))
            record = {
                "person_id": row.get("person_id"),
                "display_name": row.get("display_name"),
                "fields": fields,
                "evidence": (
                    evidence_value if isinstance(evidence_value, dict) else {}
                ),
            }
            if available_present:
                record["baseline_available_fields"] = available_fields
            records.append(record)
        normalized, errors = self._normalize_baseline_records(records, errors)
        return self._import_baseline(
            path,
            normalized,
            errors,
            name=name,
            baseline_version=baseline_version,
            source_type="EXCEL",
        )

    def _import_baseline(
        self,
        source: Path,
        records: list[dict[str, Any]],
        errors: list[str],
        *,
        name: str,
        baseline_version: str,
        source_type: str,
    ) -> ImportResult:
        """执行 JSONL/Excel 基准共用的归档和事务写入。"""

        if errors:
            raise ImportValidationError(errors)
        if not records:
            raise ImportValidationError(["基准文件不包含合法人物"])
        object_id = validate_storage_id(baseline_version, "baseline_version")
        checksum = file_checksum([("source", source)])
        if self.store.fetch_one(
            "SELECT baseline_version FROM baseline_sets WHERE checksum = ?",
            (checksum,),
        ):
            raise DuplicateImportError("相同基准文件已经导入")
        archive_dir, archived = self._archive_sources(
            object_id,
            [("source", source)],
        )
        now = utc_now_text()
        try:
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO baseline_sets(
                        baseline_version, name, source_type,
                        source_file, checksum, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (object_id, name, source_type, archived[0], checksum, now),
                )
                connection.executemany(
                    """
                    INSERT INTO baseline_people(
                        baseline_version, person_id, display_name,
                        fields_json, evidence_json, available_fields_json,
                        available_fields_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            object_id,
                            record["person_id"],
                            record["display_name"],
                            json_text(record["fields"]),
                            json_text(record["evidence"]),
                            json_text(record["available_fields"]),
                            record["available_fields_source"],
                        )
                        for record in records
                    ],
                )
        except sqlite3.IntegrityError as exc:
            self._cleanup_created(archive_dir)
            if "checksum" in str(exc).lower():
                raise DuplicateImportError("相同基准文件已经导入") from exc
            if "baseline_sets.baseline_version" in str(exc):
                raise DuplicateImportError(
                    f"baseline_version 已存在: {object_id}"
                ) from exc
            raise
        except Exception:
            self._cleanup_created(archive_dir)
            raise
        return ImportResult(object_id, len(records), checksum, archived)

    def update_baseline_available_fields(
        self,
        baseline_version: str,
        person_id: str,
        available_fields: Any,
    ) -> None:
        """人工维护人物可评估字段并令关联报告快照过期。

        参数说明:
            baseline_version: 已存在的 Baseline 版本。
            person_id: Baseline 中的人物标识。
            available_fields: 页面提交的字符串数组，允许显式清空。

        返回值:
            无；成功后来源固定标记为 ``MANUAL``。

        异常说明:
            ImportValidationError: 字段数组非法或人物不存在。
        """

        try:
            normalized = normalize_available_fields(available_fields)
        except ValueError as exc:
            raise ImportValidationError([str(exc)]) from exc
        with self.store.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE baseline_people
                SET available_fields_json = ?,
                    available_fields_source = 'MANUAL'
                WHERE baseline_version = ? AND person_id = ?
                """,
                (json_text(normalized), baseline_version, person_id),
            )
            if cursor.rowcount != 1:
                raise ImportValidationError(
                    [
                        f"Baseline 人物不存在: "
                        f"{baseline_version}/{person_id}"
                    ]
                )
            connection.execute(
                """
                UPDATE reports SET status = 'STALE'
                WHERE status = 'READY'
                  AND (
                    candidate_process_id IN (
                        SELECT process_id FROM process_runs
                        WHERE baseline_version = ?
                    )
                    OR baseline_process_id IN (
                        SELECT process_id FROM process_runs
                        WHERE baseline_version = ?
                    )
                  )
                """,
                (baseline_version, baseline_version),
            )

    def _metadata_records(
        self,
        path: Path | None,
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """读取可选 Query 元数据并按 query_id 建索引。"""

        if path is None:
            return {}, []
        records, errors = read_jsonl(path)
        indexed: dict[str, dict[str, Any]] = {}
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                errors.append(f"元数据第 {index} 条必须是对象")
                continue
            query_id = record.get("query_id") or record.get("input_id")
            if not isinstance(query_id, str) or not query_id:
                errors.append(f"元数据第 {index} 条缺少 query_id/input_id")
                continue
            if query_id in indexed:
                errors.append(f"元数据 query_id 重复: {query_id}")
                continue
            indexed[query_id] = record
        return indexed, errors

    def _normalize_result_records(
        self,
        records: list[Any],
        metadata: dict[str, dict[str, Any]],
        initial_errors: list[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """将旧版和 v1.3 结果转换为同一中间结构。"""

        normalized: list[dict[str, Any]] = []
        errors = list(initial_errors)
        seen: set[str] = set()
        for index, raw_record in enumerate(records, start=1):
            label = f"结果第 {index} 条"
            if not isinstance(raw_record, dict):
                errors.append(f"{label}必须是对象")
                continue
            query_id = raw_record.get("input_id")
            candidates = raw_record.get("results")
            if not isinstance(query_id, str) or not query_id:
                errors.append(f"{label}缺少非空 input_id")
                continue
            if query_id in seen:
                errors.append(f"{label} input_id 重复: {query_id}")
                continue
            seen.add(query_id)
            if not isinstance(candidates, list):
                errors.append(f"{label} results 必须是数组")
                continue
            normalized_candidates = []
            ranks: set[int] = set()
            candidate_error = False
            for candidate_index, candidate in enumerate(candidates, start=1):
                if not isinstance(candidate, dict):
                    errors.append(
                        f"{label} results[{candidate_index - 1}] 必须是对象"
                    )
                    candidate_error = True
                    continue
                rank = candidate.get("candidate_rank", candidate_index)
                if (
                    not isinstance(rank, int)
                    or isinstance(rank, bool)
                    or rank <= 0
                    or rank in ranks
                ):
                    errors.append(f"{label}候选人 rank 无效或重复: {rank!r}")
                    candidate_error = True
                    continue
                ranks.add(rank)
                detail_status = candidate.get("detail_status")
                if detail_status not in {"SUCCESS", "FAILED"}:
                    detail_status = "SUCCESS"
                normalized_candidate = dict(sanitize_raw(candidate))
                normalized_candidate.update(
                    {
                        "candidate_rank": rank,
                        "candidate_id": str(candidate.get("candidate_id") or ""),
                        "rank_score": (
                            candidate.get("rank_score")
                            if isinstance(candidate.get("rank_score"), (int, float))
                            and not isinstance(candidate.get("rank_score"), bool)
                            else None
                        ),
                        "detail_status": detail_status,
                        "detail_error": str(candidate.get("detail_error") or ""),
                        "list_item_raw": candidate.get("list_item_raw")
                        or {
                            "candidate_id": candidate.get("candidate_id"),
                            "rank_score": candidate.get("rank_score"),
                        },
                        "detail_data_raw": candidate.get("detail_data_raw"),
                        "ui_sections": candidate.get("ui_sections"),
                    }
                )
                normalized_candidates.append(normalized_candidate)
            if candidate_error:
                continue
            metadata_record = metadata.get(query_id, {})
            query_stage = raw_record.get("query_stage") or metadata_record.get(
                "query_stage"
            )
            if query_stage not in SUPPORTED_QUERY_STAGES:
                query_stage = None
            failed_details = sum(
                item["detail_status"] == "FAILED"
                for item in normalized_candidates
            )
            success_details = len(normalized_candidates) - failed_details
            query_status = raw_record.get("query_status")
            if query_status not in {
                "SUCCESS",
                "NO_CANDIDATE",
                "PARTIAL_DETAIL_FAILED",
            }:
                if not normalized_candidates:
                    query_status = "NO_CANDIDATE"
                elif failed_details:
                    query_status = "PARTIAL_DETAIL_FAILED"
                else:
                    query_status = "SUCCESS"
            raw_value = raw_record.get("raw")
            has_raw = isinstance(raw_value, dict) and bool(raw_value)
            task_fields = (
                raw_record.get("task_fields")
                if isinstance(raw_record.get("task_fields"), dict)
                else {}
            )
            provided_result_status = raw_record.get("result_status")
            if (
                provided_result_status is not None
                and provided_result_status not in RESULT_STATUSES
            ):
                errors.append(
                    f"{label} result_status 不受支持: "
                    f"{provided_result_status!r}"
                )
                continue
            result_status = provided_result_status or normalize_result_status(
                query_status,
                len(normalized_candidates),
            )
            normalized_task_fields = {
                key: sanitize_raw(value)
                for key, value in task_fields.items()
            }
            for key in TASK_FIELD_KEYS:
                normalized_task_fields.setdefault(key, None)
            normalized_record = dict(sanitize_raw(raw_record))
            normalized_record.update(
                {
                    "result_schema_version": str(
                        raw_record.get("result_schema_version") or "legacy"
                    ),
                    "input_id": query_id,
                    "task_id": str(raw_record.get("task_id") or ""),
                    "person_id": (
                        raw_record.get("person_id")
                        or metadata_record.get("person_id")
                    ),
                    "query_stage": query_stage,
                    "query_status": query_status,
                    "result_status": result_status,
                    "candidate_count_total": (
                        raw_record.get("candidate_count_total")
                        if isinstance(
                            raw_record.get("candidate_count_total"),
                            int,
                        )
                        and not isinstance(
                            raw_record.get("candidate_count_total"),
                            bool,
                        )
                        else None
                    ),
                    "candidate_count_listed": len(normalized_candidates),
                    "detail_success_count": success_details,
                    "detail_failure_count": failed_details,
                    "task_fields": normalized_task_fields,
                    "raw": sanitize_raw(raw_value) if has_raw else {},
                    "raw_status": (
                        "COMPLETE_RAW" if has_raw else "LEGACY_PARTIAL_RAW"
                    ),
                    "results": normalized_candidates,
                }
            )
            normalized.append(normalized_record)
        return normalized, errors

    def _normalize_failure_records(
        self,
        records: list[Any],
        initial_errors: list[str],
        metadata: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """统一旧版与 v1.3 failures.jsonl，并补全失败 Query 的配对元数据。

        参数说明:
            records: failures.jsonl 解析后的原始记录。
            initial_errors: JSONL 读取阶段已经发现的错误。
            metadata: 可选 Query 元数据索引；失败记录没有 results 行时，用其
                保留 ``person_id`` 和 ``query_stage``。

        返回值:
            规范化失败记录和全部校验错误。
        """

        normalized: list[dict[str, Any]] = []
        errors = list(initial_errors)
        metadata = metadata or {}
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                errors.append(f"失败记录第 {index} 条必须是对象")
                continue
            query_id = record.get("input_id") or record.get("query_id")
            if not isinstance(query_id, str) or not query_id:
                errors.append(f"失败记录第 {index} 条缺少 input_id/query_id")
                continue
            candidate_id = str(record.get("candidate_id") or "")
            stage = str(record.get("stage") or "Import")
            scope = record.get("scope")
            if scope not in {"INPUT", "QUERY", "CANDIDATE", "IMPORT", "PROCESS"}:
                scope = (
                    "CANDIDATE"
                    if candidate_id
                    else ("INPUT" if stage == "Input" else "QUERY")
                )
            metadata_record = metadata.get(query_id, {})
            person_id = metadata_record.get("person_id")
            query_stage = metadata_record.get("query_stage")
            normalized.append(
                {
                    "input_id": query_id,
                    "person_id": (
                        person_id
                        if isinstance(person_id, str) and person_id
                        else None
                    ),
                    "query_stage": (
                        query_stage
                        if query_stage in SUPPORTED_QUERY_STAGES
                        else None
                    ),
                    "task_id": str(record.get("task_id") or ""),
                    "candidate_id": candidate_id,
                    "scope": scope,
                    "stage": stage,
                    "error": str(record.get("error") or ""),
                    "raw": sanitize_raw(record.get("raw")),
                    "created_at": record.get("created_at") or utc_now_text(),
                }
            )
        return normalized, errors

    def import_results_jsonl(
        self,
        results_path: Path | str,
        *,
        evaluation_id: str,
        run_label: str,
        system_version: str,
        evaluation_phase: str = "UNSPECIFIED",
        failures_path: Path | str | None = None,
        metadata_path: Path | str | None = None,
        run_id: str | None = None,
    ) -> ImportResult:
        """导入旧版或 v1.3 results/failures/metadata JSONL 文件包。"""

        results = self._source_path(results_path, {".jsonl"})
        failures = (
            self._source_path(failures_path, {".jsonl"})
            if failures_path is not None
            else None
        )
        metadata_file = (
            self._source_path(metadata_path, {".jsonl"})
            if metadata_path is not None
            else None
        )
        result_values, result_errors = read_jsonl(results)
        failure_values, failure_errors = (
            read_jsonl(failures) if failures is not None else ([], [])
        )
        metadata, metadata_errors = self._metadata_records(metadata_file)
        normalized_results, result_errors = self._normalize_result_records(
            result_values,
            metadata,
            [*result_errors, *metadata_errors],
        )
        normalized_failures, failure_errors = self._normalize_failure_records(
            failure_values,
            failure_errors,
            metadata,
        )
        sources = [("results", results)]
        if failures is not None:
            sources.append(("failures", failures))
        if metadata_file is not None:
            sources.append(("metadata", metadata_file))
        return self._import_run(
            normalized_results,
            normalized_failures,
            [*result_errors, *failure_errors],
            sources=sources,
            evaluation_id=evaluation_id,
            run_label=run_label,
            system_version=system_version,
            evaluation_phase=evaluation_phase,
            source_type="JSONL_IMPORT",
            run_id=run_id,
        )

    def _raw_chunk_values(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[dict[tuple[str, str, str, str], Any], list[str]]:
        """校验并重组 Raw数据 Sheet 分块。"""

        grouped: dict[
            tuple[str, str, str, str],
            list[tuple[int, int, str]],
        ] = defaultdict(list)
        errors: list[str] = []
        for row in rows:
            key = (
                str(row.get("run_label") or ""),
                str(row.get("query_id") or ""),
                str(row.get("candidate_id") or ""),
                str(row.get("field_name") or ""),
            )
            try:
                index = int(row.get("chunk_index"))
                total = int(row.get("chunk_total"))
            except (TypeError, ValueError):
                errors.append(f"Raw数据第 {row['_row_number']} 行分块序号无效")
                continue
            grouped[key].append((index, total, str(row.get("content") or "")))
        restored: dict[tuple[str, str, str, str], Any] = {}
        for key, chunks in grouped.items():
            totals = {item[1] for item in chunks}
            if len(totals) != 1:
                errors.append(f"Raw数据分块总数不一致: {key}")
                continue
            total = totals.pop()
            ordered = sorted(chunks)
            if [item[0] for item in ordered] != list(range(1, total + 1)):
                errors.append(f"Raw数据分块不完整: {key}")
                continue
            restored[key] = cell_value("".join(item[2] for item in ordered))
        return restored, errors

    def import_results_excel(
        self,
        source: Path | str,
        *,
        evaluation_id: str,
        run_label: str,
        system_version: str,
        evaluation_phase: str = "UNSPECIFIED",
        run_id: str | None = None,
    ) -> ImportResult:
        """导入项目规范化 Excel 的候选、Query、失败和 Raw 分块。"""

        path = self._source_path(source, {".xlsx"})
        workbook = load_workbook(
            path,
            read_only=True,
            data_only=True,
            keep_links=False,
        )
        try:
            candidates, candidate_errors = self._excel_rows(
                workbook,
                "候选结果",
                {"query_id", "task_id", "candidate_id", "candidate_rank"},
            )
            queries, query_errors = self._excel_rows(
                workbook,
                "Query对比",
                {"query_id"},
                optional=True,
            )
            failures, failure_errors = self._excel_rows(
                workbook,
                "失败记录",
                {"query_id", "task_id", "stage", "error"},
                optional=True,
            )
            raw_rows, raw_errors = self._excel_rows(
                workbook,
                "Raw数据",
                {
                    "run_label",
                    "query_id",
                    "candidate_id",
                    "field_name",
                    "chunk_index",
                    "chunk_total",
                    "content",
                },
                optional=True,
            )
        finally:
            workbook.close()
        restored_raw, chunk_errors = self._raw_chunk_values(raw_rows)
        errors = [
            *candidate_errors,
            *query_errors,
            *failure_errors,
            *raw_errors,
            *chunk_errors,
        ]
        selected = [
            row
            for row in candidates
            if not row.get("run_label") or str(row.get("run_label")) == run_label
        ]
        selected_queries = [
            row
            for row in queries
            if not row.get("run_label")
            or str(row.get("run_label")) == run_label
        ]
        if not selected and not selected_queries:
            errors.append(f"候选结果中没有 run_label={run_label!r} 的记录")
        grouped_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
        candidate_ranks: dict[str, set[int]] = defaultdict(set)
        metadata: dict[str, dict[str, Any]] = {}
        task_ids: dict[str, str] = {}
        candidate_totals: dict[str, Any] = {}
        task_fields_by_query: dict[str, dict[str, Any]] = {}
        for row in selected:
            query_id = str(row.get("query_id") or "")
            candidate_id = str(row.get("candidate_id") or "")
            try:
                rank = int(row.get("candidate_rank"))
            except (TypeError, ValueError):
                errors.append(f"候选结果第 {row['_row_number']} 行 candidate_rank 无效")
                continue
            if not query_id or not candidate_id or rank <= 0:
                errors.append(
                    f"候选结果第 {row['_row_number']} 行必需标识为空或 rank 无效"
                )
                continue
            if rank in candidate_ranks[query_id]:
                errors.append(
                    f"候选结果第 {row['_row_number']} 行 candidate_rank 重复"
                )
                continue
            candidate_ranks[query_id].add(rank)
            excel_fields = {
                key: cell_value(value)
                for key, value in row.items()
                if key != "_row_number" and value not in (None, "")
            }
            for key, value in restored_raw.items():
                raw_run, raw_query, raw_candidate, field_name = key
                if (
                    raw_run in {"", run_label}
                    and raw_query == query_id
                    and raw_candidate == candidate_id
                ):
                    excel_fields[field_name] = value
            grouped_candidates[query_id].append(
                {
                    "candidate_rank": rank,
                    "candidate_id": candidate_id,
                    "rank_score": (
                        row.get("rank_score")
                        if isinstance(row.get("rank_score"), (int, float))
                        and not isinstance(row.get("rank_score"), bool)
                        else None
                    ),
                    "detail_status": "SUCCESS",
                    "detail_error": "",
                    "list_item_raw": {
                        "candidate_id": candidate_id,
                        "rank_score": row.get("rank_score"),
                    },
                    "detail_data_raw": {
                        "source_type": "EXCEL_IMPORT",
                        "fields": excel_fields,
                    },
                    "ui_sections": {
                        "_excel_import": {
                            "status": "LEGACY_STRUCTURED_DATA",
                            "data": excel_fields,
                        }
                    },
                }
            )
            task_ids[query_id] = str(row.get("task_id") or "")
            candidate_totals[query_id] = row.get("candidate_count_total")
            task_fields_by_query.setdefault(
                query_id,
                {
                    key: cell_value(row.get(key))
                    for key in TASK_FIELD_KEYS
                    if row.get(key) not in (None, "")
                },
            )
            query_type = row.get("query_type")
            metadata[query_id] = {
                "person_id": row.get("person_id"),
                "query_stage": (
                    query_type if query_type in SUPPORTED_QUERY_STAGES else None
                ),
            }
        query_statuses: dict[str, str] = {}
        result_statuses: dict[str, str] = {}
        for row in selected_queries:
            query_id = str(row.get("query_id") or "")
            status = (
                row.get("current_status")
                or row.get("candidate_status")
                or row.get("baseline_status")
            )
            if status in {
                "SUCCESS",
                "NO_CANDIDATE",
                "PARTIAL_DETAIL_FAILED",
                "FAILED",
            }:
                query_statuses[query_id] = status
            result_status = row.get("result_status")
            if result_status not in (None, ""):
                if result_status not in RESULT_STATUSES:
                    errors.append(
                        f"Query对比第 {row['_row_number']} 行 "
                        f"result_status 不受支持"
                    )
                else:
                    result_statuses[query_id] = str(result_status)
            query_task_fields = task_fields_by_query.setdefault(query_id, {})
            for key in TASK_FIELD_KEYS:
                if row.get(key) not in (None, ""):
                    query_task_fields[key] = cell_value(row.get(key))
            metadata.setdefault(
                query_id,
                {
                    "person_id": row.get("person_id"),
                    "query_stage": (
                        row.get("query_type")
                        if row.get("query_type") in SUPPORTED_QUERY_STAGES
                        else None
                    ),
                },
            )
        result_records = []
        all_query_ids = set(grouped_candidates) | {
            query_id
            for query_id, status in query_statuses.items()
            if status != "FAILED"
        }
        for query_id in sorted(all_query_ids):
            items = sorted(
                grouped_candidates.get(query_id, []),
                key=lambda item: item["candidate_rank"],
            )
            query_status = query_statuses.get(
                query_id,
                "SUCCESS" if items else "NO_CANDIDATE",
            )
            task_fields = {
                key: task_fields_by_query.get(query_id, {}).get(key)
                for key in TASK_FIELD_KEYS
            }
            result_records.append(
                {
                    "result_schema_version": "excel-legacy",
                    "input_id": query_id,
                    "task_id": task_ids.get(query_id, ""),
                    "person_id": metadata.get(query_id, {}).get("person_id"),
                    "query_stage": metadata.get(query_id, {}).get("query_stage"),
                    "query_status": query_status,
                    "result_status": result_statuses.get(
                        query_id,
                        normalize_result_status(query_status, len(items)),
                    ),
                    "candidate_count_total": candidate_totals.get(query_id),
                    "candidate_count_listed": len(items),
                    "detail_success_count": len(items),
                    "detail_failure_count": 0,
                    "task_fields": task_fields,
                    "raw": {},
                    "raw_status": "LEGACY_PARTIAL_RAW",
                    "results": items,
                }
            )
        failure_records = []
        for row in failures:
            if row.get("run_label") and str(row.get("run_label")) != run_label:
                continue
            failure_records.append(
                {
                    "input_id": str(row.get("query_id") or ""),
                    "task_id": str(row.get("task_id") or ""),
                    "candidate_id": str(row.get("candidate_id") or ""),
                    "scope": (
                        "CANDIDATE" if row.get("candidate_id") else "QUERY"
                    ),
                    "stage": str(row.get("stage") or "Import"),
                    "error": str(row.get("error") or ""),
                    "raw": None,
                    "created_at": utc_now_text(),
                }
            )
        if errors:
            raise ImportValidationError(errors)
        return self._import_run(
            result_records,
            failure_records,
            [],
            sources=[("source", path)],
            evaluation_id=evaluation_id,
            run_label=run_label,
            system_version=system_version,
            evaluation_phase=evaluation_phase,
            source_type="EXCEL_IMPORT",
            run_id=run_id,
        )

    def _insert_raw(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        query_id: str,
        candidate_pk: str | None,
        stage: str,
        sequence_no: int,
        payload: Any,
        collected_at: str | None = None,
    ) -> None:
        """向 append-only Raw 表新增一条脱敏记录。"""

        connection.execute(
            """
            INSERT INTO raw_records(
                raw_id, run_id, query_id, candidate_pk, stage,
                sequence_no, payload_json, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"raw_{uuid.uuid4().hex}",
                run_id,
                query_id,
                candidate_pk,
                stage,
                sequence_no,
                json_text(payload),
                collected_at or utc_now_text(),
            ),
        )

    def _insert_result_raw(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        record: dict[str, Any],
        candidate_pks: list[tuple[str, dict[str, Any]]],
        source_type: str,
    ) -> None:
        """把 v1.3 Raw 拆为可查询记录，旧数据写明确缺失标记。"""

        query_id = record["input_id"]
        if record["raw_status"] != "COMPLETE_RAW":
            self._insert_raw(
                connection,
                run_id=run_id,
                query_id=query_id,
                candidate_pk=None,
                stage="Import",
                sequence_no=1,
                payload={
                    "raw_status": "LEGACY_PARTIAL_RAW",
                    "source_type": source_type,
                },
            )
            return
        raw = record["raw"]
        stage_items = [
            ("CreateIntentTask", raw.get("create_intent_task")),
            *[
                ("GetTask", item)
                for item in raw.get("get_task_history", [])
                if isinstance(item, dict)
            ],
            ("ListTaskCandidates", raw.get("list_task_candidates")),
        ]
        stage_sequences: dict[str, int] = defaultdict(int)
        for stage, payload in stage_items:
            if not isinstance(payload, dict) or not payload:
                continue
            stage_sequences[stage] += 1
            self._insert_raw(
                connection,
                run_id=run_id,
                query_id=query_id,
                candidate_pk=None,
                stage=stage,
                sequence_no=int(
                    payload.get("sequence_no") or stage_sequences[stage]
                ),
                payload=payload,
                collected_at=payload.get("collected_at"),
            )
        for candidate_pk, candidate in candidate_pks:
            detail_payload = candidate.get("detail_response_raw")
            if detail_payload is None:
                detail_payload = candidate.get("detail_data_raw")
            if detail_payload is None:
                continue
            self._insert_raw(
                connection,
                run_id=run_id,
                query_id=query_id,
                candidate_pk=candidate_pk,
                stage="GetTaskCandidateDetail",
                sequence_no=candidate["candidate_rank"],
                payload=detail_payload,
            )

    def _import_run(
        self,
        result_records: list[dict[str, Any]],
        failure_records: list[dict[str, Any]],
        errors: list[str],
        *,
        sources: list[tuple[str, Path]],
        evaluation_id: str,
        run_label: str,
        system_version: str,
        evaluation_phase: str,
        source_type: str,
        run_id: str | None,
    ) -> ImportResult:
        """执行 JSONL/Excel Run 共用的归档、规范化和单事务写入。"""

        if errors:
            raise ImportValidationError(errors)
        if not result_records and not failure_records:
            raise ImportValidationError(["结果文件没有可导入记录"])
        if evaluation_phase not in EVALUATION_PHASES:
            raise ImportValidationError(
                [f"evaluation_phase 不受支持: {evaluation_phase}"]
            )
        if self.store.fetch_one(
            "SELECT evaluation_id FROM evaluations WHERE evaluation_id = ?",
            (evaluation_id,),
        ) is None:
            raise ImportValidationError([f"Evaluation 不存在: {evaluation_id}"])
        validate_storage_id(evaluation_id, "evaluation_id")
        object_id = validate_storage_id(
            run_id or f"run_{uuid.uuid4().hex}",
            "run_id",
        )
        checksum = file_checksum(sources)
        if self.store.fetch_one(
            "SELECT run_id FROM runs WHERE source_checksum = ?",
            (checksum,),
        ):
            raise DuplicateImportError("相同结果文件包已经导入")
        archive_dir, archived = self._archive_sources(object_id, sources)
        normalized_dir = self.raw_dir / evaluation_id / object_id
        if normalized_dir.exists():
            self._cleanup_created(archive_dir)
            raise DuplicateImportError(f"规范化目录已存在: {normalized_dir}")
        normalized_results_path = normalized_dir / "results.jsonl"
        normalized_failures_path = normalized_dir / "failures.jsonl"
        self._write_jsonl(normalized_results_path, result_records)
        self._write_jsonl(normalized_failures_path, failure_records)
        now = utc_now_text()
        result_by_query = {
            record["input_id"]: record for record in result_records
        }
        failures_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for failure in failure_records:
            failures_by_query[failure["input_id"]].append(failure)
        query_ids = list(result_by_query)
        query_ids.extend(
            query_id
            for query_id in failures_by_query
            if query_id not in result_by_query
        )
        query_statuses = []
        for query_id in query_ids:
            record = result_by_query.get(query_id)
            if record is None:
                query_statuses.append("FAILED")
            else:
                query_statuses.append(record["query_status"])
        success_count = sum(
            status in {"SUCCESS", "NO_CANDIDATE"} for status in query_statuses
        )
        failed_count = len(query_statuses) - success_count
        if failed_count == len(query_statuses):
            run_status = "FAILED"
        elif failed_count:
            run_status = "PARTIAL_FAILED"
        else:
            run_status = "COMPLETED"
        raw_statuses = {
            record.get("raw_status", "LEGACY_PARTIAL_RAW")
            for record in result_records
        }
        message = (
            "LEGACY_PARTIAL_RAW"
            if "LEGACY_PARTIAL_RAW" in raw_statuses
            else ""
        )
        schema_versions = {
            str(record.get("result_schema_version") or "legacy")
            for record in result_records
        }
        if RESULT_SCHEMA_VERSION in schema_versions:
            schema_version = RESULT_SCHEMA_VERSION
        elif schema_versions:
            schema_version = sorted(schema_versions)[0]
        else:
            schema_version = "legacy"
        try:
            with self.store.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO runs(
                        run_id, evaluation_id, dataset_id, run_label,
                        system_version, source_type, status,
                        result_schema_version, results_file, failures_file,
                        source_checksum, total_queries, success_queries,
                        failed_queries, started_at, finished_at, message,
                        evaluation_phase, created_at
                    ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        object_id,
                        evaluation_id,
                        run_label,
                        system_version,
                        source_type,
                        run_status,
                        schema_version,
                        normalized_results_path.relative_to(
                            self.data_dir
                        ).as_posix(),
                        normalized_failures_path.relative_to(
                            self.data_dir
                        ).as_posix(),
                        checksum,
                        len(query_ids),
                        success_count,
                        failed_count,
                        now,
                        now,
                        message,
                        evaluation_phase,
                        now,
                    ),
                )
                for query_id in query_ids:
                    record = result_by_query.get(query_id)
                    query_failures = failures_by_query.get(query_id, [])
                    if record is None:
                        first_failure = (
                            query_failures[0] if query_failures else {}
                        )
                        task_id = (
                            first_failure.get("task_id", "")
                        )
                        status = "FAILED"
                        current_stage = (
                            first_failure.get("stage", "Import")
                        )
                        error = (
                            first_failure.get("error", "缺少结果记录")
                        )
                        person_id = first_failure.get("person_id")
                        query_stage = first_failure.get("query_stage")
                        candidate_total = None
                        candidate_listed = 0
                        detail_success = 0
                        detail_failure = 0
                        task_fields: dict[str, Any] = {}
                        result_status = "EXECUTION_FAILED"
                    else:
                        task_id = record["task_id"]
                        status = record["query_status"]
                        current_stage = (
                            query_failures[0]["stage"]
                            if query_failures
                            else (
                                "Import"
                                if record["raw_status"] == "LEGACY_PARTIAL_RAW"
                                else ""
                            )
                        )
                        error = (
                            query_failures[0]["error"]
                            if status == "FAILED" and query_failures
                            else ""
                        )
                        person_id = record.get("person_id")
                        query_stage = record.get("query_stage")
                        candidate_total = record.get("candidate_count_total")
                        candidate_listed = record["candidate_count_listed"]
                        detail_success = record["detail_success_count"]
                        detail_failure = record["detail_failure_count"]
                        task_fields = record.get("task_fields", {})
                        result_status = record["result_status"]
                    public_fields = {
                        key: value
                        for key, value in task_fields.items()
                        if key not in TASK_FIELD_KEYS
                    }
                    connection.execute(
                        """
                        INSERT INTO run_queries(
                            run_id, query_id, person_id, query_stage, task_id,
                            status, current_stage, candidate_count_total,
                            candidate_count_listed, detail_success_count,
                            detail_failure_count, llm_cost, third_party_cost,
                            total_cost, pdl_called, search_duration_ms,
                            result_status, public_fields_json, error,
                            started_at, finished_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            object_id,
                            query_id,
                            person_id,
                            query_stage,
                            task_id,
                            status,
                            current_stage,
                            candidate_total,
                            candidate_listed,
                            detail_success,
                            detail_failure,
                            task_fields.get("llm_cost"),
                            task_fields.get("third_party_cost"),
                            task_fields.get("total_cost"),
                            task_fields.get("pdl_called"),
                            task_fields.get("search_duration_ms"),
                            result_status,
                            json_text(public_fields),
                            error,
                            now,
                            now,
                        ),
                    )
                    candidate_pks: list[tuple[str, dict[str, Any]]] = []
                    if record is not None:
                        for candidate in record["results"]:
                            candidate_pk = f"candidate_{uuid.uuid4().hex}"
                            candidate_pks.append((candidate_pk, candidate))
                            connection.execute(
                                """
                                INSERT INTO candidates(
                                    candidate_pk, run_id, query_id,
                                    candidate_id, candidate_rank, rank_score,
                                    detail_status, detail_error,
                                    ui_sections_json, detail_data_json,
                                    list_item_json, created_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    candidate_pk,
                                    object_id,
                                    query_id,
                                    candidate["candidate_id"],
                                    candidate["candidate_rank"],
                                    candidate["rank_score"],
                                    candidate["detail_status"],
                                    candidate["detail_error"],
                                    (
                                        json_text(candidate["ui_sections"])
                                        if candidate.get("ui_sections") is not None
                                        else None
                                    ),
                                    (
                                        json_text(candidate["detail_data_raw"])
                                        if candidate.get("detail_data_raw") is not None
                                        else None
                                    ),
                                    json_text(candidate["list_item_raw"]),
                                    now,
                                ),
                            )
                        self._insert_result_raw(
                            connection,
                            run_id=object_id,
                            record=record,
                            candidate_pks=candidate_pks,
                            source_type=source_type,
                        )
                    else:
                        self._insert_raw(
                            connection,
                            run_id=object_id,
                            query_id=query_id,
                            candidate_pk=None,
                            stage="Import",
                            sequence_no=1,
                            payload={
                                "raw_status": "LEGACY_PARTIAL_RAW",
                                "source_type": source_type,
                            },
                        )
                for failure in failure_records:
                    connection.execute(
                        """
                        INSERT INTO failures(
                            failure_id, run_id, query_id, candidate_id,
                            scope, stage, error, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"failure_{uuid.uuid4().hex}",
                            object_id,
                            failure["input_id"],
                            failure["candidate_id"],
                            failure["scope"],
                            failure["stage"],
                            failure["error"],
                            failure["created_at"],
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            self._cleanup_created(archive_dir, normalized_dir)
            if "source_checksum" in str(exc).lower():
                raise DuplicateImportError("相同结果文件包已经导入") from exc
            raise
        except Exception:
            self._cleanup_created(archive_dir, normalized_dir)
            raise
        return ImportResult(object_id, len(query_ids), checksum, archived)
