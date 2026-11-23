"""JWT access tokens and opaque refresh tokens.

* Access token: short lived (15 min) JWT, HS256, sent as an HttpOnly cookie.
* Refresh token: 256-bit random opaque string, only its SHA-256 is stored.
* CSRF token: random value in a readable cookie; the SPA echoes it in a header
  (double-submit pattern). Cookies are also SameSite=Strict.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings

ALGORITHM = "HS256"
ACCESS_COOKIE = "quarry_access"
REFRESH_COOKIE = "quarry_refresh"
CSRF_COOKIE = "quarry_csrf"
CSRF_HEADER = "x-csrf-token"


class TokenError(Exception):
    pass


def create_access_token(user_id: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
        "type": "access",
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    s = get_settings()
    try:
        # `algorithms` is pinned: never let the token header choose (alg=none attacks).
        payload = jwt.decode(token, s.jwt_secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != "access":
        raise TokenError("wrong token type")
    return str(payload["sub"])


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def tokens_match(a: str, b: str) -> bool:
    return bool(a) and bool(b) and secrets.compare_digest(a, b)
