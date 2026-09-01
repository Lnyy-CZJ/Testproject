"""E2E JSON 与 Evaluation JSONL 的严格加载和本地校验。"""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
import json
import os
import re

from aidating_eval.domain import (
    CaseDefinition,
    CaseExpectation,
    E2EAnalysisCase,
    E2EReplyCase,
    EvaluationAnalysisCase,
    EvaluationReplyCase,
    NegativeVariant,
    ReplyPreferences,
    TranscriptMessage,
)
from aidating_eval.errors import CaseValidationError


CASE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
STABLE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
INTENTS = frozenset({"opener", "flirt", "tease", "advance"})
RESERVED_FIELDS = frozenset(
    {
        "model",
        "prompt",
        "app_id",
        "user_id",
        "service_name",
        "method_name",
        "task_id",
        "api_key",
    }
)
EXPECT_FIELDS = frozenset(
    {
        "task_status",
        "result_schema",
        "business_error_code",
        "warning_codes",
        "policy_codes",
    }
)
BASE_FIELDS = frozenset(
    {"schema_version", "case_id", "task_kind", "locale", "expect"}
)
E2E_FIELDS = BASE_FIELDS | {"media", "preferences", "reply", "analysis"}
EVAL_REPLY_FIELDS = BASE_FIELDS | {
    "transcript",
    "dating_goal",
    "your_voice",
    "requested_intent",
    "background",
    "negative_variant",
}
EVAL_ANALYSIS_FIELDS = BASE_FIELDS | {"transcript", "negative_variant"}
NEGATIVE_ERROR_CODES: dict[NegativeVariant, str | None] = {
    NegativeVariant.MESSAGE_COUNT_BELOW_MIN: "INPUT_INVALID",
    NegativeVariant.INSUFFICIENT_PARTY_MESSAGES: "INPUT_INVALID",
    NegativeVariant.DUPLICATE_MESSAGE_ID: "INPUT_INVALID",
    NegativeVariant.UNSUPPORTED_FIELD: "INPUT_INVALID",
    NegativeVariant.IDEMPOTENCY_SAME: None,
    NegativeVariant.IDEMPOTENCY_CONFLICT: "IDEMPOTENCY_CONFLICT",
}


def _fail(message: str) -> None:
    raise CaseValidationError(message)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{field} 必须为对象")
    return value


def _string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        _fail(f"{field} 必须为非空字符串")
    return value


def _check_unknown_fields(data: Mapping[str, Any], allowed: set[str] | frozenset[str]) -> None:
    unknown = set(data) - set(allowed)
    if unknown:
        _fail(f"存在不支持字段: {','.join(sorted(unknown))}")
    forbidden = set(data) & RESERVED_FIELDS
    if forbidden:
        _fail(f"存在保留字段: {','.join(sorted(forbidden))}")


def _expectation(data: object, kind: str) -> CaseExpectation:
    if data is None:
        return CaseExpectation(
            result_schema=(
                "dating.reply_generation.v1"
                if kind == "reply"
                else "dating.relationship_analysis.v1"
            )
        )
    value = _mapping(data, "expect")
    _check_unknown_fields(value, EXPECT_FIELDS)
    warning_codes = value.get("warning_codes", [])
    policy_codes = value.get("policy_codes", [])
    if not isinstance(warning_codes, list) or not all(
        isinstance(item, str) and item for item in warning_codes
    ):
        _fail("expect.warning_codes 必须为非空字符串数组")
    if not isinstance(policy_codes, list) or not all(
        isinstance(item, str) and item for item in policy_codes
    ):
        _fail("expect.policy_codes 必须为非空字符串数组")
    expectation = CaseExpectation(
        task_status=value.get("task_status", "succeeded"),
        result_schema=value.get(
            "result_schema",
            "dating.reply_generation.v1"
            if kind == "reply"
            else "dating.relationship_analysis.v1",
        ),
        business_error_code=value.get("business_error_code"),
        warning_codes=tuple(warning_codes),
        policy_codes=tuple(policy_codes),
    )
    for field_name in ("task_status", "result_schema", "business_error_code"):
        item = getattr(expectation, field_name)
        if item is not None and not isinstance(item, str):
            _fail(f"expect.{field_name} 必须为字符串或 null")
    return expectation


def _validate_common(data: Mapping[str, Any]) -> tuple[str, str, str, CaseExpectation]:
    if data.get("schema_version") not in {
        "aidating.e2e.case.v1",
        "aidating.eval.case.v1",
    }:
        _fail("Case schema_version 不受支持")
    case_id = _string(data.get("case_id"), "case_id")
    if not CASE_ID_RE.fullmatch(case_id):
        _fail("case_id 只能包含安全 ASCII 字符且长度为 1～80")
    kind = _string(data.get("task_kind"), "task_kind")
    if kind not in {"reply", "analysis"}:
        _fail("task_kind 必须为 reply 或 analysis")
    locale = _string(data.get("locale"), "locale")
    if len(locale) > 64:
        _fail("locale 最多 64 个字符")
    return case_id, kind, locale, _expectation(data.get("expect"), kind)


def _stable_code(value: object, field: str) -> str:
    code = _string(value, field)
    if not STABLE_CODE_RE.fullmatch(code):
        _fail(f"{field} 不是小写稳定 code")
    return code


def _media_paths(value: object, fixture_root: Path) -> tuple[Path, ...]:
    if not isinstance(value, list) or not value:
        _fail("media 至少包含一张图片")
    root = fixture_root.resolve()
    paths: list[Path] = []
    for index, item in enumerate(value):
        media = _mapping(item, f"media[{index}]")
        _check_unknown_fields(media, {"path"})
        raw_path = _string(media.get("path"), f"media[{index}].path")
        path = (root / raw_path).resolve()
        if not path.is_relative_to(root):
            _fail("媒体路径不得越出 Fixture Root")
        if not path.is_file() or not os.access(path, os.R_OK):
            _fail(f"媒体文件不存在或不可读: {raw_path}")
        paths.append(path)
    return tuple(paths)


def _parse_e2e(data: Mapping[str, Any], fixture_root: Path) -> CaseDefinition:
    if data.get("schema_version") != "aidating.e2e.case.v1":
        _fail("E2E Case 必须使用 aidating.e2e.case.v1")
    _check_unknown_fields(data, E2E_FIELDS)
    case_id, kind, locale, expect = _validate_common(data)

    if kind == "reply":
        if "preferences" not in data or "reply" not in data or "analysis" in data:
            _fail("Reply E2E 必须包含 preferences/reply 且不能包含 analysis")
        preferences = _mapping(data["preferences"], "preferences")
        _check_unknown_fields(preferences, {"dating_goal", "your_voice"})
        reply = _mapping(data["reply"], "reply")
        _check_unknown_fields(reply, {"requested_intent", "background"})
        intent = reply.get("requested_intent")
        if intent is not None and intent not in INTENTS:
            _fail("requested_intent 不受支持")
        background = reply.get("background")
        if background is not None:
            _string(background, "reply.background", allow_empty=True)
            if len(background) > 1000:
                _fail("reply.background 最多 1000 个 Unicode 字符")
        return E2EReplyCase(
            case_id=case_id,
            locale=locale,
            media_paths=_media_paths(data.get("media"), fixture_root),
            preferences=ReplyPreferences(
                dating_goal=_stable_code(
                    preferences.get("dating_goal"), "preferences.dating_goal"
                ),
                your_voice=_stable_code(
                    preferences.get("your_voice"), "preferences.your_voice"
                ),
            ),
            requested_intent=intent,
            background=background,
            expect=expect,
        )

    if "analysis" not in data or "preferences" in data or "reply" in data:
        _fail("Analysis E2E 必须包含 analysis 且不能包含 Reply 字段")
    analysis = _mapping(data["analysis"], "analysis")
    _check_unknown_fields(analysis, {"other_person_name", "background"})
    name = analysis.get("other_person_name")
    background = analysis.get("background")
    if name is not None:
        _string(name, "analysis.other_person_name", allow_empty=True)
    if background is not None:
        _string(background, "analysis.background", allow_empty=True)
    return E2EAnalysisCase(
        case_id=case_id,
        locale=locale,
        media_paths=_media_paths(data.get("media"), fixture_root),
        other_person_name=name,
        background=background,
        expect=expect,
    )


def _messages(value: object, kind: str) -> tuple[TranscriptMessage, ...]:
    transcript = _mapping(value, "transcript")
    _check_unknown_fields(transcript, {"schema_version", "messages"})
    if transcript.get("schema_version") != "dating.transcript.v1":
        _fail("transcript 必须使用 dating.transcript.v1")
    raw_messages = transcript.get("messages")
    if not isinstance(raw_messages, list):
        _fail("transcript.messages 必须为数组")
    maximum = 300 if kind == "reply" else 500
    if not 4 <= len(raw_messages) <= maximum:
        _fail(f"{kind} 消息数量必须为 4～{maximum}")

    parsed: list[TranscriptMessage] = []
    ids: set[str] = set()
    speakers = {"user": 0, "other": 0}
    for index, item in enumerate(raw_messages):
        message = _mapping(item, f"messages[{index}]")
        _check_unknown_fields(
            message, {"message_id", "message_type", "speaker", "text"}
        )
        message_id = _string(message.get("message_id"), f"messages[{index}].message_id")
        if message_id in ids:
            _fail("message_id 在任务内必须唯一")
        ids.add(message_id)
        if message.get("message_type") != "text":
            _fail("message_type 当前固定为 text")
        speaker = _string(message.get("speaker"), f"messages[{index}].speaker")
        if speaker == "self":
            speaker = "user"
        if speaker not in speakers:
            _fail("speaker 必须为 self/user/other")
        speakers[speaker] += 1
        text = _string(message.get("text"), f"messages[{index}].text", allow_empty=True)
        if kind == "analysis" and len(text.encode("utf-8")) > 4096:
            _fail("Analysis 单条消息最多 4096 UTF-8 字节")
        parsed.append(
            TranscriptMessage(
                message_id=message_id,
                message_type="text",
                speaker=speaker,
                text=text,
            )
        )
    if speakers["user"] < 2 or speakers["other"] < 2:
        _fail("user 和 other 双方至少各 2 条消息")
    if sum(len(item.text.encode("utf-8")) for item in parsed) > 131_072:
        _fail("聊天正文总计不得超过 131072 UTF-8 字节")
    return tuple(parsed)


def _negative_variant(data: Mapping[str, Any], expect: CaseExpectation) -> NegativeVariant | None:
    raw = data.get("negative_variant")
    if raw is None:
        return None
    try:
        variant = NegativeVariant(raw)
    except (ValueError, TypeError) as exc:
        raise CaseValidationError("negative_variant 不在受控枚举中") from exc
    expected_code = NEGATIVE_ERROR_CODES[variant]
    if expect.business_error_code != expected_code:
        _fail("negative_variant 与 expect.business_error_code 不匹配")
    if expected_code is not None and (
        expect.task_status is not None or expect.result_schema is not None
    ):
        _fail("预期 Create 业务错误时 task_status/result_schema 必须为 null")
    return variant


def _parse_eval(data: Mapping[str, Any]) -> CaseDefinition:
    if data.get("schema_version") != "aidating.eval.case.v1":
        _fail("Eval Case 必须使用 aidating.eval.case.v1")
    kind = data.get("task_kind")
    allowed = EVAL_REPLY_FIELDS if kind == "reply" else EVAL_ANALYSIS_FIELDS
    _check_unknown_fields(data, allowed)
    case_id, normalized_kind, locale, expect = _validate_common(data)
    messages = _messages(data.get("transcript"), normalized_kind)
    variant = _negative_variant(data, expect)

    if normalized_kind == "reply":
        intent = data.get("requested_intent")
        if intent is not None and intent not in INTENTS:
            _fail("requested_intent 不受支持")
        background = data.get("background")
        if background is not None:
            _string(background, "background", allow_empty=True)
            if len(background) > 1000:
                _fail("background 最多 1000 个 Unicode 字符")
        case = EvaluationReplyCase(
            case_id=case_id,
            locale=locale,
            messages=messages,
            dating_goal=_stable_code(data.get("dating_goal"), "dating_goal"),
            your_voice=_stable_code(data.get("your_voice"), "your_voice"),
            requested_intent=intent,
            background=background,
            negative_variant=variant,
            expect=expect,
        )
        _validate_positive_expectation(case)
        return case

    case = EvaluationAnalysisCase(
        case_id=case_id,
        locale=locale,
        messages=messages,
        negative_variant=variant,
        expect=expect,
    )
    params_probe = {
        "case_id": case_id,
        "run_id": "r" * 80,
        "client_request_id": "c" * 80,
        "locale": locale,
        "transcript": {
            "schema_version": "dating.transcript.v1",
            "messages": [item.__dict__ for item in messages],
        },
    }
    if len(
        json.dumps(params_probe, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ) > 262_144:
        _fail("Analysis params 估算超过 262144 UTF-8 字节")
    _validate_positive_expectation(case)
    return case


def _validate_positive_expectation(case: CaseDefinition) -> None:
    if case.expect.business_error_code is not None:
        return
    expected_schema = (
        "dating.reply_generation.v1"
        if case.task_kind == "reply"
        else "dating.relationship_analysis.v1"
    )
    if case.expect.result_schema != expected_schema:
        _fail("正向 Case 的 expect.result_schema 与 task_kind 不匹配")


def _read_e2e(path: Path) -> list[Mapping[str, Any]]:
    paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not paths or any(item.suffix != ".json" for item in paths):
        _fail("E2E dataset 必须是 JSON 文件或包含 JSON 的目录")
    values: list[Mapping[str, Any]] = []
    for item in paths:
        try:
            value = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CaseValidationError(f"无法读取 E2E Case: {item.name}") from exc
        values.append(_mapping(value, item.name))
    return values


def _read_eval(path: Path) -> list[Mapping[str, Any]]:
    if not path.is_file() or path.suffix != ".jsonl":
        _fail("Eval dataset 必须是 UTF-8 JSONL 文件")
    values: list[Mapping[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CaseValidationError("无法读取 Eval JSONL") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            _fail("Eval JSONL 不允许注释")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CaseValidationError(f"Eval JSONL 第 {line_number} 行不是合法 JSON") from exc
        values.append(_mapping(value, f"line {line_number}"))
    if not values:
        _fail("dataset 不包含 Case")
    return values


def load_cases(
    path: Path | str,
    mode: str,
    fixture_root: Path | str | None = None,
) -> list[CaseDefinition]:
    """加载并严格校验数据集，不产生任何网络或文件写入副作用。

    Args:
        path: E2E JSON/目录或 Evaluation JSONL。
        mode: ``e2e`` 或 ``eval``。
        fixture_root: E2E 媒体允许访问的唯一根目录；E2E 必填。

    Raises:
        CaseValidationError: 文件、字段或业务边界不符合冻结契约。
    """

    source = Path(path)
    if mode == "e2e":
        if fixture_root is None:
            _fail("E2E 必须显式提供 fixture_root")
        raw_cases = _read_e2e(source)
        cases = [_parse_e2e(item, Path(fixture_root)) for item in raw_cases]
    elif mode == "eval":
        raw_cases = _read_eval(source)
        cases = [_parse_eval(item) for item in raw_cases]
    else:
        _fail("mode 必须为 e2e 或 eval")

    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        _fail("case_id 在数据集内必须唯一")
    return cases
