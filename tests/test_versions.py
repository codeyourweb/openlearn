# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Draft autosave, version snapshots, publication and rollback."""

from __future__ import annotations

from app.db import SessionLocal
from app.models import Quiz, QuizVersion, User
from tests.conftest import (
    csrf_headers,
    create_quiz,
    make_admin,
    make_trusted,
    question_payload,
    quiz_payload,
    register_user,
)


def draft_payload(title: str = "Work in progress", *, questions=None) -> dict:
    return {
        "title": title,
        "description": "",
        "mode": "qcm",
        "questions": questions or [],
    }


def publish(client, quiz_id: int):
    return client.post(
        f"/api/v1/quizzes/{quiz_id}/publish",
        json={"note": ""},
        headers=csrf_headers(client),
    )


def visibility(client, quiz_id: int, value: str):
    return client.post(
        f"/api/v1/quizzes/{quiz_id}/visibility",
        json={"visibility": value},
        headers=csrf_headers(client),
    )


def revoke_trust(quiz_id: int) -> None:
    with SessionLocal() as db:
        owner = db.get(User, db.get(Quiz, quiz_id).owner_id)
        owner.is_trusted = False
        db.commit()


def catalogue(client) -> list[dict]:
    return client.get("/api/v1/quizzes").json()


# ---------------------------------------------------------------------------
# Autosaved drafts
# ---------------------------------------------------------------------------
def test_autosave_starts_from_an_almost_empty_document(client):
    register_user(client)
    created = client.post(
        "/api/v1/quizzes/draft", json=draft_payload(""), headers=csrf_headers(client)
    )
    assert created.status_code == 201, created.text
    body = created.json()
    # An untitled, question-less document is a legitimate autosave target.
    assert body["title"] == "Untitled quiz"
    assert body["status"] == "draft"
    assert body["questions"] == []


def test_autosave_updates_the_same_document(client):
    register_user(client)
    quiz = client.post(
        "/api/v1/quizzes/draft", json=draft_payload("Story"), headers=csrf_headers(client)
    ).json()

    for index in range(3):
        saved = client.put(
            f"/api/v1/quizzes/{quiz['id']}/draft",
            json=draft_payload(
                f"Story {index}",
                questions=[
                    {
                        "text_html": f"<p>Step {index}</p>",
                        "options": [{"text": "Yes", "is_correct": True}, {"text": "", "is_correct": False}],
                    }
                ],
            ),
            headers=csrf_headers(client),
        )
        assert saved.status_code == 200, saved.text

    mine = client.get("/api/v1/quizzes/mine").json()
    assert len([row for row in mine if row["title"].startswith("Story")]) == 1
    detail = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    assert detail["title"] == "Story 2"
    # An empty option text is allowed while editing.
    assert detail["questions"][0]["options"][1]["text"] == ""


def test_autosave_cannot_touch_someone_elses_quiz(client):
    register_user(client)
    quiz = create_quiz(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="intruder@example.com", display_name="Intruder")
    response = client.put(
        f"/api/v1/quizzes/{quiz['id']}/draft",
        json=draft_payload("Hijacked"),
        headers=csrf_headers(client),
    )
    assert response.status_code == 403


def test_draft_autosave_never_publishes_an_incomplete_quiz(client):
    register_user(client)
    make_trusted(client)
    quiz = create_quiz(client)
    visibility(client, quiz["id"], "public")

    # The autosave is permissive, the publication is not.
    client.put(
        f"/api/v1/quizzes/{quiz['id']}/draft",
        json=draft_payload("Broken", questions=[{"text_html": "<p>?</p>", "options": []}]),
        headers=csrf_headers(client),
    )
    response = publish(client, quiz["id"])
    assert response.status_code == 422
    # The previously published version is still online.
    assert [row["id"] for row in catalogue(client)] == [quiz["id"]]


# ---------------------------------------------------------------------------
# Version snapshots
# ---------------------------------------------------------------------------
def test_publishing_freezes_a_version(client):
    register_user(client)
    quiz = create_quiz(client)
    assert quiz["published_version"] == 0

    make_trusted(client)
    result = visibility(client, quiz["id"], "public")
    assert result.status_code == 200, result.text
    assert result.json()["published_version"] == 1

    versions = client.get(f"/api/v1/quizzes/{quiz['id']}/versions").json()
    assert [row["number"] for row in versions] == [1]
    assert versions[0]["approved_at"] is not None


def test_editing_keeps_serving_the_published_version(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload("Public title"))
    make_trusted(client)
    visibility(client, quiz["id"], "public")

    edited = client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload("Unpublished title"),
        headers=csrf_headers(client),
    )
    assert edited.json()["title"] == "Unpublished title"

    # The owner edits the working copy, a visitor still reads version 1.
    assert [row["title"] for row in catalogue(client)] == ["Public title"]
    visitor = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    assert visitor["title"] == "Unpublished title"

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    anonymous = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    assert anonymous["title"] == "Public title"
    assert anonymous["questions"][0].get("is_correct") is None


def test_a_new_version_needs_moderation_and_keeps_the_old_one_live(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload("Version one"))
    make_trusted(client)
    visibility(client, quiz["id"], "public")

    revoke_trust(quiz["id"])
    client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload("Version two"),
        headers=csrf_headers(client),
    )
    pending = publish(client, quiz["id"])
    assert pending.status_code == 200, pending.text
    assert pending.json()["requires_moderation"] is True
    assert pending.json()["published_version"] == 1
    assert [row["title"] for row in catalogue(client)] == ["Version one"]

    make_admin(client)
    approved = client.post(
        f"/api/v1/admin/quizzes/{quiz['id']}/approve",
        json={"note": "Fine"},
        headers=csrf_headers(client),
    )
    assert approved.status_code == 200
    assert approved.json()["published_version"] == 2
    assert [row["title"] for row in catalogue(client)] == ["Version two"]


def test_a_session_plays_the_published_version(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload("Live", questions=[question_payload("Published?")]))
    make_trusted(client)
    visibility(client, quiz["id"], "public")

    client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload(
            "Live",
            questions=[question_payload("Draft?"), question_payload("Draft two?")],
        ),
        headers=csrf_headers(client),
    )
    session = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions",
        json={"mode": "solo"},
        headers=csrf_headers(client),
    )
    assert session.status_code == 201, session.text
    state = session.json()["state"]
    assert "Published?" in state["question"]["text_html"]
    with SessionLocal() as db:
        session_quiz = db.get(Quiz, quiz["id"])
        assert session_quiz.published_version_number == 1


def test_restoring_a_version_republishes_it(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload("Draft A"))
    make_trusted(client)
    visibility(client, quiz["id"], "public")

    client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload("Draft B"),
        headers=csrf_headers(client),
    )
    second = publish(client, quiz["id"])
    assert second.json()["published_version"] == 2
    assert [row["title"] for row in catalogue(client)] == ["Draft B"]

    restored = client.post(
        f"/api/v1/quizzes/{quiz['id']}/versions/1/restore",
        json={"publish": True},
        headers=csrf_headers(client),
    )
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["restored"] == 1
    assert body["quiz"]["title"] == "Draft A"
    # A rollback is a new version built from the old content.
    assert body["published_version"] == 3
    assert [row["title"] for row in catalogue(client)] == ["Draft A"]


def test_restoring_an_approved_version_skips_moderation(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload("Approved once"))
    make_trusted(client)
    visibility(client, quiz["id"], "public")
    revoke_trust(quiz["id"])

    client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload("Not approved"),
        headers=csrf_headers(client),
    )
    restored = client.post(
        f"/api/v1/quizzes/{quiz['id']}/versions/1/restore",
        json={"publish": True},
        headers=csrf_headers(client),
    )
    assert restored.status_code == 200, restored.text
    # The restored content was already validated by a moderator.
    assert restored.json()["status"] == "public"
    assert [row["title"] for row in catalogue(client)] == ["Approved once"]


def test_restoring_without_publishing_only_touches_the_working_copy(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload("Keep me"))
    make_trusted(client)
    visibility(client, quiz["id"], "public")
    client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload("Edited"),
        headers=csrf_headers(client),
    )
    restored = client.post(
        f"/api/v1/quizzes/{quiz['id']}/versions/1/restore",
        json={},
        headers=csrf_headers(client),
    )
    assert restored.json()["quiz"]["title"] == "Keep me"
    assert restored.json()["published_version"] == 1
    assert [row["title"] for row in catalogue(client)] == ["Keep me"]


def test_versions_are_private_to_the_owner(client):
    register_user(client)
    quiz = create_quiz(client)
    make_trusted(client)
    visibility(client, quiz["id"], "public")
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))

    register_user(client, email="nosy@example.com", display_name="Nosy")
    assert client.get(f"/api/v1/quizzes/{quiz['id']}/versions").status_code == 403
    assert client.get(f"/api/v1/quizzes/{quiz['id']}/versions/1").status_code == 403


def test_version_payload_is_a_full_quiz_document(client):
    register_user(client)
    quiz = create_quiz(client)
    make_trusted(client)
    visibility(client, quiz["id"], "public")

    detail = client.get(f"/api/v1/quizzes/{quiz['id']}/versions/1").json()
    assert detail["is_live"] is True
    assert len(detail["payload"]["questions"]) == len(quiz["questions"])
    # The snapshot keeps the answer key: it is what a restore replays.
    assert any(option["is_correct"] for option in detail["payload"]["questions"][0]["options"])


def test_a_frozen_version_survives_later_edits(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload("Snapshot"))
    make_trusted(client)
    visibility(client, quiz["id"], "public")
    client.put(
        f"/api/v1/quizzes/{quiz['id']}",
        json=quiz_payload("Snapshot", questions=[question_payload("Replaced?")]),
        headers=csrf_headers(client),
    )
    with SessionLocal() as db:
        version = db.query(QuizVersion).filter_by(quiz_id=quiz["id"], number=1).one()
        assert version.payload["questions"][0]["text_html"] == "<p>Question one?</p>"


def test_catalogue_pagination_exposes_the_total(client):
    register_user(client)
    make_trusted(client)
    for index in range(12):
        quiz = create_quiz(client, quiz_payload(f"Quiz {index:02d}"))
        visibility(client, quiz["id"], "public")

    first = client.get("/api/v1/quizzes", params={"limit": 10, "offset": 0})
    assert len(first.json()) == 10
    assert first.headers["X-Total-Count"] == "12"

    second = client.get("/api/v1/quizzes", params={"limit": 10, "offset": 10})
    assert len(second.json()) == 2
    assert first.json()[0]["id"] != second.json()[0]["id"]


def test_sessions_shuffle_questions_but_keep_swipe_order(client):
    register_user(client)
    payload = quiz_payload(
        "Swipe deck",
        questions=[
            question_payload("Card one?", [("Yes", True), ("No", False)]),
            question_payload("Card two?", [("Yes", True), ("No", False)]),
            question_payload("Card three?", [("Yes", True), ("No", False)]),
        ],
    )
    payload["mode"] = "swipe"
    quiz = create_quiz(client, payload)

    orders = set()
    for _ in range(8):
        created = client.post(
            f"/api/v1/quizzes/{quiz['id']}/sessions",
            json={"mode": "solo"},
            headers=csrf_headers(client),
        )
        assert created.status_code == 201, created.text
        state = created.json()["state"]
        # Swipe keeps "yes" on the right and "no" on the left.
        assert [option["text"] for option in state["question"]["options"]] == ["Yes", "No"]
        orders.add(state["question"]["text_html"])

    # Over several sessions the deck does not always start with the same card.
    assert len(orders) > 1
