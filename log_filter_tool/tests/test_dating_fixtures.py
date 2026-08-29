"""Dating 结构化日志黄金夹具的完整性与脱敏契约测试。"""

import hashlib
from pathlib import Path
import re
import unittest


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dating"

REPLY_FIXTURE_SHA256 = (
    "499c509cebd2a490689e506800d4a29ec90010bb062eb5f261230428456f9fd3"
)
ANALYSIS_FIXTURE_SHA256 = (
    "e220cd034456100075b6315f65bdc50badc269165cc4210a06f90bd83ec910a1"
)

SENSITIVE_PLACEHOLDERS = {
    "auth_token": "***",
    "Authorization": "***",
    "Cookie": "***",
    "user_id": "dating_user_fixture",
    "device_id": "dating_device_fixture",
}

# 只把 PRD 样本中的 Dating COS 资产地址视为签名 URL。这样既能精确约束签名
# 查询串，又不会把搜索、回调等普通业务 URL 的合法查询参数误判为泄露。
SIGNED_DATING_ASSET_QUERY_RE = re.compile(
    r"https://[A-Za-z0-9.-]+\.cos\.[A-Za-z0-9.-]+\.myqcloud\.com/"
    r"dating/staging/chat-screenshots/[^\"\s?]+\?([^\"\s]+)"
)

# 上传日志只应保留长度等元数据。显式拦截 data URI、超长 Base64 串及 Python
# bytes 字面量，避免后续更新夹具时意外提交图片正文或其他二进制内容。
INLINE_BASE64_RE = re.compile(
    r"data:[^;\s]+;base64,"
    r"|(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{256,}={0,2}(?![A-Za-z0-9+/=])",
    re.IGNORECASE,
)
PYTHON_BYTES_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:b|br|rb)[\"']",
    re.IGNORECASE,
)


class DatingFixtureTests(unittest.TestCase):
    """确保后续解析与分析测试始终使用完整、稳定且无敏感信息的夹具。"""

    def _assert_sanitization_gate(
        self,
        text,
        *,
        expected_sensitive_counts,
        expected_signed_url_count,
    ):
        """精确校验所有脱敏类别，并拒绝内联 Base64 或二进制正文。

        参数说明：
            text: 待校验的 UTF-8 日志文本。
            expected_sensitive_counts: 各敏感 JSON 字段在黄金样本中的固定次数。
            expected_signed_url_count: Dating COS 签名资产 URL 的固定次数。

        失败行为：
            任一字段缺失、值不是 brief 规定的完整占位符、签名查询未被稳定
            替换，或日志包含内联二进制内容时，抛出 AssertionError。
        """
        for key, placeholder in SENSITIVE_PLACEHOLDERS.items():
            values = re.findall(
                rf'"{re.escape(key)}"\s*:\s*"([^\"]*)"',
                text,
            )
            self.assertEqual(
                [placeholder] * expected_sensitive_counts[key],
                values,
                f"{key} 必须逐项精确替换为 {placeholder!r}",
            )

        signed_queries = SIGNED_DATING_ASSET_QUERY_RE.findall(text)
        self.assertEqual(
            ["[REDACTED]"] * expected_signed_url_count,
            signed_queries,
            "Dating COS 签名 URL 的第一个 ? 后必须只保留 [REDACTED]",
        )
        self.assertIsNone(
            INLINE_BASE64_RE.search(text),
            "黄金夹具不得包含 data URI 或超长 Base64 正文",
        )
        self.assertIsNone(
            PYTHON_BYTES_LITERAL_RE.search(text),
            "黄金夹具不得包含 Python bytes 字面量形式的二进制正文",
        )

    def _assert_fixture_contract(
        self,
        *,
        fixture_name,
        expected_gateway_count,
        expected_put_count,
        expected_method,
        expected_schema,
        expected_identity_count,
        expected_signed_url_count,
        expected_sha256,
    ):
        """组合可诊断断言与整体哈希，固定一份黄金夹具的完整验收契约。"""
        fixture_path = FIXTURE_DIR / fixture_name
        raw = fixture_path.read_bytes()
        text = raw.decode("utf-8")

        # 先报告可定位的 marker、字段或脱敏错误；其余 ID、顺序、状态、时间和
        # 业务文本漂移最终由原始字节 SHA-256 捕获。
        self.assertEqual(expected_gateway_count, text.count("Gateway 请求数据:"))
        self.assertEqual(expected_put_count, text.count("PUT 上传请求数据:"))
        self.assertIn(expected_method, text)
        self.assertIn(expected_schema, text)
        self._assert_sanitization_gate(
            text,
            expected_sensitive_counts={
                "auth_token": expected_identity_count,
                "Authorization": 0,
                "Cookie": 0,
                "user_id": expected_identity_count,
                "device_id": expected_identity_count,
            },
            expected_signed_url_count=expected_signed_url_count,
        )
        self.assertEqual(
            expected_sha256,
            hashlib.sha256(raw).hexdigest(),
            f"{fixture_name} 已偏离 Task 1 固定黄金内容",
        )

    def test_reply_fixture_is_complete_and_sanitized(self):
        """多图 Reply 夹具必须完整匹配黄金内容及所有脱敏约束。"""
        self._assert_fixture_contract(
            fixture_name="reply_generation_multi_image_success.log",
            expected_gateway_count=19,
            expected_put_count=2,
            expected_method='"method_name": "GetTaskResult"',
            expected_schema='"schema_version": "dating.reply_generation.v1"',
            expected_identity_count=19,
            expected_signed_url_count=8,
            expected_sha256=REPLY_FIXTURE_SHA256,
        )

    def test_analysis_fixture_is_complete_and_sanitized(self):
        """多图 Analysis 夹具必须完整匹配黄金内容及所有脱敏约束。"""
        self._assert_fixture_contract(
            fixture_name="relationship_analysis_multi_image_success.log",
            expected_gateway_count=30,
            expected_put_count=3,
            expected_method='"method_name": "GetAnalysisResult"',
            expected_schema=(
                '"schema_version": "dating.relationship_analysis.v1"'
            ),
            expected_identity_count=30,
            expected_signed_url_count=12,
            expected_sha256=ANALYSIS_FIXTURE_SHA256,
        )

    def test_signed_url_gate_ignores_ordinary_business_queries(self):
        """签名资产规则不得拦截普通业务 URL 的合法查询参数。"""
        business_url = "https://api.example.test/search?topic=dating&limit=10"
        self.assertEqual([], SIGNED_DATING_ASSET_QUERY_RE.findall(business_url))
