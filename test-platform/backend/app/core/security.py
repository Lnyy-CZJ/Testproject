from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def normalize_username(value: str) -> str:
    """
    标准化登录名用于唯一比较。

    参数说明:
        value: 用户输入的登录名。
    返回值:
        str: 去除首尾空白并转为小写的登录名。
    """

    return value.strip().lower()


def hash_password(password: str) -> str:
    """
    使用 Argon2id 生成不可逆密码哈希。

    参数说明:
        password: 12 到 256 字符的明文密码。
    返回值:
        str: 可安全落库的 Argon2 哈希。
    异常说明:
        ValueError: 密码长度不满足要求。
    """

    if not 12 <= len(password) <= 256:
        raise ValueError("密码长度必须为 12 到 256 个字符")
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """以常量时间语义验证密码，非法哈希安全返回 False。"""

    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_token() -> str:
    """生成至少 256 位熵的不透明 Token。"""

    return secrets.token_urlsafe(48)


def token_hash(value: str) -> str:
    """计算不透明 Token 的固定长度 SHA-256 哈希。"""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def secure_equals(left: str, right: str) -> bool:
    """使用常量时间比较两个字符串。"""

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def new_id(prefix: str) -> str:
    """生成带业务前缀且不可预测的稳定标识。"""

    return f"{prefix}_{uuid.uuid4().hex}"


class UserContextTokenError(ValueError):
    """签名用户上下文结构、签名或作用域无效。"""


class UserContextTokenExpired(UserContextTokenError):
    """签名用户上下文已超过其短期有效时间。"""


def load_user_context_signing_key(path: str) -> bytes:
    """从仅当前用户可读的独立文件加载 HMAC-SHA256 密钥。

    异常说明:
        OSError: 文件缺失、不可读或向组/其他用户开放权限。
        ValueError: 去除文本文件末尾换行后密钥不足 32 字节。
    """

    if not path:
        raise ValueError("用户上下文签名密钥文件未配置")
    key_path = Path(path)
    mode = stat.S_IMODE(key_path.stat().st_mode)
    if mode & 0o077:
        raise PermissionError("用户上下文签名密钥文件权限过宽")
    key = key_path.read_bytes().rstrip(b"\r\n")
    if len(key) < 32:
        raise ValueError("用户上下文签名密钥至少需要 32 字节")
    return key


def _base64url_encode(value: bytes) -> str:
    """生成无填充的 URL-safe Base64。"""

    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    """严格解码 URL-safe Base64，拒绝非字母表字符。"""

    if not value or len(value) > 8192:
        raise UserContextTokenError("签名用户上下文格式无效")
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, TypeError):
        raise UserContextTokenError("签名用户上下文格式无效") from None


def sign_user_context(claims: dict[str, object], key: bytes) -> str:
    """对规范 JSON Claims 生成短期 HMAC-SHA256 用户上下文 Token。"""

    if len(key) < 32:
        raise ValueError("用户上下文签名密钥至少需要 32 字节")
    payload = json.dumps(
        claims, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    signature = hmac.new(key, payload, hashlib.sha256).digest()
    return f"{_base64url_encode(payload)}.{_base64url_encode(signature)}"


def verify_user_context(
    token: str,
    key: bytes,
    *,
    expected_tool_id: str,
    expected_environment_id: str,
    max_ttl_seconds: int = 300,
    now_epoch: int | None = None,
) -> dict[str, object]:
    """验证签名、规范 Claims、时间窗口及工具/环境绑定并返回 Claims。

    签名比较使用常量时间语义。只有签名真实且时间过期的 Token 才返回独立的
    expired 异常；格式错误和作用域不匹配统一视为 invalid，减少验证预言信息。
    """

    if len(token) > 16384:
        raise UserContextTokenError("签名用户上下文格式无效")
    try:
        payload_segment, signature_segment = token.split(".")
    except ValueError:
        raise UserContextTokenError("签名用户上下文格式无效") from None
    payload = _base64url_decode(payload_segment)
    signature = _base64url_decode(signature_segment)
    expected_signature = hmac.new(key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        raise UserContextTokenError("签名用户上下文无效")
    try:
        claims = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise UserContextTokenError("签名用户上下文格式无效") from None
    if not isinstance(claims, dict):
        raise UserContextTokenError("签名用户上下文格式无效")
    canonical = json.dumps(
        claims, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if canonical != payload:
        raise UserContextTokenError("签名用户上下文格式无效")
    required = {"v", "sid", "uid", "pv", "tid", "env", "iat", "exp", "nonce"}
    if set(claims) != required:
        raise UserContextTokenError("签名用户上下文 Claims 无效")
    integer_keys = ("v", "pv", "iat", "exp")
    if any(
        not isinstance(claims[key], int) or isinstance(claims[key], bool)
        for key in integer_keys
    ):
        raise UserContextTokenError("签名用户上下文 Claims 无效")
    string_keys = ("sid", "uid", "tid", "env", "nonce")
    if any(
        not isinstance(claims[key], str) or not claims[key] or len(claims[key]) > 128
        for key in string_keys
    ):
        raise UserContextTokenError("签名用户上下文 Claims 无效")
    if claims["v"] != 1 or claims["pv"] < 1:
        raise UserContextTokenError("签名用户上下文版本无效")
    ttl = claims["exp"] - claims["iat"]
    if ttl <= 0 or ttl > min(max_ttl_seconds, 300):
        raise UserContextTokenError("签名用户上下文时间窗口无效")
    now = int(time.time()) if now_epoch is None else now_epoch
    if claims["exp"] <= now:
        raise UserContextTokenExpired("签名用户上下文已过期")
    if claims["iat"] > now + 30:
        raise UserContextTokenError("签名用户上下文签发时间无效")
    if (
        claims["tid"] != expected_tool_id
        or claims["env"] != expected_environment_id
    ):
        raise UserContextTokenError("签名用户上下文作用域无效")
    return claims


def new_runtime_context_id() -> str:
    """生成包含 256 位随机熵且可放入 String(64) 的 Runtime Context ID。"""

    return f"rtx_{secrets.token_urlsafe(32)}"


@dataclass(frozen=True)
class EncryptedValue:
    """承载 Secret 信封加密后的数据库字段。"""

    ciphertext: bytes
    cipher_nonce: bytes
    wrapped_dek: bytes
    wrap_nonce: bytes
    kek_version: str


class SecretCipher:
    """使用 AES-GCM 信封加密和解密平台 Secret。"""

    def __init__(self, keys: dict[str, bytes], active_version: str) -> None:
        """
        初始化密钥环。

        参数说明:
            keys: KEK 版本到 32 字节密钥的映射。
            active_version: 新 Secret 使用的 KEK 版本。
        异常说明:
            ValueError: 活跃版本缺失或密钥长度错误。
        """

        if active_version not in keys or any(len(key) != 32 for key in keys.values()):
            raise ValueError("Secret KEK 必须包含活跃版本且每个密钥为 32 字节")
        self.keys = keys
        self.active_version = active_version

    @classmethod
    def from_file(cls, path: str) -> "SecretCipher":
        """
        从只读 JSON 密钥文件加载版本化 KEK。

        文件格式:
            {"active":"v1","keys":{"v1":"<base64-32-bytes>"}}
        异常说明:
            OSError/ValueError: 文件缺失、JSON 或密钥格式错误。
        """

        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        active = str(payload["active"])
        keys = {
            str(version): base64.b64decode(str(encoded), validate=True)
            for version, encoded in dict(payload["keys"]).items()
        }
        return cls(keys, active)

    def encrypt(self, plaintext: str, aad: bytes) -> EncryptedValue:
        """使用随机 DEK 加密明文，并用活跃 KEK 包裹 DEK。"""

        dek = AESGCM.generate_key(bit_length=256)
        cipher_nonce = os.urandom(12)
        wrap_nonce = os.urandom(12)
        ciphertext = AESGCM(dek).encrypt(cipher_nonce, plaintext.encode("utf-8"), aad)
        wrapped_dek = AESGCM(self.keys[self.active_version]).encrypt(wrap_nonce, dek, aad)
        return EncryptedValue(ciphertext, cipher_nonce, wrapped_dek, wrap_nonce, self.active_version)

    def decrypt(self, encrypted: EncryptedValue, aad: bytes) -> str:
        """验证 AAD 后解包 DEK 并解密 Secret。"""

        kek = self.keys.get(encrypted.kek_version)
        if kek is None:
            raise ValueError("Secret 使用的 KEK 版本不可用")
        dek = AESGCM(kek).decrypt(encrypted.wrap_nonce, encrypted.wrapped_dek, aad)
        return AESGCM(dek).decrypt(encrypted.cipher_nonce, encrypted.ciphertext, aad).decode("utf-8")
