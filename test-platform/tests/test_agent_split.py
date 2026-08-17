"""两个 AI 智能体物理拆分后的平台消费契约测试。"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentSplitComposeTest(unittest.TestCase):
    """主 Compose 必须只消费镜像，本机构建上下文必须指向两个新项目。"""

    def test_main_compose_has_no_legacy_source_or_agent_build_context(self) -> None:
        """旧源码路径和智能体 build 指令不得重新进入主 Compose。"""

        text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("../AItestcase_Agents", text)
        self.assertIn("FUNCTIONAL_AGENT_IMAGE", text)
        self.assertIn("API_AGENT_IMAGE", text)
        self.assertIn("API_EXECUTOR_IMAGE", text)
        self.assertIn("../functional-test-agent/runtime", text)
        self.assertIn("../api-test-agent/runtime", text)

    def test_local_build_override_uses_only_independent_projects(self) -> None:
        """本机构建覆盖文件不得访问旧仓库或兄弟项目源码。"""

        text = (ROOT / "docker-compose.local-build.yml").read_text(encoding="utf-8")
        self.assertNotIn("AItestcase_Agents", text)
        self.assertEqual(text.count("context: ../functional-test-agent"), 1)
        self.assertEqual(text.count("context: ../api-test-agent"), 4)

    def test_compose_defaults_keep_api_execution_and_persistence_disabled(self) -> None:
        """解析后的部署配置必须维持三个批准的安全默认值。"""

        output = subprocess.run(
            ["docker", "compose", "config"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("API_EXECUTION_ENABLED: \"false\"", output)
        self.assertIn("DATABASE_PERSIST_ENABLED: \"false\"", output)
        self.assertIn("ALLOWED_TARGETS: '[]'", output)


if __name__ == "__main__":
    unittest.main()
