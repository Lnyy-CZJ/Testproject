"""两个 AI 智能体物理拆分后的平台消费契约测试。"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
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

    def test_compose_uses_seven_day_session_defaults(self) -> None:
        """平台 API 的两种新会话期限必须都解析为 168 小时。"""

        output = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        environment = json.loads(output)["services"]["platform-api"]["environment"]
        self.assertEqual(environment["SESSION_IDLE_HOURS"], "168")
        self.assertEqual(environment["SESSION_ABSOLUTE_HOURS"], "168")

    def test_compose_exposes_registration_protection_settings(self) -> None:
        """Compose 必须把模式、来源限流和全局熔断完整传给平台 API。"""

        output = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        environment = json.loads(output)["services"]["platform-api"]["environment"]
        self.assertEqual(environment["REGISTRATION_MODE"], "open")
        self.assertEqual(environment["REGISTRATION_RATE_LIMIT"], "5")
        self.assertEqual(environment["REGISTRATION_RATE_WINDOW_MINUTES"], "15")
        self.assertEqual(environment["REGISTRATION_LOCK_MINUTES"], "15")
        self.assertEqual(environment["REGISTRATION_GLOBAL_LIMIT"], "100")
        self.assertEqual(environment["REGISTRATION_GLOBAL_WINDOW_MINUTES"], "15")
        self.assertEqual(environment["REGISTRATION_GLOBAL_LOCK_MINUTES"], "15")

    def test_gateway_overwrites_forwarded_for_and_clears_untrusted_device_signal(self) -> None:
        """客户端伪造的来源链与设备头必须在进入 API 前被网关覆盖。"""

        text = (ROOT / "nginx/nginx.conf").read_text(encoding="utf-8")
        api_location = text.split("location /api/v1/ {", 1)[1].split("}", 1)[0]
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", api_location)
        self.assertIn('proxy_set_header X-Test-Platform-Gateway "1";', api_location)
        self.assertIn('proxy_set_header X-Registration-Device "";', api_location)
        self.assertNotIn("$proxy_add_x_forwarded_for", api_location)

    def test_platform_api_has_no_host_port(self) -> None:
        """平台 API 只允许由网关访问，不能新增宿主机端口映射。"""

        output = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertNotIn("ports", json.loads(output)["services"]["platform-api"])

    @staticmethod
    def _production_auth_env(**overrides: str) -> str:
        """构造只供部署门禁测试使用的完整生产认证配置。"""

        values = {
            "SESSION_IDLE_HOURS": "168",
            "SESSION_ABSOLUTE_HOURS": "168",
            "REGISTRATION_MODE": "open",
            "REGISTRATION_RATE_LIMIT": "5",
            "REGISTRATION_RATE_WINDOW_MINUTES": "15",
            "REGISTRATION_LOCK_MINUTES": "15",
            "REGISTRATION_GLOBAL_LIMIT": "100",
            "REGISTRATION_GLOBAL_WINDOW_MINUTES": "15",
            "REGISTRATION_GLOBAL_LOCK_MINUTES": "15",
            "COOKIE_SECURE": "false",
            "APP_PUBLIC_URL": "http://127.0.0.1:41873",
            "SESSION_COOKIE_RISK_ACCEPTANCE_ID": "RISK-20260830-001",
        }
        values.update(overrides)
        return "".join(f"{key}={value}\n" for key, value in values.items())

    def _run_production_auth_gate(self, env_text: str) -> subprocess.CompletedProcess[str]:
        """运行部署脚本的最前置门禁；后续固定密钥检查会阻止任何真实操作。"""

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            release = root / "release"
            release.mkdir()
            base_env = root / ".env.prod"
            base_env.write_text(env_text, encoding="utf-8")
            (release / ".env.images").write_text("", encoding="utf-8")
            (release / "versions.json").write_text("{}", encoding="utf-8")
            (release / "release-manifest.json").write_text("{}", encoding="utf-8")
            source = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
            source = source.replace(
                "base_env=/srv/test-platform/env/.env.prod",
                f"base_env={shlex.quote(str(base_env))}",
            )
            script = root / "deploy-prod.sh"
            script.write_text(source, encoding="utf-8")
            return subprocess.run(
                ["bash", str(script), str(release)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

    def test_prod_insecure_cookie_requires_release_acceptance_reference(self) -> None:
        """生产 HTTP Cookie 缺少格式合规的人工风险引用时必须在副作用前阻断。"""

        result = self._run_production_auth_gate(
            self._production_auth_env(SESSION_COOKIE_RISK_ACCEPTANCE_ID="")
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SESSION_COOKIE_RISK_ACCEPTANCE_ID", result.stderr)

    def test_prod_secure_cookie_requires_https_public_url(self) -> None:
        """Secure Cookie 组合必须配套 HTTPS 公开入口。"""

        result = self._run_production_auth_gate(
            self._production_auth_env(
                COOKIE_SECURE="true",
                APP_PUBLIC_URL="http://prod.example.test",
                SESSION_COOKIE_RISK_ACCEPTANCE_ID="",
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("APP_PUBLIC_URL", result.stderr)

    def test_deploy_env_parser_never_executes_values(self) -> None:
        """恶意 env 值只能作为文本被拒绝，不能通过 source/eval 执行。"""

        with tempfile.TemporaryDirectory() as temporary_directory:
            sentinel = Path(temporary_directory) / "executed"
            malicious = f"$(touch {sentinel})"
            result = self._run_production_auth_gate(
                self._production_auth_env(SESSION_IDLE_HOURS=malicious)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SESSION_IDLE_HOURS", result.stderr)
            self.assertFalse(sentinel.exists())

    def test_registration_release_preserves_existing_migration_manifest_gate(self) -> None:
        """认证改造不新增迁移，0019 之外仍必须提供既有项目权限 manifest。"""

        script = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
        self.assertIn('if [[ "$alembic_target" != "20260824_0019" ]]; then', script)
        self.assertIn('PROJECT_ACCESS_MANIFEST', script)
        self.assertIn('$state_dir/project-access-manifest.json', script)

        release_workflow = (ROOT.parent / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn('ALEMBIC_TARGET=" + versions["database"]["alembic_revision"]', release_workflow)

    def test_api_autotest_uses_asia_shanghai_for_human_readable_times(self) -> None:
        """接口自动化容器必须按北京时间生成任务 ID、日志文件名和日志正文。

        页面会把带时区的任务时间转换为浏览器本地时间；任务 ID 和 Python
        logging 则依赖容器本地时区。若 Compose 未声明 TZ，两者会分别显示
        北京时间和 UTC，产生固定八小时偏差。
        """

        output = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env={key: value for key, value in os.environ.items() if key != "TZ"},
        ).stdout
        config = json.loads(output)

        self.assertEqual(
            config["services"]["api-autotest"]["environment"].get("TZ"),
            "Asia/Shanghai",
        )

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
