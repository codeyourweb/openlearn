# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""The closing screen belongs to the ending node, picture and words included.

A story's "step text" is the scene the reader lands on, and the outcome text is
the last paragraph. The ending screen used to render only the outcome, so an
author who illustrated their ending and wrote its scene saw neither: the picture
never appeared, and half of what they wrote was silently dropped. A death or a
victory has no ending node behind it, so it keeps showing the closing words
alone.
"""

from __future__ import annotations

from tests.conftest import register_user
from tests.test_adventure import create_adventure, start_run, story_payload


def illustrated_story(picture: str = "/media/endings/lead-illustration.webp") -> dict:
    """The stock story, whose ending node is illustrated."""
    payload = story_payload("A star for Santa")
    for node in payload["adventure"]["nodes"]:
        if node["key"] == "ending_lead":
            node["image_path"] = picture
    return payload


def play(client, token: str, choices: list[str]) -> dict:
    state: dict = {}
    for choice in choices:
        response = client.post(
            f"/api/v1/adventure/runs/{token}/choose", json={"choice": choice}
        )
        assert response.status_code == 200, response.text
        state = response.json()
    return state


def test_an_ending_shows_its_own_scene_and_picture(client):
    register_user(client)
    quiz = create_adventure(client, illustrated_story())
    token = start_run(client, quiz["id"])["run_token"]

    state = play(client, token, ["calm", "delegate"])
    assert state["finished"] is True
    ending = state["ending"]
    assert ending["kind"] == "node"
    assert ending["image_path"] == "/media/endings/lead-illustration.webp"
    assert "You lead the response." in ending["scene_html"]
    assert "You lead the response." in ending["scene_plain"]
    # The outcome stays the closing paragraph, distinct from the scene.
    assert ending["text_html"]
    assert ending["text_html"] != ending["scene_html"]


def test_an_unillustrated_ending_still_shows_its_scene(client):
    register_user(client)
    payload = story_payload("A star for Santa")
    for node in payload["adventure"]["nodes"]:
        node.pop("image_path", None)
    quiz = create_adventure(client, payload)
    token = start_run(client, quiz["id"])["run_token"]

    ending = play(client, token, ["calm", "delegate"])["ending"]
    assert ending["image_path"] is None
    assert "You lead the response." in ending["scene_html"]


def test_a_death_keeps_the_closing_words_alone(client):
    """A premature death has no ending node, so it must not borrow a scene."""
    register_user(client)
    quiz = create_adventure(client, illustrated_story())
    token = start_run(client, quiz["id"])["run_token"]

    ending = play(client, token, ["panic"])["ending"]
    assert ending["kind"] == "death"
    assert ending["scene_html"] == ""
    assert ending["scene_plain"] == ""
    assert ending["image_path"] is None
    assert "burned out" in ending["text_html"]
