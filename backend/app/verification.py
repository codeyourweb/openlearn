# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Confirming the address a visitor typed at sign-up.

An address is a claim until someone opens the link sent to it. This module owns
the two halves: issuing a link (with the same flood protection as a password
reset, so it cannot be used to fill someone's inbox) and consuming one.

The confirmation is not a condition to sign in — a visitor who never receives
the mail still has a usable account — it is what lets the interface say the
address is real, and what a future administrator can rely on when a notification
has to reach an author.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from . import mailer, runtime
from .config import settings
from .deps import client_ip
from .models import EmailVerificationToken, User, utcnow
from .security import new_secret, sha256

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=utcnow().tzinfo)


def public_base(request: Request | None) -> str:
    """Absolute address of this instance, for the links we mail out."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    if request is None:
        return ""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}"


def issue(
    db: OrmSession, user: User, request: Request | None, *, respect_interval: bool = True
) -> str | None:
    """Create a confirmation link and mail it.

    Returns the token when a mail was sent, ``None`` when the interval since the
    previous one has not elapsed — the caller answers the same way either way, so
    the interval does not become a way to learn whether an address exists.
    """
    if user.email_verified:
        return None
    if respect_interval:
        interval = max(0, int(settings.email_verification_interval_seconds))
        if interval:
            last = db.scalar(
                select(EmailVerificationToken)
                .where(EmailVerificationToken.user_id == user.id)
                .order_by(EmailVerificationToken.created_at.desc())
                .limit(1)
            )
            if last is not None:
                age = (utcnow() - _as_utc(last.created_at)).total_seconds()
                if age < interval:
                    logger.info("Verification mail skipped (interval not elapsed)")
                    return None

    for stale in db.scalars(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id, EmailVerificationToken.used_at.is_(None)
        )
    ).all():
        stale.used_at = utcnow()

    ttl = max(5, int(settings.email_verification_ttl_minutes))
    token = new_secret(32)
    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=sha256(token),
            expires_at=utcnow() + timedelta(minutes=ttl),
            requested_ip=client_ip(request),
        )
    )
    db.commit()

    link = f"{public_base(request)}/verify/{token}"
    mailer.send_safely(
        mailer.email_verification_message(
            to=user.email,
            link=link,
            hours=max(1, ttl // 60),
            instance=runtime.instance_name(db),
            name=user.display_name,
        )
    )
    return token


def consume(db: OrmSession, token: str) -> User:
    """Mark the address confirmed. Raises LookupError/ValueError on a dead link."""
    row = db.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == sha256(token))
    )
    if row is None or row.used_at is not None:
        raise LookupError("no longer valid")
    if _as_utc(row.expires_at) <= utcnow():
        raise ValueError("expired")
    user = db.get(User, row.user_id)
    if user is None:
        raise LookupError("no longer valid")
    now = utcnow()
    row.used_at = now
    user.email_verified = True
    user.email_verified_at = now
    # A link proves the mailbox, which is also a good moment to drop the other
    # outstanding ones: they were sent to the same place for the same purpose.
    for other in db.scalars(
        select(EmailVerificationToken).where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
        )
    ).all():
        other.used_at = now
    db.add_all([row, user])
    db.commit()
    db.refresh(user)
    return user
