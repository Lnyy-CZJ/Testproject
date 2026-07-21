"""
安全模块

替代 Go 版 middleware/auth.go + aiconfig/crypto.go，提供:
1. JWT Token 生成与解析
2. bcrypt 密码哈希
3. AES-256-GCM 加密/解密（凭证和 AI 配置加密）
4. API Key 脱敏
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import JWTError, jwt

from app.config import settings

# ── bcrypt 密码哈希 ──

import bcrypt


def hash_password(password: str) -> str:
    """对密码进行 bcrypt 哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码与哈希值是否匹配"""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ── JWT Token ──

ALGORITHM = "HS256"


def create_access_token(user_id: int, username: str) -> str:
    """
    创建 JWT Access Token

    参数:
        user_id: 用户ID
        username: 用户名

    返回:
        JWT Token 字符串

    Token 载荷:
        sub: 用户ID
        username: 用户名
        jti: Token 唯一标识（用于黑名单撤销）
        exp: 过期时间
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt.expire_hour)
    to_encode = {
        "sub": str(user_id),
        "username": username,
        "jti": os.urandom(16).hex(),
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.jwt.secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """
    解析 JWT Token

    返回:
        Token 载荷字典，解析失败返回 None
    """
    try:
        return jwt.decode(token, settings.jwt.secret, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── AES-256-GCM 加密/解密 ──


def aes_encrypt(plaintext: str, key: str) -> str:
    """
    使用 AES-256-GCM 加密明文

    参数:
        plaintext: 待加密的明文
        key: 32 字节加密密钥

    返回:
        Base64 编码的密文（nonce + ciphertext 拼接）
    """
    key_bytes = key.encode("utf-8")[:32].ljust(32, b"\x00")
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return (nonce + ciphertext).hex()


def aes_decrypt(encoded: str, key: str) -> str:
    """
    使用 AES-256-GCM 解密密文

    参数:
        encoded: 十六进制编码的密文（nonce + ciphertext）
        key: 32 字节加密密钥

    返回:
        解密后的明文
    """
    key_bytes = key.encode("utf-8")[:32].ljust(32, b"\x00")
    aesgcm = AESGCM(key_bytes)
    data = bytes.fromhex(encoded)
    nonce = data[:12]
    ciphertext = data[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


def mask_key(key: str) -> str:
    """
    API Key 脱敏显示

    仅显示前 4 位和后 4 位，中间用 4 个 * 替换。
    短密钥（<=8字符）仅显示前4位 + "****"。

    示例:
        "sk-1234567890abcdef" → "sk-1****cdef"
        "short" → "shor****"
    """
    if len(key) <= 8:
        return key[:4] + "****"
    return key[:4] + "****" + key[-4:]