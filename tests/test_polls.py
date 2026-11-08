# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Polls: no answer key, live tallies, and a result policy the author chooses."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import (
    csrf_headers,
    create_quiz,
    publish_quiz,
    question_payload,
    quiz_payload,
    register_user,
)


def client_app():
    from app.main import app

    return app


def poll_payload(*, visibility: str = "respondents", multiple: bool = False) -> dict:
    question = question_payload("Which channel do you use most?", [("Chat", False), ("Email", False)])
    question["allow_multiple"] = multiple
    question["points"] = 0
    payload = quiz_payload("Team habits", questions=[question])
    payload["mode"] = "poll"
    payload["results_visibility"] = visibility
    return payload


def test_a_poll_accepts_answers_without_any_answer_key(client):
    register_user(client)
    quiz = create_quiz(client, poll_payload())
    assert quiz["mode"] == "poll"
    assert quiz["results_visibility"] == "respondents"
    assert all(option["is_correct"] is False for option in quiz["questions"][0]["options"])
    assert quiz["questions"][0]["points"] == 0


def test_a_scored_quiz_still_needs_one_correct_answer(client):
    register_user(client)
    payload = quiz_payload(questions=[question_payload("Q?", [("A", False), ("B", False)])])
    payload["mode"] = "qcm"
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 422


def test_playing_a_poll_never_scores(client):
    register_user(client)
    quiz = create_quiz(client, poll_payload())
    publish_quiz(client, quiz["id"])

    created = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions",
        json={"mode": "live"},
        headers=csrf_headers(client),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    code = body["session"]["code"]

    guest = TestClient(client_app())
    joined = guest.post(f"/api/v1/sessions/{code}/join", json={"nickname": "Voter"})
    assert joined.status_code == 201, joined.text
    token = joined.json()["participant"]["token"]

    client.post(
        f"/api/v1/sessions/{code}/start",
        headers={**csrf_headers(client), "X-Host-Token": body["host_token"]},
    )
    state = guest.get(
        f"/api/v1/sessions/{code}/state", headers={"X-Participant-Token": token}
    ).json()
    question = state["question"]
    assert question["multiple_answers"] is False
    chosen = question["options"][0]["id"]
    sent = guest.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question["id"], "option_ids": [chosen], "response_ms": 900},
        headers={"X-Participant-Token": token, **csrf_headers(guest)},
    )
    assert sent.status_code in (200, 201), sent.text
    assert sent.json()["answer"]["points_awarded"] == 0
    assert sent.json()["answer"]["is_correct"] is False


def test_poll_results_stay_private_to_the_author_until_they_say_otherwise(client):
    register_user(client)
    quiz = create_quiz(client, poll_payload(visibility="private"))
    publish_quiz(client, quiz["id"])

    author_view = client.get(f"/api/v1/quizzes/{quiz['id']}/results")
    assert author_view.status_code == 200, author_view.text
    assert author_view.json()["results_visibility"] == "private"
    assert author_view.json()["respondents"] == 0
    assert author_view.json()["questions"][0]["options"][0]["count"] == 0

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="reader@example.com", display_name="Reader")
    anonymous_view = client.get(f"/api/v1/quizzes/{quiz['id']}/results")
    assert anonymous_view.status_code == 403
    assert "private" in anonymous_view.json()["detail"].lower()


def test_a_public_poll_shows_its_tally_to_anyone_who_can_open_it(client):
    register_user(client)
    quiz = create_quiz(client, poll_payload(visibility="public"))
    publish_quiz(client, quiz["id"])

    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    register_user(client, email="reader@example.com", display_name="Reader")
    response = client.get(f"/api/v1/quizzes/{quiz['id']}/results")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results_visibility"] == "public"
    assert body["mode"] == "poll"
    assert body["questions"][0]["allow_multiple"] is False


def test_poll_questions_can_allow_several_answers(client):
    register_user(client)
    quiz = create_quiz(client, poll_payload(multiple=True))
    assert quiz["questions"][0]["allow_multiple"] is True
    assert quiz["questions"][0]["multiple_answers"] is True

def _vote(guest, code, question, texts, token):
    """Answer by option text: the option order is shuffled per session."""
    chosen = [
        option["id"] for option in question["options"] if (option.get("text") or "").strip() in texts
    ]
    assert len(chosen) == len(texts), (texts, [option.get("text") for option in question["options"]])
    return guest.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question["id"], "option_ids": chosen, "response_ms": 700},
        headers={"X-Participant-Token": token, **csrf_headers(guest)},
    )


def test_each_option_is_credited_only_with_the_answers_that_picked_it(client):
    """A tally is per chosen option, not per answer.

    Joining answers to options on the question alone credits every option with
    every vote, which showed up as four options at 25 % from six voters.
    """
    register_user(client)
    question = question_payload("Pick a channel", [("A", False), ("B", False), ("C", False), ("D", False)])
    question["allow_multiple"] = True
    question["points"] = 0
    payload = quiz_payload("Tally accuracy", questions=[question])
    payload["mode"] = "poll"
    payload["results_visibility"] = "public"
    quiz = create_quiz(client, payload)
    publish_quiz(client, quiz["id"])

    created = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions",
        json={"mode": "live"},
        headers=csrf_headers(client),
    )
    body = created.json()
    code = body["session"]["code"]

    voters = []
    for nickname in ("First", "Second"):
        guest = TestClient(client_app())
        joined = guest.post(f"/api/v1/sessions/{code}/join", json={"nickname": nickname})
        voters.append((guest, joined.json()["participant"]["token"]))

    client.post(
        f"/api/v1/sessions/{code}/start",
        headers={**csrf_headers(client), "X-Host-Token": body["host_token"]},
    )
    question = voters[0][0].get(
        f"/api/v1/sessions/{code}/state", headers={"X-Participant-Token": voters[0][1]}
    ).json()["question"]

    assert _vote(voters[0][0], code, question, {"A"}, voters[0][1]).status_code in (200, 201)
    assert _vote(voters[1][0], code, question, {"A", "B"}, voters[1][1]).status_code in (200, 201)

    report = client.get(f"/api/v1/quizzes/{quiz['id']}/results")
    assert report.status_code == 200, report.text
    row = report.json()["questions"][0]
    counts = {option["text"]: option["count"] for option in row["options"]}
    assert counts == {"A": 2, "B": 1, "C": 0, "D": 0}, counts
    # Two people answered, even though three boxes were ticked.
    assert row["respondents"] == 2
    shares = {option["text"]: option["share"] for option in row["options"]}
    assert shares["A"] == 1.0 and shares["B"] == 0.5
