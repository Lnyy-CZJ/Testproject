from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api import auth as auth_api
from app.core.config import Settings, get_settings
from app.core.security import hash_password, token_hash, verify_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.access import ProjectMembership, UserToolGrant
from app.models.audit import AuditLog
from app.models.identity import LoginThrottle, PlatformSession, User, UserRole
from app.models.tool import Tool
from app.schemas.admin import ResetPasswordRequest, UserCreateRequest
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    SetupRequest,
)
from app.services import auth as auth_service


@pytest.fixture
def registration_integration_factory() -> Generator[
    sessionmaker[Session], None, None
]:
    """连接显式指定的一次性 PostgreSQL 注册集成库。

    安全约束:
        只接受 loopback 主机和固定数据库名 ``registration_it``，防止
        ``drop_all`` 误触本机共享库、Compose 数据卷或生产数据库。
    """

    database_url = os.getenv("REGISTRATION_INTEGRATION_DATABASE_URL")
    if not database_url:
        pytest.skip("未配置一次性注册集成数据库")
    parsed = make_url(database_url)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.host not in {"127.0.0.1", "localhost", "::1"}
        or parsed.database != "registration_it"
    ):
        pytest.fail(
            "REGISTRATION_INTEGRATION_DATABASE_URL 必须指向 loopback 上的 registration_it"
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def registration_integration_client(
    registration_integration_factory: sessionmaker[Session],
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    """让业务事务和注册计数事务共同使用专用 PostgreSQL 测试库。"""

    def override_database() -> Generator[Session, None, None]:
        database = registration_integration_factory()
        try:
            yield database
        finally:
            database.close()

    original_factory = getattr(app.state, "registration_session_factory", None)
    original_overrides = dict(app.dependency_overrides)
    app.state.registration_session_factory = registration_integration_factory
    app.dependency_overrides[get_db] = override_database
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client, registration_integration_factory
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        if original_factory is None:
            delattr(app.state, "registration_session_factory")
        else:
            app.state.registration_session_factory = original_factory


def test_registration_status_exposes_only_mode(client) -> None:
    """公开状态接口只暴露注册模式，不泄露阈值或内部配置。"""

    response = client.get("/api/v1/auth/registration-status")

    assert response.status_code == 200
    assert response.json() == {"mode": "open"}


def test_registration_status_uses_no_store(client) -> None:
    """注册开关可能随时关闭，浏览器和代理不得缓存状态。"""

    response = client.get("/api/v1/auth/registration-status")

    assert response.headers["Cache-Control"] == "no-store"


def test_registration_rate_settings_have_safe_defaults() -> None:
    """默认配置必须直接启用开放注册及 5/100、15 分钟两级保护。"""

    settings = Settings()

    assert settings.registration_mode == "open"
    assert settings.registration_rate_limit == 5
    assert settings.registration_rate_window_minutes == 15
    assert settings.registration_lock_minutes == 15
    assert settings.registration_global_limit == 100
    assert settings.registration_global_window_minutes == 15
    assert settings.registration_global_lock_minutes == 15


def test_password_policy_accepts_six_and_eighteen_code_points() -> None:
    """新密码允许 6 和 18 个 Python/Unicode 字符的闭区间边界。"""

    for password in ("123456", "123456789012345678"):
        encoded = hash_password(password)
        assert verify_password(encoded, password)


@pytest.mark.parametrize("password", ["12345", "1234567890123456789"])
def test_password_policy_rejects_five_and_nineteen_code_points(password: str) -> None:
    """新密码的 5 和 19 字符边界必须被服务端拒绝。"""

    with pytest.raises(ValueError, match="6 到 18"):
        hash_password(password)


def test_password_policy_counts_unicode_code_points_without_trimming() -> None:
    """密码按 Unicode 字符计数且不 trim，空格仍是密码的一部分。"""

    unicode_password = "密码密码密码"
    spaced_password = " 1234 "

    unicode_hash = hash_password(unicode_password)
    spaced_hash = hash_password(spaced_password)
    assert verify_password(unicode_hash, unicode_password)
    assert verify_password(spaced_hash, spaced_password)
    assert not verify_password(spaced_hash, spaced_password.strip())


def test_register_setup_change_and_admin_schemas_share_password_boundaries() -> None:
    """所有设置新密码的服务端入口统一采用 6-18 位规则。"""

    factories = [
        lambda password: RegisterRequest(
            username="tester", display_name="测试人员", password=password
        ),
        lambda password: SetupRequest(
            bootstrap_token="bootstrap-token-for-tests",
            username="admin",
            display_name="管理员",
            password=password,
        ),
        lambda password: ChangePasswordRequest(
            current_password="legacy-password-value",
            new_password=password,
        ),
        lambda password: UserCreateRequest(
            username="tester",
            display_name="测试人员",
            password=password,
            role="tester",
        ),
        lambda password: ResetPasswordRequest(new_password=password),
    ]

    for factory in factories:
        factory("123456")
        factory("123456789012345678")
        with pytest.raises(ValidationError):
            factory("12345")
        with pytest.raises(ValidationError):
            factory("1234567890123456789")


def test_login_request_accepts_legacy_long_password() -> None:
    """登录输入继续接受存量长密码，不能套用新设密码上限。"""

    password = "legacy-password-that-is-longer-than-eighteen"
    payload = LoginRequest(username="legacy", password=password)

    assert payload.password == password


def test_legacy_long_password_user_can_login(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """直接写入旧 Argon2 哈希的长密码账号在升级后仍能登录。"""

    password = "legacy-password-that-is-longer-than-eighteen"
    legacy_hash = PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
    ).hash(password)
    with database_factory() as database:
        database.add(
            User(
                id="legacy-user",
                username="Legacy",
                username_normalized="legacy",
                display_name="存量用户",
                password_hash=legacy_hash,
                status="active",
                platform_role="tester",
            )
        )
        database.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "legacy", "password": password},
    )

    assert response.status_code == 200
    assert response.json()["user"]["id"] == "legacy-user"


def test_settings_default_session_lifetime_is_168_hours() -> None:
    """新部署默认同时使用 168 小时空闲和绝对会话期限。"""

    settings = Settings()

    assert settings.session_idle_hours == 168
    assert settings.session_absolute_hours == 168


def test_create_session_uses_168_hour_idle_and_absolute_expiry(
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """新建会话的两种到期时间都从创建时刻向后 168 小时。"""

    now = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(auth_service, "utc_now", lambda: now)
    with database_factory() as database:
        user = User(
            id="session-owner",
            username="session-owner",
            username_normalized="session-owner",
            display_name="会话用户",
            password_hash=hash_password("valid-pass-123"),
            status="active",
            platform_role="tester",
        )
        database.add(user)
        database.flush()
        session, _session_token, _csrf_token = auth_service.create_session(
            database,
            user,
            Settings(),
            "127.0.0.1",
            "test-agent",
        )

    assert session.idle_expires_at == now + timedelta(hours=168)
    assert session.absolute_expires_at == now + timedelta(hours=168)


def _store_boundary_session(
    database_factory: sessionmaker[Session],
    *,
    now: datetime,
    raw_token: str,
    idle_hours: int = 168,
    absolute_hours: int = 168,
) -> datetime:
    """写入可由 ``resolve_session`` 验证的边界会话并返回绝对到期时间。"""

    absolute_expires_at = now + timedelta(hours=absolute_hours)
    with database_factory() as database:
        database.add(
            User(
                id=f"user-{raw_token}",
                username=f"user-{raw_token}",
                username_normalized=f"user-{raw_token}",
                display_name="边界用户",
                password_hash=hash_password("valid-pass-123"),
                status="active",
                platform_role="tester",
            )
        )
        database.add(
            PlatformSession(
                id=f"session-{raw_token}",
                token_hash=token_hash(raw_token),
                csrf_hash=token_hash(f"csrf-{raw_token}"),
                user_id=f"user-{raw_token}",
                idle_expires_at=now + timedelta(hours=idle_hours),
                absolute_expires_at=absolute_expires_at,
                last_seen_at=now,
                ip_address="127.0.0.1",
                user_agent_hash=token_hash("test-agent"),
            )
        )
        database.commit()
    return absolute_expires_at


def test_session_is_valid_at_six_days_twenty_three_hours(
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """会话在 T+6 天 23 小时仍然有效。"""

    created_at = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
    _store_boundary_session(
        database_factory,
        now=created_at,
        raw_token="before-boundary",
    )
    monkeypatch.setattr(
        auth_service,
        "utc_now",
        lambda: created_at + timedelta(days=6, hours=23),
    )

    with database_factory() as database:
        resolved = auth_service.resolve_session(
            database,
            "before-boundary",
            Settings(session_touch_interval_seconds=999999),
        )

    assert resolved is not None


def test_session_is_invalid_at_exactly_seven_days(
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """到达 T+168 小时时使用小于等于判断，会话立即失效。"""

    created_at = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
    _store_boundary_session(
        database_factory,
        now=created_at,
        raw_token="exact-boundary",
    )
    monkeypatch.setattr(
        auth_service,
        "utc_now",
        lambda: created_at + timedelta(days=7),
    )

    with database_factory() as database:
        resolved = auth_service.resolve_session(
            database,
            "exact-boundary",
            Settings(session_touch_interval_seconds=999999),
        )

    assert resolved is None


def test_session_touch_never_extends_absolute_expiry(
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """触摸只能延长 idle 到 absolute，绝不能滑动绝对到期时间。"""

    created_at = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
    absolute = _store_boundary_session(
        database_factory,
        now=created_at,
        raw_token="touch-boundary",
        idle_hours=1,
    )
    monkeypatch.setattr(
        auth_service,
        "utc_now",
        lambda: created_at + timedelta(minutes=30),
    )

    with database_factory() as database:
        resolved = auth_service.resolve_session(
            database,
            "touch-boundary",
            Settings(session_touch_interval_seconds=0),
        )
        assert resolved is not None
        session, _user = resolved
        assert auth_service.as_utc(session.idle_expires_at) == absolute
        assert auth_service.as_utc(session.absolute_expires_at) == absolute


def test_existing_session_keeps_persisted_expiry_after_config_change(
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """配置升级只影响新会话，旧会话的 absolute 字段保持原值。"""

    created_at = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
    original_absolute = _store_boundary_session(
        database_factory,
        now=created_at,
        raw_token="persisted-expiry",
        idle_hours=8,
        absolute_hours=24,
    )
    monkeypatch.setattr(
        auth_service,
        "utc_now",
        lambda: created_at + timedelta(hours=1),
    )

    with database_factory() as database:
        resolved = auth_service.resolve_session(
            database,
            "persisted-expiry",
            Settings(session_touch_interval_seconds=0),
        )
        assert resolved is not None
        session, _user = resolved
        assert auth_service.as_utc(session.absolute_expires_at) == original_absolute


def test_registration_keys_use_reg_namespace_and_hash_values() -> None:
    """注册计数键只能保存隔离命名空间和哈希，不能落用户名或 IP 原文。"""

    keys = auth_service.registration_throttle_keys(
        username=" Alice ",
        ip_address="203.0.113.10",
        device_signal="trusted-device",
    )

    assert [kind for kind, _ in keys] == [
        "reg_global",
        "reg_ip",
        "reg_username",
        "reg_device",
    ]
    digests = [digest for _, digest in keys]
    assert all(len(digest) == 64 for digest in digests)
    assert all("alice" not in digest and "203.0.113.10" not in digest for digest in digests)


def test_login_success_clear_does_not_delete_registration_buckets(
    database_factory: sessionmaker[Session],
) -> None:
    """登录成功只能清理登录桶，注册桶必须保持独立。"""

    now = datetime.now(UTC)
    registration_hash = token_hash("reg_username:alice")
    with database_factory() as database:
        database.add_all(
            [
                LoginThrottle(
                    key_type="username",
                    key_hash=token_hash("username:alice"),
                    window_started_at=now,
                    attempt_count=2,
                ),
                LoginThrottle(
                    key_type="reg_username",
                    key_hash=registration_hash,
                    window_started_at=now,
                    attempt_count=4,
                ),
            ]
        )
        database.commit()
        auth_service.clear_login_failures(database, "Alice", "198.51.100.5")
        database.commit()

        assert database.scalar(
            select(LoginThrottle).where(LoginThrottle.key_hash == registration_hash)
        ) is not None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("registration_rate_limit", 0),
        ("registration_rate_limit", 6),
        ("registration_rate_window_minutes", 14),
        ("registration_lock_minutes", 14),
        ("registration_global_limit", 0),
        ("registration_global_limit", 101),
        ("registration_global_window_minutes", 14),
        ("registration_global_lock_minutes", 14),
    ],
)
def test_registration_rate_settings_reject_disabled_or_weakened_protection(
    field: str,
    value: int,
) -> None:
    """配置不能通过零值、更大阈值或更短窗口关闭注册保护。"""

    with pytest.raises(ValidationError):
        Settings(**{field: value})


@pytest.mark.parametrize(
    "values",
    [
        {"registration_rate_window_minutes": 30, "registration_lock_minutes": 15},
        {
            "registration_global_window_minutes": 30,
            "registration_global_lock_minutes": 15,
        },
    ],
)
def test_registration_rate_settings_require_lock_not_shorter_than_window(
    values: dict[str, int],
) -> None:
    """锁定时间短于计数窗口会产生保护空洞，启动配置必须拒绝。"""

    with pytest.raises(ValidationError):
        Settings(**values)


def test_registration_counter_allows_five_and_blocks_sixth(
    database_factory: sessionmaker[Session],
) -> None:
    """同一来源前五次可进入业务层，第六次开始返回来源限流。"""

    with database_factory() as database:
        for _ in range(5):
            decision = auth_service.evaluate_registration_attempt(
                database,
                username="Alice",
                ip_address="203.0.113.10",
                device_signal=None,
                settings=Settings(),
            )
            database.commit()
            assert decision.blocked_kind is None

        decision = auth_service.evaluate_registration_attempt(
            database,
            username="Alice",
            ip_address="203.0.113.10",
            device_signal=None,
            settings=Settings(),
        )
        database.commit()

    assert decision.blocked_kind == "rate"


def test_registration_global_counter_opens_at_one_hundred(
    database_factory: sessionmaker[Session],
) -> None:
    """第 100 次只打开熔断并仍可放行，第 101 次才返回 circuit。"""

    with database_factory() as database:
        for index in range(100):
            decision = auth_service.evaluate_registration_attempt(
                database,
                username=f"user-{index}",
                ip_address=f"198.51.100.{index}",
                device_signal=None,
                settings=Settings(),
            )
            database.commit()
        assert decision.blocked_kind is None
        assert decision.circuit_opened is True

        rejected = auth_service.evaluate_registration_attempt(
            database,
            username="user-next",
            ip_address="203.0.113.250",
            device_signal=None,
            settings=Settings(),
        )
        database.commit()

    assert rejected.blocked_kind == "circuit"


def test_rate_limited_submissions_still_increment_global_counter(
    database_factory: sessionmaker[Session],
) -> None:
    """来源已锁定时不续来源锁，但该提交仍必须进入全局计数。"""

    with database_factory() as database:
        for _ in range(6):
            decision = auth_service.evaluate_registration_attempt(
                database,
                username="Alice",
                ip_address="203.0.113.10",
                device_signal=None,
                settings=Settings(),
            )
            database.commit()
        global_row = database.scalar(
            select(LoginThrottle).where(LoginThrottle.key_type == "reg_global")
        )

    assert decision.blocked_kind == "rate"
    assert global_row is not None
    assert global_row.attempt_count == 6


def test_registration_counter_resets_after_window_and_lock(
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """窗口与锁均过期后，新提交从一次重新计数。"""

    now = datetime(2026, 8, 30, 0, 30, tzinfo=UTC)
    monkeypatch.setattr(auth_service, "utc_now", lambda: now)
    keys = [
        ("reg_global", token_hash("reg_global:*")),
        ("reg_ip", token_hash("reg_ip:203.0.113.10")),
        ("reg_username", token_hash("reg_username:alice")),
    ]
    with database_factory() as database:
        database.add_all(
            [
                LoginThrottle(
                    key_type=kind,
                    key_hash=digest,
                    window_started_at=now - timedelta(minutes=16),
                    attempt_count=100,
                    blocked_until=now - timedelta(seconds=1),
                )
                for kind, digest in keys
            ]
        )
        database.commit()

        decision = auth_service.evaluate_registration_attempt(
            database,
            username="Alice",
            ip_address="203.0.113.10",
            device_signal=None,
            settings=Settings(),
        )
        database.commit()
        rows = list(database.scalars(select(LoginThrottle)).all())

    assert decision.blocked_kind is None
    assert {row.attempt_count for row in rows} == {1}


def test_registration_creates_active_tester_without_privilege_fields(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """自助注册固定创建 tester，并拒绝客户端夹带角色或项目。"""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "new.tester",
            "display_name": "新测试人员",
            "password": "Strong-pass-123",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "tester"
    with database_factory() as database:
        user = database.scalar(select(User).where(User.username_normalized == "new.tester"))
        assert user is not None
        assert (user.platform_role, user.status) == ("tester", "active")
        assert database.scalars(
            select(UserRole).where(UserRole.user_id == user.id)
        ).all() == []
        assert database.scalars(
            select(ProjectMembership).where(ProjectMembership.user_id == user.id)
        ).all() == []
        assert database.scalars(
            select(UserToolGrant).where(UserToolGrant.user_id == user.id)
        ).all() == []

    rejected = client.post(
        "/api/v1/auth/register",
        json={
            "username": "attacker",
            "display_name": "攻击者",
            "password": "Strong-pass-123",
            "platform_role": "platform_admin",
        },
    )
    assert rejected.status_code == 422


def test_registration_mode_open_creates_session(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """开放模式注册成功后立即签发服务端 Session 和两枚认证 Cookie。"""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "session.tester",
            "display_name": "会话测试人员",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 201
    assert client.cookies.get("tp_session")
    assert client.cookies.get("tp_csrf")
    # Cookie 客户端寿命必须与服务端 7 天绝对期限一致，避免浏览器提前丢失
    # 仍然有效的会话，或在服务端失效后长期保留无效 Cookie。
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert len(set_cookie_headers) == 2
    assert all("Max-Age=604800" in header for header in set_cookie_headers)
    with database_factory() as database:
        user = database.scalar(
            select(User).where(User.username_normalized == "session.tester")
        )
        assert user is not None
        session = database.scalar(
            select(PlatformSession).where(PlatformSession.user_id == user.id)
        )
        assert session is not None


@pytest.mark.parametrize("mode", ["disabled", "invite"])
def test_registration_mode_disabled_or_invite_fails_closed(
    mode: str,
    client,
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """关闭或邀请制模式统一失败关闭，且不能写 User 或 Session。"""

    monkeypatch.setattr(get_settings(), "registration_mode", mode)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": f"blocked-{mode}",
            "display_name": "不可创建",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "REGISTRATION_UNAVAILABLE"
    with database_factory() as database:
        assert database.scalar(select(User).where(User.username_normalized == f"blocked-{mode}")) is None
        assert database.scalar(select(PlatformSession)) is None


def test_registration_rejects_blank_display_name(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """只含空白的显示名称 trim 后为空，必须在写用户前返回 422。"""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "blank-name",
            "display_name": "   ",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 422
    with database_factory() as database:
        assert database.scalar(select(User).where(User.username_normalized == "blank-name")) is None


@pytest.mark.parametrize("username", ["   ", "  a  "])
def test_registration_validates_username_length_after_trimming(
    username: str,
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """用户名必须先去除首尾空白，再按既有 3–128 位规则校验。"""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "display_name": "用户名边界",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 422
    with database_factory() as database:
        assert database.scalar(select(User)) is None


def test_duplicate_normalized_username_uses_safe_error(client) -> None:
    """大小写和首尾空格归一后的重复用户名不得暴露账号存在性。"""

    first = client.post(
        "/api/v1/auth/register",
        json={
            "username": "Safe.Name",
            "display_name": "首个用户",
            "password": "valid-pass-123",
        },
    )
    duplicate = client.post(
        "/api/v1/auth/register",
        json={
            "username": "  safe.name  ",
            "display_name": "重复用户",
            "password": "valid-pass-123",
        },
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "REGISTRATION_UNAVAILABLE"
    assert "存在" not in duplicate.json()["message"]


def test_registration_middleware_replays_body_to_pydantic(client) -> None:
    """middleware 读取计数后必须把完整 body 原样回放给注册 Schema。"""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "body-replay",
            "display_name": "请求体回放",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 201
    assert response.json()["user"]["username"] == "body-replay"


def test_registration_attempt_counts_valid_submission(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """合法注册在进入业务事务前写入 global、IP 和用户名三个桶。"""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "counted-user",
            "display_name": "计数用户",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 201
    with database_factory() as database:
        rows = list(database.scalars(select(LoginThrottle)).all())
    assert {row.key_type for row in rows} == {
        "reg_global",
        "reg_ip",
        "reg_username",
    }
    assert {row.attempt_count for row in rows} == {1}


def test_registration_attempt_counts_duplicate_username(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """业务层返回安全 409 时，两次提交仍都进入安全计数。"""

    payload = {
        "username": "duplicate-count",
        "display_name": "重复计数",
        "password": "valid-pass-123",
    }
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    assert client.post("/api/v1/auth/register", json=payload).status_code == 409

    with database_factory() as database:
        global_row = database.scalar(
            select(LoginThrottle).where(LoginThrottle.key_type == "reg_global")
        )
    assert global_row is not None
    assert global_row.attempt_count == 2


def test_registration_attempt_counts_unknown_field_submission(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """通过未知字段制造的 422 不能绕过来源和全局计数。"""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "unknown-field",
            "display_name": "未知字段",
            "password": "valid-pass-123",
            "role": "platform_admin",
        },
    )

    assert response.status_code == 422
    with database_factory() as database:
        rows = list(database.scalars(select(LoginThrottle)).all())
        audit = database.scalar(
            select(AuditLog).where(
                AuditLog.action == "auth.register",
                AuditLog.error_code == "REGISTRATION_UNKNOWN_FIELDS",
            )
        )
    assert {row.key_type for row in rows} == {
        "reg_global",
        "reg_ip",
        "reg_username",
    }
    assert audit is not None


def test_registration_attempt_counts_malformed_json_by_available_dimensions(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """畸形 JSON 只按可用的 global/IP 维度计数，并保持 422。"""

    response = client.post(
        "/api/v1/auth/register",
        content=b'{"username":"broken"',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    with database_factory() as database:
        rows = list(database.scalars(select(LoginThrottle)).all())
    assert {row.key_type for row in rows} == {"reg_global", "reg_ip"}


def test_disabled_and_invite_submissions_are_counted_without_business_writes(
    client,
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """关闭模式仍保存安全计数，但不创建任何用户或会话。"""

    monkeypatch.setattr(get_settings(), "registration_mode", "disabled")
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "disabled-count",
            "display_name": "关闭计数",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 503
    with database_factory() as database:
        assert database.scalar(select(LoginThrottle)) is not None
        assert database.scalar(select(User).where(User.username_normalized == "disabled-count")) is None
        assert database.scalar(select(PlatformSession)) is None


def test_registration_oversized_body_is_counted_then_rejected(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """超过 64 KiB 的 body 必须 drain、计 global/IP，并在业务层前返回 413。"""

    body = b'{"username":"oversized","padding":"' + b"x" * 65536 + b'"}'
    response = client.post(
        "/api/v1/auth/register",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "REGISTRATION_PAYLOAD_TOO_LARGE"
    assert response.headers["X-Request-ID"].startswith("req_")
    with database_factory() as database:
        rows = list(database.scalars(select(LoginThrottle)).all())
        audit = database.scalar(
            select(AuditLog).where(
                AuditLog.error_code == "REGISTRATION_PAYLOAD_TOO_LARGE"
            )
        )
    assert {row.key_type for row in rows} == {"reg_global", "reg_ip"}
    assert audit is not None


def test_registration_rate_limit_allows_five_and_blocks_sixth(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """相同来源的前五个 HTTP 提交放行，第六个在业务写入前返回 429。"""

    for index in range(5):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": f"rate-user-{index}",
                "display_name": f"限流用户 {index}",
                "password": "valid-pass-123",
            },
        )
        assert response.status_code == 201

    rejected = client.post(
        "/api/v1/auth/register",
        json={
            "username": "rate-user-six",
            "display_name": "第六个用户",
            "password": "valid-pass-123",
        },
    )

    assert rejected.status_code == 429
    assert rejected.json()["code"] == "REGISTRATION_RATE_LIMITED"
    with database_factory() as database:
        assert database.scalar(
            select(User).where(User.username_normalized == "rate-user-six")
        ) is None
        audit = database.scalar(
            select(AuditLog).where(
                AuditLog.error_code == "REGISTRATION_RATE_LIMITED"
            )
        )
    assert audit is not None


def test_registration_rate_limit_recovers_after_fifteen_minutes(
    client,
    monkeypatch,
) -> None:
    """来源桶在锁定和窗口都恰好满 15 分钟后恢复，不多锁一分钟。"""

    current_time = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(auth_service, "utc_now", lambda: current_time)
    headers = {"Content-Type": "application/json"}
    for _index in range(5):
        assert client.post(
            "/api/v1/auth/register", content=b'{"broken":', headers=headers
        ).status_code == 422
    assert client.post(
        "/api/v1/auth/register", content=b'{"broken":', headers=headers
    ).status_code == 429

    current_time += timedelta(minutes=15)
    assert client.post(
        "/api/v1/auth/register", content=b'{"broken":', headers=headers
    ).status_code == 422


def test_registration_global_circuit_returns_503_on_next_request(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """100 个不同来源打开全局熔断，第 101 次请求返回安全 503。"""

    for index in range(100):
        response = client.post(
            "/api/v1/auth/register",
            content=b'{"malformed":',
            headers={
                "Content-Type": "application/json",
                "X-Test-Platform-Gateway": "1",
                "X-Forwarded-For": f"198.51.100.{index}",
            },
        )
        assert response.status_code == 422

    rejected = client.post(
        "/api/v1/auth/register",
        content=b'{"malformed":',
        headers={
            "Content-Type": "application/json",
            "X-Test-Platform-Gateway": "1",
            "X-Forwarded-For": "203.0.113.250",
        },
    )

    assert rejected.status_code == 503
    assert rejected.json()["code"] == "REGISTRATION_UNAVAILABLE"
    with database_factory() as database:
        error_codes = set(
            database.scalars(
                select(AuditLog.error_code).where(
                    AuditLog.action == "auth.register.circuit"
                )
            ).all()
        )
    assert {
        "REGISTRATION_CIRCUIT_OPEN",
        "REGISTRATION_UNAVAILABLE",
    }.issubset(error_codes)


def test_registration_global_circuit_recovers_after_fifteen_minutes(
    client,
    monkeypatch,
) -> None:
    """全局熔断恰好在 15 分钟后恢复，并从新窗口重新计数。"""

    settings = get_settings()
    current_time = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(settings, "registration_global_limit", 3)
    monkeypatch.setattr(auth_service, "utc_now", lambda: current_time)
    for index in range(3):
        response = client.post(
            "/api/v1/auth/register",
            content=b'{"broken":',
            headers={
                "Content-Type": "application/json",
                "X-Test-Platform-Gateway": "1",
                "X-Forwarded-For": f"198.51.100.{index}",
            },
        )
        assert response.status_code == 422
    assert client.post(
        "/api/v1/auth/register",
        content=b'{"broken":',
        headers={
            "Content-Type": "application/json",
            "X-Test-Platform-Gateway": "1",
            "X-Forwarded-For": "203.0.113.1",
        },
    ).status_code == 503

    current_time += timedelta(minutes=15)
    assert client.post(
        "/api/v1/auth/register",
        content=b'{"broken":',
        headers={
            "Content-Type": "application/json",
            "X-Test-Platform-Gateway": "1",
            "X-Forwarded-For": "203.0.113.2",
        },
    ).status_code == 422


def test_registration_circuit_open_logs_warning_once_per_window(
    client,
    monkeypatch,
    caplog,
) -> None:
    """告警只记录熔断由关到开的边沿，熔断期内请求不重复刷屏。"""

    settings = get_settings()
    monkeypatch.setattr(settings, "registration_global_limit", 3)
    caplog.set_level("WARNING", logger="app.services.auth")
    for index in range(4):
        client.post(
            "/api/v1/auth/register",
            content=b'{"broken":',
            headers={
                "Content-Type": "application/json",
                "X-Test-Platform-Gateway": "1",
                "X-Forwarded-For": f"192.0.2.{index}",
            },
        )

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.services.auth"
        and record.getMessage() == "注册全局熔断已打开"
    ]
    assert messages == ["注册全局熔断已打开"]


def test_registration_session_factory_missing_fails_closed(
    client,
    monkeypatch,
) -> None:
    """独立计数工厂缺失时不得回退真实数据库，注册必须返回 503。"""

    monkeypatch.delattr(app.state, "registration_session_factory", raising=False)

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "no-factory",
            "display_name": "无工厂",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "REGISTRATION_UNAVAILABLE"
    assert response.headers["X-Request-ID"].startswith("req_")
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_registration_counter_database_failure_fails_closed(
    client,
    monkeypatch,
) -> None:
    """独立计数数据库异常时失败关闭，绝不能继续进入用户创建事务。"""

    def unavailable_factory():
        raise RuntimeError("registration counter unavailable")

    monkeypatch.setattr(
        app.state, "registration_session_factory", unavailable_factory
    )
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "counter-failure",
            "display_name": "计数不可用",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "REGISTRATION_UNAVAILABLE"


def test_registration_counter_wait_does_not_block_non_registration_requests(
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """注册行锁或慢数据库等待必须在线程池执行，不能卡住 ASGI 事件循环。"""

    def slow_counter(*_args, **_kwargs):
        time.sleep(0.25)
        return auth_service.RegistrationRateDecision()

    monkeypatch.setattr(auth_service, "evaluate_registration_attempt", slow_counter)
    monkeypatch.setattr(get_settings(), "registration_mode", "open")
    completed_paths: list[str] = []

    async def downstream(scope, _receive, send):
        completed_paths.append(scope["path"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = auth_service.RegistrationAttemptMiddleware(
        downstream,
        session_factory_provider=lambda: database_factory,
    )

    async def scenario() -> float:
        registration_received = False

        async def registration_receive():
            nonlocal registration_received
            if registration_received:
                return {"type": "http.disconnect"}
            registration_received = True
            return {
                "type": "http.request",
                "body": b'{"username":"slow-user"}',
                "more_body": False,
            }

        async def no_body_receive():
            return {"type": "http.disconnect"}

        async def discard_send(_message):
            return None

        registration_scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/register",
            "headers": [],
            "client": ("127.0.0.1", 10001),
            "state": {"request_id": "req_slow_registration"},
        }
        health_scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/health/live",
            "headers": [],
            "client": ("127.0.0.1", 10002),
            "state": {"request_id": "req_health"},
        }
        started_at = time.perf_counter()
        registration_task = asyncio.create_task(
            middleware(registration_scope, registration_receive, discard_send)
        )
        await asyncio.sleep(0.01)
        await middleware(health_scope, no_body_receive, discard_send)
        health_elapsed = time.perf_counter() - started_at
        await registration_task
        return health_elapsed

    elapsed = asyncio.run(scenario())

    assert "/api/v1/health/live" in completed_paths
    assert elapsed < 0.15


def test_registration_validation_and_unknown_fields_have_distinct_audit_codes(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """普通校验失败和越权未知字段使用不同安全事件码，便于告警归因。"""

    validation = client.post(
        "/api/v1/auth/register",
        json={
            "username": "short-password",
            "display_name": "普通校验",
            "password": "12345",
        },
    )
    unknown = client.post(
        "/api/v1/auth/register",
        json={
            "username": "unknown-role",
            "display_name": "未知字段",
            "password": "valid-pass-123",
            "role": "platform_admin",
        },
    )

    assert validation.status_code == 422
    assert unknown.status_code == 422
    with database_factory() as database:
        error_codes = set(
            database.scalars(
                select(AuditLog.error_code).where(
                    AuditLog.action == "auth.register"
                )
            ).all()
        )
    assert "REGISTRATION_VALIDATION_FAILED" in error_codes
    assert "REGISTRATION_UNKNOWN_FIELDS" in error_codes


def test_registration_audit_contains_no_password_hash_or_raw_token(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """注册拒绝审计不得保存请求中的明文密码、密码哈希或认证 Token。"""

    secret = "never-store-this-password"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "sensitive-audit",
            "display_name": "敏感审计",
            "password": secret,
            "role": "tester",
        },
    )
    assert response.status_code == 422

    with database_factory() as database:
        rows = list(
            database.scalars(
                select(AuditLog).where(AuditLog.action == "auth.register")
            ).all()
        )
        serialized = json.dumps(
            [
                {
                    column.name: getattr(row, column.name)
                    for column in AuditLog.__table__.columns
                }
                for row in rows
            ],
            default=str,
        )
    assert rows
    assert secret not in serialized
    assert "password_hash" not in serialized
    assert "tp_session" not in serialized
    assert "tp_csrf" not in serialized


def test_registration_response_build_failure_rolls_back_user_and_session(
    client,
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """成功响应构造失败时不得留下无法交付给客户端的用户或 Session。"""

    def fail_response_build(*_args, **_kwargs):
        raise RuntimeError("response build failed")

    monkeypatch.setattr(auth_api, "_me_response", fail_response_build)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "response-failure",
            "display_name": "响应失败",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 500
    with database_factory() as database:
        assert database.scalar(
            select(User).where(User.username_normalized == "response-failure")
        ) is None
        assert database.scalar(select(PlatformSession)) is None


def test_registration_database_error_log_hides_statement_parameters(
    client,
    database_factory: sessionmaker[Session],
    monkeypatch,
    caplog,
) -> None:
    """注册数据库异常日志不得输出用户名、显示名称或密码哈希参数。"""

    secret_hash = "never-log-this-password-hash"
    statement = "INSERT INTO users (username, display_name, password_hash) VALUES (?, ?, ?)"

    def fail_response_build(*_args, **_kwargs):
        raise IntegrityError(
            statement,
            ("sensitive-user", "敏感显示名称", secret_hash),
            RuntimeError("database rejected sensitive values"),
        )

    monkeypatch.setattr(auth_api, "_me_response", fail_response_build)
    caplog.set_level(logging.ERROR, logger="app.main")
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "sensitive-user",
            "display_name": "敏感显示名称",
            "password": "valid-pass-123",
        },
    )

    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert secret_hash not in caplog.text
    assert "sensitive-user" not in caplog.text
    assert "敏感显示名称" not in caplog.text
    assert statement not in caplog.text
    with database_factory() as database:
        assert database.scalar(
            select(User).where(User.username_normalized == "sensitive-user")
        ) is None
        assert database.scalar(select(PlatformSession)) is None


def test_non_registration_validation_error_does_not_write_registration_audit(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """全局校验处理器不能把其他接口的 422 误记成注册安全事件。"""

    assert client.post("/api/v1/auth/login", json={}).status_code == 422
    with database_factory() as database:
        assert database.scalar(
            select(AuditLog).where(AuditLog.action == "auth.register")
        ) is None


def test_registration_validation_audit_failure_preserves_422(
    client,
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """参数审计旁路失败时，调用方仍收到原始稳定 422 而不是 503/500。"""

    calls = 0

    def first_counter_then_fail():
        nonlocal calls
        calls += 1
        if calls == 1:
            return database_factory()
        raise RuntimeError("validation audit unavailable")

    monkeypatch.setattr(
        app.state, "registration_session_factory", first_counter_then_fail
    )
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "audit-failure",
            "display_name": "审计失败",
            "password": "12345",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_registration_rejection_precedence_is_mode_before_payload(
    client,
    monkeypatch,
) -> None:
    """关闭模式优先于 body 超限，避免通过响应差异探测内部处理状态。"""

    monkeypatch.setattr(get_settings(), "registration_mode", "disabled")
    body = b'{"padding":"' + b"x" * 65536 + b'"}'
    response = client.post(
        "/api/v1/auth/register",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "REGISTRATION_UNAVAILABLE"


def test_registration_middleware_drains_oversized_request_body() -> None:
    """发现 64 KiB 超限后仍读取到 more_body=False，避免污染长连接下一请求。"""

    messages = [
        {"type": "http.request", "body": b"a" * 40000, "more_body": True},
        {"type": "http.request", "body": b"b" * 40000, "more_body": True},
        {"type": "http.request", "body": b"tail", "more_body": False},
    ]
    calls = 0

    async def receive():
        nonlocal calls
        message = messages[calls]
        calls += 1
        return message

    raw_body, oversized = asyncio.run(auth_service._read_registration_body(receive))

    assert oversized is True
    assert calls == 3
    assert raw_body == b"a" * 40000


def test_registration_concurrent_counters_do_not_lose_updates(
    registration_integration_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """20 个并发首次请求不丢 global/IP 计数，阈值后也不额外创建用户。"""

    client, database_factory = registration_integration_client
    worker_count = 20
    start = threading.Barrier(worker_count)

    def submit(index: int) -> int:
        start.wait(timeout=10)
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": f"concurrent-user-{index}",
                "display_name": f"并发用户 {index}",
                "password": "valid-pass-123",
            },
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        statuses = list(executor.map(submit, range(worker_count)))

    assert statuses.count(201) == 5
    assert statuses.count(429) == 15
    assert 500 not in statuses
    assert 503 not in statuses
    with database_factory() as database:
        global_row = database.scalar(
            select(LoginThrottle).where(LoginThrottle.key_type == "reg_global")
        )
        ip_row = database.scalar(
            select(LoginThrottle).where(LoginThrottle.key_type == "reg_ip")
        )
        users = list(
            database.scalars(
                select(User).where(User.username_normalized.like("concurrent-user-%"))
            ).all()
        )
    assert global_row is not None and global_row.attempt_count == worker_count
    assert ip_row is not None and ip_row.attempt_count == 5
    assert len(users) == 5


def test_concurrent_duplicate_username_returns_201_and_safe_409(
    registration_integration_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """同名并发唯一键竞争固定收敛为一个成功和一个不泄露细节的 409。"""

    client, database_factory = registration_integration_client
    start = threading.Barrier(2)
    payload = {
        "username": "same-concurrent-user",
        "display_name": "同名并发用户",
        "password": "valid-pass-123",
    }

    def submit() -> tuple[int, dict]:
        start.wait(timeout=10)
        response = client.post("/api/v1/auth/register", json=payload)
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: submit(), range(2)))

    assert sorted(status for status, _body in results) == [201, 409]
    conflict_body = next(body for status, body in results if status == 409)
    assert conflict_body["code"] == "REGISTRATION_UNAVAILABLE"
    assert "存在" not in conflict_body["message"]
    with database_factory() as database:
        users = list(
            database.scalars(
                select(User).where(
                    User.username_normalized == "same-concurrent-user"
                )
            ).all()
        )
    assert len(users) == 1


def test_unmarked_direct_request_ignores_spoofed_forwarded_for(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """没有可信网关标记时必须忽略客户端伪造的 X-Forwarded-For。"""

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "spoof-check",
            "display_name": "来源校验",
            "password": "valid-pass-123",
        },
        headers={"X-Forwarded-For": "203.0.113.99"},
    )

    assert response.status_code == 201
    with database_factory() as database:
        ip_row = database.scalar(
            select(LoginThrottle).where(LoginThrottle.key_type == "reg_ip")
        )
    assert ip_row is not None
    assert ip_row.key_hash == token_hash("reg_ip:testclient")


def test_catalog_returns_access_source_and_management_boundary(
    client,
    database_factory: sessionmaker[Session],
) -> None:
    """工具卡片必须展示访问来源，公共工具不能产生管理入口。"""

    with database_factory() as database:
        database.add(
            Tool(
                id="public-tool",
                name="公共工具",
                description="test",
                entry_url="/public-tool/",
                health_url="http://public-tool/health",
                short_code="PUBLIC",
                icon_key="test",
                category="test",
                features=[],
                access_scope="public",
                project_id=None,
                public_safety_policy_status="complete",
                public_safety_policy={
                    "request_quota_per_minute": 10,
                    "task_quota_per_day": 20,
                    "cost_quota_daily": 5,
                    "cost_reservation_per_task": 0.25,
                    "real_execution_enabled": False,
                    "target_allowlist": ["example.test"],
                },
            )
        )
        database.commit()

    # 测试客户端的兼容用户先切换到新 tester 模型，目录必须走新授权内核。
    client.get("/api/v1/auth/me")
    with database_factory() as database:
        user = database.get(User, "test-user")
        user.platform_role = "tester"
        database.commit()

    response = client.get("/api/v1/tools")
    assert response.status_code == 200
    item = next(row for row in response.json()["items"] if row["id"] == "public-tool")
    assert item["access_source"] == "public"
    assert item["can_manage"] is False
