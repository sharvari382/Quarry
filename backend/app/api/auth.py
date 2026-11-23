"""Authentication: register, login, refresh (with rotation + reuse detection), logout."""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import authed_user, get_current_user, require_csrf
from app.models import RefreshToken, User
from app.schemas import ChangePasswordIn, LoginIn, RegisterIn, UserOut
from app.security import rate_limit
from app.security.passwords import DUMMY_HASH, hash_password, needs_rehash, password_problems, verify_password
from app.security.tokens import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    create_access_token,
    hash_token,
    new_opaque_token,
)
from app.services.audit import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

_GENERIC_LOGIN_ERROR = "Incorrect email or password."


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SQLite drops tzinfo


def _set_session_cookies(response: Response, access: str, refresh: str, csrf: str | None = None) -> None:
    s = get_settings()
    common = {"secure": s.cookie_secure, "samesite": "strict"}
    response.set_cookie(ACCESS_COOKIE, access, httponly=True, max_age=s.access_token_minutes * 60, path="/api",
                        **common)
    # Refresh cookie is scoped to the auth endpoints only, so it is not sent on every API call.
    response.set_cookie(REFRESH_COOKIE, refresh, httponly=True, max_age=s.refresh_token_days * 86400,
                        path="/api/auth", **common)
    # CSRF cookie must be readable by JS (that is the point of double-submit).
    # On refresh the existing CSRF value is kept: rotating it would break requests
    # already in flight from other tabs that read the old value.
    response.set_cookie(CSRF_COOKIE, csrf or secrets.token_urlsafe(24), httponly=False,
                        max_age=s.refresh_token_days * 86400, path="/", **common)


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/api")
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _issue_session(db: Session, user: User, response: Response, request: Request, family_id: str | None = None,
                   keep_csrf: bool = False) -> RefreshToken:
    s = get_settings()
    raw = new_opaque_token()
    token = RefreshToken(
        user_id=user.id, token_hash=hash_token(raw), family_id=family_id or str(uuid.uuid4()),
        expires_at=_now() + timedelta(days=s.refresh_token_days),
        user_agent=(request.headers.get("user-agent") or "")[:255],
    )
    db.add(token)
    db.flush()
    csrf = request.cookies.get(CSRF_COOKIE) if keep_csrf else None
    _set_session_cookies(response, create_access_token(user.id), raw, csrf)
    return token


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = rate_limit.client_ip(request)
    rate_limit.hit(f"register:{ip}", get_settings().register_per_ip_per_hour, window_seconds=3600)
    email = body.email.lower()
    if problems := password_problems(body.password, email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Password " + "; ".join(problems) + ".")
    if db.scalar(select(User).where(User.email == email)):
        # Honest message: an enumeration-proof flow would need email verification,
        # which is out of scope here. Rate limiting above bounds enumeration speed.
        raise HTTPException(status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    user = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    _issue_session(db, user, response, request)
    audit(db, "user.register", user.id, ip)
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = rate_limit.client_ip(request)
    rate_limit.hit(f"login-ip:{ip}", get_settings().login_per_ip_per_minute, window_seconds=60)
    email = body.email.lower()
    rate_limit.check_login_locked(email)

    user = db.scalar(select(User).where(User.email == email))
    # Always run one Argon2 verify so response time does not reveal whether the email exists.
    ok = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
    if not user or not ok or not user.is_active:
        rate_limit.record_login_failure(email)
        audit(db, "auth.login_failed", user.id if user else None, ip, email=email)
        db.commit()  # keep the audit row even though the request fails
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=_GENERIC_LOGIN_ERROR)

    rate_limit.clear_login_failures(email)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = _now()
    _issue_session(db, user, response, request)
    audit(db, "auth.login", user.id, ip)
    return user


@router.post("/refresh", response_model=UserOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db), _=Depends(require_csrf)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    rate_limit.hit(f"refresh:{hash_token(raw)[:16]}", 30)
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    if token is None:
        _clear_session_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    if token.revoked_at is not None:
        # A rotated token came back: someone has a copy. Kill the entire family.
        db.execute(update(RefreshToken).where(RefreshToken.family_id == token.family_id,
                                              RefreshToken.revoked_at.is_(None)).values(revoked_at=_now()))
        audit(db, "auth.refresh_reuse_detected", token.user_id, rate_limit.client_ip(request))
        db.commit()
        _clear_session_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Session revoked. Please sign in again.")

    if _aware(token.expires_at) < _now():
        _clear_session_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    new = _issue_session(db, user, response, request, family_id=token.family_id, keep_csrf=True)
    token.revoked_at = _now()
    token.replaced_by = new.id
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db), _=Depends(require_csrf)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
        if token and token.revoked_at is None:
            token.revoked_at = _now()
            audit(db, "auth.logout", token.user_id, rate_limit.client_ip(request))
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(request: Request, response: Response, user: User = Depends(authed_user),
               db: Session = Depends(get_db)):
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=_now()))
    audit(db, "auth.logout_all", user.id, rate_limit.client_ip(request))
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: ChangePasswordIn, request: Request, response: Response,
                    user: User = Depends(authed_user), db: Session = Depends(get_db)):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.")
    if problems := password_problems(body.new_password, user.email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Password " + "; ".join(problems) + ".")
    user.password_hash = hash_password(body.new_password)
    # Changing a password signs out every other device.
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=_now()))
    _issue_session(db, user, response, request)
    audit(db, "auth.password_changed", user.id, rate_limit.client_ip(request))
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
