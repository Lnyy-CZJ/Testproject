"""Dating 结构化日志黄金夹具的完整性与脱敏契约测试。"""

from pathlib import Path
import re
import unittest


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dating"


class DatingFixtureTests(unittest.TestCase):
    """确保后续解析与分析测试始终使用完整、稳定且无敏感信息的夹具。"""

    def test_reply_fixture_is_complete_and_sanitized(self):
        """多图 Reply 夹具必须保留黄金 marker，并移除令牌与签名参数。"""
        text = (FIXTURE_DIR / "reply_generation_multi_image_success.log").read_text(
            encoding="utf-8"
        )
        self.assertEqual(text.count("Gateway 请求数据:"), 19)
        self.assertEqual(text.count("PUT 上传请求数据:"), 2)
        self.assertIn('"method_name": "GetTaskResult"', text)
        self.assertIn('"schema_version": "dating.reply_generation.v1"', text)
        self.assertNotRegex(text, r'"auth_token"\s*:\s*"(?!\*\*\*)')
        self.assertNotRegex(text, r"q-signature=|q-ak=|q-sign-time=")

    def test_analysis_fixture_is_complete_and_sanitized(self):
        """多图 Analysis 夹具必须保留黄金 marker，并移除令牌与签名参数。"""
        text = (
            FIXTURE_DIR / "relationship_analysis_multi_image_success.log"
        ).read_text(encoding="utf-8")
        self.assertEqual(text.count("Gateway 请求数据:"), 30)
        self.assertEqual(text.count("PUT 上传请求数据:"), 3)
        self.assertIn('"method_name": "GetAnalysisResult"', text)
        self.assertIn('"schema_version": "dating.relationship_analysis.v1"', text)
        self.assertNotRegex(text, r'"auth_token"\s*:\s*"(?!\*\*\*)')
        self.assertNotRegex(text, r"q-signature=|q-ak=|q-sign-time=")
