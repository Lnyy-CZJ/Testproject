"""
生产上线预检工具

功能说明:
    检查生产环境变量和基础安全配置，避免默认弱密钥、弱口令和 debug
    模式进入灰度或生产环境。
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_JWT_SECRET = "bug-agent-secret-key-change-in-production"
DEFAULT_ENCRYPT_KEY = "0123456789abcdef0123456789abcdef"
WEAK_PASSWORDS = {"", "postgres", "password", "123456", "admin"}


@dataclass(frozen=True)
class PreflightCheck:
    """
    单项预检结果。

    参数说明:
        key: 检查项名称。
        passed: 是否通过。
        message: 检查说明。
    """

    key: str
    passed: bool
    message: str


@dataclass(frozen=True)
class PreflightReport:
    """预检报告"""

    passed: bool
    checks: list[PreflightCheck]

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化字典"""
        return {
            "passed": self.passed,
            "checks": [check.__dict__ for check in self.checks],
        }


def run_preflight_checks(env: Mapping[str, str] | None = None) -> PreflightReport:
    """
    运行生产上线预检。

    参数说明:
        env: 环境变量映射；为空时读取 os.environ。

    返回值:
        PreflightReport: 汇总后的预检结果。
    """
    values = env or os.environ
    mode = values.get("BUG_AGENT_SERVER_MODE", "debug").lower()
    production_like = mode in {"production", "prod", "release"}

    checks = [
        _check_server_mode(mode),
        _check_jwt_secret(values.get("BUG_AGENT_JWT_SECRET", ""), production_like),
        _check_database_password(values.get("BUG_AGENT_DATABASE_PASSWORD", ""), production_like),
        _check_encrypt_key(
            "credential_encrypt_key",
            values.get("BUG_AGENT_SECRETS_CREDENTIAL_ENCRYPT_KEY", ""),
            production_like,
        ),
        _check_encrypt_key(
            "ai_config_encryption_key",
            values.get("BUG_AGENT_SECRETS_AI_CONFIG_ENCRYPTION_KEY", ""),
            production_like,
        ),
    ]
    return PreflightReport(passed=all(item.passed for item in checks), checks=checks)


def _check_server_mode(mode: str) -> PreflightCheck:
    """检查服务运行模式"""
    passed = mode not in {"debug", "dev", "development"}
    return PreflightCheck(
        key="server_mode",
        passed=passed,
        message="生产环境不得使用 debug/dev 模式" if not passed else "server mode ok",
    )


def _check_jwt_secret(secret: str, production_like: bool) -> PreflightCheck:
    """检查 JWT 密钥"""
    passed = (not production_like) or (len(secret) >= 32 and secret != DEFAULT_JWT_SECRET)
    return PreflightCheck(
        key="jwt_secret",
        passed=passed,
        message="生产环境必须配置非默认 JWT 密钥" if not passed else "jwt secret ok",
    )


def _check_database_password(password: str, production_like: bool) -> PreflightCheck:
    """检查数据库密码"""
    passed = (not production_like) or password not in WEAK_PASSWORDS
    return PreflightCheck(
        key="database_password",
        passed=passed,
        message="生产环境数据库密码不能使用默认弱口令" if not passed else "database password ok",
    )


def _check_encrypt_key(key: str, value: str, production_like: bool) -> PreflightCheck:
    """检查加密密钥"""
    passed = (not production_like) or (len(value) >= 32 and value != DEFAULT_ENCRYPT_KEY)
    return PreflightCheck(
        key=key,
        passed=passed,
        message=f"生产环境必须配置非默认 {key}" if not passed else f"{key} ok",
    )


def main() -> int:
    """命令行入口"""
    parser = argparse.ArgumentParser(description="Run BugAgent production preflight checks")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    report = run_preflight_checks()
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False))
    else:
        for check in report.checks:
            marker = "PASS" if check.passed else "FAIL"
            print(f"[{marker}] {check.key}: {check.message}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
