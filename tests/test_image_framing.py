# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Framing a picture inside the area that shows it.

An illustration is rarely the shape of its frame. The author picks a focus point
and a zoom instead of choosing between "cropped to the centre" and "letterboxed":
`{"x": 34, "y": 62, "zoom": 1.6}` says which part of the picture stays visible.

Three promises are tested here:
  * what the author saved is what comes back, clamped to the allowed range;
  * no framing means no framing — every picture that existed before still shows
    whole, and nothing is invented on its behalf;
  * a game in progress keeps the framing it started with, like the wording.
"""

from __future__ import annotations

from tests.conftest import create_quiz, csrf_headers, question_payload, register_user


def illustrated_quiz(framing: dict | None) -> dict:
    question = question_payload("Where does this road lead?", image="/media/roads/fork.webp")
    question["image_framing"] = framing
    return {
        "title": "Framed",
        "description": "A questionnaire with one illustrated question.",
        "is_public": True,
        "questions": [question],
    }


def test_a_question_keeps_the_framing_its_author_chose(client):
    register_user(client)
    framing = {"x": 34, "y": 62, "zoom": 1.6}
    quiz = create_quiz(client, illustrated_quiz(framing))

    detail = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    assert detail["questions"][0]["image_framing"] == framing


def test_a_picture_without_framing_stays_whole(client):
    register_user(client)
    quiz = create_quiz(client, illustrated_quiz(None))

    detail = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    # No framing means what every picture written before this did: shown whole,
    # never a default centre crop.
    assert detail["questions"][0]["image_framing"] is None


def test_a_framing_outside_the_allowed_range_is_refused(client):
    register_user(client)
    response = client.post(
        "/api/v1/quizzes",
        json=illustrated_quiz({"x": -20, "y": 140, "zoom": 9}),
        headers=csrf_headers(client),
    )

    # The editor clamps before sending; a hand-written payload out of range is
    # an authoring error, and an out-of-range focus point means nothing.
    assert response.status_code == 422
    fields = {error["loc"][-1] for error in response.json()["detail"]}
    assert fields == {"x", "y", "zoom"}


def test_a_default_centred_framing_is_not_stored(client):
    register_user(client)
    quiz = create_quiz(client, illustrated_quiz({"x": 50, "y": 50, "zoom": 1}))

    # Centre, no zoom: this is what every legacy picture already does.
    assert client.get(f"/api/v1/quizzes/{quiz['id']}").json()["questions"][0]["image_framing"] is None


def test_a_running_game_keeps_the_framing_it_started_with(client):
    register_user(client)
    framing = {"x": 20, "y": 80, "zoom": 2}
    quiz = create_quiz(client, illustrated_quiz(framing))

    session = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions",
        json={"mode": "solo", "nickname": "Solo"},
        headers=csrf_headers(client),
    )
    assert session.status_code == 201, session.text
    code = session.json()["session"]["code"]

    # The author reframes the picture while the game is running.
    detail = client.get(f"/api/v1/quizzes/{quiz['id']}").json()
    payload = illustrated_quiz({"x": 70, "y": 30, "zoom": 1.2})
    payload["questions"][0]["options"] = [
        option for option in detail["questions"][0]["options"]
    ]
    updated = client.put(
        f"/api/v1/quizzes/{quiz['id']}", json=payload, headers=csrf_headers(client)
    )
    assert updated.status_code == 200, updated.text

    # The player's own view carries the frozen question.
    snapshot = client.get(
        f"/api/v1/sessions/{code}/state",
        headers={"x-participant-token": session.json()["participant"]["token"]},
    ).json()
    question = snapshot["question"]
    assert question["image_framing"] == framing


def test_a_card_frames_its_two_faces_independently(client):
    register_user(client, email="framing-cards@example.com")
    headers = csrf_headers(client)
    deck_id = client.post("/api/v1/decks", json={"title": "Portraits"}, headers=headers).json()["id"]

    created = client.post(
        f"/api/v1/decks/{deck_id}/cards",
        json={
            "front_md": "",
            "back_md": "Cheval de trait",
            "image_path": "/media/horses/breton.webp",
            "back_image_path": "/media/horses/breton-back.webp",
            "image_framing": {"x": 30, "y": 70, "zoom": 1.8},
            "back_image_framing": {"x": 65, "y": 40, "zoom": 2.2},
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    card = client.get(f"/api/v1/decks/{deck_id}").json()["cards"][0]
    assert card["image_framing"] == {"x": 30, "y": 70, "zoom": 1.8}
    assert card["back_image_framing"] == {"x": 65, "y": 40, "zoom": 2.2}

    # Clearing a face clears its framing with it.
    updated = client.put(
        f"/api/v1/decks/{deck_id}/cards/{card['id']}",
        json={"front_md": "Breton", "back_md": "Cheval de trait", "image_path": None},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["image_framing"] is None


def test_an_adventure_scene_carries_its_framing_into_the_run(client):
    from tests.test_adventure import create_adventure, start_run, story_payload

    register_user(client)
    payload = story_payload("Framed story")
    for node in payload["adventure"]["nodes"]:
        if node["key"] == "start":
            node["image_path"] = "/media/scenes/incident.webp"
            node["image_framing"] = {"x": 12, "y": 88, "zoom": 2.4}
    quiz = create_adventure(client, payload)

    assert quiz["adventure"]["nodes"][0]["image_framing"] == {"x": 12, "y": 88, "zoom": 2.4}

    run = start_run(client, quiz["id"])
    assert run["state"]["node"]["image_framing"] == {"x": 12, "y": 88, "zoom": 2.4}
