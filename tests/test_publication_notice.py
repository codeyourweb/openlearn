# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""An author learns that their queued work went public — by mail, once."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app import mailer
from app.db import SessionLocal
from app.models import User, Wiki
from tests.conftest import create_quiz, csrf_headers, quiz_payload, register_user


@pytest.fixture()
def mailbox(monkeypatch):
    sent: list[mailer.Message] = []

    def capture(message: mailer.Message) -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(mailer, "send_safely", capture)
    return sent


def _approvals(mailbox: list[mailer.Message]) -> list[mailer.Message]:
    return [message for message in mailbox if "is public on" in message.subject]


def _promote_to_moderator(email: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        user.is_moderator = True
        user.is_trusted = True
        db.add(user)
        db.commit()


def _queued_quiz(client, title: str) -> dict:
    """A quiz an ordinary author submitted for publication."""
    quiz = create_quiz(client, quiz_payload(title, public=False))
    submitted = client.post(
        f"/api/v1/quizzes/{quiz['id']}/visibility",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    assert submitted.status_code == 200, submitted.text
    return quiz


def test_a_queued_quiz_mails_its_author_once_approved(client, mailbox):
    register_user(client, email="author@example.com", display_name="Ada")
    quiz = _queued_quiz(client, "Les volcans")
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    register_user(client, email="mod@example.com", display_name="Mod")
    _promote_to_moderator("mod@example.com")

    approved = client.post(
        f"/api/v1/admin/quizzes/{quiz['id']}/approve",
        json={"note": "Belle explication."},
        headers=csrf_headers(client),
    )
    assert approved.status_code == 200, approved.text

    sent = _approvals(mailbox)
    assert len(sent) == 1
    assert sent[0].to == "author@example.com"
    assert "Les volcans" in sent[0].text
    assert "Belle explication." in sent[0].text
    assert "/quizzes/" in sent[0].text


def test_a_queued_wiki_mails_its_author_once_approved(client, mailbox):
    register_user(client, email="writer@example.com", display_name="Grace")
    created = client.post(
        "/api/v1/wiki",
        json={"title": "Atelier markdown", "description": "Notes partagées"},
        headers=csrf_headers(client),
    )
    assert created.status_code in (200, 201), created.text
    wiki_id = created.json()["id"]

    # An ordinary author asking for public visibility: queued, not published.
    queued = client.post(
        f"/api/v1/wiki/{wiki_id}/publish",
        json={"visibility": "public"},
        headers=csrf_headers(client),
    )
    assert queued.status_code == 200, queued.text
    with SessionLocal() as db:
        assert db.get(Wiki, wiki_id).status == "pending"

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="mod2@example.com", display_name="Mod Two")
    _promote_to_moderator("mod2@example.com")

    approved = client.post(
        f"/api/v1/admin/wikis/{wiki_id}/approve", json={"note": ""}, headers=csrf_headers(client)
    )
    assert approved.status_code == 200, approved.text

    sent = _approvals(mailbox)
    assert len(sent) == 1
    assert sent[0].to == "writer@example.com"
    assert "Atelier markdown" in sent[0].text


def test_a_moderator_approving_their_own_work_is_not_mailed(client, mailbox):
    register_user(client, email="self@example.com", display_name="Self")
    quiz = _queued_quiz(client, "Mon propre quiz")
    _promote_to_moderator("self@example.com")

    approved = client.post(
        f"/api/v1/admin/quizzes/{quiz['id']}/approve", json={"note": ""}, headers=csrf_headers(client)
    )
    assert approved.status_code == 200
    assert _approvals(mailbox) == [], "nobody needs a mail about their own action"


def test_rejecting_says_nothing_by_mail(client, mailbox):
    register_user(client, email="rejected@example.com")
    quiz = _queued_quiz(client, "Trop court")
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="mod3@example.com")
    _promote_to_moderator("mod3@example.com")

    refused = client.post(
        f"/api/v1/admin/quizzes/{quiz['id']}/reject",
        json={"note": "Il manque des questions."},
        headers=csrf_headers(client),
    )
    assert refused.status_code == 200
    assert _approvals(mailbox) == []
