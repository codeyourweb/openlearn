# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Authentication endpoints and cookie helpers."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import runtime, verification
from ..config import settings
from ..db import get_db
from ..deps import client_ip, enforce_rate_limit, require_user
from ..models import SecurityEvent, User, utcnow
from ..schemas import LoginIn, RegisterIn, TokenOut, UserOut
from ..security import (
    PasswordPolicyError,
    create_access_token,
    hash_password,
    hash_to_compare,
    needs_rehash,
    new_secret,
    validate_password,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def _audit(db: OrmSession, event: str, request: Request | None = None, user_id: int | None = None, detail: str = "") -> None:
    db.add(
        SecurityEvent(
            event=event,
            ip=client_ip(request) if request else None,
            user_id=user_id,
            detail=detail[:300],
        )
    )
    db.commit()


def is_secure_request(request: Request | None) -> bool:
    """True when the request reached us over TLS (directly or via a proxy)."""
    if settings.cookie_secure:
        return True
    if request is None:
        return False
    return request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def set_auth_cookies(response: Response, user: User, request: Request | None = None) -> str:
    token = create_access_token(user.id, token_version=user.token_version or 0)
    max_age = settings.access_token_ttl_minutes * 60
    secure = is_secure_request(request)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        domain=settings.cookie_domain,
    )
    csrf_token = new_secret(24)
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=max_age,
        httponly=False,  # read by the SPA to fill the X-CSRF-Token header
        secure=secure,
        samesite="lax",
        path="/",
        domain=settings.cookie_domain,
    )
    return csrf_token


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/", domain=settings.cookie_domain)
    response.delete_cookie(settings.csrf_cookie_name, path="/", domain=settings.cookie_domain)


@router.get("/csrf")
def issue_csrf(response: Response, request: Request) -> dict[str, str]:
    existing = request.cookies.get(settings.csrf_cookie_name)
    token = existing or new_secret(24)
    if not existing:
        response.set_cookie(
            key=settings.csrf_cookie_name,
            value=token,
            max_age=settings.access_token_ttl_minutes * 60,
            httponly=False,
            secure=is_secure_request(request),
            samesite="lax",
            path="/",
            domain=settings.cookie_domain,
        )
    return {"csrf_token": token}


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, request: Request, response: Response, db: OrmSession = Depends(get_db)) -> User:
    enforce_rate_limit(request, "auth", settings.auth_rate_limit, settings.auth_rate_window_seconds)
    if not runtime.registration_open(db):
        raise HTTPException(status_code=403, detail="Registrations are closed on this instance.")
    try:
        validate_password(payload.password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        _audit(db, "register_conflict", request, detail=payload.email)
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _audit(db, "register_success", request, user.id)
    # The account exists either way; the link only proves the address is theirs.
    # A missing SMTP server must not turn a sign-up into an error.
    verification.issue(db, user, request)
    set_auth_cookies(response, user, request)
    return user


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, request: Request, response: Response, db: OrmSession = Depends(get_db)) -> User:
    enforce_rate_limit(request, "auth", settings.auth_rate_limit, settings.auth_rate_window_seconds)
    user = db.scalar(select(User).where(User.email == payload.email))
    now = utcnow()

    # The hash is verified before anything is said about the account, and even
    # when there is no account: a missing address used to answer in 3 ms while a
    # real one took 60 ms, which is a free list of who is registered here.
    password_ok = verify_password(
        payload.password, hash_to_compare(user is not None, user.password_hash if user else None)
    )

    if user is None or not password_ok or not user.is_active:
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_logins = 0
            db.add(user)
            db.commit()
        _audit(db, "login_failure", request, user.id if user else None, payload.email)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Reached only with the right password: a lock is then told to its owner,
    # not to whoever guessed an address. Announcing it earlier both revealed the
    # account and let five wrong passwords lock a stranger out of it.
    if user.locked_until is not None:
        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=now.tzinfo)
        if locked_until > now:
            _audit(db, "login_locked", request, user.id)
            raise HTTPException(status_code=423, detail="Account temporarily locked after too many failed attempts.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    db.add(user)
    db.commit()
    db.refresh(user)
    _audit(db, "login_success", request, user.id)
    set_auth_cookies(response, user, request)
    return user


@router.post("/token", response_model=TokenOut)
def issue_token(payload: LoginIn, request: Request, db: OrmSession = Depends(get_db)) -> TokenOut:
    """Machine-to-machine credential for third party clients (no cookies)."""
    enforce_rate_limit(request, "auth", settings.auth_rate_limit, settings.auth_rate_window_seconds)
    user = db.scalar(select(User).where(User.email == payload.email))
    # Same rule as the cookie sign-in: verify before deciding, so an unknown
    # address and a wrong password cost the same time to an attacker probing
    # for accounts through the machine-to-machine endpoint.
    password_ok = verify_password(
        payload.password, hash_to_compare(user is not None, user.password_hash if user else None)
    )
    if user is None or not user.is_active or not password_ok:
        _audit(db, "token_failure", request, user.id if user else None, payload.email)
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    _audit(db, "token_success", request, user.id)
    return TokenOut(
        access_token=create_access_token(user.id, token_type="api"),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: OrmSession = Depends(get_db)) -> Response:
    user = None
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        from ..security import decode_access_token

        payload = decode_access_token(cookie)
        if payload:
            user = db.get(User, int(payload["sub"]))
    clear_auth_cookies(response)
    if user:
        _audit(db, "logout", request, user.id)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/email/verify/{token}")
def verify_email(token: str, request: Request, db: OrmSession = Depends(get_db)) -> dict[str, object]:
    """Consume the link mailed at sign-up (or resent later)."""
    enforce_rate_limit(request, "email-verify", 30, 3600)
    try:
        user = verification.consume(db, token)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="This confirmation link is no longer valid.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=410, detail="This confirmation link has expired.") from exc
    _audit(db, "email_verified", request, user.id)
    return {"verified": True, "email": user.email}


@router.post("/email/resend", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(
    request: Request,
    user: User = Depends(require_user),
    db: OrmSession = Depends(get_db),
) -> dict[str, object]:
    """Send the confirmation link again, at most once per interval."""
    enforce_rate_limit(request, "email-resend", 5, 3600)
    if user.email_verified:
        return {"detail": "This address is already confirmed.", "email_verified": True, "sent": False}
    token = verification.issue(db, user, request)
    _audit(db, "email_verification_requested", request, user.id, "sent" if token else "throttled")
    detail = (
        "A confirmation link has been sent."
        if token
        else "A link was sent recently; wait a few minutes before asking for another."
    )
    return {"detail": detail, "email_verified": False, "sent": bool(token)}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(require_user)) -> User:
    return user
