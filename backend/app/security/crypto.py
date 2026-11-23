"""Encryption at rest for uploaded datasets.

Fernet = AES-128-CBC + HMAC-SHA256 with a random IV per message (authenticated
encryption: tampered blobs fail to decrypt instead of returning garbage).
MultiFernet gives key rotation: new data is encrypted with the first key, and
old data remains readable with any listed key until it is re-encrypted.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import get_settings


class DecryptionError(Exception):
    pass


@lru_cache
def _cipher() -> MultiFernet:
    keys = get_settings().encryption_key_list
    if not keys:
        raise RuntimeError("DATA_ENCRYPTION_KEYS is empty")
    return MultiFernet([Fernet(k) for k in keys])


def encrypt(data: bytes) -> bytes:
    return _cipher().encrypt(data)


def decrypt(token: bytes) -> bytes:
    try:
        return _cipher().decrypt(token)
    except InvalidToken as exc:
        raise DecryptionError("blob failed integrity check or key is missing") from exc


def rotate(token: bytes) -> bytes:
    """Re-encrypt a blob with the current primary key."""
    return _cipher().rotate(token)


def generate_key() -> str:
    return Fernet.generate_key().decode()
