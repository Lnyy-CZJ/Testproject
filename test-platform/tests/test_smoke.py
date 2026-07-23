"""测试开发平台运行态冒烟测试。

功能说明:
    验证平台首页、两个工具页面、健康检查以及关键 POST 请求均可通过
    统一入口访问。测试只读取页面并发送最小输入，不保存测试日志。

配置说明:
    PLATFORM_BASE_URL 可覆盖默认的 http://127.0.0.1:8080。
"""

import json
import os
import unittest
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("PLATFORM_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def request(path, data=None, content_type=None):
    """向平台发送请求并返回状态码、响应头和解码后的正文。"""
    headers = {"Accept": "*/*"}
    if content_type:
        headers["Content-Type"] = content_type
    request_object = Request(f"{BASE_URL}{path}", data=data, headers=headers)
    with urlopen(request_object, timeout=15) as response:
        return response.status, response.headers, response.read().decode("utf-8")


class PlatformSmokeTest(unittest.TestCase):
    """从用户统一入口验证平台和两个独立工具的核心连通性。"""

    def test_platform_home_lists_both_tools(self):
        status, _, body = request("/")

        self.assertEqual(status, 200)
        self.assertIn("测试开发平台", body)
        self.assertIn('/trackevents/', body)
        self.assertIn('/log-filter/', body)

    def test_trackevents_page_health_and_analysis_are_available(self):
        page_status, _, page = request("/trackevents/")
        health_status, _, health_body = request("/trackevents/health")
        payload = json.dumps({"log_text": "", "expected_counts": {}}).encode("utf-8")
        analyze_status, _, _ = request(
            "/trackevents/api/analyze",
            data=payload,
            content_type="application/json",
        )

        self.assertEqual(page_status, 200)
        self.assertIn("埋点测试工具", page)
        self.assertEqual(health_status, 200)
        self.assertEqual(json.loads(health_body)["status"], "ok")
        self.assertEqual(analyze_status, 200)

    def test_log_filter_page_health_sample_and_form_are_available(self):
        page_status, _, page = request("/log-filter/")
        health_status, _, health_body = request("/log-filter/health")
        sample_status, _, sample = request("/log-filter/sample")
        form_body = urlencode({"log_text": "", "method": "__ALL__"}).encode("utf-8")
        post_status, _, _ = request(
            "/log-filter/",
            data=form_body,
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(page_status, 200)
        self.assertIn("Log 过滤工具", page)
        self.assertEqual(health_status, 200)
        self.assertEqual(json.loads(health_body)["status"], "ok")
        self.assertEqual(sample_status, 200)
        self.assertTrue(sample)
        self.assertEqual(post_status, 200)


if __name__ == "__main__":
    unittest.main()
