# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Search on an engine without FTS5.

The SQLite path uses FTS5; PostgreSQL and MariaDB have no such table, so every
query falls back to `LIKE`. That fallback was broken in a way SQLite could not
show: the missing-table statement aborted the transaction on PostgreSQL, and the
LIKE query that followed failed with "current transaction is aborted" — a 500 on
`/api/v1/quizzes?q=…`. The tests below force the fallback on SQLite by telling
`search._is_sqlite` that the engine is something else.
"""

from __future__ import annotations

import pytest

from app import search
from tests.conftest import csrf_headers


@pytest.fixture()
def no_fts(monkeypatch):
    monkeypatch.setattr(search, "_is_sqlite", lambda db: False)


def _rows(payload):
    """The catalogue answers a bare list; some builds wrap it in {"items": […] }."""
    return payload["items"] if isinstance(payload, dict) else payload


def _make_public_quiz(client, title="Photosynthesis for beginners"):
    client.post(
        "/api/v1/auth/register",
        json={"email": "search@example.com", "password": "TestingPassw0rd!", "display_name": "Search"},
    )
    headers = csrf_headers(client)
    created = client.post(
        "/api/v1/quizzes",
        json={
            "title": title,
            "description": "How plants eat light",
            "mode": "qcm",
            "is_public": True,
            "questions": [
                {
                    "text_html": "Which pigment captures light?",
                    "time_limit_seconds": 30,
                    "options": [
                        {"text": "Chlorophyll", "is_correct": True},
                        {"text": "Keratin", "is_correct": False},
                    ],
                }
            ],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_the_catalogue_still_searches_without_fts(client, no_fts):
    quiz_id = _make_public_quiz(client)
    # The author's own list goes through the same search path, without waiting
    # for a moderator to publish the quiz to the catalogue.
    response = client.get("/api/v1/quizzes/mine", params={"q": "photosynthesis"})
    assert response.status_code == 200, response.text
    ids = [row["id"] for row in _rows(response.json())]
    assert quiz_id in ids


def test_a_search_that_matches_nothing_is_empty_not_an_error(client, no_fts):
    _make_public_quiz(client)
    response = client.get("/api/v1/quizzes/mine", params={"q": "zzz-nothing-here"})
    assert response.status_code == 200, response.text
    assert _rows(response.json()) == []


def test_wiki_pages_are_searchable_without_fts(client, no_fts):
    client.post(
        "/api/v1/auth/register",
        json={"email": "wikisearch@example.com", "password": "TestingPassw0rd!", "display_name": "WS"},
    )
    wiki = client.post(
        "/api/v1/wiki",
        json={"title": "Marine biology", "description": "Life in the sea", "visibility": "public"},
        headers=csrf_headers(client),
    )
    assert wiki.status_code == 201, wiki.text
    wiki_id = wiki.json()["id"]
    page = client.post(
        f"/api/v1/wiki/{wiki_id}/pages",
        json={"title": "Coral reefs", "content_md": "Corals build reefs in warm shallow water."},
        headers=csrf_headers(client),
    )
    assert page.status_code == 201, page.text

    response = client.get("/api/v1/wiki/search", params={"q": "corals"})
    assert response.status_code == 200, response.text
    payload = response.json()
    rows = payload["pages"] if isinstance(payload, dict) else payload
    ids = [row["page_id"] for row in rows]
    assert page.json()["id"] in ids


def test_a_broken_fts_query_does_not_poison_the_session(client, monkeypatch):
    """A malformed MATCH rolls back and falls back, it does not return 500."""
    _make_public_quiz(client)
    monkeypatch.setattr(search, "fts_query", lambda raw: "broken:(")

    first = client.get("/api/v1/quizzes/mine", params={"q": "photosynthesis"})
    assert first.status_code == 200, first.text
    assert isinstance(_rows(first.json()), list)

    # The session is still usable: a second search answers normally.
    second = client.get("/api/v1/quizzes/mine", params={"q": "plants"})
    assert second.status_code == 200, second.text
