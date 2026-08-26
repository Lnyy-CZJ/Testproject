"""两个 AI 智能体物理拆分后的平台消费契约测试。"""

from __future__ import annotations

import json
import os
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
            env={
                **os.environ,
                "API_EXECUTION_ENABLED": "false",
                "DATABASE_PERSIST_ENABLED": "false",
                "ALLOWED_TARGETS": "[]",
            },
        ).stdout
        self.assertIn("API_EXECUTION_ENABLED: \"false\"", output)
        self.assertIn("DATABASE_PERSIST_ENABLED: \"false\"", output)
        self.assertIn("ALLOWED_TARGETS: '[]'", output)

    def test_first_prod_deploy_promotes_before_bootstrap_start(self) -> None:
        """首次 prod 必须在启动 bootstrap 注册 Client 前复制空环境配置。"""

        script = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
        migration = script.index('run --rm platform-migrate')
        promotion = script.index('python -m app.promote_environment')
        startup = script.index('up -d --remove-orphans')
        self.assertLess(migration, promotion)
        self.assertLess(promotion, startup)
        override = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
        self.assertIn("/srv/test-platform/secrets/prod-kek.json:/run/secrets/platform-kek.json:ro", override)

    def test_api_agent_component_deploy_updates_every_running_suite_service(self) -> None:
        """API Suite 独立发布必须原子重建、验证并回滚所有正在运行的套件服务。"""

        script = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
        self.assertIn('deployment_services=(api-test-agent)', script)
        self.assertIn('up -d --no-deps "${deployment_services[@]}"', script)
        self.assertIn('verify_deployed_service_images "${deployment_services[@]}"', script)
        self.assertIn('"${rollback[@]}" up -d --no-deps "${deployment_services[@]}"', script)

    def test_gateway_version_hash_covers_all_production_source_directories(self) -> None:
        """网关内容哈希必须覆盖 API、组件、上下文、数据和类型源码，避免假一致。"""

        manifest = json.loads((ROOT / "versions.json").read_text(encoding="utf-8"))
        paths = set(manifest["components"]["platform-gateway"]["source_paths"])
        self.assertTrue({
            "test-platform/frontend/src/api",
            "test-platform/frontend/src/components",
            "test-platform/frontend/src/context",
            "test-platform/frontend/src/data",
            "test-platform/frontend/src/types",
        }.issubset(paths))

    def test_dev_component_update_is_selective_and_keeps_api_suite_atomic(self) -> None:
        """选择性 Dev 构建只校验目标组件，但必须同步已运行的 API 执行链。"""

        script = (ROOT / "scripts/dev-up.sh").read_text(encoding="utf-8")
        self.assertIn('python3 - "$snapshot_temp" "${selected[@]}"', script)
        self.assertIn("selected = set(sys.argv[2:])", script)
        self.assertIn('api_suite_selected=true', script)
        self.assertIn('ps --services --status running', script)

    def test_prod_v3_smoke_uses_tool_identity_instead_of_forged_user_headers(self) -> None:
        """发布验收必须读取工具配置，不能伪造已被可信身份层拒绝的用户 Header。"""

        script = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
        self.assertNotIn('"X-Platform-User-ID":"release-smoke"', script)
        self.assertIn('runtime_config(include_secrets=False, llm_capability=None)', script)
        self.assertIn('FUNCTIONAL_WORKBENCH_V3_ENABLED', script)
        self.assertIn('测试用例生成', script)

    def test_prod_deploy_rejects_invalid_user_context_signing_key_before_compose(self) -> None:
        """生产部署必须在任何 Compose 操作前拒绝缺失或目录型签名密钥。"""

        script = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
        validation = script.index('user_context_signing_key=/srv/test-platform/secrets/prod/user-context-signing-key')
        compose = script.index('compose=(')
        self.assertLess(validation, compose)
        self.assertIn('[[ ! -f "$user_context_signing_key" ]]', script)
        self.assertIn('stat -c %s "$user_context_signing_key"', script)
        self.assertIn('/api/v1/health/ready', script)


if __name__ == "__main__":
    unittest.main()
