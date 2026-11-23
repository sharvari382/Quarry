"""Password hashing (Argon2id) and password policy."""
from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.services.bulkhead import PASSWORD_HASH

# OWASP 2024 baseline for Argon2id: m=19 MiB, t=2, p=1. We go a bit above it.
_hasher = PasswordHasher(time_cost=3, memory_cost=19 * 1024, parallelism=1)

# A tiny deny list. In production, check against the HIBP k-anonymity API as well.
_COMMON = {"password", "password1", "12345678", "123456789", "qwerty123", "letmein123", "iloveyou1"}

# Precomputed hash used to keep login timing equal for unknown emails.
DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def hash_password(password: str) -> str:
    with PASSWORD_HASH.slot():
        return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        with PASSWORD_HASH.slot():
            return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, email: str = "") -> list[str]:
    """Return human readable reasons a password is rejected (empty list = OK)."""
    problems = []
    if len(password) < 10:
        problems.append("must be at least 10 characters")
    if len(password) > 128:
        problems.append("must be at most 128 characters")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        problems.append("must contain at least one letter and one number")
    if password.lower() in _COMMON:
        problems.append("is too common")
    local = email.split("@")[0].lower()
    if local and len(local) >= 4 and local in password.lower():
        problems.append("must not contain your email name")
    return problems
