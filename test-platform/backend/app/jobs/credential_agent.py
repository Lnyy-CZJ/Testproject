from __future__ import annotations

import signal
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.redaction import redact
from app.db.session import SessionLocal
from app.models.configuration import (
    ConfigActivation,
    ConfigDefinition,
    ConfigReleaseItem,
    Credential,
    CredentialItem,
    Secret,
    SecretVersion,
)
from app.services.audit import add_audit_event
from app.services.secret_store import decrypt_secret, load_secret_cipher, replace_secret


RUNNING = True


def _stop(_signum: int, _frame: object) -> None:
    """响应容器终止信号，让当前短任务完成后安全退出。"""

    global RUNNING
    RUNNING = False


def _as_datetime(value: Any) -> datetime:
    """解析 Gateway 毫秒时间戳或 Admin ISO 时间，统一转换为 UTC。"""

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, UTC)
    if isinstance(value, str) and value.strip():
        normalized = value.strip()
        try:
            # dotenv 中的 Gateway 毫秒时间戳天然是字符串，必须与 JSON 数值
            # 使用相同解析规则，不能误交给 ISO 日期解析器。
            return datetime.fromtimestamp(float(normalized) / 1000, UTC)
        except (ValueError, OverflowError, OSError):
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    raise ValueError("凭证响应缺少有效过期时间")


def _definition_maps(database: Session, credential: Credential) -> tuple[dict[str, ConfigDefinition], dict[str, ConfigDefinition]]:
    """返回凭证工具的普通配置和 Secret 定义映射。"""

    rows = database.scalars(select(ConfigDefinition).where(
        ConfigDefinition.owner_type == "tool",
        ConfigDefinition.owner_id == credential.tool_id,
    )).all()
    return (
        {row.key: row for row in rows if row.sensitivity == "normal"},
        {row.key: row for row in rows if row.sensitivity == "secret"},
    )


def _runtime_inputs(database: Session, credential: Credential) -> tuple[dict[str, Any], dict[str, str]]:
    """从当前 Release 和 Secret 版本读取单次刷新内存快照。"""

    normal_definitions, secret_definitions = _definition_maps(database, credential)
    normal: dict[str, Any] = {
        key: definition.default_value
        for key, definition in normal_definitions.items()
        if definition.default_value is not None
    }
    activation = database.scalar(select(ConfigActivation).where(
        ConfigActivation.environment_id == credential.environment_id,
        ConfigActivation.owner_type == "tool",
        ConfigActivation.owner_id == credential.tool_id,
    ))
    if activation:
        items = database.scalars(select(ConfigReleaseItem).where(
            ConfigReleaseItem.release_id == activation.active_release_id,
        )).all()
        by_id = {row.id: row for row in normal_definitions.values()}
        for item in items:
            if item.definition_id in by_id and item.value_json is not None:
                normal[by_id[item.definition_id].key] = item.value_json
    cipher = load_secret_cipher(get_settings())
    secrets: dict[str, str] = {}
    by_definition = {row.id: key for key, row in secret_definitions.items()}
    rows = database.scalars(select(Secret).where(
        Secret.environment_id == credential.environment_id,
        Secret.owner_type == "tool",
        Secret.owner_id == credential.tool_id,
    )).all()
    for row in rows:
        key = by_definition.get(row.definition_id)
        if key and row.current_version_id:
            secrets[key] = decrypt_secret(database, cipher, row)
    return normal, secrets


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """执行一次受控身份请求，错误不包含请求体或 Secret。"""

    response = httpx.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("凭证接口响应不是 JSON 对象")
    return body


def _envelope_data(body: dict[str, Any], request_id: str) -> dict[str, Any]:
    """按请求 ID 匹配 Gateway 内层响应并校验内外层成功状态。"""

    if body.get("code") != 0:
        raise ValueError("凭证接口外层返回失败")
    responses = body.get("responses")
    item = next((row for row in responses if isinstance(row, dict) and row.get("id") == request_id), None) if isinstance(responses, list) else None
    if not item or item.get("success") is not True or item.get("code", 0) != 0 or not isinstance(item.get("data"), dict):
        raise ValueError("凭证接口内层返回失败")
    return item["data"]


def _gateway_session(normal: dict[str, Any], secrets: dict[str, str]) -> dict[str, Any]:
    """优先 RefreshSession；Refresh 不可用时调用正式匿名建会话接口。"""

    url = str(normal.get("SEARCH_API_URL") or normal.get("GATEWAY_API_URL") or "").strip()
    if not url:
        raise ValueError("缺少 Gateway 会话接口地址")
    now = datetime.now(UTC)
    refresh_expires = None
    if secrets.get("REFRESH_EXPIRES_TIME"):
        refresh_expires = _as_datetime(secrets["REFRESH_EXPIRES_TIME"])
    comm = {
        "auth_token": secrets.get("AUTH_TOKEN", ""),
        "device_id": secrets.get("DEVICE_ID", ""),
        "install_id": "",
        "client_request_id": f"gw_req_{uuid.uuid4().hex}",
        "trace_id": "",
        "platform": str(normal.get("PLATFORM", "ios")),
        "app_version": str(normal.get("APP_VERSION", "1.0.0")),
        "locale": str(normal.get("LOCALE", "zh-Hans-CN")),
        "timezone": str(normal.get("TIMEZONE", "UTC+08:00")),
    }

    def invoke(method: str) -> dict[str, Any]:
        """使用唯一请求 ID 调用一次会话方法并返回已校验数据。"""

        request_id = f"req_{uuid.uuid4().hex}"
        params = {"refresh_token": secrets["REFRESH_TOKEN"]} if method == "RefreshSession" else {"consent_policy_version": date.today().isoformat()}
        body = _post_json(url, {"comm": comm, "requests": [{
            "id": request_id,
            "service_name": "tool.identity.IdentityService",
            "method_name": method,
            "params": params,
        }]})
        return _envelope_data(body, request_id)

    can_refresh = bool(secrets.get("REFRESH_TOKEN")) and (refresh_expires is None or refresh_expires > now)
    if can_refresh:
        try:
            data = invoke("RefreshSession")
        except (httpx.HTTPError, ValueError):
            # Refresh Token 被提前撤销时，立即回退到正式建会话能力。
            data = invoke("CreateAnonymousSession")
    else:
        data = invoke("CreateAnonymousSession")
    required = {"access_token", "refresh_token", "expires_time", "refresh_expires_time", "user_id"}
    if not required.issubset(data):
        raise ValueError("会话响应缺少必需字段")
    return {
        "AUTH_TOKEN": str(data["access_token"]),
        "REFRESH_TOKEN": str(data["refresh_token"]),
        "USER_ID": str(data["user_id"]),
        "expires_at": _as_datetime(data["expires_time"]),
        "refresh_expires_at": _as_datetime(data["refresh_expires_time"]),
        "EXPIRES_TIME": data["expires_time"],
        "REFRESH_EXPIRES_TIME": data["refresh_expires_time"],
    }


def _admin_login(normal: dict[str, Any], secrets: dict[str, str]) -> dict[str, Any]:
    """使用专用服务账号调用稳定 Admin Login 契约。"""

    url = str(normal.get("ADMIN_LOGIN_API_URL") or normal.get("SEARCH_ADMIN_LOGIN_API_URL") or "").strip()
    username = secrets.get("ADMIN_USERNAME") or secrets.get("SEARCH_ADMIN_USERNAME")
    password = secrets.get("ADMIN_PASSWORD") or secrets.get("SEARCH_ADMIN_PASSWORD")
    if not url or not username or not password:
        raise ValueError("缺少 Admin Login 地址或服务账号")
    body = _post_json(url, {
        "client_request_id": f"admin_{uuid.uuid4().hex}", "method_name": "Login",
        "reason": "", "params": {"username": username, "password": password},
    })
    responses = body.get("responses")
    item = responses[0] if body.get("code") == 0 and isinstance(responses, list) and responses else None
    data = item.get("data") if isinstance(item, dict) and item.get("success") is True and item.get("code", 0) == 0 else None
    operator = data.get("operator") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(operator, dict):
        raise ValueError("Admin Login 响应协议不正确")
    required = (data.get("session_token"), data.get("expire_time"), operator.get("operator_id"), operator.get("operator_name"))
    if not all(isinstance(value, str) and value for value in required):
        raise ValueError("Admin Login 响应缺少必需字段")
    return {
        "ADMIN_SESSION_TOKEN": required[0], "expires_at": _as_datetime(required[1]),
        "operator_id": required[2], "operator_name": required[3],
    }


def _activate(database: Session, credential: Credential, expected_version: int, values: dict[str, Any]) -> None:
    """在单一事务中创建加密 Secret 版本并激活新 Credential 版本。"""

    database.refresh(credential)
    if credential.current_version != expected_version:
        # 其他任务已原子写入更新版本；释放本次租约并保留新版本状态。
        credential.refresh_lease_until = None
        credential.refresh_owner = None
        return
    _, definitions = _definition_maps(database, credential)
    cipher = load_secret_cipher(get_settings())
    new_version = expected_version + 1
    for key, value in values.items():
        if key in {"expires_at", "refresh_expires_at"}:
            continue
        definition = definitions.get(key)
        if definition and isinstance(value, (str, int)):
            secret = database.scalar(select(Secret).where(
                Secret.environment_id == credential.environment_id,
                Secret.owner_type == "tool", Secret.owner_id == credential.tool_id,
                Secret.definition_id == definition.id,
            ))
            if secret is None:
                secret = Secret(
                    id=f"sec_{uuid.uuid4().hex}", environment_id=credential.environment_id,
                    owner_type="tool", owner_id=credential.tool_id,
                    definition_id=definition.id, status="missing",
                )
                database.add(secret)
                database.flush()
            secret_version = replace_secret(database, cipher, secret, str(value), "credential-agent")
            database.flush()
            database.add(CredentialItem(
                credential_id=credential.id, credential_version=new_version,
                key=key, secret_version_id=secret_version.id,
            ))
        elif key in {"operator_id", "operator_name"}:
            database.add(CredentialItem(
                credential_id=credential.id, credential_version=new_version,
                key=key, value_json=value,
            ))
    credential.current_version = new_version
    credential.expires_at = values.get("expires_at")
    credential.refresh_expires_at = values.get("refresh_expires_at")
    credential.status = "healthy"
    credential.last_error_code = None
    credential.last_checked_at = datetime.now(UTC)
    credential.refresh_lease_until = None
    credential.refresh_owner = None
    add_audit_event(
        database, action="credential.refresh", resource_type="credential",
        resource_id=credential.id, tool_id=credential.tool_id,
        environment_id=credential.environment_id, outcome="success",
        actor_type="service", actor_id="credential-agent",
        after={"version": new_version, "status": "healthy"},
    )


def process_one() -> bool:
    """抢占一个到期凭证租约，网络请求在短数据库事务之外执行。"""

    settings = get_settings()
    now = datetime.now(UTC)
    owner = f"agent_{uuid.uuid4().hex}"
    with SessionLocal() as database:
        retry_before = now - timedelta(seconds=settings.credential_agent_interval_seconds)
        row = database.scalar(select(Credential).where(
            or_(Credential.refresh_lease_until.is_(None), Credential.refresh_lease_until < now),
            or_(
                Credential.status.in_(["pending_validation", "expiring", "expired"]),
                and_(
                    Credential.status == "action_required",
                    or_(Credential.last_checked_at.is_(None), Credential.last_checked_at <= retry_before),
                ),
                and_(
                    Credential.status.in_(["healthy", "refreshing", "missing"]),
                    or_(
                        Credential.expires_at.is_(None),
                        Credential.expires_at <= now + timedelta(seconds=settings.credential_refresh_window_seconds),
                    ),
                ),
            ),
        ).with_for_update(skip_locked=True).limit(1))
        if row is None:
            return False
        row.refresh_owner = owner
        row.refresh_lease_until = now + timedelta(minutes=2)
        row.status = "refreshing"
        credential_id = row.id
        expected_version = row.current_version
        normal, secrets = _runtime_inputs(database, row)
        database.commit()
    try:
        values = _gateway_session(normal, secrets) if row.provider_type == "gateway_session" else _admin_login(normal, secrets)
        with SessionLocal() as database:
            current = database.get(Credential, credential_id)
            if current and current.refresh_owner == owner:
                _activate(database, current, expected_version, values)
                database.commit()
    except Exception as exc:
        with SessionLocal() as database:
            current = database.get(Credential, credential_id)
            if current and current.refresh_owner == owner:
                current.status = "action_required"
                current.last_error_code = f"CREDENTIAL_REFRESH_{type(exc).__name__.upper()}"
                current.last_checked_at = datetime.now(UTC)
                current.refresh_lease_until = None
                current.refresh_owner = None
                add_audit_event(
                    database, action="credential.refresh", resource_type="credential",
                    resource_id=current.id, tool_id=current.tool_id,
                    environment_id=current.environment_id, outcome="failed",
                    error_code="CREDENTIAL_REFRESH_FAILED", actor_type="service",
                    actor_id="credential-agent", metadata=redact({"exception_type": type(exc).__name__}),
                )
                database.commit()
    return True


def main() -> None:
    """每分钟扫描临期凭证；不监听端口，不执行任何工具测试任务。"""

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    interval = get_settings().credential_agent_interval_seconds
    while RUNNING:
        while RUNNING and process_one():
            pass
        for _ in range(max(1, interval)):
            if not RUNNING:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
