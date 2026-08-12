from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
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
