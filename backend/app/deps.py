# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Shared FastAPI dependencies: authentication, CSRF and rate limiting."""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from . import runtime
from .config import settings
from .db import get_db
from .models import ApiKey, User, utcnow
from .security import decode_access_token, rate_limiter, sha256

# Only real private/loopback ranges count as "our proxy". ipaddress.is_private
# also covers documentation and reserved ranges, which would let a caller from
# such a block impersonate the proxy.
_TRUSTED_PROXY_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("::1/128"),
)


def _is_trusted_proxy(host: str) -> bool:
    """True when the peer is loopback or on a private network (our proxy)."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in _TRUSTED_PROXY_NETWORKS)


def client_ip(request: Request) -> str:
    """Client IP, trusting X-Forwarded-For only when the peer is our proxy.

    Honouring the header from any peer would let a direct caller forge its
    address and escape rate limiting and the authentication lockout.
    """
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _is_trusted_proxy(peer):
        candidate = forwarded.split(",")[0].strip()
        if candidate:
            return candidate[:45]
    return peer[:45]


def external_base_url(request: Request) -> str:
    """Base URL a browser should use, honouring a TLS-terminating proxy."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip() or request.url.scheme
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    return f"{proto}://{host}".rstrip("/")


def enforce_rate_limit(request: Request, bucket: str, limit: int, window: int) -> None:
    allowed, retry_after = rate_limiter.check(f"{bucket}:{client_ip(request)}", limit, window)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(retry_after)},
        )


def enforce_ai_interval(user: User) -> None:
    """One model call at a time, per account.

    Counted on the account rather than the IP: a shared office address would
    otherwise throttle a whole team, and one author could bypass a per-IP limit
    by switching network.
    """
    # `or 15` would turn an explicit 0 (tests, or an administrator opting out)
    # back into fifteen seconds; only a missing value falls back to the default.
    # The value is administrator-editable, so it is read at call time.
    raw = runtime.ai_config().min_interval_seconds
    interval = 15 if raw is None else int(raw)
    if interval <= 0:
        return  # disabled, as the test suite does
    allowed, retry_after = rate_limiter.check(f"ai-user:{user.id}", 1, interval)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Another AI request is already running. Wait {retry_after} s "
                "before asking the model again."
            ),
            headers={"Retry-After": str(retry_after)},
        )


def _user_from_api_key(db: OrmSession, raw_key: str) -> User | None:
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == sha256(raw_key), ApiKey.revoked_at.is_(None)))
    if key is None:
        return None
    key.last_used_at = utcnow()
    db.commit()
    return db.get(User, key.user_id)


def resolve_user(request: Request, db: OrmSession) -> User | None:
    """Resolve the caller from API key, bearer token or session cookie."""
    api_key = request.headers.get("x-api-key")
    if api_key:
        return _user_from_api_key(db, api_key)

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        payload = decode_access_token(authorization[7:].strip())
        if payload:
            user = db.get(User, int(payload["sub"]))
            if user and user.is_active and _token_version_matches(payload, user):
                return user
        return None

    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        payload = decode_access_token(cookie)
        if payload:
            user = db.get(User, int(payload["sub"]))
            if user and user.is_active and _token_version_matches(payload, user):
                return user
    return None


def _token_version_matches(payload: dict, user: User) -> bool:
    """Tokens minted before a password reset stop validating.

    Tokens issued before this field existed carry no ``ver``: they are treated
    as version 0, which is what an account that never reset its password has.
    """
    return int(payload.get("ver", 0)) == int(user.token_version or 0)


def is_cookie_auth(request: Request) -> bool:
    return not request.headers.get("authorization") and not request.headers.get("x-api-key")


def get_current_user(request: Request, db: OrmSession = Depends(get_db)) -> User:
    user = resolve_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    verify_csrf(request)
    return user


def get_optional_user(request: Request, db: OrmSession = Depends(get_db)) -> User | None:
    return resolve_user(request, db)


def verify_csrf(request: Request) -> None:
    """Double-submit cookie defence for cookie-authenticated mutations."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if not is_cookie_auth(request):
        return
    if not request.cookies.get(settings.session_cookie_name):
        return  # anonymous request: nothing to protect with a double-submit token
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    header_token = request.headers.get("x-csrf-token", "")
    if not cookie_token or not header_token or cookie_token != header_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid.")


def require_user(request: Request, db: OrmSession = Depends(get_db)) -> User:
    """Stricter dependency: also validates CSRF for cookie clients."""
    user = resolve_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled.")
    verify_csrf(request)
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    """Administrator-only dependency (instance configuration)."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges are required.",
        )
    return user


def require_staff(user: User = Depends(require_user)) -> User:
    """Moderation dependency: an administrator or a moderator.

    A moderator validates wikis, quizzes and accounts, but the instance
    configuration (AI, mail, SSO) stays behind ``require_admin``.
    """
    if not user.is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Moderator privileges are required.",
        )
    return user


def utc_now() -> datetime:
    return datetime.now(UTC)
