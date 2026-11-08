# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Temporary bans, and the password-reset flood they exist next to."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import abuse, mailer
from app.config import settings
from app.db import SessionLocal
from app.models import PasswordResetToken, User, utcnow
from tests.conftest import DEFAULT_PASSWORD, csrf_headers, make_admin, register_user


@pytest.fixture()
def mailbox(monkeypatch):
    sent: list[mailer.Message] = []

    def capture(message: mailer.Message) -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(mailer, "send_safely", capture)
    return sent


@pytest.fixture()
def tight_ban(monkeypatch):
    """Two rejections inside a minute are enough to earn a one-minute ban."""
    monkeypatch.setattr(settings, "form_ban_enabled", True)
    monkeypatch.setattr(settings, "form_ban_strikes", 2)
    monkeypatch.setattr(settings, "form_ban_window_seconds", 60)
    monkeypatch.setattr(settings, "form_ban_seconds", 60)
    monkeypatch.setattr(settings, "form_ban_allowlist", "")
    abuse.BANS.reset()
    yield
    abuse.BANS.reset()


def test_private_addresses_are_never_banned():
    # The operator's own probes and monitoring reach the app from here.
    assert abuse._allowlisted("127.0.0.1")
    assert abuse._allowlisted("172.18.0.5")
    assert abuse._allowlisted("10.1.2.3")
    assert abuse._allowlisted("192.168.1.10")
    assert not abuse._allowlisted("203.0.113.9")


def test_an_allowlisted_network_is_never_banned(monkeypatch):
    monkeypatch.setattr(settings, "form_ban_allowlist", "203.0.113.0/24")
    assert abuse._allowlisted("203.0.113.9")
    assert not abuse._allowlisted("198.51.100.7")


def test_a_visitor_who_keeps_being_refused_ends_up_blocked(client, tight_ban, monkeypatch):
    monkeypatch.setattr(settings, "auth_rate_limit", 2)
    monkeypatch.setattr(settings, "auth_rate_window_seconds", 60)
    payload = {"email": "nobody@example.com", "password": "WrongPassword1!"}

    first = client.post("/api/v1/auth/login", json=payload)
    second = client.post("/api/v1/auth/login", json=payload)
    assert first.status_code == 401 and second.status_code == 401

    # Past the budget: refused, and each refusal is a strike.
    assert client.post("/api/v1/auth/login", json=payload).status_code == 429
    assert client.post("/api/v1/auth/login", json=payload).status_code == 429

    blocked = client.post("/api/v1/auth/login", json=payload)
    assert blocked.status_code == 429
    assert "temporarily blocked" in blocked.json()["detail"]
    assert 0 < int(blocked.headers["Retry-After"]) <= 60

    # A different form is refused for the same reason: the ban is on the visitor.
    assert client.post("/api/v1/auth/password/forgot", json={"email": "x@example.com"}).status_code == 429


def test_an_administrator_can_lift_a_ban(client, tight_ban, monkeypatch):
    monkeypatch.setattr(settings, "auth_rate_limit", 1)
    register_user(client, email="boss@example.com")
    make_admin(client)

    payload = {"email": "nobody@example.com", "password": "WrongPassword1!"}
    for _ in range(4):
        client.post("/api/v1/auth/login", json=payload)
    assert abuse.BANS.entries(), "the ban should be visible"

    listing = client.get("/api/v1/admin/security/bans")
    assert listing.status_code == 200
    assert listing.json()["enabled"] is True
    assert listing.json()["threshold"] == 2
    assert listing.json()["entries"]

    lifted = client.delete("/api/v1/admin/security/bans/testclient", headers=csrf_headers(client))
    assert lifted.status_code == 204
    assert abuse.BANS.banned_for("testclient") == 0


def test_a_moderator_cannot_lift_a_ban(client, tight_ban):
    register_user(client, email="mod@example.com")
    response = client.get("/api/v1/admin/security/bans")
    assert response.status_code in (401, 403)


def test_the_password_reset_mail_is_sent_once_per_interval(client, mailbox):
    register_user(client, email="victim@example.com")

    def resets():
        return [message for message in mailbox if "Reset your" in message.subject]

    assert client.post("/api/v1/auth/password/forgot", json={"email": "victim@example.com"}).status_code == 202
    assert len(resets()) == 1

    again = client.post("/api/v1/auth/password/forgot", json={"email": "victim@example.com"})
    assert again.status_code == 202
    assert again.json()["detail"].startswith("If an account exists")
    assert len(resets()) == 1, "a second mail inside five minutes is the spam vector"

    with SessionLocal() as db:
        assert len(db.scalars(select(PasswordResetToken)).all()) == 1
        events = [row.event for row in db.scalars(select(__import__("app.models", fromlist=["SecurityEvent"]).SecurityEvent)).all()]
    assert "password_reset_throttled" in events


def test_the_reset_mail_comes_back_after_the_interval(client, mailbox, monkeypatch):
    monkeypatch.setattr(settings, "password_reset_interval_seconds", 300)
    register_user(client, email="later@example.com")
    client.post("/api/v1/auth/password/forgot", json={"email": "later@example.com"})
    resets = lambda: [message for message in mailbox if "Reset your" in message.subject]  # noqa: E731
    assert len(resets()) == 1

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "later@example.com"))
        row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
        row.created_at = utcnow() - timedelta(minutes=6)
        db.add(row)
        db.commit()

    client.post("/api/v1/auth/password/forgot", json={"email": "later@example.com"})
    assert len(resets()) == 2


def test_an_unknown_address_is_still_answered_the_same_way(client, mailbox):
    response = client.post("/api/v1/auth/password/forgot", json={"email": "ghost@example.com"})

    assert response.status_code == 202
    assert response.json() == {"detail": "If an account exists for this address, a reset link has been sent."}
    assert mailbox == []


def test_the_interval_does_not_reveal_whether_the_account_exists(client, mailbox):
    register_user(client, email="known@example.com")
    client.post("/api/v1/auth/password/forgot", json={"email": "known@example.com"})
    throttled = client.post("/api/v1/auth/password/forgot", json={"email": "known@example.com"})
    unknown = client.post("/api/v1/auth/password/forgot", json={"email": "unknown@example.com"})

    assert throttled.status_code == unknown.status_code == 202
    assert throttled.json() == unknown.json()
    assert DEFAULT_PASSWORD  # the fixture password is the documented valid one
