"""单日志分析工作台壳层与静态资源部署路径的行为测试。"""

import unittest

from app import create_app


class WorkbenchShellTest(unittest.TestCase):
    """锁定后续前端任务依赖的 DOM 标识与 Blueprint 静态资源合同。"""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_page_uses_single_log_workbench_shell(self):
        """根页面必须交付单日志壳层，且不得残留双日志比较入口。"""
        html = self.client.get("/").get_data(as_text=True)
        for marker in (
            'id="log-workbench"',
            'id="analysis-mode"',
            'id="analyze-log-btn"',
            'id="workbench-log-pane"',
            'id="workbench-result-pane"',
            'id="overviewPanel"',
            'id="interfacesPanel"',
            'id="timelinePanel"',
            'id="resultPanel"',
            'id="checksPanel"',
        ):
            self.assertIn(marker, html)
        self.assertNotIn("双日志对比", html)
        self.assertNotIn('id="compareView"', html)

    def test_blueprint_static_assets_follow_base_path(self):
        """静态资源必须由 tool Blueprint 管理，并随部署前缀一同生成。"""
        app = create_app("/log-tool")
        app.config["TESTING"] = True
        client = app.test_client()
        html = client.get("/log-tool/").get_data(as_text=True)
        self.assertIn("/log-tool/static/css/log-workbench.css", html)
        # Flask 的静态响应持有文件句柄；上下文管理器确保测试结束前主动关闭。
        with client.get("/log-tool/static/js/workbench-core.js") as response:
            self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
