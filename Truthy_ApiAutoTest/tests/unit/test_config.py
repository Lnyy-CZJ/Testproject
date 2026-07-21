"""配置加载优先级与敏感字段来源测试。"""

from pathlib import Path

import yaml

from framework.config import load_config


def _write_env_config(config_dir: Path) -> None:
    """写入最小环境配置，供优先级测试使用。"""
    config_dir.mkdir()
    (config_dir / "env.test.yaml").write_text(
        yaml.safe_dump(
            {
                "base_url": "https://yaml.example.test",
                "platform": "android",
                "auth_token": "must-not-be-loaded",
            }
        ),
        encoding="utf-8",
    )


def test_cli_overrides_environment_yaml_and_defaults(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    _write_env_config(config_dir)

    settings = load_config(
        "test",
        cli_overrides={"base_url": "https://cli.example.test"},
        environ={
            "TRUTHY_BASE_URL": "https://env.example.test",
            "TRUTHY_PLATFORM": "ios",
            "TRUTHY_AUTH_TOKEN": "env-secret",
        },
        config_dir=config_dir,
    )

    assert settings.base_url == "https://cli.example.test"
    assert settings.platform == "ios"
    assert settings.app_version == "1.0.0"
    assert settings.auth_token == "env-secret"


def test_sensitive_values_are_accepted_only_from_environment(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    _write_env_config(config_dir)

    settings = load_config(
        "test",
        cli_overrides={"auth_token": "cli-secret"},
        environ={},
        config_dir=config_dir,
    )

    assert settings.auth_token is None


def test_committed_test_environment_uses_https() -> None:
    settings = load_config("test")

    assert settings.base_url.startswith("https://")


def test_settings_repr_does_not_expose_tokens() -> None:
    """配置对象 repr 不得暴露由环境变量注入的 access/refresh token。"""
    settings = load_config(
        "test",
        environ={
            "TRUTHY_AUTH_TOKEN": "access-ultra-secret",
            "TRUTHY_REFRESH_TOKEN": "refresh-ultra-secret",
        },
    )

    rendered = repr(settings)
    assert "access-ultra-secret" not in rendered
    assert "refresh-ultra-secret" not in rendered
