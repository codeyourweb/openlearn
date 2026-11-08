# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Confirming an address at sign-up, and the link that does it."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import mailer, verification
from app.config import settings
from app.db import SessionLocal
from app.models import EmailVerificationToken, User, utcnow
from tests.conftest import DEFAULT_PASSWORD, csrf_headers, register_user


@pytest.fixture()
def mailbox(monkeypatch):
    """Collect what would have been mailed instead of opening an SMTP session."""
    sent: list[mailer.Message] = []

    def capture(message: mailer.Message) -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(mailer, "send_safely", capture)
    monkeypatch.setattr(settings, "email_verification_interval_seconds", 300)
    return sent


def _token_for(email: str) -> EmailVerificationToken:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        return db.scalar(
            select(EmailVerificationToken)
            .where(EmailVerificationToken.user_id == user.id)
            .order_by(EmailVerificationToken.created_at.desc())
        )


def test_sign_up_sends_one_link_and_leaves_the_address_unconfirmed(client, mailbox):
    body = register_user(client, email="newcomer@example.com")

    assert body["email_verified"] is False
    assert len(mailbox) == 1
    assert "Confirm your" in mailbox[0].subject
    assert "/verify/" in mailbox[0].text

    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "newcomer@example.com")).email_verified is False
        row = db.scalar(select(EmailVerificationToken))
        assert row is not None and row.used_at is None


def test_a_missing_mail_server_does_not_break_the_sign_up(client, monkeypatch):
    monkeypatch.setattr(mailer, "is_configured", lambda: False)

    body = register_user(client, email="nomail@example.com")

    assert body["email_verified"] is False
    # The account exists: the mail is an improvement, not a condition.
    assert client.get("/api/v1/auth/me").status_code == 200


def test_opening_the_link_confirms_the_address_once(client, mailbox):
    register_user(client, email="clicker@example.com")
    token = mailbox[0].text.split("/verify/")[1].split()[0].strip()

    first = client.get(f"/api/v1/auth/email/verify/{token}")
    assert first.status_code == 200, first.text
    assert first.json()["verified"] is True

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "clicker@example.com"))
        assert user.email_verified is True
        assert user.email_verified_at is not None

    # A link is single use, and the second attempt says so without naming the account.
    second = client.get(f"/api/v1/auth/email/verify/{token}")
    assert second.status_code == 404
    assert "clicker" not in second.text


def test_an_expired_link_is_reported_as_expired(client, mailbox):
    register_user(client, email="late@example.com")
    token = mailbox[0].text.split("/verify/")[1].split()[0].strip()

    with SessionLocal() as db:
        row = db.scalar(select(EmailVerificationToken))
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.add(row)
        db.commit()

    response = client.get(f"/api/v1/auth/email/verify/{token}")
    assert response.status_code == 410


def test_asking_for_the_link_again_waits_for_the_interval(client, mailbox):
    register_user(client, email="patient@example.com")
    assert len(mailbox) == 1

    first = client.post("/api/v1/auth/email/resend", headers=csrf_headers(client))
    assert first.status_code == 202
    assert first.json()["sent"] is False  # the interval has not elapsed
    assert len(mailbox) == 1

    # Ten minutes later the same request is answered with a new link, and the
    # previous one stops working.
    old_token = _token_for("patient@example.com").token_hash
    with SessionLocal() as db:
        row = db.scalar(select(EmailVerificationToken))
        row.created_at = utcnow() - timedelta(minutes=10)
        db.add(row)
        db.commit()

    second = client.post("/api/v1/auth/email/resend", headers=csrf_headers(client))
    assert second.json()["sent"] is True
    assert len(mailbox) == 2
    assert _token_for("patient@example.com").token_hash != old_token

    client.cookies.clear()
    assert client.post("/api/v1/auth/email/resend").status_code in (401, 403)


def test_an_already_confirmed_address_gets_no_more_mail(client, mailbox):
    register_user(client, email="done@example.com")
    token = mailbox[0].text.split("/verify/")[1].split()[0].strip()
    client.get(f"/api/v1/auth/email/verify/{token}")

    response = client.post("/api/v1/auth/email/resend", headers=csrf_headers(client))

    assert response.json()["email_verified"] is True
    assert response.json()["sent"] is False
    assert len(mailbox) == 1


def test_the_link_is_not_issued_when_the_address_is_already_confirmed(client):
    register_user(client, email="quiet@example.com")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "quiet@example.com"))
        user.email_verified = True
        db.add(user)
        db.commit()
        assert verification.issue(db, user, None) is None


def test_a_known_password_policy_still_applies_with_the_link(client, mailbox):
    """The link must not become a way around the rest of the sign-up rules."""
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short", "display_name": "Weak"},
    )
    assert response.status_code == 422
    assert mailbox == []
    assert DEFAULT_PASSWORD  # the fixture password is the documented valid one
