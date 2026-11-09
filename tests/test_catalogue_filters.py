# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
"""Advanced search: a catalogue can be narrowed by type and by language.

The filter has two traps the tests below guard on purpose. A quiz is *available*
in a language when it was written in it **or** translated into it, which is stored
as a JSON array — so a quiz translated into `de` has to answer a `de` filter.
And the pagination header must count the filtered set: a pager that promises
pages the filter emptied sends the reader to a blank screen.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import (
    create_quiz,
    csrf_headers,
    publish_quiz,
    question_payload,
    quiz_payload,
    register_user,
)


def _publish(
    client: TestClient,
    *,
    title: str,
    mode: str = "qcm",
    lang: str = "en",
    translations: list[str] | None = None,
) -> dict:
    payload = quiz_payload(title)
    payload["mode"] = mode
    payload["default_language"] = lang
    if mode == "swipe":
        payload["questions"] = [
            question_payload("The horse is in the field.", [("Yes", True), ("No", False)]),
        ]
    if translations:
        payload["is_multilingual"] = True
        payload["title_translations"] = {code: f"{title} ({code})" for code in translations}
    quiz = create_quiz(client, payload)
    publish_quiz(client, quiz["id"])
    return quiz


def _titles(client: TestClient, query: str) -> tuple[list[str], int]:
    response = client.get(f"/api/v1/quizzes?{query}")
    assert response.status_code == 200, response.text
    return [row["title"] for row in response.json()], int(response.headers["X-Total-Count"])


def test_the_catalogue_can_be_narrowed_by_type(client: TestClient) -> None:
    register_user(client, "filter-type@example.com")
    qcm = _publish(client, title="A quiz", mode="qcm")
    swipe = _publish(client, title="A deck of cards", mode="swipe")

    titles, total = _titles(client, "mode=swipe")
    assert "A deck of cards" in titles
    assert "A quiz" not in titles
    assert total == len(titles) >= 1

    titles, _ = _titles(client, "mode=qcm")
    assert "A quiz" in titles
    assert "A deck of cards" not in titles

    # The two published ids are the ones the filters are supposed to separate.
    assert {qcm["id"], swipe["id"]}.isdisjoint({0})


def _ids(client: TestClient, query: str) -> tuple[list[int], int]:
    response = client.get(f"/api/v1/quizzes?{query}")
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()], int(response.headers["X-Total-Count"])


def test_a_language_filter_follows_the_translations(client: TestClient) -> None:
    register_user(client, "filter-lang@example.com")
    french = _publish(client, title="Written in French", lang="fr")
    english = _publish(client, title="Written in English", lang="en")
    translated = _publish(client, title="Translated into German", lang="en", translations=["de"])

    # Compared by id: the card is *written* in the language the reader asked for,
    # so the German catalogue shows the German title of the third quiz.
    ids, total = _ids(client, "lang=fr")
    assert french["id"] in ids
    assert english["id"] not in ids
    assert total == len(ids)

    # A translation makes the quiz reachable in that language too.
    ids, _ = _ids(client, "lang=de")
    assert translated["id"] in ids
    assert english["id"] not in ids

    cards = client.get("/api/v1/quizzes?lang=de").json()
    card = next(row for row in cards if row["id"] == translated["id"])
    assert card["title"] == "Translated into German (de)"


def test_type_and_language_narrow_together(client: TestClient) -> None:
    register_user(client, "filter-both@example.com")
    _publish(client, title="French cards", mode="swipe", lang="fr")
    _publish(client, title="French questions", mode="qcm", lang="fr")
    _publish(client, title="English cards", mode="swipe", lang="en")

    titles, total = _titles(client, "mode=swipe&lang=fr")
    assert titles == ["French cards"], titles
    assert total == 1


def test_an_unknown_type_is_refused_rather_than_ignored(client: TestClient) -> None:
    # Silently ignoring it would show the whole catalogue under a filter that
    # claims to be narrowing it.
    assert client.get("/api/v1/quizzes?mode=banana").status_code == 422


def test_the_wiki_list_can_be_narrowed_by_language(client: TestClient) -> None:
    register_user(client, "filter-wiki@example.com")
    for title, lang in (("Un wiki français", "fr"), ("An English wiki", "en")):
        created = client.post(
            "/api/v1/wiki",
            json={"title": title, "description": "", "default_language": lang},
            headers=csrf_headers(client),
        )
        assert created.status_code in (200, 201), created.text

    response = client.get("/api/v1/wiki?lang=fr")
    assert response.status_code == 200, response.text
    titles = [row["title"] for row in response.json()]
    assert "Un wiki français" in titles
    assert "An English wiki" not in titles
    assert int(response.headers["X-Total-Count"]) == len(titles)
