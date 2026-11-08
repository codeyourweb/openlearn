# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Password reset by email.

The endpoint never reveals whether an address has an account: the same 202 is
returned for a known email, an unknown one and a locked account. Tokens are
random, stored hashed, single use and short lived; using one bumps the user's
token version so every open session dies with the old password.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .. import mailer, runtime
from ..config import settings
from ..db import get_db
from ..deps import client_ip, enforce_rate_limit
from ..models import PasswordResetToken, SecurityEvent, User, utcnow
from ..security import PasswordPolicyError, hash_password, new_secret, sha256, validate_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=128)


def _audit(db: OrmSession, event: str, request: Request | None, user_id: int | None = None, detail: str = "") -> None:
    db.add(
        SecurityEvent(
            event=event,
            ip=client_ip(request) if request else None,
            user_id=user_id,
            detail=detail[:300],
        )
    )
    db.commit()


def _public_base(request: Request) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}"


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    payload: ForgotIn, request: Request, db: OrmSession = Depends(get_db)
) -> dict[str, str]:
    enforce_rate_limit(request, "password-reset", 5, 3600)
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))

    token: str | None = None
    if user is not None and user.is_active:
        # Invalidate older outstanding tokens: only the last mail works, which
        # keeps a stolen mailbox archive from being a permanent backdoor.
        for stale in db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
            )
        ).all():
            stale.used_at = utcnow()
        ttl = int(runtime.get(db, "security.password_reset_ttl_minutes"))
        token = new_secret(32)
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=sha256(token),
                expires_at=utcnow() + timedelta(minutes=ttl),
                requested_ip=client_ip(request),
            )
        )
        db.commit()
        link = f"{_public_base(request)}/reset/{token}"
        sent = mailer.send_safely(
            mailer.password_reset_message(
                to=user.email,
                link=link,
                minutes=ttl,
                instance=runtime.instance_name(db),
            )
        )
        _audit(db, "password_reset_requested", request, user.id, "mail_sent" if sent else "mail_unavailable")
    else:
        _audit(db, "password_reset_unknown", request, None, email[:80])

    body = {"detail": "If an account exists for this address, a reset link has been sent."}
    # Test and demo instances can hand the token back: without it, verifying the
    # flow end to end would need a mailbox.
    if token and settings.expose_reset_token:
        body["token"] = token
        body["reset_url"] = f"{_public_base(request)}/reset/{token}"
    return body


@router.get("/password/reset/{token}")
def check_reset_token(token: str, db: OrmSession = Depends(get_db)) -> dict[str, object]:
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == sha256(token)))
    if row is None or row.used_at is not None:
        raise HTTPException(status_code=404, detail="This reset link is no longer valid.")
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=utcnow().tzinfo)
    if expires_at <= utcnow():
        raise HTTPException(status_code=410, detail="This reset link has expired.")
    return {"valid": True, "expires_at": expires_at.isoformat()}


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    payload: ResetIn, request: Request, response: Response, db: OrmSession = Depends(get_db)
) -> Response:
    enforce_rate_limit(request, "password-reset-confirm", 10, 3600)
    try:
        validate_password(payload.password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == sha256(payload.token)))
    now = utcnow()
    if row is None or row.used_at is not None:
        raise HTTPException(status_code=400, detail="This reset link is no longer valid.")
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now.tzinfo)
    if expires_at <= now:
        raise HTTPException(status_code=410, detail="This reset link has expired.")

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="This reset link is no longer valid.")

    user.password_hash = hash_password(payload.password)
    user.token_version = (user.token_version or 0) + 1
    user.failed_logins = 0
    user.locked_until = None
    row.used_at = now
    db.add_all([user, row])
    db.commit()
    _audit(db, "password_reset_completed", request, user.id)
    response.status_code = status.HTTP_204_NO_CONTENT
    # Cookies from the old password must not survive the change.
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return response
