from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings, get_settings
from app.core.security import generate_token, hash_password, new_id, normalize_username, token_hash, verify_password
from app.core.errors import PlatformError
from app.models.identity import LoginThrottle, PlatformSession, RuntimeContext, ToolClient, User
from app.services.audit import add_audit_event


DUMMY_PASSWORD_HASH = hash_password("dummy-password")
REGISTRATION_PATH = "/api/v1/auth/register"
REGISTRATION_MAX_BODY_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class RegistrationRateDecision:
    """描述一次注册提交在计数完成后的拒绝类型与熔断边沿。"""

    blocked_kind: Literal["rate", "circuit"] | None = None
    circuit_opened: bool = False


def registration_throttle_keys(
    *,
    username: str | None,
    ip_address: str | None,
    device_signal: str | None,
) -> list[tuple[str, str]]:
    """按固定锁序返回注册计数键，数据库中只保存 SHA-256 摘要。

    参数说明:
        username: 可从完整 JSON 中安全提取的用户名；缺失或空值时跳过该维度。
        ip_address: 经可信网关解析后的来源地址；不可用时跳过该维度。
        device_signal: 未来可信设备信号；当前网关固定清除，因此通常为 ``None``。
    返回值:
        list[tuple[str, str]]: global、IP、用户名、设备顺序的 ``reg_*`` 键。
    """

    values: list[tuple[str, str]] = [("reg_global", "*")]
    if ip_address:
        values.append(("reg_ip", ip_address))
    if username:
        normalized = normalize_username(username)
        if normalized:
            values.append(("reg_username", normalized))
    if device_signal:
        values.append(("reg_device", device_signal))
    return [_throttle_key(kind, value) for kind, value in values]


def evaluate_registration_attempt(
    database: Session,
    *,
    username: str | None,
    ip_address: str | None,
    device_signal: str | None,
    settings: Settings,
) -> RegistrationRateDecision:
    """原子更新一次注册提交的全局与来源计数。

    参数说明:
        database: 调用方拥有事务边界的数据库会话。
        username/ip_address/device_signal: 当前提交可安全获得的计数维度。
        settings: 已通过交叉校验的限流与熔断配置。
    返回值:
        RegistrationRateDecision: 已生效的拒绝类型，以及本次是否刚打开熔断。
    异常说明:
        SQLAlchemyError: 查询、行锁或首次插入冲突继续抛出，由 middleware
            回滚并按最多一次重试策略失败关闭。

    设计说明:
        本函数只 ``flush``，不提交、回滚或关闭会话。固定锁序和独立事务使
        计数不会因后续 409/422 或用户创建事务回滚而丢失。
    """

    now = utc_now()
    keyed_rows: list[tuple[str, LoginThrottle]] = []
    for key_type, key_hash in registration_throttle_keys(
        username=username,
        ip_address=ip_address,
        device_signal=device_signal,
    ):
        row = database.scalar(
            select(LoginThrottle)
            .where(
                LoginThrottle.key_type == key_type,
                LoginThrottle.key_hash == key_hash,
            )
            .with_for_update()
        )
        if row is None:
            row = LoginThrottle(
                key_type=key_type,
                key_hash=key_hash,
                window_started_at=now,
                attempt_count=0,
            )
            database.add(row)
        keyed_rows.append((key_type, row))

    global_row = keyed_rows[0][1]
    global_blocked_until = as_utc(global_row.blocked_until)
    if global_blocked_until is not None and global_blocked_until > now:
        database.flush()
        return RegistrationRateDecision(blocked_kind="circuit")

    global_window = timedelta(minutes=settings.registration_global_window_minutes)
    if (
        as_utc(global_row.window_started_at) + global_window <= now
        and (global_blocked_until is None or global_blocked_until <= now)
    ):
        global_row.window_started_at = now
        global_row.attempt_count = 0
        global_row.blocked_until = None

    source_rows = [row for _, row in keyed_rows[1:]]
    source_window = timedelta(minutes=settings.registration_rate_window_minutes)
    for row in source_rows:
        blocked_until = as_utc(row.blocked_until)
        if (
            as_utc(row.window_started_at) + source_window <= now
            and (blocked_until is None or blocked_until <= now)
        ):
            row.window_started_at = now
            row.attempt_count = 0
            row.blocked_until = None

    global_row.attempt_count += 1
    circuit_opened = False
    if global_row.attempt_count >= settings.registration_global_limit:
        global_row.blocked_until = now + timedelta(
            minutes=settings.registration_global_lock_minutes
        )
        circuit_opened = True

    if any(
        as_utc(row.blocked_until) is not None
        and as_utc(row.blocked_until) > now
        for row in source_rows
    ):
        database.flush()
        return RegistrationRateDecision(
            blocked_kind="rate",
            circuit_opened=circuit_opened,
        )

    for row in source_rows:
        row.attempt_count += 1
        if row.attempt_count >= settings.registration_rate_limit:
            row.blocked_until = now + timedelta(
                minutes=settings.registration_lock_minutes
            )

    database.flush()
    return RegistrationRateDecision(circuit_opened=circuit_opened)


def resolve_client_ip(
    *,
    forwarded_for: str | None,
    peer_host: str | None,
    gateway_marker: str | None,
) -> str | None:
    """只在可信网关标记存在时接受单值 X-Forwarded-For。

    参数说明:
        forwarded_for: 网关应覆盖为连接地址的请求头；包含代理链时视为不可信。
        peer_host: ASGI 连接对端地址，直连或头无效时使用。
        gateway_marker: 仅由 Nginx 写入的 ``X-Test-Platform-Gateway`` 标记。
    返回值:
        str | None: 可用于哈希计数和会话审计的来源地址。
    """

    candidate = (forwarded_for or "").strip()
    if gateway_marker == "1" and candidate and "," not in candidate:
        return candidate
    return peer_host or None


def extract_registration_username(raw_body: bytes) -> str | None:
    """只从完整 JSON 对象提取并规范化 username，不读取其他字段值。"""

    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    username = payload.get("username")
    if not isinstance(username, str):
        return None
    normalized = normalize_username(username)
    return normalized or None


def _registration_request_id(scope: Scope) -> str:
    """读取外层 RequestIdMiddleware 的 ID，缺失时安全补齐。"""

    state = scope.setdefault("state", {})
    request_id = state.get("request_id")
    if not isinstance(request_id, str) or not request_id.startswith("req_"):
        request_id = f"req_{uuid.uuid4().hex}"
        state["request_id"] = request_id
    return request_id


def _registration_error_response(
    scope: Scope,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    """构造 middleware 可直接发送的统一安全错误响应。"""

    request_id = _registration_request_id(scope)
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


async def _read_registration_body(receive: Receive) -> tuple[bytes, bool]:
    """读取并 drain 注册 body，返回不超过上限的完整内容和超限标记。"""

    chunks: list[bytes] = []
    total_size = 0
    oversized = False
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        if message["type"] != "http.request":
            continue
        chunk = message.get("body", b"")
        total_size += len(chunk)
        if total_size <= REGISTRATION_MAX_BODY_BYTES:
            chunks.append(chunk)
        else:
            oversized = True
        if not message.get("more_body", False):
            break
    return b"".join(chunks), oversized


def _registration_audit(
    database: Session,
    request: Request,
    *,
    action: str,
    error_code: str,
) -> None:
    """写入不含请求体、用户名、密码或计数值的注册安全事件。"""

    add_audit_event(
        database,
        action=action,
        resource_type="user",
        outcome="denied",
        request=request,
        actor_type="anonymous",
        error_code=error_code,
    )


class RegistrationAttemptMiddleware:
    """在 Pydantic 前统计全部注册提交，并执行限流、熔断和 body 上限。"""

    def __init__(
        self,
        app: ASGIApp,
        session_factory_provider: Callable[[], sessionmaker[Session]],
    ) -> None:
        """保存下游应用和动态数据库工厂 provider，不缓存真实会话工厂。"""

        self.app = app
        self.session_factory_provider = session_factory_provider

    def _record_attempt(
        self,
        *,
        scope: Scope,
        request: Request,
        username: str | None,
        ip_address: str | None,
        oversized: bool,
        settings: Settings,
    ) -> RegistrationRateDecision | None:
        """在线程池内完成一次注册计数、拒绝审计和事务收尾。

        Session 的创建、使用、提交/回滚与关闭全部发生在同一工作线程，既不
        跨线程传递 SQLAlchemy 状态，也不会让数据库行锁等待阻塞 ASGI 事件循环。
        返回 ``None`` 表示计数基础设施不可用，调用方必须失败关闭为 503。
        """

        for attempt in range(2):
            database: Session | None = None
            try:
                factory = self.session_factory_provider()
                if not callable(factory):
                    raise RuntimeError("registration session factory unavailable")
                database = factory()
                decision = evaluate_registration_attempt(
                    database,
                    username=username,
                    ip_address=ip_address,
                    device_signal=None,
                    settings=settings,
                )
                if decision.circuit_opened:
                    _registration_audit(
                        database,
                        request,
                        action="auth.register.circuit",
                        error_code="REGISTRATION_CIRCUIT_OPEN",
                    )
                    logger.warning(
                        "注册全局熔断已打开",
                        extra={"request_id": _registration_request_id(scope)},
                    )

                if settings.registration_mode != "open":
                    mode_error = (
                        "REGISTRATION_MODE_DISABLED"
                        if settings.registration_mode == "disabled"
                        else "REGISTRATION_INVITE_UNAVAILABLE"
                    )
                    _registration_audit(
                        database,
                        request,
                        action="auth.register",
                        error_code=mode_error,
                    )
                elif decision.blocked_kind == "circuit":
                    _registration_audit(
                        database,
                        request,
                        action="auth.register.circuit",
                        error_code="REGISTRATION_UNAVAILABLE",
                    )
                elif decision.blocked_kind == "rate":
                    _registration_audit(
                        database,
                        request,
                        action="auth.register",
                        error_code="REGISTRATION_RATE_LIMITED",
                    )
                elif oversized:
                    _registration_audit(
                        database,
                        request,
                        action="auth.register",
                        error_code="REGISTRATION_PAYLOAD_TOO_LARGE",
                    )
                database.commit()
                return decision
            except IntegrityError:
                if database is not None:
                    database.rollback()
                if attempt == 0:
                    continue
                # 注册安全链路的异常对象可能包含数据库 statement/params；
                # 这里只保留固定文案和 request_id，避免日志泄露内部值。
                logger.error(
                    "注册计数首次桶并发冲突重试失败",
                    extra={"request_id": _registration_request_id(scope)},
                )
                return None
            except Exception:
                if database is not None:
                    database.rollback()
                logger.error(
                    "注册安全计数不可用",
                    extra={"request_id": _registration_request_id(scope)},
                )
                return None
            finally:
                if database is not None:
                    database.close()
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """仅拦截注册 POST，其他 ASGI scope 原样透传。

        数据库计数事务先于业务事务提交。首次桶插入若发生唯一键竞争，只使用
        provider 创建全新 Session 重试一次；任何计数存储异常均失败关闭为 503。
        """

        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != REGISTRATION_PATH
        ):
            await self.app(scope, receive, send)
            return

        raw_body, oversized = await _read_registration_body(receive)
        request = Request(scope)
        peer = scope.get("client")
        peer_host = peer[0] if peer else None
        ip_address = resolve_client_ip(
            forwarded_for=request.headers.get("x-forwarded-for"),
            peer_host=peer_host,
            gateway_marker=request.headers.get("x-test-platform-gateway"),
        )
        username = None if oversized else extract_registration_username(raw_body)
        settings = get_settings()
        decision = await run_in_threadpool(
            self._record_attempt,
            scope=scope,
            request=request,
            username=username,
            ip_address=ip_address,
            oversized=oversized,
            settings=settings,
        )
        if decision is None:
            response = _registration_error_response(
                scope,
                status_code=503,
                code="REGISTRATION_UNAVAILABLE",
                message="暂未开放注册，请稍后重试",
            )
            await response(scope, receive, send)
            return
        if settings.registration_mode != "open":
            response = _registration_error_response(
                scope,
                status_code=503,
                code="REGISTRATION_UNAVAILABLE",
                message="暂未开放注册，请稍后重试",
            )
            await response(scope, receive, send)
            return
        if decision.blocked_kind == "circuit":
            response = _registration_error_response(
                scope,
                status_code=503,
                code="REGISTRATION_UNAVAILABLE",
                message="暂未开放注册，请稍后重试",
            )
            await response(scope, receive, send)
            return
        if decision.blocked_kind == "rate":
            response = _registration_error_response(
                scope,
                status_code=429,
                code="REGISTRATION_RATE_LIMITED",
                message="操作过于频繁，请稍后重试",
            )
            await response(scope, receive, send)
            return
        if oversized:
            response = _registration_error_response(
                scope,
                status_code=413,
                code="REGISTRATION_PAYLOAD_TOO_LARGE",
                message="请求内容过大",
            )
            await response(scope, receive, send)
            return

        replayed = False

        async def replay_receive() -> dict:
            """向下游只回放一次已完整缓存的注册请求体。"""

            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": raw_body, "more_body": False}

        await self.app(scope, replay_receive, send)


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
    *,
    for_update: bool = False,
) -> RuntimeContext:
    """重新校验 Runtime Context 及其会话、用户、权限和工具环境绑定。

    参数说明:
        runtime_context_id: 工具任务保存的不透明 Context ID。
        client/tool_id: 已认证 Tool Client 与当前 URL 工具作用域。
        for_update: 是否锁定 Context 行。仅 dispatch 前的原子重物化使用，
            普通 Execution Lease 校验保持无锁读取。
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
    statement = select(RuntimeContext).where(
        RuntimeContext.tool_id == client.tool_id,
        RuntimeContext.environment_id == client.environment_id,
        RuntimeContext.id == runtime_context_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = database.scalar(statement)
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
