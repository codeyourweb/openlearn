# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Game sessions: lobby, locking, answers, scoring and results."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import GameSession, utcnow
from tests.conftest import (
    DEFAULT_PASSWORD,
    answer_key,
    csrf_headers,
    create_quiz,
    publish_quiz,
    question_payload,
    quiz_payload,
    register_user,
)


def host_headers(client, host_token: str) -> dict[str, str]:
    return {**csrf_headers(client), "X-Host-Token": host_token}


def create_live_session(client, quiz_id: int) -> dict:
    response = client.post(
        f"/api/v1/quizzes/{quiz_id}/sessions",
        json={"mode": "live"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_solo_session(client, quiz_id: int, nickname: str = "Solo") -> dict:
    response = client.post(
        f"/api/v1/quizzes/{quiz_id}/sessions",
        json={"mode": "solo", "nickname": nickname},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def join_as_guest(code: str, nickname: str) -> tuple[TestClient, str]:
    guest = TestClient(client_app())
    response = guest.post(f"/api/v1/sessions/{code}/join", json={"nickname": nickname})
    assert response.status_code == 201, response.text
    return guest, response.json()["participant"]["token"]


def client_app():
    from app.main import app

    return app


def test_hosting_a_draft_requires_ownership(client):
    register_user(client)
    quiz = create_quiz(client)
    headers = csrf_headers(client)
    client.post("/api/v1/auth/logout", headers=headers)

    # A draft is invisible, so an anonymous visitor cannot host it...
    response = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "live"})
    assert response.status_code == 404

    # ...but a published quiz can be driven by anyone, signed in or not.
    client.post("/api/v1/auth/login", json={"email": "player@example.com", "password": DEFAULT_PASSWORD})
    publish_quiz(client, quiz["id"])
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    hosted = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "live"})
    assert hosted.status_code == 201
    assert hosted.json()["host_token"]
    assert hosted.json()["session"]["status"] == "lobby"


def test_solo_session_starts_immediately_and_hides_answers(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_solo_session(client, quiz["id"])

    state = created["state"]
    assert state["session"]["status"] == "active"
    assert state["session"]["phase"] == "question"
    assert state["session"]["is_solo"] is True
    assert state["question"]["options"]
    assert all("is_correct" not in option for option in state["question"]["options"])


def test_full_live_flow(client):
    register_user(client, email="host@example.com", display_name="Host")
    quiz = create_quiz(client)
    created = create_live_session(client, quiz["id"])
    code = created["session"]["code"]
    host_token = created["host_token"]
    assert created["session"]["status"] == "lobby"

    guest, participant_token = join_as_guest(code, "Alice")
    player_headers = {"X-Participant-Token": participant_token}

    # Lobby state is visible to the host and hides the questions.
    lobby = client.get(f"/api/v1/sessions/{code}/state", headers=host_headers(client, host_token))
    assert lobby.status_code == 200
    assert lobby.json()["question"] is None
    assert len(lobby.json()["participants"]) == 1

    start = client.post(f"/api/v1/sessions/{code}/start", headers=host_headers(client, host_token))
    assert start.status_code == 200
    state = start.json()["state"]
    question = state["question"]
    key = answer_key(question, quiz)
    correct_option = key["correct"][0]

    answer = guest.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question["id"], "option_ids": key["correct"]},
        headers=player_headers,
    )
    assert answer.status_code == 201, answer.text
    assert answer.json()["answer"]["is_correct"] is True
    assert answer.json()["score"] == 100

    # The only player answered: the question is automatically revealed.
    state = client.get(f"/api/v1/sessions/{code}/state", headers=host_headers(client, host_token)).json()
    assert state["session"]["phase"] == "reveal"
    assert correct_option in state["reveal"]["correct_option_ids"]

    advance = client.post(f"/api/v1/sessions/{code}/next", headers=host_headers(client, host_token))
    assert advance.status_code == 200
    second = advance.json()["state"]["question"]
    # The session order is shuffled, so the second question is not fixed.
    assert second["text_html"] != question["text_html"]
    assert second["options"]

    key2 = answer_key(second, quiz)
    scored = guest.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": second["id"], "option_ids": key2["correct"]},
        headers=player_headers,
    )
    assert scored.status_code == 201
    assert scored.json()["answer"]["is_correct"] is True
    assert scored.json()["score"] == 200

    finish = client.post(f"/api/v1/sessions/{code}/next", headers=host_headers(client, host_token))
    assert finish.status_code == 200
    assert finish.json()["status"] == "finished"

    results = client.get(f"/api/v1/sessions/{code}/results", headers=host_headers(client, host_token))
    assert results.status_code == 200
    payload = results.json()
    assert payload["viewer"]["role"] == "host"
    assert len(payload["questions"]) == 2
    assert payload["scoreboard"][0]["nickname"] == "Alice"
    assert payload["scoreboard"][0]["score"] == 200
    # Results are ordered by session position, so the second question is the
    # one the player answered last.
    second_rows = payload["questions"][1]["answers"]
    assert second_rows[0]["answered"] is True
    assert second_rows[0]["is_correct"] is True


def test_no_join_after_start(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_live_session(client, quiz["id"])
    code = created["session"]["code"]
    host_token = created["host_token"]

    join_as_guest(code, "First")
    client.post(f"/api/v1/sessions/{code}/start", headers=host_headers(client, host_token))

    late = TestClient(client_app())
    response = late.post(f"/api/v1/sessions/{code}/join", json={"nickname": "Late"})
    assert response.status_code == 409


def test_duplicate_nickname_is_rejected(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_live_session(client, quiz["id"])
    code = created["session"]["code"]
    join_as_guest(code, "Alice")

    second = TestClient(client_app())
    response = second.post(f"/api/v1/sessions/{code}/join", json={"nickname": "Alice"})
    assert response.status_code == 409


def test_solo_session_cannot_be_joined(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_solo_session(client, quiz["id"])
    guest = TestClient(client_app())
    response = guest.post(f"/api/v1/sessions/{created['session']['code']}/join", json={"nickname": "Guest"})
    assert response.status_code == 403


def test_multiple_answers_require_every_correct_option(client):
    register_user(client)
    quiz = create_quiz(
        client,
        quiz_payload(
            questions=[
                question_payload(
                    "Pick both",
                    [("A", True), ("B", True), ("C", False), ("D", False)],
                )
            ]
        ),
    )
    created = create_solo_session(client, quiz["id"])
    code = created["session"]["code"]
    token = created["participant"]["token"]
    question = created["state"]["question"]
    key = answer_key(question, quiz)

    full = client.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question["id"], "option_ids": key["correct"]},
        headers={"X-Participant-Token": token},
    )
    assert full.status_code == 201
    assert full.json()["answer"]["is_correct"] is True

    # Also selecting a wrong option invalidates the answer.
    quiz2 = create_quiz(
        client,
        quiz_payload(
            title="Strict multi",
            questions=[question_payload("Pick both", [("A", True), ("B", True), ("C", False)])],
        ),
    )
    second = create_solo_session(client, quiz2["id"])
    q2 = second["state"]["question"]
    key2 = answer_key(q2, quiz2)
    wrong_extra = client.post(
        f"/api/v1/sessions/{second['session']['code']}/answers",
        json={"question_id": q2["id"], "option_ids": [key2["correct"][0], key2["wrong"][0]]},
        headers={"X-Participant-Token": second["participant"]["token"]},
    )
    assert wrong_extra.json()["answer"]["is_correct"] is False


def test_penalty_policy_subtracts_points(client):
    register_user(client)
    quiz = create_quiz(client, quiz_payload(policy="penalty"))
    created = create_solo_session(client, quiz["id"])
    question = created["state"]["question"]
    wrong_option = answer_key(question, quiz)["wrong"][0]
    response = client.post(
        f"/api/v1/sessions/{created['session']['code']}/answers",
        json={"question_id": question["id"], "option_ids": [wrong_option]},
        headers={"X-Participant-Token": created["participant"]["token"]},
    )
    assert response.status_code == 201
    assert response.json()["answer"]["points_awarded"] == -100
    assert response.json()["score"] == -100


def test_answer_rules(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_solo_session(client, quiz["id"])
    code = created["session"]["code"]
    token = created["participant"]["token"]
    headers = {"X-Participant-Token": token}
    question = created["state"]["question"]

    unknown = client.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question["id"], "option_ids": [999999]},
        headers=headers,
    )
    assert unknown.status_code == 400

    stale = client.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": 424242, "option_ids": [question["options"][0]["id"]]},
        headers=headers,
    )
    assert stale.status_code == 409

    ok = client.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question["id"], "option_ids": [question["options"][0]["id"]]},
        headers=headers,
    )
    assert ok.status_code == 201

    duplicate = client.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question["id"], "option_ids": [question["options"][0]["id"]]},
        headers=headers,
    )
    assert duplicate.status_code == 409


def test_late_answer_is_rejected(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_solo_session(client, quiz["id"])
    code = created["session"]["code"]
    question = created["state"]["question"]

    with SessionLocal() as db:
        session = db.scalar(select(GameSession).where(GameSession.code == code))
        session.question_deadline = utcnow() - timedelta(seconds=5)
        db.add(session)
        db.commit()

    response = client.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question["id"], "option_ids": [question["options"][0]["id"]]},
        headers={"X-Participant-Token": created["participant"]["token"]},
    )
    assert response.status_code == 409


def test_results_access_control(client):
    register_user(client, email="host3@example.com", display_name="Host")
    quiz = create_quiz(client)
    created = create_live_session(client, quiz["id"])
    code = created["session"]["code"]
    host_token = created["host_token"]
    guest, participant_token = join_as_guest(code, "Bob")
    client.post(f"/api/v1/sessions/{code}/start", headers=host_headers(client, host_token))

    anonymous = TestClient(client_app())
    assert anonymous.get(f"/api/v1/sessions/{code}/results").status_code == 403

    player_view = guest.get(
        f"/api/v1/sessions/{code}/results", headers={"X-Participant-Token": participant_token}
    )
    assert player_view.status_code == 200
    assert player_view.json()["viewer"]["role"] == "participant"
    assert player_view.json()["scoreboard"][0]["nickname"] == "Bob"
    for question in player_view.json()["questions"]:
        assert all(row["nickname"] == "Bob" for row in question["answers"])


def test_state_requires_membership(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_live_session(client, quiz["id"])
    anonymous = TestClient(client_app())
    response = anonymous.get(f"/api/v1/sessions/{created['session']['code']}/state")
    assert response.status_code == 403


def test_cancel_session(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_live_session(client, quiz["id"])
    code = created["session"]["code"]
    response = client.post(f"/api/v1/sessions/{code}/cancel", headers=host_headers(client, created["host_token"]))
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_join_link_resolution(client):
    register_user(client)
    quiz = create_quiz(client)
    created = create_live_session(client, quiz["id"])
    code = created["session"]["code"]

    anonymous = TestClient(client_app())
    resolved = anonymous.get(f"/api/v1/join/{created['join_token']}")
    assert resolved.status_code == 200
    assert resolved.json()["code"] == code
    assert anonymous.get("/api/v1/join/does-not-exist").status_code == 404


def test_share_links_follow_the_public_scheme(client):
    """Behind the TLS proxy, share links must not fall back to plain http."""
    register_user(client)
    quiz = create_quiz(client)
    headers = {
        **csrf_headers(client),
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "quiz.example.org",
    }
    created = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "live"}, headers=headers
    )
    assert created.status_code == 201
    body = created.json()
    assert body["join_url"].startswith("https://quiz.example.org/join/")

    code = body["session"]["code"]
    host_headers = {"X-Host-Token": body["host_token"], **headers}
    link = client.get(f"/api/v1/sessions/{code}/join-link", headers=host_headers).json()
    assert link["join_url"].startswith("https://quiz.example.org/join/")
