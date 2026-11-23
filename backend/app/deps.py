"""Shared FastAPI dependencies: current user, CSRF, rate limits."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.logging_setup import user_id_var
from app.models import User
from app.security import rate_limit
from app.security.tokens import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, TokenError, decode_access_token, tokens_match

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def require_csrf(request: Request) -> None:
    """Double-submit CSRF check for every state-changing request."""
    if request.method in _SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not tokens_match(cookie, header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    try:
        user_id = decode_access_token(token)
    except TokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired") from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    user_id_var.set(user.id)
    return user


def authed_user(
    request: Request,
    user: User = Depends(get_current_user),
    _csrf: None = Depends(require_csrf),
) -> User:
    """Authenticated + CSRF protected + per-user general rate limit."""
    rate_limit.hit(f"user:{user.id}", get_settings().rate_limit_per_minute)
    return user
