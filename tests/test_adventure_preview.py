# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""An author previews the story as it is now; a reader keeps the one they started.

The run owns a snapshot, which is what makes editing a story harmless to a
play-through already under way. That same snapshot is why an author reopening
their own preview used to see the version of an hour earlier — a replaced image
never appeared, and images added to later scenes never showed at all.
"""

from __future__ import annotations

from tests.conftest import csrf_headers, publish_quiz, register_user
from tests.test_adventure import create_adventure, start_run, story_payload


def illustrated_story(title: str = "A star for Santa") -> dict:
    """The stock story, with one picture on the first scene."""
    payload = story_payload(title)
    payload["adventure"]["nodes"][0]["image_path"] = "/media/first-version.webp"
    return payload


def update_story(client, quiz_id: int, payload: dict) -> dict:
    response = client.put(
        f"/api/v1/quizzes/{quiz_id}",
        json=payload,
        headers=csrf_headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_the_author_preview_follows_the_document(client):
    register_user(client)
    payload = illustrated_story()
    quiz = create_adventure(client, payload)
    created = start_run(client, quiz["id"])
    token = created["run_token"]
    assert created["state"]["node"]["image_path"] == "/media/first-version.webp"

    payload["adventure"]["nodes"][0]["image_path"] = "/media/second-version.webp"
    payload["adventure"]["nodes"][1]["image_path"] = "/media/second-scene.webp"
    update_story(client, quiz["id"], payload)

    resumed = client.get(f"/api/v1/adventure/runs/{token}")
    assert resumed.status_code == 200, resumed.text
    state = resumed.json()
    assert state["node"]["image_path"] == "/media/second-version.webp"

    walked = client.post(f"/api/v1/adventure/runs/{token}/choose", json={"choice": "calm"})
    assert walked.status_code == 200, walked.text
    assert walked.json()["node"]["image_path"] == "/media/second-scene.webp"


def test_the_author_keeps_their_place_and_their_counters(client):
    register_user(client)
    payload = illustrated_story()
    quiz = create_adventure(client, payload)
    token = start_run(client, quiz["id"])["run_token"]

    walked = client.post(f"/api/v1/adventure/runs/{token}/choose", json={"choice": "calm"})
    assert walked.status_code == 200, walked.text
    composure = {item["key"]: item["value"] for item in walked.json()["attributes"]}["composure"]
    assert composure == 7

    payload["adventure"]["nodes"][0]["text_html"] = "<p>An incident drops at 3am.</p>"
    update_story(client, quiz["id"], payload)

    resumed = client.get(f"/api/v1/adventure/runs/{token}").json()
    assert resumed["node"]["key"] == "calm"
    assert {item["key"]: item["value"] for item in resumed["attributes"]}["composure"] == 7


def test_a_reader_keeps_the_story_they_started(client):
    register_user(client)
    payload = illustrated_story()
    quiz = create_adventure(client, payload)
    publish_quiz(client, quiz["id"])
    assert client.post("/api/v1/auth/logout", headers=csrf_headers(client)).status_code in (200, 204)

    visitor = start_run(client, quiz["id"])
    assert visitor["state"]["node"]["image_path"] == "/media/first-version.webp"
    token = visitor["run_token"]

    from tests.conftest import login_user

    login_user(client, "player@example.com")
    payload["adventure"]["nodes"][0]["image_path"] = "/media/second-version.webp"
    update_story(client, quiz["id"], payload)
    assert client.post("/api/v1/auth/logout", headers=csrf_headers(client)).status_code in (200, 204)

    resumed = client.get(f"/api/v1/adventure/runs/{token}")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["node"]["image_path"] == "/media/first-version.webp"
