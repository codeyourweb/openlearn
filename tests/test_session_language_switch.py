# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)

"""A run keeps every language it was started with, so a player can switch.

Switching the interface language during a QCM used to leave the questions and the
answers in the language the run started in: the session had frozen one wording at
creation, and the only way to read the other one was to start the quiz again. The
snapshot now carries the authored text — the questionnaire's default language —
and the translations beside it, and the player resolves the wording its reader
asks for, falling back to the default.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import (
    create_quiz,
    csrf_headers,
    make_trusted,
    publish_quiz,
    question_payload,
    quiz_payload,
    register_user,
)


def create_solo_session(client: TestClient, quiz_id: int, language: str | None = None) -> dict:
    body = {"mode": "solo", "nickname": "Solo"}
    if language:
        body["language"] = language
    response = client.post(
        f"/api/v1/quizzes/{quiz_id}/sessions", json=body, headers=csrf_headers(client)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _bilingual_quiz(client: TestClient) -> dict:
    question = question_payload(
        "Combien de serveurs racine existe-t-il ?",
        [("Treize", True), ("Trois", False)],
    )
    question["translations"] = {"de": "<p>Wie viele Root-Server gibt es?</p>"}
    question["options"][0]["translations"] = {"de": "Dreizehn"}
    question["options"][1]["translations"] = {"de": "Drei"}
    payload = quiz_payload("DNS en français", questions=[question])
    payload["default_language"] = "fr"
    quiz = create_quiz(client, payload)
    publish_quiz(client, quiz["id"])
    return quiz


def test_the_snapshot_keeps_the_default_wording_and_every_translation(client):
    register_user(client, "bilingue@example.com")
    make_trusted(client)
    quiz = _bilingual_quiz(client)

    created = create_solo_session(client, quiz["id"])
    question = created["state"]["question"]

    # The authored text is the default language; translations sit beside it.
    assert "Combien de serveurs racine" in question["text_html"]
    assert question["translations"]["de"] == "<p>Wie viele Root-Server gibt es?</p>"
    german_options = {option["translations"].get("de") for option in question["options"]}
    assert german_options == {"Dreizehn", "Drei"}

    # Reading the same run again hands back the same question, ready to be painted
    # in another language without creating a second session.
    code = created["session"]["code"]
    token = created["participant"]["token"]
    again = client.get(
        f"/api/v1/sessions/{code}/state", headers={"X-Participant-Token": token}
    ).json()["question"]
    assert again["id"] == question["id"]
    assert again["translations"]["de"] == question["translations"]["de"]


def test_a_language_the_quiz_does_not_speak_falls_back_to_its_default(client):
    register_user(client, "bilingue@example.com")
    make_trusted(client)
    quiz = _bilingual_quiz(client)

    created = create_solo_session(client, quiz["id"], language="it")
    question = created["state"]["question"]

    # Italian was asked for and does not exist: the reader gets the questionnaire's
    # default language, never an empty card or the run's stale wording.
    assert "it" not in question["translations"]
    assert "Combien de serveurs racine" in question["text_html"]


def test_the_answer_sheet_follows_the_reader_s_language(client):
    register_user(client, "bilingue@example.com")
    make_trusted(client)
    quiz = _bilingual_quiz(client)

    created = create_solo_session(client, quiz["id"])
    code = created["session"]["code"]
    token = created["participant"]["token"]
    headers = {"X-Participant-Token": token}

    english = client.get(f"/api/v1/sessions/{code}/results?lang=de", headers=headers).json()
    question = english["questions"][0]
    assert "Wie viele Root-Server" in question["text_html"]
    assert "Dreizehn" in {option["text"] for option in question["options"]}

    default = client.get(f"/api/v1/sessions/{code}/results", headers=headers).json()
    assert "Combien de serveurs racine" in default["questions"][0]["text_html"]
