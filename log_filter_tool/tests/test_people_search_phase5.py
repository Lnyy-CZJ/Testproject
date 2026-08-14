"""阶段 5：部署与回归测试（设计 §16、§17.1、§18 阶段 5）。

覆盖范围：
1. Dockerfile 与 docker-compose 部署配置正确性（复制新模块与 skills、
   不复制测试夹具与 PRD、AI 默认关闭、API Key 走只读 secret）。
2. 10 MB 级日志经分析接口可正常处理且不超时。
3. 25 MB 请求边界（MAX_CONTENT_LENGTH）拒绝超限请求。
4. 平台 base path 与 CSRF 在新接口上继续生效。
5. AI 默认关闭（部署默认值），不配置时返回 DISABLED。

阶段 5 完成条件：现有功能无回归，专项分析满足 PRD 验收项。
"""
import json
import time
import unittest
from pathlib import Path

from app import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "people_search"


def read_fixture(name):
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class DeploymentConfigTests(unittest.TestCase):
    """Dockerfile 与 compose 配置符合设计 §16。"""

    def setUp(self):
        self.dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    def test_dockerfile_copies_analyzer_modules_and_skills(self):
        """生产镜像必须包含解析、规则、AI 模块与 skills 目录。"""
        self.assertIn("COPY people_search_analyzer.py .", self.dockerfile)
        self.assertIn("COPY people_search_rules.py .", self.dockerfile)
        self.assertIn("COPY people_search_ai.py .", self.dockerfile)
        self.assertIn("COPY skills/ skills/", self.dockerfile)

    def test_dockerfile_does_not_copy_tests_or_prd(self):
        """测试夹具与 PRD 不复制进生产镜像。"""
        self.assertNotIn("COPY tests/", self.dockerfile)
        self.assertNotIn("COPY Log_Tool_PRD/", self.dockerfile)
        self.assertNotIn("COPY docs/", self.dockerfile)
        self.assertNotIn("COPY peoplesearch_logs/", self.dockerfile)

    def test_compose_declares_analyzer_env_and_secret_key(self):
        """compose 声明专项分析开关，AI 默认关闭，API Key 走 secret 文件。"""
        self.assertIn('PEOPLE_SEARCH_ANALYZER_ENABLED: "true"', self.compose)
        self.assertIn('PEOPLE_SEARCH_ANALYZER_AI_ENABLED: "false"', self.compose)
        self.assertIn("PEOPLE_SEARCH_ANALYZER_LLM_API_KEY_FILE", self.compose)
        self.assertIn("/run/secrets/log-analyzer-key", self.compose)
        self.assertIn("secrets:", self.compose)

    def test_compose_does_not_inline_api_key_plaintext(self):
        """API Key 不得以明文写入 compose 环境变量。"""
        self.assertNotIn("PEOPLE_SEARCH_ANALYZER_LLM_API_KEY:", self.compose)


class LargeLogBoundaryTests(unittest.TestCase):
    """10 MB 级日志与 25 MB 请求边界。"""

    def _make_large_log(self, target_bytes):
        """用一份有效夹具 + 大量无害噪声行拼出指定量级日志。

        噪声行不含任何 marker，解析器会直接跳过，用于验证大体量输入
        的行规范化与主循环性能，而不是触发多任务或解析错误。
        """
        base = read_fixture("f01_public_figure_local_hit.log")
        filler_line = "noise filler line without any marker " + ("x" * 950)
        chunks = [base]
        current = len(base.encode("utf-8"))
        while current < target_bytes:
            chunks.append(filler_line)
            current += len(filler_line.encode("utf-8")) + 1
        return "\n".join(chunks)

    def test_ten_mb_log_is_analyzed_within_time_budget(self):
        """10 MB 级日志应能完成分析且不超时、不崩溃。"""
        app = create_app()
        app.testing = True
        large_log = self._make_large_log(10 * 1024 * 1024)
        self.assertGreaterEqual(len(large_log.encode("utf-8")), 10 * 1024 * 1024)

        start = time.monotonic()
        response = app.test_client().post(
            "/people-search/analyze", json={"log_text": large_log}
        )
        elapsed = time.monotonic() - start

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertIn(data["verdict"], {
            "NORMAL", "ISSUES_FOUND", "NEEDS_CONFIRMATION", "INCOMPLETE_EVIDENCE",
        })
        self.assertTrue(data["report_markdown"].startswith("# People Insight 检索日志分析"))
        # 宽松时间预算：内部 MVP 同步处理 10MB 应在数十秒内完成。
        self.assertLess(elapsed, 60, f"10MB 日志分析耗时 {elapsed:.1f}s 超出预算")

    def test_request_over_25mb_is_rejected(self):
        """超过 MAX_CONTENT_LENGTH（25MB）的请求不得被正常接受。"""
        app = create_app()
        app.testing = True
        self.assertEqual(app.config["MAX_CONTENT_LENGTH"], 25 * 1024 * 1024)

        oversized_log = "x" * (25 * 1024 * 1024 + 1024)
        response = app.test_client().post(
            "/people-search/analyze", json={"log_text": oversized_log}
        )
        # 关键性质：超限请求不能返回成功 200。
        self.assertIn(response.status_code, {400, 413})


class PlatformIntegrationRegressionTests(unittest.TestCase):
    """平台前缀与 CSRF 在新接口上继续生效（回归）。"""

    def test_analyze_endpoint_follows_platform_base_path(self):
        app = create_app(base_path="/log-filter")
        app.testing = True
        client = app.test_client()
        log_text = read_fixture("f01_public_figure_local_hit.log")

        ok = client.post("/log-filter/people-search/analyze", json={"log_text": log_text})
        self.assertEqual(ok.status_code, 200)

        missing = client.post("/people-search/analyze", json={"log_text": log_text})
        self.assertEqual(missing.status_code, 404)

    def test_analyze_endpoint_enforces_csrf_in_platform_mode(self):
        app = create_app(base_path="/log-filter")
        app.testing = True
        app.config["PLATFORM_API_URL"] = "https://platform.example.com"
        client = app.test_client()
        log_text = read_fixture("f01_public_figure_local_hit.log")

        denied = client.post("/log-filter/people-search/analyze", json={"log_text": log_text})
        self.assertEqual(denied.status_code, 403)

        client.set_cookie("tp_csrf", "csrf-secret", domain="localhost")
        allowed = client.post(
            "/log-filter/people-search/analyze",
            json={"log_text": log_text},
            headers={"X-CSRF-Token": "csrf-secret"},
        )
        self.assertEqual(allowed.status_code, 200)


class AIDefaultDisabledRegressionTests(unittest.TestCase):
    """部署默认不配置 AI 时，分析接口返回 DISABLED 且不发起模型调用。"""

    def test_default_deployment_returns_ai_disabled(self):
        app = create_app()
        app.testing = True
        self.assertFalse(app.config["PEOPLE_SEARCH_ANALYZER_AI_ENABLED"])

        log_text = read_fixture("f01_public_figure_local_hit.log")
        response = app.test_client().post(
            "/people-search/analyze", json={"log_text": log_text}
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(data["ai"], {"status": "DISABLED"})
        self.assertNotIn("## AI 说明", data["report_markdown"])


class ExistingFeatureRegressionTests(unittest.TestCase):
    """现有过滤、统计、导出、健康检查不受专项分析影响（回归）。"""

    def test_health_and_index_still_work(self):
        app = create_app()
        app.testing = True
        client = app.test_client()

        self.assertEqual(client.get("/health").status_code, 200)
        index = client.get("/")
        self.assertEqual(index.status_code, 200)
        html = index.get_data(as_text=True)
        # 现有控件仍在
        self.assertIn('id="export-log-content-btn"', html)
        self.assertIn('id="result-search"', html)
        # 新增分析入口共存
        self.assertIn('id="analyze-people-search-btn"', html)

    def test_existing_log_exports_still_use_log_extension(self):
        from tempfile import TemporaryDirectory

        app = create_app()
        app.testing = True
        with TemporaryDirectory() as export_dir:
            app.config["LOG_EXPORT_DIR"] = export_dir
            app.config["LOG_EXPORT_DISPLAY_DIR"] = export_dir
            response = app.test_client().post(
                "/export",
                json={"export_type": "filtered_result", "content": "some log"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["filename"].endswith(".log"))


if __name__ == "__main__":
    unittest.main()
