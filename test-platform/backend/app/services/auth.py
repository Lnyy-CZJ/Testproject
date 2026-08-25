from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import generate_token, hash_password, new_id, normalize_username, token_hash, verify_password
from app.core.errors import PlatformError
from app.models.identity import LoginThrottle, PlatformSession, RuntimeContext, ToolClient, User


DUMMY_PASSWORD_HASH = hash_password("dummy-password-never-used")


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """把 SQLite 返回的无时区时间解释为 UTC，保持跨数据库测试一致。"""

    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _throttle_key(kind: str, value: str) -> tuple[str, str]:
    """返回不暴露用户名/IP 原文的登录限速键。"""

    return kind, token_hash(f"{kind}:{value}")


def is_login_blocked(database: Session, username: str, ip_address: str) -> bool:
    """检查用户名或 IP 是否仍处于登录锁定期。"""

    now = utc_now()
    for kind, value in (("username", normalize_username(username)), ("ip", ip_address)):
        key_type, key_hash = _throttle_key(kind, value)
        row = database.scalar(
            select(LoginThrottle).where(
                LoginThrottle.key_type == key_type,
                LoginThrottle.key_hash == key_hash,
            )
        )
        if row and as_utc(row.blocked_until) and as_utc(row.blocked_until) > now:
            return True
    return False


def record_login_failure(database: Session, username: str, ip_address: str, settings: Settings) -> None:
    """更新用户名和 IP 两个维度的持久化失败窗口。"""

    now = utc_now()
    window = timedelta(minutes=settings.login_failure_window_minutes)
    for kind, value in (("username", normalize_username(username)), ("ip", ip_address)):
        key_type, key_hash = _throttle_key(kind, value)
        row = database.scalar(
            select(LoginThrottle).where(
                LoginThrottle.key_type == key_type,
                LoginThrottle.key_hash == key_hash,
            )
        )
        if row is None:
            row = LoginThrottle(
                key_type=key_type,
                key_hash=key_hash,
                window_started_at=now,
                attempt_count=0,
            )
            database.add(row)
        elif as_utc(row.window_started_at) + window <= now:
            row.window_started_at = now
            row.attempt_count = 0
            row.blocked_until = None
        row.attempt_count += 1
        if row.attempt_count >= settings.login_failure_limit:
            row.blocked_until = now + timedelta(minutes=settings.login_lock_minutes)


def clear_login_failures(database: Session, username: str, ip_address: str) -> None:
    """登录成功后清理当前用户名和 IP 的失败窗口。"""

    hashes = [_throttle_key("username", normalize_username(username))[1], _throttle_key("ip", ip_address)[1]]
    database.execute(delete(LoginThrottle).where(LoginThrottle.key_hash.in_(hashes)))


def authenticate(database: Session, username: str, password: str) -> User | None:
    """验证用户密码和状态；用户不存在时执行等价哈希校验。"""

    user = database.scalar(select(User).where(User.username_normalized == normalize_username(username)))
    password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    if not verify_password(password_hash, password) or user is None or user.status != "active":
        return None
    return user


def create_session(
    database: Session,
    user: User,
    settings: Settings,
    ip_address: str,
    user_agent: str,
) -> tuple[PlatformSession, str, str]:
    """创建服务端会话并返回仅供 Cookie 使用的两个原始 Token。"""

    now = utc_now()
    session_token = generate_token()
    csrf_token = generate_token()
    row = PlatformSession(
        id=new_id("ses"),
        token_hash=token_hash(session_token),
        csrf_hash=token_hash(csrf_token),
        user_id=user.id,
        idle_expires_at=now + timedelta(hours=settings.session_idle_hours),
        absolute_expires_at=now + timedelta(hours=settings.session_absolute_hours),
        last_seen_at=now,
        ip_address=ip_address,
        user_agent_hash=token_hash(user_agent),
    )
    database.add(row)
    return row, session_token, csrf_token


def resolve_session(database: Session, raw_token: str, settings: Settings) -> tuple[PlatformSession, User] | None:
    """解析、校验并按受控频率触摸服务端会话。"""

    if not raw_token:
        return None
    row = database.scalar(select(PlatformSession).where(PlatformSession.token_hash == token_hash(raw_token)))
    if row is None or row.revoked_at is not None:
        return None
    now = utc_now()
    if as_utc(row.idle_expires_at) <= now or as_utc(row.absolute_expires_at) <= now:
        return None
    user = database.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    if as_utc(row.last_seen_at) + timedelta(seconds=settings.session_touch_interval_seconds) <= now:
        row.last_seen_at = now
        row.idle_expires_at = min(
            now + timedelta(hours=settings.session_idle_hours),
            as_utc(row.absolute_expires_at),
        )
    return row, user


def revoke_user_sessions(database: Session, user_id: str) -> int:
    """撤销用户全部尚未撤销的会话并返回数量。"""

    rows = list(database.scalars(select(PlatformSession).where(PlatformSession.user_id == user_id, PlatformSession.revoked_at.is_(None))).all())
    now = utc_now()
    for row in rows:
        row.revoked_at = now
    return len(rows)


def validate_runtime_context(
    database: Session,
    runtime_context_id: str,
    client: ToolClient,
    tool_id: str,
) -> RuntimeContext:
    """重新校验 Runtime Context 及其会话、用户、权限和工具环境绑定。

    参数说明:
        runtime_context_id: 工具任务保存的不透明 Context ID。
        client/tool_id: 已认证 Tool Client 与当前 URL 工具作用域。
    返回值:
        RuntimeContext: 校验通过并已更新 ``last_used_at`` 的上下文对象。
    异常说明:
        RUNTIME_CONTEXT_EXPIRED: Context 自身 TTL 已结束。
        RUNTIME_CONTEXT_INVALID: 作用域、用户状态或紧急撤销标记不再有效。
    """

    if client.status != "active" or client.tool_id != tool_id:
        raise PlatformError(403, "RUNTIME_CONTEXT_INVALID", "用户上下文无效或与工具不匹配")
    # 先以已认证 Client 的工具与环境缩小范围，再匹配随机 Context ID，确保同一
    # ID 不能被其他工具或环境当作对象存在性探针。
    row = database.scalar(select(RuntimeContext).where(
        RuntimeContext.tool_id == client.tool_id,
        RuntimeContext.environment_id == client.environment_id,
        RuntimeContext.id == runtime_context_id,
    ))
    if row is None or row.status != "active":
        raise PlatformError(403, "RUNTIME_CONTEXT_INVALID", "用户上下文无效或与工具不匹配")
    now = utc_now()
    if as_utc(row.expires_at) <= now:
        row.status = "expired"
        raise PlatformError(401, "RUNTIME_CONTEXT_EXPIRED", "用户上下文已过期，请重新提交")
    user = database.get(User, row.user_id)
    if (
        row.emergency_revoked_at is not None
        or user is None
        or user.status != "active"
    ):
        raise PlatformError(403, "RUNTIME_CONTEXT_INVALID", "用户上下文无效或与工具不匹配")
    row.last_used_at = now
    return row
