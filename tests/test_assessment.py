# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Assessment mode: one run per candidate, grants, private link, result book."""

from __future__ import annotations

import pytest

from conftest import csrf_headers, login_user, publish_quiz, question_payload, quiz_payload, register_user


def _quiz(client, *, attempts=1, public=True, title="Certification réseau"):
    payload = quiz_payload(title=title, public=public, questions=[question_payload()])
    payload["max_attempts"] = attempts
    response = client.post("/api/v1/quizzes", json=payload, headers=csrf_headers(client))
    assert response.status_code == 201, response.text
    return response.json()


def _publish(client, quiz_id):
    """Publishing publicly needs a trusted account; the helper grants it."""
    return publish_quiz(client, quiz_id)


def test_a_candidate_plays_once_and_the_second_run_is_refused(client):
    register_user(client, "owner@example.com")
    quiz = _quiz(client, attempts=1)
    _publish(client, quiz["id"])

    register_user(client, "candidate@example.com", display_name="Candidate")
    first = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"}, headers=csrf_headers(client))
    assert first.status_code == 201, first.text

    second = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"}, headers=csrf_headers(client))
    assert second.status_code == 409
    assert "already taken" in second.json()["detail"].lower()


def test_without_a_ceiling_the_candidate_may_retrain(client):
    register_user(client, "owner@example.com")
    quiz = _quiz(client, attempts=0)
    _publish(client, quiz["id"])
    register_user(client, "candidate@example.com")
    for _ in range(2):
        response = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"}, headers=csrf_headers(client))
        assert response.status_code == 201, response.text


def test_an_anonymous_candidate_cannot_take_a_limited_questionnaire(client):
    register_user(client, "owner@example.com")
    quiz = _quiz(client, attempts=1)
    _publish(client, quiz["id"])
    client.cookies.clear()
    response = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"})
    assert response.status_code in (401, 403)


def test_the_author_grants_one_more_run_and_can_take_it_back(client):
    register_user(client, "owner@example.com")
    quiz = _quiz(client, attempts=1)
    _publish(client, quiz["id"])
    candidate = register_user(client, "candidate@example.com")

    client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"}, headers=csrf_headers(client))
    blocked = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"}, headers=csrf_headers(client))
    assert blocked.status_code == 409

    login_user(client, "owner@example.com")
    grant = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts/{candidate['id']}/grant", headers=csrf_headers(client)
    )
    assert grant.status_code == 200, grant.text
    assert grant.json()["grants"] == 1

    login_user(client, "candidate@example.com")
    allowed = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"}, headers=csrf_headers(client))
    assert allowed.status_code == 201, allowed.text

    login_user(client, "owner@example.com")
    revoked = client.delete(
        f"/api/v1/quizzes/{quiz['id']}/attempts/{candidate['id']}/grant", headers=csrf_headers(client)
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["grants"] == 0


def test_the_result_book_lists_every_candidate_and_their_answers(client):
    register_user(client, "owner@example.com")
    quiz = _quiz(client, attempts=0)
    _publish(client, quiz["id"])

    register_user(client, "candidate@example.com", display_name="Camille")
    created = client.post(f"/api/v1/quizzes/{quiz['id']}/sessions", json={"mode": "solo"}, headers=csrf_headers(client))
    assert created.status_code == 201, created.text
    body = created.json()
    code = body["session"]["code"]
    token = body["participant"]["token"]
    state = client.get(f"/api/v1/sessions/{code}/state", headers={"x-participant-token": token}).json()
    question = state["question"]
    answered = client.post(
        f"/api/v1/sessions/{code}/answers",
        json={"question_id": question["id"], "option_ids": [question["options"][0]["id"]]},
        headers={**csrf_headers(client), "x-participant-token": token},
    )
    assert answered.status_code == 201, answered.text

    login_user(client, "owner@example.com")
    book = client.get(f"/api/v1/quizzes/{quiz['id']}/attempts")
    assert book.status_code == 200, book.text
    payload = book.json()
    assert payload["quiz"]["max_attempts"] == 0
    assert [candidate["candidate"] for candidate in payload["candidates"]] == ["Camille"]
    attempt = payload["attempts"][0]
    assert attempt["mode"] == "solo"
    assert attempt["answered"] == 1

    detail = client.get(f"/api/v1/quizzes/{quiz['id']}/attempts/{attempt['participant_id']}")
    assert detail.status_code == 200, detail.text
    items = detail.json()["items"]
    assert items and items[0]["answered"] is True


def test_a_non_owner_cannot_read_the_result_book(client):
    register_user(client, "owner@example.com")
    quiz = _quiz(client)
    _publish(client, quiz["id"])
    register_user(client, "candidate@example.com")
    response = client.get(f"/api/v1/quizzes/{quiz['id']}/attempts")
    assert response.status_code == 403


def test_the_private_link_opens_the_questionnaire_to_a_candidate(client):
    register_user(client, "owner@example.com")
    quiz = _quiz(client, attempts=1, public=False)
    share = client.post(f"/api/v1/quizzes/{quiz['id']}/share", headers=csrf_headers(client))
    assert share.status_code == 200, share.text
    token = share.json()["token"]
    assert share.json()["url"].endswith(f"/e/{token}")

    # The link is public information; the run is not.
    client.cookies.clear()
    overview = client.get(f"/api/v1/eval/{token}")
    assert overview.status_code == 200, overview.text
    assert overview.json()["title"] == quiz["title"]
    assert overview.json()["signed_in"] is False

    register_user(client, "candidate@example.com")
    overview = client.get(f"/api/v1/eval/{token}").json()
    assert overview["signed_in"] is True
    assert overview["remaining_attempts"] == 1

    started = client.post(f"/api/v1/eval/{token}/sessions", json={"mode": "solo"}, headers=csrf_headers(client))
    assert started.status_code == 201, started.text
    again = client.post(f"/api/v1/eval/{token}/sessions", json={"mode": "solo"}, headers=csrf_headers(client))
    assert again.status_code == 409


def test_revoking_the_link_closes_the_door(client):
    register_user(client, "owner@example.com")
    quiz = _quiz(client, public=False)
    token = client.post(f"/api/v1/quizzes/{quiz['id']}/share", headers=csrf_headers(client)).json()["token"]
    client.delete(f"/api/v1/quizzes/{quiz['id']}/share", headers=csrf_headers(client))
    client.cookies.clear()
    assert client.get(f"/api/v1/eval/{token}").status_code == 404


def test_an_unknown_token_is_a_plain_404(client):
    assert client.get("/api/v1/eval/not-a-real-token").status_code == 404


@pytest.mark.parametrize("attempts", [0, 1, 3])
def test_the_ceiling_is_stored_and_returned(client, attempts):
    register_user(client, "owner@example.com")
    quiz = _quiz(client, attempts=attempts)
    payload = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts-policy",
        json={"max_attempts": attempts},
        headers=csrf_headers(client),
    )
    assert payload.status_code == 200
    detail = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    assert detail["max_attempts"] == attempts
