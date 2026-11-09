# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""A questionnaire is read in the language the reader speaks.

The translations were stored and rendered by the editor, but nothing ever asked
for them: the player always saw the original wording. These tests pin the two
ends of the chain — the public page and the run itself.
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

TRANSLATED_QUESTION = "<p>Wie viele Server beantworten eine Anfrage?</p>"
TRANSLATED_ANSWERS = ["Einer", "Drei", "Keiner"]


def _quiz_with_translations(client: TestClient) -> dict:
    register_user(client, "translator@example.com")
    make_trusted(client)
    question = question_payload(
        "How many servers answer a query?",
        [("One", True), ("Three", False), ("None", False)],
    )
    question["translations"] = {"de": TRANSLATED_QUESTION}
    for option, text in zip(question["options"], TRANSLATED_ANSWERS, strict=True):
        option["translations"] = {"de": text}
    quiz = create_quiz(client, quiz_payload(questions=[question]))
    publish_quiz(client, quiz["id"])
    return quiz


def test_a_visitor_reads_the_questions_in_the_asked_language(client: TestClient) -> None:
    quiz = _quiz_with_translations(client)

    # Read as a visitor: the author keeps the original wording and the answer
    # key, whatever language the page is in.
    client.cookies.clear()
    german = client.get(f"/api/v1/quizzes/{quiz['id']}?lang=de")
    assert german.status_code == 200
    payload = german.json()
    assert payload["questions"][0]["text_html"] == TRANSLATED_QUESTION
    assert [option["text"] for option in payload["questions"][0]["options"]] == TRANSLATED_ANSWERS

    original = client.get(f"/api/v1/quizzes/{quiz['id']}?lang=fr").json()
    assert original["questions"][0]["text_html"] == "<p>How many servers answer a query?</p>"


def test_an_unknown_language_falls_back_instead_of_failing(client: TestClient) -> None:
    quiz = _quiz_with_translations(client)

    for query in ("?lang=xx", "?lang=", ""):
        response = client.get(f"/api/v1/quizzes/{quiz['id']}{query}")
        assert response.status_code == 200
        # The original wording, never an empty question.
        assert response.json()["questions"][0]["text_html"] == "<p>How many servers answer a query?</p>"


def test_a_run_is_played_in_the_language_it_was_started_in(client: TestClient) -> None:
    quiz = _quiz_with_translations(client)

    started = client.post(
        f"/api/v1/quizzes/{quiz['id']}/sessions",
        json={"mode": "solo", "language": "de", "nickname": "Leserin"},
        headers=csrf_headers(client),
    )
    assert started.status_code == 201, started.text
    body = started.json()
    code = body["session"]["code"]
    headers = {**csrf_headers(client), "X-Participant-Token": body["participant"]["token"]}

    client.post(f"/api/v1/sessions/{code}/start", headers={**csrf_headers(client), "X-Host-Token": body["host_token"]})
    state = client.get(f"/api/v1/sessions/{code}/state", headers=headers)
    assert state.status_code == 200, state.text
    question = state.json()["question"]
    # The run reads German and keeps the authored wording beside it: the same
    # payload serves a player who switches language without leaving the question.
    assert question["translations"]["de"] == TRANSLATED_QUESTION
    assert sorted(
        option["translations"]["de"] for option in question["options"]
    ) == sorted(TRANSLATED_ANSWERS)
    assert "How many servers answer a query" in question["text_html"]


def test_the_heading_is_in_the_language_the_reader_asked_for(client: TestClient) -> None:
    """A German card must not open an English page.

    The questions were translated, the heading was not: a reader who asked for
    German read German questions under an English title, in the catalogue and on
    the page it opened.
    """
    register_user(client, "heading@example.com")
    make_trusted(client)
    question = question_payload(
        "How many servers answer a query?",
        [("One", True), ("Three", False), ("None", False)],
    )
    question["translations"] = {"de": TRANSLATED_QUESTION}
    payload = quiz_payload("How DNS answers", questions=[question])
    payload["title_translations"] = {"de": "Wie DNS antwortet"}
    payload["description_translations"] = {"de": "Drei Fragen zur Namensauflösung."}
    quiz = create_quiz(client, payload)
    publish_quiz(client, quiz["id"])

    client.cookies.clear()
    page = client.get(f"/api/v1/quizzes/{quiz['id']}?lang=de").json()
    assert page["title"] == "Wie DNS antwortet"
    assert page["description"] == "Drei Fragen zur Namensauflösung."

    catalogue = client.get("/api/v1/quizzes?lang=de").json()
    card = next(item for item in catalogue if item["id"] == quiz["id"])
    assert card["title"] == "Wie DNS antwortet"

    original = client.get(f"/api/v1/quizzes/{quiz['id']}?lang=fr").json()
    assert original["title"] == "How DNS answers", "the original wording is never lost"
