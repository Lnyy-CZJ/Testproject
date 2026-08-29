"""通用接口日志解析原语与 Gateway/PUT 传输解析。

本模块只负责日志行规范化、JSON 边界扫描和 Gateway 信封分层，不包含任何
People/Dating 领域规则，也不得导入 Flask、app.py 或领域分析模块。这样后续
分析器可以共享稳定的传输层能力，同时避免 Web 入口与业务解析器之间形成循环依赖。
"""

from __future__ import annotations

import json
import re


PARSER_VERSION = "gateway-log-v1"
MAX_SCAN_LINES = 100000

# Flutter 控制台会在真实日志内容前附加运行器信息，只移除首个匹配前缀。
CONSOLE_PREFIX_PATTERN = re.compile(r"^.*?\bflutter:\s?")
RE_LOGGER_PREFIX = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]\d+)\s*\|\s*(\w+)\s*\|\s*([\w.]+)\s*\|\s*"
)
RE_FLUTTER_TIMESTAMP = re.compile(r"\t(\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{4})\t")


def clean_log_line(line: str) -> str:
    """清除 Flutter 控制台前缀和日志框线，并保持 app 的历史清洗行为。

    参数:
        line: 单行原始日志。调用方应传入字符串，与原 ``app.clean_log_line``
            的输入约束一致。

    返回:
        清洗后的日志内容。框线起止行返回空字符串；内容行仅移除框线字符，
        不额外裁剪尾部空白，避免改变既有过滤与导出结果。
    """
    line = CONSOLE_PREFIX_PATTERN.sub("", line, count=1)
    stripped_line = line.lstrip()
    if stripped_line.startswith(("┌", "└")):
        return ""
    if line.startswith("│ "):
        return line[2:]
    if line.startswith("│"):
        return line[1:]
    return line.replace("│", "")


def normalize_log_lines(log_text):
    """规范化日志行，同时保留原始行号、文本和可用时间戳。

    返回列表中的每个普通字典均包含 ``line_no``、``raw``、``content``、
    ``json_text`` 和 ``timestamp``。这里只清理已知控制台/Logger 前缀，
    不删除原始行，确保上层分析器继续报告准确的输入行号。
    """
    lines = []
    for index, raw in enumerate(log_text.splitlines()):
        cleaned = clean_log_line(raw)
        timestamp = None
        logger_match = RE_LOGGER_PREFIX.match(cleaned)
        if logger_match:
            timestamp = logger_match.group(1).replace(",", ".")
            content = cleaned[logger_match.end():]
        else:
            content = cleaned
            flutter_match = RE_FLUTTER_TIMESTAMP.search(raw)
            if flutter_match:
                timestamp = flutter_match.group(1)
        lines.append(
            {
                "line_no": index + 1,
                "raw": raw,
                "content": content,
                "json_text": content,
                "timestamp": timestamp,
            }
        )
    return lines


def scan_json_block(lines, start_idx):
    """从指定下标扫描首个完整 JSON 对象或数组。

    返回 ``(value, end_idx, start_line, end_line, error)``。扫描器区分字符串
    内外的括号并处理反斜杠转义；JSON 开始前若出现非空白内容则立即报错，
    防止把后续无关日志误识别为当前 marker 的 payload。
    """
    depth = 0
    in_string = False
    escaped = False
    started = False
    buffer = []
    start_line = None
    limit = min(len(lines), start_idx + MAX_SCAN_LINES)
    for idx in range(start_idx, limit):
        text = lines[idx]["json_text"]
        for ch in text:
            if not started:
                if ch in "{[":
                    started = True
                    start_line = lines[idx]["line_no"]
                    depth = 1
                    buffer.append(ch)
                elif not ch.isspace():
                    return None, idx, None, None, "marker 后未找到 JSON 起始"
                continue
            buffer.append(ch)
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    raw_text = "".join(buffer)
                    try:
                        return json.loads(raw_text), idx, start_line, lines[idx]["line_no"], None
                    except ValueError as exc:
                        return None, idx, start_line, lines[idx]["line_no"], str(exc)
        if started:
            buffer.append("\n")
    if started:
        return None, limit - 1, start_line, None, "JSON 未闭合（可能被截断）"
    return None, limit - 1, None, None, "未找到 JSON"


def scan_named_json_block(lines, start_idx, assignment_name):
    """查找精确 ``assignment_name=`` 行并扫描其后的 JSON。

    搜索从 ``start_idx`` 开始，只有行内容以完全一致的赋值前缀开头才会
    命中；例如查找 ``body`` 时不会误取 ``headers=``、``xbody=`` 或
    ``body =``。为保留输入行号且不修改调用方数据，只复制命中行后再复用
    通用括号扫描器。

    返回值与 :func:`scan_json_block` 相同，其中 ``end_idx`` 仍是原始
    ``lines`` 列表中的下标。
    """
    assignment_prefix = f"{assignment_name}="
    limit = min(len(lines), start_idx + MAX_SCAN_LINES)
    for idx in range(start_idx, limit):
        text = lines[idx]["json_text"]
        if not text.startswith(assignment_prefix):
            continue

        scoped_lines = lines[idx:limit]
        scoped_lines[0] = dict(scoped_lines[0])
        scoped_lines[0]["json_text"] = text[len(assignment_prefix):]
        value, relative_end_idx, start_line, end_line, error = scan_json_block(scoped_lines, 0)
        return value, idx + relative_end_idx, start_line, end_line, error

    return None, limit - 1, None, None, f"未找到 {assignment_prefix} JSON"


def unwrap_gateway_envelope(payload: object) -> dict:
    """将 Gateway payload 投影为网关、请求、响应和业务数据四层。

    参数:
        payload: JSON 解码后的任意对象。

    返回:
        新建的普通字典。函数不会修改 ``payload``；非字典值作为 ``data``
        原样返回，缺失或类型错误的 requests/responses 统一为空列表。
    """
    if not isinstance(payload, dict):
        return {"gateway": None, "requests": [], "responses": [], "data": payload}
    return {
        "gateway": {
            "code": payload.get("code"),
            "message": payload.get("message"),
            "request_id": payload.get("request_id"),
            "trace_id": payload.get("trace_id"),
        },
        "requests": payload.get("requests") if isinstance(payload.get("requests"), list) else [],
        "responses": payload.get("responses") if isinstance(payload.get("responses"), list) else [],
        "data": payload.get("data") if "data" in payload else payload,
    }
