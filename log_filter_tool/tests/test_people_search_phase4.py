"""阶段 4：Skill 与可选 AI 适配测试（设计 §11~§12、§17.1 安全与 AI 测试）。

验证：
- AI 配置读取（含密钥文件）、未配置或未启用时 DISABLED 状态。
- Skill frontmatter 去除。
- 超时、HTTP 错、非法 JSON、空响应均降级为 FAILED + error_code。
- Evidence Packet 超过字节上限时标记 truncated，最终仍在限额内。
- 对外 checks 与 AI Evidence Packet 脱敏：Token→***，邮箱保留。
- AI 成功返回文本后，规则报告末尾追加「## AI 说明」。
- AI 失败时不修改规则报告内容。
- 路由级集成：AI 不启用不发网络请求；启用后调用 mock URL 并处理降级。
"""

from __future__ import annotations

import io
import json
import socket
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Optional
from urllib import error as urlerror

from app import create_app
from people_search_analyzer import analyze_log_file
from people_search_ai import (
    AIConfig,
    SKILL_VERSION,
    attach_ai_to_report,
    call_llm,
    limit_evidence_packet,
    load_ai_config,
    load_skill_instruction,
    summarize_with_ai,
)
from people_search_rules import build_evidence_packet, redact_for_response

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "people_search"


# ---------------------------------------------------------------------------
# Mock 辅助
# ---------------------------------------------------------------------------


@dataclass
class MockResponse:
    """模拟 urllib.response 兼容对象。"""

    body: bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class RecordingURLOpen:
    """记录调用参数，用于验证：请求未发起、请求 payload 格式符合预期。"""

    def __init__(self, status_or_error: Any = None, body_json: dict | None = None):
        """
        status_or_error: None 走 body_json；Exception 子类实例则被 raise；
                         int 视为 HTTP 码并触发 urlerror.HTTPError。
        """
        self.called: bool = False
        self.last_request: Optional[Any] = None
        self._status_or_error = status_or_error
        self._body_json = body_json or {
            "choices": [{"message": {"content": "AI 总结：未发现严重问题。"}}]
        }

    def __call__(self, request, timeout=None):
        self.called = True
        self.last_request = request
        if isinstance(self._status_or_error, Exception):
            raise self._status_or_error
        if isinstance(self._status_or_error, int) and self._status_or_error >= 400:
            raise urlerror.HTTPError(
                request.get_full_url(),
                self._status_or_error,
                "Upstream error",
                {},
                io.BytesIO(b'{"error":"bad request"}'),
            )
        payload = json.dumps(self._body_json).encode("utf-8")
        return MockResponse(payload)


class SequenceURLOpen:
    """按顺序返回 Context、规划和物化响应，并记录全部请求。"""

    def __init__(self, payloads: list[dict | Exception]):
        self.payloads = list(payloads)
        self.requests: list[Any] = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if not self.payloads:
            raise AssertionError("收到未预期的平台请求")
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return MockResponse(json.dumps(payload).encode("utf-8"))


# ---------------------------------------------------------------------------
# 配置与 Skill 加载
# ---------------------------------------------------------------------------


class AIConfigTests(unittest.TestCase):
    def test_load_ai_config_disabled_by_default(self):
        """未显式启用 AI 时 callable=False。"""
        cfg = load_ai_config(environ={})
        self.assertFalse(cfg.ai_enabled)
        self.assertFalse(cfg.callable)

    def test_load_ai_config_enabled_without_credentials_is_not_callable(self):
        """只开开关但缺 endpoint / model / key 时 callable=False。"""
        cfg = load_ai_config(environ={
            "PEOPLE_SEARCH_ANALYZER_AI_ENABLED": "true",
        })
        self.assertTrue(cfg.ai_enabled)
        self.assertFalse(cfg.callable)

    def test_load_ai_config_reads_key_file(self):
        """密钥以只读文件形式读取，不内联到环境变量。"""
        with NamedTemporaryFile("w", suffix=".key", delete=False, encoding="utf-8") as f:
            f.write("secret-api-key\n")
            key_path = f.name
        try:
            cfg = load_ai_config(environ={
                "PEOPLE_SEARCH_ANALYZER_AI_ENABLED": "true",
                "PEOPLE_SEARCH_ANALYZER_LLM_ENDPOINT": "https://example.com/v1/chat/completions",
                "PEOPLE_SEARCH_ANALYZER_LLM_MODEL": "my-model",
                "PEOPLE_SEARCH_ANALYZER_LLM_API_KEY_FILE": key_path,
            })
        finally:
            Path(key_path).unlink(missing_ok=True)

        self.assertTrue(cfg.callable)
        self.assertEqual(cfg.model, "my-model")
        self.assertEqual(cfg.api_key, "secret-api-key")
        self.assertEqual(cfg.endpoint, "https://example.com/v1/chat/completions")
        self.assertEqual(cfg.timeout_seconds, 20)
        self.assertEqual(cfg.max_evidence_bytes, 512 * 1024)

    def test_platform_source_reads_one_snapshot_without_env_fallback(self):
        """平台模式只使用内部快照，并保留日志工具的显式参数。"""
        with NamedTemporaryFile("w", delete=False, encoding="utf-8") as token_file:
            token_file.write("t" * 40)
            token_path = token_file.name
        opener = SequenceURLOpen([
            {
                "runtime_context_id": "rtx_log_user_1",
                "expires_at": "2026-08-24T12:00:00Z",
            },
            {
                "tool_id": "log-filter", "environment": "dev",
                "snapshot_selector": {
                    "release_id": "rel_log_v1",
                    "llm_capability": "people-search-summary",
                    "llm_binding_release_id": "rel_b",
                    "llm_profile_release_id": "rel_p",
                    "llm_secret_version_id": "secv_log_1",
                },
                "llm": {"status": "ready", "model": "shared-model"},
            },
            {
                "tool_id": "log-filter", "environment": "dev",
                "llm": {
                    "status": "ready", "base_url": "https://example.com/v1",
                    "model": "shared-model", "api_key": "platform-key",
                    "temperature": 0.1, "max_tokens": 3400, "timeout_seconds": 28,
                    "snapshot_id": "llms_test", "profile_release_id": "rel_p",
                    "binding_release_id": "rel_b",
                },
            },
        ])
        cfg = load_ai_config(environ={
            "LOG_FILTER_LLM_CONFIG_SOURCE": "platform",
            "PLATFORM_API_URL": "http://platform-api:8000/api/v1",
            "PLATFORM_CLIENT_TOKEN_FILE": token_path,
            "PLATFORM_RUNTIME_ENV": "dev",
            "PEOPLE_SEARCH_ANALYZER_AI_ENABLED": "true",
            "PEOPLE_SEARCH_ANALYZER_LLM_MODEL": "must-not-be-used",
        }, signed_user_context="signed-log-user-1", resource_id="request-log-1", _urlopen=opener)
        self.assertTrue(cfg.callable)
        self.assertEqual(cfg.model, "shared-model")
        self.assertEqual(cfg.endpoint, "https://example.com/v1/chat/completions")
        self.assertEqual((cfg.temperature, cfg.max_tokens, cfg.timeout_seconds), (0.1, 3400, 28))
        self.assertEqual(cfg.snapshot_id, "llms_test")
        self.assertEqual(3, len(opener.requests))
        self.assertTrue(opener.requests[0].full_url.endswith("/runtime-contexts"))
        self.assertEqual(
            "signed-log-user-1",
            opener.requests[0].get_header("X-platform-user-context"),
        )
        self.assertIn("include_secrets=false", opener.requests[1].full_url)
        self.assertTrue(opener.requests[2].full_url.endswith("/runtime-config/materialize"))

    def test_platform_source_failure_never_falls_back_to_env_key(self):
        """平台身份或配置失败时返回稳定错误，不能静默使用旧 Secret。"""
        cfg = load_ai_config(environ={
            "LOG_FILTER_LLM_CONFIG_SOURCE": "platform",
            "PEOPLE_SEARCH_ANALYZER_AI_ENABLED": "true",
            "PEOPLE_SEARCH_ANALYZER_LLM_ENDPOINT": "https://legacy.example/v1/chat/completions",
            "PEOPLE_SEARCH_ANALYZER_LLM_MODEL": "legacy-model",
            "PEOPLE_SEARCH_ANALYZER_LLM_API_KEY_FILE": "/legacy/key",
        })
        self.assertFalse(cfg.callable)
        self.assertEqual(cfg.config_error_code, "LLM_CONFIG_UNAVAILABLE")

    def test_platform_source_preserves_personal_llm_error_code(self):
        """平台明确返回个人 LLM 未配置时，规则报告应保留该稳定错误码。"""

        with NamedTemporaryFile("w", delete=False, encoding="utf-8") as token_file:
            token_file.write("t" * 40)
            token_path = token_file.name
        platform_error = urlerror.HTTPError(
            "http://platform-api.invalid/runtime-config",
            409,
            "Conflict",
            {},
            io.BytesIO(
                json.dumps(
                    {
                        "code": "PERSONAL_LLM_NOT_CONFIGURED",
                        "message": "请先配置并发布个人 LLM 连接",
                    }
                ).encode("utf-8")
            ),
        )
        opener = SequenceURLOpen(
            [
                {
                    "runtime_context_id": "rtx_log_missing_llm",
                    "expires_at": "2026-08-24T12:00:00Z",
                },
                platform_error,
            ]
        )
        try:
            cfg = load_ai_config(
                environ={
                    "LOG_FILTER_LLM_CONFIG_SOURCE": "platform",
                    "PLATFORM_API_URL": "http://platform-api.invalid/api/v1",
                    "PLATFORM_CLIENT_TOKEN_FILE": token_path,
                    "PLATFORM_RUNTIME_ENV": "dev",
                    "PEOPLE_SEARCH_ANALYZER_AI_ENABLED": "true",
                },
                signed_user_context="signed-log-missing-llm",
                resource_id="request-log-missing-llm",
                _urlopen=opener,
            )
        finally:
            Path(token_path).unlink(missing_ok=True)

        self.assertFalse(cfg.callable)
        self.assertEqual("PERSONAL_LLM_NOT_CONFIGURED", cfg.config_error_code)


class SkillLoadingTests(unittest.TestCase):
    def test_skill_strips_frontmatter_and_keeps_body(self):
        skill = load_skill_instruction()
        self.assertTrue(skill.startswith("# People Search Log Analysis\n\n分析输入的结构化 Evidence Packet"))
        self.assertNotIn("name: people-search-log-analyzer", skill)
        self.assertNotIn("---", skill)

    def test_skill_contains_hard_constraints_and_output_sections(self):
        skill = load_skill_instruction()
        self.assertIn("硬性约束", skill)
        self.assertIn("日志不足，无法判断", skill)
        self.assertIn("face_comparison_status=not_performed 不等于相似度 0%", skill)
        self.assertIn("不新增「已确认异常」", skill)
        self.assertIn("不得把 microunit 换算", skill)


# ---------------------------------------------------------------------------
# LLM 薄适配降级
# ---------------------------------------------------------------------------


class CallLLMDegradationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = AIConfig(
            ai_enabled=True,
            endpoint="https://example.com/v1/chat/completions",
            model="m",
            api_key="k",
            timeout_seconds=5,
            max_evidence_bytes=2048,
        )

    def test_call_disabled_returns_disabled(self):
        _, status = call_llm("SKILL", "packet", AIConfig())
        self.assertEqual(status, {"status": "DISABLED"})

    def test_call_success_extracts_content(self):
        opener = RecordingURLOpen()
        content, status = call_llm("INST", "{}", self.cfg, _urlopen=opener)
        self.assertTrue(opener.called)
        self.assertEqual(status["status"], "SUCCESS")
        self.assertEqual(status["model"], "m")
        self.assertEqual(content, "AI 总结：未发现严重问题。")
        # 验证请求 payload 格式
        payload = json.loads(opener.last_request.data)
        self.assertEqual(payload["model"], "m")
        self.assertEqual(payload["temperature"], 0.1)
        self.assertEqual(payload["max_tokens"], 3400)
        messages = payload["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "INST")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "{}")
        # 验证 Header（urllib Request 通过 get_header 访问更可靠）
        req = opener.last_request
        self.assertEqual(req.get_header("Authorization"), "Bearer k")
        self.assertIn("application/json", req.get_header("Content-type") or "")

    def test_socket_timeout_graceful_degrade(self):
        opener = RecordingURLOpen(status_or_error=socket.timeout("timed out"))
        content, status = call_llm("INST", "{}", self.cfg, _urlopen=opener)
        self.assertIsNone(content)
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["error_code"], "TIMEOUT")

    def test_http_429_rate_limit_degrade(self):
        opener = RecordingURLOpen(status_or_error=429)
        content, status = call_llm("INST", "{}", self.cfg, _urlopen=opener)
        self.assertIsNone(content)
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["error_code"], "HTTP_ERROR")

    def test_invalid_json_response_degrade(self):
        opener = RecordingURLOpen()
        opener._body_json = None  # 触发 MockResponse 返回非 JSON
        # 直接模拟返回非 JSON 字节
        def non_json_open(request, timeout=None):
            opener.called = True
            opener.last_request = request
            return MockResponse(b"not json at all")
        content, status = call_llm("INST", "{}", self.cfg, _urlopen=non_json_open)
        self.assertIsNone(content)
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["error_code"], "INVALID_RESPONSE")

    def test_empty_choices_degrade(self):
        opener = RecordingURLOpen(body_json={"choices": []})
        content, status = call_llm("INST", "{}", self.cfg, _urlopen=opener)
        self.assertIsNone(content)
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["error_code"], "INVALID_RESPONSE")

    def test_length_truncated_response_degrades_to_rule_report(self):
        """模型达到输出上限时不得把半截回答作为成功结果展示。"""
        opener = RecordingURLOpen(body_json={
            "choices": [{
                "finish_reason": "length",
                "message": {"content": "未完成的分析"},
            }],
        })
        content, status = call_llm("INST", "{}", self.cfg, _urlopen=opener)
        self.assertIsNone(content)
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["error_code"], "OUTPUT_TRUNCATED")

    def test_url_error_network_unreachable_degrade(self):
        opener = RecordingURLOpen(
            status_or_error=urlerror.URLError(reason=OSError("host unreachable"))
        )
        content, status = call_llm("INST", "{}", self.cfg, _urlopen=opener)
        self.assertIsNone(content)
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["error_code"], "NETWORK_ERROR")


# ---------------------------------------------------------------------------
# Evidence Packet 截断
# ---------------------------------------------------------------------------


class EvidencePacketSizeTests(unittest.TestCase):
    def test_large_packet_is_truncated_and_kept_under_limit(self):
        packet = {
            "analyzer_version": "v1",
            "ruleset_version": SKILL_VERSION,
            "verdict": "NORMAL",
            "task_summary": {"full_name": "Alice", "clue_types": ["FULL_NAME"]},
            # 制造超大 JSON: 200 条 timeline
            "timeline": [
                {"provider": f"p{i}", "operation": f"op{i}", "status": "OK"}
                for i in range(200)
            ],
            # 再制造超大 candidate
            "candidate_summary": [
                {"name": f"cand{i}", "score": i, "source": f"src{i}" * 10}
                for i in range(50)
            ],
        }
        limited, truncated = limit_evidence_packet(packet, max_bytes=2048)
        size = len(json.dumps(limited, ensure_ascii=False).encode("utf-8"))
        self.assertLessEqual(size, 2048)
        self.assertTrue(truncated)
        self.assertTrue(limited.get("truncated"))
        # 核心元信息保留
        self.assertEqual(limited["verdict"], "NORMAL")

    def test_small_packet_is_not_modified(self):
        packet = {"a": 1, "b": [2, 3]}
        limited, truncated = limit_evidence_packet(packet, max_bytes=1024)
        self.assertFalse(truncated)
        self.assertNotIn("truncated", limited)


# ---------------------------------------------------------------------------
# 对外响应与 Evidence Packet 脱敏
# ---------------------------------------------------------------------------


class SanitizationTests(unittest.TestCase):
    def test_checks_response_redacts_token_keeps_email(self):
        checks = [{
            "rule_id": "STATE-001",
            "evidence": [
                {"json_path": "$.request.auth_token", "value": "tk-secret"},
                {"json_path": "$.candidates[0].email", "value": "carol@example.com"},
            ],
        }]
        redacted = redact_for_response(checks)
        self.assertEqual(
            redacted[0]["evidence"][0],
            {"json_path": "$.request.auth_token", "value": "***"},
        )
        self.assertEqual(
            redacted[0]["evidence"][1],
            {"json_path": "$.candidates[0].email", "value": "carol@example.com"},
        )

    def test_evidence_packet_contains_email_value_not_redacted(self):
        """§10.2 评审确认：邮箱保留原值。"""
        result = analyze_log_file(FIXTURE_DIR / "f06_social_link_queue_dedupe.log")
        packet = build_evidence_packet(result)
        serialized = json.dumps(packet, ensure_ascii=False)
        self.assertIn("carol@example.com", serialized)

    def test_evidence_packet_does_not_contain_original_auth_token_value(self):
        """§10.2：Authorization/Token 必须脱敏。"""
        result = analyze_log_file(FIXTURE_DIR / "f06_social_link_queue_dedupe.log")
        packet = build_evidence_packet(result)
        serialized = json.dumps(packet, ensure_ascii=False)
        self.assertNotIn("***_example_f06", serialized)


# ---------------------------------------------------------------------------
# summarize_with_ai 高层 API 与报告附加
# ---------------------------------------------------------------------------


class SummarizeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = AIConfig(
            ai_enabled=True,
            endpoint="https://example.com/v1/chat/completions",
            model="m",
            api_key="k",
            timeout_seconds=5,
            max_evidence_bytes=1024 * 1024,
        )
        self.result = analyze_log_file(FIXTURE_DIR / "f01_public_figure_local_hit.log")

    def test_disabled_does_not_call_network(self):
        opener = RecordingURLOpen()
        cfg = AIConfig()  # ai_enabled=False (default)
        text, status, pkt = summarize_with_ai(self.result, cfg, _urlopen=opener)
        self.assertFalse(opener.called)
        self.assertEqual(status, {"status": "DISABLED"})
        self.assertIsNone(text)

    def test_success_attaches_ai_section_to_report(self):
        from people_search_rules import render_rule_report

        report = render_rule_report(self.result)
        opener = RecordingURLOpen(body_json={
            "choices": [{"message": {"content": "AI 总体结论：Local 命中后路由正确。"}}]
        })
        text, status, _ = summarize_with_ai(
            self.result, self.cfg, skill_instruction="INST", _urlopen=opener
        )
        self.assertEqual(status["status"], "SUCCESS")
        combined = attach_ai_to_report(report, text)
        # 规则报告内容完整保留
        self.assertIn("# People Insight 检索日志分析", combined)
        self.assertIn("## 总体结论", combined)
        # AI 说明附加在末尾
        self.assertTrue(combined.rstrip().endswith("Local 命中后路由正确。"))
        self.assertIn("## AI 说明", combined)
        # AI 文本位置在规则各章之后
        ai_index = combined.index("## AI 说明")
        self.assertLess(combined.index("## 已确认正常"), ai_index)

    def test_failure_does_not_modify_rule_report(self):
        from people_search_rules import render_rule_report

        report = render_rule_report(self.result)
        opener = RecordingURLOpen(status_or_error=socket.timeout("timed out"))
        text, status, _ = summarize_with_ai(
            self.result, self.cfg, skill_instruction="INST", _urlopen=opener
        )
        self.assertEqual(status["error_code"], "TIMEOUT")
        self.assertIsNone(text)
        combined = attach_ai_to_report(report, text)
        # AI 失败时不追加“## AI 说明”章节
        self.assertNotIn("## AI 说明", combined)
        self.assertEqual(combined, report)


# ---------------------------------------------------------------------------
# Flask 路由级集成：AI 开关与降级行为
# ---------------------------------------------------------------------------


class AnalyzeRouteWithAITests(unittest.TestCase):
    def setUp(self):
        self.log = (FIXTURE_DIR / "f01_public_figure_local_hit.log").read_text(encoding="utf-8")

    def test_ai_disabled_returns_rule_report_with_ai_disabled(self):
        """AI 默认关闭，响应 ai.status=DISABLED，且不发网络请求。

        通过 RecordingURLOpen 未创建即断言为无网络请求，这由上一级
        summarize_with_ai 的 DISABLED 分支保证；此处只校验响应结构。
        """
        app = create_app()
        app.testing = True
        # 未设置 PEOPLE_SEARCH_ANALYZER_AI_ENABLED=true → 走 DISABLED
        resp = app.test_client().post(
            "/people-search/analyze", json={"log_text": self.log}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()["data"]
        self.assertEqual(data["ai"], {"status": "DISABLED"})
        self.assertNotIn("## AI 说明", data["report_markdown"])


if __name__ == "__main__":
    unittest.main()
