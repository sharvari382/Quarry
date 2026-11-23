"""Fixed-window rate limiting and login lockout, backed by the shared KV store."""
from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.services.kv import get_kv


def client_ip(request: Request) -> str:
    # nginx sets X-Real-IP from the socket peer. We only trust it because the API
    # is not reachable except through nginx (see docker-compose networks).
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def hit(bucket: str, limit: int, window_seconds: int = 60) -> None:
    kv = get_kv()
    key = f"rl:{bucket}"
    count = kv.incr(key, window_seconds)
    if count > limit:
        retry = kv.ttl(key) or window_seconds
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(retry)},
        )


def enforce_daily_llm_quota(user_id: str) -> None:
    hit(f"llm-day:{user_id}", get_settings().daily_llm_calls_per_user, window_seconds=86_400)


# Login lockout ---------------------------------------------------------------

def _fail_key(email: str) -> str:
    return f"login-fail:{email.lower()}"


def check_login_locked(email: str) -> None:
    s = get_settings()
    raw = get_kv().get(_fail_key(email))
    if raw and int(raw) >= s.login_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {s.login_lockout_minutes} minutes.",
            headers={"Retry-After": str(get_kv().ttl(_fail_key(email)))},
        )


def record_login_failure(email: str) -> None:
    get_kv().incr(_fail_key(email), get_settings().login_lockout_minutes * 60)


def clear_login_failures(email: str) -> None:
    get_kv().delete(_fail_key(email))
