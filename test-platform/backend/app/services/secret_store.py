from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import EncryptedValue, SecretCipher, new_id
from app.core.config import Settings
from app.core.errors import PlatformError
from app.models.configuration import Secret, SecretVersion


def load_secret_cipher(settings: Settings) -> SecretCipher:
    """从受控 KEK 文件加载密钥环，并将配置错误转换为脱敏的服务错误。"""

    if not settings.secret_kek_file:
        raise PlatformError(503, "SECRET_UNAVAILABLE", "Secret 服务暂时不可用")
    try:
        return SecretCipher.from_file(settings.secret_kek_file)
    except (OSError, ValueError, KeyError):
        raise PlatformError(503, "SECRET_UNAVAILABLE", "Secret 服务暂时不可用") from None


def secret_aad(secret_id: str, environment_id: str, version: int) -> bytes:
    """生成绑定 Secret、环境和版本的认证附加数据。"""

    return f"secret:v1:{secret_id}:{environment_id}:{version}".encode("utf-8")


def replace_secret(
    database: Session,
    cipher: SecretCipher,
    secret: Secret,
    plaintext: str,
    actor_id: str,
    expires_at: datetime | None = None,
) -> SecretVersion:
    """创建并激活新的加密 Secret Version，响应层不得回显明文。"""

    current = database.scalar(select(func.max(SecretVersion.version)).where(SecretVersion.secret_id == secret.id)) or 0
    version = int(current) + 1
    version_id = new_id("secv")
    encrypted = cipher.encrypt(plaintext, secret_aad(secret.id, secret.environment_id, version))
    # 激活前先做一次带 AAD 的完整解密校验，任何密钥或密文问题都不会切换当前版本。
    if cipher.decrypt(encrypted, secret_aad(secret.id, secret.environment_id, version)) != plaintext:
        raise PlatformError(503, "SECRET_UNAVAILABLE", "Secret 服务暂时不可用")
    row = SecretVersion(
        id=version_id,
        secret_id=secret.id,
        version=version,
        ciphertext=encrypted.ciphertext,
        cipher_nonce=encrypted.cipher_nonce,
        wrapped_dek=encrypted.wrapped_dek,
        wrap_nonce=encrypted.wrap_nonce,
        kek_version=encrypted.kek_version,
        aad_version=1,
        status="active",
        expires_at=expires_at,
        created_by=actor_id,
    )
    database.add(row)
    secret.current_version_id = version_id
    secret.status = "healthy"
    return row


def decrypt_secret(database: Session, cipher: SecretCipher, secret: Secret) -> str:
    """解密当前 Secret Version；缺失版本时抛出 ValueError。"""

    if not secret.current_version_id:
        raise ValueError("Secret 尚未配置")
    version = database.get(SecretVersion, secret.current_version_id)
    if version is None:
        raise ValueError("Secret 当前版本不存在")
    encrypted = EncryptedValue(
        version.ciphertext,
        version.cipher_nonce,
        version.wrapped_dek,
        version.wrap_nonce,
        version.kek_version,
    )
    return cipher.decrypt(encrypted, secret_aad(secret.id, secret.environment_id, version.version))


def decrypt_secret_version(
    database: Session,
    cipher: SecretCipher,
    secret: Secret,
    version_id: str,
) -> str:
    """解密属于指定 Secret 的固定版本，供不可变运行快照使用。"""

    version = database.get(SecretVersion, version_id)
    if version is None or version.secret_id != secret.id:
        raise ValueError("Secret 版本不存在或作用域不匹配")
    encrypted = EncryptedValue(
        version.ciphertext,
        version.cipher_nonce,
        version.wrapped_dek,
        version.wrap_nonce,
        version.kek_version,
    )
    return cipher.decrypt(encrypted, secret_aad(secret.id, secret.environment_id, version.version))
