"""People Insight 检索日志可选 AI 总结适配（设计 §11~§12，阶段 4）。

职责：
- 读取环境变量配置（endpiont / model / key file / timeout / packet 上限）。
- 读取版本化 Skill 提示词 `skills/people-search-log-analyzer/SKILL.md` 并去除 frontmatter。
- 发送前对 Evidence Packet 进行字节上限裁剪并标记 truncated。
- 使用 urllib.request 调用 OpenAI-compatible `/chat/completions`，不新增 SDK。
- 20 秒超时、不重试、不切换模型，失败统一降级为 ai.status=FAILED + error_code。
- AI 文本只附加在 Markdown 报告末尾，不修改规则结论。

关键设计点：
- 默认完全禁用，必须显式开启 `PEOPLE_SEARCH_ANALYZER_AI_ENABLED=true`。
- 单次分析最多一次模型调用。
- 任何网络、超时、解析失败都返回规则报告，AI 状态携带错误原因。
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

from people_search_rules import build_evidence_packet

# ---------------------------------------------------------------------------
# 常量与默认值（设计 §12.2）
# ---------------------------------------------------------------------------

SKILL_VERSION = "2026-08-13"
SKILL_PATH = (
    Path(__file__).with_name("skills")
    / "people-search-log-analyzer"
    / "SKILL.md"
)

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.MULTILINE | re.DOTALL
)

DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_EVIDENCE_BYTES = 524_288  # 512 KiB


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class AIConfig:
    ai_enabled: bool = False
    endpoint: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_evidence_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES

    @property
    def callable(self) -> bool:
        return bool(
            self.ai_enabled
            and self.endpoint
            and self.model
            and self.api_key
        )


def load_ai_config(environ=None, skill_path: Path = SKILL_PATH) -> AIConfig:
    """从环境变量加载 AI 配置。密钥不内联，只读文件路径（§12.2）。"""
    env = environ if environ is not None else os.environ
    cfg = AIConfig(
        ai_enabled=env.get(
            "PEOPLE_SEARCH_ANALYZER_AI_ENABLED", "false"
        ).lower() in ("1", "true", "yes", "on"),
        endpoint=env.get("PEOPLE_SEARCH_ANALYZER_LLM_ENDPOINT", "").strip() or None,
        model=env.get("PEOPLE_SEARCH_ANALYZER_LLM_MODEL", "").strip() or None,
        timeout_seconds=int(
            env.get("PEOPLE_SEARCH_ANALYZER_LLM_TIMEOUT_SECONDS", "")
            or DEFAULT_TIMEOUT_SECONDS
        ),
        max_evidence_bytes=int(
            env.get("PEOPLE_SEARCH_ANALYZER_MAX_EVIDENCE_BYTES", "")
            or DEFAULT_MAX_EVIDENCE_BYTES
        ),
    )
    key_file = env.get("PEOPLE_SEARCH_ANALYZER_LLM_API_KEY_FILE", "").strip()
    if key_file:
        try:
            cfg.api_key = Path(key_file).read_text(encoding="utf-8").strip() or None
        except OSError:
            cfg.api_key = None
    return cfg


# ---------------------------------------------------------------------------
# Skill 提示词
# ---------------------------------------------------------------------------


def load_skill_instruction(skill_path: Path = SKILL_PATH) -> str:
    """读取 Skill 文件，去除 YAML frontmatter，返回正文。

    解析失败时仅返回空字符串，调用方会视为未配置、跳过 AI。
    """
    try:
        text = skill_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = _FRONTMATTER_RE.match(text)
    if match:
        return match.group(2).rstrip()
    return text.rstrip()


# ---------------------------------------------------------------------------
# Evidence Packet 上限裁剪（§9.2、§12.3）
# ---------------------------------------------------------------------------


def _truncate_value(value: Any, quota: int):
    """优先对 Evidence Packet 中的大列表进行尾裁剪，并在顶层标记 truncated。"""
    if quota <= 0:
        return value, True

    # 先序列化得到当前体积，若不足上限直接返回
    current = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    if current <= quota:
        return value, False

    modified = False
    if isinstance(value, dict):
        # 1) 裁剪大列表字段（与 Evidence Packet 实际结构一致，审查修复）
        list_fields_by_priority = (
            "candidate_summary", "timeline",
            "social_url_decisions", "checks",
            "parse_warnings",
        )
        for field in list_fields_by_priority:
            arr = value.get(field)
            if not isinstance(arr, list) or not arr:
                continue
            new_len = max(1, len(arr) // 2)
            original = arr
            value = dict(value)
            value[field] = arr[:new_len]
            modified = True
            new_size = len(
                json.dumps(value, ensure_ascii=False).encode("utf-8")
            )
            if new_size <= quota:
                return value, True
            if not original:
                break

        # 2) 压缩顶层单文本字段（summary/actual/expected/title）
        for field in (
            "actual", "expected", "title",
            "summary", "notes", "report_markdown",
        ):
            txt = value.get(field)
            if isinstance(txt, str) and len(txt) > 200:
                value = dict(value)
                value[field] = txt[:200] + "…"
                modified = True
                if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) <= quota:
                    return value, True

        # 3) 递归裁剪对象值
        for k, v in list(value.items()):
            sub, sub_modified = _truncate_value(v, quota)
            if sub_modified:
                if not modified:
                    value = dict(value)
                value[k] = sub
                modified = True
                if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) <= quota:
                    return value, True
    elif isinstance(value, list) and len(value) > 1:
        new_len = max(1, len(value) // 2)
        value = value[:new_len]
        modified = True
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) <= quota:
            return value, True
        # 继续递归裁剪
        sub, sub_modified = _truncate_value(value, quota)
        if sub_modified:
            return sub, True
    return value, modified


def limit_evidence_packet(packet: dict, max_bytes: int) -> tuple[dict, bool]:
    """对 Evidence Packet 执行字节上限裁剪，并标记截断。

    同时设置 `truncated` 与 `source_truncated`（§9.3 字段名），
    提示模型证据不完整、不得给出“完全正常”结论。
    """
    packet = dict(packet)
    encoded = json.dumps(packet, ensure_ascii=False).encode("utf-8")
    if len(encoded) <= max_bytes:
        return packet, False

    truncated_packet, _ = _truncate_value(packet, max_bytes)
    truncated_packet = dict(truncated_packet)
    truncated_packet["truncated"] = True
    truncated_packet["source_truncated"] = True
    # 防止标记后仍超限，用更保守的配额再次检查
    encoded = json.dumps(truncated_packet, ensure_ascii=False).encode("utf-8")
    if len(encoded) > max_bytes:
        # 最后兜底：只保留核心字段
        core_keys = (
            "analyzer_version", "ruleset_version", "verdict",
            "task_summary", "coverage", "truncated", "source_truncated",
        )
        truncated_packet = {
            k: truncated_packet.get(k) for k in core_keys
            if k in truncated_packet
        }
        truncated_packet["truncated"] = True
        truncated_packet["source_truncated"] = True
    return truncated_packet, True


# ---------------------------------------------------------------------------
# 薄适配：urllib.request 调用 OpenAI-compatible /chat/completions
# ---------------------------------------------------------------------------


def _serialize_user_message(evidence_packet: dict) -> str:
    """Evidence Packet 序列化为紧凑 JSON，确保稳定且非缩进。"""
    return json.dumps(evidence_packet, ensure_ascii=False, separators=(",", ":"))


def _extract_assistant_content(response_data: Any) -> str:
    """从响应体中提取 assistant content，健壮兼容多种字段。"""
    if not isinstance(response_data, dict):
        raise ValueError("response not a JSON object")
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("response.choices missing or empty")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("response.choices[0] missing")
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    raise ValueError("response.choices[0].message.content missing")


def call_llm(
    skill_instruction: str,
    evidence_packet_json: str,
    cfg: AIConfig,
    _urlopen=None,
) -> tuple[Optional[str], dict]:
    """发起 LLM 调用。

    返回 (text, ai_status_dict)：
    - 成功：text 为 assistant 内容字符串；ai_status={status:"SUCCESS", model:..., truncated:bool}
    - 失败：text=None；ai_status={status:"FAILED", error_code:..., error_message:...}
    - 未配置：text=None；ai_status={status:"DISABLED"}
    """
    if not cfg.callable:
        return None, {"status": "DISABLED"}
    if not skill_instruction:
        return None, {
            "status": "FAILED",
            "error_code": "SKILL_MISSING",
            "error_message": "SKILL.md 未配置或读取失败",
        }

    urlopen = _urlopen or urlrequest.urlopen
    payload = json.dumps({
        "model": cfg.model,
        "temperature": 0.1,
        "max_tokens": 2000,
        "messages": [
            {"role": "system", "content": skill_instruction},
            {"role": "user", "content": evidence_packet_json},
        ],
    }).encode("utf-8")
    request = urlrequest.Request(
        cfg.endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=cfg.timeout_seconds) as response:
            body = response.read()
    except socket.timeout:
        return None, {
            "status": "FAILED",
            "error_code": "TIMEOUT",
            "error_message": f"LLM 调用超时（>={cfg.timeout_seconds}s）",
        }
    except urlerror.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = ""
        return None, {
            "status": "FAILED",
            "error_code": "HTTP_ERROR",
            "error_message": f"LLM 返回 HTTP {e.code}: {detail}",
        }
    except urlerror.URLError as e:
        return None, {
            "status": "FAILED",
            "error_code": "NETWORK_ERROR",
            "error_message": f"LLM 网络错误: {e.reason}",
        }
    except Exception as e:  # noqa: BLE001
        return None, {
            "status": "FAILED",
            "error_code": "TRANSPORT_ERROR",
            "error_message": f"LLM 调用异常: {type(e).__name__}",
        }

    try:
        response_data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, {
            "status": "FAILED",
            "error_code": "INVALID_RESPONSE",
            "error_message": f"LLM 返回非 JSON: {type(e).__name__}",
        }

    try:
        content = _extract_assistant_content(response_data)
    except ValueError as e:
        return None, {
            "status": "FAILED",
            "error_code": "INVALID_RESPONSE",
            "error_message": str(e),
        }

    return content, {
        "status": "SUCCESS",
        "model": cfg.model,
    }


# ---------------------------------------------------------------------------
# 高层 API：对分析结果生成 AI 总结（整合到路由调用）
# ---------------------------------------------------------------------------


def summarize_with_ai(
    analysis_result: dict,
    cfg: AIConfig,
    skill_instruction: str | None = None,
    _urlopen=None,
) -> tuple[Optional[str], dict, Optional[dict]]:
    """根据分析结果生成 AI 总结。

    返回 (ai_text, ai_status, evidence_packet_or_none)。
    - DISABLED / SKILL_MISSING：ai_text=None，evidence packet 为 None（未构造发送）。
    - 已发起调用（SUCCESS 或失败降级）：evidence packet 为实际发送（可能被截断）的数据。
    """
    if not cfg.callable:
        return None, {"status": "DISABLED"}, None

    instruction = (
        skill_instruction
        if skill_instruction is not None
        else load_skill_instruction()
    )
    if not instruction:
        return None, {
            "status": "FAILED",
            "error_code": "SKILL_MISSING",
        }, None

    # 构造 Evidence Packet 并裁剪到字节上限
    packet = build_evidence_packet(analysis_result)
    packet, truncated = limit_evidence_packet(packet, cfg.max_evidence_bytes)

    user_message = _serialize_user_message(packet)
    content, ai_status = call_llm(instruction, user_message, cfg, _urlopen=_urlopen)
    if truncated and ai_status.get("status") == "SUCCESS":
        ai_status = dict(ai_status)
        ai_status["truncated"] = True
    return content, ai_status, packet


def attach_ai_to_report(rule_report: str, ai_text: Optional[str]) -> str:
    """将 AI 总结附加在确定性规则报告末尾，明确作为“AI 说明”展示（§14.2）。

    规则报告是事实来源，AI 文本仅作为附加说明，不得覆盖任何规则结论。
    """
    if not ai_text:
        return rule_report
    clean = ai_text.rstrip() + "\n"
    return (
        rule_report.rstrip()
        + "\n\n## AI 说明\n\n"
        + clean
    )
