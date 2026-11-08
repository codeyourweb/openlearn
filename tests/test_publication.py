# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Publication workflow: draft, private, moderation queue and rejection."""

from __future__ import annotations

from app.db import SessionLocal
from app.models import Quiz, User
from tests.conftest import (
    create_quiz,
    csrf_headers,
    make_admin,
    make_trusted,
    quiz_payload,
    register_user,
)


def set_status(quiz_id: int, status: str, *, legal: str = "") -> None:
    with SessionLocal() as db:
        quiz = db.get(Quiz, quiz_id)
        quiz.status = status
        quiz.is_public = status == "public"
        quiz.legal_status = legal
        db.commit()


def visibility(client, quiz_id: int, value: str):
    return client.post(
        f"/api/v1/quizzes/{quiz_id}/visibility",
        json={"visibility": value},
        headers=csrf_headers(client),
    )


def test_new_quiz_is_a_private_draft(client):
    register_user(client)
    quiz = create_quiz(client)
    assert quiz["status"] == "draft"
    assert quiz["is_public"] is False
    assert client.get("/api/v1/quizzes").json() == []


def test_untrusted_author_goes_through_moderation(client):
    register_user(client)
    quiz = create_quiz(client)

    pending = visibility(client, quiz["id"], "public")
    assert pending.status_code == 200
    # Queued for a moderator, but still usable: the author plays it by link
    # while the review is pending, hence the private status rather than "pending".
    assert pending.json()["status"] == "private"
    assert pending.json()["requires_moderation"] is True

    # Not in the public catalogue until an administrator approves it.
    assert client.get("/api/v1/quizzes").json() == []
    make_admin(client)
    approved = client.post(
        f"/api/v1/admin/quizzes/{quiz['id']}/approve",
        json={"note": "Looks good"},
        headers=csrf_headers(client),
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "public"
    assert len(client.get("/api/v1/quizzes").json()) == 1


def test_admin_rejection_keeps_the_quiz_private(client):
    register_user(client)
    quiz = create_quiz(client)
    visibility(client, quiz["id"], "public")
    make_admin(client)
    rejected = client.post(
        f"/api/v1/admin/quizzes/{quiz['id']}/reject",
        json={"note": "Off topic"},
        headers=csrf_headers(client),
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["moderation_note"] == "Off topic"
    assert client.get("/api/v1/quizzes").json() == []


def test_trusted_author_publishes_directly(client):
    register_user(client)
    quiz = create_quiz(client)
    make_trusted(client)
    published = visibility(client, quiz["id"], "public")
    assert published.json()["status"] == "public"
    assert published.json()["requires_moderation"] is False
    assert len(client.get("/api/v1/quizzes").json()) == 1


def test_blocked_quiz_cannot_be_published(client):
    register_user(client)
    quiz = create_quiz(client)
    set_status(quiz["id"], "draft", legal="blocked")
    response = visibility(client, quiz["id"], "public")
    assert response.status_code == 409


def test_editing_a_public_quiz_never_unpublishes_it(client):
    register_user(client)
    quiz = create_quiz(client)
    make_trusted(client)
    visibility(client, quiz["id"], "public")
    assert client.get("/api/v1/quizzes").json()

    updated = client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload("Edited title"),
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "public"

    # Losing the trusted flag only affects the next publication, not the live one.
    with SessionLocal() as db:
        user = db.get(User, db.get(Quiz, quiz["id"]).owner_id)
        user.is_trusted = False
        db.commit()
    edited = client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload("Edited again"),
        headers=csrf_headers(client),
    )
    assert edited.json()["status"] == "public"
    assert edited.json()["title"] == "Edited again"
    # The catalogue still serves the last validated version.
    catalogue = client.get("/api/v1/quizzes").json()
    assert [row["title"] for row in catalogue] == ["Sample quiz"]


def test_pending_quiz_is_invisible_to_visitors(client):
    register_user(client)
    quiz = create_quiz(client)
    visibility(client, quiz["id"], "public")
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert client.get(f"/api/v1/quizzes/{quiz['id']}").status_code == 404


def test_owner_can_retire_a_public_quiz(client):
    register_user(client)
    quiz = create_quiz(client)
    make_trusted(client)
    visibility(client, quiz["id"], "public")
    retired = visibility(client, quiz["id"], "private")
    assert retired.json()["status"] == "private"
    assert client.get("/api/v1/quizzes").json() == []


def test_visibility_requires_ownership(client):
    register_user(client)
    quiz = create_quiz(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="other@example.com", display_name="Other")
    response = visibility(client, quiz["id"], "public")
    assert response.status_code == 403


def publish(client, quiz_id: int, visibility: str):
    return client.post(
        f"/api/v1/quizzes/{quiz_id}/publish",
        json={"note": "", "visibility": visibility},
        headers=csrf_headers(client),
    )


def test_an_author_can_publish_a_working_copy_in_private(client):
    """Private publication freezes a playable version without asking a moderator."""
    register_user(client)
    quiz = create_quiz(client)
    response = publish(client, quiz["id"], "private")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "private"
    assert body["is_public"] is False
    assert body["requires_moderation"] is False
    assert body["published_version"] == 1

    # Out of the catalogue, but the document is live: a link can play it.
    assert client.get("/api/v1/quizzes").json() == []
    detail = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    assert detail["published_version"] == 1

    created = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions",
        json={"mode": "live"},
        headers=csrf_headers(client),
    )
    assert created.status_code == 201, created.text


def test_asking_for_the_catalogue_queues_an_untrusted_author(client):
    register_user(client)
    quiz = create_quiz(client)
    response = publish(client, quiz["id"], "public")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requires_moderation"] is True
    assert body["can_publish_publicly"] is False
    # It is private but usable in the meantime, never silently invisible.
    assert body["status"] in ("private", "draft")
    assert client.get("/api/v1/quizzes").json() == []


def test_a_trusted_author_goes_straight_to_the_catalogue(client):
    register_user(client)
    quiz = create_quiz(client)
    make_trusted(client)
    response = publish(client, quiz["id"], "public")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "public"
    assert body["requires_moderation"] is False
    assert body["can_publish_publicly"] is True
    assert [row["id"] for row in client.get("/api/v1/quizzes").json()] == [quiz["id"]]


def test_a_private_publication_is_reported_to_the_editor(client):
    register_user(client)
    quiz = create_quiz(client)
    response = publish(client, quiz["id"], "private")
    assert response.status_code == 200
    detail = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    assert detail["can_publish_publicly"] is False
    assert detail["status"] == "private"
